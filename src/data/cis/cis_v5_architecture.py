"""
CIS v5 — the two-score architecture (return vs risk). REFERENCE, not yet deployed (Seth, 2026-07-22)
=====================================================================================================

CIS v4 collapses five pillars into ONE weighted sum (`cis_provider.calculate_total_score`:
`cis = Σ wᵢ·Pᵢ`, base × regime × IC). 2026-07-21→22 proved that structure is the bug, not the
weights (R63b): a single weighted sum of LEVELS cannot express that the pillars are three different
KINDS of object. **CIS v5 is an architecture change, not a reweight.** Evidence chain:

  · R62  — with PIT-safe β adjustment, CIS pillars predict the β-adj edge; cis level spread +2.85.
  · R63  — pillar S is mean-FLAT as a return predictor but widens vol (+8%) and deepens the p10 tail
           (−32%) at high S ⇒ S is a RISK factor, not a return factor.
  · R63b — signed-Δ quintiles give three kinds: LEVEL {F +3.28, M +2.74}, DIRECTIONAL-CHANGE
           {A: level +4.48, ΔA +1.18}, FAST-STATE/RISK {S, O: stability premium ΔS+2.72/ΔO+2.70}.
  · S-76 — price↔pillar lead-lag: S/O are price-COINCIDENT (contemp ρ O+0.52/S+0.44, ZERO lead),
           F is price-INDEPENDENT (ρ−0.01). Confirms S/O carry risk/regime state, not forward return;
           F/M/A carry the return signal. (`src/research/validation/so_price_leadlag.py`.)

⇒ v5 emits TWO scores instead of one:

  return_score  = f(F level, M level, A level+change)   — for RANKING / direction (what to hold)
  risk_score    = g(O level, S/O stability)             — for SIZING / confidence (how much, how sure)

  (S-77 validation refined the risk side: O — not S — is the dispersion pillar. corr(O,edge²)=+0.145,
   2× any other; F=−0.00 pure-return; S weak on both axes ⇒ S enters only via Δ-stability→confidence.)

The old scalar conflated "this asset ranks well" with "this asset is safe to size into" — exactly the
two things R63 showed diverge at high S (rank unchanged, tail deeper). v5 keeps them separate so an
allocator sizes on risk and ranks on return, instead of averaging the two into a number that hides both.

This module is a PURE REFERENCE + proposal for the Mac engine (`cis_v4_engine.py`, Minimax) and the
Railway T2 path (`cis_provider.py`, Seth). It does NOT change live scores, grades, signals, or the push
contract. Compliance: positioning language only in any surfaced output; this computes internal scores.
"""
from __future__ import annotations

import math

SCHEMA = "cis_v5_ref_2026_07_22"
_NAN = float("nan")


def _norm100(x):
    """0..100 pillar → 0..1; None/NaN → NaN (I1: unmeasured is not 0)."""
    if x is None or (isinstance(x, float) and x != x):
        return _NAN
    return max(0.0, min(1.0, float(x) / 100.0))


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ── Return score — F level, M level, A level+change (the price-carrying pillars) ──────────────
# Defaults sum to 1 over the ACTIVE (non-NaN) components — an unmeasured pillar is dropped and the
# rest renormalized (I1), never imputed to 0. A is dual-natured (R62 strong level + R63b ΔA): it
# contributes a level term AND a change term. S and O are ABSENT here by design (they are risk, S-76).
RETURN_WEIGHTS = {"F": 0.30, "M": 0.30, "A_level": 0.25, "A_change": 0.15}


def return_score(pillars: dict, prior_pillars: dict | None = None,
                 weights: dict | None = None) -> dict:
    """Directional return score from F/M levels + A level & change. 0..100. Ranking scalar.

    `prior_pillars` supplies A[t-1] for the change term; absent ⇒ the A_change component is dropped
    (NaN-honest) and remaining weights renormalize. Returns the score plus the active components so
    the decomposition is inspectable, never a black-box number.
    """
    w = dict(weights or RETURN_WEIGHTS)
    comp = {
        "F":        (_norm100(pillars.get("F")),                                  w["F"]),
        "M":        (_norm100(pillars.get("M")),                                  w["M"]),
        "A_level":  (_norm100(pillars.get("A")),                                  w["A_level"]),
    }
    # A change (PIT: prior only). ΔA normalized to [-1,1] over ±50 pts, shifted to [0,1].
    a_now, a_prev = pillars.get("A"), (prior_pillars or {}).get("A")
    if a_now is not None and a_prev is not None:
        d = _clamp((float(a_now) - float(a_prev)) / 50.0, -1.0, 1.0)
        comp["A_change"] = (0.5 * (d + 1.0), w["A_change"])
    active = {k: (v, wt) for k, (v, wt) in comp.items() if v == v}   # drop NaN components
    tw = sum(wt for _, wt in active.values())
    if tw <= 0:
        return {"return_score": _NAN, "components": {}, "coverage": 0}
    score = sum(v * wt for v, wt in active.values()) / tw * 100.0
    return {
        "return_score": round(score, 2),
        "components": {k: round(v, 3) for k, (v, wt) in active.items()},
        "coverage": len(active),
    }


