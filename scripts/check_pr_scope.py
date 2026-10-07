"""lane 分支的改动范围 = 它的任务卡允许的范围(S-500)。

    python3 scripts/check_pr_scope.py --branch lane-a/T-003 --base origin/main --head HEAD
    python3 scripts/check_pr_scope.py --title lane-a/T-003      打印 PR 标题(CI 开 PR 用)

为什么是脚本而不是让审阅者看:「改了卡上没允许的文件」是机械事实,不需要判断。
以前靠合并者一眼看出来 —— S-416 整文件 add 把别人的代码带上线、A 的 T-023 补丁基于旧文件,
都是在合并那一刻才发现。现在 lane 一推分支,CI 和 Mac 侧执行器(scripts/seth_bot/)跑同一个函数。

规则:
1. 分支名 `lane-{a,b,c}/T-NNN[-后缀]`;卡 `tasks/T-NNN.json` 必须存在,owner = 该 lane
2. 改动的每个文件 ∈ 卡的 allowed_paths(仓库内路径;绝对路径是 Mac 数据根,与仓库 diff 无关)
   + 卡自己 + tasks/BOARD.md
3. 任何文件都不许落在 卡的 forbidden_paths ∪ GLOBAL_FORBIDDEN
4. 卡的 status 必须是 in_review(lane 交付时改);lane 不能写 done(test_task_cards 已挡)
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BRANCH_RE = re.compile(r"^(lane-[abc])/(T-\d{3})(?:-[A-Za-z0-9._-]+)?$")

# 任何 lane 卡都不能放开的路径。每一条都对应一次事故或一条硬规则。
GLOBAL_FORBIDDEN = (
    "Shadow/",                 # 硬规则 2:只读、非权威,永不入库
    ".github/",                # CI 本身就是关卡;改关卡的 PR 不能由被关卡管的人发
    "scripts/githooks/",       # pre-push 钩子(S-421)
    "scripts/seth_bot/",       # 合并执行器(S-500)
    "scripts/check_pr_scope.py",
    "docs/DECISIONS.md",       # Jazz 的裁决,只经 Seth 记
    ".env",
)


def _match(path: str, pattern: str) -> bool:
    if pattern.startswith("/"):
        return False                       # Mac 数据根,不在仓库里
    if any(ch in pattern for ch in "*?["):
        return fnmatch.fnmatch(path, pattern)
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return path == pattern or path.startswith(pattern.rstrip("/") + "/")


def check(branch: str, changed: list[str], card: dict | None) -> list[str]:
    """返回问题列表;空 = 通过。纯函数,测试直接调。"""
    m = BRANCH_RE.match(branch)
    if not m:
        return [f"分支名 {branch!r} 不是 lane-{{a,b,c}}/T-NNN[-后缀]"]
    lane, tid = m.group(1), m.group(2)
    if card is None:
        return [f"tasks/{tid}.json 不存在 —— 卡号只由 Seth 分配,先要卡再开工"]
    out: list[str] = []
    if card.get("owner") != lane:
        out.append(f"{tid} 的 owner 是 {card.get('owner')!r},不是 {lane}")
    if card.get("status") != "in_review":
        out.append(f"{tid} 的 status 是 {card.get('status')!r} —— 交付时改成 in_review,notes 写上自己测得的值")
    allowed = list(card.get("allowed_paths") or []) + [f"tasks/{tid}.json", "tasks/BOARD.md"]
    forbidden = list(card.get("forbidden_paths") or []) + list(GLOBAL_FORBIDDEN)
    for f in changed:
        hit = next((p for p in forbidden if _match(f, p)), None)
        if hit:
            out.append(f"{f} 落在禁区 {hit}")
        elif not any(_match(f, p) for p in allowed):
            out.append(f"{f} 不在 {tid} 的 allowed_paths 里")
    if not changed:
        out.append("分支相对 base 没有任何改动")
    return out


def _git(*args: str) -> str:
    return subprocess.run(["git", "--no-optional-locks", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


def _card_at(rev: str, tid: str) -> dict | None:
    try:
        return json.loads(_git("show", f"{rev}:tasks/{tid}.json"))
    except subprocess.CalledProcessError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--title", metavar="BRANCH", help="只打印 PR 标题")
    a = ap.parse_args()

    if a.title:
        m = BRANCH_RE.match(a.title)
        card = _card_at("HEAD", m.group(2)) if m else None
        print(f"{m.group(2)} · {card.get('title', '')}" if (m and card) else a.title)
        return 0

    m = BRANCH_RE.match(a.branch or "")
    card = _card_at(a.head, m.group(2)) if m else None
    changed = [x for x in _git("diff", "--name-only", f"{a.base}...{a.head}").splitlines() if x]
    bad = check(a.branch or "", changed, card)
    head = f"范围检查 {a.branch}:{len(changed)} 个文件"
    if bad:
        print(f"✗ {head}\n  " + "\n  ".join(bad))
        return 1
    print(f"✓ {head},全部在 {m.group(2)} 允许的范围内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
