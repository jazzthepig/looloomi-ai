# CIS v4.1 Methodology Specification

> CometCloud Intelligence Score — Unified Index Methodology
> Version 4.1 · 2026-03-23 · Authors: Seth, Austin, Jazz

---

## 1. Purpose

CIS is a multi-pillar composite score for ranking digital and traditional assets.
It serves two consumers with different needs:

- **Institutional investors / LPs**: Transparent, auditable methodology with clear
  data provenance. Need to understand what drives each score and how confident
  the system is in its assessment.
- **Trading agents (Freqtrade, API consumers)**: Stable, continuous signals with
  liquidity awareness. Need machine-readable scores that translate directly into
  position sizing and entry/exit decisions.

This document defines the unified methodology that both scoring engines
(Mac Mini Tier 1 and Railway Tier 2) must follow.

---

## 2. Architecture: Two Engines, One Methodology

### 2.1 Data Tiers

| | Tier 1 (Full) | Tier 2 (Market) |
|---|---|---|
| **Engine** | Mac Mini (`cis_v4_engine.py`) | Railway (`cis_provider.py`) |
| **Price data** | Binance/OKX klines (1h, 30d+) | CoinGecko spot + 24h/7d/30d % |
| **On-chain** | DeFiLlama TVL (real-time) | DeFiLlama TVL (cached 30min) |
| **Macro** | Fed funds, VIX, DXY, TNX | VIX, FNG |
| **Regime** | 6-regime detection (RISK_ON, RISK_OFF, TIGHTENING, EASING, STAGFLATION, GOLDILOCKS) | Binary (Risk-On / Risk-Off) |
| **Risk metrics** | Sharpe, Sortino, rolling beta, max drawdown | ATH distance proxy, vol estimate |
| **Universe** | 40+ assets, 8 classes | 14-25 assets, curated leaders |
| **Update freq** | ~30min push to Railway | On-demand (60s frontend refresh) |

### 2.2 Score Composition

Both engines produce the same output schema:

```
{
  "cis_score": float,       // 0-100, weighted composite
  "grade": str,             // A+ through F (unified absolute thresholds)
  "signal": str,            // STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT
  "data_tier": int,         // 1 or 2
  "confidence": float,      // 0.0-1.0
  "las": float,             // Liquidity-Adjusted Score (0-100)
  "pillars": { F, M, O, S, A },
  "breakdown": { ... }
}
```

### 2.3 Frontend Display

- Tier 1: `CIS 72.3 · A · T1` — green badge "FULL ENGINE"
- Tier 2: `CIS 68.1 · B+ · T2` — amber badge "MARKET EST."
- When both tiers available, T1 takes precedence
- Confidence < 0.5 → show warning icon, tooltip: "Limited data — score is estimated"

---

## 3. Pillar Scoring (0-100 each)

### 3.1 Design Principles

1. **Continuous functions over discrete tiers** — Every pillar uses log-scale or
   linear interpolation to produce continuous scores. No more step functions that
   assign identical scores to assets with 2x differences in fundamentals.

2. **Per-asset differentiation** — Each pillar must produce meaningful variance
   across the scored universe. If a pillar returns the same ±3 points for all
   assets, it's not measuring anything useful.

3. **Degradation-aware** — When a data source is missing, the pillar returns a
   score with reduced range (compressed toward 50) rather than fabricating data
   or returning 0. The confidence field reflects this.

### 3.2 F — Fundamental (Structural Quality)

Measures the asset's structural health: how capitalized, how liquid relative to
its valuation, how fair its token economics.

**Components:**

| Component | Formula | Range | Weight |
|---|---|---|---|
| Market Cap Scale | `min(50, 10 × log₁₀(mcap / 1M))` | 0-50 | — |
| TVL Depth (DeFi/L2) | `min(20, 5 × log₁₀(tvl / 1M))` | 0-20 | — |
| FDV Fairness | `max(0, 15 × (1 - fdv/mcap) / 4)` | 0-15 | — |
| Supply Health | `15 × (circ / total)` | 0-15 | — |
| **Max possible** | | **100** | |

Notes:
- Market Cap Scale: $10M→10, $100M→20, $1B→30, $10B→40, $100B→50. Continuous.
- TVL Depth only applies to DeFi/L2. For other classes, the 20 points redistribute
  to Market Cap Scale (cap becomes 70) so the pillar max stays 100.
- FDV Fairness: ratio=1 (fair launch) → 15 pts. ratio=5 → 0 pts. Linearly interpolated.
- Supply Health: 100% circulating → 15 pts. 50% → 7.5 pts. Continuous.

### 3.3 M — Momentum (Market Activity)

Measures current trading interest and liquidity depth.

**Components:**

