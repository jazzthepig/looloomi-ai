"""S-872:R-v2 在稳定币抽的时候减半 —— 按「两把尺各管一层」判(台账 S-872,先登记后计算)。

装配与引擎原样调用 `s867_frontier.py`(不改它)。三条臂(真钱现配置 每票 0.75% / 上限 80% / 名额 10):
  FULL  现状;GATED 信号日稳定币在抽(s866_cells.json 的 L 轴)的票不开;HALF 两本子账各一半(一半 FULL、一半 GATED),逐日收益取平均。
判:(a) 账户年化不比 FULL 低超过 1.0 个点;(b) 最长水下不比 FULL 多超过 30 天。两条都过才是真钱候选。

用法(仓库根目录):python3 docs/research/s872_rv2_half_in_drain.py [<cometcloud-local/research/>]
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
R = sys.argv[1] if len(sys.argv) > 1 else "/Volumes/CometCloudAI/cometcloud-local/research/"
sys.argv = [os.path.join(HERE, "s867_frontier.py"), os.path.join(HERE, "t342_daily.csv"), R]
_sp = importlib.util.spec_from_file_location("s867", os.path.join(HERE, "s867_frontier.py"))
F = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(F)

OUT = "docs/research/s872_results.json"
CFG = (0.0075, 0.80, 10)
MAX_CAGR_GIVE_UP, MAX_EXTRA_UW_D = 0.010, 30

daily = json.load(open(os.path.join(HERE, "s866_cells.json"), encoding="utf-8"))["daily"]
drain = lambda t: (daily.get(str(t["signal_d"])[:10]) or {}).get("L") == "抽"          # noqa: E731
unlabelled = sum(1 for t in F.TK if str(t["signal_d"])[:10] not in daily)


def arm(rv2):
    m = F.metrics(F.build_account(rv2))                      # 与 S-867 同一个 metrics(),复现那一行才对得上
    return {"cagr": round(m["cagr"], 4), "longest_underwater_d": int(m["underwater_days"]), "mdd": round(m["max_dd"], 4),
            "worst_20d": round(m["worst_20d"], 4), "rv2_risk_share": round(m["rv2_risk_share"], 3)}


res_full, rv2_full = F.run_engine(F.TK, *CFG)
kept = [t for t in F.TK if not drain(t)]
res_g, rv2_g = F.run_engine(kept, *CFG)
idx = rv2_full.index.union(rv2_g.index)
rv2_half = 0.5 * rv2_full.reindex(idx).fillna(0.0) + 0.5 * rv2_g.reindex(idx).fillna(0.0)
out = {"config": CFG, "tickets": {"all": len(F.TK), "signal_in_drain": sum(1 for t in F.TK if drain(t)), "signal_day_without_label": unlabelled,
                                  "taken_full": len(res_full["taken"]), "taken_gated": len(res_g["taken"])},
       "FULL": arm(rv2_full), "GATED": arm(rv2_g), "HALF": arm(rv2_half)}
out["reproduces_s867"] = {"cagr_expected": 0.3572, "uw_expected": 750,
                          "ok": abs(out["FULL"]["cagr"] - 0.3572) <= 0.001 and out["FULL"]["longest_underwater_d"] == 750}
for k in ("GATED", "HALF"):
    a = out[k]["cagr"] >= out["FULL"]["cagr"] - MAX_CAGR_GIVE_UP
    b = out[k]["longest_underwater_d"] <= out["FULL"]["longest_underwater_d"] + MAX_EXTRA_UW_D
    out[k]["judge"] = {"a_cagr_within_1pt": bool(a), "b_underwater_within_30d": bool(b), "real_money_candidate": bool(a and b)}
for k in ("reproduces_s867", "tickets", "FULL", "GATED", "HALF"):
    print(k, json.dumps(out[k], ensure_ascii=False), flush=True)
if not out["reproduces_s867"]["ok"]:
    print("STOP: FULL 没有复现 S-867 的 35.72% / 750 天 —— 不往下报")
    sys.exit(2)
json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
print("WROTE", OUT)
