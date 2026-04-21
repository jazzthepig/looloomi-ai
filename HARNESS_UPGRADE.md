# HARNESS_UPGRADE.md — CometCloud AI Tech Stack Upgrade Plan

> Research-only document. No code changes here. Implementation gated on Jazz's
> green light for each phase.
>
> Date: 2026-04-11
> Author: Seth (research) — context from CLAUDE.md, MINIMAX_SYNC.md, MULTI_AGENT_PROTOCOL.md

---

## TL;DR

Anthropic shipped four things in late 2025/early 2026 that materially upgrade
how we should be running CometCloud's AI infrastructure:

1. **Agent SDK** (the rebranded Claude Code SDK) — same harness Claude Code uses,
   programmable in Python and TypeScript. We can run autonomous agents in
   production without rolling our own loop.
2. **Agent Skills as open standard** — December 18, 2025. SKILL.md is now the
   universal format; OpenAI adopted it for Codex CLI and ChatGPT. Microsoft,
   GitHub, Cursor, Figma, Atlassian, Canva, Stripe, Notion all on board.
3. **Managed Agents** — Anthropic-hosted harness with decoupled brain/sandbox.
   p50 TTFT down 60%, p95 down 90%. Sessions are now first-class durable objects.
4. **Plugin marketplaces** — official Anthropic marketplace has ~101 plugins.
   Plugins bundle skills + commands + hooks + subagents + MCP servers as one
   distributable unit.

GitHub shipped:

5. **GitHub Spark** (public preview) — natural-language → app → repo with
   two-way sync. Copilot Cloud Agent now does research/plan/code beyond PR
   workflows.
6. **GitHub Agentic Workflows** (Feb 2026 technical preview) — plain Markdown
   workflows in `.github/workflows/`, compiled by the `gh aw` CLI to standard
   Actions YAML, executed by Copilot CLI or other coding agents.

CometCloud's current setup is a hand-rolled multi-agent system using `CLAUDE.md`
as memory, ad-hoc Markdown sync files for coordination, and a custom MCP server.
None of this is wrong — but we are doing manually what the platform now does
natively, and we are missing the distribution and durability benefits of the
new primitives.

---

## §1 — Where we are today

### Current architecture (as of 2026-04-11)

```
┌─────────────────────────────────────────────────────────────────────┐
│  Cowork (Seth/Austin)        Mac Mini (Minimax)        Production   │
│  ─────────────────────       ───────────────────       ──────────   │
│  Cowork desktop session      cis_v4_engine.py          Railway      │
│  CLAUDE.md as memory         cis_scheduler.py          (FastAPI)    │
│  MINIMAX_SYNC.md as          cis_push.py ──────POST──→ /internal/   │
│     coordination protocol    Qwen3 35B (LM Studio)        cis-scores│
│  Shadow/ as read-only        macro_brief generator    Upstash Redis │
│     reference                                          Supabase     │
│                                                                      │
│  Multi-agent: Seth/Austin/Minimax coordinate via Markdown files     │
└─────────────────────────────────────────────────────────────────────┘
```

### What's working
- `CLAUDE.md` is doing real work as durable project context — Anthropic's own
  blog calls this out as a valid pattern
- Compliance rules (no buy/sell language) are documented but **enforced by
  human review only**
- Mac Mini ↔ Railway interface contract is documented in MINIMAX_SYNC.md
- MCP server (`cometcloud_mcp.py`) gives Claude Desktop access to live CIS data
- Multi-agent ownership boundaries are clear (Seth = src/dashboard, Minimax =
  /Volumes/CometCloudAI/cometcloud-local/, Shadow/ = read-only)

### What's missing (gaps the platform now closes)

