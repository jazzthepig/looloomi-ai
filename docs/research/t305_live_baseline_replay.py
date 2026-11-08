#!/usr/bin/env python3
"""T-305 —— 真钱基线 v1(X1V 加密腿 + SPY + GLD + 现金)在 2021-07-13 → 2026-11-07 的回放。

只读:全部数据来自 Supabase 只读 SELECT;不改代码、不做 DDL、不入库、不改规则。
统计:零分布 / 分位 / 盈亏一律走 `src/data/evaluation/apparatus.py`;
      X1V 规则走仓库内核 `src/data/signals/tom.py`(与 T-146 / T-157 同一核)。
产物:`docs/research/T-305_live_baseline_replay.md` + `docs/research/t305_results.json`

════════════════════════════════════════════════════════════════════════════
预注册(先写后算,只算一次,不扫参数)—— 2026-11-08 lane-c
════════════════════════════════════════════════════════════════════════════
窗口        2021-07-13 → 2026-11-07(含端点)
账户        30% X1V 加密腿 + 27% SPY(代理 SPYX) + 19% GLD(代理 XAUT0) + 24% 现金
            日再平衡到上述权重(收盘权重口径;当日各腿收益线性加权)
①           core_nav() 口径:core_variants_daily.cap_pit24(日 ret,≤2026-10-02)
            + core_cap_daily.cap_a1(2026-10-02→10-12)+ core_cap_daily.cap_a1_u(>10-12)
X1V 口径 A  【仓库内核 = T-146/T-157 的定义,主口径】
            tom.trade_path(close,"rally",0.0,exit_mode="l20",vol=True) → g
            腿 = 0.5·g_BTC + 0.5·g_ETH(BTC/ETH 各半,= executor.SLEEVES)
            收益 = tom.trade_returns(close, g)(10bp 换手成本;资金费默认 0.10/yr,
            只作用于 >1 的加仓部分);g[t] 收盘定、t+1 生效
X1V 口径 B  【卡面散文规则 = 卡里写的,口径出入,对照用】
            进场:收盘 > 前 20 日最高收盘(t 不含)⇒ 次日收盘进场
            出场:收盘 < 200 日均线 或 收盘 ≤ 进场价 × 0.91 ⇒ 次日收盘出场
            空仓持现金(收益 0);BTC 单币
数据源      BTC/ETH:ohlcv_daily(source=binance_hist);SPY/GLD:ohlcv_daily(source=eodhd)
            state_daily(entity=panel):dist_200 / vol_pct_3y / breadth_above_ma50
trend_vol 格 rr_matrix 口径:trend = (dist_200 > 0) ? UP : DOWN;
            vol:vol_pct_3y < 1/3 → LO,< 2/3 → MID,否则 HI;任一 NaN → UNKNOWN(不入格)
下跌簇      「BTC 离 200 日线 0~10% 之内」且「广度(breadth_above_ma50) ≤ 0.10」
            → 连续满足为 1 簇,取簇首日;簇首日之后 28 天内账户相对 ① 的回撤差
            簇 < 8 → 只报不判
压力表      SPY 21 个交易日收益 ≤ −5% 的日子之后 21 个交易日:SPY 腿 / GLD 腿 / 账户
            收益的 p10 / p50 / p90;另单列 2022-01→2022-06、2025-03→2025-04
零信号对照  同进场次数、同持有天数,随机日期抽样 1,000 次(apparatus.random_dates_like,
            同年分层;null_distribution + percentile_of),种子 305
            → 报 X1V 腿总收益与最大回撤落在第几分位
附加        去掉账户最好 5 天 / 最差 5 天后的总收益
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull, long_return, null_distribution, percentile_of, random_dates_like,
)
from src.data.signals.tom import trade_path, trade_returns  # noqa: E402

# ── 预注册常量 ───────────────────────────────────────────────────────────────
WIN_START, WIN_END = "2021-07-13", "2026-11-07"
ANCHOR_START, ANCHOR_END = "2021-01-01", "2026-10-18"   # T-146/T-157 的窗口(锚)
W_CRYPTO, W_SPY, W_GLD, W_CASH = 0.30, 0.27, 0.19, 0.24
SEED, N_NULL = 305, 1000
CARD_ENTER_LB, CARD_EXIT_DROP = 20, 0.09
MA_N = 200
CLUSTER_FWD = 28
SPY_STRESS_LB, SPY_STRESS_FWD, SPY_STRESS_THR = 21, 21, -0.05
VOL_CUTS = (1.0 / 3.0, 2.0 / 3.0)
OUT_MD = os.path.join(HERE, "T-305_live_baseline_replay.md")
OUT_JSON = os.path.join(HERE, "t305_results.json")

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY —— 不读 .env,退出。")

R: dict = {}          # 结果容器
LOG: list[str] = []


def log(msg: str) -> None:
    LOG.append(msg)
    print(msg, flush=True)


# ── 只读取数 ─────────────────────────────────────────────────────────────────
def rest(table: str, extra: str) -> tuple[int, str, dict]:
    req = urllib.request.Request(
        f"{URL}/rest/v1/{table}?{extra}",
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300], {}
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}", {}


def fetch_paged(table: str, select: str, filters: list[str], order_col: str,
                limit: int = 1000) -> tuple[list[dict], str]:
    """翻页读 —— 每页 ≤ 1000 行,一律带 order=(主键),用 gt 游标推进。"""
    rows: list[dict] = []
    last = None
    total = "?"
    while True:
        extra = f"select={select}&order={order_col}.asc&limit={limit}"
        for f in filters:
            extra += f"&{f}"
        if last is not None:
            extra += f"&{order_col}=gt.{last}"
        st, body, hdrs = rest(table, extra)
        if st != 200:
            raise RuntimeError(f"{table} 取数失败 {st}: {body[:200]}")
        cr = hdrs.get("content-range", "")
        if "/" in cr:
            total = cr.split("/")[-1]
        page = json.loads(body) if body.strip() else []
        if not page:
            break
        rows.extend(page)
        last = page[-1][order_col]
        if len(page) < limit:
            break
    return rows, total


def series_from(rows: list[dict], dcol: str, vcol: str) -> pd.Series:
    s = pd.Series({str(r[dcol])[:10]: float(r[vcol]) for r in rows if r.get(vcol) is not None})
    return pd.Series({pd.Timestamp(k): v for k, v in s.items()}).sort_index()


def fetch_ohlcv(symbol: str, source: str) -> pd.Series:
    rows, total = fetch_paged("ohlcv_daily", "trade_date,close",
                              [f"symbol=eq.{symbol}", f"source=eq.{source}"], "trade_date")
    s = series_from(rows, "trade_date", "close")
    log(f"  ohlcv {symbol}/{source}: {len(s)} 行(server total={total}) "
        f"{s.index[0].date()} → {s.index[-1].date()}")
    return s


# ── 指标 ─────────────────────────────────────────────────────────────────────
def metrics(nav: pd.Series) -> dict:
    nav = nav.dropna()
    if len(nav) < 2:
        return {"n_days": int(len(nav))}
    final = float(nav.iloc[-1] / nav.iloc[0])
    days = (nav.index[-1] - nav.index[0]).days
    years = max(days / 365.25, 1e-9)
    dd = nav / nav.cummax() - 1.0
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    after = nav.loc[trough:]
    rec = after[after >= nav.loc[peak]]
    rec_d = rec.index[0] if len(rec) else None
    dur = int((rec_d - peak).days) if rec_d is not None else int((nav.index[-1] - peak).days)
    uw = (nav < nav.cummax()).to_numpy()
    best = cur = 0
    for u in uw:
        cur = cur + 1 if u else 0
        best = max(best, cur)
    return {
        "total_return": final - 1.0,
        "ann": final ** (1.0 / years) - 1.0,
        "max_dd": float(dd.min()),
        "dd_peak": str(peak.date()),
        "dd_trough": str(trough.date()),
        "dd_recovery": str(rec_d.date()) if rec_d is not None else None,
        "dd_days": dur,
        "max_underwater_days": int(best),
        "n_days": int(len(nav)),
        "final": final,
        "years": years,
    }


def pct_rank(x: float, arr) -> float:
    a = np.asarray(arr, dtype=float)
    a = a[np.isfinite(a)]
    return float((a < x).mean()) if a.size else float("nan")


def fmt_pct(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x * 100:.{nd}f}%"


# ── 主流程 ───────────────────────────────────────────────────────────────────
def main() -> None:
    log("=== 取数(只读) ===")
    btc = fetch_ohlcv("BTC", "binance_hist")
    eth = fetch_ohlcv("ETH", "binance_hist")
    spy = fetch_ohlcv("SPY", "eodhd")
    gld = fetch_ohlcv("GLD", "eodhd")

    # ①:core_nav 口径
    cv_rows, cv_total = fetch_paged("core_variants_daily", "d,ret",
                                     ["arm=eq.cap_pit24", f"d=gte.{ANCHOR_START}"], "d")
    log(f"  core_variants_daily.cap_pit24: {len(cv_rows)} 行(server total={cv_total})")
    cc_rows, _ = fetch_paged("core_cap_daily", "d,arm,nav",
                              ["arm=in.(cap_a1,cap_a1_u)"], "d")
    log(f"  core_cap_daily(cap_a1,cap_a1_u): {len(cc_rows)} 行")

    # state_daily
    sd: dict[str, pd.Series] = {}
    for feat in ("dist_200", "vol_pct_3y", "breadth_above_ma50"):
        rows, _ = fetch_paged("state_daily", "d,value",
                              ["entity=eq.panel", f"feature=eq.{feat}"], "d")
        sd[feat] = series_from(rows, "d", "value")
        log(f"  state_daily.panel.{feat}: {len(sd[feat])} 行 "
            f"{sd[feat].index[0].date() if len(sd[feat]) else '-'} → "
            f"{sd[feat].index[-1].date() if len(sd[feat]) else '-'}")

    # ── ① NAV(核心口径)──
    INCEPTION, CORE_SINCE = pd.Timestamp("2026-10-02"), pd.Timestamp("2026-10-12")
    rets: dict[pd.Timestamp, float] = {}
    for r in cv_rows:
        d = pd.Timestamp(str(r["d"])[:10])
        if d <= INCEPTION and r.get("ret") is not None:
            rets[d] = float(r["ret"])
    arms: dict[str, pd.Series] = {}
    for arm in ("cap_a1", "cap_a1_u"):
        s = pd.Series({pd.Timestamp(str(r["d"])[:10]): float(r["nav"])
                       for r in cc_rows if r["arm"] == arm and r.get("nav") is not None}).sort_index()
        arms[arm] = s
        log(f"  ① 臂 {arm}: {len(s)} 行 {s.index[0].date() if len(s) else '-'} → "
            f"{s.index[-1].date() if len(s) else '-'}")
    old = arms["cap_a1"].pct_change().dropna()
    old = old[(old.index > INCEPTION) & (old.index <= CORE_SINCE)]
    new = arms["cap_a1_u"].pct_change().dropna()
    new = new[new.index > CORE_SINCE]
    for s in (old, new):
        for d, v in s.items():
            rets[d] = float(v)
    core_rets = pd.Series(rets).sort_index()
    core_nav = (1.0 + core_rets).cumprod()
    log(f"  ① 收益点 {len(core_rets)}: {core_rets.index[0].date()} → {core_rets.index[-1].date()}")

    # ── 账户日历(BTC 日历)──
    idx = btc.loc[WIN_START:WIN_END].index
    idx = idx[(idx >= pd.Timestamp(WIN_START)) & (idx <= pd.Timestamp(WIN_END))]
    log(f"  账户日历(BTC 日历): {len(idx)} 天 {idx[0].date()} → {idx[-1].date()}")

    # ── X1V 口径 A:仓库内核 ──
    g_btc = trade_path(btc, "rally", 0.0, exit_mode="l20", vol=True)
    g_eth = trade_path(eth, "rally", 0.0, exit_mode="l20", vol=True)
    r_btc_k = trade_returns(btc, g_btc)
    r_eth_k = trade_returns(eth, g_eth)
    legA = (0.5 * r_btc_k.reindex(idx).fillna(0.0) + 0.5 * r_eth_k.reindex(idx).fillna(0.0))
    legA_nav = (1.0 + legA).cumprod()

    # 锚:2021-01-01 → 2026-10-18 的 ①(cap_pit24 单臂)——核对 T-146/T-157 的 +26.45%
    anc = core_rets.loc[(core_rets.index >= pd.Timestamp(ANCHOR_START)) &
                         (core_rets.index <= pd.Timestamp(ANCHOR_END))]
    anc_ann = float((1 + anc).prod() ** (365.25 / max((anc.index[-1] - anc.index[0]).days, 1)) - 1)
    R["anchor_cap_pit24"] = {"window": f"{ANCHOR_START}→{ANCHOR_END}", "ann": anc_ann,
                             "t146_t157_ideal_ann": 0.2645, "t146_t157_replay_ann": 0.1699}
    # 锚 2:口径 A 的 X1V 腿,零摩擦(= T-137/T-146 的「理想」口径),T-146 窗口 —— 口径核对
    anc_idx = btc.loc[ANCHOR_START:ANCHOR_END].index
    px_b = btc.pct_change().reindex(anc_idx).fillna(0.0)
    px_e = eth.pct_change().reindex(anc_idx).fillna(0.0)
    yrs = max((anc_idx[-1] - anc_idx[0]).days / 365.25, 1e-9)

    def _anchor_ann(gb: pd.Series, ge: pd.Series, wb: float = 0.5) -> float:
        z = (wb * gb.shift(1).reindex(anc_idx).fillna(0.0) * px_b +
             (1 - wb) * ge.shift(1).reindex(anc_idx).fillna(0.0) * px_e)
        return float((1.0 + z).cumprod().iloc[-1] ** (1.0 / yrs) - 1.0)

    g_btc_nv = trade_path(btc, "rally", 0.0, exit_mode="l20", vol=False)
    g_eth_nv = trade_path(eth, "rally", 0.0, exit_mode="l20", vol=False)
    R["anchor_legA_ideal"] = {
        "window": f"{ANCHOR_START}→{ANCHOR_END}",
        "ann": _anchor_ann(g_btc, g_eth),
        "ann_novol": _anchor_ann(g_btc_nv, g_eth_nv),
        "ann_btc_only_vol": _anchor_ann(g_btc, g_eth, wb=1.0),
        "ann_btc_only_novol": _anchor_ann(g_btc_nv, g_eth_nv, wb=1.0),
        "t146_t157_ideal_ann": 0.2645, "t146_t157_replay_ann": 0.1699}

    # ── X1V 口径 B:卡面散文规则(BTC 单币)──
    c = btc.loc[:WIN_END]
    ma200 = c.rolling(MA_N, min_periods=MA_N).mean()
    h20_prev = c.rolling(CARD_ENTER_LB, min_periods=CARD_ENTER_LB).max().shift(1)
    trades: list[dict] = []
    pos = False
    entry_i = entry_px = None
    for i in range(len(c)):
        d = c.index[i]
        if not pos:
            if pd.notna(h20_prev.iloc[i]) and c.iloc[i] > h20_prev.iloc[i]:
                entry_i, entry_px = i + 1, None          # 次日收盘进场
                pos = True
                entry_px = float(c.iloc[entry_i]) if entry_i < len(c) else None
                if entry_px is None:
                    pos = False
        else:
            px = float(c.iloc[i])
            hit_ma = pd.notna(ma200.iloc[i]) and px < ma200.iloc[i]
            hit_stop = entry_px is not None and px <= entry_px * (1 - CARD_EXIT_DROP)
            if hit_ma or hit_stop:
                ex_i = i + 1                              # 次日收盘出场
                if ex_i >= len(c):
                    ex_i = len(c) - 1
                trades.append({"entry_d": str(c.index[entry_i].date()),
                               "exit_d": str(c.index[ex_i].date()),
                               "entry_px": entry_px, "exit_px": float(c.iloc[ex_i]),
                               "reason": "ma200" if hit_ma else "stop9"})
                pos = False
    if pos and entry_px is not None:                      # 窗口末仍持仓 ⇒ 按末收盘平
        ex_i = len(c) - 1
        trades.append({"entry_d": str(c.index[entry_i].date()), "exit_d": str(c.index[ex_i].date()),
                       "entry_px": entry_px, "exit_px": float(c.iloc[ex_i]), "reason": "open_end"})

    # 口径 B 的逐日收益(进场收盘 → 出场收盘 之间才吃收益)
    r_btc_d = btc.pct_change().fillna(0.0)
    legB = pd.Series(0.0, index=idx)
    legB_nav = pd.Series(1.0, index=idx)
    win_idx = {d: k for k, d in enumerate(idx)}
    btc_days = list(c.index)
    btc_pos = {d: k for k, d in enumerate(btc_days)}
    for t in trades:
        ei = btc_pos.get(pd.Timestamp(t["entry_d"]))
        xi = btc_pos.get(pd.Timestamp(t["exit_d"]))
        if ei is None or xi is None:
            continue
        for u in range(ei + 1, xi + 1):                   # 持有日:进场收盘之后、出场收盘当天
            if u >= len(btc_days):
                break
            du = btc_days[u]
            if du in win_idx:
                legB.loc[du] = float(r_btc_d.iloc[u])
    legB_nav = (1.0 + legB).cumprod()
    R["card_prose_trades"] = trades
    # 规则跑在 2017 起的历史上(路径依赖,状态连续);但「进场次数」只数窗口内的
    tr_win = [t for t in trades if t["entry_d"] >= WIN_START]
    R["card_prose_n_trades"] = len(tr_win)
    R["card_prose_n_trades_total"] = len(trades)
    R["card_prose_trades"] = tr_win
    R["card_prose_exit_reasons"] = {k: sum(1 for t in tr_win if t["reason"] == k)
                                    for k in ("ma200", "stop9", "open_end")}

    # ── SPY / GLD 腿(映射到账户日历,陈旧收盘 → 收益 0)──
    def to_cal(s: pd.Series) -> pd.Series:
        m = s.reindex(s.index.union(idx)).ffill().reindex(idx)
        return m

    spy_c, gld_c = to_cal(spy), to_cal(gld)
    r_spy = spy_c.pct_change().fillna(0.0)
    r_gld = gld_c.pct_change().fillna(0.0)
    gld_live = gld_c.notna() & spy_c.notna()

    # ── 账户 ──
    def build_account(leg: pd.Series) -> pd.Series:
        return (W_CRYPTO * leg + W_SPY * r_spy + W_GLD * r_gld).reindex(idx).fillna(0.0)

    acctA = build_account(legA)
    acctB = build_account(legB)
    # 基准点统一在窗口前一天(2021-07-12 收盘)= 1.0;窗口首日的收益算在里面
    BASE = pd.Timestamp("2021-07-12")

    def nav_from_rets(r: pd.Series, base: pd.Timestamp = BASE) -> pd.Series:
        r = r.reindex(idx).fillna(0.0)
        return pd.concat([pd.Series([1.0], index=[base]), (1.0 + r).cumprod()])

    navA = nav_from_rets(acctA)
    navB = nav_from_rets(acctB)
    navAleg = nav_from_rets(legA)
    navBleg = nav_from_rets(legB)
    nav1_cal = core_nav.reindex(core_nav.index.union(idx)).ffill().reindex(idx)
    base1 = float(core_nav.asof(BASE))
    nav1 = pd.concat([pd.Series([1.0], index=[BASE]), nav1_cal / base1])

    def sub_nav(nav: pd.Series, start: str) -> pd.Series:
        i0 = nav.index[nav.index >= pd.Timestamp(start)][0]
        head = nav.loc[:i0].iloc[[-1]]          # 只留起点前那一个点(基准 = 1.0 之前的净值)
        return pd.concat([head, nav.loc[i0:]])

    R["window"] = {"start": WIN_START, "end": WIN_END, "cal_days": int(len(idx)),
                   "cal_start": str(idx[0].date()), "cal_end": str(idx[-1].date())}
    R["coverage"] = {
        "BTC": f"{btc.index[0].date()}→{btc.index[-1].date()} ({len(btc)})",
        "ETH": f"{eth.index[0].date()}→{eth.index[-1].date()} ({len(eth)})",
        "SPY": f"{spy.index[0].date()}→{spy.index[-1].date()} ({len(spy)})",
        "GLD": f"{gld.index[0].date()}→{gld.index[-1].date()} ({len(gld)})",
        "GLD_in_window_start": str(gld.index[gld.index >= pd.Timestamp(WIN_START)][0].date()),
        "SPY_last": str(spy.index[-1].date()),
        "GLD_last": str(gld.index[-1].date()),
    }
    R["account_A_canonical"] = metrics(navA)
    R["account_B_card_prose"] = metrics(navB)
    R["core_1"] = metrics(nav1)
    R["legA_canonical"] = metrics(navAleg)
    R["legB_card_prose"] = metrics(navBleg)
    R["excess_A_vs_1"] = {"total_pp": (R["account_A_canonical"]["total_return"] -
                                       R["core_1"]["total_return"]) * 100,
                          "ann_pp": (R["account_A_canonical"]["ann"] - R["core_1"]["ann"]) * 100,
                          "maxdd_pp": (R["account_A_canonical"]["max_dd"] -
                                       R["core_1"]["max_dd"]) * 100}
    R["excess_B_vs_1"] = {"total_pp": (R["account_B_card_prose"]["total_return"] -
                                       R["core_1"]["total_return"]) * 100,
                          "ann_pp": (R["account_B_card_prose"]["ann"] - R["core_1"]["ann"]) * 100,
                          "maxdd_pp": (R["account_B_card_prose"]["max_dd"] -
                                       R["core_1"]["max_dd"]) * 100}
    # 子窗口:GLD 四腿齐全(2022-08-31 → 2026-11-07)
    sub = idx[idx >= gld.index[gld.index >= pd.Timestamp(WIN_START)][0]]
    subA, sub1, subB = sub_nav(navA, str(sub[0].date())), sub_nav(nav1, str(sub[0].date())), \
        sub_nav(navB, str(sub[0].date()))
    R["sub_all_legs"] = {
        "start": str(sub[0].date()), "end": str(sub[-1].date()), "days": int(len(sub)),
        "account_A": metrics(subA), "core_1": metrics(sub1),
        "account_B": metrics(subB),
        "excess_A_total_pp": (metrics(subA)["total_return"] - metrics(sub1)["total_return"]) * 100,
        "excess_A_ann_pp": (metrics(subA)["ann"] - metrics(sub1)["ann"]) * 100,
        "excess_A_maxdd_pp": (metrics(subA)["max_dd"] - metrics(sub1)["max_dd"]) * 100,
    }

    # ── trend_vol 分格 ──
    def tv_label(d: pd.Timestamp) -> str:
        dd = sd["dist_200"].get(d, np.nan)
        vv = sd["vol_pct_3y"].get(d, np.nan)
        if pd.isna(dd) or pd.isna(vv):
            return "UNKNOWN"
        trend = "UP" if float(dd) > 0 else "DOWN"
        bucket = "LO" if vv < VOL_CUTS[0] else ("MID" if vv < VOL_CUTS[1] else "HI")
        return f"{trend}_{bucket}"

    tv = pd.Series({d: tv_label(d) for d in idx})
    r1_all = nav1.pct_change().fillna(0.0).reindex(idx).fillna(0.0)
    cells: dict[str, dict] = {}
    for lab in ["UP_LO", "UP_MID", "UP_HI", "DOWN_LO", "DOWN_MID", "DOWN_HI", "UNKNOWN"]:
        m = (tv == lab)
        if not m.any():
            cells[lab] = {"n_days": 0}
            continue
        ra = acctA[m]
        r1 = r1_all[m]
        cells[lab] = {
            "n_days": int(m.sum()),
            "first": str(idx[m][0].date()), "last": str(idx[m][-1].date()),
            "acct_A_total": float((1 + ra).prod() - 1),
            "core_1_total": float((1 + r1).prod() - 1),
            "excess_total_pp": float(((1 + ra).prod() - (1 + r1).prod()) * 100),
            "excess_daily_bps": float((ra - r1).mean() * 1e4) if m.sum() else None,
            "win_days": float((ra > r1).mean()) if m.sum() else None,
        }
    R["trend_vol_cells"] = cells
    R["trend_vol_unknown_days"] = int((tv == "UNKNOWN").sum())

    # ── 下跌簇:BTC 距 200 日线 0~10% 且 广度 ≤ 0.10 ──
    bt = btc.reindex(btc.index.union(idx)).ffill().reindex(idx)
    ma = ma200.reindex(ma200.index.union(idx)).ffill().reindex(idx)
    dist_btc = bt / ma - 1.0
    breadth = sd["breadth_above_ma50"].reindex(sd["breadth_above_ma50"].index.union(idx)).ffill().reindex(idx)
    cond = ((dist_btc >= 0.0) & (dist_btc <= 0.10) & (breadth <= 0.10)).fillna(False)
    starts: list[pd.Timestamp] = []
    prev = False
    for d, v in cond.items():
        if v and not prev:
            starts.append(d)
        prev = bool(v)
    R["cluster"] = {
        "n_qual_days": int(cond.sum()), "n_clusters": len(starts),
        "cond_desc": "0 ≤ (BTC/MA200 − 1) ≤ 0.10 且 breadth_above_ma50 ≤ 0.10",
        "dist_btc_last": float(dist_btc.iloc[-1]) if len(dist_btc) else None,
        "breadth_last": float(breadth.iloc[-1]) if len(breadth) else None,
    }
    clusters = []
    for d0 in starts:
        fwd = idx[(idx > d0)][:CLUSTER_FWD]
        if len(fwd) == 0:
            continue
        a0 = float(navA.asof(d0))
        n0 = float(nav1.asof(d0))
        segA = navA.loc[fwd]
        seg1 = nav1.loc[fwd]
        ddA = float((segA / a0 - 1).min())
        dd1 = float((seg1 / n0 - 1).min())
        clusters.append({
            "d0": str(d0.date()), "n_days": int(len(fwd)),
            "acct_dd": ddA, "core_dd": dd1, "dd_diff_pp": (ddA - dd1) * 100,
            "acct_ret": float(segA.iloc[-1] / a0 - 1), "core_ret": float(seg1.iloc[-1] / n0 - 1),
            "dist_btc": float(dist_btc.asof(d0)), "breadth": float(breadth.asof(d0)),
        })
    R["cluster"]["clusters"] = clusters
    if clusters:
        diffs = [c["dd_diff_pp"] for c in clusters]
        R["cluster"]["median_dd_diff_pp"] = float(np.median(diffs))
        R["cluster"]["mean_dd_diff_pp"] = float(np.mean(diffs))
        R["cluster"]["acct_worse_count"] = int(sum(1 for x in diffs if x < 0))

    # ── 压力表:SPY 21 日 ≤ −5% ──
    spy_ret21 = spy.pct_change(SPY_STRESS_LB)
    stress_days = spy_ret21[(spy_ret21 <= SPY_STRESS_THR) & (spy_ret21.index >= pd.Timestamp(WIN_START))
                             & (spy_ret21.index <= pd.Timestamp(WIN_END))]
    spy_days = list(spy.index)
    spy_pos = {d: k for k, d in enumerate(spy_days)}
    legs = {"SPY": r_spy, "GLD": r_gld, "ACCT_A": acctA, "ACCT_B": acctB}
    rows = []
    for d in stress_days.index:
        k = spy_pos[d]
        fw = spy_days[k + 1: k + 1 + SPY_STRESS_FWD]
        if len(fw) < SPY_STRESS_FWD:
            continue
        row = {"d": str(d.date()), "spy21": float(spy_ret21.loc[d])}
        for name, ser in legs.items():
            v = float((1 + ser.reindex(fw)).prod() - 1)
            row[name] = v
        rows.append(row)
    R["stress"] = {"n_events": len(rows), "threshold": SPY_STRESS_THR,
                   "lookback": SPY_STRESS_LB, "forward": SPY_STRESS_FWD,
                   "gld_live_from": str(gld.index[gld.index >= pd.Timestamp(WIN_START)][0].date())}
    summ = {}
    for name in ("SPY", "GLD", "ACCT_A", "ACCT_B"):
        # GLD 腿只在 GLD 有数据的窗口内统计(此前是覆盖缺口,不是 0 收益)
        src = [r for r in rows if name != "GLD" or r["d"] >= R["stress"]["gld_live_from"]]
        vals = np.array([r[name] for r in src]) if src else np.array([])
        summ[name] = {"p10": float(np.percentile(vals, 10)) if vals.size else None,
                      "p50": float(np.percentile(vals, 50)) if vals.size else None,
                      "p90": float(np.percentile(vals, 90)) if vals.size else None,
                      "n": int(vals.size)}
    R["stress"]["summary"] = summ
    # 两个指定子区间
    for lab, lo, hi in [("2022-01→2022-06", "2022-01-01", "2022-06-30"),
                        ("2025-03→2025-04", "2025-03-01", "2025-04-30")]:
        sub_rows = [r for r in rows if lo <= r["d"] <= hi]
        s2 = {}
        for name in ("SPY", "GLD", "ACCT_A", "ACCT_B"):
            src = [r for r in sub_rows if name != "GLD" or r["d"] >= R["stress"]["gld_live_from"]]
            vals = np.array([r[name] for r in src]) if src else np.array([])
            s2[name] = {"n": int(vals.size),
                        "p10": float(np.percentile(vals, 10)) if vals.size else None,
                        "p50": float(np.percentile(vals, 50)) if vals.size else None,
                        "p90": float(np.percentile(vals, 90)) if vals.size else None}
        R["stress"][lab] = {"n_events": len(sub_rows), "legs": s2,
                            "gld_covered": any(r["d"] >= R["stress"]["gld_live_from"] for r in sub_rows)}

    # ── 零信号对照(apparatus)──
    def spells_from_flags(flags: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
        out = []
        start = None
        for d, f in flags.items():
            if f and start is None:
                start = d
            elif not f and start is not None:
                out.append((start, d, int(((flags.index > start) & (flags.index < d)).sum()) + 1))
                start = None
        if start is not None:
            out.append((start, flags.index[-1], int((flags.index >= start).sum())))
        return out

    def run_null(leg_nav: pd.Series, leg_rets: pd.Series, in_market: pd.Series,
                 basket: pd.Series, label: str) -> dict:
        sp = spells_from_flags(in_market)
        if len(sp) < 2:
            return {"error": "样本不足"}
        cal = list(idx)
        pos = {str(d.date()): k for k, d in enumerate(cal)}
        hold = [s[2] for s in sp]
        elig = {i: [str(d.date()) for d in cal] for i in range(len(sp))}
        events = [(i, str(cal[min(pos[str(sp[i][0].date())], len(cal) - 1)].date())) for i in range(len(sp))]

        def build(rng) -> tuple[float, float]:
            drawn = random_dates_like(events, elig, rng)
            mask = np.zeros(len(cal), dtype=bool)
            for (key, d) in drawn:
                if d is None:
                    continue
                k = pos.get(d)
                if k is None:
                    continue
                h = hold[key]
                mask[k:k + h] = True
            rets = np.where(mask, basket.reindex(cal).fillna(0.0).to_numpy(), 0.0)
            nav = np.cumprod(1.0 + rets)
            total = float(nav[-1] - 1.0)
            dd = float((nav / np.maximum.accumulate(nav) - 1.0).min())
            return total, dd

        def fn_t(rng):
            return build(rng)[0]

        def fn_d(rng):
            return build(rng)[1]

        act_t = float(leg_nav.iloc[-1] / leg_nav.iloc[0] - 1.0)
        nav_arr = leg_nav.to_numpy()
        act_d = float((nav_arr / np.maximum.accumulate(nav_arr) - 1.0).min())
        out = {"n_spells": len(sp), "total_hold_days": int(sum(hold)),
               "actual_total": act_t, "actual_max_dd": act_d}
        try:
            nt = null_distribution(fn_t, N_NULL, SEED, actual=act_t)
            nd = null_distribution(fn_d, N_NULL, SEED, actual=act_d)
            out["null_total_pct"] = percentile_of(act_t, nt)
            out["null_dd_pct"] = percentile_of(act_d, nd)
            out["null_total_median"] = float(np.median(nt))
            out["null_dd_median"] = float(np.median(nd))
            out["null_total_min"] = float(np.min(nt))
            out["null_total_max"] = float(np.max(nt))
        except NoOpNull as e:
            out["error"] = f"NoOpNull: {e}"
        R.setdefault("nulls", {})[label] = out
        return out

    # 口径 B:进场次数 = 交易笔数,持有天数 = 每笔持有日
    in_mkt_B = pd.Series(0.0, index=idx)
    for t in trades:
        ei = btc_pos.get(pd.Timestamp(t["entry_d"]))
        xi = btc_pos.get(pd.Timestamp(t["exit_d"]))
        if ei is None or xi is None:
            continue
        for u in range(ei + 1, xi + 1):
            if u < len(btc_days) and btc_days[u] in win_idx:
                in_mkt_B.loc[btc_days[u]] = 1.0
    basketB = r_btc_d.reindex(idx).fillna(0.0)
    run_null(navBleg, legB, in_mkt_B, basketB, "B_card_prose_BTC")

    # 口径 A:进场次数 = 敞口 > 0 的连续段,持有天数 = 段长;篮子 = 50/50 BTC+ETH 持有收益
    grossA = (0.5 * g_btc.reindex(idx).ffill() + 0.5 * g_eth.reindex(idx).ffill())
    in_mkt_A = (grossA > 0).astype(float)
    basketA = (0.5 * r_btc_d.reindex(idx).fillna(0.0) +
               0.5 * eth.pct_change().reindex(idx).fillna(0.0))
    run_null(navAleg, legA, in_mkt_A, basketA, "A_canonical_BTC_ETH")

    # ── 去掉最好/最差 5 天 ──
    def drop_best_worst(r: pd.Series, k: int = 5) -> dict:
        s = r.sort_values(ascending=False)
        best = s.index[:k]
        worst = s.index[-k:]
        total = float((1 + r).prod() - 1)
        no_best = float((1 + r.drop(index=best)).prod() - 1)
        no_worst = float((1 + r.drop(index=worst)).prod() - 1)
        return {"total": total, "no_best5": no_best, "no_worst5": no_worst,
                "best5": [str(d.date()) for d in best], "worst5": [str(d.date()) for d in worst],
                "best5_contrib_pp": (total - no_best) * 100,
                "worst5_contrib_pp": (no_worst - total) * 100}

    R["account_A_drop_extremes"] = drop_best_worst(acctA)
    R["account_B_drop_extremes"] = drop_best_worst(acctB)

    # ── 写产物 ──
    R["log"] = LOG
    with open(OUT_JSON, "w") as f:
        json.dump(R, f, ensure_ascii=False, indent=1, default=str)
    log(f"→ {OUT_JSON}")
    write_md()
    log(f"→ {OUT_MD}")


# ── 报告 ─────────────────────────────────────────────────────────────────────
def write_md() -> None:
    a, b, c1 = R["account_A_canonical"], R["account_B_card_prose"], R["core_1"]
    cov = R["coverage"]
    L: list[str] = []
    A = L.append
    A("# T-305 —— 真钱基线 v1 回放(2021-07-13 → 2026-11-07)")
    A("")
    A("**Lane**:lane-c · **卡**:T-305 · **性质**:只读研究(只 SELECT,不改规则、不动钱、不入库)")
    A(f"**生成**: `docs/research/t305_live_baseline_replay.py` · 结果 json: `docs/research/t305_results.json`")
    A("")
    A("> **口径声明(最重要的一条)**:卡面写的 X1V 散文规则与仓库内核**不是同一条规则**。")
    A("> 卡面:「BTC 收盘突破前 20 日最高收盘 → 次日进场;收盘跌破 200 日均线或自进场价回落 9% → 次日出场」。")
    A("> T-146 / T-157 里的 X1V = **实盘执行内核**(`executor.target_weights` → `tom.trade_path(close,\"rally\",0.0,")
    A("> `exit_mode=\"l20\",vol=True)`,**BTC + ETH 各半**,出场是「跌破前 20 日最低收盘」而非 MA200/−9%,且带波动缩放与加仓。")
    A("> 按卡面「有出入先报出入、以那两份为准」⇒ **主口径 A = 仓库内核**,卡面散文规则作**口径 B**并列报出。")
    A("")
    A("## 0. 预注册口径(先写后算,只算一次)")
    A("")
    A("```")
    A(f"窗口      {WIN_START} → {WIN_END}(账户日历 = BTC 日历,{R['window']['cal_days']} 天)")
    A(f"账户      30% X1V + 27% SPY + 19% GLD + 24% 现金,每日再平衡")
    A(f"口径 A    tom.trade_path(rally, exit_mode=l20, vol=True);腿 = 0.5·g_BTC + 0.5·g_ETH")
    A(f"          收益 = tom.trade_returns(10bp 换手成本;资金费默认 0.10/yr 只作用在 >1 的加仓部分)")
    A(f"口径 B    BTC 单币;进场:收盘 > 前 {CARD_ENTER_LB} 日最高收盘 ⇒ 次日收盘进场;")
    A(f"          出场:收盘 < {MA_N} 日均线 或 ≤ 进场价 × {1 - CARD_EXIT_DROP:.2f} ⇒ 次日收盘出场;空仓持现金")
    A(f"①         core_nav():cap_pit24(≤2026-10-02)+ cap_a1(→10-12)+ cap_a1_u(>10-12)")
    A(f"trend_vol rr_matrix 口径:dist_200>0 ⇒ UP;vol_pct_3y <1/3 LO / <2/3 MID / else HI;NaN ⇒ UNKNOWN")
    A(f"下跌簇    0 ≤ (BTC/MA200−1) ≤ 0.10 且 breadth_above_ma50 ≤ 0.10;连续满足为 1 簇,取簇首日;簇<8 只报不判")
    A(f"压力表    SPY 21 交易日收益 ≤ −5% 的日子之后 21 交易日")
    A(f"零信号    同进场次数 / 同持有天数,随机日期 1,000 次(apparatus.random_dates_like 同年分层),种子 {SEED}")
    A("```")
    A("")
    A("## 1. 数据覆盖(实测)")
    A("")
    A("| 序列 | 覆盖 | 备注 |")
    A("|---|---|---|")
    A(f"| BTC(binance_hist) | {cov['BTC']} | 与 `core_cap.PRICE_SOURCE` 同源 |")
    A(f"| ETH(binance_hist) | {cov['ETH']} | 口径 A 需要 |")
    A(f"| SPY(eodhd) | {cov['SPY']} | 末日 {cov['SPY_last']} |")
    A(f"| GLD(eodhd) | {cov['GLD']} | **起点 {cov['GLD_in_window_start']}** —— 窗口前 13.5 个月没有 GLD |")
    A(f"| ①(cap_pit24 + 前向臂) | {R['core_1']['n_days']} 天 | 口径同 `registry.core_nav()` |")
    A("")
    A(f"> **GLD 覆盖不足的处理**:GLD 在窗口内只从 **{cov['GLD_in_window_start']}** 起有数据,"
      f"此前的 19% 权重按**现金**处理(不是插值、不是回填)。因此另报一个**四腿齐全**的子窗口 "
      f"{R['sub_all_legs']['start']} → {R['sub_all_legs']['end']}({R['sub_all_legs']['days']} 天)。")
    A("")
    A("### 1.1 口径锚:能不能复现 T-146/T-157")
    A("")
    an = R["anchor_cap_pit24"]
    a2 = R.get("anchor_legA_ideal", {})
    A(f"- ① 的 `cap_pit24` 单臂在 **{an['window']}** 的年化 = **{fmt_pct(an['ann'])}**;"
      f"T-146/T-157 记的「理想 +26.45% / 回放 +16.99%」是 **X1V 腿**(BTC+ETH)的数,不是 ① 的数 —— 两者不可直接对账。")
    if a2:
        A(f"- **口径校验**:同一窗口、同一核(`tom.trade_path`,零摩擦)下,本卡算出的 X1V 腿年化 = "
          f"**{fmt_pct(a2['ann'])}**(含波动缩放)/ **{fmt_pct(a2.get('ann_novol'))}**(不含波动缩放)/ "
          f"**{fmt_pct(a2.get('ann_btc_only_vol'))}**(只 BTC);T-146/T-157 记的「理想」= **+26.45%**。"
          f"→ **同量级但没逐条复现(差 {(a2['ann'] - 0.2645) * 100:+.2f}pp/年)**:我用的是仓库当前的内核,"
          f"T-146/T-157 的「理想」口径细节(入场/对齐/是否含加仓)我没能逐字复现 ⇒ "
          f"**本卡的绝对数与那两份不可直接对账,只能当同族规则看**。")
        A("  - 已查到的口径差:价格源不同 —— T-137/T-146 用 `asset_mcap_daily`(CoinGecko),"
          "本卡用 `ohlcv_daily`(binance_hist);此外「理想」是否含加仓/对齐细节我没有逐字复现。")
    A("- 本卡没有重跑执行器回放(那部分拖累 T-146 已量),所以**本卡的 X1V 腿是规则级(理想)口径,不含执行拖累**。")
    A("")
    A("## 2. 账户 vs ①(主结果)")
    A("")
    A("| 口径 | 总收益 | 年化 | 最大回撤 | 回撤峰→谷→恢复 | 水下最长 | 相对 ① 总收益 | 相对 ① 最大回撤 |")
    A("|---|---|---|---|---|---|---|---|")
    for nm, m, ex in (("A(仓库内核)", a, R["excess_A_vs_1"]),
                      ("B(卡面散文)", b, R["excess_B_vs_1"])):
        rec = f"{m.get('dd_peak')} → {m.get('dd_trough')} → {m.get('dd_recovery') or '未恢复'}({m['dd_days']}d)"
        A(f"| {nm} | **{fmt_pct(m['total_return'])}** | {fmt_pct(m['ann'])} | "
          f"**{fmt_pct(m['max_dd'])}** | {rec} | {m.get('max_underwater_days')}d | "
          f"{ex['total_pp']:+.2f}pp | {ex['maxdd_pp']:+.2f}pp |")
    rec1 = f"{c1.get('dd_peak')} → {c1.get('dd_trough')} → {c1.get('dd_recovery') or '未恢复'}({c1['dd_days']}d)"
    A(f"| ①(cap_pit24) | {fmt_pct(c1['total_return'])} | {fmt_pct(c1['ann'])} | {fmt_pct(c1['max_dd'])} | "
      f"{rec1} | {c1.get('max_underwater_days')}d | — | — |")
    A("")
    sa = R["sub_all_legs"]
    A(f"**四腿齐全子窗口 {sa['start']} → {sa['end']}({sa['days']} 天)**:口径 A 账户 "
      f"{fmt_pct(sa['account_A']['total_return'])}(年化 {fmt_pct(sa['account_A']['ann'])},"
      f"最大回撤 {fmt_pct(sa['account_A']['max_dd'])})vs ① {fmt_pct(sa['core_1']['total_return'])}"
      f"(年化 {fmt_pct(sa['core_1']['ann'])},最大回撤 {fmt_pct(sa['core_1']['max_dd'])})⇒ 相对 ① "
      f"**{sa['excess_A_total_pp']:+.2f}pp** 总收益、**{sa['excess_A_ann_pp']:+.2f}pp** 年化、"
      f"**{sa['excess_A_maxdd_pp']:+.2f}pp** 最大回撤。")
    A("")
    A("> ⚠️ **这行是本卡最容易被误读的地方**:全窗口账户超 ① "
      f"{R['excess_A_vs_1']['total_pp']:+.2f}pp,但**四腿齐全的那 4.2 年里 ① 反超账户 "
      f"{abs(sa['excess_A_total_pp']):.2f}pp**。全窗口的超额几乎全部来自 2021-07 → 2022-08 那一段"
      f"(① 在那里最深回撤 {fmt_pct(R['core_1']['max_dd'])})。")
    A("")
    A("**腿本身(未乘 30%)**:")
    A("")
    la, lb = R["legA_canonical"], R["legB_card_prose"]
    A(f"- 口径 A X1V 腿(BTC+ETH):总收益 {fmt_pct(la['total_return'])},年化 {fmt_pct(la['ann'])},"
      f"最大回撤 {fmt_pct(la['max_dd'])}")
    A(f"- 口径 B X1V 腿(BTC 单币):总收益 {fmt_pct(lb['total_return'])},年化 {fmt_pct(lb['ann'])},"
      f"最大回撤 {fmt_pct(lb['max_dd'])},交易 **{R['card_prose_n_trades']} 笔**")
    A("")
    A("## 3. trend_vol 分格(state_daily + 自算,rr_matrix 口径)")
    A("")
    A("| 格 | 天数 | 账户 A 累计 | ① 累计 | 超额 | 日均超额 | 账户胜率 |")
    A("|---|---|---|---|---|---|---|")
    for lab in ["UP_LO", "UP_MID", "UP_HI", "DOWN_LO", "DOWN_MID", "DOWN_HI", "UNKNOWN"]:
        c = R["trend_vol_cells"][lab]
        if not c.get("n_days"):
            A(f"| {lab} | 0 | — | — | — | — | — |")
            continue
        A(f"| {lab} | {c['n_days']} | {fmt_pct(c['acct_A_total'])} | {fmt_pct(c['core_1_total'])} | "
          f"{c['excess_total_pp']:+.2f}pp | {c['excess_daily_bps']:+.2f}bp | {fmt_pct(c['win_days'], 1)} |")
    A("")
    A(f"**口径**:`state_daily.entity=panel` 的 `dist_200` / `vol_pct_3y`;"
      f"UNKNOWN 天数 {R['trend_vol_unknown_days']}(任一字段缺)。"
      f"`state_daily.dist_200` 是 **① 的 dist_200**,不是 BTC 自己的 MA200 —— 两者不是一回事"
      f"(第 4 节的下跌簇用的是 BTC 自己的 MA200)。")
    A("")
    A("> 「账户累计 / ① 累计」是**只把该格内的日子**复利起来(跳过格外的日子),不是连续净值 —— "
      "跨格的数字不可相加;**日均超额(bp/日)** 才是这一格的可比量。")
    A("")
    A("## 4. 下跌簇:BTC 离 200 日线 0~10% 且广度 ≤ 0.10 → 之后 28 天")
    A("")
    cl = R["cluster"]
    A(f"条件:`{cl['cond_desc']}`(BTC 自己的 MA200)。命中 **{cl['n_qual_days']} 天 / {cl['n_clusters']} 簇**。")
    A(f"末日读数:BTC 离 200 日线 {fmt_pct(cl['dist_btc_last'])}、广度 {cl['breadth_last']:.4f}。")
    A("")
    if cl["clusters"]:
        A("| 簇首日 | 距 200 日线 | 广度 | 前向天数 | 账户 28d 最大回撤 | ① 28d 最大回撤 | 回撤差 |")
        A("|---|---|---|---|---|---|---|")
        for c in cl["clusters"]:
            A(f"| {c['d0']} | {fmt_pct(c['dist_btc'])} | {c['breadth']:.4f} | {c['n_days']} | "
              f"{fmt_pct(c['acct_dd'])} | {fmt_pct(c['core_dd'])} | **{c['dd_diff_pp']:+.2f}pp** |")
        A("")
        part = [c["d0"] for c in cl["clusters"] if c["n_days"] < CLUSTER_FWD]
        verdict = ("**只报不判**" if cl["n_clusters"] < 8 else
                   f"中位回撤差 {cl['median_dd_diff_pp']:+.2f}pp、账户更差的簇 {cl['acct_worse_count']}/{cl['n_clusters']}")
        A(f"→ {verdict}(簇数 {cl['n_clusters']})。"
          + (f"⚠️ 其中 {', '.join(part)} 的前向窗口不满 {CLUSTER_FWD} 天(窗口末尾)。" if part else ""))
    else:
        A("→ 窗口内**没有**满足条件的簇。")
    A("")
    A("## 5. 压力表:SPY 21 日 ≤ −5% 之后 21 日")
    A("")
    st = R["stress"]
    A(f"事件数 **{st['n_events']}**(重叠事件全部计入)。"
      f"**GLD 腿只在 {st['gld_live_from']} 起的事件上统计**(此前 GLD 无数据,不是 0 收益)。")
    A("")
    A("| 腿 | p10 | p50 | p90 |")
    A("|---|---|---|---|")
    for nm in ("SPY", "GLD", "ACCT_A", "ACCT_B"):
        s = st["summary"][nm]
        A(f"| {nm} | {fmt_pct(s['p10'])} | {fmt_pct(s['p50'])} | {fmt_pct(s['p90'])} |")
    A("")
    for lab in ("2022-01→2022-06", "2025-03→2025-04"):
        sub = st[lab]
        A(f"**{lab}**(事件 {sub['n_events']} 个)")
        A("")
        A("| 腿 | n | p10 | p50 | p90 |")
        A("|---|---|---|---|---|")
        for nm in ("SPY", "GLD", "ACCT_A", "ACCT_B"):
            s = sub["legs"][nm]
            A(f"| {nm} | {s['n']} | {fmt_pct(s['p10'])} | {fmt_pct(s['p50'])} | {fmt_pct(s['p90'])} |")
        A("")
    A("## 6. 零信号对照(apparatus,种子 305,1,000 次)")
    A("")
    A("对照法:同样的进场次数、同样的持有天数,换成**同年的随机日期**(apparatus.random_dates_like 默认分层),")
    A("在随机日期上按同样的天数持有同一篮子,现金过场。报实际值落在零分布的第几分位。")
    A("")
    A("| 口径 | 进场段数 | 总持有天数 | 实际总收益 | 零分布中位 | 实际最大回撤 | 零分布回撤中位 | 总收益分位 | 回撤分位 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for lab, nm in (("A_canonical_BTC_ETH", "口径 A"), ("B_card_prose_BTC", "口径 B")):
        n = R["nulls"].get(lab, {})
        if n.get("error"):
            A(f"| {nm} | — | — | — | — | — | — | 失败:{n['error']} | — |")
            continue
        A(f"| {nm} | {n['n_spells']} | {n['total_hold_days']} | {fmt_pct(n['actual_total'])} | "
          f"{fmt_pct(n['null_total_median'])} | {fmt_pct(n['actual_max_dd'])} | {fmt_pct(n['null_dd_median'])} | "
          f"**{n['null_total_pct']:.3f}** | **{n['null_dd_pct']:.3f}** |")
    A("")
    A("## 7. 去掉最好 5 天 / 最差 5 天")
    A("")
    for nm, key in (("口径 A", "account_A_drop_extremes"), ("口径 B", "account_B_drop_extremes")):
        d = R[key]
        A(f"- **{nm}**:全窗口总收益 {fmt_pct(d['total'])};去掉最好 5 天 ⇒ {fmt_pct(d['no_best5'])};"
          f"去掉最差 5 天 ⇒ {fmt_pct(d['no_worst5'])}。")
    A("")
    A("## 8. 口径出入(必须先看这一节)")
    A("")
    A("| 项 | 卡面散文规则 | 仓库内核(T-146/T-157) |")
    A("|---|---|---|")
    A("| 资产 | BTC 单币 | BTC + ETH 各半(`executor.SLEEVES`) |")
    A("| 进场 | 收盘 > 前 20 日最高收盘 | 收盘 > 200 日线 **且** > 前 20 日高(多头)/ rally 段:收盘 > 前 20 日高(半仓 0.5) |")
    A("| 出场 | 跌破 200 日线 或 自进场价 −9% | 跌破**前 20 日最低收盘**(`exit_mode=\"l20\"`);另加「破 MA200 且破 20 日低」转空/空仓 |")
    A("| 仓位 | 满仓/空仓 | 0 / 0.5 / 1.0 / ≤1.3(55 日新高加仓 +0.1,加仓价 ×1.10 再加) |")
    A("| 波动缩放 | 无 | 有(`vol=True`:过去 730 天 20 日波动中位数 ÷ 当前,min(1,·)) |")
    A("| 成本 | 无 | 10bp 换手;资金费 0.10/yr(只作用在 >1 的加仓部分) |")
    A("| 生效时点 | 信号收盘后**次日收盘**成交 ⇒ 吃到的是再下一日的涨跌 | 信号收盘即成交(`g[t]` 作用于 t→t+1 的涨跌) |")
    A("")
    A(f"口径 B 在窗口内成交 **{R['card_prose_n_trades']} 笔**"
      f"(出场原因:{json.dumps(R['card_prose_exit_reasons'], ensure_ascii=False)});"
      f"规则跑在 2017 起的完整历史上以保证状态连续(窗口前成交 {R['card_prose_n_trades_total'] - R['card_prose_n_trades']} 笔不计入)。")
    A("")
    A("⇒ **两个口径的账户都报了**;主口径按卡面要求取 T-146/T-157(仓库内核)。")
    A("")
    A("## 9. 探索性发现(未经预注册,需另立预注册 + 新数据上的零信号对照)")
    A("")
    cl2, sa2, nA, nB = R["cluster"], R["sub_all_legs"], R["nulls"].get("A_canonical_BTC_ETH", {}), \
        R["nulls"].get("B_card_prose_BTC", {})
    up = [R["trend_vol_cells"][k] for k in ("UP_LO", "UP_MID", "UP_HI")]
    dn = [R["trend_vol_cells"][k] for k in ("DOWN_LO", "DOWN_MID", "DOWN_HI")]
    A(f"1. **「账户在下跌里比 ① 抗跌」是配置层的机械性质,不是 X1V 的功劳。** "
      f"{cl2['n_clusters']} 个下跌簇里账户 28 天回撤**一次都没比 ① 差**({cl2['acct_worse_count']}/{cl2['n_clusters']}),"
      f"中位浅 {cl2['median_dd_diff_pp']:.2f}pp —— 但账户里 70% 是 SPY/GLD/现金,BTC 跌它们不跌。"
      f"要证明「X1V 择时有用」,需要把非加密腿换成同 β 的对照(另立预注册)。")
    A(f"2. **trend_vol 格的超额几乎全部来自 DOWN 格。** UP 三格账户日均超额 "
      f"{min(c['excess_daily_bps'] for c in up):.1f} ~ {max(c['excess_daily_bps'] for c in up):.1f} bp/日,"
      f"DOWN 三格 {min(c['excess_daily_bps'] for c in dn):.1f} ~ {max(c['excess_daily_bps'] for c in dn):.1f} bp/日 —— "
      f"「市场涨时 ① 赢、市场跌时账户赢」,与配置层 `100% core_cap` 的读数是同一件事。")
    A(f"3. **「账户优于 ①」对窗口起点极度敏感。** 全窗口 {R['excess_A_vs_1']['total_pp']:+.2f}pp,"
      f"但四腿齐全子窗口是 {sa2['excess_A_total_pp']:+.2f}pp —— 超额几乎全部来自 2021-07 → 2022-08 的熊段。")
    A(f"4. **两个口径的零信号分位给出相反的结论。** 口径 A(仓库内核)总收益分位 "
      f"{nA.get('null_total_pct', float('nan')):.3f}、回撤分位 {nA.get('null_dd_pct', float('nan')):.3f};"
      f"口径 B(卡面散文)总收益分位 {nB.get('null_total_pct', float('nan')):.3f}、回撤分位 "
      f"{nB.get('null_dd_pct', float('nan')):.3f} —— 若真钱用的是内核,「X1V 择时有效」只对内核成立。")
    A(f"5. **压力事件的尾部**:{R['stress']['n_events']} 个事件里账户(口径 A)p10 "
      f"{fmt_pct(R['stress']['summary']['ACCT_A']['p10'])}、p50 {fmt_pct(R['stress']['summary']['ACCT_A']['p50'])},"
      f"SPY 腿 p10 {fmt_pct(R['stress']['summary']['SPY']['p10'])} —— 账户的下行尾部明显浅于 SPY 本身,"
      f"但 2022 上半年子窗口账户 p10 仍是 {fmt_pct(R['stress']['2022-01→2022-06']['legs']['ACCT_A']['p10'])}(负)。")
    A("")
    A("## 10. 限制")
    A("")
    A("- 规则级(理想)口径:**不含**执行拖累(T-146 已量 ≈ −9.46pp/年)、不含资金费的真实变动、不含 SPYX/XAUT0 的跟踪误差与溢价。")
    A("- SPY/GLD 用 EODHD 收盘代理 SPYX/XAUT0;GLD 在 2022-08-31 前无数据(该段 19% 归现金)。")
    A("- 日再平衡按收盘权重线性加权,未计再平衡本身的交易成本。")
    A("- 压力事件重叠(同一段下跌会重复计入多个 21 日窗口)⇒ p10/p50/p90 是**路径分布**不是独立样本分布。")
    A("- 零信号对照的随机日期**同年分层**,故意保守(不跨年换制度)。")
    A("")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
