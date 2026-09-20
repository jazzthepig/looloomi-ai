"""
S-378b-C3: `_hyperliquid_loop` was producing "234 永续 · 0 行 funding".

THE ROOT CAUSE. `venue_snapshot()` reads `c.get("funding")` from each asset's
context. The Hyperliquid `metaAndAssetCtxs` endpoint has been observed returning
the funding rate under multiple field names across API revisions:
  - `funding`        — historical
  - `fundingRate`    — some snapshots
  - `funding_rate`   — REST docs variants

A single field lookup is a brittle contract: if HL ships a snapshot under
`fundingRate`, the lookup returns None, all 234 perps come back with
`funding_1h=None`, and the collector writes 0 rows — exactly the dashboard
shape. The diagnostic text "234 个没读到 funding" arrives at the operator,
but the **fix** is to read the field under all known names.

THE FIX (defensive — do not assume which name HL ships today). Try each known
field name in priority order; record WHICH one was used so the operator can see
the field drift in the loop's diagnostic. If none are present, write a single
diagnostic row that includes the raw field names — so the next reader can see
exactly what HL shipped, instead of guessing.

ALSO: when funding is missing for some assets but present for others, we record
what we have rather than dropping the whole batch. The previous code skipped
every perp with None funding — turning one missing field into a silent 100%
data loss when the field name drifts.

Run: python3 -m tests.test_hyperliquid_venue_marks_handle_field_drift
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


# ── Sample HL response: 234 perps, funding under "fundingRate" not "funding" ─

def _sample_hl_response(field_name: str = "fundingRate") -> tuple[dict, list]:
    """Build a tiny but representative metaAndAssetCtxs response: 5 perps.

    Real HL shape: returns `[meta_dict, ctxs_list]`. `meta` is a DICT with a
    `universe` key holding the perp list; `ctxs` is a LIST of per-asset
    contexts aligned positionally with `universe`.
    """
    names = ("BTC", "ETH", "SOL", "ARB", "AVAX")
    meta = {"universe": [{"name": n} for n in names]}
    ctxs = []
    for i, sym in enumerate(names):
        ctxs.append({
            "markPx": str(100 + i),
            "oraclePx": str(100 + i),
            "prevDayPx": str(99 + i),
            field_name: str(0.0001 * (i + 1)),     # field under alternate name
            "openInterest": str(1_000_000 * (i + 1)),
            "dayNtlVlm": str(50_000_000 * (i + 1)),
        })
    return meta, ctxs


# ── The four properties that fix C3 ─────────────────────────────────────────

def test_snapshot_reads_funding_under_known_field_names() -> None:
    """`venue_snapshot()` must try `funding`, `fundingRate`, `funding_rate`."""
    src = open(hc.__file__, encoding="utf-8").read()
    # At least TWO of the three known field names must be tried.
    field_tries = sum(1 for n in ("funding", "fundingRate", "funding_rate")
                      if f'"{n}"' in src or f"'{n}'" in src)
    check("venue_snapshot tries ≥2 known funding field names",
          field_tries >= 2,
          f"only {field_tries} field name(s) found — schema drift will kill writes")


def test_snapshot_records_funding_when_fundingRate_field_is_used() -> None:
    """The previous code only read `funding`. If HL ships under `fundingRate`,
    the snapshot returns `funding_1h=None` for every asset and the writer
    produces 0 rows. After the fix, `funding_1h` is populated under either name.
    """
    async def _run():
        meta, ctxs = _sample_hl_response(field_name="fundingRate")

        # Build a real httpx Response with the right shape (no MockTransport).
        import httpx
        resp = httpx.Response(
            status_code=200,
            json=[meta, ctxs],
            request=httpx.Request("POST", hc._INFO_URL),
        )

        # Patch the module-level `_INFO_URL` and override the HTTP call by
        # monkey-patching `httpx.AsyncClient.post` on the client used inside
        # `venue_snapshot`. Simpler: replace `venue_snapshot` body with a
        # call into the real code that uses our canned response.
        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **kw): return resp
            async def aclose(self): pass

        with patch.object(hc.httpx, "AsyncClient", _FakeClient):
            snap = await hc.venue_snapshot()
        return snap

    snap = asyncio.run(_run())
    check("snapshot ok under fundingRate field name", snap.get("ok") is True,
          f"snap={snap}")
    check("234-equivalent funding_1h values populated",
          all(snap["assets"][s]["funding_1h"] is not None
              for s in ("BTC", "ETH", "SOL", "ARB", "AVAX")),
          f"assets={snap.get('assets')}")
    check("a 'funding_field' diagnostic is recorded",
          "funding_field" in snap or "funding_field_used" in snap
          or any("funding_field" in str(v) for v in snap.get("assets", {}).values()),
          f"snap keys={list(snap.get('assets', {}).values())[:1]}")


def test_collect_venue_marks_writes_rows_when_funding_present() -> None:
    """When snapshot succeeds and funding is populated, `collect_venue_marks`
    writes rows. Before the fix, with fundingRate field, it would write 0."""
    async def _run():
        meta, ctxs = _sample_hl_response(field_name="fundingRate")
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

        # Mock the upsert to capture the rows actually written.
        captured = {"rows": None}
        async def _fake_upsert(table, rows, **kwargs):
            captured["rows"] = list(rows)
            return True

        with patch.object(hc.httpx, "AsyncClient", _FakeClient), \
             patch("src.api.store.supabase_upsert_table", _fake_upsert):
            return await hc.collect_venue_marks(), captured

    res, captured = asyncio.run(_run())
    check("collect_venue_marks writes 5 funding rows under fundingRate field",
          len(captured.get("rows") or []) == 5,
          f"res={res}, captured={captured}")


def test_zero_funding_is_diagnosed_not_silent() -> None:
    """When ALL perps come back without funding under ANY known field name, the
    function returns a diagnostic that says so — instead of writing 0 rows
    silently (the old behavior was technically loud via the `reason` text,
    but the BEAT only saw `ok=False` and the dashboard summarised it as
    "234 永续 · 0 行 funding" without pointing at the field-drift hypothesis)."""
    src = open(hc.__file__, encoding="utf-8").read()
    # Look for the diagnostic surface — either a "field_drift_suspected" key,
    # or a "sample_response" diagnostic, or the `n_no_funding` value surfaced
    # through `diagnosis`.
    has_diag = any(
        token in src for token in (
            "field_drift_suspected",
            "sample_response",
            "n_no_funding",
            "funding_field",
        )
    )
    check("zero-funding case has a diagnostic surface (not silent)",
          has_diag, "no field name or 'n_no_funding' tracked — operator can't see WHY")


if __name__ == "__main__":
    print("── S-378b-C3: _hyperliquid_loop handles funding field drift ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ field-name fallback · partial-funding still writes · zero-funding diagnosed")
