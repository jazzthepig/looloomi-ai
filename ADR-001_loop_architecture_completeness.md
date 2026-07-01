# ADR-001: Loop architecture — completeness review & what to build next

**Status:** Proposed
**Date:** 2026-06-30
**Deciders:** Jazz (sign-off), Seth/Austin (Railway), Minimax-A/B/C (Mac)

## Context

We are not building an autonomous executor — that is the partner's (友商) game. We are
the **judgment substrate**: make other agents able to decide, and close our own loop so we
can prove and teach what we sell (ARCHITECTURE.md). "Complete" therefore means two things:

1. **The internal metabolism runs end-to-end** — Sense → Synthesize → Judge → Act → Learn.
2. **The substrate is consumable** — other agents can discover, parse, trust, and act on
   our output, and we can prove the signal with our own closed loop.

This ADR scores both against the *verified* live state (loop_health.py is green end-to-end:
SENSE/SYNTHESIZE/JUDGE/ACT/LEARN all PASS as of 2026-06-30) and names the concrete next builds.

## Decision

The architecture is **structurally complete but thin** — every layer exists and flows, but
three things keep it from being a *load-bearing* loop: (a) trading throughput is off, so
Learn has almost no sample size; (b) the chain-side of the differentiator (D3 holders) isn't
plugged; (c) the substrate payload isn't yet decision-complete (provenance + outcomes). Plus
one structural fragility surfaced this session: **committed `dist/` drifts from source**.

Build order to make the loop load-bearing: **Throughput → D3 → Provenance/Outcomes →
Grade-align → kill the dist-drift class → self-reconciliation.**

## Completeness scorecard (verified, not asserted)

| Layer | State | Evidence | Gap |
|---|---|---|---|
| **Sense** | ✅ strong | CIS push fresh (43 assets, ~30min); D4 attention live; macro regime flowing | D3 holder data (Dune query_id pending) |
| **Synthesize** | ✅ strong | CIS 5-pillar + cause_proximity (evidence-tiered) + Risk Meter, all live on 58 assets | `stage` is None until D3; grade-scale incoherence across engines (§GRADE-ALIGN) |
| **Judge** | ✅ live | `/portfolio/risk-meter` reading 0.20, out-of-circle haircut → sizing | only consumed by the (off) rebalance sleeve |
| **Act** | 🟡 built, throttled | exit loops live; rebalance executor + preview live (58 targets, sane) | `REBAL_LOOP_ENABLED` off → no throughput; entry deduped to ~5 names |
| **Learn** | 🟡 wired, starved | IC loop self-tunes CIS via Redis; trade_results writing (3 rows post-fix) | sample size ~3-12; needs throughput to reach statistical power |
| **Substrate** | ✅ ~55-60% | MCP /mcp/sse (35 tools), A2A card, llms.txt, elizaOS plugin | payload not decision-complete (no per-field provenance + proven 30d outcomes) |

## Options considered (build sequence)

### Option A: Features-first (more signals, more pages)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Med |
| Loop value | **Low** — adds surface without proving the existing loop |
| Risk | Re-introduces "imposter" breadth-over-depth |

**Cons:** violates the moat filter (anything easy ≠ moat) and the "don't claim unproven" rule.

### Option B: Throughput-first, then depth, then consumability ⭐
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low→Med, incremental |
| Loop value | **High** — turns a thin loop into a load-bearing one with real outcomes |
| Risk | Low (all reversible; paper sleeve, gated flags) |

**Pros:** each step feeds the next (throughput → Learn data → provable outcomes → consumable
substrate); matches the substrate KPI; nothing speculative.

## Trade-off analysis

The binding constraint is **not code — it's proof**. Every downstream value (substrate
credibility, LP track record, agent trust) depends on the Learn layer having real outcomes,
which depends on Act throughput. So sequencing throughput first dominates: it's the cheapest
unlock (one env flag, already verified safe) with the highest loop leverage. Depth (D3) and
consumability (provenance) compound on top of accumulating outcomes — doing them first would
mean shipping unproven claims, which our own discipline forbids.

## Action items (prioritized, with owners)

1. [ ] **Throughput on** — set `REBAL_LOOP_ENABLED=1` (verified-safe preview: 37% gross,
   diversified). Starts METER_REBAL volume → trade_results → Learn sample size. *(Jazz)*
2. [ ] **D3 chain layer** — author the Dune holder-concentration query → `query_id` →
   `dune_holder_metrics()` → lights up cause_proximity `stage`. *(Minimax-A → Seth)*
3. [ ] **Decision-complete payload** — per-asset provenance (source + confidence + as-of +
   methodology link) + 30-day outcome stats, in one universe call. *(Seth, after #1 data flows)*
4. [ ] **§GRADE-ALIGN** — adopt Option B (grade on absolute quality; regime → signal/weight);
   acceptance = combined grade histogram believable in every regime. *(Jazz sign-off → Minimax + Seth)*
5. [ ] **Kill the dist-drift class** — see Consequences; move frontend build into Railway/CI
   so served `dist/` can't lag source (this session, Risk Meter was built but invisible because
   committed dist was stale). *(Seth)*
6. [ ] **Self-reconciliation** — extend loop_health into an agent/script that diffs
   contract↔live↔Shadow and emits fix suggestions (machine catches its own drift). *(Seth)*

## Consequences

- **Easier:** once #1+#2 land, every claim we make to a consuming agent is backed by our own
  closed-loop outcomes — the substrate becomes defensible, not aspirational.
- **Harder / to revisit:** the **committed-`dist/` model** is a standing fragility — source and
  served frontend drift silently (proven this session). Until #5, every frontend change needs a
  manual rebuild+commit or it's invisible live. This is the one genuinely *architectural* debt;
  the rest is sequencing.
- **Watch:** throughput (#1) increases trade_results volume → keep the IC loop's outlier/
  sentinel guards honest (the −94% blow-up was exactly this class of bug).
```
