#!/usr/bin/env python3
"""T-336 / S-812 —— 双向配置级反转(0.7 现货 + 0.3 现金为底)。

预注册:S-812(REFUTATION_LEDGER.md,原文见报告开头)。参数全部写死,算前不改:
  价格   = Binance BTCUSDT / ETHUSDT 永续日线(perp_bv_daily);现货腿按同一收盘记。
  资金费 = v_funding_daily,日资金费 = funding_rate × n(n = 当日结算次数);年化 = 日资金费 × 365。
  阈值   = 一律只用 ≤ d 的扩张分位,每条序列 ≥ 250 个观测才出阈值。
  成本   = 7.5bp × 换手(所有臂同一口径)。

四臂:HOLD70(0.7 现货 + 0.3 现金不动)· HOT(只做过热那头)· COLD(只做过冷那头)· TWOWAY(两头都做)。
另报 HOLD100(1.0 一直拿着)与 ①(层级 ① 基准 = core_variants_daily 的 cap_pit24 NAV)。

零分布 / 分位 / A-B 只用 src/data/evaluation/apparatus.py。
"""
from __future__ import annotations

import csv
import json
import os
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src", "data", "evaluation"))
import apparatus  # noqa: E402  (零分布/分位只用这一个实现)

SUPA = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPK = os.environ.get("SUPABASE_KEY", "")
if not SUPA or not SUPK:
    raise SystemExit("SUPABASE_URL / SUPABASE_KEY 未设置,退出")

PAGE = 1000
COST_BP = 7.5
MIN_OBS = 250
ANN_DAYS = 365.0
SEED = 812
NULL_N = int(os.environ.get("T336_NULL_N", "1000"))
OUT_JSON = os.path.join(HERE, "t336_results.json")
OUT_CSV = os.path.join(HERE, "t336_rounds.csv")


# ── 取数(只读 publishable key;翻页必带 order=)────────────────────────────────
def fetch(table: str, params: dict) -> list[dict]:
    q = dict(params)
    q["select"] = q.get("select", "*")
    q["limit"] = str(PAGE)
    rows: list[dict] = []
    off = 0
    while True:
        q["offset"] = str(off)
        url = SUPA + "/rest/v1/" + table + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(
            url, headers={"apikey": SUPK, "Authorization": "Bearer " + SUPK})
        chunk = json.loads(urllib.request.urlopen(req, timeout=90).read())
        if not isinstance(chunk, list):
            raise RuntimeError(table + ": " + str(chunk)[:200])
        rows.extend(chunk)
        if len(chunk) < PAGE:
            return rows
        off += PAGE


def load_symbol(sym: str) -> tuple[pd.Series, pd.Series]:
    px = fetch("perp_bv_daily", {"symbol": "eq." + sym, "order": "d.asc", "select": "d,c"})
    close = pd.Series({r["d"]: float(r["c"]) for r in px}).sort_index()
    fu = fetch("v_funding_daily",
               {"symbol": "eq." + sym, "order": "d.asc", "select": "d,funding_rate,n"})
    fd = {}
    for r in fu:
        fr, n = r.get("funding_rate"), (r.get("n") or 0)
        fd[r["d"]] = None if fr is None else float(fr) * float(n)
    fund = pd.Series(fd).reindex(close.index)
    return close, fund


def expanding_q(s: pd.Series, q: float, min_obs: int = MIN_OBS) -> pd.Series:
    """扩张分位:第 d 天只看 ≤ d 的观测;不足 min_obs 个有效观测 ⇒ NaN(那几天不判)。"""
    a = s.to_numpy(dtype=float)
    out = np.full(len(a), np.nan)
    vals: list[float] = []
    for i in range(len(a)):
        v = a[i]
        if np.isfinite(v):
            vals.append(v)
        if len(vals) >= min_obs:
            out[i] = float(np.quantile(vals, q))
    return pd.Series(out, index=s.index)


