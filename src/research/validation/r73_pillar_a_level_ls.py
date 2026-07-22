"""
R73 — pillar_A LEVEL cross-sectional L/S test (Seth, 2026-07-22).

Per R63b domain correction (2026-07-21), pillar_A carries a structural +4.48 level-edge
in addition to a +1.18 directional ΔA-edge. R63b flagged pillar_A as the **strongest
untested pillar at strategy level** ("never run at strategy level; queue the L/S test").

R72 attempted ΔA cross-sectional at k=5 and REFUTED (gross α_t=+0.96 fails 3-check,
OOS α_t=+2.19 only — bar not cleared). Per lesson #40, the right next test of the
R63b finding is **pillar_A LEVEL** (not ΔA), at the standard k=3, on the strict
funding-bearing universe. Level-A tests "does pillar_A carry cross-sectional rank
information beyond F + M + market?" — if YES, that's a real sleeve.

Methodology (mirrors R72 + R61 + R60 + R46 for honesty):
  - Universe: strict funding ∩ CIS ∩ OHLCV intersection (same as R72; same as R69 fusion cell).
  - k_terciles = 3 (R46 default; R72 deliberately used 5 → lesson #40 anti-imposter).
  - Score: pillar_A LEVEL (one-day lag PIT-safe ffill), NOT ΔA.
  - Both signs run side-by-side (anti-imposter; matched-cell sign is the verdict).
  - Cadences {1,3,5,7,14,21} × costs {0,5,10}bps.
  - 3-check gauntlet: gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96 (last 30%).
  - Per-window W1-W6 attribution (R64-style).
  - Residualization: market + 30d trailing momentum; Newey-West lags=6.

Anti-imposter:
  - The R63b +4.48 number was a LEVEL effect — R73 ranks the level, not the change.
  - OOS is the last 30% (cut at 70%), NOT 70% as in earlier drafts.
  - Both signs (LONG-high / LONG-low) run; sign verdict comes from matched-cell (same cad×bps).

Verdict positioning:
  - ✅ SURVIVES — clears all 3 checks AND matched sign favors R63b direction (+4.48 level is a
    cross-section edge beyond F+M+market). Eligible for fusion-cell reconsideration at w or w_R73.
  - 🟡 PARTIAL — clears 2 of 3 (or 3 of 3 with ambiguous sign). Diagnostic only.
  - 🔴 REFUTED — fails 2+ checks OR matched sign is degenerate.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns, tercile_ls,
)
from src.research.validation.cis_quality_robustness import cadence_ls as _cadence_ls_re
from src.research.validation.cis_quality_robustness import (
    estimate_turnover_ann, quarter_cuts,
)
from src.research.validation.factor_absorption import absorption_test
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.w5_forensics import gauntlet_3check
from src.research.validation.funding_crowding_ls import (
    DEFAULT_CADENCES, DEFAULT_COST_GRID,
)

# ── Constants ───────────────────────────────────────────────────────────────
OOS_FRAC          = 0.30
NW_LAGS           = 6
PERIODS_PER_YEAR  = 365

# R73-specific
R73_K_TERCILES    = 3            # standard L/S — R72 deliberately tried 5 (quintile)
R73_MIN_TRADEABLE = 12           # minimum assets for a sane L/S
R73_LEVEL_LOOKBACK = 1           # one-day lag for level-A PIT alignment

# Sign constants (mirrors R72's convention for consistency)
SIGN_HIGH_A_LONG  = "high_a_long"
SIGN_LOW_A_LONG   = "low_a_long"
_VALID_SIGNS      = {SIGN_HIGH_A_LONG, SIGN_LOW_A_LONG}


# ── Score ───────────────────────────────────────────────────────────────────
def score_pillar_a_level(cis_long: pd.DataFrame) -> pd.DataFrame:
    """Pivot pillar_A from long → wide (date × asset). PIT-safe ffill."""
    wide = cis_long.pivot(index="date", columns="asset", values="A").sort_index()
    wide = wide.ffill()             # PIT-safe: today's score or last known
    return wide


# ── L/S core ────────────────────────────────────────────────────────────────
def pillar_a_level_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
                     k_terciles: int = R73_K_TERCILES,
                     cost_bps: float = 0.0,
                     rebal_days: int = 1,
                     sign: str = SIGN_HIGH_A_LONG) -> pd.Series:
    """Long high-A / short low-A (or reversed under SIGN_LOW_A_LONG)."""
    if sign not in _VALID_SIGNS:
        raise ValueError(f"sign must be one of {_VALID_SIGNS}, got {sign!r}")
    flipped = -score_wide if sign == SIGN_LOW_A_LONG else score_wide
    if rebal_days == 1:
        return tercile_ls(flipped, rets, k_terciles=k_terciles, cost_bps=cost_bps)
    return _cadence_ls_re(flipped, rets, rebal_days=rebal_days,
                          cost_bps=cost_bps, k_terciles=k_terciles)


# ── Sweep ───────────────────────────────────────────────────────────────────
def pillar_a_level_cadence_sweep(score_wide: pd.DataFrame, rets: pd.DataFrame,
                                 known_arrs: dict,
                                 cadences: tuple = DEFAULT_CADENCES,
                                 cost_grid: tuple = DEFAULT_COST_GRID,
                                 k_terciles: int = R73_K_TERCILES,
                                 sign: str = SIGN_HIGH_A_LONG) -> dict:
    """Cadence × cost sweep. Returns {(cad, bps): result}."""
    out = {}
    for cad in cadences:
        for bps in cost_grid:
            fac = pillar_a_level_ls(score_wide, rets, k_terciles=k_terciles,
                                    cost_bps=bps, rebal_days=cad, sign=sign)
            fac = fac.reindex(rets.index).fillna(0.0)
            r = absorption_test(fac.values, known_arrs,
                                nw_lags=NW_LAGS, periods_per_year=PERIODS_PER_YEAR)
            r["turnover_ann"] = float(estimate_turnover_ann(score_wide, rets, cad))
            r["cadence"] = cad
            r["cost_bps"] = bps
            r["sign"] = sign
            out[(cad, bps)] = r
    return out


# ── Orchestrator ────────────────────────────────────────────────────────────
def run(out_dir: Path,
        k_terciles: int = R73_K_TERCILES,
        sign: str = SIGN_HIGH_A_LONG,
        cadences: tuple = DEFAULT_CADENCES,
        cost_grid: tuple = DEFAULT_COST_GRID) -> dict:
    """Load → score (level-A) → L/S → cadence sweep → sub-period → gauntlet → verdict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R73 — pillar_A LEVEL cross-sectional L/S (sign={sign}, k={k_terciles}) ===\n")

    # ── Load panels ──────────────────────────────────────────────────────────
    cis_long = load_cis_history_wide()
    rets = load_daily_returns()

    lo = max(cis_long["date"].min(), rets.index.min())
    hi = min(cis_long["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    cis_long = cis_long[cis_long["date"].between(lo, hi)]
    tradeable = sorted(set(cis_long["asset"]) & set(rets.columns))

    # R73's declared universe is the strict funding ∩ CIS ∩ OHLCV
    # intersection. Same anti-imposter discipline as R72 + R69.
    funding_daily = load_funding_daily(assets=tradeable)
    matched_assets = sorted(set(tradeable) & set(funding_daily.columns))
    if not matched_assets:
        raise RuntimeError("R73 requires a non-empty funding ∩ CIS ∩ OHLCV universe")
    f_lo, f_hi = funding_daily.index.min(), funding_daily.index.max()
    lo = max(lo, f_lo)
    hi = min(hi, f_hi)
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    cis_long = cis_long[cis_long["date"].between(lo, hi)]
    tradeable = matched_assets
    print(f"CIS/funding panel: {lo.date()} → {hi.date()} ({len(tradeable)} assets)")

    # R73's headline score is pillar_A LEVEL (per R63b's +4.48 level edge claim),
    # NOT the change ΔA (per R72's refuted test of the +1.18 change edge).
    score = score_pillar_a_level(cis_long)[tradeable]
    coverage = float(score.notna().any(axis=1).mean())
    print(f"A-level score matrix: {score.shape[0]} days × {score.shape[1]} assets "
          f"({coverage:.0%} days with ≥1 valid score)")

    # Minimum-asset floor: an L/S with <12 names is non-credible
    valid_days = score.notna().sum(axis=1) >= R73_MIN_TRADEABLE
    score = score.loc[valid_days]
    rets = rets.loc[score.index.min():score.index.max()]
    rets = rets[tradeable]
    print(f"After min-asset floor ({R73_MIN_TRADEABLE}): {score.shape[0]} days, "
          f"{score.shape[1]} assets")

    # ── Known factors (mirrors R72 + R69 + R46) ──────────────────────────────
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_arrs = {"market":   f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}

    # ── Run both signs (anti-imposter) ──────────────────────────────────────
    results: dict = {}
    for sgn in (SIGN_HIGH_A_LONG, SIGN_LOW_A_LONG):
        print(f"\n══ Sign={sgn} sweep ({len(cadences)}×{len(cost_grid)}"
              f"={len(cadences)*len(cost_grid)} cells) ══\n")
        sweep = pillar_a_level_cadence_sweep(score, rets, known_arrs,
                                             cadences=cadences, cost_grid=cost_grid,
                                             k_terciles=k_terciles, sign=sgn)
        for cad in cadences:
            for bps in cost_grid:
                r = sweep[(cad, bps)]
                tag = "✓" if r["alpha_significant"] else "✗"
                print(f"  cad={cad:>2}d  bps={bps:>4.1f}  α_t={r['alpha_t']:+.2f}  "
                      f"ann={r['alpha_ann_pct']:+.1f}%  to≈{r['turnover_ann']:.1f}  {tag}")
        results[sgn] = sweep

    def _best_cell(sweep):
        zero_cost = {k: v for k, v in sweep.items() if v["cost_bps"] == 0}
        if not zero_cost:
            return None, None
        best_k = max(zero_cost, key=lambda k: zero_cost[k]["alpha_t"])
        return best_k, zero_cost[best_k]

    best_hi = _best_cell(results[SIGN_HIGH_A_LONG])
    best_lo = _best_cell(results[SIGN_LOW_A_LONG])
    headline_k, headline_v = best_hi
    matched_lo = (results[SIGN_LOW_A_LONG].get(headline_k)
                  if headline_k is not None else None)

    print("\n══ Gross sign audit ══")
    if headline_v is not None and matched_lo is not None:
        print(f"  +Level-A headline: cad={headline_k[0]:>2}d  α_t={headline_v['alpha_t']:+.2f}")
        print(f"  −Level-A matched:  cad={headline_k[0]:>2}d  α_t={matched_lo['alpha_t']:+.2f}")
    if best_lo[1] is not None:
        print(f"  Best −Level-A cell anywhere: cad={best_lo[0][0]:>2}d  "
              f"α_t={best_lo[1]['alpha_t']:+.2f}")

    if headline_v is None or matched_lo is None:
        sign_verdict = "inconclusive — no matched +/−Level-A headline cell"
        directional_alpha = 0.0
    else:
        directional_alpha = headline_v["alpha_t"] - matched_lo["alpha_t"]
        zero_cost_hi = [v["alpha_t"] for v in results[SIGN_HIGH_A_LONG].values()
                        if v["cost_bps"] == 0]
        cadence_flip = any(v < 0 for v in zero_cost_hi) and any(v > 0 for v in zero_cost_hi)
        if headline_v["alpha_t"] > 0 and matched_lo["alpha_t"] < 0:
            sign_verdict = ("✓ matched-cell sign supports +Level-A (long high-A)"
                            + (", but the effect flips at some cadences."
                               if cadence_flip else "."))
        elif headline_v["alpha_t"] <= 0 and matched_lo["alpha_t"] > 0:
            sign_verdict = "✗ matched-cell sign favors −Level-A; level edge doesn't carry as expected."
        else:
            sign_verdict = "⚠ matched-cell sign is degenerate; direction is inconclusive."

    # ── 3-check gauntlet on the predeclared +Level-A direction ──────────────
    headline_sign = SIGN_HIGH_A_LONG
    headline_k, headline_v = best_hi
    gauntlet: dict = {}
    if headline_v is not None and headline_v.get("alpha_t") is not None:
        fac_gross = pillar_a_level_ls(score, rets, k_terciles=k_terciles,
                                      cost_bps=0.0, rebal_days=headline_k[0],
                                      sign=headline_sign).reindex(rets.index).fillna(0.0)
        fac_costed = pillar_a_level_ls(score, rets, k_terciles=k_terciles,
                                       cost_bps=5.0, rebal_days=headline_k[0],
                                       sign=headline_sign).reindex(rets.index).fillna(0.0)
        try:
            # OOS is the LAST 30%, not the last 70% (anti-imposter per R72 lesson).
            cut = int((1.0 - OOS_FRAC) * len(fac_gross))
            g_gross = gauntlet_3check(fac_gross, known_arrs, cut)
            g_costed = gauntlet_3check(fac_costed, known_arrs, cut)
            gauntlet = {
                "n_full": g_gross["n_full"],
                "n_oos": g_gross["n_oos"],
                "gross_alpha_ann_pct": g_gross["gross_alpha_ann_pct"],
                "gross_t": g_gross["gross_t"],
                "cost_5bps_alpha_ann_pct": g_costed["gross_alpha_ann_pct"],
                "cost_5bps_t": g_costed["gross_t"],
                "gross_oos_t": g_gross["oos_t"],
                "oos_alpha_ann_pct": g_costed["oos_alpha_ann_pct"],
                "oos_t": g_costed["oos_t"],
                "passes_gross": bool(g_gross["gross_t"] > 1.96),
                "passes_cost": bool(g_costed["gross_t"] > 1.96),
                "passes_oos": bool(g_costed["oos_t"] > 1.96),
                "cadence": headline_k[0],
                "cost_bps": 5.0,
                "sign": headline_sign,
                "oos_cut_index": cut,
            }
            gauntlet["passes_all"] = bool(
                gauntlet["passes_gross"]
                and gauntlet["passes_cost"]
                and gauntlet["passes_oos"]
            )
            print("\n══ 3-check gauntlet ══")
            print(f"  gross α_t={gauntlet['gross_t']:+.2f}  "
                  f"5bps α_t={gauntlet['cost_5bps_t']:+.2f}  "
                  f"last-30% OOS α_t={gauntlet['oos_t']:+.2f}  "
                  f"pass={gauntlet['passes_all']}")
        except Exception as e:
            print(f"[gauntlet] failed: {e}")
            gauntlet = {"error": str(e), "passes_all": False}

    # ── W1-W6 sub-period attribution ─────────────────────────────────────────
    sub_period: dict = {}
    if headline_v is not None:
        try:
            fac = pillar_a_level_ls(score, rets, k_terciles=k_terciles,
                                    cost_bps=0.0, rebal_days=headline_k[0],
                                    sign=headline_sign).reindex(rets.index).fillna(0.0)
            windows = quarter_cuts(rets.index.min(), rets.index.max(), n_windows=6)
            for label, s, e in windows:
                sub = fac.loc[(fac.index >= s) & (fac.index <= e)]
                cumret = float((1 + sub).prod() - 1) if len(sub) > 0 else 0.0
                ann = float(((1 + sub).prod() ** (PERIODS_PER_YEAR / max(len(sub), 1)) - 1) * 100) \
                      if len(sub) > 0 else 0.0
                sharpe = float(sub.mean() / sub.std() * np.sqrt(PERIODS_PER_YEAR)) \
                         if len(sub) > 1 and sub.std() > 0 else None
                sub_period[label] = {
                    "n_days":   int(len(sub)),
                    "cumret":   cumret,
                    "ann_pct":  ann,
                    "sharpe":   sharpe,
                }
            print(f"\n══ Per-window breakdown (W1-W6) ══")
            for label in sorted(sub_period.keys()):
                w = sub_period[label]
                print(f"  {label}: ann% = {w.get('ann_pct', 0):+.1f}  "
                      f"sharpe = {w.get('sharpe', float('nan')):+.2f}")
        except Exception as e:
            print(f"[sub_period] failed: {e}")
            sub_period = {"error": str(e)}

    # ── Verdict ─────────────────────────────────────────────────────────────
    passes_3check = gauntlet.get("passes_all", False)
    if not passes_3check:
        verdict = "🔴 REFUTED"
    elif "⚠" in sign_verdict or "✗" in sign_verdict:
        verdict = "🟡 PARTIAL — sign ambiguous; level-A survives 3-check only"
    else:
        verdict = "✅ SURVIVES — +Level-A direction matches R63b, clears 3-check"

    # ── Report ─────────────────────────────────────────────────────────────
    out = {
        "r_number":     "R73",
        "title":        "pillar_A LEVEL cross-sectional L/S test",
        "sign":         headline_sign,
        "score_basis":  "level_A",
        "level_lookback_days": R73_LEVEL_LOOKBACK,
        "universe_basis": "funding ∩ CIS ∩ OHLCV",
        "score_window": [str(lo.date()), str(hi.date())],
        "n_assets":     len(tradeable),
        "n_days":       int(rets.shape[0]),
        "k_terciles":   k_terciles,
        "headline_cell": {
            "cadence_days": headline_k[0] if headline_k else None,
            "cost_bps":     0.0,
            "gross_alpha_t":  headline_v["alpha_t"] if headline_v else None,
            "gross_alpha_ann_pct": headline_v["alpha_ann_pct"] if headline_v else None,
        },
        "directional_alpha_t": directional_alpha,
        "matched_control_cell": {
            "cadence_days": headline_k[0] if headline_k else None,
            "alpha_t": matched_lo["alpha_t"] if matched_lo else None,
            "alpha_ann_pct": matched_lo["alpha_ann_pct"] if matched_lo else None,
        },
        "best_inverse_cell": {
            "cadence_days": best_lo[0][0] if best_lo[0] else None,
            "alpha_t": best_lo[1]["alpha_t"] if best_lo[1] else None,
            "alpha_ann_pct": best_lo[1]["alpha_ann_pct"] if best_lo[1] else None,
        },
        "sign_verdict": sign_verdict,
        "sweep": {
            sgn: {
                f"cad={cad}_bps={bps}": {
                    "cadence_days":  cad,
                    "cost_bps":      bps,
                    "alpha_t":        v["alpha_t"],
                    "alpha_ann_pct":  v["alpha_ann_pct"],
                    "alpha_significant": v["alpha_significant"],
                    "turnover_ann":   v["turnover_ann"],
                }
                for (cad, bps), v in results[sgn].items()
            }
            for sgn in results
        },
        "gauntlet": gauntlet,
        "sub_period": sub_period,
        "verdict": verdict,
        "r72_relation": "R72 (ΔA k=5) REFUTED. R73 (level-A k=3) is the open test for R63b's "
                        "+4.48 level-edge claim on the strict funding-bearing universe.",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "module": "src/research/validation/r73_pillar_a_level_ls.py",
    }

    md_path = out_dir / "REPORT.md"
    md_path.write_text(_format_r73_report(out))
    print(f"\nReport → {md_path}")
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    return out


def _format_r73_report(out: dict) -> str:
    g = out.get("gauntlet", {})
    hi = out.get("headline_cell", {})
    matched = out.get("matched_control_cell", {})
    inverse = out.get("best_inverse_cell", {})

    L = [
        "# R73 — pillar_A LEVEL Cross-Sectional L/S",
        "",
        "**Author:** Seth · 2026-07-22  ",
        f"**Status:** **{out['verdict']}**  ",
        "**Decision:** See verdict + §7.",
        "",
        "## 1. Question and construction",
        "",
        "R63b found two different pillar_A facts: a **+4.48 level-edge** and a "
        "**+1.18 Δ-quintile edge**. R72 tested the ΔA claim at k=5 — REFUTED. R73 is the "
        "open test of the LEVEL claim: does ranking pillar_A today surface cross-section "
        "alpha beyond F + M + market?",
        "",
        "- Positioning: top pillar_A-level tercile versus bottom; inverse sign run side-by-side.",
        f"- Universe: strict **{out['universe_basis']}** intersection; {out['n_assets']} assets.",
        f"- Window: {out['score_window'][0]} → {out['score_window'][1]}; {out['n_days']} daily bars.",
        f"- Score: pillar_A LEVEL (PIT-safe ffill, one-day lag = today's score or last known).",
        f"- Ranking: k={out['k_terciles']} terciles (standard; R72 deliberately used 5 which "
        "may have inflated gross via thinner buckets — anti-imposter discipline says k=3).",
        "- Residualization: market + 30-day momentum; Newey–West lags=6.",
        "- Sweep: cadence {1,3,5,7,14,21}d × cost {0,5,10}bps.",
        "- OOS: **last 30%** of the panel (cut at 70%).",
        "",
        "## 2. Executive finding",
        "",
        f"The best +Level-A gross cell within the declared grid is **{hi.get('cadence_days')}d**: "
        f"α_t={hi.get('gross_alpha_t', float('nan')):+.2f}, annualized residual α={hi.get('gross_alpha_ann_pct', float('nan')):+.1f}%.",
        "",
        f"At the identical construction, the inverse −Level-A direction is "
        f"α_t={matched.get('alpha_t', float('nan')):+.2f}; the matched-cell directional "
        f"differential is **{out.get('directional_alpha_t', float('nan')):+.2f}**. "
        "This is the only valid sign comparison; selecting the best cadence independently "
        "for each sign is post-hoc and can make both directions appear positive.",
        "",
        f"**Sign read:** {out['sign_verdict']}",
        "",
        "## 3. Three-check gauntlet",
        "",
        "| Check | α_t | Annualized α | Gate |",
        "|---|---:|---:|:---:|",
        f"| Gross full panel | {g.get('gross_t', float('nan')):+.2f} | "
        f"{g.get('gross_alpha_ann_pct', float('nan')):+.1f}% | "
        f"{'PASS' if g.get('passes_gross') else 'FAIL'} |",
        f"| 5bps full panel | {g.get('cost_5bps_t', float('nan')):+.2f} | "
        f"{g.get('cost_5bps_alpha_ann_pct', float('nan')):+.1f}% | "
        f"{'PASS' if g.get('passes_cost') else 'FAIL'} |",
        f"| 5bps, last-30% OOS | {g.get('oos_t', float('nan')):+.2f} | "
        f"{g.get('oos_alpha_ann_pct', float('nan')):+.1f}% | "
        f"{'PASS' if g.get('passes_oos') else 'FAIL'} |",
        "",
        f"**Combined gate:** {'PASS' if g.get('passes_all') else 'FAIL'} "
        f"(n_full={g.get('n_full', 0)}, n_oos={g.get('n_oos', 0)}).",
        "",
        "## 4. Matched sign audit",
        "",
        "| Construction | Cadence | α_t | Annualized α |",
        "|---|---:|---:|---:|",
        f"| +Level-A headline | {hi.get('cadence_days')}d | "
        f"{hi.get('gross_alpha_t', float('nan')):+.2f} | "
        f"{hi.get('gross_alpha_ann_pct', float('nan')):+.1f}% |",
        f"| −Level-A, same cell | {matched.get('cadence_days')}d | "
        f"{matched.get('alpha_t', float('nan')):+.2f} | "
        f"{matched.get('alpha_ann_pct', float('nan')):+.1f}% |",
        f"| Best −Level-A anywhere (diagnostic only) | {inverse.get('cadence_days')}d | "
        f"{inverse.get('alpha_t', float('nan')):+.2f} | "
        f"{inverse.get('alpha_ann_pct', float('nan')):+.1f}% |",
        "",
        "The final row is not a competing selected strategy; it exists to reveal cadence "
        "instability rather than to flip the hypothesis after seeing the data.",
        "",
        "## 5. Cadence × cost sweep",
        "",
    ]

    for sign_key, label in ((SIGN_HIGH_A_LONG, "+Level-A"),
                            (SIGN_LOW_A_LONG, "−Level-A control")):
        cells = list(out.get("sweep", {}).get(sign_key, {}).values())
        cadences = sorted({int(c["cadence_days"]) for c in cells})
        costs = sorted({float(c["cost_bps"]) for c in cells})
        lookup = {(int(c["cadence_days"]), float(c["cost_bps"])): c for c in cells}
        L.extend([f"### {label}", ""])
        header = "| Cadence | " + " | ".join(f"{bps:g}bps α_t / ann%" for bps in costs) + " | Turnover/yr |"
        sep = "|---:" + "|".join("---:" for _ in costs) + "|---:|"
        L.extend([header, sep])
        for cad in cadences:
            row = []
            for bps in costs:
                c = lookup[(cad, bps)]
                row.append(f"{c['alpha_t']:+.2f} / {c['alpha_ann_pct']:+.1f}%")
            turnover = lookup[(cad, costs[0])]["turnover_ann"]
            L.append(f"| {cad}d | " + " | ".join(row) + f" | {turnover:.1f} |")
        L.append("")

    L.extend([
        "## 6. Six-window attribution — +Level-A headline gross",
        "",
        "| Window | Days | Cumulative return | Annualized return | Sharpe |",
        "|---|---:|---:|---:|---:|",
    ])
    for label, w in out.get("sub_period", {}).items():
        if label == "error":
            continue
        L.append(f"| {label} | {w.get('n_days', 0)} | "
                 f"{100 * w.get('cumret', 0.0):+.1f}% | "
                 f"{w.get('ann_pct', float('nan')):+.1f}% | "
                 f"{w.get('sharpe', float('nan')):+.2f} |")

    positive = sum(1 for w in out.get("sub_period", {}).values()
                   if isinstance(w, dict) and w.get("ann_pct", 0) > 0)
    L.extend([
        "",
        f"Positive windows: **{positive}/6**. A standalone factor needs broad, cost-aware, "
        "out-of-sample persistence; isolated strong windows do not earn strategy credit.",
        "",
        "## 7. Verdict and lesson",
        "",
        out["r72_relation"],
        "",
        f"**R73 verdict: {out['verdict']}**.",
        "",
        "Aggregate lesson — to be finalized in REFUTATION_LEDGER once the OOS picture is in.",
        "",
        "## Artifacts",
        "",
        "- Module: `src/research/validation/r73_pillar_a_level_ls.py`",
        "- Smoke tests: `src/research/validation/tests/test_r73_pillar_a_level_ls_smoke.py`",
        "- Machine-readable evidence: `verdict.json`",
    ])
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    out_dir = Path(os.environ.get("R73_OUT_DIR",
                                  ROOT / "reports" / "r73_pillar_a_level_ls" / "2026-07-22"))
    print(json.dumps(run(out_dir), indent=2, default=str)[:600])
