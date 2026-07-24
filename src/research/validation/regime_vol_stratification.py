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

OOS VERDICT (train/OOS split 2026-02-01, PIT train-derived vol cuts) — the in-sample map was TOO GENEROUS:
  · **RISK_OFF × storm SURVIVES** — train +0.98 (t+1.91) AND oos +4.84 (t+14.1, n=1300), same sign both
    halves. The one cell that holds across time ⇒ the only one that sizes capital (`status=oos_confirmed`).
  · EASING × calm — real in train (+3.13, t+4.52) but **ZERO OOS obs** (the regime didn't recur post-02);
    cannot confirm ⇒ neutral, not tradeable yet.
  · RISK_OFF × normal, EASING × storm — consistently negative (the mushy middle). EASING × normal flips
    sign train↔oos (unstable). None ship.
So the honest result is ONE OOS-robust sizing cell, not two corners. Caveat: RISK_OFF×storm's OOS window is
risk-off-dominated, so its OOS strength may lean on one extended regime — event-count + DSR/PBO still owed
before it is a live sleeve. `size_multiplier()` presses ONLY `oos_confirmed`. Pure/reproducible: re-run
`stratify()` on fresh data. Compliance: internal research; a sizing multiplier, not advice.
"""
from __future__ import annotations

import math

# (macro, vol) cells with the OUT-OF-SAMPLE verdict. Train/OOS split at 2026-02-01 with PIT train-derived
# vol tercile cuts (no full-sample look-ahead). status drives sizing — only `oos_confirmed` presses capital.
#   oos_confirmed : same sign in train AND oos, oos strong                (the ONLY tradeable cell)
#   in_sample_only: real in train but ZERO oos obs (regime didn't recur)  → cannot confirm ⇒ neutral
#   unstable      : sign flips train↔oos                                  → neutral
#   negative      : consistently loses                                    → cut
# ⚠️ The full-sample 2-way map (which looked like TWO winning corners) did NOT survive: EASING×calm has no
# OOS sample, and only RISK_OFF×storm holds across time. Caveat: RISK_OFF×storm's OOS window (2026-02→05) is
# risk-off-dominated, so the OOS win may lean on one extended regime — event-count + DSR still owed.
S78_CELLS: dict[tuple[str, str], dict] = {
    ("EASING",   "calm"):   {"train": (3.13, 4.52),  "oos": (None, None),  "status": "in_sample_only"},
    ("EASING",   "normal"): {"train": (-8.00, -9.66), "oos": (11.11, 2.41), "status": "unstable"},
    ("EASING",   "storm"):  {"train": (-3.20, -4.43), "oos": (-1.46, -0.33), "status": "negative"},
    ("RISK_OFF", "calm"):   {"train": (0.73, 0.78),   "oos": (None, None),  "status": "in_sample_only"},
    ("RISK_OFF", "normal"): {"train": (-0.40, -0.77), "oos": (-3.87, -2.61), "status": "negative"},
    ("RISK_OFF", "storm"):  {"train": (0.98, 1.91),   "oos": (4.84, 14.12), "status": "oos_confirmed"},
}


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
    """OOS-GATED sizing: press ONLY cells whose edge survived the temporal split (`oos_confirmed`), cut
    consistently-`negative` cells, stay neutral (1.0) for `in_sample_only`/`unstable`/unmeasured — an
    in-sample pattern that has not held OOS does not move real capital. Returns the status + train/oos
    numbers so the decision is auditable, never a bare multiplier.
    """
    if vol is None:
        return {"size_mult": 1.0, "basis": "no_vol_regime", "status": None}
    mr = (macro_regime or "").strip().upper().replace("-", "_")
    cell = S78_CELLS.get((mr, vol))
    if cell is None:
        return {"size_mult": 1.0, "basis": "unmeasured", "status": None}
    st = cell["status"]
    mult = up if st == "oos_confirmed" else (down if st == "negative" else 1.0)
    return {"size_mult": mult, "basis": "oos_gated", "status": st,
            "train": cell["train"], "oos": cell["oos"]}


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
