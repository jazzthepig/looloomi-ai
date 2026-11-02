#!/usr/bin/env python3
"""跑 S-661 的 onset 事件(只读),把 stdout 存成 _s661_onset.json。"""
import subprocess
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = "/Users/sbb/Projects/looloomi-ai/docs/research/s661_value_mining.py"
p = subprocess.run([sys.executable, SCRIPT, "onset"], capture_output=True, text=True, timeout=900)
out = os.path.join(HERE, "_s661_onset.json")
if p.returncode != 0:
    print("FAILED rc=", p.returncode)
    print(p.stderr[-2000:])
    sys.exit(1)
open(out, "w").write(p.stdout)
import json
d = json.loads(p.stdout)
print("onset events:", len(d))
for r in d:
    print(r["onset"], r["g"], r.get("rel_1m"), r.get("rel_3m"), r.get("rel_6m"))
