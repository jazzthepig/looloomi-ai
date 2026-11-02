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

S-559(10-13 两次):① lane-a 先 `cd /Users/sbb/Projects/looloomi-ai && git status`(放行:只读),Claude Code 的 Bash
会**记住** cwd,下一条 `git switch -c lane-a/T-089 origin/main` 里没有主目录路径 ⇒ 漏过,主目录被切走,seth_bot 停 7 小时,
Seth 的两个提交落在 lane 的分支上。⇒ 钩子输入里的 `cwd` 是主目录时,不带路径的 git 写操作同样拦。
② 03:18 一个 Jazz 手动开的 lane 会话(不经 lane_bot,没装这个钩子)在主目录 stash + 切分支。⇒ `--head` 模式由仓库的
.claude/settings.json 对**所有**会话装上:主目录里只拦会移动 HEAD / 收走改动的操作(switch、checkout <分支>、stash、
reset --hard、branch -m)—— Seth 与 Jazz 的会话照常 add / commit。

11-02 降落守卫(S-705):三个 lane 同一天的定时轮次(T-218 / T-219 / T-220)**全部**以「Prompt is too long」中断,各跑 100+ 步、
读入 1,000 万 token、零交付 —— 写了十几个探针脚本、每个整份进上下文,到 130 步时上下文满了,连最终回复都写不出来。
prompt.md 里的提醒(10-13 起就有)挡不住。改成钩子按**转录文件**量上下文(`transcript_path` 是每次钩子都给的;
MiniMax 中转不回 usage,只能数字符):40 轮实测,成功收尾的轮次内容 ≤ 46 万字符、溢出的 46–56 万字符。
- ≥ SOFT(36 万):只放行「降落」工具 —— 改任务卡、task_board、preflight、git add/commit/push、往数据根 mv 产物;其余一律拦,
  理由里写明现在就收尾(卡 status / notes、提交已有的、最终回复写清还差什么)。
- ≥ HARD(44 万):一切工具都拦 —— 只剩写最终回复这一步。
- 另两条省上下文的硬规则:Read 不带 limit 且文件 > 400 行 ⇒ 拦(先 grep -n 定位、再按 offset/limit 读);
  Bash 里跑 python3 / pytest 而没有 tail / head / 重定向 ⇒ 钩子给命令补上 `2>&1 | tail -n 80`(updatedInput;老版本 CLI 不认就原样放行)。
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


_HEAD_MOVE = re.compile(
    r"\bgit\b[^|;&]*?\s(switch|stash|checkout(?!\s+--(?:\s|$))(?:\s+-[bB])?\s+(?!--)\S|reset\s+--hard|branch\s+-[mM])")
_OTHER_TREE = re.compile(r"(?:/Users/sbb|~|\$HOME|\$\{HOME\})/Projects/looloomi-ai-[\w-]+")


def _in_main(cwd: str) -> bool:
    return bool(cwd) and bool(re.fullmatch(MAIN + r"/?", cwd.strip()))


def _targets_main(cmd: str, cwd: str) -> bool:
    """命令落在主目录:命令里写了主目录路径,或会话 cwd 就是主目录且命令没有显式指向别的 worktree。"""
    if _MAIN_RE.search(cmd):
        return True
    return _in_main(cwd) and not _OTHER_TREE.search(cmd)


def head_verdict(cmd: str, cwd: str = "") -> str | None:
    """--head 模式(所有会话):主目录里不许移动 HEAD、不许 stash。纯函数。"""
    probe = re.sub(r"\bgit\s+(?:switch|checkout)\s+main\b", "", cmd)    # 切回 main 永远放行
    if _HEAD_MOVE.search(probe) and _targets_main(cmd, cwd):
        return ("拦下:主目录 ~/Projects/looloomi-ai 必须一直停在 main —— seth_bot 每 5 分钟在这里提交与快进,"
                "切分支 / stash 会让它整轮拒绝执行、把别人的未提交改动收走(10-08、10-13 两次)。"
                "要看别的分支用 `git show <分支>:<路径>` 或 `git worktree add`;lane 在自己的 worktree 里做。")
    return None


def _shared(path: str) -> bool:
    return any(path.rstrip("/").endswith("/" + d) for d in SHARED_DOCS)


#: 2026-10-20:lane 反复 `cat cometcloud-local/.env`,service_role key 进了中转上下文,随后被写进脚本推上公开仓库。
#: lane 只拿 publishable key,而且不读任何 env 文件、不把环境变量里的 key 打印出来。启发式,不是沙箱 ——
#: 真正的防线是 lane 手里的 key 本身只读(migrations/2026-10-20_lane_read_publishable.sql)。
_ENV_FILE = re.compile(r"(?:^|[\s/\"'=:(<])\.env(?:\.[\w.-]+)?(?=$|[\s\"';|&)<>])|\.cometcloud/|\bsecrets?\.(?:env|json|ya?ml)\b")
_PRINT_ENV = re.compile(r"\bprintenv\b|(?:^|[;&|]\s*)env\s*(?:$|[|;&])|\b(?:declare|export)\s+-p\b|"
                        r"\b(?:echo|printf|cat)\b[^|;&]*\$\{?[A-Z_]*(?:KEY|TOKEN|SECRET)")
WHY_SECRETS = ("拦下:lane 不读 env 文件、不打印密钥(2026-10-20 service_role 泄露)。脚本里用 os.environ['SUPABASE_URL'] / "
               "os.environ['SUPABASE_KEY'] 读 —— lane_bot 已把它们放进你的环境;缺了就报错退出,别去找文件。")


