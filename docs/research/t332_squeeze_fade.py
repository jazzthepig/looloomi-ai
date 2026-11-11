"""T-332 —— S-808 有止损的反向空票:squeeze 之后做空该币永续(裸空为主、对冲 BTC 只报)。

用法:
    python3 docs/research/t332_squeeze_fade.py fetch   # 只抓数落缓存(慢,建议 nohup 后台)
    python3 docs/research/t332_squeeze_fade.py all     # 自检 + 主跑 + 判据 + 产物

产物:
    docs/research/T-332_squeeze_fade.md       报告(S-808 原文照抄开头)
    docs/research/t332_results.json            全部数字
    docs/research/t332_tickets.csv             逐票表
    docs/research/scenarios/lane-a-T-332.json  前向命题(≥3 条,≥1 条 close: 自动结算)

数据:只读 Supabase(perp_bv_daily / v_funding_daily / crowding_watch / cycle_vector_daily)
      + T-229 的 DVOL 缓存。缓存目录 /Volumes/CometCloudAI/cometcloud-local/research/t332。
纪律:不改代码、不做 DDL、不入库;零分布 / 盈亏 / 随机对照只用 src/data/evaluation/apparatus.py。
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    ab_test,
    null_distribution,
    percentile_of,
    random_dates_like,
)

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t332")
T256_CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t256")
DVOL_CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/_cache/t229")

COST_BPS = 7.5            # 每次开 / 关 7.5bp(S-808 写死)
STOP_ATR = 1.5            # 止损 = 进场价 + 1.5 × ATR14(d)
TP_ATR = 2.5              # 止盈 = 进场价 − 2.5 × ATR14(d)  ⇒ 目标 +1.67R
TIME_STOP_MAIN = 20       # S-808 写死:时间止损 20 根(S-736 是 15)
TIME_STOP_S736 = 15       # S-736 复现用
RISK_PCT = 0.005          # 每票风险 0.5% 净值
MAX_NOTIONAL = 0.50       # 名义 ≤ 净值 50%
COOLDOWN_D = 10           # 同一币 10 天内不叠加(S-808 写死)
# 数据卫生(不是策略改动):ATR14/进场价 落在带外 ⇒ 该合约当期价格序列无意义(死票 / 换币断档),
# R 单位会炸成 1e10 量级。**实际侧与随机对照侧共用同一把尺**,两边丢多少都报。
MIN_ATR_FRAC = 0.005      # ATR14/进场价 < 0.5% ⇒ 票作废
MAX_ATR_FRAC = 1.0        # ATR14/进场价 > 100% ⇒ 票作废
DROPS: list[tuple] = []   # 被作废的进场点:(sym, d, atr, entry)
SEED = 808
N_NULL = 1000
ATR_N = 14
MA_N = 20
PERIODS = [("2020-21", (2020, 2021)), ("2022", (2022, 2022)),
           ("2023-24", (2023, 2024)), ("2025-26", (2025, 2026))]

# S-736 结果(lane-a T-256,2026-11-06)—— 自检要复现的数
S736_TRUTH = {
    "n_tickets": 18, "avg_r_net": -0.3744908562608685, "avg_r_price": -0.36693511344173546,
    "median_r_net": -0.9841310251507414, "win_rate": 0.2222222222222222,
    "total_r_net": -6.740835412695633,
    "reasons": {"止盈": 2, "保本": 2, "止损": 10, "时间": 4},
    "p_b_le_a": 0.7725,
}

PREREG_808 = """## S-808 — 有止损的反向空票:被挤空头的币(S-781 squeeze)之后中位跑输 16%、但均值只有 −1%(右尾把它拉回)—— 一张带止损的空票能不能把「典型的跌」吃下来、把「右尾的涨」截掉 —— 预注册(Seth,2026-11-11 00:30 UTC;Jazz 11-11「崩盘前观察情绪反向指标做空,抓短期机会;只要市场有波动就有机会」;squeeze 事件从没被当成**带止损的空票**算过;交 A 道 T-332)
**为什么。** 对手盘族里最强、最干净的一条是 squeeze(S-781:351 个干净事件,30 天相对篮子中位 −16.4%、为负 74%、随机对照分位 0.000),但它进不了任何规则,因为右尾(+100% 以上的几次)把均值拉回到 −1.0%。空单的止损恰好截右尾 —— 这正是「有波动就有机会」的可执行写法:不预测崩盘,只在**散户被迫追涨之后**站到反面,错了就小亏走人。
**写死。** 事件 = `crowding_watch` kind = squeeze(全部 cohort,`crowding_events()` 内核);票 = 该币 USDT 永续(`perp_bv_daily`),**d + 1 开盘进空**;止损 = 进场 + 1.5 × ATR14(d);止盈 = 进场 − 2.5 × ATR14;浮盈达 +1R 后止损移到进场价;时间止损 20 根;同一根 bar 先碰止损;成本 7.5bp × 2;资金费按持有期实计(空方收正费率,`v_funding_daily`)。票的机械**与 S-736 的 `t256_tactical_short.py` 一字相同**,只换进场事件与标的。同一币 10 天内不叠加(事件本身已去重)。
**两版:** 主 = 裸空;副(只报)= 空该币 + 等名义多 BTC(对冲 β)。
**判(主版,全过才 ✅):** (a) 票数 ≥ 60;(b) 平均 R > 0 且 `apparatus.ab_test` 对 0 p < 0.05;(c) 随机对照:**同币同年**随机进场日(`apparatus.random_dates_like`,1,000 次,种子 808,同样的票机械),实际平均 R ≥ 对照 95 分位;(d) **对 |R| 最大的一张留一,(b) 仍成立**(S-796 教训);(e) 逐期(2020–21 / 2022 / 2023–24 / 2025–26)报,任一期平均 R < −0.3 ⇒ ❌;最长连亏、最差单票(跳空穿止损)照报。
**后果:** 全过 ⇒ 开纸面臂 `short_squeeze_fade`(不动钱;动钱由 Jazz 定,且只在 HL 有该永续时可执行);不过 ⇒ squeeze 仍只留在 `crowd_map`。**试验计数:+1(做空族)。**"""

REPORT_HEADER = PREREG_808 + """

