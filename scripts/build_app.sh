#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 APP_ID VERSION_CODE VERSION_NAME" >&2
  exit 2
fi

APP_ID=$1
VERSION_CODE=$2
VERSION_NAME=$3
REPOSITORY_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SHARED_ROOT=${ULA_SHARED_ROOT:-$REPOSITORY_ROOT/build/shared}
: "${RUNNER_TEMP:?RUNNER_TEMP must be set}"

if [[ ! $VERSION_CODE =~ ^[0-9]+$ ]] || \
   (( VERSION_CODE < 2000000000 || VERSION_CODE > 2100000000 )); then
  echo "version code must be between 2000000000 and 2100000000" >&2
  exit 1
fi
if [[ -z $VERSION_NAME ]]; then
  echo "version name must not be empty" >&2
  exit 1
fi

python3 "$REPOSITORY_ROOT/tools/validate_contract.py"
python3 "$REPOSITORY_ROOT/tools/verify_dependency_tree.py" "$SHARED_ROOT"

APP_RECORD=$(python3 - "$REPOSITORY_ROOT/sources.lock.json" "$APP_ID" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    apps = json.load(source)["apps"]
matches = [app for app in apps if app["id"] == sys.argv[2]]
if len(matches) != 1:
    raise SystemExit(f"expected one app record for {sys.argv[2]}, found {len(matches)}")
app = matches[0]
print(app["profile"])
print(app["output_name"])
PY
)
mapfile -t APP_FIELDS <<< "$APP_RECORD"
PROFILE=${APP_FIELDS[0]}
OUTPUT_NAME=${APP_FIELDS[1]}

WORK_DIR=$(mktemp -d "$RUNNER_TEMP/userland-app-${APP_ID}.XXXXXX")
rsync -a "$REPOSITORY_ROOT/apps/$APP_ID/" "$WORK_DIR/"
rsync -a --exclude='.git' "$SHARED_ROOT/UserLAndLibrary/" "$WORK_DIR/UserLAndLibrary/"

python3 "$REPOSITORY_ROOT/tools/apply_compat.py" \
  --root "$WORK_DIR" \
  --profile "$REPOSITORY_ROOT/profiles/$PROFILE.json"
install -m 0644 "$REPOSITORY_ROOT/build-logic/signing.gradle" "$WORK_DIR/signing.gradle"

python3 - "$WORK_DIR/build.gradle" "$WORK_DIR/app/build.gradle" <<'PY'
import re
import sys
from pathlib import Path

root_path = Path(sys.argv[1])
root_text = root_path.read_text(encoding="utf-8")
code_pattern = re.compile(r"^\s*appVersionCode\s*=.*$", re.MULTILINE)
name_pattern = re.compile(r"^\s*appVersionName\s*=.*$", re.MULTILINE)
if len(code_pattern.findall(root_text)) != 1:
    raise SystemExit("expected exactly one appVersionCode assignment")
if len(name_pattern.findall(root_text)) != 1:
    raise SystemExit("expected exactly one appVersionName assignment")
root_text = code_pattern.sub(
    "        appVersionCode = Integer.parseInt(project.property('ulaVersionCode').toString())",
    root_text,
)
root_text = name_pattern.sub(
    "        appVersionName = project.property('ulaVersionName').toString()",
    root_text,
)
root_path.write_text(root_text, encoding="utf-8")

app_path = Path(sys.argv[2])
app_text = app_path.read_text(encoding="utf-8")
anchor = "}\n\nandroid {"
if app_text.count(anchor) != 1:
    raise SystemExit("expected exactly one app Android plugin anchor")
app_path.write_text(
    app_text.replace(
        anchor,
        "}\n\napply from: rootProject.file('signing.gradle')\n\nandroid {",
        1,
    ),
    encoding="utf-8",
)
PY

(
  cd "$WORK_DIR"
  chmod 0755 gradlew
  ./gradlew :app:tasks \
    -PulaVersionCode="$VERSION_CODE" \
    -PulaVersionName="$VERSION_NAME" \
    --no-daemon \
    --stacktrace >/dev/null
  ./gradlew :app:assembleRelease \
    -PulaVersionCode="$VERSION_CODE" \
    -PulaVersionName="$VERSION_NAME" \
    --no-daemon \
    --stacktrace
)

mapfile -d '' APKS < <(
  find "$WORK_DIR/app/build/outputs/apk/release" -type f -name '*.apk' -print0
)
if [[ ${#APKS[@]} -ne 1 ]]; then
  echo "expected exactly one release APK, found ${#APKS[@]}" >&2
  exit 1
fi
mkdir -p "$REPOSITORY_ROOT/dist"
install -m 0644 "${APKS[0]}" "$REPOSITORY_ROOT/dist/$OUTPUT_NAME"
printf 'Built %s\n' "$REPOSITORY_ROOT/dist/$OUTPUT_NAME"
