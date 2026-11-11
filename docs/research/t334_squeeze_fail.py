"""T-334 —— S-810 低频 + 等确认的 squeeze 做空:只做最极端的(扩张前 20%),等收盘吐回事件日开盘价再进空,止损放在拉升高点之上。

用法:
    python3 docs/research/t334_squeeze_fail.py all     # 主跑 + 判据 + 产物(数据已缓存,不重抓)
    python3 docs/research/t334_squeeze_fail.py fetch   # 只抓数落缓存

产物:
    docs/research/T-334_squeeze_fail.md        报告(S-810 原文照抄开头)
    docs/research/t334_results.json             全部数字
    docs/research/t334_tickets.csv              逐票表
    docs/research/scenarios/lane-a-T-334.json   前向命题(≥3 条,≥1 条 close: 自动结算)

数据:只读 Supabase(crowding_watch / perp_bv_daily / v_funding_daily)。**复用 T-332 的缓存**
      (只读,不复制):/Volumes/CometCloudAI/cometcloud-local/research/t332
纪律:不改代码、不入库、不改卡以外的仓库文件;零分布 / 盈亏 / 随机对照只用 src/data/evaluation/apparatus.py;
      票机械复用 t332_squeeze_fade.py(S-808 / S-736 那一套,逐字一致)。
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    ab_test,
    null_distribution,
    percentile_of,
    random_dates_like,
)

import t332_squeeze_fade as t332  # noqa: E402  票机械 / 抓数 / 袖套 NAV 复用

# ───────────────────────── S-810 写死的参数 ─────────────────────────
COST_BPS = 7.5             # 成本 7.5bp × 2(同 S-808)
STOP_MULT = 1.01           # 止损 = 事件日起到确认日的最高价 × 1.01
TP_MULT = 2.0              # 止盈 = 进场 − 2 × (止损 − 进场)
CONFIRM_WINDOW = 10        # 确认窗:事件后 10 个交易日内
TIME_STOP = 30             # 时间止损 30 根(S-781 的 30 天窗口)
MIN_EXTREME_N = 30         # 前 30 个事件不判(极端分位的历史不够)
EXTREME_PCTL = 80.0        # 扩张前 20% ⇒ 分位 ≥ 80
SEED = 810
N_NULL = 1000
# 数据卫生(与 S-808 同一把尺):风险单位 / 进场价 落在带外 ⇒ 进场点作废。
MIN_RU_FRAC = 0.005
MAX_RU_FRAC = 1.0
PERIOD_A = (2020, 2023)
PERIOD_B = (2024, 2026)

CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t334")
T332_CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t332")

PREREG_810 = """## S-810 — 低频 + 等确认的做空(Jazz 11-11「做空的频率要低」):只挑最极端的 squeeze,**等它自己先失败**再进空,止损放在拉升高点之上 —— 预注册(Seth,2026-11-11 03:08 UTC;S-808 的 350 张票没按极端程度或确认分过组,这条规则在任何子集上都没算过;交 A 道 T-334)
**为什么(S-808 的拆解,已看过):** 频率不是输的原因 —— 每张票的成本只有 0.011R;S-809 只有 11 张票,每张反而亏得更多(−0.64R)。输在**进场时机**:350 张里 217 张在 2 天内结束、平均 −0.71R —— squeeze 第二天还在冲,1.5 ATR 的止损先被打。所以低频要和「等确认」一起:只做最极端的,等拉升自己失败了再进。
**写死。** 事件同 S-808(`crowding_watch` squeeze)。**极端:** 事件当天 ret / atr_thr(拉升是 ATR 门槛的几倍)在**截至当日**的全部历史事件里处于扩张前 20%(前 30 个事件不判)。**确认:** 事件后 10 个交易日内,该币永续收盘**第一次低于事件当天的开盘价**(拉升被完全吐回)⇒ 次日开盘进空;10 天内没确认 ⇒ 不做。**票:** 止损 = 事件日起到确认日的最高价 × 1.01;止盈 = 进场 − 2 × (止损 − 进场);**不设保本**;时间止损 30 根(S-781 的 30 天窗口);同一币不叠加;成本与资金费同 S-808。
**判(全过才 ✅):** (a) 票数 ≥ 20(不足只报不判);(b) 平均 R > 0 且 `apparatus.ab_test` 对 0 p < 0.10;(c) 随机对照:同币同年、同样「收盘低于某个近期开盘」的日子随机进场(1,000 次,种子 810),实际 ≥ 对照 90 分位;(d) 对 |R| 最大一张留一,平均 R 仍 > 0;(e) 2020–23 与 2024–26 两段平均 R 同号。另报:每年票数(频率)、不加「极端」只加「确认」的版本、只加「极端」不加「确认」的版本(都只报)。
**后果:** 全过 ⇒ 开纸面臂 `short_squeeze_fail`(不动钱);不过 ⇒ squeeze 的做空在「低频 + 确认」下也不成立。**试验计数:做空族 +1。**"""

REPORT_HEADER = PREREG_810 + """

## T-334 —— 执行记录(lane-a,2026-11-11)

**写死的三步(逐条照 S-810):**
1. **极端** —— 事件当天 `ret / atr_thr`(拉升是 ATR 门槛的几倍),在**截至当日**的全部历史 squeeze 事件里
   处于扩张前 20%(分位 ≥ 80);前 30 个事件不判(历史不够)。
2. **确认** —— 事件后 10 个交易日内,该币永续收盘**第一次低于事件当天的开盘价** ⇒ 次日开盘进空;
   10 天内没确认 ⇒ 不做。
