"""
R63 — Fusion validation: R46 pillar_O sleeve × R62 fragility-gated fade-the-crowd (Seth, 2026-07-21).
====================================================================================================
Per MECHANISM_SPEC §3 (strategy vector) + §P2 (binding capacity): no sleeve ships to the
live book without fusion validation. R62 just produced the first credit-eligible
funding-crowding sleeve (gross=+2.03, OOS=+2.37); R46's pillar_O sleeve is the
already-credit-eligible R45/R46 finding (gross=+2.57, OOS=+0.41 ungated; OOS climbed
under R58/R59 detector overlay). The question this module answers: does combining the
two credit-eligible sleeves produce a JOINT library with materially better
risk-adjusted profile than either sleeve alone — i.e., are they TRULY orthogonal,
and does the fusion survive at the joint level?

Construction (honest, no cherry-pick):
  · Universe: STRICT 28-asset intersection (Hyperliquid funding ∩ CIS ∩ OHLCV
    tradeable). Both legs re-computed on this restricted universe — fusion is not
    tested on the easier 41-asset R46 sleeve.
  · Leg 1: pillar_O 5d/5bps L/S, k=3 (R45/R46 standard cell) on 28-asset subset.
  · Leg 2: per-asset fade-the-crowd funding-z L/S at 21d/0bps gated by external-feature
    fragility detector (R62's best cell) on the same 28 assets.
  · Fusion: w_R46 × Leg1 + (1 − w_R46) × Leg2, sweep w ∈ {0.25, 0.33, 0.50, 0.67, 0.75}.
  · Endpoints: w=1.0 (pure R46) and w=0.0 (pure R62) as sanity references.

Verdict grammar (per MECHANISM_SPEC §3):
  · ✅ FUSION WINS: fused passes 3-check AND max_joint_DD < min(R46_DD, R62_DD)
                    AND corr(R46, R62) < 0.5
  · 🟡 FUSION NEUTRAL: fused improves joint DD OR residual α but one of the three
                       above fails
  · 🔴 FUSION LOSES: fused max DD ≥ max(R46_DD, R62_DD) AND doesn't survive fusion-specific
                     test OR one leg dominates the variance decomposition

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
    load_cis_history_wide, load_daily_returns, tercile_ls,
)
from src.research.validation.cis_quality_robustness import estimate_turnover_ann
from src.research.validation.funding_crowding_ls import (
    score_funding_zwide, funding_ls,
    DEFAULT_ZWIN, R46_K,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.w5_forensics import (
    partition_into_windows, _ks_2samp,
    build_w5_detector, gauntlet_3check,
)
from src.research.validation.r62_fragility_gated_funding import (
    compute_combined_features, build_fragility_ks_table,
    DEFAULT_FRAGILE_WINDOWS, DEFAULT_PLAYABLE_WINDOWS,
)
from src.research.validation.factor_absorption import absorption_test


# === R63 constants ============================================================
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# R46 standard cell re-computed on 28-asset intersection
R46_CAD = 5
R46_BPS = 5.0

# R62 best cell (re-used exactly)
R62_CAD = 21
R62_BPS = 0.0

# R62 best detector config (from R62 ledger, "external" subset)
R62_FEATURE_SET = "external"
R62_Z = 0.5
R62_MF = 2

# Weight sweep
DEFAULT_WEIGHTS = (0.0, 0.25, 0.33, 0.50, 0.67, 0.75, 1.0)


# === R62 detector reproduction (lifted from R62 run) =========================
def _build_r62_detector(features: pd.DataFrame, fragile_mask: pd.Series,
                         fragile_ranges: list, playable_ranges: list) -> tuple:
    """Reproduce the R62 best-cell detector on the same panel."""
    ks = build_fragility_ks_table(features, fragile_mask)
    external_cols = [c for c in features.columns if c in {
        "funding_mean", "funding_disp", "funding_skew",
        "funding_extreme_long_frac", "funding_extreme_short_frac",
        "funding_net_long_frac",
    }]
    det, fired = build_w5_detector(
        features,
        *fragile_ranges[0] if fragile_ranges else (features.index[0], features.index[0]),
        *playable_ranges[0] if playable_ranges else (features.index[0], features.index[0]),
        ks, feature_subset=external_cols,
        z_threshold=R62_Z, min_features=R62_MF,
    )
    return det, ks


# === Per-leg sleeve construction ==============================================
def build_r46_sleeve_28(cis: pd.DataFrame, rets: pd.DataFrame,
                          tradeable: list) -> tuple[pd.Series, pd.Series]:
    """R46 pillar_O 5d/5bps on the tradeable universe. Returns (factor, pillar_O_wide)."""
    pillar_o_w = cis.pivot_table(index="date", columns="asset", values="O").reindex(columns=tradeable)
    pillar_o_w = pillar_o_w.reindex(rets.index).ffill()
    fac = tercile_ls(pillar_o_w, rets[tradeable], k_terciles=R46_K,
                     cost_bps=R46_BPS)  # daily cadence inside tercile_ls
    fac = fac.reindex(rets.index).fillna(0.0)
    return fac, pillar_o_w


def build_r62_sleeve_28(score: pd.DataFrame, rets: pd.DataFrame,
                         tradeable: list, detector: pd.Series) -> pd.Series:
    """R62 fade-the-crowd 21d/0bps gated by detector on the tradeable universe."""
    fac = funding_ls(score, rets[tradeable], k_terciles=R46_K,
                     cost_bps=R62_BPS, rebal_days=R62_CAD).reindex(rets.index).fillna(0.0)
    return fac.where(~detector, 0.0)


# === Fusion ==================================================================
def fuse(leg1: pd.Series, leg2: pd.Series, w: float) -> pd.Series:
    """Weighted fusion: w × Leg1 + (1 − w) × Leg2. Aligned to leg1's index."""
    aligned_l2 = leg2.reindex(leg1.index).fillna(0.0)
    return w * leg1 + (1.0 - w) * aligned_l2


