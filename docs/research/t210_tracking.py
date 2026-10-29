#!/usr/bin/env python3
"""T-210 跟踪误差:链上代币价格 vs 底层标的同日收盘。

数据源(全部只读):
  · 底层基准:Supabase `ohlcv_daily`(source=eodhd)—— XAUUSD(黄金现货) / SPY
  · 代币日线:Binance 公开日 K(PAXGUSDT / XAUTUSDT,UTC 日线)
    + CoinGecko 公开 market_chart(日频,xStocks SPYX、Ondo 的 SPY/GLD 等)

对齐口径(重要,别用「同一天」这个直觉):
  代币 24/7 交易,Binance 的 UTC 日线收盘 = 该日 00:00 UTC 的价格;
  基准在美国收市(约 21:00 UTC)结算。代币的 UTC 日窗 [00:00 d, 00:00 d+1] 里,
  基准「d 日这一场」的价格变化有 21 小时落在窗内 ⇒ 代币当日收益最该对
  「d 日收市 vs d-1 日收市」。本脚本对 ±2 天的多个错位全算一遍:
    offset=0  ⇒ r_tok(d) vs r_bench(d)      ← 语义上最贴(基准当日收市)
    offset=-1 ⇒ r_tok(d) vs r_bench(d-1)    ← 「同标签」式错位(常见误用)
    offset=+1/+2 ⇒ 再往后错,做对照
  取相关系数最高的一档作为对齐口径报 TE,并把其余档原样列出(不挑数字)。

TE(年化) = std(r_tok - r_bench) * sqrt(365)

输出:t210_tracking.json(同目录)
"""
import datetime
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

import numpy as np

# 零分布 / 分位一律走仓库里的验证装置(T-097),不自己手写
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull, block_permute, null_distribution, percentile_of,
)

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise SystemExit("SUPABASE_URL / SUPABASE_KEY 未设置 —— 读不到基准就没法算跟踪误差")

DAYS = 400
OFFSETS = [0, -1, 1, 2, -2]
BINANCE_KLINE = {"PAXG": "PAXGUSDT", "XAUT": "XAUTUSDT", "USDC": "USDCUSDT"}
# Bybit 有 USDYUSDT(Ondo 的美元收益代币)——现金腿里唯一有 CEX 日线的国债型代币
BYBIT_KLINE = {"USDY": "USDYUSDT"}
# CoinGecko 公开层:days>~30 返 401、随后整段限流 429 ⇒ 默认关闭,需要时开 T210_CG=1
CG_ENABLED = os.environ.get("T210_CG", "0") == "1"
CG_DAYS = int(os.environ.get("T210_CG_DAYS", "30"))
CG_IDS = {
    "PAXG": "pax-gold",
    "XAUT": "tether-gold",
    "SPYX_xstocks": "sp500-xstock",
    "SPY_ondo": "spdr-s-p-500-etf-ondo-tokenized-etf",
    "GLD_ondo": "spdr-gold-shares-ondo-tokenized",
    "BIL_ondo": "spdr-bloomberg-1-3-month-t-bill-etf-ondo-tokenized",
    "GLDx_xstocks": "gold-xstock",
    "OUSG": "ousg",
    "USDY": "ondo-us-dollar-yield",
    "USDC_cg": "usd-coin",
}
# 跟踪误差(代币 vs 底层标的)
BENCH = {"PAXG": "XAUUSD", "XAUT": "XAUUSD", "GLD_ondo": "XAUUSD",
         "GLD": "XAUUSD",          # T-213:不代币化的黄金腿基线(实物支撑 ETF vs 现货)
         "SPYX_xstocks": "SPY", "SPY_ondo": "SPY", "GLDx_xstocks": "XAUUSD",
         "PAXG_cg": "XAUUSD", "XAUT_cg": "XAUUSD",
         "SPYX_xstocks_dex": "SPY", "SPY_ondo_dex": "SPY"}
# 现金腿:没有 T-bill 日线序列在库里 ⇒ 不算「跟踪误差」,只算「相对现金的持有收益 + 应计抖动」
CASH_TOKENS = ["OUSG", "USDY", "USDC"]


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def get(url, hdr=None):
    h = dict(UA)
    if hdr:
        h.update(hdr)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=45) as r:
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


# ---------------------------------------------------------------- Supabase 基准
def supabase_ohlcv(symbol, want_source="eodhd", strict=False):
    """ohlcv_daily:按 trade_date 倒序取最近 N 条(带 order=),再本地升序 + 按来源去重。
    strict=True 时只保留 want_source 那一路的日期(来源对照用)。"""
    base = SUPABASE_URL.rstrip("/") + "/rest/v1/ohlcv_daily"
    hdr = {"apikey": SUPABASE_KEY, "Authorization": "Bearer " + SUPABASE_KEY}
    url = (base + f"?symbol=eq.{symbol}&select=trade_date,close,source"
           f"&order=trade_date.desc&limit=1000")
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.loads(r.read())
    pref = {}
    other = {}
    for row in rows:
        if row.get("close") is None:
            continue
        d = row["trade_date"]
        src = row.get("source") or ""
        if src == want_source:
            pref.setdefault(d, float(row["close"]))
        elif not strict:
            other.setdefault(d, float(row["close"]))
    series = {**other, **pref}
    srcs = sorted({(r.get("source") or "") for r in rows})
    return dict(sorted(series.items())), srcs, len(rows)


# ---------------------------------------------------------------- 代币日线
def binance_daily(symbol, days=DAYS):
    d = safe(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit={min(days, 1000)}")
    if not isinstance(d, list) or not d:
        return {}, f"binance klines failed: {str(d)[:120]}"
    out = {}
    for row in d:
        out[dstr(int(row[0]) / 1000)] = float(row[4])
    return dict(sorted(out.items())), "binance_spot_daily_kline_close"


def bybit_daily(symbol, days=DAYS):
    """Bybit 公开日 K。用于 USDYUSDT(CoinGecko 拿不到历史)。"""
    d = safe(f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}"
             f"&interval=D&limit={min(days, 1000)}")
    rows = ((d.get("result") or {}).get("list")) if isinstance(d, dict) else None
    if not rows:
        return {}, f"bybit kline failed: {str(d)[:120]}"
    out = {}
    for row in rows:                      # [start, open, high, low, close, volume, turnover]
        out[dstr(int(row[0]) / 1000)] = float(row[4])
    return dict(sorted(out.items())), "bybit_spot_daily_kline_close"