def build_bundle(close: pd.Series, fund: pd.Series) -> dict:
    ma50 = close.rolling(50, min_periods=50).mean()
    ma200 = close.rolling(200, min_periods=200).mean()
    x = close / ma200 - 1.0                                  # 收盘 / 200 日线 − 1
    f7 = fund.rolling(7, min_periods=7).mean() * ANN_DAYS     # 资金费年化 7 日均
    q90x, q10x = expanding_q(x, 0.90), expanding_q(x, 0.10)
    q85f, q15f = expanding_q(f7, 0.85), expanding_q(f7, 0.15)
    hot = ((x >= q90x) & (f7 >= q85f)).fillna(False)
    cold = ((x <= q10x) & (f7 <= q15f)).fillna(False)
    return {"dates": list(close.index), "close": close, "fund": fund, "ma50": ma50,
            "ma200": ma200, "x": x, "f7": f7, "q90x": q90x, "q10x": q10x,
            "q85f": q85f, "q15f": q15f, "hot": hot, "cold": cold}


# ── 引擎 ─────────────────────────────────────────────────────────────────────
def run_arm(b: dict, cfg: dict, *, budget_restores: bool = False, restore_mode: str = "units",
            cost_bp: float = COST_BP) -> tuple[np.ndarray, list[dict]]:
    """一只臂的逐日账。cfg = {name, base_w, hot, cold}。

    资金费:空方收正费率;开仓当日不收(收盘建的仓从次日算)。
    成本:7.5bp × 换手(建仓、加减仓、出场都算,四臂同一口径)。
    进场只在「区的第一天」(信号由 False 变 True 的那一天收盘)—— S-811 原文
    「进(过热区第一天收盘)」;一轮未结束不开新一轮,轮结束后若区还没灭也不重开。
    restore_mode —— 「现货回到 0.7」的两种读法(S-812 只写「现货回到 0.7」,两种都合法):
      "units"  —— **主口径**:把这一轮动过的现货单位原样买回/卖回 = 回到进场前的配置
                  (基仓永远不被悄悄再平衡)。四臂的基仓逐日完全相同 ⇒ TWOWAY − HOLD70
                  只差「这一轮的交易」,是干净的对照。
      "weight" —— 敏感性:出场把现货调回 0.7 权重(= 把 0.7 当配置权重的字面读法)。
                  这会让基仓权重每次出场被再平衡,和「不动」的 HOLD70 不再逐日可比。
    """
    close = b["close"].to_numpy(float)
    fund = b["fund"].to_numpy(float)
    ma50 = b["ma50"].to_numpy(float)
    ma200 = b["ma200"].to_numpy(float)
    hot_sig = b["hot"].to_numpy(bool)
    cold_sig = b["cold"].to_numpy(bool)
    dates = b["dates"]
    n = len(close)
    c = cost_bp / 1e4

    cash = 1.0 - cfg["base_w"]
    spot_units = cfg["base_w"] / close[0]
    cash -= cfg["base_w"] * c                       # 初始建仓成本

    eq = np.empty(n)
    rnd: dict | None = None
    rounds: list[dict] = []

    def short_pnl(tr: dict, p_now: float) -> float:
        """空腿浮盈亏(按入场名义)—— 多空盈亏口径只走 apparatus.short_return。"""
        return tr["u"] * tr["px"] * apparatus.short_return(tr["px"], p_now)

    def long_pnl(units: float, px_in: float, px_out: float) -> float:
        """多腿盈亏 —— 只走 apparatus.long_return。"""
        return units * px_in * apparatus.long_return(px_in, px_out)

    def mark(p: float) -> float:
        e = cash + spot_units * p
        if rnd is not None:
            for t in rnd["tranches"]:
                e += short_pnl(t, p)
        return e

    def open_short(notional: float, p: float) -> None:
        nonlocal cash
        u = notional / p
        t = {"u": u, "px": p, "exit": None, "cost": notional * c}
        rnd["tranches"].append(t)
        rnd["tranche_log"].append(t)
        cash -= notional * c                        # 成本扣现金;名义不占现金

    def close_shorts(p: float) -> None:
        nonlocal cash
        if not rnd["tranches"]:
            return
        # 记账口径:开仓不占现金(线性合约,名义不动现金),平仓时把**浮盈亏**结到现金,
        # 权益 = 现金 + 现货市值 + Σ u×(入场价 − 现价) 三者自洽。
        pnl = sum(short_pnl(t, p) for t in rnd["tranches"])
        gross = sum(t["u"] * p for t in rnd["tranches"])
        for t in rnd["tranches"]:
            t["exit"] = p
            t["cost"] += t["u"] * p * c
        cash += pnl - gross * c
        rnd["tranches"] = []

    def end_round(i: int, p: float, reason: str) -> None:
        nonlocal rnd, cash, spot_units
        close_shorts(p)
        E = mark(p)
        if restore_mode == "units":
            if rnd["zone"] == "hot":
                u_back = rnd["units_sold"]
                cash -= u_back * p * (1.0 + c)
                spot_units += u_back
                restore_cost = u_back * p * c
            else:
                u_sell = sum(t["u"] for t in rnd["add_log"])
                cash += u_sell * p * (1.0 - c)
                spot_units -= u_sell
                restore_cost = u_sell * p * c
        else:                                   # weight:现货调回 0.7 权重
            d = 0.7 * E - spot_units * p
            if d > 0:
                buy = min(d, max(0.0, cash) / (1.0 + c))
                cash -= buy * (1.0 + c)
                spot_units += buy / p
                restore_cost = buy * c
            elif d < 0:
                sell = min(-d, spot_units * p)
                spot_units -= sell / p
                cash += sell * (1.0 - c)
                restore_cost = sell * c
            else:
                restore_cost = 0.0
        E_end = mark(p)

        short_price = sum(short_pnl(t, t["exit"]) for t in rnd["tranche_log"])
        short_cost = sum(t["cost"] for t in rnd["tranche_log"])
        short_net = short_price + rnd["funding"] - short_cost
        # 腿账(恒等式:ΔE = 腿盈亏 + 基仓价格变动 + 空头净盈亏)
        if rnd["zone"] == "hot":
            # 减仓腿:入场按 first_px 卖掉 units_sold,出场时价格 p ⇒ units_sold × (first_px − p)
            leg = (long_pnl(-rnd["units_sold"], rnd["first_px"], p)
                   - rnd["trim_cost"] - restore_cost)
            added_net = 0.0
        else:
            # 加仓腿:每笔加仓的 units × (p − 买入价),减成本
            added_net = (sum(long_pnl(t["u"], t["px"], p) for t in rnd["add_log"])
                         - sum(t["cost"] for t in rnd["add_log"]) - restore_cost)
            leg = added_net
        base_spot = long_pnl(rnd["U_pre"], rnd["first_px"], p)
        delta = E_end - rnd["E_entry"]
        assert abs(delta - (leg + base_spot + short_net)) < 1e-9, (
            f"记账不平: delta={delta} leg={leg} base={base_spot} short={short_net}")
        rounds.append({
            "arm": cfg["name"], "zone": rnd["zone"],
            "entry_date": rnd["entry_date"], "exit_date": dates[i],
            "hold_days": i - rnd["entry_i"],
            "n_adds": rnd["n_adds"],
            "n_tranches": len(rnd["tranche_log"]) if rnd["zone"] == "hot" else len(rnd["add_log"]),
            "entry_px": rnd["first_px"], "exit_px": p,
            "budget": rnd["B"], "budget_stop": "Y" if rnd["budget_stop"] else "N",
            "budget_stop_date": rnd["budget_stop_date"] or "",
            "short_notional": rnd["short_notional"],
            "short_price_pnl": short_price, "short_funding": rnd["funding"],
            "short_cost": short_cost, "short_net": short_net,
            "added_spot_pnl": added_net if rnd["zone"] == "cold" else 0.0,
            "trim_leg_pnl": leg if rnd["zone"] == "hot" else 0.0,
            "leg_pnl": leg, "base_spot_pnl": base_spot,
            "round_equity_delta": delta,
            "exit_reason": reason,
        })
        rnd = None

    for i in range(n):
        p = float(close[i])
        f = float(fund[i]) if np.isfinite(fund[i]) else 0.0

        # 1) 资金费(空方收正费率)—— 只算昨日收盘已在手的空头
        if rnd is not None and rnd["tranches"] and f:
            cf = sum(t["u"] for t in rnd["tranches"]) * p * f
            cash += cf
            rnd["funding"] += cf

        # 2) 预算平空(只有过热轮):浮亏 ≥ B ⇒ 平空;现货要等出场条件才回 0.7
        if rnd is not None and rnd["zone"] == "hot" and rnd["tranches"] and not rnd["budget_stop"]:
            upl = sum(short_pnl(t, p) for t in rnd["tranches"])             # <0 = 浮亏
            loss = max(0.0, -upl)
            if loss > 0 and loss >= rnd["B"]:
                close_shorts(p)
                rnd["budget_stop"] = True
                rnd["budget_stop_date"] = dates[i]
                if budget_restores:                                        # 敏感性:预算平空同时结轮
                    end_round(i, p, "budget")

        # 3) 出场条件
        if rnd is not None:
            days = i - rnd["entry_i"]
            if rnd["zone"] == "hot":
                ma_hit = bool(np.isfinite(ma50[i]) and p < ma50[i])
                hit = ma_hit or days >= 90
                reason = "close<ma50" if ma_hit else ("d90" if days >= 90 else "")
            else:
                ma_hit = bool(np.isfinite(ma200[i]) and p > ma200[i])
                hit = ma_hit or days >= 180
                reason = "close>ma200" if ma_hit else ("d180" if days >= 180 else "")
            if hit:
                end_round(i, p, reason)

        # 4) 加空 / 加仓(出场条件优先:轮要结束了就不再加)
        if rnd is not None and not rnd["budget_stop"]:
            if rnd["zone"] == "hot":
                for lvl, frac in ((1.10, 0.2), (1.20, 0.2)):
                    key = f"{lvl:.2f}"
                    if key not in rnd["add_done"] and p >= rnd["first_px"] * lvl:
                        rnd["add_done"][key] = True
                        notional = frac * mark(p)
                        open_short(notional, p)
                        rnd["short_notional"] += notional
                        rnd["n_adds"] += 1
            else:
                for lvl in (0.90, 0.80):
                    key = f"{lvl:.2f}"
                    if key not in rnd["add_done"] and p <= rnd["first_px"] * lvl:
                        rnd["add_done"][key] = True
                        E_now = mark(p)
                        buy = min(0.1 * E_now, max(0.0, cash) / (1.0 + c))
                        cost = buy * c
                        cash -= buy * (1.0 + c)
                        spot_units += buy / p
                        rnd["add_log"].append({"u": buy / p, "px": p, "cost": cost})
                        rnd["n_adds"] += 1

        # 5) 开新一轮(只在「区的第一天」;一轮未结束不开新一轮)
        if rnd is None:
            prev_hot = bool(hot_sig[i - 1]) if i > 0 else False
            prev_cold = bool(cold_sig[i - 1]) if i > 0 else False
            if cfg["hot"] and bool(hot_sig[i]) and not prev_hot:
                E_entry = mark(p)
                U_pre = spot_units
                sell = min(0.35 * E_entry, spot_units * p)
                spot_units -= sell / p
                cash += sell * (1.0 - c)
                ret90 = (p / float(close[i - 90]) - 1.0) if i >= 90 else 0.0
                rnd = {"zone": "hot", "entry_i": i, "entry_date": dates[i], "first_px": p,
                       "E_entry": E_entry, "B": 0.35 * E_entry * max(0.0, ret90),
                       "tranches": [], "tranche_log": [], "add_log": [], "add_done": {},
                       "funding": 0.0, "budget_stop": False, "budget_stop_date": None,
                       "n_adds": 0, "short_notional": 0.0,
                       "trim_gross": sell, "trim_cost": sell * c,
                       "units_sold": sell / p, "U_pre": U_pre}
                notional = 0.2 * E_entry
                open_short(notional, p)
                rnd["short_notional"] += notional
            elif cfg["cold"] and bool(cold_sig[i]) and not prev_cold:
                E_entry = mark(p)
                rnd = {"zone": "cold", "entry_i": i, "entry_date": dates[i], "first_px": p,
                       "E_entry": E_entry, "B": 0.0, "tranches": [], "tranche_log": [],
                       "add_log": [], "add_done": {}, "funding": 0.0, "budget_stop": False,
                       "budget_stop_date": None, "n_adds": 0, "short_notional": 0.0,
                       "U_pre": spot_units}
                buy = min(0.1 * E_entry, max(0.0, cash) / (1.0 + c))
                cost = buy * c
                cash -= buy * (1.0 + c)
                spot_units += buy / p
                rnd["add_log"].append({"u": buy / p, "px": p, "cost": cost})

        eq[i] = mark(p)

    if rnd is not None:                       # 样本末尾还开着的轮
        end_round(n - 1, float(close[-1]), "end_of_sample")
    return eq, rounds


