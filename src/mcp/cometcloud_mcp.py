#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp[cli]>=1.6.0",
#   "httpx>=0.27.0",
#   "pydantic>=2.0.0",
# ]
# ///
"""
CometCloud AI — MCP Server

Exposes CometCloud's CIS scoring engine, market intelligence, protocol analytics,
and fund data as MCP tools. Any MCP-compatible agent (Claude, GPT, Gemini, Cursor)
can query CIS scores, signal feeds, vault data, and DeFi analytics natively.

Tools:
  CIS Intelligence  — cis_universe, cis_asset, cis_history, cis_top
  Market Data       — prices, movers, macro_pulse
  Signals           — signal_feed, macro_events, vc_funding
  DeFi & Protocols  — protocols, defi_overview, defi_yields
  Fund & Portfolio  — fund_portfolio, portfolio_stats

Transport: stdio (default) | streamable_http (set MCP_PORT env var)
Auth: none for public endpoints; set MCP_API_KEY for future gated tiers

Usage:
  python cometcloud_mcp.py                    # stdio
  MCP_PORT=8001 python cometcloud_mcp.py      # HTTP on port 8001
"""

import json
import os
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Configuration ─────────────────────────────────────────────────────────────

RAILWAY_BASE = os.getenv(
    "COMETCLOUD_API_BASE",
    "https://web-production-0cdf76.up.railway.app",
)
API_TIMEOUT     = float(os.getenv("MCP_API_TIMEOUT", "20.0"))
API_TIMEOUT_CIS = float(os.getenv("MCP_API_TIMEOUT_CIS", "60.0"))  # CIS universe is expensive
MCP_PORT        = int(os.getenv("MCP_PORT", "0"))  # 0 = stdio

# ── Server ────────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "cometcloud_mcp",
    instructions=(
        "CometCloud AI MCP Server. Provides CIS scoring, market intelligence, "
        "protocol analytics, and fund data for the CometCloud Fund-of-Funds platform. "
        "All signals use compliance-safe positioning language: "
        "STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT. "
        "Never interpret signals as BUY/SELL recommendations."
    ),
)

# ── Shared HTTP client ────────────────────────────────────────────────────────

async def _get(path: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Any:
    """Single reusable GET call to the Railway API."""
    url = f"{RAILWAY_BASE}{path}"
    t = timeout if timeout is not None else API_TIMEOUT
    async with httpx.AsyncClient(timeout=t) as client:
        resp = await client.get(url, params=params or {})
        resp.raise_for_status()
        return resp.json()


def _err(e: Exception) -> str:
    """Consistent error formatting for all tools."""
    if isinstance(e, httpx.HTTPStatusError):
        s = e.response.status_code
        if s == 404:
            return "Error: Resource not found. Check the symbol or slug."
        if s == 429:
            return "Error: Rate limit exceeded. Retry in a few seconds."
        if s == 503:
            return "Error: CometCloud API is warming up. Retry in 10s."
        return f"Error: API returned {s}."
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. The API may be under load — retry."
    return f"Error: {type(e).__name__}: {e}"


# ── Enums & shared models ─────────────────────────────────────────────────────

class Fmt(str, Enum):
    """Response format."""
    JSON     = "json"
    MARKDOWN = "markdown"


class AssetClassFilter(str, Enum):
    ALL         = "all"
    L1          = "L1"
    L2          = "L2"
    DEFI        = "DeFi"
    RWA         = "RWA"
    MEMECOIN    = "Memecoin"
    GAMING      = "Gaming"
    AI          = "AI"
    COMMODITY   = "Commodity"
    US_EQUITY   = "US Equity"
    US_BOND     = "US Bond"


# ── Tool input models ─────────────────────────────────────────────────────────

class CisUniverseInput(BaseModel):
    """Input for cometcloud_get_cis_universe."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    asset_class: AssetClassFilter = Field(
        default=AssetClassFilter.ALL,
        description="Filter by asset class. Use 'all' for the full universe.",
    )
    min_grade: Optional[str] = Field(
        default=None,
        description="Minimum CIS grade filter (A+, A, B+, B, C+, C, D, F). "
                    "Returns only assets at or above this grade.",
    )
    response_format: Fmt = Field(default=Fmt.JSON, description="json or markdown")

    @field_validator("min_grade")
    @classmethod
    def validate_grade(cls, v: Optional[str]) -> Optional[str]:
        valid = {"A+", "A", "B+", "B", "C+", "C", "D", "F"}
        if v and v not in valid:
            raise ValueError(f"min_grade must be one of {sorted(valid)}")
        return v


class CisAssetInput(BaseModel):
    """Input for cometcloud_get_cis_asset."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(
        ...,
        description="Asset ticker symbol (e.g. BTC, ETH, SOL, AAPL, GLD).",
        min_length=1,
        max_length=12,
    )
    response_format: Fmt = Field(default=Fmt.JSON)

    @field_validator("symbol")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.upper()


class CisHistoryInput(BaseModel):
    """Input for cometcloud_get_cis_history."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(..., description="Asset ticker symbol.", min_length=1, max_length=12)
    days: int = Field(default=7, description="Number of days of history to return (1–30).", ge=1, le=30)
    response_format: Fmt = Field(default=Fmt.JSON)

    @field_validator("symbol")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.upper()


class CisTopInput(BaseModel):
    """Input for cometcloud_get_cis_top."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    limit: int = Field(default=10, description="Number of top assets to return (1–50).", ge=1, le=50)
    asset_class: AssetClassFilter = Field(
        default=AssetClassFilter.ALL,
        description="Filter by asset class.",
    )
    signal: Optional[str] = Field(
        default=None,
        description="Filter by signal: OUTPERFORM, STRONG OUTPERFORM, NEUTRAL, UNDERPERFORM, UNDERWEIGHT.",
    )
    response_format: Fmt = Field(default=Fmt.MARKDOWN)


class PricesInput(BaseModel):
    """Input for cometcloud_get_prices."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbols: str = Field(
        default="BTC,ETH,SOL",
        description="Comma-separated ticker symbols (e.g. 'BTC,ETH,SOL,AAPL').",
    )
    response_format: Fmt = Field(default=Fmt.MARKDOWN)


class SignalFeedInput(BaseModel):
    """Input for cometcloud_get_signal_feed."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    limit: int = Field(default=20, description="Maximum signals to return (1–50).", ge=1, le=50)
    response_format: Fmt = Field(default=Fmt.MARKDOWN)


class ProtocolsInput(BaseModel):
    """Input for cometcloud_get_protocols."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    category: Optional[str] = Field(
        default=None,
        description="Filter by category: 'RWA - Treasuries', 'RWA - Private Credit', "
                    "'DeFi - Lending', 'DeFi - DEX', 'DeFi - Staking', 'Derivatives', 'Infrastructure'.",
    )
    min_grade: Optional[str] = Field(
        default=None,
        description="Minimum CIS grade filter.",
    )
    sort_by: str = Field(
        default="score",
        description="Sort field: 'score', 'tvl', or 'change_7d'.",
    )
    response_format: Fmt = Field(default=Fmt.JSON)


class YieldsInput(BaseModel):
    """Input for cometcloud_get_defi_yields."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    min_apy: float = Field(default=0.0, description="Minimum APY filter (e.g. 5.0 for 5%+).", ge=0)
    limit: int = Field(default=20, description="Number of pools to return (1–50).", ge=1, le=50)
    response_format: Fmt = Field(default=Fmt.MARKDOWN)


