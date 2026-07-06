"""
Data loader for CIS × regime research (Seth, 2026-07-06)
==========================================================

Loads CIS daily history (393 days) and OHLCV parquets (52 assets) into
a unified long-form DataFrame ready for IC + regime-conditional analysis.

Public surface:
    load_cis_history(dir_path) -> pd.DataFrame
        Columns: date, asset, asset_class, cis_score, pillar_f, pillar_m,
                 pillar_o, pillar_s, pillar_a, signal, grade, regime
    load_ohlcv_panel(dir_path, symbols=None) -> pd.DataFrame
        Columns: timestamp, asset, open, high, low, close, volume
    build_research_panel(cis_df, ohlcv_df, horizons=(7, 30)) -> pd.DataFrame
        Joins CIS rows with fwd returns at each horizon.  NaN for last
        `max_horizon` days (no fwd return available).

Reads from Shadow mirror by default (read-only); env-overridable.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd


logger = logging.getLogger(__name__)


# ── Paths (env-overridable) ──────────────────────────────────────────────────

DEFAULT_CIS_HISTORY_DIR = Path(
    os.getenv(
        "CIS_HISTORY_RESEARCH_DIR",
        "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
    )
)
DEFAULT_OHLCV_DIR = Path(
    os.getenv(
        "OHLCV_RESEARCH_DIR",
        "/Volumes/CometCloudAI/data/ohlcv/",
    )
)


# ── CIS history loader ───────────────────────────────────────────────────────

def load_cis_history(dir_path: Optional[Path] = None) -> pd.DataFrame:
    """Load all cis_YYYY-MM-DD.json files into a long-form DataFrame.

    Skips companion files (cis_history.db, cis_backtest_*.json, cis_scores_*).
    """
    dir_path = Path(dir_path) if dir_path else DEFAULT_CIS_HISTORY_DIR
    if not dir_path.exists():
        raise FileNotFoundError(f"CIS history dir not found: {dir_path}")

    rows: list[dict] = []
    skipped = 0
    files = sorted(dir_path.glob("cis_*.json"))
    for f in files:
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug(f"skip {f}: {exc}")
            skipped += 1
            continue
        date_str = f.stem.replace("cis_", "")
        regime = data.get("macro_regime")
        for s in data.get("scores", []):
            rows.append({
                "date": pd.to_datetime(date_str, utc=True),
                "asset": s.get("asset") or s.get("symbol"),
                "asset_class": s.get("asset_class"),
                "cis_score": s.get("cis_score"),
                "pillar_f": s.get("pillar_f"),
                "pillar_m": s.get("pillar_m"),
                "pillar_o": s.get("pillar_o"),
                "pillar_s": s.get("pillar_s"),
                "pillar_a": s.get("pillar_a"),
                "signal": s.get("signal"),
                "grade": s.get("grade") or s.get("cis_grade"),
                "data_tier": s.get("data_tier"),
                "regime": regime,
            })

    df = pd.DataFrame(rows)
    # Normalise regime strings (CIS engine has historically emitted mixed
    # case: "RISK_OFF", "Risk-Off", "Tightening", etc.).  Apply shared
    # normaliser from metrics.py so research + strategy agree.
    from .metrics import normalise_regime
    df["regime"] = df["regime"].apply(normalise_regime)
    logger.info(
        f"loaded {len(df)} CIS rows from {len(files)} files "
        f"(skipped {skipped}); {df['date'].nunique()} days, "
        f"{df['asset'].nunique()} unique assets"
    )
    return df


# ── OHLCV loader ─────────────────────────────────────────────────────────────

def load_ohlcv_panel(
    dir_path: Optional[Path] = None,
    symbols: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Load parquets into a panel.  Default: all symbols in dir.

    Returns columns: timestamp, asset, open, high, low, close, volume
    """
    import pyarrow  # noqa: F401  (parquet engine check)

    dir_path = Path(dir_path) if dir_path else DEFAULT_OHLCV_DIR
    if not dir_path.exists():
        raise FileNotFoundError(f"OHLCV dir not found: {dir_path}")

    files = sorted(dir_path.glob("*.parquet"))
    if symbols:
        wanted = {s.upper() for s in symbols}
        files = [f for f in files if f.stem.upper() in wanted]

    panels = []
    for f in files:
        try:
            df = pd.read_parquet(f)
        except Exception as exc:
            logger.debug(f"skip {f}: {exc}")
            continue
        df = df.copy()
        ts_col = "timestamp" if "timestamp" in df.columns else df.columns[0]
        df["timestamp"] = pd.to_datetime(df[ts_col], utc=True)
        df["asset"] = f.stem.upper()
        panels.append(df[["timestamp", "asset", "open", "high", "low", "close", "volume"]])

    if not panels:
        return pd.DataFrame(columns=["timestamp", "asset", "open", "high", "low", "close", "volume"])
    panel = pd.concat(panels, ignore_index=True)
    logger.info(
        f"loaded OHLCV panel: {len(panel)} rows, "
        f"{panel['asset'].nunique()} assets, "
        f"{panel['timestamp'].min()} → {panel['timestamp'].max()}"
    )
    return panel


