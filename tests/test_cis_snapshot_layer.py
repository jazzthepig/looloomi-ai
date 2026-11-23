"""正式 CIS 的第二层兜底:行情快照的收盘批次,只补「库里没有任何场所价」的名字(S-909 / T-432)。

停供期间 HYPE / SKY 在正式档里一行都没有(币安没有它们)。第二层用 `market_snapshot` 里标了 `close_of` 的那一批补。
这份测试钉住的是**边界**:只补缺、已有来源的名字逐字节不动、门不过不补、来源写进行里、回看价走旁路不塞日子。
不接 BTC 占比和供给上限 —— 理由是量出来的,写在 `cg_less_fallback` 的注释和台账 S-909 里;这里钉住「确实没接」。
"""
from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.cis import cg_less_fallback as fb  # noqa: E402
from src.data.cis.cis_provider import ASSETS_CONFIG  # noqa: E402

END = pd.Timestamp("2026-11-23")
SINCE = pd.Timestamp("2026-11-20")
CG_LAST = pd.Timestamp("2026-11-19")
VENUE = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOT", "NEAR", "SUI", "APT", "ARB", "OP", "LINK", "UNI", "AAVE"]
NO_VENUE = ["HYPE", "SKY"]
SYMS = VENUE + NO_VENUE


def _world(n: int = 120, slope: float = 0.002, vix: float = 20.0):
    """CG 到 11-19;币安(16 个名字)到 11-23;HYPE / SKY 币安没有。`slope` < 0 ⇒ 一路跌。"""
    days = pd.date_range(END - pd.Timedelta(days=n - 1), END, freq="D")
    cg_days = [d for d in days if d <= CG_LAST]
    crypto, static, raw_px, raw_vol, supply, funding = {}, {}, {}, {}, {}, {}
    truth = {}
    for i, s in enumerate(SYMS):
        px = pd.Series({d: 10.0 * (i + 1) * (1 + slope * k) for k, d in enumerate(days)}, dtype=float)
        truth[s] = px
        cg_px = px.reindex(cg_days)
        crypto[s] = (cg_px, cg_px * 1e8, pd.Series({d: 4e8 for d in cg_days}, dtype=float), px * 1.02, px * 0.98)
        static[s] = {"total_supply": None, "max_supply": None}
        cid = ASSETS_CONFIG[s]["coingecko"]
        supply[cid] = {days[0]: (1e8, 1.5e8)}
        funding[s] = {d: 0.0001 for d in days}
        if s in VENUE:
            raw_px[s] = px
            raw_vol[s] = pd.Series({d: 4e8 / 10.0 for d in days}, dtype=float) / px
    assets = {s: {"class": ASSETS_CONFIG[s]["class"], "coingecko": ASSETS_CONFIG[s]["coingecko"]} for s in SYMS}
    data = {"crypto": crypto, "tradfi": {}, "tvl": {}, "funding": funding, "static": static, "static_tf": {},
            "macro": {"fng": {d: 30 for d in days}, "vix": {d: vix for d in days}, "total_mcap": {}},
            "fundamentals": {}, "github": {}, "migration_eff": {}}
    raw = {"px": raw_px, "vol": raw_vol, "supply": supply}
    sym2cg = {s: ASSETS_CONFIG[s]["coingecko"] for s in SYMS}
    return assets, data, raw, sym2cg, truth


def _batch(truth, day: pd.Timestamp, off_pct: float = 0.05, drop: tuple = (), pct24=0.2, pct7=1.4):
    """`day` 的收盘批次:每个名字的价 = 真值 ×(1 + off%)。"""
    rows = {}
    for s in SYMS:
        if s in drop:
            continue
        p = float(truth[s].get(day)) * (1 + off_pct / 100.0)
        rows[s] = {"symbol": s, "price": p, "market_cap": p * 1.2e8, "volume_24h": 5e8, "pct_24h": pct24, "pct_7d": pct7,
                   "max_supply": 2e8, "total_supply": 1.5e8, "circulating_supply": 1.2e8}
    ts = (day + pd.Timedelta(days=1, seconds=17)).isoformat() + "+00:00"
    return {"ts": ts, "rows": rows,
            "global": {"symbol": "_GLOBAL", "market_cap": 2.1e12, "btc_dominance": 58.9, "volume_24h": 8e10}}


