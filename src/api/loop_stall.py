"""事件循环卡住的时候,记下它卡在哪一行(S-862 补二,2026-11-14)。

## 量到的事实(measured via Supabase:loop_attempt、边缘日志)

每次部署后约 5 分钟和约 9 分钟,进程各有一段 **75–175 秒什么都不做**:`loop_attempt` 一行不落,对库的请求从
每分钟 500–900 掉到几十;之后二十多个循环在几秒内一起交卷。11-13 18:00 到 11-14 08:40 的 12 次部署,次次如此。

那一段里:库已经回了 200 的响应来不及收(08:35:41 那一页 0.39 秒就回了,客户端 08:37:26 报「读不到」)⇒ 循环
白跑一轮;执行主机拿到 502;网站不回应。

## 为什么要在进程里看

是谁占着循环,从外面看不出来 —— 外面只能看到「没有动静」。卡住的当时,主线程的调用栈就是答案。

## 做法

循环里一个协程每 `TICK_S` 记一次时间;**另一条线程**每 `SAMPLE_S` 看一眼,超过 `STALL_S` 没动就抓主线程的栈
(`sys._current_frames()`),在卡到 5 / 15 / 30 / 60 / 120 / 240 秒时各抓一次。线程只读一个浮点数,不碰事件循环。
结束了的卡顿由 `main._loop_stall_loop` 取走(`drain()`),写进心跳和 `loop_attempt`。

这是测量,不是修复:它不让循环少卡一秒,只让下一次卡住时有一行文件名可看。
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

#: 循环多久没转算卡住。5 秒:客户端读超时是 10 秒,卡到一半就该记下来。
STALL_S = 5.0
TICK_S = 0.5
SAMPLE_S = 1.0
#: 卡到这些秒数时各抓一次栈 —— 一次卡顿里可能先后是不同的函数在占。
SAMPLE_AT = (5.0, 15.0, 30.0, 60.0, 120.0, 240.0)
KEEP = 50

_ROOT = str(Path(__file__).resolve().parents[2])
_LOCK = threading.Lock()
_S: dict[str, Any] = {"tick": 0.0, "cur": None, "done": [], "thread_id": None, "gen": 0, "thread": None, "ticker": None}


def _is_library(rel: str) -> bool:
    """虚拟环境建在仓库目录里(线上是 `.venv/`)⇒ 路径在仓库下面不等于是我们的代码。第一次上线抓到的四次卡顿里,
    两次把「卡在哪」报成了 numpy / httpcore 里的一行 —— 要改的是调它的那一行。"""
    r = "/" + rel.replace("\\", "/").lstrip("/")
    return "/site-packages/" in r or r.startswith(("/.venv/", "/venv/")) or "/lib/python" in r


def app_frames(frame: Any, root: str = _ROOT, tail: int = 2) -> list[str]:
    """一帧往外的调用链 → `路径:行 函数`,**外层在前**。只留仓库里的帧,外加最里面 `tail` 帧(库函数:
    真正在烧 CPU 的那一行常常在 pandas / json 里,但要改的是调它的那一行)。"""
    chain = []
    f = frame
    while f is not None:
        chain.append((f.f_code.co_filename, f.f_lineno, f.f_code.co_name))
        f = f.f_back
    chain.reverse()
    out = []
    for i, (fn, ln, name) in enumerate(chain):
        inner = i >= len(chain) - tail
        if fn.startswith(root) and not _is_library(fn[len(root):]):
            out.append(f"{fn[len(root):].lstrip('/')}:{ln} {name}")
        elif inner:
            out.append(f"[{Path(fn).name}:{ln} {name}]")
    return out


def observe(state: dict, now: float, tick: float, grab: Callable[[], list[str]],
            wall: Optional[Callable[[], str]] = None) -> Optional[dict]:
    """一次采样(纯状态机,线程里每 `SAMPLE_S` 调一次)。返回**刚结束**的那次卡顿;还在卡或没卡 ⇒ None。"""
    lag = now - tick
    cur = state.get("cur")
    if lag >= STALL_S:
        if cur is None:
            cur = state["cur"] = {"at": (wall or _utc)(), "lag_s": 0.0, "samples": []}
        cur["lag_s"] = round(lag, 1)
        n = len(cur["samples"])
        if n < len(SAMPLE_AT) and lag >= SAMPLE_AT[n]:
            cur["samples"].append({"lag_s": round(lag, 1), "frames": grab()})
        return None
    if cur is not None:
        state["cur"] = None
        return cur
    return None


def where(stall: dict) -> str:
    """这次卡顿最常落在仓库里的哪一行(最里面的一帧仓库代码)。"""
    seen: dict[str, int] = {}
    for s in stall.get("samples") or []:
        mine = [fr for fr in s.get("frames") or [] if not fr.startswith("[")]
        if mine:
            seen[mine[-1]] = seen.get(mine[-1], 0) + 1
    return max(seen, key=lambda k: seen[k]) if seen else ""


def describe(stall: dict) -> str:
    """人读的一句:卡了多久、卡在哪、从哪条循环进来的。"""
    samples = stall.get("samples") or []
    top = where(stall)
    first = next((fr for s in samples for fr in s.get("frames") or [] if "_loop" in fr and not fr.startswith("[")), "")
    lib = next((fr for s in samples for fr in reversed(s.get("frames") or []) if fr.startswith("[")), "")
    txt = f"事件循环卡住 {stall.get('lag_s')} 秒(自 {stall.get('at')})"
    if top:
        txt += f";卡在 {top}"
        if first and first != top:
            txt += f" ← {first}"
        if lib:
            txt += f";最里面是 {lib.strip('[]')}"
    else:
        txt += ";没抓到仓库里的帧"
    return txt + f"(采样 {len(samples)} 次)"


def drain() -> list[dict]:
    """取走已经结束的卡顿(取走即清)。"""
    with _LOCK:
        out, _S["done"] = list(_S["done"]), []
    return out


def watching() -> bool:
    th = _S.get("thread")
    return bool(th is not None and th.is_alive())


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _grab() -> list[str]:
    return app_frames(sys._current_frames().get(_S["thread_id"]))


def _watch(gen: int) -> None:
    while _S["gen"] == gen:                                               # 每次 start() 换一代;旧线程看到代数变了就退出
        time.sleep(SAMPLE_S)
        try:
            ended = observe(_S, time.monotonic(), float(_S["tick"]), _grab)
            if ended is not None:
                with _LOCK:
                    _S["done"] = (_S["done"] + [ended])[-KEEP:]
        except Exception:                                                  # noqa: BLE001 —— 看门的线程不能自己倒下
            pass


async def _ticker(gen: int) -> None:
    while _S["gen"] == gen:
        _S["tick"] = time.monotonic()
        await asyncio.sleep(TICK_S)


def start() -> bool:
    """在事件循环所在的线程里调(`main._loop_stall_loop` 开头)。已经在看同一个循环 ⇒ 不重复起,返回 False。"""
    t = _S.get("ticker")
    if watching() and t is not None and not t.done():
        return False
    _S["gen"] += 1
    gen = _S["gen"]
    _S.update(thread_id=threading.get_ident(), tick=time.monotonic(), cur=None)
    _S["ticker"] = asyncio.get_running_loop().create_task(_ticker(gen))
    _S["thread"] = threading.Thread(target=_watch, args=(gen,), name="loop-stall-watch", daemon=True)
    _S["thread"].start()
    return True


def stop() -> None:
    """循环退出(或测试收尾)时调:线程和协程在下一拍各自退出。"""
    _S["gen"] += 1
    t = _S.get("ticker")
    if t is not None and not t.done():
        t.cancel()
    _S["ticker"] = None
