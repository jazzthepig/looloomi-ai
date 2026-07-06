"""
Metrics for CIS × regime research (Seth, 2026-07-06)
======================================================

AQR + Millennium-grade helpers:
    - Pearson + Spearman IC with t-stats
    - Quantile spreads (top-q vs bottom-q fwd returns)
    - Sharpe / Sortino / Calmar with annualisation
    - Multiple-testing corrections (HOLM + Bonferroni)

All functions are pure (no I/O).  Designed for vectorised use over
the long-form research panel.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats


# ── Information Coefficient ──────────────────────────────────────────────────

def ic_pearson(x: pd.Series, y: pd.Series) -> dict:
    """Pearson IC with t-stat.  Returns NaN fields if either is empty/constant."""
    df = pd.concat([x, y], axis=1).dropna()
    if len(df) < 3:
        return {"n": len(df), "ic": np.nan, "t_stat": np.nan, "p_value": np.nan}
    r, p = stats.pearsonr(df.iloc[:, 0], df.iloc[:, 1])
    t = r * math.sqrt((len(df) - 2) / max(1e-9, 1 - r * r))
    return {
        "n": len(df),
        "ic": float(r),
        "t_stat": float(t),
        "p_value": float(p),
    }


def ic_spearman(x: pd.Series, y: pd.Series) -> dict:
    """Spearman rank IC with t-stat."""
    df = pd.concat([x, y], axis=1).dropna()
    if len(df) < 3:
        return {"n": len(df), "ic": np.nan, "t_stat": np.nan, "p_value": np.nan}
    rho, p = stats.spearmanr(df.iloc[:, 0], df.iloc[:, 1])
    t = rho * math.sqrt((len(df) - 2) / max(1e-9, 1 - rho * rho))
    return {
        "n": len(df),
        "ic": float(rho),
        "t_stat": float(t),
        "p_value": float(p),
    }


def ic_table(
    panel: pd.DataFrame,
    pillar_cols: list[str],
    return_col: str,
    regime_col: str = "regime",
    ic_kind: str = "pearson",
) -> pd.DataFrame:
    """IC per (pillar × regime) cell.

    Returns DataFrame with columns: pillar, regime, n, ic, t_stat, p_value.
    Adds a "_overall" pseudo-regime row first for context.
    """
    func = ic_pearson if ic_kind == "pearson" else ic_spearman
    rows = []
    # Overall (no regime filter)
    for p in pillar_cols:
        m = func(panel[p], panel[return_col])
        rows.append({"pillar": p, "regime": "_overall", **m})
    # Per regime
    for regime, sub in panel.groupby(regime_col, dropna=False):
        if pd.isna(regime):
            continue
        for p in pillar_cols:
            m = func(sub[p], sub[return_col])
            rows.append({"pillar": p, "regime": regime, **m})
    return pd.DataFrame(rows)


# ── Quantile spreads ─────────────────────────────────────────────────────────

def quantile_spreads(
    panel: pd.DataFrame,
    pillar_col: str,
    return_col: str,
    n_quantiles: int = 5,
    regime_col: str = "regime",
) -> pd.DataFrame:
    """Top-q vs bottom-q fwd return spread per regime.

    Returns: regime, n, q_top, q_bottom, spread, top_minus_bottom_std_error.
    """
    rows = []
    for regime, sub in panel.groupby(regime_col, dropna=False):
        if pd.isna(regime) or len(sub) < n_quantiles * 2:
            continue
        df = sub[[pillar_col, return_col]].dropna()
        if len(df) < n_quantiles * 2:
            continue
        try:
            df["q"] = pd.qcut(df[pillar_col], n_quantiles, labels=False, duplicates="drop")
        except ValueError:
            continue
        top = df[df["q"] == df["q"].max()][return_col].mean()
        bot = df[df["q"] == df["q"].min()][return_col].mean()
        n_top = (df["q"] == df["q"].max()).sum()
        n_bot = (df["q"] == df["q"].min()).sum()
        rows.append({
            "regime": regime,
            "pillar": pillar_col,
            "n_quantiles": n_quantiles,
            "n_total": len(df),
            "n_top": int(n_top),
            "n_bottom": int(n_bot),
            "q_top_return": float(top),
            "q_bottom_return": float(bot),
            "spread_top_minus_bottom": float(top - bot),
        })
    return pd.DataFrame(rows)


# ── Risk-adjusted return helpers ─────────────────────────────────────────────

def annualised_sharpe(returns: pd.Series, periods_per_year: int = 365) -> float:
    """Annualised Sharpe assuming daily returns.  No rf."""
    r = returns.dropna()
    if len(r) < 2:
        return np.nan
    sd = r.std(ddof=1)
    if sd <= 0:
        return np.nan
    return float(r.mean() / sd * math.sqrt(periods_per_year))


def annualised_sortino(returns: pd.Series, periods_per_year: int = 365) -> float:
    """Annualised Sortino (downside-only vol)."""
    r = returns.dropna()
    if len(r) < 2:
        return np.nan
    downside = r[r < 0]
    if len(downside) < 2:
        return np.nan
    sd = downside.std(ddof=1)
    if sd <= 0:
        return np.nan
    return float(r.mean() / sd * math.sqrt(periods_per_year))


def calmar(returns: pd.Series, periods_per_year: int = 365) -> float:
    """Calmar = annualised return / max drawdown magnitude."""
    r = returns.dropna()
    if len(r) < 2:
        return np.nan
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    max_dd = dd.min()  # negative
    if max_dd >= 0 or np.isnan(max_dd):
        return np.nan
    ann_ret = (1 + r.mean()) ** periods_per_year - 1
    return float(ann_ret / abs(max_dd))


# ── Multiple-testing corrections ─────────────────────────────────────────────

def holm_bonferroni(p_values: np.ndarray) -> np.ndarray:
    """HOLM step-down correction.  Returns adjusted p-values.

    Adjusted p-values are monotone non-decreasing and control FWER.
    """
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    if n == 0:
        return p
    # Order by p-value ascending
    order = np.argsort(p)
    ranked = p[order]
    # Adjusted: (n - i) * p_(i), floored at 1.0
    adjusted = np.minimum(1.0, ranked * (n - np.arange(n)))
    # Enforce monotonicity (step-down)
    adjusted = np.maximum.accumulate(adjusted)
    # Restore original order
    out = np.empty(n)
    out[order] = adjusted
    return out


def bonferroni(p_values: np.ndarray) -> np.ndarray:
    """Simple Bonferroni correction: p * n, capped at 1.0."""
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    if n == 0:
        return p
    return np.minimum(1.0, p * n)


# ── Regime normalisation (shared with strategy) ─────────────────────────────

REGIME_NORMALISATION = {
    "RISK_OFF": "Risk-Off", "RISK_ON": "Risk-On",
    "EASING": "Easing", "TIGHTENING": "Tightening",
    "STAGFLATION": "Stagflation", "NEUTRAL": "Neutral",
    "GOLDILOCKS": "Goldilocks",
}


def normalise_regime(raw: str) -> str:
    if not raw:
        return "Neutral"
    up = str(raw).strip().upper().replace("-", "_")
    return REGIME_NORMALISATION.get(up, "Neutral")


# ── CLI smoke ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Toy data sanity check
    rng = np.random.default_rng(42)
    n = 500
    x = pd.Series(rng.normal(0, 1, n))
    y = 0.3 * x + rng.normal(0, 1, n) * 0.5  # true IC ≈ 0.3 / sqrt(0.25 + 0.09) ≈ 0.51
    out = ic_pearson(x, y)
    print(f"toy Pearson IC: {out}")
    out_s = ic_spearman(x, y)
    print(f"toy Spearman IC: {out_s}")

    p_vals = np.array([0.001, 0.01, 0.04, 0.03, 0.5, 0.8])
    print(f"raw p:    {p_vals}")
    print(f"HOLM adj: {holm_bonferroni(p_vals)}")
    print(f"BONF adj: {bonferroni(p_vals)}")