def _run(closes, since=SINCE, end=END):
    assets, data, raw, sym2cg, truth = _world()
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=end, since=since)
    base = copy.deepcopy(d)
    cl = closes(truth) if callable(closes) else closes
    layer = fb.apply_snapshot(d, assets, cl, raw, sym2cg, rep, end, since)
    return assets, d, base, rep, layer, truth


def _same(a: pd.Series, b: pd.Series) -> bool:
    return a.index.equals(b.index) and bool(((a == b) | (a.isna() & b.isna())).all())


# ── 只补缺 ────────────────────────────────────────────────────────────────────

def test_only_names_without_any_venue_price_are_filled():
    assets, d, base, rep, layer, truth = _run(lambda t: {"2026-11-23": _batch(t, END)})
    assert rep["no_fallback_price"] == NO_VENUE and layer["targets"] == NO_VENUE
    assert set(layer["filled"]) == set(NO_VENUE) and all(list(v) == ["2026-11-23"] for v in layer["filled"].values())
    for s in NO_VENUE:
        px = d["crypto"][s][0]
        assert abs(px.get(END) / truth[s].get(END) - 1) < 0.001
        assert px.get(pd.Timestamp("2026-11-21")) is None, "没有收盘批次的日子就是没有,不塞"
        assert d["crypto"][s][1].get(END) == 1e8 * px.get(END), "市值 = 日表的流通量 × 价(与另外的名字同一个式子)"
        assert d["crypto"][s][2].get(END) == 5e8


def test_names_that_already_have_a_source_are_untouched_byte_for_byte():
    """② 的边界:23 个名字的价、市值、成交额一格不动;全市场市值与静态供给量也不动。"""
    assets, d, base, rep, layer, truth = _run(lambda t: {"2026-11-23": _batch(t, END, off_pct=0.4)})
    for s in VENUE:
        for i in range(5):
            assert _same(d["crypto"][s][i], base["crypto"][s][i]), (s, i)
    assert d["static"] == base["static"], "上限 / 总量:第二层不碰(CMC 的上限口径与 CG 不同,见模块注释)"
    assert d["macro"]["total_mcap"] == {}, "全市场市值 / BTC 占比:不接"
    assert "macro.total_mcap" in rep["batch_missing"]
    assert all("max_supply" in rep["missing_dimensions"][s] for s in SYMS)


def test_a_day_that_already_has_a_price_is_not_overwritten():
    """CG 回来之后(那一天序列里已经有价)第二层不再碰它。"""
    assets, data, raw, sym2cg, truth = _world()
    d = copy.deepcopy(data)
    px, mc, vol, h, l = d["crypto"]["HYPE"]
    d["crypto"]["HYPE"] = (fb._set_day(px, END, 123.0), fb._set_day(mc, END, 9e9), fb._set_day(vol, END, 7e8), h, l)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    layer = fb.apply_snapshot(d, assets, {"2026-11-23": _batch(truth, END)}, raw, sym2cg, rep, END, SINCE)
    assert d["crypto"]["HYPE"][0].get(END) == 123.0 and "HYPE" not in layer["filled"] and "SKY" in layer["filled"]


def test_batches_outside_the_window_are_ignored():
    def closes(t):
        return {"2026-11-19": _batch(t, CG_LAST), "2026-11-23": _batch(t, END),
                "2026-11-24": _batch({s: t[s].reindex(t[s].index.union([END + pd.Timedelta(days=1)])).ffill() for s in SYMS},
                                     END + pd.Timedelta(days=1))}
    assets, d, base, rep, layer, _ = _run(closes)
    assert sorted(layer["days"]) == ["2026-11-23"], "停供起点之前、打分日之后的批次都不看"


# ── 门 ────────────────────────────────────────────────────────────────────────

def test_gate_refuses_a_batch_that_is_not_at_the_close():
    assets, d, base, rep, layer, _ = _run(lambda t: {"2026-11-23": _batch(t, END, off_pct=2.5)})
    assert layer["filled"] == {} and "2026-11-23" in layer["skipped"] and "不像是收盘" in layer["skipped"]["2026-11-23"]
    assert layer["days"]["2026-11-23"]["gate"]["median_abs_pct"] == 2.5
    for s in NO_VENUE:
        assert _same(d["crypto"][s][0], base["crypto"][s][0])


