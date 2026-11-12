"""T-348 续做(lane-c,2026-11-12 无人值守轮):
① S-736 同日出场记账诊断(票与规则一字不动,只改出场判断次序);
② S-808(T-332)/ S-810(T-334)两族按新尺子(账户口径)重判。
口径与自检沿用 t348_graveyard.py(C0 = RBv2 + R-v2 f0.5% + 现金;两个窗口)。

用法: python3 t348_families.py
产物: t348_families_results.json + _t348_families_section.md
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import t348_graveyard as G  # noqa: E402

DATA_ROOT = "/Volumes/CometCloudAI/cometcloud-local"
T332_CACHE = os.path.join(DATA_ROOT, "research", "t332")
OUT_JSON = os.path.join(HERE, "t348_families_results.json")
OUT_MD = os.path.join(HERE, "_t348_families_section.md")


def log(msg: str) -> None:
    print(str(msg), flush=True)


# ── t332 / t334 的数据与面板(只读他们自己的缓存,不联网)────────────────────────
def t332_env():
    import t332_squeeze_fade as T332  # noqa: PLC0415
    ev_rows = json.load(open(os.path.join(T332_CACHE, "events_squeeze.json")))
    perp_rows = json.load(open(os.path.join(T332_CACHE, "perp_squeeze_syms.json")))
    fund_rows = json.load(open(os.path.join(T332_CACHE, "fund_squeeze_syms.json")))
    events = [(r["symbol"], str(r["d"])[:10]) for r in ev_rows]
    perp_by, fund_by = defaultdict(list), defaultdict(list)
    for r in perp_rows:
        perp_by[r["symbol"]].append(r)
    for r in fund_rows:
        fund_by[r["symbol"]].append(r)
    panels: dict[str, dict] = {}
    for s in sorted({s for s, _ in events}):
        if s in perp_by:
            panels[s] = T332.build_panel(perp_by[s], fund_by.get(s, []))
    return T332, ev_rows, events, panels


def fam_s808(T332, events, panels) -> dict:
    """S-808 / T-332:被挤空头的币 → 带止损的反向空票(时间止损 20 根)。
    票与规则照他们自己的 `run_tickets`;袖套照他们自己的 `sleeve_nav`(已含同日出场修正)。"""
    ev_sorted = sorted(events, key=lambda x: (x[1], x[0]))
    tickets, skipped = T332.run_tickets(ev_sorted, panels, T332.TIME_STOP_MAIN)
    days = sorted({d for t in tickets for d in t["_fd"]})
    _, navarr, _ = T332.sleeve_nav(tickets, panels, days)
    nav = pd.Series(navarr, index=pd.to_datetime(days))
    ref = json.load(open(os.path.join(HERE, "t332_results.json")))["summary"]
    m = G.metrics(nav)
    log(f"  S-808: 票 {len(tickets)}(跳过 {skipped}) · 袖套总回报 {m['total_return']:+.6%}"
        f" vs 已发布 {ref['sleeve_total_return']:+.6%}"
        f" · 最大回撤 {m['max_dd']:+.6%} vs {ref['sleeve_max_dd']:+.6%}")
    best = max(tickets, key=lambda t: float(t.get("r_net") or -9e9))
    return {"nav": nav, "first_entry": min(t["entry_d"] for t in tickets),
            "last_exit": max(t["exit_d"] for t in tickets), "n_tickets": len(tickets),
            "n_skipped": skipped, "risk_frac": G.F_FAM, "cap": 10,
            "family_published_ref": {"sleeve_total_return": ref["sleeve_total_return"],
                                     "sleeve_max_dd": ref["sleeve_max_dd"],
                                     "avg_r_net": ref["avg_r_net"], "n_tickets": ref["n_tickets"],
                                     "reasons": ref["reasons"]},
            "best_ticket": {"symbol": best.get("symbol"), "signal_d": best.get("signal_d"),
                            "entry_d": best.get("entry_d"), "r": best.get("r_net"),
                            "why": "族内 r_net 最大的一张(只报不判)"},
            "note": "照 T-332 自己的 sleeve_nav(多票并发;同名日已修);资金费实计"}


def fam_s810(T332, T334, ev_rows, panels) -> dict:
    """S-810 / T-334:低频 + 等确认的 squeeze 做空(极端 + 确认)。"""
    evs = [{"symbol": r["symbol"], "d": str(r["d"])[:10], "ret": r["ret"], "atr_thr": r["atr_thr"]}
           for r in ev_rows]
    evs.sort(key=lambda e: (e["d"], e["symbol"]))
    flags = T334.extreme_flags(evs)
    tickets, _st = T334.build_tickets(evs, flags, panels, use_extreme=True, use_confirm=True)
    days = sorted({d for t in tickets for d in t["_fd"]})
    _, navarr, _ = T332.sleeve_nav(tickets, panels, days)
    nav = pd.Series(navarr, index=pd.to_datetime(days))
    ref = json.load(open(os.path.join(HERE, "t334_results.json")))["main"]
    m = G.metrics(nav)
    log(f"  S-810: 票 {len(tickets)} · 袖套总回报 {m['total_return']:+.6%}"
        f" vs 已发布 {ref['sleeve_total_return']:+.6%}"
        f" · 最大回撤 {m['max_dd']:+.6%} vs {ref['sleeve_max_dd']:+.6%}")
    best = max(tickets, key=lambda t: float(t.get("r_net") or -9e9))
    return {"nav": nav, "first_entry": min(t["entry_d"] for t in tickets),
            "last_exit": max(t["exit_d"] for t in tickets), "n_tickets": len(tickets),
            "risk_frac": G.F_FAM, "cap": 10,
            "family_published_ref": {"sleeve_total_return": ref["sleeve_total_return"],
                                     "sleeve_max_dd": ref["sleeve_max_dd"],
                                     "summary": ref["summary"], "n_days": ref["n_days"]},
            "best_ticket": {"symbol": best.get("symbol"), "signal_d": best.get("signal_d"),
                            "entry_d": best.get("entry_d"), "r": best.get("r_net"),
                            "why": "族内 r_net 最大的一张(只报不判)"},
            "note": "照 T-334 自己的 build_tickets + T-332 sleeve_nav;资金费实计"}


# ── S-736 诊断:旧 ❌ 里有多少来自记账 ─────────────────────────────────────────
def s736_accounting(res: dict, fam736: dict) -> None:
    """逐票 R + 账户口径两个窗口(已发布曲线 vs 只改出场判断次序的诊断变体)。"""
    detail = fam736["tickets_detail"]
    n_pub = sum(1 for t in detail if t["taken_published"])
    n_fix = sum(1 for t in detail if t["taken_fixed"])
    rs = [float(t["r_net"] or 0.0) for t in detail]
    res["S736_accounting"] = {
        "n_tickets": len(detail),
        "taken_published": n_pub, "taken_fixed": n_fix,
        "ticket_level_avg_r_net": float(np.mean(rs)),
        "ticket_level_total_r_net": float(np.sum(rs)),
        "ticket_level_win_rate": float(np.mean([r > 0 for r in rs])),
        "ticket_level_reasons": {r: sum(1 for t in detail if t["reason"] == r)
                                 for r in ("止盈", "保本", "止损", "时间")},
        "tickets": detail,
        "cross_ref_T338": {"avg_r_net": -0.3744908562608685, "n": 18,
                           "reasons": {"止盈": 2, "保本": 2, "止损": 10, "时间": 4},
                           "src": "docs/research/T-338_t256_nav_sweep.md(B 道)"},
    }
    log(f"  S-736 记账:逐票平均净 R {np.mean(rs):+.6f}(B 道 T-338 同值 -0.374491)"
        f" · 已发布成交 {n_pub}/{len(detail)} 张 · 诊断变体成交 {n_fix}/{len(detail)} 张")


def write_md(res: dict) -> None:
    L: list[str] = []
    A = L.append
    A("\n---\n")
    A("## 第二部分(lane-c 续做,2026-11-12):S-736 记账诊断 + S-808 / S-810 两族\n")
    base = res["base"]
    A(f"基准 C0(RBv2 + R-v2 f0.5% + 现金)总收益 {base['C0_total_return']:+.6%}"
      f"(自检① 与 T-342 L3 差 {base['selfcheck_C0_diff']:.1e});"
      f"基准账本 {base['cal_start']} → {base['cal_end']}。\n")

    # ── S-736 ──
    acc = res["S736_accounting"]
    A("### 1. S-736(T-256 战术空单)—— 旧 ❌ 里有多少来自记账\n")
    A("| 项 | 值 |")
    A("|---|---|")
    A(f"| 票数 | {acc['n_tickets']} |")
    A(f"| 逐票平均净 R(与记账无关) | {acc['ticket_level_avg_r_net']:+.6f} |")
    A(f"| 逐票净 R 合计 | {acc['ticket_level_total_r_net']:+.6f} |")
    A(f"| 逐票胜率 | {acc['ticket_level_win_rate']:.1%} |")
    A(f"| 出场分布 | {acc['ticket_level_reasons']} |")
    A(f"| 已发布曲线实际成交 | {acc['taken_published']}/{acc['n_tickets']} 张 |")
    A(f"| 诊断变体(只改出场判断次序)成交 | {acc['taken_fixed']}/{acc['n_tickets']} 张 |")
    A("")
    A("**逐票表**(r_price / r_fund / r_cost / r_net;`已成交`列 = 该票在两条曲线里是否真的开出去):\n")
    A("| # | 进场 | 出场 | 持有一天数 | 出场原因 | r_price | r_fund | r_cost | r_net | 已发布成交 | 变体成交 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, t in enumerate(acc["tickets"], 1):
        A(f"| {i} | {t['entry_d']} | {t['exit_d']} | {t.get('hold_days')} | {t.get('reason')} | "
          f"{float(t.get('r_price') or 0):+.4f} | {float(t.get('r_fund') or 0):+.4f} | "
          f"{float(t.get('r_cost') or 0):+.4f} | {float(t.get('r_net') or 0):+.4f} | "
          f"{'✅' if t['taken_published'] else '—'} | {'✅' if t['taken_fixed'] else '—'} |")
    A("")
    for key, label in (("S736_published", "已发布曲线(照 T-256 口径)"),
                       ("S736_fixed", "诊断变体(只改出场判断次序)")):
        r = res[key]
        A(f"**{label}** —— 族自身总回报 {r['family_standalone']['total_return']:+.4%}、"
          f"最大回撤 {r['family_standalone']['max_dd']:+.4%};"
          f"结论:{r['conclusion']['class']}"
          + ("(**窗口依赖**)" if r["conclusion"]["window_dependent"] else "") + "\n")
        A("| 窗口 | C0 CAGR | +族 CAGR | Δ(pp) | C0 最长水下 | +族 最长水下 | C0 最大回撤 | +族 最大回撤 | 自检② 差 |")
        A("|---|---|---|---|---|---|---|---|---|")
        for wn, w in r["windows"].items():
            A(f"| {wn}({w['start']} →) | {w['C0']['metrics']['cagr']:+.4%} | "
              f"{w['C0_plus_family']['metrics']['cagr']:+.4%} | {w['diff']['cagr_pp']:+.3f} | "
              f"{w['C0']['underwater'].get('length_d')} 日 | {w['C0_plus_family']['underwater'].get('length_d')} 日 | "
              f"{w['C0']['metrics']['max_dd']:+.4%} | {w['C0_plus_family']['metrics']['max_dd']:+.4%} | "
              f"{w['selfcheck_family']['abs_diff']:.1e} |")
        A("")
    A("**逐档结果**:见 `t348_families_results.json` 的 `S736_accounting` 与 `S736_*`。\n")

    # ── S-808 / S-810 ──
    A("### 2. S-808(T-332 有止损的反向空票)与 S-810(T-334 低频 + 等确认)\n")
    A("| 族 | 票数 | 族自身总回报 | 族自身最大回撤 | 已发布对照 |")
    A("|---|---|---|---|---|")
    for key, label in (("S808", "S-808"), ("S810", "S-810")):
        r = res[key]
        fs = r["family_standalone"]
        ref = r["meta"].get("family_published_ref", {})
        A(f"| {label} | {r['meta']['n_tickets']} | {fs['total_return']:+.4%} | {fs['max_dd']:+.4%} | "
          f"{float(ref.get('sleeve_total_return', float('nan'))):+.4%} / "
          f"{float(ref.get('sleeve_max_dd', float('nan'))):+.4%} |")
    A("")
    for key, label in (("S808", "S-808"), ("S810", "S-810")):
        r = res[key]
        A(f"**{label}** —— 结论:{r['conclusion']['class']}"
          + ("(**窗口依赖**)" if r["conclusion"]["window_dependent"] else "") + "\n")
        A("| 窗口 | C0 CAGR | +族 CAGR | Δ(pp) | C0 最长水下 | +族 最长水下 | C0 最大回撤 | +族 最大回撤 | 自检② 差 |")
        A("|---|---|---|---|---|---|---|---|---|")
        for wn, w in r["windows"].items():
            A(f"| {wn}({w['start']} →) | {w['C0']['metrics']['cagr']:+.4%} | "
              f"{w['C0_plus_family']['metrics']['cagr']:+.4%} | {w['diff']['cagr_pp']:+.3f} | "
              f"{w['C0']['underwater'].get('length_d')} 日 | {w['C0_plus_family']['underwater'].get('length_d')} 日 | "
              f"{w['C0']['metrics']['max_dd']:+.4%} | {w['C0_plus_family']['metrics']['max_dd']:+.4%} | "
              f"{w['selfcheck_family']['abs_diff']:.1e} |")
        A("")
        A("逐年(族自身 / +族 vs C0):\n")
        A("| 年 | 族自身 | C0 | +族 |")
        A("|---|---|---|---|")
        fy = r["family_standalone_yearly"]
        for wn, w in r["windows"].items():
            for y in sorted(set(fy) | set(w["C0"]["yearly"]) | set(w["C0_plus_family"]["yearly"])):
                A(f"| {y}({wn[:1]}) | {fy.get(y, float('nan')):+.4%} | "
                  f"{w['C0']['yearly'].get(y, float('nan')):+.4%} | "
                  f"{w['C0_plus_family']['yearly'].get(y, float('nan')):+.4%} |")
        A("")
    A("**「去掉最好一张」**(只报不判):\n")
    for key, label in (("S808", "S-808"), ("S810", "S-810")):
        bt = res[key]["meta"].get("best_ticket") or {}
        A(f"- {label}:{bt.get('symbol')} · 信号 {bt.get('signal_d')} · 进场 {bt.get('entry_d')} · "
          f"r = {bt.get('r')}")
    A("")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(L))


def main() -> None:
    kernel = G.load_kernel()
    log("=== 基准 ===")
    base = G.build_base(kernel)
    res = {"card": "T-348", "part": "续做:S-736 记账诊断 + S-808 / S-810",
           "generated": "lane-c 2026-11-12",
           "base": {"C0_total_return": base["C0_total_return"], "C0_cagr": base["C0_cagr"],
                    "selfcheck_C0_diff": base["selfcheck_C0_diff"],
                    "cal_start": str(base["cal_idx"][0].date()),
                    "cal_end": str(base["cal_idx"][-1].date())}}
    log("=== ① S-736 记账诊断 ===")
    fam736 = G.family_s736()
    pub = {k: v for k, v in fam736.items() if k != "variant"}
    fix = {**pub, **fam736["variant"]}
    s736_accounting(res, fam736)
    res["S736_published"] = G.evaluate(base, kernel, pub, "S-736 已发布")
    res["S736_fixed"] = G.evaluate(base, kernel, fix, "S-736 诊断变体")
    json.dump(res, open(OUT_JSON, "w"), ensure_ascii=False, indent=2, default=str)
    log(f"  → 已写 {OUT_JSON}")
    log("=== ② S-808 / S-810 ===")
    T332, ev_rows, events, panels = t332_env()
    import t334_squeeze_fail as T334  # noqa: PLC0415
    f808 = fam_s808(T332, events, panels)
    res["S808"] = G.evaluate(base, kernel, f808, "S-808")
    json.dump(res, open(OUT_JSON, "w"), ensure_ascii=False, indent=2, default=str)
    f810 = fam_s810(T332, T334, ev_rows, panels)
    res["S810"] = G.evaluate(base, kernel, f810, "S-810")
    json.dump(res, open(OUT_JSON, "w"), ensure_ascii=False, indent=2, default=str)
    write_md(res)
    log(f"  → 已写 {OUT_JSON} / {OUT_MD}")


if __name__ == "__main__":
    main()
