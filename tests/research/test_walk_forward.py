"""Tests for walk_forward.py — gate 3-4 of STRATEGY_VALIDATION.md."""

import pytest

from src.research.walk_forward import (
    WalkForwardConfig,
    WalkForwardRoll,
    compute_window_boundaries,
    compute_decay_ratio,
    aggregate_walk_forward,
    apply_purge_embargo,
)


class TestWindowBoundaries:
    """compute_window_boundaries should produce non-overlapping, in-bounds windows."""

    def test_no_overlap(self):
        cfg = WalkForwardConfig(train_bars=100, test_bars=20, n_rolls=5, embargo_bars=5)
        bounds = compute_window_boundaries(total_bars=500, cfg=cfg)
        # TEST windows must not overlap (each new test starts where prev test ends)
        for i in range(1, len(bounds)):
            prev = bounds[i - 1]
            curr = bounds[i]
            assert curr[2] >= prev[3], (
                f"roll {i} test_start {curr[2]} overlaps prev test_end {prev[3]}"
            )

    def test_no_train_overlap_within_same_roll(self):
        """Within a single roll, train and test must be separated by at least embargo."""
        cfg = WalkForwardConfig(train_bars=100, test_bars=20, n_rolls=5, embargo_bars=10)
        bounds = compute_window_boundaries(total_bars=500, cfg=cfg)
        for b in bounds:
            # test_start must be > train_end (gap >= embargo)
            assert b[2] > b[1], f"train_end {b[1]} >= test_start {b[2]}"

    def test_last_test_ends_at_total(self):
        cfg = WalkForwardConfig(train_bars=100, test_bars=20, n_rolls=5, embargo_bars=5)
        bounds = compute_window_boundaries(total_bars=500, cfg=cfg)
        assert bounds[-1][3] == 500, f"last test should end at total_bars; got {bounds[-1][3]}"

    def test_train_test_gap_includes_embargo(self):
        cfg = WalkForwardConfig(train_bars=100, test_bars=20, n_rolls=5, embargo_bars=10)
        bounds = compute_window_boundaries(total_bars=500, cfg=cfg)
        for b in bounds:
            gap = b[2] - b[1]  # test_start - train_end
            assert gap == cfg.embargo_bars, f"gap {gap} should equal embargo {cfg.embargo_bars}"

    def test_insufficient_data_returns_empty(self):
        cfg = WalkForwardConfig(train_bars=400, test_bars=100, n_rolls=10, embargo_bars=0)
        # total_bars < train + test → no valid roll
        bounds = compute_window_boundaries(total_bars=400, cfg=cfg)
        assert bounds == []

    def test_window_count_capped_by_data(self):
        # Explicitly set embargo=0 so span = train + test only
        cfg = WalkForwardConfig(train_bars=50, test_bars=10, n_rolls=100, embargo_bars=0)
        bounds = compute_window_boundaries(total_bars=200, cfg=cfg)
        # max rolls = (200 - 50 - 0 - 10) / 10 + 1 = 15; capped at 100 → 15
        assert len(bounds) == 15


class TestDecayRatio:
    """compute_decay_ratio implements gate 3: ratio < 0.7 = overfit."""

    def test_ok_decay(self):
        ratio, status = compute_decay_ratio(is_sharpe=1.0, oos_sharpe=0.8)
        assert status == "OK"
        assert abs(ratio - 0.8) < 1e-9

    def test_overfit(self):
        ratio, status = compute_decay_ratio(is_sharpe=1.0, oos_sharpe=0.5)
        assert status == "OVERFIT"
        assert abs(ratio - 0.5) < 1e-9

    def test_negative_oos_flagged(self):
        # IS positive, OOS negative = clear overfit
        ratio, status = compute_decay_ratio(is_sharpe=1.0, oos_sharpe=-0.3)
        assert status == "NEGATIVE_OOS"

    def test_degenerate_is_sharpe(self):
        # IS near zero → can't compute meaningful decay
        ratio, status = compute_decay_ratio(is_sharpe=0.04, oos_sharpe=1.0)
        assert status == "DEGENERATE"
        assert ratio == 0.0

    def test_negative_is_positive_oos(self):
        # IS losing, OOS winning — rare but interesting case
        ratio, status = compute_decay_ratio(is_sharpe=-0.5, oos_sharpe=0.5)
        # ratio = -1.0 → flagged as overfit (because ratio < 0.7)
        assert status == "OVERFIT"


class TestAggregate:
    def test_empty_rolls(self):
        agg = aggregate_walk_forward([])
        assert agg["oos_sharpe_mean"] == 0.0
        assert agg["oos_n_trades_total"] == 0

    def test_simple_aggregate(self):
        rolls = [
            WalkForwardRoll(roll_id=0, train_start=0, train_end=100, test_start=105, test_end=125,
                            is_sharpe=1.0, oos_sharpe=0.8, oos_n_trades=10, oos_cagr_pct=5.0,
                            oos_max_dd_pct=3.0, oos_win_rate_pct=50.0),
            WalkForwardRoll(roll_id=1, train_start=20, train_end=120, test_start=125, test_end=145,
                            is_sharpe=1.2, oos_sharpe=0.6, oos_n_trades=15, oos_cagr_pct=4.0,
                            oos_max_dd_pct=4.0, oos_win_rate_pct=45.0),
        ]
        agg = aggregate_walk_forward(rolls)
        assert agg["oos_n_trades_total"] == 25
        assert abs(agg["oos_sharpe_mean"] - 0.7) < 1e-9
        assert abs(agg["is_sharpe_mean"] - 1.1) < 1e-9
        assert agg["oos_max_dd_max"] == 4.0


class TestPurgeEmbargo:
    def test_basic(self):
        # 10 pnls, boundary at index 5, purge=2, embargo=1
        # Drop indices [3, 4] (purge) and [5] (embargo) → keep [0,1,2,6,7,8,9]
        result = apply_purge_embargo(list(range(10)), boundary_idx=5, purge=2, embargo=1)
        assert result == [0, 1, 2, 6, 7, 8, 9]

    def test_purge_at_start_clamped(self):
        # boundary=2, purge=5, embargo=0.
        # Drop window = [max(0, 2-5), min(10, 2+0)) = [0, 2) -> drop indices 0, 1.
        # Symmetric purging clips purge to available data.
        result = apply_purge_embargo(list(range(10)), boundary_idx=2, purge=5, embargo=0)
        assert result == [2, 3, 4, 5, 6, 7, 8, 9]

    def test_embargo_at_end_clamped(self):
        # boundary=8, embargo=5 → end = min(10, 13) = 10, drop nothing after
        result = apply_purge_embargo(list(range(10)), boundary_idx=8, purge=0, embargo=5)
        # end=10, start=8 → keep [0..7]
        assert result == [0, 1, 2, 3, 4, 5, 6, 7]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])