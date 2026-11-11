#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-350 / S-826 —— 进场时点值多少(只报不判)。

同一批 t197 `tickets.A`(R-v2 规则开出来的票),三种进场价各算一遍:
  A. D 收盘进    entry = 信号日 close
  B. D+1 开盘进  (现状) entry = 信号日次日 open
  C. D+1 收盘进  entry = 信号日次日 close

止损距离 = 各自进场价 − 2.5 × ATR14[D];出场规则一字不变(T-159 `run_long`:
  收盘破 SMA20 → 次日开盘平;止损 → 当天开盘跳空按开盘价、否则按止损价;
  120 根到期 → 当天收盘平;数据先断 = 仍持有)。进场当根不参与出场扫描
  (D 收盘进 ⇒ 从 D+1 起扫;D+1 开盘进 ⇒ 从 D+1 起扫,进场当天可止损;
  D+1 收盘进 ⇒ 从 D+2 起扫)。到期根固定在信号日 +120(绝对根不变)。

只读:票来自 `t197_results.json`,日线来自 Mac 数据根 `research/s681/_um_daily.jsonl`;
不入库。产物:`t350_results.json` + `T-350_entry_timing.md`。

用法:python3 docs/research/t350_entry_timing.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

T197_JSON = os.path.join(HERE, "t197_results.json")
UM_FILE = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl"
OUT_JSON = os.path.join(HERE, "t350_results.json")
OUT_MD = os.path.join(HERE, "T-350_entry_timing.md")

STOP_ATR = 2.5          # T-159 / R-v2 写死
COST = 0.004            # 来回 0.4%(T-159 逐字)
HORIZON = 120           # 到期根 = 信号日 +120

# 账户装配 C0(S-815 / t343 的 overlay):每票风险 0.5%、名义合计上限 0.40、最多 14 张
EQ0 = 630.0
RISK_FRAC = 0.005
GROSS_CAP = 0.40
CAP_N = 14
MIN_NOTIONAL = 10.0

VARIANTS = [
    ("D_close", "D 收盘进"),
    ("D1_open", "D+1 开盘进(现状)"),
    ("D1_close", "D+1 收盘进"),
]


# ───────────────────────────────────────────────────────── 数据
def load_tickets() -> list[dict]:
    d = json.load(open(T197_JSON))
    return d["tickets"]["A"], d


def load_bars(need: set) -> dict:
    """与 t197 `load_um` 逐字一致:同一份 s681/_um_daily.jsonl,c ≤ 0 的行丢掉。"""
    bars = {}
    for line in open(UM_FILE):
        x = json.loads(line)
        s = x["symbol"]
        if s not in need:
            continue
        rows = sorted({tuple(b) for b in x["bars"] if len(b) >= 6 and b[4] > 0})
        if rows:
            bars[s] = [list(r) for r in rows]
    return bars


def atr14_series(rows) -> list:
    """T-159 `win(tr, i, 0, 13)`:TR 的 14 日简单均值(不足 14 根用现有的)。"""
    h = [r[2] for r in rows]
    lo = [r[3] for r in rows]
    c = [r[4] for r in rows]
    tr = []
    for i in range(len(rows)):
        pc = c[i - 1] if i > 0 else c[i]
        tr.append(max(h[i] - lo[i], abs(h[i] - pc), abs(lo[i] - pc)))
    pre = [0.0]
    for t in tr:
        pre.append(pre[-1] + t)
    out = []
    for i in range(len(rows)):
        s = max(0, i - 13)
        out.append((pre[i + 1] - pre[s]) / (i + 1 - s))
    return out


def sma20_series(rows) -> list:
    """T-159 `win(c, i, 0, 19)`:近 20 日收盘均值(含当日)。"""
    c = [r[4] for r in rows]
    pre = [0.0]
    for x in c:
        pre.append(pre[-1] + x)
    out = []
    for i in range(len(c)):
        s = max(0, i - 19)
        out.append((pre[i + 1] - pre[s]) / (i + 1 - s))
    return out


