"""S-881:按「形态」挖,不按「因子」挖 —— 状态(向量切出来的格子)× 价格自己先动(触发)× 当时人群站在哪边(持仓读数)。

Jazz 2026-11-15:「你还是默认跑了简单因子复现的路线,根本没有利用我们建立的优势。」到 S-878 为止挖的都是「日历进场 × 单个读数」,
全部不成立;唯一在留出段站住的 S-879 是另一种东西:**状态对 + 价格自己先破位 + 错了的标准写在价格上**。这里把那个模板摊开:

  触发(D 日收盘判、D + 1 开盘进;BTC / ETH 各自;固定 8% 止损、28 天、一次进满 —— 管法不是这次的变量)
      BD20  收盘跌破此前 20 天最低 ⇒ 空          BO20  收盘突破此前 20 天最高 ⇒ 多
  状态  趋势(面板离 200 日线的正负)× 谁在领(主流 30 日 − 二线 L1 / L2 30 日 的按时点 z 是否 > 0)—— 四格
  人群  触发那天四个持仓读数各自的按时点 z:高(> +0.5)/ 低(< −0.5)
        资金费(funding_7d_ann_binance)· 散户多空(pos:btc_crowd_ln)· 大户减散户(pos:btc_smart_minus_crowd)· 主动买入占比(taker_buy_share_30d)
  对照  同一格、同一方向、不看触发每 5 天一张
一个形态「站得住」= 发现段(≤ 2022)与留出段(2023 起)**都** 票数够、均值 > 0、盈亏比 ≥ 2、且均值高于同格同向的日历对照。
防自欺:状态与持仓读数的序列整条平移(≥ 180 天)100 次,数「站得住」的个数。预期与后果写在台账 S-881(先登记,后计算)。

用法(仓库根目录):
    python3 docs/research/s881_setup_mining.py --selftest
    nohup python3 docs/research/s881_setup_mining.py > docs/research/s881_run.txt 2>&1 &      # 写 s881_results.json
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


_argv, sys.argv = sys.argv, [sys.argv[0]]
B = _load("s879", os.path.join(HERE, "s879_breakdown_short.py"))
sys.argv = _argv
G, T = B.G, B.T
FK = _load("fused_knn", os.path.join(ROOT, "src", "data", "state", "fused_knn.py"))

OUT = "docs/research/s881_results.json"
SPLIT, END, H, LOOKBACK = dt.date(2022, 12, 31), dt.date(2026, 11, 13), 28, 20
CROWD = ("funding_7d_ann_binance", "pos:btc_crowd_ln", "pos:btc_smart_minus_crowd", "taker_buy_share_30d")
LEAD_KEY, Z_CUT, N_NULL, MIN_SHIFT, SEED = "style_rel_majors_30d", 0.5, 100, 180, 881
MIN_N_CELL, MIN_N_CROWD, MIN_PAYOFF = 12, 8, 2.0
CELLS = ("线上·主流领", "线上·二线领", "线下·主流领", "线下·二线领")


def breakouts(days, h, c) -> list:
    out = []
    for i, d in enumerate(days):
        if d < T.START or i < LOOKBACK + 1:
            continue
        hi = max(h[x] for x in days[i - LOOKBACK:i])
        if c[d] > hi >= c[days[i - 1]]:
            out.append(d)
    return out


def tickets(data: dict) -> dict:
    """{(触发, 方向): [(D, 票)]};BTC、ETH 合在一起。"""
    out: dict = {}
    for a in T.ASSETS:
        days, o, h, l, c = data[a]
        atr = T.atr14(days, o, h, l, c)
        every = [d for d in days if d >= T.START][::T.EVERY_N]
        sets = {("BD20", -1): [d for d, _ in B.signals(days, l, c)["BD20"]], ("BO20", 1): breakouts(days, h, c),
                ("EVERY5", -1): every, ("EVERY5", 1): every}
        for key, sig in sets.items():
            for D in sig:
                if D not in atr:
                    continue
                t = T.run_ticket(days, o, h, l, c, atr, D, key[1], "K3", "X0", H)
                if t:
                    out.setdefault(key, []).append((D, {**t, "deployed": 1.0}))
    return out


def st(ts: list) -> dict:
    return G.summ([t for _, t in ts])


def good(s: dict, base: dict, min_n: int) -> bool:
    return bool(s.get("n", 0) >= min_n and s["mean_pct"] > 0 and s["payoff"] >= MIN_PAYOFF and s["mean_pct"] > base.get("mean_pct", 0.0))


def scan(tk: dict, cell: dict, crowd: dict) -> list:
    rows = []
    for (trig, side) in (("BD20", -1), ("BO20", 1)):
        for cn in CELLS:
            ts = [(D, t) for D, t in tk.get((trig, side), []) if cell.get(D) == cn]
            bs = [(D, t) for D, t in tk.get(("EVERY5", side), []) if cell.get(D) == cn]
            halves = lambda xs: (st([x for x in xs if x[0] <= SPLIT]), st([x for x in xs if x[0] > SPLIT]))      # noqa: E731
            (d1, h1), (bd, bh) = halves(ts), halves(bs)
            rows.append({"setup": f"{trig}|{cn}", "crowd": None, "full": st(ts), "disc": d1, "hold": h1, "base_disc": bd, "base_hold": bh,
                         "holds": good(d1, bd, MIN_N_CELL) and good(h1, bh, MIN_N_CELL)})
            for k, b in crowd.items():
                for bucket in ("lo", "hi"):
                    sub = [(D, t) for D, t in ts if b.get(D) == bucket]
                    s1, s2 = halves(sub)
                    if s1.get("n", 0) >= MIN_N_CROWD and s2.get("n", 0) >= MIN_N_CROWD:
                        rows.append({"setup": f"{trig}|{cn}", "crowd": f"{k}:{bucket}", "full": st(sub), "disc": s1, "hold": s2, "base_disc": bd, "base_hold": bh,
                                     "holds": good(s1, bd, MIN_N_CROWD) and good(s2, bh, MIN_N_CROWD)})
    return rows


def shifted(x: dict, k: int) -> dict:
    ds = sorted(x)
    v = [x[d] for d in ds]
    return {d: v[(i - k) % len(ds)] for i, d in enumerate(ds)}


def run(data: dict, cell: dict, crowd: dict, n_null: int = N_NULL) -> dict:
    tk = tickets(data)
    real = scan(tk, cell, crowd)
    rng = np.random.default_rng(SEED)
    null_cell, null_crowd = [], []
    for _ in range(n_null):
        k = int(rng.integers(MIN_SHIFT, len(cell) - MIN_SHIFT))
        r = scan(tk, shifted(cell, k), {key: shifted(b, k) for key, b in crowd.items()})
        null_cell.append(sum(x["holds"] for x in r if x["crowd"] is None))
        null_crowd.append(sum(x["holds"] for x in r if x["crowd"] is not None))
    n_cell = sum(x["holds"] for x in real if x["crowd"] is None)
    n_crowd = sum(x["holds"] for x in real if x["crowd"] is not None)
    return {"n_tested_cell": sum(1 for x in real if x["crowd"] is None), "n_tested_crowd": sum(1 for x in real if x["crowd"] is not None),
            "n_holds_cell": n_cell, "n_holds_crowd": n_crowd,
            "null": {"n": n_null, "cell_median": float(np.median(null_cell)), "cell_q95": float(np.quantile(null_cell, 0.95)),
                     "p_cell_ge_real": round(float((np.array(null_cell) >= n_cell).mean()), 3),
                     "crowd_median": float(np.median(null_crowd)), "crowd_q95": float(np.quantile(null_crowd, 0.95)),
                     "p_crowd_ge_real": round(float((np.array(null_crowd) >= n_crowd).mean()), 3)},
            "cells": [x for x in real if x["crowd"] is None], "crowd_holds": [x for x in real if x["crowd"] is not None and x["holds"]],
            "cell_days": {cn: sum(1 for v in cell.values() if v == cn) for cn in CELLS}}


def load_live():
    S = _load("s851", os.path.join(HERE, "s851_watch_base_rate.py"))
    rows = S.get("feature_matrix_daily", {"select": "d,f", "d": "gte.2019-01-01", "order": "d.asc"})
    z = {dt.date.fromisoformat(k): v for k, v in FK.pit_vectors(rows).items()}
    raw = {dt.date.fromisoformat(str(r["d"])[:10]): (r.get("f") or {}) for r in rows}
    j = FK.KEYS.index(LEAD_KEY)
    cell = {}
    for d, v in z.items():
        x = raw.get(d, {}).get("dist_200")
        if x is not None and v[j] is not None:
            cell[d] = ("线下" if float(x) < 0 else "线上") + "·" + ("主流领" if v[j] > 0 else "二线领")
    crowd = {}
    for k in CROWD:
        i = FK.KEYS.index(k)
        crowd[k] = {d: ("lo" if v[i] < -Z_CUT else "hi" if v[i] > Z_CUT else "mid") for d, v in z.items() if v[i] is not None}
    data = {a: ([d for d in v[0] if d <= END], *v[1:]) for a, v in T.load_live().items()}
    return data, cell, crowd


def synthetic():
    data = T.synthetic()
    days, o, h, l, c = data[T.ASSETS[0]]
    rng = np.random.default_rng(SEED)
    cell, crowd = {}, {k: {} for k in CROWD}
    for i, d in enumerate(days):
        if i >= 200:
            below = c[d] < float(np.mean([c[x] for x in days[i - 199:i + 1]]))
            cell[d] = ("线下" if below else "线上") + "·" + ("主流领" if (i // 70) % 2 == 0 else "二线领")
            for k in CROWD:
                crowd[k][d] = ("lo", "mid", "hi")[int(rng.integers(0, 3))]
    return data, cell, crowd


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    data, cell, crowd = synthetic() if selftest else load_live()
    out = run(data, cell, crowd, n_null=(8 if selftest else N_NULL))
    print("COUNTS", json.dumps({k: out[k] for k in ("n_tested_cell", "n_tested_crowd", "n_holds_cell", "n_holds_crowd", "null", "cell_days")}, ensure_ascii=False), flush=True)
    f = lambda s: f"n{s.get('n')} m{s.get('mean_pct')} pf{s.get('payoff')}" if s.get("n") else "n0"      # noqa: E731
    for x in out["cells"]:
        print("CELL", x["setup"], "| disc", f(x["disc"]), "vs base", f(x["base_disc"]), "| hold", f(x["hold"]), "vs base", f(x["base_hold"]), "| HOLDS" if x["holds"] else "", flush=True)
    for x in out["crowd_holds"]:
        print("CROWD", x["setup"], x["crowd"], "| disc", f(x["disc"]), "| hold", f(x["hold"]), flush=True)
    if selftest:
        days, o, h, l, c = data[T.ASSETS[0]]
        bo = breakouts(days, h, c)
        cut = days[len(days) // 2]
        assert bo and breakouts([d for d in days if d <= cut], h, c) == [d for d in bo if d <= cut], "突破信号用到了之后的数据"
        assert out["n_tested_cell"] == 8 and set(out["cell_days"]) == set(CELLS)
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
