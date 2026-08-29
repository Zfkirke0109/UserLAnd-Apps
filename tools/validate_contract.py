#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
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
    if not re.fullmatch(r"[0-9a-f]{64}", archive_hash):
        errors.append("native archive SHA-256 is invalid")
    return errors


def main() -> int:
    errors = validate_contract(Path("."))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Contract valid: 10 apps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
