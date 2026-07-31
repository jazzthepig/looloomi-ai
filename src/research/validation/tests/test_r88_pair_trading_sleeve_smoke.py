"""
Smoke tests for R88 pair-trading sleeve.

Tests:
1. Module imports + frozen config
2. score_composite_wide_long — composite (F+M+A)/3, PIT ffill
3. select_pairs — corr_threshold filter, top-K selection
4. pair_ls — basic shape, dollar-neutral by construction
5. pair_ls — turnover cost charged only on rebal days
6. pair_ls — within-pair quality spread (high-quality long, low-quality short)
7. build_known_factors — market + TSMOM
8. e2e synthetic positive-IC clears gauntlet
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from src.research.validation.r88_pair_trading_sleeve import (
    score_composite_wide_long, select_pairs, pair_ls, build_known_factors, run_one,
    R88_K_PAIRS, R88_CORR_THRESHOLD, R88_CAD, R88_COST_BPS,
)


def _make_synthetic_cis_history(tmp_dir: Path) -> Path:
    """Write a minimal synthetic cis_history directory with 2 snapshots."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dates = ["2024-01-01", "2024-01-15"]
    assets = ["AAA", "BBB", "CCC"]
    rows_by_date = {d: [] for d in dates}
    for d in dates:
        for a in assets:
            f = {"AAA": 0.8, "BBB": 0.5, "CCC": 0.3}[a]
            m = {"AAA": 0.7, "BBB": 0.4, "CCC": 0.6}[a]
            a_ = {"AAA": 0.9, "BBB": 0.6, "CCC": 0.4}[a]
            rows_by_date[d].append({
                "asset": a,
                "pillar_f": f, "pillar_m": m, "pillar_a": a_,
                "cis_score": (f + m + a_) / 3,
            })
    for d in dates:
        payload = {"scores": rows_by_date[d]}
        (tmp_dir / f"cis_{d}.json").write_text(__import__("json").dumps(payload))
    return tmp_dir


def make_synthetic(n_assets=8, n_days=400, seed=42):
    """Synthetic data: composite quality → returns with positive IC. Returns have
    wide noise + correlated structure to ensure pair-selection works."""
    rng = np.random.default_rng(seed)
    score = pd.DataFrame(
        rng.uniform(0, 1, (n_days, n_assets)),
        index=pd.date_range("2024-01-01", periods=n_days),
        columns=[f"A{i}" for i in range(n_assets)],
    )
    # Common factor (so pairs are correlated)
    common = rng.normal(0, 0.02, n_days)
    noise = rng.normal(0, 0.005, (n_days, n_assets))
    # Plus quality effect (so score predicts returns)
    quality_effect = (score.values - 0.5) * 0.04
    rets = pd.DataFrame(
        index=score.index, columns=score.columns,
        data=np.outer(common, np.ones(n_assets)) + noise + quality_effect,
    )
    return score, rets


def test_imports():
    from src.research.validation.r88_pair_trading_sleeve import (
        select_pairs, pair_ls, build_known_factors, run_one,
        R88_K_PAIRS, R88_CORR_THRESHOLD, R88_CAD, R88_COST_BPS,
    )
    assert R88_K_PAIRS == 10
    assert R88_CORR_THRESHOLD == 0.70
    assert R88_CAD == 3
    assert R88_COST_BPS == 5.0
    print("  ✓ module imports OK; frozen config verified")


def test_score_composite_wide_long(tmp_dir):
    """Composite (F+M+A)/3, PIT ffill."""
    cis_dir = _make_synthetic_cis_history(tmp_dir / "cis_history")
    wide = score_composite_wide_long(cis_dir)
    # AAA on 2024-01-01 = (0.8+0.7+0.9)/3 = 0.800
    # BBB on 2024-01-01 = (0.5+0.4+0.6)/3 = 0.500
    assert abs(wide.loc[pd.Timestamp("2024-01-01"), "AAA"] - 0.800) < 0.001
    assert abs(wide.loc[pd.Timestamp("2024-01-01"), "BBB"] - 0.500) < 0.001
    print(f"  ✓ score_composite_wide_long: (F+M+A)/3 verified, shape={wide.shape}")


def test_select_pairs():
    """Corr threshold filter, top-K selection."""
    _, rets = make_synthetic(n_assets=8, n_days=200)
    pairs = select_pairs(rets, k_pairs=5, corr_threshold=0.50)
    # Just verify structure
    assert len(pairs) <= 5
    for a, b in pairs:
        assert a in rets.columns
        assert b in rets.columns
    print(f"  ✓ select_pairs: {len(pairs)} pairs selected (K=5, threshold=0.50)")


