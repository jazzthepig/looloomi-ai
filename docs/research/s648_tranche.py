"""S-648:用 S-647 的模拟路径算分级 —— 优先级在 q 置信度下不受损所需的劣后比例,以及劣后自己的收益分布。

输入:s647_sim_r_v2.py 写的 raw jsonl(每条路径 × 每个配置一行,含 rmin_c / rend_c 覆盖比,见 coverage())。
用法:python3 docs/research/s648_tranche.py --raw s648_raw.jsonl --out s648_results.json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

COUPONS = (0.0, 0.05, 0.08)
YEARS = 3.0


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))]


def junior_needed(rows, c, mode):
    """每条路径所需劣后 J = max(0, 1 − 覆盖比);mode = 'end' 用期末,'cont' 用全程最小。"""
    key = f"rend_{c}" if mode == "end" else f"rmin_{c}"
    return [max(0.0, 1.0 - r["s"][key]) for r in rows]


def junior_outcomes(rows, J, c):
    """劣后厚度 J、优先级收益 c:覆盖比曾跌破 1 − J ⇒ 劣后归零;否则期末劣后 = (期末净值 − 优先级应得)/ J。"""
    out, wiped = [], 0
    for r in rows:
        s = r["s"]
        if J <= 0 or s[f"rmin_{c}"] < 1 - J:
            wiped += 1
            out.append(-1.0)
            continue
        senior = (1 - J) * (1 + c) ** YEARS
        end_nav = s[f"rend_{c}"] * (1 + c) ** YEARS          # 期末净值 / 本金
        jr = max(0.0, end_nav - senior) / J
        out.append(jr ** (1 / YEARS) - 1 if jr > 0 else -1.0)
    return out, wiped / len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default="s648_results.json")
    a = ap.parse_args()
    groups = defaultdict(list)
    for line in open(a.raw):
        r = json.loads(line)
        v, size, policy, lev = r["c"]
        if size == 100_000.0:
            groups[(v, policy, lev)].append(r)
    res = []
    for (v, policy, lev), rows in sorted(groups.items()):
        row = {"variant": v, "policy": policy, "lev": lev, "n": len(rows)}
        for c in COUPONS:
            for mode in ("end", "cont"):
                js = junior_needed(rows, c, mode)
                row[f"J95_{mode}_{c}"] = q(js, .95)
                row[f"J99_{mode}_{c}"] = q(js, .99)
        J = row["J99_cont_0.05"]
        jr, pw = junior_outcomes(rows, J, 0.05)
        row.update({"J_used": J, "junior_cagr_p5": q(jr, .05), "junior_cagr_p50": q(jr, .5),
                    "junior_cagr_p95": q(jr, .95), "p_junior_wiped": pw})
        res.append(row)
    json.dump(res, open(a.out, "w"), indent=1)
    for r in res:
        print(r["policy"], r["lev"], {k: round(v, 3) for k, v in r.items() if k.startswith(("J", "junior", "p_"))})


if __name__ == "__main__":
    main()
