# CLAUDE.md — CometCloud AI / Looloomi

> **⭐ SESSION START: read `MEMORY.md` (facts index, 30s) then `PROJECT_STATE.md` (living state) FIRST.
> Update PROJECT_STATE LAST.** Never trust memory of what's committed — run
> `git --no-optional-locks status --porcelain` / `git rev-list origin/main..HEAD` before
> describing any "pending push". **The `--no-optional-locks` is not optional** (rule 4): plain
> `git status` refreshes the index, creates `.git/index.lock`, and FUSE will not let the sandbox
> delete it — which silently blocks every later `git add` Mac-side.

## Source-of-truth map (one table, no scattered prose)

| Question | Read | Write discipline |
|---|---|---|
| What's true right now / in flight | `PROJECT_STATE.md` | **≤80,000 chars**; update same turn work lands; `**Last updated:**` line stays at the TOP |
| Long-term facts index | `MEMORY.md` | **≤3,400 CHARACTERS** (not bytes — CJK is 3 B/char; `wc -c` will lie to you, S-337). One line per fact; evict stale; **if a test enforces it, the test is the memory** |
| Why a thing landed / build log | `PROJECT_STATE_LOG.md` | append-only; **NOT read at session start** — grep it, don't read it |
| Experiment truth (R/S/M-numbers) | `REFUTATION_LEDGER.md` | APPEND-ONLY at EOF; claim heading before body; **grep, never read whole** (577k chars) |
| Cross-lane coordination | `MINIMAX_SYNC.md` (gitignored) | **≤80,000 chars**; append §sections; syncs Mac-side, not via git. Anything dated >5d and settled → `MINIMAX_SYNC_ARCHIVE.md`; **still open ⇒ re-raise in §IN-FLIGHT, don't leave it in place** |
| Strategy truth / frozen cells | `STRATEGY_PLAYBOOK.md` | |
| The soul / north star | `ARCHITECTURE.md` | read when a decision touches what we ARE |
| Behavioral-edge doctrine | `docs/TRADER_TOM_DOCTRINE.md` | read before building any sleeve |
| **Mining output — where the research IS** | `Shadow/.../_reports/INDEX.md` → then `absorb_input/` | Minimax-C writes both; **read the WHOLE lineage, not the first hit** — R70 alone gave a number R71 corrected by 32% |
| **How deep we hold a symbol** (before ANY backfill) | `curl /internal/data-coverage?symbol=X` | Baseline is **`deepest_start` = union across sources**, never one source's. S-276: a single-source read re-fetched 820 days we already had |
| Full history | `git log` | |

**⚠️ "NOT authority" ≠ "not worth reading."** Rule #2 governs the *contract* (never take a schema
or config from Shadow) and says nothing about the RESEARCH in it. Reading it as "ignore Shadow"
once cost a false claim that we had one verifiable backtest while `_reports/absorb_input/` held 14.
**Before saying a result does not exist, grep `_reports/`.**

**Caps above are CI, not advice** (`tests/test_cold_start_contract.py`, S-165). Capping only
MEMORY.md once pushed the cost next door (PROJECT_STATE hit 315k): **a cap with too narrow a scope
redirects attention away from what it misses.**

**A lane can only judge what it can see.** When another lane gets our data wrong, ask what it could
READ before asking it to be more careful — S-276 was an interface gap, not a discipline failure.

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
family-office / HNW across APAC; HK base. AI-curated **on-chain FoF, venue- and chain-agnostic**
— we go where the on-chain liquidity is. OSL-stablecoin denominated. Target $500M AUM, 1% mgmt +
performance. Built for human LPs and AI agents equally.
**Looloomi** — the AI-agent / Web3 tech arm powering it.

> **Chain-agnostic ≠ instrument-agnostic (Jazz, 2026-08-23).** The chain follows liquidity;
> ①'s INSTRUMENT does not move. **beta = HOLD, and a long perpetual is not a hold** — it is a
> synthetic long paying carry. Measured on ①'s own 24 names: equal-weight funding **+23.07%
> annualised**, so at gross 1.15 a perp-based ① bleeds ~26.5%/yr — more than any alpha we have
> ever shown. **① holds SPOT.** Perps belong to ②③④, which already account for funding.

**Philosophy (full text: ARCHITECTURE.md):** the deepest object is not the Asset but the
**Entity/Decision** — CIS/momentum are reflections; beta+ comes from being closer to the cause.
**We ship ONE kernel**, freely fusable. In an A2A market the scarce resource is **verifiable
forward track record — the validation apparatus IS the product.** Ambition raises the evidence bar
(§ALTITUDE). Honesty over optimism; the graveyard is the asset. *Build things that feel alive.*

**⚠️ RETURN HIERARCHY (Jazz — priority order, not a menu; full text `docs/HIGH_DIM_ONTOLOGY.md` §5b):**
① **capture beta** (long-only hold of the panel — the FoF core; every sleeve's benchmark is
"hold the panel", NEVER 0) → ② **beta+** (overweight better assets INSIDE the book — CIS's job,
tilt not L/S) → ③ **beta multiplier** (time exposure 0.7x–1.3x, never short) → ④ **pure alpha**
(neutral/hedged — hardest, LAST). **We built it upside-down:** R76–R94 were all ④ (cross-sectional
demean discards beta by construction) while ① was never built — **that specification error, not
luck, is the 15-attempt graveyard.** Default long-only: tilt, don't neutralize. β-adjustment is for
ATTRIBUTION (R62), never for neutralizing a book. Report total return vs hold-the-panel, then excess.

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

