#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-355 / S-830 —— 票源的第二份:照生产内核 r_tickets_scan 从零重写开票 / 管票。

规则唯一来源:migrations/2026-11-05_r_tickets_validated_universe.sql 里的
`r_tickets_scan`(信号条件、进场、止损、SMA20 出场、到期、无数据出场)。
不读、不 import t197_rv2_survivorship.py / t159_* / t351_*。

闸门按同一份 SQL 的口径自己算(majors 市值权重的 200 日线闸门),
再在 --selftest 里用子进程跟 t310_slots.load_gate() 逐日对拍
(不 import 它,免得连带 import t159_bear_short)。

用法:
    python3 t355_tickets.py --build            # 生成票,写 t355_tickets.json
    python3 t355_tickets.py --selftest         # 闸门对拍
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
UM_FILE = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl"
STYLE_FILE = "/Volumes/CometCloudAI/cometcloud-local/research/t156/_style.json"

# ── 规则常量:逐条抄自 r_tickets_scan 的 SQL ────────────────────────────────
EXCLUDE_SYMBOLS = ("USDC", "BTCDOM", "DEFI")   # b0 的 symbol not in (...)
SIG_MIN_RN = 220          # sig: rn >= 220
SIG_MIN_ADV30 = 5e6       # sig: adv30 >= 5e6
SIG_MAX_MINDD120 = 0.5    # sig: mindd120 <= 0.5
SIG_MAX_RANGE40 = 0.40    # sig: (hh40 - ll40) / hh40 <= 0.40
STOP_ATR_MULT = 2.5       # 进场: stop_px = o - 2.5 * atr14
MAX_BARS_HELD = 120       # 到期: bars_held >= 120
NODATA_LAG_DAYS = 9       # 无数据: lb.d < v_d - 9
COST = 0.004              # r_mult 里的一次性成本(名义口径)
GATE_SMA_N = 200          # 闸门 SMA200

DEFAULT_FROM = "2020-07-18"   # SQL 自己的硬编码日(majors 闸门从这天起必须存在);
                              # 也是本宇宙里数据完整度闸门能过的最早一天
DEFAULT_TO = "2026-09-30"     # t197 meta 的 nav_to / signal_window 末端


# ── 闸门 ────────────────────────────────────────────────────────────────────
def load_gate(styles_path: str = STYLE_FILE, p_to: str | None = None) -> dict:
    """majors(市值加权)的 200 日线闸门 —— r_tickets_scan 里 _rt_gate 的口径:
    水平 = 累乘(1+ret);水平 > 自身 SMA200 ⇒ 闸门开;样本不足 200 天 ⇒ 开。"""
    rows = json.load(open(styles_path))
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("data") or []
    rows = [r for r in rows if r.get("ret") is not None and float(r["ret"]) > -0.95]
    if p_to:
        rows = [r for r in rows if r["d"] <= p_to]
    rows.sort(key=lambda r: r["d"])
    lvl, cur = [], 1.0
    for r in rows:
        cur *= (1.0 + float(r["ret"]))
        lvl.append(cur)
    gate = {}
    for i, r in enumerate(rows):
        seg = lvl[max(0, i - (GATE_SMA_N - 1)): i + 1]
        sma = sum(seg) / len(seg)
        gate[r["d"]] = bool(len(seg) < GATE_SMA_N or lvl[i] > sma)
    return gate


# ── 日线 + 特征 ─────────────────────────────────────────────────────────────
def load_um(path: str = UM_FILE) -> dict:
    """symbol -> [(d, o, h, l, c, qv), ...](按日期升序;只留 c > 0,与 b0 一致)。"""
    out = {}
    with open(path) as f:
        for line in f:
            obj = json.loads(line)
            sym = obj["symbol"]
            if sym in EXCLUDE_SYMBOLS:
                continue
            keep = []
            for r in obj.get("bars") or []:
                d = str(r[0])
                o, h, l, c = float(r[1]), float(r[2]), float(r[3]), float(r[4])
                qv = float(r[5])
                if not (c > 0):
                    continue
                keep.append((d, o, h, l, c, qv))
            keep.sort(key=lambda x: x[0])
            if keep:
                out[sym] = keep
    return out


