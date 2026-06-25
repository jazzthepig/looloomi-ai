# DATA CAPTURE SPEC — v0.1 (2026-06-19)

*What the methodology (`METHODOLOGY_CORE.md`) requires us to collect, from where,
and who owns it. Principle: most of what we need is on-chain **sign + composition**
(direction & who), not precise magnitude — cheaper to capture, and crypto-native
(TradFi can't see it). Magnitude is only needed for the capacity term.*

Legend — Source: 🔗 on-chain (our edge, self-compute) · 🛰 consume giant (Nansen/
Glassnode/Kaiko/Arkham) · 🆓 free/public. Status: ✅ have · 🟡 partial · 🔴 to build.
PIT = point-in-time history required for honest backtest (see OPEN #3).

| # | State variable | Concrete data | Source | Status | PIT? | Owner |
|---|---|---|---|---|---|---|
| D1 | Net marginal flow (SIGN) | exchange net in/outflow, stablecoin flow | 🔗 / 🛰Glassnode | 🔴 | yes | Minimax |
| D2 | Participant identity (smart/retail) | smart-money net buy/sell; early-fund/whale accumulate vs distribute | 🛰Nansen/Arkham | 🔴 | **yes (hard)** | Minimax |
| D3 | Propagation stage (出圈) | holder concentration (HHI / top-N share), holder-count growth, avg balance ↓ | 🔗 self-compute | 🔴 | yes | Minimax |
| D4 | Attention diffusion | Google Trends, exchange App-Store rank, mainstream-media mentions | 🆓 | 🔴 | partial | Seth |
| D5 | Retail fragility | retail share of marginal flow × realized vol | 🔗 + compute (D2,D3) | 🔴 | yes | Seth |
| D6 | True depth / capacity | order-book depth, impact curve per venue | 🛰Kaiko / exchange | 🔴 | no | Minimax |
| D7 | Crowding / positioning | OI, funding rate, basis | 🆓 CCXT (local) | 🟡 | partial | Minimax |
| D8 | Value anchor V | crypto: TVL/fundamentals · tok-equity: underlying spot · RWA: NAV | ✅ EODHD/DeFiLlama | 🟡 | yes | Seth |
| D9 | Momentum / price | OHLCV (daily have; 4h local) | ✅ | ✅ | yes | shared |

## Hard dependencies / risks (carry from METHODOLOGY_CORE OPEN list)

- **D2 + PIT (OPEN #1, #3):** "smart" must be defined point-in-time without hindsight,
  AND historical smart/flow labels must exist to backtest. If Nansen only exposes
  *current* labels, we **cannot** honestly prove the γ/stage edge → we downgrade to a
  declared reflection-layer heuristic, not a proven law. **Resolve before claiming alpha.**
  → Action: check Nansen/Arkham historical/PIT label availability + pricing.
- **Cross-asset (OPEN #4):** D1–D3 are crypto-native. For tokenized equity / RWA,
  holders are off-chain → these degrade. Scope the convergence index to where the data
  exists, or source an off-chain equivalent, before claiming cross-asset coverage.

## Capture priority (cheapest-honest-win first)

1. **D3 (holder concentration → dispersion)** — self-compute on-chain, no vendor cost,
   directly the 出圈 axis. Start here.
2. **D1 (exchange/stablecoin flow sign)** — Glassnode or on-chain; marginal-flow direction.
3. **D4 (attention diffusion)** — free; the out-of-circle confirm.
4. **D2 (smart/retail)** — gated on the PIT check above; do the feasibility check first.
5. **D6 (depth/impact)** — for the honest-capacity term; Kaiko or exchange depth.

## Build form

- Land into Supabase + Parquet (DuckDB research layer per the lean-stack decision).
- Each variable stored as **sign + composition + timestamp** (PIT-stamped) so backtests
  have no look-ahead. Magnitude stored only where capacity needs it (D6).
- Validation gate (`STRATEGY_VALIDATION` / METHODOLOGY §5) applies before any variable
  is allowed into CIS / Risk Meter as more than experimental.

*Companion: `METHODOLOGY_CORE.md`.*