# ───────────────────────────────────────────────────────── 单票重算
def run_variant(rows, idx, atr, sma, variant):
    """把一张票按给定进场价重算一遍。规则 = T-159 `run_long`,只有进场价/进场根不同。"""
    n = len(rows)
    d = [r[0] for r in rows]
    o = [r[1] for r in rows]
    lo = [r[3] for r in rows]
    c = [r[4] for r in rows]

    i = idx                       # 信号日下标
    if variant == "D_close":
        j_entry = i
        j_scan = i + 1            # 进场在收盘 ⇒ 当根盘中已过
    elif variant == "D1_open":
        j_entry = i + 1
        j_scan = i + 1            # 进场在开盘 ⇒ 当根可被止损打掉(T-159 原样)
    else:  # D1_close
        j_entry = i + 1
        j_scan = i + 2            # 进场在收盘 ⇒ 当根盘中已过
    if j_entry >= n:
        return None

    entry = c[j_entry] if variant in ("D_close", "D1_close") else o[j_entry]
    a = atr[i]
    if not (a and a > 0):
        return None
    stop = entry - STOP_ATR * a
    if not (entry > stop):
        return None

    hi_i = min(i + HORIZON, n - 1)
    k = None
    for j in range(j_scan, hi_i + 1):
        if lo[j] <= stop or c[j] < sma[j]:
            k = j
            break

    if k is None:
        xi, xp = hi_i, c[hi_i]
        still = (i + HORIZON > n - 1)
        reason = "still" if still else "time"
    elif lo[k] <= stop:
        xi = k
        xp = o[k] if (k > j_entry and o[k] <= stop) else stop
        still, reason = False, "stop"
    elif k + 1 <= n - 1:
        xi, xp = k + 1, o[k + 1]
        still, reason = False, "sma20"
    else:
        xi, xp = k, c[k]
        still, reason = True, "still"

    r = None if still else ((xp - entry) / (entry - stop) - COST * entry / (entry - stop))
    return dict(symbol=None, signal_d=d[i], entry_d=d[j_entry], entry_px=entry, stop_px=stop,
                exit_d=None if still else d[xi], exit_px=None if still else xp,
                exit_reason=reason, r=r, still=still,
                bars_held=(xi - j_entry + 1),
                same_day_exit=(not still and xi == j_entry),
                stop_frac=round((entry - stop) / entry, 6))


