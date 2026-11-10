#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-324 敏感性 —— §Seth-1110a 第 2 条。

P 臂在 ① 的 24 名面板上有 **686 个成员-周没有分**(资产流宇宙不含 MATIC / SHIB / CRO / GRAM 等),
`_zmap` 把「没有分」当成 z = 0 ⇒ 这些成员照拿 1/N —— 「不可算当成值」。
本脚本把这些成员-周**剔除**(该周面板只剩有分的成员,被剔除的成员当周权重 0 = 空仓),
重算 P 臂,报判据 (i)(P 总收益 ≥ M52)是否变。

自检:同一套代码先重算**未剔除**的 P 臂与 M52,必须逐位复现 `t324_results.json` 的
P cum 0.6364375528909263 / M52 cum 1.1474668426072934 —— 不复现则本脚本不可信,直接报错退出。

零分布与 A/B 只走 `src/data/evaluation/apparatus.py`(ab_test,mean_block=20, n_boot=2000, seed=802)。
只读;结果写 `t324_noscore_sens.json`。
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "t324_noscore_sens.json"

spec = importlib.util.spec_from_file_location("t324_p_tilt", HERE / "t324_p_tilt.py")
t324 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t324)
t312 = t324.t312
ap = t324._load_apparatus()

# 主结果的自检基准(t324_results.json → arms)
BASE_P_CUM = 0.6364375528909263
BASE_M52_CUM = 1.1474668426072934


