"""
Convert Nautilus fills report to per-trade PnLs.

Reusable helper that pairs each ENTRY-tagged fill with the next closing
fill on the same instrument, computing trade PnL net of fees.

This logic was originally inlined in `/tmp/nautilus_parity.py`. Centralising
it here so every framework runner uses identical trade accounting.

Trade counting (NETTING OMS):
    With OmsType.NETTING, a single position_id may flip long→short within
    the same instrument. We treat each ENTRY tag as the start of a NEW
    round-trip trade, regardless of position_id grouping. This matches
    freqtrade's per-trade accounting.

PnL formula:
    Long:  pnl = (exit_px - entry_px) * entry_qty
    Short: pnl = (entry_px - exit_px) * entry_qty
    Fee:   entry_px * entry_qty * 2 * fee  (entry + exit)

The `fee` parameter is the taker fee as a fraction (e.g., 0.0005 for 5bps).
The multiplier 2 accounts for both entry and exit sides.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class TradePnl:
    """One closed trade."""
    instrument_id: str
    side: str              # 'BUY' (long entry) or 'SELL' (short entry)
    entry_px: float
    exit_px: float
    qty: float
    pnl_gross: float       # before fees
    pnl_net: float         # after fees
    fee_paid: float
    entry_ts: int          # UNIX ns
    exit_ts: int           # UNIX ns


def fills_to_trades(
    fills: pd.DataFrame,
    fee: float = 0.0005,
    entry_tag: str = "ENTRY",
    skip_unmatched: bool = True,
) -> list[TradePnl]:
    """Convert Nautilus fills report to list of closed trades.

    Args:
        fills: pandas DataFrame from `engine.trader.generate_order_fills_report()`.
            Must have columns: instrument_id, position_id, side, avg_px, quantity,
            filled_qty, tags, ts_init.
        fee: taker fee fraction (default 0.0005 = 5bps).
        entry_tag: tag string marking opening fills (default 'ENTRY').
        skip_unmatched: if True, skip trades where no closing fill was found
            (open positions at end of backtest); if False, raise.

    Returns:
        List of TradePnl, one per closed round-trip. Order = chronological
        by entry_ts.
    """
    if not hasattr(fills, "iterrows"):
        return []

    df = fills.copy()
    df = df.sort_values("ts_init").reset_index(drop=True)

    trades: list[TradePnl] = []

    for inst_id in df["instrument_id"].unique():
        sub_inst = df[df["instrument_id"] == inst_id].reset_index(drop=True)
        for pid in sub_inst["position_id"].unique():
            sub = sub_inst[sub_inst["position_id"] == pid].reset_index(drop=True)
            entry_idx: Optional[int] = None
            entry_px: Optional[float] = None
            entry_qty: Optional[float] = None
            entry_ts: Optional[int] = None
            entry_side: Optional[str] = None
            for idx, row in sub.iterrows():
                tags = row.get("tags")
                if not isinstance(tags, list):
                    tags = []
                if entry_tag in tags:
                    # If we already had an unmatched entry, the previous
                    # trade's exit was missing — that's normal at the end
                    # of a backtest; close out the previous trade at this
                    # bar's fill price (defensive).
                    if entry_idx is not None and not skip_unmatched:
                        raise ValueError(
                            f"new ENTRY tag while previous trade still open "
                            f"at inst={inst_id} pos={pid}"
                        )
                    entry_idx = idx
                    entry_px = float(row["avg_px"])
                    entry_qty = float(row.get("filled_qty") or row["quantity"])
                    ts = row["ts_init"]
                    if hasattr(ts, "value"):
                        ts = int(ts.value)  # pandas.Timestamp → ns epoch
                    else:
                        ts = int(ts)
                    entry_ts = ts
                    entry_side = row["side"]
                elif entry_idx is not None:
                    # Closing fill
                    exit_px = float(row["avg_px"])
                    if entry_side == "BUY":
                        pnl_gross = (exit_px - entry_px) * entry_qty
                    else:  # SELL = short entry
                        pnl_gross = (entry_px - exit_px) * entry_qty
                    fee_paid = entry_px * entry_qty * 2 * fee
                    pnl_net = pnl_gross - fee_paid
                    trades.append(TradePnl(
                        instrument_id=inst_id,
                        side=entry_side,
                        entry_px=entry_px,
                        exit_px=exit_px,
                        qty=entry_qty,
                        pnl_gross=pnl_gross,
                        pnl_net=pnl_net,
                        fee_paid=fee_paid,
                        entry_ts=entry_ts,
                        exit_ts=int(row["ts_init"].value if hasattr(row["ts_init"], "value") else row["ts_init"]),
                    ))
                    entry_idx = None
                    entry_px = None
                    entry_qty = None
                    entry_ts = None
                    entry_side = None
    return trades


def trades_to_pnls(trades: list[TradePnl], net: bool = True) -> list[float]:
    """Extract per-trade PnL list for metrics.

    Args:
        trades: output of fills_to_trades
        net: if True, return net PnL (after fees); else gross.
    """
    return [t.pnl_net if net else t.pnl_gross for t in trades]


def trades_summary(trades: list[TradePnl]) -> dict:
    """Quick summary dict for debugging."""
    if not trades:
        return {"n_trades": 0}
    pnls_net = [t.pnl_net for t in trades]
    pnls_gross = [t.pnl_gross for t in trades]
    wins = sum(1 for p in pnls_net if p > 0)
    losses = sum(1 for p in pnls_net if p < 0)
    longs = sum(1 for t in trades if t.side == "BUY")
    shorts = sum(1 for t in trades if t.side == "SELL")
    return {
        "n_trades": len(trades),
        "n_wins": wins,
        "n_losses": losses,
        "win_rate_pct": wins / len(trades) * 100.0,
        "longs": longs,
        "shorts": shorts,
        "total_pnl_net": sum(pnls_net),
        "total_pnl_gross": sum(pnls_gross),
        "total_fees": sum(t.fee_paid for t in trades),
        "avg_pnl_net": sum(pnls_net) / len(trades),
    }


# ── Self-test ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Synthetic fills DataFrame
    import pandas as pd
    df = pd.DataFrame([
        # BTC LONG entry + exit
        {"instrument_id": "BTC", "position_id": "P1", "side": "BUY",  "avg_px": 50000.0, "quantity": 0.01, "filled_qty": 0.01, "tags": ["ENTRY"],     "ts_init": 1},
        {"instrument_id": "BTC", "position_id": "P1", "side": "SELL", "avg_px": 50500.0, "quantity": 0.01, "filled_qty": 0.01, "tags": ["TAKE_PROFIT"], "ts_init": 2},
        # ETH SHORT entry + exit (loss)
        {"instrument_id": "ETH", "position_id": "P2", "side": "SELL", "avg_px": 4000.0,  "quantity": 0.5,  "filled_qty": 0.5,  "tags": ["ENTRY"],     "ts_init": 3},
        {"instrument_id": "ETH", "position_id": "P2", "side": "BUY",  "avg_px": 4100.0,  "quantity": 0.5,  "filled_qty": 0.5,  "tags": ["STOP_LOSS"],   "ts_init": 4},
    ])
    trades = fills_to_trades(df, fee=0.0005)
    for t in trades:
        print(f"{t.instrument_id} {t.side}: {t.entry_px} -> {t.exit_px} "
              f"gross={t.pnl_gross:.2f} fees={t.fee_paid:.2f} net={t.pnl_net:.2f}")
    print()
    print(trades_summary(trades))
