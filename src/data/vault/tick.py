"""`tick_vault_nav()` — one vault, one tick.

The force-tick primitive. Pure function + I/O wrapper. No scheduling,
no cron — callers invoke it and read the result. That's the whole point:
the validation loop is "force-tick → curl reads result → adjust → force-tick",
not "deploy → wait 24h → see if a mark appeared".

Flow:
  1. Read latest positions per (vault_id, symbol, side) from vault_positions
  2. Read share_count from vault_state
  3. Read current prices from panel (binance_hist / coingecko_pro_ohlc)
  4. Compute NAV via positions_value()
  5. BLOCK if any symbol has no current price (NAV_POLICY §3 carries forward)
  6. If dry_run=False: write to vault_nav_tick via insert_with_detail
  7. Update loop_beat last_ok_at (liveness)
  8. Return the full diagnostic

**On ETH mainnet integration**: when alchemy/infura wiring lands, replace
step 1 with a live on-chain read. The signature does NOT change — the
rest of the system consumes the same diagnostic shape.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from src.data.vault.positions import positions_value, load_share_count


async def _load_positions(vault_id: str) -> list[dict]:
    """Latest (as_of) per (vault_id, symbol, side) from vault_positions.

    Uses supabase rpc_with_detail for read-path honesty (S-323m) — same
    pattern the rest of the project adopted for read-side errors.
    """
    from src.api.rpc_diagnostics import rpc_with_detail
    # PostgREST doesn't have DISTINCT ON, so we read all and dedupe in code.
    # For v1 (low position count per vault) this is fine; for production
    # scale (>1000 rows) swap for a server-side view.
    _rows, detail = await rpc_with_detail(
        "vault_positions",
        {})  # placeholder; we use a direct select instead
    # Fall through to a direct select via httpx for honesty
    import httpx
    from src.api.store import _SB_KEY, _SB_URL
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"{_SB_URL}/rest/v1/vault_positions?vault_id=eq.{vault_id}"
            f"&order=as_of.desc&limit=200",
            headers={"apikey": _SB_KEY,
                     "Authorization": f"Bearer {_SB_KEY}",
                     "Accept": "application/json"})
    if r.status_code == 404:
        raise LookupError(f"vault_positions 表不存在 (404) —— "
                          f"先跑 migrations/2026-09-14_vault_nav_tick.sql")
    if r.status_code != 200:
        raise RuntimeError(f"vault_positions 读失败 {r.status_code}: {r.text[:200]}")
    rows = r.json()
    # Dedupe: keep latest as_of per (symbol, side)
    seen: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (str(row.get("symbol") or ""), str(row.get("side") or ""))
        if key not in seen:
            seen[key] = row
    return [{"symbol": r["symbol"], "qty": r["qty"], "side": r["side"]}
            for r in seen.values() if r.get("symbol")]


async def _load_state(vault_id: str) -> dict | None:
    """vault_state row for this vault_id. None if not found."""
    import httpx
    from src.api.store import _SB_KEY, _SB_URL
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"{_SB_URL}/rest/v1/vault_state?vault_id=eq.{vault_id}&limit=1",
            headers={"apikey": _SB_KEY,
                     "Authorization": f"Bearer {_SB_KEY}",
                     "Accept": "application/json"})
    if r.status_code == 404:
        raise LookupError(f"vault_state 表不存在 (404) —— "
                          f"先跑 migrations/2026-09-14_vault_nav_tick.sql")
    if r.status_code != 200:
        raise RuntimeError(f"vault_state 读失败 {r.status_code}: {r.text[:200]}")
    rows = r.json()
    return rows[0] if rows else None


async def _load_prices(symbols: list[str]) -> dict[str, float]:
    """Read current prices from the panel for the given symbols.

    v1: simple binance_hist lookup via supabase_ohlcv_daily.
    Future: add coingecko fallback, hyperliquid for perps, etc.

    BLOCK if any symbol has no current price — DO NOT fabricate.
    """
    from datetime import date, timedelta
    import httpx
    from src.api.store import _SB_KEY, _SB_URL

    prices: dict[str, float] = {}
    missing: list[str] = []
    # Pull last 7 days of binance_hist close per symbol, take the most recent.
    today = date.today()
    seven_days_ago = (today - timedelta(days=7)).isoformat()

    async with httpx.AsyncClient(timeout=20) as c:
        for sym in symbols:
            try:
                r = await c.get(
                    f"{_SB_URL}/rest/v1/ohlcv_daily"
                    f"?source=eq.binance_hist&symbol=eq.{sym}"
                    f"&trade_date=gte.{seven_days_ago}"
                    f"&order=trade_date.desc&limit=1&select=close",
                    headers={"apikey": _SB_KEY,
                             "Authorization": f"Bearer {_SB_KEY}",
                             "Accept": "application/json"})
                if r.status_code == 404:
                    missing.append(sym)
                    continue
                if r.status_code != 200:
                    missing.append(sym)
                    continue
                rows = r.json()
                if not rows or rows[0].get("close") is None:
                    missing.append(sym)
                    continue
                prices[sym] = float(rows[0]["close"])
            except Exception:                                    # noqa: BLE001
                missing.append(sym)
    if missing:
        raise LookupError(f"价格拿不到 symbols={missing} —— "
                          f"vault NAV 不能在缺价时伪造 (NAV_POLICY §3)")
    return prices


async def tick_vault_nav(vault_id: str, *, dry_run: bool = False,
                          source: str = "manual") -> dict:
    """Force-tick one vault. Returns full diagnostic.

    Args:
        vault_id: vault slug (matches vault_state.vault_id)
        dry_run:  if True, compute and return NAV but DON'T write to
                  vault_nav_tick. Used for /internal/book-dryrun-style
                  validation. Default False = real write.
        source:   "manual" (force-tick) or "loop" (scheduled tick).
                  Written into vault_nav_tick.source column.

    Returns:
        {
          "ok": bool,
          "vault_id": str,
          "nav_usd": float,
          "share_count": float,
          "nav_per_share": float,
          "holdings": [{symbol, qty, side, price, value_usd}, ...],
          "tick_ts": ISO8601,
          "source": "manual" | "loop",
          "wrote": bool,                  # True if insert happened
          "write_status": int | None,     # HTTP status from Supabase
          "write_body": str | None,       # response body (truncated)
          "missing_prices": [...],
          "error": str | None,
        }

    Errors are surfaced as `error` (not exceptions) so the HTTP endpoint
    can render them as JSON. Caller decides what "ok" means.
    """
    base = {"vault_id": vault_id, "source": source}
    try:
        positions = await _load_positions(vault_id)
        if not positions:
            return {**base, "ok": False, "error":
                    f"vault_positions 中没有 {vault_id} 的任何行"
                    f" —— 没法 tick 一个空 vault"}
        symbols = sorted({p["symbol"] for p in positions})

        prices = await _load_prices(symbols)

        math = positions_value(positions, prices)
        if math["missing_prices"]:
            return {**base, "ok": False, "error":
                    f"positions 中的 symbol 在 panel 拿不到当前价:{math['missing_prices']}",
                    "holdings": math["holdings"],
                    "nav_usd": math["nav_usd"]}

        state = await _load_state(vault_id)
        share_count = load_share_count(state)
        nav_per_share = math["nav_usd"] / share_count
        tick_ts = datetime.now(timezone.utc).isoformat()

        result = {
            **base,
            "ok": True,
            "nav_usd": math["nav_usd"],
            "share_count": round(share_count, 8),
            "nav_per_share": round(nav_per_share, 10),
            "holdings": math["holdings"],
            "tick_ts": tick_ts,
            "wrote": False,
            "write_status": None,
            "write_body": None,
            "missing_prices": [],
        }

        if dry_run:
            return result

        # Real write via insert_with_detail (S-329 path: honest failure shape)
        from src.api.rpc_diagnostics import insert_with_detail, render_detail
        row = [{
            "vault_id": vault_id,
            "tick_ts": tick_ts,
            "nav_usd": math["nav_usd"],
            "share_count": round(share_count, 8),
            "nav_per_share": round(nav_per_share, 10),
            "holdings": math["holdings"],
            "source": source,
        }]
        ok, detail = await insert_with_detail("vault_nav_tick", row)
        result["wrote"] = ok
        result["write_status"] = detail.get("status_code")
        result["write_body"] = render_detail(detail, prefix="vault_nav_tick")
        if not ok:
            result["ok"] = False
            result["error"] = f"写入 vault_nav_tick 失败: {result['write_body']}"

        # Update liveness — this is what flips the loop from dead → live.
        # We piggyback on the existing _beat machinery.
        try:
            from src.api.loop_beat import beat
            await beat(f"_vault_tick_{vault_id}_loop",
                       ok=ok,
                       error=None if ok else result["write_body"])
        except Exception as _be:                                # noqa: BLE001
            # Liveness update failure must not block the tick itself —
            # the tick data is already in (or failed for an honest reason).
            result["liveness_update_error"] = f"{type(_be).__name__}: {str(_be)[:120]}"

        return result

    except LookupError as _le:
        return {**base, "ok": False, "error": str(_le)}
    except ValueError as _ve:
        return {**base, "ok": False, "error": str(_ve)}
    except Exception as _e:                                     # noqa: BLE001
        return {**base, "ok": False, "error":
                f"{type(_e).__name__}: {str(_e)[:200]}"}


__all__ = ["tick_vault_nav"]
