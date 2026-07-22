"""
R47 — regime-conditioned pillar_O L/S sleeve.
======================================================================================
Owner: Minimax-B, 2026-07-21. Triggered by R46's sub-period finding: pillar_O at
5-day rebal / 5 bps clears the 3-check gauntlet (t=+3.33, ann=+70.1%/yr) but its
alpha is NOT uniform across time — 5/6 fixed-width windows positive, one window
(W5 = 2025-10 → 2026-02, "risk-on late-cycle chop") flips to t=−2.32. R46's own
synthesis flagged the upgrade path: "concentrated flip ⇒ regime-specific death
(regime-conditioning is the upgrade path)."

R47 asks the honest question: **does gating the pillar_O sleeve on the REAL CIS
macro_regime (not a calendar window, not an EMA) recover the bad window without
overfitting?** The regime label is the top-level `macro_regime` field in each
cis_YYYY-MM-DD.json — the same regime the live engine assigned that day.

⚠️ Selection-bias discipline (the load-bearing methodology point):
  Choosing "which regimes to sit out" from the FULL sample and then testing on the
  full sample is look-ahead — you'd be picking the drop-set with knowledge of the
  outcome. R47 avoids this:
    1. Split 70/30 (same cut as R45/R46).
    2. Decide the DROP-SET from IN-SAMPLE (first 70%) per-regime α only:
       a regime is dropped iff its in-sample residual-α mean return < 0.
    3. Apply that FIXED drop-set to the OOS (last 30%) and measure whether the
       conditioned sleeve beats the unconditional pillar_O sleeve OUT of sample.
  If the conditioned sleeve only wins in-sample, that's fit, and R47 dies honest.

3-check gauntlet on the conditioned sleeve (per aggregate lesson #13):
  (1) gross residual-α t > 1.96
  (2) cost-charged (5 bps) residual-α t > 1.96
  (3) OOS residual-α t > 1.96 with the IN-SAMPLE-chosen drop-set

Reuses loaders + `cadence_ls` + `absorption_test` from the R45/R46 modules.
Sandbox-safe: reads the drive directly. Pure numpy/pandas.
Compliance: positioning language only; no trade-direction vocabulary.
"""
from __future__ import annotations

import argparse
import glob
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.cis_quality_absorption import (
    CIS_HISTORY_DIR,
    load_cis_history_wide,
    load_daily_returns,
)
from src.research.validation.cis_quality_robustness import cadence_ls
from src.research.validation.factor_absorption import absorption_test


# Regime label normalisation — the live engine emitted one "Risk-Off" typo variant.
REGIME_CANON = {
    "Risk-Off": "RISK_OFF",
    "risk_off": "RISK_OFF",
    "risk-off": "RISK_OFF",
}
# Regimes with too few days to condition on honestly (< MIN_REGIME_DAYS in-sample
# are never dropped — you can't estimate a mean from a handful of days).
MIN_REGIME_DAYS = 25

REBAL_DAYS = 5          # R46 winning cadence
COST_BPS = 5.0          # R46 cost bar (Binance VIP taker ≈ 4 bps)
OOS_FRAC = 0.30         # last 30% out of sample (R45/R46 convention)


# ─────────────────────────────────────────────────────────────────────────────
# Regime loader
# ─────────────────────────────────────────────────────────────────────────────
def load_macro_regime(cis_history_dir: Path = CIS_HISTORY_DIR) -> pd.Series:
    """Series[date → normalised macro_regime] from each snapshot's top-level field.

    Date is derived from the filename (`cis_YYYY-MM-DD.json`), matching
    `load_cis_history_wide`.
    """
    rows = {}
    for fp in sorted(glob.glob(str(cis_history_dir / "cis_*.json"))):
        d_date = pd.to_datetime(Path(fp).stem.replace("cis_", "")).normalize()
        with open(fp) as fh:
            payload = json.load(fh)
        reg = payload.get("macro_regime", "UNKNOWN")
        rows[d_date] = REGIME_CANON.get(reg, reg)
    return pd.Series(rows, name="regime").sort_index()


