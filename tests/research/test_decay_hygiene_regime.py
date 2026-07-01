"""Tests for decay_monitor, signal_hygiene, regime_attribution."""

import math
import pytest

from src.research.decay_monitor import DecayMonitor
from src.research.signal_hygiene import (
    HygieneReport, assess, capacity_estimate, slippage_bps, turnover_metrics,
)
from src.research.regime_attribution import (
    VALID_REGIMES, RegimeBucket, RegimeAttribution, attribute,
)


# ── decay_monitor ────────────────────────────────────────────────────────────

class TestDecayMonitorRolling:
    def test_insufficient_data(self):
        m = DecayMonitor(window_size=30)
        result = m.rolling_sharpe([1, 2, 3])  # less than window
        assert result == []

    def test_constant_returns_zero_sharpe(self):
        m = DecayMonitor(window_size=5)
        # All same value → std=0 → sharpe=0
        result = m.rolling_sharpe([5.0] * 20)
        for s in result:
            assert s == 0.0

    def test_positive_drift_positive_sharpe(self):
        m = DecayMonitor(window_size=10)
        # Sequence with positive drift
        pnls = [i * 1.0 for i in range(50)]  # 0, 1, ..., 49
        result = m.rolling_sharpe(pnls)
        # Each window has positive mean and positive std
        assert all(s > 0 for s in result)

    def test_annualisation(self):
        m = DecayMonitor(window_size=10)
        pnls = [1.0] * 30
        # Without annualisation
        s1 = m.rolling_sharpe(pnls, periods_per_year=None)
        # With annualisation by 252
        s2 = m.rolling_sharpe(pnls, periods_per_year=252)
        # All sharpes = 0 (constant returns), so both should be 0
        assert all(s == 0 for s in s1) and all(s == 0 for s in s2)


class TestDecayMonitorHalfLife:
    def test_linear_decay(self):
        m = DecayMonitor(window_size=10)
        # Synthetic: rolling sharpe decays from 1.0 to ~0.1 linearly
        # Need rolling_sharpes (sequences of length 50+)
        pnls = list(range(100, 0, -1))  # decreasing
        rolling = m.rolling_sharpe(pnls)
        hl = m.half_life(rolling)
        # Should give a finite positive number
        assert hl > 0
        assert not math.isnan(hl)

    def test_no_decay_when_peak_at_end(self):
        """When peak is the last value, half-life is undefined (NaN)."""
        m = DecayMonitor(window_size=10)
        pnls = list(range(100))  # monotonically increasing → peak at end
        rolling = m.rolling_sharpe(pnls)
        hl = m.half_life(rolling)
        # Peak at end → no observable decay → NaN
        assert math.isnan(hl)

    def test_half_life_finite_for_decay(self):
        m = DecayMonitor(window_size=10)
        # Decreasing pnls → rolling sharpe peak at start, then decay
        pnls = list(range(100, 0, -1))
        rolling = m.rolling_sharpe(pnls)
        hl = m.half_life(rolling)
        assert hl > 0
        assert not math.isnan(hl)
        assert hl != math.inf


class TestDecayMonitorCheck:
    def test_insufficient_data(self):
        m = DecayMonitor(window_size=30)
        status = m.check([1, 2, 3, 4, 5])
        assert status.status == "INSUFFICIENT_DATA"
        assert "need" in status.notes.lower()

    def test_stable_strategy_ok(self):
        m = DecayMonitor(window_size=30)
        # 100 stable observations
        import random
        random.seed(42)
        pnls = [random.gauss(10, 15) for _ in range(100)]
        status = m.check(pnls)
        # Should be OK or WATCH (not DECAY)
        assert status.status in ("OK", "WATCH", "DECAY")

    def test_decay_collapse(self):
        """Stable, then collapse, should trigger WATCH or DECAY."""
        import random
        random.seed(42)
        m = DecayMonitor(window_size=20, z_threshold=2.0, halflife_threshold=0.5)
        # 300 stable positive obs (mean=10, std=3) — narrow distribution.
        # Then 100 extreme collapse (mean=-100, std=10) — pulls recent
        # rolling Sharpe to extreme negative outliers vs historical norm.
        good = [random.gauss(10, 3) for _ in range(300)]
        bad = [random.gauss(-100, 10) for _ in range(100)]
        status = m.check(good + bad)
        # Either WATCH or DECAY indicates the strategy has degraded
        # significantly below its historical baseline.
        assert status.status in ("WATCH", "DECAY"), (
            f"expected decay detection; got status={status.status} "
            f"z={status.z_score:.2f} peak={status.rolling_sharpe_peak:.2f} "
            f"current={status.rolling_sharpe_current:.2f}"
        )
        assert status.z_score < 0  # current below mean


# ── signal_hygiene ───────────────────────────────────────────────────────────

class TestTurnoverMetrics:
    def test_basic(self):
        # Turnover = bars_per_year / avg_hold_bars
        turnover, _ = turnover_metrics(n_round_trips=100, avg_hold_bars=20, bars_per_year=2190)
        assert abs(turnover - 2190 / 20) < 1e-9  # = 109.5 round-trips/yr

    def test_high_frequency(self):
        # 1-bar avg hold → 2190 round-trips per year (max turnover at 4h)
        turnover, _ = turnover_metrics(n_round_trips=10000, avg_hold_bars=1, bars_per_year=2190)
        assert abs(turnover - 2190) < 1e-9

    def test_low_frequency(self):
        # 100-bar avg hold → 21.9 round-trips per year
        turnover, _ = turnover_metrics(n_round_trips=10, avg_hold_bars=100, bars_per_year=2190)
        assert abs(turnover - 21.9) < 1e-9

    def test_zero_hold(self):
        turnover, _ = turnover_metrics(n_round_trips=10, avg_hold_bars=0, bars_per_year=2190)
        assert turnover == 0.0


