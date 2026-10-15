"""T-103 —— World50 EW×(Mom+Growth) 臂(S-581 预注册里留的那条)。

预注册见 REFUTATION_LEDGER.md 的 M-583;本脚本只在 `world50_revenue` 至少有一行才进 §3 计算,
否则按 T-103 acceptance 停在此处并报「数据未到,等下一轮循环」。

用法(Mac 上,环境里有 SUPABASE_URL / SUPABASE_KEY;key 不打印、不写文件):
    python3 docs/research/t103_growth_arm.py \\
        ~/Projects/looloomi-private/research_data/t103_panel.json \\
        ~/Projects/looloomi-private/research_data/t103_growth.json \\
        [_reports/absorb_input/T-103_growth_arm.md]

§1 增长分定义(M-583 §1):
    每季末 t,对每家公司只用 world50_revenue 里 filed ≤ t 的行;
    选报得最新的 tag;TTM 营收 = 最近 4 个连续季度之和(没有季度就用最近一年);
    增长 = TTM(t) / TTM(t − 4 季) − 1;
    算不出的公司增长分记 1(中性)。

§2 回放规则(M-583 §2):
    沿用 S-581 面板 + 新增 EW×(Mom+Growth) 与探索臂 EWxGrowth;判据 apparatus.ab_test。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PAGE = 1000


def _get_all(client: httpx.Client, tail: str) -> list[dict]:
    """PostgREST 一页最多 1000 行:按 offset 翻到底。"""
    out: list[dict] = []
    while True:
        r = client.get(f"/rest/v1/{tail}&limit={PAGE}&offset={len(out)}")
        if r.status_code != 200:
            raise RuntimeError(f"读 {tail.split('?')[0]} HTTP {r.status_code}: {r.text[:160]}")
        rows = r.json()
        out += rows
        if len(rows) < PAGE:
            return out


def probe_revenue_table() -> tuple[int, int]:
    """读 world50_revenue,返回 (row_count, distinct_key_count)。为 0 直接 exit。"""
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_KEY 不在环境里")
    with httpx.Client(base_url=base, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=60) as c:
        r = c.get("/rest/v1/world50_revenue?select=key",
                  headers={"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact"})
        if r.status_code != 200:
            raise RuntimeError(f"读 world50_revenue HTTP {r.status_code}: {r.text[:160]}")
        rows = r.json()
        n_total = len(rows)
        n_keys = len({r.get("key") for r in rows if r.get("key")})
        return n_total, n_keys


def quarter_end_dates(months: list[str]) -> list[str]:
    return [m for m in months if m[5:] in ("03", "06", "09", "12")]


def main(panel_path: str, growth_path: str, report_path: Optional[str] = None) -> None:
    n_total, n_keys = probe_revenue_table()
    print(f"world50_revenue: rows={n_total}, distinct keys={n_keys}")
    if n_total == 0:
        msg = (
            "world50_revenue 0 行 —— 数据未到,按 T-103 acceptance 等下一轮循环,不跑回放、不报数。\n"
            f"  probe: rows={n_total}, distinct_keys={n_keys}\n"
            f"  panel: {panel_path}(不创建,等数据)\n"
            f"  growth scores: {growth_path}(不创建,等数据)\n"
            "  M-583 预注册已写,卡 status=in_review,notes 写「数据未到」。\n"
        )
        print(msg)
        if report_path:
            Path(report_path).parent.mkdir(parents=True, exist_ok=True)
            Path(report_path).write_text(
                "# T-103 World50 EW×(Mom+Growth) 臂 —— 数据未到,等下一轮循环\n\n"
                f"- 预注册:M-583(REFUTATION_LEDGER.md,写于看任何增长 / 营收数字之前)\n"
                f"- 数据 probe:`world50_revenue` rows={n_total}, distinct keys={n_keys}\n"
                f"- 结论:数据未到,按 T-103 acceptance 停在此处,**不跑回放、不报数**\n"
                f"- 下一步:等周更循环写入 revenue 行;循环到位后按 §3 计算增长分、加 EW×(Mom+Growth) 与 EWxGrowth 两臂。\n"
            )
        return
    # ---- 数据已到:未在本轮实现(M-583 §2-§3 的实算在下一轮完成) ----
    raise SystemExit(
        f"world50_revenue 已有 {n_total} 行({n_keys} key)—— 按 M-583 §2 / §3 实算;"
        "本轮(10-16)数据 probe=0,计算留待数据到位后再起一卡。"
    )


if __name__ == "__main__":
    main(*sys.argv[1:])