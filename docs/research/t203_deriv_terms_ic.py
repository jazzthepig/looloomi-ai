#!/usr/bin/env python3
"""T-203 / S-688 独立复算(B 道):CIS 衍生品两项(funding 项 / OI-市值项)对 30 天超额的截面 IC。

台账 S-688(2026-10-26 10:30 UTC 预注册)一字照抄:面板、两项公式、统计量、判定都不改。
本脚本是**表 `cis_standard_outcomes` 的精确复刻**:该表对 publishable key 不可读(42501),
所以按它自己的写入代码(src/data/cis/standard_outcomes.py)复刻出同一批 (symbol, d) 与同一个 alpha:
  收盘 = asset_mcap_daily 的原始 CG 日收盘(source=coingecko_pro_market_chart),迁移币按 S-537 接段;
  点位 = 已发布(cis_official_daily)优先、之前的日子用同版本重建(cis_rebuild_daily, d ≤ 最近发布日);
  alpha = (a_ret − b_ret),a_ret = 收盘(d+30)/收盘(d) − 1,b_ret 同式用 BTC;落表前四舍五入到 6 位(与表一致)。
只读 Supabase(publishable key,环境变量 SUPABASE_URL / SUPABASE_KEY)。不写库。

用法: python3 docs/research/t203_deriv_terms_ic.py [--cache DIR] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np

# 零分布一律走仓库的共享评价装置(T-203 lane 规则:零分布/盈亏/A/B 只许用 apparatus.py)
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    null_distribution,
    percentile_of,
    shuffle_within,
)

# ── 常量(全部来自仓库源码,不 import)────────────────────────────────────────
CODE_REF = "cis-standard-v1.3"          # rebuild.CODE_REF
CG_SOURCE = "coingecko_pro_market_chart"  # style/header.SOURCE
HORIZON = 30                             # standard_outcomes.HORIZON
MIN_NAMES = 8                           # 台账:该项有定义的名字 ≥ 8
SPLIT = "2024-07-01"                    # 台账:上下半段切点
TRADFI_CLASSES = frozenset({"US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity"})

# cis_provider.CRYPTO_ASSETS 的 coingecko id(24 个加密名)
CRYPTO_COIN = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
    "XRP": "ripple", "ADA": "cardano", "AVAX": "avalanche-2", "DOT": "polkadot",
    "NEAR": "near", "SUI": "sui", "APT": "aptos", "HYPE": "hyperliquid",
    "ARB": "arbitrum", "OP": "optimism", "POL": "polygon-ecosystem-token", "STRK": "starknet",
    "UNI": "uniswap", "AAVE": "aave", "LDO": "lido-dao", "PENDLE": "pendle",
    "LINK": "chainlink", "INJ": "injective-protocol", "TIA": "celestia",
    "ONDO": "ondo-finance", "SKY": "sky",
}
# src/data/cis/migrations.py —— S-537 代币迁移接段
MIGRATIONS = {
    "SKY": {"old_coin": "maker", "ratio": 24000.0},
    "POL": {"old_coin": "matic-network", "ratio": 1.0},
}
# cis_provider._BASE_WEIGHTS(加密五个类)—— 自检用
BASE_WEIGHTS = {
    "L1": {"F": 0.30, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.10},
    "L2": {"F": 0.30, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.10},
    "DeFi": {"F": 0.25, "M": 0.25, "O": 0.25, "S": 0.15, "A": 0.10},
    "RWA": {"F": 0.35, "M": 0.20, "O": 0.20, "S": 0.15, "A": 0.10},
    "Infrastructure": {"F": 0.30, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.10},
}


# ── HTTP(只读)───────────────────────────────────────────────────────────────
def _headers() -> tuple:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出(不要读 .env)")
    return url, {"apikey": key, "Authorization": "Bearer " + key, "Accept": "application/json"}


def fetch(url: str, hdr: dict, table: str, params: dict, cache_dir: str, name: str,
          page: int = 1000) -> list:
    """翻页读。**order= 必须带**(卡上规则:不带 order 时 PostgREST 翻页边界会漂)。"""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    rows: list = []
    off = 0
    while True:
        p = dict(params)
        p["limit"] = page
        p["offset"] = off
        ps = "&".join("%s=%s" % (k, urllib.parse.quote(str(v), safe="(),.*:|+-=<>"))
                      for k, v in p.items())
        req = urllib.request.Request(url + "/rest/v1/" + table + "?" + ps, headers=hdr)
        chunk = None
        for i in range(5):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    chunk = json.loads(r.read().decode())
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and i < 4:
                    time.sleep(2 * (i + 1))
                    continue
                raise
        rows.extend(chunk)
        if len(chunk) < page:
            break
        off += page
    with open(path, "w") as f:
        json.dump(rows, f)
    print("  fetched %-22s %7d rows" % (table, len(rows)), flush=True)
    return rows


# ── 两项公式 —— 一字照抄 cis_provider.calculate_cis_score v4.3(手抄,不 import)──
# 核对处:src/data/cis/cis_provider.py 第 1544–1563 行
def linear_interp(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """同 cis_provider._linear_interp:线性插值,夹在 [min(y0,y1), max(y0,y1)]。"""
    lo, hi = min(y0, y1), max(y0, y1)
    if x1 == x0:
        return (y0 + y1) / 2
    t = (x - x0) / (x1 - x0)
    return max(lo, min(hi, y0 + t * (y1 - y0)))


def fr_adj(fr: float) -> float:
    """funding 项调整值(台账 S-688 第 11 行 = cis_provider 第 1544–1553 行):
       fr > 0.0005      → interp(fr, 0.0005, 0.002, −8, −15)
       0.0001 < fr ≤ 0.0005 → interp(fr, 0.0001, 0.0005, 3, 0)
       −0.0001 < fr ≤ 0.0001 → 0
       −0.0005 < fr ≤ −0.0001 → +2
       fr ≤ −0.0005      → −3
    """
    if fr > 0.0005:
        return linear_interp(fr, 0.0005, 0.002, -8.0, -15.0)
    if fr > 0.0001:
        return linear_interp(fr, 0.0001, 0.0005, 3.0, 0.0)
    if fr > -0.0001:
        return 0.0
    if fr > -0.0005:
        return 2.0
    return -3.0


def oi_adj_of(ratio: float) -> float:
    """OI/市值项调整值(台账 S-688 第 12 行 = cis_provider 第 1556–1563 行):
       r > 1        → interp(r, 1, 3, −5, −10)
       0.5 < r ≤ 1  → interp(r, 0.5, 1, −3, −5)
       r < 0.2      → +3
       其余(0.2 ≤ r ≤ 0.5) → 0
    """
    if ratio > 1.0:
        return linear_interp(ratio, 1.0, 3.0, -5.0, -10.0)
    if ratio > 0.5:
        return linear_interp(ratio, 0.5, 1.0, -3.0, -5.0)
    if ratio < 0.2:
        return 3.0
    return 0.0


# ── 相关 ───────────────────────────────────────────────────────────────────
def ranks(xs: list) -> list:
    """平均并列名次(1 起)。"""
    n = len(xs)
    order = sorted(range(n), key=lambda i: xs[i])
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def pearson(xs: list, ys: list) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def spearman(xs: list, ys: list) -> float:
    """Spearman ρ = 秩的 Pearson。"""
    return pearson(ranks(xs), ranks(ys))


def partial_corr_rank(x: list, y: list, z: list) -> float:
    """偏相关(控 z):ρ_xy·z = (ρ_xy − ρ_xz·ρ_yz) / √((1−ρ_xz²)(1−ρ_yz²))。
    三者当天各自排名后代入(台账 S-688 第 15 行)。"""
    rx, ry, rz = ranks(x), ranks(y), ranks(z)
    rxy = pearson(rx, ry)
    rxz = pearson(rx, rz)
    ryz = pearson(ry, rz)
    if any(not math.isfinite(v) for v in (rxy, rxz, ryz)):
        return float("nan")
    den = math.sqrt((1.0 - rxz * rxz) * (1.0 - ryz * ryz))
    if den <= 0:
        return float("nan")
    return (rxy - rxz * ryz) / den


def month_of(d: str) -> str:
    return d[:7]


def _avg_rank_np(a) -> "np.ndarray":
    """numpy 版平均并列名次(与 ranks() 同一口径,给零分布循环用)。"""
    arr = np.asarray(a, dtype=float)
    n = arr.size
    order = np.argsort(arr, kind="mergesort")
    out = np.empty(n, dtype=float)
    srt = arr[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and srt[j + 1] == srt[i]:
            j += 1
        out[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return out


def spearman_np(x, y) -> float:
    rx, ry = _avg_rank_np(x), _avg_rank_np(y)
    if rx.size < 3:
        return float("nan")
    sx = rx.std()
    sy = ry.std()
    if sx <= 0 or sy <= 0:
        return float("nan")
    return float(((rx - rx.mean()) * (ry - ry.mean())).mean() / (sx * sy))


def partial_corr_rank_multi(x: list, y: list, controls: list) -> float:
    """偏相关(控多个变量):把 x、y 的秩分别对控制变量的秩做最小二乘回归,再对残差求 Pearson。
    与 partial_corr_rank(单控制)同族;单控制时两者应当一致(脚本自检)。"""
    rx, ry = _avg_rank_np(x), _avg_rank_np(y)
    cols = [_avg_rank_np(c) for c in controls]
    Z = np.column_stack([np.ones(len(rx))] + cols)
    ex = rx - Z @ np.linalg.lstsq(Z, rx, rcond=None)[0]
    ey = ry - Z @ np.linalg.lstsq(Z, ry, rcond=None)[0]
    sx, sy = ex.std(), ey.std()
    if sx <= 0 or sy <= 0:
        return float("nan")
    return float(((ex - ex.mean()) * (ey - ey.mean())).mean() / (sx * sy))


# ── 统计量 ─────────────────────────────────────────────────────────────────
def monthly_stats(daily: dict, label: str) -> dict:
    """daily:{d: rho} → 逐月月均 ρ、月数、月 t、两半月均。台账:日 ρ 按自然月取平均 → 月序列;
    t = 月均 / 月标准差(ddof=1) × √月数;上下半段以 2024-07-01 切(月序列按月份切)。"""
    by_month: dict = defaultdict(list)
    for d, v in daily.items():
        if v is not None and math.isfinite(v):
            by_month[month_of(d)].append(v)
    monthly = {m: round(sum(v) / len(v), 6) for m, v in sorted(by_month.items())}
    vals = list(monthly.values())
    n_m = len(vals)
    if n_m < 2:
        return {"monthly": monthly, "n_months": n_m, "n_days_total": sum(len(v) for v in by_month.values()),
                "mean_rho": None, "monthly_sd": None, "t": None,
                "half1": {"mean_rho": None, "n_months": 0}, "half2": {"mean_rho": None, "n_months": 0},
                "verdict": None, "label": label}
    mean = sum(vals) / n_m
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n_m - 1))
    t = mean / sd * math.sqrt(n_m) if sd > 0 else None
    h1 = [v for m, v in monthly.items() if m < SPLIT[:7]]
    h2 = [v for m, v in monthly.items() if m >= SPLIT[:7]]
    return {
        "monthly": monthly,
        "n_months": n_m,
        "n_days_total": sum(len(v) for v in by_month.values()),
        "mean_rho": round(mean, 6),
        "monthly_sd": round(sd, 6),
        "t": round(t, 6) if t is not None else None,
        "half1": {"mean_rho": round(sum(h1) / len(h1), 6) if h1 else None, "n_months": len(h1),
                  "months": sorted(m for m in monthly if m < SPLIT[:7])},
        "half2": {"mean_rho": round(sum(h2) / len(h2), 6) if h2 else None, "n_months": len(h2),
                  "months": sorted(m for m in monthly if m >= SPLIT[:7])},
        "verdict": None,
        "label": label,
    }


def verdict_funding(s: dict) -> str:
    """台账 S-688 第 20 行:月 t ≤ −2.0 ⇒ 有害(提移除);月 t ≥ 2.0 且两半同号为正 ⇒ 有用(保留并同源);
    其余 ⇒「证据两边都没有」,不动。"""
    if s["t"] is None:
        return "无定义(没有可用的日 ρ)—— 不动"
    t = s["t"]
    h1, h2 = s["half1"]["mean_rho"], s["half2"]["mean_rho"]
    if t <= -2.0:
        return "有害(月 t ≤ −2.0):提移除提案(走 CIS v2 影子 → 切换流程)"
    if t >= 2.0 and h1 is not None and h2 is not None and h1 > 0 and h2 > 0:
        return "有用(月 t ≥ 2.0 且两半同为正):保留,并让盘中改用同一来源"
    return "「证据两边都没有」,不动(移除也是方法变更)"


def verdict_oi(s: dict, p: dict) -> str:
    """台账 S-688 第 19 行:月均 ρ > 0 且 月 t ≥ 2.0,**且** 偏相关月 t ≥ 2.0,**且** 上下半段月均 ρ 都 > 0
    ⇒ ✅ 写进 CIS 标准提案;否则 ❌,OI 继续只展示。"""
    checks = {
        "月均 ρ > 0": (s["mean_rho"] is not None and s["mean_rho"] > 0),
        "月 t ≥ 2.0": (s["t"] is not None and s["t"] >= 2.0),
        "偏相关月 t ≥ 2.0": (p["t"] is not None and p["t"] >= 2.0),
        "两半月均 ρ 都 > 0": (s["half1"]["mean_rho"] is not None and s["half2"]["mean_rho"] is not None
                             and s["half1"]["mean_rho"] > 0 and s["half2"]["mean_rho"] > 0),
    }
    if all(checks.values()):
        return "✅ 通过:写进 CIS 标准提案(走 CIS v2 影子 → 切换流程)"
    failed = [k for k, v in checks.items() if not v]
    return "❌ 不通过(%s):OI 继续只展示" % "、".join(failed)


# ── 主流程 ─────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/Volumes/CometCloudAI/cometcloud-local/research/t203")
    ap.add_argument("--out", default="docs/research/t203_results.json")
    ap.add_argument("--points-vintage", default="",
                    help="用另一批重建的 signal_pct 作点位(默认用本次读到的最新一批)")
    a = ap.parse_args()

    url, hdr = _headers()
    print("[1/6] pulling ...", flush=True)
    coins = sorted(set(CRYPTO_COIN.values()) | {m["old_coin"] for m in MIGRATIONS.values()})
    mc = fetch(url, hdr, "asset_mcap_daily",
               {"select": "coin_id,d,price,mcap,volume", "source": "eq." + CG_SOURCE,
                "coin_id": "in.(" + ",".join(coins) + ")", "order": "coin_id.asc,d.asc"},
               a.cache, "mcap_daily.json")
    off = fetch(url, hdr, "cis_official_daily",
                {"select": "symbol,d,asset_class,signal,grade,code_ref", "order": "symbol.asc,d.asc"},
                a.cache, "official_daily.json")
    rb = fetch(url, hdr, "cis_rebuild_daily",
               {"select": "symbol,d,asset_class,score,raw_score,signal,signal_pct,grade,regime,computed_at,inputs,"
                          "pillar_f,pillar_m,pillar_o,pillar_s,pillar_a",
                "code_ref": "eq." + CODE_REF, "order": "symbol.asc,d.asc"},
               a.cache, "rb_v13.json")
    dm = fetch(url, hdr, "deriv_metrics_daily",
               {"select": "symbol,d,oi_value_close",
                "symbol": "in.(" + ",".join(sorted(CRYPTO_COIN)) + ")", "order": "symbol.asc,d.asc"},
               a.cache, "deriv_oi.json")
    em = fetch(url, hdr, "signal_edge_map",
               {"select": "benchmark,signal,risk_band,n,avg_alpha_pct,alpha_win_pct",
                "order": "benchmark.asc,signal.asc,risk_band.asc"},
               a.cache, "edge_map.json")

    # ── 收盘序列(原始 CG 日收盘;迁移币按 S-537 接段)────────────────────────
    px_by_coin: dict = defaultdict(dict)
    for r in mc:
        p = r.get("price")
        if p is not None:
            px_by_coin[r["coin_id"]][r["d"][:10]] = float(p)   # 后写覆盖(同 pandas Series 的 dict 语义)
    rb_price: dict = defaultdict(dict)
    for r in rb:
        pr = (r.get("inputs") or {}).get("price")
        if pr is not None:
            rb_price[r["symbol"]][r["d"][:10]] = float(pr)

    closes: dict = {}
    chain_info: dict = {}
    for sym, coin in CRYPTO_COIN.items():
        if sym in MIGRATIONS:
            mig = MIGRATIONS[sym]
            old_px, new_px = px_by_coin[mig["old_coin"]], px_by_coin[coin]
            boundary = None
            for d in sorted(rb_price.get(sym, {})):
                stored = rb_price[sym][d]
                cn = new_px.get(d)
                co = old_px.get(d)
                co = co / mig["ratio"] if co is not None else None
                if cn is None and co is None:
                    continue
                if cn is None:
                    use_old = True
                elif co is None:
                    use_old = False
                else:
                    use_old = abs(stored - co) < abs(stored - cn)
                if use_old:
                    boundary = d
                else:
                    break
            ser = {}
            for d, v in old_px.items():
                if boundary is not None and d <= boundary:
                    ser[d] = v / mig["ratio"]
            ser.update({d: v for d, v in new_px.items() if boundary is None or d > boundary})
            closes[sym] = ser
            chain_info[sym] = {"old_coin": mig["old_coin"], "ratio": mig["ratio"], "old_until": boundary,
                               "n_old": sum(1 for d in ser if boundary is not None and d <= boundary),
                               "n_new": sum(1 for d in ser if boundary is None or d > boundary)}
        else:
            closes[sym] = dict(px_by_coin.get(coin, {}))
    btc_px = closes.get("BTC", {})
    if not btc_px:
        raise SystemExit("BTC 收盘序列为空,退出")
    last_close = max(max(v) for v in closes.values() if v)
    print("  收盘序列: %d 个名字,最后收盘日 %s" % (len(closes), last_close))

    # ── 面板:cis_standard_outcomes 的 crypto 行(σ ≠ BTC)──────────────────
    # 点位的 signal 来自重建的 signal_pct。表是某一批重建写出来的;换批会改 366 行的档位
    # (funding 修复改了 O 支柱 ⇒ 分数变 ⇒ 组内分位变 ⇒ 滞回档位翻)。下面按「哪个版本能把
    # 库内 signal_edge_map 逐格对平」自动认表的那一批。
    cap = max(r["d"][:10] for r in off) if off else None
    rb_by_key = {(r["symbol"], r["d"][:10]): r for r in rb}
    oi_by: dict = {}
    for r in dm:
        v = r.get("oi_value_close")
        if v is not None:
            oi_by[(r["symbol"], r["d"][:10])] = float(v)

    def make_panel(rb_pts: list) -> tuple:
        points: dict = {}
        for r in rb_pts:
            d = r["d"][:10]
            if cap and d > cap:
                continue
            points[(r["symbol"], d)] = {"signal": r.get("signal_pct"), "provenance": "reconstructed",
                                        "asset_class": r.get("asset_class")}
        for r in off:
            d = r["d"][:10]
            points[(r["symbol"], d)] = {"signal": r.get("signal"), "provenance": "published",
                                        "asset_class": r.get("asset_class")}
        panel: dict = defaultdict(list)
        n_no_alpha = 0
        n_pt = 0
        for (sym, d), pt in points.items():
            if pt.get("asset_class") in TRADFI_CLASSES:
                continue
            if not pt.get("signal"):
                continue
            dp = (date.fromisoformat(d) + timedelta(days=HORIZON)).isoformat()
            if dp > last_close:
                continue
            p0 = closes.get(sym, {}).get(d)
            p1 = closes.get(sym, {}).get(dp)
            b0 = btc_px.get(d)
            b1 = btc_px.get(dp)
            if p0 is None or p1 is None or b0 is None or b1 is None:
                n_no_alpha += 1
                continue
            a_ret = p1 / p0 - 1.0
            b_ret = b1 / b0 - 1.0
            d30 = (date.fromisoformat(d) - timedelta(days=HORIZON)).isoformat()
            n_pt += 1
            panel[d].append({"symbol": sym, "d": d, "alpha": round(a_ret - b_ret, 6),
                             "a_ret": round(a_ret, 6), "b_ret": round(b_ret, 6),
                             "is_bench": sym == "BTC",
                             "signal": pt["signal"], "provenance": pt["provenance"],
                             "bench_trail_30d": (round(b0 / btc_px[d30] - 1.0, 6)
                                                 if btc_px.get(d30) else None)})
        # 分数 / funding / 市值(同一行 cis_rebuild_daily —— 本次读到的最新一批)
        for d, rows in panel.items():
            for row in rows:
                r2 = rb_by_key.get((row["symbol"], d), {})
                inp = r2.get("inputs") or {}
                row["score"] = r2.get("score")
                row["raw_score"] = r2.get("raw_score")
                row["pillar_o"] = r2.get("pillar_o")
                row["asset_class"] = r2.get("asset_class")
                row["fr"] = inp.get("funding")
                row["mcap"] = inp.get("mcap")
                fr = row["fr"]
                row["fr_adj"] = fr_adj(float(fr)) if fr is not None else None
                row["oi_adj"] = None
                row["ratio"] = None
        # OI(deriv_metrics_daily,同 symbol 同 d);OI 或市值缺 / ≤ 0 ⇒ 不进 OI 项
        for d, rows in panel.items():
            for row in rows:
                oi = oi_by.get((row["symbol"], d))
                if oi is None or oi <= 0:
                    continue
                mc_v = row["mcap"]
                if mc_v is None or float(mc_v) <= 0:
                    continue
                ratio = oi / float(mc_v)
                row["ratio"] = ratio
                row["oi_adj"] = oi_adj_of(ratio)
        # ── 滞后一天(T-203 lane 规则:信号日当天的派生量,判完必须再挪一天判一次)──
        # funding / OI 都是「当天」的派生量:只用当天的量做出的结论不算数(S-665 / T-178)。
        # 这里把两项的输入整体挪到 d-1(口径完全不变,只是取值日往前挪一天),主口径的数字不动。
        for d, rows in panel.items():
            d1 = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
            for row in rows:
                sym = row["symbol"]
                r1 = rb_by_key.get((sym, d1))
                inp1 = (r1.get("inputs") or {}) if r1 else {}
                fr1 = inp1.get("funding")
                row["fr_lag1"] = fr_adj(float(fr1)) if fr1 is not None else None
                mc1 = inp1.get("mcap")
                oi1 = oi_by.get((sym, d1))
                if oi1 is not None and oi1 > 0 and mc1 is not None and float(mc1) > 0:
                    row["ratio_lag1"] = oi1 / float(mc1)
                    row["oi_adj_lag1"] = oi_adj_of(row["ratio_lag1"])
                else:
                    row["ratio_lag1"] = None
                    row["oi_adj_lag1"] = None
        return panel, n_no_alpha, n_pt

    def band_of(trail: float) -> str:
        if trail < -0.15:
            return "1_deep_off"
        if trail < -0.05:
            return "2_off"
        if trail < 0.05:
            return "3_neutral"
        if trail < 0.15:
            return "4_on"
        return "5_deep_on"

    lib = {(r["signal"], r["risk_band"]): r for r in em if r["benchmark"] == "btc"}
    edge_lib_total = sum(int(r["n"]) for r in em if r["benchmark"] == "btc")

    def edge_cells(panel: dict) -> tuple:
        mine: dict = defaultdict(list)
        for d in panel:
            for row in panel[d]:
                bt = row.get("bench_trail_30d")
                if bt is None:
                    continue
                mine[(row["signal"], band_of(bt))].append(row["alpha"] * 100)
        detail: list = []
        n_match = 0
        max_diff = 0.0
        for key in sorted(set(mine) | set(lib)):
            vals = mine.get(key, [])
            row = lib.get(key)
            n_mine = len(vals)
            avg_mine = round(sum(vals) / n_mine, 2) if n_mine else None
            win_mine = round(100.0 * sum(1 for v in vals if v > 0) / n_mine, 1) if n_mine else None
            n_lib = row["n"] if row else 0
            avg_lib = float(row["avg_alpha_pct"]) if row and row["avg_alpha_pct"] is not None else None
            diff = abs(avg_mine - avg_lib) if (avg_mine is not None and avg_lib is not None) else None
            if n_mine == n_lib:
                n_match += 1
            if diff is not None:
                max_diff = max(max_diff, diff)
            detail.append({"signal": key[0], "band": key[1], "n_mine": n_mine, "n_lib": n_lib,
                           "avg_alpha_pct_mine": avg_mine, "avg_alpha_pct_lib": avg_lib,
                           "win_pct_mine": win_mine,
                           "win_pct_lib": (float(row["alpha_win_pct"]) if row and row["alpha_win_pct"] is not None else None),
                           "abs_diff_pp": diff})
        mine_total = sum(len(v) for v in mine.values())
        return detail, n_match, max_diff, mine_total

    # 候选版本:本次读到的一批 + 缓存目录里留着的旧批 + 指定的版本
    candidates: list = [("current(%s)" % (sorted({r["computed_at"] for r in rb})[-1][:19] if rb else "?"), rb)]
    cur_cache = os.path.join(a.cache, "rb_v13.json")
    for root, _dirs, files in os.walk(a.cache):
        for fn in sorted(files):
            if not (fn.startswith("rb_v13") and fn.endswith(".json")):
                continue
            p = os.path.join(root, fn)
            if os.path.abspath(p) == os.path.abspath(cur_cache):
                continue
            try:
                with open(p) as f:
                    candidates.append((os.path.relpath(p, a.cache), json.load(f)))
            except Exception:
                pass
    if a.points_vintage:
        with open(a.points_vintage) as f:
            candidates.append((os.path.basename(a.points_vintage), json.load(f)))
    best = None
    vintage_checks: list = []
    for label, cand in candidates:
        p, nna, npt = make_panel(cand)
        detail, n_match, max_diff, mine_total = edge_cells(p)
        ok = (n_match == len(detail)) and mine_total == edge_lib_total and max_diff <= 0.005
        vintage_checks.append({"vintage": label, "cells_n_match": n_match, "cells_total": len(detail),
                                "rows_mine": mine_total, "rows_lib": edge_lib_total,
                                "max_abs_diff_pp": round(max_diff, 4), "matches_table": ok})
        print("  版本 %-46s edge map %d/%d 格行数一致,最大差 %.4f pp,行数 %d/%d → %s"
              % (label, n_match, len(detail), max_diff, mine_total, edge_lib_total, "对上" if ok else "对不上"))
        if best is None or (ok, n_match, -max_diff) > (best[3], best[2], -best[4]):
            best = (label, p, n_match, ok, max_diff, nna, npt, detail, mine_total)
    label, panel, n_match, ok, max_diff, n_no_alpha, n_pt, edge_detail, edge_mine_total = best
    print("  采用版本:%s(%s)" % (label, "与表逐格对平" if ok else "与表最接近"))
    all_days = sorted(panel)
    print("  面板: %d 天 × %d 行 = %d (无 alpha %d)" %
          (len(all_days), len({r["symbol"] for r in panel[all_days[0]]}) if all_days else 0,
           sum(len(v) for v in panel.values()), n_no_alpha), flush=True)

    # ── 每日截面 IC ────────────────────────────────────────────────────────
    def daily_ic(term_key: str, min_names: int = MIN_NAMES) -> tuple:
        out: dict = {}
        skipped = {"too_few": 0, "no_variation": 0}
        for d in all_days:
            rows = [r for r in panel[d] if r.get(term_key) is not None and not r["is_bench"]]
            if len(rows) < min_names:
                skipped["too_few"] += 1
                continue
            vals = [float(r[term_key]) for r in rows]
            if len(set(vals)) < 2:
                skipped["no_variation"] += 1
                continue
            rho = spearman(vals, [float(r["alpha"]) for r in rows])
            if math.isfinite(rho):
                out[d] = rho
        return out, skipped

    def daily_partial(term_key: str) -> tuple:
        out: dict = {}
        skipped = {"too_few": 0, "no_variation": 0}
        for d in all_days:
            rows = [r for r in panel[d]
                    if r.get(term_key) is not None and r.get("score") is not None and not r["is_bench"]]
            if len(rows) < MIN_NAMES:
                skipped["too_few"] += 1
                continue
            vals = [float(r[term_key]) for r in rows]
            if len(set(vals)) < 2:
                skipped["no_variation"] += 1
                continue
            pc = partial_corr_rank(vals, [float(r["alpha"]) for r in rows],
                                   [float(r["score"]) for r in rows])
            if math.isfinite(pc):
                out[d] = pc
        return out, skipped

    print("[2/6] daily IC ...", flush=True)
    d_funding, sk_funding = daily_ic("fr_adj")
    d_oi, sk_oi = daily_ic("oi_adj")
    d_ratio, sk_ratio = daily_ic("ratio")
    d_fr_level, sk_fr_level = daily_ic("fr")
    d_pc_oi, sk_pc_oi = daily_partial("oi_adj")
    d_pc_ratio, sk_pc_ratio = daily_partial("ratio")
    d_pc_fr_level, sk_pc_fr_level = daily_partial("fr")
    # 滞后一天(T-203 lane 规则):两项的输入整体挪到 d-1,口径不变
    d_funding_lag1, sk_funding_lag1 = daily_ic("fr_lag1")
    d_ratio_lag1, sk_ratio_lag1 = daily_ic("ratio_lag1")
    d_oi_lag1, sk_oi_lag1 = daily_ic("oi_adj_lag1")

    s_funding = monthly_stats(d_funding, "funding 项 fr_adj")
    s_oi = monthly_stats(d_oi, "OI/市值项 oi_adj")
    s_ratio = monthly_stats(d_ratio, "诊断:OI/市值比值 r")
    s_fr_level = monthly_stats(d_fr_level, "诊断:funding 水平 fr")
    p_oi = monthly_stats(d_pc_oi, "OI 项偏相关(控分数)")
    p_ratio = monthly_stats(d_pc_ratio, "诊断:OI/市值比值偏相关(控分数)")
    p_fr_level = monthly_stats(d_pc_fr_level, "诊断:funding 水平偏相关(控分数)")
    s_funding_lag1 = monthly_stats(d_funding_lag1, "funding 项 fr_adj(滞后一天)")
    s_ratio_lag1 = monthly_stats(d_ratio_lag1, "诊断:OI/市值比值 r(滞后一天)")
    s_oi_lag1 = monthly_stats(d_oi_lag1, "OI/市值项 oi_adj(滞后一天)")
    s_funding["verdict"] = verdict_funding(s_funding)
    s_oi["verdict"] = verdict_oi(s_oi, p_oi)

    # ── 自检 1:raw_score = base 权重 × 五支柱 ──────────────────────────────
    raw_ok = raw_bad = 0
    bad_samples: list = []
    for d in all_days:
        for row in panel[d]:
            bw = BASE_WEIGHTS.get(row.get("asset_class"))
            r2 = rb_by_key.get((row["symbol"], d))
            if not bw or not r2:
                continue
            calc = (bw["F"] * r2["pillar_f"] + bw["M"] * r2["pillar_m"] + bw["O"] * r2["pillar_o"]
                    + bw["S"] * r2["pillar_s"] + bw["A"] * r2["pillar_a"])
            if abs(round(calc, 1) - float(r2["raw_score"])) <= 0.11:
                raw_ok += 1
            else:
                raw_bad += 1
                if len(bad_samples) < 5:
                    bad_samples.append({"symbol": row["symbol"], "d": d, "calc": round(calc, 3),
                                        "stored": r2["raw_score"]})

    # ── OI/市值比的原始分布(诊断,解释「项无分辨力」)────────────────────────
    ratios_all = sorted(r["ratio"] for rows in panel.values() for r in rows if r.get("ratio") is not None)
    oi_adj_vals: dict = defaultdict(int)
    for rows in panel.values():
        for r in rows:
            if r.get("oi_adj") is not None:
                oi_adj_vals[r["oi_adj"]] += 1
    dist = {
        "n_obs": len(ratios_all),
        "min": round(ratios_all[0], 6) if ratios_all else None,
        "p01": round(ratios_all[int(0.01 * len(ratios_all))], 6) if ratios_all else None,
        "median": round(ratios_all[len(ratios_all) // 2], 6) if ratios_all else None,
        "p95": round(ratios_all[int(0.95 * len(ratios_all))], 6) if ratios_all else None,
        "p99": round(ratios_all[int(0.99 * len(ratios_all))], 6) if ratios_all else None,
        "max": round(ratios_all[-1], 6) if ratios_all else None,
        "pct_above_0.2": round(100.0 * sum(1 for x in ratios_all if x > 0.2) / len(ratios_all), 6) if ratios_all else None,
        "pct_above_0.5": round(100.0 * sum(1 for x in ratios_all if x > 0.5) / len(ratios_all), 6) if ratios_all else None,
        "pct_above_1": round(100.0 * sum(1 for x in ratios_all if x > 1.0) / len(ratios_all), 6) if ratios_all else None,
        "oi_adj_value_counts": {str(k): v for k, v in sorted(oi_adj_vals.items())},
    }

    out = {
        "task": "T-203",
        "ledger": "S-688",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "panel_source": "cis_standard_outcomes 的 crypto 行(σ≠BTC)的复刻 —— 表本身对 publishable key 不可读(42501),"
                            "按 src/data/cis/standard_outcomes.py 的写入代码复刻同一批 (symbol,d) 与同一个 alpha",
            "alpha_reconstruction": "alpha = round(a_ret − b_ret, 6);a_ret = 收盘(d+30)/收盘(d) − 1,b_ret 同式用 BTC;"
                                    "收盘 = asset_mcap_daily 的原始 CG 日收盘(source=coingecko_pro_market_chart),迁移币按 S-537 接段;"
                                    "四舍五入到 6 位与落表一致(表里存的就是这个值)",
            "points_source": "已发布 cis_official_daily 优先;之前的日子用 cis_rebuild_daily(code_ref=cis-standard-v1.3,d ≤ 最近发布日)",
            "min_names_per_day": MIN_NAMES,
            "split": SPLIT,
            "horizon_days": HORIZON,
            "t_formula": "t = 月均 ρ / 月标准差(ddof=1) × √月数",
            "monthly_sd_ddof": 1,
            "term_formulas": "fr_adj / oi_adj 一字照抄 cis_provider.calculate_cis_score v4.3(第 1544–1563 行),手抄不 import",
        },
        "data": {
            "panel_days": len(all_days),
            "panel_rows": sum(len(v) for v in panel.values()),
            "panel_range": [all_days[0], all_days[-1]] if all_days else None,
            "panel_symbols": sorted({r["symbol"] for rows in panel.values() for r in rows}),
            "points_with_signal": n_pt,
            "rows_without_alpha": n_no_alpha,
            "official_cap": cap,
            "rebuild_computed_at": sorted({r["computed_at"] for r in rb})[-1] if rb else None,
            "rebuild_rows": len(rb),
            "chain_info": chain_info,
        },
        "validation": {
            "raw_score_formula_rows_ok": raw_ok,
            "raw_score_formula_rows_bad": raw_bad,
            "raw_score_formula_bad_samples": bad_samples,
            "edge_map_cells_compared": len(edge_detail),
            "edge_map_cells_n_match": n_match,
            "edge_map_max_abs_diff_pct_pts": round(max_diff, 4),
            "edge_map_total_rows_lib": edge_lib_total,
            "edge_map_total_rows_mine": edge_mine_total,
            "edge_map_total_rows_match": edge_lib_total == edge_mine_total,
            "edge_map_detail": edge_detail,
            "vintage_checks": vintage_checks,
            "vintage_used": label,
            "vintage_matches_table": ok,
            "oi_mcap_ratio_distribution": dist,
            "skipped_days": {"funding_term": sk_funding, "oi_term": sk_oi, "ratio_diag": sk_ratio,
                             "fr_level_diag": sk_fr_level, "oi_partial": sk_pc_oi, "ratio_partial_diag": sk_pc_ratio,
                             "funding_term_lag1": sk_funding_lag1, "oi_term_lag1": sk_oi_lag1,
                             "ratio_diag_lag1": sk_ratio_lag1},
        },
        "funding_term": s_funding,
        "oi_term": s_oi,
        "oi_term_partial": p_oi,
        "lag1_robustness": {
            "note": "T-203 lane 规则:信号日当天的派生量(当日 funding / 当日 OI÷当日市值),"
                    "判完必须再挪一天判一次 —— 只在当天成立的不算(S-665 / T-178)。"
                    "此处把两项的输入整体挪到 d-1,口径与主口径完全相同,主口径数字不动。",
            "funding_term_lag1": s_funding_lag1,
            "oi_term_lag1": s_oi_lag1,
            "oi_mcap_ratio_ic_lag1": s_ratio_lag1,
        },
        "diagnostics": {
            "funding_level_ic": s_fr_level,
            "funding_level_partial_corr": p_fr_level,
            "oi_mcap_ratio_ic": s_ratio,
            "oi_mcap_ratio_partial_corr": p_ratio,
        },
    }
    with open(a.out, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("[3/6] wrote %s" % a.out, flush=True)

    print("\n=== 结果 ===")
    for lbl, s in (("① funding 项", s_funding), ("② OI/市值项", s_oi),
                   ("  诊断 funding 水平", s_fr_level), ("  诊断 OI/市值比值", s_ratio)):
        print("  %-22s 月数=%s 月均 ρ=%s 月 t=%s | 上半 %s(%s 月) 下半 %s(%s 月)"
              % (lbl, s["n_months"], s["mean_rho"], s["t"],
                 s["half1"]["mean_rho"], s["half1"]["n_months"], s["half2"]["mean_rho"], s["half2"]["n_months"]))
    print("  %-22s 月数=%s 月均 ρ=%s 月 t=%s" % ("  OI 项偏相关", p_oi["n_months"], p_oi["mean_rho"], p_oi["t"]))
    print("  %-22s 月数=%s 月均 ρ=%s 月 t=%s" % ("  OI 比值偏相关(诊断)", p_ratio["n_months"], p_ratio["mean_rho"], p_ratio["t"]))
    print("  判定 ①: %s" % s_funding["verdict"])
    print("  判定 ②: %s" % s_oi["verdict"])
    print("  [滞后一天] funding 项  月均 ρ=%s 月 t=%s | 上半 %s 下半 %s"
          % (s_funding_lag1["mean_rho"], s_funding_lag1["t"],
             s_funding_lag1["half1"]["mean_rho"], s_funding_lag1["half2"]["mean_rho"]))
    print("  [滞后一天] OI/市值项   月均 ρ=%s 月 t=%s"
          % (s_oi_lag1["mean_rho"], s_oi_lag1["t"]))
    print("  [滞后一天] OI/市值比值 月均 ρ=%s 月 t=%s"
          % (s_ratio_lag1["mean_rho"], s_ratio_lag1["t"]))
    print("  自检: raw_score 公式 %d 行通过 / %d 行不符;edge map %d/%d 格行数一致,平均超额最大差 %.4f pp;总行数 库 %d / 我 %d(%s)"
          % (raw_ok, raw_bad, n_match, len(edge_detail), max_diff,
             edge_lib_total, edge_mine_total, "对上" if edge_lib_total == edge_mine_total else "对不上"))


if __name__ == "__main__":
    main()
