#!/usr/bin/env python3
import argparse
import json
import shutil
import stat
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

if __package__:
    from .validate_contract import load_json, validate_contract
else:
    from validate_contract import load_json, validate_contract

EXCLUDED_PARTS = {".git", ".github", ".gradle", "UserLAndLibrary", "build"}
EXCLUDED_NAMES = {"local.properties"}


def _member_path(name: str) -> tuple[str, Path] | None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe archive member: {name}")
    parts = tuple(part for part in path.parts if part not in ("", "."))
    if len(parts) < 2:
        return None
    root, relative_parts = parts[0], parts[1:]
    if any(part in EXCLUDED_PARTS for part in relative_parts):
        return None
    if relative_parts[-1] in EXCLUDED_NAMES:
        return None
    return root, Path(*relative_parts)


def extract_launcher(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    archive_root = None
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            mapped = _member_path(member.name)
            if mapped is None:
                continue
            root, relative = mapped
            if archive_root is None:
                archive_root = root
            elif root != archive_root:
                raise ValueError(f"unsafe archive member: {member.name}")
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError(f"unsafe archive member: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(f"unsafe archive member type: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = source.extractfile(member)
            if extracted is None:
                raise ValueError(f"could not read archive member: {member.name}")
            with target.open("wb") as output:
                shutil.copyfileobj(extracted, output)
            target.chmod(stat.S_IMODE(member.mode))


def import_app(app: dict, destination: Path, replace: bool = False) -> None:
    if destination.exists() and any(destination.iterdir()):
        if not replace:
            raise FileExistsError(f"destination is not empty: {destination}")
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    url = (
        f"https://api.github.com/repos/{app['repository']}/tarball/"
        f"{app['source_ref']}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "UserLAnd-Apps-importer"})
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as archive:
        with urllib.request.urlopen(request, timeout=120) as response:
            shutil.copyfileobj(response, archive)
        archive.flush()
        extract_launcher(Path(archive.name), destination)
    provenance = {
        "repository": app["repository"],
        "source_ref": app["source_ref"],
        "imported_at_utc": datetime.now(timezone.utc).isoformat(),
        "exclusions": sorted(EXCLUDED_PARTS | EXCLUDED_NAMES),
    }
    (destination / "SOURCE.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Import locked launcher sources")
    parser.add_argument("--lock", type=Path, default=Path("sources.lock.json"))
    parser.add_argument("--destination", type=Path, default=Path("apps"))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    root = args.lock.resolve().parent
    errors = validate_contract(root)
    if errors:
        raise SystemExit("\n".join(errors))
    apps = load_json(args.lock)["apps"]
    for index, app in enumerate(apps, start=1):
        import_app(app, args.destination / app["id"], replace=args.replace)
        print(f"Imported {index}/{len(apps)}: {app['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
