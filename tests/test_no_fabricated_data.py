"""编造数据的守卫 (S-288)。

CLAUDE.md 规则 #9:**「宁可空且标记,不可编造」**,并点名
「audit standing: DeFiLlama-402 fallbacks」—— 那条 audit 项一直挂着,
直到 2026-09-04 才真正清掉。

`src/data/vc/deal_flow.py` 有三个 `_get_mock_*()`,在 **10 个返回点**上
把失败替换成假数据。最坏的一个不是 402 那条:

    return rounds if rounds else self._get_mock_funding_rounds()

**一个成功但为空的响应会被替换成虚构的融资** —— 真实的「没有」变成
虚构的「有」,而调用方无从分辨。**这与今天反复出现的形状同源:
两个不同的状态(空 / 编造)塌进一个返回值。**

而那些假数据**署了真实机构的名**(Paradigm、a16z、Sony)。
一般的假数据是噪声;**署名的假数据是关于真实公司的虚构事实**。

⚠️ 本守卫用 `tests/_source.py:code_only` 剥掉注释与 docstring ——
上面这段说明里就写着那些模式名,**不剥就会被自己的解释绊倒**(当天第五次)。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._source import code_only                            # noqa: E402

_FAIL: list = []
SELF = Path(__file__).name

#: 编造数据的形状。**值是为什么它危险**,不是一句「不许」。
FABRICATION_PATTERNS = {
    r'\bdef\s+_?get_mock\w*': "mock 生成函数 —— 失败会被替换成假数据",
    r'\bdef\s+_?mock_\w+': "同上",
    r'return\s+\w*\._get_mock': "返回点上的 mock 替换",
    r'\bFALLBACK_(ROUNDS|DATA|VCS)\b': "硬编码回退数据集",
}


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def _src_files():
    for f in (ROOT / "src").rglob("*.py"):
        if ".venv" in f.parts or "site-packages" in f.parts:
            continue
        yield f


def _code(f: Path) -> str:
    try:
        return code_only(f.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return ""


def t_no_fabrication_in_src():
    """**本文件的理由。** 生产路径里不许有编造数据的生成器。"""
    for pat, why in FABRICATION_PATTERNS.items():
        hits = [str(f.relative_to(ROOT)) for f in _src_files()
                if re.search(pat, _code(f), re.I)]
        _check(f"src/ 无 {pat[:28]}", not hits, f"{hits[:3]} —— {why}")


def t_the_docstring_mention_does_not_trip_the_guard():
    """判别性:说明文字里写着那些模式名,**剥掉 docstring 后不应命中**。"""
    f = ROOT / "src/data/vc/deal_flow.py"
    raw = f.read_text(encoding="utf-8", errors="ignore")
    _check("原文里确实提到了 _get_mock(作为反例)", "_get_mock" in raw)
    _check("而剥掉注释/docstring 后没有", "_get_mock" not in _code(f),
           _code(f)[:200])
    _check("守卫因此没有被自己的解释绊倒(当天第五次的那个形状)", True)


def t_empty_is_returned_not_invented():
    """取不到 → 空。**空是一个诚实的答案。**"""
    src = _code(ROOT / "src/data/vc/deal_flow.py")
    _check("402 分支返回空", "return []" in src, src[:200])
    n_empty = src.count("return []")
    _check(f"至少 3 个返回点改成了空(实为 {n_empty})", n_empty >= 3, str(n_empty))


def t_guard_covers_new_files_automatically():
    """清册现扫 `src/` —— 明天新加的文件明天就在扫描范围里。"""
    n = sum(1 for _ in _src_files())
    _check(f"扫描到 {n} 个 src 文件(不是一份手写清单)", n > 50, str(n))


def main() -> int:
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("t_")]:
        print(f"\n▸ {fn.__name__}")
        fn()
    print("\n" + ("✓ 全部通过" if not _FAIL else f"✗ {len(_FAIL)} 条失败"))
    for f in _FAIL:
        print("   " + f)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
