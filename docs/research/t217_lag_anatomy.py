#!/usr/bin/env python3
"""T-217: is `computed_at` late because the row was BACKFILLED in bulk, or because
the daily writer simply runs a few hours/days behind?

Discriminator: a bulk recompute writes MANY consecutive d-rows with the SAME
computed_at (or a tight cluster of timestamps). A daily writer writes ONE row per
d, with computed_at close to d.

Per table/arm we report:
  distinct computed_at count vs distinct d count
  max rows sharing one computed_at
  lag histogram
  verdict: BULK_BACKFILL / DAILY_WRITE / MIXED
"""
from __future__ import annotations

import collections
import json
import os
from pathlib import Path

IN = str(Path(__file__).resolve().parent / "t217_continuity.json")
OUT = str(Path(__file__).resolve().parent / "t217_lag_anatomy.json")

# 表/臂 -> 回放臂(不是真前向记录,要在报告里分开)
REPLAY_ARM_HINT = ("replay", "cap_pit24")


def main() -> None:
    d = json.load(open(IN))
    direct = d.get("direct") or {}
    # 真实的不同 computed_at 个数 / 同一 ts 下的最大行数:
    # 必须来自**原始行**,不能用 lag 直方图的种数代替(旧版把 len(lag) 当 ts 数,
    # 把 core_cap_daily 的 BULK_BACKFILL 误判成 MIXED —— 2026-11-01 已修)。
    # t217_ts_sequence.py 的逐臂计数就是原始行算出来的,直接取用。
    ts_seq = {}
    ts_path = str(Path(__file__).resolve().parent / "t217_ts_sequence.json")
    if os.path.exists(ts_path):
        ts_seq = json.load(open(ts_path))
    out = {}
    print(f"{'table.arm':46s} {'d数':>5s} {'ts数':>5s} {'max同ts':>7s} {'lag直方图':46s} 判定")
    for t, tv in direct.items():
        if tv.get("status") != 200:
            continue
        for arm, a in sorted(tv["arms"].items()):
            lag = a.get("lag_hist") or {}
            nd = a.get("days_present") or 0
            sq = ts_seq.get(f"{t}.{arm}") or {}
            nts = sq.get("distinct_ts")
            max_same = sq.get("max_rows_per_ts")
            hist = ",".join(f"{k}:{v}" for k, v in sorted(lag.items(), key=lambda kv: int(kv[0])))
            if nts is None:  # 没有 ts_sequence 兜底:lag 直方图只能给滞后种数,不能当 ts 数
                nts = -1
                max_same = -1
            if nd == 0:
                verdict = "EMPTY"
            elif (a.get("late_gt_2d", 0) >= 0.5 * a.get("n_forward_rows", 1)
                  and max_same >= 0.5 * nd):
                verdict = "BULK_BACKFILL"
            elif a.get("late_gt_2d", 0) == 0:
                verdict = "DAILY_WRITE"
            else:
                verdict = "MIXED"
            rec = {"nd": nd, "n_distinct_ts": nts, "max_rows_per_ts": max_same,
                   "lag_hist": lag, "late_gt_2d": a.get("late_gt_2d"),
                   "n_forward_rows": a.get("n_forward_rows"),
                   "inception": a.get("inception"), "verdict": verdict,
                   "is_replay_arm": any(h in str(arm) for h in REPLAY_ARM_HINT)}
            out[f"{t}.{arm}"] = rec
            print(f"{t + '.' + str(arm)[:36]:46s} {nd:5d} {nts:5d} {max_same:7d} "
                  f"{hist[:46]:46s} {verdict}")
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nsaved", OUT)


if __name__ == "__main__":
    main()
