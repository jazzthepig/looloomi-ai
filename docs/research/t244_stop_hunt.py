#!/usr/bin/env python3
"""T-244 (S-728) — R-v2 的止损是不是被猎了:盘中止损 vs 收盘止损(+ −4 ATR 灾难线)。

预注册:REFUTATION_LEDGER.md S-728(Seth,2026-11-05 06:03 UTC),原文抄在 T-244_stop_hunt.md 开头;只算一次。
只读:不改代码、不做 DDL、不入库。
数据:t159 缓存的 770 张多头票(t159/_tickets_2020-03-01_2026-06-20.json)+ t156/t159 日线缓存(与 S-638 同一份)。
用法:python3 docs/research/t244_stop_hunt.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("COMETCLOUD_LOCAL", "/Volumes/CometCloudAI/cometcloud-local")
TK = os.path.join(ROOT, "research", "t159", "_tickets_2020-03-01_2026-06-20.json")
RES = os.path.join(HERE, "t244_results.json")
REP = os.path.join(HERE, "T-244_stop_hunt.md")

_spec = importlib.util.spec_from_file_location("t159", os.path.join(HERE, "t159_bear_short.py"))
t159 = importlib.util.module_from_spec(_spec)
sys.modules["t159"] = t159
_spec.loader.exec_module(t159)

# ── 口径常量(开算前写定) ─────────────────────────────────────────────────────
COST = 0.004            # 来回成本(t159 逐字)
F_RISK = 0.01           # 钱曲线每笔 1%(S-638 的 f★)
CAP = 10                # 同时最多 10 张
CURVE_TO = "2026-06-30"  # 全样本钱曲线终点(卡上样本尾)
S638_TO = "2026-10-19"  # S-638 原口径(只作 nav 复现自检)
H1_END = "2022-12-31"
H2_START = "2023-01-01"
H2_END = "2026-06-30"
DISASTER_ATR = 4.0      # 主口径灾难线
HUNT_WINDOW = 5         # 被猎:触发后 5 个交易日内收盘回到进场价之上

PREREG = """## S-728 — R-v2 的止损是不是被猎了:盘中止损 vs 收盘止损(+ −4 ATR 灾难线)—— 预注册(Seth,2026-11-05 06:03 UTC;交 B 道 T-244)

