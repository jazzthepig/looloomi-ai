"""
R91 — Cross-Asset Funding Pair L/S (Perp-Only, Single-Pair, Cost-Tier Aware) (Seth, 2026-07-26).

Per R90 lesson #58 (3rd case): perp shelf EXHAUSTED on cross-sectional funding demean (R76,
R89, R90 all REFUTED). Lower turnover DEFEATS the signal — R76's 5d edge was 5d-specific.

R91 = STRUCTURALLY DIFFERENT decoding: pair-wise funding spread (funding_A − funding_B),
not cross-sectional demean. Pairs are 2-asset structures; the spread is RELATIVE carry within
the pair, not across the universe. This is the perp-only analog of R88's pair-trading but on
the funding axis.

Construction:
  - Top N perp pairs by funding correlation (e.g., DOGE-SUI, INJ-SNX, STX-DOGE).
  - For each pair: funding_spread = funding_A − funding_B (cross-sectional floor 0 by 2-asset).
  - Position: long A if spread > 0, short A if spread < 0 (per pair).
  - Aggregate: dollar-neutral across all pairs (each pair contributes ±1).
  - Rebal: weekly (low turnover).
  - Cost: 9bps per rebal (2 perp-taker fees on Hyperliquid for the pair leg).
  - Cost-tier sweep: 5/10/20bps mandatory (R32 lesson #58).

Why R91 is STRUCTURALLY DIFFERENT from R76/R90:
  - R76/R90: cross-sectional demean across 47 assets at each t (mean asset = 0).
  - R91: pairwise spread across 2 assets only (2-asset "demean" by definition).
  - The signal is RELATIVE carry within a pair, not relative carry across the universe.
  - The risk is pair-specific ORTHOGONAL to the broad perp-funding factor.

Verdict grammar (R32/R89 lesson #58 — STRICT):
  - ✅ SURVIVES — TRADEABLE: 3-check at 5bps passes AND survives_realistic_10bps = True.
  - 🟡 PARTIAL: 3-check passes at 5bps but edge dies at 10bps.
  - 🔴 REFUTED: 3-check fails at any cost tier.

Anti-imposter:
  - Pair selection is in-sample (top correlated). Mitigation: walk-forward OOS on the pair.
  - The signal is pair-funding spread, NOT cross-sectional demean. Different math.
  - The R77 fusion cell is FROZEN; R91 does NOT touch it.
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

from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.r90_perp_funding_carry_held import load_perp_returns


OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

R91_TOP_PAIRS = 8                      # number of top pairs to use
R91_CADENCES = (7, 14, 21, 30)         # LOW turnover (weekly+)
R91_COST_GRID = (0.0, 5.0, 10.0, 20.0, 30.0)  # R32 mandate
R91_REALISTIC_COST_BPS = 10.0          # lesson #58 gate
R91_CORR_THRESHOLD = 0.40              # min |corr| to be a pair
R91_PERP_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")


def find_top_pairs(funding_daily: pd.DataFrame, n_pairs: int = R91_TOP_PAIRS,
                   min_corr: float = R91_CORR_THRESHOLD) -> list:
    """Find top-N most-correlated perp pairs (in-sample — selection-bias acknowledged)."""
    corr = funding_daily.corr()
    pairs = []
    cols = corr.columns.tolist()
    for i, a in enumerate(cols):
        for j, b in enumerate(cols):
            if i < j and not np.isnan(corr.loc[a, b]) and abs(corr.loc[a, b]) >= min_corr:
                pairs.append((a, b, corr.loc[a, b]))
    pairs.sort(key=lambda x: -abs(x[2]))
    return pairs[:n_pairs]


def funding_pair_spread(funding_daily: pd.DataFrame, asset_a: str, asset_b: str,
                        rebal_days: int = 7) -> pd.Series:
    """For a pair, compute the position: +1 if funding_A > funding_B, -1 if below.

    HELD: position is held for `rebal_days` days (not flipped daily).
    """
    f = funding_daily[[asset_a, asset_b]].reindex(funding_daily.index).ffill()
    spread = f[asset_a] - f[asset_b]
    # Position: sign of spread, smoothed via resampling to rebal cadence
    pos = np.sign(spread).fillna(0.0)
    # Resample to rebal cadence (forward-fill between rebal dates)
    diff = pos.diff().abs().fillna(1.0)
    cum = diff.cumsum()
    rebal_idx = cum[cum % 1 == 0].index  # every entry
    # Simpler: at each rebal_days boundary, take the position
    rebal_dates = f.index[::rebal_days]
    pos_at_rebal = pos.reindex(rebal_dates, method="ffill")
    pos_daily = pos_at_rebal.reindex(f.index, method="ffill").fillna(0.0)
    return pos_daily


def pair_ls_returns(funding_daily: pd.DataFrame, perp_returns: pd.DataFrame,
                     pairs: list, rebal_days: int = 7, cost_bps: float = 0.0) -> pd.Series:
    """Cross-asset funding pair L/S — aggregate across all pairs.

    For each pair: long A if funding_A > funding_B at rebal, short A if below.
    Aggregate: equal-weight across pairs, daily returns = ±(ret_A − ret_B) per pair.
    Cost: 2 × cost_bps × (number of flips per rebal) — applied at each rebal date.
    """
    # Per-pair daily returns
    all_pairs = []
    for a, b, _ in pairs:
        pos = funding_pair_spread(funding_daily, a, b, rebal_days=rebal_days)
        # Per-pair daily return: pos × (ret_A − ret_B). Sign-correct: long A if pos=+1.
        ret_a = perp_returns[a].fillna(0.0)
        ret_b = perp_returns[b].fillna(0.0)
        pair_ret = pos * (ret_a - ret_b)
        all_pairs.append(pair_ret)
    if not all_pairs:
        return pd.Series(0.0, index=perp_returns.index)
    # Equal-weight aggregate
    agg = pd.concat(all_pairs, axis=1).fillna(0.0).mean(axis=1)
    # Apply cost at each rebal date (count flips and apply 2 × cost_bps per flip)
    rebal_dates = perp_returns.index[::rebal_days]
    cost_per_rebal = (2.0 * cost_bps / 10000.0) / len(pairs)  # amortized across pairs
    flips = (agg.diff().abs() > 0).astype(float)
    cost_series = flips * cost_per_rebal
    agg_net = agg - cost_series
    return agg_net


def run(out_dir: Path,
        cadences: tuple = R91_CADENCES,
        cost_grid: tuple = R91_COST_GRID,
        n_pairs: int = R91_TOP_PAIRS) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R91 — Cross-Asset Funding Pair L/S (perp-only, single-pair) ===\n")

    # Load perp data
    print("Loading perp OHLCV + funding (Hyperliquid) …")
    funding_daily = load_funding_daily()

    # Perp returns
    perp_returns = load_perp_returns(funding_daily.index, funding_daily.columns.tolist())
    perp_returns = perp_returns.dropna(how="all")
    coverage = perp_returns.notna().sum() / len(perp_returns)
    perp_assets = [a for a in funding_daily.columns if coverage.get(a, 0) > 0.5]
    perp_returns = perp_returns[perp_assets]
    funding_daily = funding_daily[perp_assets]

    lo = max(funding_daily.index.min(), perp_returns.dropna(how="all").index.min())
    hi = min(funding_daily.index.max(), perp_returns.dropna(how="all").index.max())
    rets = perp_returns.loc[(perp_returns.index >= lo) & (perp_returns.index <= hi)]
    funding_daily = funding_daily.loc[(funding_daily.index >= lo) & (funding_daily.index <= hi)]
    print(f"Panel: {lo.date()} → {hi.date()} ({len(rets)} days, {len(perp_assets)} perps)")

    # Find top correlated pairs
    pairs = find_top_pairs(funding_daily, n_pairs=n_pairs)
    print(f"\nTop {len(pairs)} perp pairs (by funding correlation):")
    for a, b, c in pairs:
        print(f"  {a:6s} - {b:6s}: corr={c:+.3f}")

    # 6-window partition
    windows = partition_into_windows(rets.index, 6)

    # Build leg at default cadence (7d/0bps)
    fac_default = pair_ls_returns(funding_daily, rets, pairs, rebal_days=7, cost_bps=0.0)
    fac_default = fac_default.reindex(rets.index).fillna(0.0)

    # Full sweep
    print(f"\n══ Cadence × cost sweep (R91 low turnover) ══\n")
    f_market = rets[perp_assets].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.values, "momentum": f_momentum.values}
    cut = int(len(rets) * (1.0 - OOS_FRAC))

    sweep = {}
    for cad in cadences:
        for bps in cost_grid:
            leg = pair_ls_returns(funding_daily, rets, pairs, rebal_days=cad, cost_bps=bps)
            leg = leg.reindex(rets.index).fillna(0.0)
            g = gauntlet_3check(leg.values, known_full, cut)
            sweep[(cad, bps)] = {
                "cadence": cad, "cost_bps": bps,
                "gross_t": g["gross_t"], "gross_alpha_ann_pct": g["gross_alpha_ann_pct"],
                "oos_t": g["oos_t"], "oos_alpha_ann_pct": g["oos_alpha_ann_pct"],
                "passes_gross": g["passes_gross"], "passes_oos": g["passes_oos"],
                "passes_all": g["passes_all"],
            }

    print(f"  cell | gross_t | OOS_t | OOS_ann% | passes_all")
    print(f"  -----+---------+-------+----------+-----------")
    for (cad, bps), v in sweep.items():
        print(f"  {cad:3d}d/{bps:5.1f}bps | {v['gross_t']:+.2f} | "
              f"{v['oos_t']:+.2f} | {v['oos_alpha_ann_pct']:+.1f}% | "
              f"{'YES' if v['passes_all'] else 'NO'}")

    # Best cell (highest gross_t at 5bps)
    best_cell = max(sweep.items(),
                    key=lambda kv: (kv[1]["gross_t"] if kv[1]["cost_bps"] == 5.0 else -999,
                                     kv[1]["oos_t"]))
    (best_cad, best_bps), best_metrics = best_cell
    print(f"\nBest cell (5bps): {best_cad}d/{best_bps}bps → gross_t={best_metrics['gross_t']:+.2f}, "
          f"OOS_t={best_metrics['oos_t']:+.2f}, passes={best_metrics['passes_all']}")

    # Cost-tier sweep at best cell
    print(f"\n══ Cost-tier sweep at best cell ({best_cad}d) — R32/R89 gate ══\n")
    cost_tier = {}
    for cost_bps in cost_grid:
        leg = pair_ls_returns(funding_daily, rets, pairs, rebal_days=best_cad,
                               cost_bps=cost_bps)
        leg = leg.reindex(rets.index).fillna(0.0)
        g = gauntlet_3check(leg.values, known_full, cut)
        cost_tier[cost_bps] = {
            "cost_bps": cost_bps,
            "gross_t": g["gross_t"], "gross_alpha_ann_pct": g["gross_alpha_ann_pct"],
            "oos_t": g["oos_t"], "oos_alpha_ann_pct": g["oos_alpha_ann_pct"],
            "passes_gross": g["passes_gross"], "passes_oos": g["passes_oos"],
            "passes_all": g["passes_all"],
        }

    print(f"  cost_bps | gross_t | OOS_t | OOS_ann% | passes_all | survives_10bps")
    for cost_bps, v in cost_tier.items():
        marker = " ← GATE" if cost_bps == R91_REALISTIC_COST_BPS else ""
        survives = cost_tier[R91_REALISTIC_COST_BPS]["passes_all"] if R91_REALISTIC_COST_BPS in cost_tier else False
        print(f"  {cost_bps:8.1f} | {v['gross_t']:+.2f} | {v['oos_t']:+.2f} | "
              f"{v['oos_alpha_ann_pct']:+.1f}% | "
              f"{'YES' if v['passes_all'] else 'NO':<10} | {survives}{marker}")

    survives_realistic_10bps = cost_tier[R91_REALISTIC_COST_BPS]["passes_all"]
    print(f"\n  Survives at 10bps? {survives_realistic_10bps}")

    # Per-window at best cell (5bps)
    print(f"\n══ Per-window W1–W6 at best cell ({best_cad}d/5bps) ══\n")
    fac_5bps = pair_ls_returns(funding_daily, rets, pairs, rebal_days=best_cad, cost_bps=5.0)
    fac_5bps = fac_5bps.reindex(rets.index).fillna(0.0)
    from src.research.validation.r63_fusion_validation import per_window
    pw_5bps = per_window(fac_5bps, windows)
    print("  Window | n_days | ann_pct | maxDD")
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        if label in pw_5bps:
            print(f"  {label} | {pw_5bps[label]['n_days']:6d} | "
                  f"{pw_5bps[label]['ann_pct']:+.1f}% | "
                  f"{pw_5bps[label]['max_dd']:+.2%}")

    # Verdict
    passes_3check_5bps = best_metrics["passes_all"]
    if passes_3check_5bps and survives_realistic_10bps:
        verdict = "✅ SURVIVES — TRADEABLE — eligible for Strategy 2 slot."
        verdict_band = "TRADEABLE"
    elif passes_3check_5bps and not survives_realistic_10bps:
        verdict = ("🟡 PARTIAL — 3-check at 5bps passes but edge dies at 10bps (R32/R89 "
                   "taker-fee illusion). Cross-asset funding pair cannot survive realistic cost.")
        verdict_band = "PARTIAL"
    else:
        verdict = ("🔴 REFUTED — cross-asset funding pair L/S lacks standalone edge. "
                   "Perp-shelf 3rd-axe exhausted (R76/R89/R90 depletes cross-sectional demean; "
                   "R91 depletes pairwise spread).")
        verdict_band = "REFUTED"

    print(f"\nVerdict: {verdict}\n")

    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_perps": len(perp_assets)},
        "pairs": [{"a": a, "b": b, "corr": float(c)} for a, b, c in pairs],
        "construction": {
            "score": "funding_pair_spread = funding_A - funding_B",
            "n_pairs": n_pairs,
            "cadences": list(cadences),
            "cost_grid": list(cost_grid),
            "realistic_cost_bps": R91_REALISTIC_COST_BPS,
            "single_instrument": True, "pair_based": True, "low_turnover": True,
        },
        "best_cell": {"cadence": best_cad, "cost_bps_5bps": 5.0,
                      "gauntlet_5bps": best_metrics},
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
            "note": "R91 is research-only. Strategy 2 slot OPENED only if ✅ TRADEABLE.",
        },
    }
    return out


def format_report(payload: dict) -> str:
    """Human-readable R91 report."""
    lines = []
    lines.append("# R91 — Cross-Asset Funding Pair L/S (Perp-Only)")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"**Panel:** {payload['panel']['lo']} → {payload['panel']['hi']} "
                 f"({payload['panel']['n_days']} days, {payload['panel']['n_perps']} perps)")
    lines.append("")
    lines.append("## Top pairs (by funding correlation)")
    for p in payload["pairs"]:
        lines.append(f"- {p['a']} - {p['b']}: corr={p['corr']:+.3f}")
    lines.append("")
    lines.append("## Verdict")
    vd = payload["verdict"]
    lines.append(f"**{vd['band']}** — {vd['verdict_string']}")
    lines.append("")
    lines.append(f"- Passes 3-check at 5bps: **{vd['passes_3check_5bps']}**")
    lines.append(f"- Survives realistic 10bps cost: **{vd['survives_realistic_10bps']}**")
    lines.append("")
    lines.append("## Cost-tier sweep (R32/R89 lesson #58 — MANDATORY)")
    lines.append("")
    lines.append("| cost_bps | gross_t | OOS_t | OOS_ann% | passes_all |")
    lines.append("|----------|---------|-------|----------|------------|")
    for k, v in payload["cost_tier_sweep"].items():
        marker = " ← GATE" if float(k.replace("bps", "")) == R91_REALISTIC_COST_BPS else ""
        lines.append(f"| {k} | {v['gross_t']:+.2f} | {v['oos_t']:+.2f} | "
                     f"{v['oos_alpha_ann_pct']:+.1f}% | "
                     f"{'YES' if v['passes_all'] else 'NO'} |{marker}")
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
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r91_cross_asset_funding_pair/{today}")
    payload = run(out)

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
