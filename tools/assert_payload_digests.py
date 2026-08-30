#!/usr/bin/env python3
"""Check the payloads a device actually downloaded against the release lock.

The download journal records the digest each payload was verified against before
it was published. Comparing those to the lock proves the bytes on the device are
the bytes this release pinned, rather than whatever a remote pointer served.
"""
import argparse
import json
import sys
from pathlib import Path

PAYLOAD_NAMES = ("assets.tar.gz", "rootfs.tar.gz")


def locked_digests(lock: dict, package_id: str, abi: str) -> dict[str, str]:
    for app in lock.get("apps", []):
        if app.get("package_id") != package_id:
            continue
        record = app.get("abis", {}).get(abi)
        if record is None:
            raise SystemExit(f"{package_id} has no locked payloads for {abi}")
        return {
            name: record[name]["sha256"]
            for name in PAYLOAD_NAMES
            if name in record
        }
    raise SystemExit(f"{package_id} is not in the payload lock")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--abi", required=True)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--journal", required=True, type=Path)
    args = parser.parse_args(argv[1:])

    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    expected = locked_digests(lock, args.package, args.abi)
    if not expected:
        raise SystemExit(f"no locked payloads for {args.package}/{args.abi}")

    try:
        batch = json.loads(args.journal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"unreadable download journal: {error}", file=sys.stderr)
        return 1

    items = batch.get("items", [])
    if not items:
        print("the download journal records no payloads", file=sys.stderr)
        return 1

    seen = {}
    for item in items:
        if item.get("state") != "COMPLETE":
            print(
                f"payload {item.get('id')} is {item.get('state')}, not COMPLETE",
                file=sys.stderr,
            )
            return 1
        digest = (item.get("sha256") or "").lower()
        if not digest:
            print(f"payload {item.get('id')} carries no digest", file=sys.stderr)
            return 1
        seen[digest] = item.get("id")

    for name, digest in expected.items():
        if digest.lower() not in seen:
            print(
                f"{name} was not downloaded against its locked digest {digest}",
                file=sys.stderr,
            )
            return 1
        print(f"{name}: verified against {digest}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
