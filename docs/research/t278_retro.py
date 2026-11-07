"""T-278 —— S-757 硬规则回看(只报不判):「Binance 整币下架即剔除」在 R-v2 回放账本上的历史代价。

票源:与 lane-b T-251 / T-254 / T-277 **同一个生成器**(`T251.scan` + `T251.simulate`,40% 档),
      只取**真正成交且有 R** 的票(台账:「有 R 的成交票」)。
名单:生产口径 `delisting_watch` 表 —— 每个代号只留**第一次**整币下架公告;
      1000 前缀口径同 `src/data/signals/delisting_watch.is_excluded`。

两类(主口径 = 生产语义):
  ① 开票时已在名单上:第一次公告日 A ∈ [计划日 − 365, 计划日] ⇒ 规则不开这张票。
     计划在**信号日**生成、下一开盘成交 ⇒ 判据落在信号日(生产:`apply_to_plan` 用当时的 excl)。
     台账写的「开票日 d、窗口 [d−365, d)」是敏感性 1(d = 进场日、半开窗)。
  ② 持有期间被宣布:进场日 ≤ A < 出场日 ⇒ 规则在公告后**第一个开盘**平掉(用该开盘价重算 R)。

账本:总 R(有 R 的成交票之和)与 Calmar,「有规则 / 没有规则」两版;全窗口 + 台账窗口两版。

用法:python3 docs/research/t278_retro.py     (写 docs/research/t278_results.json)
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import t251_gross_cap as T251  # noqa: E402  —— T-251 的扫描器/模拟器,口径一字不改
from src.data.signals.delisting_watch import (  # noqa: E402  —— 生产口径的解析器 + 1000 前缀
    extract_symbols, is_excluded, screen_title,
)

OUT = HERE / "t278_results.json"
CAP_FRAC = 0.40                      # 40% 档(与 T-251 / T-254 / T-277 同)
LOOKBACK = 365                       # 名单窗口:EXCLUDE_DAYS
LEDGER_FROM = dt.date(2022, 2, 17)   # 名单第一条公告;台账窗口 2022-02 → 2026-10
LEDGER_TO = dt.date(2026, 10, 14)    # 名单最后一条公告
LIST_START = dt.date(2022, 2, 17)    # 名单最早一条 ⇒ 之前的 365 天回看不完整


def _d(x):
    return dt.date.fromisoformat(str(x)[:10])


# ---------------------------------------------------------------- 名单
def load_delist():
    """生产名单(delisting_watch 表)+ 全量公告(events,同一套解析)。"""
    rows, rng = T251._rest("delisting_watch?select=symbol,announced_at,d0,title&order=announced_at.asc")
    table = {str(r["symbol"]).upper(): r for r in rows}
    ev, rng2 = T251._rest("events?select=ts,title&source=eq.binance&kind=eq.delisting&order=ts.asc")
    all_ann = defaultdict(list)      # symbol -> [公告时刻,...](全部公告,不止第一次)
    notices = 0
    for e in ev:
        if not screen_title(e.get("title")):
            continue
        notices += 1
        ts = dt.datetime.fromisoformat(str(e["ts"]).replace("Z", "+00:00"))
        for s in extract_symbols(e.get("title")):
            all_ann[s].append(ts)
    for s in all_ann:
        all_ann[s].sort()
    return table, all_ann, dict(table_rows=len(table), table_range=rng,
                                events_rows=len(ev), events_range=rng2,
                                will_delist_notices=notices, parsed_tokens=len(all_ann))


def excl_key(sym, table):
    """生产 `is_excluded` 的反向:票代号 → 名单里的那个代号(1000 前缀剥掉)。"""
    s = str(sym or "").upper()
    if s in table:
        return s
    if s.startswith("1000") and s[4:] in table:
        return s[4:]
    return None


# ---------------------------------------------------------------- 分类
def _dates_for(sym, table, all_ann, any_ann):
    base = str(sym)[4:] if str(sym).startswith("1000") else str(sym).upper()
    if any_ann:
        return [a.date() for a in all_ann.get(base, [])]
    key = excl_key(sym, table)
    if not key:
        return []
    return [_d(table[key]["announced_at"])]


def classify(tickets, table, all_ann, plan_field="signal_d", window_closed=True, any_ann=False):
    """给票分类:① 开票时已在名单上 ② 持有期间被宣布。

    plan_field: 判 ① 的日期字段('signal_d' = 计划日,主口径 / 'entry_d' = 台账字面)。
    window_closed: True ⇒ 公告日 ≤ 计划日(生产:now 之前的都算数);False ⇒ 半开 [d−365, d)。
    any_ann: True ⇒ 用**全部**公告(不止第一次);False ⇒ 只用表里的第一次。
    """
    c1, c2 = [], []
    for t in tickets:
        dates = _dates_for(t["symbol"], table, all_ann, any_ann)
        if not dates:
            continue
        plan_d = _d(t[plan_field])
        lo = plan_d - dt.timedelta(days=LOOKBACK)
        hit1 = [a for a in dates if (lo <= a <= plan_d) if window_closed] if window_closed else \
               [a for a in dates if (lo <= a < plan_d)]
        if hit1:
            c1.append((t, min(hit1)))
            continue
        if not t.get("entry_d") or not t.get("exit_d"):
            continue
        e0, x0 = _d(t["entry_d"]), _d(t["exit_d"])
        hit2 = [a for a in dates if e0 <= a < x0]
        if hit2:
            c2.append((t, min(hit2)))
    return c1, c2


# ---------------------------------------------------------------- 规则版账本
def apply_rule(tickets, bars, c1, c2):
    """按规则改票:① 整张删掉;② 在公告后第一个开盘平掉(重算 R)。"""
    om = {s: {r[0]: r[1] for r in rws} for s, rws in bars.items()}
    ds = {s: sorted(om[s]) for s in om}
    drop = {t["tid"] for t, _ in c1}
    c2map = {t["tid"]: A for t, A in c2}
    new, detail = [], []
    for t in tickets:
        if t["tid"] in drop:
            continue
        t2 = dict(t)
        a = c2map.get(t["tid"])
        if a is not None and t.get("entry_px") and t.get("stop_px") and t["entry_px"] != t["stop_px"]:
            nxt = next((d for d in ds.get(t["symbol"], []) if d > a.isoformat()), None)
            if nxt is None:
                detail.append(dict(tid=t["tid"], symbol=t["symbol"], announced=a.isoformat(),
                                   note="公告后没有 bar,规则无法平仓 ⇒ 保留原出场"))
            else:
                den = t["entry_px"] - t["stop_px"]
                px = om[t["symbol"]][nxt]
                t2["exit_d"] = nxt
                t2["exit_px"] = px
                t2["exit_reason"] = "stop"        # 开盘平(与止损同一条路径)
                t2["exit_reason_orig"] = t["exit_reason"]
                t2["r"] = (px - t["entry_px"]) / den - 0.004 * t["entry_px"] / den
                detail.append(dict(tid=t["tid"], symbol=t["symbol"], announced=a.isoformat(),
                                   exit_rule=nxt, px_rule=px, px_orig=t["exit_px"],
                                   r_orig=t["r"], r_rule=t2["r"], reason_orig=t["exit_reason"]))
        new.append(t2)
    return new, detail


def ledger(sim, tickets):
    """账本 = 真正成交且有 R 的票。"""
    return [t for t in tickets if t["tid"] in sim["taken"] and t.get("r") is not None]


def rsum(rs):
    return round(sum(rs), 4) if rs else 0.0


def rstat(rs):
    if not rs:
        return dict(n=0, sum_r=0.0, mean_r=None, win_pct=None)
    return dict(n=len(rs), sum_r=rsum(rs), mean_r=round(sum(rs) / len(rs), 4),
                win_pct=round(100.0 * sum(1 for r in rs if r > 0) / len(rs), 1))


def main():
    t0 = time.time()
    table, all_ann, meta = load_delist()
    print(f"名单:{meta['table_rows']} 行 / events {meta['events_rows']} 条 / "
          f"整币公告 {meta['will_delist_notices']} 条 / 解析出 {meta['parsed_tokens']} 个代号", file=sys.stderr)

    pairs, style, bars, uni = T251.fetch_all()
    bars = {s: v for s, v in bars.items() if v}
    gate = T251.load_gate(style)
    tickets, stopped, hole, guard = T251.scan(bars, gate, T251.D_FROM, T251.D_TO)
    print(f"scan 完成:{len(tickets)} 张票(停机={stopped}),{time.time()-t0:.0f}s", file=sys.stderr)
    sim0 = T251.simulate(tickets, bars, gate, CAP_FRAC)
    base_ledger = ledger(sim0, tickets)
    print(f"基准账本:{len(base_ledger)} 张有 R 的成交票,总 R {rsum([t['r'] for t in base_ledger])},"
          f"{time.time()-t0:.0f}s", file=sys.stderr)

    res = dict(task="T-278", ledger="S-757", generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
               window=dict(d_from=T251.D_FROM.isoformat(), d_to=T251.D_TO.isoformat(),
                           cap_frac=CAP_FRAC, equity0=T251.EQUITY0),
               universe_n=len(uni), tickets_scanned=len(tickets), stopped=stopped,
               hole_days=len(hole), delist=dict(table_rows=meta["table_rows"],
                                                events_rows=meta["events_rows"],
                                                will_delist_notices=meta["will_delist_notices"],
                                                parsed_tokens=meta["parsed_tokens"]))

    # 表 vs events 解析的交叉核对(名单本身的可信度)
    parsed_first = {s: all_ann[s][0].date().isoformat() for s in all_ann}
    tbl_first = {s: _d(r["announced_at"]).isoformat() for s, r in table.items()}
    res["delist"]["cross_check"] = dict(
        only_in_table=sorted(set(tbl_first) - set(parsed_first)),
        only_in_events=sorted(set(parsed_first) - set(tbl_first)),
        date_mismatch=sorted(s for s in set(tbl_first) & set(parsed_first)
                             if tbl_first[s] != parsed_first[s]))

    # ---------------- 主口径:计划日 = 信号日,窗口闭(生产语义)
    c1_all, c2_all = classify(tickets, table, all_ann, plan_field="signal_d", window_closed=True)
    c1_any, c2_any = classify(tickets, table, all_ann, plan_field="signal_d", window_closed=True,
                              any_ann=True)
    led_ids = {t["tid"] for t in base_ledger}
    c1 = [(t, a) for t, a in c1_all if t["tid"] in led_ids]
    c2 = [(t, a) for t, a in c2_all if t["tid"] in led_ids]
    print(f"主口径:① 候选 {len(c1_all)}(账本 {len(c1)})/ ② 候选 {len(c2_all)}(账本 {len(c2)})", file=sys.stderr)

    rule_tickets, det2 = apply_rule(tickets, bars, c1_all, c2_all)
    sim1 = T251.simulate(rule_tickets, bars, gate, CAP_FRAC)
    rule_ledger = ledger(sim1, rule_tickets)

    st0 = T251.curve_stats(sim0["curve"], T251.EQUITY0)
    st1 = T251.curve_stats(sim1["curve"], T251.EQUITY0)
    res["baseline"] = dict(n=len(base_ledger), r=rstat([t["r"] for t in base_ledger]),
                            curve=st0, taken=len(sim0["taken"]))
    res["rule"] = dict(n=len(rule_ledger), r=rstat([t["r"] for t in rule_ledger]),
                        curve=st1, taken=len(sim1["taken"]),
                        dropped_candidates=len(c1_all), forced_candidates=len(c2_all))
    res["delta"] = dict(sum_r=rstat([t["r"] for t in rule_ledger])["sum_r"] -
                        rstat([t["r"] for t in base_ledger])["sum_r"],
                        calmar_base=st0["calmar"], calmar_rule=st1["calmar"],
                        total_return_base=st0["total_return"], total_return_rule=st1["total_return"],
                        cagr_base=st0["cagr"], cagr_rule=st1["cagr"],
                        max_dd_base=st0["max_dd"], max_dd_rule=st1["max_dd"],
                        end_equity_base=st0["end_equity"], end_equity_rule=st1["end_equity"])

    def rows_of(cls):
        out = []
        for t, a in cls:
            d = next((x for x in det2 if x["tid"] == t["tid"]), None)
            out.append(dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                            exit_d=t["exit_d"], exit_reason=t["exit_reason"],
                            announced=a.isoformat(), entry_px=t["entry_px"], stop_px=t["stop_px"],
                            exit_px=t["exit_px"], r_orig=round(t["r"], 4),
                            r_rule=(round(d["r_rule"], 4) if d and d.get("r_rule") is not None else None),
                            rule_exit_d=(d.get("exit_rule") if d else None),
                            rule_exit_px=(d.get("px_rule") if d else None),
                            lookback_incomplete=(_d(t["signal_d"]) - dt.timedelta(days=LOOKBACK)) < LIST_START))
        return out

    res["class1_already_on_list"] = dict(
        n=len(c1), n_candidates=len(c1_all), r=rstat([t["r"] for t, _ in c1]),
        rule_r=dict(n=0, sum_r=0.0, mean_r=None, win_pct=None),
        tickets=rows_of(c1))
    res["class2_announced_while_held"] = dict(
        n=len(c2), n_candidates=len(c2_all), r=rstat([t["r"] for t, _ in c2]),
        rule_r=rstat([d["r_rule"] for d in det2 if d.get("r_rule") is not None]),
        detail=det2, tickets=rows_of(c2))

    # 边界:公告日 = 出场日(规则不改变结果)
    bnd = []
    for t in base_ledger:
        key = excl_key(t["symbol"], table)
        if not key or not t.get("exit_d"):
            continue
        a = _d(table[key]["announced_at"]).isoformat()
        if a == str(t["exit_d"])[:10]:
            bnd.append(dict(symbol=t["symbol"], entry_d=t["entry_d"], exit_d=t["exit_d"],
                            exit_reason=t["exit_reason"], announced=a, r=round(t["r"], 4)))
    res["boundary_announced_on_exit_day"] = bnd

    # ---------------- 敏感性 1:台账字面(开票日 = 进场日,窗口 [d−365, d))
    c1s, c2s = classify(tickets, table, all_ann, plan_field="entry_d", window_closed=False)
    st1s_t, _ = apply_rule(tickets, bars, c1s, c2s)
    sim1s = T251.simulate(st1s_t, bars, gate, CAP_FRAC)
    led1s = ledger(sim1s, st1s_t)
    res["sensitivity_entry_day_half_open"] = dict(
        note="台账字面:开票日 = 进场日,窗口 [d−365, d)",
        class1_n=len(c1s), class2_n=len(c2s),
        class1_ledger_n=len([1 for t, _ in c1s if t["tid"] in led_ids]),
        class2_ledger_n=len([1 for t, _ in c2s if t["tid"] in led_ids]),
        class1_symbols=[t["symbol"] for t, _ in c1s], class2_symbols=[t["symbol"] for t, _ in c2s],
        base_n=len(base_ledger), base_sum_r=rstat([t["r"] for t in base_ledger])["sum_r"],
        rule_n=len(led1s), rule_sum_r=rstat([t["r"] for t in led1s])["sum_r"],
        rule_curve=T251.curve_stats(sim1s["curve"], T251.EQUITY0))

    # ---------------- 敏感性 2:用**全部**公告(不止第一次)
    st1a_t, det2a = apply_rule(tickets, bars, c1_any, c2_any)
    sim1a = T251.simulate(st1a_t, bars, gate, CAP_FRAC)
    led1a = ledger(sim1a, st1a_t)
    res["sensitivity_any_announcement"] = dict(
        note="探索性:若名单记全部公告(表的实现只留第一次),规则会多挡多少",
        class1_n=len(c1_any), class2_n=len(c2_any),
        class1_ledger_n=len([1 for t, _ in c1_any if t["tid"] in led_ids]),
        class2_ledger_n=len([1 for t, _ in c2_any if t["tid"] in led_ids]),
        class1_symbols=[t["symbol"] for t, _ in c1_any], class2_symbols=[t["symbol"] for t, _ in c2_any],
        base_sum_r=rstat([t["r"] for t in base_ledger])["sum_r"],
        rule_sum_r=rstat([t["r"] for t in led1a])["sum_r"],
        rule_curve=T251.curve_stats(sim1a["curve"], T251.EQUITY0))

    # ---------------- 台账窗口(2022-02 → 2026-10)子账本
    def in_win(t):
        return LEDGER_FROM <= _d(t["entry_d"]) <= LEDGER_TO
    b_win = [t for t in base_ledger if in_win(t)]
    r_win = [t for t in rule_ledger if in_win(t)]
    res["ledger_window_2022_2026"] = dict(
        note=f"只统计进场日在 {LEDGER_FROM} → {LEDGER_TO} 的票(台账窗口)",
        base=rstat([t["r"] for t in b_win]), rule=rstat([t["r"] for t in r_win]))

    # ---------------- 名单覆盖:宇宙里有多少代号在名单上
    cov = []
    for s in uni:
        key = excl_key(s, table)
        if key:
            cov.append(dict(symbol=s, list_key=key, announced=_d(table[key]["announced_at"]).isoformat(),
                            n_ann=len(all_ann.get(key, []))))
    led_syms = {t["symbol"] for t in base_ledger}
    res["universe_coverage"] = dict(universe_n=len(uni), on_list_n=len(cov),
                                    on_list_with_ticket=sorted(led_syms & {c["symbol"] for c in cov}),
                                    rows=cov)

    # 账本构成变化:规则下多了/少了哪些票
    res["ledger_composition_change"] = dict(
        dropped=[dict(symbol=t["symbol"], entry_d=t["entry_d"], r=round(t["r"], 4))
                 for t in base_ledger if t["tid"] not in sim1["taken"]],
        added=[dict(symbol=t["symbol"], entry_d=t["entry_d"], r=round(t["r"], 4))
               for t in rule_ledger if t["tid"] not in sim0["taken"]])

    json.dump(res, open(OUT, "w"), indent=1, ensure_ascii=False, default=str)
    print(json.dumps(dict(class1=len(c1), class2=len(c2),
                          base_sum_r=res["baseline"]["r"]["sum_r"], rule_sum_r=res["rule"]["r"]["sum_r"],
                          calmar_base=st0["calmar"], calmar_rule=st1["calmar"],
                          secs=round(time.time() - t0, 1)), ensure_ascii=False), file=sys.stderr)
    print("写出", OUT, file=sys.stderr)


if __name__ == "__main__":
    main()
