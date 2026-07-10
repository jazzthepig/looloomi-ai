"""
Correlation-aware strategy combiner + effective-number-of-bets (Seth, 2026-07-10).
==================================================================================

The DSR audit showed our 5 certified strategies are 0.67 mutually correlated —
~1.5 real ideas in 5 costumes. Equal-weight / inverse-vol blends then UNDERPERFORM
the best single, because they treat redundant strategies as if they diversified.

This module fixes both halves:
  1. `effective_number_of_bets` — a redundancy X-ray. Entropy of the correlation
     matrix's eigen-spectrum. K identical strategies → ENB≈1; K uncorrelated → ENB≈K.
     Would have flagged "5 strategies, ENB≈1.6" instantly.
  2. `combine` — inverse-variance weights DE-DUPLICATED by correlation (a poor-man's
     HRP): each strategy's weight is penalized by how much of it is already carried by
     the others. In-sample Markowitz is deliberately avoided — it is famously unstable
     out-of-sample (López de Prado). This is robust, monotone, and needs no optimizer.

Pure numpy. Input: a dict {name: daily_return_series} or an aligned T×K matrix.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np


def _align(returns_by_strategy: dict[str, dict]) -> tuple[list[str], np.ndarray]:
    """{name: {date: ret}} → (names, T×K matrix), 0-filled on flat days."""
    names = sorted(returns_by_strategy)
    dates = sorted(set().union(*[set(returns_by_strategy[n]) for n in names]))
    M = np.array([[returns_by_strategy[n].get(d, 0.0) for n in names] for d in dates])
    return names, M


def effective_number_of_bets(M: np.ndarray) -> float:
    """Entropy-based effective number of independent bets from a T×K return matrix.
    ENB = exp(-Σ p_i ln p_i) where p_i = eigenvalue_i / Σ eigenvalues of the corr matrix."""
    if M.shape[1] < 2:
        return float(M.shape[1])
    C = np.corrcoef(M.T)
    C = np.nan_to_num(C, nan=0.0)
    ev = np.linalg.eigvalsh(C)
    ev = np.clip(ev, 1e-12, None)
    p = ev / ev.sum()
    entropy = -np.sum(p * np.log(p))
    return float(np.exp(entropy))


@dataclass
class CombineResult:
    names: list[str]
    weights: dict[str, float]
    enb: float                     # effective number of bets (redundancy X-ray)
    port_sharpe_ann: float         # combined annualized Sharpe
    best_single_ann: float         # best single-strategy annualized Sharpe
    uplift: float                  # port - best_single


def _ann_sharpe(r: np.ndarray, periods: int = 365) -> float:
    sd = r.std(ddof=1)
    return float(r.mean() / sd * np.sqrt(periods)) if sd > 0 else 0.0


def combine(returns_by_strategy: dict[str, dict], *, periods: int = 365) -> CombineResult:
    """Correlation-de-duplicated inverse-variance weights + diagnostics."""
    names, M = _align(returns_by_strategy)
    K = len(names)
    var = M.var(0, ddof=1)
    var[var == 0] = 1e18
    C = np.nan_to_num(np.corrcoef(M.T), nan=0.0)
    if K == 1:
        C = np.array([[1.0]])
    # redundancy penalty: sum of |corr| a strategy shares with the book (incl. self=1).
    redundancy = np.abs(C).sum(axis=1)              # ≈1 if orthogonal, ≈K if a clone-cluster
    raw = (1.0 / var) / redundancy                  # inverse-variance, de-duplicated
    w = raw / raw.sum()
    port = M @ w
    singles = [_ann_sharpe(M[:, i], periods) for i in range(K)]
    best_i = int(np.argmax(singles))
    port_sh = _ann_sharpe(port, periods)
    return CombineResult(
        names=names,
        weights={n: round(float(wi), 4) for n, wi in zip(names, w)},
        enb=round(effective_number_of_bets(M), 2),
        port_sharpe_ann=round(port_sh, 2),
        best_single_ann=round(singles[best_i], 2),
        uplift=round(port_sh - singles[best_i], 2),
    )


# ── Self-test ────────────────────────────────────────────────────────────────

def _selftest() -> int:
    rng = np.random.default_rng(3)
    T = 800
    base = rng.normal(0.001, 0.01, T)
    # 4 near-clones of `base` + 1 truly orthogonal modest sleeve
    strat = {}
    for i in range(4):
        strat[f"swingclone_{i}"] = {d: float(v) for d, v in
                                    enumerate(base + rng.normal(0, 0.002, T))}
    strat["orthogonal"] = {d: float(v) for d, v in
                           enumerate(rng.normal(0.0007, 0.01, T))}
    _, M = _align(strat)
    enb = effective_number_of_bets(M)
    res = combine(strat)
    print(f"[SELFTEST] 4 clones + 1 orthogonal → ENB = {enb:.2f} (should be ~2, not 5)")
    print(f"[SELFTEST] weights: {res.weights}")
    wc = np.mean([res.weights[f'swingclone_{i}'] for i in range(4)])
    print(f"[SELFTEST] orthogonal weight {res.weights['orthogonal']:.3f} vs avg clone {wc:.3f}")
    assert res.weights["orthogonal"] > wc, "orthogonal sleeve must be up-weighted vs clones"
    assert enb < 3.0, "ENB must expose the redundancy (4 clones ≈ 1 bet)"
    print("[SELFTEST] combiner up-weights the uncorrelated sleeve + ENB flags redundancy. ✅")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
