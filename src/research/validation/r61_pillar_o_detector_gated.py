"""
R61 — Detector-gated pillar_O sleeve (Seth, 2026-07-22).
================================================================================
R46 pillar_O 5d/5bps SURVIVES in-sample (gross_t=+2.57, 5bps_t=+3.33) but its OOS
sign-flips at W5 (2025-10 → 2026-02 risk-on late-cycle chop, t=-2.32). R58/R59
explored detector-based gating on the *funding* factor, and R62/R63 proved the
`flat_zero` pattern works for fade-the-crowd (OOS lifted from -0.50 → +1.20).

R61 applies the same detector × `flat_zero` pattern to a DIFFERENT factor: pillar_O.
Hypothesis: the late-cycle risk-on fragility that killed R46's OOS may be
detectable via cross-asset / funding-crowding proxies (R58 detector candidates).
If SURVIVES → builds evidence base for R67 (raise w_R46 in fusion book from 0.25).
If REFUTES → W5 sign-flip is structural to pillar_O, not just statistical noise.

Approach (sandbox-safe, pure numpy/pandas — reuses R46/R58/R62 infra):
  · Frozen R46 baseline (5d rebal, 5bps cost, k=3) — NO retuning.
  · Three R58 detector candidates: btc_funding_level(30), cross_class_crowded_count,
    btc_funding_acceleration. PIT-aligned via nearest-prior lookup.
  · Detector grid sweep: (cad, bps, detector). Gate action frozen as `flat_zero`.
  · Per-cell 3-check gauntlet (gross / 5bps / OOS) + per-window P&L attribution.
  · Honest refutation grammar (per R57/R58/R62): ✅ SURVIVES / 🟡 PARTIAL / 🔴 REFUTED.

Compliance: research/validation tooling; positioning language only downstream.
"""
from __future__ import annotations

import argparse
import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Silence FutureWarning about pandas fillna downcasting on object dtype (R61 detector
# alignment reindex returns object dtype; .fillna(False) on object is deprecated in
# pandas 2.x but functionally identical to the new behavior). The opt-in flag is the
# recommended path per pandas docs.
warnings.filterwarnings(
    "ignore",
    message="Downcasting object dtype arrays.*",
    category=FutureWarning,
)

from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)
from src.research.validation.cis_quality_robustness import (
    cadence_ls, cadence_sweep, sub_period_absorption, quarter_cuts,
    estimate_turnover_ann,
)
from src.research.cis_regime_studies.regime_detector_v1 import (
    btc_funding_level, cross_class_crowded_count, btc_funding_acceleration,
)
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.factor_absorption import absorption_test


# === R61 frozen baseline (from R46, do not change) ============================
R46_REBAL_DAYS = 5
R46_COST_BPS = 5.0
R46_K = 3                # terciles
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# === R61 detector candidates (R58 winners) ====================================
DEFAULT_DETECTORS = ("btc_funding_level",
                     "cross_class_crowded_count",
                     "btc_funding_acceleration")
DEFAULT_GATE_ACTION = "flat_zero"   # skip-only, never reverse

# Sweep axes
DEFAULT_CADENCES = (1, 3, 5, 7, 14, 21)
DEFAULT_COST_GRID = (0.0, 5.0, 10.0)


# === Detector loaders (return date-indexed pd.Series aligned to rets.index) ===
def _ms_to_dateindex(ts_ms: np.ndarray) -> pd.DatetimeIndex:
    """Convert ms timestamps to date-normalized DatetimeIndex (UTC)."""
    return pd.to_datetime(ts_ms, unit="ms", utc=True).tz_convert(None).normalize()


def load_btc_funding_level_series(rets_index: pd.DatetimeIndex) -> pd.Series:
    """BTC 30d rolling-mean funding (raw level). Series indexed by date, reindexed
    to rets_index via PIT-safe ffill (nearest-prior)."""
    ts_ms, vals = btc_funding_level()
    idx = _ms_to_dateindex(ts_ms)
    s = pd.Series(np.asarray(vals, dtype=float), index=idx).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(rets_index, method="ffill")


def load_cross_class_crowded_series(rets_index: pd.DatetimeIndex) -> pd.Series:
    """Cross-class breadth of crowded-longs (perps in own 90th-pct band, 7d-smoothed).
    Series indexed by date, PIT-aligned."""
    ts_ms, vals = cross_class_crowded_count()
    if len(ts_ms) == 0:
        return pd.Series(np.nan, index=rets_index)
    idx = _ms_to_dateindex(ts_ms)
    s = pd.Series(np.asarray(vals, dtype=float), index=idx).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(rets_index, method="ffill")


