#!/usr/bin/env python3
"""
Build a Nautilus ParquetDataCatalog from the 9-year spot 4h bars
(Minimax-B, 2026-07-15).

This is a STANDALONE version of `src/research/nautilus/ls_v1/data_adapter.py::build_catalog`
that targets the spot feather set in `/Volumes/CometCloudAI/looloomi-research/data/ohlcv/4h-spot/`.

Why not reuse `build_catalog()` directly:
    The default INSTRUMENTS list is hardcoded to the futures feather stems
    (`BTC_USDT_USDT-4h-futures` etc). For the 9-year spot validation we need
    a parallel catalog that points at the spot feathers (`BTC_USDT-4h-spot`).
    Rather than env-poking the production module (which the live-runner
    depends on), this script is a contained reproducer.

NOTE: Spot bars ≠ Perpetual bars. Spot has no funding rate, but the LS v1
signal layer (EMA cross + ADX + CIS gate) doesn't depend on funding
(ENABLE_FUNDING_FILTER=False default). The strategy treats these as
synthetic perpetual bars for backtest purposes. Live trading still uses
real perps.

Output:
    /Volumes/CometCloudAI/looloomi-research/_data/nautilus_catalog_spot/
    (lives on the same Seth/Austin-owned SSD zone — not in
    /Volumes/CometCloudAI/cometcloud-local/)

Usage:
    python3 scripts/build_spot_catalog.py
    # Then run LS v1 with:
    NAUTILUS_CATALOG_DIR=/Volumes/CometCloudAI/looloomi-research/_data/nautilus_catalog_spot \\
        python3 -m src.research.nautilus.ls_v1.runner
"""
from __future__ import annotations

import argparse
import shutil
import sys
from decimal import Decimal
from pathlib import Path

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
from nautilus_trader.persistence.catalog import ParquetDataCatalog


# ── Inlined from ls_v1/data_adapter.py (kept in sync manually) ─────────────
SPOT_FEATHER_DIR = Path(
    "/Volumes/CometCloudAI/looloomi-research/data/ohlcv/4h-spot/"
)
SPOT_CATALOG_DIR = Path(
    "/Volumes/CometCloudAI/looloomi-research/_data/nautilus_catalog_spot/"
)

# (feather_stem, perpetual_symbol, price_prec, size_prec)
# 21 assets: 3 LS v1 baseline + 18 extended for pair-trade cross-section.
# Price precision per Binance spot tick size; size precision to 3 decimals.
SPOT_INSTRUMENTS = [
    # Original 3 (LS v1 baseline + pair-trade core)
    ("BTC_USDT-4h-spot", "BTCUSDT-PERP", 1, 3),
    ("ETH_USDT-4h-spot", "ETHUSDT-PERP", 2, 3),
    ("SOL_USDT-4h-spot", "SOLUSDT-PERP", 3, 3),
    # L1 majors (deep liquidity, long history)
    ("LTC_USDT-4h-spot", "LTCUSDT-PERP", 2, 3),
    ("BNB_USDT-4h-spot", "BNBUSDT-PERP", 2, 3),
    ("XRP_USDT-4h-spot", "XRPUSDT-PERP", 4, 3),
    ("ADA_USDT-4h-spot", "ADAUSDT-PERP", 4, 3),
    ("DOGE_USDT-4h-spot", "DOGEUSDT-PERP", 5, 3),
    ("DOT_USDT-4h-spot", "DOTUSDT-PERP", 3, 3),
    ("LINK_USDT-4h-spot", "LINKUSDT-PERP", 3, 3),
    ("AVAX_USDT-4h-spot", "AVAXUSDT-PERP", 3, 3),
    ("ATOM_USDT-4h-spot", "ATOMUSDT-PERP", 3, 3),
    ("NEAR_USDT-4h-spot", "NEARUSDT-PERP", 3, 3),
    # L2 / DeFi (regime-orthogonal vol)
    ("MATIC_USDT-4h-spot", "MATICUSDT-PERP", 4, 3),
    ("UNI_USDT-4h-spot", "UNIUSDT-PERP", 3, 3),
    ("AAVE_USDT-4h-spot", "AAVEUSDT-PERP", 2, 3),
    ("MKR_USDT-4h-spot", "MKRUSDT-PERP", 1, 3),
    # Newer L1 / L2 (shorter history but regime coverage)
    ("APT_USDT-4h-spot", "APTUSDT-PERP", 3, 3),
    ("ARB_USDT-4h-spot", "ARBUSDT-PERP", 4, 3),
    ("OP_USDT-4h-spot", "OPUSDT-PERP", 4, 3),
    ("SUI_USDT-4h-spot", "SUIUSDT-PERP", 4, 3),
]