def _roll(arr, back, fwd, how):
    """SQL 的 `rows between {back} preceding and {fwd} preceding` 窗口。
    下界裁到 0(与 SQL 的 frame 裁剪一致)。返回 float64 数组,空窗口为 nan。"""
    n = len(arr)
    w = back + 1 - fwd                      # 完整窗口长度
    out = np.full(n, np.nan)
    if w <= 0:
        return out
    pre = min(back, n)                      # i < back 的前缀区:窗口 = arr[0..i-fwd]
    if how == "max":
        acc = np.maximum.accumulate(arr)
    elif how == "min":
        acc = np.minimum.accumulate(arr)
    else:
        acc = None
    for i in range(pre):
        e = i - fwd
        if e < 0:
            continue
        out[i] = acc[e] if acc is not None else float(np.mean(arr[: e + 1]))
    if n > back:
        sw = np.lib.stride_tricks.sliding_window_view(arr, w)
        vals = sw.max(axis=1) if how == "max" else (
            sw.min(axis=1) if how == "min" else sw.mean(axis=1))
        out[back:] = vals[: n - back]
    return out


def features(rows):
    """把 f / f2 的每个窗口算成数组(下标 = 行号,行号即 SQL 的 rn)。"""
    n = len(rows)
    c = np.array([r[4] for r in rows], dtype=float)
    h = np.array([r[2] for r in rows], dtype=float)
    l = np.array([r[3] for r in rows], dtype=float)
    dv = np.array([r[5] for r in rows], dtype=float)
    pc = np.concatenate(([np.nan], c[:-1]))
    pcc = np.where(np.isnan(pc), c, pc)
    tr = np.maximum.reduce([h - l, np.abs(h - pcc), np.abs(l - pcc)])
    sma20 = _roll(c, 19, 0, "mean")
    sma200 = _roll(c, 199, 0, "mean")
    atr14 = _roll(tr, 13, 0, "mean")
    adv30 = _roll(dv, 29, 0, "mean")
    adv40p = _roll(dv, 40, 1, "mean")
    hh40 = _roll(h, 40, 1, "max")
    ll40 = _roll(l, 40, 1, "min")
    cmax365 = _roll(c, 365, 0, "max")
    dd = c / cmax365
    mindd120 = _roll(dd, 120, 0, "min")
    with np.errstate(invalid="ignore"):
        ok = (
            (np.arange(n) + 1 >= SIG_MIN_RN)
            & (adv30 >= SIG_MIN_ADV30)
            & (mindd120 <= SIG_MAX_MINDD120)
            & ((hh40 - ll40) / hh40 <= SIG_MAX_RANGE40)
            & (c > hh40)
            & (c > sma200)
            & (dv >= 2 * adv40p)
        )
    sig = np.nan_to_num(ok, nan=False).astype(bool)
    return {"sma20": sma20, "atr14": atr14, "sig": sig}


# ── 扫描(逐条照 SQL 的日循环) ────────────────────────────────────────────────
def _d(s):
    return dt.date.fromisoformat(s)


def _ds(d):
    return d.isoformat()


