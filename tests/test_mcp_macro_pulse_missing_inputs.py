"""2026-11-23:`cometcloud_get_macro_pulse` 在 CoinGecko 停供期间对所有 agent 报
`TypeError: unsupported format string passed to NoneType.__format__` —— 上游取不到 BTC 占比时那个值是 None(不是 0),
而工具里直接 `f"{dom:.1f}"`。缺就写 n/a;不报错,也不编一个 0。"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _call(monkeypatch, payload: dict) -> str:
    from src.mcp.pulse_format import macro_pulse_markdown
    return macro_pulse_markdown(payload)


def test_the_tool_uses_the_formatter() -> None:
    src = (ROOT / "src/mcp/cometcloud_mcp.py").read_text(encoding="utf-8")
    seg = src[src.index("async def cometcloud_get_macro_pulse"):src.index("# ── Tools — Signals & Intelligence")]
    assert "macro_pulse_markdown(data)" in seg and ":.1f}" not in seg, "工具里又出现了直接排版 —— None 会再炸一次"


def test_missing_dominance_and_price_read_as_na_not_an_error(monkeypatch) -> None:
    out = _call(monkeypatch, {"btc_dominance": None, "btc_price": None, "fear_greed_index": 12,
                              "fear_greed_label": "Extreme Fear", "macro_regime": "RISK_OFF",
                              "total_market_cap_usd": None, "defi_tvl_usd": None})
    assert "Error" not in out and "TypeError" not in out
    assert "**BTC Dominance**: n/a" in out and "**BTC Price**: n/a" in out
    assert "**Regime**: RISK_OFF" in out and "12 — Extreme Fear" in out
    assert "0.0%" not in out and "$0" not in out, "缺不许写成 0"


def test_present_values_still_format(monkeypatch) -> None:
    out = _call(monkeypatch, {"btc_dominance": 56.319, "btc_price": 61921.4, "fear_greed_index": 10,
                              "fear_greed_label": "Extreme Fear", "macro_regime": "RISK_OFF",
                              "total_market_cap_usd": 2.2e12, "defi_tvl_usd": 9.5e10})
    assert "**BTC Dominance**: 56.3%" in out and "**BTC Price**: $61,921" in out
    assert "$2200.0B" in out and "$95.0B" in out
