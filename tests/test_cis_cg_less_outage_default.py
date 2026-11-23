"""S-900:CG 停供期间正式 CIS 恢复按日发布 —— 兜底在登记的停供窗内默认开、只接停供起的日子、成交量按币校准。

钉住的是 11-23 量到的三件事:
1. 「默认关、要有人去配变量」⇒ 装上两天没人开,正式档停了四天 ⇒ 没设开关时窗内默认开。
2. 开关一开,原实现会拿 Binance 去补任何一个 CG 没有的历史日 ⇒ 只接 `since` 起的日子。
3. Binance 单所量比 CG 全市场量小 6–24 倍 ⇒ M 支柱低 14–37 分 ⇒ 按币校准,来源与比值写进行里。
另:CG live 一空,**没有兜底价的名字**(HYPE / SKY)历史上每一天的 F 支柱都被写低 ⇒ 总量照样从日表补。
"""
from __future__ import annotations

import asyncio
import copy
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.cis import cg_less_fallback as fb  # noqa: E402

END = pd.Timestamp("2026-11-22")
SINCE = pd.Timestamp("2026-11-20")
SYMS = ["BTC", "ETH", "HYPE"]


def _fixture(n: int = 60, scale: float = 12.0, cg_hole: bool = True, cg_static: bool = False):
    """CG 到 11-19(中间故意缺一天),Binance 到 11-22、量是 CG 的 1/scale;HYPE 在 Binance 没有。"""
    days = pd.date_range(END - pd.Timedelta(days=n - 1), END, freq="D")
    cg_days = [d for d in days if d < SINCE]
    hole = cg_days[10]
    crypto, static, raw_px, raw_vol, supply = {}, {}, {}, {}, {}
    for i, s in enumerate(SYMS):
        base = 100.0 * (i + 1)
        px = pd.Series({d: base * (1 + 0.001 * k) for k, d in enumerate(days)}, dtype=float)
        cg_px = px.reindex([d for d in cg_days if not (cg_hole and d == hole)])
        cg_vol = pd.Series({d: 6e8 * (i + 1) for d in cg_px.index}, dtype=float)
        crypto[s] = (cg_px, cg_px * 1e9, cg_vol, px * 1.02, px * 0.98)
        static[s] = ({"total_supply": 1e9 * (i + 1), "max_supply": 2e9 * (i + 1)} if cg_static
                     else {"total_supply": None, "max_supply": None})
        supply[s.lower()] = {days[0]: (1e9 * (i + 1), 1.5e9 * (i + 1))}
        if s != "HYPE":
            raw_px[s] = px
            raw_vol[s] = pd.Series({d: 6e8 * (i + 1) / scale for d in days}, dtype=float) / px
    assets = {s: {"class": "L1"} for s in SYMS}
    data = {"crypto": crypto, "static": static, "macro": {"total_mcap": {}}}
    raw = {"px": raw_px, "vol": raw_vol, "supply": supply}
    return assets, data, raw, {s: s.lower() for s in SYMS}, days, hole


def test_default_is_on_inside_the_registered_outage_and_off_outside(monkeypatch) -> None:
    monkeypatch.delenv(fb.ENABLE_ENV, raising=False)
    assert not fb.enabled(date(2026, 11, 19)), "停供前一天:CG 还有数,不该默认开"
    assert fb.enabled(date(2026, 11, 20)) and fb.enabled(date(2026, 11, 23)) and fb.enabled(date(2026, 12, 1))
    assert fb.enabled(date(2026, 12, 8)), "恢复后 7 天回填宽限内仍开(没回填到的日子还要兜底供)"
    assert not fb.enabled(date(2026, 12, 9)), "宽限过了默认关 —— 不让一个临时措施悄悄变成常态"
    monkeypatch.setenv(fb.ENABLE_ENV, "0")
    assert not fb.enabled(date(2026, 11, 23)), "显式关要听"
    monkeypatch.setenv(fb.ENABLE_ENV, "1")
    assert fb.enabled(date(2027, 1, 1)), "显式开要听"


def test_outage_window_is_the_same_one_the_forward_books_registered() -> None:
    from src.data.universe.state_book import OUTAGE_BACKFILL_DAYS, SOURCE_OUTAGES
    cg = [o for o in SOURCE_OUTAGES if "CoinGecko" in o[2]]
    assert len(cg) == 1
    last_good, back = date.fromisoformat(cg[0][0]), cg[0][1]
    assert fb.OUTAGE[1] == back, "两处登记的恢复日不一样 ⇒ 一边以为源回来了、另一边还在兜底"
    assert (date.fromisoformat(fb.OUTAGE[0]) - last_good).days == 1, "这里记第一个没数的日子,纸面账记最后一个有数的日子"
    assert fb.OUTAGE_GRACE_DAYS == OUTAGE_BACKFILL_DAYS