def run_scan(bars: dict, gate: dict, v_from: str, p_to: str, enforce_guard: bool = True):
    """返回 (tickets list, scan log)。每条 = 生产 r_tickets_paper 的一行。"""
    by_date = defaultdict(list)     # d -> [(sym, idx)]
    feat = {}                       # sym -> {rows, idx, sma20, atr14, sig}
    for sym, rows in bars.items():
        f = features(rows)
        idx_by_d = {}
        for i, r in enumerate(rows):
            idx_by_d[r[0]] = i
            by_date[r[0]].append((sym, i))
        feat[sym] = {"rows": rows, "idx": idx_by_d, **f}
    for d in by_date:
        by_date[d].sort()

    tickets = {}                    # ticket_id -> dict
    last_bar = {}                   # sym -> (d, c)  当日及之前最后一根 bar

    def bar_of(sym, d):
        m = feat.get(sym)
        if not m:
            return None
        i = m["idx"].get(d)
        if i is None:
            return None
        r = m["rows"][i]
        return {"d": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4],
                "sma20": float(m["sma20"][i]), "atr14": float(m["atr14"][i])}

    def close_t(t, exit_d, exit_px, reason):
        t["status"] = "closed"
        t["exit_d"] = exit_d
        t["exit_px"] = exit_px
        t["exit_reason"] = reason
        denom = t["entry_px"] - t["stop_px"]
        t["r_mult"] = ((exit_px - t["entry_px"]) / denom
                       - COST * t["entry_px"] / denom) if denom else None

    log = {"v_from": v_from, "p_to": p_to, "enforce_guard": enforce_guard,
           "stopped": None, "days": 0}

    d0, d1 = _d(v_from), _d(p_to)
    day = d0
    while day <= d1:
        ds = _ds(day)
        todays = by_date.get(ds, [])
        prev = by_date.get(_ds(day - dt.timedelta(days=1)), [])
        if enforce_guard:
            # 数据完整度闸门:当天 bar 数 < max(20, 0.8×前一天) ⇒ 整个扫描停
            if len(todays) < max(20, 0.8 * len(prev)):
                log["stopped"] = (f"only {len(todays)} bars on {ds} "
                                  f"(previous day {len(prev)})")
                break
            if ds not in gate and ds > DEFAULT_FROM:
                log["stopped"] = f"majors index missing on {ds}"
                break

        # 1. 昨天的 SMA20 出场标记,今天开盘成交
        for t in list(tickets.values()):
            if t["status"] == "open" and t["exit_flag"]:
                b = bar_of(t["symbol"], ds)
                if b is None:
                    continue
                close_t(t, ds, b["o"], "sma20")

        # 2. pending 票今天开盘成交
        for t in list(tickets.values()):
            if t["status"] != "pending":
                continue
            b = bar_of(t["symbol"], ds)
            if b is None:
                continue
            stop = b["o"] - STOP_ATR_MULT * t["atr14"]
            if stop > 0:
                t["status"] = "open"
                t["entry_d"] = ds
                t["entry_px"] = b["o"]
                t["stop_px"] = stop
            else:
                t["status"] = "void"

        # 3. 在场票的当日 bar:先数 bar,再 止损 > SMA20 标记 > 到期
        for t in tickets.values():
            if t["status"] == "open" and not t["exit_flag"] and bar_of(t["symbol"], ds):
                t["bars_held"] += 1
        for t in tickets.values():
            if t["status"] != "open" or t["exit_flag"]:
                continue
            b = bar_of(t["symbol"], ds)
            if b is None or b["l"] > t["stop_px"]:
                continue
            px = b["o"] if (ds > t["entry_d"] and b["o"] <= t["stop_px"]) else t["stop_px"]
            close_t(t, ds, px, "stop")
        for t in tickets.values():
            if t["status"] != "open" or t["exit_flag"]:
                continue
            b = bar_of(t["symbol"], ds)
            if b is None:
                continue
            if b["c"] < b["sma20"]:
                t["exit_flag"] = True
        for t in tickets.values():
            if t["status"] != "open" or t["exit_flag"] or t["bars_held"] < MAX_BARS_HELD:
                continue
            b = bar_of(t["symbol"], ds)
            if b is None:
                continue
            close_t(t, ds, b["c"], "time")

        # 3b. 该币停印 bar 超过 10 天:按最后一根收盘平掉
        for sym, i in todays:                      # last bar 要含当日
            r = feat[sym]["rows"][i]
            last_bar[sym] = (r[0], r[4])
        for t in tickets.values():
            if t["status"] != "open":
                continue
            lb = last_bar.get(t["symbol"])
            if lb is None:
                continue
            if lb[0] < _ds(day - dt.timedelta(days=NODATA_LAG_DAYS)):
                close_t(t, lb[0], lb[1], "no_data")

        # 4. 今天的信号:闸门开 ⇒ pending,否则 blocked
        busy = {t["symbol"] for t in tickets.values()
                if t["status"] in ("pending", "open")}
        for sym, i in todays:
            m = feat[sym]
            if not m["sig"][i]:
                continue
            atr = float(m["atr14"][i])
            if not (atr > 0):
                continue
            if sym in busy:
                continue
            tid = f"{sym}:{ds}"
            if tid in tickets:
                continue
            gate_open = bool(gate.get(ds, True))
            tickets[tid] = {
                "ticket_id": tid, "symbol": sym, "signal_d": ds,
                "gate_open": gate_open, "atr14": atr,
                "status": "pending" if gate_open else "blocked",
                "entry_d": None, "entry_px": None, "stop_px": None,
                "exit_d": None, "exit_px": None, "exit_reason": None,
                "r_mult": None, "bars_held": 0, "exit_flag": False,
            }
            busy.add(sym)

        log["days"] += 1
        day += dt.timedelta(days=1)

    log["stopped_at"] = _ds(day) if log["stopped"] else None
    out = sorted(tickets.values(), key=lambda t: (t["signal_d"], t["symbol"]))
    log["tickets"] = len(out)
    sh = defaultdict(int)
    rh = defaultdict(int)
    for t in out:
        sh[t["status"]] += 1
        if t["exit_reason"]:
            rh[t["exit_reason"]] += 1
    log["status_hist"] = dict(sh)
    log["exit_reason_hist"] = dict(rh)
    return out, log


