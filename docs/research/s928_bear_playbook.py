"""S-928:深熊打法按我们自己的规矩重做 —— 研究用,不进任何账、不动钱。口径全文见台账 S-928(先登记后计算)。

三层,各管各的:
1. **盯**(S-849 第 1 条,只记不动):价格在 200 日线上而 30 日主动买盘 < 0.5;稳定币 30 日供应变化 ≤ 0;2 年期高于 60 天前 —— 任一成立。
2. **⓪ 防守**(每周日收盘判,下周一起生效):周线结构坏(周日收盘 < 10 周均线 且 < 4 周前收盘)且 稳定币 30 日变化 ≤ 0
   (D2 另要 2 年期在升)⇒ 多头书 = 0(现金)。退出:周线结构不再坏 且(稳定币 30 日 > 0 或 主动买盘 ≥ 0.5)。
3. **空头只用票**(形态 #1):防守期间 BTC / ETH 收盘首次跌破此前 20 天最低收盘、且 7 日平均资金费 > 0 ⇒ 次日开盘空。
   进场前写好:硬止损 = 被破那一档 × 1.01(离进场最多 8%);目标 = 进场 − 3R,碰到就全平;碰到 −1R 之后止损移到进场价;
   28 天时间止损;防守结束那个周日收盘全平(理由消失)。同一天止损与目标都碰到按止损算。每币同时一张。
   尺寸:每张风险 0.75% 净值;单张名义 ≤ 40%、空头合计 ≤ 80%;资金费按天收付;进出各 10 bp。

对照:满仓 BTC;只防守不开票;只看价格的防守(Tom S-600);防守序列按周循环平移(零分布)。

用法(仓库根目录):
    python3 docs/research/s928_bear_playbook.py --selftest
    python3 docs/research/s928_bear_playbook.py --from-json s928_data.json
      # {"px": {sym: [[YYMMDD, o, h, l, c]]}, "fd": {sym: [[YYMMDD, 日资金费]]}, "fm": [[YYMMDD, 稳定币30日, 主动买盘30日, 2年期]]}
"""
from __future__ import annotations

import datetime as dt
import json
import sys

import numpy as np

OUT = "docs/research/s928_results.json"
START = dt.date(2020, 2, 1)
SPLIT = dt.date(2023, 1, 1)
COST = 0.001
RISK = 0.0075
CAP_ONE, CAP_ALL = 0.40, 0.80
STOP_MAX, RECLAIM, TARGET_R, TIME_D = 0.08, 1.01, 3.0, 28
CRASH, RALLY = 0.30, 0.80
N_SHIFT, SEED = 500, 928
ASSETS = ("BTC", "ETH")


