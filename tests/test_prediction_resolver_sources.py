"""S-425 — 5 个预测来源里 4 个自 08 月中起一条结果都没写出来。

`_parse_dt('2026-07-15')` 返回 naive;`_resolve_alpha` 用它去减 `now(UTC)` → TypeError;
`resolve_all_predictions` 没有逐来源兜底,于是 `signal`(排第一、列是 timestamptz)写完后
整轮失败,positioning / forward_supply / conviction / narrative(列是 date)一条没有。
同时每轮都取「最老 500 行」重插,已解析的行 409(2 小时 326 次)。
"""
import asyncio
from datetime import datetime, timezone

import pytest

from src.data.signals import prediction_resolver as pr
from src.data.signals.outcome_tracker import _parse_dt


def test_date_only_parses_as_utc():
    d = _parse_dt("2026-07-15")
    assert d.tzinfo is not None
    assert (datetime.now(timezone.utc) - d).days > 0   # 旧版在这一行抛 TypeError


class _Resp:
    def __init__(self, status, data=None):
        self.status_code, self._d = status, data if data is not None else []

    def json(self):
        return self._d


class _Client:
    """按路径返回:prediction_outcomes 里已有 ref_id=40;来源表是 conviction 的真实形状。"""
    posts = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith("/prediction_outcomes"):
            return _Resp(200, [{"ref_id": "40"}] if params.get("offset") == "0" else [])
        if params.get("offset") != "0":
            return _Resp(200, [])
        return _Resp(200, [
            {"id": 21, "symbol": "FXI", "snapshot_date": "2026-07-15", "direction": "short"},
            {"id": 40, "symbol": "ADA", "snapshot_date": "2026-07-15", "direction": "long"},
            {"id": 1, "symbol": "NVDA", "snapshot_date": "2026-07-15", "direction": "long"},
        ])

    async def post(self, url, params=None, content=None, headers=None, timeout=None):
        _Client.posts.append((params, headers.get("Prefer"), content))
        return _Resp(201)


@pytest.fixture
def wired(monkeypatch):
    _Client.posts = []
    monkeypatch.setattr(pr.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(pr, "_SB_URL", "https://x.supabase.co")
    monkeypatch.setattr(pr, "_SB_KEY", "k")
    monkeypatch.setattr(pr, "refuse_write", lambda *_: None)

    async def alpha(client, sym, cls, dt, horizon, cache):
        # 真实调用链里这一步用 dt 算年龄 —— 旧版正是在这里对 naive dt 抛异常
        (datetime.now(timezone.utc) - dt).total_seconds()
        return 0.02, 0.0, 0.02, 1.0
    monkeypatch.setattr(pr, "_resolve_alpha", alpha)


def test_date_column_source_writes_and_skips_resolved(wired):
    res = asyncio.run(pr.resolve_source("conviction", dry_run=False))
    assert res["status"] == "ok", res
    assert res["already_resolved"] == 1
    assert res["examined"] == 2 and res["rows_written"] == 2        # 40 已解析,被跳过
    params, prefer, _ = _Client.posts[0]
    assert params == {"on_conflict": "source,ref_id,horizon_days"}
    assert "ignore-duplicates" in prefer


def test_one_source_failing_does_not_stop_the_rest(wired, monkeypatch):
    real = pr.resolve_source

    async def flaky(src, **k):
        if src == "positioning":
            raise TypeError("can't subtract offset-naive and offset-aware datetimes")
        return await real(src, **k)
    monkeypatch.setattr(pr, "resolve_source", flaky)
    out = asyncio.run(pr.resolve_all_predictions(dry_run=False))["sources"]
    assert out["positioning"]["status"] == "error" and "TypeError" in out["positioning"]["error"]
    assert out["conviction"]["status"] == "ok" and out["narrative"]["status"] == "ok"


def test_a_failed_read_is_an_error_not_zero_rows(wired, monkeypatch):
    async def bad_get(self, url, params=None, headers=None, timeout=None):
        return _Resp(503)
    monkeypatch.setattr(_Client, "get", bad_get)
    res = asyncio.run(pr.resolve_source("narrative", dry_run=False))
    assert res["status"] == "error" and "503" in res["error"]
