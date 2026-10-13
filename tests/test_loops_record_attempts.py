"""S-564 / T-061:每个后台循环每一轮都要在 loop_attempt 留痕。

10-13 起 loop-watch 与判活都以 loop_attempt 为主仪表(/internal/* 要 token,定时任务没有)。当时 main.py 里
24 个循环既不写 _beat、也不写 loop_attempt —— 它们停了,哪个仪表都看不见。这里守:main.py 里带 `while True` 的
循环,要么自己写 `_record_loop_attempt` / `_beat`,要么经 `_iteration_ok` / `_iteration_error`。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKERS = ("_record_loop_attempt(", "_beat(", "_iteration_ok(", "_iteration_error(")


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
        if "_iteration_ok(" in seg:
            assert "_iteration_error(" in seg, f"{name}: 成功写了 ok,失败分支没记"
