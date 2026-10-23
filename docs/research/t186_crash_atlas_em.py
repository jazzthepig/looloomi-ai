#!/usr/bin/env python3
"""T-186 崩盘图谱 · 新兴市场(B 道)—— 台账 S-675。

崩盘两类,分开报:
  ① EEM 股票熊市 / 急跌(yfinance 2015-07 → eodhd 2022-08 拼接)
  ② EM 货币危机(美元兑 KRW / BRL / MXN / INR,63 个日历日升值 ≥ 15%)

协议内核(阈值、窗口、锚点、种子 675、零分布 2,000 次)一律 import `crash_atlas_common`,本脚本不改一个字。
需要而内核没有的函数(拼接、迹象定义、分位组切分)都写在本文件里,报告「协议问题 / 自建函数」一节列出。

读库:publishable key,只读;翻页必带 order=。
输出:docs/research/t186_results.json(每个锚点、每个迹象的原始命中都在里面,能复算)。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crash_atlas_common as K  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t186_results.json")
SPLIT_DATE = "2022-08-31"          # ETF 拼接分界(协议:之前 yfinance、之后 eodhd)
FX = {"KRW": "DEXKOUS", "BRL": "DEXBZUS", "MXN": "DEXMXUS", "INR": "DEXINUS"}
FX_FLAT = ["DEXKOUS", "DEXBZUS", "DEXMXUS", "DEXINUS"]
CCY = list(FX.keys())
ETF_FLAT = ["EWZ", "FXI", "INDA", "VWO"]

RES: dict[str, Any] = {"protocol": "S-675", "task": "T-186", "lane": "B (EM)",
                       "split_date": SPLIT_DATE, "seed": K.SEED, "n_shift": 2000}


# ── 读库(只读 publishable key;翻页必带 order=)────────────────────────────────
def q_ohlcv(symbol: str, source: str) -> pd.Series:
    """一个 symbol+source 的收盘序列。Range 翻页,每页都带 order=(T-170 / T-173 实测:不带会漏键)。"""
    url = os.environ["SUPABASE_URL"] + "/rest/v1/ohlcv_daily"
    hdr = {"apikey": os.environ["SUPABASE_KEY"], "Authorization": "Bearer " + os.environ["SUPABASE_KEY"]}
    # 注意:Range 头与 limit 查询参数不能同时给 —— 第 2 页起 PostgREST 返回 416 / PGRST103
    # ("Limit should be greater than or equal to zero"),第一页却正常返回,极易误判成「只有一页」。
    params = {"select": "trade_date,close", "symbol": "eq." + symbol, "source": "eq." + source,
              "order": "trade_date.asc"}
    out: list[tuple[str, float]] = []
    lo = 0
    while True:
        r = requests.get(url, params=params, headers={**hdr, "Range": f"{lo}-{lo + 999}"}, timeout=120)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        out.extend((x["trade_date"], x["close"]) for x in rows)
        if len(rows) < 1000:
            break
        lo += 1000
    s = pd.Series([c for _, c in out], index=pd.to_datetime([d for d, _ in out]), name=symbol + "/" + source)
    return s.dropna().sort_index()


def stitch(symbol: str, eodhd_only: bool = False) -> tuple[pd.Series, dict[str, Any]]:
    """ETF 拼接:2022-08-31 前 yfinance、之后 eodhd。拼之前报重叠段日收益相关与水平比。
    eodhd_only=True 用于协议点名的 SPY / QQQ(它们的 eodhd 2015-01 起,全段用 eodhd)。"""
    yf, eo = q_ohlcv(symbol, "yfinance"), q_ohlcv(symbol, "eodhd")
    if eodhd_only:
        diag = {"note": "eodhd full range (protocol: SPY/QQQ 全段 eodhd)", "eo_n": int(len(eo)),
                "yf_n": int(len(yf)),
                "ret_corr": float(yf.pct_change().reindex(eo.index).corr(eo.pct_change()))
                if len(eo.index.intersection(yf.index)) > 5 else None,
                "stitched_n": int(len(eo)), "stitched_start": str(eo.index[0].date()),
                "stitched_end": str(eo.index[-1].date())}
        return eo.rename(symbol), diag
    if yf.empty:
        return eo, {"note": "no yfinance, eodhd only"}
    if eo.empty:
        return yf, {"note": "no eodhd, yfinance only"}
    ov = yf.index.intersection(eo.index)
    ry, re_ = yf.pct_change().loc[ov], eo.pct_change().loc[ov]
    diag = {"overlap_n": int(len(ov)),
            "overlap_start": str(ov[0].date()) if len(ov) else None,
            "overlap_end": str(ov[-1].date()) if len(ov) else None,
            "ret_corr": float(ry.corr(re_)) if len(ov) > 5 else None,
            "level_ratio_eodhd_over_yf": float(eo.loc[ov[-1]] / yf.loc[ov[-1]]) if len(ov) else None,
            "yf_n": int(len(yf)), "eo_n": int(len(eo))}
    cut = pd.Timestamp(SPLIT_DATE)
    keep_yf = yf[yf.index <= cut]
    keep_eo = eo[eo.index > cut]
    s = pd.concat([keep_yf, keep_eo]).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    diag["stitched_n"] = int(len(s))
    diag["stitched_start"] = str(s.index[0].date())
    diag["stitched_end"] = str(s.index[-1].date())
    return s.rename(symbol), diag


# ── 迹象:内核没有的构造写在这里(协议给的定义,内核只给分位与打分)───────────────
def rv20(p: pd.Series) -> pd.Series:
    """20 日实现波动(年化 %,用日收益的 std × √252)。"""
    return p.pct_change().rolling(20).std() * np.sqrt(252) * 100


def ma200(p: pd.Series) -> pd.Series:
    return p.rolling(200).mean()


def hi52w(p: pd.Series) -> pd.Series:
    return p.rolling(252).max()


def cal(x: pd.Series, days: int = 7) -> pd.Series:
    return K.to_calendar(x, max_gap_days=days)


def lag_cal(x: pd.Series, days: int) -> pd.Series:
    """日历日序列回看 days 天(cal 之后的索引是完整日历日,shift 行数 = shift 日历日)。"""
    return cal(x).shift(days)


def bmask(cond: pd.Series, *refs: pd.Series) -> pd.Series:
    """布尔条件 → 1.0 / 0.0,任何一个输入缺值那天记 NaN(缺值不算「亮」也不算「不亮」)。
    refs 的索引先对齐到 cond(参照序列常常是日历日的,cond 是交易日的)。"""
    out = pd.Series(np.where(cond, 1.0, 0.0), index=cond.index, dtype=float)
    for r in refs:
        out[r.reindex(cond.index).isna()] = np.nan
    return out


def build_signals(eem: pd.Series, spy: pd.Series) -> dict[str, dict[str, Any]]:
    """协议 S-675 的 22 个迹象:价格 P1–P5(EEM 上)、全球宏观 M1–M13、EM 专属 E1–E4。
    返回 {name: {"on": 日历日布尔序列, "note": ..., "src": ...}};低频序列一律先过 available()。"""
    S: dict[str, dict[str, Any]] = {}

    def add(name, on, src, note=""):
        S[name] = {"on": cal(pd.Series(on, dtype="float")), "src": src, "note": note}

    # P —— EEM 价格本身
    r252 = eem / eem.shift(252) - 1.0
    p1 = K.expanding_pct(r252)
    add("P1", bmask(p1 >= 0.9, p1), "EEM 252 日收益的按时点分位 ≥ 0.9")
    ext = eem / ma200(eem) - 1.0
    p2 = K.expanding_pct(ext)
    add("P2", bmask(p2 >= 0.9, p2), "EEM / MA200 − 1 的分位 ≥ 0.9")
    vol = rv20(eem)
    p3 = K.expanding_pct(vol)
    add("P3", bmask(p3 <= 0.1, p3), "EEM 20 日实现波动分位 ≤ 0.1")
    add("P4", bmask(p3 >= 0.9, p3), "EEM 20 日实现波动分位 ≥ 0.9")
    fromhi = eem / hi52w(eem) - 1.0
    above = eem > ma200(eem)
    add("P5", bmask((fromhi <= -0.05) & above, fromhi, ma200(eem)),
        "离 52 周高点 ≥ 5% 但仍在 200 日线上")

    # M —— 全球宏观(低频先 available();全部先落成日历日序列,再算条件,
    # 否则周频 / 交易日的两条序列比较会抛 "Can only compare identically-labeled Series objects")
    dff = cal(K.load_fred("DFF"))
    l365 = dff.shift(365)
    add("M1", bmask((dff - l365) >= 1.0, l365), "联邦基金利率 12 个月升 ≥ 1pp")
    t2 = cal(K.load_fred("T10Y2Y"))
    add("M2", bmask(t2 < 0, t2), "10Y−2Y < 0")
    inv365 = (t2 < 0).rolling(365, min_periods=1).max()
    add("M3", bmask((t2 > 0) & (inv365 > 0), t2), "10Y−2Y > 0 且过去 365 天倒挂过")
    nfci = cal(K.available(K.load_fred("NFCI"), "NFCI"))
    add("M4", bmask(nfci > 0, nfci), "NFCI > 0")
    baa = cal(K.load_fred("BAA10Y") - K.load_fred("DGS10"))
    l63b = baa.shift(63)
    add("M5", bmask((baa - l63b) >= 0.5, l63b), "Baa−10Y 利差 63 天升 ≥ 0.5pp")
    vix = cal(K.load_fred("VIXCLS"))
    add("M6", bmask(vix < 13, vix), "VIX < 13")
    add("M7", bmask(vix > 30, vix), "VIX > 30")
    vxv = cal(K.load_fred("VXVCLS"))
    add("M8", bmask((vix / vxv) > 1.0, vxv), "VIX / VXV > 1")
    dtw = cal(K.load_fred("DTWEXBGS"))
    l63d = dtw.shift(63)
    add("M9", bmask(K.expanding_pct(dtw / l63d - 1.0) >= 0.9, l63d),
        "美元广义指数 63 天变化分位 ≥ 0.9")
    wti = cal(K.load_fred("DCOILWTICO"))
    l126 = wti.shift(126)
    add("M10", bmask((wti / l126 - 1.0) >= 0.50, l126), "WTI 126 天涨 ≥ 50%")
    walcl = cal(K.available(K.load_fred("WALCL"), "WALCL"))
    l91w = walcl.shift(91)
    add("M11", bmask(walcl < l91w, l91w), "美联储资产负债表 91 天缩")
    uc = cal(K.available(K.load_fred("UMCSENT"), "UMCSENT"))
    add("M12", bmask(K.expanding_pct(uc) >= 0.8, uc), "密歇根消费者信心分位 ≥ 0.8")
    ic = cal(K.available(K.load_fred("ICSA"), "ICSA"))
    ic4 = ic.rolling(20, min_periods=13).mean()           # 4 周均值(周频,5 个交易日/周)
    l91i = ic4.shift(91)                                  # 协议写 13 周;周频序列用 91 天落地
    add("M13", bmask((ic4 / l91i - 1.0) >= 0.15, l91i),
        "初请 4 周均值 13 周(91 天)升 ≥ 15%")

    # E —— EM 专属
    # 方向:协议写的是「美元升值 ≥ X」=「本币贬值」= DEX **涨** ≥ 1/(1−X) − 1。
    # 直接对 DEX 取负向门槛会把「本币升值」当成危机(KRW 1998 年 2 月的反弹就会被记成一次「危机」)。
    parts = []
    for c, sid in FX.items():
        d = cal(K.load_fred(sid))
        l63c = d.shift(63)
        parts.append(bmask((d / l63c - 1.0) >= 1.0 / 0.90 - 1.0, l63c).rename(c))
    e1 = pd.concat(parts, axis=1).max(axis=1, skipna=True)
    add("E1", e1, "KRW/BRL/MXN/INR 任一 63 天贬 ≥ 10%(DEX 涨 ≥ 1/0.9 − 1 = 11.11%)")
    cny = cal(K.load_fred("DEXCHUS"))
    l21c = cny.shift(21)
    add("E2", bmask((cny / l21c - 1.0) >= 1.0 / 0.98 - 1.0, l21c),
        "人民币 21 天贬 ≥ 2%(DEX 涨 ≥ 1/0.98 − 1 = 2.04%)")
    vxeem = cal(K.load_fred("VXEEMCLS"))
    add("E3", bmask(vxeem > 30, vxeem), "VXEEM > 30")
    ec, sc = cal(eem), cal(spy)
    le, ls = ec.shift(63), sc.shift(63)
    rel63 = (ec / le) / (sc / ls) - 1.0
    add("E4", bmask(rel63 <= -0.10, le, ls), "EEM 相对 SPY 63 天 ≤ −10%")
    return S


# ── 迹象对锚点(协议口径的统计全部走内核 sign_lift;这里只补「哪个锚点亮了」与前后半)──
def per_anchor(on: pd.Series, anchors: list[pd.Timestamp], lookback: int) -> dict[str, Any]:
    """与 sign_lift 同一套口径重算一遍命中向量,只为把「哪个锚点亮了」落进结果 json
    (用内核自己的 _window_any,不另写滚动)。"""
    on = on.sort_index()
    first_ok = on.index[on.notna().values.argmax()] + pd.Timedelta(days=lookback)
    win = K._window_any(on, lookback)
    usable = [a for a in anchors if first_ok <= a <= on.index[-1]]
    if not usable:
        return {"hits": [], "usable": []}
    pos = on.index.get_indexer(usable)
    return {"usable": [str(pd.Timestamp(a).date()) for a in usable],
            "hits": [bool(x) for x in win.values[pos]]}


def half_split(on: pd.Series, anchors: list[pd.Timestamp], lookback: int) -> tuple[Optional[float], Optional[float]]:
    pa = per_anchor(on, anchors, lookback)
    u, h = pa["usable"], pa["hits"]
    if len(u) < 2:
        return (None, None)
    mid = (len(u) - 1) // 2 + 1
    a = sum(h[:mid]) / mid
    b = sum(h[mid:]) / max(1, len(h) - mid)
    return (a, b)


def main() -> None:
    # ── 数据
    eem, eem_diag = stitch("EEM")
    spy, spy_diag = stitch("SPY", eodhd_only=True)
    RES["stitch"] = {"EEM": eem_diag, "SPY": spy_diag}
    others = {}
    for s in ETF_FLAT + ["UUP", "GLD"]:
        ser, d = stitch(s)
        others[s] = ser
        RES["stitch"][s] = d

    # ── ① EEM 崩盘目录
    bears = K.bear_episodes(eem, 0.20)
    fasts = K.fast_crashes(eem, 14, 0.10, 60)
    RES["eem_bear_episodes"] = [{k: (str(v.date()) if isinstance(v, pd.Timestamp) else v)
                                 for k, v in ep.items()} for ep in bears]
    RES["eem_fast_crashes"] = [{k: (str(v.date()) if isinstance(v, pd.Timestamp) else v)
                                for k, v in f.items()} for f in fasts]

    # ── ② EM 货币危机(每个币种 fast_crashes(1/DEX, 63, 1−1/1.15, 180),合并后跨币种 180 天只算一次)
    thr = 1.0 - 1.0 / 1.15
    ccy_hits: dict[str, list[dict[str, Any]]] = {}
    for c, sid in FX.items():
        d = K.load_fred(sid)
        # 协议的「美元兑本币 63 天升值 ≥ 15%」= 本币价值跌 ≥ 13.04%,两者完全等价(卡上写法):
        # 取倒数 1/DEX 再找急跌。直接对 DEX 找下跌会把「本币升值」记成危机。
        ccy_hits[c] = K.fast_crashes(1.0 / d, 63, thr, 180)
    RES["fx_crashes_by_ccy"] = {c: [{k: (str(v.date()) if isinstance(v, pd.Timestamp) else v)
                                     for k, v in f.items()} for f in fs]
                                for c, fs in ccy_hits.items()}
    merged: list[dict[str, Any]] = []
    for c, fs in ccy_hits.items():
        for f in fs:
            merged.append({"ccy": c, "start_d": f["start_d"], "hit_d": f["hit_d"], "ret": f["ret"]})
    merged.sort(key=lambda x: (x["start_d"], x["ccy"]))
    keep: list[dict[str, Any]] = []
    for m in merged:
        if keep and (m["start_d"] - keep[-1]["start_d"]).days <= 180:
            keep[-1]["also"].append({"ccy": m["ccy"], "start_d": str(m["start_d"].date()),
                                     "hit_d": str(m["hit_d"].date()), "ret": m["ret"]})
        else:
            m["also"] = []
            keep.append(m)
    RES["fx_crashes_merged"] = [{"ccy": m["ccy"], "start_d": str(m["start_d"].date()),
                                 "hit_d": str(m["hit_d"].date()), "ret": m["ret"],
                                 "also": m["also"]} for m in keep]

    # ── 锚点组
    peaks = [ep["peak_d"] for ep in bears if ep["first_leg"]]
    all_peaks = [ep["peak_d"] for ep in bears]
    breaks = [ep["break_d"] for ep in bears]
    fstart = [f["start_d"] for f in fasts]
    xstart = [m["start_d"] for m in keep]
    xhit = [m["hit_d"] for m in keep]
    ANCH = {
        "eem_peak_first_leg_90d": (peaks, 90, "EEM", "主锚点:熊市新一轮顶,回看 90 天"),
        "eem_peak_all_90d": (all_peaks, 90, "EEM", "稳健性:全部熊市前高(含非 first_leg),90 天"),
        "eem_break_30d": (breaks, 30, "EEM", "辅:破位日,回看 30 天"),
        "eem_fast_30d": (fstart, 30, "EEM", "辅:急跌起点,回看 30 天"),
        "fx_start_30d": (xstart, 30, "FX", "辅:货币危机起点(start_d),回看 30 天"),
        "fx_hit_30d": (xhit, 30, "FX", "辅:货币危机命中日(hit_d),回看 30 天"),
    }
    RES["anchors"] = {k: [str(pd.Timestamp(a).date()) for a in v[0]] for k, v in ANCH.items()}

    # ── 迹象表
    sig = build_signals(eem, spy)
    RES["signals_meta"] = {k: {"src": v["src"]} for k, v in sig.items()}
    table: dict[str, dict[str, Any]] = {}
    for aname, (anc, look, kind, desc) in ANCH.items():
        rows = {}
        for sname, sv in sig.items():
            if sv["on"].dropna().empty:
                continue
            if sname.startswith("P") and kind != "EEM":
                continue                      # 协议:P1–P5 只在 EEM 锚点上算
            r = K.sign_lift(sv["on"], anc, look, n_shift=2000, seed=K.SEED)
            if r["n_anchors"] == 0:
                continue
            h1, h2 = half_split(sv["on"], anc, look)
            pa = per_anchor(sv["on"], anc, look)
            same = ((sname in ("P4", "P5") and kind == "EEM" and look == 30) or
                    (sname == "E1" and kind == "FX"))
            rows[sname] = {**r, "half1": h1, "half2": h2, "same_source": same,
                           "anchor_hits": pa}
            print(f"{aname:22s} {sname:4s} n={r['n_anchors']:2d} skip={r['n_skipped']:2d} "
                  f"hit={r['hit_rate']:.3f} base={r['base_rate']:.3f} "
                  f"lift={r['lift']:.2f} p50={r['null_p50']:.3f} pct={r['pctile']:.3f}", flush=True)
        table[aname] = rows
    RES["signal_table"] = table

    # ── 线索(协议门槛:分位 ≥ 0.95 且提升 ≥ 1.5 且锚点 ≥ 6 且前后两半都亮)
    clues = []
    for aname, rows in table.items():
        for sname, r in rows.items():
            if r["same_source"] or r["pctile"] is None or r["lift"] is None:
                continue
            if (r["pctile"] >= 0.95 and r["lift"] >= 1.5 and r["n_anchors"] >= 6
                    and r["half1"] is not None and r["half2"] is not None
                    and r["half1"] > r["base_rate"] and r["half2"] > r["base_rate"]):
                clues.append({"anchor_set": aname, "signal": sname, "hit_rate": r["hit_rate"],
                              "base_rate": r["base_rate"], "lift": r["lift"],
                              "pctile": r["pctile"], "n": r["n_anchors"]})
    RES["clues"] = clues

    # ── 情绪画像:VIX / VXEEM / UMCSENT 在 顶前 90 / 前 30 / 顶 / 谷底 的水平,跨崩盘取中位
    senti = {"VIX": K.load_fred("VIXCLS"), "VXEEM": K.load_fred("VXEEMCLS"),
             "UMCSENT": K.available(K.load_fred("UMCSENT"), "UMCSENT")}
    def levels(level: pd.Series, anchors: list[pd.Timestamp], troughs: list[pd.Timestamp]) -> dict[str, Any]:
        out: dict[str, list[float]] = {}
        lv = K.to_calendar(level).ffill()
        def at(d):
            s = lv[lv.index <= pd.Timestamp(d)]
            return float(s.iloc[-1]) if len(s) else None
        for lbl, ds in (("pre90", [d - pd.Timedelta(days=90) for d in anchors]),
                        ("pre30", [d - pd.Timedelta(days=30) for d in anchors]),
                        ("peak", anchors), ("trough", troughs)):
            vals = [at(d) for d in ds]
            vals = [v for v in vals if v is not None]
            out[lbl] = {"median": float(np.median(vals)) if vals else None,
                        "per_anchor": {str(pd.Timestamp(d).date()): at(d) for d in ds}}
        return out
    RES["sentiment"] = {k: {"bear": levels(v, peaks, [e["trough_d"] for e in bears]),
                            "fast": levels(v, fstart, [f["hit_d"] for f in fasts])}
                        for k, v in senti.items()}

    # ── 风格:分阶段收益(只报不判)
    styles: dict[str, pd.Series] = {"EEM": eem, "SPY": spy, "UUP": others["UUP"], "GLD": others["GLD"]}
    for s in ETF_FLAT:
        styles[s] = others[s]
    styles["EEM_trend200_cashDFF"] = K.trend_200_nav(eem, K.load_fred("DFF"))
    def ph(lev: pd.Series, eps: list[dict[str, Any]], pre=60, post=120) -> list[dict[str, Any]]:
        return [K.phase_returns(lev, {"peak_d": e["peak_d"], "trough_d": e["trough_d"]}, pre, post)
                for e in eps]
    RES["style_bear"] = {s: ph(v, bears) for s, v in styles.items()}
    RES["style_fast"] = {s: ph(v, [{"peak_d": f["start_d"], "trough_d": f["hit_d"]} for f in fasts])
                         for s, v in styles.items()}

    # ── 货币危机锚点上的风格:持有该国货币(= DEX 下跌)vs 持有美元(= 0)
    fx_style: dict[str, Any] = {}
    for c, sid in FX.items():
        d = K.load_fred(sid)
        rows = []
        for m in keep:
            eps = {"peak_d": m["start_d"], "trough_d": m["hit_d"]}
            pr = K.phase_returns(1.0 / d, eps, 60, 180)   # 持该国货币(以美元计价)= 1/DEX
            rows.append({"ccy": c, "start_d": str(m["start_d"].date()),
                         "hit_d": str(m["hit_d"].date()), **pr})
        fx_style[c] = rows
    RES["style_fx_vs_usd"] = fx_style

    with open(OUT, "w") as fh:
        json.dump(RES, fh, indent=2, ensure_ascii=False, default=_j)
    print("\nwrote", OUT)
    print("clues:", json.dumps(clues, ensure_ascii=False, indent=1))


def _j(o: Any) -> Any:
    """numpy 标量 → python 标量(不要 default=str,那会把数字全变成字符串,结果 json 就不能复算了)。"""
    if isinstance(o, (np.generic,)):
        return o.item()
    if isinstance(o, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(o).date())
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.ndarray,)):
        return o.tolist()
    return str(o)


if __name__ == "__main__":
    main()