def to_engine_tickets(rows):
    """转成 t353_engine.simulate 吃的样子:
    r = R 倍数(= 生产 SQL 的 r_mult),不是简单收益 —— 引擎的不变量③按
    「已实现盈亏 = Σ(r × 进场时每票风险额)」记账,风险额 = 名义 × sd,
    所以 r 必须满足 r × sd = (exit/entry − 1) − 0.004,即 r = r_mult。
    still(窗口末还在场的票)没有出场价,r 记 0 —— 它只进 book 占用名额,永不结算。"""
    out = []
    for i, t in enumerate(rows):
        if t["status"] not in ("open", "closed"):
            continue
        if t["entry_d"] is None:
            continue
        sd = (t["entry_px"] - t["stop_px"]) / t["entry_px"]
        r_r = t["r_mult"] if t["r_mult"] is not None else 0.0
        out.append({
            "tid": i,
            "symbol": t["symbol"],
            "signal_d": t["signal_d"],
            "entry_d": t["entry_d"], "entry_px": t["entry_px"],
            "stop_px": t["stop_px"],
            "exit_d": t["exit_d"], "exit_px": t["exit_px"],
            "exit_reason": t["exit_reason"],
            "r": r_r, "r_mult": t["r_mult"], "sd": sd,
            "still": t["status"] == "open",
        })
    return out


