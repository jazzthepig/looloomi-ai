"""
Probability of Backtest Overfitting (PBO) via CSCV — Bailey, Borwein, López de Prado, Zhu.
==========================================================================================

The industry metric we were missing. DSR corrects a SINGLE strategy's Sharpe for the number of
trials; PBO asks a different, deeper question about the SELECTION PROCESS itself: when we pick
the in-sample-best signal from our library, how often is it below-median out-of-sample? That is
the probability our whole nucleus-selection is fishing noise.

CSCV (Combinatorially Symmetric Cross-Validation): split the timeline into S even blocks; for
every way to choose S/2 blocks as IS (the rest OOS), find the IS-best strategy and record its
OOS rank. PBO = fraction of splits where the IS-champion lands below the OOS median. Rule of
thumb: PBO < 0.5 means the selection has signal; a good process is well under that.

Reference: Bailey, Borwein, López de Prado, Zhu — "The Probability of Backtest Overfitting"
(SSRN 2326253). Pure numpy + itertools.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np


def _sharpe(x: np.ndarray) -> np.ndarray:
    mu = x.mean(0); sd = x.std(0)
    return np.where(sd > 0, mu / sd, 0.0)


def pbo_cscv(R: np.ndarray, S: int = 10) -> dict:
    """R: T×N matrix of N candidate strategies' return series. Returns PBO + diagnostics.
    S must be even; C(S, S/2) combinatorial IS/OOS splits."""
    T, N = R.shape
    if N < 2 or T < 2 * S:
        return {"pbo": None, "reason": "insufficient data", "n_strategies": N, "T": T}
    if S % 2:
        S += 1
    blocks = np.array_split(np.arange(T), S)
    logits = []
    oos_rank_of_is_best = []
    for is_combo in combinations(range(S), S // 2):
        is_rows = np.concatenate([blocks[b] for b in is_combo])
        oos_rows = np.concatenate([blocks[b] for b in range(S) if b not in is_combo])
        is_sr = _sharpe(R[is_rows])
        oos_sr = _sharpe(R[oos_rows])
        n_star = int(np.argmax(is_sr))                 # IS champion
        # relative OOS rank of the IS champion in (0,1): fraction of strategies it beats OOS
        rank = float((oos_sr < oos_sr[n_star]).sum()) / (N - 1)
        oos_rank_of_is_best.append(rank)
        w = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(np.log(w / (1 - w)))
    logits = np.array(logits)
    pbo = float((logits <= 0).mean())                  # IS-champion below OOS median
    return {"pbo": round(pbo, 3), "n_splits": len(logits), "n_strategies": N, "S": S,
            "median_oos_rank_of_is_champion": round(float(np.median(oos_rank_of_is_best)), 3),
            "verdict": ("selection has real OOS signal" if pbo < 0.3 else
                        "selection partly overfit" if pbo < 0.5 else
                        "selection is overfitting — IS-best is a coin flip OOS")}


def _selftest() -> int:
    rng = np.random.default_rng(0)
    T = 1000
    # one genuine edge + many noise strategies → PBO should be LOW (the real one wins IS & OOS)
    real = rng.normal(0.0008, 0.01, T)
    noise = rng.normal(0.0, 0.01, (T, 20))
    R_good = np.column_stack([real, noise])
    # all noise → PBO should be HIGH (IS-best is random OOS)
    R_bad = rng.normal(0.0, 0.01, (T, 21))
    print("genuine-edge library PBO:", pbo_cscv(R_good)["pbo"], "(expect low)")
    print("all-noise library  PBO:", pbo_cscv(R_bad)["pbo"], "(expect ~0.5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
