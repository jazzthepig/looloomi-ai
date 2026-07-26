"""
Enrich the 11yr CIS historical CSV with β-adj returns + regime-normalized pillar z-scores.

Adds the following columns (per §DATA-ALIGN directive, Jazz 2026-07-24):
  - `beta_adj_return`     — α = a_ret − β·btc_ret, where β is the PIT-expanding
                            window beta to BTC daily return. NULL when fewer than
                            `MIN_PRIORS=20` days of history exist for the asset.
  - `regime_zscore_{p}`    — for each pillar p ∈ {f, m, o, s, a, score}, the
                            trailing 252d z-score of pillar p within the
                            (regime, pillar) bucket, computed PIT-safely (only
                            past data, no future leakage).
  - `asset_zscore_{p}`     — for each pillar p, the trailing 252d z-score of
                            pillar p within (asset, pillar), PIT-safe.

PIT discipline (per §PIT-LEAK-C 2026-07-21):
  - All rolling windows use SHIFT(1) before computing mean/std — the row at
    time t uses the distribution from rows strictly before t.
  - β at time t uses only returns from rows strictly before t (expanding
    window). Insufficient history ⇒ NULL, not a default of 1.0.

OHLCV dependency:
  - β-adj returns require daily close prices for both the asset AND BTC.
  - Sources scanned (in order): `_data/strategy_revive/`, then
    `_data/hyperliquid_funding/` (hyperliquid_funding files have minimal schema:
    `openTime,close,quoteVolume`; strategy_revive has the full Binance format).
  - Missing coverage ⇒ NaN. Coverage is reported honestly; no silent imputation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

import numpy as np
import pandas as pd

from src.research.data_align.cis_history_schema import (
    CSV_COLUMNS, NUMERIC_COLUMNS, REGIMES,
)

# ── Config ────────────────────────────────────────────────────────────────────

# OHLCV search dirs (in priority order — strategy_revive has richer data).
OHLCV_DIRS: tuple[Path, ...] = (
    Path("/Volumes/CometCloudAI/cometcloud-local/_data/strategy_revive"),
    Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding"),
)

OHLCV_BENCHMARK = "BTC"

# PIT params (mirror src/data/market/beta_adjust.py)
MIN_PRIORS = 20            # β needs ≥20 obs to estimate; below ⇒ NULL
ZSCORE_LOOKBACK = 252      # 1 trading year

# Pillar set to z-score (extend with composite 'score' as the 6th)
ZSCORE_PILLARS: tuple[str, ...] = ("f", "m", "o", "s", "a", "score")


# ── OHLCV loader (strategy_revive + hyperliquid_funding) ──────────────────────

def _read_ohlcv_close(path: Path) -> pd.Series:
    """Read a daily OHLCV CSV and return a (date-indexed) close series.

    Supports both formats:
      - strategy_revive: `date,open,high,low,close,volume_base,...`
      - hyperliquid_funding: `openTime,close,quoteVolume` (epoch ms)
    """
    if not path.exists():
        raise FileNotFoundError(path)
    # Detect schema by header
    with path.open("r") as f:
        header = f.readline().strip().split(",")
    if "date" in header:
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        s = df.set_index("date")["close"].astype(float)
    elif "openTime" in header:
        df = pd.read_csv(path)
        # openTime is epoch ms (Binance daily bars open at 00:00 UTC)
        df["date"] = pd.to_datetime(df["openTime"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
        s = df.set_index("date")["close"].astype(float)
    else:
        raise ValueError(f"Unrecognized OHLCV schema in {path}: header={header}")
    s = s[~s.index.isna()].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s


def load_returns_wide(
    symbols: list[str],
    *,
    date_index: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Return a wide DataFrame of daily simple returns for the given symbols.

    Columns = symbols. Index = union of dates across all files.
    Missing files ⇒ column of NaN. Honest, not silent imputation.
    """
    close_dict: dict[str, pd.Series] = {}
    for sym in symbols:
        found = False
        for d in OHLCV_DIRS:
            p = d / f"{sym}_1d_ohlcv.csv"
            if p.exists():
                try:
                    close_dict[sym] = _read_ohlcv_close(p)
                    found = True
                    break
                except Exception:
                    continue
        if not found:
            # all-NaN column so the user can see the gap
            close_dict[sym] = pd.Series(dtype=float)
    if not close_dict:
        return pd.DataFrame()
    close_df = pd.concat(close_dict.values(), axis=1, keys=close_dict.keys())
    close_df.columns = list(close_dict.keys())
    # Simple returns: a_ret[t] = close[t] / close[t-1] - 1
    rets = close_df.pct_change()
    if date_index is not None:
        rets = rets.reindex(date_index)
    return rets


