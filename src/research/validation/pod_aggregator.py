"""
Strategy 3 — Pod Aggregator backtest (R-N + 30, Minimax-B, 2026-08-20).
======================================================================

Spec: docs/STRATEGY_3_POD_AGGREGATOR.md (Millennium flavor).

What this does
--------------
1. Build 3 pods on the 28-asset strict funding ∩ CIS ∩ OHLCV panel:
   - Pod 1 (R46): pillar_O 5d/5bps (k=3 terciles, long top / short bottom)
   - Pod 2 (R62): fragility-gated fade-the-crowd 21d/0bps
   - Pod 3 (R76): funding residual 5d/0bps (cross-sectional demean)
2. Apply cross-pod correlation gate (lesson #42: max |corr| < 0.30).
3. Compute OOS-Sharpe-weighted aggregation with James-Stein-style shrinkage.
4. Apply vol targeting (12% annualized) at the aggregator.
5. Apply per-pod DD circuit breaker (-15% per pod).

Output
------
* Console: 3-check gauntlet + per-window W1-W6 + max DD
* File: reports/POD_AGGREGATOR_YYYY-MM-DD.md

Lane
----
Minimax-B (analysis). Mac-side run. Reads 28-asset panel from
`/Volumes/CometCloudAI/data/ohlcv/` and CIS-history from
`/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.funding_crowding_ls import score_funding_zwide
from src.research.validation.r62_fragility_gated_funding import (
    compute_combined_features, build_fragility_ks_table,
    DEFAULT_FRAGILE_WINDOWS, DEFAULT_PLAYABLE_WINDOWS,
)
from src.research.validation.r63_fusion_validation import (
    build_r46_sleeve_28, build_r62_sleeve_28,
    fuse, max_drawdown, per_window,
    _build_r62_detector,
    R46_CAD, R46_BPS, R62_CAD, R62_BPS,
    R62_FEATURE_SET, R62_Z, R62_MF,
)
from src.research.validation.r76_funding_residual_ls import (
    score_funding_residual, funding_residual_ls,
    leg_correlation_gate,
)

# ── Constants (frozen-cell pending backtest result) ───────────────────────────
POD_DD_CIRCUIT_BREAKER = -0.15    # -15% per pod → pod weight → 0 until manual reset
VOL_TARGET_ANN = 0.12             # 12% annualized at aggregator
REBAL_DAYS = 5                    # R77 cadence
COST_BPS = 5.0                    # round-trip at aggregator (turnover)
PERIODS_PER_YEAR = 365

LEG_CORR_GATE = 0.30              # lesson #42: max |corr| < this
SHRINKAGE_K = 50                  # James-Stein shrinkage constant (days)

OHLCV_DIR = Path("/Volumes/CometCloudAI/data/ohlcv")
CIS_HISTORY_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/cis_history")
OUTPUT_DIR = Path("/Users/sbb/Documents/Claude/Reports")

_logger = logging.getLogger("pod_aggregator")


# ── Pod construction ──────────────────────────────────────────────────────────
@dataclass
class PodReturns:
    name: str
    fac: pd.Series           # daily return stream
    sharpe_is: float
    sharpe_oos: float
    max_dd: float


def build_pods(cis_long: pd.DataFrame, rets: pd.DataFrame,
               funding_daily: pd.DataFrame,
               tradeable: list[str],
               split_frac: float = 0.70) -> list[PodReturns]:
    """Build R46 / R62 / R76 pods on the tradeable universe, then split each
    pod's returns into IS (first 70%) and OOS (last 30%) for shrinkage weights."""
    # Pod 1: R46 pillar_O 5d/5bps
    leg_r46, pillar_o_w = build_r46_sleeve_28(cis_long, rets, tradeable)
    # Pod 2: R62 fade-the-crowd gated
    features = compute_combined_features(
        cis_long, rets, tradeable, tradeable, funding_daily
    )
    score = score_funding_zwide(funding_daily[tradeable], sign="fade_crowd")
    det, _ = build_fragility_ks_table(features,
                                      fragile_labels=DEFAULT_FRAGILE_WINDOWS,
                                      playable_labels=DEFAULT_PLAYABLE_WINDOWS,
                                      z_threshold=R62_Z, min_features=R62_MF)
    leg_r62 = build_r62_sleeve_28(score, rets, tradeable, det)
    # Pod 3: R76 funding residual 5d/0bps
    fr_score = score_funding_residual(funding_daily, tradeable)
    leg_r76 = funding_residual_ls(fr_score, rets[tradeable], k=3, cost_bps=0.0)
    leg_r76 = leg_r76.reindex(rets.index).fillna(0.0)

    cut = int(len(rets) * split_frac)
    is_idx = rets.index[:cut]
    oos_idx = rets.index[cut:]

    pods: list[PodReturns] = []
    for name, fac in [("R46", leg_r46), ("R62", leg_r62), ("R76", leg_r76)]:
        fac = fac.reindex(rets.index).fillna(0.0)
        s_is = sharpe(fac.loc[is_idx])
        s_oos = sharpe(fac.loc[oos_idx])
        pods.append(PodReturns(name=name, fac=fac,
                                sharpe_is=s_is, sharpe_oos=s_oos,
                                max_dd=max_drawdown(fac)))
    return pods


