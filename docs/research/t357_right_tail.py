#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-357 / S-832 —— 右尾在更早的年份出现过吗(R-v2 规则 × 含下架币的 Binance 现货,2018-03 → 2020-07)。

规则唯一来源:docs/research/t355_tickets.py(S-830 登记的「票源第二份」,与生产 SQL 对过 956/956)。
数据:/Volumes/CometCloudAI/cometcloud-local/research/binance_vision/spot_1d.jsonl
      (一行一个交易对;bars = [[d, o, h, l, c, quote_volume], ...])
闸门:BTC 自己的 200 日线(close > 自己的 SMA200),BTC 价格用 t339/coinmetrics_price_usd.json 的长历史。

用法:
    python3 t357_right_tail.py --probe          # 探针:数据形状 / 两档报价一致性
    python3 t357_right_tail.py --build          # 正式:出票 + 逐年统计
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
MAC = "/Volumes/CometCloudAI/cometcloud-local/research"
ARCHIVE = f"{MAC}/binance_vision/spot_1d.jsonl"
CM_BTC = f"{MAC}/t339/coinmetrics_price_usd.json"

WIN_FROM, WIN_TO = "2018-03-01", "2020-07-31"     # S-832 登记的窗口
ADV_HI, ADV_LO = 5e6, 1e6                        # 成交额门槛两档(美元)
OUT_JSON = os.path.join(HERE, "t357_results.json")


# ── 归档读取 ────────────────────────────────────────────────────────────────
def load_archive(path: str = ARCHIVE):
    """→ {symbol: {"USDT": {d: (o,h,l,c,qv)}, "BTC": {d: (o,h,l,c,qv)}}}, last_month}"""
    out = {}
    last_month = {}
    with open(path) as f:
        for line in f:
            x = json.loads(line)
            sym = x["symbol"]
            q = x["quote"]
            if q not in ("USDT", "BTC"):
                continue
            m = out.setdefault(sym, {"USDT": {}, "BTC": {}})
            for b in x.get("bars") or []:
                if len(b) < 6:
                    continue
                d = str(b[0])
                try:
                    o, h, l, c, qv = (float(b[1]), float(b[2]), float(b[3]),
                                      float(b[4]), float(b[5]))
                except (TypeError, ValueError):
                    continue
                if not (c > 0):
                    continue
                m[q][d] = (o, h, l, c, qv)
            lm = x.get("last_month_in_archive")
            if lm and (sym not in last_month or lm > last_month[sym]):
                last_month[sym] = lm
    return out, last_month


def load_btc_cm(path: str = CM_BTC):
    """Coin Metrics 的 BTC 日线 → {d: close}。"""
    raw = json.load(open(path))
    if isinstance(raw, dict):
        for k in ("data", "rows", "prices", "result"):
            if isinstance(raw.get(k), list):
                raw = raw[k]
                break
    close = {}
    for r in raw:
        if isinstance(r, dict):
            d = r.get("d") or r.get("date") or r.get("time") or r.get("Date")
            c = r.get("close") or r.get("c") or r.get("PriceUSD")
        elif isinstance(r, (list, tuple)) and len(r) >= 2:
            d, c = r[0], r[1]
        else:
            continue
        if d is None or c is None:
            continue
        try:
            close[str(d)[:10]] = float(c)
        except (TypeError, ValueError):
            continue
    return close