def secrets_verdict(tool: str, inp: dict) -> str | None:
    """纯函数。读 / 打印密钥文件或密钥变量 ⇒ 理由。"""
    if tool == "Bash":
        cmd = str(inp.get("command") or "")
        return WHY_SECRETS if (_ENV_FILE.search(cmd) or _PRINT_ENV.search(cmd)) else None
    if tool in ("Read", "Grep", "Glob"):
        target = " " + " ".join(str(inp.get(k) or "") for k in ("file_path", "path", "pattern", "glob"))
        return WHY_SECRETS if _ENV_FILE.search(target) else None
    return None


#: 降落守卫(S-705)。阈值单位 = 转录里 message.content 的 JSON 字符数(见文件头的实测)。
SOFT_CHARS = 360_000
HARD_CHARS = 440_000
READ_MAX_LINES = 400
_LANDING_BASH = re.compile(
    r"^\s*(?:cd\s+\S+\s*&&\s*)?(?:git\s+(?:add|commit|push|status|diff|log|fetch|switch|rebase)\b|"
    r"python3\s+scripts/task_board\.py|bash\s+scripts/preflight\.sh|mv\s|ls\s|wc\s)")
_PY_RUN = re.compile(r"\b(?:python3?|pytest)\b")
_TRUNCATED = re.compile(r"\|\s*(?:tail|head|wc|grep)\b|>\s*\S|<<")


def transcript_chars(path: str) -> int:
    """转录(jsonl)里所有 message.content 的字符数 —— 上下文大小的代理。读不到 ⇒ 0(不拦)。"""
    n = 0
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                i = line.find('"content"')
                if i < 0:
                    continue
                try:
                    msg = json.loads(line).get("message") or {}
                except ValueError:
                    continue
                c = msg.get("content")
                if c:
                    n += len(c) if isinstance(c, str) else len(json.dumps(c, ensure_ascii=False))
    except OSError:
        return 0
    return n


def landing_verdict(tool: str, inp: dict, used: int, soft: int = SOFT_CHARS, hard: int = HARD_CHARS) -> str | None:
    """纯函数。上下文用量 used ≥ hard ⇒ 全拦;≥ soft ⇒ 只放行降落工具;否则 None。"""
    if used >= hard:
        return (f"拦下:上下文已用 {used // 1000}k 字符(上限附近)。**不要再调用任何工具** —— 现在就写最终回复:做了什么、"
                "交付在哪(已推的分支 / 已落的路径)、测得的原始数字、还差什么。没交付的部分如实写「未完成」,下一轮接着做。")
    if used >= soft:
        ok = False
        if tool == "Bash":
            ok = bool(_LANDING_BASH.match(str(inp.get("command") or "")))
        elif tool in ("Write", "Edit", "MultiEdit"):
            ok = "/tasks/T-" in str(inp.get("file_path") or "") or "/_reports/" in str(inp.get("file_path") or "")
        if not ok:
            return (f"拦下:上下文已用 {used // 1000}k 字符,再读 / 再探就会以「Prompt is too long」中断、什么都交不出(11-02 三个 lane 同时发生)。"
                    "**现在降落**:① 卡 status / notes 写已测得的值 ② python3 scripts/task_board.py ③ bash scripts/preflight.sh | tail -20 "
                    "④ git add <允许的路径> → commit → push -u origin <lane>/T-NNN ⑤ 最终回复写清还差什么。只放行这些。")
    return None


def read_too_long(inp: dict, max_lines: int = READ_MAX_LINES) -> str | None:
    """Read 不带 limit 且文件行数 > max_lines ⇒ 理由。文件读不到 ⇒ None。"""
    if inp.get("limit"):
        return None
    path = str(inp.get("file_path") or "")
    try:
        with open(path, "rb") as f:
            n = sum(1 for _ in f)
    except OSError:
        return None
    if n > max_lines:
        return (f"拦下:{path.rsplit('/', 1)[-1]} 有 {n} 行,整份读进上下文是「Prompt is too long」的主因。"
                f"先 `grep -n <关键词>` 定位,再 Read 带 offset + limit(≤ {max_lines // 2})。")
    return None


def truncated_command(cmd: str) -> str | None:
    """跑 python3 / pytest 而没截断输出 ⇒ 补上 tail 的新命令;否则 None。多行 / heredoc / 已截断 / 已重定向的不动。"""
    if "\n" in cmd or not _PY_RUN.search(cmd) or _TRUNCATED.search(cmd):
        return None
    return cmd.rstrip().rstrip(";") + " 2>&1 | tail -n 80"


def verdict(tool: str, inp: dict, cwd: str = "") -> str | None:
    """返回拦截理由;None = 放行。纯函数,测试直接调。cwd = 钩子输入里会话当前目录(S-559)。"""
    why = secrets_verdict(tool, inp)
    if why:
        return why
    if tool == "Bash":
        cmd = str(inp.get("command") or "")
        if _GIT_WRITE.search(cmd) and _targets_main(cmd, cwd):
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
    tool, inp, cwd = str(ev.get("tool_name") or ""), ev.get("tool_input") or {}, str(ev.get("cwd") or "")
    if "--head" in sys.argv[1:]:
        why = head_verdict(str(inp.get("command") or ""), cwd) if tool == "Bash" else None
    else:
        why = (verdict(tool, inp, cwd)
               or landing_verdict(tool, inp, transcript_chars(str(ev.get("transcript_path") or "")))
               or (read_too_long(inp) if tool == "Read" else None))
    if why:
        print(why, file=sys.stderr)
        return 2
    if "--head" not in sys.argv[1:] and tool == "Bash":
        new = truncated_command(str(inp.get("command") or ""))
        if new:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                                     "updatedInput": {**inp, "command": new}}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
