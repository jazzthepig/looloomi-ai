#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-358 —— S-832 复核更正(T-357 的「后来下架」口径反了 + 右尾密度没有零信号基准率)。

① **下架口径改回取数脚本的判活口径**:下架 = `last_month_in_archive < (取数月 − 12 个月)`
   —— 取数脚本 `scripts/research/fetch_binance_vision_spot.py:89` 取 last_month、`:145` 判活
   (「归档停更超过一年 ⇒ 下架」)。T-357 用的是 `t357_right_tail.py:278` 的 `bars 末日 < 2020-12-31`,
   而归档本身只下到 2020-12 ⇒ **2021 之后才下架的币全被算成「活」**。
② **零信号对照**:闸门开着的日子里随机入场、票数与实际相同、同一套出场规则,≥ 500 次
   (零分布 / 分位 / p 值一律走 `src/data/evaluation/apparatus.py`)。
③ **闸门曝光**:每年闸门开 / 关的天数。

只读;不入库。用法:
    python3 t358_delisted_recompute.py --build     # ①③:宇宙表 + 票 + 闸门(约 1 分钟)
    python3 t358_delisted_recompute.py --null      # ②:零信号对照(读 t358_results.json)
    python3 t358_delisted_recompute.py --selftest  # 模拟器对照真实引擎(t355_tickets.run_scan)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # 仓库根(src/ 在下面)
MAC = "/Volumes/CometCloudAI/cometcloud-local/research"
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import t355_tickets as T          # 规则唯一来源(S-830 对过 956/956 的那份)
import t357_right_tail as T357    # 归档读取 / 美元序列 / 闸门(不重写)
from src.data.evaluation.apparatus import (   # 零分布 / 分位 / p 值只许走这里
    null_distribution, percentile_of, p_upper, p_lower, random_dates_like,
)

ARCHIVE = f"{MAC}/binance_vision/spot_1d.jsonl"
MANIFEST = f"{MAC}/binance_vision/manifest.json"
CM_BTC = f"{MAC}/t339/coinmetrics_price_usd.json"
OUT_JSON = os.path.join(HERE, "t358_results.json")

WIN_FROM, WIN_TO = "2018-03-01", "2020-07-31"      # S-832 登记的窗口(与 T-357 同)
YEARS = ["2018", "2019", "2020"]
ADV_HI, ADV_LO = 5e6, 1e6                          # 成交额门槛两档(美元)
SEED = 20261112
N_NULL = 500                                        # 卡上要求 ≥ 500 次


# ── ① 下架口径(取数脚本同口径) ──────────────────────────────────────────────
def delisted_cutoff(manifest_path: str = MANIFEST):
    """→ (cutoff_str, fetch_month_str, manifest)。cutoff = 取数月减 12 个月(字符串比较,与 :145 同)。"""
    man = json.load(open(manifest_path))
    fm = man["written_at"][:7]                       # 取数月,例 "2026-11"
    cutoff = f"{int(fm[:4]) - 1}-{fm[5:]}"           # "2025-11"
    return cutoff, fm, man


def is_delisted(last_month, cutoff: str) -> bool:
    return (last_month or "") < cutoff


# ── 逐年宇宙:过了 rn≥220 与成交额门槛的币(照 T-357 的同一段逻辑,多返回名单) ──
def universe_symbols(series, adv30_by_sym, thr, year):
    out = set()
    for sym, m in series.items():
        adv = adv30_by_sym[sym]
        rows = m["rows"]
        for i in range(len(rows)):
            d = rows[i][0]
            if d[:4] != year:
                continue
            if (i + 1) < 220:
                continue
            if not (adv[i] >= thr):
                continue
            out.add(sym)
            break
    return sorted(out)


# ── 每符号状态(进出场模拟器用) ──────────────────────────────────────────────
def build_states(series):
    st = {}
    for sym, m in series.items():
        rows = m["rows"]
        f = T.features(rows)
        st[sym] = {
            "rows": rows,
            "idx": {r[0]: i for i, r in enumerate(rows)},
            "sma20": f["sma20"], "atr14": f["atr14"],
        }
    return st


