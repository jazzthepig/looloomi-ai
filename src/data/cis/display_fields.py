"""
Display-field corrections for the CIS universe surface (2026-10-28).

The Mac engine's TradFi rows carry two size fields that are wrong for display:
  - `volume_24h` is the EODHD session volume in SHARES, rendered on the page as dollars
    (SPY showed "$28.6M"; the dollar volume is ~$22B).
  - `market_cap` for single stocks is stale (NVDA "$554B", AAPL "$416B"; actual ≈ $5T each).

Neither field feeds the official score the page shows (that comes from `cis_official_daily`), so this
fixes the surface only: dollar volume = shares × price; single-stock market cap = shares outstanding
(our own `world50_mcap_weekly`, filed share counts) × price. The engine-side fix is Minimax's lane and
is raised in MINIMAX_SYNC; the reported values are kept beside the corrected ones.
"""
from __future__ import annotations

import time
from typing import Any, Optional

TRADFI_CLASSES = {"US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity",
                  "TradFi", "ETF", "Equity", "Bond"}
# Class labels the engine gets wrong. FXI is the iShares China Large-Cap ETF — an equity fund, not FX.
CLASS_OVERRIDES = {"FXI": "EM Equity"}

_SHARES: dict[str, Any] = {"at": 0.0, "map": {}}
_SHARES_TTL_S = 6 * 3600


def apply_size_fix(rows: list[dict], shares: dict[str, float]) -> int:
    """Correct TradFi volume / market cap / class in place. Returns the number of rows touched."""
    n = 0
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").upper()
        if sym in CLASS_OVERRIDES and r.get("asset_class") != CLASS_OVERRIDES[sym]:
            r["asset_class_reported"] = r.get("asset_class")
            r["asset_class"] = CLASS_OVERRIDES[sym]
        if r.get("asset_class") not in TRADFI_CLASSES:
            continue
        try:
            px = float(r.get("price") or 0)
        except (TypeError, ValueError):
            px = 0.0
        if px <= 0:
            continue
        touched = False
        vol = r.get("volume_24h")
        if vol and r.get("volume_basis") is None:
            r["volume_24h_shares"] = vol
            r["volume_24h"] = round(float(vol) * px, 0)
            r["volume_basis"] = "shares×price"
            touched = True
        sh = shares.get(sym)
        if sh:
            r["market_cap_reported"] = r.get("market_cap")
            r["market_cap"] = round(float(sh) * px, 0)
            r["market_cap_basis"] = "shares_outstanding×price"
            touched = True
        elif r.get("market_cap") is not None:
            r.setdefault("market_cap_basis", "as_reported")
        n += int(touched)
    return n


async def _load_shares() -> dict[str, float]:
    if _SHARES["map"] and time.time() - _SHARES["at"] < _SHARES_TTL_S:
        return _SHARES["map"]
    from src.data.vector.market_state_writer import _sb_get
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 21 * 86400))
    rd = await _sb_get("world50_mcap_weekly", {"select": "key,d,shares", "shares": "gt.0",
                                               "d": f"gte.{since}", "order": "d.desc", "limit": "2000"})
    if not rd.ok:
        return _SHARES["map"]          # keep the last good map; an empty one just means "as reported"
    m: dict[str, float] = {}
    for row in rd.rows or []:
        k = str(row.get("key") or "").upper()
        if k and k not in m and row.get("shares"):
            m[k] = float(row["shares"])
    _SHARES.update({"at": time.time(), "map": m})
    return m


async def fix_universe_display(payload: Optional[dict]) -> Optional[dict]:
    """Best effort: never raises, never blocks the universe response on this."""
    try:
        if isinstance(payload, dict) and payload.get("universe"):
            apply_size_fix(payload["universe"], await _load_shares())
    except Exception:
        pass
    return payload