def maxdd(eq: np.ndarray) -> float:
    peak = np.maximum.accumulate(eq)
    return float((1.0 - eq / peak).max())


def total_return(eq: np.ndarray) -> float:
    return float(eq[-1] / eq[0] - 1.0)


ARMS = [
    {"name": "HOLD70", "base_w": 0.7, "hot": False, "cold": False},
    {"name": "HOLD100", "base_w": 1.0, "hot": False, "cold": False},
    {"name": "HOT", "base_w": 0.7, "hot": True, "cold": False},
    {"name": "COLD", "base_w": 0.7, "hot": False, "cold": True},
    {"name": "TWOWAY", "base_w": 0.7, "hot": True, "cold": True},
]
TW = ARMS[4]


def load_panel_navs() -> tuple[dict, dict | None, str]:
    """① = 层级 ① 基准:registry.core_nav()(全系统唯一读法:cap_pit24 → cap_a1 → cap_a1_u)。

    读不到就退回 core_variants_daily 的 cap_pit24,并在返回值里标明用了哪条。
    返回 (摘要, 逐日序列或 None);逐日序列不进 json(太大),只用于同窗口对照。
    """
    out: dict = {}
    series: dict | None = None
    source = ""
    try:
        import asyncio

        sys.path.insert(0, ROOT)
        from src.data.accounting.registry import core_nav

        s = asyncio.run(core_nav(start="2019-01-01"))
        if s is not None and len(s):
            idx = [str(pd.Timestamp(d).date()) for d in s.index]
            nav = np.array([float(v) for v in s.to_numpy()], dtype=float)
            series = dict(zip(idx, nav.tolist()))
            source = "registry.core_nav()"
            out["core_nav"] = {"source": source, "first": idx[0], "last": idx[-1],
                               "n": len(idx), "nav0": float(nav[0]), "navN": float(nav[-1]),
                               "total_return": float(nav[-1] / nav[0] - 1.0),
                               "maxdd": maxdd(nav)}
    except Exception as e:                                   # 读不到就退回,不悄悄换基准
        out["core_nav_error"] = repr(e)[:200]
    rows = fetch("core_variants_daily",
                 {"arm": "in.(cap_pit24,btc)", "select": "arm,d,nav", "order": "arm.asc,d.asc"})
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["arm"], []).append((r["d"], r["nav"]))
    for arm in ("cap_pit24", "btc"):
        if arm in by:
            s = pd.Series({d: float(v) for d, v in by[arm]}).sort_index()
            out[arm] = {"source": "core_variants_daily", "first": s.index[0], "last": s.index[-1],
                        "n": int(len(s)), "nav0": float(s.iloc[0]), "navN": float(s.iloc[-1]),
                        "total_return": float(s.iloc[-1] / s.iloc[0] - 1.0),
                        "maxdd": maxdd(s.to_numpy(float))}
            if series is None and arm == "cap_pit24":
                series = {d: float(v) for d, v in by[arm]}
                source = "core_variants_daily.cap_pit24(① 历史臂;core_nav 读不到时的退路)"
    return out, series, source


