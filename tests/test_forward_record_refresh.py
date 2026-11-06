"""T-231(11-06):前向记录写端 —— refresh 给足超时、超时单独说、重算覆盖与新的一天分开记。

10-31 16:04 之后 `_forward_record_loop` 0 次 ok:函数 8.3 s 均值 / 29.4 s 最大,共享客户端 10 s 放弃并重试,
服务端其实写完了。SQL 侧扫描加了下界(migrations/2026-11-06_refresh_depth_divergence_bounded.sql)。
"""
import asyncio
from pathlib import Path

from src.data.signals import forward_record_keeper as frk

ROOT = Path(__file__).resolve().parents[1]


class _R:
    def __init__(self, ok, value=None, why=""):
        self.ok, self.value, self.why = ok, value, why


def _run(monkeypatch, r1, days):
    import src.api.store as store
    calls = []

    async def rpc(fn, payload=None, *, timeout=None):
        calls.append((fn, timeout))
        return r1 if fn == "refresh_depth_divergence" else _R(True, 3)
    seq = iter(days)

    async def latest():
        return next(seq)
    monkeypatch.setattr(store, "supabase_rpc_write", rpc)
    monkeypatch.setattr(frk, "_latest_logged_day", latest)
    return asyncio.run(frk.refresh_depth_divergence_log()), calls


def test_refresh_gets_a_long_timeout_and_a_new_day_is_not_a_recompute(monkeypatch):
    out, calls = _run(monkeypatch, _R(True, 210), ["2026-11-05", "2026-11-06"])
    assert ("refresh_depth_divergence", frk.REFRESH_TIMEOUT_S) in calls and frk.REFRESH_TIMEOUT_S > 30, "超时要长过 statement_timeout"
    assert out["problems"] == [] and out["written_day"] == "2026-11-06" and out["recomputed_days"] == []


def test_rewriting_an_existing_day_is_recorded_as_a_recompute(monkeypatch):
    out, _ = _run(monkeypatch, _R(True, 210), ["2026-11-05", "2026-11-05"])
    assert out["recomputed_days"] == ["2026-11-05"] and out["problems"] == []


def test_client_timeout_says_timeout_not_none(monkeypatch):
    out, _ = _run(monkeypatch, _R(False, None, "no response from Supabase after retries"), ["2026-11-05", "2026-11-05"])
    assert any("client timeout" in p for p in out["problems"]), out["problems"]
    assert not any("NoneType" in p for p in out["problems"]), "超时不再落到「返回 None 不是 int」的兜底"
    out2, _ = _run(monkeypatch, _R(True, None), ["2026-11-05", "2026-11-05"])
    assert any("NoneType" in p for p in out2["problems"]), "调用成功却返回 None 仍然是问题(S-323g 的兜底不放松)"


def test_sql_scan_is_bounded():
    mig = (ROOT / "migrations/2026-11-06_refresh_depth_divergence_bounded.sql").read_text(encoding="utf-8")
    assert "trade_date > v_d - 200" in mig and "depth_divergence_v2" in mig, "只加下界,规则版本不变"


def test_backfill_failure_carries_its_reason(monkeypatch):
    """11-06:_forward_return_backfill_loop 24 小时 26 次 error、reason 全空 —— 失败原因在 StoreResult.why 里没往外带。"""
    import src.api.store as store
    from src.data.signals import forward_return_backfill as frb

    async def rpc(fn, payload=None, *, timeout=None):
        return _R(False, None, "no response from Supabase after retries")
    monkeypatch.setattr(store, "supabase_rpc_write", rpc)
    monkeypatch.setattr(store, "_SB_URL", "https://x")
    monkeypatch.setattr(store, "_SB_KEY", "k")
    out = asyncio.run(frb.backfill_forward_returns())
    assert out["ok"] is False and "no response" in out["reason"]
    mig = (ROOT / "migrations/2026-11-06_exec_backfill_forward_returns_lateral.sql").read_text(encoding="utf-8")
    assert "join lateral" in mig and "auth.role() is distinct from 'service_role'" in mig, "安全模型不变"
