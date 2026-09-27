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
