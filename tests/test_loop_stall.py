"""事件循环卡顿的测量(src/api/loop_stall.py,S-862 补二)。

每次部署后两段 75–175 秒的停顿是从 loop_attempt 的空白和边缘日志里量出来的;谁在占着循环,要在卡住的当时看栈。
这里钉住:状态机什么时候算卡、什么时候抓栈、什么时候算结束;抓到的栈里有调用它的那一行;真线程真循环跑一遍。
"""
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api import loop_stall as ls            # noqa: E402


def test_a_short_pause_is_not_a_stall_and_a_long_one_is_sampled_as_it_grows():
    st, grabbed = {}, []

    def grab():
        grabbed.append(1)
        return ["src/api/main.py:1 _x_loop", "src/data/x.py:9 heavy"]
    assert ls.observe(st, now=103.0, tick=100.0, grab=grab) is None and not st.get("cur"), "3 秒不算卡"
    assert ls.observe(st, now=105.5, tick=100.0, grab=grab) is None and st["cur"]["lag_s"] == 5.5
    assert len(grabbed) == 1, "一过 5 秒就抓第一次"
    ls.observe(st, now=110.0, tick=100.0, grab=grab)
    assert len(grabbed) == 1, "5 到 15 秒之间不重复抓"
    ls.observe(st, now=116.0, tick=100.0, grab=grab)
    ls.observe(st, now=131.0, tick=100.0, grab=grab)
    assert len(grabbed) == 3 and [s["lag_s"] for s in st["cur"]["samples"]] == [5.5, 16.0, 31.0]
    ended = ls.observe(st, now=204.2, tick=204.0, grab=grab)
    assert ended is not None and ended["lag_s"] == 31.0 and st["cur"] is None, "循环又转了 ⇒ 这次卡顿结束,交出来"
    assert ls.observe(st, now=205.0, tick=204.8, grab=grab) is None, "结束之后不重复交"


def test_the_sentence_names_the_line_and_the_loop_it_came_from():
    stall = {"at": "2026-11-14 08:35:42", "lag_s": 104.0, "samples": [
        {"lag_s": 5.2, "frames": ["src/api/main.py:3300 _core_pit_loop", "src/data/signals/core_pit.py:88 run_once",
                                  "src/data/signals/core_pit.py:140 build", "[frame.py:9000 apply]"]},
        {"lag_s": 15.1, "frames": ["src/api/main.py:3300 _core_pit_loop", "src/data/signals/core_pit.py:140 build",
                                   "[generic.py:1200 _reduce]"]},
        {"lag_s": 30.0, "frames": ["src/api/main.py:2100 _other_loop", "src/data/other.py:5 f"]}]}
    assert ls.where(stall) == "src/data/signals/core_pit.py:140 build", "三次采样里两次在同一行 ⇒ 说这一行"
    txt = ls.describe(stall)
    assert "104.0 秒" in txt and "core_pit.py:140 build" in txt and "_core_pit_loop" in txt and "frame.py:9000 apply" in txt
    assert "没抓到" in ls.describe({"at": "x", "lag_s": 6.0, "samples": [{"lag_s": 5.0, "frames": ["[selectors.py:1 select]"]}]})


def test_frames_keep_repo_code_outermost_first_plus_the_innermost_library_frames():
    def inner():
        return ls.app_frames(sys._getframe(), root=str(ROOT))

    def outer():
        return inner()
    fr = outer()
    mine = [f for f in fr if not f.startswith("[")]
    assert mine[-1].startswith("tests/test_loop_stall.py:") and mine[-1].endswith(" inner")
    assert mine[-2].endswith(" outer"), "外层在前:读的人顺着就能找到是哪条循环进来的"
    assert not any("site-packages" in f for f in mine)


def test_a_real_block_on_a_real_loop_is_caught_with_the_blocking_line(monkeypatch):
    monkeypatch.setattr(ls, "STALL_S", 0.25)
    monkeypatch.setattr(ls, "SAMPLE_AT", (0.25, 0.6, 1.2))
    monkeypatch.setattr(ls, "SAMPLE_S", 0.05)
    monkeypatch.setattr(ls, "TICK_S", 0.02)
    ls.stop()
    ls.drain()

    def the_blocking_call():
        time.sleep(0.9)                                  # 同步睡:事件循环在这一行上一动不动

    async def main():
        assert ls.start() is True and ls.start() is False, "重复启动无害"
        for _ in range(5):
            await asyncio.sleep(0.05)
        the_blocking_call()
        for _ in range(12):                              # 让出控制权,看门线程看到循环又转了
            await asyncio.sleep(0.05)
        got = ls.drain()
        ls.stop()
        return got
    got = asyncio.run(main())
    for _ in range(40):                                  # 停了之后看门线程在下一拍退出
        if not ls.watching():
            break
        time.sleep(0.05)
    assert not ls.watching(), "stop() 之后线程要退出 —— 探针 / 测试进程里不能留一条一直在抓栈的线程"
    assert len(got) == 1, f"一次阻塞 = 一条记录,拿到 {len(got)}"
    assert 0.5 <= got[0]["lag_s"] <= 3.0, got[0]["lag_s"]
    assert "the_blocking_call" in ls.where(got[0]), ls.describe(got[0])
    assert ls.drain() == [], "取走即清"


def test_the_app_starts_the_watch_and_reports_both_stalls_and_quiet():
    src = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    i = src.index("async def _loop_stall_loop(")
    body = src[i:src.index("\n\n\n", i)]
    assert '_beat("_loop_stall_loop"' in body and "_record_loop_attempt(" in body, "卡顿要进心跳,也要进 loop_attempt"
    assert "drain()" in body and "describe(" in body
    assert body.count('"ok"') >= 1, "没有卡顿也要定期记一条 ok —— 否则「没卡」和「没在看」分不出来"
    assert "_ls.start()" in body and "_ls.stop()" in body, "看门线程跟着这条循环起、跟着它停"
    j = src.index("async def _start_loop_stall_watch(")
    handler = src[j:src.index("\n\n\n", j)]
    assert "create_task(_loop_stall_loop())" in handler
    assert "start()" not in handler, (
        "启动钩子里只许起那条 *_loop 任务:启动探针按名字跳过 *_loop(S-161),钩子里直接起线程的话,探针里也会跑")
