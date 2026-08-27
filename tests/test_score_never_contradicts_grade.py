"""显示的分数不得落进比它的评级更高的带 (S-252).

实测 2026-08-27,`looloomi.ai/app` 排行榜首屏:

    1  Aave     75.7   A
    2  Uniswap  75.0   B+     ← 看起来像 bug,因为它就是

`UNI` 的 `raw_cis_score = 74.97`。`get_grade(74.97)` 给 B+ —— **正确**。
而显示值是 `round(74.97, 1) = 75.0`,**四舍五入跨过了 grade 自己遵守的 75 这条线**。
同一行里,数字在 A 档,徽章在 B+ 档。

这是"同一个量的两个表示在决策边界上分岔"的又一处,而这次它在产品首屏 ——
任何一个 LP 打开就能看见,并且会合理地推断:如果这么明显的东西他们都没发现,
那些看不见的地方呢。

## 为什么用穷举而不是几个例子

写第一版修复时我查错了边界(取了当前带的下界而不是上一带的下界),
几个手挑的例子里 `75.21`、`75.72` 都过,看起来是对的。
**穷举 0.00–100.00 每 0.01 一个点,立刻显示 34 处矛盾,74.97 就在里面 ——
也就是它一个都没修。** 边界 bug 只在边界上出现,而手挑的例子几乎不落在边界上。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.cis.cis_provider import (                           # noqa: E402
    GRADE_FLOORS, display_score, get_grade)

_FAILURES: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {label}")
    else:
        _FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ✗ {label}\n      {detail}")


def test_exhaustive_no_score_contradicts_its_grade():
    """**穷举**:0.00–100.00 每 0.01,显示值的评级必须等于原值的评级。

    不是抽样,是全覆盖。边界 bug 只在边界上出现;10001 个点里只有 34 个会触发,
    随便挑十个例子有 96.6% 的概率一个都碰不到。
    """
    bad = [(x / 100, display_score(x / 100), get_grade(x / 100))
           for x in range(0, 10_001)
           if get_grade(display_score(x / 100)) != get_grade(x / 100)]
    _check(f"穷举 10001 个点:0 处矛盾", not bad,
           f"{len(bad)} 处,前三:{bad[:3]}")


def test_the_exact_live_case():
    """实测那两行,逐字钉住。"""
    _check("UNI raw=74.97 → 显示 74.9(不是 75.0)", display_score(74.97) == 74.9,
           str(display_score(74.97)))
    _check("UNI 评级仍是 B+(没有为了好看抬评级)", get_grade(74.97) == "B+")
    _check("AAVE raw=75.72 → 显示 75.7,评级 A(不受影响)",
           display_score(75.72) == 75.7 and get_grade(75.72) == "A")
    _check("并排时数字顺序仍然正确(74.9 < 75.7)",
           display_score(74.97) < display_score(75.72))


def test_the_fix_does_not_inflate_grades():
    """**方向必须是把数字让下去,不是把评级抬上来。**

    另一种"修法"是让 grade 按显示值算 —— 那样 74.97 会显示 75.0 且评为 A。
    数字与徽章一致了,而**呈现层决定了评级**:四舍五入变成了升级机制。
    这条钉住方向:显示值永远 ≤ 四舍五入值,评级永远由原值决定。
    """
    worse, same = 0, 0
    for x in range(0, 10_001):
        raw = x / 100
        d, r = display_score(raw), round(raw, 1)
        if d > r:
            _check("显示值不得高于四舍五入值", False, f"raw={raw} display={d} round={r}")
            return
        worse += (d < r)
        same += (d == r)
    _check(f"显示值永不高于四舍五入值(下让 {worse} 点 · 不变 {same} 点)", True)
    _check("下让只发生在带边界正下方(≤40 个点)", worse <= 40, str(worse))
    _check("单点偏离不超过 0.1",
           max(abs(display_score(x / 100) - round(x / 100, 1))
               for x in range(0, 10_001)) <= 0.1 + 1e-9)


def test_grade_floors_match_get_grade():
    """`GRADE_FLOORS` 必须与 `get_grade` 的阈值一致 —— 两处定义会漂移。

    ⚠️ 这是本文件里最容易腐烂的一条:`display_score` 依赖 `GRADE_FLOORS`,
    而 `get_grade` 有自己的一串 if。**同一组阈值写了两遍**,改一处不改另一处,
    显示值就会退到错误的带里,而且不会有任何报错。
    所以这里按行为对齐:每个下界处,以及它下方 0.01 处,评级必须正好切换。
    """
    bad = []
    for g, f in GRADE_FLOORS:
        if get_grade(f) != g:
            bad.append(f"get_grade({f}) = {get_grade(f)},而 GRADE_FLOORS 说是 {g}")
        if get_grade(f - 0.01) == g:
            bad.append(f"get_grade({f - 0.01}) 仍是 {g} —— 下界不在 {f}")
    _check("GRADE_FLOORS 与 get_grade 的阈值逐条一致", not bad, "; ".join(bad[:3]))
    _check("最高带 A+ 之上没有天花板(不会被下让)",
           display_score(99.99) == 100.0, str(display_score(99.99)))


def test_none_passes_through():
    """未打分 ≠ 0 分。None 原样返回,不得变成一个数。"""
    _check("display_score(None) is None", display_score(None) is None,
           str(display_score(None)))


def test_the_api_uses_it():
    """`/api/v1/cis/universe` 必须真的调用它,否则这个模块只是个正确的孤儿。

    按 AST 查:`cis.py` 里给 `cis_score` 赋值的地方,右侧必须是
    `display_score(...)` 调用,不能是裸的 `round(...)`。
    S-244 那一课:写了守卫 ≠ 守卫被执行;这里是 写了修复 ≠ 修复被调用。
    """
    import ast

    src = (ROOT / "src" / "api" / "routers" / "cis.py").read_text()
    tree = ast.parse(src)
    hits, round_hits = [], []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign) or len(n.targets) != 1:
            continue
        t = n.targets[0]
        if not (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                and t.slice.value == "cis_score"):
            continue
        rhs = ast.unparse(n.value)
        if "display_score" in rhs:
            hits.append(rhs)
        elif rhs.startswith("round("):
            round_hits.append(f"line {n.lineno}: {rhs[:60]}")
    _check("universe 的 cis_score 由 display_score 赋值", bool(hits), str(hits[:2]))
    _check("没有残留的裸 round() 赋给 cis_score", not round_hits, str(round_hits[:2]))


if __name__ == "__main__":
    print("── 显示分数与评级不得矛盾(穷举验证)(S-252) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 分数/评级一致性守卫全绿")