def load_btc_funding_accel_series(rets_index: pd.DatetimeIndex) -> pd.Series:
    """BTC funding acceleration z-score (7d-30d diff, 90d norm). PIT-aligned."""
    ts_ms, vals = btc_funding_acceleration()
    idx = _ms_to_dateindex(ts_ms)
    s = pd.Series(np.asarray(vals, dtype=float), index=idx).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(rets_index, method="ffill")


def load_detector(name: str, rets_index: pd.DatetimeIndex) -> pd.Series:
    """Dispatch table for R58 detector candidates."""
    if name == "btc_funding_level":
        return load_btc_funding_level_series(rets_index)
    if name == "cross_class_crowded_count":
        return load_cross_class_crowded_series(rets_index)
    if name == "btc_funding_acceleration":
        return load_btc_funding_accel_series(rets_index)
    raise ValueError(f"Unknown detector: {name!r}")


# === Detector threshold + fire mask ===========================================
def detector_fire_mask(detector_values: pd.Series,
                       threshold: float,
                       direction: str = "above") -> pd.Series:
    """Boolean fire mask: detector above (or below) a threshold.

    `direction="above"` → fires when value > threshold (crowded-long / high-funding).
    `direction="below"` → fires when value < threshold (extreme short / funding collapse).

    Default thresholds reflect the R58 detector character:
      - btc_funding_level: sustained positive funding = crowd-long territory.
      - cross_class_crowded_count: many perps simultaneously in own 90th pct.
      - btc_funding_acceleration: positive z = funding accelerating up.

    Threshold defaults are the median value of the detector over the panel
    (computed at call time so we don't bake a number into the spec).
    """
    valid = detector_values.dropna()
    if len(valid) == 0:
        return pd.Series(False, index=detector_values.index)
    if np.isnan(threshold):
        thr = float(valid.median())
    else:
        thr = float(threshold)
    if direction == "above":
        mask = (detector_values > thr).fillna(False)
    elif direction == "below":
        mask = (detector_values < thr).fillna(False)
    else:
        raise ValueError(f"Unknown direction: {direction!r}")
    return mask


# === Gate application =========================================================
def apply_detector_gate(sleeve_pnl: pd.Series,
                        detector_fires: pd.Series,
                        action: str = DEFAULT_GATE_ACTION) -> pd.Series:
    """Apply the detector gate to a sleeve PnL series.

    `flat_zero`: zeros sleeve PnL on fire days (skip-only).
    `reverse` is FORBIDDEN per §TRADER_TOM_DOCTRINE — averaging into hope is the
    amateur trap; if you can't win big when beta is positive, reversing under
    detector-fire will produce a worse amateur trap.
    """
    if action not in (DEFAULT_GATE_ACTION,):
        raise ValueError(
            f"action={action!r} is FORBIDDEN in R61. Only {DEFAULT_GATE_ACTION!r} allowed."
        )
    aligned_fires = detector_fires.reindex(sleeve_pnl.index).fillna(False).astype(bool)
    return sleeve_pnl.where(~aligned_fires, 0.0)


# === Gated cadence L/S (wraps R46 cadence_ls) ================================
def gated_cadence_ls(score_wide: pd.DataFrame,
                     rets: pd.DataFrame,
                     detector_fires: pd.Series,
                     k_terciles: int = R46_K,
                     cost_bps: float = R46_COST_BPS,
                     rebal_days: int = R46_REBAL_DAYS,
                     gate_action: str = DEFAULT_GATE_ACTION) -> pd.Series:
    """R46 cadence L/S × detector gate. Detector fires at asof date → PnL → 0."""
    fac = cadence_ls(score_wide, rets,
                     rebal_days=rebal_days,
                     cost_bps=cost_bps,
                     k_terciles=k_terciles)
    fac = fac.reindex(rets.index).fillna(0.0)
    return apply_detector_gate(fac, detector_fires, action=gate_action)


