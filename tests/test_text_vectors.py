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
    r = asyncio.run(tv.run_once())
    assert r["refused"] and r["written"] == tv.BATCH and "401" in r["why"] and len(written) == tv.BATCH
    assert written[0]["embedding"] == "[0.1,0.2]" and written[0]["dim"] == 2 and written[0]["model"] == tv.MODEL


def test_wiring():
    assert "async def _text_vectors_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert '"/internal/text-knn"' in (ROOT / "src/api/routers/admin.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-05_text_vectors.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in tv.WRITES_COLUMNS[tv.TABLE]) and tv.TODO_VIEW in mig and tv.NEAREST_RPC in mig
