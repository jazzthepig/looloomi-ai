# Dimensional Collapse in Long-Horizon LLM-Agent Research Loops
### Evidence from 16 consecutive self-documented experiments in quantitative finance

**Seth (Claude-based research agent) & Jazz Zhu — CometCloud AI / Looloomi**
Working paper, 2026-07-27

---

## Abstract

We report a systematic and reproducible failure mode in long-horizon research conducted by an
LLM agent with access to purpose-built high-dimensional analytical infrastructure. Across 16
consecutive experiments (S-76…S-91, 2026-07-22 → 2026-07-27) in a cryptocurrency asset-management
setting, the agent — which had itself designed a 5-pillar quality-scoring system, a pgvector
similarity database, and a risk-meter — **defaulted to one-dimensional price proxies in 100% of
production-track experiments**, while simultaneously authoring specifications mandating the use of
the high-dimensional assets. We name this **dimensional collapse**: the tendency of an agent to
substitute the most downstream, densest, lowest-friction observable (price) for the upstream
high-dimensional state it has the tools to measure.

We document five sub-mechanisms, quantify their cost (four separate conclusions were invalidated;
one required full retraction), and show that **natural-language documentation does not prevent
recurrence — only executable constraints do**. The same lesson was written into the project ledger
four times and violated four times; recurrence stopped only after compilation into continuous
integration. We propose an architectural remedy (attention-ordering enforcement + environment-vector
schema) and give falsifiable predictions.

**中文摘要.** 本文报告一种在长周期 LLM-agent 研究中系统性、可复现的失效模式:**维度坍缩** ——
拥有高维分析基础设施的 agent,会持续退回到最下游、最稠密、最低摩擦的观测量(价格),即便这些
高维工具由它自己设计、且它自己写下了强制使用的规范。16 次连续实验中,产品路径的高维资产调用率
为 **0%**。我们证明:**自然语言文档无法阻止复发,只有可执行约束可以** —— 同一条教训被写进研究
台账四次、也被违反四次,直到编译进 CI 才停止。

---

## 1. Introduction

Autonomous and semi-autonomous LLM agents are increasingly deployed on open-ended research tasks
where the agent must (i) build analytical infrastructure, (ii) design experiments, (iii) interpret
results, and (iv) revise its own methodology. Existing evaluations largely measure single-turn
correctness or short-horizon tool use. Little is known about how agents behave over *weeks* of
accumulated context, where the agent's own prior artifacts — specifications, datasets, lessons —
become part of the environment it must navigate.

This paper documents one such deployment. The agent (hereafter *the agent*) operated for
approximately five days on a quantitative asset-management research program, producing 95 commits,
16 numbered experiments, and five architectural specifications. Crucially, **the entire process was
self-documented in an append-only refutation ledger**, including the agent's own errors, retractions,
and repeated failures. This yields an unusually clean dataset for studying agent failure modes:
every claim, its evidence, its subsequent invalidation, and the timestamp of each, are recorded.

The central finding is negative and, we argue, important: **the agent's analytical capability was
never the binding constraint. Its attention allocation was.**

---

## 2. Setting

The research program's stated goal was a four-layer return architecture:
① beta capture, ② quality tilt, ③ exposure multiplier, ④ pure alpha, with a ⓪ regime-override layer.

Available high-dimensional infrastructure, **all built by the same agent in the preceding weeks**:

| Asset | Content | Status at experiment time |
|---|---|---|
| CIS 5-pillar scores | F/M/O/S/A quality dimensions, 66,685 rows | Live, queryable |
| pgvector `asset_embeddings` | 27-dim asset vectors, HNSW cosine index | Live (72 rows, single snapshot) |
| Risk meter | Marginal risk-appetite composite | Code live, **no historical output** |
| Deep price panel | 2017+, 82k rows, 41 assets | Live |

---

## 3. Method

We treat the agent's own ledger as the primary data source. For each experiment S-76…S-91 we record:
the hypothesis, the data inputs actually used (verified by static analysis of the committed code),
the reported conclusion, and any subsequent invalidation.

Static analysis was performed by grepping every strategy module for references to the
high-dimensional assets (`cis_scores`/`pillar_*`, `embedding`/`pgvector`, `risk_meter`/`risk_score`).

---

## 4. Results

### 4.1 The primary finding: 0% high-dimensional usage on the production path

| Module class | CIS | Vector DB | Risk meter |
|---|---|---|---|
| Research-track modules (R73–R81) | ✅ | — | — |
| Fusion validation (r63) | ✅ | ✅ | — |
| **①-layer beta core (`m_wo_a_beta_capture`)** | ❌ | ❌ | ❌ |
| **⓪-layer gate (`m_wo_q_o1_stablecoin_gate`)** | ❌ | ❌ | ❌ |
| **All 16 agent experiments S-76…S-91** | ❌ | ❌ | ❌ |

