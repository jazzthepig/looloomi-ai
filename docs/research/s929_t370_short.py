"""S-929:空头腿改回已经定稿的 T-370 v1 重跑 —— 研究用,不进任何账、不动钱。口径见台账 S-929(先登记后计算)。

T-370 v1(11-15 定稿,卡 `tasks/T-370.json`)+ 11-13 的 ⓪ short 状态 + S-886 的人群条件:
- 触发 = 生产 `setup_watch.trigger_1` 原样:D 日面板 `dist_200` < 0 且 `stable_supply_30d` < 0;收盘 < 此前 20 根日线的最低价(不含 D);
  7 日资金费 > 0。进场 = D 收盘;认错线 = 20 日低 × 1.01,且 ≤ 进场 × 1.08。
- 管法:碰认错线就平(跳空按开盘);否则第 28 天收盘平;**不设目标、不移保本、不加仓**;⓪ 结束 ⇒ 当天收盘全平。每币同时一张。
- ⓪ short 状态要 Jazz 签名;回测里用 S-928 的 D1 防守代理(周线坏 × 稳定币抽)—— 是代理,不是他的判断。
- 尺寸 = 档位 2:每币名义 = 账户 10%(合计 20%)。资金费按天收付;进出各 10 bp。多头书照 S-928(D1 防守时空仓)。

三组:A = ⓪ 代理 + T-370 v1;B = 只看 T-370 的状态(不经 ⓪);C = A 的同一批进场换成 S-928 的「3R 目标 + 1R 保本」。

用法(仓库根目录):
    python3 docs/research/s929_t370_short.py --selftest
    python3 docs/research/s929_t370_short.py --from-json s929_data.json      # S-928 的导出 + "dist200": [[YYMMDD, 面板离 200 日线]]
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_sp = importlib.util.spec_from_file_location("s928", os.path.join(HERE, "s928_bear_playbook.py"))
B = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(B)

OUT = "docs/research/s929_results.json"
LOOKBACK, STOP_ABOVE, STOP_CAP, HORIZON = 20, 1.01, 1.08, 28       # = setup_watch 的常量
NOTIONAL = 0.10                                                    # 档位 2:每币 10%,合计 20%
COST = B.COST
ASSETS = B.ASSETS
SPLIT = B.SPLIT


def trigger(px: dict, days: list, i: int, t200, stab, f7) -> dict | None:
    """= setup_watch.trigger_1:状态、资金费、收盘 < 此前 20 根日线最低价。"""
    if t200 is None or stab is None or f7 is None or not (t200 < 0 and stab < 0 and f7 > 0) or i < LOOKBACK:
        return None
    lo20 = min(px[days[k]][2] for k in range(i - LOOKBACK, i))
    entry = px[days[i]][3]
    if not entry < lo20:
        return None
    return {"entry": entry, "lo20": lo20, "stop": min(lo20 * STOP_ABOVE, entry * STOP_CAP)}


def funding7(fund: dict, d: dt.date):
    v = [fund.get(d - dt.timedelta(days=k)) for k in range(7)]
    if fund.get(d) is None:
        return None
    v = [x for x in v if x is not None]
    return float(np.mean(v)) if v else None


def simulate(days: list, px: dict, fund: dict, d200: dict, stable: dict, defend: dict | None, weekly: dict | None,
             mode: str, long_book: bool = True) -> dict:
    """mode:'t370'(拿到 28 天)或 's928'(3R 目标 + 1R 保本)。defend = None ⇒ 不经 ⓪(B 组),多头书也不动(只统计票)。"""
    btc = px["BTC"]
    eq, nav, w_prev = 1.0, [1.0], None
    open_t, done = {}, []
    w_prev = 0.0 if (defend and defend[days[0]]) or not long_book else 1.0
    for i in range(1, len(days)):
        d, p = days[i], days[i - 1]
        w = (0.0 if (defend and defend[d]) else 1.0) if long_book else 0.0
        pnl = eq * w * (btc[d][3] / btc[p][3] - 1) if w else 0.0
        if w != w_prev:
            pnl -= COST * abs(w - w_prev) * eq
        for sym in list(open_t):
            t = open_t[sym]
            o, h, l, c = px[sym][d]
            ex = why = None
            if o >= t["stop"]:
                ex, why = o, ("breakeven" if t["be"] else "stop")
            elif h >= t["stop"]:
                ex, why = t["stop"], ("breakeven" if t["be"] else "stop")
            elif mode == "s928" and l <= t["target"]:
                ex, why = (o if o <= t["target"] else t["target"]), "target"
            elif (d - t["entry_d"]).days >= HORIZON:
                ex, why = c, "time"
            mark = ex if ex is not None else c
            fd = fund[sym].get(d, 0.0)
            pnl += t["n"] * (t["mark"] - mark) / t["entry"] + t["n"] * fd
            t["fund"] += fd
            t["mark"] = mark
            if mode == "s928" and ex is None and not t["be"] and l <= t["entry"] - t["r"]:
                t["stop"], t["be"] = t["entry"], True
            if ex is not None:
                pnl -= COST * t["n"]
                t.update(exit_d=d, exit=ex, why=why)
                done.append(t)
                del open_t[sym]
        eq += pnl
        if weekly is not None and d in weekly and not weekly[d]["defend"] and open_t:      # ⓪ 结束 ⇒ 全平
            for sym in list(open_t):
                t = open_t.pop(sym)
                eq -= COST * t["n"]
                t.update(exit_d=d, exit=t["mark"], why="reason_gone")
                done.append(t)
        # 新票:D 收盘触发、D 收盘进;持有期从 D+1 起,所以要求 D+1 在 ⓪ 状态里(B 组不要求)
        if i + 1 < len(days):
            for sym in ASSETS:
                if sym in open_t:
                    continue
                if defend is not None and not defend[days[i + 1]]:
                    continue
                hit = trigger(px[sym], days, i, B.asof(d200, d, 3), B.asof(stable, d, 3), funding7(fund[sym], d))
                if not hit:
                    continue
                n = NOTIONAL * eq
                eq -= COST * n
                r = hit["stop"] - hit["entry"]
                open_t[sym] = {"sym": sym, "signal_d": d, "entry_d": d, "entry": hit["entry"], "lo20": hit["lo20"], "stop": hit["stop"],
                               "stop0": hit["stop"], "r": r, "target": hit["entry"] - 3 * r, "n": n, "mark": hit["entry"], "be": False, "fund": 0.0}
        nav.append(eq)
        w_prev = w
    still = []
    for t in open_t.values():                     # 窗口结束时还没到期的票:按最后收盘记浮动,单列,不进已了结的统计
        t.update(exit_d=None, exit=t["mark"], why="open")
        still.append(t)
    for t in done + still:
        t["pct"] = (t["entry"] - t["exit"]) / t["entry"] + t["fund"] - (2 if t["why"] != "open" else 1) * COST   # 占名义 %(S-865 的单位)
        t["R"] = t["pct"] / (t["stop0"] / t["entry"] - 1)
        t["risk_usd"] = t["n"] * (t["stop0"] / t["entry"] - 1)
    return {"nav": np.array(nav), "tickets": done, "open": still}


def tstats(ts: list) -> dict:
    if not ts:
        return {"n": 0}
    x = np.array([t["pct"] for t in ts])
    w, lo = x[x > 0], x[x <= 0]
    return {"n": len(x), "mean_pct": round(float(x.mean()), 4), "median_pct": round(float(np.median(x)), 4), "win": round(float((x > 0).mean()), 3),
            "payoff": round(float(w.mean() / -lo.mean()), 2) if len(w) and len(lo) and lo.mean() < 0 else None,
            "worst_pct": round(float(x.min()), 4), "best_pct": round(float(x.max()), 4),
            "mean_R": round(float(np.mean([t["R"] for t in ts])), 3),
            "exits": {k: int(sum(1 for t in ts if t["why"] == k)) for k in ("stop", "time", "target", "breakeven", "reason_gone")}}


def split(ts: list) -> dict:
    return {"all": tstats(ts), "disc": tstats([t for t in ts if t["entry_d"] < SPLIT]), "hold": tstats([t for t in ts if t["entry_d"] >= SPLIT])}


def run(data: dict, n_shift: int | None = None) -> dict:
    px, fund, stable, taker, y2, d200 = data["px"], data["fund"], data["stable"], data["taker"], data["y2"], data["d200"]
    days = sorted(d for d in px["BTC"] if d in px["ETH"])
    close = {d: px["BTC"][d][3] for d in days}
    days_w = [d for d in days if d >= B.START]
    crashes, rallies = B.episodes(days_w, close)
    wk = B.weekly_states(days, close, stable, taker, y2, "D1")
    wk = {s: x for s, x in wk.items() if s >= B.START - dt.timedelta(days=7)}
    dd = B.daily_defend(days_w, wk)
    out = {"window": [str(days_w[0]), str(days_w[-1])], "groups": {}}
    resA = simulate(days_w, px, fund, d200, stable, dd, wk, "t370")
    resC = simulate(days_w, px, fund, d200, stable, dd, wk, "s928")
    resB = simulate(days_w, px, fund, d200, stable, None, None, "t370", long_book=False)
    for name, res in (("A_zero_proxy_T370", resA), ("C_same_entries_S928_mgmt", resC), ("B_state_only_T370", resB)):
        out["groups"][name] = {"tickets": split(res["tickets"]),
                               "list": [{k: (str(t[k]) if isinstance(t[k], dt.date) else (round(t[k], 4) if isinstance(t[k], float) else t[k]))
                                         for k in ("sym", "entry_d", "entry", "stop0", "exit_d", "exit", "why", "pct", "R")} for t in res["tickets"] + res["open"]]}
    hold = B.simulate(days_w, px, fund, {d: False for d in days_w}, None, False)
    hold_rep = B.report(days_w, close, hold, {d: False for d in days_w}, crashes, rallies, None)
    for name, res in (("A_zero_proxy_T370", resA), ("C_same_entries_S928_mgmt", resC)):
        rep = B.report(days_w, close, res, dd, crashes, rallies, wk)
        out["groups"][name]["account"] = {k: rep[k] for k in ("all", "disc", "hold", "crash", "rally")}
        if name.startswith("A"):
            rng = np.random.default_rng(929)
            suns = sorted(s for s, v in wk.items() if v.get("ready"))
            flags = [wk[s]["defend"] for s in suns]
            null = []
            for _ in range(n_shift or 500):
                o = int(rng.integers(8, len(suns) - 8))
                w2 = {s: {"defend": bool(f), "ready": True} for s, f in zip(suns, np.roll(flags, o))}
                r2 = simulate(days_w, px, fund, d200, stable, B.daily_defend(days_w, w2), w2, "t370")
                null.append(B.underwater(days_w, r2["nav"])["longest_underwater_d"])
            pct = float((np.array(null) > rep["all"]["longest_underwater_d"]).mean())
            jt = out["groups"][name]["tickets"]
            ok_t = all(jt[s].get("n") and jt[s]["mean_pct"] > 0 and (jt[s]["payoff"] or 0) >= 2 for s in ("disc", "hold"))
            ja = B.judge(rep, hold_rep, pct)
            out["groups"][name]["judge"] = {"tickets_pass": bool(ok_t), "account": ja}
    out["hold"] = {k: hold_rep[k] for k in ("all", "disc", "hold")}
    return out


def load(path: str) -> dict:
    px, fund, stable, taker, y2 = B.load(path)
    j = json.load(open(path))
    return {"px": px, "fund": fund, "stable": stable, "taker": taker, "y2": y2, "d200": {B.D(a): v for a, v in j["dist200"]}}


def synthetic() -> dict:
    px, fund, stable, taker, y2 = B.synthetic()
    days = sorted(px["BTC"])
    cl = [px["BTC"][d][3] for d in days]
    d200 = {d: (cl[i] / np.mean(cl[max(0, i - 199):i + 1]) - 1) for i, d in enumerate(days)}
    return {"px": px, "fund": fund, "stable": stable, "taker": taker, "y2": y2, "d200": d200}


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    data = synthetic() if selftest else load(sys.argv[sys.argv.index("--from-json") + 1])
    out = run(data, n_shift=5 if selftest else None)
    print("WINDOW", json.dumps(out["window"]), "| HOLD", json.dumps(out["hold"]), flush=True)
    for g, v in out["groups"].items():
        print("GROUP", g, "| tickets", json.dumps(v["tickets"]), "| open", json.dumps([t for t in v["list"] if t["why"] == "open"]), flush=True)
        if "account" in v:
            a = v["account"]
            print("  ACCOUNT", g, json.dumps({k: a[k] for k in ("all", "disc", "hold")}), flush=True)
            print("  CRASH", g, json.dumps([{k: c[k] for k in ("peak", "hold", "acct", "cut")} for c in a["crash"]]), flush=True)
            print("  RALLY", g, json.dumps([{k: c[k] for k in ("trough", "captured")} for c in a["rally"]]), flush=True)
        if "judge" in v:
            print("  JUDGE", g, json.dumps(v["judge"]), flush=True)
    if selftest:
        days = sorted(data["px"]["BTC"])
        r = simulate(days, data["px"], data["fund"], data["d200"], data["stable"], None, None, "t370", long_book=False)
        assert all(t["why"] in ("stop", "time") for t in r["tickets"]), "T-370 v1 只有认错线与 28 天两种出场"
        assert all(t["stop0"] <= t["entry"] * STOP_CAP + 1e-9 and t["stop0"] > t["entry"] for t in r["tickets"])
        assert all((t["exit_d"] - t["entry_d"]).days <= HORIZON for t in r["tickets"])
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
        print("WROTE", OUT)