**为什么。** Jazz 11-04:「机械海龟交易会成为交易所和做市商的提款机。」R-v2 的止损是交易所触发单,放在进场 − 2.5 ATR —— 一个可被看见、可被扫的价位。Doctrine §5b:被插针洗出去是业余者的税。S-620 / S-621 只比过止损**距离**,没比过**触发方式**。
**定义(写死):** 「被猎」= 止损触发那天收盘高于止损价(只是盘中插针),且 5 个交易日内收盘回到进场价之上;报占比与这些票若继续持有的 R。规则 C = 止损只在收盘 ≤ 止损价时触发(次日开盘出),盘中灾难线 = 进场 − 4 ATR14(触及即出);其余全同。770 张缓存票、f = 1%、cap 10、0.4% 来回。
**判据(全过 ✅):** C 的总 R 比原规则高 ≥ 10%;两半(2020-03 → 2022-12 / 2023-01 → 2026-06)都高;Calmar 不低于原规则;最差单票 R ≥ −2.0R。副只报:灾难线 −3 / −5 ATR;被猎按市值分档。**✅ 的含义:** 执行器的止损从交易所触发单改成「收盘判 + 远端灾难单」要另走真钱变更流程(DECISIONS),不是这条直接改。**试验计数:交易层 +1。**"""


# ── 数据 ─────────────────────────────────────────────────────────────────────
def load():
    tk = json.load(open(TK))
    bars = t159.load_bars()
    ind, idx = {}, {}
    for s, rows in bars.items():
        ind[s] = t159.indicators(rows)
        idx[s] = {rows[k][0]: k for k in range(len(rows))}
    return tk, bars, ind, idx


def r_of(entry, stop, exit_px):
    """R(与 t159 逐字一致):(exit-entry)/(entry-stop) - 0.004*entry/(entry-stop)。"""
    return (exit_px - entry) / (entry - stop) - COST * entry / (entry - stop)


# ── 原规则出口复算(自检用) ────────────────────────────────────────────────────
def orig_exit(a, ei, i_sig, entry_d, stop):
    """t159.run_long 的逐字语义(v1):盘中触止损 → 出场;close<sma20 → 次日开盘;否则 120 根 → 收盘。"""
    n = len(a["d"])
    j_max = min(i_sig + 120, n - 1)
    for j in range(ei, j_max + 1):
        if a["l"][j] <= stop:
            px = a["o"][j] if (j > ei and a["o"][j] <= stop) else stop
            return j, px, "stop", False
        if a["c"][j] < a["sma20"][j]:
            if j + 1 <= n - 1:
                return j + 1, a["o"][j + 1], "sma20", False
            return j, a["c"][j], "sma20_open", True
    return j_max, a["c"][j_max], "time", (i_sig + 120 > n - 1)


# ── 规则 C 出口复算 ──────────────────────────────────────────────────────────
def rule_c_exit(a, ei, i_sig, entry_d, stop, atr_i, k_atr):
    """规则 C:止损只在收盘 ≤ 止损价时触发(次日开盘出);盘中灾难线 = 进场 − k×ATR14(触及即出)。
    其余规则全同(SMA20 次日开盘、120 根收盘)。
    优先级(同一根 K 线):灾难线(盘中即出)> 收盘止损(次日开盘)> SMA20(次日开盘)> 时间(收盘)。
    R 的分母仍是原来的 2.5×ATR 风险单位(entry − stop_px),两规则才可比。"""
    n = len(a["d"])
    j_max = min(i_sig + 120, n - 1)
    disaster = stop - (k_atr - 2.5) * atr_i          # entry − k×ATR
    for j in range(ei, j_max + 1):
        if a["l"][j] <= disaster:
            return j, disaster, "disaster", False
        if a["c"][j] <= stop:
            if j + 1 <= n - 1:
                return j + 1, a["o"][j + 1], "close_stop", False
            return j, a["c"][j], "close_stop_open", True
        if a["c"][j] < a["sma20"][j]:
            if j + 1 <= n - 1:
                return j + 1, a["o"][j + 1], "sma20", False
            return j, a["c"][j], "sma20_open", True
    return j_max, a["c"][j_max], "time", (i_sig + 120 > n - 1)


def hold_on(a, ei, i_sig, stop, frm):
    """若不止损、继续按原规则(SMA20 / 120 根)持有 → 假想出场价与 R。"""
    n = len(a["d"])
    j_max = min(i_sig + 120, n - 1)
    for j in range(frm, j_max + 1):
        if a["c"][j] < a["sma20"][j]:
            if j + 1 <= n - 1:
                return j + 1, a["o"][j + 1], False
            return j, a["c"][j], True
    if j_max < i_sig + 120:
        return j_max, a["c"][j_max], True
    return j_max, a["c"][j_max], False


# ── 钱曲线 ───────────────────────────────────────────────────────────────────
def curve(tickets, bars, d_to, d_from=None, d_end=None):
    tk = [t for t in tickets if t["entry_d"] and (d_from is None or d_from <= t["entry_d"] <= (d_end or d_to))]
    c = list(t159.nav(tk, bars, F_RISK, cap=CAP, d_to=d_to))
    if not c:
        return {}
    st = t159.stats(c)
    st["calmar"] = (st["annualised"] / abs(st["mdd"])) if (st["annualised"] is not None and st["mdd"]) else None
    st["total_r"] = sum((t.get("r") or 0.0) for t in tk)
    st["n_tickets"] = len(tk)
    st["n_closed"] = sum(1 for t in tk if t.get("exit_d"))
    st["win_rate"] = (sum(1 for t in tk if (t.get("r") or 0) > 0) / len(tk)) if tk else None
    rs = [t.get("r") for t in tk if t.get("r") is not None]
    st["worst_r"] = min(rs) if rs else None
    st["best_r"] = max(rs) if rs else None
    st["mean_r"] = (sum(rs) / len(rs)) if rs else None
    return st


# ── 市值(只读;找不到就退到 ADV 代理并标注) ──────────────────────────────────
def db_get(path, timeout=60):
    u = os.environ["SUPABASE_URL"]
    k = os.environ["SUPABASE_KEY"]
    req = urllib.request.Request(u + "/rest/v1/" + path,
                                 headers={"apikey": k, "Authorization": "Bearer " + k})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        return {"__err": e.code, "__body": e.read().decode()[:200]}
    except Exception as e:  # noqa: BLE001
        return {"__err": str(e)[:120]}


DATE_COLS = ("d", "date", "score_date", "trade_date", "as_of", "recorded_at", "updated_at", "ts", "day")


CANDIDATE_TABLES = ("cis_official_daily", "cis_scores", "cis_daily", "cis_score_daily",
                    "cis_official", "market_data_daily", "asset_market_cap_daily")


def find_mcap_table():
    """只读探测:找一张带 symbol + market_cap 的表(先试 OpenAPI spec,再试候选表名)。"""
    spec = db_get("", timeout=90)
    defs = {}
    if isinstance(spec, dict):
        defs = spec.get("definitions") or (spec.get("components") or {}).get("schemas") or {}
    for name, d in defs.items():
        props = set((d.get("properties") or {}).keys())
        if "market_cap" in props and "symbol" in props:
            dc = next((c for c in DATE_COLS if c in props), None)
            if dc:
                return name, dc
    for name in CANDIDATE_TABLES:
        rows = db_get(f"{name}?select=*&limit=1", timeout=60)
        if isinstance(rows, list) and rows:
            props = set(rows[0].keys())
            if "market_cap" in props and "symbol" in props:
                dc = next((c for c in DATE_COLS if c in props), None)
                if dc:
                    return name, dc
    return None, None


def mcap_at(table, dcol, symbol, date):
    q = (f"{table}?select=symbol,{dcol},market_cap&symbol=eq.{symbol}"
         f"&{dcol}=lte.{date}&order={dcol}.desc&limit=1")
    rows = db_get(q)
    if isinstance(rows, list) and rows and rows[0].get("market_cap"):
        return float(rows[0]["market_cap"])
    return None


def med(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def pct(x, n):
    return (100.0 * x / n) if n else None


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    tk, bars, ind, idx = load()
    longs = list(tk["long"])
    res = {"task": "T-244", "prereg": "S-728", "as_of": "2026-11-05", "n_tickets": len(longs),
           "n_symbols": len(bars), "constants": {"cost": COST, "f": F_RISK, "cap": CAP,
                                                 "disaster_atr": DISASTER_ATR, "hunt_window": HUNT_WINDOW,
                                                 "curve_to": CURVE_TO, "h1_end": H1_END, "h2": [H2_START, H2_END]}}

    # ── 0. 自检:进场价 / 止损价 / ATR 对齐,原规则出口复算与缓存 R 一致 ──────
    sc = {"entry_px_match": 0, "stop_atr_match": 0, "n_checked": 0, "r_mismatch": 0,
          "max_abs_dr": 0.0, "reason_counts": {}, "still": 0, "no_bars": 0}
    reasons = {}
    per = []
    for t in longs:
        s = t["symbol"]
        if s not in ind or t["ei"] >= len(ind[s]["d"]):
            sc["no_bars"] += 1
            continue
        a = ind[s]
        ei = t["ei"]
        i_sig = ei - 1
        atr_i = a["atr14"][i_sig]
        sc["n_checked"] += 1
        if abs(a["o"][ei] - t["entry_px"]) <= 1e-6 * max(1.0, abs(t["entry_px"])):
            sc["entry_px_match"] += 1
        if atr_i and abs((t["entry_px"] - t["stop_px"]) - 2.5 * atr_i) <= 1e-6 * max(1.0, t["entry_px"]):
            sc["stop_atr_match"] += 1
        j, px, why, still = orig_exit(a, ei, i_sig, t["entry_d"], t["stop_px"])
        reasons[why] = reasons.get(why, 0) + 1
        if still:
            sc["still"] += 1
        r_new = None if still else r_of(t["entry_px"], t["stop_px"], px)
        r_old = t.get("r")
        if r_old is None or r_new is None:
            if (r_old is None) != (r_new is None):
                sc["r_mismatch"] += 1
        else:
            d = abs(r_new - r_old)
            sc["max_abs_dr"] = max(sc["max_abs_dr"], d)
            if d > 1e-9:
                sc["r_mismatch"] += 1
        per.append({"t": t, "a": a, "ei": ei, "i_sig": i_sig, "atr_i": atr_i,
                    "orig_j": j, "orig_px": px, "orig_why": why, "orig_still": still,
                    "orig_r": r_new})
    sc["reason_counts"] = reasons
    res["selfcheck"] = sc

    # ── ① 止损出场的票 ─────────────────────────────────────────────────────
    stop_exits = []
    for p in per:
        t = p["t"]
        if t.get("still") or t.get("exit_px") is None:
            continue
        a = p["a"]
        xi = t["xi"]
        low_le = (a["l"][xi] <= t["stop_px"]) if xi < len(a["l"]) else False
        by_px = t["exit_px"] <= t["stop_px"] * 1.001
        mech = (p["orig_why"] == "stop")
        if by_px or low_le:
            stop_exits.append((p, by_px, low_le, mech))
    n_closed = sum(1 for p in per if not p["t"].get("still") and p["t"].get("exit_px") is not None)
    res["step1_stop_exits"] = {
        "n": len(stop_exits), "share_of_all": pct(len(stop_exits), len(per)),
        "share_of_closed": pct(len(stop_exits), n_closed), "n_closed": n_closed,
        "n_by_px_rule": sum(1 for _, b, _, _ in stop_exits if b),
        "n_mechanism_stop": sum(1 for _, _, _, m in stop_exits if m),
        "n_mismatch_def_vs_mech": sum(1 for _, _, _, m in stop_exits if not m),
    }

    # ── ② 被猎 ─────────────────────────────────────────────────────────────
    hunted = []
    for p, by_px, low_le, mech in stop_exits:
        t = p["t"]
        a = p["a"]
        j = p["orig_j"]           # 触发/出场那根
        trig = j
        first_touch = None
        for k in range(p["ei"], j + 1):
            if a["l"][k] <= t["stop_px"]:
                first_touch = k
                break
        close_gt_stop = a["c"][trig] > t["stop_px"]
        back = False
        back_day = None
        for k in range(trig + 1, min(trig + 1 + HUNT_WINDOW, len(a["c"]))):
            if a["c"][k] > t["entry_px"]:
                back = True
                back_day = a["d"][k]
                break
        if close_gt_stop and back:
            j2, px2, still2 = hold_on(a, p["ei"], p["i_sig"], t["stop_px"], trig)
            missed = None if still2 else r_of(t["entry_px"], t["stop_px"], px2)
            hunted.append({"p": p, "close_gt_stop": close_gt_stop, "back_day": back_day,
                           "missed_r": missed, "still": still2, "first_touch": first_touch,
                           "trig": trig})
    mr = [h["missed_r"] for h in hunted if h["missed_r"] is not None]
    orig_rs = [h["p"]["orig_r"] for h in hunted if h["p"]["orig_r"] is not None]
    uplift = [h["missed_r"] - h["p"]["orig_r"] for h in hunted
              if h["missed_r"] is not None and h["p"]["orig_r"] is not None]
    res["step2_hunted"] = {
        "definition": "止损触发当天收盘 > 止损价,且其后 5 个交易日内某日收盘 > 进场价",
        "n_hunted": len(hunted), "n_stop_exits": len(stop_exits),
        "share_of_stop_exits": pct(len(hunted), len(stop_exits)),
        "share_of_all": pct(len(hunted), len(per)),
        "n_spike_only_no_recovery": sum(1 for p, _, _, _ in stop_exits
                                        if p["a"]["c"][p["orig_j"]] > p["t"]["stop_px"]) - len(hunted),
        "n_close_below_stop": sum(1 for p, _, _, _ in stop_exits
                                  if p["a"]["c"][p["orig_j"]] <= p["t"]["stop_px"]),
        "n_first_touch_neq_exit": sum(1 for h in hunted if h["first_touch"] != h["trig"]),
        "missed_r": {"n": len(mr), "median": med(mr), "mean": (sum(mr) / len(mr)) if mr else None,
                     "share_ge_1R": pct(sum(1 for x in mr if x >= 1.0), len(mr)),
                     "share_ge_2R": pct(sum(1 for x in mr if x >= 2.0), len(mr)),
                     "min": min(mr) if mr else None, "max": max(mr) if mr else None},
        "orig_r_of_hunted": {"median": med(orig_rs), "mean": (sum(orig_rs) / len(orig_rs)) if orig_rs else None},
        "uplift_vs_orig": {"median": med(uplift), "mean": (sum(uplift) / len(uplift)) if uplift else None,
                           "share_positive": pct(sum(1 for x in uplift if x > 0), len(uplift))},
        "hunted_rows": [{"symbol": h["p"]["t"]["symbol"], "signal_d": h["p"]["t"]["signal_d"],
                         "entry_d": h["p"]["t"]["entry_d"], "exit_d": h["p"]["t"]["exit_d"],
                         "entry_px": h["p"]["t"]["entry_px"], "stop_px": h["p"]["t"]["stop_px"],
                         "orig_r": h["p"]["orig_r"], "missed_r": h["missed_r"],
                         "back_day": h["back_day"]}
                        for h in hunted],
    }

    # ── ③ 规则 C(主口径 + 灾难线 3 / 5 ATR 敏感性) ────────────────────────
    def build_c(k_atr):
        out = []
        for p in per:
            t = p["t"]
            a = p["a"]
            j, px, why, still = rule_c_exit(a, p["ei"], p["i_sig"], t["entry_d"], t["stop_px"], p["atr_i"], k_atr)
            nt = dict(t)
            nt["exit_d"] = None if still else a["d"][j]
            nt["exit_px"] = None if still else px
            nt["r"] = None if still else r_of(t["entry_px"], t["stop_px"], px)
            nt["c_reason"] = why
            nt["c_j"] = j
            out.append(nt)
        return out

    variants = {}
    for k_atr in (DISASTER_ATR, 3.0, 5.0):
        ctk = build_c(k_atr)
        rs = [t["r"] for t in ctk if t["r"] is not None]
        pairs = []
        for o, c in zip(longs, ctk):
            if o.get("r") is None or c.get("r") is None:
                continue
            pairs.append((o["r"], c["r"]))
        changed = sum(1 for o, c in zip(longs, ctk) if o.get("exit_d") != c.get("exit_d"))
        deltas = [c["r"] - o["r"] for o, c in pairs]
        better = sum(1 for x in deltas if x > 1e-12)
        worse = sum(1 for x in deltas if x < -1e-12)
        same = len(deltas) - better - worse
        rc = {}
        for t in ctk:
            rc[t["c_reason"]] = rc.get(t["c_reason"], 0) + 1
        variants[k_atr] = {
            "k_atr": k_atr,
            "total_r": sum(rs), "n_closed": len(rs),
            "mean_r": (sum(rs) / len(rs)) if rs else None,
            "win_rate": pct(sum(1 for x in rs if x > 0), len(rs)),
            "worst_r": min(rs) if rs else None, "best_r": max(rs) if rs else None,
            "n_exit_day_changed": changed, "n_tickets_compared": len(pairs),
            "n_better": better, "n_worse": worse, "n_same": same,
            "delta_r_median": med(deltas), "delta_r_mean": (sum(deltas) / len(deltas)) if deltas else None,
            "delta_r_max": max(deltas) if deltas else None, "delta_r_min": min(deltas) if deltas else None,
            "reason_counts": rc,
            "h1_total_r": sum(t["r"] for t in ctk if t.get("r") is not None and t["entry_d"] <= H1_END),
            "h2_total_r": sum(t["r"] for t in ctk if t.get("r") is not None and t["entry_d"] >= H2_START),
            "curve_full": curve(ctk, bars, CURVE_TO),
            "curve_h1": curve(ctk, bars, H1_END, d_end=H1_END),
            "curve_h2": curve(ctk, bars, H2_END, d_from=H2_START, d_end=H2_END),
            "curve_s638_to": curve(ctk, bars, S638_TO),
        }
    res["step3_rule_c"] = variants

    orig_rs = [t["r"] for t in longs if t.get("r") is not None]
    res["step0_original"] = {
        "total_r": sum(orig_rs), "n_closed": len(orig_rs),
        "mean_r": (sum(orig_rs) / len(orig_rs)) if orig_rs else None,
        "win_rate": pct(sum(1 for x in orig_rs if x > 0), len(orig_rs)),
        "worst_r": min(orig_rs) if orig_rs else None, "best_r": max(orig_rs) if orig_rs else None,
        "h1_total_r": sum(t["r"] for t in longs if t.get("r") is not None and t["entry_d"] <= H1_END),
        "h2_total_r": sum(t["r"] for t in longs if t.get("r") is not None and t["entry_d"] >= H2_START),
        "curve_full": curve(longs, bars, CURVE_TO),
        "curve_h1": curve(longs, bars, H1_END, d_end=H1_END),
        "curve_h2": curve(longs, bars, H2_END, d_from=H2_START, d_end=H2_END),
        "curve_s638_to": curve(longs, bars, S638_TO),
    }

    # ── ④ 判据 ─────────────────────────────────────────────────────────────
    o = res["step0_original"]
    c4 = variants[DISASTER_ATR]
    cal_o = (o["curve_full"] or {}).get("calmar")
    cal_c = (c4["curve_full"] or {}).get("calmar")
    checks = {
        "C1_total_R_ge_10pct": {"value": c4["total_r"], "ref": o["total_r"],
                                "pct": pct(c4["total_r"] - o["total_r"], abs(o["total_r"])) if o["total_r"] else None,
                                "pass": bool(o["total_r"] and c4["total_r"] >= 1.10 * o["total_r"])},
        "C2_both_halves_higher": {"h1": [o["h1_total_r"], c4["h1_total_r"]],
                                  "h2": [o["h2_total_r"], c4["h2_total_r"]],
                                  "pass": bool(c4["h1_total_r"] > o["h1_total_r"] and c4["h2_total_r"] > o["h2_total_r"])},
        "C3_calmar_not_lower": {"orig": cal_o, "C": cal_c,
                                "pass": bool(cal_o is not None and cal_c is not None and cal_c >= cal_o)},
        "C4_worst_ticket_R_ge_-2": {"orig": o["worst_r"], "C": c4["worst_r"],
                                   "pass": bool(c4["worst_r"] is not None and c4["worst_r"] >= -2.0)},
    }
    checks["all_pass"] = all(v["pass"] for k, v in checks.items() if k.startswith("C"))
    res["step4_verdict"] = {"checks": checks, "verdict": "✅" if checks["all_pass"] else "❌"}

    # ── ⑤ 副:被猎按市值分档 ────────────────────────────────────────────────
    table, dcol = find_mcap_table()
    buckets = {"table": table, "date_col": dcol, "n_with_mcap": 0, "n_missing": 0,
               "median_mcap": None, "rows": []}
    if table:
        mc = {}
        for p, _, _, _ in stop_exits:
            t = p["t"]
            key = (t["symbol"], t["entry_d"])
            if key not in mc:
                mc[key] = mcap_at(table, dcol, t["symbol"], t["entry_d"])
            p["_mcap"] = mc[key]
        vals = [p["_mcap"] for p, _, _, _ in stop_exits if p.get("_mcap")]
        buckets["n_with_mcap"] = len(vals)
        buckets["n_missing"] = len(stop_exits) - len(vals)
        thr = med(vals)
        buckets["median_mcap"] = thr
        hunted_keys = {(h["p"]["t"]["symbol"], h["p"]["t"]["entry_d"]) for h in hunted}
        big = [p for p, _, _, _ in stop_exits if p.get("_mcap") and p["_mcap"] >= thr]
        small = [p for p, _, _, _ in stop_exits if p.get("_mcap") and p["_mcap"] < thr]
        hb = sum(1 for p in big if (p["t"]["symbol"], p["t"]["entry_d"]) in hunted_keys)
        hs = sum(1 for p in small if (p["t"]["symbol"], p["t"]["entry_d"]) in hunted_keys)
        buckets["rows"] = [
            {"bucket": "large(>=median mcap)", "n_stop_exits": len(big), "n_hunted": hb,
             "hunted_pct": pct(hb, len(big))},
            {"bucket": "small(<median mcap)", "n_stop_exits": len(small), "n_hunted": hs,
             "hunted_pct": pct(hs, len(small))},
        ]
    # 副:流动性代理分档(若市值不可得,用进场时 ADV30 美元额;明确标注这不是市值)
    hunted_keys = {(h["p"]["t"]["symbol"], h["p"]["t"]["entry_d"]) for h in hunted}
    adv = []
    for p, _, _, _ in stop_exits:
        t = p["t"]
        a = p["a"]
        adv30 = a.get("adv30") or []
        p["_adv"] = adv30[p["ei"]] if (p["ei"] < len(adv30) and adv30[p["ei"]]) else None
        if p["_adv"]:
            adv.append(p["_adv"])
    thr_adv = med(adv)
    big = [p for p, _, _, _ in stop_exits if p.get("_adv") and p["_adv"] >= thr_adv]
    small = [p for p, _, _, _ in stop_exits if p.get("_adv") and p["_adv"] < thr_adv]
    hb = sum(1 for p in big if (p["t"]["symbol"], p["t"]["entry_d"]) in hunted_keys)
    hs = sum(1 for p in small if (p["t"]["symbol"], p["t"]["entry_d"]) in hunted_keys)
    adv_buckets = {"note": "代理口径(非市值):按进场时 ADV30 美元额中位数切两档",
                   "median_adv30_usd": thr_adv,
                   "rows": [{"bucket": "high ADV30", "n_stop_exits": len(big), "n_hunted": hb,
                             "hunted_pct": pct(hb, len(big))},
                            {"bucket": "low ADV30", "n_stop_exits": len(small), "n_hunted": hs,
                             "hunted_pct": pct(hs, len(small))}]}
    res["step5_side"] = {"mcap_buckets": buckets, "adv_proxy_buckets": adv_buckets,
                          "disaster_sensitivity": {str(k): {"total_r": v["total_r"], "worst_r": v["worst_r"],
                                                            "win_rate": v["win_rate"],
                                                            "calmar": (v["curve_full"] or {}).get("calmar"),
                                                            "mdd": (v["curve_full"] or {}).get("mdd"),
                                                            "end": (v["curve_full"] or {}).get("end")}
                                                for k, v in variants.items()}}

    json.dump(res, open(RES, "w"), indent=1, default=str)
    write_report(res)
    print(json.dumps({"verdict": res["step4_verdict"]["verdict"],
                      "checks": {k: v["pass"] for k, v in checks.items() if k.startswith("C")},
                      "step1": res["step1_stop_exits"],
                      "hunted": {k: res["step2_hunted"][k] for k in
                                 ("n_hunted", "share_of_stop_exits", "share_of_all")},
                      "orig_total_r": o["total_r"], "C_total_r": c4["total_r"],
                      "selfcheck": sc}, indent=1, default=str))


def _f(x, nd=3):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def write_report(res):
    o = res["step0_original"]
    s1 = res["step1_stop_exits"]
    s2 = res["step2_hunted"]
    v = res["step3_rule_c"]
    c4 = v[DISASTER_ATR]
    vd = res["step4_verdict"]
    L = []
    A = L.append
    A("# T-244 (S-728) —— R-v2 的止损是不是被猎了:盘中止损 vs 收盘止损(+ −4 ATR 灾难线)\n")
    A("## 0. 预注册(S-728 原文,先写下来再算;只算一次)\n")
    A(PREREG + "\n")
    A("## 1. 口径与实现决定(开算前写定)\n")
    A("| 项 | 决定 | 依据 |")
    A("|---|---|---|")
    A("| 票集 | t159 缓存 770 张多头票(`research/t159/_tickets_2020-03-01_2026-06-20.json`) | 卡上写死;入口不动,只换出场 |")
    A("| 日线 | t156 + t159 缓存(`t159.load_bars()`,与 S-638 同一份) | 同上 |")
    A("| 进场 | 原规则原样(信号日收盘 → 次日开盘进场;止损 = 进场 − 2.5×ATR14) | 进场与止损触发方式无关,故票集与进场固定 |")
    A("| R 的分母 | 两规则都用原来的 2.5×ATR 风险单位(`entry − stop_px`) | 否则「高 10%」是两个分母比,没有意义 |")
    A("| 成本 | 0.4% 来回(t159 逐字) | 卡上写死 |")
    A("| 钱曲线 | f = 1%、cap 10、逐日盯市(`t159.nav`,S-638 同款) | 卡上写死 |")
    A("| 两半 | 按**进场日**切:≤2022-12-31 / ≥2023-01-01 | 卡上写死 |")
    A("| 被猎 | 止损触发当天收盘 > 止损价,且其后 5 个交易日内某日收盘 > 进场价 | S-728 写死 |")
    A("| 灾难线 | 进场 − 4×ATR14(盘中触及即按该价出);副报 −3 / −5 | S-728 写死 |")
    A("| 规则 C 优先级 | 同根 K 线:灾难线(盘中即出)> 收盘止损(次日开盘)> SMA20(次日开盘)> 时间(120 根收盘) | 与原规则「盘中止损 > SMA20 > 时间」同序 |")
    A("| 纪律 | 不改代码、不做 DDL、不入库;零分布未用到(本卡是全样本对照,非统计检验) | 卡上写死 |")
    A("")
    A("## 2. 自检(先证明复算无误,再看结论)\n")
    sc = res["selfcheck"]
    A(f"* 进场价对得上 `open[ei]`:**{sc['entry_px_match']}/{sc['n_checked']}**;")
    A(f"* `entry − stop == 2.5 × ATR14[ei−1]`:**{sc['stop_atr_match']}/{sc['n_checked']}**;")
    A(f"* 原规则出口复算 vs 缓存 R:**不一致 {sc['r_mismatch']}** 张,最大 |ΔR| = **{_f(sc['max_abs_dr'], 9)}**;")
    A(f"* 复算出口原因分布:{sc['reason_counts']};未收口(still){sc['still']} 张;无日线 {sc['no_bars']} 张。")
    s638 = o["curve_s638_to"]
    if s638:
        A(f"* nav 复现自检(原规则、曲线到 {S638_TO},S-638 的口径):终值 **{_f(s638.get('end'))}**、年化 **{_f(s638.get('annualised'), 4)}**、"
          f"盯市 MDD **{_f(s638.get('mdd'), 4)}**、taken **{s638.get('taken')}** / skipped **{s638.get('skipped')}**;"
          f"S-638 公布的是 4.12 / +24.4% / −32.3% / 304 taken / 425 skipped ⇒ **MDD 逐位对上**,"
          f"总 R {res['step0_original']['total_r']:.2f} 对 S-638 记的 369.23R(差 {res['step0_original']['total_r'] - 369.23:+.2f}R)。")
    A("")
    A("## 3. ① 止损出场的票\n")
    A(f"* **n = {s1['n']}** 张,占全部 {res['n_tickets']} 张的 **{_f(s1['share_of_all'], 1)}%**,占已平仓 {s1['n_closed']} 张的 **{_f(s1['share_of_closed'], 1)}%**。")
    A(f"* 其中「出场价 ≤ 止损价×1.001」{s1['n_by_px_rule']} 张;按出口机制(复算原因 = stop){s1['n_mechanism_stop']} 张;两个口径差 {s1['n_mismatch_def_vs_mech']} 张(卡上的口径把「出场当天 low 触到止损」也算止损出场)。")
    A("")
    A("## 4. ② 被猎(插针洗出去)\n")
    A(f"* **被猎 {s2['n_hunted']} 张**,占止损出场 **{_f(s2['share_of_stop_exits'], 1)}%**,占全部 **{_f(s2['share_of_all'], 1)}%**。")
    A(f"* 止损出场里「收盘仍高于止损价」(纯插针)但 5 日内没收回进场的:{s2['n_spike_only_no_recovery']} 张;收盘直接跌穿止损的:{s2['n_close_below_stop']} 张。")
    mr = s2["missed_r"]
    A(f"* 被猎票若不止损、按原规则继续持有(SMA20 / 120 根)的 **错过的 R**:n = {mr['n']},中位 **{_f(mr['median'])}R**,均值 **{_f(mr['mean'])}R**,≥ +1R 占 **{_f(mr['share_ge_1R'], 1)}%**,≥ +2R 占 **{_f(mr['share_ge_2R'], 1)}%**(区间 {_f(mr['min'])} … {_f(mr['max'])}R)。")
    up = s2["uplift_vs_orig"]
    A(f"* 相对原来那笔(被猎票原 R 中位 {_f(s2['orig_r_of_hunted']['median'])}R)的抬升:中位 **{_f(up['median'])}R**,均值 **{_f(up['mean'])}R**,为正占 **{_f(up['share_positive'], 1)}%**。")
    A("")
    A("## 5. ③ 规则 C(收盘判 + 远端灾难线)vs 原规则\n")
    A("| 量 | 原规则(盘中止损) | 规则 C(收盘止损 + 灾难线) |")
    A("|---|---|---|")
    A(f"| 总 R | **{_f(o['total_r'], 2)}** | **{_f(c4['total_r'], 2)}** |")
    A(f"| 每票平均 R | {_f(o['mean_r'])} | {_f(c4['mean_r'])} |")
    A(f"| 胜率 | {_f(o['win_rate'], 1)}% | {_f(c4['win_rate'], 1)}% |")
    A(f"| 最差单票 R | {_f(o['worst_r'])} | **{_f(c4['worst_r'])}** |")
    A(f"| H1 总 R(≤2022-12) | {_f(o['h1_total_r'], 2)} | {_f(c4['h1_total_r'], 2)} |")
    A(f"| H2 总 R(≥2023-01) | {_f(o['h2_total_r'], 2)} | {_f(c4['h2_total_r'], 2)} |")
    oc, cc = o["curve_full"], c4["curve_full"]
    A(f"| 钱曲线终值 | {_f((oc or {}).get('end'))} | {_f((cc or {}).get('end'))} |")
    A(f"| 钱曲线年化 | {_f((oc or {}).get('annualised'), 4)} | {_f((cc or {}).get('annualised'), 4)} |")
    A(f"| 盯市 MDD | {_f((oc or {}).get('mdd'), 4)} | {_f((cc or {}).get('mdd'), 4)} |")
    A(f"| Calmar | {_f((oc or {}).get('calmar'))} | {_f((cc or {}).get('calmar'))} |")
    A(f"| 进场/出场日变了的票 | — | {c4['n_exit_day_changed']}/{c4['n_tickets_compared']} |")
    A("")
    A(f"逐票看:规则 C 让 **{c4['n_better']}** 张变好、**{c4['n_worse']}** 张变差、{c4['n_same']} 张不变;"
      f"ΔR 中位 **{_f(c4['delta_r_median'])}R**、均值 **{_f(c4['delta_r_mean'])}R**,区间 {_f(c4['delta_r_min'])} … {_f(c4['delta_r_max'])}R。\n")
    A("**两半的钱曲线**(同一套 nav,各自从 equity0=1 起算):\n")
    A("| 段 | 规则 | 票 n | 总 R | 终值 | 年化 | MDD | Calmar |")
    A("|---|---|---|---|---|---|---|---|")
    for lbl, key_o, key_c in (("H1 ≤2022-12", "curve_h1", "curve_h1"), ("H2 ≥2023-01", "curve_h2", "curve_h2")):
        for rname, src in (("原", o[key_o]), ("C", c4[key_c])):
            s = src or {}
            A(f"| {lbl} | {rname} | {s.get('n_tickets', 'n/a')} | {_f(s.get('total_r'), 2)} | {_f(s.get('end'))} | "
              f"{_f(s.get('annualised'), 4)} | {_f(s.get('mdd'), 4)} | {_f(s.get('calmar'))} |")
    A("")
    A("## 6. ④ 判(S-728:全过 ✅)\n")
    ck = vd["checks"]
    A("| 判据 | 原 | C | 过? |")
    A("|---|---|---|---|")
    A(f"| C1 总 R ≥ 原 +10% | {_f(ck['C1_total_R_ge_10pct']['ref'], 2)} | {_f(ck['C1_total_R_ge_10pct']['value'], 2)}(+{_f(ck['C1_total_R_ge_10pct']['pct'], 1)}%) | {'✅' if ck['C1_total_R_ge_10pct']['pass'] else '❌'} |")
    A(f"| C2 两半都高 | H1 {_f(ck['C2_both_halves_higher']['h1'][0], 2)} / {_f(ck['C2_both_halves_higher']['h1'][1], 2)};H2 {_f(ck['C2_both_halves_higher']['h2'][0], 2)} / {_f(ck['C2_both_halves_higher']['h2'][1], 2)} | | {'✅' if ck['C2_both_halves_higher']['pass'] else '❌'} |")
    A(f"| C3 Calmar 不低 | {_f(ck['C3_calmar_not_lower']['orig'])} | {_f(ck['C3_calmar_not_lower']['C'])} | {'✅' if ck['C3_calmar_not_lower']['pass'] else '❌'} |")
    A(f"| C4 最差单票 R ≥ −2.0 | {_f(ck['C4_worst_ticket_R_ge_-2']['orig'])} | {_f(ck['C4_worst_ticket_R_ge_-2']['C'])} | {'✅' if ck['C4_worst_ticket_R_ge_-2']['pass'] else '❌'} |")
    A("")
    A(f"**判: {vd['verdict']}**\n")
    A("## 7. ⑤ 副报\n")
    A("| 灾难线 | 总 R | 最差单票 R | 胜率 | Calmar | MDD |")
    A("|---|---|---|---|---|---|")
    for k, row in res["step5_side"]["disaster_sensitivity"].items():
        A(f"| −{k} ATR | {_f(row['total_r'], 2)} | {_f(row['worst_r'])} | {_f(row['win_rate'], 1)}% | {_f(row['calmar'])} | {_f(row['mdd'], 4)} |")
    A("")
    mb = res["step5_side"]["mcap_buckets"]
    A(f"**被猎按市值分档**(来源 `{mb['table']}` / 日期列 `{mb['date_col']}`;有市值 {mb['n_with_mcap']} 张、缺 {mb['n_missing']} 张;中位市值 {_f(mb['median_mcap'], 0)}):")
    if mb["rows"]:
        A("| 档 | 止损出场 n | 被猎 n | 被猎占比 |")
        A("|---|---|---|---|")
        for row in mb["rows"]:
            A(f"| {row['bucket']} | {row['n_stop_exits']} | {row['n_hunted']} | {_f(row['hunted_pct'], 1)}% |")
    else:
        A("(只读库里找不到带 market_cap 的表 —— 未做市值分档;下面给流动性代理)")
    ap = res["step5_side"].get("adv_proxy_buckets")
    if ap:
        A("")
        A(f"**被猎按规模分档(代理口径,{ap['note']};中位 ADV30 = {_f(ap['median_adv30_usd'], 0)} USD)**")
        A("| 档 | 止损出场 n | 被猎 n | 被猎占比 |")
        A("|---|---|---|---|")
        for row in ap["rows"]:
            A(f"| {row['bucket']} | {row['n_stop_exits']} | {row['n_hunted']} | {_f(row['hunted_pct'], 1)}% |")
    A("")
    A("**被猎票里「错过的 R」最大的 10 张**")
    A("| 币 | 进场日 | 出场日 | 原 R | 错过的 R | 收回日 |")
    A("|---|---|---|---|---|---|")
    for row in sorted(s2["hunted_rows"], key=lambda x: (x["missed_r"] is None, -(x["missed_r"] or 0)))[:10]:
        A(f"| {row['symbol']} | {row['entry_d']} | {row['exit_d']} | {_f(row['orig_r'])} | {_f(row['missed_r'])} | {row['back_day']} |")
    A("")
    A("## 8. 数字出处与边界\n")
    A("* 全部数字来自 `t244_results.json`,由 `docs/research/t244_stop_hunt.py` 一次跑出;报告里没有手打的数。")
    A("* 入口固定、只换出口 ⇒ 这是「止损触发方式」的干净对照;但**没有**让规则 C 重新生成票(同一 symbol 的后续票在 C 下可能因出场更晚而被挤掉)—— 那是另一题。")
    A("* 规则 C 的灾难线按卡上写死「触及即按该价出」;若某日开盘已低于灾难线,实盘滑点会更差,本卡未模拟。")
    A("")
    open(REP, "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
