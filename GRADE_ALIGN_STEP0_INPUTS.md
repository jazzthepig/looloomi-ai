# §GRADE-ALIGN Step 0 — Methodology decision inputs (for quant)

**Status:** Three-way T1/T2 divergence flagged 2026-07-01 (§GRADE-ALIGN step-3). Frontend
grade-on-raw switch + `SCHEMA_VERSION` 1.0 → 1.1 are **HELD** until these calls land.
This doc is the focused input package for the methodology decision.

**Engines in scope:**
- **T1** — Mac Mini local scoring (`/Volumes/CometCloudAI/cometcloud-local/cis_v4_engine.py`)
- **T2** — Railway market estimation (`src/data/cis/cis_provider.py`)

**Stakes:** "Same pillars → same grade across engines" must hold for agents to consume
the two interchangeably. Today the acceptance test fails by accident on several assets
(US Bond, Commodity, Memecoin hit hardest). Resolution requires three calls below.

---

## Decision 1 — Pillar semantics

**The hidden divergence.** T1 and T2 use the same letter (`O` / `R`) for what are
**different pillars**:

| Slot | T1 letter | T1 actual (engine code) | T2 letter | T2 actual (engine code) |
|---|---|---|---|---|
| 3rd | **R** | Sharpe + Sortino + Max DD + WinRate + G/L ratio (`cis_v4_engine.py:655–704`) | **O** | ATH distance + drawdown estimate + supply/TVL health + derivatives adj (`cis_provider.py:1295–1364`) |
| 5th | **A** | Alpha independence (BTC/SPY divergence) | **A** | Alpha independence (BTC/SPY divergence) |
| Other 3 | F, M, S | Fundamental / Momentum / Sensitivity | F, M, S | Fundamental / Momentum / Sentiment |

**The semantic split is real, not nominal:**
- T1.R = "is the asset producing return per unit of risk?" (positive-space, returns)
- T2.O = "is the asset far from ATH / suffering drawdowns?" (negative-space, risk state)

### Three options for quant

| Option | Cost | Pro | Con |
|---|---|---|---|
| **(a) T1 wins** — T2 rewrites O to Sharpe/Sortino/Calmar | High (rewrite + need volatility/returns history) | Matches the `cis_provider.py:1188` vol-math extension path already started | Loses ATH/Drawdown info that's actually predictive (drawdown is a strong reversal signal) |
| **(b) T2 wins** — T1 renames R → O + recomputes ATH/Drawdown/Health | Medium (rename + recompute) | Keeps the on-chain + drawdown signal | Breaks T1 architecture (Sharpe lineage is its core strength) |
| **(c) Split into 6 pillars** — both engines add a new pillar | High (both engines) | Most principled; preserves both signals | Bigger refactor; changes the user-facing 5-pillar story; bigger SCHEMA bump |

### Recommendation
**Option (c) for principled correctness.** If that's too big a refactor right now,
**Option (b) is the next-best** (T2's on-chain + drawdown signal is what makes our
crypto CIS meaningful; T1's Sharpe family is a downstream use case that can be derived
from pillar scores, not a primary pillar).

→ **Quant call needed.**

---

## Decision 2 — Class taxonomy

**Current state (2026-07-05):**

| Engine | Classes | Missing vs T2 |
|---|---|---|
| T1 (cis_v4_engine.py `class AssetClass`) | 15 — L1, L2, DeFi, RWA, Infrastructure, Memecoin, Gaming, Crypto, US Equity, US Bond, Commodity, FX, EM Equity, Real Estate, Alternative | AI, NFT |
| T2 (cis_provider.py `_BASE_WEIGHTS` dict) | 17 — all 15 T1 classes + AI + NFT | — |

