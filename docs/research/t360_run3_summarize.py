#!/usr/bin/env python3
"""T-360 第三轮(规则 A,H ∈ {20,30,45},N_NULL=50)结果摘要器。

只挑需要的字段打印,避免把整个 results json 灌进上下文。
用法:python3 docs/research/t360_run3_summarize.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "T-360_results_run3.json")
VER = os.path.join(HERE, "T-360_verify_run3.json")

res = json.load(open(RES))
ver = json.load(open(VER)) if os.path.exists(VER) else {}

print("RECON", json.dumps(res["recon"], ensure_ascii=False))
print("ACCOUNT", json.dumps(res.get("account", {}), ensure_ascii=False))
for v in res["variants"]:
    w1, w2 = v.get("window1", {}), v.get("window2", {})
    sc = v.get("selfcheck") or {}
    vv = ver.get(v["variant"], {})
    row = {
        "variant": v["variant"], "H": v["H"], "events": v.get("events"),
        "w1": w1.get("w"), "w2": w2.get("w"),
        "selfchain_cum_pct": sc.get("chain_cum", 0) and round((sc["chain_cum"] - 1) * 100, 2),
        "selfcheck_diff_abs": sc.get("diff_abs"), "selfcheck_pass": sc.get("pass"),
        "cagr_old_w1": w1.get("acct_cagr_old_pct"), "cagr_new_w1": w1.get("acct_cagr_new_pct"),
        "cagr_old_w2": w2.get("acct_cagr_old_pct"), "cagr_new_w2": w2.get("acct_cagr_new_pct"),
        "contrib_pp_w1": w1.get("acct_contrib_pp"), "contrib_pp_w2": w2.get("acct_contrib_pp"),
        "p_acct_w1": w1.get("p_upper_acct_contrib"), "p_acct_w2": w2.get("p_upper_acct_contrib"),
        "p_self_w1": w1.get("p_upper_self_literal"), "p_self_w2": w2.get("p_upper_self_literal"),
        "null_n": w1.get("null_n"),
        "corr_acct_full": w1.get("corr_acct_full"), "corr_acct_stress": w1.get("corr_acct_stress"),
        "corr_rv2_full": w1.get("corr_rv2_full"), "corr_rv2_stress": w1.get("corr_rv2_stress"),
        "i_pass_w1": w1.get("i_pass"), "i_pass_w2": w2.get("i_pass"),
        "ii_pass_w1": w1.get("ii_pass"), "ii_pass_w2": w2.get("ii_pass"),
        "iii_pass_w1": w1.get("iii_pass"), "iii_pass_w2": w2.get("iii_pass"),
        "iii_worst20_ok_w1": w1.get("iii_worst20_ok"), "iii_worst20_ok_w2": w2.get("iii_worst20_ok"),
        "worst20d_window": w2.get("worst20d_window"),
        "cand_in_worst20d_pct": w2.get("cand_in_worst20d_window_pct"),
        "rv2_in_worst20d_pct": w2.get("rv2_in_worst20d_window_pct"),
        "worst20_old_pct": w2.get("worst20_old_pct"), "worst20_new_pct": w2.get("worst20_new_pct"),
        "sign_w1": w1.get("sign_self"), "sign_w2": w2.get("sign_self"),
        "iv_same_sign": v.get("iv_same_sign"), "all_pass": v.get("all_pass"),
        "self_total_ret_pct": v.get("self_total_ret_pct"),
        "total_ret_pct": v.get("total_ret_pct"), "ann_pct": v.get("ann_pct"),
        "verify_self_cum_fullcal_pct": vv.get("self_cum_fullcal_pct"),
        "verify_acct_cagr_base_pct": vv.get("acct_cagr_base_pct"),
        "verify_acct_cagr_with_pct": vv.get("acct_cagr_with_pct"),
        "verify_worst5": vv.get("worst5"),
        "verify_min_day_ret_pct": vv.get("min_day_ret_pct"),
        "verify_max_day_ret_pct": vv.get("max_day_ret_pct"),
        "verify_days_below_-50pct": vv.get("days_below_-50pct"),
    }
    print("ROW", json.dumps(row, ensure_ascii=False))
print("DONE")
