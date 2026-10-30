"""S-564 / T-061:每个后台循环每一轮都要在 loop_attempt 留痕。

10-13 起 loop-watch 与判活都以 loop_attempt 为主仪表(/internal/* 要 token,定时任务没有)。当时 main.py 里
24 个循环既不写 _beat、也不写 loop_attempt —— 它们停了,哪个仪表都看不见。这里守:main.py 里带 `while True` 的
循环,要么自己写 `_record_loop_attempt` / `_beat`,要么经 `_iteration_ok` / `_iteration_error`。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKERS = ("_record_loop_attempt(", "_beat(", "_iteration_ok(", "_iteration_error(", "_iteration_result(")


def _loops():
    src = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name.endswith("_loop"):
            seg = ast.get_source_segment(src, n) or ""
            if any(isinstance(w, ast.While) for w in ast.walk(n)):
                yield n.name, seg


def test_every_while_loop_leaves_a_trace() -> None:
    silent = [name for name, seg in _loops() if not any(m in seg for m in MARKERS)]
    assert not silent, f"这些循环停了没有任何仪表看得见:{silent}"


def test_error_path_is_recorded_too() -> None:
    """只在成功路径写 ok 不够:异常分支也要记(那正是要看见的)。"""
    for name, seg in _loops():
        if "_iteration_ok(" in seg or "_iteration_result(" in seg:
            assert "_iteration_error(" in seg, f"{name}: 成功写了 ok,失败分支没记"


def test_a_result_dict_decides_the_verdict_not_the_fact_that_the_call_returned() -> None:
    """10-30:`_regime_fitness_loop` 四个月 ok=True rows=0 —— 函数回 ok=False/degraded,循环照旧 `_iteration_ok`,
    cis_regime_fitness 0 行没人看见。守:循环里把函数返回值接到 `res` / `r` 并打印 ok=/status= 的,不能再无条件记 ok。"""
    import re
    bad = []
    for name, seg in _loops():
        if "_iteration_ok(" not in seg:
            continue
        if re.search(r"(res|r)\.get\(['\"](ok|status)['\"]\)", seg) and "_iteration_result(" not in seg:
            bad.append(name)
    assert not bad, f"这些循环拿到了 ok/status 却无条件记 ok(用 _iteration_result):{bad}"


def test_iteration_result_logic_pinned() -> None:
    """纯逻辑:ok=False / status=failed ⇒ 不记 ok;degraded ⇒ refused。从 main.py 抽函数体跑,不起 app。"""
    import ast as _ast, asyncio, types
    src = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    tree = _ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, _ast.AsyncFunctionDef) and n.name == "_iteration_result")
    calls: list = []
    ns: dict = {}
    async def _ok(name): calls.append(("ok", name))
    async def _rec(name, outcome, reason=None, detail=None, writer=None): calls.append((outcome, name, reason))
    ns.update({"_iteration_ok": _ok, "_record_loop_attempt": _rec})
    exec(compile(_ast.Module(body=[fn], type_ignores=[]), "main_slice", "exec"), ns)
    f = ns["_iteration_result"]
    asyncio.run(f("a", {"ok": True})); asyncio.run(f("b", {"ok": False, "degraded": True, "reason": "thin"}))
    asyncio.run(f("c", {"status": "failed", "error": "redis"}, ok_key="status")); asyncio.run(f("d", {"status": "ok"}, ok_key="status"))
    asyncio.run(f("e", None)); asyncio.run(f("g", {"status": "nothing_to_flush"}, ok_key="status"))
    asyncio.run(f("h", {"status": "unconfigured"}, ok_key="status"))
    assert calls == [("ok", "a"), ("refused", "b", "thin"), ("error", "c", "redis"), ("ok", "d"), ("ok", "e"), ("ok", "g"), ("ok", "h")], calls
