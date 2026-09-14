"""CometCloud Layer II vault — ETH ERC-20 NAV tick infrastructure.

Tick-based, not daily. Per-minute mark-to-market. **Force-tick first**:
the validation loop is "force-tick → curl reads result → adjust → force-tick",
not "deploy → wait 24h → see if a mark appeared".

NOT Drift / NOT Solana. CometCloud's vault is on Ethereum, holding ERC-20.
v1 has no live chain integration — positions come from `vault_positions` table
(seeded by ops), prices come from the existing panel (binance_hist /
coingecko_pro_ohlc). Future source="on_chain" needs alchemy/infura wiring,
which is explicitly OUT of scope here.

Each tick writes one row to `vault_nav_tick`. The schema is:
- vault_state: durable (share_count, inception)
- vault_positions: many rows per vault, latest-as_of = current holding
- vault_nav_tick: one row per tick, the snapshot

`source` ∈ {"manual", "loop"} tells the operator which path wrote the row.
"""
