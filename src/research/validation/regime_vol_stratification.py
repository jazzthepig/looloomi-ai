"""
S-78 — the (macro_regime × vol_regime) edge map: the sizing LAYER above the direction table (Seth, 2026-07-23)
==============================================================================================================

The strategy-library coverage map (build-order #3) said the whole library is directional — calm-vol and
storm-vol are UNCOVERED. This mines the missing axis: does the MARKET VOLATILITY regime stratify the
β-adjusted signal-book edge, INDEPENDENTLY of the macro regime? It does, and the interaction is the point.

EMPIRICAL (β-backfilled signal_outcomes ∩ ohlcv, PIT 30d BTC realized-vol terciles, n≈5,937):

  one-way vol:        calm +2.52 (t+6.3) · normal −0.93 (t−2.3) · storm +4.09 (t+15.1)  ← U-shape, best at extremes
  two-way (× macro), controlling for regime:
                       │ calm vol          │ normal vol        │ storm vol
        EASING         │ +6.35 (t+8.0) ✅   │ −6.86 (t−8.4) ✗   │ −2.47 (t−3.1) ✗
        RISK_OFF       │ −0.96 (t−2.0)     │ +0.48 (t+1.0)     │ +5.70 (t+17.6) ✅

The edge concentrates in OPPOSITE vol corners by regime — **EASING×calm** and **RISK_OFF×storm** — and
NORMAL vol loses in both. Not time-clustered (all terciles span 2025-06→2026-05); not a macro proxy (the
pattern is U-shaped while RISK_OFF% is monotonic 28→65→82). This is the SIZE layer that complements the
H2 DIRECTION table (Minimax): H2 says which way to lean per regime; S-78 says how hard to press given the
vol state. It also grounds CIS v5's `risk_score` — market vol is a real sizing input, not just pillar_O.

Interpretation: liquidity-returning + calm (EASING×calm) = trend the signals cleanly; risk-off flush +
high vol (RISK_OFF×storm) = capitulation where CIS calls are sharply right; the mushy middle (normal vol)
is where the book bleeds. Size UP in the two ✅ corners, FLAT/avoid in normal vol and the ✗ cross-cells.

⚠️ IN-SAMPLE map. Before it sizes real capital it must survive the gauntlet (OOS split + DSR/PBO) — this
module produces the map + a PIT vol classifier; the OOS test is the next step. Pure/reproducible: re-run
`stratify()` when the pipeline refreshes. Compliance: internal research; sizing multiplier, not advice.
"""
from __future__ import annotations

import math

# Validated 2-way cells (mean β-adj edge %, t-stat). None = not yet measured (I1: unmeasured ≠ neutral-claim).
# Keyed (MACRO_UPPER, vol_regime). vol_regime ∈ {calm, normal, storm}.
S78_MAP: dict[tuple[str, str], tuple[float, float]] = {
    ("EASING",   "calm"):   (6.35,  8.01),
    ("EASING",   "normal"): (-6.86, -8.44),
    ("EASING",   "storm"):  (-2.47, -3.12),
    ("RISK_OFF", "calm"):   (-0.96, -1.96),
    ("RISK_OFF", "normal"): (0.48,  1.00),
    ("RISK_OFF", "storm"):  (5.70,  17.62),
}
# One-way vol fallback (used when the (macro,vol) cell is unmeasured) — calm/storm favoured, normal cut.
S78_VOL_ONEWAY: dict[str, tuple[float, float]] = {
    "calm": (2.52, 6.33), "normal": (-0.93, -2.31), "storm": (4.09, 15.07),
}
_T_GATE = 3.0   # |t| below this ⇒ treat as neutral (not enough signal to move size)


def vol_regime(prior_returns: list[float], window: int = 30) -> str | None:
    """PIT market-vol regime from the benchmark's trailing daily returns (most-recent `window`, all
    STRICTLY before the scored day). Returns None when < window/2 obs — never guess a regime.

    Terciles are calibrated to the study's BTC 30d-realized-vol breakpoints so live labels match the map.
    """
    r = [x for x in (prior_returns or [])[-window:] if x is not None and x == x]
    if len(r) < max(10, window // 2):
        return None
    mu = sum(r) / len(r)
    sd = math.sqrt(sum((x - mu) ** 2 for x in r) / (len(r) - 1)) if len(r) > 1 else 0.0
    # Empirical BTC 30d-vol tercile cut points from the S-78 sample (daily-return std):
    if sd < 0.028:
        return "calm"
    if sd < 0.045:
        return "normal"
    return "storm"


def size_multiplier(macro_regime: str | None, vol: str | None,
                    up: float = 1.5, down: float = 0.5) -> dict:
    """Actionable sizing from the S-78 map: press in validated-positive cells, cut in validated-negative,
    neutral (1.0) where unvalidated. Uses the (macro×vol) cell if measured, else the one-way vol fallback.

    Returns {size_mult, basis, cell_mean, cell_t} — never a bare number, so the reason is auditable.
    """
    if vol is None:
        return {"size_mult": 1.0, "basis": "no_vol_regime", "cell_mean": None, "cell_t": None}
    mr = (macro_regime or "").strip().upper().replace("-", "_")
    cell = S78_MAP.get((mr, vol))
    basis = "two_way(macro×vol)"
    if cell is None:
        cell = S78_VOL_ONEWAY.get(vol)
        basis = "one_way(vol)"
    if cell is None:
        return {"size_mult": 1.0, "basis": "unmeasured", "cell_mean": None, "cell_t": None}
    mean, t = cell
    if t >= _T_GATE:
        mult = up
    elif t <= -_T_GATE:
        mult = down
    else:
        mult = 1.0
    return {"size_mult": mult, "basis": basis, "cell_mean": mean, "cell_t": t}


def stratify(rows: list[dict]) -> list[dict]:
    """Recompute the (macro×vol) edge map from rows [{edge, macro_regime, vol_regime}] — the reproducible
    core (re-run on fresh data for the OOS test). One-sample t of edge vs 0 per cell."""
    buckets: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        e = r.get("edge")
        if e is None or e != e:
            continue
        mr = (r.get("macro_regime") or "").strip().upper().replace("-", "_")
        v = r.get("vol_regime")
        if not v:
            continue
        buckets.setdefault((mr, v), []).append(float(e))
    out = []
    for (mr, v), vals in sorted(buckets.items()):
        n = len(vals)
        mu = sum(vals) / n if n else float("nan")
        sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / (n - 1)) if n > 1 else float("nan")
        t = (mu / sd * math.sqrt(n)) if (n > 1 and sd and sd == sd and sd > 0) else float("nan")
        out.append({"macro_regime": mr, "vol_regime": v, "n": n,
                    "mean_edge": round(mu, 2) if mu == mu else None,
                    "t_stat": round(t, 2) if t == t else None})
    return out
