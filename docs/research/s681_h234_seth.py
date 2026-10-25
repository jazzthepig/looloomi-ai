"""S-681 H2 / H3 / H4 —— Seth 的那一份(三道 T-194 / T-195 / T-196 各自另做一份,逐张对照)。定义逐字照台账 S-681。
发现段先算完、落盘,再打开留出段。用法:python3 docs/research/s681_h234_seth.py --root <数据根> --h H2|H3|H4
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
H = sys.argv[sys.argv.index("--h") + 1] if "--h" in sys.argv else "H3"
os.environ["COMETCLOUD_DATA_ROOT"] = ROOT
import short_lab_common as sl  # noqa: E402


def sma(x: np.ndarray, n: int) -> np.ndarray:
    return sl.rolling_mean(x, n)


def prep(um: dict, fund: dict) -> dict:
    """每币:adv30、上市天数、3 日收益、3 日资金费年化、SMA20 / SMA200 —— 只用当天及以前。"""
    out = {}
    for s, a in um.items():
        n = len(a["d"])
        c = a["c"]
        r3 = np.full(n, np.nan)
        r3[3:] = c[3:] / c[:-3] - 1
        fd = fund.get(s, {})
        fday = np.array([fd.get(d, np.nan) for d in a["d"]])
        f3 = np.full(n, np.nan)
        for i in range(2, n):
            w = fday[i - 2:i + 1]
            if np.isfinite(w).all():
                f3[i] = w.mean() * 365
        out[s] = {"adv": sl.adv30(a), "r3": r3, "f3": f3, "sma20": sma(c, 20), "sma200": sma(c, 200)}
    return out


def top20_by_day(um: dict, P: dict) -> dict[str, set]:
    by: dict[str, list] = {}
    for s, a in um.items():
        for i, d in enumerate(a["d"]):
            v = P[s]["adv"][i]
            if np.isfinite(v):
                by.setdefault(d, []).append((v, s))
    return {d: {s for _, s in sorted(v, reverse=True)[:20]} for d, v in by.items()}


def run_h2(um, fund, P):
    top = top20_by_day(um, P)
    tk, pools = [], {}
    for s, a in um.items():
        last = -10 ** 9
        for i in range(60, len(a["d"]) - 1):
            d = a["d"][i]
            ok = P[s]["adv"][i] >= 5e6 and s not in top.get(d, set())
            if not ok:
                continue
            if np.isfinite(P[s]["r3"][i]) and P[s]["r3"][i] >= 0.40:
                if i - last > 14:
                    t = sl.short_ticket(a, i, 0.30, 14, fund=fund.get(s), symbol=s)
                    if t:
                        tk.append(t)
                    last = i
            elif np.isfinite(P[s]["r3"][i]):
                pools.setdefault(d, []).append((s, i))
    make = lambda s, i: sl.short_ticket(um[s], i, 0.30, 14, fund=fund.get(s), symbol=s)  # noqa: E731
    return sl.chain(tk), pools, make


def run_h3(um, fund, P):
    tk, pools = [], {}
    for s, a in um.items():
        last = -10 ** 9
        for i in range(60, len(a["d"]) - 1):
            d = a["d"][i]
            f3 = P[s]["f3"][i]
            if not (P[s]["adv"][i] >= 5e6 and np.isfinite(f3)):
                continue
            if f3 >= 0.50:
                if i - last > 10:
                    t = sl.short_ticket(a, i, 0.30, 10, fund=fund.get(s), symbol=s)
                    if t:
                        tk.append(t)
                    last = i
            elif f3 < 0.20:
                pools.setdefault(d, []).append((s, i))
    make = lambda s, i: sl.short_ticket(um[s], i, 0.30, 10, fund=fund.get(s), symbol=s)  # noqa: E731
    return sl.chain(tk), pools, make


def h4_parts(a, P, s, i):
    """熊市反弹失败:状态 + 设置;返回止损价(过去 10 天最高价,封顶进场 × 1.30)或 None。"""
    c, l = a["c"], a["l"]
    s200, s20 = P[s]["sma200"], P[s]["sma20"]
    if i < 220 or not (np.isfinite(s200[i]) and np.isfinite(s200[i - 20]) and np.isfinite(s20[i])):
        return None, False
    state = c[i] < s200[i] and s200[i] < s200[i - 20]
    return state, (c[i - 9:i + 1].max() >= c[i - 19:i + 1].min() * 1.15 and c[i] < l[i - 1] and c[i] < s20[i])


def h4_ticket(um, fund, P, s, i):
    a = um[s]
    if i + 1 >= len(a["d"]):
        return None
    entry = float(a["o"][i + 1])
    stop = min(float(a["h"][i - 9:i + 1].max()), entry * 1.30)
    s20 = P[s]["sma20"]
    rule = lambda a_, j: bool(np.isfinite(s20[j]) and a_["c"][j] > s20[j])  # noqa: E731
    return sl.short_ticket(a, i, 0.0, 30, fund=fund.get(s), exit_rule=rule, stop_px=stop, symbol=s)


def run_h4(um, fund, P):
    tk, pools = [], {}
    for s, a in um.items():
        for i in range(220, len(a["d"]) - 1):
            if not (P[s]["adv"][i] >= 5e6):
                continue
            state, setup = h4_parts(a, P, s, i)
            if not state:
                continue
            if sl.DISCOVERY[0] <= a["d"][i] <= sl.DISCOVERY[1]:
                pools.setdefault(f"{s}", []).append((s, i))     # 同币、同状态、发现段内的随机日
            if setup:
                t = h4_ticket(um, fund, P, s, i)
                if t:
                    tk.append(t)
    tk = sl.chain(tk)
    # 对照按「同币」抽:把每张票的键临时换成币名(null_same_day 按 signal_d 取 pools)
    keyed = [{**t, "signal_d_orig": t["signal_d"], "signal_d": t["symbol"]} for t in tk]
    make = lambda s, i: h4_ticket(um, fund, P, s, i)  # noqa: E731
    return tk, pools, make, keyed


def main() -> None:
    um = sl.load_um()
    fund = sl.daily_funding(sl.load_funding())
    P = prep(um, fund)
    keyed = None
    if H == "H2":
        tk, pools, make = run_h2(um, fund, P)
    elif H == "H3":
        tk, pools, make = run_h3(um, fund, P)
    else:
        tk, pools, make, keyed = run_h4(um, fund, P)
    disc = sl.in_window(tk, *sl.DISCOVERY)
    hold = [t for t in tk if t["signal_d"] >= sl.HOLDOUT_FROM]
    if keyed is not None:
        kd = [k for k in keyed if sl.DISCOVERY[0] <= k["signal_d_orig"] <= sl.DISCOVERY[1]]
        null = sl.null_same_day(kd, pools, make)
    else:
        null = sl.null_same_day(disc, pools, make)
    res = {"h": H, "discovery": sl.summary(disc), "null_median": float(np.median(null)) if len(null) else None,
           "null_q95": float(np.quantile(null, 0.95)) if len(null) else None}
    out = os.path.join(HERE, f"s681_{H.lower()}_seth_results.json")
    json.dump(res, open(out, "w"), indent=1, default=str)          # 发现段先落盘
    res["judged"] = sl.judge(disc, null, hold)
    res["holdout"] = sl.summary(hold)
    nb = sl.nav_bars(um)
    res["money_discovery"] = sl.money(disc, nb, "2024-02-29")
    last = max(a["d"][-1] for a in um.values())
    res["money_holdout"] = sl.money(hold, nb, last)
    res["tickets"] = [{k: t[k] for k in ("symbol", "signal_d", "entry_d", "exit_d", "entry_px", "stop_px", "exit_px", "r",
                                         "ret", "funding", "why", "gap", "still")} for t in tk]
    json.dump(res, open(out, "w"), indent=1, default=str)
    print(H, "DISC", json.dumps({k: v for k, v in res["discovery"].items() if k != "by_year"}), res["discovery"].get("by_year"))
    print(H, "HOLD", json.dumps({k: v for k, v in res["holdout"].items() if k != "by_year"}), res["holdout"].get("by_year"))
    print(H, "JUDGED", json.dumps(res["judged"]))
    print(H, "MONEY", json.dumps({"disc": {k: res["money_discovery"][k] for k in ("annualised", "mdd", "taken", "skipped")} if res["money_discovery"] else None,
                                   "hold": {k: res["money_holdout"][k] for k in ("annualised", "mdd", "taken", "skipped")} if res["money_holdout"] else None}))


if __name__ == "__main__":
    main()
