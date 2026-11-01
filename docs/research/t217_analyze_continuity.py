#!/usr/bin/env python3
"""T-217 ① analysis: turn continuity.json into the master continuity table.

Answers, per arm of every daily forward table:
  first / last / days_present / days_expected / missing_days
  longest_gap (len + date range) / late_gt_2d (computed_at after d+2)
  early_before_day / corrections_nonempty
plus a per-table verdict on whether the table can serve a third party as
「自首日起连续、未回填」的证据.
"""
from __future__ import annotations

import json
from pathlib import Path

IN = str(Path(__file__).resolve().parent / "t217_continuity.json")
OUT = str(Path(__file__).resolve().parent / "t217_continuity_table.md")

# 表 -> 是不是「按日写入的前向记录」(卡片点名的 + 我们发现的)
DAILY_FORWARD = [
    "core_cap_daily", "cis_tilt_daily", "beta_plus_daily", "tokenization_tilt_daily",
    "hl_book_daily", "allocation_daily", "allocation_nav_daily", "live_account_daily",
    "depth_divergence_log", "rr_matrix_daily",
    "core_variants_daily", "multiplier_daily", "portfolio_layer_daily",
    "feature_arms_daily", "meta_allocator_daily", "r_money_daily", "short_paper_money",
    "beta_core_nav", "risk_meter_history", "cis_official_daily", "signal_journal",
]


def main() -> None:
    d = json.load(open(IN))
    direct = d.get("direct") or {}
    series = d.get("series") or {}
    card = d.get("card_tables") or {}

    lines = []
    lines.append("# T-217 ① 连续性总表(逐臂)\n")
    lines.append("| 表 | 臂 | 前向首日 | 前向末日 | 有/应有天 | 缺失天 | 最长缺口 | 缺口日期 | computed_at 晚于 d+2 | 早于当天 | 更正非空 | 可作第三方证据 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")

    summary = []
    for t in DAILY_FORWARD:
        if t in direct and direct[t].get("status") == 200:
            for arm, a in sorted(direct[t]["arms"].items()):
                gap = f"{a['longest_gap_days']}d"
                gr = "/".join(a["longest_gap_range"]) if a["longest_gap_range"] else "-"
                ev = evidence_verdict(a)
                lines.append(
                    f"| `{t}` | {arm} | {a['first']} | {a['last']} | "
                    f"{a['days_present']}/{a['days_expected']} | {a['missing_days']} | {gap} | {gr} | "
                    f"{a['late_gt_2d']} | {a['early_before_day']} | {a['corrections_nonempty']} | {ev} |")
                summary.append({"table": t, "arm": arm, **a, "evidence": ev})
        elif t in series and series[t].get("status") == 200:
            for arm, a in sorted(series[t]["arms"].items(), key=lambda kv: str(kv[0])):
                lines.append(
                    f"| `{t}` | {arm} | {a.get('first')} | {a.get('last')} | "
                    f"{a.get('n')}/? | ? | ? | ? | ? (无 computed_at) | ? | ? | "
                    f"**否** — 逐日明细不可读,只给臂级计数 |")
                summary.append({"table": t, "arm": arm, "series_only": True, **a})
        else:
            st = (card.get(t) or {}).get("note", "")
            lines.append(
                f"| `{t}` | — | — | — | — | — | — | — | — | — | — | "
                f"**否** — publishable key 读不到({st[:60]}) |")
            summary.append({"table": t, "blocked": True, "note": st})

    lines.append("\n\n# 表级汇总\n")
    lines.append("| 表 | 可读通道 | 臂数 | 前向总行 | 缺失天合计 | 晚写>2d 合计 | 更正合计 | 证据可用 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for t in DAILY_FORWARD:
        if t in direct and direct[t].get("status") == 200:
            arms = direct[t]["arms"].values()
            lines.append(
                f"| `{t}` | 直读 | {len(arms)} | {sum(a['n_forward_rows'] for a in arms)} | "
                f"{sum(a['missing_days'] for a in arms)} | {sum(a['late_gt_2d'] for a in arms)} | "
                f"{sum(a['corrections_nonempty'] for a in arms)} | "
                f"{'是' if all(a['missing_days'] == 0 and a['late_gt_2d'] == 0 and a['corrections_nonempty'] == 0 for a in arms) else '否/需说明'} |")
        elif t in series and series[t].get("status") == 200:
            lines.append(f"| `{t}` | series 端点 | {len(series[t]['arms'])} | — | 不可算 | 不可算 | 不可算 | 否 |")
        else:
            lines.append(f"| `{t}` | 读不到 | — | — | 不可算 | 不可算 | 不可算 | 否 |")

    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(str(Path(__file__).resolve().parent / "t217_continuity_summary.json"), "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("\n".join(lines))


def evidence_verdict(a: dict) -> str:
    """能作第三方证据吗:无缺口 + 无晚补写 + 无更正 + 前向段从 inception 起连续。"""
    if a["missing_days"] == 0 and a["late_gt_2d"] == 0 and a["corrections_nonempty"] == 0:
        return "是"
    if a["missing_days"] == 0 and a["late_gt_2d"] == 0:
        return "是(但有更正行)"
    return "否"


if __name__ == "__main__":
    main()