class VcFundingInput(BaseModel):
    """Input for cometcloud_get_vc_funding."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    limit: int = Field(default=15, description="Number of funding rounds to return (1–50).", ge=1, le=50)
    response_format: Fmt = Field(default=Fmt.MARKDOWN)


class PortfolioStatsInput(BaseModel):
    """Input for cometcloud_get_portfolio_stats."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbols: str = Field(
        default="BTC,ETH,SOL",
        description="Comma-separated asset symbols for portfolio analysis.",
    )
    weights: Optional[str] = Field(
        default=None,
        description="Comma-separated portfolio weights matching symbols (e.g. '0.5,0.3,0.2'). "
                    "Must sum to 1.0. Leave blank for equal-weight.",
    )
    response_format: Fmt = Field(default=Fmt.JSON)


class CisReportInput(BaseModel):
    """Input for cometcloud_get_cis_report."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(
        ...,
        description="Asset ticker symbol (e.g. BTC, ETH, SOL, LINK, AAPL, GLD).",
        min_length=1,
        max_length=12,
    )

    @field_validator("symbol")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.upper()


# ── Grade ordering helper ─────────────────────────────────────────────────────

_GRADE_ORDER = {"A+": 8, "A": 7, "B+": 6, "B": 5, "C+": 4, "C": 3, "D": 2, "F": 1}

def _above_min_grade(asset_grade: str, min_grade: str) -> bool:
    return _GRADE_ORDER.get(asset_grade, 0) >= _GRADE_ORDER.get(min_grade, 0)


# ── Tools — CIS Intelligence ─────────────────────────────────────────────────

@mcp.tool(
    name="cometcloud_get_cis_universe",
    annotations={
        "title": "CIS Universe — Full Leaderboard",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_cis_universe(params: CisUniverseInput) -> str:
    """Retrieve the full CIS (CometCloud Intelligence Score) universe leaderboard.

    Returns all scored assets with grades, signals, pillar breakdowns, LAS
    (Liquidity-Adjusted Score), data tier (T1 Mac Mini / T2 Railway), and
    7-day score sparklines. Supports filtering by asset class and minimum grade.

    CIS v4.1 grading uses absolute thresholds:
    A+≥85, A≥75, B+≥65, B≥55, C+≥45, C≥35, D≥25, F<25.

    Signals are compliance-safe positioning language:
    STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT.
    Do NOT interpret as BUY/SELL recommendations.

    Args:
        params (CisUniverseInput):
            - asset_class: Filter by class (all, L1, L2, DeFi, RWA, Memecoin, ...)
            - min_grade: Minimum grade threshold (A+, A, B+, B, C+, C, D, F)
            - response_format: 'json' or 'markdown'

    Returns:
        str: JSON or markdown with:
        {
          "universe_size": int,
          "data_tier": "T1_LOCAL" | "T2_MARKET",
          "macro_regime": str,
          "assets": [
            {
              "symbol": str, "name": str, "asset_class": str,
              "grade": str, "cis_score": float,
              "signal": str,
              "las": float,                    # Liquidity-Adjusted Score
              "confidence": float,
              "pillars": {"F": float, "M": float, "O": float, "S": float, "A": float},
              "sparkline_7d": [float],         # 7-day score history
              "price": float, "change_24h": float
            }
          ]
        }

    Examples:
        - "Show me all A-grade assets" → min_grade="A"
        - "List all DeFi protocols in the CIS universe" → asset_class="DeFi"
        - "What RWA assets are rated OUTPERFORM?" → asset_class="RWA"
    """
    try:
        data = await _get("/api/v1/cis/universe", timeout=API_TIMEOUT_CIS)
        assets = data.get("universe", data.get("assets", []))

        # Apply filters
        if params.asset_class != AssetClassFilter.ALL:
            assets = [a for a in assets if a.get("asset_class") == params.asset_class]
        if params.min_grade:
            assets = [a for a in assets if _above_min_grade(a.get("grade", "F"), params.min_grade)]

        result = {
            "universe_size": len(assets),
            "data_tier": data.get("source", "T2_MARKET"),
            "macro_regime": data.get("macro", {}).get("regime", "UNKNOWN"),
            "last_updated": data.get("last_updated"),
            "assets": assets,
        }

        if params.response_format == Fmt.JSON:
            return json.dumps(result, indent=2)

        # Markdown
        lines = [
            f"# CIS Universe — {len(assets)} assets",
            f"**Data tier**: {result['data_tier']} · **Regime**: {result['macro_regime']}",
            "",
            "| # | Symbol | Class | Grade | Score | Signal | LAS |",
            "|---|--------|-------|-------|-------|--------|-----|",
        ]
        for i, a in enumerate(assets[:50], 1):
            lines.append(
                f"| {i} | {a.get('symbol')} | {a.get('asset_class')} | "
                f"**{a.get('grade')}** | {a.get('cis_score', 0):.1f} | "
                f"{a.get('signal')} | {a.get('las', 0):.1f} |"
            )
        if len(assets) > 50:
            lines.append(f"\n*…and {len(assets) - 50} more. Use response_format=json for full data.*")
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


@mcp.tool(
    name="cometcloud_get_cis_asset",
    annotations={
        "title": "CIS Asset — Single Asset Deep Dive",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_cis_asset(params: CisAssetInput) -> str:
    """Get a complete CIS scoring breakdown for a single asset.

    Returns the full 5-pillar score (F/M/O/S/A), grade, signal, LAS,
    recommended portfolio weight, macro regime context, and all metadata
    for a specified asset symbol. Covers both crypto and TradFi assets.

    Args:
        params (CisAssetInput):
            - symbol: Ticker (e.g. 'BTC', 'ETH', 'SOL', 'MKR', 'AAPL', 'GLD')
            - response_format: 'json' or 'markdown'

    Returns:
        str: Full CIS data including:
        {
          "symbol": str, "name": str, "asset_class": str,
          "grade": str, "cis_score": float, "signal": str,
          "las": float, "confidence": float,
          "pillars": {"F": float, "M": float, "O": float, "S": float, "A": float},
          "pillar_weights": {"F": float, ...},
          "recommended_weight": float,     # % of portfolio
          "price": float, "market_cap": float, "volume_24h": float,
          "change_24h": float, "change_7d": float
        }

    Examples:
        - "What's Bitcoin's CIS score?" → symbol="BTC"
        - "Is Solana rated outperform?" → symbol="SOL"
        - "Give me MakerDAO's pillar breakdown" → symbol="MKR"
        - "What's the recommended weight for ETH?" → symbol="ETH"
    """
    try:
        data = await _get(f"/api/v1/cis/asset/{params.symbol}", timeout=API_TIMEOUT_CIS)

        if params.response_format == Fmt.JSON:
            return json.dumps(data, indent=2)

        p = data.get("pillars", {})
        lines = [
            f"# {data.get('name', params.symbol)} ({params.symbol}) — CIS Deep Dive",
            "",
            f"**Grade**: {data.get('grade')}  |  **Score**: {data.get('cis_score', 0):.1f}  |  "
            f"**Signal**: {data.get('signal')}  |  **LAS**: {data.get('las', 0):.1f}",
            f"**Asset Class**: {data.get('asset_class')}  |  "
            f"**Confidence**: {data.get('confidence', 0):.0%}  |  "
            f"**Rec. Weight**: {data.get('recommended_weight', 0):.1f}%",
            "",
            "## CIS Pillar Scores",
            f"- **F (Fundamental)**: {p.get('F', 0):.1f}",
            f"- **M (Momentum)**: {p.get('M', 0):.1f}",
            f"- **O (On-chain / Risk)**: {p.get('O', 0):.1f}",
            f"- **S (Sentiment)**: {p.get('S', 0):.1f}",
            f"- **A (Alpha)**: {p.get('A', 0):.1f}",
            "",
            "## Price Data",
            f"- **Price**: ${data.get('price', 0):,.4f}",
            f"- **24H**: {data.get('change_24h', 0):+.2f}%",
            f"- **7D**: {data.get('change_7d', 0):+.2f}%",
            f"- **Market Cap**: ${data.get('market_cap', 0):,.0f}",
            f"- **24H Volume**: ${data.get('volume_24h', 0):,.0f}",
        ]
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


@mcp.tool(
    name="cometcloud_get_cis_history",
    annotations={
        "title": "CIS Score History — Trend Analysis",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_cis_history(params: CisHistoryInput) -> str:
    """Retrieve historical CIS score trend for a single asset.

    Returns daily CIS scores over the requested window. Useful for detecting
    grade migrations, momentum regime changes, and signal reversals.

    Args:
        params (CisHistoryInput):
            - symbol: Asset ticker (e.g. 'BTC', 'ETH')
            - days: History window 1–30 days (default 7)
            - response_format: 'json' or 'markdown'

    Returns:
        str: Score history with:
        {
          "symbol": str,
          "history": [
            {"date": str, "score": float, "grade": str, "signal": str}
          ],
          "trend": "IMPROVING" | "DECLINING" | "STABLE"
        }

    Examples:
        - "Has BTC's CIS score improved this week?" → symbol="BTC", days=7
        - "Show me ETH's 30-day score trend" → symbol="ETH", days=30
    """
    try:
        data = await _get(f"/api/v1/cis/history/{params.symbol}", params={"days": params.days}, timeout=API_TIMEOUT_CIS)

        if params.response_format == Fmt.JSON:
            return json.dumps(data, indent=2)

        history = data.get("history", [])
        trend = data.get("trend", "STABLE")
        lines = [
            f"# {params.symbol} — CIS Score History ({params.days}d)",
            f"**Trend**: {trend}",
            "",
            "| Date | Score | Grade | Signal |",
            "|------|-------|-------|--------|",
        ]
        for row in history:
            date_val = row.get('recorded_at', row.get('date', '—'))
            score_val = row.get('score', 0)
            grade_val = row.get('grade', '—')
            signal_val = row.get('signal', '—')
            lines.append(
                f"| {date_val} | {score_val:.1f} | {grade_val} | {signal_val} |"
            )
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


@mcp.tool(
    name="cometcloud_get_cis_top",
    annotations={
        "title": "CIS Top Assets — Ranked List",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_cis_top(params: CisTopInput) -> str:
    """Get the top N assets ranked by CIS score, with optional class and signal filters.

    A quick way to surface the highest-scoring assets in the universe or within
    a specific asset class. Useful for portfolio screening and signal monitoring.

    Args:
        params (CisTopInput):
            - limit: Number of assets to return (default 10, max 50)
            - asset_class: Filter by class (default 'all')
            - signal: Optional signal filter (OUTPERFORM, NEUTRAL, etc.)
            - response_format: 'json' or 'markdown'

    Returns:
        str: Ranked table of top assets with grades, scores, signals, and price data.

    Examples:
        - "What are the top 10 assets by CIS score?" → default params
        - "Top 5 DeFi protocols by score" → limit=5, asset_class="DeFi"
        - "Which L1s have OUTPERFORM signal?" → asset_class="L1", signal="OUTPERFORM"
    """
    try:
        data = await _get("/api/v1/cis/universe", timeout=API_TIMEOUT_CIS)
        assets = data.get("universe", data.get("assets", []))

        if params.asset_class != AssetClassFilter.ALL:
            assets = [a for a in assets if a.get("asset_class") == params.asset_class]
        if params.signal:
            assets = [a for a in assets if a.get("signal", "").upper() == params.signal.upper()]

        assets = sorted(assets, key=lambda a: a.get("cis_score", 0), reverse=True)
        assets = assets[: params.limit]

        if params.response_format == Fmt.JSON:
            return json.dumps({"count": len(assets), "assets": assets}, indent=2)

        lines = [
            f"# Top {len(assets)} Assets by CIS Score",
            f"Filter — Class: {params.asset_class.value} | Signal: {params.signal or 'any'}",
            "",
            "| Rank | Symbol | Class | Grade | Score | Signal | 24H% |",
            "|------|--------|-------|-------|-------|--------|------|",
        ]
        for i, a in enumerate(assets, 1):
            chg = a.get("change_24h", 0)
            lines.append(
                f"| {i} | **{a.get('symbol')}** | {a.get('asset_class')} | "
                f"**{a.get('grade')}** | {a.get('cis_score', 0):.1f} | "
                f"{a.get('signal')} | {chg:+.2f}% |"
            )
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


# ── Tools — Market Data ───────────────────────────────────────────────────────

@mcp.tool(
    name="cometcloud_get_prices",
    annotations={
        "title": "Market Prices — Multi-Asset",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_prices(params: PricesInput) -> str:
    """Fetch live prices, 24H/7D changes, and market cap for multiple assets.

    Covers crypto (via CoinGecko) and TradFi assets (via yfinance): equities,
    bonds, commodities. Returns current price, volume, and change data.

    Args:
        params (PricesInput):
            - symbols: Comma-separated tickers (e.g. 'BTC,ETH,SOL,AAPL,GLD')
            - response_format: 'json' or 'markdown'

    Returns:
        str: Price data per asset including price, change_24h, change_7d,
             market_cap, volume_24h.

    Examples:
        - "What's the price of BTC and ETH?" → symbols="BTC,ETH"
        - "Show me prices for SOL, AVAX, and MATIC" → symbols="SOL,AVAX,MATIC"
    """
    try:
        data = await _get("/api/v1/market/prices", params={"symbols": params.symbols})

        if params.response_format == Fmt.JSON:
            return json.dumps(data, indent=2)

        prices = data if isinstance(data, list) else data.get("prices", [])
        lines = [
            "# Live Market Prices",
            "",
            "| Symbol | Price | 24H% | 7D% | Market Cap |",
            "|--------|-------|------|-----|-----------|",
        ]
        for asset in prices:
            mc = asset.get("market_cap", 0)
            mc_str = f"${mc/1e9:.1f}B" if mc >= 1e9 else f"${mc/1e6:.0f}M" if mc >= 1e6 else "—"
            lines.append(
                f"| **{asset.get('symbol')}** | ${asset.get('price', 0):,.4f} | "
                f"{asset.get('change_24h', 0):+.2f}% | {asset.get('change_7d', 0):+.2f}% | "
                f"{mc_str} |"
            )
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


@mcp.tool(
    name="cometcloud_get_market_movers",
    annotations={
        "title": "Market Movers — Top Gainers & Losers",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_market_movers() -> str:
    """Fetch the top gainers and losers across the tracked market universe.

    Returns the 5 biggest 24H gainers and 5 biggest losers, including price,
    change percentage, and market cap. Useful for momentum scanning.

    Returns:
        str: Markdown table of top gainers and losers with symbol, price, change%.

    Examples:
        - "What's pumping today?" → use this tool
        - "What are the biggest losers in crypto right now?" → use this tool
    """
    try:
        data = await _get("/api/v1/market/movers")
        gainers = data.get("gainers", [])
        losers  = data.get("losers", [])

        lines = ["# Market Movers — 24H", ""]
        lines += [
            "## 🔺 Top Gainers",
            "| Symbol | Price | 24H% |",
            "|--------|-------|------|",
        ]
        for a in gainers:
            lines.append(f"| **{a.get('symbol')}** | ${a.get('price', 0):,.4f} | +{a.get('change', 0):.2f}% |")

        lines += ["", "## 🔻 Top Losers", "| Symbol | Price | 24H% |", "|--------|-------|------|"]
        for a in losers:
            lines.append(f"| **{a.get('symbol')}** | ${a.get('price', 0):,.4f} | {a.get('change', 0):.2f}% |")

        return "\n".join(lines)

    except Exception as e:
        return _err(e)


@mcp.tool(
    name="cometcloud_get_macro_pulse",
    annotations={
        "title": "Macro Pulse — Market Regime & Sentiment",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_macro_pulse() -> str:
    """Get the current macro market pulse: Bitcoin dominance, Fear & Greed Index,
    total crypto market cap, DeFi TVL, and CometCloud's macro regime classification.

    Regime classifications:
    RISK_ON, RISK_OFF, TIGHTENING, EASING, STAGFLATION, GOLDILOCKS.

    Returns:
        str: Macro pulse snapshot with:
        {
          "btc_dominance": float,
          "fear_greed_index": int,       # 0 (extreme fear) to 100 (extreme greed)
          "fear_greed_label": str,
          "total_market_cap_usd": float,
          "defi_tvl_usd": float,
          "btc_price": float,
          "macro_regime": str
        }

    Examples:
        - "What's the current market sentiment?" → use this tool
        - "Is Bitcoin dominance rising or falling?" → use this tool
        - "What macro regime is the market in?" → use this tool
    """
    try:
        data = await _get("/api/v1/market/macro-pulse")

        # Flat fields (present after data_layer.py v2 — added 2026-04-02)
        # Fall back to parsing nested structure for older deployments
        _fng_nested  = data.get("fng", {})
        _cg_nested   = data.get("data", {})
        _btc_nested  = data.get("btc", {})

        fg  = data.get("fear_greed_index",
                       int(_fng_nested.get("value", 0) or 0))
        fg_label = data.get("fear_greed_label",
                            _fng_nested.get("value_classification", "—"))
        dom = data.get("btc_dominance",
                       round(_cg_nested.get("market_cap_percentage", {}).get("btc", 0), 2))
        mc  = data.get("total_market_cap_usd", 0)
        tvl = data.get("defi_tvl_usd", 0)
        btc_px = data.get("btc_price",
                          _btc_nested.get("usd", 0))
        regime = data.get("macro_regime", "—")

        lines = [
            "# Macro Pulse",
            "",
            f"**Regime**: {regime}",
            f"**Fear & Greed**: {fg} — {fg_label}",
            f"**BTC Dominance**: {dom:.1f}%",
            f"**BTC Price**: ${btc_px:,.0f}",
        ]
        if mc:
            lines.append(f"**Total Crypto Market Cap**: ${mc/1e9:.1f}B")
        if tvl:
            lines.append(f"**DeFi TVL**: ${tvl/1e9:.1f}B")
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


# ── Tools — Signals & Intelligence ───────────────────────────────────────────

@mcp.tool(
    name="cometcloud_get_signal_feed",
    annotations={
        "title": "Signal Feed — CometCloud Intelligence Signals",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_signal_feed(params: SignalFeedInput) -> str:
    """Fetch the CometCloud signal feed — curated intelligence signals across
    7 concurrent sources: CIS Score Updates, Momentum Alerts, On-chain Flows,
    VC Funding, DeFi TVL Shifts, Macro Events, and Sentiment Shifts.

    All signals use compliance-safe positioning language only.
    Do NOT interpret as BUY/SELL trade recommendations.

    Args:
        params (SignalFeedInput):
            - limit: Max signals to return (default 20, max 50)
            - response_format: 'json' or 'markdown'

    Returns:
        str: List of signals with:
        {
          "signals": [
            {
              "id": str, "type": str, "title": str,
              "body": str, "asset": str,
              "signal": str,           # OUTPERFORM / NEUTRAL / UNDERPERFORM / etc.
              "time_horizon": str,     # SHORT / MEDIUM / LONG
              "confidence": float,
              "timestamp": str
            }
          ]
        }

    Examples:
        - "What are the latest CometCloud signals?" → use this tool
        - "Any new DeFi TVL signals?" → use this tool, filter type by client
    """
    try:
        data = await _get("/api/v1/signals")
        signals = data.get("signals", data if isinstance(data, list) else [])
        signals = signals[: params.limit]

        if params.response_format == Fmt.JSON:
            return json.dumps({"count": len(signals), "signals": signals}, indent=2)

        lines = [f"# Signal Feed ({len(signals)} signals)", ""]
        for sig in signals:
            # API uses description/logic/affected_assets/vector_direction
            # (not title/body/asset/signal)
            title   = sig.get("description") or sig.get("title") or "—"
            body    = sig.get("logic") or sig.get("body") or ""
            assets  = sig.get("affected_assets") or ([sig.get("asset")] if sig.get("asset") else [])
            assets_str = ", ".join(assets) if isinstance(assets, list) else str(assets)
            signal  = sig.get("vector_direction") or sig.get("signal") or "—"
            lines += [
                f"### {title}",
                f"**Type**: {sig.get('type', '—')} · **Assets**: {assets_str} · "
                f"**Direction**: {signal} · **Horizon**: {sig.get('time_horizon', '—')} · "
                f"**Importance**: {sig.get('importance', '—')}",
                body,
                f"*{sig.get('timestamp', '')}*",
                "",
            ]
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


@mcp.tool(
    name="cometcloud_get_macro_events",
    annotations={
        "title": "Macro Events — Upcoming Calendar",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_macro_events() -> str:
    """Fetch upcoming macro events that may impact asset prices and CIS scores.

    Covers Fed meetings, CPI/PPI releases, token unlocks, major protocol launches,
    and other scheduled market-moving events tracked by CometCloud.

    Returns:
        str: Markdown list of upcoming macro events with date, event name,
             affected assets, and expected market impact.

    Examples:
        - "Any upcoming FOMC meetings this month?" → use this tool
        - "What macro events should I watch?" → use this tool
    """
    try:
        data = await _get("/api/v1/intelligence/macro-events")
        events = data.get("events", data if isinstance(data, list) else [])

        lines = ["# Upcoming Macro Events", ""]
        for ev in events:
            lines += [
                f"### {ev.get('date', '—')} — {ev.get('name', '—')}",
                f"**Category**: {ev.get('category', '—')} · "
                f"**Impact**: {ev.get('impact', '—')}",
                ev.get("description", ""),
                "",
            ]
        return "\n".join(lines) if len(lines) > 2 else "No upcoming macro events found."

    except Exception as e:
        return _err(e)


@mcp.tool(
    name="cometcloud_get_vc_funding",
    annotations={
        "title": "VC Funding Rounds — Web3 Investment Intelligence",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_vc_funding(params: VcFundingInput) -> str:
    """Fetch recent VC funding rounds in the Web3 / crypto space.

    Tracks investment flows into protocols, infrastructure, and application
    layer projects. Funding data is an input to the CIS F (Fundamental) pillar.

    Args:
        params (VcFundingInput):
            - limit: Number of rounds to return (default 15, max 50)
            - response_format: 'json' or 'markdown'

    Returns:
        str: Table of funding rounds with project, amount, investors, category, date.

    Examples:
        - "What are the biggest recent crypto funding rounds?" → use this tool
        - "Who's investing in DeFi infrastructure?" → use this tool
    """
    try:
        data = await _get("/api/v1/vc/funding-rounds")
        rounds = data.get("rounds", data if isinstance(data, list) else [])
        rounds = rounds[: params.limit]

        if params.response_format == Fmt.JSON:
            return json.dumps({"count": len(rounds), "rounds": rounds}, indent=2)

        lines = [
            f"# VC Funding Rounds (last {len(rounds)})",
            "",
            "| Project | Amount | Category | Investors | Date |",
            "|---------|--------|----------|-----------|------|",
        ]
        for r in rounds:
            amt = r.get("amount_usd", 0)
            amt_str = f"${amt/1e6:.0f}M" if amt >= 1e6 else f"${amt:,.0f}"
            investors = ", ".join(r.get("investors", [])[:2]) or "—"
            lines.append(
                f"| **{r.get('project', '—')}** | {amt_str} | "
                f"{r.get('category', '—')} | {investors} | {r.get('date', '—')} |"
            )
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


# ── Tools — DeFi & Protocols ─────────────────────────────────────────────────

@mcp.tool(
    name="cometcloud_get_protocols",
    annotations={
        "title": "Protocol Intelligence — CIS-Scored DeFi & RWA Shelf",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_protocols(params: ProtocolsInput) -> str:
    """Retrieve CometCloud's curated protocol universe with CIS scores, live TVL,
    analyst narratives, and selection rationale for each protocol.

    Covers 25 protocols across RWA (Treasuries, Private Credit), DeFi (Lending,
    DEX, Staking, Yield), Derivatives, and Infrastructure. Each protocol includes
    CometCloud's analyst thesis for why it was selected ('why_selected') and
    key strengths ('strengths').

    Args:
        params (ProtocolsInput):
            - category: Filter by category string (optional)
            - min_grade: Minimum CIS grade (optional)
            - sort_by: 'score', 'tvl', or 'change_7d' (default: 'score')
            - response_format: 'json' or 'markdown'

    Returns:
        str: Protocol list with:
        {
          "protocols": [
            {
              "id": str, "name": str, "category": str, "chain": str,
              "cis_score": float, "grade": str, "signal": str,
              "tvl": float, "tvl_formatted": str,
              "tvl_change_7d": float, "tvl_change_30d": float,
              "apy": float, "risk_tier": str,
              "description": str,
              "why_selected": str,        # CometCloud's selection rationale
              "strengths": [str],         # Key investment strengths
              "pillars": {"F": float, ...}
            }
          ]
        }

    Examples:
        - "Show me CometCloud's top RWA protocols" → category="RWA - Treasuries"
        - "What DeFi protocols are rated OUTPERFORM?" → category="DeFi - Lending"
        - "Which protocols have the highest TVL?" → sort_by="tvl"
        - "Why did CometCloud choose Aave?" → use json format, look at why_selected
    """
    try:
        data = await _get("/api/v1/protocols/universe")
        protos = data.get("protocols", [])

        if params.category:
            protos = [p for p in protos if params.category.lower() in p.get("category", "").lower()]
        if params.min_grade:
            protos = [p for p in protos if _above_min_grade(p.get("grade", "F"), params.min_grade)]

        sort_key = {"score": "cis_score", "tvl": "tvl", "change_7d": "tvl_change_7d"}.get(
            params.sort_by, "cis_score"
        )
        protos = sorted(protos, key=lambda p: p.get(sort_key, 0), reverse=True)

        if params.response_format == Fmt.JSON:
            return json.dumps({"count": len(protos), "protocols": protos}, indent=2)

        lines = [
            f"# CometCloud Protocol Intelligence ({len(protos)} protocols)",
            "",
            "| # | Protocol | Category | Grade | TVL | 7D% | Signal |",
            "|---|----------|----------|-------|-----|-----|--------|",
        ]
        for i, p in enumerate(protos, 1):
            tvl_chg = p.get("tvl_change_7d", 0)
            lines.append(
                f"| {i} | **{p.get('name')}** | {p.get('category')} | "
                f"**{p.get('grade')}** | {p.get('tvl_formatted', '—')} | "
                f"{tvl_chg:+.1f}% | {p.get('signal')} |"
            )
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


@mcp.tool(
    name="cometcloud_get_defi_overview",
    annotations={
        "title": "DeFi Overview — Sector Metrics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_defi_overview() -> str:
    """Get the current DeFi sector overview: total TVL, 24H and 7D changes,
    L2 TVL, RWA TVL, and top protocols by TVL.

    Powered by DeFiLlama data via CometCloud's proxy (cached 5 min).

    Returns:
        str: DeFi sector snapshot with total TVL, changes, and breakdown by segment.

    Examples:
        - "What's the total DeFi TVL?" → use this tool
        - "How is the RWA sector trending?" → use this tool
        - "Is DeFi TVL growing or shrinking?" → use this tool
    """
    try:
        data = await _get("/api/v1/defi/overview")
        tvl  = data.get("total_tvl", 0)
        l2   = data.get("l2_tvl", 0)
        rwa  = data.get("rwa_tvl", 0)

        lines = [
            "# DeFi Overview",
            "",
            f"**Total TVL**: ${tvl/1e9:.2f}B",
            f"**24H Change**: {data.get('defi_change_24h', 0):+.2f}%",
            f"**L2 TVL**: ${l2/1e9:.2f}B",
            f"**RWA TVL**: ${rwa/1e9:.2f}B",
        ]

        top = data.get("top_protocols", [])
        if top:
            lines += ["", "## Top Protocols by TVL", "| Protocol | TVL | 24H% |", "|----------|-----|------|"]
            for p in top[:10]:
                pt = p.get("tvl", 0)
                lines.append(
                    f"| {p.get('name')} | ${pt/1e9:.2f}B | {p.get('change_1d', 0):+.2f}% |"
                )
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


@mcp.tool(
    name="cometcloud_get_defi_yields",
    annotations={
        "title": "DeFi Yields — Top Yield Opportunities",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_defi_yields(params: YieldsInput) -> str:
    """Fetch the top DeFi yield opportunities across protocols and chains.

    Returns pools sorted by APY with TVL, protocol, chain, and asset info.
    Useful for identifying yield opportunities that complement CIS-based
    asset allocation.

    Args:
        params (YieldsInput):
            - min_apy: Minimum APY filter (default 0%)
            - limit: Max pools to return (default 20)
            - response_format: 'json' or 'markdown'

    Returns:
        str: Table of yield pools with protocol, asset, chain, APY, and TVL.

    Examples:
        - "Where can I get the best yield on USDC?" → min_apy=0, limit=20
        - "Show high-yield DeFi pools above 10% APY" → min_apy=10
    """
    try:
        data = await _get("/api/v1/defi/yields")
        pools = data.get("pools", data if isinstance(data, list) else [])
        pools = [p for p in pools if p.get("apy", 0) >= params.min_apy]
        pools = sorted(pools, key=lambda p: p.get("apy", 0), reverse=True)
        pools = pools[: params.limit]

        if params.response_format == Fmt.JSON:
            return json.dumps({"count": len(pools), "pools": pools}, indent=2)

        lines = [
            f"# Top DeFi Yields (min APY: {params.min_apy}%)",
            "",
            "| Protocol | Asset | Chain | APY | TVL |",
            "|----------|-------|-------|-----|-----|",
        ]
        for p in pools:
            tvl = p.get("tvlUsd", 0)
            tvl_str = f"${tvl/1e6:.0f}M" if tvl >= 1e6 else f"${tvl:,.0f}"
            lines.append(
                f"| {p.get('project', '—')} | {p.get('symbol', '—')} | "
                f"{p.get('chain', '—')} | **{p.get('apy', 0):.1f}%** | {tvl_str} |"
            )
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


# ── Tools — Fund & Portfolio ─────────────────────────────────────────────────

@mcp.tool(
    name="cometcloud_get_fund_portfolio",
    annotations={
        "title": "Fund Portfolio — CometCloud GP Funds",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_fund_portfolio() -> str:
    """Retrieve CometCloud's curated vault fund portfolio — the roster of GP
    partner funds available through the CometCloud Fund-of-Funds structure.

    Returns verified GP fund profiles including strategy, AUM, performance
    metrics (where available), and CometCloud's composite scoring.

    Returns:
        str: List of GP funds with strategy, location, status, performance, and scores.

    Examples:
        - "What funds are in the CometCloud vault?" → use this tool
        - "Show me the available GP partner funds" → use this tool
        - "What's the performance of the trading funds?" → use this tool
    """
    try:
        data = await _get("/api/v1/vault/funds")
        funds = data.get("funds", data if isinstance(data, list) else [])

        lines = ["# CometCloud GP Fund Portfolio", ""]
        for f in funds:
            perf = f.get("performance", {})
            sc   = f.get("scores", {})
            lines += [
                f"## {f.get('name', '—')}",
                f"**Strategy**: {f.get('strategy', '—')} · "
                f"**Location**: {f.get('location', '—')} · "
                f"**Status**: {f.get('status', '—')}",
                f"**AUM**: {f.get('aum', '—')} · "
                f"**Founded**: {f.get('yearFounded', '—')}",
            ]
            if perf:
                lines.append(
                    f"**YTD**: {perf.get('ytd', 0):+.1f}% · "
                    f"**Max DD**: {perf.get('maxDrawdown', 0):.1f}%"
                )
            if f.get("note"):
                lines.append(f"*{f['note']}*")
            lines.append("")
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


@mcp.tool(
    name="cometcloud_get_portfolio_stats",
    annotations={
        "title": "Portfolio Stats — Risk & Return Analytics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_portfolio_stats(params: PortfolioStatsInput) -> str:
    """Compute portfolio risk/return statistics for a given set of assets and weights.

    Returns expected return, volatility, Sharpe ratio, max drawdown, and
    correlation data for the specified portfolio. Uses CometCloud's CIS scores
    as a quality overlay on top of the statistical output.

    Args:
        params (PortfolioStatsInput):
            - symbols: Comma-separated asset tickers (e.g. 'BTC,ETH,SOL')
            - weights: Optional comma-separated weights summing to 1.0
            - response_format: 'json' or 'markdown'

    Returns:
        str: Portfolio analytics including return, volatility, Sharpe, drawdown,
             and CIS-weighted quality score.

    Examples:
        - "Analyze a 50/30/20 BTC/ETH/SOL portfolio" → symbols="BTC,ETH,SOL", weights="0.5,0.3,0.2"
        - "Equal-weight portfolio stats for top L1s" → symbols="BTC,ETH,SOL,AVAX"
    """
    try:
        body_params: Dict[str, Any] = {"assets": params.symbols}
        if params.weights:
            weight_list = [float(w.strip()) for w in params.weights.split(",")]
            body_params["weights"] = weight_list

        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            resp = await client.post(
                f"{RAILWAY_BASE}/api/v1/portfolio/stats",
                json=body_params,
            )
            resp.raise_for_status()
            data = resp.json()

        if params.response_format == Fmt.JSON:
            return json.dumps(data, indent=2)

        lines = [
            f"# Portfolio Stats — {params.symbols}",
            "",
            f"**Expected Annual Return**: {data.get('expected_return', 0):.2%}",
            f"**Annual Volatility**: {data.get('volatility', 0):.2%}",
            f"**Sharpe Ratio**: {data.get('sharpe_ratio', 0):.2f}",
            f"**Max Drawdown**: {data.get('max_drawdown', 0):.2%}",
            f"**CIS Quality Score**: {data.get('cis_weighted_score', 0):.1f}",
        ]
        return "\n".join(lines)

    except Exception as e:
        return _err(e)


# ── Tools — CIS Deep Report ───────────────────────────────────────────────────

@mcp.tool(
    name="cometcloud_get_cis_report",
    annotations={
        "title": "CIS Asset Report — Full Structured Scorecard",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def cometcloud_get_cis_report(params: CisReportInput) -> str:
    """Generate a complete, structured CIS investment scorecard for a single asset.

    Builds a quantitative report directly from live CIS engine data — no LM Studio,
    no timeout risk. Returns pillar breakdown, signal rationale, trigger thresholds,
    and monitoring metrics in clean markdown.

    Use this tool when asked for a 'CIS report', 'scorecard', 'investment signal',
    or 'analysis' of any asset. For an additional analyst narrative on top of the
    scorecard, pass the output to lmstudio_cis_narrative.

    Args:
        params (CisReportInput):
            - symbol: Ticker (e.g. 'LINK', 'BTC', 'ETH', 'SOL', 'MKR', 'AAPL')

    Returns:
        str: Structured markdown scorecard including:
             - CIS composite score, grade, signal, LAS, confidence
             - 5-pillar breakdown table with ratings and visual bars
             - Price data + 7-day score trend
             - Signal trigger conditions (upgrade / downgrade)
             - Asset-class-specific monitoring metrics
             - Compliance-safe positioning language throughout

    Examples:
        - "Give me a full CIS report on LINK" → symbol="LINK"
        - "Generate a scorecard for SOL" → symbol="SOL"
        - "Analyze BTC's CIS positioning" → symbol="BTC"
    """
    import asyncio
    import datetime

    try:
        # Fetch CIS data + history concurrently
        cis_result, hist_result = await asyncio.gather(
            _get(f"/api/v1/cis/asset/{params.symbol}"),
            _get(f"/api/v1/cis/history/{params.symbol}", {"days": 7}),
            return_exceptions=True,
        )
        data = cis_result if not isinstance(cis_result, Exception) else {}
        hist = hist_result if not isinstance(hist_result, Exception) else {}

        if not data or isinstance(data, dict) and data.get("detail"):
            return f"Error: Asset '{params.symbol}' not found in CIS universe."

        # ── Extract fields ────────────────────────────────────────────────
        symbol      = data.get("symbol", params.symbol)
        name        = data.get("name", symbol)
        asset_class = data.get("asset_class", "—")
        grade       = data.get("grade", "—")
        cis_score   = float(data.get("cis_score", 0))
        signal      = data.get("signal", "NEUTRAL")
        las         = float(data.get("las", 0))
        confidence  = float(data.get("confidence", 0))
        rec_weight  = float(data.get("recommended_weight", 0))
        price       = float(data.get("price", 0))
        market_cap  = float(data.get("market_cap", 0))
        change_24h  = float(data.get("change_24h", 0))
        change_7d   = float(data.get("change_7d", 0))
        macro_regime = data.get("macro_regime", "—")

        # data_tier: API returns int (1/2) or string; normalise to label
        _dt = data.get("data_tier", 2)
        data_tier = "T1_LOCAL" if str(_dt) in ("1", "T1", "T1_LOCAL") else "T2_MARKET"

        # Pillar scores — T2 engine returns lowercase top-level keys (f, m, r, s, a)
        # "r" = risk_adjusted → maps to O (On-chain/Risk) pillar
        # "s" = sensitivity   → maps to S (Sentiment) pillar
        # Also check nested "pillars" dict (T1 engine format) as fallback
        _p  = data.get("pillars", {})
        F   = float(data.get("f") or _p.get("F") or 0)
        M   = float(data.get("m") or _p.get("M") or 0)
        O   = float(data.get("r") or data.get("o") or _p.get("O") or 0)   # r = risk_adjusted
        S   = float(data.get("s") or _p.get("S") or 0)                    # s = sensitivity
        A   = float(data.get("a") or _p.get("A") or 0)

        # Pillar weights — "weights" key in T2, "pillar_weights" in T1
        _pw_default = {"F": 0.30, "M": 0.20, "O": 0.25, "S": 0.10, "A": 0.15}
        pw = data.get("weights") or data.get("pillar_weights") or _pw_default

        # ── Helpers ───────────────────────────────────────────────────────
        def _rating(s: float) -> str:
            if s >= 85: return "Exceptional"
            if s >= 75: return "Strong"
            if s >= 65: return "Above Avg"
            if s >= 55: return "Moderate"
            if s >= 45: return "Below Avg"
            if s >= 35: return "Weak"
            return "Very Weak"

        def _bar(s: float) -> str:
            n = max(0, min(10, round(s / 10)))
            return "█" * n + "░" * (10 - n)

        def _mc(v: float) -> str:
            if v >= 1e12: return f"${v/1e12:.2f}T"
            if v >= 1e9:  return f"${v/1e9:.2f}B"
            if v >= 1e6:  return f"${v/1e6:.0f}M"
            return f"${v:,.0f}"

        # ── 7-day trend ───────────────────────────────────────────────────
        hist_scores: List[float] = []
        if isinstance(hist, dict):
            hist_scores = [h.get("cis_score", 0) for h in hist.get("history", [])]
        trend_str = "—"
        if len(hist_scores) >= 2:
            delta = hist_scores[-1] - hist_scores[0]
            trend_str = f"{'▲' if delta >= 0 else '▼'} {abs(delta):.1f} pts (7d)"

        # ── Signal descriptions (compliance-safe) ─────────────────────────
        SIGNAL_DESC: Dict[str, str] = {
            "STRONG OUTPERFORM": (
                "High-conviction overweight. All major CIS pillars constructive; "
                "composite materially above A-grade threshold. Regime-aligned."
            ),
            "OUTPERFORM": (
                "Positive relative positioning. CIS composite above B+ threshold; "
                "fundamental + momentum support overweight vs. benchmark."
            ),
            "NEUTRAL": (
                "No directional conviction. Mixed pillar signals; CIS composite "
                "in 45–65 range. Monitor for regime shift before increasing exposure."
            ),
            "UNDERPERFORM": (
                "Cautious positioning. Headwinds in ≥2 pillars; CIS composite "
                "below C+ threshold. Reduce relative exposure vs. benchmark."
            ),
            "UNDERWEIGHT": (
                "Defensive positioning. CIS composite materially weak (<35). "
                "Capital preservation priority; avoid new exposure."
            ),
        }

        # F/M/O/S/A already extracted above from top-level fields

        # ── Pillar notes ──────────────────────────────────────────────────
        def _pnote(key: str, score: float, high: str, low: str) -> str:
            tag = "✔" if score >= 60 else "✖" if score < 45 else "~"
            return f"- **{key}** {tag}  {high if score >= 60 else low} *(score: {score:.1f})*"

        pillar_notes = [
            _pnote("F — Fundamental", F,
                   "Value accrual, revenue, or network adoption metrics constructive.",
                   "Fundamental headwinds — revenue, adoption, or balance sheet below threshold."),
            _pnote("M — Momentum", M,
                   "Positive price momentum relative to benchmark; trend and volume aligned.",
                   "Trend below benchmark; near-term velocity weak. Caution on timing."),
            _pnote("O — On-chain / Risk", O,
                   "On-chain health stable — liquidity depth, volatility regime, network metrics nominal.",
                   "On-chain risk elevated — liquidity concerns, high realized vol, or anomalous activity."),
            _pnote("S — Sentiment", S,
                   "Sentiment constructive — Fear & Greed, social indicators, derivatives positioning aligned.",
                   "Sentiment cautious — market fear or speculative positioning creating near-term headwinds."),
            _pnote("A — Alpha", A,
                   "Positive alpha vs. benchmark (BTC/SPY) over 30d; regime-adjusted outperformance.",
                   "Negative alpha vs. benchmark over 30d; underperforming peer group on risk-adjusted basis."),
        ]

        # ── Signal triggers ───────────────────────────────────────────────
        if signal in ("NEUTRAL", "UNDERPERFORM", "UNDERWEIGHT"):
            triggers = [
                "| CIS ≥ 65 | ↑ → OUTPERFORM | Composite recovers to B+ threshold |",
                "| F pillar ≥ 70 | ↑ Fundamental recovery | Revenue/adoption normalises |",
                "| M pillar ≥ 65 | ↑ Momentum confirms | Trend re-establishes above benchmark |",
                "| S pillar ≤ 25 | ↓ Capitulation risk | Extreme fear; watch for distribution |",
                "| CIS ≤ 35 | ↓ → UNDERWEIGHT | C threshold — full defensive posture |",
            ]
        else:
            triggers = [
                "| CIS ≤ 55 | ↓ → NEUTRAL | Composite falls below B threshold |",
                "| M pillar ≤ 45 | ↓ Momentum loss | Trend breaks below benchmark |",
                "| O pillar ≤ 40 | ↓ On-chain risk spike | Liquidity or volatility deterioration |",
                "| F pillar ≥ 85 | ↑ → STRONG OUTPERFORM | Exceptional fundamental conviction |",
                "| CIS ≥ 85 | ↑ → STRONG OUTPERFORM | A+ grade — all pillars aligned |",
            ]

        # ── Asset-class monitoring metrics ────────────────────────────────
        monitoring: Dict[str, List[str]] = {
            "L1": [
                "Active addresses + daily transaction count (F pillar driver)",
                "Protocol revenue and fee burn rate vs. peers",
                "30d price divergence vs. BTC benchmark (A pillar)",
                "Derivatives OI and funding rate (O pillar — leverage risk)",
                "Fear & Greed Index + social volume (S pillar)",
            ],
            "L2": [
                "TVL bridged + sequencer revenue (F pillar)",
                "TPS and gas savings vs. L1 (value proposition)",
                "30d price divergence vs. ETH benchmark (A pillar)",
                "Bridge liquidity and security audit status (O pillar)",
                "Developer activity + deployed contracts",
            ],
            "DeFi": [
                "TVL — absolute level and 7d/30d change (F pillar)",
                "Protocol revenue / fee generation per dollar TVL",
                "Market share vs. sector competitors (A pillar benchmark)",
                "Liquidation health and collateral ratio (O pillar)",
                "Governance activity and token concentration",
            ],
            "RWA": [
                "AUM / TVL growth and weekly inflow trends (F pillar)",
                "Yield spread vs. off-chain equivalent (value proposition)",
                "Regulatory filing status and compliance updates",
                "Issuer credit quality and counterparty exposure (O pillar)",
                "Institutional integration pipeline and redemption flow",
            ],
        }
        default_monitoring = [
            "CIS composite — flag if any pillar moves ±5 pts within a week",
            "F pillar: fundamental quality indicators (revenue, adoption, TVL)",
            "M pillar: 30-day price vs. benchmark divergence",
            "O pillar: liquidity depth and volatility regime",
            "S pillar: Fear & Greed + derivatives positioning",
        ]
        monitor_lines = monitoring.get(asset_class, default_monitoring)

        # ── Assemble report ───────────────────────────────────────────────
        today = datetime.date.today().isoformat()

        lines = [
            f"# {name} ({symbol}) — CIS Investment Scorecard",
            f"*{today} · CometCloud Intelligence System v4.1 · {asset_class} · {data_tier} · Regime: {macro_regime}*",
            "",
            "---",
            "",
            "## 1 · Composite Score",
            "",
            "| CIS Score | Grade | Signal | LAS | Confidence | Rec. Weight |",
            "|-----------|-------|--------|-----|------------|-------------|",
            f"| **{cis_score:.1f} / 100** | **{grade}** | **{signal}** "
            f"| {las:.1f} | {confidence:.0%} | {rec_weight:.1f}% |",
            "",
            f"> **Positioning**: {SIGNAL_DESC.get(signal, signal)}",
            "",
            "---",
            "",
            "## 2 · Pillar Breakdown",
            "",
            "| Pillar | Weight | Score | Visual | Rating |",
            "|--------|--------|-------|--------|--------|",
            f"| F — Fundamental      | {pw.get('F', 0.25):.0%} | {F:.1f} | `{_bar(F)}` | {_rating(F)} |",
            f"| M — Momentum         | {pw.get('M', 0.20):.0%} | {M:.1f} | `{_bar(M)}` | {_rating(M)} |",
            f"| O — On-chain / Risk  | {pw.get('O', 0.20):.0%} | {O:.1f} | `{_bar(O)}` | {_rating(O)} |",
            f"| S — Sentiment        | {pw.get('S', 0.20):.0%} | {S:.1f} | `{_bar(S)}` | {_rating(S)} |",
            f"| A — Alpha            | {pw.get('A', 0.15):.0%} | {A:.1f} | `{_bar(A)}` | {_rating(A)} |",
            "",
            "### Pillar Notes",
            "",
        ] + pillar_notes + [
            "",
            "---",
            "",
            "## 3 · Price & Market Data",
            "",
            "| Price | 24H | 7D | Market Cap | Score Trend |",
            "|-------|-----|----|------------|-------------|",
            f"| **${price:,.4f}** | {change_24h:+.2f}% | {change_7d:+.2f}% "
            f"| {_mc(market_cap)} | {trend_str} |",
            "",
            "---",
            "",
            "## 4 · Signal Trigger Levels",
            "",
            "Conditions that would cause a signal upgrade or downgrade:",
            "",
            "| Condition | Direction | Rationale |",
            "|-----------|-----------|-----------|",
        ] + triggers + [
            "",
            "---",
            "",
            "## 5 · Key Monitoring Metrics",
            "",
            "Track weekly for early signal-change detection:",
            "",
        ] + [f"- {m}" for m in monitor_lines] + [
            "",
            "---",
            "",
            "*CIS v4.1 — Absolute grading: A+≥85 · A≥75 · B+≥65 · B≥55 · C+≥45 · C≥35 · D≥25 · F<25*  ",
            "*Signals are relative positioning language only — not investment advice.*  ",
            "*Valid signals: STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT*",
        ]

        return "\n".join(lines)

    except Exception as e:
        return _err(e)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if MCP_PORT:
        mcp.run(transport="streamable_http", port=MCP_PORT)
    else:
        mcp.run()
