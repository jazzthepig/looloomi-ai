"""Smoke tests for §BETA-METRIC-AGG track-record aggregator.

Covers the anti-imposter invariants:
  1. tier order is FIXED (TIER_ORDER) — consumers rely on shape.
  2. RAW stays populated when the gate is closed (RAW does not depend on
     ohlcv_daily freshness — it's a pre-R62 number either way).
  3. BETA_ADJ and BETA_ADJ_T_STAT become None (NOT zero, NOT hidden)
     when the gate is closed — silence is worse than a clear None.
  4. defect_warning surfaces ONLY when the gate is open AND
     UNDERWEIGHT's BETA_ADJ_T_STAT is negative (the R62 defect).
  5. bucket_rows is case-insensitive on signal.
  6. n_weighted_mean correctly handles: empty rows, all-null values,
     zero-weight rows, single-row bucket, multi-row bucket (matching spec).
  7. weight_key switch from "n" to "n_beta_adj" preserves the math
     (β columns use the β-adjusted n, not the resolved-outcome n).
  8. apply_ship_gate does not mutate the input dict.
"""
import pytest

from src.api.routers._track_record_agg import (
    TIER_ORDER,
    bucket_rows,
    n_weighted_mean,
    n_weighted_win,
    build_headline,
    apply_ship_gate,
    defect_warning,
)


# ── Synthetic row fixtures ─────────────────────────────────────────────────
def _row(signal, n, raw_alpha=None, alpha_win=None,
         n_beta_adj=None, edge_beta=None, beta_t=None):
    return {
        "signal": signal, "grade": "B", "n": n,
        "avg_alpha_pct": raw_alpha, "alpha_win_pct": alpha_win,
        "n_beta_adj": n_beta_adj, "avg_edge_beta_adj_pct": edge_beta,
        "edge_beta_adj_t": beta_t,
        "computed_at": "2026-07-26T00:00:00Z",
    }


# ── 1. Tier order is fixed ─────────────────────────────────────────────────
def test_tier_order_is_fixed():
    """Consumers may rely on TIER_ORDER being exactly this 4-tuple, in order."""
    assert TIER_ORDER == (
        "STRONG_OUTPERFORM", "OUTPERFORM_broad",
        "UNDERPERFORM", "UNDERWEIGHT",
    )


# ── 2. RAW survives a closed gate (independent of freshness) ───────────────
def test_raw_survives_closed_gate():
    rows = [_row("STRONG OUTPERFORM", 100, raw_alpha=3.42,
                 n_beta_adj=80, edge_beta=8.06, beta_t=5.41)]
    head = build_headline(rows)
    gated = apply_ship_gate(head, gate_open=False)
    assert gated["RAW"]["STRONG_OUTPERFORM"]["avg_alpha_pct"] == 3.42
    assert gated["RAW"]["STRONG_OUTPERFORM"]["n"] == 100


# ── 3. BETA_ADJ + T_STAT are explicitly None when gate is closed ───────────
def test_beta_silent_when_gate_closed():
    rows = [_row("STRONG OUTPERFORM", 100, raw_alpha=3.42,
                 n_beta_adj=80, edge_beta=8.06, beta_t=5.41)]
    head = build_headline(rows)
    gated = apply_ship_gate(head, gate_open=False)
    for tier in TIER_ORDER:
        assert gated["BETA_ADJ"][tier] is None
        assert gated["BETA_ADJ_T_STAT"][tier] is None


# ── 4. defect_warning surfaces only on the R62 condition ───────────────────
def test_defect_warning_open_and_negative():
    rows = [_row("UNDERWEIGHT", 50, raw_alpha=-1.0,
                 n_beta_adj=40, edge_beta=-3.69, beta_t=-3.56)]
    head = build_headline(rows)
    gated_open = apply_ship_gate(head, gate_open=True)
    msg = defect_warning(gated_open, gate_open=True)
    assert msg is not None
    assert "UNDERWEIGHT" in msg and "-3.56" in msg


def test_defect_warning_silent_when_gate_closed():
    rows = [_row("UNDERWEIGHT", 50, raw_alpha=-1.0,
                 n_beta_adj=40, edge_beta=-3.69, beta_t=-3.56)]
    head = build_headline(rows)
    gated = apply_ship_gate(head, gate_open=False)
    msg = defect_warning(gated, gate_open=False)
    assert msg is None  # can't diagnose β without β


def test_defect_warning_silent_when_uw_positive():
    rows = [_row("UNDERWEIGHT", 50, raw_alpha=2.0,
                 n_beta_adj=40, edge_beta=2.0, beta_t=1.5)]
    head = build_headline(rows)
    gated = apply_ship_gate(head, gate_open=True)
    msg = defect_warning(gated, gate_open=True)
    assert msg is None


