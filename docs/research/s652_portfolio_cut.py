"""S-652:组合层回吐止损(权益从峰值回撤 15% ⇒ 次日开盘所有持仓减半、新票风险减半,创新高后恢复)vs 恒定 vs 回撤刹车。

引擎 = src/exec_host/sim_tickets.py(policy = "cut");装载 / 月块重抽 = docs/research/s647_sim_r_v2.py(同一组 2,000 条路径,种子 647)。
用法:python3 docs/research/s652_portfolio_cut.py [--root /Volumes/CometCloudAI/cometcloud-local] [--paths 2000] [--jobs 4]
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
spec = importlib.util.spec_from_file_location("s647", os.path.join(HERE, "s647_sim_r_v2.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
from src.exec_host import sim_tickets as st  # noqa: E402

POLICIES = ("const", "brake", "cut")
LEVS = (3.0, 5.0)
SIZE = 100_000.0


def _run(tks, lev, policy, apy, s0, s1):
    return st.simulate(tks, SIZE, lev, policy=policy, executable=lambda t: m.hl_listed(t.symbol), apy_for_day=apy,
                       start_day=s0, end_day=s1, collateral_mult=float("inf"))


def _worker(args):
    seed0, n, by_month, months = args
    out = []
    for p in range(n):
        rng = random.Random(seed0 + p)
        tks, apys, s0, s1 = m.mc_path(by_month, months, rng)
        for lev in LEVS:
            for pol in POLICIES:
                if not tks:
                    out.append(((pol, lev), {"cagr": None, "mdd": 0.0, "cuts": 0}))
                    continue
                r = _run(tks, lev, pol, lambda d: apys[d - s0] if 0 <= d - s0 < len(apys) else 0.034, s0, s1)
                out.append(((pol, lev), {**st.stats(r.equity, SIZE), "cuts": r.cuts}))
    return out


def main():
    root = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
    paths = int(sys.argv[sys.argv.index("--paths") + 1]) if "--paths" in sys.argv else 2000
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 4
    bars, fund, tix = m.load(root)
    tk, meta = m.build_tickets(bars, fund, tix)
    s0, s1 = (m.HIST_START - st.EPOCH).days, (m.HIST_END - st.EPOCH).days
    res = {"hist": {}, "mc": {}}
    for lev in LEVS:
        for pol in POLICIES:
            r = _run(tk, lev, pol, m._apy_hist, s0, s1)
            res["hist"][f"{pol}_L{lev:g}"] = {**st.stats(r.equity, SIZE), "cuts": r.cuts}
    months = m._months()
    by_month = [[t for t in tk if m0 <= st.EPOCH + dt.timedelta(days=t.entry_day) < m1] for m0, m1 in months]
    per = paths // jobs
    agg: dict = {}
    with ProcessPoolExecutor(jobs) as pool:
        for chunk in pool.map(_worker, [(m.SEED * 100_000 + j * per, per, by_month, months) for j in range(jobs)]):
            for c, s in chunk:
                agg.setdefault(c, []).append(s)
    for (pol, lev), xs in agg.items():
        cg = [x["cagr"] for x in xs if x["cagr"] is not None]
        dd = [x["mdd"] for x in xs]
        res["mc"][f"{pol}_L{lev:g}"] = {"n": len(xs), "cagr_p5": m.pct(cg, .05), "cagr_p50": m.pct(cg, .5),
                                        "cagr_p95": m.pct(cg, .95), "mdd_p50": m.pct(dd, .5), "mdd_p95": m.pct(dd, .05),
                                        "p_mdd_50": sum(d <= -0.5 for d in dd) / len(dd),
                                        "mean_cuts": sum(x["cuts"] for x in xs) / len(xs)}
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
