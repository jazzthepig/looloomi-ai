"""T-299 拉数:perp_bv_daily(2019-10-01 → 2023-01-31,USDT 永续)+ perp_bv_pairs + asset_mcap_daily(2020→2022)。

纪律:按 symbol 分片、Range 翻页(每页 ≤1000)、每个查询带 order=、抓完核总行数。
产出(在 Mac 数据根,不落仓库):<T299_CACHE>/perp_bv_early.jsonl / pairs.json / mcap.jsonl / pull_summary.json
T299_CACHE 默认 /Volumes/CometCloudAI/cometcloud-local/research/_cache/t299 —— 与 t299_leadlag.py 读的是同一个目录。
"""
import json
import os
import time
import urllib.request
from collections import Counter

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
OUT = os.environ.get("T299_CACHE", "/Volumes/CometCloudAI/cometcloud-local/research/_cache/t299")
os.makedirs(OUT, exist_ok=True)
PAGE = 1000
EXACT = {"Prefer": "count=exact"}
T0 = time.time()


def log(m):
    print("[%6.1fs] %s" % (time.time() - T0, m), flush=True)


def req(path, rng=None, extra=None, tries=4):
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    if rng:
        h["Range"] = rng
    if extra:
        h.update(extra)
    last = None
    for a in range(tries):
        try:
            r = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=h)
            with urllib.request.urlopen(r, timeout=180) as resp:
                return resp.read().decode(), dict(resp.headers)
        except Exception as e:
            last = e
            time.sleep(1.5 * (a + 1))
    raise RuntimeError(f"GET failed: {path}: {last}")


def count_of(hdrs):
    cr = hdrs.get("Content-Range", "") or hdrs.get("content-range", "")
    if "/" in cr:
        tail = cr.rsplit("/", 1)[1]
        return None if tail == "*" else int(tail)
    return None


def page_all(path):
    rows, start = [], 0
    while True:
        body, _ = req(path, rng=f"{start}-{start + PAGE - 1}")
        got = json.loads(body)
        if not got:
            break
        rows.extend(got)
        start += len(got)
        if len(got) < PAGE:
            break
    return rows


# ── 1. pairs 全表(小)────────────────────────────────────────────────────────
log("perp_bv_pairs ...")
pairs = []
off = 0
while True:
    body, _ = req(
        f"perp_bv_pairs?select=symbol,pair,kind,dead_from,first_d,active&order=pair.asc&limit={PAGE}&offset={off}",
        extra=EXACT,
    )
    rr = json.loads(body)
    if not rr:
        break
    pairs.extend(rr)
    off += len(rr)
    if len(rr) < PAGE:
        break
with open(f"{OUT}/pairs.json", "w") as f:
    json.dump(pairs, f)
log("pairs rows=%d" % len(pairs))

# ── 2. perp_bv_daily 早期窗口(按 symbol 分片)───────────────────────────────
W_START, W_END = "2019-10-01", "2023-01-31"
log("perp_bv_daily %s..%s ..." % (W_START, W_END))
_, h = req(
    f"perp_bv_daily?select=symbol&d=gte.{W_START}&d=lte.{W_END}&limit=1&order=symbol.asc", extra=EXACT
)
expect_rows = count_of(h)
log("  expected rows (count=exact) = %s" % expect_rows)

syms = sorted({p["symbol"] for p in pairs})
perp = []
SH = 40
for i in range(0, len(syms), SH):
    chunk = syms[i:i + SH]
    filt = "symbol=in.(" + ",".join(chunk) + f")&d=gte.{W_START}&d=lte.{W_END}"
    rows = page_all(
        f"perp_bv_daily?select=symbol,pair,d,o,c,h,l,qv,tbqv,recorded_at&{filt}&order=symbol.asc,d.asc"
    )
    perp.extend(rows)
    log("  shard %d/%d rows=%d total=%d" % (i // SH + 1, (len(syms) + SH - 1) // SH, len(rows), len(perp)))

with open(f"{OUT}/perp_bv_early.jsonl", "w") as f:
    for r in perp:
        f.write(json.dumps(r) + "\n")
log("perp rows=%d" % len(perp))

# ── 3. asset_mcap_daily 2020-01-01 → 2022-12-31 ─────────────────────────────
log("asset_mcap_daily 2020..2022 ...")
_, h = req(
    "asset_mcap_daily?select=symbol&d=gte.2020-01-01&d=lte.2022-12-31&limit=1&order=symbol.asc", extra=EXACT
)
mcap_expect = count_of(h)
log("  expected rows (count=exact) = %s" % mcap_expect)

mcap = []
SH = 60
msyms = sorted({p["symbol"] for p in pairs})
for i in range(0, len(msyms), SH):
    chunk = msyms[i:i + SH]
    filt = "symbol=in.(" + ",".join(chunk) + ")&d=gte.2020-01-01&d=lte.2022-12-31"
    rows = page_all(f"asset_mcap_daily?select=symbol,d,mcap,price,volume&{filt}&order=symbol.asc,d.asc")
    mcap.extend(rows)
    log("  shard %d/%d rows=%d total=%d" % (i // SH + 1, (len(msyms) + SH - 1) // SH, len(rows), len(mcap)))

with open(f"{OUT}/mcap.jsonl", "w") as f:
    for r in mcap:
        f.write(json.dumps(r) + "\n")
log("mcap rows=%d" % len(mcap))

# ── 4. 摘要 ─────────────────────────────────────────────────────────────────
def drange(rows, k="d"):
    v = [r[k] for r in rows if r.get(k)]
    return [min(v), max(v)] if v else [None, None]


dup = Counter((r["symbol"], r["d"]) for r in perp)
summary = {
    "window": [W_START, W_END],
    "perp_rows": len(perp),
    "perp_expected_rows": expect_rows,
    "perp_d_range": drange(perp),
    "perp_symbols": len({r["symbol"] for r in perp}),
    "perp_dup_keys": sum(1 for v in dup.values() if v > 1),
    "mcap_rows": len(mcap),
    "mcap_expected_rows": mcap_expect,
    "mcap_d_range": drange(mcap),
    "mcap_symbols": len({r["symbol"] for r in mcap}),
}
with open(f"{OUT}/pull_summary.json", "w") as f:
    json.dump(summary, f, indent=1)
print(json.dumps(summary, indent=1), flush=True)
print("DONE", flush=True)