# ── 探针 ────────────────────────────────────────────────────────────────────
def probe():
    arc, last_month = load_archive()
    btc_usdt = arc.get("BTC", {}).get("USDT", {})
    print(json.dumps({
        "n_symbols": len(arc),
        "n_with_usdt": sum(1 for v in arc.values() if v["USDT"]),
        "n_with_btc_only": sum(1 for v in arc.values() if v["BTC"] and not v["USDT"]),
        "n_usdt_only": sum(1 for v in arc.values() if v["USDT"] and not v["BTC"]),
        "n_both": sum(1 for v in arc.values() if v["USDT"] and v["BTC"]),
        "btc_usdt_days": len(btc_usdt),
        "btc_usdt_first": sorted(btc_usdt)[:2],
        "btc_usdt_last": sorted(btc_usdt)[-2:],
        "btc_btc_days": len(arc.get("BTC", {}).get("BTC", {})),
    }, ensure_ascii=False, indent=1))

    # 两档报价一致性:USDT 收盘 vs BTC 收盘 × BTCUSDT 收盘
    ratios = []
    for sym, v in arc.items():
        if not (v["USDT"] and v["BTC"]):
            continue
        for d, b in v["USDT"].items():
            bq = v["BTC"].get(d)
            if not bq or d not in btc_usdt:
                continue
            conv = bq[3] * btc_usdt[d][3]
            if conv > 0:
                ratios.append(b[3] / conv)
    ratios.sort()
    n = len(ratios)

    def q(p):
        return ratios[min(n - 1, max(0, int(p * n)))] if n else None
    print(json.dumps({
        "n_ratio_samples": n,
        "ratio_p01": q(0.01), "ratio_p25": q(0.25), "ratio_p50": q(0.50),
        "ratio_p75": q(0.75), "ratio_p99": q(0.99),
        "ratio_min": ratios[0] if n else None,
        "ratio_max": ratios[-1] if n else None,
    }, ensure_ascii=False, indent=1))
    return 0


# ── 美元序列拼装 ────────────────────────────────────────────────────────────
def build_usd_series(arc, btc_close):
    """每个币一条美元序列:有 USDT 对的日子用 USDT 对;没有的日子用 BTC 对 ×
    当日 BTCUSDT 收盘(开高低收都乘,成交额 = BTC 计价成交额 × BTCUSDT 收盘)。

    → {symbol: {"rows": [(d,o,h,l,c,qv), ...], "usdt_days": n, "btc_days": n,
                 "first": d, "last": d, "mixed": bool}}
    """
    out = {}
    for sym, v in arc.items():
        us, bq = v["USDT"], v["BTC"]
        days = set(us) | set(bq)
        rows = []
        n_conv = 0
        for d in sorted(days):
            if d in us:
                rows.append((d,) + tuple(us[d]))
            else:
                b = bq[d]
                px = btc_close.get(d)
                if px is None:
                    continue                      # 没有 BTCUSDT 当天收盘 → 跳过这根
                n_conv += 1
                rows.append((d, b[0] * px, b[1] * px, b[2] * px, b[3] * px, b[4] * px))
        if not rows:
            continue
        out[sym] = {
            "rows": rows,
            "usdt_days": len([d for d in days if d in us]),
            "btc_days": len([d for d in days if d in bq]),
            "converted_days": n_conv,
            "first": rows[0][0], "last": rows[-1][0],
            "mixed": bool(us and bq),
        }
    return out


def build_gate(cm_close):
    """BTC 收盘 > 自己的 SMA200(Coin Metrics 长历史;不够 200 根 ⇒ 开)。"""
    days = sorted(cm_close)
    close = [cm_close[d] for d in days]
    gate = {}
    for i, d in enumerate(days):
        if i < 199:
            gate[d] = True
            continue
        sma = sum(close[i - 199: i + 1]) / 200.0
        gate[d] = bool(close[i] > sma)
    return gate, days


# ── 统计 ────────────────────────────────────────────────────────────────────
def closed_of(tickets):
    return [t for t in tickets if t["status"] == "closed" and t.get("r_mult") is not None]


