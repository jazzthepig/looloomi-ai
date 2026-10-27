"""S-693(台账,预注册 2026-10-27 14:40 UTC):R-v2 的票 × 开票日 30 天 OI 张数变化的规模中性分位(G = p3 ≥ 2/3),
在 S-690 留下的票(非 H)里检验。输入:s693_bits.json(G 位,lag 0)+ s690_lag_bits.json 的 lag 0(H 位),顺序同
(signal_d, symbol 的 C 序);R 来自 t197_results.json tickets.A。'-' = 不在截面。"""
import json
import random
import statistics as st
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def boot_p(rows, key_a, seed=693, n=2000):
    by_m = defaultdict(list)
    for x in rows:
        by_m[x["signal_d"][:7]].append(x)
    months = sorted(by_m)
    rng = random.Random(seed)
    ge0, k = 0, 0
    for _ in range(n):
        pick = [x for m in (rng.choice(months) for _ in months) for x in by_m[m]]
        a = [x["r"] for x in pick if key_a(x)]
        b = [x["r"] for x in pick if not key_a(x)]
        if a and b:
            k += 1
            ge0 += (st.mean(a) - st.mean(b)) >= 0
    return ge0 / k


def grp(v):
    return {"n": len(v), "mean_r": round(st.mean(v), 4) if v else None, "sum_r": round(sum(v), 2),
            "n_r_ge_5": sum(1 for r in v if r >= 5)}


def test(rows, label):
    G = [x["r"] for x in rows if x["G"]]
    N = [x["r"] for x in rows if not x["G"]]
    diff = st.mean(G) - st.mean(N)
    p = boot_p(rows, lambda x: x["G"])
    halves = {}
    for name, pred in (("to_2024_06", lambda x: x["signal_d"] <= "2024-06-30"), ("after", lambda x: x["signal_d"] > "2024-06-30")):
        g = [x["r"] for x in rows if x["G"] and pred(x)]
        n = [x["r"] for x in rows if not x["G"] and pred(x)]
        halves[name] = {"n_G": len(g), "n_N": len(n), "diff": round(st.mean(g) - st.mean(n), 4) if g and n else None}
    fish = [x for x in rows if x["r"] >= 5]
    share_fish = sum(1 for x in fish if x["G"]) / len(fish) if fish else None
    share = len(G) / len(rows)
    c1 = diff < 0 and p < 0.05
    c2 = all(h["diff"] is not None and h["diff"] < 0 for h in halves.values())
    c3 = share_fish is not None and share_fish <= share
    return {"label": label, "n": len(rows), "G": grp(G), "notG": grp(N), "diff": round(diff, 4), "boot_p": round(p, 4),
            "halves": halves, "fish": {"n": len(fish), "share_in_G": round(share_fish, 4) if share_fish is not None else None,
                                       "share_tickets_G": round(share, 4)},
            "verdict": {"a": c1, "b": c2, "c": c3, "pass": c1 and c2 and c3}}


def main():
    pairs = [tuple(p) for p in json.load(open(HERE / "s690_lag_bits.json"))["pairs"]]
    hb = json.load(open(HERE / "s690_lag_bits.json"))["bits"]["0"]
    gb = json.load(open(HERE / "s693_bits.json"))["bits"]
    hmap = {pr: c for pr, c in zip(pairs, hb)}
    gmap = {pr: c for pr, c in zip(pairs, gb)}
    tickets = [x for x in json.load(open(HERE / "t197_results.json"))["tickets"]["A"] if x.get("exit_d")]
    rows = []
    for t in tickets:
        k = (t["symbol"], t["signal_d"])
        h, g = hmap[k], gmap[k]
        if h == "-" or g == "-":
            continue
        rows.append({"symbol": t["symbol"], "signal_d": t["signal_d"], "r": t["r"], "H": h == "1", "G": g == "1"})
    kept = [x for x in rows if not x["H"]]
    out = {"ledger": "S-693", "n_both_tagged": len(rows),
           "main_in_s690_kept": test(kept, "S-690 留下的票(非 H)"),
           "side_all": test(rows, "全部有两个标签的票"),
           "side_cells": {f"H{int(h)}G{int(g)}": grp([x["r"] for x in rows if x["H"] == h and x["G"] == g])
                          for h in (False, True) for g in (False, True)},
           "side_drop_top_ticket": test([x for x in kept if not (x["symbol"] == "ZEC" and x["signal_d"] == "2025-09-06")],
                                        "非 H 去掉 ZEC 2025-09-06")}
    json.dump(out, open(HERE / "s693_results.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
