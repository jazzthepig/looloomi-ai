"""S-683:生产内核(src/data/signals/short_paper.py)对研究模拟器(short_lab_common + s681_h234_seth / s681_h1)逐张对票。
同一批日线(数据根 research/s681/_um_daily.jsonl)、同一个闸门(t159.load_gate 的 gate_closed),窗口 2024-01-01 → 2026-09-30。
臂 H:研究侧 = s681_h234_seth.h4_parts / h4_ticket,只留闸门关的信号再 chain;臂 L:研究侧 = s681_h1 的 short_ticket(a, 6, 0.5, 60)。
用法:python3 docs/research/s683_kernel_parity.py --root <数据根>
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
os.environ["COMETCLOUD_DATA_ROOT"] = ROOT
os.environ.setdefault("T156_DATA", os.path.join(ROOT, "research", "t156") + "/")
os.environ.setdefault("T159_DATA", os.path.join(ROOT, "research", "t159") + "/")
import numpy as np  # noqa: E402
import short_lab_common as sl  # noqa: E402
import t159_bear_short as t159  # noqa: E402
from src.data.signals import short_paper as sp  # noqa: E402

sys.argv += [] if "--h" in sys.argv else ["--h", "H4"]
import s681_h234_seth as seth  # noqa: E402

D0, D1 = "2024-01-01", "2026-09-30"


def main() -> None:
    um = sl.load_um()
    gate = {d: v["gate_closed"] for d, v in t159.load_gate().items()}
    # 生产内核:pair 名 = symbol + USDT
    bars = {s + "USDT": {"d": a["d"], "o": a["o"], "h": a["h"], "l": a["l"], "c": a["c"], "qv": a["qv"]} for s, a in um.items()}
    ph, blocked = sp.h4_tickets(bars, gate, D0, D1)
    first = {s + "USDT": a["d"][0] for s, a in um.items()}
    pl, _ = sp.listing_tickets(bars, first, D0, D1)
    # 研究侧
    fund = sl.daily_funding(sl.load_funding())
    P = seth.prep(um, fund)
    rh = []
    for s, a in um.items():
        for i in range(220, len(a["d"])):
            d = a["d"][i]
            if not (D0 <= d <= D1) or not (P[s]["adv"][i] >= 5e6):
                continue
            state, setup = seth.h4_parts(a, P, s, i)
            if state and setup and gate.get(d, False):
                t = seth.h4_ticket(um, fund, P, s, i) if i + 1 < len(a["d"]) else None
                if t:
                    rh.append(t)
    rh = sl.chain(rh)
    rl = []
    for s, a in um.items():
        if len(a["d"]) > 6 and D0 <= a["d"][6] <= D1 and s != "BTC":
            t = sl.short_ticket(a, 6, 0.5, 60, fund=fund.get(s), symbol=s)
            if t:
                rl.append(t)
    rl = sl.chain(rl)
    res = {}
    for name, prod, rsch in (("H", ph, rh), ("L", pl, rl)):
        pm = {(t["symbol"], t["signal_d"]): t for t in prod if t["status"] != "pending"}
        rm = {(t["symbol"], t["signal_d"]): t for t in rsch}
        both = set(pm) & set(rm)
        # 价格 R:研究的 ret 含资金费,去掉资金费再比
        dr = [abs(((pm[k]["gross"] - 2 * sp.COST_SIDE) / pm[k]["risk"]) - ((rm[k]["ret"] - rm[k]["funding"]) / rm[k]["risk"])) for k in both]
        dx = sum(1 for k in both if pm[k]["exit_d"] != rm[k]["exit_d"] or pm[k]["why"] != rm[k]["why"])
        res[name] = {"prod": len(pm), "research": len(rm), "both": len(both), "prod_only": sorted(map(list, set(pm) - set(rm)))[:5],
                     "research_only": sorted(map(list, set(rm) - set(pm)))[:5], "max_abs_dR_price": max(dr) if dr else None,
                     "exit_mismatch": dx}
    res["H"]["blocked_gate_open"] = blocked
    out = os.path.join(HERE, "s683_kernel_parity_results.json")
    json.dump(res, open(out, "w"), indent=1)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
