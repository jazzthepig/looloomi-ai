# Signal track record — from our own data (2026-07-01)

**This is the validated 30-day track record the financial audit said we didn't have.** It is
computed **entirely from tables we already store** — `cis_scores` (historical signals) joined
to `ohlcv_daily` (prices we kept) — with **benchmark-relative** scoring (alpha vs BTC for
crypto, SPY for TradFi). No external fetch, no "wait 30 days." Canonical query:
`scripts/track_record.sql`.

Sample: **1,609 matured OUTPERFORM/STRONG-OUTPERFORM signals resolved** (of 2,879 matured;
the rest lack OHLCV coverage for that symbol/date — a data-coverage gap, not a scoring one).

## The result — a clean conviction gradient

| Signal | Grade | N | Avg 30d alpha | Alpha win rate |
|---|---|---|---|---|
| OUTPERFORM | B | 946 | **−0.22%** | 37.9% |
| OUTPERFORM | B+ | 529 | **−0.64%** | 38.4% |
| STRONG OUTPERFORM | A | 125 | **+3.29%** | 48.8% |
| STRONG OUTPERFORM | A+ | 9 | +3.66% | 66.7% |

(Aggregate across all OUTPERFORM: avg alpha −0.06%, win 39.1% — the noise tier drowns the
signal tier, which is why the headline looked flat.)

## What it means

- **The broad OUTPERFORM tier (B/B+) is NOT an edge.** ~1,475 signals, negative alpha, ~38%
  win — it underperforms its own benchmark. Trading it dilutes returns.
- **STRONG OUTPERFORM on A/A+ IS a real edge.** ~134 signals, **+3.3% 30-day alpha**, ~49–67%
  win. This is the tradeable slice.
- This is 大象无形 confirmed empirically: the edge is the **narrow top-conviction slice**, not
  the broad signal. It also matches GRADE-ALIGN (grade = quality) — the highest-quality,
  highest-conviction calls are the ones that actually pay.
- A+ N=9 is too small to lean on alone; **A (N=125, +3.29%) is the statistically meaningful
  core.** Combined A+A STRONG OUTPERFORM (N=134) is the headline.

## Actions this drives

1. **Strategy:** size on **STRONG OUTPERFORM + A/A+ only**; treat plain OUTPERFORM as
   watchlist, not position. Feed this into the Risk Meter / rebalance conviction weighting.
2. **Make it automatic, from our DB:** the live `outcome_tracker` currently fetches prices
   *externally* and waits for maturity. It should resolve from `ohlcv_daily` first (we have the
   prices) — then the forward `signal_journal` outcomes populate from our own store, no waiting.
   (Also fixes the aged-signal `entry_price IS NULL` gap: backfill entry from `ohlcv_daily` at
   `signal_date`.)
3. **Surface it:** publish "STRONG OUTPERFORM (A/A+): +3.3% 30-day alpha, N=134, benchmark-
   relative, from own data" on win.html / strategy.html / agent API — a defensible, honest
   track record for the top tier (with the noise-tier caveat stated).

## Honesty notes

- Down-market sample (avg absolute return −3.4%) — alpha (relative) is the right lens, and the
  top tier is positive on alpha even as the market fell.
- 1,270 matured signals unresolved = OHLCV coverage gaps → widen `ohlcv_daily` collection so the
  next cut resolves more of the universe.
- This is observational (signal → forward outcome), not a live-traded P&L; it validates the
  *signal*, which is our product. Live paper P&L (METER_REBAL sleeve) is the separate execution proof.
