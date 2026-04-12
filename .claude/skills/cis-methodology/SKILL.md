---
name: cis-methodology
description: CometCloud Intelligence Score (CIS) v4.1 domain knowledge. Use whenever generating, editing, debugging, or reviewing CIS-related code — scoring engines (cis_provider.py, cis_v4_engine.py), API endpoints (routers/cis.py, routers/market.py), frontend components (CISLeaderboard.jsx, ScoreAnalytics.jsx, AssetRadar.jsx), signal feed entries, macro briefs, backtest logic, agent JSON, methodology docs, or investor-facing explanations of how CIS works. This skill is loaded whenever a task touches any of: pillar scoring (F/M/O/S/A), grading thresholds, LAS calculation, confidence scoring, data tiers (T1/T2), regime detection, signal definitions, or the Mac Mini ↔ Railway score bridge. If you're not sure whether CIS knowledge is needed, it probably is — load the skill.
---

# CIS v4.1 — Scoring Engine Domain Knowledge

## What CIS is

CIS (CometCloud Intelligence Score) is a 5-pillar composite score (0–100) for
ranking digital and traditional assets. It is the core intellectual property of
CometCloud AI. Every product surface — leaderboard, signal feed, trading agent,
macro brief, vault strategy — flows from CIS.

Two audiences consume CIS differently:

- **Institutional investors / LPs**: Transparent, auditable methodology.
  They care about what drives a score and whether they can trust it.
- **Trading agents (Freqtrade, API consumers)**: Stable, continuous signals
  with liquidity awareness. They care about LAS and pillar breakdowns for
  strategy selection.

The full specification lives in `CIS_METHODOLOGY.md` (repo root, 446 lines).
Load `references/quick_reference.md` for a condensed cheat sheet.

## Architecture: Two engines, one methodology

```
Mac Mini (Tier 1)                   Railway (Tier 2)
─────────────────                   ─────────────────
cis_v4_engine.py                    cis_provider.py
Binance/OKX klines                  CoinGecko spot + %
DeFiLlama TVL (live)                DeFiLlama TVL (30min cache)
VIX, DXY, TNX, Fed                  VIX, FNG
Sharpe, Sortino, beta, MDD          ATH proxy, vol estimate
6-regime detection                  Binary Risk-On/Off
40+ assets, 8 classes               14-25 curated leaders
Pushes every ~30min → Redis         Fallback if Redis stale
                    ↘               ↗
                   Upstash Redis (2h TTL)
                         ↓
              GET /api/v1/cis/universe
                         ↓
              CISLeaderboard.jsx
```

T1 always wins when available. T2 is a real scoring engine, not a placeholder.

## The 5 pillars (memorize these)

| Pillar | Name | Measures | Key inputs |
|---|---|---|---|
| **F** | Fundamental | Structural quality | mcap, TVL, FDV/mcap, circ/total supply |
| **M** | Momentum | Trading interest | vol_24h, vol/mcap ratio, 30d price change |
| **O** | On-Chain/Risk | Resilience | Sharpe, MDD (T1); ATH recovery, vol (T2) |
| **S** | Sentiment | Psychology + divergence | FNG/VIX baseline + asset-specific momentum |
| **A** | Alpha | Independence | Return vs BTC/SPY benchmark, category premium |

All pillars score 0–100 using continuous functions (log/linear). No step
functions. The continuous design means every asset gets a genuinely unique
pillar score — if two assets have materially different fundamentals, their F
scores will differ.

## Scoring math rules

When writing or debugging scoring code:

1. **Use `_log_score()` for exponential distributions** (market cap, volume, TVL).
   Pattern: `min(cap, multiplier × log₁₀(value / floor))`. This compresses the
   10x–100x differences into meaningful score ranges.

2. **Use `_linear_interp()` for bounded ratios** (FDV/mcap, vol/mcap, momentum).
   Pattern: linear map from input range → score range with clamping.

3. **Never hardcode tier breakpoints.** If you see `if mcap > 10e9: score = 40`
   that is v4.0 code and must be replaced with a continuous log function.

4. **Degrade gracefully.** Missing data → compress score toward 50, reduce
   confidence. Never return 0 or 100 for missing data. Never fabricate inputs.

5. **Pillar max = 100 always.** If components don't sum to 100 when a data
   source is unavailable, redistribute the missing weight to remaining components.

## Grading — unified absolute thresholds

Both engines MUST use these identical thresholds:

| Grade | Score | Signal |
|---|---|---|
| A+ | ≥ 85 | STRONG OUTPERFORM |
| A  | ≥ 75 | OUTPERFORM |
| B+ | ≥ 65 | OUTPERFORM |
| B  | ≥ 55 | NEUTRAL |
| C+ | ≥ 45 | NEUTRAL |
| C  | ≥ 35 | UNDERPERFORM |
| D  | ≥ 25 | UNDERWEIGHT |
| F  | < 25 | UNDERWEIGHT |

**Critical:** Percentile rank is metadata only. It does NOT override grade.
If all 14 assets score 55–70, they are all B/B+ — that is correct, and it
tells investors the market is range-bound.

**Compliance:** Signals MUST use positioning language only. See the
`compliance-language` skill. Never `BUY`/`SELL`/`HOLD`/`AVOID`/`REDUCE`.

## LAS (Liquidity-Adjusted Score)

```
LAS = CIS × liquidity_multiplier × confidence
liquidity_multiplier = min(1.0, daily_tradeable / target_position)
daily_tradeable = volume_24h × 0.10 (10% participation rate)
target_position = AUM × 0.05 ($1.5M for $30M fund)
```

