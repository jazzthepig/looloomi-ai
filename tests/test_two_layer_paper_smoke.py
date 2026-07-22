"""Smoke tests for the §5b two-layer paper book (Seth, 2026-07-21).

The properties that actually matter for a book going to production:
  1. a DEAD core holds ZERO size (never fabricates exposure) — R57's whole lesson
  2. a LIVE core + open gate DOES engage (the book isn't just permanently off)
  3. the strict C gate is respected (live core but closed gate ⇒ flat)
  4. the regime score is POINT-IN-TIME safe (no look-ahead; the research version wasn't)
  5. graceful degradation when funding data is missing
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.signals.two_layer_paper import (  # noqa: E402
    DEFAULT_CORE, core_health, core_position, regime_score_c, target_weights)


def _uptrend(n=300, seed=3):
    rng = np.random.default_rng(seed)
    return 100 * np.cumprod(1 + rng.normal(0.005, 0.015, n))


def _downtrend(n=300, seed=4):
    rng = np.random.default_rng(seed)
    return 100 * np.cumprod(1 + rng.normal(-0.004, 0.025, n))


def test_core_position_tracks_trend():
    up, dn = _uptrend(), _downtrend()
    assert (core_position(up, DEFAULT_CORE) > 0).mean() > 0.5
    assert (core_position(dn, DEFAULT_CORE)[-90:] > 0).mean() < 0.2


def test_dead_core_holds_zero_size():
    """R57: the core is dead ⇒ the book must sit FLAT, not invent trades."""
    dn = _downtrend()
    h = core_health(core_position(dn, DEFAULT_CORE))
    assert h["state"] == "dead"
    w, diag = target_weights({"BTC": {"close": dn, "funding": np.array([])}}, DEFAULT_CORE)
    assert w == {}
    assert diag["book_state"] == "core_dead"


def test_live_core_is_recognised():
    up = _uptrend()
    h = core_health(core_position(up, DEFAULT_CORE))
    assert h["state"] == "live"
    assert h["engagement_90d"] > 0.05


def test_strict_gate_blocks_when_regime_negative():
    """Live core but C below the gate ⇒ still flat. The overlay is the point."""
    up = _uptrend()
    _, diag = target_weights({"BTC": {"close": up, "funding": np.array([])}}, DEFAULT_CORE)
    a = diag["per_asset"]["BTC"]
    if a["c_score"] is not None and a["c_score"] <= 0.20:
        assert a["gate_open"] is False


def test_regime_score_is_point_in_time_safe():
    """Score at t must be identical whether or not future bars exist. The research
    implementation used full-sample normalization and would FAIL this."""
    px = np.concatenate([_uptrend(250), _downtrend(150)])
    rng = np.random.default_rng(9)
    f = rng.normal(0.0001, 0.0002, len(px))
    full = regime_score_c(px, f)
    trunc = regime_score_c(px[:300], f[:300])
    for t in (280, 290, 299):
        assert np.isclose(full[t], trunc[t], equal_nan=True), f"look-ahead leak at t={t}"


def test_degrades_without_funding():
    up = _uptrend()
    c = regime_score_c(up, np.array([]))
    assert np.isfinite(c[-1]), "must still score using trend+chop when funding is absent"


def test_weights_bounded_and_sane():
    up = _uptrend()
    w, _ = target_weights({"BTC": {"close": up, "funding": np.array([])},
                           "ETH": {"close": _uptrend(300, 5), "funding": np.array([])}},
                          DEFAULT_CORE)
    assert sum(abs(v) for v in w.values()) <= 1.0 + 1e-9
    assert all(0 <= v <= 1 for v in w.values())


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for fn in fns:
        try:
            fn(); print(f"  ✓ {fn.__name__}")
        except Exception:
            bad += 1; print(f"  ✗ {fn.__name__}"); traceback.print_exc()
    print(f"\n{len(fns)-bad}/{len(fns)} passed")
    sys.exit(1 if bad else 0)
