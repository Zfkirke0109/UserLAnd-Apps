#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 LOCK OUTPUT CACHE" >&2
  exit 2
fi

LOCK_FILE=$(realpath "$1")
OUTPUT_DIR=$(realpath -m "$2")
CACHE_DIR=$(realpath -m "$3")
REPOSITORY_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

read_lock() {
  python3 - "$LOCK_FILE" "$1" "$2" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    data = json.load(source)
print(data[sys.argv[2]][sys.argv[3]])
PY
}

clone_locked() {
  local repository=$1
  local revision=$2
  local destination=$3
  git init --quiet "$destination"
  git -C "$destination" remote add origin "https://github.com/${repository}.git"
  git -C "$destination" fetch --quiet --depth=1 origin "$revision"
  git -C "$destination" checkout --quiet --detach FETCH_HEAD
  test "$(git -C "$destination" rev-parse HEAD)" = "$revision"
}

validate_archive() {
  local archive_path=$1
  test -s "$archive_path" &&
    printf '%s  %s\n' "$NATIVE_SHA256" "$archive_path" | sha256sum --check --status &&
    gzip -t "$archive_path" &&
    tar -tzf "$archive_path" >/dev/null
}

if [[ -e "$OUTPUT_DIR" ]] && [[ -n "$(find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo "output directory must be empty: $OUTPUT_DIR" >&2
  exit 1
fi
mkdir -p "$OUTPUT_DIR" "$CACHE_DIR"

USERLAND_REPOSITORY=$(read_lock userland_library repository)
USERLAND_REF=$(read_lock userland_library ref)
CLIENTS_REPOSITORY=$(read_lock remote_desktop_clients repository)
CLIENTS_REF=$(read_lock remote_desktop_clients ref)
TERMUX_REPOSITORY=$(read_lock termux_app repository)
TERMUX_REF=$(read_lock termux_app ref)
FREERDP_REPOSITORY=$(read_lock freerdp repository)
FREERDP_REF=$(read_lock freerdp ref)
NATIVE_URL=$(read_lock native_archive url)
NATIVE_SHA256=$(read_lock native_archive sha256)

USERLAND_DIR="$OUTPUT_DIR/UserLAndLibrary"
CLIENTS_DIR="$USERLAND_DIR/remote-desktop-clients"
TERMUX_DIR="$USERLAND_DIR/termux-app"
FREERDP_SOURCE="$OUTPUT_DIR/freerdp-source"

clone_locked "$USERLAND_REPOSITORY" "$USERLAND_REF" "$USERLAND_DIR"
clone_locked "$CLIENTS_REPOSITORY" "$CLIENTS_REF" "$CLIENTS_DIR"
clone_locked "$TERMUX_REPOSITORY" "$TERMUX_REF" "$TERMUX_DIR"

ARCHIVE="$CACHE_DIR/${NATIVE_SHA256}-remote-desktop-clients-libs-1.tar.gz"
PART_ARCHIVE="${ARCHIVE}.part"
trap 'rm -f "$PART_ARCHIVE"' EXIT

if ! validate_archive "$ARCHIVE"; then
  rm -f "$ARCHIVE" "$PART_ARCHIVE"
  for attempt in 1 2 3 4 5; do
    rm -f "$PART_ARCHIVE"
    if curl \
      --fail \
      --location \
      --show-error \
      --connect-timeout 20 \
      --max-time 300 \
      --output "$PART_ARCHIVE" \
      "$NATIVE_URL" && validate_archive "$PART_ARCHIVE"
    then
      mv "$PART_ARCHIVE" "$ARCHIVE"
      break
    fi
    if [[ $attempt -eq 5 ]]; then
      echo "dependency download failed validation after $attempt attempts" >&2
      exit 1
    fi
    delay=$((2 ** (attempt - 1)))
    echo "dependency download attempt $attempt failed; retrying in ${delay}s" >&2
    sleep "$delay"
  done
fi
validate_archive "$ARCHIVE"

install -m 0644 "$ARCHIVE" "$CLIENTS_DIR/remote-desktop-clients-libs-1.tar.gz"
(
  cd "$CLIENTS_DIR"
  TAR_OPTIONS=--no-same-owner bash ./download-prebuilt-dependencies.sh
)

test -f "$CLIENTS_DIR/FreeRDP/client/Android/Studio/freeRDPCore/build.gradle"
FREERDP_DESTINATION="$CLIENTS_DIR/remoteClientLib/jni/libs/deps/FreeRDP"
mkdir -p "$FREERDP_DESTINATION"
rsync -a "$CLIENTS_DIR/FreeRDP/" "$FREERDP_DESTINATION/"

clone_locked "$FREERDP_REPOSITORY" "$FREERDP_REF" "$FREERDP_SOURCE"
rsync -a --exclude='.git' "$FREERDP_SOURCE/" "$FREERDP_DESTINATION/"

python3 "$REPOSITORY_ROOT/tools/verify_dependency_tree.py" "$OUTPUT_DIR"
