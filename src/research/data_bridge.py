"""
Nautilus data bridge — read OHLCV parquet → resample 1h→4h → nautilus Bars.

Source:
  See ``src/research/paths.py::OHLCV_DIR`` (default
  ``/Volumes/CometCloudAI/data/ohlcv/{SYMBOL}.parquet``).
  Schema: [timestamp (datetime64[ms, UTC]), open, high, low, close, volume]

Output:
  list[Bar] for a given instrument, optionally resampled to 4h, optionally
  filtered to a [start, end] date range.

Pair conventions (mirror freqtrade futures config):
  Symbol on disk:    "BTC"
  Nautilus id:       "BTCUSDT.BINANCE"
  Freqtrade pair:    "BTC/USDT:USDT"
  Bar spec:          4h, EXTERNAL, LAST
  Fee:               0.0005 (taker, from freqtrade config_ls_futures.json)
"""

import datetime as dt
import logging
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model.data import (
    Bar, BarAggregation, BarSpecification, BarType,
)
from nautilus_trader.model.enums import AggregationSource, PriceType
from nautilus_trader.model.instruments import CryptoPerpetual

from src.research.paths import OHLCV_DIR

logger = logging.getLogger(__name__)


def load_1h_parquet(symbol: str) -> pd.DataFrame:
    """Load 1h OHLCV from parquet. Ensures timestamp is UTC-aware."""
    path = OHLCV_DIR / f"{symbol}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"OHLCV parquet not found: {path}")
    df = pd.read_parquet(path)
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def resample_to_4h(df: pd.DataFrame) -> pd.DataFrame:
    """Resample 1h bars to 4h. Use first open, max high, min low, last close,
    sum volume. Align to 4h boundaries (00, 04, 08, 12, 16, 20 UTC).
    """
    df = df.set_index("timestamp")
    agg = df.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })
    # Drop any rows where open is NaN (no source bars in that bucket)
    agg = agg.dropna(subset=["open"]).reset_index()
    return agg