| Gap | Cost today | New primitive that solves it |
|---|---|---|
| No `.claude/skills/` folder — domain knowledge lives in CLAUDE.md only | CLAUDE.md is bloated; loaded fully every session; no progressive disclosure | **Agent Skills** (SKILL.md format) |
| No subagent definitions — every task uses the main agent context | Context bloat on long sessions; no specialization | **Subagents** in Agent SDK |
| No hooks — compliance enforcement is review-only | Buy/sell language slips through occasionally; we catch in code review, not generation | **PreToolUse hooks** on Edit/Write |
| No formal session persistence across Cowork sessions | Every session reads all of CLAUDE.md to bootstrap | **Sessions API** in Managed Agents |
| Hand-rolled Mac Mini ↔ Railway pipeline | Brittle; secret rotation requires file-based coordination | **Managed Agents** decoupled brain/sandbox pattern |
| MCP server is internal-only — not distributable | We can't easily give investors/agents a CometCloud plugin | **Plugin marketplace** publication |
| No automated GitHub workflows for compliance/test/deploy | Every deploy is manual; no CI agent | **GitHub Agentic Workflows** |
| Macro brief generation runs as a cron on Mac Mini, brittle | Single point of failure; no observability | **Agent SDK + scheduled task** |

---

## §2 — What Anthropic built since our last architecture pass

### 2.1 Claude Agent SDK (formerly Claude Code SDK)

The same harness that powers Claude Code, exposed as a library in Python and
TypeScript. Key abstractions:

- **`query(prompt, options)`** — async iterator over agent messages. Built-in
  tool execution loop. No need to write your own.
- **Built-in tools**: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch,
  AskUserQuestion, plus a `Monitor` tool that watches a background script and
  reacts to each output line as an event.
- **Hooks**: `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, `SessionEnd`,
  `UserPromptSubmit`. Callback functions that validate, log, block, or transform
  agent behavior. This is exactly the missing piece for CometCloud compliance
  enforcement.
- **Subagents**: defined as `AgentDefinition` objects with their own prompt and
  tool subset. Main agent invokes via the `Agent` tool. Each subagent gets its
  own context window — no pollution back to parent.
- **Sessions**: persistent, resumable, forkable. First query returns
  `session_id`; subsequent calls pass `resume=session_id` to continue.
- **Filesystem-based config**: when `setting_sources=["project"]` is set, the
  SDK reads `.claude/skills/`, `.claude/commands/`, and `CLAUDE.md` exactly the
  way Claude Code does. **Same project files, programmatic execution.**
- **MCP servers**: passed via `mcp_servers` option; same MCPs we use today.

This is the right foundation for our scheduled tasks (morning macro brief,
nightly compliance audit, post-deploy verification). We currently run these as
cron jobs on the Mac Mini — we could move them to Agent SDK with persistent
sessions and proper observability.

### 2.2 Agent Skills as open standard (Dec 18, 2025)

Skills are folders with a `SKILL.md` file. The format is now adopted by
OpenAI (Codex CLI, ChatGPT), Microsoft, GitHub, Cursor, Figma, Atlassian.
Anything we build as a skill becomes portable across ecosystems.

**Canonical structure:**

```
skill-name/
├── SKILL.md              # YAML frontmatter + Markdown body
├── scripts/              # Optional. Python/JS for deterministic processing
├── references/           # Optional. Loaded by Claude on demand
└── assets/               # Optional. Templates, fonts, icons
```

**SKILL.md frontmatter:**

```yaml
---
name: skill-name
description: What it does. Use when [trigger]. Trigger with "[phrase]"
   or "[alternative phrase]".
