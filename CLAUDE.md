# CLAUDE.md — CometCloud AI / Looloomi

> **⭐ SESSION START: read `MEMORY.md` (facts index, 30s) then `PROJECT_STATE.md` (living state) FIRST.
> Update PROJECT_STATE LAST.** Never trust memory of what's committed — run `git status` /
> `git rev-list origin/main..HEAD` before describing any "pending push".

## Source-of-truth map (one table, no scattered prose)

| Question | Read | Write discipline |
|---|---|---|
| What's true right now / in flight | `PROJECT_STATE.md` | **≤80,000 chars**; update same turn work lands; `**Last updated:**` line stays at the TOP |
| Long-term facts index | `MEMORY.md` | **≤3,400 CHARACTERS** (not bytes — the file is bilingual and CJK costs 3 B/char; reading time scales with chars). One line per fact; evict stale; **if a test already enforces it, the test is the memory** |
| Why a thing landed / build log | `PROJECT_STATE_LOG.md` | append-only; **NOT read at session start** — grep it, don't read it |
| Experiment truth (R/S/M-numbers) | `REFUTATION_LEDGER.md` | APPEND-ONLY at EOF; claim heading before body; **grep, never read whole** (577k chars) |
| Cross-lane coordination | `MINIMAX_SYNC.md` (gitignored) | **≤80,000 chars**; append §sections; syncs Mac-side, not via git. Anything dated >5d and settled → `MINIMAX_SYNC_ARCHIVE.md`; **still open ⇒ re-raise in §IN-FLIGHT, don't leave it in place** |
| Strategy truth / frozen cells | `STRATEGY_PLAYBOOK.md` | |
| The soul / north star | `ARCHITECTURE.md` | read when a decision touches what we ARE |
| Behavioral-edge doctrine | `docs/TRADER_TOM_DOCTRINE.md` | read before building any sleeve |
| **Mining output — where the research actually IS** | `Shadow/cometcloud-local/_reports/` (`absorb_input/` = R-number + vector_mine summaries, 217 files) | Minimax lane writes it; Seth/Austin **READ it before claiming a result does not exist** |
| Full history | `git log` | |

**⚠️ "NOT authority" ≠ "not worth reading" — this cost real work (2026-08-19).** Rule #2 below
says Shadow is read-only and drifts, and that is about the *contract*: never take a schema or a
config from it. It says nothing about the RESEARCH in it, and the source-of-truth table did not
mention `_reports/` at all. Reading the rule as "ignore Shadow" led Seth to survey four
directories, find one verifiable backtest, and tell Jazz we did not have more — while
`_reports/absorb_input/` held 14 R-number summaries including R70's held-out OOS grid, the single
best-disciplined result we own. **Before saying a result does not exist, grep `_reports/`.**

**Cold-start budget is enforced, not advisory** (`tests/test_cold_start_contract.py`, S-165).
Only MEMORY.md was capped, so the cost moved next door: PROJECT_STATE reached 315k chars
(~99k tokens **per lane per session**) and MINIMAX_SYNC 150k, while both contained headings
that already called themselves history and neither had ever been split. A cap with too narrow
a scope doesn't just miss things — it redirects attention away from them.

## Who I'm working with

**Jazz** — founder, sole decision-maker, product lead. TradFi/econ/blockchain/AI background,
EN/中文 bilingual. Direct, fast, execution over deliberation. Match his language; peer tone;
no padding. Make obvious implementation decisions yourself — do and report. If stuck, say so
immediately. Internals can be rough; interfaces cannot.

**You** — Seth (technical execution, Sabastian Bath) and Austin (systems/architecture).
Collaborative peer, not assistant. Build first, report after.

**Minimax** — Mac Mini engine operator (Claude Code agent on MiniMax M3). Owns
`/Volumes/CometCloudAI/cometcloud-local/` (cis_v4_engine, scheduler, data_fetcher, cis_push).
Coordinate via `MINIMAX_SYNC.md` before touching anything Mac-side.

**Nic** — senior network lead; sales channels + institutional relationships.

## What we're building

**CometCloud AI** — crypto Fund-of-Funds platform + intelligence ecosystem for institutional /
family-office / HNW across APAC; HK base. AI-curated on-chain FoF on Solana, OSL-stablecoin
denominated. Target $500M AUM, 1% mgmt + performance. Built for human LPs and AI agents equally.
**Looloomi** — the AI-agent / Web3 tech arm powering it.