| Component | Formula | Range |
|---|---|---|
| Volume Scale | `min(40, 8 × log₁₀(vol_24h / 100K))` | 0-40 |
| Liquidity Ratio | `min(25, vol_24h / mcap × 200)` capped | 0-25 |
| Price Momentum 30d | Linear map: -50%→0, 0%→15, +50%→30, +100%→35 | 0-35 |
| **Max possible** | | **100** |

Notes:
- Volume Scale: $100K→0, $1M→8, $10M→16, $100M→24, $1B→32, $10B→40. Continuous.
- Liquidity Ratio: vol/mcap of 0.05 (5%) → 10 pts, 0.125 → 25 pts (cap).
  Below 0.01 (1%) → penalty: score = max(0, ratio × 1000 - 5).
- Price Momentum: linear interpolation, not step function. Negative momentum
  produces sub-15 scores (not just 0), allowing proper differentiation in bear markets.

### 3.4 O — On-Chain Health / Risk-Adjusted

Measures resilience and risk-adjusted quality.

**Tier 1 (Mac Mini — full data):**

| Component | Formula | Range |
|---|---|---|
| Sharpe Ratio (30d) | `min(35, max(0, sharpe × 15 + 15))` | 0-35 |
| Max Drawdown (90d) | `max(0, 35 × (1 - mdd / 80))` | 0-35 |
| TVL Stability (DeFi) | TVL 7d change: <-20%→0, stable→20, growth→30 | 0-30 |
| **Max possible** | | **100** |

**Tier 2 (Railway — limited data):**

| Component | Formula | Range |
|---|---|---|
| ATH Recovery | `min(35, max(0, 35 × (1 - ath_dist / 80)))` | 0-35 |
| Drawdown Estimate | From 24h high/low range, annualized: `35 × (1 - ann_vol / 200)` | 0-35 |
| Supply + TVL Health | Same as F pillar supply score + TVL if available | 0-30 |
| **Max possible** | | **100** |

Notes:
- Tier 2 O pillar has inherently less precision. Confidence penalty: T2 O-pillar
  confidence = 0.6 (vs T1 = 1.0).
- ATH Recovery is continuous: -80% from ATH → 0 pts, at ATH → 35 pts.

### 3.5 S — Sentiment (Market Psychology + Asset-Specific Signal)

Measures market-wide sentiment baseline + per-asset divergence from that baseline.

**Architecture:**

```
S = baseline(market_wide) + divergence(asset_specific) + volatility_regime
```

**Baseline (0-40):**
- Crypto: `FNG × 0.4` → FNG=25 (fear) → 10pts, FNG=75 (greed) → 30pts
- TradFi: VIX inverse map → VIX=12 → 38pts, VIX=20 → 24pts, VIX=30 → 8pts

**Divergence (asset-specific, -20 to +40):**
- 30d price momentum vs category median:
  `divergence = asset_change_30d - median(category_change_30d)`
  Score: `min(25, max(-15, divergence × 0.5))`
- 24h momentum burst: `min(10, max(-5, change_24h × 0.5))`
- Dev activity (if available): active → +5, dead → -8

**Volatility Regime Modifier (-10 to +20):**
- Realized vol (7d) vs 30d avg: elevated vol + positive momentum → +15 (breakout signal)
- Elevated vol + negative momentum → -10 (capitulation signal)
- Low vol + positive momentum → +10 (accumulation signal)
- Low vol + negative momentum → -5 (stagnation signal)

This design ensures two crypto assets with the same FNG baseline get different
S scores based on their individual momentum, volatility character, and dev activity.

**Max possible: 100** (baseline 40 + divergence 40 + vol regime 20)

### 3.6 A — Alpha Independence

Measures how much the asset moves independently of its primary benchmark.

**Components:**

| Component | Formula | Range |
|---|---|---|
| Benchmark Divergence | 30d return difference vs benchmark | -20 to +40 |
| Class Independence | Category premium (DeFi/RWA > L1 > Meme) | 0-20 |
| Size Efficiency | Smaller cap with strong score → more alpha | -5 to +20 |
| Correlation Discount | High beta to BTC/SPY → penalty | -15 to 0 |
| **Max possible** | | **100** (practical max ~80) |

**Benchmarks:**
- Crypto (non-BTC): benchmark = BTC 30d return
- BTC: benchmark = SPY 30d return (cross-asset alpha)
- US Equity: benchmark = SPY
- US Bond: benchmark = -SPY (inverted — bond alpha = equity weakness)
- Commodity: benchmark = SPY

**Divergence scoring** (continuous):
```python
div = asset_30d - benchmark_30d
score = min(40, max(-20, div * 0.8))  # Linear, continuous
```

---

## 4. Weighting

### 4.1 Base Weights by Asset Class