def per_year_table(tickets, meta_by_sym, years):
    out = {}
    for y in years:
        tk = [t for t in tickets if t["signal_d"][:4] == y]
        entered = [t for t in tk if t.get("entry_d")]
        cl = closed_of(tk)
        rs = [t["r_mult"] for t in cl]
        big5 = sorted([t for t in cl if t["r_mult"] >= 5], key=lambda t: -t["r_mult"])
        big10 = sorted([t for t in cl if t["r_mult"] >= 10], key=lambda t: -t["r_mult"])
        best = max(rs) if rs else None
        delisted = [t for t in entered if meta_by_sym[t["symbol"]]["delisted_ever"]]
        delisted_cl = closed_of(delisted)
        out[y] = {
            "signals": len(tk),
            "blocked_gate": sum(1 for t in tk if t["status"] == "blocked"),
            "pending_never_entered": sum(1 for t in tk if t["status"] == "pending"),
            "entered": len(entered),
            "closed": len(cl),
            "still_open_at_window_end": len(entered) - len(cl),
            "r_sum": round(sum(rs), 4) if rs else 0.0,
            "r_mean": round(sum(rs) / len(rs), 4) if rs else None,
            "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 4) if rs else None,
            "r_max": round(best, 4) if best is not None else None,
            "r_sum_ex_max": round(sum(rs) - best, 4) if best is not None else 0.0,
            "n_ge5": len(big5),
            "ge5": [f"{t['symbol']}@{t['signal_d']} R={t['r_mult']:.2f}" for t in big5],
            "n_ge10": len(big10),
            "ge10": [f"{t['symbol']}@{t['signal_d']} R={t['r_mult']:.2f}" for t in big10],
            "delisted_tickets": len(delisted),
            "delisted_closed": len(delisted_cl),
            "delisted_r_sum": round(sum(t["r_mult"] for t in delisted_cl), 4),
            "delisted_names": sorted({t["symbol"] for t in delisted}),
        }
    return out


def universe_by_year(series, meta_by_sym, adv30_by_sym, thr, years):
    """每年:过了 rn≥220 且 adv30≥门槛的币数;其中后来下架的多少。"""
    out = {}
    for y in years:
        syms = set()
        for sym, m in series.items():
            adv = adv30_by_sym[sym]
            rows = m["rows"]
            for i in range(len(rows)):
                d = rows[i][0]
                if d[:4] != y:
                    continue
                if (i + 1) < 220:
                    continue
                if not (adv[i] >= thr):
                    continue
                syms.add(sym)
                break
        delisted = [s for s in syms if meta_by_sym[s]["delisted_ever"]]
        out[y] = {
            "eligible_symbols": len(syms),
            "delisted_ever": len(delisted),
            "still_listed": len(syms) - len(delisted),
        }
    return out


