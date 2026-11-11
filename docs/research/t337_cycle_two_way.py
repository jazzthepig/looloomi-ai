#!/usr/bin/env python3
"""T-337 / S-813(含 11-11 修订)双向配置级反转 —— 中长线指标定「过热 / 过冷」。

预注册原文(REFUTATION_LEDGER S-813 + 「S-813 修订」,2026-11-11 03:41 / 03:46 UTC),
逐字照抄见报告 docs/research/T-337_cycle_indicators_two_way.md 开头;本脚本是那份预注册的实现。

区(修订后):
  过热 武装 = 最近 30 天内 fng 有一天 ≥ 95,且 MVRV ≥ 扩张 90 分位 或 Puell ≥ 扩张 90 分位
       扳机 = 武装期内 BTC 收盘第一次同时满足「< 20 日均线」且「7 日收益 < 0」⇒ 次日执行过热动作
  过冷 武装 = 最近 30 天内 fng 有一天 ≤ 10,且 MVRV ≤ 扩张 10 分位 或 Puell ≤ 扩张 10 分位
       扳机 = 武装期内 BTC 收盘第一次同时满足「> 20 日均线」且「7 日收益 > 0」⇒ 次日执行过冷动作
动作 / 出场 / 成本:与 S-812 一字相同(0.7 现货 + 0.3 现金;过热减到 0.35 + 用落袋利润分批加永续空、
  无价格止损、预算平空、收盘 < 50 日线或 90 天出;过冷用现金分三笔加现货到 1.0、收盘 > 200 日线或 180 天出;
  成本 7.5bp × 换手;两区不同时成立;一轮未结束不开新一轮)。

只读:macro_daily(fng / btc_mvrv / btc_issuance_usd)、perp_bv_daily(BTCUSDT)、v_funding_daily(BTC)、
ohlcv_daily(BTC, source=binance_hist,现货腿 2019-12 前)。不入库、不改代码。
零分布 / 分位只用 src/data/evaluation/apparatus.py;联合检验不适用(单因子、单票)。

产物:docs/research/t337_results.json · docs/research/t337_rounds.csv
原始取数缓存:/Volumes/CometCloudAI/cometcloud-local/research/t337/(不在 /tmp)
"""
from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t337")
OUT = REPO / "docs" / "research"

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K}

# ───────────────────────────── 写死(全部来自预注册)─────────────────────────────
START, END = "2018-02-01", "2026-10-31"
SPOT_W, CASH_W = 0.7, 0.3          # 基础配置:现货 0.7 + 现金 0.3(现金收益 0)
HOT_SPOT_TO = 0.35                  # 过热:现货 0.7 → 0.35
SHORT_FIRST = 0.2                   # 空腿首笔 0.2 倍
SHORT_ADD_PCTS = (0.10, 0.20)      # 较首笔再涨 +10% / +20% 各加 0.2
SHORT_MAX = 0.6                    # 空腿最多 0.6 倍
COLD_ADD = 0.1                      # 过冷:现金每笔买现货 +0.1
COLD_ADD_PCTS = (-0.10, -0.20)     # 较首笔再跌 −10% / −20% 各 +0.1
SPOT_CAP_COLD = 1.0                # 过冷最多买到 1.0 倍(现金用完)
FUND_EVENTS_PER_DAY = 3            # v_funding_daily 每行 n=3 个结算点(8h 费率 → 日 carry = 3×)
COST_BPS = 7.5                      # 成本 7.5bp × 换手
HOT_EXIT_MA, HOT_EXIT_DAYS = 50, 90      # 收盘第一次 < 50 日线,或 90 天
COLD_EXIT_MA, COLD_EXIT_DAYS = 200, 180  # 收盘第一次 > 200 日线,或 180 天
FNG_HOT, FNG_COLD, ARM_WIN = 95, 10, 30   # 武装阈值与 30 天窗口
Q_HOT, Q_COLD = 90, 10              # MVRV / Puell 扩张分位阈值
PCT_MIN_OBS = 365                   # 分位最少观测
TRIG_MA = 20                        # 扳机用 20 日均线
NULL_N, NULL_SEED = 1000, 813       # 随机日程对照

# 大事件(逐轮表的一栏,事后标注,只给 Jazz 判断;不进规则)。仅标模型有把握的历史事件。
EVENTS = {
    "2018-12": "2018 熊市末段(BTC 从 2018-01 高点 3.1 万跌到 12 月底 3.2 千;12-15 见低点)",
    "2020-03": "COVID 崩盘 + 3M 流动性危机 + 美联储无限 QE(3-15 后流动性转向)",
    "2021-01": "2020-12→2021-02 逼空(BTC 1.9 万→5.2 万);Tesla/ARK 主题;扳机扣在 1-20,之后还涨到 4 月 6.4 万",
    "2021-02": "2020-12→2021-02 逼空(BTC 1.9 万→5.2 万);2-23 Tesla 破万亿美元",
    "2022-05": "Terra/Luna 崩盘(5-19)+ Fed 缩表",
    "2022-06": "3AC/Celsius 破产(6 月)+ Fed 加息 + ETH 暴跌",
    "2022-07": "熊市末段(3AC 破产 7 月、Celsius 余波);这一轮之后又跌到 11 月,持有到 2023-01 才退",
    "2026-02": "【模型知识不到 2026】需 Jazz 自行标注",
    "2026-03": "【模型知识不到 2026】需 Jazz 自行标注",
    "2026-07": "【模型知识不到 2026】需 Jazz 自行标注",
}


