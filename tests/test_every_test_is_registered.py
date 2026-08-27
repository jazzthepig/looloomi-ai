"""一个测试文件存在,不等于它会被运行 (S-244).

怎么发现的:S-243 的台账条目写着「回归测试:`tests/test_one_regime_one_spelling.py`
(13 passed)」。那个文件确实存在,13 条断言确实全绿 —— 而 **preflight 里没有任何一行
提到它**,所以从写完那天起它一次也没有跑过,以后也不会跑。

实测 2026-08-27,`tests/` 75 个文件里 **9 个从未被 preflight 引用**:

    test_one_regime_one_spelling      13 passed   ← 台账称它为回归测试
    test_regime_reaches_the_signal_feed 19 passed
    test_strategy_vector_smoke        14 passed
    test_cis                           8 passed
    test_outcome_canonical             8 passed
    test_two_layer_paper_smoke         7 passed
    test_spa_deep_links_resolve        5 passed
    test_pit_replay                   12 properties  ← 自跑式,S-207 的守卫
    test_factory                       9 FAILED      ← 烂了没人知道

**74 条绿断言在守护空气,9 条红断言在无声地烂着。**

### 这是同一个形状,不是新的

`docs/PLAN_2026-08-25_STRUCTURE_PRESERVING.md` 数出的 31 条,全部是「两个不同的状态
被压进同一个表示」。这条是第 32 条,而且压的是**验证装置自己**:

    守卫写了  vs  守卫被执行     →  一个"有测试"

S-233 说「没有调用者的代码不会被任何东西碰到」。preflight 是测试的调用者,
而它是**手写枚举**的 —— 一个新文件不会自动进去,而漏掉它没有任何征兆:
测试全绿,文件在仓库里,台账上写着它是回归测试。

### 和 S-124 的那条不重复

`test_cold_start_contract.py::test_every_test_file_actually_runs_the_tests_it_defines`
问的是「**这个文件跑不跑它自己定义的测试**」（收集器写在了最后一个 def 之前）。
这条问的是「**有没有东西跑这个文件**」。两个不同的断链点,合起来才是一条完整的链:

    文件定义了测试 → 文件会跑它们 (S-124) → 有东西会跑这个文件 (S-244)

### 三个状态,不是两个

    registered   preflight 点名运行
    exempt       明确豁免 + 写下原因(名单只能减)
    orphan       既没注册也没豁免 → 失败

### 还有第四件事:调用方式必须和文件形式匹配

**这是最容易踩的一脚,我自己差点踩。** `tests/` 里两种文件混着:

    pytest 式      有 `def test_*`      必须 `python3 -m pytest tests/x.py`
    stdlib 自跑式  模块体 + `sys.exit`  必须 `python3 -m tests.x`

把 pytest 式的文件写成 `python3 -m tests.x`,模块导入成功、零断言执行、**退出码 0**。
它会永远"通过"。所以注册了还不够 —— 注册的**方式**也要对。

### 为什么这条可以上棘轮 (S-238)

棘轮只对**机器无关**的属性成立。这里守的是「preflight.sh 的文本里有没有提到这个
文件名」—— 纯代码属性,和这台机器有没有数据、有没有凭证无关。
(测试本身的通过与否是机器相关的,所以 `test_factory` 进豁免名单并写下原因,
而不是让它在沙箱里常红 —— 常红的关卡等于没有关卡。)

### 范围:`tests/` 是 CI 面,`src/research/validation/tests/` 不是

实测 55 个 validation smoke 文件里 preflight 只引用 4 个。那**不是缺陷** ——
它们是每个实验各自的一次性冒烟,归 Minimax-C 的实验流程,不归 CI。
把 51 个实验冒烟塞进 preflight 会让 push 前等好几分钟,而人会开始跳过 preflight。
**这个区分本身就是一次状态分离:CI 面 vs 研究草稿面。** 所以这条守卫只扫 `tests/`,
并在输出里把 validation 面的数字**报出来但不失败**。
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
PREFLIGHT = ROOT / "scripts" / "preflight.sh"
VALIDATION_TESTS = ROOT / "src" / "research" / "validation" / "tests"

#: 明确豁免 —— 附原因,名单**只能减**。
#:
#: 豁免不是赦免:每一行都要说清"为什么这个文件不该进 CI",而当它被注册之后
#: 这一行必须删掉,否则名单会变成永久特赦(和 test_no_investor_facing_internals
#: 里 `KNOWN_CODE_ONLY` 同一个设计)。
EXEMPT = {
    "test_factory":
        "9 个断言在沙箱里返回 503/403 —— 缺凭证与 role gate,是环境相关而非代码缺陷。"
        "进 CI 会让 preflight 在没有凭证的机器上常红,而常红的关卡等于没有关卡。"
        "归属:需要先给它一个不依赖真实凭证的 fixture,再注册 (S-244 未了项)。",
}

#: 非测试文件 —— 不参与统计。
NOT_A_TEST = {"__init__", "conftest", "_source"}


def _registered() -> set[str]:
    """preflight.sh 文本里点名的测试模块。

    两种调用形式都要认:`python3 -m pytest tests/x.py` 和 `python3 -m tests.x`。
    只匹配一种,另一种形式注册的文件会被误判成孤儿。
    """
    if not PREFLIGHT.exists():
        return set()
    txt = PREFLIGHT.read_text()
    return {m.group(1) for m in re.finditer(r"\btests[./](test_[a-z0-9_]+)", txt)}


def _invoked_as_pytest(name: str) -> bool:
    """preflight 是用 pytest 跑它的吗?"""
    txt = PREFLIGHT.read_text() if PREFLIGHT.exists() else ""
    return bool(re.search(rf"pytest\s+tests/{re.escape(name)}\.py", txt))


def _invoked_as_module(name: str) -> bool:
    txt = PREFLIGHT.read_text() if PREFLIGHT.exists() else ""
    return bool(re.search(rf"python3?\s+-m\s+tests\.{re.escape(name)}\b", txt))


def _is_main_guard(node: ast.stmt) -> bool:
    """这个顶层节点是不是 `if __name__ == "__main__":`。"""
    if not isinstance(node, ast.If):
        return False
    t = node.test
    return (isinstance(t, ast.Compare)
            and isinstance(t.left, ast.Name) and t.left.id == "__name__"
            and any(isinstance(c, ast.Constant) and c.value == "__main__"
                    for c in t.comparators))


def _does_work(nodes) -> bool:
    """这些节点里有没有【除了打印以外的调用】。

    ⚠️ 第二版这里也判错了,同一个错法的第二遍:我要求 `__main__` 块里必须有
    `sys.exit`。实测 2026-08-27,`test_strategy_discipline.py` 的块是

        for t in TESTS:
            t(); print(f"  ✓ {t.__name__}")

    **没有 sys.exit,而它照样正确失败** —— 裸调用抛出的 AssertionError 一路
    传到解释器,退出码就是 1。我把"用退出码说话"这个属性,错认成了"字面写了
    sys.exit"这个拼写。判据必须是「这个块会不会去执行测试」,
    而不是「它有没有我预期的那一行」。
    """
    for n in nodes:
        for sub in ast.walk(n):
            if not isinstance(sub, ast.Call):
                continue
            f = sub.func
            if isinstance(f, ast.Name) and f.id == "print":
                continue
            return True
    return False


def _file_style(path: pathlib.Path) -> str:
    """文件形式:dual / pytest / selfrunner / neither —— 按 AST 判,不按文件名。

    ⚠️ 第一版把这件事判错了,而错法正是今天被 mutation 打回六次的那一种:
    **匹配了模式,不是构造。** 我看到顶层有 `def test_*` 就判成"pytest 式",
    于是 50 个文件被报成「以 -m 调用会零断言通过」。实测不成立 —— 它们大多是
    **双模式**的:

        def test_x(): ...                       ← pytest 收得到
        if __name__ == "__main__":
            for fn in [v for k, v in globals().items() if k.startswith("test_")]:
                fn()
            sys.exit(1 if _FAILURES else 0)     ← -m 也跑得动

    两种调用都会执行断言,所以两种都对。真正危险的只有**有 test 函数、却没有
    `__main__` 运行块**的文件被以 `-m` 调用 —— 那才是导入成功、零断言、退出码 0。

    判据是那个 `if __name__` 节点**会不会去执行测试**(有非 print 的调用),
    不是"有没有 def test_",也不是"有没有写 sys.exit" —— 这两个我都错过一遍,
    所以下面 `_negative_control()` 用合成样本把三种形式钉住。
    """
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return "unparseable"

    has_test_fn = any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
        for n in tree.body
    ) or any(
        isinstance(n, ast.ClassDef) and n.name.startswith("Test")
        for n in tree.body
    )

    # `__main__` 块里用退出码说话 = 它能被 `-m` 正确调用。
    main_runner = any(_is_main_guard(n) and _does_work(n.body) for n in tree.body)

    # 模块体(不含 `__main__` 块)里就 sys.exit = 纯自跑式,pytest 收集为 0。
    body_exit = _does_work([n for n in tree.body if not _is_main_guard(n)])

    if has_test_fn and main_runner:
        return "dual"          # 两种调用都执行断言
    if has_test_fn:
        return "pytest"        # 只能 pytest
    if main_runner or body_exit:
        return "selfrunner"    # 只能 -m
    return "neither"


#: 合成样本 —— 分类器的负控制。
#:
#: 这个分类器我连错两次(先是"有 def test_ 就算 pytest 式",再是"__main__ 里
#: 必须有 sys.exit"),两次都在真实文件上跑出了几十条假阳性。一个会误报的守卫,
#: 比没有守卫更糟:人会学会忽略它,然后连真阳性一起忽略。
#:
#: 所以分类不靠我读代码时的印象,靠这四个钉死的样本。改 `_file_style` 时它们先响。
_CONTROL = {
    "dual": "def test_a():\n    assert 1\nif __name__ == '__main__':\n"
            "    for t in [test_a]:\n        t()\n",
    # 真实形态:裸调用,没有 sys.exit —— 靠 AssertionError 传播给出退出码。
    "dual_no_exit": "def test_a():\n    assert 1\nif __name__ == '__main__':\n"
                    "    test_a()\n    print('ok')\n",
    # 危险形态:有测试函数,`__main__` 只打印,不执行 —— 以 -m 调用等于零断言。
    "pytest": "def test_a():\n    assert 1\nif __name__ == '__main__':\n"
              "    print('run me with pytest')\n",
    # 纯自跑式:模块体断言,pytest 收集为 0。
    "selfrunner": "import sys\n_f = []\nif _f:\n    sys.exit(1)\n",
}


def _negative_control(tmp: pathlib.Path) -> list[str]:
    """分类器必须在合成样本上给出预期分类,否则它自己是坏的。"""
    expect = {"dual": "dual", "dual_no_exit": "dual",
              "pytest": "pytest", "selfrunner": "selfrunner"}
    bad = []
    for key, src in _CONTROL.items():
        f = tmp / f"_ctl_{key}.py"
        f.write_text(src)
        got = _file_style(f)
        if got != expect[key]:
            bad.append(f"分类器负控制失败:合成样本 '{key}' 应判为 "
                       f"{expect[key]},实判 {got} —— 先修 _file_style,再信它的报告")
        f.unlink()
    return bad


def main() -> int:
    if not TESTS.exists():
        print("  ⓘ tests/ 不存在,跳过")
        return 0

    reg = _registered()
    problems: list[str] = []
    n_reg = n_exempt = 0

    # 负控制先跑 —— 分类器坏了就不要报它的结论。
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ctl = _negative_control(pathlib.Path(td))
    if ctl:
        print("✗ " + "\n✗ ".join(ctl))
        return 1

    for p in sorted(TESTS.glob("*.py")):
        name = p.stem
        if name in NOT_A_TEST:
            continue

        if name in reg:
            n_reg += 1
            style = _file_style(p)
            # ── 调用方式必须匹配文件形式 ────────────────────────────────
            # `dual` 两种都对,不检查。真正的陷阱只有下面两种:有 test 函数
            # 但没有 `__main__` 运行块的文件被 `-m` 调用 = 导入成功、零断言、
            # 退出码 0,它会永远"通过";以及纯自跑式文件被 pytest 调用 =
            # 收集到 0 个测试,同样报成功。
            if style == "dual":
                pass
            elif style == "pytest" and _invoked_as_module(name) and not _invoked_as_pytest(name):
                problems.append(
                    f"{name}: pytest 式文件(顶层有 def test_*)却以 `python3 -m tests.{name}` 调用 —— "
                    f"导入成功、零断言执行、退出码 0。改成 `python3 -m pytest tests/{name}.py -q`")
            elif style == "selfrunner" and _invoked_as_pytest(name) and not _invoked_as_module(name):
                problems.append(
                    f"{name}: 自跑式文件(模块体断言 + sys.exit)却以 pytest 调用 —— "
                    f"pytest 收集到 0 个测试并报成功。改成 `python3 -m tests.{name}`")
            elif style == "neither":
                problems.append(
                    f"{name}: 既没有顶层 `def test_*` 也没有 sys.exit —— "
                    f"无论怎么调用都不会有断言失败传出来")
            elif style == "unparseable":
                problems.append(f"{name}: 语法错误,parse 不了")
            continue

        if name in EXEMPT:
            n_exempt += 1
            continue

        problems.append(
            f"{name}: 存在但 preflight 从不运行 —— "
            f"注册它(`{'python3 -m pytest tests/%s.py -q' % name if _file_style(p) == 'pytest' else 'python3 -m tests.%s' % name}`)"
            f",或写进 EXEMPT 并说明原因")

    # 名单只能减:已经注册的文件还留在豁免名单里 → 失败。
    for name in sorted(set(EXEMPT) & reg):
        problems.append(f"{name}: 已经注册了,却还在 EXEMPT 里 —— 删掉那一行")
    # 豁免一个不存在的文件也是过期条目。
    present = {p.stem for p in TESTS.glob("*.py")}
    for name in sorted(set(EXEMPT) - present):
        problems.append(f"{name}: EXEMPT 里列着,但文件不存在 —— 删掉那一行")

    if problems:
        print(f"✗ 测试注册缺口:{len(problems)} 处")
        for s in problems:
            print(f"   · {s}")
        print("  一个测试文件存在,不等于它会被运行。preflight 是手写枚举的,"
              "漏掉一个没有任何征兆 (S-244)。")
        return 1

    n_vt = len(list(VALIDATION_TESTS.glob("test_*.py"))) if VALIDATION_TESTS.exists() else 0
    print(f"  ✓ tests/ 全部注册:{n_reg} 个在 preflight 里 · {n_exempt} 个已豁免并写明原因")
    if n_vt:
        # 报出来但不失败 —— 这是研究草稿面,不是 CI 面。数字在这里是为了让
        # "它有 51 个没跑的冒烟"成为一件被看见的事,而不是一个被沉默的事实。
        print(f"    (src/research/validation/tests/ 另有 {n_vt} 个实验冒烟,"
              f"归研究流程不归 CI —— 见本文件 docstring「范围」)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
