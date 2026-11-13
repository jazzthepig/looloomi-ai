"""T-375 附属:用仓库自己的 scenario_ledger 校验器验一遍 scenarios/lane-a-T-375.json。

只读,不写库 —— 只跑 repo_files() + validate(),把不合格的条目报出来。
用法(仓库根目录):
    python3 docs/research/s852_check_scenarios.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from src.data.evaluation.scenario_ledger import repo_files, validate  # noqa: E402

TARGET = "lane-a-T-375.json"


def main() -> None:
    today = dt.date(2026, 11, 14)
    files = repo_files()
    hit = [f for f in files if f["file"] == TARGET]
    if not hit:
        print("没找到", TARGET, "—— repo_files() 只扫到", len(files), "个文件")
        return
    rec = hit[0]
    print("file:", rec["file"], "| author:", rec["author"], "| entries:", len(rec["entries"]))
    if rec["problems"]:
        print("文件级问题:", rec["problems"])
    bad = 0
    for e in rec["entries"]:
        probs = validate({**e, "author": rec["author"]}, today)
        print("  %-10s %-28s %-6s prob=%-5s horizon=%s  %s" % (
            e.get("id"), e.get("variable"), e.get("op"), e.get("prob"), e.get("horizon_d"),
            "OK" if not probs else "不合格: " + "; ".join(probs)))
        bad += bool(probs)
    print("\n不合格条目数:", bad)


if __name__ == "__main__":
    main()
