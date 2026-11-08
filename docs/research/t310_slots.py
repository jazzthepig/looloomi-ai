"""T-310(lane-c,2026-11-08)—— R-v2 名额 10 → 14 的回放护栏(gross_cap = 0.40 固定,cap_n ∈ {10, 14, ∞})。

**为什么**:S-788(Jazz 11-08「make it work」)。T-251 量过:40% 的名义上限**从未咬合** —— 因为「主机最多 10 张」
挡在前面(每票约合净值 2.9%,10 张满仓 ≈ 29% < 40%)。要让名义上限当家,名额得让到 14。改真钱参数之前先过
回放护栏。

**本脚本 = `t251_gross_cap_t197.py` 的复制品,只改两处**(S-788 写死):
  ① `CAPS = [0.40]`(只跑 40% 一档);
  ② 名额档位 `CAP_NS = [10, 14, 999]`(999 = ∞ 的代理,引擎里 `len(book) >= cap_n` 故取一个够大的整数)。
其余参数与口径**一字不改**:票源同一份(`t197_results.json → tickets.A`,956 张)、f = 0.5%、起始净值 $630、
L = 1、同一闸门、同一票源窗口、引擎 `t251_gross_cap.py` 的 `simulate` / `curve_stats` 一字不改。

**护栏(S-788 原文,判一次)**:cap_n = 14 的最大回撤比 cap_n = 10 差 ≤ 5pp **且** Calmar 不低于 cap_n = 10 的 90%
⇒ 采用 14;任一条不过 ⇒ 不采用,回报 Jazz。

**为什么重做**:T-251 原始题是 30 / 40 / 100 三档 gross_cap(只报不判);本卡换题,档位从 gross_cap 移到名额。

**引擎不重写**:逐日模拟直接 import lane-b 的 `t251_gross_cap.simulate` / `curve_stats` —— 就是 T-254 / T-277 /
T-278 / T-251 import 的同一份口径,一字不改(那份路径被这些脚本 import,不能覆盖)。本脚本的产物另起名字:
`t310_results.json`。

口径(卡 T-310,与 T-251 完全一致,只把档位从 gross_cap 移到名额):
  票源 `docs/research/t197_results.json` → `tickets.A`(956 张;signal 2020-08-15 → 2026-09-29,进场 2020-08-16 → 2026-09-30)
  参数 f = 0.5%(每票风险占净值)、起始净值 $630、复利、组合杠杆 L = 1、gross_cap = 0.40、名额 cap_n ∈ {10, 14, ∞}
  主机跳过规则(`src/exec_host/tickets.py` 的 `ticket_actions`):
      名义 = min(净值 × f ÷ 止损距离, 净值 × 50%);名义 < HL 最小 $10 ⇒ 不做;
      主机已满 cap_n 张 ⇒ 不做;同一个币已有仓 ⇒ 不做;名义合计 > 净值 × gross_cap ⇒ 这张票不做、**不找替补**。
  判一次(S-788 护栏),不搜参数:cap_n 是执行参数,不是可搜索的超参。

**窗口到不了「昨天」**(报告里写明,同 T-251):`r_tickets_paper` 前向 0 行;`r_tickets_scan`(plpgsql)在 lane 侧调不到
(MCP `execute_sql` 被拒、PostgREST 只读 key 无 RPC 执行权限);票源窗口本身到 2026-09-30 为止,不外延。

自检(跑之前先过,不过就不发):
  ① 票源重建:`t159.nav(tickets.A, f=1%, cap=10)` 与 T-197 已发布的 `nav.A` 逐项对表(end / mdd / taken / skipped)。
  ② 出场原因(stop / 破 SMA20 / 到期)由 K 线重算,与 t197 存的 `exit_d` / `exit_px` 逐张对表。

用法:`python3 docs/research/t310_slots.py`   → 写 `docs/research/t310_results.json`
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

import t251_gross_cap as T251          # noqa: E402  —— 引擎(不改一字)
import t159_bear_short as t159         # noqa: E402  —— 只用 nav/stats 做自检

T197 = os.path.join(HERE, "t197_results.json")
UM = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl"
STYLE = "/Volumes/CometCloudAI/cometcloud-local/research/t156/_style.json"
OUT_JSON = os.path.join(HERE, "t310_results.json")

F = 0.005                 # 每票风险占净值 0.5%(卡)
CAP_N = 10                # 主机最多 10 张(T-310 的基准档)
CAP_NS = [10, 14, 999]    # 名额档位:10(现状) / 14(S-788 目标) / 999(= ∞ 的代理)
CAP_N_KEY = {10: "10", 14: "14", 999: "inf"}   # 输出里的档位标签
EQ0 = 630.0               # 今天账户净值(美元)
CAPS = [0.40]             # S-788 写死:只跑 40% 一档
NAV_TO = "2026-09-30"     # 票源(与数据)的终点


# ── 取数 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def load_tickets():
    d = json.load(open(T197))
    return d["tickets"]["A"], d


def load_bars(need):
    """s681/_um_daily.jsonl → {symbol: [[d,o,h,l,c,qv], ...]}(与 T-197 的 load_um 同一处理:c ≤ 0 的行丢掉)。"""
    bars = {}
    with open(UM) as f:
        for line in f:
            x = json.loads(line)
            s = x["symbol"]
            if s not in need:
                continue
            rows = sorted({tuple(b) for b in x["bars"] if len(b) >= 6 and b[4] > 0})
            if rows:
                bars[s] = [list(r) for r in rows]
    return bars


def sma20(rows):
    c = [r[4] for r in rows]
    out = []
    for i in range(len(c)):
        seg = c[max(0, i - 19): i + 1]
        out.append(sum(seg) / len(seg))
    return out


def classify_exits(tickets, bars):
    """重算每张票的出场原因与出场价(T-159 的 run_long 逐字),与 t197 存的值逐张对表。

    run_long:进场后最多 120 根;先扫到 `low ≤ 止损` 或 `close < sma20` 的那天 k;
      止损出场  exit_px = open[k](若 k > 进场日 且 open[k] ≤ 止损)否则 止损价 —— 当天开盘平;
      破 SMA20 出场 exit_px = open[k+1] —— 也就是**次日开盘**平(不是当天收盘);
      都没扫到  120 根到期、当天收盘平(still=True 的那些)。
    """
    cache = {}
    out, bad = {}, []
    for t in tickets:
        sym = t["symbol"]
        rows = bars.get(sym)
        if not rows:
            continue
        if sym not in cache:
            cache[sym] = ({r[0]: i for i, r in enumerate(rows)}, sma20(rows))
        idx, sm = cache[sym]
        i, ei = idx.get(t["signal_d"]), idx.get(t["entry_d"])
        if i is None or ei is None:
            continue
        stop = t["stop_px"]
        n = len(rows)
        hi = min(i + 120, n - 1)
        k = None
        for j in range(ei, hi + 1):
            if rows[j][3] <= stop or rows[j][4] < sm[j]:
                k = j
                break
        if k is None:
            # t159:still = (i + 120 > n - 1)—— 数据先断(票还开着);否则是 120 根到期、当天收盘平
            if i + 120 > n - 1:
                reason, ed, ep = "still", None, None
            else:
                reason, ed, ep = "time", rows[hi][0], rows[hi][4]
        elif rows[k][3] <= stop:
            ep = rows[k][1] if (k > ei and rows[k][1] <= stop) else stop
            reason, ed = "stop", rows[k][0]
        elif k + 1 <= n - 1:
            reason, ed, ep = "sma20", rows[k + 1][0], rows[k + 1][1]
        else:
            reason, ed, ep = "still", None, None
        out[t["signal_d"] + "|" + sym] = (reason, ed, ep)
        if t.get("still"):
            if reason != "still":
                bad.append((sym, t["signal_d"], "still 但重算不是 still"))
        else:
            if ed != t["exit_d"] or abs((ep or 0) - (t["exit_px"] or 0)) > 1e-9 * max(1.0, abs(t["exit_px"] or 0)):
                bad.append((sym, t["signal_d"], f"重算 {reason} {ed} {ep} vs t197 {t['exit_d']} {t['exit_px']}"))
    return out, bad


def to_engine_tickets(tickets, exits):
    """换成 lane-b 引擎要的字段形状(字段名一致,值来自 t197)。"""
    out = []
    for t in tickets:
        key = t["signal_d"] + "|" + t["symbol"]
        reason, ed, ep = exits.get(key, (None, None, None))
        out.append(dict(
            tid=f"{t['symbol']}:{t['signal_d']}", symbol=t["symbol"], signal_d=t["signal_d"],
            entry_d=t["entry_d"], exit_d=t["exit_d"], entry_px=t["entry_px"], stop_px=t["stop_px"],
            exit_px=t["exit_px"], exit_reason=reason, r=t.get("r"), filled=True))
    return out


def load_gate():
    """majors 指数(市值加权)的 200 日线闸门 —— 与 T-159 load_gate / src/data/signals/multiplier.py 同一读法:
    ret → 水平 = cumprod(1+ret) → SMA200;水平 > SMA200 ⇒ 闸门开。"""
    rows = json.load(open(STYLE))
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("data") or []
    diag = {"raw_rows": len(rows)}
    if rows and isinstance(rows[0], dict) and "style" in rows[0]:
        styles = sorted({str(r.get("style")) for r in rows})
        diag["styles_in_file"] = styles
        rows = [r for r in rows if r.get("style") == "majors" and r.get("weighting") in (None, "cap")]
        diag["after_filter"] = len(rows)
    rows = [r for r in rows if r.get("ret") is not None and float(r["ret"]) > -0.95]
    rows.sort(key=lambda r: r["d"])
    lvl, cur = [], 1.0
    for r in rows:
        cur *= (1.0 + float(r["ret"]))
        lvl.append(cur)
    gate, lvl_by_d = {}, {}
    for i, r in enumerate(rows):
        seg = lvl[max(0, i - 199): i + 1]
        sma = sum(seg) / len(seg)
        n = len(seg)
        gate[r["d"]] = bool(n < 200 or lvl[i] > sma)
        lvl_by_d[r["d"]] = lvl[i]
    diag.update(rows=len(rows), d0=rows[0]["d"] if rows else None, d1=rows[-1]["d"] if rows else None)
    return gate, lvl_by_d, diag


def prev_day(d):
    return (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()


# ── 指标 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def margin_stats(blocked_gross):
    """被上限挡掉的票离上限有多近(正数 = 超出的美元)。刀刃上的票 = 净值路径一变就翻面。"""
    rows = []
    for t in blocked_gross:
        over = (t.get("gross_before", 0.0) + t.get("notional", 0.0)) - t.get("gross_limit", 0.0)
        rows.append(dict(symbol=t["symbol"], signal_d=t["signal_d"], over_usd=over,
                         over_pct_of_limit=over / t["gross_limit"] if t.get("gross_limit") else None,
                         r=t.get("r")))
    return rows


def rstats(rs):
    if not rs:
        return dict(n=0)
    s = sorted(rs)
    return dict(n=len(rs), mean=sum(rs) / len(rs), median=s[len(s) // 2], min=s[0], max=s[-1],
                sum=sum(rs), n_pos=sum(1 for x in rs if x > 0), n_neg=sum(1 for x in rs if x < 0))


def pct(vals, p):
    return T251.q(vals, p)


def run_cap(cap_frac, tickets, bars, gate, cap_n=CAP_N):
    global by_tid_global
    res = T251.simulate(tickets, bars, gate, cap_frac, equity0=EQ0, risk_frac=F, cap_n=cap_n)
    st = T251.curve_stats(res["curve"], EQ0)
    blocked_gross = res["blocked_gross"]
    blocked_cap = res["blocked_cap"]
    # 被名额挡掉的票(主机已满 cap_n 张):它们本来能进,只是没位置
    slot_rs = [((by_tid_global.get(t["tid"]) or {}).get("r")) for t in blocked_cap] if by_tid_global else []
    slot_rs = [x for x in slot_rs if x is not None]
    out = dict(
        cap_frac=cap_frac, cap_n=cap_n, stats=st,
        taken=len(res["taken"]),
        max_positions=max((c[2] for c in res["curve"]), default=0),
        sum_r_taken=sum((by_tid_global[t]["r"] or 0.0) for t in res["taken"]) if by_tid_global else None,
        days_above_cap=sum(1 for x in res["gross_ratio_hist"] if x > cap_frac + 1e-12),
        days_above_cap_max=max(res["gross_ratio_hist"]),
        blocked_episodes=sorted({t["entry_d"] for t in blocked_gross}),
        blocked=dict(
            gross=len(blocked_gross),
            gross_r_sum=sum((t.get("r") or 0.0) for t in blocked_gross),
            gross_r_stats=rstats([t["r"] for t in blocked_gross if t.get("r") is not None]),
            gross_usd_at_block=sum(t.get("notional", 0.0) for t in blocked_gross),
            gross_usd_if_taken=sum((t.get("r") or 0.0) * F * float(t.get("alloc") or 0.0) for t in blocked_gross),
            cap10=len(res["blocked_cap"]),
            slots_blocked=len(blocked_cap),
            slots_blocked_r_sum=sum(slot_rs), slots_blocked_r_stats=rstats(slot_rs),
            slots_sample=[dict(tid=t["tid"], symbol=t["symbol"], entry_d=t["entry_d"],
                               r=(by_tid_global.get(t["tid"]) or {}).get("r") if by_tid_global else None)
                          for t in blocked_cap[:25]],
            min_notional=len(res["blocked_min"]), same_coin=len(res["blocked_coin"]),
            margin=margin_stats(blocked_gross),
            margin_stats=dict(
                over_usd_median=pct([m["over_usd"] for m in margin_stats(blocked_gross)], 0.5),
                over_usd_min=min([m["over_usd"] for m in margin_stats(blocked_gross)]) if blocked_gross else None,
                n_knife_edge=sum(1 for m in margin_stats(blocked_gross)
                                 if (m["over_pct_of_limit"] or 1) < 0.05),
                n_under_2pct=sum(1 for m in margin_stats(blocked_gross)
                                 if (m["over_pct_of_limit"] or 1) < 0.02),
            ),
            gross_sample=[dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"], r=t.get("r"),
                               notional=t.get("notional"), gross_before=t.get("gross_before"),
                               gross_limit=t.get("gross_limit"), alloc=t.get("alloc")) for t in blocked_gross[:25]],
        ),
        gross=dict(
            abs_median=pct(res["gross_hist"], 0.5), abs_p95=pct(res["gross_hist"], 0.95), abs_max=max(res["gross_hist"]),
            ratio_median=pct(res["gross_ratio_hist"], 0.5), ratio_p95=pct(res["gross_ratio_hist"], 0.95),
            ratio_max=max(res["gross_ratio_hist"]),
            ratio_max_minus_cap=max(res["gross_ratio_hist"]) - cap_frac,
            note=("名义合计 = 持仓名义(当日开盘价盯市)÷ 当时的净值;判定只发生在**建仓那一刻**,"
                  "所以比值可以超过 cap(ratio_max − cap 就是超出的部分)。"),
        ),
    )
    return res, out


def main():
    raw, t197 = load_tickets()
    need = {t["symbol"] for t in raw}
    bars = load_bars(need)
    print(f"[load] tickets {len(raw)}  symbols {len(need)}  bars {len(bars)}")

    exits, bad = classify_exits(raw, bars)
    print(f"[exit-reason] 重算 {len(exits)} 张,与 t197 不一致 {len(bad)} 张")
    for b in bad[:10]:
        print("   ", b)

    tk = to_engine_tickets(raw, exits)
    global by_tid_global
    by_tid_global = {x["tid"]: x for x in tk}

    # 自检①:票源重建 —— t159.nav(f=1%, cap=10) 与 T-197 已发布的 nav.A 对表
    pub = (t197.get("nav") or {}).get("A") or {}
    parity = None
    try:
        curve = list(t159.nav([dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                                    exit_d=t["exit_d"], entry_px=t["entry_px"], stop_px=t["stop_px"],
                                    exit_px=t["exit_px"]) for t in raw],
                               bars, f=0.01, cap=10, d_to=NAV_TO))
        mine = t159.stats(curve)
        parity = dict(published=dict(end=pub.get("end"), annualised=pub.get("annualised"), mdd=pub.get("mdd"),
                                     taken=pub.get("taken"), skipped=pub.get("skipped"), closed=pub.get("closed"),
                                     peak_gross=pub.get("peak_gross")),
                       rebuilt=dict(end=mine.get("end"), annualised=mine.get("annualised"), mdd=mine.get("mdd"),
                                    taken=mine.get("taken"), skipped=mine.get("skipped"), closed=mine.get("closed"),
                                    peak_gross=mine.get("peak_gross")),
                       match=bool(abs((mine.get("end") or 0) - (pub.get("end") or 0)) < 1e-9
                                  and (mine.get("taken") == pub.get("taken"))
                                  and (mine.get("skipped") == pub.get("skipped"))))
        print("[parity]", json.dumps(parity["match"]), parity["rebuilt"])
    except Exception as e:  # noqa
        parity = dict(error=repr(e))
        print("[parity] FAIL", repr(e))

    gate, lvl_by_d, gdiag = load_gate()
    print("[gate]", gdiag)

    # regime 标签:进场决策那天能看到的闸门(前一日收盘读法,multiplier.py 的读法)
    def regime(d):
        return gate.get(d) if d else None

    def f4(v):
        return "n/a" if v is None else f"{v:.4f}"

    res_by_cn, summ = {}, {}
    for cn in CAP_NS:
        res_by_cn[cn] = {}
        summ[CAP_N_KEY[cn]] = {}
        for cap in CAPS:
            res, summ_s = run_cap(cap, tk, bars, gate, cap_n=cn)
            res_by_cn[cn][cap] = res
            summ[CAP_N_KEY[cn]][f"{cap:.2f}"] = summ_s
            s = summ_s["stats"]
            print(f"[cap_n {CAP_N_KEY[cn]} cap {cap:.2f}] total {s['total_return']:+.4%}  cagr {s['cagr']:+.4%}  "
                  f"mdd {s['max_dd']:+.4%}  "
                  f"calmar {s['calmar'] if s['calmar'] is None else round(s['calmar'], 3)}  "
                  f"taken {summ_s['taken']}  max_pos {summ_s['max_positions']}  "
                  f"blocked_gross {summ_s['blocked']['gross']} "
                  f"(R {summ_s['blocked']['gross_r_sum']:+.3f})  "
                  f"blocked_slots {summ_s['blocked']['slots_blocked']} "
                  f"(R {summ_s['blocked']['slots_blocked_r_sum']:+.3f})  "
                  f"gross/eq med/p95/max {f4(summ_s['gross']['ratio_median'])}/"
                  f"{f4(summ_s['gross']['ratio_p95'])}/{f4(summ_s['gross']['ratio_max'])}  "
                  f"worst_month {s['worst_month']} {s['worst_month_ret']:+.2%}")

    # ③ 边际:名额变化是**双向**的 —— 14 多做的 = 10 下被名额挡掉的;10 多做的 = 14 下被名额挤掉的。
    #    两个方向都要报(只看一个方向会得出错的结论)。
    cap0 = CAPS[0]
    t10, t14, tinf = res_by_cn[10][cap0]["taken"], res_by_cn[14][cap0]["taken"], res_by_cn[999][cap0]["taken"]
    by_tid = {x["tid"]: x for x in tk}

    def describe(tids):
        rows = []
        for tid in sorted(tids):
            t = by_tid[tid]
            reg_e = regime(prev_day(t["entry_d"]))
            reg_x = regime(t["exit_d"]) if t["exit_d"] else None
            held = []
            if t["exit_d"]:
                d = t["entry_d"]
                while d < t["exit_d"]:
                    held.append(bool(gate.get(d)))
                    d = (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
            rows.append(dict(tid=tid, symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                             exit_d=t["exit_d"], r=t.get("r"), regime_entry=reg_e, regime_exit=reg_x,
                             held_days_above=sum(1 for x in held if x), held_days=len(held)))
        return rows

    def split_by_regime(rows):
        out = {}
        for key in ("regime_entry", "regime_exit"):
            out[key] = {}
            for v in (True, False, None):
                rs = [r["r"] for r in rows if r[key] is v and r.get("r") is not None]
                out[key][str(v)] = rstats(rs)
        return out

    extra_rows = describe(t14 - t10)      # 14 多做的
    lost_rows = describe(t10 - t14)       # 10 多做的(14 下反而没进)
    by_reg = split_by_regime(extra_rows)
    by_reg_lost = split_by_regime(lost_rows)
    extra_rows_inf = describe(tinf - t14)  # ∞ 比 14 多做的(14 张名额也挡掉的那批)
    lost_rows_inf = describe(t14 - tinf)

    # ④ 护栏判定(S-788 写死,只判一次):cap_n=14 的最大回撤比 10 差 ≤ 5pp 且 Calmar ≥ 10 的 90%
    s10 = summ["10"][f"{cap0:.2f}"]["stats"]
    s14 = summ["14"][f"{cap0:.2f}"]["stats"]
    dd_gap_pp = (abs(s14["max_dd"]) - abs(s10["max_dd"])) * 100.0
    calmar_ratio = (s14["calmar"] / s10["calmar"]) if (s10["calmar"] not in (None, 0)
                                                       and s14["calmar"] is not None) else None
    pass_dd = dd_gap_pp <= 5.0
    pass_calmar = (calmar_ratio is not None) and (calmar_ratio >= 0.90)
    verdict = "采用 14" if (pass_dd and pass_calmar) else "不采用"
    guardrail = dict(
        rule=("S-788 原文:cap_n = 14 的最大回撤比 cap_n = 10 差 ≤ 5pp **且** Calmar 不低于 cap_n = 10 的 90% "
              "⇒ 采用 14;任一条不过 ⇒ 不采用,回报 Jazz。"),
        cap_n_10=dict(mdd=s10["max_dd"], calmar=s10["calmar"], total=s10["total_return"],
                       cagr=s10["cagr"], worst_month=s10["worst_month"], worst_month_ret=s10["worst_month_ret"]),
        cap_n_14=dict(mdd=s14["max_dd"], calmar=s14["calmar"], total=s14["total_return"],
                       cagr=s14["cagr"], worst_month=s14["worst_month"], worst_month_ret=s14["worst_month_ret"]),
        dd_gap_pp=dd_gap_pp, dd_gap_limit_pp=5.0, pass_dd=pass_dd,
        calmar_ratio=calmar_ratio, calmar_ratio_limit=0.90, pass_calmar=pass_calmar,
        verdict=verdict,
    )
    print(f"[guardrail] dd_gap {dd_gap_pp:+.2f}pp (≤5) {pass_dd}  calmar_ratio {calmar_ratio} (≥0.90) {pass_calmar}  "
          f"=> {verdict}")

    # ④ 真钱尺度:净值 $630 时每张票的名义
    notionals, under10, stop_fracs, n_pct = [], 0, [], []
    for t in raw:
        stop_frac = (t["entry_px"] - t["stop_px"]) / t["entry_px"] if t["entry_px"] else None
        if not stop_frac or stop_frac <= 0:
            continue
        n = min(EQ0 * F / stop_frac, EQ0 * 0.5)
        notionals.append(n)
        n_pct.append(n / EQ0)
        stop_fracs.append(stop_frac)
        if n < 10.0:
            under10 += 1
    med_slot_frac = pct(n_pct, 0.5)

    sig_days = sorted({t["signal_d"] for t in raw})
    gate_open_frac_sig = sum(1 for d in sig_days if gate.get(d)) / max(1, len(sig_days))
    ent_days = sorted({t["entry_d"] for t in raw})
    gate_open_frac_ent = sum(1 for d in ent_days if regime(prev_day(d))) / max(1, len(ent_days))

    out = dict(
        meta=dict(
            card="T-310", lane="lane-c", ran_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            ticket_source="docs/research/t197_results.json → tickets.A",
            ticket_source_run_utc=(t197.get("meta") or {}).get("run_utc"),
            n_tickets=len(raw), n_symbols=len(need),
            signal_window=[min(t["signal_d"] for t in raw), max(t["signal_d"] for t in raw)],
            entry_window=[min(t["entry_d"] for t in raw), max(t["entry_d"] for t in raw)],
            exit_window=[min(t["exit_d"] for t in raw if t["exit_d"]), max(t["exit_d"] for t in raw if t["exit_d"])],
            still_open=sum(1 for t in raw if t.get("still")),
            bars_source=UM, gate_source=STYLE,
            engine="docs/research/t251_gross_cap.py(simulate / curve_stats,未改一字)",
            params=dict(risk_frac=F, cap_ns=CAP_NS, cap_n_key=CAP_N_KEY, equity0=EQ0, gross_caps=CAPS,
                        leverage=1.0, min_notional_usd=10.0, single_ticket_max_frac=0.5,
                        cap_n_inf_proxy=999,
                        changed_vs_t251=("只改两处:① CAPS = [0.40];② 名额档位 cap_n ∈ {10, 14, ∞}(∞ 用 999 代理)。"
                                         "票源 / f / $630 / L / 引擎 一字不改。")),
            window_note=("票源本身到 2026-09-30 就没了: r_tickets_paper 前向 0 行、r_tickets_scan(plpgsql)在 lane 侧"
                         "调不到(MCP execute_sql 被拒、只读 key 无 RPC 执行权限);延到「昨天」只能重放 perp_bv_daily"
                         "(lane-b 那版的票源),混用会毁掉可比性,故不延。"),
        ),
        validation=dict(exit_reason_mismatch=len(bad), exit_reason_mismatch_sample=bad[:20], nav_parity=parity,
                        gate_diag=gdiag),
        regime=dict(gate_open_frac_signal_days=gate_open_frac_sig, gate_open_frac_entry_days=gate_open_frac_ent,
                    note=("票源本身只含闸门**开着**的信号(T-159 run_long 的 sig_long 要求 gate_open),所以按信号日分组"
                          "是退化的;下面按**进场决策日**(前一日收盘读法)与出场日分组。")),
        slots=summ,
        guardrail=guardrail,
        gross_cap_binding=dict(
            blocked_gross_by_cap_n={k: summ[k][f"{cap0:.2f}"]["blocked"]["gross"] for k in ("10", "14", "inf")},
            taken_by_cap_n={k: summ[k][f"{cap0:.2f}"]["taken"] for k in ("10", "14", "inf")},
            max_positions_by_cap_n={k: summ[k][f"{cap0:.2f}"]["max_positions"] for k in ("10", "14", "inf")},
            note=("被名义上限挡掉的票数 = 「40% 上限在工作」的证据。cap_n=10 时若为 0 ⇒ 40% 从未咬合"
                  "(被「主机最多 10 张」挡在前面);名额放大后这个数应该 > 0。"),
        ),
        marginal_slots=dict(
            n_extra_14_vs_10=len(extra_rows), n_lost_14_vs_10=len(lost_rows),
            n_extra_inf_vs_14=len(extra_rows_inf), n_lost_inf_vs_14=len(lost_rows_inf),
            extra_r_stats=rstats([r["r"] for r in extra_rows if r.get("r") is not None]),
            lost_r_stats=rstats([r["r"] for r in lost_rows if r.get("r") is not None]),
            extra_inf_r_stats=rstats([r["r"] for r in extra_rows_inf if r.get("r") is not None]),
            lost_inf_r_stats=rstats([r["r"] for r in lost_rows_inf if r.get("r") is not None]),
            extra_by_regime=by_reg, lost_by_regime=by_reg_lost,
            extra_tickets=extra_rows, lost_tickets=lost_rows,
            extra_inf_tickets=extra_rows_inf, lost_inf_tickets=lost_rows_inf,
            note=("14 的「多做的」= 10 下被名额挡掉的那批;10 的「多做的」= 14 下被名额挤掉的那批。"
                  "两个方向都要看,只看一个方向会得出错的结论。")),
        real_money=dict(
            equity0=EQ0, risk_frac=F,
            notional_at_equity0=dict(median=pct(notionals, 0.5), p10=pct(notionals, 0.1), p95=pct(notionals, 0.95),
                                     max=max(notionals), min=min(notionals)),
            stop_frac=dict(median=pct(stop_fracs, 0.5), p10=pct(stop_fracs, 0.1), p95=pct(stop_fracs, 0.95)),
            notional_pct_of_equity=dict(median=med_slot_frac, p10=pct(n_pct, 0.1), p95=pct(n_pct, 0.95),
                                        max=max(n_pct)),
            implied_slots_at_cap={f"{c:.2f}": (c / med_slot_frac if med_slot_frac else None) for c in CAPS},
            frac_below_hl_min_10=under10 / max(1, len(notionals)), n_below_hl_min_10=under10, n=len(notionals),
            in_sim_blocked_min={f"{k}|{c:.2f}": summ[k][f"{c:.2f}"]["blocked"]["min_notional"]
                                for k in ("10", "14", "inf") for c in CAPS},
            note=("名义 = 净值 × 0.5% ÷ 止损距离(单票 ≤ 净值 50%);典型止损距离中位 "
                  f"{pct(stop_fracs, 0.5):.2%} ⇒ 每张票约合净值的 {med_slot_frac:.2%},10 张满仓 ≈ "
                  f"{10 * med_slot_frac:.1%}、14 张满仓 ≈ {14 * med_slot_frac:.1%} —— "
                  "40% 名义上限对应名额 ≈ ceil(0.40 ÷ 每票占净值比),这就是 S-788 选 14 的算式。"),
        ),
    )
    json.dump(out, open(OUT_JSON, "w"), indent=1, default=str)
    print("[out]", OUT_JSON)


if __name__ == "__main__":
    main()
