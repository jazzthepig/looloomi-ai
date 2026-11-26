"""S-921:参数面 —— 突破回看长度 × 吊灯 ATR 倍数,看 S-919 的优势是一片平台还是一个尖。**不挑最优点**,只报整张面。

规则 = `s916_jazz_4h_rules.py` 的 BRF_L(带 EMA 过滤的突破回踩做多)与 BR_L(不带过滤),管法 = 吊灯止损(atr3 那一套,只换倍数)、
止损下限 1%、单张截 +20R;11 个币。网格:回看 HL ∈ {10, 20, 40, 60} 根 × ATR 倍数 K ∈ {2, 3, 4, 5} = 16 格,S-919 用的是 (20, 3)。
每格报:发现段(≤ 2022)/ 留出段(2023 起)的张数、均值 R、去掉最好 5 张后的均值、胜率;对照 = 同一 K 下随机进场(每 5 天一张)。
判(写在台账 S-921,先登记后计算):「平台」= BRF_L 16 格里 ≥ 12 格两段均值 R 都 > 0,且两段都高于同 K 的对照;
「尖」= (20, 3) 是 16 格里留出段均值最高的、而它上下左右相邻格的留出段均值都不到它的一半。

用法(仓库根目录;环境里有只读的 SUPABASE_URL / SUPABASE_KEY):
    python3 docs/research/s921_param_surface.py --selftest
    nohup python3 docs/research/s921_param_surface.py > docs/research/s921_run.txt 2>&1 &      # 写 s921_results.json
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


_argv, sys.argv = sys.argv, [sys.argv[0], "--mgmt", "atr3", "--dmin", "0.01", "--cap", "20"]
R = _load("s916", os.path.join(HERE, "s916_jazz_4h_rules.py"))
sys.argv = _argv

OUT = "docs/research/s921_results.json"
HLS, KS, RULES = (10, 20, 40, 60), (2.0, 3.0, 4.0, 5.0), ("BRF_L", "BR_L")
SPLIT = R.SPLIT


def halves(ts: list) -> tuple:
    return (R.summ([x[2] for x in ts if x[0].date() <= SPLIT]), R.summ([x[2] for x in ts if x[0].date() > SPLIT]))


def surface(bars: dict) -> dict:
    cells, base = [], {}
    for k in KS:
        R.ATR_K = k
        bl = []
        for b in bars.values():
            R.HL_N = 20
            bl += R.baseline(b, R.indicators(b), 1)
        base[k] = halves(bl)
        for hl in HLS:
            R.HL_N = hl
            for rule in RULES:
                ts = []
                for b in bars.values():
                    ts += R.tickets(b, R.indicators(b), rule)
                d, h = halves(ts)
                cells.append({"rule": rule, "hl": hl, "k": k, "disc": d, "hold": h, "base_disc": base[k][0], "base_hold": base[k][1]})
    R.HL_N, R.ATR_K = 20, 3.0
    return {"cells": cells}


def verdict(cells: list) -> dict:
    out = {}
    for rule in RULES:
        cs = [c for c in cells if c["rule"] == rule]
        ok = [c for c in cs if c["disc"].get("n") and c["hold"].get("n") and c["disc"]["mean_r"] > 0 and c["hold"]["mean_r"] > 0
              and c["disc"]["mean_r"] > c["base_disc"].get("mean_r", 0) and c["hold"]["mean_r"] > c["base_hold"].get("mean_r", 0)]
        hold_of = {(c["hl"], c["k"]): (c["hold"].get("mean_r") if c["hold"].get("n") else None) for c in cs}
        best = max(hold_of, key=lambda q: -1e9 if hold_of[q] is None else hold_of[q])
        here = hold_of.get((20, 3.0))
        i, j = HLS.index(20), KS.index(3.0)
        nb = [hold_of.get((HLS[a], KS[b])) for a, b in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)) if 0 <= a < len(HLS) and 0 <= b < len(KS)]
        spike = best == (20, 3.0) and here is not None and here > 0 and all(v is None or v < here / 2 for v in nb)
        rank = 1 + sum(1 for q, v in hold_of.items() if v is not None and here is not None and v > here)
        out[rule] = {"n_cells_ok": len(ok), "plateau": len(ok) >= 12, "spike_at_20_3": spike, "rank_of_20_3_by_hold": rank, "best_by_hold": list(best)}
    return out


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    bars, _ = R.synthetic() if selftest else R.load_live()
    ref = []
    for b in bars.values():                                   # S-919 的默认参数 (20, 3) 直接跑一遍,作网格那一格的对照
        ref += R.tickets(b, R.indicators(b), "BRF_L")
    out = surface(bars)
    out["verdict"] = verdict(out["cells"])
    f = lambda s: f"n{s.get('n')} r{s.get('mean_r')} x5{s.get('mean_ex_top5')} win{s.get('win')}" if s.get("n") else "n0"  # noqa: E731
    for c in out["cells"]:
        print("CELL", c["rule"], f"hl{c['hl']}", f"k{c['k']}", "| disc", f(c["disc"]), "vs", f(c["base_disc"]), "| hold", f(c["hold"]), "vs", f(c["base_hold"]), flush=True)
    print("VERDICT", json.dumps(out["verdict"], ensure_ascii=False), flush=True)
    if selftest:
        assert len(out["cells"]) == len(HLS) * len(KS) * len(RULES)
        assert R.HL_N == 20 and R.ATR_K == 3.0, "跑完要还原全局参数"
        # 网格里 (20, 3) 那一格 = 默认参数直接跑一遍(改全局参数的写法没有串味)
        c = [x for x in out["cells"] if x["rule"] == "BRF_L" and x["hl"] == 20 and x["k"] == 3.0][0]
        assert (c["disc"], c["hold"]) == halves(ref), "网格 (20, 3) 与默认参数不一致"
        assert any(x["disc"] != c["disc"] for x in out["cells"] if x["rule"] == "BRF_L"), "参数没有生效"
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
        print("WROTE", OUT)
