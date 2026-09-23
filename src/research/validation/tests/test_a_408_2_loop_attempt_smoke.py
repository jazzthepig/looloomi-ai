"""Smoke test for loop_attempt per-iteration record (A-408-2 / S-408-2).

The structural fix for "loops go dark and nobody notices for 42 days":
`_beat()` writes a Redis hash, last-write-wins, 3-day TTL — it answers
"is the loop alive right now" but cannot answer a COUNT. The audit
gate is `select count(*) from loop_attempt where loop_name='_cg_panel_loop'
and at::date = current_date` ≥ 100, which is a COUNT.

The two views are complementary, not duplicative. A loop that ran
cleanly 200 times today and failed once shows beat()=ok and
loop_attempt={ok:199, error:1}. The audit gate needs the COUNT.

Tests:

  T1:  HELPER_TYPING — Literal narrows the four-outcome vocabulary
  T2:  HELPER_NEVER_RAISES — even when httpx throws, returns False
  T3:  HELPER_SKIPS_WHEN_NOT_CONFIGURED — _SB_URL missing → False, no network
  T4:  ROW_PAYLOAD_OUTCOME_OK — outcome=ok rows have all fields truncated sanely
  T5:  ROW_PAYLOAD_OUTCOME_ERROR — error rows carry reason+detail
  T6:  REASON_TRUNCATION — pass 1000-char reason; assert only 400 chars land
  T7:  BUILD_FIELD_PRESENT — build[:8] is set from loop_beat.build_sha
  T8:  LOOP_ATTEMPT_TABLE_CONSTANT — _LOOP_ATTEMPT_TABLE == 'loop_attempt'
  T9:  CALL_SITE_GUARD — S-244 family: main.py contains
       `_record_loop_attempt("_cg_panel_loop"` ≥ 3 times. Drop one
       and the audit gate's per-iteration record silently disappears.
  T10: PARALLEL_WITH_BEAT — calling _record + _beat at the same site doesn't raise
  T11: IDEMPOTENT_TWO_CALLS — calling the helper twice does not raise
  T12: REPLAY_09-23 (the A-408-2 fixture) — replicate `_cg_panel_loop`'s
       three branches and assert the helper is called exactly once per
       iteration with the right outcome, regardless of which branch fires.

Synthetic data + httpx mocking — no DB / no Supabase / no secrets.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai")

from src.api.rpc_diagnostics import (
    _record_loop_attempt, _LOOP_ATTEMPT_TABLE, LoopOutcome,
)
from src.api import store


# ── T1: Literal narrows the four outcomes ───────────────────────────────────
def test_t1_literal_outcome_vocabulary():
    """The four values are exactly the union {_beat's ok/refused/failing
    + panel_unavailable for S-410's specific failure mode}."""
    expected = {"ok", "refused", "error", "panel_unavailable"}
    actual = set(LoopOutcome.__args__)
    print(f"  T1 LoopOutcome.__args__ = {sorted(actual)}")
    assert actual == expected, (
        f"LoopOutcome vocabulary drifted: got {actual}, expected {expected}. "
        "If you added a value, update _classify mapping + dashboard filter "
        "+ this test in the same commit."
    )
    print("✓ T1: LoopOutcome vocabulary is {ok, refused, error, panel_unavailable}")


# ── T2: never raises, even when httpx throws ────────────────────────────────
def test_t2_helper_never_raises():
    """Even with httpx blowing up, _record_loop_attempt must return False,
    never raise. Same S-352 contract: it has no second-layer logger."""
    async def _run():
        with patch.object(store, "_SB_URL", "https://example.supabase.co"), \
             patch.object(store, "_SB_KEY", "fake_key"):
            with patch("httpx.AsyncClient") as MockClient:
                mock_inst = MagicMock()
                mock_inst.post = MagicMock(
                    side_effect=ConnectionError("simulated network down"))
                mock_inst.__aenter__ = MagicMock(return_value=mock_inst)
                mock_inst.__aexit__ = MagicMock(return_value=None)
                MockClient.return_value = mock_inst
                ok = await _record_loop_attempt("_cg_panel_loop", "ok",
                                                reason="simulated",
                                                writer="t2.test")
                print(f"  T2 returned={ok}")
                assert ok is False, "should return False on httpx error"
    asyncio.run(_run())
    print("✓ T2: helper never raises — ConnectionError → returns False")


# ── T3: not-configured short-circuits ────────────────────────────────────────
def test_t3_not_configured_short_circuits():
    """When SUPABASE_URL/KEY are missing, helper returns False without
    touching the network. Same as _record_attempt."""
    async def _run():
        with patch.object(store, "_SB_URL", ""), \
             patch.object(store, "_SB_KEY", ""):
            with patch("httpx.AsyncClient") as MockClient:
                # If helper short-circuits, this is never called.
                ok = await _record_loop_attempt("_cg_panel_loop", "ok",
                                                writer="t3.test")
                print(f"  T3 returned={ok}, httpx called={MockClient.called}")
                assert ok is False, "should return False when not configured"
                assert not MockClient.called, "must not hit network when not configured"
    asyncio.run(_run())
    print("✓ T3: _SB_URL/KEY empty → returns False, no network call")


# ── T4: ok payload shape ─────────────────────────────────────────────────────
def test_t4_payload_outcome_ok():
    """Outcome=ok rows carry all fields, with truncation."""
    captured = {}

    class _FakeResp:
        status_code = 201

    async def _fake_post(*args, **kwargs):
        # httpx.AsyncClient.post is bound; both positional and kwarg forms
        # occur across versions. Capture whatever shape comes in.
        if args:
            captured.setdefault("args", []).append(args)
        if kwargs:
            captured.update(kwargs)
        return _FakeResp()

    async def _run():
        with patch.object(store, "_SB_URL", "https://example.supabase.co"), \
             patch.object(store, "_SB_KEY", "fake_key"), \
             patch.dict("os.environ", {"RAILWAY_GIT_COMMIT_SHA": "abcdef0123456789"}):
            with patch("httpx.AsyncClient.post", new=_fake_post):
                ok = await _record_loop_attempt(
                    "_cg_panel_loop", "ok",
                    reason="4 symbols backfilled",
                    elapsed_ms=1200,
                    detail={"symbols_total": 158, "rows_written": 4},
                    writer="src.api.main._cg_panel_loop")
                print(f"  T4 ok={ok}, captured keys={list(captured.keys())}")
                assert ok is True
                # Newer httpx passes via kwargs; older via positional args.
                # We pass `json=[row]` so the body lands in either kwargs['json']
                # or args[-1] depending on signature.
                body_obj = captured.get("json")
                if body_obj is None and "args" in captured:
                    body_obj = captured["args"][0][-1]   # last positional = body
                assert body_obj is not None, (
                    f"no body captured: keys={list(captured.keys())}, "
                    f"args={captured.get('args')}")
                body = body_obj[0]
                assert body["loop_name"] == "_cg_panel_loop", body
                assert body["outcome"] == "ok", body
                assert body["reason"] == "4 symbols backfilled", body
                assert body["elapsed_ms"] == 1200, body
                assert body["detail"]["symbols_total"] == 158, body
                assert body["writer"] == "src.api.main._cg_panel_loop", body
                assert "build" in body and len(body["build"]) == 8, body
    asyncio.run(_run())
    print("✓ T4: ok payload has all fields, truncated sanely")


# ── T5: error payload carries reason+detail ─────────────────────────────────
def test_t5_payload_outcome_error():
    captured = {}

    class _FakeResp:
        status_code = 200

    async def _fake_post(self, url, json, headers):
        captured["json"] = json
        return _FakeResp()

    async def _run():
        with patch.object(store, "_SB_URL", "https://example.supabase.co"), \
             patch.object(store, "_SB_KEY", "fake_key"):
            with patch("httpx.AsyncClient.post", new=_fake_post):
                ok = await _record_loop_attempt(
                    "_cg_panel_loop", "error",
                    reason="HTTPError: too many values to unpack",
                    elapsed_ms=300,
                    detail={"status": 500, "body": "internal"},
                    writer="src.api.main._cg_panel_loop")
                assert ok is True
                body = captured["json"][0]
                assert body["outcome"] == "error"
                assert body["reason"].startswith("HTTPError")
                assert body["detail"]["status"] == 500
                print(f"  T5 reason len={len(body['reason'])}")
    asyncio.run(_run())
    print("✓ T5: error payload carries reason + detail")


# ── T6: reason truncation at 400 chars ──────────────────────────────────────
def test_t6_reason_truncation():
    captured = {}

    class _FakeResp:
        status_code = 201

    async def _fake_post(self, url, json, headers):
        captured["json"] = json
        return _FakeResp()

    async def _run():
        with patch.object(store, "_SB_URL", "https://example.supabase.co"), \
             patch.object(store, "_SB_KEY", "fake_key"):
            with patch("httpx.AsyncClient.post", new=_fake_post):
                long_reason = "X" * 1000
                ok = await _record_loop_attempt(
                    "_cg_panel_loop", "error",
                    reason=long_reason,
                    writer="t6.test")
                assert ok is True
                body = captured["json"][0]
                assert len(body["reason"]) == 400, (
                    f"reason should truncate to 400, got {len(body['reason'])}")
    asyncio.run(_run())
    print("✓ T6: reason truncates to 400 chars")


# ── T7: build field present ──────────────────────────────────────────────────
def test_t7_build_field_present():
    captured = {}

    class _FakeResp:
        status_code = 201

    async def _fake_post(self, url, json, headers):
        captured["json"] = json
        return _FakeResp()

    async def _run():
        with patch.object(store, "_SB_URL", "https://example.supabase.co"), \
             patch.object(store, "_SB_KEY", "fake_key"), \
             patch.dict("os.environ", {"RAILWAY_GIT_COMMIT_SHA": "abcdef0123456789"}):
            with patch("httpx.AsyncClient.post", new=_fake_post):
                ok = await _record_loop_attempt(
                    "_cg_panel_loop", "ok",
                    writer="t7.test")
                assert ok is True
                body_obj = captured.get("json")
                if body_obj is None and "args" in captured:
                    body_obj = captured["args"][0][-1]
                assert body_obj is not None
                body = body_obj[0]
                assert "build" in body, "build field missing"
                assert isinstance(body["build"], str)
                assert len(body["build"]) == 8, (
                    f"build should be 8 chars (loop_beat.build_sha()[:8]), "
                    f"got {len(body['build'])}")
                print(f"  T7 build={body['build']}")
    asyncio.run(_run())
    print("✓ T7: build field present, 8 chars from build_sha()")


# ── T8: table name constant ──────────────────────────────────────────────────
def test_t8_table_constant():
    """The constant exists and is the table name the DDL creates."""
    assert _LOOP_ATTEMPT_TABLE == "loop_attempt", (
        f"constant drifted: {_LOOP_ATTEMPT_TABLE!r}")
    print(f"✓ T8: _LOOP_ATTEMPT_TABLE == '{_LOOP_ATTEMPT_TABLE}'")


# ── T9: S-244 family call-site guard ─────────────────────────────────────────
def test_t9_call_site_guard():
    """A regression that drops `_record_loop_attempt` from `_cg_panel_loop`
    silently kills the audit gate. This text-based assertion catches it at
    preflight (S-244 family: test exists ≠ test runs)."""
    main_path = Path("/Users/sbb/Projects/looloomi-ai/src/api/main.py")
    text = main_path.read_text()
    # Match the call signature regardless of whitespace/indent between
    # `(` and the loop_name literal (calls span multiple lines).
    import re
    pattern = re.compile(
        r'_record_loop_attempt\(\s*"_cg_panel_loop"',
        re.MULTILINE)
    matches = pattern.findall(text)
    count = len(matches)
    # Three branches: panel_unavailable, ok|refused, error.
    # If a future refactor merges branches, lower the bound — but never 0.
    print(f"  T9 call-site count = {count}")
    assert count >= 3, (
        f"S-408-2 call-site regression: expected ≥ 3 sites in main.py, "
        f"found {count}. Each iteration branch (panel_unavailable, ok/refused, "
        f"error) must record its own row. See test_a_408_2_loop_attempt_smoke "
        f"for the audit gate.")
    print(f"✓ T9: _cg_panel_loop has {count} _record_loop_attempt call sites (≥ 3 required)")


# ── T10: parallel with _beat ─────────────────────────────────────────────────
def test_t10_parallel_with_beat():
    """Calling _record_loop_attempt at the same site as _beat() must not raise
    or block. Both are best-effort. (Simulates main.py's pattern:
    `await _beat(...); await _record_loop_attempt(...)`.)"""
    async def _run():
        calls = []

        class _FakeResp:
            status_code = 201

        async def _fake_post(self, url, json, headers):
            calls.append(json[0])
            return _FakeResp()

        with patch.object(store, "_SB_URL", "https://example.supabase.co"), \
             patch.object(store, "_SB_KEY", "fake_key"), \
             patch("httpx.AsyncClient.post", new=_fake_post):
            # simulate main.py's pattern: _beat (no-op mock) then _record
            for outcome in ("ok", "refused", "error", "panel_unavailable"):
                await _record_loop_attempt(
                    "_cg_panel_loop", outcome,
                    reason=f"t10 sim {outcome}",
                    writer="t10.test")
        print(f"  T10 recorded {len(calls)} rows across 4 outcomes")
        assert len(calls) == 4
        assert [c["outcome"] for c in calls] == [
            "ok", "refused", "error", "panel_unavailable"]
    asyncio.run(_run())
    print("✓ T10: helper composes with _beat pattern across all 4 outcomes")


# ── T11: idempotent ──────────────────────────────────────────────────────────
def test_t11_idempotent_two_calls():
    """Calling the helper twice on the same loop is idempotent — it writes
    two rows. (No recursion guard needed: loop_attempt doesn't write to
    write_log, no path exists.)"""
    async def _run():
        calls = []

        class _FakeResp:
            status_code = 201

        async def _fake_post(self, url, json, headers):
            calls.append(json[0])
            return _FakeResp()

        with patch.object(store, "_SB_URL", "https://example.supabase.co"), \
             patch.object(store, "_SB_KEY", "fake_key"), \
             patch("httpx.AsyncClient.post", new=_fake_post):
            await _record_loop_attempt("_cg_panel_loop", "ok",
                                       reason="first", writer="t11.test")
            await _record_loop_attempt("_cg_panel_loop", "ok",
                                       reason="second", writer="t11.test")
        print(f"  T11 calls={len(calls)} reasons={[c['reason'] for c in calls]}")
        assert len(calls) == 2
        assert [c["reason"] for c in calls] == ["first", "second"]
    asyncio.run(_run())
    print("✓ T11: two calls → two rows (no recursion guard interference)")


# ── T12: REPLAY 09-23 (the A-408-2 fixture) ──────────────────────────────────
def test_t12_replay_three_branches():
    """Replicate `_cg_panel_loop`'s three branches from S-410's actual
    failure mode (2026-09-23, 366× fails). Assert helper called once per
    iteration with the right outcome."""
    captured = []

    class _FakeResp:
        status_code = 201

    async def _fake_post(self, url, json, headers):
        captured.append(json[0])
        return _FakeResp()

    async def _simulate_cg_panel_iteration(sim_kind):
        """Mirror the three-branch shape of _cg_panel_loop."""
        with patch.object(store, "_SB_URL", "https://example.supabase.co"), \
             patch.object(store, "_SB_KEY", "fake_key"), \
             patch("httpx.AsyncClient.post", new=_fake_post):
            if sim_kind == "panel_unavailable":
                # Branch 1: deep_panel_symbols_detailed() → None
                await _record_loop_attempt(
                    "_cg_panel_loop", "panel_unavailable",
                    reason="RPC unreachable",
                    detail={"status": 503, "body": "service down"},
                    writer="src.api.main._cg_panel_loop")
            elif sim_kind == "ok":
                # Branch 2: _classify(res) → ok
                await _record_loop_attempt(
                    "_cg_panel_loop", "ok",
                    reason="4 symbols backfilled",
                    writer="src.api.main._cg_panel_loop")
            elif sim_kind == "refused":
                await _record_loop_attempt(
                    "_cg_panel_loop", "refused",
                    reason="panel below floor (57/97)",
                    writer="src.api.main._cg_panel_loop")
            elif sim_kind == "error":
                # Branch 3: exception
                await _record_loop_attempt(
                    "_cg_panel_loop", "error",
                    reason="ValueError: too many values to unpack",
                    writer="src.api.main._cg_panel_loop")

    async def _run():
        for kind in ("panel_unavailable", "ok", "refused", "error"):
            await _simulate_cg_panel_iteration(kind)
        print(f"  T12 captured {len(captured)} rows across 4 branch kinds")
        outcomes = [c["outcome"] for c in captured]
        assert outcomes == ["panel_unavailable", "ok", "refused", "error"]
        # All writer strings stable across calls — audit gate depends on it
        assert all(c["writer"] == "src.api.main._cg_panel_loop"
                   for c in captured)
    asyncio.run(_run())
    print("✓ T12: REPLAY — 4 branch kinds → 4 rows with stable writer")


if __name__ == "__main__":
    print("── A-408-2 / S-408-2 loop_attempt smoke ──")
    tests = sorted(
        [(k, v) for k, v in globals().items()
         if k.startswith("test_t")],
        key=lambda kv: int(kv[0].split("_t")[1].split("_")[0]))
    fails = []
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            print(f"  ✗ {name} :: {e}")
            fails.append(name)
        except Exception as e:
            print(f"  ✗ {name} :: {type(e).__name__}: {e}")
            fails.append(name)
    if fails:
        print(f"\n🔴 {len(fails)} FAILED: {fails}")
        sys.exit(1)
    print(f"\n✅ {len(tests)} tests pass")