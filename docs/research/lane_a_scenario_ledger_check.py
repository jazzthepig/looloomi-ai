"""lane-a 的情景台账体检:哪些条目会进不了台账(死条目)。

口径与写入端一致(`src/data/evaluation/scenario_ledger.py`):
  - 文件级:`repo_files()` 认 `author` 与 `entries`;
  - 条目级:`ingest_repo()` 用**文件级 author 注入每条**再 `validate()`。

所以本脚本注入 author 再 validate —— 直接把条目喂 validate 会误报「缺 author」(2026-11-12 的坑)。

用法:
    python3 docs/research/lane_a_scenario_ledger_check.py            # 全部 lane
    python3 docs/research/lane_a_scenario_ledger_check.py lane-a     # 只看一个 lane

退出码:有死条目 = 1(可当门禁用)。
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.scenario_ledger import repo_files, validate  # noqa: E402


def main(argv: list[str]) -> int:
    only = argv[1] if len(argv) > 1 else ""
    today = dt.date.today()
    recs = repo_files(str(ROOT))
    if only:
        recs = [r for r in recs if r["file"].startswith(only + "-")]
    live = dead = 0
    for r in sorted(recs, key=lambda x: x["file"]):
        if r["problems"]:
            print(f"{r['file']}  文件级:{'; '.join(r['problems'])}  (entries {len(r['entries'])})")
            dead += 1
            continue
        bad = [(e.get("id"), validate({**e, "author": r["author"]}, today))
               for e in r["entries"]]
        bad = [(i, w) for i, w in bad if w]
        live += len(r["entries"]) - len(bad)
        dead += len(bad)
        for i, w in bad:
            print(f"{r['file']}/{i}  条目级:{'; '.join(w)}")
    print(f"\n活条目 {live} · 死条目 {dead}(文件级 {sum(1 for r in recs if r['problems'])} 份整份不认)")
    return 1 if dead else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
