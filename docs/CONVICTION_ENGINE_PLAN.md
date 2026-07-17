# Conviction Engine — Architecture & Build Plan
### The AI-augmented beta-plus lane (Seth, 2026-07-15)

## 0. What this is (and what it is NOT)
A **quantamental idea-generation engine**: it *surfaces* a ranked watchlist of structural-winner
candidates (the HYPE archetype) for **discretionary human+AI conviction** — it does **not**
auto-trade. This is the honest form of the beta-plus lane after **R21** refuted the systematic
version (revenue-momentum-as-a-factor: IC −0.05). The alpha is judgment-led — a *specific* moat-
proving catalyst — so the engine's job is to do the deep-research legwork and put the best
candidates, with the evidence, in front of a decision-maker.

Grounded in real practice: Balyasny's AI research engine (LLM reasoning + internal models, agent
workflows) compresses days of research to hours; Point72's quantamental pods trade fundamental
research via quant methods. We build the crypto-native version, on rails nobody else has (24/7
on-chain, our CIS/cause stack).

**Scalability:** it points discretionary capital at large-cap structural winners held directionally
— capacity is the asset's liquidity, and our size doesn't erode the edge (unlike carry). This is
the lane Jazz selected precisely because it scales.

## 1. Architecture — compose the 4-layer stack we already have
A candidate must climb all four layers; each filters a *different* way to be wrong. R21's lesson:
no single layer predicts — the **conjunction** is the hypothesis.

```
   data products                     layer scorers                     fusion + surfacing
 ┌────────────────┐   ┌─────────────────────────────────────┐   ┌────────────────────────┐
 │ moat_map (L1)  │──▶│ L1 MOAT   structural-value score     │   │                        │
 │ news/macro RSS │   │           (durable capability?)      │   │  ConvictionScore =     │
 │ Binance px/vol │──▶│ L2 CATALYST  narrative×on-chain      │──▶│   gate(L1) ×            │──▶ /api/v1/conviction/watchlist
 │ DeFiLlama rev  │   │           (event proves moat + the   │   │   f(L2,L3,L4)          │     + MCP tool + UI panel
 │ CIS F/O pillar │──▶│           market already voting)     │   │   + LLM thesis         │     + watchlist persistence
 │ holders/NMA    │   │ L3 FUND-MOMENTUM  rev/fee/TVL accel   │   │   + drivers/evidence   │
 └────────────────┘   │           + reflexive-loop flag      │   │   + honest label       │
                      │ L4 TREND  price confirmation (timing) │   └────────────────────────┘
                      └─────────────────────────────────────┘
                                     ▲ LLM reasoning layer (LM Studio / cloud):
                                       event→moat classification (L2) + per-candidate thesis writeup
```

**What exists vs what to build:**
| Layer | Have | Build |
|---|---|---|
| L1 Moat | `src/data/narrative/moat_map.py` — capability/condition ontology, `Moat`, `MOAT_MAP` | **Expand** the ontology (small/curated today) + a moat-quality score |
| L2 Catalyst | `src/data/narrative/catalyst_detector.py` — narrative×on-chain coincidence, **HYPE-validated (z=9.63, 2026-01-27)** | Wire the **LLM** event→capability classifier (the narrative half); news feed already exists |
| L3 Fund-momentum | CIS F+O pillars (levels); DeFiLlama revenue/fees/TVL access verified | **NEW `fundamental_momentum.py`**: revenue/fee/TVL *acceleration* (rate-of-change) + **reflexive-loop flag** (buyback / fee-share / burn / real-yield) |
| L4 Trend | price momentum (have via factory) | Confirmation gate (breakout / above-trend) |
| Fusion | `conviction.py` (CIS-based) as a pattern | **NEW `conviction_engine.py`**: L1-gate × f(L2,L3,L4) → score + drivers |

## 2. Data products (inputs)
moat_map (curated) · macro/news events (`macro_events_scraper` — have) · Binance daily price+volume
(on-chain activation) · DeFiLlama daily revenue/fees/TVL (verified: Lido 1900d, Aave 2250d) ·
CIS F/O pillars · holder concentration (`holder_provider`) · NMA narrative. All already reachable.

