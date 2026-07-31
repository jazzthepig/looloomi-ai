# The Drawdown Staircase: Why Tightening a Stop-Loss Can Increase Maximum Drawdown

### Ex-ante volatility targeting versus ex-post drawdown ladders in a high-volatility panel

**Seth (Claude-based research agent) · Jazz Zhu** — CometCloud AI / Looloomi
Paper III of the CometCloud series · Working paper, 2026-07-28

---

## Abstract

We document a counterintuitive but mechanically explicable result: in a high-volatility asset panel,
**tightening a drawdown-triggered de-risking rule from −15% to −10% made realized maximum drawdown
worse, from −53.9% to −60.1%**, while cutting the Sharpe ratio from 0.79 to 0.36 and reducing
positive years from 8/9 to 6/9. The mechanism is a *drawdown staircase*: each trigger de-risks at a
local low and then resets the high-water mark, so the next trigger measures from the reduced level.
Individual losses are capped; **the number of losses is not**, and the capped losses compound. Over
our sample the ladder fired 23 times across 339 in-market days, compounding to −54% despite no
single trigger permitting a loss larger than 15%.

We show that an **ex-ante** control dominates: scaling exposure to a 25% annualized volatility
target using a 30-day realized-volatility estimate yields Sharpe 1.01 and maximum drawdown −23.8%,
retaining 8/9 positive years. We further show the ordering matters for leverage: applying 2.0×
leverage to the un-optimized base (Sharpe 0.79) does not improve risk-adjusted return, while the
same leverage on the volatility-targeted base produces a profile matching buy-and-hold's return at
roughly half its drawdown. We give the condition under which the staircase dominates, an
implementation defect that silently invalidates ladder backtests, and the falsification conditions
for the result.

**中文摘要.** 本文记录一个反直觉但机制清晰的结果:**把回撤止损从 −15% 收紧到 −10%,实际最大回撤
反而恶化**(−53.9% → −60.1%),Sharpe 从 0.79 掉到 0.36,正收益年份从 8/9 降到 6/9。机制是
**回撤阶梯**:每次触发都在局部低点减仓并重置高水位,下一次从更低的基准再算。**单次损失被限制了,
次数没有被限制**,而被限制的损失在复利。事前控制(波动率目标)完胜:Sharpe 1.01,最大回撤 −23.8%。

---

## 1. The result

Stop-losses and drawdown ladders are the default risk control in discretionary and systematic
practice alike, and the implicit assumption is monotone: a tighter stop should produce a smaller
drawdown. It does not, and the reason is structural rather than sample-specific.

All figures: 20-asset equal-weight panel, 2018-01→2026-07, monthly rebalance, 10bps one-way cost,
point-in-time eligibility, identical base configuration across rows (active risk-ratio weighting,
trend gate with 10-day hysteresis, −0.3× short leg).

| Configuration | Total return | CAGR | Sharpe | max DD | Positive years |
|---|---|---|---|---|---|
| Buy-and-hold panel (benchmark) | +490% | 23.0% | 0.67 | −83.3% | — |
| Drawdown ladder, −15% trigger | +548% | 24.4% | 0.79 | −53.9% | 8/9 |
| Drawdown ladder, **−10% trigger** | **+76%** | 6.8% | **0.36** | **−60.1%** | **6/9** |
| Portfolio-level circuit breaker, −20/−30% | +2% | 0.2% | 0.07 | −32.1% | 1/9 |
| Ex-ante vol target, 40% | +337% | 18.8% | 0.83 | −38.6% | 8/9 |
| **Ex-ante vol target, 25%** | +259% | 16.1% | **1.01** | **−23.8%** | **8/9** |
| Vol target 25% × 1.5× leverage | +291% | 17.3% | 0.80 | −38.2% | 8/9 |
| **Vol target 25% × 2.0× leverage** | **+484%** | 22.9% | 0.87 | −39.1% | **8/9** |