| Class | F | M | O | S | A |
|---|---|---|---|---|---|
| L1 | 0.30 | 0.25 | 0.20 | 0.15 | 0.10 |
| L2 | 0.30 | 0.25 | 0.20 | 0.15 | 0.10 |
| DeFi | 0.25 | 0.25 | 0.25 | 0.15 | 0.10 |
| RWA | 0.35 | 0.20 | 0.20 | 0.15 | 0.10 |
| Infrastructure | 0.30 | 0.20 | 0.25 | 0.10 | 0.15 |
| Memecoin | 0.15 | 0.35 | 0.15 | 0.25 | 0.10 |
| US Equity | 0.30 | 0.25 | 0.10 | 0.20 | 0.15 |
| US Bond | 0.30 | 0.20 | 0.10 | 0.20 | 0.20 |
| Commodity | 0.25 | 0.25 | 0.10 | 0.20 | 0.20 |

### 4.2 Regime Adjustment (Tier 1 only)

Mac Mini detects macro regime and adjusts weights:

| Regime | Adjustment |
|---|---|
| RISK_ON | M+5%, S+5%, F-5%, O-5% |
| RISK_OFF | O+10%, F+5%, M-10%, A-5% |
| TIGHTENING | F+5%, O+5%, M-5%, S-5% |
| EASING | M+5%, A+5%, F-5%, O-5% |
| STAGFLATION | O+10%, F+5%, M-5%, S-5%, A-5% |
| GOLDILOCKS | Even +2% across all |

Tier 2 does NOT apply regime adjustments — it uses base weights only.
This is a feature, not a bug: it keeps T2 scores stable and predictable.

---

## 5. Grading — Unified Absolute Thresholds

Both engines use identical thresholds:

| Grade | Threshold | Signal | Interpretation |
|---|---|---|---|
| A+ | ≥ 85 | STRONG OUTPERFORM | Exceptional across all pillars |
| A  | ≥ 75 | OUTPERFORM | Strong fundamentals + momentum |
| B+ | ≥ 65 | OUTPERFORM | Above average, positive outlook |
| B  | ≥ 55 | NEUTRAL | Solid but not exceptional |
| C+ | ≥ 45 | NEUTRAL | Mixed signals, watch closely |
| C  | ≥ 35 | UNDERPERFORM | Below average, deteriorating |
| D  | ≥ 25 | UNDERWEIGHT | Significant weakness |
| F  | < 25 | UNDERWEIGHT | Distressed or insufficient data |

> **Compliance note:** CIS signals use positioning language (OUTPERFORM / NEUTRAL /
> UNDERPERFORM / UNDERWEIGHT), not buy/sell language. CometCloud does not hold an
> investment advisory license. Signals are quantitative indicators derived from
> market data, not investment recommendations.

**Key design decisions:**

1. **No percentile override.** Grades reflect absolute quality, not relative rank.
   If all 14 assets score 55-70 in a low-vol market, they're all B/B+ — that IS
   the correct assessment. The clustering tells investors the market is range-bound.

2. **Percentile rank is metadata only.** Still computed, exposed as `percentile_rank`
   in the API for agents that want relative positioning, but it does NOT override
   the grade.

3. **Thresholds aligned.** Previous mismatch (Railway A+=85, Mac Mini A+=90) is
   eliminated. Both use these thresholds. Mac Mini's wider score distribution means
   it naturally produces more A+ grades — this is correct because it has more data
   to justify extreme ratings.

---

## 6. Liquidity-Adjusted Score (LAS)

### 6.1 Purpose

Raw CIS answers "how good is this asset?" LAS answers "how actionable is this
asset for a portfolio of size X?"

Trading agents should use LAS as their primary signal for position sizing.
Institutional investors use CIS for due diligence and LAS for execution planning.

### 6.2 Formula

```
LAS = CIS_score × liquidity_multiplier × confidence

liquidity_multiplier = min(1.0, daily_tradeable / target_position)
daily_tradeable = volume_24h × participation_rate
participation_rate = 0.10  (assume 10% of daily volume is our max participation)
target_position = AUM × max_single_position_pct
```

Default parameters:
- `AUM = 30_000_000` ($30M target fund size)
- `max_single_position_pct = 0.05` (5% max per asset = $1.5M)
- `participation_rate = 0.10`

So for a $30M fund:
- target_position = $1.5M
- Asset with $15M daily volume: tradeable = $1.5M → multiplier = 1.0 (fully liquid)
- Asset with $5M daily volume: tradeable = $500K → multiplier = 0.33 (illiquid penalty)
- Asset with $500M daily volume: tradeable = $50M → multiplier = 1.0 (capped)

### 6.3 Spread Penalty