# ───────────────────────────── 取数 ─────────────────────────────
def pull(table: str, params: dict) -> list[dict]:
    """PostgREST 翻页读:必须带 order=(按主键排),每页 ≤ 1000 行。"""
    rows: list[dict] = []
    off = 0
    while True:
        q = dict(params)
        q["limit"] = "1000"
        q["offset"] = str(off)
        url = f"{U}/rest/v1/{table}?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers=H)
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read())
        if not isinstance(body, list):
            raise RuntimeError(f"{table}: {str(body)[:200]}")
        rows.extend(body)
        if len(body) < 1000:
            return rows
        off += 1000


def cached(name: str, fn) -> object:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{name}.json"
    if p.exists():
        print(f"  cache {name}", flush=True)
        return json.loads(p.read_text())
    v = fn()
    p.write_text(json.dumps(v))
    print(f"  fetched {name} -> {p}", flush=True)
    return v


def series_from_macro(series: str) -> tuple[dict[str, float], int]:
    rows = cached(f"macro_{series}", lambda: pull(
        "macro_daily", {"select": "d,value", "series": "eq." + series, "order": "d.asc"}))
    out: dict[str, float] = {}
    for r in rows:
        v = r.get("value")
        if v is None:
            continue
        out[str(r["d"])[:10]] = float(v)
    return out, len(rows)


