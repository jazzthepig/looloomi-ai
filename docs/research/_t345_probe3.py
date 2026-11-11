"""T-345 探针 3:给前向预期测基率(BTC 收盘方向、funding_7d_ann、vol_30)。

只读库。基率 = 我们自己库里最近 N 个观测里「N 日后更高」的比例。
"""
from __future__ import annotations

import json
import os
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]


def fetch(table: str, query: str, order: str) -> list[dict]:
    rows, start, total = [], 0, None
    while True:
        req = urllib.request.Request(
            f"{URL}/rest/v1/{table}?{query}&order={order}",
            headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                     "Prefer": "count=exact", "Range": f"{start}-{start + 999}"},
        )
        with urllib.request.urlopen(req, timeout=180) as r:
            cr = r.headers.get("Content-Range", "")
            page = json.loads(r.read().decode())
        if total is None and "/" in cr:
            total = int(cr.split("/")[-1])
        rows.extend(page)
        if len(page) < 1000:
            break
        start += 1000
        if total is not None and start >= total:
            break
    if total is not None and len(rows) != total:
        raise SystemExit(f"{table}: 抓到 {len(rows)} 行 ≠ total {total}")
    return rows


# ── BTC:35 个交易日后的收盘方向 ──────────────────────────────────────────────
btc = fetch("ohlcv_daily", "select=trade_date,close&symbol=eq.BTC&source=eq.binance_hist"
                           "&order=trade_date.desc&limit=1000", "trade_date.desc")
cl = [(r["trade_date"], float(r["close"])) for r in btc if r.get("close") is not None]
cl.reverse()
H = 35
pairs = [(cl[i][1], cl[i + H][1]) for i in range(len(cl) - H)]
up = sum(1 for a, b in pairs if b > a)
print(f"BTC binance_hist: n_rows={len(cl)} first={cl[0][0]} last={cl[-1][0]} last_close={cl[-1][1]:.4f}")
print(f"  base rate 35 交易日后更高: {up}/{len(pairs)} = {up / len(pairs):.4f}")

# ── state_daily:两个 feature,35 日后的方向 ─────────────────────────────────
rows = fetch("state_daily", "select=d,feature,value&entity=eq.panel"
                           "&feature=in.(funding_7d_ann,vol_30)&order=d.asc", "d.asc")
byf = {}
for r in rows:
    if r.get("value") is None:
        continue
    byf.setdefault(r["feature"], []).append((r["d"], float(r["value"])))
for feat, ser in byf.items():
    vals = [v for _, v in ser]
    pairs = [(vals[i], vals[i + H]) for i in range(len(vals) - H)]
    up = sum(1 for a, b in pairs if b > a)
    print(f"{feat}: n={len(ser)} first={ser[0][0]} last={ser[-1][0]} last_value={vals[-1]:.6f}")
    print(f"  base rate 35 日后更高: {up}/{len(pairs)} = {up / len(pairs):.4f}")
