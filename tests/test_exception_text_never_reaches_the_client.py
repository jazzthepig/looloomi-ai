"""异常原文不得进入 HTTP 响应 (S-247).

## 为什么要新写一条,而不是改现成的那条

仓库里已经有 `tests/test_no_stack_leakage_on_user_surfaces.py`,名字写着
「用户可见面不泄漏栈信息」,preflight 每次都跑,**每次都绿**。

实测 2026-08-27,它的 5 条断言是:

    test_no_vendor_or_hardware_names_in_rendered_strings
    test_the_paid_tier_list_does_not_describe_our_hardware
    test_a_retired_label_is_retired_everywhere
    test_the_rule_is_stated_where_the_nav_is_defined
    test_tier_meaning_survived_the_rewrite

**全部在扫 `dashboard/src/*.jsx` 里的厂商名/硬件名** —— 那是规则 #8 的地盘,
和「栈信息泄漏」没有关系。Python API 根本不在它的扫描范围里。

于是:`src/api/` 里有 **20 处**把异常原文塞进 `HTTPException(detail=...)`,
其中 `auth.py:276` 是不截断的 `str(e)`。**这 20 处从来没有被任何东西看过**,
而每次 preflight 都有一行绿色的「no stack leakage」滚过去。

> **一个名字宣称了某个属性,而没有任何东西检查它。**

这正是今天 S-244 的形状(「台账说它是回归测试,而它一次也没跑过」),
只不过这次落在安全面上:守卫的名字本身成了那个「被压掉的维度」——
读的人以为「有守卫 = 被检查」,而这两件事之间没有连线。

**没有改那个文件的名字**:它属于另一条 lane,而且它的 5 条断言各自是有效的,
只是名字取错了。改名会让 preflight 和台账里的引用一起断。这里加一条真的做这件事的。

## 为什么异常原文是安全问题

`detail` 直接进 HTTP body。异常原文里典型会带:

    · 数据库列名 / 表名 / 约束名(帮攻击者画出 schema)
    · 内部主机名与端口(`httpx.ConnectError: [Errno 111] ... 10.0.0.x:5432`)
    · 文件系统路径(部署布局)
    · 上游厂商的错误原话(反过来暴露我们用了谁 —— 也是规则 #8)

规则 #8 说投资人可见面不出现实现细节。一个 500 响应里的
`ConnectError to db.xxx.supabase.co:5432` 比 QuantMonitor 上那两个模型名
说得多得多,而后者今天上午刚被修掉。

## 三个状态,不是两个

    clean    detail 是我们自己写的常量文本
    frozen   已知的 20 处,冻结在基线里,只能减
    new      新增的一处 → 失败

不一次性修完 20 处,是因为每一处都要判断「这个调用方需要知道什么」——
那是 20 次产品判断,不是一次批量替换。基线让欠账**可见且不再增长**,
这和 `KNOWN_CODE_ONLY` / `_S195_KNOWN` 是同一个设计。

棘轮合法性 (S-238):这里守的是「源码里有没有把异常名塞进 detail」,
**纯代码属性,机器无关** —— 棘轮成立。
"""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCAN = (ROOT / "src" / "api",)
SKIP_PARTS = {"__pycache__", ".venv", "node_modules"}

#: 冻结的欠账。**只能减。** 每修好一处就删掉一行;新增的一处会直接失败。
#:
#: ⚠️ 键是 `路径::detail 表达式`,**不是行号** —— 这是变异测试逼出来的修正。
#: 第一版用 `路径:行号`,变异 A(在某个 offender 上方插一行)让**两条无关的欠账
#: 变成"新增"**。那不是抓到了缺陷,那是一个假阳性发生器:任何人在
#: `market.py` 上面加一行注释都会让 preflight 红,而修法是"重新生成基线"——
#: 于是基线变成每次盲目重刷的东西,棘轮就废了。
#:
#: **一个会因无关改动而误报的安全守卫,比没有守卫更糟**:它训练人去绕过它,
#: 而绕过的动作(重刷基线)恰好也会把真正的新增一起吞掉。
#: 表达式在行号漂移下稳定,而它变了就说明这处 detail 真的被改过 —— 那正是要看的。
#:
#: 已知代价,说出来而不是藏着:同一文件里两处**完全相同**的 detail 表达式会合并成
#: 一个键(实测 `ohlcv.py` 的两处 `str(e)[:200]` → 19 处坍成 18 个键)。
#: 后果是"只修了两处中的一处"不会被表扬,也不会被误报 —— 保守方向,可接受。
#: 换成行号能分开它们,但那要付上面那个假阳性的代价,而假阳性会废掉整个棘轮。
BASELINE = ROOT / "scripts" / "exception_detail_baseline.txt"


def _refs(node: ast.AST | None, name: str) -> bool:
    """`node` 这棵子树里有没有引用变量 `name`。

    ⚠️ 按构造查,不按字符串查。`detail=str(e)[:200]` 是
    Subscript(Call(Name('str'), [Name('e')])) —— 一个只找 `str(e)` 文本的检查
    会漏掉 `f"...{e}"`,而一个只找 `{e}` 的会漏掉 `repr(e)`。
    走 AST 就不用枚举写法。
    """
    if node is None:
        return False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == name:
            return True
    return False


