# A Falsification-First Research Protocol for Autonomous Strategy Discovery
### (Working title — paper skeleton, v0.1, 2026-07-15)

> **Status honesty.** This is a *methods + negative-results* paper. Its claim is about a
> **research protocol** and its yield, **not** about a validated live edge. Every empirical
> row below is real (from `experiment_runs` / `REFUTATION_LEDGER.md`). Sections marked
> ⏳ require accruing data (live marks, 30–90 days) before they can be written truthfully.
> Do not upgrade any "candidate" to "validated" in the text until the live track record clears.

---

## Abstract (to write last)
One paragraph. The contribution is a **falsification-first loop** an autonomous agent can run:
propose → walk-forward test with selection-bias correction → **record the refutation** → let a
persistent negative-results ledger constrain the next proposal. Applied to crypto/RWA strategy
discovery over N hypotheses, it produced a **survival rate** (1 certified, 2 live candidates,
3 refuted, 1 null out of 7 recorded), and — as a by-product — a reusable measurement substrate
(prediction resolver + per-source track record) and one genuinely novel signal object (the
tokenized-RWA funding-cap regime). State plainly: no realized live alpha is claimed yet.

## 1. Introduction / motivation
- The pathology this addresses: research agents (and humans) publish/keep **survivors** and
  silently discard failures, so the same dead ideas get re-run and in-sample cleverness is
  mistaken for edge. Proximity blindness: when the proposer and evaluator are the same system,
  gaps get filled with internal knowledge a fresh test wouldn't have.
- Thesis (from `ARCHITECTURE.md`): most tradable signals (CIS, momentum) are **reflections** of an
  upstream **cause** (forced supply, positioning/leverage, narrative). Edge, if any, comes from
  being closer to the cause — but that belief is itself a hypothesis to be **falsified**, not asserted.
- Claim of the paper: the valuable, transferable artifact is not a strategy but the **protocol** —
  and specifically the discipline of treating a refuted hypothesis as permanent, compounding knowledge.

## 2. Related work (to fill)
- Deflated Sharpe Ratio & the multiple-testing / backtest-overfitting literature (Bailey &
  López de Prado). Position our DSR gate here.
- Walk-forward / combinatorially-purged CV as the OOS standard.
- Effective Number of Bets / correlation-aware portfolio construction.
- Agentic/LLM research loops and tool use (MCP) — position the "agent as operator" framing.
- Gap we fill: a *negative-results-first* operating discipline with a persistent, machine- and
  human-readable ledger, run by an autonomous agent against live markets.

## 3. The protocol (core contribution)
Describe the closed loop precisely enough to reproduce:

1. **Propose** — one hypothesis, stated as a directional claim on a measurable object.
2. **Pre-register the bar** — the test is walk-forward OOS, net of costs, with a selection-bias
   correction (DSR) sized to the number of trials actually run. Fixed *before* seeing results.
3. **Test** — walk-forward folds; report per-fold, not just pooled. Cost sensitivity + break-even bps.
4. **Adjudicate** — verdict ∈ {certified, candidate, null, refuted, false-alarm}. A single OOS
   split is explicitly **not** sufficient (see §5, R1/R13 — we caught our own overclaims twice).
5. **Record** — every outcome, especially failures, gets a permanent ledger entry carrying *the
   number that killed it* and the lesson that generalizes. Nothing is deleted.
6. **Constrain** — before any new proposal, the ledger is consulted; a hypothesis already in the
   graveyard is not re-run.

Figure 1: the loop. Figure 2: the data-flow that makes it self-measuring (§6).

## 4. Application domain: crypto + tokenized RWA
- Universe, data sources, why market-neutral / cross-sectional framing (removes beta, isolates the
  cause). Why crypto is a hard case: no earnings anchor (killed the naive sector-valuation import —
  R12 / `sector_val_rotation`), 24/7 markets, reflexive leverage.
- **Novel object — the funding-cap ("顶格") regime on tokenized-RWA perps.** Tokenized equity/
  commodity perps (MSTR, NVDA, gold, silver) trade 24/7 on-chain while the underlying is closed
  (weekends/holidays). Positioning cannot hedge into the real asset → funding pins at the exchange
  cap (annualized >500–1000%), then wide-range chop, then a new trend whose **direction is set by
  volume, not price momentum** (bidirectional: crowded-long flush vs crowded-short squeeze). This is
  a structural, calendar-driven dislocation with no equity-market analogue. (Present as a
  *characterized phenomenon*; the mechanical trading rule for it was **refuted** — see §5.)

## 5. Results: the survival table (the honest yield)
Present `experiment_runs` verbatim — the point is the **ratio**, not a highlight reel.

| Hypothesis | Verdict | Key stat |
|---|---|---|
| SwingOverlay lineage survives DSR after 50-way selection | **certified** | Sharpe 6.3, DSR 0.999 |
| Causal positioning (fade funding crowding, market-neutral) survives walk-forward | **candidate** | WF Sharpe 1.41; corr-to-book **0.002** (orthogonal) |
| Funding-cap (顶格) → forced-unwind reversal | **candidate** | characterized; live-tracking |
| Funding-cap as a *mechanical* rule (fixed entry+7d, vol-direction, 12% stop) | **refuted** | Sharpe 0.41 |
| Fee-value fundamental screen *gated by* momentum | **refuted** | Sharpe 0.06 |
| Naive price-based crypto sector valuation-rotation (韭圈儿 port) | **refuted** | Sharpe 0.04 |
| Fee-revenue cross-sectional valuation anchor | **null** | Sharpe 0.13 |

