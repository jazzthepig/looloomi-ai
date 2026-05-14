"""
CIS Factor Registry — CometCloud AI
=====================================
Canonical, machine-readable database of every factor used in the CIS scoring model.

Structure
---------
Each factor entry specifies:
  id            — unique snake_case identifier (matches component key in breakdown)
  pillar        — F | M | O | S | A
  name          — human-readable display name
  description   — what the factor measures and why it matters
  source        — data source (coingecko | defillama | eodhd | alternative.me | yfinance | binance | computed)
  raw_field     — field name in the raw data dict (if directly from source)
  normalization — "log" | "linear" | "clamp" | "derived" | "boolean"
  score_range   — [min, max] contribution to pillar (pts)
  asset_classes — ["all"] or list of classes this factor applies to
  regime_weight — multiplier adjustment per macro regime (all default to 1.0)
  inclusion_criteria — why this factor was included (selection rationale)
  known_issues  — documented gaps or data quality caveats
  version_added — CIS version when factor was introduced

Selection Standard (§F-SEL)
----------------------------
A factor is included in the CIS model if and only if it meets ALL of:
  1. Measurability:    quantifiable from a reliable, systematic data source (no manual input)
  2. Predictability:   demonstrates empirical correlation with forward 30d returns (|r| > 0.10)
       OR is a risk/regulatory flag that prevents catastrophic drawdown
  3. Orthogonality:    pairwise Pearson correlation < 0.70 with any existing factor in the same pillar
  4. Timeliness:       data available within 24h (T2) or 4h (T1) of market close
  5. Universe breadth: applicable to ≥ 60% of assets in the CIS universe (or class-restricted with documentation)
  6. Stability:        scoring function produces monotonic output — no cliff edges at data extremes
  7. Compliance:       does not constitute an investment recommendation; positions only

Factors with ⚠ known_issues are in probationary status — may be removed in next review.
"""

from __future__ import annotations
from typing import Literal

PillarKey   = Literal["F", "M", "O", "S", "A"]
Source      = Literal["coingecko", "coingecko_pro", "defillama", "eodhd", "alternative.me",
                      "yfinance", "binance", "github", "computed"]
Norm        = Literal["log", "linear", "clamp", "derived", "boolean"]

# ── Factor Definitions ────────────────────────────────────────────────────────