**The state has moved since the original §GRADE-ALIGN step-3 reply (2026-07-01):**
- T2 has absorbed T1's four "unique" classes (FX, EM Equity, Real Estate, Alternative).
- Only T2-only classes now: **AI, NFT** (2).
- No T1-only classes (T1 was already a subset of T2's coverage).

**Implication:** the taxonomy reconciliation is essentially solved by adding AI + NFT
to T1's enum + BASE_WEIGHTS. Two-line fix in T1 (one enum entry + one weight dict entry)
gives full parity.

### Recommendation
**Adopt T2's 17-class taxonomy verbatim into T1.** T1 adds `AI` and `NFT` enum members
+ entries in `BASE_WEIGHTS`. Both engines reference the same canonical list in
`CIS_METHODOLOGY.md` going forward.

→ **Quant sign-off needed** on:
1. The T2 weight values for AI + NFT (do they make sense — see table below)
2. Whether any future class needs adding now (e.g., "Stablecoin" as separate from Crypto)

---

## Decision 3 — Per-class weight values (the diff Seth found, now with full context)

For the **15 shared classes**, T1 and T2 differ on **8/15** (was 7/11 — T2 grew and
the diff expanded). Side-by-side:

| Class | T1 (F/M/R/O/S/A) | T2 (F/M/O/S/A) | Match? | Diff source |
|---|---|---|---|---|
| Crypto | 20/25/**20**/15/20 | 25/25/20/15/15 | ✗ | F & A flipped |
| L1 / L2 | 30/25/20/15/10 | 30/25/20/15/10 | ✅ | — |
| DeFi | 25/25/**25**/15/10 | 25/25/**25**/15/10 | ✅ | — |
| RWA | 35/20/20/15/10 | 35/20/20/15/10 | ✅ | — |
| Infrastructure | 25/25/20/**20**/10 | 30/25/20/15/10 | ✗ | F +5, S -5 |
| Memecoin | 15/20/15/**35**/15 | 10/30/10/**40**/10 | ✗✗ | T1 S-dominant; T2 M+S-dominant |
| Gaming | 20/25/20/20/15 | 20/30/15/25/10 | ✗ | M +5, S +5, A -5 |
| US Equity | 30/20/25/15/10 | 35/25/20/10/10 | ✗ | F +5, M +5, R -5 |
| US Bond | 15/15/**30**/**30**/10 | 35/10/**30**/10/15 | ✗✗ | F +20, M -5, S -20, A +5 (massive) |
| Commodity | 15/**30**/20/**25**/10 | 25/**30**/15/20/10 | ✗ | F +10, S -5, A -5 |
| FX | 15/25/20/**35**/5 | 25/25/20/20/10 | ✗ | F +10, S -15, A +5 |
| Real Estate | 35/15/25/20/5 | 40/15/20/15/10 | ✗ | F +5, R -5, S -5, A +5 |
| EM Equity | 25/25/20/20/10 | 30/25/15/20/10 | ✗ | F +5, R -5 |
| Alternative | 20/20/25/15/20 | 25/20/25/15/15 | ✗ | F +5, A -5 |
| T2-only (no T1 weight) | — | AI: 20/30/20/15/15 / NFT: 15/25/15/30/15 | n/a | need to add to T1 |

### Patterns observed
1. **T2 weights Fundamental more aggressively on TradFi** (US Equity, US Bond, EM Equity,
   Real Estate, Commodity all +5 to +20 vs T1). Consistent with the
   `cis_provider.py:1756–1771` regime-multiplier philosophy (fundamentals dominate in
   Tightening/Risk-Off).
2. **T1 weights Sentiment more on Memecoin** (35 vs 40; both high — it's the dominant
   pillar). Both engines agree Memecoin is sentiment-driven.
3. **US Bond is the most divergent** — T1 weights R/S 30/30 (treats it as a risk-managed
   asset); T2 weights F 35 + R 30 (treats it as a fundamentally-driven asset). Both are
   defensible; quant pick.
4. **Commodity** — T1 weights S 25 (sensitivity to macro), T2 weights M 30 (momentum-led).

### Recommendation
For the 8 mismatched classes, **adopt T2's values** in T1 (single source of truth =
`CIS_BASE_WEIGHTS.md`). Justification:
- T2 values are coherent with the regime-multiplier philosophy baked into T2's engine.
- T2 is the consumer-facing engine (Railway serves the API). Adopting T2 values in T1
  means user-visible grades stay aligned with internal scores after the SCHEMA bump.
- T1 becomes a "Mac-side equivalent" of T2's grade output (with local-only extras like
  `recommended_weight`, `class_rank`, `global_rank`).

If quant prefers the reverse (T2 adopts T1's values) the diff is larger — T1 values
on TradFi are systematically lighter on Fundamental, which would force a regime-
multiplier rewrite on T2.

→ **Quant call needed:** adopt T2 verbatim in T1, or vice versa, or build a fresh
canonical table from first principles.

---

## What ships after these three calls land

1. T1 `cis_v4_engine.py` adopts the canonical 17-class taxonomy + canonical weights
   (5-line enum→string fix already shipped 2026-07-04 + structural edit here).
2. T2 `cis_provider.py` keeps current weights (already canonical).
3. `CIS_METHODOLOGY.md` becomes the single source of truth — both engines reference it.
4. `SCHEMA_VERSION` bumps 1.0 → 1.1 in `MINIMAX_SYNC.md §2`.
5. Seth unblocks frontend grade-on-`raw_cis_score` switch (CISLeaderboard / AssetRadar /
   ProtocolIntelligence / CISWidget / H5) with regime as a separate exposure axis
   (signal + `recommended_weight`).
6. Acceptance test: `for asset in universe: assert grade(T1, asset) == grade(T2, asset)`
   — passes for all 84 assets.

**Until then:** T1 ≠ T2 by accident on 8/15 shared classes. Agents / LPs see different
grades for the same data depending on which engine served them. Acceptable as a known
inconsistency but documented.

---

## Acceptance criteria (proposed for quant sign-off)

1. **Pillar semantics:** pick (a), (b), or (c). Document in `CIS_METHODOLOGY.md §3`.
2. **Taxonomy:** add AI + NFT to T1 (or document if T1 explicitly drops them).
3. **Weights:** adopt T2 values verbatim (or document reverse). Update T1's
   `BASE_WEIGHTS` to match.
4. **Methodology doc:** `CIS_METHODOLOGY.md` lists the canonical 17 classes + weights +
   pillar semantics as a single source. Both engines reference it.
5. **Acceptance test:** `scripts/test_grade_align.py` runs the assertion in step 6 above
   (Seth will write; passes once decisions 1–3 land).

---

**Drafter:** Minimax-A · **Date:** 2026-07-05 · **For:** Jazz + quant methodology review
**Block on:** Three decisions above. Once landed, this file moves to `CIS_METHODOLOGY.md`
and a one-liner pointer lives here.