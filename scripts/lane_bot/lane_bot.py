"""lane_bot —— 不用 Jazz 开 terminal,A / B / C 也会醒来干活(S-503)。

为什么:Jazz 10-07「a b c 还是要我在 claude code 发起对话才行动」。lane 是 Claude Code 会话(接 MiniMax),
没人输入就不动 —— 合并流程自动化了(S-500),派活和交付之间还卡着「Jazz 去对应 terminal 打一句话」。

怎么做:launchd 每 10 分钟跑一次本脚本(另外 `.lane_bot/wake/` 里一出现文件就立刻跑)。对每个 lane:
    醒的条件  wake 文件(Seth 派卡 / 回复时写)    或   距上次 ≥ every_min 且名下有 open / claimed、还没在分支上交成 in_review 的卡
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
#: 2026-10-20(service_role 泄露后 Jazz 裁定):lane 只拿 publishable key。登录 shell 读完 rc 之后先清掉一切可能带进来的
#: 写权限 key,再只放回 lane_bot 交给它的那一把(lane_db_env 已验过是 sb_publishable_)。
_SCRUB = ("unset INTERNAL_TOKEN EXECUTOR_TOKEN SUPABASE_SERVICE_KEY SUPABASE_SERVICE_ROLE_KEY SUPABASE_SECRET_KEY "
          "SUPABASE_KEY SUPABASE_URL HL_API_WALLET_PRIVATE_KEY; "
          '[ -n "$LANE_SUPABASE_KEY" ] && export SUPABASE_URL="$LANE_SUPABASE_URL" SUPABASE_KEY="$LANE_SUPABASE_KEY"; '
          "unset LANE_SUPABASE_KEY LANE_SUPABASE_URL; ")
#: 11-02(S-706)备用后端:主后端(MiniMax M Plan)5 小时 / 每周窗口用完时,用 Jazz 放在 lane_fallback.env 里的
#: 另一个 Anthropic 兼容端点(第二个订阅、别家 coding plan、或本机 Ollama / LM Studio)。值只从那个文件来,不进日志。
_FALLBACK = ('[ -n "$LANE_FB_URL" ] && export ANTHROPIC_BASE_URL="$LANE_FB_URL" ANTHROPIC_AUTH_TOKEN="$LANE_FB_TOKEN" '
             'ANTHROPIC_MODEL="$LANE_FB_MODEL" ANTHROPIC_SMALL_FAST_MODEL="$LANE_FB_MODEL" && unset ANTHROPIC_API_KEY; '
             'unset LANE_FB_URL LANE_FB_TOKEN LANE_FB_MODEL; ')
_LAUNCH = (_SCRUB + _FALLBACK + 'cd "$LANE_CWD" && exec "$LANE_CMD" -p "$LANE_PROMPT" --output-format stream-json --verbose '
           '--max-turns "$LANE_TURNS" --permission-mode acceptEdits --settings "$LANE_SETTINGS" '
           '--add-dir "$LANE_WORKTREE" --add-dir "$LANE_MAIN" --add-dir "$LANE_DATA" '
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


WAITING = ("in_review", "done")


def branch_card_status(lane: str, cid: str) -> str | None:
    """卡在 lane 自己分支上的状态。lane 交付时只在分支上把卡改成 in_review,main 上那张还是 open / claimed,
    要等 Seth 合并才变 —— 只看 main 的话,lane_bot 会一轮轮把 lane 叫醒去「重验」一张已经交了的卡。"""
    for ref in (f"origin/{lane}/{cid}", f"{lane}/{cid}"):
        try:
            r = subprocess.run(["git", "--no-optional-locks", "-C", str(ROOT), "show", f"{ref}:tasks/{cid}.json"],
                               capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode == 0:
            try:
                return json.loads(r.stdout).get("status")
            except ValueError:
                return None
    return None


def actionable_cards(lane: str, branch_status=branch_card_status) -> list[str]:
    """名下 open / claimed、且没有在自己分支上交成 in_review / done 的卡。

    S-558(10-13 实测):过去 27 小时 32 轮里约 16 轮是「本轮无新代码,只重验」—— 全是分支上已 in_review、
    main 上还是 claimed 的卡(lane-b T-059 九轮、lane-c T-036 / T-085 五轮、lane-a T-083 两轮)。等审的卡不再叫醒 lane;
    Seth 退回时写 wake 文件,lane 照样会醒。"""
    out = []
    for p in sorted((ROOT / "tasks").glob("T-*.json")):
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if c.get("owner") == lane and c.get("status") in ("open", "claimed"):
            if branch_status(lane, c["id"]) in WAITING:
                continue
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


def guard_settings(lane: str = "", dirs: tuple[str, ...] = (), env: dict[str, str] | None = None) -> Path:
    """每一轮都装上的 PreToolUse 钩子:lane 不在主目录做 git 写操作、不往主目录写文件(10-08 事故)。

    白名单拦不住 —— --allowedTools 是追加在用户自己的权限之上的,而 terminal 里的 claude 早已放行 git。
    钩子对每次工具调用都跑,退出码 2 = 拦下。

    ⚠️ 10-08 第二次:装上 --settings 之后,lane-c(cwd 在 Mac 数据根)连自己的 worktree 和任务卡都读不到了 ——
    「允许的工作目录」只剩 cwd。所以把 lane 的 worktree 与主仓库(只读用;写由钩子拦)显式写进
    additionalDirectories,启动命令再带 --add-dir,两处都给。"""
    BOT.mkdir(parents=True, exist_ok=True)
    f = BOT / (f"guard_settings-{lane}.json" if lane else "guard_settings.json")
    guard = ROOT / "scripts" / "lane_bot" / "guard_main_dir.py"
    doc: dict = {"permissions": {"additionalDirectories": list(dirs)}, "hooks": {"PreToolUse": [{
        "matcher": "Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Grep|Glob",
        "hooks": [{"type": "command", "command": f'python3 "{guard}"'}]}]}}
    if env:                      # 备用后端:--settings 的 env 优先级高于用户 settings 里的 MiniMax 配置
        doc["env"] = dict(env)
    f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    os.chmod(f, 0o600)
    return f


#: Minimax 研究产物的归宿(CLAUDE.md 规则 3a)。10-15:lane-b 的 cwd 在自己的 worktree,写不进数据根,
#: T-101 的交付只好留在 worktree 里的 lane-b-scratch/ —— 每个 lane 都显式带上这个目录。
DATA_ROOT = "/Volumes/CometCloudAI/cometcloud-local"


def data_root(fallback: str) -> str:
    """数据盘挂着就给数据根;没挂(或不在 Mac 上)给 lane 自己的 worktree,不让 --add-dir 指向不存在的路径。"""
    return DATA_ROOT if os.path.isdir(DATA_ROOT) else fallback


#: lane 读库用的 URL + publishable key。文件归 Jazz(chmod 600),lane 自己读不到(guard_main_dir 拦 .cometcloud/ 与 .env)。
LANE_ENV_FILE = Path(os.environ.get("LANE_ENV_FILE", "~/.cometcloud/lane.env")).expanduser()


def lane_db_env(path: Path = LANE_ENV_FILE) -> dict[str, str]:
    """→ {LANE_SUPABASE_URL, LANE_SUPABASE_KEY},只在 key 是 sb_publishable_ 时给;否则 {}(lane 照跑,只是连不上库)。
    宁可连不上,也不把一把能写库的 key 交给跑在第三方中转上的 lane。值不进日志。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    kv: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.removeprefix("export ").split("=", 1)
        kv[k.strip()] = v.strip().strip("'\"")
    url, key = kv.get("SUPABASE_URL", ""), kv.get("SUPABASE_KEY", "")
    if not url.startswith("https://") or not key.startswith("sb_publishable_"):
        log(f"lane.env 不合格(要 https URL + sb_publishable_ key)—— 不给 lane 任何库凭证:{path}")
        return {}
    return {"LANE_SUPABASE_URL": url, "LANE_SUPABASE_KEY": key}


