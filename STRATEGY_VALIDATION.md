# Strategy Validation Checklist

> **Status:** Active guardrail. No strategy is "an edge" until it clears every step below.
> **Owner:** Seth (Railway + design), Minimax (Mac Mini execution).
> **Created:** 2026-06-21 (resolves `MINIMAX_SYNC §STRATEGY` S3 P0).

---

## Why this exists

The autoresearch loop (`autoresearch-mlx-gp`) runs 100+ TA combinations against limited data. **Most "winners" are spurious** — they fit the noise, die live, and burn capital. This document is the structural fix: every strategy must clear ten gates before it gets the word "edge" attached to it.

**The 4h long-short engine (`CometCloudStrategy`) is the current alpha candidate** per `MINIMAX_SYNC §STRATEGY`. It is also the test case: walk it through this checklist, fix what fails, ship v4. The same process applies to every future strategy.

---

## The 10 gates

### 1. Data source
- **Binance 4h** OHLCV ≥ 2 years (so ~4,300 candles, covers at least one full cycle)
- **Real fees** — 0.1% taker (or 0.075% with BNB discount; check current schedule)
- **Real funding rate** — sourced from Binance futures `/fapi/v1/fundingRate`, NOT zero or assumed
- **Realistic slippage** — assume 0.05% per fill unless order-book depth proves otherwise
- **No look-ahead** — every signal computed from data with timestamp ≤ `current_time`

### 2. Sample size
- **≥ 100 closed trades** for any reported metric. A Sharpe computed on 12 trades is a coin flip.
- Current freqtrade dry-run = 3 trades (`MINIMAX_SYNC §STRATEGY S1`). **No backtest report is meaningful at this count.** Paper trading or synthetic fills are the only path to scale.
- If signals are too rare, **relax the entry gate explicitly and document the change**; do not silently extend the time window to inflate trade count.

### 3. Walk-forward (out-of-sample by construction)
- **Train 12 months / test 1 month, roll 24×** (or equivalent granularity). Two years of data → 24 monthly OOS windows.
- **No overlap** between train and test slices.
- **Aggregate OOS metrics** — never report train metrics as the strategy's expected live performance.
- If the OOS Sharpe is materially below train Sharpe (>30% decay), the strategy is overfit. Reject and retune.

### 4. Purged / embargoed cross-validation
- **5% embargo** around major events: funding flips, exchange listings/delistings, oracle failures, governance attacks.
- This prevents a single event from leaking into both train and test via overlapping influence.
- Reference: López de Prado, *Advances in Financial Machine Learning*, ch. 7.

### 5. Multiple-testing awareness
- When comparing N strategy variants (autoresearch typically tests 50-200), **apply Bonferroni or Benjamini-Hochberg FDR** to the Sharpe / profit-factor p-values.
- Without correction, "the best of 100 random variants" will look significant by construction.
- `scripts/autoresearch-mlx-gp/screen.py` already has the screen layer; add a `multiple_testing.py` module if it doesn't exist.

### 6. Net-of-cost vs benchmark
The strategy's claim is "I add alpha" — prove it against three honest benchmarks:
- **(a) BTC hold** — buy BTC on day 0, never touch. Most crypto strategies lose to this.
- **(b) Equal-weight universe** — hold all 25+ tracked assets, rebalance weekly. The "average of my universe" baseline.
- **(c) Buy-and-hold universe** — same as (b) but no rebalancing (skip-cost control).

Reported metrics, net of fees + slippage:
- **CAGR** (compound annual growth rate)
- **Sharpe** (annualized, rf=0)
- **Sortino** (downside-only vol)
- **Max drawdown** (peak-to-trough, daily)
- **Win rate** (% of trades with positive PnL)
- **Profit factor** (gross profit / gross loss)
- **Turnover** (avg trades / week, cost-awareness)

**A strategy is only "alpha" if it beats (a) on Sharpe AND CAGR net of costs.**

### 7. Regime-segmented report
Aggregate metrics hide regime risk. Always report **per regime**:
- Tightening · Risk-Off · Stagflation · Neutral · Easing · Risk-On · Goldilocks
- A strategy that prints 80% win rate in `Risk-On` and -40% in `Risk-Off` is NOT an edge — it's a regime bet.
- **If a regime contributes >50% of drawdown, the strategy MUST either (a) auto-shut-down in that regime, or (b) carry an explicit `risk_off_shutoff: true` flag in the config.**
- Source regime from Mac Mini's `cis:local_scores` payload (canonical contract `v1.0`, see `src/api/contracts/cis_push.py`).

### 8. Out-of-sample holdout
- **Final 20% of available data is never touched during development.** No tuning, no thresholds, no parameter search.
- Run the locked strategy on the holdout. **Single metric reported: OOS Sharpe net of costs.**
- If this number isn't competitive, ship nothing.

### 9. Live paper period
- **≥ 30 days of dry-run** on Binance testnet or local dry-run before any "edge" claim.
- Track the full ledger: entry, exit, PnL, max adverse excursion, fill quality vs backtest.
- **Compare live metrics vs backtest OOS**: a 30% degradation is normal (slippage, latency, regime drift). >50% means the backtest is wrong, not the live market.
- Connect results to Supabase `trade_results` (Railway) via the existing `signal_outcome_tracker.py`.

