"""T-179 reconcile — world50 的 shares 台阶 vs SEC 申报封面股数(只进报告)。

不是独立研究脚本,是给报告用的对照表:每一步台阶左边是库里那一周的股数,
右边是 EDGAR 在那前后最近的一次申报封面股数 + 申报号 + 表单类型。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import date

spec = importlib.util.spec_from_file_location(
    "t179", os.path.abspath("docs/research/t179_share_change_audit.py")
)
m = importlib.util.module_from_spec(spec)
sys.modules["t179"] = m
spec.loader.exec_module(m)

EDGAR = "/Volumes/CometCloudAI/cometcloud-local/research/t179/edgar_entity_shares.json"


def main() -> None:
    ev = json.load(open(EDGAR))
    syms, _ = m.universe()
    ser = m.shares_series(syms)
    rows = json.load(open("/Volumes/CometCloudAI/cometcloud-local/research/t179/t179_summary.json"))["rows"]
    by_key = {r["key"]: r for r in rows}

    order = [r["key"] for r in rows if r["new_52w_pct"] is not None and abs(r["new_52w_pct"]) > 5]
    order += ["VZ", "CMCSA", "MO"]
    seen = set()
    for tk in order:
        if tk in seen:
            continue
        seen.add(tk)
        r = by_key.get(tk)
        e = ev.get(tk, {})
        print("=" * 78)
        print(f"{tk}  {e.get('title','?')}  CIK {e.get('cik','?')}")
        print(f"  52w shares change {r['new_52w_pct']:+.2f}%   旧推法 {r['old_52w_pct']}%   "
              f"差 {r['delta_pp']}pp")
        print(f"  {r['old_shares']:>18,} ({r['base_date']})  ->  {r['new_shares']:>18,} ({r['last_date']})")
        print("  库内台阶:", r["steps"] or "(无)")
        seq = sorted(ser.get(tk, []), key=lambda x: x["d"])
        vals = {}
        for row in seq:
            vals.setdefault(row["shares"], row["d"])
        print("  台阶明细:")
        shown = 0
        for a, b in zip(seq, seq[1:]):
            ch = b["shares"] / a["shares"] - 1.0
            if abs(ch) > 0.02:
                print(f"    {b['d']}  {a['shares']:>18,.0f} -> {b['shares']:>18,.0f}  {ch*100:+6.2f}%")
                shown += 1
            if shown > 8:
                break
        print("  EDGAR dei:EntityCommonStockSharesOutstanding (2025-09 起):")
        for f in e.get("facts", [])[-8:]:
            print(f"    end={f['end']} filed={f['filed']} {f['form']:8s} {f['accn']}  val={f['val']:,}"
                  if isinstance(f["val"], (int, float)) else f"    {f}")
        if e.get("n") == 0:
            print("    (窗口内无记录)")


if __name__ == "__main__":
    main()