"""研究脚本里翻页读库必须带 order(T-170 / T-173 / A 道 10-22 复核)。

不带 order 时 PostgREST 的翻页边界会漂:同一查询三四次里有一次缺两成 (symbol, date) —— 行数照样对,
重复 serve 了别的页(t148 缺 21%、t155 缺 8.9%,价格本身零分歧)。行数不能当完整性证据。

静态检查两种写法(文件里出现 offset + limit 翻页的才查):
- URL 字符串 `"table?select=..."`:同一字面量或其后 3 行内要有 `order=`;
- 参数字典 `{"select": ...}`:同一个字典字面量里要有 "order" 键。
ALLOW = 已知违例、返工卡在路上(改好一个就从这里删一个);新文件一律不许进来。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW = {
    "docs/research/T-090_check.py", "docs/research/T-090_modify.py", "docs/research/T-093_run.py",  # 已归档的旧卡
    "docs/research/t155_funding_tilt.py", "docs/research/t142_narrative_ab.py",                     # 返工中(B 道)
    "docs/research/t144_narrative_ab.py",
}
URL_RE = re.compile(r"""["']([a-z_0-9]+)\?select=""")


def _pages(src: str) -> bool:
    return bool(re.search(r"offset", src) and re.search(r"limit", src))


def violations(path: Path) -> list[int]:
    src = path.read_text(encoding="utf-8", errors="replace")
    if not _pages(src):
        return []
    out = []
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if URL_RE.search(line):
            window = " ".join(lines[i:i + 4])
            if "order=" not in window and '"order"' not in window and "'order'" not in window:
                out.append(i + 1)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if "select" in keys and "order" not in keys:
                out.append(node.lineno)
    return sorted(set(out))


def test_new_research_scripts_page_with_order():
    bad = {}
    for p in sorted((ROOT / "docs" / "research").glob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel in ALLOW:
            continue
        v = violations(p)
        if v:
            bad[rel] = v[:5]
    assert not bad, f"翻页读库没带 order=(会间歇性漏两成键):{bad}"


def test_allow_list_only_holds_files_that_still_violate():
    stale = [rel for rel in sorted(ALLOW) if (ROOT / rel).exists() and not violations(ROOT / rel)]
    assert not stale, f"这些已经改好了,从 ALLOW 里删掉:{stale}"


def test_the_detector_catches_both_styles(tmp_path):
    p = tmp_path / "x.py"
    p.write_text('def f(o):\n    return get("ohlcv_daily?select=a,b", limit=1000, offset=o)\n'
                 'def g(o):\n    return _get("ohlcv_daily", {"select": "a", "limit": 1000, "offset": o})\n')
    assert violations(p) == [2, 4]
    p.write_text('def f(o):\n    return get("ohlcv_daily?select=a&order=a.asc", limit=1000, offset=o)\n'
                 'def g(o):\n    return _get("ohlcv_daily", {"select": "a", "order": "a.asc", "limit": 1000, "offset": o})\n')
    assert violations(p) == []
