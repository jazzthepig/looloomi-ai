#!/usr/bin/env python3
"""T-217 §3.2 —— 循环失败分类(确定性规则,可机器复核)。

四个互斥桶,关键修正:「原因为空」单独成桶 —— 它**不可归类**,
不能同时被算进「良性无操作」和「不可归因」(旧稿在这里双算了 14 次)。

  FROZEN   reason 以「冻结」开头            -> 有意冻结,不是错误
  EMPTY    reason 为空/纯空白               -> 不可归类(不推测)
  BENIGN   reason 含良性无操作标记           -> 没有待补 / 已记录 / 已锚过 / up to date / 回放至 / 重算至
  OTHER    其余                              -> 有具体原因文本,需人工看
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
d = json.load(open(HERE / "t217_final2.json"))

BENIGN_MARKERS = ("已记录", "已锚过", "up to date", "没有待补", "回放至", "重算至")

rows = [x for x in d["loop_rpc"]["loops"] if int(x.get("n_fail_24h") or 0) > 0]
buckets: dict[str, list] = {"FROZEN": [], "EMPTY": [], "BENIGN": [], "OTHER": []}
for x in rows:
    r = (x.get("last_reason") or "").strip()
    if r.startswith("冻结"):
        b = "FROZEN"
    elif not r:
        b = "EMPTY"
    elif any(m in r for m in BENIGN_MARKERS):
        b = "BENIGN"
    else:
        b = "OTHER"
    buckets[b].append(x)

total = 0
for b in ("BENIGN", "FROZEN", "EMPTY", "OTHER"):
    sub = sum(int(x["n_fail_24h"]) for x in buckets[b])
    total += sub
    print("### %s  次=%d  循环数=%d" % (b, sub, len(buckets[b])))
    for x in sorted(buckets[b], key=lambda z: -int(z["n_fail_24h"])):
        print("   %-34s n=%-4s %r" % (x.get("loop"), x.get("n_fail_24h"),
                                       (x.get("last_reason") or "")[:66]))
    print()

print("合计失败次数:", total, "| 有失败的循环数:", len(rows))
print("BENIGN+FROZEN = %d (%.1f%%)  | EMPTY = %d (%.1f%%)  | OTHER = %d" % (
    sum(int(x["n_fail_24h"]) for x in buckets["BENIGN"] + buckets["FROZEN"]),
    100.0 * sum(int(x["n_fail_24h"]) for x in buckets["BENIGN"] + buckets["FROZEN"]) / total,
    sum(int(x["n_fail_24h"]) for x in buckets["EMPTY"]),
    100.0 * sum(int(x["n_fail_24h"]) for x in buckets["EMPTY"]) / total,
    sum(int(x["n_fail_24h"]) for x in buckets["OTHER"])))
print("原因含 timeout/超时/deadline 字样的失败次数:",
      sum(int(x["n_fail_24h"]) for x in rows
          if any(w in (x.get("last_reason") or "").lower()
                 for w in ("timeout", "timed out", "time out", "超时", "deadline"))))

fl = sorted(rows, key=lambda x: (x.get("last_fail") or ""))
print("失败时间范围:", fl[0].get("last_fail"), "->", fl[-1].get("last_fail"))