Spread penalty if 24h high/low range > 5%:
```
spread_penalty = max(0.8, 1.0 - (range - 0.05) × 2)
```

Agents use LAS for position sizing. CIS is due diligence; LAS is execution.

## Confidence scoring

| Data source | Weight | Availability |
|---|---|---|
| Price (spot) | 0.15 | Always (CG) |
| Volume 24h | 0.10 | Always (CG) |
| Market cap | 0.10 | Always (CG) |
| 30d price history | 0.15 | T1 only |
| TVL (DeFiLlama) | 0.15 | Most DeFi/L2 |
| On-chain metrics | 0.15 | T1 only |
| FNG / VIX | 0.10 | Usually |
| Dev activity | 0.10 | Partial |

T1 typical: 0.85–1.00. T2 typical: 0.50–0.70.

Display rules: ≥0.7 full grade, 0.5–0.7 `~B+` with tooltip, <0.5 no grade.

## Weighting by asset class

| Class | F | M | O | S | A |
|---|---|---|---|---|---|
| L1 | .30 | .25 | .20 | .15 | .10 |
| L2 | .30 | .25 | .20 | .15 | .10 |
| DeFi | .25 | .25 | .25 | .15 | .10 |
| RWA | .35 | .20 | .20 | .15 | .10 |
| Infra | .30 | .20 | .25 | .10 | .15 |
| Meme | .15 | .35 | .15 | .25 | .10 |
| US Equity | .30 | .25 | .10 | .20 | .15 |
| US Bond | .30 | .20 | .10 | .20 | .20 |
| Commodity | .25 | .25 | .10 | .20 | .20 |

T1 applies regime adjustments (RISK_ON: M+5% S+5% F-5% O-5%, etc).
T2 uses base weights only — this keeps T2 scores stable and predictable.

## Regime detection (T1 only)

6 regimes: RISK_ON, RISK_OFF, TIGHTENING, EASING, STAGFLATION, GOLDILOCKS.
Detected from Fed funds, VIX, DXY, TNX inputs. Adjusts pillar weights per the
table in `CIS_METHODOLOGY.md` §4.2.

When working with regime data:
- Mac Mini pushes `macro_regime` to Redis alongside scores
- Railway forwards it in `/api/v1/cis/universe` response
- Frontend shows regime badge in MacroPulse widget
- Signal Feed uses regime in context generation

## S pillar architecture (most complex pillar)

```
S = baseline + divergence + volatility_regime

baseline:   crypto → FNG × 0.4   |   TradFi → VIX inverse
divergence: asset 30d change vs category median (per-asset differentiation)
vol regime: breakout/capitulation/accumulation/stagnation modifier
```

This is the pillar most likely to have bugs. When debugging:
- Verify the baseline source is correct for the asset class
- Check that category median is computed per-class, not global
- Verify vol regime modifier sign (+breakout, -capitulation)

## A pillar benchmarks

| Asset class | Benchmark | Notes |
|---|---|---|
| Crypto (non-BTC) | BTC 30d return | Standard crypto alpha |
| BTC | SPY 30d return | Cross-asset alpha |
| US Equity | SPY 30d return | Standard equity alpha |
| US Bond | -SPY 30d return | Inverted — bond alpha = equity weakness |
| Commodity | SPY 30d return | Real asset independence |

## Common debugging patterns

**"All scores are the same (±3 points)"**
- Likely a step-function remnant from v4.0. Check for `if/elif` scoring.
- Or: S pillar baseline is dominating because divergence is zero.

**"Score is NaN or null"**
- A pillar returned NaN from a log(0) or division by zero.
- Add guards: `mcap = max(mcap, 1)` before `log10(mcap)`.

**"T1 and T2 disagree by 20+ points for the same asset"**
- Expected if the asset has poor CG spot data but rich kline data.
- Check confidence values — T2 should be lower.

**"All scores dropped 10+ points suddenly"**
- FNG/VIX data source went stale → S baseline collapsed.
- Check `get_fear_greed()` in data_layer.py for cache miss.

**"LAS is 0 for a scored asset"**
- Volume is missing or zero → liquidity_multiplier = 0.
- Check CoinGecko response for that asset's `total_volume`.

## File map

| File | Purpose | Owner |
|---|---|---|
| `CIS_METHODOLOGY.md` | Canonical spec (investor-grade) | Seth/Jazz |
| `src/data/cis/cis_provider.py` | Railway T2 scoring engine | Seth |
| `src/api/routers/cis.py` | CIS API endpoints | Seth |
| `Shadow/cometcloud-local/cis_v4_engine.py` | Mac Mini T1 engine (read-only) | Minimax |
| `Shadow/cometcloud-local/cis_push.py` | Score push to Railway (read-only) | Minimax |
| `dashboard/src/components/CISLeaderboard.jsx` | Main leaderboard UI | Seth |
| `dashboard/src/components/ScoreAnalytics.jsx` | Grade migration, sector rotation | Seth |
| `dashboard/src/components/AssetRadar.jsx` | Asset detail cards with LAS | Seth |
| `MINIMAX_SYNC.md` | Mac Mini ↔ Railway interface contract | Seth/Minimax |

## References

- `references/quick_reference.md` — one-page cheat sheet with all formulas
- `CIS_METHODOLOGY.md` (repo root) — full specification (446 lines)
- `.claude/skills/compliance-language/SKILL.md` — signal language rules
