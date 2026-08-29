#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path


EXPECTED_ABIS = ("arm64", "arm", "x86", "x86_64")
EXPECTED_PAYLOADS = ("assets.tar.gz", "rootfs.tar.gz")
EXPECTED_RECORDS = ("assets.txt", *EXPECTED_PAYLOADS)
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REPOSITORY_RE = re.compile(
    r"CypherpunkArmory/UserLAnd-Assets-[A-Za-z0-9._-]+"
)
PAYLOAD_SOURCES = {
    "foxbox": {
        "repository": "CypherpunkArmory/UserLAnd-Assets-Debian",
        "release": "v7.7.9",
    },
    "andacious": {
        "repository": "CypherpunkArmory/UserLAnd-Assets-Debian",
        "release": "v7.8.11",
    },
    "gnuplot": {
        "repository": "CypherpunkArmory/UserLAnd-Assets-Gnuplot",
        "release": "v0.0.1",
    },
    "r": {
        "repository": "CypherpunkArmory/UserLAnd-Assets-R",
        "release": "v0.0.1",
    },
    "libredocs": {
        "repository": "CypherpunkArmory/UserLAnd-Assets-LibreDocs",
        "release": "v0.0.1",
    },
    "devstudio": {
        "repository": "CypherpunkArmory/UserLAnd-Assets-deVStudio",
        "release": "v0.0.1",
        "abis": ("arm64", "arm", "x86_64"),
    },
    "inkscape": {
        "repository": "CypherpunkArmory/UserLAnd-Assets-Inkscape",
        "release": "v0.0.1",
    },
    "birdbox": {
        "repository": "CypherpunkArmory/UserLAnd-Assets-Thunderbird",
        "release": "v0.0.2",
    },
    "gimp": {
        "repository": "CypherpunkArmory/UserLAnd-Assets-Gimp",
        "release": "v0.0.1",
    },
    "idle": {
        "repository": "CypherpunkArmory/UserLAnd-Assets-IDLE",
        "release": "v0.0.1",
    },
}


def payload_abis(app_id: str) -> tuple[str, ...]:
    source = PAYLOAD_SOURCES.get(app_id, {})
    return tuple(source.get("abis", EXPECTED_ABIS))


def _load_json(path: Path, label: str, errors: list[str]) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"cannot read {label}: {error}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return {}
    return value


def _positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _duplicates(values: list[str]) -> set[str]:
    seen = set()
    return {value for value in values if value in seen or seen.add(value)}


def _validate_asset(
    app_id: str,
    abi: str,
    logical_name: str,
    record: object,
    repository: str,
    release: str,
    errors: list[str],
) -> None:
    location = f"{app_id}/{abi}/{logical_name}"
    if not isinstance(record, dict):
        errors.append(f"{location}: payload record must be an object")
        return

    expected_filename = f"{abi}-{logical_name}"
    filename = record.get("filename")
    if filename != expected_filename:
        errors.append(
            f"{location}: filename must be {expected_filename}, got {filename!r}"
        )

    if not _positive_integer(record.get("asset_id")):
        errors.append(f"{location}: asset id must be a positive integer")
    if not _positive_integer(record.get("size")):
        errors.append(f"{location}: size must be a positive integer")

    sha256 = record.get("sha256")
    if not sha256:
        errors.append(f"{location}: missing SHA-256")
    elif not isinstance(sha256, str) or SHA256_RE.fullmatch(sha256) is None:
        errors.append(f"{location}: sha256 must be 64 lowercase hexadecimal characters")

    expected_url = (
        f"https://github.com/{repository}/releases/download/"
        f"{release}/{expected_filename}"
    )
    if record.get("url") != expected_url:
        errors.append(f"{location}: url must equal {expected_url}")


