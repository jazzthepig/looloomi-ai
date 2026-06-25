# Auto Paper Trading Trigger — Honest Framing

This trigger fires paper orders hourly from fresh CIS scores. As of 2026-06-25,
it is **deployed in `cis_scheduler.py` (commit `012022a`)** and runs every cron cycle.

## What this trigger measures

**Daily-frequency long-only CIS-gated strategy.**

That is the whole thing. It is a position-tilt strategy that:
- Looks at CIS scores hourly
- When a name crosses the regime threshold with signal OUTPERFORM/STRONG OUTPERFORM
- Opens a small LONG position

That's it. No shorting. No intraday signals. No multi-factor combination.

## What this trigger is NOT

- **NOT the headline edge.** Expected profile is **weak, possibly beta-like**.
- **NOT comparable to S1.** S1 is the 4h long-short proper walk-forward backtest.
  That is where real alpha lives (per STRATEGY_VALIDATION.md gate 3).
- **NOT a benchmark for fund performance.** A weak return here is an honest
  data point, not a failure. It validates the *infrastructure* (orders flow,
  positions tracked, P&L computed) more than it validates the *strategy*.

## Why we kept it conservative

We could loosen the gate (NEUTRAL with CIS buffer, larger cap, more asset
classes) to inflate trade count. We deliberately did not:

1. **Cap = 2 orders/cycle.** Hourly cron × 2 = 48 worst-case/day, but steady-
   state is ~10-15 new positions/day because most cycles have 0-2 qualifying
   names. This keeps the record legible as a fund-style tilt, not a bot.

2. **Strict gate.** Only `OUTPERFORM` and `STRONG OUTPERFORM` fire. No
   `NEUTRAL + CIS buffer` fallbacks. A faithful null hypothesis is more
   valuable for walk-forward comparison than a noisy inflated record.

3. **Dedup against open positions.** Skips symbols already held. Prevents
   re-adding on every cycle.

## Where to find it in code

`cis_scheduler.py` `run_cis_job()` → `# ── Auto paper trading ──` block.

```python
REGIME_THRESHOLD = {
    "TIGHTENING": 52, "RISK_OFF": 55, "EASING": 48,
    "RISK_ON": 48, "STAGFLATION": 58, "GOLDILOCKS": 46,
}
MAX_NEW_PER_CYCLE = 2

# Open positions fetched to skip already-held symbols
# Signal gate: OUTPERFORM or STRONG OUTPERFORM only
# Sizing: conviction_bps = min(800, ...) -- bounded at 8% of portfolio
```

## Verify it's running

```bash
tail -f /Volumes/CometCloudAI/cometcloud-local/_logs/cis_scheduler.log | grep TRADING
```

Look for:
- `[TRADING] N open positions: [...]` -- current open count
- `[TRADING] N paper orders placed | regime=...` -- successful fires
- `[TRADING] no qualifying assets | regime=...` -- gate is honest (most cycles)

## Where to push next (energy allocation)

**S1 -- 4h long-short proper walk-forward backtest.** This is the real alpha
candidate. Use STRATEGY_VALIDATION.md gate 3 as the validator. Current
freqtrade dry-run has 4 closed trades (per Railway trading/metrics) -- not
enough for validation gate 1 (>= 100 closed trades).

Tools available:
- `scripts/run_freqtrade_backtest.py` -- wrapper with walk-forward
- `scripts/backtest_strategies.py` -- multi-strategy screen
- STRATEGY_VALIDATION.md -- 10 gates that gate "edge" status

## Original spec (kept for reference, NOT current implementation)

The original spec from 2026-06-04 was looser (no cap, `size_bps` instead of
`size_usd`, included NEUTRAL-with-buffer fallback in early drafts). It was
deliberately tightened before deploy per Jazz's framing: *"expected weak or
even beta -- honest data point, not failure. Don't use it as headline edge.
Energy goes to S1."*
