"""S-537 — 代币迁移(MKR→SKY 1:24000、MATIC→POL 1:1)在 CIS 统一标准里接成一段。

守:① 生效日 = 新币 30 日平均成交第一次超过旧币、且不早于迁移开始日,只用当天及以前的数据;
② 生效日前价格按比例换成新币单位,之后用新币自己的;旧币市值记 0 而新币有市值时用新币的;
③ 正式视图里旧代码让位给新代码,正式有、实时没有的名字补进来;④ 前一天的档:正式优先、缺的取重建。
"""
from __future__ import annotations

import pandas as pd

from src.data.cis.migrations import BY_NEW, RETIRED, chain, effective_day, token_on


def _s(start: str, vals: list[float]) -> pd.Series:
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq="D"), dtype=float)


def test_registry_has_both_migrations_with_fixed_ratios() -> None:
    assert BY_NEW["SKY"]["old"] == "MKR" and BY_NEW["SKY"]["ratio"] == 24000.0
    assert BY_NEW["POL"]["old"] == "MATIC" and BY_NEW["POL"]["ratio"] == 1.0
    assert RETIRED == {"MKR": "SKY", "MATIC": "POL"}


def test_effective_day_is_first_volume_crossover_after_start() -> None:
    old = _s("2025-01-01", [100.0] * 60 + [1.0] * 60)
    new = _s("2025-01-01", [0.0] * 40 + [150.0] * 80)
    eff = effective_day(old, new, "2025-01-01")
    # 新币 30 日均值(≥ 20 天有数)第一次 > 旧币 30 日均值
    om = old.rolling(30, min_periods=1).mean()
    nm = new.rolling(30, min_periods=20).mean()
    want = ((nm > om) & nm.notna())
    assert eff == want[want].index[0]
    assert effective_day(old, new, "2025-04-15") == pd.Timestamp("2025-04-15"), "不早于迁移开始日"
    assert effective_day(old, _s("2025-01-01", [150.0] * 10), "2025-01-01") is None, "新币不足 20 天 → 判不了"


def test_effective_day_only_uses_data_up_to_that_day() -> None:
    old = _s("2025-01-01", [100.0] * 90)
    new = _s("2025-01-01", [50.0] * 70 + [400.0] * 20)
    eff = effective_day(old, new, "2025-01-01")
    eff_trunc = effective_day(old[:eff], new[:eff], "2025-01-01")
    assert eff is not None and eff_trunc == eff, "截到生效日当天也判得出同一天(没有偷看后面)"


def test_chain_scales_price_before_switch_and_takes_new_mcap_when_old_is_zero() -> None:
    idx = "2025-06-01"
    old = (_s(idx, [2400.0, 2400.0, 2448.0, 2448.0]), _s(idx, [9e8, 0.0, 0.0, 0.0]), _s(idx, [5e7] * 4),
           _s(idx, [2500.0] * 4), _s(idx, [2300.0] * 4))
    new = (_s(idx, [0.1, 0.1, 0.1, 0.105]), _s(idx, [0.0, 1.5e9, 1.5e9, 1.6e9]), _s(idx, [1e6, 1e6, 1e6, 9e7]),
           pd.Series(dtype=float), pd.Series(dtype=float))
    px, mc, vol, hi, lo = chain(old, new, 24000.0, pd.Timestamp("2025-06-04"))
    assert list(px.round(6)) == [0.1, 0.1, 0.102, 0.105]
    assert list(mc) == [9e8, 1.5e9, 1.5e9, 1.6e9], "旧币市值 0 的日子取新币的(同一份供应)"
    assert list(vol) == [5e7, 5e7, 5e7, 9e7]
    assert round(hi.iloc[0], 6) == round(2500 / 24000, 6) and len(hi) == 3, "高低价同样换算,生效后新币没有就缺"