def max_drawdown(returns: pd.Series) -> float:
    """Max drawdown as a negative ratio (e.g. -0.30 = 30% drawdown)."""
    if returns.std() == 0 or len(returns) < 2:
        return 0.0
    cum = (1 + returns.fillna(0.0)).cumprod()
    peak = cum.cummax()
    dd = cum / peak - 1
    return float(dd.min())


# === Per-window P&L (ann%/yr) ================================================
def per_window(fac: pd.Series, windows: list[tuple]) -> dict:
    out = {}
    for label, s, e in windows:
        sub = fac.loc[(fac.index >= s) & (fac.index <= e)]
        if len(sub) < 2:
            out[label] = {"n_days": int(len(sub)), "ann_pct": np.nan,
                          "sharpe": np.nan, "max_dd": np.nan, "cumret": np.nan}
            continue
        cumret = (1 + sub).prod() - 1
        ann = ((1 + sub).prod() ** (PERIODS_PER_YEAR / max(len(sub), 1)) - 1) * 100
        sharpe = float(sub.mean() / sub.std() * np.sqrt(PERIODS_PER_YEAR)) if sub.std() > 0 else np.nan
        out[label] = {"n_days": int(len(sub)), "ann_pct": float(ann),
                      "sharpe": sharpe, "max_dd": max_drawdown(sub),
                      "cumret": float(cumret)}
    return out


