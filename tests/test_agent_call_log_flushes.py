"""S-562:agent_call_log 自上线 0 行 —— 后台写入任务只在 import 时尝试启动(那时没有运行中的事件循环,直接 return),
注释说「首个请求时再启动」,却没有任何地方再启动它;队列只进不出。

这里不导入整个 MCP(干净机器上没有 mcp 包),只取出这几个函数在桩环境里跑。
"""
from __future__ import annotations

import ast
import asyncio
import os
import queue
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "src/mcp/cometcloud_mcp.py").read_text(encoding="utf-8")
NAMES = ("_ensure_call_log_task", "_enqueue_agent_call", "_call_log_loop")


def _ns(sb_url: str) -> dict:
    fns = [n for n in ast.parse(SRC).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in NAMES]
    assert {f.name for f in fns} == set(NAMES)
    flushed: list = []

    async def _flush_call_log():
        while True:
            try:
                flushed.append(ns["_call_log_queue"].get_nowait())
            except queue.Empty:
                return

    ns = {"asyncio": asyncio, "queue": queue, "os": os, "datetime": datetime, "timezone": timezone,
          "_call_log_queue": queue.Queue(), "_SB_URL": sb_url, "_SB_KEY": "k" if sb_url else "",
          "_background_task": None, "_CALL_LOG_MAX": 3, "_flush_call_log": _flush_call_log, "flushed": flushed}
    exec(compile(ast.Module(body=fns, type_ignores=[]), "cometcloud_mcp", "exec"), ns)
    return ns


def test_first_call_inside_a_running_loop_starts_the_writer_and_rows_get_flushed() -> None:
    ns = _ns("https://x.supabase.co")

    async def run():
        ns["_enqueue_agent_call"]("cometcloud_get_cis_top", None, 12.0, 100)
        assert ns["_background_task"] is not None, "第一次调用就要把后台写入任务起起来"
        await asyncio.sleep(1.3)
        ns["_background_task"].cancel()
    asyncio.run(run())
    assert len(ns["flushed"]) == 1 and ns["flushed"][0]["tool_name"] == "cometcloud_get_cis_top"


def test_queue_is_bounded_and_nothing_starts_without_supabase() -> None:
    ns = _ns("")
    for i in range(10):
        ns["_enqueue_agent_call"](f"t{i}")
    assert ns["_background_task"] is None, "没配 Supabase(本地 stdio)不启动"
    assert ns["_call_log_queue"].qsize() == 3, "写不出去时只留最近的几条,不让内存无限涨"
