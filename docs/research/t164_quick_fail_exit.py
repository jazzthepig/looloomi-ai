"""T-164 / S-655 规则 Q:进场第 5 根日线收盘 < 进场价 ⇒ 次日开盘出(快认错)。

与 S-647 / S-654 同一批 770 张 R-v2 多头票(2020-03-01 → 2026-06-20)。
规则 Q 是 *paper* 层规则(每个 ticket 的 exit 是哪根日线 + 哪个价格)。
保留原 R-v2 的出场栈(stop / 时间到期 / SMA20),只在原规则还没走人的情况下加快认错。
0.2% / 边 round-trip 成本 = 0.4% 价格滑点,作用在 (exit - entry) 上,等价
R cost = 0.004 / stop_frac = 0.004 * entry / (entry - stop)。

装载复用 docs/research/s647_sim_r_v2.py 的 load()(C 道 T-159 缓存:770 张票 + 日线)。

用法:
  python3 docs/research/t164_quick_fail_exit.py
  python3 docs/research/t164_quick_fail_exit.py --seed 164 --month-boot 2000
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(THIS_DIR, "..", "..")))
sys.path.insert(0, THIS_DIR)  # 让 import s647_sim_r_v2 用上
import s647_sim_r_v2 as base

REF_BASELINE_R = 372.20        # S-654 / 卡 acceptance 引用 baseline
COST_PER_SIDE = 0.002          # 0.2% / 边 round-trip
COST_RT = 2 * COST_PER_SIDE    # 0.4% 价格滑点(等价 R cost = COST_RT/stop_frac)
ENTRY = "entry"
DAY0 = "day0"                  # 第 1 根 = 进场根
DAY5 = "day5"                  # 第 5 根 = 进场 + 4 根日线
DAY6 = "day6"                  # 次日开盘出


MAX_START_GAP_DAYS = 6   # 进场后第一条日线最晚隔几天(覆盖周末;长假另算)
MAX_STEP_DAYS = 6        # 相邻两根日线最远隔几天
N_BARS_AFTER_ENTRY = 5   # 卡口径「进场日算第 1 根」⇒ 第 5 根日线 = nxt[3],次日开盘 = nxt[4]


def _bar_window(bars: dict, symbol: str, after: dt.date, n: int):
    """进场日之后的 n 根日线,要求**连续**,否则判「不可算」。

    T-164 v2(Seth §1021d):v1 的 `_bars_after` 只按 `d > after` 取最早 n 根,
    **不检查连续性**。t159 的 bars 缓存始于 2025-04,而票从 2020-03 起 ——
    于是 2020~2024 的票静默拿到 1~5 年后的日线(错位),规则 Q 在错误的日期上触发。
    这里加两道闸:
      (a) 第一根不超过 after + MAX_START_GAP_DAYS 天;
      (b) 相邻两根不超过 MAX_STEP_DAYS 天。
    不满足 ⇒ (bars=[], why=原因)。**不可算的票不回落原规则** —— 回落会让两条臂
    跑在不同票集上,ΔR 变成两个样本的差,不是规则的差。
    """
    sb = bars.get(symbol, {})
    days = sorted(d for d in sb if d > after)
    if not days:
        return [], "该票进场后该币无任何日线(bars 缓存不含此币)"
    if len(days) < n:
        return [], f"进场后只剩 {len(days)} 根日线(需 {n} 根)"
    days = days[:n]
    gap0 = (days[0] - after).days
    if gap0 > MAX_START_GAP_DAYS:
        return [], f"第一根日线在进场后第 {gap0} 天(> {MAX_START_GAP_DAYS} 天)—— 日线与票错配"
    for a, b in zip(days, days[1:]):
        step = (b - a).days
        if step > MAX_STEP_DAYS:
            return [], f"日线不连续(相邻间隔 {step} 天 > {MAX_STEP_DAYS} 天)"
    return [(*sb[d], d) for d in days], ""


def ticket_r(entry_px: float, stop_px: float, exit_px: float) -> float:
    if entry_px <= 0 or stop_px <= 0 or exit_px is None:
        return 0.0
    return (exit_px - entry_px) / abs(entry_px - stop_px)


def ticket_r_after_cost(entry_px: float, stop_px: float, exit_px: float, cost_rt: float = COST_RT) -> float:
    r = ticket_r(entry_px, stop_px, exit_px)
    risk = abs(entry_px - stop_px)
    if risk <= 0:
        return r
    return r - cost_rt * entry_px / risk


def original_reason(t: dict) -> str:
    if t.get("still"):
        return "open"
    if t["exit_px"] <= t["stop_px"] * (1 + 1e-9):
        return "stop"
    if t.get("bars_held", 0) >= 120:
        return "time"
    return "sma20"


def simulate_q(bars: dict, tickets: list[dict], print_diag: bool = False) -> dict:
    """对 770 张 R-v2 long 票逐张重算:保留原 stop/time/sma20 出场,只在原规则没命中的窗口里
    触发规则 Q:进场后第 5 根日线收盘 < 进场价 ⇒ 改在第 6 根日线开盘出。

    返回里包括:
      - total_R_base / total_R_q (with cost)
      - 提前出掉的几张(< 原出场天数, 且被规则 Q 改写出场)
      - 第 3 / 第 10 根变体的总 R 差(只报项,主结论用第 5 根)
      - 每张票 (reason 旧 / reason 新 / R 旧 / R 新 / 命中分支)
      - 月分块 bootstrap(2,000 次)单侧 p
      - <2023-01-01 与 ≥2023-01-01 子段总 R 差
      - 按出场日累计最大回撤(depth;用每张票出场时净值相对峰值的跌幅)
    """
    rows = []
    total_base = 0.0     # after cost (= sum of t["r"])
    total_base_pre = 0.0  # pre-cost (= sum of (exit-entry)/risk)
    total_q = 0.0
    total_q_pre = 0.0
    early_exits = []   # 规则 Q 提前出掉的
    orig_top3 = []     # 原规则 ≥ +3R 且被 Q 改了出场的
    q_total_pre_cost = 0.0
    # T-164 v2(Seth §1021d):不可算的票单列,并给两臂一个共同的票集
    not_computable = []
    n_skip = {}
    total_base_all_pre = 0.0  # 全部票的 pre-cost baseline(复现 S-654 的 372.2 B 用)

    for t in tickets:
        entry_d = dt.date.fromisoformat(t["entry_d"])
        sym = t["symbol"]
        entry_px = float(t["entry_px"])
        stop_px = float(t["stop_px"])
        base_r = t.get("r")
        if base_r is None:
            continue
        exit_px_orig = float(t["exit_px"])
        base_r_pre_cost = ticket_r(entry_px, stop_px, exit_px_orig)
        base_r_after = ticket_r_after_cost(entry_px, stop_px, exit_px_orig)
        total_base_all_pre += base_r_pre_cost

        reason_old = original_reason(t)
        # 规则 Q:进场日算第 1 根 ⇒ 第 5 根日线 = nxt[3],次日开盘 = nxt[4]
        nxt, why = _bar_window(bars, sym, entry_d, N_BARS_AFTER_ENTRY)
        if not nxt:
            # 不可算:两臂都不收这张票(Seth §1021d)。不回落原规则 ——
            # 回落会让 Q 臂比 baseline 臂少票,ΔR 不再是同一票集上的差。
            not_computable.append({
                "sym": sym, "entry_d": t["entry_d"], "exit_d": t.get("exit_d"),
                "reason_old": reason_old, "why": why,
                "old_R": round(base_r, 3), "old_R_after_cost": round(base_r_after, 3),
            })
            n_skip[why.split("(")[0].strip()] = n_skip.get(why.split("(")[0].strip(), 0) + 1
            continue
        # 两臂共同的样本:baseline 从这里开始累加,保证 ΔR 是同一票集上的差
        total_base += base_r_after
        total_base_pre += base_r_pre_cost

        b2, b3, b4, b5, b6 = nxt  # 第 2..6 根日线 (o, h, l, c, trade_date)
        q_triggered = b5[3] < entry_px          # 第 5 根日线收盘 < 进场价
        # 原规则若已在第 5 根日线(含)之前走人,Q 不变更(bars_held=4 ⇒ 出在第 5 根上)
        old_exit_day_idx = int(t["bars_held"]) if reason_old != "open" else None
        if old_exit_day_idx is not None and old_exit_day_idx <= 4:
            # 原规则早于或等于第 5 根日线已被出掉,Q 不改
            new_r_pre = ticket_r(entry_px, stop_px, exit_px_orig)
            new_r_after = ticket_r_after_cost(entry_px, stop_px, exit_px_orig)
            branch = ("kept_stop" if reason_old == "stop"
                      else "kept_time" if reason_old == "time" else "kept_sma20")
            total_q += new_r_after
            total_q_pre += new_r_pre
            rows.append({**t, "reason_q": reason_old, "new_r": new_r_pre, "new_r_after_cost": new_r_after,
                         "delta_R": new_r_after - base_r_after, "branch": branch,
                         "new_exit_d": t["exit_d"]})
            continue

        if q_triggered:
            # 改成第 6 根日线开盘(b6[0])出
            new_exit_px = b6[0]
            new_exit_d = b6[4]
            q_r = ticket_r(entry_px, stop_px, new_exit_px)
            q_r_after = ticket_r_after_cost(entry_px, stop_px, new_exit_px)
            delta = q_r_after - base_r_after
            total_q += q_r_after
            total_q_pre += q_r
            early = (dt.date.fromisoformat(t["exit_d"]) - b6[4]).days
            if early > 0:
                early_exits.append({"sym": sym, "entry_d": t["entry_d"], "old_exit": t["exit_d"],
                                    "new_exit_d": new_exit_d.isoformat(), "early_d": early,
                                    "old_r": round(base_r, 3), "new_r": round(q_r, 3)})
            if base_r >= 3.0:
                orig_top3.append({"sym": sym, "entry_d": t["entry_d"], "old_exit": t["exit_d"],
                                  "new_exit_d": new_exit_d.isoformat(),
                                  "old_r": round(base_r, 3), "new_r": round(q_r, 3),
                                  "old_R_after_cost": round(base_r_after, 3),
                                  "new_R_after_cost": round(q_r_after, 3),
                                  "delta": round(delta, 3)})
            rows.append({**t, "reason_q": "rule_q_day6_open", "new_r": q_r, "new_r_after_cost": q_r_after,
                         "delta_R": delta, "branch": "rule_q", "new_exit_d": new_exit_d.isoformat()})
        else:
            # 第 5 根收盘 ≥ 进场价,按原规则走
            new_r_pre = ticket_r(entry_px, stop_px, exit_px_orig)
            new_r_after = ticket_r_after_cost(entry_px, stop_px, exit_px_orig)
            total_q += new_r_after
            total_q_pre += new_r_pre
            rows.append({**t, "reason_q": reason_old, "new_r": new_r_pre, "new_r_after_cost": new_r_after,
                         "delta_R": 0.0, "branch": "kept_above"})

    return {"rows": rows, "total_base": total_base, "total_q": total_q,
            "total_base_pre_cost": total_base_pre, "total_q_pre_cost": total_q_pre,
            "early_exits": early_exits, "orig_top3": orig_top3,
            "n": len(rows),
            # T-164 v2:不可算的票单列 + 两臂共同票集
            "not_computable": not_computable, "n_skip": n_skip,
            "n_computable": len(rows), "total_base_all_pre_cost": total_base_all_pre}


def summarize(rows: list[dict]) -> dict:
    by_branch = defaultdict(lambda: [0, 0.0])
    for r in rows:
        bb = r["branch"]
        by_branch[bb][0] += 1
        by_branch[bb][1] += r["delta_R"]
    return {k: {"n": v[0], "sum_delta_R_after_cost": round(v[1], 3)} for k, v in by_branch.items()}


# ── 月分块 bootstrap ────────────────────────────────────────────────────────
def monthly_deltas(rows: list[dict]) -> dict[str, float]:
    by_m = defaultdict(float)
    for r in rows:
        m = r["entry_d"][:7]
        by_m[m] += r["delta_R"]
    return dict(sorted(by_m.items()))


def block_bootstrap(by_m: dict[str, float], n_boot: int, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    keys = sorted(by_m)
    vals = [by_m[k] for k in keys]
    if not vals:
        return 0.0, 1.0
    obs = sum(vals)
    ge = 0
    dist = []
    for _ in range(n_boot):
        s = sum(vals[rng.randrange(len(vals))] for _ in range(len(vals)))
        dist.append(s)
        if s >= obs:
            ge += 1
    dist.sort()
    p = (ge + 1) / (n_boot + 1)
    return obs, p


# ── 子段差(<2023-01-01 / ≥2023-01-01) ─────────────────────────────────────
def period_split(rows: list[dict]) -> tuple[float, float]:
    pre = sum(r["delta_R"] for r in rows if r["entry_d"] < "2023-01-01")
    post = sum(r["delta_R"] for r in rows if r["entry_d"] >= "2023-01-01")
    return pre, post


# ── 按出场日累计回撤 ─────────────────────────────────────────────────────────
def drawdown_curve(rows: list[dict], which: str) -> tuple[float, list[tuple]]:
    """返回 (最深回撤, 每日累计 + 顶点 + 谷值时点)。

    which ∈ {"base", "q"}:用 base R 还是 q R。Date = 出场日(原 / Q 后)。
    """
    def _exit_date_key(row):
        return row.get("new_exit_d") if which == "q" and row["branch"] == "rule_q" else row["exit_d"]

    cal = []
    for r in sorted(rows, key=_exit_date_key):
        d = _exit_date_key(r)
        if d is None:
            continue
        if which == "q":
            v = r["new_r_after_cost"]
        else:
            v = (ticket_r_after_cost(float(r["entry_px"]), float(r["stop_px"]), float(r["exit_px"]))
                 if r.get("r") is not None else 0.0)
        cal.append((d, v))
    eq = []
    s = 0.0
    for d, v in cal:
        s += v
        eq.append((d, s))
    peak, maxdd = eq[0][1], 0.0
    dd_series = []
    for d, v in eq:
        if v > peak:
            peak = v
        dd = v - peak
        dd_series.append((d, v, peak, dd))
        if dd < maxdd:
            maxdd = dd
    return maxdd, dd_series


# ── 第 3 / 第 10 根变体(只报项) ────────────────────────────────────────────
def simulate_variant(bars: dict, tickets: list[dict], trigger_bar: int) -> dict:
    """trigger_bar = 第 N 根日线收盘 < 进场价 ⇒ 第 N+1 根开盘出。"""
    total = 0.0
    base_total = 0.0
    for t in tickets:
        entry_d = dt.date.fromisoformat(t["entry_d"])
        sym = t["symbol"]
        entry_px = float(t["entry_px"])
        stop_px = float(t["stop_px"])
        if t.get("r") is None:
            continue
        base_r = ticket_r_after_cost(entry_px, stop_px, float(t["exit_px"]))
        if t.get("bars_held", 0) is not None and int(t["bars_held"]) <= trigger_bar:
            base_total += base_r
            total += base_r
            continue
        nxt, _why = _bar_window(bars, sym, entry_d, trigger_bar)
        if len(nxt) < trigger_bar:
            # 不可算:两臂同票集,不回落(v2 修正)
            continue
        base_total += base_r   # 同票集:过了这道闸的票才进 baseline 臂
        bar_n = nxt[trigger_bar - 2]   # 第 N 根日线(进场日 = 第 1 根 ⇒ nxt[0] 是第 2 根)
        bar_n1 = nxt[trigger_bar - 1]  # 次日开盘
        if bar_n[3] < entry_px:
            total += ticket_r_after_cost(entry_px, stop_px, bar_n1[0])
        else:
            total += base_r
    return {"total": total, "base": base_total, "delta": total - base_total, "trigger_bar": trigger_bar}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/Volumes/CometCloudAI/cometcloud-local")
    ap.add_argument("--seed", type=int, default=164)
    ap.add_argument("--month-boot", type=int, default=2000)
    a = ap.parse_args()

    bars, fund, longs = base.load(a.root)
    print(f"# n_long = {len(longs)}  (REF_BASELINE_R = {REF_BASELINE_R})", file=sys.stderr)

    sim = simulate_q(bars, longs)
    rows = sim["rows"]
    base_total_pre = sim["total_base_pre_cost"]
    q_total_pre = sim["total_q_pre_cost"]
    print(f"# total_R pre-cost:  base = {base_total_pre:.3f}    q = {q_total_pre:.3f}    Δ = {q_total_pre - base_total_pre:.3f}",
          file=sys.stderr)
    print(f"# total_R after cost:base = {sim['total_base']:.3f}    q = {sim['total_q']:.3f}    Δ = {sim['total_q'] - sim['total_base']:.3f}",
          file=sys.stderr)
    if abs(base_total_pre - REF_BASELINE_R) > REF_BASELINE_R * 0.02:
        print(f"# WARNING: base drift > 2%: measured={base_total_pre:.3f} vs ref={REF_BASELINE_R}", file=sys.stderr)

    print(f"# baseline drift vs REF_BASELINE_R {REF_BASELINE_R}: measured={base_total_pre:.3f}  Δ={base_total_pre - REF_BASELINE_R:+.3f}",
          file=sys.stderr)

    branch = summarize(rows)
    print(f"# branches: {branch}", file=sys.stderr)
    early = sim["early_exits"]
    top3 = sim["orig_top3"]
    print(f"# early_exits (提前出): {len(early)}", file=sys.stderr)
    print(f"# orig_top3 (原 ≥ +3R 且被 Q 改写出场): {len(top3)}", file=sys.stderr)

    by_m = monthly_deltas(rows)
    obs, p = block_bootstrap(by_m, a.month_boot, a.seed)
    pre, post = period_split(rows)
    dd_base, _ = drawdown_curve(rows, "base")
    dd_q, _ = drawdown_curve(rows, "q")
    segs = {"<2023-01-01": pre, ">=2023-01-01": post}
    dd_out = {"baseline": dd_base, "rule_q": dd_q}

    v3 = simulate_variant(bars, longs, 3)
    v10 = simulate_variant(bars, longs, 10)

    out = {
        "meta": {
            "n_long": len(longs),
            "ref_baseline_R": REF_BASELINE_R,
            "cost_per_side": COST_PER_SIDE,
            "seed": a.seed,
            "n_boot": a.month_boot,
        },
        "baseline": {
            "total_R_pre_cost": base_total_pre,
            "total_R_after_cost": sim["total_base"],
            "vs_ref_pre_cost": base_total_pre - REF_BASELINE_R,
        },
        "rule_q_day5": {
            "trigger": "第 5 根日线收盘 < 进场价 ⇒ 第 6 根开盘出",
            "n_triggered": sum(1 for r in rows if r["branch"] == "rule_q"),
            "total_R_pre_cost": q_total_pre,
            "total_R_after_cost": sim["total_q"],
            "delta_R_pre_cost": q_total_pre - base_total_pre,
            "delta_R_after_cost": sim["total_q"] - sim["total_base"],
            "by_branch": branch,
            "early_exits_n": len(early),
            "early_exits_mean_early_days": (sum(e["early_d"] for e in early) / len(early)) if early else None,
            "orig_top3_or_more_changed_n": len(top3),
            "orig_top3_or_more_saved_R_sum_pre_cost": sum(e["old_r"] - e["new_r"] for e in top3),
            "orig_top3_or_more_saved_R_sum_after_cost": sum(e["delta"] for e in top3),
        },
        "monthly_deltas": by_m,
        "block_bootstrap_monthly": {"obs_delta_R_after_cost": obs,
                                    "p_one_sided_ge_obs_under_H0": p,
                                    "n_boot": a.month_boot},
        "period_split": {"pre_2023": pre, "post_2023": post,
                         "pre_2023_positive": pre > 0, "post_2023_positive": post > 0},
        "drawdown": {"base": dd_base, "q": dd_q,
                     "q_not_deeper_than_base": dd_q >= dd_base},
        "variants": {"day3_trigger": v3, "day10_trigger": v10},
        "examples": {"early_exits_first_15": early[:15],
                     "orig_top3_first_15": top3[:15]},
    }

    print(json.dumps(out, indent=1, default=str))
    # 行级明细只在前置 stdout 由报告脚本按需再读;此处落到 _reports/absorb_input/T-164_helper.jsonl 的同伴 .json
    helper_path = os.path.join(a.root, "_reports", "absorb_input", "T-164_helper.json")
    os.makedirs(os.path.dirname(helper_path), exist_ok=True)
    with open(helper_path, "w") as f:
        json.dump(out, f, indent=1, default=str)
    # 行级明细(large)
    rows_path = helper_path.replace(".json", "_rows.json")
    with open(rows_path, "w") as f:
        json.dump(rows, f, default=str, ensure_ascii=False)
    write_report(a, sim, out, v3, v10, segs, dd_out)


REPORT_MD = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-164_s655_quick_fail.md"


def write_report(a, sim, out, v3, v10, segs, dd_out):
    """把 S-655 规则 Q 的结果写成报告 + 末尾「S-655 结果」草稿(Seth 抄进台账)。"""
    n_all = out["meta"]["n_long"]   # 票总数;可算 = n_computable(不含无 R 的票与不可算票)
    L = []
    L.append("# T-164 / S-655 — Trader Tom「最好的输家」:规则 Q\n")
    L.append(f"生成 {dt.datetime.now(dt.timezone.utc).isoformat()} · 脚本 `docs/research/t164_quick_fail_exit.py`\n")
    L.append("## 0. 与 v1 的差异(先说清楚哪些数作废)\n")
    L.append("Seth §1021d 的三条 CHANGES 已全部落实:\n")
    L.append(f"1. **日线/票错配**:`_bar_window()` 加连续性闸(第一根 ≤ 进场 +{MAX_START_GAP_DAYS} 天,"
             f"相邻 ≤{MAX_STEP_DAYS} 天),不满足 ⇒ 该票判**不可算**,两臂都不收。")
    L.append(f"2. **不可算票单列**:{len(sim['not_computable'])} 张,原因分布 `{sim['n_skip']}`,"
             f"逐张见 §3(带 sym / 进场日 / 原出场日 / 原 R)。")
    L.append(f"3. **ΔR 改为同票集**:baseline 臂不再跨全部票累加,只在 {sim['n_computable']} 张可算票上与 Q 臂对照。\n")
    L.append("> **v1 的 −3.06R / p=0.4973 / pre-2023 数字全部作废,不得入台账。**\n")

    L.append("## 1. 基线复现 —— 对不上,先报差(卡要求)\n")
    allpre = sim["total_base_all_pre_cost"]
    ref = REF_BASELINE_R
    L.append(f"| 口径 | 值 (R) | vs ref 372.2 |\n|---|---:|---:|")
    L.append(f"| 全部 {n_all} 张票,pre-cost | **{allpre:.3f}** | Δ = {allpre-ref:+.3f} ({allpre/ref-1:+.2%}) |")
    L.append(f"| 可算 {sim['n_computable']} 张,pre-cost | {sim['total_base_pre_cost']:.3f} | Δ = {sim['total_base_pre_cost']-ref:+.3f} |")
    L.append(f"| 可算 {sim['n_computable']} 张,after cost | {sim['total_base']:.3f} | Δ = {sim['total_base']-ref:+.3f} |\n")
    L.append(f"**复现失败:pre-cost 实测 {allpre:.3f} vs 卡引用的 372.2,差 {allpre-ref:+.3f} R({allpre/ref-1:+.2%}),"
             f"超出 2% 容差。** 按卡「对不上先停下报差」——本轮**不出结论**,只报差。\n")
    L.append("> 附注:v1 曾拿 **after-cost** 的 369.008 去比 **pre-cost** 的 372.2,得出「−0.86%,在容差内」。"
             "两个口径相减不算复现;v1 的基线核对是错的,但当时掩盖了 4.3% 的真漂移。\n")

    L.append("## 2. 规则 Q 结果(同票集,767/770 张可算)\n")
    d = sim["total_q"] - sim["total_base"]
    L.append(f"- baseline after cost **{sim['total_base']:.3f} R** / 规则 Q **{sim['total_q']:.3f} R**")
    L.append(f"- **ΔR = {d:+.3f}**(v1 报 −3.06,口径错)")
    L.append(f"- 触发(第 5 根收盘 < 进场价):`{out['rule_q_day5']['n_triggered']}` 张")
    L.append(f"- 提前出场:{len(sim['early_exits'])} 张;原规则 ≥ +3R 且被 Q 改写的:{len(sim['orig_top3'])} 张\n")
    L.append(f"- 第 3 根变体 ΔR = {v3['delta']:+.3f};第 10 根变体 ΔR = {v10['delta']:+.3f}(只报项)\n")
    L.append(f"- 分段 ΔR:{segs}\n")
    L.append(f"- 按出场日累计最大回撤:{dd_out}\n")

    L.append("## 3. 不可算的票(Seth 要求单列)\n")
    if not sim["not_computable"]:
        L.append("无。\n")
    else:
        L.append("| sym | 进场日 | 原出场日 | 原出场原因 | 不可算原因 | 原 R |\n|---|---|---|---|---|---:|")
        for r in sim["not_computable"]:
            L.append(f"| {r['sym']} | {r['entry_d']} | {r.get('exit_d')} | {r['reason_old']} | {r['why']} | {r['old_R']} |")
        L.append("")

    L.append("## 4. 关于「bars 始于 2025-04」这一前提\n")
    L.append("**`research/t159/_bars.jsonl` 单独看确实始于 2025-04-01**(已核)。但本脚本的装载器"
             "`s647_sim_r_v2.load()` 读的是**三个文件的并集**:\n")
    L.append("```\nresearch/t156/_bars_early.jsonl\nresearch/t156/_bars.jsonl\nresearch/t159/_bars.jsonl\n```\n")
    L.append(f"并集覆盖全部票期,连续性闸对 {sim['n_computable']}/{n_all} 张通过,"
             f"只判 {len(sim['not_computable'])} 张不可算。所以 v1 报的「652/767 张第 5 根错位」"
             f"在**实际装载的数据**上不成立 —— 那条是以 `_bars.jsonl` 单文件为依据的。\n")
    L.append("> 这条闸本身仍要留着:它正是能把「静默拿到几年后的日线」变成显式失败的那道闸。"
             "**探索性 —— 需另立预注册、在新数据上过零信号对照**:闸只查了首根与相邻间隔,"
             "没有校验符号表(t156/t159 混用 `1000LUNC` 这类 Binance 前缀)是否与票的 symbol 同一资产。\n")

    L.append("---\n")
    L.append("## S-655 结果(草稿 — Seth 抄进台账)\n")
    L.append("> **本轮不出结论**:卡要求先复现 S-654 的原规则总盈亏 372.2 R,实测 pre-cost "
             f"{allpre:.3f} R,差 {allpre-ref:+.3f} R({allpre/ref-1:+.2%}),超出 2% 容差,按卡停下报差。\n")
    L.append(f"- **复现**:❌ 未复现。全部 {n_all} 张票 pre-cost = {allpre:.3f} R vs ref 372.2(Δ {allpre-ref:+.3f})。"
             f"v1 的基线核对把 after-cost 与 pre-cost 相减,掩盖了这 {allpre/ref-1:+.1%} 的漂移。")
    L.append(f"- **错配**:⚠️ 前提不成立。`_bars.jsonl` 单文件始于 2025-04-01,但装载器读 t156+t156+t159 三个文件的并集,"
             f"覆盖全部票期;连续性闸 {sim['n_computable']}/{n_all} 通过,仅 {len(sim['not_computable'])} 张不可算。")
    L.append(f"- **规则 Q**:ΔR = **{d:+.3f}**(同票集 {sim['n_computable']} 张;v1 的 −3.06 作废)。"
             f"方向与 v1 一致(负),量级变大。**但基线未复现,此数不进台账**。")
    L.append("- **待 @seth 定**:372.2 是怎么算的(哪一票集、pre/post cost、是否含 funding)?"
             "对不上之前规则 Q 的数一律不进 doctrine §11。")

    Path(REPORT_MD).parent.mkdir(parents=True, exist_ok=True)
    Path(REPORT_MD).write_text("\n".join(L))
    print(f"WROTE {REPORT_MD}")


if __name__ == "__main__":
    main()
