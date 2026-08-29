#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_CERTIFICATE = "82:9A:55:6F:C5:8A:D5:24:9B:5D:4C:4A:7F:CB:9A:96:9C:FF:38:26:AA:5C:7E:41:02:C3:13:B2:20:A4:5F:EC"
MIN_VERSION_CODE = 2_000_000_000
MAX_VERSION_CODE = 2_100_000_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_checksums(root: Path, output: Path) -> None:
    lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(root.glob("*.apk"), key=lambda item: item.name)
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _match(pattern: str, text: str, field: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError(f"APK metadata missing {field}")
    return match.group(1)


def inspect_apk(path: Path) -> dict:
    badging = subprocess.run(
        ["aapt", "dump", "badging", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    certificates = subprocess.run(
        ["apksigner", "verify", "--verbose", "--print-certs", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    raw_certificate = _match(
        r"^Signer #1 certificate SHA-256 digest: ([0-9a-fA-F:]+)$",
        certificates,
        "signer SHA-256",
    ).replace(":", "")
    certificate = ":".join(
        raw_certificate[index : index + 2].upper()
        for index in range(0, len(raw_certificate), 2)
    )
    return {
        "package_id": _match(r"^package: name='([^']+)'", badging, "package name"),
        "version_code": int(
            _match(r"^package: .* versionCode='([0-9]+)'", badging, "versionCode")
        ),
        "version_name": _match(
            r"^package: .* versionName='([^']+)'", badging, "versionName"
        ),
        "min_sdk": int(_match(r"^sdkVersion:'([0-9]+)'", badging, "sdkVersion")),
        "target_sdk": int(
            _match(r"^targetSdkVersion:'([0-9]+)'", badging, "targetSdkVersion")
        ),
        "certificate_sha256": certificate,
    }


def build_manifest(dist: Path, lock: Path, release_tag: str, generated_at: str) -> dict:
    apps = json.loads(lock.read_text(encoding="utf-8"))["apps"]
    expected_names = {app["output_name"] for app in apps}
    actual_paths = list(dist.glob("*.apk"))
    actual_names = {path.name for path in actual_paths}
    if len(apps) != 10 or len(expected_names) != 10:
        raise ValueError("source lock must define ten unique APK output names")
    if len(actual_paths) != len(actual_names):
        raise ValueError("duplicate APK filenames found")
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise ValueError(f"APK set mismatch; missing={missing}, extra={extra}")

    results = []
    version_codes = set()
    for app in sorted(apps, key=lambda item: item["id"]):
        apk = dist / app["output_name"]
        metadata = inspect_apk(apk)
        if metadata["package_id"] != app["package_id"]:
            raise ValueError(
                f"{app['id']} package mismatch: {metadata['package_id']} != {app['package_id']}"
            )
        if not MIN_VERSION_CODE <= metadata["version_code"] <= MAX_VERSION_CODE:
            raise ValueError(f"{app['id']} version code is out of range")
        if metadata["certificate_sha256"] != EXPECTED_CERTIFICATE:
            raise ValueError(f"{app['id']} certificate mismatch")
        version_codes.add(metadata["version_code"])
        results.append(
            {
                "id": app["id"],
                "display_name": app["display_name"],
                "apk": app["output_name"],
                "sha256": sha256_file(apk),
                **metadata,
                "source_repository": app["repository"],
                "source_ref": app["source_ref"],
            }
        )
    if len(version_codes) != 1:
        raise ValueError(f"release APK version codes differ: {sorted(version_codes)}")
    return {
        "schema_version": 1,
        "release_tag": release_tag,
        "generated_at_utc": generated_at,
        "certificate_sha256": EXPECTED_CERTIFICATE,
        "apps": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and document release APKs")
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--lock", type=Path, default=Path("sources.lock.json"))
    parser.add_argument("--release-tag", required=True)
    parser.add_argument(
        "--generated-at-utc",
        default=datetime.now(timezone.utc).isoformat(),
    )
    args = parser.parse_args()
    manifest = build_manifest(
        args.dist, args.lock, args.release_tag, args.generated_at_utc
    )
    (args.dist / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_checksums(args.dist, args.dist / "SHA256SUMS")
    print(f"Release manifest valid: {len(manifest['apps'])} apps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
