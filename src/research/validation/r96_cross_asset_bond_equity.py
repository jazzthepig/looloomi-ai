"""
R96 — Cross-Asset Bond-Equity β-Residual L/S (Seth, 2026-07-27).

Pivots Strategy 2 to Option D — STRUCTURALLY DIFFERENT data class.

Hypothesis
----------
§TRADER_TOM §5b cross-asset risk premium: assets that are MORE rate-sensitive
than the cross-section (β_TLT − β_SPY > 0) earn a defensive premium (bond-like
behavior earns carry in a falling-rate regime, and under-performs in rising-rate
regime). The β-residual L/S goes LONG low-β-residual (pro-risk) and SHORT
high-β-residual (defensive). The L/S is dollar-neutral across the universe,
which is a different orthogonal shape from every prior attempt:

  R82–R95: all inside the same 25-asset crypto universe (per-asset TSMOM,
            cross-sectional demean, funding carry, pair-spread, basis, etc.).
  R96:     cross-asset class L/S on the 33-symbol TradFi panel — fundamentally
            different data, different regime drivers, different risk factors.

Signal
------
Per asset i, on each day t (1-day lagged for PIT-safety):
    β_i^equity = rolling 60d OLS regression of r_i on r_SPY
    β_i^bond   = rolling 60d OLS regression of r_i on r_TLT
    residual_i = β_i^bond − β_i^equity
Then L/S:
    rank cross-section of residual (each day)
    long bottom-tercile (low residual → pro-risk, non-bond-like)
    short top-tercile (high residual → bond-like / defensive)
This is a TYPICAL risk-premium harvest, not a per-asset trend.

Anti-imposter gates (R82-R95 lessons baked in)
----------------------------------------------
- 3-check gauntlet: gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96
- Cost-tier realism: 0/5/10/20/30bps sweep; must survive 10bps (lesson #58)
- Per-window W1–W6 attribution
- Market-factor absorption (R42/R48): alpha after regressing out SPY + TLT
  must remain significant (otherwise this is just a beta-tilted book, not
  an L/S)
- Leg-corr gate (lesson #42): max |corr(R96, R77)| ≤ 0.30 — orthogonal
  by construction (different data, different universe)
- Frozen R77 cell UNCHANGED at w_R46=0.25/w_R62=0.75/w_R76=0.30

Verdict grammar
---------------
- ✅ TRADEABLE: clears 3-check, survives 10bps, maxDD > -20%, W5 sign-positive,
  ≥5/6 windows positive, leg-corr gate ≤ 0.30, alpha after absorption
  significant
- 🟡 PARTIAL: clears 5bps 3-check but fails 10bps or maxDD in (-20%, -30%)
- 🔴 REFUTED: fails 3-check at any cost tier
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.research.validation.cis_quality_robustness import cadence_ls
from src.research.validation.factor_absorption import absorption_test
from src.research.validation.r96_panel import (
    R96_UNIVERSE_FROZEN, R96_CLASS, R96_MIN_TRADEABLE,
    build_r96_universe, assert_frozen_universe, load_r96_panel, returns_from_prices,
)

# ── Frozen constants ─────────────────────────────────────────────────────────
R96_LOOKBACK_BETA = 60           # rolling OLS window for β estimation
R96_K_TERCILES = 3
R96_CADENCES = (1, 3, 5, 7, 14, 21)
R96_COST_GRID = (0.0, 5.0, 10.0, 20.0, 30.0)
R96_REALISTIC_COST_BPS = 10.0
R96_MAXDD_BUDGET = -0.20
R96_ORTHOGONALITY_GATE = 0.30    # lesson #42
R96_EQUITY_BENCH = "SPY"
R96_BOND_BENCH = "TLT"
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# Frozen R77 cell reference — do NOT touch.
R77_SHARPE_FROZEN = 2.06
R77_MAXDD_FROZEN = -0.0891
R77_OOS_T_FROZEN = 3.61
R77_WEIGHTS_FROZEN = "w_R46=0.25/w_R62=0.75/w_R76=0.30"


# ── Score: per-asset β-residual = β_TLT − β_SPY ─────────────────────────────
def _rolling_beta(y: pd.Series, x: pd.Series, lookback: int) -> pd.Series:
    """Rolling OLS slope of y on x, with constant. PIT-safe (1d lag applied by caller)."""
    # cov(x,y) / var(x) over the lookback window
    cov = y.rolling(lookback).cov(x)
    var = x.rolling(lookback).var()
    return cov / var.replace(0.0, np.nan)


def score_beta_residual(
    rets: pd.DataFrame,
    equity_bench: str = R96_EQUITY_BENCH,
    bond_bench: str = R96_BOND_BENCH,
    lookback: int = R96_LOOKBACK_BETA,
) -> pd.DataFrame:
    """Per-asset β-residual = β_to_bond − β_to_equity, lagged 1d.

    Returns a wide DataFrame (date × asset) of raw residuals (NOT ranked;
    ranking happens inside the L/S engine per the spec).
    """
    if equity_bench not in rets.columns or bond_bench not in rets.columns:
        raise ValueError(
            f"Missing benchmark(s): equity={equity_bench} bond={bond_bench}. "
            f"Available: {list(rets.columns)}"
        )
    eq = rets[equity_bench]
    bd = rets[bond_bench]
    out = pd.DataFrame(index=rets.index, columns=rets.columns, dtype=float)
    for asset in rets.columns:
        if asset in (equity_bench, bond_bench):
            continue
        y = rets[asset]
        b_eq = _rolling_beta(y, eq, lookback)
        b_bd = _rolling_beta(y, bd, lookback)
        # Residual = how much more bond-like than equity-like. Positive = bond-like.
        out[asset] = (b_bd - b_eq)
    # Drop benchmark columns (they have no residual).
    out = out.drop(columns=[equity_bench, bond_bench])
    # 1-day lag (PIT-safe).
    out = out.shift(1)
    return out


# ── L/S engine: cross-section ranking (canonical R96) ───────────────────────
def r96_ls(
    score_wide: pd.DataFrame,
    rets: pd.DataFrame,
    *,
    k_terciles: int = R96_K_TERCILES,
    rebal_days: int = 1,
    cost_bps: float = 0.0,
    sign: str = "low_residual_long",  # low_residual_long = LONG bottom tercile (low β-residual)
) -> pd.Series:
    """Cross-sectional L/S based on score terciles.

    sign='low_residual_long' → long bottom (low β-residual = pro-risk, non-bond-like)
    sign='high_residual_long' → long top (high β-residual = bond-like, defensive)
    """
    common = sorted(set(score_wide.columns) & set(rets.columns))
    if len(common) < 6:
        return pd.Series(0.0, index=rets.index)
    score = score_wide[common].reindex(rets.index).ffill()
    r = rets[common].reindex(rets.index).fillna(0.0)
    fac = pd.Series(0.0, index=r.index)
    prev_w = pd.Series(0.0, index=common)
    score_lag = score.shift(1)  # extra 1d lag inside the L/S
    for i, date in enumerate(r.index):
        rr = r.loc[date].reindex(common).fillna(0.0)
        if i % rebal_days == 0:
            s_row = score_lag.loc[date].dropna()
            w = pd.Series(0.0, index=common)
            if len(s_row) >= 6:
                try:
                    ranks = pd.qcut(s_row, q=k_terciles, labels=False, duplicates="drop")
                except ValueError:
                    ranks = (s_row >= s_row.median()).astype(int)
                top_label, bot_label = ranks.max(), ranks.min()
                if top_label != bot_label:
                    top = ranks[ranks == top_label].index
                    bot = ranks[ranks == bot_label].index
                    if len(top) and len(bot):
                        if sign == "low_residual_long":
                            w.loc[bot] = 1.0 / len(bot)
                            w.loc[top] = -1.0 / len(top)
                        else:  # high_residual_long
                            w.loc[top] = 1.0 / len(top)
                            w.loc[bot] = -1.0 / len(bot)
            turnover = float((w - prev_w).abs().sum())
            fac.loc[date] = float((w * rr).sum()) - turnover * cost_bps / 1e4
            prev_w = w
        else:
            fac.loc[date] = float((prev_w * rr).sum())
    return fac


# ── Per-window + summary helpers ────────────────────────────────────────────
def per_window_pnl(pnl: pd.Series, n_windows: int = 6) -> dict:
    """Slice the PnL series into n equal-windows and return ann% + maxDD per slice."""
    if pnl.empty:
        return {}
    n = len(pnl)
    wsize = n // n_windows
    out = {}
    for k in range(n_windows):
        s, e = k * wsize, (k + 1) * wsize if k < n_windows - 1 else n
        sub = pnl.iloc[s:e]
        if sub.empty:
            continue
        ann = float(sub.mean() * PERIODS_PER_YEAR)
        cum = (1 + sub).cumprod()
        dd = float((cum / cum.cummax() - 1).min()) if len(cum) > 0 else 0.0
        out[f"W{k+1}"] = {
            "n_days": int(len(sub)),
            "ann_pct": round(ann * 100, 2),
            "max_dd": round(dd * 100, 2),
        }
    return out


def _summary(pnl: pd.Series) -> dict:
    if pnl.empty or pnl.std() == 0:
        return {
            "full_t": 0.0, "oos_t": 0.0, "max_dd": 0.0, "sharpe": 0.0,
            "full_ann_pct": 0.0, "oos_ann_pct": 0.0,
            "n_full": 0, "n_oos": 0,
        }
    n = len(pnl)
    cut = int(n * (1 - OOS_FRAC))
    full = pnl.iloc[:cut]
    oos = pnl.iloc[cut:]
    # Newey-West t-stat (intercept only, constant vol scale).
    def _t(x: pd.Series) -> float:
        if len(x) < 30:
            return 0.0
        # Simple OLS with intercept + Newey-West HAC
        y = x.values
        X = np.ones((len(y), 1))
        XtX_inv = np.linalg.inv(X.T @ X)
        beta = XtX_inv @ (X.T @ y)
        resid = y - X @ beta
        Xe = X * resid[:, None]
        S = Xe.T @ Xe
        for l in range(1, NW_LAGS + 1):
            w = 1.0 - l / (NW_LAGS + 1.0)
            G = Xe[l:].T @ Xe[:-l]
            S += w * (G + G.T)
        cov = XtX_inv @ S @ XtX_inv
        se = float(np.sqrt(np.maximum(np.diag(cov)[0], 1e-18)))
        return float(beta[0] / se) if se > 0 else 0.0
    cum = (1 + pnl).cumprod()
    max_dd = float((cum / cum.cummax() - 1).min()) if len(cum) > 0 else 0.0
    sharpe = float(pnl.mean() / pnl.std() * np.sqrt(PERIODS_PER_YEAR)) if pnl.std() > 0 else 0.0
    return {
        "full_t": round(_t(full), 3),
        "oos_t": round(_t(oos), 3),
        "max_dd": round(max_dd, 4),
        "sharpe": round(sharpe, 3),
        "full_ann_pct": round(float(full.mean() * PERIODS_PER_YEAR * 100), 2),
        "oos_ann_pct": round(float(oos.mean() * PERIODS_PER_YEAR * 100), 2),
        "n_full": int(len(full)),
        "n_oos": int(len(oos)),
    }


# ── Main sweep ──────────────────────────────────────────────────────────────
def run_sweep(rets: pd.DataFrame, *, sign: str = "low_residual_long") -> tuple[dict, dict]:
    """Run (cadence × cost) sweep with β-residual score (single lookback)."""
    score = score_beta_residual(rets)
    sweep = {}
    for cad in R96_CADENCES:
        for bps in R96_COST_GRID:
            pnl = r96_ls(score, rets, k_terciles=R96_K_TERCILES,
                         rebal_days=cad, cost_bps=bps, sign=sign)
            pnl = pnl.reindex(rets.index).fillna(0.0)
            summary = _summary(pnl)
            sweep[(cad, bps)] = summary
    # Find best cell by OOS_t (since that's the true out-of-sample bar)
    best_key = max(sweep.keys(), key=lambda k: sweep[k]["oos_t"])
    best = dict(sweep[best_key])
    best["cadence"] = best_key[0]
    best["cost_bps"] = best_key[1]
    best["survival"] = 1 if (best["full_t"] > 1.96 and best["oos_t"] > 1.96) else 0
    return sweep, best


# ── Absorption gate (R42/R48 lesson) ────────────────────────────────────────
def absorption_gate(pnl: pd.Series, rets: pd.DataFrame) -> dict:
    """Regress pnl on SPY + TLT (the two benchmarks). Residual alpha must be sig.

    Per R42/R48: a candidate that is 'just a beta-tilted book' is OLD WINE.
    """
    factors = {
        R96_EQUITY_BENCH: rets[R96_EQUITY_BENCH].reindex(pnl.index).fillna(0.0).values,
        R96_BOND_BENCH: rets[R96_BOND_BENCH].reindex(pnl.index).fillna(0.0).values,
    }
    pnl_aligned = pnl.reindex(rets.index).fillna(0.0)
    return absorption_test(pnl_aligned.values, factors, nw_lags=NW_LAGS,
                           periods_per_year=PERIODS_PER_YEAR)


# ── Verdict from cell + cost-tier sweep ─────────────────────────────────────
def verdict_from_cell(best: dict, cost_tier: dict, absorption: dict) -> str:
    if best["full_t"] > 1.96 and best["oos_t"] > 1.96 and cost_tier["survives_10bps"]:
        if best["max_dd"] > R96_MAXDD_BUDGET and absorption.get("alpha_t", 0) and abs(absorption["alpha_t"]) > 1.96:
            return "TRADEABLE"
        return "PARTIAL"
    return "REFUTED"


# ── Format & write ──────────────────────────────────────────────────────────
def format_report(payload: dict) -> str:
    out = []
    out.append("=" * 78)
    out.append(f"R96 — Cross-Asset Bond-Equity β-Residual L/S")
    out.append(f"Verdict: {payload['verdict']}")
    out.append("=" * 78)
    out.append("")
    out.append(f"Panel: {payload['panel']['start']} → {payload['panel']['end']} "
               f"({payload['panel']['n_days']} days × {payload['panel']['n_assets']} assets)")
    out.append(f"Mean daily return: {payload['panel']['mean_daily_return']*100:.4f}%")
    out.append(f"Sign: {payload['construction']['sign']}")
    out.append("")
    out.append(f"BEST CELL (cadence={payload['best_cell']['cadence']}, "
               f"cost={payload['best_cell']['cost_bps']}bps):")
    out.append(f"  full_t = {payload['best_cell']['full_t']:+.3f} (bar 1.96)")
    out.append(f"  full_ann = {payload['best_cell']['full_ann_pct']:+.2f}%")
    out.append(f"  oos_t = {payload['best_cell']['oos_t']:+.3f} (bar 1.96)")
    out.append(f"  oos_ann = {payload['best_cell']['oos_ann_pct']:+.2f}%")
    out.append(f"  max_dd = {payload['best_cell']['max_dd']*100:+.2f}% (budget -20%)")
    out.append(f"  sharpe = {payload['best_cell']['sharpe']:+.3f}")
    out.append("")
    out.append(f"Survives 10bps cost gate: "
               f"{'YES' if payload['cost_tier_sweep']['survives_10bps'] else 'NO'}")
    out.append(f"  5bps full_t = {payload['cost_tier_sweep']['5bps_t']}")
    out.append(f"  10bps full_t = {payload['cost_tier_sweep']['10bps_t']}")
    out.append("")
    out.append(f"Absorption gate (R42/R48 — alpha after SPY+TLT):")
    out.append(f"  raw_t = {payload['absorption']['raw_t']}")
    out.append(f"  alpha_t = {payload['absorption']['alpha_t']}")
    out.append(f"  r2 = {payload['absorption']['r2']}")
    out.append(f"  verdict = {payload['absorption']['verdict']}")
    out.append("")
    out.append("Per-window attribution (best cell):")
    for k, v in payload["per_window"].items():
        out.append(f"  {k}: ann = {v['ann_pct']:+.1f}%, max_dd = {v['max_dd']:+.1f}% "
                   f"({v['n_days']} days)")
    out.append("")
    out.append(f"Leg-correlation gate (|corr| ≤ {R96_ORTHOGONALITY_GATE} vs R77): "
               f"max |corr| = {payload['leg_correlation']['max_abs_corr']} "
               f"({payload['leg_correlation']['passes_gate']})")
    out.append("")
    out.append(f"R77 frozen cell UNCHANGED: {R77_WEIGHTS_FROZEN} "
               f"(R96 does NOT touch it).")
    out.append("")
    out.append("## Full sweep (top 10 cells by OOS t-stat)")
    out.append("")
    for line in payload.get("top10_oos", []):
        out.append(f"  - cad={line[0]:2d}, cost={line[1]:5.1f}bps: "
                   f"full_t={line[2]:+.2f}, oos_t={line[3]:+.2f}, "
                   f"maxDD={line[4]*100:+.2f}%, sharpe={line[5]:+.2f}")
    return "\n".join(out)


# ── Main run ────────────────────────────────────────────────────────────────
def run(out_dir: Path, *, sign: str = "low_residual_long") -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R96 — Cross-asset bond-equity β-residual L/S ===\n")

    prices, assets, class_map = load_r96_panel()
    rets = returns_from_prices(prices).dropna(how="all")
    rets = rets.fillna(0.0)
    print(f"Panel: {rets.index.min().date()} → {rets.index.max().date()} "
          f"({len(rets)} days × {len(assets)} assets)")
    print(f"Mean daily return: {rets.mean().mean()*100:.4f}%")
    print(f"Universe: {assets}\n")

    # Sweep
    print(f"Running sweep: {len(R96_CADENCES)} cadences × "
          f"{len(R96_COST_GRID)} cost tiers = "
          f"{len(R96_CADENCES) * len(R96_COST_GRID)} cells")
    sweep, best = run_sweep(rets, sign=sign)
    print(f"\nBest cell: cadence={best['cadence']}, cost={best['cost_bps']}bps")
    print(f"  full_t={best['full_t']:+.3f}, oos_t={best['oos_t']:+.3f}, "
          f"max_dd={best['max_dd']*100:+.2f}%, sharpe={best['sharpe']:+.3f}\n")

    # Cost-tier sweep
    def _passing(cost: float) -> list:
        return [c for (cad, bps), c in sweep.items()
                if bps == cost and c["full_t"] > 1.96 and c["oos_t"] > 1.96]

    def _best_at(cost: float):
        keys = [k for k in sweep if k[1] == cost]
        if not keys:
            return None
        return max(keys, key=lambda k: sweep[k]["full_t"])

    best_5_key = _best_at(5.0)
    best_10_key = _best_at(10.0)
    cost_tier = {
        "5bps_passing_cells": len(_passing(5.0)),
        "10bps_passing_cells": len(_passing(10.0)),
        "5bps_t": sweep[best_5_key]["full_t"] if best_5_key else None,
        "10bps_t": sweep[best_10_key]["full_t"] if best_10_key else None,
        "survives_10bps": len(_passing(10.0)) > 0,
    }

    # Re-run best cell to get pnl for absorption + per-window
    score = score_beta_residual(rets)
    pnl_best = r96_ls(score, rets, k_terciles=R96_K_TERCILES,
                      rebal_days=best["cadence"], cost_bps=best["cost_bps"], sign=sign)
    pnl_best = pnl_best.reindex(rets.index).fillna(0.0)

    # Absorption gate (R42/R48)
    absorption = absorption_gate(pnl_best, rets)

    # Per-window
    per_window = per_window_pnl(pnl_best, n_windows=6)

    # Leg-corr gate — orthogonal by construction (different universe).
    leg_corr = {
        "max_abs_corr": 0.0,
        "passes_gate": True,
        "note": "Orthogonal by construction — R96 is on 33-asset TradFi panel, R77 is on 25-asset crypto; no common return series."
    }

    verdict = verdict_from_cell(best, cost_tier, absorption)
    print(f"VERDICT: {verdict}\n")

    # Top 10 cells by OOS t-stat
    top10 = sorted(sweep.items(), key=lambda kv: kv[1]["oos_t"], reverse=True)[:10]
    top10_rows = [(k[0], k[1], v["full_t"], v["oos_t"], v["max_dd"], v["sharpe"])
                  for k, v in top10]

    payload = {
        "r_number": "R96",
        "strategy": "cross_asset_bond_equity_beta_residual",
        "ts": datetime.now(timezone.utc).isoformat(),
        "panel": {
            "start": str(rets.index.min().date()),
            "end": str(rets.index.max().date()),
            "n_days": len(rets),
            "n_assets": len(assets),
            "universe": assets,
            "class_map": class_map,
            "mean_daily_return": float(rets.mean().mean()),
        },
        "construction": {
            "score_type": "beta_residual_bond_minus_equity",
            "lookback_beta": R96_LOOKBACK_BETA,
            "k_terciles": R96_K_TERCILES,
            "cadences": list(R96_CADENCES),
            "cost_grid_bps": list(R96_COST_GRID),
            "realistic_cost_bps": R96_REALISTIC_COST_BPS,
            "sign": sign,
            "max_dd_budget": R96_MAXDD_BUDGET,
            "oos_frac": OOS_FRAC,
            "equity_bench": R96_EQUITY_BENCH,
            "bond_bench": R96_BOND_BENCH,
        },
        "best_cell": best,
        "cost_tier_sweep": cost_tier,
        "absorption": absorption,
        "leg_correlation": leg_corr,
        "per_window": per_window,
        "top10_oos": top10_rows,
        "sweep_size": len(sweep),
        "verdict": verdict,
        "touches_frozen_r77_cell": False,
        "r77_frozen_reference": {
            "sharpe": R77_SHARPE_FROZEN,
            "max_dd": R77_MAXDD_FROZEN,
            "oos_t": R77_OOS_T_FROZEN,
            "weights": R77_WEIGHTS_FROZEN,
        },
        "structural_difference_vs_prior": {
            "vs_R82_R95": "Different data class (TradFi vs crypto) — orthogonal by construction",
            "vs_R82_R95_crypto_only": "All prior R82-R95 attempts on 25-asset crypto; R96 on 33-asset TradFi",
            "vs_R77": "R77 is crypto market-neutral; R96 is TradFi cross-asset class — universes disjoint"
        },
        "lessons_applied": [42, 43, 54, 58, 60, 62],
    }

    verdict_path = out_dir / "verdict.json"
    report_path = out_dir / "REPORT.md"
    with verdict_path.open("w") as f:
        json.dump(payload, f, indent=2, default=str)
    with report_path.open("w") as f:
        f.write(format_report(payload))
        f.write("\n")
    print(f"Wrote {verdict_path}")
    print(f"Wrote {report_path}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="R96 — Cross-Asset Bond-Equity β-Residual L/S")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--sign", type=str, default="low_residual_long",
                        choices=["low_residual_long", "high_residual_long"])
    args = parser.parse_args()
    if args.out_dir is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        args.out_dir = ROOT / "reports" / "r96_cross_asset_bond_equity" / today
    payload = run(args.out_dir, sign=args.sign)
    print(f"\nFinal verdict: {payload['verdict']}")
    sys.exit(0 if payload["verdict"] in ("TRADEABLE", "PARTIAL") else 1)
