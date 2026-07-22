"""
Regime-Robustness gate — is the edge broad, or a one-window mirage? (Seth, 2026-07-18).
========================================================================================
Absorption catches BETA (repackaged known premia). It does NOT catch an edge that is real-looking
but CONCENTRATED in a single friendly regime — Minimax-B's exact warning on the +1.97 composite
("2nd-half Sharpe 2× the 1st, current regime favorable"). The Google/academia factor study ran the
same filter ("subsample robustness, post-2010") and it killed ~half the survivors.

This gate splits a return series by regime label (or into N time-folds) and asks:
  · does the edge stay POSITIVE across (most) subsamples, or flip sign somewhere?
  · how CONCENTRATED is the PnL — does one window carry most of the gains (fragile)?
  · what's the WORST subsample Sharpe (the drawdown-regime read)?

A signal that only earns in one regime is a bet on that regime persisting, not an edge. Compliance:
research/validation tooling.
"""
from __future__ import annotations

import numpy as np


def subsample_robustness(returns, labels=None, n_folds: int = 4, periods_per_year: int = 365,
                         concentration_flag: float = 0.60, min_obs: int = 20) -> dict:
    """returns: 1d return series. labels: optional per-period regime label (same length) — if given,
    groups by regime; else splits chronologically into `n_folds`. Flags concentration + sign-flips."""
    r = np.asarray(returns, dtype=float)
    keep = ~np.isnan(r)
    r = r[keep]
    n = len(r)
    if n < min_obs * 2:
        return {"gate": "regime_robustness", "passed": False, "verdict": "INSUFFICIENT DATA", "n": n}

    if labels is not None:
        lab = np.asarray(labels)[keep][:n]
        groups = {str(g): r[lab == g] for g in sorted(set(lab.tolist()))}
        mode = "regime"
    else:
        groups = {f"fold{i+1}": chunk for i, chunk in enumerate(np.array_split(r, n_folds))}
        mode = f"{n_folds}-fold chronological"

    total = float(r.sum())
    rows = {}
    for g, rr in groups.items():
        if len(rr) < min_obs:
            rows[g] = {"n": int(len(rr)), "note": "too few obs"}
            continue
        sd = rr.std()
        rows[g] = {
            "n": int(len(rr)),
            "sharpe": round(float(rr.mean() / sd * np.sqrt(periods_per_year)), 2) if sd > 0 else 0.0,
            "mean_bps": round(float(rr.mean() * 1e4), 2),
            "pnl_share": round(float(rr.sum() / total), 3) if total != 0 else None,
            "positive": bool(rr.mean() > 0),
        }
    valid = {g: v for g, v in rows.items() if "sharpe" in v}
    if not valid:
        return {"gate": "regime_robustness", "passed": False, "verdict": "INSUFFICIENT DATA", "n": n}

    n_pos = sum(1 for v in valid.values() if v["positive"])
    worst_sharpe = min(v["sharpe"] for v in valid.values())
    # concentration = the single best group's share of total POSITIVE pnl
    pos_pnls = [float(groups[g].sum()) for g, v in valid.items() if groups[g].sum() > 0]
    concentration = round(max(pos_pnls) / sum(pos_pnls), 3) if pos_pnls else None

    # chronological half-split — the "2nd-half Sharpe 2× the 1st, favorable regime" tell (Minimax-B)
    def _sh(x):
        return round(float(x.mean() / x.std() * np.sqrt(periods_per_year)), 2) if x.std() > 0 else 0.0
    half = n // 2
    s1, s2 = _sh(r[:half]), _sh(r[half:])
    recent_ratio = round(s2 / s1, 2) if s1 > 0.10 else None
    regime_dependent = (s1 <= 0 < s2) or (recent_ratio is not None and recent_ratio > 2.5)

    concentrated = concentration is not None and concentration > concentration_flag
    sign_stable = n_pos == len(valid)
    passed = sign_stable and not concentrated and not regime_dependent and worst_sharpe > 0

    if passed:
        verdict = "ROBUST — edge positive across all subsamples and both halves, not concentrated."
    elif not sign_stable:
        verdict = f"FRAGILE — edge flips sign ({n_pos}/{len(valid)} subsamples positive); not regime-robust."
    elif regime_dependent:
        verdict = (f"REGIME-DEPENDENT — edge concentrated in the recent/favorable window "
                   f"(2nd-half Sharpe {s2} vs 1st-half {s1}); a bet on the regime persisting, not a robust edge.")
    elif concentrated:
        verdict = f"CONCENTRATED — {int(concentration*100)}% of gains from one window; likely a regime mirage, not an edge."
    else:
        verdict = f"WEAK — worst-subsample Sharpe {worst_sharpe:+.2f}; edge thin in an adverse regime."

    return {"gate": "regime_robustness", "mode": mode, "n": n,
            "n_subsamples": len(valid), "n_positive": n_pos,
            "concentration": concentration, "worst_subsample_sharpe": worst_sharpe,
            "first_half_sharpe": s1, "second_half_sharpe": s2, "recent_ratio": recent_ratio,
            "by_subsample": rows, "passed": passed, "verdict": verdict}


if __name__ == "__main__":
    import json
    rng = np.random.default_rng(3)
    # (a) MIRAGE: ~flat first half, strong second half (Minimax-B's +1.97 shape)
    mirage = np.concatenate([rng.normal(0.0001, 0.01, 500), rng.normal(0.0025, 0.01, 500)])
    # (b) ROBUST: consistent small edge throughout
    robust = rng.normal(0.0009, 0.01, 1000)
    print("MIRAGE signal (friendly-window):")
    print(json.dumps({k: v for k, v in subsample_robustness(mirage).items() if k != "by_subsample"}, indent=2))
    print("\nROBUST signal (broad edge):")
    print(json.dumps({k: v for k, v in subsample_robustness(robust).items() if k != "by_subsample"}, indent=2))
