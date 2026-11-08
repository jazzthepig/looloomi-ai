"""T-303 —— S-785「打标签即剔除」回看(只报不判):R-v2 回放账本在 2023-07 → 2026-10
如果排除 Binance 监控标签上的币,会差多少 —— 给 Jazz 拍板用的数。

口径(照 S-785 预注册原文;票生成与重算 R 复用 S-757 / T-278 的做法):
  票   = T251.scan + T251.simulate(r_v2_k2.5_gate200,40% 档),只取真正成交且有 R 的票。
  标签 = events(source=binance,kind ∈ {monitoring_tag,monitoring_tag_removed}),按 ts 走状态机:
         打上 ⇒ 在标签上;移除 ⇒ 不在。代号口径同 S-751(1000 前缀:票代号 1000PEPE 与 PEPE 同判)。
  ① 开票时已在标签上 ⇒ 不开这张票;
  ② 持有期间被打上标签 ⇒ 次日开盘平(用次日开盘价重算这张票的 R)。
  报:两类各多少张、原 R 合计、规则下 R 合计、差值;账本 2023-07 → 2026-10 的总 R / 最大回撤 /
     Calmar 四版:无规则 / 只下架(S-757) / 只标签(S-785) / 两条都在。**只报不判**;票 < 10 ⇒「无检出力」。

用法:python3 docs/research/t303_retro.py --probe   # 只看数据形状(快)
      python3 docs/research/t303_retro.py --full    # 全跑(写 t303_results.json)
"""
from __future__ import annotations

import argparse
import csv
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

import t251_gross_cap as T251           # noqa: E402 —— 票生成器,口径一字不改
import t278_retro as T278               # noqa: E402 —— S-757 的名单 / 分类 / 规则版账本
from src.data.market.events import monitoring_tag as parse_mon_title   # noqa: E402 —— 生产解析器(交叉核对用)

OUT = HERE / "t303_results.json"
TAGS_CSV = HERE / "t303_tags.csv"
CAP_FRAC = 0.40                        # 40% 档(与 T-251 / T-254 / T-277 / T-278 同)
WIN_FROM = dt.date(2023, 7, 26)        # Binance 监控标签推出日 = 库里最早一条标签公告
WIN_TO = dt.date(2026, 10, 14)         # 台账窗口末端(与 T-278 的 LEDGER_TO 同一天)
FULL_FROM = dt.date(2020, 7, 1)        # 全书起点(与 T251.D_FROM 同)
PREREG = (
    "**写死:** 票 = S-757 同一个生成器(R-v2 规则 r_v2_k2.5_gate200,40% 档,有 R 的成交票),"
    "2023-07-26 → 2026-10。「在标签上」= 开票日 d 之前已有 `events` source = binance、"
    "kind = monitoring_tag 含该代号,且之后没有 monitoring_tag_removed(1000 前缀与 S-751 同口径)。"
    "两类:① 开票日在标签上 ⇒ 不开;② 持有期间被打上标签 ⇒ 次日开盘平(用次日开盘价重算这张票的 R)。"
    "报:两类各多少张、原 R 合计、规则下 R 合计、差值;整个账本 2023-07 → 2026-10 的总 R、最大回撤、Calmar "
    "有 / 没有两版;再叠加 S-757 的下架规则一版(两条都在)。**只报不判。** 票不足 10 张就写「无检出力」。"
)


def _d(x):
    return dt.date.fromisoformat(str(x)[:10])


# ---------------------------------------------------------------- 标签名单
def fetch_pages(path):
    """带 order= 的翻页;Content-Range(PREFER count=exact)核总行数。"""
    rows, off, total = [], 0, None
    while True:
        r, cr = T251._rest(path, f"{off}-{off+999}", extra={"Prefer": "count=exact"})
        if not r:
            break
        rows += r
        off += len(r)
        if cr and "/" in cr:
            try:
                total = int(cr.split("/")[-1])
            except ValueError:
                total = None
        if len(r) < 1000:
            break
    return rows, total


def load_tag_rows():
    path = ("events?select=ts,kind,symbols,title&source=eq.binance"
            "&kind=in.%28monitoring_tag%2Cmonitoring_tag_removed%29&order=ts.asc%2Cid.asc")
    rows, total = fetch_pages(path)
    return rows, total