## 3. The scoring model (honest, conjunction-first)
- **L1 gate (binary-ish):** does the asset have a *durable* structural capability (moat_map)? No moat → not a candidate (kills pumps).
- **L2 catalyst (0–1):** narrative event activates the moat AND on-chain activation confirms (volume/price z-score). The coincidence — narrative *without* activation = thesis waiting; activation *without* narrative = pump to fade.
- **L3 fundamental momentum (0–1):** is the moat becoming cash flow, *accelerating*? revenue/fee/TVL rate-of-change + reflexive-loop bonus. (R21: not a standalone signal → used as a *conjunction filter*, not a factor.)
- **L4 trend (0–1):** is price starting to confirm? (timing gate — enter on confirmation, per methodology; avoids catching the falling knife.)
- **ConvictionScore = L1_gate × (w2·L2 + w3·L3 + w4·L4)**, weights learned by the self-verification loop (§5), not hand-set. Output the *drivers* + which layers fired + the LLM thesis.

## 4. Surfacing (how it's consumed — discretionary)
- `GET /api/v1/conviction/watchlist` → ranked candidates: `{symbol, conviction_score, L1..L4 breakdown, reflexive_loop, thesis (LLM), drivers, first_flagged}`.
- MCP tool `cometcloud_get_conviction_watchlist` (agents consume it).
- UI panel (Diagnose/Intelligence) — the "Conviction Watchlist," honestly labeled *candidates for discretionary conviction, not a signal; positioning language only.*
- **Execution guidance** surfaced per methodology §3 (NOT auto-executed): convex sizing, pyramid on L4 confirmation, exit on **thesis break** (moat contested / catalyst fades / fundamental momentum rolls over / reflexive loop breaks).

## 5. Self-verification loop (this is what makes it real, not a screen)
Every surfaced candidate is logged as a dated prediction → the **prediction resolver** scores its
forward benchmark-relative return → we learn **which layer-combinations actually surfaced winners.**
The R21 hypothesis to prove: *the 4-layer conjunction predicts even though no single layer does.*
- Log to `conviction_watchlist_log` (dated) + resolve via the existing outcome pipeline.
- Learn `w2/w3/w4` + the L1 gate threshold from realized outcomes (champion/challenger).
- If the conjunction's hit-rate doesn't beat baseline after N candidates → refute honestly (R-ledger).
This turns a static screen into a self-tuning engine and gives every candidate provenance a PM can trust.

## 6. Build phases
- **P0 — L3 fundamental-momentum + reflexivity** (`fundamental_momentum.py`): DeFiLlama revenue/fee/TVL acceleration + reflexive-loop detector (buyback/fee-share/burn). Data access verified. *(≈ the one net-new data science piece.)*
- **P1 — Fusion scorer** (`conviction_engine.py`): compose L1 (moat_map) × L2 (catalyst_detector) × L3 × L4 → ConvictionScore + drivers. Deterministic, equal weights to start.
- **P2 — LLM reasoning layer**: event→moat classifier for L2's narrative half + per-candidate thesis writeup (LM Studio `LLM_BASE_URL`, cloud fallback). The Balyasny "days→hours" research step.
- **P3 — Surfacing**: `/api/v1/conviction/watchlist` + MCP tool + `conviction_watchlist_log` persistence + daily refresh loop.
- **P4 — Self-verification**: log→resolve→learn weights; champion/challenger on the layer weights; R-ledger if the conjunction fails.
- **P5 — UI + execution guidance**: Conviction Watchlist panel + convex-sizing / thesis-break guidance (advisory).

## 7. Guardrails & honesty
- **Surfaces, never trades.** Discretionary human+AI decision.
- **Conjunction-first (R21):** value is L1∧L2∧L3∧L4, not any single factor; proven only by the self-verification track record.
- **Coverage caveat:** moat_map is curated/small → P1 needs ontology expansion; a candidate absent from moat_map can't surface (accept, then widen).
- **Compliance:** positioning language only; no buy/sell; thesis is analysis, not advice.
- **LLM risk:** the L2 narrative classification is model-dependent → keep the deterministic on-chain-activation half as the hard confirmation so a bad LLM call can't manufacture a candidate.

## 8. Success metric
Not a backtest Sharpe (it's discretionary) but: **does the surfaced watchlist's forward hit-rate on
structural winners beat a naive quality/momentum screen**, measured live by the self-verification
loop — and does it flag the next HYPE early (L1+L2 firing before the price re-rating, as it did on
HYPE 2026-01-27). That's the honest bar.

## References
- [Balyasny AI research engine (OpenAI)](https://openai.com/index/balyasny-asset-management/) · Point72 quantamental pods · `CONVICTION_METHODOLOGY.md` · `REFUTATION_LEDGER.md` R21
