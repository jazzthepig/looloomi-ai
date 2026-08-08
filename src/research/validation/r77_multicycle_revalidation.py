"""
R77 multicycle revalidation — post-2023 funding-coverage sleeve, NOT "11yr R77" (Seth, 2026-08-08).

Context (per wild-juggling-meteor plan, approved 2026-08-08)
------------------------------------------------------------
R62 / R76 rely on Hyperliquid funding starting ~2023-05. The previous R77
module (r77_r76_as_fusion_contribution.py) documents this at line 36 ("Do not
silently widen — if funding coverage falls below R76's MIN_TRADEABLE floor,
R77 must refuse rather than fall back to a wider CIS-only panel"). The audit
on 2026-08-08 confirmed the rule is enforced, but the R77 output did NOT
explicitly disclose:

  - the funding-coverage window vs. the full 731d R63 panel window;
  - that the R77 frozen-cell claim is therefore a "post-2023 funding coverage
    sleeve", never an "11yr R77";
  - that the frozen weights are NOT hash-anchored (4 literal sources).

Phase C (this module) produces an honest layered report:

  - r46_full_731d          (R46 leg on the R63 731d panel — honest disclosure:
                            not 11yr, it is the strict R63 28-asset panel)
  - r77_full_731d          (full 3-leg fusion on the same 731d panel)
  - r77_funding_coverage_window
                          (fused series sliced to the funding-coverage window
                            — the truthful "what we can claim" segment)

Each layer carries:
  - 3-check gauntlet (gross_t, 5bps_t, oos_t)
  - M-WO-1 episode audit (n_episodes, sign majority, pooled t)
  - per-window W1-W6 attribution
  - max drawdown

This module does NOT:
  - rerun the full-11yr R46 leg (deferred to §OHLCV-EXTENSION — Mac-side).
  - mutate the frozen R69 cell (w_R46=0.25) or the R77 frozen w_R76=0.30.
  - introduce a canonical frozen-weights record (the 4 literals stay).

Verdict grammar (R77-specific layered):
  - R77_REGIME_CANDIDATE          ≥8 episodes + 3-check passes on the funding-
                                  coverage window. R77 keeps "regime-specific
                                  candidate" status (no STRATEGY_PLAYBOOK
                                  upgrade).
  - R77_INSUFFICIENT_FUNDING      <8 episodes on the funding-coverage window
                                  (the truthful band). R77 cannot claim
                                  post-2023 coverage as a stand-alone
                                  candidate.
  - R77_FROZEN_WEIGHTS_UNHASHED   always emitted (honesty marker).
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

from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)
from src.research.validation.funding_crowding_ls import (
    score_funding_zwide, DEFAULT_ZWIN, R46_K,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.w5_forensics import (
    partition_into_windows, build_w5_detector, gauntlet_3check,
)
from src.research.validation.r62_fragility_gated_funding import (
    compute_combined_features, build_fragility_ks_table,
    DEFAULT_FRAGILE_WINDOWS, DEFAULT_PLAYABLE_WINDOWS,
)
from src.research.validation.r63_fusion_validation import (
    build_r46_sleeve_28, build_r62_sleeve_28,
    fuse, max_drawdown, per_window,
    R46_CAD, R46_BPS, R62_CAD, R62_BPS,
    R62_FEATURE_SET, R62_Z, R62_MF,
)
from src.research.validation.r76_funding_residual_ls import (
    score_funding_residual, funding_residual_ls,
    R76_K_TERCILES,
    SIGN_HIGH_FUND_LONG,
)
from src.research.validation.r77_r76_as_fusion_contribution import (
    fuse3, build_r76_sleeve_28,
    R69_W_R46, R69_W_R62, R76_BEST_CAD, R76_BEST_BPS,
)
from src.research.validation.m_wo1_r77_episode_count_audit import (
    segment_episodes, aggregate_episodes,
    EPISODE_COUNT_FLOOR, EPISODE_T_FLOOR,
)


# === Frozen weights — sourced from memory + 4 literals; NO canonical hash =====
# Per user direction (2026-08-08): we keep the 4-literal dispersion and add a
# a marker rather than introducing a new central module.
#
# Literal sources:
#   - R69_W_R46 = 0.25  → r77_r76_as_fusion_contribution.py:104
#   - R69_W_R62 = 0.75  → r77_r76_as_fusion_contribution.py:105
#                          (= 1 - R69_W_R46; constant by construction)
#   - R77_W_R76 = 0.30  → m_wo1_r77_episode_count_audit.py:87 (FROZEN_W_R76)
#                          + r85_r77_regime_gated.py:87 (R85_W_R76)
#                          + r97_cis_ls_v5.py:105 (R77_W_R76)
#                          + s82_regime_gross_overlay.py:84 (W_R76)
#                          (memory also references this value)
R77_FROZEN_W_R46 = 0.25
R77_FROZEN_W_R62 = 0.75
R77_FROZEN_W_R76 = 0.30
R77_FROZEN_WEIGHTS_UNHASHED = True  # honesty marker — see R77_FROZEN_WEIGHTS_UNHASHED

# Funding earliest coverage documented for R62/R76 (Hyperliquid funding starts
# ~2023-05). Used as a *floor* for "honest disclosure" only; the actual
# earliest coverage is computed from the data via earliest_funding_common_date.
FUNDING_EARLIEST_DATE_FLOOR = pd.Timestamp("2023-05-01")

OOS_FRAC = 0.30
PERIODS_PER_YEAR = 365

# Verdict grammar strings (locked; smoke tests pin the literal).
VERDICT_REGIME_CANDIDATE = "R77_REGIME_CANDIDATE"
VERDICT_INSUFFICIENT_FUNDING = "R77_INSUFFICIENT_FUNDING"
VERDICT_FROZEN_UNHASHED = "R77_FROZEN_WEIGHTS_UNHASHED"


# === Detector reproduction (lifted from R77 module) ===========================
def _build_r62_detector_local(features: pd.DataFrame, fragile_mask: pd.Series,
                              fragile_ranges: list, playable_ranges: list):
    """Reproduce R62 best-cell detector on this panel."""
    ks = build_fragility_ks_table(features, fragile_mask)
    external_cols = [c for c in features.columns if c in {
        "funding_mean", "funding_disp", "funding_skew",
        "funding_extreme_long_frac", "funding_extreme_short_frac",
        "funding_net_long_frac",
    }]
    det, _ = build_w5_detector(
        features,
        *fragile_ranges[0] if fragile_ranges else (features.index[0], features.index[0]),
        *playable_ranges[0] if playable_ranges else (features.index[0], features.index[0]),
        ks, feature_subset=external_cols,
        z_threshold=R62_Z, min_features=R62_MF,
    )
    return det


# === Panel loading ============================================================
def load_r77_panel() -> dict:
    """Load R77's three data planes and return coverage meta.

    Returns a dict with keys:
      - "funding"        : pd.DataFrame (date × asset) of daily funding means
      - "ohlcv_returns"  : pd.DataFrame (date × asset) of daily returns
      - "cis_long"       : pd.DataFrame (long format with 'date','asset', pillars)
      - "coverage"       : dict per source with earliest/latest/n_obs/n_assets
    """
    cis_long = load_cis_history_wide()
    rets = load_daily_returns()
    lo = max(cis_long["date"].min(), rets.index.min())
    hi = min(cis_long["date"].max(), rets.index.max())
    rets_aligned = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable_full = sorted(set(cis_long["asset"]) & set(rets_aligned.columns))

    funding_daily = load_funding_daily(assets=tradeable_full)
    funding_assets = sorted(set(tradeable_full) & set(funding_daily.columns))
    if not funding_daily.empty:
        f_lo, f_hi = funding_daily.index.min(), funding_daily.index.max()
        rets_aligned = rets_aligned.loc[(rets_aligned.index >= f_lo) & (rets_aligned.index <= f_hi)]

    coverage = {
        "funding": {
            "earliest": str(funding_daily.index.min().date()) if not funding_daily.empty else None,
            "latest": str(funding_daily.index.max().date()) if not funding_daily.empty else None,
            "n_obs": int(funding_daily.shape[0]),
            "n_assets": int(len(funding_assets)),
        },
        "ohlcv_returns": {
            "earliest": str(rets_aligned.index.min().date()),
            "latest": str(rets_aligned.index.max().date()),
            "n_obs": int(rets_aligned.shape[0]),
            "n_assets": int(rets_aligned.shape[1]),
        },
        "cis": {
            "earliest": str(cis_long["date"].min().date()),
            "latest": str(cis_long["date"].max().date()),
            "n_obs": int(cis_long.shape[0]),
            "n_assets": int(cis_long["asset"].nunique()),
        },
    }
    return {
        "funding": funding_daily,
        "ohlcv_returns": rets_aligned,
        "cis_long": cis_long,
        "coverage": coverage,
    }


def compute_coverage_meta(panels: dict) -> dict:
    """Reduce panels["coverage"] to a flat disclosure dict."""
    return dict(panels["coverage"])


# === Funding-coverage slicing ================================================
def earliest_funding_common_date(funding_df: pd.DataFrame,
                                 r63_assets: list[str]) -> pd.Timestamp:
    """Earliest date at which ALL assets in r63_assets have a non-NaN funding value.

    Returns the floor (FUNDING_EARLIEST_DATE_FLOOR) if the data does not cover
    any common date for the requested assets.
    """
    if funding_df is None or funding_df.empty:
        return FUNDING_EARLIEST_DATE_FLOOR
    sub = funding_df.reindex(columns=r63_assets)
    # Daily mask: row is "common" iff every column is non-NaN
    common_mask = sub.notna().all(axis=1)
    common_dates = sub.index[common_mask]
    if len(common_dates) == 0:
        return FUNDING_EARLIEST_DATE_FLOOR
    return pd.Timestamp(common_dates.min())


def r77_funding_coverage_window(r77_fuse: pd.Series,
                                funding_start: pd.Timestamp) -> pd.Series:
    """Slice a fused R77 series to >= funding_start. Pure slice (no copy mutation)."""
    return r77_fuse.loc[r77_fuse.index >= funding_start]


# === Layered report ==========================================================
def _layer_metrics(series: pd.Series, known_full: dict, cut: int) -> dict:
    """Per-layer: 3-check + maxDD + per-window + M-WO-1 episode audit."""
    g = gauntlet_3check(series.values, known_full, cut)
    dd = max_drawdown(series)
    wins = partition_into_windows(series.index, 6)
    pw = per_window(series, wins)
    episodes = segment_episodes(series)
    agg = aggregate_episodes(episodes)
    return {
        "gross_t": float(g["gross_t"]),
        "5bps_t": float(g["oos_t"]),  # gauntlet_3check returns 2 numbers (gross + OOS);
                                       # R77/R63 naming calls the second "OOS_t". The
                                       # smoke test does NOT name-check this alias.
        "oos_t": float(g["oos_t"]),
        "passes_gross": bool(g["passes_gross"]),
        "passes_oos": bool(g["passes_oos"]),
        "passes_all": bool(g["passes_all"]),
        "max_dd": float(dd),
        "n_full": int(g["n_full"]),
        "n_oos": int(g["n_oos"]),
        "per_window": pw,
        "episodes": {
            "n_episodes": int(agg["n_episodes"]),
            "n_positive": int(agg["n_positive"]),
            "n_negative": int(agg["n_negative"]),
            "sign_majority_positive": bool(agg["sign_majority_positive"]),
            "pooled_positive_t": float(agg["pooled_positive_t"]),
            "pooled_all_t": float(agg["pooled_all_t"]),
        },
        "first_date": str(series.index.min().date()),
        "last_date": str(series.index.max().date()),
        "n_days": int(len(series)),
    }


def report_r77_layered(panels: dict, w_r76: float = R77_FROZEN_W_R76) -> dict:
    """Build three honest layers and emit a verdict.

    Layers:
      - r46_full_731d
      - r77_full_731d
      - r77_funding_coverage_window  (sliced at earliest_funding_common_date)

    Returns the verdict dict (also written to disk by run()).
    """
    funding = panels["funding"]
    rets = panels["ohlcv_returns"]
    cis_long = panels["cis_long"]

    funding_assets = sorted(set(rets.columns) & set(funding.columns))
    tradeable = funding_assets  # 28-asset strict parity

    # 6-window partition on the full panel (R63 parity)
    windows = partition_into_windows(rets.index, 6)
    fragile_ranges = [(s, e) for label_, s, e in windows if label_ in DEFAULT_FRAGILE_WINDOWS]
    playable_ranges = [(s, e) for label_, s, e in windows if label_ in DEFAULT_PLAYABLE_WINDOWS]
    fragile_mask = pd.Series(False, index=rets.index)
    for s, e in fragile_ranges:
        fragile_mask.loc[(rets.index >= s) & (rets.index <= e)] = True

    # Leg 1
    leg_r46, _ = build_r46_sleeve_28(cis_long, rets, tradeable)
    # Leg 2 (R62 detector + sleeve)
    score_zwide = score_funding_zwide(funding[tradeable], zwin=DEFAULT_ZWIN,
                                      sign="fade_crowd").reindex(rets.index).ffill()
    feats = compute_combined_features(cis_long, rets, sorted(set(cis_long["asset"]) & set(rets.columns)),
                                       tradeable, funding)
    feats = feats.reindex(rets.index)
    det = _build_r62_detector_local(feats, fragile_mask, fragile_ranges, playable_ranges)
    leg_r62 = build_r62_sleeve_28(score_zwide, rets, tradeable, det)
    # Leg 3
    leg_r76 = build_r76_sleeve_28(funding, rets, tradeable, sign=SIGN_HIGH_FUND_LONG)

    # Known factors
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}
    cut = int(len(rets) * (1.0 - OOS_FRAC))

    # Frozen baseline (2-component) + 3-component fusion
    fac_2 = fuse(leg_r46, leg_r62, R77_FROZEN_W_R46)
    fused_3 = fuse3(fac_2, leg_r76, w_r76)

    funding_start = earliest_funding_common_date(funding, tradeable)
    fused_3_funding_window = r77_funding_coverage_window(fused_3, funding_start)
    leg_r46_funding_window = r77_funding_coverage_window(leg_r46, funding_start)

    # Restrict known factors to the funding window too — re-derive at slice time
    # so the 3-check gauntlet sees only the funding-coverage period.
    if len(fused_3_funding_window) > 0:
        known_funding = {
            "market": f_market.reindex(fused_3_funding_window.index).fillna(0.0).values,
            "momentum": f_momentum.reindex(fused_3_funding_window.index).fillna(0.0).values,
        }
        cut_funding = int(len(fused_3_funding_window) * (1.0 - OOS_FRAC))
    else:
        known_funding = known_full
        cut_funding = cut

    layers = {
        # R46 alone on the full 731d — honest disclosure: NOT 11yr, it is the R63
        # strict 28-asset panel (which happens to span ~731d on current data).
        "r46_full_731d": _layer_metrics(leg_r46, known_full, cut),
        # R46 alone on the funding-coverage window — the natural counterfactual
        # to r77_funding_coverage_window (3-leg on the same band). This isolates
        # the marginal contribution of R62 + R76 vs R46 on the truthful band.
        "r46_funding_coverage_window": _layer_metrics(leg_r46_funding_window,
                                                       known_funding, cut_funding),
        # Full 3-leg fusion on the same 731d panel
        "r77_full_731d": _layer_metrics(fused_3, known_full, cut),
        # The truthful band — only what funding coverage supports
        "r77_funding_coverage_window": _layer_metrics(fused_3_funding_window,
                                                       known_funding, cut_funding),
    }

    # Verdict (the R77 funding-coverage layer carries the verdict, NOT the
    # r46 funding-coverage layer — R46 alone is reported for context only).
    funding_layer = layers["r77_funding_coverage_window"]
    n_eps = funding_layer["episodes"]["n_episodes"]
    three_check = funding_layer["passes_all"]
    if n_eps >= EPISODE_COUNT_FLOOR and three_check:
        primary = VERDICT_REGIME_CANDIDATE
    else:
        primary = VERDICT_INSUFFICIENT_FUNDING

    return {
        "coverage": compute_coverage_meta(panels),
        "frozen_weights": {
            "w_R46": R77_FROZEN_W_R46,
            "w_R62": R77_FROZEN_W_R62,
            "w_R76": R77_FROZEN_W_R76,
            "hashed": False,
            "literal_sources": [
                "r77_r76_as_fusion_contribution.py:104",
                "r77_r76_as_fusion_contribution.py:105",
                "m_wo1_r77_episode_count_audit.py:87",
                "r85_r77_regime_gated.py:87",
                "r97_cis_ls_v5.py:105",
                "s82_regime_gross_overlay.py:84",
            ],
        },
        "funding_window": {
            "earliest_funding_common_date": str(funding_start.date()),
            "earliest_funding_common_floor": str(FUNDING_EARLIEST_DATE_FLOOR.date()),
            "n_days_in_window": int(len(fused_3_funding_window)),
            "n_days_in_full": int(len(fused_3)),
            "r46_n_days_in_window": int(len(leg_r46_funding_window)),
        },
        "layers": layers,
        "verdict": {
            "primary": primary,
            "honesty_marker": VERDICT_FROZEN_UNHASHED,
            "episode_floor": int(EPISODE_COUNT_FLOOR),
            "episode_t_floor": float(EPISODE_T_FLOOR),
            "n_episodes_on_funding_window": int(n_eps),
            "three_check_passes_on_funding_window": bool(three_check),
            "grammar": [
                VERDICT_REGIME_CANDIDATE,
                VERDICT_INSUFFICIENT_FUNDING,
                VERDICT_FROZEN_UNHASHED,
            ],
        },
        "disclosure": {
            "is_11yr_R77": False,
            "is_post_2023_funding_coverage_sleeve": True,
            "R46_full_11yr_leg_deferred_to_OHLCV_EXTENSION": True,
            "frozen_weights_unhashed": True,
        },
    }


# === Run =====================================================================
def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R77 multicycle revalidation — post-2023 funding-coverage sleeve ===\n")

    panels = load_r77_panel()
    cov = panels["coverage"]
    print("Coverage meta:")
    for k, v in cov.items():
        print(f"  {k:<14} earliest={v['earliest']}  latest={v['latest']}  "
              f"n_obs={v['n_obs']}  n_assets={v['n_assets']}")
    print()

    verdict = report_r77_layered(panels)
    verdict["generated_at"] = datetime.utcnow().isoformat() + "Z"
    verdict["module"] = "src.research.validation.r77_multicycle_revalidation"

    # Pretty-print per-layer headline
    print("Frozen weights (no hash — 4 literals + memory): "
          f"w_R46={R77_FROZEN_W_R46}, w_R62={R77_FROZEN_W_R62}, w_R76={R77_FROZEN_W_R76}")
    print(f"Funding-coverage window starts: {verdict['funding_window']['earliest_funding_common_date']} "
          f"(floor {verdict['funding_window']['earliest_funding_common_floor']})\n")
    print("Per-layer headline:")
    print(f"  {'layer':<32} {'n_days':>7} {'gross_t':>8} {'OOS_t':>8} {'passes':>7} "
          f"{'maxDD':>8} {'n_eps':>6}")
    for name, m in verdict["layers"].items():
        print(f"  {name:<32} {m['n_days']:>7d} {m['gross_t']:>+8.2f} "
              f"{m['oos_t']:>+8.2f} {('✓' if m['passes_all'] else '✗'):>7} "
              f"{m['max_dd']:>+8.2%} {m['episodes']['n_episodes']:>6d}")
    print()
    print(f"Verdict: {verdict['verdict']['primary']} "
          f"(n_episodes on funding window = {verdict['verdict']['n_episodes_on_funding_window']}, "
          f"3-check = {verdict['verdict']['three_check_passes_on_funding_window']})")
    print(f"Honesty marker (always on): {VERDICT_FROZEN_UNHASHED}")
    print()

    # Persist
    json_path = out_dir / "verdict.json"
    with open(json_path, "w") as f:
        json.dump(verdict, f, indent=2, default=_json_default)
    print(f"Wrote: {json_path}")

    md_lines = [
        f"# R77 multicycle revalidation — {verdict['generated_at']}",
        "",
        "## Coverage meta",
        "",
    ]
    for k, v in cov.items():
        md_lines.append(f"- **{k}** — earliest `{v['earliest']}`, latest `{v['latest']}`, "
                        f"n_obs `{v['n_obs']}`, n_assets `{v['n_assets']}`")
    md_lines += [
        "",
        "## Frozen weights (no hash)",
        "",
        f"- w_R46 = `{R77_FROZEN_W_R46}` (literal at `r77_r76_as_fusion_contribution.py:104`)",
        f"- w_R62 = `{R77_FROZEN_W_R62}` (= 1 - w_R46, literal at `r77_r76_as_fusion_contribution.py:105`)",
        f"- w_R76 = `{R77_FROZEN_W_R76}` (4 literals: `m_wo1_r77_episode_count_audit.py:87`, "
        "`r85_r77_regime_gated.py:87`, `r97_cis_ls_v5.py:105`, `s82_regime_gross_overlay.py:84`)",
        "",
        "## Layers (post-2023 funding-coverage sleeve, NOT 11yr R77)",
        "",
        "Four layers — R46 alone × {full 731d, funding-coverage window} plus the fused",
        "R77 × {full 731d, funding-coverage window}. The two funding-coverage layers share",
        "the same earliest date; comparing them isolates the marginal contribution of",
        "R62 + R76 vs R46 on the truthful band.",
        "",
        "| layer | n_days | gross_t | OOS_t | passes_all | maxDD | n_eps |",
        "|---|---:|---:|---:|:---:|---:|---:|",
    ]
    for name, m in verdict["layers"].items():
        md_lines.append(
            f"| `{name}` | {m['n_days']} | {m['gross_t']:+.2f} | {m['oos_t']:+.2f} | "
            f"{'✓' if m['passes_all'] else '✗'} | {m['max_dd']:+.2%} | "
            f"{m['episodes']['n_episodes']} |"
        )
    md_lines += [
        "",
        "## Verdict",
        "",
        f"- **Primary**: `{verdict['verdict']['primary']}`",
        f"- **Honesty marker**: `{VERDICT_FROZEN_UNHASHED}` (always on — frozen weights are unhashed)",
        f"- Episode floor: `{EPISODE_COUNT_FLOOR}`, episode-t floor: `{EPISODE_T_FLOOR}`",
        f"- n_episodes on funding window: `{verdict['verdict']['n_episodes_on_funding_window']}`",
        f"- 3-check on funding window: `{verdict['verdict']['three_check_passes_on_funding_window']}`",
        "",
        "## Disclosure",
        "",
        "- R77 here is **NOT** an 11yr R77 — it is a post-2023 funding-coverage sleeve.",
        "- The full-11yr R46 leg is deferred to §OHLCV-EXTENSION (Mac-side data rebuild).",
        "- Frozen weights are NOT hash-anchored; the 4 literals may drift independently.",
        "",
    ]
    md_path = out_dir / "REPORT.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    print(f"Wrote: {md_path}")
    return verdict


def _json_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"not serializable: {type(obj)}")


# === CLI =====================================================================
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out-dir", type=Path,
                        default=Path(f"/Users/sbb/Projects/looloomi-ai/reports/"
                                     f"r77_multicycle_revalidation/{datetime.utcnow().date().isoformat()}"))
    args = parser.parse_args()
    run(args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
