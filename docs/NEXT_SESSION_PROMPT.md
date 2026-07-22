# Next-session kickoff prompt

Copy everything below into a fresh session.

---

Seth — continuing CometCloud. Previous session (2026-07-21) hit context limit. Read in this order
before doing anything:

1. `PROJECT_STATE.md` — top entry (per CLAUDE.md, always first)
2. `docs/SESSION_LOG_2026-07-21.md` — machine-readable digest of the last session
3. `WEEKLY_REVIEW.md` — the 2026-07-21 entry (strategy + business model thread)
4. `docs/VECTOR_SCHEMA_SPEC.md` — the build order I'm asking you to follow
5. `docs/MECHANISM_SPEC.md` — A2A market mechanics (note: Minimax has since edited it)

## The one thing that must not be lost

**The metric was the bug, not the model.** Asset β vs benchmark is 1.4–2.4, so
`alpha = a_ret − b_ret` measured *leveraged beta*, not alpha. In a bear-dominated window this made a
working signal read as inverted. PIT-safe β adjustment flips it: OUTPERFORM −0.36 → **+2.86 (t=+5.75)**,
STRONG OUTPERFORM → **+8.06 (t=+5.41)**. **CIS works.** UNDERWEIGHT (t=−3.79) is the one real defect.
Chain: **R61 → R62 (overturns R61) → R63/R63b**. Never read R61 alone.

Meta-lessons #21 and #22, both earned the hard way:
- **Audit the METRIC before the MODEL.** All three "our edge is broken" findings that session were
  measurement defects (β contamination + two look-ahead leaks in independent code paths).
- **A factor can fail as a mean-return predictor and still be information.** Pillar S is mean-flat but
  vol +8% / left tail 32% deeper → it is a **risk gate**, not dead weight. We nearly deleted it.

**Three factor kinds** (R63b) — level-only (F, M), directional-change (A), fast-state/risk (S, O,
stability premium +2.72/+2.70). ⇒ **CIS v5 is an architecture change, not a reweight.**

## ⚠️ Reconcile first — this may have moved

Minimax landed **R64–R68b** after that session and added a "binary-permanent kill register" to
`MECHANISM_SPEC.md`: cross-sectional L/S on the 22-asset upgraded CIS is now a **binary-permanent
kill** (7-deep refutation lineage). Critically, **R67 refutes R46** on upgraded data — 0/120 cells
pass the ship-gate, and the earlier ★ SURVIVOR was a snapshot artifact.

I used R46 as independent corroboration for R62 (both remove β — one by construction, one by
adjustment). **That corroboration is now weaker than I claimed.** R62's own finding stands on its own
data, but re-derive whether the cross-check still holds before repeating it to anyone. Do not carry
my sentence forward unchecked.

## Build order (from VECTOR_SCHEMA_SPEC §4) — do not reorder

1. **β-adjusted metric into production.** Module + Supabase columns are done
   (`src/data/market/beta_adjust.py`; `signal_outcomes.{beta_pit,alpha_beta_adj,edge_beta_adj}`,
   `signal_track_record.{avg_edge_beta_adj_pct,...}`). The live writer is **Mac-side = Minimax's**
   — see `MINIMAX_SYNC.md` §BETA-METRIC. Chase it; everything else waits on this.
2. **Pillar deltas + stability dims** into the asset vector (cheap, computable from `signal_outcomes`).
3. **Converge the two strategy-vector stacks.** Minimax's 30-dim `src/data/vector/` is the keeper;
   port in from my `src/research/strategy_vector.py`: NaN-honesty (unmeasured ≠ 0), the binary
   validity floor, `coverage_gaps()`, `redundancy()`. Then delete my duplicate.
4. **Risk moments** (`edge_vol`, `edge_p10`) — needs β-adjusted history backfilled first.
5. **High-frequency S/O sampling** — the stability premium says we sample *after* the market reprices.
   Route: related-instrument price action (Jazz's AI-ETF analogy).
6. **CIS v5 architecture — LAST.** Building it on a yardstick that still counts leveraged beta as
   alpha would bake the bug in permanently.

## Also open

- **UNDERWEIGHT is broken** (t=−3.79) — the only genuinely defective signal.
- **Library coverage gaps** (first run, 8 sleeves): **calm n=0, stormy n=0, chop best=0.16.**
  Everything we own is directional. That is the build list.
- **Noise-injection gate** is now stage 8 of `signal_gauntlet` (from the Mamba article — the only
  gate that perturbs *inputs*). It needs re-runnable candidates (`signal_fn` + `features`); most of
  our sleeves are stored equity curves and **cannot** be tested. That inability is research debt,
  not a pass.
- **Mamba verdict:** not now. Our bottleneck is identification, not model capacity. Revisit only if
  hourly S/O sampling creates a real sequence-length problem.

## Coordination hazards — these cost real work last session

- **Ledger is append-only at EOF.** It was rewritten Mac-side mid-session and silently destroyed
  entries. Claim an R-number by appending before writing the body. Never rewrite the whole file.
- **Two agents built the same embedder in one afternoon** because assignments lived in prose.
  Implement against `docs/VECTOR_SCHEMA_SPEC.md`, not against each other.
- **Never run git write-commands from the sandbox** (FUSE denies unlink → stranded `index.lock`).
  Edit files; Jazz commits Mac-side. If a commit fails, clear the lock with `git unlock`.
- **`bash scripts/preflight.sh` before any push.** `py_compile` is not sufficient — Railway
  auto-deploys and preflight is the only gate protecting prod.
- **`docs/transcripts/` is gitignored** — conversation archives stay local. Regenerate with
  `scripts/export_transcripts.py`.

## Standing discipline (§ALTITUDE)

We are building the capital-allocation mechanism for an A2A economy — third parties will deploy on
this. The validation apparatus **is** the product: in an A2A market the scarce resource is not
capital, it is verifiable forward track record. So ambition raises the evidence bar, it does not
lower it. A Sharpe of 5 gets *more* scrutiny, not a victory lap. Honesty over optimism — and log the
refutations, because a tidy ledger is a worthless one.

Start by confirming what actually got committed (`git status`, `git log origin/main..HEAD`) — do not
trust the previous session's account of what was pushed.
