"""Smoke test for BTT-LEX (M-152 Path π) family wire.

Tests:
  T1: 趋势 ON + EASING → ENTERED weight 1.30
  T2: 趋势 ON + RISK_OFF → SKIPPED "regime ladder = 0"
  T3: 趋势 OFF (close < ma200) → SKIPPED "trend off"
  T4: 趋势 OFF (mom60 < 0) → SKIPPED "trend off"
  T5: BTC 缺失 → BLOCKED
  T6: BTC 历史 < ma_lookback+1 → BLOCKED
  T7: 未知 regime → fallback NEUTRAL → ENTERED weight 1.00
  T8: max_open_trades hit → SKIPPED
  T9: panel too old → BLOCKED
"""
from __future__ import annotations
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai")

from paper_trading.spec_runner import (
    Spec, Panel, decide_btc_trend, build_panel
)


def _make_btc_panel(n_days: int, end: date, *, start_price: float = 100.0,
                     trend_up: bool = True) -> list[dict]:
    """Synthetic BTC panel with deterministic trend."""
    rows = []
    px = start_price
    for i in range(n_days):
        d = (end - timedelta(days=n_days - 1 - i)).isoformat()
        if trend_up:
            px = px * 1.003    # ~0.3%/day up
        else:
            px = px * 0.997    # ~0.3%/day down
        rows.append({"symbol": "BTC", "trade_date": d, "close": px, "source": "binance_hist"})
    return rows


def _save_spec(params: dict) -> str:
    spec = {
        "spec_name": "btt_lex_test",
        "spec_family": "btc_trend_regime_ladder",
        "universe": ["BTC"],
        "parameters": {
            "ma_lookback": 200,
            "mom_lookback": 60,
            "regime_multipliers": {
                "EASING": 1.30,
                "TIGHTENING": 1.15,
                "NEUTRAL": 1.00,
                "STAGFLATION": 0.80,
                "RISK_OFF": 0.00,
                "RISK_ON": 1.15,
            },
            "cost_bps_rt": 5.0,
            "dd_stop_pct": -20.0,
            "max_open_trades": 1,
            **params,
        },
        "data_source": {"primary": "binance_hist"},
        "execution": {"dry_run": True},
    }
    fd = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(spec, fd)
    fd.close()
    return fd.name


def test_t1_trend_on_easing():
    spec_path = _save_spec({})
    spec = Spec.load(spec_path)
    end = date(2026, 8, 15)
    panel = build_panel(_make_btc_panel(220, end, trend_up=True), source="binance_hist")
    d = decide_btc_trend(spec, panel, as_of=end, regime="EASING", n_open=0)
    print(f"  T1 verdict={d.verdict} weight={d.legs[0].weight if d.legs else 'n/a'}")
    assert d.verdict == "ENTERED", f"expected ENTERED, got {d.verdict} reason={d.reason}"
    assert d.legs[0].weight == 1.30, f"expected weight 1.30, got {d.legs[0].weight}"
    print("✓ T1: trend ON + EASING → ENTERED weight 1.30")


def test_t2_trend_on_risk_off():
    spec_path = _save_spec({})
    spec = Spec.load(spec_path)
    end = date(2026, 8, 15)
    panel = build_panel(_make_btc_panel(220, end, trend_up=True), source="binance_hist")
    d = decide_btc_trend(spec, panel, as_of=end, regime="RISK_OFF", n_open=0)
    print(f"  T2 verdict={d.verdict} reason={d.reason[:80] if d.reason else 'n/a'}")
    assert d.verdict == "SKIPPED"
    assert "ladder" in d.reason and "0" in d.reason, f"unexpected reason: {d.reason}"
    print("✓ T2: trend ON + RISK_OFF → SKIPPED 'regime ladder = 0'")


def test_t3_trend_off_close_below_ma():
    spec_path = _save_spec({})
    spec = Spec.load(spec_path)
    end = date(2026, 8, 15)
    # Start high, drop down so close < ma200
    rows = []
    px = 200.0
    for i in range(220):
        d = (end - timedelta(days=219 - i)).isoformat()
        px = px * (0.995 if i > 100 else 1.005)   # up then sharp down
        rows.append({"symbol": "BTC", "trade_date": d, "close": px, "source": "binance_hist"})
    panel = build_panel(rows, source="binance_hist")
    d = decide_btc_trend(spec, panel, as_of=end, regime="EASING", n_open=0)
    print(f"  T3 verdict={d.verdict} reason={d.reason[:80] if d.reason else 'n/a'}")
    assert d.verdict == "SKIPPED"
    assert "trend OFF" in d.reason, f"unexpected reason: {d.reason}"
    print("✓ T3: close < ma200 → SKIPPED 'trend OFF'")


