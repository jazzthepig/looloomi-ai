#!/usr/bin/env python3
"""T-217 —— 复核 §3 的循环失败分类与 §3.5 的 write_health 数字(按当前 json 重算)。"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
d = json.load(open(HERE / "t217_final2.json"))

lr = d["loop_rpc"]
loops = lr["loops"]
print("loops total:", lr["n_loops"], "| ok24h:", lr["sum_ok_24h"], "| fail24h:", lr["sum_fail_24h"],
      "| loops with fail:", lr["n_loops_fail24h"])
print("timeout-class loops:", lr["n_loops_timeout_reason"], "| timeout fails:", lr["sum_fail_24h_timeout_loops"])

empty_reason_fails = sum(int(x.get("n_fail_24h") or 0) for x in loops if not (x.get("last_reason") or "").strip())
print("fails with EMPTY last_reason:", empty_reason_fails)

fail_loops = [x for x in loops if int(x.get("n_fail_24h") or 0) > 0]
fail_loops.sort(key=lambda x: (x.get("last_fail") or ""))
print("loops with fail:", len(fail_loops))
print("  first fail at:", fail_loops[0].get("last_fail"), "| last fail at:", fail_loops[-1].get("last_fail"))
print("  top sources by n_fail_24h:")
for x in sorted(fail_loops, key=lambda z: -int(z.get("n_fail_24h") or 0))[:6]:
    print("    %-34s n=%-4s reason=%r" % (x.get("loop"), x.get("n_fail_24h"), (x.get("last_reason") or "")[:70]))

print()
print("### write_health")
wh = d.get("write_health") or {}
print("tables:", wh.get("n_tables"), "| with last_fail:", wh.get("n_with_fail"), "| sum n_fail_24h:", wh.get("sum_fail_24h"))
for r in wh.get("rows", []):
    if r.get("n_fail_24h"):
        print("   %-32s n_fail_24h=%-3s last_fail=%-26s %s" % (
            r.get("table"), r.get("n_fail_24h"), r.get("last_fail"), str(r.get("last_body"))[:95]))