#: 10-20(T-144):每周定时跑的**研究脚本**(不是 lane 的 claude 轮次)—— lanes.json 的 weekly_scripts。
#: 只给 publishable key(SUPABASE_URL / SUPABASE_KEY 两个名字,脚本照 T-142 的写法读),环境里其余一律不带:
#: lane_bot 自己的进程可能带着别的 key,脚本是 lane 写、Seth 合并的代码,不该看到它们。
WEEKLY_TIMEOUT_S = 1800


FALLBACK_ENV_FILE = Path(os.environ.get("LANE_FALLBACK_ENV_FILE", "~/.cometcloud/lane_fallback.env")).expanduser()


def fallback_env(path: Path = FALLBACK_ENV_FILE) -> dict[str, str]:
    """→ {LANE_FB_URL, LANE_FB_TOKEN, LANE_FB_MODEL};文件不在 / 不全 ⇒ {}(没有备用后端)。
    文件归 Jazz(chmod 600):ANTHROPIC_BASE_URL=… ANTHROPIC_AUTH_TOKEN=… ANTHROPIC_MODEL=…。值不进日志。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    kv: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.removeprefix("export ").split("=", 1)
            kv[k.strip()] = v.strip().strip("'\"")
    url, tok, model = kv.get("ANTHROPIC_BASE_URL", ""), kv.get("ANTHROPIC_AUTH_TOKEN", ""), kv.get("ANTHROPIC_MODEL", "")
    if not (url.startswith("http") and tok and model):
        return {}
    return {"LANE_FB_URL": url, "LANE_FB_TOKEN": tok, "LANE_FB_MODEL": model}


# ── 额度预算(S-706,11-02 Jazz「abc 受制于 5 小时 usage limit,不能让整个 harness 停摆」)──
# MiniMax M Plan:5 小时窗口 + 每周窗口各自独立计,按调用次数;用完就 429。10-27 一天撞了 12 次,每次全停 60 分钟。
# 这里把每一轮的调用次数记进 usage.jsonl,醒之前按滚动窗口算还剩多少:① 永远留 reserve_frac 给 Seth 的唤醒
# ② 一小时内不超过窗口均速的 burst 倍(把额度摊开到 5 小时,而不是前两小时烧光、后三小时全停)
# ③ 剩得少就缩单轮步数(min_turns 以下不醒)④ 真撞 429 时按本账算最早一次调用什么时候滚出窗口,到点再起,不是固定 60 分钟
# ⑤ 主后端停着而备用后端在 ⇒ 用备用后端跑(各自记账)。calls_per_window 要按 Jazz 的档位填(lanes.json)。
USAGE = BOT / "usage.jsonl"
OBSERVED_CAP = BOT / "quota_observed_calls"        # 撞 429 时窗口内的调用数 —— 真实上限的观测值,自动压低配置值
DEFAULT_BUDGET = {"window_h": 5, "calls_per_window": 4500, "weekly_calls": 0, "reserve_frac": 0.2, "burst": 1.5,
                  "min_turns": 30}


#: 11-07:MiniMax 的 5 小时额度是**按档重置**的(Jazz:「rate just refreshed」),而这里按滚动窗口记 —— 重置之后,
#: 重置前的调用还在滚动窗口里,lane 被白白挡住一两个小时。Jazz / Seth 知道刚重置时写这个文件(ISO UTC 时刻),
#: 重置时刻之前的调用不再计入。撞 429 的自校准照旧,是这条的安全网。写法:`date -u +%FT%TZ > .lane_bot/quota_reset_at`
RESET_AT = BOT / "quota_reset_at"


def reset_at() -> Optional[dt.datetime]:
    try:
        t = dt.datetime.fromisoformat(RESET_AT.read_text().strip().replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except (OSError, ValueError):
        return None


def observed_cap() -> int:
    try:
        return int(float(OBSERVED_CAP.read_text().strip()))
    except (OSError, ValueError):
        return 0


def effective_cap(cfg_cap: int, observed: int) -> int:
    """纯函数。配置的上限与观测值(撞 429 时窗口内已用次数 × 0.9)取小:档位填高了也不会一直撞。"""
    return min(cfg_cap, int(observed * 0.9)) if observed > 0 else cfg_cap


def record_usage(lane: str, started: dt.datetime, ended: dt.datetime, calls: int, backend: str) -> None:
    BOT.mkdir(exist_ok=True)
    with USAGE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"lane": lane, "start": started.isoformat(), "end": ended.isoformat(), "calls": int(calls),
                            "backend": backend}) + "\n")


def load_usage(days: float = 8.0, at: dt.datetime | None = None) -> list[dict]:
    at = at or now()
    out = []
    try:
        for line in USAGE.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                if (at - dt.datetime.fromisoformat(r["end"])).total_seconds() <= days * 86400:
                    out.append(r)
            except (ValueError, KeyError):
                continue
    except OSError:
        pass
    return out


def calls_since(usage: list[dict], at: dt.datetime, hours: float, backend: str = "primary") -> int:
    """纯函数。最近 hours 小时内(按结束时间)该后端的调用次数。"""
    lo = at - dt.timedelta(hours=hours)
    return sum(int(r.get("calls") or 0) for r in usage
               if r.get("backend", "primary") == backend and dt.datetime.fromisoformat(r["end"]) >= lo)


def budget_turns(cfg: dict, usage: list[dict], at: dt.datetime, *, woken: bool, backend: str = "primary",
                 reset: Optional[dt.datetime] = None) -> tuple[int, str]:
    """纯函数。这一轮最多给几步、为什么(0 = 不醒)。备用后端不限(它的额度我们不知道,撞了再停)。
    reset = 额度最近一次重置的时刻(`quota_reset_at`):之前开始的调用不计。"""
    b = {**DEFAULT_BUDGET, **(cfg.get("budget") or {})}
    if reset is not None and reset <= at:
        usage = [r for r in usage if dt.datetime.fromisoformat(r.get("start") or r["end"]) >= reset]
    cap, hours = effective_cap(int(b["calls_per_window"]), int(b.get("observed") or 0)), float(b["window_h"])
    if backend != "primary" or cap <= 0:
        return int(cfg["max_turns"]), "不按额度限"
    used = calls_since(usage, at, hours, backend)
    reserve = cap * float(b["reserve_frac"]) * (0.25 if woken else 1.0)     # Seth 的唤醒可以动到储备的 3/4
    left = cap - used - reserve
    hourly = calls_since(usage, at, 1.0, backend)
    burst_cap = cap / hours * float(b["burst"])
    if hourly >= burst_cap and not woken:
        return 0, f"这一小时已用 {hourly} 次 ≥ 均速 × burst {burst_cap:.0f},摊开到整个窗口"
    weekly = int(b.get("weekly_calls") or 0)
    if weekly:
        wk_left = weekly - calls_since(usage, at, 24 * 7, backend) - weekly * float(b["reserve_frac"]) * (0.25 if woken else 1.0)
        left = min(left, wk_left)
    turns = int(min(cfg["max_turns"], left))
    if turns < int(b["min_turns"]):
        return 0, f"5 小时窗口已用 {used}/{cap}(含储备 {reserve:.0f}),剩 {max(0, int(left))} 步不够一轮(min_turns {b['min_turns']})"
    return turns, f"窗口已用 {used}/{cap},本轮上限 {turns} 步"


def quota_resume_at(usage: list[dict], at: dt.datetime, hours: float, fallback_min: int) -> dt.datetime:
    """纯函数。撞 429 之后什么时候再试:窗口内最早一次调用滚出窗口的时刻 + 5 分钟;本账里没有调用 ⇒ 固定 fallback_min。"""
    lo = at - dt.timedelta(hours=hours)
    starts = sorted(dt.datetime.fromisoformat(r["start"]) for r in usage
                    if r.get("backend", "primary") == "primary" and dt.datetime.fromisoformat(r["end"]) >= lo)
    if not starts:
        return at + dt.timedelta(minutes=fallback_min)
    return max(starts[0] + dt.timedelta(hours=hours, minutes=5), at + dt.timedelta(minutes=10))


def weekly_due(job: dict, at: dt.datetime, last: str | None) -> bool:
    """纯函数。job = {weekday: 0 = 周一, utc: "HH:MM"}。本周的计划时刻已过、且上次跑在它之前 ⇒ 该跑。"""
    hh, mm = (int(x) for x in str(job["utc"]).split(":"))
    day = at.date() - dt.timedelta(days=(at.weekday() - int(job["weekday"])) % 7)
    sched = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=dt.timezone.utc)
    if at < sched:
        sched -= dt.timedelta(days=7)
    if not last:
        return True
    prev = dt.datetime.fromisoformat(last)
    return (prev if prev.tzinfo else prev.replace(tzinfo=dt.timezone.utc)) < sched


def weekly_env(db: dict[str, str]) -> dict[str, str]:
    """纯函数。脚本的全部环境:PATH / HOME / 语言 + 两个库变量(publishable)。"""
    base = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TZ") if k in os.environ}
    return {**base, "SUPABASE_URL": db["LANE_SUPABASE_URL"], "SUPABASE_KEY": db["LANE_SUPABASE_KEY"]}


def run_weekly(cfg: dict, st: dict, at: dt.datetime) -> None:
    for job in cfg.get("weekly_scripts", []):
        key = f"weekly:{job['name']}"
        if not weekly_due(job, at, st.get(key)):
            continue
        script = (ROOT / job["script"]).resolve()
        if not script.is_file() or ROOT.resolve() not in script.parents:
            log(f"✗ weekly {job['name']}:脚本不在仓库里 —— {job['script']}")
            st[key] = at.isoformat()
            continue
        db = lane_db_env()
        if not db:
            log(f"✗ weekly {job['name']}:没有合格的 publishable key,不跑(下一次检查再试)")
            continue
        try:
            p = subprocess.run([sys.executable, "-I", str(script)], cwd=ROOT, env=weekly_env(db),
                               capture_output=True, text=True, timeout=WEEKLY_TIMEOUT_S)
            code, tail = p.returncode, (p.stdout + p.stderr)[-200:].replace("\n", " ")
        except subprocess.TimeoutExpired:
            code, tail = -1, f"超时 {WEEKLY_TIMEOUT_S}s"
        st[key] = at.isoformat()
        log(f"{'✓' if code == 0 else '✗'} weekly {job['name']} → exit={code} {tail}")

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


def last_assistant_text(out: str) -> str:
    """stream-json 里最后一段 assistant 文本(不是工具调用)。没有 ⇒ ""。"""
    last = ""
    for line in out.splitlines():
        if not line.startswith("{") or '"assistant"' not in line[:40]:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "assistant":
            continue
        for c in (e.get("message") or {}).get("content") or []:
            if c.get("type") == "text" and c.get("text", "").strip():
                last = c["text"].strip()
    return last


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


def run_lane(lane: str, cfg: dict, reason: str, dry: bool = False, task: str = "", turns: int | None = None,
             backend: str = "primary") -> dict:
    lc = cfg["lanes"][lane]
    cwd = os.path.expanduser(lc["cwd"])
    wt = os.path.expanduser(lc.get("worktree") or lc["cwd"])
    turns = int(turns or cfg["max_turns"])
    fb = fallback_env() if backend == "fallback" else {}
    fb_settings = {"ANTHROPIC_BASE_URL": fb["LANE_FB_URL"], "ANTHROPIC_AUTH_TOKEN": fb["LANE_FB_TOKEN"],
                   "ANTHROPIC_MODEL": fb["LANE_FB_MODEL"], "ANTHROPIC_SMALL_FAST_MODEL": fb["LANE_FB_MODEL"]} if fb else None
    ctx = int(lc.get("ctx_tokens") or 115_000)      # 该 lane 实测溢出的估算 token(S-705);软 0.80×、硬 0.95×
    if dry:
        # 11-07:--dry-run 以前也会写 guard_settings-<lane>.json —— 从沙盒跑一次,文件里的钩子路径就成了沙盒路径,
        # 正在跑的 lane 的 Claude Code 热加载设置 ⇒ 每个工具调用都被一个不存在的钩子拦下(lane-c 23:03 整轮零交付)。
        # 干跑只报会怎么起,不碰任何文件。
        return {"lane": lane, "reason": reason, "cwd": cwd, "argv": launch_argv(cfg), "tools": ALLOWED_TOOLS,
                "turns": turns, "backend": backend}
    env = dict(os.environ, LANE_CWD=cwd, LANE_CMD=cfg.get("command", "claude"),
               LANE_CTX_SOFT=str(int(ctx * 0.80)), LANE_CTX_HARD=str(int(ctx * 0.95)),
               LANE_PROMPT=build_prompt(lane, lc, reason, task), LANE_TURNS=str(turns),
               LANE_TOOLS=",".join(ALLOWED_TOOLS), LANE_WORKTREE=wt, LANE_MAIN=str(ROOT),
               LANE_DATA=data_root(wt),
               LANE_SETTINGS=str(guard_settings(lane, (wt, str(ROOT), data_root(wt)), fb_settings)),
               **lane_db_env(), **fb)
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
    j, text = parse_stream(out, turns)
    res["last_said"] = last_assistant_text(out)[-1500:]          # 溢出 / 超时时 lane 最后说的话也要落盘(§Seth-1102f)
    res["ok"] = (p.returncode == 0 and not timed_out and not quota_hit(text) and not context_overflow(text)
                 and j.get("subtype") == "success" and not j.get("is_error"))
    res.update({k: j.get(k) for k in ("subtype", "num_turns", "total_cost_usd", "session_id")})
    res["backend"] = backend
    res["calls"] = sum(1 for line in out.splitlines() if line.startswith("{") and '"assistant"' in line[:40])
    record_usage(lane, started, now(), res["calls"], backend)
    if timed_out:
        text = f"(超时 {cfg['timeout_min']} 分钟被终止)\n" + text
    if not out.strip():
        text = f"(没有任何输出:exit={p.returncode})\n" + (err or "")[-600:]
    stem = RUNS / f"{lane}-{started:%Y%m%dT%H%M%SZ}"
    stem.with_suffix(".jsonl").write_text(out, encoding="utf-8")          # 完整过程:每一步做了什么
    stem.with_suffix(".json").write_text(
        json.dumps({**res, "result": text, "stderr_tail": (err or "")[-2000:]}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    if quota_hit(text) or context_overflow(text):   # 额度报错 / 上下文溢出不进 SYNC(同一句话每 15 分钟一段;10-28 lane-a 复核又报一次)
        log(f"✗ {lane} 本轮无交付({'额度' if quota_hit(text) else '上下文溢出'}),只记在 runs/,不进 SYNC")
    else:
        append_to_sync(lane, lc, text, f"{reason};{res.get('num_turns') or '?'} 步;{res['seconds']} 秒")
    res["text"] = text[:2000]
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
    b = {**DEFAULT_BUDGET, **(cfg.get("budget") or {})}
    at = now()
    usage = load_usage(at=at)
    print(f"额度(S-706):5 小时窗口已用 {calls_since(usage, at, float(b['window_h']))}/{effective_cap(int(b['calls_per_window']), observed_cap())} 次调用"
          f"{'(配置 ' + str(b['calls_per_window']) + ',观测 ' + str(observed_cap()) + ')' if observed_cap() else ''},"
          f"这一小时 {calls_since(usage, at, 1.0)},7 天 {calls_since(usage, at, 168.0)}"
          f"{'(周上限 ' + str(b['weekly_calls']) + ')' if b.get('weekly_calls') else ''};"
          f"主后端{'⏸ 停到 ' + dt.datetime.fromtimestamp(float(QUOTA.read_text().strip()), dt.timezone.utc).strftime('%H:%MZ') if quota_paused(at.timestamp()) else '可用'};"
          f"备用后端{'已配' if fallback_env() else '未配(~/.cometcloud/lane_fallback.env)'}")
    for lane, lc in cfg["lanes"].items():
        cwd = Path(os.path.expanduser(lc["cwd"])).resolve().as_posix()
        print(f"\n══ {lane}  目录 {cwd}  {'← 你正开着' if cwd in busy else ''}")
        runs = sorted(RUNS.glob(f"{lane}-*.json"))[-n:]
        if not runs:
            print("   还没有自动轮次")
        for r in runs:
            d = json.loads(r.read_text(encoding="utf-8"))
            ok = d["ok"] if "ok" in d else (d.get("exit") == 0 and not d.get("timed_out")
                                            and not str(d.get("result") or "").startswith("Prompt is too long"))
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
    ap.add_argument("--run", metavar="LANE", help=argparse.SUPPRESS)      # spawn() 起的子进程:跑一轮就退出
    ap.add_argument("--why", default="", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.status:
        status()
        return 0
    if a.run:
        return child(a.run, a.why)
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
    if not a.once and not a.dry_run:
        run_weekly(cfg, st, at)                  # T-144:每周的研究脚本,与 lane 的模型额度无关
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    backend = "primary"
    if not a.once and not a.dry_run and quota_paused(at.timestamp()):
        if not fallback_env() or quota_paused(at.timestamp(), FB_QUOTA):
            return 0
        backend = "fallback"                      # 主后端停着、备用在 ⇒ 这一轮全部走备用
    usage = load_usage(at=at)
    cfg["budget"] = {**(cfg.get("budget") or {}), "observed": observed_cap()}
    lanes = [a.once] if a.once else list(cfg["lanes"])
    stale = (cfg["timeout_min"] + 10) * 60
    todo: list[tuple[str, str, str]] = []
    for lane in lanes:
        lc = cfg["lanes"][lane]
        cwd = Path(os.path.expanduser(lc["cwd"])).resolve().as_posix()
        wake, lock = WAKE / lane, BOT / f"{lane}.lock"
        locked = lock_held(lock, at.timestamp(), stale)
        if a.once:
            go = cwd not in busy and not locked
            why = "Jazz 手动" if go else "这个目录里已经开着一个 claude,或上一轮未完"
        else:
            go, why = decide(lane, cfg, st, woken=wake.exists(), cards=actionable_cards(lane), local_hour=local.hour,
                             today=today, at=at, busy=(cwd in busy or locked))
        turns = int(cfg["max_turns"])
        if go:
            turns, bwhy = budget_turns(cfg, usage, at, woken=wake.exists(), backend=backend, reset=reset_at())
            if turns <= 0:
                go, why = False, f"额度:{bwhy}"
            else:
                why = f"{why};{bwhy}"
        if a.dry_run:
            print(json.dumps({"lane": lane, "wake": go, "why": why,
                              **(run_lane(lane, cfg, why, dry=True, turns=turns, backend=backend) if go else {})},
                             ensure_ascii=False, indent=1))
        elif go:
            task = wake.read_text(encoding="utf-8") if wake.exists() else ""
            wake.unlink(missing_ok=True)
            lock.write_text(str(os.getpid()))
            s = st.setdefault(lane, {})
            if s.get("day") != today:
                s.update(day=today, runs_today=0)
            s["runs_today"] = s.get("runs_today", 0) + 1
            s["last_run"] = at.isoformat()
            todo.append((lane, why, task, turns, backend))
    if todo:
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")

    if a.once:                                   # Jazz 手动:前台跑完再返回,他要看结果
        for t in todo:
            run_one(cfg, *t)
        return 0
    for t in todo:                               # 定时 / 唤醒:每个 lane 一个脱离的进程,本次检查立刻返回
        spawn(*t)
    return 0


QUOTA = BOT / "quota_until"
FB_QUOTA = BOT / "quota_until_fallback"
QUOTA_BACKOFF_MIN = 60
_QUOTA_MARKS = ("usage limit reached", "Request rejected (429)")


def quota_hit(text: str) -> bool:
    """纯函数。lane 的模型额度用完(MiniMax Token Plan 429)。10-15:三个 lane 撞上之后,每 15 分钟一醒、每轮 1 步就失败,
    还往 SYNC 里追加一段同样的报错 —— 撞上一次就整体停 QUOTA_BACKOFF_MIN 分钟。"""
    return any(m in (text or "") for m in _QUOTA_MARKS)


def context_overflow(text: str) -> bool:
    """纯函数。这一轮的「最终回复」只是一句上下文溢出(lane 整读了大文件)—— 没有交付,贴进 SYNC 只是噪声。"""
    t = (text or "").strip()
    return t.startswith("Prompt is too long") and len(t) < 200


def quota_paused(at_ts: float, f: Path | None = None) -> bool:
    try:
        return at_ts < float((f or QUOTA).read_text().strip())
    except (OSError, ValueError):
        return False


def run_one(cfg: dict, lane: str, why: str, task: str, turns: int | None = None, backend: str = "primary") -> None:
    try:
        res = run_lane(lane, cfg, why, task=task, turns=turns, backend=backend)
        if quota_hit(res.get("text", "")):
            at = now()
            if backend == "primary":
                b = {**DEFAULT_BUDGET, **(cfg.get("budget") or {})}
                usage = load_usage(at=at)
                until = quota_resume_at(usage, at, float(b["window_h"]), QUOTA_BACKOFF_MIN)
                QUOTA.write_text(str(until.timestamp()))
                used = calls_since(usage, at, float(b["window_h"]))
                if used >= 100:                      # 记下观测到的上限(太小的值多半是别的工具在用同一订阅,不记)
                    OBSERVED_CAP.write_text(str(used))
                hint = (f";本账窗口内记了 {used} 次 < calls_per_window {b['calls_per_window']} —— 之后按 {int(used * 0.9)} 算"
                        if used < int(b["calls_per_window"]) * 0.8 else "")
                log(f"⏸ {lane} 主后端额度用完(429)—— 停到 {until:%H:%M}Z(最早一次调用滚出窗口){hint};"
                    + ("备用后端接手" if fallback_env() else "没有备用后端(~/.cometcloud/lane_fallback.env),等窗口"))
            else:
                FB_QUOTA.write_text(str(at.timestamp() + QUOTA_BACKOFF_MIN * 60))
                log(f"⏸ {lane} 备用后端也 429 —— 备用停 {QUOTA_BACKOFF_MIN} 分钟")
            w = WAKE / lane
            if task and not w.exists():          # 这一轮没做成:任务原文放回去,额度恢复后接着做(10-15 两次丢了 Seth 的派活)
                w.write_text(task, encoding="utf-8")
        ok = bool(res.get("ok"))
        log(f"{'✓' if ok else '✗'} {lane} {why} → exit={res.get('exit')} {res.get('num_turns') or '?'} 步 "
            f"{res['seconds']}s · {res.get('calls', '?')} 次调用 · {backend}")
    except Exception as e:  # noqa: BLE001 — 一个 lane 崩了不能挡其他 lane,但必须留痕
        log(f"✗ {lane} {type(e).__name__}: {e}")
    finally:
        (BOT / f"{lane}.lock").unlink(missing_ok=True)


def spawn(lane: str, why: str, task: str, turns: int | None = None, backend: str = "primary") -> int:
    """10-15:原来三个 lane 在本进程的线程里跑、最后 join —— launchd 的这次检查要等最慢的 lane 跑完(上限 60 分钟)
    才返回,而 launchd 不会在上一次没返回时再起一次:B 跑长任务时,写给 A / C 的 wake 文件干等了一个小时。
    现在每个 lane 是一个新会话里的独立进程(launchd 收尾时只清自己的进程组),本次检查立刻返回;
    lane 之间互不等待,同一 lane 不重入靠 lock(里面写子进程 pid,进程不在了锁就不算数)。任务原文经文件传,不进 argv。"""
    (BOT / f"task-{lane}.txt").write_text(task, encoding="utf-8")
    (BOT / f"run-{lane}.json").write_text(json.dumps({"turns": turns, "backend": backend}), encoding="utf-8")
    with open(BOT / "child.log", "a", encoding="utf-8") as errf:
        p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--run", lane, "--why", why],
                             cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=errf, stderr=errf, start_new_session=True)
    (BOT / f"{lane}.lock").write_text(str(p.pid))
    return p.pid


def child(lane: str, why: str) -> int:
    tf = BOT / f"task-{lane}.txt"
    task = tf.read_text(encoding="utf-8") if tf.exists() else ""
    tf.unlink(missing_ok=True)
    rf = BOT / f"run-{lane}.json"
    try:
        opts = json.loads(rf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        opts = {}
    rf.unlink(missing_ok=True)
    run_one(load_config(), lane, why, task, turns=opts.get("turns"), backend=opts.get("backend") or "primary")
    return 0


def lock_held(lock: Path, at_ts: float, stale_s: float) -> bool:
    """锁算数 = 文件在、没过期、且里面写的进程还活着(写不出 pid 的老锁只看时间)。"""
    if not lock.exists() or at_ts - lock.stat().st_mtime >= stale_s:
        return False
    try:
        pid = int(lock.read_text().strip())
    except (ValueError, OSError):
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


if __name__ == "__main__":
    sys.exit(main())