def test_t4_trend_off_negative_mom():
    spec_path = _save_spec({})
    spec = Spec.load(spec_path)
    end = date(2026, 8, 15)
    # Slow climb for 200d (so close > ma200) but mom60 negative (recent drop)
    rows = []
    px = 100.0
    for i in range(220):
        d = (end - timedelta(days=219 - i)).isoformat()
        if i < 160:
            px = px * 1.003   # up
        else:
            px = px * 0.99    # sharp drop in last 60d
        rows.append({"symbol": "BTC", "trade_date": d, "close": px, "source": "binance_hist"})
    panel = build_panel(rows, source="binance_hist")
    d = decide_btc_trend(spec, panel, as_of=end, regime="EASING", n_open=0)
    print(f"  T4 verdict={d.verdict} reason={d.reason[:80] if d.reason else 'n/a'}")
    assert d.verdict == "SKIPPED"
    assert "trend OFF" in d.reason
    print("✓ T4: mom60 < 0 → SKIPPED 'trend OFF'")


def test_t5_btc_missing():
    spec_path = _save_spec({})
    spec = Spec.load(spec_path)
    end = date(2026, 8, 15)
    rows = [{"symbol": "ETH", "trade_date": (end - timedelta(days=i)).isoformat(),
             "close": 100.0, "source": "binance_hist"} for i in range(220)]
    panel = build_panel(rows, source="binance_hist")
    d = decide_btc_trend(spec, panel, as_of=end, regime="EASING", n_open=0)
    print(f"  T5 verdict={d.verdict}")
    assert d.verdict == "BLOCKED"
    assert "BTC 不在" in d.reason
    print("✓ T5: BTC missing → BLOCKED")


def test_t6_insufficient_history():
    spec_path = _save_spec({})
    spec = Spec.load(spec_path)
    end = date(2026, 8, 15)
    panel = build_panel(_make_btc_panel(150, end), source="binance_hist")  # only 150 < 201
    d = decide_btc_trend(spec, panel, as_of=end, regime="EASING", n_open=0)
    print(f"  T6 verdict={d.verdict}")
    assert d.verdict == "BLOCKED"
    assert "MA200" in d.reason or "MA" in d.reason
    print("✓ T6: BTC history < ma_lookback+1 → BLOCKED")


def test_t7_unknown_regime_falls_back_to_neutral():
    spec_path = _save_spec({})
    spec = Spec.load(spec_path)
    end = date(2026, 8, 15)
    panel = build_panel(_make_btc_panel(220, end, trend_up=True), source="binance_hist")
    d = decide_btc_trend(spec, panel, as_of=end, regime="WEIRD_NEW_LABEL", n_open=0)
    print(f"  T7 verdict={d.verdict} weight={d.legs[0].weight if d.legs else 'n/a'}")
    assert d.verdict == "ENTERED"
    assert d.legs[0].weight == 1.00, f"unknown regime should fall back to NEUTRAL=1.00, got {d.legs[0].weight}"
    print("✓ T7: unknown regime → fallback NEUTRAL weight 1.00")


def test_t8_max_open_trades():
    spec_path = _save_spec({})
    spec = Spec.load(spec_path)
    end = date(2026, 8, 15)
    panel = build_panel(_make_btc_panel(220, end, trend_up=True), source="binance_hist")
    d = decide_btc_trend(spec, panel, as_of=end, regime="EASING", n_open=1)
    print(f"  T8 verdict={d.verdict} reason={d.reason[:80] if d.reason else 'n/a'}")
    assert d.verdict == "SKIPPED"
    assert "max_open_trades" in d.reason
    print("✓ T8: n_open=1 (>= max=1) → SKIPPED")


def test_t9_panel_too_old():
    spec_path = _save_spec({})
    spec = Spec.load(spec_path)
    end = date(2026, 8, 15)
    panel = build_panel(_make_btc_panel(220, end - timedelta(days=5)), source="binance_hist")
    # as_of=end but panel last_bar is 5 days ago → age=5 > MAX_PANEL_AGE_DAYS=2
    d = decide_btc_trend(spec, panel, as_of=end, regime="EASING", n_open=0)
    print(f"  T9 verdict={d.verdict} panel_last_bar={panel.last_bar}")
    assert d.verdict == "BLOCKED"
    assert "已 5 天" in d.reason or "5 天" in d.reason
    print("✓ T9: panel 5d old → BLOCKED")


if __name__ == "__main__":
    print("=== BTT-LEX (M-152 Path π) family smoke ===\n")
    test_t1_trend_on_easing()
    test_t2_trend_on_risk_off()
    test_t3_trend_off_close_below_ma()
    test_t4_trend_off_negative_mom()
    test_t5_btc_missing()
    test_t6_insufficient_history()
    test_t7_unknown_regime_falls_back_to_neutral()
    test_t8_max_open_trades()
    test_t9_panel_too_old()
    print(f"\n=== All BTT-LEX smoke tests passed (9/9) ===")
