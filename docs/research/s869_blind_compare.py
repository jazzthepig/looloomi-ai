#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-391 对账:我的盲复算 vs Seth 的 S-869 表。

**顺序**:`s869_blind_results.json` 先落盘,这一步才读 `s869_results.json`(卡上的规定)。
不改任何一边去凑:不一致的格子两边都列出来。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETH = "/Users/sbb/Projects/looloomi-ai/docs/research/s869_results.json"
MINE = os.path.join(HERE, "s869_blind_results.json")

STRAT_MAP = {"核心": "core", "X1V": "x1v", "ACWI": "equity", "XAUUSD": "gold", "R-v2": "rv2"}
STATE_MAP = {"线上·注": "T线上·L注", "线下·注": "T线下·L注",
             "线下·抽": "T线下·L抽", "线上·抽": "T线上·L抽"}


def s_state(name: str) -> str:
    return STATE_MAP.get(name, name)


def s_strat(name: str) -> str:
    return STRAT_MAP.get(name, name)


def mine_table():
    return json.load(open(MINE))["table"]


def seth_table():
    return json.load(open(SETH))["table"]


def compare(verbose=True):
    mine = mine_table()
    seth = seth_table()
    rows = []
    for key, m in mine.items():
        s, st = m["strategy"], m["state"]
        sc = seth[s_strat(s)][s_state(st)]
        ann_vol = m["vol"] * math.sqrt(365.0) if m["vol"] is not None else None
        ratio_ann = (m["ann_excess"] / ann_vol) if (m["ann_excess"] is not None and ann_vol) else None
        rows.append({
            "key": key, "seth_key": f"{s_strat(s)}|{s_state(st)}",
            "days": (m["days"], sc["n_days"]), "segs": (m["segments"], sc["n_episodes"]),
            "ann": (m["ann_excess"], sc["ann_in"]),
            "vol_ann": (ann_vol, sc["vol_in"]),
            "ratio_sharpe": (m["mean_vol"], sc["ratio_in"]),
            "ratio_ann": (ratio_ann, sc["ratio_in"]),
            "pos_seg": (m["pos_seg_frac"], sc["pos_episodes"]),
            "ann_after": (m["ann_after_best"], sc["ann_in_without_best_episode"]),
            "ann_out": (m["out_ann_excess"], sc["ann_out"]),
            "worst": (m["worst_seg"], sc["worst_episode"]),
            "strength": (m["all_pass"], sc["strength"]),
        })
    return rows


def report(field, tol):
    rows = compare()
    bad = []
    for r in rows:
        a, b = r[field]
        if a is None or b is None:
            if (a is None) != (b is None):
                bad.append((r["key"], a, b))
            continue
        if abs(a - b) > tol:
            bad.append((r["key"], a, b))
    print(f"{field}: 不一致 {len(bad)}/{len(rows)} (tol={tol})")
    for k, a, b in bad[:15]:
        print(f"   {k:24s} mine={a} seth={b}")
    return bad


if "--compare" in sys.argv:
    rows = compare()
    report("days", 0)
    report("segs", 0)
    report("ann", 0.002)
    report("vol_ann", 0.002)
    report("ratio_sharpe", 0.002)
    report("ratio_ann", 0.002)
    report("pos_seg", 0.002)
    report("ann_after", 0.002)
    report("ann_out", 0.002)
    report("worst", 0.002)
    bad = [r for r in rows if r["strength"][0] != r["strength"][1]]
    print(f"strength: 不一致 {len(bad)}/{len(rows)}")
    for r in bad:
        print("   ", r["key"], "mine", r["strength"][0], "seth", r["strength"][1])
    sys.exit(0)

if "--peek" in sys.argv:
    s = json.load(open(SETH))
    print("rules:", json.dumps(s["rules"], ensure_ascii=False))
    print("n_cells_judged:", s["n_cells_judged"])
    print("state keys per strategy (core):", list(s["table"]["core"].keys()))
    print("strengths:", json.dumps(s["strengths"], ensure_ascii=False))
    sys.exit(0)

mine = mine_table()
seth = seth_table()
print("mine cells:", len(mine), "| seth strategies:", len(seth))
