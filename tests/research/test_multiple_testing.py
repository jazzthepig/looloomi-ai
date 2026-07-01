"""Tests for multiple_testing.py — gate 5 of STRATEGY_VALIDATION.md."""

import math
import pytest

from src.research.multiple_testing import apply_correction, interpret_correction


class TestBonferroni:
    def test_all_reject_obvious_signals(self):
        # 3 strong signals (p < 0.001) should all reject under any correction
        result = apply_correction([1e-6, 1e-5, 1e-4], method="bonferroni", alpha=0.05)
        assert result.n_rejected == 3

    def test_noise_not_rejected(self):
        # 10 noise p-values (uniform between 0.1 and 0.9) → most should NOT reject
        result = apply_correction(
            [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.95],
            method="bonferroni", alpha=0.05,
        )
        # Bonferroni: 0.05/10 = 0.005 — none should reject
        assert result.n_rejected == 0

    def test_mixed(self):
        # 2 strong + 8 noise → only strong reject
        pvals = [0.001, 0.005] + [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.9]
        result = apply_correction(pvals, method="bonferroni", alpha=0.05)
        assert result.n_rejected == 2

    def test_corrected_pvalues_monotone(self):
        # Bonferroni-corrected p-values should be ≥ original p-values × N
        pvals = [0.01, 0.02, 0.05]
        result = apply_correction(pvals, method="bonferroni", alpha=0.05)
        for orig, corr in zip(pvals, result.p_values_corrected):
            assert corr >= orig - 1e-9


class TestHolm:
    def test_more_powerful_than_bonferroni(self):
        pvals = [0.001, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        b = apply_correction(pvals, method="bonferroni", alpha=0.05)
        h = apply_correction(pvals, method="holm", alpha=0.05)
        # Holm should reject at least as many as Bonferroni
        assert h.n_rejected >= b.n_rejected

    def test_step_down(self):
        # Holm rejects smallest first
        pvals = [0.001, 0.5, 0.5, 0.5]
        result = apply_correction(pvals, method="holm", alpha=0.05)
        assert result.rejected[0] is True
        # Once we hit a non-reject, all subsequent must also not reject
        for r in result.rejected[1:]:
            assert r is False


class TestBH:
    def test_most_powerful(self):
        pvals = [0.001, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        b = apply_correction(pvals, method="bonferroni", alpha=0.05)
        bh = apply_correction(pvals, method="fdr_bh", alpha=0.05)
        assert bh.n_rejected >= b.n_rejected

    def test_corrected_pvalues_bounded_by_one(self):
        pvals = [0.001, 0.01, 0.05, 0.5]
        result = apply_correction(pvals, method="fdr_bh", alpha=0.05)
        for p in result.p_values_corrected:
            assert 0.0 <= p <= 1.0


class TestEdgeCases:
    def test_empty(self):
        result = apply_correction([], method="holm", alpha=0.05)
        assert result.n_tests == 0
        assert result.n_rejected == 0
        assert "empty" in result.notes.lower()

    def test_single(self):
        result = apply_correction([0.01], method="bonferroni", alpha=0.05)
        assert result.n_tests == 1
        assert result.n_rejected == 1

    def test_all_zero(self):
        # p=0 → strongly reject
        result = apply_correction([0.0, 0.0, 0.0], method="bonferroni", alpha=0.05)
        assert result.n_rejected == 3

    def test_nan_treated_as_not_rejected(self):
        pvals = [0.001, float("nan"), 0.5]
        result = apply_correction(pvals, method="holm", alpha=0.05)
        assert result.n_tests == 3
        assert result.rejected[0] is True
        assert result.rejected[1] is False  # NaN → False
        assert "NaN" in result.notes

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError):
            apply_correction([0.1, 0.2], method="unknown_method", alpha=0.05)

    def test_interpret(self):
        result = apply_correction([0.001, 0.5, 0.8], method="holm", alpha=0.05)
        msg = interpret_correction(result)
        assert isinstance(msg, str) and len(msg) > 0


class TestFWER:
    def test_bonferroni_fwer_close_to_alpha(self):
        # FWER ≤ α for small N; approaches α as N grows
        result = apply_correction([0.01] * 5, method="bonferroni", alpha=0.05)
        # 1 - (1 - 0.05/5)^5 ≈ 1 - 0.99^5 ≈ 0.049
        assert abs(result.family_wise_error - 0.049) < 0.005


if __name__ == "__main__":
    pytest.main([__file__, "-v"])