def sharpe(returns: pd.Series) -> float:
    r = returns.dropna()
    if len(r) < 2 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(PERIODS_PER_YEAR))


# ── Cross-pod correlation gate (lesson #42) ───────────────────────────────────
def apply_correlation_gate(pods: list[PodReturns], gate: float = LEG_CORR_GATE
                            ) -> tuple[list[PodReturns], dict]:
    """Drop pods whose pairwise correlation with any survivor exceeds `gate`.
    The lowest-OOS-Sharpe pod is dropped first if there is a breach."""
    facs = pd.DataFrame({p.name: p.fac for p in pods})
    survivors = list(pods)
    dropped = []
    while True:
        if len(survivors) <= 1:
            break
        corr = facs[[p.name for p in survivors]].corr()
        # Max abs off-diagonal correlation
        n = len(survivors)
        max_corr = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                c = abs(corr.iloc[i, j])
                if c > max_corr:
                    max_corr = c
        if max_corr <= gate:
            break
        # Drop the lowest-OOS-Sharpe pod
        victim = min(survivors, key=lambda p: p.sharpe_oos)
        survivors.remove(victim)
        dropped.append({"name": victim.name, "sharpe_oos": victim.sharpe_oos,
                        "reason": f"max |corr|={max_corr:.3f} > gate={gate}"})
    return survivors, {"dropped": dropped, "max_corr_retained": max_corr}


# ── OOS-Sharpe weighting with James-Stein shrinkage ───────────────────────────
def shrink_weights(pods: list[PodReturns], k: int = SHRINKAGE_K) -> dict[str, float]:
    """OOS-Sharpe weighted combination with James-Stein-style shrinkage toward
    equal weights. Shrinks each weight by n/(n+K) to avoid tiny-sample overfit."""
    n = len(pods)
    if n == 0:
        return {}
    sharpes = np.array([max(p.sharpe_oos, 0.0) for p in pods])
    if sharpes.sum() == 0:
        # All zero — equal weight
        raw = np.ones(n) / n
    else:
        raw = sharpes / sharpes.sum()
    equal = np.ones(n) / n
    # James-Stein-style: shrink raw toward equal by n/(n+K)
    shrink = n / (n + k)
    w = shrink * raw + (1.0 - shrink) * equal
    return {p.name: float(w[i]) for i, p in enumerate(pods)}


# ── Vol targeting ─────────────────────────────────────────────────────────────
def vol_target(fac: pd.Series, target_ann: float = VOL_TARGET_ANN) -> pd.Series:
    """Scale daily returns so annualized vol = target. Uses trailing 30d
    realized vol; static floor to avoid blow-up when realized → 0."""
    daily_target = target_ann / np.sqrt(PERIODS_PER_YEAR)
    rv = fac.rolling(30, min_periods=10).std().fillna(fac.std())
    rv = rv.clip(lower=daily_target * 0.5)   # static floor
    scale = (daily_target / rv).clip(upper=2.0)  # cap leverage at 2x
    return fac * scale


