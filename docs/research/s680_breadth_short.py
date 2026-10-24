"""S-680(台账 2026-10-24 14:35 UTC):山寨广度两天内塌 ≥ 30 个点、落到 ≤ 0.25 之后,等权空山寨篮子 H 天 —— 比随便哪天空好吗。

样本内 = binance_hist 面板(t159 缓存,2020 → 2026-10-19);样本外 = S-678 的合并日线(Binance 全部 USDT + BTC 计价对,含已下架,2017-08 → 2020-08)。
定义逐字照台账 S-680;零分布 = 事件序列整体循环平移(保留事件个数与间隔,只换时点)。
用法:python3 docs/research/s680_breadth_short.py [--root /Volumes/CometCloudAI/cometcloud-local]
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("s678", os.path.join(HERE, "s678_rv2_oos_btcpairs.py"))
s678 = importlib.util.module_from_spec(_spec)
sys.modules["s678"] = s678
_spec.loader.exec_module(s678)
t159 = s678.t159

EXCLUDE = {"BTC", "ETH", "USDC", "BTCDOM", "DEFI"}
COST, H_MAIN, HS = 0.002, 5, (1, 3, 5, 10)
SEED, N_SHIFT = 680, 2000


def prep(bars: dict[str, list]) -> tuple[list[str], dict]:
    """每个币:按日期的 close / open / dv 字典 + 当天是否在宇宙、是否在 50 日线上。"""
    per = {}
    days = set()
    for s, rows in bars.items():
        c = np.array([r[4] for r in rows], float)
        o = np.array([r[1] for r in rows], float)
        dv = np.array([r[5] for r in rows], float)
        d = [r[0] for r in rows]
        n = len(rows)
        cs, dvs = np.cumsum(np.r_[0, c]), np.cumsum(np.r_[0, dv])
        info = {}
        for i in range(n):
            adv30 = (dvs[i + 1] - dvs[max(0, i - 29)]) / (i + 1 - max(0, i - 29))
            sma50 = (cs[i + 1] - cs[max(0, i - 49)]) / (i + 1 - max(0, i - 49)) if i >= 49 else None
            sma200 = (cs[i + 1] - cs[max(0, i - 199)]) / 200 if i >= 199 else None
            info[d[i]] = {"c": c[i], "o": o[i], "in_u": i >= 219 and adv30 >= 5e6 and s not in EXCLUDE,
                          "above50": (sma50 is not None and c[i] > sma50), "above200": (sma200 is not None and c[i] > sma200)}
            days.add(d[i])
        per[s] = info
    return sorted(days), per


def plus(d: str, k: int) -> str:
    return (dt.date.fromisoformat(d) + dt.timedelta(days=k)).isoformat()


def build(bars: dict[str, list]) -> dict:
    days, per = prep(bars)
    breadth, members = {}, {}
    for d in days:
        u = [s for s, info in per.items() if d in info and info[d]["in_u"]]
        if len(u) >= 15:
            breadth[d] = sum(per[s][d]["above50"] for s in u) / len(u)
            members[d] = u
    pnl = {h: {} for h in HS}
    hedged = {}
    for d, u in members.items():
        e, = (plus(d, 1),)
        for h in HS:
            x = plus(d, 1 + h)
            rs = [per[s][x]["o"] / per[s][e]["o"] - 1 for s in u if e in per[s] and x in per[s] and per[s][e]["o"] > 0]
            if len(rs) >= 10:
                pnl[h][d] = -float(np.mean(rs)) - COST
                if h == H_MAIN and "BTC" in per and e in per["BTC"] and x in per["BTC"]:
                    hedged[d] = pnl[h][d] + (per["BTC"][x]["o"] / per["BTC"][e]["o"] - 1) - COST
    return {"days": days, "breadth": breadth, "members": members, "pnl": pnl, "hedged": hedged,
            "btc_above200": {d: per["BTC"][d]["above200"] for d in days if "BTC" in per and d in per["BTC"]}}


def events(b: dict[str, float], lo: str, hi: str) -> list[str]:
    ds = sorted(b)
    out, last = [], None
    for i in range(2, len(ds)):
        d = ds[i]
        if not (lo <= d <= hi):
            continue
        prev = max(b[ds[i - 1]], b[ds[i - 2]])
        if b[d] <= 0.25 and b[d] - prev <= -0.30:
            if last is None or (dt.date.fromisoformat(d) - dt.date.fromisoformat(last)).days > 10:
                out.append(d)
                last = d
    return out


def null_pct(pnl: dict[str, float], evs: list[str], lo: str, hi: str) -> dict:
    ds = sorted(d for d in pnl if lo <= d <= hi)
    idx = {d: i for i, d in enumerate(ds)}
    vals = np.array([pnl[d] for d in ds])
    on = np.zeros(len(ds), bool)
    for e in evs:
        if e in idx:
            on[idx[e]] = True
    actual = float(vals[on].mean()) if on.any() else None
    rng = np.random.default_rng(SEED)
    null = []
    for _ in range(N_SHIFT):
        k = int(rng.integers(30, len(ds) - 30))
        sh = np.roll(on, k)
        null.append(float(vals[sh].mean()))
    null = np.array(null)
    return {"n_days": len(ds), "n_events_used": int(on.sum()), "actual": actual, "null_median": float(np.median(null)),
            "null_q95": float(np.quantile(null, 0.95)),
            "pct": float((null < actual).mean() + 0.5 * (null == actual).mean()) if actual is not None else None,
            "base_mean_all_days": float(vals.mean())}


def report(name: str, data: dict, lo: str, hi: str) -> dict:
    evs = events(data["breadth"], lo, hi)
    out = {"events": [], "by_h": {}}
    for e in evs:
        ds = sorted(data["breadth"])
        i = ds.index(e)
        out["events"].append({"d": e, "b_prev2": round(max(data["breadth"][ds[i - 1]], data["breadth"][ds[i - 2]]), 3),
                              "b": round(data["breadth"][e], 3), "n_u": len(data["members"][e]),
                              "btc_above200": data["btc_above200"].get(e),
                              **{f"short_h{h}": (round(data["pnl"][h][e], 4) if e in data["pnl"][h] else None) for h in HS},
                              "hedged_h5": round(data["hedged"][e], 4) if e in data["hedged"] else None})
    for h in HS:
        out["by_h"][h] = null_pct(data["pnl"][h], [e for e in evs if e in data["pnl"][h]], lo, hi)
    hv = [x["hedged_h5"] for x in out["events"] if x["hedged_h5"] is not None]
    out["hedged_h5_mean"] = float(np.mean(hv)) if hv else None
    up = [x["short_h5"] for x in out["events"] if x["btc_above200"] and x["short_h5"] is not None]
    out["btc_above200_only_h5"] = {"n": len(up), "mean": float(np.mean(up)) if up else None}
    return out


def main() -> None:
    ins = t159.load_bars()
    res = {"in_sample": report("in", build(ins), "2020-03-01", "2026-10-12")}
    oos_bars, _, _ = s678.merged_bars()
    res["oos"] = report("oos", build(oos_bars), "2018-01-01", "2020-02-29")
    i5, o5 = res["in_sample"]["by_h"][H_MAIN], res["oos"]["by_h"][H_MAIN]
    n_in, n_oos = len(res["in_sample"]["events"]), len(res["oos"]["events"])
    j = {"1_in_mean_gt0": i5["actual"] is not None and i5["actual"] > 0,
         "2_in_pct_ge_0.95": i5["pct"] is not None and i5["pct"] >= 0.95,
         "3_oos_mean_gt0": (o5["actual"] is not None and o5["actual"] > 0) if n_oos >= 5 else "只报(事件 < 5)",
         "4_in_events_ge_8": n_in >= 8}
    res["judged"] = j
    res["verdict"] = "过" if all(v is True for v in j.values()) else "不过"
    json.dump(res, open(os.path.join(HERE, "s680_results.json"), "w"), indent=1, default=str)
    for k in ("in_sample", "oos"):
        r = res[k]
        print(k, "events", len(r["events"]), {h: {kk: (round(v, 4) if isinstance(v, float) else v) for kk, v in r["by_h"][h].items()}
                                               for h in HS})
        print("  hedged_h5", r["hedged_h5_mean"], "btc>200 only", r["btc_above200_only_h5"])
        for e in r["events"]:
            print("   ", e)
    print("judged", j, "verdict", res["verdict"])


if __name__ == "__main__":
    main()
