#!/usr/bin/env python3
"""Push each verified Play listing title into that app's build profile.

The title is user-visible text naming someone else's Store listing, so it
lives in credits.lock.json and is copied from there rather than typed into
ten separate profiles. Run with --check to verify without writing.
"""
import json
import sys
from pathlib import Path

ANCHOR = '        resValue "string", "clear_support_files_enabled", "false"\n'
PATH = "CustomLibrary/build.gradle"


def resource_line(title: str) -> str:
    if '"' in title or "\\" in title:
        raise ValueError(f"title needs escaping rules this tool does not have: {title!r}")
    return f'        resValue "string", "creator_play_title", "{title}"\n'


def operation(title: str) -> dict:
    return {
        "type": "insert_after",
        "path": PATH,
        "anchor": ANCHOR,
        "text": resource_line(title),
        "count": 1,
    }


def sync(root: Path, check: bool) -> list[str]:
    lock = json.loads((root / "credits.lock.json").read_text(encoding="utf-8"))
    sources = json.loads((root / "sources.lock.json").read_text(encoding="utf-8"))
    profiles = {app["id"]: app["profile"] for app in sources["apps"]}
    problems: list[str] = []

    for app in lock["apps"]:
        title = app.get("play_title")
        if not title:
            problems.append(f"{app['id']} has no play_title")
            continue
        path = root / "profiles" / f"{profiles[app['id']]}.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        wanted = operation(title)
        existing = [
            op for op in profile["operations"]
            if op.get("type") == "insert_after"
            and op.get("path") == PATH
            and "creator_play_title" in op.get("text", "")
        ]
        if existing == [wanted]:
            continue
        if check:
            problems.append(
                f"{app['id']}: profile does not carry the locked title {title!r}"
            )
            continue
        for op in existing:
            profile["operations"].remove(op)
        profile["operations"].append(wanted)
        path.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return problems


def main(argv: list[str]) -> int:
    check = "--check" in argv
    problems = sync(Path("."), check)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print("Creator titles synced: 10 apps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
