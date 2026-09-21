"""
S-389 FIX-A: `fusion_paper_nav` mark_date 409 unique violation → upsert.

THE BUG. `fusion_paper._write_nav` writes through `insert_with_detail`, which
underneath is `supabase_insert_table` semantics — INSERT, not UPSERT. On a
retry / re-run of the same `mark_date`, the second INSERT hits Postgres'
UNIQUE(mark_date) constraint and answers HTTP 409 / code 23505. Measured
2026-09-20, ops-console post-deploy verification (`_fusion_paper_loop`):
    detail=mark_failed :: durable_write_failed :: fusion_paper_nav?:
      HTTP 409 [204ms] — {"code":"23505","details":"Key
      (mark_date)=(2026-09-20) already exists."}
The 409 surfaces as `detail.outcome='http_error'`, `status=409`, and
`_write_nav` returns `(False, why)` → `mark_and_rebalance` returns
`{"status":"mark_failed", ...}`.

THE FIX (FIX-A ⭐ per MINIMAX_SYNC §S-389). Make `insert_with_detail` accept
`on_conflict: str | None = None`. When set, the URL becomes
`?on_conflict=<value>` and the `Prefer` header adds
`resolution=merge-duplicates`. PostgREST then answers 200/201/204 instead of
409, and the second write silently merges into the existing row.

Two contracts to guard:

  T1. `insert_with_detail` accepts the kwarg and forwards it to URL+Prefer.
  T2. The insert path is preserved when `on_conflict` is unset — adding the
      parameter must not change behaviour for the nine other books that do
      not need upsert semantics.
  T3. `fusion_paper._write_nav` passes `on_conflict='mark_date'` at the call
      site. AST-level so a rename / move / accidental kwarg drop cannot ship
      without the test failing.

Run: python3 -m tests.test_fusion_paper_mark_date_upsert
"""
from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


class _FakeResp:
    """Minimal httpx.Response-shaped stand-in."""
    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.text = text


async def _run_insert_with_detail(**kw):
    """Call `insert_with_detail` and return (ok, detail, captured_request)."""
    from src.api import rpc_diagnostics
    from src.api import store
    from src.api import runtime_role

    captured: dict = {}

    async def fake_retry(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers") or {}
        # Default success; tests can swap via re-patching if they want 409.
        return _FakeResp(201)

    # role gate sits BEFORE URL/Prefer are built. The test exercises URL+Prefer
    # wiring — bypass the gate so we get to the http call.
    with patch.object(runtime_role, "refuse_write", return_value=None), \
         patch.object(store, "_supabase_request_with_retry", side_effect=fake_retry), \
         patch.object(store, "_SB_URL", "http://test"), \
         patch.object(store, "_SB_KEY", "test-key"):
        ok, detail = await rpc_diagnostics.insert_with_detail(
            "fusion_paper_nav",
            [{"mark_date": "2026-09-20", "nav": 1.0}],
            **kw,
        )
    return ok, detail, captured


# ── T1: on_conflict wired into URL + Prefer ─────────────────────────────────
async def test_t1_insert_with_detail_uses_upsert_when_on_conflict_set():
    ok, detail, captured = await _run_insert_with_detail(on_conflict="mark_date")

    check("insert_with_detail accepted on_conflict kwarg",
          isinstance(ok, bool) and detail.get("outcome") == "ok",
          f"ok={ok} detail={detail}")
    check("URL carries ?on_conflict=mark_date (upsert, not insert)",
          captured.get("url", "").endswith("?on_conflict=mark_date"),
          f"url={captured.get('url')}")
    check("Prefer header carries resolution=merge-duplicates",
          "resolution=merge-duplicates" in (captured.get("headers") or {}).get("Prefer", ""),
          f"Prefer={(captured.get('headers') or {}).get('Prefer')}")
    check("Prefer header still has return=minimal (PostgREST contract)",
          "return=minimal" in (captured.get("headers") or {}).get("Prefer", ""),
          f"Prefer={(captured.get('headers') or {}).get('Prefer')}")


# ── T2: insert path preserved when on_conflict unset ────────────────────────
async def test_t2_insert_with_detail_keeps_insert_when_on_conflict_unset():
    ok, detail, captured = await _run_insert_with_detail()

    check("default (no on_conflict) succeeds",
          ok is True and detail.get("outcome") == "ok",
          f"ok={ok} detail={detail}")
    check("URL has no on_conflict query (insert path preserved)",
          "on_conflict" not in captured.get("url", ""),
          f"url={captured.get('url')}")
    check("Prefer header is bare return=minimal (no merge-duplicates)",
          (captured.get("headers") or {}).get("Prefer", "") == "return=minimal",
          f"Prefer={(captured.get('headers') or {}).get('Prefer')}")


# ── T3: call site in fusion_paper._write_nav actually passes on_conflict ───
def test_t3_fusion_paper_write_nav_call_site_uses_on_conflict_mark_date():
    """Regression guard: AST check on `fusion_paper.py`. The call to
    `insert_with_detail` MUST carry `on_conflict='mark_date'` kwarg.
    Without it the 409 returns on every retry.

    The first arg is the module-level `_NAV_TABLE` (Name node), so the test
    resolves it against module-level `ast.Assign` constants before comparing.
    """
    fp = _ROOT / "src" / "data" / "signals" / "fusion_paper.py"
    tree = ast.parse(fp.read_text(encoding="utf-8"))

    # Module-level constants: name -> string value.
    consts: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    consts[tgt.id] = node.value.value

    def _resolve_first_arg(arg_node) -> str | None:
        if isinstance(arg_node, ast.Constant) and isinstance(arg_node.value, str):
            return arg_node.value
        if isinstance(arg_node, ast.Name):
            return consts.get(arg_node.id)
        return None

    found_call = False
    found_kwarg = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn_name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fn_name != "insert_with_detail":
            continue
        # The call site we care about writes to _NAV_TABLE ("fusion_paper_nav")
        first = node.args[0] if node.args else None
        if _resolve_first_arg(first) != "fusion_paper_nav":
            continue
        found_call = True
        for kw in node.keywords:
            if kw.arg == "on_conflict" and isinstance(kw.value, ast.Constant) \
                    and kw.value.value == "mark_date":
                found_kwarg = True

    check("fusion_paper.py calls insert_with_detail('fusion_paper_nav', ...)",
          found_call, "the writer call site disappeared")
    check("the call carries on_conflict='mark_date' kwarg (FIX-A contract)",
          found_kwarg, "FIX-A contract not at the call site — _write_nav will 409 again")


if __name__ == "__main__":
    print("── S-389 FIX-A: fusion_paper_nav mark_date upsert ──")

    async def _run_async():
        await test_t1_insert_with_detail_uses_upsert_when_on_conflict_set()
        await test_t2_insert_with_detail_keeps_insert_when_on_conflict_unset()

    try:
        asyncio.run(_run_async())
    except Exception as e:                                      # noqa: BLE001
        print(f"  ✗ async phase crashed: {type(e).__name__}: {e}")
        _FAILURES.append("async-phase-crash")

    try:
        test_t3_fusion_paper_write_nav_call_site_uses_on_conflict_mark_date()
    except Exception as e:                                      # noqa: BLE001
        print(f"  ✗ T3 AST walk crashed: {type(e).__name__}: {e}")
        _FAILURES.append("t3-ast-crash")

    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ on_conflict wired into URL+Prefer · insert path preserved · call site carries on_conflict='mark_date'")