def filter_timerange(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Filter df to [start, end] inclusive of start, exclusive of end."""
    s = pd.Timestamp(start, tz="UTC")
    e = pd.Timestamp(end, tz="UTC")
    return df[(df["timestamp"] >= s) & (df["timestamp"] < e)].reset_index(drop=True)


def make_perp_instrument(symbol: str, price_prec: int = 2, size_prec: int = 3,
                         taker_fee: float = 0.0005) -> CryptoPerpetual:
    """Build a CryptoPerpetual instrument matching freqtrade futures config.

    Binance USDT-margined perpetual. Price precision defaults to 2 (BTC/ETH/SOL)
    but should be set per-asset. Use TestInstrumentProvider or override.
    """
    inst_id = InstrumentId_from_symbol(symbol)
    return CryptoPerpetual(
        instrument_id=inst_id,
        raw_symbol=Symbol(symbol),
        base_currency=base_ccy_for(symbol),
        quote_currency=USDT,
        settlement_currency=USDT,
        is_inverse=False,
        price_precision=price_prec,
        size_precision=size_prec,
        price_increment=Price.from_str(str(10 ** -price_prec)),
        size_increment=Quantity.from_str(str(10 ** -size_prec)),
        taker_fee=Decimal(str(taker_fee)),
        maker_fee=Decimal(str(taker_fee)),
        ts_event=dt_to_unix_nanos(dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)),
        ts_init=dt_to_unix_nanos(dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)),
    )


def bars_from_df(instrument: CryptoPerpetual, df: pd.DataFrame,
                 bar_spec_step: int = 4, bar_agg: BarAggregation = BarAggregation.HOUR) -> list[Bar]:
    """Build nautilus Bar list from a 4h (or any-step) OHLCV DataFrame.

    bar_spec_step × bar_agg must match the actual timeframe of df.
    For 4h bars: bar_spec_step=4, bar_agg=BarAggregation.HOUR.
    For 1h bars: bar_spec_step=1, bar_agg=BarAggregation.HOUR.
    """
    bar_type = BarType(
        instrument_id=instrument.id,
        bar_spec=BarSpecification(bar_spec_step, bar_agg, PriceType.LAST),
        aggregation_source=AggregationSource.EXTERNAL,
    )
    bars: list[Bar] = []
    for _, row in df.iterrows():
        ts = row["timestamp"].to_pydatetime()
        ts_ns = dt_to_unix_nanos(ts)
        try:
            bars.append(Bar(
                bar_type=bar_type,
                open=instrument.make_price(float(row["open"])),
                high=instrument.make_price(float(row["high"])),
                low=instrument.make_price(float(row["low"])),
                close=instrument.make_price(float(row["close"])),
                volume=instrument.make_qty(float(row["volume"])),
                ts_event=ts_ns,
                ts_init=ts_ns,
            ))
        except Exception as exc:
            logger.warning(f"skip bad bar at {ts}: {exc}")
            continue
    return bars


# ── Helpers (lazy imports to avoid cycles) ───────────────────────────────────
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.currencies import BTC, ETH, SOL, BNB, XRP, USDT, Currency
from nautilus_trader.model.objects import Price, Quantity

# Pre-instantiated base currencies for the 5 majors (avoid Currency.from_str()
# overhead for hot-path symbols). Other symbols are constructed on demand via
# `base_ccy_for()`, which falls back to Currency.from_str() for the long tail
# of altcoins. The currency registry is global in nautilus, so the same
# symbol always returns the same Currency object.
_BASE_CCY_KNOWN = {"BTC": BTC, "ETH": ETH, "SOL": SOL, "BNB": BNB, "XRP": XRP}

# Per-asset precision (Binance USDT-margined perp contract specs). This is the
# single source of truth — `universe.py` re-exports these by reference so the
# two dicts are literally the same object.
PRICE_PRECISION: dict[str, int] = {
    "BTC": 1,   "ETH": 2,   "SOL": 3,   "BNB": 2,   "XRP": 4,
    "ADA": 4,   "AVAX": 3,  "LINK": 3,  "DOGE": 5,  "DOT": 3,
    "ATOM": 3,  "LTC": 2,   "NEAR": 3,  "APT": 3,   "ARB": 4,
    "OP": 4,    "INJ": 3,   "SUI": 4,   "TIA": 4,   "UNI": 3,
}

SIZE_PRECISION: dict[str, int] = {
    "BTC": 3,   "ETH": 3,   "SOL": 0,   "BNB": 2,   "XRP": 1,
    "ADA": 0,   "AVAX": 0,  "LINK": 1,  "DOGE": 0,  "DOT": 1,
    "ATOM": 1,  "LTC": 2,   "NEAR": 0,  "APT": 1,   "ARB": 1,
    "OP": 1,    "INJ": 1,   "SUI": 1,   "TIA": 1,   "UNI": 1,
}

# Backward-compat alias for legacy code that referenced BASE_CCY.
BASE_CCY = _BASE_CCY_KNOWN


def InstrumentId_from_symbol(symbol: str) -> InstrumentId:
    return InstrumentId(symbol=Symbol(f"{symbol}USDT"), venue=Venue("BINANCE"))


def base_ccy_for(symbol: str):
    """Return the Currency object for a Binance perp base symbol.

    Uses a pre-instantiated cache for the 5 majors and Currency.from_str()
    for the long tail (ADA, AVAX, LINK, DOGE, DOT, ATOM, LTC, NEAR, APT,
    ARB, OP, INJ, SUI, TIA, UNI, etc.).
    """
    ccy = _BASE_CCY_KNOWN.get(symbol)
    if ccy is not None:
        return ccy
    return Currency.from_str(symbol)


def build_instrument(symbol: str, taker_fee: float = 0.0005) -> CryptoPerpetual:
    """Factory: build a perp instrument matching Binance contract specs.

    Precision is sourced from `src.research.universe.PRICE_PRECISION /
    SIZE_PRECISION` so updates to those tables flow through automatically.
    """
    inst_id = InstrumentId_from_symbol(symbol)
    pp = PRICE_PRECISION.get(symbol, 2)
    sp = SIZE_PRECISION.get(symbol, 3)
    return CryptoPerpetual(
        instrument_id=inst_id,
        raw_symbol=Symbol(f"{symbol}USDT"),
        base_currency=base_ccy_for(symbol),
        quote_currency=USDT,
        settlement_currency=USDT,
        is_inverse=False,
        price_precision=pp,
        size_precision=sp,
        price_increment=Price.from_str(f"{10 ** -pp:.10f}".rstrip("0").rstrip(".") or "0.1"),
        size_increment=Quantity.from_str(f"{10 ** -sp:.10f}".rstrip("0").rstrip(".") or "0.001"),
        taker_fee=Decimal(str(taker_fee)),
        maker_fee=Decimal(str(taker_fee)),
        ts_event=0,
        ts_init=0,
    )


# ── Pre-computed Wilder ADX / EMAs / ATR (per 4h bar) ───────────────────────
# Indicator math lives in `src.research.indicators` so it can be imported by
# `universe.py` without creating a circular import with data_bridge. We
# re-export the function here for backward-compat with existing callers.
from src.research.indicators import precompute_indicators  # noqa: E402,F401


# ── Quick smoke test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sym = "BTC"
    print(f"=== Loading {sym} ===")
    df1h = load_1h_parquet(sym)
    print(f"1h rows: {len(df1h)}, ts: {df1h.iloc[0]['timestamp']} → {df1h.iloc[-1]['timestamp']}")

    df4h = resample_to_4h(df1h)
    print(f"4h rows: {len(df4h)}, ts: {df4h.iloc[0]['timestamp']} → {df4h.iloc[-1]['timestamp']}")

    df4h = filter_timerange(df4h, "2025-05-03", "2026-03-12")
    print(f"4h in timerange: {len(df4h)}")

    df4h = precompute_indicators(df4h)
    print(f"with indicators: cols={df4h.columns.tolist()}")
    print(df4h[["timestamp", "close", "adx_14", "ema_9", "ema_21", "atr", "rsi"]].tail(5))

    print("\n=== Building instrument ===")
    inst = build_instrument(sym)
    print(f"instrument id: {inst.id}, price_prec: {inst.price_precision}, size_prec: {inst.size_precision}")
    p = inst.make_price(50000.123); print(f"make_price(50000.123): {p}")
    q = inst.make_qty(0.001); print(f"make_qty(0.001): {q}")

    print("\n=== Building bars ===")
    bars = bars_from_df(inst, df4h)
    print(f"bars: {len(bars)}")
    print(f"first bar: {bars[0]}")
    print(f"last bar: {bars[-1]}")