def test_gate_waits_when_the_venue_closes_have_not_landed():
    """零点刚过,币安当天的收盘还没采到 ⇒ 没有可比的 ⇒ 这一轮不补(不拿没核过的价去发)。"""
    assets, data, raw, sym2cg, truth = _world()
    raw["px"] = {s: v[v.index < END] for s, v in raw["px"].items()}
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    layer = fb.apply_snapshot(d, assets, {"2026-11-23": _batch(truth, END)}, raw, sym2cg, rep, END, SINCE)
    g = layer["days"]["2026-11-23"]["gate"]
    assert layer["filled"] == {} and g["n"] == 0 and not g["ok"] and "还没到齐" in layer["skipped"]["2026-11-23"]


def test_gate_does_not_compare_the_names_it_is_about_to_fill():
    assets, data, raw, sym2cg, truth = _world()
    b = _batch(truth, END)
    crypto = {s: (truth[s],) for s in SYMS}
    g = fb.close_gate(b["rows"], crypto, END, frozenset(NO_VENUE))
    assert g["ok"] and g["n"] == len(VENUE) and g["median_abs_pct"] == 0.05 and g["worst"] in VENUE


def test_a_name_missing_from_the_batch_is_named_not_invented():
    assets, d, base, rep, layer, _ = _run(lambda t: {"2026-11-23": _batch(t, END, drop=("SKY",))})
    assert set(layer["filled"]) == {"HYPE"} and layer["no_row"] == {"2026-11-23": ["SKY"]}


# ── 回看价走旁路 ──────────────────────────────────────────────────────────────

def test_lookbacks_come_from_the_vendor_change_without_adding_days():
    assets, d, base, rep, layer, truth = _run(lambda t: {"2026-11-23": _batch(t, END, pct24=3.0, pct7=-5.0)})
    lb = d["lookback_px"]["HYPE"]
    p = d["crypto"]["HYPE"][0].get(END)
    assert abs(lb[pd.Timestamp("2026-11-22")] - p / 1.03) < 1e-9, "24h 回看 = 对方自己报的涨跌倒推"
    assert pd.Timestamp("2026-11-16") not in lb, "7 天前序列里有价(CG)⇒ 用序列的,不用倒推的"
    assert layer["filled"]["HYPE"]["2026-11-23"]["lookback"] == {"24h": "cmc_pct", "7d": "series", "30d": "series"}
    assert d["crypto"]["HYPE"][0].get(pd.Timestamp("2026-11-22")) is None, "倒推出来的价不进序列"


def test_market_data_uses_the_side_channel_only_for_changes():
    from src.data.cis.rebuild import crypto_market_data
    days = pd.date_range("2026-10-01", "2026-11-19", freq="D")
    px = pd.Series({d: 100.0 for d in days}, dtype=float)
    px.loc[END] = 110.0
    mc, vol = px * 1e6, px * 0 + 1e6
    args = (px, mc, vol, px * 1.01, px * 0.99, END, {"total_supply": 2e6})
    md0, _ = crypto_market_data(*args)
    md1, _ = crypto_market_data(*args, {pd.Timestamp("2026-11-22"): 100.0})
    assert md0["change_24h"] == 0.0 and abs(md1["change_24h"] - 10.0) < 1e-9
    assert md1["change_7d"] == md0["change_7d"] and abs(md0["change_7d"] - 10.0) < 1e-9 and md1["price"] == md0["price"]
    assert crypto_market_data(*args, None)[0] == md0, "不给旁路 ⇒ 与原来相同"
    assert crypto_market_data(px, mc, vol, px, px, pd.Timestamp("2026-11-22"), {}, {pd.Timestamp("2026-11-22"): 100.0})[0] is None, \
        "旁路价不能让一个没有行情的日子变成有行"


# ── 走真的打分:补回来的两行、另外的名字不变、来源在行里 ─────────────────────────

def _score(with_layer: bool):
    from src.data.cis.rebuild import score_day
    assets, data, raw, sym2cg, truth = _world()
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    if with_layer:
        fb.apply_snapshot(d, assets, {"2026-11-23": _batch(truth, END, pct24=0.2, pct7=1.4)}, raw, sym2cg, rep, END, SINCE)
    rows = fb.annotate_rows(score_day(END, assets, d), rep)
    return {r["symbol"]: r for r in rows}, rep


