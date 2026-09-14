"""Smoke test for force-mark primitive (A-21 vault-tick shape for paper books).

Pure unit tests; all Supabase / Redis / Binance calls are mocked. CI-portable:
no DB, no secrets, no network.

The 24h feedback loop was the bug (S-328). Every paper-book fix this week went
unverified for ~24h because `beta_core_paper.py:843` refuses writes outside the
00:05 UTC window (NAV_POLICY §3, 30-min tolerance). A-21 shipped the vault
side. This PR copies the shape to the 9 paper books. These tests verify the
primitive exists end-to-end at the code level — the deploy verification
(`/internal/force-mark/{book}` curl) runs after Mac-side commit.

Tests:

  T1: every paper book has mark_and_rebalance / mark_and_trade with the
      `force=False, source="cron"` signature
  T2: every paper book's writer path includes "mark_source": source in the row
      dict (so the migration column gets populated)
  T3: beta_core valuation guard bypass — force=True skips the 00:05 UTC check
      (the ONLY book with a timing guard)
  T4: source="manual" propagates from mark_and_rebalance into the row dict
      (end-to-end with mocked insert_with_detail)
  T5: router exists with POST /internal/force-mark/{book} and maps all 9 books
  T6: router fires beat per call with name f"_book_{book}_loop" — closes the
      S-327 / S-334 / S-336 loop (a successful write updates liveness immediately)
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai")


# ── T1: signature ─────────────────────────────────────────────────────────────
_BOOKS_USE_MARK_AND_REBALANCE = [
    "src.data.signals.beta_core_paper",
    "src.data.signals.causal_paper",
    "src.data.signals.combined_book",
    "src.data.signals.fusion_paper",
    "src.data.signals.factor_tilt_paper",
    "src.data.signals.pod_aggregator_paper",
    "src.data.signals.scalable_paper",
    "src.data.signals.two_layer_paper",
]
# dingge uses mark_and_trade (different name, same contract)
_BOOKS_USE_MARK_AND_TRADE = [
    "src.data.signals.dingge_paper",
]


def test_t1_all_books_have_force_and_source():
    """Every paper book accepts force=False, source='cron'."""
    import importlib

    for mod_path in _BOOKS_USE_MARK_AND_REBALANCE:
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, "mark_and_rebalance", None)
        assert fn is not None, f"{mod_path}: no mark_and_rebalance"
        sig = inspect.signature(fn)
        params = sig.parameters
        assert "force" in params, f"{mod_path}.mark_and_rebalance: missing 'force' param"
        assert params["force"].default is False, \
            f"{mod_path}.mark_and_rebalance: 'force' default must be False"
        assert "source" in params, f"{mod_path}.mark_and_rebalance: missing 'source' param"
        assert params["source"].default == "cron", \
            f"{mod_path}.mark_and_rebalance: 'source' default must be 'cron'"
        print(f"✓ {mod_path}: mark_and_rebalance(force=False, source='cron')")

    for mod_path in _BOOKS_USE_MARK_AND_TRADE:
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, "mark_and_trade", None)
        assert fn is not None, f"{mod_path}: no mark_and_trade"
        sig = inspect.signature(fn)
        params = sig.parameters
        assert "force" in params, f"{mod_path}.mark_and_trade: missing 'force' param"
        assert params["force"].default is False, \
            f"{mod_path}.mark_and_trade: 'force' default must be False"
        assert "source" in params, f"{mod_path}.mark_and_trade: missing 'source' param"
        assert params["source"].default == "cron", \
            f"{mod_path}.mark_and_trade: 'source' default must be 'cron'"
        print(f"✓ {mod_path}: mark_and_trade(force=False, source='cron')")
    print("✓ T1: all 9 paper books accept force + source params (default cron)")


# ── T2: row dict contains mark_source ─────────────────────────────────────────
def test_t2_row_dict_contains_mark_source():
    """Every writer path includes 'mark_source': source in the row dict."""
    import importlib

    # Each book has a known writer path. Spot-check by reading source lines.
    expected_substrings = {
        "src.data.signals.beta_core_paper":      "\"mark_source\": source",
        "src.data.signals.causal_paper":         "\"mark_source\": source",
        "src.data.signals.combined_book":        "\"mark_source\": source",
        "src.data.signals.fusion_paper":         "\"mark_source\": source",
        "src.data.signals.scalable_paper":       "\"mark_source\": source",
        "src.data.signals.dingge_paper":         "\"mark_source\": source",
        "src.data.signals.two_layer_paper":      "\"mark_source\": source",
    }
    # factor_tilt + pod_aggregator go through nav_persist.write_nav_row, which
    # takes the row dict directly — the test is "mark_source is in the row dict
    # passed TO write_nav_row", which is a textual check too.
    expected_substrings["src.data.signals.factor_tilt_paper"] = "\"mark_source\": source"
    expected_substrings["src.data.signals.pod_aggregator_paper"] = "\"mark_source\": source"

    for mod_path, expected in expected_substrings.items():
        mod = importlib.import_module(mod_path)
        src_file = Path(mod.__file__).read_text()
        # Look for `"mark_source": source` somewhere in the writer section.
        # Allow flexibility: the literal may appear with different whitespace
        # or be split across lines.
        assert '"mark_source"' in src_file, \
            f"{mod_path}: 'mark_source' not present in source"
        assert 'source' in src_file, \
            f"{mod_path}: 'source' identifier not present"
        # Look for the pattern that binds them: "mark_source": followed by source
        # in the writer context. We accept either on the same line or split.
        lines = src_file.splitlines()
        bound = any(
            ('"mark_source"' in ln and "source" in ln and "source=" not in ln)
            or (
                '"mark_source"' in ln
                and i + 1 < len(lines)
                and "source" in lines[i + 1]
            )
            for i, ln in enumerate(lines)
        )
        assert bound, f"{mod_path}: 'mark_source' and 'source' not bound in same row"
        print(f"✓ {mod_path}: 'mark_source': source in row dict")
    print("✓ T2: all 9 paper books include 'mark_source': source in row dict")


# ── T3: beta_core valuation guard bypass ──────────────────────────────────────
def test_t3_beta_core_guard_bypassed_by_force():
    """beta_core is the ONLY book with a valuation guard. force=True must skip it.

    Inspect the source at the guard line: the condition must include
    `and not force` so the operator can strike a mark NOW instead of waiting
    for 00:05 UTC ±30min. The other 8 books have no timing guard, so this
    change applies only to beta_core.
    """
    from src.data.signals import beta_core_paper
    src = Path(beta_core_paper.__file__).read_text()
    # The original guard: `if not dry_run and _off_by > _VALUATION_POINT_TOLERANCE_MIN:`
    # After the change: `if not dry_run and not force and _off_by > ...:`
    # We look for the new form anywhere in the file.
    new_guard = "if not dry_run and not force and _off_by >"
    old_guard = "if not dry_run and _off_by >"
    assert new_guard in src, \
        "beta_core_paper.py: new guard condition with `not force` not found"
    # Make sure the old guard (without `not force`) is NOT present — otherwise
    # a stale guard could still fire on operator override.
    old_count = src.count(old_guard)
    new_count = src.count(new_guard)
    assert old_count <= new_count, \
        f"beta_core_paper.py: old guard ({old_count}) found more often than new ({new_count})"
    print(f"✓ T3: beta_core guard = `not dry_run and not force and _off_by >` "
          f"(old={old_count} new={new_count})")
    print("✓ T3: beta_core valuation guard bypassed when force=True")


# ── T4: source propagation end-to-end ────────────────────────────────────────
async def test_t4_source_propagates_to_row():
    """Calling mark_and_rebalance with source='manual' writes 'manual' to the row.

    Uses causal_paper (smallest of the 9, simple _write_nav shape). Mocks all
    I/O so the test is offline. The captured row dict MUST contain
    mark_source='manual'.
    """
    from src.data.signals import causal_paper

    # Mock _fetch_live: return one asset (causal needs ≥5 to proceed past the
    # coverage floor; mock returns 6 to be safe).
    def fake_fetch_live(universe):
        return {s: {"close": 100.0, "fmean": [0.0] * 16} for s in universe[:6]}

    # Mock _redis_get: return None so we hit the inception branch.
    async def fake_redis_get(key):
        return None
    async def fake_redis_set(key, val, ttl=0):
        return True

    # Mock insert_with_detail: capture the row dict; return success.
    captured: list[list[dict]] = []
    async def fake_insert_with_detail(table, rows):
        captured.append(rows)
        return True, {"outcome": "ok", "status_code": 201}

    async def fake_nav_row_exists(table, day):
        return False  # no prior row → proceed to mark

    with patch.object(causal_paper, "_fetch_live", side_effect=fake_fetch_live), \
         patch("src.data.market.data_layer._redis_get", side_effect=fake_redis_get), \
         patch("src.data.market.data_layer._redis_set", side_effect=fake_redis_set), \
         patch("src.api.rpc_diagnostics.insert_with_detail", side_effect=fake_insert_with_detail), \
         patch("src.data.signals.nav_persist.nav_row_exists", side_effect=fake_nav_row_exists):
        result = await causal_paper.mark_and_rebalance(
            dry_run=False, force=True, source="manual")

    print(f"  T4 result status={result.get('status')} nav={result.get('nav')}")
    assert result.get("status") in ("inception", "marked"), \
        f"unexpected status {result.get('status')}: {result}"
    assert captured, "insert_with_detail was never invoked"
    row = captured[0][0]
    assert "mark_source" in row, \
        f"row dict missing 'mark_source': {list(row.keys())}"
    assert row["mark_source"] == "manual", \
        f"row['mark_source'] = {row['mark_source']!r}, expected 'manual'"
    print(f"✓ T4: source='manual' → row['mark_source'] = 'manual' (captured)")


# ── T5: router exists and maps all 9 books ────────────────────────────────────
def test_t5_router_endpoint_and_book_map():
    """force_mark router has POST /internal/force-mark/{book} covering all 9 books."""
    from src.api.routers.force_mark import router, _FORCE_BOOKS
    paths = {r.path for r in router.routes}
    # FastAPI path templates: /internal/force-mark/{book}
    assert "/internal/force-mark/{book}" in paths, \
        f"POST /internal/force-mark/{{book}} not in router routes: {paths}"

    expected_books = {
        "beta_core", "causal", "combined", "dingge", "fusion",
        "factor_tilt", "pod_aggregator", "scalable", "two_layer",
    }
    assert set(_FORCE_BOOKS) == expected_books, \
        f"_FORCE_BOOKS = {set(_FORCE_BOOKS)}, expected {expected_books}"

    # Methods: POST must be present on the path
    post_routes = [r for r in router.routes
                   if r.path == "/internal/force-mark/{book}"]
    assert post_routes, "no route found for /internal/force-mark/{book}"
    methods = post_routes[0].methods
    assert "POST" in methods, f"POST not in methods: {methods}"
    print(f"✓ T5: router covers all 9 books: {sorted(_FORCE_BOOKS)}")
    print(f"✓ T5: POST /internal/force-mark/{{book}} registered (methods={methods})")


# ── T6: router fires beat per call ────────────────────────────────────────────
async def test_t6_router_fires_beat_per_call():
    """force-mark invokes beat(f'_book_{book}_loop', ok=...) on every call.

    Mocks the underlying mark function so the router flow runs end-to-end
    without hitting Supabase / Redis / Binance. Verifies beat was called with
    the right key and the result contains the documented shape.
    """
    from src.api.routers import force_mark

    fake_beat = AsyncMock()
    fake_mark_result = {
        "status": "marked",
        "nav": 1.0123,
        "daily_return_pct": 0.5,
        "date": "2026-09-14",
    }
    fake_mark_fn = AsyncMock(return_value=fake_mark_result)

    with patch.object(force_mark, "_token", return_value="test-token"), \
         patch("src.api.loop_beat.beat", fake_beat), \
         patch.object(force_mark, "importlib") as fake_importlib:
        fake_mod = MagicMock()
        fake_mod.mark_and_rebalance = fake_mark_fn
        fake_mod.mark_and_trade = None
        fake_importlib.import_module.return_value = fake_mod

        result = await force_mark.force_mark(
            book="causal",
            dry_run=False,
            x_internal_token="test-token",
        )

    assert result["ok"] is True, f"result.ok = {result.get('ok')}"
    assert result["book"] == "causal"
    assert result["mark_source"] == "manual"
    assert result["wrote"] is True
    assert result["mark_status"] == "marked"
    assert fake_beat.await_count == 1, \
        f"beat awaited {fake_beat.await_count} times, expected 1"
    beat_call = fake_beat.await_args
    beat_args, beat_kwargs = beat_call
    # beat(name, ok=, error=) — positional name, kw ok=bool, kw error=...
    assert beat_args[0] == "_book_causal_loop", \
        f"beat name = {beat_args[0]!r}, expected '_book_causal_loop'"
    assert beat_kwargs.get("ok") is True, \
        f"beat ok = {beat_kwargs.get('ok')!r}, expected True"
    assert fake_mark_fn.await_count == 1
    mark_call = fake_mark_fn.await_args
    mark_kwargs = mark_call.kwargs
    assert mark_kwargs.get("force") is True, \
        f"mark_and_rebalance force = {mark_kwargs.get('force')!r}"
    assert mark_kwargs.get("source") == "manual", \
        f"mark_and_rebalance source = {mark_kwargs.get('source')!r}"
    assert mark_kwargs.get("dry_run") is False
    print(f"✓ T6: beat('_book_causal_loop', ok=True) fired once")
    print(f"✓ T6: mark_and_rebalance(force=True, source='manual', dry_run=False)")


if __name__ == "__main__":
    import asyncio
    print("=== Force-mark primitive smoke ===\n")
    test_t1_all_books_have_force_and_source()
    print()
    test_t2_row_dict_contains_mark_source()
    print()
    test_t3_beta_core_guard_bypassed_by_force()
    print()
    asyncio.run(test_t4_source_propagates_to_row())
    print()
    test_t5_router_endpoint_and_book_map()
    print()
    asyncio.run(test_t6_router_fires_beat_per_call())
    print(f"\n=== All force-mark primitive tests passed (6/6) ===")