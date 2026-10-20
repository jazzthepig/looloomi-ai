"""T-154 重数 —— 用公用鱼计数器重数 T-145 / T-149 报告里的「鱼」数,报与它们各自的差。

只报不改(不改 T-145 / T-149 的台账结论)。

T-145 在报告里给的鱼数是 trade-level「在鱼上」= entry 之后 120 根内最高 high 或 close ≥ 3 × entry,
覆盖 892 张 S-633 信号票,「在鱼上」= 96 张 (10.8%)。这不是 S-618 的 panel-fish 数,
那个数也会贴出来,两条要分开看。

T-149 的「S-618 鱼数自检」是 panel-level,跟 S-618 台账原文同口径,直接重数可比:
本次测得 = 286,T-149 自报 837,Δ = -551。

读库只用 os.environ['SUPABASE_URL' / 'SUPABASE_KEY'],publishable,不打印 key。
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any

_FC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fish_counter.py")
_spec = _ilu.spec_from_file_location("fish_counter", _FC_PATH)
fish_counter = _ilu.module_from_spec(_spec)  # type: ignore
_spec.loader.exec_module(fish_counter)  # type: ignore

URL = os.environ.get("SUPABASE_URL", "")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY")


def _sb_select(path: str, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
    hdr = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    qs = urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(f"{URL}/rest/v1/{path}?{qs}", headers=hdr)
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def main() -> None:
    t0 = time.time()
    panel = fish_counter.fetch_panel_supabase("2020-03-01", "2026-06-20")
    panel_rows = sum(len(v) for v in panel.values())
    n_sym = len(panel)
    print(f"[t154-recount] panel rows={panel_rows}  symbols={n_sym}  (pull {time.time()-t0:.1f}s)")

    # 公用鱼计数器对当前面板(同 universe 与台账同)
    fish = fish_counter.fish(panel, "2020-03-01", "2026-06-20")
    panel_fish = len(fish)
    panel_fish_syms = len({f["symbol"] for f in fish})
    panel_fish_run_hits = sum(f["n_hits"] for f in fish)

    # T-149 自检的 837 = 同样的 S-618 口径(合并 30 根)数出来的鱼
    t149_self = json.load(open("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-149_results.json"))["selfcheck_s618"]
    # T-149 实际 keys: n_fish_unmerged / n_fish_runs / n_symbols
    t149_fish_runs = t149_self["n_fish_runs"]
    t149_unmerged = t149_self["n_fish_unmerged"]
    t149_panel_symbols = t149_self["n_symbols"]
    delta_t149 = panel_fish - t149_fish_runs

    # T-145 的「鱼」是 trade-level「在鱼上」= entry 之后 120 根内 max(h or c) ≥ 3 × entry;
    # 不是 panel 鱼。报里给的是 96 张。面板鱼是另一个量,两条数字都贴出来。
    t145 = json.load(open("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-145_results.json"))
    t145_meta = t145.get("meta", {})
    t145_in_fish_trades = sum(1 for g in t145.get("by_W", {}).values() for _ in [])
    # `by_W` 是 dict[W]={n, on_fish, ...};on_fish 是 W=0+1 的总和
    on_fish_total = 0
    for g in t145.get("by_W", {}).values():
        on_fish_total += g.get("on_fish", 0)
    # ↑ by_W 是分组后的;原 T-145 「全表 96 条 (10.8%)」= by_W 合并
    delta_t145 = panel_fish - 0  # T-145 没有 panel-fish 数,作 0 占位

    payload = {
        "panel_window": ["2020-03-01", "2026-06-20"],
        "panel_rows": panel_rows,
        "panel_symbols": n_sym,
        "panel_fish_runs": panel_fish,
        "panel_fish_distinct_symbols": panel_fish_syms,
        "panel_fish_total_hits": panel_fish_run_hits,
        "elapsed_s": round(time.time() - t0, 1),
        "t149": {
            "t149_selfcheck_panel_fish_runs": t149_self["n_fish_runs"],
            "t149_selfcheck_n_fish_unmerged_hits": t149_unmerged,
            "t149_selfcheck_panel_symbols": t149_panel_symbols,
            "canonical_panel_fish_runs": panel_fish,
            "delta_vs_t149": delta_t149,
        },
        "t145": {
            "t145_tickets": t145_meta.get("n_tickets"),
            "t145_in_fish_trades_total": on_fish_total,
            "t145_scope_note": "T-145 '鱼' = trade-level '在鱼上' (entry+120 根内 max(h,c) ≥ 3×entry),"
                               " 不是 S-618 panel-fish;两者同宇宙但口径不同,数字本来就不该相等。",
            "canonical_panel_fish_runs_on_same_universe": panel_fish,
            "delta_vs_t145_panelfish": delta_t145,  # 占位 = 0,因为 T-145 没有 panel-fish
        },
    }
    print(json.dumps(payload, indent=2, default=str))
    out_path = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-154_recount_t145_t149.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\n[t154-recount] wrote {out_path}")


if __name__ == "__main__":
    main()
