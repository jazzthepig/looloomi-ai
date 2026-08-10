"""R102 — Cross-Frequency Funding Spread (pure cross-frequency, NON cross-sectional demean).

Per §C6-DISCOVERY-SPEC (2026-08-10, Minimax-C) and Jazz 2026-08-10拍板 "A = 现在做":
this is the only remaining truly-untested shape after R76/R77/R78/R79/R80/R81/R90/
R91/R93/R96 REFUTED the cross-sectional demean family and most cousin-shapes.

Why this is structurally different:
  R76  funding[t,a] - mean_a(funding[t,a])               cross-asset demean
  R102 cumsum_24h(funding)[t,a] - 6*cumsum_4h(funding)[t,a]  cross-frequency spread

The signal is NOT demean-of-X — it captures when the LOW-FREQUENCY funding
trajectory diverges from the HIGH-FREQUENCY trajectory within the same asset.
Interpretation: when 24h-cumulative funding moves DIFFERENTLY than 6×(4h-cumulative
funding), the divergence is either (a) micro-structure arbitrage inside the perp
or (b) market-maker positioning shifting at sub-daily cadence.

Per §C6-DISCOVERY-SPEC Gate 1 (anchor-acceptance, S-107):
  best-10-day share <60%; daily Sharpe <5; pos-day 50-80%.
Per Gate 2 (Lesson #43 leg-corr): max |corr| ≤ 0.30 vs R77 / R62 / R76.
Per Gate 3 (3-check): gross_t / 5bps_t / OOS_t all > 1.96.

Window: 1h tick funding from /Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding
        (47 perps, 2023-05-12 → 2026-07-19, 27390 rows / asset).
        Resample to 4h and 24h, compute cross-frequency spread, run k=3 tercile L/S
        across cadences × cost tiers.

FROZEN SPEC (no reparam after this commit):
  R102_RESAMPLE_FREQS = ('4h', '8h', '24h')
  R102_SPREAD_FAMILY  = (4h-24h, 8h-24h)  # pure cross-frequency, NOT demean
  R102_CADENCES       = (3, 5, 7, 14) days
  R102_COST_GRID      = (0, 5, 10, 20) bps
  R102_K_TERCILES     = 3
  R102_OOS_FRAC       = 0.30
  R102_MIN_DAYS       = 100  # per-asset coverage floor

Verdict grammar (one of):
  R102_SURVIVES                       — 3-check + Gate 1 + Gate 2 all pass
  R102_REFUTED_GATE1                  — anchor-acceptance failed
  R102_REFUTED_GATE2                  — leg-corr |corr|>0.30 vs any of R77/R62/R76
  R102_REFUTED_GATE3                  — 3-check failed (gross_t or 5bps_t or OOS_t ≤1.96)
  R102_INSUFFICIENT_COVERAGE          — fewer than 100 days for any asset
  R102_DATA_MISSING                   — funding 1h CSV not readable
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

PERIODS_PER_YEAR = 365

# === FROZEN SPEC (do not edit after this commit) ===========================
R102_RESAMPLE_FREQS = ('4h', '8h', '24h')
R102_SPREAD_FAMILY = (('4h', '24h'), ('8h', '24h'))
R102_CADENCES = (3, 5, 7, 14)
R102_COST_GRID = (0, 5, 10, 20)
R102_K_TERCILES = 3
R102_OOS_FRAC = 0.30
R102_MIN_DAYS = 100
# ===========================================================================


def load_funding_1h(funding_dir: Path,
                    assets: Optional[list] = None) -> pd.DataFrame:
    """Load all *_funding_1h.csv into a [datetime × asset] DataFrame of 1h funding rates.

    Returns NaN for missing rows; resample caller will fill.
    """
    if assets is None:
        files = sorted(funding_dir.glob("*_funding_1h.csv"))
        assets = [f.stem.replace("_funding_1h", "") for f in files]

    out = {}
    for a in assets:
        fp = funding_dir / f"{a}_funding_1h.csv"
        if not fp.exists():
            continue
        df = pd.read_csv(fp)
        if df.empty or "fundingRate" not in df.columns or "fundingTime" not in df.columns:
            continue
        df["dt"] = pd.to_datetime(df["fundingTime"], unit="ms")
        s = df.set_index("dt")["fundingRate"].sort_index()
        s = s[~s.index.duplicated(keep="last")]
        if len(s) < R102_MIN_DAYS * 24:
            continue
        out[a] = s
    if not out:
        return pd.DataFrame()
    wide = pd.concat(out, axis=1).sort_index()
    wide.columns = wide.columns.get_level_values(0)
    return wide


def cross_frequency_spread(funding_1h: pd.DataFrame, fast_freq: str,
                           slow_freq: str) -> pd.DataFrame:
    """Pure cross-frequency spread = cumsum_slow(funding) - scale * cumsum_fast(funding).

    fast_freq ∈ {'4h', '8h'}, slow_freq = '24h'.
    Scale: slow_period_hours / fast_period_hours = 6 for (4h,24h), 3 for (8h,24h).
    Aligns two series by reindexing fast to slow cadence via `.last()` per slow bar.

    Sign convention:
        spread > 0  ⇒ slow-cumulative > scaled-fast-cumulative ⇒
                       high-freq funding has been net positive relative to slow
                       (i.e. fast hours running "more long" than 24h average)
        spread < 0  ⇒ opposite (fast hours running "more short" / less positive)
    """
    fast_period_h = {'4h': 4, '8h': 8}[fast_freq]
    slow_period_h = 24
    scale = slow_period_h / fast_period_h

    # Resample: use SUM over each bar (funding is per-bar accrual). For 1h source,
    # 24h-sum = daily total funding, 4h-sum = 4h block total funding.
    cum_slow = funding_1h.resample(slow_freq).sum().cumsum()
    cum_fast = funding_1h.resample(fast_freq).sum().cumsum()
    # Align: for each slow bar, take the last fast-cumulative within or before it.
    cum_fast_aligned = cum_fast.reindex(cum_slow.index, method='ffill')
    spread = cum_slow - scale * cum_fast_aligned
    return spread


def score_cross_frequency(funding_1h: pd.DataFrame) -> pd.DataFrame:
    """Daily cross-frequency spread score = end-of-day value of cross_frequency_spread.

    Returns a [date × asset] DataFrame (index = daily timestamps).
    """
    panels = {}
    for fast, slow in R102_SPREAD_FAMILY:
        spread = cross_frequency_spread(funding_1h, fast, slow)
        # Take EOD value (24h bar ends at 00:00 of next day)
        daily = spread.resample('24h').last()
        panels[f"{fast}_{slow}"] = daily
    # Combine: average of (4h-24h) and (8h-24h) cross-frequency spreads.
    combined = sum(panels.values()) / len(panels)
    return combined


def tercile_ls(score: pd.DataFrame, returns: pd.DataFrame,
               k_terciles: int = R102_K_TERCILES) -> pd.DataFrame:
    """k-tercile long-short per day.

    score, returns aligned on index. Per-day: rank cross-section, long top,
    short bottom, equal-weight, return = (top - bottom) / 2.
    """
    aligned_idx = score.index.intersection(returns.index)
    score = score.loc[aligned_idx]
    returns = returns.loc[aligned_idx]
    out = []
    for dt in aligned_idx:
        s = score.loc[dt].dropna()
        if len(s) < k_terciles * 2:
            out.append(np.nan)
            continue
        ranks = s.rank(method='first')
        n = len(s)
        try:
            top_cut = ranks.quantile(1.0 - 1.0 / k_terciles)
            bot_cut = ranks.quantile(1.0 / k_terciles)
        except AttributeError:
            top_cut = np.nanpercentile(ranks, 100 * (1 - 1.0 / k_terciles))
            bot_cut = np.nanpercentile(ranks, 100 * (1.0 / k_terciles))
        top_assets = ranks[ranks >= top_cut].index
        bot_assets = ranks[ranks <= bot_cut].index
        if dt not in returns.index:
            out.append(np.nan)
            continue
        r = returns.loc[dt]
        long_ret = r[top_assets].mean() if len(top_assets) else 0.0
        short_ret = r[bot_assets].mean() if len(bot_assets) else 0.0
        if np.isnan(long_ret):
            long_ret = 0.0
        if np.isnan(short_ret):
            short_ret = 0.0
        out.append((long_ret - short_ret) / 2.0)
    return pd.Series(out, index=aligned_idx, name='ls')


def apply_rebal_with_cost(ls_daily: pd.Series, rebal_days: int,
                          cost_bps: float) -> pd.Series:
    """Apply rebalancing: only trade every `rebal_days` days. Cost = 2*cost_bps per flip.

    On non-rebal days, return is carried forward (compounded). On rebal days,
    if the previous position was different sign (long→short or short→long),
    subtract `2 * cost_bps * 2` (one-way cost times 2 legs).
    """
    out = ls_daily.copy().fillna(0.0)
    rebal_idx = np.arange(0, len(out), rebal_days)
    is_rebal = pd.Series(False, index=out.index)
    is_rebal.iloc[rebal_idx] = True

    # Track sign of position
    pos = pd.Series(0.0, index=out.index)
    cur_pos = 0.0
    for dt in out.index:
        if is_rebal.loc[dt]:
            target = np.sign(out.loc[dt])
            if target != cur_pos and target != 0.0:
                # Pay one-way cost on the leg being flipped.
                out.loc[dt] -= cost_bps * 0.0001 * 2  # 2-way flip
                cur_pos = target
        pos.loc[dt] = cur_pos
    return out


def compute_3check(returns: pd.Series, oos_frac: float = R102_OOS_FRAC) -> dict:
    """gross_t / 5bps_t / OOS_t + max DD + Sharpe + per-half stats."""
    r = returns.dropna()
    if len(r) < 30:
        return {"gross_t": float("nan"), "5bps_t": float("nan"), "OOS_t": float("nan"),
                "max_dd": float("nan"), "sharpe": float("nan"), "n_full": len(r)}
    # 5bps cost-adjusted
    r_5bps = r - 0.0005
    # OOS = last 30%
    cut = int(len(r) * (1.0 - oos_frac))
    r_full = r.iloc[:cut]
    r_oos = r.iloc[cut:]
    # t-stat (mean / std * sqrt(N))
    gross_t = r.mean() / r.std() * np.sqrt(len(r)) if r.std() > 0 else 0.0
    five_t = r_5bps.mean() / r_5bps.std() * np.sqrt(len(r_5bps)) if r_5bps.std() > 0 else 0.0
    oos_t = r_oos.mean() / r_oos.std() * np.sqrt(len(r_oos)) if len(r_oos) > 5 and r_oos.std() > 0 else 0.0
    # max DD
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum / peak - 1).min()
    return {
        "gross_t": float(gross_t),
        "5bps_t": float(five_t),
        "OOS_t": float(oos_t),
        "max_dd": float(dd),
        "sharpe": float(r.mean() / r.std() * np.sqrt(PERIODS_PER_YEAR)) if r.std() > 0 else 0.0,
        "ann_pct": float(r.mean() * PERIODS_PER_YEAR),
        "n_full": int(len(r)),
        "n_oos": int(len(r_oos)),
    }


def gate1_anchor_acceptance(ls_daily: pd.Series) -> dict:
    """Gate 1 anchor-acceptance per S-107.

    best-10-day share < 60% (no concentration)
    daily Sharpe < 5 (no microstructure masquerading as alpha)
    pos-day rate in [50%, 80%] (no over-fit, no tail bet)
    """
    r = ls_daily.dropna()
    if len(r) < 30:
        return {"best_10day_share": float("nan"), "daily_sharpe": float("nan"),
                "pos_day_rate": float("nan"), "passes": False,
                "reason": "insufficient_n"}
    sharpe = r.mean() / r.std() if r.std() > 0 else 0.0
    pos_day = (r > 0).mean()
    # best 10-day share
    best_10 = r.nlargest(10).sum()
    total_pos = r[r > 0].sum()
    best_10_share = best_10 / total_pos if total_pos > 0 else float("nan")
    passes = (best_10_share < 0.60) and (sharpe < 5.0) and (0.50 <= pos_day <= 0.80)
    reasons = []
    if best_10_share >= 0.60:
        reasons.append(f"best_10day_share={best_10_share:.2%}>=60%")
    if sharpe >= 5.0:
        reasons.append(f"daily_sharpe={sharpe:.2f}>=5")
    if pos_day < 0.50 or pos_day > 0.80:
        reasons.append(f"pos_day_rate={pos_day:.2%} out of [50%,80%]")
    return {"best_10day_share": float(best_10_share),
            "daily_sharpe": float(sharpe),
            "pos_day_rate": float(pos_day),
            "passes": bool(passes),
            "reason": "; ".join(reasons) if reasons else "ok"}


def gate2_leg_correlation(r102_returns: pd.Series,
                          existing_legs: dict) -> dict:
    """Gate 2 Lesson #43 leg-corr: max |corr| ≤ 0.30 vs each existing leg."""
    out = {"correlations": {}, "max_abs_corr": float("nan"), "passes": True}
    r = r102_returns.dropna()
    if len(r) < 30:
        out["passes"] = False
        out["reason"] = "insufficient_n"
        return out
    max_abs = 0.0
    for leg_name, leg_series in existing_legs.items():
        aligned = pd.concat([r.rename("r102"), leg_series.rename("leg")], axis=1).dropna()
        if len(aligned) < 30:
            continue
        corr = aligned["r102"].corr(aligned["leg"])
        out["correlations"][leg_name] = float(corr)
        max_abs = max(max_abs, abs(corr))
    out["max_abs_corr"] = float(max_abs)
    out["passes"] = max_abs <= 0.30
    if not out["passes"]:
        out["reason"] = f"max_abs_corr={max_abs:.3f} > 0.30"
    return out


