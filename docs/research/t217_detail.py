#!/usr/bin/env python3
"""T-217 —— 明细打印:hl_book_daily 晚写行 / 循环失败原因 / write_health / proof 锚点。"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent
d = json.load(open(HERE / "t217_final2.json"))

# ---- hl_book_daily 逐行:computed_at 晚于 d+2 的行 + correction 非空的行 ----
url = (SB + "/rest/v1/hl_book_daily?select=d,computed_at,correction,decided,held,is_decision"
       "&order=d.asc")
req = urllib.request.Request(url, headers=H)
with urllib.request.urlopen(req, timeout=90) as r:
    rows = json.loads(r.read().decode() or "[]")
print("### hl_book_daily 逐行(n=%d)" % len(rows))
for x in rows:
    d0 = x.get("d")
    t = x.get("computed_at")
    lag = None
    if t and d0:
        try:
            lag = (dt.datetime.fromisoformat(str(t).replace("Z", "+00:00")).date()
                   - dt.date.fromisoformat(str(d0)[:10])).days
        except Exception:  # noqa: BLE001
            lag = None
    corr = x.get("correction")
    flag = ""
    if lag is not None and lag > 2:
        flag += " LATE(lag=%d)" % lag
    if corr not in (None, "", [], {}):
        flag += " CORRECTION(%s)" % str(corr)[:80]
    if flag:
        print("  ", d0, t, "lag=", lag, "decided=", x.get("decided"), "held=", x.get("held"),
              "is_decision=", x.get("is_decision"), flag)

print()
print("### 循环失败(近 24h 聚合,rpc/loop_attempt_health)")
for r in d["loop_rpc"].get("loops_with_fail", []):
    print("  %-34s fail24h=%-4s last_fail=%s reason=%s" % (
        str(r["loop"])[:34], r["n_fail_24h"], r["last_fail"], str(r["last_reason"])[:150]))
print("  -- 汇总: loops=%s fail24h合计=%s ok24h合计=%s 有失败循环数=%s timeout类=%s" % (
    d["loop_rpc"]["n_loops"], d["loop_rpc"]["sum_fail_24h"], d["loop_rpc"]["sum_ok_24h"],
    d["loop_rpc"]["n_loops_fail24h"], d["loop_rpc"]["n_loops_timeout_reason"]))
print("  -- 时间点最晚的 12 个失败:")
for r in sorted([x for x in d["loop_rpc"]["loops"] if x["last_fail"]],
                key=lambda x: x["last_fail"], reverse=True)[:12]:
    print("     %s  %-30s fail24h=%s  %s" % (r["last_fail"], str(r["loop"])[:30],
                                             r["n_fail_24h"], str(r["last_reason"])[:110]))

print()
print("### write_health(rpc)")
w = d.get("write_health", {})
print("  tables=%s with_fail=%s sum_fail_24h=%s" % (w.get("n_tables"), w.get("n_with_fail"),
                                                   w.get("sum_fail_24h")))
for r in w.get("rows", []):
    if r.get("last_fail"):
        print("   %-34s fail24h=%-3s last_fail=%s body=%s" % (
            str(r["table"])[:34], r["n_fail_24h"], r["last_fail"], str(r["last_body"])[:120]))

print()
print("### proof/anchors")
print(d["proof"]["/api/v1/proof/anchors"]["head"][:1400])
print()
print("### proof/books")
print(d["proof"]["/api/v1/proof/books"]["head"][:1200])
