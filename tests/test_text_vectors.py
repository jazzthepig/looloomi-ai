"""VDB 文字空间(11-05,MiniMax 嵌入):文字拼接、两种回包形状、错误不写半截、接线。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.vector import text_vectors as tv  # noqa: E402


def test_text_for_joins_kind_title_body_and_drops_untitled():
    assert tv.text_for({"title": "  Binance  lists FOO ", "kind": "listing"}) == "[listing] Binance lists FOO"
    assert tv.text_for({"title": "BTC ETF inflows", "body": "x" * 1000}).startswith("BTC ETF inflows — xxx")
    assert len(tv.text_for({"title": "t" * 900})) == tv.TEXT_MAX and tv.text_for({"title": ""}) is None


def test_parse_vectors_accepts_minimax_and_openai_shapes_and_rejects_bad_ones():
    v, e = tv.parse_vectors({"vectors": [[0.1, 0.2], [0.3, 0.4]], "base_resp": {"status_code": 0}}, 2)
    assert e is None and v == [[0.1, 0.2], [0.3, 0.4]]
    v, e = tv.parse_vectors({"data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]}, 2)
    assert v == [[1.0], [2.0]]
    assert tv.parse_vectors({"base_resp": {"status_code": 1004, "status_msg": "auth"}}, 1)[1].startswith("base_resp 1004")
    assert "条数" in tv.parse_vectors({"vectors": [[1.0]]}, 2)[1]
    assert tv.parse_vectors({"vectors": [[1.0, float("nan")]]}, 1)[1] == "向量里有非数"
    assert tv.parse_vectors({"vectors": [[1.0], [1.0, 2.0]]}, 2)[1] == "同一批向量维数不一"
    assert tv.vec_literal([0.5, -1.0]) == "[0.5,-1]"


def test_run_once_refuses_without_partial_writes(monkeypatch):
    written = []

    async def read_all(table, params):
        return [{"source": "events", "item_id": f"e{i}", "title": f"t{i}", "kind": "news"} for i in range(tv.BATCH + 3)]

    calls = {"n": 0}

    async def embed(texts, kind="db"):
        calls["n"] += 1
        return ([[0.1, 0.2]] * len(texts), None) if calls["n"] == 1 else (None, "HTTP 401: bad key")

    class W:
        def __bool__(self):
            return True

    async def upsert(table, rows, on_conflict=None):
        written.extend(rows)
        return W()

    import src.api.store as store
    import src.data.style.header as header
    monkeypatch.setattr(header, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    monkeypatch.setattr(tv, "embed", embed)
    monkeypatch.setattr(tv, "PAUSE_S", 0)
    r = asyncio.run(tv.run_once())
    assert r["refused"] and r["written"] == tv.BATCH and "401" in r["why"] and len(written) == tv.BATCH
    assert written[0]["embedding"] == "[0.1,0.2]" and written[0]["dim"] == 2 and written[0]["model"] == tv.MODEL


def test_wiring():
    assert "async def _text_vectors_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert '"/internal/text-knn"' in (ROOT / "src/api/routers/admin.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-05_text_vectors.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in tv.WRITES_COLUMNS[tv.TABLE]) and tv.TODO_VIEW in mig and tv.NEAREST_RPC in mig


def test_embed_retries_on_rate_limit_then_gives_up(monkeypatch):
    calls = []

    async def once(texts, kind="db"):
        calls.append(kind)
        return (None, "base_resp 1002: rate limit exceeded(RPM)") if len(calls) < 3 else ([[1.0]], None)

    from src.data.narrative import llm_narrator as llm
    monkeypatch.setattr(llm, "_FB_KEY", "")
    monkeypatch.setattr(tv, "_embed_once", once)
    v, e = asyncio.run(tv.embed(["a"], waits=(0, 0)))
    assert e is None and v == [[1.0]] and len(calls) == 3
    calls.clear()
    monkeypatch.setattr(tv, "_embed_once", lambda texts, kind="db": _err())
    v, e = asyncio.run(tv.embed(["a"], waits=(0,)))
    assert v is None and tv.rate_limited(e) and not tv.rate_limited("HTTP 401: bad key")


async def _err():
    return None, "base_resp 1002: rate limit exceeded(RPM)"


def test_rate_limit_backs_off_for_the_whole_quota_window(monkeypatch):
    async def read_all(table, params):
        return [{"source": "events", "item_id": "e1", "title": "t", "kind": "news"}]

    async def embed(texts, kind="db"):
        return None, "base_resp 1002: rate limit exceeded(RPM)"

    import src.data.style.header as header
    monkeypatch.setattr(header, "_read_all", read_all)
    monkeypatch.setattr(tv, "embed", embed)
    monkeypatch.setitem(tv._COOLDOWN_UNTIL, "t", 0.0)
    assert asyncio.run(tv.run_once())["refused"]
    r = asyncio.run(tv.run_once())
    assert r["status"] == "skipped" and "额度" in r["why"], "撞到 1002 后整个窗口不再调(额度与 lane 共用)"


def test_fallback_key_is_used_on_quota_hit(monkeypatch):
    from src.data.narrative import llm_narrator as llm
    calls = []

    async def once(texts, kind="db", fallback=False):
        calls.append(fallback)
        return ([[1.0]], None) if fallback else (None, "base_resp 1002: rate limit exceeded(RPM)")

    monkeypatch.setattr(llm, "_FB_KEY", "x")
    monkeypatch.setattr(tv, "_embed_once", once)
    v, e = asyncio.run(tv.embed(["a"], waits=(0,)))
    assert v == [[1.0]] and calls == [False, True]
    assert llm.quota_hit(429, None) and llm.quota_hit(200, {"base_resp": {"status_code": 1002}})
    assert llm.quota_hit(200, {"base_resp": {"status_code": 1008}}) and not llm.quota_hit(200, {"base_resp": {"status_code": 0}})
    assert not llm.quota_hit(401, None)
