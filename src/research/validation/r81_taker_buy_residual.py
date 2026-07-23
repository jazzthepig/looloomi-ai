"""
R81 — Taker buy ratio residual (cross-sectional demean of trailing-30d taker-buy-ratio)
on the price-flow axis (Seth, 2026-07-24).

Per R80 lesson #43 v3 (REFUTED 2026-07-24): cross-sectional demean of single-class
microstructure axes (funding, momentum, vol, turnover) MOSTLY LACK EDGE; only R76
funding residual survives. User direction 2026-07-24: "不做费率相关的" (don't do
rate-related) → pivot to NON-rate axes.

R81 opens orthogonal candidate #5 on the **PRICE-FLOW axis** (NON-rate): taker-buy
ratio residual = mean_30d(taker_buy_quote / volume_quote) −
mean_a(mean_30d(taker_buy_quote / volume_quote)).

Taker-buy ratio captures ORDER-FLOW IMBALANCE — which assets have aggressive buyers
(taker-buys) vs aggressive sellers (taker-sells) dominating the day's flow. This
is a structurally different signal from R46/R62/R76/R78/R79/R80:
  · R46 — CIS-quality multi-pillar rank
  · R62 — absolute funding-z crowding (RATE)
  · R76 — funding residual (RATE)
  · R78 — TSMOM cross-sectional demean (TREND)
  · R79 — realized vol residual (VOL)
  · R80 — turnover residual (ACTIVITY/FLOW)
  · R81 — taker-buy ratio residual (ORDER-FLOW IMBALANCE) ← NEW

Taker-buy ratio is a price-flow axis: it's about WHO initiated the trade, not
the price level, momentum, vol, or funding. It captures informed-flow pressure
(aggressive buyers = informed flow is positive for that asset).

R81 design:
  · Universe: A-S1 24-symbol panel (`_data/strategy_revive/{sym}_1d_ohlcv.csv`),
    2025-01-01 → 2026-07-18 (~563 days). This is the ONLY available panel with
    taker-buy data. Smaller and shorter than the 28-asset 731-day panel used by
    R46/R62/R76/R78.
  · Score: tafi_residual[t, a] = mean_30d(taker_buy_ratio[t, a]) −
    mean_a(mean_30d(taker_buy_ratio[t, a])).
  · k_terciles = 3.
  · Cadences {1,3,5,7,14,21}d × costs {0,5,10}bps.
  · 3-check gauntlet: gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96.
  · Per-window W1-W6 attribution.
  · Both signs run; matched-cell sign verdict.

**GATE TEST N/A — IMPORTANT.** The leg-correlation gate (lesson #42) tests if
R81's leg is orthogonal to existing fusion legs R46/R62/R76/R78. R46/R62/R76/R78
were built on the 28-asset 731-day panel; R81 is on the A-S1 24-symbol 563-day
panel. The legs are STRUCTURALLY NOT COMPARABLE (different universes, different
windows). Gate is marked N/A in the verdict payload.

**Implication:** R81 is a STANDALONE gauntlet test on the A-S1 universe. If it
survives, the next step is "extend taker-buy to the 28-asset panel by fetching
taker-buy for the wider universe" — out of scope for R81. If it refutes, the
finding still informs R82+ candidate generation (the price-flow axis may be
exhausted too).

Anti-imposter:
  - Taker-buy ratio is structurally different from funding (RATE), turnover
    (ACTIVITY), vol (DISPERSION), TSMOM (TREND), CIS quality (FUNDAMENTAL).
  - Pre-test leg-correlation gate is MANDATORY (lesson #42) — but unavailable
    due to panel mismatch (R81 panel ≠ fusion-cell panel). Documented honestly.
  - The R77 fusion-cell (R46+R62+R76 at w_R46=0.25, w_R62=0.75, w_R76=0.30) is
    FROZEN. R81 does NOT touch it.
  - R81 ships no production change regardless of verdict.

Verdict grammar:
  · ✅ SURVIVES — clears 3-check on A-S1 universe. Standalone-eligible; fusion-
    eligibility requires extension to 28-asset panel.
  · 🔴 REFUTED — fails 3-check. Lesson #43 v3 deepens: PRICE-FLOW axis (taker-
    buy residual) also lacks standalone edge. The cross-sectional demean of any
    single-class microstructure/price axis mostly lacks edge on this universe.
    Future orthogonal candidates must reach for STRUCTURALLY DIFFERENT sources
    (cross-asset, cross-frequency, cross-section-of-cross-section).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.cis_quality_robustness import (
    estimate_turnover_ann,
)
from src.research.validation.funding_crowding_ls import (
    DEFAULT_CADENCES, DEFAULT_COST_GRID,
)
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.r73_pillar_a_level_ls import (
    pillar_a_level_ls, SIGN_HIGH_A_LONG,
)


# === Constants ================================================================
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# R81-specific
R81_K_TERCILES = 3                    # R46/R76 standard
R81_MIN_TRADEABLE = 12                # same floor as R73/R76/R78/R79/R80
R81_TAFI_LOOKBACK = 30                # days; trailing mean window
R81_TAFI_MIN_OBS = 5                  # min observations for stable mean
A_S1_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/strategy_revive")


def _discover_a_s1_symbols(a_s1_dir: Path = A_S1_DIR) -> list[str]:
    """Discover available A-S1 symbols by scanning the data directory.

    Honest: derive the universe from actual CSVs, not a hardcoded list. As of
    2026-07-24, the directory holds 24 symbol CSVs (BTC, ETH, SOL, ...).
    """
    if not a_s1_dir.exists():
        return []
    return sorted(p.stem.replace("_1d_ohlcv", "")
                  for p in a_s1_dir.glob("*_1d_ohlcv.csv"))


A_S1_SYMBOLS = _discover_a_s1_symbols()
assert len(A_S1_SYMBOLS) >= 20, \
    f"Expected >=20 A-S1 symbols, got {len(A_S1_SYMBOLS)} — data dir anomaly"

# Sign constants
SIGN_HIGH_TAFI_LONG = "high_tafi_long"   # long assets with above-mean taker-buy ratio (buy-pressure)
SIGN_LOW_TAFI_LONG = "low_tafi_long"     # long assets with below-mean taker-buy ratio (sell-pressure)
_VALID_SIGNS = {SIGN_HIGH_TAFI_LONG, SIGN_LOW_TAFI_LONG}


# === Load: daily taker-buy ratio ==============================================
def load_daily_taker_buy_ratio(a_s1_dir: Path = A_S1_DIR) -> pd.DataFrame:
    """Load A-S1 24-symbol CSVs → daily taker-buy ratio = taker_buy_quote / volume_quote.

    Returns wide DataFrame (date × asset). NaN behavior: assets with no parquet
    are absent from the output. Days where either taker_buy_quote or volume_quote
    is NaN/zero are dropped (I1 invariant — never impute 0/0.5, which would
    misrepresent the buy-side pressure).
    """
    symbols = _discover_a_s1_symbols(a_s1_dir)
    all_ratios = {}
    for sym in symbols:
        f = a_s1_dir / f"{sym}_1d_ohlcv.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f)
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        # Drop rows with missing taker_buy_quote or volume_quote
        df = df.dropna(subset=["taker_buy_quote", "volume_quote"])
        # Compute taker-buy ratio = buy_quote / total_quote
        df["taker_buy_ratio"] = np.where(
            df["volume_quote"] > 0,
            df["taker_buy_quote"] / df["volume_quote"],
            np.nan,
        )
        # Drop zero-volume days (would divide by zero)
        df = df.dropna(subset=["taker_buy_ratio"])
        daily = df.groupby("date")["taker_buy_ratio"].last().sort_index()
        all_ratios[sym] = daily
    return pd.DataFrame(all_ratios)


# === Score: taker-buy ratio residual ==========================================
def score_taker_buy_residual(taker_buy_ratio: pd.DataFrame, tradeable: list,
                              lookback: int = R81_TAFI_LOOKBACK,
                              min_obs: int | None = None) -> pd.DataFrame:
    """Cross-sectionally demeaned trailing-30d taker-buy-ratio mean.

    tafi_30[t, a] = mean of taker_buy_ratio over the trailing `lookback` days.
    tafi_residual[t, a] = tafi_30[t, a] − mean_a(tafi_30[t, a]).

    The residual is RELATIVE order-flow imbalance — which assets have above-mean
    buy-side pressure on this date vs the universe.

    NaN behavior (I1):
      - Warmup rows (< min_periods): NaN, NOT zero.
      - Insufficient obs in window for an asset at a given t: NaN, NOT 0.
      - Cross-section demean uses dropna(how="any"): rows where ANY asset is
        NaN are excluded from the mean computation.
    """
    if min_obs is None:
        min_obs = lookback
    sub = taker_buy_ratio[tradeable].copy()
    # Trailing rolling mean; min_periods gates the warmup-period estimate.
    tafi_30 = sub.rolling(lookback, min_periods=min_obs).mean()
    # Cross-sectional demean at each t — only on fully-observed rows.
    fully_observed = tafi_30.dropna(how="any")
    demeaned_full = fully_observed.subtract(fully_observed.mean(axis=1), axis=0)
    residual = demeaned_full.reindex(tafi_30.index)
    return residual


# === L/S core (reuses R73's pillar_a_level_ls signature for parity) ==========
def taker_buy_residual_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
                            k_terciles: int = R81_K_TERCILES,
                            cost_bps: float = 0.0,
                            rebal_days: int = 1,
                            sign: str = SIGN_HIGH_TAFI_LONG) -> pd.Series:
    """Long high-tafi-residual / short low-tafi-residual (or reversed under SIGN_LOW_TAFI_LONG).

    Reuses R73's pillar_a_level_ls as the L/S engine — score function differs
    (taker-buy residual vs pillar_A level vs funding residual vs TSMOM vs vol
    residual vs turnover residual) but L/S logic is the same: long top tercile,
    short bottom tercile, optional sign flip.
    """
    if sign not in _VALID_SIGNS:
        raise ValueError(f"sign must be one of {_VALID_SIGNS}, got {sign!r}")
    flipped = -score_wide if sign == SIGN_LOW_TAFI_LONG else score_wide
    return pillar_a_level_ls(flipped, rets, k_terciles=k_terciles,
                              cost_bps=cost_bps, rebal_days=rebal_days,
                              sign=SIGN_HIGH_A_LONG)


# === Run =====================================================================
def run(out_dir: Path,
        cadences: tuple = DEFAULT_CADENCES,
        cost_grid: tuple = DEFAULT_COST_GRID,
        sign: str = SIGN_HIGH_TAFI_LONG) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R81 — Taker buy ratio residual (30d rolling-mean taker-buy ratio "
          f"cross-sectional demean) L/S (sign={sign}, k={R81_K_TERCILES}) ===\n")

    # ── Load A-S1 panel ───────────────────────────────────────────────────────
    print("Loading A-S1 24-symbol taker-buy ratio panel …")
    tafi = load_daily_taker_buy_ratio()
    tafi_assets = sorted(tafi.columns.tolist())
    print(f"  Taker-buy ratio: {tafi.shape[0]} days × {tafi.shape[1]} assets")

    # Compute returns from the same CSVs (close prices)
    print("Computing daily returns from A-S1 close prices …")
    all_rets = {}
    symbols_runtime = _discover_a_s1_symbols()
    for sym in symbols_runtime:
        f = A_S1_DIR / f"{sym}_1d_ohlcv.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f)
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        daily = df.groupby("date")["close"].last().sort_index()
        all_rets[sym] = daily.pct_change()
    rets = pd.DataFrame(all_rets)
    print(f"  Returns: {rets.shape[0]} days × {rets.shape[1]} assets")

    # Align to taker-buy ratio availability
    lo = max(tafi.index.min(), rets.index.min())
    hi = min(tafi.index.max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tafi = tafi.loc[(tafi.index >= lo) & (tafi.index <= hi)]
    print(f"Aligned panel: {lo.date()} → {hi.date()} ({len(rets)} days)\n")

    # Strict intersection: assets with both taker-buy AND returns
    tradeable = sorted(set(tafi_assets) & set(rets.columns))
    print(f"Strict intersection universe: {len(tradeable)} assets")
    if len(tradeable) < R81_MIN_TRADEABLE:
        raise RuntimeError(
            f"Universe too small: {len(tradeable)} < {R81_MIN_TRADEABLE} "
            f"(R81_MIN_TRADEABLE floor). R81 refuses to silently widen.")

    # ── Score: taker-buy ratio residual ──────────────────────────────────────
    print("Computing taker-buy ratio residual (30d rolling-mean cross-sectional demean) …")
    score_tafi_wide = score_taker_buy_residual(tafi, tradeable)
    score_tafi_wide = score_tafi_wide.reindex(rets.index).ffill()
    print(f"  Score shape: {score_tafi_wide.shape}, "
          f"mean (post-warmup) = {score_tafi_wide.mean().mean():.6f} "
          f"(should be ~0 by construction), "
          f"std (post-warmup) = {score_tafi_wide.std().mean():.6f}")

    # ── 6-window partition (R46/R76 parity) ──────────────────────────────────
    windows = partition_into_windows(rets.index, 6)

    # ── Build R81 leg at default cadence (3d/0bps — mirrors R73 best cell) ───
    best_cad = 3
    leg_r81 = taker_buy_residual_ls(score_tafi_wide, rets[tradeable],
                                     k_terciles=R81_K_TERCILES, cost_bps=0.0,
                                     rebal_days=best_cad, sign=sign)
    leg_r81 = leg_r81.reindex(rets.index).fillna(0.0)

    # ── Known factors + OOS cut (R46/R76 parity) ─────────────────────────────
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}
    cut = int(len(rets) * (1.0 - OOS_FRAC))

    # ── Per-leg gauntlet ────────────────────────────────────────────────────
    g_r81 = gauntlet_3check(leg_r81.values, known_full, cut)
    print(f"Leg R81 ({best_cad}d/0bps): gross_t={g_r81['gross_t']:+.2f}, "
          f"OOS_t={g_r81['oos_t']:+.2f}, pass_all={g_r81['passes_all']}\n")

    # ── Sweep cadences × costs (both signs; matched-cell sign verdict) ──────
    print(f"══ Cadence × cost sweep (signs: {SIGN_HIGH_TAFI_LONG}, {SIGN_LOW_TAFI_LONG}) ══\n")
    sweep_hi = {}
    sweep_lo = {}
    for cad in cadences:
        for bps in cost_grid:
            fac_hi = taker_buy_residual_ls(score_tafi_wide, rets[tradeable],
                                            k_terciles=R81_K_TERCILES, cost_bps=bps,
                                            rebal_days=cad, sign=SIGN_HIGH_TAFI_LONG)
            fac_hi = fac_hi.reindex(rets.index).fillna(0.0)
            g_hi = gauntlet_3check(fac_hi.values, known_full, cut)
            sweep_hi[(cad, bps)] = {
                "alpha_t": g_hi["gross_t"], "oos_t": g_hi["oos_t"],
                "passes_gross": g_hi["passes_gross"], "passes_oos": g_hi["passes_oos"],
                "passes_all": g_hi["passes_all"],
            }
            fac_lo = taker_buy_residual_ls(score_tafi_wide, rets[tradeable],
                                            k_terciles=R81_K_TERCILES, cost_bps=bps,
                                            rebal_days=cad, sign=SIGN_LOW_TAFI_LONG)
            fac_lo = fac_lo.reindex(rets.index).fillna(0.0)
            g_lo = gauntlet_3check(fac_lo.values, known_full, cut)
            sweep_lo[(cad, bps)] = {
                "alpha_t": g_lo["gross_t"], "oos_t": g_lo["oos_t"],
                "passes_gross": g_lo["passes_gross"], "passes_oos": g_lo["passes_oos"],
                "passes_all": g_lo["passes_all"],
            }

    # ── Matched-cell sign audit (anti-imposter) ──────────────────────────────
    print("══ Matched-cell sign audit (anti-imposter) ══\n")
    matched_diffs = []
    for cad in cadences:
        for bps in cost_grid:
            hi_entry = sweep_hi[(cad, bps)]
            lo_entry = sweep_lo[(cad, bps)]
            diff = hi_entry["alpha_t"] - lo_entry["alpha_t"]
            matched_diffs.append((cad, bps, diff, hi_entry["alpha_t"], lo_entry["alpha_t"]))
    matched_diffs.sort(key=lambda x: -x[2])
    print("Top-3 matched-cell differentials (sign audit):")
    for cad, bps, diff, hi_t, lo_t in matched_diffs[:3]:
        print(f"  cad={cad:>2}d bps={bps:>4.1f}: Δ(α_t) = {diff:+.2f} "
              f"(hi={hi_t:+.2f}, lo={lo_t:+.2f})")
    pos_count = sum(1 for _, _, diff, _, _ in matched_diffs[:3] if diff > 0)
    neg_count = sum(1 for _, _, diff, _, _ in matched_diffs[:3] if diff < 0)
    sign_verdict = "high_tafi_long" if pos_count >= 2 else ("low_tafi_long" if neg_count >= 2 else "mixed")
    print(f"Sign verdict (top-3 majority): **{sign_verdict}**\n")

    # ── Sweep summary: best cell by pass + alpha + OOS ───────────────────────
    print("══ Sweep summary (best cell per sign) ══\n")
    viable_hi = [(k, v) for k, v in sweep_hi.items() if v["passes_all"]]
    viable_lo = [(k, v) for k, v in sweep_lo.items() if v["passes_all"]]
    best_hi = max(viable_hi, key=lambda kv: kv[1]["alpha_t"]) if viable_hi else (None, None)
    best_lo = max(viable_lo, key=lambda kv: kv[1]["alpha_t"]) if viable_lo else (None, None)
    if best_hi[0]:
        cad, bps = best_hi[0]
        v = best_hi[1]
        print(f"Best SIGN_HIGH_TAFI_LONG cell: {cad}d/{bps}bps, α_t={v['alpha_t']:+.2f}, "
              f"OOS_t={v['oos_t']:+.2f}")
    if best_lo[0]:
        cad, bps = best_lo[0]
        v = best_lo[1]
        print(f"Best SIGN_LOW_TAFI_LONG  cell: {cad}d/{bps}bps, α_t={v['alpha_t']:+.2f}, "
              f"OOS_t={v['oos_t']:+.2f}")
    if not viable_hi and not viable_lo:
        print("⚠ NO cell passes 3-check — R81 likely REFUTED.\n")
    else:
        print()

    # ── Final verdict ────────────────────────────────────────────────────────
    passes_3check = g_r81["passes_all"]
    if passes_3check:
        verdict = ("✅ SURVIVES — clears 3-check on A-S1 universe; "
                   "standalone-eligible; fusion-eligibility requires extension to "
                   "28-asset panel (out of scope for R81).")
        verdict_band = "SURVIVES"
    else:
        verdict = ("🔴 REFUTED — fails 3-check; lesson #43 v3 deepens: PRICE-FLOW "
                   "axis (taker-buy residual) also lacks standalone edge. The "
                   "cross-sectional demean of any single-class microstructure/price "
                   "axis mostly lacks edge on this universe. Future orthogonal "
                   "candidates must reach for STRUCTURALLY DIFFERENT sources.")
        verdict_band = "REFUTED"
    print(f"VERDICT: {verdict}\n")

    # ── Per-window W1-W6 attribution ─────────────────────────────────────────
    from src.research.validation.r63_fusion_validation import per_window, max_drawdown
    dd_r81 = max_drawdown(leg_r81)
    pw_r81 = per_window(leg_r81, windows)
    print(f"R81 maxDD: {dd_r81:+.2%}")
    print(f"R81 per-window (best-cad {best_cad}d/0bps, sign={sign}):")
    for label_ in sorted(pw_r81.keys()):
        ann_pct = pw_r81[label_]["ann_pct"]
        n = pw_r81[label_]["n_days"]
        print(f"  {label_}: {ann_pct:+.1f}% (n={n})")

    # ── Persist out ──────────────────────────────────────────────────────────
    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets_intersection": len(tradeable),
                  "matched_assets": tradeable, "panel_source": "A-S1 24-symbol"},
        "panel_mismatch_note": (
            "R81 uses A-S1 24-symbol 563-day panel (2025-01-01 → 2026-07-18). "
            "R46/R62/R76/R78 used 28-asset 731-day panel (2024-06-07 → 2026-06-07). "
            "The leg-correlation gate (lesson #42) is N/A because legs built on "
            "different panels are structurally not comparable. R81 is a STANDALONE "
            "gauntlet test on the A-S1 universe."
        ),
        "construction": {
            "score_basis": "taker_buy_residual (30d rolling-mean taker-buy ratio cross-sectional demean)",
            "tafi_lookback": R81_TAFI_LOOKBACK,
            "tafi_min_obs": R81_TAFI_MIN_OBS,
            "k_terciles": R81_K_TERCILES,
            "universe": "A-S1 24-symbol taker-buy ∩ returns",
            "cadences": list(cadences), "cost_grid": list(cost_grid),
            "default_cad": best_cad, "default_cost_bps": 0.0,
            "sign": sign,
        },
        "leg_correlation_gate": {
            "available": False,
            "reason": ("Panel mismatch — R81 uses A-S1 24-symbol 563-day panel; "
                       "R46/R62/R76/R78 use 28-asset 731-day panel. Legs are "
                       "structurally not comparable."),
        },
        "per_leg_gauntlet": {
            "leg_r81": {"gauntlet": g_r81, "default_cad": best_cad, "default_cost_bps": 0.0,
                        "max_dd": dd_r81, "per_window": pw_r81},
        },
        "sweep_high": {f"{k[0]}d_{k[1]}bps": v for k, v in sweep_hi.items()},
        "sweep_low": {f"{k[0]}d_{k[1]}bps": v for k, v in sweep_lo.items()},
        "matched_cell_sign_audit": {
            "top_3": [{"cad": c, "bps": b, "diff": d, "hi_alpha_t": h, "lo_alpha_t": l}
                       for c, b, d, h, l in matched_diffs[:3]],
            "sign_verdict": sign_verdict,
        },
        "best_cells": {
            "sign_high_tafi_long": ({"cad": best_hi[0][0], "cost_bps": best_hi[0][1],
                                      "alpha_t": best_hi[1]["alpha_t"],
                                      "oos_t": best_hi[1]["oos_t"]}
                                     if best_hi[0] else None),
            "sign_low_tafi_long": ({"cad": best_lo[0][0], "cost_bps": best_lo[0][1],
                                     "alpha_t": best_lo[1]["alpha_t"],
                                     "oos_t": best_lo[1]["oos_t"]}
                                    if best_lo[0] else None),
        },
        "verdict": {
            "band": verdict_band,
            "verdict_string": verdict,
            "passes_3check": passes_3check,
            "leg_correlation_gate_available": False,
        },
        "live_book_impact": {
            "touches_frozen_r77_cell": False,
            "r65_paper_book_unaffected": True,
            "r66_tracking_unaffected": True,
            "note": ("R81 is research-only. R82 = extend taker-buy to 28-asset panel "
                     "by fetching taker-buy for the wider universe, then re-test "
                     "with leg-correlation gate available, is the next step IF "
                     "verdict is SURVIVES."),
        },
    }
    return out


# === Format report ===========================================================
def format_report(payload: dict) -> str:
    """Human-readable R81 report."""
    lines = []
    lines.append("# R81 — Taker buy ratio residual (30d rolling-mean taker-buy ratio cross-sectional demean) L/S")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"**Panel:** {payload['panel']['lo']} → {payload['panel']['hi']} "
                 f"({payload['panel']['n_days']} days, "
                 f"{payload['panel']['n_assets_intersection']}-asset A-S1 universe)")
    lines.append("")
    lines.append("**Panel-mismatch note:** " + payload["panel_mismatch_note"])
    lines.append("")
    lines.append("## Verdict")
    v = payload["verdict"]
    lines.append(f"**{v['band']}** — {v['verdict_string']}")
    lines.append("")
    lines.append(f"- Passes 3-check: **{v['passes_3check']}**")
    lines.append(f"- Leg-correlation gate available: **{v['leg_correlation_gate_available']}** "
                 f"(panel mismatch — see note)")
    lines.append("")
    lines.append("## Per-leg gauntlet (on A-S1 universe)")
    for leg in ("leg_r81",):
        gp = payload["per_leg_gauntlet"][leg]["gauntlet"]
        lines.append(f"- **{leg}**: gross_t = {gp['gross_t']:+.2f}, "
                     f"OOS_t = {gp['oos_t']:+.2f}, pass_all = {gp['passes_all']}")
    lines.append("")
    lines.append("## Matched-cell sign audit (top-3)")
    lines.append("| cad | bps | Δ(α_t) | hi (long) | lo (short) |")
    lines.append("|---:|---:|---:|---:|---:|")
    for r in payload["matched_cell_sign_audit"]["top_3"]:
        lines.append(f"| {r['cad']} | {r['bps']} | {r['diff']:+.2f} | "
                     f"{r['hi_alpha_t']:+.2f} | {r['lo_alpha_t']:+.2f} |")
    lines.append(f"\n**Sign verdict:** `{payload['matched_cell_sign_audit']['sign_verdict']}`\n")
    lines.append("## Live book impact")
    li = payload["live_book_impact"]
    lines.append(f"- Touches frozen R77 cell: **{li['touches_frozen_r77_cell']}**")
    lines.append(f"- R65 paper book unaffected: **{li['r65_paper_book_unaffected']}**")
    lines.append(f"- R66 tracking unaffected: **{li['r66_tracking_unaffected']}**")
    lines.append(f"- Note: {li['note']}")
    lines.append("")
    lines.append("## Aggregate lesson (proposed, depends on verdict)")
    if v["band"] == "SURVIVES":
        lines.append("- ✅ Lesson #43 v3 (deepened): \"Taker-buy residual on the "
                     "price-flow axis (NON-rate) survives the gauntlet. The "
                     "rate-vs-non-rate distinction matters less than the "
                     "STRUCTURAL specificity of the signal — funding residual "
                     "(rate) and taker-buy residual (price-flow) are BOTH "
                     "informed-flow-pressure signals. Future orthogonal candidates "
                     "should focus on micro-informativeness signals "
                     "(funding, taker-buy, OI flow) not price-momentum/volume axes.\"")
    else:
        lines.append("- 🔴 Lesson #43 v3 deepens (5 cases now): \"Cross-sectional "
                     "demean of any single-class axis (rate, price-flow, vol, "
                     "trend, activity) MOSTLY LACKS EDGE on this universe. Only "
                     "R76 funding residual survives. Even the price-flow axis "
                     "(taker-buy) refutes. The gate-then-gauntlet discipline is "
                     "still the right filter, but the pool of viable candidates "
                     "is exhausted for cross-sectional demean shapes. Future "
                     "orthogonal candidates must reach for STRUCTURALLY "
                     "DIFFERENT sources (cross-asset, cross-frequency, cross-"
                     "section-of-cross-section) OR abandon the L/S cross-section "
                     "construction entirely.\"")
    lines.append("")
    return "\n".join(lines)


# === CLI =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--sign", type=str, default=SIGN_HIGH_TAFI_LONG,
                        choices=[SIGN_HIGH_TAFI_LONG, SIGN_LOW_TAFI_LONG])
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r81_taker_buy_residual/{today}")
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
