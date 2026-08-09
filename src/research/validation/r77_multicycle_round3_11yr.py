"""R77 multicycle revalidation — ROUND 3: 11yr panel bridge (skeleton).

Context
--------
Phase C (commit 9423821) shipped the 4-layer honest-disclosure report on the
731d R63 panel. Per MINIMAX_SYNC.md §OHLCV-EXTENSION-CONSUMER, the 11yr R46
leg is deferred to a **separate round-3 module** that consumes the
`/tmp/cometcloud_data/ohlcv_11yr.db` panel built by `scripts/fetch_ohlcv_11yr_binance.py`
(per Seth §OHLCV-EXTENSION-RESOLVE 2026-08-08).

Why a SEPARATE module (not modify r77_multicycle_revalidation.py)
-----------------------------------------------------------------
- The 731d 4-layer report has 12/12 smoke tests passing. Modifying it to
  optionally swap data sources would touch test 12 (slice geometry) and risk
  corrupting the working 4-layer logic.
- `disclosure.is_11yr_R77 = False` is *correct as-is* on the 731d panel. The
  round-3 module gets its own disclosure field set so the verdict grammar
  stays clean.
- This is the same pattern as `r97_panel_11yr.py` (separate module, separate
  verdict) vs `r97_cis_ls_v5_11yr.py` (Phase A REFUTED). Each panel length
  is its own test.

Skeleton status (2026-08-09)
----------------------------
This file is a **skeleton**. The panel has not been rebuilt yet (§OHLCV-EXTENSION
awaiting §OHLCV-EXTENSION-RESOLVE-COMPLETE from Minimax-A). The skeleton:
- Imports cleanly (preflight-green even without the sqlite).
- Exposes `load_r77_panel_11yr()` signature so the next session can wire it
  once the panel exists.
- Exposes a new verdict grammar string `VERDICT_INSUFFICIENT_FUNDING_ON_11YR`
  to handle the case where the 11yr panel still doesn't clear the gauntlet.
- `disclosure.is_11yr_R77 = False` is the **default** until a successful
  round-3 run flips it to `True` AND `passes_all` is true.

Once §OHLCV-EXTENSION-RESOLVE-COMPLETE confirms the panel is usable:
1. Fill in `load_r77_panel_11yr()` body (see TODO comments).
2. Wire `report_r77_layered_round3()` (see TODO).
3. Land ledger entry `R77-MULTICYCLE-ROUND3`.
4. THEN consider adding to preflight (skeleton does NOT belong in preflight).

Lane: Minimax-C (per CLAUDE.md hard rule #3, src/research/validation/ is a
shared sub-territory; R77-multicycle work is owned by Minimax-C per prior commits).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.research.validation.r97_panel_11yr import (
    DB_PATH, MIN_SPAN_DAYS, freeze_universe, to_wide, Panel11yr,
)
from src.research.validation.cis_quality_absorption import load_cis_history_wide
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.r77_multicycle_revalidation import (
    report_r77_layered,
    VERDICT_REGIME_CANDIDATE as VERDICT_731D_REGIME_CANDIDATE,
    VERDICT_INSUFFICIENT_FUNDING as VERDICT_731D_INSUFFICIENT_FUNDING,
    VERDICT_FROZEN_UNHASHED,
    R77_FROZEN_W_R46 as R77_731D_W_R46,
    R77_FROZEN_W_R62 as R77_731D_W_R62,
    R77_FROZEN_W_R76 as R77_731D_W_R76,
)


# === Verdict grammar (round-3 specific) =======================================
# Inherits the 731d verdict grammar from r77_multicycle_revalidation (those
# strings describe the 731d panel verdict and stay valid there). The round-3
# verdict grammar is ADDITIVE — a NEW set of strings for the 11yr panel.
VERDICT_R3_REGIME_CANDIDATE = "R77_REGIME_CANDIDATE_ON_11YR"
VERDICT_R3_INSUFFICIENT_FUNDING = "R77_INSUFFICIENT_FUNDING_ON_11YR"
VERDICT_R3_FROZEN_UNHASHED = "R77_FROZEN_WEIGHTS_UNHASHED"  # inherited marker


# === Frozen weights (inherited, NOT redefined) ================================
# Same 4-literal dispersion as r77_multicycle_revalidation. NO hash (Lesson #92).
R77_FROZEN_W_R46 = 0.25
R77_FROZEN_W_R62 = 0.75
R77_FROZEN_W_R76 = 0.30


# === Panel loading (the round-3 bridge) =======================================
def load_r77_panel_11yr(db_path: Path = DB_PATH,
                        min_span_days: int = MIN_SPAN_DAYS) -> dict:
    """Load R77's three data planes anchored on the 11yr sqlite panel.

    Returns the SAME dict shape as r77_multicycle_revalidation.load_r77_panel():
      - "funding"        : pd.DataFrame (date × asset) of daily funding means
      - "ohlcv_returns"  : pd.DataFrame (date × asset) of daily returns from sqlite
      - "cis_long"       : pd.DataFrame (long form with 'date','asset', pillars)
      - "coverage"       : dict per source with earliest/latest/n_obs/n_assets

    Difference vs 731d loader: `ohlcv_returns` is derived from the 11yr sqlite
    (via r97_panel_11yr.freeze_universe + to_wide + pct_change), not from the
    1h parquet at /Volumes/CometCloudAI/data/ohlcv/.

    TODO: Once §OHLCV-EXTENSION-RESOLVE-COMPLETE lands, fill in the body below.
    The current body is a SKETCH that:
      1. Calls freeze_universe() to get Panel11yr
      2. Pivots long → wide via to_wide(panel, "close")
      3. Computes daily returns (pct_change)
      4. Aligns to the funding-coverage window (R62/R76 floor ~2023-05)
      5. Loads funding + cis from their original sources (unchanged)

    Raises FileNotFoundError if the sqlite is missing — this is intentional
    so the smoke tests can pin "skeleton present, panel absent" without
    needing the rebuild to have completed.
    """
    if not db_path.exists():
        raise FileNotFoundError(
            f"11yr panel DB not found at {db_path}. "
            f"Awaiting §OHLCV-EXTENSION-RESOLVE-COMPLETE from Minimax-A. "
            f"Once confirmed, this loader will consume the rebuilt panel."
        )

    # TODO(round-3-body): replace this minimal stub with the full implementation
    # once the panel exists. The stub returns the SAME shape so the smoke tests
    # can pin the contract; the actual freeze_universe + pivot + pct_change
    # wiring lands after §OHLCV-EXTENSION-RESOLVE-COMPLETE.
    panel = freeze_universe(db_path=db_path, min_span_days=min_span_days,
                            verbose=False)
    close_wide = to_wide(panel, "close")
    rets = close_wide.pct_change()

    # Funding + CIS still from their original sources (no 11yr equivalent)
    cis_long = load_cis_history_wide()
    tradeable = sorted(set(cis_long["asset"]) & set(rets.columns))
    funding_daily = load_funding_daily(assets=tradeable)
    if not funding_daily.empty:
        f_lo, f_hi = funding_daily.index.min(), funding_daily.index.max()
        rets = rets.loc[(rets.index >= f_lo) & (rets.index <= f_hi)]

    coverage = {
        "funding": {
            "earliest": str(funding_daily.index.min().date()) if not funding_daily.empty else None,
            "latest": str(funding_daily.index.max().date()) if not funding_daily.empty else None,
            "n_obs": int(funding_daily.shape[0]),
            "n_assets": int(len(set(tradeable) & set(funding_daily.columns))),
        },
        "ohlcv_returns": {
            "earliest": str(rets.index.min().date()),
            "latest": str(rets.index.max().date()),
            "n_obs": int(rets.shape[0]),
            "n_assets": int(rets.shape[1]),
            "source": f"binance_spot@{db_path}",
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
        "ohlcv_returns": rets,
        "cis_long": cis_long,
        "coverage": coverage,
    }


# === Verdict (placeholder until round-3 lands) ===============================
def round3_disclosure_default() -> dict:
    """Default disclosure for round 3 — `is_11yr_R77 = False` until the
    round-3 run actually clears the 3-check + M-WO-1 gauntlet on the 11yr panel.

    A round-3 SUCCESSFUL run flips `is_11yr_R77 = True`. Until then, this is
    the honest disclosure per Lesson #92.
    """
    return {
        "is_11yr_R77": False,  # FLIPS to True ONLY on round-3 success
        "is_post_2023_funding_coverage_sleeve": True,  # still true on 11yr panel
        "R46_full_11yr_leg_status": "PENDING_ROUND3_RUN",
        "frozen_weights_unhashed": True,
        "panel_source": f"binance_spot@{DB_PATH}",
        "min_span_days": int(MIN_SPAN_DAYS),
        "skeleton_status": "PRESENT_BODY_AWAITING_RESOLVE_COMPLETE",
    }


def main() -> int:
    """CLI: print skeleton status + acceptance floor. Does NOT load data."""
    print("=" * 72)
    print("R77 multicycle ROUND 3 — 11yr panel bridge (skeleton)")
    print("=" * 72)
    print()
    print(f"  Panel DB path : {DB_PATH}")
    print(f"  Panel exists  : {'✅ YES' if DB_PATH.exists() else '❌ NO (awaiting §OHLCV-EXTENSION-RESOLVE-COMPLETE)'}")
    print(f"  Min span days : {MIN_SPAN_DAYS}")
    print()
    print("  Frozen weights (unhashed):")
    print(f"    w_R46 = {R77_FROZEN_W_R46}")
    print(f"    w_R62 = {R77_FROZEN_W_R62}")
    print(f"    w_R76 = {R77_FROZEN_W_R76}")
    print()
    print("  Round-3 verdict grammar:")
    print(f"    {VERDICT_R3_REGIME_CANDIDATE}")
    print(f"    {VERDICT_R3_INSUFFICIENT_FUNDING}")
    print(f"    {VERDICT_R3_FROZEN_UNHASHED}")
    print()
    disc = round3_disclosure_default()
    print("  Default disclosure (flips on successful round-3 run):")
    for k, v in disc.items():
        print(f"    {k} = {v}")
    print()
    if not DB_PATH.exists():
        print("  → Panel absent; skeleton is import-safe but load_r77_panel_11yr()")
        print("    will raise FileNotFoundError until §OHLCV-EXTENSION-RESOLVE-COMPLETE.")
    return 0


# === Round-3 wrapper (post-processes 731d verdict for the 11yr panel) =========
def _translate_verdict_to_r3(v731d: str) -> str:
    """Translate 731d verdict string to round-3 grammar.

    The 731d verdict grammar strings stay valid; round-3 just appends `_ON_11YR`
    so the language of the verdict is unambiguous about which panel produced it.
    Lesson #92 applies: do not silently widen the claim — `is_11yr_R77 = True` is
    only ever set when the round-3 run actually clears 3-check + M-WO-1.
    """
    return {
        VERDICT_731D_REGIME_CANDIDATE: VERDICT_R3_REGIME_CANDIDATE,
        VERDICT_731D_INSUFFICIENT_FUNDING: VERDICT_R3_INSUFFICIENT_FUNDING,
    }.get(v731d, v731d)


def report_r77_layered_round3(w_r76: float = R77_FROZEN_W_R76) -> dict:
    """Build the round-3 layered report on the 11yr panel.

    Thin wrapper around `report_r77_layered()` from the 731d module:
      1. Loads the panel from sqlite via `load_r77_panel_11yr()`.
      2. Calls the 731d `report_r77_layered()` to get the 4-layer analysis
         (r46_full / r46_funding_window / r77_full / r77_funding_window).
      3. Translates verdict strings to `_ON_11YR` grammar.
      4. Updates disclosure to mark `is_11yr_R77 = True` ONLY IF the
         funding-coverage layer clears 3-check + M-WO-1 (Lesson #92).
      5. Adds round-3 metadata (panel source, min_span_days, generated_at).

    Raises FileNotFoundError when the 11yr sqlite is absent (see
    `load_r77_panel_11yr()`).

    Returns the round-3 verdict dict (also written to disk by `run()`).
    """
    panels = load_r77_panel_11yr()
    v731d = report_r77_layered(panels, w_r76=w_r76)

    # Translate the primary verdict to ON_11YR grammar
    primary_r3 = _translate_verdict_to_r3(v731d["verdict"]["primary"])

    # The funding-coverage layer is what determines the round-3 disclosure flip.
    # If the 731d run cleared it on the longer panel, then R77 IS 11yr-honest.
    funding_layer = v731d["layers"]["r77_funding_coverage_window"]
    round3_success = (
        primary_r3 == VERDICT_R3_REGIME_CANDIDATE
        and funding_layer["passes_all"]
        and funding_layer["episodes"]["n_episodes"] >= 8  # EPISODE_COUNT_FLOOR
    )

    # Compose round-3 verdict
    v3 = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "module": "src.research.validation.r77_multicycle_round3_11yr",
        "parent_module": "src.research.validation.r77_multicycle_revalidation",
        "panel_source": f"binance_spot@{DB_PATH}",
        "min_span_days": int(MIN_SPAN_DAYS),
        "coverage": v731d["coverage"],
        "funding_window": v731d["funding_window"],
        "layers": v731d["layers"],
        "frozen_weights": v731d["frozen_weights"],
        "verdict": {
            **v731d["verdict"],
            "primary": primary_r3,
            "round3_success": bool(round3_success),
            "grammar": [
                VERDICT_R3_REGIME_CANDIDATE,
                VERDICT_R3_INSUFFICIENT_FUNDING,
                VERDICT_R3_FROZEN_UNHASHED,
            ],
        },
        "disclosure": {
            **v731d["disclosure"],
            "is_11yr_R77": bool(round3_success),  # FLIPS to True on round-3 success
            "R46_full_11yr_leg_status": "COMPLETED_ON_11YR_PANEL" if round3_success
                                          else "REFUTED_ON_11YR_PANEL",
            "panel_length_years": (
                (pd.Timestamp(v731d["coverage"]["ohlcv_returns"]["latest"]) -
                 pd.Timestamp(v731d["coverage"]["ohlcv_returns"]["earliest"])).days / 365.25
            ),
        },
    }
    return v3


def _json_default(obj):
    """Handle numpy / pandas types for JSON serialization."""
    if hasattr(obj, "item"):
        return obj.item()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"not serializable: {type(obj)}")


def run(out_dir: Path) -> dict:
    """Execute round-3 report and write JSON + MD to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    verdict = report_r77_layered_round3()

    json_path = out_dir / "verdict.json"
    with open(json_path, "w") as f:
        json.dump(verdict, f, indent=2, default=_json_default)
    print(f"Wrote: {json_path}")

    md_lines = [
        f"# R77 multicycle revalidation — ROUND 3 — {verdict['generated_at']}",
        "",
        "## Panel source",
        "",
        f"- DB path: `{verdict['panel_source']}`",
        f"- Min span days: `{verdict['min_span_days']}`",
        f"- Panel length: `{verdict['disclosure']['panel_length_years']:.2f} years`",
        "",
        "## Coverage meta",
        "",
    ]
    for k, v in verdict["coverage"].items():
        extra = f", source `{v['source']}`" if "source" in v else ""
        md_lines.append(
            f"- **{k}** — earliest `{v.get('earliest', 'N/A')}`, latest `{v.get('latest', 'N/A')}`, "
            f"n_obs `{v.get('n_obs', 0)}`, n_assets `{v.get('n_assets', 0)}`{extra}"
        )
    md_lines += [
        "",
        "## Layers (round-3 — same 4-layer structure as 731d, anchored on 11yr sqlite)",
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
        "## Verdict (round-3 grammar)",
        "",
        f"- **Primary**: `{verdict['verdict']['primary']}`",
        f"- **Round-3 success**: `{verdict['verdict']['round3_success']}`",
        f"- **Honesty marker**: `{VERDICT_R3_FROZEN_UNHASHED}` (always on)",
        f"- n_episodes on funding window: `{verdict['verdict']['n_episodes_on_funding_window']}`",
        f"- 3-check on funding window: `{verdict['verdict']['three_check_passes_on_funding_window']}`",
        "",
        "## Disclosure",
        "",
        f"- `is_11yr_R77 = {verdict['disclosure']['is_11yr_R77']}`",
        f"- `R46_full_11yr_leg_status = {verdict['disclosure']['R46_full_11yr_leg_status']}`",
        f"- `panel_length_years = {verdict['disclosure']['panel_length_years']:.2f}`",
        f"- Frozen weights unhashed: `{verdict['disclosure']['frozen_weights_unhashed']}`",
        "",
    ]
    md_path = out_dir / "REPORT.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    print(f"Wrote: {md_path}")
    return verdict


if __name__ == "__main__":
    sys.exit(main())
