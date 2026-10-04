"""S-481:多空账本在 Redis 状态丢失时不许把 NAV 重置为 1.0 —— 先从表恢复,恢复不了就报错等人。"""
import asyncio
import inspect

import pytest

from src.data.signals import nav_persist as np_


class _Resp:
    def __init__(self, code, rows):
        self.status_code, self._rows = code, rows

    def json(self):
        return self._rows


def _client(code, rows):
    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp(code, rows)
    return C


@pytest.fixture
def sb(monkeypatch):
    import src.api.store as store
    monkeypatch.setattr(store, "_SB_URL", "http://x")
    monkeypatch.setattr(store, "_SB_KEY", "k")
    return monkeypatch


def _run(sb, code, rows):
    import httpx
    sb.setattr(httpx, "AsyncClient", _client(code, rows))
    return asyncio.run(np_.recover_book_state("scalable_book_nav"))


def test_empty_table_is_a_genuine_inception(sb):
    assert _run(sb, 200, []) == (None, None)


def test_last_row_state_is_recovered_with_its_nav(sb):
    st = {"weights": {"BTC": 0.5, "ETH": -0.5}, "mark_prices": {"BTC": 1.0, "ETH": 2.0}, "last_rebal": "2026-10-01"}
    got, why = _run(sb, 200, [{"mark_date": "2026-10-03", "nav": 0.955, "state": st}])
    assert why is None and got["weights"] == st["weights"] and got["nav"] == 0.955 and got["last_mark"] == "2026-10-03"


def test_history_without_state_refuses_instead_of_resetting(sb):
    got, why = _run(sb, 200, [{"mark_date": "2026-10-03", "nav": 0.955, "state": None}])
    assert got is None and "不把 NAV 重置为 1.0" in why


def test_unreadable_table_refuses(sb):
    got, why = _run(sb, 500, [])
    assert got is None and why


@pytest.mark.parametrize("mod,table", [("causal_paper", "causal_paper_nav"),
                                       ("combined_book", "combined_book_nav"),
                                       ("scalable_paper", "scalable_book_nav")])
def test_each_ls_book_recovers_before_inception_and_persists_state(mod, table):
    import importlib
    m = importlib.import_module(f"src.data.signals.{mod}")
    src = inspect.getsource(m)
    i_rec = src.index(f'recover_book_state("{table}")')
    i_inc = src.index('"nav": 1.0, "weights": w')
    assert i_rec < i_inc
    assert '"state": _state_json(state)' in src and src.count("source=source, state=state)") == 2
    st = m._state_json({"weights": {"BTC": 0.1}, "mark_prices": {"BTC": 60000.0}, "last_rebal": "2026-10-01",
                        "inception": "2026-07-13", "last_mark": "2026-10-03", "nav": 1.2})
    assert st["weights"] == {"BTC": 0.1} and "nav" not in st


def test_registry_builds_ls_navs_from_returns():
    from src.data.accounting.registry import BOOKS
    by_id = {b.id: b for b in BOOKS}
    assert all(by_id[k].nav_from_returns for k in ("causal_paper", "scalable_book", "combined_book"))
    assert not by_id["beta_core"].nav_from_returns
