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
import time
import urllib.error
import urllib.request

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
def supabase_ohlcv(symbol, want_source="eodhd"):
    """ohlcv_daily:按 trade_date 倒序取最近 N 条(带 order=),再本地升序 + 按来源去重。"""
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
            pref[d] = float(row["close"])
        else:
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
        for k in range(step - 1, len(pairs) - step, step):
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
        if best_off := max((o for o in OFFSETS if "corr" in rec["by_offset"][str(o)]),
                            key=lambda o: rec["by_offset"][str(o)]["corr"], default=None):
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

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t210_tracking.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print("WROTE", path)


if __name__ == "__main__":
    main()