def _is_httpexception(call: ast.expr) -> bool:
    if not isinstance(call, ast.Call):
        return False
    f = call.func
    return ((isinstance(f, ast.Name) and f.id == "HTTPException")
            or (isinstance(f, ast.Attribute) and f.attr == "HTTPException"))


def _offenders(path: pathlib.Path) -> list[tuple[int, str]]:
    """这个文件里,把 except 绑定的异常变量传进 HTTPException(detail=…) 的位置。"""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return []

    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        # 只看 `except ... as e:` —— 没有绑定名字的 handler 泄漏不了异常原文。
        if not isinstance(node, ast.ExceptHandler) or not node.name:
            continue
        var = node.name
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Raise) or not _is_httpexception(sub.exc):
                continue
            call = sub.exc
            assert isinstance(call, ast.Call)
            for kw in call.keywords:
                if kw.arg == "detail" and _refs(kw.value, var):
                    hits.append((sub.lineno, ast.unparse(kw.value)[:70]))
    return hits


def _load_baseline() -> set[str]:
    if not BASELINE.exists():
        return set()
    return {ln.split("#")[0].strip() for ln in BASELINE.read_text().splitlines()
            if ln.split("#")[0].strip()}


def _negative_control() -> list[str]:
    """分类器必须在合成样本上给出预期结果 —— 否则不要信它的报告。

    今天这个错法已经踩了九次(`tests/_source.py`),所以每条新守卫自带负控制。
    """
    import tempfile
    cases = {
        "bare_name":  ("try:\n    x()\nexcept Exception as e:\n"
                       "    raise HTTPException(status_code=500, detail=e)\n", True),
        "str_call":   ("try:\n    x()\nexcept Exception as e:\n"
                       "    raise HTTPException(status_code=500, detail=str(e))\n", True),
        "sliced":     ("try:\n    x()\nexcept Exception as e:\n"
                       "    raise HTTPException(status_code=500, detail=str(e)[:200])\n", True),
        "fstring":    ("try:\n    x()\nexcept Exception as e:\n"
                       "    raise HTTPException(status_code=500, detail=f'failed: {e}')\n", True),
        "repr_call":  ("try:\n    x()\nexcept Exception as e:\n"
                       "    raise HTTPException(status_code=500, detail=repr(e))\n", True),
        # 干净:自己写的常量文本,异常只进日志。
        "constant":   ("try:\n    x()\nexcept Exception as e:\n"
                       "    log.warning(e)\n"
                       "    raise HTTPException(status_code=500, detail='upstream unavailable')\n",
                       False),
        # 干净:异常变量出现在 status_code 之外的地方但没进 detail。
        "log_only":   ("try:\n    x()\nexcept Exception as e:\n"
                       "    log.exception('boom %s', e)\n"
                       "    raise HTTPException(status_code=502, detail='bad gateway')\n", False),
        # 干净:没有绑定异常变量。
        "no_binding": ("try:\n    x()\nexcept Exception:\n"
                       "    raise HTTPException(status_code=500, detail='failed')\n", False),
    }
    bad: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        for key, (src, should_flag) in cases.items():
            p = pathlib.Path(td) / f"_ctl_{key}.py"
            p.write_text(src)
            flagged = bool(_offenders(p))
            if flagged != should_flag:
                bad.append(f"负控制失败:样本 '{key}' 应{'命中' if should_flag else '放行'},"
                           f"实际{'命中' if flagged else '放行'} —— 先修 _offenders,再信它的报告")
    return bad


def main() -> int:
    ctl = _negative_control()
    if ctl:
        print("✗ " + "\n✗ ".join(ctl))
        return 1

    found: dict[str, str] = {}
    for base in SCAN:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if set(p.parts) & SKIP_PARTS:
                continue
            rel = str(p.relative_to(ROOT))
            for lineno, expr in _offenders(p):
                # 键不含行号(见 BASELINE 上的说明);行号只用于打印定位。
                found[f"{rel}::{expr}"] = f"{rel}:{lineno}"

    baseline = _load_baseline()
    new = sorted(set(found) - baseline)
    fixed = sorted(baseline - set(found))

    if new:
        print(f"✗ {len(new)} 处【新增】把异常原文放进 HTTP detail:")
        for k in new:
            print(f"   · {found[k]}  detail={k.split('::', 1)[1]}")
        print("  异常原文会带出表名/内部主机名/文件路径/上游厂商原话 —— 后者还违反规则 #8。")
        print("  写一句自己的文本给调用方,异常进日志。")
        return 1

    if fixed:
        # 只能减:修好了却还留在基线里 → 失败,否则基线会变成永久特赦。
        print(f"✗ {len(fixed)} 处已经修好了,却还留在 {BASELINE.name} 里 —— 删掉这些行:")
        for k in fixed:
            print(f"      {k}")
        return 1

    print(f"  ✓ 异常原文未进 HTTP detail(新增 0 处 · {len(baseline)} 处欠账冻结,只能减)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