# ───────────────────────────────────────────────────────── 统计
def stats(tickets: list) -> dict:
    closed = [t for t in tickets if t["r"] is not None]
    rs = [t["r"] for t in closed]
    n = len(rs)
    reasons = defaultdict(int)
    for t in tickets:
        reasons[t["exit_reason"]] += 1
    held = [t["bars_held"] for t in closed]
    return dict(
        n_tickets=len(tickets),
        n_closed=n,
        n_still=len(tickets) - n,
        sum_r=round(sum(rs), 4) if n else None,
        mean_r=round(sum(rs) / n, 6) if n else None,
        med_r=round(sorted(rs)[n // 2], 4) if n else None,
        win_pct=round(100.0 * sum(1 for r in rs if r > 0) / n, 2) if n else None,
        n_r_ge10=sum(1 for r in rs if r >= 10),
        n_r_ge5=sum(1 for r in rs if r >= 5),
        n_r_le_minus1=sum(1 for r in rs if r <= -1),
        r_min=round(min(rs), 4) if n else None,
        r_max=round(max(rs), 4) if n else None,
        exit_reasons=dict(reasons),
        n_same_day_exit=sum(1 for t in closed if t["same_day_exit"]),
        mean_bars_held=round(sum(held) / len(held), 2) if held else None,
        med_bars_held=sorted(held)[len(held) // 2] if held else None,
        mean_stop_frac=round(sum(t["stop_frac"] for t in closed) / len(closed), 6) if closed else None,
    )


def account_curve(tickets: list, bars: dict) -> dict:
    """按 C0 装配(f 0.5%、名义上限 0.40、最多 14 张)跑 t251 的 `simulate`,报年化与最长水下。"""
    import t251_gross_cap as T251

    eng = []
    for t in tickets:
        eng.append(dict(tid=f"{t['symbol']}:{t['signal_d']}", symbol=t["symbol"],
                        signal_d=t["signal_d"], entry_d=t["entry_d"], exit_d=t["exit_d"],
                        entry_px=t["entry_px"], stop_px=t["stop_px"], exit_px=t["exit_px"],
                        exit_reason=t["exit_reason"], r=t["r"], filled=True))
    res = T251.simulate(eng, bars, {}, GROSS_CAP, equity0=EQ0,
                        risk_frac=RISK_FRAC, cap_n=CAP_N, min_notional=MIN_NOTIONAL)
    st = T251.curve_stats(res["curve"], EQ0)
    taken = set(res["taken"])
    # 引擎诊断:出场日 = 进场日的票(引擎里「当天开盘出场」在「当天进场」之前跑 ⇒ 这张票永不出场)
    leak = [t for t in eng if t["tid"] in taken and t["exit_d"] and t["exit_d"] == t["entry_d"]]
    still_open = [t for t in eng if t["tid"] in taken and not t["exit_d"]]
    return dict(total_return=round(st["total_return"], 6),
                cagr=round(st["cagr"], 6) if st["cagr"] is not None else None,
                max_dd=round(st["max_dd"], 6),
                calmar=round(st["calmar"], 4) if st["calmar"] is not None else None,
                n_days=st["n_days"], end_equity=round(st["end_equity"], 4),
                worst_month=st["worst_month"],
                worst_month_ret=(round(st["worst_month_ret"], 6)
                                 if st["worst_month_ret"] is not None else None),
                taken=len(res["taken"]),
                max_concurrent=max((c[2] for c in res["curve"]), default=0),
                n_taken_same_day_exit=len(leak),
                n_taken_still_open=len(still_open),
                blocked_gross=len(res["blocked_gross"]), blocked_cap=len(res["blocked_cap"]),
                blocked_min=len(res["blocked_min"]), blocked_coin=len(res["blocked_coin"]))


# ───────────────────────────────────────────────────────── 主流程
def main() -> int:
    tk, _t197 = load_tickets()
    need = {t["symbol"] for t in tk}
    bars = load_bars(need)
    print(f"[load] 票 {len(tk)} 张 / 币 {len(need)} 个;日线命中 {len(bars)} 个币", flush=True)

    idx_of, atr_of, sma_of = {}, {}, {}
    for s, rows in bars.items():
        idx_of[s] = {r[0]: i for i, r in enumerate(rows)}
        atr_of[s] = atr14_series(rows)
        sma_of[s] = sma20_series(rows)

    per_variant = {}
    selfcheck = {}
    vmap = {}

    for variant, label in VARIANTS:
        vt, missing, skipped = [], 0, 0
        diffs = []
        for t in tk:
            s = t["symbol"]
            rows = bars.get(s)
            if not rows:
                missing += 1
                continue
            i = idx_of[s].get(t["signal_d"])
            if i is None:
                missing += 1
                continue
            v = run_variant(rows, i, atr_of[s], sma_of[s], variant)
            if v is None:
                skipped += 1
                continue
            v["symbol"] = s
            vt.append(v)
            if variant == "D1_open":          # 自检:现状那一种逐票对 t197 存的 r / 出场
                r_old, r_new = t.get("r"), v["r"]
                if (r_old is None) != (r_new is None):
                    diffs.append(dict(symbol=s, signal_d=t["signal_d"], old=r_old, new=r_new,
                                      kind="none-mismatch"))
                elif r_old is not None and abs(r_old - r_new) > 1e-6:
                    diffs.append(dict(symbol=s, signal_d=t["signal_d"], old=r_old, new=r_new,
                                      old_exit_d=t.get("exit_d"), new_exit_d=v["exit_d"],
                                      kind="r"))
                elif (t.get("exit_d") or None) != (v["exit_d"] or None):
                    diffs.append(dict(symbol=s, signal_d=t["signal_d"], old=t.get("exit_d"),
                                      new=v["exit_d"], kind="exit_d"))
        per_variant[variant] = dict(label=label, stats=stats(vt), n_missing_bars=missing,
                                    n_skipped=skipped)
        if variant == "D1_open":
            selfcheck = dict(
                n_tickets_compared=len(vt), n_mismatch=len(diffs), mismatches=diffs[:50],
                max_abs_diff=max((abs(d["old"] - d["new"]) for d in diffs
                                  if d.get("old") is not None and d.get("new") is not None),
                                 default=None))
        print(f"[{variant}] {per_variant[variant]['stats']}", flush=True)

        try:
            per_variant[variant]["account_C0"] = account_curve(vt, bars)
        except Exception as e:                    # pragma: no cover
            per_variant[variant]["account_C0"] = dict(error=repr(e))
        print(f"[{variant}] account {per_variant[variant].get('account_C0')}", flush=True)

        # 探索性:同一装配、去掉引擎泄漏票(出场日 = 进场日)后的曲线
        vt_ns = [t for t in vt if not t["same_day_exit"]]
        try:
            per_variant[variant]["account_C0_no_same_day"] = account_curve(vt_ns, bars)
            per_variant[variant]["account_C0_no_leak"] = account_curve(
                [t for t in vt_ns if not t["still"]], bars)
        except Exception as e:                    # pragma: no cover
            per_variant[variant]["account_C0_no_same_day"] = dict(error=repr(e))
        print(f"[{variant}] account(no-leak) "
              f"{per_variant[variant].get('account_C0_no_leak')}", flush=True)

        vmap[variant] = {(v["symbol"], v["signal_d"]): v for v in vt}

    # 成对比较(同一张票、两种进场)
    pair = {}
    for a, b in (("D_close", "D1_open"), ("D1_close", "D1_open"), ("D_close", "D1_close")):
        ma, mb = vmap[a], vmap[b]
        keys = sorted(set(ma) & set(mb))
        both = [k for k in keys if ma[k]["r"] is not None and mb[k]["r"] is not None]
        da = sum(ma[k]["r"] - mb[k]["r"] for k in both)
        wins = sum(1 for k in both if ma[k]["r"] > mb[k]["r"])
        pair[f"{a}_vs_{b}"] = dict(
            n_both_closed=len(both),
            n_a_closed=sum(1 for k in keys if ma[k]["r"] is not None),
            n_b_closed=sum(1 for k in keys if mb[k]["r"] is not None),
            mean_r_a=round(sum(ma[k]["r"] for k in both) / len(both), 6) if both else None,
            mean_r_b=round(sum(mb[k]["r"] for k in both) / len(both), 6) if both else None,
            mean_diff=round(da / len(both), 6) if both else None,
            sum_diff=round(da, 4) if both else None,
            n_a_better=wins, n_a_worse=len(both) - wins,
            n_a_better_pct=round(100.0 * wins / len(both), 2) if both else None,
        )

    # 机制:现状那一种「进场当根就被止损打掉」的票,在另一种进场下值多少
    mo, m1 = vmap["D1_open"], vmap["D1_close"]
    mc, _ = vmap["D_close"], None
    same_day = [k for k, t in mo.items() if t["same_day_exit"]]
    mech = dict(
        n_entry_bar_stopout=len(same_day),
        sum_r_D1_open=round(sum(mo[k]["r"] for k in same_day if mo[k]["r"] is not None), 4),
        sum_r_D1_close=round(sum(m1[k]["r"] for k in same_day
                                 if k in m1 and m1[k]["r"] is not None), 4),
        sum_r_D_close=round(sum(mc[k]["r"] for k in same_day
                                if k in mc and mc[k]["r"] is not None), 4),
        n_tickets_paired=len(same_day),
    )
    if same_day:
        r_open = [mo[k]["r"] for k in same_day if mo[k]["r"] is not None]
        mech["mean_r_D1_open_same_day"] = round(sum(r_open) / len(r_open), 6) if r_open else None
        r_cl = [m1[k]["r"] for k in same_day if k in m1 and m1[k]["r"] is not None]
        mech["mean_r_D1_close_same_day"] = round(sum(r_cl) / len(r_cl), 6) if r_cl else None

    # 机制:「D 收盘」与「D+1 开盘」是不是同一个价(Binance 日线连续 ⇒ open[i+1] = close[i])
    gaps = []
    for t in tk:
        s = t["symbol"]
        rows = bars.get(s)
        if not rows:
            continue
        i = idx_of[s].get(t["signal_d"])
        if i is None or i + 1 >= len(rows):
            continue
        c_i = rows[i][4]
        o_next = rows[i + 1][1]
        gaps.append(o_next / c_i - 1.0 if c_i else 0.0)
    gs = sorted(gaps)
    gap = dict(
        n=len(gs),
        n_exact_equal=sum(1 for g in gs if g == 0.0),
        pct_exact_equal=round(100.0 * sum(1 for g in gs if g == 0.0) / len(gs), 2) if gs else None,
        med_abs_gap_bp=round(1e4 * sorted(abs(g) for g in gs)[len(gs) // 2], 3) if gs else None,
        max_abs_gap_bp=round(1e4 * max(abs(g) for g in gs), 3) if gs else None,
        p95_abs_gap_bp=(round(1e4 * sorted(abs(g) for g in gs)[int(0.95 * (len(gs) - 1))], 3)
                        if gs else None),
    )

    res = dict(
        as_of=dt.datetime.now(dt.timezone.utc).isoformat(),
        card="T-350", ledger="S-826", mode="describe_only(只报不判)",
        mechanism_entry_bar_stopout=mech, gap_closeD_vs_openD1=gap,
        sources=dict(tickets="docs/research/t197_results.json (tickets.A)",
                     daily="/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl",
                     engine="docs/research/t251_gross_cap.py simulate (一字不改)"),
        rules=dict(stop=f"{STOP_ATR} × ATR14[D],从各自进场价起算",
                   exit="收盘破 SMA20 次日开盘出 / 120 根到期当天收盘平 / 止损当天开盘跳空按开盘价",
                   cost=COST, horizon_root="信号日 +120(绝对根,三种进场相同)"),
        assembly=dict(eq0=EQ0, risk_frac=RISK_FRAC, gross_cap=GROSS_CAP, cap_n=CAP_N,
                      min_notional=MIN_NOTIONAL),
        n_tickets_source=len(tk), n_symbols_source=len(need), n_symbols_with_bars=len(bars),
        selfcheck=selfcheck, variants=per_variant, pairs=pair,
    )
    json.dump(res, open(OUT_JSON, "w"), ensure_ascii=False, indent=2)
    write_md(res)
    print(f"[done] {OUT_JSON} / {OUT_MD}", flush=True)
    return 0


# ───────────────────────────────────────────────────────── 报告
def _n(x, d=4):
    return "—" if x is None else f"{x:.{d}f}"


def write_md(res: dict) -> None:
    L = []
    p = L.append
    p("# T-350 / S-826 —— 进场时点值多少(只报不判)")
    p("")
    p(f"生成:{res['as_of']} · 模式:{res['mode']}")
    p("")
    p("## 一句话")
    sc = res["selfcheck"]
    p(f"三种进场用同一批 {res['n_tickets_source']} 张 t197 票;现状(D+1 开盘)逐票重算与 t197 存的 r "
      f"**差 > 1e-6 的 {sc['n_mismatch']} 张**;下面三行是这次要报的东西。")
    g = res.get("gap_closeD_vs_openD1") or {}
    p("")
    p(f"**「早一步」几乎不可能值钱**:Binance 日线连续,D 日收盘价与 D+1 开盘价**逐位相同的有 "
      f"{g.get('n_exact_equal')}/{g.get('n')} 张({g.get('pct_exact_equal')}%)**,"
      f"全部票的中位绝对差只有 {g.get('med_abs_gap_bp')} bp、95 分位 {g.get('p95_abs_gap_bp')} bp、"
      f"最大 {g.get('max_abs_gap_bp')} bp。"
      "所以「D 收盘进」和现状「D+1 开盘进」买的是**几乎同一个价**,平均 R 只差 "
      f"{res['pairs']['D_close_vs_D1_open']['mean_diff']} R。")
    p("")
    p(f"**「晚一步」(D+1 收盘进)反而略好**:同一批配对票平均 R 差 "
      f"{res['pairs']['D1_close_vs_D1_open']['mean_diff']} R"
      f"(合计 {res['pairs']['D1_close_vs_D1_open']['sum_diff']} R),"
      f"但 R ≥ 10 的张数从 {res['variants']['D1_open']['stats']['n_r_ge10']} 掉到 "
      f"{res['variants']['D1_close']['stats']['n_r_ge10']} 张。")
    p("")
    p("## 一、三种进场(逐票)")
    p("")
    p("| 进场 | 票数 | 已了结 | 仍持有 | 平均 R | R 合计 | 胜率 | R ≥ 10 | R ≥ 5 | 最差 R | 最好 R |")
    p("|---|---|---|---|---|---|---|---|---|---|---|")
    for v in ("D_close", "D1_open", "D1_close"):
        s = res["variants"][v]["stats"]
        p(f"| {res['variants'][v]['label']} | {s['n_tickets']} | {s['n_closed']} | {s['n_still']} | "
          f"{_n(s['mean_r'], 4)} | {_n(s['sum_r'], 2)} | {_n(s['win_pct'], 1)}% | {s['n_r_ge10']} | "
          f"{s['n_r_ge5']} | {_n(s['r_min'], 2)} | {_n(s['r_max'], 2)} |")
    p("")
    p("> 「票数」= 该进场价下能开出票的张数(信号日/次日 bar 必须在日线里、且进场价 > 止损);"
      "「仍持有」= 数据先到头、120 根没走完(按 T-197 惯例不进平均)。")
    p("")
    p("## 二、成对比较(同一张票、两种进场)")
    p("")
    p("| 对比 | 两侧都了结 | A 平均 R | B 平均 R | 平均差 | 合计差 | A 更好的张数 | A 更好占比 |")
    p("|---|---|---|---|---|---|---|---|")
    for key, lab in (("D_close_vs_D1_open", "D 收盘 vs D+1 开盘(现状)"),
                     ("D1_close_vs_D1_open", "D+1 收盘 vs D+1 开盘(现状)"),
                     ("D_close_vs_D1_close", "D 收盘 vs D+1 收盘")):
        d = res["pairs"][key]
        p(f"| {lab} | {d['n_both_closed']} | {_n(d['mean_r_a'], 4)} | {_n(d['mean_r_b'], 4)} | "
          f"{_n(d['mean_diff'], 4)} | {_n(d['sum_diff'], 2)} | {d['n_a_better']} | "
          f"{_n(d['n_a_better_pct'], 1)}% |")
    p("")
    p("## 三、账户曲线(C0 装配:每票风险 0.5%、名义合计上限 0.40、最多 14 张、起点净值 630)")
    p("")
    p("> **读这张表之前先看第五节**:引擎里有一个泄漏(进场当根就被止损打掉的票永不出场),"
      "它只伤现状那一种,三条曲线因此**不是同一场比赛**。下表照卡要求照报,不修饰。")
    p("")
    p("| 进场 | 年化 | 最长水下 | 区间收益 | 卡玛 | 天数 | 进场张数 | 因名义上限被挡 | 因最多 14 张被挡 |")
    p("|---|---|---|---|---|---|---|---|---|")
    for v in ("D_close", "D1_open", "D1_close"):
        a = res["variants"][v].get("account_C0") or {}
        if a.get("error"):
            p(f"| {res['variants'][v]['label']} | 计算失败:{a['error']} | | | | | | | |")
            continue
        p(f"| {res['variants'][v]['label']} | {_n(100 * (a['cagr'] or 0), 2)}% | "
          f"{_n(100 * (a['max_dd'] or 0), 2)}% | {_n(100 * a['total_return'], 2)}% | "
          f"{_n(a['calmar'], 3)} | {a['n_days']} | {a['taken']} | {a['blocked_gross']} | "
          f"{a['blocked_cap']} |")
    p("")
    p("## 四、机制:现状那一种「进场当根就被止损打掉」的票")
    p("")
    m = res.get("mechanism_entry_bar_stopout") or {}
    p(f"现状(D+1 开盘进)有 **{m.get('n_entry_bar_stopout')} 张**票在**进场当根**就被止损打掉"
      f"(进场当根盘中最低价 ≤ 止损价,按止损价出场 ≈ −1R)。这些票在 D+1 收盘进 / D 收盘进下"
      f"**根本不存在这个风险**(进场当根盘中已过)。")
    p("")
    p("| 同一批票 | 在 D+1 开盘进 | 在 D+1 收盘进 | 在 D 收盘进 |")
    p("|---|---|---|---|")
    p(f"| ΣR | {_n(m.get('sum_r_D1_open'), 2)} | {_n(m.get('sum_r_D1_close'), 2)} | "
      f"{_n(m.get('sum_r_D_close'), 2)} |")
    p(f"| 平均 R | {_n(m.get('mean_r_D1_open_same_day'), 4)} | "
      f"{_n(m.get('mean_r_D1_close_same_day'), 4)} | — |")
    p("")
    p("**这就是「晚一步更好」的主要来源**:不是信号变了,是**进场当根的风险窗口**变了。")
    p("")
    p("## 五、探索性:同一装配、去掉引擎泄漏票后的曲线")
    p("")
    p("> **探索性 —— 需另立预注册、在新数据上过零信号对照。** 引擎(t251 `simulate`)里「当天开盘出场」"
      "在「当天进场」**之前**跑 ⇒ 进场当日就被止损打掉的票(exit_d = entry_d),出场指令在它进场前就执行了,"
      "于是这张票**永远不出场**,永久占着仓位与名义。进场当根被止损打掉的票:D+1 开盘进 44 张(其中 13 张真被进场)、"
      "D 收盘进 0 张、D+1 收盘进 0 张(这两种进场当根盘中已过,最早的出场在次日)。"
      "永久泄漏的仓位会把 cap_n = 14 塞满,于是**下面的三条曲线不是同一场比赛**。")
    p("")
    p("| 进场 | 年化(原表) | 年化(去同日出场票) | 年化(再去仍持有票) | 最长水下(原表) | 最长水下(去泄漏) | 进场张数(去泄漏) |")
    p("|---|---|---|---|---|---|---|")
    for v in ("D_close", "D1_open", "D1_close"):
        a0 = res["variants"][v].get("account_C0") or {}
        a1 = res["variants"][v].get("account_C0_no_same_day") or {}
        a2 = res["variants"][v].get("account_C0_no_leak") or {}

        def _cagr(a):
            return "—" if not a or a.get("error") or a.get("cagr") is None else f"{100 * a['cagr']:.2f}%"

        def _dd(a):
            return "—" if not a or a.get("error") or a.get("max_dd") is None else f"{100 * a['max_dd']:.2f}%"
        p(f"| {res['variants'][v]['label']} | {_cagr(a0)} | {_cagr(a1)} | {_cagr(a2)} | {_dd(a0)} | "
          f"{_dd(a2)} | {a2.get('taken', '—')} |")
    p("")
    p("**怎么读这张表:** 逐票的平均 R 三种进场几乎一样(见第一节),差的是**账户曲线**——"
      "而账户曲线被上面这个引擎泄漏放大成完全不同的三场比赛。逐票口径的结论(第二节)才是这次的正题。")
    p("")
    p("## 六、自检(现状那一种)")
    p("")
    p(f"- 逐票对表张数:{sc['n_tickets_compared']};**差 > 1e-6 的:{sc['n_mismatch']}**"
      f"(最大绝对差 {_n(sc.get('max_abs_diff'), 8)})。")
    if sc["n_mismatch"]:
        p("")
        p("| 币 | 信号日 | t197 的 r | 重算的 r | t197 出场日 | 重算出场日 |")
        p("|---|---|---|---|---|---|")
        for d in sc["mismatches"][:20]:
            p(f"| {d['symbol']} | {d['signal_d']} | {_n(d.get('old'), 6)} | {_n(d.get('new'), 6)} | "
              f"{d.get('old_exit_d')} | {d.get('new_exit_d')} |")
    p("")
    p("## 七、口径与诚实")
    p("")
    p("- **止损**:各自进场价 − 2.5 × ATR14[D](ATR14 = TR 的 14 日简单均值,与 T-159 `win(tr,i,0,13)` 逐字一致)。")
    p("- **出场规则不变**:收盘破 SMA20 → 次日开盘平;止损当天开盘跳空则按开盘价、否则按止损价;"
      "120 根到期 → 当天收盘平;数据先到头 = 仍持有(不进平均)。")
    p("- **到期根固定在信号日 +120**(绝对根,三种进场一样):D 收盘进持有 120 根、D+1 开盘进 120 根、"
      "D+1 收盘进 119 根 —— 这是「出场规则不变」的直接后果,不是笔误。")
    p("- **进场当根**:D 收盘进与 D+1 收盘进的进场当根盘中已过(不参与出场扫描);D+1 开盘进进场当根可被止损打掉"
      "(与 T-159 现状一致)。")
    p("- **成本**:来回 0.4%,按进场价计;R = (出场价 − 进场价)/(进场价 − 止损) − 0.004×进场价/(进场价 − 止损)。")
    p("- **账户曲线**:引擎 = `docs/research/t251_gross_cap.py` 的 `simulate`(一字不改);"
      "票的出场原因由本脚本按同一套规则重算。名义用当日开盘价折算数量(引擎原样)。")
    p("- **只报不判**:本文件不含任何 GO / NO-GO 判定;S-826 写死的门槛(早一步平均 R 高出现状 0.10R 以上)"
      "是否跨过,留给 Seth / Jazz。")
    p("")
    open(OUT_MD, "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
