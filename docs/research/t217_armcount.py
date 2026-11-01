#!/usr/bin/env python3
"""T-217 —— 核对臂数口径:直读臂 / 公开接口臂 / 两通道并集(唯一 table+arm 对)。

含 t217_final2.json(主脚本 7 张直读表 + 7 张公开接口表)与
t217_extra_tables.json(补扫的 4 张表:cis_official_daily / signal_journal /
beta_core_nav / risk_meter_history)。
signal_journal 是**事件表**不是按日表,单独列出,不计入按日连续性的臂数。
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
d = json.load(open(HERE / "t217_final2.json"))
ex = json.load(open(HERE / "t217_extra_tables.json"))

EVENT_TABLES = {"signal_journal"}

sarms, darms = set(), set()
for t, s in d["series"].items():
    for a in (s.get("arms") or []):
        sarms.add((t, str(a.get("arm"))))
for t, a in d["direct"].items():
    for r in (a.get("arms") or []):
        darms.add((t, str(r.get("arm"))))
extra = {}
for t, blk in ex.items():
    if "error" in blk:
        continue
    extra[t] = len(blk["arms"])
    for a in blk["arms"]:
        darms.add((t, str(a["arm"])))

daily_darms = {p for p in darms if p[0] not in EVENT_TABLES}

print("series per-table:", {t: len(s.get("arms") or []) for t, s in d["series"].items()})
print("series arms total:", len(sarms))
print("direct per-table (main):", {t: len(a.get("arms") or []) for t, a in d["direct"].items()})
print("direct per-table (extra):", extra)
print("direct arms total (含事件表):", len(darms))
print("overlap (same table+arm in both):", len(sarms & darms))
print("union unique table+arm pairs (含事件表):", len(sarms | darms))
print()
print("== 按日口径(剔除事件表 %s)==" % sorted(EVENT_TABLES))
print("  直读按日臂:", len(daily_darms))
print("  公开接口臂:", len(sarms))
print("  并集唯一 table+arm 对:", len(daily_darms | sarms))
print("  series-only tables:", sorted({t for t, _ in sarms} - {t for t, _ in darms}))
print("  direct-only tables:", sorted({t for t, _ in darms} - {t for t, _ in sarms}))
