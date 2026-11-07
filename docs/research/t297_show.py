#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-297 — 只打印:干净事件集(S-777 两条守卫)的 wo 0/1 × 1/7/30 天中位、随机分位、两半、事件数,
以及被守卫剔掉那批的单独中位。数字全部来自 t297_results.json,不重算。

用法: python3 docs/research/t297_show.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "t297_results.json")))


def med(block, path):
    cur = block
    for p in path:
        cur = (cur or {}).get(p)
        if cur is None:
            return None
    return cur


for nm in ("squeeze", "flush"):
    ev = R["events"][nm]
    dr = R["dropped"][nm]
    print("=" * 78)
    print("%s: clean n=%d  (legacy n=%d, dropped %d, added %d)  by_year=%s"
          % (nm, ev["n"], dr["n_legacy"], dr["n_dropped"], dr["n_added"], ev["by_year"]))
    print("  dropped_by: %s" % dr["dropped_by"])
    for wo in ("0", "1"):
        for H in ("1", "7", "30"):
            b = R["results"][nm][H][wo]
            full = b["full"]["excess"]
            nul = b["null"]["full"]
            print("  wo=%s H=%-2s n=%-3d median=%+.4f  null_pctl=%.3f  H1=%s  H2=%s"
                  % (wo, H, full.get("n", 0), full.get("median", float("nan")),
                     nul.get("null_median_pctl", float("nan")),
                     ("%+.4f(n=%d)" % (med(b, ["H1", "excess", "median"]), med(b, ["H1", "excess", "n"]))),
                     ("%+.4f(n=%d)" % (med(b, ["H2", "excess", "median"]), med(b, ["H2", "excess", "n"])))))
    print("  -- legacy(S-768 ① 原口径,同一次运行复算) --")
    for wo in (0, 1):
        for H in (1, 7, 30):
            b = dr["legacy_stats"]["H%d|wo%d" % (H, wo)]["excess"]
            print("  legacy wo=%d H=%-2d n=%-3d median=%+.4f" % (wo, H, b.get("n", 0), b.get("median", float("nan"))))
    print("  -- 被剔掉那批(legacy − clean)的单独中位 --")
    for wo in (0, 1):
        for H in (1, 7, 30):
            b = dr["dropped_stats"]["H%d|wo%d" % (H, wo)]
            print("  dropped wo=%d H=%-2d n=%-3d median=%s  H1=%s  H2=%s"
                  % (wo, H, b["n"], ("%+.4f" % b["excess"]["median"]) if b["excess"].get("median") is not None else "n/a",
                     ("%+.4f(n=%d)" % (b["H1"]["excess"].get("median", float("nan")), b["H1"]["n"])) if b["H1"]["n"] else "n/a",
                     ("%+.4f(n=%d)" % (b["H2"]["excess"].get("median", float("nan")), b["H2"]["n"])) if b["H2"]["n"] else "n/a"))
    syms = {}
    for e in dr["dropped_events"]:
        syms[e["sym"]] = syms.get(e["sym"], 0) + 1
    print("  被剔掉的合约: %s" % dict(sorted(syms.items(), key=lambda kv: -kv[1])))
    print("  被剔掉的事件(日期/合约): %s" % ", ".join("%s/%s" % (e["d"], e["sym"]) for e in dr["dropped_events"][:40]))
