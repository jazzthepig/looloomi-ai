# Honest audit — looloomi.ai / CometCloud, from a financial engineer's chair

**Date:** 2026-06-30
**Lens:** A skeptical buy-side quant / financial engineer evaluating whether to (a) trust the
signals enough to allocate, and (b) consume the data as an agent. No charity, no marketing.
**Method:** live API + dashboard + source code (this is an internal honest audit, written
adversarially on purpose).

---

## Bottom line up front

The **infrastructure is real and genuinely good**. The **alpha is unproven**, and the only
live evidence that exists is **negative or mis-measured**. As of today I could not allocate
capital against this, and I would not present the CIS scores to an IC as a validated signal.
It is a strong *research + agent-data platform* wearing the language of a *proven strategy* —
and the gap between those two is the single biggest risk. To the team's credit, the codebase
**documents its own unproven status** honestly (CLAUDE.md, MINIMAX_TRADING_TRIGGER, the
validation gates). The danger is the investor-facing surface outrunning that honesty.

---

## What is real (don't undersell this)

- Live, multi-source data pipeline (CoinGecko Pro, DeFiLlama, EODHD, FNG) with caching,
  84-asset universe, 25 protocols, refreshed ~30 min. This works.
- A coherent 5-pillar scoring engine (T1 Mac + T2 Railway), regime detection, MCP server
  (35 tools), A2A card, agent API. The **substrate / agent-consumability** story is legitimate
  and is arguably the real product.
- Compliance discipline (positioning-only language), evidence-tiered outputs with confidence
  labels, an explicit validation-gate doc, and a harness that now self-checks the loop daily.
- Paper-trading plumbing that opens/closes positions and persists a track record.

That is more real engineering than most "AI crypto" decks have. Credit where due.

## What is claimed vs proven — the gap

| Claim implied by the product | Proven? | Evidence |
|---|---|---|
| CIS scores are predictive "intelligence" | **No** | CIS IC vs forward returns is borderline/undemonstrated; CIS-as-gate was *harmful* in the team's own testing |
| Our OUTPERFORM signals work | **Negative so far** | Live tracker: 34 closed, **0% win rate**, Sharpe **−0.97**; 30-day outcomes **0/12** |
| There is a track record | **No (not validated)** | No walk-forward backtest yet (S5 CIS-history backfill + S1 4h L/S both pending); 4h dry-run had 3-4 trades |
| Momentum L/S Sharpe ~0.73 | **Unverified** | Not yet net-of-cost, walk-forward, n≥100, purged CV |
| cause-proximity / 出圈 edge | **Unproven heuristic** | New; D3 holder data not even wired; D4 has no history; honestly labeled a heuristic |
| $500M+ capacity / $5B FoF | **Modeled, not measured** | executability is a sqrt-impact *estimate*; real order-book depth geo-blocked on Railway |

## Methodology critiques (the ones that matter)

1. **Measurement is mis-specified against the signal's own definition.** "OUTPERFORM" is a
   *relative* claim, but the performance/outcome tracker scores *absolute* return_pct. In a
   Tightening down-market, an asset can be down yet still outperform its peers — and it gets
   logged as a "loss." So the headline **0% win rate is partly an artifact** of measuring the
   wrong thing, AND it means we genuinely cannot tell whether the relative call worked. **Fix:
   score outcomes benchmark-relative (alpha vs category/BTC), not raw return.** Until then the
   win-rate number is both unflattering and uninformative.

2. **Historical backtests carry look-ahead.** CIS history isn't backfilled (S5 pending), so any
   pre-backfill backtest reads *today's* CIS state at every past candle — a constant-signal
   pseudo-backtest. Any Sharpe/return quoted from that is not trustworthy. (Live forward signals
   ARE point-in-time and clean — the contamination is only in historicals.)

3. **The strategy is hand-set, not fit.** POSITION_FRAC=0.10, HAIRCUT=0.60, SHORT_BOOST=0.30,
   the grade→weight map, regime exposure factors — all hardcoded constants. That is a *rules
   opinion*, defensible as priors, but it is not an optimized or validated strategy, and it
   should not be described as one. The rebalance backtest itself showed ~−0.25%/−0.51% CAGR
   (defensive in bear, lags bull) — modest at best.

4. **No statistical significance.** Sharpe on 34 sparse event-driven returns has no confidence
   interval and is dominated by a down-market regime. Autoresearch over many candidate factors
   invites multiple-testing/overfitting; the validation gates (purged/embargoed CV, Holm/BH-FDR)
   exist on paper but nothing has passed them yet.

5. **Data-quality controls are fragile.** A **−94% drawdown was displayed live until today**
   (a −100% price=0 sentinel compounding) — that it reached a public investor tab is itself a
   controls red flag. Also: MKR volume reported $42K vs ~$50M real; a corrupt macro brief was
   serving structured junk; TradFi prices via EODHD/yfinance fallbacks. For anything touching
   capital, this is the area I'd hammer in DD.

## What I would require before allocating (the DD ask)

1. **Out-of-sample IC** of CIS vs forward *benchmark-relative* returns, by regime, with CIs.
2. A **real walk-forward backtest**: S5 history backfill → S1 (n≥100, net-of-cost, purged/
   embargoed CV, vs BTC-hold + equal-weight), passing the STRATEGY_VALIDATION gates.
3. **Benchmark-relative outcome scoring** in the live tracker (fix critique #1).
4. **Calibration** (or honest labeling as priors) of the meter/rebalance constants.
5. **Measured capacity** — real depth/impact data, not a sqrt model, for any AUM claim.
6. **60–90 days of clean live paper track record** on the now-fixed metrics, benchmark-relative.

## Verdict

**As a strategy: not allocatable today.** Unproven signal, negative/mis-measured live evidence,
no validated walk-forward record, hand-set parameters.

**As an agent-data substrate / research platform: genuinely interesting and differentiated** —
the moat is the hard-to-verify upstream judgment (holder diffusion, proximity-to-cause) *if and
when* it's validated and shipped with provenance + outcomes. That is the right thing to sell, and
it's honest to sell it as "intelligence to help you decide," not "a proven edge."

**Single highest-priority fix for credibility:** make the outcome tracker benchmark-relative
(critique #1) and turn on the validated walk-forward (S5→S1). Everything the investor page asserts
should trace to one of those numbers, or it shouldn't be asserted. The team already knows this —
the job is to not let the narrative get ahead of it.
