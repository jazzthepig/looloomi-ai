"""
R89 — Perp-Spot Basis Sleeve (Seth, 2026-07-26).

Per user's pivot to "fundamentally different data shape" (option C), the structural
finding after 6 attempts (R82/R83/R85/R86/R87/R88) is FINAL: the 731-day panel is
bear-dominated for ANY single-strategy shape on OHLCV-only data. R89 = perp-spot
basis trade, which uses perp market microstructure (perp OHLCV + funding rates) that
the OHLCV-only strategies couldn't access.

Hypothesis:
  Basis = (perp_close - spot_close) / spot_close is the forward premium of perp over
  spot. When basis is WIDE and POSITIVE (strong contango), the perp trades at a premium
  and tends to UNDERPERFORM spot (mean reversion of the basis). When basis is WIDE
  and NEGATIVE (backwardation), perp tends to OUTPERFORM spot.

  Strategy:
    - basis > +threshold (e.g., +0.5%) → SHORT perp, LONG spot (basis mean reverts down)
    - basis < -threshold (e.g., -0.5%) → LONG perp, SHORT spot (basis mean reverts up)
    - |basis| < threshold → flat
  This is dollar-neutral by construction (every position is +1 spot / -1 perp or vice versa).

Data shape (FUNDAMENTALLY DIFFERENT from R77):
  - Spot OHLCV: /Volumes/CometCloudAI/data/ohlcv/{ASSET}.parquet (52 assets)
  - Perp 1d OHLCV: /Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding/{asset}_1d_ohlcv.csv (47 assets)
  - Funding 1h: /Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding/{asset}_funding_1h.csv (47 assets)
  - Overlap: 31 assets have both perp and spot (smaller than R77's 28, but DATA IS NEW)

Anti-imposter:
  - Perp-spot basis is a structural market-neutral trade that does NOT depend on
    cross-sectional rank or quality signal
  - 7-day rolling mean basis (smoothing) prevents whipsaw on noisy days
  - Threshold gates (0.5% default) prevent trading on tiny basis moves
  - Dollar-neutral by construction
  - Cost charged on full turnover (long + short leg both count)
  - Per-window W1-W6 attribution shows the regime-DEPENDENCE

Verdict grammar:
  ✅ SURVIVES = gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96 AND W5 sign-positive
  🟡 PARTIAL  = clears 2 of 3 (typically gross + 5bps but OOS weak)
  🔴 REFUTED = fails 2+ checks OR W5 catastrophic sign-flip
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.research.validation.cis_quality_robustness import (
    quarter_cuts,
    sub_period_absorption,
)
from src.research.validation.factor_absorption import absorption_test

# ── Frozen config ─────────────────────────────────────────────────────────────
# ⚠️ R89 REFUTED AS TRADEABLE (2026-07-26, cost-tier check) — TAKER-FEE ILLUSION.
#   At the 5bps used for the initial "SURVIVES" verdict, R89 clears 3/3
#   (gross_t=+5.51, 5bps_t=+3.62, OOS_t=+4.75). BUT R89 is a DAILY-REBALANCED
#   TWO-LEG (spot+perp) basis flip — realistic round-trip cost is 15–30bps
#   (perp-taker + spot-taker + slippage on BOTH legs). Cost-tier sweep:
#       5bps → 3/3  (OOS_ann +33.9%)   ← the only surviving tier
#      10bps → 1/3  (cost_t=−0.69, OOS_ann +1.9%)   ← already dead
#      20bps → 1/3  (OOS_ann −62.3%)
#      30bps → 1/3  (OOS_ann −126.4%)
#   NO cell survives at 10bps across the full threshold × cadence × lookback grid.
#   This is the SAME failure mode as R32 cash_carry ("+2.42 Sharpe is a taker-fee
#   illusion"). The edge lives entirely in the 5→10bps gap.
#   VERDICT: 🔴 REFUTED as a live strategy. Kept as a research artifact + the
#   lesson that basis/carry trades MUST pass a ≥10bps cost-tier gate before lock.
R89_BASIS_THRESHOLD = 0.003   # ±0.30% basis threshold for entry
R89_BASIS_LOOKBACK = 1        # 1d basis (no smoothing — fast microstructure)
R89_CAD = 1                   # 1-day rebal (basis is fast-moving)
R89_COST_BPS = 5.0            # ⚠️ UNREALISTIC for a two-leg daily flip — see above
R89_REALISTIC_COST_BPS = 10.0 # gate: two-leg trade must survive ≥10bps to be tradeable
R89_PER_LEG_WEIGHT = 1.0      # each leg is +1X (gross = 2.0 per position)
NW_LAGS = 6
PERIODS_PER_YEAR = 365
OOS_FRAC = 0.30

# Data paths
SPOT_OHLCV_DIR = Path("/Volumes/CometCloudAI/data/ohlcv")
PERP_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")


def load_spot_returns(panel_dates: pd.DatetimeIndex,
                      assets: list) -> pd.DataFrame:
    """Load spot returns for the given assets, aligned to panel_dates."""
    rets = pd.DataFrame(index=panel_dates)
    for asset in assets:
        fp = SPOT_OHLCV_DIR / f"{asset}.parquet"
        if not fp.exists():
            continue
        df = pd.read_parquet(fp)
        if "timestamp" in df.columns:
            df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None).dt.normalize()
        elif "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        else:
            continue
        daily = df.groupby("date")["close"].last().sort_index().pct_change()
        rets[asset] = daily.reindex(panel_dates)
    return rets


def load_perp_returns(panel_dates: pd.DatetimeIndex,
                      assets: list) -> pd.DataFrame:
    """Load perp returns for the given assets, aligned to panel_dates."""
    rets = pd.DataFrame(index=panel_dates)
    for asset in assets:
        fp = PERP_DIR / f"{asset.lower()}_1d_ohlcv.csv"
        if not fp.exists():
            continue
        df = pd.read_csv(fp)
        df["date"] = pd.to_datetime(df["openTime"], unit="ms").dt.normalize()
        daily = df.groupby("date")["close"].last().sort_index().pct_change()
        rets[asset] = daily.reindex(panel_dates)
    return rets


def load_perp_spot_basis(panel_dates: pd.DatetimeIndex,
                          assets: list,
                          lookback: int = R89_BASIS_LOOKBACK) -> pd.DataFrame:
    """Compute basis = (perp - spot) / spot for each asset, then 7d rolling mean."""
    basis_wide = pd.DataFrame(index=panel_dates)
    for asset in assets:
        spot_fp = SPOT_OHLCV_DIR / f"{asset}.parquet"
        perp_fp = PERP_DIR / f"{asset.lower()}_1d_ohlcv.csv"
        if not spot_fp.exists() or not perp_fp.exists():
            continue
        # Spot close
        spot_df = pd.read_parquet(spot_fp)
        if "timestamp" in spot_df.columns:
            spot_df["date"] = pd.to_datetime(spot_df["timestamp"]).dt.tz_localize(None).dt.normalize()
        else:
            spot_df["date"] = pd.to_datetime(spot_df["date"]).dt.tz_localize(None).dt.normalize()
        spot = spot_df.groupby("date")["close"].last().sort_index()

        # Perp close
        perp_df = pd.read_csv(perp_fp)
        perp_df["date"] = pd.to_datetime(perp_df["openTime"], unit="ms").dt.normalize()
        perp = perp_df.groupby("date")["close"].last().sort_index()

        # Align on common dates
        common = spot.index.intersection(perp.index)
        if len(common) < 30:
            continue
        spot_aligned = spot.reindex(common)
        perp_aligned = perp.reindex(common)
        basis = (perp_aligned - spot_aligned) / spot_aligned
        basis = basis.rolling(lookback, min_periods=lookback).mean()  # 7d rolling mean
        basis_wide[asset] = basis.reindex(panel_dates)
    return basis_wide


def perp_spot_ls(basis_wide: pd.DataFrame, spot_rets: pd.DataFrame, perp_rets: pd.DataFrame,
                  *, threshold: float = R89_BASIS_THRESHOLD,
                  rebal_days: int = R89_CAD,
                  cost_bps: float = R89_COST_BPS) -> pd.Series:
    """Perp-spot basis L/S.

    On rebal days: for each asset,
      - basis > +threshold → SHORT perp, LONG spot (per leg weight = -perp, +spot)
      - basis < -threshold → LONG perp, SHORT spot
      - |basis| < threshold → flat
    On other days: HOLD previous weights, no turnover, no cost.
    Returns daily PnL series."""
    common = sorted(set(basis_wide.columns) & set(spot_rets.columns) & set(perp_rets.columns))
    if len(common) < 2:
        return pd.Series(0.0, index=spot_rets.index)

    basis = basis_wide[common].ffill().shift(1)  # PIT-safe 1-day lag
    sr = spot_rets[common]
    pr = perp_rets[common]

    fac = pd.Series(0.0, index=sr.index)
    # Positions: per-asset (spot_weight, perp_weight) tuple
    spot_w = pd.Series(0.0, index=common)
    perp_w = pd.Series(0.0, index=common)
    prev_spot_w = pd.Series(0.0, index=common)
    prev_perp_w = pd.Series(0.0, index=common)

    for i, date in enumerate(sr.index):
        s_ret = sr.loc[date].reindex(common).fillna(0.0)
        p_ret = pr.loc[date].reindex(common).fillna(0.0)

        if i % rebal_days == 0:
            b_row = basis.loc[date].dropna()
            spot_w = pd.Series(0.0, index=common)
            perp_w = pd.Series(0.0, index=common)
            for asset in b_row.index:
                b = b_row[asset]
                if b > threshold:
                    # SHORT perp, LONG spot
                    spot_w[asset] = R89_PER_LEG_WEIGHT
                    perp_w[asset] = -R89_PER_LEG_WEIGHT
                elif b < -threshold:
                    # LONG perp, SHORT spot
                    spot_w[asset] = -R89_PER_LEG_WEIGHT
                    perp_w[asset] = R89_PER_LEG_WEIGHT
                # else: stay flat

            turnover = float((spot_w - prev_spot_w).abs().sum() +
                            (perp_w - prev_perp_w).abs().sum())
            pnl = float((spot_w * s_ret).sum() + (perp_w * p_ret).sum())
            cost = turnover * cost_bps / 1e4
            fac.loc[date] = pnl - cost
            prev_spot_w = spot_w.copy()
            prev_perp_w = perp_w.copy()
        else:
            fac.loc[date] = float((prev_spot_w * s_ret).sum() + (prev_perp_w * p_ret).sum())

    return fac


def build_known_factors(rets: pd.DataFrame, lookback: int = 30) -> dict:
    """Standard 2-factor absorption (market + TSMOM). NaN-safe via trailing fillna(0)."""
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).rolling(lookback, min_periods=lookback).apply(np.prod, raw=True) - 1
    f_momentum = (np.sign(cum) * f_market).fillna(0.0)
    return {"market": f_market.values, "momentum": f_momentum.values}


def run_one(fac: pd.Series, known: dict, oos_frac: float = OOS_FRAC) -> dict:
    cut = int(len(fac) * (1 - oos_frac))
    r_full = absorption_test(fac.values, known, nw_lags=NW_LAGS,
                              periods_per_year=PERIODS_PER_YEAR)
    r_oos = absorption_test(fac.values[cut:], {k: v[cut:] for k, v in known.items()},
                             nw_lags=NW_LAGS, periods_per_year=PERIODS_PER_YEAR)
    return {
        "full_t": r_full["alpha_t"],
        "full_ann_pct": r_full["alpha_ann_pct"],
        "oos_t": r_oos["alpha_t"],
        "oos_ann_pct": r_oos["alpha_ann_pct"],
        "oos_n": int(len(fac.values[cut:])),
    }


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R89 — Perp-Spot Basis Sleeve (perp microstructure trade) ===\n")
    print(f"Frozen config: threshold=±{R89_BASIS_THRESHOLD*100:.2f}%, "
          f"lookback={R89_BASIS_LOOKBACK}d, cad={R89_CAD}d, cost={R89_COST_BPS}bps\n")

    # ── Find universe (perp ∩ spot) ──────────────────────────────────────────
    perp_assets = set()
    for f in PERP_DIR.glob("*_1d_ohlcv.csv"):
        perp_assets.add(f.stem.replace("_1d_ohlcv", "").upper())
    spot_assets = set()
    for f in SPOT_OHLCV_DIR.glob("*.parquet"):
        spot_assets.add(f.stem.upper())
    common_assets = sorted(perp_assets & spot_assets)
    print(f"Universe: {len(common_assets)} assets (perp ∩ spot)")

    # ── Panel dates (use BTC as anchor) ──────────────────────────────────────
    spot_btc = pd.read_parquet(SPOT_OHLCV_DIR / "BTC.parquet")
    spot_btc["date"] = pd.to_datetime(spot_btc["timestamp"]).dt.tz_localize(None).dt.normalize()
    panel_dates = spot_btc["date"].sort_values().unique()
    panel_dates = pd.DatetimeIndex(panel_dates)
    panel_start = pd.Timestamp("2024-06-07")
    panel_end = pd.Timestamp("2026-06-07")
    panel_dates = panel_dates[(panel_dates >= panel_start) & (panel_dates <= panel_end)]
    print(f"Panel: {len(panel_dates)} days, {panel_dates[0].date()} → {panel_dates[-1].date()}")

    # ── Load spot and perp returns + basis ───────────────────────────────────
    spot_rets = load_spot_returns(panel_dates, common_assets)
    perp_rets = load_perp_returns(panel_dates, common_assets)
    basis_wide = load_perp_spot_basis(panel_dates, common_assets, lookback=R89_BASIS_LOOKBACK)
    spot_rets = spot_rets.dropna(axis=1, thresh=int(len(spot_rets) * 0.7))
    perp_rets = perp_rets.dropna(axis=1, thresh=int(len(perp_rets) * 0.7))
    basis_wide = basis_wide.dropna(axis=1, thresh=int(len(basis_wide) * 0.5))
    final_assets = sorted(set(spot_rets.columns) & set(perp_rets.columns) & set(basis_wide.columns))
    spot_rets = spot_rets[final_assets]
    perp_rets = perp_rets[final_assets]
    basis_wide = basis_wide[final_assets]
    print(f"After data filtering: {len(final_assets)} assets with both spot + perp + basis")

    # ── Build perp-spot basis sleeve (LOCKED config) ─────────────────────────
    print(f"\nBuilding R89 sleeve (LOCKED: cad={R89_CAD}d, "
          f"threshold=±{R89_BASIS_THRESHOLD*100:.2f}%, {R89_COST_BPS}bps) …")
    fac_5bps = perp_spot_ls(basis_wide, spot_rets, perp_rets,
                              threshold=R89_BASIS_THRESHOLD,
                              rebal_days=R89_CAD, cost_bps=R89_COST_BPS)
    fac_5bps = fac_5bps.reindex(panel_dates).fillna(0.0)
    fac_gross = perp_spot_ls(basis_wide, spot_rets, perp_rets,
                              threshold=R89_BASIS_THRESHOLD,
                              rebal_days=R89_CAD, cost_bps=0.0)
    fac_gross = fac_gross.reindex(panel_dates).fillna(0.0)

    # ── 3-check gauntlet ────────────────────────────────────────────────────
    known = build_known_factors(spot_rets)
    r_g = run_one(fac_gross, known, oos_frac=OOS_FRAC)
    r_5 = run_one(fac_5bps, known, oos_frac=OOS_FRAC)

    clears = (r_g["full_t"] > 1.96) + (r_5["full_t"] > 1.96) + (r_5["oos_t"] > 1.96)
    marker = "✅" if clears == 3 else ("🟡" if clears >= 2 else "🔴")
    print(f"\n=== 3-check gauntlet (LOCKED config) ===")
    print(f"  gross_t={r_g['full_t']:+.2f}  5bps_t={r_5['full_t']:+.2f}  "
          f"OOS_t={r_5['oos_t']:+.2f}  OOS_ann={r_5['oos_ann_pct']:+.1f}%  "
          f"OOS_n={r_5['oos_n']}  {clears}/3  {marker}")

    # ── COST-TIER SWEEP (R32 illusion gate — MANDATORY for basis/carry trades) ──
    # A two-leg (spot+perp) daily-rebalanced basis flip pays taker on BOTH legs.
    # Realistic round-trip is 15-30bps, not 5. Must survive ≥10bps to be tradeable.
    print(f"\n=== Cost-tier sweep (R32 taker-fee illusion gate) ===")
    cost_tiers = {}
    for c in (5.0, 10.0, 20.0, 30.0):
        fc = perp_spot_ls(basis_wide, spot_rets, perp_rets,
                          threshold=R89_BASIS_THRESHOLD, rebal_days=R89_CAD,
                          cost_bps=c).reindex(panel_dates).fillna(0.0)
        rc = run_one(fc, known, oos_frac=OOS_FRAC)
        cl = (r_g["full_t"] > 1.96) + (rc["full_t"] > 1.96) + (rc["oos_t"] > 1.96)
        cost_tiers[c] = {"cost_t": rc["full_t"], "oos_t": rc["oos_t"],
                          "oos_ann_pct": rc["oos_ann_pct"], "clears": int(cl)}
        print(f"  {c:>4.0f}bps  cost_t={rc['full_t']:+.2f}  OOS_t={rc['oos_t']:+.2f}  "
              f"OOS_ann={rc['oos_ann_pct']:+.1f}%  {cl}/3")
    survives_realistic = cost_tiers[R89_REALISTIC_COST_BPS]["clears"] == 3

    # ── Per-window W1-W6 attribution ────────────────────────────────────────
    windows = quarter_cuts(panel_dates[0], panel_dates[-1], n_windows=6)
    sub = sub_period_absorption(fac_5bps, known, windows, nw_lags=NW_LAGS,
                                  periods_per_year=PERIODS_PER_YEAR)
    print(f"\n=== W1-W6 attribution (5bps, perp-spot basis) ===")
    for w in sub:
        print(f"  {w['label']}: α_t={w['alpha_t']:+.2f}  α_ann_pct={w['alpha_ann_pct']:+.2f}%")

    # ── Verdict (gated on REALISTIC cost, not just 5bps) ─────────────────────
    if clears == 3 and survives_realistic:
        verdict = "✅ SURVIVES"
    elif clears == 3 and not survives_realistic:
        verdict = "🔴 REFUTED (taker-fee illusion — clears at 5bps, dies at ≥10bps)"
    elif clears >= 2:
        verdict = "🟡 PARTIAL"
    else:
        verdict = "🔴 REFUTED"
    print(f"\n  Verdict: {verdict}  (5bps {clears}/3; "
          f"10bps {cost_tiers[R89_REALISTIC_COST_BPS]['clears']}/3)")

    # ── Report ───────────────────────────────────────────────────────────────
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "panel": {
            "lo": str(panel_dates[0].date()),
            "hi": str(panel_dates[-1].date()),
            "n_days": int(len(panel_dates)),
            "n_assets": int(len(final_assets)),
        },
        "config": {
            "threshold": R89_BASIS_THRESHOLD,
            "basis_lookback": R89_BASIS_LOOKBACK,
            "cadence_days": R89_CAD,
            "cost_bps": R89_COST_BPS,
            "per_leg_weight": R89_PER_LEG_WEIGHT,
        },
        "data_sources": {
            "spot_ohlcv_dir": str(SPOT_OHLCV_DIR),
            "perp_ohlcv_dir": str(PERP_DIR),
            "perp_ohlcv_format": "1d, only close column",
            "funding_format": "1h, fundingTime + fundingRate",
        },
        "gauntlet": {
            "gross_t": r_g["full_t"],
            "5bps_t": r_5["full_t"],
            "oos_t": r_5["oos_t"],
            "oos_ann_pct": r_5["oos_ann_pct"],
            "oos_n": r_5["oos_n"],
            "clears": int(clears),
        },
        "cost_tier_sweep": {
            f"{c:.0f}bps": cost_tiers[c] for c in cost_tiers
        },
        "survives_realistic_10bps": bool(survives_realistic),
        "per_window_w1_w6": [
            {"label": w["label"],
             "alpha_t": float(w["alpha_t"]) if w["alpha_t"] is not None else None,
             "alpha_ann_pct": float(w["alpha_ann_pct"]) if w["alpha_ann_pct"] is not None else None}
            for w in sub
        ],
        "verdict": verdict,
    }
    json_path = out_dir / "verdict.json"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {json_path}")
    return report


def main():
    ap = argparse.ArgumentParser(description="R89 — Perp-Spot Basis Sleeve")
    ap.add_argument("--out-dir", type=Path,
                     default=ROOT / "reports" / "r89_perp_spot_basis" /
                              datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()
    run(args.out_dir)


if __name__ == "__main__":
    main()
