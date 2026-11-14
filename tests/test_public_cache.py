"""`src/api/public_cache.py`:源站兑现接口自己声明的可缓存;先给旧的、后台换新;带凭据 / 没声明 / 出错的一律不存。"""
import asyncio

from src.api import public_cache as pc


def _app(counter, cache_control="public, max-age=60", status=200, slow=None, extra=()):
    async def app(scope, receive, send):
        counter["n"] += 1
        n = counter["n"]
        if slow is not None and n >= 2:
            await slow.wait()
        headers = [(b"content-type", b"application/json")] + list(extra)
        if cache_control:
            headers.append((b"cache-control", cache_control.encode()))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": f'{{"n":{n}}}'.encode(), "more_body": False})
    return app


async def _get(mw, path="/api/v1/x", headers=(), method="GET", query=b""):
    out = {"status": None, "headers": {}, "body": b""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
            out["headers"] = {k.decode(): v.decode() for k, v in msg["headers"]}
        else:
            out["body"] += msg.get("body") or b""
    await mw({"type": "http", "method": method, "path": path, "query_string": query, "headers": list(headers)}, receive, send)
    return out


def test_second_request_is_served_from_the_cache_and_says_so():
    pc.reset()
    c = {"n": 0}
    mw = pc.PublicCacheMiddleware(_app(c), enabled=True)

    async def go():
        a = await _get(mw)
        b = await _get(mw)
        d = await _get(mw, query=b"k=5")
        return a, b, d
    a, b, d = asyncio.run(go())
    assert c["n"] == 2 and a["body"] == b["body"] == b'{"n":1}' and d["body"] == b'{"n":2}', "同键只算一次;换了查询参数是另一个键"
    assert "x-cache" not in a["headers"] and b["headers"]["x-cache"] == "HIT" and "age" in b["headers"] and b["headers"]["content-length"] == "7"


def test_expired_value_is_served_at_once_and_replaced_behind_the_request(monkeypatch):
    pc.reset()
    clock = {"t": 1000.0}
    monkeypatch.setattr(pc.time, "time", lambda: clock["t"])
    c = {"n": 0}

    async def go():
        slow = asyncio.Event()
        mw = pc.PublicCacheMiddleware(_app(c, slow=slow), enabled=True)
        assert (await _get(mw))["body"] == b'{"n":1}'
        clock["t"] += 61
        r = await asyncio.wait_for(_get(mw), timeout=0.3)
        assert r["body"] == b'{"n":1}' and r["headers"]["x-cache"] == "STALE" and r["headers"]["age"] == "61", "没有等那次慢的重算"
        r2 = await asyncio.wait_for(_get(mw), timeout=0.3)
        await asyncio.sleep(0.01)
        assert r2["headers"]["x-cache"] == "STALE" and c["n"] == 2, "刷新在飞时不再起第二次"
        slow.set()
        await asyncio.sleep(0.02)
        r3 = await _get(mw)
        assert r3["body"] == b'{"n":2}' and r3["headers"]["x-cache"] == "HIT" and pc.stats()["refresh"] == 1
        clock["t"] += 60 * 12 + 1                                    # 超过可容忍的旧值年龄:不给旧的,现算
        r4 = await _get(mw)
        assert r4["body"] == b'{"n":3}' and "x-cache" not in r4["headers"]
    asyncio.run(go())


def test_what_must_never_be_cached_is_not():
    cases = [
        (dict(cache_control=None), {}, "没声明可缓存"),
        (dict(cache_control="private, max-age=60"), {}, "private"),
        (dict(cache_control="public, max-age=0"), {}, "max-age=0"),
        (dict(status=500), {}, "出错的响应"),
        (dict(extra=((b"set-cookie", b"a=1"),)), {}, "带 set-cookie"),
        (dict(), dict(headers=((b"authorization", b"Bearer x"),)), "带凭据的请求"),
        (dict(), dict(headers=((b"x-api-key", b"k"),)), "带 API key 的请求"),
        (dict(), dict(path="/api/v1/trading/positions"), "交易前缀"),
        (dict(), dict(path="/internal/executor/plan"), "内部路径"),
        (dict(), dict(method="POST"), "不是 GET"),
    ]
    for app_kw, req_kw, why in cases:
        pc.reset()
        c = {"n": 0}
        mw = pc.PublicCacheMiddleware(_app(c, **app_kw), enabled=True)

        async def go():
            await _get(mw, **req_kw)
            return await _get(mw, **req_kw)
        r = asyncio.run(go())
        assert c["n"] == 2 and "x-cache" not in r["headers"], why


def test_no_cache_request_gets_a_fresh_value_and_refreshes_the_entry():
    pc.reset()
    c = {"n": 0}
    mw = pc.PublicCacheMiddleware(_app(c), enabled=True)

    async def go():
        await _get(mw)
        a = await _get(mw, headers=((b"cache-control", b"no-cache"),))
        b = await _get(mw)
        return a, b
    a, b = asyncio.run(go())
    assert a["body"] == b'{"n":2}' and "x-cache" not in a["headers"] and b["body"] == b'{"n":2}' and b["headers"]["x-cache"] == "HIT"


def test_concurrent_cold_requests_compute_once():
    pc.reset()
    c = {"n": 0}

    async def app(scope, receive, send):
        c["n"] += 1
        await asyncio.sleep(0.02)
        await send({"type": "http.response.start", "status": 200, "headers": [(b"cache-control", b"public, max-age=60")]})
        await send({"type": "http.response.body", "body": b"x", "more_body": False})
    mw = pc.PublicCacheMiddleware(app, enabled=True)

    async def go():
        return await asyncio.gather(*[_get(mw) for _ in range(6)])
    out = asyncio.run(go())
    assert c["n"] == 1 and all(o["body"] == b"x" for o in out)


def test_total_size_is_bounded_and_the_switch_turns_it_off(monkeypatch):
    pc.reset()
    monkeypatch.setattr(pc, "MAX_TOTAL", 15)
    c = {"n": 0}
    mw = pc.PublicCacheMiddleware(_app(c), enabled=True)

    async def go():
        for i in range(5):
            await _get(mw, path=f"/api/v1/p{i}")
    asyncio.run(go())
    assert pc.stats()["bytes"] <= 15 and pc.stats()["entries"] == 2, "最旧的先被挤掉"
    pc.reset()
    off = pc.PublicCacheMiddleware(_app(c), enabled=False)

    async def go2():
        await _get(off)
        return await _get(off)
    assert "x-cache" not in asyncio.run(go2())["headers"] and pc.stats()["entries"] == 0
    monkeypatch.setenv("PUBLIC_CACHE", "0")
    assert pc.PublicCacheMiddleware(_app(c)).enabled is False
    monkeypatch.delenv("PUBLIC_CACHE")
    assert pc.PublicCacheMiddleware(_app(c)).enabled is True


def test_it_sits_directly_above_the_routes():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "src/api/main.py").read_text(encoding="utf-8")
    i, j = src.index("app.add_middleware(PublicCacheMiddleware)"), src.index("app.add_middleware(GZipMiddleware")
    assert i < j, "先加的在最里面:缓存要在 GZip / 限流 / CORS 的里面,存的是没压缩、没加跨域头的原始响应"
