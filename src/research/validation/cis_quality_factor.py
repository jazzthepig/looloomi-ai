"""
True CIS-quality factor — long top-tercile CIS / short bottom-tercile CIS (Seth, 2026-07-18).
================================================================================================
Replaces the price-tercile proxy in `src/research/cis_regime_studies/absorption_sweep_runner.py`
when §CIS-HISTORY-BACKFILL lands. The deliverable from that workstream is per-day
`cis_YYYY-MM-DD.json` snapshots at
`/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/`.

Why a TRUE CIS factor matters (the remaining true-α question):
  The current proxy sorts on RECENT PRICE RETURN (top-quartile winners / bottom-quartile losers).
  That series structurally overlaps with `f_momentum` — anything absorbed by TSMOM today might
  only have appeared orthogonal because we're double-counting the same momentum flavor.
  The true factor sorts on CIS SCORE (a multi-pillar cross-sectional quality measure).
  A sleeve that's orthogonal to QUALITY but appears to correlate with MOMENTUM won't pass
  the trap of the price-tercile proxy. Re-running with the true CIS factor reveals which
  sleeves carry genuine orthogonal alpha vs which were just hidden by a momentum-flavored proxy.

Construction:
  - Sort universe into terciles by CIS score from day d-1 (NOT d — no look-ahead)
  - Top tercile → long; bottom tercile → short; middle → flat
  - Daily factor return = mean(top) − mean(bottom) of asset returns on day d
  - Output: pd.Series indexed by date with the column `f_cis_quality` (decimal returns)

Outputs are designed to slot directly into the absorption sweep's wide CSV — same column
name as the proxy (`f_cis_quality`), so the swap is "change the numbers behind the column",
not "change the schema".

Compliance: positioning language only; trade-direction vocabulary is forbidden in this module.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# Default location per §CIS-HISTORY-BACKFILL (MINIMAX_SYNC.md line 3500-3502).
# Override at call-time via `cis_history_dir=`.
DEFAULT_CIS_HISTORY_DIR = "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history"
TERCILES = (1 / 3, 2 / 3)  # rank-percentile cut points; top third, middle, bottom third.


def load_cis_history(cis_history_dir: str | Path = DEFAULT_CIS_HISTORY_DIR,
                     date_range: Optional[tuple] = None) -> pd.DataFrame:
    """Load every `cis_YYYY-MM-DD.json` snapshot into a long-form DataFrame.

    Returns: DataFrame with columns [date, asset, cis_score, asset_class, signal, las].
    date_range: optional (start_date, end_date) tuple of datetime.date — restricts the load.
    """
    rows = []
    files = sorted(glob.glob(str(Path(cis_history_dir) / "cis_*.json")))
    for fp in files:
        with open(fp) as fh:
            d = json.load(fh)
        # Date resolution order: explicit "date" key → parse from filename (cis_YYYY-MM-DD.json)
        # → top-level "timestamp". The reconstructed snapshots carry only "timestamp", so the
        # filename is the robust source of the calendar date.
        if d.get("date"):
            d_date = pd.to_datetime(d["date"]).date()
        else:
            stem = Path(fp).stem  # cis_2024-03-01
            date_str = stem.replace("cis_", "")
            try:
                d_date = pd.to_datetime(date_str).date()
            except (ValueError, TypeError):
                d_date = pd.to_datetime(d.get("timestamp")).date()
        if date_range and not (date_range[0] <= d_date <= date_range[1]):
            continue
        for s in d.get("scores", []):
            rows.append({
                "date": d_date,
                "asset": s.get("asset") or s.get("symbol"),
                "cis_score": float(s["cis_score"]),
                "asset_class": s.get("asset_class"),
                "signal": s.get("signal"),
                "las": s.get("las"),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["date", "asset"]).reset_index(drop=True)


def build_cis_quality_factor(cis_history_df: pd.DataFrame,
                              daily_returns_df: pd.DataFrame,
                              k_terciles: int = 3) -> pd.Series:
    """Long top-tercile CIS / short bottom-tercile CIS, lagged 1 day.

    cis_history_df: from `load_cis_history()`. Must have columns [date, asset, cis_score].
    daily_returns_df: pd.DataFrame indexed by date, COLUMNS are assets, values are DAILY
                     decimal returns (e.g. 0.012 = +1.2%). The asset universe is the
                     intersection with `cis_history_df`'s asset set.
    k_terciles: 3 for terciles (default), can do 4 for quartiles to match the proxy exactly.

    Returns: pd.Series of daily factor returns, decimal. Index = date of returns realized
             (i.e. factor(t) uses CIS ranking from day t-1).
    """
    if cis_history_df.empty or daily_returns_df.empty:
        return pd.Series(dtype=float)

    # 1. Restrict to assets that exist in BOTH the CIS history AND the price returns.
    asset_universe = sorted(set(cis_history_df["asset"]) & set(daily_returns_df.columns))
    if len(asset_universe) < 6:
        # fewer than 6 assets — won't form a meaningful cross-section
        return pd.Series(0.0, index=daily_returns_df.index)

    cis = cis_history_df[cis_history_df["asset"].isin(asset_universe)].copy()
    rets = daily_returns_df[asset_universe].copy()

    # 2. For each day, lag the CIS ranking by 1 day. We carry yesterday's CIS forward to today.
    cis_dates = sorted(cis["date"].unique())
    rank_per_day = {}
    for d in cis_dates:
        day_slice = cis[cis["date"] == d].set_index("asset")["cis_score"]
        # rank into k_terciles via qcut (handles ties deterministically by rank-then-cut)
        try:
            ranks = pd.qcut(day_slice, q=k_terciles, labels=False, duplicates="drop")
        except ValueError:
            # too few unique values to form k bins — fall back to median-split
            ranks = (day_slice >= day_slice.median()).astype(int)
        rank_per_day[d] = ranks.to_dict()

    rank_df = pd.DataFrame(rank_per_day).T  # date × asset
    rank_df.index = pd.to_datetime(rank_df.index)
    rank_df = rank_df.sort_index()

    # 3. Forward-fill yesterday's CIS tercile ranks through today. That is: rank(t) is known
    #    by day t+1; we want to apply it to returns on day t+1.
    # Trick: re-index the rank to today's date index using ffill.
    rank_ffill = rank_df.reindex(rets.index, method="ffill")
    # If the first day(s) have NaN ranks (no prior CIS history), set to middle rank → flat.
    rank_ffill = rank_ffill.fillna((k_terciles - 1) / 2)

    # 4. Compute factor return per day: mean(top-rank returns) − mean(bottom-rank returns).
    top_label = k_terciles - 1           # top tercile = label 2 (for k=3)
    bot_label = 0                        # bottom tercile = label 0
    fac = pd.Series(0.0, index=rets.index)
    valid = rank_ffill.notna().all(axis=1)  # require full asset universe to have a rank
    for date in rets.index[valid]:
        ranks_today = rank_ffill.loc[date]
        top_assets = ranks_today[ranks_today == top_label].index.tolist()
        bot_assets = ranks_today[ranks_today == bot_label].index.tolist()
        if not top_assets or not bot_assets:
            fac.loc[date] = 0.0
            continue
        top_ret = rets.loc[date, top_assets].mean()
        bot_ret = rets.loc[date, bot_assets].mean()
        fac.loc[date] = top_ret - bot_ret
    return fac.rename("f_cis_quality")


def build_factor_from_disk(cis_history_dir: str | Path = DEFAULT_CIS_HISTORY_DIR,
                            daily_returns_df: Optional[pd.DataFrame] = None,
                            k_terciles: int = 3) -> pd.Series:
    """Convenience: load CIS history + compute factor in one call.

    `daily_returns_df` must be supplied separately (it lives at
    `/Volumes/CometCloudAI/.../data/ohlcv/1d-spot/`, fetched by Minimax-B).
    Function returns a pd.Series ready to merge into the wide CSV as `f_cis_quality`.
    """
    if daily_returns_df is None:
        raise ValueError(
            "daily_returns_df is required — load from "
            "/Volumes/CometCloudAI/looloomi-research/data/ohlcv/1d-spot/*.parquet "
            "(Minimax-B owns the ohlcv fetch)."
        )
    cis_df = load_cis_history(cis_history_dir)
    return build_cis_quality_factor(cis_df, daily_returns_df, k_terciles=k_terciles)


if __name__ == "__main__":
    # Self-test on synthetic cis history + synthetic prices. Builds in sandbox; no disk.
    print("=== CIS-quality factor self-test (synthetic, no disk reads) ===")
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-03-01", "2025-05-02", freq="D")
    assets = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "LINK", "DOT"]
    # synthetic CIS history
    rows = []
    for d in dates[::7]:  # weekly snapshots
        cis_vals = rng.uniform(40, 90, len(assets))
        for a, c in zip(assets, cis_vals):
            rows.append({"date": d.date(), "asset": a, "cis_score": float(c),
                         "asset_class": "L1", "signal": "NEUTRAL", "las": c})
    cis_df = pd.DataFrame(rows)
    # synthetic daily returns: top-CIS assets earn higher returns on average (positive IC)
    cis_score_lookup = cis_df.groupby("asset")["cis_score"].mean()
    rets = pd.DataFrame(index=dates, columns=assets, dtype=float)
    for a in assets:
        base = (cis_score_lookup[a] - 65) * 0.0003   # positive quality premium
        rets[a] = rng.normal(base, 0.03, len(dates))
    fac = build_cis_quality_factor(cis_df, rets)
    print(f"\nFactor shape: {fac.shape}, mean: {fac.mean():+.5f}/day, "
          f"annualized: {fac.mean() * 365 * 100:+.2f}%/yr, "
          f"std: {fac.std():.5f}")
    # Sanity: with quality premium embedded, factor should be positive on average.
    assert fac.mean() > 0, "expected positive quality premium from synth data"
    print("\n✅ Self-test passed.")