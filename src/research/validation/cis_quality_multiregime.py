"""
R46 multi-regime extension — crypto proxy factor on 2022-2026 prices.
============================================================================
Owner: Seth, 2026-07-20. Triggered by R46 having only a 731-day window
(2024-06 → 2026-06). Per Jazz "继续深化研究" + "挖掘更远的窗口, 22年起," this
extends the diagnostic to **3 distinct macro regimes**: 2022 bear (BTC −65%
peak-to-trough), 2023 recovery (BTC +155%), 2024-2026 chop + melt-up + chop.

The constraint (per data survey 2026-07-20):
  * `/Volumes/.../data/ohlcv/*.parquet` only covers 2024-06-07 → 2026-06-07 (731d).
  * `/Volumes/.../looloomi-research/data/ohlcv/4h-spot/*.feather` covers 2017-08 →
    2026-07 for majors (BTC/ETH/BNB/LTC/ADA/XRP), 2019+ for mid, 2020+ for newer —
    i.e. **2022-2026 fully available for 14 majors** with 4h bars.

True CIS scores do NOT exist before 2024-03 (only monthly grade outcomes for 2022
in `cis_backtest_2022.json`). So for the pre-2024-03 window we run a **NO-CIS
QUALITY PROXY** that approximates the CIS signal from raw price/volume:

    proxy_quality(t, a) = sign-adjusted momentum + inverse-vol scaling
        = clip(zscore(trailing_90d_return − 0.5·trailing_30d_vol), −3, 3)

This is **not** identical to CIS but tests the SAME MECHANISM (cross-section L/S
on a quality-like score at multi-day cadence). If the proxy factor survives the
3-check gauntlet at 5-day rebal across 2022-2026, the MECHANISM is regime-agnostic,
not a 2024-2026 risk-on accident. On the overlapping window (2024-06 → 2026-06)
we run BOTH proxy and true CIS to compare signals.

Reuses cadence_ls, cadence_sweep, sub_period_absorption from cis_quality_robustness.

Output: reports/cis_quality_multiregime/<date>/{verdict.json, REPORT.md}

Compliance: positioning language only.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.cis_quality_robustness import (
    cadence_ls, cadence_sweep, sub_period_absorption,
)
from src.research.validation.cis_quality_absorption import load_cis_history_wide
from src.research.validation.factor_absorption import absorption_test

FEATHER_DIR = Path("/Volumes/CometCloudAI/looloomi-research/data/ohlcv/4h-spot")
CIS_HISTORY_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/cis_history")

# Asset universe with ≥2022-01-01 availability (14 majors from prior survey)
CRYPTO_UNIVERSE = ["BTC", "ETH", "BNB", "LTC", "ADA", "XRP", "LINK", "ATOM",
                   "DOGE", "SOL", "DOT", "UNI", "AVAX", "AAVE"]


def load_4h_to_daily(feather_dir: Path = FEATHER_DIR,
                     symbols: list = CRYPTO_UNIVERSE) -> pd.DataFrame:
    """Load all 4h-spot feathers, resample to daily close, return date × asset
    daily-returns matrix (date index = UTC date of the 4h bar, tz-naive)."""
    out = {}
    for sym in symbols:
        # assets stored as AAVE_USDT-4h-spot.feather — strip _USDT suffix
        candidates = list(feather_dir.glob(f"{sym}*4h-spot*"))
        if not candidates:
            print(f"  {sym}: no feather found, skipping")
            continue
        fp = candidates[0]
        df = pd.read_feather(fp, columns=["date", "close"])
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        daily = df.groupby(df["date"].dt.normalize())["close"].last().sort_index()
        out[sym] = daily
    prices = pd.DataFrame(out).sort_index().ffill()
    rets = prices.pct_change()
    return rets.dropna(how="all")


def compute_quality_proxy(daily_rets: pd.DataFrame,
                          lookback_ret: int = 90,
                          lookback_vol: int = 30) -> pd.DataFrame:
    """Per-asset quality proxy: positive trailing return minus inverse-volatility
    tilt, z-scored cross-section per day. Returns date × asset score matrix.

    Construction:
        raw_t = trailing_lookback_ret mean return − 0.5 · trailing_lookback_vol
                std of returns   (zero-mean cross-section per day)

    Lower (more negative) raw = "higher quality candidates" — long BOTTOM, short TOP
    is the L/S signal we want (mean-reversion tilt). Wait — this is REVERSAL style.
    For a momentum + low-vol quality L/S (long high CIS = long high quality), use
        raw_t = trailing_lookback_ret mean + 0.5 · (−trailing_vol_zscore)

    We use MOMENTUM + LOW-VOL because that's what "high CIS" practically proxies
    in a multi-pillar cross-section model. Reversal-tilt would test H22a-style
    which is a known loser (R22 in the ledger).
    """
    # trailing return (momentum)
    ret_mean = daily_rets.rolling(lookback_ret, min_periods=lookback_ret // 2).mean()
    # trailing vol
    vol = daily_rets.rolling(lookback_vol, min_periods=lookback_vol // 2).std()
    vol_inv = -vol  # low vol → high score (z-scored below)
    # raw score = momentum + inverse vol, equal weights
    raw = ret_mean + 0.5 * vol_inv
    # cross-section z-score per day
    raw_t = raw.sub(raw.mean(axis=1), axis=0).div(raw.std(axis=1).replace(0, np.nan), axis=0)
    return raw_t.clip(-3, 3)


def known_factors(rets: pd.DataFrame) -> tuple:
    """Return (f_market, f_momentum, known_arrs) for a rets matrix."""
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_arrs = {"market": f_market.values, "momentum": f_momentum.values}
    return f_market, f_momentum, known_arrs


def run_window(window_label: str, rets_window: pd.DataFrame,
               proxy_score: pd.DataFrame, cis_score: pd.DataFrame | None,
               cadences=(1, 3, 5, 7), cost_grid=(0.0, 5.0, 10.0)) -> dict:
    """Run cadence sweep on a single window for proxy + (optional) CIS."""
    tradeable = sorted(set(rets_window.columns) & set(proxy_score.columns))
    rets_w = rets_window[tradeable]
    _, _, known_arrs = known_factors(rets_w)
    proxy_w = proxy_score[tradeable]

    out = {"window": window_label, "n_days": len(rets_w),
           "n_assets": len(tradeable), "tradeable": tradeable,
           "cadence_proxy": {}, "cadence_cis": {}}

    # Proxy factor
    for cad in cadences:
        for bps in cost_grid:
            fac = cadence_ls(proxy_w, rets_w, rebal_days=cad,
                             cost_bps=bps).reindex(rets_w.index).fillna(0.0)
            r = absorption_test(fac.values, known_arrs, nw_lags=6, periods_per_year=365)
            out["cadence_proxy"][f"{cad}_{int(bps)}"] = {
                "alpha_t": r["alpha_t"], "alpha_ann_pct": r["alpha_ann_pct"],
                "raw_t": r["raw_t"], "raw_ann_pct": r["raw_ann_pct"],
                "alpha_significant": bool(r["alpha_significant"]),
                "r2": r["r2"],
            }

    # True CIS factor (only if available)
    if cis_score is not None:
        cis_tradeable = sorted(set(rets_window.columns) & set(cis_score.columns))
        if cis_tradeable:
            cis_w = cis_score[cis_tradeable]
            rets_cis = rets_window[cis_tradeable]
            _, _, known_cis = known_factors(rets_cis)
            for cad in cadences:
                for bps in cost_grid:
                    fac = cadence_ls(cis_w, rets_cis, rebal_days=cad,
                                     cost_bps=bps).reindex(rets_cis.index).fillna(0.0)
                    r = absorption_test(fac.values, known_cis, nw_lags=6, periods_per_year=365)
                    out["cadence_cis"][f"{cad}_{int(bps)}"] = {
                        "alpha_t": r["alpha_t"], "alpha_ann_pct": r["alpha_ann_pct"],
                        "raw_t": r["raw_t"], "raw_ann_pct": r["raw_ann_pct"],
                        "alpha_significant": bool(r["alpha_significant"]),
                        "r2": r["r2"],
                    }
    return out


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R46 multi-regime extension — crypto proxy 2022-2026 ===\n")

    print("Loading 4h-spot feathers → daily returns...")
    rets = load_4h_to_daily()
    print(f"  {rets.shape[0]} days  ×  {rets.shape[1]} assets  ·  "
          f"{rets.index.min().date()} → {rets.index.max().date()}\n")

    print("Computing quality proxy (momentum + inverse-vol)...")
    proxy = compute_quality_proxy(rets)
    print(f"  proxy shape: {proxy.shape}\n")

    # True CIS (overlapping window only)
    cis_long = load_cis_history_wide()
    cis_pivot = cis_long.pivot_table(index="date", columns="asset",
                                     values="cis_score")
    print(f"  true CIS: {cis_pivot.shape}\n")

    # Windows
    windows = [
        ("2022-01 → 2024-06 (bear + recovery + pre-CIS detail)",
         pd.Timestamp("2022-01-01"), pd.Timestamp("2024-06-01")),
        ("2024-06 → 2026-06 (CIS coverage, full R46 window)",
         pd.Timestamp("2024-06-07"), pd.Timestamp("2026-06-07")),
        ("2022-01 → 2026-06 (multi-regime full)",
         pd.Timestamp("2022-01-01"), pd.Timestamp("2026-06-07")),
    ]

    results = {}
    for label, s, e in windows:
        print(f"\n─── {label} ───\n")
        rets_w = rets.loc[(rets.index >= s) & (rets.index <= e)]
        proxy_w = proxy.loc[(proxy.index >= s) & (proxy.index <= e)]
        cis_w = (cis_pivot.loc[(cis_pivot.index >= s) & (cis_pivot.index <= e)]
                 if (cis_pivot.index.max() >= s and cis_pivot.index.min() <= e)
                 else None)
        if cis_w is not None and cis_w.empty:
            cis_w = None
        results[label] = run_window(label, rets_w, proxy_w, cis_w)

    out = {"windows": results, "asset_universe": list(rets.columns)}
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    report = format_report(out)
    (out_dir / "REPORT.md").write_text(report)
    print(report)
    print(f"\nSaved: {out_dir/'verdict.json'} + {out_dir/'REPORT.md'}")
    return out


def format_report(out: dict) -> str:
    L = []
    L.append("# R46 Multi-Regime Extension — Crypto Quality Proxy 2022-2026\n")
    L.append(f"**Asset universe:** {', '.join(out['asset_universe'])}  ·  "
             f"{len(out['asset_universe'])} crypto majors with 4h coverage from 2022-01\n")
    L.append("Per Jazz 2026-07-20 '挖掘更远的窗口, 22年起.' Constraint: true CIS scores "
             "do not exist before 2024-03; for pre-2024 we use a quality proxy "
             "(`trailing_90d_momentum + inverse_30d_vol`, cross-section z-scored). "
             "This tests the MECHANISM (cross-section L/S on a quality-like score at "
             "multi-day cadence), not CIS specifically. On the overlapping "
             "2024-06 → 2026-06 window we run proxy vs true CIS for cross-validation.\n")

    L.append("## Cadence × cost grid by window\n")
    L.append("`t` = Newey-West residual-α t-stat after {market, momentum}. "
             "**Bold** = clears t > 1.96.\n")

    for label, data in out["windows"].items():
        L.append(f"\n### {label}\n")
        L.append(f"n_days={data['n_days']}, n_assets={data['n_assets']}\n")

        # Proxy table
        L.append("**Quality proxy factor:**\n")
        L.append("| rebal (d) | 0 bps t | 5 bps t | 10 bps t |")
        L.append("|--:|--:|--:|--:|")
        for cad in (1, 3, 5, 7):
            ts = []
            for bps in (0.0, 5.0, 10.0):
                r = data["cadence_proxy"][f"{cad}_{int(bps)}"]
                t = r["alpha_t"]
                ts.append(f"**{t:+.2f}**" if r["alpha_significant"] else f"{t:+.2f}")
            L.append(f"| {cad} | {ts[0]} | {ts[1]} | {ts[2]} |")

        # CIS table if available
        if data["cadence_cis"]:
            L.append("\n**True CIS factor (only on overlapping window):**\n")
            L.append("| rebal (d) | 0 bps t | 5 bps t | 10 bps t |")
            L.append("|--:|--:|--:|--:|")
            for cad in (1, 3, 5, 7):
                ts = []
                for bps in (0.0, 5.0, 10.0):
                    r = data["cadence_cis"][f"{cad}_{int(bps)}"]
                    t = r["alpha_t"]
                    ts.append(f"**{t:+.2f}**" if r["alpha_significant"] else f"{t:+.2f}")
                L.append(f"| {cad} | {ts[0]} | {ts[1]} | {ts[2]} |")

    # ─── Synthesis ───
    L.append("\n## Synthesis (regime-agnostic test)\n")

    # Per-window best (proxy)
    for label, data in out["windows"].items():
        # find best cadence × cost for proxy
        best_key = None
        best_t = -np.inf
        for k, r in data["cadence_proxy"].items():
            if r["alpha_t"] > best_t:
                best_t = r["alpha_t"]
                best_key = k
        cad, bps = best_key.split("_")
        r_best = data["cadence_proxy"][best_key]
        tag = "✓ clears" if r_best["alpha_significant"] else "✗ fails"
        L.append(f"- **{label[:50]}...** proxy best = "
                 f"`rebal={cad}d, cost={bps}bps`  "
                 f"t={r_best['alpha_t']:+.2f}, ann={r_best['alpha_ann_pct']:+.1f}%/yr  "
                 f"({tag})")

    # Multi-regime verdict
    L.append("")
    windows_data = list(out["windows"].values())
    bear = windows_data[0]   # 2022-01 → 2024-06
    cis_win = windows_data[1]  # 2024-06 → 2026-06
    full = windows_data[2]    # 2022-01 → 2026-06

    # Best proxy t per window
    proxy_t_bear = max(r["alpha_t"] for r in bear["cadence_proxy"].values())
    proxy_t_cis = max(r["alpha_t"] for r in cis_win["cadence_proxy"].values())
    proxy_t_full = max(r["alpha_t"] for r in full["cadence_proxy"].values())

    L.append(f"- **Proxy best t per window**: bear ({proxy_t_bear:+.2f}) · "
             f"CIS ({proxy_t_cis:+.2f}) · full ({proxy_t_full:+.2f})")

    # True CIS on its overlapping window for cross-check
    if cis_win["cadence_cis"]:
        cis_t = max(r["alpha_t"] for r in cis_win["cadence_cis"].values())
        L.append(f"- **True CIS best t on overlapping window:** {cis_t:+.2f}  "
                 f"(proxy direction here: {proxy_t_cis:+.2f}; similar = proxy tracks CIS)")

    L.append("")
    # Survival assessment
    survival_5d_5bps_proxy = [
        bear["cadence_proxy"].get("5_5", {}).get("alpha_t", float("nan")),
        cis_win["cadence_proxy"].get("5_5", {}).get("alpha_t", float("nan")),
        full["cadence_proxy"].get("5_5", {}).get("alpha_t", float("nan")),
    ]
    n_clear = sum(1 for t in survival_5d_5bps_proxy if abs(t) > 1.96)
    L.append(f"- **5d-rebal / 5bps survival across windows (proxy):** "
             f"{sum(1 for t in survival_5d_5bps_proxy if t > 0)}/{len(survival_5d_5bps_proxy)} "
             f"positive; {n_clear}/3 clear the 1.96 bar.")

    if n_clear == 3:
        L.append("- **Mechanism is regime-agnostic** — the long-winners/short-losers "
                 "pattern at 5d rebal survives bear + chop + melt-up. This is the "
                 "strongest evidence the edge is real, not a 2024-2026 risk-on artifact.")
    elif n_clear == 0:
        L.append("- **Mechanism does NOT survive across regimes** — refutes the "
                 "hypothesis that the 2024-2026 edge generalizes. R46's 5d-rebal "
                 "finding is window-specific.")
    else:
        L.append(f"- **Partial survival** — works in {n_clear}/3 regimes. "
                 "Regime conditioning is essential, not optional.")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path,
                    default=Path(f"reports/cis_quality_multiregime/{datetime.now():%Y-%m-%d}"))
    args = ap.parse_args()
    run(args.out_dir)