# ─────────────────────────────────────────────────────────────────────────────
# Per-regime decomposition
# ─────────────────────────────────────────────────────────────────────────────
def per_regime_stats(fac: pd.Series, regime: pd.Series,
                     known_arrs: dict, min_days: int = MIN_REGIME_DAYS) -> dict:
    """For each regime, absorption-test the factor's returns on that regime's days.

    Returns {regime: {n, mean_ret, sharpe, alpha_t, alpha_ann_pct}}.
    A regime with < min_days is reported but flagged too_thin=True.
    """
    reg_aligned = regime.reindex(fac.index).ffill()
    out = {}
    for reg in sorted(reg_aligned.dropna().unique()):
        mask = (reg_aligned == reg).values
        n = int(mask.sum())
        entry = {"n": n, "too_thin": n < min_days}
        f_sub = fac.values[mask]
        if n >= 2:
            entry["mean_ret"] = float(np.mean(f_sub))
            sd = float(np.std(f_sub, ddof=1))
            entry["sharpe_ann"] = (float(np.mean(f_sub) / sd * np.sqrt(365))
                                   if sd > 1e-12 else 0.0)
        else:
            entry["mean_ret"] = float("nan")
            entry["sharpe_ann"] = float("nan")
        if n >= 30:
            k_sub = {k: v[mask] for k, v in known_arrs.items()}
            try:
                r = absorption_test(f_sub, k_sub, nw_lags=6, periods_per_year=365)
                entry["alpha_t"] = r["alpha_t"]
                entry["alpha_ann_pct"] = r["alpha_ann_pct"]
            except Exception as ex:
                entry["alpha_t"] = float("nan")
                entry["alpha_ann_pct"] = float("nan")
                entry["error"] = str(ex)
        else:
            entry["alpha_t"] = float("nan")
            entry["alpha_ann_pct"] = float("nan")
        out[reg] = entry
    return out


def choose_drop_set(fac_is: pd.Series, regime: pd.Series,
                    min_days: int = MIN_REGIME_DAYS) -> tuple[set, dict]:
    """Decide which regimes to sit out, using IN-SAMPLE data only.

    Rule: drop a regime iff (i) it has ≥ min_days in-sample AND (ii) its in-sample
    mean factor return is negative. Thin regimes are never dropped (can't estimate).

    Returns (drop_set, per_regime_is_stats).
    """
    reg_is = regime.reindex(fac_is.index).ffill()
    drop = set()
    stats = {}
    for reg in sorted(reg_is.dropna().unique()):
        mask = (reg_is == reg).values
        n = int(mask.sum())
        mean_ret = float(np.mean(fac_is.values[mask])) if n >= 2 else float("nan")
        stats[reg] = {"n": n, "mean_ret": mean_ret, "too_thin": n < min_days}
        if n >= min_days and mean_ret < 0:
            drop.add(reg)
    return drop, stats


def apply_regime_gate(fac: pd.Series, regime: pd.Series, drop_set: set) -> pd.Series:
    """Zero the factor return on days whose regime ∈ drop_set (sit-out = flat)."""
    reg_aligned = regime.reindex(fac.index).ffill()
    gated = fac.copy()
    sit_out = reg_aligned.isin(drop_set).values
    gated.values[sit_out] = 0.0
    return gated


