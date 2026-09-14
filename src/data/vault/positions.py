"""Vault positions loader + NAV math. Pure functions, no I/O beyond
a single Supabase read for the positions and a price lookup against the
panel.

`load_positions(vault_id, as_of)` reads the latest (as_of) row per
(vault_id, symbol, side) from `vault_positions`. Returns a list of
dicts the tick layer can turn into NAV.

`mark_positions(positions, prices)` is pure: takes the loaded positions
and a {symbol: price} map, returns:
- per-position value_usd (qty × price × sign(side))
- total nav_usd
- holdings list (the per-position breakdown, ready for the JSONB column)

**No fabrication, no stale-data guessing**: if a position's symbol has no
current price in the panel, the caller BLOCKs. NAV_POLICY §3 carries
forward from fund NAV — a vault NAV without current prices is not a NAV.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def positions_value(positions: list[dict], prices: Mapping[str, float]) -> dict:
    """Pure NAV math.

    Args:
        positions: list of {symbol, qty, side} dicts (as loaded from
                   vault_positions, with the latest-as_of filter applied)
        prices:    {symbol: current_price_usd} map from the panel

    Returns:
        {
          "holdings": [{symbol, qty, side, price, value_usd}, ...],
          "nav_usd":  float,
          "missing_prices": [symbol, ...]   # symbols in positions but not in prices
        }

    The "missing_prices" list is what the caller BLOCKs on. NAV without
    a price is not NAV.
    """
    holdings: list[dict] = []
    missing: list[str] = []
    total = 0.0
    for p in positions:
        sym = str(p.get("symbol") or "")
        if not sym:
            continue
        if sym not in prices:
            missing.append(sym)
            continue
        qty = float(p.get("qty") or 0.0)
        side = str(p.get("side") or "LONG").upper()
        sign = 1.0 if side == "LONG" else -1.0
        price = float(prices[sym])
        value = qty * price * sign
        total += value
        holdings.append({
            "symbol": sym, "qty": qty, "side": side,
            "price": price, "value_usd": round(value, 8),
        })
    return {
        "holdings": holdings,
        "nav_usd": round(total, 8),
        "missing_prices": sorted(set(missing)),
    }


def format_holdings_for_jsonb(holdings: list[dict]) -> list[dict]:
    """JSONB-safe: keys already snake_case, numbers rounded to 8 decimals.
    Kept as a separate function so the math layer doesn't grow a
    persistence concern.
    """
    return holdings  # already JSONB-safe per positions_value()


def load_share_count(state_row: Mapping[str, Any] | None) -> float:
    """Pull share_count from a vault_state row, or fail loud.

    v1 ships WITHOUT a fallback — if share_count is NULL or the row
    doesn't exist, we raise. A vault that mints shares silently is a
    worse failure mode than one that refuses to tick.
    """
    if not state_row:
        raise ValueError("vault_state 查无此 vault_id —— 没有 share_count 不能 tick")
    sc = state_row.get("share_count")
    if sc is None:
        raise ValueError(f"vault_state.share_count = NULL for {state_row.get('vault_id')} "
                         f"—— share_count 必须先 seed,不能 tick 一个不知道发了多少股的 vault")
    sc = float(sc)
    if sc <= 0:
        raise ValueError(f"vault_state.share_count = {sc} for {state_row.get('vault_id')} "
                         f"—— 必须 > 0,nav_per_share 才算得出")
    return sc


__all__ = ["positions_value", "format_holdings_for_jsonb", "load_share_count"]
