"""T-422:CG-less 兜底(默认关)。

三条性质(卡上的验收):
1. **开关关 ⇒ 与今天逐字节相同**(不动 data 的任何一维、不加任何标注)。
2. **开关开 + CG 那条路模拟成取不到 ⇒ 兜底接管**,价 / 市值 / 总量都有值,
   `miss` 里只剩如实该缺的(max_supply 等)。
3. **变异测试**:把兜底的某一维改成 0 ⇒ 分数必须变(否则那一维是装饰品)。

真实数据那一条(拿 2026-11-19 的真实输入跑)在有凭证时自动跑;没有凭证就跳过 ——
夹具那三条永远跑。
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from src.data.cis import cg_less_fallback as fb

D = pd.Timestamp("2026-11-19")
REAL_PICKLE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t422/data_2026-11-19.pkl")
CRYPTO_SYMS = ["BTC", "ETH", "SOL", "AAVE", "LINK", "UNI"]


def _tradfi_syms(n: int = 5) -> list[str]:
    from src.data.cis.rebuild import TRADFI
    from src.data.cis.cis_provider import ASSETS_CONFIG
    return [s for s, v in ASSETS_CONFIG.items() if v["class"] in TRADFI][:n]


def _fixture():
    """一套形状与 load_inputs 一致的合成输入(不联网)。"""
    from src.data.cis.cis_provider import ASSETS_CONFIG
    from src.data.cis.rebuild import TRADFI
    tf = _tradfi_syms()
    syms = CRYPTO_SYMS + tf
    assets = {s: {"class": ASSETS_CONFIG[s]["class"], "coingecko": ASSETS_CONFIG[s].get("coingecko")}
              for s in syms}
    days = pd.date_range(D - pd.Timedelta(days=120), D, freq="D")
    crypto, tradfi, static, static_tf, funding = {}, {}, {}, {}, {}
    raw_px, raw_vol, supply = {}, {}, {}
    for i, s in enumerate(CRYPTO_SYMS):
        base = 100.0 * (i + 1)
        px = pd.Series({d: base * (1.0 + 0.001 * k) for k, d in enumerate(days)}, dtype=float)
        mc = px * 1e9
        vol = pd.Series({d: 5e6 * (i + 1) for d in days}, dtype=float)
        hi = px * 1.02
        lo = px * 0.98
        crypto[s] = (px, mc, vol, hi, lo)
        static[s] = {"total_supply": 1e9 * (i + 1), "max_supply": 2e9 * (i + 1)}
        funding[s] = {d: 0.0001 for d in days}
        cg_id = ASSETS_CONFIG[s].get("coingecko") or s.lower()
        # 兜底原料:Binance 收盘比 CG 高 0.1%;供给量 = 市值 / 价格
        fb_px = px * 1.001
        raw_px[s] = fb_px
        raw_vol[s] = vol / px
        supply[cg_id] = {d: (1e9 * (i + 1), 1e9 * (i + 1)) for d in days}
    for i, s in enumerate(tf):
        px = pd.Series({d: 100.0 * (i + 1) * (1.0 + 0.0005 * k) for k, d in enumerate(days)}, dtype=float)
        tradfi[s] = (px, px * 1.01, px * 0.99, pd.Series({d: 1e6 for d in days}, dtype=float))
        static_tf[s] = {"market_cap": 1e11 * (i + 1), "price": float(px.iloc[-1])}
    macro = {"fng": {d: 42 for d in days}, "vix": {d: 19.0 for d in days}, "total_mcap": {d: 3.0e12 for d in days}}
    data = {"crypto": crypto, "tradfi": tradfi, "tvl": {}, "macro": macro, "funding": funding,
            "static": static, "static_tf": static_tf, "fundamentals": {}, "github": {}, "migration_eff": {}}
    raw = {"px": raw_px, "vol": raw_vol, "supply": supply}
    sym2cg = {s: (ASSETS_CONFIG[s].get("coingecko") or s.lower()) for s in CRYPTO_SYMS}
    return assets, data, raw, sym2cg


def _rows(assets, data) -> list[dict]:
    from src.data.cis.rebuild import score_day
    return score_day(D, assets, data)


def _fb_rows(assets, data, raw, sym2cg, force: bool = True):
    """跑一次兜底(就地改 data),返回 (行, 改过的 data, 报告)。"""
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=D, force=force)
    return fb.annotate_rows(_rows(assets, d), rep), d, rep


def _jsonable(o):
    """dict 的键可能是 pd.Timestamp —— json 不接受,先统一转成 str。"""
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if o is None or isinstance(o, (str, int, float, bool)):
        return o
    return str(o)


def _rows_after_fb(assets, data, raw, sym2cg, force: bool = True):
    """兜底跑一遍(就地改 data 的副本),返回 score_day 的行。"""
    d = copy.deepcopy(data)
    fb.apply(d, assets, raw, sym2cg, end=D, force=force)
    return _rows(assets, d)


def _digest(rows: list[dict]) -> str:
    return json.dumps(_jsonable(rows), sort_keys=True)


# ── ① 开关关 ⇒ 逐字节相同 ────────────────────────────────────────────────

def test_switch_off_touches_nothing(monkeypatch):
    monkeypatch.delenv(fb.ENABLE_ENV, raising=False)
    assets, data, raw, sym2cg = _fixture()
    before = copy.deepcopy(data)
    out, report = _run_apply_if_enabled(assets, data)
    assert report is None
    assert "cg_less_fallback" not in out
    assert _digest(out) == _digest(before)


def test_annotate_rows_is_noop_without_report():
    rows = [{"symbol": "BTC", "asset_class": "L1", "missing": []}]
    assert fb.annotate_rows(rows, None) == rows
    assert rows[0]["missing"] == []


def test_switch_off_real_data_is_byte_identical():
    """拿 2026-11-19 的真实输入跑:开关关时 load_inputs 的输出与落盘快照逐字节相同。"""
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")):
        pytest.skip("没有凭证 —— 真实数据那一条跳过(夹具那几条永远跑)")
    if not REAL_PICKLE.exists():
        pytest.skip(f"没有落盘快照:{REAL_PICKLE}")
    import asyncio
    import pickle

    from src.data.cis.rebuild import load_inputs

    with open(REAL_PICKLE, "rb") as f:
        snap = pickle.load(f)
    assets, data = asyncio.run(load_inputs(D))
    assert set(data.keys()) == set(snap["data"].keys())
    for k in ("crypto", "tradfi", "static", "macro", "funding", "tvl"):
        if k in ("macro", "funding", "tvl"):
            assert data[k] == snap["data"][k], f"{k} 不一致"
        else:
            assert set(data[k].keys()) == set(snap["data"][k].keys()), f"{k} 的名字集合不一致"
    assert _digest(_rows(assets, data)) == _digest(_rows(snap["assets"], snap["data"]))


# ── ② 开关开 + CG 取不到 ⇒ 兜底接管 ─────────────────────────────────────

def test_fallback_takes_over_and_fills():
    assets, data, raw, sym2cg = _fixture()
    rep = fb.apply(data, assets, raw, sym2cg, end=D, force=True)
    assert set(rep["took_over"]) == set(CRYPTO_SYMS)
    assert rep["still_missing"] == []
    for s in CRYPTO_SYMS:
        px, mc, vol, hi, lo = data["crypto"][s]
        i = CRYPTO_SYMS.index(s)
        assert abs(float(px.iloc[-1]) - float(raw["px"][s].iloc[-1])) < 1e-9      # 价 = 兜底价
        assert float(mc.iloc[-1]) > 0                                             # 市值有值
        assert abs(float(mc.iloc[-1]) - float(raw["px"][s].iloc[-1]) * 1e9 * (i + 1)) < 1e-3
        assert float(vol.iloc[-1]) > 0                                            # 成交额有值
        assert data["static"][s]["total_supply"] > 0                              # 总量有值
    # 如实该缺的:max_supply 没有库内来源 ⇒ 保持 None,并在报告里点名
    assert all(v["max_supply"] is None for v in data["static"].values())
    assert set(rep["no_max_supply"]) == set(CRYPTO_SYMS)
    # 夹具里全市场市值有值 ⇒ 不是批次级缺
    assert rep["batch_missing"] == []


def test_batch_missing_marks_total_mcap():
    """全市场市值没有库内来源(CG 的)⇒ 缺就是缺,不许补 0(BTC 占比 / regime 会少一个输入)。"""
    assets, data, raw, sym2cg = _fixture()
    data["macro"]["total_mcap"] = {}          # 模拟 11-20 起 CG 死
    rep = fb.apply(data, assets, raw, sym2cg, end=D, force=True)
    assert "macro.total_mcap" in rep["batch_missing"]
    # 如实缺 ⇒ 不许用 0 假装有
    assert not data["macro"]["total_mcap"]


def test_fallback_marks_missing_rows():
    assets, data, raw, sym2cg = _fixture()
    rep = fb.apply(data, assets, raw, sym2cg, end=D, force=True)
    rows = fb.annotate_rows(_rows(assets, data), rep)
    for r in rows:
        if r["asset_class"] not in ("US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity"):
            assert "max_supply" in r["missing"]


def test_fallback_only_takes_over_when_cg_missing():
    """CG 有值的日子仍然走 CG(口径优先)—— 不许替换。"""
    assets, data, raw, sym2cg = _fixture()
    cg_px = data["crypto"]["BTC"][0]
    rep = fb.apply(data, assets, raw, sym2cg, end=D, force=False)
    assert rep["took_over"] == []
    assert float(data["crypto"]["BTC"][0].iloc[-1]) == float(cg_px.iloc[-1])


def test_fallback_respects_missing_price_honestly():
    """库里没有兜底价的名字 ⇒ 如实缺,不许补 0。"""
    assets, data, raw, sym2cg = _fixture()
    raw["px"].pop("LINK")
    raw["vol"].pop("LINK")
    # force=True(模拟「CG 那条路整个取不到」)⇒ LINK 就是没有,不保留 CG 的值
    rep = fb.apply(data, assets, raw, sym2cg, end=D, force=True)
    assert "LINK" in rep["no_fallback_price"]
    assert len(data["crypto"]["LINK"][0]) == 0
    assert len(data["crypto"]["LINK"][1]) == 0
    # force=False(CG 那边还有值)⇒ 保留 CG 的值,兜底不接管
    _, data2, raw2, sym2cg2 = _fixture()
    raw2["px"].pop("LINK")          # 兜底这一维对 LINK 也没有 ⇒ 如实报告
    raw2["vol"].pop("LINK")
    rep2 = fb.apply(data2, assets, raw2, sym2cg2, end=D, force=False)
    assert "LINK" in rep2["no_fallback_price"]
    assert "LINK" not in rep2["took_over"]
    assert float(data2["crypto"]["LINK"][1].iloc[-1]) > 0


# ── ③ 变异测试:某一维改成 0 ⇒ 分数必须变 ─────────────────────────────────

def test_mutation_price_zero_is_detected(monkeypatch):
    assets, data, raw, sym2cg = _fixture()
    base = _rows_after_fb(assets, data, raw, sym2cg)
    mut_raw = copy.deepcopy(raw)
    for s in mut_raw["px"]:
        mut_raw["px"][s] = mut_raw["px"][s] * 0.0
    mut = _rows_after_fb(assets, data, mut_raw, sym2cg)
    assert _digest(base) != _digest(mut), "把兜底价改成 0 没有改变输出 ⇒ 那一维是装饰品"


def test_mutation_mcap_zero_is_detected():
    assets, data, raw, sym2cg = _fixture()
    base = _rows_after_fb(assets, data, raw, sym2cg)
    mut_raw = copy.deepcopy(raw)
    for cid in mut_raw["supply"]:
        mut_raw["supply"][cid] = {d: (0.0, v[1]) for d, v in mut_raw["supply"][cid].items()}
    mut = _rows_after_fb(assets, data, mut_raw, sym2cg)
    assert _digest(base) != _digest(mut), "把兜底流通量改成 0 没有改变输出 ⇒ 那一维是装饰品"
    # 且市值确实塌成 0 ⇒ F 支柱的规模项掉下去
    b = {r["symbol"]: r for r in base}
    m = {r["symbol"]: r for r in mut}
    assert m["BTC"]["inputs"]["mcap"] == 0
    assert m["BTC"]["pillar_f"] < b["BTC"]["pillar_f"]


def test_mutation_total_supply_zero_is_detected():
    """total_supply 补 0 ⇒ fdv 与 supply_ratio 一起塌(卡上点名的那个坑)。"""
    assets, data, raw, sym2cg = _fixture()
    base = _rows_after_fb(assets, data, raw, sym2cg)
    mut_raw = copy.deepcopy(raw)
    for cid in mut_raw["supply"]:
        mut_raw["supply"][cid] = {d: (v[0], 0.0) for d, v in mut_raw["supply"][cid].items()}
    mut = _rows_after_fb(assets, data, mut_raw, sym2cg)
    b = {r["symbol"]: r for r in base}
    m = {r["symbol"]: r for r in mut}
    assert m["BTC"]["pillar_f"] < b["BTC"]["pillar_f"], "total_supply 补 0 没有压低 F 支柱"


# ── 工具 ────────────────────────────────────────────────────────────────

def _run_apply_if_enabled(assets, data):
    import asyncio

    async def _go():
        return await fb.apply_if_enabled(assets, data, D)
    return asyncio.run(_go())


# ── 真实数据(2026-11-19):开关关 ⇒ 逐字节相同;开关开 ⇒ 确实接管 ────────────

def _http_get(table: str, qs: str) -> list[dict]:
    """读库(只读)。翻页带 order= ⇒ 边界不漂;每页最多 1000 行。"""
    import urllib.request

    url = os.environ["SUPABASE_URL"].rstrip("/") + f"/rest/v1/{table}?"
    hdr = {"apikey": os.environ["SUPABASE_KEY"],
           "Authorization": f"Bearer {os.environ['SUPABASE_KEY']}"}
    rows: list[dict] = []
    off = 0
    while True:
        req = urllib.request.Request(f"{url}{qs}&limit=1000&offset={off}", headers=hdr)
        with urllib.request.urlopen(req, timeout=60) as resp:
            page = json.loads(resp.read().decode())
        rows.extend(page)
        if len(page) < 1000:
            return rows
        off += 1000


def _series(rows: list[dict], key: str, val: str, want: str) -> pd.Series:
    out = {}
    for r in rows:
        if str(r.get(key)) != want or r.get(val) is None:
            continue
        out[pd.Timestamp(str(r["d" if "d" in r else "trade_date"])[:10])] = float(r[val])
    return pd.Series(out, dtype=float).sort_index()


def _real_data():
    """真实 2026-11-19 的加密四维(CG 口径)+ 兜底原料(Binance 日线 + 供给量)。"""
    from src.data.cis.cis_provider import ASSETS_CONFIG
    from src.data.cis.rebuild import TRADFI

    syms = [s for s, v in ASSETS_CONFIG.items() if v["class"] not in TRADFI]
    cg_ids = sorted({ASSETS_CONFIG[s]["coingecko"] for s in syms if ASSETS_CONFIG[s].get("coingecko")})
    in_syms = ",".join(syms)
    in_cg = ",".join(cg_ids)
    frm = "2026-07-01"
    px_rows = _http_get("ohlcv_daily", f"select=symbol,trade_date,close,high,low,volume&source=eq.binance_hist"
                                       f"&symbol=in.({in_syms})&trade_date=gte.{frm}&order=symbol.asc,trade_date.asc")
    cg_rows = _http_get("asset_mcap_daily", f"select=coin_id,d,price,mcap,volume&source=eq.coingecko_pro_market_chart"
                                            f"&coin_id=in.({in_cg})&d=gte.{frm}&order=coin_id.asc,d.asc")
    sup_rows = _http_get("coin_supply_daily", f"select=coin_id,d,total_supply,circulating_supply"
                                               f"&d=gte.{frm}&order=coin_id.asc,d.asc")
    crypto, static, raw_px, raw_vol, supply = {}, {}, {}, {}, {}
    for s in syms:
        cg_id = ASSETS_CONFIG[s].get("coingecko")
        if not cg_id:
            continue
        cpx = _series([r for r in cg_rows if str(r["coin_id"]) == cg_id], "coin_id", "price", cg_id)
        cmc = _series([r for r in cg_rows if str(r["coin_id"]) == cg_id], "coin_id", "mcap", cg_id)
        cvol = _series([r for r in cg_rows if str(r["coin_id"]) == cg_id], "coin_id", "volume", cg_id)
        bpx = _series([r for r in px_rows if str(r["symbol"]) == s], "symbol", "close", s)
        bhi = _series([r for r in px_rows if str(r["symbol"]) == s], "symbol", "high", s)
        blo = _series([r for r in px_rows if str(r["symbol"]) == s], "symbol", "low", s)
        bvol = _series([r for r in px_rows if str(r["symbol"]) == s], "symbol", "volume", s)
        crypto[s] = (cpx, cmc, cvol, bhi, blo)
        static[s] = {"total_supply": None, "max_supply": None}
        raw_px[s] = bpx
        raw_vol[s] = bvol
        days = {}
        for r in sup_rows:
            if str(r["coin_id"]) != cg_id or r.get("circulating_supply") is None:
                continue
            days[pd.Timestamp(str(r["d"])[:10])] = (float(r["circulating_supply"]),
                                                   float(r["total_supply"]) if r.get("total_supply") is not None else None)
        supply[cg_id] = days
    assets = {s: {"class": ASSETS_CONFIG[s]["class"], "coingecko": ASSETS_CONFIG[s].get("coingecko")}
              for s in crypto}
    data = {"crypto": crypto, "tradfi": {}, "tvl": {}, "macro": {"fng": {}, "vix": {}, "total_mcap": {}},
            "funding": {}, "static": static, "static_tf": {}, "fundamentals": {}, "github": {},
            "migration_eff": {}}
    sym2cg = {s: ASSETS_CONFIG[s].get("coingecko") for s in crypto}
    return assets, data, {"px": raw_px, "vol": raw_vol, "supply": supply}, sym2cg


def test_real_data_switch_off_is_byte_identical():
    """真实 2026-11-19 数据:开关关 ⇒ data 与 score_day 的输出一个字节都不变。"""
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")):
        pytest.skip("没有凭证")
    assets, data, raw, sym2cg = _real_data()
    before = copy.deepcopy(data)
    rows_before = _rows(assets, data)
    out, report = _run_apply_if_enabled(assets, data)
    assert report is None, "开关关时不该有接管报告"
    assert "cg_less_fallback" not in out
    assert _digest(_jsonable(data)) == _digest(_jsonable(before)), "开关关时 data 变了"
    assert _digest(_rows(assets, data)) == _digest(rows_before), "开关关时 score_day 的输出变了"


def test_real_data_switch_on_actually_takes_over(monkeypatch):
    """同一份真实数据:开关开 + CG 那条路模拟取不到 ⇒ 兜底真的接管(不是装饰品)。"""
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")):
        pytest.skip("没有凭证")
    assets, data, raw, sym2cg = _real_data()
    rows_before = _rows(assets, data)
    monkeypatch.setenv(fb.ENABLE_ENV, "1")
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=D, force=True)
    assert rep["took_over"], "开关开后兜底没有接管任何一个名字"
    for s in rep["took_over"]:
        px, mc, vol, _, _ = d["crypto"][s]
        assert float(px.iloc[-1]) > 0, f"{s} 兜底价没有值"
        assert float(mc.iloc[-1]) > 0, f"{s} 兜底市值没有值"
        assert float(vol.iloc[-1]) > 0, f"{s} 兜底成交额没有值"
        assert (d["static"][s].get("total_supply") or 0) > 0, f"{s} total_supply 没有补上"
    # 接管 ⇒ 输出必须变(否则那一维是装饰品)
    assert _digest(_rows(assets, d)) != _digest(rows_before)
