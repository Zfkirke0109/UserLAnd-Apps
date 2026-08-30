#!/usr/bin/env python3
"""A scriptable stand-in for adb, so the emulator gate can be run without one.

The gate is a long shell script whose whole job is to refuse a broken first run.
Asserting on its source text only proves the words are present; running it
against a simulated device proves it actually fails when the device is wrong.
The scenario is a JSON file named by FAKE_DEVICE.
"""
import json
import os
import re
import sys
from pathlib import Path

scenario = json.loads(Path(os.environ["FAKE_DEVICE"]).read_text(encoding="utf-8"))
root = Path(os.environ["FAKE_DEVICE_ROOT"])
argv = sys.argv[1:]
joined = " ".join(argv)


# Both the runtime-permission controller and the All Files settings screen are
# reported visible, so the r2 permission handoff runs to completion.
VISIBLE_WINDOWS = """  Window #0 Window{aaaa u0 com.android.permissioncontroller/GrantActivity}:
    mViewVisibility=0x0 mHasSurface=true isReadyForDisplay()=true
  Window #1 Window{bbbb u0 com.android.settings/ManageAppsActivity}:
    mViewVisibility=0x0 mHasSurface=true isReadyForDisplay()=true
"""


def emit(text: str = "") -> None:
    sys.stdout.write(text if text.endswith("\n") or not text else text + "\n")


def device_path(path: str) -> Path:
    return root / path.lstrip("/")


# Progress is time-free: each poll advances a counter, and the scenario says how
# many polls the download and extraction take.
state_file = root / ".polls"
def bump(name: str) -> int:
    counts = json.loads(state_file.read_text()) if state_file.exists() else {}
    counts[name] = counts.get(name, 0) + 1
    state_file.write_text(json.dumps(counts))
    return counts[name]


if argv[:1] == ["root"]:
    emit("restarting adbd as root")
elif argv[:1] == ["wait-for-device"]:
    pass
elif argv[:1] == ["uninstall"] or argv[:1] == ["install"]:
    emit("Success")
elif argv[:1] == ["logcat"]:
    emit(scenario.get("logcat", ""))
elif argv[:2] == ["exec-out", "screencap"]:
    sys.stdout.buffer.write(b"\x89PNG fake")
elif argv[:1] == ["pull"]:
    source, destination = argv[1], argv[2]
    data = device_path(source)
    Path(destination).write_text(data.read_text() if data.exists() else "")
elif argv[:1] == ["shell"]:
    command = " ".join(argv[1:])
    if command.startswith("id -u"):
        emit("0" if scenario.get("rooted", True) else "2000")
    elif command.startswith("pidof"):
        emit(scenario.get("pid", "4242"))
    elif command.startswith("dumpsys package"):
        # The first read is the installed rc-era APK; every later read is the
        # upgraded one, so the gate sees a real version increase.
        if bump("package_dump") == 1:
            emit(scenario.get("old_package_dump",
                              "versionCode=2003329000\nversionName=2026.08.29-r2"))
        else:
            emit(scenario.get("package_dump",
                              "versionCode=2003329001\nversionName=2026.08.29-r3"))
    elif command.startswith("dumpsys activity activities"):
        emit(scenario.get("activities", f"    ResumedActivity: ActivityRecord{{a u0 {os.environ.get('FAKE_PACKAGE','tech.ula.foxbox_pro')}/tech.ula.library.MainActivity t1}}"))
    elif command.startswith("dumpsys window windows"):
        emit(scenario.get("windows", VISIBLE_WINDOWS))
    elif command.startswith("dumpsys activity services"):
        emit(scenario.get("services", "ServiceRecord{a tech.ula/.ServerService}"))
    elif command.startswith("dumpsys"):
        emit("")
    elif command.startswith("cmd package resolve-activity"):
        emit(scenario.get("launcher", "tech.ula/.MainActivity"))
    elif command.startswith("uiautomator dump"):
        Path(root / "sdcard/userland-window.xml").parent.mkdir(parents=True, exist_ok=True)
        (root / "sdcard/userland-window.xml").write_text(scenario.get("ui", ""))
    elif command.startswith("cat "):
        target = device_path(command.split(" ", 1)[1].strip().strip("'\""))
        if not target.exists():
            sys.exit(1)
        contents = target.read_text()
        emit(contents)
        # The real app clears the journal as soon as it stages the downloads.
        # The gate reads it to confirm setup began, then again while waiting;
        # this models it disappearing right after the read that observed the
        # batch complete, which is when the app finishes staging.
        allowed = scenario.get("clear_journal_after_read")
        if allowed and target.name == "download-journal.json":
            if bump("journal-read") >= int(allowed):
                target.write_text("")
    elif command.startswith("find "):
        match = re.match(r"find (\S+)(?: -maxdepth \d+)?(?: -name '?([^' ]+)'?)?", command)
        base = device_path(match.group(1))
        pattern = match.group(2)
        # Extraction finishes only after the scenario's configured number of polls.
        if pattern == ".success_filesystem_extraction":
            if bump("extract") < scenario.get("extract_polls", 1):
                sys.exit(0)
        results = []
        if base.exists():
            for path in sorted(base.rglob("*")):
                if pattern is None or path.match(pattern):
                    results.append("/" + str(path.relative_to(root)))
        emit("\n".join(results))
    elif command.startswith("test -e"):
        target = command.split("test -e", 1)[1].split("&&")[0].strip().strip("'\"")
        if device_path(target).exists():
            emit("yes")
    elif command.startswith("pm clear"):
        emit("Success")
    else:
        emit("")
else:
    emit("")
