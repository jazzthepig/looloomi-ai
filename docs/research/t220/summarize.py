#!/usr/bin/env python3
"""T-220:把 ②③ 的结果压成报告要用的紧凑表。"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
A = json.load(open(os.path.join(HERE, "_a_events.json")))
B = json.load(open(os.path.join(HERE, "_b_onset.json")))
C = json.load(open(os.path.join(HERE, "_c_mindshare.json")))
CIS = ["AAVE", "ADA", "APT", "ARB", "AVAX", "BNB", "BTC", "DOT", "ETH", "HYPE", "INJ", "LDO",
       "LINK", "NEAR", "ONDO", "OP", "PENDLE", "POL", "SKY", "SOL", "STRK", "SUI", "TIA", "UNI", "XRP"]

for m in ("sentiment_weighted_total", "social_volume_total"):
    d = A["social"][m]
    cov = [s for s in CIS if d[s].get("n_days")]
    print(f"\n== {m}:覆盖 {len(cov)}/25,缺失={[s for s in CIS if s not in cov]}")
    print("   事件合计 z>2:", sum(d[s].get("n_events_z_gt2", 0) for s in CIS),
          "| 30日均值 z>2:", sum(d[s].get("n_events_z30_gt2", 0) for s in CIS))
    per = {s: d[s].get("n_events_z_gt2", 0) for s in cov}
    print("   逐币:", json.dumps(per, ensure_ascii=False))
    per30 = {s: d[s].get("n_events_z30_gt2", 0) for s in cov}
    print("   逐币(30日均值):", json.dumps(per30, ensure_ascii=False))
    starts = sorted({d[s]["start"] for s in cov})
    ends = sorted({d[s]["end"] for s in cov})
    print("   起点集合:", starts[:3], "…", "终点集合:", ends[:3], "…")

t = A["trend"]
print("\n== trending_log:覆盖", sum(1 for s in CIS if t[s].get("n_days")), "/25",
      "| 事件合计:", sum(t[s].get("n_events_z_gt2", 0) for s in CIS))
print("   逐币:", json.dumps({s: t[s].get("n_events_z_gt2", 0) for s in CIS}, ensure_ascii=False))
print("   起止:", sorted({(t[s].get("start"), t[s].get("end")) for s in CIS if t[s].get("n_days")})[:6])

print("\n== mindshare_snap: 覆盖", len(C["mind_per_symbol"]), "/25 | 事件合计", C["mind_events_total"])
print("   起止:", sorted({(v["start"], v["end"]) for v in C["mind_per_symbol"].values()}))
print("== narrative_mindshare: 叙事数", C["n_narratives"], "| 事件合计", C["narrative_events_total"],
      "| 起止", min(v["start"] for v in C["narratives"]), max(v["end"] for v in C["narratives"]))

print("\n== ③ S-661 开闸事件逐个标记 ==")
print(f"{'onset':12s} {'gecko':28s} {'sym':6s} {'rel1m':>7s} | {'senti n/max/peak':>22s} | "
      f"{'volume n/max/peak':>22s} | trend")
for r in B:
    sw = r.get("sentiment_weighted_total_symbol")
    sv = r.get("social_volume_total_symbol")
    def cell(p):
        if r.get(p + "_symbol") is None:
            return f"{'无数据':>22s}"
        return (f"{r.get(p+'_pre30_n',0):>4d}/{str(r.get(p+'_pre30_z_max')):>7s}/"
                f"{'峰值' if r.get(p+'_peak_pre30') else '无峰':>4s}")
    ts = r.get("trend_symbol")
    tc = (f"{r.get('trend_pre30_n')}d/{r.get('trend_pre30_z_max')}/"
          f"{'峰值' if r.get('trend_peak_pre30') else '无峰'}") if ts else "无数据"
    print(f"{r['onset']:12s} {r['g']:28s} {(sw or sv or '-'):6s} "
          f"{str(r.get('rel_1m')):>7s} | {cell('sentiment_weighted_total')} | "
          f"{cell('social_volume_total')} | {tc}")
n_cover = sum(1 for r in B if r.get("sentiment_weighted_total_pre30_covered")
              or r.get("social_volume_total_pre30_covered"))
n_peak = sum(1 for r in B if r.get("sentiment_weighted_total_peak_pre30")
             or r.get("social_volume_total_peak_pre30"))
print(f"\n可判定(前 30 天 ≥20 天热度数据)={n_cover}/{len(B)};其中有热度峰值(z>2)={n_peak}")
