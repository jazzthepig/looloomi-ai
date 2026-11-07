"""T-292 拉数(第 3 版):并行 offset 拉取。

为什么:整表 ORDER BY market,d 的单线程 offset 扫描实测 ~4s/页(329 页 ≈ 22 分钟);
Range 头之间没有依赖(offset 可以任意取),所以按 offset 交错分给 8 个线程即可线性加速。
纪律:每页 ≤1000 行、每页带 order=(market.asc,d.asc / symbol.asc,trade_date.asc)、抓完核总行数(Prefer: count=exact)。
产出(Mac 数据根,不落仓库):<T292_CACHE>/upbit_daily.jsonl / ohlcv_binance_hist.csv / mcap.jsonl / pull_summary.json
"""
import json
import os
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
OUT = os.environ.get("T292_CACHE", "/Volumes/CometCloudAI/cometcloud-local/research/_cache/t292")
os.makedirs(OUT, exist_ok=True)
PAGE = 1000
WIN = "2020-12-01"
WORKERS = 8
T0 = time.time()
LOCK = threading.Lock()


def log(m):
    with LOCK:
        print("[%6.1fs] %s" % (time.time() - T0, m), flush=True)


def req(path, rng=None, tries=5, timeout=90):
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    if rng:
        h["Range"] = rng
    last = None
    for a in range(tries):
        try:
            r = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=h)
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                return resp.read().decode()
        except Exception as e:
            last = e
            time.sleep(0.8 * (a + 1))
    raise RuntimeError(f"GET failed: {path}: {last}")


def count_of(path):
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"}
    r = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=h)
    with urllib.request.urlopen(r, timeout=180) as resp:
        cr = resp.headers.get("Content-Range", "")
    tail = cr.rsplit("/", 1)[1] if "/" in cr else "*"
    return None if tail == "*" else int(tail)


def pull_offsets(path, expect):
    """把 offset 0,1,2,... 的页分给线程;每页独立,无依赖。返回 (rows, 页数)。"""
    npages = (expect + PAGE - 1) // PAGE
    offsets = list(range(npages))

    def one(k):
        got = json.loads(req(path, rng=f"{k * PAGE}-{(k + 1) * PAGE - 1}"))
        return k, got

    rows, seen = [], set()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for k, got in ex.map(one, offsets):
            rows.extend(got)
            seen.add(k)
            if len(seen) % 40 == 0:
                log("  %s: %d/%d pages rows=%d" % (path[:28], len(seen), npages, len(rows)))
    return rows, npages


# ── 1. upbit_daily ──────────────────────────────────────────────────────────
log("upbit_daily ...")
UP_PATH = ("upbit_daily?select=market,symbol,d,c,vol_krw&d=gte.%s&order=market.asc,d.asc" % WIN)
up_expect = count_of(UP_PATH)
log("  expected rows=%s" % up_expect)
up_rows, _ = pull_offsets(UP_PATH, up_expect)
# 去重((market,d) 应当唯一)
seen = set()
uniq = []
for r in up_rows:
    k = (r["market"], r["d"])
    if k in seen:
        continue
    seen.add(k)
    uniq.append(r)
up_rows = sorted(uniq, key=lambda r: (r["market"], r["d"]))
log("upbit rows=%d (unique) dup_dropped=%d markets=%d" % (
    len(up_rows), len(up_rows) - len(seen), len({r["market"] for r in up_rows})))
with open(f"{OUT}/upbit_daily.jsonl", "w") as f:
    for r in up_rows:
        f.write(json.dumps(r) + "\n")
syms = sorted({r["symbol"] for r in up_rows})
with open(f"{OUT}/upbit_symbols.json", "w") as f:
    json.dump(syms, f, indent=1)
log("symbols=%d" % len(syms))

# ── 2. ohlcv_daily(binance_hist),只拉 Upbit 覆盖的代号 ──────────────────────
log("ohlcv_daily binance_hist (%d symbols) ..." % len(syms))


def fetch_ohlcv(sym):
    p = ("ohlcv_daily?select=symbol,trade_date,close,volume&source=eq.binance_hist"
         "&symbol=eq.%s&trade_date=gte.%s&order=symbol.asc,trade_date.asc" % (sym, WIN))
    out, start = [], 0
    while True:
        got = json.loads(req(p, rng=f"{start}-{start + PAGE - 1}"))
        if not got:
            break
        out.extend(got)
        start += len(got)
        if len(got) < PAGE:
            break
    return out


oh = []
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    for i, rows in enumerate(ex.map(fetch_ohlcv, syms), 1):
        oh.extend(rows)
        if i % 50 == 0:
            log("  ohlcv %d/%d symbols rows=%d" % (i, len(syms), len(oh)))
log("ohlcv rows=%d symbols=%d" % (len(oh), len({r["symbol"] for r in oh})))
with open(f"{OUT}/ohlcv_binance_hist.csv", "w") as f:
    f.write("symbol,trade_date,close,volume\n")
    for r in oh:
        f.write("%s,%s,%s,%s\n" % (r["symbol"], r["trade_date"], r.get("close"), r.get("volume")))

# ── 3. asset_mcap_daily ─────────────────────────────────────────────────────
log("asset_mcap_daily ...")


def fetch_mcap(sym):
    p = ("asset_mcap_daily?select=symbol,d,price,mcap,volume&symbol=eq.%s&d=gte.%s"
         "&order=symbol.asc,d.asc" % (sym, WIN))
    out, start = [], 0
    while True:
        got = json.loads(req(p, rng=f"{start}-{start + PAGE - 1}"))
        if not got:
            break
        out.extend(got)
        start += len(got)
        if len(got) < PAGE:
            break
    return out


mc = []
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    for i, rows in enumerate(ex.map(fetch_mcap, syms), 1):
        mc.extend(rows)
        if i % 50 == 0:
            log("  mcap %d/%d symbols rows=%d" % (i, len(syms), len(mc)))
log("mcap rows=%d symbols=%d" % (len(mc), len({r["symbol"] for r in mc})))
with open(f"{OUT}/mcap.jsonl", "w") as f:
    for r in mc:
        f.write(json.dumps(r) + "\n")

summary = {
    "window_start": WIN,
    "upbit_rows": len(up_rows),
    "upbit_expected_rows": up_expect,
    "upbit_markets": len({r["market"] for r in up_rows}),
    "upbit_symbols": len(syms),
    "upbit_d_range": [min(r["d"] for r in up_rows), max(r["d"] for r in up_rows)],
    "ohlcv_rows": len(oh),
    "ohlcv_symbols": len({r["symbol"] for r in oh}),
    "ohlcv_d_range": [min(r["trade_date"] for r in oh), max(r["trade_date"] for r in oh)],
    "mcap_rows": len(mc),
    "mcap_symbols": len({r["symbol"] for r in mc}),
}
with open(f"{OUT}/pull_summary.json", "w") as f:
    json.dump(summary, f, indent=1)
print(json.dumps(summary, indent=1), flush=True)
print("DONE", flush=True)