## T-332 —— 执行记录(lane-a,2026-11-11)

**票机械(逐字照抄 t256_tactical_short.py 的 `simulate()`,只换事件与标的):**
d+1 开盘进空 · 止损 = 进场 + 1.5×ATR14(d) · 止盈 = 进场 − 2.5×ATR14(⇒ 目标 +1.67R) ·
浮盈 +1R 后止损移到进场价(保本) · 同一根 bar 先碰止损 · 时间止损 20 根 ·
成本 7.5bp × 2 · 资金费按持有期实计(空方收正费率) · 同一币 10 天内不叠加 ·
名义 ≤ 净值 50%、每票风险 0.5% 净值。

**数据(只读,不入库):** 事件 = `crowding_watch` kind=squeeze(351 个 / 240 合约,
2020-08-08 → 2026-10-30);价格 `perp_bv_daily`;资金费 `v_funding_daily`;
随机对照 = `apparatus.random_dates_like`(同币同年随机进场日,1000 次,种子 808,同一套票机械)。

**自检:** 用同一套票机械复现 S-736(t256)的 18 张票、平均净 R −0.3745 —— 一致才算数。

**数据卫生(两侧同一把尺):** ATR14/进场价 落在 [0.5%, 100%] 之外的进场点作废
(死票 / 换币断档会让 R 单位炸成 1e10 量级)。实际侧与随机对照侧丢多少都照报。

全部数字见 `t332_results.json`,逐票表见 `t332_tickets.csv`。

