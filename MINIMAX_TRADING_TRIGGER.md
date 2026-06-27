# Auto Paper Trading Trigger — Live Track Record

**Status:** ✅ Complete (2026-06-26)
**Deployed in:** `src/api/routers/trading.py` + `src/api/main.py` (commit on Railway after this doc lands)
**Spec:** This file is the canonical spec. The trigger code in `cis_scheduler.py` (Mac Mini hourly cron) + Railway background loops (`_sl_tp_loop`, `_cis_flip_exit_loop`, `_age_sweep_loop`) implement it.

---

## What this trigger measures

**Daily-frequency long-only CIS-gated strategy, fully closed-loop.**

That is the whole thing. It is a position-tilt strategy that:
- Opens a small LONG when fresh CIS pushes a name to OUTPERFORM/STRONG OUTPERFORM past the regime threshold
- Closes when **any** of: SL/TP breach, CIS flips bearish, age >7d with PnL in band, or manual DELETE

Every close writes to Supabase `trade_results` — same schema as Freqtrade fills — so Simons IC regression + L1 metric in MINIMAX_SYNC.md both work on the combined stream.

## What this trigger is NOT

- **NOT the headline edge.** Expected profile is **weak, possibly beta-like**.
- **NOT comparable to S1.** S1 is the 4h long-short proper walk-forward backtest. That is where real alpha lives (per STRATEGY_VALIDATION.md gate 3).
- **NOT a benchmark for fund performance.** A weak return here is an honest data point, not a failure. It validates the *infrastructure* (orders flow, positions tracked, P&L computed, track record populates) more than it validates the *strategy*.

---

## How it works (full lifecycle)

### Entry path (Mac Mini hourly cron)

`cis_scheduler.py` `run_cis_job()` → `# ── Auto paper trading ──` block.

```python
REGIME_THRESHOLD = {
    "TIGHTENING": 52, "RISK_OFF": 55, "EASING": 48,
    "RISK_ON": 48, "STAGFLATION": 58, "GOLDILOCKS": 46,
}
MAX_NEW_PER_CYCLE = 2

# Gate: OUTPERFORM or STRONG OUTPERFORM only.
# Size: conviction_bps = scale with score above threshold; T2 discount 60%.
# Dedup against already-open positions fetched from Railway.
```

POST `https://looloomi.ai/api/v1/trading/order` with `{symbol, side: "LONG", size_usd, strategy: "CIS_AUTO_{regime}", reason, time_horizon: "7D"}`.

### Exit paths (5 paths, all flow through `close_position`)

| Path | Cadence | Trigger | `exit_reason` | Added |
|------|---------|---------|---------------|-------|
| Stop-loss breach | 5 min | LONG: price ≤ SL; SHORT: price ≥ SL | `sl_triggered` | 2026-06-26 |
| Take-profit breach | 5 min | LONG: price ≥ TP; SHORT: price ≤ TP | `tp_triggered` | 2026-06-26 |
| CIS-flip | 5 min | latest cis_scores signal ∈ {UNDERPERFORM, UNDERWEIGHT} **or** score < 45 | `cis_flip_exit` / `cis_flip_exit_score` | 2026-06-26 |
| Aged-sweep | 24 h | position >7d old AND \|PnL\| ≤ 10% | `sweep_aged_position` | 2026-06-04 (band 5%→10% on 2026-06-26) |
| Manual | on-demand | `DELETE /api/v1/trading/positions/{id}` | `manual` | 2026-06-04 |

All paths funnel through `close_position()` (trading.py:649) which:
1. Fetches current price, computes realized P&L
2. Persists updated position dict
3. Returns cash to paper balance
4. Telegram alert (fire-and-forget)
5. **Writes to Supabase `trade_results`** (fire-and-forget, 2026-06-26)
6. Triggers Simons IC auto-mine after every 5th close

### Close-to-track-record flow

```
position breached SL/TP (or CIS flip / aged sweep / manual)
  ↓
close_position(order_id, reason="sl_triggered"|"tp_triggered"|"cis_flip_exit"|"sweep_aged_position"|"manual")
  ↓
persists positions[order_id] with status="closed" + realized_pnl + realized_pct + exit_reason + closed_at
  ↓
_write_closed_trade_to_supabase(pos) → supabase_insert_table("trade_results", [_paper_position_to_row(pos)])
  ↓
trade_results table gains a row → Simons IC regression picks it up on next run
```

The Supabase write is **best-effort fire-and-forget**: failure logs `[TRADE_RESULTS] write failed for {symbol}` but does not block close. Positions dict (Redis) is the source of truth; `trade_results` is the denormalized analytics mirror.

---

## Why we kept it conservative

We could loosen the gate (NEUTRAL with CIS buffer, larger cap, more asset classes) to inflate trade count. We deliberately did not:

1. **Cap = 2 orders/cycle.** Hourly cron × 2 = 48 worst-case/day, but steady-state is ~10-15 new positions/day because most cycles have 0-2 qualifying names. This keeps the record legible as a fund-style tilt, not a bot.

