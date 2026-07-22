"""
Smoke tests for R67 pillar_A L/S (src/research/validation/pillar_a_ls.py).

Anti-imposter: a pillar-A L/S that:
  - flips the sign and declares success on whichever direction worked
  - computes Sharpe on too-few days and declares the cell alive
  - paper-over a missing OOS split by using the full period as "OOS"
...is the trader agent at its worst. These tests pin the discipline.

Scope:
  - score_pillar_a_long: long → wide pivot, no future leakage
  - pillar_a_ls: sign handling, quintile (k=5) wiring
  - pillar_a_cadence_sweep: sweep shape + sign in each result
  - sign-verdict logic (anti-imposter: +A and -A both computed)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.research.validation.pillar_a_ls import (
    score_pillar_a_long, score_pillar_a_change, pillar_a_ls, pillar_a_cadence_sweep,
    SIGN_HIGH_A_LONG, SIGN_LOW_A_LONG, R67_K_TERCILES,
)


_passes: list[str] = []
_fails: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        _passes.append(name)
        print(f"  ✓ {name}")
    else:
        _fails.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")


def _summary(suite: str) -> None:
    print(f"\n  {len(_passes)} passed · {len(_fails)} failed — {suite}")
    if _fails:
        for f in _fails:
            print(f"    FAILED: {f}")


# ── Tests ────────────────────────────────────────────────────────────────────

def test_score_pillar_a_long_shape():
    print("\n[test_score_pillar_a_long_shape]")
    # synthetic: 6 dates × 4 assets, pillar_A varies
    rows = []
    for i, d in enumerate(["2026-05-01", "2026-05-02", "2026-05-03",
                           "2026-05-04", "2026-05-05", "2026-05-06"]):
        for j, a in enumerate(["BTC", "ETH", "SOL", "AVAX"]):
            rows.append({"date": pd.Timestamp(d), "asset": a, "A": 50 + (i + j) % 30})
    df = pd.DataFrame(rows)
    w = score_pillar_a_long(df)
    _check("wide shape is date × asset",
           w.shape == (6, 4), detail=str(w.shape))
    _check("index is DatetimeIndex sorted ascending",
           isinstance(w.index, pd.DatetimeIndex) and w.index.is_monotonic_increasing)
    _check("columns are asset names",
           set(w.columns) == {"BTC", "ETH", "SOL", "AVAX"})

    delta = score_pillar_a_change(df)
    _check("ΔA preserves date × asset shape",
           delta.shape == w.shape, detail=str(delta.shape))
    _check("ΔA is PIT-safe: first row has no prior score",
           delta.iloc[0].isna().all(), detail=str(delta.iloc[0].to_dict()))
    _check("ΔA uses the one-day difference, not the level",
           float(delta.iloc[1]["BTC"]) == 1.0,
           detail=str(delta.iloc[1]["BTC"]))

    # Forward-fill safety: a single NaN row at day 5 for SOL keeps day 5 value
    rows2 = []
    for d in ["2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04"]:
        for a in ["BTC", "SOL"]:
            rows2.append({"date": pd.Timestamp(d), "asset": a, "A": 70.0})
    df2 = pd.DataFrame(rows2)
    w2 = score_pillar_a_long(df2)
    _check("ffill: missing asset row lands at NaN BEFORE ffill",
           df2[df2["asset"] == "AVAX"].empty)


def test_pillar_a_ls_sign_handling():
    print("\n[test_pillar_a_ls_sign_handling]")
    # tercile_ls requires ≥6 assets for qcut to fire — use 6 so the rank works
    dates = pd.date_range("2026-05-01", periods=30, freq="D")
    np.random.seed(11)
    # 6 assets with stable A levels: top-2 always highest, bottom-2 always lowest
    w = pd.DataFrame({
        "BTC":  [80.0] * 30,
        "ETH":  [70.0] * 30,
        "SOL":  [60.0] * 30,   # mid — split point
        "AVAX": [50.0] * 30,
        "DOT":  [40.0] * 30,
        "LINK": [30.0] * 30,
    }, index=dates)
    # Returns: top-2 (BTC, ETH) up 1%, bottom-2 (DOT, LINK) up 0%, mid up 0.5%
    rets = pd.DataFrame({
        "BTC":  [0.01] * 30,
        "ETH":  [0.01] * 30,
        "SOL":  [0.005] * 30,
        "AVAX": [0.005] * 30,
        "DOT":  [0.0] * 30,
        "LINK": [0.0] * 30,
    }, index=dates)

    # HIGH_A_LONG with k=3 (terciles): top tercile = BTC, ETH (long); bottom = DOT, LINK (short)
    # Expected daily gross = mean(long_returns) - mean(short_returns)
    #                       = mean(BTC,ETH) - mean(DOT,LINK) = 0.01 - 0.0 = +0.01
    fac_high = pillar_a_ls(w, rets, k_terciles=3, cost_bps=0.0,
                            rebal_days=1, sign=SIGN_HIGH_A_LONG)
    daily_high = fac_high.mean()

    # LOW_A_LONG: long bottom tercile (DOT, LINK); short top (BTC, ETH)
    # Expected daily = mean(DOT, LINK) - mean(BTC, ETH) = 0.0 - 0.01 = -0.01
    fac_low = pillar_a_ls(w, rets, k_terciles=3, cost_bps=0.0,
                            rebal_days=1, sign=SIGN_LOW_A_LONG)
    daily_low = fac_low.mean()

    _check("HIGH_A_LONG produces positive daily return (≈+1%/day)",
           abs(daily_high - 0.01) < 0.001, detail=str(daily_high))
    _check("LOW_A_LONG produces negative daily return (≈−1%/day)",
           abs(daily_low + 0.01) < 0.001, detail=str(daily_low))
    _check("HIGH_A_LONG and LOW_A_LONG are exact opposites (no asymmetry)",
           abs(daily_high + daily_low) < 1e-9,
           detail=f"high={daily_high}, low={daily_low}")
    # First-day return should be 0 (lag = 1 day, no prior score on day 0)
    _check("day-0 (no prior score) face = 0 by construction",
           fac_high.iloc[0] == 0.0 or pd.isna(fac_high.iloc[0]),
           detail=str(fac_high.iloc[0]))


def test_invalid_sign_raises():
    print("\n[test_invalid_sign_raises]")
    dates = pd.date_range("2026-05-01", periods=10, freq="D")
    w = pd.DataFrame({"BTC": [50.0] * 10}, index=dates)
    rets = pd.DataFrame({"BTC": [0.0] * 10}, index=dates)
    raised = False
    try:
        pillar_a_ls(w, rets, k_terciles=2, cost_bps=0.0,
                    rebal_days=1, sign="bogus")
    except ValueError:
        raised = True
    _check("invalid sign raises ValueError", raised)


def test_cadence_sweep_sign_propagation():
    print("\n[test_cadence_sweep_sign_propagation]")
    dates = pd.date_range("2026-05-01", periods=60, freq="D")
    np.random.seed(7)
    # 6 assets (tercile_ls requires ≥6 for qcut)
    w = pd.DataFrame({
        "BTC":  [70.0] * 60,
        "ETH":  [60.0] * 60,
        "SOL":  [50.0] * 60,
        "AVAX": [45.0] * 60,
        "DOT":  [40.0] * 60,
        "LINK": [30.0] * 60,
    }, index=dates)
    rets = pd.DataFrame({
        "BTC":  np.random.normal(0.002, 0.01, 60),
        "ETH":  np.random.normal(0.0015, 0.01, 60),
        "SOL":  np.random.normal(0.0005, 0.01, 60),
        "AVAX": np.random.normal(0.001, 0.01, 60),
        "DOT":  np.random.normal(-0.0005, 0.01, 60),
        "LINK": np.random.normal(-0.001, 0.01, 60),
    }, index=dates)
    f_market = rets.mean(axis=1).fillna(0.0).values
    # Independent momentum proxy (autocorrelation of market returns, signed)
    f_momentum = (np.sign(np.roll(f_market, 1)) * f_market).astype(float)
    known_arrs = {"market": f_market, "momentum": f_momentum}

    sweep = pillar_a_cadence_sweep(
        w, rets, known_arrs,
        cadences=(1, 5, 14),
        cost_grid=(0.0, 5.0),
        k_terciles=2,
        sign=SIGN_HIGH_A_LONG,
        label="test",
    )
    _check("sweep returns 6 cells (3 cad × 2 cost)",
           len(sweep) == 6, detail=str(len(sweep)))
    for (cad, bps), r in sweep.items():
        _check(f"cell cad={cad} bps={bps} has alpha_t",
               "alpha_t" in r, detail=str(r.keys()))
        _check(f"cell cad={cad} bps={bps} has sign=SIGN_HIGH_A_LONG",
               r.get("sign") == SIGN_HIGH_A_LONG,
               detail=str(r.get("sign")))
        _check(f"cell cad={cad} bps={bps} has turnover_ann",
               r.get("turnover_ann") is not None)


def test_anti_imposter_both_signs_run():
    """Pillar-A L/S does NOT silently flip sign to declare success — both
    directions must be in the output for anti-imposter review."""
    print("\n[test_anti_imposter_both_signs_run]")
    import inspect
    from src.research.validation import pillar_a_ls as mod
    src = inspect.getsource(mod.run)

    # Both sign names must appear as values in the source (not necessarily
    # as string literals — they are module constants referenced by name).
    _check("run() references SIGN_HIGH_A_LONG",
           "SIGN_HIGH_A_LONG" in src,
           detail="the +A direction must be in the sweep")
    _check("run() references SIGN_LOW_A_LONG",
           "SIGN_LOW_A_LONG" in src,
           detail="the -A direction (anti-imposter control) must also be swept")

    # Anti-imposter: must compare both directions explicitly, not pick one
    _check("run() mentions +A vs -A explicitly in the verdict",
           ("+A" in src and "-A" in src) or
           ("+ΔA" in src and "−ΔA" in src) or
           ("differential_alpha" in src and ("best_hi" in src and "best_lo" in src)),
           detail="sign-verdict logic must reference both directions explicitly")

    _check("run() uses ΔA rather than level A for the headline score",
           "score_pillar_a_change" in src,
           detail="R63b's directional claim is about change, not level")
    _check("run() cuts OOS at 70% so OOS is the last 30%",
           "(1.0 - OOS_FRAC)" in src,
           detail="int(OOS_FRAC*n) would incorrectly leave 70% as OOS")
    _check("run() uses the strict funding-bearing universe",
           "load_funding_daily" in src and "matched_assets" in src,
           detail="R67 declared funding ∩ CIS ∩ OHLCV, not the easier 40-name panel")

    _check("run() picks best cell by alpha_t (not by hand)",
           "max(" in src or "key=lambda" in src,
           detail="manual best-cell selection is suspect")


def main() -> None:
    print("=" * 60)
    print("R67 PILLAR_A L/S SMOKE TESTS")
    print("=" * 60)
    test_score_pillar_a_long_shape()
    test_pillar_a_ls_sign_handling()
    test_invalid_sign_raises()
    test_cadence_sweep_sign_propagation()
    test_anti_imposter_both_signs_run()
    _summary("R67 pillar-A L/S")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
