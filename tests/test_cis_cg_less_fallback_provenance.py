"""T-422 补:兜底接管时,**来源要标在行里**(不只是在运行日志里)。

为什么这道测试存在:

`cis_official_daily` 是**只追加 + 不可改**的表(触发器 `cis_official_daily_no_change`
拒 UPDATE/DELETE)⇒ **发出去的档事后补不了标记**。
而兜底补出来的档**口径是真的不同**(T-422 卡量过:成交额差 6.5–34 倍、M 支柱低 ~24 分、
23 个加密名里 14 个等级会变)⇒ 不标出来,下游会把口径断读成真实变动。

⇒ 所以标记必须在**发布之前**就在行里。这一道测试钉住三件事:
  ① 报告里逐日记下「哪一天、哪一维是兜底供的」(口径断点);
  ② 行里的 `inputs` 带上来源键 —— **只在兜底供的那一天**,CG 的那天一个键都不加;
  ③ 没有兜底接管时,行**一个字节都不动**(开关关 ⇒ 与今天逐字节相同)。
"""
from __future__ import annotations

import copy

import pandas as pd

from src.data.cis import cg_less_fallback as fb

D = pd.Timestamp("2026-11-19")
SYMS = ["BTC", "ETH"]


def _fixture(n_cg: int = 10, n_all: int = 12):
    """CG 只到倒数第二天,兜底(Binance)到今天 —— 就是现在这个停订的样子。"""
    days = pd.date_range(D - pd.Timedelta(days=n_all - 1), D, freq="D")
    cg_days = days[:n_cg]
    crypto, static = {}, {}
    raw_px, raw_vol, supply = {}, {}, {}
    for i, s in enumerate(SYMS):
        base = 100.0 * (i + 1)
        px_cg = pd.Series({d: base * (1 + 0.001 * k) for k, d in enumerate(cg_days)}, dtype=float)
        px_fb = pd.Series({d: base * (1 + 0.001 * k) for k, d in enumerate(days)}, dtype=float)
        crypto[s] = (px_cg, px_cg * 1e9,
                      pd.Series({d: 5e6 * (i + 1) for d in cg_days}, dtype=float),
                      px_cg * 1.02, px_cg * 0.98)
        static[s] = {"total_supply": 1e9 * (i + 1), "max_supply": 2e9 * (i + 1)}
        raw_px[s] = px_fb
        raw_vol[s] = pd.Series({d: 5e6 * (i + 1) for d in days}, dtype=float) / px_fb
        supply[s.lower()] = {d: (1e9 * (i + 1), 1e9 * (i + 1)) for d in days}
    assets = {s: {"class": "Crypto"} for s in SYMS}
    data = {"crypto": crypto, "static": static,
            "macro": {"total_mcap": {d: 3.0e12 for d in days}}}
    raw = {"px": raw_px, "vol": raw_vol, "supply": supply}
    sym2cg = {s: s.lower() for s in SYMS}
    return assets, data, raw, sym2cg, days


def _applied():
    assets, data, raw, sym2cg, days = _fixture()
    d = copy.deepcopy(data)
    rep = fb.apply(d, assets, raw, sym2cg, end=D, force=False)
    return rep, days


# ── ① 报告里逐日记下口径断点 ──────────────────────────────────────────────

def test_report_records_the_break_point_per_dimension():
    rep, days = _applied()
    want = [str(days[-2].date()), str(days[-1].date())]
    for s in SYMS:
        assert rep["fb_days"][s]["price"] == want, rep["fb_days"][s]
        assert rep["fb_days"][s]["mcap"] == want
        assert rep["fb_days"][s]["volume"] == want


def test_report_fb_days_empty_when_cg_never_missing():
    """CG 覆盖全部日期 ⇒ 兜底一天都不用供 ⇒ 没有断点。"""
    assets, data, raw, sym2cg, days = _fixture(n_cg=12, n_all=12)
    rep = fb.apply(copy.deepcopy(data), assets, raw, sym2cg, end=D, force=False)
    assert rep["fb_days"] == {} or all(not v for v in rep["fb_days"].values())


# ── ② 行里带来源标记(只在兜底供的那天) ────────────────────────────────────

def test_annotate_marks_only_the_takeover_days():
    rep, days = _applied()
    rows = [
        {"symbol": "BTC", "d": str(days[-1].date()), "missing": [], "inputs": {"price": 1.0}},
        {"symbol": "BTC", "d": str(days[0].date()), "missing": [], "inputs": {"price": 1.0}},
    ]
    out = fb.annotate_rows(rows, rep)
    assert out[0]["inputs"]["px_source"] == "binance_hist"
    assert out[0]["inputs"]["vol_source"] == "volume_x_close"
    assert out[0]["inputs"]["mcap_source"] == "circulating_supply_x_close"
    # CG 供的那天 —— 一个来源键都不加(加了就是把 CG 的行说成兜底的行)
    assert set(out[1]["inputs"]) == {"price"}


def test_annotate_tolerates_rows_without_inputs():
    rep, _days = _applied()
    rows = [{"symbol": "BTC", "d": "2026-11-19", "missing": []}]
    out = fb.annotate_rows(rows, rep)
    assert out[0]["missing"] == ["max_supply"]


# ── ③ 没有兜底接管 ⇒ 一个字节都不动 ──────────────────────────────────────

def test_no_report_changes_nothing():
    rows = [{"symbol": "BTC", "d": "2026-11-19", "missing": [], "inputs": {"price": 1.0}}]
    before = copy.deepcopy(rows)
    assert fb.annotate_rows(rows, None) is rows
    assert rows == before


# ── ④ 标记进得了只追加的正式表 ────────────────────────────────────────────

def test_marker_survives_into_the_official_row():
    """正式档的行由 `official_rows` 造 ⇒ `inputs` 原样带过去 ⇒ 标记进得了表。"""
    from src.data.cis.official import official_rows
    rows = [{"symbol": "BTC", "asset_class": "Crypto", "d": "2026-11-21",
             "raw_score": 70.0, "score": 70.0, "grade": "B", "pct": None,
             "pillar_f": 1.0, "pillar_m": 1.0, "pillar_o": 1.0, "pillar_s": 1.0, "pillar_a": 1.0,
             "regime": "RISK_OFF", "missing": [],
             "inputs": {"price": 1.0, "px_source": "binance_hist"}}]
    out = official_rows(rows, {}, "2026-11-22T00:00:00Z")
    assert out[0]["inputs"]["px_source"] == "binance_hist"
    assert out[0]["inputs"]["price"] == 1.0