# ── Research panel builder ───────────────────────────────────────────────────

def _resample_daily(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Resample hourly OHLCV to daily (last close, sum volume)."""
    df = ohlcv.copy()
    df = df.set_index("timestamp").sort_index()
    daily = df.groupby("asset").resample("1D").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["close"]).reset_index()
    return daily


def _compute_fwd_returns(daily: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Forward return at given horizon (days)."""
    df = daily.sort_values(["asset", "timestamp"]).copy()
    df[f"fwd_{horizon}d"] = (
        df.groupby("asset")["close"].shift(-horizon) / df["close"] - 1.0
    )
    return df


def build_research_panel(
    cis_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    horizons: tuple[int, ...] = (7, 30),
    assets_filter: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Join CIS rows with fwd returns at each horizon.

    Returns a long-form DataFrame: one row per (date, asset) with CIS
    columns + fwd_<horizon>d columns + regime.  Drops rows where NO fwd
    return is available (last `max_horizon` days).
    """
    daily = _resample_daily(ohlcv_df)
    for h in horizons:
        daily = _compute_fwd_returns(daily, h)

    # Normalise asset name on CIS side to match OHLCV
    cis = cis_df.copy()
    cis["asset"] = cis["asset"].str.upper()

    # Convert CIS date to a daily timestamp at UTC midnight
    cis["timestamp"] = pd.to_datetime(cis["date"]).dt.tz_convert("UTC") if cis["date"].dt.tz is not None else pd.to_datetime(cis["date"]).dt.tz_localize("UTC")

    if assets_filter:
        wanted = {a.upper() for a in assets_filter}
        cis = cis[cis["asset"].isin(wanted)]
        daily = daily[daily["asset"].isin(wanted)]

    panel = cis.merge(
        daily[["timestamp", "asset"] + [f"fwd_{h}d" for h in horizons]],
        on=["timestamp", "asset"],
        how="inner",
    )
    panel = panel.dropna(subset=[f"fwd_{h}d" for h in horizons], how="all")

    logger.info(
        f"research panel: {len(panel)} rows, "
        f"{panel['asset'].nunique()} assets, "
        f"regime counts: {panel['regime'].value_counts().to_dict()}"
    )
    return panel


# ── CLI smoke ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cis = load_cis_history()
    print(f"\nCIS history: {len(cis)} rows")
    print(f"  date range: {cis['date'].min().date()} → {cis['date'].max().date()}")
    print(f"  unique assets: {cis['asset'].nunique()}")
    print(f"  regime distribution:\n{cis['regime'].value_counts().to_string()}")

    ohlcv = load_ohlcv_panel()
    print(f"\nOHLCV panel: {len(ohlcv)} rows, {ohlcv['asset'].nunique()} assets")

    panel = build_research_panel(cis, ohlcv, horizons=(7, 30))
    print(f"\nResearch panel: {len(panel)} rows")
    print(f"  fwd_7d null%: {panel['fwd_7d'].isna().mean():.1%}")
    print(f"  fwd_30d null%: {panel['fwd_30d'].isna().mean():.1%}")