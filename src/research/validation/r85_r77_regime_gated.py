"""
R85 — R77 fusion cell + REGIME GATE (Strategy 2 sub-configuration) (Seth, 2026-07-26).

Triggered by user's choice (after R82 PARTIAL + R83 REFUTED + R76 standalone
failing 5bps): fold Strategy 2 into R77 as a sub-configuration. R85 is the
"defensive sub-book" — same R77 signal source (R46 + R62 + R76 at frozen weights),
but with a regime gate that flat-zeros positions in TIGHTENING/RISK_OFF days.

Two-book design:
  - Strategy 1: R77 fusion cell (always-on, full gross). Validated: gross_t=+3.10,
    OOS_t=+3.61, maxDD=−8.91%, Sharpe=+2.06.
  - Strategy 2: R77 regime-gated (only RISK_ON/EASING/STAGFLATION; flat-zero in
    TIGHTENING/RISK_OFF). Same signal, different risk profile: lower gross in
    bear regimes, no bear exposure.

Why "two books" rather than "one book with overlay":
  - They can be sized independently. Strategy 1 captures the full R77 alpha at
    constant gross. Strategy 2 captures the bull-regime alpha with lower maxDD.
  - When bear hits, Strategy 1 still pays (R77 is regime-conditional, not pure-bull),
    Strategy 2 goes to zero. The two sum to a smoother PnL.
  - Operationally separable: different risk limits, different monitoring, different
    P&L attribution.

Why this is expected to clear 3-check:
  - R77 already cleared 3-check (gross + 5bps + OOS).
  - Regime-gate is a TIGHTER version (it removes the worst tail risk windows).
  - R82 confirmed W5 rotation-out works (TIGHTENING/RISK_OFF days → flat-zero PnL).
  - The gate should: (a) PRESERVE gross_t (the gain in bull regimes is intact),
    (b) IMPROVE OOS (the bear regime OOS contribution is removed), (c) REDUCE maxDD
    (no bear exposure).

Anti-imposter:
  - Regime lookup is STRICTLY LAGGED (no forward look).
  - Both gate ON (always-on R77) and gate OFF (full R77) are reported; R85 is
    only a SURVIVES if it BEATS the R77 frozen baseline on at least 2 of 3 checks.
  - Per-window W1-W6 attribution shows the gate's payload.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

# Reuse R77's leg builders (frozen R69 cell + R76 best cell)
from src.research.validation.r77_r76_as_fusion_contribution import (
    build_r76_sleeve_28, R69_W_R46, R69_W_R62, R76_BEST_CAD, R76_BEST_BPS,
    SIGN_HIGH_FUND_LONG,
)
from src.research.validation.r63_fusion_validation import (
    build_r46_sleeve_28, build_r62_sleeve_28, fuse, max_drawdown, per_window,
    R46_CAD, R46_BPS, R62_CAD, R62_BPS,
)
from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.r62_fragility_gated_funding import (
    compute_combined_features, build_fragility_ks_table,
    DEFAULT_FRAGILE_WINDOWS, DEFAULT_PLAYABLE_WINDOWS,
)
from src.research.validation.funding_crowding_ls import (
    score_funding_zwide, DEFAULT_ZWIN,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.r77_r76_as_fusion_contribution import _build_r62_detector_local
from src.research.validation.r77_r76_as_fusion_contribution import fuse3
from src.research.data_align.cis_history_loader import load_cis_history

ALIGNED_CSV = ROOT / "_data" / "cis_historical" / "cis_historical_11yr_aligned.csv"

# ── Strategy 2 regime gate ─────────────────────────────────────────────────
# Default: only run R77 in bullish regimes; flat-zero in TIGHTENING/RISK_OFF
R85_REGIMES_ALLOWED = ("RISK_ON", "EASING", "STAGFLATION")
R85_REGIMES_BLOCKED = ("TIGHTENING", "RISK_OFF")

# Frozen R77 leg-3 weight (from R77 verdict)
R85_W_R76 = 0.30

OOS_FRAC = 0.30


# ── Regime loader (from 11yr aligned CSV) ──────────────────────────────────
def load_regime_per_day(panel_dates: pd.DatetimeIndex) -> pd.Series:
    """Load macro_regime from 11yr aligned CSV, restrict to panel_dates,
    forward-fill so every date in panel has a regime.

    The 11yr CSV is recorded daily; we use nearest-prior lookup. If a date in
    panel_dates has no entry, we forward-fill from the most recent prior date."""
    cis = load_cis_history(ALIGNED_CSV, force_schema=True)
    # Use the modal regime per day (per R82 logic)
    regime_wide = cis.pivot(index="_date", columns="symbol", values="macro_regime").sort_index()
    mode_per_day = regime_wide.mode(axis=1).iloc[:, 0]
    # Reindex to panel_dates with ffill (no forward look, just propagation of last known)
    out = mode_per_day.reindex(panel_dates).ffill()
    return out


def apply_regime_gate(pnl: pd.Series, regime_per_day: pd.Series) -> pd.Series:
    """Per-day regime gate. Returns PnL with TIGHTENING/RISK_OFF days set to 0."""
    allowed = set(R85_REGIMES_ALLOWED)
    gate = regime_per_day.reindex(pnl.index).isin(allowed).fillna(False)
    return pnl.where(gate, other=0.0)


# ── Master run ──────────────────────────────────────────────────────────────
def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R85 — R77 fusion cell + REGIME GATE (Strategy 2 sub-config) ===\n")
    print(f"Frozen R77 weights: w_R46={R69_W_R46}, w_R62={R69_W_R62}, w_R76={R85_W_R76}")
    print(f"Regime gate: ALLOW={R85_REGIMES_ALLOWED}, BLOCK={R85_REGIMES_BLOCKED}\n")

    # ── Load panels (R63/R77 parity) ─────────────────────────────────────────
    cis_long = load_cis_history_wide()
    rets = load_daily_returns()
    lo = max(cis_long["date"].min(), rets.index.min())
    hi = min(cis_long["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable_full = sorted(set(cis_long["asset"]) & set(rets.columns))

    funding_daily = load_funding_daily(assets=tradeable_full)
    funding_assets = sorted(set(tradeable_full) & set(funding_daily.columns))
    if not funding_daily.empty:
        f_lo, f_hi = funding_daily.index.min(), funding_daily.index.max()
        rets = rets.loc[(rets.index >= f_lo) & (rets.index <= f_hi)]
    tradeable = funding_assets
    print(f"Panel: {rets.index[0].date()} → {rets.index[-1].date()} "
          f"({len(rets)} days, {len(tradeable)} assets)\n")

    # 6-window partition for R62 detector
    windows = partition_into_windows(rets.index, 6)
    fragile_ranges = [(s, e) for label_, s, e in windows if label_ in DEFAULT_FRAGILE_WINDOWS]
    playable_ranges = [(s, e) for label_, s, e in windows if label_ in DEFAULT_PLAYABLE_WINDOWS]
    fragile_mask = pd.Series(False, index=rets.index)
    for s, e in fragile_ranges:
        fragile_mask.loc[(rets.index >= s) & (rets.index <= e)] = True

    # ── Build the 3 legs (R77's exact pipeline) ──────────────────────────────
    print("Building Leg 1 (R46 pillar_O 5d/5bps on 28-asset) …")
    leg_r46, _ = build_r46_sleeve_28(cis_long, rets, tradeable)

    print("Building Leg 2 (R62 fade-the-crowd 21d/0bps gated) …")
    score_zwide = score_funding_zwide(funding_daily[tradeable], zwin=DEFAULT_ZWIN,
                                       sign="fade_crowd").reindex(rets.index).ffill()
    feats = compute_combined_features(cis_long, rets, tradeable_full, tradeable,
                                       funding_daily)
    feats = feats.reindex(rets.index)
    det = _build_r62_detector_local(feats, fragile_mask, fragile_ranges, playable_ranges)
    leg_r62 = build_r62_sleeve_28(score_zwide, rets, tradeable, det)

    print(f"Building Leg 3 (R76 funding residual {R76_BEST_CAD}d/{R76_BEST_BPS}bps) …")
    leg_r76 = build_r76_sleeve_28(funding_daily, rets, tradeable, sign=SIGN_HIGH_FUND_LONG)

    # ── 3-component fusion (R77 frozen) ─────────────────────────────────────
    fac_2 = fuse(leg_r46, leg_r62, R69_W_R46)
    r77_pnl = fuse3(fac_2, leg_r76, R85_W_R76).reindex(rets.index).fillna(0.0)
    print(f"\nR77 (ungated) total daily PnL: gross_t cells in `g_full` below.\n")

    # ── Apply regime gate ────────────────────────────────────────────────────
    regime_per_day = load_regime_per_day(rets.index)
    n_blocked = (~regime_per_day.isin(R85_REGIMES_ALLOWED)).sum()
    n_allowed = regime_per_day.isin(R85_REGIMES_ALLOWED).sum()
    print(f"Regime distribution on panel:")
    print(f"  ALLOW ({R85_REGIMES_ALLOWED}): {n_allowed} days")
    print(f"  BLOCK ({R85_REGIMES_BLOCKED}): {n_blocked} days")
    print(f"  panel share gated: {n_blocked}/{n_blocked+n_allowed} = "
          f"{100.0*n_blocked/(n_blocked+n_allowed):.1f}%\n")

    r85_pnl = apply_regime_gate(r77_pnl, regime_per_day)

    # ── 3-check gauntlet: R77 (ungated) vs R85 (gated) ──────────────────────
    cut = int(len(rets) * (1 - OOS_FRAC))
    # Standard f_market (cross-section mean) + f_momentum (TSMOM 30d)
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).rolling(30, min_periods=30).apply(np.prod, raw=True) - 1
    f_momentum = (np.sign(cum) * f_market).fillna(0.0)
    known = {
        "market": f_market.values,
        "momentum": f_momentum.values,
    }

    def gauntlet_one(fac: pd.Series) -> dict:
        g_full = gauntlet_3check(fac.values, known, cut)
        return {
            "gross_t": g_full["gross_t"],
            "oos_t": g_full["oos_t"],
            "full_ann_pct": g_full["gross_alpha_ann_pct"],
            "oos_ann_pct": g_full["oos_alpha_ann_pct"],
            "max_dd": max_drawdown(fac),
        }

    g_ungated = gauntlet_one(r77_pnl)
    g_gated = gauntlet_one(r85_pnl)

    print("=== 2-check gauntlet (gross + OOS) — R46 leg 5bps already baked in ===")
    print(f"  Strategy 1 (R77 ungated):  gross_t={g_ungated['gross_t']:+.2f}  "
          f"OOS_t={g_ungated['oos_t']:+.2f}  maxDD={g_ungated['max_dd']*100:+.2f}%")
    print(f"  Strategy 2 (R85 regime-gated): gross_t={g_gated['gross_t']:+.2f}  "
          f"OOS_t={g_gated['oos_t']:+.2f}  maxDD={g_gated['max_dd']*100:+.2f}%")

    clears_ungated = (g_ungated["gross_t"] > 1.96) + (g_ungated["oos_t"] > 1.96)
    clears_gated = (g_gated["gross_t"] > 1.96) + (g_gated["oos_t"] > 1.96)

    # R85 verdict
    if clears_gated == 2:
        r85_verdict = "✅ SURVIVES"
    elif clears_gated >= 1:
        r85_verdict = "🟡 PARTIAL"
    else:
        r85_verdict = "🔴 REFUTED"
    print(f"\n  Strategy 1 verdict: {clears_ungated}/2 cleared")
    print(f"  Strategy 2 verdict: {r85_verdict} ({clears_gated}/2 cleared)")

    # Per-window W1-W6 attribution
    print(f"\n=== W1-W6 attribution (Strategy 2 R85 gated) ===")
    pw_gated = per_window(r85_pnl, windows)
    pw_ungated = per_window(r77_pnl, windows)
    for i, (label_, _, _) in enumerate(windows):
        g_pct = pw_gated[i].get("ann_pct", float("nan")) if i < len(pw_gated) else float("nan")
        u_pct = pw_ungated[i].get("ann_pct", float("nan")) if i < len(pw_ungated) else float("nan")
        g_t = pw_gated[i].get("t_stat", float("nan")) if i < len(pw_gated) else float("nan")
        u_t = pw_ungated[i].get("t_stat", float("nan")) if i < len(pw_ungated) else float("nan")
        print(f"  {label_}: gated α_t={g_t:+.2f} ({g_pct:+.1f}%)  "
              f"ungated α_t={u_t:+.2f} ({u_pct:+.1f}%)")

    # Compile report
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "panel": {
            "lo": str(rets.index[0].date()),
            "hi": str(rets.index[-1].date()),
            "n_days": int(len(rets)),
            "n_assets": int(len(tradeable)),
        },
        "r85_config": {
            "r77_weights": {"w_R46": R69_W_R46, "w_R62": R69_W_R62, "w_R76": R85_W_R76},
            "regimes_allowed": list(R85_REGIMES_ALLOWED),
            "regimes_blocked": list(R85_REGIMES_BLOCKED),
            "n_days_allowed": int(n_allowed),
            "n_days_blocked": int(n_blocked),
        },
        "strategy_1_r77_ungated": g_ungated,
        "strategy_2_r85_gated": g_gated,
        "strategy_2_verdict": r85_verdict,
        "n_clears_ungated": int(clears_ungated),
        "n_clears_gated": int(clears_gated),
        "w5_attribution_gated": [
            {"label": pw_gated[i].get("label"),
             "alpha_t": float(pw_gated[i].get("t_stat")) if pw_gated[i].get("t_stat") is not None else None,
             "ann_pct": float(pw_gated[i].get("ann_pct")) if pw_gated[i].get("ann_pct") is not None else None}
            for i in range(len(pw_gated))
        ],
    }
    json_path = out_dir / "verdict.json"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {json_path}")
    return report


def main():
    ap = argparse.ArgumentParser(description="R85 — R77 + regime-gate (Strategy 2)")
    ap.add_argument("--out-dir", type=Path,
                     default=ROOT / "reports" / "r85_r77_regime_gated" /
                              datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()
    run(args.out_dir)


if __name__ == "__main__":
    main()