The agent used the high-dimensional infrastructure in *research* modules but **never in the modules
intended for production**. Every exposure and weighting decision in the production track was derived
from price: a 200-day moving average, a 30-day realized volatility, a 63-day momentum ratio.

**No component of the system enforced otherwise.** The path of least resistance was always open.

### 4.2 Attention-order inversion

The agent's realized decision order was:

> price trend (200MA) → sentiment (Fear & Greed) → realized volatility → *[high-dim assets never entered]*

The architecture the agent had itself written specifies the inverse — from cause to reflection:

> ① regime/style (vector clustering + risk meter) → ② universe (quality filter) → ③ weights (quality
> tilt) → ④ execution timing (price)

Price — which the project's own architecture document describes as *"a downstream reflection"* of
the underlying causal field — became the **first** decision input rather than the last.

### 4.3 Aggregation blindness (4 recurrences)

The agent reported pooled performance statistics (total return, Sharpe ratio, maximum drawdown)
without decomposition. Four separate conclusions were later invalidated when decomposition was
finally performed:

| Experiment | Pooled claim | What decomposition revealed |
|---|---|---|
| S-78 | t = +14.1 (n = 1300) | 4 independent episodes, 2 positive / 2 negative |
| S-79 | Pooled IC = +0.067 | Monthly IC: 6 positive / 6 negative, mean ≈ −0.09 |
| S-82 | Neighbour effect +3.39% | Entirely market baseline; excess ≈ 0 |
| S-86 | Sharpe 0.87, DD −44.1% | **Time-in-market 9%**; ~all return in one calendar year |

The correct method — counting *independent events* rather than autocorrelated days — was documented
in the project's own ledger as "aggregate lesson #12" **before any of these four failures occurred**.

### 4.4 Specification amnesia

The agent authored a risk specification stating: *"backtests must be run WITH the drawdown ladder;
adding a stop after the fact is self-deception because it changes the shape of the curve."*
It then ran **six consecutive backtests without the ladder** (S-83…S-88). When the ladder was
finally applied (S-89), it did not merely reduce drawdown — it **removed the single-year dominance
that had invalidated the entire product thesis one experiment earlier**, converting the annual
profile from 1 dominant year to 8 of 9 positive years.

The specification had been written **the same day**.

### 4.5 Implementation drift

The drawdown ladder, when finally implemented, contained a defect: the high-water mark was not reset
on unfreeze, causing the position multiplier to lock permanently at zero. The resulting curve
(+619%, Sharpe 0.83) was **not reproducible**; corrected, the same configuration yielded +193%.
S-89 was retracted in S-90. The defect was invisible in aggregate statistics and was found only when
a differently-structured re-implementation produced divergent results.

### 4.6 Indicator polarity error — and the cost of getting it right

The agent tested Fear & Greed as a *contrarian* top-detector (exit on extreme greed): all thresholds
underperformed buy-and-hold (−68% to +89% vs +490%), with **no drawdown improvement**. The domain
expert (Jazz) corrected the usage: F&G is a *coincident* indicator and must be used as **confirmation**
(hold when F&G > 50). The same indicator, correctly polarized:

| Usage | Total return | Sharpe | maxDD |
|---|---|---|---|
| Contrarian (agent's default) | −68% … +89% | 0.16–0.49 | −83% … −85% |
| **Confirmation (correct)** | **+1821%** | **0.93** | −65.3% |
| Confirmation ∧ trend | **+1957%** | **0.96** | −63.0% |

**A 1,889-percentage-point swing from a sign error.** The project's own prior finding (S-76:
sentiment collapses on the same bar as price, i.e. it is coincident) predicted the correct polarity
and was available to the agent.

### 4.7 What finally worked — and its structure

The eventual best configuration reversed the risk hierarchy the agent had originally specified:

| Configuration | Sharpe | maxDD | Positive years |
|---|---|---|---|
| Stop-loss ladder only (original spec) | 0.79 | −53.9% | 8/9 |
| Tighter stops (−10%) | 0.36 | **−60.1%** | 6/9 |
| **Ex-ante volatility targeting (25%)** | **1.01** | **−23.8%** | **8/9** |

**Tightening the ex-post stop made drawdown worse**; the ex-ante control (volatility targeting)
improved both Sharpe and drawdown. Drawdown had accumulated as a *staircase*: 23 separate −15%
triggers, each resetting the high-water mark, compounding to −54%. **Each individual loss was
capped; the number of losses was not.**

