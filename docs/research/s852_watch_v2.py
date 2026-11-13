"""S-852(11-13,Seth 写、lane 跑):盯盘基率第二版 —— 改掉 S-851 定义的两处毛病,并记下每一段在「开始盯 / 最高点 / 结束」三个时点的派发清单读数。

登记见 REFUTATION_LEDGER `## S-852`(**写于看过 S-851 结果之后**,所以这是修正定义后的描述,不是检验)。只读,不动钱。
用法(仓库根目录;与 s851_watch_base_rate.py 放在同一目录):
    python3 docs/research/s852_watch_v2.py --selftest
    nohup python3 docs/research/s852_watch_v2.py > docs/research/s852_run.txt 2>&1 &
产出 docs/research/s852_results.json。
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

import numpy as np

_sp = importlib.util.spec_from_file_location("s851", os.path.join(os.path.dirname(os.path.abspath(__file__)), "s851_watch_base_rate.py"))
S = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(S)

OUT = "docs/research/s852_results.json"
MIN_CONDS, MAX_WATCH_D, INVALID_D, POST_D = 2, 180, 14, 56


def episodes_v2(days, cond: dict, wdown: dict, close: dict) -> list[dict]:
    """与 S-851 的两处不同:① 开始盯的那天周线必须没坏;② 不设 30 天安静期 —— 上一段结束之后,条件 ≥ 2 条且周线没坏的第一天就是新的一段。"""
    out, i, n = [], 0, len(days)
    while i < n:
        d = days[i]
        if not ((cond.get(d) or 0) >= MIN_CONDS and wdown.get(d) is False):
            i += 1
            continue
        peak, peak_d, zero_run, end, how = close[d], d, 0, None, "timeout"
        j = i
        for j in range(i + 1, min(i + MAX_WATCH_D, n - 1) + 1):
            x = days[j]
            if close.get(x, 0) > peak:
                peak, peak_d = close[x], x
            if wdown.get(x):
                end, how = x, "confirmed"
                break
            zero_run = zero_run + 1 if (cond.get(x) or 0) == 0 else 0
            if zero_run >= INVALID_D:
                end, how = x, "invalidated"
                break
        end = end or days[j]
        post = close.get(end + dt.timedelta(days=POST_D))
        out.append({"start": str(d), "peak": str(peak_d), "end": str(end), "outcome": how, "days": (end - d).days, "days_to_peak": (peak_d - d).days,
                    "max_runup_pct": round((peak / close[d] - 1) * 100, 1), "ret_start_to_end_pct": round((close[end] / close[d] - 1) * 100, 1),
                    "ret_peak_to_end_pct": round((close[end] / peak - 1) * 100, 1),
                    "ret_8w_after_end_pct": None if post is None else round((post / close[end] - 1) * 100, 1)})
        i = max(j, i) + 1
    return out


def readings(ep: list[dict], series: dict) -> None:
    """每一段在 开始 / 最高点 / 结束 三个时点的清单读数(≤ 当天的最近一个值,太旧就 None)。series[name] = (dates, values, max_age)。"""
    for e in ep:
        for when in ("start", "peak", "end"):
            d = S.D(e[when])
            e[f"at_{when}"] = {name: (None if (v := S.asof(ds, vs, d, age)) is None else round(float(v), 4)) for name, (ds, vs, age) in series.items()}


def etf_5d(dates: list, vals: list) -> tuple[list, list]:
    """ETF 净流入(按可得日)→ 滚动 5 个交易日合计(十亿美元)。"""
    out = [float(sum(vals[max(0, i - 4):i + 1])) / 1e9 for i in range(len(vals))]
    return dates, out


def run(days, close, dist200, taker, stable, y2_d, y2_v, extra: dict) -> dict:
    wdown = S.weekly_down_days(days, close)
    cond = {d: S.conditions(d, close, dist200, taker, stable, y2_d, y2_v) for d in days}
    ep = episodes_v2(days, cond, wdown, close)
    tk = sorted((d, v) for d, v in taker.items() if v is not None)
    st = sorted((d, v) for d, v in stable.items() if v is not None)
    series = {"taker_buy_share_30d": ([a for a, _ in tk], [b for _, b in tk], 5), "stable_supply_30d": ([a for a, _ in st], [b for _, b in st], 5), **extra}
    readings(ep, series)
    conf = [e for e in ep if e["outcome"] == "confirmed"]

    def med(key):
        xs = [e[key] for e in conf if e.get(key) is not None]
        return None if not xs else round(float(np.median(xs)), 1)
    summary = {"n": len(ep), "confirmed": len(conf), "invalidated": sum(1 for e in ep if e["outcome"] == "invalidated"), "timeout": sum(1 for e in ep if e["outcome"] == "timeout"),
               "confirmed_median": {k: med(k) for k in ("days", "days_to_peak", "max_runup_pct", "ret_start_to_end_pct", "ret_peak_to_end_pct", "ret_8w_after_end_pct")},
               "confirmed_8w_after_negative": sum(1 for e in conf if (e["ret_8w_after_end_pct"] or 0) < 0)}
    cut = days[len(days) // 2]
    close2 = {d: v * (2.0 if d > cut else 1.0) for d, v in close.items()}
    ep2 = episodes_v2(days, cond, S.weekly_down_days(days, close2), close2)
    key = lambda e: (e["start"], e["end"], e["outcome"], e["max_runup_pct"])
    lim = str(cut - dt.timedelta(days=POST_D))
    checks = {"episodes_before_cut_ignore_future_prices": [key(e) for e in ep if e["end"] <= lim] == [key(e) for e in ep2 if e["end"] <= lim],
              "no_start_while_weekly_already_down": all(wdown.get(S.D(e["start"])) is False for e in ep),
              "episodes_do_not_overlap": all(ep[i]["end"] < ep[i + 1]["start"] for i in range(len(ep) - 1)),
              "episodes_since_2026_08": [(e["start"], e["peak"], e["end"], e["outcome"], e["max_runup_pct"]) for e in ep if e["start"] >= "2026-08-01"]}
    return {"summary": summary, "self_checks": checks, "episodes": ep}


def load_extra() -> dict:
    out = {}
    for name, series, age in (("fng", "fng", 5), ("funding_7d_ann", None, 5), ("btc_mvrv", "btc_mvrv", 5), ("ust_2y", "ust_2y", 10), ("usdjpy", "usdjpy", 12)):
        if series is None:
            rows = S.get("state_daily", {"select": "d,value", "entity": "eq.panel", "feature": "eq.funding_7d_ann_binance", "d": "gte.2019-01-01", "order": "d.asc"})
        else:
            rows = S.get("macro_daily", {"select": "d,value", "series": f"eq.{series}", "d": "gte.2019-01-01", "order": "d.asc"})
        rows = [r for r in rows if r.get("value") is not None]
        out[name] = ([S.D(r["d"]) for r in rows], [float(r["value"]) for r in rows], age)
        print("loaded", name, len(rows), flush=True)
    rows = [r for r in S.get("macro_daily", {"select": "d,value", "series": "eq.btc_etf_net_flow_usd", "order": "d.asc"}) if r.get("value") is not None]
    ds, vs = etf_5d([S.D(r["d"]) for r in rows], [float(r["value"]) for r in rows])
    out["btc_etf_flow_5d_bn"] = (ds, vs, 5)
    return out


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        base = S.synthetic()
        days_all = base[5]
        rng = np.random.default_rng(3)
        extra = {"fng": (days_all, list(map(float, 50 + 20 * np.sin(np.arange(len(days_all)) / 60.0))), 5),
                 "btc_etf_flow_5d_bn": etf_5d(days_all[2000:], list(map(float, rng.normal(0, 2e8, len(days_all) - 2000)))) + (5,)}
    else:
        base, extra = S.load_live(), load_extra()
    out = run(*base, extra)
    print("SUMMARY", json.dumps(out["summary"], ensure_ascii=False), flush=True)
    print("SELF_CHECKS", json.dumps(out["self_checks"], ensure_ascii=False), flush=True)
    for e in out["episodes"]:
        print("EP", json.dumps({k: e[k] for k in ("start", "peak", "end", "outcome", "days", "days_to_peak", "max_runup_pct", "ret_peak_to_end_pct", "ret_8w_after_end_pct")}), flush=True)
        print("   AT", json.dumps({w: e[f"at_{w}"] for w in ("start", "peak", "end")}), flush=True)
    if selftest:
        c = out["self_checks"]
        assert out["summary"]["n"] >= 5 and c["episodes_before_cut_ignore_future_prices"] and c["no_start_while_weekly_already_down"] and c["episodes_do_not_overlap"]
        assert all("fng" in e["at_peak"] and "btc_etf_flow_5d_bn" in e["at_start"] for e in out["episodes"])
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
