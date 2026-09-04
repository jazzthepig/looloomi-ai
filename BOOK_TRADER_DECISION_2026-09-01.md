# Book_trader 决策矩阵 — 2026-09-01 (updated 2026-09-02 with prompt #1 grep verification)

> **Status:** Discussion artifact for Seth + team. NOT yet written to PROJECT_STATE.
> Use this as the substrate for the next book_trader decision conversation.
> After the team decides, the surviving choice + verification record goes into
> PROJECT_STATE.md (per CLAUDE.md source-of-truth discipline).
>
> **2026-09-02 update:** ran the reverse-hypothesis verification before
> discussion lands. Findings added in the "Architecture verification" section.
> TL;DR of the update: **R14 is regime-agnostic (confirmed), but Book B is
> NOT, because M-93 sleeve is regime-gated (50% weight)**. "Thin" verdict
> is metadata at the wrapper level, not what flows into the book. Lane split
> is real: `paper_trading/spec_runner.py` is Seth/Austin, `book_trader.py`
> is Minimax-C on Mac — Option C needs cross-lane coordination.

---

## TL;DR

`book_trader.py` is in **M-112 P0 HALT** since 2026-08-30. The honest book (after
correcting same-bar look-ahead) is **Book B = M-93 + R14-Lite** with SR +1.629 /
cum +321.5% / MaxDD -22.9% on 1196d lag-1. Three reopen paths:

| Option | Action | Risk |
|---|---|---|
| A | Stay HALT (do nothing) | 0 work, 0 risk; signal-validity dies |
| B | Resume Book B paper immediately | HIGH — regime quorum today = "thin" (bad input) |
| **C** | Fix quorum gate → resume Book B paper | 3-5d work; cleanest path |

**Recommended: Option C.** OPEN RISK 0 already specifies this path
("要不要拦,跟恢复 book 一起签").

---

## Inputs (verified this session)

### Research lineage

| Source | Finding |
|---|---|
| **M-112 P0** (2026-08-30) | M-95c book Sharpe +8.2 = same-bar look-ahead artifact. Honest value +1.25 (Book A) / +1.63 (Book B). VOIDED: M-95c/96/97/98/99/100/101/103/104/107/108/110/111. **HALT book_trader Day 2/3 — JAZZ DECISION.** |
| **M-113** (2026-08-30) | Book A = M-93 + R19-Lite @ SR +1.249 / cum +180.6% / MaxDD -26.9% (survivors-only risk-parity, lag-1, 1196d). |
| **M-114** (2026-08-31) | Lag-discipline regression guard. **R19 retention 0.493 < 0.5 floor (BORDERLINE FAIL)** — hidden leak. R14 retention 0.614 = clean pass. Wired into `preflight.sh` stage 3a.1 (commit a3e0191). |
| **M-115** (2026-08-31) | **Book B = M-93 + R14-Lite** @ SR **+1.629** / cum +321.5% / MaxDD -22.9% (risk-parity). Beats Book A by Δ +0.380 / +140.9pp / +4.0pp. Cost stress: B survives +10bps/day (A negative). DSR p≈0.001 (B) vs p=0.009 (A). |
| **M-116** (2026-08-31) | OOS train/test split on 1196d: Book B PASS 60/40 (+1.218) and 50/50 (+1.110); borderline 70/30 (+0.354). DSR p=0.078@1 / 0.81@50 / 0.97@1000 NOT significant under multiple-testing. RISK_OFF barely positive (+0.003). Rolling 90d 67.9% positive (vs full 85.7%). |

### Open risks (current first screen)