def cg_daily(cg_id, days=DAYS):
    """CoinGecko market_chart 日频。公开接口会偶发 401/429(限流),所以重试 + 退避。"""
    url = (f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart"
           f"?vs_currency=usd&days={days}&interval=daily")
    last = ""
    for attempt, wait in enumerate((0, 6, 15, 30)):
        if wait:
            time.sleep(wait)
        d = safe(url)
        if isinstance(d, dict) and "prices" in d:
            out = {}
            for ts, px in d["prices"]:
                out[dstr(int(ts) / 1000)] = float(px)
            return dict(sorted(out.items())), "coingecko_market_chart_daily"
        last = str(d)[:120]
    return {}, f"coingecko market_chart failed: {last}"


def carry_stats(px):
    """现金腿专用:日收益的年化均值(=隐含持有收益)与年化波动(=应计抖动)。"""
    days = sorted(px)
    if len(days) < 30:
        return {"error": "too few days", "n_days": len(days)}
    rets = []
    for i in range(1, len(days)):
        rets.append(px[days[i]] / px[days[i - 1]] - 1.0)
    mu = statistics.mean(rets)
    sd = statistics.stdev(rets)
    return {
        "n_days": len(rets), "first_day": days[0], "last_day": days[-1],
        "carry_ann_pct": round(mu * 365 * 100, 3),
        "accrual_jitter_ann_pct": round(sd * math.sqrt(365) * 100, 3),
        "daily_vol_bps": round(sd * 1e4, 3),
        "total_return_pct": round((px[days[-1]] / px[days[0]] - 1) * 100, 3),
    }


