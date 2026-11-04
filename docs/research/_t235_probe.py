"""T-235 probe: 本地 bars 与 DB 的差异到底是什么(量纲?对?来源?)。重写同一文件再跑。"""
import json
import os
import urllib.request
from collections import Counter, defaultdict

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}
ROOT = "/Volumes/CometCloudAI/cometcloud-local"


def pull(table, query, step=5000):
    rows, off, total = [], 0, -1
    while True:
        h = dict(H)
        h["Range"] = f"{off}-{off+step-1}"
        req = urllib.request.Request(f"{U}/rest/v1/{table}?{query}", headers=h)
        try:
            resp = urllib.request.urlopen(req, timeout=300)
        except urllib.error.HTTPError as e:
            if e.code == 416:
                break
            raise
        with resp:
            cr = resp.headers.get("Content-Range", "")
            body = json.loads(resp.read())
        rows.extend(body)
        if "/" in cr:
            total = int(cr.split("/")[-1])
        off += len(body)
        if not body or total < 0 or off >= total:
            break
    return rows


tix = json.load(open(f"{ROOT}/research/t159/_tickets_2020-03-01_2026-06-20.json"))
symbols = {t["symbol"] for t in tix["long"]} | {"BTC"}

loc = defaultdict(dict)
for f in ("t156/_bars_early.jsonl", "t156/_bars.jsonl", "t159/_bars.jsonl"):
    for line in open(f"{ROOT}/research/{f}"):
        for r in json.loads(line):
            if r["symbol"] in symbols:
                loc[r["symbol"]][r["trade_date"][:10]] = (float(r["close"]), float(r["volume"]))

print("== ohlcv_daily source 分布 ==")
c = Counter(r["source"] for r in pull("ohlcv_daily", "select=source&limit=3000"))
print(c)

db = defaultdict(dict)
for r in pull("ohlcv_daily", "select=symbol,trade_date,close,volume&source=eq.binance_hist"
                        "&trade_date=gte.2021-01-01&trade_date=lte.2023-12-31&order=symbol.asc,trade_date.asc"):
    if r["symbol"] in symbols:
        db[r["symbol"]][r["trade_date"][:10]] = (float(r["close"]), float(r["volume"]))

print("\n== 逐符号:量能(close×volume)中位数对比 local vs DB (2021-2023) ==")
print(f"{'sym':8} {'n_loc':>6} {'n_db':>6} {'turn_loc':>14} {'turn_db':>14} {'ratio':>8} {'close_ratio':>11}")
rows_out = []
for s in sorted(loc):
    tl = [loc[s][d][0] * loc[s][d][1] for d in loc[s] if "2021-01-01" <= d <= "2023-12-31"]
    td = [db[s][d][0] * db[s][d][1] for d in db.get(s, {})]
    cl = [loc[s][d][0] for d in loc[s] if "2021-01-01" <= d <= "2023-12-31"]
    cd = [db[s][d][0] for d in db.get(s, {})]
    if not tl or not td:
        continue
    tl.sort(); td.sort(); cl.sort(); cd.sort()
    ratio = td[len(td)//2] / tl[len(tl)//2] if tl[len(tl)//2] else float("nan")
    cr = cd[len(cd)//2] / cl[len(cl)//2] if cl[len(cl)//2] else float("nan")
    rows_out.append((s, len(tl), len(td), tl[len(tl)//2], td[len(td)//2], ratio, cr))
for r in rows_out[:14]:
    print(f"{r[0]:8} {r[1]:6} {r[2]:6} {r[3]:14.0f} {r[4]:14.0f} {r[5]:8.3f} {r[6]:11.5f}")
print("...")
print("turnover ratio 分位:", [round(x, 3) for x in sorted(r[5] for r in rows_out)[::max(1, len(rows_out)//8)]])
print("close   ratio 分位:", [round(x, 5) for x in sorted(r[6] for r in rows_out)[::max(1, len(rows_out)//8)]])
print("volume 完全相同的符号数:", sum(1 for r in rows_out if abs(r[5]-1) < 1e-9))
