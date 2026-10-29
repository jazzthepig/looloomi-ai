"""NAV 表「上一行」的读取(10-29):没有 `void_reason` 列的表不能因为那个过滤读不到。

实测:factor_tilt_nav / pod_aggregator_nav 没有 void_reason 列,默认过滤每次 400 → 读不到被当成起点
→ 46 天每行 NAV = 1 + 当天收益,从没复利。修法:无此列 ⇒ 去掉过滤再读(等价);仍读不到 ⇒ unreadable,
调用方拒绝,不当起点。
"""
import asyncio

import httpx

from src.data.signals import nav_persist


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text

    def json(self):
        return self._payload


def _fake_client(calls, table_has_void: bool, rows):
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None):
            calls.append(list(params or []))
            if not table_has_void and any(p[0] == "void_reason" for p in params or []):
                return _Resp(400, None, '{"code":"42703","message":"column x.void_reason does not exist"}')
            return _Resp(200, rows)
    return _C


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _setup(monkeypatch, calls, has_void, rows):
    import src.api.store as store
    monkeypatch.setattr(store, "_SB_URL", "https://example.invalid", raising=False)
    monkeypatch.setattr(store, "_SB_KEY", "k", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(calls, has_void, rows))


def test_table_without_void_column_still_reads_its_last_row(monkeypatch):
    calls = []
    _setup(monkeypatch, calls, False, [{"mark_date": "2026-10-28", "nav": 1.04}])
    nav, d, st = _run(nav_persist.nav_table_last_nav_status("factor_tilt_nav", before="2026-10-29"))
    assert (nav, d, st) == (1.04, "2026-10-28", "ok")
    assert len(calls) == 2 and not any(p[0] == "void_reason" for p in calls[1])
    assert _run(nav_persist.nav_table_has_any_rows("factor_tilt_nav")) is True


def test_empty_and_unreadable_are_different_states(monkeypatch):
    calls = []
    _setup(monkeypatch, calls, True, [])
    assert _run(nav_persist.nav_table_last_nav_status("t", before="2026-10-29"))[2] == "empty"

    class _Boom:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp(500, None, "upstream")
    monkeypatch.setattr(httpx, "AsyncClient", _Boom)
    assert _run(nav_persist.nav_table_last_nav_status("t", before="2026-10-29"))[2] == "unreadable"
    assert _run(nav_persist.nav_table_last_nav("t", before="2026-10-29")) == (None, None)


def test_inception_scoping_is_never_silently_dropped(monkeypatch):
    """只去掉 void_reason;inception_id 过滤缺列时是真的不匹配 —— 必须读不到,不能放宽。"""
    calls = []
    _setup(monkeypatch, calls, False, [{"mark_date": "2026-10-28", "nav": 1.0}])
    _run(nav_persist.nav_table_last_nav_status("t", before="2026-10-29", inception_id="v2"))
    assert all(any(p[0] == "inception_id" for p in c) for c in calls)


def test_both_books_refuse_instead_of_restarting_at_one():
    import inspect
    from src.data.signals import factor_tilt_paper, pod_aggregator_paper
    for mod in (factor_tilt_paper, pod_aggregator_paper):
        src = inspect.getsource(mod.mark_and_rebalance)
        assert "nav_table_last_nav_status" in src and '"unreadable"' in src, mod.__name__
    src = inspect.getsource(pod_aggregator_paper.mark_and_rebalance)
    assert "await _save_state(new_state)" in src, "pod 的 state 必须真的存"