def test_the_two_names_come_back_and_nobody_else_moves():
    off, _ = _score(False)
    on, rep = _score(True)
    assert set(off) == set(VENUE) and set(on) == set(SYMS)
    for s in VENUE:
        a, b = off[s], on[s]
        for k in ("pillar_f", "pillar_o", "pillar_s", "pillar_a", "inputs", "missing"):
            assert a[k] == b[k], (s, k)
    # M 支柱里有「同组 30 日涨跌中位数」这一项:组里多了两个名字,中位数可能动 —— 这是多了两个成员,不是换了源
    moved = [s for s in VENUE if off[s]["pillar_m"] != on[s]["pillar_m"]]
    assert all(ASSETS_CONFIG[s]["class"] in {ASSETS_CONFIG[x]["class"] for x in NO_VENUE} for s in moved), moved


def test_filled_rows_say_where_every_number_came_from():
    on, rep = _score(True)
    h = on["HYPE"]["inputs"]
    assert h["px_source"] == fb.SNAP_SOURCE and h["vol_source"] == fb.SNAP_SOURCE
    assert h["mcap_source"] == "circulating_supply_x_close"
    assert h["snapshot_ts"].startswith("2026-11-24T00:00:17") and h["lookback"]["24h"] == "cmc_pct"
    assert h["supply_asof"] == "2026-07-27", "市值用的流通量是哪天的快照,写在行里"
    assert h["btc_dom"] is None, "占比没接"
    assert "max_supply" in on["HYPE"]["missing"], "上限没接,照实标缺"
    b = on["BTC"]["inputs"]
    assert b["px_source"] == fb.PRICE_SOURCE and "snapshot_ts" not in b and "lookback" not in b, "不是第二层补的行一个键都不加"


def test_preview_shows_the_rows_before_they_are_published():
    on, rep = _score(True)
    pv = fb.snapshot_preview(list(on.values()), rep, "2026-11-23")
    assert set(pv["filled"]) == set(NO_VENUE) and pv["day"]["gate"]["ok"] and pv["skipped"] is None
    assert pv["filled"]["HYPE"]["f"] == on["HYPE"]["pillar_f"] and pv["filled"]["HYPE"]["score"] == on["HYPE"]["score"]
    import json
    json.dumps(pv)                                           # 要进 loop_attempt.detail,必须能序列化
    assert fb.snapshot_preview(list(on.values()), {"enabled": True}, "2026-11-23") is None


def test_regime_is_not_moved_by_the_vendor_dominance():
    """量出来的事(S-909):状态判定里只有一处用 BTC 占比 —— `vix > 27 and btc_30d < -5 and bdom > 58` ⇒ Stagflation。
    11-22:VIX 35.9、BTC 30 日 −24.5%,前两个条件都成立;我们一直用的口径占比 56.3,CMC 的是 58.9,门槛夹在中间。
    这里把那个局面搭出来:第二层开着,状态不变、占比仍是缺;而谁要是把对方的全市场市值递进去,状态当场变成 STAGFLATION。"""
    from src.data.cis.rebuild import score_day
    assets, data, raw, sym2cg, truth = _world(slope=-0.004, vix=35.9)
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    r0 = {r["symbol"]: r for r in score_day(END, assets, copy.deepcopy(d))}
    assert r0["BTC"]["inputs"]["chg30"] < -5 and r0["BTC"]["inputs"]["vix"] > 27, "前两个条件要先成立,这条测试才测到东西"
    fb.apply_snapshot(d, assets, {"2026-11-23": _batch(truth, END)}, raw, sym2cg, rep, END, SINCE)
    r1 = {r["symbol"]: r for r in score_day(END, assets, d)}
    assert r1["BTC"]["regime"] == r0["BTC"]["regime"] != "STAGFLATION" and r1["BTC"]["inputs"]["btc_dom"] is None
    hazard = copy.deepcopy(d)
    hazard["macro"]["total_mcap"][END] = r1["BTC"]["inputs"]["mcap"] / 0.589        # 对方口径的占比 58.9
    r2 = {r["symbol"]: r for r in score_day(END, assets, hazard)}
    assert r2["BTC"]["regime"] == "STAGFLATION", "这就是不接的理由:换一家的定义,状态就变了"
    hazard["macro"]["total_mcap"][END] = r1["BTC"]["inputs"]["mcap"] / 0.563        # 我们一直用的口径 56.3
    r3 = {r["symbol"]: r for r in score_day(END, assets, hazard)}
    assert r3["BTC"]["regime"] == r0["BTC"]["regime"], "原口径下占比在门槛另一侧,与「缺」的判定相同"


