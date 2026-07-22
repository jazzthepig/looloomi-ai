"""
R60 — Funding-crowding L/S per-asset (NEW factor, Seth 2026-07-21).
================================================================================
Driven by R49's final recommendation: per-asset overlay (R44/R36-style) is the
highest-orthogonality remaining route after the pooled cross-section path was
refuted (R47 — F1 memecoin rotation destroyed the pooled construction; R49 —
12-cell regime gate couldn't fix it either). R60 builds that path:

    Cross-sectional L/S indexed by PER-ASSET funding z-score (NOT pooled demean).
    LONG low-funding (top tercile of -funding_z) / SHORT high-funding (bottom tercile).
    Same 5-day-rebal / 5-bps / k=3 construction as R46 winning cell — direct
    comparability.

Universe: 28-asset overlap of {Hyperliquid funding panel × CIS × OHLCV tradeable}.
          Same 731-day window as R45/R46 (2024-06-07 → 2026-06-07).

Gauntlet: 3-check (gross residual-α t > 1.96 + 5bps t > 1.96 + OOS t > 1.96),
          identical to R58/R59. Sub-period W1..W6 partition matches R57/R58/R59
          for direct W5 attribution.

Why this is NOT R47 / R49 redux:
  · R47 pooled cross-section demean: zeroed out the per-asset signal by design.
  · R49 regime-conditioned pooled: still pooled, F1 (crowd-was-right) is structural.
  · R60 uses the per-asset z-score as a CROSS-SECTIONAL RANKING score — each
    asset's funding history is its own signal, no cross-section subtraction.
    The L/S picks names that have a HIGH z-funding this week (short) and LOW
    z-funding (long). Two assets with identical funding levels can be on
    opposite sides depending on their own history. This is what R49 recommended.

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
from src.research.validation.cis_quality_robustness import (
    cadence_ls, cadence_sweep, sub_period_absorption, quarter_cuts,
    estimate_turnover_ann,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.w5_forensics import gauntlet_3check
from src.research.validation.factor_absorption import absorption_test


# === Constants (mirror R46) ===================================================
R46_REBAL_DAYS = 5
R46_COST_BPS = 5.0
R46_K = 3
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# R60-specific defaults
DEFAULT_ZWIN = 30                  # per-asset funding z window (R35 zwin parallel)
DEFAULT_CADENCES = (1, 3, 5, 7, 14, 21)
DEFAULT_COST_GRID = (0.0, 5.0, 10.0)
DEFAULT_K_TERCILES = R46_K

# Sign convention
SIGN_FADE_CROWD = "fade_crowd"     # default: LONG low-funding (the R49-recommended direction)
SIGN_RIDE_CROWD = "ride_crowd"     # alternative: LONG high-funding (long crowd)


# === Score construction =======================================================
def score_funding_zwide(funding_daily: pd.DataFrame,
                        zwin: int = DEFAULT_ZWIN,
                        sign: str = SIGN_FADE_CROWD) -> pd.DataFrame:
    """Per-asset rolling z-score of daily funding (R35 zwin parallel).

    Args:
        funding_daily: wide DataFrame [date × asset] of daily-mean funding rates (decimal).
        zwin: rolling window in days for the z-score.
        sign: "fade_crowd" returns -z so HIGH score = LOW funding = LONG candidate
              (the R49-recommended direction). "ride_crowd" returns +z.

    Returns:
        wide DataFrame [date × asset] of funding z-scores (signed per `sign`).
        Rows before zwin warmup are NaN (downstream ffill handles).
    """
    if sign not in (SIGN_FADE_CROWD, SIGN_RIDE_CROWD):
        raise ValueError(f"sign must be {SIGN_FADE_CROWD} or {SIGN_RIDE_CROWD}, got {sign!r}")
    mu = funding_daily.rolling(zwin, min_periods=max(5, zwin // 3)).mean()
    sd = funding_daily.rolling(zwin, min_periods=max(5, zwin // 3)).std()
    z = (funding_daily - mu) / (sd + 1e-12)
    return -z if sign == SIGN_FADE_CROWD else z


# === L/S construction =========================================================
def funding_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
               k_terciles: int = DEFAULT_K_TERCILES,
               cost_bps: float = 0.0,
               rebal_days: int = 1) -> pd.Series:
    """Long top-tercile / short bottom-tercile by funding z-score (R46 cadence-aware).

    rebal_days=1 → wraps R45's tercile_ls.
    rebal_days>1 → wraps R46's cadence_ls (rebal every N days, costs only on rebal days).
    """
    if rebal_days == 1:
        return tercile_ls(score_wide, rets, k_terciles=k_terciles, cost_bps=cost_bps)
    return cadence_ls(score_wide, rets, rebal_days=rebal_days,
                      cost_bps=cost_bps, k_terciles=k_terciles)


# === Robustness sweep =========================================================
def funding_cadence_sweep(score_wide: pd.DataFrame, rets: pd.DataFrame,
                          known_arrs: dict,
                          cadences: tuple = DEFAULT_CADENCES,
                          cost_grid: tuple = DEFAULT_COST_GRID,
                          k_terciles: int = DEFAULT_K_TERCILES,
                          label: str = "funding_ls") -> dict:
    """Run cadence × cost grid. Returns nested dict {(cad, bps): result}."""
    out = {}
    for cad in cadences:
        for bps in cost_grid:
            fac = funding_ls(score_wide, rets, k_terciles=k_terciles,
                             cost_bps=bps, rebal_days=cad)
            fac = fac.reindex(rets.index).fillna(0.0)
            r = absorption_test(fac.values, known_arrs,
                                nw_lags=NW_LAGS, periods_per_year=PERIODS_PER_YEAR)
            r["turnover_ann"] = float(estimate_turnover_ann(score_wide, rets, cad))
            r["cadence"] = cad
            r["cost_bps"] = bps
            out[(cad, bps)] = r
    return out


# === Master run ===============================================================
def run(out_dir: Path,
        zwin: int = DEFAULT_ZWIN,
        k_terciles: int = DEFAULT_K_TERCILES,
        sign: str = SIGN_FADE_CROWD,
        cadences: tuple = DEFAULT_CADENCES,
        cost_grid: tuple = DEFAULT_COST_GRID) -> dict:
    """Load → score → L/S → cadence sweep → sub-period → gauntlet → verdict → report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R60 — Funding-crowding L/S per-asset (sign={sign}, zwin={zwin}d, "
          f"k={k_terciles}) ===\n")

    # ── Load core panel (CIS + OHLCV) ────────────────────────────────────────
    cis = load_cis_history_wide()
    rets = load_daily_returns()
    lo = max(cis["date"].min(), rets.index.min())
    hi = min(cis["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable = sorted(set(cis["asset"]) & set(rets.columns))
    print(f"Panel: {lo.date()} → {hi.date()} ({len(rets)} days, {len(tradeable)} assets)")

    # ── Load funding daily ───────────────────────────────────────────────────
    funding_daily = load_funding_daily(assets=tradeable)
    matched_assets = sorted(set(tradeable) & set(funding_daily.columns))
    print(f"Funding daily: {funding_daily.shape[0]} days × {funding_daily.shape[1]} assets "
          f"({len(matched_assets)} matched with tradeable universe)")

    # Trim rets to funding date range
    if not funding_daily.empty:
        f_lo, f_hi = funding_daily.index.min(), funding_daily.index.max()
        rets = rets.loc[(rets.index >= f_lo) & (rets.index <= f_hi)]
    print(f"Aligned panel: {rets.index.min().date()} → {rets.index.max().date()} "
          f"({len(rets)} days, {len(matched_assets)} funding-bearing assets)\n")

    # ── Build score matrix ───────────────────────────────────────────────────
    score = score_funding_zwide(funding_daily[matched_assets], zwin=zwin, sign=sign)
    score = score.reindex(rets.index).ffill()
    coverage = float(score.notna().any(axis=1).mean())
    print(f"Score matrix: {score.shape[0]} days × {score.shape[1]} assets "
          f"({coverage:.0%} days with at least one valid score)")

    # ── Known factors ───────────────────────────────────────────────────────
    f_market = rets[matched_assets].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_arrs = {"market": f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}

    # ── Cadence × cost sweep ─────────────────────────────────────────────────
    print(f"\n══ Cadence × cost sweep ({len(cadences)} cadences × {len(cost_grid)} "
          f"cost grid) ══\n")
    sweep = funding_cadence_sweep(score, rets[matched_assets], known_arrs,
                                  cadences=cadences, cost_grid=cost_grid,
                                  k_terciles=k_terciles, label="funding_ls")
    for cad in cadences:
        for bps in cost_grid:
            r = sweep[(cad, bps)]
            tag = "✓" if r["alpha_significant"] else "✗"
            print(f"  cad={cad:>2}d  bps={bps:>4.1f}  α_t={r['alpha_t']:+.2f}  "
                  f"ann={r['alpha_ann_pct']:+.1f}%  to≈{r['turnover_ann']:.1f}  {tag}")

    # Pick the (cad, bps) winner = max alpha_t at the (R46_REBAL_DAYS, R46_COST_BPS) cell,
    # else max alpha_t across the whole grid (transparent if R46-cell loses).
    target = sweep[(R46_REBAL_DAYS, R46_COST_BPS)]
    best = max(sweep.items(), key=lambda kv: kv[1]["alpha_t"])
    cad_best, bps_best = best[0]
    print(f"\n  R46-cell (5d/5bps): α_t={target['alpha_t']:+.2f}")
    print(f"  Best grid cell ({cad_best}d/{bps_best:.0f}bps): α_t={best[1]['alpha_t']:+.2f}")

    # ── 3-check gauntlet on R46 cell + best cell ────────────────────────────
    fac_r46 = funding_ls(score, rets[matched_assets], k_terciles=k_terciles,
                         cost_bps=R46_COST_BPS, rebal_days=R46_REBAL_DAYS)
    fac_r46 = fac_r46.reindex(rets.index).fillna(0.0)
    # OOS is the last OOS_FRAC of the panel; cut at the 70% boundary.
    cut = int(len(rets) * (1.0 - OOS_FRAC))
    g_r46 = gauntlet_3check(fac_r46.values, known_arrs, cut)

    fac_best = funding_ls(score, rets[matched_assets], k_terciles=k_terciles,
                          cost_bps=bps_best, rebal_days=cad_best)
    fac_best = fac_best.reindex(rets.index).fillna(0.0)
    g_best = gauntlet_3check(fac_best.values, known_arrs, cut)

    # ── Sub-period OOS (6 fixed-width windows) ──────────────────────────────
    print(f"\n══ Sub-period OOS (6 fixed-width windows, cadence={cad_best}d, "
          f"cost={bps_best:.0f}bps) ══\n")
    periods = quarter_cuts(rets.index.min(), rets.index.max(), n_windows=6)
    sub_r46 = sub_period_absorption(fac_r46, known_arrs, periods)
    sub_best = sub_period_absorption(fac_best, known_arrs, periods)
    for i, (label, s, e) in enumerate(periods):
        r46_t = sub_r46[i].get("alpha_t", float("nan"))
        bst_t = sub_best[i].get("alpha_t", float("nan"))
        print(f"  {label} ({s.date()}→{e.date()})  n={sub_r46[i].get('n','?')}  "
              f"R46 5d/5bps α_t={r46_t:+.2f}  best {cad_best}d/{bps_best:.0f}bps α_t={bst_t:+.2f}")

    # ── Per-window P&L (annualized) for the two candidate factors ────────────
    def per_window(fac):
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

    pw_r46 = per_window(fac_r46)
    pw_best = per_window(fac_best)

    # ── Save + emit report ───────────────────────────────────────────────────
    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets": int(len(tradeable)),
                  "funding_matched_assets": len(matched_assets),
                  "matched_assets": matched_assets},
        "construction": {"zwin": zwin, "k_terciles": k_terciles, "sign": sign,
                         "cadences": list(cadences), "cost_grid": list(cost_grid)},
        "score_coverage_pct": coverage * 100,
        "sweep": {f"{c}_{int(b)}": v for (c, b), v in sweep.items()},
        "r46_cell": {
            "cadence": R46_REBAL_DAYS, "cost_bps": R46_COST_BPS,
            "gauntlet": g_r46,
            "sub_period_alpha_t": [r.get("alpha_t", None) for r in sub_r46],
            "per_window": pw_r46,
        },
        "best_cell": {
            "cadence": cad_best, "cost_bps": bps_best,
            "gauntlet": g_best,
            "sub_period_alpha_t": [r.get("alpha_t", None) for r in sub_best],
            "per_window": pw_best,
        },
        "r46_benchmark": {
            "pillar_O_5d_5bps_alpha_t_gross": 2.57,
            "pillar_O_5d_5bps_alpha_t_costed": 3.33,
            "pillar_O_5d_5bps_OOS_alpha_t": -0.31,
        },
        "w5_window": {"label": "W5", "lo": str(periods[4][1].date()),
                      "hi": str(periods[4][2].date())},
    }
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    report = format_report(out)
    (out_dir / "REPORT.md").write_text(report)
    print(report)
    print(f"\nSaved: {out_dir/'verdict.json'} + {out_dir/'REPORT.md'}")
    return out


