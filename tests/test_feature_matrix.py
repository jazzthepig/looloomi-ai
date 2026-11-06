"""融合特征矩阵(11-06):物化 + 每小时刷新;把表里早有却没并进来的风格 / 链上 / 持仓结构 / 渠道维度并进来。"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.state import feature_matrix as fm  # noqa: E402

TODAY = dt.date(2026, 11, 6)


def test_verdict():
    assert fm.verdict(2500, "2026-11-05", 54, TODAY)["ok"]
    assert not fm.verdict(None, "2026-11-05", 54, TODAY)["ok"]
    assert not fm.verdict(2500, None, None, TODAY)["ok"]
    assert not fm.verdict(2500, "2026-11-01", 54, TODAY)["ok"]


def test_migration_fuses_existing_dimensions_and_materializes():
    sql = (ROOT / "migrations/2026-11-06_feature_matrix_daily.sql").read_text(encoding="utf-8")
    for src in ("style_index_pit_daily", "chain_activity_daily", "deriv_metrics_daily", "channel_series_daily"):
        assert f"public.{src}" in sql, src
    for key in ("'style:", "'chain:fees_30v30'", "'pos:btc_smart_minus_crowd'", "'channel:'", "'venue:coinbase_share_spot30'",
                "'holders:breadth_4w'", "'supply:locked_share_median'", "'listings:new_coins_7d'", "'cat:share_up_24h'", "'stablechain:'"):
        assert key in sql, key
    assert "create materialized view if not exists public.feature_matrix_daily" in sql
    assert "refresh materialized view concurrently public.feature_matrix_daily" in sql
    assert "create unique index if not exists feature_matrix_daily_d_uq" in sql      # concurrently 需要唯一索引


def test_wiring():
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert "async def _feature_matrix_loop" in main
    assert fm.RPC in json.loads((ROOT / "src/api/schema_manifest.json").read_text(encoding="utf-8"))["rpc_functions"]


def test_refresh_gets_a_long_timeout_and_a_failed_call_says_so(monkeypatch):
    """11-06:刷新 9–12 s,共享客户端 10 s 放弃 ⇒ 「没返回行数」。现在给 60 s;调用失败要说是调用失败。"""
    import asyncio
    import datetime as dt

    import src.api.store as store
    import src.data.vector.market_state_writer as msw
    from src.data.state import feature_matrix as fm
    seen = {}

    class R:
        def __init__(self, ok, value=None, why=""):
            self.ok, self.value, self.why, self.rows, self.reason = ok, value, why, [{"d": "2026-11-05", "f": {"a": 1}}], ""

    async def rpc(fn, payload=None, *, timeout=None):
        seen["t"] = timeout
        return R(seen.get("fail") is None, 1990, "no response from Supabase after retries")

    async def get(t, p):
        return R(True)
    monkeypatch.setattr(store, "supabase_rpc_write", rpc)
    monkeypatch.setattr(msw, "_sb_get", get)
    now = dt.datetime(2026, 11, 6, 12, tzinfo=dt.timezone.utc)
    out = asyncio.run(fm.run_once(now))
    assert seen["t"] == fm.REFRESH_TIMEOUT_S >= 30 and out["ok"] and out["rows"] == 1990
    seen["fail"] = True
    out = asyncio.run(fm.run_once(now))
    assert out["ok"] is False and "调用失败" in out["why"]
