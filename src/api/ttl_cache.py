"""
In-process stale-while-revalidate cache for slow, read-only public endpoints (2026-10-29).

Measured on the live site: /signals/dingge-board recomputed a 7 s scan on every request and
/trading/metrics re-ran per-symbol history lookups (6 s) on every request — the panels sat on
skeletons each time anyone opened them. This keeps the last good value for `ttl` seconds, then keeps
serving it while ONE background task refreshes it (`stale_for` seconds at most). A failed refresh
leaves the last good value in place; nothing is fabricated when there is no value yet.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

_VALUES: dict[str, tuple[float, Any]] = {}
_REFRESHING: set[str] = set()


async def swr(key: str, ttl: float, fn: Callable[[], Awaitable[Any]], stale_for: float = 3600.0) -> Any:
    now = time.time()
    hit = _VALUES.get(key)
    if hit is not None:
        age = now - hit[0]
        if age < ttl:
            return hit[1]
        if age < ttl + stale_for:
            if key not in _REFRESHING:
                _REFRESHING.add(key)

                async def _bg():
                    try:
                        _VALUES[key] = (time.time(), await fn())
                    except Exception:
                        pass                       # keep the last good value
                    finally:
                        _REFRESHING.discard(key)
                asyncio.create_task(_bg())
            return hit[1]
    value = await fn()
    _VALUES[key] = (time.time(), value)
    return value


def clear(key: str | None = None) -> None:
    if key is None:
        _VALUES.clear()
    else:
        _VALUES.pop(key, None)
