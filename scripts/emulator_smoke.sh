#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 || $# -gt 5 ]]; then
  echo "usage: $0 PACKAGE_ID OLD_APK NEW_APK EVIDENCE_DIR [EXPECTED_VERSION_NAME]" >&2
  exit 2
fi

PACKAGE_ID=$1
OLD_APK=$2
NEW_APK=$3
EVIDENCE_DIR=$4
EXPECTED_VERSION_NAME=${5:-2026.08.29-r2}
EXPECTED_CERTIFICATE='82:9A:55:6F:C5:8A:D5:24:9B:5D:4C:4A:7F:CB:9A:96:9C:FF:38:26:AA:5C:7E:41:02:C3:13:B2:20:A4:5F:EC'
mkdir -p "$EVIDENCE_DIR"

fail() {
  echo "runtime verification failed: $*" >&2
  exit 1
}

capture_evidence() {
  adb logcat -d > "$EVIDENCE_DIR/logcat.txt" 2>&1 || true
  adb logcat -b crash -d > "$EVIDENCE_DIR/crash-buffer.txt" 2>&1 || true
  adb shell dumpsys activity activities > "$EVIDENCE_DIR/activity.txt" 2>&1 || true
  adb shell dumpsys window windows > "$EVIDENCE_DIR/window.txt" 2>&1 || true
  adb shell dumpsys package "$PACKAGE_ID" \
    > "$EVIDENCE_DIR/final-package.txt" 2>&1 || true
  adb shell cmd appops get "$PACKAGE_ID" \
    > "$EVIDENCE_DIR/appops.txt" 2>&1 || true
  aapt dump permissions "$NEW_APK" \
    > "$EVIDENCE_DIR/permissions.txt" 2>&1 || true
  aapt dump xmltree "$NEW_APK" AndroidManifest.xml \
    > "$EVIDENCE_DIR/manifest-tree.txt" 2>&1 || true
  adb exec-out screencap -p > "$EVIDENCE_DIR/screenshot.png" 2>/dev/null || true
  adb shell uiautomator dump /sdcard/userland-window.xml >/dev/null 2>&1 || true
  adb pull /sdcard/userland-window.xml "$EVIDENCE_DIR/ui.xml" >/dev/null 2>&1 || true
}
trap capture_evidence EXIT

read_version_code() {
  sed -n 's/.*versionCode=\([0-9][0-9]*\).*/\1/p' | head -1
}

read_version_name() {
  sed -n 's/.*versionName=\([^[:space:]]*\).*/\1/p' | head -1
}

assert_no_app_crash() {
  adb logcat -b crash -d > "$EVIDENCE_DIR/crash-current.txt"
  adb logcat -d > "$EVIDENCE_DIR/logcat-current.txt"
  if grep -Eq 'FATAL EXCEPTION|AndroidRuntime|ANR in|Force finishing activity' \
      "$EVIDENCE_DIR/crash-current.txt" "$EVIDENCE_DIR/logcat-current.txt" &&
     grep -Eq "$PACKAGE_ID|tech\.ula\.library" \
      "$EVIDENCE_DIR/crash-current.txt" "$EVIDENCE_DIR/logcat-current.txt"
  then
    fail "app-scoped fatal exception, ANR, or force-finish found"
  fi
}

wait_for_userland_activity() {
  for attempt in $(seq 1 30); do
    adb shell dumpsys activity activities > "$EVIDENCE_DIR/activity-current.txt"
    if grep -Eq \
      "$PACKAGE_ID/tech\.ula\.library\.MainActivity|tech\.ula\.library/\.MainActivity" \
      "$EVIDENCE_DIR/activity-current.txt" &&
       [[ -n "$(adb shell pidof -s "$PACKAGE_ID" | tr -d '\r')" ]]
    then
      return 0
    fi
    assert_no_app_crash
    sleep 1
  done
  fail "tech.ula.library.MainActivity did not become visible"
}

assert_stable_process() {
  local expected_pid=$1
  : > "$EVIDENCE_DIR/pid-stability.txt"
  for stable_second in $(seq 1 20); do
    current_pid=$(adb shell pidof -s "$PACKAGE_ID" | tr -d '\r')
    printf '%s %s\n' "$stable_second" "$current_pid" \
      >> "$EVIDENCE_DIR/pid-stability.txt"
    if [[ -z $current_pid || $current_pid != "$expected_pid" ]]; then
      fail "process died during stability window"
    fi
    assert_no_app_crash
    sleep 1
  done
}

