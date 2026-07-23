"""
S/O ↔ price lead-lag — does price LEAD the S and O pillars? (Seth, 2026-07-22)
==============================================================================

Validates the load-bearing premise of build-order #5 (`docs/VECTOR_SCHEMA_SPEC.md` §4.5) BEFORE
building any "related-instrument price-action nowcast" infrastructure. The premise: R63b's stability
premium (edge best when ΔS/ΔO stable) was read as "we sample S/O AFTER the market reprices" ⇒ if
price *leads* S/O, a fast price proxy could nowcast S/O between the slow CIS samples.

EMPIRICAL VERDICT (daily, 58 assets ∩ ohlcv, 2025-05→2026-06, n≈8,280) — **REFUTED at daily
resolution.** Price does not LEAD S/O; it is CONTEMPORANEOUS with them:

    corr(own_ret[t], Δpillar over [t-1,t])   — CONTEMPORANEOUS (same bar):
        M +0.82  ·  A +0.57  ·  O +0.52  ·  S +0.44  ·  F -0.01
    corr(own_ret[t], Δpillar over [t,t+1])   — LEAD +1 (the test):
        ΔO +0.013 (t=1.1)   ΔS -0.010 (t=-0.9)      ← ZERO predictive lead
    lead +2 / +3: small NEGATIVE (ΔS lead+2 t=-6.9) — a weak mean-reversion, wrong sign for a nowcast.

So O and S sit near the price-DERIVED end of the pillar spectrum (only F is price-independent). They
reprice WITH price on the same daily bar; today's return carries no information about tomorrow's S/O
move. ⇒ a daily price-based S/O nowcast adds nothing — do NOT build it. The stability premium is
better read as a REGIME/RISK signal (large ΔS/ΔO = large contemporaneous price moves = high-vol tape
where edge degrades), consistent with using S as a risk gate, NOT a sampling-latency problem.

RESIDUAL: the only place a lead could exist is SUB-DAILY (intraday price → end-of-day S/O snapshot).
That needs hourly pillar + hourly price — geo-blocked on Railway (Binance) and ohlcv is daily — and
even then the expected payoff is marginal because S/O are ~contemporaneous price transforms. This
module runs at any resolution: hand it hourly (ret, pillar) series when that data exists and re-read
the LEAD row. Companion to Minimax's R75 (hourly S/O Δ-quintile edge): if S/O Δ is ~half price-
mechanical, R75's hourly factor must clear an absorption test vs contemporaneous price/momentum or
it is momentum in a costume (the R24 Crowd-Clock trap).

Compliance: internal research. PIT-safe by construction (lead uses only future pillar vs present;
correlations are descriptive, not a traded signal).
"""
from __future__ import annotations

import math


def _corr_t(xs: list[float], ys: list[float]) -> tuple[float, float, int]:
    """Pearson corr + one-sample t (H0: ρ=0) over paired finite observations."""
    pairs = [(x, y) for x, y in zip(xs, ys)
             if x is not None and y is not None and x == x and y == y]
    n = len(pairs)
    if n < 3:
        return (float("nan"), float("nan"), n)
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    sxx = sum((p[0] - mx) ** 2 for p in pairs)
    syy = sum((p[1] - my) ** 2 for p in pairs)
    if sxx < 1e-12 or syy < 1e-12:
        return (float("nan"), float("nan"), n)
    r = sxy / math.sqrt(sxx * syy)
    r = max(-0.999999, min(0.999999, r))
    t = r * math.sqrt((n - 2) / (1 - r * r))
    return (r, t, n)


def returns(prices: list[float]) -> list[float]:
    """Simple returns; index [i] is the return over (i-1, i]. First element is None."""
    out = [None]
    for i in range(1, len(prices)):
        p0, p1 = prices[i - 1], prices[i]
        out.append((p1 / p0 - 1.0) if (p0 and p1 and p0 != 0) else None)
    return out


def pillar_deltas(series: list[float], lead: int = 0) -> list[float]:
    """Δpillar aligned to a return at index t.

    lead=0  → Δ over (t-1, t]  (contemporaneous with return[t]) = series[t]-series[t-1]
    lead=k  → Δ over (t+k-1, t+k] (k days ahead)                = series[t+k]-series[t+k-1]
    Only past/future pillar values are used relative to t — no look-ahead into the return itself.
    """
    n = len(series)
    out = [None] * n
    for t in range(n):
        a, b = t + lead - 1, t + lead
        if 0 <= a and b < n and series[a] is not None and series[b] is not None:
            out[t] = series[b] - series[a]
    return out


def lead_lag_profile(ret: list[float], pillar: list[float], max_lead: int = 3) -> dict:
    """Correlation of return[t] with Δpillar at leads 0..max_lead. lead 0 = contemporaneous.

    A price signal that LEADS the pillar shows a positive lead≥1 correlation (tomorrow's pillar
    catches up to today's price). A price-COINCIDENT pillar shows a big lead-0 and ~0 for lead≥1.
    """
    prof = {}
    for k in range(max_lead + 1):
        r, t, n = _corr_t(ret, pillar_deltas(pillar, lead=k))
        prof[k] = {"rho": None if r != r else round(r, 4),
                   "t": None if t != t else round(t, 2), "n": n}
    return prof


def pooled_profile(panel: list[tuple[list, list]], max_lead: int = 3) -> dict:
    """Pool many assets' (ret, pillar) series and compute one lead-lag profile.

    `panel` is a list of (ret_series, pillar_series) already aligned per asset. Deltas are computed
    within each asset (no cross-asset differencing) then pooled — the correct way to avoid a
    per-asset level offset contaminating the correlation.
    """
    pooled_ret: list[float] = []
    pooled: dict[int, list[float]] = {k: [] for k in range(max_lead + 1)}
    for ret, pillar in panel:
        for k in range(max_lead + 1):
            d = pillar_deltas(pillar, lead=k)
            if k == 0:
                pooled_ret.extend(ret)
            pooled[k].extend(d)
    prof = {}
    # pooled_ret is repeated per k; rebuild cleanly by re-pooling ret once and each delta once
    base_ret: list[float] = []
    base_delta: dict[int, list[float]] = {k: [] for k in range(max_lead + 1)}
    for ret, pillar in panel:
        base_ret.extend(ret)
        for k in range(max_lead + 1):
            base_delta[k].extend(pillar_deltas(pillar, lead=k))
    for k in range(max_lead + 1):
        r, t, n = _corr_t(base_ret, base_delta[k])
        prof[k] = {"rho": None if r != r else round(r, 4),
                   "t": None if t != t else round(t, 2), "n": n}
    return prof


def verdict(profile: dict) -> str:
    """LEADS / COINCIDENT / INDEPENDENT from a lead-lag profile (lead-1 t vs lead-0 |rho|)."""
    c = profile.get(0, {})
    l1 = profile.get(1, {})
    c_rho = abs(c.get("rho") or 0.0)
    l1_t = l1.get("t") or 0.0
    if l1_t > 2.0 and (l1.get("rho") or 0) > 0:
        return "LEADS — price predicts the next pillar move (nowcast justified)"
    if c_rho > 0.2:
        return "COINCIDENT — pillar reprices with price same-bar; no exploitable lead (nowcast adds nothing)"
    return "INDEPENDENT — pillar unrelated to price"