| Risk | State (2026-09-01) |
|---|---|
| **S-263 OPEN RISK 0** | Two regime labels fighting on same machine: Supabase `daily_macro_regime` = TIGHTENING (36d unchanged); M-120-backfilled local `narrative_daily::regime` = EASING (derived from BTC 30d = +24.6%, **single-asset momentum renamed, not macro**). `book_trader` reads local. Built `regime_quorum.py` 5-value arbiter (ok/thin/COLLAPSED/frozen/no_baseline); current verdict = **thin** (sources 2/baseline 3). Currently **report-only, no gate** — by design during HALT. |
| **S-263 OPEN RISK 0b** | M-120 misread process state: book_trader 18:04:46 DD-STOP triggered (-60.07%) → 18:06:35 stopped = **109 seconds, by design**. NOT a crash. "Crash" vs "correctly refused to continue" read as same state. |

### Architecture constraints

- **ARCHITECTURE §5b**: ① capture beta → ② beta+ (tilt, not L/S) → ③ beta multiplier (0.7x–1.3x, never short) → ④ pure alpha (LAST). Default long-only: tilt, don't neutralize.
- Book B violates §5b: ④ weight = 50% (R14-Lite) > doctrine max 20%. **Book B is honest baseline, NOT §5b production book.** M-117 = §5b-aligned redesign (60d parallel work, not blocker).
- M-114 guard already wired — prevents same-bar leak, **does NOT prevent wrong-regime mis-input**.

---

## Decision matrix

| | **A: Stay HALT** | **B: Direct resume Book B paper** | **C: Fix quorum → resume Book B** ★ |
|---|---|---|---|
| **Action** | No action | Switch `book_trader` to Book B config (M-93 + R14-Lite), 60d paper track | (1) `regime_quorum`: thin → gate (block not just report); (2) once verdict = ok, resume Book B paper; (3) 60d paper track + parallel M-117 §5b redesign |
| **Workload** | 0 | Mac-side config switch (~1h) | Seth: arbiter contract + new test (~1d). Minimax-C: config + verify (~0.5d). Total ~3-5d sequential. |
| **Data risk** | 0 | **HIGH** — regime = thin = diseased input; book trades on bad label | Low — quorum gate blocks book until verdict = ok |
| **§5b compliance** | n/a | ❌ ④ 50% > 20% (M-117 pending) | Same as B; paper-only does not block §5b redesign |
| **M-114 guard** | n/a | Passes (R14 retention 0.614 ≥ 0.5) | Same; M-114 already wired in preflight stage 3a.1 |
| **M-116 OOS** | n/a | Borderline (70/30 SR +0.354; DSR p=0.078@1 NOT significant) | Same |
| **Cost stress** | n/a | Survives +10bps/day | Same |

---

## Recommendation: Option C

### Why C, not B

M-112 P0 root cause = **book received wrong signal** → fake Sharpe. Regime = thin is the
**same class of failure mode**, just shifted one layer up:

- M-112 leak: book sees `p[d]` at decision time (same-bar)
- OPEN RISK 0 leak: book sees `regime = EASING` (from BTC 30d, not macro)

M-114 guard catches lag-0 leaks. It does **not** catch wrong-regime-label mis-input.

Direct resume (B) without fixing the quorum = **HALT off, book back online, but trading
on a "regime = thin" diagnosis**. Same disease, different signal class.

OPEN RISK 0 author (Seth, 2026-09-01) explicitly designed these as one decision:
**"要不要拦,跟恢复 book 一起签"** — that's Option C.

### Why C, not A

- 6+ days without paper validation: rolling 90d stat (67.9% positive per M-116) needs
  fresh tracking; absence of book = absence of evidence.
- Regime fight (OPEN RISK 0) doesn't auto-resolve by waiting — the `narrative_daily`
  producer is the upstream fix and that's a Minimax-A rebuild, not a passive wait.
- M-117 §5b redesign needs empirical signal from paper trading to validate.

### Why not other variants

- **Book A (R19-Lite) + fix regime** — M-115 hidden finding: R19 retention 0.493 borderline
  fail (差 0.007). Book A is honest but weaker; Book B is honest **and** clearly better.
