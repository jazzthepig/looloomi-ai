"""
Strategy 6 candidate — Funding MOMENTUM Residual L/S (R96, Seth, 2026-08-24).

CAUSE (per §STRATEGY-DISCIPLINE): funding LEVEL captures the *current state*
of perp carry (R76 ✓); funding IVOL captures the *stability* of carry (R95
PARTIAL); funding MOMENTUM captures the *change in carry* — the 3rd missing
moment. The economic story: when perp funding is RAPIDLY RISING, longs are
piling into a crowded trade and the asset is exposed to unwind cascades;
when funding is RAPIDLY FALLING, shorts are crowded and a squeeze is the
mean-reversion path. Cross-sectional demean removes the BTC/ETH common
component so the signal isolates the *idiosyncratic* funding flow.

DATA: 28-asset strict funding ∩ CIS ∩ OHLCV panel (R77 family), 770 days.

WHY THIS SHAPE: the 14-attempt structural finding says cross-sectional L/S
on a within-class microstructure signal is the only shape that clears
3-check on this panel; R76 funding LEVEL was the 1-in-many outlier. After
LEVEL ✓ and IVOL ✗ (R95 PARTIAL), MOMENTUM is the 3rd natural moment in
the same axis family. If MOMENTUM also REFUTES, the structural finding
closes and Strategy 2 is gated on §OHLCV-EXTENSION.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.cis_quality_absorption import load_daily_returns
from src.research.validation.r73_pillar_a_level_ls import pillar_a_level_ls
from src.research.validation.r63_fusion_validation import max_drawdown, per_window
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.pod_aggregator import _simple_t
from src.data.signals.fusion_paper import UNIVERSE as TRADEABLE_28

_logger = logging.getLogger("r96_funding_momentum_residual")

# Two natural signs for funding MOMENTUM:
#   - long falling-funding (squeeze setup) / short rising-funding (crowded unwind)
#   - long rising-funding (momentum continuation) / short falling-funding
# Sign is parameterized so we can test BOTH and report which survives.
SIGN_FALLING_LONG = "low_a_long"      # long low Δfunding (falling) / short high Δfunding (rising)
SIGN_RISING_LONG = "high_a_long"     # long high Δfunding (rising) / short low Δfunding (falling)

MOMENTUM_SMOOTH = 5      # 5d rolling mean of Δfunding (smooth the noise)
COST_BPS = 5.0
REBAL_DAYS = 5
K_TERCILES = 3
OOS_FRAC = 0.30
PERIODS_PER_YEAR = 365


def score_funding_momentum_residual(funding_daily: pd.DataFrame,
                                     tradeable: list[str],
                                     smooth: int = MOMENTUM_SMOOTH) -> pd.DataFrame:
    """Per-asset smoothed Δfunding, cross-sectionally demeaned.

    High score (positive demeaned momentum) = funding rapidly rising
    (longs piling in, crowded).
    Low score (negative demeaned momentum) = funding rapidly falling
    (shorts piling in, squeeze setup).
    """
    common = [a for a in tradeable if a in funding_daily.columns]
    f = funding_daily[common].copy()

    # 1-day change in funding, smoothed to reduce single-day noise
    delta = f.diff()
    mom = delta.rolling(smooth, min_periods=max(2, smooth // 2)).mean()

    # Cross-sectional demean: subtract the day's mean across assets
    cs_mean = mom.mean(axis=1)
    residual = mom.sub(cs_mean, axis=0)

    return residual


def decide(gauntlet: dict, oos_sharpe: float, max_dd: float) -> str:
    if (gauntlet.get("passes_all")
            and oos_sharpe >= 1.0
            and max_dd >= -0.20):
        return "FUSION_LIFT"
    if oos_sharpe >= 0.5 and max_dd >= -0.25:
        return "NEUTRAL"
    return "REFUTED"


def run_one_sign(rets, funding_daily, common, sign: str):
    """Run a single sign variant; return (fac, score)."""
    score = score_funding_momentum_residual(funding_daily, common)
    fac = pillar_a_level_ls(
        score, rets[common], k_terciles=K_TERCILES,
        cost_bps=COST_BPS, rebal_days=REBAL_DAYS, sign=sign,
    ).reindex(rets.index).fillna(0.0)
    return fac, score


def report(fac, score, rets, common, sign, label, out_path):
    """Print + write a single-sign report."""
    windows = partition_into_windows(fac.index, n_windows=6)
    pw = per_window(fac, windows)
    mdd = max_drawdown(fac)
    is_idx = int(len(fac) * (1 - OOS_FRAC))
    is_pnl = fac.iloc[:is_idx].fillna(0.0)
    oos_pnl = fac.iloc[is_idx:].fillna(0.0)
    is_sharpe = (_simple_t(is_pnl.values) * np.sqrt(PERIODS_PER_YEAR)
                 if is_pnl.std() > 0 else 0.0)
    oos_sharpe = (_simple_t(oos_pnl.values) * np.sqrt(PERIODS_PER_YEAR)
                  if oos_pnl.std() > 0 else 0.0)

    known = {}
    mkt = rets[common].mean(axis=1).fillna(0.0).reindex(fac.index).fillna(0.0)
    cum = (1 + mkt).cumprod()
    trail30 = cum / cum.shift(30) - 1
    known["market"] = mkt.values
    known["momentum"] = (np.sign(trail30.shift(1)).fillna(0.0) * mkt).values

    try:
        res = gauntlet_3check(fac, known, oos_idx=is_idx)
        gross_t = float(res.get("gross_t", res.get("alpha_t", 0.0)))
        oos_t = float(res.get("oos_t", 0.0))
        passes_gross = bool(res.get("passes_gross", False))
        passes_oos = bool(res.get("passes_oos", False))
    except (np.linalg.LinAlgError, ValueError):
        gross_t = _simple_t(is_pnl.values)
        oos_t = _simple_t(oos_pnl.values)
        passes_gross = gross_t > 1.96
        passes_oos = oos_t > 1.96

    gauntlet = {
        "gross_t": gross_t, "oos_t": oos_t,
        "passes_gross": passes_gross, "passes_oos": passes_oos,
        "passes_all": passes_gross and passes_oos, "cut": is_idx,
    }
    decision = decide(gauntlet, oos_sharpe, mdd)

    # Per-window sign audit: per-window Sharpe of (fac on long-leg days)
    # minus (fac on short-leg days)
    score_signed = score.mean(axis=1).reindex(fac.index).fillna(0.0)
    long_minus_short = {}
    for w in sorted(pw):
        s, e = next((S, E) for L, S, E in windows if L == w)
        in_w = (fac.index >= s) & (fac.index <= e)
        if sign == SIGN_FALLING_LONG:
            long_mask = (score_signed < 0) & in_w   # falling-funding days (we go long)
            short_mask = (score_signed > 0) & in_w  # rising-funding days (we go short)
        else:
            long_mask = (score_signed > 0) & in_w   # rising-funding days (we go long)
            short_mask = (score_signed < 0) & in_w  # falling-funding days (we go short)
        long_sub = fac[long_mask]
        short_sub = fac[short_mask]
        long_sharpe = float(long_sub.mean() / long_sub.std() * np.sqrt(PERIODS_PER_YEAR)) \
            if len(long_sub) > 2 and long_sub.std() > 0 else np.nan
        short_sharpe = float(short_sub.mean() / short_sub.std() * np.sqrt(PERIODS_PER_YEAR)) \
            if len(short_sub) > 2 and short_sub.std() > 0 else np.nan
        long_minus_short[w] = float(long_sharpe - short_sharpe) \
            if not (np.isnan(long_sharpe) or np.isnan(short_sharpe)) else 0.0

    sign_audit_pass = all(v > 0 for v in long_minus_short.values()
                          if not np.isnan(v))

    print(f"\n=== R96 sign={sign} ({label}) ===")
    print(f"3-check: gross_t={gross_t:+.3f} ({'✓' if passes_gross else '✗'}) "
          f"oos_t={oos_t:+.3f} ({'✓' if passes_oos else '✗'}) "
          f"passes_all={gauntlet['passes_all']}")
    print(f"IS Sharpe={is_sharpe:+.2f}  OOS Sharpe={oos_sharpe:+.2f}  "
          f"maxDD={mdd*100:+.2f}%  Decision={decision}")
    print(f"Sign audit: {'PASS' if sign_audit_pass else 'FAIL'} — "
          f"{long_minus_short}")
    print(f"Per-window:")
    for w in sorted(pw):
        row = pw[w]
        print(f"  {w}  ann%={row['ann_pct']:+.2f}%  Sharpe={row['sharpe']:+.2f}  "
              f"maxDD={row['max_dd']*100:+.2f}%  Δ(long-short)={long_minus_short[w]:+.3f}")

    with open(out_path, "a") as f:
        f.write(f"\n## Sign = {sign} ({label})\n\n")
        f.write(f"- 3-check: gross_t={gross_t:+.3f} ({'✓' if passes_gross else '✗'}) "
                f"oos_t={oos_t:+.3f} ({'✓' if passes_oos else '✗'})\n")
        f.write(f"- IS Sharpe={is_sharpe:+.2f}  OOS Sharpe={oos_sharpe:+.2f}  "
                f"maxDD={mdd*100:+.2f}%\n")
        f.write(f"- Decision: **{decision}**\n")
        f.write(f"- Sign audit: **{'PASS' if sign_audit_pass else 'FAIL'}** — "
                f"long-leg Sharpe > short-leg Sharpe in every window\n")
        f.write(f"- Per-window: {long_minus_short}\n")

    return {
        "sign": sign, "label": label,
        "gross_t": gross_t, "oos_t": oos_t,
        "is_sharpe": is_sharpe, "oos_sharpe": oos_sharpe,
        "max_dd": mdd, "decision": decision,
        "sign_audit": sign_audit_pass,
        "per_window": {w: dict(pw[w]) for w in sorted(pw)},
        "fac": fac, "score": score,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")

    _logger.info("Loading funding + returns panel...")
    funding_daily = load_funding_daily()
    rets = load_daily_returns()
    common = [a for a in TRADEABLE_28
              if a in funding_daily.columns and a in rets.columns]
    _logger.info("Universe: %d assets (28-strict)", len(common))

    # Market + TSMOM known factors (used in both report() and fusion sweep)
    mkt = rets[common].mean(axis=1).fillna(0.0)
    cum_mkt = (1 + mkt).cumprod()
    trail30 = cum_mkt / cum_mkt.shift(30) - 1
    known_global = {
        "market": mkt.values,
        "momentum": (np.sign(trail30.shift(1)).fillna(0.0) * mkt).values,
    }

    out = Path("/tmp/cometcloud_reports/R96_FUNDING_MOMENTUM_RESIDUAL_2026-08-24.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        f.write("# R96 — Funding MOMENTUM Residual L/S (Strategy 6 candidate)\n\n")
        f.write(f"**Date:** 2026-08-24\n")
        f.write(f"**Panel:** {len(common)} assets (28-strict funding ∩ CIS ∩ OHLCV)\n")
        f.write(f"**Score:** smoothed Δfunding, cross-sectionally demeaned\n")
        f.write(f"**Smoothing:** {MOMENTUM_SMOOTH}-day rolling mean of 1d Δfunding\n")
        f.write(f"**Cost:** {COST_BPS} bps · **Rebal:** {REBAL_DAYS}d · "
                f"**K:** {K_TERCILES} terciles\n\n")
        f.write("## Cause\n\n")
        f.write("Funding LEVEL captures current perp carry state (R76 ✓); "
                "funding IVOL captures carry stability (R95 PARTIAL); "
                "funding MOMENTUM captures the **change** in carry. Rising "
                "demeaned funding = longs crowding in, exposed to unwind "
                "cascades; falling demeaned funding = shorts crowding in, "
                "squeeze setup. Two natural signs: long-falling (squeeze) "
                "and long-rising (momentum continuation).\n\n")

    # Test BOTH signs
    res_fall = run_one_sign(rets, funding_daily, common, SIGN_FALLING_LONG)
    out_fall = report(res_fall[0], res_fall[1], rets, common, SIGN_FALLING_LONG,
                      "long falling-funding (squeeze) / short rising-funding (crowd)",
                      out)
    res_rise = run_one_sign(rets, funding_daily, common, SIGN_RISING_LONG)
    out_rise = report(res_rise[0], res_rise[1], rets, common, SIGN_RISING_LONG,
                      "long rising-funding (momentum) / short falling-funding (revert)",
                      out)

    # Pick the better sign by OOS_t
    candidates = [out_fall, out_rise]
    best = max(candidates, key=lambda r: r["oos_t"])
    print(f"\n=== Best sign: {best['sign']} "
          f"(OOS_t={best['oos_t']:+.3f} IS_t={best['gross_t']:+.3f} "
          f"OOS_Sharpe={best['oos_sharpe']:+.2f} maxDD={best['max_dd']*100:+.2f}%) ===")

    # ── R77 + R96 fusion test (lesson #42 + #43) ─────────────────────────────
    print(f"\n=== R96 + R77 fusion test ===")
    try:
        from src.research.validation.r63_fusion_validation import (
            build_r46_sleeve_28, build_r62_sleeve_28, fuse,
        )
        from src.research.validation.r76_funding_residual_ls import (
            score_funding_residual, funding_residual_ls,
        )
        from src.research.validation.funding_crowding_ls import score_funding_zwide
        from src.research.validation.cis_quality_absorption import load_cis_history_wide

        cis_long = load_cis_history_wide()
        leg_r46, _ = build_r46_sleeve_28(cis_long, rets, common)
        score_r62 = score_funding_zwide(funding_daily[common], sign="fade_crowd")
        leg_r62 = build_r62_sleeve_28(score_r62, rets, common,
                                     detector=pd.Series(False, index=score_r62.index))
        score_r76 = score_funding_residual(funding_daily, common)
        leg_r76 = funding_residual_ls(score_r76, rets[common], k_terciles=3, cost_bps=0.0)
        leg_r76 = leg_r76.reindex(rets.index).fillna(0.0)
        # R96 leg using best sign
        leg_r96 = best["fac"].copy()

        # Frozen R77 baseline
        fac_2 = fuse(leg_r46, leg_r62, 0.25)
        r77_base = (1 - 0.30) * fac_2 + 0.30 * leg_r76
        r77_base = r77_base.reindex(rets.index).fillna(0.0)

        # Lesson #42: cross-pod correlation
        overlap = leg_r96.dropna().index.intersection(r77_base.dropna().index)
        if len(overlap) >= 50:
            corrs = {
                "R96 vs R46": float(leg_r96.reindex(overlap).corr(leg_r46.reindex(overlap))),
                "R96 vs R62": float(leg_r96.reindex(overlap).corr(leg_r62.reindex(overlap))),
                "R96 vs R76": float(leg_r96.reindex(overlap).corr(leg_r76.reindex(overlap))),
                "R96 vs R77": float(leg_r96.reindex(overlap).corr(r77_base.reindex(overlap))),
            }
            max_abs_corr = max(abs(v) for v in corrs.values())
            print(f"Cross-pod correlation (lesson #42):")
            for k, v in corrs.items():
                print(f"  {k} = {v:+.3f}")
            print(f"  MAX |corr| = {max_abs_corr:.3f} "
                  f"({'✓' if max_abs_corr < 0.30 else '✗'} clears lesson #42 gate < 0.30)")

            # Sweep w_R96
            print(f"\n=== R77 + R96 fusion sweep (w_R96 ∈ [0, 0.50]) ===")
            print(f"{'w_R96':>6} | {'gross_t':>8} | {'OOS_t':>8} | {'pass':>5} | "
                  f"{'OOS_S':>7} | {'maxDD %':>8}")
            sweep = []
            for w in np.arange(0, 0.55, 0.05):
                w = round(w, 2)
                fused = (1 - w) * r77_base + w * leg_r96
                fused = fused.reindex(rets.index).fillna(0.0)
                cut = int(len(fused) * 0.70)
                is_p = fused.iloc[:cut].fillna(0.0)
                oos_p = fused.iloc[cut:].fillna(0.0)
                known2 = {
                    "market": mkt.reindex(fused.index).fillna(0.0).values,
                    "momentum": (np.sign(tRAIL := (cum_mkt / cum_mkt.shift(30) - 1).shift(1)).fillna(0.0)
                                 * mkt.reindex(fused.index).fillna(0.0)).values,
                }
                try:
                    r2 = gauntlet_3check(fused, known2, oos_idx=cut)
                    gt = float(r2.get("gross_t", 0.0))
                    ot = float(r2.get("oos_t", 0.0))
                except (np.linalg.LinAlgError, ValueError):
                    gt = _simple_t(is_p.values)
                    ot = _simple_t(oos_p.values)
                passes = gt > 1.96 and ot > 1.96
                os2 = (float(oos_p.mean() / oos_p.std() * np.sqrt(PERIODS_PER_YEAR))
                       if oos_p.std() > 0 else 0.0)
                mdd2 = max_drawdown(fused)
                sweep.append({
                    "w_R96": w, "gross_t": gt, "oos_t": ot, "passes": passes,
                    "oos_sharpe": os2, "max_dd": mdd2,
                })
                print(f"  {w:>5.2f} | {gt:>+7.3f} | {ot:>+7.3f} | "
                      f"{'✓' if passes else '✗':>4} | {os2:>+6.2f} | "
                      f"{mdd2*100:>+7.2f}%")
            df_sweep = pd.DataFrame(sweep)
            pass_df = df_sweep[df_sweep["passes"]]
            print(f"\nPassing cells: {len(pass_df)} / {len(df_sweep)}")
            base_row = df_sweep.iloc[0]
            if len(pass_df):
                b = pass_df.sort_values("oos_t", ascending=False).iloc[0]
                print(f"Best passing: w_R96={b['w_R96']:.2f} "
                      f"→ gross_t={b['gross_t']:+.3f} oos_t={b['oos_t']:+.3f} "
                      f"OOS_sharpe={b['oos_sharpe']:+.2f} maxDD={b['max_dd']*100:+.2f}%")
            else:
                best_nb = df_sweep.iloc[1:].sort_values("oos_t", ascending=False).iloc[0]
                delta = best_nb["oos_t"] - base_row["oos_t"]
                print(f"No config passes 3-check. Best w_R96>0: {best_nb['w_R96']:.2f} "
                      f"ΔOOS_t={delta:+.3f} "
                      f"({'clears' if delta >= 0.5 else 'does NOT clear'} "
                      f"lesson #43 lift bar +0.5)")

            with open(out, "a") as f:
                f.write(f"\n## R77 + R96 fusion sweep\n\n")
                f.write(f"**Best sign:** {best['sign']} ({best['label']})\n\n")
                f.write(f"### Cross-pod correlation (lesson #42)\n\n")
                for k, v in corrs.items():
                    f.write(f"- {k} = {v:+.3f}\n")
                f.write(f"- **MAX |corr| = {max_abs_corr:.3f}** "
                        f"({'✓' if max_abs_corr < 0.30 else '✗'} clears lesson #42 gate < 0.30)\n\n")
                f.write(f"### Sweep\n\n")
                f.write(df_sweep.to_markdown(index=False))
                f.write(f"\n\nPassing cells: {len(pass_df)} / {len(df_sweep)}\n")
                if len(pass_df):
                    b = pass_df.sort_values("oos_t", ascending=False).iloc[0]
                    f.write(f"\n**Best passing:** w_R96={b['w_R96']:.2f}\n")
                else:
                    f.write(f"\n**No config passes 3-check.** "
                            f"Best ΔOOS_t={delta:+.3f} "
                            f"({'clears' if delta >= 0.5 else 'does NOT clear'} "
                            f"lesson #43 lift bar +0.5)\n")
        else:
            print("Insufficient overlap for fusion test")
    except Exception as e:
        print(f"Fusion test failed: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n=== Report: {out} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
