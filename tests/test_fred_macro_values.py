"""FRED 宏观回退的两处读数错(10-29,线上 /market/economic-indicators):

- GDP:A191RL1Q225SBEA 已是「季调后折年率」,原来再 ×4 —— 页面 2.2%,喂给状态阈值的是 8.8%;
- CPI:prev_value 原来是「一年前那个月的环比」(3.72 旁边写 0.3),trend 是「同比 > 0 就 up」。
"""
import asyncio

from src.data.market import data_layer as dl

# 15 个月的 CPI 指数(升序写,函数自己排序):同比由 2.0% 升到 3.0%
_CPI = [("2025-07-01", 100.0), ("2025-08-01", 100.2), ("2025-09-01", 100.4), ("2025-10-01", 100.6),
        ("2025-11-01", 100.8), ("2025-12-01", 101.0), ("2026-01-01", 101.2), ("2026-02-01", 101.4),
        ("2026-03-01", 101.6), ("2026-04-01", 101.8), ("2026-05-01", 102.0), ("2026-06-01", 102.2),
        ("2026-07-01", 102.4), ("2026-08-01", 102.814), ("2026-09-01", 103.0)]
_SERIES = {"CPIAUCSL": _CPI,
           "A191RL1Q225SBEA": [("2026-01-01", 2.5), ("2026-04-01", 2.2)],
           "UNRATE": [("2026-08-01", 4.1), ("2026-09-01", 4.2)],
           "FEDFUNDS": [("2026-08-01", 3.63), ("2026-09-01", 3.75)]}


class _R:
    status_code = 200

    def __init__(self, text):
        self.text = text


class _Client:
    async def get(self, url, params=None, timeout=None):
        rows = _SERIES[params["id"]]
        return _R("DATE,VALUE\n" + "\n".join(f"{d},{v}" for d, v in rows))


def _run(monkeypatch):
    async def _none(*a, **k):
        return None
    monkeypatch.setattr(dl, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(dl, "_cache_set", lambda k, v: v)
    monkeypatch.setattr(dl, "_redis_get", _none)
    monkeypatch.setattr(dl, "_redis_set", _none)
    monkeypatch.setattr(dl, "_get_misc_client", lambda: _Client())
    return asyncio.new_event_loop().run_until_complete(dl._get_fred_macro_indicators("usa"))


def test_gdp_is_not_annualised_twice(monkeypatch):
    r = _run(monkeypatch)
    assert r["indicators"]["gdp_growth"]["value"] == 2.2
    assert r["regime_inputs"]["gdp_growth"] == 2.2


def test_cpi_prev_value_is_last_months_yoy_and_trend_compares_them(monkeypatch):
    r = _run(monkeypatch)
    cpi = r["indicators"]["cpi_yoy"]
    assert cpi["value"] == round((103.0 - 100.4) / 100.4 * 100, 2)          # 2026-09 vs 2025-09
    assert cpi["prev_value"] == round((102.814 - 100.2) / 100.2 * 100, 2)   # 2026-08 vs 2025-08
    assert cpi["trend"] == ("up" if cpi["value"] > cpi["prev_value"] else "down")
    assert abs(cpi["prev_value"]) > 1, "prev_value 必须是同比量级,不是环比"
