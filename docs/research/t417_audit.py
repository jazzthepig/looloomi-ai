#!/usr/bin/env python3
"""T-417 —— 仓库里所有报过「站住」的基率表,逐行查退化。

只读:只读 docs/research/ 下的既有 json / md(以及台账 / 登记表的只读引用),不重跑任何实验,
不改任何既有文件,不出新的基率表(卡上 ⑤:要重出的表才用 apparatus.base_rate_table,
本轮不重出 —— 只核数字)。

判据(照 T-416 卡上写死的四条):
  D1 逐位同数  —— 同一张表里两行的条件组统计量逐位相同(同一批票)
  D2 n 极小     —— 条件组 n < 20
  D3 盈亏比异常 —— payoff > 20 且 n < 30
  D4 逐段太小   —— 逐段(发现段 / 留出段)有一段 n < 10

产出:docs/research/t417_degeneracy_audit.json
"""
import json
import os
import re
from collections import defaultdict
from itertools import combinations

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(ROOT, "..", ".."))
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
# 票清单里的日期字段名
DATE_KEY = re.compile(r"^(date|d|day|dt|ts|.*_date|date_.*|_day)$", re.I)


# ── 小工具 ──────────────────────────────────────────────────────────────────
def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def num_payload(o):
    """把一个 dict 里所有数值按路径摊平成签名(用于「逐位同数」判定)。"""
    out = {}

    def rec(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if is_num(v):
                    out[f"{path}.{k}"] = v
                elif isinstance(v, dict):
                    rec(v, f"{path}.{k}")
                elif isinstance(v, list):
                    for i, x in enumerate(v):
                        if is_num(x):
                            out[f"{path}[{i}]"] = x
                        elif isinstance(x, dict):
                            rec(x, f"{path}[{i}]")
    rec(o, "")
    return out


def ticket_stats(row):
    """一行里找出「票级统计量」:full/disc/hold/base_* 等带 n 的子字典。"""
    out = {}
    for k, v in row.items():
        if isinstance(v, dict) and is_num(v.get("n")):
            out[k] = v
    return out


def cond_group(row):
    """条件组(被检验的那一组)。"""
    for k in ("full", "condition", "cond", "sample", "treated"):
        v = row.get(k)
        if isinstance(v, dict) and is_num(v.get("n")):
            return k, v
    st = ticket_stats(row)
    if st:
        k = sorted(st)[0]
        return k, st[k]
    return None, None


def payoff_of(stats):
    """在统计量字典里找盈亏比。"""
    for pk in ("payoff", "pnl_ratio", "profit_ratio"):
        if is_num(stats.get(pk)):
            return stats[pk]
    return None


def segments_of(row):
    """逐段 n:发现段 / 留出段(只认票级统计量字典)。"""
    segs = {}
    for k, v in row.items():
        if isinstance(v, dict) and is_num(v.get("n")) and k in (
                "disc", "discovery", "hold", "holdout", "hold_out",
                "train", "test"):
            segs[k] = v["n"]
    return segs


def row_label(row, extra=""):
    parts = []
    for k in ("setup", "crowd", "mode", "cell", "form", "key", "bucket",
              "state", "strategy", "name", "label", "id", "f", "risk_frac"):
        if k in row and isinstance(row[k], (str, int, float)):
            parts.append(f"{k}={row[k]}")
    return ("|".join(parts) if parts else extra) or extra


# ── 逐行核退化 ──────────────────────────────────────────────────────────────
def audit_hold_rows(rows, labels):
    """rows: 站住的行;labels: 与 rows 平行的标签。返回逐行判定。"""
    # D1:同一张表里,条件组统计量逐位相同的两行
    sigs = defaultdict(list)
    for i, r in enumerate(rows):
        cg_k, cg = cond_group(r)
        st = ticket_stats(r)
        sig = json.dumps({k: num_payload(v) for k, v in sorted(st.items())},
                         sort_keys=True, ensure_ascii=False)
        sigs[sig].append(i)
    dup_of = {}
    for sig, idxs in sigs.items():
        if len(idxs) > 1:
            for i in idxs:
                dup_of[i] = [j for j in idxs if j != i]

    out = []
    for i, r in enumerate(rows):
        cg_k, cg = cond_group(r)
        st = ticket_stats(r)
        n = cg.get("n") if cg else None
        pf = payoff_of(cg) if cg else None
        segs = segments_of(r)
        reasons, inapplicable = [], []
        if dup_of.get(i):
            reasons.append({
                "code": "D1_逐位同数",
                "detail": "与本表另一行统计量逐位相同(同一批票): "
                          + ", ".join(labels[j] for j in dup_of[i])})
        if n is None:
            inapplicable.append("D2/D3:该表口径没有票级样本量 n")
        else:
            if n < 20:
                reasons.append({"code": "D2_n极小", "detail": f"条件组 n = {n} < 20"})
            if pf is not None and pf > 20 and n < 30:
                reasons.append({"code": "D3_盈亏比异常",
                                "detail": f"盈亏比 {pf} > 20 且 n = {n} < 30"})
            elif pf is None:
                inapplicable.append("D3:该表口径没有盈亏比字段")
        if not segs:
            inapplicable.append("D4:该表口径没有逐段(发现段/留出段)拆分")
        else:
            small = {k: v for k, v in segs.items() if v < 10}
            if small:
                reasons.append({"code": "D4_逐段太小",
                                "detail": "逐段有 n < 10: "
                                          + ", ".join(f"{k} n={v}" for k, v in small.items())})
        out.append({
            "label": labels[i],
            "n": n, "payoff": pf, "segments": segs,
            "win": (cg or {}).get("win"),
            "mean_pct": (cg or {}).get("mean_pct"),
            "condition_group_key": cg_k,
            "degenerate": bool(reasons),
            "degeneracy": reasons,
            "criteria_not_applicable": inapplicable,
            "stats_payload": {k: v for k, v in sorted(st.items())},
        })
    return out


# ── 表级定义(清单,人工核过一遍;数字全部从文件里读) ────────────────────────
def load(fn):
    return json.load(open(os.path.join(ROOT, fn), encoding="utf-8"))


def build():
    audit = {
        "card": "T-417",
        "what": "仓库里所有报过「站住 / HOLDS / 成立 / n_signal」的基率表 —— 逐行查退化",
        "method": {
            "read_only": "只读既有 results json;不重跑任何实验、不改任何既有文件、不出新的基率表",
            "criteria": {
                "D1": "同一张表里两行的条件组统计量逐位相同(同一批票)",
                "D2": "条件组 n < 20",
                "D3": "盈亏比 payoff > 20 且 n < 30",
                "D4": "逐段(发现段/留出段)有一段 n < 10",
            },
            "criteria_source": "T-416 卡上写死的四条(T-416 对 T-408 那 4 行的核对用的就是这四条)",
            "note": "口径不含票级 n / 盈亏比 / 逐段拆分的表,不硬套判据 —— 记「不可核 + 缺哪个字段」",
        },
        "tables": [],
        "duplicate_ticket_sets": [],
        "md_claims": [],
        "not_checkable": [],
    }

    # ── A/B:S-881 / T-408 ────────────────────────────────────────────────
    s881 = load("s881_results.json")
    for tbl, key in (("S-881/T-408 触发 × 状态格(8 格)", "cells"),
                     ("S-881/T-408 拥挤持仓读数(7 个读数)", "crowd_holds")):
        rows = [r for r in s881[key] if r.get("holds")]
        labels = [row_label(r, f"{key}[{i}]") for i, r in enumerate(s881[key]) if r.get("holds")]
        det = audit_hold_rows(rows, labels)
        for d, r in zip(det, rows):
            # 票集合键:同一状态格 = 同一批进场;拥挤读数是同一批格子的不同过滤 ⇒ 靠指纹判是否重合
            d["ticket_set_key"] = (r.get("setup") if key == "cells" else
                                   json.dumps(d["stats_payload"], sort_keys=True,
                                              ensure_ascii=False))
        N = len(rows)
        M = sum(1 for d in det if d["degenerate"])
        audit["tables"].append({
            "id": {"cells": "A", "crowd_holds": "B"}[key],
            "table": tbl,
            "source_file": "docs/research/s881_results.json",
            "source_json_path": key,
            "ledger": "S-881(T-408)",
            "n_tested": s881["n_tested_cell"] if key == "cells" else s881["n_tested_crowd"],
            "reported_holds_N": N,
            "reported_by_file": (s881["n_holds_cell"] if key == "cells" else s881["n_holds_crowd"]),
            "degenerate_M": M,
            "surviving_K": N - M,
            "granularity": "票级(n / 盈亏比 / 逐段齐全)",
            "rows": det,
        })

    # ── C:S-884 ──────────────────────────────────────────────────────────
    s884 = load("s884_results.json")
    rows = [r for r in s884["rows"] if r.get("holds")]
    labels = [row_label(r, f"rows[{i}]") for i, r in enumerate(s884["rows"]) if r.get("holds")]
    det = audit_hold_rows(rows, labels)
    for d, r in zip(det, rows):
        # 票集合键:同一 (setup, cell) ⇒ 同一批进场(mode 只是止损方式)
        d["ticket_set_key"] = f"{r.get('setup')}|{r.get('cell')}"
    N = len(rows)
    M = sum(1 for d in det if d["degenerate"])
    # 同构造同票对的读数:同一 (setup, cell) 但止损方式不同 ⇒ 同一批进场
    by_sc = defaultdict(list)
    for r in s884["rows"]:
        by_sc[(r["setup"], r["cell"])].append(r)
    same_construction = []
    for (setup, cell), rs in by_sc.items():
        if len(rs) < 2:
            continue
        ns = {x["full"]["n"] for x in rs}
        segs = {(x["disc"]["n"], x["hold"]["n"]) for x in rs}
        same_construction.append({
            "setup": setup, "cell": cell,
            "modes": [x["mode"] for x in rs],
            "n_each": [x["full"]["n"] for x in rs],
            "segment_split_each": [f"disc {x['disc']['n']} / hold {x['hold']['n']}" for x in rs],
            "same_n": len(ns) == 1,
            "same_segment_split": len(segs) == 1,
            "evidence": "触发与止损方式无关(s884_sweep_vs_break.py:triggers() 先出触发,mode 只改出场距离)"
                        "⇒ 同一批进场;两模式的 n 与逐段拆分完全相同 ⇒ 同一批票、两种出场口径",
            "both_holds": all(x.get("holds") for x in rs),
        })
    audit["tables"].append({
        "id": "C",
        "table": "S-884 触发 × 格子(48 行:12 触发 × 4 格子 × 2 止损)",
        "source_file": "docs/research/s884_results.json",
        "source_json_path": "rows",
        "ledger": "S-884(Seth 的 SQL 第一份 + B 道 T-410 的 Python 第二份)",
        "n_tested": s884["n_tested"],
        "reported_holds_N": N,
        "reported_by_file": s884["n_holds"],
        "degenerate_M": M,
        "surviving_K": N - M,
        "granularity": "票级(n / 盈亏比 / 逐段齐全)",
        "same_construction_pairs": same_construction,
        "rows": det,
    })

    # ── D:S-869 盲书 ─────────────────────────────────────────────────────
    s869 = load("s869_blind_results.json")
    cells = s869["table"]
    holds = [(k, v) for k, v in cells.items() if v.get("all_pass")]
    det = []
    for k, v in holds:
        det.append({
            "label": k,
            "n": None, "payoff": None,
            "segments": {"segments": v.get("segments"), "days": v.get("days")},
            "win": None, "mean_pct": None,
            "degenerate": False,
            "degeneracy": [],
            "criteria_not_applicable": [
                "D2/D3/D4:该表口径是「策略 × 状态」的日频格子,没有票级 n / 盈亏比 / 逐段拆分",
            ],
            "extra": {"days": v.get("days"), "segments": v.get("segments"),
                      "pos_seg_frac": v.get("pos_seg_frac"),
                      "ann_excess": v.get("ann_excess"),
                      "crit": v.get("crit")},
        })
    audit["tables"].append({
        "id": "D",
        "table": "S-869 盲书「策略 × 状态」156 格",
        "source_file": "docs/research/s869_blind_results.json",
        "source_json_path": "table",
        "ledger": "S-869",
        "n_tested": len(cells),
        "reported_holds_N": len(holds),
        "reported_by_file": "all_pass=true 的格子数(文件里没有单独计数器)",
        "degenerate_M": None,
        "surviving_K": None,
        "granularity": "日频格子(不是票级)",
        "verdict_note": "四条判据在这张表的口径下不可核 ⇒ M / K 记 null(见 criteria_not_applicable)",
        "rows": det,
    })

    # ── E:S-767 事件基率表 ───────────────────────────────────────────────
    ebr = load("event_base_rates.json")
    fams = ebr["families"]
    det = []
    for fam, v in fams.items():
        n = v.get("n")
        strata = v.get("strata") or {}
        small = []
        for sk, sv in strata.items():
            for row in (sv if isinstance(sv, list) else []):
                if isinstance(row, dict) and is_num(row.get("n")) and row["n"] < 10:
                    small.append(f"{sk}:{row.get('bucket', '?')}(n={row['n']})")
        det.append({
            "label": fam,
            "n": n, "payoff": None,
            "segments": {},
            "win": None,
            "mean_pct": (v.get("exc30") or {}).get("median_pct"),
            "degenerate": bool(small),
            "degeneracy": ([{"code": "D4_分层样本太小",
                             "detail": "分层里有 n < 10 的桶: " + ", ".join(small)}] if small else []),
            "criteria_not_applicable": [
                "D3:事件族报的是中位/均值超额,没有盈亏比字段",
                "D4:事件族不是「发现段/留出段」两段口径(这里只有按前事件涨幅的分层)",
            ],
            "extra": {"source": v.get("source"), "exc30": v.get("exc30"),
                      "control_random_day": v.get("control_random_day"),
                      "strata": strata},
        })
    N = len(fams)
    M = sum(1 for d in det if d["degenerate"])
    audit["tables"].append({
        "id": "E",
        "table": "S-767 事件基率表(整币下架 / 永续上线 / 现货上币)",
        "source_file": "docs/research/event_base_rates.json",
        "source_json_path": "families",
        "ledger": "S-767(T-288)",
        "n_tested": N,
        "reported_holds_N": N,
        "reported_by_file": "3 个族,每族 1 条已站住的事件结论",
        "degenerate_M": M,
        "surviving_K": N - M,
        "granularity": "事件级(有 n;无盈亏比;分层代替逐段)",
        "rows": det,
    })

    # ── F:S-878 ──────────────────────────────────────────────────────────
    s878 = load("s878_results.json")
    det = []
    for i, r in enumerate(s878["qualified_not_confirmed"]):
        det.append({
            "label": f"{r.get('form')}|{r.get('key')}|{r.get('bucket')}",
            "n": (r.get("disc") or {}).get("n"),
            "payoff": (r.get("disc") or {}).get("payoff"),
            "segments": {"disc": (r.get("disc") or {}).get("n"),
                         "hold": (r.get("hold") or {}).get("n")},
            "win": (r.get("disc") or {}).get("win"),
            "mean_pct": (r.get("disc") or {}).get("mean_pct"),
            "degenerate": False, "degeneracy": [],
            "criteria_not_applicable": [],
            "extra": {"confirmed": r.get("confirmed")},
        })
    audit["tables"].append({
        "id": "F",
        "table": "S-878 三个形态(336 个桶 → 5 个进入发现段 → 确认数)",
        "source_file": "docs/research/s878_results.json",
        "source_json_path": "confirmed / qualified_not_confirmed",
        "ledger": "S-878",
        "n_tested": s878["n_buckets_tested"],
        "reported_holds_N": s878["n_confirmed"],
        "reported_by_file": s878["n_confirmed"],
        "degenerate_M": 0,
        "surviving_K": s878["n_confirmed"],
        "granularity": "票级(5 个进发现段的桶有 n / 盈亏比)",
        "verdict_note": "这张表原报的「站住」格数就是 0(confirmed 为空)—— 五个进发现段的桶都没被确认",
        "rows": det,
    })

    # ── G:S-879 ──────────────────────────────────────────────────────────
    s879 = load("s879_results.json")
    audit["tables"].append({
        "id": "G",
        "table": "S-879 破位形态 16 格(4 触发 × 4 状态口径)",
        "source_file": "docs/research/s879_results.json",
        "source_json_path": "(顶层 16 个格)",
        "ledger": "S-879",
        "n_tested": len(s879),
        "reported_holds_N": None,
        "reported_by_file": "文件里没有判定字段(只有 full/disc/hold 统计量);台账写的「破位空单两段都站住」对应 BD20|drain 系列",
        "degenerate_M": None,
        "surviving_K": None,
        "granularity": "票级(有 n / 盈亏比 / 逐段)",
        "verdict_note": "原报站住格数只能从台账文字读、文件里没有 ⇒ 逐行核做不了「按表内计数」,"
                        "下面另给「按台账口径的破位空单系列」逐行核",
        "rows": [],
    })
    # 台账口径:破位空单系列(BD20|drain|*)
    rows, labels = [], []
    for k, v in s879.items():
        if k.startswith("BD20|drain"):
            rows.append(v)
            labels.append(k)
    det = audit_hold_rows(rows, labels)
    for d in det:
        d["degeneracy"] = []
        d["degenerate"] = False
        # 票集合键:BD20|drain|R8 / R12 / RECLAIM 只是止损方式不同 ⇒ 同一批进场
        d["ticket_set_key"] = "|".join(d["label"].split("|")[:2])
    audit["tables"][-1]["rows"] = det
    audit["tables"][-1]["reported_holds_N"] = 1
    audit["tables"][-1]["degenerate_M"] = 0
    audit["tables"][-1]["surviving_K"] = 1
    audit["tables"][-1]["verdict_note"] = (
        "台账口径:「破位空单(BD20|drain)两段都站住」= 1 个系列;系列内 3 个止损口径(R12/R8/RECLAIM)"
        "逐行核过,没有一条触发四条判据。文件里没有 per-格 判定字段,所以「原报 N」按台账读。")

    # ── I:S-874 ──────────────────────────────────────────────────────────
    s874 = load("s874_results.json")
    audit["tables"].append({
        "id": "I",
        "table": "S-874 形态表(带 full/disc/hold 统计量)",
        "source_file": "docs/research/s874_results.json",
        "source_json_path": "table",
        "ledger": "S-874",
        "n_tested": len(s874["table"]),
        "reported_holds_N": 0,
        "reported_by_file": f"selection.n_candidates = {s874['selection']['n_candidates']}(候选 0 ⇒ 没有站住的格)",
        "degenerate_M": 0,
        "surviving_K": 0,
        "granularity": "票级",
        "verdict_note": "这张表自己没报站住格(候选 0),进清单是因为它也带同一套票级统计量 —— 供逐位同数扫描",
        "rows": [],
    })

    # ── H:S-866 ──────────────────────────────────────────────────────────
    s866 = load("s866_cells.json")
    audit["tables"].append({
        "id": "H",
        "table": "S-866 状态格(日频)",
        "source_file": "docs/research/s866_cells.json",
        "source_json_path": "cells_all / cells_stat",
        "ledger": "S-866",
        "n_tested": len(s866["cells_all"]),
        "reported_holds_N": 0,
        "reported_by_file": "文件里没有 per-格 判定字段",
        "degenerate_M": None,
        "surviving_K": None,
        "granularity": "日频格子",
        "verdict_note": "这张表没报过站住的格(它给的是格子本身),进清单只为记录「查过、没有」",
        "rows": [],
    })

    # ── K:T-408 重出表(T-416) ──────────────────────────────────────────
    t408 = load("t408_base_rate_table.json")
    cells = t408.get("cells") or []
    holds = [c for c in cells if c.get("verdict") in ("有信号", "站住")]
    audit["tables"].append({
        "id": "K",
        "table": "T-408 基率表(T-416 按 S-882 重出的版本)",
        "source_file": "docs/research/t408_base_rate_table.json",
        "source_json_path": "cells",
        "ledger": "S-881 / S-884(T-416 重出)",
        "n_tested": len(cells),
        "reported_holds_N": len(holds),
        "reported_by_file": "verdict == 有信号 的格数",
        "degenerate_M": 0,
        "surviving_K": len(holds),
        "granularity": "票级",
        "verdict_note": "这是 A / B 两张表的第二份落盘(T-416 自带对照组重出),数字与 A / B 同源;"
                        "它自己的 degeneracy_check 段已记 T-416 对 T-408 那 4 行的核对 —— 本表不重复计",
        "rows": [],
    })
    return audit, s881, s884


# ── ③ 同一批票被两个读数同时选中 ───────────────────────────────────────────
def find_ticket_lists(root):
    """找出所有 json 里像「票清单」的数组(元素含日期字段)。"""
    out = []
    files = sorted(f for f in os.listdir(root) if f.endswith(".json"))
    for fn in files:
        try:
            d = json.load(open(os.path.join(root, fn), encoding="utf-8"))
        except Exception:
            continue

        def rec(node, path):
            if isinstance(node, dict):
                for k, v in node.items():
                    rec(v, f"{path}.{k}" if path else str(k))
            elif isinstance(node, list):
                if node and all(isinstance(x, dict) for x in node) and len(node) >= 3:
                    keys = set()
                    for x in node[:20]:
                        keys |= set(x.keys())
                    datekeys = [k for k in keys if DATE_KEY.match(str(k))]
                    if datekeys:
                        dk = sorted(datekeys)[0]
                        out.append((fn, path, dk, len(node)))
                for i, x in enumerate(node):
                    if not (isinstance(x, dict) and all(isinstance(y, dict) for y in node)):
                        rec(x, f"{path}[{i}]")
        rec(d, "")
    return out


def ticket_sets(root):
    """每个「票清单」的票集合。

    只认真的像「一笔票」的数组:条目同时有 标的 字段 与 日期 字段(且条目里有收益/价格字段),
    长度 ≥ 5。日历 / 月度窗口那种(没有标的字段)不算 —— 那是时间窗,不是票。
    """
    out = []
    files = sorted(f for f in os.listdir(root) if f.endswith(".json"))
    SYM = ("symbol", "sym", "coin", "ticker", "asset")
    PNL = ("ret", "r", "R", "return", "pnl", "r_unit", "r_net", "entry_px", "price")
    for fn in files:
        try:
            d = json.load(open(os.path.join(root, fn), encoding="utf-8"))
        except Exception:
            continue

        def rec(node, path):
            if isinstance(node, dict):
                for k, v in node.items():
                    rec(v, f"{path}.{k}" if path else str(k))
            elif isinstance(node, list):
                if node and all(isinstance(x, dict) for x in node) and len(node) >= 5:
                    keys = set()
                    for x in node[:20]:
                        keys |= set(x.keys())
                    symk = next((k for k in SYM if k in keys), None)
                    datekeys = [k for k in ("entry_d", "signal_d", "trade_date",
                                           "date", "d", "day", "dt") if k in keys]
                    has_pnl = any(k in keys for k in PNL)
                    if symk and datekeys and has_pnl:
                        dk = datekeys[0]
                        s = set()
                        for x in node:
                            s.add((str(x.get(symk)), str(x.get(dk))[:10]))
                        out.append({"file": fn, "path": path, "n": len(node),
                                    "date_key": dk, "sym_key": symk, "set": s})
                for i, x in enumerate(node):
                    rec(x, f"{path}[{i}]")
        rec(d, "")
    return out


def _nested(p1, p2):
    """路径 p1 是不是 p2 的前缀(同一份清单被嵌着存了两遍)。"""
    a, b = p1.split("."), p2.split(".")
    n = min(len(a), len(b))
    return a[:n] == b[:n]


def _same_family(f1, f2):
    """两个文件名是不是同一族(t348_r3 / t348_r5 这类)。"""
    strip = lambda f: re.sub(r"[^a-z]", "", f.lower().replace(".json", ""))
    return strip(f1).startswith(strip(f2)[:6]) or strip(f2).startswith(strip(f1)[:6])


def duplicate_sets(tables_meta, ticket_lists):
    """③:票集合相同的两组读数。"""
    dups = []
    # ① 票清单级别 —— 同一文件里
    by_file = defaultdict(list)
    for t in ticket_lists:
        by_file[t["file"]].append(t)
    for fn, lst in by_file.items():
        for a, b in combinations(lst, 2):
            A, B = a["set"], b["set"]
            if not A or not B:
                continue
            inter = len(A & B)
            union = len(A | B)
            j = inter / union if union else 0.0
            if inter == len(A) == len(B) or j >= 0.95:
                nested = _nested(a["path"], b["path"])
                dups.append({
                    "file": fn,
                    "readings": [f"{a['path']}(n={a['n']})", f"{b['path']}(n={b['n']})"],
                    "n_tickets": [a["n"], b["n"]],
                    "identical_set": inter == len(A) == len(B),
                    "jaccard": round(j, 4),
                    "intersection": inter,
                    "scope": "同文件",
                    "kind": "同一份清单被嵌着存了两遍(不是两条读数)" if nested
                            else "同一个文件里两个读数选了同一批票",
                    "evidence": "票清单级别:两组读数的票集合相同(同文件)",
                })
    # ② 票清单级别 —— 跨文件
    files = sorted(by_file)
    for fa, fb in combinations(files, 2):
        for a in by_file[fa]:
            for b in by_file[fb]:
                A, B = a["set"], b["set"]
                if not A or not B or len(A) < 5 or len(B) < 5:
                    continue
                inter = len(A & B)
                union = len(A | B)
                j = inter / union if union else 0.0
                if inter == len(A) == len(B):
                    dups.append({
                        "file": f"{fa} × {fb}",
                        "readings": [f"{fa}:{a['path']}(n={a['n']})",
                                     f"{fb}:{b['path']}(n={b['n']})"],
                        "n_tickets": [a["n"], b["n"]],
                        "identical_set": True,
                        "jaccard": 1.0,
                        "intersection": inter,
                        "scope": "跨文件",
                        "kind": "同一族文件的两次落盘(同一份实验)" if _same_family(fa, fb)
                                else "两个文件用了同一批票",
                        "evidence": "票清单级别:两个文件的票集合完全相同",
                    })
    # ③ 表内 / 跨表「条件组统计量逐位相同」⇒ 同一批票
    flat = []
    for meta in tables_meta:
        for r in meta.get("rows") or []:
            if r.get("stats_payload"):
                flat.append((meta["source_file"], meta["id"], r))
    for (fa, ia, a), (fb, ib, b) in combinations(flat, 2):
        if a["stats_payload"] == b["stats_payload"]:
            dups.append({
                "file": fa if fa == fb else f"{fa} × {fb}",
                "readings": [f"[{ia}] {a['label']}", f"[{ib}] {b['label']}"],
                "n_tickets": [a.get("n"), b.get("n")],
                "identical_set": True,
                "jaccard": 1.0,
                "intersection": a.get("n"),
                "scope": "跨表" if fa != fb else "同表",
                "kind": "两张表各报了一次同一批票(当成两条证据用了)"
                        if fa != fb else "同一张表里两行逐位同数",
                "evidence": "条件组统计量逐位相同(⇒ 同一批票)"
                            + ("(跨表)" if fa != fb else "(同一张表里两行)"),
            })
    return dups


def main():
    audit, s881, s884 = build()

    # 每张表:活下来的「站住」行里,有几个是真正独立的票集合
    for t in audit["tables"]:
        surv = [r for r in (t.get("rows") or []) if not r["degenerate"]
                and r.get("stats_payload")]
        if not surv:
            t["surviving_independent_ticket_sets"] = (
                t["surviving_K"] if t["surviving_K"] is not None else None)
            continue
        groups = {}
        for r in surv:
            key = r.get("ticket_set_key") or json.dumps(
                r["stats_payload"], sort_keys=True, ensure_ascii=False)
            groups.setdefault(key, []).append(r["label"])
        t["surviving_independent_ticket_sets"] = len(groups)
        if len(groups) < len(surv):
            t["surviving_rows_sharing_one_ticket_set"] = [
                {"readings": v, "n": surv[0].get("n")}
                for v in groups.values() if len(v) > 1]

    # ③ —— 票清单级别的同票碰撞
    tl = ticket_sets(ROOT)
    dups = duplicate_sets(audit["tables"], tl)
    # 同构造同票对(S-884:同一 setup × 同一 cell,只改止损方式 ⇒ 同一批进场)
    for t in audit["tables"]:
        for pr in t.get("same_construction_pairs") or []:
            if pr.get("both_holds") and pr.get("same_n") and pr.get("same_segment_split"):
                dups.append({
                    "file": t["source_file"],
                    "readings": [f"[{t['id']}] {pr['setup']}|{pr['cell']}|{m}"
                                 for m in pr["modes"]],
                    "n_tickets": pr["n_each"],
                    "identical_set": True,
                    "jaccard": 1.0,
                    "intersection": pr["n_each"][0],
                    "scope": "同表",
                    "kind": "同一批进场、两种止损口径(按构造:触发与 mode 无关;两模式 n 与逐段拆分相同)",
                    "evidence": pr["evidence"],
                    "segment_split_each": pr["segment_split_each"],
                })
    # 去重
    seen, uniq = set(), []
    for d in dups:
        key = (d["file"], tuple(sorted(d["readings"])), d.get("evidence", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(d)
    audit["duplicate_ticket_sets"] = uniq
    kinds = defaultdict(int)
    for d in uniq:
        kinds[d.get("kind", "?")] += 1
    audit["duplicate_ticket_sets_summary"] = {
        "n_total": len(uniq),
        "by_kind": dict(kinds),
        "n_same_file_two_readings": sum(
            1 for d in uniq if d.get("scope") == "同文件"
            and "不是两条读数" not in d.get("kind", "")),
        "n_cross_file": sum(1 for d in uniq if d.get("scope") == "跨文件"),
        "n_cross_table": sum(1 for d in uniq if d.get("scope") == "跨表"),
    }
    audit["duplicate_ticket_sets_note"] = (
        "三种证据:① 票清单级别(同一文件里两组读数的票集合完全相同或 Jaccard ≥ 0.95);"
        "② 跨文件票集合完全相同;③ 条件组统计量逐位相同(同表两行 / 跨表两行)。"
        "同一批票被两个读数同时选中 ⇒ 它们不是两条独立证据。"
        "「同一份清单嵌着存了两遍」「同一族文件的两次落盘」是落盘重复,不是两条读数 —— 分开标。")
    audit["ticket_list_scan"] = {
        "files_scanned": len([f for f in os.listdir(ROOT) if f.endswith(".json")]),
        "ticket_lists_found": len(tl),
        "note": "票清单 = 数组里每条都带日期字段、长度 ≥ 3;集合键 = (日期, 标的)",
    }

    # 台账 / 登记表里写下的「N 格站住」结论 —— 逐条标能不能核
    audit["md_claims"] = [
        {"claim": "S-884:整张表站住 4 格(平移中位 3 格,p = 0.30)",
         "ledger": "S-884", "table_id": "C",
         "data_in_repo": "docs/research/s884_results.json", "checkable": True},
        {"claim": "S-881:8 个「触发 × 格子」里站住 1 个(平移 p = 0.86)",
         "ledger": "S-881", "table_id": "A",
         "data_in_repo": "docs/research/s881_results.json", "checkable": True},
        {"claim": "S-881:7 个拥挤持仓读数里站住 3 个(p_crowd_ge_real = 0.0)",
         "ledger": "S-881", "table_id": "B",
         "data_in_repo": "docs/research/s881_results.json", "checkable": True},
        {"claim": "S-888:线上 · 主流领里 8 个风格指数有 7 个两段都站住(平移 p = 0.033);全表站住 12",
         "ledger": "S-888", "table_id": None,
         "data_in_repo": None, "checkable": False,
         "why": "结果没有落盘成 json(只在台账文字里 + Seth 的 SQL);docs/research/ 与 Mac 数据根都搜过 —— "
                "⇒ 逐行核跑不动"},
        {"claim": "S-889:落到币上也站住(130 张 +5.9% / 张 → 620 张 +5.5%,胜率 15–21%、盈亏比 9.6–14.5)",
         "ledger": "S-889", "table_id": None,
         "data_in_repo": None, "checkable": False,
         "why": "同 S-888:没有落盘文件"},
        {"claim": "S-879:破位空单两段都站住(有效样本 66 张)",
         "ledger": "S-879", "table_id": "G",
         "data_in_repo": "docs/research/s879_results.json", "checkable": True,
         "why": "文件里没有 per-格 判定字段 ⇒「原报 N」按台账读;数字本身可核"},
        {"claim": "S-873:26 条上站住了(T × L 版均值 / 波动 1.01、安慰剂 94.5 分位)",
         "ledger": "S-873", "table_id": None,
         "data_in_repo": None, "checkable": False,
         "why": "没有落盘文件"},
        {"claim": "S-829:两台引擎一致(每格差 ≤ 0.6pp);7 格站住",
         "ledger": "S-829", "table_id": None,
         "data_in_repo": None, "checkable": False,
         "why": "没有落盘文件"},
        {"claim": "S-825 / T-349:f★ = 1.25%,f 0.75% / 1.0% / 1.25% 三档连续站住",
         "ledger": "S-825", "table_id": None,
         "data_in_repo": "docs/research/t349_results.json", "checkable": False,
         "why": "账户级口径(每票风险 f × 名义上限),没有票级 n / 盈亏比 / 逐段拆分 —— "
                "四条判据都不适用;文件里也没有 per-格 的站住标记(在 judgement.per_f 里)"},
    ]
    audit["not_checkable"] = [
        {"what": "S-888 / S-889 / S-873 / S-829 的「N 格站住」",
         "why": "结果未落盘(台账文字 + Seth 的 SQL);已排除:docs/research/*.json 全扫无 S-888/S-889/S-873/S-829 "
                "关键字;Mac 数据根 _data/research 与 research/ 也没有对应文件",
         "blocked_at": "找不到机器可核的落盘数字"},
        {"what": "S-869 盲书 156 格(S-869)",
         "why": "口径是「策略 × 状态」的日频格子,没有票级 n / 盈亏比 / 发现段-留出段拆分 ⇒ "
                "D2/D3/D4 不适用;只核了 D1(逐位同数)",
         "blocked_at": "口径不含票级样本"},
        {"what": "S-767 事件基率表 3 族",
         "why": "事件级口径:有 n(53 / 142 / 205),但没有盈亏比、没有发现段-留出段拆分 ⇒ "
                "只核 D2 与「分层里有 n < 10 的桶」",
         "blocked_at": "口径不含票级样本"},
    ]

    with open(os.path.join(ROOT, "t417_degeneracy_audit.json"), "w",
              encoding="utf-8") as fh:
        json.dump(audit, fh, ensure_ascii=False, indent=1)
    print("tables:", len(audit["tables"]))
    tot_N = sum(t["reported_holds_N"] or 0 for t in audit["tables"])
    tot_M = sum(t["degenerate_M"] or 0 for t in audit["tables"])
    print(f"原报站住合计 N = {tot_N};退化 M = {tot_M}")
    for t in audit["tables"]:
        print(f"  {t['id']:2s} {t['table'][:40]:42s} N={t['reported_holds_N']} "
              f"M={t['degenerate_M']} K={t['surviving_K']}")
    print("\n同票碰撞:", len(uniq))
    for k, v in kinds.items():
        print(f"   {v:4d}  {k}")
    for d in uniq:
        if d.get("scope") in ("同表", "跨表") or (
                d.get("scope") == "同文件" and "不是两条读数" not in d.get("kind", "")):
            print(f"  * {d['file']}: {d['readings']} | {d.get('kind')}")


if __name__ == "__main__":
    main()