**Philosophy (full text: ARCHITECTURE.md):** technology and art are one impulse; we build early
infrastructure for human+AI convergence. The deepest object is not the Asset but the
**Entity/Decision** — influence propagating into quality and price; CIS/momentum are reflections,
beta+ comes from being closer to the cause. We ship ONE kernel, freely fusable. In an A2A market
the scarce resource is **verifiable forward track record** — the validation apparatus IS the
product. Ambition raises the evidence bar (§ALTITUDE). Honesty over optimism; the graveyard is
the asset. *Build things that feel alive.*

**⚠️ RETURN HIERARCHY (Jazz, asset-management first principle — priority order, not a menu; full text
`docs/HIGH_DIM_ONTOLOGY.md` §5b):** ① **capture beta** (long-only hold of the panel — the FoF core;
the benchmark every sleeve is measured against is "hold the panel", NEVER 0) → ② **beta+** (overweight
better assets INSIDE the book — CIS's actual job, tilt not L/S) → ③ **beta multiplier** (time total
exposure 0.7x–1.3x, never short — regime×vol, liquidity gate, v5 risk_score) → ④ **pure alpha**
(neutral/hedged — hardest, LAST). **We built this upside-down:** R76–R94 were all ④ (cross-sectional
demean = beta discarded by construction) while ① was never built — that specification error, not luck,
is the 15-attempt graveyard. **Default long-only: tilt, don't neutralize.** β-adjustment is for
ATTRIBUTION (R62), never for neutralizing a book. Every result reports total return vs hold-the-panel,
then excess.

**The bar:** every claim is guilty until proven with out-of-sample outcomes. Every sleeve needs a
*cause*, a base rate, and OOS survival. **This is now CI, not prose** —
`tests/test_strategy_discipline.py` + `scripts/preflight.sh` stage 3 enforce: cause documented,
`oos_survival=True`, ≥60d paper trade, regime-conditional reporting, before any SHIP verdict.

## Hard rules (each has burned us; violating any is a P0)

1. **Compliance — no buy/sell language, anywhere user-facing.** No 投顾 license. Signals use ONLY:
   `STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT`. Never BUY/SELL/
   ACCUMULATE/AVOID/REDUCE — backend, frontend, API, docs, decks. Full substitution tables:
   `.claude/skills/compliance-language/`.

2. **Shadow/ is READ-ONLY and NOT authority.** Never `git add` Shadow/. It drifts. The Mac↔Railway
   authority is the canonical contract: `src/api/contracts/cis_push.py` + `MINIMAX_SYNC.md` §2 +
   live echo `GET /internal/cis-scores/schema`. Contract wins on any disagreement. Schema changes
   documented in MINIMAX_SYNC §2 BEFORE code; both sides confirm; bump `SCHEMA_VERSION`.

3. **Ownership lanes.** Seth/Austin: `src/`, `dashboard/`, `docs/`, `scripts/`. Minimax:
   `/Volumes/CometCloudAI/cometcloud-local/`. When unsure, `MINIMAX_SYNC.md` §1.

4. **NEVER run git write-commands from the Cowork sandbox** (FUSE denies unlink → stranded
   `.git/index.lock`). Sandbox = edit surface only; ALL git happens Mac-side. Agent edits files
   and reports the commit list; Jazz/Mac commits. Unstick: `git unlock`.