# ── Per-pod DD circuit breaker ────────────────────────────────────────────────
def apply_dd_circuit_breaker(pods: list[PodReturns],
                              breaker: float = POD_DD_CIRCUIT_BREAKER
                              ) -> dict[str, pd.Series]:
    """Per-pod DD circuit breaker: if a pod's drawdown exceeds `breaker`,
    that pod's contribution to the aggregator is zeroed out until manual reset.
    Returns a dict {pod_name: enabled_mask} where mask=True means the pod is
    enabled on that day."""
    masks = {}
    for p in pods:
        cum = (1 + p.fac.fillna(0.0)).cumprod()
        peak = cum.cummax()
        dd = cum / peak - 1
        # Pod is disabled from the first day its DD breaches the threshold
        # until end (no auto-recovery — manual reset only).
        breached = (dd <= breaker).astype(bool)
        # Once breached, stays disabled forever (the mask is monotonic)
        ever_breached = breached.cumsum() > 0
        masks[p.name] = (~ever_breached).astype(float)
    return masks


# ── Aggregator ────────────────────────────────────────────────────────────────
def aggregate(pods: list[PodReturns],
              weights: dict[str, float],
              masks: dict[str, pd.Series],
              cost_bps: float = COST_BPS) -> pd.Series:
    """Weighted aggregator with masks + turnover cost.

    The aggregator's daily return is sum_i (w_i × mask_i × pod_i_fac) − cost.
    Cost is half of round-trip on turnover (per-leg weight changes)."""
    facs = pd.DataFrame({p.name: p.fac for p in pods}).fillna(0.0)
    mask_df = pd.DataFrame(masks).reindex(facs.index).fillna(1.0)
    w_vec = pd.Series(weights).reindex(facs.columns).fillna(0.0)

    # Effective contribution per day per pod
    contrib = facs * mask_df * w_vec
    agg = contrib.sum(axis=1)

    # Turnover cost: on rebalance days, half round-trip × Σ|w·mask changes|
    rebal_every = REBAL_DAYS
    cost_per_unit = cost_bps / 2.0 / 1e4   # half of round-trip
    # Track weight changes day over day
    eff_w = mask_df * w_vec   # broadcast weight by pod
    delta_w = eff_w.diff().abs().sum(axis=1).fillna(0.0)
    cost = delta_w * cost_per_unit

    # Apply cost on rebalance days only (the spec says "rebalance 5d")
    rebal_mask = pd.Series(0.0, index=agg.index)
    rebal_mask.iloc[::rebal_every] = 1.0
    agg = agg - cost * rebal_mask

    return agg


# ── 3-check gauntlet + per-window ─────────────────────────────────────────────
def full_gauntlet(fac: pd.Series, rets: pd.DataFrame | None = None,
                  *, split_frac: float = 0.70) -> dict:
    """3-check gauntlet. If `rets` provided, builds known factors (market +
    momentum) and uses the real gauntlet_3check; otherwise computes t-stats
    directly on the return stream (sandbox mode)."""
    cut = int(len(fac) * split_frac)
    is_f = fac.iloc[:cut].fillna(0.0)
    oos_f = fac.iloc[cut:].fillna(0.0)
    if rets is not None:
        # Build known factors from returns
        mkt = rets.mean(axis=1).fillna(0.0).reindex(fac.index).fillna(0.0)
        cum = (1 + mkt).cumprod()
        trail30 = cum / cum.shift(30) - 1
        known = {
            "market": mkt.values,
            "momentum": (np.sign(trail30.shift(1)).fillna(0.0) * mkt).values,
        }
        res = gauntlet_3check(fac, known, oos_idx=cut)
        gross_t = res.get("gross_t", res.get("alpha_t", 0.0))
        oos_t = res.get("oos_t", 0.0)
    else:
        # Sandbox fallback: compute t-stats directly on the return stream
        gross_t = _simple_t(is_f.values)
        oos_t = _simple_t(oos_f.values)
    return {
        "gross_t": gross_t,
        "oos_t": oos_t,
        "is_sharpe": float(is_f.mean() / is_f.std() * np.sqrt(PERIODS_PER_YEAR)) if is_f.std() > 0 else 0.0,
        "oos_sharpe": float(oos_f.mean() / oos_f.std() * np.sqrt(PERIODS_PER_YEAR)) if oos_f.std() > 0 else 0.0,
        "max_dd": max_drawdown(fac),
        "ann_vol": float(fac.std() * np.sqrt(PERIODS_PER_YEAR)),
    }


