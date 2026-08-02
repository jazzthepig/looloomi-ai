# 3-Sleeve Parallel Paper Book — 60d Forward Phase

**Status (2026-07-28):** PROTOTYPE LIVE. Daily paper-trade positions logged for
all 3 sleeves; 60-day forward paper phase just started.

**Why this exists:** per user direction 2026-07-28 ("隔壁gpt sol5.6已经开发了
很多生产环境能赚钱的策略了，你能不能好好看看顶级量化出了front-running和
费率还在做什么？风格周期预判那么难嘛？我们可以容错的，你倒是好好做啊"),
the prior 15-attempt R-numbered sleeve graveyard was structurally
single-family (cross-sectional single-leg factor L/S) — same alpha source
under different demean. This package is a directional pivot: 3 production-
grade alpha sources that top quant funds actually deploy, none of which
require the 1.96 3-check gauntlet to be useful.

## 3 sleeves (each independent, all parallel, all paper-only)

| Sleeve | Alpha source | Signal | Action | File |
|---|---|---|---|---|
| **sleeve_1** | Vol carry (sell IV > RV) | term_premium = Deribit DVOL 30d − BTC 30d RV | Sell ATM straddle + long OTM 1.5x put tail hedge when term_premium > 5% | `sleeve_1_vol_carry.py` |
| **sleeve_2** | Regime nowcast + tilt (NOT static rotation) | P(RISK_ON) = logistic(BTC 30d ret, TVL 7d Δ, USDT 7d Δ) | Tilt R77 gross × ∈ {0.5, 1.0, 1.5} based on probability bands | `sleeve_2_regime_nowcast.py` |
| **sleeve_3** | Cross-asset macro overlay | 7-asset cross-section 30d+90d momentum z | Long top half / short bottom half, $400k notional | `sleeve_3_macro_overlay.py` |

## What's NOT in this package

- **No 3-check gauntlet** (gross_t > 1.96, maxDD > -20%, ≥6/7 cycles,
  M-WO-1 majority-positive) — per user "我们可以容错的"
- **No R-numbered ledger entries** — these are forward-paper candidates,
  not backtest experiments
- **No mock data** — every input is real public data (Deribit DVOL,
  Binance BTC klines, DeFiLlama TVL, EODHD macro); on failure the sleeve
  logs FLAT and skips the day

## Files

```
src/research/paper_books/
  ledger.py                          # shared append-only position log (CSV)
  sleeve_1_vol_carry.py              # Deribit DVOL + Binance RV
  sleeve_2_regime_nowcast.py         # BTC + DeFiLlama + USDT → P(RISK_ON)
  sleeve_3_macro_overlay.py          # EODHD 7-asset cross-section
  daily_runner.py                    # orchestrate all 3 + write daily_summary
  weekly_summary.py                  # 60d signal-trajectory aggregation + R77 baseline (optional)
```

## Output

```
/tmp/cometcloud_data/paper_books/
  vol_carry_positions.csv            # 2 rows/day (straddle + tail hedge)
  regime_nowcast_positions.csv       # 1 row/day (tilt multiplier)
  macro_overlay_positions.csv        # 7 rows/day (4 long + 3 short)
  daily_summary.csv                  # 1 row/day, joined signal values
```

## 60-day decision rule

After 60 days, the 3 sleeves are compared on:
1. Sharpe (annualized) — primary
2. maxDD — secondary
3. Orthogonality to R77 (lowest |ρ(daily_returns, R77 NAV)| wins)
4. Implementation complexity / cost (tail risk + infra cost)

The winner becomes the live Strategy 2 candidate; losers are honest
graveyard. R77 baseline is the reference (frozen cell unchanged).

**Important honest-scope note:** `weekly_summary.py` operates on SIGNAL
TRAJECTORIES (term_premium, P(RISK_ON), long-short imbalance), NOT on
mark-to-market P&L. The 60-day Sharpe/maxDD verdict requires a daily NAV
ledger (next-phase work — out of scope for the prototype). What this
module gives you today: a transparent signal-correlation dashboard and
a countdown to the verdict window.

## Daily operation

```bash
# Run all 3 sleeves + write daily summary
python3 src/research/paper_books/daily_runner.py

# Run a single sleeve in isolation (for debugging)
python3 src/research/paper_books/sleeve_1_vol_carry.py
python3 src/research/paper_books/sleeve_2_regime_nowcast.py
python3 src/research/paper_books/sleeve_3_macro_overlay.py

# Weekly aggregation (signal trajectories + R77 orthogonal comparison)
python3 src/research/paper_books/weekly_summary.py

# Set R77 baseline NAV orthogonal comparison (optional):
export SUPABASE_URL=https://xxx.supabase.co
export SUPABASE_KEY=xxx
```

## Mac-side cron (Jazz / Minimax to wire)

Suggested: 1x daily at 00:30 UTC (after most exchanges settle) for 60 days.
Failure-isolated — one sleeve's failure does not block the others.

## Honest limitations (anti-imposter)

- **Logistic coefficients in sleeve_2 are pre-registered heuristics, not fit
  on data.** A negative 60d verdict is fine — the sleeve's job is to test
  the structural hypothesis, not to clear any backtest bar.
- **Sleeve_1 sells vol with limited tail hedge** — the 30% tail-hedge
  notional may be insufficient for a true regime shift (a 50% BTC drop
  will still lose > the hedge value). A real production sleeve needs
  dynamic tail sizing on the realized-vol path, not a fixed ratio.
- **Sleeve_3 macro overlay is cross-section only** — no USD-neutrality
  hedge, no carry adjustment. The 7 assets are USD-denominated
  (EODHD .US tickers), so the sleeve has a residual USD bias.
- **Daily NAV mark is the prior mark + sleeve-specific return proxy.**
  No live mark-to-market against real fills (this is paper).

## Compliance

All 3 sleeves use positioning language only — no BUY/SELL/ACCUMULATE/AVOID.
The paper book is internal Seth-side research; no investor-facing surface
exposes it.
