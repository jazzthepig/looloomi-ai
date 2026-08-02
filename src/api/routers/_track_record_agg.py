"""
Pure aggregation logic for /api/v1/signals/track-record.

Seth, 2026-07-26 (MINIMAX_SYNC §BETA-METRIC-AGG ship).

The endpoint in src/api/routers/signals.py delegates to this module so the
math can be unit-tested without a live Supabase. The endpoint adds the
HTTP-level gate (ohlcv_daily freshness), the docstring, and the response
envelope; this module owns the row → tier → headline transformation.

Functions:
  bucket_rows(rows, signal_name) -> list[dict]
  n_weighted_mean(rows, value_key, weight_key="n") -> dict | None
  n_weighted_win(rows, win_key) -> dict | None
  build_headline(rows) -> dict
    Returns the four-axis headline dict
    {RAW, BETA_ADJ, BETA_ADJ_T_STAT, WIN_PCT} keyed by tier.

  apply_ship_gate(headline, gate_open) -> dict
    When gate_open is False, every BETA_ADJ / BETA_ADJ_T_STAT dict
    becomes None (do not publish β-ADJ on stale data).

  defect_warning(headline, gate_open) -> str | None
    When UNDERWEIGHT's β-ADJ t-stat is negative, surface the
    known R62 defect (consumer must not size that tier).
"""
from __future__ import annotations


# Tier order in the headline dict — fixed so consumers can rely on the shape.
TIER_ORDER = (
    "STRONG_OUTPERFORM",
    "OUTPERFORM_broad",
    "UNDERPERFORM",
    "UNDERWEIGHT",
)


def bucket_rows(rows: list[dict], signal_name: str) -> list[dict]:
    """Return the rows whose signal column equals signal_name (case-insensitive)."""
    target = (signal_name or "").strip().upper()
    return [r for r in (rows or [])
            if str(r.get("signal") or "").strip().upper() == target]


def n_weighted_mean(rows: list[dict], value_key: str, weight_key: str = "n") -> dict | None:
    """N-weighted mean of value_key across rows. None when no rows contribute.

    Returns {"n": total_weight, value_key: weighted_mean, "n_buckets": #rows}.
    Designed for ANY value column: avg_alpha_pct (weight_key="n"),
    avg_edge_beta_adj_pct (weight_key="n_beta_adj"), edge_beta_adj_t, etc.
    """
    if not rows:
        return None
    pairs = [(float(r.get(value_key) or 0),
              int(r.get(weight_key) or 0))
             for r in rows
             if r.get(value_key) is not None and int(r.get(weight_key) or 0) > 0]
    if not pairs:
        return None
    n = sum(w for _, w in pairs)
    if not n:
        return None
    mean = sum(v * w for v, w in pairs) / n
    return {"n": n, value_key: round(mean, 4), "n_buckets": len(pairs)}


def n_weighted_win(rows: list[dict], win_key: str) -> dict | None:
    """N-weighted average of a win-rate column (kept at the same scale %, not pp).

    Same shape as n_weighted_mean; kept separate so the docstring is local
    to the win-rate column and future readers don't mistake its semantics
    (avg of percentages, not percentage of averages).
    """
    return n_weighted_mean(rows, win_key, weight_key="n")


def build_headline(rows: list[dict]) -> dict:
    """Compute the four-axis headline from a signal_track_record batch.

    Returns: {RAW, BETA_ADJ, BETA_ADJ_T_STAT, WIN_PCT} → {tier → aggd | None}.
    Tier order is fixed per TIER_ORDER. Buckets with zero contributing rows
    become None for that axis (e.g. a signal tier that has no β-adj rows
    this snapshot gets BETA_ADJ=None — but RAW may still be populated).

    Symmetry invariants (no signal may publish an axis based on partial math):
      - RAW uses weight_key="n"; BETA_ADJ uses weight_key="n_beta_adj".
      - n_beta_adj is the count of rows with sufficient priors for β; missing
        priors on a row → that row excluded from BETA_ADJ aggregation
        (not silently substituted with raw).
      - WIN_PCT uses weight_key="n" (win rate is per row, not per β window).
    """
    buckets = {tier: bucket_rows(rows, _signal_name_from_tier(tier))
               for tier in TIER_ORDER}

    head_raw = {tier: n_weighted_mean(rs, "avg_alpha_pct") for tier, rs in buckets.items()}
    head_beta = {tier: n_weighted_mean(rs, "avg_edge_beta_adj_pct", weight_key="n_beta_adj")
                 for tier, rs in buckets.items()}
    head_beta_t = {tier: n_weighted_mean(rs, "edge_beta_adj_t", weight_key="n_beta_adj")
                   for tier, rs in buckets.items()}
    head_win = {tier: n_weighted_win(rs, "alpha_win_pct") for tier, rs in buckets.items()}

    return {
        "RAW":            head_raw,
        "BETA_ADJ":       head_beta,
        "BETA_ADJ_T_STAT": head_beta_t,
        "WIN_PCT":        head_win,
    }


def apply_ship_gate(headline: dict, gate_open: bool) -> dict:
    """When gate_open is False, suppress the β-ADJ axes.

    RAW + WIN_PCT stay populated (they depend only on resolved outcomes,
    not on the price-feed freshness). BETA_ADJ + BETA_ADJ_T_STAT every
    value set to None so consumers can distinguish "we don't know" from
    "negative" — and so the headline is guaranteed-shape.

    Returns a NEW dict; does not mutate the input.
    """
    if gate_open:
        return headline
    out = {}
    for axis, tiers in headline.items():
        if axis in ("BETA_ADJ", "BETA_ADJ_T_STAT"):
            out[axis] = {tier: None for tier in tiers}
        else:
            out[axis] = tiers
    return out


def defect_warning(headline_after_gate: dict, gate_open: bool) -> str | None:
    """Surface the UNDERWEIGHT defect when its β-ADJ t-stat is negative.

    R62 (2026-07-21) found UNDERWEIGHT to be the ONE tier with a
    negatively-signed β-ADJ edge (t ≈ -3.79). Consumers must NOT size
    this tier until the cause is identified — surface that explicitly
    so they don't have to re-derive it from the headline.

    Returns the warning string, or None if no defect (or gate is closed —
    we can't diagnose β-ADJ without β-ADJ, so the warning is silent when
    the gate is closed).
    """
    if not gate_open:
        return None
    beta_t = (headline_after_gate.get("BETA_ADJ_T_STAT") or {}).get("UNDERWEIGHT")
    if not beta_t:
        return None
    t = beta_t.get("edge_beta_adj_t")
    if t is None or t >= 0:
        return None
    return (
        f"UNDERWEIGHT β-ADJ edge is NEGATIVE (t={t}). Known defect per R62 — "
        "do not size this tier until the cause is identified and fixed."
    )


# ── Internal: tier name → underlying signal name ──────────────────────────
_TIER_TO_SIGNAL = {
    "STRONG_OUTPERFORM": "STRONG OUTPERFORM",
    "OUTPERFORM_broad":  "OUTPERFORM",
    "UNDERPERFORM":      "UNDERPERFORM",
    "UNDERWEIGHT":       "UNDERWEIGHT",
}


def _signal_name_from_tier(tier: str) -> str:
    return _TIER_TO_SIGNAL[tier]
