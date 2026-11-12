#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-355 —— 把自写的票源(t355_tickets.py)与 t197 的 956 张票逐张对,
再把两批票分别喂给 t353_engine.simulate(f 0.5% / 名额上限 0.40 / 14 个名额)。

用法:
    python3 t355_compare.py --mine t355_tickets_full.json --out t355_results.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import t355_tickets as T355          # noqa: E402
import t353_engine as T353           # noqa: E402

T197_FILE = os.path.join(HERE, "t197_results.json")
REF = {"taken": 358, "total_return": 0.9835255738794331, "mdd": -0.2419641660502755}
REL_TOL = 1e-9


def close(a, b, tol=REL_TOL):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def signal_day_of(tk, bars):
    """t197 票里的信号日:有字段就用字段,否则用「进场日之前该币最后一根 bar」。"""
    for k in ("signal_d", "sig_d", "signal_date", "s_date"):
        if tk.get(k):
            return str(tk[k])
    ed, sym = tk.get("entry_d"), tk.get("symbol")
    if not ed or not sym:
        return None
    ds = [r[0] for r in bars.get(sym, []) if r[0] < ed]
    return ds[-1] if ds else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mine", default=os.path.join(HERE, "t355_tickets_full.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "t355_results.json"))
    args = ap.parse_args()

    mine = json.load(open(args.mine))
    my_tickets = mine["tickets"]
    my_eng = mine["engine_tickets"]

    t197 = json.load(open(T197_FILE))
    A = t197["tickets"]["A"]
    meta = t197["meta"]

    bars = T353.load_um()          # {sym: [(d,o,h,l,c)]} —— 引擎要的形状

    # ── 键:(币, 信号日) ──────────────────────────────────────────────────
    my_by_key = {(t["symbol"], t["signal_d"]): t for t in my_tickets}
    th_by_key = {}
    th_no_sigday = 0
    for t in A:
        sd = signal_day_of(t, bars)
        if sd is None:
            th_no_sigday += 1
            continue
        th_by_key[(t["symbol"], sd)] = t

    my_keys, th_keys = set(my_by_key), set(th_by_key)
    both = my_keys & th_keys
    only_my = my_keys - th_keys
    only_th = th_keys - my_keys

    # ── 重合票逐项比对 ────────────────────────────────────────────────────
    diff = Counter()
    examples = defaultdict(list)
    for k in sorted(both):
        m, t = my_by_key[k], th_by_key[k]
        # r 的口径:R 倍数(生产 SQL 的 r_mult),不是简单收益
        my_r = m.get("r_mult")
        fields = [
            ("entry_d", m.get("entry_d"), t.get("entry_d")),
            ("entry_px", m.get("entry_px"), t.get("entry_px")),
            ("stop_px", m.get("stop_px"), t.get("stop_px")),
            ("exit_d", m.get("exit_d"), t.get("exit_d")),
            ("exit_px", m.get("exit_px"), t.get("exit_px")),
            ("r", my_r, t.get("r")),
        ]
        for name, a, b in fields:
            ok = (a == b) if isinstance(a, str) or isinstance(b, str) else close(a, b)
            if not ok:
                diff[name] += 1
                if len(examples[name]) < 5:
                    examples[name].append({"key": list(k), "mine": a, "t197": b,
                                           "mine_exit_reason": m.get("exit_reason"),
                                           "t197_exit_reason": t.get("exit_reason")})

    # ── 只在一边的票 ──────────────────────────────────────────────────────
    only_my_rows = []
    for k in sorted(only_my):
        t = my_by_key[k]
        only_my_rows.append({"symbol": k[0], "signal_d": k[1], "status": t["status"],
                              "gate_open": t["gate_open"], "entry_d": t.get("entry_d"),
                              "exit_d": t.get("exit_d"), "exit_reason": t.get("exit_reason")})
    only_th_rows = []
    for k in sorted(only_th):
        t = th_by_key[k]
        only_th_rows.append({"symbol": k[0], "signal_d": k[1], "entry_d": t.get("entry_d"),
                              "entry_px": t.get("entry_px"), "exit_d": t.get("exit_d"),
                              "exit_reason": t.get("exit_reason"), "r": t.get("r")})

    # ── 逐年分布 ──────────────────────────────────────────────────────────
    def by_year(rows, key):
        c = Counter()
        for r in rows:
            d = r.get(key)
            if d:
                c[str(d)[:4]] += 1
        return dict(sorted(c.items()))

    # ── 两批票各跑一遍账户引擎 ────────────────────────────────────────────
    def run(tickets, label):
        res = T353.simulate(tickets, bars, f=0.005, gross_cap=0.40, cap_n=14,
                            exits_first=True, gross_basis="marked",
                            nav_to=meta["nav_to"], strict=True)
        s = T353.summarize(res)
        s["label"] = label
        s["skip_reasons"] = dict(res["skip_reasons"])
        s["n_tickets_fed"] = len(tickets)
        s["by_year"] = {y: (v["ret"] if isinstance(v, dict) else v)
                        for y, v in s["by_year"].items()}
        return s

    th_eng = []
    for i, t in enumerate(A):
        tt = dict(t)
        tt["tid"] = i
        th_eng.append(tt)

    res_mine = run(my_eng, "mine")
    res_th = run(th_eng, "t197")

    out = {
        "meta": {
            "rule_source": mine["meta"]["rule_source"],
            "data": mine["meta"]["data"],
            "v_from": mine["meta"]["v_from"], "p_to": mine["meta"]["p_to"],
            "enforce_guard": mine["meta"]["enforce_guard"],
            "n_symbols": mine["meta"]["n_symbols"], "n_bars": mine["meta"]["n_bars"],
            "t197_file": T197_FILE,
            "t197_meta": meta,
        },
        "scan_log": mine["scan_log"],
        "counts": {
            "mine_tickets": len(my_tickets),
            "mine_status_hist": dict(Counter(t["status"] for t in my_tickets)),
            "mine_exit_reason_hist": dict(Counter(
                t["exit_reason"] for t in my_tickets if t["exit_reason"])),
            "mine_engine_tickets": len(my_eng),
            "t197_tickets": len(A),
            "t197_signal_day_missing": th_no_sigday,
            "overlap": len(both),
            "only_mine": len(only_my),
            "only_t197": len(only_th),
            "overlap_pct_of_t197": len(both) / len(A) if A else None,
        },
        "mismatch_counts": dict(diff),
        "mismatch_examples": dict(examples),
        "only_mine_examples": only_my_rows[:12],
        "only_t197_examples": only_th_rows[:12],
        "by_year": {
            "mine_signal": by_year(my_tickets, "signal_d"),
            "mine_entry": by_year(my_eng, "entry_d"),
            "t197_entry": by_year(A, "entry_d"),
        },
        "engine": {
            "cell": "f=0.005 gross_cap=0.40 cap_n=14 exits_first=True gross_basis=marked",
            "mine": res_mine, "t197": res_th, "reference_T353": REF,
            "delta_mine_vs_ref": {
                "taken": res_mine["taken"] - REF["taken"],
                "total_return_pp": (res_mine["total_return"] - REF["total_return"]) * 100,
            },
            "delta_mine_vs_t197_run": {
                "taken": res_mine["taken"] - res_th["taken"],
                "total_return_pp": (res_mine["total_return"] - res_th["total_return"]) * 100,
            },
        },
    }
    with open(args.out, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps({"out": args.out,
                      "counts": out["counts"],
                      "mismatch_counts": out["mismatch_counts"],
                      "engine_mine": {k: res_mine[k] for k in
                                      ("taken", "skipped", "closed", "open_at_end",
                                       "total_return", "mdd")},
                      "engine_t197": {k: res_th[k] for k in
                                      ("taken", "skipped", "closed", "open_at_end",
                                       "total_return", "mdd")}},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
