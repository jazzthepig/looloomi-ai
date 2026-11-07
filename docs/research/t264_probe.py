"""T-264 探针 #4(单文件,反复改同一个文件跑;不产生最终产物)。

三件事:
 1. **BH 重算**:T2 的方向与台账预注册相反(IC +0.147 而预期负)。若把方向翻过来
    (事后翻,本身违反预注册,只能当探索),BH q 会是多少?—— 检验「翻过来就能过吗」。
 2. **双边残差控制时间**:把特征与结果**都**对日期序号取秩回归残差后再算偏相关
    (比只残差结果更严),看 T4 的 +0.171 是否只是「越晚回撤越浅」+「越晚杠杆占比越高」
    的日历影子。
 3. **零分布紧凑化变体**:主跑的空分布是 np.roll(整条序列)后按原 valid 掩码取样,
    而特征前段有暖机 NaN(F2/F3 前 ~90 天),滚动后掩码与数据错位 ⇒ 每次抽样的
    有效子集略有不同。这里改成「先把有效子序列压紧,再循环滚动」重算分位,
    看 T2 反向 p=0.042 是否稳。

只读。
"""
from __future__ import annotations

import os
import sys

import numpy as np
from scipy.stats import spearmanr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import t264_venue as T  # noqa: E402
from t264_venue import bh_qvalues  # noqa: E402


def main():
    fmd = T.load_fmd()
    perp = T.load_perp_btc()
    ohlcv = T.load_ohlcv(list(T.PANEL_24))
    fseries = T.feature_series_from_view(fmd)
    outs = T.build_outcomes(perp, ohlcv)

    all_dates = sorted({d for k in T.FEATURE_KEYS.values() for d in fseries.get(k, {})})
    dates = np.array(all_dates)

    def align(s):
        arr = np.full(len(all_dates), np.nan)
        for i, d in enumerate(all_dates):
            if d in s:
                arr[i] = s[d]
        return arr

    def ovec(mp):
        arr = np.full(len(all_dates), np.nan)
        for i, d in enumerate(all_dates):
            v = mp.get(d)
            if v is not None:
                arr[i] = v
        return arr

    raw = {k: align(fseries.get(k, {})) for k in T.FEATURE_KEYS.values()}
    F = {
        "F1": raw[T.FEATURE_KEYS["F1"]] - T.trailing_mean(raw[T.FEATURE_KEYS["F1"]], 180),
        "F2": T.trailing_percentile(raw[T.FEATURE_KEYS["F2"]], 365),
        "F3": T.trailing_percentile(raw[T.FEATURE_KEYS["F3"]], 365),
    }
    o_ret30 = ovec(outs["btc_ret30"])
    o_mdd30 = ovec(outs["btc_mdd30"])
    o_exc30 = ovec(outs["alt_exc30"])
    tidx = np.arange(len(dates), dtype=float)

    cases = [("T1", "F1", o_ret30, "+"), ("T2", "F2", o_ret30, "-"),
             ("T3", "F2", o_exc30, "-"), ("T4", "F3", o_mdd30, "-"),
             ("T5", "F3", o_ret30, "0")]

    # ── 1. BH 重算(原方向 vs 全翻转) ────────────────────────────────
    print("=== 1. BH(q=0.10,跨 5 检验)重算 ===")
    p_orig = [0.455, 0.958, 0.512, 0.902, 0.245]   # 主跑 p_one_sided(原方向)
    q_orig = bh_qvalues(p_orig, 0.10)
    print("  原方向 p:", p_orig, "→ q:", [round(x, 5) for x in q_orig])
    # 翻方向:把预注册方向反过来后的单侧 p(主跑里 pct 已给,反向后 p = 1 - p)
    p_flip = [round(1 - p, 5) for p in p_orig]
    q_flip = bh_qvalues(p_flip, 0.10)
    print("  全翻转 p:", p_flip, "→ q:", [round(x, 5) for x in q_flip])
    print("  全翻转后过 BH(q<=0.10)的条数:", sum(1 for x in q_flip if x is not None and x <= 0.10))

    # ── 2. 双边残差控制时间 ────────────────────────────────────────
    print("\n=== 2. 特征与结果都对时间取残差后的偏 Spearman ===")

    def resid_on_time(v):
        m = np.isfinite(v)
        res = np.full(v.shape, np.nan)
        x = np.argsort(np.argsort(tidx[m])).astype(float)
        y = np.argsort(np.argsort(v[m])).astype(float)
        beta, alpha = np.polyfit(x, y, 1)
        res[m] = y - (alpha + beta * x)
        return res

    for code, fk, ov in (("T1", "F1", o_ret30), ("T2", "F2", o_ret30), ("T3", "F2", o_exc30),
                         ("T4", "F3", o_mdd30), ("T5", "F3", o_ret30)):
        rf = resid_on_time(F[fk])
        ro = resid_on_time(ov)
        m = np.isfinite(rf) & np.isfinite(ro)
        if m.sum() < 50:
            continue
        sp = spearmanr(rf[m], ro[m]).statistic
        print(f"  {code} {fk}: 控制时间后偏 IC={sp:+.4f} n={int(m.sum())}")

    # ── 3. 零分布紧凑化变体 ────────────────────────────────────────
    print("\n=== 3. 零分布:压缩有效子序列后再循环滚动(重算分位) ===")
    N, SEED, MIN_SHIFT = T.N_NULL, T.SEED, T.MIN_SHIFT

    def null_compact(feat, outcome, seed):
        rng = np.random.default_rng(seed)
        m = np.isfinite(feat) & np.isfinite(outcome)
        x, y = feat[m], outcome[m]
        n = x.size
        out = np.empty(N)
        for i in range(N):
            s = int(rng.integers(MIN_SHIFT, n - MIN_SHIFT + 1))
            out[i] = spearmanr(np.roll(x, s), y).statistic
        return out

    for code, fk, ov, expect in cases:
        m = np.isfinite(F[fk]) & np.isfinite(ov)
        x, y = F[fk][m], ov[m]
        ic = spearmanr(x, y).statistic
        null = null_compact(F[fk], ov, SEED)
        null = null[np.isfinite(null)]
        if expect == "+":
            pct = T.percentile_of(ic, null)
        elif expect == "-":
            pct = 1.0 - T.percentile_of(ic, null)
        else:
            pct = T.percentile_of(abs(ic), np.abs(null))
        # 反向分位(翻方向后)
        if expect == "+":
            pct_rev = 1.0 - T.percentile_of(ic, null)
        elif expect == "-":
            pct_rev = T.percentile_of(ic, null)
        else:
            pct_rev = pct
        print(f"  {code}: IC={ic:+.4f} | 原方向分位={pct:.4f} | 反向分位={pct_rev:.4f} "
              f"| null |q95|={np.quantile(np.abs(null), 0.95):.4f} n={int(m.sum())}")


if __name__ == "__main__":
    main()
