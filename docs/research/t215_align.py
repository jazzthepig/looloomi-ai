#!/usr/bin/env python3
"""T-215 —— T-213 报告返工:块对齐敏感性 + 固定日期窗口 + 漂移的正确零分布。

背景(§B-auto-1031-1215 lane-b 自查 + §Seth-1031a):
  · T-213 的头条「5 日块 TE」对**块起点**极敏感:非重叠 5 日块的起点是任意的,
    而代币序列用 Binance `limit=400` 的**滚动**窗口取(起点每天前移一天)
    ⇒ 同代码两天跑出不同数(实测 PAXG 4.638% vs 2.291%,差 2.35pp)。
  · 「代币化溢价 ≈ 0」恰是 5 种对齐里**最小**的一个 ⇒ 量级必须降级为方向性结论。
  · §4 探索 2「错位本身可能是可交易的时序源」已被判为伪发现(撤回)。

本脚本(只读:只读 Supabase + 公开行情源;不写库、不下单、不打印任何 key):
  ① 固定日期窗口取数(窗口写死在常量里,不是滚动 N 天)⇒ 同代码两天跑出同数。
  ② 块对齐:5 种起点(0..4)× 2 套行集 + ISO 自然周钉(权威口径)。
  ③ 漂移的零分布:平稳块自助法重抽**中心化**的超出收益
     (置换保值 ⇒ 零分布退化;重抽才动)。
  ④ 2026-06-26 基准坏点(eodhd SPY)剔除前后的 SPYX / Ondo 数。
  ⑤ eq.SPX 的 hyperliquid 污染(只记录,不改库)。

输出:docs/research/t215_align.json(同目录)
"""
import datetime
import hashlib
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from src.data.evaluation.apparatus import (  # noqa: E402
    block_permute, null_distribution, percentile_of, stationary_bootstrap_index,
)

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise SystemExit("SUPABASE_URL / SUPABASE_KEY 未设置 —— 读不到基准就没法算跟踪误差")

# ── 固定窗口(写死,不是滚动)────────────────────────────────────────────────
TOK_START = "2025-09-01"          # 代币序列固定起点
TOK_END = "2026-10-28"            # 代币序列固定终点(最后一个完整收市日)
BENCH_START = "2024-08-01"        # 基准固定起点(给基线留长窗口)
BENCH_END = "2026-10-28"
COMMON_START = "2026-04-30"       # T-213 的公共窗口(固定)
COMMON_END = "2026-10-28"
BAD_DAY = "2026-06-26"            # eodhd SPY 坏点(ETF −0.72% vs 指数 −0.05%)

SEED = 20261031
N_BOOT = 2000

BINANCE_PAIR = {"PAXG": "PAXGUSDT", "XAUT": "XAUTUSDT"}
GT_POOL = {
    "SPYX": ("solana", "6truu3rZuiB9rKQg4VYC3Dt3QwV7DgwGqXrYUcrvnDDE"),
    "SPY_ondo": ("eth", "0x5638bbde046ec2efc7c8f3fd8dc5a9a1016f7eeb"),
}
LEGS = [
    ("PAXG", "PAXG", "XAUUSD", "黄金:Paxos Gold"),
    ("XAUT", "XAUT", "XAUUSD", "黄金:Tether Gold"),
    ("SPYX", "SPYX", "SPY", "股票:xStocks SPYX(Solana 池)"),
    ("SPY_ondo", "SPY_ondo", "SPY", "股票:Ondo SPY(Ethereum 池)"),
]


# ── 取数(全部固定日期窗口)────────────────────────────────────────────────
def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def get(url, hdr=None):
    h = dict(UA)
    if hdr:
        h.update(hdr)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def safe(url, hdr=None):
    try:
        return get(url, hdr)
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {str(e)[:140]}"}