def coverage_report(returns_wide: pd.DataFrame) -> pd.DataFrame:
    """Per-asset coverage report — first/last available date + n obs + status."""
    rows = []
    for sym in returns_wide.columns:
        s = returns_wide[sym].dropna()
        rows.append({
            "symbol": sym,
            "n_obs": len(s),
            "first_date": s.index.min() if len(s) else pd.NaT,
            "last_date": s.index.max() if len(s) else pd.NaT,
            "coverage_ok": len(s) >= MIN_PRIORS,
        })
    return pd.DataFrame(rows)


# ── β-adjusted returns (PIT-safe expanding window) ────────────────────────────

def compute_beta_adjusted_returns(
    df: pd.DataFrame,
    rets_wide: pd.DataFrame,
    benchmark: str = OHLCV_BENCHMARK,
) -> pd.DataFrame:
    """Add `beta_adj_return` column to `df`.

    For each row at (symbol, date):
      - Look up a_ret = returns_wide[symbol].loc[date]
      - Look up b_ret = returns_wide[benchmark].loc[date]
      - Estimate β from the EXPANDING window of (a_ret, b_ret) for the symbol
        using ONLY observations strictly before this date.
      - α = a_ret - β·b_ret. NULL if β is NULL or either return is NaN.
    """
    if benchmark not in rets_wide.columns:
        raise ValueError(
            f"Benchmark {benchmark!r} not in returns_wide columns. "
            f"Available: {list(rets_wide.columns)}"
        )
    b_ret_series = rets_wide[benchmark]

    # Pre-compute β per symbol: for each date t, β from prior a/b series.
    # Use the production-grade estimator from src/data/market/beta_adjust.py.
    from src.data.market.beta_adjust import estimate_beta_pit

    # Sort rows by (symbol, _date) for stable expansion
    df = df.copy()
    df["_row_idx"] = np.arange(len(df))

    # Group rows by symbol; expand within each symbol
    by_symbol: dict[str, pd.DataFrame] = {}
    for sym, g in df.groupby("symbol", sort=False):
        g = g.sort_values("_date").copy()
        a_series = rets_wide[sym].reindex(g["_date"]).reset_index(drop=True)
        b_series = b_ret_series.reindex(g["_date"]).reset_index(drop=True)
        # Expanding β at each row uses observations strictly before that row's index
        betas: list[float] = []
        prior_a: list[float] = []
        prior_b: list[float] = []
        for i in range(len(g)):
            if i == 0:
                betas.append(np.nan)
            else:
                b = estimate_beta_pit(prior_a, prior_b, min_priors=MIN_PRIORS)
                betas.append(b if b is not None else np.nan)
            # Append this row's returns to the prior pool AFTER estimating β for this row
            ai = a_series.iat[i] if i < len(a_series) else np.nan
            bi = b_series.iat[i] if i < len(b_series) else np.nan
            if pd.notna(ai) and pd.notna(bi):
                prior_a.append(float(ai))
                prior_b.append(float(bi))
        g["_beta"] = betas
        # α = a_ret − β·b_ret
        g["_a_ret"] = a_series.values
        g["_b_ret"] = b_series.values
        alpha = g["_a_ret"] - g["_beta"] * g["_b_ret"]
        g["beta_adj_return"] = alpha.where(g["_beta"].notna() & g["_a_ret"].notna() & g["_b_ret"].notna())
        by_symbol[sym] = g

    out = pd.concat(list(by_symbol.values()), axis=0).sort_values("_row_idx")
    return out.drop(columns=["_row_idx", "_beta", "_a_ret", "_b_ret"])


# ── Regime-normalized pillar z-scores (PIT-safe) ──────────────────────────────