def main():
    mem, mem_by_month, Pcal, R, pmeta = t324._load_panel()
    all_syms = sorted({r["symbol"] for r in mem})
    per_sym, sc = t324._p_predictions()
    print("面板 %d 行成员 / %d 个币;P 臂自检 IC 均值 %.6f(S-791 发表 %.6f)"
          % (len(mem), len(all_syms), sc["ic_mean"], sc["published"]), flush=True)

    mondays = [pd.Timestamp(x) for x in t312._mondays(t324.SIGNAL_START, t324.SIGNAL_END)]
    days = pd.date_range(pd.Timestamp(t324.SIGNAL_START),
                          pd.Timestamp(t324.SIGNAL_END) + pd.Timedelta(days=1), freq="D")

    # ── 逐周的面板与两个信号(与 t324_p_tilt.cmd_run 同构)─────────────────────
    panel_of, m52_of, p_of = {}, {}, {}
    n_noscore_p = 0
    for t in mondays:
        month = t.strftime("%Y-%m-01")
        members = [s for s in mem_by_month.get(month, []) if s in Pcal.columns]
        px = Pcal.loc[t] if t in Pcal.index else pd.Series(dtype=float)
        panel = [s for s in members if s in px.index and np.isfinite(px[s])]
        panel_of[t] = panel

        sc52 = {}
        if panel:
            sub = Pcal[panel]
            rk = lambda X: X.rank(axis=1, pct=True)
            mom = {n: sub / sub.shift(n) - 1.0 for n in (14, 28, 90)}
            mc = (rk(mom[14]) + rk(mom[28]) + rk(mom[90])) / 3.0
            h52 = sub / sub.rolling(365, min_periods=180).max()
            combo = (rk(mc) + rk(h52)) / 2.0
            row = combo.loc[t] if t in combo.index else pd.Series(dtype=float)
            for s in panel:
                v = row.get(s, np.nan)
                sc52[s] = float(v) if np.isfinite(v) else None
        m52_of[t] = sc52

        scp = {}
        for s in panel:
            ds, vals = per_sym.get(s, (None, None))
            if ds is None or len(ds) == 0:
                continue
            j = int(np.searchsorted(ds, t.strftime("%Y-%m-%d"), side="right")) - 1
            if j < 0:
                continue
            v = float(vals[j])
            if np.isfinite(v):
                scp[s] = v
        p_of[t] = scp
        n_noscore_p += len(panel) - len(scp)

    def hold_target(t):
        p = panel_of.get(t, [])
        if not p:
            return None
        return pd.Series(1.0 / len(p), index=p)

    def tilt(scores, scored_only=False):
        def f(t):
            p = panel_of.get(t, [])
            sc = scores.get(t, {})
            if scored_only:                      # 剔除:该周只留有分的成员
                p = [s for s in p if sc.get(s) is not None]
            if not p:
                return None
            z = t324._zmap({s: sc.get(s) for s in p})
            w = pd.Series({s: (1.0 / len(p)) * (1.0 + t324.K * z[s]) for s in p}).clip(lower=0.0)
            if w.sum() <= 0:
                return None
            return w / w.sum()
        return f

    r_hold, to_h = t324._run_arm(days, R, all_syms, Pcal, hold_target)
    r_m52, to_m = t324._run_arm(days, R, all_syms, Pcal, tilt(m52_of))
    r_p, to_p = t324._run_arm(days, R, all_syms, Pcal, tilt(p_of))
    r_px, to_px = t324._run_arm(days, R, all_syms, Pcal, tilt(p_of, scored_only=True))

    st_h = t324._stats(r_hold, r_hold, to_h, "HOLD")
    st_m = t324._stats(r_m52, r_hold, to_m, "M52")
    st_p = t324._stats(r_p, r_hold, to_p, "P")
    st_px = t324._stats(r_px, r_hold, to_px, "P_excl_noscore")

    # ── 自检:未剔除的 P / M52 必须逐位复现主结果 ─────────────────────────────
    dc_p = abs(st_p["cum"] - BASE_P_CUM)
    dc_m = abs(st_m["cum"] - BASE_M52_CUM)
    ok = dc_p < 1e-9 and dc_m < 1e-9
    print("自检: P cum %.12f(基准 %.12f,Δ %.2e)· M52 cum %.12f(基准 %.12f,Δ %.2e)→ %s"
          % (st_p["cum"], BASE_P_CUM, dc_p, st_m["cum"], BASE_M52_CUM, dc_m,
             "复现" if ok else "不复现"), flush=True)
    if not ok:
        sys.exit("自检失败:未剔除的 P / M52 没能逐位复现主结果,本脚本不可信")

    # ── 剔除统计 ────────────────────────────────────────────────────────────
    n_weeks_affected = sum(1 for t in mondays
                            if len(panel_of.get(t, [])) - len(p_of.get(t, {})) > 0)
    sizes_full = [len(panel_of.get(t, [])) for t in mondays]
    sizes_cut = [len([s for s in panel_of.get(t, []) if p_of.get(t, {}).get(s) is not None])
                 for t in mondays]
    dropped = sorted({s for t in mondays
                       for s in panel_of.get(t, []) if p_of.get(t, {}).get(s) is None})

    # ── A/B:P_excl 对 M52(零分布只走 apparatus)──────────────────────────────
    ab_px = ap.ab_test(r_m52.to_numpy(), r_px.to_numpy(),
                       mean_block=t324.AB_BLOCK, n_boot=t324.AB_BOOT, seed=t324.AB_SEED)

    crit_i_base = BASE_P_CUM >= BASE_M52_CUM
    crit_i_new = st_px["cum"] >= st_m["cum"]
    out = {
        "task": "T-324",
        "purpose": "§Seth-1110a 第 2 条 —— P 臂的 686 个无分成员-周(z=0 拿 1/N)剔除后,判据 (i) 是否变",
        "window": [t324.SIGNAL_START, t324.SIGNAL_END],
        "self_check": {"p_cum_reproduced": st_p["cum"], "p_cum_published": BASE_P_CUM,
                       "m52_cum_reproduced": st_m["cum"], "m52_cum_published": BASE_M52_CUM,
                       "ok": True},
        "dropped": {
            "n_noscore_member_weeks": int(n_noscore_p),
            "n_weeks_affected": int(n_weeks_affected),
            "n_weeks_total": len(mondays),
            "panel_size_full_mean": float(np.mean(sizes_full)),
            "panel_size_after_cut_mean": float(np.mean(sizes_cut)),
            "panel_size_after_cut_min": int(np.min(sizes_cut)),
            "dropped_symbols": dropped,
        },
        "arms": {"HOLD": st_h, "M52": st_m, "P": st_p, "P_excl_noscore": st_px},
        "criterion_i": {
            "rule": "P cum ≥ M52 cum",
            "base": {"P": st_p["cum"], "M52": st_m["cum"], "diff": st_p["cum"] - st_m["cum"],
                     "pass": bool(crit_i_base)},
            "excl": {"P": st_px["cum"], "M52": st_m["cum"], "diff": st_px["cum"] - st_m["cum"],
                     "pass": bool(crit_i_new)},
            "changed": bool(crit_i_new != crit_i_base),
            "verdict": "不变(仍不过)" if (not crit_i_base and not crit_i_new) else
                       ("翻转(剔除后通过)" if crit_i_new else "翻转(剔除后更差)"),
        },
        "ab_test_Pexcl_vs_M52": ab_px,
        "ab_test_params": {"mean_block": t324.AB_BLOCK, "n_boot": t324.AB_BOOT,
                           "seed": t324.AB_SEED},
        "reading": ("剔除 = 该周只在该周有 P 分的成员里做倾斜;被剔除的成员当周权重 0(空仓),"
                    "其余成员的基准权重在有分的子集上重算(仍 1/N)。"
                    "M52 / HOLD 两臂口径不动,只有 P 臂变。"),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=float))
    print("剔除 %d 个成员-周(涉及 %d/%d 周);面板 %.1f → %.1f 个"
          % (n_noscore_p, n_weeks_affected, len(mondays),
             float(np.mean(sizes_full)), float(np.mean(sizes_cut))), flush=True)
    print("P cum %.4f → %.4f;M52 cum %.4f;判据 (i) %s"
          % (st_p["cum"], st_px["cum"], st_m["cum"], out["criterion_i"]["verdict"]), flush=True)
    print("→", OUT.name, flush=True)


if __name__ == "__main__":
    main()
