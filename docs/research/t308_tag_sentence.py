"""T-308 —— T-303「按标题分句重跑」(只读,只算不判)。

问题(卡上写死):`events` 表一行一个 kind + 一坨 symbols。标题
『Extend the Monitoring Tag to Include X … and Remove the Seed Tag for Y』被整行判成 removed,
种子标签那一支被错当成「监控标签被移除」。S-785「打标签即剔除」的结论是在这份被错判的名单上得出的。

本卡做的事(全部只在分析脚本里做,不改 `src/data/market/events.py`、不改入库字段):
  (1) 按标题**分句**:三类语义分开 —— ① 监控标签新增(Extend the Monitoring Tag …)
      ② 监控标签移除(Remove the Monitoring Tag …)③ 种子标签移除(Remove the Seed Tag …,
      与监控标签状态**无关**);用分句结果重建「在标签上」状态机,重跑口径 A / B。
  (2) tag_d 改存**实际打标签日**(状态机里 off→on 的那一天),不是计划日(信号日)。
  (3) 补零信号基线:窗口成交票的亏损占比 + 随机挡 N 张的期望与零分布分位
      (用 src/data/evaluation/apparatus.py 的 null_distribution / percentile_of)。
  (4) 补口径映射表 T-303 ↔ T-278。
  (5) 报告 §七.2「几乎零交集」按修正后的代号集合重写。

口径不动:T-251 的票生成器 / T-278 的规则与账本,一字不改其行为。
用法:python3 docs/research/t308_tag_sentence.py [raw|split|book|null|all]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import t251_gross_cap as T251           # noqa: E402 —— 票生成器,口径一字不改
import t278_retro as T278               # noqa: E402 —— S-757 的名单 / 规则 / 账本
import t303_retro as T303               # noqa: E402 —— T-303 的名单 / 状态机 / 视图
from src.data.evaluation import apparatus as AP   # noqa: E402 —— 零分布 / 分位

RAW_JSON = HERE / "t308_events_raw.json"
SPLIT_JSON = HERE / "t308_split.json"
OUT_JSON = HERE / "t308_results.json"
TAGS_CSV = HERE / "t308_tags.csv"

CAP_FRAC = 0.40
WIN_FROM = dt.date(2023, 7, 26)
WIN_TO = dt.date(2026, 10, 14)
FULL_FROM = dt.date(2020, 7, 1)
N_NULL = 2000
SEED = 20261108

# 标题里不是代号的词(全大写形态)。生产解析器只挡 6 个词,这里补齐公告套话。
STOP = {
    "ON", "TO", "AND", "THE", "FOR", "OF", "INCLUDE", "INCLUDING", "INCLUDES", "REMOVE",
    "REMOVED", "REMOVES", "REMOVING", "SEED", "TAG", "TAGS", "MONITORING", "WILL", "BE",
    "IS", "ARE", "WAS", "WERE", "BINANCE", "EXTEND", "EXTENDED", "EXTENDS", "CHANGE",
    "CHANGES", "CHANGED", "INCLUSION", "FREQUENCY", "MONTHLY", "TOKENS", "HIGH",
    "VOLATILITY", "RISKS", "INTRODUCING", "WITH", "IT", "ITS", "NEW", "LISTING",
    "DELISTING", "TRADING", "ADD", "ADDS", "ADDED", "UPDATE", "UPDATED", "UNDER", "FROM",
    "ALL", "THESE", "THAT", "VIA", "HAS", "HAVE", "HAD", "ALSO", "NOW", "OR", "BUT",
    "NOT", "THEY", "WE", "YOU", "THEIR", "WHICH", "WHEN", "WHILE", "AFTER", "BEFORE",
    "DUE", "THIS", "MIGHT", "MAY", "CAN", "SHOULD", "MUST", "IF", "THEN",
    "INTO", "OVER", "PER", "MORE", "MOST", "LESS", "THAN", "LIKE", "SAME", "NEWLY",
    "AS", "BY", "AT", "IN", "SO", "UP", "OUT", "NOTICE", "ANNOUNCEMENT",
    "ANNOUNCED", "PLATFORM", "USER", "USERS", "SERVICE", "SERVICES", "MONTHLY",
}

# 子句头:`the (监控标签|种子标签)`;动词从左边最近的那个取(承前动词:「Remove the Monitoring Tag
# for ZEC and the Seed Tag for ENA」里的 Seed Tag 沿用 Remove)。
TAGREF_RE = re.compile(r"\bthe\s+(?P<which>monitoring|seed)\s+tags?\b", re.IGNORECASE)
VERB_RE = re.compile(r"\b(?P<verb>extend|remove|add|update|change)\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"\b[A-Z0-9]{2,12}\b")
DATE_RE = re.compile(r"\(?\d{4}-\d{2}-\d{2}\)?")


def _d(x):
    return dt.date.fromisoformat(str(x)[:10])


# ── 阶段 1:原始事件行(现读,翻页带 order=,核 Content-Range 总数)──────────────
def phase_raw():
    path = ("events?select=*&source=eq.binance"
            "&kind=in.%28monitoring_tag%2Cmonitoring_tag_removed%29&order=ts.asc%2Cid.asc")
    rows, total = T303.fetch_pages(path)
    out = dict(task="T-308", fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(),
               content_range_total=total, n_rows=len(rows), rows=rows)
    json.dump(out, open(RAW_JSON, "w"), ensure_ascii=False, indent=1, default=str)
    keys = sorted({k for r in rows for k in r})
    print(f"events 行 {len(rows)}(Content-Range 总数 {total})→ {RAW_JSON.name}", file=sys.stderr)
    print(f"列: {keys}", file=sys.stderr)
    return out


# ── 阶段 2:按标题分句 ─────────────────────────────────────────────────────
def clause_tokens(seg, whitelist):
    """片段 → 代号列表(大写 token;STOP 挡掉套话;白名单只认事件表里出现过的代号形态)。"""
    seg = DATE_RE.sub(" ", seg)
    out, seen = [], set()
    for s in TOKEN_RE.findall(seg):
        if s.isdigit() or s in STOP or s in seen:
            continue
        if whitelist is not None and s not in whitelist:
            continue
        seen.add(s)
        out.append(s)
    return out


def split_title(title, whitelist=None):
    """标题 → 三类语义:
       add = 监控标签新增;rem_mon = 监控标签移除;rem_seed = 种子标签移除(与监控标签无关);
       other = 只改制度参数(频率等),不产生代号。"""
    t = str(title or "")
    refs = list(TAGREF_RE.finditer(t))
    out = dict(add=[], rem_mon=[], rem_seed=[], other=[])
    last_verb = None
    for i, m in enumerate(refs):
        end = refs[i + 1].start() if i + 1 < len(refs) else len(t)
        prev_end = refs[i - 1].end() if i > 0 else 0
        vms = list(VERB_RE.finditer(t, prev_end, m.start()))
        verb = vms[-1].group("verb").lower() if vms else last_verb
        last_verb = verb or last_verb
        which = m.group("which").lower()
        toks = clause_tokens(t[m.end():end], whitelist)
        if which == "seed":
            out["rem_seed"] += toks              # 种子标签:不进监控标签状态机
        elif verb in ("extend", "add", "update"):
            out["add"] += toks
        elif verb == "remove":
            out["rem_mon"] += toks
        else:
            out["other"] += toks                  # change 频率等
    for k in out:
        seen, keep = set(), []
        for s in out[k]:
            if s not in seen:
                seen.add(s)
                keep.append(s)
        out[k] = keep
    return out


def phase_split():
    raw = json.load(open(RAW_JSON))
    rows = raw["rows"]
    # 白名单:所有行 symbols 的并集(生产解析器抓到的代号形态全集)
    wl = set()
    for r in rows:
        for s in (r.get("symbols") or []):
            wl.add(str(s).upper().strip())
    out = []
    for r in rows:
        sp = split_title(r.get("title"), wl)
        out.append(dict(ts=str(r.get("ts") or ""), id=r.get("id"), kind=r.get("kind"),
                        db_symbols=sorted(str(s).upper() for s in (r.get("symbols") or [])),
                        title=str(r.get("title") or ""),
                        add=sp["add"], rem_mon=sp["rem_mon"], rem_seed=sp["rem_seed"],
                        other=sp["other"]))
    json.dump(dict(task="T-308", stage="split", whitelist=sorted(wl), rows=out),
              open(SPLIT_JSON, "w"), ensure_ascii=False, indent=1)
    for o in out:
        print(f"{o['ts'][:10]} {o['kind'][-8:]:>8} | add={o['add']} rem_mon={o['rem_mon']} "
              f"rem_seed={o['rem_seed']} other={o['other']}", file=sys.stderr)
    print("→", SPLIT_JSON.name, file=sys.stderr)
    return out


# ── 状态机(分句口径)────────────────────────────────────────────────────────
def build_timeline_sentence(rows):
    """代号 → [(日, 打在标签上?, ts)]。种子标签那一支不进状态机。"""
    tl = defaultdict(list)
    for r in sorted(rows, key=lambda x: str(x.get("ts") or "")):
        d = str(r.get("ts") or "")[:10]
        for s in r.get("add") or []:
            tl[s].append((d, True, str(r.get("ts") or "")))
        for s in r.get("rem_mon") or []:
            tl[s].append((d, False, str(r.get("ts") or "")))
    return tl


def last_on_before(tl, sym, d):
    """该代号截至 d(含当天)最后一次 off→on 的日 = 实际打标签日。"""
    ds = d.isoformat() if isinstance(d, dt.date) else str(d)[:10]
    cands = []
    for s in ([sym] + ([sym[4:]] if sym.startswith("1000") else [])):
        cands += [x for x in T303.onsets(tl, s) if x <= ds]
    return max(cands) if cands else None


def classify_split(tickets, tl, plan_field="signal_d"):
    """① 开票时已在标签上(tag_d = 实际打标签日)② 持有期间被打上(tag_d = 实际打标签日)。"""
    c1, c2 = [], []
    for t in tickets:
        sym = str(t["symbol"]).upper()
        plan_d = _d(t[plan_field])
        if T303.tagged_at(tl, sym, plan_d):
            c1.append((t, last_on_before(tl, sym, plan_d)))
            continue
        if not t.get("entry_d") or not t.get("exit_d"):
            continue
        e0, x0 = _d(t["entry_d"]), _d(t["exit_d"])
        hits = [_d(x) for x in T303.onsets(tl, sym) if e0 <= _d(x) < x0]
        if hits:
            c2.append((t, min(hits)))
    return c1, c2


# ── 阶段 3:账本重跑(口径 A 窗口独立起账 / 口径 B 全书 + 窗口子账本)──────────
def phase_book():
    t0 = time.time()
    raw = json.load(open(RAW_JSON))
    split = json.load(open(SPLIT_JSON))
    db_rows = raw["rows"]

    tl_row = T303.build_timeline(db_rows)                 # 行级(报告口径 / T-303 原口径)
    tl_sent = build_timeline_sentence(split["rows"])       # 分句(修正口径)

    # 名单对照
    names = {}
    for tag, tl in (("row", tl_row), ("sentence", tl_sent)):
        on_now = sorted(s for s in tl if T303._on_at(tl, s, dt.date.today().isoformat()))
        names[tag] = dict(n_symbols=len(tl),
                          n_with_add_event=sum(1 for v in tl.values() if any(x[1] for x in v)),
                          on_list_now=on_now)
    print(f"名单:行级 {names['row']['n_symbols']} 代号(有打上事件 {names['row']['n_with_add_event']})"
          f" / 分句 {names['sentence']['n_symbols']} 代号(有打上事件 {names['sentence']['n_with_add_event']})",
          file=sys.stderr)

    # 票 + 账本
    pairs, style, bars, uni = T251.fetch_all()
    bars = {s: v for s, v in bars.items() if v}
    gate = T251.load_gate(style)
    print(f"宇宙 {len(uni)} 符号 / bars 到位 / {time.time()-t0:.0f}s", file=sys.stderr)

    tickets_p, stopped_p, hole_p, _g = T251.scan(bars, gate, WIN_FROM, WIN_TO)
    sim_b = T251.simulate(tickets_p, bars, gate, CAP_FRAC)
    led_b, view_b = T303.book_view(sim_b, tickets_p)
    print(f"口径 A 基线: n={view_b['n']} sum_r={view_b['r']['sum_r']} "
          f"(期望 155 / 110.0372)", file=sys.stderr)

    def run(tickets, tl, tag, plan_field="signal_d"):
        c1, c2 = classify_split(tickets, tl, plan_field=plan_field)
        tk, det = T278.apply_rule(tickets, bars, c1, c2)
        sim = T251.simulate(tk, bars, gate, CAP_FRAC)
        led, view = T303.book_view(sim, tk)
        return dict(tag=tag, c1=c1, c2=c2, det=det, sim=sim, led=led, view=view)

    books = {}
    for tag, tl in (("row", tl_row), ("sentence", tl_sent)):
        books[tag] = run(tickets_p, tl, tag)
        v = books[tag]["view"]
        print(f"口径 A · 名单 {tag}: class1 {len(books[tag]['c1'])} class2 {len(books[tag]['c2'])} "
              f"| n {v['n']} sum_r {v['r']['sum_r']} ΔR {round(v['r']['sum_r'] - view_b['r']['sum_r'], 4)}",
              file=sys.stderr)

    led_ids = {t["tid"] for t in led_b}

    def rows_of(tag, cls):
        out = []
        det = books[tag]["det"]
        for t, a in cls:
            d = next((x for x in det if x["tid"] == t["tid"]), None)
            out.append(dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                            exit_d=t["exit_d"], exit_reason=t["exit_reason"],
                            tag_d=(a.isoformat() if isinstance(a, dt.date)
                                   else (str(a)[:10] if a else None)),
                            plan_d=_d(t["signal_d"]).isoformat(),
                            r_orig=round(t["r"], 4) if t.get("r") is not None else None,
                            in_ledger=t["tid"] in led_ids))
        return out

    # 口径 A:账内被挡的票(基线账本有、规则账本无)
    for tag in ("row", "sentence"):
        b = books[tag]
        rule_ids = {t["tid"] for t in b["led"]}
        dropped = [t for t in led_b if t["tid"] not in rule_ids]
        b["dropped_ledger_n"] = len(dropped)
        b["dropped_ledger_r"] = round(sum(t["r"] for t in dropped), 4)
        b["dropped_ledger_rows"] = [dict(symbol=t["symbol"], signal_d=t["signal_d"],
                                         entry_d=t["entry_d"], exit_d=t["exit_d"],
                                         r=round(t["r"], 4)) for t in dropped]

    res = dict(task="T-308", ledger="S-785", stage="book",
               generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
               window=dict(win_from=WIN_FROM.isoformat(), win_to=WIN_TO.isoformat(),
                           full_from=FULL_FROM.isoformat(), cap_frac=CAP_FRAC),
               universe_n=len(uni), names=names,
               book_A=dict(
                   note="口径 A:窗口内独立起账(2023-07-26 起);名单口径 row=行级 kind(报告口径),"
                        "sentence=按标题分句(修正口径)",
                   baseline=view_b,
                   baseline_tickets_r=[round(t["r"], 6) for t in led_b],
                   row=dict(n=books["row"]["view"]["n"], r=books["row"]["view"]["r"],
                            curve=books["row"]["view"]["curve"],
                            delta_sum_r=round(books["row"]["view"]["r"]["sum_r"]
                                              - view_b["r"]["sum_r"], 4),
                            dropped_ledger_n=books["row"]["dropped_ledger_n"],
                            dropped_ledger_r=books["row"]["dropped_ledger_r"],
                            dropped_ledger_rows=books["row"]["dropped_ledger_rows"],
                            class1_n=len(books["row"]["c1"]), class2_n=len(books["row"]["c2"]),
                            class1_rows=rows_of("row", books["row"]["c1"])),
                   sentence=dict(n=books["sentence"]["view"]["n"], r=books["sentence"]["view"]["r"],
                                 curve=books["sentence"]["view"]["curve"],
                                 delta_sum_r=round(books["sentence"]["view"]["r"]["sum_r"]
                                                   - view_b["r"]["sum_r"], 4),
                                 dropped_ledger_n=books["sentence"]["dropped_ledger_n"],
                                 dropped_ledger_r=books["sentence"]["dropped_ledger_r"],
                                 dropped_ledger_rows=books["sentence"]["dropped_ledger_rows"],
                                 class1_n=len(books["sentence"]["c1"]),
                                 class2_n=len(books["sentence"]["c2"]),
                                 class1_rows=rows_of("sentence", books["sentence"]["c1"]))))

    # ---- 口径 B:全书 2020-07 起 + 窗口子账本 ----
    tickets_f, stopped_f, hole_f, _gf = T251.scan(bars, gate, FULL_FROM, WIN_TO)
    sim_fb = T251.simulate(tickets_f, bars, gate, CAP_FRAC)

    def sub_led(sim, tks):
        return [t for t in T278.ledger(sim, tks)
                if WIN_FROM <= _d(t["entry_d"]) <= WIN_TO]

    fb = {}
    led0 = sub_led(sim_fb, tickets_f)
    for tag, tl in (("row", tl_row), ("sentence", tl_sent)):
        c1, c2 = classify_split(tickets_f, tl, plan_field="signal_d")
        tk, _det = T278.apply_rule(tickets_f, bars, c1, c2)
        sim = T251.simulate(tk, bars, gate, CAP_FRAC)
        sl = sub_led(sim, tk)
        wc = T303.window_curve_stats(sim, WIN_FROM, WIN_TO)
        base_ids = {t["tid"] for t in led0}
        dropped = [t for t in led0 if t["tid"] not in {x["tid"] for x in sl}]
        fb[tag] = dict(class1_n=len(c1), class2_n=len(c2), window_n=len(sl),
                       window_sum_r=round(sum(t["r"] for t in sl), 4),
                       dropped_ledger_n=len(dropped),
                       dropped_ledger_r=round(sum(t["r"] for t in dropped), 4),
                       tickets_r=[round(t["r"], 6) for t in sl],
                       window_curve={k: round(v, 4) if isinstance(v, float) else v
                                     for k, v in (wc or {}).items()
                                     if k in ("max_dd", "calmar", "end_equity", "total_return", "cagr")})
        print(f"口径 B · 名单 {tag}: class1 {len(c1)} class2 {len(c2)} | 窗口成交票 {len(sl)} "
              f"总 R {fb[tag]['window_sum_r']} 账内被挡 {len(dropped)} 张", file=sys.stderr)
    res["book_B"] = dict(
        note="口径 B:全书 2020-07-01 起(实盘账本轨迹),窗口 = 进场日落在 2023-07-26 → 2026-10-14 的子账本",
        tickets_scanned=len(tickets_f), stopped=stopped_f,
        baseline=dict(window_n=len(led0), window_sum_r=round(sum(t["r"] for t in led0), 4),
                      tickets_r=[round(t["r"], 6) for t in led0]),
        row=fb["row"], sentence=fb["sentence"])

    # ---- 与 T-278 对齐的口径(T-278 自己的 scan 区间 + 整本账本)--------------
    # T-278:scan(T251.D_FROM → T251.D_TO)= 2020-07-01 → today-1,ledger 整本不过滤 ⇒ 145 张 / 54.3331
    A_FROM, A_TO = dt.date(2022, 2, 17), dt.date(2026, 10, 14)
    tickets_al, _sa, _ha, _ga = T251.scan(bars, gate, T251.D_FROM, T251.D_TO)
    sim_al = T251.simulate(tickets_al, bars, gate, CAP_FRAC)

    def sub_led_aligned(sim, tks):
        return [t for t in T278.ledger(sim, tks) if A_FROM <= _d(t["entry_d"]) <= A_TO]

    al_base_full = T278.ledger(sim_al, tickets_al)
    al_base = sub_led_aligned(sim_al, tickets_al)
    al = dict(note="对齐 T-278(S-757 下架)口径:scan(T251.D_FROM → T251.D_TO),"
                   "整本账本(不过滤窗口)= T-278 报告的 145 张 / 54.3331;"
                   f"台账窗口 {A_FROM} → {A_TO} 另给一份子账本",
             scan_window=f"{T251.D_FROM} → {T251.D_TO}",
             baseline=dict(full_n=len(al_base_full),
                           full_sum_r=round(sum(t["r"] for t in al_base_full), 4),
                           full_tickets_r=[round(t["r"], 6) for t in al_base_full],
                           window_n=len(al_base),
                           window_sum_r=round(sum(t["r"] for t in al_base), 4),
                           window_tickets_r=[round(t["r"], 6) for t in al_base]))
    print(f"对齐 T-278:整本 {len(al_base_full)} 张 / {al['baseline']['full_sum_r']} "
          f"(T-278 报告 145 / 54.3331) | 窗口子账本 {len(al_base)} / "
          f"{al['baseline']['window_sum_r']}", file=sys.stderr)
    for tag, tl in (("row", tl_row), ("sentence", tl_sent)):
        c1, c2 = classify_split(tickets_al, tl, plan_field="signal_d")
        tk, _ = T278.apply_rule(tickets_al, bars, c1, c2)
        sim = T251.simulate(tk, bars, gate, CAP_FRAC)
        full = T278.ledger(sim, tk)
        sl = sub_led_aligned(sim, tk)
        base_ids = {t["tid"] for t in al_base}
        dropped = [t for t in al_base if t["tid"] not in {x["tid"] for x in sl}]
        al[tag] = dict(class1_n=len(c1), class2_n=len(c2),
                       full_n=len(full), full_sum_r=round(sum(t["r"] for t in full), 4),
                       full_delta=round(sum(t["r"] for t in full)
                                        - sum(t["r"] for t in al_base_full), 4),
                       window_n=len(sl), window_sum_r=round(sum(t["r"] for t in sl), 4),
                       window_delta=round(sum(t["r"] for t in sl)
                                         - sum(t["r"] for t in al_base), 4),
                       dropped_ledger_n=len(dropped),
                       dropped_ledger_r=round(sum(t["r"] for t in dropped), 4),
                       full_tickets_r=[round(t["r"], 6) for t in full],
                       window_tickets_r=[round(t["r"], 6) for t in sl])
        print(f"对齐 · 名单 {tag}: class1 {len(c1)} class2 {len(c2)} | 整本 {len(full)} / "
              f"{al[tag]['full_sum_r']} Δ{al[tag]['full_delta']} | 窗口子账本 {len(sl)} / "
              f"{al[tag]['window_sum_r']} Δ{al[tag]['window_delta']} 账内被挡 {len(dropped)}",
              file=sys.stderr)
    # 下架规则(交叉验证:同一口径下应与 T-278 逐位相同 —— 0 bites)
    try:
        table, all_ann, dmeta = T278.load_delist()
        dl_c1, dl_c2 = T278.classify(tickets_al, table, all_ann, plan_field="signal_d",
                                     window_closed=True)
        tk_dl, _ = T278.apply_rule(tickets_al, bars, dl_c1, dl_c2)
        sim_dl = T251.simulate(tk_dl, bars, gate, CAP_FRAC)
        full_dl = T278.ledger(sim_dl, tk_dl)
        al["delist_only"] = dict(class1_n=len(dl_c1), class2_n=len(dl_c2),
                                 full_n=len(full_dl),
                                 full_sum_r=round(sum(t["r"] for t in full_dl), 4),
                                 full_delta=round(sum(t["r"] for t in full_dl)
                                                   - sum(t["r"] for t in al_base_full), 4))
        print(f"对齐 · 下架规则(S-757):整本 {len(full_dl)} / {al['delist_only']['full_sum_r']} "
              f"Δ{al['delist_only']['full_delta']}(T-278:145 / 54.3331 / Δ0)", file=sys.stderr)
    except Exception as e:                       # 名单读不到就跳过,不影响其它数
        al["delist_only"] = dict(error=f"{type(e).__name__}: {str(e)[:120]}")
        print("下架名单 ERR", type(e).__name__, str(e)[:120], file=sys.stderr)
    res["book_T278_aligned"] = al

    json.dump(res, open(OUT_JSON, "w"), indent=1, ensure_ascii=False, default=str)
    print("→", OUT_JSON.name, f"({time.time()-t0:.0f}s)", file=sys.stderr)
    return res


# ── 阶段 4:零信号基线(亏损占比 + 随机挡 N 张的期望与零分布分位)───────────────
def null_baseline(rs, k, actual_delta, seed=SEED, n=N_NULL):
    """rs = 账本票的 R 列表;k = 规则实际挡掉的账内票数。
    零分布:随机挡 k 张 ⇒ ΔR = −(被挡票 R 之和);返回期望 / 分位。"""
    import numpy as np
    rs = [float(x) for x in rs]
    n_t = len(rs)
    if n_t == 0 or k <= 0 or k > n_t:
        return dict(n=n_t, k=k, note="k 不可用", loss_pct=None, null_mean=None, percentile=None)
    arr = np.array(rs, dtype=float)

    def fn(rng):
        idx = rng.choice(n_t, size=k, replace=False)
        return -float(arr[idx].sum())

    null = AP.null_distribution(fn, n, seed, actual=actual_delta)
    return dict(
        n=n_t, k=k,
        loss_pct=round(100.0 * float((arr < 0).sum()) / n_t, 2),
        win_pct=round(100.0 * float((arr > 0).sum()) / n_t, 2),
        sum_r=round(float(arr.sum()), 4),
        mean_r=round(float(arr.mean()), 4),
        expected_delta_random_block=round(-k * float(arr.mean()), 4),
        null_mean=round(float(null.mean()), 4),
        null_std=round(float(null.std()), 4),
        actual_delta=(round(actual_delta, 4) if actual_delta is not None else None),
        percentile=AP.percentile_of(actual_delta, null),
        note="零分布 = 随机挡 k 张票的组合式期望(不重跑模拟,不释放持仓名额);"
             "实际值 = 规则版的 ΔR(整账本口径,含腾出名额换进别的票)",
    )


def phase_null():
    res = json.load(open(OUT_JSON))
    out = dict(task="T-308", stage="null", generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
               n_null=N_NULL, seed=SEED, groups={})
    # 组 1:口径 A 窗口独立起账(155 张)
    a = res["book_A"]
    out["groups"]["book_A_window"] = dict(
        n=len(a["baseline_tickets_r"]),
        row=null_baseline(a["baseline_tickets_r"], a["row"]["dropped_ledger_n"],
                          a["row"]["delta_sum_r"]),
        sentence=null_baseline(a["baseline_tickets_r"], a["sentence"]["dropped_ledger_n"],
                               a["sentence"]["delta_sum_r"]))
    # 组 2:口径 B 窗口子账本(67 张)
    b = res["book_B"]
    out["groups"]["book_B_window"] = dict(
        n=b["baseline"]["window_n"],
        row=null_baseline(b["baseline"]["tickets_r"], b["row"]["dropped_ledger_n"],
                          b["row"]["window_sum_r"] - b["baseline"]["window_sum_r"]),
        sentence=null_baseline(b["baseline"]["tickets_r"], b["sentence"]["dropped_ledger_n"],
                               b["sentence"]["window_sum_r"] - b["baseline"]["window_sum_r"]))
    # 组 3:对齐 T-278 窗口(145 张)
    c = res.get("book_T278_aligned") or {}
    if c.get("baseline"):
        out["groups"]["aligned_T278_window"] = dict(
            n=c["baseline"]["window_n"],
            row=null_baseline(c["baseline"]["tickets_r"], c.get("row", {}).get("dropped_ledger_n"),
                              c.get("row", {}).get("delta_sum_r")),
            sentence=null_baseline(c["baseline"]["tickets_r"],
                                   c.get("sentence", {}).get("dropped_ledger_n"),
                                   c.get("sentence", {}).get("delta_sum_r")))
    res["null_baseline"] = out
    json.dump(res, open(OUT_JSON, "w"), indent=1, ensure_ascii=False, default=str)
    for g, v in out["groups"].items():
        for tag in ("row", "sentence"):
            x = v.get(tag) or {}
            print(f"{g} · {tag}: n={x.get('n')} k={x.get('k')} 亏损占比 {x.get('loss_pct')}% "
                  f"随机挡期望 ΔR {x.get('expected_delta_random_block')} "
                  f"实际 ΔR {x.get('actual_delta')} 零分布分位 {x.get('percentile')}",
                  file=sys.stderr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", nargs="?", default="all",
                    choices=["raw", "split", "book", "null", "all"])
    a = ap.parse_args()
    if a.stage in ("raw", "all"):
        phase_raw()
    if a.stage in ("split", "all"):
        phase_split()
    if a.stage in ("book", "all"):
        phase_book()
    if a.stage in ("null", "all"):
        print("阶段 null 还没实现", file=sys.stderr)


if __name__ == "__main__":
    main()
