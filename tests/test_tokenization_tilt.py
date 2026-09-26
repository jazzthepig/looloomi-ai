"""S-427 — 代币化基础设施倾斜账本:预注册的规则被钉住,fusion 那种「只扣成本不记价格」不可能发生。"""
import math

import pandas as pd
import pytest

from src.data.signals import tokenization_tilt as tt

PANEL = ("BTC", "ETH", "LINK", "UNI")          # 小面板,足够验规则


def _px(days, **cols):
    return pd.DataFrame(cols, index=pd.to_datetime(days), dtype=float)


def _row(rows, d, arm):
    return next(r for r in rows if r["d"] == d and r["arm"] == arm)


def test_inception_weights_are_the_preregistered_split():
    px = _px(["2026-09-25"], BTC=[1], ETH=[1], LINK=[1], UNI=[1], ONDO=[1], HYPE=[1])
    rows = tt.compute_path(px, PANEL, [], "t")
    base = _row(rows, "2026-09-25", "panel_hold")
    tilt = _row(rows, "2026-09-25", "tokenization_tilt_25")
    assert all(math.isclose(v, 0.25) for v in base["weights"].values())
    # 篮子里有报价的:LINK/UNI(也在面板)+ ONDO/HYPE —— 篮子合计 = 25% + 面板里 LINK/UNI 的 75%×2/4
    assert math.isclose(tilt["basket_weight"], 0.25 + 0.75 * 0.5, abs_tol=1e-4)
    assert math.isclose(sum(tilt["weights"].values()), 1.0, abs_tol=1e-4)
    assert base["rebalanced"] and tilt["rebalanced"]


def test_price_moves_are_marked_not_just_costs():
    """fusion 22 天 ret ≡ −0.05%:只扣成本。这里 LINK +10% 必须体现在 NAV 上。"""
    px = _px(["2026-09-25", "2026-09-26"],
             BTC=[1, 1], ETH=[1, 1], LINK=[1, 1.1], UNI=[1, 1], ONDO=[1, 1.2], HYPE=[1, 1])
    rows = tt.compute_path(px, PANEL, [], "t")
    b = _row(rows, "2026-09-26", "panel_hold")
    t = _row(rows, "2026-09-26", "tokenization_tilt_25")
    assert math.isclose(b["ret"], 0.25 * 0.10, rel_tol=1e-6)          # 面板里只有 LINK 动
    link_w = 0.75 * 0.25 + 0.25 * 0.25          # 面板 1/4 + 篮子 1/4(LINK/UNI/ONDO/HYPE 四个)
    ondo_w = 0.25 * 0.25                        # 只在篮子里
    assert math.isclose(t["ret"], link_w * 0.10 + ondo_w * 0.20, rel_tol=1e-6)
    assert t["ret"] > b["ret"]
    assert t["nav"] != 1.0 and b["nav"] != 1.0


def test_rebalances_only_on_the_first_of_the_month():
    days = pd.date_range("2026-09-25", "2026-10-03", freq="D")
    n = len(days)
    px = pd.DataFrame({s: [1.0] * n for s in ("BTC", "ETH", "LINK", "UNI", "ONDO")}, index=days)
    rows = tt.compute_path(px, PANEL, [], "t")
    reb = sorted({r["d"] for r in rows if r["rebalanced"]})
    assert reb == ["2026-09-25", "2026-10-01"]


def test_missing_quotes_refuse_rather_than_mark_flat():
    """读不到 ≠ 没涨跌。持仓一半没有真实收盘 ⇒ 抛错,不记平 NAV。"""
    px = _px(["2026-09-25", "2026-09-26"],
             BTC=[1, float("nan")], ETH=[1, float("nan")], LINK=[1, 1.0], UNI=[1, 1.0])
    with pytest.raises(ValueError, match="读不到"):
        tt.compute_path(px, PANEL, [], "t")


def test_does_not_silently_start_elsewhere():
    px = _px(["2026-09-26"], BTC=[1], ETH=[1], LINK=[1], UNI=[1])
    with pytest.raises(ValueError, match="起点"):
        tt.compute_path(px, PANEL, [], "t")


def test_deterministic_recompute():
    px = _px(["2026-09-25", "2026-09-26", "2026-09-27"],
             BTC=[1, 1.02, 0.99], ETH=[1, 0.97, 1.01], LINK=[1, 1.1, 1.05], UNI=[1, 1, 1],
             ONDO=[1, 1.2, 1.1], HYPE=[1, 0.9, 1.0])
    a = tt.compute_path(px, PANEL, [], "t")
    b = tt.compute_path(px, PANEL, [], "t")
    strip = lambda rs: [{k: v for k, v in r.items() if k != "computed_at"} for r in rs]
    assert strip(a) == strip(b)


def test_basket_matches_the_decision():
    """Jazz 09-26 选「通路+发行」;场所未挂牌/下架的显式列出,不静默丢。"""
    assert set(tt.BASKET) == {"LINK", "ONDO", "PENDLE", "POLYX", "AAVE", "UNI", "HYPE"}
    assert set(tt.RESEARCH_ONLY) == {"QNT", "MKR"}
    assert tt.TILT == 0.25 and tt.INCEPTION == pd.Timestamp("2026-09-25")
