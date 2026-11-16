#!/usr/bin/env python3
"""T-411 —— 纸面账成员的前向来源对账:生产序列 vs 研究面板。

问题(T-406 前向记账的前置):纸面账 `src/data/universe/state_book.py` 的成员收益走**生产**
来路(`load_inputs`,S-890 冻结名单),研究面板(`docs/research/s869_strategy_state.py::load_panel`)
走**研究**来路。两边不是同一份代码 ⇒ 前向的数和回测的数能不能放在一起读,要先量。

本脚本:
- **不 import `src/`**(卡要求)。生产公式照抄进脚本,每段注明出处行号。
- 生产取数照抄 `src/data/universe/forward_books.py::tom_inputs` 与
  `src/data/universe/state_book.py::load_inputs` 的来路(表 / 过滤 / 口径)。
- 研究侧照抄 `docs/research/s869_strategy_state.py::load_panel` 的**净值 → 逐日收益**口径
  (首末日之间缺的日子按净值不变补齐;**这一步不扣现金**),读它读的同一批 CSV。
- 逐日比:重叠起止 / 天数 / 逐日差(绝对值中位数、95 分位、最大)/ 两边累计收益 /
  两边年化波动 / 相关系数。
- 判:**逐日差中位数 < 1bp 且累计差 < 2% ⇒「同一条」**;否则写清差在哪
  (参数、资金费口径、成本、价源),**不改任何一边去凑**。

用法:python3 docs/research/t411_member_parity.py
产物:docs/research/t411_member_parity.json
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import urllib.parse
import urllib.request
from typing import Any, Optional

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "t411_member_parity.json")
MAC = "/Volumes/CometCloudAI/cometcloud-local"

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]

# ── 生产常量(照抄)───────────────────────────────────────────────────────────
TOM_WARM_FROM = "2024-01-01"   # src/data/universe/forward_books.py:36(tom_inputs 的起读日)
BOOK_START = "2026-11-15"     # src/data/universe/state_book.py:31
HISTORY_DAYS = 200            # src/data/universe/state_book.py:37
CUTOFF = "2026-11-14"         # 最后一个完整收盘日(记账起点日的前一天)
#: 生产读窗:`load_inputs` 的 since = _shift(START, -HISTORY_DAYS)(state_book.py:281)
PROD_SINCE = (dt.date.fromisoformat(BOOK_START) - dt.timedelta(days=HISTORY_DAYS)).isoformat()

#: 判据(卡):逐日差中位数 < 1bp 且累计差 < 2% ⇒ 同一条
MED_TOL = 1e-4
CUM_TOL = 0.02


def D(s: Any) -> dt.date:
    """日期键统一成 date(照抄 state_book.py:94-95 的写法)。"""
    return s if isinstance(s, dt.date) and not isinstance(s, dt.datetime) else dt.date.fromisoformat(str(s)[:10])


def log(msg: str) -> None:
    print(msg, flush=True)


# ── 读库(每页 ≤ 1000;一律带 order=)─────────────────────────────────────────
def rest(table: str, params: list[tuple[str, str]]) -> list:
    url = f"{URL}/rest/v1/{table}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip() else []


def fetch_paged(table: str, select: str, filters: list[tuple[str, str]], order_col: str) -> list[dict]:
    out: list[dict] = []
    off = 0
    while True:
        params = list(filters) + [("select", select), ("order", f"{order_col}.asc"),
                                  ("limit", "1000"), ("offset", str(off))]
        rows = rest(table, params)
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
        if off > 200000:
            break
    log(f"  {table}: {len(out)} 行")
    return out


# ── 生产公式(照抄;每段注明出处)───────────────────────────────────────────────
def daily_from_nav(nav: dict) -> dict:
    """净值 → 逐日收益;首末日之间缺的日子按净值不变(收益 0)。
    照抄 src/data/universe/state_book.py:100-110(= 研究脚本 `_daily_from_nav`,
    docs/research/s869_strategy_state.py:64-72,同一写法)。"""
    ds = sorted(nav)
    if not ds:
        return {}
    out, prev, d = {}, nav[ds[0]], ds[0] + dt.timedelta(days=1)
    while d <= ds[-1]:
        cur = nav.get(d, prev)
        out[d] = cur / prev - 1 if prev else 0.0
        prev, d = cur, d + dt.timedelta(days=1)
    return out


def extend_weekend(rets: dict) -> tuple[dict, Optional[dt.date]]:
    """只在工作日有收盘的腿:最后一根是周五 ⇒ 周六、周日收益 = 0。照抄 state_book.py:177-187。"""
    if not rets:
        return {}, None
    last = max(rets)
    out = dict(rets)
    if last.weekday() == 4:
        for k in (1, 2):
            out[last + dt.timedelta(days=k)] = 0.0
        return out, last + dt.timedelta(days=2)
    return out, last


UNIT, STEP, HI_N, LO_N, MA_N, DEF_BASE, CAP = 0.1, 1.10, 55, 20, 200, 0.7, 1.3   # tom.py:20
COST_BPS, RALLY_SIZE, RALLY_TP, SHORT_TP, WARM = 10.0, 0.5, 1.15, 0.80, 200    # tom.py:52


def tom_gross(close: pd.Series, cap: float = CAP, defend: bool = True) -> pd.Series:
    """照抄 src/data/signals/tom.py:23-47。"""
    c = close.dropna().astype(float).to_numpy()
    idx = close.dropna().index
    g = np.ones(len(c))
    b, k, last_add = 1.0, 0, None
    for t in range(len(c)):
        x = c[t]
        if t >= HI_N:
            hi = c[t - HI_N:t].max()
            lo = c[t - LO_N:t].min()
            if k > 0 and x < lo:
                k, last_add = 0, None
            elif k == 0 and x > hi and b + UNIT <= cap + 1e-9:
                k, last_add = 1, x
            elif k > 0 and x >= last_add * STEP and b + UNIT * (k + 1) <= cap + 1e-9:
                k, last_add = k + 1, x
            if defend and t >= MA_N - 1:
                ma = c[t - MA_N + 1:t + 1].mean()
                if x < ma and x < lo:
                    b = DEF_BASE
                elif x > ma:
                    b = 1.0
        g[t] = min(cap, b + UNIT * k)
    return pd.Series(g, index=idx)


def vol_scale(close: pd.Series) -> pd.Series:
    """照抄 src/data/signals/tom.py:55-71。"""
    s = close.dropna().astype(float)
    c = s.to_numpy()
    lr = np.zeros(len(c))
    lr[1:] = np.log(c[1:] / c[:-1])
    v20 = np.full(len(c), np.nan)
    for t in range(20, len(c)):
        v20[t] = lr[t - 19:t + 1].std(ddof=1)
    out = np.ones(len(c))
    for t in range(260, len(c)):
        hist = v20[max(20, t - 730):t + 1]
        hist = hist[np.isfinite(hist)]
        if len(hist) >= 200 and v20[t] > 0:
            out[t] = min(1.0, float(np.median(hist)) / v20[t])
    return pd.Series(out, index=s.index)


def trade_path(close: pd.Series, bear: str, short_size: float = 0.0, exit_mode: str = "ma", vol: bool = False) -> pd.Series:
    """照抄 src/data/signals/tom.py:73-122。"""
    s = close.dropna().astype(float)
    c, n = s.to_numpy(), len(s)
    g = np.ones(n)
    mode, k, last_add, entry = "long", 0, None, None
    for t in range(WARM, n):
        x = c[t]
        ma = c[t - MA_N + 1:t + 1].mean()
        h20, l20, h55, l10 = c[t - 20:t].max(), c[t - 20:t].min(), c[t - 55:t].max(), c[t - 10:t].min()
        long_entry = x > ma and x > h20
        if mode == "long":
            if exit_mode == "l20" and x < l20:
                mode, k, last_add = "flat", 0, None
                g[t] = 0.0
                continue
            if k > 0 and x < l20:
                k, last_add = 0, None
            elif k == 0 and x > h55 and 1 + UNIT <= CAP + 1e-9:
                k, last_add = 1, x
            elif k > 0 and x >= last_add * STEP and 1 + UNIT * (k + 1) <= CAP + 1e-9:
                k, last_add = k + 1, x
            if x < ma and x < l20:
                k, last_add = 0, None
                mode, entry = ("short", x) if bear == "short" else ("flat", None)
        elif mode == "flat":
            if long_entry:
                mode, k = "long", 0
            elif bear == "rally" and x > h20:
                mode, entry = "rally", x
            elif bear == "short" and x < ma and x < l20:
                mode, entry = "short", x
        elif mode == "rally":
            if long_entry:
                mode, k = "long", 0
            elif x >= entry * RALLY_TP or x < l10:
                mode = "flat"
        elif mode == "short":
            if long_entry:
                mode, k = "long", 0
            elif x <= entry * SHORT_TP or x > h20:
                mode = "flat"
        g[t] = {"long": 1 + UNIT * k, "flat": 0.0, "rally": RALLY_SIZE, "short": short_size}[mode]
    out = pd.Series(g, index=s.index)
    if vol:
        vs = vol_scale(s)
        out = out.where(np.arange(n) < WARM, out * vs)
    return out


def trade_returns(close: pd.Series, g: pd.Series, funding_ann: Optional[pd.Series] = None) -> pd.Series:
    """照抄 src/data/signals/tom.py:125-133。"""
    s = close.dropna().astype(float)
    px = s.pct_change()
    gp = g.reindex(s.index).shift(1)
    prev = g.reindex(s.index).shift(2).fillna(1.0)
    f = (funding_ann.reindex(s.index).ffill().fillna(0.10) if funding_ann is not None
         else pd.Series(0.10, index=s.index)) / 365
    r = (gp * px - (gp - 1).clip(lower=0) * f + (-gp).clip(lower=0) * f
         - (gp - prev).abs() * COST_BPS / 1e4)
    return r.iloc[1:].fillna(0.0)


def series_to_dict(s: pd.Series) -> dict:
    """照抄 state_book.py:253-254。"""
    return {ts.date(): float(v) for ts, v in s.items() if v == v}


# ── 生产取数(照抄 tom_inputs / load_inputs 的来路)─────────────────────────────
def load_production() -> dict:
    log("[生产] 取数")
    out: dict[str, Any] = {}

    # ① 核心净值 = multiplier_daily 的 core_u_replay(forward_books.py:208-210)
    rows = fetch_paged("multiplier_daily", "d,nav",
                        [("arm", "eq.core_u_replay"), ("d", f"gte.{TOM_WARM_FROM}"), ("d", f"lte.{CUTOFF}")], "d")
    core_nav = {D(r["d"]): float(r["nav"]) for r in rows if r.get("nav") is not None}
    out["core_nav"] = core_nav

    # 收盘:BTC / ETH = asset_mcap_daily(forward_books.py:194-210)
    closes: dict[str, pd.Series] = {}
    for sym in ("BTC", "ETH"):
        rows = fetch_paged("asset_mcap_daily", "d,price",
                            [("symbol", f"eq.{sym}"), ("d", f"gte.{TOM_WARM_FROM}"), ("d", f"lte.{CUTOFF}")], "d")
        pts = [(D(r["d"]), float(r["price"])) for r in rows if r.get("price")]
        closes[sym] = pd.Series([v for _, v in pts], index=pd.to_datetime([d for d, _ in pts]))
    out["closes"] = closes

    # 资金费:funding_history 币安永续按天求和 × 365(forward_books.py:211-219)
    fund: dict[str, pd.Series] = {}
    for sym in ("BTC", "ETH"):
        rows = fetch_paged("funding_history", "funding_time,funding_rate",
                            [("venue", "eq.binance_perp"), ("symbol", f"eq.{sym}"),
                             ("funding_time", f"gte.{TOM_WARM_FROM}")], "funding_time")
        if rows:
            df = pd.DataFrame(rows)
            df["d"] = pd.to_datetime(df["funding_time"].str[:10])
            fund[sym] = df.groupby("d")["funding_rate"].sum().astype(float) * 365
    fund["CORE"] = fund.get("BTC")
    out["fund"] = fund

    # R-v2 = r_money_daily 的净值(state_book.py:299-301)
    rows = fetch_paged("r_money_daily", "d,nav", [("d", f"lte.{CUTOFF}")], "d")
    out["rv2_nav"] = {D(r["d"]): float(r["nav"]) for r in rows if r.get("nav") is not None}

    # 股 / 金 = ohlcv_daily eodhd(state_book.py:304-311);这里取全史(源相同,读窗另记)
    for sym in ("ACWI", "XAUUSD"):
        rows = fetch_paged("ohlcv_daily", "trade_date,close",
                            [("source", "eq.eodhd"), ("symbol", f"eq.{sym}"),
                             ("trade_date", f"lte.{CUTOFF}")], "trade_date")
        out[f"px_{sym}"] = {D(r["trade_date"]): float(r["close"]) for r in rows if r.get("close")}

    # 风格 = style_index_pit_daily(cap)的 ret(state_book.py:312-326)
    rows = fetch_paged("style_index_pit_daily", "d,style,ret",
                        [("weighting", "eq.cap"), ("d", f"lte.{CUTOFF}")], "d")
    by: dict[str, dict] = {}
    for r in rows:
        if r.get("ret") is not None:
            by.setdefault(r["style"], {})[D(r["d"])] = float(r["ret"])
    out["style_rets"] = by
    return out


def production_members(P: dict) -> dict:
    """按 state_book.load_inputs 的口径拼出每个成员的逐日收益(**不扣现金**,卡要求)。"""
    m: dict[str, dict] = {}

    # X1V:TOM_ARMS['CORE_X1V'] = ('CORE','rally',0.0,'l20',True)(forward_books.py:43)
    #      作用于 multiplier_daily core_u_replay 的净值(state_book.py:264-265)
    core_nav = P["core_nav"]
    core = pd.Series([core_nav[d] for d in sorted(core_nav)],
                      index=pd.to_datetime([d for d in sorted(core_nav)]))
    g = trade_path(core, "rally", 0.0, "l20", True)
    m["X1V"] = series_to_dict(trade_returns(core, g, P["fund"].get("CORE")))
    # 核心 = core_u_replay 净值(state_book.py:266)
    m["核心"] = daily_from_nav(core_nav)

    # R-v2 = r_money_daily 净值(state_book.py:299-301)
    m["R-v2"] = daily_from_nav(P["rv2_nav"])

    # 股 / 金 = eodhd 收盘(周末 0)(state_book.py:304-311)
    for sym in ("ACWI", "XAUUSD"):
        rets, _known = extend_weekend(daily_from_nav(P[f"px_{sym}"]))
        m[sym] = rets

    # 风格 = cap 加权指数的 ret 累乘成净值再转逐日(state_book.py:312-326)
    for style, rr in P["style_rets"].items():
        nav, v = {}, 1.0
        for d in sorted(rr):
            v *= 1 + rr[d]
            nav[d] = v
        m[f"style_{style}"] = daily_from_nav(nav)

    # Tom PD13 = tom_gross + trade_returns 作用于 asset_mcap_daily 收盘(state_book.py:269-274)
    for sym, name in (("BTC", "tom_pd13_btc"), ("ETH", "tom_pd13_eth")):
        c = P["closes"][sym]
        m[name] = series_to_dict(trade_returns(c, tom_gross(c), P["fund"].get(sym)))
    return m


# ── 研究面板(照抄 s869_strategy_state.py::load_panel 的取数与口径)─────────────
def load_research_nav() -> dict:
    log("[研究] 读面板")
    navs: dict[str, dict] = {}

    def put(name: str, d: dt.date, v: float) -> None:
        navs.setdefault(name, {})[d] = v

    with open(os.path.join(HERE, "t348_r4_legs.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = D(r["d"])
            if r.get("crypto_nav"):
                put("x1v", d, float(r["crypto_nav"]))
            if r.get("equity_close"):
                put("equity", d, float(r["equity_close"]))
            if r.get("gold_close"):
                put("gold", d, float(r["gold_close"]))
    with open(os.path.join(HERE, "t342_daily.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("core_nav_1_cap_pit24"):
                put("core", D(r["date"]), float(r["core_nav_1_cap_pit24"]))
    with open(os.path.join(HERE, "t348_r3_rv2_curve.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("nav"):
                put("rv2", D(r["d"]), float(r["nav"]))
    with open(os.path.join(HERE, "s869_extra_panel_a.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("nav"):
                put(r["family"], D(r["d"]), float(r["nav"]))
    for k in sorted(navs):
        log(f"  {k}: {len(navs[k])} 天 {min(navs[k])} → {max(navs[k])}")
    return navs


# ── 比 ───────────────────────────────────────────────────────────────────────
def compare(prod: dict, res: dict, since: Optional[dt.date] = None) -> dict:
    ds = sorted(set(prod) & set(res))
    if since is not None:
        ds = [d for d in ds if d >= since]
    if not ds:
        return {"overlap_days": 0, "verdict": "无重叠"}
    p = np.array([prod[d] for d in ds], dtype=float)
    r = np.array([res[d] for d in ds], dtype=float)
    diff = p - r
    ad = np.abs(diff)
    cum_p = float(np.prod(1 + p) - 1)
    cum_r = float(np.prod(1 + r) - 1)
    cum_d = cum_p - cum_r
    corr = float(np.corrcoef(p, r)[0, 1]) if p.std() > 0 and r.std() > 0 else None
    same = bool(np.median(ad) < MED_TOL and abs(cum_d) < CUM_TOL)
    worst = [{"d": ds[i].isoformat(), "prod_ret": float(p[i]), "res_ret": float(r[i]),
              "diff_bp": float(diff[i] * 1e4)} for i in np.argsort(-ad)[:5]]
    return {
        "overlap_start": ds[0].isoformat(),
        "overlap_end": ds[-1].isoformat(),
        "overlap_days": len(ds),
        "abs_diff_median_bp": float(np.median(ad) * 1e4),
        "abs_diff_p95_bp": float(np.percentile(ad, 95) * 1e4),
        "abs_diff_max_bp": float(ad.max() * 1e4),
        "mean_diff_bp": float(diff.mean() * 1e4),
        "prod_cum_return": cum_p,
        "res_cum_return": cum_r,
        "cum_diff": cum_d,
        "prod_ann_vol": float(p.std(ddof=1) * math.sqrt(365)) if len(p) > 1 else None,
        "res_ann_vol": float(r.std(ddof=1) * math.sqrt(365)) if len(r) > 1 else None,
        "corr": corr,
        "worst_days": worst,
        "verdict": "同一条" if same else "不同一条",
    }


# ── Tom PD13 的 2×2 分解(价源 × 资金费口径)──────────────────────────────────
def pd13_decomposition() -> dict:
    """生产公式在四种(价源 × 资金费)组合上的逐日收益,各自与研究曲线比。
    研究侧 = S-596(s596_tom_pyramid.py):close.json 收盘 + 月均资金费 + 10bp 成本。"""
    res_nav: dict[str, dict] = {}
    with open(os.path.join(HERE, "s869_extra_panel_a.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["family"] in ("tom_pd13_btc", "tom_pd13_eth") and r.get("nav"):
                res_nav.setdefault(r["family"], {})[D(r["d"])] = float(r["nav"])
    res_rets = {k: daily_from_nav(v) for k, v in res_nav.items()}

    # 研究价源:close.json(Mac 根 research/w50_daily/)
    cj = json.load(open(os.path.join(MAC, "research/w50_daily/close.json")))
    cdates = [str(d)[:10] for d in cj["dates"]]
    price_res = {}
    for sym in ("BTC", "ETH"):
        vals = cj["close"][sym]
        price_res[sym] = pd.Series(
            {pd.Timestamp(d): float(v) for d, v in zip(cdates, vals) if v},
            dtype=float).sort_index()

    # 研究资金费:funding_monthly.txt 的月均(年化)→ 日率 = 月值 / 365
    fm: dict[str, dict[str, float]] = {}
    for line in open(os.path.join(MAC, "research/s596/funding_monthly.txt")):
        parts = line.split()
        if parts and parts[0] in ("BTC", "ETH"):
            fm[parts[0]] = {p.split(":")[0]: float(p.split(":")[1]) for p in parts[1:]}
    fund_res = {}
    for sym in ("BTC", "ETH"):
        m = fm.get(sym, {})
        s = pd.Series({pd.Timestamp(d): m.get(str(d)[:7], 0.10) for d in cdates}, dtype=float)
        fund_res[sym] = s.sort_index()

    # 生产价源 / 生产资金费(DB)
    db_price, db_fund = {}, {}
    for sym in ("BTC", "ETH"):
        rows = fetch_paged("asset_mcap_daily", "d,price",
                            [("symbol", f"eq.{sym}"), ("d", f"gte.{TOM_WARM_FROM}"), ("d", f"lte.{CUTOFF}")], "d")
        pts = [(D(r["d"]), float(r["price"])) for r in rows if r.get("price")]
        db_price[sym] = pd.Series([v for _, v in pts], index=pd.to_datetime([d for d, _ in pts]))
        rows = fetch_paged("funding_history", "funding_time,funding_rate",
                            [("venue", "eq.binance_perp"), ("symbol", f"eq.{sym}"),
                             ("funding_time", f"gte.{TOM_WARM_FROM}")], "funding_time")
        if rows:
            df = pd.DataFrame(rows)
            df["d"] = pd.to_datetime(df["funding_time"].str[:10])
            db_fund[sym] = df.groupby("d")["funding_rate"].sum().astype(float) * 365

    out: dict[str, Any] = {}
    for sym, fam in (("BTC", "tom_pd13_btc"), ("ETH", "tom_pd13_eth")):
        combos = {
            "价研究+费研究": (price_res[sym], fund_res.get(sym)),
            "价研究+费DB": (price_res[sym], db_fund.get(sym)),
            "价DB+费研究": (db_price[sym], fund_res.get(sym)),
            "价DB+费DB": (db_price[sym], db_fund.get(sym)),
        }
        rows_out = {}
        for label, (px, fd) in combos.items():
            c = px.dropna()
            if len(c) < 300:
                rows_out[label] = {"overlap_days": 0, "verdict": "价源不够"}
                continue
            g = tom_gross(c)
            r = trade_returns(c, g, fd)
            prod = series_to_dict(r)
            rows_out[label] = compare(prod, res_rets[fam])
        out[fam] = {"combos": rows_out,
                    "note": "研究侧 = S-596(close.json 收盘 + 月均资金费);生产侧 = 本脚本的生产公式"}
    return out


# ── 核心这条链的来源核对 ──────────────────────────────────────────────────────
def core_source_check(P: dict, res: dict) -> dict:
    """① 研究核心(t342 的 cap_pit24)是否等于今天库里的 core_variants_daily.cap_pit24
    (导出之后库有没有被修订);② 生产核心(core_u_replay)与研究核心差多少;
    ③ 把生产 X1V 的公式改用**研究核心**(cap_pit24)重算,能不能回到研究 X1V
    (⇒ X1V 的差全在核心源,不在资金费/成本)。"""
    rows = fetch_paged("core_variants_daily", "d,nav",
                        [("arm", "eq.cap_pit24"), ("d", f"lte.{CUTOFF}")], "d")
    cap_nav = {D(r["d"]): float(r["nav"]) for r in rows if r.get("nav") is not None}
    cap = pd.Series([cap_nav[d] for d in sorted(cap_nav)],
                    index=pd.to_datetime([d for d in sorted(cap_nav)]))
    g = trade_path(cap, "rally", 0.0, "l20", True)
    x1v_on_cap = series_to_dict(trade_returns(cap, g, P["fund"].get("CORE")))
    return {
        "core_variants_cap_pit24_span": ([min(cap_nav).isoformat(), max(cap_nav).isoformat()]
                                          if cap_nav else None),
        "研究核心(t342 cap_pit24) vs 今天库 core_variants.cap_pit24":
            compare(daily_from_nav(cap_nav), res.get("core", {})),
        "生产核心(core_u_replay) vs 研究核心(cap_pit24)":
            compare(daily_from_nav(P["core_nav"]), res.get("core", {})),
        "X1V(用研究核心 cap_pit24 重算) vs 研究 X1V":
            compare(x1v_on_cap, res.get("x1v", {})),
    }


def style_revision_check(P: dict, res_nav: dict) -> dict:
    """研究面板是 11-14 的导出快照;这里查今天库的 ret 与快照隐含的 ret 是否已不一致(=库被改过)。"""
    out: dict[str, Any] = {}
    for style, rr in P["style_rets"].items():
        nav = res_nav.get(f"style_{style}", {})
        ds = sorted(nav)
        n, mx = 0, 0.0
        for i in range(1, len(ds)):
            d0, d1 = ds[i - 1], ds[i]
            if not nav[d0] or d1 not in rr:
                continue
            dd = abs(nav[d1] / nav[d0] - 1 - rr[d1])
            if dd > 1e-12:
                n += 1
                mx = max(mx, dd)
        out[f"style_{style}"] = {"快照隐含ret与今天库ret不一致的天数": n, "最大不一致": mx}
    return out


# ── 主流程 ───────────────────────────────────────────────────────────────────
MEMBERS = [
    ("X1V", "x1v",
     "生产:multiplier_daily core_u_replay 净值 + TOM_ARMS['CORE_X1V'] + BTC 资金费(按天求和×365)",
     "研究:t348_r4_legs.csv crypto_nav(2021-07-13 起换 t342 官方腿;核心 = core_variants_daily cap_pit24)"),
    ("核心", "core",
     "生产:multiplier_daily core_u_replay 净值",
     "研究:t342_daily.csv core_nav_1_cap_pit24 = core_variants_daily.cap_pit24 的 ret 累乘"),
    ("R-v2", "rv2",
     "生产:r_money_daily 净值",
     "研究:t348_r3_rv2_curve.csv = t353_engine.simulate(t197 票 / f 0.005 / cap 0.40 / 名额 14)"),
    ("ACWI", "equity",
     "生产:ohlcv_daily eodhd ACWI 收盘(周末 0)",
     "研究:t348_r4_legs.csv equity_close ← t342_daily.csv equity_close_acwi(eodhd ACWI)"),
    ("XAUUSD", "gold",
     "生产:ohlcv_daily eodhd XAUUSD 收盘(周末 0)",
     "研究:t348_r4_legs.csv gold_close ← t342_daily.csv gold_close_xauusd(eodhd XAUUSD)"),
    ("style_ai", "style_ai", "生产:style_index_pit_daily ai/cap 的 ret", "研究:s869_extra_panel_a.csv style_ai(T-392 同源)"),
    ("style_app", "style_app", "生产:style_index_pit_daily app/cap 的 ret", "研究:s869_extra_panel_a.csv style_app(T-392 同源)"),
    ("style_defi", "style_defi", "生产:style_index_pit_daily defi/cap 的 ret", "研究:s869_extra_panel_a.csv style_defi(T-392 同源)"),
    ("style_infra_tokenization", "style_infra_tokenization", "生产:style_index_pit_daily infra_tokenization/cap 的 ret", "研究:s869_extra_panel_a.csv style_infra_tokenization(T-392 同源)"),
    ("style_meme", "style_meme", "生产:style_index_pit_daily meme/cap 的 ret", "研究:s869_extra_panel_a.csv style_meme(T-392 同源)"),
    ("style_second_l1_l2", "style_second_l1_l2", "生产:style_index_pit_daily second_l1_l2/cap 的 ret", "研究:s869_extra_panel_a.csv style_second_l1_l2(T-392 同源)"),
    ("style_top_l1", "style_top_l1", "生产:style_index_pit_daily top_l1/cap 的 ret", "研究:s869_extra_panel_a.csv style_top_l1(T-392 同源)"),
    ("tom_pd13_btc", "tom_pd13_btc",
     "生产:tom_gross + trade_returns 作用于 asset_mcap_daily BTC 收盘 + funding_history 按天求和×365",
     "研究:s869_extra_panel_a.csv tom_pd13_btc = S-596(close.json 收盘 + 月均资金费)"),
    ("tom_pd13_eth", "tom_pd13_eth",
     "生产:tom_gross + trade_returns 作用于 asset_mcap_daily ETH 收盘 + funding_history 按天求和×365",
     "研究:s869_extra_panel_a.csv tom_pd13_eth = S-596(close.json 收盘 + 月均资金费)"),
]


def main() -> None:
    P = load_production()
    prod = production_members(P)
    res_nav = load_research_nav()
    res = {k: daily_from_nav(v) for k, v in res_nav.items()}

    members: dict[str, Any] = {}
    for name, fam, src_p, src_r in MEMBERS:
        p = prod.get(name, {})
        r = res.get(fam, {})
        members[name] = {
            "prod_source": src_p, "res_source": src_r,
            "prod_span": [min(p).isoformat(), max(p).isoformat()] if p else None,
            "res_span": [min(r).isoformat(), max(r).isoformat()] if r else None,
            "parity_full_overlap": compare(p, r),
            "parity_in_prod_read_window": compare(p, r, since=D(PROD_SINCE)),
        }

    decomp = pd13_decomposition()
    corechk = core_source_check(P, res)
    stylechk = style_revision_check(P, res_nav)

    out = {
        "task": "T-411",
        "what": "纸面账成员的前向来源对账:生产序列 vs 研究面板",
        "cutoff": CUTOFF,
        "prod_read_window": {"since": PROD_SINCE, "book_start": BOOK_START,
                             "note": "load_inputs 的 since = _shift(START, -HISTORY_DAYS)(state_book.py:281);"
                                     "X1V/核心/PD13 的生产源另有下限 TOM_WARM_FROM=2024-01-01"},
        "criteria": {"median_abs_diff_lt_bp": 1.0, "cum_diff_lt": 0.02},
        "members": members,
        "pd13_decomposition": decomp,
        "core_source_check": corechk,
        "style_snapshot_vs_db": stylechk,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n== 逐日对账(生产 vs 研究)==")
    print(f"{'成员':<26}{'重叠':<24}{'天数':>6}{'中位差bp':>10}{'p95差bp':>10}{'最大差bp':>11}{'累计差':>10}{'相关':>8}  判")
    for name, fam, _sp, _sr in MEMBERS:
        c = members[name]["parity_full_overlap"]
        if not c.get("overlap_days"):
            print(f"{name:<26}{'无重叠':<24}{0:>6}{'':>10}{'':>10}{'':>11}{'':>10}{'':>8}  无重叠")
            continue
        corr = "n/a" if c["corr"] is None else f"{c['corr']:.4f}"
        print(f"{name:<26}{c['overlap_start'] + '→' + c['overlap_end']:<24}{c['overlap_days']:>6}"
              f"{c['abs_diff_median_bp']:>10.2f}{c['abs_diff_p95_bp']:>10.2f}{c['abs_diff_max_bp']:>11.2f}"
              f"{c['cum_diff'] * 100:>9.2f}%{corr:>8}  {c['verdict']}")
    print("\n== 分解 ==")
    for fam, blk in decomp.items():
        for lab, c in blk["combos"].items():
            if not c.get("overlap_days"):
                print(f"  {fam} · {lab}: 无重叠")
                continue
            print(f"  {fam} · {lab}: 天数 {c['overlap_days']} · 中位差 {c['abs_diff_median_bp']:.4f}bp · "
                  f"最大 {c['abs_diff_max_bp']:.1f}bp · 累计差 {c['cum_diff'] * 100:.2f}pp · {c['verdict']}")
    for k, c in corechk.items():
        if isinstance(c, dict) and c.get("overlap_days"):
            print(f"  [核心链] {k}: 天数 {c['overlap_days']} · 中位差 {c['abs_diff_median_bp']:.2f}bp · "
                  f"最大 {c['abs_diff_max_bp']:.1f}bp · 累计差 {c['cum_diff'] * 100:.2f}pp · {c['verdict']}")
        elif isinstance(c, dict):
            print(f"  [核心链] {k}: {c.get('verdict', '')}")
        else:
            print(f"  [核心链] {k}: {c}")
    print(f"\n产物:{OUT}")


if __name__ == "__main__":
    main()