def build_timeline(rows):
    """代号 → [(日, 打在标签上?, ts)],按 ts 顺序。"""
    tl = defaultdict(list)
    for r in sorted(rows or [], key=lambda r: str(r.get("ts") or "")):
        kind = str(r.get("kind") or "")
        syms = r.get("symbols")
        if not isinstance(syms, list):
            continue
        d = str(r.get("ts") or "")[:10]
        for s in syms:
            s = str(s).upper().strip()
            if s:
                tl[s].append((d, kind == "monitoring_tag", str(r.get("ts") or "")))
    return tl


def _on_at(tl, sym, d):
    """截至 d(含当天)该代号是否在标签上 —— 状态机(打上 True / 移除 False)。"""
    ds = d.isoformat() if isinstance(d, dt.date) else str(d)[:10]
    st = False
    for (dd, on, _ts) in tl.get(sym, ()):
        if dd > ds:
            break
        st = on
    return st


def tagged_at(tl, sym, d):
    """1000 前缀同 S-751:票代号 1000PEPE 与 PEPE 同判。"""
    if _on_at(tl, sym, d):
        return True
    if sym.startswith("1000") and _on_at(tl, sym[4:], d):
        return True
    return False


def onsets(tl, sym):
    """「被打上标签」的时刻(off→on 的切换日),按时间序;含 1000 前缀的底代号。"""
    out = []
    for s in ([sym] + ([sym[4:]] if sym.startswith("1000") else [])):
        st = False
        for (dd, on, _ts) in tl.get(s, ()):
            if on and not st:
                out.append(dd)
            st = on
    return sorted(set(out))


def classify_tag(tickets, tl, plan_field="signal_d"):
    """① 开票时已在标签上 ② 持有期间被打上标签。"""
    c1, c2 = [], []
    for t in tickets:
        sym = str(t["symbol"]).upper()
        if tagged_at(tl, sym, _d(t[plan_field])):
            c1.append((t, _d(t[plan_field])))
            continue
        if not t.get("entry_d") or not t.get("exit_d"):
            continue
        e0, x0 = _d(t["entry_d"]), _d(t["exit_d"])
        hits = [_d(x) for x in onsets(tl, sym) if e0 <= _d(x) < x0]
        if hits:
            c2.append((t, min(hits)))
    return c1, c2


# ---------------------------------------------------------------- 合并两类规则
def merge_classes(c1_a, c2_a, c1_b, c2_b):
    """两条规则同时生效:剔除取并集;强制出场取最早触发日。"""
    seen, c1m = set(), []
    for t, a in list(c1_a) + list(c1_b):
        if t["tid"] in seen:
            continue
        seen.add(t["tid"])
        c1m.append((t, a))
    drop = {t["tid"] for t, _ in c1m}
    c2m = {}
    for t, a in list(c2_a) + list(c2_b):
        if t["tid"] in drop:
            continue
        a = a if isinstance(a, dt.date) else _d(a)
        cur = c2m.get(t["tid"])
        if cur is None or a < cur[1]:
            c2m[t["tid"]] = (t, a)
    return c1m, list(c2m.values())


# ---------------------------------------------------------------- 账本
def rstat(rs):
    if not rs:
        return dict(n=0, sum_r=0.0, mean_r=None, win_pct=None)
    return dict(n=len(rs), sum_r=round(sum(rs), 4), mean_r=round(sum(rs) / len(rs), 4),
                win_pct=round(100.0 * sum(1 for r in rs if r > 0) / len(rs), 1))


def book_view(sim, tickets, equity0=T251.EQUITY0, curve=None):
    led = T278.ledger(sim, tickets)
    st = T251.curve_stats(curve if curve is not None else sim["curve"], equity0)
    return led, dict(n=len(led), r=rstat([t["r"] for t in led]), taken=len(sim["taken"]), curve=st)


