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
    "Bash(python3:*)", "Bash(bash scripts/preflight.sh)",
    "Bash(git fetch:*)", "Bash(git switch:*)", "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)",
    "Bash(git show:*)", "Bash(git add:*)", "Bash(git commit:*)",
    # 「:*」是前缀匹配:只放行以 `git push -u origin lane-` 开头的推送;推 main 另有 pre-push 钩子兜底。
    "Bash(git push -u origin lane-:*)", "Bash(git push origin lane-:*)", "Bash(git rebase origin/main)",
    "Bash(cd:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)", "Bash(grep:*)",
    "Bash(mkdir:*)", "Bash(mv:*)", "Bash(cp:*)",
]
# 工具白名单逐项作为独立参数传(模式里有空格):zsh 的 ${(@s:,:)…} 按逗号拆、每项保持一个词。
_LAUNCH = ('cd "$LANE_CWD" && exec "$LANE_CMD" -p "$LANE_PROMPT" --output-format json '
           '--max-turns "$LANE_TURNS" --permission-mode acceptEdits --allowedTools "${(@s:,:)LANE_TOOLS}"')


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


def build_prompt(lane: str, lc: dict, reason: str) -> str:
    tpl = (HERE / "prompt.md").read_text(encoding="utf-8")
    return tpl.format(name=lc["name"], lane=lane, short=lane[-1].upper(), reason=reason, repo=ROOT.as_posix(),
                      worktree=os.path.expanduser(lc["worktree"]))


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


def run_lane(lane: str, cfg: dict, reason: str, dry: bool = False) -> dict:
    lc = cfg["lanes"][lane]
    cwd = os.path.expanduser(lc["cwd"])
    env = dict(os.environ, LANE_CWD=cwd, LANE_CMD=cfg.get("command", "claude"),
               LANE_PROMPT=build_prompt(lane, lc, reason), LANE_TURNS=str(cfg["max_turns"]),
               LANE_TOOLS=",".join(ALLOWED_TOOLS))
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
    res: dict = {"lane": lane, "reason": reason, "started": started.isoformat(), "exit": p.returncode,
                 "timed_out": timed_out, "seconds": round((now() - started).total_seconds())}
    try:
        j = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
    except ValueError:
        j = {}
    res.update({k: j.get(k) for k in ("subtype", "num_turns", "total_cost_usd", "session_id")})
    text = j.get("result") or ""
    if not text:
        text = f"(未拿到最终回复:exit={p.returncode}{',超时' if timed_out else ''})\n" + (err or out)[-800:]
    (RUNS / f"{lane}-{started:%Y%m%dT%H%M%SZ}.json").write_text(
        json.dumps({**res, "result": text, "stderr_tail": (err or "")[-2000:]}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    append_to_sync(lane, lc, text, f"{reason};{res.get('num_turns') or '?'} 步;{res['seconds']} 秒")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", metavar="LANE")
    a = ap.parse_args()
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
    lanes = [a.once] if a.once else list(cfg["lanes"])
    stale = (cfg["timeout_min"] + 10) * 60
    todo: list[tuple[str, str]] = []
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
            wake.unlink(missing_ok=True)
            lock.write_text(str(os.getpid()))
            s = st.setdefault(lane, {})
            if s.get("day") != today:
                s.update(day=today, runs_today=0)
            s["runs_today"] = s.get("runs_today", 0) + 1
            s["last_run"] = at.isoformat()
            todo.append((lane, why))
    if todo:
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")

    def one(lane: str, why: str) -> None:
        try:
            res = run_lane(lane, cfg, why)
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
