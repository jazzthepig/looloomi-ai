#!/usr/bin/env python3
"""T-217:把 continuity_fwd.json 渲染成报告用的 markdown 表行。只读。"""
from __future__ import annotations

import json
from pathlib import Path

d = json.load(open(str(Path(__file__).resolve().parent / "t217_continuity_fwd.json")))
SHOW = {
    "core_cap_daily": ["cap_a1", "cap_a05", "ew_a0", "cap_a1_u"],
    "cis_tilt_daily": ["cis_a1", "cis_a1_u", "fund_a1_u"],
    "hl_book_daily": ["_all"],
    "core_variants_daily": ["btc", "cap_uncapped", "mom90", "cap_pit24"],
    "multiplier_daily": ["mult_v1", "mult_v2", "tom_pd13", "q_v2"],
    "r_money_daily": ["_all"],
    "short_paper_money": ["short_h4_gate", "short_listing_hedged"],
    "beta_core_nav": ["_all"],
    "risk_meter_history": ["_all"],
}
LAG = {
    "core_cap_daily": "全表同一 computed_at(逐小时整条重算)",
    "cis_tilt_daily": "T+1 为主,早段一次批量补写",
    "hl_book_daily": "T+1 为主(34/39),11 行带 correction",
    "core_variants_daily": "T+1 为主,早段一次批量补写",
    "multiplier_daily": "T+1 为主,早段一次批量补写",
    "r_money_daily": "全部 T+1",
    "short_paper_money": "T+1~T+3",
    "beta_core_nav": "全部 T+0(marked_at=mark_date)",
    "risk_meter_history": "T+0/T-1(9 行早于当日)",
}
print("| 表 | 臂 | inception | 前向首日 | 前向末日 | 天数 | 应有 | 缺失 | 最长缺口 | computed_at>d+2 | correction |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
for t, arms in SHOW.items():
    info = d.get(t, {})
    for a in arms:
        c = info.get("arms", {}).get(a)
        if not c:
            continue
        gap = f"{c['fwd_longest_gap']} ({c['fwd_gap_range'][0]}~{c['fwd_gap_range'][1]})" if c["fwd_gap_range"] else "0(无缺口)"
        print(f"| `{t}` | `{a}` | {c['inception'] or '—'} | {c['fwd_first']} | {c['fwd_last']} | {c['fwd_days']} | "
              f"{c['fwd_expected']} | {c['fwd_missing']} | {gap} | {c['late_gt_2d']} | {c['corrections']} |")
print()
print("写入滞后分布(前向段):")
for t, arms in SHOW.items():
    info = d.get(t, {})
    for a in arms:
        c = info.get("arms", {}).get(a)
        if not c:
            continue
        h = {k: v for k, v in c["lag_hist"].items() if int(k) <= 3}
        print(f"- `{t}.{a}`: 滞后≤3天 {h} · 全部 {c['lag_hist'] if len(c['lag_hist']) <= 6 else '{…}'} · {LAG.get(t,'')}")
