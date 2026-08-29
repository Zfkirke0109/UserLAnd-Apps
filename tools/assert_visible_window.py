#!/usr/bin/env python3
import re
import sys
from pathlib import Path


WINDOW_START = re.compile(r"^\s+(?:Window #\d+|#\d+) Window\{")


def window_blocks(text: str) -> list[str]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if WINDOW_START.match(line):
            current = [line]
            blocks.append(current)
        elif current is not None:
            current.append(line)
    return ["\n".join(block) for block in blocks]


def has_visible_window(text: str, package_id: str) -> bool:
    return any(
        package_id in block
        and "mViewVisibility=0x0" in block
        and "mHasSurface=true" in block
        and "isReadyForDisplay()=true" in block
        for block in window_blocks(text)
    )


def main(arguments: list[str]) -> int:
    if len(arguments) != 3:
        print(
            "usage: assert_visible_window.py DUMPSYS_WINDOW PACKAGE_ID",
            file=sys.stderr,
        )
        return 2

    path = Path(arguments[1])
    try:
        text = path.read_text(errors="replace")
    except OSError as error:
        print(f"unable to read {path}: {error}", file=sys.stderr)
        return 2

    if has_visible_window(text, arguments[2]):
        return 0
    print(f"no visible window found for {arguments[2]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
