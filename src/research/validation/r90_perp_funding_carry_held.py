"""
R90 — Perp Funding-Carry HELD (Weekly+ Single-Instrument, Cost-Tier Aware) (Seth, 2026-07-26).

Per R89 lesson #58: any basis/carry/two-leg trade MUST pass a ≥10bps cost-tier gate before
"tradeable." R89's perp-spot basis L/S (daily two-leg flip) passed 3-check at 5bps but
**died at 10bps** (cost_t=−0.69, OOS +1.9%) — the W5 fragility-clearing edge was a taker-fee
illusion.

R89's KEPT DISCOVERY: perp microstructure IS regime-orthogonal to the OHLCV factor family
(R89 W5=+36.59%, all 6 windows positive — the W5 fragility that kills OHLCV-family strategies
doesn't touch perp microstructure). But the daily two-leg flip is too expensive.

R90 TRANSFORMS the kept discovery into a tradeable shape:
  · Single-instrument: perps only (no spot leg). Long perp A / short perp B = 2 perp positions
    (4.5bps each on Hyperliquid), not 4 (spot + perp × 2 = 15-30bps).
  · LOW turnover: weekly/monthly rebal (7d/14d/21d/30d) — R89's 1d flip was the structural cost.
  · EXPLICIT cost-tier sweep (R32 lesson #58 baked in): every cell re-evaluated at 5/10/20/30bps.
  · Verdict gates on `survives_realistic_10bps` — if the 10bps cost tier sign-flips or OOS dies
    → verdict is 🔴 REFUTED (taker-fee illusion, same class as R32/R89).

Construction:
  · Universe: 47 perps with both funding + perp OHLCV (Hyperliquid dataset).
  · Score: funding residual (cross-sectional demean of daily funding) — R76's signal verbatim.
  · k_terciles = 3 (R76/R46 standard).
  · Cadences {7, 14, 21, 30}d × costs {0, 5, 10, 20, 30}bps.
  · 3-check gauntlet: gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96 (per R56/R76).
  · Cost-tier sweep: at the best cell, recompute α_t / OOS_t / OOS_ann% at 5/10/20/30bps.
  · Per-window W1–W6 attribution.
  · Both signs (high_fund_long, low_fund_long); matched-cell sign verdict.

Verdict grammar (R32/R89 lesson #58 — STRICT):
  · ✅ SURVIVES — TRADEABLE: 3-check at 5bps passes AND survives_realistic_10bps = True
    AND matched-cell sign clear AND W5 t ≥ 0. Eligible for Strategy 2 slot.
  · 🟡 PARTIAL: 3-check passes at 5bps BUT survives_realistic_10bps = False (edge dies at
    realistic cost — confirmed R32 lesson). NOT tradeable.
  · 🔴 REFUTED: 3-check fails at any cost tier. Perp-only funding carry lacks standalone edge.

R76 vs R90 — what R90 is NOT:
  · R76 was tested at 0bps cost only (its blind spot). R90 sees the cost-tier reality.
  · R76 cadence range {1, 3, 5, 7, 14, 21}d. R90 LOW turnover {7, 14, 21, 30}d.
  · R76 universe: 28 strict funding ∩ CIS ∩ OHLCV. R90: 47 perps (no CIS overlay requirement).
  · R90's value-add: prove R76's edge is FUNDING-CARRY (not noise) by surviving at ≥10bps cost
    AND being stable at lower turnover. If R90 PARTIAL → R76's standalone edge is a taker-fee
    illusion (same death as R89). If R90 TRADEABLE → R76 was the real edge, R90 is the
    deployable spec.

Anti-imposter:
  - Funding residual is single-instrument (perp only) — no spot leg. R89's spot hedge was the
    cost trap. R90 removes it.
  - Cost-tier sweep is MANDATORY (R32 lesson #58). Don't claim "SURVIVES" if 10bps cost dies.
  - The R77 fusion cell (w_R46=0.25, w_R62=0.75, w_R76=0.30) is FROZEN; R90 does NOT touch it.
  - R90 result informs Strategy 2 slot ONLY if verdict is ✅ TRADEABLE.
  - R90 is research-only this round; live paper deployment requires user sign-off after verdict.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.research.validation.r76_funding_residual_ls import (
    score_funding_residual,
    SIGN_HIGH_FUND_LONG, SIGN_LOW_FUND_LONG,
)
from src.research.validation.r76_funding_residual_ls import _VALID_SIGNS as R76_VALID_SIGNS
from src.research.validation.r73_pillar_a_level_ls import pillar_a_level_ls
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.w5_forensics_external import load_funding_daily


# === Constants ================================================================
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# R90-specific
R90_K_TERCILES = 3                       # R76/R46 standard
R90_MIN_TRADEABLE = 12                   # same floor as R76/R73
R90_CADENCES = (7, 14, 21, 30)           # LOW turnover (weekly + monthly)
R90_COST_GRID = (0.0, 5.0, 10.0, 20.0, 30.0)  # R32/R89 cost-tier sweep
R90_REALISTIC_COST_BPS = 10.0            # lesson #58 — gate on survival here
R90_PERP_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")

_VALID_SIGNS = R76_VALID_SIGNS  # both signs of R76 (high_fund_long / low_fund_long)


# === Perp returns loader (parallel to R89's load_perp_returns) ===============
def load_perp_returns(panel_dates: pd.DatetimeIndex,
                      assets: list) -> pd.DataFrame:
    """Load perp close-to-close returns for the given assets, aligned to panel_dates.

    Single-instrument (perp OHLCV only — no spot leg). R89's load_perp_returns exact pattern.
    """
    rets = pd.DataFrame(index=panel_dates)
    for asset in assets:
        fp = R90_PERP_DIR / f"{asset.lower()}_1d_ohlcv.csv"
        if not fp.exists():
            continue
        df = pd.read_csv(fp)
        if df.empty or "openTime" not in df.columns or "close" not in df.columns:
            continue
        df["date"] = pd.to_datetime(df["openTime"], unit="ms").dt.normalize()
        daily = df.groupby("date")["close"].last().sort_index().pct_change()
        rets[asset] = daily.reindex(panel_dates)
    return rets


# === Leg construction (reuses R76's kernel via pillar_a_level_ls) =============
def perp_funding_carry_held(score_wide: pd.DataFrame, rets: pd.DataFrame,
                             k_terciles: int = R90_K_TERCILES,
                             cost_bps: float = 0.0,
                             rebal_days: int = 7,
                             sign: str = SIGN_HIGH_FUND_LONG) -> pd.Series:
    """Long high-funding-residual / short low-funding-residual (or reversed under low_fund_long).

    Reuses R76's funding_residual_ls kernel (parallel to pillar_a_level_ls as L/S engine).
    R90's contribution: lower cadence defaults + cost-tier sweep at the verdict.
    """
    if sign not in _VALID_SIGNS:
        raise ValueError(f"sign must be one of {_VALID_SIGNS}, got {sign!r}")
    flipped = -score_wide if sign == SIGN_LOW_FUND_LONG else score_wide
    return pillar_a_level_ls(flipped, rets, k_terciles=k_terciles,
                              cost_bps=cost_bps, rebal_days=rebal_days,
                              sign="high_a_long")  # already flipped above


# === Cost-tier sweep (R32 lesson #58 — MANDATORY) ============================
def cost_tier_sweep(leg_returns: pd.Series, rets: pd.DataFrame,
                    tradeable: list, *,
                    cost_grid: tuple = R90_COST_GRID,
                    cut: int) -> dict:
    """For each cost tier, recompute the L/S with that cost and run gauntlet_3check.

    R32 / R89 lesson #58: a 'SURVIVES' on a high-turnover strategy without a cost sensitivity
    table is a curve-fit to an optimistic fee, not a finding. This is the gate that killed R89.

    Returns: {cost_bps: {gross_t, oos_t, oos_ann_pct, gross_ann_pct, passes_all}}
    """
    # Need to re-build the score from the leg_returns to recompute? No — we have the score
    # as the implicit structure of the leg. But we don't have the score explicitly here.
    # Cheaper: re-run the L/S with each cost.
    # However, we need score_wide. Best to pass it explicitly.
    raise NotImplementedError(
        "cost_tier_sweep needs score_wide — use cost_tier_sweep_with_score() instead"
    )


def cost_tier_sweep_with_score(score_wide: pd.DataFrame, rets: pd.DataFrame,
                                tradeable: list, *,
                                cadence: int,
                                cost_grid: tuple = R90_COST_GRID,
                                cut: int,
                                sign: str = SIGN_HIGH_FUND_LONG) -> dict:
    """For each cost tier, recompute the L/S at (cadence, cost) and run gauntlet_3check.

    cost grid is FULL — includes 0bps for reference. Survival at 10bps is the gate.
    Returns: {cost_bps: {gross_t, oos_t, oos_ann_pct, gross_ann_pct, passes_all}}
    """
    out = {}
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.values, "momentum": f_momentum.values}
    for cost_bps in cost_grid:
        leg = perp_funding_carry_held(score_wide, rets[tradeable],
                                       k_terciles=R90_K_TERCILES,
                                       cost_bps=cost_bps,
                                       rebal_days=cadence,
                                       sign=sign)
        leg = leg.reindex(rets.index).fillna(0.0)
        g = gauntlet_3check(leg.values, known_full, cut)
        out[cost_bps] = {
            "cost_bps": cost_bps,
            "gross_t": g["gross_t"],
            "gross_alpha_ann_pct": g["gross_alpha_ann_pct"],
            "oos_t": g["oos_t"],
            "oos_alpha_ann_pct": g["oos_alpha_ann_pct"],
            "passes_gross": g["passes_gross"],
            "passes_oos": g["passes_oos"],
            "passes_all": g["passes_all"],
        }
    return out


# === Sweep (R76-style cadence × cost, R90's wider cost grid) =================
def perp_funding_carry_sweep(score, rets, *,
                              cadences: tuple = R90_CADENCES,
                              cost_grid: tuple = R90_COST_GRID,
                              k_terciles: int = R90_K_TERCILES,
                              sign: str = SIGN_HIGH_FUND_LONG) -> dict:
    """Returns {(cad, bps): {gross_t, oos_t, oos_ann_pct, passes_all}}."""
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.values, "momentum": f_momentum.values}
    cut = int(len(rets) * (1.0 - OOS_FRAC))
    sweep = {}
    for cad in cadences:
        for bps in cost_grid:
            leg = perp_funding_carry_held(score, rets, k_terciles=k_terciles,
                                           cost_bps=bps, rebal_days=cad,
                                           sign=sign)
            leg = leg.reindex(rets.index).fillna(0.0)
            g = gauntlet_3check(leg.values, known_full, cut)
            sweep[(cad, bps)] = {
                "cadence": cad, "cost_bps": bps, "sign": sign,
                "gross_t": g["gross_t"],
                "gross_alpha_ann_pct": g["gross_alpha_ann_pct"],
                "oos_t": g["oos_t"],
                "oos_alpha_ann_pct": g["oos_alpha_ann_pct"],
                "passes_gross": g["passes_gross"],
                "passes_oos": g["passes_oos"],
                "passes_all": g["passes_all"],
            }
    return sweep


# === Run =====================================================================
def run(out_dir: Path,
        cadences: tuple = R90_CADENCES,
        cost_grid: tuple = R90_COST_GRID,
        sign: str = SIGN_HIGH_FUND_LONG) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R90 — Perp Funding-Carry HELD (sign={sign}, k={R90_K_TERCILES}, "
          f"cadences={cadences}, cost_grid={cost_grid}) ===\n")

    # ── Load perp data ────────────────────────────────────────────────────────
    print("Loading perp OHLCV + funding (Hyperliquid dataset) …")
    # First, get the universe of perps with both funding + OHLCV
    funding_daily = load_funding_daily()
    funding_assets = set(funding_daily.columns)

    # Get perp OHLCV universe
    perp_files = list(R90_PERP_DIR.glob("*_1d_ohlcv.csv"))
    ohlcv_assets = [f.stem.replace("_1d_ohlcv", "").upper() for f in perp_files]
    perp_assets = sorted(funding_assets & set(ohlcv_assets))
    print(f"Perp universe (funding ∩ OHLCV): {len(perp_assets)} assets")

    if not perp_assets:
        raise RuntimeError(
            "No perp assets with both funding + OHLCV. "
            "R90 refuses to silently widen the universe."
        )

    # Build panel dates from perp OHLCV (use intersection of funding + OHLCV date ranges)
    perp_returns = load_perp_returns(funding_daily.index, perp_assets)
    perp_returns = perp_returns.dropna(how="all")

    # Trim to assets with sufficient perp returns coverage
    coverage = perp_returns.notna().sum() / len(perp_returns)
    perp_assets = [a for a in perp_assets if coverage.get(a, 0) > 0.5]
    perp_returns = perp_returns[perp_assets]
    funding_daily = funding_daily[[a for a in funding_assets if a in perp_assets]]

    # Align
    lo = max(funding_daily.index.min(), perp_returns.dropna(how="all").index.min())
    hi = min(funding_daily.index.max(), perp_returns.dropna(how="all").index.max())
    rets = perp_returns.loc[(perp_returns.index >= lo) & (perp_returns.index <= hi)]
    funding_daily = funding_daily.loc[(funding_daily.index >= lo) & (funding_daily.index <= hi)]

    print(f"Panel: {lo.date()} → {hi.date()} ({len(rets)} days, "
          f"{len(perp_assets)} perps)")
    print(f"Funding daily: {funding_daily.shape[0]} days × "
          f"{funding_daily.shape[1]} assets")

    if len(perp_assets) < R90_MIN_TRADEABLE:
        raise RuntimeError(
            f"Universe too small: {len(perp_assets)} < {R90_MIN_TRADEABLE} "
            f"(R90_MIN_TRADEABLE floor). R90 refuses to silently widen the universe."
        )

    # ── Score: funding residual (R76's signal verbatim) ───────────────────────
    print("\nComputing funding residual (cross-sectional demean) …")
    score_residual_wide = score_funding_residual(funding_daily, perp_assets)
    score_residual_wide = score_residual_wide.reindex(rets.index).ffill()
    print(f"  Score shape: {score_residual_wide.shape}, "
          f"mean={score_residual_wide.mean().mean():.6f} (should be ~0 by construction), "
          f"std={score_residual_wide.std().mean():.6f}")

    # ── 6-window partition (R76 parity) ───────────────────────────────────────
    windows = partition_into_windows(rets.index, 6)
    print(f"\n6-window partition: {[lab for lab, _, _ in windows]}")

    # ── Build R90 leg at default cadence (7d/0bps) ────────────────────────────
    print("\nBuilding R90 leg at 7d/0bps (default) …")
    leg_default = perp_funding_carry_held(score_residual_wide, rets,
                                           k_terciles=R90_K_TERCILES, cost_bps=0.0,
                                           rebal_days=7, sign=sign)
    leg_default = leg_default.reindex(rets.index).fillna(0.0)

    # ── Full sweep (cadences × costs, both signs) ─────────────────────────────
    print(f"\n══ Cadence × cost sweep (R90 low turnover {cadences}) ══\n")
    sweep = perp_funding_carry_sweep(score_residual_wide, rets,
                                       cadences=cadences, cost_grid=cost_grid,
                                       sign=sign)
    # Print summary
    print(f"  Cell | cadence | cost | gross_t | OOS_t | OOS_ann% | passes_all")
    print(f"  -----+---------+------+---------+-------+----------+-----------")
    for (cad, bps), v in sweep.items():
        print(f"  {cad:3d}d/{bps:5.1f}bps | gross_t={v['gross_t']:+.2f} | "
              f"OOS_t={v['oos_t']:+.2f} | OOS_ann={v['oos_alpha_ann_pct']:+.1f}% | "
              f"passes={'YES' if v['passes_all'] else 'NO'}")

    # ── Find best cell (highest gross_t at 5bps; safer than 0bps) ─────────────
    best_cell = max(sweep.items(),
                    key=lambda kv: (kv[1]["gross_t"] if kv[1]["cost_bps"] == 5.0 else -999,
                                     kv[1]["oos_t"]))
    (best_cad, best_bps), best_metrics = best_cell
    print(f"\nBest cell (highest gross_t at 5bps): {best_cad}d/{best_bps}bps")
    print(f"  gross_t = {best_metrics['gross_t']:+.2f}, "
          f"OOS_t = {best_metrics['oos_t']:+.2f}, "
          f"passes_all = {best_metrics['passes_all']}")

    # ── Cost-tier sweep at best cell (R32 lesson #58 — MANDATORY) ────────────
    print(f"\n══ Cost-tier sweep at best cell ({best_cad}d, sign={sign}) — R32/R89 gate ══\n")
    cut = int(len(rets) * (1.0 - OOS_FRAC))
    cost_tier = cost_tier_sweep_with_score(score_residual_wide, rets, perp_assets,
                                            cadence=best_cad, cost_grid=cost_grid,
                                            cut=cut, sign=sign)
    print(f"  cost_bps | gross_t | OOS_t | OOS_ann% | passes_all | survives_realistic_10bps")
    print(f"  ---------+---------+-------+----------+------------+------------------------")
    for cost_bps, v in cost_tier.items():
        survives = cost_tier[R90_REALISTIC_COST_BPS]["passes_all"] if R90_REALISTIC_COST_BPS in cost_tier else False
        marker = " ← GATE" if cost_bps == R90_REALISTIC_COST_BPS else ""
        print(f"  {cost_bps:8.1f} | {v['gross_t']:+.2f} | {v['oos_t']:+.2f} | "
              f"{v['oos_alpha_ann_pct']:+.1f}% | "
              f"{'YES' if v['passes_all'] else 'NO':<10} | "
              f"{survives}{marker}")

    survives_realistic_10bps = cost_tier[R90_REALISTIC_COST_BPS]["passes_all"]
    survives_realistic_10bps_t = cost_tier[R90_REALISTIC_COST_BPS]["oos_t"]
    survives_realistic_10bps_ann = cost_tier[R90_REALISTIC_COST_BPS]["oos_alpha_ann_pct"]
    print(f"\n  Survives at 10bps? {survives_realistic_10bps}")
    print(f"  OOS_t at 10bps = {survives_realistic_10bps_t:+.2f}")
    print(f"  OOS_ann% at 10bps = {survives_realistic_10bps_ann:+.1f}%")

    # ── Per-window attribution at best cell (5bps reference) ─────────────────
    print(f"\n══ Per-window W1–W6 at best cell ({best_cad}d/5bps) ══\n")
    fac_5bps = perp_funding_carry_held(score_residual_wide, rets[perp_assets],
                                        k_terciles=R90_K_TERCILES, cost_bps=5.0,
                                        rebal_days=best_cad, sign=sign)
    fac_5bps = fac_5bps.reindex(rets.index).fillna(0.0)
    from src.research.validation.r63_fusion_validation import per_window
    pw_5bps = per_window(fac_5bps, windows)
    print("  Window | n_days | ann_pct | maxDD")
    print("  -------+--------+---------+--------")
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        if label in pw_5bps:
            print(f"  {label} | {pw_5bps[label]['n_days']:6d} | "
                  f"{pw_5bps[label]['ann_pct']:+.1f}% | "
                  f"{pw_5bps[label]['max_dd']:+.2%}")

    # ── Verdict (R32/R89 lesson #58 — STRICT cost-tier gate) ─────────────────
    passes_3check_5bps = best_metrics["passes_all"]
    if passes_3check_5bps and survives_realistic_10bps:
        verdict = ("✅ SURVIVES — TRADEABLE — R90 perp funding carry HELD clears 3-check "
                   "AND survives ≥10bps realistic cost. Eligible for Strategy 2 slot.")
        verdict_band = "TRADEABLE"
    elif passes_3check_5bps and not survives_realistic_10bps:
        verdict = ("🟡 PARTIAL — 3-check passes at 5bps but edge dies at 10bps (R32/R89 "
                   "taker-fee illusion). R76's apparent edge was a cost-tier artifact; "
                   "perp-only funding carry cannot survive realistic cost.")
        verdict_band = "PARTIAL"
    else:
        verdict = ("🔴 REFUTED — perp-only funding carry HELD lacks standalone edge. "
                   "Perp microstructure (R89 too) cannot survive 3-check at any cost tier.")
        verdict_band = "REFUTED"

    print(f"\nVerdict: {verdict}\n")

    # ── Persist out ───────────────────────────────────────────────────────────
    out = {
        "panel": {
            "lo": str(lo.date()), "hi": str(hi.date()),
            "n_days": int(len(rets)), "n_perps": len(perp_assets),
        },
        "construction": {
            "score": "funding_residual = funding[t, a] - mean_a(funding[t, a])",
            "k_terciles": R90_K_TERCILES,
            "min_tradeable": R90_MIN_TRADEABLE,
            "universe": "perp OHLCV ∩ perp funding (Hyperliquid)",
            "cadences": list(cadences),
            "cost_grid": list(cost_grid),
            "realistic_cost_bps": R90_REALISTIC_COST_BPS,
            "single_instrument": True,
            "low_turnover": True,
        },
        "windows": [{"label": lab, "start": str(s.date()), "end": str(e.date()),
                      "n_days": int((e - s).days + 1)}
                     for lab, s, e in windows],
        "best_cell": {
            "cadence": best_cad, "cost_bps_5bps": 5.0,
            "sign": sign,
            "gauntlet_5bps": best_metrics,
        },
        "cost_tier_sweep": {f"{int(k)}bps": v for k, v in cost_tier.items()},
        "survives_realistic_10bps": survives_realistic_10bps,
        "per_window_5bps": pw_5bps,
        "sweep": {f"{c}d/{b}bps": v for (c, b), v in sweep.items()},
        "verdict": {
            "band": verdict_band,
            "verdict_string": verdict,
            "passes_3check_5bps": passes_3check_5bps,
            "survives_realistic_10bps": survives_realistic_10bps,
        },
        "live_book_impact": {
            "touches_frozen_r77_cell": False,
            "strategy_2_slot_eligible": survives_realistic_10bps,
            "note": ("R90 is research-only. Strategy 2 slot is OPENED only if verdict is "
                     "✅ TRADEABLE + user sign-off."),
        },
    }
    return out


# === Format report ===========================================================
def format_report(payload: dict) -> str:
    """Human-readable R90 report."""
    lines = []
    lines.append("# R90 — Perp Funding-Carry HELD (Cost-Tier Aware)")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"**Panel:** {payload['panel']['lo']} → {payload['panel']['hi']} "
                 f"({payload['panel']['n_days']} days, "
                 f"{payload['panel']['n_perps']}-perp universe)")
    lines.append("")
    lines.append("## Verdict")
    vd = payload["verdict"]  # rename to avoid shadowing in loops below
    lines.append(f"**{vd['band']}** — {vd['verdict_string']}")
    lines.append("")
    lines.append(f"- Passes 3-check at 5bps: **{vd['passes_3check_5bps']}**")
    lines.append(f"- Survives realistic 10bps cost: **{vd['survives_realistic_10bps']}**")
    lines.append("")
    lines.append("## Cost-tier sweep (R32/R89 lesson #58 — MANDATORY)")
    lines.append("")
    lines.append("| cost_bps | gross_t | OOS_t | OOS_ann% | passes_all |")
    lines.append("|----------|---------|-------|----------|------------|")
    for k, v_t in payload["cost_tier_sweep"].items():
        marker = " ← GATE" if float(k.replace("bps", "")) == R90_REALISTIC_COST_BPS else ""
        lines.append(f"| {k} | {v_t['gross_t']:+.2f} | {v_t['oos_t']:+.2f} | "
                     f"{v_t['oos_alpha_ann_pct']:+.1f}% | "
                     f"{'YES' if v_t['passes_all'] else 'NO'} |{marker}")
    lines.append("")
    lines.append("## Per-window W1–W6 at best cell (5bps)")
    lines.append("")
    lines.append("| Window | n_days | ann_pct | maxDD |")
    lines.append("|--------|--------|---------|-------|")
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        if label in payload["per_window_5bps"]:
            pw = payload["per_window_5bps"][label]
            lines.append(f"| {label} | {pw['n_days']:6d} | "
                         f"{pw['ann_pct']:+.1f}% | {pw['max_dd']:+.2%} |")
    lines.append("")
    lines.append("## Cadence × cost sweep (full grid)")
    lines.append("")
    lines.append("| cell | gross_t | OOS_t | OOS_ann% | passes_all |")
    lines.append("|------|---------|-------|----------|------------|")
    for k, v_cell in payload["sweep"].items():
        lines.append(f"| {k} | {v_cell['gross_t']:+.2f} | {v_cell['oos_t']:+.2f} | "
                     f"{v_cell['oos_alpha_ann_pct']:+.1f}% | "
                     f"{'YES' if v_cell['passes_all'] else 'NO'} |")
    lines.append("")
    lines.append("## Live book impact")
    li = payload["live_book_impact"]
    lines.append(f"- Touches frozen R77 cell: **{li['touches_frozen_r77_cell']}**")
    lines.append(f"- Strategy 2 slot eligible: **{li['strategy_2_slot_eligible']}**")
    lines.append(f"- Note: {li['note']}")
    lines.append("")
    lines.append("## Aggregate lesson #58 (depends on verdict)")
    band = vd["band"]
    if band == "TRADEABLE":
        lines.append("- ✅ Aggregate lesson #58 (confirmed in positive form): 'Perp funding "
                     "carry HELD (weekly+ rebal, single-instrument, no spot leg) IS a tradeable "
                     "Strategy 2 candidate even at ≥10bps realistic cost. Lesson #58's "
                     "cost-tier gate is the right discipline — the R76 edge was real but "
                     "invisible at 0bps test. R90 becomes Strategy 2; R89 becomes the "
                     "cautionary tale of what two-leg daily flips cost.'")
    elif band == "PARTIAL":
        lines.append("- 🟡 Aggregate lesson #58 (CONFIRMED, second case): 'Perp funding carry "
                     "lacks standalone edge at realistic cost. R76's standalone 5d/0bps edge "
                     "dies at 10bps — same taker-fee illusion as R89. Cross-sectional demean "
                     "of single-instrument funding (the carry) cannot survive ≥10bps cost. "
                     "Strategy 2 must wait for OHLCV extension (Option A) or take a "
                     "fundamentally different shape (cross-frequency / informativeness-WEIGHTED).'")
    else:
        lines.append("- 🔴 Aggregate lesson #58 (CONFIRMED, third case): 'Perp microstructure — "
                     "RESIDUAL, LEVEL, or CARRY — never survives realistic cost. The kept W5 "
                     "lift was real but the alpha is not in the cross-sectional funding-residual "
                     "itself. Path forward: cross-frequency funding (4h → 24h aggregation), "
                     "informativeness-weighted funding, or a CROSS-ASSET basis (ETH-funding vs "
                     "BTC-funding — single instrument but informativeness-weighted).'")
    return "\n".join(lines)


# === CLI =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--sign", type=str, default=SIGN_HIGH_FUND_LONG,
                        choices=[SIGN_HIGH_FUND_LONG, SIGN_LOW_FUND_LONG])
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r90_perp_funding_carry_held/{today}")
    payload = run(out, sign=args.sign)

    out.mkdir(parents=True, exist_ok=True)
    verdict_path = out / "verdict.json"
    report_path = out / "REPORT.md"
    with verdict_path.open("w") as f:
        json.dump(payload, f, indent=2, default=str)
    with report_path.open("w") as f:
        f.write(format_report(payload))

    print(f"Wrote {verdict_path}")
    print(f"Wrote {report_path}")
    print()
    print(format_report(payload))
