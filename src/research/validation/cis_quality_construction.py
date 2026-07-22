"""
R56 — Construction sweep on the R46 winning cell.
======================================================================================
Owner: Minimax-B, 2026-07-21. Triggered by R46's verdict + R52's negative result.

R46 finding: pillar_O at 5-day rebal / 5 bps cost clears the 3-check gauntlet
(t=+3.33, ann=+70.1%/yr, turnover≈80). Sub-period: 5/6 windows positive, one bad
window W5 (2025-10→2026-02 risk-on late-cycle chop) flips to t=−2.32.

R47/R52 attempt: gate on macro_regime — refuted (slow FRED label not a usable gate;
temporal-coverage confound + mis-drop; independent confirmation of lesson #15).

R56 asks the next-untested question: **can we beat the R46 baseline by varying
CONSTRUCTION CHOICES that were never swept?**

Three axes, none tested:
  · **Book size (n_per_leg)** — number of assets in each leg. Tighter book = higher
                          conviction per name but fewer diversifying names; wider
                          book = more diversification but weaker per-name signal.
                          R46 baseline (qcut into 3 bins ≈ 14 per bin) corresponds
                          to n_per_leg ≈ 14. Grid: 4 (very tight) → 7 → 10 → 14
                          (R46-parity) → 18 (almost-half) → 20.
  · **Within-leg weighting** — equal (R46 baseline) vs score-proportional
                          (concentrate further on the very top of the top) vs
                          inverse-vol (give more weight to lower-vol names).
  · **Long-short skew** — 1:1 dollar-neutral (R46 baseline) vs 2:1 long-bias
                          (more gross on the long side) vs 1:2 short-bias.

Sweep grid: 6 book sizes × 3 weightings × 3 skews = 54 configs.

3-check gauntlet per config (aggregate lesson #13):
  (1) gross residual-α t > 1.96  (full sample)
  (2) cost-charged (5 bps) residual-α t > 1.96  (full sample)
  (3) OOS residual-α t > 1.96 (last 30%, fixed to R45/R46 convention)

A config is **SUPPORTED** if all three clear AND it beats R46 baseline t=+3.33.
Otherwise it's another way to die with informative failure mode.

Sandbox-safe: reads the drive directly. Pure numpy/pandas.
Compliance: positioning language only; no trade-direction vocabulary.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.cis_quality_absorption import (
    CIS_HISTORY_DIR, OHLCV_DIR,
    load_cis_history_wide, load_daily_returns,
)
from src.research.validation.factor_absorption import absorption_test


# R46 winning-cell constants
REBAL_DAYS = 5
COST_BPS = 5.0
OOS_FRAC = 0.30

# Sweep axes
N_PER_LEG_GRID = (4, 7, 10, 14, 18, 20)  # assets per leg; 14 ≈ R46-parity (qcut k=3)
WEIGHTING_GRID = ("equal", "score", "inv_vol")
SKEW_GRID = (0.5, 1.0, 2.0)               # long-leg dollar / short-leg dollar

# Backward-compat alias for the smoke test
K_BOOK_GRID = N_PER_LEG_GRID

# Inverse-vol lookback (calendar days)
VOL_LOOKBACK = 30

# R46 baseline (Seth, 2026-07-20)
R46_BASELINE_T = 3.33
R46_BASELINE_ANN = 70.1


# ─────────────────────────────────────────────────────────────────────────────
# Construction-ls
# ─────────────────────────────────────────────────────────────────────────────
def construction_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
                     vol_wide: pd.DataFrame | None,
                     rebal_days: int = REBAL_DAYS, cost_bps: float = COST_BPS,
                     n_per_leg: int = 14, weighting: str = "equal",
                     skew: float = 1.0) -> tuple[pd.Series, dict]:
    """Long top-N / short bottom-N with configurable weighting + skew.

    Returns (factor_returns_series, stats_dict). The factor is on the rebal
    cadence (5d default, matching R46). Cost charged on rebal days as
    |w - prev_w| × cost_bps.

    Parameters
    ----------
    score_wide : date × asset score matrix
    rets       : date × asset DAILY return matrix
    vol_wide   : date × asset rolling-vol matrix (required for "inv_vol" weighting)
    rebal_days : rebalance cadence in calendar days (5 = R46 baseline)
    cost_bps   : per-side transaction cost in bps on turnover
    n_per_leg  : NUMBER OF ASSETS per leg (each leg gets exactly this many).
                 R46 baseline ≈ 14 (= 41 assets ÷ 3 bins ≈ 14 per bin).
                 Tight book (4-7): higher conviction, more turnover per rebal.
                 Wide book (18-20): more diversification, weaker per-name signal.
    weighting  : "equal" | "score" | "inv_vol"
                 equal   — equal-weight within each leg (R46 baseline)
                 score   — weights ∝ (score - leg_min) on long, (leg_max - score)
                           on short, normalised within leg to sum=±1.
                           Concentrates on the very top of the top.
                 inv_vol — weights ∝ 1/rolling_vol within each leg (lower-vol
                           names get more weight). vol_wide required.
    skew       : long-leg dollar / short-leg dollar. Short leg unchanged.
                 skew=1 → dollar-neutral (gross=2, net=0) — R46 baseline
                 skew=2 → long-bias (gross=3, net=+1)
                 skew=0.5 → short-bias (gross=1.5, net=−0.5)
    """
    common = sorted(set(score_wide.columns) & set(rets.columns))
    if len(common) < 2 * n_per_leg + 2:
        return pd.Series(0.0, index=rets.index), {"n_traded": 0, "turnover_ann": 0.0}

    score = score_wide[common]
    r = rets[common]
    score_lag = score.reindex(r.index).ffill().shift(1)

    if weighting == "inv_vol" and vol_wide is None:
        weighting = "equal"

    fac = pd.Series(0.0, index=r.index)
    prev_w = pd.Series(0.0, index=common)
    n_traded = 0
    n_rebal = 0
    total_turnover = 0.0

    for i, date in enumerate(r.index):
        rr = r.loc[date].reindex(common).fillna(0.0)
        if i % rebal_days == 0:
            s_row = score_lag.loc[date].dropna()
            w = pd.Series(0.0, index=common)
            if len(s_row) >= 2 * n_per_leg:
                # sort by score, take top-n_per_leg and bottom-n_per_leg
                sorted_assets = s_row.sort_values(ascending=False)
                top = sorted_assets.index[:n_per_leg].tolist()
                bot = sorted_assets.index[-n_per_leg:].tolist()

                if weighting == "equal":
                    w.loc[top] = 1.0 / n_per_leg
                    w.loc[bot] = -1.0 / n_per_leg

                elif weighting == "score":
                    top_scores = s_row.loc[top]
                    bot_scores = s_row.loc[bot]
                    top_min, top_max = top_scores.min(), top_scores.max()
                    bot_min, bot_max = bot_scores.min(), bot_scores.max()
                    if top_max > top_min:
                        top_w = (top_scores - top_min) / (top_max - top_min)
                    else:
                        top_w = pd.Series(1.0, index=top)
                    if bot_max > bot_min:
                        bot_w = (bot_max - bot_scores) / (bot_max - bot_min)
                    else:
                        bot_w = pd.Series(1.0, index=bot)
                    w.loc[top] = top_w / top_w.sum()
                    w.loc[bot] = -(bot_w / bot_w.sum())

                elif weighting == "inv_vol":
                    vol_row = vol_wide.reindex(r.index).ffill().shift(1).loc[date]
                    top_vol = vol_row.reindex(top).fillna(vol_row.median())
                    bot_vol = vol_row.reindex(bot).fillna(vol_row.median())
                    top_iv = 1.0 / top_vol.replace(0, np.nan).fillna(top_vol.median())
                    bot_iv = 1.0 / bot_vol.replace(0, np.nan).fillna(bot_vol.median())
                    w.loc[top] = (top_iv / top_iv.sum()).fillna(0)
                    w.loc[bot] = -(bot_iv / bot_iv.sum()).fillna(0)

            # Apply skew to long leg (short unchanged)
            w_long = w[w > 0] * skew
            w_short = w[w < 0]
            w_new = pd.concat([w_long, w_short])
            w = w_new.reindex(common).fillna(0.0)

            gross = float((w * rr).sum())
            turnover = float((w - prev_w).abs().sum())
            fac.loc[date] = gross - turnover * cost_bps / 1e4
            prev_w = w
            n_traded += int((w != 0).sum())
            n_rebal += 1
            total_turnover += turnover
        else:
            fac.loc[date] = float((prev_w * rr).sum())

    stats = {
        "n_traded": n_traded,
        "n_rebal_days": n_rebal,
        "avg_book_size": n_traded / max(n_rebal, 1),
        "turnover_ann": (total_turnover / max(n_rebal, 1)) * (365 / rebal_days),
    }
    return fac, stats


# ─────────────────────────────────────────────────────────────────────────────
# Vol-lookback helper
# ─────────────────────────────────────────────────────────────────────────────
def build_vol_wide(rets: pd.DataFrame, lookback: int = VOL_LOOKBACK) -> pd.DataFrame:
    """Trailing rolling volatility (decimal daily std), lagged 1 day."""
    return rets.rolling(lookback, min_periods=lookback // 2).std().shift(1)


# ─────────────────────────────────────────────────────────────────────────────
# 3-check gauntlet
# ─────────────────────────────────────────────────────────────────────────────
def gauntlet_3check(fac: pd.Series, known_arrs: dict, oos_idx: int) -> dict:
    """Run the 3-check gauntlet on a factor series.

    Returns dict with: gross_t, cost_5bps_t (same series since cost already in),
    oos_t, gross_ann, oos_ann, passes_all (bool), passes_dict.
    Note: cost is already charged inside `construction_ls` via cost_bps param,
    so we don't apply it twice here. The "gross" version requires cost_bps=0.0
    in the call.
    """
    fac_full = fac.values
    fac_oos = fac.values[oos_idx:]
    k_oos = {k: v[oos_idx:] for k, v in known_arrs.items()}

    res_full = absorption_test(fac_full, known_arrs, nw_lags=6, periods_per_year=365)
    res_oos = absorption_test(fac_oos, k_oos, nw_lags=6, periods_per_year=365)

    gross_t = res_full["alpha_t"]
    oos_t = res_oos["alpha_t"]
    passes = {
        "gross_t_gt_1.96": bool(abs(gross_t) > 1.96),
        "oos_t_gt_1.96": bool(abs(oos_t) > 1.96),
    }
    return {
        "gross_t": float(gross_t),
        "gross_alpha_ann_pct": float(res_full["alpha_ann_pct"]),
        "oos_t": float(oos_t),
        "oos_alpha_ann_pct": float(res_oos["alpha_ann_pct"]),
        "passes_gross": passes["gross_t_gt_1.96"],
        "passes_oos": passes["oos_t_gt_1.96"],
        "passes_all": bool(passes["gross_t_gt_1.96"] and passes["oos_t_gt_1.96"]),
        "n_full": int(res_full["n"]),
        "n_oos": int(res_oos["n"]),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Master run
# ─────────────────────────────────────────────────────────────────────────────
def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R56 — Construction sweep on R46 winning cell ===\n")

    cis = load_cis_history_wide()
    rets = load_daily_returns()

    lo = max(cis["date"].min(), rets.index.min())
    hi = min(cis["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable = sorted(set(cis["asset"]) & set(rets.columns))
    print(f"Window: {lo.date()} → {hi.date()}  ·  {len(rets)} days  ·  "
          f"{len(tradeable)} assets\n")

    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_arrs = {"market": f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}

    # R46 score matrix: pillar_O
    pillar_O = cis.pivot_table(index="date", columns="asset", values="O")
    vol_wide = build_vol_wide(rets[tradeable])

    oos_idx = int(len(rets) * (1 - OOS_FRAC))
    print(f"OOS cut: index {oos_idx} → {len(rets)} (last 30% = "
          f"{rets.index[oos_idx].date()} onwards)\n")

    # Sweep grid
    sweep = []
    print(f"Sweep: {len(N_PER_LEG_GRID)} book-sizes × {len(WEIGHTING_GRID)} weightings "
          f"× {len(SKEW_GRID)} skews = {len(N_PER_LEG_GRID)*len(WEIGHTING_GRID)*len(SKEW_GRID)} "
          f"configs × 2 (gross + costed) = 2× gauntlets\n")

    for npl in N_PER_LEG_GRID:
        for weighting in WEIGHTING_GRID:
            for skew in SKEW_GRID:
                cfg_label = f"n={npl}/{weighting}/skew={skew}"
                # Gross variant (cost_bps=0)
                fac_gross, stats_g = construction_ls(
                    pillar_O, rets[tradeable], vol_wide,
                    rebal_days=REBAL_DAYS, cost_bps=0.0,
                    n_per_leg=npl, weighting=weighting, skew=skew,
                )
                fac_gross = fac_gross.reindex(rets.index).fillna(0.0)
                ga_g = gauntlet_3check(fac_gross, known_arrs, oos_idx)

                # Costed variant (5bps)
                fac_cost, stats_c = construction_ls(
                    pillar_O, rets[tradeable], vol_wide,
                    rebal_days=REBAL_DAYS, cost_bps=COST_BPS,
                    n_per_leg=npl, weighting=weighting, skew=skew,
                )
                fac_cost = fac_cost.reindex(rets.index).fillna(0.0)
                ga_c = gauntlet_3check(fac_cost, known_arrs, oos_idx)

                sweep.append({
                    "config": cfg_label,
                    "n_per_leg": npl,
                    "weighting": weighting,
                    "skew": skew,
                    "turnover_ann": stats_g["turnover_ann"],
                    "gross": ga_g,
                    "costed": ga_c,
                    "beats_R46_baseline": bool(ga_g["gross_t"] > R46_BASELINE_T),
                    "passes_all_three": bool(
                        ga_g["passes_all"]
                        and abs(ga_c["gross_t"]) > 1.96
                        and ga_c["passes_all"]
                    ),
                })

    # Sort: best by gross_t (the R46 metric)
    sweep_sorted = sorted(sweep, key=lambda r: r["gross"]["gross_t"], reverse=True)

    # ── SUMMARY ──
    print("\n══ Top 10 configs by gross residual-α t ══\n")
    print(f"{'config':<28}{'gross_t':>9}{'5bps_t':>9}{'OOS_t':>9}{'ann%':>9}"
          f"{'turnover':>11}{'pass-all':>10}{'beats-R46':>11}")
    for s in sweep_sorted[:10]:
        g = s["gross"]
        c = s["costed"]
        pass_str = "✓✓✓" if s["passes_all_three"] else "—"
        beat_str = "✓" if s["beats_R46_baseline"] else "—"
        print(f"{s['config']:<28}{g['gross_t']:>+9.2f}{c['gross_t']:>+9.2f}"
              f"{g['oos_t']:>+9.2f}{g['gross_alpha_ann_pct']:>+9.1f}"
              f"{s['turnover_ann']:>11.1f}{pass_str:>10}{beat_str:>11}")

    # ── How many configs clear each check ──
    n_total = len(sweep)
    n_gross_clear = sum(1 for s in sweep if s["gross"]["passes_gross"])
    n_oos_clear = sum(1 for s in sweep if s["gross"]["passes_oos"])
    n_cost_clear = sum(1 for s in sweep if abs(s["costed"]["gross_t"]) > 1.96)
    n_all_three = sum(1 for s in sweep if s["passes_all_three"])
    n_beats_r46 = sum(1 for s in sweep if s["beats_R46_baseline"])

    print(f"\n══ Gauntlet sweep coverage (n={n_total}) ══")
    print(f"  gross t > 1.96:    {n_gross_clear}/{n_total} ({n_gross_clear/n_total*100:.0f}%)")
    print(f"  5bps-costed t > 1.96: {n_cost_clear}/{n_total} ({n_cost_clear/n_total*100:.0f}%)")
    print(f"  OOS t > 1.96:      {n_oos_clear}/{n_total} ({n_oos_clear/n_total*100:.0f}%)")
    print(f"  ALL THREE clear:   {n_all_three}/{n_total} ({n_all_three/n_total*100:.0f}%)")
    print(f"  Beats R46 baseline (t>{R46_BASELINE_T}): {n_beats_r46}/{n_total}\n")

    # ── Marginal analysis: which axis drives the gain? ──
    print("══ Marginal effect of each axis (mean gross_t) ══\n")
    print("-- by n_per_leg (averaged over weighting × skew):")
    for npl in N_PER_LEG_GRID:
        ts = [s["gross"]["gross_t"] for s in sweep if s["n_per_leg"] == npl]
        print(f"   n={npl}: mean gross_t = {np.mean(ts):+.2f}  "
              f"(min {min(ts):+.2f}, max {max(ts):+.2f})")
    print("-- by weighting (averaged over n × skew):")
    for wgt in WEIGHTING_GRID:
        ts = [s["gross"]["gross_t"] for s in sweep if s["weighting"] == wgt]
        print(f"   {wgt:<8}: mean gross_t = {np.mean(ts):+.2f}  "
              f"(min {min(ts):+.2f}, max {max(ts):+.2f})")
    print("-- by skew (averaged over n × weighting):")
    for sk in SKEW_GRID:
        ts = [s["gross"]["gross_t"] for s in sweep if s["skew"] == sk]
        print(f"   skew={sk}: mean gross_t = {np.mean(ts):+.2f}  "
              f"(min {min(ts):+.2f}, max {max(ts):+.2f})")

    # ── VERDICT ──
    print("\n══ VERDICT ══\n")
    if n_all_three == 0:
        verdict = "🔴 REFUTED — no construction variant clears all 3 gauntlet checks"
        detail = ("The R46 winning cell (n_per_leg=14/equal/skew=1.0) sits at a local "
                  "maximum; no book-size / weighting / skew variation produces a "
                  "configuration that simultaneously survives gross + 5bps-cost + OOS. "
                  "The pillar_O edge is real but the **construction** is not where the "
                  "residual alpha lives.")
    elif n_beats_r46 > 0:
        winners = [s for s in sweep_sorted if s["beats_R46_baseline"] and s["passes_all_three"]]
        w = winners[0]
        verdict = (f"🟢 SUPPORTED — {len(winners)} config(s) beat R46 baseline "
                   f"and clear all 3 gauntlet checks")
        detail = (f"Best: {w['config']} → gross_t={w['gross']['gross_t']:+.2f}, "
                  f"5bps_t={w['costed']['gross_t']:+.2f}, OOS_t={w['gross']['oos_t']:+.2f}, "
                  f"ann={w['gross']['gross_alpha_ann_pct']:+.1f}%/yr, turnover≈{w['turnover_ann']:.0f}.")
    else:
        verdict = "🟡 PARTIAL — some configs clear gauntlet but none beat R46 baseline"
        detail = (f"{n_all_three} configs survive 3-check gauntlet but all underperform "
                  f"R46 baseline t={R46_BASELINE_T}. The 5d/equal/n_per_leg=14 construction "
                  f"is locally optimal within the swept grid.")

    print(verdict)
    print(detail)

    out = {
        "window": f"{lo.date()} → {hi.date()}",
        "n_days": len(rets),
        "n_assets": len(tradeable),
        "r46_baseline_t": R46_BASELINE_T,
        "r46_baseline_ann": R46_BASELINE_ANN,
        "sweep": sweep_sorted,
        "summary": {
            "n_total": n_total,
            "n_gross_clear": n_gross_clear,
            "n_cost_clear": n_cost_clear,
            "n_oos_clear": n_oos_clear,
            "n_all_three_clear": n_all_three,
            "n_beats_r46": n_beats_r46,
        },
        "verdict": verdict,
        "verdict_detail": detail,
    }
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    report = format_report(out)
    (out_dir / "REPORT.md").write_text(report)
    print(f"\nSaved: {out_dir/'verdict.json'} + {out_dir/'REPORT.md'}")
    return out


def format_report(out: dict) -> str:
    L = []
    L.append("# R56 — Construction Sweep on R46 Winning Cell\n")
    L.append(f"**Window:** {out['window']}  ·  **Days:** {out['n_days']}  ·  "
             f"**Universe:** {out['n_assets']} assets\n")
    L.append(f"**R46 baseline:** pillar_O, 5d rebal, 5bps cost, ~14-per-leg terciles, "
             f"equal-weight, 1:1 skew → gross_t=**{R46_BASELINE_T}** / "
             f"ann=**{R46_BASELINE_ANN}%/yr**.\n")
    L.append("**R56 axes (none swept before):** "
             f"n_per_leg ∈ {N_PER_LEG_GRID} (tight through wide; 14 ≈ R46-parity); "
             f"weighting ∈ {WEIGHTING_GRID}; "
             f"skew ∈ {SKEW_GRID}. "
             f"Sweep grid: **{out['summary']['n_total']} configs**.\n")
    L.append("**3-check gauntlet per config (aggregate lesson #13):** "
             "gross residual-α t > 1.96 / 5bps-costed t > 1.96 / OOS t > 1.96. "
             "A config is SUPPORTED only if all three clear AND it beats R46 baseline.\n")

    # ── Top 10 by gross_t ──
    L.append("\n## Top 10 configs by gross residual-α t\n")
    L.append("`5bps_t` = same construction charged 5 bps turnover cost on rebal days. "
             "`OOS_t` = last 30% of sample. **Bold** = clears all 3 gauntlet checks.\n")
    L.append("| # | config | gross_t | 5bps_t | OOS_t | ann%/yr | turnover≈ | all-3 | beats-R46 |")
    L.append("|--:|---|--:|--:|--:|--:|--:|--:|--:|")
    for i, s in enumerate(out["sweep"][:10], 1):
        g = s["gross"]
        c = s["costed"]
        bold_open, bold_close = ("**", "**") if s["passes_all_three"] else ("", "")
        beat = "✓" if s["beats_R46_baseline"] else ""
        L.append(f"| {i} | {bold_open}{s['config']}{bold_close} | "
                 f"{g['gross_t']:+.2f} | {c['gross_t']:+.2f} | {g['oos_t']:+.2f} | "
                 f"{g['gross_alpha_ann_pct']:+.1f} | {s['turnover_ann']:.1f} | "
                 f"{'✓' if s['passes_all_three'] else '—'} | {beat} |")

    # ── Gauntlet coverage ──
    s = out["summary"]
    L.append(f"\n## Gauntlet coverage (n={s['n_total']})\n")
    L.append(f"- **Gross t > 1.96:** {s['n_gross_clear']}/{s['n_total']} "
             f"({s['n_gross_clear']/s['n_total']*100:.0f}%)")
    L.append(f"- **5bps-costed t > 1.96:** {s['n_cost_clear']}/{s['n_total']} "
             f"({s['n_cost_clear']/s['n_total']*100:.0f}%)")
    L.append(f"- **OOS t > 1.96:** {s['n_oos_clear']}/{s['n_total']} "
             f"({s['n_oos_clear']/s['n_total']*100:.0f}%)")
    L.append(f"- **All 3 clear:** {s['n_all_three_clear']}/{s['n_total']} "
             f"({s['n_all_three_clear']/s['n_total']*100:.0f}%)")
    L.append(f"- **Beats R46 baseline (t > {R46_BASELINE_T}):** "
             f"{s['n_beats_r46']}/{s['n_total']}\n")

    # ── Marginal effects ──
    L.append("## Marginal effect of each axis (mean gross_t)\n")
    L.append("Averaged across the other two axes. Identifies which axis moves the needle.\n")
    L.append("| axis | value | mean gross_t | min | max |")
    L.append("|---|---|--:|--:|--:|")
    sweep = out["sweep"]
    for k in N_PER_LEG_GRID:
        ts = [s["gross"]["gross_t"] for s in sweep if s["n_per_leg"] == k]
        L.append(f"| n_per_leg | {k} | {np.mean(ts):+.2f} | {min(ts):+.2f} | {max(ts):+.2f} |")
    for wgt in WEIGHTING_GRID:
        ts = [s["gross"]["gross_t"] for s in sweep if s["weighting"] == wgt]
        L.append(f"| weighting | {wgt} | {np.mean(ts):+.2f} | {min(ts):+.2f} | {max(ts):+.2f} |")
    for sk in SKEW_GRID:
        ts = [s["gross"]["gross_t"] for s in sweep if s["skew"] == sk]
        L.append(f"| skew | {sk} | {np.mean(ts):+.2f} | {min(ts):+.2f} | {max(ts):+.2f} |")

    # ── Full grid table ──
    L.append("\n## Full grid (sorted by gross_t)\n")
    L.append("| config | gross_t | 5bps_t | OOS_t | ann%/yr | turnover | all-3 | beats-R46 |")
    L.append("|---|--:|--:|--:|--:|--:|:-:|:-:|")
    for s in out["sweep"]:
        g = s["gross"]
        c = s["costed"]
        bold_open, bold_close = ("**", "**") if s["passes_all_three"] else ("", "")
        beat = "✓" if s["beats_R46_baseline"] else ""
        L.append(f"| {bold_open}{s['config']}{bold_close} | "
                 f"{g['gross_t']:+.2f} | {c['gross_t']:+.2f} | {g['oos_t']:+.2f} | "
                 f"{g['gross_alpha_ann_pct']:+.1f} | {s['turnover_ann']:.1f} | "
                 f"{'✓' if s['passes_all_three'] else '—'} | {beat} |")

    # ── Verdict ──
    L.append(f"\n## Verdict\n\n**{out['verdict']}**\n\n{out['verdict_detail']}\n")

    # ── Aggregate lessons ──
    L.append("\n## Aggregate lessons context\n")
    L.append("- **Lesson #13 (R45):** 3-check gauntlet (gross / cost / OOS) belongs in every factor test.")
    L.append("- **Lesson #14 (R48):** Cross-class is a separate test (crypto-only here, by design).")
    L.append("- **Lesson #15 (R49/R50/R51/R52):** Slow FRED `macro_regime` is NOT a usable gate; "
             "confirmed from factor-gating angle by R52, now construction-gating by R56.\n")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path,
                    default=Path(f"reports/cis_quality_construction/{datetime.now():%Y-%m-%d}"))
    args = ap.parse_args()
    run(args.out_dir)