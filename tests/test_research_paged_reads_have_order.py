"""研究脚本里翻页读库必须带 order(T-170 / T-173 / A 道 10-22 复核)。

不带 order 时 PostgREST 的翻页边界会漂:同一查询三四次里有一次缺两成 (symbol, date) —— 行数照样对,
重复 serve 了别的页(t148 缺 21%、t155 缺 8.9%,价格本身零分歧)。行数不能当完整性证据。

静态检查两种写法(文件里出现 offset + limit 翻页的才查):
- URL 字符串 `"table?select=..."`:同一字面量或其后 3 行内要有 `order=`;
- 参数字典 `{"select": ...}`:同一个字典字面量里要有 "order" 键,或同一个调用以关键字传 `order=` / 以位置参数传一个排序串(`"d.asc"`)(11-07 起);函数名含 count 的(只数行数)不查。
ALLOW = 已知违例、返工卡在路上(改好一个就从这里删一个);新文件一律不许进来。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW = {
    "docs/research/T-090_check.py", "docs/research/T-090_modify.py", "docs/research/T-093_run.py",  # 已归档的旧卡
}
URL_RE = re.compile(r"""["']([a-z_0-9]+)\?select=""")
# 11-09:URL 字符串后面以位置参数传排序串(`_paged("t?select=…", "d.asc")`)也算带了 order —— t313 的合并因此被误拦
POS_ORDER_RE = re.compile(r""",\s*["'][a-z_][a-z0-9_]*\.(?:asc|desc)(?:\.nulls(?:first|last))?["']""")


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
            if ("order=" not in window and '"order"' not in window and "'order'" not in window
                    and not POS_ORDER_RE.search(window)):
                out.append(i + 1)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    # 11-07:同一个调用里以关键字传 order=…(`get_all(tbl, {"select": …}, order="d.asc")`)也算带了 order ——
    # t286 / t287 两次合并都因为这个写法被误拦(请求串里有 order=,检查只认字典键)。
    # 同一个调用里另一个位置参数就是排序串(`fetch_paged(tbl, {"select": …}, "d.asc")`)也算;
    # 只数行数的调用(函数名含 count,HEAD + limit=1)不是翻页读,不查。
    _ORDER_STR = re.compile(r"^[a-z_][a-z0-9_]*\.(?:asc|desc)(?:\.nulls(?:first|last))?(?:,[a-z_][a-z0-9_]*\.(?:asc|desc)(?:\.nulls(?:first|last))?)*$")
    ordered_args: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        has_kw = any(kw.arg == "order" and not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
                     for kw in node.keywords)
        has_pos = any(isinstance(a, ast.Constant) and isinstance(a.value, str) and _ORDER_STR.match(a.value) for a in node.args)
        if has_kw or has_pos or "count" in str(fname).lower():
            for a in node.args:
                if isinstance(a, ast.Dict):
                    ordered_args.add(id(a))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and id(node) not in ordered_args:
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


def test_order_passed_as_a_keyword_on_the_same_call_counts(tmp_path):
    f = tmp_path / "x.py"
    f.write_text('def g():\n    offset = 0; limit = 1000\n'
                 '    a = get_all("t", {"select": "a,b"}, order="a.asc")\n'
                 '    b = get_all("t", {"select": "a,b"})\n'
                 '    c = get_all("t", {"select": "a,b"}, order=None)\n', encoding="utf-8")
    assert violations(f) == [4, 5], violations(f)


def test_positional_order_string_and_count_calls(tmp_path):
    f = tmp_path / "y.py"
    f.write_text('def g():\n    offset = 0; limit = 1000\n'
                 '    a = fetch_paged("t", {"select": "*"}, "d.asc,id.asc")\n'
                 '    n = count("t", {"select": "*"})\n'
                 '    b = fetch_paged("t", {"select": "*"}, "hello")\n', encoding="utf-8")
    assert violations(f) == [5], violations(f)
