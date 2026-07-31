"""
R82 — pillar_A REGIME-GATED cross-sectional L/S (Seth, 2026-07-26).

Triggered by §DATA-ALIGN pillar-IC mining (2026-07-25):
  pillar_A is regime-CONDITIONAL, NOT regime-illusion.
  ✅ POSITIVE in RISK_ON, EASING (2024 + 2025), STAGFLATION (2025)
  🔴 NEGATIVE in TIGHTENING (2024), RISK_OFF-bear (2025 + 2026), EASING-bear (2026)
  By class: ✅ L1/L2/Infra on 2024-bull, 🔴 RWA on 2024-bull.

R73 (UN-gated pillar_A level L/S) REFUTED on the 28-asset 731-day panel (2024-06 →
2026-06) — but that panel is bear-dominated. R73's failure is HYPOTHESIZED to be a
regime artifact (W5 2026-bear rot), not a true factor-cancellation. R82 tests that
hypothesis by applying a regime-gate + class-scope TIER so that the bullish-regime
edge survives aggregation.

Methodology (mirrors R73 + R46 + R61 for honesty):
  - Score: pillar_A LEVEL (one-day lag PIT-safe ffill), NOT ΔA.
  - Universe: 34-asset 11yr CSV ∩ OHLCV (data-align aligned CSV, NOT the JSON dir).
    The 11yr CSV is the only source that carries pillar_a + macro_regime + asset_class.
  - Regime gate: only emit positions on days where trailing macro_regime ∈ allowed.
    Default ALLOWED = (RISK_ON, EASING, STAGFLATION). R73-BASELINE = ALL (no gate).
  - Class scope: only score assets whose asset_class ∈ ALLOWED. Default ALLOWED =
    (L1, L2, Infrastructure). R73-BASELINE = ALL classes.
  - K-terciles = 3; cadence = 5d (R46 winner); cost = 5bps (R46 frozen).
  - 3-check gauntlet: gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96.
  - Per-window W1-W6 attribution to verify W5 rotation-out (the regime gate's
    payload — W5 should be roughly zero).

Anti-imposter:
  - R73 reference (no gate) is the comparator. R82 must BEAT R73 on all 3 checks,
    not just survive.
  - Regime lookup is STRICTLY LAGGED (searchsorted side='right' on the regime
    dates); no forward look.
  - OOS is the last 30% (cut at 70%), identical to R73 split.

Verdict positioning:
  - ✅ SURVIVES — clears all 3 checks AND matched sign favors R63b direction
    (high_A_long) AND beats R73 on each check. Eligible for fusion-cell
    reconsideration at w_R82.
  - 🟡 PARTIAL — clears 2 of 3 OR clears but doesn't beat R73.
  - 🔴 REFUTED — fails 2+ checks OR R73 reference dominates.
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
    cadence_ls as _cadence_ls_re,
    estimate_turnover_ann,
    quarter_cuts,
    sub_period_absorption,
)
from src.research.validation.factor_absorption import absorption_test
from src.research.validation.w5_forensics import gauntlet_3check
from src.research.validation.cis_quality_absorption import load_daily_returns

# ── Constants ───────────────────────────────────────────────────────────────
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365
R82_K_TERCILES = 3
R82_CADENCE = 5
R82_COST_BPS = 5.0

# Regime gate (strict, bullish-only)
R82_REGIMES_ALLOWED_DEFAULT = ("RISK_ON", "EASING", "STAGFLATION")
R82_REGIMES_BLOCKED = ("TIGHTENING", "RISK_OFF")  # explicit bear

# Class scope (IC-positive on 2024_bull)
R82_CLASS_ALLOWED_DEFAULT = ("L1", "L2", "Infrastructure")

# Sign constants
SIGN_HIGH_A_LONG = "high_a_long"
SIGN_LOW_A_LONG = "low_a_long"
_VALID_SIGNS = {SIGN_HIGH_A_LONG, SIGN_LOW_A_LONG}

# Aligned-11yr CSV (the only source with pillar_a + regime + class)
ALIGNED_CSV = ROOT / "_data" / "cis_historical" / "cis_historical_11yr_aligned.csv"


# ── Loaders ────────────────────────────────────────────────────────────────
def load_aligned_cis(csv_path: Path = ALIGNED_CSV) -> pd.DataFrame:
    """Load the §DATA-ALIGN aligned 11yr CSV. Returns long form with _date col."""
    from src.research.data_align.cis_history_loader import load_cis_history
    return load_cis_history(csv_path, force_schema=True)


def pillar_a_wide(cis_long: pd.DataFrame) -> pd.DataFrame:
    """Pivot pillar_A long → wide (date × asset). PIT-safe ffill."""
    wide = cis_long.pivot(index="_date", columns="symbol", values="pillar_a").sort_index()
    return wide.ffill()


def regime_wide(cis_long: pd.DataFrame) -> pd.DataFrame:
    """Pivot macro_regime long → wide (date × asset). Each (date, asset) snapshot
    carries the regime that was RULING at that snapshot date. NOT forwarded forward
    on a per-asset basis — the regime is market-wide, so the column is uniform across
    a row's assets at a given date, but we don't pre-claim uniformity."""
    return cis_long.pivot(index="_date", columns="symbol", values="macro_regime").sort_index()


def asset_class_map(cis_long: pd.DataFrame) -> pd.Series:
    """Asset → asset_class (constant per asset)."""
    return cis_long.groupby("symbol")["asset_class"].first()


# ── PIT-safe regime lookup ─────────────────────────────────────────────────
def nearest_prior_regime(regime_dates: pd.DatetimeIndex,
                          regime_values: np.ndarray,
                          asof_date: pd.Timestamp) -> str | None:
    """Return regime at the closest date STRICTLY <= asof_date.
    No forward look. regime_values is a 1-D array aligned with regime_dates.

    For dates before the first regime entry, returns None (no regime known ⇒
    treat as blocked)."""
    if len(regime_dates) == 0:
        return None
    idx = regime_dates.searchsorted(asof_date, side="right") - 1
    if idx < 0:
        return None
    return str(regime_values[idx])


def per_day_regime_lookup(regime_wide: pd.DataFrame) -> pd.Series:
    """One regime per day (NOT per asset). The dataset is regime-classified at
    the DAILY level (BTC trailing 30d). Returns a Series indexed by date with
    regime as the value.

    Anti-imposter: if multiple assets carry different regimes on the same date,
    we use the modal regime (the regime that the majority of assets carry)."""
    # Mode per row
    modes = regime_wide.mode(axis=1)
    return modes.iloc[:, 0]


# ── Daily-allowed mask ─────────────────────────────────────────────────────
def daily_allowed_mask(score_wide: pd.DataFrame,
                        regime_per_day: pd.Series,
                        asset_class_map: pd.Series,
                        regimes_allowed: tuple = R82_REGIMES_ALLOWED_DEFAULT,
                        classes_allowed: tuple = R82_CLASS_ALLOWED_DEFAULT) -> pd.DataFrame:
    """Boolean (date × asset) mask. True if:
      (a) regime_per_day[date] ∈ regimes_allowed, AND
      (b) asset_class_map[asset] ∈ classes_allowed.

    For dates with no regime entry, mask=False (treat as blocked)."""
    # Class mask: 1D Series indexed by asset (reindexed to score_wide.columns)
    class_mask = (
        asset_class_map.reindex(score_wide.columns)
        .isin(classes_allowed)
        .fillna(False)
        .astype(bool)
    )
    # Regime mask: 1D Series indexed by date (reindexed to score_wide.index)
    allowed_set = set(regimes_allowed)
    regime_mask = (
        regime_per_day.reindex(score_wide.index)
        .isin(allowed_set)
        .fillna(False)
        .astype(bool)
    )
    # Broadcast: (date, asset) = regime_mask[date] AND class_mask[asset]
    mask = pd.DataFrame(
        np.outer(regime_mask.values, class_mask.values),
        index=score_wide.index,
        columns=score_wide.columns,
    )
    return mask


# ── Regime-gated L/S core ─────────────────────────────────────────────────
def regime_gated_ls(score_wide: pd.DataFrame,
                     rets: pd.DataFrame,
                     allowed_mask: pd.DataFrame,
                     *,
                     k_terciles: int = R82_K_TERCILES,
                     cost_bps: float = R82_COST_BPS,
                     rebal_days: int = R82_CADENCE,
                     sign: str = SIGN_HIGH_A_LONG) -> pd.Series:
    """R46 cadence_ls × per-day/per-asset allowed mask.

    On each rebal day:
      1. subset score_wide to allowed assets (mask[date] == True)
      2. rank → top-k / bot-k weights
      3. On non-rebal days: hold weights
      4. On disabled days (mask[date] is all False): PnL = 0
      5. cost charged only on rebal days when at least one enabled asset is held
    """
    if sign not in _VALID_SIGNS:
        raise ValueError(f"sign must be one of {_VALID_SIGNS}, got {sign!r}")
    flipped = -score_wide if sign == SIGN_LOW_A_LONG else score_wide

    common = sorted(set(flipped.columns) & set(rets.columns))
    if len(common) < 6:
        return pd.Series(0.0, index=rets.index)
    score = flipped[common]
    r = rets[common]
    mask = allowed_mask.reindex(columns=common).reindex(r.index).fillna(False)
    score_lag = score.reindex(r.index).ffill().shift(1)

    fac = pd.Series(0.0, index=r.index)
    prev_w = pd.Series(0.0, index=common)
    for i, date in enumerate(r.index):
        rr = r.loc[date].reindex(common).fillna(0.0)
        if i % rebal_days == 0:
            day_mask = mask.loc[date]
            allowed_assets = day_mask[day_mask].index.tolist()
            w = pd.Series(0.0, index=common)
            if len(allowed_assets) >= 6:
                s_row = score_lag.loc[date, allowed_assets].dropna()
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
                            w.loc[top] = 1.0 / len(top)
                            w.loc[bot] = -1.0 / len(bot)
            turnover = float((w - prev_w).abs().sum())
            fac.loc[date] = float((w * rr).sum()) - turnover * cost_bps / 1e4
            prev_w = w
        else:
            fac.loc[date] = float((prev_w * rr).sum())
    return fac


# ── Known factors for absorption ───────────────────────────────────────────
def build_known_factors(rets: pd.DataFrame, lookback: int = 30) -> dict:
    """Standard f_market (cross-section mean) + f_momentum (TSMOM 30d)."""
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).rolling(lookback, min_periods=lookback).apply(np.prod, raw=True) - 1
    f_momentum = (np.sign(cum) * f_market).fillna(0.0)
    return {"market": f_market.values, "momentum": f_momentum.values}


# ── Configuration sweep ─────────────────────────────────────────────────────
DEFAULT_CONFIGS = {
    "R82_strict_L1L2Infra": (
        R82_REGIMES_ALLOWED_DEFAULT, R82_CLASS_ALLOWED_DEFAULT,
    ),
    "R73_unrestricted_baseline": (
        ("RISK_ON", "RISK_OFF", "EASING", "TIGHTENING", "STAGFLATION", "GOLDILOCKS"),
        ("L1", "L2", "DeFi", "RWA", "Memecoin", "Gaming", "AI", "Infrastructure", "Commodity", "US Equity", "US Bond"),
    ),
    "R82_broad_regimes_strict_class": (
        R82_REGIMES_ALLOWED_DEFAULT + ("RISK_OFF",),
        R82_CLASS_ALLOWED_DEFAULT,
    ),
    "R82_strict_regimes_all_class": (
        R82_REGIMES_ALLOWED_DEFAULT,
        ("L1", "L2", "DeFi", "RWA", "Memecoin", "Gaming", "AI", "Infrastructure", "Commodity", "US Equity", "US Bond"),
    ),
}


def one_config_run(score_wide: pd.DataFrame,
                     rets: pd.DataFrame,
                     regime_per_day: pd.Series,
                     class_map: pd.Series,
                     regimes_allowed: tuple,
                     classes_allowed: tuple,
                     *,
                     sign: str = SIGN_HIGH_A_LONG) -> dict:
    """Run one (regime-set, class-set) configuration. Returns the sleeve series
    plus diagnostics."""
    mask = daily_allowed_mask(
        score_wide, regime_per_day, class_map,
        regimes_allowed=regimes_allowed, classes_allowed=classes_allowed,
    )
    fac = regime_gated_ls(score_wide, rets, mask, sign=sign)
    fac = fac.reindex(rets.index).fillna(0.0)
    return {"fac": fac, "mask": mask}


def config_gauntlet(score_wide: pd.DataFrame,
                     rets: pd.DataFrame,
                     regime_per_day: pd.Series,
                     class_map: pd.Series,
                     regimes_allowed: tuple,
                     classes_allowed: tuple,
                     *,
                     known_arrs: dict) -> dict:
    """3-check gauntlet for one config (both signs)."""
    # HIGH-A-LONG
    res_high = one_config_run(
        score_wide, rets, regime_per_day, class_map,
        regimes_allowed, classes_allowed, sign=SIGN_HIGH_A_LONG,
    )
    # LOW-A-LONG (reversed)
    res_low = one_config_run(
        score_wide, rets, regime_per_day, class_map,
        regimes_allowed, classes_allowed, sign=SIGN_LOW_A_LONG,
    )
    out = {}
    for label, res in (("high_a_long", res_high), ("low_a_long", res_low)):
        fac = res["fac"]
        r = absorption_test(fac.values, known_arrs, nw_lags=NW_LAGS,
                             periods_per_year=PERIODS_PER_YEAR)
        # 3-check: gross (cost=0), 5bps (cost=5), OOS (last 30%)
        costed_run = one_config_run(
            score_wide, rets, regime_per_day, class_map,
            regimes_allowed, classes_allowed, sign=(SIGN_HIGH_A_LONG if label == "high_a_long" else SIGN_LOW_A_LONG),
        )
        # Re-run with cost_bps=0 for the gross leg
        mask = res["mask"]
        fac_gross = regime_gated_ls(score_wide, rets, mask, cost_bps=0.0,
                                     sign=(SIGN_HIGH_A_LONG if label == "high_a_long" else SIGN_LOW_A_LONG))
        fac_gross = fac_gross.reindex(rets.index).fillna(0.0)
        r_gross = absorption_test(fac_gross.values, known_arrs, nw_lags=NW_LAGS,
                                    periods_per_year=PERIODS_PER_YEAR)
        # OOS: last 30%
        cut = int(len(rets) * (1 - OOS_FRAC))
        r_oos = absorption_test(fac.values[cut:], {k: v[cut:] for k, v in known_arrs.items()},
                                 nw_lags=NW_LAGS, periods_per_year=PERIODS_PER_YEAR)
        out[label] = {
            "gross_t": r_gross["alpha_t"],
            "gross_ann_pct": r_gross["alpha_ann_pct"],
            "5bps_t": r["alpha_t"],
            "5bps_ann_pct": r["alpha_ann_pct"],
            "oos_t": r_oos["alpha_t"],
            "oos_ann_pct": r_oos["alpha_ann_pct"],
            "oos_n": int(len(fac.values[cut:])),
        }
    # Matched-cell sign verdict
    h, l = out["high_a_long"], out["low_a_long"]
    matched_diff = (h["gross_t"] + h["5bps_t"] + h["oos_t"]) - (l["gross_t"] + l["5bps_t"] + l["oos_t"])
    sign_verdict = SIGN_HIGH_A_LONG if matched_diff > 0 else SIGN_LOW_A_LONG
    out["matched_diff"] = float(matched_diff)
    out["sign_verdict"] = sign_verdict
    return out


# ── Master run ──────────────────────────────────────────────────────────────
def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R82 — pillar_A regime-gated L/S ===\n")

    cis = load_aligned_cis()
    print(f"Loaded 11yr aligned CSV: {len(cis):,} rows × {cis['symbol'].nunique()} symbols × "
          f"{cis['_date'].nunique():,} dates")

    score_a = pillar_a_wide(cis)
    regime_w = regime_wide(cis)
    class_map = asset_class_map(cis)
    regime_per_day = per_day_regime_lookup(regime_w)
    print(f"Regime distribution (per day): {regime_per_day.value_counts().to_dict()}")
    print(f"Class distribution: {class_map.value_counts().to_dict()}")

    rets = load_daily_returns()
    common_dates = sorted(set(score_a.index) & set(rets.index))
    # Restrict to dates where we have both CIS data and OHLCV
    score_a = score_a.reindex(common_dates)
    rets = rets.reindex(common_dates)
    regime_per_day = regime_per_day.reindex(common_dates)
    print(f"Common panel: {len(common_dates):,} dates × {len(score_a.columns)} assets")

    known_arrs = build_known_factors(rets)

    # Run all configurations
    results = {}
    for cfg_name, (regs, classes) in DEFAULT_CONFIGS.items():
        print(f"\n--- {cfg_name} ---")
        print(f"  regimes_allowed: {regs}")
        print(f"  classes_allowed: {classes}")
        g = config_gauntlet(score_a, rets, regime_per_day, class_map,
                              regs, classes, known_arrs=known_arrs)
        results[cfg_name] = g
        h = g["high_a_long"]
        l = g["low_a_long"]
        print(f"  high_a_long: gross_t={h['gross_t']:+.2f}  5bps_t={h['5bps_t']:+.2f}  OOS_t={h['oos_t']:+.2f}")
        print(f"  low_a_long:  gross_t={l['gross_t']:+.2f}  5bps_t={l['5bps_t']:+.2f}  OOS_t={l['oos_t']:+.2f}")
        print(f"  matched-cell diff: {g['matched_diff']:+.3f}  → sign: {g['sign_verdict']}")

    # Verdict per config
    print("\n=== Verdict per config ===")
    ref = results["R73_unrestricted_baseline"]
    for cfg_name, g in results.items():
        v = g[g["sign_verdict"]]
        verdict = "✅ SURVIVES" if (v["gross_t"] > 1.96 and v["5bps_t"] > 1.96 and v["oos_t"] > 1.96) else (
            "🟡 PARTIAL" if (v["gross_t"] > 1.96) + (v["5bps_t"] > 1.96) + (v["oos_t"] > 1.96) >= 2 else "🔴 REFUTED"
        )
        g["verdict"] = verdict
        print(f"  {cfg_name}: {verdict}  (sign={g['sign_verdict']}, gross={v['gross_t']:+.2f}, "
              f"5bps={v['5bps_t']:+.2f}, OOS={v['oos_t']:+.2f})")

    # W5 rotation-out check on the strict config
    print("\n=== W5 rotation-out check (strict config) ===")
    strict = results["R82_strict_L1L2Infra"]
    # Use the high_a_long sign to compute per-window
    strict_fac = one_config_run(
        score_a, rets, regime_per_day, class_map,
        R82_REGIMES_ALLOWED_DEFAULT, R82_CLASS_ALLOWED_DEFAULT,
        sign=strict["sign_verdict"],
    )["fac"]
    windows = quarter_cuts(
        strict_fac.index[0], strict_fac.index[-1], n_windows=6,
    )
    sub = sub_period_absorption(strict_fac, known_arrs, windows, nw_lags=NW_LAGS,
                                  periods_per_year=PERIODS_PER_YEAR)
    for w in sub:
        print(f"  {w['label']}: n={w['n']}  α_t={w['alpha_t']:+.2f}  α_ann_pct={w['alpha_ann_pct']:+.2f}%")

    # Compile report
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_dates": int(len(common_dates)),
        "n_assets": int(len(score_a.columns)),
        "pipeline": "score=pillar_A, gate=regime∩class, abs=market+momentum",
        "configs": results,
        "w5_rotation_out": [
            {"label": w["label"], "n": w["n"],
             "alpha_t": float(w["alpha_t"]) if w["alpha_t"] is not None else None,
             "alpha_ann_pct": float(w["alpha_ann_pct"]) if w["alpha_ann_pct"] is not None else None}
            for w in sub
        ],
    }

    json_path = out_dir / "verdict.json"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {json_path}")
    return report


# ── CLI ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="R82 — pillar_A regime-gated L/S")
    ap.add_argument("--out-dir", type=Path,
                     default=ROOT / "reports" / "r82_pillar_a_regime_gated" /
                              datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()
    run(args.out_dir)


if __name__ == "__main__":
    main()
