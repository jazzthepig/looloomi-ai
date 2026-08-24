"""Guards for the asset_embeddings writer (S-220).

The defect was not a broken loop — it was NO loop. So the properties worth
guarding are the ones that make "no writer" and "a writer that declined" and
"a writer that failed" three distinguishable states, plus the floor that must
return BEFORE the write rather than annotate the return value (S-190).
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.vector.embedding_loop import (                        # noqa: E402
    BUDGET_S, INTERVAL_S, MIN_UNIVERSE, RebuildResult, rebuild_once)
from tests._source import code_only                                 # noqa: E402

_fails: list[str] = []


def check(cond: bool, label: str) -> None:
    if not cond:
        _fails.append(label)


# ── 1. a refusal is `degraded` and carries its reason ────────────────────────
p = RebuildResult(False, reason="universe has 3 assets").as_payload()
check(p["status"] == "degraded", "a refusal reported status ok")
check(p.get("reason"), "a refusal shipped without a reason")
check(p["written"] == 0, "a refusal claimed rows written")

ok = RebuildResult(True, written=58, schema_version=3, dims=27).as_payload()
check(ok["status"] == "ok" and "reason" not in ok,
      "a successful rebuild carried a failure reason")
check("verify" in ok, "the payload lost its verify query — 58 rows and 58 rows of "
                      "the WRONG SHAPE look identical in a row count")


# ── 2. THE FLOOR RETURNS BEFORE THE WRITE (S-190) ────────────────────────────
# deep_panel_collector's floor only annotated the return value while the write
# went ahead, so a 1-of-262 run still made max(trade_date) read as current.
# Construct check: in rebuild_once, every `len(...) < MIN_UNIVERSE` branch must
# contain a Return, and no upsert may appear inside it.
_src = (ROOT / "src/data/vector/embedding_loop.py").read_text()
_tree = ast.parse(_src)
_fn = next((n for n in ast.walk(_tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "rebuild_once"), None)
check(_fn is not None, "rebuild_once not found")
if _fn is not None:
    floor_branches = [
        n for n in ast.walk(_fn)
        if isinstance(n, ast.If) and any(
            isinstance(c, ast.Name) and c.id == "MIN_UNIVERSE" for c in ast.walk(n.test))]
    check(len(floor_branches) >= 2,
          f"expected a floor on both the universe and the embedder output, "
          f"found {len(floor_branches)}")
    for br in floor_branches:
        check(any(isinstance(n, ast.Return) for n in ast.walk(br)),
              "a MIN_UNIVERSE branch does not return — a floor that only annotates "
              "the return value is not a floor (S-190)")
        wrote = [n for n in ast.walk(br) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", getattr(n.func, "attr", None))
                 == "upsert_embeddings"]
        check(not wrote, "a MIN_UNIVERSE branch writes anyway")


# ── 3. rebuild_once never raises, and it never reaches the network here ──────
# It runs inside a loop; an exception escaping it kills the schedule silently,
# which is indistinguishable from the 31 days of no writer at all.
#
# ⚠️ THE FIRST VERSION OF THIS CHECK CALLED rebuild_once() BARE — and it went
# out to the live CIS universe from inside preflight, printing five T2 branch
# timeouts. Preflight is credential-free and offline by construction (S-163);
# a guard that phones out is machine-dependent and slow, which is how the gate
# got that way the first time. The universe is stubbed instead.
import src.data.cis.cis_provider as _cp                             # noqa: E402


async def _fake_universe():
    return {"universe": [{"symbol": f"S{i}", "macro_regime": "NEUTRAL"}
                         for i in range(3)]}          # 3 < MIN_UNIVERSE


_orig = _cp.calculate_cis_universe
_cp.calculate_cis_universe = _fake_universe
try:
    res = asyncio.run(rebuild_once())
finally:
    _cp.calculate_cis_universe = _orig

check(isinstance(res, RebuildResult), "rebuild_once did not return a RebuildResult")
check(res.ok is False, "rebuild_once wrote from a 3-asset universe")
check(bool(res.reason) and "MIN_UNIVERSE" in res.reason,
      f"the thin-universe refusal did not name the floor: {res.reason!r}")


# ── 4. ONE implementation, not two ───────────────────────────────────────────
# The rebuild used to live only in the router. A loop that re-implemented it
# would be the third instance this session of two versions of one rule.
#
# Scoped to the rebuild ENDPOINT, not the whole module: `/internal/asset-vectors`
# (the inbound receiver) legitimately embeds payloads Minimax pushes, and a guard
# that banned the name file-wide would be asserting something untrue.
_router_src = (ROOT / "src/api/routers/vector.py").read_text()
_r_tree = ast.parse(_router_src)
_rebuild_fn = next((n for n in ast.walk(_r_tree)
                    if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == "rebuild_asset_vectors"), None)
check(_rebuild_fn is not None, "rebuild_asset_vectors endpoint not found")
if _rebuild_fn is not None:
    called = {getattr(n.func, "id", getattr(n.func, "attr", None))
              for n in ast.walk(_rebuild_fn) if isinstance(n, ast.Call)}
    check("rebuild_once" in called,
          "the rebuild endpoint no longer delegates to embedding_loop.rebuild_once")
    check("generate_embedding" not in called,
          "the rebuild endpoint re-implements the embedding walk — one rule, "
          "one implementation")


# ── 5. THE LOOP IS ACTUALLY SCHEDULED ────────────────────────────────────────
# The whole defect was a writer that EXISTED and was never called, so this is
# the one guard that had to hold — and the first version of it did not.
#
# v1 checked `"_embedding_rebuild_loop" in main.py` plus "create_task" appearing
# somewhere in the 400 characters after the hook's name. Replacing
# `create_task(_embedding_rebuild_loop())` with `pass` SURVIVED: the function
# definition still carries the name, and a neighbouring hook supplied a
# create_task within the window. A substring guard cannot tell a definition from
# a call, which is the entire distinction here — the 31 stale days were a defined
# writer nobody invoked.
#
# Construct: the startup hook must contain create_task(_embedding_rebuild_loop()).
_main_tree = ast.parse((ROOT / "src/api/main.py").read_text())
_hook = next((n for n in ast.walk(_main_tree)
              if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
              and n.name == "_start_embedding_rebuild"), None)
check(_hook is not None, "no _start_embedding_rebuild hook in main.py")
_scheduled = False
if _hook is not None:
    for node in ast.walk(_hook):
        if not isinstance(node, ast.Call):
            continue
        fname = getattr(node.func, "attr", getattr(node.func, "id", None))
        if fname != "create_task":
            continue
        for arg in node.args:
            inner = getattr(getattr(arg, "func", None), "id", None)
            if inner == "_embedding_rebuild_loop":
                _scheduled = True
check(_scheduled,
      "_start_embedding_rebuild does not create_task(_embedding_rebuild_loop()) — "
      "a writer that is defined and never invoked is precisely the 31-day defect")

_loop_fn = next((n for n in ast.walk(_main_tree)
                 if isinstance(n, ast.AsyncFunctionDef)
                 and n.name == "_embedding_rebuild_loop"), None)
check(_loop_fn is not None, "_embedding_rebuild_loop is gone from main.py")
if _loop_fn is not None:
    _calls = {getattr(n.func, "attr", getattr(n.func, "id", None))
              for n in ast.walk(_loop_fn) if isinstance(n, ast.Call)}
    check("rebuild_once" in _calls,
          "the loop no longer calls rebuild_once — it schedules something else")

check(INTERVAL_S <= 24 * 3600, "rebuild interval is slower than daily")
check(BUDGET_S < INTERVAL_S, "a run may outlive its own schedule")
check(MIN_UNIVERSE >= 20, "the universe floor is below the observed panel size")

if _fails:
    print("✗ embedding-loop guards FAILED:")
    for f in _fails:
        print("   ·", f)
    sys.exit(1)
print(f"  ✓ embedding loop (S-220): floor returns before write, refusal ≠ failure, "
      f"one implementation, and the loop is scheduled")
