"""lane 不碰主目录:Claude Code PreToolUse 钩子(lane_bot 启动每一轮时经 --settings 装上)。

10-08 事故:lane-c 的自动轮次在**主目录** ~/Projects/looloomi-ai 里
`switch -c lane-c/T-036` → `stash push -m "...not mine..."` → `switch main` → `update-index --chmod`,
把 Seth 17 个未提交的文件(含 Jazz 的 pptx)收进了 stash,另在主目录留下两个散落脚本。
白名单(--allowedTools)拦不住:它是**追加**在用户自己的权限之上的,而 terminal 里的 claude 早已放行 git。
钩子不一样 —— 它对每次调用都跑,退出码 2 = 拦下,stderr 原文回给 lane。

拦三类:
1. 指向主目录的 git 写操作(切分支、stash、add/commit、reset、update-index ……)
2. Write / Edit 写进主目录 —— 共享的 gitignored 文档除外(SYNC、台账、策略手册)
3. Bash 重定向 / tee 写进主目录 —— 同样的例外
lane 自己的 worktree(~/Projects/looloomi-ai-lane-x)与私有仓库(looloomi-ai-private)不受影响。
"""
from __future__ import annotations

import json
import re
import sys

MAIN = r"(?:/Users/sbb|~|\$HOME|\$\{HOME\})/Projects/looloomi-ai(?![\w-])"
SHARED_DOCS = ("MINIMAX_SYNC.md", "MINIMAX_SYNC_ARCHIVE.md", "REFUTATION_LEDGER.md", "STRATEGY_PLAYBOOK.md")
_GIT_WRITE = re.compile(
    r"\bgit\b[^|;&]*?\s(switch|checkout|stash|reset|update-index|add|commit|merge|rebase|restore|clean|"
    r"worktree|cherry-pick|am|apply|rm|mv|pull|push|tag|branch\s+-[dDmMcCf])\b")
_MAIN_RE = re.compile(MAIN)
_REDIRECT_INTO_MAIN = re.compile(r"(?:>>?|\btee(?:\s+-a)?)\s*[\"']?(" + MAIN + r"/[^\s\"';&|]*)")

WHY = ("lane 不在主目录 ~/Projects/looloomi-ai 里做 git 写操作或写文件 —— 那是 Seth 的工作区,"
       "里面未提交的改动不是「pre-existing dirty state」,是别人正在做的事(10-08 事故)。"
       "在你自己的 worktree(~/Projects/looloomi-ai-lane-x)里做;共享文档(MINIMAX_SYNC.md / 台账)可以直接写。")


def _shared(path: str) -> bool:
    return any(path.rstrip("/").endswith("/" + d) for d in SHARED_DOCS)


def verdict(tool: str, inp: dict) -> str | None:
    """返回拦截理由;None = 放行。纯函数,测试直接调。"""
    if tool == "Bash":
        cmd = str(inp.get("command") or "")
        if _MAIN_RE.search(cmd) and _GIT_WRITE.search(cmd):
            return f"拦下:主目录上的 git 写操作。{WHY}"
        for m in _REDIRECT_INTO_MAIN.finditer(cmd):
            if not _shared(m.group(1)):
                return f"拦下:往主目录写文件 {m.group(1)}。{WHY}"
        return None
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = str(inp.get("file_path") or inp.get("notebook_path") or "")
        if _MAIN_RE.match(path) and not _shared(path):
            return f"拦下:往主目录写文件 {path}。{WHY}"
    return None


def main() -> int:
    try:
        ev = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 — 读不懂输入不拦(拦了 lane 就整轮动不了),但留痕
        print("guard_main_dir: unreadable hook input", file=sys.stderr)
        return 0
    why = verdict(str(ev.get("tool_name") or ""), ev.get("tool_input") or {})
    if why:
        print(why, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
