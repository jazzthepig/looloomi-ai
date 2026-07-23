# R-numbering convention — APPROVED 2026-07-23 (lane prefix, forward-only from R76)

**Status:** APPROVED by Jazz on 2026-07-23. **Option 2** (recommended) is the rule going forward.
**Cutover:** from the next entry each lane appends — Seth/Austin uses `S-`, Minimax uses `M-`,
both increment independently starting from `76`. Frozen history `R1…R75` stays bare. Each lane
still applies its own claim-before-write discipline (append heading first, body second).

**One-line ask:** approve a lane prefix so the R-ledger stops colliding. Recommended option in §2.

## 1. The problem (why "renumber up" keeps failing)

Two lanes append to a **single flat R-sequence independently**: Seth/Austin (`src/`, Railway, docs)
and Minimax (`/Volumes/…/cometcloud-local/`, Mac engine). With no shared lock, both reach for the
same next integer. This has now collided **twice**:

- R64–R68b: Seth's fusion lane vs Minimax's pillar_A kill register (resolved 2026-07-22 by renumbering
  Seth → R69–R72).
- **Immediately re-collided:** Minimax then used R69/R70 (regime-gated L/S) and R73–R75 (pillar_A
  fusion, hourly S/O) — overlapping the exact numbers Seth had just moved to.

"Whoever renumbers up" cannot work: the other lane advances into the vacated space. The flat sequence
is the bug. A prefix fixes it **structurally** — each lane increments its own counter, zero coordination.

## 2. Recommended: lane prefix, forward-only, shared frozen history

- **Frozen history:** `R1 … R75` stay **exactly as written** (bare, no renaming). The 2026-07-22
  `§LEDGER-RECONCILIATION-MAP` already disambiguates the R64–R72 overlap. No retroactive sweep — that
  is the expensive, error-prone path we avoid.
- **Forward, from the next entry:** every new ledger heading carries a lane prefix and continues from 76:
  - **Seth/Austin → `S-76`, `S-77`, …**
  - **Minimax → `M-76`, `M-77`, …**
  The prefix is the namespace; both lanes using "76+" is fine because `S-76` and `M-76` are distinct keys
  (like two books each having a chapter 1). Each lane advances ONLY its own prefix.
- **Claim-before-write still applies within a lane:** append the heading first to reserve the number,
  then fill the body (the append-only rule from `SESSION_LOG_2026-07-21.md` §5).
- **Immediate application:** the two entries currently deferred/loose become —
  - Seth's #5 lead-lag study → **`S-76`**
  - Minimax's active R73/R74/R75 → stay bare as frozen history; their *next* entry is **`M-76`**.

**Cost:** one line in the ledger header declaring the cutover. No file-wide renaming. Durable forever.

## 3. Alternative (if you prefer a hard split)

Minimax keeps the bare `R##` sequence forever (incumbent, high-frequency lane); Seth/Austin uses a
separate `S##` counter starting at **S1**. Cleaner separation, but restarts Seth's count and loses the
visual continuity with Seth's existing bare entries (R45/R46/R58–R63/R69–R72). Recommended only if you
want Minimax to "own" the R-line outright.

## 4. Approved

- [x] **Option 2** (recommended — prefix + continue from 76): **Jazz, 2026-07-23** ✅
- [ ] **Option 3** (Minimax bare `R`, Seth fresh `S1+`): not chosen

**Cutover applied 2026-07-23:** new Seth entries begin at `S-76`, `S-77`, …; new Minimax entries
begin at `M-76`, `M-77`, …. Frozen history `R1…R75` stays bare. The two deferred/loose entries
explicitly named in this doc — Seth's #5 lead-lag study and Minimax's active R73/R74/R75 — are
**renumbered retroactively** at the next touch:

- Seth's #5 lead-lag → **`S-76`** (the `src/research/validation/so_price_leadlag.py` already on disk
  this session is the artefact).
- Minimax's next new entry after R75 → **`M-76`**; existing R73/R74/R75 stay bare as frozen history.

**Mirroring:** Minimax mirrors on the Mac side; no other files change this cutover. Once the cutover
is in place, the "renumber on collision" loop is closed structurally.