dump_ui() {
  local output=$1
  adb shell uiautomator dump /sdcard/userland-window.xml >/dev/null
  adb pull /sdcard/userland-window.xml "$output" >/dev/null
}

assert_visible_app_ui() {
  local ui="$EVIDENCE_DIR/ui.xml"
  dump_ui "$ui"
  python3 - "$ui" "$PACKAGE_ID" <<'PY'
import sys
from xml.etree import ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
package = sys.argv[2]
visible = [
    node for node in root.iter("node")
    if node.get("package") == package
    and node.get("bounds") not in (None, "[0,0][0,0]")
]
if not visible:
    raise SystemExit(f"no visible UI nodes belong to {package}")
if not any(
    node.get("text") or node.get("content-desc") or node.get("resource-id")
    for node in visible
):
    raise SystemExit(f"visible UI for {package} has no usable content")
PY
}

tap_positive_dialog() {
  local ui="$EVIDENCE_DIR/permission-rationale.xml"
  dump_ui "$ui"
  coordinates=$(python3 - "$ui" <<'PY'
import re
import sys
from xml.etree import ElementTree as ET

for node in ET.parse(sys.argv[1]).getroot().iter("node"):
    resource = node.get("resource-id", "")
    text = node.get("text", "")
    if resource.endswith(":id/button1") or text in {"OK", "Continue"}:
        bounds = node.get("bounds", "")
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if match:
            x1, y1, x2, y2 = map(int, match.groups())
            print((x1 + x2) // 2, (y1 + y2) // 2)
            raise SystemExit(0)
raise SystemExit("positive permission rationale button not found")
PY
)
  read -r tap_x tap_y <<< "$coordinates"
  adb shell input tap "$tap_x" "$tap_y"
}

wait_for_permission_controller() {
  for attempt in $(seq 1 20); do
    adb shell dumpsys window windows > "$EVIDENCE_DIR/runtime-permission-window.txt"
    if grep -Eq 'mCurrentFocus.*permissioncontroller|mFocusedApp.*permissioncontroller' \
      "$EVIDENCE_DIR/runtime-permission-window.txt"
    then
      dump_ui "$EVIDENCE_DIR/runtime-permission.xml"
      return 0
    fi
    assert_no_app_crash
    sleep 1
  done
  fail "runtime permission controller did not appear"
}

wait_for_all_files_settings() {
  for attempt in $(seq 1 20); do
    adb shell dumpsys window windows > "$EVIDENCE_DIR/all-files-settings-window.txt"
    if grep -Eq 'mCurrentFocus.*com\.android\.settings|mFocusedApp.*com\.android\.settings' \
      "$EVIDENCE_DIR/all-files-settings-window.txt"
    then
      dump_ui "$EVIDENCE_DIR/all-files-settings.xml"
      return 0
    fi
    assert_no_app_crash
    sleep 1
  done
  fail "All Files Access settings did not appear"
}

assert_apk_contract() {
  aapt dump permissions "$NEW_APK" > "$EVIDENCE_DIR/permissions.txt"
  for permission in \
    android.permission.POST_NOTIFICATIONS \
    android.permission.MANAGE_EXTERNAL_STORAGE \
    android.permission.FOREGROUND_SERVICE_SPECIAL_USE
  do
    grep -F "$permission" "$EVIDENCE_DIR/permissions.txt" >/dev/null ||
      fail "missing APK permission: $permission"
  done
  if grep -F 'android.permission.CAMERA' "$EVIDENCE_DIR/permissions.txt"; then
    fail "camera permission is present despite USES_CAMERA=false"
  fi
  if [[ $PACKAGE_ID == tech.ula.andacious ]]; then
    grep -F 'android.permission.RECORD_AUDIO' "$EVIDENCE_DIR/permissions.txt" >/dev/null ||
      fail "Andacious microphone permission is missing"
  elif grep -F 'android.permission.RECORD_AUDIO' "$EVIDENCE_DIR/permissions.txt"; then
    fail "microphone permission is present for a non-audio launcher"
  fi

  certificate=$(apksigner verify --verbose --print-certs "$NEW_APK" |
    sed -n 's/^Signer #1 certificate SHA-256 digest: //p' | head -1)
  expected=$(tr -d ':' <<< "$EXPECTED_CERTIFICATE" | tr '[:upper:]' '[:lower:]')
  actual=$(tr -d ':' <<< "$certificate" | tr '[:upper:]' '[:lower:]')
  [[ $actual == "$expected" ]] || fail "APK signing certificate mismatch"
}

adb wait-for-device
adb uninstall "$PACKAGE_ID" >/dev/null 2>&1 || true
adb install "$OLD_APK"
old_dump=$(adb shell dumpsys package "$PACKAGE_ID")
printf '%s\n' "$old_dump" > "$EVIDENCE_DIR/old-package.txt"
old_version=$(read_version_code <<< "$old_dump")
[[ -n $old_version ]] || fail "old installed versionCode not found"

adb install -r "$NEW_APK"
new_dump=$(adb shell dumpsys package "$PACKAGE_ID")
printf '%s\n' "$new_dump" > "$EVIDENCE_DIR/new-package.txt"
new_version=$(read_version_code <<< "$new_dump")
new_name=$(read_version_name <<< "$new_dump")
[[ -n $new_version ]] || fail "new installed versionCode not found"
(( new_version > old_version )) ||
  fail "upgrade versionCode did not increase: $old_version -> $new_version"
[[ $new_name == "$EXPECTED_VERSION_NAME" ]] ||
  fail "versionName mismatch: $new_name != $EXPECTED_VERSION_NAME"
[[ $new_name == *r2 ]] || fail "versionName does not end in r2"
assert_apk_contract

launcher=$(adb shell cmd package resolve-activity \
  --brief \
  -a android.intent.action.MAIN \
  -c android.intent.category.LAUNCHER \
  "$PACKAGE_ID" | tr -d '\r' | tail -1)
[[ $launcher == */* ]] || fail "launcher activity was not resolved: $launcher"
printf '%s\n' "$launcher" > "$EVIDENCE_DIR/launcher.txt"

adb shell appops set --uid "$PACKAGE_ID" MANAGE_EXTERNAL_STORAGE deny
adb shell pm revoke "$PACKAGE_ID" android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || true
if [[ $PACKAGE_ID == tech.ula.andacious ]]; then
  adb shell pm revoke "$PACKAGE_ID" android.permission.RECORD_AUDIO >/dev/null 2>&1 || true
fi
adb shell am force-stop "$PACKAGE_ID"
adb logcat -c
adb shell am start -W -n "$launcher" > "$EVIDENCE_DIR/launch-result.txt"
wait_for_userland_activity
pid=$(adb shell pidof -s "$PACKAGE_ID" | tr -d '\r')
[[ -n $pid ]] || fail "package PID missing after cold launch"
assert_stable_process "$pid"
assert_visible_app_ui

# Prove the in-context session path requests runtime access.
tap_positive_dialog
wait_for_permission_controller
adb shell pm grant "$PACKAGE_ID" android.permission.POST_NOTIFICATIONS
if [[ $PACKAGE_ID == tech.ula.andacious ]]; then
  adb shell pm grant "$PACKAGE_ID" android.permission.RECORD_AUDIO
fi

# Relaunch with runtime access granted and prove the special-access handoff/recheck.
adb shell am force-stop "$PACKAGE_ID"
adb shell appops set --uid "$PACKAGE_ID" MANAGE_EXTERNAL_STORAGE deny
adb logcat -c
adb shell am start -W -n "$launcher" > "$EVIDENCE_DIR/special-access-launch.txt"
wait_for_userland_activity
tap_positive_dialog
wait_for_all_files_settings
adb shell appops set --uid "$PACKAGE_ID" MANAGE_EXTERNAL_STORAGE allow
adb shell input keyevent 4
wait_for_userland_activity
resumed_pid=$(adb shell pidof -s "$PACKAGE_ID" | tr -d '\r')
[[ -n $resumed_pid ]] || fail "process missing after All Files Access return"
assert_no_app_crash
sleep 2
assert_no_app_crash

printf 'Runtime verified for %s: %s -> %s (%s)\n' \
  "$PACKAGE_ID" "$old_version" "$new_version" "$new_name"
