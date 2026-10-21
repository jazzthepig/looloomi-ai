"""S-664:S-661 的价值捕获比(V4)控制规模 / 波动 / 稀释之后还剩不剩 —— 预注册见台账(2026-10-21 16:45 UTC)。

复用 s661_value_mining.py 的数据与截面;每个月末在截面内把 V4 对 ln(市值)、90 日波动、90 日流通量增长做最小二乘,
取残差算与之后 1 个月相对收益的 Spearman IC。
用法:python3 docs/research/s664_value_vs_quality.py [--root …]
"""
from __future__ import annotations

import bisect
import datetime as dt
import importlib.util
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("s661", os.path.join(HERE, "s661_value_mining.py"))
m = importlib.util.module_from_spec(_spec)
sys.modules["s661"] = m
_spec.loader.exec_module(m)
SEED = 664


def vol90(ser, t):
    i = bisect.bisect_right(ser, (t, float("inf"), float("inf")))
    seg = [x for x in ser[max(0, i - 91):i]]
    if len(seg) < 60:
        return None
    r = [math.log(seg[k][1] / seg[k - 1][1]) for k in range(1, len(seg)) if seg[k - 1][1] > 0 and seg[k][1] > 0]
    mu = sum(r) / len(r)
    return math.sqrt(sum((x - mu) ** 2 for x in r) / (len(r) - 1))


def supply_growth(ser, t):
    a, b = m.at(ser, t), m.at(ser, t - dt.timedelta(days=90), tol=7)
    if not a or not b or not a[1] or not b[1] or not a[2] or not b[2]:
        return None
    s1, s0 = a[2] / a[1], b[2] / b[1]
    return math.log(s1 / s0) if s0 > 0 and s1 > 0 else None


def ols_resid(y, X):
    """y ~ 1 + X(最小二乘,正规方程,列数很少)。"""
    n, k = len(y), len(X[0]) + 1
    A = [[1.0] + list(x) for x in X]
    ata = [[sum(A[r][i] * A[r][j] for r in range(n)) for j in range(k)] for i in range(k)]
    aty = [sum(A[r][i] * y[r] for r in range(n)) for i in range(k)]
    # 高斯消元
    M = [row[:] + [aty[i]] for i, row in enumerate(ata)]
    for c in range(k):
        p = max(range(c, k), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            return None
        M[c], M[p] = M[p], M[c]
        for r in range(k):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [M[r][j] - f * M[c][j] for j in range(k + 1)]
    beta = [M[i][k] / M[i][i] for i in range(k)]
    return [y[r] - sum(beta[i] * A[r][i] for i in range(k)) for r in range(n)]


def run(window, rev, hrev, start, px):
    out = {"resid": [], "lnmcap": [], "vol": [], "supply": [], "quality": [], "v4": []}
    for t in m.month_ends(*window):
        rows = m.cross_section(t, rev, hrev, start, px)
        pts = []
        for r in rows:
            if r.get("V4") is None or r.get("x1m") is None:
                continue
            v, sg = vol90(px[r["g"]], t), supply_growth(px[r["g"]], t)
            if v is None or sg is None:
                continue
            pts.append((r["V4"], math.log(r["mcap"]), v, sg, r["x1m"]))
        if len(pts) < m.MIN_XS + 2:
            continue
        y = [p[4] for p in pts]
        e = ols_resid([p[0] for p in pts], [p[1:4] for p in pts])
        if e is None:
            continue
        out["resid"].append((t, m.spearman(e, y)))
        out["v4"].append((t, m.spearman([p[0] for p in pts], y)))
        out["lnmcap"].append((t, m.spearman([p[1] for p in pts], y)))
        out["vol"].append((t, m.spearman([-p[2] for p in pts], y)))
        out["supply"].append((t, m.spearman([-p[3] for p in pts], y)))
        rk_m = {i: k for k, i in enumerate(sorted(range(len(pts)), key=lambda i: pts[i][1]))}
        rk_v = {i: k for k, i in enumerate(sorted(range(len(pts)), key=lambda i: pts[i][2]))}
        out["quality"].append((t, m.spearman([rk_m[i] - rk_v[i] for i in range(len(pts))], y)))
    return out


def stats(ser, boot=False):
    ics = [i for _, i in ser]
    n = len(ics)
    mu = sum(ics) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in ics) / (n - 1))
    res = {"months": n, "mean_ic": round(mu, 4), "t": round(mu / (sd / math.sqrt(n)), 2)}
    if boot:
        rng = random.Random(SEED)
        blocks = [ics[i:i + 3] for i in range(0, n, 3)]
        bs = []
        for _ in range(2000):
            d = [x for _b in range(len(blocks)) for x in rng.choice(blocks)]
            bs.append(sum(d) / len(d))
        res["p_block_boot"] = sum(1 for b in bs if b <= 0) / len(bs)
    return res


def main():
    rev, hrev, start, px = m.load()
    res = {}
    for lab, win in (("discovery", m.DISC), ("holdout", m.HOLD)):
        o = run(win, rev, hrev, start, px)
        res[lab] = {k: stats(v, boot=(k == "resid" and lab == "holdout")) for k, v in o.items()}
    h, d = res["holdout"]["resid"], res["discovery"]["resid"]
    res["verdict"] = "过" if (h["mean_ic"] > 0 and h["p_block_boot"] < 0.05 and d["mean_ic"] > 0) else "不过"
    json.dump(res, open(os.path.join(HERE, "s664_results.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