# ── 5. bucket_rows is case-insensitive ──────────────────────────────────────
def test_bucket_rows_case_insensitive():
    rows = [_row("strong outperform", 10, raw_alpha=1.0)]
    rs = bucket_rows(rows, "STRONG OUTPERFORM")
    assert len(rs) == 1
    rs = bucket_rows(rows, "strong outperform")
    assert len(rs) == 1


# ── 6. n_weighted_mean correctness ─────────────────────────────────────────
def test_n_weighted_mean_empty():
    assert n_weighted_mean([], "avg_alpha_pct") is None


def test_n_weighted_mean_all_null_value():
    rows = [_row("OUTPERFORM", 100, raw_alpha=None)]
    assert n_weighted_mean(rows, "avg_alpha_pct") is None


def test_n_weighted_mean_zero_weight_filtered():
    rows = [_row("OUTPERFORM", 0, raw_alpha=5.0),
            _row("OUTPERFORM", 100, raw_alpha=2.0)]
    out = n_weighted_mean(rows, "avg_alpha_pct")
    assert out is not None
    # The 0-weight row is filtered; only the n=100 row counts.
    assert out["n"] == 100
    assert out["avg_alpha_pct"] == 2.0
    assert out["n_buckets"] == 1


def test_n_weighted_mean_multi_bucket_correctness():
    # 100 outcomes at +2.0 + 200 outcomes at +4.0 → mean = (200+800)/300 = 3.333
    rows = [_row("OUTPERFORM", 100, raw_alpha=2.0),
            _row("OUTPERFORM", 200, raw_alpha=4.0)]
    out = n_weighted_mean(rows, "avg_alpha_pct")
    assert out["n"] == 300
    assert abs(out["avg_alpha_pct"] - 3.3333) < 1e-3
    assert out["n_buckets"] == 2


# ── 7. weight_key switch for BETA_ADJ vs RAW is correct ─────────────────────
def test_beta_columns_use_beta_n_not_resolved_n():
    """A row with n=100 but n_beta_adj=0 should NOT contribute to BETA_ADJ."""
    rows = [_row("OUTPERFORM", 100, raw_alpha=2.0,
                 n_beta_adj=0, edge_beta=None, beta_t=None),
            _row("OUTPERFORM", 100, raw_alpha=4.0,
                 n_beta_adj=100, edge_beta=8.0, beta_t=4.0)]
    head = build_headline(rows)
    # RAW uses n=100+100=200; BETA uses n_beta_adj=100 only.
    assert head["RAW"]["OUTPERFORM_broad"]["n"] == 200
    # The β row's weight is 100; edge_beta is 8.0
    assert head["BETA_ADJ"]["OUTPERFORM_broad"]["n"] == 100
    assert head["BETA_ADJ"]["OUTPERFORM_broad"]["avg_edge_beta_adj_pct"] == 8.0


# ── 8. apply_ship_gate does not mutate the input ───────────────────────────
def test_apply_gate_no_mutation():
    rows = [_row("STRONG OUTPERFORM", 100, raw_alpha=3.42,
                 n_beta_adj=80, edge_beta=8.06, beta_t=5.41)]
    head = build_headline(rows)
    # Snapshot the original
    original = {axis: dict(tiers) for axis, tiers in head.items()}
    apply_ship_gate(head, gate_open=False)
    # Head should not be touched
    for axis, tiers in original.items():
        for tier, val in tiers.items():
            assert head[axis][tier] == val


def test_apply_gate_open_passthrough():
    rows = [_row("STRONG OUTPERFORM", 100, raw_alpha=3.42,
                 n_beta_adj=80, edge_beta=8.06, beta_t=5.41)]
    head = build_headline(rows)
    out = apply_ship_gate(head, gate_open=True)
    assert out["BETA_ADJ"]["STRONG_OUTPERFORM"]["avg_edge_beta_adj_pct"] == 8.06


# ── 9. n_weighted_win is the same math, just a clearer name for intent ──────
def test_win_pct_uses_n_not_n_beta():
    rows = [_row("OUTPERFORM", 100, alpha_win=60.0, raw_alpha=2.0,
                 n_beta_adj=50, edge_beta=5.0, beta_t=2.0)]
    head = build_headline(rows)
    assert head["WIN_PCT"]["OUTPERFORM_broad"]["n"] == 100
    assert head["WIN_PCT"]["OUTPERFORM_broad"]["alpha_win_pct"] == 60.0


# ── 10. Defensive: empty rows → headline is all None ───────────────────────
def test_empty_rows_yields_all_none():
    head = build_headline([])
    for axis in ("RAW", "BETA_ADJ", "BETA_ADJ_T_STAT", "WIN_PCT"):
        for tier in TIER_ORDER:
            assert head[axis][tier] is None, f"{axis}.{tier} should be None"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
