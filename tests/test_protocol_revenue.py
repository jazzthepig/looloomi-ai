"""协议收入 / 持币人收入快照(S-661 前向):子协议并到母协议、价值捕获比、半挂接口不写、简报接上 HL 币名。"""
import asyncio

import pytest

from src.data.execution import battlefield_brief as bb
from src.data.market import protocol_revenue as pr

REV = [{"slug": "uniswap-v3", "parentProtocol": "parent#uniswap", "total24h": 100, "total30d": 3000, "total60dto30d": 2000},
       {"slug": "uniswap-v4", "parentProtocol": "parent#uniswap", "total24h": 50, "total30d": 1000, "total60dto30d": 0},
       {"slug": "hyperliquid", "name": "Hyperliquid", "total24h": 10, "total30d": 300, "total60dto30d": 300}]
HOLD = [{"slug": "uniswap-v3", "parentProtocol": "parent#uniswap", "total24h": 0, "total30d": 1000, "total60dto30d": 0},
        {"slug": "hyperliquid", "total24h": 10, "total30d": 290, "total60dto30d": 280}]
GECKO = {"uniswap": "uniswap", "hyperliquid": "hyperliquid"}


def test_children_fold_into_the_parent_and_value_capture_uses_both_30_day_windows():
    rows = pr.aggregate(REV, HOLD, GECKO, "2026-10-21")
    by = {r["slug"]: r for r in rows}
    assert by["uniswap"]["revenue_30d"] == 4000 and by["uniswap"]["revenue_60to30d"] == 2000
    assert by["uniswap"]["holders_30d"] == 1000 and by["uniswap"]["gecko_id"] == "uniswap"
    vc = pr.value_capture(rows)
    assert vc["uniswap"]["value_capture"] == pytest.approx(1000 / 6000)
    assert vc["hyperliquid"]["value_capture"] == pytest.approx(570 / 600)


def test_no_revenue_means_no_ratio_not_zero():
    rows = pr.aggregate([{"slug": "x", "total30d": 0, "total60dto30d": 0}], [], {"x": "x-token"}, "2026-10-21")
    assert pr.value_capture(rows)["x-token"]["value_capture"] is None


def test_a_half_answered_overview_is_refused_not_written(monkeypatch):
    class R:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return R({"protocols": REV})

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", C)
    out = asyncio.run(pr.run_once())
    assert out["status"] == "refused" and "不写" in out["reason"]


def test_brief_attaches_value_capture_by_hl_name():
    rows = [{"coin": "HYPE"}, {"coin": "kPEPE"}, {"coin": "UNI"}]
    n = bb.attach_value(rows, {"HYPE": "hyperliquid", "PEPE": "pepe", "UNI": "uniswap"},
                        {"hyperliquid": {"value_capture": 0.95, "holders_rev_30d": 290.0},
                         "uniswap": {"value_capture": None, "holders_rev_30d": 0.0}})
    assert n == 1 and rows[0]["value_capture"] == 0.95 and rows[1]["gecko_id"] == "pepe"
    assert rows[1]["value_capture"] is None and rows[2]["value_capture"] is None
