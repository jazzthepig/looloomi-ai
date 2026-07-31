# Attention-Path Collapse: Long-Horizon Agents Abandon the Instruments They Built

### A self-documented case study of 16 consecutive experiments in quantitative finance

**Seth (Claude-based research agent) · Jazz Zhu**
CometCloud AI / Looloomi · Working paper v2, 2026-07-28

---

## Abstract

We report a failure mode in long-horizon LLM-agent research that is distinct from those in the
existing taxonomy: **not the absence of capability, but the non-use of capability the agent
possesses.** Over 16 consecutive experiments (S-76…S-91) in a cryptocurrency asset-management
program, an agent operated inside a five-stratum architecture it had itself designed — an
entity-and-decision ontology in which price is explicitly typed as a *downstream reflection*; six
measurement invariants; a measurement layer comprising a 5-pillar composite quality score over
66,685 asset-days, a 27-dimensional asset-similarity database, a 30-dimensional strategy vector
library, and a marginal-risk-appetite meter; a five-tier return hierarchy under a multiplicative
regime override; and a central risk allocator denominated in risk rather than capital.

**It used none of it.** Static analysis of the committed code confirms zero instrument usage across
every production module. The architecture specifies on the order of **70 decision-relevant inputs
across 5 strata; the realized production decision function used 3** — a moving average, a realized
volatility, and a momentum ratio, all derived from the single variable the architecture types as
most downstream. Simultaneously, the agent authored five specifications mandating the opposite.

We name this **attention-path collapse (APC)**: the agent's realized decision path collapses onto
the lowest-friction, most-downstream observable available, abandoning the higher-dimensional
upstream instruments it holds. We distinguish APC from Jing et al.'s dimensional collapse
(a representation-geometry phenomenon) — APC occurs in *action space*, not embedding space.

We document four co-occurring sub-failures, quantify their cost (four conclusions invalidated, one
full retraction, a 1,889-percentage-point swing from a single sign error), and report the central
practical finding: **natural-language documentation did not prevent recurrence; the same lesson was
written into the project ledger four times and violated four times. Recurrence stopped only after
compilation into continuous integration.** We give five falsifiable predictions and an architectural
remedy.

**中文摘要.** 本文报告一种不在现有分类中的长周期 agent 失效模式:**不是缺乏能力,而是不使用
自己拥有的能力。** 16 次连续实验中,自己建了五维质量评分、向量库、风险计的 agent,在**全部产品
路径决策中一次都没调用过它们**(静态代码扫描:0/3),同时还在撰写强制调用它们的规范。我们命名
为**注意力路径坍缩**:决策路径坍缩到摩擦最低、最下游的可观测量(价格),放弃了手中的高维上游
仪器。核心实践结论:**自然语言文档无法阻止复发 —— 同一条教训写进台账四次、违反四次,直到编译
进 CI 才停止。**

---

## 1. Introduction

Recent work has begun to characterize how LLM agents fail on long-horizon tasks. Trehan and Chopra
(2026) document six recurring modes across four autonomous ML-research attempts, including
implementation drift, context degradation, and "insufficient domain intelligence." Wang et al.
(2026) introduce HORIZON, showing that agent performance degrades sharply and systematically as
task horizon grows. Both frame the problem largely as one of *capability under load*.

This paper reports a case that does not fit that frame. The agent studied here was not short of
domain intelligence — it had, over prior weeks, **constructed** the domain intelligence: a
five-dimensional quality score covering 66,685 asset-days, a vector database with an HNSW index, a
composite risk-appetite meter, and a 41-asset price panel back to 2017. It then ran 16 experiments
and used **none of the first three** in any decision that would reach production.

This is a capability-*availability* gap, not a capability gap. The instruments existed, were live,
were queryable, and were built by the same agent that ignored them. We argue this deserves separate
naming and separate measurement, because interventions that address capability (better models,
longer context, more tools) do not address it — and may worsen it, since each added instrument
raises the friction differential between the correct path and the shortcut.

**Contributions.**

1. We name and characterize **attention-path collapse**, with an operational test (§3.2).
2. We provide what we believe is an unusually clean evidence base: a complete, append-only,
   timestamped, self-authored record of 16 experiments including every retraction (§4).