VENUE = Venue("BINANCE")
USDT = Currency.from_str("USD")


def build_instrument(symbol: str, price_prec: int, size_prec: int) -> CryptoPerpetual:
    """Same shape as freqtrade LS V4 + ls_v1/data_adapter.py — keep in sync."""
    base = symbol.replace("USDT-PERP", "")
    price_inc = Price(10 ** -price_prec, price_prec)
    size_inc = Quantity(10 ** -size_prec, size_prec)
    instrument_id = InstrumentId(symbol=Symbol(symbol), venue=VENUE)
    return CryptoPerpetual(
        instrument_id=instrument_id,
        raw_symbol=Symbol(f"{base}USDT"),
        base_currency=Currency.from_str(base),
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
    """Build Nautilus Bar objects from a 4h dataframe.

    Mirrors `ls_v1/data_adapter.py::build_bars` — positional BarType(id, spec)
    is the API on Nautilus 1.229 (the keyword form changed in later versions).
    """
    out: list[Bar] = []
    spec = BarSpecification(4, BarAggregation.HOUR, PriceType.LAST)
    bar_type = BarType(instrument.id, spec)
    for row in df.itertuples(index=False):
        # ts is already ns precision (pandas Timestamp.value is nanoseconds since epoch UTC)
        ts_ns = int(row.date.value)
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


def main() -> int:
    SPOT_FEATHER_DIR.mkdir(parents=True, exist_ok=True)
    SPOT_CATALOG_DIR.mkdir(parents=True, exist_ok=True)

    # Idempotent wipe
    for sub in ("instruments", "bars"):
        p = SPOT_CATALOG_DIR / sub
        if p.exists():
            shutil.rmtree(p)

    catalog = ParquetDataCatalog(str(SPOT_CATALOG_DIR))
    summary = {"feather_dir": str(SPOT_FEATHER_DIR),
               "catalog_dir": str(SPOT_CATALOG_DIR),
               "instruments": {}}

    for stem, symbol, price_prec, size_prec in SPOT_INSTRUMENTS:
        feather_path = SPOT_FEATHER_DIR / f"{stem}.feather"
        if not feather_path.exists():
            print(f"SKIP {stem}: missing {feather_path}", file=sys.stderr)
            summary["instruments"][symbol] = {"status": "missing", "rows": 0}
            continue
        df = pd.read_feather(feather_path)
        instrument = build_instrument(symbol, price_prec, size_prec)
        catalog.write_data([instrument], data_cls=CryptoPerpetual)
        bars = build_bars(df, instrument)
        catalog.write_data(bars, data_cls=Bar)
        summary["instruments"][symbol] = {
            "rows": len(bars),
            "first": str(df["date"].min()),
            "last": str(df["date"].max()),
        }
        print(f"  {symbol}: {len(bars):,} bars  "
              f"{df['date'].min().date()} → {df['date'].max().date()}")

    print(f"\nwrote catalog → {SPOT_CATALOG_DIR}")
    print("Use NAUTILUS_CATALOG_DIR=.../nautilus_catalog_spot/ to point the runner at it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())