#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


PAYLOAD_NAMES = ("assets.tar.gz", "rootfs.tar.gz")


def render_catalog(payload_lock: dict) -> dict:
    apps = []
    for app in sorted(payload_lock["apps"], key=lambda item: item["package_id"]):
        rendered_abis = {}
        for abi in sorted(app["abis"]):
            source = app["abis"][abi]
            rendered_abi = {"asset_list": list(source["asset_list"])}
            for name in PAYLOAD_NAMES:
                payload = source[name]
                rendered_abi[name] = {
                    "filename": payload["filename"],
                    "release": app["release"],
                    "url": payload["url"],
                    "size": payload["size"],
                    "sha256": payload["sha256"],
                }
            rendered_abis[abi] = rendered_abi
        apps.append(
            {
                "id": app["id"],
                "package_id": app["package_id"],
                "repository": app["repository"],
                "abis": rendered_abis,
            }
        )
    return {"schema_version": 1, "apps": apps}


def catalog_bytes(payload_lock: dict) -> bytes:
    return (
        json.dumps(render_catalog(payload_lock), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def write_catalog(payload_lock: dict, output: Path, check: bool = False) -> None:
    expected = catalog_bytes(payload_lock)
    if check:
        if not output.is_file() or output.read_bytes() != expected:
            raise ValueError(f"runtime catalog differs from {output}")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(expected)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the APK runtime payload catalog")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("payload_lock", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload_lock = json.loads(args.payload_lock.read_text(encoding="utf-8"))
    try:
        write_catalog(payload_lock, args.output, check=args.check)
    except ValueError as error:
        print(error)
        return 1
    print(
        f"Runtime payload catalog {'verified' if args.check else 'written'}: "
        f"{args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