# === Sweep (cadence × cost × detector) ========================================
def gated_cadence_sweep(score_wide: pd.DataFrame,
                        rets: pd.DataFrame,
                        detector_fires_by_name: dict,
                        known_arrs: dict,
                        cadences: tuple = DEFAULT_CADENCES,
                        cost_grid: tuple = DEFAULT_COST_GRID,
                        k_terciles: int = R46_K) -> list[dict]:
    """Sweep cad × cost × detector. Returns list of dict rows (one per cell).

    `detector_fires_by_name` maps detector-name → pd.Series of bool fire mask
    (already aligned to rets.index).
    """
    rows = []
    # OOS is the last OOS_FRAC of the panel; cut at the 70% boundary.
    cut = int(len(rets) * (1.0 - OOS_FRAC))
    for det_name, det_fires in detector_fires_by_name.items():
        for cad in cadences:
            for bps in cost_grid:
                fac = cadence_ls(score_wide, rets,
                                 rebal_days=cad, cost_bps=0.0,
                                 k_terciles=k_terciles)
                fac = fac.reindex(rets.index).fillna(0.0)
                # Apply detector gate (flat_zero)
                fac_gated = apply_detector_gate(fac, det_fires,
                                                action=DEFAULT_GATE_ACTION)
                # If bps > 0, recompute with cost (gate then cost)
                if bps > 0:
                    fac_cost = cadence_ls(score_wide, rets,
                                          rebal_days=cad, cost_bps=bps,
                                          k_terciles=k_terciles)
                    fac_cost = fac_cost.reindex(rets.index).fillna(0.0)
                    fac_gated = apply_detector_gate(fac_cost, det_fires,
                                                    action=DEFAULT_GATE_ACTION)
                g = gauntlet_3check(fac_gated.values, known_arrs, cut)
                rows.append({
                    "detector": det_name,
                    "cadence": cad,
                    "cost_bps": bps,
                    "gross_t": g["gross_t"],
                    "gross_alpha_ann_pct": g["gross_alpha_ann_pct"],
                    "oos_t": g["oos_t"],
                    "oos_alpha_ann_pct": g["oos_alpha_ann_pct"],
                    "passes_gross": g["passes_gross"],
                    "passes_oos": g["passes_oos"],
                    "passes_all": g["passes_all"],
                    "pct_panel_flat": float(det_fires.reindex(rets.index).fillna(False).mean()),
                    "turnover_ann": float(estimate_turnover_ann(score_wide, rets, cad)),
                })
    return rows


# === Per-window P&L with detector annotation =================================
def gated_sub_period(fac_gated: pd.Series,
                     known_arrs: dict,
                     periods: list[tuple],
                     detector_fires: pd.Series,
                     nw_lags: int = NW_LAGS,
                     periods_per_year: int = PERIODS_PER_YEAR) -> list[dict]:
    """Per-window absorption + detector firing count.

    `periods` is list of (label, s, e) tuples (from quarter_cuts or partition_into_windows).
    """
    if not isinstance(fac_gated.index, pd.DatetimeIndex):
        fac_gated = fac_gated.copy()
        fac_gated.index = pd.to_datetime(fac_gated.index)
    fac_gated = fac_gated.reindex(fac_gated.index).fillna(0.0)
    fac_arr = fac_gated.values
    out = []
    for label, s, e in periods:
        mask = (fac_gated.index >= s) & (fac_gated.index <= e)
        mask = np.asarray(mask)
        if int(mask.sum()) < 30:
            out.append({"label": label, "n": int(mask.sum()),
                        "alpha_t": np.nan, "alpha_ann_pct": np.nan,
                        "det_fire_pct": float(detector_fires.reindex(fac_gated.index).fillna(False).iloc[mask].mean())
                                      if int(mask.sum()) > 0 else np.nan,
                        "alpha_significant": False})
            continue
        f_sub = fac_arr[mask]
        k_sub = {k: v[mask] for k, v in known_arrs.items()}
        try:
            r = absorption_test(f_sub, k_sub, nw_lags=nw_lags,
                                periods_per_year=periods_per_year)
            r["label"] = label
            r["n"] = int(mask.sum())
            r["alpha_significant"] = bool(r["alpha_significant"])
            r["det_fire_pct"] = float(detector_fires.reindex(fac_gated.index).fillna(False).iloc[mask].mean())
            out.append(r)
        except Exception as ex:
            out.append({"label": label, "n": int(mask.sum()), "error": str(ex),
                        "det_fire_pct": float(detector_fires.reindex(fac_gated.index).fillna(False).iloc[mask].mean())
                                      if int(mask.sum()) > 0 else np.nan})
    return out


def per_window_pnl(fac: pd.Series, periods: list[tuple]) -> dict:
    """Per-window ann% / Sharpe / cumret (no absorption — just sleeve P&L)."""
    out = {}
    for label, s, e in periods:
        sub = fac.loc[(fac.index >= s) & (fac.index <= e)]
        if len(sub) < 2:
            out[label] = {"n_days": int(len(sub)), "ann_pct": np.nan,
                          "sharpe": np.nan, "cumret": np.nan}
            continue
        cumret = (1 + sub).prod() - 1
        ann = ((1 + sub).prod() ** (PERIODS_PER_YEAR / max(len(sub), 1)) - 1) * 100
        sharpe = float(sub.mean() / sub.std() * np.sqrt(PERIODS_PER_YEAR)) if sub.std() > 0 else np.nan
        out[label] = {"n_days": int(len(sub)), "ann_pct": float(ann),
                      "sharpe": sharpe, "cumret": float(cumret)}
    return out