def compute_regime_zscores(
    df: pd.DataFrame,
    *,
    lookback: int = ZSCORE_LOOKBACK,
    pillars: tuple[str, ...] = ZSCORE_PILLARS,
) -> pd.DataFrame:
    """Add `regime_zscore_{p}` columns — trailing z-score within (regime, p) bucket.

    Pool all assets in the same regime bucket. For each row at time t:
      - μ_regime, σ_regime are computed from rows in the SAME regime, with
        dates in [t - lookback, t). PIT-safe (excludes t itself via SHIFT).
      - z = (pillar[t] - μ) / σ
      - σ < 1e-9 ⇒ NaN (degenerate bucket).

    Also adds `asset_zscore_{p}` — trailing z-score within (asset, p), 252d
    lookback. PIT-safe.
    """
    df = df.copy()
    df["_orig_idx"] = np.arange(len(df))
    df = df.sort_values(["_date", "symbol"]).reset_index(drop=True)

    # Regime z-scores: cross-asset within regime × pillar bucket.
    # Vectorized: build a wide (date × symbol) DataFrame per regime, compute
    # rolling z-scores column-wise (per-symbol), then melt back to long form.
    for p in pillars:
        col = f"pillar_{p}" if p != "score" else "score"
        if col not in df.columns:
            continue
        z_col = f"regime_zscore_{p}"
        df[z_col] = np.nan

        for regime, g in df.groupby("macro_regime"):
            # Unknown regime → skip (handled by global pool if needed)
            if pd.notna(regime) and regime not in REGIMES:
                continue
            if pd.isna(regime):
                continue
            # Pivot: rows = _date, columns = symbol, values = pillar value.
            wide = g.pivot_table(index="_date", columns="symbol",
                                  values=col, aggfunc="first")
            wide = wide.sort_index()
            # Per-symbol rolling z-score, with shift(1) to ensure PIT-safe
            # (row t uses distribution from rows strictly before t).
            wide_lag = wide.shift(1)
            mu = wide_lag.rolling(lookback, min_periods=20).mean()
            sd = wide_lag.rolling(lookback, min_periods=20).std()
            with np.errstate(divide="ignore", invalid="ignore"):
                z_wide = (wide - mu) / sd.where(sd > 1e-9)
            # Melt back to long form and align with df via merge.
            z_long = z_wide.stack(future_stack=True).reset_index()
            z_long.columns = ["_date", "symbol", z_col]
            # Merge: vectorized assignment via map
            z_map = z_long.set_index(["_date", "symbol"])[z_col]
            # Build a (date, symbol) MultiIndex on df for reindex
            keys = list(zip(df.loc[g.index, "_date"], df.loc[g.index, "symbol"]))
            df.loc[g.index, z_col] = [z_map.get(k, np.nan) for k in keys]

    # Asset z-scores: per-(symbol, pillar), trailing. PIT-safe via shift(1).
    # Vectorized via wide pivot, same trick as regime z-scores.
    for p in pillars:
        col = f"pillar_{p}" if p != "score" else "score"
        if col not in df.columns:
            continue
        z_col = f"asset_zscore_{p}"
        df[z_col] = np.nan
        # Wide pivot per (symbol, _date) — only ONE row per (symbol, date)
        # since the 11yr CSV has at most 1 entry per day per asset.
        wide = df.pivot_table(index="_date", columns="symbol",
                              values=col, aggfunc="first").sort_index()
        wide_lag = wide.shift(1)
        mu = wide_lag.rolling(lookback, min_periods=20).mean()
        sd = wide_lag.rolling(lookback, min_periods=20).std()
        with np.errstate(divide="ignore", invalid="ignore"):
            z_wide = (wide - mu) / sd.where(sd > 1e-9)
        z_long = z_wide.stack(future_stack=True).reset_index()
        z_long.columns = ["_date", "symbol", z_col]
        z_map = z_long.set_index(["_date", "symbol"])[z_col]
        keys = list(zip(df["_date"], df["symbol"]))
        df[z_col] = [z_map.get(k, np.nan) for k in keys]

    df = df.sort_values("_orig_idx").drop(columns=["_orig_idx"]).reset_index(drop=True)
    return df


# ── Orchestrator ──────────────────────────────────────────────────────────────