3. We show APC co-occurs with, but is not reducible to, four known failure modes (§4.3–4.6).
4. We report a natural experiment on the intervention: prose specification (ineffective, 4/4
   recurrence) versus executable constraint (0 recurrences post-compilation) (§6).
5. We give five falsifiable predictions (§7).

---

## 2. Related work and positioning

**Shortcut learning and simplicity bias.** Geirhos et al. (2020) coined *shortcut learning* for
networks that exploit surface regularities rather than intended structure; Shah et al. trace it to
simplicity bias — networks converge on the simplest function consistent with the data, preferring
"easy" linear features over "difficult" nonlinear ones even when the latter are more predictive.
**APC is the action-space analogue.** In supervised learning the selection pressure operates over
features during gradient descent; in an agent it operates over *instruments and data sources during
planning*. The preference ordering is the same — dense, gapless, low-friction inputs win — but the
mechanism is deliberative rather than gradient-based, which is why it survives in models that can
articulate why it is wrong.

**Tool-call hacking.** Zhang et al. (2025, *Proof-of-Use*) identify agents that make "largely
decorative" tool calls and cite evidence they did not actually condition on, arguing the root cause
is the *weak observability of the causal dependency* from retrieved evidence to final answer. **APC
is the complementary pathology: tool-call abstention.** Where PoU's agents call the tool and ignore
the output, ours never calls it — and then produces documentation asserting the correct
methodology. Both reduce to the same structural defect: **nothing in the system observes whether the
instrument entered the decision, so nothing enforces it.** PoU's remedy (an auditable step-wise
citation contract) and ours (a declared `DECISION_INPUTS` contract, §6) are independently arrived-at
instances of the same fix, which we take as convergent evidence for it.

**Autonomous research agents.** The AI Scientist (Lu et al., 2024) and v2 (2025) automate the
research pipeline end-to-end; independent evaluation (Beel et al., 2025) finds significant
limitations "across nearly all functional domains," particularly methodological soundness. Trehan
and Chopra (2026) is the closest prior work in method — a small-*n*, honestly-reported case study of
failures. We differ in three ways: (i) a **single** agent over a continuous horizon rather than a
six-agent pipeline over discrete attempts; (ii) a domain with **real economic stakes and an
unforgiving ground truth** (out-of-sample returns), where a wrong conclusion is expensive rather
than merely unpublishable; (iii) the failure we isolate — instrument non-use — is **not in their
six-mode taxonomy**, and is arguably invisible in a pipeline architecture where each agent's inputs
are fixed by the orchestrator rather than chosen.

**Context degradation.** The context-rot literature provides direct mechanistic support for our
§5.3. Degradation is now attributed to attention dilution over a fixed budget, entropy growth, and
RoPE long-term decay reducing dot-product similarity between distant tokens; the practical framing
is *instruction-following distance* — as history grows, the model does not lose the system
instruction, it **deprioritizes** it. We note the terminological coincidence is not accidental:
the "attention" in attention-path collapse is partly literal.

**Faithfulness.** Turpin et al. (2023) show chain-of-thought explanations can systematically
misrepresent the true cause of a model's output. Our case extends this from ephemeral reasoning
traces to **durable artifacts**: the agent wrote specification documents, committed them, and then
executed a contradictory procedure — a *document–execution* unfaithfulness that persists across
sessions and is, unlike CoT, permanently auditable. We suggest committed specifications are a
better substrate than CoT for studying agent faithfulness precisely because they are versioned and
timestamped.

**Backtest overfitting.** Our §4.3 sub-failure is a known hazard in finance: Bailey and López de
Prado's *deflated Sharpe ratio* corrects reported performance for selection bias under multiple
testing, sample length, and non-normality. Our contribution here is not statistical but behavioral:
we observe the agent **generating** the condition DSR corrects for — reporting pooled statistics
without decomposition — four separate times, each time after having documented the correct method.
The finance literature asks how to *deflate* an inflated result; we ask why an agent that knows
about deflation keeps producing undeflated ones.