def format_report(out: dict) -> str:
    L = []
    L.append("# R60 — Funding-Crowding L/S Per-Asset — REPORT\n")
    panel = out["panel"]
    L.append(f"**Panel:** {panel['lo']} → {panel['hi']}  ·  "
             f"**{panel['n_days']} days × {panel['funding_matched_assets']} funding-bearing assets** "
             f"(out of {panel['n_assets']} CIS ∩ OHLCV tradeable)")
    cn = out["construction"]
    L.append(f"\n**Construction:** funding_z(zwin={cn['zwin']}d) → "
             f"{cn['sign']} sign → long-top/short-bottom k={cn['k_terciles']}, "
             f"cadences {cn['cadences']}, cost grid {cn['cost_grid']} bps")
    L.append(f"\n**Score coverage:** {out['score_coverage_pct']:.0f}% of days have ≥1 valid score")
    L.append(f"\n**Matched funding ∩ CIS assets:** "
             f"`{', '.join(panel['matched_assets'])}`\n")

    # Cadence × cost grid
    L.append("## Cadence × cost grid (residual-α t after {market, momentum})\n")
    L.append("`t` = Newey-West HAC t-stat. **Bold** = clears t > 1.96. `to` = annualized turnover.\n")
    cads = cn["cadences"]
    costs = cn["cost_grid"]
    L.append("| rebal (d) | " + " | ".join(f"{b:.0f} bps" for b in costs) + " | first-clear-at-5bps |")
    L.append("|--:|" + "|".join([":--:"] * len(costs)) + "|--:|")
    for cad in cads:
        ts = []
        for bps in costs:
            r = out["sweep"][f"{cad}_{int(bps)}"]
            t_str = f"**{r['alpha_t']:+.2f}**" if r["alpha_significant"] else f"{r['alpha_t']:+.2f}"
            ts.append(t_str)
        first_clear = "—"
        for c2 in cads:
            r = out["sweep"][f"{c2}_5"]
            if r["alpha_significant"]:
                first_clear = f"**{c2}d** (t={r['alpha_t']:+.2f})"
                break
        L.append(f"| {cad} | " + " | ".join(ts) + f" | {first_clear} |")

    # 3-check gauntlet
    g_r46 = out["r46_cell"]["gauntlet"]
    g_best = out["best_cell"]["gauntlet"]
    L.append("\n## 3-check gauntlet (R46 cell vs best cell)\n")
    L.append("| config | gross_t | 5bps_t | OOS_t | pass_gross | pass_5bps | pass_OOS | pass_all |")
    L.append("|---|--:|--:|--:|:--:|:--:|:--:|:--:|")
    L.append(f"| R46 cell (5d/5bps) | {g_r46['gross_t']:+.2f} | (5bps charged in series) | "
             f"{g_r46['oos_t']:+.2f} | "
             f"{'✓' if g_r46['passes_gross'] else '✗'} | n/a (costed) | "
             f"{'✓' if g_r46['passes_oos'] else '✗'} | n/a |")
    L.append(f"| best cell ({out['best_cell']['cadence']}d/{out['best_cell']['cost_bps']:.0f}bps) | "
             f"{g_best['gross_t']:+.2f} | (costed in series) | "
             f"{g_best['oos_t']:+.2f} | "
             f"{'✓' if g_best['passes_gross'] else '✗'} | n/a | "
             f"{'✓' if g_best['passes_oos'] else '✗'} | n/a |")

    # Per-window P&L (best cell)
    L.append("\n## Per-window P&L (best cell)\n")
    L.append("Annualized return % per fixed-width window. n = days in window.\n")
    L.append("| Window | dates | n | ann% | Sharpe |")
    L.append("|--:|---|--:|--:|--:|")
    period_labels = list(out["r46_cell"]["per_window"].keys())
    # Reconstruct dates from sub_period
    # We didn't store dates in the json (sweep dates would help); just show label+n
    for i, label in enumerate(period_labels):
        d = out["best_cell"]["per_window"][label]
        L.append(f"| {label} | (W{i+1}) | {d['n_days']} | {d['ann_pct']:+.1f} | "
                 f"{d['sharpe']:+.2f} |")

    # R46 baseline reference
    rb = out["r46_benchmark"]
    L.append("\n## Reference (R46 pillar_O 5d/5bps baseline)\n")
    L.append(f"- gross α_t = {rb['pillar_O_5d_5bps_alpha_t_gross']:+.2f}")
    L.append(f"- 5bps α_t = {rb['pillar_O_5d_5bps_alpha_t_costed']:+.2f}")
    L.append(f"- OOS α_t = {rb['pillar_O_5d_5bps_OOS_alpha_t']:+.2f}")

    # Verdict
    L.append("\n## Verdict\n")
    if g_best["passes_gross"] and g_best["oos_t"] > 1.0:
        verdict = "✅ SURVIVES"
        if g_best["passes_oos"]:
            verdict = "✅ SURVIVES — clears full 3-check gauntlet"
        else:
            verdict = "🟡 PARTIAL — clears gross but OOS sub-threshold"
    else:
        verdict = "🔴 REFUTED — fails 2+ checks"
    L.append(f"**{verdict}**")
    L.append(f"- R60 best cell ({out['best_cell']['cadence']}d/{out['best_cell']['cost_bps']:.0f}bps): "
             f"gross_t={g_best['gross_t']:+.2f}, OOS_t={g_best['oos_t']:+.2f}")
    L.append(f"- R60 R46-cell parity (5d/5bps): gross_t={g_r46['gross_t']:+.2f}, "
             f"OOS_t={g_r46['oos_t']:+.2f}")
    L.append(f"- R46 pillar_O baseline (5d/5bps): gross_t={rb['pillar_O_5d_5bps_alpha_t_costed']:+.2f}, "
             f"OOS_t={rb['pillar_O_5d_5bps_OOS_alpha_t']:+.2f}")

    # W5 attribution
    w5 = out["w5_window"]
    w5_r46 = out["r46_cell"]["sub_period_alpha_t"]
    w5_best = out["best_cell"]["sub_period_alpha_t"]
    L.append(f"\n## W5 attribution ({w5['label']}: {w5['lo']} → {w5['hi']})\n")
    L.append(f"- R60 R46-cell: W5 α_t = {w5_r46[4]:+.2f}")
    L.append(f"- R60 best cell: W5 α_t = {w5_best[4]:+.2f}")
    L.append("- Note: W5 is the regime-flip window that R52/R56/R58/R59 all attempted to fix. "
             "If W5 sign-flips more than −2/yr on R60 best cell, R60 is fragile in the same way R46 was.")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--zwin", type=int, default=DEFAULT_ZWIN)
    ap.add_argument("--k-terciles", type=int, default=DEFAULT_K_TERCILES)
    ap.add_argument("--sign", choices=[SIGN_FADE_CROWD, SIGN_RIDE_CROWD],
                    default=SIGN_FADE_CROWD)
    args = ap.parse_args()
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = args.out_dir or Path(f"reports/funding_crowding_ls/{today}")
    run(out_dir, zwin=args.zwin, k_terciles=args.k_terciles, sign=args.sign)
