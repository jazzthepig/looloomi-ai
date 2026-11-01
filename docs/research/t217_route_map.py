#!/usr/bin/env python3
"""T-217 helper: map @app/@router decorators to line numbers in a source file,
so we can find which route encloses a given table reference."""
from __future__ import annotations

import re
import sys

DEC = re.compile(r'^\s*@(app|router)\.(get|post|put|delete)\(\s*"([^"]+)"')


def main() -> None:
    path = sys.argv[1]
    needles = sys.argv[2:]
    with open(path) as f:
        lines = f.readlines()
    routes = []
    for i, ln in enumerate(lines, 1):
        m = DEC.match(ln)
        if m:
            routes.append((i, m.group(3)))
    for i, ln in enumerate(lines, 1):
        if any(n in ln for n in needles):
            owner = None
            for ri, rpath in routes:
                if ri <= i:
                    owner = (ri, rpath)
                else:
                    break
            print(f"{i}: {ln.strip()[:110]}")
            print(f"    -> enclosing route: {owner}")


if __name__ == "__main__":
    main()
