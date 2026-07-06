"""
feather → Nautilus ParquetDataCatalog adapter (Minimax-B, 2026-07-04)
======================================================================

Ports Shadow's `cometcloud-local/nautilus_strategies/feather_to_parquet_catalog.py`
into the main repo with env-overridable paths so the same code runs on
the Mac Mini (via /Volumes/CometCloudAI/...) and on a developer's local
checkout (via $NAUTILUS_FEATHER_DIR / $NAUTILUS_CATALOG_DIR).

Idempotent: re-running wipes `instruments/` and `bars/` and rewrites from
the source feathers.  This is intentional — stale rows in the catalog are
the #1 source of "why does my backtest disagree with the freqtrade one"
headaches.

Default inputs (no env) match the freqtrade LS V4 config:
    /Volumes/CometCloudAI/freqtrade/user_data/data/binance/futures/
        {BTC,ETH,SOL}_USDT_USDT-4h-futures.feather

Default output:
    /Volumes/CometCloudAI/cometcloud-local/_data/nautilus_catalog/

Public surface:
    build_catalog(feather_dir=None, catalog_dir=None) -> dict
        Wipe + rewrite.  Returns a small summary dict for the runner.
    CATALOG_DIR, FEATHER_DIR, INSTRUMENTS — module-level defaults
"""

from __future__ import annotations

import logging
import os
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pandas as pd

from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarSpecification
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.model.enums import PriceType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Currency
from nautilus_trader.model.objects import Money
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog


logger = logging.getLogger(__name__)


# ── Defaults (env-overridable) ───────────────────────────────────────────────

FEATHER_DIR = Path(
    os.getenv(
        "NAUTILUS_FEATHER_DIR",
        "/Volumes/CometCloudAI/freqtrade/user_data/data/binance/futures",
    )
)
CATALOG_DIR = Path(
    os.getenv(
        "NAUTILUS_CATALOG_DIR",
        "/Volumes/CometCloudAI/cometcloud-local/_data/nautilus_catalog",
    )
)

# (file_stem, instrument_symbol, price_prec, size_prec)
# These mirror the freqtrade LS V4 config_ls_futures.json instrument list.
INSTRUMENTS = [
    ("BTC_USDT_USDT-4h-futures", "BTCUSDT-PERP", 1, 3),
    ("ETH_USDT_USDT-4h-futures", "ETHUSDT-PERP", 2, 3),
    ("SOL_USDT_USDT-4h-futures", "SOLUSDT-PERP", 3, 3),
]

VENUE = Venue("BINANCE")
BAR_AGG = BarAggregation.HOUR
BAR_PT = PriceType.LAST
BAR_STEP = 4  # 4h

USDT = Currency.from_str("USD")


# ── Instrument + bar builders ────────────────────────────────────────────────

def _currency(symbol: str) -> Currency:
    return Currency.from_str(symbol)


def build_instrument(
    symbol: str, price_prec: int, size_prec: int
) -> CryptoPerpetual:
    """Build a CryptoPerpetual matching Binance USDT-margined futures.

    Fee levels mirror the freqtrade LS V4 config (0.05% taker, 0.02% maker).
    Margin init/maint 5%/2.5% — standard Binance isolated margin.
    """
    base = symbol.replace("USDT-PERP", "")
    price_inc = Price(10 ** -price_prec, price_prec)
    size_inc = Quantity(10 ** -size_prec, size_prec)
    instrument_id = InstrumentId(symbol=Symbol(symbol), venue=VENUE)
    return CryptoPerpetual(
        instrument_id=instrument_id,
        raw_symbol=Symbol(f"{base}USDT"),
        base_currency=_currency(base),
        quote_currency=USDT,
        settlement_currency=USDT,
        is_inverse=False,
        price_precision=price_prec,
        price_increment=price_inc,
        size_precision=size_prec,
        size_increment=size_inc,
        max_quantity=Quantity.from_str("1000.000"),
        min_quantity=Quantity.from_str("0.001"),
        max_notional=None,
        min_notional=Money(10.00, USDT),
        max_price=Price.from_str("1000000.0"),
        min_price=Price.from_str("0.01"),
        margin_init=Decimal("0.0500"),
        margin_maint=Decimal("0.0250"),
        maker_fee=Decimal("0.000200"),
        taker_fee=Decimal("0.000180"),
        ts_event=0,
        ts_init=0,
    )


def build_bars(df: pd.DataFrame, instrument: CryptoPerpetual) -> list[Bar]:
    """Convert dataframe rows to Nautilus Bar objects.

    `date` is tz-aware UTC (freqtrade feather convention); Nautilus
    expects unix nanoseconds for ts_event / ts_init.
    """
    out: list[Bar] = []
    spec = BarSpecification(BAR_STEP, BAR_AGG, BAR_PT)
    bar_type = BarType(instrument.id, spec)
    for row in df.itertuples(index=False):
        ts_ns = int(row.date.value)  # ns precision
        bar = Bar(
            bar_type=bar_type,
            open=Price(round(row.open, instrument.price_precision), instrument.price_precision),
            high=Price(round(row.high, instrument.price_precision), instrument.price_precision),
            low=Price(round(row.low, instrument.price_precision), instrument.price_precision),
            close=Price(round(row.close, instrument.price_precision), instrument.price_precision),
            volume=Quantity(round(row.volume, instrument.size_precision), instrument.size_precision),
            ts_event=ts_ns,
            ts_init=ts_ns,
        )
        out.append(bar)
    return out


# ── Public entry ─────────────────────────────────────────────────────────────

def build_catalog(
    feather_dir: Optional[Path] = None,
    catalog_dir: Optional[Path] = None,
) -> dict:
    """Wipe + rewrite the ParquetDataCatalog from the source feathers.

    Returns a summary dict with per-instrument row counts and the catalog
    path, suitable for the runner to log or write to a JSON report.
    """
    feather_dir = Path(feather_dir) if feather_dir else FEATHER_DIR
    catalog_dir = Path(catalog_dir) if catalog_dir else CATALOG_DIR
    catalog_dir.mkdir(parents=True, exist_ok=True)

    # Idempotent: wipe stale instrument + bar data first
    for sub in ("instruments", "bars"):
        p = catalog_dir / sub
        if p.exists():
            shutil.rmtree(p)

    catalog = ParquetDataCatalog(str(catalog_dir))
    summary = {
        "feather_dir": str(feather_dir),
        "catalog_dir": str(catalog_dir),
        "instruments": {},
    }
    for stem, symbol, price_prec, size_prec in INSTRUMENTS:
        feather_path = feather_dir / f"{stem}.feather"
        if not feather_path.exists():
            logger.warning(f"SKIP {stem}: missing {feather_path}")
            summary["instruments"][symbol] = {"status": "missing", "rows": 0}
            continue
        df = pd.read_feather(feather_path)
        instrument = build_instrument(symbol, price_prec, size_prec)
        catalog.write_data([instrument], data_cls=CryptoPerpetual)
        bars = build_bars(df, instrument)
        catalog.write_data(bars, data_cls=Bar)
        summary["instruments"][symbol] = {
            "status": "ok",
            "rows": len(bars),
            "first": str(df["date"].iloc[0]),
            "last": str(df["date"].iloc[-1]),
        }
        logger.info(
            f"wrote {symbol}: {len(bars)} bars "
            f"({df['date'].iloc[0]} -> {df['date'].iloc[-1]})"
        )
    return summary


# ── Smoke ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json as _json
    out = build_catalog()
    print(_json.dumps(out, indent=2, default=str))