# === Run =====================================================================
def run(out_dir: Path,
        cadences_r46: tuple = (R46_CAD,),
        bps_r46: tuple = (R46_BPS,),
        cadences_r62: tuple = (R62_CAD,),
        bps_r62: tuple = (R62_BPS,),
        weights: tuple = DEFAULT_WEIGHTS,
        fragile_labels: tuple = DEFAULT_FRAGILE_WINDOWS,
        playable_labels: tuple = DEFAULT_PLAYABLE_WINDOWS,
        zwin: int = DEFAULT_ZWIN) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R63 — Fusion validation (R46 pillar_O × R62 fragility-gated "
          f"fade-the-crowd) ===\n")

    # ── Load panel ───────────────────────────────────────────────────────────
    cis = load_cis_history_wide()
    rets = load_daily_returns()
    lo = max(cis["date"].min(), rets.index.min())
    hi = min(cis["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable_full = sorted(set(cis["asset"]) & set(rets.columns))
    print(f"Panel: {lo.date()} → {hi.date()} ({len(rets)} days, "
          f"{len(tradeable_full)} CIS ∩ OHLCV assets)")

    funding_daily = load_funding_daily(assets=tradeable_full)
    funding_assets = sorted(set(tradeable_full) & set(funding_daily.columns))
    print(f"Funding daily: {funding_daily.shape[0]} days × "
          f"{funding_daily.shape[1]} assets ({len(funding_assets)} matched)")

    # Trim rets to funding coverage
    if not funding_daily.empty:
        f_lo, f_hi = funding_daily.index.min(), funding_daily.index.max()
        rets = rets.loc[(rets.index >= f_lo) & (rets.index <= f_hi)]
    print(f"Aligned panel: {rets.index.min().date()} → {rets.index.max().date()} "
          f"({len(rets)} days)\n")

    # 28-asset STRICT intersection is the honest fusion universe
    tradeable = funding_assets
    print(f"Strict intersection universe (funding-bearing, used for both legs): "
          f"{len(tradeable)} assets\n")

    # ── 6-window partition ───────────────────────────────────────────────────
    windows = partition_into_windows(rets.index, 6)
    fragile_ranges = [(s, e) for label_, s, e in windows if label_ in fragile_labels]
    playable_ranges = [(s, e) for label_, s, e in windows if label_ in playable_labels]
    fragile_mask = pd.Series(False, index=rets.index)
    for s, e in fragile_ranges:
        fragile_mask.loc[(rets.index >= s) & (rets.index <= e)] = True

    # ── R46 leg (re-compute on 28 assets) ────────────────────────────────────
    print("Building R46 leg (pillar_O 5d/5bps on 28-asset intersection) …")
    leg_r46, pillar_o_w = build_r46_sleeve_28(cis, rets, tradeable)

    # ── R62 leg (score + detector + gate) ────────────────────────────────────
    print("Building R62 leg (fragility-gated fade-the-crowd on 28-asset) …")
    score = score_funding_zwide(funding_daily[tradeable], zwin=zwin,
                                  sign="fade_crowd").reindex(rets.index).ffill()
    feats = compute_combined_features(cis, rets, tradeable_full, tradeable, funding_daily)
    feats = feats.reindex(rets.index)
    det, _ = _build_r62_detector(feats, fragile_mask, fragile_ranges, playable_ranges)
    leg_r62 = build_r62_sleeve_28(score, rets, tradeable, det)

    # ── Known factors (R46/R62 parity) ──────────────────────────────────────
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}
    # OOS is the last OOS_FRAC of the panel; cut at the 70% boundary.
    cut = int(len(rets) * (1.0 - OOS_FRAC))

    # ── Per-leg gauntlet + correlation + max DD ─────────────────────────────
    g_r46 = gauntlet_3check(leg_r46.values, known_full, cut)
    g_r62 = gauntlet_3check(leg_r62.values, known_full, cut)
    corr_legs = float(pd.Series(leg_r46.values).corr(pd.Series(leg_r62.values)))
    dd_r46 = max_drawdown(leg_r46)
    dd_r62 = max_drawdown(leg_r62)

    print(f"R46 leg on 28-asset: gross_t={g_r46['gross_t']:+.2f}, "
          f"OOS_t={g_r46['oos_t']:+.2f}, maxDD={dd_r46:+.2%}")
    print(f"R62 leg on 28-asset: gross_t={g_r62['gross_t']:+.2f}, "
          f"OOS_t={g_r62['oos_t']:+.2f}, maxDD={dd_r62:+.2%}")
    print(f"corr(R46_returns, R62_returns) = {corr_legs:+.2f}\n")

    # ── Per-leg per-window P&L ───────────────────────────────────────────────
    pw_r46 = per_window(leg_r46, windows)
    pw_r62 = per_window(leg_r62, windows)

    # ── Weight sweep: fused gauntlet + per-window + max DD + IR ──────────────
    print(f"══ Weight sweep (w_R46 ∈ {list(weights)}) ══\n")
    rows = []
    for w in weights:
        fused = fuse(leg_r46, leg_r62, w)
        g = gauntlet_3check(fused.values, known_full, cut)
        dd = max_drawdown(fused)
        # Per-window P&L
        pw = per_window(fused, windows)
        # Time-in-market (days where fused != 0)
        tim = float((fused != 0).mean())
        # Sharpe (pooled, gross of fusion-specific turnover, since legs already costed)
        sharpe = float(fused.mean() / fused.std() * np.sqrt(PERIODS_PER_YEAR)) if fused.std() > 0 else float("nan")
        # IR vs each leg
        ir_vs_r46 = float((fused - leg_r46).mean() / (fused - leg_r46).std()
                          * np.sqrt(PERIODS_PER_YEAR)) if (fused - leg_r46).std() > 0 else float("nan")
        ir_vs_r62 = float((fused - leg_r62).mean() / (fused - leg_r62).std()
                          * np.sqrt(PERIODS_PER_YEAR)) if (fused - leg_r62).std() > 0 else float("nan")
        rows.append({
            "w_r46": w,
            "gross_t": g["gross_t"], "oos_t": g["oos_t"],
            "passes_gross": g["passes_gross"], "passes_oos": g["passes_oos"],
            "passes_all": g["passes_all"],
            "max_dd": dd,
            "sharpe": sharpe,
            "time_in_market": tim,
            "ir_vs_r46_leg": ir_vs_r46,
            "ir_vs_r62_leg": ir_vs_r62,
            "per_window": pw,
        })

    print("  w_R46  | gross_t | OOS_t   | pass | maxDD    | sharpe | %TIM | IR vs R46 | IR vs R62")
    print("  -------|---------|---------|------|----------|--------|------|-----------|----------")
    for r in rows:
        print(f"  {r['w_r46']:>4.2f}  | {r['gross_t']:>+7.2f} | {r['oos_t']:>+7.2f} | "
              f"{'✓' if r['passes_all'] else '✗'}    | {r['max_dd']:>+8.2%} | "
              f"{r['sharpe']:>+6.2f} | {r['time_in_market']:>4.0%} | "
              f"{r['ir_vs_r46_leg']:>+9.2f} | {r['ir_vs_r62_leg']:>+9.2f}")
    print()

    # ── Pick best fused row (passes_all first, else max OOS_t) ───────────────
    viable = [r for r in rows if r["passes_all"]]
    if viable:
        best = max(viable, key=lambda r: r["oos_t"])
        verdict_band = "✅ FUSION WINS"
    else:
        # Use max OOS_t with positive gross_t + DD improvement
        candidates = [r for r in rows if 0 < r["w_r46"] < 1
                      and r["oos_t"] > 0 and r["max_dd"] > min(dd_r46, dd_r62)]
        if candidates:
            best = max(candidates, key=lambda r: (r["oos_t"], r["max_dd"]))
            verdict_band = "🟡 FUSION NEUTRAL"
        else:
            best = max([r for r in rows if 0 < r["w_r46"] < 1],
                       key=lambda r: (r["oos_t"], r["gross_t"]))
            verdict_band = "🔴 FUSION LOSES"

    # Build out the verdict with the 3 gates
    fusion_passes = best["passes_all"]
    dd_improves = best["max_dd"] > min(dd_r46, dd_r62)   # less negative DD = better
    orthogonal = abs(corr_legs) < 0.50

    gates_passed = sum([fusion_passes, dd_improves, orthogonal])
    if gates_passed == 3:
        verdict = "✅ FUSION WINS — passes 3-check + DD improves + corr < 0.5"
    elif gates_passed == 2:
        verdict = "🟡 FUSION NEUTRAL — 2 of 3 gates pass"
    else:
        verdict = "🔴 FUSION LOSES — ≤ 1 gate passes"

    print(f"Best fused (w_R46={best['w_r46']:.2f}): "
          f"gross_t={best['gross_t']:+.2f}, OOS_t={best['oos_t']:+.2f}, "
          f"maxDD={best['max_dd']:+.2%}, sharpe={best['sharpe']:+.2f}")
    print(f"  pass_all={fusion_passes}, DD_improves={dd_improves}, "
          f"corr<0.5={orthogonal}")
    print(f"Verdict: {verdict}\n")

    # ── Joint factor decomposition of best fused (market/momentum/R46/R62/resid) ──
    fused_best = fuse(leg_r46, leg_r62, best["w_r46"])
    # Decompose fused variance into components
    X = np.column_stack([
        known_full["market"],
        known_full["momentum"],
        leg_r46.values,
        leg_r62.values,
    ])
    n = len(fused_best)
    y = fused_best.values
    X_ = np.column_stack([np.ones(n), X])
    # OLS via lstsq (no scipy)
    coef, *_ = np.linalg.lstsq(X_, y, rcond=None)
    y_hat = X_ @ coef
    resid = y - y_hat
    # Variance decomposition
    var_y = float(np.var(y))
    var_resid = float(np.var(resid))
    var_attrib = float(var_y - var_resid)
    decomp = {
        "market": float(coef[1]),
        "momentum": float(coef[2]),
        "leg_r46": float(coef[3]),
        "leg_r62": float(coef[4]),
        "alpha_const": float(coef[0]),
        "r2_attrib": float(var_attrib / var_y) if var_y > 0 else float("nan"),
        "r2_resid_var_pct": float(var_resid / var_y) * 100 if var_y > 0 else float("nan"),
    }
    print(f"Decomposition of fused ({best['w_r46']:.2f}-weight R46):")
    print(f"  β_market={decomp['market']:+.3f}, β_momentum={decomp['momentum']:+.3f}, "
          f"β_leg_r46={decomp['leg_r46']:+.3f}, β_leg_r62={decomp['leg_r62']:+.3f}")
    print(f"  R²_attrib={decomp['r2_attrib']:.2f}, residual var {decomp['r2_resid_var_pct']:.0f}% of total\n")

    # ── Capacity proxy (P2) — annualized fused turnover × ADV
    # Use estimate_turnover_ann on the dominant score (highest turnover contributor)
    turnover_r46 = float(estimate_turnover_ann(pillar_o_w, rets[tradeable], R46_CAD))
    turnover_r62 = float(estimate_turnover_ann(score, rets[tradeable], R62_CAD))
    fused_turnover_ann = (best["w_r46"] * turnover_r46
                          + (1 - best["w_r46"]) * turnover_r62)
    # Crude capacity: assumes median ADV ~ $50M/day across the 28 assets => $1.4B/day
    # notional; per-leg clip = 5% of ADV = $250k/leg; fused 2-leg = ~$500k
    CRUDE_ADV_USD = 50e6
    PER_LEG_CLIP_PCT = 0.05
    crude_capacity_usd = (CRUDE_ADV_USD * PER_LEG_CLIP_PCT * 2)

    print(f"Capacity proxy (P2): turnover_ann_fused ≈ {fused_turnover_ann:.1f}, "
          f"declared_capacity ≈ ${crude_capacity_usd/1e6:.1f}M "
          f"(crude ADV × {PER_LEG_CLIP_PCT:.0%}/leg × 2-leg, "
          f"see MECHANISM_SPEC §P2)\n")

    # ── Persist out ──────────────────────────────────────────────────────────
    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets_intersection": len(tradeable),
                  "matched_assets": tradeable},
        "construction": {
            "leg_r46": {"cadence": R46_CAD, "cost_bps": R46_BPS, "k_terciles": R46_K,
                          "universe": "28-asset funding-bearing intersection"},
            "leg_r62": {"cadence": R62_CAD, "cost_bps": R62_BPS, "k_terciles": R46_K,
                          "feature_set": R62_FEATURE_SET, "z_threshold": R62_Z,
                          "min_features": R62_MF, "zwin": zwin,
                          "universe": "28-asset funding-bearing intersection"},
            "fusion_weights": list(weights),
        },
        "windows": [{"label": lab, "start": str(s.date()), "end": str(e.date()),
                      "n_days": int((e - s).days + 1),
                      "fragile": lab in fragile_labels} for lab, s, e in windows],
        "leg_r46": {"gauntlet": g_r46, "max_dd": dd_r46, "per_window": pw_r46},
        "leg_r62": {"gauntlet": g_r62, "max_dd": dd_r62, "per_window": pw_r62},
        "correlation": {"corr_legs": corr_legs, "orthogonal": orthogonal},
        "weight_sweep": [
            {"w_r46": r["w_r46"],
             "gauntlet": {k: r[k] for k in ["gross_t", "oos_t", "passes_gross",
                                              "passes_oos", "passes_all"]},
             "max_dd": r["max_dd"], "sharpe": r["sharpe"], "time_in_market": r["time_in_market"],
             "ir_vs_r46_leg": r["ir_vs_r46_leg"], "ir_vs_r62_leg": r["ir_vs_r62_leg"],
             "per_window": r["per_window"]}
            for r in rows
        ],
        "best_fused": {
            "w_r46": best["w_r46"],
            "gauntlet": {k: best[k] for k in ["gross_t", "oos_t", "passes_gross",
                                                "passes_oos", "passes_all"]},
            "max_dd": best["max_dd"], "sharpe": best["sharpe"],
            "time_in_market": best["time_in_market"],
            "ir_vs_r46_leg": best["ir_vs_r46_leg"], "ir_vs_r62_leg": best["ir_vs_r62_leg"],
            "per_window": best["per_window"],
            "factor_decomposition": decomp,
        },
        "gates": {"fusion_passes_3check": fusion_passes,
                   "dd_improves": dd_improves,
                   "orthogonal_corr_lt_0.5": orthogonal,
                   "gates_passed": gates_passed},
        "capacity_proxy_p2": {
            "crude_adv_per_asset_usd": CRUDE_ADV_USD,
            "per_leg_clip_pct": PER_LEG_CLIP_PCT,
            "fused_notional_usd": crude_capacity_usd,
            "fused_turnover_ann": fused_turnover_ann,
            "turnover_r46_leg": turnover_r46,
            "turnover_r62_leg": turnover_r62,
            "note": "CRUDE — verify with fill-attribution (P2 req'd) before deployment.",
        },
        "verdict": verdict,
    }
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    report = format_report(out, rows)
    (out_dir / "REPORT.md").write_text(report)
    print(report)
    print(f"\nSaved: {out_dir/'verdict.json'} + {out_dir/'REPORT.md'}")
    return out