- **Book B + wait for §5b redesign (M-117)** — §5b is architecture change; shouldn't block
  paper validation. Book B explicitly violates §5b but paper-only evidence can validate
  whether §5b is necessary or over-conservative.
- **Book B + full §5b redesign now** — complexity explosion; 60d paper is cheaper validation.

---

## VERIFY per option

| Option | Verification command |
|---|---|
| A | `ps aux \| grep book_trader` → 0 lines · `select max(trade_date) from beta_core_nav` ≤ 2026-08-29 |
| B | `bash scripts/preflight.sh` green · `python3 paper_trading/spec_runner.py --book=b --dry-run` → 0 trades + `regime=thin` warning logged |
| **C** | `python3 -m tests.test_regime_quorum` green · `python3 -m tests.test_regime_quorum_blocks_book` (NEW) green · `python3 paper_trading/spec_runner.py --book=b --dry-run --require-regime=ok` → 0 trades, no thin warning |

---

## OWNER matrix

| Option | Seth (Cowork) | Minimax-C (Mac) | Jazz (decision) |
|---|---|---|---|
| A | — | — | default (no action) |
| B | spec_runner config update | wire `book_trader` to new config | sign off |
| **C** | arbiter gate contract + new test | config switch + verify | sign off |

---

## Parallel non-blocking work

| Item | Why parallel, not blocker |
|---|---|
| M-117 §5b-aligned design | Book B violates §5b (④ 50% > 20%); paper-only is evidence for/against the doctrine. 60d paper informs §5b redesign, doesn't block it. |
| M-118 cost robustness | Final SHIP gate; only meaningful after 60d paper track. |
| M-114 guard | **Already wired** (`preflight.sh:91`, stage 3a.1, commit a3e0191). No further work. |
| S-263 OPEN RISK 1 (service_role) | Railway-side RESOLVED 2026-08-09; local Mac-side backfill is P2 follow-on (Jazz decides on .env paste). |
| CG Pro deep backfill (S-258 / M-92) | Mac-side; unblocks M-86/M-87 panels BLOCKED on 343d vs 1811d. Independent of book_trader decision. |
| 7 stale Mac-side IN-FLIGHT items | Lane-crossing; book_trader decision doesn't depend on these. |

---

## What changes after team decides

### If Jazz picks A
- No file changes.
- book_trader stays HALT; OPEN RISK 0 + 0b remain "AWAITING JAZZ".
- Next natural trigger: M-117 §5b redesign, M-118 cost, or fresh research that breaks the
  deadlock (e.g., new data layer change).

### If Jazz picks B
- Update PROJECT_STATE OPEN RISK 0 → "🟢 mitigated by Option B; book resumed 2026-XX-XX";
  OPEN RISK 0b → "🟢 was misdiagnosis; book_trader correctly self-stopped".
- spec_runner.py config update (Minimax-C lane).
- Mac-side `book_trader` restart with new spec.
- 60d paper track; final SHIP gate = M-117 + M-118.

### If Jazz picks C
- Update PROJECT_STATE OPEN RISK 0 → "🟢 arbiter gate shipped + book resumed 2026-XX-XX".
- Seth: write `regime_quorum_blocks_book.py` test + ship arbiter gate contract.
- Minimax-C: wire gate into `book_trader` config.
- Mac-side restart, gated on regime = ok.
- 60d paper track; final SHIP gate = M-117 + M-118.

---

## Discussion prompts (use with Seth)

1. **Is regime = thin genuinely a "wrong input", or am I overweighting OPEN RISK 0?**
   - Counter-argument: Book B uses R14-Lite which is regime-agnostic (cross-sectional momentum);
     maybe it doesn't even read regime as input — in which case Option B and C are equivalent.
   - Need to read `paper_trading/spec_runner.py` `M-115 wire` lines + R14 sleeve to confirm
     regime is actually in the path.