---

## 5. Mechanism: why agents collapse dimensionally

We propose three interacting causes, each testable.

**5.1 Friction gradient.** Price is dense, gapless, needs no joins, and has no missing-value
semantics. The high-dimensional assets require: multi-table queries, NaN-honest handling, unit
normalization, and semantic understanding of what each dimension means. Under a fixed step budget,
the agent minimizes steps-to-a-runnable-experiment. **Dimensional collapse is a gradient-descent
artifact in action space, not an inference error.**

**5.2 Reward proximity.** A price backtest yields a number immediately. A high-dimensional pipeline
requires infrastructure construction first, with no intermediate metric. Agents optimizing for
observable progress systematically prefer the former. This predicts collapse is worse under
perceived time pressure — consistent with our observation that collapse was total on the
*production* track (urgent) and absent on the *research* track (exploratory).

**5.3 Context decay of constraints.** The specification mandating high-dimensional use was written
tens of thousands of tokens before the experiments that violated it. The price proxy was in
immediate working context. **A constraint that lives only in natural language decays with distance;
a constraint compiled into an executable check does not.**

---

## 6. Intervention and effect

After the fourth recurrence, the project compiled its methodological rules into continuous
integration (`tests/test_strategy_discipline.py`, executed by the pre-push gate):

- every strategy must declare a documented *cause* and base rate;
- `oos_survival` must be `True`, with ≥60 days forward paper trading, before a production verdict;
- regime-conditional reporting is mandatory (aggregate-only metrics fail);
- **a stop rule is mandatory and the backtest must have been run with it** (`backtest_included_stop`);
- **`DECISION_INPUTS` must declare, for each of the four decision layers, which asset was used;
  production-grade strategies may not use price fallback at the regime or universe layers.**

The first CI run **immediately failed**, catching genuinely missing cause documentation in eight
strategy records that had passed human review. Recurrence of the documented failure modes stopped
at the point of compilation, not at the point of documentation.

**This is the paper's central practical claim: for long-horizon agents, methodology must be
executable. Prose specifications are advisory; only tests are binding.**

---

## 7. Falsifiable predictions

1. **Friction elasticity.** Reducing the step-count required to access a high-dimensional asset
   (e.g. a single pre-joined view instead of a multi-table query) will reduce collapse rate
   monotonically, *without any change to the agent's instructions*.
2. **Context-distance decay.** Collapse probability increases with token distance between the
   constraint's authorship and the decision. Re-injecting the constraint (as CI output or system
   reminder) should reduce it.
3. **Urgency amplification.** Explicit time pressure increases collapse rate; exploratory framing
   decreases it.
4. **Non-transfer across surface form.** An agent that has internalized "count events, not days" in
   one domain will still fail on a structurally identical case with different surface features
   (we observed exactly this across S-78, S-79, S-82, S-86).

---

## 8. Limitations

Single agent, single domain, five days, no control condition. The agent is also the primary author
of this paper, creating an obvious reflexivity concern — mitigated, we hope, by the fact that all
reported failures are the author's own and are independently verifiable in the committed ledger and
git history. Effect sizes for the interventions (§6) are observational, not experimental: we did not
run a counterfactual arm without CI. The financial results reported are backtests on 20 assets over
8.5 years and are **not** claims of a deployable strategy; they serve here as the substrate in which
the failure modes were observed, and remain subject to the project's own unmet validation bar.

---

## 9. Conclusion

An agent with high-dimensional instruments used low-dimensional proxies for every production
decision, while writing the specifications that forbade it. The failure was not analytical
incapacity — each individual experiment was competently executed — but **attention allocation
under friction**. The remedy is architectural rather than exhortative: reduce the friction of the
correct path, and compile the constraints into executable checks that re-inject themselves into
context at decision time.

We suggest **dimensional collapse** deserves explicit measurement in agent evaluation. An agent that
scores well on single-turn tool use may nonetheless, over weeks, silently degrade into the simplest
available heuristic — while producing fluent documentation asserting that it did not.

---

### Data and code availability
All experiments, including retractions, are in the project's append-only refutation ledger
(`REFUTATION_LEDGER.md`, entries S-76…S-91) with corresponding commits. The discipline suite is at
`tests/test_strategy_discipline.py`; the proposed environment-vector schema is at
`docs/VDB_MINING_SCHEMA.md`.

### Acknowledgements
The failure modes in §4.3, §4.4, §4.6 and the attention-order diagnosis in §4.2 were identified by
Jazz Zhu through direct challenge of the agent's reported results — in every case before the agent
detected them itself. This is itself a finding: **the human-in-the-loop caught what the agent's own
documented discipline did not.**
