"""S-557:挂在 API 进程里的 MCP 工具不再绕出公网读 REST、不再共用一个匿名 IP 额度。

10-13 实测:所有 MCP 工具返回「Rate limit exceeded」,loop-watch 看到熔断器打开。原因:工具经 https://looloomi.ai 读本服务,
请求从 Railway 的出口 IP 进门 —— 所有 agent 的调用共用 ip:<出口> 这一个匿名桶(120 次 / 分、2,000 次 / 天)。
"""
import pathlib

from starlette.requests import Request

from src.api.middleware.rate_limit import _is_loopback

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _req(host: str, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "method": "GET", "path": "/api/v1/cis/universe", "headers": headers,
                    "client": (host, 50000), "query_string": b""})


def test_only_true_loopback_without_forwarding_is_exempt():
    assert _is_loopback(_req("127.0.0.1"))
    assert _is_loopback(_req("::1"))
    assert not _is_loopback(_req("127.0.0.1", xff="203.0.113.7"))      # 经代理进来的,一律按来源 IP 计
    assert not _is_loopback(_req("10.0.0.5"))                          # Railway 内网 / 边缘代理
    assert not _is_loopback(_req("100.64.0.2"))


def test_mounted_mcp_reads_the_api_over_loopback():
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    i_set = main.index('os.environ.setdefault("MCP_INPROCESS_BASE"')
    i_imp = main.index("from src.mcp.cometcloud_mcp import mcp as _cometcloud_mcp")
    assert i_set < i_imp, "MCP_INPROCESS_BASE must be set before the MCP module reads it at import"
    mcp_src = (ROOT / "src/mcp/cometcloud_mcp.py").read_text(encoding="utf-8")
    assert 'RAILWAY_BASE = os.getenv("MCP_INPROCESS_BASE") or' in mcp_src
