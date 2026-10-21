"""S-654:Trader Tom 的「对了才加」用在 R-v2 单票上(半仓进场,+1R / +2R 各加半个单位、各自带止损,不收部分利润)。

以 B(原规则一张票的风险单位)为单位,和原规则在同一批 770 张票上配对比较。票与日线 = C 道 T-159 缓存(S-647 同一份)。
用法:python3 docs/research/s654_tom_pyramid_rv2.py [--root /Volumes/CometCloudAI/cometcloud-local]
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
spec = importlib.util.spec_from_file_location("s647", os.path.join(HERE, "s647_sim_r_v2.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

COST_SIDE = 0.002
UNIT = 0.5                 # 每个单位的风险 = 0.5 B
ADD_AT = (1.0, 2.0)        # 收盘 ≥ 进场 + k × R ⇒ 次日开盘加
STOP_ATR = 2.5


def atr14(bs: dict, day: dt.date):
    ds, d = [], day
    while len(ds) < 15 and d >= day - dt.timedelta(days=60):
        if d in bs:
            ds.append(d)
        d -= dt.timedelta(days=1)
    ds = sorted(ds)
    if len(ds) < 15:
        return None
    trs = [max(bs[ds[i]][1] - bs[ds[i]][2], abs(bs[ds[i]][1] - bs[ds[i - 1]][3]), abs(bs[ds[i]][2] - bs[ds[i - 1]][3]))
           for i in range(1, len(ds))]
    return sum(trs[-14:]) / 14.0


def unit_r(entry, stop, exit_px):
    risk = entry - stop
    return (exit_px - entry) / risk - 2 * COST_SIDE * entry / risk


def ticket_tom(t: dict, bs: dict, end: dt.date):
    """返回 (以 B 为单位的盈亏, 加了几档, 用掉的风险 B, 原规则出场日)。"""
    e, entry, stop = dt.date.fromisoformat(t["entry_d"]), t["entry_px"], t["stop_px"]
    R = entry - stop
    x = dt.date.fromisoformat(t["exit_d"]) if t.get("exit_d") else None
    base_exit_px = t["exit_px"] if x else None
    last = x if x else end
    pnl = UNIT * (t["r"] if t["r"] is not None else 0.0)
    if x is None:                                               # 仍在持有:按最后收盘盯市
        lc = bs[max(d for d in bs if d <= end)][3]
        pnl = UNIT * unit_r(entry, stop, lc)
        base_exit_px = lc
    adds, used = 0, UNIT
    d = e
    for k in ADD_AT:
        # 找第一个收盘 ≥ 进场 + k × R 的日子(必须早于原规则的出场判定日)
        trig = None
        while d < last:
            b = bs.get(d)
            if b and b[3] >= entry + k * R:
                trig = d
                break
            d += dt.timedelta(days=1)
        if trig is None:
            break
        ad = trig + dt.timedelta(days=1)
        while ad not in bs and ad <= last:
            ad += dt.timedelta(days=1)
        if ad > last or (x and ad >= x):
            break
        a = bs[ad][0]
        at = atr14(bs, trig)
        if not at:
            break
        s = a - STOP_ATR * at
        # 这个单位:自己的止损先到 ⇒ 按 min(开盘, 止损);否则跟着整张票在原出场价出
        px, dd = None, ad
        while dd <= last:
            b = bs.get(dd)
            if b and (x is None or dd < x or (x and dd == x and t["exit_px"] <= t["stop_px"] * (1 + 1e-9))):
                if b[2] <= s:
                    px = min(b[0], s)
                    break
            dd += dt.timedelta(days=1)
        if px is None:
            px = base_exit_px
        pnl += UNIT * unit_r(a, s, px)
        adds += 1
        used += UNIT
        d = trig + dt.timedelta(days=1)
    return pnl, adds, used


def mdd_by_exit(rows, key):
    rows = sorted(rows, key=lambda r: r["exit"])
    cum = peak = mdd = 0.0
    for r in rows:
        cum += r[key]
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return mdd


def main():
    root = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
    bars, fund, tix = m.load(root)
    rows = []
    for t in tix:
        bs = bars.get(t["symbol"], {})
        base = t["r"] if t["r"] is not None else 0.0
        if t["r"] is None:
            lc = bs[max(d for d in bs if d <= m.HIST_END)][3]
            base = unit_r(t["entry_px"], t["stop_px"], lc)
        tom, adds, used = ticket_tom(t, bs, m.HIST_END)
        rows.append({"tid": f"{t['symbol']}:{t['signal_d']}", "signal_d": t["signal_d"],
                     "exit": t.get("exit_d") or m.HIST_END.isoformat(), "base": base, "tom": tom, "adds": adds,
                     "used": used})
    out = {"n": len(rows), "base_total": sum(r["base"] for r in rows), "tom_total": sum(r["tom"] for r in rows),
           "base_mdd": mdd_by_exit(rows, "base"), "tom_mdd": mdd_by_exit(rows, "tom"),
           "adds_ge1": sum(r["adds"] >= 1 for r in rows), "adds_2": sum(r["adds"] >= 2 for r in rows),
           "mean_used_B": sum(r["used"] for r in rows) / len(rows),
           "losers_base": sum(r["base"] for r in rows if r["base"] < 0),
           "losers_tom": sum(r["tom"] for r in rows if r["base"] < 0)}
    for lab, lo, hi in (("lt2023", "0000", "2023-01-01"), ("ge2023", "2023-01-01", "9999")):
        sel = [r for r in rows if lo <= r["signal_d"] < hi]
        out[f"half_{lab}"] = {"n": len(sel), "base": sum(r["base"] for r in sel), "tom": sum(r["tom"] for r in sel)}
    top = sorted(rows, key=lambda r: -r["base"])[:10]
    out["top10"] = [(r["tid"], round(r["base"], 2), round(r["tom"], 2), r["adds"]) for r in top]
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
