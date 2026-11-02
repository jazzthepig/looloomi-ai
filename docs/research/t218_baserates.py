#!/usr/bin/env python3
"""T-218:命题变量的历史基准率(state/macro 日频),供 ③ 的 prob 锚定。"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent


def sb(path, params):
    """全量翻页,每页带 order=(PostgREST 单页上限 1000)。"""
    rows, off = [], 0
    while True:
        p = dict(params)
        p.update({"order": "d.asc", "limit": "1000", "offset": str(off)})
        q = urllib.parse.urlencode(p, safe="().,:*$")
        req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + q, headers=H)
        with urllib.request.urlopen(req, timeout=120) as r:
            b = r.read().decode()
            chunk = json.loads(b) if b else []
        if not chunk:
            return rows
        rows.extend(chunk)
        if len(chunk) < 1000:
            return rows
        off += 1000
        if off > 20000:
            return rows


def main():
    out = {}
    for feat, tests in (
        ("stable_supply_30d", [("gt0", lambda v: v > 0), ("lt0", lambda v: v < 0)]),
        ("breadth_above_ma50", [("gt0.5", lambda v: v > 0.5), ("gt0.25", lambda v: v > 0.25)]),
        ("funding_7d_ann", [("lt0.15", lambda v: v < 0.15), ("gt0.10", lambda v: v > 0.10)]),
        ("mom_20", [("gt0", lambda v: v > 0)]),
        ("vol_30", [("gt0.40", lambda v: v > 0.40)]),
    ):
        rows = sb("state_daily", {"feature": f"eq.{feat}"})
        vals = [r["value"] for r in rows if r.get("value") is not None]
        if not vals:
            continue
        out[feat] = {"n": len(vals), "last": vals[-1],
                     "freq": {name: round(sum(1 for v in vals if f(v)) / len(vals), 3)
                              for name, f in tests}}
    for ser, tests in (
        ("fng", [("45-75", lambda v: 45 <= v <= 75), ("gt60", lambda v: v > 60)]),
        ("vix", [("lt18", lambda v: v < 18), ("gt25", lambda v: v > 25)]),
    ):
        rows = sb("macro_daily", {"series": f"eq.{ser}"})
        vals = [r["value"] for r in rows if r.get("value") is not None]
        if not vals:
            continue
        out["macro:" + ser] = {"n": len(vals), "last": vals[-1],
                               "freq": {name: round(sum(1 for v in vals if f(v)) / len(vals), 3)
                                        for name, f in tests}}
    (HERE / "t218_baserates.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
