"""② 小股东待遇倾斜前向账(S-711):分类、乘数归一、周一再平衡、乘数取前一天的 treatment_daily、起点缺行拒绝。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.signals import treatment_tilt as tt  # noqa: E402


def test_classify_and_targets():
    assert tt.classify(None) == "none" and tt.classify({"revenue_30d": None}) == "none"
    assert tt.classify({"revenue_30d": 1e6, "holders_share": 1.0}) == "pays"
    assert tt.classify({"revenue_30d": 1e6, "holders_share": 0.0}) == "keeps"
    assert tt.classify({"revenue_30d": 1e6, "holders_share": 0.49}) == "keeps"
    panel = ("BTC", "HYPE", "AAVE", "UNI")
    cls = {"HYPE": "pays", "AAVE": "keeps", "UNI": "pays"}
    w = tt.targets("treatment_tilt", set(panel), panel, cls)
    assert abs(sum(w.values()) - 1) < 1e-9 and abs(w["HYPE"] / w["BTC"] - 1.5) < 1e-9 and abs(w["AAVE"] / w["BTC"] - 0.5) < 1e-9
    assert tt.targets("panel_hold", {"BTC", "HYPE"}, panel, cls) == {"BTC": 0.5, "HYPE": 0.5}
    assert tt.targets("treatment_tilt", set(), panel, cls) == {}


def test_compute_path_rebalances_mondays_with_previous_day_classes():
    days = pd.date_range("2026-11-02", periods=16, freq="D")
    px = pd.DataFrame({"BTC": [100 + i for i in range(16)], "HYPE": [10 + 0.5 * i for i in range(16)],
                       "AAVE": [200 - 2 * i for i in range(16)]}, index=days, dtype=float)
    classes = {"2026-11-03": {"HYPE": "pays", "AAVE": "keeps"}, "2026-11-08": {"HYPE": "pays", "AAVE": "keeps"}}
    rows = tt.compute_path(px, ("BTC", "HYPE", "AAVE"), classes, [], "test", end=days[-1])
    tilt = [r for r in rows if r["arm"] == "treatment_tilt"]
    hold = [r for r in rows if r["arm"] == "panel_hold"]
    assert tilt[0]["d"] == "2026-11-04" and tilt[0]["rebalanced"] and tilt[0]["tilt_classes"] == {"pays": 1, "keeps": 1, "none": 1}
    reb = [r["d"] for r in tilt if r["rebalanced"]]
    assert "2026-11-09" in reb and "2026-11-16" in reb and "2026-11-10" not in reb, "周一再平衡(UTC)"
    assert abs(tilt[0]["weights"]["HYPE"] / tilt[0]["weights"]["BTC"] - 1.5) < 1e-3
    assert tilt[-1]["nav"] > hold[-1]["nav"], "合成里 HYPE 涨 AAVE 跌,倾斜臂该赢"
    assert all(abs(sum(r["weights"].values()) - 1) < 0.02 for r in rows)
    try:
        tt.compute_path(px.iloc[3:], ("BTC", "HYPE", "AAVE"), classes, [], "test")
        raise AssertionError("起点没行要拒")
    except ValueError:
        pass


def test_registry_loop_and_migration():
    from src.data.accounting.registry import BOOKS
    b = next(x for x in BOOKS if x.id == "treatment_tilt")
    assert b.layer == "②" and b.table == tt.TABLE and b.arm == "treatment_tilt" and b.benchmark == "arm:panel_hold"
    assert "_treatment_tilt_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-04_treatment_tilt_daily.sql").read_text(encoding="utf-8")
    for col in tt.WRITES_COLUMNS[tt.TABLE]:
        assert col in mig, col