def verify_payload_lock(
    path: Path, sources_path: Path = Path("sources.lock.json")
) -> list[str]:
    errors: list[str] = []
    payload_lock = _load_json(path, "payload lock", errors)
    sources = _load_json(sources_path, "source lock", errors)
    if errors:
        return errors

    if payload_lock.get("schema_version") != 1:
        errors.append("payload lock schema_version must be 1")
    if sources.get("schema_version") != 1:
        errors.append("source lock schema_version must be 1")

    source_apps = sources.get("apps")
    lock_apps = payload_lock.get("apps")
    if not isinstance(source_apps, list):
        errors.append("source lock apps must be a list")
        source_apps = []
    if not isinstance(lock_apps, list):
        errors.append("payload lock apps must be a list")
        lock_apps = []

    expected_packages = {
        item.get("package_id"): item.get("id")
        for item in source_apps
        if isinstance(item, dict) and isinstance(item.get("package_id"), str)
    }
    package_ids = [
        item.get("package_id")
        for item in lock_apps
        if isinstance(item, dict) and isinstance(item.get("package_id"), str)
    ]
    for package_id in sorted(_duplicates(package_ids)):
        errors.append(f"duplicate package_id: {package_id}")
    for package_id in sorted(set(expected_packages) - set(package_ids)):
        errors.append(f"missing package_id: {package_id}")
    for package_id in sorted(set(package_ids) - set(expected_packages)):
        errors.append(f"unexpected package_id: {package_id}")

    for index, app in enumerate(lock_apps):
        if not isinstance(app, dict):
            errors.append(f"app #{index}: record must be an object")
            continue
        app_id = app.get("id")
        package_id = app.get("package_id")
        label = app_id if isinstance(app_id, str) and app_id else f"app #{index}"
        expected_id = expected_packages.get(package_id)
        if expected_id is not None and app_id != expected_id:
            errors.append(f"{label}: source id must be {expected_id}")

        repository = app.get("repository")
        if not isinstance(repository, str) or REPOSITORY_RE.fullmatch(repository) is None:
            errors.append(f"{label}: invalid asset repository")
            repository = "invalid/repository"
        release = app.get("release")
        if not isinstance(release, str) or not release or "latest" in release.lower():
            errors.append(f"{label}: mutable release selector is forbidden")
            release = "invalid-release"
        elif not release.startswith("v") or "/" in release:
            errors.append(f"{label}: release must be a literal v-prefixed tag")
        fixed_source = PAYLOAD_SOURCES.get(app_id)
        if fixed_source is not None:
            if repository != fixed_source["repository"]:
                errors.append(
                    f"{label}: repository must be {fixed_source['repository']}"
                )
            if release != fixed_source["release"]:
                errors.append(f"{label}: release must be {fixed_source['release']}")

        abis = app.get("abis")
        if not isinstance(abis, dict):
            errors.append(f"{label}: abis must be an object")
            continue
        expected_abis = payload_abis(app_id)
        for abi in expected_abis:
            if abi not in abis:
                errors.append(f"{label}: missing ABI {abi}")
        for abi in sorted(set(abis) - set(expected_abis)):
            errors.append(f"{label}: unexpected ABI {abi}")

        for abi in expected_abis:
            abi_record = abis.get(abi)
            if not isinstance(abi_record, dict):
                continue
            allowed = {"asset_list", *EXPECTED_RECORDS}
            for name in sorted(set(abi_record) - allowed):
                errors.append(f"{label}/{abi}: unexpected payload {name}")
            asset_list = abi_record.get("asset_list")
            if not isinstance(asset_list, list) or not asset_list:
                errors.append(f"{label}/{abi}: empty asset list")
            elif any(not isinstance(item, str) or not item for item in asset_list):
                errors.append(f"{label}/{abi}: asset list entries must be nonempty strings")
            elif len(asset_list) != len(set(asset_list)):
                errors.append(f"{label}/{abi}: duplicate asset list entry")
            elif set(asset_list) != set(EXPECTED_PAYLOADS):
                errors.append(
                    f"{label}/{abi}: asset list must contain "
                    "assets.tar.gz and rootfs.tar.gz"
                )
            for logical_name in EXPECTED_RECORDS:
                if logical_name not in abi_record:
                    errors.append(f"{label}/{abi}: missing payload {logical_name}")
                    continue
                _validate_asset(
                    label,
                    abi,
                    logical_name,
                    abi_record[logical_name],
                    repository,
                    release,
                    errors,
                )

    return errors


