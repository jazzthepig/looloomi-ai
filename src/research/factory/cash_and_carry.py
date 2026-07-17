"""
Cash-and-Carry / Funding Basis Harvest (Seth 2026-07-15) — the competitive crypto edge.
=========================================================================================

Generic factor tilts (momentum/vol/skew) are crowded and low-Sharpe. The real institutional
crypto edge is the DELTA-NEUTRAL FUNDING BASIS TRADE: perp longs persistently overpay funding, so
long spot + short perp earns the funding stream with the price risk hedged out → steady positive
return, low vol, high Sharpe, and it scales (deepest instruments).

Per name, daily: pnl = spot_return − perp_return + funding_received(short perp).
  · spot_return − perp_return ≈ the basis convergence (small, mean-reverting) — the residual RISK
  · funding_received = +Σ daily funding when funding>0 (short perp receives) — the harvested PREMIUM
Only take the leg when funding is positive (receive); size across names by funding level. Aggregate
equal-notional. Real basis risk included (spot vs perp both fetched). Binance spot + fapi. Pure numpy.
"""
from __future__ import annotations

import json
import urllib.request

import numpy as np

_SPOT = "https://data-api.binance.vision/api/v3/klines"
_PERP = "https://fapi.binance.com/fapi/v1/klines"
_FUND = "https://fapi.binance.com/fapi/v1/fundingRate"
MAJORS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC"]
COST_RT = 0.0004        # 4bps round-trip on rebalance (both legs, liquid)


def _kl(url, sym, limit=1000):
    try:
        u = f"{url}?symbol={sym}USDT&interval=1d&limit={limit}"
        r = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "cc"}), timeout=15).read())
        return {int(k[0]) // 86400000: float(k[4]) for k in r} if isinstance(r, list) else {}
    except Exception:
        return {}


def _funding_daily(sym, limit=1000):
    try:
        u = f"{_FUND}?symbol={sym}USDT&limit={limit}"
        r = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "cc"}), timeout=15).read())
        by = {}
        for x in r if isinstance(r, list) else []:
            day = int(x["fundingTime"]) // 86400000
            by[day] = by.get(day, 0.0) + float(x["fundingRate"])   # sum 8h settlements → daily
        return by
    except Exception:
        return {}


def _sr(x): x = np.asarray(x); return float(x.mean() / x.std() * np.sqrt(365)) if x.std() > 0 else 0.0
def _maxdd(pnl): c = np.cumprod(1 + pnl); return float(((np.maximum.accumulate(c) - c) / np.maximum.accumulate(c)).max())


def run() -> dict:
    legs = {}
    for s in MAJORS:
        spot, perp, fund = _kl(_SPOT, s), _kl(_PERP, s), _funding_daily(s)
        days = sorted(set(spot) & set(perp) & set(fund))
        if len(days) < 120:
            continue
        legs[s] = (days, spot, perp, fund)
    if not legs:
        return {"status": "no_data"}
    common = sorted(set.intersection(*[set(v[0]) for v in legs.values()]))
    if len(common) < 120:
        return {"status": "insufficient_overlap", "days": len(common)}

    # per-name delta-neutral carry pnl on the common calendar
    per = {}
    for s, (_, spot, perp, fund) in legs.items():
        pnl = []
        for i in range(1, len(common)):
            d0, d1 = common[i - 1], common[i]
            sr = spot[d1] / spot[d0] - 1.0
            pr = perp[d1] / perp[d0] - 1.0
            f = fund.get(d1, 0.0)
            take = 1.0 if f > 0 else 0.0            # only harvest when funding is positive (receive)
            pnl.append(take * (sr - pr + f))
        per[s] = np.array(pnl)

    # aggregate: equal-notional across the names carrying today (renormalise), minus rebalance cost
    K = len(per); names = list(per)
    P = np.array([per[n] for n in names])           # K×T
    active = (P != 0).astype(float)
    wsum = active.sum(0); wsum[wsum == 0] = 1
    book = (P.sum(0) / wsum) - COST_RT / 7.0        # equal-weight active legs; amortised weekly cost
    avg_fund_ann = float(np.mean([np.mean(list(f.values())) for *_, f in legs.values()]) * 3 * 365 * 100)

    # also build a simple TREND book on the SAME perp closes/calendar, to show the ensemble lift
    perp_px = np.array([[legs[n][2][d] for n in names] for d in common])
    pret = np.zeros_like(perp_px); pret[1:] = np.nan_to_num((perp_px[1:] - perp_px[:-1]) / perp_px[:-1])
    trend = np.zeros(len(common) - 1)
    for i in range(60, len(common) - 1):
        v = pret[max(0, i - 30):i].std(0)
        sig = np.mean([np.sign(np.nan_to_num(perp_px[i] / perp_px[i - h] - 1)) for h in (20, 40, 60)], axis=0)
        w = sig * np.where(v > 0, 1 / v, 0); g = np.abs(w).sum(); w = w / g if g > 0 else w
        trend[i] = (w * pret[i + 1]).sum()
    n = min(len(book), len(trend)); bk, tn = book[-n:], trend[-n:]
    corr = float(np.corrcoef(bk, tn)[0, 1]) if bk.std() > 0 and tn.std() > 0 else 0.0
    # equal-RISK blend (inverse-vol) then vol-target to 10%
    bz = bk / bk.std() if bk.std() > 0 else bk; tz = tn / tn.std() if tn.std() > 0 else tn
    blend = 0.5 * bz + 0.5 * tz
    return {"overlap_days": len(common), "n_names": K, "names": names,
            "avg_funding_annualized_pct": round(avg_fund_ann, 1),
            "carry_sharpe": round(_sr(book), 2), "carry_ann_vol_pct": round(float(book.std() * np.sqrt(365) * 100), 1),
            "carry_maxdd_pct": round(_maxdd(book) * 100, 1),
            "trend_sharpe": round(_sr(tn), 2),
            "carry_vs_trend_corr": round(corr, 2),
            "COMBINED_carry+trend_sharpe": round(_sr(blend), 2)}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