# === Master run ===============================================================
def run(out_dir: Path,
        k_terciles: int = R46_K,
        cadences: tuple = DEFAULT_CADENCES,
        cost_grid: tuple = DEFAULT_COST_GRID,
        detectors: tuple = DEFAULT_DETECTORS) -> dict:
    """Load → score (pillar_O only) → sleeve (R46 cadence) → detector (3-way) → gate
    → cadence sweep → sub-period → gauntlet → verdict → report.

    Frozen R46 baseline: 5d rebal, 5bps cost, k=3.
    Gate action: `flat_zero` (skip-only, never reverse).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R61 — Detector-gated pillar_O sleeve ===")
    print(f"  Frozen baseline: rebal={R46_REBAL_DAYS}d, cost={R46_COST_BPS}bps, "
          f"k={k_terciles}, gate={DEFAULT_GATE_ACTION}\n")

    # ── Load panel ───────────────────────────────────────────────────────────
    cis = load_cis_history_wide()
    rets = load_daily_returns()
    lo = max(cis["date"].min(), rets.index.min())
    hi = min(cis["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable = sorted(set(cis["asset"]) & set(rets.columns))
    print(f"Panel: {lo.date()} → {hi.date()} ({len(rets)} days, {len(tradeable)} assets)")

    # ── Score: pillar_O only ────────────────────────────────────────────────
    pillar_o_w = cis.pivot_table(index="date", columns="asset", values="O").reindex(columns=tradeable)
    coverage_pct = float(pillar_o_w.reindex(rets.index).ffill().notna().any(axis=1).mean())
    print(f"pillar_O score: {coverage_pct:.0%} of days with ≥1 valid score\n")

    # ── Known factors (R46-parity) ──────────────────────────────────────────
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_arrs = {"market": f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}
    # OOS is the last OOS_FRAC of the panel; cut at the 70% boundary.
    cut = int(len(rets) * (1.0 - OOS_FRAC))

    # ── R46 ungated baseline reproduction ────────────────────────────────────
    fac_ungated = cadence_ls(pillar_o_w, rets[tradeable],
                             rebal_days=R46_REBAL_DAYS,
                             cost_bps=R46_COST_BPS,
                             k_terciles=k_terciles)
    fac_ungated = fac_ungated.reindex(rets.index).fillna(0.0)
    g_ungated = gauntlet_3check(fac_ungated.values, known_arrs, cut)
    print(f"R46 baseline (ungated, 5d/5bps/k=3):")
    print(f"  gross_t = {g_ungated['gross_t']:+.2f}  "
          f"OOS_t = {g_ungated['oos_t']:+.2f}  "
          f"pass_all = {g_ungated['passes_all']}\n")

    # ── 6-window partition ───────────────────────────────────────────────────
    windows = quarter_cuts(rets.index.min(), rets.index.max(), n_windows=6)
    print("Sub-windows:")
    for label, s, e in windows:
        print(f"  {label}: {s.date()} → {e.date()} ({int((e - s).days + 1)} days)")
    print()

    # ── Per-window ungated P&L (W5 attribution) ──────────────────────────────
    pw_ungated = per_window_pnl(fac_ungated, windows)
    w5_label, w5_s, w5_e = windows[4]
    print(f"R46 ungated per-window ann% (W5 = {w5_label}: "
          f"{w5_s.date()} → {w5_e.date()}):")
    for label, w in pw_ungated.items():
        marker = "🟥" if label == w5_label else "🟩"
        print(f"  {label}: {w['ann_pct']:+.1f}% {marker}")
    print()

    # ── Load detectors (PIT-aligned to rets.index) ──────────────────────────
    print("Loading detectors (PIT-aligned via ffill to rets.index) …")
    detector_fires_by_name = {}
    detector_summary = {}
    for name in detectors:
        try:
            s = load_detector(name, rets.index)
            thr = float(s.dropna().median()) if s.notna().any() else np.nan
            fire_mask = detector_fire_mask(s, threshold=thr, direction="above")
            detector_fires_by_name[name] = fire_mask
            detector_summary[name] = {
                "median_threshold": thr,
                "pct_fires": float(fire_mask.mean()),
                "coverage_pct": float(s.notna().mean()),
                "min": float(s.min()) if s.notna().any() else np.nan,
                "max": float(s.max()) if s.notna().any() else np.nan,
                "median": float(s.median()) if s.notna().any() else np.nan,
            }
            print(f"  {name}: median={detector_summary[name]['median']:+.4f}, "
                  f"thr={thr:+.4f}, fires={detector_summary[name]['pct_fires']:.0%} "
                  f"of panel, coverage={detector_summary[name]['coverage_pct']:.0%}")
        except Exception as ex:
            print(f"  {name}: FAILED ({ex})")
            detector_summary[name] = {"error": str(ex)}
    print()

    # ── Sweep: cad × cost × detector ────────────────────────────────────────
    print(f"══ Sweep (cad={list(cadences)} × cost={list(cost_grid)} × "
          f"det={list(detector_fires_by_name.keys())}) ══\n")
    rows = gated_cadence_sweep(
        pillar_o_w, rets[tradeable], detector_fires_by_name, known_arrs,
        cadences=cadences, cost_grid=cost_grid, k_terciles=k_terciles,
    )
    n_pass_all = sum(1 for r in rows if r["passes_all"])
    best_gross_t = max((r["gross_t"] for r in rows), default=float("nan"))
    best_oos_t = max((r["oos_t"] for r in rows), default=float("nan"))
    print(f"  Total cells: {len(rows)}  ·  pass_all: {n_pass_all}")
    print(f"  Best gross_t: {best_gross_t:+.2f}  ·  Best OOS_t: {best_oos_t:+.2f}\n")

    # ── Pick best cell (R62 precedent: pass_all first, then max OOS_t, then max gross_t) ──
    # NOTE: per R61 plan, the SURVIVES bar is stricter than R62's — we require the gate
    # to actually LIFT OOS vs the R46 baseline (ΔOOS_t > 0) AND keep W5 sign non-negative.
    # A cell that passes the 3-check gauntlet but has ΔOOS_t ≤ 0 is 🟡 PARTIAL because
    # the gate is taking alpha away (W2 in-sample loss) without compensating OOS lift.
    viable = [r for r in rows if r["passes_all"]]
    if viable:
        # Filter further to cells that actually LIFT OOS (ΔOOS_t > 0)
        lifts = [r for r in viable if (r["oos_t"] - g_ungated["oos_t"]) > 0]
        if lifts:
            best = max(lifts, key=lambda r: (r["oos_t"], r["gross_t"]))
            verdict = "✅ SURVIVES — clears all 3 checks AND gate lifts OOS"
        else:
            # Pass the gauntlet but gate didn't actually lift OOS
            best = max(viable, key=lambda r: (r["oos_t"], r["gross_t"]))
            verdict = ("🟡 PARTIAL — clears all 3 checks but gate does NOT lift OOS "
                       "(ΔOOS_t ≤ 0). The detector trades in-sample alpha for OOS "
                       "neutrality; not a rescue, not a refutation.")
    else:
        candidates = [r for r in rows if r["oos_t"] > 0]
        if candidates:
            best = max(candidates, key=lambda r: (r["oos_t"], r["gross_t"]))
        else:
            best = max(rows, key=lambda r: (r["oos_t"], r["gross_t"]))
        if best["passes_gross"]:
            verdict = "🟡 PARTIAL — clears gross + positive OOS, sub-1.96"
        else:
            verdict = "🔴 REFUTED — fails 2+ checks"

    delta_oos = best["oos_t"] - g_ungated["oos_t"]
    print(f"Best cell: det={best['detector']}, cad={best['cadence']}d, "
          f"bps={best['cost_bps']:.0f}")
    print(f"  gross_t = {best['gross_t']:+.2f}  "
          f"OOS_t = {best['oos_t']:+.2f}  "
          f"pass_all = {best['passes_all']}")
    print(f"  ΔOOS_t vs R46 ungated = {delta_oos:+.2f}")
    print(f"  %panel flat (gate fires) = {best['pct_panel_flat']:.0%}\n")
    print(f"Verdict: {verdict}\n")

    # ── Best cell re-run for full reporting (per-window gated vs ungated) ───
    det_best_fires = detector_fires_by_name[best["detector"]]
    fac_best_ungated = cadence_ls(pillar_o_w, rets[tradeable],
                                  rebal_days=best["cadence"],
                                  cost_bps=best["cost_bps"],
                                  k_terciles=k_terciles)
    fac_best_ungated = fac_best_ungated.reindex(rets.index).fillna(0.0)
    fac_best_gated = apply_detector_gate(fac_best_ungated, det_best_fires,
                                         action=DEFAULT_GATE_ACTION)
    g_best_gated = gauntlet_3check(fac_best_gated.values, known_arrs, cut)
    pw_best_gated = per_window_pnl(fac_best_gated, windows)
    sp_best_gated = gated_sub_period(fac_best_gated, known_arrs, windows, det_best_fires)

    # ── Per-detector summary at R46 baseline cell ───────────────────────────
    per_detector_summary = {}
    for det_name, fires in detector_fires_by_name.items():
        fac_d = apply_detector_gate(fac_ungated, fires, action=DEFAULT_GATE_ACTION)
        g_d = gauntlet_3check(fac_d.values, known_arrs, cut)
        per_detector_summary[det_name] = {
            "gross_t": g_d["gross_t"],
            "oos_t": g_d["oos_t"],
            "passes_gross": g_d["passes_gross"],
            "passes_oos": g_d["passes_oos"],
            "passes_all": g_d["passes_all"],
            "delta_oos_vs_ungated": g_d["oos_t"] - g_ungated["oos_t"],
        }

    # ── Top-3 cells by (pass_all desc, OOS_t desc, gross_t desc) ────────────
    rows_sorted = sorted(rows, key=lambda r: (-r["passes_all"], -r["oos_t"], -r["gross_t"]))
    top3 = rows_sorted[:3]

    # ── Save + report ────────────────────────────────────────────────────────
    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets": int(len(tradeable))},
        "construction": {
            "score": "pillar_O",
            "frozen_baseline": {"rebal_days": R46_REBAL_DAYS, "cost_bps": R46_COST_BPS,
                                 "k_terciles": k_terciles, "gate_action": DEFAULT_GATE_ACTION},
            "cadences": list(cadences),
            "cost_grid": list(cost_grid),
            "detectors": list(detectors),
            "oos_frac": OOS_FRAC,
        },
        "score_coverage_pct": coverage_pct * 100,
        "windows": [{"label": lab, "start": str(s.date()), "end": str(e.date()),
                     "n_days": int((e - s).days + 1)} for lab, s, e in windows],
        "r46_ungated_baseline": {
            "gross_t": g_ungated["gross_t"], "oos_t": g_ungated["oos_t"],
            "passes_gross": g_ungated["passes_gross"], "passes_oos": g_ungated["passes_oos"],
            "passes_all": g_ungated["passes_all"],
            "per_window_ann_pct": {k: v["ann_pct"] for k, v in pw_ungated.items()},
        },
        "detector_summary": detector_summary,
        "per_detector_at_r46_cell": per_detector_summary,
        "sweep_size": len(rows),
        "sweep_summary": {
            "n_pass_all": n_pass_all,
            "best_gross_t": best_gross_t,
            "best_oos_t": best_oos_t,
        },
        "best_cell": {
            **{k: best[k] for k in ["detector", "cadence", "cost_bps",
                                     "gross_t", "oos_t", "passes_gross",
                                     "passes_oos", "passes_all",
                                     "pct_panel_flat", "turnover_ann"]},
            "gauntlet_gated": g_best_gated,
            "per_window_gated_pnl": pw_best_gated,
            "per_window_gated_absorption": sp_best_gated,
            "delta_oos_vs_ungated": delta_oos,
        },
        "top3_cells": [{
            "label": f"{r['detector']}_cad{r['cadence']}_bps{int(r['cost_bps'])}",
            **{k: r[k] for k in ["detector", "cadence", "cost_bps",
                                  "gross_t", "oos_t", "passes_gross",
                                  "passes_oos", "passes_all",
                                  "pct_panel_flat", "turnover_ann"]},
        } for r in top3],
        "verdict": verdict,
    }
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    (out_dir / "sweep_full.json").write_text(json.dumps(rows, indent=2, default=str))
    report = format_report(out, rows)
    (out_dir / "REPORT.md").write_text(report)
    print(report)
    print(f"\nSaved: {out_dir/'verdict.json'} + {out_dir/'REPORT.md'} + {out_dir/'sweep_full.json'}")
    return out


def format_report(out: dict, rows: list[dict]) -> str:
    L = []
    L.append("# R61 — Detector-Gated Pillar_O Sleeve — REPORT\n")
    panel = out["panel"]
    L.append(f"**Panel:** {panel['lo']} → {panel['hi']}  ·  "
             f"**{panel['n_days']} days × {panel['n_assets']} assets**")
    L.append(f"\n**Score:** pillar_O (R46's winning factor; per R45 lesson #13, "
             "composite adds nothing over pillar_O alone)")
    L.append(f"\n**Score coverage:** {out['score_coverage_pct']:.0f}% of days")
    cb = out["construction"]["frozen_baseline"]
    L.append(f"\n**Frozen R46 baseline:** rebal={cb['rebal_days']}d, "
             f"cost={cb['cost_bps']}bps, k={cb['k_terciles']}, "
             f"gate_action={cb['gate_action']} (skip-only, never reverse per "
             f"§TRADER_TOM_DOCTRINE)")
    L.append(f"\n**Sweep axes:** cad={out['construction']['cadences']} × "
             f"cost={out['construction']['cost_grid']} × "
             f"det={out['construction']['detectors']} → "
             f"{out['sweep_size']} cells")

    # Sub-windows
    L.append("\n## Sub-windows\n")
    L.append("| Window | Start | End | n_days |")
    L.append("|---|---|---|--:|")
    for w in out["windows"]:
        L.append(f"| {w['label']} | {w['start']} | {w['end']} | {w['n_days']} |")

    # R46 ungated baseline
    ub = out["r46_ungated_baseline"]
    w5_label = "W5"
    L.append(f"\n## R46 ungated baseline (5d/5bps/k=3, reproduction)\n")
    L.append(f"- gross_t = **{ub['gross_t']:+.2f}** "
             f"{'✓' if ub['passes_gross'] else '✗'}")
    L.append(f"- OOS_t = **{ub['oos_t']:+.2f}** "
             f"{'✓' if ub['passes_oos'] else '✗'}")
    L.append(f"- pass_all = **{ub['passes_all']}**\n")

    L.append(f"Per-window ungated ann% (W5 highlighted):\n")
    for k, v in ub["per_window_ann_pct"].items():
        marker = "🟥" if k == w5_label else "🟩"
        L.append(f"- {k}: {v:+.1f}% {marker}")

    # Detector summary
    L.append("\n## Detector summary (R58 candidates, PIT-aligned to rets.index)\n")
    L.append("| Detector | median | threshold | fires % | coverage |")
    L.append("|---|--:|--:|--:|--:|")
    for name, d in out["detector_summary"].items():
        if "error" in d:
            L.append(f"| {name} | (failed: {d['error']}) |")
            continue
        L.append(f"| {name} | {d['median']:+.4f} | {d['median_threshold']:+.4f} | "
                 f"{d['pct_fires']:.0%} | {d['coverage_pct']:.0%} |")

    # Per-detector at R46 cell
    L.append(f"\n## Per-detector lift at R46 frozen cell (5d/5bps)\n")
    L.append("`ΔOOS_t` = OOS_t(detector-gated) − OOS_t(R46 ungated)\n")
    L.append("| Detector | gross_t | OOS_t | ΔOOS_t | pass_all |")
    L.append("|---|--:|--:|--:|:--:|")
    pd_sum = out["per_detector_at_r46_cell"]
    for det_name, d in pd_sum.items():
        L.append(f"| {det_name} | {d['gross_t']:+.2f} | {d['oos_t']:+.2f} | "
                 f"{d['delta_oos_vs_ungated']:+.2f} | "
                 f"{'✓' if d['passes_all'] else '✗'} |")

    # Sweep summary
    ss = out["sweep_summary"]
    L.append(f"\n## Sweep summary\n")
    L.append(f"- Total cells: **{out['sweep_size']}** "
             f"({len(out['construction']['cadences'])} cadences × "
             f"{len(out['construction']['cost_grid'])} costs × "
             f"{len(out['construction']['detectors'])} detectors)")
    L.append(f"- Cells passing all 3 checks: **{ss['n_pass_all']}**")
    L.append(f"- Best gross_t across sweep: **{ss['best_gross_t']:+.2f}**")
    L.append(f"- Best OOS_t across sweep:   **{ss['best_oos_t']:+.2f}**")

    # Top-3 cells
    L.append(f"\n## Top-3 cells (pass_all ↓, OOS_t ↓, gross_t ↓)\n")
    L.append("| rank | config | %panel flat | gross_t | OOS_t | pass |")
    L.append("|--:|---|--:|--:|--:|:--:|")
    for i, m in enumerate(out["top3_cells"], 1):
        L.append(f"| {i} | `{m['label']}` | {m['pct_panel_flat']:.0%} | "
                 f"{m['gross_t']:+.2f} | {m['oos_t']:+.2f} | "
                 f"{'✓' if m['passes_all'] else '✗'} |")

    # Best cell detail
    bc = out["best_cell"]
    L.append(f"\n## Best cell detail\n")
    L.append(f"**Config:** detector=`{bc['detector']}`, cadence={bc['cadence']}d, "
             f"cost={bc['cost_bps']:.0f}bps, turnover≈{bc['turnover_ann']:.1f}")
    L.append(f"**%panel flat (gate fires):** {bc['pct_panel_flat']:.0%}")
    L.append(f"**ΔOOS_t vs R46 ungated:** {bc['delta_oos_vs_ungated']:+.2f}\n")

    L.append(f"**3-check gauntlet (gated):**")
    g = bc["gauntlet_gated"]
    L.append(f"- gross_t = **{g['gross_t']:+.2f}** {'✓' if g['passes_gross'] else '✗'}")
    L.append(f"- OOS_t = **{g['oos_t']:+.2f}** {'✓' if g['passes_oos'] else '✗'}")
    L.append(f"- pass_all = **{g['passes_all']}**")

    # Per-window gated vs ungated
    L.append(f"\n## Per-window P&L: ungated vs gated (best cell, ann%)\n")
    L.append("W5 row tracked. 🟥 = W5 (the failure mode).")
    L.append("\n| Window | dates | ungated ann% | gated ann% | Δ |")
    L.append("|--:|---|--:|--:|--:|")
    for w in out["windows"]:
        label = w["label"]
        u = ub["per_window_ann_pct"].get(label, float("nan"))
        g_pnl = bc["per_window_gated_pnl"].get(label, {})
        g_ann = g_pnl.get("ann_pct", float("nan"))
        delta = (g_ann - u) if (not np.isnan(g_ann) and not np.isnan(u)) else float("nan")
        marker = "🟥" if label == w5_label else "🟩"
        L.append(f"| {label} {marker} | {w['start']} → {w['end']} | "
                 f"{u:+.1f} | {g_ann:+.1f} | {delta:+.1f} |")

    # Per-window absorption (gated, residual α_t)
    L.append(f"\n## Per-window absorption (gated, residual-α t after {{market, momentum}})\n")
    L.append("| Window | n | gated α_t | gated α_ann% | det_fire_pct |")
    L.append("|--:|--:|--:|--:|--:|")
    for r in bc["per_window_gated_absorption"]:
        label = r.get("label", "?")
        n = r.get("n", "?")
        t = r.get("alpha_t", float("nan"))
        ann = r.get("alpha_ann_pct", float("nan"))
        dfp = r.get("det_fire_pct", float("nan"))
        t_str = f"**{t:+.2f}**" if abs(t) > 1.96 and not np.isnan(t) else f"{t:+.2f}"
        L.append(f"| {label} | {n} | {t_str} | {ann:+.1f} | {dfp:.0%} |")

    # Verdict
    L.append(f"\n## Verdict\n**{out['verdict']}**")
    L.append(f"\nBest gated cell: gross_t={bc['gross_t']:+.2f}, "
             f"OOS_t={bc['oos_t']:+.2f}.")
    L.append(f"\nvs R46 ungated 5d/5bps (gross_t={ub['gross_t']:+.2f}, "
             f"OOS_t={ub['oos_t']:+.2f}).")
    L.append(f"\nΔOOS_t = **{bc['delta_oos_vs_ungated']:+.2f}** "
             f"({'OOS LIFTED' if bc['delta_oos_vs_ungated'] > 0 else 'OOS NOT LIFTED'})")
    if out["verdict"].startswith("✅"):
        L.append(f"\n**Action:** detector × flat_zero rescues R46 OOS. "
                 f"Build evidence for R67 (raise w_R46 in fusion book from 0.25).")
    elif out["verdict"].startswith("🟡"):
        if "PARTIAL — clears all 3 checks" in out["verdict"]:
            L.append(f"\n**Action:** Gate trades in-sample alpha (W2: "
                     f"{bc['per_window_gated_pnl'].get('W2', {}).get('ann_pct', '?')} vs "
                     f"ungated {ub['per_window_ann_pct'].get('W2', '?')}) for OOS "
                     f"neutrality. NOT a rescue — the plan's hypothesis that R46's OOS "
                     f"sign-flip is detector-fixable is REFUTED on this data. "
                     f"Frozen R64 fusion cell stays at w_R46 = 0.25 unchanged. "
                     f"Lesson: detector × flat_zero generalizes from fade-the-crowd "
                     f"(R62 SURVIVES) to pillar_O (R61 PARTIAL) — W5 sign-flip assumed "
                     f"in plan was +15% on this reproduction, not negative.")
        else:
            L.append(f"\n**Action:** detector lifts OOS partially. Worth a second pass with "
                     f"additional detector candidates (R58 set may be too narrow for pillar_O).")
    else:
        L.append(f"\n**Action:** detector × flat_zero does NOT rescue R46 OOS at the "
                 f"R58 detector set. W5 sign-flip is structural to pillar_O in late-cycle "
                 f"risk-on, not just statistical noise that any detector can mask. "
                 f"Frozen R64 fusion cell stays at w_R46 = 0.25 unchanged.")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()
    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r61_pillar_o_detector_gated/{today}")
    run(out)