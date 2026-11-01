#!/usr/bin/env python3
"""T-217 —— 复核 §3.5 write_health 数字(100 张表逐张)。"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
w = json.load(open(HERE / "t217_write_health.json"))

print("tables:", len(w))
with_fail = [x for x in w if x.get("last_fail")]
print("with last_fail:", len(with_fail))
print("sum n_fail_24h (all tables):", sum(int(x.get("n_fail_24h") or 0) for x in w))
print()
print("### 表有 n_fail_24h > 0")
for x in sorted([y for y in w if int(y.get("n_fail_24h") or 0) > 0],
                key=lambda z: -int(z.get("n_fail_24h") or 0)):
    print("   %-34s n_fail_24h=%-3s last_fail=%-27s %s" % (
        x.get("table_name"), x.get("n_fail_24h"), str(x.get("last_fail"))[:26],
        str(x.get("last_body") or "")[:110]))
print()
print("### 有 last_fail 但 last_body 为空(不可归因)")
for x in with_fail:
    if not x.get("last_body"):
        print("   %-34s n_fail_24h=%-3s last_fail=%s" % (
            x.get("table_name"), x.get("n_fail_24h"), str(x.get("last_fail"))[:30]))
