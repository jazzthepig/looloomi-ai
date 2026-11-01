#!/usr/bin/env python3
"""T-217 —— 两件收尾核对:(1) write_health 的真实列名 (2) 「n == 首末跨度+1」的日历连续性算术核对。"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent
d = json.load(open(HERE / "t217_final2.json"))

print("### write_health 原始列名 + 有失败的行")
req = urllib.request.Request(SB + "/rest/v1/rpc/write_health", headers=H)
with urllib.request.urlopen(req, timeout=90) as r:
    w = json.loads(r.read().decode() or "[]")
if w:
    print("   keys:", list(w[0].keys()))
    for x in w:
        if x.get("last_fail"):
            print("   ", json.dumps({k: (str(v)[:90] if v is not None else None) for k, v in x.items()},
                                   ensure_ascii=False))

print()
print("### 臂级日历连续性算术核对(n 是否等于首末跨度+1)")
bad = []
for t, s in d["series"].items():
    for a in (s.get("arms") or []):
        f, l, n = a.get("first"), a.get("last"), a.get("n")
        try:
            span = (dt.date.fromisoformat(l) - dt.date.fromisoformat(f)).days + 1
        except Exception:  # noqa: BLE001
            print("   ??", t, a.get("arm"), f, l, n)
            continue
        ok = (n == span)
        if not ok:
            bad.append((t, a.get("arm"), f, l, n, span))
        print("   %-22s %-24s %s..%s n=%-5s span=%-5s %s" % (
            t, str(a.get("arm"))[:24], f, l, n, span, "连续" if ok else "缺 %d 天" % (span - n)))
print("   不连续臂数:", len(bad))

print()
print("### 直读表:整表(所有臂合并)的日期轴")
for t, a in d["direct"].items():
    arms = a.get("arms") or []
    if not arms:
        continue
    miss = sum(x.get("missing_cal", 0) for x in arms)
    gaps = [x.get("longest_gap_cal") for x in arms if x.get("longest_gap_cal")]
    print("   %-22s 臂=%-3d 缺失合计=%-3d 最长缺口=%s" % (t, len(arms), miss, gaps or "无"))