---
```

**The progressive disclosure pattern is the key insight:**

- **Metadata** (name + description, ~100 tokens) is **always in context**
- **SKILL.md body** is loaded **only when triggered** by description match
- **`references/`** files are loaded by Claude **on demand** as it works
- **`scripts/`** are executed as tools, not loaded as text

This is what CometCloud's CLAUDE.md needs. Right now CLAUDE.md is one giant
file loaded fully every session — ~500 lines, ~3,000 tokens. We should split
the static reference parts into skills with progressive disclosure.

### 2.3 Managed Agents (Anthropic hosted harness)

Decouples the **brain** (Claude + harness) from the **hands** (sandbox + tools).
Three abstractions:

1. **Session** — append-only log of all agent activity. Interrogable; you can
   "rewind a few events before a specific moment." Solves the irreversible-decision
   problem.
2. **Harness** — the loop calling Claude and routing tool results. **Stateless.**
   When a harness crashes, a new one boots with `wake(sessionId)`, fetches history
   via `getSession(id)`, resumes. No manual recovery.
3. **Sandbox** — execution environment for code/files. Provisioned only when
   needed. Credentials never touch the sandbox.

> "our p50 TTFT dropped roughly 60% and p95 dropped over 90%"
> — Anthropic engineering blog

The pattern matters for us because **our Mac Mini ↔ Railway split is exactly
this brain/hands decoupling, just hand-rolled.** Mac Mini is the sandbox
(execution), Railway is the consumer. We could rebuild the bridge using
Sessions API and get persistence, observability, and crash recovery for free.

### 2.4 Plugin marketplaces

A Claude Code plugin bundles **skills + commands + hooks + subagents + MCP
servers** into one distributable unit. Official Anthropic marketplace has
~101 plugins as of March 2026; community marketplace has 340+ plugins and
1,367 skills.

A plugin manifest looks like:

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json       # name, version, author, description
├── skills/
│   ├── skill-1/SKILL.md
│   └── skill-2/SKILL.md
├── commands/             # /slash-commands
├── agents/               # subagent definitions
├── hooks/                # PreToolUse, PostToolUse, etc.
└── mcp/                  # bundled MCP servers
```

For CometCloud this means: **our `cometcloud_mcp.py` is 80% of a plugin
already.** We add a few skills (research-token, explain-cis, fetch-macro-brief),
a manifest, and we have a distributable artifact for investors and agent users
who want CometCloud intelligence in their own Claude Desktop / Claude Code /
ChatGPT (because OpenAI adopted the spec).

### 2.5 Effective harnesses for long-running agents

Anthropic published two engineering posts on harness design that map directly
to our use case:

**Pattern 1 — Two-agent architecture (initializer + worker):**
- *Initializer* runs once: sets up environment, creates `claude-progress.txt`,
  generates feature spec JSON
- *Worker* runs incrementally: reads progress file + git log + runs verification
  tests *before* doing new work
- Critical: "It is unacceptable to remove or edit tests" — strongly-worded
  instructions in the spec are load-bearing

**Pattern 2 — Multi-agent specialization (planner / generator / evaluator):**
- *Planner* expands the spec
- *Generator* implements
- *Evaluator* (separate, skeptical) grades against explicit criteria
- "Tuning a standalone evaluator to be skeptical turns out to be far more
  tractable than making a generator critical of its own work."

**Pattern 3 — Structured handoff via files, not conversation:**
- Agents write specifications/contracts to disk
- Other agents read and respond
- No token-expensive conversation history shared between agents

**Pattern 4 — Sprint contracts before implementation:**
- Generator and evaluator negotiate "what done looks like" for each work chunk
- Bridges high-level spec with testable concrete requirements

Our `MINIMAX_SYNC.md` is already pattern 3. We are doing this manually for the
Seth ↔ Minimax handoff. The pattern says we are right; we should formalize it.

### 2.6 The harness performance gap is real

> On the CORE benchmark, the same Claude Opus 4.5 model scored **78% with
> Claude Code's harness but only 42% with Smolagents**.
> — Anthropic engineering

Same model, different harness, **86% relative performance gap.** This is the
single most important number in this document. The harness matters as much as
the model. We should not be rolling our own.

---

## §3 — What GitHub built that we should care about

### 3.1 GitHub Spark (public preview, Pro+)

Natural language → app → repository with two-way sync. We don't need this for
the main CometCloud platform (we have the dashboard built), but it's perfect
for **investor microsites and one-off prototypes**: "build me a one-page
calculator showing CIS-weighted portfolio expected return," push to a Spark
repo, share with Nic.

### 3.2 GitHub Agentic Workflows (Feb 2026, technical preview)

Plain Markdown workflows in `.github/workflows/`, compiled by the `gh aw` CLI
to standard Actions YAML. Workflows describe automation goals in natural
language; an AI agent (Copilot CLI by default) handles intelligent
decision-making.

For us: **automated compliance audit on every PR.** Markdown workflow says
"check the diff for any of these strings: BUY, SELL, ACCUMULATE, AVOID, REDUCE,
STRONG BUY. If found, comment on the PR with the offending lines and request
changes." This is a 5-line Markdown file, no YAML, no Python.

### 3.3 Copilot Cloud Agent