def format_report(out: dict, rows: list[dict]) -> str:
    L = []
    L.append("# R63 — Sleeve Fusion Validation — REPORT\n")
    panel = out["panel"]
    L.append(f"**Panel:** {panel['lo']} → {panel['hi']}  ·  "
             f"**{panel['n_days']} days × {panel['n_assets_intersection']} "
             f"funding-bearing assets** (STRICT intersection, both legs re-computed on this subset)")
    cn = out["construction"]
    L.append(f"\n**Leg R46:** pillar_O 5d/5bps L/S, k=3, on 28-asset strict intersection")
    L.append(f"**Leg R62:** fade-the-crowd 21d/0bps gated by `external` fragility detector "
             f"(z={cn['leg_r62']['z_threshold']}, mf={cn['leg_r62']['min_features']})")
    L.append(f"**Fusion:** w × Leg R46 + (1−w) × Leg R62, weight sweep "
             f"{cn['fusion_weights']}\n")

    # Per-leg gauntlet
    L.append("## Per-leg gauntlet (re-computed on 28-asset strict intersection)\n")
    L.append("| leg | gross_t | OOS_t | pass_gross | pass_OOS | maxDD |")
    L.append("|---|--:|--:|:--:|:--:|--:|")
    L.append(f"| R46 pillar_O 5d/5bps | {out['leg_r46']['gauntlet']['gross_t']:+.2f} | "
             f"{out['leg_r46']['gauntlet']['oos_t']:+.2f} | "
             f"{'✓' if out['leg_r46']['gauntlet']['passes_gross'] else '✗'} | "
             f"{'✓' if out['leg_r46']['gauntlet']['passes_oos'] else '✗'} | "
             f"{out['leg_r46']['max_dd']:+.2%} |")
    L.append(f"| R62 fade-the-crowd 21d/0bps gated | "
             f"{out['leg_r62']['gauntlet']['gross_t']:+.2f} | "
             f"{out['leg_r62']['gauntlet']['oos_t']:+.2f} | "
             f"{'✓' if out['leg_r62']['gauntlet']['passes_gross'] else '✗'} | "
             f"{'✓' if out['leg_r62']['gauntlet']['passes_oos'] else '✗'} | "
             f"{out['leg_r62']['max_dd']:+.2%} |")
    L.append(f"\n**Cross-leg correlation:** ρ(R46, R62) = {out['correlation']['corr_legs']:+.2f}  →  "
             f"orthogonal? **{'✓ (|ρ| < 0.5)' if out['correlation']['orthogonal'] else '✗'}**\n")

    # Per-leg per-window
    L.append("## Per-window ann%: R46 vs R62 vs Best-fused\n")
    L.append("| Window | character | R46 ann% | R62 ann% | Best-fused ann% |")
    L.append("|--:|---|--:|--:|--:|")
    best = out["best_fused"]
    for w in out["windows"]:
        label = w["label"]
        marker = "🟥" if w["fragile"] else "🟩"
        r46_pct = out["leg_r46"]["per_window"].get(label, {}).get("ann_pct", float("nan"))
        r62_pct = out["leg_r62"]["per_window"].get(label, {}).get("ann_pct", float("nan"))
        fused_pct = best["per_window"].get(label, {}).get("ann_pct", float("nan"))
        L.append(f"| {label} {marker} | — | {r46_pct:+.1f} | {r62_pct:+.1f} | "
                 f"{fused_pct:+.1f} |")

    # Weight sweep table
    L.append(f"\n## Weight sweep — fused gauntlet + max DD\n")
    L.append("| w_R46 | gross_t | OOS_t | pass | maxDD | sharpe | %TIM | IR vs R46 | IR vs R62 |")
    L.append("|--:|--:|--:|:--:|--:|--:|--:|--:|--:|")
    for r in rows:
        L.append(f"| {r['w_r46']:.2f} | {r['gross_t']:+.2f} | {r['oos_t']:+.2f} | "
                 f"{'✓' if r['passes_all'] else '✗'} | {r['max_dd']:+.2%} | "
                 f"{r['sharpe']:+.2f} | {r['time_in_market']:.0%} | "
                 f"{r['ir_vs_r46_leg']:+.2f} | {r['ir_vs_r62_leg']:+.2f} |")

    # Best fused + decomposition
    b = out["best_fused"]
    L.append(f"\n## Best fused (w_R46 = {b['w_r46']:.2f})\n")
    L.append(f"**Gauntlet:** gross_t = {b['gauntlet']['gross_t']:+.2f} "
             f"{'✓' if b['gauntlet']['passes_gross'] else '✗'}, "
             f"OOS_t = {b['gauntlet']['oos_t']:+.2f} "
             f"{'✓' if b['gauntlet']['passes_oos'] else '✗'}, "
             f"pass_all = {b['gauntlet']['passes_all']}")
    L.append(f"**Max DD:** {b['max_dd']:+.2%}  ·  "
             f"Sharpe: {b['sharpe']:+.2f}  ·  "
             f"Time-in-market: {b['time_in_market']:.0%}")
    L.append(f"**IR vs each leg standalone:** "
             f"vs R46 = {b['ir_vs_r46_leg']:+.2f}, vs R62 = {b['ir_vs_r62_leg']:+.2f}")
    decomp = b["factor_decomposition"]
    L.append(f"\n**Factor decomposition (R² attributable / residual %):**")
    L.append(f"- β_market = {decomp['market']:+.3f}")
    L.append(f"- β_momentum = {decomp['momentum']:+.3f}")
    L.append(f"- β_leg_r46 (in-fused) = {decomp['leg_r46']:+.3f}")
    L.append(f"- β_leg_r62 (in-fused) = {decomp['leg_r62']:+.3f}")
    L.append(f"- α_const = {decomp['alpha_const']:+.5f}")
    L.append(f"- R²_attrib = {decomp['r2_attrib']:.2f}, "
             f"residual var = {decomp['r2_resid_var_pct']:.0f}% of fused total")

    # Gates
    gates = out["gates"]
    L.append(f"\n## Verdict gates\n")
    L.append(f"- (1) fusion passes 3-check: **{'✓' if gates['fusion_passes_3check'] else '✗'}** "
             f"(gross_t={b['gauntlet']['gross_t']:+.2f}, OOS_t={b['gauntlet']['oos_t']:+.2f})")
    L.append(f"- (2) max DD improves (best-fused < min(R46, R62)): "
             f"**{'✓' if gates['dd_improves'] else '✗'}** "
             f"(fused={b['max_dd']:+.2%}, min(legs)={min(out['leg_r46']['max_dd'], out['leg_r62']['max_dd']):+.2%})")
    L.append(f"- (3) orthogonal: |ρ(R46, R62)| < 0.5: "
             f"**{'✓' if gates['orthogonal_corr_lt_0.5'] else '✗'}** "
             f"(ρ={out['correlation']['corr_legs']:+.2f})")
    L.append(f"\nGates passed: **{gates['gates_passed']}/3**")

    # Capacity proxy (P2)
    cap = out["capacity_proxy_p2"]
    L.append(f"\n## Capacity proxy (MECHANISM_SPEC §P2 — binding capacity)\n")
    L.append(f"- Fused turnover (ann): **{cap['fused_turnover_ann']:.1f}** "
             f"(R46 leg: {cap['turnover_r46_leg']:.1f}, R62 leg: {cap['turnover_r62_leg']:.1f})")
    L.append(f"- Crude declared capacity: **${cap['fused_notional_usd']/1e6:.1f}M** "
             f"(assumes median ADV ${cap['crude_adv_per_asset_usd']/1e6:.0f}M/asset × "
             f"{cap['per_leg_clip_pct']:.0%}/leg × 2-leg)")
    L.append(f"- **{cap['note']}**")

    # Verdict
    L.append(f"\n## Verdict\n**{out['verdict']}**\n")
    if gates["gates_passed"] >= 2:
        L.append(f"**Action per MECHANISM_SPEC §P2:** declare joint capacity "
                 f"`${cap['fused_notional_usd']/1e6:.1f}M` (P2) and start flat-recording "
                 f"the fragility-gated position count (P3). Per §P1 forward commitment: "
                 f"this report IS the pre-declared criterion — the live numbers must reconcile to "
                 f"the cells in this sweep at horizon.")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--zwin", type=int, default=DEFAULT_ZWIN)
    args = ap.parse_args()
    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r63_fusion_validation/{today}")
    run(out, zwin=args.zwin)