def run(funding_dir: Path, returns_df: pd.DataFrame,
        r46_leg: Optional[pd.Series] = None,
        r62_leg: Optional[pd.Series] = None,
        r76_leg: Optional[pd.Series] = None) -> dict:
    """Full R102 pipeline.

    funding_dir: Path to *_funding_1h.csv directory
    returns_df:  [date × asset] daily perp returns (per-asset, NOT spot)
    """
    print("[R102] loading funding 1h...")
    funding_1h = load_funding_1h(funding_dir)
    if funding_1h.empty:
        return {"verdict": "R102_DATA_MISSING",
                "reason": "no funding 1h CSV readable from funding_dir"}
    print(f"[R102] funding 1h shape: {funding_1h.shape}, "
          f"range {funding_1h.index.min().date()} → {funding_1h.index.max().date()}")

    print("[R102] computing cross-frequency spread...")
    score = score_cross_frequency(funding_1h)
    # Cross-frequency spread is at 24h cadence; align to daily returns index.
    score_daily = score.resample('24h').last().dropna(how='all')
    # Tradeable assets = ∩(score assets, returns assets)
    tradeable = sorted(set(score_daily.columns) & set(returns_df.columns))
    if len(tradeable) < 6:
        return {"verdict": "R102_INSUFFICIENT_COVERAGE",
                "reason": f"only {len(tradeable)} tradeable assets"}
    score_daily = score_daily[tradeable].ffill().dropna(how='all')
    rets = returns_df[tradeable]
    print(f"[R102] {len(tradeable)} tradeable assets, "
          f"score range {score_daily.index.min().date()} → {score_daily.index.max().date()}")

    print("[R102] running cadence × cost grid...")
    grid = {}
    best_cell = None
    best_score = -np.inf
    for rebal in R102_CADENCES:
        for cost in R102_COST_GRID:
            ls_raw = tercile_ls(score_daily, rets)
            ls_after = apply_rebal_with_cost(ls_raw, rebal, cost)
            stats = compute_3check(ls_after)
            cell_key = f"rebal={rebal}d/cost={cost}bps"
            grid[cell_key] = stats
            # best by gross_t
            if stats["gross_t"] > best_score:
                best_score = stats["gross_t"]
                best_cell = cell_key

    best_stats = grid[best_cell]
    passes_3check = (best_stats["gross_t"] > 1.96 and
                     best_stats["5bps_t"] > 1.96 and
                     best_stats["OOS_t"] > 1.96)

    # Gate 1 on best cell
    ls_best_raw = tercile_ls(score_daily, rets)
    rebal_best = int(best_cell.split("rebal=")[1].split("d")[0])
    cost_best = float(best_cell.split("cost=")[1].split("bps")[0])
    ls_best_after = apply_rebal_with_cost(ls_best_raw, rebal_best, cost_best)
    g1 = gate1_anchor_acceptance(ls_best_after)

    # Gate 2: corr vs R46/R62/R76
    existing_legs = {}
    if r46_leg is not None:
        existing_legs["R46"] = r46_leg
    if r62_leg is not None:
        existing_legs["R62"] = r62_leg
    if r76_leg is not None:
        existing_legs["R76"] = r76_leg
    g2 = gate2_leg_correlation(ls_best_after, existing_legs) if existing_legs else \
        {"passes": True, "reason": "no_existing_legs_supplied", "max_abs_corr": float("nan")}

    if not g1["passes"]:
        verdict = "R102_REFUTED_GATE1"
    elif not g2["passes"]:
        verdict = "R102_REFUTED_GATE2"
    elif passes_3check:
        verdict = "R102_SURVIVES"
    else:
        verdict = "R102_REFUTED_GATE3"

    return {
        "verdict": verdict,
        "n_tradeable": len(tradeable),
        "score_range": [str(score_daily.index.min().date()),
                        str(score_daily.index.max().date())],
        "grid": grid,
        "best_cell": best_cell,
        "best_stats": best_stats,
        "passes_3check": bool(passes_3check),
        "gate1_anchor_acceptance": g1,
        "gate2_leg_correlation": g2,
        "spec_frozen": {
            "R102_RESAMPLE_FREQS": list(R102_RESAMPLE_FREQS),
            "R102_SPREAD_FAMILY": [list(x) for x in R102_SPREAD_FAMILY],
            "R102_CADENCES": list(R102_CADENCES),
            "R102_COST_GRID": list(R102_COST_GRID),
            "R102_K_TERCILES": R102_K_TERCILES,
            "R102_OOS_FRAC": R102_OOS_FRAC,
            "R102_MIN_DAYS": R102_MIN_DAYS,
        },
    }