Annual profile of the 25% vol-target configuration: 2018 +6%, 2019 +8%, 2020 +31%, 2021 +67%,
2022 +5%, 2023 +9%, 2024 +35%, 2025 −10%, 2026 +3%. The maximum drawdown episode ran
**2024-12-08 → 2025-11-12 (339 days) with 23 ladder triggers**.

A third configuration is worth recording because it fails for the *same* structural reason as the
tightened stop: an absolute portfolio-level circuit breaker measured from all-time high, with no
recovery mechanism, reduced maximum drawdown to −32.1% but destroyed the strategy (+2% total, 1/9
positive years) — once breached, it never re-enters. **Both failures are the same pathology: a rule
that measures from a mark it never resets, or resets in a way that ratchets downward.**

Two features are worth isolating. First, the tighter stop is worse on **every** axis simultaneously
— return, risk-adjusted return, drawdown, and consistency. This rules out the usual
return-for-safety trade-off interpretation. Second, the ex-ante control improves drawdown by 30
percentage points relative to the ex-post control while *also* improving Sharpe, which is the
signature of removing a structural defect rather than repricing a trade-off.

## 1b. Related work, and an honest narrowing of our claim

A literature review conducted *after* the first draft of this paper materially reduced what we can
claim as novel. We report the correction rather than quietly re-scoping.

**Volatility targeting is not our finding.** Moreira and Muir (*Journal of Finance*, 2017) established
that portfolios taking less risk when volatility is high earn large alphas and higher Sharpe ratios
across the market, value, momentum, profitability, ROE, investment, and BAB factors, and the currency
carry trade — because changes in volatility are not offset by proportional changes in expected
returns. **Our §1 volatility-targeting result is a rediscovery of theirs in a crypto panel, not a
contribution.** Any presentation of it as novel would be wrong.

**And it is contested.** Cederburg, O'Doherty, Wang and Yan (*Journal of Financial Economics*, 2020)
examine 103 equity strategies and find volatility-managed portfolios do **not** systematically
outperform their unmanaged counterparts: the spanning-regression alphas are not implementable in
real time, and reasonable out-of-sample versions generally earn *lower* certainty-equivalent returns
and Sharpe ratios. This is directly adverse to us and we flag it prominently, because our result is
exactly the kind of single-panel, in-sample finding their study is designed to deflate.

One qualification cuts in our favour and we state it without overclaiming: Cederburg et al. find
volatility management *does* enhance momentum, profitability, and BAB, while adding nothing for the
other six factors. Our base is trend- and momentum-driven, placing it in the subset where their
evidence is favourable. **This makes our result consistent with the more skeptical literature rather
than contradicted by it — but consistency is not confirmation, and a single panel cannot adjudicate
between these papers.**

**Stop-loss efficacy is regime-dependent, and this is known.** Kaminski and Lo (2014) show that under
a random walk, simple 0/1 stop-loss rules always reduce expected return, while in the presence of
momentum they can add value — efficacy depends on the return-generating process and on the dynamics
of the stop policy itself. Their framework supports our mechanism: our panel is momentum-driven, so
the *existence* of a beneficial stop is expected; what we address is the separate question of how
its benefit varies with the threshold.

**Whipsaw is known qualitatively.** Practitioner literature has long observed that stops set too
tight are triggered by ordinary fluctuation, producing consecutive stop-outs, higher costs, and
degraded performance, and at least one analysis notes that the drawdown relationship in trend
following is "less robust" than the skewness relationship. So the *direction* of our §1 result is not
unknown folklore.

**What remains ours**, and what this paper should be read as claiming:

1. A **closed-form condition** (§2) specifying exactly when tightening increases *cumulative*
   drawdown, expressed as an elasticity of trigger count to threshold. Whipsaw is usually stated as
   a qualitative caution; we give the inequality that decides it.
2. Identification of the **high-water-mark reset ratchet** as the compounding channel. This is
   distinct from generic whipsaw: the damage comes not merely from firing often, but from each firing
   **re-basing the reference mark downward**, so that capped losses compound as $(1-\delta)^n$. A
   stop that fires frequently *without* re-basing does not produce a staircase.
3. A documented instance with the count made explicit — **23 triggers over 339 days compounding to
   −54% with no single loss exceeding 15%** — and a directly testable no-reset control (§5.2).

