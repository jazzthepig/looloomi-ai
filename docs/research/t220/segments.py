#!/usr/bin/env python3
"""T-220 ④:按发现段 / 留出段切分,数 H2 三个变体的事件个数(功效上界)。"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
A = json.load(open(os.path.join(HERE, "_a_events.json")))
DISC = ("2025-12-19", "2026-03-31")
HOLD = ("2026-04-01", "2026-10-02")

print("切分:发现段", DISC, "留出段", HOLD)
for var, key, evk in (("V1 social_volume_total 30日均值z>2", "social_volume_total", "events_z30"),
                      ("V2 sentiment_weighted_total 30日均值z>2", "sentiment_weighted_total", "events_z30"),
                      ("V3 sentiment 点值z>2", "sentiment_weighted_total", "events"),
                      ("V4 social_volume 点值z>2", "social_volume_total", "events")):
    d = A["social"][key]
    n_d = n_h = 0
    per = {}
    for s, v in d.items():
        evs = v.get(evk) or []
        a = [e for e in evs if DISC[0] <= e <= DISC[1]]
        b = [e for e in evs if HOLD[0] <= e <= HOLD[1]]
        n_d += len(a)
        n_h += len(b)
        if a or b:
            per[s] = [len(a), len(b)]
    print(f"{var:38s} 发现段 {n_d:4d} | 留出段 {n_h:4d} | 逐币(发现,留出): {json.dumps(per, ensure_ascii=False)}")

t = A["trend"]
n_d = n_h = 0
per = {}
for s, v in t.items():
    evs = v.get("events") or []
    a = [e for e in evs if DISC[0] <= e <= DISC[1]]
    b = [e for e in evs if HOLD[0] <= e <= HOLD[1]]
    n_d += len(a)
    n_h += len(b)
    if a or b:
        per[s] = [len(a), len(b)]
print(f"{'V5 trending_log attention 点值z>2':38s} 发现段 {n_d:4d} | 留出段 {n_h:4d} | {json.dumps(per, ensure_ascii=False)}")
