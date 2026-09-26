"""
T-013: 首页和页面路由免于限流

当 anon IP 触发 429 时:
  - API 请求 (/api/v1/*, /internal/*)  → JSON 429(SDK 可解析)
  - 页面请求 (/)                       → HTML 200 + meta refresh 提示

测试验证:同 IP 限流后访问 / 仍是 HTML 200,而不是 JSON 429。

跑法:python3 -m tests.test_rate_limit_page_html_429
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.api.middleware import rate_limit as rl   # noqa: E402

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


# ── Helpers ────────────────────────────────────────────────────────────────

class _FakeRequest:
    """Minimal Request stand-in: only `.url.path` is touched."""
    def __init__(self, path: str):
        self.url = type("u", (), {"path": path})()
        self.headers = {}
        self.client = type("c", (), {"host": "1.2.3.4"})()


def _exhaust(identity_kind: str = "ip:1.2.3.4") -> None:
    """Force the rpm counter above 120 for the test identity."""
    rl._key_cache.clear()
    return None  # the test calls redis_incr with explicit count


async def _drive(middleware: rl.RateLimitMiddleware, request,
                 rpm_count: int, rpd_count: int):
    """Call middleware.dispatch with mocked counters."""
    async def call_next(_request):
        return type("R", (), {"status_code": 200, "headers": {}})()

    with patch.object(rl, "_redis_incr", new=AsyncMock(side_effect=[rpm_count, rpd_count])):
        return await middleware.dispatch(request, call_next)


def _make_middleware() -> rl.RateLimitMiddleware:
    return rl.RateLimitMiddleware(app=None)


# ── Properties T-013 requires ──────────────────────────────────────────────

async def test_page_request_returns_html_200_on_minute_429() -> None:
    """Anon IP hitting 429 on `/` returns HTML 200, not JSON 429."""
    mw = _make_middleware()
    req = _FakeRequest("/")
    resp = await _drive(mw, req, rpm_count=121, rpd_count=1)

    check("page 429 returns 200, not 429",
          resp.status_code == 200,
          f"status={resp.status_code}")
    check("page 429 returns HTML, not JSON",
          "text/html" in resp.headers.get("content-type", ""),
          f"content_type={resp.headers.get('content-type')}")
    check("HTML body has meta refresh for auto-retry",
          "http-equiv=refresh" in resp.body.decode("utf-8", errors="replace"),
          f"body[:200]={resp.body[:200]!r}")
    check("HTML body mentions rate limit (English)",
          "Rate limited" in resp.body.decode("utf-8", errors="replace"),
          "missing human-readable label")


async def test_api_request_returns_json_429_on_minute_429() -> None:
    """Anon IP hitting 429 on `/api/v1/...` keeps JSON 429 envelope (regression)."""
    mw = _make_middleware()
    req = _FakeRequest("/api/v1/cis/universe")
    resp = await _drive(mw, req, rpm_count=121, rpd_count=1)

    check("API 429 keeps 429 status",
          resp.status_code == 429,
          f"status={resp.status_code}")
    check("API 429 keeps JSON envelope",
          resp.headers.get("content-type", "").startswith("application/json"),
          f"content_type={resp.headers.get('content-type')}")
    check("API 429 body has error: rate_limit_exceeded",
          '"error":"rate_limit_exceeded"' in resp.body.decode("utf-8", errors="replace"),
          f"body[:200]={resp.body[:200]!r}")


async def test_internal_request_returns_json_429_on_429() -> None:
    """`/internal/...` (which is not for anon SDKs but for ops tooling)
    still gets JSON 429 — it is NOT a page request."""
    mw = _make_middleware()
    req = _FakeRequest("/internal/data-freshness")
    resp = await _drive(mw, req, rpm_count=121, rpd_count=1)
    check("/internal/* 429 keeps JSON envelope (not a page)",
          resp.status_code == 429 and "rate_limit_exceeded" in resp.body.decode("utf-8", errors="replace"),
          f"status={resp.status_code}")


async def test_page_under_limit_passes_through() -> None:
    """Under the rpm limit, page requests still pass to the handler."""
    mw = _make_middleware()
    req = _FakeRequest("/")
    resp = await _drive(mw, req, rpm_count=10, rpd_count=10)
    check("under-limit page request returns the handler response (200)",
          resp.status_code == 200,
          f"status={resp.status_code}")


def test_is_page_request_helper() -> None:
    """The `_is_page_request` predicate is the branch condition — verify each
    side so a future refactor can't silently invert it."""
    for path in ("/", "/app.html", "/portfolio.html", "/agent.html",
                 "/static/x.js", "/assets/y.js", "/llms.txt"):
        check(f"is_page_request({path!r}) = True",
              rl._is_page_request(path) is True, "should be page")
    for path in ("/api/v1/cis/universe", "/api/v1/health", "/internal/foo",
                 "/ws/live", "/mcp/sse", "/mcp-sse"):
        check(f"is_page_request({path!r}) = False",
              rl._is_page_request(path) is False, "should NOT be page")


def test_rate_limit_middleware_imports_htmllibresponse() -> None:
    """S-244 family text guard: `_rate_limited_response` MUST exist and be
    called from the dispatch path, so a refactor that drops the HTML branch
    silently regresses to JSON 429-on-/ — which is the bug T-013 closed."""
    src = open(rl.__file__, encoding="utf-8").read()
    check("HTMLResponse imported in rate_limit.py",
          "HTMLResponse" in src,
          "HTMLResponse not imported — page 429 will be JSON")
    check("_rate_limited_response helper exists",
          "def _rate_limited_response" in src,
          "helper missing — page/JSON branch logic lost")
    check("dispatch calls _rate_limited_response (not raw JSONResponse on 429)",
          "_rate_limited_response(" in src and
          src.count("_rate_limited_response(") >= 3,    # helper def + 2 call sites
          "dispatch path did not call the helper")


if __name__ == "__main__":
    print("── T-013: page 429 returns HTML 200, API 429 keeps JSON ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        if asyncio.iscoroutinefunction(fn):
            asyncio.run(fn())
        else:
            fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ page 429 → HTML 200 · API 429 → JSON 429 · page under-limit passes through")