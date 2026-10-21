"""S-659:R-v2 最近 20 张已平仓票的 R 合计 > 0 ⇒ 满仓,否则 0.25 仓 —— 预注册见台账(2026-10-21 13:34 UTC)。

票 = R-v2 的 770 张(`t159_bear_short.run_long` 逐张复现;仍持有的按最后收盘盯市)。对照 = 等敞口恒定仓位,
零假设 = 把状态序列对票循环平移 1,000 次。单位 B(一张票的风险)。
用法:python3 docs/research/s659_equity_state.py [--root /Volumes/CometCloudAI/cometcloud-local]
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
os.environ.setdefault("T159_DATA", os.path.join(ROOT, "research", "t159") + "/")
os.environ.setdefault("T156_DATA", os.path.join(ROOT, "research", "t156") + "/")
sys.path.insert(0, os.path.join(HERE, "..", ".."))
_spec = importlib.util.spec_from_file_location("s657", os.path.join(HERE, "s657_s658_breadth_second_leg.py"))
s657 = importlib.util.module_from_spec(_spec)
sys.modules["s657"] = s657
_spec.loader.exec_module(s657)
t159 = s657.t159

LOW = 0.25


def states(tickets, window=20):
    """每张票信号日的状态:出场日 ≤ t − 1 的最近 window 张已平仓票 R 合计 > 0 ⇒ True。"""
    closed = sorted((t for t in tickets if not t.get("still") and t.get("exit_d")),
                    key=lambda t: (t["exit_d"], t["symbol"]))
    out = []
    for t in tickets:
        prior = [u["r"] for u in closed if u["exit_d"] < t["signal_d"]]
        out.append(True if len(prior) < window else sum(prior[-window:]) > 0)
    return out


def book(tickets, sizes):
    pnl = [s * t["r"] for s, t in zip(sizes, tickets)]
    order = sorted(range(len(tickets)), key=lambda k: (tickets[k].get("exit_d") or "9999", tickets[k]["symbol"]))
    cum = peak = mdd = 0.0
    for k in order:
        cum += pnl[k]
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return sum(pnl), mdd, pnl


def run(tickets, window=20):
    st = states(tickets, window)
    sizes = [1.0 if s else LOW for s in st]
    avg = sum(sizes) / len(sizes)
    tot_e, mdd_e, pnl_e = book(tickets, sizes)
    tot_c, mdd_c, pnl_c = book(tickets, [avg] * len(tickets))
    n = len(tickets)
    shifted = []
    for k in range(1, 1001):
        sh = (k * n) // 1001 or 1
        sz = sizes[sh:] + sizes[:sh]
        shifted.append(book(tickets, sz)[0])
    shifted.sort()
    halves = {}
    for lab, cond in (("lt2023", lambda t: t["signal_d"] < "2023-01-01"), ("ge2023", lambda t: t["signal_d"] >= "2023-01-01")):
        idx = [i for i, t in enumerate(tickets) if cond(t)]
        halves[lab] = {"E": sum(pnl_e[i] for i in idx), "const": sum(pnl_c[i] for i in idx), "n": len(idx)}
    by_y: dict = {}
    for t, s in zip(tickets, sizes):
        y = t["signal_d"][:4]
        by_y.setdefault(y, []).append(s)
    return {"window": window, "n": n, "full_share": sum(st) / n, "avg_size": avg,
            "E_total": tot_e, "E_mdd": mdd_e, "const_total": tot_c, "const_mdd": mdd_c,
            "base_total": sum(t["r"] for t in tickets), "base_mdd": book(tickets, [1.0] * n)[1],
            "shift_q95": shifted[int(0.95 * len(shifted))], "shift_median": shifted[len(shifted) // 2],
            "shift_pct": sum(x < tot_e for x in shifted) / len(shifted), "halves": halves,
            "avg_size_by_year": {y: round(sum(v) / len(v), 3) for y, v in sorted(by_y.items())}}


def main():
    panel = t159.load_bars()
    gate = t159.load_gate()
    tickets = s657.mtm(t159.run_long(panel, gate, "2020-03-01", "2026-10-19"), panel)
    tickets.sort(key=lambda t: (t["signal_d"], t["symbol"]))
    assert len(tickets) == 770, len(tickets)
    res = {w: run(tickets, w) for w in (20, 10, 40)}
    r = res[20]
    ok = (r["E_total"] > r["const_total"] and r["E_total"] > r["shift_q95"]
          and all(h["E"] > h["const"] for h in r["halves"].values()) and r["E_mdd"] >= r["const_mdd"])
    res["verdict"] = "过" if ok else "不过"
    json.dump(res, open(os.path.join(HERE, "s659_results.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