2. **What does "60d paper track" mean concretely?**
   - Same metrics as M-116 (rolling 90d positive %, OOS Sharpe, DSR, MaxDD)?
   - Or different gates for live paper vs backtest?

3. **M-117 §5b redesign — when does it actually start?**
   - Parallel during 60d paper?
   - After 60d paper verdict?
   - This affects whether §5b evidence is from this book or from a redesign.

4. **Does OPEN RISK 0b's "M-120 misread process state" need a separate fix?**
   - The current `book_trader` process-state documentation should distinguish
     "stopped by design" vs "crashed".
   - M-120 itself may want to be updated to reflect 109s-DD-STOP behavior.

5. **What is the JAZZ escalation criteria for book resume?**
   - Per CLAUDE.md "decision backlog > 7d", OPEN RISK 0/0b need a decision by 2026-09-08.
   - What's the smallest viable decision today vs waiting for fuller M-117?

---

## Architecture verification (this session, 2026-09-02)

Ran the **prompt #1** reverse-hypothesis check before this discussion lands:

### What "Book B" actually reads

| Layer | File | Reads regime? | Mechanism |
|---|---|---|---|
| `decide(spec, panel, *, regime, ...)` (single-sleeve) | `paper_trading/spec_runner.py:395` | ✅ via `spec.skip_regimes` check (line 441) | If `canon in spec.skip_regimes` → SKIPPED. Generic xs/cluster family. |
| `decide_survivors_book(spec, panel, *, regime, ...)` (Book B / Book A) | `paper_trading/spec_runner.py:481` | ✅ via M-93 sleeve gate | M-93 sleeve: `m93_in_pos = canon is None or canon not in spec.skip_regimes` (line 553). If regime in `spec.skip_regimes` → M-93 to cash, line 588 logs "regime 让 M-93 sleeve 在 cash". |
| R14-Lite sub-sleeve (within Book B) | inline in `decide_survivors_book` lines 558-580 | ❌ regime-agnostic | Pure xs momentum: `score = {s: _return_over(panel.closes[s], d, spec.n_lookback)}`. Only universe prices + n_lookback. |

**Refined prompt #1 verdict:**
- ✅ R14-Lite ITSELF is regime-agnostic (confirmed)
- ❌ Book B ≠ regime-agnostic, because M-93 sleeve IS regime-gated (50% weight)
- ❌ B ≠ C — Option C adds value because it intercepts the label M-93 reads, not because it gates the R14 sleeve directly

### What "thin verdict" actually means for the book

- `regime_quorum.py` returns one of: `ok / thin / COLLAPSED / frozen / no_baseline`
- This verdict is **metadata** at the wrapper level — NOT what flows into `spec_runner.decide()`
- `decide()` receives `regime: Optional[str]` = the **label** (e.g., `"EASING"` or `"TIGHTENING"`), not the verdict
- Implication: a "thin" quorum today means **the label is suspect**, but the book will still receive a label and trade on it
- For the book to actually gate on "thin", Option C needs to add a **wrapper-level check** BEFORE `decide()` is called:
  ```
  verdict = regime_quorum.check(date)
  if verdict not in ("ok", "thin_with_override"):
      return Decision(verdict=SKIPPED, reason=f"regime quorum={verdict}")
  ```

### Lane split (verified 2026-09-02)

