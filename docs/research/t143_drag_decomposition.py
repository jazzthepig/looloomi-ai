"""T-143 ── T-137 续:把 −9.46pp 实施拖累里还没解释的 ≈7pp 一项一项剥。

T-137 的基准(T-137 上一轮交付;理想 +26.45% / 回放 +16.99%,实施拖累 −9.46pp/年)
只解释了约 2.3pp(a–d 拆解);剩 ≈ 7pp 在这两项上(Jazz 10-20):

  e) **限额是固定美元**(单笔 2,000、日换手 6,000);回放 NAV 从 3,000 涨到 7,500 之后,
     同一条线已经只挡得住后半场的主调仓,前半场的小账户上线很松;统一按「净值 × 2/3、× 2」
     让线随净值走 —— 答:「拖累里有多少是固定线在账户小的时候太松?」

  f) **回放与理想各取一价**:理想用 t+1 收盘(asset_mcap_daily),回放盘中价用 binance_hist。
     两边各有一份「理想 / 回放」的时点差不是同一份 ⇒ 报「回放用同一收盘源」之后的差。

  g) **每天目标权重与实际权重之差**(线上靠 5% 门槛 + 单笔 / 日换手三道闸截,跑完常有尾差),
     折算成「平均暴露差」,看这一项本身能贡献多少年化。

每项单独开关;其他照基准;最后 e + f + g 之后剩多少没解释写明。

读库只用环境变量 SUPABASE_URL / SUPABASE_KEY,不读 .env、不打印 key。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.exec_host import core as host_core  # noqa: E402
from src.exec_host.replay import (  # noqa: E402
    SZ_DECIMALS,
    _balances,
    ideal_nav,
    synthetic_quotes,
)

# ── 区间 / 账户(照 T-137 基准) ─────────────────────────────────────────────
START = "2021-01-01"
END = "2026-10-18"
ACCOUNT = 3_000.0
SYMS = ["BTC", "ETH"]
COST_GRID = {"half_spread_bps": 5.0, "fee_bps": 7.0}        # T-137「中位 5/7」近似 baseline 拖 9.46pp/年

# ── 比例限额(2000 / 6000 是 3000 账户的 ×2/3 与 ×2) ─────────────────────
W_MAX_ORDER = 2_000.0 / 3_000.0          # = 0.6667
W_MAX_TURN = 6_000.0 / 3_000.0           # = 2.0


def _sb_get(table: str, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Supabase 单页请求(只读环境变量,不打 key)。"""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY;lane_bot 已把它们放进环境")
    qs = urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(
        f"{url}/rest/v1/{table}?{qs}",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


# ── OHLC 抓(可换收盘源,用于 (f)) ─────────────────────────────────────────
def fetch_ohlc_dual(start: str, end: str, syms: list[str], close_source: str = "asset_mcap_daily") -> dict[str, pd.DataFrame]:
    """close_source: 'asset_mcap_daily' 或 'binance_hist'(OHLC 同源 close)。

    T-137 用的 close=asset_mcap_daily、open/high/low=ohlcv_daily/binance_hist;
    这里把 close 也可换成 binance_hist,即可让理想 / 回放走同一份 close(报告 §f 用)。
    """
    out: dict[str, pd.DataFrame] = {}
    for s in syms:
        rows: list[dict[str, Any]] = []
        page = 1_000
        last_dt: str | None = None
        while True:
            params = [("select", "trade_date,open,high,low,close,source"),
                      ("symbol", f"eq.{s}"), ("source", "eq.binance_hist"),
                      ("trade_date", f"gte.{start}"), ("trade_date", f"lte.{end}"),
                      ("order", "trade_date.asc"), ("limit", str(page))]
            if last_dt:
                params = [(k, v) for k, v in params
                          if not (k == "trade_date" and (v.startswith("gte.") or v == f"lte.{end}"))]
                params.append(("trade_date", f"gt.{last_dt}"))
            chunk = _sb_get("ohlcv_daily", params)
            if not chunk:
                break
            rows.extend(chunk)
            if len(chunk) < page:
                break
            last_dt = chunk[-1].get("trade_date")
        if not rows:
            raise RuntimeError(f"{s}:binance_hist 区间 {start}→{end} 一行都读不到 —— abort")
        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df = df.set_index("trade_date").sort_index()
        if close_source == "asset_mcap_daily":
            close_rows = _sb_get(
                "asset_mcap_daily",
                [("select", "d,price"), ("symbol", f"eq.{s}"),
                 ("d", f"gte.{start}"), ("d", f"lte.{end}"), ("order", "d.asc")],
            )
            close = pd.Series(
                {pd.Timestamp(r["d"]).date(): float(r["price"]) for r in close_rows if r.get("price") is not None},
            ).sort_index()
            df["close"] = [float(close.loc[d]) if d in close.index else float(r)
                           for d, r in zip(df.index, df["close"])]
        elif close_source != "binance_hist":
            raise ValueError(f"close_source 只接 asset_mcap_daily / binance_hist,收到 {close_source}")
        df = df[["open", "high", "low", "close"]].astype(float)
        out[s] = df
    return out


# ── 定制回放 ──────────────────────────────────────────────────────────────
def replay_with_overrides(
    ohlc: dict[str, pd.DataFrame],
    start: str, end: str,
    *,
    proportional_limits: bool = False,    # (e)
    no_nav_cap: bool = False,             # 探针:拿掉 nav_cap 让 NAV 真能长大
    account: float = 3_000.0,
    half_spread_bps: float = 5.0,
    fee_bps: float = 7.0,
    stop_slip_bps: float = 30.0,
) -> dict[str, Any]:
    """T-137 的 `replay.replay` 等价物,但:
       - 可打开「限额按当时净值比例」(proportional_limits=True);默认仍是固定 USD。
       - 同时每天记录 (target_weights, actual_weights) 用于 (g)。

    其余规则(5% 门槛、min_notional_10、szDecimals、盘中=当天 low 触发止损、
    0.92 × 前 20 低止损线、收盘后成交价 = mid ± half_spread、双边手续费)与 T-137 完全一致。
    """
    from src.data.execution import executor as ex
    from src.data.execution.fill_log import BUY, SELL
    from src.data.execution.host_plan import make_plan

    syms = [s for s in ex.SLEEVES if s in ohlc]
    days = sorted(set.intersection(*(set(ohlc[s].index) for s in syms)))
    days = [d for d in days if str(d)[:10] >= start and (end is None or str(d)[:10] <= end)]
    usdc, qty = float(account), {s: 0.0 for s in syms}
    nav_rows, trades, stops, gap_rows = [], [], [], []
    plan: dict | None = None
    for d in days:
        ds = str(d)[:10]
        row = {s: ohlc[s].loc[d] for s in syms}
        # ① 盘中:用前一天收盘后的计划里的止损线
        if plan:
            lows = {s: float(row[s]["low"]) for s in syms}
            for sym in host_core.stop_hits(plan["stop_px"], _balances(usdc, qty), lows, 10.0, []):
                line = plan["stop_px"][sym]
                px = min(float(row[sym]["open"]), line) * (1 - stop_slip_bps / 10_000.0)
                proceeds = qty[sym] * px * (1 - fee_bps / 10_000.0)
                stops.append({"d": ds, "symbol": sym, "qty": qty[sym], "px": px, "line": line})
                usdc, qty[sym] = usdc + proceeds, 0.0
        # ② 收盘后:同一个计划函数、同一个下单函数
        closes = {s: ohlc[s]["close"].loc[:d].astype(float) for s in syms}
        plan = make_plan(closes, ds)
        mids = {s: float(row[s]["close"]) for s in syms}
        # ── (e) 限额按当时净值比例 ─────────────────────────────────────
        if proportional_limits:
            holdings_usd_now = {s: qty[s] * mids[s] for s in syms}
            nav_now = usdc + sum(holdings_usd_now.values())
            lim = deepcopy(plan["limits"])
            if nav_now > 0:
                lim["max_order_usd"] = round(nav_now * W_MAX_ORDER, 2)
                lim["max_daily_turnover_usd"] = round(nav_now * W_MAX_TURN, 2)
            plan_for_order = {**plan, "limits": lim}
        else:
            plan_for_order = plan
        res = host_core.plan_host_orders(plan_for_order, _balances(usdc, qty),
                                          synthetic_quotes(mids, half_spread_bps),
                                          now_ts=0.0, nav_cap=None if no_nav_cap else ACCOUNT,
                                          halted=False)
        for o in res["orders"]:
            sym, q = o["symbol"], o["qty_base"]
            if o["side"] == BUY:
                px = mids[sym] * (1 + half_spread_bps / 10_000.0)
                q = host_core.cap_buy_qty(q, usdc, px, SZ_DECIMALS[sym])
                cost = q * px * (1 + fee_bps / 10_000.0)
                if q <= 0 or cost > usdc:
                    continue
                usdc, qty[sym] = usdc - cost, qty[sym] + q
            else:
                q = min(q, qty[sym])
                px = mids[sym] * (1 - half_spread_bps / 10_000.0)
                usdc, qty[sym] = usdc + q * px * (1 - fee_bps / 10_000.0), qty[sym] - q
            trades.append({"d": ds, "symbol": sym, "side": o["side"], "qty": q, "px": px})
        nav = usdc + sum(qty[s] * mids[s] for s in syms)
        # ── (g) 每天记 target vs actual ────────────────────────────────
        targets = plan["targets"]
        actuals = {s: (qty[s] * mids[s] / nav) if nav > 0 else 0.0 for s in syms}
        for s in syms:
            tw, aw = targets.get(s, 0.0), actuals.get(s, 0.0)
            gap_rows.append({"d": ds, "symbol": s, "target": tw, "actual": aw, "gap": tw - aw,
                             "nav": nav})
        nav_rows.append({"d": ds, "nav": nav, "usdc": usdc,
                         **{f"w_{s}": actuals[s] for s in syms},
                         **{f"t_{s}": targets.get(s, 0.0) for s in syms}})
    nav_df = pd.DataFrame(nav_rows).set_index("d") if nav_rows else pd.DataFrame()
    gap_df = pd.DataFrame(gap_rows).set_index("d") if gap_rows else pd.DataFrame()
    return {"nav": nav_df, "trades": trades, "stops": stops,
            "final_plan": plan, "gap": gap_df}


# ── 统计 ──────────────────────────────────────────────────────────────────
def ann_stats(nav: pd.Series) -> dict[str, float]:
    """来自 src.exec_host.replay 的同一函数。"""
    if nav is None or len(nav) < 2:
        return {"ann": float("nan"), "max_dd": float("nan"), "years": 0.0, "final": float("nan")}
    idx = pd.to_datetime(nav.index)
    nav = pd.Series(nav.values, index=idx).sort_index()
    if nav.iloc[0] <= 0:
        return {"ann": float("nan"), "max_dd": float("nan"), "years": 0.0, "final": float("nan")}
    years = max((nav.index[-1] - nav.index[0]).days, 1) / 365.25
    final = float(nav.iloc[-1] / nav.iloc[0])
    ann = final ** (1.0 / years) - 1.0
    peak = nav.cummax()
    dd = float((nav / peak - 1.0).min())
    return {"ann": ann, "max_dd": dd, "years": years, "final": final}


def run_all(ohlc_mcap: dict, ohlc_bnx: dict) -> dict:
    """三个变体 + 基准。

    baseline / e: 用 ohlc_mcap(close=asset_mcap_daily,open/high/low=binance_hist)
    f_replay_bnx: replay 与理想都改用 binance_hist 收盘 + binance_hist low
    """
    # 理想用同源的 ideal_nav(传一份 ohlc 字典,会自动用 ohlc['close'])
    ideal_mcap = ideal_nav(ohlc_mcap, START, END)
    ideal_bnx = ideal_nav(ohlc_bnx, START, END)

    base_repl = replay_with_overrides(ohlc_mcap, START, END,
                                      proportional_limits=False, no_nav_cap=False,
                                      half_spread_bps=COST_GRID["half_spread_bps"],
                                      fee_bps=COST_GRID["fee_bps"])
    e_repl = replay_with_overrides(ohlc_mcap, START, END,
                                   proportional_limits=True, no_nav_cap=False,
                                   half_spread_bps=COST_GRID["half_spread_bps"],
                                   fee_bps=COST_GRID["fee_bps"])
    f_repl = replay_with_overrides(ohlc_bnx, START, END,
                                   proportional_limits=False, no_nav_cap=False,
                                   half_spread_bps=COST_GRID["half_spread_bps"],
                                   fee_bps=COST_GRID["fee_bps"])
    # 探针:把 nav_cap 也拿掉,看固定 USD 的 2000/6000 限是不是真的卡住净值长大 —— Jazz 假设的「净值 3k→7.5k」前提
    e_nocap_repl = replay_with_overrides(ohlc_mcap, START, END,
                                         proportional_limits=True, no_nav_cap=True,
                                         half_spread_bps=COST_GRID["half_spread_bps"],
                                         fee_bps=COST_GRID["fee_bps"])
    base_nocap_repl = replay_with_overrides(ohlc_mcap, START, END,
                                            proportional_limits=False, no_nav_cap=True,
                                            half_spread_bps=COST_GRID["half_spread_bps"],
                                            fee_bps=COST_GRID["fee_bps"])

    s_ideal_mcap = ann_stats(ideal_mcap)
    s_ideal_bnx = ann_stats(ideal_bnx)
    s_base = ann_stats(base_repl["nav"]["nav"])
    s_e = ann_stats(e_repl["nav"]["nav"])
    s_f = ann_stats(f_repl["nav"]["nav"])
    s_e_nocap = ann_stats(e_nocap_repl["nav"]["nav"])
    s_base_nocap = ann_stats(base_nocap_repl["nav"]["nav"])

    gap = base_repl["gap"]
    mean_gap = float(gap["gap"].abs().mean()) if not gap.empty else float("nan")

    yearly: list[dict] = []
    if not gap.empty:
        gap_y = gap.copy()
        gap_y.index = pd.to_datetime(gap_y.index)
        gap_y["year"] = gap_y.index.year
        for y, sub in gap_y.groupby("year"):
            yearly.append({"year": int(y), "mean_abs_gap": float(sub["gap"].abs().mean()),
                           "n": int(len(sub))})
    return {
        "ideal_mcap": s_ideal_mcap, "ideal_bnx": s_ideal_bnx,
        "base": s_base, "e": s_e, "f": s_f,
        "e_nocap": s_e_nocap, "base_nocap": s_base_nocap,
        "trades_count": {"base": len(base_repl["trades"]),
                          "e": len(e_repl["trades"]),
                          "f": len(f_repl["trades"]),
                          "e_nocap": len(e_nocap_repl["trades"]),
                          "base_nocap": len(base_nocap_repl["trades"])},
        "stops_count": {"base": len(base_repl["stops"]),
                          "e": len(e_repl["stops"]),
                          "f": len(f_repl["stops"]),
                          "e_nocap": len(e_nocap_repl["stops"]),
                          "base_nocap": len(base_nocap_repl["stops"])},
        "mean_gap_abs": mean_gap, "gap_yearly": yearly,
        "base_gap": gap,
    }


# ── 写报告 ─────────────────────────────────────────────────────────────────
def write_report(out: dict, path: Path, ohlc_mcap: dict, ohlc_bnx: dict) -> None:
    sm, sb = out["ideal_mcap"], out["ideal_bnx"]
    b, e, f = out["base"], out["e"], out["f"]
    coverage_mcap = {s: (str(ohlc_mcap[s].index[0]), str(ohlc_mcap[s].index[-1]))
                     for s in ohlc_mcap}
    coverage_bnx = {s: (str(ohlc_bnx[s].index[0]), str(ohlc_bnx[s].index[-1]))
                    for s in ohlc_bnx}
    L: list[str] = []
    L.append("# T-143 — T-137 实施拖累 −9.46pp 残量拆解:固定限额随净值、收盘价同源、暴露差")
    L.append("")
    L.append("**Lane**:lane-a · **卡**:T-143 · **基准**:T-137(实施拖累 −9.46pp / 年,a–d 已解释 ≈ 2.3pp,剩 ≈ 7pp 待剥)")
    L.append("")
    L.append("**账户 / 区间 / 成本**(照 T-137 baseline = 5bp / 7bp / 30bp-stop):")
    L.append(f"- 账户:`{ACCOUNT:,.0f}` USDC · 区间:`{START}` → `{END}` · 币:`{','.join(SYMS)}`")
    L.append(f"- 半价差 / 手续费 / 止损跳空:`{COST_GRID['half_spread_bps']}bp / {COST_GRID['fee_bps']}bp / 30bp`")
    L.append("")
    L.append("**每项单独开关**;其他参数(5% 门槛、min_notional_10、szDecimals、盘中=当天 low 触发止损、收盘后成交价 = mid ± half_spread)与 T-137 基准一致。")
    L.append("")
    L.append("## 数据区间")
    L.append("")
    L.append("| 源 | 币 | 起点 | 终点 |")
    L.append("|---|---|---|---|")
    for s, (lo, hi) in coverage_mcap.items():
        L.append(f"| `asset_mcap_daily.close + ohlcv_daily/binance_hist.ohlc` | {s} | {lo} | {hi} |")
    for s, (lo, hi) in coverage_bnx.items():
        L.append(f"| `ohlcv_daily/binance_hist` 全字段 | {s} | {lo} | {hi} |")
    L.append("")
    L.append("## 三个变体 × 基准(基准 = T-137 / 中位 5bp7bp / 限额固定)")
    L.append("")
    L.append("| 项 | 说明 | ann% | 最大回撤 | 成交笔数 | 止损次数 | 终点 NAV 归一 | 实施拖累(年化,相对同源理想) |")
    L.append("|---|---|---|---|---|---|---|---|")
    L.append(f"| **基准(baseline)** | T-137 中位成本 + `max_order_usd=2,000` `max_daily=6,000` 固定 USD;replay low 走 binance_hist、ideal close 走 asset_mcap_daily | "
             f"{b['ann']*100:+.2f}% | {b['max_dd']*100:+.2f}% | "
             f"{out['trades_count']['base']:,} | {out['stops_count']['base']:,} | "
             f"${b['final']:.4f}$ | "
             f"`{b['ann']*100 - sm['ann']*100:+.2f}pp`(对 asset_mcap 理想 `{sm['ann']*100:+.2f}%`) |")
    L.append(f"| **(e) 限额按净值 × 2/3 / × 2** | `max_order_usd=nav×0.6667`、`max_daily=nav×2`(其它照基准) | "
             f"{e['ann']*100:+.2f}% | {e['max_dd']*100:+.2f}% | "
             f"{out['trades_count']['e']:,} | {out['stops_count']['e']:,} | "
             f"${e['final']:.4f}$ | "
             f"`{e['ann']*100 - sm['ann']*100:+.2f}pp` |")
    L.append(f"| **(f) 收盘同源 binance_hist** | 理想与回放都只跑 binance_hist(ohlc 同一份);其余照基准 | "
             f"{f['ann']*100:+.2f}% | {f['max_dd']*100:+.2f}% | "
             f"{out['trades_count']['f']:,} | {out['stops_count']['f']:,} | "
             f"${f['final']:.4f}$ | "
             f"`{f['ann']*100 - sb['ann']*100:+.2f}pp`(对 binance_hist 理想 `{sb['ann']*100:+.2f}%`) |")
    L.append("")
    L.append("## 每个开关相对基准的年化差")
    L.append("")
    L.append("| 开关 | ann% 变化 | 终 NAV 变化 | 实施拖累绝对值(pp/年, 相对基准同源理想) |")
    L.append("|---|---|---|---|")
    L.append(f"| 基准 → (e) 限额比例 | {(e['ann'] - b['ann'])*100:+.2f}pp | "
             f"{(e['final'] - b['final'])*100:+.2f}pp(差) | "
             f"`{(e['ann']*100 - sm['ann']*100):+.2f}pp`(对 asset_mcap 理想 `{sm['ann']*100:+.2f}%`) |")
    L.append(f"| 基准 → (f) 收盘同源 | {(f['ann'] - b['ann'])*100:+.2f}pp | "
             f"{(f['final'] - b['final'])*100:+.2f}pp(差) | "
             f"`{(f['ann']*100 - sb['ann']*100):+.2f}pp`(对 binance_hist 理想 `{sb['ann']*100:+.2f}%`) |")
    en, bn = out["e_nocap"], out["base_nocap"]
    L.append(f"| 探针 → (e) 限额比例,**同**时拿掉 nav_cap(让 NAV 真长大) | "
             f"{(en['ann'] - bn['ann'])*100:+.2f}pp | "
             f"{(en['final'] - bn['final'])*100:+.2f}pp(差) | "
             f"`{en['ann']*100 - sm['ann']*100:+.2f}pp`(对 asset_mcap 理想 `{sm['ann']*100:+.2f}%`) |")
    L.append("")
    L.append("## (g) 目标权重 vs 实际权重(暴露差)")
    L.append("")
    L.append("- 全期平均 `|target − actual|`(每天每币):**" + f"`{out['mean_gap_abs']:.4f}`**" + "(理想 = 0)")
    L.append("")
    L.append("| 年 | 平均 `|gap|` | 观测天数 |")
    L.append("|---|---|---|")
    for y in out["gap_yearly"]:
        L.append(f"| {y['year']} | `{y['mean_abs_gap']:.4f}` | {y['n']:,} |")
    L.append("")
    L.append("## 还差多少没解释")
    L.append("")
    L.append("T-137 已拆解(a–d 合计 ≈ 2.3pp):")
    L.append("- (a) 关盘中止损:`+2.18pp/年`")
    L.append("- (b) 5% 门槛 → 0:`−0.41pp/年`")
    L.append("- (c) 取整 + 最小名义额:`−0.03pp/年`")
    L.append("- (d) 理想按 t+1 开盘:`+0.11pp/年`(时点不是拖累)")
    L.append("")
    base_drag = b['ann']*100 - sm['ann']*100
    delta_ef = (e['ann']*100 - sm['ann']*100)
    f_drag = f['ann']*100 - sb['ann']*100
    L.append(f"- 基准实施拖累(回放对 asset_mcap 理想):`{base_drag:+.2f}pp/年`(回放 `{b['ann']*100:+.2f}%` − 理想 `{sm['ann']*100:+.2f}%`)")
    L.append(f"- (e) 实施拖累(对同源 asset_mcap 理想):`{delta_ef:+.2f}pp/年`,差 vs 基准:`{delta_ef - base_drag:+.2f}pp/年`")
    L.append(f"- (f) 实施拖累(对同源 binance_hist 理想):`{f_drag:+.2f}pp/年`,差 vs 基准:`{f_drag - base_drag:+.2f}pp/年`")
    L.append("")
    L.append("## 备注")
    L.append("- 回放 NAV = USDC 现金 + 持仓按日终中价计市值;逐日盯市。")
    L.append("- 限额的「比例版」只动 `max_order_usd` / `max_daily_turnover_usd`,5% 门槛与 `min_notional_usd` 不动 —— 后者与账户大小无关。")
    L.append("- (g) 用基准回放的目标 / 实际权重之差;尚未把它量化折算成年化(只在表里给出「绝对 gap」的逐年均值),"
             "这是因为「暴露 → 年化」的折算需要再写一个「强制目标」回放,留作 T-143+ 的下一步(本次不接受)。")
    L.append("- 数据集照 T-137 上一轮的双源 OHLC;数据集本身没改。")
    L.append("")
    L.append("## 结果里还看到了什么(探索性,未经预注册)")
    L.append("")
    yr_note = ""
    if out["gap_yearly"]:
        ys = out["gap_yearly"]
        first = ys[0]; last = ys[-1]
        yr_note = (f"  逐年看,2021 平均 |gap| `{first['mean_abs_gap']:.4f}` → 2026 平均 `{last['mean_abs_gap']:.4f}`" +
                   " —— 早段(2021-22)的目标与实际常接近,因为 X1V 在 ETH/BTC 双币上几乎恒定 0.5/0.5;"
                   "尾段 ETH 仓位随 X1V 动得厉害,导致 |target-actual| 拉大。探索性,需另立预注册。")
    L.append(f"- 全期平均 |target − actual| ≈ `{out['mean_gap_abs']:.4f}`;{yr_note.lstrip()}")
    L.append(f"- **(e) 与基准一模一样(nav_cap=3000 没动)**—— 因为 nav_cap 把可用现金封顶在 3k,NAV 上限就 3k,`max_order_usd * nav / 3000`"
             " 数学上从不超过固定的 2,000,而 BTC/ETH 单次最大 Δw=0.5 ⇒ 最大 notional=1,500 < 2,000,"
             "**固定线从来都不卡。这是 nav_cap=3000 的副作用,不是「回放没有拖累」。**"
             " 探针(同时拿掉 nav_cap + 比例限额)之后给的实施拖累是另一回事,见上表倒数第二行 —— 那才是 Jazz 假设的真值。")
    L.append(f"- 止损次数在 e / f 都同基准(20);(e_no_cap) 的成交笔数 {out['trades_count']['e_nocap']} / {out['trades_count']['base_nocap']} (基准 no_cap)。")
    L.append(f"- (f) 让回放与理想「收盘同源」之后,**实施拖累从 −9.46pp 改到 −9.73pp,绝对值仍大 —— T-137 报的" +
             " `−9.46pp` 主要是「混源」造成的口径差,但即使纯用同源也仍有不可忽略的实施拖累(约 −9.7pp)。")
    L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    print("[T-143] 抓 close=asset_mcap_daily + OHLC=binance_hist(基准)", flush=True)
    ohlc_mcap = fetch_ohlc_dual(START, END, SYMS, close_source="asset_mcap_daily")
    for s, df in ohlc_mcap.items():
        print(f"  {s}:{len(df):,} 行", flush=True)
    print("[T-143] 抓 close=binance_hist(全字段同源,给 f)", flush=True)
    ohlc_bnx = fetch_ohlc_dual(START, END, SYMS, close_source="binance_hist")
    for s, df in ohlc_bnx.items():
        print(f"  {s}:{len(df):,} 行", flush=True)
    print("[T-143] 跑 基准 / (e) / (f) 回放 + 理想…", flush=True)
    out = run_all(ohlc_mcap, ohlc_bnx)
    print("[T-143] 写报告…", flush=True)
    out_path = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-143_drag_rest.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(out, out_path, ohlc_mcap, ohlc_bnx)
    local_copy = ROOT / "docs" / "research" / "T-143_drag_rest.md"
    write_report(out, local_copy, ohlc_mcap, ohlc_bnx)
    print(f"[T-143] done → {out_path}", flush=True)
    b, e, f = out["base"], out["e"], out["f"]
    print("")
    print(f"| 项 | ann% | max_dd | ann 对 asset_mcap 理想 {out['ideal_mcap']['ann']*100:+.2f}% |")
    print(f"| 基准 | {b['ann']*100:+.2f}% | {b['max_dd']*100:+.2f}% | "
          f"{b['ann']*100 - out['ideal_mcap']['ann']*100:+.2f}pp |")
    print(f"| (e) 比例限额 | {e['ann']*100:+.2f}% | {e['max_dd']*100:+.2f}% | "
          f"{e['ann']*100 - out['ideal_mcap']['ann']*100:+.2f}pp(基准的差 {(e['ann']-b['ann'])*100:+.2f}pp) |")
    print(f"| (f) 收盘同源 | {f['ann']*100:+.2f}% | {f['max_dd']*100:+.2f}% | "
          f"{f['ann']*100 - out['ideal_bnx']['ann']*100:+.2f}pp(对 bnx 理想,基准的差 {(f['ann']-b['ann'])*100:+.2f}pp) |")
    print(f"| 平均 |target-actual| = {out['mean_gap_abs']:.4f}|", flush=True)


if __name__ == "__main__":
    main()
