"""`src/research/` 里的模块必须真的能 import (S-236).

怎么发现的:改 `report.py` 的一行渲染,顺手 import 它 ——

    ModuleNotFoundError: No module named 'statsmodels'
      report.py:39 → multiple_testing.py:32 → statsmodels.stats.multitest

而 `statsmodels>=0.14.0` **就在 requirements.txt:29**。所以生产有它,沙箱没有,
声明是对的。Minimax-A 的审计把这条记成「装 statsmodels,解锁 pytest 收集」——
**真正的问题不是那个包,是没有任何关卡会 import 这些模块。**

preflight 对 `src/` 做的是 `py_compile`(只查语法)加一次 app boot smoke。
`src/research/report.py`、`multiple_testing.py`、`walk_forward.py` 不在 app 的
import 图上,于是:

    语法没问题 → py_compile 绿
    没人 import → boot smoke 碰不到
    结果:一个 import 就炸的模块,可以在仓库里躺任意久

而 `src/research/` 正是**每一条策略主张被算出来的地方**。S-233 是"没有调用者的
代码不会被任何东西碰到";这条是它的环境版本 —— **没有 import 者的模块,连
能不能 import 都没人知道。**

### 三值,不是两值

这个关卡必须分开三件事,否则它在沙箱里会因为一个【已声明】的依赖而常红,
而常红的关卡等于没有关卡(MEMORY.md:永远在响的 warning 不携带信息):

    ok        import 成功
    missing   依赖没装,但它在 requirements.txt 里 —— 环境问题,不是代码问题
    broken    真错(NameError / SyntaxError / 循环 import / 依赖没声明)

**只有 broken 让构建失败。** `missing` 打印出来并给出装它的命令。
"""
from __future__ import annotations

import importlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: 只扫这些子树 —— 策略主张被计算的地方。
SCAN = ("src/research",)

#: 目录名里带这些的跳过:测试自跑、虚拟环境、缓存。
SKIP_PARTS = {"__pycache__", ".venv", "tests", "node_modules"}

#: 已知的【模块顶层做 I/O】。
#:
#: 这是第三类,和 missing / broken 都不同:模块本身没错,但它在 import 时就去读
#: 文件、断言数据目录。**import 一个模块不该有副作用** —— 那让它无法被检查、
#: 无法在没有那份数据的机器上使用,也让"能不能 import"和"数据在不在"变成一件事。
#: 修法是把 I/O 挪进函数,归各自作者;这里先让它可见且不再增加。
#:
#: ⚠️ 这个名单【没有】"只能减"的棘轮,而这是我第一版的错 (S-238)。
#: 我照搬了 `_S195_KNOWN` 的棘轮 —— 那条守的是"某文件是否调用某端点",
#: 一个**机器无关**的代码属性,所以"修好了还留在名单上"必然是过期条目。
#:
#: 这里守的是"import 时的 I/O 会不会失败",而那**取决于这台机器有没有那份数据**。
#: 实测 2026-08-25:`r81_taker_buy_residual` 在沙箱抛异常,在 Mac 上干净通过
#: (数据卷挂着)。于是棘轮在 Mac 上把一个正常的模块判成"过期豁免"并挂了构建。
#:
#: **棘轮只对机器无关的属性成立。** 对环境相关的属性,它把"环境不同"误报成"状态变了"。
_MODULE_LEVEL_IO = {
    "src.research.beta_core.beta_core_backtest":
        "顶层读 'panel.json'(相对路径,依赖 cwd)",
    "src.research.validation.r81_taker_buy_residual":
        "顶层 assert 数据目录里有 >=20 个 A-S1 symbol",
}


def _declared_requirements() -> set[str]:
    """requirements.txt 里声明过的顶层包名(小写)。"""
    req = ROOT / "requirements.txt"
    if not req.exists():
        return set()
    out: set[str] = set()
    for line in req.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)", line)
        if m:
            out.add(m.group(1).lower().replace("-", "_"))
    return out


def _modules():
    for rel in SCAN:
        base = ROOT / rel
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if set(p.parts) & SKIP_PARTS or p.name.startswith("_"):
                continue
            yield ".".join(p.relative_to(ROOT).with_suffix("").parts)


def main() -> int:
    declared = _declared_requirements()
    ok: list[str] = []
    missing: dict[str, str] = {}
    broken: list[tuple[str, str]] = []
    io_at_import: dict[str, str] = {}

    for mod in _modules():
        try:
            importlib.import_module(mod)
            ok.append(mod)
        except ModuleNotFoundError as e:
            dep = (e.name or "").split(".")[0].lower().replace("-", "_")
            if dep in declared:
                # 已声明但此环境没装 —— 生产装得上,这里不算代码缺陷。
                missing[mod] = dep
            else:
                broken.append((mod, f"未声明的依赖 '{e.name}' —— 加进 requirements.txt"))
        except Exception as e:                                    # noqa: BLE001
            if mod in _MODULE_LEVEL_IO:
                io_at_import[mod] = _MODULE_LEVEL_IO[mod]
            else:
                broken.append((mod, f"{type(e).__name__}: {str(e)[:120]}"))

    if missing:
        deps = sorted(set(missing.values()))
        print(f"  ⓘ {len(missing)} 个模块因【已声明但本环境未装】的依赖跳过: {deps}")
        print(f"    装它们:pip3 install {' '.join(deps)} --break-system-packages")

    if io_at_import:
        print(f"  ⚠ {len(io_at_import)} 个模块在 import 时就做 I/O(本机复现):")
        for mod, why in sorted(io_at_import.items()):
            print(f"      {mod}: {why}")
    # 名单里的模块在这台机器上干净 import —— 说明这里有那份数据,不是缺陷。
    # 报出来供人判断,但【不失败】:见 _MODULE_LEVEL_IO 上的 S-238 说明。
    clean_here = sorted(set(_MODULE_LEVEL_IO) & set(ok))
    if clean_here:
        print(f"  ⓘ {len(clean_here)} 个顶层 I/O 模块在本机干净 import(本机有那份数据):")
        for mod in clean_here:
            print(f"      {mod}")

    if broken:
        print(f"✗ {len(broken)} 个 src/research 模块 import 就失败:")
        for mod, why in broken[:12]:
            print(f"   · {mod}: {why}")
        print("  这些模块 py_compile 会过(语法没问题),而 app boot smoke 碰不到它们 ——")
        print("  没有 import 者的模块,连能不能 import 都没人知道 (S-236)。")
        return 1

    print(f"  ✓ src/research imports: {len(ok)} ok · {len(missing)} skipped (declared dep absent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
