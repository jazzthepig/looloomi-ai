"""T-024 — 每日快照不得写 T1(那是 Mac 引擎的序列)。

实测 2026-09-27:cis_scores 里 source='railway_snapshot' 且 data_tier='T1' 的行自 06-19 起 15,661 行,
confidence / asset_class 与引擎行不同、DQS 为空;每次部署重启都写一轮。lane-a 找了 4 天的「第二个 T1 写入端」就是它。
"""
import asyncio

from src.api.routers import cis


def _run(monkeypatch, universe, fresh_t1=frozenset()):
    written = {}

    async def fake_universe(force_source=None):
        return {"universe": universe, "macro_regime": "TIGHTENING"}

    async def fake_fresh(max_age_minutes=1440):
        return set(fresh_t1)

    async def fake_insert(rows):
        written["rows"] = rows
        return True

    monkeypatch.setattr(cis, "get_cis_universe", fake_universe)
    import src.api.store as store
    monkeypatch.setattr(store, "supabase_fresh_t1_symbols", fake_fresh)
    monkeypatch.setattr(store, "supabase_insert_batch", fake_insert)
    if hasattr(cis, "supabase_insert_batch"):                 # 模块级导入的那个名字
        monkeypatch.setattr(cis, "supabase_insert_batch", fake_insert)
    res = asyncio.run(cis.snapshot_full_universe_to_supabase())
    return res, written.get("rows", [])


def test_t1_assets_are_left_to_the_engine(monkeypatch):
    uni = [{"symbol": "BTC", "cis_score": 70, "data_tier": 1, "confidence": 0.83},
           {"symbol": "ETH", "cis_score": 65, "data_tier_label": "T1"},
           {"symbol": "SPY", "cis_score": 55, "data_tier": 2}]
    res, rows = _run(monkeypatch, uni)
    assert [r["symbol"] for r in rows] == ["SPY"]
    assert all(r["data_tier"] == "T2" for r in rows)
    assert res["t1"] == 0 and res["t1_left_to_engine"] == 2


def test_t2_shadow_suppression_still_applies(monkeypatch):
    uni = [{"symbol": "SOL", "cis_score": 60, "data_tier": 2}]
    res, rows = _run(monkeypatch, uni, fresh_t1={"SOL"})
    assert rows == [] and res.get("shadow_suppressed") == 1 or res.get("reason") == "no_valid_rows"