def D(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%y%m%d").date()


def asof(series: dict, d: dt.date, max_age: int):
    for k in range(max_age + 1):
        v = series.get(d - dt.timedelta(days=k))
        if v is not None:
            return v
    return None


# ── ⓪ 周度状态 ──────────────────────────────────────────────────────────────

def weekly_states(days: list, close: dict, stable: dict, taker: dict, y2: dict, variant: str) -> dict:
    """周日 → (防守?, 细节)。周日收盘判,作用于之后的周一到周日。"""
    suns = [d for d in days if d.weekday() == 6]
    wk = [close[d] for d in suns]
    ma200 = {}
    cl = [close[d] for d in days]
    for i, d in enumerate(days):
        if i >= 199:
            ma200[d] = float(np.mean(cl[i - 199:i + 1]))
    out, defend = {}, False
    for j, s in enumerate(suns):
        if j < 9:
            out[s] = {"defend": False, "ready": False}
            continue
        flag = wk[j] < np.mean(wk[j - 9:j + 1]) and wk[j] < wk[j - 4]
        st, tk = asof(stable, s, 7), asof(taker, s, 7)
        a, b = asof(y2, s, 5), asof(y2, s - dt.timedelta(days=60), 5)
        drain = st is not None and st <= 0
        rates_up = a is not None and b is not None and a > b
        entry = flag and drain and (rates_up if variant == "D2" else True)
        leave = (not flag) and ((st is not None and st > 0) or (tk is not None and tk >= 0.5))
        defend = (defend and not leave) or ((not defend) and entry)
        watch = {"above200_weak_taker": bool(s in ma200 and close[s] > ma200[s] and tk is not None and tk < 0.5),
                 "stable_drain": bool(drain), "rates_up": bool(rates_up)}
        out[s] = {"defend": bool(defend), "ready": True, "flag": bool(flag), "watch": watch, "stable": st, "taker": tk}
    return out


def daily_defend(days: list, weekly: dict) -> dict:
    """第 t 天是否在防守 = t 之前最近一个周日(不含 t 当天)的判定。"""
    out, cur = {}, False
    for d in days:
        out[d] = cur
        if d in weekly:
            cur = weekly[d]["defend"]
    return out


def price_defend(days: list, close: dict) -> dict:
    """Tom S-600:收盘 < 200 日线 且 跌破此前 20 天最低 ⇒ 从次日起空仓;收盘 > 200 日线 且 突破此前 20 天最高 ⇒ 次日起回满仓。"""
    cl = [close[d] for d in days]
    out, cur = {}, False
    for i, d in enumerate(days):
        out[d] = cur
        if i < 200:
            continue
        ma = np.mean(cl[i - 199:i + 1])
        lo, hi = min(cl[i - 20:i]), max(cl[i - 20:i])
        if not cur and cl[i] < ma and cl[i] < lo:
            cur = True
        elif cur and cl[i] > ma and cl[i] > hi:
            cur = False
    return out


# ── 账户 ────────────────────────────────────────────────────────────────────

def simulate(days: list, px: dict, fund: dict, defend: dict, weekly: dict | None, tickets_on: bool) -> dict:
    """逐日记账。px[sym][d] = (o, h, l, c);defend[d] = 当天多头书是否为 0。"""
    btc = px["BTC"]
    eq, nav, w_prev = 1.0, [], None
    open_t, done = {}, []
    for i, d in enumerate(days):
        if i == 0:
            nav.append(eq)
            w_prev = 0.0 if defend[d] else 1.0
            continue
        p = days[i - 1]
        w = 0.0 if defend[d] else 1.0                 # defend[d] = d 之前那个周日收盘定下的状态 ⇒ 前一天收盘换好,d 这一天的收益按 w
        pnl = eq * w * (btc[d][3] / btc[p][3] - 1) if w else 0.0
        if w != w_prev:
            pnl -= COST * abs(w - w_prev) * eq
        # 票:先按今天的高低价判出场,再记今天的浮动盈亏与资金费
        for sym in list(open_t):
            t = open_t[sym]
            o, h, l, c = px[sym][d]
            exit_px = why = None
            if h >= t["stop"]:
                exit_px, why = (max(o, t["stop"]) if o > t["stop"] else t["stop"]), ("breakeven" if t["be"] else "stop")
            elif l <= t["target"]:
                exit_px, why = (min(o, t["target"]) if o < t["target"] else t["target"]), "target"
            elif (d - t["entry_d"]).days + 1 >= TIME_D:
                exit_px, why = c, "time"
            mark = exit_px if exit_px is not None else c
            pnl += t["n"] * (t["mark"] - mark) / t["entry"]
            pnl += t["n"] * fund.get(sym, {}).get(d, 0.0)
            t["fund"] += t["n"] * fund.get(sym, {}).get(d, 0.0)
            t["mark"] = mark
            if exit_px is None and l <= t["entry"] - t["r"] and not t["be"]:
                t["stop"], t["be"] = min(t["stop"], t["entry"]), True     # 碰到 −1R ⇒ 下一天起保本
            if exit_px is not None:
                pnl -= COST * t["n"]
                t.update(exit_d=d, exit=exit_px, why=why)
                done.append(t)
                del open_t[sym]
        eq += pnl
        # 理由消失:防守在今天(周日)收盘结束 ⇒ 按今天收盘全平
        if weekly is not None and d in weekly and not weekly[d]["defend"] and open_t:
            for sym in list(open_t):
                t = open_t.pop(sym)
                eq -= COST * t["n"]
                t.update(exit_d=d, exit=t["mark"], why="reason_gone")
                done.append(t)
        # 新票:今天收盘触发,明天开盘进(明天仍在防守才进)
        if tickets_on and i + 1 < len(days) and defend.get(days[i + 1]):
            nxt = days[i + 1]
            for sym in ASSETS:
                if sym in open_t or i < 21:
                    continue
                cl = [px[sym][days[k]][3] for k in range(i - 21, i + 1)]
                lo_prev, lo_prev2 = min(cl[1:21]), min(cl[0:20])
                first = cl[21] < lo_prev and cl[20] >= lo_prev2
                f7 = [fund.get(sym, {}).get(days[k]) for k in range(i - 6, i + 1)]
                f7 = [x for x in f7 if x is not None]
                if not (first and f7 and np.mean(f7) > 0):
                    continue
                entry = px[sym][nxt][0]
                stop = min(lo_prev * RECLAIM, entry * (1 + STOP_MAX))
                if stop <= entry * 1.002:
                    continue                                         # 开盘已经站回认错线之上:这张票在进场前就失效
                risk_pct = stop / entry - 1
                n = min(RISK * eq / risk_pct, CAP_ONE * eq, CAP_ALL * eq - sum(x["n"] for x in open_t.values()))
                if n <= 0:
                    continue
                eq -= COST * n
                r = stop - entry
                open_t[sym] = {"sym": sym, "signal_d": d, "entry_d": nxt, "entry": entry, "stop": stop, "stop0": stop, "r": r,
                               "target": entry - TARGET_R * r, "n": n, "risk_usd": n * risk_pct, "mark": entry, "be": False, "fund": 0.0}
        nav.append(eq)
        w_prev = w
    for t in done:
        t["R"] = (t["n"] * (t["entry"] - t["exit"]) / t["entry"] + t["fund"] - 2 * COST * t["n"]) / t["risk_usd"]
    return {"nav": np.array(nav), "tickets": done}


# ── 尺子 ────────────────────────────────────────────────────────────────────

def underwater(days: list, nav: np.ndarray, mask=None) -> dict:
    idx = [i for i in range(len(days)) if mask is None or mask[i]]
    peak, peak_d, longest, dd = -1.0, None, 0, 0.0
    for i in idx:
        v = nav[i]
        if v >= peak:
            if peak_d is not None:
                longest = max(longest, (days[i] - peak_d).days)
            peak, peak_d = v, days[i]
        dd = max(dd, 1 - v / peak)
    now = (days[idx[-1]] - peak_d).days
    return {"longest_underwater_d": max(longest, now), "underwater_now_d": now, "max_dd": round(dd, 4),
            "total": round(float(nav[idx[-1]] / nav[idx[0]] - 1), 4)}


def episodes(days: list, close: dict) -> tuple:
    """峰 → 谷(≥ 30%)与 谷 → 峰(≥ 80%):相邻两个新高之间的最低点算一段下跌。"""
    cl = [close[d] for d in days]
    crashes, peak_i, i = [], 0, 1
    while i < len(cl):
        if cl[i] >= cl[peak_i]:
            peak_i = i
            i += 1
            continue
        j = i
        while j < len(cl) and cl[j] < cl[peak_i]:
            j += 1
        seg = range(peak_i, j)
        tr = min(seg, key=lambda k: cl[k])
        if 1 - cl[tr] / cl[peak_i] >= CRASH:
            crashes.append((days[peak_i], days[tr]))
        peak_i, i = (j, j + 1) if j < len(cl) else (peak_i, j)
    rallies = []
    for k, (p, t) in enumerate(crashes):
        nxt_peak = crashes[k + 1][0] if k + 1 < len(crashes) else days[-1]
        if close[nxt_peak] / close[t] - 1 >= RALLY:
            rallies.append((t, nxt_peak))
    return crashes, rallies


def ticket_stats(ts: list) -> dict:
    if not ts:
        return {"n": 0}
    r = np.array([t["R"] for t in ts])
    win, loss = r[r > 0], r[r <= 0]
    return {"n": len(r), "win": round(float((r > 0).mean()), 3), "mean_R": round(float(r.mean()), 3),
            "payoff": round(float(win.mean() / -loss.mean()), 2) if len(win) and len(loss) and loss.mean() < 0 else None,
            "worst_R": round(float(r.min()), 2), "best_R": round(float(r.max()), 2),
            "exits": {k: int(sum(1 for t in ts if t["why"] == k)) for k in ("target", "stop", "breakeven", "time", "reason_gone")}}


def defend_runs(days: list, defend: dict, close: dict, nav: np.ndarray) -> list:
    out, start = [], None
    for i, d in enumerate(days + [None]):
        on = defend.get(d, False) if d else False
        if on and start is None:
            start = i
        if not on and start is not None:
            a, b = days[start], days[i - 1]
            out.append({"from": str(a), "to": str(b), "days": (b - a).days + 1, "btc": round(close[b] / close[days[start - 1]] - 1, 3) if start else None,
                        "acct": round(float(nav[i - 1] / nav[start - 1] - 1), 3) if start else None})
            start = None
    return out


def report(days: list, close: dict, res: dict, defend: dict, crashes: list, rallies: list, weekly) -> dict:
    nav = res["nav"]
    pos = {d: i for i, d in enumerate(days)}
    seg_disc = np.array([d < SPLIT for d in days])
    out = {"all": underwater(days, nav), "disc": underwater(days, nav, seg_disc), "hold": underwater(days, nav, ~seg_disc),
           "crash": [], "rally": [], "tickets": {"all": ticket_stats(res["tickets"]),
                                                   "disc": ticket_stats([t for t in res["tickets"] if t["entry_d"] < SPLIT]),
                                                   "hold": ticket_stats([t for t in res["tickets"] if t["entry_d"] >= SPLIT])},
           "defend_days_share": round(float(np.mean([defend[d] for d in days])), 3)}
    first_ready = min((s for s, v in (weekly or {}).items() if v.get("ready")), default=days[0])
    for p, t in crashes:
        hold = close[t] / close[p] - 1
        acct = nav[pos[t]] / nav[pos[p]] - 1
        on = [d for d in days if p <= d <= t and defend[d]]
        out["crash"].append({"peak": str(p), "trough": str(t), "hold": round(hold, 3), "acct": round(float(acct), 3),
                             "cut": round(float(1 - acct / hold), 3) if hold < 0 else None,
                             "defend_from": str(on[0]) if on else None,
                             "btc_fall_before_defend": round(close[on[0]] / close[p] - 1, 3) if on else None,
                             "evaluable": p >= first_ready})
    for t, p in rallies:
        hold = close[p] / close[t] - 1
        acct = nav[pos[p]] / nav[pos[t]] - 1
        out["rally"].append({"trough": str(t), "peak": str(p), "hold": round(hold, 3), "acct": round(float(acct), 3),
                             "captured": round(float(np.log1p(acct) / np.log1p(hold)), 3)})
    out["runs"] = defend_runs(days, defend, close, nav)
    return out


def judge(rep: dict, hold_rep: dict, shift_pct: float) -> dict:
    ev = [c for c in rep["crash"] if c["evaluable"]]
    c1 = all(c["cut"] is not None and c["cut"] >= 0.5 for c in ev)
    c2 = rep["disc"]["longest_underwater_d"] < hold_rep["disc"]["longest_underwater_d"] and rep["hold"]["longest_underwater_d"] < hold_rep["hold"]["longest_underwater_d"]
    td, th = rep["tickets"]["disc"], rep["tickets"]["hold"]
    c3 = all(x.get("n") and x["mean_R"] > 0 and (x["payoff"] or 0) >= 2 for x in (td, th))
    c4 = shift_pct >= 0.90
    return {"i_crash_cut_ge_half": bool(c1), "ii_underwater_shorter_both": bool(c2), "iii_tickets_both_segments": bool(c3),
            "iv_shift_pct_ge_0.90": bool(c4), "shift_pct": round(shift_pct, 3), "pass": bool(c1 and c2 and c3 and c4)}


def shift_null(days, px, fund, weekly, rng) -> np.ndarray:
    suns = sorted(s for s, v in weekly.items() if v.get("ready"))
    flags = [weekly[s]["defend"] for s in suns]
    out = []
    for _ in range(N_SHIFT):
        o = int(rng.integers(8, len(suns) - 8))
        sh = dict(zip(suns, np.roll(flags, o)))
        wk = {s: {"defend": bool(sh[s]), "ready": True} for s in suns}
        dd = daily_defend(days, wk)
        res = simulate(days, px, fund, dd, wk, True)
        out.append(underwater(days, res["nav"])["longest_underwater_d"])
    return np.array(out)


def load(path: str) -> tuple:
    j = json.load(open(path))
    px = {s: {D(a): (o, h, l, c) for a, o, h, l, c in v} for s, v in j["px"].items()}
    fund = {s: {D(a): v for a, v in rows} for s, rows in j["fd"].items()}
    stable = {D(a): s for a, s, t, y in j["fm"] if s is not None}
    taker = {D(a): t for a, s, t, y in j["fm"] if t is not None}
    y2 = {D(a): y for a, s, t, y in j["fm"] if y is not None}
    return px, fund, stable, taker, y2


def run(px, fund, stable, taker, y2, n_shift=None) -> dict:
    days = sorted(d for d in px["BTC"] if d in px["ETH"])
    close = {d: px["BTC"][d][3] for d in days}
    days_w = [d for d in days if d >= START]
    crashes, rallies = episodes(days_w, close)
    out = {"window": [str(days_w[0]), str(days_w[-1])], "crashes": [(str(a), str(b)) for a, b in crashes],
           "rallies": [(str(a), str(b)) for a, b in rallies], "arms": {}}
    hold_def = {d: False for d in days_w}
    hold = simulate(days_w, px, fund, hold_def, None, False)
    hold_rep = report(days_w, close, hold, hold_def, crashes, rallies, None)
    out["arms"]["HOLD"] = hold_rep
    pdf = price_defend(days, close)
    pdf = {d: pdf[d] for d in days_w}
    out["arms"]["TOM_PRICE_FLAT"] = report(days_w, close, simulate(days_w, px, fund, pdf, None, False), pdf, crashes, rallies, None)
    rng = np.random.default_rng(SEED)
    for v in ("D1", "D2"):
        wk = weekly_states(days, close, stable, taker, y2, v)
        wk = {s: x for s, x in wk.items() if s >= START - dt.timedelta(days=7)}
        dd = daily_defend(days_w, wk)
        flat = simulate(days_w, px, fund, dd, wk, False)
        full = simulate(days_w, px, fund, dd, wk, True)
        out["arms"][f"{v}_FLAT"] = report(days_w, close, flat, dd, crashes, rallies, wk)
        rep = report(days_w, close, full, dd, crashes, rallies, wk)
        global N_SHIFT
        if n_shift:
            N_SHIFT = n_shift
        null = shift_null(days_w, px, fund, wk, rng)
        pct = float((null > rep["all"]["longest_underwater_d"]).mean())
        rep["shift_null_longest_uw"] = {"median": float(np.median(null)), "q10": float(np.quantile(null, 0.10))}
        rep["judge"] = judge(rep, hold_rep, pct)
        rep["ticket_list"] = [{k: (str(t[k]) if isinstance(t[k], dt.date) else (round(t[k], 4) if isinstance(t[k], float) else t[k]))
                               for k in ("sym", "signal_d", "entry_d", "entry", "stop0", "target", "exit_d", "exit", "why", "R")} for t in full["tickets"]]
        rep["watch"] = watch_runs(wk, dd)
        out["arms"][f"{v}_FULL"] = rep
    return out


def watch_runs(wk: dict, dd: dict) -> dict:
    """盯:任一先行条件成立的周 → 连续成段;每段是否在 26 周内走到防守、隔几周。"""
    suns = sorted(s for s, v in wk.items() if v.get("ready"))
    runs, start = [], None
    for s in suns + [None]:
        on = bool(s) and any(wk[s]["watch"].values())
        if on and start is None:
            start = s
        if not on and start is not None:
            conf = next((x for x in suns if start <= x <= start + dt.timedelta(weeks=26) and wk[x]["defend"]), None)
            runs.append({"from": str(start), "confirmed": str(conf) if conf else None,
                         "weeks_to_confirm": ((conf - start).days // 7) if conf else None})
            start = None
    return {"n": len(runs), "n_confirmed": sum(1 for r in runs if r["confirmed"]), "runs": runs}


def synthetic() -> tuple:
    rng = np.random.default_rng(1)
    d0, n = dt.date(2019, 6, 1), 2400
    px, fund = {}, {}
    for k, s in enumerate(ASSETS):
        p, rows = 100.0 * (k + 1), {}
        for i in range(n):
            d = d0 + dt.timedelta(days=i)
            drift = 0.004 * np.sin(i / 160)
            o = p
            p = max(1.0, p * np.exp(drift + 0.03 * rng.standard_normal()))
            rows[d] = (o, max(o, p) * 1.01, min(o, p) * 0.99, p)
        px[s] = rows
        fund[s] = {d0 + dt.timedelta(days=i): 0.0002 for i in range(n)}
    stable = {d0 + dt.timedelta(days=i): float(np.sin(i / 160 + 0.3)) for i in range(n)}
    taker = {d0 + dt.timedelta(days=i): 0.5 + 0.01 * float(np.sin(i / 160)) for i in range(n)}
    y2 = {d0 + dt.timedelta(days=i): 2 + float(np.cos(i / 300)) for i in range(n)}
    return px, fund, stable, taker, y2


def _fmt(rep: dict) -> str:
    keys = ("all", "disc", "hold", "defend_days_share")
    return json.dumps({k: rep[k] for k in keys}, ensure_ascii=False)


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        px, fund, stable, taker, y2 = synthetic()
        out = run(px, fund, stable, taker, y2, n_shift=5)
    else:
        px, fund, stable, taker, y2 = load(sys.argv[sys.argv.index("--from-json") + 1])
        out = run(px, fund, stable, taker, y2)
    print("WINDOW", json.dumps(out["window"]), "| crashes", json.dumps(out["crashes"]), "| rallies", json.dumps(out["rallies"]), flush=True)
    for k, rep in out["arms"].items():
        print("ARM", k, _fmt(rep), flush=True)
        print("  CRASH", k, json.dumps(rep["crash"]), flush=True)
        print("  RALLY", k, json.dumps(rep["rally"]), flush=True)
        if "judge" in rep:
            print("  TICKETS", k, json.dumps(rep["tickets"]), flush=True)
            print("  JUDGE", k, json.dumps(rep["judge"]), "| shift null", json.dumps(rep["shift_null_longest_uw"]), flush=True)
            print("  WATCH", k, json.dumps({x: rep["watch"][x] for x in ("n", "n_confirmed")}), flush=True)
    if selftest:
        # 票的四样出场都写在进场时;同一天止损与目标都碰到按止损
        days = sorted(px["BTC"])
        res = simulate(days, px, fund, {d: True for d in days}, None, True)
        assert all(t["why"] in ("target", "stop", "breakeven", "time") for t in res["tickets"])
        assert all(t["target"] < t["entry"] < t["stop0"] and t["stop"] <= t["stop0"] for t in res["tickets"])
        assert all(t["stop"] == t["entry"] for t in res["tickets"] if t["why"] == "breakeven")
        assert all(t["R"] <= TARGET_R + 0.5 for t in res["tickets"]), "单张盈利不该超过目标太多(只有资金费)"
        assert all(t["R"] >= -2.5 for t in res["tickets"] if t["why"] != "stop")
        # 满仓:净值 = BTC 收盘之比
        h = simulate(days, px, fund, {d: False for d in days}, None, False)["nav"]
        assert abs(h[-1] - px["BTC"][days[-1]][3] / px["BTC"][days[0]][3]) < 1e-9
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
        print("WROTE", OUT)
