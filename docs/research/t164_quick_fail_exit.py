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


def _bars_after(bars: dict, symbol: str, after: dt.date, n: int) -> list[tuple]:
    """从 after 之后第一条日线开始,顺序取 n 根日线(含 entry_d 当天则用 prev close 替补)。"""
    sb = bars.get(symbol, {})
    days = sorted(d for d in sb if d > after)[:n]
    return [(*sb[d], d) for d in days]


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
        total_base_pre += base_r_pre_cost
        total_base += base_r_after

        reason_old = original_reason(t)
        # 规则 Q:取进场后 5 根日线 + 第 6 根开盘
        nxt = _bars_after(bars, sym, entry_d, 6)
        if len(nxt) < 6:
            # 数据不足,保持原规则
            total_q += base_r_after
            total_q_pre += base_r_pre_cost
            rows.append({**t, "reason_q": reason_old, "new_r": base_r_pre_cost, "new_r_after_cost": base_r_after,
                         "delta_R": 0.0, "branch": "no_bar"})
            continue

        b1, b2, b3, b4, b5, b6 = nxt  # (o, h, l, c, trade_date)
        q_triggered = b5[3] < entry_px          # 第 5 根日线收盘 < 进场价
        # 若原规则已经在第 6 根(含)之前走人,规则 Q 不变更
        old_exit_day_idx = int(t["bars_held"]) if reason_old != "open" else None
        if old_exit_day_idx is not None and old_exit_day_idx <= 5:
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
            "n": len(rows)}


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
        base_total += base_r
        if t.get("bars_held", 0) is not None and int(t["bars_held"]) <= trigger_bar:
            total += base_r
            continue
        nxt = _bars_after(bars, sym, entry_d, trigger_bar + 1)
        if len(nxt) < trigger_bar + 1:
            total += base_r
            continue
        bar_n = nxt[trigger_bar - 1]
        bar_n1 = nxt[trigger_bar] if len(nxt) > trigger_bar else None
        if bar_n[3] < entry_px and bar_n1 is not None:
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


if __name__ == "__main__":
    main()
