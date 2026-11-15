"""S-879:「跌破就返空」—— Jazz 2026-11-15 在 HL 上实际做的那个动作(反弹太弱、跌破 1800 整数关口返空),做成可查的形态来量。

进场信号(D 日收盘判、D + 1 开盘进空;BTC / ETH 各自):
  BD20   收盘跌破此前 20 天的最低价(不含当天)
  ROUND  收盘跌破一个整数关口(关口 = 价格数量级的 1 / 10 的整数倍:1800、1900 … / 66000、67000 …),且前一天收盘还在它上方
  两组各再分:全部 / 只取面板「线下 · 稳定币抽」状态里的(s866_cells.json)
管法(票的走法原样用 S-874 的 ticket(),一次进满、28 天):
  RECLAIM  止损 = 被跌破的那一档之上 1%(「收回去就认错」);离进场价不足 1% 的按 1%
  R8 / R12 固定 8% / 12%
每格报 2022 年底以前 / 2023 年起 / 全样本:票数、均值、胜率、盈亏比、最坏一张;另报同一批日子里「不看信号、每 5 天一张」的对照。
预期与读法写在台账 S-879(先登记,后计算)。只描述。

用法(仓库根目录):
    python3 docs/research/s879_breakdown_short.py --selftest
    python3 docs/research/s879_breakdown_short.py            # 写 docs/research/s879_results.json
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_argv, sys.argv = sys.argv, [sys.argv[0]]
_sp = importlib.util.spec_from_file_location("s874", os.path.join(HERE, "s874_short_scale_in.py"))
G = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(G)
sys.argv = _argv
T = G.T

OUT = "docs/research/s879_results.json"
SPLIT, END, H, LOOKBACK, RECLAIM_BUF, MIN_DIST = dt.date(2022, 12, 31), dt.date(2026, 11, 13), 28, 20, 0.01, 0.01


def round_step(px: float) -> float:
    return 10 ** (math.floor(math.log10(px)) - 1)                         # 1769 → 100;68314 → 1000


def signals(days, l, c) -> dict:
    """{'BD20': [(D, 被跌破的那一档)], 'ROUND': [...]};只用 D 及以前。"""
    out = {"BD20": [], "ROUND": []}
    for i, d in enumerate(days):
        if d < T.START or i < LOOKBACK + 1:
            continue
        lo = min(l[x] for x in days[i - LOOKBACK:i])
        if c[d] < lo <= c[days[i - 1]]:
            out["BD20"].append((d, lo))
        step = round_step(c[days[i - 1]])
        lvl = math.floor(c[days[i - 1]] / step) * step
        if c[d] < lvl <= c[days[i - 1]] and lvl > 0:
            out["ROUND"].append((d, lvl))
    return out


def run(data: dict, labels: dict) -> dict:
    cells: dict = {}
    for a in T.ASSETS:
        days, o, h, l, c = data[a]
        idx = {d: i for i, d in enumerate(days)}
        sig = signals(days, l, c)
        base = [(d, None) for d in days if d >= T.START][::T.EVERY_N]
        for name, lst in list(sig.items()) + [("EVERY5", base)]:
            for scope in ("all", "drain"):
                for D, lvl in lst:
                    if scope == "drain" and not ((labels.get(D) or {}).get("T") == "线下" and (labels.get(D) or {}).get("L") == "抽"):
                        continue
                    i = idx[D] + 1
                    if i >= len(days):
                        continue
                    e0 = o[days[i]]
                    forms = {"R8": 0.08, "R12": 0.12}
                    if lvl is not None:
                        forms["RECLAIM"] = max(MIN_DIST, lvl * (1 + RECLAIM_BUF) / e0 - 1)
                    for f, dist in forms.items():
                        t = G.ticket(days, o, h, l, c, idx, D, dist, "A0", H, None)
                        if t:
                            cells.setdefault(f"{name}|{scope}|{f}", []).append((D, t))
    out = {}
    for k, ts in sorted(cells.items()):
        out[k] = {"full": G.summ([t for _, t in ts]), "disc": G.summ([t for D, t in ts if D <= SPLIT]), "hold": G.summ([t for D, t in ts if D > SPLIT])}
    return out


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        data = T.synthetic()
        labels = G.synthetic_labels(data)
    else:
        data = {a: ([d for d in v[0] if d <= END], *v[1:]) for a, v in T.load_live().items()}
        daily = json.load(open(os.path.join(HERE, "s866_cells.json"), encoding="utf-8"))["daily"]
        labels = {dt.date.fromisoformat(k): {"T": v["T"], "L": v["L"]} for k, v in daily.items()}
    out = run(data, labels)
    for k, v in out.items():
        print("CELL", k, "| full", json.dumps(v["full"], ensure_ascii=False), "| disc", json.dumps(v["disc"], ensure_ascii=False), "| hold", json.dumps(v["hold"], ensure_ascii=False), flush=True)
    if selftest:
        assert round_step(1769.2) == 100 and round_step(68314) == 1000
        days, o, h, l, c = data[T.ASSETS[0]]
        s = signals(days, l, c)
        assert s["BD20"] and s["ROUND"] and all(c[d] < lvl for d, lvl in s["BD20"] + s["ROUND"])
        cut = days[len(days) // 2]
        dz = [d for d in days if d <= cut]
        assert signals(dz, l, c)["ROUND"] == [x for x in s["ROUND"] if x[0] <= cut], "信号用到了之后的数据"
        assert out["BD20|all|RECLAIM"]["full"]["n"] > 10 and out["EVERY5|all|R8"]["full"]["worst_pct"] >= -8.0 - 6.0
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
