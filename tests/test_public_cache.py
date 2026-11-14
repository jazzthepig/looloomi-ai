"""`src/api/public_cache.py`:源站兑现接口自己声明的可缓存;先给旧的、后台换新;带凭据 / 没声明 / 出错的一律不存。"""
import asyncio

import pytest

from src.api import public_cache as pc


@pytest.fixture(autouse=True)
def _no_real_redis(monkeypatch):
    """这些测试不碰真 Redis:缺省把「重启后还是热的」那一半关掉;专门测它的用例自己接一个假的。"""
    monkeypatch.setenv("PUBLIC_CACHE_PERSIST", "0")


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
        (dict(cache_control="no-store"), {}, "no-store"),
        (dict(cache_control="no-cache"), {}, "no-cache"),
        (dict(cache_control="max-age=60"), {}, "给了 max-age 但没说 public"),
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



def test_undeclared_json_gets_a_short_default_and_non_json_does_not(monkeypatch):
    """上线后重量:104 个公开接口里 61 个没写任何缓存头,最慢的都在里面。缺省 30 秒新、旧值最多 5 分钟。"""
    pc.reset()
    clock = {"t": 0.0}
    monkeypatch.setattr(pc.time, "time", lambda: clock["t"])
    c = {"n": 0}
    mw = pc.PublicCacheMiddleware(_app(c, cache_control=None), enabled=True)

    async def go():
        await _get(mw)
        a = await _get(mw)
        clock["t"] = 31
        b = await _get(mw)
        await asyncio.sleep(0.01)
        clock["t"] = 31 + 601
        d = await _get(mw)
        return a, b, d
    a, b, d = asyncio.run(go())
    assert a["headers"]["x-cache"] == "HIT" and b["headers"]["x-cache"] == "STALE" and b["body"] == b'{"n":1}'
    assert "x-cache" not in d["headers"] and c["n"] == 3, "超过 10 分钟的旧值不给;中间那次后台刷新算一次"
    assert pc.storable(200, [(b"content-type", b"image/png")], b"x") is None, "不是 JSON 又没声明:不猜"
    assert pc.storable(200, [(b"content-type", b"application/json"), (b"cache-control", b"public, max-age=600")], b"x") == (600, 3600)
    assert pc.storable(200, [(b"content-type", b"application/json"), (b"cache-control", b"public, max-age=60")], b"x") == (60, 720)


def _fake_redis(monkeypatch, fail=False, hang=False):
    db, calls = {}, {"get": 0, "set": 0}

    async def rget(k):
        calls["get"] += 1
        if hang:
            await asyncio.sleep(5)
        if fail:
            raise RuntimeError("redis down")
        return db.get(k)

    async def rset(k, data, ttl):
        calls["set"] += 1
        db[k] = {**data, "_ttl": ttl}
        return True
    monkeypatch.setenv("PUBLIC_CACHE_PERSIST", "1")
    monkeypatch.setattr(pc, "PERSIST_MIN_COST_S", 0.0)                 # 测试里的假路由是瞬时的;「只存算得慢的」另有用例
    monkeypatch.setattr(pc, "_redis_get", rget)
    monkeypatch.setattr(pc, "_redis_set", rset)
    return db, calls


def test_a_restarted_process_serves_what_the_previous_one_stored(monkeypatch):
    """11-14:每次部署进程重启、内存缓存清零,之后几分钟人人等现算。内存里没有的键先问 Redis。"""
    pc.reset()
    clock = {"t": 1000.0}
    monkeypatch.setattr(pc.time, "time", lambda: clock["t"])
    db, calls = _fake_redis(monkeypatch)
    c = {"n": 0}

    async def go():
        mw = pc.PublicCacheMiddleware(_app(c), enabled=True)
        await _get(mw)
        await asyncio.sleep(0.01)
        assert calls["set"] == 1 and len(db) == 1 and list(db.values())[0]["_ttl"] == 1800 and list(db.values())[0]["k"] == "/api/v1/x?"
        pc.reset()                                                 # ← 进程重启:内存清空,Redis 还在
        clock["t"] += 30
        mw2 = pc.PublicCacheMiddleware(_app(c), enabled=True)
        r = await _get(mw2)
        assert c["n"] == 1 and r["body"] == b'{"n":1}' and r["headers"]["x-cache"] == "HIT" and r["headers"]["age"] == "30", "没有重新算"
        pc.reset()
        clock["t"] += 60                                           # 再重启一次,这回已过 max-age:先给旧的,后台换新
        mw3 = pc.PublicCacheMiddleware(_app(c), enabled=True)
        r2 = await _get(mw3)
        await asyncio.sleep(0.02)
        assert r2["headers"]["x-cache"] == "STALE" and r2["body"] == b'{"n":1}' and c["n"] == 2 and pc.stats()["restored"] == 1
        pc.reset()
        clock["t"] += 1201                                         # 上一个进程存的最多认 20 分钟
        mw4 = pc.PublicCacheMiddleware(_app(c), enabled=True)
        r3 = await _get(mw4)
        assert "x-cache" not in r3["headers"] and c["n"] == 3
    asyncio.run(go())