def coinmetrics_fallback(metrics: list[str]) -> list[dict]:
    """macro_daily 里 btc_* 还没入库时的同源兜底:Coin Metrics 社区 API,
    参数与 src/data/market/data_layer.py::get_coinmetrics_btc 一致(免密钥)。"""
    url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?"
           + urllib.parse.urlencode({"assets": "btc", "metrics": ",".join(metrics),
                                     "start_time": "2011-01-01", "page_size": 10000,
                                     "frequency": "1d"}))
    out: list[dict] = []
    while url:
        req = urllib.request.Request(url, headers={"User-Agent": "cometcloud-research/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            j = json.loads(resp.read())
        out += j.get("data") or []
        url = j.get("next_page_url")
    return out


def load_puell_fn():
    """Puell 用 src/data/market/btc_cycle.py 的 puell()(纯函数,只用 ≤ d)。"""
    cands = [REPO / "src" / "data" / "market" / "btc_cycle.py",
             Path("/Users/sbb/Projects/looloomi-ai/src/data/market/btc_cycle.py")]
    for p in cands:
        if p.exists():
            spec = importlib.util.spec_from_file_location("btc_cycle_mod", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            print(f"  puell() from {p}", flush=True)
            return mod.puell
    raise RuntimeError("找不到 src/data/market/btc_cycle.py 的 puell()")


# ───────────────────────────── 指标 ─────────────────────────────
def expanding_pct(values: list[tuple[str, float]], min_obs: int) -> dict[str, float]:
    """扩张分位(只用 ≤ d 的观测):pct = 100 × (≤ d 的观测里 ≤ 当前值的个数) / 总数。"""
    out: dict[str, float] = {}
    arr = np.empty(len(values), dtype=float)
    for i, (d, v) in enumerate(values):
        arr[i] = v
        if i + 1 < min_obs:
            continue
        out[d] = 100.0 * float((arr[: i + 1] <= v).sum()) / (i + 1)
    return out


def ma_series(closes: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) < n:
        return out
    run = float(np.sum(closes[:n]))
    out[n - 1] = run / n
    for i in range(n, len(closes)):
        run += closes[i] - closes[i - n]
        out[i] = run / n
    return out


def dd(nav: list[float]) -> float:
    peak, m = nav[0], 0.0
    for v in nav:
        peak = max(peak, v)
        m = min(m, v / peak - 1.0)
    return m


def dd_window(nav: list[float], days: list[str] | None = None) -> dict:
    """最大回撤发生在哪一段(峰日 → 谷日),用于审计 max_dd 是不是记账假象。"""
    peak, pi = nav[0], 0
    best = (0.0, 0, 0)
    for i, v in enumerate(nav):
        if v > peak:
            peak, pi = v, i
        d = v / peak - 1.0
        if d < best[0]:
            best = (d, pi, i)
    out = {"dd": best[0], "peak_idx": best[1], "trough_idx": best[2],
           "peak_nav": nav[best[1]], "trough_nav": nav[best[2]],
           "min_nav": min(nav), "min_nav_idx": int(np.argmin(nav))}
    if days:
        out["peak_date"] = days[best[1]]
        out["trough_date"] = days[best[2]]
        out["min_nav_date"] = days[out["min_nav_idx"]]
    return out


# ───────────────────────────── 模拟 ─────────────────────────────
def simulate(rounds: list[dict], ctx: dict) -> dict:
    """按 S-812 动作跑一个臂。rounds = [{kind, trigger}]。返回 NAV 序列与逐轮明细。"""
    days: list[str] = ctx["days"]
    closes: dict[str, float] = ctx["closes"]
    funding: dict[str, float] = ctx["funding"]
    ma50: list[float | None] = ctx["ma50"]
    ma200: list[float | None] = ctx["ma200"]
    close0 = ctx["close0"]
    base_nav: list[float] = ctx["base_nav"]

    spot_units = SPOT_W / close0
    cash = CASH_W
    min_cash = CASH_W
    legs: list[dict] = []
    nav: list[float] = []
    detail: list[dict] = []
    cur: dict | None = None
    pending: dict | None = None
    pend_adds: list[float] = []
    rounds_by_trigger = {r["trigger"]: r for r in rounds}

    def cost(notional: float) -> float:
        return abs(notional) * COST_BPS / 1e4

    def nav_at(c: float) -> float:
        """NAV = 现货市值 + 现金 + 空腿未实现(Σ u×(fill − c))。"""
        return (cash + sum(lg["units"] * lg["fill"] for lg in legs)
                + c * (spot_units - sum(lg["units"] for lg in legs)))

    def rebase_spot(c: float, mult: float, r: dict | None = None) -> None:
        """把现货调到 mult × 当前账户净值,其余留现金(现金不够就只买到上限)。"""
        nonlocal spot_units, cash
        target = mult * nav_at(c)
        delta = target - spot_units * c
        if abs(delta) < 1e-12:
            return
        if delta > 0:
            spend = min(delta, max(0.0, cash))
            spot_units += spend / c
            cash -= spend
            cst = cost(spend)
        else:
            u = (-delta) / c
            spot_units -= u
            cash += u * c
            cst = cost(u * c)
        cash -= cst
        if r is not None:
            r["cost_spot"] += cst

    def close_shorts(d: str, c: float, r: dict) -> None:
        """平空:空腿的现金效果 = 已实现盈亏 u×(fill − close)(开仓时的卖出所得已在 unreal 里,
        这里只把 unreal 兑现进现金,避免与 NAV 里的 unreal 重复计)。"""
        nonlocal legs, cash
        for lg in legs:
            pnl = lg["units"] * (lg["fill"] - c)
            cash += pnl
            cst = cost(lg["units"] * c)
            cash -= cst
            r["short_leg_pnl"] += pnl
            r["cost_short"] += cst
        legs = []

    for i, d in enumerate(days):
        c = closes[d]

        # 1) 执行昨日排定的轮次动作(入场日 = 扳机日 + 1)
        if pending is not None:
            kind, trig = pending["kind"], pending["trigger"]
            if kind == "hot":
                nav_pre = nav_at(c)                  # 账户净值(动作发生时)
                target_val = HOT_SPOT_TO * nav_pre   # 现货 0.7 → 0.35(账户口径)
                sell_val = max(0.0, spot_units * c - target_val)
                sell_units = sell_val / c
                spot_units -= sell_units
                cash += sell_val
                cst = cost(sell_val)
                cash -= cst
                fill1 = c
                n_short = SHORT_FIRST * nav_pre      # 空腿首笔 0.2 倍账户
                u = n_short / c
                legs.append({"units": u, "fill": fill1, "open": d})
                cst_s = cost(n_short)
                cash -= cst_s
                b = (HOT_SPOT_TO * nav_pre * max(0.0, c / ctx["closes"][days[i - 90]] - 1.0)
                     if i >= 90 else 0.0)
                cur = {"kind": "hot", "trigger": trig, "entry": d, "fill1": fill1,
                       "budget": b, "nav_entry": nav_pre,
                       "spot_sold_units": sell_units, "spot_sold_value": sell_val,
                       "spot_leg_pnl": 0.0, "short_leg_pnl": 0.0, "funding_pnl": 0.0,
                       "cost_spot": cst, "cost_short": cst_s, "short_notional": n_short,
                       "short_cap": SHORT_MAX * nav_pre,
                       "adds": [], "exit": None, "exit_reason": None}
                pend_adds = list(SHORT_ADD_PCTS)
            else:
                nav_pre = nav_at(c)
                spend = min(COLD_ADD * nav_pre, max(0.0, cash))   # 现金买现货 +0.1(账户口径)
                buy_units = spend / c
                spot_units += buy_units
                cash -= spend
                cst = cost(spend)
                cash -= cst
                cur = {"kind": "cold", "trigger": trig, "entry": d, "fill1": c,
                       "nav_entry": nav_pre, "spot_bought_units": buy_units,
                       "spot_bought_value": spend, "spot_leg_pnl": 0.0,
                       "funding_pnl": 0.0, "cost_spot": cst, "cost_short": 0.0,
                       "adds": [], "exit": None, "exit_reason": None}
                pend_adds = list(COLD_ADD_PCTS)
            pending = None

        # 2) 轮内机械动作:加仓 / 资金费 / 预算平空 / 出场
        if cur is not None:
            if cur["kind"] == "hot":
                for lvl in list(pend_adds):
                    if c >= cur["fill1"] * (1 + lvl):
                        n_add = min(SHORT_FIRST * nav_at(c),
                                    max(0.0, cur["short_cap"] - cur["short_notional"]))
                        if n_add <= 1e-12:
                            pend_adds.remove(lvl)
                            continue
                        u = n_add / c
                        legs.append({"units": u, "fill": c, "open": d})
                        cst = cost(n_add)
                        cash -= cst
                        cur["short_notional"] += n_add
                        cur["cost_short"] += cst
                        cur["adds"].append({"date": d, "level": lvl, "units": u,
                                            "price": c, "notional": n_add})
                        pend_adds.remove(lvl)
                fr = funding.get(d)
                if fr is not None and legs:
                    notional_now = sum(lg["units"] * c for lg in legs)
                    # 费率为正 = 多头付空头 ⇒ 空腿收 +(每行 n=3 个结算点)×rate×名义
                    fp = FUND_EVENTS_PER_DAY * fr * notional_now
                    cash += fp
                    cur["funding_pnl"] += fp
                    cur["short_leg_pnl"] += fp
                if d > cur["entry"]:
                    unreal = sum((lg["fill"] - c) * lg["units"] for lg in legs)
                    m50 = ma50[i]
                    days_since = (dt.date.fromisoformat(d) - dt.date.fromisoformat(cur["entry"])).days
                    hit_ma = m50 is not None and c < m50
                    if cur["budget"] > 0 and unreal <= -cur["budget"]:
                        close_shorts(d, c, cur)
                        rebase_spot(c, SPOT_W, cur)          # 现货回到 0.7 倍账户净值
                        cur["exit"], cur["exit_reason"] = d, "budget_stop"
                        cur["delta_vs_base"] = nav_at(c) - base_nav[i]
                        detail.append(cur)
                        cur = None
                    elif hit_ma or days_since >= HOT_EXIT_DAYS:
                        close_shorts(d, c, cur)
                        rebase_spot(c, SPOT_W, cur)
                        cur["exit"], cur["exit_reason"] = d, ("ma50" if hit_ma else "90d")
                        cur["delta_vs_base"] = nav_at(c) - base_nav[i]
                        detail.append(cur)
                        cur = None
            else:
                for lvl in list(pend_adds):
                    if c <= cur["fill1"] * (1 + lvl):
                        nav_now = nav_at(c)
                        spend = min(COLD_ADD * nav_now,
                                    max(0.0, cash),
                                    max(0.0, SPOT_CAP_COLD * nav_now - spot_units * c))
                        if spend <= 1e-12:
                            pend_adds.remove(lvl)
                            continue
                        want = spend / c
                        spot_units += want
                        cash -= spend
                        cst = cost(spend)
                        cash -= cst
                        cur["spot_bought_units"] += want
                        cur["cost_spot"] += cst
                        cur["adds"].append({"date": d, "level": lvl, "units": want,
                                            "price": c, "notional": spend})
                        pend_adds.remove(lvl)
                if d > cur["entry"]:
                    m200 = ma200[i]
                    days_since = (dt.date.fromisoformat(d) - dt.date.fromisoformat(cur["entry"])).days
                    hit_ma = m200 is not None and c > m200
                    if hit_ma or days_since >= COLD_EXIT_DAYS:
                        rebase_spot(c, SPOT_W, cur)          # 现货回到 0.7 倍账户净值
                        pnl = cur["spot_bought_units"] * (c - cur["fill1"])
                        for a in cur["adds"]:
                            pnl += a["units"] * (c - a["price"])
                        cur["spot_leg_pnl"] = pnl - cur["cost_spot"]
                        cur["exit"], cur["exit_reason"] = d, ("ma200" if hit_ma else "180d")
                        cur["delta_vs_base"] = nav_at(c) - base_nav[i]
                        detail.append(cur)
                        cur = None

        # 3) NAV
        unreal = sum((lg["fill"] - c) * lg["units"] for lg in legs)
        nav.append(spot_units * c + cash + unreal)
        min_cash = min(min_cash, cash)

        # 4) 排定次日(扳机日 + 1)的入场
        if days[i] in rounds_by_trigger:
            pending = rounds_by_trigger[days[i]]

    return {"nav": nav, "rounds": detail, "min_cash": min_cash}


def arm_stats(nav: list[float]) -> dict:
    tr = nav[-1] / nav[0] - 1.0
    rets = [nav[i] / nav[i - 1] - 1.0 for i in range(1, len(nav)) if nav[i - 1] > 0]
    sd = float(np.std(rets, ddof=1)) if len(rets) > 2 else 0.0
    return {"total_return": tr, "max_dd": dd(nav),
            "ann_vol": sd * math.sqrt(365),
            "sharpe": (float(np.mean(rets)) / sd * math.sqrt(365)) if sd > 0 else None,
            "final_nav": nav[-1]}


# ───────────────────────────── 主流程 ─────────────────────────────
print("[1] 取数…", flush=True)
fng, fng_raw_rows = series_from_macro("fng")
mvrv, mvrv_raw_rows = series_from_macro("btc_mvrv")
issuance, iss_raw_rows = series_from_macro("btc_issuance_usd")

gate = {"fng_rows_raw": fng_raw_rows, "fng_rows": len(fng),
        "fng_first": min(fng) if fng else None, "fng_last": max(fng) if fng else None,
        "btc_mvrv_rows_raw": mvrv_raw_rows, "btc_mvrv_rows": len(mvrv),
        "btc_mvrv_first": min(mvrv) if mvrv else None, "btc_mvrv_last": max(mvrv) if mvrv else None,
        "btc_issuance_rows_raw": iss_raw_rows, "btc_issuance_rows": len(issuance),
        "btc_issuance_first": min(issuance) if issuance else None,
        "btc_issuance_last": max(issuance) if issuance else None}
print("  gate:", json.dumps(gate), flush=True)

if not mvrv or not issuance:
    print("  ⚠ macro_daily 的 btc_mvrv / btc_issuance_usd 还没有数 → 同源兜底"
          "(Coin Metrics 社区 API,参数与 data_layer.get_coinmetrics_btc 一致)", flush=True)
    raw = cached("coinmetrics_btc_cycle", lambda: coinmetrics_fallback(["CapMVRVCur", "IssTotUSD"]))
    for r in raw:
        d = str(r.get("time") or "")[:10]
        if len(d) != 10:
            continue
        v = r.get("CapMVRVCur")
        if v is not None and float(v) > 0:
            mvrv.setdefault(d, float(v))
        v = r.get("IssTotUSD")
        if v is not None and float(v) > 0:
            issuance.setdefault(d, float(v))
    gate["fallback"] = "coinmetrics_community_api"
    gate["btc_mvrv_rows"], gate["btc_mvrv_first"], gate["btc_mvrv_last"] = len(mvrv), min(mvrv), max(mvrv)
    gate["btc_issuance_rows"], gate["btc_issuance_first"], gate["btc_issuance_last"] = (
        len(issuance), min(issuance), max(issuance))
    print("  兜底后:", json.dumps(gate), flush=True)

perp_rows = cached("perp_btc", lambda: pull(
    "perp_bv_daily", {"select": "d,o,h,l,c,pair", "pair": "eq.BTCUSDT", "order": "d.asc,recorded_at.asc"}))
perp_close: dict[str, float] = {}
for r in perp_rows:
    if r.get("c") is None:
        continue
    perp_close[str(r["d"])[:10]] = float(r["c"])
spot_rows = cached("ohlcv_btc_binance_hist", lambda: pull(
    "ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC", "source": "eq.binance_hist",
                    "order": "trade_date.asc"}))
spot_close: dict[str, float] = {}
for r in spot_rows:
    if r.get("close") is None:
        continue
    spot_close[str(r["trade_date"])[:10]] = float(r["close"])

closes: dict[str, float] = dict(spot_close)
closes.update(perp_close)          # 永续优先(S-812:价格 = 永续日线;现货腿按同一收盘记)

fund_rows = cached("v_funding_btc", lambda: pull(
    "v_funding_daily", {"select": "d,symbol,funding_rate,n", "symbol": "eq.BTC", "order": "d.asc,symbol.asc"}))
funding: dict[str, float] = {}
for r in fund_rows:
    fr = r.get("funding_rate")
    if fr is None:
        continue
    funding[str(r["d"])[:10]] = funding.get(str(r["d"])[:10], 0.0) + float(fr)

print("  价格:现货(binance_hist) %d 行 %s→%s;永续(perp_bv_daily) %d 行 %s→%s;资金费 %d 行 %s→%s" % (
    len(spot_close), min(spot_close), max(spot_close), len(perp_close), min(perp_close),
    max(perp_close), len(funding), min(funding), max(funding)), flush=True)

print("[2] 指标…", flush=True)
puell_fn = load_puell_fn()
puell: dict[str, float] = {}
for d in sorted(issuance):
    v = puell_fn(issuance, d)
    if v is not None and v == v:
        puell[d] = float(v)
mvrv_items = sorted(mvrv.items())
puell_items = sorted(puell.items())
pct_mvrv = expanding_pct(mvrv_items, PCT_MIN_OBS)
pct_puell = expanding_pct(puell_items, PCT_MIN_OBS)
print("  MVRV 观测 %d(%s→%s),分位可用日 %d;Puell 观测 %d(%s→%s),分位可用日 %d" % (
    len(mvrv_items), mvrv_items[0][0], mvrv_items[-1][0], len(pct_mvrv),
    len(puell_items), puell_items[0][0], puell_items[-1][0], len(pct_puell)), flush=True)

days = sorted(d for d in closes if START <= d <= END)
closes_s = [closes[d] for d in days]
n = len(days)
fng_s = [fng.get(d) for d in days]
ma20 = ma_series(closes_s, TRIG_MA)
ma50 = ma_series(closes_s, HOT_EXIT_MA)
ma200 = ma_series(closes_s, COLD_EXIT_MA)
ret7 = [None if i < 7 else closes_s[i] / closes_s[i - 7] - 1.0 for i in range(n)]

arm_hot = [False] * n
arm_cold = [False] * n
for i, d in enumerate(days):
    win = [x for x in fng_s[max(0, i - ARM_WIN + 1): i + 1] if x is not None]
    if not win:
        continue
    pm, pp = pct_mvrv.get(d), pct_puell.get(d)
    if max(win) >= FNG_HOT and ((pm is not None and pm >= Q_HOT) or (pp is not None and pp >= Q_HOT)):
        arm_hot[i] = True
    if min(win) <= FNG_COLD and ((pm is not None and pm <= Q_COLD) or (pp is not None and pp <= Q_COLD)):
        arm_cold[i] = True
print("  武装日:过热 %d 天、过冷 %d 天" % (sum(arm_hot), sum(arm_cold)), flush=True)


def trigger_at(i: int, kind: str) -> bool:
    if ma20[i] is None or ret7[i] is None:
        return False
    if kind == "hot":
        return closes_s[i] < ma20[i] and ret7[i] < 0
    return closes_s[i] > ma20[i] and ret7[i] > 0


def build_rounds() -> list[dict]:
    """逐轮串行:一轮未结束不开新一轮。"""
    out: list[dict] = []
    i = 0
    while i < n:
        kind = None
        if arm_hot[i] and trigger_at(i, "hot"):
            kind = "hot"
        elif arm_cold[i] and trigger_at(i, "cold"):
            kind = "cold"
        if kind is None:
            i += 1
            continue
        out.append({"kind": kind, "trigger": days[i]})
        ei = i + 1
        if ei >= n:
            break
        entry = days[ei]
        j = ei + 1          # 出场从入场次日算(入场当天的收盘还在进场之前)
        while j < n:
            mx = ma50[j] if kind == "hot" else ma200[j]
            days_since = (dt.date.fromisoformat(days[j]) - dt.date.fromisoformat(entry)).days
            lim = HOT_EXIT_DAYS if kind == "hot" else COLD_EXIT_DAYS
            hit = mx is not None and (closes_s[j] < mx if kind == "hot" else closes_s[j] > mx)
            if hit or days_since >= lim:
                break
            j += 1
        i = max(j, ei) + 1
    return out


rounds = build_rounds()
print("  轮次 %d 条:%s" % (len(rounds), [(r["kind"], r["trigger"]) for r in rounds]), flush=True)

base_nav = [SPOT_W * c / closes_s[0] + CASH_W for c in closes_s]
ctx = {"days": days, "closes": closes, "funding": funding, "ma50": ma50, "ma200": ma200,
       "close0": closes_s[0], "base_nav": base_nav}

print("[3] 模拟…", flush=True)
res_all = simulate(rounds, ctx)
hot_only = simulate([r for r in rounds if r["kind"] == "hot"], ctx)
cold_only = simulate([r for r in rounds if r["kind"] == "cold"], ctx)

hold70_nav = base_nav
hold100_nav = [c / ctx["close0"] for c in closes_s]
stats = {"HOLD70": arm_stats(hold70_nav), "HOLD100": arm_stats(hold100_nav),
         "HOT": arm_stats(hot_only["nav"]), "COLD": arm_stats(cold_only["nav"]),
         "TWOWAY": arm_stats(res_all["nav"])}
for k, v in stats.items():
    print("  %-7s 收益 %+.2f%%  最大回撤 %+.2f%%  Sharpe %s  期末 NAV %.4f" % (
        k, v["total_return"] * 100, v["max_dd"] * 100,
        ("%+.2f" % v["sharpe"]) if v["sharpe"] is not None else "n/a", v["final_nav"]), flush=True)
for k, nav in [("HOLD70", hold70_nav), ("HOLD100", hold100_nav), ("HOT", hot_only["nav"]),
               ("COLD", cold_only["nav"]), ("TWOWAY", res_all["nav"])]:
    w = dd_window(nav, days)
    stats[k]["dd_window"] = w
    print("  %-7s maxDD %.2f%%:峰 %s(%.4f) → 谷 %s(%.4f);min NAV %.4f @ %s" % (
        k, w["dd"] * 100, w["peak_date"], w["peak_nav"], w["trough_date"], w["trough_nav"],
        w["min_nav"], w["min_nav_date"]), flush=True)
for k, res in [("HOT", hot_only), ("COLD", cold_only), ("TWOWAY", res_all)]:
    stats[k]["min_cash"] = res.get("min_cash")
    print("  %-7s 最低现金 %.4f(负数 = 记账破口)" % (k, res.get("min_cash")), flush=True)

print("[4] 随机日程对照(circular_shift,1000 次,种子 813)…", flush=True)
from src.data.evaluation.apparatus import circular_shift, null_distribution, percentile_of  # noqa: E402

sched = np.zeros(n, dtype=int)
for r in rounds:
    sched[days.index(r["trigger"])] = 1 if r["kind"] == "hot" else -1
actual_diff = stats["TWOWAY"]["total_return"] - stats["HOLD70"]["total_return"]


def null_fn(rng) -> float:
    sh = circular_shift(sched, rng, block=1)
    rl = [{"kind": "hot" if sh[j] > 0 else "cold", "trigger": days[int(j)]}
          for j in np.nonzero(sh)[0]]
    sim = simulate(rl, ctx)
    return sim["nav"][-1] / sim["nav"][0] - stats["HOLD70"]["total_return"]


try:
    null = null_distribution(null_fn, NULL_N, NULL_SEED, actual=actual_diff)
    pct = percentile_of(actual_diff, null)
    null_stats = {"percentile": pct, "mean": float(np.mean(null)), "std": float(np.std(null)),
                  "p90": float(np.quantile(null, 0.9)), "n": int(len(null))}
except Exception as e:  # NoOpNull 等
    null_stats = {"error": f"{type(e).__name__}: {e}"}
    pct = None
print("  实际 TWOWAY−HOLD70 = %+.4f;零分布分位 = %s" % (actual_diff, pct), flush=True)

print("[5] 逐轮表…", flush=True)
rounds_csv = OUT / "t337_rounds.csv"
with rounds_csv.open("w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["round", "kind", "trigger_date", "entry_date", "exit_date", "exit_reason",
                "fng_at_trigger", "mvrv_at_trigger", "mvrv_pct_at_trigger", "puell_at_trigger",
                "puell_pct_at_trigger", "fill1_price", "nav_at_entry", "actions",
                "spot_leg_pnl", "short_leg_pnl", "funding_pnl", "cost", "round_pnl",
                "delta_vs_base", "events_nearby"])
    for k, r in enumerate(res_all["rounds"], 1):
        tr = r["trigger"]
        pm, pp = pct_mvrv.get(tr), pct_puell.get(tr)
        dv = r.get("delta_vs_base", 0.0)
        short_pnl = r.get("short_leg_pnl", 0.0)
        spot_pnl = r["spot_leg_pnl"] if r["kind"] == "cold" else dv - short_pnl
        acts = []
        if r["kind"] == "hot":
            acts.append(f"现货→0.35(卖 {r.get('spot_sold_value', 0.0):.3f});空 {r['short_notional']:.3f}@{r['fill1']:.0f}")
            for a in r["adds"]:
                acts.append(f"加空 {a['notional']:.3f}@{a['price']:.0f}(+{a['level']*100:.0f}%)")
            acts.append(f"预算 B={r['budget']:.3f}")
        else:
            acts.append(f"现金买现货 {r.get('spot_bought_value', 0.0):.3f}@{r['fill1']:.0f}")
            for a in r["adds"]:
                acts.append(f"加现货 {a['notional']:.3f}@{a['price']:.0f}({a['level']*100:.0f}%)")
        ev = EVENTS.get(tr[:7], "")
        w.writerow([k, r["kind"], tr, r["entry"], r["exit"], r["exit_reason"],
                    round(fng.get(tr), 1) if fng.get(tr) is not None else "",
                    round(mvrv.get(tr), 3) if mvrv.get(tr) is not None else "",
                    round(pm, 1) if pm is not None else "",
                    round(puell.get(tr), 3) if puell.get(tr) is not None else "",
                    round(pp, 1) if pp is not None else "",
                    round(r["fill1"], 2), round(r.get("nav_entry", 0.0), 4), "; ".join(acts),
                    round(spot_pnl, 5), round(short_pnl, 5),
                    round(r.get("funding_pnl", 0.0), 5),
                    round(r["cost_spot"] + r["cost_short"], 5),
                    round(spot_pnl + short_pnl, 5), round(dv, 5), ev])
print("  →", rounds_csv, flush=True)

hot_rs = [r for r in res_all["rounds"] if r["kind"] == "hot"]
cold_rs = [r for r in res_all["rounds"] if r["kind"] == "cold"]

print("[6] 审计…", flush=True)
audit = {"fng_ge_95_days": sorted(d for d, v in fng.items() if v >= FNG_HOT),
         "fng_le_10_days": sorted(d for d, v in fng.items() if v <= FNG_COLD),
         "rounds": [], "nav_reconciliation": {}}
for r in res_all["rounds"]:
    tr = r["trigger"]
    i = days.index(tr)
    win = [x for x in fng_s[max(0, i - ARM_WIN + 1): i + 1] if x is not None]
    ei = days.index(r["entry"])
    xi = days.index(r["exit"])
    unreal_at_exit = (SHORT_FIRST * r.get("nav_entry", 0.0) / r["fill1"]) * (r["fill1"] - closes[r["exit"]]) \
        if r["kind"] == "hot" else None
    dv = r.get("delta_vs_base", 0.0)
    short_pnl = r.get("short_leg_pnl", 0.0)
    spot_pnl = r["spot_leg_pnl"] if r["kind"] == "cold" else dv - short_pnl
    audit["rounds"].append({
        "kind": r["kind"], "trigger": tr, "entry": r["entry"], "exit": r["exit"],
        "exit_reason": r["exit_reason"], "entry_px": closes[r["entry"]], "exit_px": closes[r["exit"]],
        "nav_at_entry": r.get("nav_entry"), "delta_vs_base": dv,
        "fng_window_min": min(win) if win else None, "fng_window_max": max(win) if win else None,
        "fng_at_trigger": fng.get(tr), "mvrv_pct": pct_mvrv.get(tr), "puell_pct": pct_puell.get(tr),
        "budget_B": r.get("budget"), "budget_unreal_first_leg_at_exit": unreal_at_exit,
        "spot_leg_pnl": spot_pnl, "short_leg_pnl": short_pnl,
        "round_pnl": spot_pnl + short_pnl,
    })
sum_round = sum(x["round_pnl"] for x in audit["rounds"])
sum_delta = sum(x["delta_vs_base"] for x in audit["rounds"])
audit["nav_reconciliation"] = {
    "twoway_minus_hold70_nav": res_all["nav"][-1] - hold70_nav[-1],
    "sum_of_round_delta_vs_base": sum_delta,
    "sum_of_round_leg_pnl": sum_round,
    "note": ("delta_vs_base = 每一轮出场时该臂净值 − HOLD70 净值(账户口径);"
             "轮与轮之间这笔差额按 0.7/0.3 配置随 BTC 复利放大或缩小,"
             "所以最终净值差 ≠ 各轮 Δ 之和"),
}
print("  fng ≥ 95 天数 %d:%s" % (len(audit["fng_ge_95_days"]), audit["fng_ge_95_days"][:14]), flush=True)
print("  fng ≤ 10 天数 %d(首 %s 末 %s)" % (len(audit["fng_le_10_days"]),
      audit["fng_le_10_days"][0] if audit["fng_le_10_days"] else None,
      audit["fng_le_10_days"][-1] if audit["fng_le_10_days"] else None), flush=True)
for x in audit["rounds"]:
    print("   %s 扳机 %s 入 %s 出 %s(%s) 入价 %.0f 出价 %.0f | fng窗 %.0f~%.0f | mvrv%% %s puell%% %s | 轮盈亏 %+.4f"
          % (x["kind"], x["trigger"], x["entry"], x["exit"], x["exit_reason"], x["entry_px"], x["exit_px"],
             x["fng_window_min"], x["fng_window_max"],
             ("%.1f" % x["mvrv_pct"]) if x["mvrv_pct"] else "n/a",
             ("%.1f" % x["puell_pct"]) if x["puell_pct"] else "n/a", x["round_pnl"]), flush=True)
print("  NAV 对账: TWOWAY−HOLD70(期末) = %+.4f;各轮 Δ 合计 = %+.4f;各腿盈亏合计 = %+.4f"
      % (audit["nav_reconciliation"]["twoway_minus_hold70_nav"], sum_delta, sum_round), flush=True)

results = {
    "task": "T-337", "ledger": "S-813(+11-11 修订)",
    "run_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "window": [START, END], "n_days": n, "data_gate": gate,
    "config": {"spot_w": SPOT_W, "cash_w": CASH_W, "hot_spot_to": HOT_SPOT_TO,
               "short_first": SHORT_FIRST, "short_add_pcts": list(SHORT_ADD_PCTS), "short_max": SHORT_MAX,
               "cold_add": COLD_ADD, "cold_add_pcts": list(COLD_ADD_PCTS), "cost_bps": COST_BPS,
               "hot_exit_ma": HOT_EXIT_MA, "hot_exit_days": HOT_EXIT_DAYS,
               "cold_exit_ma": COLD_EXIT_MA, "cold_exit_days": COLD_EXIT_DAYS,
               "fng_hot": FNG_HOT, "fng_cold": FNG_COLD, "arm_window": ARM_WIN,
               "q_hot": Q_HOT, "q_cold": Q_COLD, "pct_min_obs": PCT_MIN_OBS, "trig_ma": TRIG_MA,
               "null_n": NULL_N, "null_seed": NULL_SEED,
               "fill_convention": "全部成交价 = 信号日收盘;加仓档位按首笔成交价 ×(1±档位)当日收盘触发;时间止损按自然日"},
    "data_counts": {"fng": len(fng), "mvrv": len(mvrv), "issuance": len(issuance),
                    "puell": len(puell), "spot_close": len(spot_close), "perp_close": len(perp_close),
                    "funding": len(funding)},
    "arm_days": {"hot": sum(arm_hot), "cold": sum(arm_cold)},
    "audit": audit,
    "rounds": [{"kind": r["kind"], "trigger": r["trigger"]} for r in rounds],
    "stats": stats,
    "null": {"actual_diff_twoway_minus_hold70": actual_diff, **null_stats},
    "verdict_numbers": {
        "(i) TWOWAY 总收益 > HOLD70": stats["TWOWAY"]["total_return"] > stats["HOLD70"]["total_return"],
        "(ii) 最大回撤不比 HOLD70 深": stats["TWOWAY"]["max_dd"] >= stats["HOLD70"]["max_dd"],
        "(iii) 随机日程分位 ≥ 90": (pct is not None and pct >= 0.90),
        "(iv) 逐轮表两头各自多数为正": {
            "hot_short_legs": [(r["trigger"], round(r.get("short_leg_pnl", 0.0), 5)) for r in hot_rs],
            "cold_added_spot_legs": [(r["trigger"], round(r["spot_leg_pnl"], 5)) for r in cold_rs],
            "hot_majority_positive": (sum(1 for r in hot_rs if r.get("short_leg_pnl", 0.0) > 0) > len(hot_rs) / 2)
            if hot_rs else None,
            "cold_majority_positive": (sum(1 for r in cold_rs if r["spot_leg_pnl"] > 0) > len(cold_rs) / 2)
            if cold_rs else None,
        },
    },
}
(OUT / "t337_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
print("  →", OUT / "t337_results.json", flush=True)
print("[done]", flush=True)