def test_since_keeps_the_fallback_out_of_history() -> None:
    assets, data, raw, sym2cg, days, hole = _fixture()
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    for s in ("BTC", "ETH"):
        px = d["crypto"][s][0]
        assert hole not in px.index, "CG 历史上缺的那一天被 Binance 补上了 ⇒ 开关一开就改写历史"
        assert rep["fb_days"][s]["price"] == ["2026-11-20", "2026-11-21", "2026-11-22"]
        assert rep["sources"][s]["from"] == "2026-11-20"
    # 对照:不给 since(原实现)⇒ 那一天会被补 —— 这条测试钉的就是这个差别
    d2 = copy.deepcopy(data)
    fb.apply(d2, assets, raw, sym2cg, end=END)
    assert hole in d2["crypto"]["BTC"][0].index


def test_volume_is_scaled_by_the_trailing_median_ratio_and_says_so() -> None:
    assets, data, raw, sym2cg, days, _ = _fixture(scale=12.0)
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    for i, s in enumerate(("BTC", "ETH")):
        vol = d["crypto"][s][2]
        assert abs(rep["vol_cal"][s]["ratio"] - 12.0) < 1e-6 and rep["vol_cal"][s]["n"] == fb.VOL_CAL_WINDOW
        assert rep["vol_cal"][s]["to"] == "2026-11-19", "比值只用兜底开始供量之前的共有日"
        assert abs(float(vol[END]) - 6e8 * (i + 1)) < 1.0, "校准后应回到 CG 的量级"
        assert abs(float(vol[days[5]]) - 6e8 * (i + 1)) < 1e-6, "CG 供的日子一个数都不动"
        assert rep["sources"][s]["volume"] == fb.VOL_SOURCE_CAL
    rows = [{"symbol": "BTC", "d": "2026-11-22", "missing": [], "inputs": {"price": 1.0}},
            {"symbol": "BTC", "d": "2026-11-19", "missing": [], "inputs": {"price": 1.0}}]
    out = fb.annotate_rows(rows, rep)
    assert out[0]["inputs"]["vol_source"] == "binance_hist_x_cg_ratio" and out[0]["inputs"]["vol_ratio"] == 12.0
    assert out[0]["inputs"]["px_source"] == "binance_hist"
    assert set(out[1]["inputs"]) == {"price"}, "CG 供的那天一个来源键都不加"
    # 不校准(对照)⇒ 量小一个数量级
    d2 = copy.deepcopy(data)
    rep2 = fb.apply(d2, assets, raw, sym2cg, end=END, since=SINCE, calibrate=False)
    assert abs(float(d2["crypto"]["BTC"][2][END]) - 6e8 / 12.0) < 1.0 and not rep2["vol_cal"]


def test_too_few_overlap_days_means_no_scaling_and_it_is_named() -> None:
    assets, data, raw, sym2cg, days, _ = _fixture(n=fb.VOL_CAL_MIN + 2, cg_hole=False)   # 共有日 = MIN − 1
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    assert rep["vol_cal"] == {} and set(rep["vol_uncalibrated"]) == {"BTC", "ETH"}
    out = fb.annotate_rows([{"symbol": "BTC", "d": "2026-11-22", "missing": [], "inputs": {}}], rep)
    assert out[0]["inputs"]["vol_source"] == "volume_x_close" and "vol_ratio" not in out[0]["inputs"]


def test_ratio_never_uses_days_after_the_fallback_started() -> None:
    cg = pd.Series({d: 100.0 for d in pd.date_range("2026-10-01", "2026-11-19")}, dtype=float)
    cg = pd.concat([cg, pd.Series({pd.Timestamp("2026-12-02"): 9999.0})])           # CG 恢复后新落的一天
    bn = pd.Series({d: 10.0 for d in pd.date_range("2026-10-01", "2026-12-02")}, dtype=float)
    r, n, to = fb.vol_ratio(cg, bn, before=SINCE)
    assert r == 10.0 and n == fb.VOL_CAL_WINDOW and to == pd.Timestamp("2026-11-19")
    assert fb.vol_ratio(cg, bn * 0.0, before=SINCE)[0] is None, "兜底量为 0 的日子不算共有日"
    assert fb.vol_ratio(None, bn)[0] is None


def test_a_name_without_fallback_price_still_gets_its_total_supply() -> None:
    assets, data, raw, sym2cg, _, _ = _fixture()
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    assert rep["no_fallback_price"] == ["HYPE"]
    assert d["static"]["HYPE"]["total_supply"] == 1.5e9 * 3, "HYPE 没有兜底价,但总量在日表里 —— 不补 ⇒ 整段历史的 F 支柱被写低"
    assert d["static"]["HYPE"]["max_supply"] is None and rep["missing_dimensions"]["HYPE"] == ["max_supply"]
    assert len(d["crypto"]["HYPE"][0]) == len(data["crypto"]["HYPE"][0]), "CG 的历史价原样留着"
    assert d["static"]["BTC"]["total_supply"] == 1.5e9 and rep["missing_dimensions"]["BTC"] == ["max_supply"]


