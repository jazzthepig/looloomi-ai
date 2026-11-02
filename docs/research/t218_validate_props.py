#!/usr/bin/env python3
"""T-218:用 origin/main 的情景台账校验器逐条检查报告里的 10 条命题。

台账实现在 origin/main(不在本工作树),这里只读地取源码、在内存里 exec,
用它自己的 `validate()` 跑一遍 —— 规则以实现为准,不以本报告的转述为准。
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORT = HERE / "T-218_rails_vs_tokens.md"

src = subprocess.run(["git", "--no-optional-locks", "show",
                      "origin/main:src/data/evaluation/scenario_ledger.py"],
                     capture_output=True, text=True, cwd=HERE.parent.parent, check=True).stdout
ns: dict = {"__name__": "scenario_ledger_ref"}
exec(compile(src, "scenario_ledger.py", "exec"), ns)
validate = ns["validate"]
parse_variable = ns["parse_variable"]

text = REPORT.read_text()
m = re.search(r"```json\n(.*?)\n```", text, re.S)
props = json.loads(m.group(1))
today = dt.date(2026, 11, 2)

bad = 0
for e in props:
    why = validate(e, today)
    kind, key = parse_variable(e["variable"])
    flag = "OK " if not why else "BAD"
    if why:
        bad += 1
    print(f"{flag} {e['id']:<9} {kind:<6} {key:<24} op={e['op']:<7} "
          f"lo={e['lo']} hi={e['hi']} prob={e['prob']} horizon={e['horizon_d']} "
          f"weekday={dt.date.fromisoformat(e['horizon_d']).strftime('%a')} {why or ''}")
print()
print(f"共 {len(props)} 条,不合规 {bad} 条")