| Component | Lane | Where |
|---|---|---|
| `paper_trading/spec_runner.py` (spec library, M-115 Book B wiring) | **Seth/Austin** (Cowork) | `/Users/sbb/Projects/looloomi-ai/paper_trading/spec_runner.py` (already shipped in commit `a3e0191`) |
| `book_trader.py` (the actual book process that M-112 P0 HALT applies to) | **Minimax-C** (Mac) | `/Volumes/CometCloudAI/cometcloud-local/book_trader.py` (NOT in repo; Shadow mirror root shows `cis_*.py`, `data_fetcher.py`, `nautilus_strategies/` but no `paper_trading/` subdir — confirming Mac-side book_trader is OUT of Seth/Austin repo) |
| `regime_quorum.py` (new arbiter) | **Seth/Austin** (Cowork) | `src/data/market/regime_quorum.py` per OPEN RISK 0 |
| Quorum → book wrapper gate (NEW, needed for Option C) | **Seth/Austin** (Cowork) | Wraps `paper_trading/spec_runner.py` before Mac book_trader calls it |
| Wire wrapper into Mac book_trader | **Minimax-C** (Mac) | Modify `/Volumes/CometCloudAI/cometcloud-local/book_trader.py` to call new wrapper or check verdict first |

**Implication for Option C ownership:**
- Seth writes the wrapper / arbiter contract + new test (Cowork lane)
- Seth ships the wrapper into `paper_trading/spec_runner.py` or a sibling `paper_trading/quorum_gate.py`
- Minimax-C picks up the new wrapper in Mac-side `book_trader.py` config
- Two-lane coordination needed (per CLAUDE.md rule #3, the lane boundary is real)

### Reverse-hypothesis verification commands (run 2026-09-02)

```bash
# 1. spec_runner reads regime?
$ grep -nE 'regime|macro_regime' paper_trading/spec_runner.py
# → 30+ hits across decide(), decide_survivors_book(), skip_regimes,
#   canonical_regime_strict, M-93 sleeve gate

# 2. R14-Lite sub-sleeve reads regime?
$ grep -nE 'ret_Nd|R14|n14|14d' paper_trading/spec_runner.py
# → Only in spec.family, docstring, comments. R14 score function
#   (_return_over) is regime-free.

# 3. book_trader.py in repo?
$ find . -maxdepth 3 -name 'book_trader*'
# → 0 hits — confirmed Mac-side only

# 4. Shadow mirror has paper_trading?
$ ls Shadow/cometcloud-local/ | head
# → No paper_trading/ subdir — confirms book_trader on Mac side,
#   uses Seth/Austin spec_runner via direct import or HTTP
```

### Implication for the recommendation

**Option C still recommended**, with this tighter reasoning:

- Regime = thin = **suspect label** flows into `decide()` regardless
- M-93 sleeve (50% book weight) checks `spec.skip_regimes` against that label
- If label = "TIGHTENING" (Supabase) and skip_regimes = ["RISK_OFF", "STAGFLATION"] → M-93 trades long
- If label = "EASING" (local narrative_daily) and same skip_regimes → M-93 trades long
- **Either label = M-93 long**, so the question is **what's in skip_regimes default for the book?**
- (This is a separate prompt: `grep -A 30 'skip_regimes' paper_trading/spec_runner.py` to see the default + check `M-93 sleeve spec` configuration)
- Quorum gate at wrapper level = intercepts BEFORE M-93 gets the label = paper-trading safety even when label is suspect

**Conclusion:** B ≠ C, but the gap is narrower than the original matrix implied. The discussion should now focus on:
1. What's the **default skip_regimes for M-93**? If empty (no skip), then label quality matters less and B might be acceptable.
2. What's the **cost of a 3-5d wrapper gate** vs the cost of resuming on a suspect label?
3. Is "thin verdict → paper trade only" sufficient, or do we need "thin verdict → no trade"?

---

## File location

This file: `/Users/sbb/Projects/looloomi-ai/BOOK_TRADER_DECISION_2026-09-01.md`

**Not committed yet** — discussion artifact only. Seth can:
- `git add BOOK_TRADER_DECISION_2026-09-01.md && git commit && git push` (if wants in repo)
- Or share via paste / different channel (if wants off-repo discussion)

**Not written to PROJECT_STATE** — per explicit direction. PROJECT_STATE.md "Last updated"
header still reads **2026-08-30**; if discussion produces a decision, the next PROJECT_STATE
update should bump header AND record the decision + verification result.