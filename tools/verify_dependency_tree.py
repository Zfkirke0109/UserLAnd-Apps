#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

REQUIRED_FILES = (
    "UserLAndLibrary/app/build.gradle",
    "UserLAndLibrary/termux-app/app/build.gradle",
    "UserLAndLibrary/termux-app/terminal-view/build.gradle",
    "UserLAndLibrary/termux-app/terminal-emulator/build.gradle",
    "UserLAndLibrary/remote-desktop-clients/bVNC/build.gradle",
    "UserLAndLibrary/remote-desktop-clients/pubkeyGenerator/build.gradle",
    "UserLAndLibrary/remote-desktop-clients/remoteClientLib/build.gradle",
    "UserLAndLibrary/remote-desktop-clients/remoteClientLib/jni/libs/deps/FreeRDP/client/Android/Studio/freeRDPCore/build.gradle",
    "UserLAndLibrary/remote-desktop-clients/remoteClientLib/jni/libs/deps/FreeRDP/client/Android/Studio/freeRDPCore/src/main/AndroidManifest.xml",
    "UserLAndLibrary/remote-desktop-clients/remoteClientLib/jni/libs/deps/FreeRDP/client/Android/Studio/freeRDPCore/src/main/jniLibs.DISABLED/armeabi-v7a/libfreerdp-android.so",
    "UserLAndLibrary/remote-desktop-clients/remoteClientLib/jni/libs/deps/FreeRDP/client/Android/Studio/freeRDPCore/src/main/jniLibs.DISABLED/armeabi-v7a/libfreerdp.so",
    "UserLAndLibrary/remote-desktop-clients/remoteClientLib/jni/libs/deps/FreeRDP/client/Android/Studio/freeRDPCore/src/main/jniLibs.DISABLED/armeabi-v7a/libwinpr.so",
)


def verify_dependency_tree(root: Path) -> list[str]:
    errors = []
    for relative in REQUIRED_FILES:
        path = root / relative
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"missing or empty: {relative}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify restored UserLAnd dependencies")
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    errors = verify_dependency_tree(args.root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Dependency tree verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