5. **`bash scripts/preflight.sh` before EVERY push.** Railway auto-deploys on push; preflight is
   the ONLY prod gate. `py_compile` is NOT sufficient (2026-07-13: import-time error 502'd prod).
   Preflight = compile + boot smoke + discipline suite + contract SCHEMA_VERSION echo.

6. **Stage only your OWN paths; NEVER `git add -A`** (blind sweeps commit the other lane's
   half-finished work under your message). Explicit paths, always.

7. **Ledger numbering is lane-prefixed, forward-only** (`docs/R_NUMBERING_CONVENTION.md`):
   Seth/Austin = `S-76+`, Minimax = `M-76+`, frozen history `R1…R75` stays bare. Ledger is
   append-only at EOF; claim the heading before writing the body.

8. **No investor-facing internals.** strategy.html etc. must not mention FastAPI/Railway/Ollama/
   hardware/architecture.

9. **No mock data in production paths.** Prefer empty + flagged over fabricated (audit standing:
   DeFiLlama-402 fallbacks).

## Skills (`.claude/skills/`) — load on demand, don't rely on this file

| Skill | When |
|---|---|
| `compliance-language` | ANY user-facing output |
| `cis-methodology` | CIS scoring/grading/LAS/pillars/tiers/regime detail |
| `mac-mini-coordination` | any Mac Mini / Shadow / MINIMAX_SYNC work |
| `deploy-workflow` | deploy / build / push / Railway / release |
| `task-audit` | session start + "where are we / 卡在哪" — 4-block status |
| `completion-verification` | before ANY "done/shipped/✅" claim |

## The operational loop (compressed; skills own the mechanics)

```
START   task-audit → MEMORY.md → PROJECT_STATE.md          (~60s)
EXECUTE plan if non-trivial → edit+test → completion-verification before "done"
        → update PROJECT_STATE same turn → MINIMAX_SYNC if cross-lane
HANDOFF sandbox writes files → emit MAC-SIDE COMMIT HANDOFF block (below) → Mac commits+pushes
SHIP    preflight → push → wait ~90s → deploy-verifier agent (5 health categories)
END     TaskList closed/escalated → PROJECT_STATE header + log entry → MEMORY.md if new fact
```

**Handoff format — emit RUNNABLE COMMANDS, not a manifest.** Jazz pastes these into a terminal;
a file list plus a commit message is homework, because he still has to compose the `git add` lines
himself. Give the exact block, in order, path-scoped, with preflight first:

```bash
cd ~/Projects/looloomi-ai
bash scripts/preflight.sh          # green before anything below

git add <explicit paths — never -A>
git commit -m "<type>(<scope>): <subject>

<body: what changed and WHY it was wrong before>"

git push origin main
```

Rules: one commit per concern (ledger appends ride their own — `git log` is a source-of-truth
surface, and a commit whose title covers 9% of its diff corrupts it); any post-push verification
as a copy-pasteable `curl`; if a step is Jazz's alone (Supabase console, restart), say so on its
own line rather than burying it in a table.

**Staleness thresholds (task-audit flags):** in_progress >3d 🟡 / >7d 🔴 · queue P0 >3d 🟡 / >7d 🔴
· P1 >7d 🟡 / >14d 🔴 · AWAITING JAZZ >7d 🔴 · "done" claimed with dirty tree / unpushed commit /
stale header = 🔴 drift, same turn.

## Tech stack (essence)

React+Tailwind → Railway (auto-deploy on push) · FastAPI `src/api/main.py` (23 routers) ·
Upstash Redis (2h-TTL cache bridge) · **Supabase Postgres = system of record** (cis_scores,
signal_outcomes β-adjusted, ohlcv_daily incl. 2017+ `binance_hist` deep panel, pgvector
`asset_embeddings` HNSW + `match_asset_embeddings` RPC) · Mac Mini M4 Pro T1 engine (pushes
`/internal/cis-scores` ~30min, `X-Internal-Token`) · Data: CoinGecko→Hyperliquid fallback (crypto),
EODHD→yfinance fallback (TradFi), DeFiLlama, Alternative.me · Env vars: see Railway dashboard;
key ones `SUPABASE_URL/KEY`, `UPSTASH_REDIS_REST_URL/TOKEN`, `INTERNAL_TOKEN`, `COINGECKO_API_KEY`,
`EODHD_API_KEY`, `LLM_*`, `NARRATIVE_LLM_*` (fallback chains documented in code at use-site).

**CIS spine:** Mac T1 (full engine, 8 classes, 6 regimes) → cis_push → Redis `cis:local_scores` →
`cis_provider.py` T2 fallback (shape-tolerant pillar persist + `canonical_regime()` UPPER_SNAKE)
→ `/api/v1/cis/universe` → frontend badge T1 green / T2 amber. Grades A+≥85…F<25, percentile is
metadata. Signals = compliance enum only. Full spec: `CIS_METHODOLOGY.md` + cis-methodology skill.
**CIS v5 (validated, not deployed):** two-score architecture — return {F-anchored 0.40, M 0.25,
A 0.35 level+change} · risk {O-led + S/O stability→confidence}. `src/data/cis/cis_v5_architecture.py`.

## Design principles

Void blacks `#020208` · Turrell ambient orbs (screen blend, slow breathe) · type hierarchy
Syne→Exo 2→JetBrains Mono, single source `dashboard/src/index.css` (never per-page font links) ·
ONDO precision (thin borders, no noise) · data always present — skeletons, never empty states.

## Weekly strategy review (Sunday/Monday or ad hoc "strategy review")

1h: adversarial reads 30' (rotate lens: trader-agent / LP / competitor / developer) →
infra-debt check 15' → ONE strategic priority 15'. Output → `WEEKLY_REVIEW.md`. The builder and
the strategist use different mental OSes; this hour is the structural fix for proximity blindness.