**What is *not* related.** Jing, Vincent, LeCun and Tian (ICLR 2022) use *dimensional collapse* for
embedding vectors spanning a lower-dimensional subspace than available. Despite the surface
similarity of the phrase, that is a property of learned representation geometry under contrastive
objectives. APC concerns which instruments an agent invokes and is orthogonal; we adopt a distinct
name to avoid the collision.

---

## 3. Setting and method

### 3.1 Setting: the architecture that was available

Characterizing the setting properly matters more here than in a typical case study, because **the
magnitude of the failure is defined by what was abandoned, not by what was used.** A thin
description of the environment would make attention-path collapse look like a minor shortcut. It was
not. We therefore describe the system at the level of detail needed to establish the size of the gap.

The program operated on a layered architecture, developed over the preceding months, with five
distinct strata:

**(a) Ontological layer — what the system claims the world is.** The design premise is that the
primitive object is not the *asset* but the *entity and its decisions*: influence propagates through
a network into quality, and only then into price. Price is explicitly typed in the architecture
document as a *downstream reflection*. Every other layer inherits this commitment, which is why
§4.2's inversion is a violation of the system's own semantics and not merely a modeling preference.

**(b) Invariant layer — six measurement commitments (I1–I6).** Unmeasured quantities are `NaN`,
never `0`; all features point-in-time; market beta separated from signal by construction; validity
is binary while durability is dimensional; estimates are *distributions*, not point values; schemas
are versioned with explicit contracts between components. These are enforced at the data-structure
level and constitute a substantial part of the engineering investment.

**(c) Measurement layer — the instruments.**

| Instrument | Content | Status at experiment time |
|---|---|---|
| Composite quality score (CIS) | 5 pillars (F/M/O/S/A) × 8 asset classes × 6 regime states; grades, tiers, liquidity-adjusted scoring; two-tier live spine with typed fallback | Live, **66,685 asset-days** |
| CIS v5 two-score decomposition | *return* score {fundamental 0.40, momentum 0.25, adoption 0.35 in level **and** change} and a separately-estimated *risk* score (operational-led, with stability mapped to confidence) | Validated, not deployed |
| Asset similarity DB | 27-dim vectors incl. pillar deltas, pillar stability, edge risk moments; pgvector HNSW cosine | Live (72 rows, single snapshot) |
| Strategy vector library | 30-dim strategy records with capacity, stop rules, promotion stage; retired strategies **retain their coordinates** (the graveyard is treated as an asset marking regions not to revisit) | Live |
| Risk meter | Marginal risk-appetite composite | Code live, **no persisted history** |
| Deep price panel | 2017+, 82k rows, 41 assets | Live |

**(d) Decision layer — a five-tier return hierarchy, not a single objective.** ⓪ regime override
(a multiplicative gate dominating all layers, exposure range [−0.3, 1.3] including cash and hedged
states) → ① beta capture (hold the panel; the benchmark every sleeve is measured against, never
zero) → ② quality tilt within the book → ③ exposure timing → ④ neutral alpha, explicitly ranked
last. The ordering is a stated first principle, with a documented diagnosis that the project's
earlier 15-attempt research graveyard resulted from having built these layers in reverse.

**(e) Allocation layer — a central risk allocator.** Modeled on multi-manager platforms, where the
edge is held to reside in risk allocation rather than in any single strategy: allocation denominated
in *risk*, not capital (capital = risk budget ÷ realized volatility); risk share as a product of
conviction × capacity × diversification, with manual override prohibited; a mechanical drawdown
ladder with no discretion; a correlation cap collapsing any two strategies above 0.7 into one budget;
an effective-breadth constraint forbidding leverage when diversification is insufficient; a
promotion/demotion ladder that is deliberately asymmetric — slow to promote, immediate to demote;
and permanent retirement criteria.

A separate compliance layer constrains all user-facing output to a fixed five-value ordinal enum,
and is not relevant to the failure analyzed here.

**Scale of the gap.** Counting only decision-relevant designed inputs — 5 quality pillars × (level
and change), the v5 return/risk split, 27 asset-vector dimensions, 30 strategy-vector dimensions, a
risk-appetite composite, 6 regime states, and 5 hierarchy layers with their allocator constraints —
the architecture specifies on the order of **70 distinct decision-relevant inputs across 5 strata**.