3. **票** —— 止损 = 事件日起到确认日的最高价 × 1.01;止盈 = 进场 − 2 × (止损 − 进场);**不设保本**;
   时间止损 30 根;同一币不叠加(上一张没平仓就不再开);成本 7.5bp × 2;资金费按持有期实计
   (空方收正费率,`v_funding_daily`)。R 单位 = 止损 − 进场。

**数据(只读,不入库):** 事件 = `crowding_watch` kind=squeeze(351 个 / 240 合约,2020-08-08 → 2026-10-30);
价格 `perp_bv_daily`;资金费 `v_funding_daily`;**复用 T-332 的缓存(只读,不复制、不重抓)**。
随机对照 = `apparatus.random_dates_like` + `apparatus.null_distribution`(同币同年,1000 次,种子 810)。

**与 S-808 的差异(只在三处,其余逐字相同):** 进场从「d+1 开盘」改成「确认后次日开盘」;
止损从「1.5 × ATR14」改成「拉升高点 × 1.01」;止盈从「2.5 × ATR14」改成「2R」;去掉 +1R 保本;
时间止损 20 → 30 根。成本 / 资金费 / 名义 / 每票风险 / 数据卫生带全部照抄。

**随机对照的口径(写下来,免得事后解释):** 对照把「触发」随机化、票机械一字不变 ——
同一张票的构造是「事件日 E → 确认日 C(第一次收盘低于 open(E))→ C+1 开盘进场」,
对照里 E 换成同币同年随机抽的一个日子。**主对照的抽样池 = 上涨日**(close > open),
因为真实 squeeze 事件日本身就是一根大涨的阳线;池里全是上涨日 ⇒ 对照的进场日同样是
「收盘被吐回某个近期开盘价」的日子,和实际侧同种。**稳健对照(只作旁证)** 把池换成全部日子。
两侧同一把尺(同样的确认窗 / 止损 / 止盈 / 时间止损 / 同一币不叠加 / 同样的数据卫生带)。

全部数字见 `t334_results.json`,逐票表见 `t334_tickets.csv`。