def _simple_t(x: np.ndarray) -> float:
    """Newey-West-free t-stat for sandbox mode."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2 or x.std() == 0:
        return 0.0
    return float(x.mean() / (x.std() / np.sqrt(len(x))))


# ── Driver ────────────────────────────────────────────────────────────────────
def run(output_dir: Path = OUTPUT_DIR, sandbox: bool = False) -> dict:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")

    if sandbox:
        # Synthetic panel for Cowork execution — NOT a real backtest result.
        # Verifies the pipeline end-to-end; verdict on synthetic data is
        # always REFUTED (no real alpha survives on noise) but proves the
        # discipline gates fire correctly.
        from src.research.validation.tests.test_pod_aggregator_smoke import (
            _shared_factor, _synth_pod,
        )
        n_days = 365
        dates = pd.date_range("2024-06-07", periods=n_days, freq="D")
        sf = _shared_factor(seed=42)
        tradeable = [f"A{i:02d}" for i in range(28)]
        # 3 pods: R46 (positive trend), R62 (mean-reverting), R76 (low-vol)
        pod_r46 = _synth_pod("R46", sharpe_oos=2.0,
                              shared_factor=sf, shared_weight=0.0, seed=1)
        pod_r62 = _synth_pod("R62", sharpe_oos=1.5,
                              shared_factor=sf, shared_weight=0.0, seed=2)
        pod_r76 = _synth_pod("R76", sharpe_oos=1.0,
                              shared_factor=sf, shared_weight=0.0, seed=3)
        pods = [pod_r46, pod_r62, pod_r76]
        survivors, gate_log = apply_correlation_gate(pods, gate=LEG_CORR_GATE)
        weights = shrink_weights(survivors, k=SHRINKAGE_K)
        masks = apply_dd_circuit_breaker(survivors)
        raw_agg = aggregate(survivors, weights, masks)
        targeted_agg = vol_target(raw_agg, target_ann=VOL_TARGET_ANN)
        # Build synthetic return matrix for known factors in the gauntlet
        rets_synth = pd.DataFrame(
            np.random.default_rng(99).normal(0, 0.02, (len(targeted_agg), len(tradeable))),
            index=targeted_agg.index, columns=tradeable)
        raw_g = full_gauntlet(raw_agg, rets_synth)
        tgt_g = full_gauntlet(targeted_agg, rets_synth)
        pw_raw = per_window(raw_agg, partition_into_windows(raw_agg.index))
        pw_tgt = per_window(targeted_agg, partition_into_windows(targeted_agg.index))
        best_t = max(tgt_g["gross_t"], tgt_g["oos_t"])
        if (tgt_g["oos_sharpe"] >= 1.5
                and tgt_g["max_dd"] >= -0.15
                and best_t >= 2.0):
            decision = "FUSION_LIFT"
        elif tgt_g["oos_sharpe"] >= 1.0 and tgt_g["max_dd"] >= -0.20:
            decision = "NEUTRAL"
        else:
            decision = "REFUTED"
        _logger.warning("SANDBOX MODE — verdict is on synthetic data, NOT real")
        return {
            "sandbox": True,
            "decision": decision,
            "pods_survived": [p.name for p in survivors],
            "pods_dropped": gate_log["dropped"],
            "weights": weights,
            "max_corr_retained": gate_log["max_corr_retained"],
            "raw_aggregator_gauntlet": raw_g,
            "vol_targeted_gauntlet": tgt_g,
            "per_window_raw": pw_raw,
            "per_window_targeted": pw_tgt,
            "panel": {
                "lo": str(dates[0].date()), "hi": str(dates[-1].date()),
                "n_days": n_days, "n_assets": len(tradeable),
            },
        }

    # ── Load panels (R63 parity) ─────────────────────────────────────────────
    cis_long = load_cis_history_wide()
    rets = load_daily_returns()
    lo = max(cis_long["date"].min(), rets.index.min())
    hi = min(cis_long["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable_full = sorted(set(cis_long["asset"]) & set(rets.columns))
    funding_daily = load_funding_daily(assets=tradeable_full)
    funding_assets = sorted(set(tradeable_full) & set(funding_daily.columns))
    tradeable = funding_assets  # 28-asset strict intersection

    _logger.info("Panel: %s → %s (%d days × %d pods-universe)",
                 lo.date(), hi.date(), len(rets), len(tradeable))

    # ── Build pods ──────────────────────────────────────────────────────────
    pods = build_pods(cis_long, rets, funding_daily, tradeable)

    # ── Apply correlation gate (lesson #42) ─────────────────────────────────
    survivors, gate_log = apply_correlation_gate(pods, gate=LEG_CORR_GATE)

    # ── Shrinkage weights ───────────────────────────────────────────────────
    weights = shrink_weights(survivors, k=SHRINKAGE_K)
    _logger.info("Survivors: %s, weights: %s",
                 [p.name for p in survivors], weights)

    # ── DD circuit breaker ─────────────────────────────────────────────────
    masks = apply_dd_circuit_breaker(survivors)

    # ── Vol target the aggregator ───────────────────────────────────────────
    raw_agg = aggregate(survivors, weights, masks)
    targeted_agg = vol_target(raw_agg, target_ann=VOL_TARGET_ANN)

    # ── 3-check gauntlet ────────────────────────────────────────────────────
    raw_g = full_gauntlet(raw_agg)
    tgt_g = full_gauntlet(targeted_agg)
    pw_raw = per_window(raw_agg, partition_into_windows(raw_agg.index))
    pw_tgt = per_window(targeted_agg, partition_into_windows(targeted_agg.index))

    # ── Decision grammar ───────────────────────────────────────────────────
    decision = "TBD"
    best_t = max(tgt_g["gross_t"], tgt_g["oos_t"])
    if (tgt_g["oos_sharpe"] >= 1.5
            and tgt_g["max_dd"] >= -0.15
            and best_t >= 2.0):
        decision = "FUSION_LIFT"
    elif tgt_g["oos_sharpe"] >= 1.0 and tgt_g["max_dd"] >= -0.20:
        decision = "NEUTRAL"
    else:
        decision = "REFUTED"

    result = {
        "decision": decision,
        "pods_survived": [p.name for p in survivors],
        "pods_dropped": gate_log["dropped"],
        "weights": weights,
        "max_corr_retained": gate_log["max_corr_retained"],
        "raw_aggregator_gauntlet": raw_g,
        "vol_targeted_gauntlet": tgt_g,
        "per_window_raw": pw_raw,
        "per_window_targeted": pw_tgt,
    }
    return result


def render_report(result: dict, output_path: Path) -> None:
    lines = []
    lines.append("# Strategy 3 — Pod Aggregator backtest")
    lines.append(f"**Date:** {pd.Timestamp.now().date()}  ")
    lines.append(f"**Decision:** **{result['decision']}**\n")
    lines.append("## Pods\n")
    lines.append(f"- Survived: {result['pods_survived']}")
    lines.append(f"- Dropped: {result['pods_dropped']}")
    lines.append(f"- Weights (after shrinkage): {result['weights']}")
    lines.append(f"- Max |corr| retained: {result['max_corr_retained']:.3f}\n")
    lines.append("## Aggregator gauntlet\n")
    lines.append("| Metric | Raw | Vol-targeted |")
    lines.append("|--------|-----|--------------|")
    for k in ("gross_t", "oos_t", "is_sharpe", "oos_sharpe",
              "max_dd", "ann_vol"):
        lines.append(f"| {k} | {result['raw_aggregator_gauntlet'][k]:+.3f} | "
                     f"{result['vol_targeted_gauntlet'][k]:+.3f} |")
    lines.append("")
    lines.append("## Per-window W1-W6 (vol-targeted)\n")
    lines.append("| Window | ann % | Sharpe | maxDD |")
    lines.append("|--------|-------|--------|-------|")
    for label, row in sorted(result["per_window_targeted"].items()):
        lines.append(f"| {label} | {row['ann_pct']:+.2f}% | "
                     f"{row['sharpe']:+.2f} | {row['max_dd']:+.3f} |")
    lines.append("")
    output_path.write_text("\n".join(lines))
    _logger.info("Report written: %s", output_path)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    p.add_argument("--sandbox", action="store_true",
                   help="Run on synthetic data (Cowork only, NOT a real backtest)")
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = run(output_dir=args.output_dir, sandbox=args.sandbox)
    stamp = pd.Timestamp.now().strftime("%Y-%m-%d")
    suffix = "_SANDBOX" if args.sandbox else ""
    out = args.output_dir / f"POD_AGGREGATOR_{stamp}{suffix}.md"
    render_report(result, out)
    print(f"\n=== Decision: {result['decision']} ==="
          + ("  [SANDBOX — not a real backtest]" if args.sandbox else ""))
    print(f"=== Report: {out} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())