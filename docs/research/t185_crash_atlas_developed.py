"""T-185 崩盘图谱 · 主流市场(developed)—— 台账 S-675 A 道,Jazz 10-23。

**这是挖掘,不是检验。** 崩完之后回头找先兆最容易自欺(每次崩之前都能找到点什么),所以每个迹象都跟
**基准率**(它在随便哪天之前出现的频率)比,并用**循环平移 2,000 次**给零分布、种子 675。
挖出来的「线索」只进候选名单:要用必须另立预注册、按前向判。本脚本不产生任何可交易规则。

共用内核 `docs/research/crash_atlas_common.py`(bear_episodes / fast_crashes / expanding_pct /
sign_lift / phase_returns / trend_200_nav / load_fred / available / to_calendar)—— import,不复制。
本文件新增的函数都在下面,报告「协议问题」一节列出。

数据:FRED 快照 25 条(数据根 research/crash_atlas/fred/,Seth 抓,只读);库 ohlcv_daily(只读 publishable key)。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crash_atlas_common import (  # noqa: E402  台账 S-675:唯一一份内核,三道都 import 它
    FRED_DIR,
    SEED,
    _window_any,
    available,
    bear_episodes,
    expanding_pct,
    fast_crashes,
    load_fred,
    phase_returns,
    sign_lift,
    to_calendar,
    trend_200_nav,
)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_JSON = os.path.join(REPO, "docs", "research", "t185_results.json")

BEAR_THR = 0.20          # 熊市 −20% 起 / 反弹 +20% 确认(S-675 写死)
FAST_WINDOW, FAST_THR, FAST_DECLUSTER = 14, 0.10, 60   # 急跌:14 个日历日 ≤ −10%,60 天内只算一次
MAIN_LOOKBACK = 90       # 锚点一:first_leg 前高日回看 90 天
AUX_LOOKBACK = 30        # 锚点二/三:破位日 / 急跌起点回看 30 天
N_SHIFT = 2000

# ETF 拼接口径(S-675 补记):2022-08-31 之前 yfinance、之后 eodhd;SPY / QQQ 全段 eodhd。
SPLICE_DATE = "2022-08-31"
FULL_EODHD = ("SPY", "QQQ")


# ── 库读取(只读 publishable key;翻页必带 order=)────────────────────────────────
def fetch(symbol: str, table: str = "ohlcv_daily", **eq) -> pd.DataFrame:
    """从库里读一个 symbol 的全部行,按主键排(不带 order= 时 PostgREST 翻页边界会漂,实测丢两成键)。"""
    import urllib.parse
    import urllib.request

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    parts = [f"symbol=eq.{symbol}"] + [f"{k}=eq.{v}" for k, v in eq.items()]
    rows, off = [], 0
    while True:
        q = f"{table}?select=trade_date,close,source&{ '&'.join(parts) }&order=trade_date.asc&limit=1000&offset={off}"
        req = urllib.request.Request(url + "/rest/v1/" + q, headers={"apikey": key, "Authorization": f"Bearer {key}"})
        chunk = json.load(urllib.request.urlopen(req, timeout=60))
        rows += chunk
        if len(chunk) < 1000:
            break
        off += 1000
    if not rows:
        return pd.DataFrame(columns=["trade_date", "close", "source"])
    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values("trade_date").reset_index(drop=True)


def fetch_series(table: str, series: str, date_col: str) -> pd.Series:
    """库里的宏观日频序列(如 macro_daily 的 fng / total_mcap)。翻页带 order=。"""
    import urllib.parse
    import urllib.request

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    rows, off = [], 0
    while True:
        q = (f"{table}?select={date_col},value&series=eq.{urllib.parse.quote(series)}"
             f"&order={date_col}.asc&limit=1000&offset={off}")
        req = urllib.request.Request(url + "/rest/v1/" + q,
                                     headers={"apikey": key, "Authorization": f"Bearer {key}"})
        chunk = json.load(urllib.request.urlopen(req, timeout=60))
        rows += chunk
        if len(chunk) < 1000:
            break
        off += 1000
    if not rows:
        raise SystemExit(f"{table}/{series} 库里没有行 —— 报告情绪画像这一节写「未做」")
    s = pd.Series([r.get("value") for r in rows], index=pd.to_datetime([r[date_col] for r in rows]))
    return pd.to_numeric(s, errors="coerce").dropna().sort_index().rename(series)


def db_ohlcv(symbol: str, prefer: Optional[str] = None) -> pd.Series:
    """收盘价日序列。prefer=None 时两个源都留着(拼接自己处理)。"""
    df = fetch(symbol)
    if prefer:
        df = df[df["source"] == prefer]
    s = pd.Series(df["close"].astype(float).values, index=pd.to_datetime(df["trade_date"]), name=symbol)
    return s[~s.index.duplicated(keep="last")].sort_index()


def splice_etf(symbol: str) -> tuple[pd.Series, dict[str, Any]]:
    """2022-08-31 前 yfinance、之后 eodhd;全段 eodhd 的(SPY / QQQ)不拼。
    拼之前报重叠段的日收益相关与水平比 —— 拼出来的接缝必须能被看见。"""
    df = fetch(symbol)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    yf = df[df["source"] == "yfinance"].set_index("trade_date")["close"].astype(float).sort_index()
    eo = df[df["source"] == "eodhd"].set_index("trade_date")["close"].astype(float).sort_index()
    yf = yf[~yf.index.duplicated(keep="last")]
    eo = eo[~eo.index.duplicated(keep="last")]
    if symbol in FULL_EODHD or yf.empty or eo.empty:
        merged = eo if not eo.empty else yf
        return merged, {"symbol": symbol, "mode": "eodhd_only" if symbol in FULL_EODHD else "single_source",
                        "n_days": int(len(merged)), "overlap": None}
    cut = pd.Timestamp(SPLICE_DATE)
    ov = yf.index.intersection(eo.index)
    meta: dict[str, Any] = {"symbol": symbol, "mode": "spliced", "splice_date": SPLICE_DATE,
                            "n_yf": int(len(yf)), "n_eodhd": int(len(eo)), "overlap": {}}
    if len(ov) >= 30:
        ry = yf.loc[ov].pct_change().dropna()
        re_ = eo.loc[ov].pct_change().dropna()
        j = ry.index.intersection(re_.index)
        meta["overlap"] = {"n_days": int(len(j)), "first": str(j.min().date()), "last": str(j.max().date()),
                           "ret_corr": float(ry.reindex(j).corr(re_.reindex(j))),
                           "level_ratio_median": float((eo.loc[ov] / yf.loc[ov]).median()),
                           "level_ratio_p5": float((eo.loc[ov] / yf.loc[ov]).quantile(0.05)),
                           "level_ratio_p95": float((eo.loc[ov] / yf.loc[ov]).quantile(0.95))}
    left = yf[yf.index < cut]
    right = eo[eo.index >= cut]
    merged = pd.concat([left, right]).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    meta["n_days"] = int(len(merged))
    meta["first"] = str(merged.index.min().date())
    meta["last"] = str(merged.index.max().date())
    return merged, meta


# ── 迹象的装配:缺值 = 不算亮,不算覆盖 ──────────────────────────────────────────
def mk(deps: list[pd.Series], fn) -> pd.Series:
    """把若干依赖对齐到日历日后判条件:依赖全有数的地方给 0/1,有缺值的地方给 NaN。
    依赖按位置对齐(同一 union 索引),fn 收到的是一维数组,逐点条件在 fn 里写。"""
    idx = None
    for d in deps:
        idx = d.index if idx is None else idx.union(d.index)
    idx = idx.sort_values()
    vals = np.column_stack([d.reindex(idx).values for d in deps])
    ok = ~np.isnan(vals).any(axis=1)
    out = np.full(len(idx), np.nan)
    if ok.any():
        out[ok] = np.asarray(fn(*[vals[ok, i] for i in range(len(deps))]), dtype=float)
    return pd.Series(out, index=idx)


def ret_pct(x: pd.Series, days: int) -> pd.Series:
    return x / x.shift(days) - 1.0


def rv20(x: pd.Series) -> pd.Series:
    return x.pct_change().rolling(20, min_periods=20).std() * np.sqrt(252)


def build_signals(nasdaq: pd.Series) -> dict[str, pd.Series]:
    """P1–P5(在 NASDAQCOM 上)+ M1–M13(FRED)。全部按时点计算,低频序列先过 available()。
    派生量(分位、差分、滚动)一律在 pandas 上先算好再交给 mk —— mk 只做逐点条件。"""
    px = to_calendar(nasdaq, 7)
    ma200 = px.rolling(200, min_periods=200).mean()
    hi52 = px.rolling(252, min_periods=252).max()
    r252 = px / px.shift(252) - 1.0
    vol20 = rv20(px)
    pct_r252 = expanding_pct(r252, 252)
    pct_ma = expanding_pct(px / ma200 - 1.0, 252)
    pct_vol = expanding_pct(vol20, 252)

    dff = available(load_fred("DFF", FRED_DIR), "DFF")
    t10y2y = available(load_fred("T10Y2Y", FRED_DIR), "T10Y2Y")
    baa10y = available(load_fred("BAA10Y", FRED_DIR), "BAA10Y")
    nfci = available(load_fred("NFCI", FRED_DIR), "NFCI")
    vix_c = to_calendar(available(load_fred("VIXCLS", FRED_DIR), "VIXCLS"), 7)
    vxv_c = to_calendar(available(load_fred("VXVCLS", FRED_DIR), "VXVCLS"), 7)
    usd_c = to_calendar(available(load_fred("DTWEXBGS", FRED_DIR), "DTWEXBGS"), 7)
    wti = available(load_fred("DCOILWTICO", FRED_DIR), "DCOILWTICO")
    walcl = available(load_fred("WALCL", FRED_DIR), "WALCL")
    umcsent = available(load_fred("UMCSENT", FRED_DIR), "UMCSENT")
    icsa = available(load_fred("ICSA", FRED_DIR), "ICSA")

    inv365 = (t10y2y < 0).rolling(366, min_periods=1).max()
    dff_365 = dff - dff.shift(365)
    baa_63 = baa10y - baa10y.shift(63)
    usd63_pct = expanding_pct(usd_c / usd_c.shift(63) - 1.0, 252)
    wti_126 = wti / wti.shift(126) - 1.0
    walcl_91 = walcl - walcl.shift(91)
    sent_pct = expanding_pct(umcsent, 252)
    icsa_ma = icsa.rolling(104, min_periods=52).mean()
    icsa_13w = icsa_ma / icsa_ma.shift(65) - 1.0

    S: dict[str, pd.Series] = {}
    # —— 价格本身 ——
    S["P1"] = mk([pct_r252], lambda a: (a >= 0.9))
    S["P2"] = mk([pct_ma], lambda a: (a >= 0.9))
    S["P3"] = mk([pct_vol], lambda a: (a <= 0.1))
    S["P4"] = mk([pct_vol], lambda a: (a >= 0.9))
    S["P5"] = mk([px, hi52, ma200], lambda p, h, m: ((p / h - 1.0) <= -0.05) & (p > m))
    # —— 全球宏观 ——
    S["M1"] = mk([dff_365], lambda a: (a >= 1.0))
    S["M2"] = mk([t10y2y], lambda a: (a < 0))
    S["M3"] = mk([t10y2y, inv365], lambda a, b: (a > 0) & (b >= 1))
    S["M4"] = mk([nfci], lambda a: (a > 0))
    S["M5"] = mk([baa_63], lambda a: (a >= 0.5))
    S["M6"] = mk([vix_c], lambda a: (a < 13))
    S["M7"] = mk([vix_c], lambda a: (a > 30))
    S["M8"] = mk([vix_c, vxv_c], lambda a, b: (a / b > 1.0))
    S["M9"] = mk([usd63_pct], lambda a: (a >= 0.9))
    S["M10"] = mk([wti_126], lambda a: (a >= 0.50))
    S["M11"] = mk([walcl_91], lambda a: (a < 0))
    S["M12"] = mk([sent_pct], lambda a: (a >= 0.8))
    S["M13"] = mk([icsa_13w], lambda a: (a >= 0.15))
    # sign_lift 要的是**日历日**布尔序列(内核 docstring 明写「先用 to_calendar 对齐」):
    # 周频(M4 NFCI / M11 WALCL / M13 ICSA)与月频(M12 UMCSENT)不铺开的话,锚点日会落在索引外
    # —— get_indexer 返回 −1,核心里被当成最后一格,等于把锚点静默指到别处。
    gaps = {"M12": 40, "M4": 10, "M11": 10, "M13": 10}
    return {k: to_calendar(v, gaps.get(k, 7)) for k, v in S.items()}


SIGNAL_NAMES = {
    "P1": "过去 252 天收益分位 ≥ 0.9(亢奋)", "P2": "价格/200 日均线−1 分位 ≥ 0.9(过度延伸)",
    "P3": "20 日实现波动分位 ≤ 0.1(风平浪静)", "P4": "20 日实现波动分位 ≥ 0.9(动荡)",
    "P5": "离 52 周高点 ≥ 5% 但仍在 200 日线上(初裂)",
    "M1": "联邦基金利率 12 个月升 ≥ 1pp", "M2": "10Y−2Y < 0(倒挂)", "M3": "10Y−2Y > 0 且过去 365 天倒挂过(解除倒挂)",
    "M4": "NFCI > 0(金融条件紧)", "M5": "Baa−10Y 利差 63 天升 ≥ 0.5pp", "M6": "VIX < 13", "M7": "VIX > 30",
    "M8": "VIX / VXV > 1(期限结构倒挂)", "M9": "美元广义指数 63 天变化分位 ≥ 0.9", "M10": "WTI 126 天涨 ≥ 50%",
    "M11": "美联储资产负债表 91 天缩", "M12": "密歇根消费者信心分位 ≥ 0.8", "M13": "初请 4 周均值 13 周升 ≥ 15%",
}
SAME_SOURCE = {  # 与崩盘定义同源:锚点就是崩点本身,不算线索
    ("P4", "aux_break"), ("P5", "aux_break"), ("P4", "aux_fast"), ("P5", "aux_fast"),
}


# ── 风格 ──────────────────────────────────────────────────────────────────────
def norm(s: pd.Series) -> pd.Series:
    s = s.dropna().sort_index()
    return s / s.iloc[0]


def bond10y_total_return(dgs10: pd.Series) -> pd.Series:
    """DGS10 近似总收益:日收益 ≈ y/365 − 8 × Δy(y 用小数)。"""
    y = (dgs10.dropna().sort_index() / 100.0)
    r = y / 365.0 - 8.0 * y.diff()
    r.iloc[0] = y.iloc[0] / 365.0
    return (1 + r).cumprod()


def cash_nav(dff: pd.Series) -> pd.Series:
    y = (dff.dropna().sort_index() / 100.0)
    dt = y.index.to_series().diff().dt.days.fillna(1).values
    return pd.Series((1 + y.values * dt / 365.0).cumprod(), index=y.index, name="cash")


def at_or_before(s: pd.Series, d: pd.Timestamp) -> Optional[float]:
    s = s.dropna().sort_index()
    s = s[s.index <= d]
    return float(s.iloc[-1]) if len(s) else None


def main() -> dict[str, Any]:
    res: dict[str, Any] = {"task": "T-185", "protocol": "S-675", "seed": SEED, "n_shift": N_SHIFT,
                           "definitions": {"bear": BEAR_THR, "fast": [FAST_WINDOW, FAST_THR, FAST_DECLUSTER],
                                           "main_lookback": MAIN_LOOKBACK, "aux_lookback": AUX_LOOKBACK,
                                           "splice_date": SPLICE_DATE}}

    nasdaq = load_fred("NASDAQCOM", FRED_DIR)
    spy = db_ohlcv("SPY", prefer="eodhd")
    qqq = db_ohlcv("QQQ", prefer="eodhd")

    # ── 崩盘目录 ──
    cat: dict[str, Any] = {}
    for name, px in (("NASDAQCOM", nasdaq), ("SPY", spy)):
        eps = bear_episodes(px, BEAR_THR)
        fcs = fast_crashes(px, FAST_WINDOW, FAST_THR, FAST_DECLUSTER)
        cat[name] = {
            "first": str(px.index.min().date()), "last": str(px.index.max().date()), "n_obs": int(len(px)),
            "bears": [{"peak_d": str(e["peak_d"].date()), "break_d": str(e["break_d"].date()),
                       "trough_d": str(e["trough_d"].date()), "depth": round(e["depth"], 4),
                       "recover_d": str(e["recover_d"].date()) if e["recover_d"] is not None else None,
                       "open": e["open"], "first_leg": e["first_leg"]} for e in eps],
            "fast_crashes": [{"start_d": str(f["start_d"].date()), "hit_d": str(f["hit_d"].date()),
                              "ret": round(f["ret"], 4)} for f in fcs],
        }
    res["catalog"] = cat

    eps = bear_episodes(nasdaq, BEAR_THR)
    fcs = fast_crashes(nasdaq, FAST_WINDOW, FAST_THR, FAST_DECLUSTER)
    anchors = {
        "main": [e["peak_d"] for e in eps if e["first_leg"]],
        "aux_break": [e["break_d"] for e in eps],
        "aux_fast": [f["start_d"] for f in fcs],
    }
    res["anchors"] = {k: [str(pd.Timestamp(a).date()) for a in v] for k, v in anchors.items()}

    # ── 迹象表 ──
    S = build_signals(nasdaq)
    sig_rows = []
    for name, on in S.items():
        for ak, lb in (("main", MAIN_LOOKBACK), ("aux_break", AUX_LOOKBACK), ("aux_fast", AUX_LOOKBACK)):
            r = sign_lift(on, anchors[ak], lb, n_shift=N_SHIFT, seed=SEED)
            r2 = dict(r)
            r2.update({"signal": name, "anchor_set": ak, "lookback": lb,
                       "label": SIGNAL_NAMES.get(name, name),
                       "same_source": (name, ak) in SAME_SOURCE,
                       "first_data": str(on.dropna().index.min().date()) if on.notna().any() else None})
            # 前后两半各自的命中率(线索门槛之一:两半都要亮过基准率)
            if r["hit_rate"] is not None:
                win = _window_any(on, lb)
                first_ok = on.index[on.notna().values.argmax()] + pd.Timedelta(days=lb)
                usable = sorted(pd.Timestamp(a) for a in anchors[ak] if first_ok <= pd.Timestamp(a) <= on.index[-1])
                mid = usable[len(usable) // 2]
                for half, sel in (("first", [a for a in usable if a <= mid]),
                                  ("second", [a for a in usable if a > mid])):
                    got = win.reindex(pd.DatetimeIndex(sel)).dropna() if sel else pd.Series(dtype=float)
                    r2[f"hit_{half}"] = float(got.mean()) if len(got) else None
                    r2[f"n_{half}"] = int(len(got))
                r2["both_halves_above_base"] = bool(
                    r2["hit_first"] is not None and r2["hit_second"] is not None
                    and r["base_rate"] is not None
                    and r2["hit_first"] > r["base_rate"] and r2["hit_second"] > r["base_rate"])
                # 线索门槛(S-675):分位 ≥ 0.95 且 提升 ≥ 1.5 且 锚点 ≥ 6 且 前后两半都亮
                r2["is_clue"] = bool((r["pctile"] or 0) >= 0.95 and (r["lift"] or 0) >= 1.5
                                     and r["n_anchors"] >= 6 and r2["both_halves_above_base"]
                                     and (name, ak) not in SAME_SOURCE)
            else:
                r2.update({"hit_first": None, "hit_second": None, "n_first": 0, "n_second": 0,
                           "both_halves_above_base": False, "is_clue": False})
            sig_rows.append(r2)
    res["signals"] = sig_rows

    # ── 情绪画像:VIX / 消费者信心,跨崩盘取中位 ──
    vix = to_calendar(available(load_fred("VIXCLS", FRED_DIR), "VIXCLS"), 7)
    sent = to_calendar(available(load_fred("UMCSENT", FRED_DIR), "UMCSENT"), 40)
    fng = to_calendar(fetch_series("macro_daily", "fng", "d"), 7)
    rows_sent = []
    for e in eps:
        pk, tr = pd.Timestamp(e["peak_d"]), pd.Timestamp(e["trough_d"])
        row = {"peak_d": str(pk.date()), "trough_d": str(tr.date()), "first_leg": e["first_leg"]}
        for k, d in (("vix_peak-90", pk - pd.Timedelta(days=90)), ("vix_peak-30", pk - pd.Timedelta(days=30)),
                     ("vix_peak", pk), ("vix_trough", tr), ("sent_peak", pk), ("sent_trough", tr),
                     ("fng_peak-90", pk - pd.Timedelta(days=90)), ("fng_peak-30", pk - pd.Timedelta(days=30)),
                     ("fng_peak", pk), ("fng_trough", tr)):
            src = vix if k.startswith("vix") else (sent if k.startswith("sent") else fng)
            v = at_or_before(src, d)
            row[k] = round(v, 2) if v is not None else None
        rows_sent.append(row)
    res["sentiment"] = {"per_episode": rows_sent,
                        "fng_first": str(fng.dropna().index.min().date()) if fng.notna().any() else None,
                        **{f"median_{k}": _med(rows_sent, k) for k in
                           ("vix_peak-90", "vix_peak-30", "vix_peak", "vix_trough",
                            "sent_peak", "sent_trough", "fng_peak-90", "fng_peak-30", "fng_peak", "fng_trough")}}

    # ── 风格:分阶段(只报不判)──
    dgs10 = available(load_fred("DGS10", FRED_DIR), "DGS10")
    dff = load_fred("DFF", FRED_DIR)
    styles: dict[str, pd.Series] = {
        "NASDAQCOM 持有": norm(nasdaq),
        "NASDAQCOM 200 日趋势": trend_200_nav(nasdaq, dff),
        "10 年美债(近似总收益)": bond10y_total_return(dgs10),
        "美元(DTWEXBGS)": norm(to_calendar(available(load_fred("DTWEXBGS", FRED_DIR), "DTWEXBGS"), 7)),
        "现金(DFF)": cash_nav(dff),
    }
    splice_meta = {}
    for sym in ("SPY", "QQQ", "TLT", "IEF", "GLD", "UUP", "HYG"):
        if sym in ("SPY", "QQQ"):
            styles[f"{sym}(eodhd)"] = norm(spy if sym == "SPY" else qqq)
            splice_meta[sym] = {"symbol": sym, "mode": "eodhd_only", "n_days": int(len(spy if sym == "SPY" else qqq))}
            continue
        s, meta = splice_etf(sym)
        styles[f"{sym}(拼接)"] = norm(s)
        splice_meta[sym] = meta
    res["etf_splice"] = splice_meta

    ph: dict[str, Any] = {}
    for nm, ser in styles.items():
        ph[nm] = [phase_returns(ser, e) for e in eps]
        ph[nm] = [{"peak_d": str(pd.Timestamp(e["peak_d"]).date()), "first_leg": e["first_leg"],
                   "pre": _r(v["pre"]), "crash": _r(v["crash"]), "recovery": _r(v["recovery"])}
                  for v, e in zip(ph[nm], eps)]
    res["styles"] = ph
    res["styles_median"] = {nm: {"pre": _med(ph[nm], "pre"), "crash": _med(ph[nm], "crash"),
                                 "recovery": _med(ph[nm], "recovery")} for nm in styles}

    with open(OUT_JSON, "w") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    print(f"wrote {OUT_JSON}")
    print(f"NASDAQCOM bears={len(eps)} first_leg={sum(1 for e in eps if e['first_leg'])} fast={len(fcs)}")
    return res


def _r(x):
    return round(x, 4) if isinstance(x, (int, float)) and x == x else None


def _med(rows, key):
    v = [r[key] for r in rows if r.get(key) is not None]
    return round(float(np.median(v)), 4) if v else None


if __name__ == "__main__":
    main()