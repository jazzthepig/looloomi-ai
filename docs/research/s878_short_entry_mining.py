"""S-878:空单「什么时候进」的挖掘 —— 向量的 56 个键里,哪一个在高 / 低位时,空单(Jazz 的管法与近止损)之后是挣的。

S-874:管法救不了进场 —— 机械进场下 360 种远止损 / 加仓没有一种盈亏比过 2,连近止损 2023 年后也略负。Jazz 的原话里进场本身是判断
(「进入观察、反转之前情绪冲得很猛」)。这里把判断拆成可查的条件:每张票进场那天,每个键的按时点 z 落在低位(< −0.5)还是高位(> +0.5),
分桶看三种管法的票:
  JZ_add  基准 25%、波动大则更远、三笔 20 / 30 / 50%(越冲越多)、28 天 —— Jazz 的写法
  JZ_one  同上但一次进满
  NEAR12  固定 12%、一次进满、28 天 —— S-874 里过了盈亏比的那一类
进场日 = 每隔 5 天(BTC / ETH 各自;不带任何别的条件)。一个桶「过发现段」= 2022 年底以前 票数 ≥ 30、均值 > 0、盈亏比 ≥ 2;
「留出段确认」= 2023 年起 票数 ≥ 20、均值 > 0、盈亏比 ≥ 2。56 键 × 2 桶 × 3 种管法 = 336 个桶,靠运气也会过几个 ——
所以把每个键的分桶序列整条平移(≥ 180 天)100 次,数「确认」的桶数,真数落在哪。预期、判法与后果写在台账 S-878(先登记,后计算)。

用法(仓库根目录):
    python3 docs/research/s878_short_entry_mining.py --selftest
    nohup python3 docs/research/s878_short_entry_mining.py > docs/research/s878_run.txt 2>&1 &      # 写 s878_results.json
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
G = _load("s874", os.path.join(HERE, "s874_short_scale_in.py"))          # 票的走法原样用 S-874 的 ticket()
sys.argv = _argv
T = G.T
FK = _load("fused_knn", os.path.join(ROOT, "src", "data", "state", "fused_knn.py"))

OUT = "docs/research/s878_results.json"
SPLIT, END = dt.date(2022, 12, 31), dt.date(2026, 11, 13)
FORMS = {"JZ_add": (0.25, -1, "A3w"), "JZ_one": (0.25, -1, "A0"), "NEAR12": (0.12, 0, "A0")}
H, Z_CUT, N_NULL, MIN_SHIFT, SEED = 28, 0.5, 100, 180, 878
MIN_N_DISC, MIN_N_HOLD, MIN_PAYOFF = 30, 20, 2.0


def tickets(data: dict) -> dict:
    """{管法: [(进场信号日 D, 盈亏占满仓名义)]};BTC、ETH 合在一起。"""
    out = {f: [] for f in FORMS}
    for a in T.ASSETS:
        days, o, h, l, c = data[a]
        idx = {d: i for i, d in enumerate(days)}
        atr = T.atr14(days, o, h, l, c)
        sr = G.sigma_ref(days, atr, c)
        for D in T.entry_days(days, c, -1, "all"):
            if D not in atr:
                continue
            for f, (base, gam, sch) in FORMS.items():
                if gam == 0:
                    dist = base
                elif D in sr:
                    dist = float(np.clip(base * (sr[D][1] / sr[D][0]) ** gam, G.DIST_MIN, G.DIST_MAX))
                else:
                    continue
                t = G.ticket(days, o, h, l, c, idx, D, dist, sch, H, None)
                if t:
                    out[f].append((D, t["pnl"]))
    return out


def stats(p: list) -> dict:
    if not p:
        return {"n": 0}
    a = np.array(p)
    win, loss = a[a > 0], a[a < 0]
    pf = 0.0 if not len(win) else (99.0 if not len(loss) else float(win.mean() / abs(loss.mean())))
    return {"n": int(len(a)), "mean_pct": round(float(a.mean()) * 100, 2), "win": round(float((a > 0).mean()), 3), "payoff": round(pf, 2),
            "worst_pct": round(float(a.min()) * 100, 2)}


def ok(s: dict, min_n: int) -> bool:
    return bool(s.get("n", 0) >= min_n and s["mean_pct"] > 0 and s["payoff"] >= MIN_PAYOFF)


def scan(tk: dict, buckets: dict) -> list:
    """buckets = {键: {日: 'lo' | 'hi' | 'mid'}}。→ 每个(管法, 键, 桶)的发现段 / 留出段读数与是否确认。"""
    rows = []
    for f, ts in tk.items():
        for k, b in buckets.items():
            for side in ("lo", "hi"):
                disc = stats([p for D, p in ts if D <= SPLIT and b.get(D) == side])
                if not ok(disc, MIN_N_DISC):
                    continue
                hold = stats([p for D, p in ts if D > SPLIT and b.get(D) == side])
                rows.append({"form": f, "key": k, "bucket": side, "disc": disc, "hold": hold, "confirmed": ok(hold, MIN_N_HOLD)})
    return rows


def shifted(b: dict, k: int) -> dict:
    ds = sorted(b)
    v = [b[d] for d in ds]
    return {d: v[(i - k) % len(ds)] for i, d in enumerate(ds)}


def run(data: dict, z: dict, n_null: int = N_NULL) -> dict:
    tk = tickets(data)
    buckets = {}
    for j, k in enumerate(FK.KEYS):
        b = {d: ("lo" if v[j] < -Z_CUT else "hi" if v[j] > Z_CUT else "mid") for d, v in z.items() if v[j] is not None}
        if len(b) >= 1000:
            buckets[k] = b
    real = scan(tk, buckets)
    rng = np.random.default_rng(SEED)
    null_q, null_c = [], []
    for _ in range(n_null):
        sb = {k: shifted(b, int(rng.integers(MIN_SHIFT, len(b) - MIN_SHIFT))) for k, b in buckets.items()}
        r = scan(tk, sb)
        null_q.append(len(r))
        null_c.append(sum(x["confirmed"] for x in r))
    nq, nc = len(real), sum(x["confirmed"] for x in real)
    return {"unconditional": {f: {"disc": stats([p for D, p in ts if D <= SPLIT]), "hold": stats([p for D, p in ts if D > SPLIT])} for f, ts in tk.items()},
            "n_buckets_tested": len(buckets) * 2 * len(FORMS), "n_qualified_disc": nq, "n_confirmed": nc,
            "null": {"n": n_null, "qualified_median": float(np.median(null_q)), "qualified_q95": float(np.quantile(null_q, 0.95)),
                     "confirmed_median": float(np.median(null_c)), "confirmed_q95": float(np.quantile(null_c, 0.95)),
                     "p_confirmed_ge_real": round(float((np.array(null_c) >= nc).mean()), 3)},
            "confirmed": sorted([x for x in real if x["confirmed"]], key=lambda x: -x["hold"]["mean_pct"]),
            "qualified_not_confirmed": sorted([x for x in real if not x["confirmed"]], key=lambda x: -x["disc"]["mean_pct"])[:15]}


def load_live():
    S = _load("s851", os.path.join(HERE, "s851_watch_base_rate.py"))
    rows = S.get("feature_matrix_daily", {"select": "d,f", "d": "gte.2019-01-01", "order": "d.asc"})
    z = {dt.date.fromisoformat(k): v for k, v in FK.pit_vectors(rows).items()}
    data = {a: ([d for d in v[0] if d <= END], *v[1:]) for a, v in T.load_live().items()}
    return data, z


def synthetic():
    data = T.synthetic()
    data[T.ASSETS[1]] = data[T.ASSETS[0]]                                  # 自检里两只资产用同一条价格:种进去的信号对两边都成立
    days, o, h, l, c = data[T.ASSETS[0]]
    rng = np.random.default_rng(SEED)
    z = {}
    for i, d in enumerate(days):
        fut = (c[days[min(i + 28, len(days) - 1)]] / c[d] - 1) if i + 28 < len(days) else 0.0
        v = [float(rng.normal(0, 1)) for _ in FK.KEYS]
        v[0] = 1.5 if fut < -0.08 else -1.0                                # 第 0 个键:偷看了未来(只为自检 —— 它应当被挖出来)
        z[d] = v
    return data, z


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    data, z = synthetic() if selftest else load_live()
    out = run(data, z, n_null=(10 if selftest else N_NULL))
    print("UNCONDITIONAL", json.dumps(out["unconditional"], ensure_ascii=False), flush=True)
    print("COUNTS", json.dumps({k: out[k] for k in ("n_buckets_tested", "n_qualified_disc", "n_confirmed", "null")}, ensure_ascii=False), flush=True)
    for x in out["confirmed"][:20]:
        print("CONFIRMED", json.dumps(x, ensure_ascii=False), flush=True)
    for x in out["qualified_not_confirmed"][:8]:
        print("DISC_ONLY", json.dumps(x, ensure_ascii=False), flush=True)
    if selftest:
        keys = {(x["key"], x["bucket"]) for x in out["confirmed"]}
        assert (FK.KEYS[0], "hi") in keys, "偷看未来的那个键在高位时空单应当被确认(自检用的合成信号)"
        assert out["n_confirmed"] > out["null"]["confirmed_q95"], out["null"]
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
