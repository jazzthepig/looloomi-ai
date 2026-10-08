"""S-528 / T-077:CIS 特征臂 —— 分组、三条臂的权重规则、只用 d−1 的信号、稳定币不进宇宙。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.signals.feature_arms import arm_weights, build, cis_group, groups_frame  # noqa: E402


def test_cis_group_maps_only_compliant_signals() -> None:
    assert cis_group("STRONG OUTPERFORM") == "OUT" and cis_group("outperform") == "OUT"
    assert cis_group("UNDERWEIGHT") == "UNDER" and cis_group("UNDERPERFORM") == "UNDER"
    assert cis_group("NEUTRAL") == "NEU"
    assert cis_group("HOLD") is None and cis_group(None) is None


def test_arm_weights_rules() -> None:
    g = {"A": "OUT", "B": "UNDER", "C": "NEU", "D": "UNDER"}
    assert arm_weights("cis_ew", g, True) == {s: 0.25 for s in "ABCD"}
    assert arm_weights("cis_follow", g, False) == {"A": 1.0}
    assert arm_weights("cis_follow", {"B": "UNDER", "C": "NEU"}, False) == {"B": 0.5, "C": 0.5}, "没有 OUT ⇒ 宇宙等权"
    down = arm_weights("cis_contra", g, True)
    assert "A" not in down and abs(down["B"] - 0.4) < 1e-12 and abs(down["C"] - 0.2) < 1e-12, "下行时 UNDER 2 倍"
    up = arm_weights("cis_contra", g, False)
    assert "A" not in up and all(abs(v - 1 / 3) < 1e-12 for v in up.values())
    assert arm_weights("cis_contra", g, None) == up, "均线读不出 ⇒ 不加倍"
    assert arm_weights("cis_contra", {"A": "OUT"}, True) == {"A": 1.0}, "全是 OUT ⇒ 退回等权,不空仓"


def test_build_uses_previous_day_signal_and_skips_stables() -> None:
    days = pd.date_range("2025-03-01", "2025-06-30", freq="D")
    rng = np.random.default_rng(0)
    px = pd.DataFrame({s: 100 * np.cumprod(1 + rng.normal(0, 0.02, len(days))) for s in ("BTC", "AAA", "BBB", "USDT")},
                      index=days)
    grp = pd.DataFrame("NEU", index=days, columns=px.columns)
    mon = pd.Timestamp("2025-05-19")
    grp.loc[mon - pd.Timedelta(days=1), "AAA"] = "OUT"          # d−1 是 OUT
    grp.loc[mon, "AAA"] = "NEU"                                 # d 当天又变回 —— 不该被看到
    rows, ev = build(px, grp, pd.Timestamp("2025-06-30"))
    assert {r["arm"] for r in rows} == {"cis_ew", "cis_follow", "cis_contra"}
    r = pd.DataFrame(rows)
    assert r["d"].min() == "2025-05-12"
    fol = r[(r["arm"] == "cis_follow") & (r["d"] == mon.date().isoformat())]["ret"].iloc[0]
    aaa = px.at[mon, "AAA"] / px.at[mon - pd.Timedelta(days=1), "AAA"] - 1
    assert 0 <= aaa - fol <= 2 * 10 / 1e4 + 1e-12, "cis_follow 在那个周一只持 AAA(d−1 的信号),差的只是换手成本"
    ew = r[(r["arm"] == "cis_ew") & (r["d"] == mon.date().isoformat())]["ret"].iloc[0]
    assert abs(ew - fol) > 1e-6
    assert "USDT" not in ev["latest_out"] and ev["latest_universe"]["NEU"] == 3, "稳定币不进宇宙"


def test_groups_frame_filters_crypto_and_noncompliant() -> None:
    rows = [{"symbol": "AAA", "asset_class": "L1", "d": "2025-05-01", "signal": "OUTPERFORM"},
            {"symbol": "SPY", "asset_class": "US Equity", "d": "2025-05-01", "signal": "OUTPERFORM"},
            {"symbol": "BBB", "asset_class": "DeFi", "d": "2025-05-01", "signal": "HOLD"}]
    g = groups_frame(rows)
    assert list(g.columns) == ["AAA"] and g.iloc[0, 0] == "OUT"