We accordingly retitle our contribution from "tighter stops can be worse" (known) to **"the
reset rule, not the trigger rate, is what makes tighter stops worse"** (we believe new).

---

## 2. Mechanism: the staircase

Let the ladder de-risk when drawdown from the running high-water mark $H$ exceeds $\delta$, and let
the high-water mark reset on re-entry. Then each trigger contributes a factor of approximately
$(1-\delta)$ to cumulative drawdown, and $n$ triggers compound:

$$\text{DD}_{\text{cum}} \approx 1 - (1-\delta)^{n}$$

With $\delta = 0.15$ and the 23 triggers observed over 339 in-market days, this yields the −54%
actually realized. The rule guarantees *no single loss exceeds 15%*; it says nothing about $n$.

The comparative static is what produces the paradox. Tightening $\delta$ reduces the per-event term
but **increases the trigger rate**, because the threshold is crossed more often by ordinary noise.
Writing $n(\delta)$ for the trigger count,

$$\frac{\partial}{\partial \delta}\Big[1-(1-\delta)^{n(\delta)}\Big] \;<\; 0
\quad\text{whenever}\quad \left|\frac{\partial n}{\partial \delta}\right| \cdot \ln\frac{1}{1-\delta} \;>\; \frac{n}{1-\delta}$$

i.e. **whenever the trigger count is sufficiently elastic to the threshold, tightening the stop
increases cumulative drawdown.** In a high-volatility panel, where daily moves are large relative to
plausible stop distances, this elasticity is high — which is precisely the regime where stops feel
most necessary and are most often tightened. There is a second, compounding cost: each trigger
de-risks *at a local low* and re-enters later, so the rule systematically realizes the trough and
forgoes the rebound. This is a path-dependence cost invisible in any aggregate statistic.

## 3. Why the ex-ante control dominates

Volatility targeting sets exposure before the loss occurs:

$$e_t \;=\; \min\!\left(\text{cap},\; \frac{\sigma_{\text{target}}}{\hat\sigma_{t}^{(30)}}\right)$$

with $\hat\sigma^{(30)}$ a point-in-time 30-day realized-volatility estimate. Because realized
volatility is strongly autocorrelated, $\hat\sigma_t$ carries information about $\sigma_{t+1}$, so
exposure is already reduced when the large moves arrive. The ex-post ladder, by contrast, can only
act *after* the loss is realized, and pays the trough-realization cost each time. The staircase never
forms because exposure is continuous rather than triggered: there are no discrete events and hence
no $n$ to compound.

We emphasize the two controls are **not substitutes but a stack**, in this order:

1. **Ex-ante volatility targeting** — sets the base and removes the staircase;
2. **Drawdown ladder** — retained as *tail insurance* for the regime shifts volatility targeting
   cannot anticipate, not as the primary control;
3. **Leverage** — applied only to an already-optimized base.

Step 3 is not cosmetic. Applying 2.0× leverage to the Sharpe-0.79 base did not improve risk-adjusted
return, a result we initially misread as "leverage does not help this strategy." The correct reading
is that **leverage multiplies the base's Sharpe ratio, it does not create it**; on the Sharpe-1.01
base the same leverage produced a materially better profile. Leverage tested on an unoptimized base
yields a conclusion about the base, not about leverage.

## 4. Two implementation hazards

**4.1 The unfreeze defect.** In our first implementation, the high-water mark was not reset when the
freeze period ended. The position multiplier therefore locked at zero permanently once triggered.
The resulting curve (+619%, Sharpe 0.83) was **not reproducible** and the associated experiment was
retracted; corrected, the same configuration returned +193%. The defect is invisible in aggregate
statistics — the curve looked plausible — and surfaced only when a differently structured
re-implementation diverged. We recommend the ladder's unfreeze path carry a dedicated unit test
asserting high-water-mark reset; ours now does.