def test_chain_without_effective_day_switches_when_new_data_starts() -> None:
    old = (_s("2025-01-01", [2.0] * 5), _s("2025-01-01", [1e9] * 5), _s("2025-01-01", [1e8] * 5),
           pd.Series(dtype=float), pd.Series(dtype=float))
    new = (_s("2025-01-04", [2.1, 2.2]), _s("2025-01-04", [1.1e9, 1.2e9]), _s("2025-01-04", [9e7, 9e7]),
           pd.Series(dtype=float), pd.Series(dtype=float))
    px, *_ = chain(old, new, 1.0, None)
    assert list(px) == [2.0, 2.0, 2.0, 2.1, 2.2]


def test_token_on_labels_the_source_of_each_day() -> None:
    eff = {"SKY": pd.Timestamp("2025-09-01")}
    assert token_on("SKY", pd.Timestamp("2025-08-31"), eff) == "MKR÷24000"
    assert token_on("SKY", pd.Timestamp("2025-09-01"), eff) == "SKY"
    assert token_on("POL", pd.Timestamp("2024-01-01"), {"POL": None}) == "MATIC"
    assert token_on("BTC", pd.Timestamp("2025-01-01"), eff) is None


def test_zero_market_cap_is_flagged_not_silent() -> None:
    from src.data.cis.rebuild import crypto_market_data
    d = pd.Timestamp("2026-10-10")
    px = _s("2026-09-01", [1.0] * 40)
    md, miss = crypto_market_data(px, _s("2026-09-01", [0.0] * 40), _s("2026-09-01", [1e6] * 40),
                                  _s("2026-09-01", [1.1] * 40), _s("2026-09-01", [0.9] * 40), d, {"total_supply": 100})
    assert md is not None and "market_cap" in miss


def test_universe_lists_sky_not_mkr() -> None:
    from src.data.cis.cis_provider import ASSETS_CONFIG
    assert "SKY" in ASSETS_CONFIG and ASSETS_CONFIG["SKY"]["coingecko"] == "sky" and "MKR" not in ASSETS_CONFIG


def test_overlay_retires_old_code_and_adds_official_only_names() -> None:
    from src.data.cis.official import overlay
    live = {"universe": [{"symbol": "MKR", "cis_score": 55.8, "signal": "NEUTRAL"},
                         {"symbol": "BTC", "cis_score": 70.0, "signal": "OUTPERFORM"}]}
    row = lambda s, sc, sig: {"symbol": s, "asset_class": "RWA", "cis_score": sc, "regime_adjusted_score": sc,  # noqa: E731
                              "grade": "B", "signal": sig, "watch": None, "pct": 0.5, "pillar_f": 1, "pillar_m": 2,
                              "pillar_o": 3, "pillar_s": 4, "pillar_a": 5, "regime": "RISK_ON", "missing": []}
    latest = {"d": "2026-10-11", "code_ref": "x", "published_at": "t",
              "rows": {"BTC": row("BTC", 60.0, "NEUTRAL"), "SKY": row("SKY", 52.0, "NEUTRAL")}}
    out = overlay(live, latest, names={"SKY": "Sky (prev. Maker)"})
    syms = [a["symbol"] for a in out["universe"]]
    assert syms == ["BTC", "SKY"], "MKR 让位给 SKY;SKY 由正式行补进来"
    sky = out["universe"][1]
    assert sky["name"] == "Sky (prev. Maker)" and sky["signal_basis"] == "daily_close" and sky["intraday"] is None
    assert out["official"]["retired"] == ["MKR->SKY"] and out["official"]["covered"] == 2


def test_prev_levels_prefer_published_and_fill_from_rebuild() -> None:
    from src.data.cis.official import merge_prev
    off = [{"symbol": "BTC", "signal": "OUTPERFORM"}, {"symbol": "MKR", "signal": "UNDERWEIGHT"}]
    reb = [{"symbol": "BTC", "signal_pct": "NEUTRAL"}, {"symbol": "SKY", "signal_pct": "UNDERPERFORM"}]
    assert merge_prev(off, reb) == {"BTC": 3, "MKR": 0, "SKY": 1}