# ── 接线与开关 ────────────────────────────────────────────────────────────────

def _wire(monkeypatch, closes, raises=False):
    assets, data, raw, sym2cg, truth = _world()
    import src.data.market.market_snapshot as ms
    monkeypatch.setattr(fb, "enabled", lambda today=None: True)
    monkeypatch.setattr(fb, "sym2cg_map", lambda: sym2cg)

    async def load_raw(_):
        return raw

    seen = {}

    async def close_batches(since, until=None, source="coinmarketcap"):
        seen["args"] = (since, until)
        if raises:
            raise RuntimeError("HTTP 500")
        return closes(truth)

    monkeypatch.setattr(fb, "load_raw", load_raw)
    monkeypatch.setattr(ms, "close_batches", close_batches)
    return assets, data, seen


def test_apply_if_enabled_runs_the_second_layer(monkeypatch):
    monkeypatch.delenv(fb.SNAPSHOT_ENV, raising=False)
    assets, data, seen = _wire(monkeypatch, lambda t: {"2026-11-23": _batch(t, END)})
    out, rep = asyncio.run(fb.apply_if_enabled(assets, copy.deepcopy(data), END))
    assert seen["args"] == (fb.OUTAGE[0], "2026-11-23") and set(rep["snapshot_layer"]["filled"]) == set(NO_VENUE)
    assert out["crypto"]["HYPE"][0].get(END) is not None


def test_switch_off_means_the_layer_is_never_read(monkeypatch):
    monkeypatch.setenv(fb.SNAPSHOT_ENV, "0")
    assets, data, seen = _wire(monkeypatch, lambda t: {"2026-11-23": _batch(t, END)})
    out, rep = asyncio.run(fb.apply_if_enabled(assets, copy.deepcopy(data), END))
    assert "args" not in seen and "snapshot_layer" not in rep and out["crypto"]["HYPE"][0].get(END) is None


def test_unreadable_batches_fill_nothing_and_say_so(monkeypatch):
    monkeypatch.delenv(fb.SNAPSHOT_ENV, raising=False)
    assets, data, seen = _wire(monkeypatch, lambda t: {}, raises=True)
    out, rep = asyncio.run(fb.apply_if_enabled(assets, copy.deepcopy(data), END))
    assert "读不到" in rep["snapshot_layer"]["error"] and out["crypto"]["HYPE"][0].get(END) is None
    assert fb.snapshot_preview([], rep, "2026-11-23")["error"]


def test_official_and_loop_carry_the_preview():
    off = (ROOT / "src/data/cis/official.py").read_text(encoding="utf-8")
    assert off.count('"snapshot_layer": preview') == 1 and 'out_ret["snapshot_layer"] = preview' in off
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    seg = main[main.index("async def _cis_official_loop"):main.index("async def _start_cis_official_loop")]
    assert '_detail["snapshot_layer"]' in seg, "发布前要在循环的记录里看得见"


def test_market_cap_falls_back_to_the_vendor_only_when_we_have_no_supply():
    assets, data, raw, sym2cg, truth = _world()
    raw["supply"].pop(ASSETS_CONFIG["SKY"]["coingecko"])
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    layer = fb.apply_snapshot(d, assets, {"2026-11-23": _batch(truth, END)}, raw, sym2cg, rep, END, SINCE)
    assert layer["filled"]["SKY"]["2026-11-23"]["mcap_source"] == fb.SNAP_SOURCE
    assert layer["filled"]["HYPE"]["2026-11-23"]["mcap_source"] == "circulating_supply_x_close"
    assert d["crypto"]["SKY"][1].get(END) == d["crypto"]["SKY"][0].get(END) * 1.2e8


def test_supply_snapshot_after_the_day_is_not_used():
    """PIT:打分日之后才有的流通量快照不拿来算那一天的市值。"""
    assets, data, raw, sym2cg, truth = _world()
    cid = ASSETS_CONFIG["HYPE"]["coingecko"]
    raw["supply"][cid] = {END + pd.Timedelta(days=2): (9e8, 1e9)}
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=END, since=SINCE)
    layer = fb.apply_snapshot(d, assets, {"2026-11-23": _batch(truth, END)}, raw, sym2cg, rep, END, SINCE)
    assert layer["filled"]["HYPE"]["2026-11-23"]["mcap_source"] == fb.SNAP_SOURCE
