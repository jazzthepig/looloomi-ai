"""
Guard: no literal route is shadowed by a path parameter (S-143).

WHAT WAS BROKEN, in production, silently:

    GET /api/v1/factors/performance  → 404 {"detail":"Factor 'performance' not found"}
    GET /api/v1/strategy/stats       → 404 {"detail":"record 'stats' not in strategy…"}

Both endpoints existed, were deployed, and were unreachable. FastAPI matches routes
in REGISTRATION order, and both files registered a single-segment `/{param}` route
BEFORE its literal siblings, so `/factors/{factor_id}` swallowed `/factors/performance`
with factor_id="performance".

WHY IT SURVIVED. The 404 message is PLAUSIBLE. "Factor 'performance' not found"
reads like the factor does not exist — a data question — rather than like the route
was hijacked, which is a routing question. Anyone checking would have concluded the
endpoint worked and the data was missing, and gone looking in the wrong place.

That is the same defect as everything else found this week: a failure that produces
a BELIEVABLE WRONG ANSWER rather than an error. The api_keys column name (S-138)
returned "Key storage failed", the 出圈 band (S-141) returned "low", the identity
column reported column_default=null. In each case the system answered confidently
and the answer was wrong in a way that invited a plausible false diagnosis.

Code review cannot catch this class: each route is individually correct, and the bug
is a property of their ORDER. Only the assembled app knows.

Run: python3 -m tests.test_no_route_is_shadowed
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("INTERNAL_TOKEN", "preflight")
os.environ.setdefault("ENVIRONMENT", "ci")

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


_PARAM = re.compile(r"\{[^}]+\}")


def _segments(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s]


def _shadows(earlier: str, later: str) -> bool:
    """Would a request for the LITERAL `later` path be matched by `earlier` first?

    Only same-length paths can collide, and only if every earlier segment is either
    identical or a parameter. `later` must contain no parameters of its own — a
    parameterised route being shadowed by another parameterised route is ambiguous
    by design and not what this guard is about."""
    a, b = _segments(earlier), _segments(later)
    if len(a) != len(b) or _PARAM.search(later):
        return False
    if not _PARAM.search(earlier):
        return False                      # two literals cannot shadow each other
    return all(sa == sb or _PARAM.fullmatch(sa) for sa, sb in zip(a, b))


_MIN_ROUTES = 150      # the app registers ~193; see the comment in the scan below


def _flatten(routes) -> list[tuple[str, list[str]]]:
    """Flatten app.routes IN MATCH ORDER, descending into included routers.

    Recent FastAPI wraps `include_router` results in `fastapi.routing._IncludedRouter`
    rather than splicing the child routes into `app.routes`. So a naive read of
    `app.routes` sees 27 opaque wrappers plus the 31 routes defined directly on
    `app` — and the ~160 router endpoints, including BOTH bugs this suite exists
    for, are invisible.

    The first version of this guard did exactly that and printed "no shadowed
    routes among 31 registered". True, and useless: 16 % coverage reported as a
    clean bill. That is the same defect the suite is about — a believable answer
    to a question that was not asked — committed inside the fix for it.

    `_IncludedRouter` is a FastAPI internal, so this can break on upgrade. It must
    break LOUDLY: `test_the_scan_actually_covers_the_app` asserts the count, so a
    structure change fails the build instead of silently shrinking coverage."""
    out: list[tuple[str, list[str]]] = []
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None and getattr(inner, "routes", None):
            out.extend(_flatten(inner.routes))
            continue
        # Mounts (StaticFiles) have a path but no methods — not routes in the
        # matching sense.
        if getattr(r, "path", None) and getattr(r, "methods", None):
            out.append((r.path, sorted(r.methods)))
    return out


def _all_routes() -> list[tuple[str, list[str]]]:
    """Every reachable route, flattened. IMPORT ONLY — the app is never started.

    This used to wrap the read in `with TestClient(app):` to "read after
    startup". Measured 2026-08-13: 201 routes before startup, 201 after,
    identical sets — routers are registered by `include_router` at IMPORT time,
    so startup contributes nothing to the route table.

    What it did contribute was 31 background loops hitting Moralis, CoinGecko,
    Binance and the paper books. That made a pure structural check depend on the
    network: instant in a sandbox with no egress, minutes-to-forever on a laptop
    with internet, and it hung the gate repeatedly on 2026-08-13.

    The fix is not a timeout on the boot; it is not booting. A test that reads a
    data structure should not start a server, and once it doesn't, there is no
    hang left to bound."""
    from src.api.main import app
    return _flatten(app.routes)


def test_the_scan_actually_covers_the_app() -> None:
    n = len(_all_routes())
    check(f"scan sees {n} routes (≥{_MIN_ROUTES})", n >= _MIN_ROUTES,
          f"only {n} routes visible — routers did not mount, so this suite is "
          f"reporting on a fraction of the surface while looking green")


def test_no_literal_route_is_shadowed_by_a_parameter() -> None:
    routes = _all_routes()

    hits: list[str] = []
    for i, (later, later_m) in enumerate(routes):
        for earlier, earlier_m in routes[:i]:
            if not set(earlier_m) & set(later_m):
                continue
            if _shadows(earlier, later):
                hits.append(f"{later} is unreachable — {earlier} matches it first")

    check(f"no shadowed routes among {len(routes)} registered",
          not hits, "\n      " + "\n      ".join(sorted(set(hits))[:12]))



def _flatten_objs(routes) -> list:
    """Same descent as _flatten, but keeps the route OBJECTS so their compiled
    path_regex can be used for matching."""
    out = []
    for r in routes:
        # `original_router`, the same attribute _flatten uses. The first cut of
        # this helper read `.router` — which no top-level object has — so it
        # silently returned 5 routes out of 201 and everything "resolved" to the
        # SPA catch-all. A wrong attribute name does not raise, it just makes the
        # scan agree with itself about nothing.
        inner = getattr(r, "original_router", None)
        if inner is not None and getattr(inner, "routes", None):
            out.extend(_flatten_objs(inner.routes))
            continue
        if getattr(r, "path_regex", None) is not None:
            out.append(r)
    return out


def _resolves_to(path: str) -> str | None:
    """Which route pattern does `path` actually reach? Compiled-regex matching in
    REGISTRATION ORDER — the handler is never called.

    The earlier version issued real GETs against /api/v1/factors/performance,
    /api/v1/strategy/stats and two more. Those endpoints fetch live provider
    data, so on a machine with network this suite took minutes; on 2026-08-13 it
    hung preflight past 117s while the two fast ones had already answered 200
    and 404.

    The claim being tested is a ROUTING fact — does the literal path reach the
    literal route, or does the {param} sibling swallow it. Asking the data stack
    to answer it drags CoinGecko into a question about registration order and
    makes the gate's runtime a property of the network. **Assert at the layer of
    the claim.**"""
    from src.api.main import app
    for r in _flatten_objs(app.routes):
        if r.path_regex.match(path):
            return getattr(r, "path", None)
    return None


def test_the_two_known_victims_now_answer() -> None:
    """Named explicitly because a generic guard passing is not evidence that THESE
    were fixed — it is evidence that nothing is currently shadowed, which is also
    true of an app where both endpoints were deleted."""
    for ep in ("/api/v1/factors/performance", "/api/v1/strategy/stats"):
        got = _resolves_to(ep)
        check(f"{ep} reaches its own literal route", got == ep,
              f"resolves to {got!r} instead — still shadowed, or the endpoint is gone")


def test_the_parameterised_sibling_still_works() -> None:
    """Reordering must not have broken the route it was moved behind. A fix that
    trades one dead endpoint for another is not a fix."""
    got = _resolves_to("/api/v1/factors/market_cap")
    check("/api/v1/factors/{factor_id} still catches a non-literal id",
          got == "/api/v1/factors/{factor_id}", f"resolves to {got!r}")
    got2 = _resolves_to("/api/v1/factors/definitely_not_a_factor")
    check("and an unknown id lands on the same parameterised route",
          got2 == "/api/v1/factors/{factor_id}", f"resolves to {got2!r}")


def test_this_suite_never_starts_the_app() -> None:
    """Locks the fix in. Every question this file asks — which routes exist, and
    which pattern a path resolves to — is answerable from the route table. The
    moment someone reaches for the test client again to answer one of them, this
    suite becomes network-dependent and can hang the gate, which it did three
    times on 2026-08-13 before the cause was found.

    Checked with the AST, not with a text search. The first cut grepped the file
    for the class name and fired on its OWN docstring — the guard matching the
    sentence that explains the guard. That has now bitten five times in this
    repo, so: parse, and look at code."""
    import ast
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))

    imports_client, http_calls = [], []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and "testclient" in n.module.lower():
            imports_client.append(n.lineno)
        if isinstance(n, ast.Import):
            imports_client += [n.lineno for a in n.names if "testclient" in a.name.lower()]
        # a request against a literal path, e.g. client.get("/api/...")
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("get", "post", "put", "delete", "patch")
                and n.args and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str) and n.args[0].value.startswith("/")):
            http_calls.append(n.lineno)

    check("this suite never imports a test client", not imports_client,
          f"lines {imports_client} — booting the app to read its routes makes a "
          f"structural check depend on CoinGecko being up")
    check("and never issues a request to answer a routing question",
          not http_calls,
          f"lines {http_calls} — a request runs the handler, and the handler is "
          f"the data stack")


if __name__ == "__main__":
    print("── no route is shadowed by a path parameter (S-143) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ every registered route is reachable")
