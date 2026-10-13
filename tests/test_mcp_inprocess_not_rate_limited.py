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


def test_local_mcp_sends_an_api_key_when_one_is_configured(monkeypatch):
    """本地 stdio MCP(lane / Cowork / loop-watch 同一台 Mac 的 IP)设了 COMETCLOUD_API_KEY 就按 key 的档位计,不吃匿名额度。"""
    import ast, json, os
    src = (ROOT / "src/mcp/cometcloud_mcp.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_headers")
    ns = {"os": os}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "cometcloud_mcp", "exec"), ns)   # 不导入整个 MCP(干净机器上没有 mcp 包)
    monkeypatch.setenv("COMETCLOUD_API_KEY", "cc_test_dummy")
    assert ns["_headers"]() == {"X-API-Key": "cc_test_dummy"}
    monkeypatch.delenv("COMETCLOUD_API_KEY")
    assert ns["_headers"]() == {}
    assert src.count("httpx.AsyncClient(") - src.count("headers=_headers()") == 1, \
        "every REST client sends the key (the one exception is the Supabase call-log writer)"
    cfg = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["cometcloud"]["env"]["COMETCLOUD_API_KEY"] == "${COMETCLOUD_API_KEY:-}", \
        "the key is never written into this public file — only an env reference"