def _hash_download(url: str, expected_size: int, open_url) -> tuple[int, str, bytes]:
    digest = hashlib.sha256()
    size = 0
    collected = bytearray()
    with open_url(url) as response:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
            if expected_size <= 1024 * 1024:
                collected.extend(block)
    if size != expected_size:
        raise ValueError(
            f"downloaded size mismatch for {url}: {size} != {expected_size}"
        )
    return size, digest.hexdigest(), bytes(collected)


def build_payload_record(
    app_id: str,
    package_id: str,
    abi: str,
    release_metadata: dict,
    open_url,
) -> dict:
    if app_id not in PAYLOAD_SOURCES:
        raise ValueError(f"unknown app id: {app_id}")
    source = PAYLOAD_SOURCES[app_id]
    if abi not in payload_abis(app_id):
        raise ValueError(f"unsupported ABI for {app_id}: {abi}")
    if release_metadata.get("tag_name") != source["release"]:
        raise ValueError(
            f"release tag mismatch for {app_id}: "
            f"{release_metadata.get('tag_name')} != {source['release']}"
        )
    release_assets = release_metadata.get("assets")
    if not isinstance(release_assets, list):
        raise ValueError("release assets must be a list")

    by_name = {}
    for asset in release_assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            continue
        name = asset["name"]
        if name in by_name:
            raise ValueError(f"duplicate release asset: {name}")
        by_name[name] = asset

    result = {
        "schema_version": 1,
        "id": app_id,
        "package_id": package_id,
        "repository": source["repository"],
        "release": source["release"],
        "abi": abi,
    }
    asset_list_bytes = b""
    for logical_name in EXPECTED_RECORDS:
        filename = f"{abi}-{logical_name}"
        asset = by_name.get(filename)
        if asset is None:
            raise ValueError(f"release is missing asset: {filename}")
        asset_id = asset.get("id")
        expected_size = asset.get("size")
        url = asset.get("browser_download_url")
        if not _positive_integer(asset_id):
            raise ValueError(f"invalid release asset id for {filename}")
        if not _positive_integer(expected_size):
            raise ValueError(f"invalid release asset size for {filename}")
        expected_url = (
            f"https://github.com/{source['repository']}/releases/download/"
            f"{source['release']}/{filename}"
        )
        if url != expected_url:
            raise ValueError(f"release asset URL mismatch for {filename}")
        size, sha256, body = _hash_download(url, expected_size, open_url)
        result[logical_name] = {
            "asset_id": asset_id,
            "filename": filename,
            "url": url,
            "size": size,
            "sha256": sha256,
        }
        if logical_name == "assets.txt":
            asset_list_bytes = body

    try:
        lines = asset_list_bytes.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("assets.txt is not UTF-8") from error
    asset_list = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        filename = line.split()[0]
        if filename != "assets.txt":
            asset_list.append(filename)
    if not asset_list:
        raise ValueError("assets.txt contains no payload entries")
    if len(asset_list) != len(set(asset_list)):
        raise ValueError("assets.txt contains duplicate payload entries")
    result["asset_list"] = asset_list
    return result