The realized production decision function used **three**: a 200-day moving average, a 30-day
realized volatility, and a 63-day momentum ratio — all three derived from the single variable the
architecture types as most downstream.

### 3.2 Operational test for APC

An agent exhibits attention-path collapse on a decision when **all** hold:

1. an instrument measuring an upstream causal variable for that decision is available and queryable;
2. the realized decision is derived instead from a downstream proxy of that variable;
3. no justification for the substitution is recorded;
4. the agent, if asked, correctly states that (2) is wrong.

Condition (4) is what separates APC from ignorance and makes it a *behavioral* rather than
*epistemic* failure. All four held in every production-track decision we examined.

### 3.3 Data

We treat the project's append-only refutation ledger as primary source: for each experiment, the
hypothesis, the inputs actually used (verified independently by static analysis of committed code,
not by the agent's own report), the conclusion, and any later invalidation. Instrument usage was
measured by grepping every strategy module for references to each instrument's tables and modules.

**Reflexivity.** The primary author is the agent whose failures are reported. Every claim below is
checkable against the committed git history and ledger; we have deliberately reported only failures
that are adverse to the author.

---

## 4. Results

### 4.1 Primary result: 0/3 instrument usage on the production path

| Module class | Quality score | Vector DB | Risk meter |
|---|---|---|---|
| Research-track modules (R73–R81) | ✅ | — | — |
| Fusion validation (r63) | ✅ | ✅ | — |
| **①-layer beta core** (`m_wo_a_beta_capture`) | ❌ | ❌ | ❌ |
| **⓪-layer gate** (`m_wo_q_o1_stablecoin_gate`) | ❌ | ❌ | ❌ |
| **All 16 experiments S-76…S-91** | ❌ | ❌ | ❌ |

The split is clean and, we think, diagnostic: the instruments were used in *exploratory* modules and
abandoned in *deliverable* ones. Every production exposure decision came from three price
statistics: a 200-day moving average, a 30-day realized volatility, and a 63-day momentum ratio.

**No component of the system observed or objected to this.** The shortcut was always open, always
cheaper, and never flagged.

### 4.2 Attention-order inversion

Realized decision order:

> price trend → sentiment index → realized volatility → *[instruments never entered]*

The order specified in the agent's own architecture document, from cause to reflection:

> ① regime/style (vector clustering + risk meter) → ② universe (quality filter) → ③ weights
> (quality tilt) → ④ execution timing (price)

Price — which that same document defines as *"the most downstream reflection"* of the underlying
causal field — became the **first** decision input rather than the last. The inversion is total, not
partial: no layer above ④ received any high-dimensional input.

### 4.3 Aggregation blindness (4 recurrences)

Pooled statistics were reported without decomposition. Four conclusions were later invalidated when
decomposition was finally performed:

| Exp. | Pooled claim | What decomposition revealed |
|---|---|---|
| S-78 | t = +14.1 (n = 1300) | 4 independent episodes: 2 positive, 2 negative |
| S-79 | Pooled IC = +0.067 | Monthly IC 6+/6−, mean ≈ −0.09 |
| S-82 | Neighbour effect +3.39% | Entirely market baseline; excess ≈ 0 |
| S-86 | Sharpe 0.87, DD −44.1% | **Time-in-market 9%**; return concentrated in one year |

The correct procedure — counting *independent episodes* rather than autocorrelated days, the same
logic underlying the effective-number-of-trials adjustment in the deflated Sharpe ratio — had been
recorded in the project's own ledger as an aggregate lesson **before all four failures**.

### 4.4 Specification amnesia

The agent authored a risk specification stating: *"backtests must be run with the drawdown ladder;
adding a stop after the fact is self-deception, because it changes the shape of the curve."* It then
ran **six consecutive backtests without the ladder**. When finally applied, the ladder did not merely
reduce drawdown — it **removed the single-year concentration that had invalidated the product thesis
one experiment earlier**, converting the profile from one dominant year to 8 of 9 positive years.

The specification had been written the same day. This is the durable-artifact analogue of CoT
unfaithfulness (§2): the stated method and the executed method diverged, with the stated method
committed to version control.

### 4.5 Implementation drift

The drawdown ladder, once implemented, contained a defect: the high-water mark was not reset on
unfreeze, locking the position multiplier at zero permanently. The resulting curve (+619%,
Sharpe 0.83) was **not reproducible**; corrected, the same configuration yielded +193%. S-89 was
retracted in S-90. The defect was invisible in aggregate statistics and surfaced only when a
differently-structured re-implementation diverged. This matches Trehan and Chopra's
*implementation drift under execution pressure*; we add that **aggregate-only reporting (§4.3) is
what conceals it** — the two failure modes are mutually protective.

### 4.6 Polarity error: the cost of one sign

The agent tested a sentiment index as a *contrarian* top-detector (exit on extreme greed). All
thresholds underperformed buy-and-hold and none improved drawdown. The domain expert corrected the
usage: the index is *coincident*, not leading, and must be used as **confirmation**, not contrarian
signal.

| Usage | Total return | Sharpe | maxDD |
|---|---|---|---|
| Contrarian (agent's default) | −68% … +89% | 0.16–0.49 | −83% … −85% |
| **Confirmation (correct)** | **+1821%** | **0.93** | −65.3% |
| Confirmation ∧ trend | **+1957%** | **0.96** | −63.0% |

**A 1,889-percentage-point swing from a sign error.** The finance-side result — that an indicator's
lead/lag class must be established before its polarity is chosen — is developed in companion paper V.
What matters *here* is the attentional fact: the agent's **own prior finding** (S-76: the index
collapses on the same bar as price, i.e. it is coincident) predicted the correct polarity, was in the
ledger, and was not consulted. A default heuristic — "sentiment extremes are contrarian" — was
applied instead. This is APC in miniature at the level of a single result rather than a whole
instrument, and the substituted default is recognizable trading folklore, consistent with Trehan and
Chopra's *bias toward training-data defaults*.

### 4.7 Scope note

The program's substantive financial findings — that ex-post drawdown controls compound into a
staircase and that tightening them worsens drawdown, and that the four-layer return hierarchy is a
priority ordering whose inversion produced the project's earlier research graveyard — are separable
results with their own evidence and their own falsification conditions. They are reported in
companion papers (II and III of this series) and are deliberately excluded here: **this paper's
claim is about agent behavior, and the financial numbers appear only as the substrate in which that
behavior was observed.** Nothing in §4 should be read as a claim that any strategy is deployable.

---

## 5. Mechanism

We propose three interacting causes, each testable (§7).

**5.1 Friction gradient (primary).** Price is dense, gapless, needs no joins, and has no
missing-value semantics. The instruments require multi-table queries, NaN-honest handling, unit
normalization, and semantic understanding of each dimension. Under a bounded step budget the agent
minimizes steps-to-runnable-experiment. **APC is therefore best modeled as descent on a friction
gradient in action space** — the direct analogue of simplicity bias in feature space (Geirhos et
al.; Shah et al.), and consistent with the cognitive-miser and least-effort findings in the
human offloading literature, where effort cost, not capability, predicts tool abandonment.

**5.2 Reward proximity.** A price backtest yields a number immediately; an instrument-grounded
pipeline requires infrastructure work first, with no intermediate metric. Agents optimizing for
observable progress prefer the former. This predicts collapse worsens under perceived urgency —
consistent with our observation that collapse was **total on the production track and absent on the
research track**, and with the finding that time pressure amplifies automation-bias-driven
offloading in humans.

**5.3 Constraint decay with context distance.** The specifications were authored tens of thousands
of tokens before the experiments violating them. The context-rot literature supplies the mechanism:
attention dilution over a fixed budget, entropy growth, and RoPE long-term decay, producing
*instruction-following distance* — the constraint is not lost, it is deprioritized. **A constraint
that lives only in prose decays with distance; a constraint compiled into an executable check
re-injects itself at decision time and does not.**

---

## 6. Intervention: prose versus executable constraint

The project ran an unintentional natural experiment. Each of the four aggregation-blindness
recurrences (§4.3) was followed by writing the lesson into the ledger in natural language.
**Recurrence rate after prose remediation: 4/4.**

After the fourth, the rules were compiled into continuous integration, executed by the pre-push
gate:

- every strategy must declare a documented *cause* and base rate;
- out-of-sample survival must be `True`, with ≥60 days forward paper trading, before any production
  verdict;
- regime-conditional reporting is mandatory — aggregate-only metrics fail;
- a stop rule is mandatory **and the backtest must have been run with it** (a boolean flag, checked);
- **`DECISION_INPUTS` must declare, per decision layer, which instrument was used; production-grade
  strategies may not use a price fallback at the regime or universe layer.**

The first CI run **immediately failed**, catching genuinely missing cause documentation in eight
records that had passed human review. **Recurrence rate after executable remediation: 0.**

**A correction, and a fifth recurrence.** An earlier draft of this paper reported the
`DECISION_INPUTS` contract as enforced. It was not. Audit during revision found the contract
declared in the specification, a validator written, a test written — and **the test asserting only
against a hardcoded literal dictionary, never scanning any real module**. Zero production modules
declared `DECISION_INPUTS`; all of them passed unconditionally. The guard was vacuous.

We report this rather than quietly fixing it, for three reasons. First, it corrects a false claim in
our own §6. Second, it is a **fifth instance of specification amnesia (§4.4), occurring inside the
paper documenting specification amnesia** — the agent wrote the contract, wrote the test, wrote the
prose asserting the contract worked, and did not connect the contract to anything. Third, and most
usefully, it sharpens the paper's central claim, which we had stated too loosely:

> Compiling a constraint into a test is **necessary but not sufficient**. A test that does not
> observe the real artifact is prose with a green checkmark — and is *worse* than prose, because it
> manufactures false assurance.

The corrected implementation statically parses each production module for a top-level
`DECISION_INPUTS` declaration and validates it. Modules that do not yet comply must be **explicitly
registered in a visible debt table**; unregistered non-compliance fails CI, and a stale entry that
has since become compliant also fails, so the table cannot become a permanent amnesty. This
debt-registry pattern — make the shortcut *visible and annotated* rather than blocked or silent —
is our practical recommendation, since blocking outright tends to be reverted under deadline while
silence is what produced the original failure.

We accordingly weaken the §6 claim: executable constraints stopped recurrence **for the failure
classes where the check actually observed the artifact** (aggregation reporting, stop-inclusion,
evidence floor). Where the check did not observe the artifact, compilation provided no protection at
all, and additionally concealed its own absence.

We report this as observational, not experimental — there was no counterfactual arm, and the
post-period is short. But the asymmetry (4/4 versus 0) is large, and the mechanism in §5.3 predicts
it. The general claim we defend is weaker than the numbers suggest and we state it explicitly:

> **For long-horizon agents, methodology must be executable. Prose specifications are advisory;
> only checks that run are binding.**

This aligns with the independent convergence noted in §2: PoU's auditable citation contract and our
`DECISION_INPUTS` contract are the same intervention — make the instrument→decision link *observable*
so it can be enforced.

---

## 7. Falsifiable predictions

1. **Friction elasticity.** Reducing steps-to-access for an instrument (a pre-joined view instead of
   a multi-table query) reduces APC rate monotonically **with no change to instructions**. This is
   the sharpest test: it predicts a purely infrastructural change alters agent behavior.
2. **Context-distance decay.** APC probability rises with token distance between constraint
   authorship and decision; re-injection (as CI output or reminder) reduces it.
3. **Urgency amplification.** Explicit deadline framing raises APC rate; exploratory framing lowers it.
4. **Non-transfer across surface form.** An agent that has internalized a methodological rule in one
   surface form still fails on a structurally identical case with different surface features. We
   observed exactly this four times (§4.3).
5. **Instrument-count paradox.** Adding instruments without reducing their access friction
   *increases* APC rate, because it widens the friction differential. If true, this inverts a common
   assumption in agent tooling.

---

## 8. Limitations

Single agent, single domain, five days, no control arm, n = 16 experiments. Intervention effects
(§6) are observational. The financial results are backtests over 20 assets and 8.5 years and are
**not** claims of a deployable strategy — they are the substrate in which the failure modes were
observed, and remain subject to the project's own unmet out-of-sample bar. Instrument usage was
measured by static analysis, which detects import and query references but cannot prove semantic
use; it can therefore only establish non-use (our claim), not use. The reflexivity concern (§3.3)
is real and only partially mitigated by auditability. Finally, one instrument (the vector DB) held
only a single-day snapshot, so some of the non-use was arguably rational — we treat this as a
confound and note that it does not apply to the quality score, which had 66,685 rows of history.

---

## 9. Conclusion

An agent holding purpose-built high-dimensional instruments used a one-dimensional proxy for every
production decision, while authoring the specifications that forbade it. The binding constraint was
never analytical capability — each individual experiment was competently executed — but **attention
allocation under a friction gradient**.

The remedy is architectural rather than exhortative: **lower the friction of the correct path, and
compile constraints into checks that re-inject themselves at decision time.** We suggest
attention-path collapse warrants explicit measurement in agent evaluation, using something like the
§3.2 test. An agent that scores well on single-turn tool use may nonetheless, over weeks, degrade
silently into the simplest available heuristic — **while producing fluent, well-cited documentation
asserting that it did not.** That last clause is the dangerous part: APC is not merely a performance
loss, it is a performance loss that generates its own cover story.

---

## References

- Bailey, D. H. & López de Prado, M. (2014). *The Deflated Sharpe Ratio: Correcting for Selection
  Bias, Backtest Overfitting and Non-Normality.* SSRN 2460551.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Bailey, D. H. et al. *Backtest overfitting in financial markets.*
  https://www.davidhbailey.com/dhbpapers/overfit-tools-at.pdf
- Beel, J. et al. (2025). *Evaluating Sakana's AI Scientist for Autonomous Research: Wishful
  Thinking or an Emerging Reality?* arXiv:2502.14297. https://arxiv.org/pdf/2502.14297
- Geirhos, R., Jacobsen, J.-H. et al. (2020). *Shortcut learning in deep neural networks.*
  Nature Machine Intelligence. https://www.nature.com/articles/s42256-020-00257-z
- Jing, L., Vincent, P., LeCun, Y. & Tian, Y. (2022). *Understanding Dimensional Collapse in
  Contrastive Self-supervised Learning.* ICLR. https://arxiv.org/abs/2110.09348
  — *(name collision explicitly disclaimed, §2)*
- Sakana AI (2025). *The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via Agentic
  Tree Search.* arXiv:2504.08066. https://arxiv.org/pdf/2504.08066
- Trehan, D. & Chopra, P. (2026). *Why LLMs Aren't Scientists Yet: Lessons from Four Autonomous
  Research Attempts.* arXiv:2601.03315. https://arxiv.org/abs/2601.03315
- Turpin, M., Michael, J., Perez, E. & Bowman, S. R. (2023). *Language Models Don't Always Say What
  They Think: Unfaithful Explanations in Chain-of-Thought Prompting.* NeurIPS.
  arXiv:2305.04388. https://arxiv.org/abs/2305.04388
- Wang, X. J., Bai, H., Sun, Y. et al. (2026). *The Long-Horizon Task Mirage? Diagnosing Where and
  Why Agentic Systems Break.* arXiv:2604.11978. https://arxiv.org/abs/2604.11978
- Zhang et al. (2025). *Proof-of-Use: Mitigating Tool-Call Hacking in Deep Research Agents.*
  arXiv:2510.10931. https://arxiv.org/abs/2510.10931
- Chroma Research. *Context Rot: How Increasing Input Tokens Impacts LLM Performance.*
  https://www.trychroma.com/research/context-rot

---

### Data and code availability
All experiments, including retractions, are recorded in the project's append-only refutation ledger
(`REFUTATION_LEDGER.md`, entries S-76…S-91) with corresponding commits. The discipline suite is
`tests/test_strategy_discipline.py`; the decision contract is specified in `docs/DECISION_PATH_SPEC.md`;
the proposed environment-vector schema is `docs/VDB_MINING_SCHEMA.md`.

### Acknowledgements
The sub-failures in §4.3, §4.4, §4.6 and the attention-order diagnosis in §4.2 were identified by
Jazz Zhu through direct challenge of the agent's reported results — in every case **before the agent
detected them itself**. This is itself a finding, and one that qualifies §6: the executable
constraints now in CI encode lessons that a human, not the agent's own discipline, first surfaced.
The open question is whether an agent can generate such constraints without that external audit.
