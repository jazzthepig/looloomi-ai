"""S-682(台账 2026-10-25):新币做空的对冲版(空新币 + 等名义多 BTC),Binance 现货 2017-09 → 2020-06 的上市 —— 没看过的时代。
规则与 S-681 H1 一字相同(L+7 开盘、币腿 +50% 硬止损、60 天),只是加上 BTC 多腿、没有资金费。数据 = S-678 的合并美元日线。
用法:python3 docs/research/s682_listing_hedged_oos.py --root <数据根>
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
os.environ["COMETCLOUD_DATA_ROOT"] = ROOT
sys.path.insert(0, HERE)
import short_lab_common as sl  # noqa: E402

_spec = importlib.util.spec_from_file_location("s678", os.path.join(HERE, "s678_rv2_oos_btcpairs.py"))
s678 = importlib.util.module_from_spec(_spec)
sys.modules["s678"] = s678
_spec.loader.exec_module(s678)

S, N, ENTRY_AFTER, L_FROM = 0.50, 60, 7, "2017-09-01"


def as_arr(rows):
    a = np.array([r[1:] for r in rows], float)
    return {"d": [r[0] for r in rows], "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3], "qv": a[:, 4]}


def main() -> None:
    bars, _, _ = s678.merged_bars()
    arrs = {s: as_arr(r) for s, r in bars.items()}
    btc = arrs["BTC"]
    bi = {d: i for i, d in enumerate(btc["d"])}
    rows = []
    for s, a in arrs.items():
        if s == "BTC" or a["d"][0] < L_FROM or len(a["d"]) <= ENTRY_AFTER:
            continue
        t = sl.short_ticket(a, ENTRY_AFTER - 1, S, N, symbol=s)
        if not t or t["entry_d"] not in bi or t["exit_d"] not in bi:
            continue
        bx = btc["c"][bi[t["exit_d"]]] if t["still"] else btc["o"][bi[t["exit_d"]]]
        rb = bx / btc["o"][bi[t["entry_d"]]] - 1
        t["hedged_ret"] = t["ret"] + rb - 2 * sl.COST_SIDE
        t["hedged_r"] = t["hedged_ret"] / S
        t["listing_d"] = a["d"][0]
        rows.append(t)
    hr = [{"r": t["hedged_r"], "signal_d": t["signal_d"]} for t in rows]
    p = sl.boot_months(hr) if hr else None
    m = float(np.mean([t["hedged_r"] for t in rows])) if rows else None
    by = {}
    for t in rows:
        by.setdefault(t["signal_d"][:4], []).append(t["hedged_r"])
    res = {"n": len(rows), "hedged_mean_r": m, "hedged_median_r": float(np.median([t["hedged_r"] for t in rows])) if rows else None,
           "hedged_win": float(np.mean([t["hedged_r"] > 0 for t in rows])) if rows else None, "p_le0": p,
           "hedged_p01": float(np.quantile([t["hedged_r"] for t in rows], 0.01)) if rows else None,
           "by_year": {y: (len(v), round(float(np.mean(v)), 3)) for y, v in sorted(by.items())},
           "unhedged": sl.summary(rows),
           "judged": {"1_ok": bool(m is not None and m > 0 and p is not None and p < 0.05), "2_ok": len(rows) >= 30}}
    res["verdict"] = "过" if all(res["judged"].values()) else "不过"
    res["tickets"] = [{k: t[k] for k in ("symbol", "listing_d", "signal_d", "entry_d", "exit_d", "r", "hedged_r", "why", "still")}
                      for t in rows]
    json.dump(res, open(os.path.join(HERE, "s682_results.json"), "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in res.items() if k not in ("tickets",)}, default=str, indent=1)[:2500])


if __name__ == "__main__":
    main()
