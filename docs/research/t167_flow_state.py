"""S-660:山寨合约未平仓总额 20 日在涨 + 一半以上的币主动买盘占优 ⇒ R-v2 满仓,否则 0.25 仓。

预注册原文在台账 REFUTATION_LEDGER.md「S-660」一节(2026-10-21 13:36 UTC 写于算任何结果之前)。
票 = R-v2 的 770 张(t159_bear_short.run_long 逐张复现,仍持有的按最后收盘盯市 = s657.mtm),
装载走 t159.load_bars() —— 它同时读 t156 的 _bars_early.jsonl(2018 → 2025-04)与 t159 的 _bars.jsonl,
只读 t159 会从 2025-04 才开始、T-164 就是这样错的。判据与零假设复用 s659_equity_state.py 的 book() / 循环平移。
状态数据 = deriv_metrics_daily(source binance_vision_metrics,publishable key,2020-10-01 起),
按 (symbol, d) 缓存到 <root>/research/t167/。用法:python3 docs/research/t167_flow_state.py [--root ...]
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
CACHE = os.path.join(ROOT, "research", "t167")
os.makedirs(CACHE, exist_ok=True)
os.environ.setdefault("T159_DATA", os.path.join(ROOT, "research", "t159") + "/")
os.environ.setdefault("T156_DATA", os.path.join(ROOT, "research", "t156") + "/")
sys.path.insert(0, os.path.join(HERE, "..", ".."))

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}
SINCE = "2020-10-01"          # deriv_metrics_daily 的起点(S-660 数据节)
EXCL = {"BTC", "ETH", "BTCUSDT", "ETHUSDT", "BTCBUSD", "ETHBUSD"}
FULL, LOW, W = 1.0, 0.25, 20  # 满仓 / 0.25 仓 / OI 回看 20 日


def _import_s659():
    import importlib.util
    spec = importlib.util.spec_from_file_location("s659", os.path.join(HERE, "s659_equity_state.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["s659"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------- 状态数据 ----------
def _page(off):
    q = ("deriv_metrics_daily?select=d,symbol,oi_value_close,taker_ratio_mean"
         "&source=eq.binance_vision_metrics&oi_value_close=not.is.null"
         f"&d=gte.{SINCE}&order=d.asc,symbol.asc")
    req = urllib.request.Request(URL + "/rest/v1/" + q, headers=dict(HDR, Range=f"{off}-{off + 999}"))
    try:
        return json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        if e.code == 416:
            return []
        raise


def load_deriv():
    """(symbol, d) → (oi_value_close, taker_ratio_mean);PostgREST 每页 1000 行,并发翻页,取回后本地缓存。"""
    path = os.path.join(CACHE, "deriv_metrics_daily.json")
    if os.path.exists(path):
        return {(r["symbol"], r["d"]): r for r in json.load(open(path))}
    rows, off = [], 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for chunk in ex.map(_page, range(0, 400_000, 1000)):
            if not chunk:
                break
            rows += chunk
            if len(chunk) < 1000:
                break
            off += 1000
    json.dump(rows, open(path, "w"))
    return {(r["symbol"], r["d"]): r for r in rows}


def flow_states(deriv):
    """S-660 的两条分量,逐日冻结:OI 流入 + 主动买盘广度。返回 (all, oi_only, br_only) 三套布尔。"""
    oi, tk = defaultdict(dict), defaultdict(dict)
    days = set()
    for (sym, d), r in deriv.items():
        if sym in EXCL:
            continue
        days.add(d)
        if r.get("oi_value_close") is not None:
            oi[d][sym] = float(r["oi_value_close"])
        if r.get("taker_ratio_mean") is not None:
            tk[d][sym] = float(r["taker_ratio_mean"])
    days = sorted(days)
    all_, oi_only, br_only = {}, {}, {}
    n_paired_lt30 = n_default_in = 0
    for i, d in enumerate(days):
        if i < 1:
            continue
        prev = days[i - 1]
        # OI 流入:t 与 t−20(按日历序第 i 与第 i−20 个有数据的日)都有值的配对集合
        j = i - W
        if j >= 0 and len(oi[d]) and len(oi[days[j]]):
            pair = [s for s in oi[d] if s in oi[days[j]]]
            if len(pair) < 30:                       # 配对集合 < 30 个币的日子 ⇒ 默认「在场」
                o_ok = None
                n_default_in += 1
            else:
                o_ok = sum(oi[d][s] for s in pair) > sum(oi[days[j]][s] for s in pair)
        else:
            o_ok, n_default_in = None, n_default_in + 1
        # 主动买盘广度:taker_ratio_mean 过去 5 天均值 > 1 的币的占比 > 0.5
        hist = [tk[x] for x in days[max(0, i - 4):i + 1]]
        cands = set(hist[-1])
        share = 0.0
        if cands:
            good = 0
            for s in cands:
                seq = [h[s] for h in hist if s in h]
                if seq and sum(seq) / len(seq) > 1.0:
                    good += 1
            share = good / len(cands)
        b_ok = share > 0.5
        if o_ok is None:
            all_[d], oi_only[d], br_only[d] = True, True, b_ok
        else:
            all_[d] = bool(o_ok and b_ok)
            oi_only[d] = bool(o_ok)
            br_only[d] = b_ok
        all_.setdefault(d, True)
        oi_only.setdefault(d, True)
    return all_, oi_only, br_only, {"days": len(days), "default_in_days": n_default_in}


# ---------- 判据(与 S-659 同一套) ----------
def judge(s659, tickets, states, label, do_null=True):
    # 状态日缺失(deriv 非空数据之前的日子,配对集合 0 个币 < 30)⇒ 默认「在场」,不改原规则
    sizes = [FULL if states.get(t["signal_d"], True) else LOW for t in tickets]
    n = len(tickets)
    avg = sum(sizes) / n
    tot_e, mdd_e, pnl_e = s659.book(tickets, sizes)
    tot_c, mdd_c, pnl_c = s659.book(tickets, [avg] * n)
    order = sorted(range(n), key=lambda k: (tickets[k].get("exit_d") or "9999", tickets[k]["symbol"]))
    cum = peak = mdd_x = 0.0
    for k in order:                                 # 组件单用时按出场日累计(原规则 1 B)
        cum += pnl_e[k] if sizes[k] == FULL else 0.0
        peak = max(peak, cum)
        mdd_x = min(mdd_x, cum - peak)
    halves = {}
    for lab, cond in (("lt2023", lambda t: t["signal_d"] < "2023-01-01"),
                      ("ge2023", lambda t: t["signal_d"] >= "2023-01-01")):
        idx = [i for i, t in enumerate(tickets) if cond(t)]
        halves[lab] = {"E": sum(pnl_e[i] for i in idx), "const": sum(pnl_c[i] for i in idx), "n": len(idx)}
    res = {"n": n, "in_share_tickets": sum(sizes) / n, "avg_size": avg,
           "E_total": tot_e, "E_mdd": mdd_e, "const_total": tot_c, "const_mdd": mdd_c,
           "onetime_mdd": mdd_x, "halves": halves,
           "base_total": sum(t["r"] for t in tickets)}
    if do_null and n:
        sh = sorted(s659.book(tickets, sizes[k:] + sizes[:k])[0] for k in range(1, n))  # 全部不同平移
        res["shift_q95"] = sh[int(0.95 * len(sh))]
        res["shift_median"] = sh[len(sh) // 2]
        res["shift_pct"] = sum(x < tot_e for x in sh) / len(sh)
    ok = (res["E_total"] > res["const_total"] and (not do_null or res["E_total"] > res.get("shift_q95", -1e9))
          and all(h["E"] > h["const"] for h in halves.values()) and res["E_mdd"] >= res["const_mdd"])
    res["verdict"] = "过" if ok else "不过"
    res["label"] = label
    return res


def main():
    s659 = _import_s659()
    s657, t159 = s659.s657, s659.s657.t159
    panel, gate = t159.load_bars(), t159.load_gate()
    early = os.path.join(os.environ["T156_DATA"], "_bars_early.jsonl")       # 必须同时读 t156 的早期日线
    assert os.path.exists(early), "t156 早期日线缺失 —— 停(T-164 的错)"
    raw = t159.run_long(panel, gate, "2020-03-01", "2026-10-19")
    pre = round(sum(t["r"] or 0 for t in raw), 3)
    tickets = s657.mtm(raw, panel)
    tickets.sort(key=lambda t: (t["signal_d"], t["symbol"]))
    assert len(tickets) == 770, len(tickets)
    assert abs(pre - 369.008) < 0.01, pre
    assert abs(sum(t["r"] for t in tickets) - 372.156) < 0.01, sum(t["r"] for t in tickets)

    deriv = load_deriv()
    all_, oi_only, br_only, meta = flow_states(deriv)
    # 预注册写「2020-10-01 起」,但 oi_value_close 非空的数据实际从 2021-12-02 才有 —— 记录,不改判据
    data_start = min(all_)
    assert max(all_) >= "2026-10-01", max(all_)
    ds = [d for d in all_ if d >= SINCE]
    in_days = sum(all_[d] for d in ds)

    tk = [t for t in tickets if t["signal_d"] >= SINCE]
    legs = [t for t in s657.mtm(s657.second_leg(panel, gate), panel) if t["signal_d"] >= SINCE]

    res = {"pre_register": "REFUTATION_LEDGER.md S-660 (2026-10-21 13:36 UTC)",
           "data": {"source": "deriv_metrics_daily/binance_vision_metrics", "since": SINCE,
                    "first_non_null_day": data_start,
                    "rows": len(deriv), "symbols": len({s for s, _ in deriv}),
                    "days": meta["days"], "default_in_days": meta["default_in_days"],
                    "in_days_share": in_days / len(ds)},
           "tickets": {"n_770": len(tickets), "total_r_pre_mtm": pre,
                       "total_r_post_mtm": sum(t["r"] for t in tickets),
                       "n_since": len(tk),
                       "n_before_data_start": sum(1 for t in tk if t["signal_d"] < data_start)},
           "combo": judge(s659, tk, all_, "OI 流入 ∧ 主动买盘广度"),
           "oi_only": judge(s659, tk, oi_only, "只 OI 流入", do_null=False),
           "breadth_only": judge(s659, tk, br_only, "只主动买盘广度", do_null=False),
           "leg": judge(s659, legs, all_, "S-658 第二段臂 × 同一状态", do_null=False) if legs else None}
    res["verdict"] = res["combo"]["verdict"]
    json.dump(res, open(os.path.join(HERE, "t167_results.json"), "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()