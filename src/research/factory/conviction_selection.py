"""
Conviction Beta-Plus Selection (Seth 2026-07-15) — the scalable, differentiated edge.
======================================================================================

Jazz: the scalable competitive edge is judgment-led SELECTION of structural winners held
directionally (the HYPE playbook), not capacity-capped arb. Most crypto quants trade price; we
trade STRUCTURAL VALUE BECOMING CASHFLOW, ACCELERATING. The measurable core of CONVICTION_
METHODOLOGY: fundamental momentum (revenue/fee ACCELERATION) → re-rating; confirm with trend.

Test (the honest science): does REVENUE MOMENTUM predict forward price returns on liquid,
revenue-generating tokens? IC(revenue-acceleration, fwd 30d return) + a long-top-quartile book
vs equal-weight and BTC. If yes, that's scalable directional alpha (hold large-cap winners); if
no, it's refuted. Real data: DeFiLlama daily revenue + Binance price. Pure numpy.
"""
from __future__ import annotations

import json
import urllib.request

import numpy as np

# token → (defillama fee/revenue slug, binance symbol). Liquid, revenue-generating.
UNIVERSE = {
    "AAVE": ("aave", "AAVE"), "UNI": ("uniswap", "UNI"), "LDO": ("lido", "LDO"),
    "MKR": ("makerdao", "MKR"), "CRV": ("curve-dex", "CRV"), "GMX": ("gmx", "GMX"),
    "PENDLE": ("pendle", "PENDLE"), "HYPE": ("hyperliquid", "HYPE"), "JUP": ("jupiter", "JUP"),
    "RAY": ("raydium", "RAY"), "ENA": ("ethena", "ENA"), "AERO": ("aerodrome-v1", "AERO"),
    "CAKE": ("pancakeswap", "CAKE"), "DYDX": ("dydx", "DYDX"),
}
_LLAMA = "https://api.llama.fi/summary/fees/{}?dataType=dailyRevenue"
_PERP = "https://fapi.binance.com/fapi/v1/klines"


def _rev(slug):
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(_LLAMA.format(slug), headers={"User-Agent": "cc"}), timeout=15).read())
        ch = d.get("totalDataChart") or []
        return {int(t) // 86400: float(v) for t, v in ch}       # day-index → daily revenue USD
    except Exception:
        return {}


def _px(sym):
    try:
        u = f"{_PERP}?symbol={sym}USDT&interval=1d&limit=700"
        r = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "cc"}), timeout=15).read())
        return {int(k[0]) // 86400000: float(k[4]) for k in r} if isinstance(r, list) else {}
    except Exception:
        return {}


def _spearman(x, y):
    def rank(v):
        o = np.argsort(v); r = np.empty_like(o, float); r[o] = np.arange(len(v)); return r
    x, y = rank(np.array(x)), rank(np.array(y))
    return float(np.corrcoef(x, y)[0, 1]) if len(x) > 3 else float("nan")


def run(horizon=30) -> dict:
    rev, px = {}, {}
    for tok, (slug, sym) in UNIVERSE.items():
        r, p = _rev(slug), _px(sym)
        if len(r) > 150 and len(p) > 150:
            rev[tok], px[tok] = r, p
    if len(rev) < 5:
        return {"status": "insufficient", "n": len(rev)}
    toks = list(rev)
    days = sorted(set.intersection(*[set(px[t]) for t in toks]))
    if len(days) < 150:
        return {"status": "short_overlap", "days": len(days)}

    # signal: revenue momentum = 30d revenue sum vs prior 30d (fundamental acceleration)
    def rev30(t, d):
        return sum(rev[t].get(dd, 0) for dd in range(d - 30, d))
    ics, panel = [], []
    for i in range(60, len(days) - horizon, 10):
        d = days[i]
        sig, fwd = [], []
        for t in toks:
            r0, r1 = rev30(t, d - 30), rev30(t, d)
            if r0 <= 0:
                continue
            mom = r1 / r0 - 1.0                              # revenue acceleration
            p_now, p_fut = px[t].get(days[i]), px[t].get(days[min(i + horizon, len(days) - 1)])
            if not (p_now and p_fut):
                continue
            sig.append(mom); fwd.append(p_fut / p_now - 1.0)
        if len(sig) >= 5:
            ics.append(_spearman(sig, fwd))
            # long top-half vs bottom-half fwd return (the selection payoff)
            order = np.argsort(sig); k = len(sig) // 2
            top = np.mean([fwd[j] for j in order[-k:]]); bot = np.mean([fwd[j] for j in order[:k]])
            panel.append((top, bot, np.mean(fwd)))
    if not panel:
        return {"status": "no_signal_windows"}
    ic = float(np.nanmean(ics))
    top = np.array([p[0] for p in panel]); bot = np.array([p[1] for p in panel]); ew = np.array([p[2] for p in panel])
    return {"tokens": toks, "overlap_days": len(days), "horizon_d": horizon, "n_windows": len(panel),
            "revenue_momentum_IC": round(ic, 3),
            "long_top_avg_fwd_pct": round(float(top.mean()) * 100, 1),
            "long_bottom_avg_fwd_pct": round(float(bot.mean()) * 100, 1),
            "equalweight_avg_fwd_pct": round(float(ew.mean()) * 100, 1),
            "top_minus_bottom_pct": round(float((top - bot).mean()) * 100, 1),
            "selection_hit_rate_pct": round(float((top > bot).mean()) * 100, 0)}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
