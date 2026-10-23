#!/usr/bin/env python3
"""
T-189 — S-677 独立复现(A 道):R-v2 规则在 2018-01 → 2020-02(Binance 全部 USDT 现货对)的票。

规则来源(只此两处,不看 Seth 的任何脚本):
  1) docs/research/r_v2_tickets.sql(台账 S-677 规则原文)
  2) 台账 S-677 预注册原文 + 卡 T-189 acceptance 里写死的规则描述

数据(只读,Mac 数据根):
  research/s677/_bv_daily.jsonl   145 个 USDT 对, bars = [d, o, h, l, c, dv]
  research/s677/_gate_proxy.json  闸门代理 runs(start, end, open)—— open=false 的日子不出信号

输出:
  docs/research/t189_tickets.csv        票表(symbol, signal_d, entry_d, exit_d, entry_px, stop_px, exit_px, r, still)
  <Mac 数据根>/_reports/absorb_input/T-189_s677_tickets.json  逐张明细 + 判据余量(供两份实现对票)

不做任何判定(票数 < 30 只报不判,是 Seth 对完两份之后的事)。

跑法:  python3 docs/research/t189_s677_replicate.py
"""
from __future__ import annotations

import csv
import json
import os
import sys

import numpy as np

# ---------------------------------------------------------------- 常数(全部来自规则原文)
DATA_ROOT = "/Volumes/CometCloudAI/cometcloud-local"
BARS_PATH = os.path.join(DATA_ROOT, "research/s677/_bv_daily.jsonl")
GATE_PATH = os.path.join(DATA_ROOT, "research/s677/_gate_proxy.json")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV_OUT = os.path.join(REPO_ROOT, "docs/research/t189_tickets.csv")
JSON_OUT = os.path.join(DATA_ROOT, "_reports/absorb_input/T-189_s677_tickets.json")

SIG_FROM = "2018-01-01"   # 信号窗口(S-677 预注册:2017-08 起的数据只作 220 根预热)
SIG_TO = "2020-02-29"
MIN_RN = 220              # rn >= 220
ADV30_MIN = 5e6           # adv30(含当天 30 根)>= $5M
MINDD120_MAX = 0.5        # mindd120 <= 0.5
RANGE40_MAX = 0.40       # (前 40 根最高 high - 前 40 根最低 low)/前 40 根最高 <= 0.40
DV_MULT = 2.0            # 当天 dv >= 2 * 前 40 根 dv 均值
ATR_MULT = 2.5           # 止损 = 进场 - 2.5 * ATR14(信号日)
COST = 0.004             # 成本 0.4%
MAX_HOLD = 120           # 120 根到期按收盘

# 窗口口径(来自 SQL 的 frame 写法;做敏感性测试时可改):
#   dd 的分母 = `max(c) over (rows between 365 preceding and current row)` => 含当天共 366 根
#   mindd120  = `min(dd) over (rows between 120 preceding and current row)` => 含当天共 121 个 dd
# 卡 T-189 的中文复述写的是「前 365 根含当天」「120 根含当天」(=365 / 120 个),
# 与 SQL 的 366 / 121 差一根。两者都能跑,敏感性测试见 t189_s677_sensitivity.py。
DD_WINDOW = 366
MINDD_WINDOW = 121
# 同币不叠票:SQL `t.ei > rec.xi` = 新票进场根必须严格晚于上一张的出场根
OVERLAP_STRICT = True


# ---------------------------------------------------------------- 工具
def roll_mean(x: np.ndarray, window: int) -> np.ndarray:
    """SQL `avg(x) over (order by rn rows between N-1 preceding and current row)`,
    帧在分区开头被裁剪(Postgres 语义):前不满 N-1 根时用现有全部。"""
    c = np.concatenate(([0.0], np.cumsum(x, dtype=float)))
    n = len(x)
    lo = np.maximum(0, np.arange(n) - (window - 1))
    return (c[np.arange(n) + 1] - c[lo]) / (np.arange(n) + 1 - lo)


def roll_max(x: np.ndarray, window: int) -> np.ndarray:
    """SQL `max(x) over (... rows between N preceding and current row)` —— 含当天 N+1 根。"""
    n = len(x)
    out = np.empty(n, dtype=float)
    for i in range(n):
        out[i] = x[max(0, i - window + 1): i + 1].max()
    return out


def roll_min(x: np.ndarray, window: int) -> np.ndarray:
    n = len(x)
    out = np.empty(n, dtype=float)
    for i in range(n):
        out[i] = x[max(0, i - window + 1): i + 1].min()
    return out


def roll_prev(x: np.ndarray, window: int) -> np.ndarray:
    """SQL `avg(x) over (... rows between N preceding and 1 preceding)` —— 不含当天。"""
    n = len(x)
    out = np.full(n, np.nan, dtype=float)
    for i in range(1, n):
        out[i] = x[max(0, i - window): i].mean()
    return out


