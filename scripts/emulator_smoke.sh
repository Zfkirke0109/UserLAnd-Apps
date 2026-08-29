#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "usage: $0 PACKAGE_ID OLD_APK NEW_APK [EVIDENCE_DIR]" >&2
  exit 2
fi

PACKAGE_ID=$1
OLD_APK=$2
NEW_APK=$3
EVIDENCE_DIR=${4:-evidence/$PACKAGE_ID}
mkdir -p "$EVIDENCE_DIR"

capture_evidence() {
  adb logcat -d > "$EVIDENCE_DIR/logcat.txt" 2>&1 || true
  adb shell dumpsys package "$PACKAGE_ID" \
    > "$EVIDENCE_DIR/final-package.txt" 2>&1 || true
}
trap capture_evidence EXIT

read_version_code() {
  sed -n 's/.*versionCode=\([0-9][0-9]*\).*/\1/p' | head -1
}

adb wait-for-device
adb uninstall "$PACKAGE_ID" >/dev/null 2>&1 || true
adb logcat -c

adb install "$OLD_APK"
old_dump=$(adb shell dumpsys package "$PACKAGE_ID")
printf '%s\n' "$old_dump" > "$EVIDENCE_DIR/old-package.txt"
old_version=$(read_version_code <<< "$old_dump")
if [[ -z $old_version ]]; then
  echo "old installed versionCode not found" >&2
  exit 1
fi

launcher=$(adb shell cmd package resolve-activity \
  --brief \
  -a android.intent.action.MAIN \
  -c android.intent.category.LAUNCHER \
  "$PACKAGE_ID" | tr -d '\r' | tail -1)
if [[ $launcher != */* ]]; then
  echo "launcher activity was not resolved: $launcher" >&2
  exit 1
fi
printf '%s\n' "$launcher" > "$EVIDENCE_DIR/launcher.txt"
adb shell monkey \
  -p "$PACKAGE_ID" \
  -c android.intent.category.LAUNCHER \
  1

adb install -r "$NEW_APK"
new_dump=$(adb shell dumpsys package "$PACKAGE_ID")
printf '%s\n' "$new_dump" > "$EVIDENCE_DIR/new-package.txt"
new_version=$(read_version_code <<< "$new_dump")
if [[ -z $new_version ]]; then
  echo "new installed versionCode not found" >&2
  exit 1
fi
if (( new_version <= old_version )); then
  echo "upgrade versionCode did not increase: $old_version -> $new_version" >&2
  exit 1
fi

adb logcat -d > "$EVIDENCE_DIR/logcat.txt"
if grep -E 'PackageManager.*signature mismatch|INSTALL_FAILED_UPDATE_INCOMPATIBLE' \
  "$EVIDENCE_DIR/logcat.txt"
then
  echo "signature-incompatible upgrade found in logcat" >&2
  exit 1
fi
printf 'Upgrade verified for %s: %s -> %s\n' \
  "$PACKAGE_ID" "$old_version" "$new_version"
