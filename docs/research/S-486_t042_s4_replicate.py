"""S-486: 独立复现 T-042 v1.2 S4 —— sign×sign 交互信号下,四个基线该是什么样。
按 C 报告里写的设计:bg 24 维/日、form 16 维/(币,日) 独立 N(0,1);fwd = Δ·sign(bg)·sign(form) + N(0,0.02);
pinball 分位 [.1,.25,.5,.75,.9];邻居 d ≤ t−10;combo = 背景最近 K=20 天(两两 ≥10 天)里按形态取 10;
pattern = 全部过去按形态取 10(每日 ≤2);bg_only_eq = 背景最近 K 天里随机取 10(每日 ≤2);random = 随机 20 天里随机 10。
另加 bg_only_as_combo:C 的 Fix 2 若把 bg-only 也做成「K 天里按形态取 10」,它就等于 combo。
"""
import numpy as np, sys
MODE = sys.argv[1] if len(sys.argv) > 1 else "sign"
rng = np.random.default_rng(20261005)
ND, NS, BD, FD, K, NN, CAP, GAP, OFF = 500, 24, 24, 16, 20, 10, 2, 10, 10
Q = np.array([.1, .25, .5, .75, .9])
bg = rng.normal(0, 1, (ND, BD)); form = rng.normal(0, 1, (ND, NS, FD))
bs, fs = bg.mean(1), form.mean(2)
if MODE == "sign":
    fwd = 0.2 * np.sign(bs)[:, None] * np.sign(fs) + rng.normal(0, .02, (ND, NS))
elif MODE == "linear":
    p = bs[:, None] * fs; fwd = 0.05 * p / p.std() + rng.normal(0, .02, (ND, NS))
else:
    fwd = rng.normal(0, .02, (ND, NS))
def pin(y, s):
    q = np.quantile(s, Q); e = y - q
    return float(np.mean(np.maximum(Q * e, (Q - 1) * e)))
def gap_dates(order):
    out = []
    for d in order:
        if all(abs(d - x) >= GAP for x in out):
            out.append(d)
            if len(out) >= K: break
    return out
def capped(rows_d, rows_s, order, n):
    cnt, sel = {}, []
    for i in order:
        d = rows_d[i]
        if cnt.get(d, 0) >= CAP: continue
        cnt[d] = cnt.get(d, 0) + 1; sel.append(i)
        if len(sel) >= n: break
    return sel
L = {k: [] for k in ["combo", "pattern", "bg_only_eq", "bg_only_as_combo", "random"]}
keys = [(t, s) for t in range(60, ND) for s in range(NS)]
rng.shuffle(keys)
for t, s in keys[:800]:
    y = fwd[t, s]; cut = t - OFF
    dd, ss = np.meshgrid(np.arange(cut + 1), np.arange(NS), indexing="ij")
    m = ss != s; dd, ss = dd[m], ss[m]
    fdist = np.sqrt(((form[dd, ss] - form[t, s]) ** 2).sum(1))
    bdist = np.sqrt(((bg[:cut + 1] - bg[t]) ** 2).sum(1))
    kd = set(gap_dates(np.argsort(bdist)))
    ink = np.array([d in kd for d in dd])
    o = np.argsort(fdist)
    combo = capped(dd, ss, [i for i in o if ink[i]], NN)
    patt = capped(dd, ss, o, NN)
    bgeq = capped(dd, ss, rng.permutation(np.where(ink)[0]), NN)
    rd = set(gap_dates(rng.permutation(cut + 1)))
    rnd = capped(dd, ss, [i for i in rng.permutation(len(dd)) if dd[i] in rd], NN)
    v = lambda idx: fwd[dd[idx], ss[idx]]
    L["combo"].append(pin(y, v(combo))); L["pattern"].append(pin(y, v(patt)))
    L["bg_only_eq"].append(pin(y, v(bgeq))); L["bg_only_as_combo"].append(pin(y, v(combo)))
    L["random"].append(pin(y, v(rnd)))
def boot(a, b, B=2000, bs_=30):
    d = np.array(a) - np.array(b); n = len(d) // bs_
    r = np.random.default_rng(1)
    m = [np.concatenate([d[i*bs_:(i+1)*bs_] for i in r.integers(0, n, n)]).mean() for _ in range(B)]
    m = np.array(m)
    return d.mean(), float((m < 0).mean()), float((m <= 0).mean()), float((d == 0).mean())
print(f"MODE={MODE} n={len(L['combo'])}")
for a, b in [("combo","random"),("combo","pattern"),("combo","bg_only_eq"),("combo","bg_only_as_combo"),
             ("pattern","random"),("bg_only_eq","random"),("bg_only_as_combo","random")]:
    md, p_strict, p_tie_as_win, tie = boot(L[a], L[b])
    print(f"  {a:>16} vs {b:<16} meandiff={md:+.5f}  p(a<b)={p_strict:.3f}  p_C式(<=0)={p_tie_as_win:.3f}  ties={tie:.0%}")