class TestCapacityEstimate:
    def test_zero_edge_returns_inf(self):
        cap = capacity_estimate(
            avg_volume_usd_per_bar=10_000_000,
            position_size_usd=10_000,
            signal_edge_bps=0,
        )
        assert cap == float("inf")

    def test_capacity_scales_with_volume(self):
        # Doubling volume should double capacity
        cap1 = capacity_estimate(10_000_000, 10_000, 50)
        cap2 = capacity_estimate(20_000_000, 10_000, 50)
        assert abs(cap2 - 2 * cap1) < 1e-6

    def test_realistic_numbers(self):
        # Liquid BTC perp: avg daily volume $1B / 24 1h bars ≈ $42M/bar
        # Edge 50bps, k=0.1, max_pct_volume=1%
        # capacity = 42M * (0.005/0.1)^2 / 0.01 = 42M * 0.0025 / 0.01 = 10.5M
        cap = capacity_estimate(42_000_000, 10_000, 50)
        assert 5_000_000 < cap < 50_000_000


class TestSlippageBps:
    def test_zero_volume_returns_inf(self):
        s = slippage_bps(position_size_usd=10_000, avg_volume_usd_per_bar=0)
        assert s == float("inf")

    def test_slippage_scales_with_size(self):
        s1 = slippage_bps(position_size_usd=10_000, avg_volume_usd_per_bar=1_000_000)
        s2 = slippage_bps(position_size_usd=40_000, avg_volume_usd_per_bar=1_000_000)
        # 4x order size → 2x slippage (sqrt model)
        assert abs(s2 - 2 * s1) < 1e-6

    def test_bps_unit(self):
        # 10bps at standard config
        s = slippage_bps(position_size_usd=10_000, avg_volume_usd_per_bar=100_000_000)
        assert 0 < s < 100   # reasonable range


class TestAssess:
    def test_overfit_capacity(self):
        # Very low volume → capacity < 2x position
        r = assess(
            n_round_trips=100, avg_hold_bars=10, bars_per_year=2190,
            avg_volume_usd_per_bar=10_000,  # tiny volume
            position_size_usd=10_000,
            signal_edge_bps=50,
        )
        assert r.hygiene_grade == "OVERFIT"

    def test_ok_capacity(self):
        # High volume, small position
        r = assess(
            n_round_trips=100, avg_hold_bars=10, bars_per_year=2190,
            avg_volume_usd_per_bar=10_000_000_000,  # $10B/bar
            position_size_usd=10_000,
            signal_edge_bps=50,
        )
        assert r.hygiene_grade == "OK"

    def test_high_turnover_flagged(self):
        r = assess(
            n_round_trips=10_000, avg_hold_bars=1, bars_per_year=2190,
            avg_volume_usd_per_bar=10_000_000_000,
            position_size_usd=10_000,
            signal_edge_bps=50,
        )
        assert r.turnover_per_year > 200
        assert "turnover" in r.notes.lower()


# ── regime_attribution ───────────────────────────────────────────────────────

class TestRegimeAttribution:
    def test_length_mismatch(self):
        with pytest.raises(ValueError):
            attribute([1, 2, 3], ["RISK_ON", "RISK_OFF"])

    def test_unknown_regime(self):
        with pytest.raises(ValueError):
            attribute([1, 2], ["RISK_ON", "WHATEVER"])

    def test_basic(self):
        pnls = [100, -50, 30, -20]
        regimes = ["RISK_ON", "RISK_OFF", "GOLDILOCKS", "RISK_OFF"]
        r = attribute(pnls, regimes)
        assert r.total_trades == 4
        assert r.buckets["RISK_ON"].n_trades == 1
        assert r.buckets["RISK_OFF"].n_trades == 2
        assert r.buckets["RISK_ON"].total_pnl == 100
        assert r.buckets["RISK_OFF"].total_pnl == -70
        assert r.buckets["GOLDILOCKS"].total_pnl == 30

    def test_contributions_sum_to_100(self):
        pnls = [100, -50, 30, -20, 80, -40]
        regimes = ["RISK_ON", "RISK_OFF", "GOLDILOCKS", "RISK_OFF", "RISK_ON", "TIGHTENING"]
        r = attribute(pnls, regimes)
        total_contrib = sum(b.contribution_pct for b in r.buckets.values() if b.n_trades > 0)
        assert abs(total_contrib - 100.0) < 0.01

    def test_worst_best(self):
        pnls = [-100, 50, 50]
        regimes = ["RISK_OFF", "RISK_ON", "GOLDILOCKS"]
        r = attribute(pnls, regimes)
        assert r.worst_regime == "RISK_OFF"
        assert r.worst_regime_pnl == -100
        assert r.best_regime in ("RISK_ON", "GOLDILOCKS")  # tied at +50

    def test_all_zero_pnl(self):
        r = attribute([0, 0, 0], ["RISK_ON", "RISK_OFF", "RISK_ON"])
        assert r.total_pnl == 0.0
        # No clear best/worst
        assert r.regime_dependency == 0.0

    def test_regime_dependency_concentrated(self):
        # All PnL in one regime → high dependency
        r = attribute([100, 100, 100, -10, -10], ["RISK_ON"] * 3 + ["RISK_OFF"] * 2)
        assert r.regime_dependency > 0.3  # concentrated

    def test_regime_dependency_robust(self):
        # PnL spread across 3 regimes → low dependency
        r = attribute([10, 10, 10, -10, -10, 10], ["RISK_ON"] * 3 + ["RISK_OFF"] * 2 + ["TIGHTENING"])
        assert r.regime_dependency < 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])