#!/usr/bin/env python3
import re
import sys
from pathlib import Path


def find_app_failure(package_id: str, text: str) -> str | None:
    package = re.escape(package_id)
    lines = text.splitlines()

    for line in lines:
        if re.search(rf"\bANR in\s+{package}(?:\b|[:/])", line):
            return "ANR"
        if "Force finishing activity" in line and re.search(
            rf"{package}(?:/|\b)", line
        ):
            return "force-finish"

    for index, line in enumerate(lines):
        if "FATAL EXCEPTION" not in line:
            continue
        block = "\n".join(lines[index : index + 16])
        if re.search(rf"\bProcess:\s*{package}(?:\s|,|$)", block):
            return "fatal exception"

    return None


def main(arguments: list[str]) -> int:
    if len(arguments) < 3:
        print(
            "usage: assert_no_app_crash.py PACKAGE_ID LOGCAT [LOGCAT ...]",
            file=sys.stderr,
        )
        return 2

    package_id = arguments[1]
    for path_text in arguments[2:]:
        path = Path(path_text)
        try:
            failure = find_app_failure(package_id, path.read_text(errors="replace"))
        except OSError as error:
            print(f"unable to read {path}: {error}", file=sys.stderr)
            return 2
        if failure:
            print(f"{failure} found for {package_id} in {path}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
