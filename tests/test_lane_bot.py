"""S-503:lane_bot 让 A / B / C 无人值守地醒来干活 —— 这里钉住它的缰绳。

它在 Jazz 的 Mac 上、用 lane 平时的配置跑 claude;能推分支(推 main 有 pre-push 钩子,越界有 CI 与 seth_bot)。
这里守的是不该变松的部分:醒的条件、白名单里没有删除与推 main、不拼 shell 字符串、lane 不编辑 SYNC、
lane 改不了自己的缰绳。
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_pr_scope import GLOBAL_FORBIDDEN  # noqa: E402
from scripts.lane_bot.lane_bot import ALLOWED_TOOLS, _LAUNCH, actionable_cards, build_prompt, decide, load_config, parse_stream, review_tasks, run_summary  # noqa: E402

CFG = {"active_hours": [9, 23], "every_min": 120, "max_runs_per_day": 8,
       "lanes": {"lane-b": {"enabled": True, "name": "Minimax-B", "cwd": "/x", "worktree": "/x"}}}
AT = dt.datetime(2026, 10, 7, 6, 0, tzinfo=dt.timezone.utc)


def _d(**kw):
    args = dict(woken=False, cards=["T-058"], local_hour=15, today="2026-10-07", at=AT, busy=False)
    args.update(kw)
    return decide("lane-b", CFG, {}, **args)


def test_wakes_on_cards_or_seth_and_respects_limits() -> None:
    assert _d()[0] and _d(woken=True, cards=[])[0]
    assert not _d(cards=[])[0], "没有卡、也没人唤醒,就不该醒"
    assert not _d(local_hour=3)[0] and not _d(local_hour=3, woken=True)[0], "夜里不醒"
    assert not _d(busy=True, woken=True)[0], "Jazz 正开着这个 lane 的 claude 时不能再起一个"
    recent = {"lane-b": {"last_run": (AT - dt.timedelta(minutes=30)).isoformat(), "day": "2026-10-07", "runs_today": 1}}
    assert not decide("lane-b", CFG, recent, woken=False, cards=["T-058"], local_hour=15, today="2026-10-07",
                      at=AT, busy=False)[0], "间隔未到"
    full = {"lane-b": {"day": "2026-10-07", "runs_today": 8}}
    assert not decide("lane-b", CFG, full, woken=True, cards=["T-058"], local_hour=15, today="2026-10-07",
                      at=AT, busy=False)[0], "每天上限对唤醒也生效"


def test_allowlist_has_no_delete_no_main_push_no_raw_shell() -> None:
    for t in ALLOWED_TOOLS:
        assert not t.startswith(("Bash(rm", "Bash(sudo", "Bash(curl", "Bash(*")), t
        assert t != "Bash" and "--force" not in t and "push -f" not in t, t
        if t.startswith("Bash(git push"):
            assert "origin lane-:*" in t, f"只许推 lane 分支:{t}"


def test_launch_is_env_driven_not_string_built() -> None:
    src = (ROOT / "scripts/lane_bot/lane_bot.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "shell":
            raise AssertionError("lane_bot 不许 shell=True")
    for var in ("$LANE_CWD", "$LANE_CMD", "$LANE_PROMPT", "$LANE_TURNS", "LANE_TOOLS"):
        assert var in _LAUNCH
    assert "{" not in _LAUNCH.replace("${(@s:,:)LANE_TOOLS}", ""), "提示词等可变内容不能拼进命令字符串"


def test_prompt_keeps_lanes_out_of_sync_and_their_own_leash() -> None:
    p = build_prompt("lane-b", {"name": "Minimax-B", "worktree": "/w"}, "测试")
    for must in ("编辑 `MINIMAX_SYNC.md`", "推 main", "scripts/lane_bot/", ".seth_bot/", "删除文件", "STRONG OUTPERFORM"):
        assert must in p, must
    assert "scripts/lane_bot/" in GLOBAL_FORBIDDEN, "lane 改不了自己的缰绳"


def test_shipped_config_is_sane() -> None:
    cfg = load_config()
    assert set(cfg["lanes"]) == {"lane-a", "lane-b", "lane-c"}
    # 每天 48 轮 = Jazz 10-15「non-stop」(15 分钟一醒、全天);单轮步数与超时的上限不动
    assert cfg["max_turns"] <= 200 and cfg["timeout_min"] <= 60 and cfg["max_runs_per_day"] <= 48


def test_max_turns_posts_a_sentence_not_raw_json() -> None:
    """10-07 B 的第一轮到 60 步上限,SYNC 里被贴进了一段原始 JSON 尾巴。"""
    import json as _j
    ev = [{"type": "assistant", "message": {"content": [{"type": "text", "text": "先读 T-058 卡"}]}},
          {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "git show x:y"}}]}},
          {"type": "result", "subtype": "error_max_turns", "num_turns": 61}]
    j, text = parse_stream("\n".join(_j.dumps(e) for e in ev), 60)
    assert j["subtype"] == "error_max_turns" and "60 步上限" in text and "git show x:y" in text and "{" not in text
    ok = [{"type": "result", "subtype": "success", "result": "T-058 已推 lane-b/T-058"}]
    assert parse_stream(_j.dumps(ok[0]), 60)[1] == "T-058 已推 lane-b/T-058"


def test_status_shows_model_writes_and_pushes() -> None:
    """Jazz 10-07「我怎么知道它们有没有做事、用的是谁的算力」—— 从完整记录里取出模型、写过的文件、推过的分支。"""
    import json as _j
    ev = [{"type": "system", "subtype": "init", "model": "MiniMax-M3", "apiKeySource": "none"},
          {"type": "assistant", "message": {"content": [
              {"type": "tool_use", "name": "Write", "input": {"file_path": "/x/report.md"}},
              {"type": "tool_use", "name": "Bash", "input": {"command": "git push -u origin lane-b/T-058"}}]}},
          {"type": "result", "modelUsage": {"MiniMax-M3": {"inputTokens": 10, "cacheReadInputTokens": 5, "outputTokens": 3}}}]
    import tempfile
    with tempfile.TemporaryDirectory() as d:   # 不用 pytest 的 tmp_path:preflight 以 python3 -m 自跑,不注入夹具
        f = Path(d) / "r.jsonl"
        f.write_text("\n".join(_j.dumps(e) for e in ev))
        sm = run_summary(f)
    assert sm["model"] == "MiniMax-M3" and sm["writes"] == ["/x/report.md"] and sm["pushes"] and sm["tokens_in"] == 15


def test_cross_review_rotates_once_a_day() -> None:
    """Jazz 10-07:lane 们要定时互相验证。A 查 B、B 查 C、C 查 A;到点才派,每天一次。"""
    cfg = {"review_hour": 21, "lanes": {"lane-a": {}, "lane-b": {}, "lane-c": {}}}
    assert review_tasks(cfg, {}, "2026-10-07", 20) == {}
    t = review_tasks(cfg, {}, "2026-10-07", 21)
    assert set(t) == {"lane-a", "lane-b", "lane-c"} and "lane-b-20261007" in t["lane-a"] and "lane-a-20261007" in t["lane-c"]
    assert "不改对方任何文件" in t["lane-b"]
    done = {"lane-a": {"review_day": "2026-10-07"}}
    assert "lane-a" not in review_tasks(cfg, done, "2026-10-07", 22)


if __name__ == "__main__":
    print("── S-503 lane_bot ──")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("\n✅ passed")


def test_guard_blocks_main_dir_git_writes_and_file_writes() -> None:
    """10-08:lane-c 在主目录 switch → stash「not mine」→ switch main,收走了 Seth 17 个未提交的文件。"""
    from scripts.lane_bot.guard_main_dir import verdict
    M, L = "/Users/sbb/Projects/looloomi-ai", "/Users/sbb/Projects/looloomi-ai-lane-c"
    blocked = [
        f"git -C {M} switch -c lane-c/T-036 origin/main",
        f'git -C {M} stash push -m "pre-existing dirty state (not mine)" --keep-index',
        f"git -C {M} update-index --chmod=+x scripts/x.sh",
        f"cd {M} && git add -A && git commit -m x",
        "cd ~/Projects/looloomi-ai && git checkout main",
        f"echo hi > {M}/scripts/stray.sh",
    ]
    for cmd in blocked:
        assert verdict("Bash", {"command": cmd}), cmd
    allowed = [
        f"git -C {L} switch -c lane-c/T-036 origin/main",
        f"cd {L} && git add tasks/T-036.json && git commit -m x",
        f"git -C {M} log --oneline -5", f"git -C {M} show origin/main:tasks/T-036.json", f"git -C {M} status",
        f"cat {M}/MINIMAX_SYNC.md", f"echo '## §C' >> {M}/MINIMAX_SYNC.md",
        "git -C /Users/sbb/Projects/looloomi-ai-private log -1",
    ]
    for cmd in allowed:
        assert verdict("Bash", {"command": cmd}) is None, cmd
    assert verdict("Write", {"file_path": f"{M}/scripts/verify_rotation_alive.sh"})
    assert verdict("Write", {"file_path": f"{M}/MINIMAX_SYNC.md"}) is None
    assert verdict("Edit", {"file_path": f"{L}/scripts/verify_rotation_alive.sh"}) is None


def test_every_launch_installs_the_guard() -> None:
    import json as _json
    from scripts.lane_bot.lane_bot import guard_settings
    assert '--settings "$LANE_SETTINGS"' in _LAUNCH
    assert '--add-dir "$LANE_WORKTREE"' in _LAUNCH and '--add-dir "$LANE_MAIN"' in _LAUNCH, \
        "10-08:装了 --settings 之后 lane-c 只剩 cwd 可读,连自己的 worktree 都打不开"
    assert '--add-dir "$LANE_DATA"' in _LAUNCH, "10-15:lane-b 写不进 Mac 数据根,T-101 的交付只好留在 worktree 里"
    src = (ROOT / "scripts/lane_bot/lane_bot.py").read_text(encoding="utf-8")
    assert "LANE_DATA=data_root(wt)" in src and "data_root(wt)), fb_settings)" in src
    cfg = _json.loads(guard_settings("lane-x", ("/tmp/wt", "/tmp/main")).read_text(encoding="utf-8"))
    assert cfg["permissions"]["additionalDirectories"] == ["/tmp/wt", "/tmp/main"]
    hook = cfg["hooks"]["PreToolUse"][0]
    assert "Bash" in hook["matcher"] and "Write" in hook["matcher"]
    assert "guard_main_dir.py" in hook["hooks"][0]["command"]


def test_cards_waiting_for_review_do_not_wake_the_lane() -> None:
    """S-558:分支上已 in_review 的卡(main 上还是 claimed)不算「有活」—— 否则 lane 一轮轮重验已交付的卡。"""
    import json as _json
    mine = [_json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "tasks").glob("T-*.json"))]
    lane = next((c["owner"] for c in mine if c.get("status") in ("open", "claimed") and str(c.get("owner", "")).startswith("lane-")), None)
    if lane is None:
        return
    live = actionable_cards(lane, branch_status=lambda _l, _c: None)
    assert live, "没有分支状态时,open / claimed 的卡照常算活"
    assert actionable_cards(lane, branch_status=lambda _l, _c: "in_review") == []
    assert actionable_cards(lane, branch_status=lambda _l, _c: "claimed") == live
    p = build_prompt(lane, {"name": "x", "worktree": "/w"}, "测试")
    assert "等 Seth 审的卡不是你的活" in p


def test_guard_uses_session_cwd_and_head_mode_for_every_session() -> None:
    """S-559(10-13 两次):`cd 主目录` 之后不带路径的 `git switch` 漏过;Jazz 手动开的会话没装钩子。"""
    import json as _json
    from scripts.lane_bot.guard_main_dir import head_verdict, verdict
    M, L = "/Users/sbb/Projects/looloomi-ai", "/Users/sbb/Projects/looloomi-ai-lane-a"
    assert verdict("Bash", {"command": "git fetch origin && git switch -c lane-a/T-089 origin/main"}, cwd=M)
    assert verdict("Bash", {"command": "git switch -c lane-a/T-089 origin/main"}, cwd=L) is None
    assert verdict("Bash", {"command": f"cd {L} && git switch -c x"}, cwd=M) is None
    for cmd in ("git stash push -u -m x", "git checkout lane-b/T-059", "git checkout -b foo", "git reset --hard HEAD",
                "git branch -m a b", f"git -C {M} switch lane-b/T-059"):
        assert head_verdict(cmd, M), cmd
    for cmd in ("git checkout -- tasks/T-089.json", "git switch main", "git checkout main", "git add a && git commit -m x",
                "git status", f"git -C {L} switch x"):
        assert head_verdict(cmd, M) is None, cmd
    assert head_verdict("git checkout lane-b/T-059", L) is None
    hooks = _json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    cmd = next(h["hooks"][0]["command"] for h in hooks if "guard_main_dir.py" in h["hooks"][0]["command"])
    assert "--head" in cmd and "exit 0" in cmd, "所有会话都装;文件不在时放行(旧分支上不能把所有 Bash 都锁死)"


def test_a_long_lane_does_not_hold_the_others() -> None:
    """10-15:三个 lane 在线程里跑、main 最后 join —— B 跑长任务时 launchd 不再起新一次检查,A / C 的 wake 干等一小时。
    现在:定时检查给每个 lane 起一个新会话里的独立进程就返回;任务原文经文件传、不进 argv;锁跟着进程走。"""
    import os as _os
    import tempfile
    from unittest import mock
    import scripts.lane_bot.lane_bot as lb
    src = (ROOT / "scripts/lane_bot/lane_bot.py").read_text(encoding="utf-8")
    assert ".join()" not in src and "threading" not in src
    with tempfile.TemporaryDirectory() as td, mock.patch.object(lb, "BOT", Path(td)), \
            mock.patch.object(lb.subprocess, "Popen") as P:
        P.return_value.pid = 4242
        assert lb.spawn("lane-a", "Seth 唤醒", "秘密任务原文") == 4242
        argv, kw = P.call_args[0][0], P.call_args[1]
        assert kw["start_new_session"] is True and "--run" in argv and "lane-a" in argv
        assert not any("秘密任务原文" in a for a in argv)
        assert (Path(td) / "task-lane-a.txt").read_text(encoding="utf-8") == "秘密任务原文"
        lock = Path(td) / "lane-a.lock"
        assert lock.read_text() == "4242"
        now_ts = lock.stat().st_mtime + 1
        lock.write_text(str(_os.getpid()))
        assert lb.lock_held(lock, now_ts, 4200), "进程在、没过期 ⇒ 锁算数"
        assert not lb.lock_held(lock, now_ts + 5000, 4200), "过期 ⇒ 不算"
        dead = 2 ** 22 + 12345
        lock.write_text(str(dead))
        assert not lb.lock_held(lock, now_ts, 4200), "进程不在了 ⇒ 锁不算,下一次检查就能起这个 lane"
        lock.write_text("")
        assert lb.lock_held(lock, now_ts, 4200), "写不出 pid 的老锁只看时间"
        assert not lb.lock_held(Path(td) / "none.lock", now_ts, 4200)


def test_quota_exhaustion_pauses_every_lane() -> None:
    """10-15:MiniMax Token Plan 429 之后,三个 lane 每 15 分钟一醒、1 步失败、每次往 SYNC 追加同一句报错。"""
    import tempfile
    from unittest import mock
    import scripts.lane_bot.lane_bot as lb
    msg = "API Error: Request rejected (429) · Token Plan usage limit reached: Upgrade your Token Plan"
    assert lb.quota_hit(msg) and not lb.quota_hit("到 160 步上限,没有收尾")
    with tempfile.TemporaryDirectory() as td, mock.patch.object(lb, "QUOTA", Path(td) / "quota_until"), \
            mock.patch.object(lb, "BOT", Path(td)), mock.patch.object(lb, "log", lambda *_: None), \
            mock.patch.object(lb, "USAGE", Path(td) / "usage.jsonl"), mock.patch.object(lb, "OBSERVED_CAP", Path(td) / "obs"), \
            mock.patch.object(lb, "FALLBACK_ENV_FILE", Path(td) / "none.env"), \
            mock.patch.object(lb, "run_lane", lambda *a, **k: {"exit": 0, "timed_out": False, "seconds": 1, "text": msg}):
        assert not lb.quota_paused(lb.now().timestamp())
        with mock.patch.object(lb, "WAKE", Path(td) / "wake"):
            (Path(td) / "wake").mkdir()
            lb.run_one({}, "lane-b", "Seth 唤醒", "T-105 接着做")
            assert (Path(td) / "wake" / "lane-b").read_text(encoding="utf-8") == "T-105 接着做", "没做成的派活要放回去"
        assert lb.quota_paused(lb.now().timestamp())
        assert not lb.quota_paused(lb.now().timestamp() + lb.QUOTA_BACKOFF_MIN * 60 + 1), "本账里没有调用 ⇒ 固定退避"
        assert not (Path(td) / "obs").exists(), "窗口内不到 100 次就撞 ⇒ 不当成上限观测"
        # S-706:本账里有调用 ⇒ 停到最早一次调用滚出窗口;窗口内已用次数记成观测上限
        at = lb.now()
        (Path(td) / "usage.jsonl").write_text("".join(json.dumps({"lane": "lane-a", "start": (at - dt.timedelta(hours=h)).isoformat(),
                                                                   "end": (at - dt.timedelta(hours=h) + dt.timedelta(minutes=20)).isoformat(),
                                                                   "calls": 400, "backend": "primary"}) + "\n" for h in (4, 3, 2)), encoding="utf-8")
        lb.run_one({}, "lane-b", "定时", "")
        until = float((Path(td) / "quota_until").read_text())
        assert abs(until - (at - dt.timedelta(hours=4) + dt.timedelta(hours=5, minutes=5)).timestamp()) < 120
        assert (Path(td) / "obs").read_text() == "1200"
    src = (ROOT / "scripts/lane_bot/lane_bot.py").read_text(encoding="utf-8")
    assert "if quota_hit(text) or context_overflow(text):" in src, "额度报错 / 上下文溢出不进 SYNC"


# ── 2026-10-20:service_role 泄露之后,lane 只拿 publishable key ─────────────────────────────────────

def test_launch_scrubs_write_keys_then_exports_only_the_lane_key():
    head = _LAUNCH.split('cd "$LANE_CWD"')[0]
    for var in ("INTERNAL_TOKEN", "SUPABASE_SERVICE_KEY", "SUPABASE_KEY", "SUPABASE_SECRET_KEY", "HL_API_WALLET_PRIVATE_KEY"):
        assert var in head.split(";")[0], f"{var} 必须在 rc 读完之后先 unset"
    assert 'SUPABASE_KEY="$LANE_SUPABASE_KEY"' in head


def test_lane_db_env_only_hands_out_a_publishable_key(tmp_path, monkeypatch):
    from scripts.lane_bot import lane_bot as lb
    monkeypatch.setattr(lb, "log", lambda msg: None)        # 不往真的 .lane_bot/log.txt 里写测试噪音
    lane_db_env = lb.lane_db_env
    f = tmp_path / "lane.env"
    f.write_text("SUPABASE_URL=https://x.supabase.co\nSUPABASE_KEY=sb_publishable_abc123\n", encoding="utf-8")
    assert lane_db_env(f) == {"LANE_SUPABASE_URL": "https://x.supabase.co", "LANE_SUPABASE_KEY": "sb_publishable_abc123"}
    for bad in ("sb_" + "secret_abc123", "eyJhbGciOiJIUzI1NiJ9.e30.sig", ""):
        f.write_text(f"SUPABASE_URL=https://x.supabase.co\nSUPABASE_KEY={bad}\n", encoding="utf-8")
        assert lane_db_env(f) == {}, bad
    assert lane_db_env(tmp_path / "missing.env") == {}


def test_guard_blocks_reading_env_files_and_printing_keys():
    from scripts.lane_bot.guard_main_dir import verdict
    for cmd in ("cat /Volumes/CometCloudAI/cometcloud-local/.env", "source ./.env; python3 x.py", "printenv | grep SUPA",
                "echo $SUPABASE_KEY", "grep KEY .env.local"):
        assert verdict("Bash", {"command": cmd}), cmd
    assert verdict("Read", {"file_path": "/Volumes/CometCloudAI/cometcloud-local/.env"})
    assert verdict("Read", {"file_path": "/Users/sbb/.cometcloud/lane.env"})
    for cmd in ('curl -s -H "apikey: $SUPABASE_KEY" "$SUPABASE_URL/rest/v1/ohlcv_daily?limit=1"',
                "python3 docs/research/t137.py", "env PYTHONPATH=. python3 x.py", "cat docs/research/T-137.md"):
        assert verdict("Bash", {"command": cmd}) is None, cmd


def test_guard_hook_also_sees_read_tools():
    import json
    from scripts.lane_bot.lane_bot import guard_settings
    hook = json.loads(guard_settings().read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]
    assert "Read" in hook["matcher"] and "Grep" in hook["matcher"]


def test_weekly_script_runs_once_per_week_after_its_slot() -> None:
    """T-144:每周一 01:30 UTC 冻结叙事臂名单 —— 时刻没到不跑、跑过不重跑、错过了下一次检查补跑。"""
    from scripts.lane_bot.lane_bot import weekly_due
    job = {"weekday": 0, "utc": "01:30"}
    mon = dt.datetime(2026, 10, 26, 1, 0, tzinfo=dt.timezone.utc)
    assert not weekly_due(job, mon, (mon - dt.timedelta(days=6)).isoformat()), "周一 01:30 之前不跑"
    after = mon + dt.timedelta(minutes=45)
    assert weekly_due(job, after, (mon - dt.timedelta(days=6)).isoformat())
    assert not weekly_due(job, after + dt.timedelta(hours=3), after.isoformat()), "本周跑过不重跑"
    assert weekly_due(job, after + dt.timedelta(days=2), None), "从没跑过 ⇒ 补跑"


def test_weekly_script_env_carries_only_the_publishable_key(monkeypatch) -> None:
    from scripts.lane_bot.lane_bot import load_config, weekly_env
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "_".join(["sb", "secret", "SENTINEL"]))   # 拼出来:字面量会被 secret_scan 拦
    monkeypatch.setenv("INTERNAL_TOKEN", "SENTINEL")
    env = weekly_env({"LANE_SUPABASE_URL": "https://x.supabase.co", "LANE_SUPABASE_KEY": "sb_publishable_abc"})
    assert env["SUPABASE_KEY"].startswith("sb_publishable_") and "SENTINEL" not in "".join(env.values())
    assert not any(k in env for k in ("SUPABASE_SERVICE_KEY", "INTERNAL_TOKEN", "EXECUTOR_TOKEN"))
    jobs = load_config().get("weekly_scripts", [])
    assert any(j["script"] == "docs/research/t144_narrative_ab.py" and j["weekday"] == 0 for j in jobs)


def test_a_context_overflow_round_does_not_go_into_sync():
    from scripts.lane_bot import lane_bot as lb
    assert lb.context_overflow("Prompt is too long") and lb.context_overflow("  Prompt is too long\n")
    assert not lb.context_overflow("T-208 交付完成。…Prompt is too long 只是正文里提到")
    assert not lb.context_overflow("")


def test_landing_guard_forces_a_landing_before_context_overflow(tmp_path):
    """S-705:11-02 三个 lane 的定时轮次全部「Prompt is too long」、零交付。钩子按转录量上下文:
    软阈值只放行降落工具(改卡 / task_board / preflight / git add-commit-push / mv 产物),硬阈值全拦;
    Read 不带 limit 的长文件拦;python3 不截断输出的命令补 tail。"""
    import json
    from scripts.lane_bot.guard_main_dir import (HARD_CHARS, SOFT_CHARS, landing_verdict, read_too_long,
                                                 transcript_chars, truncated_command)
    assert SOFT_CHARS < HARD_CHARS <= 115_000          # 85 轮实测(估算 token):lane-a / b 最早在 115k 溢出
    assert landing_verdict("Read", {"file_path": "x"}, SOFT_CHARS - 1) is None
    soft = SOFT_CHARS
    assert "降落" in landing_verdict("Read", {"file_path": "x"}, soft)
    assert "降落" in landing_verdict("Bash", {"command": "python3 docs/research/probe9.py"}, soft)
    wt = "/Users/sbb/Projects/looloomi-ai-lane-a"
    assert "降落" in landing_verdict("Write", {"file_path": f"{wt}/docs/research/probe9.py", "content": "x" * 9000}, soft), "大文件不写"
    assert landing_verdict("Write", {"file_path": f"{wt}/docs/research/T-218_report.md", "content": "x" * 5000}, soft) is None, "软阈值还能写短报告"
    for cmd in ("git add tasks/T-218.json docs/research/x.md", "cd /Users/sbb/Projects/looloomi-ai-lane-a && git commit -m x",
                "git push -u origin lane-a/T-218", "python3 scripts/task_board.py", "bash scripts/preflight.sh | tail -20",
                "mv /tmp/x.md /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/x.md",
                f"git -C {wt} add docs/research ; git -C {wt} commit -m x", f"git -C {wt} status --short", "tail -n 20 /Volumes/x/run.log"):
        assert landing_verdict("Bash", {"command": cmd}, soft) is None, cmd
        assert landing_verdict("Bash", {"command": cmd}, HARD_CHARS + 50_000) is None, "降落永远放行(11-02 lane-c 第一轮被硬阈值拦住没推出去)"
    assert landing_verdict("Edit", {"file_path": f"{wt}/tasks/T-218.json", "new_string": "x"}, HARD_CHARS) is None
    assert landing_verdict("Write", {"file_path": f"{wt}/docs/research/scenarios/lane-a-T-218.json", "content": "{}"}, HARD_CHARS) is None
    assert "上限附近" in landing_verdict("Write", {"file_path": f"{wt}/docs/research/T-218_report.md", "content": "x" * 5000}, HARD_CHARS)
    assert "上限附近" in landing_verdict("Bash", {"command": "python3 docs/research/probe9.py"}, HARD_CHARS)
    # 转录量法:只数 message.content
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "user", "message": {"content": "x" * 1000}}) + "\n"
                 + json.dumps({"type": "progress", "data": "z" * 5000}) + "\n"
                 + json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "y" * 500}]}}) + "\n",
                 encoding="utf-8")
    from scripts.lane_bot.guard_main_dir import est_tokens
    assert est_tokens("x" * 1000) < 100 and 1000 <= est_tokens("中" * 1000) <= 1200, "中文按字算,英文按词算"
    assert est_tokens(json.dumps({"close": 81234.5, "d": "2026-11-02"})) > 15, "数字与 JSON 标点按半个 token"
    assert 0 < transcript_chars(str(t)) <= 1200 and transcript_chars(str(tmp_path / "nope")) == 0
    # 每个 lane 的阈值由 lane_bot 按 lanes.json 的 ctx_tokens 给钩子(a / b 115k,c 150k)
    cfg_ = load_config()
    assert cfg_["lanes"]["lane-c"]["ctx_tokens"] > cfg_["lanes"]["lane-a"]["ctx_tokens"] == 115_000
    assert "LANE_CTX_SOFT=str(int(ctx * 0.80))" in (ROOT / "scripts/lane_bot/lane_bot.py").read_text(encoding="utf-8")
    # 长文件整读拦;带 limit 放
    big = tmp_path / "big.py"
    big.write_text("x\n" * 500, encoding="utf-8")
    assert "offset" in read_too_long({"file_path": str(big)})
    assert read_too_long({"file_path": str(big), "limit": 120}) is None
    assert read_too_long({"file_path": str(tmp_path / "missing.py")}) is None
    # 输出截断
    assert truncated_command("python3 docs/research/t218_probe.py").endswith("2>&1 | tail -n 80")
    assert truncated_command("python3 -m pytest tests/test_x.py -q") .endswith("| tail -n 80")
    for cmd in ("python3 x.py | tail -5", "python3 x.py > out.txt", "python3 - <<'EOF'\nprint(1)\nEOF", "ls docs", "git status"):
        assert truncated_command(cmd) is None, cmd


def test_budget_spreads_the_5h_window_and_keeps_a_reserve_for_seth(tmp_path):
    """S-706:按滚动窗口记调用;剩得少就缩步数;储备只给 Seth 的唤醒;一小时内不超均速 × burst;
    429 之后按本账算最早一次调用滚出窗口的时刻再起;备用后端不按主后端的额度限。"""
    from scripts.lane_bot.lane_bot import budget_turns, calls_since, fallback_env, quota_resume_at
    cfg = {"max_turns": 120, "budget": {"window_h": 5, "calls_per_window": 1000, "reserve_frac": 0.2, "burst": 1.5, "min_turns": 30}}
    at = dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.timezone.utc)
    mk = lambda h_ago, calls, backend="primary": {"lane": "lane-a", "start": (at - dt.timedelta(hours=h_ago, minutes=20)).isoformat(),  # noqa: E731
                                                 "end": (at - dt.timedelta(hours=h_ago)).isoformat(), "calls": calls, "backend": backend}
    assert budget_turns(cfg, [], at, woken=False) == (120, "窗口已用 0/1000,本轮上限 120 步")
    usage = [mk(4, 300), mk(3, 300), mk(2, 150)]                         # 750 用了,储备 200 ⇒ 剩 50
    assert budget_turns(cfg, usage, at, woken=False)[0] == 50
    assert budget_turns(cfg, usage + [mk(1.5, 40)], at, woken=False)[0] == 0, "不够 min_turns 就不醒"
    assert budget_turns(cfg, usage + [mk(1.5, 40)], at, woken=True)[0] == 120, "Seth 的唤醒可以动储备"
    assert budget_turns(cfg, [mk(0.5, 310)], at, woken=False)[0] == 0, "一小时 310 ≥ 均速 200 × 1.5 ⇒ 摊开"
    assert budget_turns(cfg, [mk(0.5, 310)], at, woken=True)[0] == 120
    assert budget_turns(cfg, [mk(6, 999)], at, woken=False)[0] == 120, "6 小时前的不算"
    assert budget_turns(cfg, [mk(1, 999, "fallback")], at, woken=False, backend="fallback")[0] == 120
    assert calls_since([mk(1, 10), mk(1, 5, "fallback")], at, 5) == 10
    assert quota_resume_at([mk(4, 300), mk(1, 300)], at, 5, 60) == at - dt.timedelta(hours=4, minutes=20) + dt.timedelta(hours=5, minutes=5)
    assert quota_resume_at([], at, 5, 60) == at + dt.timedelta(minutes=60)
    f = tmp_path / "fb.env"
    assert fallback_env(f) == {}
    f.write_text("ANTHROPIC_BASE_URL=https://x\nANTHROPIC_AUTH_TOKEN=t\nANTHROPIC_MODEL=m\n", encoding="utf-8")
    assert fallback_env(f) == {"LANE_FB_URL": "https://x", "LANE_FB_TOKEN": "t", "LANE_FB_MODEL": "m"}
    from scripts.lane_bot.lane_bot import effective_cap
    assert effective_cap(4500, 0) == 4500 and effective_cap(4500, 1310) == 1179 and effective_cap(1000, 5000) == 1000
    assert budget_turns({**cfg, "budget": {**cfg["budget"], "observed": 500}}, [mk(1, 400)], at, woken=False)[0] == 0, "观测到的上限压过配置"
    cfg2 = load_config()
    assert cfg2["budget"]["calls_per_window"] > 0 and cfg2["budget"]["reserve_frac"] >= 0.1


def test_failed_rounds_are_not_success_and_the_last_words_are_kept():
    """§Seth-1102f:exit=1「Prompt is too long」不得记成 success;lane 最后一段话要落盘;降落时可以 Read 自己的卡(Edit 要先 Read)。"""
    import json
    from scripts.lane_bot.guard_main_dir import HARD_CHARS, landing_verdict
    from scripts.lane_bot.lane_bot import last_assistant_text
    out = "\n".join([json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "先看卡"}]}}),
                     json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]}}),
                     json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "结果在 t226/ 里,CSV 还没跑完"}]}}),
                     json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "Prompt is too long"})])
    assert last_assistant_text(out) == "结果在 t226/ 里,CSV 还没跑完"
    src = (ROOT / "scripts/lane_bot/lane_bot.py").read_text(encoding="utf-8")
    assert 'res["ok"] = (p.returncode == 0 and not timed_out and not quota_hit(text) and not context_overflow(text)' in src
    wt = "/Users/sbb/Projects/looloomi-ai-lane-c"
    assert landing_verdict("Read", {"file_path": f"{wt}/tasks/T-226.json"}, HARD_CHARS) is None
    assert landing_verdict("Read", {"file_path": f"{wt}/docs/research/T-226_wallet_sets.md"}, HARD_CHARS) is not None


def test_read_guard_blocks_a_huge_single_line_file_even_with_limit(tmp_path):
    """11-07:5.2 MB 的单行 JSON 过了行数门槛(1 行)整份进了上下文。按字节 + 平均行长再拦。"""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lane_bot"))
    import guard_main_dir as g
    blob = tmp_path / "big.json"
    blob.write_text("[" + ",".join('{"i": %d, "x": "%s"}' % (i, "y" * 40) for i in range(8000)) + "]", encoding="utf-8")
    assert g.read_too_long({"file_path": str(blob)}) is not None
    assert g.read_too_long({"file_path": str(blob), "limit": 50}) is not None, "limit 按行截,单行文件截不住"
    tall = tmp_path / "tall.txt"
    tall.write_text("\n".join("row %d" % i for i in range(1000)), encoding="utf-8")
    assert g.read_too_long({"file_path": str(tall)}) is not None
    assert g.read_too_long({"file_path": str(tall), "limit": 100}) is None


def test_cat_of_a_big_file_is_blocked(tmp_path):
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lane_bot"))
    import guard_main_dir as g
    big = tmp_path / "r.json"
    big.write_text("x" * 300_000, encoding="utf-8")
    assert g.cat_too_big(f"cat {big}") is not None
    assert g.cat_too_big(f"cat {big} | head -5") is None, "接了管道的放行"
    small = tmp_path / "s.txt"
    small.write_text("ok", encoding="utf-8")
    assert g.cat_too_big(f"cat {small}") is None
