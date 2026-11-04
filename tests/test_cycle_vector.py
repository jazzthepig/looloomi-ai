"""⓪ 周期向量(11-04,S-713):分量按时点、扩张 z 前 365 天不打分、恶化 + 搬家 + 滞回相位,合成的转向被认出来、之前不误报。"""
from __future__ import annotations

import datetime as dt
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.state import cycle_vector as cv  # noqa: E402


def _synth(n=900, break_at=700, seed=3):
    random.seed(seed)
    base = dt.date(2019, 1, 1)
    state, macro, liq = [], [], 1.0
    for i in range(n):
        d = (base + dt.timedelta(days=i)).isoformat()
        for name, feat in cv.STATE_FEATURES.items():
            v = random.gauss(0, 1)
            if i > break_at:
                v += 3.0 if cv.SIGN[name] < 0 else -3.0
            state.append({"d": d, "feature": feat, "value": v})
        liq *= 1 + random.gauss(0, 0.002) - (0.003 if i > break_at else 0)
        macro.append({"d": d, "value": liq})
    return state, macro


def test_components_are_point_in_time_and_fed_change_needs_60_days():
    state, macro = _synth(100)
    comps = cv.components_by_day(state, macro)
    assert "fed_liq_60d" not in comps["2019-01-10"] and "fed_liq_60d" in comps["2019-03-15"]
    assert set(cv.STATE_FEATURES) <= set(comps["2019-01-10"])


def test_turning_is_detected_after_a_regime_break_and_not_before():
    state, macro = _synth()
    rows = cv.zscores(cv.components_by_day(state, macro))
    assert rows[100]["phase"] is None and rows[100]["z"] == {}, "前 365 天不打分"
    before = [r for r in rows if "2020-01-01" <= r["d"] <= "2020-11-20"]
    assert sum(1 for r in before if r["phase"] != "normal") <= 0.01 * len(before), "断点前纯噪声上几乎不误报(连续 3 天去抖)"
    after = [r for r in rows if r["d"] >= "2020-12-15"]
    assert sum(1 for r in after if r["phase"] == "turning") / len(after) > 0.9, "断点后 10 天内进转向相并保持"
    first = next(r for r in rows if r["phase"] == "turning")
    assert first["deterioration"] <= cv.TURN_DET and first["shift_pct"] >= cv.TURN_SHIFT_PCT and first["d"] >= "2020-12-03"
    assert all(abs(v) <= 4 for r in rows for v in r["z"].values()), "z 截在 ±4"


def test_hysteresis_exits_only_when_deterioration_recovers():
    state, macro = _synth(n=1000, break_at=700)
    # 第 850 天起回到正常分布 ⇒ 恶化回到 > 0 才退出
    base = dt.date(2019, 1, 1)
    random.seed(9)
    for r in state:
        if r["d"] >= (base + dt.timedelta(days=850)).isoformat():
            r["value"] = random.gauss(0, 1)
    rows = cv.zscores(cv.components_by_day(state, macro))
    tail = [r["phase"] for r in rows if r["d"] >= (base + dt.timedelta(days=900)).isoformat()]
    assert "normal" in tail


def test_wiring():
    assert "_cycle_vector_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert 'inputs["cycle_phase"]' in (ROOT / "src/data/execution/exposure_decision.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-04_cycle_vector_daily.sql").read_text(encoding="utf-8")
    for col in cv.WRITES_COLUMNS[cv.TABLE]:
        assert col in mig, col


def test_run_once_recomputes_when_code_ref_changed_and_never_writes_past_d(monkeypatch):
    import asyncio
    import src.api.store as store
    import src.data.style.header as hdr
    up = {}
    state, macro = _synth(400)
    state.append({"d": "2020-02-05", "feature": "breadth_above_ma50", "value": 0.5})   # 今天的半日行

    async def read_all(t, params):
        if t == cv.TABLE:
            return [{"d": "2020-02-04", "code_ref": "cycle_vector v1 (11-04)"}]      # 旧版写的 ⇒ 要重算
        if t == "state_daily":
            assert "funding_7d_ann_binance" in params["feature"] and "funding_7d_ann," not in params["feature"]
            return state
        if t == "macro_daily":
            return macro
        raise AssertionError(t)

    async def ups(t, rows, on_conflict):
        up[t] = rows
        return True
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    r = asyncio.run(cv.run_once(dt.datetime(2020, 2, 5, 9, 0, tzinfo=dt.timezone.utc)))
    assert r["ok"] and r["d"] == "2020-02-04" and max(x["d"] for x in up[cv.TABLE]) == "2020-02-04"
    assert all(x["code_ref"] == cv.CODE_REF for x in up[cv.TABLE])
