"""S-690(台账,预注册 2026-10-27 04:33 UTC):R-v2 的票 × 开票日规模中性 OI/市值分位。Seth 版;A 道 T-205 独立复算。

输入:docs/research/t197_results.json(tickets.A,已平 908 张)+ 每张票的分位 p(Supabase 上按 S-690 算,
SQL 见同目录 s690_rv2_oi_filter.sql;输出逐票存 s690_p.txt:symbol|signal_d|p|当天截面名字数|映射校验过否)。
"""
import json
import random
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(p_file: Path):
    tickets = [x for x in json.load(open(HERE / "t197_results.json"))["tickets"]["A"] if x.get("exit_d")]
    pmap = {}
    for tok in p_file.read_text().strip().split(";"):
        sym, d, p, n, kept = tok.split("|")
        pmap[(sym, d)] = (float(p) if p else None, int(n) if n else None, kept == "true")
    return tickets, pmap


def run(p_file: Path) -> dict:
    tickets, pmap = load(p_file)
    rows, drop = [], defaultdict(int)
    for t in tickets:
        p, n, kept = pmap[(t["symbol"], t["signal_d"])]
        if not kept:
            drop["映射校验不过 / 没有 OI 历史"] += 1
        elif p is None:
            drop["当天不在截面(无 OI / 市值 < 2,000 万 / 无价)"] += 1
        else:
            rows.append({"symbol": t["symbol"], "signal_d": t["signal_d"], "r": t["r"], "p": p, "H": p >= 2 / 3})
    H = [x["r"] for x in rows if x["H"]]
    L = [x["r"] for x in rows if not x["H"]]
    diff = st.mean(H) - st.mean(L)
    by_m = defaultdict(list)
    for x in rows:
        by_m[x["signal_d"][:7]].append(x)
    months = sorted(by_m)
    rng = random.Random(690)
    ge0, draws = 0, []
    for _ in range(2000):
        pick = [x for m in (rng.choice(months) for _ in months) for x in by_m[m]]
        h = [x["r"] for x in pick if x["H"]]
        lo = [x["r"] for x in pick if not x["H"]]
        if not h or not lo:
            continue
        dd = st.mean(h) - st.mean(lo)
        draws.append(dd)
        ge0 += dd >= 0
    pval = ge0 / len(draws)

    def half(pred):
        h = [x["r"] for x in rows if x["H"] and pred(x)]
        lo = [x["r"] for x in rows if not x["H"] and pred(x)]
        return {"n_H": len(h), "n_L": len(lo), "mean_H": round(st.mean(h), 4) if h else None,
                "mean_L": round(st.mean(lo), 4) if lo else None,
                "diff": round(st.mean(h) - st.mean(lo), 4) if h and lo else None}
    h1 = half(lambda x: x["signal_d"] <= "2024-06-30")
    h2 = half(lambda x: x["signal_d"] > "2024-06-30")
    fish_all = [x for x in rows if x["r"] >= 5]
    fish_H = [x for x in fish_all if x["H"]]
    share_H = len(H) / len(rows)
    share_fish_H = len(fish_H) / len(fish_all) if fish_all else None

    def grp(v):
        return {"n": len(v), "mean_r": round(st.mean(v), 4), "median_r": round(st.median(v), 4),
                "win": round(sum(1 for r in v if r > 0) / len(v), 4), "sum_r": round(sum(v), 2),
                "n_r_ge_5": sum(1 for r in v if r >= 5)}
    c1 = diff < 0 and pval < 0.05
    c2 = (h1["diff"] is not None and h1["diff"] < 0) and (h2["diff"] is not None and h2["diff"] < 0)
    c3 = share_fish_H is not None and share_fish_H <= share_H
    # 副:p 与 R 的 Spearman,按月聚类 —— 这里只报全体 Spearman(秩相关),月内样本太少不做月 t
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); rk = [0.0] * len(v); i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                rk[o[k]] = (i + j) / 2 + 1
            i = j + 1
        return rk
    rp, rr = rank([x["p"] for x in rows]), rank([x["r"] for x in rows])
    mp, mr = st.mean(rp), st.mean(rr)
    rho = sum((a - mp) * (b - mr) for a, b in zip(rp, rr)) / (
        (sum((a - mp) ** 2 for a in rp) * sum((b - mr) ** 2 for b in rr)) ** 0.5)
    return {"ledger": "S-690", "n_tickets": len(tickets), "n_used": len(rows), "dropped": dict(drop),
            "H": grp(H), "L": grp(L), "diff_mean_r": round(diff, 4), "boot_p_diff_ge0": round(pval, 4),
            "boot_draws": len(draws), "halves": {"to_2024_06": h1, "after": h2},
            "fish": {"n_r_ge_5": len(fish_all), "in_H": len(fish_H), "share_fish_in_H": round(share_fish_H, 4) if share_fish_H is not None else None,
                     "share_tickets_in_H": round(share_H, 4)},
            "spearman_p_vs_r": round(rho, 4),
            "verdict": {"c1_diff_neg_p_lt_005": c1, "c2_both_halves_neg": c2, "c3_not_cutting_fish": c3, "pass": c1 and c2 and c3},
            "tickets": rows}


if __name__ == "__main__":
    out = run(Path(sys.argv[1]))
    json.dump(out, open(HERE / "s690_results.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "tickets"}, ensure_ascii=False, indent=1))