def test_redis_down_or_slow_means_compute_as_before_and_ask_once(monkeypatch):
    for kw in (dict(fail=True), dict(hang=True)):
        pc.reset()
        monkeypatch.setattr(pc, "RESTORE_TIMEOUT_S", 0.05)
        db, calls = _fake_redis(monkeypatch, **kw)
        c = {"n": 0}
        mw = pc.PublicCacheMiddleware(_app(c, cache_control="no-store"), enabled=True)

        async def go():
            a = await asyncio.wait_for(_get(mw), timeout=1.0)
            b = await asyncio.wait_for(_get(mw), timeout=1.0)
            return a, b
        a, b = asyncio.run(go())
        assert a["status"] == 200 and c["n"] == 2 and calls["get"] == 1, "问不到就现算;同一个键 60 秒内只问一次"
        assert pc.stats()["restore_failed"] == 1


def test_only_small_text_bodies_are_persisted_and_a_wrong_key_is_ignored(monkeypatch):
    pc.reset()
    db, calls = _fake_redis(monkeypatch)
    monkeypatch.setattr(pc, "PERSIST_MAX_BODY", 5)

    async def go():
        c = {"n": 0}
        await _get(pc.PublicCacheMiddleware(_app(c), enabled=True))          # 体 7 字节 > 5:不落 Redis
        await asyncio.sleep(0.01)
        assert calls["set"] == 0 and pc.stats()["stored"] == 1
        db[pc._rkey("/api/v1/y?")] = {"k": "/api/v1/OTHER?", "at": pc.time.time(), "max_age": 60, "stale_age": 720, "headers": [], "body": "{}"}
        r = await _get(pc.PublicCacheMiddleware(_app(c), enabled=True), path="/api/v1/y")
        assert "x-cache" not in r["headers"], "哈希撞了 / 键对不上的不认"
    asyncio.run(go())


def test_only_slow_responses_go_to_redis_and_at_most_once_per_ten_minutes(monkeypatch):
    """Redis 还担着 CIS 的推送桥和限流:缓存不能把它的额度吃掉。算得快的不存;同一个键 10 分钟最多写一次。"""
    pc.reset()
    clock = {"t": 0.0}
    monkeypatch.setattr(pc.time, "time", lambda: clock["t"])
    db, calls = _fake_redis(monkeypatch)
    monkeypatch.setattr(pc, "PERSIST_MIN_COST_S", 0.5)

    async def go():
        c = {"n": 0}
        mw = pc.PublicCacheMiddleware(_app(c), enabled=True)
        await _get(mw)
        await asyncio.sleep(0.01)
        assert calls["set"] == 0, "瞬时算完的不落 Redis"
        for now, cost, want in ((0.0, 0.9, 1), (100.0, 0.9, 1), (599.0, 0.9, 1), (601.0, 0.9, 2), (700.0, 0.1, 2)):
            pc._store("/api/v1/slow?", 200, [(b"content-type", b"application/json")], b"{}", now, cost)
            await asyncio.sleep(0.01)
            assert calls["set"] == want, (now, cost, calls["set"])
    asyncio.run(go())


def test_random_query_strings_cannot_flood_redis(monkeypatch):
    pc.reset()
    db, calls = _fake_redis(monkeypatch)
    monkeypatch.setattr(pc, "RESTORE_PER_MINUTE", 5)
    c = {"n": 0}
    mw = pc.PublicCacheMiddleware(_app(c, cache_control="no-store"), enabled=True)

    async def go():
        for i in range(40):
            await _get(mw, query=f"_={i}".encode())
    asyncio.run(go())
    assert calls["get"] == 5 and c["n"] == 40, "超过每分钟的额度就不再问 Redis,请求照常现算"


def test_warm_loop_requests_what_the_dashboard_requests_within_the_stale_bound():
    """访客少 ⇒ 两次访问之间缓存会过期。预热循环按面板实际发出的请求逐条保温;它的间隔必须短于缺省的旧值上限。"""
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parents[1] / "src/api/main.py").read_text(encoding="utf-8")
    block = src[src.index("_WARM_PATHS = ("):src.index("async def _public_cache_warm_loop")]
    paths = re.findall(r'"(/api/v1/[^"]+)"', block)
    assert len(paths) == len(set(paths)) >= 24 and {"/api/v1/cis/universe", "/api/v1/market/crowd-clock", "/api/v1/intelligence/macro-events"} <= set(paths)
    assert all(pc.eligible(p.split("?")[0], {}) or p.startswith("/api/v1/trading/") for p in paths), "保温的路径要进得了缓存这一层"
    loop = src[src.index("async def _public_cache_warm_loop"):src.index("async def _start_public_cache_warm_loop")]
    m = re.search(r"_asyncio\.sleep\((\d+)\)\s*$", loop.strip().splitlines()[-1]) or re.search(r"await _asyncio\.sleep\((\d+)\)", loop[loop.rindex("await _asyncio.sleep("):])
    assert m and int(m.group(1)) < pc.DEFAULT_STALE_S, "循环间隔要短于缺省的旧值上限,否则保不住"

