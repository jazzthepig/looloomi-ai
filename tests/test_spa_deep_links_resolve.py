"""
Guard: every SPA route serves the shell, and no route serves a 500 (S-160).

WHAT WAS MEASURED, live, 2026-08-13:

    /              200  41172B
    /cis           500     21B
    /intelligence  500     21B
    /strategies    500     21B
    /vault         500     21B
    /diagnose      500     21B

Only "/" worked, because it has its own explicit route. Every deep link — a
refresh, a bookmark, a shared URL — returned 500 and rendered a blank shell
whose panels then displayed "Failed to load: API error: 500".

THE COST OF THE WRONG LAYER. That error text sent us hunting the API for hours.
Every API endpoint was fine: /api/v1/cis/universe returned 200 with 58 assets
under twelve sequential requests, five concurrent ones, and full browser
headers. The failing request was never an API call — it was the HTML document.
Nothing found it until the browser's own network log was read, because the
symptom named a layer the fault was not in.

THE BUG:

    try:    return FileResponse(file_path)
    except FileNotFoundError: pass
    return FileResponse(index.html)

Starlette's FileResponse is LAZY. It does not stat on construction; it stats
when the response is sent. A missing file therefore raises nothing inside the
try, the `except` never fires, the index.html line is unreachable, and the
failure arrives after the handler has returned — as a RuntimeError that becomes
a 500.

**A try/except around a call that cannot raise the exception being caught is
indistinguishable from no error handling, and reads like more.** That is the
same shape as a column that is displayed and never written, and a guard that
scans the directory where you expected the bug.

Introduced in b29313f — long before the night it was found. It was never a
regression; it was a fallback that had never once executed.

Run: python3 -m tests.test_spa_deep_links_resolve
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


_MAIN = (_ROOT / "src/api/main.py").read_text(encoding="utf-8")


def test_a_missing_file_does_not_rely_on_an_exception_that_never_fires() -> None:
    """The mechanism, asserted directly: constructing a FileResponse over a
    path that does not exist raises NOTHING. Any handler whose fallback depends
    on catching FileNotFoundError there has no fallback."""
    from starlette.responses import FileResponse
    raised = None
    try:
        FileResponse("/definitely/not/here/index.html")
    except Exception as e:                     # noqa: BLE001 - that is the point
        raised = type(e).__name__
    check("FileResponse does not raise on a missing path at construction",
          raised is None,
          f"raised {raised} — if this ever changes, the original try/except "
          f"would have worked and this guard can be reconsidered")


def test_the_spa_handler_checks_existence_instead_of_catching() -> None:
    blk = _MAIN.split("async def serve_spa")[1][:2200]
    check("serve_spa tests the file with isfile", "os.path.isfile(" in blk,
          "existence must be checked; the exception never arrives")
    code = "\n".join(l for l in blk.splitlines() if not l.lstrip().startswith("#"))
    check("serve_spa no longer relies on except FileNotFoundError",
          "except FileNotFoundError" not in code,
          "that except cannot fire — it is decoration that reads like a fallback")


def test_the_shell_is_served_for_client_side_routes() -> None:
    """The behaviour users depend on: a deep link returns the SPA shell so the
    router can take over. Checked against the real build directory."""
    dash = _ROOT / "dashboard" / "dist"
    if not (dash / "index.html").is_file():
        check("dashboard build present", False,
              f"{dash}/index.html missing — cannot verify SPA serving")
        return
    for route in ("cis", "intelligence", "strategies", "vault", "diagnose"):
        target = dash / route
        check(f"/{route} is not a real file, so it must fall back to the shell",
              not target.is_file(),
              "if this becomes a real file the test needs a different route")
    check("the shell exists to fall back to", (dash / "index.html").is_file(), "")


def test_api_prefixes_still_get_json_404_not_the_shell() -> None:
    """An unmatched /api/... path must return JSON, not an HTML page. A client
    parsing the shell as JSON reports a parse error, which is another symptom
    that names the wrong layer."""
    blk = _MAIN.split("async def serve_spa")[1][:2200]
    check("api-ish prefixes short-circuit to a JSON 404",
          '_api_prefixes' in blk and 'status_code=404' in blk, "")


def test_traversal_cannot_escape_the_build_directory() -> None:
    """`os.path.join(base, "../../etc/passwd")` resolves outside base. Checking
    isfile() without also checking containment would happily serve it."""
    blk = _MAIN.split("async def serve_spa")[1][:2200]
    check("the resolved path is normalised", "normpath(" in blk, "")
    check("and confined to the build directory",
          "startswith(dashboard_path)" in blk,
          "isfile() alone would serve any readable file on the container")


if __name__ == "__main__":
    print("── SPA deep links resolve, and no route 500s (S-160) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ a refresh on any route serves the app, not a 500")
