#!/usr/bin/env python3
import hashlib
import json
import re
import sys
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SUPPORT_ASSETS = {
    "arm64-v8a": "ec9bb2e652afb0ceab2cc6830809214ee4d786d31ef8463d0ec213aca67ff9ce",
    "armeabi-v7a": "af0a2667dbf90076fbc4bdde40538db84950bc596aabe24261a766ae57ccfe41",
    "x86": "9cb71e2e79fa0d1eb453cf669c8232e0000878a190f5c01f3f17cd01c06ca4d0",
    "x86_64": "897e0902202c6c07cb4efd9b0f00f5c33d5d2925092c62b3c14951ba7a371252",
}
APP_KEYS = {
    "id",
    "display_name",
    "package_id",
    "repository",
    "source_ref",
    "profile",
    "output_name",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contract(root: Path) -> list[str]:
    sources = load_json(root / "sources.lock.json")
    dependencies = load_json(root / "dependencies.lock.json")
    release = load_json(root / "release.lock.json")
    apps = sources.get("apps", [])
    errors = []
    if len(apps) != 10:
        errors.append(f"expected 10 apps, found {len(apps)}")
    packages = set()
    ids = set()
    for app in apps:
        missing = APP_KEYS - set(app)
        if missing:
            errors.append(f"{app.get('id', '<unknown>')} missing: {sorted(missing)}")
        app_id = app.get("id")
        if app_id in ids:
            errors.append(f"duplicate id: {app_id}")
        ids.add(app_id)
        package_id = app.get("package_id")
        if package_id in packages:
            errors.append(f"duplicate package_id: {package_id}")
        packages.add(package_id)
        if not SHA.fullmatch(app.get("source_ref", "")):
            errors.append(f"{app_id} has non-SHA source_ref")
    for name in (
        "userland_library",
        "remote_desktop_clients",
        "termux_app",
        "freerdp",
    ):
        if not SHA.fullmatch(dependencies.get(name, {}).get("ref", "")):
            errors.append(f"{name} has non-SHA ref")
    archive_hash = dependencies.get("native_archive", {}).get("sha256", "")
    if not SHA256.fullmatch(archive_hash):
        errors.append("native archive SHA-256 is invalid")
    support = dependencies.get("support_assets", {})
    if support.get("repository") != "CypherpunkArmory/UserLAnd-Assets-Support":
        errors.append("support assets repository is invalid")
    if support.get("release") != "v1.5.1":
        errors.append("support assets release must be v1.5.1")
    archives = support.get("archives", [])
    found_support = {}
    for archive in archives:
        abi = archive.get("abi")
        if abi in found_support:
            errors.append(f"duplicate support asset ABI: {abi}")
        found_support[abi] = archive.get("sha256")
        filename = f"{abi}-assets.zip"
        if archive.get("filename") != filename:
            errors.append(f"support asset filename is invalid for {abi}")
        expected_url = (
            "https://github.com/CypherpunkArmory/UserLAnd-Assets-Support/"
            f"releases/download/v1.5.1/{filename}"
        )
        if archive.get("url") != expected_url:
            errors.append(f"support asset URL is invalid for {abi}")
        if not SHA256.fullmatch(archive.get("sha256", "")):
            errors.append(f"support asset SHA-256 is invalid for {abi}")
    if found_support != SUPPORT_ASSETS:
        errors.append("support asset ABI/checksum set is invalid")
    if release.get("schema_version") != 1:
        errors.append("release schema_version must be 1")
    if release.get("release_tag") != "v2026.08.29-r3":
        errors.append("release tag must be v2026.08.29-r3")
    if release.get("version_name") != "2026.08.29-r3":
        errors.append("release version_name must be 2026.08.29-r3")
    version_code = release.get("version_code")
    old_version_code = release.get("upgrade_from_version_code")
    if not isinstance(version_code, int) or not 2_000_000_000 <= version_code <= 2_100_000_000:
        errors.append("release version_code is invalid")
    if not isinstance(old_version_code, int) or (
        isinstance(version_code, int) and version_code <= old_version_code
    ):
        errors.append("release version_code must exceed upgrade version_code")
    if release.get("upgrade_from_tag") != "v2026.08.29-r2":
        errors.append("upgrade_from_tag must be v2026.08.29-r2")
    if old_version_code != 2003329000:
        errors.append("upgrade_from_version_code must be 2003329000")
    foxbox = next((app for app in apps if app.get("id") == "foxbox"), None)
    if foxbox is None or foxbox.get("source_ref") != (
        "7f08dcf54fcae40bb96fd20e1c057c8ac89c2fde"
    ):
        errors.append("foxbox source_ref is not the approved r2 commit")
    return errors


def validate_credits(root: Path) -> list[str]:
    """The bundled Play badge must be Google's asset, byte for byte."""
    errors: list[str] = []
    lock_path = root / "credits.lock.json"
    if not lock_path.is_file():
        return ["credits.lock.json is missing"]
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"credits.lock.json is unreadable: {error}"]

    badge = lock.get("badge", {})
    badge_path = root / badge.get("path", "")
    if not badge_path.is_file():
        errors.append(f"badge is missing: {badge.get('path')}")
    else:
        data = badge_path.read_bytes()
        if len(data) != badge.get("size"):
            errors.append(
                f"badge is {len(data)} bytes, locked at {badge.get('size')}"
            )
        digest = hashlib.sha256(data).hexdigest()
        if digest != badge.get("sha256"):
            errors.append("badge SHA-256 does not match credits.lock.json")

    packages = {app["package_id"] for app in lock.get("apps", [])}
    for app in lock.get("apps", []):
        if not app.get("play_package"):
            errors.append(f"{app.get('id')} has no Play package to link to")
    if len(packages) != 10:
        errors.append(f"credits cover {len(packages)} packages, expected 10")
    return errors


def main() -> int:
    errors = validate_contract(Path(".")) + validate_credits(Path("."))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Contract valid: 10 apps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