### 10. Reviewer sign-off
- **One shadow reviewer (Minimax or another Seth) walks the full pipeline independently.** The reviewer is NOT the developer.
- Reviewer checks: (1) data, (2) trade count, (3) walk-forward OOS, (4) benchmark comparison, (5) regime breakdown, (6) holdout untouched, (7) live paper period.
- Reviewer writes a 5-line verdict in the backtest report header: `PASS / FAIL / NEEDS-WORK (with reason)`.
- Without a reviewer sign-off, the strategy is **experimental, not an edge**.

---

## Current state (2026-06-21)

| Strategy | Where | Gates passed | Notes |
|---|---|---|---|
| `CISEnhancedStrategy.py` (live v3) | `/Volumes/.../freqtrade/.../strategies/` | 1, 2-partial (3 trades), 7-partial | All others fail. Walk-forward gap. |
| `CometCloudStrategy.py` (Shadow v2) | `Shadow/freqtrade/.../strategies/` | 1, 6-partial | Compliance-violating; LLM-dependent. |
| `CISEnhancedStrategyV4` (this PR) | TBD | 1, 4, 5, 6, 7 (designed-in) | 2, 3, 8, 9, 10 require Mac execution. |
| `CometCloudLongShortV4` (this PR) | TBD | 1, 4, 5, 6, 7 (designed-in) | Same as above. |

**To clear gate 3 (walk-forward) and gate 2 (≥ 100 trades) for v4:**
- `scripts/run_freqtrade_backtest.py` (this PR) — `python3 scripts/run_freqtrade_backtest.py --strategy CISEnhancedStrategyV4 --walk-forward 12 1 24 --timerange 20240101-20260601 --export supabase`
- Mac-only execution (Binance 4h data geo-blocked on Railway).

---

## Anti-patterns (red flags in a backtest report)

These are the most common ways a "wins" report is actually a lie:

1. **In-sample on full window** — train + test on the same 2 years, no split. The strategy fits noise.
2. **Survivorship-biased universe** — only backtested on assets that exist today. Delisted ones vanish from the candle feed.
3. **No fee / zero slippage** — instant 0.5% Sharpe boost, zero realism.
4. **Single-regime window** — backtest on a Risk-On year, claim "works in all markets".
5. **"Sharpe of 6"** — anything >3 annualized on 4h crypto is almost certainly overfit unless the strategy is market-making or stat-arb.
6. **Equity curve that looks like a ramp** — if there's no drawdown >10%, the backtest missed a tail event.
7. **"1.63 PF, 49.6% WR, 113 trades" (current AutoResearch v2)** — 49.6% WR with 113 trades is **statistically indistinguishable from 50% coin flip** (binomial p ≈ 0.89). Not an edge.

---

## What goes in a backtest report

Every backtest ships a markdown file at `reports/{strategy}_{YYYYMMDD}.md` containing:

```markdown
# Backtest Report — {strategy} — {date}
**Verdict:** {PASS | FAIL | NEEDS-WORK}
**Reviewer:** {name}

## Setup
- Strategy: ...
- Timerange: ...
- Pairs: ...
- Timeframe: ...
- Fee: 0.1% taker
- Slippage: 0.05% assumed

## Aggregate metrics
| metric | strategy | BTC-hold | equal-weight | universe-hold |
|---|---|---|---|---|
| CAGR |  |  |  |  |
| Sharpe |  |  |  |  |
| Sortino |  |  |  |  |
| MaxDD |  |  |  |  |
| WinRate |  | n/a | n/a | n/a |
| PF |  | n/a | n/a | n/a |
| n_trades |  | n/a | n/a | n/a |

## Walk-forward (train 12mo / test 1mo, 24 rolls)
| roll | train_sharpe | oos_sharpe | oos_pnl |
|---|---|---|---|

## Regime breakdown
| regime | n_trades | win_rate | avg_pnl | total_pnl | maxdd_within |
|---|---|---|---|---|---|

## Gate checklist (paste the 10)
- [x] Gate 1 — data source
- [x] Gate 2 — ≥ 100 closed trades
- [x] Gate 3 — walk-forward (24 OOS rolls)
- ...
- [ ] Gate 9 — 30d live paper period (TBD, started YYYY-MM-DD)

## Verdict reasoning
{5-line review}
```

---

## Related work (referenced by this checklist)

- `scripts/backtest_cis.py` — cross-sectional long-only top-quartile by CIS. **Not freqtrade; useful as a sanity check on the CIS engine itself.**
- `scripts/backtest_strategies.py` — long-short variants (5 strategies), market-neutral, on Supabase daily data. **Not freqtrade; useful for cross-sectional edge questions.**
- `scripts/run_freqtrade_backtest.py` (this PR) — **the freqtrade in-time-series backtest + walk-forward wrapper this checklist demands.**
- `src/api/contracts/cis_push.py::SCHEMA_VERSION` — the canonical contract for the `cis:local_scores` payload the strategies read.
- `MINIMAX_SYNC §STRATEGY` — the strategic context (4h LS is the alpha candidate, this is the validation harness).
- `.claude/skills/compliance-language/SKILL.md` — the substitution table used in Track A.

---

*Build things that don't apologize for their discipline.*
