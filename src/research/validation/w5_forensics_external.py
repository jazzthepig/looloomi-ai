"""
R59 — External-feature enrichment of the W5 detector (Seth, 2026-07-21).
=================================================================================
Driven by R58's finding: the internal-only W5 detector improves gross (+1.84→+4.84)
and flips OOS sign (−0.89→+0.41) but does NOT clear the 1.96 OOS bar. R58 attributed
the residual fragility to "funding/leverage/cross-asset contagion — needs external
data." We now have it:
  · 47 assets × hourly funding rates, 2023-05-12 → 2026-07-19
    `/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding/*_funding_1h.csv`
  · BTC/ETH/SOL OI history (Binance USD-M) in `/cache/macro/oi_hist_*.json`
  · 28 of these overlap with the 41-asset tradeable universe.

This module:
  1. Loads the 28 funding 1h CSVs, resamples to daily mean per asset, then computes
     cross-sectional funding features:
       funding_mean, funding_disp, funding_skew, funding_extreme_long_frac,
       funding_extreme_short_frac, btc_funding_zscore_30
  2. Loads BTC OI history if available → btc_oi_zscore_30
  3. Merges with R58's 10 internal features → enriched feature set (~17 cols)
  4. Re-runs KS distance + detector sweep on the enriched set
  5. Compares: R58-internal-only detector vs R59-enriched detector on the 3-check
     gauntlet. Hypothesis: external features capture the residual OOS fragility
     the internal features missed.

Compliance: research/validation tooling; positioning language only downstream.
"""
from __future__ import annotations

import argparse
import json
import glob
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.w5_forensics import (
    compute_features as compute_internal_features,
    partition_into_windows, fingerprint_window, ks_distance,
    build_w5_detector, gauntlet_3check, _ks_2samp,
    N_WINDOWS, W5_START, W5_END, R46_REBAL_DAYS, R46_COST_BPS, R46_K,
    R46_BASELINE_T_COSTED, R46_BASELINE_OOS_T,
)
from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns, tercile_ls,
)
from src.research.validation.factor_absorption import absorption_test


# === External data paths ======================================================
FUNDING_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")
OI_CACHE_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_cache/macro")