If 24h high/low range > 5%, additional penalty:
```
spread_penalty = max(0.8, 1.0 - (high_low_range - 0.05) × 2)
LAS = LAS × spread_penalty
```

This penalizes assets with wide spreads even if volume looks adequate.

### 6.4 API Exposure

```json
{
  "las": 62.4,
  "las_params": {
    "assumed_aum": 30000000,
    "participation_rate": 0.10,
    "liquidity_multiplier": 0.87,
    "spread_penalty": 1.0,
    "daily_tradeable_usd": 1305000
  }
}
```

Agents can override AUM via query param: `GET /api/v1/cis/universe?aum=10000000`

---

## 7. Confidence Score

### 7.1 Components

| Data Source | Available | Weight |
|---|---|---|
| Price (spot) | Always (CG) | 0.15 |
| Volume 24h | Always (CG) | 0.10 |
| Market Cap | Always (CG) | 0.10 |
| 30d price history | T1 only (klines) | 0.15 |
| TVL (DeFiLlama) | Most DeFi/L2 | 0.15 |
| On-chain metrics | T1 only | 0.15 |
| Sentiment (FNG/VIX) | Usually | 0.10 |
| Dev activity (GitHub) | Partial | 0.10 |

Confidence = sum of available weights.

- Tier 1 typical: 0.85-1.00
- Tier 2 typical: 0.50-0.70
- Tier 2 without TVL: 0.35-0.55

### 7.2 Impact on Display

- confidence ≥ 0.7: Full grade display
- confidence 0.5-0.7: Grade with "~" prefix (e.g., "~B+") + tooltip
- confidence < 0.5: No grade shown, only numerical score + "insufficient data" label

---

## 8. Signal Definitions

| Signal | Trigger | Agent Action |
|---|---|---|
| STRONG OUTPERFORM | Grade A+ | Enter full position (LAS-adjusted) |
| OUTPERFORM | Grade A or B+ | Enter partial position |
| NEUTRAL | Grade B or C+ | Maintain existing, no new entry |
| UNDERPERFORM | Grade C | Scale down 50%, set stop-loss |
| UNDERWEIGHT | Grade D or F | Exit position, no new entry |

**Signal stability rule:** Signal changes require 2 consecutive scoring cycles
at the new level before the signal updates. This prevents noise-driven flipping
for trading agents. Raw score changes are always visible; the signal is debounced.

---

## 9. Implementation Checklist

### Railway (`cis_provider.py`):
- [ ] Replace all discrete tier scoring with continuous log/linear functions
- [ ] Unify grade thresholds to match this spec (A+ ≥ 85 for both engines)
- [ ] Remove `compute_percentile_ranks()` grade override — keep percentile as metadata
- [ ] Add S pillar volatility regime modifier
- [ ] Add S pillar category-median divergence (not just raw momentum)
- [ ] Implement LAS calculation
- [ ] Add `data_tier: 2` to all Railway-scored assets
- [ ] Update confidence scoring to match §7

### Mac Mini (`cis_v4_engine.py`):
- [ ] Align grade thresholds (A+ ≥ 85, currently ≥ 90)
- [ ] Add LAS calculation using same formula
- [ ] Add `data_tier: 1` to output
- [ ] Ensure output schema matches §2.2

### Frontend (`CISLeaderboard.jsx`):
- [ ] Display data tier badge (T1/T2) per asset
- [ ] Show confidence indicator
- [ ] Show LAS alongside CIS score
- [ ] Implement `~` prefix for low-confidence grades

### API:
- [ ] `GET /api/v1/cis/universe?aum=N` — AUM parameter for LAS
- [ ] Include `data_tier`, `confidence`, `las` in response
- [ ] Document in API spec

---

## 10. Why Scores Cluster — And Why That's OK

When CIS scores cluster at B/B+ (55-70), this reflects reality:

1. **Our universe is pre-curated.** We only score category leaders (top 3 by
   on-chain data per category). These ARE good assets. A universe of leaders
   should cluster above-average.

2. **Market regime drives clustering.** In a range-bound market with moderate
   FNG (40-60), the S pillar baseline compresses everyone. In a strong bull
   run with FNG > 75, baseline lifts → scores spread upward. The clustering
   IS the macro signal.

3. **Differentiation comes from pillars, not grades.** Two assets both graded
   B+ might have very different pillar profiles: one strong F + weak A, the
   other weak F + strong A. The breakdown matters more than the composite.

**For investors:** "All B+" means "the market is in a neutral regime and these
leaders are performing as expected." It's the ABSENCE of outlier A+ or D scores
that's informative.

**For agents:** Use LAS, not grade, for position sizing. Use pillar scores for
strategy selection (momentum strategy → weight M pillar; value strategy → weight F).

---

*CometCloud AI · Built for convergence.*
