"""T-021 — 死链重定向必须在 Cloudflare Pages 的 `_redirects` 里,而不只是在 FastAPI 里。

2026-09-27 实测:FastAPI `serve_spa` 的 301 在 Railway 源站生效,但 looloomi.ai 的页面由 Cloudflare Pages 提供
(`/app.html` → 308 → `/app`),对缺失文件回落到 SPA 壳 —— 六个旧链接仍是 200。两处必须同步。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _pages_rules() -> dict[str, tuple[str, str]]:
    rules = {}
    for line in (ROOT / "dashboard/public/_redirects").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        assert len(parts) == 3, f"_redirects 行格式应为 '<from> <to> <code>':{line!r}"
        rules[parts[0]] = (parts[1], parts[2])
    return rules


def _fastapi_dead_links() -> set[str]:
    src = (ROOT / "src/api/main.py").read_text()
    block = re.search(r"_DEAD_HTML_REDIRECTS\s*=\s*\{(.*?)\}", src, re.S).group(1)
    return set(re.findall(r'"([\w\-]+\.html)"\s*:', block))


def test_every_fastapi_dead_link_is_also_redirected_on_pages():
    pages = _pages_rules()
    for name in _fastapi_dead_links():
        assert f"/{name}" in pages, f"/{name} 在 FastAPI 里重定向,但 Pages _redirects 里没有 —— looloomi.ai 上仍是 200"
        assert pages[f"/{name}"] == ("/app", "301"), pages[f"/{name}"]


def test_no_proxy_rules_and_no_pretty_url_redirects():
    for src_path, (to, code) in _pages_rules().items():
        assert code in ("301", "302", "308"), f"{src_path}: 只放重定向,代理规则在 Pages Functions 里"
        assert src_path.endswith(".html"), f"{src_path}: 只重定向 .html 形式,/cis 之类是 SPA 深链(S-160)"


if __name__ == "__main__":
    test_every_fastapi_dead_link_is_also_redirected_on_pages()
    test_no_proxy_rules_and_no_pretty_url_redirects()
    print("✅ Pages _redirects 与 FastAPI 死链表一致")


def test_every_advertised_backend_path_has_a_pages_proxy():
    """11-07:llms.txt / agent.json 对外写着 https://looloomi.ai/mcp 与 /mcp-sse/sse,但 Pages 只给 /api/* 与 /internal/* 配了
    Functions 代理 —— /mcp 的 GET 回 SPA 壳、POST 回 405,外部 agent 从来连不上(agent_call_log 自上线 0 行)。
    同一个形状:页面是 Pages 的,后端路径必须有 functions/<段>/ 代理,否则广告出去的就是死链。"""
    pub = ROOT / "dashboard/public"
    text = (pub / "llms.txt").read_text(encoding="utf-8") + (pub / ".well-known/agent.json").read_text(encoding="utf-8")
    firsts = set()
    for path in re.findall(r"https://looloomi\.ai(/[A-Za-z0-9_\-./]*)", text):
        seg = path.strip("/").split("/")[0]
        if seg and not seg.startswith(".") and "." not in seg:
            firsts.add(seg)
    backend = {s for s in firsts if s in ("api", "internal", "mcp", "mcp-sse")}
    assert {"mcp", "mcp-sse", "api"} <= backend, backend
    missing = [s for s in sorted(backend) if not (ROOT / "functions" / s / "[[path]].js").exists()]
    assert not missing, f"对外写着却没有 Pages 代理的后端路径:{missing}"
    src = (ROOT / "functions/mcp/[[path]].js").read_text(encoding="utf-8")
    assert "'/mcp' ? '/mcp/'" in src, "源站把 MCP 挂在 /mcp/(带斜杠);不带斜杠的 POST 在源站也是 405"
