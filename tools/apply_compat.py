#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

ANDROID_URI = "http://schemas.android.com/apk/res/android"
ANDROID = f"{{{ANDROID_URI}}}"
ET.register_namespace("android", ANDROID_URI)


def load_profile(path: Path, base: Path | None = None, seen: set[Path] | None = None) -> dict:
    path = path.resolve()
    base = base.resolve() if base else path.parent
    seen = set() if seen is None else seen
    if not path.is_relative_to(base):
        raise ValueError(f"profile include escapes directory: {path}")
    if path in seen:
        raise ValueError(f"profile include cycle: {path}")
    seen.add(path)
    profile = json.loads(path.read_text(encoding="utf-8"))
    operations = []
    if "extends" in profile:
        parent = load_profile(path.parent / profile["extends"], base, seen)
        operations.extend(parent.get("operations", []))
    operations.extend(profile.get("operations", []))
    seen.remove(path)
    return {**profile, "operations": operations}


def _resolve(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path escapes workspace: {relative}")
    if not path.is_file():
        raise ValueError(f"profile path is not a file: {relative}")
    return path


def _resolve_asset(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"replacement asset escapes directory: {relative}")
    if not path.is_file():
        raise ValueError(f"replacement asset is not a file: {relative}")
    return path


def _resolve_destination(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"copy target escapes workspace: {relative}")
    if path.exists() and not path.is_file():
        raise ValueError(f"copy target is not a file: {relative}")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_count(operation: dict, found: int) -> None:
    expected = operation.get("count")
    if not isinstance(expected, int):
        raise ValueError("modifying operation requires integer count")
    if found != expected:
        raise ValueError(f"expected {expected} anchors, found {found}")


def _replace(path: Path, operation: dict) -> bool:
    text = path.read_text(encoding="utf-8")
    found = text.count(operation["old"])
    _expected_count(operation, found)
    updated = text.replace(operation["old"], operation["new"])
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def _replace_file(
    path: Path, operation: dict, assets_root: Path
) -> bool:
    source = _resolve_asset(assets_root, operation["source"])
    if path.read_bytes() == source.read_bytes():
        return False
    current_sha256 = _sha256(path)
    if current_sha256 != operation.get("old_sha256"):
        raise ValueError(
            "old SHA-256 mismatch for "
            f"{operation['path']}: {current_sha256}"
        )
    mode = path.stat().st_mode
    path.write_bytes(source.read_bytes())
    os.chmod(path, mode)
    return True


def _copy_file(root: Path, operation: dict, assets_root: Path) -> bool:
    source = _resolve_asset(assets_root, operation["source"])
    source_sha256 = _sha256(source)
    if source_sha256 != operation.get("sha256"):
        raise ValueError(
            "copy_file source SHA-256 mismatch for "
            f"{operation['source']}: {source_sha256}"
        )
    target = _resolve_destination(root, operation["path"])
    source_bytes = source.read_bytes()
    if target.exists():
        if target.read_bytes() == source_bytes:
            return False
        raise ValueError(
            "copy_file target already exists with different bytes: "
            f"{operation['path']}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return True


def _delete_lines(path: Path, operation: dict) -> bool:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(operation["pattern"])
    lines = text.splitlines(keepends=True)
    matches = [line for line in lines if pattern.search(line.rstrip("\n"))]
    _expected_count(operation, len(matches))
    updated = "".join(line for line in lines if not pattern.search(line.rstrip("\n")))
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def _insert_after(path: Path, operation: dict) -> bool:
    text = path.read_text(encoding="utf-8")
    anchor = operation["anchor"]
    found = text.count(anchor)
    _expected_count(operation, found)
    updated = text.replace(anchor, anchor + operation["text"])
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def _set_xml_exported(path: Path, operation: dict) -> bool:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(path, parser=parser)
    manifest = tree.getroot()
    requested = {(item["tag"], item["name"]) for item in operation["components"]}
    found = set()
    changed = False
    for application in manifest.findall("application"):
        for component in application:
            if not isinstance(component.tag, str):
                continue
            key = (component.tag.split("}")[-1], component.get(ANDROID + "name"))
            if key not in requested:
                continue
            found.add(key)
            exported = component.get(ANDROID + "exported")
            if exported is None:
                component.set(ANDROID + "exported", "true")
                changed = True
            elif exported != "true":
                raise ValueError(f"existing android:exported is false for {key[1]}")
    _expected_count(operation, len(found))
    missing = requested - found
    if missing:
        raise ValueError(f"missing XML components: {sorted(missing)}")
    if changed:
        ET.indent(tree, space="    ")
        tree.write(path, encoding="utf-8", xml_declaration=True)
    return changed


def _assert_absent(path: Path, operation: dict) -> bool:
    text = path.read_text(encoding="utf-8")
    if "pattern" in operation:
        present = re.search(operation["pattern"], text) is not None
    else:
        present = operation["text"] in text
    if present:
        raise ValueError(f"forbidden content remains in {operation['path']}")
    return False


def apply_profile(
    root: Path, profile: dict, assets_root: Path | None = None
) -> list[str]:
    assets_root = (
        assets_root.resolve()
        if assets_root is not None
        else Path(__file__).resolve().parents[1]
    )
    handlers = {
        "replace": _replace,
        "delete_lines_matching": _delete_lines,
        "insert_after": _insert_after,
        "set_xml_exported": _set_xml_exported,
        "assert_absent": _assert_absent,
    }
    changed = []
    for operation in profile.get("operations", []):
        kind = operation.get("type")
        if kind == "copy_file":
            if _copy_file(root, operation, assets_root):
                changed.append(operation["path"])
            continue
        if kind == "replace_file":
            path = _resolve(root, operation["path"])
            if _replace_file(path, operation, assets_root):
                changed.append(operation["path"])
            continue
        if kind not in handlers:
            raise ValueError(f"unsupported operation type: {kind}")
        path = _resolve(root, operation["path"])
        if handlers[kind](path, operation) and operation["path"] not in changed:
            changed.append(operation["path"])
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a compatibility profile")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    profile = load_profile(args.profile)
    if args.check:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "workspace"
            shutil.copytree(args.root, copy, symlinks=True)
            changed = apply_profile(copy, profile)
        print(f"Profile valid: {args.profile} ({len(changed)} changed paths)")
    else:
        changed = apply_profile(args.root, profile)
        print(f"Applied profile: {args.profile} ({len(changed)} changed paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