# ── 正式跑 ──────────────────────────────────────────────────────────────────
def build():
    sys.path.insert(0, HERE)
    import t355_tickets as T   # 规则唯一来源(S-830 对过 956/956 的那份)

    arc, last_month = load_archive()
    btc_usdt = dict(arc.get("BTC", {}).get("USDT", {}))
    cm = load_btc_cm()

    # BTCUSDT 收盘:Coin Metrics 为主(长历史),归档的 BTCUSDT 覆盖同日期
    btc_close = dict(cm)
    n_from_archive = 0
    for d, v in btc_usdt.items():
        if d in btc_close:
            n_from_archive += 1
        btc_close[d] = v[3]

    series = build_usd_series(arc, btc_close)
    gate, gate_days = build_gate(cm)

    # 元信息:下架 / 首根 bar / 是否有 USDT 报价
    ARCHIVE_END = "2020-12-31"
    meta_by_sym = {}
    for sym, m in series.items():
        meta_by_sym[sym] = {
            "first": m["first"], "last": m["last"],
            "last_month_in_archive": last_month.get(sym),
            "delisted_ever": bool(m["last"] < ARCHIVE_END),
            "delisted_by_window_end": bool(m["last"] <= WIN_TO),
            "usdt_covered": m["usdt_days"] > 0,
            "btc_converted_days": m["converted_days"],
            "mixed_quote": m["mixed"],
            "pre_archive_listing": bool(m["first"] <= "2017-08-20"),
        }

    # ── 出票:两档成交额门槛各跑一次 ──
    ARCHIVE_END = "2020-12-31"
    results = {}
    for thr, tag in ((5e6, "adv5m"), (1e6, "adv1m")):
        T.SIG_MIN_ADV30 = thr
        rows, log = T.run_scan({s: series[s]["rows"] for s in series}, gate,
                                WIN_FROM, WIN_TO, enforce_guard=True)
        rows_ng, log_ng = T.run_scan({s: series[s]["rows"] for s in series},
                                     gate, WIN_FROM, WIN_TO, enforce_guard=False)
        results[tag] = {"rows": rows, "log": log, "rows_noguard": rows_ng,
                        "log_noguard": log_ng}

    # ── 附加臂:信号窗不变,出场允许跑到归档末端(T-351 的口径:t159 的引擎
    #    会把窗末的票算完,不会留「still」)。这里只用来跟 T-351 对账。──
    T.SIG_MIN_ADV30 = 5e6
    rows_ext, log_ext = T.run_scan({s: series[s]["rows"] for s in series}, gate,
                                    WIN_FROM, ARCHIVE_END, enforce_guard=False)
    rows_ext = [t for t in rows_ext if WIN_FROM <= t["signal_d"] <= WIN_TO]
    results["adv5m_ext"] = {"rows": rows_ext, "log": log_ext}

    # ── 统计 ──
    years = ["2018", "2019", "2020"]
    out = {
        "meta": {
            "archive": ARCHIVE, "rule_source": "docs/research/t355_tickets.py",
            "window": [WIN_FROM, WIN_TO],
            "gate": "BTC 收盘 > 自己的 SMA200(Coin Metrics 长历史 t339/coinmetrics_price_usd.json)",
            "cost": "来回 0.4%(r = (exit-entry)/(entry-stop) - 0.004*entry/(entry-stop))",
            "n_symbols_in_archive": len(arc),
            "n_symbols_with_usd_series": len(series),
            "n_btcusdt_from_archive": len(btc_usdt),
            "n_btcusdt_dates_also_in_coinmetrics": n_from_archive,
            "gate_days": len(gate_days),
            "gate_first": gate_days[0] if gate_days else None,
            "gate_last": gate_days[-1] if gate_days else None,
        },
        "universe": {}, "years": {}, "verdict": {}, "selfcheck": {}, "tickets": {},
    }

    for thr, tag in ((5e6, "adv5m"), (1e6, "adv1m")):
        T.SIG_MIN_ADV30 = thr
        import numpy as np
        adv30_by_sym = {
            s: T._roll(np.array([r[5] for r in series[s]["rows"]], dtype=float),
                       29, 0, "mean")
            for s in series
        }
        out["universe"][tag] = {
            "adv_threshold_usd": thr,
            "by_year": universe_by_year(series, meta_by_sym, adv30_by_sym, thr, years),
            "n_symbols_total": len(series),
            "n_delisted_ever": sum(1 for v in meta_by_sym.values() if v["delisted_ever"]),
            "n_delisted_by_window_end": sum(1 for v in meta_by_sym.values() if v["delisted_by_window_end"]),
            "n_pre_archive_listing": sum(1 for v in meta_by_sym.values() if v["pre_archive_listing"]),
            "n_btc_only_symbols": sum(1 for v in series.values() if v["usdt_days"] == 0),
            "n_with_any_btc_conversion": sum(1 for v in series.values() if v["converted_days"] > 0),
        }
        rows = results[tag]["rows"]
        out["years"][tag] = per_year_table(rows, meta_by_sym, years)
        cl = closed_of(rows)
        big10 = [t for t in cl if t["r_mult"] >= 10]
        yrs10 = sorted({t["signal_d"][:4] for t in big10})
        out["verdict"][tag] = {
            "n_ge10": len(big10), "years_ge10": yrs10, "n_years_ge10": len(yrs10),
            "verdict_right_tail_present": bool(len(big10) >= 3 and len(yrs10) >= 2),
            "ge10_tickets": [f"{t['symbol']}@{t['signal_d']} r={t['r_mult']:.2f} "
                             f"exit={t['exit_d']}" for t in sorted(big10, key=lambda t: -t["r_mult"])],
        }
        det = []
        for t in rows:
            md = meta_by_sym[t["symbol"]]
            det.append({
                "symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
                "exit_d": t["exit_d"], "exit_reason": t["exit_reason"],
                "r": None if t["r_mult"] is None else round(t["r_mult"], 4),
                "entry_px": t["entry_px"], "exit_px": t["exit_px"], "status": t["status"],
                "gate_open": t["gate_open"], "bars_held": t["bars_held"],
                "delisted_ever": md["delisted_ever"],
                "delisted_after_ticket": bool(md["delisted_ever"] and md["last"] > (t["entry_d"] or "")),
                "quote": "USDT" if md["usdt_covered"] else "BTC->USDT",
                "pre_archive_listing": md["pre_archive_listing"],
                "sym_last_bar": md["last"],
            })
        out["tickets"][tag] = det
        out.setdefault("scan_log", {})[tag] = {"with_guard": results[tag]["log"],
                                               "no_guard": results[tag]["log_noguard"]}

    # ── 附加臂的统计(信号窗不变、出场跑到归档末端)──
    rows_ext = results["adv5m_ext"]["rows"]
    out["years"]["adv5m_ext"] = per_year_table(rows_ext, meta_by_sym, years)
    cl_ext = closed_of(rows_ext)
    big10_ext = [t for t in cl_ext if t["r_mult"] >= 10]
    yrs10_ext = sorted({t["signal_d"][:4] for t in big10_ext})
    out["verdict"]["adv5m_ext"] = {
        "n_ge10": len(big10_ext), "years_ge10": yrs10_ext, "n_years_ge10": len(yrs10_ext),
        "verdict_right_tail_present": bool(len(big10_ext) >= 3 and len(yrs10_ext) >= 2),
        "ge10_tickets": [f"{t['symbol']}@{t['signal_d']} r={t['r_mult']:.2f} "
                         f"exit={t['exit_d']}" for t in sorted(big10_ext, key=lambda t: -t["r_mult"])],
    }
    out.setdefault("scan_log", {})["adv5m_ext"] = {"with_guard": results["adv5m_ext"]["log"]}

    # ── 交叉核对:与 T-351(库里那 340 币、无下架币)逐张对 ──
    t351_path = os.path.join(HERE, "t351_results.json")
    if os.path.exists(t351_path):
        t351 = json.load(open(t351_path))
        ref = {(t["symbol"], t["signal_d"]): t for t in t351.get("tickets", [])}
        mine = {}
        for t in rows_ext:
            if t.get("entry_d"):
                mine[(t["symbol"], t["signal_d"])] = t
        both = sorted(set(ref) & set(mine))
        only_ref = sorted(set(ref) - set(mine))
        only_mine = sorted(set(mine) - set(ref))
        rdiff = []
        for k in both:
            a, b = ref[k].get("r"), mine[k].get("r_mult")
            if a is None or b is None:
                continue
            rdiff.append((k, a, b, abs(a - b)))
        rdiff.sort(key=lambda x: -x[3])
        out["crosscheck_t351"] = {
            "note": "T-351(无下架币的库宇宙) vs 本卡(归档宇宙 + 下架币),信号窗相同;出场口径同为「跑到算完」",
            "ref_n": len(ref), "mine_n": len(mine), "both": len(both),
            "only_ref": [f"{k[0]}@{k[1]}" for k in only_ref][:40],
            "only_mine": [f"{k[0]}@{k[1]}" for k in only_mine][:40],
            "n_only_ref": len(only_ref), "n_only_mine": len(only_mine),
            "r_mismatch_n": sum(1 for x in rdiff if x[3] > 0.01),
            "r_mismatch_top": [f"{k[0]}@{k[1]} ref={a:.4f} mine={b:.4f} d={d:.4f}"
                               for k, a, b, d in rdiff[:15]],
        }

    # ── 自检:BTC 2019-04-02 那张(T-351 的 +10.1282) ──
    T.SIG_MIN_ADV30 = 5e6
    rows = results["adv5m"]["rows"]
    btc_t = [t for t in rows if t["symbol"] == "BTC" and t["signal_d"] == "2019-04-02"]
    ref = {"symbol": "BTC", "signal_d": "2019-04-02", "entry_d": "2019-04-03",
           "exit_d": "2019-06-04", "entry_px": 4857.19,
           "stop_px": 4537.386428571428, "exit_px": 8115.66,
           "r": 10.128220974928803, "bars_held": 63, "src": "t351_results.json"}
    got = None
    if btc_t:
        t = btc_t[0]
        got = {"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
               "exit_d": t["exit_d"], "entry_px": t["entry_px"], "stop_px": t["stop_px"],
               "exit_px": t["exit_px"], "r": t["r_mult"], "bars_held": t["bars_held"],
               "status": t["status"], "exit_reason": t["exit_reason"]}
    out["selfcheck"] = {"reference_t351": ref, "got": got}
    if got and got.get("r") is not None:
        out["selfcheck"]["r_abs_diff"] = abs(got["r"] - ref["r"])
        out["selfcheck"]["r_rel_diff"] = abs(got["r"] - ref["r"]) / abs(ref["r"])
        out["selfcheck"]["entry_px_abs_diff"] = abs(got["entry_px"] - ref["entry_px"])
        out["selfcheck"]["same_exit_d"] = bool(got["exit_d"] == ref["exit_d"])
        out["selfcheck"]["pass"] = bool(out["selfcheck"]["r_abs_diff"] < 0.01
                                        and got["exit_d"] == ref["exit_d"])

    with open(OUT_JSON, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({"out": OUT_JSON,
                      "universe": {k: v["by_year"] for k, v in out["universe"].items()},
                      "verdict": out["verdict"],
                      "crosscheck_t351": out.get("crosscheck_t351"),
                      "selfcheck": out["selfcheck"]}, ensure_ascii=False, indent=1))
    return 0


