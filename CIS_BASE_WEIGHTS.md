# CIS canonical base weights — single source of truth (GRADE-ALIGN, 2026-06-30)

**Status:** Proposed by Seth, pending Jazz sign-off. Once approved, BOTH engines adopt this
table **verbatim**: T1 `cis_v4_engine.py:308 BASE_WEIGHTS` (enum-keyed, `R`≡`O`) and T2
`cis_provider.py:1731 _BASE_WEIGHTS` (string-keyed). They currently diverge (see §GRADE-ALIGN
step-2 in MINIMAX_SYNC) — that divergence is why "same pillars → same grade across engines"
fails. This file resolves it.

Pillars: **F** Fundamental · **M** Momentum/market-structure · **O** On-chain / risk-adjusted
quality · **S** Sentiment · **A** Alpha-independence. Each row sums to 1.00. These are
**regime-neutral** — regime is applied as a *separate* multiplier on top (Option B); the grade
is computed from the regime-neutral weighted sum (`raw_cis_score`).

| Asset class | F | M | O | S | A | Rationale |
|---|---|---|---|---|---|---|
| Crypto (generic) | 0.25 | 0.25 | 0.20 | 0.15 | 0.15 | balanced beta; no single pillar dominates |
| L1 | 0.30 | 0.25 | 0.20 | 0.15 | 0.10 | network value (fundamentals) leads; low idiosyncratic alpha |
| L2 | 0.30 | 0.25 | 0.20 | 0.15 | 0.10 | same logic as L1 |
| DeFi | 0.25 | 0.25 | 0.25 | 0.15 | 0.10 | on-chain revenue/TVL is real cashflow → O elevated |
| RWA | 0.35 | 0.20 | 0.20 | 0.15 | 0.10 | backed by real assets/cashflows → fundamentals dominate |
| Infrastructure | 0.30 | 0.25 | 0.20 | 0.15 | 0.10 | adoption + fundamentals; momentum secondary |
| AI | 0.20 | 0.30 | 0.20 | 0.15 | 0.15 | narrative/momentum-led, some real usage |
| Gaming | 0.20 | 0.30 | 0.15 | 0.25 | 0.10 | momentum + community sentiment drive |
| NFT | 0.15 | 0.25 | 0.15 | 0.30 | 0.15 | sentiment-dominant, weak fundamentals |
| Memecoin | 0.10 | 0.30 | 0.10 | 0.40 | 0.10 | sentiment + momentum are ~everything; no cashflow/on-chain value |
| US Equity | 0.35 | 0.25 | 0.20 | 0.10 | 0.10 | earnings/fundamentals lead; O = quality/risk-adjusted factor |
| US Bond | 0.35 | 0.10 | 0.30 | 0.10 | 0.15 | rates/credit fundamentals + risk-adjusted dominate; momentum minimal |
| Commodity | 0.25 | 0.30 | 0.15 | 0.20 | 0.10 | supply/demand fundamentals + trend; macro sentiment |
| FX | 0.25 | 0.25 | 0.20 | 0.20 | 0.10 | macro fundamentals + trend + risk sentiment |
| EM Equity | 0.30 | 0.25 | 0.15 | 0.20 | 0.10 | fundamentals + momentum, higher sentiment beta than DM |
| Real Estate | 0.40 | 0.15 | 0.20 | 0.15 | 0.10 | NAV/cashflow fundamentals dominate |
| Alternative | 0.25 | 0.20 | 0.25 | 0.15 | 0.15 | balanced, risk-adjusted-tilted |

**Key reconciliations from the divergence:**
- **Crypto:** chose T2's 25/25/20/15/15 (balanced) over T1's 20/25/20/15/20 (over-weights alpha
  for assets that are mostly beta).
- **US Bond:** neither old table was right — T1 over-weighted S (0.30, bonds aren't sentiment-led),
  T2 under-weighted O (0.10). Set F+O dominant (rates/credit + risk-adjusted), S/M minimal.
- **Memecoin:** pushed S to 0.40 and cut F/O to 0.10 — fundamentals and on-chain "quality" are
  noise for memecoins; price is pure attention/flow.
- **US Equity:** O kept meaningful (0.20) as a quality/risk-adjusted factor (not the literal
  on-chain pillar, which is N/A for equities — the scorer maps it to a quality proxy).

**Adoption checklist (after Jazz approves):**
1. T1 (Minimax): replace `BASE_WEIGHTS` values to match this table exactly; `R`→`O` naming.
2. T2 (Seth): replace `_BASE_WEIGHTS` to match.
3. Acceptance: feed identical pillars `[F,M,O,S,A]` for each class to both engines →
   `raw_cis_score` equal within 0.1; combined T1+T2+protocol grade histogram believable per regime.
4. Bump `SCHEMA_VERSION` 1.0 → 1.1, note the weight reconciliation in MINIMAX_SYNC §2.
