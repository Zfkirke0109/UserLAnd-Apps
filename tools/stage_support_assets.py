#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

SUPPORTED_ABIS = {"arm64-v8a", "armeabi-v7a", "x86", "x86_64"}
EXCLUDED_SUPPORT_MEMBERS = {
    # The v1.5.1 archive includes PulseAudio's optional echo canceller without
    # its libwebrtc-audio-processing dependency. Neither file is loaded by the
    # shipped default.pa, so omit the unusable pair instead of packaging a
    # knowingly broken ELF closure.
    "libwebrtc-util.so",
    "module-echo-cancel.so",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validated_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if not members:
        raise ValueError("support archive is empty")
    destinations = set()
    for member in members:
        path = PurePosixPath(member.filename)
        mode = member.external_attr >> 16
        if (
            path.is_absolute()
            or len(path.parts) != 1
            or path.name in ("", ".", "..")
            or member.is_dir()
            or stat.S_ISLNK(mode)
            or member.flag_bits & 0x1
        ):
            raise ValueError(f"unsafe support archive member: {member.filename}")
        destination = f"lib_{path.name}.so"
        if destination == "lib_arch.so":
            raise ValueError(f"reserved support archive member: {member.filename}")
        if destination in destinations:
            raise ValueError(f"duplicate support archive member: {member.filename}")
        destinations.add(destination)
    return members


def stage_archive(
    archive: Path, destination: Path, abi: str, release: str
) -> list[Path]:
    if abi not in SUPPORTED_ABIS:
        raise ValueError(f"unsupported ABI: {abi}")
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        members = _validated_members(source)
        with tempfile.TemporaryDirectory(
            prefix=f".{abi}-", dir=destination.parent
        ) as directory:
            staging = Path(directory) / abi
            staging.mkdir()
            for member in members:
                if PurePosixPath(member.filename).name in EXCLUDED_SUPPORT_MEMBERS:
                    continue
                target = staging / f"lib_{PurePosixPath(member.filename).name}.so"
                with source.open(member) as input_file, target.open("wb") as output_file:
                    shutil.copyfileobj(input_file, output_file)
                if target.stat().st_size != member.file_size:
                    raise ValueError(f"short support archive member: {member.filename}")
            (staging / "lib_arch.so").write_text(abi, encoding="utf-8")
            final = destination / abi
            if final.exists():
                shutil.rmtree(final)
            destination.mkdir(parents=True, exist_ok=True)
            os.replace(staging, final)

    staged = sorted((destination / abi).iterdir(), key=lambda path: path.name)
    marker_dir = destination.parent / ".support-assets"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = {
        "abi": abi,
        "archive_sha256": sha256_file(archive),
        "release": release,
        "staged_files": [path.name for path in staged],
    }
    (marker_dir / f"{abi}.json").write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return staged


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely stage UserLAnd support assets")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--abi", required=True)
    parser.add_argument("--release", required=True)
    args = parser.parse_args()
    staged = stage_archive(args.archive, args.destination, args.abi, args.release)
    print(f"Staged {len(staged)} support files for {args.abi}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