---
"""

PREREG_736 = """## S-736 — 战术空单:流动性变差 + 不确定性升高时才开,到目标就撤、浮盈后保本 —— 预注册(Seth,2026-11-06 03:47 UTC)
**触发(d 日收盘,全部按时点可知,三条同时满足):** ① 流动性变差:⓪ `phase = turning`,或 `deterioration` ≤ 截至 d 的扩张 20 分位(≥ 250 个观测);② 不确定性:BTC DVOL 一年分位 ≥ 0.70(`dvol_btc_pct_1y`);③ 价格确认:BTC 永续收盘 < 20 日均线。已有一张票在场 ⇒ 不叠加。
**票(BTCUSDT 永续):** d+1 开盘进空;止损 = 进场价 + 1.5 × ATR14(d);止盈 = 进场价 − 2.5 × ATR14;浮盈达 +1R 后止损移到进场价(保本);时间止损 15 根;同一根 bar 既碰止损又碰止盈 ⇒ 按止损算(保守)。成本 7.5bp × 2,资金费按持有期实计(空方收正费率)。"""


# ───────────────────────────── 抓数 ─────────────────────────────
def pull(table: str, query: str, step: int = 1000) -> list[dict]:
    """分页取表。每页 ≤1000 行;query 必须自带 order=(按主键),否则翻页边界会漂。"""
    rows: list[dict] = []
    off, total = 0, -1
    while True:
        h = dict(H)
        h["Range"] = f"{off}-{off + step - 1}"
        req = urllib.request.Request(f"{U}/rest/v1/{table}?{query}", headers=h)
        with urllib.request.urlopen(req, timeout=300) as resp:
            cr = resp.headers.get("Content-Range", "")
            body = json.loads(resp.read())
        rows.extend(body)
        if "/" in cr:
            total = int(cr.split("/")[-1])
        off += len(body)
        if not body or total < 0 or off >= total:
            break
    return rows


def cached(name: str, fn) -> list[dict]:
    p = CACHE / f"{name}.json"
    if p.exists():
        rows = json.loads(p.read_text())
        print(f"  cache {name}: {len(rows)} rows", flush=True)
        return rows
    rows = fn()
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows))
    print(f"  pulled {name}: {len(rows)} rows", flush=True)
    return rows


def pull_symbols(table: str, select: str, syms: list[str], chunk: int = 40) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(syms), chunk):
        part = syms[i:i + chunk]
        q = f"select={select}&symbol=in.({','.join(part)})&order=symbol.asc,d.asc"
        out.extend(pull(table, q))
    return out


# ───────────────────────────── 面板与票 ─────────────────────────────
def wilder_atr(h, l, c) -> list[float]:
    """ATR14(d) = Wilder RMA(TR),种子 = mean(TR[1:15])(t256 第 224–228 行,一字照抄)。"""
    n = len(c)
    tr = [0.0] * n
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = [float("nan")] * n
    if n > ATR_N:
        atr[ATR_N] = float(np.mean(tr[1:ATR_N + 1]))
        for i in range(ATR_N + 1, n):
            atr[i] = (atr[i - 1] * (ATR_N - 1) + tr[i]) / ATR_N
    return atr


def build_panel(rows: list[dict], fund_rows: list[dict]) -> dict:
    """一个合约的日线面板:日期 / 开高低收 / ATR14 / 日资金费。"""
    by_d: dict[str, dict] = {}
    for r in rows:
        if any(r.get(k) is None for k in ("o", "h", "l", "c")):
            continue
        by_d[str(r["d"])[:10]] = r           # 同日多条 → 保留最后一条(按 order 排序)
    ds = sorted(by_d)
    o = [float(by_d[d]["o"]) for d in ds]
    h = [float(by_d[d]["h"]) for d in ds]
    l = [float(by_d[d]["l"]) for d in ds]
    c = [float(by_d[d]["c"]) for d in ds]
    fund: dict[str, float] = defaultdict(float)
    for r in fund_rows:
        n = int(r.get("n") or 1)
        fund[str(r["d"])[:10]] += float(r["funding_rate"]) * n
    return {"dates": ds, "idx": {d: i for i, d in enumerate(ds)}, "o": o, "h": h, "l": l, "c": c,
            "atr": wilder_atr(h, l, c), "fund": dict(fund), "n": len(ds)}


def simulate(pan: dict, d: str, tp_atr: float = TP_ATR, time_stop: int = TIME_STOP_MAIN) -> dict | None:
    """在信号日 d 开一张空票(t256 `simulate()` 逐字照抄,只把面板参数化)。"""
    idx = pan["idx"]
    dates = pan["dates"]
    n = pan["n"]
    i = idx.get(d)
    if i is None or i + 1 >= n:
        return None
    a = pan["atr"][i]
    if math.isnan(a) or a <= 0:
        return None
    j = i + 1
    entry = pan["o"][j]
    r_unit = STOP_ATR * a
    stop0 = entry + r_unit
    target = entry - tp_atr * a
    be_trigger = entry - r_unit          # +1R
    stop = stop0
    exit_i = exit_px = None
    reason = ""
    for k in range(time_stop):
        b = j + k
        if b >= n:
            break
        o, h, l = pan["o"][b], pan["h"][b], pan["l"][b]
        if o >= stop:                       # 跳空穿止损 ⇒ 按开盘价
            exit_i, exit_px, reason = b, o, ("保本" if stop == entry else "止损")
            break
        if o <= target:                    # 跳空越过止盈 ⇒ 按开盘价
            exit_i, exit_px, reason = b, o, "止盈"
            break
        if h >= stop:
            exit_i, exit_px, reason = b, stop, ("保本" if stop == entry else "止损")
            break
        if l <= target:
            exit_i, exit_px, reason = b, target, "止盈"
            break
        if l <= be_trigger:                # 浮盈到 +1R ⇒ 止损移到进场价
            if h >= entry:                 # 同一根 bar 回到进场价 ⇒ 保守按保本出场
                exit_i, exit_px, reason = b, entry, "保本"
                break
            stop = entry
    truncated = False
    if exit_i is None:
        b = min(j + time_stop - 1, n - 1)
        exit_i, exit_px, reason = b, pan["c"][b], "时间"
        truncated = b < j + time_stop - 1
    hold_days = exit_i - j + 1
    fd = dates[j:exit_i + 1]
    fund = float(sum(pan["fund"].get(x, 0.0) for x in fd))
    r_px = (entry - exit_px) / r_unit
    r_fund = fund * entry / r_unit
    r_cost = 2.0 * (COST_BPS / 1e4) * entry / r_unit
    return {"signal_d": d, "entry_d": dates[j], "exit_d": dates[exit_i],
            "entry": entry, "exit": exit_px, "atr14_d": a, "r_unit": r_unit,
            "stop": stop0, "target": target, "reason": reason, "hold_days": hold_days,
            "funding_sum": fund, "r_price": r_px, "r_fund": r_fund, "r_cost": r_cost,
            "r_net": r_px + r_fund - r_cost, "truncated": truncated,
            "_fund": pan["fund"], "_fd": fd}


def d_days(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def run_tickets(events: list[tuple[str, str]], panels: dict[str, dict], time_stop: int,
                tp_atr: float = TP_ATR, global_single: bool = False) -> tuple[list[dict], int]:
    """事件 → 票。同一币 10 天内不叠加(S-808);global_single=True 时另加「全局同时只一张票」(t256 原口径,只作副)。"""
    out: list[dict] = []
    last_entry: dict[str, str] = {}
    open_until = ""
    skipped = 0
    for sym, d in events:
        pan = panels.get(sym)
        if pan is None:
            continue
        i = pan["idx"].get(d)
        if i is None or i + 1 >= pan["n"]:
            continue
        entry_d = pan["dates"][i + 1]
        a_px = pan["atr"][i]
        e_px = pan["o"][i + 1]
        if (not math.isfinite(a_px) or a_px <= 0 or not math.isfinite(e_px) or e_px <= 0
                or a_px / e_px < MIN_ATR_FRAC or a_px / e_px > MAX_ATR_FRAC):
            DROPS.append((sym, d, a_px, e_px))
            continue
        if global_single:
            if entry_d <= open_until:
                skipped += 1
                continue
        else:
            prev = last_entry.get(sym)
            if prev is not None and d_days(prev, entry_d) <= COOLDOWN_D:
                skipped += 1
                continue
        t = simulate(pan, d, tp_atr=tp_atr, time_stop=time_stop)
        if t is None:
            continue
        t["symbol"] = sym
        t["_key"] = (sym, d)
        out.append(t)
        last_entry[sym] = entry_d
        if global_single:
            open_until = t["exit_d"]
    return out, skipped


# ───────────────────────────── 袖套 NAV(多票并发) ─────────────────────────────
def sleeve_nav(tks: list[dict], panels: dict[str, dict], days: list[str],
               btc_pan: dict | None = None) -> tuple[list[str], np.ndarray, dict]:
    """每票风险 0.5% 净值(进场当时),名义 ≤ 净值 50%。允许多票并发(S-808 只限「同一币 10 天内」)。"""
    cash = 1.0
    open_pos: dict[tuple, dict] = {}
    nav: list[float] = []
    detail: dict[str, dict] = {}
    btc_cum = 0.0
    btc_curve: list[float] = []
    by_entry: dict[str, list[dict]] = defaultdict(list)
    for t in tks:
        by_entry[t["entry_d"]].append(t)
    for d in days:
        for key, t in list(open_pos.items()):
            if t["exit_d"] == d:
                pnl = t["notional"] * (t["entry"] - t["exit"]) / t["entry"]
                fund_cash = t["notional"] * sum(t["_fund"].get(x, 0.0) for x in t["_fd"])
                cash += pnl + fund_cash - t["notional"] * (COST_BPS / 1e4)
                open_pos.pop(key)
        for t in by_entry.get(d, []):
            notional = min(RISK_PCT * cash / (t["r_unit"] / t["entry"]), MAX_NOTIONAL * cash)
            t["notional"] = notional
            cash -= notional * (COST_BPS / 1e4)
            t["_fund_acc"] = 0.0
            if t["exit_d"] <= d:
                # 同日进出(hold_days == 1):出场价在进场那根 bar 就定下了,直接结算,
                # 否则这张票永远不会被出场循环关掉,变成一路盯到样本末的「幽灵仓位」。
                pnl = t["notional"] * (t["entry"] - t["exit"]) / t["entry"]
                fund_cash = t["notional"] * sum(t["_fund"].get(x, 0.0) for x in t["_fd"])
                cash += pnl + fund_cash - t["notional"] * (COST_BPS / 1e4)
                continue
            open_pos[t["_key"]] = t
        unreal = 0.0
        for t in open_pos.values():
            pan = panels[t["symbol"]]
            i = pan["idx"][d]
            t["_fund_acc"] = t["_fund_acc"] + t["_fund"].get(d, 0.0)
            unreal += t["notional"] * (t["entry"] - pan["c"][i]) / t["entry"]
        nav.append(cash + unreal)
        detail[d] = {"cash": cash, "unreal": unreal}
        if btc_pan is not None:
            pass
    return days, np.array(nav), {"detail": detail}


def hedge_leg_nav(tks: list[dict], panels: dict[str, dict], days: list[str],
                  btc_pan: dict) -> np.ndarray:
    """对冲腿(只报):每张空票配一条**等名义多 BTC**。名义沿用空腿的 notional。
    BTC 腿:进场日 BTC 开盘进多、出场日 BTC 收盘平;资金费多头付(正费率即付);成本 7.5bp × 2。"""
    by_exit: dict[str, list[dict]] = defaultdict(list)
    for t in tks:
        by_exit[t["exit_d"]].append(t)
    cum = 0.0
    curve: list[float] = []
    for d in days:
        for t in by_exit.get(d, []):
            j = btc_pan["idx"].get(t["entry_d"])
            i = btc_pan["idx"].get(t["exit_d"])
            if j is None or i is None:
                continue
            pnl = t["notional"] * (btc_pan["c"][i] - btc_pan["o"][j]) / btc_pan["o"][j]
            fund = -t["notional"] * sum(btc_pan["fund"].get(dd, 0.0) for dd in t["_fd"])
            cum += pnl + fund - t["notional"] * 2.0 * (COST_BPS / 1e4)
        unreal = 0.0
        for t in tks:
            if t["entry_d"] <= d < t["exit_d"]:
                j = btc_pan["idx"].get(t["entry_d"])
                i = btc_pan["idx"].get(d)
                if j is None or i is None:
                    continue
                unreal += t["notional"] * (btc_pan["c"][i] - btc_pan["o"][j]) / btc_pan["o"][j]
        curve.append(cum + unreal)
    return np.array(curve)


def daily_rets(nav: np.ndarray) -> np.ndarray:
    s = np.asarray(nav, dtype=float)
    r = np.empty_like(s)
    r[0] = 0.0
    if len(s) > 1:
        r[1:] = s[1:] / s[:-1] - 1.0
    return r


def max_dd(nav: np.ndarray) -> float:
    s = np.asarray(nav, dtype=float)
    return float((s / np.maximum.accumulate(s) - 1.0).min())


def period_of(d: str) -> str:
    y = int(d[:4])
    for name, (a, b) in PERIODS:
        if a <= y <= b:
            return name
    return "其他"


def max_consec_losses(tks: list[dict]) -> int:
    run = best = 0
    for t in sorted(tks, key=lambda x: (x["entry_d"], x["symbol"])):
        if t["r_net"] <= 0:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


# ───────────────────────────── 主流程 ─────────────────────────────
def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    res: dict = {"card": "T-332", "prereg": "S-808", "mode": mode}

    # ── 事件 ──
    print("[1] 事件(crowding_watch, kind=squeeze,全部 cohort)…", flush=True)
    ev_rows = cached("events_squeeze", lambda: pull(
        "crowding_watch", "select=kind,symbol,d,cohort,fund_pct,ret,atr_thr,qv_mult"
        "&kind=eq.squeeze&order=d.asc,symbol.asc"))
    events = [(r["symbol"], str(r["d"])[:10]) for r in ev_rows]
    syms = sorted({s for s, _ in events})
    print(f"  squeeze 事件 {len(events)} 个,{len(syms)} 个合约;"
          f" {events[0][1]} → {events[-1][1]}", flush=True)

    # ── 数据 ──
    print("[2] 抓行情与资金费…", flush=True)
    perp_rows = cached("perp_squeeze_syms", lambda: pull_symbols(
        "perp_bv_daily", "d,o,h,l,c,symbol,pair", syms))
    fund_rows = cached("fund_squeeze_syms", lambda: pull_symbols(
        "v_funding_daily", "d,symbol,funding_rate,n", syms))
    perp_by: dict[str, list[dict]] = defaultdict(list)
    for r in perp_rows:
        perp_by[r["symbol"]].append(r)
    fund_by: dict[str, list[dict]] = defaultdict(list)
    for r in fund_rows:
        fund_by[r["symbol"]].append(r)
    panels: dict[str, dict] = {}
    for s in syms:
        if s in perp_by:
            panels[s] = build_panel(perp_by[s], fund_by.get(s, []))
    print(f"  面板 {len(panels)} 个合约,"
          f" {sum(p['n'] for p in panels.values())} 根 bar", flush=True)

    # BTC(自检 + 对冲腿)—— 用 t256 缓存的同一份,保证自检逐字复现
    def btc_rows():
        p = T256_CACHE / "perp_btc.json"
        if p.exists():
            return json.loads(p.read_text())
        return pull("perp_bv_daily", "select=d,o,h,l,c,symbol,pair&pair=eq.BTCUSDT&order=d.asc,recorded_at.asc")

    def btc_fund_rows():
        p = T256_CACHE / "v_funding_btc.json"
        if p.exists():
            return json.loads(p.read_text())
        return pull("v_funding_daily", "select=d,symbol,funding_rate,n&symbol=eq.BTC&order=d.asc,symbol.asc")

    btc_pan = build_panel(btc_rows(), btc_fund_rows())
    print(f"  BTC 面板 {btc_pan['n']} 根 {btc_pan['dates'][0]} → {btc_pan['dates'][-1]}", flush=True)
    res["data"] = {
        "n_events": len(events), "n_symbols": len(syms),
        "event_first": events[0][1], "event_last": events[-1][1],
        "n_bars_event_syms": int(sum(p["n"] for p in panels.values())),
        "btc_bars": btc_pan["n"], "btc_first": btc_pan["dates"][0], "btc_last": btc_pan["dates"][-1],
    }

    if mode == "fetch":
        (HERE / "t332_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
        print("fetch 完成")
        return

    # ── 自检:复现 S-736 的 18 张票 ──
    print("[3] 自检:复现 S-736(t256 票机械,BTC,时间止损 15 根)…", flush=True)
    cyc = json.loads((T256_CACHE / "cycle.json").read_text())
    dvol = {k: float(v) for k, v in json.loads((DVOL_CACHE / "deribit_dvol_btc_daily.json").read_text()).items()}
    phase: dict[str, str] = {}
    det: dict[str, float] = {}
    for r in cyc:
        dd = str(r["d"])[:10]
        if r.get("phase"):
            phase[dd] = str(r["phase"])
        if r.get("deterioration") is not None:
            det[dd] = float(r["deterioration"])
    det_days = sorted(det)
    buf: list[float] = []
    det_exp_p20: dict[str, float] = {}
    for d in det_days:
        buf.append(det[d])
        if len(buf) >= 250:
            det_exp_p20[d] = float(np.percentile(np.asarray(buf, dtype=float), 20))
    dv_days = sorted(dvol)
    dv_vals = np.array([dvol[d] for d in dv_days], dtype=float)

    def dvol_pct(d: str) -> float | None:
        i = dv_days.index(d) if d in dv_days else None
        if i is None:
            return None
        lo = (dt.date.fromisoformat(d) - dt.timedelta(days=365)).isoformat()
        j = int(np.searchsorted(dv_days, lo, side="left"))
        w = dv_vals[j:i]
        if w.size == 0:
            return None
        return float(np.sum(w <= dv_vals[i]) / w.size)

    ma20 = [float("nan")] * btc_pan["n"]
    c = btc_pan["c"]
    for i in range(MA_N - 1, btc_pan["n"]):
        ma20[i] = float(np.mean(c[i - MA_N + 1:i + 1]))
    sig736: list[str] = []
    for d in btc_pan["dates"]:
        if not (dv_days[0] <= d <= dv_days[-1]):
            continue
        i = btc_pan["idx"][d]
        ok_px = not math.isnan(ma20[i]) and c[i] < ma20[i]
        liq = phase.get(d) == "turning"
        p20 = det_exp_p20.get(d)
        if not liq and p20 is not None and det.get(d) is not None and det[d] <= p20:
            liq = True
        q = dvol_pct(d)
        if liq and q is not None and q >= 0.70 and ok_px:
            sig736.append(d)
    t736, _ = run_tickets([("BTC", d) for d in sig736], {"BTC": btc_pan},
                           TIME_STOP_S736, global_single=True)
    r736 = [t["r_net"] for t in t736]
    reasons736 = {r: sum(1 for t in t736 if t["reason"] == r) for r in ("止盈", "保本", "止损", "时间")}
    sc = {
        "n_tickets": len(t736),
        "avg_r_net": float(np.mean(r736)) if r736 else None,
        "median_r_net": float(np.median(r736)) if r736 else None,
        "win_rate": float(np.mean([x > 0 for x in r736])) if r736 else None,
        "total_r_net": float(np.sum(r736)) if r736 else None,
        "reasons": reasons736,
        "truth": S736_TRUTH,
    }
    sc["match"] = {
        "n_tickets": len(t736) == S736_TRUTH["n_tickets"],
        "avg_r_net_abs_diff": abs(sc["avg_r_net"] - S736_TRUTH["avg_r_net"]),
        "reasons_equal": reasons736 == S736_TRUTH["reasons"],
    }
    sc["ok"] = bool(sc["match"]["n_tickets"] and sc["match"]["reasons_equal"]
                    and sc["match"]["avg_r_net_abs_diff"] < 1e-6)
    print(f"  自检:票 {len(t736)}(真值 {S736_TRUTH['n_tickets']}),"
          f"平均净 R {sc['avg_r_net']:.4f}(真值 {S736_TRUTH['avg_r_net']:.4f}),"
          f"出场 {reasons736} ⇒ {'✅ 一致' if sc['ok'] else '❌ 不一致'}", flush=True)
    res["self_check_s736"] = sc

    # ── 主跑:裸空 ──
    print("[4] 主跑:裸空(时间止损 20 根)…", flush=True)
    ev_sorted = sorted(events, key=lambda x: (x[1], x[0]))
    tickets, skipped = run_tickets(ev_sorted, panels, TIME_STOP_MAIN)
    drops_main = len(DROPS)
    res["data_sanity_drops_main"] = drops_main
    res["data_sanity_drop_examples"] = [{"symbol": s, "d": d, "atr": a, "entry": e}
                                        for s, d, a, e in DROPS[:5]]
    print(f"  票 {len(tickets)}(同币 10 天内不叠加,跳过 {skipped})"
          f" · 数据卫生作废 {drops_main}", flush=True)
    rs = [t["r_net"] for t in tickets]
    avg_r = float(np.mean(rs)) if rs else None
    all_days = sorted({d for t in tickets for d in t["_fd"]})
    days, nav, navdet = sleeve_nav(tickets, panels, all_days)
    det = navdet.get("detail", {})
    res["nav_decomposition"] = {
        "nav0": float(nav[0]) if len(nav) else None,
        "nav_end": float(nav[-1]) if len(nav) else None,
        "final_cash": float(det[days[-1]]["cash"]) if days else None,
        "final_unreal": float(det[days[-1]]["unreal"]) if days else None,
        "realized_pnl_sum": float(sum(t["notional"] * (t["entry"] - t["exit"]) / t["entry"]
                                       for t in tickets)) if tickets else None,
        "funding_pnl_sum": float(sum(t["notional"] * sum(t["_fund"].get(x, 0.0) for x in t["_fd"])
                                     for t in tickets)) if tickets else None,
        "cost_pnl_sum": float(-2 * sum(t["notional"] * (COST_BPS / 1e4)
                                       for t in tickets)) if tickets else None,
    }
    print(f"  NAV 分解:nav0 {nav[0]:.4f} → nav_end {nav[-1]:.4f} · 末现金 "
          f"{res['nav_decomposition']['final_cash']:.4f} · 末未实现 "
          f"{res['nav_decomposition']['final_unreal']:.4f} · Σ已实现 "
          f"{res['nav_decomposition']['realized_pnl_sum']:.4f} · Σ资金费 "
          f"{res['nav_decomposition']['funding_pnl_sum']:.4f}", flush=True)
    rets = daily_rets(nav)
    ab = ab_test(np.zeros_like(rets), rets, mean_block=20.0, n_boot=2000, seed=SEED)
    summary = {
        "n_tickets": len(tickets), "avg_r_net": avg_r,
        "avg_r_price": float(np.mean([t["r_price"] for t in tickets])) if tickets else None,
        "median_r_net": float(np.median(rs)) if rs else None,
        "win_rate": float(np.mean([x > 0 for x in rs])) if rs else None,
        "total_r_net": float(np.sum(rs)) if rs else None,
        "reasons": {r: sum(1 for t in tickets if t["reason"] == r) for r in ("止盈", "保本", "止损", "时间")},
        "sleeve_total_return": float(nav[-1] / nav[0] - 1.0) if len(nav) else None,
        "sleeve_max_dd": max_dd(nav) if len(nav) else None,
        "ab_vs_zero": ab,
    }
    print(f"  平均净 R {avg_r:.4f} · 中位 {summary['median_r_net']:.4f} · 胜率 {summary['win_rate']:.2%}"
          f" · 袖套 {summary['sleeve_total_return']:.2%} · ab p(b≤0)={ab.get('p_b_le_a')}", flush=True)

    # ── 判据 ──
    print("[5] 判据…", flush=True)
    verdicts: dict[str, dict] = {}
    verdicts["(a) 票数 ≥ 60"] = {"ok": len(tickets) >= 60, "value": len(tickets), "need": "≥ 60"}

    # (c) 随机对照:同币同年随机进场日
    eligible: dict[tuple, list[str]] = defaultdict(list)
    for sym, pan in panels.items():
        for d in pan["dates"]:
            if pan["idx"][d] + 1 < pan["n"]:
                eligible[(sym, d[:4])].append(d)
    keyed = [((sym, d[:4]), d) for sym, d in ev_sorted]
    n_null_tickets: list[int] = []

    null_offenders: list[tuple] = []

    def null_draw(rng):
        picks = random_dates_like(keyed, eligible, rng)
        null_events = []
        for (key, d) in picks:
            if d is None:
                continue
            null_events.append((key[0], d))
        null_events.sort(key=lambda x: (x[1], x[0]))
        tk, _ = run_tickets(null_events, panels, TIME_STOP_MAIN)
        n_null_tickets.append(len(tk))
        rr = [t["r_net"] for t in tk]
        if tk:
            w = max(tk, key=lambda t: abs(t["r_net"]))
            null_offenders.append((abs(w["r_net"]), w["symbol"], w["entry_d"], w["entry"],
                                   w["atr14_d"], w["r_unit"] / w["entry"], w["r_net"]))
        return float(np.mean(rr)) if rr else float("nan")

    drops_before_null = len(DROPS)
    try:
        null = null_distribution(null_draw, N_NULL, SEED, actual=avg_r)
        pctl = percentile_of(avg_r, null)
        null_p95 = float(np.percentile(null, 95))
        null_median = float(np.median(null))
        null_stats = {"n_null": N_NULL, "null_mean": float(null.mean()),
                      "null_median": null_median, "null_p95": null_p95,
                      "actual_avg_r_net": avg_r, "actual_median_r_net": summary["median_r_net"],
                      "null_pctl_of_actual": pctl,
                      "null_pctl_of_actual_median": percentile_of(summary["median_r_net"], null),
                      "null_drops_total": len(DROPS) - drops_before_null,
                      "null_ticket_count_mean": float(np.mean(n_null_tickets)) if n_null_tickets else None,
                      "null_ticket_count_min": int(np.min(n_null_tickets)) if n_null_tickets else None,
                      "null_ticket_count_max": int(np.max(n_null_tickets)) if n_null_tickets else None}
    except NoOpNull as e:
        null_stats = {"error": str(e)}
        pctl, null_p95 = None, None
    print(f"  随机对照:实际 {avg_r:.4f} vs 对照 p95 {null_p95},分位 {pctl}"
          f" · 对照中位 {null_stats.get('null_median')}"
          f" · 对照作废 {null_stats.get('null_drops_total')}", flush=True)
    if null_offenders:
        for o in sorted(null_offenders, reverse=True)[:5]:
            print(f"    对照极端票 |R|={o[0]:.3f} {o[1]} {o[2]} entry={o[3]:.3e} atr={o[4]:.3e}"
                  f" r_unit/entry={o[5]:.4f} R={o[6]:.3f}", flush=True)

    def leave_one_out():
        if not tickets:
            return None
        k = int(np.argmax([abs(t["r_net"]) for t in tickets]))
        keep = [t for i, t in enumerate(tickets) if i != k]
        rr = [t["r_net"] for t in keep]
        d2, nav2, _ = sleeve_nav(keep, panels, sorted({d for t in keep for d in t["_fd"]}))
        ab2 = ab_test(np.zeros_like(daily_rets(nav2)), daily_rets(nav2), mean_block=20.0, n_boot=2000, seed=SEED)
        return {"dropped": {"symbol": tickets[k]["symbol"], "event_d": tickets[k]["signal_d"],
                            "r_net": tickets[k]["r_net"]},
                "n_tickets": len(keep), "avg_r_net": float(np.mean(rr)),
                "p_b_le_a": ab2.get("p_b_le_a"),
                "ok": bool(float(np.mean(rr)) > 0 and (ab2.get("p_b_le_a") or 1.0) < 0.05)}

    loo = leave_one_out()
    verdicts["(b) 平均净 R > 0 且 ab_test 对 0 p < 0.05"] = {
        "ok": bool(avg_r is not None and avg_r > 0 and (ab.get("p_b_le_a") or 1.0) < 0.05),
        "avg_r_net": avg_r, "p_b_le_a": ab.get("p_b_le_a"), "ab_verdict": ab.get("verdict"),
        "n_days": ab.get("n_days"), "cum_b": ab.get("cum_b"),
    }
    verdicts["(c) 随机对照:实际平均 R ≥ 对照 95 分位"] = {
        "ok": bool(pctl is not None and null_p95 is not None and avg_r >= null_p95),
        **null_stats,
    }
    verdicts["(d) 留一(|R| 最大的那张)后 (b) 仍成立"] = {"ok": bool(loo and loo["ok"]), **(loo or {})}
    per = []
    for name, (a, b) in PERIODS:
        sub = [t for t in tickets if a <= int(t["signal_d"][:4]) <= b]
        rr = [t["r_net"] for t in sub]
        per.append({"period": name, "n": len(sub),
                    "avg_r_net": float(np.mean(rr)) if rr else None,
                    "median_r_net": float(np.median(rr)) if rr else None,
                    "win_rate": float(np.mean([x > 0 for x in rr])) if rr else None,
                    "total_r_net": float(np.sum(rr)) if rr else None})
    bad = [p["period"] for p in per if p["avg_r_net"] is not None and p["avg_r_net"] < -0.3]
    verdicts["(e) 逐期平均净 R ≥ −0.3"] = {"ok": not bad, "bad_periods": bad, "periods": per}
    worst = min(tickets, key=lambda t: t["r_net"]) if tickets else None
    gaps = [t for t in tickets if t["reason"] in ("止损", "保本") and t["exit"] > t["stop"] + 1e-9]
    verdicts["(附) 最长连亏 / 最差单票"] = {
        "ok": True,
        "max_consecutive_losses": max_consec_losses(tickets),
        "worst_ticket": ({"symbol": worst["symbol"], "event_d": worst["signal_d"],
                          "r_net": worst["r_net"], "entry": worst["entry"], "exit": worst["exit"],
                          "stop": worst["stop"], "gapped_through_stop": worst["exit"] > worst["stop"] + 1e-9,
                          "reason": worst["reason"]} if worst else None),
        "n_gapped_through_stop": len(gaps),
    }
    res["summary"] = summary
    res["verdicts"] = verdicts
    res["leave_one_out"] = loo
    res["tickets"] = [{k: v for k, v in t.items() if k != "_fund"} for t in tickets]
    res["periods"] = per

    # ── 副:对冲 BTC(只报) ──
    print("[6] 副:对冲 BTC(等名义多 BTC,只报)…", flush=True)
    hedged_rows = []
    for t in tickets:
        j = btc_pan["idx"].get(t["entry_d"])
        i = btc_pan["idx"].get(t["exit_d"])
        if j is None or i is None:
            continue
        btc_ret = btc_pan["c"][i] / btc_pan["o"][j] - 1.0
        btc_fund = sum(btc_pan["fund"].get(dd, 0.0) for dd in t["_fd"])
        btc_net = btc_ret - btc_fund - 2.0 * (COST_BPS / 1e4)
        short_net = t["r_price"] * (t["r_unit"] / t["entry"]) + t["funding_sum"] - 2.0 * (COST_BPS / 1e4)
        comb_pct = short_net + btc_net
        hedged_rows.append({
            "symbol": t["symbol"], "event_d": t["signal_d"], "r_net_short": t["r_net"],
            "btc_ret_pct": btc_ret, "btc_funding_sum": btc_fund, "btc_net_pct": btc_net,
            "comb_pct": comb_pct,
            "comb_r_coin": comb_pct / (t["r_unit"] / t["entry"]),
        })
    days_h, nav_h, navdet_h = sleeve_nav(tickets, panels, all_days, btc_pan=btc_pan)
    btc_curve = hedge_leg_nav(tickets, panels, all_days, btc_pan)
    nav_comb = nav_h + btc_curve
    rh = daily_rets(nav_comb)
    btc_rets = np.zeros(len(rh))
    for k, d in enumerate(days_h):
        j = btc_pan["idx"].get(d)
        if j is not None and j > 0:
            btc_rets[k] = btc_pan["c"][j] / btc_pan["c"][j - 1] - 1.0
    beta_h = float(np.cov(rh, btc_rets)[0, 1] / np.var(btc_rets)) if np.var(btc_rets) > 0 else None
    hedge = {
        "n": len(hedged_rows),
        "avg_comb_r_coin": float(np.mean([h["comb_r_coin"] for h in hedged_rows])) if hedged_rows else None,
        "avg_r_short": float(np.mean([h["r_net_short"] for h in hedged_rows])) if hedged_rows else None,
        "avg_btc_net_pct": float(np.mean([h["btc_net_pct"] for h in hedged_rows])) if hedged_rows else None,
        "sleeve_total_return_naked": summary["sleeve_total_return"],
        "sleeve_total_return_hedged": float(nav_comb[-1] / nav_comb[0] - 1.0),
        "sleeve_max_dd_naked": summary["sleeve_max_dd"],
        "sleeve_max_dd_hedged": max_dd(nav_comb),
        "beta_to_btc_naked": float(np.cov(daily_rets(nav), btc_rets)[0, 1] / np.var(btc_rets)) if np.var(btc_rets) > 0 else None,
        "beta_to_btc_hedged": beta_h,
    }
    res["hedge_btc"] = hedge
    res["hedge_rows"] = hedged_rows
    print(f"  裸空 {hedge['sleeve_total_return_naked']:.2%} / 对冲 {hedge['sleeve_total_return_hedged']:.2%};"
          f" β {hedge['beta_to_btc_naked']} → {hedge['beta_to_btc_hedged']}", flush=True)

    # ── 副:全局同时只一张票(t256 原口径) + 时间止损 15 根 ──
    print("[7] 副:全局只一张票 / 时间止损 15 根(只报)…", flush=True)
    for tag, kw in (("global_single_20", dict(global_single=True, time_stop=TIME_STOP_MAIN)),
                    ("per_coin_15", dict(global_single=False, time_stop=TIME_STOP_S736))):
        tk2, sk2 = run_tickets(ev_sorted, panels, kw.pop("time_stop"), **kw)
        rr2 = [t["r_net"] for t in tk2]
        d2 = sorted({d for t in tk2 for d in t["_fd"]})
        _, nav2, _ = sleeve_nav(tk2, panels, d2) if tk2 else ([], np.array([]), {})
        r2 = daily_rets(nav2) if len(nav2) else np.array([])
        ab2 = ab_test(np.zeros_like(r2), r2, mean_block=20.0, n_boot=2000, seed=SEED) if len(r2) else {}
        res.setdefault("sensitivity", {})[tag] = {
            "n_tickets": len(tk2), "skipped": sk2,
            "avg_r_net": float(np.mean(rr2)) if rr2 else None,
            "median_r_net": float(np.median(rr2)) if rr2 else None,
            "win_rate": float(np.mean([x > 0 for x in rr2])) if rr2 else None,
            "total_r_net": float(np.sum(rr2)) if rr2 else None,
            "sleeve_total_return": float(nav2[-1] / nav2[0] - 1.0) if len(nav2) else None,
            "p_b_le_a": ab2.get("p_b_le_a"),
        }
        print(f"  {tag}:票 {len(tk2)},平均净 R {res['sensitivity'][tag]['avg_r_net']}", flush=True)

    # ── 产物 ──
    out_json = HERE / "t332_results.json"
    out_json.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    print(f"\n写了 {out_json}", flush=True)

    csv_path = HERE / "t332_tickets.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "event_d", "entry_d", "exit_d", "reason", "entry", "exit",
                    "atr14_d", "r_unit", "stop", "target", "hold_days",
                    "r_price", "r_fund", "r_cost", "r_net", "funding_sum", "gapped_through_stop"])
        for t in sorted(tickets, key=lambda x: (x["entry_d"], x["symbol"])):
            w.writerow([t["symbol"], t["signal_d"], t["entry_d"], t["exit_d"], t["reason"],
                        round(t["entry"], 10), round(t["exit"], 10), round(t["atr14_d"], 10),
                        round(t["r_unit"], 10), round(t["stop"], 10), round(t["target"], 10),
                        t["hold_days"], round(t["r_price"], 6), round(t["r_fund"], 6),
                        round(t["r_cost"], 6), round(t["r_net"], 6), round(t["funding_sum"], 8),
                        int(t["reason"] in ("止损", "保本") and t["exit"] > t["stop"] + 1e-9)])
    print(f"写了 {csv_path}", flush=True)

    ok_all = all(v["ok"] for v in verdicts.values())
    res["overall"] = ("✅ 全过(可开纸面臂 short_squeeze_fade,不动钱)" if ok_all
                      else "❌ 未全过(不立臂)")
    # 报告:叙述部分先写好,这里把测得的数**追加**到同一个 md
    md = HERE / "T-332_squeeze_fade.md"
    if not md.exists():
        md.write_text(REPORT_HEADER)
    else:
        # 重跑幂等:旧的「结果」块整段丢掉,只留叙述部分(第一个结果块标记之前)
        old = md.read_text()
        cut = old.find("\n## 结果(脚本自动追加")
        if cut > 0:
            md.write_text(old[:cut].rstrip() + "\n")
    lines = ["", "---", "", "## 结果(脚本自动追加;完整数字见 `t332_results.json`)", "",
             f"- 票数 {summary['n_tickets']} · 平均净 R {avg_r:.4f} · 中位 {summary['median_r_net']:.4f}"
             f" · 胜率 {summary['win_rate']:.1%} · 总 {summary['total_r_net']:.2f}R",
             f"- 出场原因 {summary['reasons']}",
             f"- 袖套 {summary['sleeve_total_return']:.2%} · 最大回撤 {summary['sleeve_max_dd']:.2%}"
             f" · ab p(b≤0)={ab.get('p_b_le_a')}",
             f"- NAV 分解:nav0 {nav[0]:.4f} → nav_end {nav[-1]:.4f} · 末现金 "
             f"{res['nav_decomposition']['final_cash']:.4f} · 末未实现 "
             f"{res['nav_decomposition']['final_unreal']:.4f} · Σ已实现 "
             f"{res['nav_decomposition']['realized_pnl_sum']:.4f} · Σ资金费 "
             f"{res['nav_decomposition']['funding_pnl_sum']:.4f} · Σ成本 "
             f"{res['nav_decomposition']['cost_pnl_sum']:.4f}",
             f"- 数据卫生(ATR/进场价 ∉ [{MIN_ATR_FRAC},{MAX_ATR_FRAC}]):实际侧作废 "
             f"{res['data_sanity_drops_main']} · 随机对照侧作废 "
             f"{null_stats.get('null_drops_total')}",
             f"- 自检(S-736 复现):票 {sc['n_tickets']} · 平均净 R {sc['avg_r_net']:.4f}"
             f" ⇒ {'✅ 一致' if sc['ok'] else '❌ 不一致'}",
             f"- 对冲版(只报):裸空 {hedge['sleeve_total_return_naked']:.2%} → 对冲 "
             f"{hedge['sleeve_total_return_hedged']:.2%} · β {hedge['beta_to_btc_naked']} → "
             f"{hedge['beta_to_btc_hedged']}",
             ""]
    for k, v in verdicts.items():
        lines.append(f"- **{k}** ⇒ {'✅' if v.get('ok') else '❌'} "
                     f"`{json.dumps(v, ensure_ascii=False, default=str)[:520]}`")
    lines += ["", f"**总判:{res['overall']}**", ""]
    md.write_text(md.read_text() + "\n".join(lines))
    out_json.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({"summary": summary, "verdicts": verdicts, "overall": res["overall"]},
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
