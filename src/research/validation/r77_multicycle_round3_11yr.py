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

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.research.validation.r97_panel_11yr import (
    DB_PATH, MIN_SPAN_DAYS, freeze_universe, to_wide, Panel11yr,
)
from src.research.validation.cis_quality_absorption import load_cis_history_wide
from src.research.validation.w5_forensics_external import load_funding_daily


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


if __name__ == "__main__":
    sys.exit(main())