def simulate_entry(state, signal_d, win_to=WIN_TO):
    """照 t355_tickets.run_scan 的同一套规则模拟一张票:信号日 → 进场 → 出场 → R。

    顺序逐条照引擎:进场(下一根 bar 的开盘,止损 = open − 2.5×ATR14)→ 每根 bar 计 bars_held
    → 止损(最低价触及;跳空低开用开盘价)→ 收盘破 SMA20 标记(次日开盘出)→ 120 根到期(收盘出)
    → 该币停印超 9 天(按最后一根收盘平掉,出场日 = 最后一根的日期)。
    窗末还在场的票不出场(引擎状态 'open',R 为 None)。
    """
    rows, idx = state["rows"], state["idx"]
    sma20, atr14 = state["sma20"], state["atr14"]
    n = len(rows)
    i = idx.get(signal_d)
    if i is None:
        return None
    j = i + 1
    if j >= n:
        return None
    atr = float(atr14[i])          # 引擎在信号当天锁定 ATR14(不是进场那天)
    if not (atr > 0):
        return None
    entry_px = float(rows[j][1])
    stop = entry_px - T.STOP_ATR_MULT * atr
    if stop <= 0:
        return None
    entry_d = rows[j][0]
    denom = entry_px - stop

    def close(d, px, reason):
        if d > win_to:            # 引擎的扫描停在窗末 ⇒ 窗末还在场(R 为 None)
            return {"entry_d": entry_d, "entry_px": entry_px, "stop_px": stop,
                    "exit_d": None, "exit_px": None, "exit_reason": None, "r_mult": None}
        return {"entry_d": entry_d, "entry_px": entry_px, "stop_px": stop,
                "exit_d": d, "exit_px": px, "exit_reason": reason,
                "r_mult": ((px - entry_px) / denom - T.COST * entry_px / denom) if denom else None}

    bars_held = 1          # 引擎里进场当天的 bar 也计一次
    exit_flag = False
    for k in range(j, n):
        d = rows[k][0]
        o = float(rows[k][1]); l = float(rows[k][3]); c = float(rows[k][4])
        if k > j:
            if exit_flag:                       # 昨天标记了破 SMA20 → 今天开盘出
                return close(d, o, "sma20")
            bars_held += 1
        if l <= stop:                           # 止损
            px = o if (d > entry_d and o <= stop) else stop
            return close(d, px, "stop")
        if c < float(sma20[k]):                 # 收盘破 SMA20 → 标记
            exit_flag = True
        if (not exit_flag) and bars_held >= T.MAX_BARS_HELD:   # 到期
            return close(d, c, "time")
    # 停印:引擎在「最后一根 bar + 10 天」那天平掉,出场日 = 最后一根的日期
    last = rows[-1]
    close_day = dt.date.fromisoformat(last[0]) + dt.timedelta(days=10)
    if close_day > dt.date.fromisoformat(win_to):
        return {"entry_d": entry_d, "entry_px": entry_px, "stop_px": stop,
                "exit_d": None, "exit_px": None, "exit_reason": None, "r_mult": None}
    return close(last[0], float(last[4]), "no_data")


def candidate_days(state, gate, win_from=WIN_FROM, win_to=WIN_TO):
    """该符号可当「信号日」的日期:有 bar、闸门开、下一根 bar 在窗内、ATR 与止损有效。"""
    rows, idx = state["rows"], state["idx"]
    sma20, atr14 = state["sma20"], state["atr14"]
    n = len(rows)
    out = []
    for i in range(n):
        d = rows[i][0]
        if d < win_from or d > win_to:
            continue
        j = i + 1
        if j >= n or rows[j][0] > win_to:
            continue
        if not bool(gate.get(d, True)):
            continue
        atr = float(atr14[i])      # 信号当天的 ATR(与引擎一致)
        if not (atr > 0):
            continue
        if float(rows[j][1]) - T.STOP_ATR_MULT * atr <= 0:
            continue
        out.append(d)
    return out


# ── ② 零信号对照 ───────────────────────────────────────────────────────────
def _sim_set(states, picks):
    """picks = [(sym, signal_d)] → 出场结果列表(跳过无效进场)。"""
    res = []
    for sym, d in picks:
        st = states.get(sym)
        if st is None:
            continue
        r = simulate_entry(st, d)
        if r is None:
            continue
        res.append(dict(r, symbol=sym, signal_d=d))
    return res


def null_n2(rng, states, cand_by_year, eligible_by_year, n_by_year):
    """臂 N2:随机币 × 随机闸门开着的日子(票数与实际逐年相同)。"""
    picks = []
    for y in YEARS:
        pool = eligible_by_year.get(y, [])
        n = n_by_year.get(y, 0)
        if not pool or n <= 0:
            continue
        syms = rng.choice(len(pool), size=min(n, len(pool)), replace=False)
        for k in syms:
            sym = pool[int(k)]
            days_y = cand_by_year.get(sym, {}).get(y) or []
            if not days_y:
                continue
            picks.append((sym, days_y[int(rng.integers(0, len(days_y)))]))
    return picks


