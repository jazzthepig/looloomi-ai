"""S-923:S-920 做空一侧「站得住」的两格,扛不扛得住扎堆 —— 平移零分布 + 按天等权 + 去掉一个币。研究用,不进任何账。

S-920 的打乱检验是逐张打乱:同一天常有几个币一起触发、市场层特征对它们完全相同,逐张打乱把这种扎堆拆掉 ⇒ 把握被高估。
这里**不改 S-920 的任何东西**(import 它:同一批候选单、同一套特征、同一个走步与模型、同一个种子),只换三种更难过的检验:

1. **平移零分布**:每个评估折里按进场时间排好,把预测概率整体循环平移 o 张(o 在 [n/10, 9n/10] 里均匀取),再分三档、
   算合并的上一档均值;1,000 次。平移保留了预测与收益各自的扎堆 / 自相关,只拆掉两者的对齐。分位 = 零分布里低于实测的比例。
2. **按天等权**:同一天进场的票先在天内取平均,再对天取平均 —— 上一档(天内只看上一档的票)减全部。一天十个币一起触发,只算一票。
3. **去掉一个币**:11 个币逐个拿掉(模型不重训,只从评估里拿掉),合并增量的最小值。

判(写在台账 S-923,先登记后计算):一格「扛得住」= 平移分位 ≥ 0.95,且按天等权的增量 ≥ +0.15R,且去掉任何一个币增量都 > 0。

用法(仓库根目录;环境里有只读的 SUPABASE_URL / SUPABASE_KEY):
    python3 docs/research/s923_cluster_null.py --selftest
    nohup python3 docs/research/s923_cluster_null.py > docs/research/s923_run.txt 2>&1 &      # 写 s923_results.json
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


M = _load("s920", os.path.join(HERE, "s920_meta_label.py"))

OUT = "docs/research/s923_results.json"
N_SHIFT = 1000
SEED = 923
CELLS = (("short", -1, "logit"), ("short", -1, "hgb"), ("long", 1, "logit"), ("long", 1, "hgb"))   # 做多两格只作对照


def eval_folds(cands: list, side: int, kind: str) -> list:
    """S-920 的走步原样跑一遍,取评估年的折,补上每张票的进场时间与币(按进场时间排好 —— walk 里本来就排过)。"""
    w = M.walk(cands, side, kind)
    rows = sorted([x for x in cands if x["side"] == side], key=lambda x: x["t"])
    out = []
    for f in w["folds"]:
        if f.get("skipped") or f["year"] not in M.EVAL_YEARS:
            continue
        start = M.dt.datetime(f["year"], 1, 1, tzinfo=M.dt.timezone.utc)
        last = f["year"] == M.TEST_YEARS[-1]
        end = M.dt.datetime(2100 if last else f["year"] + 1, 1, 1, tzinfo=M.dt.timezone.utc)
        test = [x for x in rows if start <= x["t"] < end]
        assert len(test) == len(f["p"]), "评估折与 S-920 的切法不一致"
        out.append({**f, "t": [x["t"] for x in test], "coin": [x["coin"] for x in test]})
    return out


def pooled_top(folds: list, ps: list | None = None) -> float:
    tops = [f["r"][M.terciles(f["p"] if ps is None else ps[i]) == 2] for i, f in enumerate(folds)]
    return float(np.concatenate(tops).mean())


def shift_null(folds: list, rng) -> dict:
    real = pooled_top(folds)
    null = []
    for _ in range(N_SHIFT):
        ps = []
        for f in folds:
            n = len(f["p"])
            o = int(rng.integers(max(1, n // 10), max(2, 9 * n // 10)))
            ps.append(np.roll(f["p"], o))
        null.append(pooled_top(folds, ps))
    null = np.array(null)
    return {"top_r": round(real, 3), "null_median": round(float(np.median(null)), 3), "null_q95": round(float(np.quantile(null, 0.95)), 3),
            "pct": round(float((null < real).mean()), 3)}


def day_weighted(folds: list) -> dict:
    alld, topd = defaultdict(list), defaultdict(list)
    for f in folds:
        tc = M.terciles(f["p"])
        for t, r, c in zip(f["t"], f["r"], tc):
            alld[t.date()].append(float(r))
            if c == 2:
                topd[t.date()].append(float(r))
    a = float(np.mean([np.mean(v) for v in alld.values()]))
    tp = float(np.mean([np.mean(v) for v in topd.values()])) if topd else float("nan")
    return {"days_all": len(alld), "days_top": len(topd), "all_r": round(a, 3), "top_r": round(tp, 3), "lift": round(tp - a, 3),
            "tickets_per_day": round(sum(len(v) for v in alld.values()) / max(len(alld), 1), 2)}


def leave_one_coin(folds: list) -> dict:
    coins = sorted({c for f in folds for c in f["coin"]})
    out = {}
    for c in coins:
        ra, rt = [], []
        for f in folds:
            tc = M.terciles(f["p"])                            # 档位按全部的票切(模型不重训),只从评估里拿掉这个币
            keep = np.array([x != c for x in f["coin"]])
            ra.append(f["r"][keep])
            rt.append(f["r"][keep & (tc == 2)])
        out[c] = round(float(np.concatenate(rt).mean() - np.concatenate(ra).mean()), 3)
    worst = min(out, key=out.get)
    return {"by_coin": out, "min_lift": out[worst], "min_coin": worst}


def run(cands: list) -> dict:
    rng = np.random.default_rng(SEED)
    res = {}
    for name, side, kind in CELLS:
        folds = eval_folds(cands, side, kind)
        r_all = np.concatenate([f["r"] for f in folds])
        top = pooled_top(folds)
        sh, dw, lo = shift_null(folds, rng), day_weighted(folds), leave_one_coin(folds)
        crit = {"shift_pct_ge_0.95": sh["pct"] >= 0.95, "day_lift_ge_0.15": dw["lift"] >= 0.15, "loco_min_gt_0": lo["min_lift"] > 0}
        res[f"{name}|{kind}"] = {"n": int(len(r_all)), "all_r": round(float(r_all.mean()), 3), "top_r": round(top, 3),
                                 "lift": round(top - float(r_all.mean()), 3), "shift": sh, "day": dw, "loco": lo,
                                 "criteria": crit, "survives": all(crit.values())}
    return {"cells": res, "n_survive_short": sum(1 for k, v in res.items() if k.startswith("short") and v["survives"])}


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        N_SHIFT = 40
    bars, fund, market, jz = M.synthetic() if selftest else M.load_live()
    cands = M.candidates(bars, fund, market, jz)
    out = run(cands)
    for k, v in out["cells"].items():
        print("CELL", k, json.dumps({q: v[q] for q in ("n", "all_r", "top_r", "lift")}), "| shift", json.dumps(v["shift"]),
              "| day", json.dumps(v["day"]), "| loco", json.dumps({"min_lift": v["loco"]["min_lift"], "min_coin": v["loco"]["min_coin"]}),
              "| crit", json.dumps(v["criteria"]), "| SURVIVES" if v["survives"] else "", flush=True)
    print("SUMMARY", json.dumps({"n_survive_short": out["n_survive_short"]}), flush=True)
    if selftest:
        # 同一批折:合并上一档的均值与 S-920 judge 的 top_r 一致(没有换掉 S-920 的切法)
        for name, side, kind in CELLS[:1]:
            w = M.walk(cands, side, kind)
            j = M.judge(w, np.random.default_rng(0))
            assert abs(out["cells"][f"{name}|{kind}"]["top_r"] - j["pooled"]["top_r"]) < 1e-3, "与 S-920 的上一档对不上"
        # 平移 0 张 = 实测;按天等权在「一天一张」时等于按张
        f0 = eval_folds(cands, -1, "logit")
        assert abs(pooled_top(f0, [f["p"] for f in f0]) - pooled_top(f0)) < 1e-12
        one = [{"p": np.array([0.1, 0.9, 0.5]), "r": np.array([-1.0, 2.0, 0.5]),
                "t": [M.dt.datetime(2024, 1, d, tzinfo=M.dt.timezone.utc) for d in (1, 2, 3)], "coin": ["A", "B", "C"]}]
        d = day_weighted(one)
        assert d["all_r"] == round(1.5 / 3, 3) and d["top_r"] == 2.0 and d["days_top"] == 1
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
        print("WROTE", OUT)
