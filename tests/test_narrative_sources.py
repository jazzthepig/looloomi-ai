"""外部叙事源探针(Sharpe / Santiment):形状摘要是纯函数,探针失败要原样记下,key 永远不进输出。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import narrative_sources as ns  # noqa: E402


def test_shape_summarises_without_dumping():
    s = ns.shape({"data": {"narratives": [{"id": "defi", "name": "x" * 100}, {"id": "ai"}]}, "meta": {"n": 3}}, depth=4)
    assert s["data"]["narratives"]["_len"] == 2
    assert s["data"]["narratives"]["_first"]["name"] == "x" * 40
    assert ns.ts_range([[1, 2], [3, 4]]) == {"n": 2, "first": 1, "last": 3}
    assert ns.ts_range([{"datetime": "a"}, {"datetime": "b"}])["last"] == "b"
    assert ns.ts_range([]) == {"n": 0}


def test_probe_records_failures_and_never_the_key(monkeypatch):
    from src.data.market import data_layer as dl
    monkeypatch.setenv("SHARPE_AI_KEY", "sk_live_SENTINEL")
    monkeypatch.setenv("SANTIMENT_KEY", "SANTIMENT_SENTINEL")

    async def sharpe(path, params=None):
        if "narratives" in path:
            return {"data": {"narratives": [{"id": "defi"}]}}
        raise RuntimeError("Sharpe mindshare/data HTTP 403: plan")

    async def santi(query, variables=None):
        if "getAccessRestrictions" in query:
            return {"getAccessRestrictions": [{"name": "social_volume_total", "isRestricted": True}]}
        if "getMetric" in query:
            return {"getMetric": {"timeseriesData": [{"datetime": "2024-01-01", "value": 1}]}}
        return {"allProjects": [{"slug": "bitcoin", "ticker": "BTC"}]}

    monkeypatch.setattr(dl, "get_sharpe_v1", sharpe)
    monkeypatch.setattr(dl, "get_santiment_gql", santi)
    p = asyncio.run(ns.probe())
    assert p["sharpe_narratives"]["ok"] and p["sharpe_narratives"]["ids"] == ["defi"]
    assert not p["sharpe_mindshare_tokens"]["ok"] and "403" in p["sharpe_mindshare_tokens"]["error"]
    assert p["santiment_restrictions"]["social"][0]["name"] == "social_volume_total"
    assert p["santiment_btc_social_volume"]["n"] == 1
    blob = json.dumps(p)
    assert "SENTINEL" not in blob
    assert ns.verdict(p)[0] == "ok"
    assert ns.verdict({"a": {"ok": False, "error": "x"}})[0] == "error"


def test_fetchers_refuse_without_keys(monkeypatch):
    from src.data.market import data_layer as dl
    monkeypatch.delenv("SHARPE_AI_KEY", raising=False)
    monkeypatch.delenv("SANTIMENT_KEY", raising=False)
    for coro in (dl.get_sharpe_v1("narratives/data"), dl.get_santiment_gql("{ x }")):
        try:
            asyncio.run(coro)
            raise AssertionError("没有 key 必须报错")
        except RuntimeError as e:
            assert "不在进程环境里" in str(e)


def test_probe_is_retired_from_the_schedule():
    """10-20 探针完成了它的事(形状写进了 loop_attempt);每天再探一次只烧 Santiment 的月配额 —— 由入库循环取代。"""
    src = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    assert "_narrative_probe_loop()" not in src
    assert "_asyncio.create_task(_social_ingest_loop())" in src