3. **Ownership lanes.** Seth/Austin: `src/`, `dashboard/`, `docs/`, `scripts/`,
   `paper_trading/` (canonical spec library). `src/research/paper_books/` = **older
   sleeve+ledger prototypes, pre-spec_runner** — `daily_runner.py` there is NOT a
   spec_runner entry point (OPEN RISK §0c, reconciliation pending). Minimax:
   `/Volumes/CometCloudAI/cometcloud-local/` — **that path is the Minimax data root,
   architecture not debt** (S-323w: I once flagged it as a hardcoded path and was wrong).
   When unsure, `MINIMAX_SYNC.md` §1.

3b. **Ingestion is ONE lane (Seth), by function not by path.** Fetching/persisting price data goes
   through the guarded path only; Minimax *consumes* — mining, backtests, VDB upkeep. Path-based
   lanes alone let M-118 build a 3rd fetcher over data we already had. **Two ingesters means two
   series that look like the same quantity and are not** (S-273/274/275, one day). Backfill
   request → say so in `MINIMAX_SYNC`, Seth's lane runs it.

4. **NEVER run ANY git command from the Cowork sandbox that touches the index** — including
   `git status` / `git diff` / `git checkout`, which refresh the index, create
   `.git/index.lock`, and FUSE will not let the sandbox unlink it. Cost: a whole batch
   (2026-09-04, 16 files silently uncommitted) and again S-334 (`git checkout` deleted a fix
   mid-session). **Sandbox read-only alternatives:** `git --no-optional-locks status
   --porcelain`, or `git show origin/main:<path>`. ALL writes happen Mac-side.
   **Every handoff block puts `rm -f .git/index.lock` immediately before the first `git add`,
   AFTER preflight** — preflight itself calls `git ls-files` and re-locks.

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
bash scripts/preflight.sh
rm -f .git/index.lock
git add <explicit paths — never -A>
git commit -m "<type>(<scope>): <subject>

<body: what changed and WHY it was wrong before>"
git push origin main
```

**NO TRAILING `#` COMMENTS ON ANY COMMAND LINE. NO INLINE ANNOTATION. EVER.** This kept recurring
because the template itself used to carry them — **the rule and its own example disagreed, and the
example is what gets copied.** Explanation goes in prose *outside* the fence; inside, only lines
that paste and run. No blank lines for grouping either — they invite a partial paste.

Rules: one commit per concern (ledger appends ride their own — a commit whose title covers 9% of
its diff corrupts `git log` as a source of truth); post-push verification as a pasteable `curl`;
if a step is Jazz's alone (Supabase console, restart), say so on its own line.

**Staleness (task-audit):** in_progress >3d 🟡 />7d 🔴 · P0 >3d 🟡 />7d 🔴 · P1 >7d 🟡 />14d 🔴 ·
AWAITING JAZZ >7d 🔴 · "done" with dirty tree / unpushed commit / stale header = 🔴 same turn.

## Tech stack (essence)

React+Tailwind → Railway (auto-deploy on push) · FastAPI `src/api/main.py` · Upstash Redis
(2h-TTL cache bridge) · **Supabase Postgres = system of record** (Pro plan; compute is a SEPARATE
add-on and is still Micro — 256MB shared_buffers, 60 conns) · Mac Mini M4 Pro T1 engine (pushes
`/internal/cis-scores` ~30min, `X-Internal-Token`) · Data: CoinGecko Pro (crypto), EODHD (TradFi),
DeFiLlama, Alternative.me · Env vars in the Railway dashboard; fallback chains documented at
use-site. Table/RPC inventory: `src/api/schema_manifest.py`, never a list here.

**CIS spine:** Mac T1 → cis_push → Redis `cis:local_scores` → `cis_provider.py` T2 fallback →
`/api/v1/cis/universe` → badge T1 green / T2 amber. Grades A+≥85…F<25; percentile is metadata;
signals = compliance enum only. Spec: `CIS_METHODOLOGY.md` + cis-methodology skill.
**CIS v5 validated, NOT deployed:** `src/data/cis/cis_v5_architecture.py`.

## Design principles

Void blacks `#020208` · Turrell ambient orbs (screen blend, slow breathe) · type hierarchy
Syne→Exo 2→JetBrains Mono, single source `dashboard/src/index.css` (never per-page font links) ·
ONDO precision (thin borders, no noise) · data always present — skeletons, never empty states.

## Weekly strategy review (Sunday/Monday or ad hoc "strategy review")

1h: adversarial reads 30' (rotate lens: trader-agent / LP / competitor / developer) →
infra-debt check 15' → ONE strategic priority 15'. Output → `WEEKLY_REVIEW.md`. The builder and
the strategist use different mental OSes; this hour is the structural fix for proximity blindness.
