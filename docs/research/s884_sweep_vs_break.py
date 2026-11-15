"""S-884:同一个 20 日高 / 低被刺穿之后的两种结局 —— 收在外面(破位顺势)还是收回来(扫过再收回,反手)—— 各在哪个状态是主场;
以及波动压缩之后的突破。外部从业者最常讲的两个形态(swing failure / liquidity sweep、volatility squeeze),在我们的状态四格里量基率。

触发(D 日收盘判、D + 1 开盘进;BTC / ETH 各自;lo20 / hi20 = 此前 20 天、不含 D 的最低 / 最高):
  BREAK_DN   c[D] < lo20 ≤ c[D−1]                ⇒ 空,认错 = lo20 之上 1%
  SWEEP_DN   l[D] < lo20 且 c[D] ≥ lo20          ⇒ 多,认错 = l[D] 之下 0.5%
  BREAK_UP   c[D] > hi20 ≥ c[D−1]                ⇒ 多,认错 = hi20 之下 1%
  SWEEP_UP   h[D] > hi20 且 c[D] ≤ hi20          ⇒ 空,认错 = h[D] 之上 0.5%
  COMP_BREAK_UP / COMP_BREAK_DN = BREAK_UP / BREAK_DN 且 D 的 30 日实现波动处在此前 365 天的最低 20%
  认错距离按进场价算,不足 1% 按 1%、超过 12% 按 12%(STRUCT);另报固定 8%(FIX8)。一次进满、28 天。
状态 = 趋势 × 谁在领(与 S-881 同一份装载)。对照 = 同格同向每 5 天一张(固定 8%)。
「站得住」= 发现段(≤ 2022)与留出段(2023 起)都:票数 ≥ 8、均值 > 0、盈亏比 ≥ 2、均值高于同格同向的对照。状态序列平移 100 次。
预期与后果写在台账 S-884(先登记,后计算)。

用法(仓库根目录):
    python3 docs/research/s884_sweep_vs_break.py --selftest
    nohup python3 docs/research/s884_sweep_vs_break.py > docs/research/s884_run.txt 2>&1 &      # 写 s884_results.json
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


_argv, sys.argv = sys.argv, [sys.argv[0]]
X = _load("s881", os.path.join(HERE, "s881_setup_mining.py"))        # 状态四格的装载、平移、统计都用它的
sys.argv = _argv
T, G = X.T, X.G

OUT = "docs/research/s884_results.json"
SPLIT, H, LB, RV_WIN, RV_HIST, COMP_PCT = dt.date(2022, 12, 31), 28, 20, 30, 365, 0.20
DMIN, DMAX, FIX = 0.01, 0.12, 0.08
MIN_N, MIN_PAYOFF, N_NULL, SEED = 8, 2.0, 100, 884
SETUPS = {"BREAK_DN": -1, "SWEEP_DN": 1, "BREAK_UP": 1, "SWEEP_UP": -1, "COMP_BREAK_UP": 1, "COMP_BREAK_DN": -1}


def ticket(days, o, h, l, c, idx, D, side: int, dist: float):
    """一张票:D + 1 开盘进,止损 = 进场价 ×(1 − side × dist),拿到 H 天;同一根先看止损;跳空越过按开盘价。与 s865 run_ticket 的 K3 + X0 同一套走法。"""
    i = idx[D] + 1
    if i + H >= len(days):
        return None
    e = o[days[i]]
    stop = e * (1 - side * dist)
    for j in range(i, i + H + 1):
        d = days[j]
        if (l[d] <= stop) if side > 0 else (h[d] >= stop):
            px = min(o[d], stop) if side > 0 else max(o[d], stop)
            p = side * (px - e) / e
            return {"pnl": p, "days": j - i + 1, "stopped": p < 0, "deployed": 1.0}
    p = side * (c[days[i + H]] - e) / e
    return {"pnl": p, "days": H + 1, "stopped": False, "deployed": 1.0}


def rv_pct(days, c) -> dict:
    """D → D 的 30 日实现波动在此前 365 天(各自的 30 日波动)里的分位;只用 D 及以前。"""
    lr = [None] + [math.log(c[days[i]] / c[days[i - 1]]) for i in range(1, len(days))]
    rv = {}
    for i in range(RV_WIN, len(days)):
        w = lr[i - RV_WIN + 1:i + 1]
        rv[days[i]] = float(np.std(w, ddof=1))
    out, ds = {}, [d for d in days if d in rv]
    vals = [rv[d] for d in ds]
    for k in range(RV_HIST, len(ds)):
        hist = vals[k - RV_HIST:k]
        out[ds[k]] = float(np.mean([x <= vals[k] for x in hist]))
    return out


def triggers(days, o, h, l, c) -> dict:
    """{名: [(D, 结构止损的绝对价)]};只用 D 及以前。"""
    out = {k: [] for k in SETUPS}
    rp = rv_pct(days, c)
    for i, d in enumerate(days):
        if d < T.START or i < LB + 1:
            continue
        lo, hi, prev = min(l[x] for x in days[i - LB:i]), max(h[x] for x in days[i - LB:i]), c[days[i - 1]]
        comp = rp.get(d) is not None and rp[d] <= COMP_PCT
        if c[d] < lo <= prev:
            out["BREAK_DN"].append((d, lo * 1.01))
            if comp:
                out["COMP_BREAK_DN"].append((d, lo * 1.01))
        if l[d] < lo <= c[d]:
            out["SWEEP_DN"].append((d, l[d] * 0.995))
        if c[d] > hi >= prev:
            out["BREAK_UP"].append((d, hi * 0.99))
            if comp:
                out["COMP_BREAK_UP"].append((d, hi * 0.99))
        if h[d] > hi >= c[d]:
            out["SWEEP_UP"].append((d, h[d] * 1.005))
    return out


def all_tickets(data: dict) -> dict:
    """{(名, 止损方式): [(D, 票)]} + {('EVERY5', 方向): …}。"""
    out: dict = {}
    for a in T.ASSETS:
        days, o, h, l, c = data[a]
        idx = {d: i for i, d in enumerate(days)}
        for name, lst in triggers(days, o, h, l, c).items():
            side = SETUPS[name]
            for D, stop_px in lst:
                i = idx[D] + 1
                if i >= len(days):
                    continue
                e = o[days[i]]
                struct = (e - stop_px) / e if side > 0 else (stop_px - e) / e
                for mode, dist in (("STRUCT", float(np.clip(struct, DMIN, DMAX))), ("FIX8", FIX)):
                    t = ticket(days, o, h, l, c, idx, D, side, dist)
                    if t:
                        out.setdefault((name, mode), []).append((D, t))
        for side in (-1, 1):
            for D in [d for d in days if d >= T.START][::T.EVERY_N]:
                t = ticket(days, o, h, l, c, idx, D, side, FIX)
                if t:
                    out.setdefault(("EVERY5", side), []).append((D, t))
    return out


def scan(tk: dict, cell: dict) -> list:
    rows = []
    halves = lambda xs: (X.st([x for x in xs if x[0] <= SPLIT]), X.st([x for x in xs if x[0] > SPLIT]))      # noqa: E731
    for name, side in SETUPS.items():
        for mode in ("STRUCT", "FIX8"):
            for cn in X.CELLS:
                ts = [(D, t) for D, t in tk.get((name, mode), []) if cell.get(D) == cn]
                bs = [(D, t) for D, t in tk.get(("EVERY5", side), []) if cell.get(D) == cn]
                (d1, h1), (bd, bh) = halves(ts), halves(bs)
                ok = lambda s, b: bool(s.get("n", 0) >= MIN_N and s["mean_pct"] > 0 and s["payoff"] >= MIN_PAYOFF and s["mean_pct"] > b.get("mean_pct", 0.0))  # noqa: E731
                rows.append({"setup": name, "mode": mode, "cell": cn, "full": X.st(ts), "disc": d1, "hold": h1, "base_disc": bd, "base_hold": bh,
                             "holds": ok(d1, bd) and ok(h1, bh)})
    return rows


def run(data: dict, cell: dict, n_null: int = N_NULL) -> dict:
    tk = all_tickets(data)
    real = scan(tk, cell)
    rng = np.random.default_rng(SEED)
    null = [sum(x["holds"] for x in scan(tk, X.shifted(cell, int(rng.integers(X.MIN_SHIFT, len(cell) - X.MIN_SHIFT))))) for _ in range(n_null)]
    n_real = sum(x["holds"] for x in real)
    uncond = {f"{name}|{mode}": {"disc": X.st([x for x in tk.get((name, mode), []) if x[0] <= SPLIT]),
                                 "hold": X.st([x for x in tk.get((name, mode), []) if x[0] > SPLIT])} for name in SETUPS for mode in ("STRUCT", "FIX8")}
    return {"n_tested": len(real), "n_holds": n_real,
            "null": {"n": n_null, "median": float(np.median(null)), "q95": float(np.quantile(null, 0.95)), "p_ge_real": round(float((np.array(null) >= n_real).mean()), 3)},
            "unconditional": uncond, "rows": real}


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        data, cell, _ = X.synthetic()
    else:
        data, cell, _ = X.load_live()
    out = run(data, cell, n_null=(8 if selftest else N_NULL))
    f = lambda s: f"n{s.get('n')} m{s.get('mean_pct')} win{s.get('win')} pf{s.get('payoff')} w{s.get('worst_pct')}" if s.get("n") else "n0"      # noqa: E731
    print("COUNTS", json.dumps({k: out[k] for k in ("n_tested", "n_holds", "null")}, ensure_ascii=False), flush=True)
    for k, v in out["unconditional"].items():
        print("UNCOND", k, "| disc", f(v["disc"]), "| hold", f(v["hold"]), flush=True)
    for r in out["rows"]:
        if r["mode"] == "STRUCT" or r["holds"]:
            print("ROW", r["setup"], r["mode"], r["cell"], "| disc", f(r["disc"]), "vs", f(r["base_disc"]), "| hold", f(r["hold"]), "vs", f(r["base_hold"]),
                  "| HOLDS" if r["holds"] else "", flush=True)
    if selftest:
        # 走法与 s865 的 K3 + X0 逐张相同(两个方向)
        days, o, h, l, c = data[T.ASSETS[0]]
        idx, atr = {d: i for i, d in enumerate(days)}, T.atr14(days, o, h, l, c)
        for side in (-1, 1):
            for D in [d for d in days if d >= T.START][::37][:40]:
                a, b = ticket(days, o, h, l, c, idx, D, side, 0.08), T.run_ticket(days, o, h, l, c, atr, D, side, "K3", "X0", H)
                assert (a is None) == (b is None) and (a is None or abs(a["pnl"] - b["pnl"]) < 1e-12), (side, D, a, b)
        tr = triggers(days, o, h, l, c)
        cut = days[len(days) // 2]
        tz = triggers([d for d in days if d <= cut], o, h, l, c)
        assert all(tz[k] == [x for x in tr[k] if x[0] <= cut] for k in tr), "触发用到了之后的数据"
        assert tr["SWEEP_DN"] and tr["BREAK_DN"] and not set(d for d, _ in tr["SWEEP_DN"]) & set(d for d, _ in tr["BREAK_DN"]), "同一天不该既是破位又是扫过收回"
        assert out["n_tested"] == len(SETUPS) * 2 * 4
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