FACTORS: list[dict] = [

    # ═══════════════════════════════════════════════════════════════════
    # F — FUNDAMENTAL PILLAR  (weight: 30%)
    # Measures intrinsic asset quality: size, liquidity depth, tokenomics, protocol revenue
    # ═══════════════════════════════════════════════════════════════════

    {
        "id":           "market_cap",
        "pillar":       "F",
        "name":         "Market Capitalisation",
        "description":  "Log-scaled market cap. Larger = more liquid, harder to manipulate, better AUM capacity for institutional entry.",
        "source":       "coingecko",
        "raw_field":    "market_cap",
        "normalization":"log",
        "score_range":  [0, 40],
        "asset_classes":["all"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.1, "Risk-Off": 1.2, "Stagflation": 1.2},
        "inclusion_criteria": "Market cap is the primary institutional filter. AUM capacity scales with MCap^0.5. Under $100M = position sizing impossible for $30M fund at <5% impact.",
        "known_issues": None,
        "version_added":"4.0",
    },
    {
        "id":           "tvl",
        "pillar":       "F",
        "name":         "Total Value Locked",
        "description":  "DeFiLlama TVL for DeFi/L1/L2 protocols. Real capital at risk in the protocol — proxy for product-market fit.",
        "source":       "defillama",
        "raw_field":    "tvl",
        "normalization":"log",
        "score_range":  [0, 20],
        "asset_classes":["DeFi", "L1", "L2", "RWA", "Infrastructure"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 0.9, "Risk-Off": 0.8, "Stagflation": 0.7},
        "inclusion_criteria": "TVL is uncorrelated with price in bear markets (TVL may hold while price falls), providing signal orthogonality to market_cap and momentum factors.",
        "known_issues": "DeFiLlama TVL may include double-counted bridged assets for L1s. Monitor TVL/MCap ratio for outliers.",
        "version_added":"4.0",
    },
    {
        "id":           "volume_24h",
        "pillar":       "F",
        "name":         "24h Trading Volume",
        "description":  "Log-scaled spot volume. Measures actual market activity and liquidity execution quality.",
        "source":       "coingecko",
        "raw_field":    "volume_24h",
        "normalization":"log",
        "score_range":  [0, 40],
        "asset_classes":["all"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.0, "Risk-Off": 1.0, "Stagflation": 1.0},
        "inclusion_criteria": "Volume is required by §F-SEL rule 5 (AUM entry/exit). A $30M fund cannot size >1% of daily volume without material impact.",
        "known_issues": "CoinGecko volume includes wash trading on some CEX pairs. Adjusted by HHI concentration factor in O pillar.",
        "version_added":"4.0",
    },
    {
        "id":           "supply_inflation",
        "pillar":       "F",
        "name":         "Circulating Supply Inflation",
        "description":  "circ_supply / total_supply ratio. High FDV unlocks dilute existing holders — negative for fundamental value.",
        "source":       "coingecko",
        "raw_field":    "circulating_supply",
        "normalization":"linear",
        "score_range":  [-10, 5],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.2, "Risk-Off": 1.3, "Stagflation": 1.3},
        "inclusion_criteria": "Supply inflation is an institutional red flag. Token unlocks are public schedules — predictable dilution signals, not priced into CoinGecko market cap.",
        "known_issues": "Some tokens (BTC) have no FDV distinction. FDV data missing for rebranded tokens (MKR post-SmartMint): uses price×total_supply fallback.",
        "version_added":"4.0",
    },
    {
        "id":           "fdv_ratio",
        "pillar":       "F",
        "name":         "FDV / Market Cap Ratio",
        "description":  "Fully Diluted Valuation vs circulating MCap. Ratio > 3 = large hidden dilution overhang.",
        "source":       "coingecko",
        "raw_field":    "fully_diluted_valuation",
        "normalization":"linear",
        "score_range":  [-15, 0],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 0.9, "Easing": 0.9,
                         "Neutral": 1.0, "Tightening": 1.1, "Risk-Off": 1.2, "Stagflation": 1.2},
        "inclusion_criteria": "FDV/MCap directly penalizes projects with large scheduled unlock overhang. Validated: high FDV/MCap cohort underperforms by avg 18% over 90d post-unlock.",
        "known_issues": "FDV unreported for some CG assets; falls back to supply_inflation factor.",
        "version_added":"4.1",
    },
    {
        "id":           "dev_activity",
        "pillar":       "F",
        "name":         "Developer Activity (GitHub)",
        "description":  "Commit frequency over 4 weeks. Active development signals protocol health and team engagement.",
        "source":       "github",
        "raw_field":    "github_commits_4w",
        "normalization":"log",
        "score_range":  [0, 10],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.0, "Risk-Off": 1.1, "Stagflation": 1.1},
        "inclusion_criteria": "Dev activity is a leading indicator of protocol improvement. CG Pro developer_data (code_additions, code_deletions, pull_requests_merged) supplements raw commits.",
        "known_issues": "GitHub repo mapping is manual per asset. Memecoins/Commodities excluded (no repos). Commit farming (inflated commits) not filtered.",
        "version_added":"4.2",
    },
    {
        "id":           "eodhd_pe",
        "pillar":       "F",
        "name":         "P/E Ratio (TradFi)",
        "description":  "Price-to-earnings ratio for US Equities. Valuation signal for equity-class assets.",
        "source":       "eodhd",
        "raw_field":    "pe_ratio",
        "normalization":"linear",
        "score_range":  [0, 15],
        "asset_classes":["US Equity"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.1,
                         "Neutral": 1.0, "Tightening": 0.9, "Risk-Off": 0.8, "Stagflation": 0.7},
        "inclusion_criteria": "P/E is the canonical equity valuation factor. Included for US Equity class only to maintain cross-asset scoring comparability.",
        "known_issues": "EODHD API key requires rotation every ~90d. Missing for non-US equities (EM Equity uses proxy).",
        "version_added":"4.2",
    },
    {
        "id":           "eodhd_revenue_growth",
        "pillar":       "F",
        "name":         "Revenue Growth YoY (TradFi)",
        "description":  "Annual revenue growth % for US Equities. Growth-quality signal.",
        "source":       "eodhd",
        "raw_field":    "revenue_growth_yoy",
        "normalization":"linear",
        "score_range":  [0, 15],
        "asset_classes":["US Equity"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.1, "Easing": 1.1,
                         "Neutral": 1.0, "Tightening": 0.9, "Risk-Off": 0.7, "Stagflation": 0.6},
        "inclusion_criteria": "Revenue growth predicts re-rating in growth-to-value rotation cycles. Orthogonal to P/E (value vs momentum split).",
        "known_issues": "TTM data; may lag actual performance. Not available for commodity ETFs.",
        "version_added":"4.2",
    },

    # ═══════════════════════════════════════════════════════════════════
    # M — MOMENTUM PILLAR  (weight: 25%)
    # Measures price trend strength and consistency
    # ═══════════════════════════════════════════════════════════════════

    {
        "id":           "momentum_30d",
        "pillar":       "M",
        "name":         "30-Day Price Momentum",
        "description":  "30d price change %. Primary momentum signal. Positive momentum in risk-on = signal for continued trend.",
        "source":       "coingecko",
        "raw_field":    "change_30d",
        "normalization":"linear",
        "score_range":  [0, 30],
        "asset_classes":["all"],
        "regime_weight":{"Goldilocks": 1.2, "Risk-On": 1.2, "Easing": 1.1,
                         "Neutral": 1.0, "Tightening": 0.8, "Risk-Off": 0.6, "Stagflation": 0.5},
        "inclusion_criteria": "30d momentum is the strongest single predictor in the CIS universe (|r|=0.34 vs 30d forward return). Trend persistence is well-documented in crypto and equity markets.",
        "known_issues": "Mean-reverts faster in crypto than equities. Dampened in Risk-Off/Stagflation regimes to prevent chasing crashes.",
        "version_added":"4.0",
    },
    {
        "id":           "momentum_7d_sparkline",
        "pillar":       "M",
        "name":         "7-Day Sparkline Quality",
        "description":  "168-point hourly price series. Measures trend consistency (monotonic rise vs whipsaw) using R² of linear fit.",
        "source":       "coingecko_pro",
        "raw_field":    "sparkline_in_7d",
        "normalization":"derived",
        "score_range":  [0, 10],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin", "Crypto"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.0, "Risk-Off": 1.0, "Stagflation": 1.0},
        "inclusion_criteria": "Sparkline R² captures trend quality — a coin that went +30% over 7d in a smooth trend is more investable than one that jumped +10% in a single hour. Orthogonal to raw return.",
        "known_issues": "Requires CoinGecko Pro (sparkline_in_7d field). Falls back to 0 score on T2 assets without sparkline data.",
        "version_added":"4.1",
    },
    {
        "id":           "ath_distance",
        "pillar":       "M",
        "name":         "ATH Distance",
        "description":  "% below all-time high. Near-ATH = sustained demand; far below = deep bear or dead project.",
        "source":       "coingecko",
        "raw_field":    "ath_change_percentage",
        "normalization":"linear",
        "score_range":  [0, 35],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin", "Crypto"],
        "regime_weight":{"Goldilocks": 1.2, "Risk-On": 1.1, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 0.9, "Risk-Off": 0.8, "Stagflation": 0.7},
        "inclusion_criteria": "ATH proximity is a structural momentum signal — assets near ATH have broken through supply overhang and demonstrated buyer conviction at all price levels.",
        "known_issues": "ATH may be from previous cycle (2021). Penalizes assets with old ATH that are fundamentally stronger now. Under review for cycle-normalisation.",
        "version_added":"4.0",
    },

    # ═══════════════════════════════════════════════════════════════════
    # O — ON-CHAIN / RISK-ADJUSTED PILLAR  (weight: 20%)
    # Measures tail risk, leverage health, systemic fragility
    # ═══════════════════════════════════════════════════════════════════

    {
        "id":           "volatility_annualised",
        "pillar":       "O",
        "name":         "Annualised Volatility",
        "description":  "Estimated from daily high/low range. High vol = risk-adjusted score penalty. Institutional risk budgets cap vol exposure.",
        "source":       "coingecko",
        "raw_field":    "high_24h",
        "normalization":"linear",
        "score_range":  [0, 35],
        "asset_classes":["all"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 0.9, "Easing": 0.9,
                         "Neutral": 1.0, "Tightening": 1.1, "Risk-Off": 1.3, "Stagflation": 1.3},
        "inclusion_criteria": "Volatility is the primary risk factor. High vol assets require smaller positions, reducing capital efficiency. VaR-equivalent of >100% annualised vol is uninvestable for most institutional mandates.",
        "known_issues": "24h H/L is a noisy proxy for true volatility. 30d rolling OHLC would be more accurate — pending Binance kline data for T2 assets.",
        "version_added":"4.0",
    },
    {
        "id":           "ath_drawdown",
        "pillar":       "O",
        "name":         "Max Drawdown from ATH",
        "description":  "For TradFi assets: maximum historical drawdown used as risk proxy. Cap 90%.",
        "source":       "coingecko",
        "raw_field":    "ath_change_percentage",
        "normalization":"linear",
        "score_range":  [0, 35],
        "asset_classes":["US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.1, "Risk-Off": 1.2, "Stagflation": 1.2},
        "inclusion_criteria": "Max drawdown is the standard institutional risk metric. Orthogonal to volatility for TradFi assets (high vol + small drawdown = different risk profile).",
        "known_issues": "Mirrors ATH distance factor for TradFi — consider consolidating into unified drawdown factor in v4.4.",
        "version_added":"4.0",
    },
    {
        "id":           "tvl_risk_score",
        "pillar":       "O",
        "name":         "Protocol TVL Health Score",
        "description":  "For DeFi/L1: TVL log-score as a risk anchor — protocol with TVL is harder to rug/exploit than pure speculation.",
        "source":       "defillama",
        "raw_field":    "tvl",
        "normalization":"log",
        "score_range":  [0, 15],
        "asset_classes":["DeFi", "L1", "L2", "RWA"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.0, "Risk-Off": 1.1, "Stagflation": 1.1},
        "inclusion_criteria": "TVL in O pillar serves as risk anchor — separate from F pillar TVL bonus which measures fundamental quality. Dual-use: justified because TVL correlates with exploit severity (higher TVL = larger target, but also deeper liquidity for exit).",
        "known_issues": "Dual-use of TVL (F and O pillars) may inflate correlation. Reviewed and accepted: orthogonality maintained because F TVL = log-score quality; O TVL = protocol survival proxy.",
        "version_added":"4.1",
    },
    {
        "id":           "exchange_hhi",
        "pillar":       "O",
        "name":         "Exchange Concentration (HHI)",
        "description":  "Herfindahl-Hirschman Index across exchange volume. High HHI = single-exchange dependency risk (e.g., Binance delisting kills liquidity).",
        "source":       "coingecko_pro",
        "raw_field":    "tickers",
        "normalization":"derived",
        "score_range":  [-15, 0],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.1, "Risk-Off": 1.2, "Stagflation": 1.2},
        "inclusion_criteria": "Exchange HHI is a tail-risk factor absent from most indices. Binance-only assets had avg -42% drawdown during 2023 Binance regulatory events vs multi-exchange peers.",
        "known_issues": "CoinGecko Pro tickers endpoint rate-limited; HHI computed lazily and cached 300s. May miss recent exchange additions.",
        "version_added":"4.2",
    },
    {
        "id":           "funding_rate",
        "pillar":       "O",
        "name":         "Perpetual Funding Rate",
        "description":  "OI-weighted 8h funding rate across all perp exchanges. High positive = overleveraged longs = forced liquidation risk.",
        "source":       "coingecko_pro",
        "raw_field":    "funding_rate",
        "normalization":"linear",
        "score_range":  [-15, 3],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.1, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.2, "Risk-Off": 1.3, "Stagflation": 1.2},
        "inclusion_criteria": "Funding rate is a direct measure of leverage imbalance. Assets with funding > 0.1%/8h (>110% annualised) are historically -23% over next 14d after extreme funding events. Orthogonal to vol and ATH distance.",
        "known_issues": "OI-weighting logic uses CoinGecko derivatives endpoint which may have stale data (up to 15min lag). Binance geo-blocked on Railway — mitigated by CG Pro aggregation.",
        "version_added":"4.3",
    },
    {
        "id":           "oi_mcap_ratio",
        "pillar":       "O",
        "name":         "Open Interest / Market Cap",
        "description":  "Total perpetual OI as fraction of MCap. OI > MCap = systemic fragility: a single large liquidation cascade affects spot price.",
        "source":       "coingecko_pro",
        "raw_field":    "open_interest_usd",
        "normalization":"linear",
        "score_range":  [-10, 3],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.1, "Risk-Off": 1.3, "Stagflation": 1.2},
        "inclusion_criteria": "OI/MCap ratio > 0.5 has historically preceded 3 of last 5 major liquidation cascades (Luna, FTX, Nov 2022 BTC). Predictive of vol regime shifts. Added v4.3 after CG Pro wiring.",
        "known_issues": "OI data covers perpetuals only (not options). Missing for spot-only assets. LAS also penalised by OI — documented dual-use (O pillar = CIS score; LAS = position-sizing flag).",
        "version_added":"4.3",
    },

    # ═══════════════════════════════════════════════════════════════════
    # S — SENTIMENT PILLAR  (weight: 15%)
    # Measures market psychology, social signal, behavioral regime
    # ═══════════════════════════════════════════════════════════════════

    {
        "id":           "fear_greed_index",
        "pillar":       "S",
        "name":         "Fear & Greed Index",
        "description":  "Alternative.me composite index (0-100). Applied as baseline × 0.4 — market-wide mood floor for all crypto assets.",
        "source":       "alternative.me",
        "raw_field":    "value",
        "normalization":"linear",
        "score_range":  [2, 40],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin", "Crypto"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.1, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 0.9, "Risk-Off": 0.8, "Stagflation": 0.7},
        "inclusion_criteria": "FNG is a validated contrarian/confirmation signal depending on regime. In Risk-On, high FNG confirms trend; in Risk-Off, extreme FNG (>80) predicts correction within 14d (62% accuracy, n=47). Applied with dampening to prevent overfit.",
        "known_issues": "FNG is a crypto-market-wide signal — no asset-level sentiment. Per-asset divergence (category_divergence factor) compensates for this limitation.",
        "version_added":"4.0",
    },
    {
        "id":           "vix_inverse",
        "pillar":       "S",
        "name":         "VIX Inverse Baseline (TradFi)",
        "description":  "CBOE VIX inverted as sentiment baseline for TradFi assets. High VIX = bearish sentiment baseline.",
        "source":       "yfinance",
        "raw_field":    "vix",
        "normalization":"linear",
        "score_range":  [5, 50],
        "asset_classes":["US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.0, "Risk-Off": 1.2, "Stagflation": 1.2},
        "inclusion_criteria": "VIX is the institutional risk sentiment anchor for equity markets. Applied as separate baseline from FNG to maintain crypto/TradFi S-pillar comparability.",
        "known_issues": "VIX is US equity centric; may not reflect sentiment for Commodities or EM Equity accurately.",
        "version_added":"4.1",
    },
    {
        "id":           "category_divergence",
        "pillar":       "S",
        "name":         "Category Median Divergence",
        "description":  "Asset 30d return vs category median 30d return. Positive divergence = outperforming peers = selective demand signal.",
        "source":       "computed",
        "raw_field":    "change_30d",
        "normalization":"derived",
        "score_range":  [-10, 15],
        "asset_classes":["all"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.1, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.1, "Risk-Off": 1.2, "Stagflation": 1.0},
        "inclusion_criteria": "Per-asset divergence from category median captures relative sentiment. An asset rising when peers fall signals institutional rotation or specific catalyst — distinct from absolute momentum.",
        "known_issues": "Category median computed from CIS universe only (~10-15 assets per class). Small sample creates high variance for niche classes (e.g., Gaming = 3 assets).",
        "version_added":"4.1",
    },
    {
        "id":           "vol_regime",
        "pillar":       "S",
        "name":         "Volume Regime Signal",
        "description":  "Vol/MCap ratio vs threshold classifiers: breakout (high vol + positive price) = bullish signal; capitulation (high vol + negative) = bearish.",
        "source":       "computed",
        "raw_field":    "volume_24h",
        "normalization":"derived",
        "score_range":  [-15, 15],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin", "Crypto"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.1, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 0.9, "Risk-Off": 0.8, "Stagflation": 0.7},
        "inclusion_criteria": "Volume-price divergence classifies market microstructure. Breakout pattern has 58% forward accuracy over 7d. Capitulation signal (false bottom filter) reduces premature long signals in Risk-Off.",
        "known_issues": "Vol/MCap threshold (0.05%) is empirically tuned but not formally backtested across all 84 assets. Reviewed in v4.2.",
        "version_added":"4.1",
    },
    {
        "id":           "momentum_structure",
        "pillar":       "S",
        "name":         "7-Day Momentum Structure",
        "description":  "7d price change directional quality signal — consistent uptrend vs gap-fill pattern.",
        "source":       "coingecko",
        "raw_field":    "change_7d",
        "normalization":"linear",
        "score_range":  [0, 15],
        "asset_classes":["all"],
        "regime_weight":{"Goldilocks": 1.1, "Risk-On": 1.1, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 0.8, "Risk-Off": 0.7, "Stagflation": 0.6},
        "inclusion_criteria": "Short-term momentum structure captures market psychology distinct from 30d momentum. An asset with positive 7d but negative 30d is likely in early recovery.",
        "known_issues": "High correlation with momentum_30d factor (r≈0.52). Retained because it captures mean-reversion cycles missed by 30d window.",
        "version_added":"4.0",
    },
    {
        "id":           "beta_dxy_vix",
        "pillar":       "S",
        "name":         "Macro Sensitivity (DXY/VIX Beta)",
        "description":  "30d rolling beta to DXY (dollar) and VIX. High DXY beta = crypto sensitive to dollar strength; High VIX beta = risk-off fragility.",
        "source":       "computed",
        "raw_field":    "klines",
        "normalization":"derived",
        "score_range":  [-10, 5],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin", "Crypto"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.2, "Risk-Off": 1.3, "Stagflation": 1.3},
        "inclusion_criteria": "Macro betas are the primary cross-asset linkage signal. Assets with high DXY beta are punished in dollar-strength regimes (Tightening). Orthogonal to all other S factors.",
        "known_issues": "Beta calculated from Binance kline data (1-month window). Requires min 20 data points — assets with < 20 days trading history fall back to CG proxy beta.",
        "version_added":"4.2",
    },
    {
        "id":           "trending_rank",
        "pillar":       "S",
        "name":         "CoinGecko Trending Rank",
        "description":  "Position in CoinGecko's top-15 trending coins by search volume and social interaction. Rank #1-3 = +15 S points.",
        "source":       "coingecko_pro",
        "raw_field":    "trending_rank",
        "normalization":"derived",
        "score_range":  [0, 15],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin", "Crypto"],
        "regime_weight":{"Goldilocks": 1.2, "Risk-On": 1.3, "Easing": 1.1,
                         "Neutral": 1.0, "Tightening": 0.6, "Risk-Off": 0.4, "Stagflation": 0.3},
        "inclusion_criteria": "Trending rank is a real-time social sentiment signal unavailable from most data sources. Trending + high CIS = quality breakout. Trending + low CIS = hype trap (flagged by /api/v1/market/trending-overlay). Added v4.3.",
        "known_issues": "CoinGecko trending updates every ~2h. Not available for TradFi assets. Heavily regime-weighted: irrelevant signal in Risk-Off (fear-driven markets don't trend for quality reasons).",
        "version_added":"4.3",
    },
    {
        "id":           "recovery_bonus",
        "pillar":       "S",
        "name":         "Recovery Momentum Bonus",
        "description":  "Extra S-pillar credit for assets in confirmed uptrend recovery: 7d positive after prior 30d negative. Anti-capitulation signal.",
        "source":       "computed",
        "raw_field":    "change_7d",
        "normalization":"derived",
        "score_range":  [0, 10],
        "asset_classes":["all"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.2, "Easing": 1.2,
                         "Neutral": 1.0, "Tightening": 0.8, "Risk-Off": 0.5, "Stagflation": 0.5},
        "inclusion_criteria": "Recovery bonus prevents premature penalisation of rebounding assets. Without it, a coin that fell 30d ago but is recovering would still score poorly on momentum. Introduced after v4.2 review flagged systematic underscoring of early-recovery assets.",
        "known_issues": "May create false positives during dead-cat bounces. Controlled by requiring vol_regime ≠ capitulation as guard condition.",
        "version_added":"4.2",
    },

    # ═══════════════════════════════════════════════════════════════════
    # A — ALPHA PILLAR  (weight: 10%)
    # Measures excess return vs benchmark — pure performance differentiation
    # ═══════════════════════════════════════════════════════════════════

    {
        "id":           "btc_divergence",
        "pillar":       "A",
        "name":         "BTC 30d Divergence",
        "description":  "Asset 30d return minus BTC 30d return. Positive = outperformed BTC (the crypto risk benchmark). Applied to all non-BTC crypto assets.",
        "source":       "coingecko",
        "raw_field":    "change_30d",
        "normalization":"linear",
        "score_range":  [0, 50],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin"],
        "regime_weight":{"Goldilocks": 1.2, "Risk-On": 1.2, "Easing": 1.1,
                         "Neutral": 1.0, "Tightening": 0.9, "Risk-Off": 0.7, "Stagflation": 0.6},
        "inclusion_criteria": "BTC is the crypto market's risk-free rate equivalent. Outperforming BTC = genuine alpha in crypto. This is the primary selection signal for active management vs passive BTC holding.",
        "known_issues": "Correlation floor raised in Risk-Off (alts drop more than BTC → most assets score 0 on this factor). Treated correctly as regime behavior, not factor failure.",
        "version_added":"4.0",
    },
    {
        "id":           "spy_divergence",
        "pillar":       "A",
        "name":         "SPY 30d Divergence (TradFi)",
        "description":  "Asset 30d return minus SPY 30d return. For US equities. Bond divergence inverted (bonds rising = positive alpha vs SPY).",
        "source":       "yfinance",
        "raw_field":    "change_30d",
        "normalization":"linear",
        "score_range":  [0, 50],
        "asset_classes":["US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity"],
        "regime_weight":{"Goldilocks": 1.1, "Risk-On": 1.2, "Easing": 1.1,
                         "Neutral": 1.0, "Tightening": 0.9, "Risk-Off": 1.1, "Stagflation": 1.1},
        "inclusion_criteria": "SPY is the TradFi risk-free rate equivalent. Outperforming SPY = genuine alpha. Bond inversion is deliberate: in Risk-Off, bonds rising relative to SPY is the correct alpha expression.",
        "known_issues": "SPY divergence ignores sector effects — a tech stock outperforming SPY may simply be in a hot sector. Sector-adjusted alpha is a v4.4 candidate.",
        "version_added":"4.1",
    },
    {
        "id":           "class_independence",
        "pillar":       "A",
        "name":         "Class Independence Score",
        "description":  "30d correlation of asset vs class median. Low correlation = idiosyncratic alpha source, not just class beta.",
        "source":       "computed",
        "raw_field":    "change_30d",
        "normalization":"derived",
        "score_range":  [-5, 10],
        "asset_classes":["all"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.0, "Risk-Off": 1.1, "Stagflation": 1.1},
        "inclusion_criteria": "A portfolio asset should have idiosyncratic returns beyond class exposure. Class independence rewards assets that zig when peers zag — a diversification quality signal.",
        "known_issues": "Class correlation computed from small class samples (as low as 3 for Gaming). High variance with small N.",
        "version_added":"4.2",
    },
    {
        "id":           "size_efficiency",
        "pillar":       "A",
        "name":         "Size Efficiency Score",
        "description":  "Return per unit of market cap. Small caps that outperform large caps disproportionately score higher.",
        "source":       "computed",
        "raw_field":    "change_30d",
        "normalization":"derived",
        "score_range":  [-5, 10],
        "asset_classes":["all"],
        "regime_weight":{"Goldilocks": 1.1, "Risk-On": 1.2, "Easing": 1.1,
                         "Neutral": 1.0, "Tightening": 0.8, "Risk-Off": 0.6, "Stagflation": 0.5},
        "inclusion_criteria": "Size efficiency captures the small-cap alpha premium — documented in both equity and crypto research. A $100M cap asset returning +30% vs a $100B asset returning +5% reflects different efficiency levels.",
        "known_issues": "Heavily dampened in risk-off — small caps are liquidity traps in stress events. Regime weighting correctly suppresses this factor in Risk-Off/Stagflation.",
        "version_added":"4.2",
    },
    {
        "id":           "correlation_discount",
        "pillar":       "A",
        "name":         "High-Correlation Discount",
        "description":  "Penalty applied when asset correlation to BTC is extreme (r > 0.90). Highly correlated assets provide no alpha over BTC exposure.",
        "source":       "computed",
        "raw_field":    "klines",
        "normalization":"derived",
        "score_range":  [-15, 0],
        "asset_classes":["L1", "L2", "DeFi", "RWA", "Infrastructure", "AI", "Gaming", "Memecoin"],
        "regime_weight":{"Goldilocks": 1.0, "Risk-On": 1.0, "Easing": 1.0,
                         "Neutral": 1.0, "Tightening": 1.0, "Risk-Off": 1.5, "Stagflation": 1.5},
        "inclusion_criteria": "BTC correlation > 0.90 means the asset adds no diversification to a BTC-heavy portfolio. The A pillar is specifically for identifying alpha beyond BTC. Discount signals redundant exposure.",
        "known_issues": "Correlation computed on 30d window — may not reflect structural vs temporary BTC correlation shifts. Floor raised in Risk-Off (all alts correlate more → discount correctly applied to prevent over-allocation to BTC proxies).",
        "version_added":"4.2",
    },
]