**4.2 Post-hoc stop attachment.** Applying a stop rule to an already-computed return series is not
an approximation of running the strategy with the stop; it changes the *shape* of the path and
therefore every subsequent trigger. In our sample, running the ladder inside the backtest rather than
attaching it afterward did not merely reduce drawdown — it eliminated a single-year return
concentration that had otherwise invalidated the strategy's thesis, converting the annual profile
from one dominant year to 8 of 9 positive years. **Post-hoc stops and in-loop stops are different
strategies, not different reports of one strategy.**

## 5. Falsification conditions

The result is stated to be falsifiable, and we specify how it would fail:

1. **Low-elasticity panels.** In an asset panel where the trigger count is insensitive to the
   threshold — low volatility relative to plausible stop distances — the inequality in §2 fails and
   tightening should behave monotonically. Finding monotone behavior *there* confirms rather than
   refutes the mechanism; finding it in a **high**-volatility panel refutes it.
2. **No-reset ladders.** If the high-water mark is not reset on re-entry, the staircase cannot form
   and the paradox should disappear. This is the cleanest direct test and does not require new data.
3. **Volatility-targeting failure under vol-of-vol.** If realized volatility loses autocorrelation —
   a jump-dominated regime — the ex-ante advantage should collapse toward the ex-post control.
4. **Trigger count.** If a replication reports a materially different $n$ for the same $\delta$ and
   panel, our arithmetic in §2 is wrong.

## 6. Limitations

Backtest on 20 assets over 8.5 years of a single asset class, on a panel with unusually high
volatility and a short history relative to what would be needed to sample multiple full cycles.
Parameters (25% target, 30-day estimator, −15%/−10% thresholds, 2.0× leverage) were selected within
this sample; the reported statistics are therefore not corrected for selection under multiple
testing, and a deflated Sharpe ratio (Bailey & López de Prado) would be the appropriate adjustment
before treating any of the levels as expectations. **We make no claim that any configuration here is
deployable**; the strategy has not passed the project's own out-of-sample bar (≥60 days forward
paper trading with regime-conditional reporting). What we do claim is the *comparative* and
*mechanical* result: the ordering (tighter stop worse) and its explanation, which follow from
structure rather than from parameter choice, and which §5.2 permits testing without new data.

The primary author is an AI research agent, and the analysis in this paper was prompted by the human
co-author's challenge of an earlier, aggregate-only presentation of the same backtests — a
methodological history reported in full in companion paper I.

## References

- Bailey, D. H. & López de Prado, M. (2014). *The Deflated Sharpe Ratio: Correcting for Selection
  Bias, Backtest Overfitting and Non-Normality.* SSRN 2460551.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Bailey, D. H., Borwein, J. M. et al. *Backtest overfitting in financial markets.*
  https://www.davidhbailey.com/dhbpapers/overfit-tools-at.pdf
- Cederburg, S., O'Doherty, M. S., Wang, F. & Yan, X. S. (2020). *On the performance of
  volatility-managed portfolios.* Journal of Financial Economics 138(1), 95–117.
  https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X
  — **adverse to §1; see §1b**
- Kaminski, K. & Lo, A. W. (2014). *When do stop-loss rules stop losses?* Journal of Financial
  Markets. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=968338
- Moreira, A. & Muir, T. (2017). *Volatility-Managed Portfolios.* Journal of Finance 72(4),
  1611–1644. https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513
  — **prior art for our §1 volatility-targeting result**
- CFA Institute (2026). *Why Tight Stop-Losses Often Hurt Investors.*
  https://rpc.cfainstitute.org/blogs/enterprising-investor/2026/why-tight-stop-losses-often-hurt-investors-and-what-robust-capital-growth-really-requires

### Disclosure
Research and drafting were performed by an AI research agent under human direction; the human author
takes full responsibility for all contents. The literature review in §1b was conducted after the
first draft and materially narrowed the paper's claims; the pre-review version overstated novelty.

### Data availability
Experiment records S-83…S-91, including the retraction of S-89 described in §4.1, are in the
project's append-only ledger (`REFUTATION_LEDGER.md`). The ladder implementation and its
unfreeze-reset unit tests are at `src/research/beta_core/risk_ladder.py`.
