#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
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

SUPPORT_ABIS = ("arm64-v8a", "armeabi-v7a", "x86", "x86_64")
SUPPORT_FILES = (
    "lib_addNonRootUser.sh.so",
    "lib_arch.so",
    "lib_assets.txt.so",
    "lib_busybox.so",
    "lib_busybox_static.so",
    "lib_extractFilesystem.sh.so",
    "lib_libbusybox.so.1.37.0.so",
    "lib_proot.so",
)
SUPPORT_ARCHIVE_SHA256 = {
    "arm64-v8a": "ec9bb2e652afb0ceab2cc6830809214ee4d786d31ef8463d0ec213aca67ff9ce",
    "armeabi-v7a": "af0a2667dbf90076fbc4bdde40538db84950bc596aabe24261a766ae57ccfe41",
    "x86": "9cb71e2e79fa0d1eb453cf669c8232e0000878a190f5c01f3f17cd01c06ca4d0",
    "x86_64": "897e0902202c6c07cb4efd9b0f00f5c33d5d2925092c62b3c14951ba7a371252",
}
ANDROID_SYSTEM_LIBRARIES = {
    "libEGL.so",
    "libGLESv1_CM.so",
    "libGLESv2.so",
    "libGLESv3.so",
    "libOpenMAXAL.so",
    "libOpenSLES.so",
    "libaaudio.so",
    "libandroid.so",
    "libcamera2ndk.so",
    "libc.so",
    "libdl.so",
    "libjnigraphics.so",
    "liblog.so",
    "libm.so",
    "libmediandk.so",
    "libnativewindow.so",
    "libstdc++.so",
    "libsync.so",
    "libvulkan.so",
    "libz.so",
}
NEEDED_RE = re.compile(r"\(NEEDED\).*Shared library: \[([^]]+)\]")


def elf_needed(path: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["readelf", "-d", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"readelf failed for {path}: {result.stderr.strip()}")
    return tuple(
        match.group(1)
        for line in result.stdout.splitlines()
        if (match := NEEDED_RE.search(line)) is not None
    )


def missing_needed_libraries(
    needed: tuple[str, ...], staged_files: set[str]
) -> tuple[str, ...]:
    return tuple(
        library
        for library in needed
        if library not in ANDROID_SYSTEM_LIBRARIES
        and library not in staged_files
        and f"lib_{library}.so" not in staged_files
    )


def _is_elf(path: Path) -> bool:
    with path.open("rb") as source:
        return source.read(4) == b"\x7fELF"


def _load_marker(path: Path) -> dict | None:
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return marker if isinstance(marker, dict) else None


def _packaged_files_for_abi(root: Path, abi: str) -> set[str]:
    packaged = set()
    for jni_root in root.rglob("jniLibs"):
        abi_root = jni_root / abi
        if not abi_root.is_dir():
            continue
        packaged.update(path.name for path in abi_root.iterdir() if path.is_file())
    return packaged


def verify_dependency_tree(root: Path) -> list[str]:
    errors = []
    for relative in REQUIRED_FILES:
        path = root / relative
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"missing or empty: {relative}")
    for abi in SUPPORT_ABIS:
        jni_relative = f"UserLAndLibrary/app/src/main/jniLibs/{abi}"
        jni = root / jni_relative
        for filename in SUPPORT_FILES:
            relative = f"{jni_relative}/{filename}"
            path = root / relative
            if not path.is_file() or path.stat().st_size == 0:
                errors.append(f"missing or empty support asset for {abi}: {relative}")
        marker_relative = f"UserLAndLibrary/app/src/main/.support-assets/{abi}.json"
        marker = root / marker_relative
        marker_data = _load_marker(marker)
        actual_files = (
            sorted(path.name for path in jni.iterdir() if path.is_file())
            if jni.is_dir()
            else []
        )
        marker_metadata_valid = marker_data == {
            "abi": abi,
            "archive_sha256": SUPPORT_ARCHIVE_SHA256[abi],
            "release": "v1.5.1",
            "staged_files": actual_files,
        }
        if not marker_metadata_valid:
            errors.append(f"missing or invalid support marker for {abi}: {marker_relative}")
            if marker_data is not None and marker_data.get("staged_files") != actual_files:
                errors.append(f"marker file list mismatch for {abi}")

        arch_marker = jni / "lib_arch.so"
        if arch_marker.is_file():
            try:
                arch_value = arch_marker.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                arch_value = ""
            if arch_value != abi:
                errors.append(f"invalid architecture marker for {abi}: {arch_marker}")

        packaged_set = _packaged_files_for_abi(root, abi)
        for filename in actual_files:
            path = jni / filename
            if not _is_elf(path):
                continue
            try:
                missing = missing_needed_libraries(elf_needed(path), packaged_set)
            except ValueError as error:
                errors.append(str(error))
                continue
            for library in missing:
                errors.append(
                    f"unresolved ELF dependency for {abi}/{filename}: {library}"
                )
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
