"""跨 Python 版本的地雷守卫 (S-280)。

## 为什么存在:preflight 在 Mac 把门,而我在沙箱验证它

    Cowork 沙箱   Python 3.10.12
    Jazz 的 Mac   Python 3.14.3     ← **preflight 真正运行的地方**

2026-09-02:`tests/test_deep_walk.py` 用 `asyncio.get_event_loop()`,
在 3.10 上通过、在 3.14 上 **RuntimeError**。我报了「PREFLIGHT PASSED」,
而那句话**没有声明它的适用环境** —— 同一天在修的形状,出现在我自己的验收上。

> **一个不声明运行环境的「通过」,和一个不声明窗口的分位数是同一种东西。**

## 两类地雷,两种处理

    硬错(3.14 直接抛)      零容忍 —— 出现即失败
    弃用(还能跑但会消失)    **只减不增预算** —— 不逼一次大改,但不许新增

只减不增是仓里已有的模式(S-264 `UNWIRED_BUDGET`、S-262 `PUBLIC_BY_DESIGN`):
**一个不能变大的数,比一句「以后要改」有用。**
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._source import code_only                            # noqa: E402
_FAIL: list = []

#: 3.14 上直接抛异常的调用。**零容忍。**
HARD_ERRORS = {
    r"asyncio\.get_event_loop\(\)":
        "3.14 起无运行中的 loop 时直接抛 RuntimeError。用 asyncio.run()",
    r"\basyncio\.coroutine\b": "3.11 已移除。用 async def",
    r"^\s*import imp\b": "3.12 已移除。用 importlib",
    r"^\s*import distutils\b": "3.12 已移除。用 setuptools/packaging",
}

#: 还能跑但已弃用 —— **只减不增**。今天的实测数字写死在这里。
UTCNOW_BUDGET = 28

SEARCH_DIRS = ("src", "tests", "scripts")

#: **本文件自己不算** —— 它的 `HARD_ERRORS` 键里就写着那些模式。
#: 与 S-264 排除 `source_policy.py`、S-262 排除 `*_probe.sh` 同一个先例:
#: 一个登记表会匹配到自己,于是守卫为自己的说明文字报警。
#: (今天第四次被自己的解释绊倒 —— S-249 docstring / S-265 注释 /
#:  S-271 枚举名 / 本条模式字符串。)
SELF = Path(__file__).name


def _files():
    for d in SEARCH_DIRS:
        for f in (ROOT / d).rglob("*.py"):
            if (".venv" not in f.parts and "site-packages" not in f.parts
                    and f.name != SELF):
                yield f


def _code(f: Path) -> str:
    """只看**代码**,不看注释与 docstring —— `tests/_source.py` 已有的工具。

    我曾手写过三个更差的版本(S-272 那次才发现它一直在)。
    这里的第二个来源正是 `test_deep_walk._run` 的 docstring 引用了那句调用。
    """
    try:
        return code_only(f.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return ""


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def t_the_running_python_is_reported():
    """**「通过」必须带上它在哪通过的。**"""
    v = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"      本次运行于 Python {v}")
    _check("Python ≥ 3.10", sys.version_info >= (3, 10), v)
    if sys.version_info < (3, 12):
        print("      ⚠️ 低于 3.12 —— **Mac 上的 preflight 跑的是 3.14**,"
              "本机通过不代表那边通过")


def t_no_hard_errors_on_314():
    """零容忍:这些在 3.14 上直接抛。"""
    for pat, why in HARD_ERRORS.items():
        hits = []
        rx = re.compile(pat, re.M)
        for f in _files():
            if rx.search(_code(f)):
                hits.append(str(f.relative_to(ROOT)))
        _check(f"无 {pat.replace(chr(92), '')}", not hits,
               f"{hits[:4]} —— {why}")


def t_deprecated_utcnow_is_shrink_only():
    """还能跑,但**不许新增**。一个不能变大的数比一句「以后要改」有用。"""
    rx = re.compile(r"datetime\.utcnow\(\)")
    n = 0
    for f in _files():
        n += len(rx.findall(_code(f)))
    _check(f"utcnow 用量 {n} ≤ 预算 {UTCNOW_BUDGET}(只减不增)",
           n <= UTCNOW_BUDGET,
           f"新增了 {n - UTCNOW_BUDGET} 处 —— 用 datetime.now(datetime.UTC)")
    if n < UTCNOW_BUDGET:
        print(f"      ↓ 已降到 {n},请把 UTCNOW_BUDGET 调到 {n} 锁住成果")


def t_deep_walk_actually_runs_here():
    """回归:那个具体失败必须在本机可复现地通过。"""
    r = subprocess.run([sys.executable, "-m", "tests.test_deep_walk"],
                       cwd=ROOT, capture_output=True, text=True, timeout=180)
    _check("tests.test_deep_walk 通过", r.returncode == 0,
           (r.stdout + r.stderr)[-300:])


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
