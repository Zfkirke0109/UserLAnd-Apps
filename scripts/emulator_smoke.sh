#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 || $# -gt 6 ]]; then
  echo "usage: $0 PACKAGE_ID OLD_APK NEW_APK EVIDENCE_DIR [VERSION_NAME] [API_LEVEL]" >&2
  exit 2
fi

PACKAGE_ID=$1
OLD_APK=$2
NEW_APK=$3
EVIDENCE_DIR=$4
EXPECTED_VERSION_NAME=${5:-2026.08.29-r3}
EXPECTED_CERTIFICATE='82:9A:55:6F:C5:8A:D5:24:9B:5D:4C:4A:7F:CB:9A:96:9C:FF:38:26:AA:5C:7E:41:02:C3:13:B2:20:A4:5F:EC'
API_LEVEL=${6:-${ANDROID_API_LEVEL:-35}}

REPOSITORY_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PAYLOAD_LOCK=${PAYLOAD_LOCK:-$REPOSITORY_ROOT/payloads.lock.json}
# The emulator matrix is x86_64, so that is the ABI whose payloads are pinned.
DEVICE_ABI=${DEVICE_ABI:-x86_64}
APP_FILES="/data/user/0/$PACKAGE_ID/files"

# A first run downloads a whole root filesystem, so the budget is generous; the
# waits below are driven by conditions, never by sleeping for the whole of it.
SETUP_TIMEOUT_SECONDS=${SETUP_TIMEOUT_SECONDS:-1800}
POLL_INTERVAL_SECONDS=${POLL_INTERVAL_SECONDS:-5}
DIALOG_SETTLE_SECONDS=${DIALOG_SETTLE_SECONDS:-3}
NETWORK_OUTAGE_SECONDS=${NETWORK_OUTAGE_SECONDS:-10}
RELAUNCH_SETTLE_SECONDS=${RELAUNCH_SETTLE_SECONDS:-20}
STABILITY_WINDOW_SECONDS=${STABILITY_WINDOW_SECONDS:-20}

note() {
  printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"
}
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
  adb shell dumpsys activity services "$PACKAGE_ID" \
    > "$EVIDENCE_DIR/services.txt" 2>&1 || true
  adb shell dumpsys notification --noredact \
    > "$EVIDENCE_DIR/notifications.txt" 2>&1 || true
  # Only if the journal was never captured while complete: overwriting the
  # snapshot with the emptied file on disk is how the last run lost the one
  # record that could explain it.
  if [[ ! -s "$EVIDENCE_DIR/download-journal.json" ]]; then
    adb shell cat "$APP_FILES/downloads/download-journal.json" \
      > "$EVIDENCE_DIR/download-journal.json" 2>/dev/null || true
  fi
  adb shell find "$APP_FILES" -maxdepth 3 \
    > "$EVIDENCE_DIR/app-files-tree.txt" 2>/dev/null || true
  # The journal is cleared once downloads are staged, so on an extraction
  # failure it can no longer say whether the archive arrived whole. Record what
  # is actually on disk: a short archive and a BusyBox that will not run produce
  # the same symptom otherwise.
  adb shell "find $APP_FILES -name 'rootfs.tar.gz' -exec ls -l {} \; 2>/dev/null" \
    > "$EVIDENCE_DIR/rootfs-archives.txt" 2>/dev/null || true
  adb shell "ls -l $APP_FILES/support/busybox_static $APP_FILES/support/proot 2>&1" \
    >> "$EVIDENCE_DIR/rootfs-archives.txt" 2>/dev/null || true
  adb shell "$APP_FILES/support/busybox_static --help 2>&1 | head -3" \
    >> "$EVIDENCE_DIR/rootfs-archives.txt" 2>/dev/null || true
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

read_package_pid() {
  adb shell pidof -s "$PACKAGE_ID" 2>/dev/null | tr -d '\r' || true
}

