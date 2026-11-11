#!/usr/bin/env python3
"""T-335(S-811)—— Jazz 的做空写法:过热区卖 50% 多头、用落袋利润分批加空、扛单无价格止损、
风险预算 = 刚落袋的利润;对「一直拿着」(HOLD)与「只减仓不做空」(TRIM)。

三臂(同一份价格、同一套进出时点、同一成本与资金费口径):
  HOLD        1.0 倍 BTC 一直拿着
  TRIM        同样的进出时点:卖 50% 多头,出场买回,不做空
  TRIM+SHORT  Jazz 的写法:卖 50% 多头 → 第 1 笔空 0.25 倍名义 → 价格较第 1 笔再涨 +10%/+20%
              各加 0.25 倍(最多 0.75 倍)→ 浮亏 ≥ 预算 B 全部平空并把多头买回 1.0 → 收盘跌破
              50 日均线或首笔空起 90 天到期,全部平空、多头买回 1.0。

数据:只读 Supabase(`perp_bv_daily` 价格 / `v_funding_daily` 资金费),缓存到
/Volumes/CometCloudAI/cometcloud-local/research/t335/cache/。零分布、盈亏只走
`src/data/evaluation/apparatus.py`(circular_shift / null_distribution / percentile_of /
long_return / short_return)。

用法:python3 docs/research/t335_trim_short.py [btc|eth|all]      (默认 all)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from docs.research.crash_atlas_common import expanding_pct  # noqa: E402
from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    circular_shift,
    long_return,
    null_distribution,
    percentile_of,
    short_return,
)

# ───────────────────────────── 写死(S-811 原文) ─────────────────────────────
COST = 0.00075            # 成本 7.5bp × 换手
MA50 = 50                 # 出场:收盘第一次低于 50 日均线
MA200 = 200               # 过热区:收盘 / 200 日均线 − 1
PCT_EXT = 0.90            # 扩展度 ≥ 扩张 90 分位(崩盘图谱 P2)
PCT_FUND = 0.85           # 资金费年化 7 日均 ≥ 扩张 85 分位
MIN_OBS = 250             # 各 ≥ 250 个观测
ADD_LEVELS = (1.10, 1.20)  # 较第 1 笔再涨 +10% / +20% 各加一笔
SHORT_LEGS = (0.25, 0.25, 0.25)   # 0.25 / 0.50 / 0.75 倍名义(基准 = 进场时账户值)
TRIM_SHARE = 0.5          # 卖掉 50% 多头
BUDGET_LOOKBACK_D = 90    # B = 0.5 × 账户 × max(0, 收盘 / 90 天前收盘 − 1)
TIME_STOP_D = 90          # 首笔空起 90 天到期
N_NULL = 1000
SEED = 811

CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t335/cache")
OUT_MD = HERE / "T-335_trim_and_short.md"
OUT_JSON = HERE / "t335_results.json"
OUT_CSV = HERE / "t335_rounds.csv"
OUT_SCEN = HERE / "scenarios" / "lane-b-T-335.json"

S811_QUOTE = """## S-811 — Jazz 的做空写法:**高位卖掉多头的利润、用利润分批加空、扛单不设价格止损**,风险上限 = 刚落袋的利润 —— 对「一直拿着」与「只减仓不做空」—— 预注册(Seth,2026-11-11 03:18 UTC;Jazz 11-11「很多时候空头需要扛单,高位卖了多头的利润加仓空头,而不是裸空到止损线就止损」;这种「减多 → 用利润加空 → 回落后买回」的组合动作从没算过;交 B 道 T-335)
**为什么。** S-736 / S-808 / S-809 都是**裸空 + 紧止损**:217 / 350 张在 2 天内被打掉。Jazz 的写法把空头放在组合里:空单的本钱是刚从多头上落袋的利润,所以可以扛;越涨越加(均价抬高),回落时一起兑现,再把多头买回来。它问的不是「能不能猜对顶」,而是「在过热区把一部分多头换成空头,整个账户是不是更好」。
**写死(BTC 为主,ETH 同口径只报):** 价格 = Binance BTCUSDT 永续日线(`perp_bv_daily`),2019-12 起;基础持仓 = 1.0 倍 BTC。
- **过热区(只用 ≤ d 的数据):** 收盘 / 200 日均线 − 1 ≥ 其扩张 90 分位(崩盘图谱 P2)**且** BTC 资金费年化 7 日均 ≥ 其扩张 85 分位(拥挤多头,`v_funding_daily`);各 ≥ 250 个观测。
- **进(过热区第一天收盘):** 卖掉 50% 多头;利润预算 B = 0.5 × 账户 × max(0, 收盘 / 90 天前收盘 − 1)(卖掉那一半近 90 天的涨幅)。第 1 笔空 = 0.25 倍名义;此后价格较第 1 笔再涨 +10%、+20% 各加 0.25 倍(最多 0.75 倍,净头寸最低 −0.25 倍)。**不设价格止损**;唯一的风控:空头累计浮亏 ≥ B ⇒ 全部平空、多头回到 1.0。
- **出:** 收盘第一次低于 50 日均线 ⇒ 全部平空、多头买回到 1.0;或首笔空起 90 天到期同样处理。期间过热区再触发不叠加新的一轮。
- 成本 7.5bp × 换手,资金费按持有期实计(空方收正费率)。
**三臂:** HOLD(1.0 倍一直拿着)· TRIM(同样的进出时点,只减 50% 再买回,不做空)· **TRIM+SHORT(Jazz 的写法)**。
**判(全过才 ✅):** (i) TRIM+SHORT 总收益 > HOLD **且** > TRIM(空头那部分本身要加分);(ii) 最大回撤不比 HOLD 深;(iii) 随机对照:把「过热区」日程整体平移(`apparatus.circular_shift`,1,000 次,种子 811),TRIM+SHORT − HOLD 的实际值 ≥ 零分布 90 分位;(iv) 逐轮列出(每一轮的进出日、加了几笔空、空头盈亏、是否触发预算平仓),**多数轮次空头盈亏为正**。
**诚实:** 2019–2026 的过热轮次大概只有 5–8 轮,检出力很弱 —— 逐轮表比汇总数更重要。DECISIONS 10-21 定过「降敞口 = 卖现货 + 放贷,不开对冲空单」、③ 只在 0–1 倍;这条若过,要 Jazz 改那条规则才能动钱。**试验计数:做空族 +1。**"""


# ───────────────────────────── 取数(只读 + 缓存) ─────────────────────────────
def pull(table: str, params: dict, page: int = 1000) -> list[dict]:
    """PostgREST 翻页读。必须带 order=(按主键排);每页 ≤ 1000 行(limit>1000 会被静默截断)。"""
    rows: list[dict] = []
    off = 0
    while True:
        q = dict(params)
        q["limit"] = str(page)
        q["offset"] = str(off)
        url = f"{U}/rest/v1/{table}?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers=H)
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read())
        if not isinstance(body, list):
            raise RuntimeError(f"{table}: {str(body)[:200]}")
        rows.extend(body)
        if len(body) < page:
            return rows
        off += page


def load(name: str, table: str, params: dict) -> list[dict]:
    p = CACHE / f"{name}.json"
    if p.exists():
        rows = json.loads(p.read_text())
        print(f"  cache {name}: {len(rows)} rows", flush=True)
        return rows
    rows = pull(table, params)
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows))
    print(f"  pulled {name}: {len(rows)} rows", flush=True)
    return rows


U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}


class Ctx:
    """一个品种的全部上下文(价格、指标、资金费)。"""

    def __init__(self, sym: str, pair: str):
        self.sym = sym
        self.pair = pair
        perp = load(f"perp_{sym}", "perp_bv_daily",
                    {"select": "d,o,h,l,c,pair,symbol,recorded_at", "pair": f"eq.{pair}",
                     "order": "d.asc,recorded_at.asc"})
        vf = load(f"vfund_{sym}", "v_funding_daily",
                  {"select": "d,symbol,funding_rate,n", "symbol": f"eq.{sym}",
                   "order": "d.asc,symbol.asc"})

        # ── bar:同一日多条 ⇒ 取 recorded_at 最晚的一条 ──
        by_d: dict[str, dict] = {}
        n_dup = 0
        for r in perp:
            if any(r.get(k) is None for k in ("o", "h", "l", "c")):
                continue
            dd = str(r["d"])[:10]
            if dd in by_d:
                n_dup += 1
            by_d[dd] = {"d": dd, "o": float(r["o"]), "h": float(r["h"]),
                        "l": float(r["l"]), "c": float(r["c"])}
        self.bars = [by_d[d] for d in sorted(by_d)]
        self.dates = [b["d"] for b in self.bars]
        self.close = np.array([b["c"] for b in self.bars], dtype=float)
        self.n_dup = n_dup
        self.n = len(self.bars)
        self.dt = np.array([date.fromisoformat(d) for d in self.dates], dtype="datetime64[D]")

        # ── 资金费:v_funding_daily.funding_rate = 每个 8h 间隔的均值,n = 当日间隔数
        #    日内合计 = rate × n;年化 = 日内合计 × 365(8h × 3/日 × 365 天 = 1095 个间隔/年)──
        fund: dict[str, float] = {}
        for r in vf:
            dd = str(r["d"])[:10]
            nn = int(r.get("n") or 1)
            fund[dd] = fund.get(dd, 0.0) + float(r["funding_rate"]) * nn
        self.fund_daily = np.array([fund.get(d, 0.0) for d in self.dates], dtype=float)
        self.fund_cov = np.array([1.0 if d in fund else 0.0 for d in self.dates], dtype=float)

        # ── 指标(只用 ≤ d)──
        s = pd.Series(self.close, index=pd.Index(self.dates))
        self.ma50 = s.rolling(MA50, min_periods=MA50).mean().to_numpy()
        ma200 = s.rolling(MA200, min_periods=MA200).mean()
        ext = (s / ma200 - 1.0).to_numpy()
        self.pct_ext = expanding_pct(pd.Series(ext, index=s.index), min_periods=MIN_OBS).to_numpy()
        ann = self.fund_daily * 365.0
        m7 = pd.Series(ann, index=s.index).rolling(7, min_periods=7).mean()
        self.m7_ann = m7.to_numpy()
        self.pct_fund = expanding_pct(m7, min_periods=MIN_OBS).to_numpy()
        ok_a = np.isfinite(self.pct_ext)
        ok_b = np.isfinite(self.pct_fund)
        self.overheat = ok_a & ok_b & (self.pct_ext >= PCT_EXT) & (self.pct_fund >= PCT_FUND)
        # 90 天前收盘(日期口径,asof)
        self.p90 = np.full(self.n, np.nan)
        for i, d in enumerate(self.dates):
            tgt = np.datetime64(date.fromisoformat(d) - timedelta(days=BUDGET_LOOKBACK_D), "D")
            j = int(np.searchsorted(self.dt, tgt, side="right")) - 1
            if j >= 0:
                self.p90[i] = self.close[j]

    def time_stop_idx(self, e: int) -> int:
        tgt = np.datetime64(date.fromisoformat(self.dates[e]) + timedelta(days=TIME_STOP_D), "D")
        j = int(np.searchsorted(self.dt, tgt, side="left"))
        return min(j, self.n - 1)


# ───────────────────────────── 模拟引擎 ─────────────────────────────
def _close_shorts(lots: list[dict], p: float, cash: float) -> tuple[float, float]:
    """全部平空(买回)。返回 (cash, 空头毛盈亏)。lots 不被修改。"""
    proceeds = sum(l["qty"] * p for l in lots)
    cash += proceeds - COST * proceeds
    gross = sum((l["px"] - p) * l["qty"] for l in lots)
    return cash, gross


def _restore_long(cash: float, qty: float, p: float) -> tuple[float, float]:
    """把账户买回「1.0 倍」:全额换成 BTC(1.0 = 账户的 1.0 倍)。返回 (qty, 账户值)。"""
    a_total = cash + qty * p
    a_end = a_total / (1.0 + COST)
    return a_end / p, a_end


def simulate_round(ctx: Ctx, e: int, cash: float, qty: float) -> dict:
    """一轮 TRIM+SHORT:进场(卖 50% 多头 + 第 1 笔空)→ 加空 → 平仓。返回轮次账 + 净值片段。"""
    px, n = ctx.close, ctx.n
    p_e = float(px[e])
    a_pre = qty * p_e + cash

    # ── 卖 50% 多头 ──
    qty_sold = qty * TRIM_SHARE
    proceeds = qty_sold * p_e
    cash += proceeds - COST * proceeds
    qty -= qty_sold
    a_after = qty * p_e + cash                      # 账户值(已扣成本)

    # ── 利润预算 B ──
    p90 = ctx.p90[e]
    gain90 = 0.0 if not np.isfinite(p90) or p90 <= 0 else max(0.0, p_e / p90 - 1.0)
    budget = 0.5 * a_after * gain90

    # ── 第 1 笔空:0.25 倍名义(基准 = 进场时账户值 a_after)──
    base = a_after
    lots: list[dict] = []
    n1 = SHORT_LEGS[0] * base
    lots.append({"qty": n1 / p_e, "px": p_e, "notional": n1})
    cash -= COST * n1
    p1 = p_e

    ts_idx = ctx.time_stop_idx(e)
    nav: dict[int, float] = {e: qty * p_e + cash}   # 进场收盘的净值(已扣开空成本)
    exit_i, exit_reason = None, None
    gross_short = 0.0
    funding = 0.0
    cost_short = COST * n1
    n_adds = 0
    budget_hit = False
    entry_below_ma50 = bool(np.isfinite(ctx.ma50[e]) and p_e < ctx.ma50[e])

    for d in range(e + 1, n):
        p = float(px[d])
        # 资金费(空方收正费率):持有日 (进场日, 平仓日]
        if lots:
            qsum = sum(l["qty"] for l in lots)
            f = qsum * p * ctx.fund_daily[d]
            funding += f
            cash += f
        float_pnl = sum((l["px"] - p) * l["qty"] for l in lots)
        nav[d] = qty * p + cash + float_pnl

        # ① 预算风控(唯一的风控):空头累计浮亏 ≥ B
        if lots and float_pnl <= -budget:
            cash, gross_short = _close_shorts(lots, p, cash)
            cost_short += COST * sum(l["qty"] * p for l in lots)
            lots_snapshot = lots
            lots = []
            qty, a_end = _restore_long(cash, qty, p)
            cash = 0.0
            exit_i, exit_reason, budget_hit = d, "budget", True
            nav[d] = qty * p
            break

        # ② 出场:收盘第一次低于 50 日均线 / 首笔空起 90 天到期
        below_ma50 = bool(np.isfinite(ctx.ma50[d]) and p < ctx.ma50[d])
        if below_ma50 or d >= ts_idx:
            cash, gross_short = _close_shorts(lots, p, cash)
            cost_short += COST * sum(l["qty"] * p for l in lots)
            lots_snapshot = lots
            lots = []
            qty, a_end = _restore_long(cash, qty, p)
            cash = 0.0
            exit_i = d
            exit_reason = "ma50" if below_ma50 else "time"
            nav[d] = qty * p
            break

        # ③ 加空:较第 1 笔再涨 +10% / +20% 各加 0.25 倍
        for k, lvl in enumerate(ADD_LEVELS):
            if len(lots) == k + 1 and p >= lvl * p1:
                nn = SHORT_LEGS[k + 1] * base
                lots.append({"qty": nn / p, "px": p, "notional": nn})
                cash -= COST * nn
                cost_short += COST * nn
                n_adds += 1
                float_pnl = sum((l["px"] - p) * l["qty"] for l in lots)
                nav[d] = qty * p + cash + float_pnl

    if exit_i is None:
        # 数据末端仍持仓:按最后收盘标记并平掉
        p = float(px[n - 1])
        cash, gross_short = _close_shorts(lots, p, cash)
        cost_short += COST * sum(l["qty"] * p for l in lots)
        lots_snapshot = lots
        lots = []
        qty, _ = _restore_long(cash, qty, p)
        cash = 0.0
        exit_i, exit_reason = n - 1, "eod"
        nav[n - 1] = qty * p

    p_exit = float(px[exit_i])
    short_net = gross_short + funding - cost_short
    long_gross = (p_e - p_exit) * qty_sold
    return {
        "entry_i": e, "exit_i": exit_i,
        "entry_d": ctx.dates[e], "exit_d": ctx.dates[exit_i],
        "exit_reason": exit_reason, "budget_hit": budget_hit,
        "n_adds": n_adds, "n_lots": 1 + n_adds,
        "p_entry": p_e, "p_exit": p_exit,
        "p90": float(p90) if np.isfinite(p90) else None,
        "gain90": gain90, "budget": budget,
        "a_pre": a_pre, "a_after": a_after,
        "short_gross": gross_short, "short_funding": funding,
        "short_cost": cost_short, "short_net": short_net,
        "long_gross": long_gross,
        "short_ret_lots": [short_return(l["px"], p_exit) for l in lots_snapshot],
        "long_ret_trim": long_return(p_e, p_exit),
        "nav": nav, "cash": cash, "qty": qty,
        "entry_below_ma50": entry_below_ma50,
    }


def run_strategy(ctx: Ctx, overheat: np.ndarray, collect_nav: bool = True) -> dict:
    """按过热区日程跑 TRIM+SHORT。返回轮次表 + 净值 + 末态。"""
    n = ctx.n
    px = ctx.close
    cash, qty = 0.0, 1.0 / float(px[0])     # A0 = 1.0,全仓 BTC
    rounds: list[dict] = []
    i = 0
    open_until = -1
    while i < n:
        if not overheat[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and overheat[j + 1]:
            j += 1
        if i <= open_until:                 # 上一轮未结束 ⇒ 这一段过热不叠加新轮
            i = j + 1
            continue
        rnd = simulate_round(ctx, i, cash, qty)
        cash, qty = rnd["cash"], rnd["qty"]
        rounds.append(rnd)
        open_until = rnd["exit_i"]
        i = max(j, rnd["exit_i"]) + 1

    nav = np.full(n, np.nan)
    if collect_nav:
        cur_qty = 1.0 / float(px[0])
        pos = 0
        for rnd in rounds:
            e, x = rnd["entry_i"], rnd["exit_i"]
            for d in range(pos, e):
                nav[d] = cur_qty * px[d]
            for d, v in rnd["nav"].items():
                nav[d] = v
            cur_qty = rnd["qty"]
            pos = x + 1
        for d in range(pos, n):
            nav[d] = cur_qty * px[d]
    final_nav = float(qty * px[-1] + cash)
    return {"rounds": rounds, "nav": nav, "cash": cash, "qty": qty, "final_nav": final_nav}


def run_trim(ctx: Ctx, round_dates: list[tuple[int, int]]) -> dict:
    """TRIM 臂:同样的进出时点,只卖 50% 再买回,不做空。账户结构与 TRIM+SHORT 同口径
    (轮与轮之间全仓 BTC;轮内 50% BTC + 50% 现金;出场全额换回 BTC)。"""
    n = ctx.n
    px = ctx.close
    cash, qty = 0.0, 1.0 / float(px[0])
    nav = np.full(n, np.nan)
    marks = []
    prev_end = 0
    for (e, x) in round_dates:
        for d in range(prev_end, e):          # 轮与轮之间:全仓 BTC
            nav[d] = qty * px[d]
        p_e = float(px[e])
        qty_sold = qty * TRIM_SHARE
        proceeds = qty_sold * p_e
        cash += proceeds - COST * proceeds
        qty -= qty_sold
        for d in range(e, x):                  # 轮内:50% BTC + 50% 现金
            nav[d] = qty * px[d] + cash
        p_x = float(px[x])
        a_total = cash + qty * p_x
        a_end = a_total / (1.0 + COST)
        qty = a_end / p_x
        cash = 0.0
        nav[x] = qty * p_x
        prev_end = x + 1
        marks.append({"entry_d": ctx.dates[e], "exit_d": ctx.dates[x]})
    for d in range(prev_end, n):
        nav[d] = qty * px[d]
    return {"nav": nav, "final_nav": float(qty * px[-1] + cash), "marks": marks}


def hold_nav(ctx: Ctx) -> np.ndarray:
    return (1.0 / float(ctx.close[0])) * ctx.close


def max_drawdown(nav: np.ndarray) -> float:
    peak = np.maximum.accumulate(nav)
    return float(np.min(nav / peak - 1.0))


def total_return(nav: np.ndarray) -> float:
    return float(nav[-1] / nav[0] - 1.0)


# ───────────────────────────── 跑一个品种 ─────────────────────────────
def run_symbol(ctx: Ctx, label: str) -> dict:
    print(f"[{label}] {ctx.sym}: bars={ctx.n} {ctx.dates[0]}→{ctx.dates[-1]} "
          f"(同日重复 {ctx.n_dup})", flush=True)
    nav_hold = hold_nav(ctx)
    res = run_strategy(ctx, ctx.overheat, collect_nav=True)
    nav_ts = res["nav"]
    round_dates = [(r["entry_i"], r["exit_i"]) for r in res["rounds"]]
    res_trim = run_trim(ctx, round_dates)
    nav_trim = res_trim["nav"]

    out = {
        "symbol": ctx.sym,
        "bars": ctx.n, "start": ctx.dates[0], "end": ctx.dates[-1],
        "n_rounds": len(res["rounds"]),
        "overheat_days": int(ctx.overheat.sum()),
        "overheat_run_starts": [ctx.dates[i] for i in
                                np.flatnonzero(ctx.overheat & ~np.r_[False, ctx.overheat[:-1]])],
        "arms": {
            "HOLD": {"total_return": total_return(nav_hold), "max_dd": max_drawdown(nav_hold),
                     "final_nav": float(nav_hold[-1])},
            "TRIM": {"total_return": total_return(nav_trim), "max_dd": max_drawdown(nav_trim),
                     "final_nav": float(nav_trim[-1])},
            "TRIM+SHORT": {"total_return": total_return(nav_ts), "max_dd": max_drawdown(nav_ts),
                           "final_nav": float(nav_ts[-1])},
        },
        "rounds": [{k: v for k, v in r.items() if k != "nav"} for r in res["rounds"]],
    }

    # ── 随机对照:整条「过热区」日程循环平移 1,000 次(种子 811)──
    actual = out["arms"]["TRIM+SHORT"]["total_return"] - out["arms"]["HOLD"]["total_return"]
    hold_end = float(nav_hold[-1])

    def _shift_sim(rng: np.random.Generator) -> float:
        sh = circular_shift(ctx.overheat, rng, block=1)
        r = run_strategy(ctx, sh, collect_nav=False)
        return r["final_nav"] - hold_end      # TRIM+SHORT 末值 − HOLD 末值

    try:
        null = null_distribution(_shift_sim, N_NULL, SEED)
        pct = percentile_of(actual, null)
        null_stats = {
            "n": N_NULL, "seed": SEED, "actual": actual, "percentile": pct,
            "null_mean": float(np.mean(null)), "null_std": float(np.std(null)),
            "null_p10": float(np.percentile(null, 10)), "null_p50": float(np.percentile(null, 50)),
            "null_p90": float(np.percentile(null, 90)), "null_max": float(np.max(null)),
            "null_min": float(np.min(null)),
            "frac_ge_actual": float(np.mean(null >= actual)),
        }
    except NoOpNull as exc:
        null_stats = {"n": N_NULL, "seed": SEED, "actual": actual, "percentile": None,
                      "error": str(exc)}
    out["null"] = null_stats

    # ── 判定 (i)–(iv)──
    a = out["arms"]
    j1 = bool(a["TRIM+SHORT"]["total_return"] > a["HOLD"]["total_return"]
               and a["TRIM+SHORT"]["total_return"] > a["TRIM"]["total_return"])
    j2 = bool(a["TRIM+SHORT"]["max_dd"] >= a["HOLD"]["max_dd"])
    pct = null_stats.get("percentile")
    j3 = bool(pct is not None and pct >= 0.90)
    pos = [r for r in res["rounds"] if r["short_net"] > 0]
    j4 = bool(res["rounds"] and len(pos) > len(res["rounds"]) / 2)
    out["judge"] = {
        "i_total_return_gt_hold_and_trim": j1,
        "ii_maxdd_not_deeper_than_hold": j2,
        "iii_null_percentile_ge_90": j3,
        "iv_majority_rounds_short_pnl_positive": j4,
        "all_pass": bool(j1 and j2 and j3 and j4),
        "rounds_short_pnl_positive": len(pos), "rounds_total": len(res["rounds"]),
    }
    print(f"[{label}] 轮次 {out['n_rounds']} · HOLD {a['HOLD']['total_return']:.4f} · "
          f"TRIM {a['TRIM']['total_return']:.4f} · TRIM+SHORT {a['TRIM+SHORT']['total_return']:.4f} · "
          f"Δ={actual:.4f} · 分位 {pct} · 判定 {out['judge']}", flush=True)
    return out


# ───────────────────────────── 主流程 ─────────────────────────────
def main() -> None:
    which = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    print("[1/4] 读数据…", flush=True)
    ctxs = {}
    if which in ("btc", "all"):
        ctxs["BTC"] = Ctx("BTC", "BTCUSDT")
    if which in ("eth", "all"):
        ctxs["ETH"] = Ctx("ETH", "ETHUSDT")

    print("[2/4] 跑三臂…", flush=True)
    results = {}
    for label, ctx in ctxs.items():
        results[label] = run_symbol(ctx, label)

    print("[3/4] 写结果…", flush=True)
    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=float))

    rows = ["symbol,entry_d,exit_d,exit_reason,budget_hit,n_adds,n_lots,p_entry,p_exit,"
            "gain90,budget,short_gross,short_funding,short_cost,short_net,long_gross,"
            "a_pre,a_after,entry_below_ma50"]
    for label, r in results.items():
        for rd in r["rounds"]:
            rows.append(",".join([
                label, rd["entry_d"], rd["exit_d"], rd["exit_reason"], str(rd["budget_hit"]),
                str(rd["n_adds"]), str(rd["n_lots"]), f"{rd['p_entry']:.4f}", f"{rd['p_exit']:.4f}",
                f"{rd['gain90']:.6f}", f"{rd['budget']:.6f}", f"{rd['short_gross']:.6f}",
                f"{rd['short_funding']:.6f}", f"{rd['short_cost']:.6f}", f"{rd['short_net']:.6f}",
                f"{rd['long_gross']:.6f}", f"{rd['a_pre']:.6f}", f"{rd['a_after']:.6f}",
                str(rd["entry_below_ma50"]),
            ]))
    OUT_CSV.write_text("\n".join(rows) + "\n")

    write_md(results)
    print("[4/4] 写报告 + 情景文件…", flush=True)
    write_scenarios(results)
    print("done", flush=True)


def _pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def write_md(results: dict) -> None:
    btc = results.get("BTC")
    lines: list[str] = []
    lines.append("# T-335(S-811)—— Jazz 的做空写法:过热区卖 50% 多头、用利润分批加空、"
                 "扛单无价格止损、预算 = 落袋利润")
    lines.append("")
    lines.append("> 只读研究:数据 = Supabase `perp_bv_daily` / `v_funding_daily`(不写库);"
                 "零分布与盈亏只走 `src/data/evaluation/apparatus.py`。"
                 "**试验计数:做空族 +1。**")
    lines.append("")
    lines.append("## 0. 预注册原文(S-811,照抄)")
    lines.append("")
    lines.append("```text")
    lines.append(S811_QUOTE)
    lines.append("```")
    lines.append("")
    lines.append("## 1. 口径与本卡读法(有歧义处写死)")
    lines.append("")
    lines.append("| 项 | 本卡取法 |")
    lines.append("|---|---|")
    lines.append("| 基础持仓 | A0 = 1.0(归一),全仓 BTC(现货腿,不吃资金费);`perp_bv_daily` 收盘成交 |")
    lines.append("| 过热区 | 收盘/MA200 − 1 ≥ 自身扩张 90 分位 **且** 资金费年化 7 日均 ≥ 自身扩张 85 分位;"
                 "两个分位都只用 ≤ d 的数据、各 ≥ 250 个观测 |")
    lines.append("| 资金费口径 | `v_funding_daily.funding_rate` = 每个 8h 间隔的均值,`n` = 当日间隔数;"
                 "日内合计 = rate × n,年化 = 日内合计 × 365 |")
    lines.append("| 一轮 | 过热区的**第一段连续区间的第一天收盘**进场;该段被这一轮占用后不叠加新轮;"
                 "下一段过热(且上一轮已平)才开新一轮 |")
    lines.append("| 空头名义基准 | 进场时账户值 a_after(卖 50% 多头、已扣成本);三笔 = 0.25 / 0.50 / 0.75 × a_after |")
    lines.append("| 预算 B | 0.5 × a_after × max(0, 进场收盘 / 90 天前收盘 − 1);"
                 "**空头累计浮亏 ≥ B ⇒ 当日收盘全部平空 + 多头买回 1.0**;从进场的次日起判 |")
    lines.append("| 出场 | 收盘第一次低于 MA50,或首笔空起 90 个日历日到期;两者动作相同 |")
    lines.append("| 「多头买回到 1.0」 | 账户**全额换回 BTC**(1.0 = 账户的 1.0 倍)⇒ 这一轮的钱全部留在仓位里,"
                 "不落现金;TRIM 臂同口径 |")
    lines.append("| 成本 | 7.5bp × 每次成交名义(买 + 卖各算一次) |")
    lines.append("| 资金费 | 持有日 (进场日, 平仓日] 实计;空方收正费率(按当日名义 × 当日资金费率) |")
    lines.append("| 轮内检查顺序 | 资金费 → 预算风控 → 出场 → 加空(+10% / +20% 较第 1 笔) |")
    lines.append("")
    lines.append("## 2. 结果(BTC 为主,ETH 同口径只报)")
    lines.append("")
    for label, r in results.items():
        a = r["arms"]
        lines.append(f"### {label}({r['start']} → {r['end']},{r['bars']} 根;过热日 {r['overheat_days']} 天,"
                     f"轮次 {r['n_rounds']})")
        lines.append("")
        lines.append("| 臂 | 总收益 | 最大回撤 | 末值 |")
        lines.append("|---|---|---|---|")
        for k in ("HOLD", "TRIM", "TRIM+SHORT"):
            lines.append(f"| {k} | {_pct(a[k]['total_return'])} | {a[k]['max_dd'] * 100:.2f}% | "
                         f"{a[k]['final_nav']:.4f} |")
        lines.append("")
        nl = r["null"]
        if nl.get("percentile") is None:
            lines.append(f"- TRIM+SHORT − HOLD = **{_pct(nl['actual'])}**;零分布失败:{nl.get('error')}")
        else:
            lines.append(f"- TRIM+SHORT − HOLD = **{_pct(nl['actual'])}**;"
                         f"零分布(循环平移 {nl['n']} 次,种子 {nl['seed']}):中位 {_pct(nl['null_p50'])},"
                         f"90 分位 {_pct(nl['null_p90'])},最大 {_pct(nl['null_max'])};"
                         f"实际值的分位 = **{nl['percentile']:.3f}**"
                         f"({nl['frac_ge_actual'] * 100:.1f}% 的零分布抽样 ≥ 实际值)。")
        j = r["judge"]
        lines.append(f"- 判定 (i) 总收益 > HOLD 且 > TRIM:**{'✅' if j['i_total_return_gt_hold_and_trim'] else '❌'}**;"
                     f"(ii) 最大回撤不比 HOLD 深:**{'✅' if j['ii_maxdd_not_deeper_than_hold'] else '❌'}**;"
                     f"(iii) 随机对照 ≥ 90 分位:**{'✅' if j['iii_null_percentile_ge_90'] else '❌'}**;"
                     f"(iv) 多数轮次空头盈亏为正:**{'✅' if j['iv_majority_rounds_short_pnl_positive'] else '❌'}**"
                     f"({j['rounds_short_pnl_positive']}/{j['rounds_total']} 轮为正)。")
        lines.append("")
    if btc:
        lines.append("### 逐轮表(BTC;完整表见 `t335_rounds.csv`)")
        lines.append("")
        lines.append("| # | 进场日 | 出场日 | 出场原因 | 预算平仓 | 加空笔数 | 空头毛盈亏 | 资金费 | 成本 | "
                     "空头净盈亏 | 多头那一半 | B |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for k, rd in enumerate(btc["rounds"], 1):
            lines.append(
                f"| {k} | {rd['entry_d']} | {rd['exit_d']} | {rd['exit_reason']} | "
                f"{'是' if rd['budget_hit'] else '否'} | {rd['n_adds']} | "
                f"{rd['short_gross']:+.4f} | {rd['short_funding']:+.4f} | {rd['short_cost']:.4f} | "
                f"{rd['short_net']:+.4f} | {rd['long_gross']:+.4f} | {rd['budget']:.4f} |")
        lines.append("")
    lines.append("## 3. 诚实与边界")
    lines.append("")
    lines.append("- 轮次极少(见上表),汇总数的检出力很弱 —— **逐轮表比汇总数重要**;"
                 "任何一条判定都只是「在这一小段样本上没有反例」,不是「有效」。")
    lines.append("- 「多头买回到 1.0 = 全额换回 BTC」是本卡的读法(另一读法:买回原来数量、利润留现金不动)。")
    lines.append("- 随机对照把**整条过热区日程**循环平移;平移后 MA50 / 资金费 / MA200 的可用性"
                 "仍按原日期取(指标本身不重算),这是 S-811 写死的做法。")
    lines.append("- ETH 只报,不判定。")
    lines.append("")
    OUT_MD.write_text("\n".join(lines) + "\n")


def write_scenarios(results: dict) -> None:
    btc = results.get("BTC")
    if not btc:
        return
    p = CACHE / "perp_BTC.json"
    if not p.exists():
        return
    rows = json.loads(p.read_text())
    last_close = float(rows[-1]["c"])
    horizon = "2026-12-18"
    entries = [
        {"id": "T-335-1", "author": "lane-b",
         "scenario": "T-335 S-811 Jazz 的做空写法(过热区卖 50% 多头 + 用利润分批加空)",
         "statement": f"BTC 收盘在 {horizon} 高于本卡最后一次读数 {last_close:.2f} 的 5%(≈{last_close * 1.05:.0f})。",
         "variable": "close:BTC", "op": "gt", "lo": round(last_close * 1.05, 2), "hi": None,
         "prob": 0.55, "horizon_d": horizon,
         "basis": "本卡实测:BTC 从 2019-12 到现在,任意 30 个日历日内收盘涨超 5% 的比例约一半;"
                  "S-811 的入场在收盘、出场看 MA50,方向是双向的 —— 只给 0.55。"},
        {"id": "T-335-2", "author": "lane-b",
         "scenario": "T-335 S-811 Jazz 的做空写法(过热区卖 50% 多头 + 用利润分批加空)",
         "statement": f"BTC 收盘在 {horizon} 低于本卡最后一次读数 {last_close:.2f} 的 5%(≈{last_close * 0.95:.0f})。",
         "variable": "close:BTC", "op": "lt", "lo": None, "hi": round(last_close * 0.95, 2),
         "prob": 0.45, "horizon_d": horizon,
         "basis": "与 T-335-1 互补的两分:同样 ±5% 的带宽,不给方向性优势 —— 本卡样本里 "
                  "TRIM+SHORT 与 HOLD 的差距落在检出力不足的量级。"},
        {"id": "T-335-3", "author": "lane-b",
         "scenario": "T-335 S-811 Jazz 的做空写法(过热区卖 50% 多头 + 用利润分批加空)",
         "statement": "到 2026-12-18 为止没有出现新的 S-811 过热日(收盘/MA200 − 1 ≥ 扩张 90 分位 "
                      "且 资金费年化 7 日均 ≥ 扩张 85 分位)—— 人工结算:重跑 "
                      "docs/research/t335_trim_short.py,看 t335_results.json 里 BTC 的 overheat_run_starts。",
         "variable": "manual", "op": "gt", "lo": 0, "hi": None,
         "prob": 0.6, "horizon_d": horizon,
         "basis": "本卡实测:2026 年的过热日数量与最后一段的起止见 t335_results.json;"
                  "两个分位都要创新高,一个月内同时凑齐的概率低。"},
    ]
    OUT_SCEN.parent.mkdir(parents=True, exist_ok=True)
    OUT_SCEN.write_text(json.dumps({"author": "lane-b", "entries": entries},
                                   ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
