#!/usr/bin/env python3
"""T-210:把 t210_cites.json 里指定页面的引文打出来(报告里每句话都要在这里核到)。

用法:python3 t210_cites_show.py <page_key> [<page_key> ...]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPACT = 3
d = json.load(open(os.path.join(HERE, "t210_cites.json")))
pages = d["pages"]

for name in (sys.argv[1:] or sorted(pages)):
    p = pages.get(name)
    print("==", name, p.get("url") if p else "MISSING")
    if not p:
        continue
    if p.get("error"):
        print("   ERROR:", str(p["error"])[:220])
        print()
        continue
    print("   chars:", p.get("chars"), "| keywords:", p.get("keywords"))
    lim = COMPACT if os.environ.get("T210_COMPACT") == "1" else 999
    width = 300 if lim == 3 else 460
    for q in (p.get("quotes") or [])[:lim]:
        if isinstance(q, dict):
            s = " ".join(str(q.get("text", "")).split())
            print(f"   - [{q.get('kw')}] {s[:width]}")
        else:
            print("   -", " ".join(str(q).split())[:width])
    print()
