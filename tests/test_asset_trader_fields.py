"""2026-10-26 用户报告 → 单资产端点给交易者的三样东西:信号稳定性、HL 可交易性、正式/盘中口径分开。"""
from src.api.routers.cis import hl_tradability, signal_stability
from src.data.cis import official


def _pts(seq, start=1):
    return [{"d": f"2026-10-{start + i:02d}", "signal": s} for i, s in enumerate(seq)]


def test_stability_since_and_changes():
    pts = _pts(["NEUTRAL"] * 5 + ["OUTPERFORM"] * 4)
    st = signal_stability(pts)
    assert st["available"] and st["signal"] == "OUTPERFORM"
    assert st["since"] == "2026-10-06" and st["days_held"] == 4
    assert st["changes_30d"] == 1


def test_stability_counts_quick_reversal_only_when_observable():
    # 10-03 换到 UNDERPERFORM,10-05 换回 NEUTRAL(3 天内)→ 1 次;10-09 的换档还没看满 3 天 → 不数
    pts = _pts(["NEUTRAL", "NEUTRAL", "UNDERPERFORM", "UNDERPERFORM", "NEUTRAL",
                "NEUTRAL", "NEUTRAL", "NEUTRAL", "OUTPERFORM", "OUTPERFORM"])
    st = signal_stability(pts)
    assert st["changes_30d"] == 3
    assert st["reverted_within_3d_90d"] == 1


def test_stability_empty():
    assert signal_stability([]) == {"available": False}


def test_hl_tradability_usd_oi_and_k_prefix():
    snap = {"ok": True, "fetched_at": "t", "assets": {
        "NEAR": {"mark": 2.0, "open_interest": 1_000_000.0, "day_notional_volume": 5e6, "funding_1h": 1e-5},
        "KPEPE": {"mark": 0.01, "open_interest": 3e9, "day_notional_volume": 1e7, "funding_1h": 0.0}}}
    n = hl_tradability("near", snap)
    assert n["listed"] and n["open_interest_usd"] == 2_000_000
    assert hl_tradability("PEPE", snap)["open_interest_usd"] == 30_000_000
    assert hl_tradability("XYZ", snap)["listed"] is False
    assert hl_tradability("NEAR", {"ok": False, "reason": "x"})["available"] is False


def test_overlay_moves_regime_confidence_into_intraday():
    # 报告:「日线 NEUTRAL,置信度 0.41」—— 0.41 属于盘中状态,不该挂在正式档位旁边
    from datetime import date
    live = {"universe": [{"symbol": "NEAR", "cis_score": 60.0, "grade": "B", "signal": "NEUTRAL",
                          "macro_regime": "TIGHTENING", "regime_confidence": 0.41},
                         {"symbol": "NEW", "cis_score": 40.0, "signal": "NEUTRAL", "regime_confidence": 0.5}]}
    row = {"symbol": "NEAR", "d": "2026-10-10", "cis_score": 66.0, "regime_adjusted_score": 65.0, "grade": "B+",
           "signal": "OUTPERFORM", "pct": 0.7, "regime": "RISK_ON", "code_ref": official.CODE_REF,
           "published_at": "2026-10-11T00:10:00+00:00"}
    latest = {"d": "2026-10-10", "code_ref": official.CODE_REF, "published_at": row["published_at"],
              "rows": {"NEAR": row}}
    live["regime_confidence"], live["macro_regime"] = 0.41, "TIGHTENING"
    res = official.overlay(live, latest, today=date(2026, 10, 11))
    assert res["macro_regime"] == "RISK_ON" and "regime_confidence" not in res
    assert res["intraday"] == {"macro_regime": "TIGHTENING", "regime_confidence": 0.41}
    by = {a["symbol"]: a for a in res["universe"]}
    assert "regime_confidence" not in by["NEAR"]
    assert by["NEAR"]["intraday"]["regime_confidence"] == 0.41
    assert by["NEW"]["regime_confidence"] == 0.5, "names without an official row keep the intraday reading as is"
