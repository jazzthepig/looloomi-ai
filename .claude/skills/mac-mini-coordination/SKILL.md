---
name: mac-mini-coordination
description: Governs all coordination between Seth/Austin (Cowork) and Minimax (Mac Mini / CometCloud local engine). Use this skill when: working with Shadow/ files, proposing schema changes to the CIS push interface, assigning tasks to Minimax, reading MINIMAX_SYNC.md, or any time the words "Mac Mini", "Minimax", "cis_push", "cis_scheduler", "data_fetcher", "local engine", "Shadow", or "interface contract" appear in context. Hard ownership rules are enforced by this skill — read before touching anything related to the local scoring stack.
---

# Mac Mini Coordination — Ownership Boundaries + Protocol

## Ownership rules (hard — no exceptions)

| Agent | Owns | Cannot touch |
|-------|------|--------------|
| **Seth / Austin** (Cowork) | `src/`, `dashboard/`, docs, `.claude/`, `MINIMAX_SYNC.md` | `/Volumes/CometCloudAI/cometcloud-local/`, `Shadow/` (read-only) |
| **Minimax** (Mac Mini) | `/Volumes/CometCloudAI/cometcloud-local/`, `/Volumes/CometCloudAI/freqtrade/`, `/Volumes/CometCloudAI/data/` | `src/`, `dashboard/`, `Shadow/` |
| **Shadow/** | READ-ONLY reference for Seth. Never `git add` Shadow/ files. | N/A — never write |

Shadow/ is a mirror of the Mac Mini's `cometcloud-local/` code, kept for reference. Minimax manually applies changes to the actual paths. **Shadow/ is never committed to git.**

---

## The MINIMAX_SYNC.md protocol

`MINIMAX_SYNC.md` at the repo root is the sole coordination channel between Seth and Minimax. It is a file-based protocol — no API calls between the two agents.

**What goes in MINIMAX_SYNC.md:**
- `§1` — Interface contract: field names, types, enum values, timestamp format for `/internal/cis-scores` POST body
- `§2` — Schema change proposals (Seth proposes → Minimax confirms before either side implements)
- `§3` — Task assignments to Minimax (P0/P1/P2 with acceptance criteria)
- `§4` — Status confirmations from Minimax (timestamped, signed)

**Protocol for schema changes:**
1. Seth documents the proposed change in MINIMAX_SYNC.md §2 FIRST
2. Minimax reads and confirms (or counter-proposes) in the same file
3. Only after both sides confirm: Seth updates `src/api/routers/cis.py`, Minimax updates `cis_push.py`
4. No unilateral changes to the interface contract

**Never bypass MINIMAX_SYNC.md for interface changes.** If Minimax changes the push payload shape without updating MINIMAX_SYNC.md, the Railway endpoint will silently drop the new fields. This has happened before.

---

## The local scoring stack (read-only reference)

Minimax runs on Mac Mini M4 Pro (48GB RAM / 1TB). The local engine:

```
cis_v4_engine.py       → 8-asset-class scoring engine (F/M/O/S/A pillars)
cis_scheduler.py       → Job manager, pushes CIS scores every ~30 min
cis_push.py            → POSTs scores to Railway /internal/cis-scores with INTERNAL_TOKEN
data_fetcher.py        → DeFiLlama + CoinGecko + Binance (CCXT) + yfinance
config.py              → ASSET_UNIVERSE, grade thresholds, compliance signals
```

**Mac Mini data sources that Railway cannot use:**
- Binance via CCXT — geo-blocked on Railway US. Mac Mini has no restriction.
- EODHD API — TradFi prices + earnings calendar. Key in Mac Mini env, not Railway.
- LM Studio (Qwen3 35B via Ollama) — Macro Brief narrative generation. Mac Mini only.

**Redis bridge:**
- Key: `cis:local_scores` — Minimax writes, Seth reads (via `GET /api/v1/cis/universe`)
- All other `cis:*` keys are Seth's. Minimax never writes to them.
- TTL: 2h. If stale, Railway falls back to T2 (CoinGecko-based estimation).

---

## Current T1/T2 split

| Tier | Source | Badge | Refresh | Asset count |
|------|--------|-------|---------|-------------|
| T1 | Mac Mini (full CIS engine) | `CIS PRO · LOCAL ENGINE` (green) | ~30 min | ~25 assets |
| T2 | Railway CoinGecko estimation | `CIS MARKET · ESTIMATED` (amber) | On-request | ~59 assets |

When Mac Mini scores are in Redis, they take priority for the assets they cover. T2 fills the gaps. Final universe = merge of T1 + T2, deduplicated by symbol.

---

## Task assignment to Minimax

Write tasks to `MINIMAX_SYNC.md §3` using this format:

```markdown
### Task [P0/P1/P2]: [title]
**Status:** pending
**Acceptance criteria:**
- [specific, testable criterion]
**Notes:** [context, links to relevant code]
**Assigned:** [date]
```

Do not assign Minimax tasks verbally in Cowork chat. The Mac Mini does not read the chat. File-based only.

---

## What to do when Mac Mini is unreachable

1. Check `MINIMAX_SYNC.md §4` for last status update from Minimax
2. Check Railway `/api/v1/cis/universe` — is `source: "local_engine"` still appearing?
   - Yes → Mac Mini pushed recently; last scores are in Redis (2h TTL)
   - No → Mac Mini has stopped pushing. T2 fallback active.
3. Check CLAUDE.md `Production health` section for known outages
4. If >2h without T1 data: per MULTI_AGENT_PROTOCOL.md §7, this is an escalation to Jazz

---

## References

- `MINIMAX_SYNC.md` — live coordination protocol + interface contract + task backlog
- `MULTI_AGENT_PROTOCOL.md` — agent roles, automation levels, escalation procedures
- `CIS_METHODOLOGY.md` — full CIS scoring spec (what Minimax implements locally)
- `Shadow/cometcloud-local/cis_push.py` — what the push payload looks like (read-only)
