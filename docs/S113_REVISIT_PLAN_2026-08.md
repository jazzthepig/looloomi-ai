# S-113 Revisit Plan — S-108/S-109 on the 687-asset panel — 2026-08-08

*Seth. Per OVERSIGHT §3 P1 (which S-111 partially unlocked with the 687-asset
survivorship-free panel). Per task #281 ("都做啊"). This is the bounded Seth-lane
deliverable: framework + smoke tests + plan. The actual re-run waits for
service_role key restoration (OPEN RISK #1).*

---

## 0. Why this plan exists

**S-108** (派发假说 / Wyckoff distribution) REFUTED at n=20 episodes on the 10-large-cap
hourly panel. **S-109** (state detection instead of bucket sort) REFUTED at n=13 episodes
on the same panel. Both bottoms-up said the bottleneck was **breadth, not length** —
episodes come from cycles across assets, not from longer history.

**S-113** measured N_eff on the 249-asset extended panel: ρ̄=0.435, **N_eff=2.28**.
**6× more assets bought 1.51× effective breadth** — co-movement structure means
breadth scales sub-linearly with N. S-113 predicted: even larger panels won't rescue
episode counting for S-108/S-109 hypotheses.

**S-111** unlocked the **687-asset survivorship-free panel** (was 75 alive-only).
The 25.1pp/yr survivorship bias is now measurable AND correctable. The structural
question: does 687 change N_eff enough to make S-108/S-109 actually measure?

**S-113's prediction:** no, but measure, don't argue. This plan + the framework in
`src/research/validation/s113_revisit_s108_s109_on_687asset.py` IS that measurement.

---

## 1. What the framework does (and doesn't)

### Does
1. **Layer 1 — `n_eff_687`:** Recomputes N_eff on the 687-asset panel (ρ̄ + the
   S-113 formula `N_eff = N / (1 + (N-1) * ρ̄)`).
2. **Layer 2 — `s108_episodes_687`:** Counts S-108 episodes using a coarse proxy
   (runup ≥ 10% on dying names, 5-day forward mean). The proxy is a LOWER BOUND on
   true S-108 episodes (no hourly trades data on the 687 panel).
3. **Layer 3 — `s109_episodes_687`:** Counts S-109 episodes using a coarse proxy
   (20-day return ≥ 5%, 20-day forward drawdown). Lower bound on true EUPHORIA
   episodes (no funding-p85, no distance-from-ATH).

### Does NOT
- Claim a verdict on S-108 or S-109 themselves — that requires ≥
  EPISODE_COUNT_FLOOR episodes, and the prediction is we still won't hit it.
- Rerun S-108's ATS slope test or S-109's EUPHORIA state detector — those live in
  their own modules (hourly trades data only).
- Mutate any frozen cell (R69, R77, R46, R62, R76).
- Write to Supabase — pure compute module.
- Run from this session — service_role key is OPEN RISK #1, blocked on this machine.

---

## 2. Verdict grammar (the four honest outcomes)

```
PANEL_BREADTH_OK         N_eff ≥ 5.0 (real breadth improvement vs 2.28 baseline)
PANEL_BREADTH_FLAT       2.23 ≤ N_eff < 5.0 (S-113 prediction — same wall)
PANEL_NARROWED           N_eff < 2.23 (assets DECREASED effective breadth — rare)

S108_EPISODES_OK         ≥ EPISODE_COUNT_FLOOR on the new panel
S108_EPISODES_INSUFFICIENT  < EPISODE_COUNT_FLOOR (expected)

S109_EPISODES_OK         ≥ EPISODE_COUNT_FLOOR on the new panel
S109_EPISODES_INSUFFICIENT  < EPISODE_COUNT_FLOOR (expected)

Primary verdict:
  PREMATURE_PANEL       N_eff < 5 AND both S108/S109 are insufficient
                         (the S-113 prediction; expected outcome)
  PANEL_BREADTH_OK      N_eff ≥ 5 (materially improved breadth)
  INCONSISTENT          mixed signal (one or both episodes OK but N_eff flat)
```

The primary verdict `PREMATURE_PANEL` does NOT mean "S-108/S-109 are false". It means
**the panel physically cannot measure them** — the lever is panel LENGTH, not breadth.

---

## 3. Why §OHLCV-EXTENSION is the real unlock

**The 731-day panel (2024-06-07 → 2026-06-07) is bear-dominated** — per memory
`[§STRATEGY-2-DEFERRED]` structural finding: 12 directional attempts REFUTED on this panel
because the panel is too bear-dominated for ANY single-strategy shape (market-neutral L/S,
directional long-only, pair-trading — all three shapes REFUTED).

**§OHLCV-EXTENSION** (Mac-side data rebuild) is what changes the lever from breadth
to **length**. With an 11-year panel:
- More cycles per asset (10× more episodes per asset)
- N_eff might still be ~2, but the episode count per asset grows linearly with length
- S-108/S-109's per-asset episode floor would be reached on a multi-cycle basis

**The 687-asset panel is a breadth play; the 11yr panel would be a length play.**
Both are needed, but the 687-asset alone is unlikely to change S-108/S-109's verdict.

---

## 4. How to run (Mac-side, when OPEN RISK #1 cleared)

```bash
# After service_role restored:
cd ~/Projects/looloomi-ai

# Live run path — loads 687-asset panel from Supabase
python3 -m src.research.validation.s113_revisit_s108_s109_on_687asset \
  --out-dir reports/s113_revisit/$(date +%Y-%m-%d) \
  --supabase-url "$SUPABASE_URL" \
  --supabase-key "$SUPABASE_SERVICE_ROLE_KEY"

# OR without creds — emits blocked-stub (the current honest state):
python3 -m src.research.validation.s113_revisit_s108_s109_on_687asset \
  --out-dir reports/s113_revisit/$(date +%Y-%m-%d)
# → verdict.json with status=blocked, framework_ready=True, predicted_verdict=PREMATURE_PANEL

# Always run the smoke tests first:
python3 src/research/validation/tests/test_s113_revisit_smoke.py
# → 6/6 passed expected
```

The blocked-stub path is what this session can emit today — it documents that the
framework EXISTS, is testable, and has a *predicted* verdict (`PREMATURE_PANEL`)
that aligns with S-113's prediction. Mac-side replaces prediction with measurement
when service_role is restored.

---

## 5. What this plan does NOT do

- **Does NOT propose changes to the S-108/S-109 ledger entries.** Their REFUTED
  status holds; the re-run is a NEW measurement, not a reversal. New entries
  (S-114+) would be appended to REFUTATION_LEDGER.md when the live run completes.
- **Does NOT touch the R77 module or any frozen fusion cell.** This is research-
  only, sibling to `m_wo1_r77_episode_count_audit.py` and `r77_multicycle_revalidation.py`.
- **Does NOT propose a directional-shape candidate.** OVERSIGHT §2.3's directional
  question is OPEN pending §OHLCV-EXTENSION; this revisit is for episode-count
  hypotheses, not directional beta.
- **Does NOT add to the production loop.** This is `src/research/validation/`,
  not `src/data/signals/`. No Railway deploy impact.

---

## 6. Source-of-truth chain

| Claim | Cite this |
|---|---|
| S-108 REFUTED at n=20 | `REFUTATION_LEDGER.md` S-108 entry (line 6436) |
| S-109 REFUTED at n=13 | `REFUTATION_LEDGER.md` S-109 entry (line 6504) |
| N_eff=2.28 on 249-asset panel | `REFUTATION_LEDGER.md` S-113 entry (line 6931) |
| Lesson #93 (constants need window) | S-113 + MEMORY |
| 687-asset panel unlocked | S-111 + `scripts/supabase_universe_survivorship.sql` + commit `b3dfbee` |
| 25.1pp/yr survivorship measured | S-111 ledger entry + SQL VERIFY query |
| Framework exists, smoke-tested | `src/research/validation/s113_revisit_s108_s109_on_687asset.py` + `tests/test_s113_revisit_smoke.py` (6/6) |
| Service_role blocked | `PROJECT_STATE.md` OPEN RISK #1 + `MEMORY.md` Lesson #72 |
| §OHLCV-EXTENSION is the real lever | memory `[§STRATEGY-2-DEFERRED]` structural finding · MEMORY §OHLCV-EXTENSION |
| OVERSIGHT §2.3 directional question is OPEN | `docs/OVERSIGHT_2026-08.md` §2.3 + `docs/R77_VS_OVERSIGHT_2.3_ANALYSIS_2026-08-08.md` |

---

*Plan prepared by Seth, 2026-08-08, per task #281 ("都做啊"). Framework + smoke tests
shipped; live run waits for service_role key restoration. Expected verdict:
PREMATURE_PANEL (S-113 prediction). The lever is panel LENGTH, not breadth — §OHLCV-EXTENSION
is the real unlock and remains Mac-side.*