def gt_pool_daily(network, pool_addr, days=DAYS):
    """GeckoTerminal:某个池子的日线(UTC 日,close=row[4])。用于没有 CEX 现货的代币化股票。
    免费层会限流(429),所以退避重试。"""
    url = (f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool_addr}"
           f"/ohlcv/day?aggregate=1&limit={min(days, 1000)}&currency=usd&token=base")
    last = ""
    for attempt, wait in enumerate((0, 8, 20, 35)):
        if wait:
            time.sleep(wait)
        d = safe(url)
        rows = ((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        if rows:
            out = {}
            for row in rows:
                out[dstr(int(row[0]))] = float(row[4])
            return dict(sorted(out.items())), f"geckoterminal_pool_ohlcv_day:{network}"
        last = str(d.get("_error") if isinstance(d, dict) else d)[:120]
    return {}, f"gt pool ohlcv failed: {last}"


def deepest_pool_from_depth_json(token_key):
    """从深度测量 json 里取该代币在某链上最深的池(同一份测量,口径一致)。
    先看第二轮(t210_depth2.json),没有再看第一轮(t210_depth.json)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for fn in ("t210_depth2.json", "t210_depth.json"):
        path = os.path.join(here, fn)
        if not os.path.exists(path):
            continue
        try:
            d = json.load(open(path))
        except Exception:  # noqa: BLE001
            continue
        dex = d.get("dex") or {}
        rec = dex.get(token_key)
        if not rec:
            continue
        pools = rec.get("top_pools") or []
        if not pools:
            continue
        net = rec.get("network")
        return net, pools[0].get("pool")
    return None, None


# ---------------------------------------------------------------- 计算
def te_stats(tok, bench, offset=0, step=1):
    """offset=0: r_tok(d) 对 r_bench(d);offset=k: 对 r_bench(d+k)。
    step>1: 每 step 天取一个不重叠的窗口(用来压掉「日界错位」带来的噪声)。

    ⚠️ 窗口必须同起同止:代币与基准都用 [days[i-1] → days[i]] 这一段,
    否则两边差了整整一个交易日,而黄金/美股日收益几乎不自相关 ⇒ 相关被抹平成 0。
    (2026-10-29:旧版把代币取成 [days[i] → days[i+1]] 而基准取成 [days[i-1] → days[i]],
     得到 corr=-0.02 / TE=42%/yr 的假数;同窗口重算 corr=0.97 / TE≈7%/yr。)
    """
    days = sorted(set(tok) & set(bench))
    pairs = []
    for i in range(1, len(days) - 1):
        d = days[i]
        r_tok = tok[d] / tok[days[i - 1]] - 1.0
        j = i + offset
        if j <= 0 or j >= len(days) - 1:
            continue
        b_prev = bench[days[j - 1]] if j - 1 >= 0 else None
        b_cur = bench[days[j]]
        if b_prev is None:
            continue
        gap = (datetime.date.fromisoformat(days[j]) - datetime.date.fromisoformat(days[j - 1])).days
        pairs.append((d, r_tok, b_cur / b_prev - 1.0, gap))
    if len(pairs) < 20:
        return {"n_days": len(pairs), "error": "too few overlapping days"}
    diffs = [p[1] - p[2] for p in pairs]
    r_t = [p[1] for p in pairs]
    r_b = [p[2] for p in pairs]
    mt, mb = statistics.mean(r_t), statistics.mean(r_b)
    cov = sum((a - mt) * (b - mb) for a, b in zip(r_t, r_b)) / (len(r_t) - 1)
    sdt, sdb = statistics.stdev(r_t), statistics.stdev(r_b)
    corr = cov / (sdt * sdb) if sdt and sdb else None
    sd_diff = statistics.stdev(diffs)
    gaps = {}
    for p in pairs:
        gaps[p[3]] = gaps.get(p[3], 0) + 1
    out = {
        "n_days": len(pairs), "first_day": pairs[0][0], "last_day": pairs[-1][0],
        "gap_days_hist": gaps,
        "corr": round(corr, 4) if corr is not None else None,
        "te_ann_pct": round(sd_diff * math.sqrt(365) * 100, 3),
        "te_daily_bps": round(sd_diff * 1e4, 2),
        "mean_daily_diff_bps": round(statistics.mean(diffs) * 1e4, 3),
        "drift_ann_pct": round(statistics.mean(diffs) * 365 * 100, 3),
        "beta_vs_bench": round(cov / (sdb ** 2), 4) if sdb else None,
        "token_vol_ann_pct": round(sdt * math.sqrt(365) * 100, 2),
        "bench_vol_ann_pct": round(sdb * math.sqrt(365) * 100, 2),
    }
    if step > 1:
        # 每 step 天一个不重叠窗口:错位的「日界」噪声被稀释,剩下的才是真跟踪差
        comp_t, comp_b = [], []
        # 2026-10-30(T-213)修:原起点是 step-1 ⇒ 头 4 对永远不进任何块(off-by-one)。
        # 现在从第 0 对开始,块与块不重叠且覆盖整段。
        for k in range(0, len(pairs) - step + 1, step):
            comp_t.append(math.prod([1 + pairs[k][1]] + [1 + pairs[j][1] for j in range(k + 1, k + step)]) - 1)
            comp_b.append(math.prod([1 + pairs[k][2]] + [1 + pairs[j][2] for j in range(k + 1, k + step)]) - 1)
        if len(comp_t) >= 10:
            dif5 = [a - b for a, b in zip(comp_t, comp_b)]
            mt5 = statistics.mean(comp_t)
            mb5 = statistics.mean(comp_b)
            cov5 = sum((a - mt5) * (b - mb5) for a, b in zip(comp_t, comp_b)) / (len(comp_t) - 1)
            s5t, s5b = statistics.stdev(comp_t), statistics.stdev(comp_b)
            out["block"] = {
                "step_days": step, "n_blocks": len(comp_t),
                "corr": round(cov5 / (s5t * s5b), 4) if s5t and s5b else None,
                "te_ann_pct": round(statistics.stdev(dif5) * math.sqrt(365 / step) * 100, 3),
                "drift_ann_pct": round(statistics.mean(dif5) * (365 / step) * 100, 3),
                "token_vol_ann_pct": round(s5t * math.sqrt(365 / step) * 100, 2),
                "bench_vol_ann_pct": round(s5b * math.sqrt(365 / step) * 100, 2),
            }
    return out


def ratio_drift(tok, bench):
    days = sorted(set(tok) & set(bench))
    if len(days) < 10:
        return {}
    f, l = days[0], days[-1]
    return {"start": f, "end": l,
            "ratio_start": round(tok[f] / bench[f], 6),
            "ratio_end": round(tok[l] / bench[l], 6),
            "ratio_change_pct": round((tok[l] / bench[l]) / (tok[f] / bench[f]) * 100 - 100, 3)}


def main():
    out = {
        "generated_at_utc": now(), "window_days": DAYS,
        "alignment": ("代币与基准都取同一段日历窗口 [days[i-1] → days[i]](两边同起同止)。"
                      "代币 UTC 日线收盘 = 00:00 UTC;基准在美国收市(约 21:00 UTC)结算,"
                      "因此同窗口内仍约有 3 小时错位 —— offset=±1/±2 就是量化这层错位的代价,"
                      "取相关系数最高的一档作为对齐口径报 TE,其余档原样列出(不挑数字)。"
                      "注:代币 24/7 交易而基准只在工作日有值,交集日 = 工作日,"
                      "周一的收益是「周五收市 → 周一收市」,两边同口径。"),
        "benchmarks": {}, "tokens": {}, "tracking": {},
    }

    print("[1/3] Supabase 基准 …\n")
    bench = {}
    for sym in ("XAUUSD", "SPY"):
        try:
            px, srcs, n = supabase_ohlcv(sym)
            bench[sym] = px
            out["benchmarks"][sym] = {
                "source": "supabase:ohlcv_daily(" + ",".join(srcs) + ",prefer=eodhd)",
                "n_rows_fetched": n, "n_days_used": len(px),
                "first": min(px) if px else None, "last": max(px) if px else None,
            }
            print("   ", sym, len(px), out["benchmarks"][sym]["first"], "→", out["benchmarks"][sym]["last"])
        except Exception as exc:  # noqa: BLE001
            out["benchmarks"][sym] = {"error": str(exc)[:200]}
            print("   ", sym, "ERR", exc)

    print("[2/3] 代币日线 …\n")
    tok = {}
    # T-213:GLD(实物支撑 ETF)作为「不代币化的黄金腿」序列进同一套 TE 计算
    # ⇒ 它的 by_offset 扫描直接回答「ETF 收市时间 vs 现货定盘时间差多少」。
    try:
        gld_px, gld_srcs, _ = supabase_ohlcv("GLD")
        if gld_px:
            tok["GLD"] = gld_px
            out["tokens"]["GLD"] = {
                "price_source": "supabase:ohlcv_daily(" + ",".join(gld_srcs) + ",prefer=eodhd)",
                "n_days": len(gld_px), "first": min(gld_px), "last": max(gld_px)}
            print("   GLD", gld_srcs, len(gld_px))
    except Exception as exc:  # noqa: BLE001
        print("   GLD ERR", exc)
    for sym, pair in BINANCE_KLINE.items():
        try:
            px, src = binance_daily(pair)
            tok[sym] = px
            out["tokens"][sym] = {"price_source": src, "n_days": len(px),
                                  "first": min(px) if px else None, "last": max(px) if px else None}
            print("   ", sym, src, len(px))
        except Exception as exc:  # noqa: BLE001
            out["tokens"][sym] = {"error": str(exc)[:200]}
        time.sleep(0.4)
    for sym, pair in BYBIT_KLINE.items():
        try:
            px, src = bybit_daily(pair)
            if len(px) > 5:
                tok[sym] = px
                out["tokens"][sym] = {"price_source": src, "n_days": len(px),
                                      "first": min(px), "last": max(px)}
                print("   ", sym, src, len(px))
            else:
                out["tokens"][sym] = {"error": src}
                print("   ", sym, "no data", src[:80])
        except Exception as exc:  # noqa: BLE001
            out["tokens"][sym] = {"error": str(exc)[:200]}
        time.sleep(0.4)
    for sym, cg_id in (CG_IDS.items() if CG_ENABLED else []):
        try:
            px, src = cg_daily(cg_id, days=CG_DAYS)
            if len(px) > 5:
                out["tokens"][sym + "_cg"] = {"price_source": src, "n_days": len(px),
                                             "first": min(px), "last": max(px)}
                print("   ", sym, src, len(px))
                if sym not in tok:          # Binance 已有则以 Binance 为主序列
                    tok[sym] = px
                else:                      # 交叉核对:同一代币另一数据源
                    tok[sym + "_cg"] = px
            else:
                out["tokens"][sym + "_cg"] = {"error": src}
                print("   ", sym, "no data", src[:80])
        except Exception as exc:  # noqa: BLE001
            out["tokens"][sym + "_cg"] = {"error": str(exc)[:200]}
        time.sleep(4.0)

    print("[3/3] 跟踪误差 …\n")
    # 股票腿 / 国债腿:DEX 池日线(没有 CEX 现货的代币只能用池子价格)
    for label, net_want in (("SPYX_xstocks", "solana"), ("SPY_ondo", "eth"),
                             ("OUSG", "eth"), ("USDY", "solana"), ("GLDx_xstocks", "solana")):
        net, pool = deepest_pool_from_depth_json(label + ":" + net_want)
        if not pool:
            print("    ", label, "no pool from depth json")
            continue
        px, src = gt_pool_daily(net, pool)
        if len(px) > 20:
            tok[label + "_dex"] = px
            out["tokens"][label + "_dex"] = {"price_source": src, "n_days": len(px),
                                             "first": min(px), "last": max(px),
                                             "pool": pool, "network": net}
            print("    ", label, src, len(px), "pool", pool[:14])
        else:
            print("    ", label, "pool series too short:", src)
        time.sleep(1.0)

    for t, b in BENCH.items():
        if t not in tok or not bench.get(b):
            out["tracking"][f"{t}_vs_{b}"] = {"error": "missing series"}
            continue
        rec = {"token": t, "benchmark": b,
               "price_ratio": ratio_drift(tok[t], bench[b]),
               "by_offset": {}}
        for off in OFFSETS:
            rec["by_offset"][str(off)] = te_stats(tok[t], bench[b], offset=off)
        # ⚠️ 2026-10-30(T-213)修:原写法 `if best_off := max(...)` 把 best_off == 0 当假值
        # ⇒ 最佳对齐恰是 offset 0(黄金/股票腿都是)时,5 日块检验从来没跑过。
        # 现在先取值再判空,块检验对每条腿都执行。
        best_off = max((o for o in OFFSETS if "corr" in rec["by_offset"][str(o)]),
                        key=lambda o: rec["by_offset"][str(o)]["corr"], default=None)
        if best_off is not None:
            rec["block_5d_at_best_offset"] = te_stats(tok[t], bench[b], offset=best_off, step=5)
        best = max((o for o in OFFSETS if "corr" in rec["by_offset"][str(o)]),
                   key=lambda o: rec["by_offset"][str(o)]["corr"], default=None)
        rec["best_offset"] = best
        rec["aligned"] = rec["by_offset"][str(best)] if best is not None else {}
        out["tracking"][f"{t}_vs_{b}"] = rec
        a = rec["aligned"]
        corr_line = ", ".join(
            f"{k}:{v.get('corr')}" for k, v in rec["by_offset"].items())
        print(f"    {t} vs {b}: best_offset={best} n={a.get('n_days')} corr={a.get('corr')} "
              f"TE_ann={a.get('te_ann_pct')}% drift_ann={a.get('drift_ann_pct')}% "
              f"| corr_by_offset [{corr_line}]")

    print("[4/4] 现金腿:持有收益与应计抖动 …\n")
    out["cash_leg"] = {}
    for sym in CASH_TOKENS:
        if sym not in tok:
            out["cash_leg"][sym] = {"error": "missing series"}
            continue
        st = carry_stats(tok[sym])
        out["cash_leg"][sym] = st
        print(f"    {sym}: n={st.get('n_days')} carry_ann={st.get('carry_ann_pct')}% "
              f"jitter_ann={st.get('accrual_jitter_ann_pct')}% tot={st.get('total_return_pct')}%")

    # T-213(2026-10-30)更正与重报:公共窗口/全窗口两列、零信号对照、候选差异、基线
    try:
        t213_analysis(out, tok, bench)
    except Exception as exc:  # noqa: BLE001
        out["t213_correction"] = {"error": f"{type(exc).__name__}: {exc}"}
        print("   [T-213] ERR", type(exc).__name__, str(exc)[:200])

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t210_tracking.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print("WROTE", path)


# ══════════════════════════════════════════════════════════════════════════
# T-213(2026-10-30):更正与重报
#   ② 逐日 TE / 5 日不重叠块 TE / 累计 price_ratio / 波动比 —— 公共窗口 + 各自全窗口
#   ③ 零信号对照:基准 block_permute ≥1000 次,报实际 TE 的分位;候选之间的差走同一对照
#   ④ 基线:GLD vs XAUUSD(不代币化的黄金腿)、SPY(ETF 本身)vs SPY 指数口径
#   零分布/分位一律用 src/data/evaluation/apparatus.py(不自己手写)
# ══════════════════════════════════════════════════════════════════════════
NULL_N = 2000
NULL_SEED = 20261030


def make_rows(dates, series):
    """dates: 有序日期;series: {名称: {日期: 价格}} → [{'d','gap','r':{名: 日收益}}]"""
    rows = []
    for i in range(1, len(dates)):
        prev, cur = dates[i - 1], dates[i]
        r = {}
        for name, px in series.items():
            r[name] = px[cur] / px[prev] - 1.0
        gap = (datetime.date.fromisoformat(cur) - datetime.date.fromisoformat(prev)).days
        rows.append({"d": cur, "gap": gap, "r": r})
    return rows


def te_stats_from(rt, rb, periods=365):
    """给定两条同轴收益 ⇒ corr / TE(年化) / drift / 波动 / 波动比。
    periods=365 逐日、73 = 365/5 五日块、52 自然周块。"""
    n = len(rt)
    if n < 5:
        return None
    mt, mb = statistics.mean(rt), statistics.mean(rb)
    cov = sum((a - mt) * (b - mb) for a, b in zip(rt, rb)) / (n - 1)
    sdt, sdb = statistics.stdev(rt), statistics.stdev(rb)
    diffs = [a - b for a, b in zip(rt, rb)]
    sd = statistics.stdev(diffs)
    return {
        "n": n,
        "corr": round(cov / (sdt * sdb), 4) if sdt and sdb else None,
        "te_ann_pct": round(sd * math.sqrt(periods) * 100, 3),
        "te_bps": round(sd * 1e4, 2),
        "drift_ann_pct": round(statistics.mean(diffs) * periods * 100, 3),
        "tok_vol_ann_pct": round(sdt * math.sqrt(periods) * 100, 2),
        "ben_vol_ann_pct": round(sdb * math.sqrt(periods) * 100, 2),
        "vol_ratio": round(sdt / sdb, 4) if sdb else None,
    }


def te_from_rows(rows, arm, bench="bench", periods=365):
    return te_stats_from([x["r"][arm] for x in rows], [x["r"][bench] for x in rows], periods)


def step_blocks(rows, arms, step=5):
    """不重叠的 step 日块:rows[0..step-1]、rows[step..2*step-1]……(从第一对开始,不丢头部)。
    所有 arm 共用同一组块边界 ⇒ 腿与腿之间可比。"""
    out = {a: [] for a in arms}
    meta = []
    for k in range(0, len(rows) - step + 1, step):
        chunk = rows[k:k + step]
        if len(chunk) < step:
            break
        for a in arms:
            out[a].append(math.prod([1 + c["r"][a] for c in chunk]) - 1)
        meta.append({"from": chunk[0]["d"], "to": chunk[-1]["d"], "n_days": step})
    return out, meta


def week_blocks(rows, arm, bench="bench"):
    """ISO 自然周块(gap==1 的周内相邻对复合)。次要口径:周一→周五 = 5 个日历日。"""
    buckets = {}
    for x in rows:
        if x["gap"] != 1:
            continue
        y, w, _ = datetime.date.fromisoformat(x["d"]).isocalendar()
        buckets.setdefault((y, w), []).append(x)
    out = []
    for key in sorted(buckets):
        rs = buckets[key]
        if len(rs) < 4:
            continue
        out.append({
            "week": "%dW%02d" % key,
            "n_days": len(rs),
            "r_tok": math.prod([1 + c["r"][arm] for c in rs]) - 1,
            "r_bench": math.prod([1 + c["r"][bench] for c in rs]) - 1,
            "last_day": rs[-1]["d"],
        })
    return out


def window_slice(px, start, end):
    return {d: v for d, v in px.items() if start <= d <= end}


def series_report(tok, bench, label, window_label):
    """一条腿的四个量:逐日 TE / 5 日块 TE / 累计 price_ratio / 波动比。"""
    dates = sorted(set(tok) & set(bench))
    rows = make_rows(dates, {"tok": tok, "bench": bench})
    gap1 = [x for x in rows if x["gap"] == 1]
    blocks5, meta5 = step_blocks(rows, ["tok", "bench"], step=5)
    wk = week_blocks(rows, "tok")
    gaps = {}
    for x in rows:
        gaps[x["gap"]] = gaps.get(x["gap"], 0) + 1
    rep = {
        "label": label,
        "window": window_label,
        "n_days_all": len(rows),
        "n_days_gap1": len(gap1),
        "gap_hist": {str(k): v for k, v in sorted(gaps.items())},
        "first_day": rows[0]["d"] if rows else None,
        "last_day": rows[-1]["d"] if rows else None,
        "daily_te": te_from_rows(rows, "tok"),
        "daily_te_gap1": te_from_rows(gap1, "tok"),
        "block5_te": te_stats_from(blocks5["tok"], blocks5["bench"], periods=365.0 / 5),
        "block5_meta": {"step_days": 5, "n_blocks": len(meta5),
                        "first_block": meta5[0] if meta5 else None,
                        "last_block": meta5[-1] if meta5 else None},
        "week_block_te": te_stats_from([b["r_tok"] for b in wk],
                                       [b["r_bench"] for b in wk], periods=52),
        "week_block_meta": {"n_blocks": len(wk),
                            "first_week": wk[0]["week"] if wk else None,
                            "last_week": wk[-1]["week"] if wk else None,
                            "mean_days_per_block": round(
                                statistics.mean(b["n_days"] for b in wk), 2) if wk else None},
        "price_ratio": ratio_drift(tok, bench),
    }
    return rep, rows, blocks5


def flag_outliers(rows, thresh=0.005):
    """标出 |r_tok − r_bench| 超过阈值的日子(数据源坏点 / 口径跳变),
    并给出剔除这些日子后的 TE(敏感性检查)。阈值固定,不因结果调整。"""
    flagged = [x["d"] for x in rows
               if abs(x["r"]["tok"] - x["r"]["bench"]) > thresh]
    fset = set(flagged)
    keep = [x for x in rows if x["d"] not in fset]
    te_excl = te_stats_from([x["r"]["tok"] for x in keep],
                             [x["r"]["bench"] for x in keep])
    return {
        "threshold_bps": round(thresh * 10000, 1),
        "n_flagged": len(flagged),
        "flagged_days": flagged,
        "n_kept": len(keep),
        "te_ann_pct_excl_flagged": te_excl["te_ann_pct"] if te_excl else None,
        "corr_excl_flagged": te_excl["corr"] if te_excl else None,
    }


def null_daily(rows, n=NULL_N, seed=NULL_SEED, block=5):
    """零信号对照(逐日):打乱基准的日收益(块长 5 天),重算 TE,报实际 TE 的分位。
    零分布中心 ≈ sqrt(代币波动² + 基准波动²)(两者被打散成无关)⇒ 这是「完全没在跟踪」的 TE。"""
    rt = [x["r"]["tok"] for x in rows]
    rb = [x["r"]["bench"] for x in rows]
    actual = te_stats_from(rt, rb)
    if not actual:
        return {"error": "too few days"}

    def one(rng):
        perm = list(block_permute(rb, block, rng))
        s = te_stats_from(rt, perm)
        return s["te_ann_pct"] if s else float("nan")

    try:
        null = null_distribution(one, n, seed, actual=actual["te_ann_pct"])
    except NoOpNull as exc:
        return {"error": f"NoOpNull: {exc}"}
    p = percentile_of(actual["te_ann_pct"], null)
    return {
        "actual_te_ann_pct": actual["te_ann_pct"],
        "n_draws": int(len(null)),
        "permute_block_days": block,
        "null_median": round(float(np.median(null)), 3),
        "null_p05": round(float(np.percentile(null, 5)), 3),
        "null_p95": round(float(np.percentile(null, 95)), 3),
        "percentile_of_actual": p,
        "verdict": (f"实际 TE 在零分布的第 {p * 100:.1f} 分位(远低于 50 ⇒ 不是随机噪声)"
                    if p is not None else None),
    }


def null_block(blocks5, n=NULL_N, seed=NULL_SEED + 1):
    """零信号对照(5 日块):打乱块级的基准收益,重算块 TE。"""
    rt, rb = blocks5["tok"], blocks5["bench"]
    actual = te_stats_from(rt, rb, periods=365.0 / 5)
    if not actual:
        return {"error": "too few blocks"}

    def one(rng):
        perm = list(block_permute(rb, 1, rng))
        s = te_stats_from(rt, perm, periods=365.0 / 5)
        return s["te_ann_pct"] if s else float("nan")

    try:
        null = null_distribution(one, n, seed, actual=actual["te_ann_pct"])
    except NoOpNull as exc:
        return {"error": f"NoOpNull: {exc}"}
    p = percentile_of(actual["te_ann_pct"], null)
    return {
        "actual_te_ann_pct": actual["te_ann_pct"],
        "n_draws": int(len(null)),
        "null_median": round(float(np.median(null)), 3),
        "null_p05": round(float(np.percentile(null, 5)), 3),
        "null_p95": round(float(np.percentile(null, 95)), 3),
        "percentile_of_actual": p,
        "verdict": (f"实际块 TE 在零分布的第 {p * 100:.1f} 分位" if p is not None else None),
    }


def diff_null(tok_a, tok_b, bench, dates, label, n=NULL_N, seed=NULL_SEED + 2, block=5):
    """候选之间的差(XAUT−PAXG、SPYX−Ondo)过同一套零信号对照。
    同一组日期、同一份被打乱的基准 ⇒ 零分布里的差 = 「两条腿都不跟踪时」的差
    (≈ 两条腿自身波动率之差,不是 0)⇒ 观测差要落在零分布尾部才算「差距可读」。"""
    rows = make_rows(dates, {"a": tok_a, "b": tok_b, "bench": bench})
    sa = te_from_rows(rows, "a")
    sb = te_from_rows(rows, "b")
    if not sa or not sb:
        return {"error": "too few days"}
    actual_diff = sa["te_ann_pct"] - sb["te_ann_pct"]
    blocks, meta = step_blocks(rows, ["a", "b", "bench"], step=5)
    ba = te_stats_from(blocks["a"], blocks["bench"], periods=365.0 / 5)
    bb = te_stats_from(blocks["b"], blocks["bench"], periods=365.0 / 5)

    def one(rng):
        perm = list(block_permute([x["r"]["bench"] for x in rows], block, rng))
        ra = [x["r"]["a"] for x in rows]
        rb_ = [x["r"]["b"] for x in rows]
        return te_stats_from(ra, perm)["te_ann_pct"] - te_stats_from(rb_, perm)["te_ann_pct"]

    def one_block(rng):
        perm = list(block_permute(blocks["bench"], 1, rng))
        return (te_stats_from(blocks["a"], perm, periods=365.0 / 5)["te_ann_pct"]
                - te_stats_from(blocks["b"], perm, periods=365.0 / 5)["te_ann_pct"])

    out = {
        "label": label,
        "n_days": len(dates),
        "first_day": dates[0] if dates else None,
        "last_day": dates[-1] if dates else None,
        "daily": {
            "te_a_ann_pct": sa["te_ann_pct"], "te_b_ann_pct": sb["te_ann_pct"],
            "observed_diff_pp": round(actual_diff, 3),
        },
        "block5": {
            "n_blocks": len(meta),
            "te_a_ann_pct": ba["te_ann_pct"] if ba else None,
            "te_b_ann_pct": bb["te_ann_pct"] if bb else None,
            "observed_diff_pp": (round(ba["te_ann_pct"] - bb["te_ann_pct"], 3)
                                 if ba and bb else None),
        },
    }
    for key, fn, act in (("daily", one, actual_diff),
                         ("block5", one_block, out["block5"]["observed_diff_pp"])):
        if act is None:
            continue
        try:
            null = null_distribution(fn, n, seed)
        except NoOpNull as exc:
            out[key]["null"] = {"error": f"NoOpNull: {exc}"}
            continue
        p = percentile_of(act, null)
        p2 = min(1.0, 2 * min(p, 1 - p)) if p is not None else None
        out[key].update({
            "n_draws": int(len(null)),
            "null_median_diff_pp": round(float(np.median(null)), 3),
            "null_p05_pp": round(float(np.percentile(null, 5)), 3),
            "null_p95_pp": round(float(np.percentile(null, 95)), 3),
            "percentile_of_observed": p,
            "two_sided_p": p2,
            "verdict": ("差距可读" if (p2 is not None and p2 < 0.05)
                        else "差距不可读(观测差落在零分布中段,分位 %s)"
                        % ("NA" if p is None else f"{p:.3f}")),
        })
    return out


def fetch_spx_series():
    """标普 500 指数日线。试公开源,记录每个源的成败(拿不到也是结论的一部分)。
    2026-10-30 追加 FRED(SP500 = S&P Dow Jones 官方指数收盘),前两个源当时取不到。"""
    attempts = []
    out = {}
    src = None
    for sym in ("i:SPX", "i:SP500", "i:^GSPC", "i:GSPC"):
        url = f"https://stockanalysis.com/api/symbol/{sym}/history?range=5Y&period=Daily"
        try:
            d = get(url)
            rows = d.get("data") if isinstance(d, dict) else None
            if rows:
                out = {r["t"]: float(r["c"]) for r in rows if r.get("c")}
                attempts.append({"source": "stockanalysis", "symbol": sym,
                                 "ok": True, "n_days": len(out)})
                src = "stockanalysis:" + sym
                break
            attempts.append({"source": "stockanalysis", "symbol": sym, "ok": False,
                             "note": "empty data"})
        except Exception as exc:  # noqa: BLE001
            attempts.append({"source": "stockanalysis", "symbol": sym, "ok": False,
                             "note": f"{type(exc).__name__}: {str(exc)[:100]}"})
    if not out:
        try:
            url = ("https://api.investing.com/api/financialdata/historical/166"
                   "?start-date=2024-08-01&end-date=2026-10-29"
                   "&interval=P1D&time-frame=Daily")
            d = get(url)
            rows = d.get("data") if isinstance(d, dict) else None
            if rows:
                out = {r["date"]: float(r["close"]) for r in rows if r.get("close")}
                attempts.append({"source": "investing.com", "symbol": "SPX(166)",
                                 "ok": True, "n_days": len(out)})
                src = "investing.com:SPX(166)"
            else:
                attempts.append({"source": "investing.com", "symbol": "SPX(166)",
                                 "ok": False, "note": "empty data"})
        except Exception as exc:  # noqa: BLE001
            attempts.append({"source": "investing.com", "symbol": "SPX(166)",
                             "ok": False, "note": f"{type(exc).__name__}: {str(exc)[:100]}"})
    if not out:
        # FRED:SP500 —— S&P Dow Jones 官方指数收盘,CSV 无需 key
        try:
            url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                raw = r.read().decode("utf-8", "replace")
            out = {}
            for line in raw.strip().split("\n")[1:]:
                parts = line.split(",")
                if len(parts) != 2:
                    continue
                d, v = parts[0].strip(), parts[1].strip()
                if not v or v == ".":
                    continue
                out[d] = float(v)
            if out:
                attempts.append({"source": "fred", "symbol": "SP500", "ok": True,
                                 "n_days": len(out), "first_day": min(out),
                                 "last_day": max(out),
                                 "note": "S&P Dow Jones 官方指数收盘(CSV,无需 key)"})
                src = "fred:SP500"
            else:
                attempts.append({"source": "fred", "symbol": "SP500", "ok": False,
                                 "note": "empty data"})
        except Exception as exc:  # noqa: BLE001
            attempts.append({"source": "fred", "symbol": "SP500", "ok": False,
                             "note": f"{type(exc).__name__}: {str(exc)[:100]}"})
    return out, attempts, src


def t213_analysis(out, tok, bench):
    """T-213 更正与重报:公共窗口 + 全窗口两列、零信号对照、候选差异、基线。"""
    print("   [T-213] 更正与重报 …")
    res = {
        "generated_at_utc": now(),
        "definition": {
            "alignment": "代币与基准同窗口 [d-1 → d](offset 0);基准在美国收市结算、代币 24/7 ⇒ 仍有 ~21h 日界错位",
            "daily_te": "逐日 TE(年化)= std(r_tok − r_bench)·sqrt(365)",
            "gap1": "只保留基准相邻日(gap==1)的成对;周五→周一(gap==3)被剔除:代币 7×24、基准休市,口径不齐",
            "block5_te": "5 日不重叠块:连续 5 个成对日收益复合,块 TE(年化)= std(块差)·sqrt(365/5)",
            "week_block_te": "自然周块(次要口径):周内 gap==1 的逐日收益复合,块 TE(年化)= std·sqrt(52)",
            "price_ratio": "代币价 / 基准价 的累计变化(%)",
            "vol_ratio": "代币年化波动 / 基准年化波动",
            "null_control": ("基准日收益用 src/data/evaluation/apparatus.py 的 block_permute 打乱(块长 5 天),"
                             "≥1000 次重算 TE,报实际 TE 的分位"),
            "seed": NULL_SEED, "n_draws": NULL_N,
        },
        "series": {}, "candidate_differences": {},
        "baselines": {}, "spx_fetch_attempts": [],
    }

    legs = [
        ("PAXG", "PAXG", "XAUUSD", "黄金:Paxos Gold"),
        ("XAUT", "XAUT", "XAUUSD", "黄金:Tether Gold"),
        ("SPYX", "SPYX_xstocks_dex", "SPY", "股票:xStocks SPYX(Solana 池)"),
        ("SPY_ondo", "SPY_ondo_dex", "SPY", "股票:Ondo SPY(Ethereum 池)"),
    ]

    # ── 公共窗口:四条腿的日线交集
    spans = []
    for name, tkey, bkey, _ in legs:
        if tkey in tok and bench.get(bkey):
            ds = sorted(set(tok[tkey]) & set(bench[bkey]))
            if ds:
                spans.append((ds[0], ds[-1]))
    if not spans:
        res["error"] = "no common series"
        out["t213_correction"] = res
        return
    common_start = max(s[0] for s in spans)
    common_end = min(s[1] for s in spans)
    avail = [set(tok[t]) for _, t, _, _ in legs if t in tok]
    inter = set.intersection(*avail) if avail else set()
    res["common_window"] = {
        "start": common_start, "end": common_end,
        "n_days": len([d for d in sorted(inter) if common_start <= d <= common_end]),
        "note": "四条腿的价格日线交集(XAUUSD 基准含周末行,SPY 基准只有工作日)",
    }

    for name, tkey, bkey, desc in legs:
        if tkey not in tok or not bench.get(bkey):
            res["series"][name] = {"error": "missing series"}
            continue
        rep_full, rows_full, blocks_full = series_report(
            tok[tkey], bench[bkey], name + " vs " + bkey, "full_window")
        rep_cw, rows_cw, blocks_cw = series_report(
            window_slice(tok[tkey], common_start, common_end),
            window_slice(bench[bkey], common_start, common_end),
            name + " vs " + bkey, "common_window")
        res["series"][name] = {
            "desc": desc, "token_key": tkey, "benchmark": bkey,
            "full_window": rep_full, "common_window": rep_cw,
            "null_controls": {
                "full_window_daily": null_daily(rows_full),
                "full_window_block5": null_block(blocks_full),
                "common_window_daily": null_daily(rows_cw, seed=NULL_SEED + 3),
                "common_window_block5": null_block(blocks_cw, seed=NULL_SEED + 4),
            },
            "outlier_check": {
                "full_window": flag_outliers(rows_full),
                "common_window": flag_outliers(rows_cw),
            },
        }
        print(f"      {name}: 全窗口 日TE {rep_full['daily_te'] and rep_full['daily_te']['te_ann_pct']}% "
              f"5日块 {rep_full['block5_te'] and rep_full['block5_te']['te_ann_pct']}% | "
              f"公共窗口 日TE {rep_cw['daily_te'] and rep_cw['daily_te']['te_ann_pct']}% "
              f"5日块 {rep_cw['block5_te'] and rep_cw['block5_te']['te_ann_pct']}%")

    # ── 候选之间的差(同一对照)
    for label, a_key, b_key, bkey, a_name, b_name in (
            ("XAUT_minus_PAXG", "XAUT", "PAXG", "XAUUSD", "XAUT", "PAXG"),
            ("SPYX_minus_SPY_ondo", "SPYX_xstocks_dex", "SPY_ondo_dex", "SPY",
             "SPYX", "SPY(ondo)")):
        if a_key in tok and b_key in tok and bench.get(bkey):
            ds = sorted(set(tok[a_key]) & set(tok[b_key]) & set(bench[bkey]))
            ds = [d for d in ds if common_start <= d <= common_end]
            res["candidate_differences"][label] = diff_null(
                tok[a_key], tok[b_key], bench[bkey], ds, f"{a_name} − {b_name}")
            d = res["candidate_differences"][label]
            print("      差", label, "日:", (d.get("daily") or {}).get("verdict"),
                  "| 5日块:", (d.get("block5") or {}).get("verdict"))
        else:
            res["candidate_differences"][label] = {"error": "missing series"}

    # ── ④ 基线:不代币化那条腿的跟踪成本
    try:
        gld, srcs, _ = supabase_ohlcv("GLD")
        res["baselines"]["GLD_vs_XAUUSD"] = {
            "why": "不代币化的黄金腿:实物支撑 ETF 的自身跟踪成本(费用 + 期货展期)",
            "source": "supabase:ohlcv_daily(" + ",".join(srcs) + ",prefer=eodhd)",
            "full_window": series_report(gld, bench["XAUUSD"], "GLD vs XAUUSD", "full_window")[0],
            "common_window": series_report(
                window_slice(gld, common_start, common_end),
                window_slice(bench["XAUUSD"], common_start, common_end),
                "GLD vs XAUUSD", "common_window")[0],
        }
        gw = res["baselines"]["GLD_vs_XAUUSD"]["common_window"]
        print("      基线 GLD vs XAUUSD(公共窗口): 日TE "
              f"{gw['daily_te'] and gw['daily_te']['te_ann_pct']}% 5日块 "
              f"{gw['block5_te'] and gw['block5_te']['te_ann_pct']}%")
    except Exception as exc:  # noqa: BLE001
        res["baselines"]["GLD_vs_XAUUSD"] = {"error": f"{type(exc).__name__}: {exc}"}

    # 股票:SPY(ETF 本身) vs SPY 指数口径 —— 指数序列能不能拿到是这一步的前提
    spx, attempts, spx_src = fetch_spx_series()
    res["spx_fetch_attempts"] = attempts
    if spx:
        rep_full, rows_full, _ = series_report(
            spx, bench["SPY"], "SPY(ETF) vs SPX(指数)", "full_window")
        rep_cw, rows_cw, _ = series_report(
            window_slice(spx, common_start, common_end),
            window_slice(bench["SPY"], common_start, common_end),
            "SPY(ETF) vs SPX(指数)", "common_window")
        res["baselines"]["SPY_etf_vs_index"] = {
            "why": "不代币化的股票腿:ETF 自身对指数的跟踪成本",
            "spx_source": spx_src,
            "full_window": rep_full, "common_window": rep_cw,
            "null_controls": {"common_window_daily": null_daily(rows_cw, seed=NULL_SEED + 5)},
            "outlier_check": {
                "full_window": flag_outliers(rows_full),
                "common_window": flag_outliers(rows_cw),
            },
        }
        print("      基线 SPY(ETF) vs SPX(指数) 全窗口 日TE "
              f"{rep_full['daily_te'] and rep_full['daily_te']['te_ann_pct']}% 5日块 "
              f"{rep_full['block5_te'] and rep_full['block5_te']['te_ann_pct']}% | 公共窗口 日TE "
              f"{rep_cw['daily_te'] and rep_cw['daily_te']['te_ann_pct']}% 5日块 "
              f"{rep_cw['block5_te'] and rep_cw['block5_te']['te_ann_pct']}%")
    else:
        res["baselines"]["SPY_etf_vs_index"] = {
            "error": "S&P 500 指数日线在本环境取不到(见 spx_fetch_attempts);库内 ohlcv_daily 无指数序列",
            "fallback": ("用同一只 ETF 的两个数据源(eodhd vs yfinance)之间的偏离度 = 本方法能分辨的"
                         "最小尺度(测量分辨率下限),代替 ETF-vs-指数"),
        }

    # 同一只 ETF 两个数据源的偏离 = 测量分辨率下限(两种情况下都算,作对照)
    try:
        spy_yf, srcs2, _ = supabase_ohlcv("SPY", want_source="yfinance", strict=True)
        res["baselines"]["SPY_source_divergence"] = {
            "why": "同一只 ETF、两个数据源(eodhd vs yfinance)的偏离度 = 测量分辨率下限",
            "source": "supabase:ohlcv_daily(" + ",".join(srcs2) + ",prefer=yfinance)",
            "common_window": series_report(
                window_slice(spy_yf, common_start, common_end),
                window_slice(bench["SPY"], common_start, common_end),
                "SPY(eodhd) vs SPY(yfinance)", "common_window")[0],
        }
        sd = res["baselines"]["SPY_source_divergence"]["common_window"]
        print("      基线 SPY(eodhd) vs SPY(yfinance): 日TE "
              f"{sd['daily_te'] and sd['daily_te']['te_ann_pct']}% 5日块 "
              f"{sd['block5_te'] and sd['block5_te']['te_ann_pct']}%")
    except Exception as exc:  # noqa: BLE001
        res["baselines"]["SPY_source_divergence"] = {"error": f"{type(exc).__name__}: {exc}"}

    out["t213_correction"] = res


if __name__ == "__main__":
    main()
