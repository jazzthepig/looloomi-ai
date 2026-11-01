#!/usr/bin/env python3
"""T-217 —— beta_core_nav / risk_meter_history 的写入口径判据:
这两张表的 interval_hours / void_reason 说明它们**不是**严格每日一行,
所以「缺失天数」不能当连续性断档来读。先判口径,再报数。"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent


def get(path, **kw):
    q = urllib.parse.urlencode(kw, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + q, headers=H)
    with urllib.request.urlopen(req, timeout=120) as x:
        return json.loads(x.read().decode() or "[]")


rows = get("beta_core_nav", select="mark_date,marked_at,interval_hours,void_reason,mark_source",
           order="mark_date.asc")
print("### beta_core_nav  rows:", len(rows))
ds = [r["mark_date"] for r in rows]
print("  mark_date 唯一数:", len(set(ds)), "| 首/末:", min(ds), max(ds))
print("  void_reason 非空行数:", sum(1 for r in rows if r.get("void_reason")))
for r in rows:
    if r.get("void_reason"):
        print("    VOID", r["mark_date"], "| void_reason:", str(r.get("void_reason"))[:80],
              "| mark_source:", r.get("mark_source"))
print("  interval_hours 分布:", dict(Counter(str(r.get("interval_hours")) for r in rows)))
print("  mark_source 分布:", dict(Counter(str(r.get("mark_source")) for r in rows)))

rh = get("risk_meter_history", select="d,computed_at,band,regime", order="d.asc")
print()
print("### risk_meter_history  rows:", len(rh))
ds2 = [r["d"] for r in rh]
print("  d 唯一数:", len(set(ds2)), "| 首/末:", min(ds2), max(ds2))
print("  computed_at 样例:", [r.get("computed_at") for r in rh[:3]])
print("  computed_at 唯一数:", len({r.get("computed_at") for r in rh}))