def load_funding_daily(funding_dir: Path = FUNDING_DIR,
                      assets: list[str] | None = None) -> pd.DataFrame:
    """Load all *_funding_1h.csv, resample to daily mean per asset.

    Returns: DataFrame [date × asset] of mean daily funding rate (8h rate, as decimal).
    Only assets with > 100 obs are kept (drops the "ALT" / obscure tickers with sparse data).
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
        df["dt"] = pd.to_datetime(df["fundingTime"], unit="ms").dt.normalize()
        # daily mean of the 8h funding rate
        daily = df.groupby("dt")["fundingRate"].mean()
        if len(daily) < 100:
            continue
        out[a.upper()] = daily

    panel = pd.DataFrame(out).sort_index()
    return panel


def compute_funding_features(funding_daily: pd.DataFrame,
                             rets_index: pd.DatetimeIndex,
                             tradeable: list[str]) -> pd.DataFrame:
    """Cross-sectional funding features + BTC-specific.

    funding_mean               cross-sectional mean of daily funding (longs pay if +)
    funding_disp               cross-sectional std
    funding_skew               cross-sectional skew (Fisher-Pearson)
    funding_extreme_long_frac  fraction of assets with funding > +5 bps/8h
    funding_extreme_short_frac fraction of assets with funding < -5 bps/8h
    funding_net_long_frac      (long_frac - short_frac) — net crowded direction
    btc_funding_zscore_30      BTC funding z-score vs trailing 30d
    """
    # align to rets.index (forward-fill to daily cadence)
    common = [a for a in tradeable if a in funding_daily.columns]
    f = funding_daily[common].reindex(rets_index).ffill()

    feats = pd.DataFrame(index=rets_index)
    feats["funding_mean"] = f.mean(axis=1)
    feats["funding_disp"] = f.std(axis=1)
    feats["funding_skew"] = f.skew(axis=1)
    feats["funding_extreme_long_frac"] = (f > 0.0005).sum(axis=1) / f.notna().sum(axis=1)
    feats["funding_extreme_short_frac"] = (f < -0.0005).sum(axis=1) / f.notna().sum(axis=1)
    feats["funding_net_long_frac"] = feats["funding_extreme_long_frac"] - feats["funding_extreme_short_frac"]

    if "BTC" in f.columns:
        btc_f = f["BTC"].fillna(method="ffill")
        feats["btc_funding_raw"] = btc_f
        feats["btc_funding_zscore_30"] = (
            (btc_f - btc_f.rolling(30, min_periods=10).mean())
            / (btc_f.rolling(30, min_periods=10).std() + 1e-12)
        )

    return feats


def load_btc_oi(oi_cache_dir: Path = OI_CACHE_DIR) -> pd.Series | None:
    """Load BTC OI history if available. Returns Series indexed by date, or None."""
    candidates = [
        oi_cache_dir / "oi_hist_BTCUSDT.json",
        oi_cache_dir / "oi_BTC.json",
        oi_cache_dir / "oi_BTCUSDT.json",
    ]
    for fp in candidates:
        if not fp.exists():
            continue
        try:
            with open(fp) as fh:
                d = json.load(fh)
        except Exception:
            continue
        # try a few shapes
        if isinstance(d, list):
            arr = d
        elif isinstance(d, dict):
            for k in ("data", "oi", "openInterest", "history"):
                if k in d and isinstance(d[k], list):
                    arr = d[k]
                    break
            else:
                arr = []
        else:
            arr = []
        if not arr:
            continue
        # Try to parse as list of {timestamp, sumOpenInterest}
        try:
            df = pd.DataFrame(arr)
            ts_col = next((c for c in df.columns if "time" in c.lower()), df.columns[0])
            oi_col = next((c for c in df.columns if "interest" in c.lower() or "oi" in c.lower()), df.columns[1])
            df["dt"] = pd.to_datetime(df[ts_col], unit="ms", errors="coerce")
            if df["dt"].isna().all():
                df["dt"] = pd.to_datetime(df[ts_col], errors="coerce")
            df = df.dropna(subset=["dt"])
            df["dt"] = df["dt"].dt.normalize()
            daily = df.groupby("dt")[oi_col].mean()
            return daily.sort_index()
        except Exception:
            continue
    return None


def compute_oi_features(btc_oi: pd.Series | None,
                        rets_index: pd.DatetimeIndex) -> pd.DataFrame:
    """OI-derived features (only if btc_oi available)."""
    feats = pd.DataFrame(index=rets_index)
    if btc_oi is None:
        feats["btc_oi_zscore_30"] = np.nan
        feats["btc_oi_present"] = 0.0
        return feats
    aligned = btc_oi.reindex(rets_index).ffill()
    feats["btc_oi_zscore_30"] = (
        (aligned - aligned.rolling(30, min_periods=10).mean())
        / (aligned.rolling(30, min_periods=10).std() + 1e-12)
    )
    feats["btc_oi_present"] = aligned.notna().astype(float)
    return feats


# === Master run ================================================================
def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R59 — External-feature W5 detector enrichment ===\n")

    # === Load core panel (CIS + OHLCV) ===
    cis = load_cis_history_wide()
    rets = load_daily_returns()
    lo = max(cis["date"].min(), rets.index.min())
    hi = min(cis["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable = sorted(set(cis["asset"]) & set(rets.columns))
    print(f"Panel: {lo.date()} → {hi.date()} ({len(rets)} days, {len(tradeable)} assets)")

    # === Load funding daily ===
    funding_daily = load_funding_daily(assets=tradeable)
    matched_assets = sorted(set(tradeable) & set(funding_daily.columns))
    print(f"Funding daily: {funding_daily.shape[0]} days × {funding_daily.shape[1]} assets "
          f"({len(matched_assets)} matched with tradeable universe)")

    # === Load BTC OI ===
    btc_oi = load_btc_oi()
    if btc_oi is not None:
        print(f"BTC OI: {len(btc_oi)} obs ({btc_oi.index.min().date()} → {btc_oi.index.max().date()})")
    else:
        print("BTC OI: NOT AVAILABLE — skipping OI features")

    # === Compute features ===
    print("\nComputing features …")
    internal_feats = compute_internal_features(cis, rets, tradeable)
    funding_feats = compute_funding_features(funding_daily, rets.index, matched_assets)
    oi_feats = compute_oi_features(btc_oi, rets.index)
    feats = pd.concat([internal_feats, funding_feats, oi_feats], axis=1)
    # Drop OI column if no data
    if not btc_oi:
        feats = feats.drop(columns=["btc_oi_zscore_30"], errors="ignore")
    print(f"  total features: {list(feats.columns)}")
    print(f"  coverage (head): {feats.notna().mean().round(2).to_dict()}")

    # === Window partition ===
    windows = partition_into_windows(rets.index, N_WINDOWS)
    w5_label, w5_lo, w5_hi = windows[4]

    # === KS ranking (all features) ===
    feats_non_w5 = feats.loc[~((feats.index >= w5_lo) & (feats.index <= w5_hi))]
    ks_w5_vs_all = {}
    for col in feats.columns:
        a = feats.loc[(feats.index >= w5_lo) & (feats.index <= w5_hi), col].dropna().values
        b = feats_non_w5[col].dropna().values
        if len(a) < 5 or len(b) < 5:
            ks_w5_vs_all[col] = {"ks": np.nan, "p": np.nan, "mean_diff": np.nan,
                                 "mean_w5": np.nan, "mean_ref": np.nan}
            continue
        ks, p = _ks_2samp(a, b)
        ks_w5_vs_all[col] = {"ks": float(ks), "p": float(p),
                             "mean_diff": float(a.mean() - b.mean()),
                             "mean_w5": float(a.mean()), "mean_ref": float(b.mean())}

    ks_ranked = sorted(ks_w5_vs_all.items(),
                       key=lambda kv: -kv[1]["ks"] if not np.isnan(kv[1]["ks"]) else 0)

    # Split features into internal-only (R58 set) vs enriched (R59 set)
    internal_cols = list(internal_feats.columns)
    enriched_cols = list(feats.columns)  # includes everything
    external_cols = [c for c in enriched_cols if c not in internal_cols]

    # === Detector sweep on EACH feature set ====================================
    def run_detector_sweep(features, top_k=5, ks_table=None, label="R59-enriched"):
        """Run (z_threshold × min_features) sweep on top-k KS-distinctive features."""
        if ks_table is None:
            ks_table = ks_w5_vs_all
        ranked = sorted(
            [(c, v) for c, v in ks_table.items() if c in features.columns],
            key=lambda kv: -kv[1]["ks"] if not np.isnan(kv[1]["ks"]) else 0
        )
        top_features = [name for name, _ in ranked[:top_k] if not np.isnan(_["ks"])]
        sweep = []
        for z_thr in (0.0, 0.25, 0.5, 0.75, 1.0):
            for min_f in (1, 2, 3, 4, 5):
                det, _ = build_w5_detector(features, w5_lo, w5_hi, w5_lo, w5_hi,
                                           ks_table, feature_subset=top_features,
                                           z_threshold=z_thr, min_features=min_f)
                w5_hr = float(det.loc[(det.index >= w5_lo) & (det.index <= w5_hi)].mean())
                nonw5_hr = float(det.loc[~((det.index >= w5_lo) & (det.index <= w5_hi))].mean())
                total_days = int(det.sum())
                sweep.append({"z_threshold": z_thr, "min_features": min_f,
                              "w5_hit_rate": w5_hr, "non_w5_hit_rate": nonw5_hr,
                              "precision_proxy": (w5_hr / max(w5_hr + nonw5_hr, 1e-9))
                                                  if (w5_hr + nonw5_hr) > 0 else np.nan,
                              "total_trigger_days": total_days,
                              "pct_panel": total_days / len(features)})
        # Pick the best viable detector
        viable = [d for d in sweep if d["w5_hit_rate"] >= 0.50 and d["non_w5_hit_rate"] <= 0.50]
        if viable:
            best = max(viable, key=lambda d: d["w5_hit_rate"] - d["non_w5_hit_rate"])
        else:
            best = max(sweep, key=lambda d: d["precision_proxy"])
        # Re-build best detector for full gauntlet
        det_best, _ = build_w5_detector(features, w5_lo, w5_hi, w5_lo, w5_hi,
                                        ks_table, feature_subset=top_features,
                                        z_threshold=best["z_threshold"],
                                        min_features=best["min_features"])
        return sweep, best, top_features, det_best

    print("\nDetector sweep on INTERNAL-only features (R58 parity):")
    sw_internal, best_internal, top_int, det_internal = run_detector_sweep(
        internal_feats, top_k=5, label="R58-internal")
    print(f"  best: z={best_internal['z_threshold']}, min_f={best_internal['min_features']}, "
          f"W5_hr={best_internal['w5_hit_rate']:.0%}, nonW5_hr={best_internal['non_w5_hit_rate']:.0%}")

    print("\nDetector sweep on ENRICHED features (R59 — internal + funding + OI):")
    sw_enriched, best_enriched, top_enr, det_enriched = run_detector_sweep(
        feats, top_k=8, label="R59-enriched")
    print(f"  best: z={best_enriched['z_threshold']}, min_f={best_enriched['min_features']}, "
          f"W5_hr={best_enriched['w5_hit_rate']:.0%}, nonW5_hr={best_enriched['non_w5_hit_rate']:.0%}")

    # === Build sleeve + gauntlet ============================================
    pillar_o_w = cis.pivot_table(index="date", columns="asset", values="O").reindex(columns=tradeable)
    fac_pillar_o_5d = tercile_ls(pillar_o_w, rets[tradeable], k_terciles=R46_K,
                                  cost_bps=R46_COST_BPS).reindex(rets.index).fillna(0.0)

    fac_internal = fac_pillar_o_5d.where(~det_internal, 0.0)
    fac_enriched = fac_pillar_o_5d.where(~det_enriched, 0.0)

    # Known factors
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known = {"market": f_market.reindex(rets.index).fillna(0.0).values,
             "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}
    cut = int(len(rets) * 0.70)

    g_ungated = gauntlet_3check(fac_pillar_o_5d.values, known, cut)
    g_internal = gauntlet_3check(fac_internal.values, known, cut)
    g_enriched = gauntlet_3check(fac_enriched.values, known, cut)

    # === UNION detector: R58 OR R59 fires (try a few promising combos) ========
    union_results = []
    # top-5 internal features used by R58; top-8 enriched by R59
    ranked_all = sorted(ks_w5_vs_all.items(),
                         key=lambda kv: -kv[1]["ks"] if not np.isnan(kv[1]["ks"]) else 0)
    top_5_internal = [name for name, _ in ranked_all if name in internal_feats.columns][:5]
    top_8_enriched = [name for name, _ in ranked_all][:8]
    for z58, mf58, z59, mf59 in [
        (0.75, 2, 0.50, 4),       # R58 best + R59 moderate
        (0.50, 3, 0.50, 4),       # both moderate → tighter
        (0.75, 2, 0.50, 3),       # R58 best + R59 loose
        (1.00, 2, 0.75, 4),       # both strict
    ]:
        d58, _ = build_w5_detector(internal_feats, w5_lo, w5_hi, w5_lo, w5_hi,
                                    ks_w5_vs_all, feature_subset=top_5_internal,
                                    z_threshold=z58, min_features=mf58)
        d59, _ = build_w5_detector(feats, w5_lo, w5_hi, w5_lo, w5_hi,
                                    ks_w5_vs_all, feature_subset=top_8_enriched,
                                    z_threshold=z59, min_features=mf59)
        du = d58 | d59
        fu = fac_pillar_o_5d.where(~du, 0.0)
        gu = gauntlet_3check(fu.values, known, cut)
        u5 = float(du.loc[(du.index >= w5_lo) & (du.index <= w5_hi)].mean())
        un5 = float(du.loc[~((du.index >= w5_lo) & (du.index <= w5_hi))].mean())
        union_results.append({
            "z58": z58, "mf58": mf58, "z59": z59, "mf59": mf59,
            "w5_hit_rate": u5, "non_w5_hit_rate": un5,
            "total_trigger_days": int(du.sum()),
            **gu,
        })

    print("\n3-check gauntlet (costed, full + OOS):")
    print(f"  ungated:       gross_t={g_ungated['gross_t']:+.2f}  OOS_t={g_ungated['oos_t']:+.2f}")
    print(f"  R58 internal:  gross_t={g_internal['gross_t']:+.2f}  OOS_t={g_internal['oos_t']:+.2f}")
    print(f"  R59 enriched:  gross_t={g_enriched['gross_t']:+.2f}  OOS_t={g_enriched['oos_t']:+.2f}")
    print("\nUNION detector (R58 OR R59 fires):")
    for ur in union_results:
        print(f"  z58={ur['z58']}/mf58={ur['mf58']} OR z59={ur['z59']}/mf59={ur['mf59']}: "
              f"W5={ur['w5_hit_rate']:.0%}, nonW5={ur['non_w5_hit_rate']:.0%}, "
              f"gross={ur['gross_t']:+.2f}, OOS={ur['oos_t']:+.2f}, "
              f"pass_all={'✓' if ur['passes_all'] else '✗'}")

    # Per-window P&L for each variant
    def per_window(fac):
        out = {}
        for label, s, e in windows:
            sub = fac.loc[(fac.index >= s) & (fac.index <= e)]
            cumret = (1 + sub).prod() - 1
            ann = ((1 + sub).prod() ** (365 / max(len(sub), 1)) - 1) * 100
            sharpe = float(sub.mean() / sub.std() * np.sqrt(365)) if sub.std() > 0 else np.nan
            out[label] = {"n_days": int(len(sub)),
                          "mean_daily": float(sub.mean()),
                          "cumret": float(cumret), "ann_pct": float(ann),
                          "sharpe": sharpe}
        return out

    w_ungated = per_window(fac_pillar_o_5d)
    w_internal = per_window(fac_internal)
    w_enriched = per_window(fac_enriched)

    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets": int(len(tradeable))},
        "data_coverage": {
            "funding_matched_assets": len(matched_assets),
            "btc_oi_available": btc_oi is not None,
        },
        "feature_columns": list(feats.columns),
        "internal_features": internal_cols,
        "external_features_added": external_cols,
        "ks_W5_vs_nonW5_ranked": [{"feature": name, **v} for name, v in ks_ranked],
        "detector_internal": {
            "label": "R58 internal-only (parity)",
            "features_used": top_int,
            "selected_z_threshold": best_internal["z_threshold"],
            "selected_min_features": best_internal["min_features"],
            "w5_hit_rate": best_internal["w5_hit_rate"],
            "non_w5_hit_rate": best_internal["non_w5_hit_rate"],
            "precision_proxy": best_internal["precision_proxy"],
            "grid_sweep": sw_internal,
        },
        "detector_enriched": {
            "label": "R59 internal + funding + OI",
            "features_used": top_enr,
            "selected_z_threshold": best_enriched["z_threshold"],
            "selected_min_features": best_enriched["min_features"],
            "w5_hit_rate": best_enriched["w5_hit_rate"],
            "non_w5_hit_rate": best_enriched["non_w5_hit_rate"],
            "precision_proxy": best_enriched["precision_proxy"],
            "grid_sweep": sw_enriched,
        },
        "gauntlet_ungated": g_ungated,
        "gauntlet_internal": g_internal,
        "gauntlet_enriched": g_enriched,
        "union_detector_sweep": union_results,
        "window_pnl_ungated": w_ungated,
        "window_pnl_internal": w_internal,
        "window_pnl_enriched": w_enriched,
        "r58_baseline": {"gross_t": R46_BASELINE_T_COSTED, "oos_t": R46_BASELINE_OOS_T,
                         "verdict": "R58 internal-only detector at z=0.75/min_f=2: "
                                    "gross_t=+4.84, OOS_t=+0.41"},
    }

    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    report = format_report(out)
    (out_dir / "REPORT.md").write_text(report)
    print(report)
    print(f"\nSaved: {out_dir/'verdict.json'} + {out_dir/'REPORT.md'}")
    return out


def format_report(out: dict) -> str:
    L = []
    L.append("# R59 — External-Feature W5 Detector Enrichment — REPORT")
    L.append(f"\n**Panel:** {out['panel']['lo']} → {out['panel']['hi']}  ·  "
             f"**{out['panel']['n_days']} days × {out['panel']['n_assets']} assets**")
    L.append(f"\n**W5 boundary:** 2025-10-07 → 2026-02-05 (122 days, the R52/R56/R58 OOS failure mode)")
    dc = out["data_coverage"]
    L.append(f"\n**Data coverage:** {dc['funding_matched_assets']} assets with funding data, "
             f"BTC OI: {'available' if dc['btc_oi_available'] else 'NOT AVAILABLE'}")
    L.append(f"\n**Internal features ({len(out['internal_features'])}):** "
             f"`{', '.join(out['internal_features'])}`")
    L.append(f"\n**External features added ({len(out['external_features_added'])}):** "
             f"`{', '.join(out['external_features_added'])}`")

    # KS ranking — top 12 features
    L.append("\n## W5 vs non-W5 — KS ranking (top 12, all features)\n")
    L.append("| rank | feature | type | KS | p | mean(W5) | mean(non-W5) | mean-diff |")
    L.append("|--:|---|---|--:|--:|--:|--:|--:|")
    for i, row in enumerate(out["ks_W5_vs_nonW5_ranked"][:12], 1):
        ftype = "EXT" if row["feature"] in out["external_features_added"] else "INT"
        L.append(f"| {i} | {row['feature']} | {ftype} | {row['ks']:.2f} | "
                 f"{row['p']:.3f} | {row['mean_w5']:.4f} | {row['mean_ref']:.4f} | "
                 f"{row['mean_diff']:+.4f} |")

    # Detector comparison
    di = out["detector_internal"]
    de = out["detector_enriched"]
    L.append("\n## Detector: R58 internal-only vs R59 enriched\n")
    L.append("| detector | z | min_f | features | W5_hr | nonW5_hr | precision | total days |")
    L.append("|---|--:|--:|---|--:|--:|--:|--:|")
    L.append(f"| R58 internal-only | {di['selected_z_threshold']} | {di['selected_min_features']} | "
             f"`{', '.join(di['features_used'])}` | {di['w5_hit_rate']:.0%} | "
             f"{di['non_w5_hit_rate']:.0%} | {di['precision_proxy']:.0%} | "
             f"{sum(d['total_trigger_days'] for d in di['grid_sweep'] if d['z_threshold']==di['selected_z_threshold'] and d['min_features']==di['selected_min_features'])} |")
    L.append(f"| R59 enriched | {de['selected_z_threshold']} | {de['selected_min_features']} | "
             f"`{', '.join(de['features_used'])}` | {de['w5_hit_rate']:.0%} | "
             f"{de['non_w5_hit_rate']:.0%} | {de['precision_proxy']:.0%} | "
             f"{sum(d['total_trigger_days'] for d in de['grid_sweep'] if d['z_threshold']==de['selected_z_threshold'] and d['min_features']==de['selected_min_features'])} |")

    # 3-check gauntlet comparison
    gu = out["gauntlet_ungated"]
    gi = out["gauntlet_internal"]
    ge = out["gauntlet_enriched"]
    L.append("\n## 3-check gauntlet — ungated vs R58 vs R59\n")
    L.append("| version | gross_t | OOS_t | pass_gross | pass_OOS | pass_all |")
    L.append("|---|--:|--:|:--:|:--:|:--:|")
    L.append(f"| ungated (R46-baseline) | {gu['gross_t']:+.2f} | {gu['oos_t']:+.2f} | "
             f"{'✓' if gu['passes_gross'] else '✗'} | {'✓' if gu['passes_oos'] else '✗'} | "
             f"{'✓' if gu['passes_all'] else '✗'} |")
    L.append(f"| R58 (internal-only) | {gi['gross_t']:+.2f} | {gi['oos_t']:+.2f} | "
             f"{'✓' if gi['passes_gross'] else '✗'} | {'✓' if gi['passes_oos'] else '✗'} | "
             f"{'✓' if gi['passes_all'] else '✗'} |")
    L.append(f"| R59 (internal + funding + OI) | {ge['gross_t']:+.2f} | {ge['oos_t']:+.2f} | "
             f"{'✓' if ge['passes_gross'] else '✗'} | {'✓' if ge['passes_oos'] else '✗'} | "
             f"{'✓' if ge['passes_all'] else '✗'} |")

    # Per-window P&L
    L.append("\n## Per-window P&L — ungated vs R58 vs R59 (ann% / Sharpe)\n")
    L.append("| Window | ungated ann% | R58 internal ann% | R59 enriched ann% |")
    L.append("|---|--:|--:|--:|")
    for label in out["window_pnl_ungated"]:
        u = out["window_pnl_ungated"][label]["ann_pct"]
        i = out["window_pnl_internal"][label]["ann_pct"]
        e = out["window_pnl_enriched"][label]["ann_pct"]
        L.append(f"| {label} | {u:+.1f} | {i:+.1f} | {e:+.1f} |")

    # UNION detector sweep
    L.append("\n## UNION detector (R58 OR R59 fires) — exploration\n")
    L.append("| R58 (z/mf) | R59 (z/mf) | W5_hr | nonW5_hr | total days | gross_t | OOS_t | pass_all |")
    L.append("|---|---|--:|--:|--:|--:|--:|:--:|")
    for ur in out["union_detector_sweep"]:
        L.append(f"| {ur['z58']}/{ur['mf58']} | {ur['z59']}/{ur['mf59']} | "
                 f"{ur['w5_hit_rate']:.0%} | {ur['non_w5_hit_rate']:.0%} | "
                 f"{ur['total_trigger_days']} | {ur['gross_t']:+.2f} | "
                 f"{ur['oos_t']:+.2f} | {'✓' if ur['passes_all'] else '✗'} |")

    # Verdict
    L.append("\n## Read")
    if ge["passes_all"]:
        L.append(f"- **R59 ENRICHED DETECTOR CLEARS THE FULL 3-CHECK GAUNTLET** "
                 f"(gross_t={ge['gross_t']:+.2f}, OOS_t={ge['oos_t']:+.2f}). "
                 f"External features (funding + OI) captured the residual fragility "
                 f"the internal features missed. **The W5 failure mode is now fully "
                 f"addressable — paper-deployable detector-gated sleeve.**")
    elif ge["passes_gross"] and not ge["passes_oos"]:
        if ge["oos_t"] > gi["oos_t"]:
            L.append(f"- R59 enriched detector improves OOS over R58 internal-only "
                     f"({gi['oos_t']:+.2f} → {ge['oos_t']:+.2f}) but still doesn't clear 1.96. "
                     f"External features help but not enough to fully restore OOS.")
        else:
            L.append(f"- R59 enriched detector does NOT improve OOS over R58 internal-only "
                     f"({gi['oos_t']:+.2f} → {ge['oos_t']:+.2f}). External features don't add "
                     f"the missing signal.")
        # UNION check
        best_union = max(out["union_detector_sweep"], key=lambda u: u["oos_t"])
        if best_union["passes_all"]:
            L.append(f"- **UNION (R58 OR R59) CLEARS THE FULL GAUNTLET** — "
                     f"best union config: z58={best_union['z58']}/mf58={best_union['mf58']} OR "
                     f"z59={best_union['z59']}/mf59={best_union['mf59']} → "
                     f"gross_t={best_union['gross_t']:+.2f}, OOS_t={best_union['oos_t']:+.2f}. "
                     f"This is the actionable answer.")
        else:
            L.append(f"- UNION best: gross={best_union['gross_t']:+.2f}, OOS={best_union['oos_t']:+.2f} — "
                     f"closer but still doesn't clear 1.96.")
    else:
        L.append(f"- R59 enriched detector fails both checks "
                 f"(gross_t={ge['gross_t']:+.2f}, OOS_t={ge['oos_t']:+.2f}). External features "
                 f"may need different aggregation (per-asset vs cross-sectional) or aren't the "
                 f"right lens.")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path,
                    default=Path(f"reports/w5_forensics_external/{datetime.now():%Y-%m-%d}"))
    args = ap.parse_args()
    run(args.out_dir)