def srcdiff(sym="EOS", d="2019-04-02"):
    """同一只票、两个数据源,逐条条件对拍:归档(Binance Vision)vs T-351 的库缓存。

    用途:解释交叉核对里那 7 张差异票(哪一条条件在哪个源上没过)。
    """
    sys.path.insert(0, HERE)
    import t355_tickets as T
    arc, _ = load_archive()
    cm = load_btc_cm()
    btc_close = dict(cm)
    for dd, v in arc.get("BTC", {}).get("USDT", {}).items():
        btc_close[dd] = v[3]
    series = build_usd_series(arc, btc_close)
    mine = series[sym]["rows"]

    cache = "/Volumes/CometCloudAI/cometcloud-local/research/t351/_bars_binance_hist.jsonl"
    db = []
    with open(cache) as f:
        for line in f:
            x = json.loads(line)
            if x["symbol"] != sym:
                continue
            c = float(x["close"])
            if c <= 0:
                continue
            db.append((x["trade_date"], float(x["open"]), float(x["high"]),
                       float(x["low"]), c, c * float(x["volume"])))
    db = sorted(set(db))

    def detail(rows, tag):
        idx = {r[0]: i for i, r in enumerate(rows)}
        if d not in idx:
            return {"src": tag, "found": False, "n_rows": len(rows),
                    "first": rows[0][0] if rows else None, "last": rows[-1][0] if rows else None}
        i = idx[d]
        det = T.signal_detail(rows, i)
        det["src"] = tag
        det["n_rows"] = len(rows)
        det["first"] = rows[0][0]
        det["last"] = rows[-1][0]
        return det

    out = {"symbol": sym, "date": d,
           "mine": detail(mine, "archive(binance_vision)"),
           "db": detail(db, "t351_db_cache")}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--srcdiff", nargs=2, metavar=("SYM", "DATE"))
    args = ap.parse_args()
    if args.probe:
        return probe()
    if args.build:
        return build()
    if args.srcdiff:
        return srcdiff(args.srcdiff[0], args.srcdiff[1])
    print("need --probe / --build / --srcdiff", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
