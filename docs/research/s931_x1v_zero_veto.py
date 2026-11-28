"""S-931:升级加密腿 —— 生产 X1V 不动,加「⓪ 否决」与 T-370 v1 空头票。研究用,不进任何账、不动钱。口径与算式见台账 S-931(先登记后计算)。

- BASE = 生产 `TOM_ARMS['CORE_X1V']`:`tom.trade_path(① NAV, 'rally', 0, 'l20', vol=True)`,收益 `tom.trade_returns`(直接调生产函数,不重写)。
- V1 = BASE + ⓪ 否决:⓪(S-928 的 D1,BTC 周线坏 × 稳定币抽)在防守的日子,X1V 的任何多头(含反弹单、回补)清零。
- V2 = V1 + T-370 v1 空头票(S-929 A 组原样:`house_rules.T370`,档位 2 = 每币 10% 名义,⓪ 结束当天收盘全平)。

用法(仓库根目录):
    python3 docs/research/s931_x1v_zero_veto.py --selftest
    python3 docs/research/s931_x1v_zero_veto.py --from-json s931_data.json     # S-929 的导出 + "core": [[YYMMDD, ① NAV]]
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from src.data.evaluation.house_rules import T370  # noqa: E402
from src.data.evaluation.setup_watch import trigger_1  # noqa: E402  (T-445:形态 #1 的触发直接调生产函数,不再重写)
from src.data.signals.tom import trade_path, trade_returns  # noqa: E402


def _load(name):
    sp = importlib.util.spec_from_file_location(name, os.path.join(HERE, f"{name}.py"))
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


B = _load("s928_bear_playbook")          # ⓪ D1、水下、崩塌 / 上涨分段
P = _load("s929_t370_short")             # T-370 v1 的触发与资金费

#: 研究前三问(docs/RULEBOOK.md;CI 查)
HOUSE_RULES = {
    "layer": "③ 加密腿(生产 X1V)+ ⓪ 否决 + 空头票",
    "ruler": "账户口径:回本时间、每段崩塌的损失、每段上涨拿到几成;票:占名义 % 的均值与盈亏比(DECISIONS 11-11 / 11-15)",
    "uses": ["T370", "EXPOSURE"],
    "varies": {"⓪ 否决": "S-931:新加的一层 —— ⓪ 确认转向后,X1V 的多头(含反弹单、回补)清零,直到 ⓪ 退出",
               "⓪ 签名": "S-931:回测里没有 Jazz 的签名,用 S-928 的 D1 防守代理(同 S-929)"},
}

OUT = "docs/research/s931_results.json"
START, SPLIT = dt.date(2020, 2, 1), dt.date(2023, 1, 1)
NOTIONAL = T370["tiers"][1] / 2
COST = 0.001
N_SHIFT, SEED = 500, 931


def x1v(core: pd.Series) -> pd.Series:
    return trade_path(core, "rally", 0.0, "l20", True)


def veto(g: pd.Series, defend: dict) -> pd.Series:
    """g[d] 作用于 d+1;d+1 在 ⓪ 防守 ⇒ 清零。"""
    out = g.copy()
    idx = list(g.index)
    for i, ts in enumerate(idx[:-1]):
        nxt = idx[i + 1].date()
        if defend.get(nxt):
            out.iloc[i] = 0.0
    return out


def _bars(px: dict, sym: str, days: list, i: int) -> list[dict]:
    """生产 `trigger_1` 要的日线格式 [{d, high, low, close}](只给到 D 为止的 21 根,够它取此前 20 根)。"""
    return [{"d": days[k].isoformat(), "high": px[sym][days[k]][1], "low": px[sym][days[k]][2], "close": px[sym][days[k]][3]}
            for k in range(max(0, i - 20), i + 1)]


def account(days: list, base_ret: dict, px: dict, fund: dict, d200: dict, stable: dict, defend: dict, weekly: dict,
            tickets_on: bool) -> dict:
    """账户 = 加密腿日收益(base_ret[d])+ ⓪ 期间的 T-370 v1 票。"""
    eq, nav, open_t, done = 1.0, [1.0], {}, []
    for i in range(1, len(days)):
        d = days[i]
        pnl = eq * base_ret.get(d, 0.0)
        for sym in list(open_t):
            t = open_t[sym]
            o, h, l, c = px[sym][d]
            ex = why = None
            if o >= t["stop"]:
                ex, why = o, "stop"
            elif h >= t["stop"]:
                ex, why = t["stop"], "stop"
            elif (d - t["entry_d"]).days >= T370["horizon_d"]:
                ex, why = c, "time"
            mark = ex if ex is not None else c
            fd = fund[sym].get(d, 0.0)
            pnl += t["n"] * (t["mark"] - mark) / t["entry"] + t["n"] * fd
            t["fund"] += fd
            t["mark"] = mark
            if ex is not None:
                pnl -= COST * t["n"]
                t.update(exit_d=d, exit=ex, why=why)
                done.append(t)
                del open_t[sym]
        eq += pnl
        if d in weekly and not weekly[d]["defend"] and open_t:
            for sym in list(open_t):
                t = open_t.pop(sym)
                eq -= COST * t["n"]
                t.update(exit_d=d, exit=t["mark"], why="reason_gone")
                done.append(t)
        if tickets_on and i + 1 < len(days) and defend.get(days[i + 1]):
            for sym in P.ASSETS:
                if sym in open_t or d not in px[sym]:
                    continue
                bars = _bars(px, sym, days, i)
                hit = trigger_1(bars, d, B.asof(d200, d, 3), B.asof(stable, d, 3), P.funding7(fund[sym], d))
                if not hit:
                    continue
                n = NOTIONAL * eq
                eq -= COST * n
                open_t[sym] = {"sym": sym, "entry_d": d, "entry": hit["entry"], "stop": hit["stop"], "stop0": hit["stop"],
                               "n": n, "mark": hit["entry"], "fund": 0.0}
        nav.append(eq)
    for t in open_t.values():
        t.update(exit_d=None, exit=t["mark"], why="open")
    for t in done + list(open_t.values()):
        t["pct"] = (t["entry"] - t["exit"]) / t["entry"] + t["fund"] - (2 if t["why"] != "open" else 1) * COST
    return {"nav": np.array(nav), "tickets": done, "open": list(open_t.values())}


def seg_stats(days, nav):
    m = np.array([d < SPLIT for d in days])
    return {"all": B.underwater(days, nav), "disc": B.underwater(days, nav, m), "hold": B.underwater(days, nav, ~m)}


def episodes_table(days, core_d, navs: dict, first_ready) -> tuple:
    crashes, rallies = B.episodes(days, core_d)
    pos = {d: i for i, d in enumerate(days)}
    ct, rt = [], []
    for p, t in crashes:
        row = {"peak": str(p), "trough": str(t), "core": round(core_d[t] / core_d[p] - 1, 4), "evaluable": p >= first_ready}
        for k, nv in navs.items():
            row[k] = round(float(nv[pos[t]] / nv[pos[p]] - 1), 4)
        ct.append(row)
    for t, p in rallies:
        row = {"trough": str(t), "peak": str(p), "core": round(core_d[p] / core_d[t] - 1, 3)}
        base = np.log(core_d[p] / core_d[t])
        for k, nv in navs.items():
            row[k] = round(float(np.log(nv[pos[p]] / nv[pos[t]]) / base), 3)
        rt.append(row)
    return ct, rt


def tstats(ts):
    return P.split([{**t, "R": 0.0} for t in ts]) if ts else {"all": {"n": 0}, "disc": {"n": 0}, "hold": {"n": 0}}


_CACHE: dict = {}


def build(data: dict, wk_override: dict | None = None):
    px, fund, stable, taker, y2, d200 = data["px"], data["fund"], data["stable"], data["taker"], data["y2"], data["d200"]
    key = id(data)
    if key not in _CACHE:                                   # 生产 X1V 只算一次(平移零分布里只有 ⓪ 在变)
        core = pd.Series({pd.Timestamp(d): v for d, v in data["core"].items()}).sort_index()
        g0 = x1v(core)
        _CACHE[key] = (core, g0, trade_returns(core, g0))
    core, g0, r0 = _CACHE[key]
    bdays = sorted(d for d in px["BTC"] if d in px["ETH"])
    bclose = {d: px["BTC"][d][3] for d in bdays}
    wk = wk_override if wk_override is not None else {s: x for s, x in B.weekly_states(bdays, bclose, stable, taker, y2, "D1").items()}
    defend_all = B.daily_defend(bdays, wk)
    g1 = veto(g0, defend_all)
    r1 = trade_returns(core, g1)
    days = [d for d in (ts.date() for ts in core.index) if d >= START and d in px["BTC"] and d in px["ETH"]]
    base_ret = {ts.date(): float(v) for ts, v in r0.items()}
    v1_ret = {ts.date(): float(v) for ts, v in r1.items()}
    dd = {d: defend_all.get(d, False) for d in days}
    wkw = {s: x for s, x in wk.items() if s in set(days)}
    res = {"BASE": account(days, base_ret, px, fund, d200, stable, dd, wkw, False),
           "V1": account(days, v1_ret, px, fund, d200, stable, dd, wkw, False),
           "V2": account(days, v1_ret, px, fund, d200, stable, dd, wkw, True)}
    core_d = {d: float(core[pd.Timestamp(d)]) for d in days}
    hold = np.array([core_d[d] / core_d[days[0]] for d in days])
    first_ready = min((s for s, v in wk.items() if v.get("ready")), default=days[0])
    return days, core_d, hold, res, wk, dd, first_ready, g0, g1


def judge(st: dict, ct: list, rt: list, tk: dict, pct: float) -> dict:
    c1 = st["V2"]["hold"]["longest_underwater_d"] < st["BASE"]["hold"]["longest_underwater_d"] and \
        st["V2"]["disc"]["longest_underwater_d"] <= st["BASE"]["disc"]["longest_underwater_d"]
    ev = [c for c in ct if c["evaluable"]]
    cuts = [1 - c["V2"] / c["BASE"] for c in ev if c["BASE"] < 0]
    c2 = all(c["V2"] >= c["BASE"] for c in ev) and (np.mean(cuts) > 0 if cuts else False)
    c3 = all(r["V2"] >= r["BASE"] - 0.10 for r in rt)
    c4 = pct >= 0.90
    c5 = all(tk[s].get("n") and tk[s]["mean_pct"] > 0 and (tk[s]["payoff"] or 0) >= 2 for s in ("disc", "hold"))
    return {"c1_underwater": bool(c1), "c2_crash_not_worse": bool(c2), "mean_cut_vs_base": round(float(np.mean(cuts)), 3) if cuts else None,
            "c3_rally_cost": bool(c3), "c4_shift_pct": round(pct, 3), "c4": bool(c4), "c5_tickets": bool(c5),
            "pass": bool(c1 and c2 and c3 and c4 and c5)}


def run(data: dict, n_shift: int = N_SHIFT) -> dict:
    days, core_d, hold, res, wk, dd, first_ready, g0, g1 = build(data)
    navs = {"HOLD": hold, **{k: v["nav"] for k, v in res.items()}}
    st = {k: seg_stats(days, nv) for k, nv in navs.items()}
    ct, rt = episodes_table(days, core_d, navs, first_ready)
    tk = tstats(res["V2"]["tickets"])
    suns = sorted(s for s, v in wk.items() if v.get("ready"))
    flags = [wk[s]["defend"] for s in suns]
    rng = np.random.default_rng(SEED)
    null = []
    for _ in range(n_shift):
        o = int(rng.integers(8, len(suns) - 8))
        w2 = {s: {"defend": bool(f), "ready": True} for s, f in zip(suns, np.roll(flags, o))}
        _, _, _, r2, _, _, _, _, _ = build(data, w2)
        null.append(B.underwater(days, r2["V2"]["nav"])["longest_underwater_d"])
    pct = float((np.array(null) > st["V2"]["all"]["longest_underwater_d"]).mean())
    veto_days = int(sum(1 for d in days if dd[d]))
    vetoed_long = int(sum(1 for ts, a, b in zip(g0.index, g0.values, g1.values) if ts.date() >= START and a > 0 and b == 0))
    return {"window": [str(days[0]), str(days[-1])], "stats": st, "crash": ct, "rally": rt, "tickets": tk,
            "open_tickets": [{k: (str(v) if isinstance(v, dt.date) else v) for k, v in t.items() if k in ("sym", "entry_d", "entry", "stop0", "pct")}
                             for t in res["V2"]["open"]],
            "defend_days": veto_days, "x1v_long_days_vetoed": vetoed_long, "shift_null_luw": {"median": float(np.median(null)), "q10": float(np.quantile(null, 0.10))},
            "judge": judge(st, ct, rt, tk, pct)}


def load(path: str) -> dict:
    d = P.load(path)
    j = json.load(open(path))
    d["core"] = {B.D(a): float(v) for a, v in j["core"]}
    return d


def synthetic() -> dict:
    d = P.synthetic()
    days = sorted(d["px"]["BTC"])
    d["core"] = {x: d["px"]["BTC"][x][3] / d["px"]["BTC"][days[0]][3] for x in days}
    return d


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    data = synthetic() if selftest else load(sys.argv[sys.argv.index("--from-json") + 1])
    out = run(data, n_shift=5 if selftest else N_SHIFT)
    print("WINDOW", json.dumps(out["window"]), "| defend days", out["defend_days"], "| X1V long days vetoed", out["x1v_long_days_vetoed"], flush=True)
    for k, v in out["stats"].items():
        print("STATS", k, json.dumps(v), flush=True)
    print("CRASH", json.dumps(out["crash"]), flush=True)
    print("RALLY", json.dumps(out["rally"]), flush=True)
    print("TICKETS", json.dumps(out["tickets"]), "| open", json.dumps(out["open_tickets"]), flush=True)
    print("JUDGE", json.dumps(out["judge"]), "| shift null", json.dumps(out["shift_null_luw"]), flush=True)
    if selftest:
        days, core_d, hold, res, wk, dd, fr, g0, g1 = build(data)
        # 否决只会把仓位压到 0,不会加仓;防守以外的日子与生产 X1V 完全相同
        assert ((g1 <= g0 + 1e-12) | (g1 == 0)).all()
        same = [(a == b) for ts, a, b in zip(g0.index[:-1], g0.values[:-1], g1.values[:-1])
                if not dd.get(g0.index[list(g0.index).index(ts) + 1].date(), False)]
        assert all(same), "防守以外的日子,V1 必须等于生产 X1V"
        assert np.allclose(res["BASE"]["nav"], res["V1"]["nav"]) or any(dd.values())
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
        print("WROTE", OUT)
