"""组合层 0–1 风险敞口(可空仓)—— T-070 / S-511。

## 为什么有这本账

Jazz 10-08:「组合层是可以空仓的,是策略层不空而已。」③ 的 0.7–1.3× 是策略层的定义;组合层另有一个
0–1 的风险敞口旋钮,其余放现金等价物。2025-01 → 2026-10 ① −21% / 回撤 −60%,③ v1 救不了(S-505)。
S-506 / S-507 / S-508 的探索:这段回撤是**低波动阴跌**,价格与波动维度看不见;两窗口方向一致的特征是
「低波 + 缩量」「美股强而币弱」「山寨领涨」「资金费率」。

## 预注册(2026-10-08 定下;改任何一项 = 新起点,旧记录留档)

    输入    全部是 d 收盘可知的值,决定 d+1 的敞口:
            vol_pct_3y / style_rel_majors_30d(state_daily)· 成交额比 = BTC+ETH 成交额 30 日均 / 180 日均
            SPY 21 个交易日收益 · 资金费率 7 日均(binance_perp 5 主流,年化;2024-02 前没有 ⇒ 不知道)
            ① 的 30 日收益
    旗标    死市    vol_pct_3y ≤ 0.30 且 成交额比 < 0.80        −1
            脱钩    SPY 21 日 > +2% 且 ① 30 日 < −5%           −1
            山寨热  主流相对山寨 < −3%                          −1
            拥挤    资金费率 > 10.95%(默认基准)               −1
            出清    资金费率 < 0                                 +1
            读不到的输入不举旗(不把「不知道」当信号)
    敞口    分数 ≥ 0 ⇒ 1.0;= −1 ⇒ 0.5;≤ −2 ⇒ 0;其余现金等价物 4% 年化;|Δx| × 10 bps
    对照    ① 本身 · **同平均仓位恒定持有**(S-506:跌市里少持仓本身就像择时)·
            随机择时 = x 序列按 20 天一块重排 1,000 次(保留仓位分布与大致换手)
    窗口    2023–2024 / 2025-01-01 → 起点前一天 / 起点后前向

## 必须写在最前面的偏差

阈值与变量是**看过 2023–24 与 2025–26 两段之后**选的(S-508)—— 回放两段都不是证据,只是描述;
**前向是唯一干净的检验**。照 Jazz 10-07「不等,每天修正」:前向每天记,修正只改流程与数据,改规则 = 新起点。
① 的 24 名是今天的名单回填(幸存者偏差),对组合层与 ① 同时成立。

## ④ 第二条腿

④ 的日序列还不在库里(C 的 5 spec 等权只有汇总数)。lane-c 交付 `research/series/strategy4_blend_daily.json`
(T-071)之后,评估里自动加 w4 = 0.25 / 0.5 两档;没有就写「未交付」,不拿汇总数顶替。

## 判活判据(规则 5b ②)

    select max(d) from portfolio_layer_daily where arm = 'pl_v2_replay';   -- 应 = ① 回放的最新一天
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

TABLE = "portfolio_layer_daily"
WRITES_TABLES = (TABLE,)
ARM, REPLAY_ARM, V1CASH_ARM = "pl_v2", "pl_v2_replay", "pl_v1cash_replay"
CASH_ANN = 0.04
SWITCH_COST_BPS = 10.0
REPLAY_START = pd.Timestamp("2023-01-02")
HOLDOUT_START = pd.Timestamp("2025-01-01")
INCEPTION = pd.Timestamp("2026-10-08")
FUNDING_BASE_ANN = 0.1095
CODE_REF = "T-070 portfolio layer v2"
S4_FILE = Path(__file__).resolve().parents[3] / "research" / "series" / "strategy4_blend_daily.json"

FLAGS = ("dead_market", "decoupled", "alt_froth", "crowded", "flushed")


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def flags_for(row: dict) -> dict[str, Optional[int]]:
    """纯函数。每个旗:−1 / +1 举旗,0 不举,None = 输入读不到(不举)。"""
    vp, vr, spy, c30 = _f(row.get("vol_pct_3y")), _f(row.get("vratio")), _f(row.get("spy21")), _f(row.get("core30"))
    mr, fu = _f(row.get("maj_rel")), _f(row.get("fund7"))
    return {
        "dead_market": None if vp is None or vr is None else (-1 if vp <= 0.30 and vr < 0.80 else 0),
        "decoupled": None if spy is None or c30 is None else (-1 if spy > 0.02 and c30 < -0.05 else 0),
        "alt_froth": None if mr is None else (-1 if mr < -0.03 else 0),
        "crowded": None if fu is None else (-1 if fu > FUNDING_BASE_ANN else 0),
        "flushed": None if fu is None else (1 if fu < 0 else 0),
    }


def exposure(flags: dict[str, Optional[int]]) -> tuple[int, float]:
    score = sum(v for v in flags.values() if v is not None)
    return score, (1.0 if score >= 0 else 0.5 if score == -1 else 0.0)


def v1cash(row: dict) -> float:
    """S-506 的对照:③ v1 的状态,下行且高波 ⇒ 空仓。读不到 ⇒ 1.0。"""
    d, vp = _f(row.get("dist_200")), _f(row.get("vol_pct_3y"))
    if d is None or vp is None:
        return 1.0
    return 0.0 if (d <= 0 and vp > 0.5) else 1.0


def apply_exposure(core_ret: pd.Series, x_prev: pd.Series) -> pd.DataFrame:
    """纯函数。x_prev(d) = d−1 收盘定下、作用于 d 的敞口,夹在 [0, 1]。"""
    x = x_prev.reindex(core_ret.index).fillna(1.0).clip(0.0, 1.0)
    cost = x.diff().abs().fillna(0.0) * SWITCH_COST_BPS / 1e4
    ret = x * core_ret + (1 - x) * CASH_ANN / 365.0 - cost
    return pd.DataFrame({"x": x, "ret": ret, "cost": cost, "nav": (1 + ret).cumprod()})


def state_frame(st: pd.DataFrame, quote_vol: pd.Series, spy_close: pd.DataFrame, fund_daily: pd.Series,
                core_ret: pd.Series) -> pd.DataFrame:
    """纯函数。所有输入按日历日对齐,每个值都只用 d 及以前。

    st:列 vol_pct_3y / dist_200 / style_rel_majors_30d · quote_vol:BTC+ETH 当日成交额 ·
    spy_close:列 = 源(yfinance / eodhd),值 = 收盘,只有交易日 · fund_daily:资金费率当日均值(年化) ·
    core_ret:① 日收益"""
    days = pd.date_range(min(core_ret.index.min(), st.index.min()), core_ret.index.max(), freq="D")
    out = pd.DataFrame(index=days)
    for c, name in (("vol_pct_3y", "vol_pct_3y"), ("dist_200", "dist_200"), ("style_rel_majors_30d", "maj_rel")):
        out[name] = st[c].reindex(days) if c in st.columns else np.nan
    qv = quote_vol.reindex(days)
    out["vratio"] = qv.rolling(30, min_periods=25).mean() / qv.rolling(180, min_periods=150).mean()
    r21 = None
    for src in ("yfinance", "eodhd"):                       # 同源内算收益,不跨源拼价格
        if src in spy_close.columns:
            s = spy_close[src].dropna()
            rr = (s / s.shift(21) - 1).reindex(days, method="ffill")
            r21 = rr if r21 is None else r21.combine_first(rr)
    out["spy21"] = r21 if r21 is not None else np.nan
    out["fund7"] = fund_daily.reindex(days).rolling(7, min_periods=5).mean()
    lr = np.log1p(core_ret.reindex(days))
    out["core30"] = np.expm1(lr.rolling(30, min_periods=28).sum())
    return out


def _stats(r: pd.Series) -> dict[str, Optional[float]]:
    if len(r) < 2:
        return {"n": len(r), "total": None, "sharpe": None, "maxdd": None}
    nav = (1 + r).cumprod()
    sd = float(r.std())
    return {"n": int(len(r)), "total": round(float(nav.iloc[-1] - 1), 5),
            "sharpe": round(float(r.mean() / sd * math.sqrt(365)), 3) if sd > 0 else None,
            "maxdd": round(float((nav / nav.cummax() - 1).min()), 5)}


def _window_eval(r1: pd.Series, x_prev: pd.Series, s4: Optional[pd.Series]) -> dict[str, Any]:
    from src.data.signals.multiplier import random_timing_pct
    book = apply_exposure(r1, x_prev)
    avg_x = float(book["x"].mean())
    const = apply_exposure(r1, pd.Series(avg_x, index=r1.index))
    out = {"core": _stats(r1), "layer": _stats(book["ret"]), "avg_exposure": round(avg_x, 3),
           "same_exposure_constant": _stats(const["ret"]),
           "excess_vs_constant": (round(_stats(book["ret"])["total"] - _stats(const["ret"])["total"], 5)
                                  if len(r1) >= 2 else None),
           **random_timing_pct(r1, book["x"], pd.Series(dtype=float))}
    if s4 is not None:
        s = s4.reindex(r1.index)
        if s.notna().mean() >= 0.95:
            out["with_strategy4"] = {f"w4_{w}": _stats((1 - w) * book["ret"] + w * s.fillna(0.0))
                                     for w in (0.25, 0.5)}
        else:
            out["with_strategy4"] = f"④ 序列只覆盖本窗口 {s.notna().mean():.0%} 的日子 —— 不算"
    return out


def evaluate(core_ret: pd.Series, x_prev: pd.Series, end: pd.Timestamp,
             s4: Optional[pd.Series] = None) -> dict[str, Any]:
    windows = {"in_sample_2023_2024": (REPLAY_START, HOLDOUT_START - pd.Timedelta(days=1)),
               "holdout_2025_to_inception": (HOLDOUT_START, INCEPTION),
               "forward": (INCEPTION + pd.Timedelta(days=1), end)}
    out: dict[str, Any] = {"caveat": "阈值看过 2023–26 才定:回放是描述,前向才是检验(S-508)"}
    for name, (lo, hi) in windows.items():
        r1 = core_ret[(core_ret.index >= lo) & (core_ret.index <= hi)]
        out[name] = _window_eval(r1, x_prev, s4) if len(r1) >= 2 else {"n": int(len(r1))}
    if s4 is None:
        out["strategy4"] = "④ 日序列未交付(T-071)—— 不用汇总数顶替"
    return out


def build_rows(core_ret: pd.Series, state: pd.DataFrame, end: pd.Timestamp,
               s4: Optional[pd.Series] = None) -> tuple[list[dict], dict[str, Any]]:
    """纯函数。state = state_frame(...) 的输出。"""
    recs = state.to_dict("index")
    fl = {d: flags_for(r) for d, r in recs.items()}
    sc = {d: exposure(f) for d, f in fl.items()}
    x_at = pd.Series({d: v[1] for d, v in sc.items()}, dtype=float)
    x_prev = x_at.shift(1, freq="D")
    v1_prev = pd.Series({d: v1cash(r) for d, r in recs.items()}, dtype=float).shift(1, freq="D")
    core_ret = core_ret[(core_ret.index >= REPLAY_START) & (core_ret.index <= end)]
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []

    def emit(arm: str, book: pd.DataFrame, with_flags: bool) -> None:
        for d, b in book.iterrows():
            prev = d - pd.Timedelta(days=1)                 # 作用于 d 的敞口来自 d−1 的旗
            f = fl.get(prev) if with_flags else None
            rows.append({"d": d.date().isoformat(), "arm": arm, "x": float(b["x"]),
                         "ret": round(float(b["ret"]), 8), "nav": round(float(b["nav"]), 8),
                         "cost": round(float(b["cost"]), 8),
                         "score": sc[prev][0] if (with_flags and prev in sc) else None,
                         "flags": f, "inception": INCEPTION.date().isoformat(), "code_ref": CODE_REF,
                         "computed_at": now})

    emit(REPLAY_ARM, apply_exposure(core_ret, x_prev), True)
    emit(V1CASH_ARM, apply_exposure(core_ret, v1_prev), False)
    fwd = core_ret[core_ret.index > INCEPTION]
    if len(fwd):
        emit(ARM, apply_exposure(fwd, x_prev), True)
    ev = evaluate(core_ret, x_prev, end, s4)
    ev["v1cash_holdout"] = _window_eval(core_ret[(core_ret.index >= HOLDOUT_START) & (core_ret.index <= INCEPTION)],
                                        v1_prev, None)
    last = max(fl) if fl else None
    ev["today"] = {"d": last.date().isoformat() if last is not None else None,
                   "flags": fl.get(last), "score": sc.get(last, (None,))[0],
                   "exposure_next_day": sc.get(last, (None, None))[1]}
    return rows, ev


def load_strategy4() -> Optional[pd.Series]:
    """lane-c 交付的 ④ 日收益(T-071)。格式 {"rows": [{"d": "YYYY-MM-DD", "ret": float}, ...]}。没有 ⇒ None。"""
    if not S4_FILE.exists():
        return None
    data = json.loads(S4_FILE.read_text(encoding="utf-8"))
    rows = data.get("rows") if isinstance(data, dict) else data
    s = pd.Series({pd.Timestamp(r["d"]): _f(r.get("ret")) for r in rows or []}, dtype=float).dropna().sort_index()
    return s if len(s) else None


async def run_once() -> dict[str, Any]:
    """读 ① 回放(multiplier_daily core_replay)与状态输入,回放 2023 起 + 前向,整条 upsert。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all

    start = (REPLAY_START - pd.Timedelta(days=200)).date().isoformat()
    core = await _read_all("multiplier_daily", {"select": "d,ret", "arm": "eq.core_replay", "order": "d.asc"})
    if not core:
        return {"ok": False, "refused": True, "written": 0, "reason": "① 回放(multiplier_daily core_replay)读到 0 行"}
    core_ret = pd.Series({pd.Timestamp(r["d"]): float(r["ret"]) for r in core}).sort_index()
    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    if core_ret.index.max() < target:
        return {"ok": False, "refused": True, "written": 0,
                "reason": f"① 回放只到 {core_ret.index.max().date()},还没到 {target.date()} —— 等 ③ 那一轮先写"}

    st_rows = await _read_all("state_daily", {"select": "d,feature,value", "entity": "eq.panel",
                                              "feature": "in.(vol_pct_3y,dist_200,style_rel_majors_30d)",
                                              "d": f"gte.{start}", "order": "d.asc"})
    st = pd.DataFrame(st_rows)
    st["d"] = pd.to_datetime(st["d"])
    st = st.pivot_table(index="d", columns="feature", values="value")

    ov = await _read_all("ohlcv_daily", {"select": "trade_date,symbol,close,volume", "source": "eq.binance_hist",
                                         "symbol": "in.(BTC,ETH)", "trade_date": f"gte.{start}",
                                         "order": "trade_date.asc"})
    qv = pd.DataFrame(ov)
    qv["trade_date"] = pd.to_datetime(qv["trade_date"])
    quote_vol = (qv["close"].astype(float) * qv["volume"].astype(float)).groupby(qv["trade_date"]).sum()

    sp = await _read_all("ohlcv_daily", {"select": "trade_date,source,close", "symbol": "eq.SPY",
                                         "source": "in.(yfinance,eodhd)", "trade_date": f"gte.{start}",
                                         "order": "trade_date.asc"})
    spd = pd.DataFrame(sp)
    spd["trade_date"] = pd.to_datetime(spd["trade_date"])
    spy_close = spd.pivot_table(index="trade_date", columns="source", values="close")

    fr = await _read_all("funding_history", {"select": "funding_time,funding_rate", "venue": "eq.binance_perp",
                                             "symbol": "in.(BTC,ETH,SOL,XRP,BNB)", "funding_time": f"gte.{start}",
                                             "order": "funding_time.asc"})
    fd = pd.DataFrame(fr)
    fund_daily = pd.Series(dtype=float)
    if len(fd):
        fd["d"] = pd.to_datetime(fd["funding_time"].str[:10])
        fund_daily = fd.groupby("d")["funding_rate"].mean().astype(float) * 3 * 365

    state = state_frame(st, quote_vol, spy_close, fund_daily, core_ret)
    rows, ev = build_rows(core_ret, state, target, load_strategy4())
    res = await supabase_upsert_table(TABLE, rows, on_conflict="d,arm")
    if not res.ok:
        return {"ok": False, "refused": False, "written": 0, "reason": f"写入失败:{res.why}"}
    return {"ok": True, "refused": False, "written": len(rows), "reason": f"回放至 {target.date()}", "eval": ev}
