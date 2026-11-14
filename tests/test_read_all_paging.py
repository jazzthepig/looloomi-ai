"""`_read_all` 的每页行数跟着服务端的上限走(T-379 / S-860);上限比以为的低时不许静默截断。"""
import asyncio

from src.data.style import header as hd


class _RD:
    def __init__(self, rows=None, reason=None):
        self.rows, self.reason, self.ok = rows, reason, rows is not None


def _server(n_rows, cap, calls, fail_at=None):
    """像 PostgREST:按 offset / limit 给行,每次最多 cap 行。"""
    data = [{"id": i} for i in range(n_rows)]

    async def sb_get(table, params):
        calls.append((table, int(params["limit"]), int(params.get("offset", 0))))
        if fail_at is not None and int(params.get("offset", 0)) == fail_at:
            return _RD(None, "boom")
        lim, off = min(int(params["limit"]), cap), int(params.get("offset", 0))
        if table == hd.PAGE_PROBE_TABLE and params.get("select") == "id" and "offset" not in params:
            return _RD([{"id": i} for i in range(min(lim, 50_000))])
        return _RD(data[off:off + lim])
    return sb_get


def _setup(monkeypatch, sb_get, cap=None, env=True):
    import src.data.vector.market_state_writer as msw
    monkeypatch.setattr(msw, "_sb_get", sb_get)
    monkeypatch.setattr(hd, "_PAGE", {"cap": cap, "tried_at": 0.0})
    if env:
        monkeypatch.setenv("SUPABASE_URL", "http://x")
    else:
        monkeypatch.delenv("SUPABASE_URL", raising=False)


def test_pages_follow_the_server_cap(monkeypatch):
    calls = []
    _setup(monkeypatch, _server(25_000, 10_000, calls))
    rows = asyncio.run(hd._read_all("t", {"select": "id"}))
    assert [r["id"] for r in rows] == list(range(25_000))
    reads = [c for c in calls if c[0] == "t"]
    assert reads == [("t", 10_000, 0), ("t", 10_000, 10_000), ("t", 10_000, 20_000), ("t", 1, 25_000)], "三页 + 一次「还有没有」"
    assert hd._PAGE["cap"] == 10_000 and sum(1 for c in calls if c[0] == hd.PAGE_PROBE_TABLE) == 1


def test_a_cap_lower_than_believed_does_not_truncate(monkeypatch):
    """代码以为每页 10,000,服务端其实只给 1,000(Max rows 被调回去了)。旧的「不足一页就算读完」会在第一页停下。"""
    calls = []
    _setup(monkeypatch, _server(4_321, 1_000, calls), cap=10_000)
    rows = asyncio.run(hd._read_all("t", {"select": "id"}))
    assert [r["id"] for r in rows] == list(range(4_321)), "一行不少、一行不重"
    assert hd._PAGE["cap"] == 1_000, "发现之后按实际的上限接着读,并记住"
    assert calls[0] == ("t", 10_000, 0) and calls[1] == ("t", 1, 1_000) and calls[2] == ("t", 1_000, 1_000)


def test_without_a_database_or_a_probe_it_behaves_as_before(monkeypatch):
    calls = []
    _setup(monkeypatch, _server(2_500, 10_000, calls), env=False)
    rows = asyncio.run(hd._read_all("t", {"select": "id"}))
    assert len(rows) == 2_500 and [c[1] for c in calls] == [1_000, 1_000, 1_000] and not any(c[0] == hd.PAGE_PROBE_TABLE for c in calls)

    async def broken(table, params):
        if table == hd.PAGE_PROBE_TABLE and "offset" not in params:
            raise RuntimeError("probe down")
        return _RD([{"id": 1}] if int(params.get("offset", 0)) == 0 else [])
    _setup(monkeypatch, broken)
    assert asyncio.run(hd._read_all("t", {"select": "id"})) == [{"id": 1}] and hd._PAGE["cap"] is None, "探不到 ⇒ 每页 1,000,不记"


def test_small_reads_cost_one_request_and_a_failed_read_still_raises(monkeypatch):
    import pytest
    calls = []
    _setup(monkeypatch, _server(300, 10_000, calls), cap=10_000)
    assert len(asyncio.run(hd._read_all("t", {"select": "id"}))) == 300 and calls == [("t", 10_000, 0)], "小表不多花一次请求"
    calls.clear()
    _setup(monkeypatch, _server(25_000, 10_000, calls, fail_at=10_000), cap=10_000)
    with pytest.raises(RuntimeError, match="读不到"):
        asyncio.run(hd._read_all("t", {"select": "id"}))
    calls.clear()
    _setup(monkeypatch, _server(15_000, 10_000, calls, fail_at=15_000), cap=10_000)
    with pytest.raises(RuntimeError, match="核对是否读完"):
        asyncio.run(hd._read_all("t", {"select": "id"}))