def enrich_cis_history(
    df: pd.DataFrame,
    *,
    compute_beta_adj: bool = True,
    compute_zscores: bool = True,
    benchmark: str = OHLCV_BENCHMARK,
) -> tuple[pd.DataFrame, dict]:
    """Run all enrichment steps. Returns (enriched_df, report)."""
    report: dict = {
        "n_rows_in": int(len(df)),
        "n_assets": int(df["symbol"].nunique()) if "symbol" in df.columns else 0,
        "n_dates": int(df["_date"].nunique()) if "_date" in df.columns else 0,
        "beta_adj": None,
        "regime_zscores": None,
    }

    if compute_beta_adj:
        symbols = sorted(df["symbol"].dropna().unique().tolist())
        rets = load_returns_wide(symbols, date_index=pd.DatetimeIndex(sorted(df["_date"].dropna().unique())))
        cov = coverage_report(rets)
        report["beta_adj"] = {
            "n_assets_with_ohlcv": int(cov["coverage_ok"].sum()),
            "n_assets_total": len(cov),
            "coverage_pct": float(cov["coverage_ok"].mean() * 100.0) if len(cov) else 0.0,
            "min_first_date": str(cov["first_date"].min()) if cov["first_date"].notna().any() else None,
            "max_last_date": str(cov["last_date"].max()) if cov["last_date"].notna().any() else None,
            "per_asset": cov.to_dict(orient="records"),
        }
        df = compute_beta_adjusted_returns(df, rets, benchmark=benchmark)

    if compute_zscores:
        df = compute_regime_zscores(df)
        report["regime_zscores"] = {}
        for p in ZSCORE_PILLARS:
            col = f"regime_zscore_{p}"
            if col in df.columns:
                finite = int(df[col].notna().sum())
                report["regime_zscores"][p] = {
                    "n_finite": finite,
                    "pct_finite": round(100.0 * finite / max(1, len(df)), 2),
                }

    return df, report


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(
    in_csv: Union[str, Path] = "_data/cis_historical/cis_historical_11yr.csv",
    out_csv: Union[str, Path] = "_data/cis_historical/cis_historical_11yr_aligned.csv",
    *,
    compute_beta_adj: bool = True,
) -> None:
    from src.research.data_align.cis_history_loader import load_cis_history

    df = load_cis_history(in_csv)
    enriched, report = enrich_cis_history(df, compute_beta_adj=compute_beta_adj)

    # Write with canonical header (loader is header-aware, write needs it explicit)
    from src.research.data_align.cis_history_schema import CSV_COLUMNS
    extra_cols = [c for c in enriched.columns if c not in CSV_COLUMNS and c != "_date"]
    header_line = ",".join(CSV_COLUMNS + extra_cols + ["_date"])

    out = Path(out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(out, index=False)
    # Prepend header if first line is not "symbol,..."
    with out.open("r") as f:
        first = f.readline().strip()
    if first.split(",", 1)[0] != "symbol":
        tmp = out.with_suffix(out.suffix + ".tmp")
        with tmp.open("w", newline="") as fout, out.open("r") as fin:
            fout.write(header_line + "\n")
            fout.write(fin.read())
        tmp.replace(out)

    print(f"Enriched {len(enriched)} rows × {len(enriched.columns)} cols → {out}")
    if report.get("beta_adj"):
        b = report["beta_adj"]
        print(f"  β-adj coverage: {b['n_assets_with_ohlcv']}/{b['n_assets_total']} assets "
              f"({b['coverage_pct']:.1f}%) have ≥{MIN_PRIORS} obs")
        if b["min_first_date"]:
            print(f"  OHLCV coverage window: {b['min_first_date']} → {b['max_last_date']}")
    if report.get("regime_zscores"):
        print("  Regime z-score coverage (per pillar):")
        for p, r in report["regime_zscores"].items():
            print(f"    {p}: {r['n_finite']} finite ({r['pct_finite']}%)")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Enrich 11yr CIS historical CSV")
    ap.add_argument("--in", dest="in_csv", default="_data/cis_historical/cis_historical_11yr.csv")
    ap.add_argument("--out", dest="out_csv", default="_data/cis_historical/cis_historical_11yr_aligned.csv")
    ap.add_argument("--no-beta-adj", dest="no_beta_adj", action="store_true")
    args = ap.parse_args()
    main(in_csv=args.in_csv, out_csv=args.out_csv,
         compute_beta_adj=not args.no_beta_adj)