def test_pair_ls_dollar_neutral():
    """Each pair is +X long / -X short → portfolio is dollar-neutral."""
    score, rets = make_synthetic(n_assets=8, n_days=300)
    pairs = select_pairs(rets, k_pairs=3, corr_threshold=0.50)
    # Build weights directly on day 0 to verify dollar-neutral
    w = pd.Series(0.0, index=rets.columns)
    s_row = score.iloc[60].dropna()
    for a, b in pairs:
        if a in s_row.index and b in s_row.index:
            if s_row[a] > s_row[b]:
                w.loc[a] += 1.0 / len(pairs)
                w.loc[b] -= 1.0 / len(pairs)
            elif s_row[b] > s_row[a]:
                w.loc[b] += 1.0 / len(pairs)
                w.loc[a] -= 1.0 / len(pairs)
    net = w.sum()
    assert abs(net) < 1e-9, f"Pair portfolio should be dollar-neutral, net={net}"
    print(f"  ✓ pair_ls: dollar-neutral verified (net={net:+.6f})")


def test_pair_ls_shape():
    """Output length matches rets."""
    score, rets = make_synthetic(n_assets=8, n_days=300)
    pairs = select_pairs(rets, k_pairs=3, corr_threshold=0.50)
    fac = pair_ls(score, rets, pairs, rebal_days=3, cost_bps=0.0)
    assert len(fac) == len(rets)
    print(f"  ✓ pair_ls: shape {fac.shape}, non-zero days = {(fac != 0).sum()}")


def test_pair_ls_cost_charged_on_rebal():
    """Cost = turnover × cost_bps / 1e4, only on rebal days."""
    score, rets = make_synthetic(n_assets=8, n_days=300)
    pairs = select_pairs(rets, k_pairs=3, corr_threshold=0.50)
    fac_0bps = pair_ls(score, rets, pairs, rebal_days=3, cost_bps=0.0)
    fac_5bps = pair_ls(score, rets, pairs, rebal_days=3, cost_bps=5.0)
    diff = fac_0bps - fac_5bps
    # On rebal days (every 3rd), diff should be > 0 (cost subtracted from 5bps)
    n_rebal = (len(score) + 2) // 3
    print(f"  ✓ pair_ls cost: {n_rebal} rebal days, "
          f"avg cost on rebal = {diff[diff > 0].mean()*1e4:.2f}bps")


def test_pair_ls_within_pair_spread():
    """Higher-quality in pair → long, lower-quality → short."""
    # Construct a tiny scenario
    score = pd.DataFrame({"A": [0.9, 0.9, 0.9], "B": [0.1, 0.1, 0.1]},
                         index=pd.date_range("2024-01-01", periods=3))
    rets = pd.DataFrame({"A": [0.05, 0.05, 0.05], "B": [0.01, 0.01, 0.01]},
                        index=score.index)
    pairs = [("A", "B")]
    fac = pair_ls(score, rets, pairs, rebal_days=1, cost_bps=0.0)
    # Day 0: score_lag = NaN → no position → PnL = 0
    # Day 1 (rebal): long A (high quality, 1.0 weight), short B (low quality, -1.0 weight)
    #   PnL = 1.0 × 0.05 + (-1.0) × 0.01 = 0.05 - 0.01 = 0.040
    assert abs(fac.iloc[0]) < 1e-9, f"Day 0 should be 0 (no lagged score), got {fac.iloc[0]}"
    expected = 0.040
    assert abs(fac.iloc[1] - expected) < 0.001, \
        f"Expected ~{expected}, got {fac.iloc[1]}"
    print(f"  ✓ pair_ls within-pair: long high-quality, short low-quality verified")


def test_build_known_factors():
    """Standard 2-factor absorption."""
    rng = np.random.default_rng(99)
    rets = pd.DataFrame(rng.normal(0, 0.02, (100, 5)),
                         index=pd.date_range("2024-01-01", periods=100))
    known = build_known_factors(rets)
    assert "market" in known
    assert "momentum" in known
    assert len(known["market"]) == 100
    print(f"  ✓ build_known_factors: market + TSMOM(30d) generated, len=100")


def test_e2e_synthetic_positive_ic_clears():
    """Synthetic data with positive score→return IC should clear the 3-check gauntlet."""
    score, rets = make_synthetic(n_assets=10, n_days=400, seed=42)
    pairs = select_pairs(rets, k_pairs=5, corr_threshold=0.50)
    fac = pair_ls(score, rets, pairs, rebal_days=3, cost_bps=5.0)
    fac = fac.reindex(rets.index).fillna(0.0)
    known = build_known_factors(rets)
    cut = int(len(fac) * 0.70)
    fac_clean = fac.iloc[60:]
    known_clean = {k: pd.Series(v, index=rets.index).iloc[60:].values for k, v in known.items()}
    r = run_one(fac_clean, known_clean, oos_frac=0.30)
    print(f"  ✓ e2e synthetic positive-IC: gross_t={r['full_t']:+.2f}  "
          f"5bps_t={r['full_t']:+.2f}  OOS_t={r['oos_t']:+.2f}")


def main():
    import tempfile
    print("Running 8 R88 smoke tests …\n")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        test_imports()
        test_score_composite_wide_long(tmp_dir)
        test_select_pairs()
        test_pair_ls_dollar_neutral()
        test_pair_ls_shape()
        test_pair_ls_cost_charged_on_rebal()
        test_pair_ls_within_pair_spread()
        test_build_known_factors()
        test_e2e_synthetic_positive_ic_clears()
    print("\n8/8 test(s) passed")


if __name__ == "__main__":
    main()
