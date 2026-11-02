"""给 seth_bot 排任务的一行命令(11-02,Seth 待命模式 `docs/SETH_STANDBY.md`):Jazz 不用手写 JSON。

    python3 scripts/seth_bot/queue.py merge lane-a/T-231 [-m "标题"]        合并一条 lane 分支(seth_bot 跑 preflight 后推 main)
    python3 scripts/seth_bot/queue.py commit -m "feat(x): …" 路径 路径 …     提交主目录里这些路径(永远不是 -A)
    python3 scripts/seth_bot/queue.py wake lane-b "任务原文"                 叫醒一个 lane 做一件具体的事(写 .lane_bot/wake/<lane>)
    python3 scripts/seth_bot/queue.py status                               队列里有什么、最近五条结果

只写文件,不跑 git;写进 `.seth_bot/queue/`(与 `.lane_bot/wake/`)之后由 launchd 的 seth_bot / lane_bot 接手。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUEUE = ROOT / ".seth_bot" / "queue"
DONE = ROOT / ".seth_bot" / "done"
WAKE = ROOT / ".lane_bot" / "wake"
_BR = re.compile(r"^lane-[abc]/T-\d+(?:-[\w.-]+)?$")


def _id(tag: str) -> str:
    return f"{dt.datetime.now(dt.timezone.utc):%Y%m%d-%H%M%S}-{tag}"


def _write(job: dict) -> Path:
    QUEUE.mkdir(parents=True, exist_ok=True)
    p = QUEUE / f"{job['id']}.json"
    p.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def cmd_merge(a) -> int:
    if not _BR.match(a.branch):
        print(f"分支名要是 lane-{{a,b,c}}/T-NNN:{a.branch!r}")
        return 1
    tid = a.branch.split("/", 1)[1]
    p = _write({"id": _id(f"merge-{tid.lower()}"), "by": "seth", "op": "merge", "branch": a.branch,
                "message": a.message or f"merge({a.branch.split('/')[0]}): {tid}"})
    print(f"排了合并 {a.branch} → {p.name}(seth_bot 每 5 分钟一轮;看 .seth_bot/log.txt)")
    return 0


def cmd_commit(a) -> int:
    paths = [p for p in a.paths if p]
    bad = [p for p in paths if p in ("-A", ".", "*") or p.startswith("-")]
    if not paths or bad:
        print("要给明确的路径,不能 -A / .")
        return 1
    missing = [p for p in paths if not (ROOT / p).exists()]
    if missing:
        print(f"主目录里没有:{missing}")
        return 1
    p = _write({"id": _id("commit"), "by": "seth", "op": "commit", "paths": paths, "message": a.message})
    print(f"排了提交 {len(paths)} 个路径 → {p.name}")
    return 0


def cmd_wake(a) -> int:
    if a.lane not in ("lane-a", "lane-b", "lane-c"):
        print("lane 要是 lane-a / lane-b / lane-c")
        return 1
    WAKE.mkdir(parents=True, exist_ok=True)
    (WAKE / a.lane).write_text(a.task.strip() + "\n", encoding="utf-8")
    print(f"写了 .lane_bot/wake/{a.lane};lane_bot 下一轮(≤ 10 分钟)叫醒它")
    return 0


def cmd_status(_a) -> int:
    q = sorted(QUEUE.glob("*.json")) if QUEUE.exists() else []
    print(f"队列 {len(q)} 条:" + (", ".join(x.stem for x in q) or "空"))
    for f in sorted(DONE.glob("*.json"))[-5:] if DONE.exists() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        print(f"  {'✓' if d.get('ok') else '✗'} {f.stem} → {d.get('stage')} {(d.get('sha') or '')[:8]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("branch")
    m.add_argument("-m", "--message", default="")
    m.set_defaults(fn=cmd_merge)
    c = sub.add_parser("commit")
    c.add_argument("-m", "--message", required=True)
    c.add_argument("paths", nargs="+")
    c.set_defaults(fn=cmd_commit)
    w = sub.add_parser("wake")
    w.add_argument("lane")
    w.add_argument("task")
    w.set_defaults(fn=cmd_wake)
    s = sub.add_parser("status")
    s.set_defaults(fn=cmd_status)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
