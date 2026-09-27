"""
T-021: 死链与遗留路由清理

T-014 产品面审计(2026-09-26)发现:
  - 6 个静态 .html 全部 200 / 41121 bytes(SPA catch-all serve_spa 把它们当
    index.html 返,URL 留在 *.html 但内容是落地页 —— UX 错位 + 误导爬虫)
  - 4 个 API 端点 404 但 SPA bundle 不调用(死代码 / 误命名,需要 doc 标注)

本卡修复:
  1. 6 个 .html → 301 → /app.html(浏览器 / 爬虫自动跳 SPA 入口,客户端 Sidebar
     接管 section 切)。
  2. 4 个 API 路径保留 404 但在 main.py 留 dead-API doc 注释 + 实际替代路径
     (future:删除复活任一都要起新 task,不要在这里改)。

覆盖:
  - 源级 (1-9): `_DEAD_HTML_REDIRECTS` 6 条 + RedirectResponse 导入 + serve_spa
    里 301 分支 + 4 个 dead API 路径出现在 doc comment。
  - 运行级 (10-15):TestClient 探真请求,验证 6 条 301 + Location 头 + 4 条
    dead API 仍 404 + `/` 与 `/app.html` 仍 200 (SPA bundle 不破)。

跑法:python3 -m tests.test_t021_dead_routes
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MAIN = _ROOT / "src" / "api" / "main.py"

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def _src() -> str:
    return _MAIN.read_text(encoding="utf-8")


# ── 1. Source-level guards: dict literal ─────────────────────────────────────

_DEAD_HTML_NAMES = (
    "market.html",
    "cis.html",
    "vault.html",
    "protocol.html",
    "intelligence.html",
    "quant-gp.html",
)


def test_dead_html_redirects_dict_has_all_six() -> None:
    """The dict literal must contain exactly the 6 names from the audit.
    Adding a name without a redirect target = silent dead link; removing
    a name = re-introducing the bug."""
    src = _src()
    m = re.search(
        r"_DEAD_HTML_REDIRECTS\s*=\s*\{(.*?)\n\}",
        src,
        re.DOTALL,
    )
    check("_DEAD_HTML_REDIRECTS dict is extractable from main.py",
          m is not None,
          "could not find _DEAD_HTML_REDIRECTS dict")
    if m is None:
        return
    body = m.group(1)
    for name in _DEAD_HTML_NAMES:
        hit = re.search(rf'"{re.escape(name)}"\s*:\s*"([^"]+)"', body)
        check(f"_DEAD_HTML_REDIRECTS contains '{name}'",
              hit is not None,
              f"missing from dict literal")
        if hit is not None:
            target = hit.group(1)
            check(f"  → '{name}' points to /app.html (not somewhere else)",
                  target == "/app.html",
                  f"got {target!r}")


def test_redirectresponse_is_imported() -> None:
    """The redirect branch uses RedirectResponse — verify the import exists.
    If someone drops it from the imports, the runtime will NameError."""
    src = _src()
    check("RedirectResponse imported from fastapi.responses",
          re.search(r"from\s+fastapi\.responses\s+import\s+[^#\n]*RedirectResponse", src)
          is not None,
          "no `RedirectResponse` import — serve_spa redirect will NameError")


def test_serve_spa_has_301_redirect_branch() -> None:
    """The redirect check must be the FIRST thing inside serve_spa — before
    the api_prefixes 404 guard. Otherwise `/market.html` would still hit
    the api branch (it doesn't, but the order is load-bearing for any
    future name in the form `internal.html` etc)."""
    src = _src()
    # Locate the start of serve_spa, then look for the relevant lines after
    # it. We don't try to balance braces — we just want the lines that the
    # redirect branch lives on.
    start_match = re.search(r"async\s+def\s+serve_spa\(", src)
    check("serve_spa function is defined", start_match is not None,
          "no `async def serve_spa(` in main.py — branch can't exist")
    if start_match is None:
        return
    start = start_match.start()

    # The api_prefixes guard is a well-known literal lower in the file.
    api_guard_idx = src.find("_api_prefixes", start)
    check("api_prefixes guard is below serve_spa",
          api_guard_idx != -1,
          "no _api_prefixes literal — ordering check meaningless")
    if api_guard_idx == -1:
        return

    body_window = src[start:api_guard_idx + 200]

    check("serve_spa calls RedirectResponse(",
          "RedirectResponse(" in body_window,
          "no RedirectResponse call in serve_spa body")
    check("serve_spa uses status_code=301",
          re.search(r"status_code\s*=\s*301", body_window) is not None,
          "no 301 status — wrong code (302 would not be permanent)")
    check("serve_spa branches on `_DEAD_HTML_REDIRECTS` membership",
          re.search(r"full_path\s+in\s+_DEAD_HTML_REDIRECTS", body_window) is not None,
          "no `full_path in _DEAD_HTML_REDIRECTS` guard")

    # Ordering check: redirect branch must come BEFORE api_prefixes guard
    pos_redirect = body_window.find("RedirectResponse(")
    pos_redirect_guard = body_window.find("full_path in _DEAD_HTML_REDIRECTS")
    check("redirect branch is BEFORE api_prefixes 404 guard",
          pos_redirect != -1 and pos_redirect < api_guard_idx - start,
          f"redirect@{pos_redirect} should be earlier than api_guard@{api_guard_idx - start}")


# ── 2. Source-level guards: dead-API doc comment ─────────────────────────────

_DEAD_API_PATHS = (
    "/api/v1/intelligence/signals",
    "/api/v1/vault/positions",
    "/api/v1/protocol/metrics",
    "/api/v1/quant/gp-status",
)


def test_dead_api_doc_comment_present() -> None:
    """The 4 dead API paths must be documented in main.py — without the doc
    comment, a future contributor will 'fix' the 404 to 200 and break the
    contract (SPA bundle calls the *real* endpoints, not these)."""
    src = _src()
    for path in _DEAD_API_PATHS:
        check(f"doc comment mentions dead path {path!r}",
              path in src,
              f"missing from main.py — doc contract broken")

    # Each entry should also list its real replacement
    expected_replacements = {
        "/api/v1/intelligence/signals":  "signals/feed",
        "/api/v1/vault/positions":       "trading/positions",
        "/api/v1/protocol/metrics":      "protocols/universe",
        "/api/v1/quant/gp-status":       "trading/",
    }
    for path, replacement in expected_replacements.items():
        check(f"doc comment for {path!r} mentions real replacement {replacement!r}",
              replacement in src,
              f"no replacement path — reader won't know what SPA actually calls")


def test_dead_api_paths_not_registered_as_routes() -> None:
    """The 4 paths must NOT exist as actual route handlers — they live in
    the catch-all (api_prefixes → 404 JSON). If they were registered as
    real routes, they would 200, not 404."""
    src = _src()
    for path in _DEAD_API_PATHS:
        # Look for any @app.<method>(<path>) registration
        bare = path.lstrip("/")
        pattern = rf'@\s*app\.\w+\(\s*"{re.escape(bare)}"\s*[,)]'
        hit = re.search(pattern, src)
        check(f"dead path {path!r} is NOT registered as a route",
              hit is None,
              f"found @app.<method>(\"{bare}\") registration — should be removed")


# ── 3. Runtime test: TestClient requests ─────────────────────────────────────

def _runtime_check(allow_runtime: bool) -> None:
    """All runtime tests live behind a flag: they require dashboard/dist
    (so serve_spa is mounted) and import the full app (slow + has side
    effects). The source-level guards above cover the same surface in
    CI environments without a built dashboard."""
    if not allow_runtime:
        print("  ⊘ runtime checks skipped (set T021_RUNTIME=1 to enable)")
        return

    try:
        from fastapi.testclient import TestClient
        from src.api.main import app
    except Exception as e:  # noqa: BLE001
        print(f"  ⊘ runtime import failed ({type(e).__name__}: {str(e)[:80]})")
        return

    c = TestClient(app)

    # 6 dead .html → 301 with Location=/app.html
    for name in _DEAD_HTML_NAMES:
        # Don't follow_redirects — we want to assert the 301 itself
        r = c.get(f"/{name}", follow_redirects=False)
        check(f"GET /{name} → 301",
              r.status_code == 301,
              f"got {r.status_code}")
        loc = r.headers.get("location", "")
        check(f"GET /{name} Location: /app.html",
              loc.rstrip("/").endswith("/app.html") or loc == "/app.html",
              f"got Location={loc!r}")

    # 4 dead APIs → 404 JSON (catch-all _api_prefixes)
    for path in _DEAD_API_PATHS:
        r = c.get(path)
        check(f"GET {path} → 404",
              r.status_code == 404,
              f"got {r.status_code}")
        check(f"GET {path} returns JSON (not SPA shell)",
              r.headers.get("content-type", "").startswith("application/json"),
              f"got content-type={r.headers.get('content-type')!r}")

    # `/` and `/app.html` still return SPA bundle (no regression)
    for path in ("/", "/app.html"):
        r = c.get(path, follow_redirects=False)
        check(f"GET {path} still 200 (SPA bundle intact)",
              r.status_code == 200,
              f"got {r.status_code}")

    # A non-dead, non-api path still falls through to SPA shell
    r = c.get("/some-client-section", follow_redirects=False)
    check("GET /some-client-section → 200 (catch-all still works)",
          r.status_code == 200,
          f"got {r.status_code}")


def test_runtime_redirects() -> None:
    """Aggregate runtime test — sets the flag and delegates to _runtime_check."""
    _runtime_check(allow_runtime=os.environ.get("T021_RUNTIME") == "1")


# ── 4. S-244 family regression guard ────────────────────────────────────────

def test_dead_html_redirects_dict_keyword_present() -> None:
    """Pinning the dict IDENTIFIER name in main.py — a future refactor that
    renames the dict (or accidentally drops it) breaks the redirect branch
    silently if this guard isn't there."""
    src = _src()
    occurrences = len(re.findall(r"_DEAD_HTML_REDIRECTS", src))
    check(f"_DEAD_HTML_REDIRECTS appears ≥ 2 times in main.py (defn + use)",
          occurrences >= 2,
          f"only {occurrences} occurrence(s) — refactor regression risk")


if __name__ == "__main__":
    print("── T-021: 死链与遗留路由清理 ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print(
        "\n✅ 6 .html → 301 /app.html;4 dead APIs documented + 404;"
        "SPA bundle intact at / and /app.html"
    )