---
"""

# ───────────────────────────── 抓数(复用 T-332 缓存) ─────────────────────────────
def load(name: str, puller) -> list[dict]:
    """先读自己的缓存 → 再读 T-332 的缓存(只读)→ 都没有才抓。"""
    for base in (CACHE, T332_CACHE):
        p = base / f"{name}.json"
        if p.exists():
            rows = json.loads(p.read_text())
            print(f"  cache[{base.name}] {name}: {len(rows)} rows", flush=True)
            return rows
    rows = puller()
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{name}.json").write_text(json.dumps(rows))
    print(f"  pulled {name}: {len(rows)} rows", flush=True)
    return rows


# ───────────────────────────── 极端分位 ─────────────────────────────
def extreme_flags(evs: list[dict]) -> list[dict]:
    """每个事件算 x = ret / atr_thr,并判「截至当日」的历史里是否处在扩张前 20%。

    参考集 = 日期 ≤ 事件当日的全部历史事件(含事件本身)。前 30 个事件历史不够 ⇒ 不判。
    """
    out = []
    ratios: list[float] = []
    for j, ev in enumerate(evs):
        x = float(ev["ret"]) / float(ev["atr_thr"])
        ratios.append(x)
        judged = (j + 1) >= MIN_EXTREME_N
        thr = None
        if judged:
            thr = float(np.percentile(np.asarray(ratios[:j + 1], dtype=float), EXTREME_PCTL))
        out.append({"ratio": x, "judged": judged, "p80_thr": thr,
                    "extreme": bool(judged and x >= thr)})
    return out


# ───────────────────────────── 确认 + 票 ─────────────────────────────
def find_confirmation(pan: dict, i_event: int) -> int | None:
    """事件后 10 个交易日内,收盘第一次低于事件当日开盘价的那一天(bar 序号);没有 ⇒ None。"""
    n = pan["n"]
    o_ref = pan["o"][i_event]
    hi = min(i_event + 1 + CONFIRM_WINDOW, n)
    for j in range(i_event + 1, hi):
        if pan["c"][j] < o_ref:
            return j
    return None


def simulate_s810(pan: dict, i_event: int, i_conf: int, i_entry: int,
                  symbol: str, event_d: str, extra: dict | None = None,
                  hygiene: bool = False) -> tuple[dict | None, str]:
    """S-810 的票:进场 = C+1 开盘,止损 = max(high[E..C]) × 1.01,止盈 = 进场 − 2R,无保本,时间止损 30 根。

    `hygiene=True` 时额外套 S-808 的数据卫生带(风险单位 / 进场价 ∉ [0.5%, 100%] ⇒ 作废)。
    **默认关闭**:S-810 的止损是价格(拉升高点),不是 ATR,风险单位天然可以很大
    (进场远低于拉升高点 ⇒ 2R 的目标价甚至可能落到 0 以下)。这是**规则的性质**,不是坏数据,
    所以按预注册原文跑;带子作为敏感度另报。
    """
    n = pan["n"]
    if i_entry >= n:
        return None, "no_entry_bar"
    entry = pan["o"][i_entry]
    stop_px = float(max(pan["h"][i_event:i_conf + 1])) * STOP_MULT
    r_unit = stop_px - entry
    if not math.isfinite(entry) or entry <= 0:
        return None, "bad_entry"
    if not math.isfinite(r_unit) or r_unit <= 0:
        return None, "stop_below_entry"
    frac = r_unit / entry
    if hygiene and (frac < MIN_RU_FRAC or frac > MAX_RU_FRAC):
        return None, "hygiene"
    target = entry - TP_MULT * r_unit
    exit_i = exit_px = None
    reason = ""
    for b in range(i_entry, min(i_entry + TIME_STOP, n)):
        o, h, l = pan["o"][b], pan["h"][b], pan["l"][b]
        if o >= stop_px:          # 跳空穿止损 ⇒ 按开盘价
            exit_i, exit_px, reason = b, o, "止损"
            break
        if o <= target:           # 跳空越过止盈 ⇒ 按开盘价
            exit_i, exit_px, reason = b, o, "止盈"
            break
        if h >= stop_px:          # 同一根 bar 先碰止损(保守)
            exit_i, exit_px, reason = b, stop_px, "止损"
            break
        if l <= target:
            exit_i, exit_px, reason = b, target, "止盈"
            break
    truncated = False
    if exit_i is None:
        b = min(i_entry + TIME_STOP - 1, n - 1)
        exit_i, exit_px, reason = b, pan["c"][b], "时间"
        truncated = b < i_entry + TIME_STOP - 1
    hold_days = exit_i - i_entry + 1
    fd = pan["dates"][i_entry:exit_i + 1]
    fund = float(sum(pan["fund"].get(x, 0.0) for x in fd))
    r_px = (entry - exit_px) / r_unit
    r_fund = fund * entry / r_unit
    r_cost = 2.0 * (COST_BPS / 1e4) * entry / r_unit
    t = {"symbol": symbol, "signal_d": event_d, "entry_d": pan["dates"][i_entry],
         "exit_d": pan["dates"][exit_i], "entry": entry, "exit": exit_px,
         "stop": stop_px, "target": target, "r_unit": r_unit,
         "reason": reason, "hold_days": hold_days, "funding_sum": fund,
         "r_price": r_px, "r_fund": r_fund, "r_cost": r_cost,
         "r_net": r_px + r_fund - r_cost, "truncated": truncated,
         "confirm_d": pan["dates"][i_conf], "event_to_confirm_bars": i_conf - i_event,
         "_fund": pan["fund"], "_fd": fd, "_key": (symbol, event_d),
         "_i_entry": i_entry, "_i_exit": exit_i}
    if extra:
        t.update(extra)
    return t, "ok"


def build_tickets(evs: list[dict], flags: list[dict], panels: dict[str, dict],
                  use_extreme: bool, use_confirm: bool, hygiene: bool = False) -> tuple[list[dict], dict]:
    """事件 → 票(use_extreme / use_confirm 开关,用来跑「只加确认」「只加极端」两个只报版本)。"""
    stats = {"n_events": 0, "n_extreme": 0, "n_no_panel": 0, "n_no_bar": 0,
             "n_unconfirmed": 0, "n_dropped": 0, "drop_reasons": defaultdict(int),
             "n_stack_skipped": 0}
    cands: list[dict] = []
    for ev, fl in zip(evs, flags):
        stats["n_events"] += 1
        if use_extreme:
            if not fl["judged"]:
                stats["drop_reasons"]["极端:历史不足30"] += 1
                continue
            if not fl["extreme"]:
                stats["drop_reasons"]["非极端"] += 1
                continue
            stats["n_extreme"] += 1
        sym = ev["symbol"]
        pan = panels.get(sym)
        if pan is None:
            stats["n_no_panel"] += 1
            continue
        i_event = pan["idx"].get(ev["d"])
        if i_event is None or i_event + 1 >= pan["n"]:
            stats["n_no_bar"] += 1
            continue
        if use_confirm:
            i_conf = find_confirmation(pan, i_event)
            if i_conf is None:
                stats["n_unconfirmed"] += 1
                continue
            i_entry = i_conf + 1
        else:
            i_conf = i_event
            i_entry = i_event + 1
        if i_entry >= pan["n"]:
            stats["n_no_bar"] += 1
            continue
        t, why = simulate_s810(pan, i_event, i_conf, i_entry, sym, ev["d"],
                               extra={"ratio": fl["ratio"], "extreme": fl["extreme"],
                                      "p80_thr": fl["p80_thr"]},
                               hygiene=hygiene)
        if t is None:
            stats["n_dropped"] += 1
            stats["drop_reasons"][why] += 1
            continue
        cands.append(t)
    # 同一币不叠加:上一张没平仓(进场 bar ≤ 上一张出场 bar)就不再开
    cands.sort(key=lambda x: (x["entry_d"], x["symbol"]))
    out: list[dict] = []
    busy: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for t in cands:
        sym = t["symbol"]
        clash = False
        for (a, b) in busy[sym]:
            if not (t["_i_exit"] < a or t["_i_entry"] > b):
                clash = True
                break
        if clash:
            stats["n_stack_skipped"] += 1
            stats["drop_reasons"]["同一币不叠加"] += 1
            continue
        busy[sym].append((t["_i_entry"], t["_i_exit"]))
        out.append(t)
    stats["drop_reasons"] = dict(stats["drop_reasons"])
    return out, stats


# ───────────────────────────── 随机对照 ─────────────────────────────
def make_pools(panels: dict[str, dict]) -> dict[str, dict[str, list[str]]]:
    """eligible[(sym, year)] = 该币该年可用的日子。

    pool_up: 上涨日(close > open)—— 真实 squeeze 事件日就是阳线,主对照用这个池。
    pool_all: 全部日子 —— 稳健对照。
    """
    pools: dict[str, dict[str, list[str]]] = {"pool_up": defaultdict(list), "pool_all": defaultdict(list)}
    for sym, pan in panels.items():
        for i, d in enumerate(pan["dates"]):
            if i + 1 >= pan["n"]:
                continue
            key = (sym, d[:4])
            pools["pool_all"][key].append(d)
            if pan["c"][i] > pan["o"][i]:
                pools["pool_up"][key].append(d)
    return {k: dict(v) for k, v in pools.items()}


# ───────────────────────────── 主流程 ─────────────────────────────
def summarize(tks: list[dict]) -> dict:
    rs = [t["r_net"] for t in tks]
    return {
        "n_tickets": len(tks),
        "avg_r_net": float(np.mean(rs)) if rs else None,
        "median_r_net": float(np.median(rs)) if rs else None,
        "avg_r_price": float(np.mean([t["r_price"] for t in tks])) if tks else None,
        "avg_r_fund": float(np.mean([t["r_fund"] for t in tks])) if tks else None,
        "avg_r_cost": float(np.mean([t["r_cost"] for t in tks])) if tks else None,
        "win_rate": float(np.mean([x > 0 for x in rs])) if rs else None,
        "total_r_net": float(np.sum(rs)) if rs else None,
        "reasons": {r: sum(1 for t in tks if t["reason"] == r) for r in ("止盈", "止损", "时间")},
    }


def sleeve_stats(tks: list[dict], panels: dict[str, dict]) -> dict:
    if not tks:
        return {}
    days = sorted({d for t in tks for d in t["_fd"]})
    _, nav, _ = t332.sleeve_nav(tks, panels, days)
    rets = t332.daily_rets(nav)
    ab = ab_test(np.zeros_like(rets), rets, mean_block=20.0, n_boot=2000, seed=SEED)
    return {"sleeve_total_return": float(nav[-1] / nav[0] - 1.0),
            "sleeve_max_dd": t332.max_dd(nav),
            "ab_vs_zero": ab, "n_days": len(days)}


def diag(evs: list[dict], flags: list[dict], panels: dict[str, dict]) -> None:
    """诊断:逐年「极端 → 确认 → 进场」的漏斗,以及风险单位 / 进场价 的分布(数据卫生带的影响)。"""
    byy: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    det: list[tuple] = []
    for ev, fl in zip(evs, flags):
        if not fl["extreme"]:
            continue
        y = ev["d"][:4]
        byy[y][0] += 1
        pan = panels.get(ev["symbol"])
        i = pan["idx"].get(ev["d"]) if pan else None
        if i is None:
            continue
        ic = find_confirmation(pan, i)
        if ic is None:
            continue
        byy[y][1] += 1
        stop = float(max(pan["h"][i:ic + 1])) * STOP_MULT
        ie = ic + 1
        if ie >= pan["n"]:
            continue
        entry = pan["o"][ie]
        byy[y][2] += 1
        det.append((ev["symbol"], ev["d"], (stop - entry) / entry, y))
    print("  year  extreme  confirmed  entered", flush=True)
    for y in sorted(byy):
        print(f"   {y}   {byy[y][0]:5d}  {byy[y][1]:8d}  {byy[y][2]:7d}", flush=True)
    fr = sorted(d[2] for d in det)
    if fr:
        print(f"  风险单位/进场价:n={len(fr)} min={fr[0]:.4f} p25={fr[len(fr)//4]:.4f} "
              f"med={fr[len(fr)//2]:.4f} p75={fr[3*len(fr)//4]:.4f} max={fr[-1]:.4f}", flush=True)
        print(f"  < {MIN_RU_FRAC}:{sum(1 for x in fr if x < MIN_RU_FRAC)}  "
              f"> {MAX_RU_FRAC}:{sum(1 for x in fr if x > MAX_RU_FRAC)}", flush=True)
        print("  最小的 5 个:" + ", ".join(f"{d[0]} {d[1]} {d[2]:.4f}" for d in
                                          sorted(det, key=lambda x: x[2])[:5]), flush=True)
    # 确认时滞(事件 → 确认)分布
    lags = []
    for ev, fl in zip(evs, flags):
        if not fl["extreme"]:
            continue
        pan = panels.get(ev["symbol"])
        i = pan["idx"].get(ev["d"]) if pan else None
        if i is None:
            continue
        ic = find_confirmation(pan, i)
        if ic is not None:
            lags.append(ic - i)
    if lags:
        ls = sorted(lags)
        print(f"  事件→确认 滞后(根):min={ls[0]} med={ls[len(ls)//2]} max={ls[-1]}  "
              f"分布={ {k: ls.count(k) for k in range(1, 11)} }", flush=True)
    # 极端阈值的时间轨迹:「扩张前 20%」是不是其实一个「近期」过滤器
    print("  year  事件  极端  ratio中位  p80阈值中位  阈值/事件中位", flush=True)
    byy2: dict[str, list] = defaultdict(list)
    for ev, fl in zip(evs, flags):
        if fl["judged"]:
            byy2[ev["d"][:4]].append((fl["ratio"], fl["p80_thr"]))
    for y in sorted(byy2):
        rs = sorted(x[0] for x in byy2[y])
        ths = sorted(x[1] for x in byy2[y] if x[1] is not None)
        nex = sum(1 for x in byy2[y] if x[0] >= x[1]) if ths else 0
        print(f"   {y}  {len(rs):4d}  {nex:4d}  {rs[len(rs)//2]:9.3f}  "
              f"{ths[len(ths)//2]:11.3f}  {(ths[len(ths)//2]/rs[len(rs)//2]):11.2f}", flush=True)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    res: dict = {"card": "T-334", "prereg": "S-810", "mode": mode}

    # ── 事件 ──
    print("[1] 事件(crowding_watch, kind=squeeze)…", flush=True)
    ev_rows = load("events_squeeze", lambda: t332.pull(
        "crowding_watch", "select=kind,symbol,d,cohort,fund_pct,ret,atr_thr,qv_mult"
        "&kind=eq.squeeze&order=d.asc,symbol.asc"))
    evs = [{"symbol": r["symbol"], "d": str(r["d"])[:10], "ret": r["ret"], "atr_thr": r["atr_thr"]}
           for r in ev_rows]
    evs.sort(key=lambda e: (e["d"], e["symbol"]))
    dup = len(evs) - len({(e["symbol"], e["d"]) for e in evs})
    syms = sorted({e["symbol"] for e in evs})
    print(f"  squeeze 事件 {len(evs)} 个,{len(syms)} 个合约;重复(同币同日){dup};"
          f" {evs[0]['d']} → {evs[-1]['d']}", flush=True)

    # ── 面板 ──
    print("[2] 面板(复用 T-332 缓存)…", flush=True)
    perp_rows = load("perp_squeeze_syms", lambda: t332.pull_symbols(
        "perp_bv_daily", "d,o,h,l,c,symbol,pair", syms))
    fund_rows = load("fund_squeeze_syms", lambda: t332.pull_symbols(
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
            panels[s] = t332.build_panel(perp_by[s], fund_by.get(s, []))
    print(f"  面板 {len(panels)} 个合约,{sum(p['n'] for p in panels.values())} 根 bar", flush=True)
    if mode == "diag":
        flags = extreme_flags(evs)
        diag(evs, flags, panels)
        return
    res["data"] = {"n_events": len(evs), "n_symbols": len(syms), "dup_event_sym_d": dup,
                   "event_first": evs[0]["d"], "event_last": evs[-1]["d"],
                   "n_panels": len(panels),
                   "n_bars": int(sum(p["n"] for p in panels.values()))}
    if mode == "fetch":
        (HERE / "t334_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
        print("fetch 完成")
        return

    # ── 极端分位 ──
    print("[3] 极端分位(ret/atr_thr,截至当日的扩张前 20%)…", flush=True)
    flags = extreme_flags(evs)
    n_judged = sum(1 for f in flags if f["judged"])
    n_extreme = sum(1 for f in flags if f["extreme"])
    print(f"  可判事件 {n_judged}(前 {MIN_EXTREME_N} 个不判)· 极端事件 {n_extreme}", flush=True)
    res["extreme"] = {"n_judged": n_judged, "n_extreme": n_extreme,
                      "ratio_min": float(min(f["ratio"] for f in flags)),
                      "ratio_med": float(np.median([f["ratio"] for f in flags])),
                      "ratio_max": float(max(f["ratio"] for f in flags))}

    # ── 主跑:极端 + 确认 ──
    print("[4] 主跑:极端 + 确认…", flush=True)
    tickets, st_main = build_tickets(evs, flags, panels, use_extreme=True, use_confirm=True)
    if not tickets:
        res["main"] = {"flow": st_main}
        res["overall"] = "⚠️ 0 张票 —— 只报不判"
        (HERE / "t334_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        (HERE / "T-334_squeeze_fail.md").write_text(
            REPORT_HEADER + "\n\n## 结果\n\n0 张票(流程统计见 `t334_results.json` 的 `main.flow`)。\n")
        print("0 张票,已落产物", flush=True)
        return
    sum_main = summarize(tickets)
    print(f"  票 {len(tickets)} · 平均净 R {sum_main['avg_r_net']} · 中位 {sum_main['median_r_net']}"
          f" · 出场 {sum_main['reasons']}", flush=True)
    res["main"] = {"summary": sum_main, "flow": st_main}
    res["main"].update(sleeve_stats(tickets, panels))

    # ── 只报版本 1:不加极端、只加确认 ──
    print("[5] 只报:只加「确认」(全部事件)…", flush=True)
    t_conf_only, st_conf = build_tickets(evs, flags, panels, use_extreme=False, use_confirm=True)
    sum_conf = summarize(t_conf_only)
    print(f"  票 {len(t_conf_only)} · 平均净 R {sum_conf['avg_r_net']}", flush=True)
    res["variant_confirm_only"] = {"summary": sum_conf, "flow": st_conf}
    res["variant_confirm_only"].update(sleeve_stats(t_conf_only, panels))

    # ── 只报版本 2:只加极端、不加确认(S-808 票机械原样) ──
    print("[6] 只报:只加「极端」(S-808 票机械: d+1 开盘进空、1.5ATR 止损、2.5ATR 止盈、+1R 保本、时间 20 根)…",
          flush=True)
    ext_events = [(e["symbol"], e["d"]) for e, f in zip(evs, flags) if f["extreme"]]
    t_ext_only, sk_ext = t332.run_tickets(ext_events, panels, t332.TIME_STOP_MAIN)
    sum_ext = summarize(t_ext_only)
    print(f"  票 {len(t_ext_only)}(跳过 {sk_ext}) · 平均净 R {sum_ext['avg_r_net']}", flush=True)
    res["variant_extreme_only"] = {"summary": sum_ext, "skipped": sk_ext,
                                   "note": "S-808 原票机械,只把事件池换成极端事件",
                                   "sleeve": sleeve_stats(t_ext_only, panels)}

    # ── 随机对照 ──
    print("[7] 随机对照(1,000 次,种子 810)…", flush=True)
    pools = make_pools(panels)
    actual_avg = sum_main["avg_r_net"]
    ctrl_stats: dict = {}

    def run_control(tag: str, pool: dict, actual: float, tickets_ref: list[dict],
                    hygiene: bool) -> dict:
        n_tk: list[int] = []

        def draw(rng):
            keyed = [((t["symbol"], t["signal_d"][:4]), t["signal_d"]) for t in tickets_ref]
            picks = random_dates_like(keyed, pool, rng)
            cands = []
            for (key, d) in picks:
                if d is None:
                    continue
                sym = key[0]
                pan = panels.get(sym)
                if pan is None:
                    continue
                i_event = pan["idx"].get(d)
                if i_event is None or i_event + 1 >= pan["n"]:
                    continue
                i_conf = find_confirmation(pan, i_event)
                if i_conf is None:
                    continue
                t, _ = simulate_s810(pan, i_event, i_conf, i_conf + 1, sym, d,
                                     extra={"ctrl": True}, hygiene=hygiene)
                if t is None:
                    continue
                cands.append(t)
            cands.sort(key=lambda x: (x["entry_d"], x["symbol"]))
            busy: dict[str, list[tuple[int, int]]] = defaultdict(list)
            keep = []
            for t in cands:
                sym = t["symbol"]
                if any(not (t["_i_exit"] < a or t["_i_entry"] > b) for (a, b) in busy[sym]):
                    continue
                busy[sym].append((t["_i_entry"], t["_i_exit"]))
                keep.append(t)
            n_tk.append(len(keep))
            rr = [t["r_net"] for t in keep]
            return float(np.mean(rr)) if rr else float("nan")

        try:
            null = null_distribution(draw, N_NULL, SEED, actual=actual)
            fin = null[np.isfinite(null)]
            pctl = percentile_of(actual, null)
            null_p90 = float(np.percentile(fin, 90))
            null_p95 = float(np.percentile(fin, 95))
            st = {"n_null": N_NULL, "n_finite": int(fin.size),
                  "null_mean": float(fin.mean()), "null_median": float(np.median(fin)),
                  "null_p90": null_p90, "null_p95": null_p95,
                  "actual_avg_r_net": actual,
                  "null_pctl_of_actual": pctl,
                  "ctrl_ticket_count_mean": float(np.mean(n_tk)) if n_tk else None,
                  "ctrl_ticket_count_min": int(np.min(n_tk)) if n_tk else None,
                  "ctrl_ticket_count_max": int(np.max(n_tk)) if n_tk else None,
                  "actual_ge_p90": bool(actual >= null_p90)}
            print(f"  {tag}:对照均值 {fin.mean():.4f}(有限 {fin.size}/{N_NULL}) · p90 {null_p90:.4f} · "
                  f"实际 {actual:.4f} ⇒ 分位 {pctl} · 对照票数均值 {np.mean(n_tk):.1f}", flush=True)
            return st
        except NoOpNull as e:
            print(f"  {tag}:对照失败 {e}", flush=True)
            return {"error": str(e)}

    ctrl_stats["main_up_days"] = run_control("main_up_days", pools["pool_up"], actual_avg,
                                             tickets, hygiene=False)
    ctrl_stats["robust_all_days"] = run_control("robust_all_days", pools["pool_all"], actual_avg,
                                                 tickets, hygiene=False)
    res["control"] = ctrl_stats

    # ── 敏感度:把 S-808 的数据卫生带套上(两侧同一把尺) ──
    print("[8] 敏感度:套上 S-808 的数据卫生带(风险单位/进场价 ∉ [0.5%,100%])…", flush=True)
    tickets_h, st_h = build_tickets(evs, flags, panels, True, True, hygiene=True)
    sum_h = summarize(tickets_h)
    ctrl_h = run_control("hygiene_band", pools["pool_up"],
                         sum_h["avg_r_net"] if tickets_h else float("nan"),
                         tickets_h, hygiene=True)
    res["sensitivity_hygiene_band"] = {"summary": sum_h, "flow": st_h, "control": ctrl_h}
    print(f"  卫生带版:票 {len(tickets_h)} · 平均净 R {sum_h['avg_r_net']}", flush=True)

    # 只加确认版(96 张票那一版)也配一个对照:「确认」单独有没有超出随机
    ctrl_conf = run_control("confirm_only_up_days", pools["pool_up"],
                             sum_conf["avg_r_net"] if t_conf_only else float("nan"),
                             t_conf_only, hygiene=False)
    res.setdefault("variant_confirm_only", {})["control"] = ctrl_conf
    print(f"  只加确认版的对照:实际 {sum_conf['avg_r_net']:.4f} vs 对照 p90 "
          f"{ctrl_conf.get('null_p90')} ⇒ 分位 {ctrl_conf.get('null_pctl_of_actual')}", flush=True)

    # 逐年轨迹:事件数 / 极端数 / 阈值
    byy: dict[str, dict] = {}
    for ev, fl in zip(evs, flags):
        y = ev["d"][:4]
        b = byy.setdefault(y, {"events": 0, "judged": 0, "extreme": 0, "ratios": [], "thrs": []})
        b["events"] += 1
        if fl["judged"]:
            b["judged"] += 1
            b["ratios"].append(fl["ratio"])
            b["thrs"].append(fl["p80_thr"])
            if fl["extreme"]:
                b["extreme"] += 1
    for y, b in byy.items():
        b["ratio_median"] = float(np.median(b["ratios"])) if b["ratios"] else None
        b["p80_median"] = float(np.median(b["thrs"])) if b["thrs"] else None
        b.pop("ratios"), b.pop("thrs")
    res["extreme_by_year"] = byy
    # 漏斗:极端 → 确认 → 进场
    funnel: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for ev, fl in zip(evs, flags):
        if not fl["extreme"]:
            continue
        y = ev["d"][:4]
        funnel[y][0] += 1
        pan = panels.get(ev["symbol"])
        i = pan["idx"].get(ev["d"]) if pan else None
        if i is None:
            continue
        ic = find_confirmation(pan, i)
        if ic is None:
            continue
        funnel[y][1] += 1
        if ic + 1 < pan["n"]:
            funnel[y][2] += 1
    res["funnel_by_year"] = {y: {"extreme": v[0], "confirmed": v[1], "entered": v[2]}
                             for y, v in sorted(funnel.items())}
    print(f"  逐年漏斗:{json.dumps(res['funnel_by_year'], ensure_ascii=False)}", flush=True)

    # ── 判据 ──
    print("[8] 判据…", flush=True)
    V: dict = {}
    V["(a) 票数 ≥ 20"] = {"ok": len(tickets) >= 20, "value": len(tickets), "need": "≥ 20"}
    ab = res["main"].get("ab_vs_zero", {})
    p_ab = ab.get("p_b_le_a")
    V["(b) 平均净 R > 0 且 ab_test 对 0 p < 0.10"] = {
        "ok": bool(actual_avg is not None and actual_avg > 0 and (p_ab is not None and p_ab < 0.10)),
        "avg_r_net": actual_avg, "p_b_le_a": p_ab, "ab_verdict": ab.get("verdict"),
        "n_days": ab.get("n_days")}
    cm = ctrl_stats.get("main_up_days", {})
    V["(c) 随机对照:实际平均 R ≥ 对照 90 分位"] = {
        "ok": bool(cm.get("actual_ge_p90", False)), **{k: v for k, v in cm.items()}}
    if tickets:
        k = int(np.argmax([abs(t["r_net"]) for t in tickets]))
        keep = [t for i, t in enumerate(tickets) if i != k]
        rr = [t["r_net"] for t in keep]
        loo = {"dropped": {"symbol": tickets[k]["symbol"], "event_d": tickets[k]["signal_d"],
                           "r_net": tickets[k]["r_net"]},
               "n_tickets": len(keep), "avg_r_net": float(np.mean(rr)),
               "ok": bool(float(np.mean(rr)) > 0)}
    else:
        loo = {"ok": False, "avg_r_net": None}
    V["(d) 留一(|R| 最大的那张)后平均 R 仍 > 0"] = {"ok": bool(loo.get("ok")), **loo}
    ya = [t for t in tickets if PERIOD_A[0] <= int(t["signal_d"][:4]) <= PERIOD_A[1]]
    yb = [t for t in tickets if PERIOD_B[0] <= int(t["signal_d"][:4]) <= PERIOD_B[1]]
    ra = float(np.mean([t["r_net"] for t in ya])) if ya else None
    rb = float(np.mean([t["r_net"] for t in yb])) if yb else None
    same_sign = (ra is not None and rb is not None and np.sign(ra) == np.sign(rb))
    V["(e) 2020–23 与 2024–26 平均 R 同号"] = {
        "ok": bool(same_sign), "avg_2020_23": ra, "n_2020_23": len(ya),
        "avg_2024_26": rb, "n_2024_26": len(yb)}
    # 附:频率 / 最差票 / 连亏
    per_year: dict[str, int] = defaultdict(int)
    for t in tickets:
        per_year[t["signal_d"][:4]] += 1
    worst = min(tickets, key=lambda t: t["r_net"]) if tickets else None
    V["(附) 频率 / 最差票 / 最长连亏"] = {
        "ok": True,
        "tickets_per_year": dict(sorted(per_year.items())),
        "n_years_with_ticket": len(per_year),
        "max_consecutive_losses": t332.max_consec_losses(tickets),
        "worst_ticket": ({"symbol": worst["symbol"], "event_d": worst["signal_d"],
                          "r_net": worst["r_net"], "entry": worst["entry"], "exit": worst["exit"],
                          "stop": worst["stop"], "reason": worst["reason"],
                          "gapped_through_stop": bool(worst["exit"] > worst["stop"] + 1e-9)}
                         if worst else None),
        "n_gapped_through_stop": sum(1 for t in tickets
                                     if t["reason"] == "止损" and t["exit"] > t["stop"] + 1e-9),
        "median_hold_days": float(np.median([t["hold_days"] for t in tickets])) if tickets else None,
        "median_event_to_confirm_bars": float(np.median([t["event_to_confirm_bars"] for t in tickets]))
        if tickets else None,
    }
    res["verdicts"] = V
    res["tickets"] = [{k: v for k, v in t.items() if not k.startswith("_")} for t in tickets]
    res["tickets_confirm_only"] = [{k: v for k, v in t.items() if not k.startswith("_")}
                                    for t in t_conf_only]
    res["tickets_extreme_only"] = [{k: v for k, v in t.items() if not k.startswith("_")}
                                   for t in t_ext_only]

    ok_all = all(v.get("ok") for k, v in V.items() if not k.startswith("(附)"))
    res["overall"] = ("✅ 全过(可开纸面臂 short_squeeze_fail,不动钱)" if ok_all else "❌ 未全过(不立臂)")
    if len(tickets) < 20:
        res["overall"] = f"⚠️ 票数 {len(tickets)} < 20 —— 只报不判({res['overall']})"

    # ── 产物 ──
    out_json = HERE / "t334_results.json"
    out_json.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    print(f"\n写了 {out_json}", flush=True)

    csv_path = HERE / "t334_tickets.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "event_d", "confirm_d", "entry_d", "exit_d", "reason",
                    "ratio_ret_over_atr_thr", "extreme", "event_to_confirm_bars",
                    "entry", "exit", "stop", "target", "r_unit", "hold_days",
                    "r_price", "r_fund", "r_cost", "r_net", "funding_sum",
                    "gapped_through_stop"])
        for t in sorted(tickets, key=lambda x: (x["entry_d"], x["symbol"])):
            w.writerow([t["symbol"], t["signal_d"], t["confirm_d"], t["entry_d"], t["exit_d"],
                        t["reason"], round(t["ratio"], 6), int(t["extreme"]),
                        t["event_to_confirm_bars"], round(t["entry"], 10),
                        round(t["exit"], 10), round(t["stop"], 10), round(t["target"], 10),
                        round(t["r_unit"], 10), t["hold_days"], round(t["r_price"], 6),
                        round(t["r_fund"], 6), round(t["r_cost"], 6), round(t["r_net"], 6),
                        round(t["funding_sum"], 8),
                        int(t["reason"] == "止损" and t["exit"] > t["stop"] + 1e-9)])
    print(f"写了 {csv_path}", flush=True)

    md = HERE / "T-334_squeeze_fail.md"
    md.write_text(REPORT_HEADER)
    ru_frac = [t["r_unit"] / t["entry"] for t in tickets]
    L = ["", "---", "", "## 结果(脚本自动追加;完整数字见 `t334_results.json`)", "",
         f"- 极端事件 {n_extreme} / 可判 {n_judged}(共 {len(evs)} 个 squeeze 事件)→ 确认后成票 {len(tickets)}",
         f"- 票数 {len(tickets)} · 平均净 R {actual_avg:.4f} · 中位 {sum_main['median_r_net']:.4f}"
         f" · 胜率 {sum_main['win_rate']:.1%} · 总 {sum_main['total_r_net']:.2f}R",
         f"- 出场原因 {sum_main['reasons']} · 中位持有 {V['(附) 频率 / 最差票 / 最长连亏']['median_hold_days']}"
         f" 根 · 事件→确认 中位 {V['(附) 频率 / 最差票 / 最长连亏']['median_event_to_confirm_bars']} 根",
         f"- 拆分:价 {sum_main['avg_r_price']:+.4f}R · 资金费 {sum_main['avg_r_fund']:+.4f}R"
         f" · 成本 {sum_main['avg_r_cost']:+.4f}R",
         f"- 风险单位/进场价:中位 {float(np.median(ru_frac)):.3f}(止损在进场价上方多少倍)"
         f" · 最大 {max(ru_frac):.2f} ⇒ 2R 的目标价多数落在 0 以下",
         f"- 袖套 {res['main'].get('sleeve_total_return', float('nan')):.2%}"
         f" · 最大回撤 {res['main'].get('sleeve_max_dd', float('nan')):.2%}"
         f" · ab p(b≤0)={p_ab}",
         f"- 流程:非极端 {st_main['drop_reasons'].get('非极端', 0)} · 历史不足 30 个不判 "
         f"{st_main['drop_reasons'].get('极端:历史不足30', 0)} · 未确认 {st_main['n_unconfirmed']}"
         f" · 作废 {st_main['n_dropped']} · 同一币不叠加跳过 {st_main['n_stack_skipped']}",
         f"- 只报·只加确认(全部事件):票 {len(t_conf_only)} · 平均净 R {sum_conf['avg_r_net']:.4f}"
         f" · 中位 {sum_conf['median_r_net']:.4f} · 胜率 {sum_conf['win_rate']:.1%}"
         f" · 对照分位 {ctrl_conf.get('null_pctl_of_actual')}",
         f"- 只报·只加极端(S-808 原机械):票 {len(t_ext_only)} · 平均净 R {sum_ext['avg_r_net']:.4f}"
         f" · 中位 {sum_ext['median_r_net']:.4f} · 胜率 {sum_ext['win_rate']:.1%}",
         f"- 敏感度·套 S-808 数据卫生带:票 {len(tickets_h)} · 平均净 R {sum_h['avg_r_net']:.4f}"
         f" · 对照分位 {res['sensitivity_hygiene_band']['control'].get('null_pctl_of_actual')}",
         f"- 每年票数(频率):{V['(附) 频率 / 最差票 / 最长连亏']['tickets_per_year']}", "",
         "### 逐年漏斗(极端 → 确认 → 进场)", "",
         "| 年 | squeeze 事件 | 可判 | 极端 | 确认 | 进场 | 极端 ratio 中位 | p80 阈值中位 |",
         "|---|---|---|---|---|---|---|---|"]
    for y, b in sorted(res["extreme_by_year"].items()):
        fu = res["funnel_by_year"].get(y, {})
        L.append(f"| {y} | {b['events']} | {b['judged']} | {b['extreme']} | {fu.get('confirmed', 0)}"
                 f" | {fu.get('entered', 0)} | {b['ratio_median']:.3f} | {b['p80_median']:.3f} |"
                 if b["ratio_median"] is not None else
                 f"| {y} | {b['events']} | {b['judged']} | {b['extreme']} | 0 | 0 | — | — |")
    L += ["", "### 逐票表", "",
          "见 `t334_tickets.csv`(逐票:事件日 / 确认日 / 进场日 / 出场日 / 出场原因 / 风险单位 / R 拆分)。", ""]
    for k, v in V.items():
        L.append(f"- **{k}** ⇒ {'✅' if v.get('ok') else '❌'} "
                 f"`{json.dumps(v, ensure_ascii=False, default=str)[:600]}`")
    L += ["", f"**总判:{res['overall']}**", ""]
    md.write_text(md.read_text() + "\n".join(L))
    print(json.dumps({"summary": sum_main, "verdicts": V, "overall": res["overall"]},
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