No longer limited to PR workflows. Can run research sessions, answer questions
about the codebase, and execute multi-step plans. Less relevant for us than the
Agent SDK because we already have Claude Cowork.

---

## §4 — Concrete upgrade plan for CometCloud

Phased so each phase delivers value independently. Implementation only after
Jazz approves each phase.

### Phase A — Skill structure refactor (low risk, immediate value)

**Goal:** Move static reference content out of `CLAUDE.md` and into
progressive-disclosure skills. Cut the always-loaded context budget.

**What to create in `.claude/skills/`:**

1. **`compliance-language`**
   - YAML: triggers on "compliance", "buy/sell language", "signal naming",
     "investor copy", "marketing", any signal/grade output
   - Body: full §1 of CLAUDE.md compliance rules + the prohibited word list +
     the approved signal vocabulary
   - `references/`: full text of `CIS_METHODOLOGY.md` §5 and §8

2. **`cis-methodology`**
   - YAML: triggers on "CIS", "scoring", "v4.1", "v4.2", "pillar", "grade",
     "LAS", "regime"
   - Body: short overview pointing to references
   - `references/`: full CIS_METHODOLOGY.md split into 5 files (one per pillar
     + grading + LAS + regime modifiers)

3. **`mac-mini-coordination`**
   - YAML: triggers on "Mac Mini", "Minimax", "Shadow", "cis_push", "scheduler",
     "data_fetcher", "interface contract"
   - Body: ownership boundaries from CLAUDE.md §"Compliance rules" #5
   - `references/`: MINIMAX_SYNC.md, MULTI_AGENT_PROTOCOL.md

4. **`deploy-workflow`**
   - YAML: triggers on "deploy", "build", "Railway", "git push", "release"
   - Body: the standard deploy workflow from CLAUDE.md
   - `scripts/build_and_push.sh`: deterministic build + commit + push helper

5. **`design-system`**
   - YAML: triggers on "design", "Turrell", "void", "Space Grotesk", "ONDO",
     "color", "layout"
   - Body: the design principles from CLAUDE.md §"Design principles"
   - `references/tokens.js` extract: full token table for reference

6. **`tech-stack`**
   - YAML: triggers on "stack", "FastAPI", "React", "Upstash", "CoinGecko",
     "EODHD", "Qwen3"
   - Body: the tech stack section + env var table from CLAUDE.md

After this phase, `CLAUDE.md` shrinks to ~150 lines: identity (who we work with),
philosophy, current focus / task matrix, and a manifest of skills. Everything
else is loaded on demand. **Estimated context reduction: ~70% on every
session.**

**Risk:** None. Skills are additive. If discovery doesn't trigger correctly,
the original CLAUDE.md content still works as fallback during transition.

### Phase B — Compliance hooks (medium risk, prevents real bugs)

**Goal:** Move compliance enforcement from human review to automatic blocking.

**What to add (using Agent SDK hooks pattern, runs in Cowork):**

1. **`PreToolUse` hook on `Edit` and `Write`:**
   - Scans the new content for any of: `BUY`, `SELL`, `STRONG BUY`,
     `ACCUMULATE`, `AVOID`, `REDUCE`
   - Allows them inside `.git/`, comments, test fixtures, and the
     `compliance-language` skill itself (where they appear as the prohibited
     list)
   - Returns `{block: true, reason: "..."}` if violation found
   - Forces the agent to use the approved vocabulary

2. **`PreToolUse` hook on `Bash` for `git commit`:**
   - Reads the staged diff
   - Same scan
   - Blocks the commit if violation found

3. **`PostToolUse` hook on `Bash`:**
   - Logs all `git push`, `rm`, and `curl` invocations to
     `.cowork/audit.log` for review

4. **`SessionStart` hook:**
   - Reads `claude-progress.txt` (new file, see Phase D) and presents the
     current task state to the agent

5. **`SessionEnd` hook:**
   - Updates `claude-progress.txt` with what was done in this session

