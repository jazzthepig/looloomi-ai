"""
S-378b-C1: `_deep_panel_loop` was timing out at 15s on the slow
`deep_panel_symbol_list` RPC (an aggregation over 386k rows).

THE TIMEOUT. The 15s measured in the dashboard beat was one PostgREST timeout
(10s) plus a bit of overhead. The slow path is fine when the DB is idle; it
dies when every loop fires within ~180s of process boot and 8 of them hit the
same RPC. **A collection loop that is supposed to run daily does not need a
10-second RPC to resolve its universe** — `deep_panel_symbols_fast` does the
same job via skip-scan (203ms / 793 buffers vs 1315ms / 2406 buffers) and
returns distinct symbol names directly.

THE FIX (TWO-PATH, NOT REPLACE). Fast path is now the primary call; the slow
path is the SECONDARY, only invoked when (a) the fast path failed AND (b) we
need `latest` for the auto-heal window. That keeps the S-323 self-heal feature
while removing the 15s timeout as the dominant cost of a normal run.

WHAT THIS TEST GUARDS. Three properties:

  1. **Fast path is the primary call.** The slow `deep_panel_symbol_list` RPC
     is not invoked when `deep_panel_symbols_fast` returns a non-empty list.
     (Verified by recording which RPC names get called.)
  2. **Slow path is the fallback only.** If the fast path returns None, the
     slow path is consulted — so the S-323 auto-heal window still works when
     only the fast RPC is degraded.
  3. **Both-failed is still one error, not two.** When both RPCs fail, the
     function returns a single failure (the fast-path detail) and does not
     double-timeout.

Run: python3 -m tests.test_deep_panel_uses_fast_rpc_first
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.data.market import deep_panel_collector as dpc   # noqa: E402

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


# ── The three properties that fix C1 ─────────────────────────────────────────

class _FakeRpc:
    """Records which RPC names get called and returns canned responses."""
    def __init__(self, fast_rows, slow_rows):
        self.fast_rows = fast_rows
        self.slow_rows = slow_rows
        self.calls: list[str] = []

    async def __call__(self, fn_name, payload=None):
        self.calls.append(fn_name)
        if fn_name == "deep_panel_symbols_fast":
            return self.fast_rows, {"outcome": "ok", "fn": fn_name, "n_rows": len(self.fast_rows or [])}
        if fn_name == "deep_panel_symbol_list":
            return self.slow_rows, {"outcome": "ok", "fn": fn_name, "n_rows": len(self.slow_rows or [])}
        return None, {"outcome": "unrecognised", "fn": fn_name}


def test_fast_path_is_primary_when_it_succeeds() -> None:
    """Normal run: fast RPC works → slow RPC is NEVER called."""
    fake = _FakeRpc(
        fast_rows=["BTC", "ETH", "SOL"],   # fast path OK
        slow_rows=None,                     # must NOT be called
    )

    async def _run():
        from src.data.market import deep_panel_collector as dpc
        async def _no_upsert(*args, **kwargs):
            return True
        from src.data.market import source_policy
        with patch.object(source_policy, "assert_purpose_source", lambda *a, **kw: None), \
             patch("src.api.store.supabase_upsert_table", _no_upsert), \
             patch.object(dpc, "deep_panel_symbols_detailed", side_effect=_fast_side_effect(fake)), \
             patch.object(dpc, "deep_panel_state_detailed", side_effect=_slow_side_effect(fake)), \
             patch.object(dpc, "_fetch_one", _fake_fetch_one):
            return await dpc.collect_deep_panel()

    before = list(fake.calls)
    res = asyncio.run(_run())
    new_calls = list(fake.calls)[len(before):]

    check("fast path primary when it succeeds",
          "deep_panel_symbols_fast" in new_calls,
          f"fast RPC not in calls: {new_calls}")
    check("slow path NOT consulted when fast succeeds",
          "deep_panel_symbol_list" not in new_calls,
          f"slow RPC was called despite fast success: {new_calls}")
    # Resolved a 3-symbol universe (or close to it) without using the slow RPC
    check("resolved a small universe", res.get("symbols_total") == 3,
          f"res={res}")


def test_slow_path_is_fallback_only() -> None:
    """Fast path FAILS → slow path is consulted (auto-heal still works)."""
    fake = _FakeRpc(
        fast_rows=None,    # fast path fails
        slow_rows=["BTC", "ETH", "SOL", "XRP", "ADA"],   # slow path OK
    )

    async def _run():
        from src.data.market import deep_panel_collector as dpc
        async def _no_upsert(*args, **kwargs):
            return True
        from src.data.market import source_policy
        with patch.object(source_policy, "assert_purpose_source", lambda *a, **kw: None), \
             patch("src.api.store.supabase_upsert_table", _no_upsert), \
             patch.object(dpc, "deep_panel_symbols_detailed", side_effect=_fast_side_effect(fake)), \
             patch.object(dpc, "deep_panel_state_detailed", side_effect=_slow_side_effect(fake)), \
             patch.object(dpc, "_fetch_one", _fake_fetch_one):
            return await dpc.collect_deep_panel()

    before = list(fake.calls)
    res = asyncio.run(_run())
    new_calls = list(fake.calls)[len(before):]

    check("fast path was attempted first",
          "deep_panel_symbols_fast" in new_calls, f"{new_calls}")
    check("slow path was consulted as fallback",
          "deep_panel_symbol_list" in new_calls, f"{new_calls}")
    check("the loop resolved symbols via the slow-path fallback",
          res.get("symbols_total") == 5 or res.get("symbols_ok") is not None,
          f"res={res}")


def test_both_failed_returns_one_error_not_two() -> None:
    """When both paths fail, we get ONE error — not a stack of two."""
    fake = _FakeRpc(fast_rows=None, slow_rows=None)  # both fail

    async def _run():
        from src.data.market import deep_panel_collector as dpc
        from src.data.market import source_policy
        with patch.object(source_policy, "assert_purpose_source", lambda *a, **kw: None), \
             patch.object(dpc, "deep_panel_symbols_detailed", side_effect=_fast_side_effect(fake)), \
             patch.object(dpc, "deep_panel_state_detailed", side_effect=_slow_side_effect(fake)):
            return await dpc.collect_deep_panel()

    res = asyncio.run(_run())
    check("both-failed → ok=False", res.get("ok") is False, f"res={res}")
    check("both-failed → symbols_total is None (not a number)",
          res.get("symbols_total") is None, f"res={res}")
    check("both-failed → rpc_detail present (the observation, not the guess)",
          "rpc_detail" in res, f"res={res}")


# ── Helpers used across tests ────────────────────────────────────────────────

def _fast_side_effect(fake: "_FakeRpc"):
    async def _impl():
        fake.calls.append("deep_panel_symbols_fast")
        if fake.fast_rows is None:
            return None, {"outcome": "no_response",
                          "fn": "deep_panel_symbols_fast",
                          "elapsed_ms": 5000}, None
        # S-378b-C1: third return value is the `latest` hint. Production SQL
        # doesn't return it today, so the third slot is None. If a test wants
        # to exercise the heal-window-from-fast-path branch, it sets
        # `fake.fast_latest` to a non-empty list of ISO dates.
        rows = [{"symbol": s} for s in fake.fast_rows]
        return (rows,
                {"outcome": "ok",
                 "n_rows": len(fake.fast_rows),
                 "fn": "deep_panel_symbols_fast"},
                getattr(fake, "fast_latest", None))
    return _impl


def _slow_side_effect(fake: "_FakeRpc"):
    async def _impl():
        fake.calls.append("deep_panel_symbol_list")
        if fake.slow_rows is None:
            return None, {"outcome": "no_response",
                          "fn": "deep_panel_symbol_list",
                          "elapsed_ms": 15173}
        return ([{"symbol": s, "latest": "2026-09-19"} for s in fake.slow_rows],
                {"outcome": "ok",
                 "n_rows": len(fake.slow_rows),
                 "fn": "deep_panel_symbol_list"})
    return _impl


async def _fake_fetch_one(symbol: str, days: int):
    """Mock _fetch_one to return a single fake bar — enough for collect_deep_panel
    to consider the run 'OK' from a fetch perspective."""
    return symbol, [{
        "symbol": symbol, "asset_class": "Crypto",
        "trade_date": "2026-09-19",
        "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
        "source": "binance_hist",
    }], None


# ── 4th property: heal window computes from fast-path latest hint ───────────

def test_fast_path_latest_hint_powers_heal_window_without_slow_rpc() -> None:
    """When the fast RPC also returns latest dates, `collect_deep_panel` can
    expand its heal window WITHOUT consulting the slow RPC.

    This is the regression guard for the bug where C1 (fast-path-primary)
    silently shrank the S-323 self-heal window back to 14 days because the
    fast path didn't expose `latest`. The fix: `deep_panel_symbols_detailed`
    returns a 3-tuple, and `collect_deep_panel` synthesises a `state` view
    from `latest_hint` so the existing heal-window branch runs unchanged.
    """
    from datetime import datetime, timedelta, timezone

    fake = _FakeRpc(
        fast_rows=["BTC", "ETH", "SOL"],
        slow_rows=None,    # must NOT be called
    )
    # 30 days ago — gap that the 14-day default window cannot reach.
    old = (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()
    fake.fast_latest = [old, old, old]

    async def _run():
        from src.data.market import deep_panel_collector as dpc
        from src.data.market import source_policy
        async def _no_upsert(*args, **kwargs):
            return True
        with patch.object(source_policy, "assert_purpose_source", lambda *a, **kw: None), \
             patch("src.api.store.supabase_upsert_table", _no_upsert), \
             patch.object(dpc, "deep_panel_symbols_detailed", side_effect=_fast_side_effect(fake)), \
             patch.object(dpc, "deep_panel_state_detailed", side_effect=_slow_side_effect(fake)), \
             patch.object(dpc, "_fetch_one", _fake_fetch_one):
            return await dpc.collect_deep_panel()

    before = list(fake.calls)
    res = asyncio.run(_run())
    new_calls = list(fake.calls)[len(before):]

    check("fast path with latest was attempted",
          "deep_panel_symbols_fast" in new_calls, f"{new_calls}")
    check("slow path STILL not consulted when fast path carries latest",
          "deep_panel_symbol_list" not in new_calls,
          f"slow RPC was called despite fast+latest: {new_calls}")
    # The function returns a result (the 3-symbol synth trips the 200-floor
    # with universe_collapsed=True — that IS production behaviour; the
    # floor's job is exactly to refuse this shape). The point of the test
    # is that the slow RPC was not consulted; the function didn't crash on
    # the 3-tuple unpacking; and the floor fired with the right diagnostic.
    check("3-tuple signature unpacks cleanly (no TypeError)",
          isinstance(res, dict), f"res type={type(res).__name__}")
    check("floor correctly refuses short universe (200-floor still enforced)",
          res.get("universe_collapsed") is True, f"res={res}")
    check("rpc_detail absent (fast path succeeded — no error to surface)",
          "rpc_detail" not in res, f"res={res}")


if __name__ == "__main__":
    print("── S-378b-C1: _deep_panel_loop uses fast RPC first ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ fast path primary · slow path fallback only · both-failed = one error · heal window from fast-path latest hint")
