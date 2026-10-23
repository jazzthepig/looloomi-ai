"""T-184 诊断:卡上 6/17 用的是「35 天内水平累计 >1.5%」,逐周台阶口径是 5/17。
找出两种口径各自点名了谁,差的那一个是谁。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t184_endpoint_pin as T184  # noqa: E402

syms, _ = T184.universe()
raw = T184.shares_series(syms)
cutoff, _ = T184.last_full_friday(raw)
rows = T184.window_rows(T184.series_at(raw, cutoff), 364)
names = {r["key"] for r in T184.flagged(rows)}
inl = [r for r in rows if r["key"] in names]
outl = [r for r in rows if r["key"] not in names]

print("名单内 —— 累计口径命中:")
for r in sorted(inl, key=lambda x: -abs(x["cum35_pct"])):
    if abs(r["cum35_pct"]) > 1.5:
        print(f"  {r['key']:6s} cum35={r['cum35_pct']:+7.2f}%  逐周>1.5% 的步数={r['n_early']}"
              f"  40天内步: {r['early_all'] or '(无)'}")
print("名单外 —— 累计口径命中:")
for r in sorted(outl, key=lambda x: -abs(x["cum35_pct"])):
    if abs(r["cum35_pct"]) > 1.5:
        print(f"  {r['key']:6s} cum35={r['cum35_pct']:+7.2f}%  逐周>1.5% 的步数={r['n_early']}")