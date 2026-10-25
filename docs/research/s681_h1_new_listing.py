"""S-681 H1(台账 2026-10-25 13:21 UTC):新币做空 —— Binance 永续上市第 7 天开盘空,+50% 硬止损,持有 60 天。

对照 = 同一天、随机空一个已上市 ≥ 365 天、30 日成交额 ≥ $5M 的合约,同样规则(1,000 次,种子 681)。
发现段 = 信号日 2020-01-01 → 2023-12-31;**先算完发现段并写进结果,再打开留出段(2024-01-01 起)**。
只报:HL 原生新币(research/s657/_hl_daily.jsonl 里 Binance 没有的,无资金费)。
用法:python3 docs/research/s681_h1_new_listing.py [--root <数据根>]
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
os.environ["COMETCLOUD_DATA_ROOT"] = ROOT
import short_lab_common as sl  # noqa: E402

S, N, ENTRY_AFTER = 0.50, 60, 7
FIRST_MONTH_END = "2019-10-01"


def tickets_for(um: dict, fund: dict) -> list[dict]:
    out = []
    for sym, a in um.items():
        if a["d"][0] < FIRST_MONTH_END or len(a["d"]) <= ENTRY_AFTER:
            continue
        t = sl.short_ticket(a, ENTRY_AFTER - 1, S, N, fund=fund.get(sym), symbol=sym)
        if t:
            t["listing_d"] = a["d"][0]
            out.append(t)
    return sl.chain(out)


def pools_for(um: dict) -> dict[str, list[tuple[str, int]]]:
    pools: dict[str, list[tuple[str, int]]] = {}
    for sym, a in um.items():
        adv = sl.adv30(a)
        for i in range(365, len(a["d"]) - 1):
            if adv[i] >= 5e6:
                pools.setdefault(a["d"][i], []).append((sym, i))
    return pools


def phase(name: str, tk: list[dict], um: dict, fund: dict, pools: dict) -> dict:
    make = lambda s, i: sl.short_ticket(um[s], i, S, N, fund=fund.get(s), symbol=s)  # noqa: E731
    null = sl.null_same_day(tk, pools, make)
    return {"summary": sl.summary(tk), "null_median": float(np.median(null)) if len(null) else None,
            "null_q95": float(np.quantile(null, 0.95)) if len(null) else None,
            "null_pct": float((null < np.mean([t["r"] for t in tk])).mean()) if len(null) and tk else None,
            "p_le0": sl.boot_months(tk) if tk else None, "_null": null}


def main() -> None:
    um = sl.load_um()
    fund = sl.daily_funding(sl.load_funding())
    allt = tickets_for(um, fund)
    pools = pools_for(um)
    disc = sl.in_window(allt, *sl.DISCOVERY)
    res = {"rule": {"s": S, "n_hold": N, "entry_day_after_listing": ENTRY_AFTER}, "n_listings_total": len(allt)}
    d = phase("discovery", disc, um, fund, pools)
    res["discovery"] = {k: v for k, v in d.items() if k != "_null"}
    out = os.path.join(HERE, "s681_h1_results.json")
    json.dump(res, open(out, "w"), indent=1, default=str)          # 发现段先落盘
    print("DISCOVERY", json.dumps(res["discovery"], default=str)[:1500])
    hold = [t for t in allt if t["signal_d"] >= sl.HOLDOUT_FROM]
    h = phase("holdout", hold, um, fund, pools)
    res["holdout"] = {k: v for k, v in h.items() if k != "_null"}
    res["judged"] = sl.judge(disc, d["_null"], hold)
    last = max(a["d"][-1] for a in um.values())
    nb = sl.nav_bars(um)
    res["money_discovery"] = sl.money(disc, nb, "2024-03-31")
    res["money_holdout"] = sl.money(hold, nb, last)
    # 只报:HL 原生新币
    hl_path = os.path.join(ROOT, "research", "s657", "_hl_daily.jsonl")
    if os.path.exists(hl_path):
        hl = {}
        for line in open(hl_path):
            x = json.loads(line)
            name = x["coin"]
            base = name[1:] if name.startswith("k") and name[1:2].isupper() else name
            if base in um or ("1000" + base) in um or name in um:
                continue
            bars = sorted({(b["d"], b["o"], b["h"], b["l"], b["c"], b["c"] * b["v"]) for b in x["bars"] if b["c"] > 0})
            if len(bars) > ENTRY_AFTER:
                arr = np.array([r[1:] for r in bars], float)
                hl[name] = {"d": [r[0] for r in bars], "o": arr[:, 0], "h": arr[:, 1], "l": arr[:, 2], "c": arr[:, 3], "qv": arr[:, 4]}
        hk = [t for t in (sl.short_ticket(a, ENTRY_AFTER - 1, S, N, symbol=s) for s, a in hl.items()) if t]
        res["hl_native"] = sl.summary(hk)
    res["tickets"] = [{k: t[k] for k in ("symbol", "listing_d", "signal_d", "entry_d", "exit_d", "entry_px", "stop_px",
                                         "exit_px", "r", "ret", "funding", "why", "gap", "still")} for t in allt]
    json.dump(res, open(out, "w"), indent=1, default=str)
    print("HOLDOUT", json.dumps(res["holdout"], default=str)[:1200])
    print("JUDGED", json.dumps(res["judged"], default=str))
    print("MONEY", json.dumps({"disc": res["money_discovery"], "hold": res["money_holdout"]}, default=str)[:800])
    print("HL_NATIVE", json.dumps(res.get("hl_native"), default=str)[:600])


if __name__ == "__main__":
    main()