def null_n1(rng, states, cand, events):
    """臂 N1:同样的币、同样逐年、随机换日子(闸门开着的日子);同一币的票不许重叠。"""
    picks = []
    taken = {}
    for sym, d0 in events:
        days = cand.get(sym) or []
        if not days:
            continue
        same_year = [d for d in days if d[:4] == d0[:4]] or days
        chosen = None
        for _ in range(40):
            (_k, d) = random_dates_like([(sym, d0)], {sym: same_year}, rng,
                                         stratum=lambda x: str(x)[:4])[0]
            if d is None:
                break
            iv = taken.get(sym) or []
            if all(not (a <= d <= b) for a, b in iv):
                chosen = d
                break
        if chosen is None:
            continue
        r = simulate_entry(states[sym], chosen)
        end = (r["exit_d"] or chosen) if r else chosen
        taken.setdefault(sym, []).append((chosen, end))
        picks.append((sym, chosen))
    return picks


# ── 正式跑 ──────────────────────────────────────────────────────────────────
def build():
    cutoff, fetch_month, man = delisted_cutoff()
    arc, last_month = T357.load_archive(ARCHIVE)
    cm = T357.load_btc_cm(CM_BTC)
    btc_usdt = dict(arc.get("BTC", {}).get("USDT", {}))
    btc_close = dict(cm)
    n_from_archive = 0
    for d, v in btc_usdt.items():
        if d in btc_close:
            n_from_archive += 1
        btc_close[d] = v[3]
    series = T357.build_usd_series(arc, btc_close)
    gate, gate_days = T357.build_gate(cm)

    # ── 元信息:两种下架口径 ──
    meta = {}
    for sym, m in series.items():
        lm = last_month.get(sym)
        meta[sym] = {
            "first": m["first"], "last": m["last"], "last_month_in_archive": lm,
            "dead_new": is_delisted(lm, cutoff),              # 取数脚本口径
            "dead_old": bool(m["last"] < "2020-12-31"),        # T-357 用的代理(错的)
            "dead_by_window_end": bool(m["last"] <= WIN_TO),
        }
    n_total = len(meta)
    n_new = sum(1 for v in meta.values() if v["dead_new"])
    n_old = sum(1 for v in meta.values() if v["dead_old"])
    death_by_year = {}
    for v in meta.values():
        if v["dead_new"]:
            k = (v["last_month_in_archive"] or "?" )[:4]
            death_by_year[k] = death_by_year.get(k, 0) + 1

    # ── 出票(两档门槛) ──
    results = {}
    adv30_by_sym = {}
    for thr, tag in ((ADV_HI, "adv5m"), (ADV_LO, "adv1m")):
        T.SIG_MIN_ADV30 = thr
        rows, log = T.run_scan({s: series[s]["rows"] for s in series}, gate,
                                WIN_FROM, WIN_TO, enforce_guard=True)
        adv30_by_sym = {
            s: T._roll(np.array([r[5] for r in series[s]["rows"]], dtype=float), 29, 0, "mean")
            for s in series
        }
        results[tag] = {"rows": rows, "log": log, "adv30_by_sym": adv30_by_sym}

    # 附加臂:信号窗不变,出场允许跑到归档末端(T-351 的口径)—— 窗末那几张票才有 R
    T.SIG_MIN_ADV30 = ADV_HI
    rows_ext, log_ext = T.run_scan({s: series[s]["rows"] for s in series}, gate,
                                    WIN_FROM, "2020-12-31", enforce_guard=False)
    rows_ext = [t for t in rows_ext if WIN_FROM <= t["signal_d"] <= WIN_TO]
    results["adv5m_ext"] = {"rows": rows_ext, "log": log_ext}

    # ── 逐年宇宙表(新口径) ──
    universe = {}
    for thr, tag in ((ADV_HI, "adv5m"), (ADV_LO, "adv1m")):
        adv30_by_sym = results[tag]["adv30_by_sym"]
        by_year = {}
        for y in YEARS:
            syms = universe_symbols(series, adv30_by_sym, thr, y)
            dead = [s for s in syms if meta[s]["dead_new"]]
            by_year[y] = {
                "eligible_symbols": len(syms),
                "truly_dead": len(dead),
                "still_listed": len(syms) - len(dead),
                "dead_names": dead,
                "eligible_names": syms,
            }
        universe[tag] = {
            "adv_threshold_usd": thr,
            "by_year": by_year,
            "n_symbols_total": n_total,
            "n_truly_dead_all": n_new,
            "n_still_listed_all": n_total - n_new,
            "n_dead_old_t357": n_old,
            "n_missed_by_old": n_new - n_old,
            "death_year_hist": death_by_year,
        }

    # ── 逐年票表(新口径的「开在后来下架的币上」两列) ──
    years_tbl = {}
    for tag in ("adv5m", "adv1m", "adv5m_ext"):
        rows = results[tag]["rows"]
        per_year = {}
        for y in YEARS:
            tk = [t for t in rows if t["signal_d"][:4] == y]
            entered = [t for t in tk if t.get("entry_d")]
            cl = [t for t in tk if t["status"] == "closed" and t.get("r_mult") is not None]
            rs = [t["r_mult"] for t in cl]
            big10 = [t for t in cl if t["r_mult"] >= 10]
            dead_tk = [t for t in entered if meta[t["symbol"]]["dead_new"]]
            dead_cl = [t for t in dead_tk if t["status"] == "closed" and t.get("r_mult") is not None]
            best = max(rs) if rs else None
            per_year[y] = {
                "signals": len(tk),
                "blocked_gate": sum(1 for t in tk if t["status"] == "blocked"),
                "entered": len(entered),
                "closed": len(cl),
                "still_open_at_window_end": len(entered) - len(cl),
                "r_sum": round(sum(rs), 4) if rs else 0.0,
                "r_mean": round(sum(rs) / len(rs), 4) if rs else None,
                "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 4) if rs else None,
                "r_max": round(best, 4) if best is not None else None,
                "r_sum_ex_max": round(sum(rs) - best, 4) if best is not None else 0.0,
                "n_ge5": sum(1 for r in rs if r >= 5),
                "n_ge10": len(big10),
                "ge10": [f"{t['symbol']}@{t['signal_d']} R={t['r_mult']:.2f}" for t in big10],
                # 新口径:开在后来下架的币上
                "dead_tickets_entered": len(dead_tk),
                "dead_tickets_closed": len(dead_cl),
                "dead_r_sum": round(sum(t["r_mult"] for t in dead_cl), 4),
                "dead_names": sorted({t["symbol"] for t in dead_tk}),
                "dead_tickets": [f"{t['symbol']}@{t['signal_d']} R="
                                 f"{'' if t.get('r_mult') is None else format(t['r_mult'], '.3f')}"
                                 f" exit={t.get('exit_d')}" for t in dead_tk],
                # 老口径(对照)
                "dead_old_tickets_entered": sum(1 for t in entered if meta[t["symbol"]]["dead_old"]),
            }
        years_tbl[tag] = per_year

    # ── 闸门曝光 ──
    d0, d1 = dt.date.fromisoformat(WIN_FROM), dt.date.fromisoformat(WIN_TO)
    gate_tbl = {}
    tot_open = tot_days = 0
    for y in YEARS:
        days = [d for d in sorted(gate_days) if WIN_FROM <= d <= WIN_TO and d[:4] == y]
        open_d = [d for d in days if bool(gate.get(d, True))]
        closed_d = [d for d in days if not bool(gate.get(d, True))]
        # 闸门重开的第一天(该年第一次开)
        first_open = open_d[0] if open_d else None
        gate_tbl[y] = {
            "calendar_days": len(days),
            "gate_open_days": len(open_d),
            "gate_closed_days": len(closed_d),
            "first_open_day": first_open,
            "open_days_list": open_d if len(open_d) <= 40 else open_d[:20] + ["…"] + open_d[-10:],
        }
        tot_open += len(open_d); tot_days += len(days)
    # 窗口内闸门从关到开的第一天(2019)
    reopen = None
    prev = None
    for d in sorted(gate_days):
        if d < WIN_FROM:
            prev = bool(gate.get(d, True)); continue
        if d > WIN_TO:
            break
        cur = bool(gate.get(d, True))
        if cur and not prev:
            reopen = d
            break
        prev = cur

    out = {
        "meta": {
            "card": "T-358",
            "archive": ARCHIVE,
            "rule_source": "docs/research/t355_tickets.py",
            "window": [WIN_FROM, WIN_TO],
            "delisted_definition": f"last_month_in_archive < '{cutoff}'(取数月 {fetch_month} − 12 个月;"
                                   "同 scripts/research/fetch_binance_vision_spot.py:145)",
            "fetch_month": fetch_month, "delisted_cutoff": cutoff,
            "manifest_written_at": man.get("written_at"),
            "n_symbols": n_total,
            "n_truly_dead": n_new, "n_still_listed": n_total - n_new,
            "n_dead_old_T357": n_old, "n_missed_by_old": n_new - n_old,
            "death_year_hist": death_by_year,
            "gate": "BTC 收盘 > 自己的 SMA200(Coin Metrics 长历史)",
            "cost": "来回 0.4%",
        },
        "universe": universe,
        "years": years_tbl,
        "gate": {"by_year": gate_tbl, "window_days": tot_days,
                 "window_gate_open_days": tot_open, "first_reopen_day": reopen},
    }

    # ── 模拟器自检:同一套规则能不能复现引擎出的票 ──
    states = build_states(series)
    out["simulator_check"] = simulator_check(states, results["adv5m"]["rows"])
    # 顺带把零信号对照需要的输入落盘(避免下一轮重跑)
    out["_control_inputs"] = {
        "n_by_year_adv5m": {y: years_tbl["adv5m"][y]["entered"] for y in YEARS},
        "eligible_by_year_adv5m": {y: universe["adv5m"]["by_year"][y]["eligible_names"] for y in YEARS},
        "actual_tickets_adv5m": [{"symbol": t["symbol"], "signal_d": t["signal_d"],
                                  "r": t.get("r_mult"), "status": t["status"]}
                                 for t in results["adv5m"]["rows"] if t.get("entry_d")],
    }
    json.dump(out, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"universe": {t: {y: {k: v for k, v in universe[t]["by_year"][y].items()
                                          if k not in ("dead_names", "eligible_names")}
                                    for y in YEARS} for t in universe},
                      "gate": out["gate"], "simulator_check": out["simulator_check"]},
                     ensure_ascii=False, indent=1))
    return 0


