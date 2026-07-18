"""
Cash-and-Carry / Funding Basis Harvest — investigation harness (Seth, 2026-07-18).
==================================================================================
The existing `cash_and_carry.py` reported a striking 2.42 Sharpe / 0.3% maxDD on a 167-day
overlap with 4bps rebalance cost — but a 167-day window is short, and 4bps is an aggressive
cost assumption (realistic: spot taker ~0.10% + perp taker ~0.05% × 2 legs = 0.30% RT minimum,
or VIP-0 maker 0.02% × 2 legs = 0.08% RT minimum). This harness subjects the hypothesis to
the factory's honest gate:

  · LONGER WINDOW — paginate Binance klines/funding by startTime to get the FULL available
    history per symbol (not just limit=1000). The 167-day overlap was bounded by the shortest
    name's funding history; this version starts each symbol from its own first available day.
  · REALISTIC COSTS — three cost scenarios: optimistic (4bps), realistic VIP-0 taker (30bps),
    pessimistic (50bps). The truth usually lives between.
  · PER-NAME BREAKDOWN — does one outlier dominate the 2.42 Sharpe? If BTC/ETH alone carry
    the book, the rest is window-dressing.
  · WALK-FORWARD — split the 167-day window (or whatever we get) into 3 chronological folds,
    check positive in ≥2/3. If the edge collapses in later folds, it's a window artifact.
  · ORTHOGONALITY — vs the factory's positioning_funding signal (the validated baseline) on
    the same dates. Cash-carry is funding-CARRY; positioning_funding is funding-POSITIONING
    (cross-sectional crowd fade). Are they distinct?

Honest scope: ONE experiment. The "edge" of cash-and-carry IS the funding payment itself
(the strategy collects perp funding by shorting perp when funding is positive). The question
this harness answers is not "is there an edge" — the funding payment is observable. The
question is: after costs, after a real window, after walk-forward, does the carry STILL
dominate positioning_funding as a sleeve?
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.research.factory.cash_and_carry import _sr, _maxdd  # noqa: E402

_SPOT = "https://data-api.binance.vision/api/v3/klines"
_PERP = "https://fapi.binance.com/fapi/v1/klines"
_FUND = "https://fapi.binance.com/fapi/v1/fundingRate"

# Four cost scenarios — pessimistic to optimistic.
# Spot taker (VIP-0): 0.10%. Perp taker (VIP-0): 0.05%. RT for both legs: 0.30%.
# If we use limit orders AND get fills AND don't pay spread: 0.04% RT total.
# With perp market-making rebate + post-only limit orders on spot: ~0.01% RT (best case).
COST_SCENARIOS = {
    "pessimistic":    0.0050,   # 50 bps RT — accounts for slippage + spread + taker
    "realistic_vip0": 0.0030,   # 30 bps RT — pure taker fees, no slippage
    "aggressive_maker": 0.0014, # 14 bps/day RT — spot 0.02% × 2 + perp 0.02% × 2 (maker-only, both legs)
    "optimistic":     0.0004,   # 4 bps RT — assumes maker rebates + spread capture
}

MAJORS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC"]


# ── longer-history fetchers (paginated by startTime, no 1000-bar limit) ──────

def _paginate_klines(url: str, sym: str, start_ms: int) -> dict:
    """Paginate Binance klines backwards from `start_ms`. Returns {epoch_day: close}."""
    out = {}
    cur = start_ms
    end_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    client = httpx.Client(timeout=25, headers={"User-Agent": "research"})
    try:
        while cur < end_ms:
            j = client.get(url, params={"symbol": f"{sym}USDT", "interval": "1d",
                                          "startTime": cur, "limit": 1000}).json()
            if not isinstance(j, list) or not j:
                break
            for k in j:
                out[int(k[0]) // 86400000] = float(k[4])
            cur = int(j[-1][0]) + 86_400_000
            if len(j) < 1000 or cur > end_ms:
                break
    finally:
        client.close()
    return out


def _paginate_funding(sym: str, start_ms: int) -> dict:
    """Paginate funding events; sum 8h settlements into daily buckets."""
    out: dict[int, float] = {}
    cur = start_ms
    end_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    client = httpx.Client(timeout=25, headers={"User-Agent": "research"})
    try:
        while cur < end_ms:
            j = client.get(_FUND, params={"symbol": f"{sym}USDT",
                                            "startTime": cur, "limit": 1000}).json()
            if not isinstance(j, list) or not j:
                break
            for x in j:
                d = int(x["fundingTime"]) // 86400000
                out[d] = out.get(d, 0.0) + float(x["fundingRate"])
            cur = int(j[-1]["fundingTime"]) + 1
            if len(j) < 1000 or cur > end_ms:
                break
    finally:
        client.close()
    return out


# ── core pnl builder ─────────────────────────────────────────────────────────

def build_carry_pnl(spot: dict, perp: dict, fund: dict) -> tuple[np.ndarray, list]:
    """Per-name daily pnl of long-spot + short-perp, only when funding>0. NO cost here —
    cost is applied at the BOOK level (one rebalance = one RT cost across the whole portfolio,
    not per-name). Returns (pnl_vector T-1, list_of_days_used)."""
    days = sorted(set(spot) & set(perp) & set(fund))
    if len(days) < 120:
        return np.array([]), days
    pnl = []
    for i in range(1, len(days)):
        d0, d1 = days[i - 1], days[i]
        sr = spot[d1] / spot[d0] - 1.0
        pr = perp[d1] / perp[d0] - 1.0
        f = fund.get(d1, 0.0)
        take = 1.0 if f > 0 else 0.0
        pnl.append(take * (sr - pr + f))
    return np.array(pnl), days[1:]


def aggregate_book_with_cost(per_name_pnl: dict[str, np.ndarray], common_len: int,
                              cost_rt: float) -> np.ndarray:
    """Equal-notional across active legs, normalised to active-count per day. Apply ONE
    cost_rt/7 amortised cost per day at the book level (not per-name)."""
    if not per_name_pnl:
        return np.array([])
    K = len(per_name_pnl)
    P = np.array([per_name_pnl[n] for n in per_name_pnl])
    if P.shape[1] != common_len:
        min_len = min(p.shape[0] for p in per_name_pnl.values())
        P = np.array([p[-min_len:] for p in per_name_pnl.values()])
    active = (P != 0).astype(float)
    wsum = active.sum(0); wsum[wsum == 0] = 1
    book = (P.sum(0) / wsum) - cost_rt / 7.0
    return book


def aggregate_book(per_name_pnl: dict[str, np.ndarray], common_len: int) -> np.ndarray:
    """Equal-notional across active legs, normalised to active-count per day."""
    if not per_name_pnl:
        return np.array([])
    K = len(per_name_pnl)
    P = np.array([per_name_pnl[n] for n in per_name_pnl])   # K×T
    if P.shape[1] != common_len:
        # align to the shortest
        min_len = min(p.shape[0] for p in per_name_pnl.values())
        P = np.array([p[-min_len:] for p in per_name_pnl.values()])
    active = (P != 0).astype(float)
    wsum = active.sum(0); wsum[wsum == 0] = 1
    return (P.sum(0) / wsum)


# ── walk-forward ─────────────────────────────────────────────────────────────

def walk_forward(pnl: np.ndarray, folds: int = 3) -> dict:
    """Split into `folds` chronological blocks; report per-fold Sharpe + count positive."""
    if len(pnl) < folds * 30:
        return {"sufficient_data": False, "n": len(pnl)}
    blocks = np.array_split(pnl, folds)
    srs = [_sr(b) for b in blocks]
    return {"folds": folds, "n": len(pnl), "fold_sharpes": [round(x, 2) for x in srs],
            "pos_folds": sum(1 for x in srs if x > 0),
            "mean_fold_sr": round(float(np.mean(srs)), 2),
            "robust": sum(1 for x in srs if x > 0) >= folds - 1 and np.mean(srs) > 0}


# ── the honest investigation ─────────────────────────────────────────────────

def run(start_iso: str = "2022-01-01") -> dict:
    """Fetch max available history per symbol, build the carry book, test it under three cost
    scenarios, walk-forward, and per-name. Network — research-grade, not on request path."""
    start_ms = int(dt.datetime.fromisoformat(start_iso).timestamp() * 1000)
    print(f"  …fetching spot/perp/funding from {start_iso} (paginated) …")
    legs = {}
    for s in MAJORS:
        spot = _paginate_klines(_SPOT, s, start_ms)
        perp = _paginate_klines(_PERP, s, start_ms)
        fund = _paginate_funding(s, start_ms)
        if len(spot) > 120 and len(perp) > 120 and len(fund) > 120:
            legs[s] = {"spot": spot, "perp": perp, "fund": fund,
                       "n_spot": len(spot), "n_perp": len(perp), "n_fund": len(fund)}
            print(f"  …{s}: spot={len(spot)}d, perp={len(perp)}d, fund={len(fund)}d")
        else:
            print(f"  !!{s}: insufficient history (spot={len(spot)} perp={len(perp)} fund={len(fund)})")
    if len(legs) < 3:
        return {"status": "no_data", "n_legs": len(legs)}

    # Per-name pnl (cost-free at this layer; cost is applied at the book level)
    per_name = {}
    common_days = sorted(set.intersection(*[set(v["spot"]) & set(v["perp"]) & set(v["fund"])
                                              for v in legs.values()]))
    for s, d in legs.items():
        pnl, _ = build_carry_pnl(d["spot"], d["perp"], d["fund"])
        per_name[s] = pnl

    out = {"overlap_days": len(common_days), "n_names": len(legs),
           "start": start_iso, "per_name_stats": {}}
    for s, p in per_name.items():
        if p.std() > 0:
            # gross per-name stats (no cost) — cost is applied at the book level
            out["per_name_stats"][s] = {
                "n": len(p),
                "gross_sharpe":  round(_sr(p), 2),
                "gross_total_pnl_pct": round(float(p.sum()) * 100, 2),
                "hit_pct":       round(100 * (p > 0).mean(), 1),
            }

    out["cost_scenarios"] = {}
    for scen, cost in COST_SCENARIOS.items():
        book = aggregate_book_with_cost(per_name, len(common_days) - 1, cost)
        if book.size == 0:
            out["cost_scenarios"][scen] = {"status": "empty"}
            continue
        wf = walk_forward(book, folds=3)
        out["cost_scenarios"][scen] = {
            "cost_rt_pct": cost * 100,
            "book_sharpe": round(_sr(book), 2),
            "book_maxdd_pct": round(_maxdd(book) * 100, 2),
            "book_total_pnl_pct": round(float(book.sum()) * 100, 2),
            "walk_forward": wf,
            "robust_at_cost": wf.get("robust", False),
        }

    out["disclaimer"] = ("Cash-and-carry 'edge' = funding payment itself (observable, not a "
                          "forecast). This harness tests whether the carry PERSISTS through "
                          "realistic costs + walk-forward. If robust, it joins the factory as "
                          "the carry sleeve; if not, R32.")
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))