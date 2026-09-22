"""Smoke test for `paper_trading.ls_state_builder` — S-397 §5b ④ L/S context.

Per `s397-jev-ls-overlay-redesign-2026-09-21.md`: every L/S Jev batch needs
a 30-field-ish state payload with per-symbol + cross-asset features. This
module owns the feature engineering; the Jev backend serializes the dict.

What we test:
  1. Required field validation (bar_ts, universe, closes_by_sym)
  2. Per-symbol features: 5 fields each (mom_30, mom_60, vol_30, breadth_pos, cs_score)
  3. Cross-asset features: 10 fields (regime, btc_dominance, ...)
  4. Cardinality: 5-symbol state = ~35 fields
  5. NaN-safe: None features for short history
  6. CS rank: rank by mom_60 within universe, [0, 1] range
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paper_trading.ls_state_builder import (   # noqa: E402
    build_ls_context, count_fields,
)


def _make_closes(n_days: int = 250, base_px: float = 100.0, drift: float = 0.001) -> dict[str, float]:
    """Synthetic monotonically-rising close series."""
    closes: dict[str, float] = {}
    px = base_px
    for i in range(n_days):
        d = (dt.date(2025, 1, 1) + dt.timedelta(days=i)).isoformat()
        px *= (1.0 + drift)
        closes[d] = round(px, 4)
    return closes


# ── Required fields ────────────────────────────────────────────────────────


def test_bar_ts_required():
    with pytest.raises(ValueError, match="bar_ts is REQUIRED"):
        build_ls_context(
            bar_ts="", universe=["BTC", "ETH"],
            closes_by_sym={"BTC": _make_closes(), "ETH": _make_closes()},
            panel_age_days=1,
        )
    print("✓ bar_ts required")


def test_universe_must_have_two_symbols():
    with pytest.raises(ValueError, match="≥ 2 symbols"):
        build_ls_context(
            bar_ts="2026-09-21", universe=["BTC"],
            closes_by_sym={"BTC": _make_closes()},
            panel_age_days=1,
        )
    print("✓ ≥ 2 symbols required")


def test_universe_must_have_closes_for_at_least_two():
    with pytest.raises(ValueError, match="only 1 have closes"):
        build_ls_context(
            bar_ts="2026-09-21", universe=["BTC", "ETH"],
            closes_by_sym={"BTC": _make_closes()},  # ETH missing
            panel_age_days=1,
        )
    print("✓ closes required for ≥ 2 symbols")


# ── Feature shape ──────────────────────────────────────────────────────────


def test_per_symbol_has_five_fields():
    closes = {
        "BTC": _make_closes(300, drift=0.002),  # uptrend
        "ETH": _make_closes(300, drift=-0.001),  # downtrend
        "SOL": _make_closes(300, drift=0.005),  # strong uptrend
    }
    state = build_ls_context(
        bar_ts="2026-09-21", universe=["BTC", "ETH", "SOL"],
        closes_by_sym=closes, panel_age_days=1,
    )
    assert "per_symbol" in state
    for sym in ["BTC", "ETH", "SOL"]:
        feats = state["per_symbol"][sym]
        assert set(feats.keys()) == {"mom_30", "mom_60", "vol_30",
                                      "breadth_pos", "cs_score"}, \
            f"{sym} features: {feats.keys()}"
    print("✓ per-symbol has 5 fields each")


def test_cross_asset_has_ten_fields():
    state = build_ls_context(
        bar_ts="2026-09-21", universe=["BTC", "ETH"],
        closes_by_sym={"BTC": _make_closes(), "ETH": _make_closes()},
        panel_age_days=1, regime="EASING", btc_dominance=0.55,
    )
    assert "cross_asset" in state
    assert set(state["cross_asset"].keys()) == {
        "regime", "btc_dominance", "funding_rate_btc", "breadth_200ma",
        "cross_skew", "panel_age_days", "panel_n_symbols",
        "vol_20d_panel", "cadence_days", "cost_bps_rt",
    }
    print("✓ cross-asset has 10 fields")


# ── Cardinality ────────────────────────────────────────────────────────────


def test_cardinality_5_symbols_under_255():
    closes = {s: _make_closes(300) for s in ["BTC", "ETH", "SOL", "BNB", "XRP"]}
    state = build_ls_context(
        bar_ts="2026-09-21", universe=list(closes.keys()),
        closes_by_sym=closes, panel_age_days=1,
    )
    n = count_fields(state)
    assert n == 35, f"expected 35, got {n}"
    assert n < 255
    print(f"✓ 5-symbol cardinality = {n} (cap 255)")


# ── Feature values ─────────────────────────────────────────────────────────


def test_mom_60_sign_matches_drift():
    """mom_60 > 0 for uptrend, < 0 for downtrend."""
    closes = {
        "UP": _make_closes(300, drift=0.003),    # up
        "DOWN": _make_closes(300, drift=-0.003),  # down
    }
    state = build_ls_context(
        bar_ts="2026-09-21", universe=["UP", "DOWN"],
        closes_by_sym=closes, panel_age_days=1,
    )
    assert state["per_symbol"]["UP"]["mom_60"] > 0
    assert state["per_symbol"]["DOWN"]["mom_60"] < 0
    print(f"✓ mom_60 signs: UP={state['per_symbol']['UP']['mom_60']:.4f}, "
          f"DOWN={state['per_symbol']['DOWN']['mom_60']:.4f}")


def test_cs_score_normalized_0_to_1():
    """CS rank: best=1.0, worst=0.0."""
    closes = {
        "BEST": _make_closes(300, drift=0.01),    # strongest up
        "MID":  _make_closes(300, drift=0.002),
        "WORST": _make_closes(300, drift=-0.01),   # down
    }
    state = build_ls_context(
        bar_ts="2026-09-21", universe=["BEST", "MID", "WORST"],
        closes_by_sym=closes, panel_age_days=1,
    )
    cs = {s: state["per_symbol"][s]["cs_score"] for s in ["BEST", "MID", "WORST"]}
    assert cs["BEST"] == pytest.approx(1.0, abs=1e-6)
    assert cs["WORST"] == pytest.approx(0.0, abs=1e-6)
    assert 0.0 <= cs["MID"] <= 1.0
    print(f"✓ cs_score rank: {cs}")


def test_breadth_pos_positive_for_uptrend():
    """breadth_pos > 0 when close > 200d MA."""
    state = build_ls_context(
        bar_ts="2026-09-21", universe=["UP", "DOWN"],
        closes_by_sym={"UP": _make_closes(300, drift=0.005),
                       "DOWN": _make_closes(300, drift=-0.005)},
        panel_age_days=1,
    )
    assert state["per_symbol"]["UP"]["breadth_pos"] > 0
    assert state["per_symbol"]["DOWN"]["breadth_pos"] < 0
    print(f"✓ breadth_pos: UP={state['per_symbol']['UP']['breadth_pos']:.4f}, "
          f"DOWN={state['per_symbol']['DOWN']['breadth_pos']:.4f}")


# ── NaN safety ─────────────────────────────────────────────────────────────


def test_short_history_returns_none_features():
    """< 60d history → mom_60 returns None (Vadim discipline: missing ≠ 0)."""
    closes = {
        "BTC": _make_closes(300),
        "SHORT": _make_closes(30),  # only 30d
    }
    state = build_ls_context(
        bar_ts="2026-09-21", universe=["BTC", "SHORT"],
        closes_by_sym=closes, panel_age_days=1,
    )
    assert state["per_symbol"]["SHORT"]["mom_60"] is None
    assert state["per_symbol"]["SHORT"]["mom_30"] is None
    # 30d is enough for vol_30? need window+1=31 → 30d is NOT enough
    assert state["per_symbol"]["SHORT"]["vol_30"] is None
    print("✓ short history → None features (not 0)")