def signal_detail(rows, i):
    """某一根 bar 上的信号条件逐项取值 + 哪几条没过(给「只在对方那边」的票找原因)。"""
    n = len(rows)
    c = np.array([r[4] for r in rows], dtype=float)
    h = np.array([r[2] for r in rows], dtype=float)
    l = np.array([r[3] for r in rows], dtype=float)
    dv = np.array([r[5] for r in rows], dtype=float)
    pc = np.concatenate(([np.nan], c[:-1]))
    pcc = np.where(np.isnan(pc), c, pc)
    tr = np.maximum.reduce([h - l, np.abs(h - pcc), np.abs(l - pcc)])
    sma20 = _roll(c, 19, 0, "mean")
    sma200 = _roll(c, 199, 0, "mean")
    atr14 = _roll(tr, 13, 0, "mean")
    adv30 = _roll(dv, 29, 0, "mean")
    adv40p = _roll(dv, 40, 1, "mean")
    hh40 = _roll(h, 40, 1, "max")
    ll40 = _roll(l, 40, 1, "min")
    cmax365 = _roll(c, 365, 0, "max")
    mindd120 = _roll(c / cmax365, 120, 0, "min")
    checks = {
        "rn>=220": (i + 1) >= SIG_MIN_RN,
        "adv30>=5e6": bool(adv30[i] >= SIG_MIN_ADV30),
        "mindd120<=0.5": bool(mindd120[i] <= SIG_MAX_MINDD120),
        "range40<=0.40": bool((hh40[i] - ll40[i]) / hh40[i] <= SIG_MAX_RANGE40),
        "c>hh40": bool(c[i] > hh40[i]),
        "c>sma200": bool(c[i] > sma200[i]),
        "dv>=2*adv40p": bool(dv[i] >= 2 * adv40p[i]),
    }
    return {"rn": i + 1, "n_bars": n, "checks": checks,
            "failed": [k for k, v in checks.items() if not v],
            "values": {"c": float(c[i]), "hh40": float(hh40[i]), "ll40": float(ll40[i]),
                       "sma200": float(sma200[i]), "adv30": float(adv30[i]),
                       "adv40p": float(adv40p[i]), "dv": float(dv[i]),
                       "mindd120": float(mindd120[i]), "atr14": float(atr14[i])}}


# ── 自检 ────────────────────────────────────────────────────────────────────
def selftest(p_to):
    """闸门逐日对拍 t310_slots.load_gate()(子进程跑,不 import t159)。"""
    mine = load_gate(p_to=p_to)
    code = (
        "import sys, json; sys.path.insert(0, %r);"
        "import t310_slots as t; g,_,_ = t.load_gate();"
        "print(json.dumps({k: bool(v) for k, v in g.items()}))" % HERE
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if out.returncode != 0:
        return {"gate_crosscheck": "FAILED: " + out.stderr.strip()[-400:]}
    theirs = {k: bool(v) for k, v in json.loads(out.stdout).items()}
    days = sorted(set(mine) & set(theirs))
    diff = [d for d in days if mine[d] != theirs[d]]
    return {"gate_crosscheck": {"days_compared": len(days), "mismatches": len(diff),
                                "first_mismatch": diff[:5],
                                "mine_days": len(mine), "theirs_days": len(theirs)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--from", dest="v_from", default=DEFAULT_FROM)
    ap.add_argument("--to", dest="p_to", default=DEFAULT_TO)
    ap.add_argument("--no-guard", action="store_true", help="不执行数据完整度闸门")
    ap.add_argument("--out", default=os.path.join(HERE, "t355_tickets.json"))
    args = ap.parse_args()

    if args.selftest:
        print(json.dumps(selftest(args.p_to), ensure_ascii=False, indent=1))
        return

    if args.build:
        bars = load_um()
        gate = load_gate(p_to=args.p_to)
        rows, log = run_scan(bars, gate, args.v_from, args.p_to,
                             enforce_guard=not args.no_guard)
        eng = to_engine_tickets(rows)
        payload = {
            "meta": {
                "rule_source": "migrations/2026-11-05_r_tickets_validated_universe.sql :: r_tickets_scan",
                "data": UM_FILE, "style": STYLE_FILE,
                "v_from": args.v_from, "p_to": args.p_to,
                "universe": "t197 A universe(= _um_daily.jsonl 全部符号)",
                "n_symbols": len(bars), "n_bars": sum(len(v) for v in bars.values()),
                "enforce_guard": not args.no_guard,
            },
            "scan_log": log,
            "tickets": rows,
            "engine_tickets": eng,
        }
        with open(args.out, "w") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(json.dumps({"out": args.out, "scan_log": log,
                          "engine_tickets": len(eng)}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