def dstr(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")


def ms(day):
    return int(datetime.datetime.fromisoformat(day).replace(
        tzinfo=datetime.timezone.utc).timestamp() * 1000)


def sec(day):
    return int(datetime.datetime.fromisoformat(day).replace(
        tzinfo=datetime.timezone.utc).timestamp())


def binance_window(symbol, start, end):
    """Binance 现货日 K,固定 startTime/endTime(不是 limit=N 的滚动窗口)。"""
    url = (f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d"
           f"&startTime={ms(start)}&endTime={ms(end) + 86400000}&limit=1000")
    d = safe(url)
    if not isinstance(d, list) or not d:
        return {}, f"binance klines failed: {str(d)[:120]}"
    out = {}
    for row in d:
        day = dstr(int(row[0]) / 1000)
        if start <= day <= end:
            out[day] = float(row[4])
    return dict(sorted(out.items())), "binance_spot_daily_kline_close"


def gt_pool_window(network, pool, start, end):
    """GeckoTerminal 池子日线,固定 after_timestamp(起点钉死)。"""
    url = (f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool}"
           f"/ohlcv/day?aggregate=1&limit=1000&currency=usd&token=base"
           f"&after_timestamp={sec(start)}")
    last = ""
    for wait in (0, 8, 20, 35):
        if wait:
            time.sleep(wait)
        d = safe(url)
        rows = (((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []) \
            if isinstance(d, dict) else []
        if rows:
            out = {}
            for row in rows:
                day = dstr(int(row[0]))
                if start <= day <= end:
                    out[day] = float(row[4])
            return dict(sorted(out.items())), f"geckoterminal_pool_ohlcv_day:{network}"
        last = str(d.get("_error") if isinstance(d, dict) else d)[:120]
    return {}, f"gt pool ohlcv failed: {last}"


def supabase_window(symbol, start, end, source="eodhd"):
    """ohlcv_daily 的固定日期窗口;钉死来源(多源合并会让「哪一天用哪条」随时间变)。"""
    base = SUPABASE_URL.rstrip("/") + "/rest/v1/ohlcv_daily"
    hdr = {"apikey": SUPABASE_KEY, "Authorization": "Bearer " + SUPABASE_KEY}
    q = (f"?symbol=eq.{symbol}&select=trade_date,close,source"
         f"&trade_date=gte.{start}&trade_date=lte.{end}&order=trade_date.asc")
    if source:
        q += f"&source=eq.{source}"
    rows = get(base + q, hdr)
    out = {}
    srcs = set()
    for row in rows:
        if row.get("close") is None:
            continue
        srcs.add(row.get("source") or "")
        out[row["trade_date"]] = float(row["close"])
    return dict(sorted(out.items())), sorted(srcs)


def supabase_sources(symbol):
    """该 symbol 在库里有哪些来源、各有多少行(污染排查用)。"""
    base = SUPABASE_URL.rstrip("/") + "/rest/v1/ohlcv_daily"
    hdr = {"apikey": SUPABASE_KEY, "Authorization": "Bearer " + SUPABASE_KEY}
    q = f"?symbol=eq.{symbol}&select=trade_date,close,source&order=trade_date.asc&limit=5000"
    rows = get(base + q, hdr)
    by = {}
    for row in rows:
        by.setdefault(row.get("source") or "", []).append(row)
    return {k: {"n_rows": len(v), "first": v[0]["trade_date"], "last": v[-1]["trade_date"],
                "closes": [r["close"] for r in v]}
            for k, v in by.items()}


def bench_quality(symbol, start, end):
    """基准通道的数据质量:每个来源的行数 / 空收盘 / 独立日期数(坏点排查用)。"""
    base = SUPABASE_URL.rstrip("/") + "/rest/v1/ohlcv_daily"
    hdr = {"apikey": SUPABASE_KEY, "Authorization": "Bearer " + SUPABASE_KEY}
    q = (f"?symbol=eq.{symbol}&select=trade_date,close,source"
         f"&trade_date=gte.{start}&trade_date=lte.{end}&order=trade_date.asc")
    rows = get(base + q, hdr)
    by = {}
    for row in rows:
        by.setdefault(row.get("source") or "", []).append(row)
    out = {}
    for s, rs in by.items():
        days = {r["trade_date"] for r in rs}
        nulls = sum(1 for r in rs if r.get("close") is None)
        out[s] = {"n_rows": len(rs), "n_null_close": nulls, "n_distinct_days": len(days),
                  "first": min(days) if days else None, "last": max(days) if days else None}
    out["_total_rows"] = len(rows)
    return out


def fred_sp500(start, end):
    """FRED SP500(S&P Dow Jones 官方指数收盘,CSV 免 key)。"""
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8", "replace")
    out = {}
    for line in raw.strip().split("\n")[1:]:
        parts = line.split(",")
        if len(parts) != 2:
            continue
        day, v = parts[0].strip(), parts[1].strip()
        if not v or v == "." or not (start <= day <= end):
            continue
        out[day] = float(v)
    return dict(sorted(out.items())), "fred:SP500"


# ── 行集与块 ──────────────────────────────────────────────────────────────
def pair_rows(dates, series, adjacent_only=True):
    """dates(已排序、已过滤)→ 成对日收益行。
    adjacent_only=True 只留日历相邻(gap==1)的对;False 保留全部相邻行
    (T-213 原行集:周五→周一的 gap==3 对也在内)。"""
    rows = []
    for i in range(1, len(dates)):
        p, c = dates[i - 1], dates[i]
        gap = (datetime.date.fromisoformat(c) - datetime.date.fromisoformat(p)).days
        if adjacent_only and gap != 1:
            continue
        r = {}
        for name, px in series.items():
            r[name] = px[c] / px[p] - 1.0
        rows.append({"d": c, "gap": gap, "r": r})
    return rows


def weekday_dates(dates):
    """只留周一~周五(基准的交易日)。"""
    return [d for d in dates if datetime.date.fromisoformat(d).weekday() < 5]


def blocks_fixed(rows, step=5, offset=0):
    """不重叠 step 日块,从第 offset 行开始切(5 种对齐 = offset 0..4)。"""
    rs = rows[offset:]
    out = []
    for k in range(0, len(rs) - step + 1, step):
        chunk = rs[k:k + step]
        out.append({
            "from": chunk[0]["d"], "to": chunk[-1]["d"], "n_days": step,
            "r_tok": math.prod([1 + c["r"]["a"] for c in chunk]) - 1,
            "r_bench": math.prod([1 + c["r"]["b"] for c in chunk]) - 1,
        })
    return out


def blocks_iso_week(rows, min_days=4):
    """ISO 自然周块(周一~周五的行按 ISO 周分组;整周不足 min_days 天则弃)。"""
    buckets = {}
    for x in rows:
        y, w, _ = datetime.date.fromisoformat(x["d"]).isocalendar()
        buckets.setdefault((y, w), []).append(x)
    out = []
    for key in sorted(buckets):
        rs = buckets[key]
        if len(rs) < min_days:
            continue
        out.append({
            "week": "%dW%02d" % key, "n_days": len(rs),
            "from": rs[0]["d"], "to": rs[-1]["d"],
            "r_tok": math.prod([1 + c["r"]["a"] for c in rs]) - 1,
            "r_bench": math.prod([1 + c["r"]["b"] for c in rs]) - 1,
        })
    return out


def te_from(block_list, periods):
    """块口径 TE(年化)= std(块差)·sqrt(periods)。"""
    if len(block_list) < 3:
        return None
    rt = [b["r_tok"] for b in block_list]
    rb = [b["r_bench"] for b in block_list]
    n = len(rt)
    diffs = [a - b for a, b in zip(rt, rb)]
    sd = statistics.stdev(diffs)
    mt, mb = statistics.mean(rt), statistics.mean(rb)
    cov = sum((a - mt) * (b - mb) for a, b in zip(rt, rb)) / (n - 1)
    sdt, sdb = statistics.stdev(rt), statistics.stdev(rb)
    return {
        "n": n, "te_ann_pct": round(sd * math.sqrt(periods) * 100, 3),
        "te_bps": round(sd * 1e4, 2),
        "corr": round(cov / (sdt * sdb), 4) if sdt and sdb else None,
        "drift_ann_pct": round(statistics.mean(diffs) * periods * 100, 3),
    }


def te_daily(rows):
    if len(rows) < 5:
        return None
    rt = [x["r"]["a"] for x in rows]
    rb = [x["r"]["b"] for x in rows]
    diffs = [a - b for a, b in zip(rt, rb)]
    mt, mb = statistics.mean(rt), statistics.mean(rb)
    cov = sum((a - mt) * (b - mb) for a, b in zip(rt, rb)) / (len(rt) - 1)
    sdt, sdb = statistics.stdev(rt), statistics.stdev(rb)
    return {
        "n": len(rt), "te_ann_pct": round(statistics.stdev(diffs) * math.sqrt(365) * 100, 3),
        "te_bps": round(statistics.stdev(diffs) * 1e4, 2),
        "corr": round(cov / (sdt * sdb), 4) if sdt and sdb else None,
        "drift_ann_pct": round(statistics.mean(diffs) * 365 * 100, 3),
        "vol_ratio": round(sdt / sdb, 4) if sdb else None,
    }


def drift_pct(rows):
    """累计漂移(%)= 代币累计 / 基准累计 − 1(= price_ratio 的变化)。"""
    if not rows:
        return None
    num = math.prod([1 + x["r"]["a"] for x in rows])
    den = math.prod([1 + x["r"]["b"] for x in rows])
    return round((num / den - 1) * 100, 4)


def metrics(rows, label):
    """一条腿的逐日 / ISO 周 / 5 种块对齐 / 漂移。"""
    iso = blocks_iso_week(rows)
    m = {
        "label": label,
        "n_rows": len(rows),
        "first_day": rows[0]["d"] if rows else None,
        "last_day": rows[-1]["d"] if rows else None,
        "daily_te": te_daily(rows),
        "iso_week_te": te_from(iso, 52),
        "iso_week_meta": {
            "n_blocks": len(iso),
            "first_block": iso[0]["from"] if iso else None,
            "last_block": iso[-1]["to"] if iso else None,
            "days_per_block": sorted({b["n_days"] for b in iso}),
        },
        "align": {},
        "drift_pct": drift_pct(rows),
    }
    for off in range(5):
        bl = blocks_fixed(rows, 5, off)
        m["align"]["offset_%d" % off] = {
            "n_blocks": len(bl),
            "te_ann_pct": (te_from(bl, 365.0 / 5) or {}).get("te_ann_pct"),
        }
    vals = [v["te_ann_pct"] for v in m["align"].values() if v["te_ann_pct"] is not None]
    m["align_min"] = min(vals) if vals else None
    m["align_max"] = max(vals) if vals else None
    m["align_spread"] = round(max(vals) - min(vals), 4) if vals else None
    return m


def rows_for(tok, bench, start, end, weekday_only=True, drop_days=(), adjacent_only=True):
    dates = sorted(set(tok) & set(bench))
    dates = [d for d in dates if start <= d <= end and d not in drop_days]
    if weekday_only:
        dates = weekday_dates(dates)
    return pair_rows(dates, {"a": tok, "b": bench}, adjacent_only=adjacent_only)


# ── 零分布(一律走 apparatus)──────────────────────────────────────────────
def null_diff_te(rows_a, rows_b, n=N_BOOT, seed=SEED, block=5, mode="iso"):
    """两条腿 TE 差的零分布:打乱**基准**日收益(块长 5)后重算两腿 TE。
    两条腿共用同一次置换(否则就不是「同一条基准」的对照)。"""
    rt_a = [x["r"]["a"] for x in rows_a]
    rt_b = [x["r"]["a"] for x in rows_b]
    rb = [x["r"]["b"] for x in rows_a]
    days = [x["d"] for x in rows_a]

    def te_of(rb_vec, rt_vec, mode_):
        rr = [{"d": d, "r": {"a": a, "b": b}} for d, a, b in zip(days, rt_vec, rb_vec)]
        if mode_ == "iso":
            return te_from(blocks_iso_week(rr), 52)
        off = int(mode_.split("_")[1])
        return te_from(blocks_fixed(rr, 5, off), 365.0 / 5)

    ta = te_of(rb, rt_a, mode)
    tb = te_of(rb, rt_b, mode)
    if not ta or not tb:
        return {"error": "not computable", "mode": mode}
    actual = ta["te_ann_pct"] - tb["te_ann_pct"]

    def draw(rng):
        rb_p = list(block_permute(rb, block, rng))
        pa = te_of(rb_p, rt_a, mode)
        pb = te_of(rb_p, rt_b, mode)
        if not pa or not pb:
            return float("nan")
        return pa["te_ann_pct"] - pb["te_ann_pct"]

    null = null_distribution(draw, n, seed, actual=actual)
    null = null[np.isfinite(null)]
    pct = percentile_of(actual, null)
    return {
        "mode": mode, "n_rows": len(rows_a),
        "te_a": ta["te_ann_pct"], "te_b": tb["te_ann_pct"],
        "actual_diff_pp": round(actual, 4),
        "null_median": round(float(np.median(null)), 4),
        "null_p05": round(float(np.percentile(null, 5)), 4),
        "null_p95": round(float(np.percentile(null, 95)), 4),
        "percentile": pct,
        "two_sided_p": round(min(1.0, 2 * min(pct, 1 - pct)), 4) if pct is not None else None,
        "n_draws": int(null.size),
    }


def null_drift(rows, n=N_BOOT, seed=SEED, mean_block=5.0):
    """漂移的正确零分布:平稳块自助法重抽**中心化**的超出收益。
    (置换保值 ⇒ 乘积不变 ⇒ 零分布退化;重抽才动。)"""
    rt = np.asarray([x["r"]["a"] for x in rows], dtype=float)
    rb = np.asarray([x["r"]["b"] for x in rows], dtype=float)
    e = rt - rb
    e_c = e - e.mean()
    den = math.prod((1.0 + rb).tolist())
    idx = stationary_bootstrap_index(len(e), mean_block, n, np.random.default_rng(seed))
    tok_star = rb[None, :] + e_c[idx]
    drifts = np.prod(1.0 + tok_star, axis=1) / den * 100 - 100
    actual = drift_pct(rows)
    pct = percentile_of(actual, drifts)
    return {
        "actual_drift_pct": actual,
        "null_median_pct": round(float(np.median(drifts)), 4),
        "null_sd_pct": round(float(np.std(drifts, ddof=1)), 4),
        "null_p05_pct": round(float(np.percentile(drifts, 5)), 4),
        "null_p95_pct": round(float(np.percentile(drifts, 95)), 4),
        "percentile_one_sided": pct,
        "two_sided_p": round(min(1.0, 2 * min(pct, 1 - pct)), 4) if pct is not None else None,
        "n": int(drifts.size),
        "mean_block": mean_block,
        "note": "零假设=无方向性漂移;重抽中心化超出收益(平稳块自助),乘积会被重抽改变",
    }


def main():
    out = {
        "generated_at_utc": now(),
        "seed": SEED, "n_boot": N_BOOT,
        "windows": {
            "token": [TOK_START, TOK_END], "benchmark": [BENCH_START, BENCH_END],
            "common": [COMMON_START, COMMON_END], "bad_day": BAD_DAY,
        },
        "definitions": {
            "row_set_canonical": "代币与基准的公共日期 ∩ [窗口] ∩ 周一~周五,只保留日历相邻(gap==1)的成对 ⇒ 块内没有跨周末的对",
            "row_set_legacy": "T-213 原行集:公共日期全部保留(含周五→周一的 gap==3 对)",
            "block_iso_week": "ISO 自然周块:同一 ISO 周内(周一~周五)的逐日收益复合,块 TE(年化)=std(块差)·sqrt(52);整周不足 4 天则弃",
            "block_5d_align": "5 日不重叠块,从第 k 行开始切(k=0..4);块 TE(年化)=std(块差)·sqrt(365/5)",
            "daily_te": "逐日 TE(年化)=std(r_a − r_b)·sqrt(365)",
            "drift_pct": "累计漂移(%)= 代币累计/基准累计 − 1(= price_ratio 的变化)",
            "null_te_diff": "打乱基准日收益(块长 5)后重算两腿 TE 的差 ⇒ 零分布(差距是否可读)",
            "null_drift": "平稳块自助(mean_block=5)重抽中心化超出收益 ⇒ 漂移的零分布(置换保值会退化)",
        },
        "sources": {}, "legs": {}, "baselines": {}, "comparisons": {},
        "drift_null": {}, "bad_day": {}, "eq_spx": {},
    }

    # ── 取数(固定窗口)─────────────────────────────────────────────────────
    bench = {}
    for sym in ("XAUUSD", "SPY", "GLD"):
        series, srcs = supabase_window(sym, BENCH_START, BENCH_END, "eodhd")
        bench[sym] = series
        out["sources"]["bench_" + sym] = {
            "source": "supabase:ohlcv_daily(source=eodhd)",
            "rows_in_window": len(series), "first": min(series) if series else None,
            "last": max(series) if series else None, "sources_seen": srcs,
            "channel_quality_full": bench_quality(sym, BENCH_START, BENCH_END),
            "channel_quality_common": bench_quality(sym, COMMON_START, COMMON_END),
        }
    toks = {}
    for name, pair in BINANCE_PAIR.items():
        s, src = binance_window(pair, TOK_START, TOK_END)
        toks[name] = s
        out["sources"]["token_" + name] = {
            "source": src, "pair": pair, "rows": len(s),
            "first": min(s) if s else None, "last": max(s) if s else None,
        }
        time.sleep(0.4)
    for name, (net, pool) in GT_POOL.items():
        s, src = gt_pool_window(net, pool, TOK_START, TOK_END)
        toks[name] = s
        out["sources"]["token_" + name] = {
            "source": src, "network": net, "pool": pool, "rows": len(s),
            "first": min(s) if s else None, "last": max(s) if s else None,
        }
        time.sleep(1.0)
    spx, spx_src = fred_sp500(BENCH_START, BENCH_END)
    out["sources"]["SPX_index"] = {
        "source": spx_src, "rows": len(spx),
        "first": min(spx) if spx else None, "last": max(spx) if spx else None,
    }

    # ── 每条腿的两种窗口 ────────────────────────────────────────────────
    for name, tkey, bkey, desc in LEGS:
        if not toks.get(tkey) or not bench.get(bkey):
            out["legs"][name] = {"error": "missing series"}
            continue
        for wlabel, (ws, we) in (("common_window", (COMMON_START, COMMON_END)),
                                 ("fixed_window", (TOK_START, TOK_END))):
            rows_wd = rows_for(toks[tkey], bench[bkey], ws, we, True)
            rows_all = rows_for(toks[tkey], bench[bkey], ws, we, False, adjacent_only=False)
            rec = {
                "desc": desc, "token": tkey, "benchmark": bkey,
                "window": [ws, we],
                "canonical": metrics(rows_wd, name + " vs " + bkey + " (周一~周五行集)"),
                "legacy": metrics(rows_all, name + " vs " + bkey + " (T-213 原行集)"),
            }
            out["legs"].setdefault(name, {})[wlabel] = rec
            c = rec["canonical"]
            print(f"  {name:9s} {wlabel:13s} n={c['n_rows']:4d} "
                  f"日TE={(c['daily_te'] or {}).get('te_ann_pct')}% "
                  f"ISO周TE={(c['iso_week_te'] or {}).get('te_ann_pct')}% "
                  f"对齐区间=[{c['align_min']}, {c['align_max']}] "
                  f"原口径5日块={(rec['legacy']['align']['offset_0']['te_ann_pct'])}%", flush=True)

    # ── 基线:不代币化那条腿 ─────────────────────────────────────────────
    out["baselines"]["GLD_vs_XAUUSD"] = {
        "why": "不代币化的黄金腿:实物支撑 ETF 的自身跟踪成本",
        "common_window": metrics(
            rows_for(bench.get("GLD", {}), bench.get("XAUUSD", {}), COMMON_START, COMMON_END, True),
            "GLD vs XAUUSD"),
        "common_window_legacy": metrics(
            rows_for(bench.get("GLD", {}), bench.get("XAUUSD", {}), COMMON_START, COMMON_END,
                     False, adjacent_only=False),
            "GLD vs XAUUSD(T-213 原行集)"),
        "fixed_window": metrics(
            rows_for(bench.get("GLD", {}), bench.get("XAUUSD", {}), TOK_START, TOK_END, True),
            "GLD vs XAUUSD"),
    }
    if spx and bench.get("SPY"):
        out["baselines"]["SPY_etf_vs_index"] = {
            "why": "不代币化的股票腿:ETF 自身对指数的跟踪成本",
            "index_source": spx_src,
            "common_window": metrics(
                rows_for(bench["SPY"], spx, COMMON_START, COMMON_END, True),
                "SPY(ETF) vs SPX(指数)"),
            "common_window_legacy": metrics(
                rows_for(bench["SPY"], spx, COMMON_START, COMMON_END, False, adjacent_only=False),
                "SPY(ETF) vs SPX(指数)(T-213 原行集)"),
            "fixed_window": metrics(
                rows_for(bench["SPY"], spx, TOK_START, TOK_END, True),
                "SPY(ETF) vs SPX(指数)"),
        }
        c = out["baselines"]["SPY_etf_vs_index"]["common_window"]
        print(f"  基线 SPY(ETF) vs SPX(指数) n={c['n_rows']} "
              f"ISO周TE={(c['iso_week_te'] or {}).get('te_ann_pct')}% "
              f"对齐区间=[{c['align_min']}, {c['align_max']}]", flush=True)

    # ── 比较:腿之间的 TE 差(同一零分布)─────────────────────────────────
    def cmp_legs(a_key, b_key, bench_key, ws, we):
        if not toks.get(a_key) or not toks.get(b_key) or not bench.get(bench_key):
            return {"error": "missing series"}
        dates = sorted(set(toks[a_key]) & set(toks[b_key]) & set(bench[bench_key]))
        dates = weekday_dates([d for d in dates if ws <= d <= we])
        rows_a = pair_rows(dates, {"a": toks[a_key], "b": bench[bench_key]})
        rows_b = pair_rows(dates, {"a": toks[b_key], "b": bench[bench_key]})
        rec = {"common_days": len(rows_a), "window": [ws, we]}
        for mode in ("iso", "align_0", "align_1", "align_2", "align_3", "align_4"):
            rec[mode] = null_diff_te(rows_a, rows_b, seed=SEED + len(mode), mode=mode)
        rec["drift_a_pct"] = drift_pct(rows_a)
        rec["drift_b_pct"] = drift_pct(rows_b)
        return rec

    out["comparisons"]["SPYX_minus_SPY_ondo"] = cmp_legs(
        "SPYX", "SPY_ondo", "SPY", COMMON_START, COMMON_END)
    out["comparisons"]["XAUT_minus_PAXG"] = cmp_legs(
        "XAUT", "PAXG", "XAUUSD", COMMON_START, COMMON_END)

    # ── 漂移零分布(正确口径)─────────────────────────────────────────────
    for name, tkey, bkey, _ in LEGS:
        rows = rows_for(toks.get(tkey, {}), bench.get(bkey, {}), COMMON_START, COMMON_END, True)
        rows_legacy = rows_for(toks.get(tkey, {}), bench.get(bkey, {}), COMMON_START, COMMON_END,
                               False, adjacent_only=False)
        if len(rows) > 30:
            out["drift_null"][name] = null_drift(rows, seed=SEED + 7)
            d = out["drift_null"][name]
            print(f"  漂移零分布 {name:9s} 实测 {d['actual_drift_pct']}% "
                  f"单侧分位 {d['percentile_one_sided']} 双侧 p {d['two_sided_p']}", flush=True)
        if len(rows_legacy) > 30:
            out["drift_null"][name + "_legacy_rows"] = null_drift(rows_legacy, seed=SEED + 7)
            dl = out["drift_null"][name + "_legacy_rows"]
            print(f"  漂移零分布 {name:9s}(T-213 原行集) 实测 {dl['actual_drift_pct']}% "
                  f"单侧分位 {dl['percentile_one_sided']} 双侧 p {dl['two_sided_p']}", flush=True)
    if spx and bench.get("SPY"):
        out["drift_null"]["SPY_etf_vs_index"] = null_drift(
            rows_for(bench["SPY"], spx, COMMON_START, COMMON_END, True), seed=SEED + 8)

    # ── ④ 2026-06-26 基准坏点:剔除前后(SPYX / Ondo vs 不代币化基线)──────
    if spx and bench.get("SPY"):
        for label, tkey in (("SPYX", "SPYX"), ("SPY_ondo", "SPY_ondo")):
            rec = {}
            for tag, drop in (("with_bad_day", ()), ("without_bad_day", (BAD_DAY,))):
                dates = sorted(set(toks.get(tkey, {})) & set(bench["SPY"]) & set(spx))
                dates = weekday_dates([d for d in dates
                                       if COMMON_START <= d <= COMMON_END and d not in drop])
                rows_leg = pair_rows(dates, {"a": toks.get(tkey, {}), "b": bench["SPY"]})
                rows_idx = pair_rows(dates, {"a": bench["SPY"], "b": spx})
                leg_m = metrics(rows_leg, label + " vs SPY(ETF)")
                base_m = metrics(rows_idx, "SPY(ETF) vs SPX(指数)")
                rec[tag] = {"leg": leg_m, "baseline_etf_vs_index": base_m}
                rec[tag]["premium_pp"] = {
                    "iso_week": round(leg_m["iso_week_te"]["te_ann_pct"]
                                      - base_m["iso_week_te"]["te_ann_pct"], 4)
                    if leg_m["iso_week_te"] and base_m["iso_week_te"] else None,
                    "align_min": round(leg_m["align_min"] - base_m["align_min"], 4),
                    "align_max": round(leg_m["align_max"] - base_m["align_max"], 4),
                }
            out["bad_day"][label] = rec
            print(f"  坏点 {label}: ISO周TE {rec['with_bad_day']['leg']['iso_week_te']['te_ann_pct']}% "
                  f"→ 剔除 {rec['without_bad_day']['leg']['iso_week_te']['te_ann_pct']}%", flush=True)

    # ── ⑤ eq.SPX 的 hyperliquid 污染(只记录)─────────────────────────────
    try:
        srcs = supabase_sources("SPX")
        rec = {"why": "库内 eq.SPX 不是 S&P 500 指数(是 Hyperliquid 的 SPX 永续)",
               "by_source": {}}
        for s, info in srcs.items():
            closes = [c for c in info["closes"] if c is not None]
            rets = [(closes[i] / closes[i - 1] - 1) * 100
                    for i in range(1, len(closes)) if closes[i - 1]]
            rec["by_source"][s] = {
                "n_rows": info["n_rows"], "first": info["first"], "last": info["last"],
                "max_abs_daily_move_pct": round(max((abs(x) for x in rets), default=0.0), 3),
                "n_days_abs_move_gt_5pct": sum(1 for x in rets if abs(x) > 5),
            }
        if "hyperliquid" in rec["by_source"]:
            rows = get(
                SUPABASE_URL.rstrip("/") + "/rest/v1/ohlcv_daily"
                "?symbol=eq.SPX&select=trade_date,close,source"
                "&source=eq.hyperliquid&order=trade_date.asc",
                {"apikey": SUPABASE_KEY, "Authorization": "Bearer " + SUPABASE_KEY})
            days = [r["trade_date"] for r in rows]
            cl = [r["close"] for r in rows]
            moves = [{"d": days[i], "pct": round((cl[i] / cl[i - 1] - 1) * 100, 3)}
                     for i in range(1, len(cl)) if cl[i - 1]]
            rec["hyperliquid_detail"] = {
                "first": days[0] if days else None, "last": days[-1] if days else None,
                "n_rows": len(rows),
                "daily_moves_gt_5pct": [m for m in moves if abs(m["pct"]) > 5],
                "note": ("任何走 ohlcv_daily eq.SPX 的基线都会踩到这段污染"
                         "(T-213 的基线走 FRED SP500,没踩到)"),
            }
        out["eq_spx"] = rec
    except Exception as exc:  # noqa: BLE001
        out["eq_spx"] = {"error": f"{type(exc).__name__}: {exc}"}

    payload = {k: v for k, v in out.items() if k != "generated_at_utc"}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    out["fingerprint_sha256_excl_timestamp"] = hashlib.sha256(blob.encode()).hexdigest()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t215_align.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, default=str)
    print("WROTE t215_align.json  fingerprint=", out["fingerprint_sha256_excl_timestamp"][:16])


if __name__ == "__main__":
    main()
