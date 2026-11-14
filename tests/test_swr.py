"""`src/api/swr.py`:有旧值先给旧值、后台换新;并发共用一次读;读坏了有界地给旧值。11-14 量到 `/cis/attribution` 每 10 分钟让一个访客等 12–19 秒。"""
import asyncio

import pytest

from src.api import swr


def _run(coro):
    return asyncio.run(coro)


def test_cold_concurrent_requests_share_one_load():
    swr.reset()
    calls = []

    async def loader():
        calls.append(1)
        await asyncio.sleep(0.02)
        return {"v": len(calls)}

    async def go():
        return await asyncio.gather(*[swr.swr("k", 60, loader) for _ in range(8)])
    out = _run(go())
    assert len(calls) == 1 and all(x == {"v": 1} for x in out), "8 个同时到的请求只读一次"


def test_stale_value_is_returned_at_once_and_refreshed_in_the_background(monkeypatch):
    swr.reset()
    clock = {"t": 1000.0}
    monkeypatch.setattr(swr.time, "time", lambda: clock["t"])
    n = {"i": 0}
    gate = asyncio.Event

    async def scenario():
        release = gate()

        async def loader():
            n["i"] += 1
            if n["i"] >= 2:
                await release.wait()                      # 第二次读很慢
            return n["i"]
        assert await swr.swr("k", 600, loader) == 1
        clock["t"] += 601                                   # 过期
        got = await asyncio.wait_for(swr.swr("k", 600, loader), timeout=0.2)
        assert got == 1 and swr.state("k")["refreshing"], "慢读在后台;这个请求没有等它"
        assert await asyncio.wait_for(swr.swr("k", 600, loader), timeout=0.2) == 1
        for _ in range(5):                                  # 让后台任务真的开始跑(3.12+ 的 wait_for 不一定让出事件循环 —— Mac 上 3.14 就没让)
            await asyncio.sleep(0)
        assert n["i"] == 2, "两次过期请求只起了一次刷新"
        release.set()
        await asyncio.sleep(0.01)
        assert await swr.swr("k", 600, loader) == 2 and not swr.state("k")["refreshing"]
    _run(scenario())


def test_failed_refresh_keeps_the_old_value_only_within_the_bound(monkeypatch):
    swr.reset()
    clock = {"t": 0.0}
    monkeypatch.setattr(swr.time, "time", lambda: clock["t"])
    ok = {"v": True}

    async def loader():
        if not ok["v"]:
            raise RuntimeError("db down")
        return "old"

    async def scenario():
        assert await swr.swr("k", 10, loader, max_stale_s=100) == "old"
        ok["v"] = False
        clock["t"] = 50
        assert await swr.swr("k", 10, loader, max_stale_s=100) == "old"
        await asyncio.sleep(0.01)
        assert "db down" in swr.state("k")["error"], "读坏了要看得见"
        clock["t"] = 200                                    # 旧值超过 100 秒:不再给
        with pytest.raises(RuntimeError, match="db down"):
            await swr.swr("k", 10, loader, max_stale_s=100)
    _run(scenario())


def test_no_value_and_a_failing_loader_raises_instead_of_returning_empty():
    swr.reset()

    async def loader():
        raise TimeoutError("unreadable")
    with pytest.raises(TimeoutError):
        _run(swr.swr("k", 10, loader))


def test_attribution_and_v2_routes_use_it():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "src/api/routers/cis.py").read_text(encoding="utf-8")
    assert '_swr("cis_attribution_rows", 600, _load_rows, max_stale_s=6 * 3600)' in src and '_swr("cis_v2_view", 120, latest_view, max_stale_s=3600)' in src
    assert "_ATTR_CACHE.get(" not in src, "旧的「过期就原地重读」不许留着"
