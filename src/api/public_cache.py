"""公开 GET 的源站缓存:接口自己声明了 `Cache-Control: public, max-age=N`,源站先把这句话兑现(Jazz 2026-11-14「数据出来的速度也很慢」)。

量到的(S-859):几十个公开接口都标着可缓存,但没有任何一层真的在缓存 —— 边缘节点不缓存(`cf-cache-status: DYNAMIC`),源站每个请求
都重新算或重新读库。访客少、各接口自己的缓存又短,于是几乎每个人都是「过期后的第一个」,等 1–19 秒。

这一层放在路由正上方(GZip / 限流 / CORS 都在它外面):
- 命中且没过 max-age ⇒ 直接给(`x-cache: HIT`)。
- 过了 max-age、还在可容忍的旧值年龄内 ⇒ **先给旧的**(`x-cache: STALE`,带 `age`),后台把这个请求原样再跑一遍换新;同一个键同时只刷一次。
- 没有值 / 太旧 ⇒ 照常跑路由,同时到的同键请求等这一次的结果,不各算各的。
- 只存:200、没有 `set-cookie`、体积 ≤ 2 MB,且路由声明了 `public, max-age > 0`(按它声明的来)**或什么缓存头都没写的 JSON**
  (缺省 30 秒新、旧值最多 5 分钟);写了 no-store / private / no-cache / max-age=0 的不存。带凭据的请求(Authorization / X-API-Key /
  内部 token / Cookie)与交易、鉴权、密钥、分析这些前缀一律不进这一层。请求头带 `cache-control: no-cache` ⇒ 不读缓存(硬刷新照常拿新的)。
- 旧值最多给到 max-age 的 12 倍、且不超过 1 小时;响应里各接口自己的 `as_of` 照旧,旧不旧看得见。
关掉:环境变量 `PUBLIC_CACHE=0`。判活:响应头 `x-cache`;`stats()`。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections import OrderedDict
from typing import Any, Optional

_log = logging.getLogger(__name__)

MAX_BODY = 2_000_000
MAX_TOTAL = 96_000_000
MAX_ENTRIES = 600
STALE_FACTOR, STALE_MIN_S, STALE_CAP_S = 12, 300, 3600
FOLLOWER_WAIT_S = 45.0
PREFIX = "/api/v1/"
EXCLUDE = ("/api/v1/trading/", "/api/v1/auth/", "/api/v1/keys/", "/api/v1/analytics/", "/api/v1/leads/", "/api/v1/webhooks/",
           "/api/v1/agent/tasks", "/api/v1/onchain/", "/api/v1/factory/", "/api/v1/health", "/api/v1/vault/deposit")
CREDENTIAL_HEADERS = ("authorization", "x-api-key", "x-internal-token", "x-executor-token", "cookie")
_MAX_AGE = re.compile(r"max-age\s*=\s*(\d+)")

_C: "OrderedDict[str, dict]" = OrderedDict()
_INFLIGHT: dict[str, asyncio.Future] = {}
_REFRESHING: set[str] = set()
_N = {"hit": 0, "stale": 0, "miss": 0, "stored": 0, "refresh": 0, "refresh_failed": 0}


def eligible(path: str, headers: dict[str, str]) -> bool:
    return (path.startswith(PREFIX) and not any(path.startswith(x) for x in EXCLUDE)
            and not any(h in headers for h in CREDENTIAL_HEADERS))


#: 没声明缓存头的公开 JSON 接口的缺省:30 秒内算新的,旧值最多给到 5 分钟。11-14 上线后重量:104 个公开接口里 61 个什么都没声明,
#: 最慢的全在这 61 个里(research/channels 9.8 秒、core-alpha 7.3 秒、ohlcv/coverage 6.5 秒…)—— 只兑现「声明过的」帮不到它们。
#: 明确写了 no-store / private / no-cache / max-age=0 的照旧不存;要更长或更短,在路由里声明。
DEFAULT_MAX_AGE, DEFAULT_STALE_S = 30, 300


def storable(status: Optional[int], headers: list, body: Optional[bytes]) -> Optional[tuple[int, int]]:
    """能存 ⇒ (max-age 秒, 旧值最多给到多少秒);不能 ⇒ None。"""
    if status != 200 or body is None:
        return None
    h = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in headers}
    cc = h.get("cache-control", "").lower()
    if "no-store" in cc or "private" in cc or "no-cache" in cc or "set-cookie" in h or "content-encoding" in h:
        return None
    m = _MAX_AGE.search(cc)
    if m:
        n = int(m.group(1))
        return (n, min(max(n * STALE_FACTOR, STALE_MIN_S), STALE_CAP_S)) if n > 0 and "public" in cc else None
    if cc or "json" not in h.get("content-type", "").lower():
        return None                                                       # 有缓存头但没给 max-age、或不是 JSON:不猜
    return DEFAULT_MAX_AGE, DEFAULT_STALE_S


def _store(key: str, status: Optional[int], headers: list, body: Optional[bytes], now: float) -> bool:
    policy = storable(status, headers, body)
    if policy is None:
        return False
    keep = [(k, v) for k, v in headers if k.lower() not in (b"content-length", b"date", b"age", b"x-cache")]
    _C[key] = {"at": now, "max_age": policy[0], "stale_age": policy[1], "headers": keep, "body": body}
    _C.move_to_end(key)
    _N["stored"] += 1
    total = sum(len(e["body"]) for e in _C.values())
    while _C and (len(_C) > MAX_ENTRIES or total > MAX_TOTAL):
        _, old = _C.popitem(last=False)
        total -= len(old["body"])
    return True


async def _run(app, scope, receive, send) -> tuple[Optional[int], list, Optional[bytes]]:
    """跑一遍内层应用;`send` 不为空就原样转发给客户。返回 (状态, 头, 体);体超过上限 ⇒ None。"""
    st: dict[str, Any] = {"status": None, "headers": [], "chunks": [], "size": 0, "over": False}

    async def cap(msg):
        if msg["type"] == "http.response.start":
            st["status"], st["headers"] = msg["status"], list(msg.get("headers") or [])
        elif msg["type"] == "http.response.body" and not st["over"]:
            b = msg.get("body") or b""
            st["size"] += len(b)
            if st["size"] > MAX_BODY:
                st["over"], st["chunks"] = True, []
            else:
                st["chunks"].append(b)
        if send is not None:
            await send(msg)
    await app(scope, receive, cap)
    return st["status"], st["headers"], (None if st["over"] else b"".join(st["chunks"]))


async def _send_cached(send, e: dict, age: float, tag: str) -> None:
    headers = list(e["headers"]) + [(b"content-length", str(len(e["body"])).encode()), (b"age", str(int(age)).encode()),
                                    (b"x-cache", tag.encode())]
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({"type": "http.response.body", "body": e["body"], "more_body": False})


class PublicCacheMiddleware:
    def __init__(self, app, enabled: Optional[bool] = None):
        self.app = app
        self.enabled = (os.environ.get("PUBLIC_CACHE", "1").strip().lower() not in ("0", "off", "false", "no")) if enabled is None else enabled

    async def __call__(self, scope, receive, send):
        if not self.enabled or scope["type"] != "http" or scope.get("method") != "GET":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        if not eligible(path, headers):
            return await self.app(scope, receive, send)
        key = path + "?" + (scope.get("query_string") or b"").decode("latin-1")
        force = "no-cache" in headers.get("cache-control", "").lower() or "no-cache" in headers.get("pragma", "").lower()
        e = None if force else _C.get(key)
        if e is not None:
            age = time.time() - e["at"]
            if age <= e["max_age"]:
                _N["hit"] += 1
                _C.move_to_end(key)
                return await _send_cached(send, e, age, "HIT")
            if age <= e["stale_age"]:
                _N["stale"] += 1
                self._kick(key, scope)
                return await _send_cached(send, e, age, "STALE")
        fut = None if force else _INFLIGHT.get(key)
        if fut is not None:                                               # 同一个键正有人在算:等它,不再算一遍
            try:
                await asyncio.wait_for(asyncio.shield(fut), timeout=FOLLOWER_WAIT_S)
            except Exception:                                             # noqa: BLE001 —— 等不到就自己算
                pass
            e = _C.get(key)
            if e is not None and time.time() - e["at"] <= e["stale_age"]:
                _N["hit"] += 1
                return await _send_cached(send, e, time.time() - e["at"], "HIT")
        _N["miss"] += 1
        mine = asyncio.get_running_loop().create_future()
        _INFLIGHT.setdefault(key, mine)
        try:
            status, hdrs, body = await _run(self.app, scope, receive, send)
            _store(key, status, hdrs, body, time.time())
        finally:
            if _INFLIGHT.get(key) is mine:
                _INFLIGHT.pop(key, None)
            if not mine.done():
                mine.set_result(None)

    def _kick(self, key: str, scope) -> None:
        if key in _REFRESHING:
            return
        _REFRESHING.add(key)
        s2 = {**scope, "headers": [(k, v) for k, v in scope.get("headers") or [] if k.lower() in (b"host", b"accept", b"user-agent")]}
        first = {"sent": False}

        async def recv():
            if not first["sent"]:
                first["sent"] = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Event().wait()                                  # 之后一直不来消息(也不报断开),直到任务结束

        async def job():
            try:
                status, hdrs, body = await _run(self.app, s2, recv, None)
                _N["refresh"] += 1
                if not _store(key, status, hdrs, body, time.time()):
                    _N["refresh_failed"] += 1                             # 刷新拿到的不是可存的 200:旧值照旧按年龄上限处理
            except Exception as ex:                                       # noqa: BLE001
                _N["refresh_failed"] += 1
                _log.warning("[PUBLIC-CACHE] refresh %s failed: %s: %s", key, type(ex).__name__, str(ex)[:160])
            finally:
                _REFRESHING.discard(key)
        asyncio.ensure_future(job())


def stats() -> dict:
    return {**_N, "entries": len(_C), "bytes": sum(len(e["body"]) for e in _C.values()), "refreshing": len(_REFRESHING)}


def reset() -> None:
    _C.clear()
    _INFLIGHT.clear()
    _REFRESHING.clear()
    for k in _N:
        _N[k] = 0