def roll_max_prev(x: np.ndarray, window: int) -> np.ndarray:
    n = len(x)
    out = np.full(n, np.nan, dtype=float)
    for i in range(1, n):
        out[i] = x[max(0, i - window): i].max()
    return out


def roll_min_prev(x: np.ndarray, window: int) -> np.ndarray:
    n = len(x)
    out = np.full(n, np.nan, dtype=float)
    for i in range(1, n):
        out[i] = x[max(0, i - window): i].min()
    return out


# ---------------------------------------------------------------- 闸门
def load_gate() -> list[tuple[str, str, bool]]:
    with open(GATE_PATH) as fh:
        raw = json.load(fh)
    runs = []
    for r in raw["runs"]:
        runs.append((r["start"], r["end"], bool(r["open"])))
    return runs


def gate_open(runs, d: str) -> bool:
    """SQL: `coalesce(g.gate_open, true)` —— 没有闸门行 ⇒ 当开。"""
    for start, end, is_open in runs:
        if start <= d <= end:
            return is_open
    return True


# ---------------------------------------------------------------- 单个 symbol 的票
def tickets_for_symbol(sym: str, bars: list, runs) -> list[dict]:
    d = [b[0] for b in bars]
    o = np.array([b[1] for b in bars], dtype=float)
    h = np.array([b[2] for b in bars], dtype=float)
    l = np.array([b[3] for b in bars], dtype=float)
    c = np.array([b[4] for b in bars], dtype=float)
    dv = np.array([b[5] for b in bars], dtype=float)
    n = len(bars)

    pc = np.concatenate(([c[0]], c[:-1]))          # lag(close); 第一根 coalesce(pc, c) => c
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])

    sma20 = roll_mean(c, 20)
    sma200 = roll_mean(c, 200)
    atr14 = roll_mean(tr, 14)
    adv30 = roll_mean(dv, 30)
    adv40p = roll_prev(dv, 40)                     # 前 40 根(不含当天)
    hh40 = roll_max_prev(h, 40)                    # 前 40 根最高 high(不含当天)
    ll40 = roll_min_prev(l, 40)                    # 前 40 根最低 low(不含当天)
    dd = c / roll_max(c, DD_WINDOW)                # 前 365 根(含当天)最高收盘
    mindd120 = roll_min(dd, MINDD_WINDOW)           # 取 120 根(含当天)的最小值

    cands = []
    for i in range(n):
        rn = i + 1
        if rn < MIN_RN:
            continue
        if not (SIG_FROM <= d[i] <= SIG_TO):
            continue
        if i + 1 > n - 1:                          # e.rn + 1 <= a.n: 必须还有下一根能进场
            continue
        if not (adv30[i] >= ADV30_MIN):
            continue
        if not (mindd120[i] <= MINDD120_MAX):
            continue
        if not ((hh40[i] - ll40[i]) / hh40[i] <= RANGE40_MAX):
            continue
        if not (c[i] > hh40[i]):
            continue
        if not (c[i] > sma200[i]):
            continue
        if not (dv[i] >= DV_MULT * adv40p[i]):
            continue
        if not (atr14[i] > 0):
            continue
        if not gate_open(runs, d[i]):
            continue

        entry_i = i + 1
        entry = o[entry_i]
        stop = entry - ATR_MULT * atr14[i]
        if not (entry > stop):                    # tr 的 where s.entry > s.stop
            continue

        # 出场:从进场那根起往后最多 120 根,先触发止损(low<=stop)否则 close<SMA20 次日开盘出
        k = None
        for j in range(entry_i, min(i + MAX_HOLD, n - 1) + 1):
            if l[j] <= stop or c[j] < sma20[j]:
                k = j
                break

        if k is None:
            xi = min(i + MAX_HOLD, n - 1)          # 120 根到期按收盘
            xp = c[xi]
            still = (i + MAX_HOLD) > (n - 1)
            rule = "expiry"
        elif l[k] <= stop:
            xi = k
            xp = o[k] if (k > entry_i and o[k] <= stop) else stop
            still = False
            rule = "stop"
        else:
            if k + 1 <= n - 1:
                xi = k + 1
                xp = o[xi]
                still = False
                rule = "sma20"
            else:
                xi = k
                xp = c[k]
                still = True
                rule = "sma20_lastbar"

        denom = entry - stop
        r = (xp - entry) / denom - COST * entry / denom
        cands.append({
            "symbol": sym, "rn": rn, "signal_d": d[i], "entry_d": d[entry_i],
            "exit_d": d[xi], "entry_px": entry, "stop_px": stop, "exit_px": xp,
            "r": r, "still": still, "exit_rule": rule,
            "entry_i": entry_i, "exit_i": xi,
            "atr14": float(atr14[i]), "adv30": float(adv30[i]),
            "sma20_at_signal": float(sma20[i]), "sma200_at_signal": float(sma200[i]),
            "hh40": float(hh40[i]), "ll40": float(ll40[i]),
            "mindd120": float(mindd120[i]),
            # 判据余量:两份实现若对不上,先看这里接近 0 的票
            "m_c_gt_hh40": float(c[i] - hh40[i]),
            "m_c_gt_sma200": float(c[i] - sma200[i]),
            "m_dv_ge_2adv40p": float(dv[i] - DV_MULT * adv40p[i]),
            "m_mindd120_le": float(MINDD120_MAX - mindd120[i]),
            "m_range40_le": float(RANGE40_MAX - (hh40[i] - ll40[i]) / hh40[i]),
            "m_adv30_ge": float(adv30[i] - ADV30_MIN),
        })

    # 同币不叠票:同币上一张出场之前不开新票(SQL rec CTE)
    cands.sort(key=lambda t: t["entry_i"])
    taken = []
    for t in cands:
        if not taken:
            taken.append(t)
            continue
        prev = taken[-1]
        ok = t["entry_i"] > prev["exit_i"] if OVERLAP_STRICT else t["entry_i"] >= prev["exit_i"]
        if ok:
            taken.append(t)
    return taken


