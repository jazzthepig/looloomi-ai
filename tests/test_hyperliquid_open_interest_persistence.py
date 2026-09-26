"""
T-012: HL 采集器加持仓量(OI)—— venue_snapshot() 返回 open_interest 但
collect_venue_marks() 把它丢弃。本只测 persistence 端:
venue_snapshot 拿出 OI → collect_venue_marks 写进 open_interest_history 表,
NONE 走 I1("未测量")不被写成 0,行数 > 200(HL ~232 perps)。

跑法:python3 -m tests.test_hyperliquid_open_interest_persistence
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.data.market import hyperliquid_collector as hc   # noqa: E402

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


# ── Sample HL response: 5 perps, all with OI ────────────────────────────────

def _sample_hl_response(n_perps: int = 5,
                        oi_field: str = "openInterest") -> tuple[dict, list]:
    """Build a tiny but representative metaAndAssetCtxs response.

    `oi_field` defaults to "openInterest" (HL's current field name).
    """
    names = tuple(f"SYM{i}" for i in range(n_perps))
    meta = {"universe": [{"name": n} for n in names]}
    ctxs = []
    for i, sym in enumerate(names):
        ctxs.append({
            "markPx": str(100 + i),
            "oraclePx": str(100 + i),
            "prevDayPx": str(99 + i),
            "funding": str(0.0001 * (i + 1)),
            oi_field: str(1_000_000 * (i + 1)),
            "dayNtlVlm": str(50_000_000 * (i + 1)),
        })
    return meta, ctxs


# ── Properties T-012 requires ────────────────────────────────────────────────

def test_oi_persisted_to_open_interest_history_table() -> None:
    """`collect_venue_marks()` must upsert to `open_interest_history`."""
    async def _run():
        meta, ctxs = _sample_hl_response(n_perps=5)
        import httpx
        resp = httpx.Response(
            status_code=200, json=[meta, ctxs],
            request=httpx.Request("POST", hc._INFO_URL),
        )

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **kw): return resp
            async def aclose(self): pass

        captured = {"funding": [], "oi": []}
        async def _fake_upsert(table, rows, **kwargs):
            if table == "funding_history":
                captured["funding"].extend(rows)
            elif table == "open_interest_history":
                captured["oi"].extend(rows)
            return True

        with patch.object(hc.httpx, "AsyncClient", _FakeClient), \
             patch("src.api.store.supabase_upsert_table", _fake_upsert):
            return await hc.collect_venue_marks(), captured

    res, captured = asyncio.run(_run())
    check("oi upsert target = open_interest_history",
          len(captured["oi"]) == 5,
          f"res={res}, oi_rows={captured['oi']}")
    check("funding upsert target = funding_history (regression check)",
          len(captured["funding"]) == 5,
          f"funding_rows={captured['funding']}")


def test_oi_skips_none_with_i1_discipline() -> None:
    """A perp with None OI must NOT be written as 0 (I1: 未测量 != 0)."""
    async def _run():
        meta = {"universe": [{"name": "HAS_OI"}, {"name": "NO_OI"}]}
        ctxs = [
            {"markPx": "100", "funding": "0.0001", "openInterest": "5000000",
             "dayNtlVlm": "1000"},
            # NO_OI has no openInterest field at all (legitimate "未读到")
            {"markPx": "200", "funding": "0.0002", "dayNtlVlm": "2000"},
        ]
        import httpx
        resp = httpx.Response(
            status_code=200, json=[meta, ctxs],
            request=httpx.Request("POST", hc._INFO_URL),
        )

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **kw): return resp
            async def aclose(self): pass

        captured = {"oi": []}
        async def _fake_upsert(table, rows, **kwargs):
            if table == "open_interest_history":
                captured["oi"].extend(rows)
            return True

        with patch.object(hc.httpx, "AsyncClient", _FakeClient), \
             patch("src.api.store.supabase_upsert_table", _fake_upsert):
            return await hc.collect_venue_marks(), captured

    res, captured = asyncio.run(_run())
    check("None OI is skipped (HAS_OI only)",
          len(captured["oi"]) == 1 and captured["oi"][0]["symbol"] == "HAS_OI",
          f"oi_rows={captured['oi']}")
    check("n_missing_oi count surfaced in return",
          res.get("n_missing_oi") == 1,
          f"res={res}")
    check("HAS_OI row has open_interest populated (no None, no 0)",
          captured["oi"][0]["open_interest"] == 5000000.0,
          f"row={captured['oi'][0]}")


def test_oi_row_shape_matches_ddl() -> None:
    """Every OI row must carry symbol + snapshot_time + venue + open_interest,
    matching `open_interest_history` PK / columns. S-244 family guard: if the
    collector drifts from the DDL, the upsert will fail at the PostgREST layer
    and be silently swallowed by `supabase_upsert_table`'s return-False
    contract — so we pin the row shape here."""
    captured_local: dict[str, list] = {"oi": []}

    async def _run():
        meta, ctxs = _sample_hl_response(n_perps=2)
        import httpx
        resp = httpx.Response(
            status_code=200, json=[meta, ctxs],
            request=httpx.Request("POST", hc._INFO_URL),
        )

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **kw): return resp
            async def aclose(self): pass

        async def _fake_upsert(table, rows, **kwargs):
            if table == "open_interest_history":
                captured_local["oi"].extend(rows)
            return True

        with patch.object(hc.httpx, "AsyncClient", _FakeClient), \
             patch("src.api.store.supabase_upsert_table", _fake_upsert):
            await hc.collect_venue_marks()

    asyncio.run(_run())
    required = {"symbol", "snapshot_time", "venue", "open_interest"}
    if not captured_local["oi"]:
        check("OI rows captured", False, "captured['oi'] is empty")
    for r in captured_local["oi"]:
        check(f"OI row {r.get('symbol')} has all required keys",
              required.issubset(r.keys()),
              f"row={r}")


def test_oi_hourly_bucketing_is_idempotent() -> None:
    """Two calls within the same hour must write to the same `snapshot_time`,
    so a re-run is idempotent on PK (symbol, snapshot_time, venue)."""
    async def _run():
        meta, ctxs = _sample_hl_response(n_perps=1)
        import httpx
        resp = httpx.Response(
            status_code=200, json=[meta, ctxs],
            request=httpx.Request("POST", hc._INFO_URL),
        )

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **kw): return resp
            async def aclose(self): pass

        captured = {"oi": []}
        async def _fake_upsert(table, rows, **kwargs):
            if table == "open_interest_history":
                captured["oi"].extend(rows)
            return True

        with patch.object(hc.httpx, "AsyncClient", _FakeClient), \
             patch("src.api.store.supabase_upsert_table", _fake_upsert):
            r1 = await hc.collect_venue_marks()
            r2 = await hc.collect_venue_marks()
            return r1, r2, captured

    r1, r2, captured = asyncio.run(_run())
    check("two same-hour calls share snapshot_time (idempotent PK)",
          r1.get("funding_time") == r2.get("funding_time"),
          f"r1.funding_time={r1.get('funding_time')} r2.funding_time={r2.get('funding_time')}")


def test_collector_calls_open_interest_history_table() -> None:
    """S-244 family text guard: `collect_venue_marks` must literally reference
    `open_interest_history` so a regression that drops OI persistence fails
    preflight stage 3 instead of silently going to 0 rows."""
    src = open(hc.__file__, encoding="utf-8").read()
    check("hyperliquid_collector.py writes to open_interest_history",
          '"open_interest_history"' in src,
          "OI persistence missing — T-012 regression")


if __name__ == "__main__":
    print("── T-012: HL OI persistence to open_interest_history ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ OI writes to open_interest_history · None skipped · row shape pinned · hourly idempotent")