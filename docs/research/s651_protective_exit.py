"""S-651:R-v2 票证明到 +3R 之后加一条吊灯线(进场以来最高收盘 − 3 × ATR14),收盘跌破 ⇒ 次日开盘出,与原出场先到先出。

数据与模拟 = S-647(docs/research/s647_sim_r_v2.py 的装载 + src/exec_host/sim_tickets.py 引擎);票 = C 道 T-159 缓存的 770 张。
用法:python3 docs/research/s651_protective_exit.py [--root /Volumes/CometCloudAI/cometcloud-local]
"""
from __future__ import annotations

import dataclasses
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
from src.exec_host import sim_tickets as st  # noqa: E402

PROVE_R, CHANDELIER_ATR = 3.0, 3.0
COST = 0.004


def atr14(bars_sym: dict, day: dt.date) -> float | None:
    """14 日真实波幅均值,含当天(与 r_v2_tickets.sql 同口径:前收缺 ⇒ 用当天收盘)。"""
    trs, d, prev_needed = [], day, 14
    ds = []
    while len(ds) < prev_needed + 1 and d >= day - dt.timedelta(days=60):
        if d in bars_sym:
            ds.append(d)
        d -= dt.timedelta(days=1)
    ds = sorted(ds)
    if len(ds) < 15:
        return None
    for i in range(1, len(ds)):
        o, h, l, c = bars_sym[ds[i]]
        pc = bars_sym[ds[i - 1]][3]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-14:]) / 14.0


def protective_exit(t: dict, bars_sym: dict, end: dt.date) -> tuple[dt.date, float] | None:
    """返回 (新的出场日, 出场价);吊灯线没有比原出场更早触发 ⇒ None。"""
    e, entry, stop = dt.date.fromisoformat(t["entry_d"]), t["entry_px"], t["stop_px"]
    risk = entry - stop
    x = dt.date.fromisoformat(t["exit_d"]) if t.get("exit_d") else None
    last_check = (x - dt.timedelta(days=1)) if x else end        # 判定日 k 的开盘出场在 k + 1 ≤ 原出场日
    hh, proven, d = None, False, e
    while d <= last_check:
        b = bars_sym.get(d)
        if b is not None:
            c = b[3]
            hh = c if hh is None else max(hh, c)
            proven = proven or c >= entry + PROVE_R * risk
            if proven:
                a = atr14(bars_sym, d)
                if a and c < hh - CHANDELIER_ATR * a:
                    nd = d + dt.timedelta(days=1)
                    while nd not in bars_sym and nd <= end:
                        nd += dt.timedelta(days=1)
                    if nd > end:
                        return None
                    if x and nd > x:
                        return None
                    return nd, bars_sym[nd][0]
        d += dt.timedelta(days=1)
    return None


def paper_r(entry, stop, exit_px):
    risk = entry - stop
    return (exit_px - entry) / risk - COST * entry / risk


def main():
    root = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
    bars, fund, tix = m.load(root)
    tk, meta = m.build_tickets(bars, fund, tix)
    by_tid = {t.tid: t for t in tk}
    new_tk, rows = [], []
    for t in tix:
        tid = f"{t['symbol']}:{t['signal_d']}"
        base_r = t["r"] if t["r"] is not None else 0.0
        pe = protective_exit(t, bars.get(t["symbol"], {}), m.HIST_END)
        s = by_tid.get(tid)
        risk = t["entry_px"] - t["stop_px"]
        peak_r = None
        e = dt.date.fromisoformat(t["entry_d"])
        x = dt.date.fromisoformat(t["exit_d"]) if t.get("exit_d") else m.HIST_END
        cl = [bars[t["symbol"]][d][3] for d in (e + dt.timedelta(days=i) for i in range((x - e).days + 1))
              if d in bars.get(t["symbol"], {})]
        if cl:
            peak_r = (max(cl) - t["entry_px"]) / risk
        if pe:
            nd, px = pe
            new_r = paper_r(t["entry_px"], t["stop_px"], px)
            off = (nd - e).days
            if s:
                new_tk.append(dataclasses.replace(s, exit_off=off, paper_exit_off=off))
        else:
            new_r = base_r
            if s:
                new_tk.append(s)
        rows.append({"tid": tid, "signal_d": t["signal_d"], "base_r": base_r, "new_r": new_r, "triggered": bool(pe),
                     "peak_r": peak_r, "hl": m.hl_listed(t["symbol"])})
    s0, s1 = (m.HIST_START - st.EPOCH).days, (m.HIST_END - st.EPOCH).days
    out = {"meta": meta, "n_triggered": sum(r["triggered"] for r in rows)}
    for lev in (3.0, 1.0):
        res = {}
        for name, tks in (("base", tk), ("P", new_tk)):
            r = st.simulate(tks, 1e5, lev, executable=lambda t: m.hl_listed(t.symbol), apy_for_day=m._apy_hist,
                            start_day=s0, end_day=s1, collateral_mult=float("inf"))
            i0, i1 = (dt.date(2024, 12, 8) - m.HIST_START).days, (dt.date(2025, 9, 25) - m.HIST_START).days
            seg, pk, wdd = r.equity[i0:i1 + 1], r.equity[i0], 0.0
            for v in seg:
                pk = max(pk, v)
                wdd = min(wdd, v / pk - 1)
            res[name] = {**st.stats(r.equity, 1e5), "window_dd": wdd}
        out[f"L{lev:g}"] = res
    for lab, lo, hi in (("lt2023", "0000", "2023-01-01"), ("ge2023", "2023-01-01", "9999")):
        sel = [r for r in rows if lo <= r["signal_d"] < hi]
        out[f"half_{lab}"] = {"n": len(sel), "base_R": sum(r["base_r"] for r in sel), "P_R": sum(r["new_r"] for r in sel)}
    proven = [r for r in rows if r["peak_r"] is not None and r["peak_r"] >= PROVE_R]
    out["proven"] = {"n": len(proven), "mean_peak_R": sum(r["peak_r"] for r in proven) / max(1, len(proven)),
                     "mean_base_R": sum(r["base_r"] for r in proven) / max(1, len(proven)),
                     "mean_P_R": sum(r["new_r"] for r in proven) / max(1, len(proven))}
    top = sorted(rows, key=lambda r: -r["base_r"])[:10]
    out["top10"] = [{"tid": r["tid"], "base_r": round(r["base_r"], 2), "P_r": round(r["new_r"], 2)} for r in top]
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
