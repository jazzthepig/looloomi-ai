"""
C-13 P4 — manifest registration for cap-weighted ① nav_panel tables + mcap fields.

WHY THIS FILE EXISTS. Mac-side writers in `cometcloud-local/research/` write to
`nav_panel_rebalances`, `nav_panel_daily`, and add three columns
(`mcap_usd`, `adv_usd_20d`, `adv_screen_pass`) to the existing
`market_state_vectors` table. Per Rule 3, `cometcloud-local/` is not Seth's
lane and the AST walker in `src/api/schema_manifest.py` cannot follow those
imports, so without an explicit declaration here the offline manifest stays
blind to these tables — and `/internal/schema-drift` cannot flag a missing
migration as drift.

The declarations below mirror C-13 §2.2 DDL exactly. If a new column lands on
either table without being added here, the column drift guard (S-286) does not
catch it; that is the same shape as the eleven-table S-166 incident, where
writes succeeded-and-returned-False until somebody counted. A declaration
that goes stale is a silent hole, so this file is the single source of truth
for Seth-side awareness of these tables.

The test that pins this contract is `tests/test_c13_nav_panel_manifest_registered.py`.
"""
from __future__ import annotations

# Tables WRITTEN by Mac-side writers. Same shape as WRITES_TABLES in
# `src/data/entity/writer.py` (treasury_*), `src/data/market/cg_panel_sync.py`
# (cg_coin_map). Schema_manifest reads this at AST-walk time.
WRITES_TABLES = ("nav_panel_rebalances", "nav_panel_daily")

# Columns WRITTEN per table. Three columns on the existing market_state_vectors
# table (added by nav_writer.py) plus the new rebalance / daily NAV tables.
# Use frozenset because the values are hashed into the manifest's column set
# and we want declaration drift to be loud, not silent.
WRITES_COLUMNS = {
    "market_state_vectors": frozenset({
        "mcap_usd",           # snapshot mcap at the time the writer ran
        "adv_usd_20d",        # 20-day average daily volume in USD
        "adv_screen_pass",    # boolean: passed ADV ≥$5M/day screen
    }),
    "nav_panel_rebalances": frozenset({
        "symbol",             # uppercase ticker
        "weight",             # cap-clipped weight (40% ceiling)
        "mcap_usd",           # snapshot mcap at rebalance time
        "as_of",              # the trade_date the rebalance is anchored to
        "trade_date",         # the date the rebalance was written
    }),
    "nav_panel_daily": frozenset({
        "trade_date",         # the day's UTC date
        "nav",                # the ① NAV for the day
        "return_pct",         # daily return (decimal, not basis points)
    }),
}