def load_perp_returns(funding_dir: Path) -> pd.DataFrame:
    """Load perp 1d OHLCV close-to-close returns from same dir as funding 1h.

    Hyperliquid perp convention: 1d bars, midnight UTC open.
    Returns: [date × asset] daily close-to-close returns (decimal).
    """
    out = {}
    for fp in sorted(funding_dir.glob("*_1d_ohlcv.csv")):
        a = fp.stem.replace("_1d_ohlcv", "")
        df = pd.read_csv(fp)
        if df.empty or "close" not in df.columns or "openTime" not in df.columns:
            continue
        df["dt"] = pd.to_datetime(df["openTime"], unit="ms").dt.normalize()
        df = df.sort_values("dt")
        if len(df) < R102_MIN_DAYS:
            continue
        out[a] = pd.Series(df["close"].values, index=df["dt"]).pct_change()
    if not out:
        return pd.DataFrame()
    wide = pd.concat(out, axis=1).sort_index()
    wide.columns = wide.columns.get_level_values(0)
    return wide


def main():
    FUNDING_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")
    out_dir = Path(f"/Users/sbb/Projects/looloomi-ai/reports/r102_cross_frequency_funding/"
                   f"2026-08-11")
    out_dir.mkdir(parents=True, exist_ok=True)
    print("[R102] loading perp 1d returns...")
    perp_rets = load_perp_returns(FUNDING_DIR)
    if perp_rets.empty:
        result = {"verdict": "R102_DATA_MISSING",
                  "reason": "no perp 1d OHLCV CSV readable"}
    else:
        print(f"[R102] perp returns shape: {perp_rets.shape}, "
              f"range {perp_rets.index.min().date()} → {perp_rets.index.max().date()}")
        result = run(funding_dir=FUNDING_DIR, returns_df=perp_rets)
    with (out_dir / "verdict.json").open("w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"[R102] verdict={result.get('verdict')}")
    if "best_cell" in result:
        print(f"[R102] best_cell={result['best_cell']}")
        print(f"[R102] best_stats={result['best_stats']}")
    if "gate1_anchor_acceptance" in result:
        print(f"[R102] gate1={result['gate1_anchor_acceptance']}")
    if "gate2_leg_correlation" in result:
        print(f"[R102] gate2={result['gate2_leg_correlation']}")
    print(f"[R102] wrote {out_dir / 'verdict.json'}")


if __name__ == "__main__":
    main()
