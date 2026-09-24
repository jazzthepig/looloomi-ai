"""任务卡 → 看板(S-421)。

    python3 scripts/task_board.py            重新生成 tasks/BOARD.md
    python3 scripts/task_board.py --check    只检查 BOARD.md 是否最新(preflight 用)

任务卡在 `tasks/T-*.json`(JSON 而不是 YAML:不引入新依赖,preflight 在任何机器上都能跑),一张卡一个任务。看板是生成物,不要手改 ——
手改的看板会和卡片分开演化,那正是 MINIMAX_SYNC 里散文待办的毛病。
"""
from __future__ import annotations

import sys
from pathlib import Path

import json

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks"
BOARD = TASKS / "BOARD.md"

OWNERS = ("jazz", "seth", "lane-a", "lane-b", "lane-c")
STATUSES = ("open", "claimed", "blocked", "in_review", "done", "dropped")
REQUIRED = ("id", "title", "owner", "status", "created", "source",
            "allowed_paths", "forbidden_paths", "acceptance", "prior_value")
_ORDER = {s: i for i, s in enumerate(("in_review", "claimed", "open", "blocked", "done", "dropped"))}


def load_cards() -> list[dict]:
    cards = []
    for p in sorted(TASKS.glob("T-*.json")):
        c = json.loads(p.read_text(encoding="utf-8")) or {}
        c["_file"] = p.name
        cards.append(c)
    return cards


def problems(cards: list[dict]) -> list[str]:
    """卡片自身的问题。**done 只能由合并者验证后的值决定,agent 不能自己宣布。**"""
    out, seen = [], set()
    for c in cards:
        f = c.get("_file", "?")
        for k in REQUIRED:
            if k not in c or c[k] in (None, ""):
                out.append(f"{f}: 缺字段 {k}")
        if c.get("id") and f != f"{c['id']}.json":
            out.append(f"{f}: 文件名和 id 不一致")
        if c.get("id") in seen:
            out.append(f"{f}: id 重复")
        seen.add(c.get("id"))
        if c.get("owner") not in OWNERS:
            out.append(f"{f}: owner 必须是 {OWNERS}")
        if c.get("status") not in STATUSES:
            out.append(f"{f}: status 必须是 {STATUSES}")
        acc = c.get("acceptance") or {}
        if not (isinstance(acc, dict) and acc.get("check") and acc.get("expect")):
            out.append(f"{f}: acceptance 必须有 check 和 expect")
        if c.get("status") == "blocked" and not c.get("blocked_by"):
            out.append(f"{f}: blocked 必须写 blocked_by")
        if c.get("status") == "done":
            v = c.get("verified") or {}
            if v.get("by") != "seth" or not v.get("value") or not v.get("at"):
                out.append(f"{f}: done 必须有合并者验证(verified.by=seth / value / at)—— 不能自己宣布完成")
    return out


def render(cards: list[dict]) -> str:
    rows = sorted(cards, key=lambda c: (_ORDER.get(c.get("status"), 9), c.get("owner", ""), c.get("id", "")))
    lines = ["# 任务看板(生成物,勿手改:`python3 scripts/task_board.py`)", "",
             "| 状态 | 任务 | 负责 | 标题 | 验收 | 之前 | 验证 |", "|---|---|---|---|---|---|---|"]
    for c in rows:
        acc = c.get("acceptance") or {}
        v = c.get("verified") or {}
        ver = f"{v.get('value')} @ {v.get('at')}" if v else ""
        blk = f"(等 {c['blocked_by']})" if c.get("blocked_by") else ""
        lines.append(f"| {c.get('status')}{blk} | {c.get('id')} | {c.get('owner')} | {c.get('title')} "
                     f"| {acc.get('expect', '')} | {c.get('prior_value', '')} | {ver} |")
    n = {s: sum(1 for c in cards if c.get("status") == s) for s in STATUSES}
    lines += ["", " · ".join(f"{s} {k}" for s, k in n.items() if k)]
    return "\n".join(lines) + "\n"


def main() -> int:
    cards = load_cards()
    bad = problems(cards)
    if bad:
        print("✗ 任务卡有问题:\n  " + "\n  ".join(bad))
        return 1
    text = render(cards)
    if "--check" in sys.argv:
        if not BOARD.exists() or BOARD.read_text(encoding="utf-8") != text:
            print("✗ tasks/BOARD.md 不是最新 —— 跑 python3 scripts/task_board.py")
            return 1
        print(f"✓ {len(cards)} 张任务卡合法,看板是最新的")
        return 0
    BOARD.write_text(text, encoding="utf-8")
    print(f"✓ 看板已生成:{len(cards)} 张卡")
    return 0


if __name__ == "__main__":
    sys.exit(main())
