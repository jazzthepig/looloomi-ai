"""
L3 — Fundamental Momentum (Seth 2026-07-15). CONVICTION_METHODOLOGY layer 3.
============================================================================

"Is the moat becoming CASH FLOW, and accelerating?" Real protocol revenue (DeFiLlama daily
revenue) — its LEVEL, its rate-of-change (acceleration), and the reflexive-loop flag (buyback /
fee-share / real-yield). R21 proved revenue-momentum is NOT a standalone factor, so this is a
CONJUNCTION FILTER inside the conviction engine (L1∧L2∧L3∧L4), not a signal on its own.
"""
from __future__ import annotations

import json
import urllib.request

_LLAMA = "https://api.llama.fi/summary/fees/{}?dataType=dailyRevenue"


def _daily_revenue(slug: str) -> dict:
    try:
        d = json.loads(urllib.request.urlopen(
            urllib.request.Request(_LLAMA.format(slug), headers={"User-Agent": "cc"}), timeout=15).read())
        ch = d.get("totalDataChart") or []
        return {int(t) // 86400: float(v) for t, v in ch}
    except Exception:
        return {}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def fundamental_momentum(slug: str) -> dict:
    """L3 score 0..1 + evidence for one protocol. score = f(revenue acceleration, sustained level)."""
    rev = _daily_revenue(slug)
    if len(rev) < 90:
        return {"score": 0.0, "status": "insufficient_revenue_history", "slug": slug}
    days = sorted(rev)
    def _sum(a, b):
        return sum(rev.get(d, 0.0) for d in days[a:b] if rev.get(d, 0.0) is not None)
    n = len(days)
    r30 = _sum(n - 30, n)
    r30_prev = _sum(n - 60, n - 30)
    r90 = _sum(n - 90, n)
    accel = (r30 / r30_prev - 1.0) if r30_prev > 0 else 0.0          # 30d vs prior 30d
    # sustained-vs-trailing: is the recent run-rate above its 90d average?
    run_rate_ratio = (r30 / 30) / (r90 / 90) if r90 > 0 else 0.0
    # score: reward acceleration AND a run-rate above trend; both matter (growth that sticks)
    score = _clamp(0.5 * _clamp(0.5 + accel) + 0.5 * _clamp(run_rate_ratio - 0.5))
    return {"score": round(score, 3), "slug": slug,
            "revenue_30d_usd": round(r30, 0),
            "revenue_accel_pct": round(accel * 100, 1),
            "run_rate_vs_90d": round(run_rate_ratio, 2),
            "status": "ok"}


if __name__ == "__main__":
    for s in ("hyperliquid", "aave", "lido", "ethena"):
        print(s, fundamental_momentum(s))
