# DATA CAPTURE SPEC — v0.1 (2026-06-19)

*What the methodology (`METHODOLOGY_CORE.md`) requires us to collect, from where,
and who owns it. Principle: most of what we need is on-chain **sign + composition**
(direction & who), not precise magnitude — cheaper to capture, and crypto-native
(TradFi can't see it). Magnitude is only needed for the capacity term.*

**SOURCE POLICY (aligned 2026-06-25): CoinGecko Pro ($129, ALREADY PAID) is the PRIMARY
source — use it fully before adding any vendor.** It covers D1/D4/D6/D7/D9. Only two
things it can't do: D3 holder distribution → **Dune** (the one justified extra source),
and D2 wallet-level smart/retail → **Nansen, DEFERRED** (do not wire until we actually
reach D2). EODHD for TradFi (D8). Glassnode/Kaiko are *later upgrades only if CoinGecko
proves insufficient* — not now.

Legend — 🦎 CoinGecko Pro · 🟫 Dune · ⏸ Nansen (deferred) · 📊 EODHD · 🔗 self-compute.
Status: ✅ have · 🟡 partial · 🔴 to build.

| # | State variable | Concrete data | Source | Status | Owner |
|---|---|---|---|---|---|
| D1 | Net marginal flow (sign) | CG `/coins/{id}/tickers` volume by venue + GeckoTerminal DEX flow (true exchange-netflow = Glassnode, *later*) | 🦎 CoinGecko Pro | 🔴 | Seth |
| D2 | Participant identity (smart/retail) | wallet-level smart-money net buy/sell | ⏸ **Nansen — DEFERRED** | ⏸ | (later) |
| D3 | Propagation stage (出圈) | holder concentration (HHI / top-N / count) — `tokens_ethereum.balances_daily` | 🟫 Dune | 🟡 metric+adapter done, query_id pending | Minimax authors query |
| D4 | Attention diffusion | CG **trending** + `/coins/{id}` community_data (twitter/reddit/tg) + sentiment_votes + watchlist_users | 🦎 CoinGecko (Pro) | 🟡 collector built, upgrading to community/sentiment | Seth |
| D5 | Retail fragility | f(D3 dispersion-accel, D4 attention, realized vol) | 🔗 compute | 🔴 | Seth |
| D6 | Depth / capacity (partial) | CG `/coins/{id}/tickers` bid-ask spread per market + GeckoTerminal (Kaiko = later for true book) | 🦎 CoinGecko Pro | 🔴 | Seth |
| D7 | Crowding / positioning | CG **derivatives** (open interest, funding rate, basis) | 🦎 CoinGecko Pro | 🔴 | Seth |
| D8 | Value anchor V | crypto: TVL/fundamentals · tok-equity: underlying spot · RWA: NAV | 📊 EODHD + DeFiLlama + CG | 🟡 | Seth |
| D9 | Momentum / price | deep OHLCV (daily since 2013 backfilled ✅; 4h local) | 🦎 CoinGecko ✅ | ✅ | shared |

## Hard dependencies / risks

- **D2 / Nansen — DEFERRED (not a current dependency).** Wallet-level smart/retail is the
  one variable CoinGecko can't give. We decided 2026-06-25 to exhaust CoinGecko first and
  only buy Nansen when we actually reach D2. Until then γ/stage runs on D3 (holder
  dispersion) + D4 (attention) proxies and is labelled a **heuristic**, not a proven law.
  Do NOT wire Nansen now.
- **Cross-asset (OPEN #4):** D3 (on-chain holders) is crypto-native; tokenized equity / RWA
  holders are off-chain → it degrades there. Scope the index to where the data exists.

## Capture priority (CoinGecko-first — use the paid plan fully)

1. **D4 (attention)** — CoinGecko trending + community/sentiment/watchlist. Collector built; upgrade to community fields. *(Seth, now)*
2. **D7 (crowding)** — CoinGecko derivatives (OI/funding). Cheap, already paid. *(Seth)*
3. **D1 (marginal-flow sign)** — CoinGecko volume-by-venue + GeckoTerminal DEX. *(Seth)*
4. **D6 (depth, partial)** — CoinGecko `/tickers` bid-ask spread. *(Seth)*
5. **D3 (holder concentration)** — Dune query authoring (Minimax) → query_id → Seth's adapter.
6. D2 (Nansen) — deferred. D8 EODHD/DeFiLlama ongoing.

## Build form

- Land into Supabase + Parquet (DuckDB research layer per the lean-stack decision).
- Each variable stored as **sign + composition + timestamp** (PIT-stamped) so backtests
  have no look-ahead. Magnitude stored only where capacity needs it (D6).
- Validation gate (`STRATEGY_VALIDATION` / METHODOLOGY §5) applies before any variable
  is allowed into CIS / Risk Meter as more than experimental.

*Companion: `METHODOLOGY_CORE.md`.*