**Risk:** Hooks can be wrong and block valid work. Mitigation: dry-run mode for
2 weeks (log violations but don't block), then enable blocking after we've
tuned the regex.

### Phase C — Subagent specialization (medium risk, immediate quality gain)

**Goal:** Move specialized work out of the main session, get specialization
benefits and context isolation.

**Subagents to define (in `.claude/agents/` or programmatically):**

1. **`compliance-auditor`**
   - Tools: Read, Glob, Grep
   - Prompt: "Scan the working directory for any prohibited buy/sell language.
     Output a list of file:line:context entries. Do not modify anything."
   - Used by: main agent before commits, scheduled weekly via Agent SDK

2. **`cis-validator`**
   - Tools: Read, Bash
   - Prompt: "Given a CIS score output, recompute from the input data and
     verify the math. Flag any discrepancy >1%."
   - Used by: main agent when reviewing Mac Mini ↔ Railway sync

3. **`deploy-verifier`**
   - Tools: WebFetch, Bash
   - Prompt: "After a Railway deploy, hit /api/v1/cis/universe,
     /api/v1/market/macro-pulse, /api/v1/signals. Verify response shape, latency
     <2s, and that CIS universe is non-empty. Report status."
   - Used by: main agent after every push, scheduled hourly via Agent SDK

4. **`minimax-coordinator`**
   - Tools: Read, Edit (only on MINIMAX_SYNC.md)
   - Prompt: "You are the contract negotiator between Seth/Austin and Minimax.
     Your only job is to update MINIMAX_SYNC.md with field name changes,
     enum updates, and new endpoints. Refuse all other edits."
   - Used by: main agent when proposing schema changes

5. **`research-agent`**
   - Tools: WebSearch, WebFetch, Read, Write
   - Prompt: "Investigate the user's research question thoroughly. Output a
     structured report. No code changes."
   - Used by: Jazz directly for "go research X"

**Risk:** Low. Subagents are isolated by design. Worst case is they fail to do
their task and we fall back to main agent.

### Phase D — Long-running harness pattern (medium risk, big productivity)

**Goal:** Bridge the gap between Cowork sessions. Today every new session reads
all of CLAUDE.md cold; we want progress files + git log to bootstrap.

**What to create:**

1. **`claude-progress.txt`** at repo root
   - Plain text, append-only
   - Each entry: timestamp, agent (Seth/Austin), summary, files touched, git
     commit hash, blockers
   - Updated by `SessionEnd` hook (Phase B)
   - Read by `SessionStart` hook (Phase B)

2. **`feature-spec.json`** at repo root
   - JSON list of features in flight
   - Each: id, owner, status (pending/in_progress/completed/blocked), acceptance
     criteria, dependent_on
   - Replaces the ad-hoc task matrix in CLAUDE.md
   - Updated by Cowork agent during work; read by both Cowork and any Agent SDK
     scheduled tasks

3. **`session-handoff/` directory**
   - One file per Seth ↔ Minimax handoff
   - Pattern from Anthropic blog: structured handoff via files, not conversation
   - Replaces ad-hoc Markdown chat in MINIMAX_SYNC.md (which becomes the
     interface contract spec only)

**Risk:** Low. These are coordination files, not code. Worst case they're out
of date.

### Phase E — Package CometCloud as a Claude plugin (high value, distribution play)

**Goal:** Ship a `cometcloud-intelligence` plugin to the Anthropic marketplace.
Investors, agents, and other Claude users get CometCloud data in one install.

**What goes in the plugin:**

```
cometcloud-intelligence/
├── .claude-plugin/plugin.json
├── skills/
│   ├── research-token/SKILL.md         # "research X token" → CIS + macro context
│   ├── explain-cis/SKILL.md            # "explain the CIS score for SOL"
│   ├── fetch-macro-brief/SKILL.md      # "what's the current market regime?"
│   ├── portfolio-builder/SKILL.md      # "build a CIS-weighted portfolio for $X"
│   └── compliance-check/SKILL.md       # "review this for compliance language"
├── commands/
│   ├── cis.md                          # /cis SOL → returns full score breakdown
│   └── regime.md                       # /regime → returns current macro pulse
├── agents/
│   └── cis-analyst.md                  # specialized analyst with CIS toolchain
└── mcp/
    └── cometcloud.json                 # references our existing Railway MCP
```

The MCP server already exists. We just package it.

**Distribution:** Submit to `anthropics/claude-plugins-official` or list on
community marketplace. Free tier reads public CIS data; paid tier (Pro key)
unlocks history, backtests, and the agent JSON API.

**Strategic value:** This is the "AI agent FoF" thesis made concrete. Other
agents discover us via the marketplace. They can use our skills natively,
without us building any custom integration. The plugin is the canonical
distribution unit for AI-native services.

**Risk:** Low engineering risk. Marketing risk = we ship it and nobody installs
it. Mitigation: launch alongside investor outreach as "the only crypto FoF with
a native Claude plugin."

### Phase F — GitHub Agentic Workflows for CI (low risk, high leverage)

**Goal:** Move repetitive ops (compliance check, deploy verify, dependency
audit) from manual review to GitHub Actions agents.

**Workflows to write (in `.github/workflows/`, plain Markdown):**

1. **`compliance-pr-check.md`**
   - Trigger: `on: pull_request`
   - Goal: "Scan the diff for prohibited buy/sell language. If found, comment
     on the PR with the offending lines and request changes."

2. **`post-deploy-verify.md`**
   - Trigger: `on: push: branches: [main]`
   - Goal: "After Railway deploys, hit the live API endpoints and verify
     response shapes and latency. If any fail, open an incident issue."

3. **`weekly-cis-audit.md`**
   - Trigger: `on: schedule: cron: '0 8 * * 1'`
   - Goal: "Pull last 7 days of CIS scores from Supabase. Verify no asset
     dropped below D grade unexpectedly. Flag anomalies in #cometcloud-alerts."

**Risk:** Low. Workflows run in CI, not production. Worst case they fail loudly
and we get a notification.

### Phase G — Migrate scheduled tasks to Agent SDK (long-term)

**Goal:** Replace the Mac Mini cron jobs with Agent SDK programs that have
sessions, observability, and crash recovery.

**What to migrate first (lowest risk, highest visibility):**

1. **Morning macro brief generation** (currently `cis_scheduler.py` cron)
   - Becomes an Agent SDK Python program
   - Resumes session daily; appends new brief to thread
   - Hooks log every step to `audit.log`
   - Runs on Mac Mini (or migrates to Railway worker)

2. **Hourly post-deploy verifier** (currently doesn't exist; manual)
   - Agent SDK Python program with `deploy-verifier` subagent
   - Scheduled via Railway Cron or Mac Mini cron
   - Reports to Slack/Telegram on failure

3. **Weekly CIS audit** (currently doesn't exist)
   - Agent SDK Python program with `cis-validator` subagent
   - Pulls last 7 days from Supabase, recomputes, compares
   - Reports drift to `audit.log` and Slack

**Risk:** Moderate. We have to keep the existing Mac Mini scoring engine
running while migrating. Mitigation: dual-run period; flip cutover only after
Agent SDK output matches Mac Mini output for 7 days.

---

## §5 — Order of operations

```
Phase A (skills refactor)              ◀── start here, low risk, immediate
   │                                       context savings
   ▼
Phase B (compliance hooks, dry-run)    ◀── needs A done so the
   │                                       compliance-language skill exists
   ▼
Phase C (subagents)                    ◀── independent of B; can run parallel
   │
   ▼
Phase D (progress files + handoff)     ◀── depends on B for SessionStart/End hooks
   │
   ▼
Phase F (GitHub Agentic Workflows)     ◀── independent; can run in parallel
   │                                       with C/D
   ▼
Phase E (plugin distribution)          ◀── depends on A done; ideally B + C too
   │                                       so the plugin showcases the harness
   ▼
Phase G (Agent SDK scheduled tasks)    ◀── biggest lift; only after we trust
                                           the harness pattern from Phase B/C
```

Phases A through F are 1-3 days each. Phase G is a multi-week migration.

---

## §6 — What we should NOT change

These are working well; do not refactor without evidence they're broken:

1. **Mac Mini ↔ Railway split** — this IS the brain/sandbox decoupling pattern.
   We had it right by accident. Don't move scoring to Railway.
2. **Upstash Redis bridge** — works, fast, persistent across deploys. Don't
   replace with Supabase or direct DB.
3. **CIS v4.1/v4.2 scoring methodology** — this is our edge. Don't refactor for
   refactoring's sake.
4. **CLAUDE.md as identity + philosophy** — the parts about "who we work with",
   philosophy, current focus should stay in CLAUDE.md. Only the static
   reference content moves to skills.
5. **MULTI_AGENT_PROTOCOL.md** — the human protocol stays. We're augmenting it
   with skills, not replacing.
6. **The MCP server** — it works, it's our distribution vector. We package it,
   we don't rewrite it.

---

## §7 — Decision points for Jazz

Before I touch any of this, I need decisions on:

1. **Phase A scope** — refactor all 6 skills at once, or just 2-3 to validate
   the pattern first? Recommendation: start with `compliance-language` and
   `cis-methodology` (highest value, lowest risk).

2. **Phase B scope** — hooks in dry-run for 2 weeks, or enable blocking
   immediately? Recommendation: dry-run for 1 week, then block.

3. **Phase E timing** — ship the plugin now (with current capabilities) or
   wait until we have score history + backtest API stable? Recommendation:
   ship now as v0.1, iterate. The marketplace listing is itself marketing.

4. **Phase G scope** — migrate all 3 scheduled tasks at once, or pilot with
   the macro brief first? Recommendation: pilot with macro brief; it has
   lowest blast radius if it breaks.

5. **Who owns each phase** — Phase A through F are Seth/Austin work in Cowork.
   Phase G touches Mac Mini cron, so it's a Seth + Minimax handoff. Need
   Minimax's signoff before starting Phase G.

---

## §8 — Sources

### Anthropic engineering & docs
- [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Scaling Managed Agents: Decoupling the brain from the hands](https://www.anthropic.com/engineering/managed-agents)
- [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Claude Managed Agents overview](https://platform.claude.com/docs/en/managed-agents/overview)
- [Extend Claude with skills (Claude Code Docs)](https://code.claude.com/docs/en/skills)
- [Agent Skills (Claude API Docs)](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [Discover and install prebuilt plugins through marketplaces](https://code.claude.com/docs/en/discover-plugins)
- [Plugins for Claude Code and Cowork](https://claude.com/plugins)

### Anthropic open-source repos
- [anthropics/skills](https://github.com/anthropics/skills) — public Agent Skills repository (canonical SKILL.md examples)
- [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) — official plugin marketplace

### Industry analysis
- [Agent Skills: Anthropic's Next Bid to Define AI Standards (The New Stack)](https://thenewstack.io/agent-skills-anthropics-next-bid-to-define-ai-standards/)
- [Anthropic Opens Agent Skills Standard (Unite.AI)](https://www.unite.ai/anthropic-opens-agent-skills-standard-continuing-its-pattern-of-building-industry-infrastructure/)
- [How OpenAI Quietly Adopted Anthropic's "Skills" (Global Tech Council)](https://www.globaltechcouncil.org/ai/openai-adopted-anthropics-skills/)
- [Top 10 Claude Code Skills Every Builder Should Know in 2026 (Composio)](https://composio.dev/content/top-claude-skills)
- [50+ Best MCP Servers for Claude Code in 2026](https://claudefa.st/blog/tools/mcp-extensions/best-addons)

### GitHub
- [GitHub Spark concept docs](https://docs.github.com/en/copilot/concepts/spark)
- [GitHub Agentic Workflows (Feb 2026 changelog)](https://github.blog/changelog/2026-02-13-github-agentic-workflows-are-now-in-technical-preview/)
- [Research, plan, and code with Copilot cloud agent (Apr 2026)](https://github.blog/changelog/2026-04-01-research-plan-and-code-with-copilot-cloud-agent/)
- [GitHub Copilot 2026 complete guide (NxCode)](https://www.nxcode.io/resources/news/github-copilot-complete-guide-2026-features-pricing-agents)

### Community
- [jeremylongshore/claude-code-plugins-plus-skills](https://github.com/jeremylongshore/claude-code-plugins-plus-skills) — 340 plugins / 1367 skills marketplace
- [Build with Claude — Plugin Marketplace](https://buildwithclaude.com/)
- [Claude Code Marketplaces directory](https://claudemarketplaces.com/)