def window_curve_stats(sim, d_from, d_to):
    """实盘账本轨迹在窗口内的统计:曲线切窗 + 净值以窗口起点重基。"""
    pts = [c for c in sim["curve"] if d_from <= _d(c[0]) <= d_to]
    if not pts:
        return None
    eq0 = pts[0][1]
    return T251.curve_stats(pts, eq0)


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    # ---- 1) 标签名单(现读 events)
    rows, total = load_tag_rows()
    tl = build_timeline(rows)
    notices = defaultdict(list)
    for r in rows:
        for s in (r.get("symbols") or []):
            notices[str(s).upper()].append(r)
    print(f"events 标签行 {len(rows)}(Content-Range 总数 {total})/ 代号 {len(tl)}", file=sys.stderr)

    # 交叉核对:DB 的 kind/symbols 与生产解析器(标题重解析)是否一致
    xcheck = dict(kind_mismatch=[], sym_mismatch=[], parse_empty=[], n=len(rows))
    for r in rows:
        k2, s2 = parse_mon_title(r.get("title"))
        if k2 != str(r.get("kind") or ""):
            xcheck["kind_mismatch"].append(dict(ts=r.get("ts"), db=r.get("kind"), parsed=k2,
                                                title=str(r.get("title"))[:120]))
        db_s = sorted({str(x).upper() for x in (r.get("symbols") or [])})
        if sorted(set(s2)) != db_s:
            xcheck["sym_mismatch"].append(dict(ts=r.get("ts"), db=db_s, parsed=sorted(set(s2)),
                                               title=str(r.get("title"))[:120]))
        if not s2:
            xcheck["parse_empty"].append(dict(ts=r.get("ts"), title=str(r.get("title"))[:120]))
    print(f"交叉核对:kind 不一致 {len(xcheck['kind_mismatch'])}/ 代号不一致 {len(xcheck['sym_mismatch'])}"
          f"/ 解析不出代号 {len(xcheck['parse_empty'])}", file=sys.stderr)

    # ---- 2) 取数(缓存)
    pairs, style, bars, uni = T251.fetch_all()
    bars = {s: v for s, v in bars.items() if v}
    gate = T251.load_gate(style)
    last_bar = max((r[0] for v in bars.values() for r in v), default="")
    print(f"宇宙 {len(uni)} 个符号 / bars 到 {last_bar} / gate 到 {max(gate) if gate else None}"
          f" / {time.time()-t0:.0f}s", file=sys.stderr)

    # ---- 3) 标签名单 CSV(先落盘)
    today = dt.date.today()
    with open(TAGS_CSV, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "first_tag_d", "last_tag_d", "n_tag_events", "n_removed",
                    "on_list_now", "in_rv2_universe", "titles"])
        for s in sorted(tl):
            evs = tl[s]
            tags = [e for e in evs if e[1]]
            rems = [e for e in evs if not e[1]]
            w.writerow([s, tags[0][0] if tags else "", tags[-1][0] if tags else "",
                        len(tags), len(rems), "Y" if _on_at(tl, s, today.isoformat()) else "N",
                        "Y" if s in uni else "",
                        " | ".join(str(r.get("title"))[:80] for r in notices.get(s, [])[:3])])
    print("写出", TAGS_CSV, file=sys.stderr)

    if args.probe and not args.full:
        on_now = sorted(s for s in tl if _on_at(tl, s, today.isoformat()))
        print(json.dumps(dict(events_rows=len(rows), total=total, symbols=len(tl),
                              on_list_now=on_now, xcheck=xcheck), ensure_ascii=False, indent=1))
        return

    res = dict(task="T-303", ledger="S-785",
               generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
               prereg=PREREG,
               window=dict(win_from=WIN_FROM.isoformat(), win_to=WIN_TO.isoformat(),
                           full_from=FULL_FROM.isoformat(), cap_frac=CAP_FRAC,
                           equity0=T251.EQUITY0),
               universe_n=len(uni), last_bar=last_bar,
               tags=dict(events_rows=len(rows), content_range_total=total,
                         symbols=len(tl), csv=TAGS_CSV.name, cross_check=xcheck,
                         on_list_now=sorted(s for s in tl if _on_at(tl, s, today.isoformat()))))

    # ---- 4) 下架名单(S-757 口径,复用 T-278)
    table, all_ann, dmeta = T278.load_delist()
    res["delist"] = dict(dmeta)
    print(f"下架名单:{dmeta['table_rows']} 行 / events {dmeta['events_rows']} 条", file=sys.stderr)

    # ---- 5) 主账本(窗口内独立起账)
    tickets_p, stopped_p, hole_p, _g = T251.scan(bars, gate, WIN_FROM, WIN_TO)
    print(f"主账本 scan:{len(tickets_p)} 张票(停机={stopped_p}),{time.time()-t0:.0f}s", file=sys.stderr)
    sim_b = T251.simulate(tickets_p, bars, gate, CAP_FRAC)
    led_b, view_b = book_view(sim_b, tickets_p)

    # 标签规则
    c1, c2 = classify_tag(tickets_p, tl, plan_field="signal_d")
    tk_t, det_t = T278.apply_rule(tickets_p, bars, c1, c2)
    sim_t = T251.simulate(tk_t, bars, gate, CAP_FRAC)
    led_t, view_t = book_view(sim_t, tk_t)

    # 下架规则
    dl_c1, dl_c2 = T278.classify(tickets_p, table, all_ann, plan_field="signal_d", window_closed=True)
    dl_t, det_d = T278.apply_rule(tickets_p, bars, dl_c1, dl_c2)
    sim_d = T251.simulate(dl_t, bars, gate, CAP_FRAC)
    led_d, view_d = book_view(sim_d, dl_t)

    # 两条都在
    m_c1, m_c2 = merge_classes(c1, c2, dl_c1, dl_c2)
    bo_t, det_b = T278.apply_rule(tickets_p, bars, m_c1, m_c2)
    sim_bo = T251.simulate(bo_t, bars, gate, CAP_FRAC)
    led_bo, view_bo = book_view(sim_bo, bo_t)

    print(f"主账本:{len(led_b)} 张有 R 的成交票,总 R {view_b['r']['sum_r']}", file=sys.stderr)

    def deltas(base, other):
        return dict(sum_r_delta=round(other["r"]["sum_r"] - base["r"]["sum_r"], 4),
                    n_delta=other["n"] - base["n"],
                    calmar_delta=(round(other["curve"]["calmar"] - base["curve"]["calmar"], 4)
                                  if base["curve"].get("calmar") is not None
                                  and other["curve"].get("calmar") is not None else None),
                    max_dd_delta=(round(other["curve"]["max_dd"] - base["curve"]["max_dd"], 4)
                                  if base["curve"].get("max_dd") is not None
                                  and other["curve"].get("max_dd") is not None else None))

    res["book_window"] = dict(
        note="口径 A:窗口内独立起账(2023-07-26 起,equity0=630);四版同一生成器、同一 40% 档",
        baseline=view_b, tag_only=view_t, delist_only=view_d, both=view_bo,
        delta=dict(tag_only=deltas(view_b, view_t), delist_only=deltas(view_b, view_d),
                   both=deltas(view_b, view_bo)))

    # 票级明细
    led_ids = {t["tid"] for t in led_b}

    def rows_of(cls):
        out = []
        for t, a in cls:
            d = next((x for x in det_t if x["tid"] == t["tid"]), None)
            out.append(dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                            exit_d=t["exit_d"], exit_reason=t["exit_reason"], tag_d=a.isoformat(),
                            entry_px=t["entry_px"], stop_px=t["stop_px"], exit_px=t["exit_px"],
                            r_orig=round(t["r"], 4) if t.get("r") is not None else None,
                            r_rule=(round(d["r_rule"], 4) if d and d.get("r_rule") is not None else None),
                            rule_exit_d=(d.get("exit_rule") if d else None),
                            rule_exit_px=(d.get("px_rule") if d else None),
                            in_ledger=t["tid"] in led_ids))
        return out

    res["class1_already_tagged"] = dict(
        n_candidates=len(c1), n_ledger=len([1 for t, _ in c1 if t["tid"] in led_ids]),
        r=rstat([t["r"] for t, _ in c1 if t.get("r") is not None]),
        rule_r=rstat([]), rows=rows_of(c1))
    res["class2_tagged_while_held"] = dict(
        n_candidates=len(c2), n_ledger=len([1 for t, _ in c2 if t["tid"] in led_ids]),
        r=rstat([t["r"] for t, _ in c2 if t.get("r") is not None]),
        rule_r=rstat([d["r_rule"] for d in det_t if d.get("r_rule") is not None]),
        detail=det_t, rows=rows_of(c2))

    # ---- 6) 敏感性:同一台账的字面口径(开票日 = 进场日)
    c1s, c2s = classify_tag(tickets_p, tl, plan_field="entry_d")
    st1s, det_s = T278.apply_rule(tickets_p, bars, c1s, c2s)
    sim_s = T251.simulate(st1s, bars, gate, CAP_FRAC)
    led_s, view_s = book_view(sim_s, st1s)
    res["sensitivity_entry_day"] = dict(
        note="台账字面:开票日 = 进场日(主口径用信号日,生产语义:计划生成时看名单)",
        class1_n=len(c1s), class2_n=len(c2s),
        class1_ledger_n=len([1 for t, _ in c1s if t["tid"] in led_ids]),
        class2_ledger_n=len([1 for t, _ in c2s if t["tid"] in led_ids]),
        class1_symbols=[t["symbol"] for t, _ in c1s], class2_symbols=[t["symbol"] for t, _ in c2s],
        rule_n=view_s["n"], rule_sum_r=view_s["r"]["sum_r"], rule_curve=view_s["curve"])

    # ---- 7) 敏感性:全书(2020-07 起)+ 窗口子账本
    tickets_f, stopped_f, hole_f, _gf = T251.scan(bars, gate, FULL_FROM, WIN_TO)
    print(f"全书 scan:{len(tickets_f)} 张票(停机={stopped_f}),{time.time()-t0:.0f}s", file=sys.stderr)
    sim_fb = T251.simulate(tickets_f, bars, gate, CAP_FRAC)
    fb_c1, fb_c2 = classify_tag(tickets_f, tl, plan_field="signal_d")
    fb_dl_c1, fb_dl_c2 = T278.classify(tickets_f, table, all_ann, plan_field="signal_d",
                                       window_closed=True)
    fb_t, fb_det = T278.apply_rule(tickets_f, bars, fb_c1, fb_c2)
    fb_d, fb_dd = T278.apply_rule(tickets_f, bars, fb_dl_c1, fb_dl_c2)
    fb_mc1, fb_mc2 = merge_classes(fb_c1, fb_c2, fb_dl_c1, fb_dl_c2)
    fb_b, fb_bd = T278.apply_rule(tickets_f, bars, fb_mc1, fb_mc2)
    sims_f = dict(baseline=T251.simulate(tickets_f, bars, gate, CAP_FRAC),
                  tag_only=T251.simulate(fb_t, bars, gate, CAP_FRAC),
                  delist_only=T251.simulate(fb_d, bars, gate, CAP_FRAC),
                  both=T251.simulate(fb_b, bars, gate, CAP_FRAC))

    def sub_led(sim, tks):
        return [t for t in T278.ledger(sim, tks)
                if WIN_FROM <= _d(t["entry_d"]) <= WIN_TO]

    full = {}
    for k, sim in sims_f.items():
        sl = sub_led(sim, {"baseline": tickets_f, "tag_only": fb_t, "delist_only": fb_d,
                           "both": fb_b}[k])
        full[k] = dict(n=len(sl), r=rstat([t["r"] for t in sl]),
                        window_curve=window_curve_stats(sim, WIN_FROM, WIN_TO),
                        book_n=len(T278.ledger(sim, {"baseline": tickets_f, "tag_only": fb_t,
                                                    "delist_only": fb_d, "both": fb_b}[k])))
    res["sensitivity_full_book"] = dict(
        note="口径 B:全书从 2020-07-01 起(实盘账本轨迹),窗口 = 进场日落在 2023-07-26 → 2026-10-14 的子账本;"
             "标签规则在 2023-07-26 之前天然不生效(标签制度那天才推出)",
        tickets_scanned=len(tickets_f), stopped=stopped_f, books=full)

    res["caveats"] = [
        "只报不判:本卡不给结论,只给 Jazz 拍板用的数。",
        "被剔除的票腾出的持仓名额与本金会改变后续成交 ⇒ 规则版的账本与原账本不是同一批票(逐位相同才说明规则没 bites)。",
        "票生成器不会因规则重扫信号:被剔除的票所在代号,后面若还有信号,仍按原生成器的口径参与(与 T-278 同一简化)。",
        "② 的次日开盘可能低于止损价 ⇒ 重算 R 用开盘价(跳空止损同路径),不会先假设止损成交。",
        "窗口内独立起账(口径 A)与全书轨迹(口径 B)都给;两者数字不同是正常的(起点净值与占用不同)。",
    ]

    # ---- 8) 账本构成变化(规则到底换掉了哪几张票)与入场被挡的机制
    def compose(base_sim, base_tks, rule_sim, rule_tks):
        bt = {t["tid"]: t for t in T278.ledger(base_sim, base_tks)}
        rt = {t["tid"]: t for t in T278.ledger(rule_sim, rule_tks)}
        return dict(
            dropped=[dict(tid=t["tid"], symbol=t["symbol"], entry_d=t["entry_d"], exit_d=t["exit_d"],
                          exit_reason=t["exit_reason"], r=round(t["r"], 4))
                     for t in bt.values() if t["tid"] not in rt],
            added=[dict(tid=t["tid"], symbol=t["symbol"], entry_d=t["entry_d"], exit_d=t["exit_d"],
                        exit_reason=t["exit_reason"], r=round(t["r"], 4))
                   for t in rt.values() if t["tid"] not in bt],
            dropped_sum_r=round(sum(t["r"] for t in bt.values() if t["tid"] not in rt), 4),
            added_sum_r=round(sum(t["r"] for t in rt.values() if t["tid"] not in bt), 4))

    res["composition_change_window"] = compose(sim_b, tickets_p, sim_t, tk_t)
    res["composition_change_full_book"] = compose(sims_f["baseline"], tickets_f,
                                                  sims_f["tag_only"], fb_t)

    def admit_stats(sim):
        c = [x[1] for x in sim["curve"]]
        return dict(taken=len(sim["taken"]), blocked_gross=len(sim["blocked_gross"]),
                    blocked_cap=len(sim["blocked_cap"]), blocked_min=len(sim["blocked_min"]),
                    blocked_coin=len(sim["blocked_coin"]),
                    equity_min=round(min(c), 2) if c else None,
                    equity_max=round(max(c), 2) if c else None)

    def stop_frac_stats(tks):
        fs = sorted(100.0 * (t["entry_px"] - t["stop_px"]) / t["entry_px"]
                    for t in tks if t.get("entry_px") and t.get("stop_px"))
        if not fs:
            return None
        q = lambda p: fs[min(len(fs) - 1, int(p * len(fs)))]
        return dict(n=len(fs), p10=round(q(0.1), 2), p50=round(q(0.5), 2), p90=round(q(0.9), 2))

    win_tickets_p = [t for t in tickets_p]
    win_tickets_f = [t for t in tickets_f if WIN_FROM <= _d(t["signal_d"]) <= WIN_TO]
    res["admission_diagnostics"] = dict(
        note="为什么两个口径票数不同:入场被 $10 最小名义 / 持仓上限 / 总名义上限各挡掉多少",
        window_A=dict(book=admit_stats(sim_b), tag_book=admit_stats(sim_t),
                      scanned=len(tickets_p), stop_frac_pct=stop_frac_stats(win_tickets_p)),
        full_B_window=dict(book=admit_stats(sims_f["baseline"]),
                           tag_book=admit_stats(sims_f["tag_only"]),
                           scanned=len(win_tickets_f),
                           stop_frac_pct=stop_frac_stats(win_tickets_f)))



    json.dump(res, open(OUT, "w"), indent=1, ensure_ascii=False, default=str)
    print(json.dumps(dict(class1=len(c1), class2=len(c2),
                          base_n=view_b["n"], base_sum_r=view_b["r"]["sum_r"],
                          tag_sum_r=view_t["r"]["sum_r"], delist_sum_r=view_d["r"]["sum_r"],
                          both_sum_r=view_bo["r"]["sum_r"],
                          secs=round(time.time() - t0, 1)), ensure_ascii=False), file=sys.stderr)
    print("写出", OUT, file=sys.stderr)


if __name__ == "__main__":
    main()
