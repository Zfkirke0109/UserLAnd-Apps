#!/usr/bin/env python3
"""Locate a node in a uiautomator dump and print its centre coordinates.

Taps derived from the UI tree survive density and API-level differences that
silently move fixed screen coordinates, which is how a real regression turns
into a green run.
"""
import argparse
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def centre(node: ET.Element) -> tuple[int, int] | None:
    match = BOUNDS.fullmatch(node.get("bounds", ""))
    if match is None:
        return None
    x1, y1, x2, y2 = (int(value) for value in match.groups())
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1 + x2) // 2, (y1 + y2) // 2


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ui")
    parser.add_argument("--package")
    parser.add_argument("--text", action="append", default=[])
    parser.add_argument("--resource-suffix", action="append", default=[])
    parser.add_argument("--first-clickable", action="store_true")
    args = parser.parse_args(argv[1:])

    try:
        root = ET.parse(Path(args.ui)).getroot()
    except (OSError, ET.ParseError) as error:
        print(f"unreadable UI tree {args.ui}: {error}", file=sys.stderr)
        return 2

    for node in root.iter("node"):
        if args.package and node.get("package") != args.package:
            continue
        position = centre(node)
        if position is None:
            continue

        resource = node.get("resource-id", "")
        text = (node.get("text") or "").strip()
        if any(resource.endswith(suffix) for suffix in args.resource_suffix):
            print(*position)
            return 0
        if text and text in args.text:
            print(*position)
            return 0
        if args.first_clickable and node.get("clickable") == "true":
            # An entry the user could actually press: it has to say something.
            if text or node.get("content-desc") or resource:
                print(*position)
                return 0

    print("no matching UI node", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
