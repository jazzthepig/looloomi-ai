"""S-653:整个 FoF(① + R-v2 + 现金)的分级 —— 同月联合重抽(2023-01 → 2026-09 月份池),月初再平衡,算优先 / 劣后所需厚度。

① 日收益 = core_variants_daily arm cap_uncapped(docs/research/s653_core_ret.json,2026-10-21 从库里读出:1,387 天,
  按 1e-5 取整;核对:条数 1,387、和 1.7448 vs 库 1.7447、年化 41.0% 与 S-643 一致)。
R-v2 = S-647 引擎(HL 宇宙、钱全留 HL、恒定 L);票与数据 = C 道 T-159 缓存。覆盖 / 劣后口径同 S-648。
用法:python3 docs/research/s653_fof_tranche.py [--root /Volumes/CometCloudAI/cometcloud-local] [--paths 2000] [--jobs 4]
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

SEED, MONTHS, YEARS = 653, 36, 3.0
POOL = (dt.date(2023, 1, 1), dt.date(2026, 9, 1))
MIXES = {"core100": (1.0, 0.0, 0.0), "core70_rv30": (0.7, 0.3, 0.0), "core50_rv30_cash20": (0.5, 0.3, 0.2),
         "core50_rv50": (0.5, 0.5, 0.0)}
LEVS = (1.0, 3.0)
#: S-653 补:① 闸门版(majors 闸门关时 ① 敞口 0.5,余下放贷;切换成本 0.2% × |Δ|)。闸门 = S-643 同一条,t 日收盘判、t+1 起生效;
#: 2026-10-21 从库里读出的游程(O = 开、C = 关;2023-01-02 → 2026-10-19 关 509 天,与 S-643 一致)
GATE_RUNS = ("C2023-01-01,O2023-01-14,C2023-08-18,O2023-10-21,C2024-07-05,O2024-07-14,C2024-08-03,O2024-10-15,"
             "C2024-10-26,O2024-10-27,C2025-02-27,O2025-03-03,C2025-03-04,O2025-03-06,C2025-03-08,O2025-04-26,"
             "C2025-04-28,O2025-05-02,C2025-05-05,O2025-05-07,C2025-11-04,O2026-08-20")
GATE_MIXES = {"coreG100": (1.0, 0.0, 0.0), "coreG70_rv30": (0.7, 0.3, 0.0), "coreG50_rv50": (0.5, 0.5, 0.0)}


def gate_open_map():
    runs = [(x[0] == "O", dt.date.fromisoformat(x[1:])) for x in GATE_RUNS.split(",")]
    out = {}
    for i, (o, d0) in enumerate(runs):
        d1 = runs[i + 1][1] if i + 1 < len(runs) else dt.date(2026, 10, 20)
        d = d0
        while d < d1:
            out[d] = o
            d += dt.timedelta(days=1)
    return out


GATE = gate_open_map()
COUPONS = (0.0, 0.05, 0.08)


def load_core():
    d = json.load(open(os.path.join(HERE, "s653_core_ret.json")))
    r = [int(x) * d["scale"] for x in d["r"].split(",")]
    d0 = dt.date.fromisoformat(d["d0"])
    return {d0 + dt.timedelta(days=i): x for i, x in enumerate(r)}       # 日序连续(cap_uncapped 每天一行)


def months_pool():
    out, mth = [], POOL[0]
    while mth <= POOL[1]:
        nxt = (mth.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        out.append((mth, nxt))
        mth = nxt
    return out


def coverage(nav):
    out = {}
    for c in COUPONS:
        rmin, rend = float("inf"), None
        for t, e in enumerate(nav, start=1):
            r = e / (1 + c) ** (t / 365.0)
            rmin, rend = min(rmin, r), r
        out[f"rmin_{c}"], out[f"rend_{c}"] = rmin, rend
    return out


def _worker(args):
    seed0, n, by_month, months, core = args
    res = []
    for p in range(n):
        rng = random.Random(seed0 + p)
        draws = [rng.randrange(len(months)) for _ in range(MONTHS)]
        # R-v2 合成票 + 每日 ① 收益 + 放贷利率 + 月初标记
        S0, base, tks, core_r, apys, month_start, coreg_r = 50_000, 50_000, [], [], [], [], []
        prev_x = 1.0
        for k, i in enumerate(draws):
            m0, m1 = months[i]
            nd = (m1 - m0).days
            for t in by_month[i]:
                off = (st.EPOCH + dt.timedelta(days=t.entry_day) - m0).days
                ne = base + off
                tks.append(st.SimTicket(tid=f"{t.tid}#{k}", symbol=t.symbol, entry_day=ne, exit_off=t.exit_off,
                                        paper_exit_off=t.paper_exit_off, stop_frac=t.stop_frac, path=t.path,
                                        signal_day=ne - 1, major=t.major))
            for j in range(nd):
                dd_ = m0 + dt.timedelta(days=j)
                core_r.append(core.get(dd_, 0.0))
                x = 1.0 if GATE.get(dd_, True) else 0.5
                coreg_r.append(x * core.get(dd_, 0.0) + (1 - x) * m.apy(m0) / 365.0 - 0.002 * abs(x - prev_x))
                prev_x = x
                apys.append(m.apy(m0))
                month_start.append(j == 0)
            base += nd
        T = len(core_r)
        rv = {}
        for lev in LEVS:
            if tks:
                r = st.simulate(tks, 100_000.0, lev, executable=lambda t: m.hl_listed(t.symbol),
                                apy_for_day=lambda d: apys[d - S0] if 0 <= d - S0 < T else 0.034,
                                start_day=S0, end_day=S0 + T - 1, collateral_mult=float("inf"))
                eq = [100_000.0] + r.equity
                rv[lev] = [eq[i + 1] / eq[i] - 1 if eq[i] > 0 else 0.0 for i in range(T)]
            else:
                rv[lev] = [apys[i] / 365.0 for i in range(T)]
        for lev in LEVS:
            for name, (wc, wr, wx) in {**MIXES, **GATE_MIXES}.items():
                if wr == 0 and lev != LEVS[0]:
                    continue
                cr = coreg_r if name.startswith("coreG") else core_r
                nav, vals = [], None
                for i in range(T):
                    if month_start[i] or vals is None:
                        tot = sum(vals) if vals else 1.0
                        vals = [tot * wc, tot * wr, tot * wx]
                    vals = [vals[0] * (1 + cr[i]), vals[1] * (1 + rv[lev][i]), vals[2] * (1 + apys[i] / 365.0)]
                    nav.append(sum(vals))
                s = st.stats(nav, 1.0)
                res.append(((name, lev), {**s, **coverage(nav)}))
    return res


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))]


def summarize(rows):
    out = {"n": len(rows), "cagr_p5": q([r["cagr"] for r in rows], .05), "cagr_p50": q([r["cagr"] for r in rows], .5),
           "cagr_p95": q([r["cagr"] for r in rows], .95), "mdd_p50": q([r["mdd"] for r in rows], .5),
           "mdd_p95": q([r["mdd"] for r in rows], .05)}
    for c in COUPONS:
        for mode, key in (("end", "rend"), ("cont", "rmin")):
            js = [max(0.0, 1 - r[f"{key}_{c}"]) for r in rows]
            out[f"J95_{mode}_{c}"], out[f"J99_{mode}_{c}"] = q(js, .95), q(js, .99)
    J, c = out["J99_cont_0.05"], 0.05
    jr, wiped = [], 0
    for r in rows:
        if J <= 0 or r[f"rmin_{c}"] < 1 - J:
            wiped += 1
            jr.append(-1.0)
            continue
        end_nav = r[f"rend_{c}"] * (1 + c) ** YEARS
        v = max(0.0, end_nav - (1 - J) * (1 + c) ** YEARS) / J
        jr.append(v ** (1 / YEARS) - 1 if v > 0 else -1.0)
    out.update({"junior_cagr_p5": q(jr, .05), "junior_cagr_p50": q(jr, .5), "junior_cagr_p95": q(jr, .95),
                "p_junior_wiped": wiped / len(rows)})
    return out


def main():
    root = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
    paths = int(sys.argv[sys.argv.index("--paths") + 1]) if "--paths" in sys.argv else 2000
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 4
    bars, fund, tix = m.load(root)
    tk, _ = m.build_tickets(bars, fund, tix)
    months = months_pool()
    by_month = [[t for t in tk if m0 <= st.EPOCH + dt.timedelta(days=t.entry_day) < m1] for m0, m1 in months]
    core = load_core()
    per = paths // jobs
    agg: dict = {}
    with ProcessPoolExecutor(jobs) as pool:
        for chunk in pool.map(_worker, [(SEED * 100_000 + j * per, per, by_month, months, core) for j in range(jobs)]):
            for c, s in chunk:
                agg.setdefault(c, []).append(s)
    out = {f"{name}_L{lev:g}": summarize(rows) for (name, lev), rows in sorted(agg.items())}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
