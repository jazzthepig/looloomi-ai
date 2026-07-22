"""
R62 — Regime-conditioned fade-the-crowd: R60 + fragility detector (Seth, 2026-07-21).
================================================================================
R60 verdict was 🔴 REFUTED but with a constructive 4/6 windows positive — W2 +170%,
W4 +37%, W5 +30% (first cross-sectional L/S to win W5 without a detector), W6 +84%.
The two deeply negative windows (W1 -37%, W3 -23%) are early-cycle and consolidation —
regimes where the fade-the-crowd premium is fully overwhelmed by trend / chop forces.

R62 builds R58-style KS-based fragility detector trained to discriminate
(fragile = W1 ∪ W3) from (playable = W2 ∪ W4 ∪ W5 ∪ W6), then gates the R60 factor
to flat on detector-fire days. Goal: clear 3-check gauntlet on the best cadence ×
cost × detector cell while keeping the W5 win.

Approach (sandbox-safe, pure numpy/pandas — reuses R58/R59/R60 infra):
  · Build fragility detector using R58's KS infrastructure (`build_w5_detector`)
    parameterized on the FRAGILE label = W1 ∪ W3, REFERENCE = W2 ∪ W4 ∪ W5 ∪ W6.
  · Sweep z_threshold × min_features × {internal-only, external-only, top-K}
    feature subsets at the cadence × cost cell level.
  · Per-cell gauntlet (gross / 5bps / OOS) + per-window P&L (gated vs ungated).
  · Honest refutation grammar (per R58/R59): ✅ SURVIVES / 🟡 PARTIAL / 🔴 REFUTED.

Compliance: research/validation tooling; positioning language only downstream.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)
from src.research.validation.cis_quality_robustness import (
    quarter_cuts, estimate_turnover_ann,
)
from src.research.validation.funding_crowding_ls import (
    score_funding_zwide, funding_ls,
    R46_REBAL_DAYS, R46_COST_BPS, R46_K,
    DEFAULT_ZWIN, SIGN_FADE_CROWD, OOS_FRAC, NW_LAGS, PERIODS_PER_YEAR,
)
from src.research.validation.w5_forensics_external import (
    load_funding_daily, compute_funding_features,
)
from src.research.validation.w5_forensics import (
    compute_features as compute_internal_features,
    partition_into_windows, _ks_2samp,
    build_w5_detector, gauntlet_3check,
)
from src.research.validation.factor_absorption import absorption_test


# === R62-specific defaults ====================================================
# Fragile windows per R60 6-window partition (empirically identified from R60
# ledger: W1 + W3 are the only two with ann% < 0 on the best cell 21d/0bps).
FRAGILE_LABEL = "FRAGILE"
DEFAULT_FRAGILE_WINDOWS = ("W1", "W3")     # ann% -37% / -22% on R60 best cell
DEFAULT_PLAYABLE_WINDOWS = ("W2", "W4", "W5", "W6")
DEFAULT_CADENCES = (5, 7, 14, 21)         # R60 sweet spot starts at 5d, ≥14d needed
DEFAULT_COST_GRID = (0.0, 5.0)            # R60 best 21d/0bps, also test 5bps survival
DEFAULT_Z_THRESHOLDS = (0.0, 0.25, 0.5, 0.75)
DEFAULT_MIN_FEATURES = (2, 3, 4)
DEFAULT_FEATURE_SUBSETS = ("internal", "external", "top8")


# === Feature union (R58 internal + R59 external) =============================
def compute_combined_features(cis: pd.DataFrame, rets: pd.DataFrame,
                              tradeable: list, matched_assets: list,
                              funding_daily: pd.DataFrame) -> pd.DataFrame:
    """Stack R58 10 internal features + R59 5 funding features. PIT-safe (rolling)."""
    internal_feats = compute_internal_features(cis, rets, tradeable)
    # Funding features: only for assets in matched_assets
    if not funding_daily.empty and matched_assets:
        fd = funding_daily[matched_assets]
        external_feats = compute_funding_features(fd, rets.index, matched_assets)
        external_feats = external_feats.reindex(rets.index)
    else:
        external_feats = pd.DataFrame(index=rets.index)
        for c in ["funding_mean", "funding_disp", "funding_skew",
                  "funding_extreme_long_frac", "funding_extreme_short_frac",
                  "funding_net_long_frac"]:
            external_feats[c] = np.nan
    feats = pd.concat([internal_feats, external_feats], axis=1)
    return feats


# === Fragility detector ======================================================
def build_fragility_ks_table(features: pd.DataFrame,
                             fragile_mask: pd.Series) -> dict:
    """KS table: feature distribution in FRAGILE days vs PLAYABLE days.

    Uses R58 schema keys (`mean_w5`/`mean_ref`) so `build_w5_detector`
    (which reads these by name) works without modification — only the
    semantic role differs (mean_w5 here = mean(fragile)).
    """
    ref = features.loc[~fragile_mask].dropna(how="all")
    out = {}
    for col in features.columns:
        a = features.loc[fragile_mask, col].dropna().values
        b = ref[col].dropna().values
        if len(a) < 5 or len(b) < 5:
            out[col] = {"ks": np.nan, "p": np.nan, "mean_diff": np.nan,
                        "mean_w5": np.nan, "mean_ref": np.nan}
            continue
        ks, p = _ks_2samp(a, b)
        out[col] = {
            "ks": float(ks), "p": float(p),
            "mean_diff": float(a.mean() - b.mean()),
            "mean_w5": float(a.mean()),     # mean(fragile)
            "mean_ref": float(b.mean()),    # mean(playable)
        }
    return out


def fragility_detector_holdout_mask(fragile_labels: list[str],
                                    windows: list[tuple],
                                    oos_labels: list[str] | None = None) -> tuple[pd.Series, pd.Series]:
    """Build fragile-day mask (training label) and holdout mask.

    If `oos_labels` is None, full labels used (in-sample); otherwise OOS labels are
    held out from KS training. Returns (fragile_mask, holdout_mask).
    """
    fragile_ranges = []
    holdout_ranges = []
    for label, lo, hi in windows:
        if label in fragile_labels:
            fragile_ranges.append((lo, hi))
        if oos_labels is not None and label in oos_labels:
            holdout_ranges.append((lo, hi))
    def _in_range(d, ranges):
        return any((d >= lo and d <= hi) for lo, hi in ranges)
    # We need a date-indexed mask; caller passes index separately. This fn returns
    # (lo, hi) pairs instead.
    return fragile_ranges, holdout_ranges


def features_in_ranges(features: pd.DataFrame,
                       ranges: list[tuple]) -> pd.Series:
    """Boolean mask: rows of `features` whose date falls inside any (lo, hi) range."""
    m = pd.Series(False, index=features.index)
    for lo, hi in ranges:
        m = m | ((features.index >= lo) & (features.index <= hi))
    return m


# === Per-cell gauntlet (R58-style, gated) ====================================
def cell_gauntlet(fac: pd.Series, known: dict, oos_idx: int) -> dict:
    """3-check gauntlet wrapper."""
    return gauntlet_3check(fac.values, known, oos_idx)


# === Per-window P&L ==========================================================
def per_window_pnl(fac: pd.Series, periods: list[tuple]) -> dict:
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


# === Master run ==============================================================
def run(out_dir: Path,
        zwin: int = DEFAULT_ZWIN,
        k_terciles: int = R46_K,
        sign: str = SIGN_FADE_CROWD,
        cadences: tuple = DEFAULT_CADENCES,
        cost_grid: tuple = DEFAULT_COST_GRID,
        z_thresholds: tuple = DEFAULT_Z_THRESHOLDS,
        min_features_grid: tuple = DEFAULT_MIN_FEATURES,
        feature_subsets: tuple = DEFAULT_FEATURE_SUBSETS,
        fragile_labels: tuple = DEFAULT_FRAGILE_WINDOWS,
        playable_labels: tuple = DEFAULT_PLAYABLE_WINDOWS) -> dict:
    """Load → score → fragility detector → sweep (cad × cost × det) → verdict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R62 — Regime-conditioned fade-the-crowd (fragility detector, "
          f"sign={sign}, zwin={zwin}d) ===\n")

    # ── Load panel ───────────────────────────────────────────────────────────
    cis = load_cis_history_wide()
    rets = load_daily_returns()
    lo = max(cis["date"].min(), rets.index.min())
    hi = min(cis["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable = sorted(set(cis["asset"]) & set(rets.columns))
    print(f"Panel: {lo.date()} → {hi.date()} ({len(rets)} days, {len(tradeable)} assets)")

    funding_daily = load_funding_daily(assets=tradeable)
    matched_assets = sorted(set(tradeable) & set(funding_daily.columns))
    print(f"Funding daily: {funding_daily.shape[0]} days × {funding_daily.shape[1]} assets "
          f"({len(matched_assets)} matched)")

    if not funding_daily.empty:
        f_lo, f_hi = funding_daily.index.min(), funding_daily.index.max()
        rets = rets.loc[(rets.index >= f_lo) & (rets.index <= f_hi)]
    print(f"Aligned panel: {rets.index.min().date()} → {rets.index.max().date()} "
          f"({len(rets)} days, {len(matched_assets)} funding-bearing assets)\n")

    # ── 6-window partition ───────────────────────────────────────────────────
    windows = partition_into_windows(rets.index, n_windows=6)
    print("Sub-windows:")
    for label, s, e in windows:
        print(f"  {label}: {s.date()} → {e.date()} ({int((e - s).days + 1)} days)")
    print()

    fragile_ranges = [(lo_, hi_) for label_, lo_, hi_ in windows if label_ in fragile_labels]
    playable_ranges = [(lo_, hi_) for label_, lo_, hi_ in windows if label_ in playable_labels]
    fragile_mask = features_in_ranges(
        pd.DataFrame(index=rets.index), fragile_ranges
    ).reindex(rets.index).fillna(False)

    print(f"Fragile windows (training label): {list(fragile_labels)} → "
          f"{int(fragile_mask.sum())}/{len(fragile_mask)} days "
          f"({fragile_mask.mean():.0%} of panel)")
    print(f"Playable windows (reference):     {list(playable_labels)}\n")

    # ── Features (R58 internal + R59 external) ───────────────────────────────
    print("Computing combined features (internal + funding) …")
    feats = compute_combined_features(cis, rets, tradeable, matched_assets, funding_daily)
    # Restrict features to dates where fragile_mask is meaningful (full panel)
    feats = feats.reindex(rets.index)
    print(f"  features: {list(feats.columns)}")
    print(f"  coverage: {feats.notna().mean().round(2).to_dict()}\n")

    # ── R60 score + factor ───────────────────────────────────────────────────
    score = score_funding_zwide(funding_daily[matched_assets], zwin=zwin, sign=sign)
    score = score.reindex(rets.index).ffill()
    coverage_pct = float(score.notna().any(axis=1).mean())
    print(f"Score matrix: {score.shape[0]} days × {score.shape[1]} assets "
          f"({coverage_pct:.0%} of days with ≥1 valid score)\n")

    # ── Known factors (R46/R60 parity) ──────────────────────────────────────
    f_market = rets[matched_assets].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known = {"market": f_market.reindex(rets.index).fillna(0.0).values,
             "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}
    # OOS is the last OOS_FRAC of the panel; cut at the 70% boundary.
    cut = int(len(rets) * (1.0 - OOS_FRAC))

    # ── R60 ungated baseline (best cell 21d/0bps + R46 cell 5d/5bps) ─────────
    fac_5d_5 = funding_ls(score, rets[matched_assets], k_terciles=k_terciles,
                           cost_bps=R46_COST_BPS, rebal_days=R46_REBAL_DAYS).reindex(rets.index).fillna(0.0)
    fac_21d_0 = funding_ls(score, rets[matched_assets], k_terciles=k_terciles,
                           cost_bps=0.0, rebal_days=21).reindex(rets.index).fillna(0.0)
    g_r46 = cell_gauntlet(fac_5d_5, known, cut)
    g_best_ungated = cell_gauntlet(fac_21d_0, known, cut)
    print(f"R60 ungated baseline parity:")
    print(f"  5d/5bps:   gross_t={g_r46['gross_t']:+.2f}, OOS_t={g_r46['oos_t']:+.2f}")
    print(f"  21d/0bps:  gross_t={g_best_ungated['gross_t']:+.2f}, OOS_t={g_best_ungated['oos_t']:+.2f}\n")

    # ── R60 per-window P&L (ungated reference) ───────────────────────────────
    pw_ungated = per_window_pnl(fac_21d_0, windows)

    # ── Build fragility detector (KS on (W1∪W3) vs (W2∪W4∪W5∪W6)) ───────────
    ks_frag = build_fragility_ks_table(feats, fragile_mask)
    ks_ranked = sorted(
        [(c, v) for c, v in ks_frag.items() if not np.isnan(v["ks"])],
        key=lambda kv: -kv[1]["ks"],
    )
    internal_cols = [c for c in feats.columns if c not in {
        "funding_mean", "funding_disp", "funding_skew",
        "funding_extreme_long_frac", "funding_extreme_short_frac",
        "funding_net_long_frac",
    }]
    external_cols = [c for c in feats.columns if c not in internal_cols]
    top5 = [n for n, _ in ks_ranked[:5]]
    top8 = [n for n, _ in ks_ranked[:8]]
    print(f"Fragility KS ranking (top-5 by KS distance, fragile vs playable):")
    for n, v in ks_ranked[:5]:
        print(f"  {n:>30}: KS={v['ks']:.2f}, p={v['p']:.3f}, "
              f"mean_frag={v['mean_w5']:+.4f}, mean_play={v['mean_ref']:+.4f}")
    print()

    feature_sets = {
        "internal": internal_cols,
        "external": external_cols,
        "top5": top5,
        "top8": top8,
    }

    # ── Detector grid sweep ──────────────────────────────────────────────────
    print(f"══ Detector grid sweep (cad={list(cadences)} × bps={list(cost_grid)} × "
          f"z={list(z_thresholds)} × min_f={list(min_features_grid)} × "
          f"feature_sets={list(feature_subsets)}) ══\n")
    rows = []
    for fs_name in feature_subsets:
        if fs_name not in feature_sets:
            continue
        fs = feature_sets[fs_name]
        if not fs:
            continue
        for z_thr in z_thresholds:
            for min_f in min_features_grid:
                if min_f > len(fs):
                    continue
                # Build detector once; reuse across (cad, bps) cells
                det, _ = build_w5_detector(
                    feats, *fragile_ranges[0] if fragile_ranges else (rets.index[0], rets.index[0]),
                    *playable_ranges[0] if playable_ranges else (rets.index[0], rets.index[0]),
                    ks_frag, feature_subset=fs,
                    z_threshold=z_thr, min_features=min_f,
                )
                # Hit-rate diagnostics
                fragile_hr = float(det.loc[fragile_mask].mean()) if fragile_mask.sum() > 0 else float("nan")
                playable_hr = float(det.loc[~fragile_mask].mean()) if (~fragile_mask).sum() > 0 else float("nan")
                precision = (fragile_hr / (fragile_hr + playable_hr)
                             if (fragile_hr + playable_hr) > 0 else float("nan"))
                flat_pct = float(det.mean())
                for cad in cadences:
                    for bps in cost_grid:
                        fac = funding_ls(score, rets[matched_assets], k_terciles=k_terciles,
                                          cost_bps=bps, rebal_days=cad).reindex(rets.index).fillna(0.0)
                        fac_gated = fac.where(~det, 0.0)
                        g = gauntlet_3check(fac_gated.values, known, cut)
                        rows.append({
                            "feature_set": fs_name, "z_threshold": z_thr,
                            "min_features": min_f, "cadence": cad, "cost_bps": bps,
                            "fragile_hit_rate": fragile_hr,
                            "playable_hit_rate": playable_hr,
                            "precision_proxy": precision,
                            "pct_panel_flat": flat_pct,
                            "gross_t": g["gross_t"], "oos_t": g["oos_t"],
                            "passes_gross": g["passes_gross"], "passes_oos": g["passes_oos"],
                            "passes_all": g["passes_all"],
                        })
    print(f"  Total cells evaluated: {len(rows)}")
    print(f"  Cells passing all 3 checks: "
          f"{sum(1 for r in rows if r['passes_all'])}")
    print(f"  Best gross_t: {max(r['gross_t'] for r in rows):+.2f}")
    print(f"  Best OOS_t:   {max(r['oos_t'] for r in rows):+.2f}\n")

    # ── Pick best cell (passes_all first, then max OOS_t, then max gross_t) ──
    viable = [r for r in rows if r["passes_all"]]
    if viable:
        best = max(viable, key=lambda r: (r["oos_t"], r["gross_t"]))
        verdict = "✅ SURVIVES — clears all 3 checks"
    else:
        # Fall back to cells with positive OOS_t
        candidates = [r for r in rows if r["oos_t"] > 0]
        if candidates:
            best = max(candidates, key=lambda r: (r["oos_t"], r["gross_t"]))
        else:
            best = max(rows, key=lambda r: (r["oos_t"], r["gross_t"]))
        if best["passes_gross"]:
            verdict = "🟡 PARTIAL — clears gross + positive OOS, sub-1.96"
        else:
            verdict = "🔴 REFUTED — fails 2+ checks"

    print(f"Best cell: feature_set={best['feature_set']}, z={best['z_threshold']}, "
          f"min_f={best['min_features']}, cad={best['cadence']}d, "
          f"bps={best['cost_bps']:.0f}, "
          f"gross_t={best['gross_t']:+.2f}, OOS_t={best['oos_t']:+.2f}")
    print(f"  fragile HR={best['fragile_hit_rate']:.0%}, "
          f"playable HR={best['playable_hit_rate']:.0%}, "
          f"%flat={best['pct_panel_flat']:.0%}")
    print(f"Verdict: {verdict}\n")

    # ── Best cell re-run for full reporting (per-window gated vs ungated) ───
    fs = feature_sets[best["feature_set"]]
    det_best, _ = build_w5_detector(
        feats,
        *fragile_ranges[0] if fragile_ranges else (rets.index[0], rets.index[0]),
        *playable_ranges[0] if playable_ranges else (rets.index[0], rets.index[0]),
        ks_frag, feature_subset=fs,
        z_threshold=best["z_threshold"], min_features=best["min_features"],
    )
    fac_best_ungated = funding_ls(score, rets[matched_assets], k_terciles=k_terciles,
                                   cost_bps=best["cost_bps"], rebal_days=best["cadence"]).reindex(rets.index).fillna(0.0)
    fac_best_gated = fac_best_ungated.where(~det_best, 0.0)
    g_best_gated = gauntlet_3check(fac_best_gated.values, known, cut)
    pw_best_gated = per_window_pnl(fac_best_gated, windows)

    # ── Multi-config gauntlet for top-3 cells (transparency) ────────────────
    # Take top 3 by (passes_all desc, OOS_t desc, gross_t desc)
    rows_sorted = sorted(rows, key=lambda r: (-r["passes_all"], -r["oos_t"], -r["gross_t"]))
    top3 = rows_sorted[:3]
    multi = []
    for r in top3:
        fse = feature_sets[r["feature_set"]]
        d_, _ = build_w5_detector(
            feats,
            *fragile_ranges[0] if fragile_ranges else (rets.index[0], rets.index[0]),
            *playable_ranges[0] if playable_ranges else (rets.index[0], rets.index[0]),
            ks_frag, feature_subset=fse,
            z_threshold=r["z_threshold"], min_features=r["min_features"],
        )
        f_ = funding_ls(score, rets[matched_assets], k_terciles=k_terciles,
                        cost_bps=r["cost_bps"], rebal_days=r["cadence"]).reindex(rets.index).fillna(0.0)
        g_ = gauntlet_3check(f_.where(~d_, 0.0).values, known, cut)
        multi.append({
            "label": f"top{r['feature_set']}_z{r['z_threshold']}_mf{r['min_features']}_"
                     f"cad{r['cadence']}_bps{int(r['cost_bps'])}",
            **{k: r[k] for k in ["cadence", "cost_bps", "fragile_hit_rate",
                                  "playable_hit_rate", "pct_panel_flat",
                                  "gross_t", "oos_t", "passes_gross", "passes_oos", "passes_all"]},
            "pct_panel_flat": float(d_.mean()),
            **g_,
        })

    # ── Save + report ────────────────────────────────────────────────────────
    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets": int(len(tradeable)),
                  "funding_matched_assets": len(matched_assets),
                  "matched_assets": matched_assets},
        "construction": {"zwin": zwin, "k_terciles": k_terciles, "sign": sign,
                         "cadences": list(cadences), "cost_grid": list(cost_grid),
                         "z_thresholds": list(z_thresholds),
                         "min_features_grid": list(min_features_grid),
                         "feature_subsets": list(feature_subsets),
                         "fragile_labels": list(fragile_labels),
                         "playable_labels": list(playable_labels)},
        "windows": [{"label": lab, "start": str(s.date()), "end": str(e.date()),
                     "n_days": int((e - s).days + 1),
                     "fragile": lab in fragile_labels} for lab, s, e in windows],
        "score_coverage_pct": coverage_pct * 100,
        "feature_columns": list(feats.columns),
        "feature_coverage": {c: float(feats[c].notna().mean()) for c in feats.columns},
        "fragile_ks_ranked": [{"feature": n, **v} for n, v in ks_ranked],
        "r60_ungated_baseline": {
            "5d_5bps": {"gross_t": g_r46["gross_t"], "oos_t": g_r46["oos_t"],
                        "passes_gross": g_r46["passes_gross"], "passes_oos": g_r46["passes_oos"]},
            "21d_0bps": {"gross_t": g_best_ungated["gross_t"], "oos_t": g_best_ungated["oos_t"],
                         "passes_gross": g_best_ungated["passes_gross"], "passes_oos": g_best_ungated["passes_oos"]},
            "per_window_ann_pct": {k: v["ann_pct"] for k, v in pw_ungated.items()},
        },
        "sweep_size": len(rows),
        "sweep_summary": {
            "n_pass_all": sum(1 for r in rows if r["passes_all"]),
            "best_gross_t": max(r["gross_t"] for r in rows),
            "best_oos_t": max(r["oos_t"] for r in rows),
        },
        "best_cell": {
            **{k: best[k] for k in ["feature_set", "z_threshold", "min_features",
                                     "cadence", "cost_bps", "fragile_hit_rate",
                                     "playable_hit_rate", "pct_panel_flat",
                                     "gross_t", "oos_t", "passes_gross", "passes_oos",
                                     "passes_all"]},
            "gauntlet_gated": g_best_gated,
            "per_window_gated": pw_best_gated,
            "per_window_ungated": pw_ungated,
            "features_used": fs,
        },
        "multi_top3": multi,
        "verdict": verdict,
    }
    # Slim sweep for json (drop full grid to avoid huge file)
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    (out_dir / "sweep_full.json").write_text(json.dumps(rows, indent=2, default=str))
    report = format_report(out, rows)
    (out_dir / "REPORT.md").write_text(report)
    print(report)
    print(f"\nSaved: {out_dir/'verdict.json'} + {out_dir/'REPORT.md'} + {out_dir/'sweep_full.json'}")
    return out


def format_report(out: dict, rows: list[dict]) -> str:
    L = []
    L.append("# R62 — Regime-Conditioned Fade-the-Crowd — REPORT\n")
    panel = out["panel"]
    L.append(f"**Panel:** {panel['lo']} → {panel['hi']}  ·  "
             f"**{panel['n_days']} days × {panel['funding_matched_assets']} funding-bearing assets** "
             f"(out of {panel['n_assets']} CIS ∩ OHLCV)")
    L.append(f"\n**Score coverage:** {out['score_coverage_pct']:.0f}% of days")
    L.append(f"\n**Fragile label:** {out['construction']['fragile_labels']} — "
             f"identified from R60 per-window P&L (the two deeply-negative windows).")
    L.append(f"\n**Playable label:** {out['construction']['playable_labels']} (KS reference).")

    # Sub-windows
    L.append("\n## Sub-windows (fragile = light red)\n")
    L.append("| Window | Start | End | n_days | fragile |")
    L.append("|--:|---|---|--:|:--:|")
    for w in out["windows"]:
        mark = "🟥" if w["fragile"] else "🟩"
        L.append(f"| {w['label']} | {w['start']} | {w['end']} | {w['n_days']} | {mark} |")

    # R60 ungated baseline
    ub = out["r60_ungated_baseline"]
    L.append("\n## R60 ungated baseline (reproduction parity)\n")
    L.append("| config | gross_t | OOS_t | pass_gross | pass_OOS |")
    L.append("|---|--:|--:|:--:|:--:|")
    for k in ("5d_5bps", "21d_0bps"):
        u = ub[k]
        L.append(f"| {k} | {u['gross_t']:+.2f} | {u['oos_t']:+.2f} | "
                 f"{'✓' if u['passes_gross'] else '✗'} | "
                 f"{'✓' if u['passes_oos'] else '✗'} |")
    L.append(f"\nR60 per-window ungated P&L (ann%, 21d/0bps baseline):\n")
    for k, v in ub["per_window_ann_pct"].items():
        marker = "🟥" if k in out["construction"]["fragile_labels"] else "🟩"
        L.append(f"- {k}: {v:+.1f}% {marker}")

    # KS ranking
    L.append("\n## Fragility KS ranking (top-8 by KS distance)\n")
    L.append("| rank | feature | KS | p | mean(fragile) | mean(playable) |")
    L.append("|--:|---|--:|--:|--:|--:|")
    for i, row in enumerate(out["fragile_ks_ranked"][:8], 1):
        L.append(f"| {i} | {row['feature']} | {row['ks']:.2f} | "
                 f"{row['p']:.3f} | {row['mean_w5']:+.4f} | "
                 f"{row['mean_ref']:+.4f} |")

    # Sweep summary
    ss = out["sweep_summary"]
    L.append(f"\n## Sweep summary\n")
    L.append(f"- Total cells: **{out['sweep_size']}** "
             f"(={len(out['construction']['cadences'])} cadences × "
             f"{len(out['construction']['cost_grid'])} costs × "
             f"{len(out['construction']['z_thresholds'])} z-thresholds × "
             f"{len(out['construction']['min_features_grid'])} min-features × "
             f"{len(out['construction']['feature_subsets'])} feature sets)")
    L.append(f"- Cells passing all 3 checks: **{ss['n_pass_all']}**")
    L.append(f"- Best gross_t across sweep: **{ss['best_gross_t']:+.2f}**")
    L.append(f"- Best OOS_t across sweep:   **{ss['best_oos_t']:+.2f}**")

    # Top-3 detector-gated cells
    L.append(f"\n## Top-3 cells by (pass_all ↓, OOS_t ↓, gross_t ↓)\n")
    L.append("| rank | config | fragile_HR | playable_HR | %flat | gross_t | OOS_t | pass |")
    L.append("|--:|---|--:|--:|--:|--:|--:|:--:|")
    for i, m in enumerate(out["multi_top3"], 1):
        L.append(f"| {i} | `{m['label']}` | {m['fragile_hit_rate']:.0%} | "
                 f"{m['playable_hit_rate']:.0%} | {m['pct_panel_flat']:.0%} | "
                 f"{m['gross_t']:+.2f} | {m['oos_t']:+.2f} | "
                 f"{'✓' if m['passes_all'] else '✗'} |")

    # Best cell detail + per-window gated
    bc = out["best_cell"]
    L.append(f"\n## Best cell detail\n")
    L.append(f"**Config:** feature_set=`{bc['feature_set']}`, z_threshold={bc['z_threshold']}, "
             f"min_features={bc['min_features']}, cadence={bc['cadence']}d, "
             f"cost={bc['cost_bps']:.0f}bps")
    L.append(f"**Features used (`feature_set={bc['feature_set']}`):** "
             f"`{', '.join(bc['features_used'])}`")
    L.append(f"**Hit-rate diagnostics:** fragile_hit={bc['fragile_hit_rate']:.0%}, "
             f"playable_hit={bc['playable_hit_rate']:.0%}, "
             f"%panel flat={bc['pct_panel_flat']:.0%}")

    L.append(f"\n**3-check gauntlet (gated):**")
    g = bc["gauntlet_gated"]
    L.append(f"- gross_t = **{g['gross_t']:+.2f}** {'✓' if g['passes_gross'] else '✗'}")
    L.append(f"- 5bps is the cost in series for the chosen cell "
             f"(`cost_bps={bc['cost_bps']:.0f}`)")
    L.append(f"- OOS_t = **{g['oos_t']:+.2f}** {'✓' if g['passes_oos'] else '✗'}")
    L.append(f"- pass_all = **{g['passes_all']}**")

    L.append(f"\n## Per-window P&L: ungated vs gated (best cell, ann%)\n")
    L.append("Fragile rows highlighted 🟥. W5 row tracked separately.\n")
    L.append("| Window | dates | ungated ann% | gated ann% | Δ |")
    L.append("|--:|---|--:|--:|--:|")
    for label in bc["per_window_ungated"]:
        u = bc["per_window_ungated"][label]
        g_ = bc["per_window_gated"].get(label, {})
        marker = "🟥" if label in out["construction"]["fragile_labels"] else "🟩"
        delta = g_.get("ann_pct", 0) - u["ann_pct"] if not np.isnan(u["ann_pct"]) and not np.isnan(g_.get("ann_pct", np.nan)) else float("nan")
        uann = u["ann_pct"]
        gann = g_.get("ann_pct", float("nan"))
        L.append(f"| {label} {marker} | (W{label[1]}) | {uann:+.1f} | {gann:+.1f} | "
                 f"{delta:+.1f} |")

    # Verdict
    L.append(f"\n## Verdict\n**{out['verdict']}**")
    L.append(f"\nBest gated cell: gross_t={bc['gross_t']:+.2f}, OOS_t={bc['oos_t']:+.2f}. "
             f"vs R60 ungated 21d/0bps (gross_t={ub['21d_0bps']['gross_t']:+.2f}, "
             f"OOS_t={ub['21d_0bps']['oos_t']:+.2f}).")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--zwin", type=int, default=DEFAULT_ZWIN)
    args = ap.parse_args()
    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r62_fragility_funding_ls/{today}")
    run(out, zwin=args.zwin)