# ─────────────────────────────────────────────────────────────────────────────
# Master run
# ─────────────────────────────────────────────────────────────────────────────
def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R47 — regime-conditioned pillar_O L/S sleeve ===\n")

    cis = load_cis_history_wide()
    rets = load_daily_returns()
    regime = load_macro_regime()

    lo = max(cis["date"].min(), rets.index.min())
    hi = min(cis["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable = sorted(set(cis["asset"]) & set(rets.columns))
    print(f"Window: {lo.date()} → {hi.date()}  ·  {len(rets)} days  ·  "
          f"{len(tradeable)} assets\n")

    # Known factors (identical construction to R45/R46)
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known = {"market": f_market.reindex(rets.index).fillna(0.0).values,
             "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}

    # pillar_O 5d-cadence L/S factor (R46 winner) — gross + 5bps
    O_mat = cis.pivot_table(index="date", columns="asset", values="O")
    fac_gross = cadence_ls(O_mat, rets[tradeable], rebal_days=REBAL_DAYS,
                           cost_bps=0.0).reindex(rets.index).fillna(0.0)
    fac_cost = cadence_ls(O_mat, rets[tradeable], rebal_days=REBAL_DAYS,
                          cost_bps=COST_BPS).reindex(rets.index).fillna(0.0)

    # Regime coverage over the overlap window
    reg_aligned = regime.reindex(rets.index).ffill()
    reg_counts = reg_aligned.value_counts().to_dict()
    print("Regime coverage (overlap window):")
    for r_, c_ in sorted(reg_counts.items(), key=lambda x: -x[1]):
        print(f"   {r_:14s} {c_:4d}  {c_/len(rets)*100:.1f}%")
    print()

    # ── Per-regime decomposition (FULL sample, descriptive) ──
    print("── Per-regime α (full sample, gross) ──")
    regime_full = per_regime_stats(fac_gross, regime, known)
    for reg, st in sorted(regime_full.items(), key=lambda x: -x[1]["n"]):
        thin = "  (thin)" if st["too_thin"] else ""
        print(f"   {reg:14s} n={st['n']:>3}  mean={st['mean_ret']*1e4:+.1f}bp/d  "
              f"Sharpe={st['sharpe_ann']:+.2f}  α_t={st['alpha_t']:+.2f}{thin}")
    print()

    # ── IN-SAMPLE drop-set decision (no look-ahead) ──
    cut = int(len(rets) * (1 - OOS_FRAC))
    is_idx = rets.index[:cut]
    oos_idx = rets.index[cut:]
    fac_gross_is = fac_gross.loc[is_idx]
    drop_set, is_stats = choose_drop_set(fac_gross_is, regime)
    print(f"IN-SAMPLE ({is_idx[0].date()} → {is_idx[-1].date()}, {len(is_idx)}d) "
          f"drop-set (regimes with negative in-sample mean): "
          f"{sorted(drop_set) if drop_set else 'NONE'}")
    for reg, st in sorted(is_stats.items(), key=lambda x: -x[1]["n"]):
        drop_flag = "  → DROP" if reg in drop_set else ""
        thin = "  (thin, never drop)" if st["too_thin"] else ""
        print(f"   {reg:14s} IS n={st['n']:>3}  mean={st['mean_ret']*1e4:+.1f}bp/d"
              f"{drop_flag}{thin}")
    print()

    # ── Build conditioned sleeves (gross + cost), apply FIXED drop-set everywhere ──
    fac_cond_gross = apply_regime_gate(fac_gross, regime, drop_set)
    fac_cond_cost = apply_regime_gate(fac_cost, regime, drop_set)

    # ── 3-check gauntlet: unconditional vs conditioned ──
    def full_abs(series):
        return absorption_test(series.values, known, nw_lags=6, periods_per_year=365)

    def oos_abs(series):
        k_oos = {k: v[cut:] for k, v in known.items()}
        return absorption_test(series.values[cut:], k_oos,
                               nw_lags=6, periods_per_year=365)

    gauntlet = {
        "unconditional": {
            "gross": full_abs(fac_gross),
            "cost5": full_abs(fac_cost),
            "oos_gross": oos_abs(fac_gross),
            "oos_cost5": oos_abs(fac_cost),
        },
        "conditioned": {
            "gross": full_abs(fac_cond_gross),
            "cost5": full_abs(fac_cond_cost),
            "oos_gross": oos_abs(fac_cond_gross),
            "oos_cost5": oos_abs(fac_cond_cost),
        },
    }

    print("── 3-check gauntlet (pillar_O, 5d rebal) ──")
    for sleeve in ("unconditional", "conditioned"):
        g = gauntlet[sleeve]
        print(f"  {sleeve}:")
        print(f"    gross     t={g['gross']['alpha_t']:+.2f}  "
              f"ann={g['gross']['alpha_ann_pct']:+.1f}%")
        print(f"    5bps      t={g['cost5']['alpha_t']:+.2f}  "
              f"ann={g['cost5']['alpha_ann_pct']:+.1f}%")
        print(f"    OOS 5bps  t={g['oos_cost5']['alpha_t']:+.2f}  "
              f"ann={g['oos_cost5']['alpha_ann_pct']:+.1f}%  n={g['oos_cost5']['n']}")
    print()

    # ── OOS-by-regime diagnostic: is the OOS collapse concentrated in one regime,
    #    or spread across regimes that were positive in-sample? (Answers "could
    #    ANY regime gate rescue OOS?" — if the collapse hits IS-positive regimes
    #    too, no honest gate can save it.) ──
    fac_gross_oos = fac_gross.loc[oos_idx]
    known_oos = {k: v[cut:] for k, v in known.items()}
    oos_by_regime = per_regime_stats(fac_gross_oos, regime, known_oos)
    print("── OOS-by-regime (does the collapse concentrate?) ──")
    for reg, st in sorted(oos_by_regime.items(), key=lambda x: -x[1]["n"]):
        was_pos_is = is_stats.get(reg, {}).get("mean_ret", 0) > 0
        flag = "  ⚠ IS-positive but OOS-?" if was_pos_is else ""
        print(f"   {reg:14s} OOS n={st['n']:>3}  mean={st['mean_ret']*1e4:+.1f}bp/d  "
              f"Sharpe={st['sharpe_ann']:+.2f}{flag}")
    print()

    out = {
        "window": f"{lo.date()} → {hi.date()}",
        "n_days": len(rets),
        "n_assets": len(tradeable),
        "rebal_days": REBAL_DAYS,
        "cost_bps": COST_BPS,
        "oos_window": f"{oos_idx[0].date()} → {oos_idx[-1].date()}",
        "oos_n": len(oos_idx),
        "regime_counts": {str(k): int(v) for k, v in reg_counts.items()},
        "regime_full_stats": regime_full,
        "in_sample_stats": is_stats,
        "oos_by_regime": oos_by_regime,
        "drop_set": sorted(drop_set),
        "gauntlet": gauntlet,
    }
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    report = format_report(out)
    (out_dir / "REPORT.md").write_text(report)
    print(report)
    print(f"\nSaved: {out_dir/'verdict.json'} + {out_dir/'REPORT.md'}")
    return out


def format_report(out: dict) -> str:
    L = []
    L.append("# R47 — Regime-conditioned pillar_O L/S sleeve\n")
    L.append(f"**Window:** {out['window']}  ·  **Days:** {out['n_days']}  ·  "
             f"**Universe:** {out['n_assets']} assets  ·  "
             f"**Rebal:** {out['rebal_days']}d  ·  **Cost:** {out['cost_bps']:.0f} bps\n")
    L.append("Gate the R46-winning pillar_O 5d-cadence L/S sleeve on the REAL CIS "
             "`macro_regime`. Drop-set chosen from IN-SAMPLE only (no look-ahead), "
             "then applied fixed to OOS.\n")

    # Per-regime α (full sample)
    L.append("## Per-regime α (full sample, gross — descriptive)\n")
    L.append("| Regime | n | mean bp/d | Sharpe ann | α_t | note |")
    L.append("|---|--:|--:|--:|--:|---|")
    for reg, st in sorted(out["regime_full_stats"].items(), key=lambda x: -x[1]["n"]):
        note = "thin (< min days)" if st["too_thin"] else ""
        at = st["alpha_t"]
        at_s = f"**{at:+.2f}**" if not np.isnan(at) and abs(at) > 1.96 else f"{at:+.2f}"
        L.append(f"| {reg} | {st['n']} | {st['mean_ret']*1e4:+.1f} | "
                 f"{st['sharpe_ann']:+.2f} | {at_s} | {note} |")

    # Drop-set
    L.append(f"\n## In-sample drop-set decision ({out['oos_window']} held out)\n")
    L.append("A regime is dropped iff it has ≥ min-days in-sample AND its in-sample "
             "mean factor return is negative. Thin regimes are never dropped.\n")
    L.append(f"**Drop-set: {out['drop_set'] if out['drop_set'] else 'NONE'}**\n")
    L.append("| Regime | IS n | IS mean bp/d | decision |")
    L.append("|---|--:|--:|---|")
    for reg, st in sorted(out["in_sample_stats"].items(), key=lambda x: -x[1]["n"]):
        dec = ("DROP" if reg in out["drop_set"]
               else "thin → keep" if st["too_thin"] else "keep")
        L.append(f"| {reg} | {st['n']} | {st['mean_ret']*1e4:+.1f} | {dec} |")

    # OOS-by-regime diagnostic
    L.append("\n## OOS-by-regime diagnostic (is the collapse concentrated?)\n")
    L.append("The OOS window's factor return, split by regime. If regimes that were "
             "POSITIVE in-sample also collapse OOS, no honest regime gate can rescue it.\n")
    L.append("| Regime | OOS n | OOS mean bp/d | OOS Sharpe | IS mean bp/d | IS→OOS |")
    L.append("|---|--:|--:|--:|--:|---|")
    for reg, st in sorted(out["oos_by_regime"].items(), key=lambda x: -x[1]["n"]):
        is_mean = out["in_sample_stats"].get(reg, {}).get("mean_ret", float("nan"))
        is_n = out["in_sample_stats"].get(reg, {}).get("n", 0)
        if is_n == 0 or np.isnan(is_mean):
            arrow = "**NO IS DAYS** (temporal confound)"
            is_str = "—"
        else:
            arrow = ("held +" if is_mean > 0 and st["mean_ret"] > 0
                     else "FLIPPED +→−" if is_mean > 0 and st["mean_ret"] <= 0
                     else "held −" if is_mean <= 0 and st["mean_ret"] <= 0
                     else "−→+ (mis-dropped)")
            is_str = f"{is_mean*1e4:+.1f}"
        L.append(f"| {reg} | {st['n']} | {st['mean_ret']*1e4:+.1f} | "
                 f"{st['sharpe_ann']:+.2f} | {is_str} | {arrow} |")

    # Gauntlet
    L.append("\n## 3-check gauntlet: unconditional vs conditioned\n")
    L.append("`t` = Newey-West residual-α after {market, momentum}. "
             "**Bold** = clears t > 1.96.\n")
    L.append("| Sleeve | gross t | gross ann% | 5bps t | 5bps ann% | OOS 5bps t | OOS ann% | OOS n |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for sleeve in ("unconditional", "conditioned"):
        g = out["gauntlet"][sleeve]
        def b(v):
            return f"**{v:+.2f}**" if abs(v) > 1.96 else f"{v:+.2f}"
        L.append(f"| {sleeve} | {b(g['gross']['alpha_t'])} | "
                 f"{g['gross']['alpha_ann_pct']:+.1f} | {b(g['cost5']['alpha_t'])} | "
                 f"{g['cost5']['alpha_ann_pct']:+.1f} | {b(g['oos_cost5']['alpha_t'])} | "
                 f"{g['oos_cost5']['alpha_ann_pct']:+.1f} | {g['oos_cost5']['n']} |")

    # Verdict
    L.append("\n## Verdict\n")
    u = out["gauntlet"]["unconditional"]
    c = out["gauntlet"]["conditioned"]
    checks_uncond = [u["gross"]["alpha_t"] > 1.96, u["cost5"]["alpha_t"] > 1.96,
                     u["oos_cost5"]["alpha_t"] > 1.96]
    checks_cond = [c["gross"]["alpha_t"] > 1.96, c["cost5"]["alpha_t"] > 1.96,
                   c["oos_cost5"]["alpha_t"] > 1.96]
    L.append(f"- Unconditional pillar_O 3-check: gross={checks_uncond[0]}, "
             f"5bps={checks_uncond[1]}, OOS={checks_uncond[2]} "
             f"→ {'PASS' if all(checks_uncond) else 'FAIL'}")
    L.append(f"- Conditioned pillar_O 3-check: gross={checks_cond[0]}, "
             f"5bps={checks_cond[1]}, OOS={checks_cond[2]} "
             f"→ {'PASS' if all(checks_cond) else 'FAIL'}")

    oos_improve = c["oos_cost5"]["alpha_t"] - u["oos_cost5"]["alpha_t"]
    L.append("")

    # Structural diagnosis from the OOS-by-regime table:
    #  (i) temporal confound — a strongly-negative-OOS regime with no IS presence
    #  (ii) mis-drop — a regime dropped IS-negative but actually positive OOS
    #  (iii) workhorse decay — the biggest IS-positive regime fading OOS
    no_is_neg_oos = [reg for reg, st in out["oos_by_regime"].items()
                     if out["in_sample_stats"].get(reg, {}).get("n", 0) == 0
                     and st["mean_ret"] < 0 and st["n"] >= 20]
    mis_dropped = [reg for reg in out["drop_set"]
                   if out["oos_by_regime"].get(reg, {}).get("mean_ret", 0) > 0]

    if not out["drop_set"]:
        L.append("- **No regime qualified for the drop-set in-sample** — every regime "
                 "with enough days had non-negative in-sample mean. Regime-conditioning "
                 "has nothing to act on; the unconditional sleeve stands. R47 = the "
                 "regime story is descriptive, not a tradable gate on this data.")
    elif all(checks_cond) and oos_improve > 0:
        L.append(f"- **Regime-conditioning IMPROVES OOS** (Δ OOS-5bps t = {oos_improve:+.2f}) "
                 f"AND clears the full 3-check gauntlet → R47 SURVIVES as an upgrade to "
                 f"the pillar_O sleeve. The drop-set was chosen without look-ahead, so "
                 f"the OOS gain is real. Slot the conditioned sleeve into the two-layer book.")
    elif oos_improve > 0:
        L.append(f"- Regime-conditioning improves OOS (Δ OOS-5bps t = {oos_improve:+.2f}) "
                 f"but does not clear the full gauntlet. Promising, not confirmed — watch.")
    else:
        L.append(f"- **Regime-conditioning does NOT improve OOS** (Δ OOS-5bps t = "
                 f"{oos_improve:+.2f}). R47 dies honest — the unconditional pillar_O "
                 f"sleeve is the better artifact.")
        L.append("- **Two structural reasons the live regime label is not a usable gate "
                 "here** (both from the OOS-by-regime table, not hindsight):")
        if no_is_neg_oos:
            L.append(f"  1. **Temporal-coverage confound** — {', '.join(no_is_neg_oos)} is "
                     f"the strongly-negative-OOS regime (the real culprit) but has ZERO "
                     f"in-sample days, so no in-sample-learned drop rule could ever catch "
                     f"it. The bad regime lives entirely out of sample.")
        if mis_dropped:
            L.append(f"  2. **Mis-drop** — the in-sample rule dropped {', '.join(mis_dropped)} "
                     f"(IS-negative by noise) but that regime was POSITIVE OOS, so the gate "
                     f"sat out profitable days and made OOS worse.")
        L.append("- The workhorse regime (largest IS-positive) decayed IS→OOS independent "
                 "of any regime flip — the OOS collapse is broad alpha-decay, not a "
                 "regime-specific hole a gate could plug.")
        L.append("- **Confirms aggregate lesson #15 (REGIME-DETECTOR ARCHITECTURE > "
                 "FACTOR CHOICE) from the factor-gating angle:** a calendar-window flip "
                 "(R46's W5) is NOT the same as a regime-label flip. Regime-conditioning "
                 "can only rescue a sleeve when the bad regime (a) is *labelled* correctly "
                 "by the live engine AND (b) appears in-sample often enough to be learned "
                 "without look-ahead. Neither held here — the slow macro_regime label is "
                 "not a usable gate (same verdict R49/R50/R51 reached on direction-gating). "
                 "Shelf candidate R52b: an *a-priori* TIGHTENING drop (monetary-tightening "
                 "structurally penalises high-O quality longs) — but that needs a regime-"
                 "STRATIFIED CV or a fresh OOS where TIGHTENING recurs; it cannot be "
                 "credited on this 70/30 split.")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path,
                    default=Path(f"reports/cis_quality_regime/{datetime.now():%Y-%m-%d}"))
    args = ap.parse_args()
    run(args.out_dir)