# ---------------------------------------------------------------- 主流程
def main() -> int:
    if not os.path.exists(BARS_PATH):
        print("缺少数据文件:", BARS_PATH, file=sys.stderr)
        return 1
    if not os.path.exists(GATE_PATH):
        print("缺少闸门文件:", GATE_PATH, file=sys.stderr)
        return 1

    runs = load_gate()
    with open(BARS_PATH) as fh:
        rows = [json.loads(line) for line in fh]

    all_tickets = []
    n_bars = 0
    for row in rows:
        bars = row["bars"]
        n_bars += len(bars)
        all_tickets.extend(tickets_for_symbol(row["symbol"], bars, runs))

    all_tickets.sort(key=lambda t: (t["signal_d"], t["symbol"]))

    # ---- 票表 CSV
    os.makedirs(os.path.dirname(CSV_OUT), exist_ok=True)
    with open(CSV_OUT, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "signal_d", "entry_d", "exit_d", "entry_px", "stop_px",
                    "exit_px", "r", "still"])
        for t in all_tickets:
            w.writerow([
                t["symbol"], t["signal_d"], t["entry_d"], t["exit_d"],
                f"{t['entry_px']:.10g}", f"{t['stop_px']:.10g}", f"{t['exit_px']:.10g}",
                f"{t['r']:.10g}", int(t["still"]),
            ])

    # ---- 明细 JSON(Mac 数据根)
    rs = np.array([t["r"] for t in all_tickets], dtype=float) if all_tickets else np.array([])

    def agg(rows_):
        if not rows_:
            return {"n": 0, "avg_r": None, "sum_r": None}
        v = np.array([t["r"] for t in rows_], dtype=float)
        return {"n": len(v), "avg_r": float(v.mean()), "sum_r": float(v.sum())}

    by_year = {}
    for y in sorted({t["signal_d"][:4] for t in all_tickets}):
        by_year[y] = agg([t for t in all_tickets if t["signal_d"].startswith(y)])

    closed = [t for t in all_tickets if not t["still"]]
    out = {
        "task": "T-189",
        "what": "S-677 R-v2 票的独立复现(A 道,规则自实现)",
        "rules_source": ["docs/research/r_v2_tickets.sql", "ledger S-677 pre-registration",
                         "tasks/T-189.json acceptance"],
        "data": {"bars": BARS_PATH, "gate": GATE_PATH, "pairs": len(rows), "bars_total": n_bars},
        "window": {"signal_from": SIG_FROM, "signal_to": SIG_TO},
        "n_tickets": len(all_tickets),
        "n_still": len(all_tickets) - len(closed),
        "avg_r": float(rs.mean()) if len(rs) else None,
        "sum_r": float(rs.sum()) if len(rs) else None,
        "by_year": by_year,
        "tickets": all_tickets,
    }
    os.makedirs(os.path.dirname(JSON_OUT), exist_ok=True)
    with open(JSON_OUT, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=False)

    print("pairs", len(rows), "bars", n_bars)
    print("票数", len(all_tickets), "(其中 still", out["n_still"], ")")
    if len(rs):
        print("平均 R %.4f  合计 R %.4f" % (rs.mean(), rs.sum()))
    for y, a in by_year.items():
        print("  %s: 票 %d  平均 R %+.4f  合计 R %+.4f" % (y, a["n"], a["avg_r"], a["sum_r"]))
    print("CSV ->", CSV_OUT)
    print("JSON ->", JSON_OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
