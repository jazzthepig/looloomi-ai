"""Seth 的 Mac 侧执行器(S-500)—— 把「Jazz 粘贴交接块」这一跳换成一个有关卡的进程。

为什么:Seth 在 Cowork 沙箱里,不能碰 git 索引(硬规则 4:FUSE 删不掉 .git/index.lock)。
所以每一次提交、合并、推送后核对,都要 Jazz 把命令块粘进终端,再把输出粘回来 ——
每个改动要过 Jazz 的手三次(S-500)。这个进程在 Mac 上、用 Jazz 的 git 身份,执行 Seth 放进队列的
**三种**动作,每一种都先过和手动时完全一样的关卡:

    commit   指定路径(绝不 -A)→ preflight → add → commit → check_commit_imports → push → 等部署 → GET 核对
    merge    lane 分支 → 范围检查 → 临时 worktree 里合并 → preflight(合并后的树)→ push → 快进主目录
    fetch    只 git fetch origin(让沙箱能用 --no-optional-locks 读 origin/lane-*)

它**不**做的事:执行队列里的任意命令;推送 Seth 以外的任务;碰 Shadow/、.env、本地专用文件;
在主工作目录 reset/checkout(主目录有未提交的改动,那是 S-334 的伤口)。

队列:<repo>/.seth_bot/queue/*.json(gitignored)。结果:.seth_bot/done/<id>.json + .seth_bot/log.txt。
暂停:touch .seth_bot/PAUSE。安装/卸载:scripts/seth_bot/install.sh。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOT = ROOT / ".seth_bot"
QUEUE, DONE, LOG = BOT / "queue", BOT / "done", BOT / "log.txt"
BASE = os.environ.get("COMETCLOUD_BASE", "https://web-production-0cdf76.up.railway.app")

# 永不经执行器提交的路径(硬规则 + 交接块里一直手写的「永不 stage」清单)。
DENY = ("Shadow/", ".env", ".seth_bot/", "MINIMAX_SYNC", "WEEKLY_REVIEW.md", "docs/reading/",
        "scripts/lesson_enforcement_baseline.txt", "paper_trading/specs/eth_ls_walkforward_v1.json")
DENY_SUFFIX = (".pptx",)
MAX_PATHS = 80
LOCAL_ONLY = ("_data",)
LANE_BRANCH = re.compile(r"^lane-[abc]/T-\d{3}(?:-[A-Za-z0-9._-]+)?$")
VERIFY_PATH = re.compile(r"^/[A-Za-z0-9_\-./?=&%,:]*$")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    BOT.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{now()} {msg}\n")


def run(cmd: list[str], cwd: Path = ROOT, timeout: int = 1800) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)


def git(*args: str, cwd: Path = ROOT) -> tuple[int, str]:
    return run(["git", *args], cwd=cwd, timeout=300)


def notify(title: str, text: str) -> None:
    if sys.platform == "darwin":
        safe = text.replace('"', "'")[:200]
        subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "{title}"'],
                       capture_output=True)


def path_problems(paths: list[str]) -> list[str]:
    """纯函数:commit 的路径清单本身合不合法。测试直接调。"""
    out = []
    if not paths:
        out.append("paths 为空")
    if len(paths) > MAX_PATHS:
        out.append(f"paths 超过 {MAX_PATHS} 个 —— 拆成几个提交")
    for p in paths:
        if p in ("", ".", "-A", "--all") or p.startswith(("/", "-")) or ".." in Path(p).parts:
            out.append(f"非法路径 {p!r}")
        elif any(p == d.rstrip("/") or p.startswith(d) for d in DENY) or p.endswith(DENY_SUFFIX):
            out.append(f"{p} 在永不提交清单里")
    return out


def preflight(cwd: Path) -> tuple[bool, str]:
    env = dict(os.environ)
    env.pop("INTERNAL_TOKEN", None)
    p = subprocess.run(["bash", "scripts/preflight.sh"], cwd=cwd, capture_output=True, text=True,
                       timeout=2400, env=env)
    out = p.stdout + p.stderr
    return p.returncode == 0 and "PREFLIGHT PASSED" in out, out


def verify_after_deploy(paths: list[str], sha: str) -> dict:
    env = dict(os.environ, WANT_SHA=sha)
    p = subprocess.run(["bash", "scripts/wait_for_deploy.sh"], cwd=ROOT, capture_output=True, text=True,
                       timeout=1000, env=env)
    code, out = p.returncode, p.stdout + p.stderr
    res: dict = {"deploy": out.strip().splitlines()[-1] if out.strip() else "", "deploy_ok": code == 0}
    if code != 0:
        return res
    for p in paths[:10]:
        if not VERIFY_PATH.match(p):
            res[p] = "拒绝:只接受本站相对路径的 GET"
            continue
        try:
            with urllib.request.urlopen(BASE + p, timeout=30) as r:
                res[p] = r.read(6000).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 — 结果原样记录,不吞
            res[p] = f"ERROR {type(e).__name__}: {e}"
    return res


def behind_origin() -> int:
    git("fetch", "--quiet", "origin")
    _, n = git("rev-list", "--count", "HEAD..origin/main")
    return int(n.strip() or 0)


def do_commit(job: dict) -> dict:
    paths = list(job.get("paths") or [])
    bad = path_problems(paths)
    if bad:
        return {"ok": False, "stage": "validate", "detail": bad}
    if not (job.get("message") or "").strip():
        return {"ok": False, "stage": "validate", "detail": "message 为空"}
    if behind_origin():
        return {"ok": False, "stage": "sync", "detail": "本地 main 落后 origin/main —— 先在 Mac 上 git pull --ff-only"}
    if git("diff", "--cached", "--quiet")[0] != 0:
        return {"ok": False, "stage": "index", "detail": "索引里已有别人 stage 的东西;执行器不替任何人提交"}
    ok, out = preflight(ROOT)
    if not ok:
        return {"ok": False, "stage": "preflight", "detail": out[-4000:]}
    (ROOT / ".git" / "index.lock").unlink(missing_ok=True)
    code, out = git("add", "--", *paths)
    if code != 0:
        return {"ok": False, "stage": "add", "detail": out}
    _, staged = git("diff", "--cached", "--name-only")
    extra = [f for f in staged.splitlines() if not any(f == p or f.startswith(p.rstrip("/") + "/") for p in paths)]
    if extra or not staged.strip():
        git("reset", "--quiet", "--", *paths)
        return {"ok": False, "stage": "add", "detail": f"stage 结果与清单不符:多出 {extra}" if extra else "没有任何改动"}
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as f:
        f.write(job["message"].rstrip() + f"\n\nCommitted-by: seth_bot (job {job['id']})\n")
    code, out = git("commit", "-q", "-F", f.name)
    os.unlink(f.name)
    if code != 0:
        return {"ok": False, "stage": "commit", "detail": out}
    code, out = run(["python3", "scripts/check_commit_imports.py"], timeout=120)
    if code != 0:
        return {"ok": False, "stage": "commit_imports", "detail": out + "\n(已提交未推送 —— 补上缺的文件后再推)"}
    code, out = git("push", "origin", "main")
    if code != 0:
        return {"ok": False, "stage": "push", "detail": out}
    sha = git("rev-parse", "HEAD")[1].strip()
    return {"ok": True, "stage": "pushed", "sha": sha, "verify": verify_after_deploy(job.get("verify") or [], sha)}


def do_merge(job: dict) -> dict:
    br = job.get("branch") or ""
    if not LANE_BRANCH.match(br):
        return {"ok": False, "stage": "validate", "detail": f"只合并 lane-{{a,b,c}}/T-NNN 分支,收到 {br!r}"}
    if behind_origin():
        return {"ok": False, "stage": "sync", "detail": "本地 main 落后 origin/main"}
    _, ahead = git("rev-list", "--count", "origin/main..HEAD")
    if int(ahead.strip() or 0):
        return {"ok": False, "stage": "sync", "detail": "本地 main 有未推送的提交 —— 先处理"}
    code, out = run(["python3", "scripts/check_pr_scope.py", "--branch", br, "--base", "origin/main",
                     "--head", f"origin/{br}"], timeout=60)
    if code != 0:
        return {"ok": False, "stage": "scope", "detail": out}
    wt = Path(tempfile.mkdtemp(prefix="sethbot-merge-"))
    shutil.rmtree(wt)
    sha = ""
    try:
        code, out = git("worktree", "add", "--detach", str(wt), "origin/main")
        if code != 0:
            return {"ok": False, "stage": "worktree", "detail": out}
        msg = (job.get("message") or f"merge {br}").rstrip() + f"\n\nCommitted-by: seth_bot (job {job['id']})"
        code, out = git("merge", "--no-ff", "-m", msg, f"origin/{br}", cwd=wt)
        if code != 0:
            git("merge", "--abort", cwd=wt)
            return {"ok": False, "stage": "merge", "detail": out[-3000:]}
        for name in LOCAL_ONLY:          # gitignored 本机产物,Mac 侧 preflight 要读(S-500)
            if (ROOT / name).exists() and not (wt / name).exists():
                (wt / name).symlink_to(ROOT / name)
        ok, out = preflight(wt)
        if not ok:
            return {"ok": False, "stage": "preflight(merged tree)", "detail": out[-4000:]}
        code, out = git("push", "origin", "HEAD:main", cwd=wt)
        if code != 0:
            return {"ok": False, "stage": "push", "detail": out}
        sha = git("rev-parse", "HEAD", cwd=wt)[1].strip()
    finally:
        for name in LOCAL_ONLY:
            if (wt / name).is_symlink():
                (wt / name).unlink()
        git("worktree", "remove", "--force", str(wt))
    git("fetch", "--quiet", "origin")
    code, out = git("merge", "--ff-only", "--quiet", "origin/main")
    ff = "主目录已快进" if code == 0 else f"主目录没能快进(本地改动冲突)—— 在 Mac 上手动 git pull --ff-only:{out[-300:]}"
    res = {"ok": True, "stage": "pushed", "sha": sha, "main_worktree": ff}
    res["verify"] = verify_after_deploy(job.get("verify") or [], sha)
    return res


def process(job_file: Path) -> None:
    try:
        job = json.loads(job_file.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        job = {"id": job_file.stem, "op": "?", "_error": str(e)}
    job.setdefault("id", job_file.stem)
    if job.get("by") != "seth":
        res = {"ok": False, "stage": "validate", "detail": "只执行 by=seth 的任务"}
    elif job.get("op") == "commit":
        res = do_commit(job)
    elif job.get("op") == "merge":
        res = do_merge(job)
    elif job.get("op") == "fetch":
        code, out = git("fetch", "--quiet", "--prune", "origin")
        res = {"ok": code == 0, "stage": "fetched", "detail": out}
    else:
        res = {"ok": False, "stage": "validate", "detail": f"未知 op {job.get('op')!r}(只有 commit / merge / fetch)"}
    res.update({"id": job["id"], "op": job.get("op"), "finished_at": now()})
    DONE.mkdir(parents=True, exist_ok=True)
    (DONE / f"{job['id']}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    job_file.unlink(missing_ok=True)
    line = f"{'✓' if res['ok'] else '✗'} {job['id']} {job.get('op')} → {res['stage']} {res.get('sha', '')[:8]}"
    log(line)
    notify("seth_bot", line)


def main() -> int:
    BOT.mkdir(exist_ok=True)
    QUEUE.mkdir(exist_ok=True)
    if (BOT / "PAUSE").exists():
        return 0
    lock = BOT / "lock"
    try:
        lock.mkdir()
    except FileExistsError:
        if dt.datetime.now().timestamp() - lock.stat().st_mtime < 3600:
            return 0
        log("stale lock (>1h) cleared")
        shutil.rmtree(lock, ignore_errors=True)
        lock.mkdir()
    try:
        jobs = sorted(QUEUE.glob("*.json"))
        if not jobs:
            git("fetch", "--quiet", "--prune", "origin")
        for jf in jobs:
            process(jf)
    finally:
        shutil.rmtree(lock, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
