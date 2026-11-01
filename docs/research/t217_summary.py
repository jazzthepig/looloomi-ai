#!/usr/bin/env python3
"""T-217 —— 把 t217_final2.json 压成可核对的紧凑表(报告直接引用)。"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
d = json.load(open(HERE / "t217_final2.json"))

print("read_at:", d["read_at"])
print()
print("### A. 直读按日前向表(逐臂)")
for t, a in d["direct"].items():
    print("\n--", t, "rows=", a.get("n_rows"), "arm_col=", a.get("arm_col"),
          "ts_cols=", a.get("ts_cols"))
    for r in a.get("arms", []):
        fwd = ""
        if "fwd_n" in r:
            fwd = " | fwd[%s..%s] n=%d exp=%d miss=%d gap=%s" % (
                r.get("fwd_first"), r.get("fwd_last"), r["fwd_n"], r["fwd_expected"],
                r["fwd_missing"], r.get("fwd_longest_gap"))
        print("   %-22s %s..%s n=%-5d exp=%-5d miss=%-3d gap=%-28s wd_miss=%-3d%s" % (
            r["arm"][:22], r["first"], r["last"], r["n_days"], r["expected_cal"],
            r["missing_cal"], str(r.get("longest_gap_cal")), r.get("missing_weekdays"), fwd))
        print("      write_mode:", r.get("write_mode"),
              "| lag_gt2=", r.get("computed_at_n_lag_gt2", r.get("recorded_at_n_lag_gt2")),
              "| correction_nonempty=", r.get("correction_nonempty"),
              "| inception=", r.get("inception"), r.get("inception_src"),
              "| pre_inception_days=", r.get("pre_inception_days"))

print()
print("### B. 公开接口臂级事实(series)")
for t, s in d["series"].items():
    arms = s.get("arms") or []
    print("--", t, "status", s.get("status"), "note", str(s.get("note"))[:80])
    for a in arms:
        print("   %-24s inception=%s first=%s last=%s n=%s" % (
            str(a.get("arm"))[:24], a.get("inception"), a.get("first"), a.get("last"), a.get("n")))
