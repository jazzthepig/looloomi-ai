"""
Multiple-testing correction for strategy families.

Implements gate 5 of STRATEGY_VALIDATION.md. When you test N strategy
variants (e.g. all LS-V4 parameter sweeps) on the same data, the chance
of at least one false positive is much higher than the nominal alpha.
This module applies standard corrections:

- Bonferroni: divide alpha by N (most conservative).
- Holm-Bonferroni: step-down, less conservative than Bonferroni, still
  controls family-wise error rate.
- Benjamini-Hochberg FDR: controls the EXPECTED PROPORTION of false
  discoveries among rejected hypotheses; less conservative, more powerful.

For strategy research, BH-FDR is usually the right choice — you want to
find the real alphas, not be paralyzed by the strictest test. Holm is a
good middle ground.

Usage:
    result = apply_correction([0.001, 0.01, 0.04, 0.05, 0.2],
                              method="holm", alpha=0.05)
    for var, p, rej in zip(variant_names, result.p_values, result.rejected):
        print(f"{var}: p={p:.4f}  rejected={rej}")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
from statsmodels.stats.multitest import multipletests


@dataclass
class CorrectionResult:
    """Result of applying multiple-testing correction to a family of variants."""
    method: str
    alpha: float
    p_values: list[float]           # original p-values (echoed back)
    p_values_corrected: list[float] # corrected p-values
    rejected: list[bool]            # True where H0 (alpha=0) is rejected
    n_tests: int
    n_rejected: int                 # count of rejected variants
    family_wise_error: float        # worst-case FWER at this alpha (1 - (1-alpha)^n for Bonferroni)
    notes: str = ""

    def summary(self) -> str:
        return (
            f"{self.method} α={self.alpha}: "
            f"{self.n_rejected}/{self.n_tests} rejected  "
            f"(FWER ~ {self.family_wise_error:.3f})"
        )


def apply_correction(
    p_values: Sequence[float],
    method: str = "holm",
    alpha: float = 0.05,
    labels: Optional[Sequence[str]] = None,
) -> CorrectionResult:
    """Apply multiple-testing correction to a list of p-values.

    Args:
        p_values: one p-value per variant (e.g. Sharpe ratio t-test p-values).
        method: one of "bonferroni", "holm", "fdr_bh", "fdr_by", "sidak".
        alpha: significance level (default 0.05).
        labels: optional variant names for reporting.

    Returns:
        CorrectionResult with corrected p-values + rejection mask.
    """
    method = method.lower()
    valid_methods = {"bonferroni", "holm", "fdr_bh", "fdr_by", "sidak", "holm-sidak"}
    if method not in valid_methods:
        raise ValueError(f"unknown method {method!r}; valid: {sorted(valid_methods)}")

    p = np.asarray(p_values, dtype=float)
    n = len(p)

    # statsmodels handles NaN by passing them through rejected=False,
    # but we want to fail loudly if a caller passed garbage.
    if n == 0:
        return CorrectionResult(
            method=method, alpha=alpha, p_values=[], p_values_corrected=[],
            rejected=[], n_tests=0, n_rejected=0, family_wise_error=0.0,
            notes="empty input",
        )

    # Drop NaN before correction; warn via notes
    nan_mask = np.isnan(p)
    n_nan = int(nan_mask.sum())
    p_clean = p[~nan_mask]
    if len(p_clean) == 0:
        return CorrectionResult(
            method=method, alpha=alpha, p_values=list(p), p_values_corrected=list(p),
            rejected=[False] * n, n_tests=n, n_rejected=0, family_wise_error=0.0,
            notes=f"all {n_nan} p-values are NaN — no test possible",
        )

    # Apply correction via statsmodels
    reject, p_corrected, _, _ = multipletests(
        p_clean, alpha=alpha, method=method,
    )

    # Pad rejected/corrected back to original length (NaN positions → False/NaN)
    full_rejected = [False] * n
    full_corrected = list(p)
    clean_idx = 0
    for i in range(n):
        if nan_mask[i]:
            continue
        full_rejected[i] = bool(reject[clean_idx])
        full_corrected[i] = float(p_corrected[clean_idx])
        clean_idx += 1

    # Estimate family-wise error rate (Bonferroni-like upper bound)
    if method in ("bonferroni", "holm"):
        # FWER ≤ 1 - (1 - alpha/n)^n  for Bonferroni
        fwer = 1.0 - (1.0 - alpha / max(n, 1)) ** n
    elif method == "fdr_bh":
        # BH controls FDR at α — under independence, E[V/R] ≤ α
        fwer = alpha
    else:
        fwer = alpha

    notes_parts: list[str] = []
    if n_nan > 0:
        notes_parts.append(f"{n_nan} NaN p-value(s) treated as non-rejected")
    notes = "; ".join(notes_parts)

    return CorrectionResult(
        method=method, alpha=alpha,
        p_values=list(p),
        p_values_corrected=full_corrected,
        rejected=full_rejected,
        n_tests=n,
        n_rejected=int(sum(full_rejected)),
        family_wise_error=fwer,
        notes=notes,
    )


def interpret_correction(result: CorrectionResult) -> str:
    """One-line human interpretation of a correction result.

    `n_rejected` counts variants where the null was rejected (i.e., the test
    FAILED to survive correction). `n_survived` is the complement.
    """
    if result.n_tests == 0:
        return "no tests performed"
    n_survived = result.n_tests - result.n_rejected
    if result.n_rejected == 0:
        return (
            f"all {result.n_tests} variant(s) survive {result.method.upper()} "
            f"at α={result.alpha} — robust family"
        )
    if result.n_rejected == result.n_tests:
        return (
            f"no variant survives {result.method.upper()} at α={result.alpha} — "
            f"all signals are likely noise or shared data leakage"
        )
    return (
        f"{n_survived}/{result.n_tests} variant(s) survive {result.method.upper()} "
        f"at α={result.alpha}; {result.n_rejected} rejected"
    )


# ── Self-test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Synthetic 10-variant family: 3 real signals, 7 noise
    rng = np.random.default_rng(42)
    p_real = [0.001, 0.005, 0.02]   # 3 real alphas
    p_noise = list(rng.uniform(0.05, 0.95, size=7))
    p_all = p_real + p_noise
    labels = [f"real_{i}" for i in range(3)] + [f"noise_{i}" for i in range(7)]

    for method in ["bonferroni", "holm", "fdr_bh"]:
        result = apply_correction(p_all, method=method, alpha=0.05, labels=labels)
        print(f"\n=== {method.upper()} (α=0.05) ===")
        print(result.summary())
        print(interpret_correction(result))
        print("Per-variant:")
        for lbl, p, p_c, r in zip(labels, p_all, result.p_values_corrected, result.rejected):
            mark = "✓" if r else "·"
            print(f"  {mark} {lbl:<12} p={p:.4f}  p_corr={p_c:.4f}")