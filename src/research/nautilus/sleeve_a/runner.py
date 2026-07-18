"""
Nautilus backtest runner for Sleeve A (Seth, 2026-07-17)
========================================================

Runs BacktestNode for each instrument in `INSTRUMENTS` over the same
14mo OOS window as the freqtrade MultiFactorV2 baseline
(2025-01-01 → 2026-03-12, 1h bars, 3 pairs BTC/ETH/SOL perpetuals).

Per MINIMAX_SYNC.md §STRATEGY-REVIVE: Sleeve A is the "durable fundamental
core" of the surviving two-layer book.  This runner is the engine plumbing
that lets Minimax-C do an apples-to-apples parity check of the Nautilus
port against the freqtrade baseline.

Emits STRUCTURED output (JSON + CSV) to a per-run directory so
`parity_check.py` can diff Nautilus vs freqtrade results cleanly.

Output structure for one run (default OUT_DIR/<timestamp>/):
    per_instrument.json      — {instr_id: {n_orders, n_positions, pnl_usd, ...}}
    per_instrument.csv       — flat table, one row per instrument
    summary.json             — totals across all instruments
    skip_summary.json        — strategy-level skip counts (trend, extreme, momentum, ...)
    run_metadata.json        — window, instruments, feature flags, env

Public surface:
    run_parity(start=None, end=None, out_root=None) -> Path
        Top-level: run a parity backtest, return the output directory.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

# Make sibling modules importable when this file is run directly
sys.path.insert(0, str(Path(__file__).parent))

from nautilus_trader.backtest.config import BacktestDataConfig
from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.backtest.config import BacktestRunConfig
from nautilus_trader.backtest.config import BacktestVenueConfig
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.model.data import BarSpecification
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.enums import PriceType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Currency
from nautilus_trader.trading.config import ImportableStrategyConfig

from data_adapter import CATALOG_DIR as RUNNER_CATALOG_DIR  # noqa: E402
from strategy import SleeveAConfig  # noqa: E402


logger = logging.getLogger(__name__)


# ── Defaults ─────────────────────────────────────────────────────────────────

# OOS window — must match the freqtrade MultiFactorV2 baseline per
# PROFITABLE_STRATEGY_REPORT.md (14mo, BTC/ETH/SOL, 1h, 3× lev).
DEFAULT_START = "2025-01-01T00:00:00Z"
DEFAULT_END = "2026-03-12T00:00:00Z"

# Trade size: 5% of equity, 3x leverage (matches freqtrade MultiFactorV2
# config + PROFITABLE_STRATEGY_REPORT 3× lev assumption).
DEFAULT_TRADE_SIZE = Decimal("0.05")
DEFAULT_LEVERAGE = 3.0
DEFAULT_STARTING_BALANCE = "10000 USD"

# Output root — env-overridable for the CI smoke run
OUT_DIR = Path(
    os.getenv(
        "SLEEVE_A_OUT_DIR",
        "/Volumes/CometCloudAI/cometcloud-local/_reports/nautilus/sleeve_a",
    )
)
OUT_DIR.mkdir(parents=True, exist_ok=True)

INSTRUMENTS = [
    "BTCUSDT-PERP.BINANCE",
    "ETHUSDT-PERP.BINANCE",
    "SOLUSDT-PERP.BINANCE",
]

USDT = Currency.from_str("USD")


# ── msgspec config sanitiser ─────────────────────────────────────────────────

def _config_to_dict(cfg) -> dict:
    """Convert Nautilus StrategyConfig (msgspec.Struct) to JSON-safe dict.

    Nautilus types (InstrumentId, BarType, Decimal) are not msgspec-native,
    so we walk msgspec.structs.asdict and stringify the unsupported leaves.
    """
    import msgspec

    def _walk(v):
        if isinstance(v, InstrumentId):
            return str(v)
        if isinstance(v, BarType):
            return str(v)
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, dict):
            return {k: _walk(val) for k, val in v.items()}
        return v

    raw = msgspec.structs.asdict(cfg)
    return {k: _walk(v) for k, v in raw.items()}


# ── BacktestNode configs ─────────────────────────────────────────────────────

def venue_config() -> BacktestVenueConfig:
    return BacktestVenueConfig(
        name="BINANCE",
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        starting_balances=[DEFAULT_STARTING_BALANCE],
        base_currency="USD",
        default_leverage=DEFAULT_LEVERAGE,
    )


def data_config(iid_str: str, start: str, end: str) -> BacktestDataConfig:
    return BacktestDataConfig(
        catalog_path=str(RUNNER_CATALOG_DIR),
        data_cls="nautilus_trader.model.data:Bar",
        instrument_id=iid_str,
        bar_spec="1-HOUR-LAST",
        start_time=start,
        end_time=end,
    )


def strategy_config(iid_str: str, trade_size: Decimal = DEFAULT_TRADE_SIZE) -> SleeveAConfig:
    iid = InstrumentId.from_str(iid_str)
    spec = BarSpecification(1, BarAggregation.HOUR, PriceType.LAST)
    bar_type = BarType(iid, spec)
    return SleeveAConfig(
        instrument_id=iid,
        bar_type=bar_type,
        trade_size=trade_size,
    )


# ── Per-instrument run ──────────────────────────────────────────────────────

def run_one(iid_str: str, start: str, end: str) -> dict:
    cfg = BacktestRunConfig(
        venues=[venue_config()],
        data=[data_config(iid_str, start, end)],
        engine=BacktestEngineConfig(
            strategies=[
                ImportableStrategyConfig(
                    strategy_path="strategy:CometCloudNautilusMultiFactorV2",
                    config_path="strategy:SleeveAConfig",
                    config=_config_to_dict(strategy_config(iid_str)),
                )
            ],
        ),
        start=start,
        end=end,
        raise_exception=True,
        dispose_on_completion=False,
    )
    node = BacktestNode(configs=[cfg])
    results = node.run()
    if not results:
        return {"instrument": iid_str, "n_orders": 0, "n_positions": 0, "error": "no_results"}

    r = results[0]
    pnl_by_ccy = r.stats_pnls or {}
    pnl = {}
    for ccy in ("USD", "USDT", "USDC", "BUSD"):
        if ccy in pnl_by_ccy:
            pnl = pnl_by_ccy[ccy]
            break

    # ── Resolve BacktestEngine (BacktestResult has no `.engine` attr in 1.230) ─
    skip_summary: dict = {}
    n_long = n_short = 0
    eng = None
    try:
        engines = node.get_engines()  # list[BacktestEngine] keyed by run_config_id
        eng = engines[0] if engines else None
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"could not resolve engine from node: {exc}")

    if eng is not None:
        # ── Strategy-level diagnostics (skip counters, regime state) ──────
        try:
            for s in eng.trader.strategies():
                if hasattr(s, "skip_summary"):
                    skip_summary = s.skip_summary()
                    break
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"could not extract skip_summary: {exc}")

        # ── Long vs short entries (from filled orders in the cache) ──────
        # Sleeve A is long-only — we still count so parity_check can verify
        # the long-only invariant holds.
        try:
            from nautilus_trader.model.enums import OrderSide
            from nautilus_trader.model.enums import OrderType
            for o in eng.cache.orders():
                # Only count entry orders (market, not SL).  Entries carry
                # entry_tags set in strategy._enter_long.
                if o.order_type != OrderType.MARKET:
                    continue
                if o.side == OrderSide.BUY:
                    n_long += 1
                elif o.side == OrderSide.SELL:
                    n_short += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"could not extract order sides: {exc}")

        # ── Per-position realised PnL (for downstream Sharpe computation) ─
        positions: list[dict] = []
        try:
            for p in eng.cache.positions():
                try:
                    positions.append({
                        "id": str(p.id),
                        "side": str(p.side),
                        "realized_pnl": float(p.realized_pnl) if p.realized_pnl is not None else 0.0,
                        "realized_return": float(p.realized_return) if p.realized_return is not None else 0.0,
                        "ts_opened": int(p.ts_opened) if p.ts_opened else 0,
                        "ts_closed": int(p.ts_closed) if p.ts_closed else 0,
                    })
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"could not serialise position {p.id}: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"could not extract positions: {exc}")

    # elapsed_time is in nanoseconds per Nautilus convention
    elapsed_sec = float(r.elapsed_time) / 1e9 if r.elapsed_time else 0.0

    return {
        "instrument": iid_str,
        "n_orders": r.total_orders,
        "n_positions": r.total_positions,
        "n_long_entries": n_long,
        "n_short_entries": n_short,
        "stats_pnls_USD": pnl_by_ccy.get("USD", {}),
        "positions": positions,
        "elapsed_sec": round(elapsed_sec, 3),
        "elapsed_ns": int(r.elapsed_time) if r.elapsed_time else 0,
        "iterations": r.iterations,
        "summary": r.summary if r.summary else {},
        "skip_summary": skip_summary,
    }


# ── Top-level: run parity backtest ──────────────────────────────────────────

def run_parity(
    start: Optional[str] = None,
    end: Optional[str] = None,
    out_root: Optional[Path] = None,
) -> Path:
    """Run the parity backtest across all 3 instruments, emit structured
    JSON + CSV.  Returns the output directory.

    Env-overridable:
        SLEEVE_A_START  override default start (2025-01-01T00:00:00Z)
        SLEEVE_A_END    override default end   (2026-03-12T00:00:00Z)
    """
    start = start or os.getenv("SLEEVE_A_START") or DEFAULT_START
    end = end or os.getenv("SLEEVE_A_END") or DEFAULT_END

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_root = Path(out_root) if out_root else OUT_DIR
    run_dir = out_root / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Sleeve A parity backtest starting — window {start} -> {end}")
    logger.info(f"output → {run_dir}")

    rows: list[dict] = []
    skip_summaries: dict[str, dict] = {}
    failed: list[dict] = []

    started = time.monotonic()
    for iid_str in INSTRUMENTS:
        logger.info(f"=== {iid_str} ===")
        t0 = time.monotonic()
        try:
            row = run_one(iid_str, start, end)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"  FAIL: {exc!r}")
            row = {"instrument": iid_str, "error": repr(exc)}
            failed.append(row)
        row["wall_sec"] = round(time.monotonic() - t0, 2)
        rows.append(row)
        if "skip_summary" in row and row["skip_summary"]:
            skip_summaries[iid_str] = row["skip_summary"]
        logger.info(f"  {row}")

    total_wall = round(time.monotonic() - started, 2)

    # ── Write outputs ────────────────────────────────────────────────────
    per_inst_path = run_dir / "per_instrument.json"
    per_inst_path.write_text(json.dumps(rows, indent=2, default=str))

    # CSV — flat per-instrument summary
    csv_path = run_dir / "per_instrument.csv"
    flat_keys = [
        "instrument", "n_orders", "n_positions", "n_long_entries",
        "n_short_entries", "wall_sec", "elapsed_sec", "elapsed_ns",
        "iterations", "error",
    ]
    with csv_path.open("w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=flat_keys, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in flat_keys})

    # Skip summaries (strategy-level diagnostics)
    (run_dir / "skip_summary.json").write_text(
        json.dumps(skip_summaries, indent=2, default=str)
    )

    # Run metadata
    feature_flag_env = {
        "SLEEVE_A_ENABLE_RSI_EXIT": os.getenv("SLEEVE_A_ENABLE_RSI_EXIT", "1"),
        "SLEEVE_A_ENABLE_PRICEPOS_EXIT": os.getenv("SLEEVE_A_ENABLE_PRICEPOS_EXIT", "1"),
    }
    metadata = {
        "engine": "nautilus_trader",
        "strategy": "CometCloudNautilusMultiFactorV2",
        "compliance_tag": "CC_SLEEVE_A_NAUTILUS",
        "window": {"start": start, "end": end},
        "instruments": INSTRUMENTS,
        "timeframe": "1h",
        "trade_size": str(DEFAULT_TRADE_SIZE),
        "leverage": DEFAULT_LEVERAGE,
        "starting_balance": DEFAULT_STARTING_BALANCE,
        "hard_stop_pct": 0.03,
        "max_open_trades": 2,
        "max_daily_trades": 2,
        "cooldown_bars": 15,
        "feature_flags": feature_flag_env,
        "wall_sec_total": total_wall,
        "n_failed": len(failed),
        "n_succeeded": len(rows) - len(failed),
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2, default=str))

    # Top-level summary
    total_pnl = 0.0
    total_orders = 0
    total_positions = 0
    for row in rows:
        if "error" in row:
            continue
        total_orders += row.get("n_orders", 0)
        total_positions += row.get("n_positions", 0)
        pnl_dict = row.get("stats_pnls_USD", {})
        if isinstance(pnl_dict, dict):
            # ONLY sum the "PnL (total)" key — the dict contains other
            # stats (Sharpe, Sortino, Win Rate, etc.) which are NOT dollars.
            pnl_val = pnl_dict.get("PnL (total)")
            if pnl_val is not None:
                try:
                    total_pnl += float(pnl_val)
                except (TypeError, ValueError):
                    pass
    summary = {
        "n_instruments": len(rows),
        "n_orders_total": total_orders,
        "n_positions_total": total_positions,
        "pnl_usd_total": round(total_pnl, 2),
        "wall_sec_total": total_wall,
        "out_dir": str(run_dir),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    logger.info(f"wrote {run_dir}/")
    logger.info(f"  per_instrument.json ({len(rows)} rows)")
    logger.info(f"  per_instrument.csv")
    logger.info(f"  summary.json — {summary}")
    logger.info(f"  skip_summary.json — {len(skip_summaries)} strategies")
    return run_dir


# ── Smoke (CLI) ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out = run_parity()
    print(f"\nSleeve A parity run complete → {out}")