def aggregate_records(sources: dict, records: list[dict]) -> dict:
    source_apps = sources.get("apps")
    if not isinstance(source_apps, list):
        raise ValueError("source lock apps must be a list")
    source_by_id = {
        app["id"]: app
        for app in source_apps
        if isinstance(app, dict) and isinstance(app.get("id"), str)
    }
    if set(source_by_id) - set(PAYLOAD_SOURCES):
        raise ValueError("source lock contains an app without fixed payload metadata")

    by_key = {}
    for record in records:
        key = (record.get("id"), record.get("abi"))
        if key in by_key:
            raise ValueError(f"duplicate record: {key[0]}/{key[1]}")
        by_key[key] = record

    apps = []
    for app_id, source_app in source_by_id.items():
        source = PAYLOAD_SOURCES[app_id]
        abis = {}
        for abi in payload_abis(app_id):
            record = by_key.get((app_id, abi))
            if record is None:
                raise ValueError(f"missing record: {app_id}/{abi}")
            if record.get("package_id") != source_app.get("package_id"):
                raise ValueError(f"package mismatch: {app_id}/{abi}")
            if record.get("repository") != source["repository"]:
                raise ValueError(f"repository mismatch: {app_id}/{abi}")
            if record.get("release") != source["release"]:
                raise ValueError(f"release mismatch: {app_id}/{abi}")
            abis[abi] = {
                "asset_list": record["asset_list"],
                **{name: record[name] for name in EXPECTED_RECORDS},
            }
        apps.append(
            {
                "id": app_id,
                "package_id": source_app["package_id"],
                "repository": source["repository"],
                "release": source["release"],
                "abis": abis,
            }
        )
    extra = set(by_key) - {
        (app_id, abi) for app_id in source_by_id for abi in payload_abis(app_id)
    }
    if extra:
        app_id, abi = sorted(extra)[0]
        raise ValueError(f"unexpected record: {app_id}/{abi}")
    return {
        "schema_version": 1,
        "apps": sorted(apps, key=lambda item: item["package_id"]),
    }


def _github_open(url: str, accept: str = "application/octet-stream"):
    headers = {
        "Accept": accept,
        "User-Agent": "UserLAnd-Apps-payload-lock/1",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=120
    )


def _fetch_release(source: dict) -> dict:
    url = (
        f"https://api.github.com/repos/{source['repository']}/releases/tags/"
        f"{source['release']}"
    )
    with _github_open(url, accept="application/vnd.github+json") as response:
        return json.load(response)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and verify first-run payload locks")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("path", type=Path)
    verify_parser.add_argument("--sources", type=Path, default=Path("sources.lock.json"))
    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--app", required=True)
    record_parser.add_argument("--abi", choices=EXPECTED_ABIS, required=True)
    record_parser.add_argument("--sources", type=Path, default=Path("sources.lock.json"))
    record_parser.add_argument("--output", type=Path, required=True)
    aggregate_parser = subparsers.add_parser("aggregate")
    aggregate_parser.add_argument("--sources", type=Path, required=True)
    aggregate_parser.add_argument("--records", type=Path, required=True)
    aggregate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "verify":
        errors = verify_payload_lock(args.path, args.sources)
        if errors:
            for error in errors:
                print(error)
            return 1
        app_count = len(json.loads(args.path.read_text(encoding="utf-8"))["apps"])
        print(f"Payload lock valid: {app_count} apps")
        return 0
    if args.command == "record":
        sources = json.loads(args.sources.read_text(encoding="utf-8"))
        app = next(
            (item for item in sources["apps"] if item["id"] == args.app), None
        )
        if app is None:
            raise ValueError(f"unknown source app: {args.app}")
        source = PAYLOAD_SOURCES[args.app]
        record = build_payload_record(
            args.app,
            app["package_id"],
            args.abi,
            _fetch_release(source),
            _github_open,
        )
        _write_json(args.output, record)
        print(f"Payload record written: {args.app}/{args.abi}")
        return 0
    if args.command == "aggregate":
        sources = json.loads(args.sources.read_text(encoding="utf-8"))
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(args.records.rglob("*.json"))
        ]
        payload_lock = aggregate_records(sources, records)
        _write_json(args.output, payload_lock)
        print(f"Payload lock written: {len(payload_lock['apps'])} apps")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