def simulator_check(states, rows):
    """用模拟器复跑引擎出的每张票(进场日 / 出场日 / R),报告不一致的条数。"""
    bad = []
    n = 0
    for t in rows:
        if not t.get("entry_d"):
            continue
        n += 1
        st = states.get(t["symbol"])
        r = simulate_entry(st, t["signal_d"]) if st else None
        if r is None:
            bad.append({"ticket": t["ticket_id"], "why": "sim_none"})
            continue
        dr = None if (r["r_mult"] is None or t.get("r_mult") is None) else abs(r["r_mult"] - t["r_mult"])
        if (r["entry_d"] != t["entry_d"] or (dr is not None and dr > 1e-9)
                or (r["exit_d"] or "") != (t.get("exit_d") or "")
                or (r["r_mult"] is None) != (t.get("r_mult") is None)):
            bad.append({"ticket": t["ticket_id"], "sim": [r["entry_d"], r["exit_d"], r["r_mult"],
                                                          r["exit_reason"]],
                        "engine": [t["entry_d"], t.get("exit_d"), t.get("r_mult"),
                                   t.get("exit_reason")]})
    return {"n_checked": n, "n_mismatch": len(bad), "examples": bad[:8]}


def run_null():
    d = json.load(open(OUT_JSON))
    cutoff, fetch_month, _ = delisted_cutoff()
    arc, last_month = T357.load_archive(ARCHIVE)
    cm = T357.load_btc_cm(CM_BTC)
    btc_close = dict(cm)
    for d_, v in dict(arc.get("BTC", {}).get("USDT", {})).items():
        btc_close[d_] = v[3]
    series = T357.build_usd_series(arc, btc_close)
    gate, _ = T357.build_gate(cm)
    states = build_states(series)
    cand = {sym: candidate_days(st, gate) for sym, st in states.items()}
    cand_by_year = {}
    for sym, days in cand.items():
        by = {}
        for dd in days:
            by.setdefault(dd[:4], []).append(dd)
        cand_by_year[sym] = by
    inp = d["_control_inputs"]
    n_by_year = inp["n_by_year_adv5m"]
    eligible_by_year = inp["eligible_by_year_adv5m"]
    events = [(t["symbol"], t["signal_d"]) for t in inp["actual_tickets_adv5m"]]

    # 实际:窗内 R≥10 的张数
    actual_n_ge10 = sum(1 for t in inp["actual_tickets_adv5m"] if (t["r"] or -99) >= 10)
    actual_sum = sum(t["r"] for t in inp["actual_tickets_adv5m"] if t["r"] is not None)

    actual_win = (sum(1 for t in inp["actual_tickets_adv5m"]
                      if (t["r"] or 0.0) > 0) / len(events)) if events else 0.0

    def make_fn(picks_fn, stat="n_ge10"):
        """stat ∈ {n_ge10, sum_r, n_tickets, win_rate}。
        同一 seed ⇒ 同一批抽样 ⇒ 四个零分布逐位对齐(可相减、可配对读)。"""
        def fn(rng):
            picks = picks_fn(rng)
            res = _sim_set(states, picks)
            if stat == "n_ge10":
                return float(sum(1 for r in res if (r["r_mult"] or -99) >= 10))
            if stat == "sum_r":
                return float(sum((r["r_mult"] or 0.0) for r in res))
            if stat == "n_tickets":
                return float(len(res))
            nw = sum(1 for r in res if (r["r_mult"] or 0.0) > 0)
            return float(nw) / float(len(res)) if res else 0.0
        return fn

    def try_null(picks_fn, stat, actual_v):
        try:
            arr = null_distribution(make_fn(picks_fn, stat), N_NULL, SEED, actual=actual_v)
            return arr, None
        except Exception as e:                      # apparatus 的 NoOpNull 等
            return None, f"{type(e).__name__}: {e}"

    out = {"actual_n_ge10": actual_n_ge10, "actual_n_tickets": len(events),
           "actual_r_sum": round(actual_sum, 4),
           "actual_win_rate": round(actual_win, 4),
           "n_null": N_NULL, "seed": SEED}

    for arm, picks_fn in (
        ("N2_random_symbol_random_day",
         lambda rng: null_n2(rng, states, cand_by_year, eligible_by_year, n_by_year)),
        ("N1_same_symbol_random_day",
         lambda rng: null_n1(rng, states, cand, events)),
    ):
        rec = {}
        # ── 主判据:R≥10 张数(结构与 seed 与上一轮一致 ⇒ 逐位可比) ──
        null, err = try_null(picks_fn, "n_ge10", float(actual_n_ge10))
        if null is None:
            rec["error"] = err
        else:
            rec["null"] = {
                "n": int(null.size),
                "mean": round(float(null.mean()), 4),
                "median": round(float(np.median(null)), 4),
                "max": int(null.max()),
                "hist": {str(int(v)): int(c) for v, c in
                         zip(*np.unique(null, return_counts=True))},
                "p_ge_1": round(float((null >= 1).mean()), 4),
            }
            rec["percentile_of_actual"] = round(percentile_of(float(actual_n_ge10), null), 4)
            rec["p_upper"] = round(p_upper(float(actual_n_ge10), null), 4)
            rec["p_lower"] = round(p_lower(float(actual_n_ge10), null), 4)
        # ── 附加(账本口径,探索性):ΣR / 每轮实际注数 / 胜率 ──
        for stat, act, key in (("sum_r", actual_sum, "null_sum_r"),
                                ("n_tickets", float(len(events)), "null_n_tickets"),
                                ("win_rate", actual_win, "null_win_rate")):
            a2, e2 = try_null(picks_fn, stat, float(act))
            if a2 is None:
                rec[key] = {"error": e2}
                continue
            rec[key] = {
                "actual": round(float(act), 4),
                "null_mean": round(float(a2.mean()), 4),
                "null_median": round(float(np.median(a2)), 4),
                "null_min": round(float(a2.min()), 4),
                "null_max": round(float(a2.max()), 4),
                "percentile_of_actual": round(percentile_of(float(act), a2), 4),
                "p_upper": round(p_upper(float(act), a2), 4),
                "p_lower": round(p_lower(float(act), a2), 4),
            }
        out[arm] = rec

    out["_note"] = ("主判据 = R≥10 张数的零分布与实际 1 张的分位;null_sum_r / null_n_tickets / "
                    "null_win_rate 是同一批抽样(同 seed)的账本口径附加统计,探索性。"
                    "N1/N2 的抽样逐位对齐。")
    json.dump(out, open(os.path.join(HERE, "t358_null_results.json"), "w"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--null", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.build:
        return build()
    if a.null:
        return run_null()
    if a.selftest:
        return build()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
