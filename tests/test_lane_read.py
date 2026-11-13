"""研究数据只读入口(11-13):没有 token 进不来;名单外的对象读不到;每次读留一行;只有 GET / HEAD。"""
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import lane_read as lr

TOK_A, TOK_B = "a" * 32, "b" * 32


def test_readers_need_a_name_and_a_long_token():
    t = lr.readers(f"lane-a:{TOK_A}, lane-b:{TOK_B},:{'c' * 32},lane-x:short,")
    assert t == {TOK_A: "lane-a", TOK_B: "lane-b"}
    assert lr.readers("") == {} and lr.who(TOK_A, None, {}) is None, "没配 token ⇒ 谁都不是读者"
    assert lr.who(TOK_A, None, t) == "lane-a" and lr.who(None, f"Bearer {TOK_B}", t) == "lane-b"
    assert lr.who("wrong" * 8, "Bearer nope", t) is None and lr.who(None, None, t) is None


def test_rows_come_from_content_range_and_are_never_guessed():
    assert lr.rows_of(200, "0-999/*", b"") == 1000 and lr.rows_of(200, "*/0", b"") == 0
    assert lr.rows_of(200, None, b"[]") is None and lr.rows_of(403, "0-9/*", b"") is None


def test_the_allowlist_is_research_data_only():
    assert "ohlcv_daily" in lr.ALLOW and "feature_matrix_daily" in lr.ALLOW
    for private in ("live_account_daily", "portfolio_targets_daily", "regime_calls", "data_access_log", "webhook_subscriptions", "cis_scores"):
        assert private not in lr.ALLOW, private


def _client(monkeypatch, logged, calls):
    monkeypatch.setenv(lr.ENV, f"lane-a:{TOK_A}")

    async def up(obj, query, headers, method):
        calls.append((obj, query, headers, method))
        return 200, b'[{"x":1}]', {"content-range": "0-0/*", "content-type": "application/json"}

    async def log(row):
        logged.append(row)
    monkeypatch.setattr(lr, "_upstream", up)
    monkeypatch.setattr(lr, "_log", log)
    app = FastAPI()
    app.include_router(lr.router)
    return TestClient(app)


def test_no_token_no_read_and_every_read_leaves_a_row(monkeypatch):
    logged, calls = [], []
    c = _client(monkeypatch, logged, calls)
    assert c.get("/lane/rest/v1/ohlcv_daily").status_code == 401
    assert c.get("/lane/rest/v1/ohlcv_daily", headers={"apikey": "x" * 40}).status_code == 401 and not calls, "错的 token 连上游都不碰"
    r = c.get("/lane/rest/v1/ohlcv_daily?select=symbol,close&source=eq.binance_hist&order=trade_date.asc&limit=1",
              headers={"apikey": TOK_A, "Range": "0-0", "X-Evil": "1"})
    assert r.status_code == 200 and r.json() == [{"x": 1}] and r.headers["content-range"] == "0-0/*"
    obj, query, headers, method = calls[0]
    assert obj == "ohlcv_daily" and ("source", "eq.binance_hist") in query and method == "GET"
    assert set(k.lower() for k in headers) <= set(lr.PASS_REQUEST_HEADERS), "只带名单上的请求头,读者的 token 不往上游传"
    assert logged[-1]["reader"] == "lane-a" and logged[-1]["obj"] == "ohlcv_daily" and logged[-1]["n_rows"] == 1 and "eq.binance_hist" in logged[-1]["query"]
    assert TOK_A not in str(logged), "日志里没有 token"


def test_objects_off_the_list_and_writes_are_refused(monkeypatch):
    logged, calls = [], []
    c = _client(monkeypatch, logged, calls)
    assert c.get("/lane/rest/v1/live_account_daily", headers={"Authorization": f"Bearer {TOK_A}"}).status_code == 403 and not calls
    assert logged and logged[-1]["status"] == 403 and logged[-1]["obj"] == "live_account_daily", "被拒的尝试也留痕"
    for verb in (c.post, c.patch, c.delete, c.put):
        assert verb("/lane/rest/v1/ohlcv_daily", headers={"apikey": TOK_A}).status_code == 405
    assert asyncio.run(lr._log({"reader": "t"})) is None