assert_no_app_crash() {
  adb logcat -b crash -d > "$EVIDENCE_DIR/crash-current.txt"
  adb logcat -d > "$EVIDENCE_DIR/logcat-current.txt"
  if ! python3 "$(dirname "$0")/../tools/assert_no_app_crash.py" \
      "$PACKAGE_ID" \
      "$EVIDENCE_DIR/crash-current.txt" \
      "$EVIDENCE_DIR/logcat-current.txt"
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
       [[ -n "$(read_package_pid)" ]]
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
  for stable_second in $(seq 1 "$STABILITY_WINDOW_SECONDS"); do
    current_pid=$(read_package_pid)
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
    if python3 "$(dirname "$0")/../tools/assert_visible_window.py" \
      "$EVIDENCE_DIR/runtime-permission-window.txt" \
      com.android.permissioncontroller
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
    if python3 "$(dirname "$0")/../tools/assert_visible_window.py" \
      "$EVIDENCE_DIR/all-files-settings-window.txt" \
      com.android.settings
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
[[ $new_name == *r3 ]] || fail "versionName does not end in r3"
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
pid=$(read_package_pid)
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
resumed_pid=$(read_package_pid)
[[ -n $resumed_pid ]] || fail "process missing after All Files Access return"
assert_no_app_crash
sleep 2
assert_no_app_crash


# ---------------------------------------------------------------- conditions

# Polls a condition instead of sleeping for a fixed download duration, and says
# so once a minute; a first run is long and a silent job looks hung.
wait_for_condition() {
  local description=$1 timeout=$2
  shift 2
  local waited=0
  while (( waited < timeout )); do
    if "$@"; then
      note "satisfied after ${waited}s: $description"
      return 0
    fi
    sleep "$POLL_INTERVAL_SECONDS"
    waited=$(( waited + POLL_INTERVAL_SECONDS ))
    if (( waited % 60 < POLL_INTERVAL_SECONDS )); then
      note "still waiting (${waited}s of ${timeout}s): $description"
      assert_no_forbidden_signatures
      # A minute of "still waiting" that says nothing about what the app is
      # doing is what made the last extraction timeout unanswerable.
      [[ -z $PROGRESS_HOOK ]] || "$PROGRESS_HOOK"
    fi
    # Setup asks for acknowledgement partway through, not only at the start:
    # low storage, feedback and contribution prompts are all modal, and a wait
    # that never clears them is waiting for a user who is not there.
    clear_blocking_dialog || true
  done
  [[ -z $PROGRESS_HOOK ]] || "$PROGRESS_HOOK"
  fail "timed out after ${timeout}s waiting for: $description"
}

# Named by wait_for_condition once a minute, so a long wait reports what the app
# is actually doing rather than only that it has not finished.
PROGRESS_HOOK=""

# Signatures that mean the run is already lost. Checked while waiting, so a
# crashed setup fails in seconds rather than at the end of the timeout.
assert_no_forbidden_signatures() {
  local log="$EVIDENCE_DIR/logcat-scan.txt"
  adb logcat -d > "$log" 2>&1 || true
  python3 "$REPOSITORY_ROOT/tools/assert_no_app_crash.py" "$PACKAGE_ID" "$log" \
    > "$EVIDENCE_DIR/crash-scan.txt" 2>&1 \
    || fail "app-scoped fatal, ANR or force-finish detected"

  # NoSessionSelectedWhenTransitionNecessary means setup lost the session it was
  # preparing and reset itself. Nothing crashes and no marker is written, so
  # without this the run just waits out its whole budget in silence.
  local forbidden
  forbidden=$(grep -nE \
    'CANNOT LINK EXECUTABLE|library ".*" not found|addNonRootUser\.sh: not found|IncorrectSessionTransition|NoSessionSelectedWhenTransitionNecessary' \
    "$log" || true)
  if [[ -n $forbidden ]]; then
    printf '%s\n' "$forbidden" > "$EVIDENCE_DIR/forbidden-signatures.txt"
    fail "forbidden runtime signature: $(head -1 <<< "$forbidden")"
  fi
}

device_file_exists() {
  [[ $(adb shell "test -e '$1' && echo yes" 2>/dev/null | tr -d '\r') == yes ]]
}

# ------------------------------------------------------------------ first run

# The app clears the journal as soon as it stages the downloads, so the gate
# gets exactly one chance to read it. Keep a copy the moment it reads COMPLETE:
# every later assertion works from that copy, never from the device again.
JOURNAL_SNAPSHOT="$EVIDENCE_DIR/download-journal.json"

journal_batch_state() {
  local raw state
  raw="$(adb shell cat "$APP_FILES/downloads/download-journal.json" 2>/dev/null || true)"
  [[ -n $raw ]] || { printf ''; return 0; }
  state="$(printf '%s' "$raw" | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("state", ""))
except Exception:
    print("")' 2>/dev/null || true)"
  state="${state//$'\r'/}"
  if [[ $state == COMPLETE ]]; then
    printf '%s' "$raw" > "$JOURNAL_SNAPSHOT"
  fi
  printf '%s' "$state"
}

downloads_are_complete() {
  [[ $(journal_batch_state) == COMPLETE ]]
}

extraction_succeeded() {
  [[ -n $(adb shell find "$APP_FILES" -name '.success_filesystem_extraction' -print -quit 2>/dev/null | tr -d '\r') ]]
}

extraction_failure_marker() {
  adb shell find "$APP_FILES" -name '.failure_filesystem_extraction' -print -quit 2>/dev/null \
    | tr -d '\r'
}

# The app records a verdict either way, so waiting out the full timeout for a
# success marker after it has already written a failure marker spends half an
# hour to learn nothing. Stop at the verdict and report the reason.
extraction_has_settled() {
  if extraction_succeeded; then
    return 0
  fi
  local marker
  marker=$(extraction_failure_marker)
  if [[ -n $marker ]]; then
    report_extraction_diagnosis
    fail "setup recorded an extraction failure at $marker"
  fi
  # Losing the session mid-setup has two exits. One logs an illegal state and is
  # caught as a forbidden signature; the other just posts
  # ProgressBarOperationComplete and resets, leaving nothing to find. Support
  # files are never cleared during a first run, so that state can only mean setup
  # ended here without ever attempting extraction.
  if adb logcat -d 2>/dev/null | grep -aq 'ProgressBarOperationComplete'; then
    report_extraction_diagnosis
    fail "setup ended without attempting extraction (it reset itself)"
  fi
  return 1
}

# Written to the job log, not only to the evidence bundle: the bundle is not
# always reachable when the diagnosis is needed.
report_extraction_diagnosis() {
  note "extraction diagnosis for $PACKAGE_ID"
  # Downloaded payloads keep their catalogue name, "<repo>-rootfs.tar.gz-<version>",
  # until they are staged. Matching the bare name saw neither the payload waiting
  # in downloads/ nor a partial one, and reported an empty disk that was not empty.
  note "  anything rootfs-shaped on disk:"
  adb shell "find $APP_FILES -name '*rootfs*' -exec ls -l {} \; 2>/dev/null" \
    | tr -d '\r' | sed 's/^/    /' || true
  note "  extraction markers:"
  adb shell "find $APP_FILES -name '.success_filesystem_extraction' \
    -o -name '.failure_filesystem_extraction' 2>/dev/null" \
    | tr -d '\r' | sed 's/^/    /' || true
  note "  app files tree:"
  adb shell "find $APP_FILES -maxdepth 2 2>/dev/null" \
    | tr -d '\r' | sed 's/^/    /' || true
  note "  entries unpacked under each filesystem root:"
  adb shell "for d in $APP_FILES/[0-9]*; do \
    [ -d \"\$d\" ] && echo \"\$d \$(find \"\$d\" | wc -l)\"; done 2>/dev/null" \
    | tr -d '\r' | sed 's/^/    /' || true
  note "  free storage (setup blocks on a dialog between 251MB and 1000MB free):"
  adb shell "df /data 2>/dev/null" | tr -d '\r' | sed 's/^/    /' || true
  # The failure is reported as an exit code, so read it here directly rather
  # than inferring it: this is the same command the app runs to validate the
  # archive before unpacking it.
  note "  host busybox reading the archive it must unpack:"
  adb shell "for a in \$(find $APP_FILES -name '*rootfs.tar.gz*' 2>/dev/null); do \
    b=\$(find $APP_FILES -name 'lib_busybox_static.so' -o -name 'busybox_static' \
      2>/dev/null | head -1); \
    [ -n \"\$b\" ] || b=busybox_static; \
    echo \"\$b tar -tzf \$a\"; \
    \$b tar -tzf \"\$a\" 2>&1 | head -3; \
    echo \"  exit \$?\"; done" \
    | tr -d '\r' | sed 's/^/    /' || true
  note "  busybox and tar processes:"
  adb shell "ps -A -o NAME 2>/dev/null | grep -iE 'busybox|tar|proot'" \
    | tr -d '\r' | sed 's/^/    /' || true
  # The state machine's own trace. Filtering on extraction words instead hid every
  # breadcrumb after the downloads began, which is exactly the part in question.
  note "  last state machine breadcrumbs:"
  adb logcat -d 2>/dev/null | grep -aE 'Breadcrumb|FSM' \
    | tail -25 | cut -c1-320 | sed 's/^/    /' || true
  note "  last app-scoped log lines:"
  adb logcat -d 2>/dev/null \
    | grep -aiE 'extract|rootfs|busybox|tar:|filesystem' \
    | grep -av 'Breadcrumb' \
    | tail -25 | cut -c1-320 | sed 's/^/    /' || true
}

# Every success marker must sit beside a filesystem that actually works. This is
# the r2 failure: a marker written over a filesystem that was never extracted.
assert_filesystem_anchors() {
  adb shell find "$APP_FILES" -name '.success_filesystem_extraction' 2>/dev/null \
    | tr -d '\r' > "$EVIDENCE_DIR/success-markers.txt"
  [[ -s "$EVIDENCE_DIR/success-markers.txt" ]] || fail "no extraction success marker was written"

  while read -r marker; do
    [[ -n $marker ]] || continue
    local support root
    support=$(dirname "$marker")
    root=$(dirname "$support")
    device_file_exists "$root/bin/sh" || fail "success marker without $root/bin/sh"
    device_file_exists "$root/etc/passwd" || fail "success marker without $root/etc/passwd"
    for anchor in nosudo userland_profile.sh ld.so.preload; do
      device_file_exists "$support/$anchor" || fail "success marker without support/$anchor"
    done
    note "filesystem anchors verified under $root"
  done < "$EVIDENCE_DIR/success-markers.txt"
}

assert_no_pending_transfers() {
  local pending
  pending=$(adb shell find "$APP_FILES" -name '*.part' -print 2>/dev/null | tr -d '\r')
  if [[ -n $pending ]]; then
    printf '%s\n' "$pending" > "$EVIDENCE_DIR/pending-parts.txt"
    fail "setup reported success with unfinished transfers: $pending"
  fi
}

# The journal records the digest each payload was verified against. Comparing it
# to the lock proves the bytes on the device are the bytes the release pinned.
assert_payload_digests_match_lock() {
  [[ -s "$JOURNAL_SNAPSHOT" ]] \
    || fail "no download journal was captured while the batch was complete"
  python3 "$REPOSITORY_ROOT/tools/assert_payload_digests.py" \
    --package "$PACKAGE_ID" \
    --abi "$DEVICE_ABI" \
    --lock "$PAYLOAD_LOCK" \
    --journal "$EVIDENCE_DIR/download-journal.json" \
    > "$EVIDENCE_DIR/payload-digest-report.txt" \
    || fail "downloaded payload digests do not match the release lock"
  note "payload digests match the release lock"
}

assert_session_is_ready() {
  adb shell dumpsys activity services "$PACKAGE_ID" \
    > "$EVIDENCE_DIR/services.txt" 2>&1 || true
  grep -q "ServiceRecord" "$EVIDENCE_DIR/services.txt" \
    || fail "no service record for $PACKAGE_ID after setup"
  grep -qE 'ServerService|AssetDownloadService' "$EVIDENCE_DIR/services.txt" \
    || fail "neither the session nor the download service ever ran"
  note "session service verified"
}

# Proves the transfer resumes rather than restarting: drop the network once
# mid-download and bring it back.
interrupt_network_once() {
  note "interrupting network to prove the transfer resumes"
  adb shell svc data disable >/dev/null 2>&1 || true
  adb shell svc wifi disable >/dev/null 2>&1 || true
  sleep "$NETWORK_OUTAGE_SECONDS"
  adb shell svc data enable >/dev/null 2>&1 || true
  adb shell svc wifi enable >/dev/null 2>&1 || true
  note "network restored"
}

# --------------------------------------------------------------- first-run ui

node_center() {
  local ui=$1
  shift
  python3 "$REPOSITORY_ROOT/tools/find_ui_node.py" "$ui" "$@"
}

tap_node() {
  local coordinates=$1
  local tap_x tap_y
  read -r tap_x tap_y <<< "$coordinates"
  adb shell input tap "$tap_x" "$tap_y"
}

# Dismisses whatever consent or credential dialog is on screen, if any.
tap_any_positive_dialog() {
  local ui="$EVIDENCE_DIR/dialog.xml"
  dump_ui "$ui"
  local coordinates
  coordinates=$(node_center "$ui" --resource-suffix ':id/button1' \
    --text OK --text Continue --text Yes --text Allow --text Start 2>/dev/null || true)
  if [[ -n $coordinates ]]; then
    tap_node "$coordinates"
    return 0
  fi
  return 1
}

# Nothing is dismissed silently: whatever the gate clears is recorded first, so
# a genuine error dialog cannot be tapped away without leaving a trace.
clear_blocking_dialog() {
  local ui="$EVIDENCE_DIR/blocking-dialog.xml"
  dump_ui "$ui" 2>/dev/null || return 1
  grep -q 'resource-id="android:id/button1"' "$ui" || return 1

  local text
  text=$(grep -o 'text="[^"]*"' "$ui" | sed 's/^text="//; s/"$//' \
    | grep -v '^$' | head -8 | paste -sd '|' -)
  printf '%s\n' "$text" >> "$EVIDENCE_DIR/dialogs-cleared.txt"

  # An acknowledgement the run can continue past is one thing; a failure report
  # is another. Tapping OK on "has entered an illegal state" dismissed the only
  # statement of what went wrong and left the gate waiting for a setup that had
  # already given up, which is what runs 5, 6 and 7 each spent their whole
  # budget doing.
  if [[ $text == *"illegal state"* || $text == *"Failed to extract"* ]]; then
    fail "setup reported a failure it cannot continue past: $text"
  fi

  note "clearing a dialog that is blocking setup: ${text:-no text}"
  tap_any_positive_dialog
}

start_setup_from_ui() {
  local ui=$1
  local coordinates
  coordinates=$(node_center "$ui" --package "$PACKAGE_ID" --first-clickable) \
    || fail "no clickable entry point in the app UI"
  note "starting setup from the app list"
  tap_node "$coordinates"

  # Consent, credentials and large-download prompts vary per app and per API, so
  # clear whatever appears rather than assuming a fixed sequence.
  local attempt
  for attempt in $(seq 1 8); do
    sleep "$DIALOG_SETTLE_SECONDS"
    tap_any_positive_dialog || true
    if [[ -n $(journal_batch_state) ]]; then
      note "setup started (download batch journalled)"
      return 0
    fi
  done
  note "no download batch appeared yet; continuing to wait by condition"
}

# ================================================================ first run
# Everything above proved the r2 upgrade and permission path. What follows is
# the path r2 never covered: a genuine clean install that has to download,
# verify, extract, and reach a usable session.

adb root >/dev/null 2>&1 || true
adb wait-for-device
# Without root the gate cannot read the app's private files, and an extraction
# it cannot inspect is an extraction it cannot vouch for.
[[ $(adb shell id -u 2>/dev/null | tr -d '\r') == 0 ]] \
  || fail "adb root unavailable; this gate cannot verify the app filesystem"

note "clearing app data for a clean first run"
adb shell pm clear "$PACKAGE_ID" >/dev/null
adb shell pm grant "$PACKAGE_ID" android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || true
adb shell appops set --uid "$PACKAGE_ID" MANAGE_EXTERNAL_STORAGE allow >/dev/null 2>&1 || true
if [[ $PACKAGE_ID == tech.ula.andacious ]]; then
  adb shell pm grant "$PACKAGE_ID" android.permission.RECORD_AUDIO >/dev/null 2>&1 || true
fi

adb logcat -c
adb shell am start -W -n "$launcher" > "$EVIDENCE_DIR/first-run-launch.txt"
wait_for_userland_activity
assert_no_forbidden_signatures

dump_ui "$EVIDENCE_DIR/first-run-ui.xml"
start_setup_from_ui "$EVIDENCE_DIR/first-run-ui.xml"

interrupt_network_once

wait_for_condition "every payload to download and verify" "$SETUP_TIMEOUT_SECONDS" \
  downloads_are_complete
assert_no_forbidden_signatures
assert_payload_digests_match_lock
# Checked here, while the download directory still exists. After extraction the
# app has cleared it, so a part file left behind could never be observed and the
# assertion would pass for the wrong reason.
assert_no_pending_transfers

PROGRESS_HOOK=report_extraction_diagnosis
wait_for_condition "the filesystem to finish extracting" "$SETUP_TIMEOUT_SECONDS" \
  extraction_has_settled
PROGRESS_HOOK=""

assert_no_forbidden_signatures
assert_filesystem_anchors
assert_session_is_ready
adb exec-out screencap -p > "$EVIDENCE_DIR/setup-complete.png" 2>/dev/null || true

note "relaunching to prove the finished filesystem is reused"
adb shell am force-stop "$PACKAGE_ID"
adb logcat -c
adb shell am start -W -n "$launcher" > "$EVIDENCE_DIR/relaunch.txt"
wait_for_userland_activity
sleep "$RELAUNCH_SETTLE_SECONDS"
assert_no_forbidden_signatures
assert_filesystem_anchors
assert_no_pending_transfers
adb exec-out screencap -p > "$EVIDENCE_DIR/relaunch.png" 2>/dev/null || true

printf 'Runtime verified for %s: %s -> %s (%s) on API %s\n' \
  "$PACKAGE_ID" "$old_version" "$new_version" "$new_name" "$API_LEVEL" \
  | tee "$EVIDENCE_DIR/result.txt"
