"""进程内「先给旧的、后台换新」缓存 + 单飞(Jazz 2026-11-14「速度也有很大问题」)。

量到的形状(11-14,线上):`/api/v1/cis/attribution` 每次缓存过期,下一个请求要把 2.7 万行、18 MB 的表分 27 页重读一遍,12–19 秒;
缓存 10 分钟过期,所以这 19 秒每 10 分钟就有一个人(或预热循环)替大家付一次。而这张表一天才变一次。同一形状还在协议页(冷 4–7 秒)、
两本账、证明页上 —— 都是「过期 ⇒ 现算 ⇒ 现算的那个人等」。

这里换成:**有值就立刻给**(哪怕过期),过期了由后台刷一次;同时到的请求共用同一次读(单飞),不各读各的。
没有值(刚部署)⇒ 等这一次读。旧值老过 `max_stale_s` ⇒ 不再给旧的,等新的 —— 读坏了不能无限期端着旧数装没事。
读失败:有旧值 ⇒ 继续给旧值、错误记在 `state()` 里;没旧值 ⇒ 把错抛给调用方(读不到 ≠ 空)。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Optional

_log = logging.getLogger(__name__)
_E: dict[str, dict] = {}


def _entry(key: str) -> dict:
    return _E.setdefault(key, {"at": 0.0, "value": None, "has": False, "task": None, "err": None, "loads": 0})


async def _refresh(key: str, loader: Callable[[], Awaitable[Any]]) -> None:
    e = _entry(key)
    try:
        v = await loader()
        e.update(value=v, at=time.time(), has=True, err=None)
    except Exception as ex:                                              # noqa: BLE001 —— 记下,由调用方按有没有旧值决定
        e["err"] = ex
        _log.warning("[SWR] %s refresh failed: %s: %s", key, type(ex).__name__, str(ex)[:160])
    finally:
        e["loads"] += 1


async def swr(key: str, ttl_s: float, loader: Callable[[], Awaitable[Any]], max_stale_s: Optional[float] = None) -> Any:
    e = _entry(key)
    now = time.time()
    if e["has"] and now - e["at"] <= ttl_s:
        return e["value"]
    if e["task"] is None or e["task"].done():
        e["task"] = asyncio.ensure_future(_refresh(key, loader))
    usable = e["has"] and (max_stale_s is None or now - e["at"] <= max_stale_s)
    if usable:
        return e["value"]
    await asyncio.shield(e["task"])
    if e["has"] and (max_stale_s is None or time.time() - e["at"] <= max_stale_s):
        return e["value"]
    raise e["err"] or RuntimeError(f"{key}: 没有可用的值")


def state(key: str) -> dict:
    """给判活 / 测试看:有没有值、多旧、读过几次、最近一次错。"""
    e = _entry(key)
    return {"has": e["has"], "age_s": (time.time() - e["at"]) if e["has"] else None, "loads": e["loads"],
            "refreshing": bool(e["task"] and not e["task"].done()), "error": None if e["err"] is None else f"{type(e['err']).__name__}: {e['err']}"}


def reset(key: Optional[str] = None) -> None:
    if key is None:
        _E.clear()
    else:
        _E.pop(key, None)