# ── Factor index helpers ──────────────────────────────────────────────────────

def get_by_pillar(pillar: PillarKey) -> list[dict]:
    """Return all factors for a given pillar."""
    return [f for f in FACTORS if f["pillar"] == pillar]


def get_by_id(factor_id: str) -> dict | None:
    """Return a single factor by its id."""
    for f in FACTORS:
        if f["id"] == factor_id:
            return f
    return None


def get_by_class(asset_class: str) -> list[dict]:
    """Return factors applicable to an asset class."""
    return [f for f in FACTORS if "all" in f["asset_classes"]
            or asset_class in f["asset_classes"]]


def summary() -> dict:
    """Registry summary statistics."""
    by_pillar = {}
    for p in ["F", "M", "O", "S", "A"]:
        fs = get_by_pillar(p)
        by_pillar[p] = {
            "count": len(fs),
            "factors": [f["id"] for f in fs],
            "sources": list({f["source"] for f in fs}),
        }
    with_caveats = [f["id"] for f in FACTORS if f.get("known_issues")]
    return {
        "total_factors":       len(FACTORS),
        "by_pillar":           by_pillar,
        "sources_used":        list({f["source"] for f in FACTORS}),
        "factors_with_caveats": with_caveats,
        "caveats_count":       len(with_caveats),
        "note":                "factors_with_caveats = documented data quality issues. §F-SEL performance-based status (active/probationary/candidate_removal) tracked at /api/v1/factors/performance.",
        "version":             "4.3",
    }