# ── Risk score — O level (sizing) + S/O stability (confidence) ────────────────────────────────
# risk_score ∈ [0,1], higher = riskier. **O is the empirical dispersion pillar** — S-77 validation on
# β-adjusted outcomes (n=6,207): corr(O, edge²) = +0.145, TWICE any other pillar (A 0.079, S 0.040,
# F −0.002); the O quintiles escalate vol 14.3→20.8 and deepen the p10 tail −13.5→−20.9 monotonically.
# So risk is O-led, NOT S-led. S is DEMOTED: weak on both axes at the level (mean-IC 0.042, var-corr
# 0.040), it contributes to risk only through its Δ-STABILITY (R63b), which flows via `confidence`.
# S/O INSTABILITY (R63b + S-76: a large recent move = we arrived AFTER the reprice) lowers confidence.
_STABILITY_SCALE = 25.0   # trailing std of 25 pillar-pts ⇒ fully unstable


def risk_score(pillars: dict, so_stability: dict | None = None) -> dict:
    """Risk/sizing score from O level (primary) + S/O stability. Returns risk_score, confidence,
    size_mult. `so_stability` = {'S': std_S, 'O': std_O} trailing dispersions (asset-vector v2
    stability dims). Absent ⇒ confidence falls back to a flagged-neutral 0.5, never a false 1.0 (I1).
    """
    o = pillars.get("O")
    o_risk = _norm100(o)          # 0..1, primary risk driver (S-77: O is the dispersion pillar)

    inst = _NAN
    if so_stability:
        parts = [so_stability.get("S"), so_stability.get("O")]
        parts = [float(p) for p in parts if p is not None and p == p]
        if parts:
            inst = _clamp((sum(parts) / len(parts)) / _STABILITY_SCALE, 0.0, 1.0)

    # combine: risk is high if the on-chain dispersion pillar is elevated OR the fast state is churning
    known = [x for x in (o_risk, inst) if x == x]
    rscore = max(known) if known else _NAN          # max: either channel raising risk is enough
    confidence = (1.0 - inst) if inst == inst else (0.5 if o_risk == o_risk else _NAN)
    size_mult = (1.0 - rscore) * (confidence if confidence == confidence else 1.0) if rscore == rscore else _NAN
    return {
        "risk_score":  None if rscore != rscore else round(rscore, 3),
        "confidence":  None if confidence != confidence else round(confidence, 3),
        "size_mult":   None if size_mult != size_mult else round(_clamp(size_mult, 0.0, 1.0), 3),
        "o_risk":      None if o_risk != o_risk else round(o_risk, 3),
        "instability": None if inst != inst else round(inst, 3),
    }


def cis_v5(pillars: dict, *, prior_pillars: dict | None = None,
           so_stability: dict | None = None) -> dict:
    """The v5 object: return and risk as SEPARATE outputs (never one weighted sum).

    rank on `return_score`; size on `size_mult` (return gated by risk × confidence). The scalar
    `blended_for_display` exists ONLY for legacy single-number surfaces — it is return_score × size_mult
    and must NOT be used to rank (it re-conflates the two axes v5 exists to separate).
    """
    ret = return_score(pillars, prior_pillars)
    rk = risk_score(pillars, so_stability)
    rs = ret["return_score"]
    sm = rk["size_mult"]
    blended = round(rs * sm, 2) if (rs == rs and sm is not None) else None
    return {
        "schema": SCHEMA,
        "return_score": rs,          # RANK on this
        "risk_score": rk["risk_score"],
        "confidence": rk["confidence"],
        "size_mult": sm,             # SIZE on this
        "blended_for_display": blended,   # legacy only; do not rank
        "return_components": ret["components"],
        "risk_detail": {k: rk[k] for k in ("o_risk", "instability")},
        "return_coverage": ret["coverage"],
    }
