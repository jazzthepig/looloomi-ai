"""lane_bot —— 不用 Jazz 开 terminal,A / B / C 也会醒来干活(S-503)。

为什么:Jazz 10-07「a b c 还是要我在 claude code 发起对话才行动」。lane 是 Claude Code 会话(接 MiniMax),
没人输入就不动 —— 合并流程自动化了(S-500),派活和交付之间还卡着「Jazz 去对应 terminal 打一句话」。

怎么做:launchd 每 10 分钟跑一次本脚本(另外 `.lane_bot/wake/` 里一出现文件就立刻跑)。对每个 lane:
    醒的条件  wake 文件(Seth 派卡 / 回复时写)    或   距上次 ≥ every_min 且名下有 open / claimed 的卡
    不醒      不在 active_hours;今天已满 max_runs_per_day;该目录里已经开着一个 claude(Jazz 在用);上一轮还没完
醒了就在 lane 平时的目录里用无界面模式跑一轮:`claude -p <prompt> --max-turns N --permission-mode acceptEdits
--allowedTools <白名单>`,经 `zsh -lic` 启动 —— 和 Jazz 在 terminal 里打开 claude 读的是同一份配置(MiniMax 连接),
key 不经过本脚本、不写进任何文件。lane 的最终回复由本脚本加锁追加进 MINIMAX_SYNC(lane 自己不编辑 SYNC:
三个 lane 同时整文件改写会互相覆盖)。

不做的事:推 main(pre-push 钩子)、越出卡的范围(CI + seth_bot 的 check_pr_scope)、rm、改自己的缰绳
(scripts/lane_bot/ 在全局禁区)。暂停:touch .lane_bot/PAUSE;单个 lane:lanes.json 里 enabled=false。

手动:  python3 scripts/lane_bot/lane_bot.py --dry-run          看谁会醒、命令是什么
        python3 scripts/lane_bot/lane_bot.py --once lane-b      前台立刻跑 B 一轮(第一次装好后先这样试)
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BOT = ROOT / ".lane_bot"
WAKE, RUNS, STATE, LOG = BOT / "wake", BOT / "runs", BOT / "state.json", BOT / "log.txt"
SYNC = ROOT / "MINIMAX_SYNC.md"
SYNC_SOFT_CAP = 76_000

ALLOWED_TOOLS = [
    "Read", "Edit", "Write", "Glob", "Grep",
    "Bash(python3:*)", "Bash(bash scripts/preflight.sh:*)",
    "Bash(git fetch:*)", "Bash(git switch:*)", "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)",
    "Bash(git show:*)", "Bash(git add:*)", "Bash(git commit:*)",
    # 「:*」是前缀匹配:只放行以 `git push -u origin lane-` 开头的推送;推 main 另有 pre-push 钩子兜底。
    "Bash(git push -u origin lane-:*)", "Bash(git push origin lane-:*)", "Bash(git rebase origin/main)",
    "Bash(cd:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)", "Bash(grep:*)",
    "Bash(mkdir:*)", "Bash(mv:*)", "Bash(cp:*)",
]
# 工具白名单逐项作为独立参数传(模式里有空格):zsh 的 ${(@s:,:)…} 按逗号拆、每项保持一个词。
# unset INTERNAL_TOKEN:lane 不需要它;它出现在 shell 环境里时,preflight 的 schema-drift 检查会对线上 401(10-07 B 撞上)。
_LAUNCH = ('unset INTERNAL_TOKEN; cd "$LANE_CWD" && exec "$LANE_CMD" -p "$LANE_PROMPT" --output-format stream-json --verbose '
           '--max-turns "$LANE_TURNS" --permission-mode acceptEdits --settings "$LANE_SETTINGS" '
           '--allowedTools "${(@s:,:)LANE_TOOLS}"')


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def log(msg: str) -> None:
    BOT.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{now():%Y-%m-%dT%H:%M:%SZ} {msg}\n")


def load_config() -> dict:
    return json.loads((HERE / "lanes.json").read_text(encoding="utf-8"))


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def actionable_cards(lane: str) -> list[str]:
    out = []
    for p in sorted((ROOT / "tasks").glob("T-*.json")):
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if c.get("owner") == lane and c.get("status") in ("open", "claimed"):
            out.append(c["id"])
    return out


def decide(lane: str, cfg: dict, st: dict, *, woken: bool, cards: list[str], local_hour: int,
           today: str, at: dt.datetime, busy: bool) -> tuple[bool, str]:
    """纯函数:醒不醒、为什么。测试直接调。"""
    lc = cfg["lanes"][lane]
    if not lc.get("enabled", True):
        return False, "disabled"
    if busy:
        return False, "这个目录里已经开着一个 claude(Jazz 在用或上一轮未完)"
    s = st.get(lane, {})
    if s.get("day") == today and s.get("runs_today", 0) >= cfg["max_runs_per_day"]:
        return False, f"今天已跑满 {cfg['max_runs_per_day']} 轮"
    lo, hi = cfg["active_hours"]
    if not (lo <= local_hour < hi):
        return False, "不在 active_hours"
    if woken:
        return True, "Seth 唤醒"
    if not cards:
        return False, "名下没有 open / claimed 的卡"
    last = s.get("last_run")
    if last and (at - dt.datetime.fromisoformat(last)).total_seconds() < cfg["every_min"] * 60:
        return False, "未到间隔"
    return True, f"定时({', '.join(cards[:3])})"


def interactive_claude_cwds() -> set[str]:
    """正在运行的 claude 进程的工作目录(macOS:ps + lsof)。拿不到就返回空集 —— 只影响『跳过』,不影响安全。"""
    try:
        ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    cwds = set()
    for line in ps.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if "claude" not in cmd or "lane_bot" in cmd or not pid.isdigit():
            continue
        try:
            out = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True,
                                 text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        cwds.update(Path(l[1:]).resolve().as_posix() for l in out.splitlines() if l.startswith("n"))
    return cwds


def build_prompt(lane: str, lc: dict, reason: str, task: str = "") -> str:
    """task = Seth 写进 wake 文件的那件事(一两句话);没有就是「名下最靠前的卡」。执行要极简:给一件具体的事,不让 lane 自己通读背景去找。"""
    tpl = (HERE / "prompt.md").read_text(encoding="utf-8")
    cards = actionable_cards(lane)
    task = task.strip() or (f"你名下最靠前的卡 {cards[0]}:按卡上的 acceptance 做到能交付" if cards else "没有派给你的事 —— 只回一行说明")
    return tpl.format(name=lc["name"], lane=lane, short=lane[-1].upper(), reason=reason, repo=ROOT.as_posix(),
                      worktree=os.path.expanduser(lc["worktree"]), task=task)


def guard_settings() -> Path:
    """每一轮都装上的 PreToolUse 钩子:lane 不在主目录做 git 写操作、不往主目录写文件(10-08 事故)。

    白名单拦不住 —— --allowedTools 是追加在用户自己的权限之上的,而 terminal 里的 claude 早已放行 git。
    钩子对每次工具调用都跑,退出码 2 = 拦下。"""
    BOT.mkdir(parents=True, exist_ok=True)
    f = BOT / "guard_settings.json"
    guard = ROOT / "scripts" / "lane_bot" / "guard_main_dir.py"
    f.write_text(json.dumps({"hooks": {"PreToolUse": [{
        "matcher": "Bash|Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [{"type": "command", "command": f'python3 "{guard}"'}]}]}}, ensure_ascii=False), encoding="utf-8")
    return f


def launch_argv(cfg: dict) -> list[str]:
    """不拼 shell 字符串:所有可变内容走环境变量,zsh 只展开带引号的变量(测试钉住)。"""
    return [os.environ.get("LANE_BOT_ZSH", "/bin/zsh"), "-lic", _LAUNCH]


def append_to_sync(lane: str, lc: dict, text: str, meta: str) -> None:
    head = f"\n\n## §{lane[-1].upper()}-auto-{now():%m%d-%H%M} — {lc['name']} 自动轮次(lane_bot,{meta})\n\n"
    body = text.strip()[:3000] or "(本轮没有最终回复)"
    lock = BOT / "sync.lock"
    with lock.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        with SYNC.open("a", encoding="utf-8") as f:
            f.write(head + body + "\n")
    n = len(SYNC.read_text(encoding="utf-8"))
    if n >= SYNC_SOFT_CAP:
        log(f"⚠ MINIMAX_SYNC {n} 字符 ≥ {SYNC_SOFT_CAP} —— Seth 的合并轮需要归档")


def parse_stream(out: str, max_turns: int) -> tuple[dict, str]:
    """stream-json 的每一行是一个事件;最后的 type=result 是收尾。到步数上限时没有 result 文本 ——
    那时贴进 SYNC 的是一句人话 + 最后在做什么,不是一段原始 JSON(10-07 B 第一轮就是这样把 JSON 尾巴贴进了 SYNC)。"""
    events = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    text = (final.get("result") or "").strip()
    if text:
        return final, text
    last_said, last_did = "", ""
    for e in events:
        if e.get("type") != "assistant":
            continue
        for c in (e.get("message") or {}).get("content") or []:
            if c.get("type") == "text" and c.get("text", "").strip():
                last_said = c["text"].strip()
            elif c.get("type") == "tool_use":
                inp = c.get("input") or {}
                last_did = f"{c.get('name')}: {inp.get('command') or inp.get('file_path') or ''}"[:200]
    why = {"error_max_turns": f"到 {max_turns} 步上限,没有收尾"}.get(final.get("subtype", ""), "没有最终回复")
    text = f"({why})\n最后说的:{last_said[-600:] or '—'}\n最后在做:{last_did or '—'}"
    return final, text


def run_lane(lane: str, cfg: dict, reason: str, dry: bool = False, task: str = "") -> dict:
    lc = cfg["lanes"][lane]
    cwd = os.path.expanduser(lc["cwd"])
    env = dict(os.environ, LANE_CWD=cwd, LANE_CMD=cfg.get("command", "claude"),
               LANE_PROMPT=build_prompt(lane, lc, reason, task), LANE_TURNS=str(cfg["max_turns"]),
               LANE_TOOLS=",".join(ALLOWED_TOOLS), LANE_SETTINGS=str(guard_settings()))
    if dry:
        return {"lane": lane, "reason": reason, "cwd": cwd, "argv": launch_argv(cfg), "tools": ALLOWED_TOOLS}
    RUNS.mkdir(parents=True, exist_ok=True)
    started = now()
    p = subprocess.Popen(launch_argv(cfg), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    try:
        out, err = p.communicate(timeout=cfg["timeout_min"] * 60)
        timed_out = False
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGTERM)
        out, err = p.communicate()
        timed_out = True
    res: dict = {"lane": lane, "reason": reason, "task": task[:500], "started": started.isoformat(), "exit": p.returncode,
                 "timed_out": timed_out, "seconds": round((now() - started).total_seconds())}
    j, text = parse_stream(out, cfg["max_turns"])
    res.update({k: j.get(k) for k in ("subtype", "num_turns", "total_cost_usd", "session_id")})
    if timed_out:
        text = f"(超时 {cfg['timeout_min']} 分钟被终止)\n" + text
    if not out.strip():
        text = f"(没有任何输出:exit={p.returncode})\n" + (err or "")[-600:]
    stem = RUNS / f"{lane}-{started:%Y%m%dT%H%M%SZ}"
    stem.with_suffix(".jsonl").write_text(out, encoding="utf-8")          # 完整过程:每一步做了什么
    stem.with_suffix(".json").write_text(
        json.dumps({**res, "result": text, "stderr_tail": (err or "")[-2000:]}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    append_to_sync(lane, lc, text, f"{reason};{res.get('num_turns') or '?'} 步;{res['seconds']} 秒")
    return res


REVIEW_OF = {"lane-a": "lane-b", "lane-b": "lane-c", "lane-c": "lane-a"}   # 交叉复核轮转:A 查 B,B 查 C,C 查 A


def review_tasks(cfg: dict, st: dict, today: str, local_hour: int) -> dict[str, str]:
    """每天一次交叉复核(Jazz 10-07:让 lane 们定时互相验证 —— 他手动让 C 复核 C 自己的自动轮次,一次就找出三个问题)。
    到 review_hour 之后,给今天还没复核过的 lane 派一条复核任务。纯函数:返回 {复核者: 任务原文}。"""
    hour = cfg.get("review_hour")
    if hour is None or local_hour < hour:
        return {}
    out = {}
    for lane, target in REVIEW_OF.items():
        if lane not in cfg["lanes"] or (st.get(lane) or {}).get("review_day") == today:
            continue
        out[lane] = (
            f"交叉复核(每天一次):复核 {target} 今天的自动轮次。材料:`{RUNS.as_posix()}/` 里 {target}-{today.replace('-', '')}*.json"
            f"(每轮的任务原文与最终回复)和同名 .jsonl(每一步做了什么),以及它交付的文件 / 分支;今天没有就复核它最近一次交付。"
            "问三件事:① 它回答的是不是被问的问题(对照任务原文,和 MINIMAX_SYNC 里点名它的最新 §Seth 段);"
            "② 判据与数据站不站得住(偷换题面、用了已撤回的判据、读了不存在的列、偷看未来、结论超出证据、没有随机 / 零信号对照);"
            "③ 漏了什么该看的(高维:风格 × 周期、多个时间尺度、和随机组合比)。"
            "列 ≤ 5 条,按严重排序,每条附证据(文件:行 或 数据)。只读,不改对方任何文件;值得返工的写「@seth 建议返工:…」。")
    return out


def run_summary(jsonl: Path) -> dict:
    """从一轮的完整记录里取出:用的模型、步数、写了哪些文件、推了哪些分支、跑了哪些命令。
    回答 Jazz 10-07「我怎么知道它们到底有没有做事、用的是谁的算力」。"""
    out: dict = {"model": None, "auth": None, "writes": [], "pushes": [], "commands": 0, "tokens_in": 0, "tokens_out": 0}
    for line in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("{"):
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "system" and e.get("subtype") == "init":
            out["model"], out["auth"] = e.get("model"), e.get("apiKeySource")
        elif e.get("type") == "assistant":
            for c in (e.get("message") or {}).get("content") or []:
                if c.get("type") != "tool_use":
                    continue
                inp = c.get("input") or {}
                if c.get("name") in ("Write", "Edit") and inp.get("file_path"):
                    out["writes"].append(inp["file_path"])
                elif c.get("name") == "Bash":
                    out["commands"] += 1
                    cmd = inp.get("command") or ""
                    if "git push" in cmd:
                        out["pushes"].append(cmd[:120])
        elif e.get("type") == "result":
            for u in (e.get("modelUsage") or {}).values():
                out["tokens_in"] += (u.get("inputTokens") or 0) + (u.get("cacheReadInputTokens") or 0)
                out["tokens_out"] += u.get("outputTokens") or 0
    out["writes"] = sorted(set(out["writes"]))
    return out


def status(n: int = 3) -> None:
    """python3 scripts/lane_bot/lane_bot.py --status —— 每个 lane 最近几轮:何时、为什么、做了什么、用了谁的模型。"""
    cfg = load_config()
    busy = interactive_claude_cwds()
    print(f"此刻开着的 claude 会话目录(lane_bot 会让开这些目录):{sorted(busy) or '无'}")
    for lane, lc in cfg["lanes"].items():
        cwd = Path(os.path.expanduser(lc["cwd"])).resolve().as_posix()
        print(f"\n══ {lane}  目录 {cwd}  {'← 你正开着' if cwd in busy else ''}")
        runs = sorted(RUNS.glob(f"{lane}-*.json"))[-n:]
        if not runs:
            print("   还没有自动轮次")
        for r in runs:
            d = json.loads(r.read_text(encoding="utf-8"))
            ok = d.get("exit") == 0 and not d.get("timed_out")
            print(f"   {'✓' if ok else '✗'} {d.get('started', '')[:16]}Z  {d.get('num_turns') or '?'} 步 {d.get('seconds')} 秒 —— {d.get('reason')}")
            if d.get("task"):
                print(f"     任务:{d['task'][:110]}")
            jl = r.with_suffix(".jsonl")
            if jl.exists():
                sm = run_summary(jl)
                print(f"     模型:{sm['model']}(认证方式 {sm['auth']});读入 {sm['tokens_in']:,} / 写出 {sm['tokens_out']:,} tokens;命令 {sm['commands']} 条")
                for w in sm["writes"][:6]:
                    print(f"     写了:{w}")
                for ps in sm["pushes"]:
                    print(f"     推送:{ps}")
            first = (d.get("result") or "").strip().splitlines()[:3]
            for l in first:
                print(f"     回复:{l[:110]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", metavar="LANE")
    ap.add_argument("--status", action="store_true", help="每个 lane 最近几轮做了什么、用了谁的模型")
    a = ap.parse_args()
    if a.status:
        status()
        return 0
    cfg = load_config()
    BOT.mkdir(exist_ok=True)
    WAKE.mkdir(exist_ok=True)
    (BOT / "heartbeat").write_text(f"{now():%Y-%m-%dT%H:%M:%SZ}\n", encoding="utf-8")
    if (BOT / "PAUSE").exists() and not a.once:
        return 0
    st = load_state()
    at, local = now(), dt.datetime.now()
    today = local.strftime("%Y-%m-%d")
    busy = interactive_claude_cwds()
    if not a.once and not a.dry_run:
        for lane, task in review_tasks(cfg, st, today, local.hour).items():
            w = WAKE / lane
            if not w.exists():                       # 已有待办任务就先做那件,复核下一次检查再派
                w.write_text(task, encoding="utf-8")
                st.setdefault(lane, {})["review_day"] = today
                log(f"→ {lane} 今日交叉复核 {REVIEW_OF[lane]}")
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    lanes = [a.once] if a.once else list(cfg["lanes"])
    stale = (cfg["timeout_min"] + 10) * 60
    todo: list[tuple[str, str, str]] = []
    for lane in lanes:
        lc = cfg["lanes"][lane]
        cwd = Path(os.path.expanduser(lc["cwd"])).resolve().as_posix()
        wake, lock = WAKE / lane, BOT / f"{lane}.lock"
        locked = lock.exists() and (at.timestamp() - lock.stat().st_mtime) < stale
        if a.once:
            go = cwd not in busy and not locked
            why = "Jazz 手动" if go else "这个目录里已经开着一个 claude,或上一轮未完"
        else:
            go, why = decide(lane, cfg, st, woken=wake.exists(), cards=actionable_cards(lane), local_hour=local.hour,
                             today=today, at=at, busy=(cwd in busy or locked))
        if a.dry_run:
            print(json.dumps({"lane": lane, "wake": go, "why": why,
                              **(run_lane(lane, cfg, why, dry=True) if go else {})}, ensure_ascii=False, indent=1))
        elif go:
            task = wake.read_text(encoding="utf-8") if wake.exists() else ""
            wake.unlink(missing_ok=True)
            lock.write_text(str(os.getpid()))
            s = st.setdefault(lane, {})
            if s.get("day") != today:
                s.update(day=today, runs_today=0)
            s["runs_today"] = s.get("runs_today", 0) + 1
            s["last_run"] = at.isoformat()
            todo.append((lane, why, task))
    if todo:
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")

    def one(lane: str, why: str, task: str) -> None:
        try:
            res = run_lane(lane, cfg, why, task=task)
            ok = res.get("exit") == 0 and not res["timed_out"]
            log(f"{'✓' if ok else '✗'} {lane} {why} → exit={res.get('exit')} {res.get('num_turns') or '?'} 步 {res['seconds']}s")
        except Exception as e:  # noqa: BLE001 — 一个 lane 崩了不能挡其他 lane,但必须留痕
            log(f"✗ {lane} {type(e).__name__}: {e}")
        finally:
            (BOT / f"{lane}.lock").unlink(missing_ok=True)

    threads = [threading.Thread(target=one, args=t) for t in todo]   # 三个 lane 各自的目录,并行;SYNC 追加有锁
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