def series_window_return(series: dict, d0: str, d1: str) -> float | None:
    ks = sorted(k for k in series if d0 <= k <= d1)
    if len(ks) < 2:
        return None
    return float(series[ks[-1]] / series[ks[0]] - 1.0)


def window_return(dates: list[str], eq: np.ndarray, d0: str, d1: str) -> float | None:
    idx = [i for i, d in enumerate(dates) if d0 <= d <= d1]
    if len(idx) < 2:
        return None
    return float(eq[idx[-1]] / eq[idx[0]] - 1.0)


def main() -> None:
    panel, panel_series, panel_series_source = load_panel_navs()
    results: dict = {"meta": {
        "card": "T-336", "prereg": "S-812 (REFUTATION_LEDGER.md)",
        "cost_bp": COST_BP, "min_obs": MIN_OBS, "ann_days": ANN_DAYS,
        "seed": SEED, "null_n": NULL_N,
        "funding_convention": "daily = funding_rate × n; annualized = daily × 365",
        "hot_rule": "close/MA200-1 ≥ exp q90 且 f7 ≥ exp q85 ⇒ 现货 0.7→0.35(卖 0.35 倍权益)、空 0.2 倍、+10%/+20% 各加 0.2(上限 0.6)、B=0.35×E×max(0,ret90)、浮亏 ≥ B 平空、出:收盘<MA50 或 90 天 ⇒ 平空 + 现货回 0.7",
        "cold_rule": "close/MA200-1 ≤ exp q10 且 f7 ≤ exp q15 ⇒ 现金买现货 +0.1、-10%/-20% 各加 +0.1(上限 1.0)、无止损、出:收盘>MA200 或 180 天 ⇒ 现货回 0.7",
        "entry_rule": "只在「区的第一天」进场(信号 False→True 的那一天收盘;S-811「进(过热区第一天收盘)」);一轮未结束不开新一轮",
        "restore_mode_primary": "units —— 出场把这一轮动过的现货单位原样买回/卖回 = 回到进场前的配置;四臂基仓逐日相同",
        "notes": "S-812 原文说「浮亏 ≥ B ⇒ 平空」只平空、现货等出场条件才回 0.7(主口径);预算同时结轮是敏感性对照。「现货回到 0.7」两种读法(回到进场前的单位 / 调回 0.7 权重)都跑,主口径=回到进场前的单位。",
    }}
    all_rounds: list[dict] = []
    per_sym: dict = {}

    for sym in ("BTC", "ETH"):
        close, fund = load_symbol(sym)
        b = build_bundle(close, fund)
        dates = b["dates"]
        sig = {k: {"n": int(b[k].sum()),
                   "dates": [d for d, v in zip(dates, b[k]) if bool(v)]}
               for k in ("hot", "cold")}
        overlaps = int((b["hot"] & b["cold"]).sum())
        arms_res: dict = {}
        eqs: dict = {}
        rounds_by_arm: dict = {}
        for cfg in ARMS:
            eq, rounds = run_arm(b, cfg)
            eqs[cfg["name"]] = eq
            rounds_by_arm[cfg["name"]] = rounds
            arms_res[cfg["name"]] = {
                "total_return": total_return(eq), "final_equity": float(eq[-1]),
                "maxdd": maxdd(eq), "n_rounds": len(rounds),
                "first_date": dates[0], "last_date": dates[-1],
            }
        # (i) 总收益 > HOLD70   (ii) 最大回撤不比 HOLD70 深
        actual = arms_res["TWOWAY"]["total_return"] - arms_res["HOLD70"]["total_return"]
        i_ok = arms_res["TWOWAY"]["total_return"] > arms_res["HOLD70"]["total_return"]
        ii_ok = arms_res["TWOWAY"]["maxdd"] <= arms_res["HOLD70"]["maxdd"]
        # (iii) 把两个区的日程整体平移:把「过热=1 / 过冷=2」编成一条日程,一次 circular_shift
        #       同时挪动两个区 ⇒ 偏移相同 ⇒ 两区仍互斥。1,000 次,种子 812。
        sched = b["hot"].to_numpy(int) + 2 * b["cold"].to_numpy(int)
        idx = b["close"].index

        def one_draw(rng, _b=b, _sched=sched, _idx=idx, _hold70=arms_res["HOLD70"]["total_return"]):
            sh = apparatus.circular_shift(_sched, rng, block=1).astype(int)
            b2 = dict(_b)
            b2["hot"] = pd.Series(sh == 1, index=_idx)
            b2["cold"] = pd.Series(sh == 2, index=_idx)
            eq2, _ = run_arm(b2, TW)
            return total_return(eq2) - _hold70

        null_note = ""
        try:
            null = apparatus.null_distribution(one_draw, NULL_N, SEED, actual=actual)
        except apparatus.NoOpNull as e:
            null = np.array([one_draw(np.random.default_rng(SEED + i)) for i in range(NULL_N)])
            null_note = "NoOpNull: " + str(e)
        pct = apparatus.percentile_of(actual, null)
        q90 = float(np.quantile(null, 0.90))
        iii_ok = bool(pct is not None and pct >= 0.90 and actual >= q90)
        # (iv) 逐轮表
        tw = rounds_by_arm["TWOWAY"]
        hot_rounds = [r for r in tw if r["zone"] == "hot"]
        cold_rounds = [r for r in tw if r["zone"] == "cold"]
        hot_pos = sum(1 for r in hot_rounds if r["short_net"] > 0)
        cold_pos = sum(1 for r in cold_rounds if r["added_spot_pnl"] > 0)
        iv_ok = bool(hot_rounds and cold_rounds
                     and hot_pos * 2 > len(hot_rounds) and cold_pos * 2 > len(cold_rounds))
        # 敏感性:预算平空同时把现货回到 0.7(结轮)
        eq_s, rounds_s = run_arm(b, TW, budget_restores=True)
        sens = {"total_return": total_return(eq_s), "maxdd": maxdd(eq_s),
                "diff_vs_hold70": total_return(eq_s) - arms_res["HOLD70"]["total_return"],
                "n_rounds": len(rounds_s),
                "i_pass": total_return(eq_s) > arms_res["HOLD70"]["total_return"],
                "ii_pass": maxdd(eq_s) <= arms_res["HOLD70"]["maxdd"]}
        # 敏感性:出场把现货调回 0.7 权重(把 0.7 当配置权重的字面读法)
        eq_w, rounds_w = run_arm(b, TW, restore_mode="weight")
        sens_weight = {"total_return": total_return(eq_w), "maxdd": maxdd(eq_w),
                       "diff_vs_hold70": total_return(eq_w) - arms_res["HOLD70"]["total_return"],
                       "n_rounds": len(rounds_w),
                       "i_pass": total_return(eq_w) > arms_res["HOLD70"]["total_return"],
                       "ii_pass": maxdd(eq_w) <= arms_res["HOLD70"]["maxdd"]}
        # 与 ① 的同窗口对照(① 用 registry.core_nav;窗口 = 本臂样本窗)
        cmp_panel = {}
        d0, d1 = dates[0], dates[-1]
        for name in ("HOLD70", "HOLD100", "HOT", "COLD", "TWOWAY"):
            cmp_panel[name] = window_return(dates, eqs[name], d0, d1)
        cmp_panel["window"] = [d0, d1]
        if panel_series is not None:
            cmp_panel["①_window_return"] = series_window_return(panel_series, d0, d1)
            cmp_panel["①_series_source"] = panel_series_source
        if "cap_pit24" in panel:
            cmp_panel["①_cap_pit24_full"] = panel["cap_pit24"]["total_return"]
        if "btc" in panel:
            cmp_panel["panel_btc_arm_full"] = panel["btc"]["total_return"]
        # 附加:日收益 A/B(apparatus.ab_test)+ 日差值的 Newey-West t(不是判据,是佐证)
        r70 = np.concatenate([[0.0], np.diff(np.log(eqs["HOLD70"]))])
        rtw = np.concatenate([[0.0], np.diff(np.log(eqs["TWOWAY"]))])
        ab = apparatus.ab_test(r70, rtw, seed=SEED)
        nw = apparatus.newey_west_t(rtw - r70, lags=5)
        per_sym[sym] = {
            "dates": {"first": dates[0], "last": dates[-1], "n": len(dates)},
            "signals": sig, "signal_overlap_days": overlaps,
            "arms": arms_res,
            "criteria": {
                "i_total_return_gt_hold70": {"pass": bool(i_ok),
                    "twoway": arms_res["TWOWAY"]["total_return"],
                    "hold70": arms_res["HOLD70"]["total_return"], "diff": actual},
                "ii_maxdd_not_deeper": {"pass": bool(ii_ok),
                    "twoway_maxdd": arms_res["TWOWAY"]["maxdd"],
                    "hold70_maxdd": arms_res["HOLD70"]["maxdd"]},
                "iii_shift_null": {"pass": iii_ok, "actual": actual,
                    "null_p90_value": q90, "percentile_of_actual": pct,
                    "null_mean": float(null.mean()), "null_min": float(null.min()),
                    "null_max": float(null.max()), "n": int(null.size), "note": null_note},
                "iv_rounds_majority_positive": {"pass": iv_ok,
                    "hot_rounds": len(hot_rounds), "hot_positive": hot_pos,
                    "cold_rounds": len(cold_rounds), "cold_positive": cold_pos},
            },
            "sensitivity_budget_restores_spot": sens,
            "sensitivity_restore_weight": sens_weight,
            "extra_ab_test_hold70_vs_twoway": ab,
            "extra_newey_west_t_daily_diff": {"t": nw[0], "mean": nw[1], "se": nw[2]},
            "vs_panel_1": cmp_panel,
            "monthly": {"dates": dates[::30],
                        **{name: [float(v) for v in eqs[name][::30]] for name in eqs}},
        }
        for arm, rounds in rounds_by_arm.items():
            for r in rounds:
                rr = dict(r)
                rr["symbol"] = sym
                all_rounds.append(rr)

    results["panel_baseline"] = panel
    results["by_symbol"] = per_sym
    results["rounds"] = all_rounds

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        cols = ["symbol", "arm", "zone", "entry_date", "exit_date", "hold_days", "n_adds",
                "n_tranches", "entry_px", "exit_px", "budget", "budget_stop",
                "budget_stop_date", "short_notional", "short_price_pnl", "short_funding",
                "short_cost", "short_net", "added_spot_pnl", "trim_leg_pnl", "leg_pnl",
                "base_spot_pnl", "round_equity_delta", "exit_reason"]
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in all_rounds:
            w.writerow({k: r.get(k, "") for k in cols})

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1, default=str)

    def rnd6(v):
        return round(v, 6) if isinstance(v, (int, float)) and not isinstance(v, bool) else v

    brief = {s: {"arms": {k: {kk: rnd6(vv) for kk, vv in v.items()}
                           for k, v in d["arms"].items()},
                 "criteria": d["criteria"],
                 "signals": {k: v["n"] for k, v in d["signals"].items()},
                 "sens": d["sensitivity_budget_restores_spot"],
                 "sens_weight": d["sensitivity_restore_weight"],
                 "vs_panel_1": d["vs_panel_1"]}
             for s, d in per_sym.items()}
    brief["panel"] = panel
    brief["n_rounds_rows"] = len(all_rounds)
    # stdout 只出摘要(完整结果在 t336_results.json)
    for s, d in per_sym.items():
        a = d["arms"]
        c = d["criteria"]
        print(f"{s} signals hot={d['signals']['hot']['n']} cold={d['signals']['cold']['n']} "
              f"| HOLD70 {a['HOLD70']['total_return']:.4f} dd {a['HOLD70']['maxdd']:.4f} "
              f"| HOLD100 {a['HOLD100']['total_return']:.4f} "
              f"| HOT {a['HOT']['total_return']:.4f} r{a['HOT']['n_rounds']} "
              f"| COLD {a['COLD']['total_return']:.4f} r{a['COLD']['n_rounds']} "
              f"| TWOWAY {a['TWOWAY']['total_return']:.4f} dd {a['TWOWAY']['maxdd']:.4f} "
              f"r{a['TWOWAY']['n_rounds']}")
        print(f"  i={c['i_total_return_gt_hold70']['pass']} diff={c['i_total_return_gt_hold70']['diff']:.4f} "
              f"ii={c['ii_maxdd_not_deeper']['pass']} "
              f"iii={c['iii_shift_null']['pass']} pct={c['iii_shift_null']['percentile_of_actual']} "
              f"nullq90={c['iii_shift_null']['null_p90_value']:.4f} "
              f"iv={c['iv_rounds_majority_positive']['pass']} "
              f"hot{c['iv_rounds_majority_positive']['hot_rounds']}+{c['iv_rounds_majority_positive']['hot_positive']} "
              f"cold{c['iv_rounds_majority_positive']['cold_rounds']}+{c['iv_rounds_majority_positive']['cold_positive']} "
              f"| sens_budget {d['sensitivity_budget_restores_spot']['total_return']:.4f} "
              f"| sens_weight {d['sensitivity_restore_weight']['total_return']:.4f} "
              f"(i={d['sensitivity_restore_weight']['i_pass']})")
        print(f"  vs_panel1 {json.dumps(d['vs_panel_1'], ensure_ascii=False, default=str)}")
    print("panel " + json.dumps(panel, ensure_ascii=False, default=str))
    print("rounds_rows " + str(len(all_rounds)))


if __name__ == "__main__":
    main()