2. **Strict gate.** Only `OUTPERFORM` and `STRONG OUTPERFORM` fire. No `NEUTRAL + CIS buffer` fallbacks. A faithful null hypothesis is more valuable for walk-forward comparison than a noisy inflated record.

3. **Dedup against open positions.** Skips symbols already held. Prevents re-adding on every cycle.

4. **Tightened SL/TP (2% / 4%) as of 2026-06-19.** Combined with the SL/TP loop every 5min, losers exit before they bleed. Winners ride until TP or CIS flip.

5. **CIS-flip exit is a soft stop.** A position whose CIS drops to UNDERPERFORM is closed even if SL hasn't triggered — protects against thesis decay before price catches up.

---

## Where to find it in code

| Component | File | Lines |
|-----------|------|-------|
| Entry trigger | `cis_scheduler.py` | 769-894 |
| Position store | `src/api/routers/trading.py` | `_get_positions` / `_save_positions` (Redis-backed) |
| Close (all paths funnel here) | `src/api/routers/trading.py` | `close_position` ~649 |
| Supabase write | `src/api/routers/trading.py` | `_write_closed_trade_to_supabase` ~757 |
| SL/TP auto-execution | `src/api/routers/trading.py` | `_sl_tp_exit` |
| CIS-flip exit | `src/api/routers/trading.py` | `_cis_flip_exit` |
| Aged-sweep | `src/api/routers/trading.py` | `sweep_aged_positions` |
| SL/TP loop (5 min) | `src/api/main.py` | `_sl_tp_loop` |
| CIS-flip loop (5 min) | `src/api/main.py` | `_cis_flip_loop` |
| Aged-sweep loop (24 h) | `src/api/main.py` | `_age_sweep_loop` |

Manual triggers (for testing):
- `POST /internal/sl-tp-exit` (auth: X-Internal-Token)
- `POST /internal/cis-flip-exit` (auth: X-Internal-Token)
- `POST /internal/sweep-aged-positions` (auth: X-Internal-Token)

Disable flags (env):
- `DISABLE_SL_TP_LOOP=1` — skip the 5-min SL/TP loop
- `DISABLE_CIS_FLIP_LOOP=1` — skip the 5-min CIS-flip loop
- `DISABLE_AGE_SWEEP=1` — skip the 24-h aged sweep (existing)

---

## Verify it's running

```bash
# Tail scheduler log for entry triggers
tail -f /Volumes/CometCloudAI/cometcloud-local/_logs/cis_scheduler.log | grep TRADING

# Tail Railway logs for exit loops (via Railway dashboard or `railway logs`)
# Look for:
#   [SL/TP] closed=N sl=N tp=N scanned=N
#   [CIS-FLIP] closed=N by_signal=N by_score=N
#   [SWEEP] daily — swept=N (SYM1, SYM2) skipped=N total_open=N
#   [TRADE_RESULTS] wrote SYM reason profit_pct=±N.NN%

# Check open positions
curl -s https://looloomi.ai/api/v1/trading/positions | jq '.count, [.positions[].symbol]'

# Check trade_results row count
psql $SUPABASE_URL -c "SELECT count(*), max(exit_time) FROM trade_results WHERE strategy LIKE 'CIS_AUTO%';"
```

Healthy state: open positions fluctuate 3-8, `trade_results` grows daily, exit_reasons distributed across `sl_triggered` / `tp_triggered` / `cis_flip_exit` / `sweep_aged_position` / `manual`.

---

## Where to push next (energy allocation)

**S1 — 4h long-short proper walk-forward backtest.** This is the real alpha candidate. Use STRATEGY_VALIDATION.md gate 3 as the validator. Current freqtrade dry-run has 4 closed trades (per Railway trading/metrics) — not enough for validation gate 1 (≥ 100 closed trades).

Tools available:
- `scripts/run_freqtrade_backtest.py` — wrapper with walk-forward
- `scripts/backtest_strategies.py` — multi-strategy screen
- STRATEGY_VALIDATION.md — 10 gates that gate "edge" status

The paper trigger now provides the **infrastructure validation track record** (positions flow, P&L computed, trade_results populates) — but the alpha must come from S1's 4h LS proper backtest, not from this long-only CIS-gated tilt.

---

## Original spec (kept for reference, NOT current implementation)

The original spec from 2026-06-04 was looser (no cap, `size_bps` instead of `size_usd`, included NEUTRAL-with-buffer fallback in early drafts). It was deliberately tightened before deploy per Jazz's framing: *"expected weak or even beta — honest data point, not failure. Don't use it as headline edge. Energy goes to S1."*

The 2026-06-26 update added the **exit path layer** (SL/TP, CIS-flip, Supabase writes). Before that date, the trigger could open positions but never reliably closed them — track record was effectively null. After 2026-06-26: every open position has at least one of 5 exit paths firing within 5min of breach, every close lands in `trade_results`, L1 metric in MINIMAX_SYNC.md accumulates daily.