**Selected refutations that taught the most** (from `REFUTATION_LEDGER.md`, cite the number):
- **R1** — the "edge gate" (in-sample IC-grid *direction* generalizes OOS): falsified, p=0.867;
  4 straight longs into a falling BTC (−$479) while the humble quality-floor baseline made money
  (+0.59 Sharpe). *Lesson: an in-sample IC grid is a description, not a predictor.*
- **R4** — "more strategies = more diversification": 5 DSR-certified strategies had mean mutual
  corr 0.67, **ENB = 2.16** → "one idea in five costumes." *Lesson: diversification is real only
  when correlation is measured, not counted.*
- **R6** — trend-following captures the parabolic winner (HYPE): +37% vs buy-and-hold +110%; the
  stop chopped us out of the asset we most wanted to hold. *Lesson: on a genuine narrative winner
  the alpha is selection + conviction-hold, not trend micro-management.*
- **R7** — widening the causal sleeve's universe (24→50 perps) adds edge: refuted; +1.34 Sharpe
  (24 majors) collapses to +0.12 (all-50). *Lesson: funding-crowding is a large-cap phenomenon;
  expand only behind a liquidity gate.*
- **R13** — a fee-value gate "validated" on a single OOS split (+0.75) was **refuted** under
  walk-forward (3/7 folds, +0.06). *Lesson (meta): we caught our own overclaim; one split is not
  validation. This is the protocol working on its authors.*
- **R18** — the forward-supply *cause* is tradeable at the unlock event: **refuted** with a
  control. Across 11 large 2024–25 cliff unlocks, raw 30d post-unlock alpha looked bearish
  (−9.75%, 82% negative) — but netting each token against its own non-event window flips it:
  control-adjusted effect **+15.8%, 9/10 positive, sign-test p=0.021** (unlock windows *beat*
  baseline), and the biggest unlocks show the biggest relief (TIA 82% → +34.7%). *Lesson: a
  scheduled, publicly-known cause is priced in — proximity to it is not an edge; trade the
  surprise, not the schedule. Directly tests, and tightens, the paper's own reflection→cause
  claim (§1): the cause survives as a **descriptor/risk-filter**, not as event-timing alpha.*

The methodological point: the **refutations are the product**. Six of seven recorded hypotheses did
not survive as deployable alpha; the discipline's value is that this is *known and permanent*.

## 6. The self-measuring substrate (systems contribution)
- **Predict → resolve → record → adjust**, in production. Every directional claim from each source
  (signal / positioning / forward-supply / conviction / narrative) is written as a dated prediction;
  a resolver marks it against realized benchmark-relative alpha at horizon; per-source hit-rate and
  directional alpha feed back into conviction weighting. (Ref: `prediction_resolver.py`.)
- **Engineering honesty for the paper:** as of 2026-07-15 only 1 of 5 sources (`signal`) had accrued
  outcomes — the other four (`positioning`, `forward_supply`, `conviction`, `narrative`) emitted
  live signals but never *persisted* a dated daily snapshot, so the resolver had nothing to read
  (two of the four target tables were empty; `narrative_snapshots` did not exist). All five are now
  wired to write one dated row/day (upsert on `(date,symbol)`), so per-source causal track records
  begin accruing — **measurable at horizon (~30 days), not before.** Report the fix and the honest
  clock; do not pre-state the result. (This gap — a resolver ready but starved of inputs — is itself
  a worked example of the proximity blindness in §1.)
- **Live paper book** (`causal_paper.py`): market-neutral NAV, daily mark / weekly rebalance — the
  validated deployable cadence. Turns the walk-forward *candidate* into a real, LP-showable number.
- **Agent substrate:** the whole apparatus is exposed over MCP (Streamable HTTP, 38 tools), so an
  external agent can query the universe, the exclusions, and — the reusable part — adopt the
  protocol. This is the "template for other agents" claim, stated as *portability of the discipline*,
  not portability of alpha.

## 7. ⏳ Live validation (cannot be written yet — accruing)
Reserve this section. To be filled only when the data clears:
- Causal-positioning paper NAV: ≥60–90 daily marks, ann. Sharpe with confidence interval, max DD,
  realized vs walk-forward expectation. (Book just (re)started accruing after the state-persistence fix.)
- Per-source predictive track records once ≥1 horizon of causal snapshots exists.
- 顶格 reversal candidate: out-of-sample episode outcomes with volume-direction confirmation.
- Deflated Sharpe recomputed on the *live* trials count.

## 8. Limitations & threats to validity (write honestly, prominently)
- Small n; candidates are candidates, not certified. Single operator / single market regime window.
- Survivorship in the *proposal* stream (we propose what we find plausible) — the ledger mitigates
  but does not eliminate it.
- Crypto microstructure: funding/borrow costs, liquidity gates, capacity limits on the large-cap signal.
- The reflection→cause thesis is a *frame*, not yet a proven source of excess return.

## 9. Reproducibility
- Open-sourced strategies (MIT) + the resolver/DSR/combiner tooling. Ledger is public by design.
- Exact universes, cost assumptions, fold definitions, and adjudication thresholds pre-registered.

## 10. Conclusion
The transferable asset is the loop and its graveyard. An autonomous agent that (a) pre-registers its
bar, (b) corrects for how many times it looked, and (c) is *forced* to remember what it disproved,
compounds negative knowledge faster than it fools itself — which, in a domain this overfit-prone, is
the only durable edge worth claiming.

---

### Appendix A — data availability
`experiment_runs`, `prediction_outcomes`, `causal_paper_nav`, `cause_snapshots_daily`,
`conviction_verdicts_daily` (Supabase); `REFUTATION_LEDGER.md`, `ARCHITECTURE.md`,
`CONVICTION_METHODOLOGY.md` (repo).

### Appendix B — the refutation ledger, in full
Reproduce R1–R13 verbatim as the paper's core evidence exhibit.