def test_max_supply_is_flagged_only_when_it_is_actually_missing() -> None:
    assets, data, raw, sym2cg, _, _ = _fixture(cg_static=True)                       # CG 回来了,live 有上限
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    assert rep["missing_dimensions"]["BTC"] == [] and d["static"]["BTC"]["max_supply"] == 2e9
    out = fb.annotate_rows([{"symbol": "BTC", "d": "2026-11-22", "missing": [], "inputs": {}}], rep)
    assert out[0]["missing"] == []


def test_apply_if_enabled_passes_the_outage_start(monkeypatch) -> None:
    assets, data, raw, sym2cg, _, hole = _fixture()
    monkeypatch.delenv(fb.ENABLE_ENV, raising=False)
    monkeypatch.setattr(fb, "enabled", lambda today=None: True)
    monkeypatch.setattr(fb, "sym2cg_map", lambda: sym2cg)

    async def load_raw(_):
        return raw
    monkeypatch.setattr(fb, "load_raw", load_raw)
    out, rep = asyncio.run(fb.apply_if_enabled(assets, copy.deepcopy(data), END))
    assert rep["since"] == fb.OUTAGE[0] and hole not in out["crypto"]["BTC"][0].index
    assert out["cg_less_fallback"] is rep


def test_scaled_volume_moves_the_score_back_toward_the_cg_scale() -> None:
    """用真的 score_day:同一天,校准前后 M 支柱差一截 —— 校准不是装饰品。"""
    from src.data.cis.cis_provider import ASSETS_CONFIG
    from src.data.cis.rebuild import score_day
    syms = ["BTC", "ETH", "SOL"]
    days = pd.date_range(END - pd.Timedelta(days=119), END, freq="D")
    cg_days = [d for d in days if d < SINCE]
    crypto, static, raw_px, raw_vol, supply, funding = {}, {}, {}, {}, {}, {}
    for i, s in enumerate(syms):
        px = pd.Series({d: 100.0 * (i + 1) * (1 + 0.001 * k) for k, d in enumerate(days)}, dtype=float)
        cg_px = px.reindex(cg_days)
        crypto[s] = (cg_px, cg_px * 1e9, pd.Series({d: 3e9 for d in cg_days}, dtype=float), px * 1.02, px * 0.98)
        static[s] = {"total_supply": None, "max_supply": None}
        cid = ASSETS_CONFIG[s]["coingecko"]
        supply[cid] = {days[0]: (1e9, 1.2e9)}
        raw_px[s] = px
        raw_vol[s] = pd.Series({d: 3e9 / 15.0 for d in days}, dtype=float) / px
        funding[s] = {d: 0.0001 for d in days}
    assets = {s: {"class": ASSETS_CONFIG[s]["class"], "coingecko": ASSETS_CONFIG[s]["coingecko"]} for s in syms}
    data = {"crypto": crypto, "tradfi": {}, "tvl": {}, "funding": funding, "static": static, "static_tf": {},
            "macro": {"fng": {d: 30 for d in days}, "vix": {d: 20.0 for d in days}, "total_mcap": {}},
            "fundamentals": {}, "github": {}, "migration_eff": {}}
    raw = {"px": raw_px, "vol": raw_vol, "supply": supply}
    sym2cg = {s: ASSETS_CONFIG[s]["coingecko"] for s in syms}
    m = {}
    for cal in (True, False):
        d = copy.deepcopy(data)
        fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE, calibrate=cal)
        rows = {r["symbol"]: r for r in score_day(END, assets, d)}
        assert set(rows) == set(syms), "停供后的日子三个名字都要有行"
        m[cal] = rows["BTC"]
    assert abs(m[True]["inputs"]["volume"] - 3e9) < 1.0 and abs(m[False]["inputs"]["volume"] - 2e8) < 1.0
    assert m[True]["pillar_m"] - m[False]["pillar_m"] > 5, "量差 15 倍,M 支柱应差出几分"
    assert "total_supply" not in (m[True].get("missing") or []), "总量从日表补上了"


def test_circulating_supply_is_flagged_only_for_days_the_fallback_prices() -> None:
    """供给量日表 11-10 才开始。原来看整段历史 ⇒ 每个名字每一天都被标「缺流通量」,连 CG 供市值的那三年也是。"""
    assets, data, raw, sym2cg, days, _ = _fixture()
    late = SINCE - pd.Timedelta(days=5)
    for cid in raw["supply"]:
        raw["supply"][cid] = {late: raw["supply"][cid][days[0]]}            # 快照只从停供前 5 天起
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    assert rep["missing_dimensions"]["BTC"] == ["max_supply"], "兜底供市值的三天都有快照 ⇒ 不该标缺流通量"
    assert float(d["crypto"]["BTC"][1][END]) > 0
    for cid in raw["supply"]:
        raw["supply"][cid] = {END + pd.Timedelta(days=1): (1e9, 1e9)}        # 快照都在打分日之后 ⇒ 兜底那几天没有流通量
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    assert "circulating_supply" in rep["missing_dimensions"]["BTC"], "真缺的时候要标"
