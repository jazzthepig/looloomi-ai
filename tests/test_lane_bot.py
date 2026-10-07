"""S-503:lane_bot 让 A / B / C 无人值守地醒来干活 —— 这里钉住它的缰绳。

它在 Jazz 的 Mac 上、用 lane 平时的配置跑 claude;能推分支(推 main 有 pre-push 钩子,越界有 CI 与 seth_bot)。
这里守的是不该变松的部分:醒的条件、白名单里没有删除与推 main、不拼 shell 字符串、lane 不编辑 SYNC、
lane 改不了自己的缰绳。
"""
from __future__ import annotations

import ast
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_pr_scope import GLOBAL_FORBIDDEN  # noqa: E402
from scripts.lane_bot.lane_bot import ALLOWED_TOOLS, _LAUNCH, build_prompt, decide, load_config, parse_stream, run_summary  # noqa: E402

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
    assert cfg["max_turns"] <= 100 and cfg["timeout_min"] <= 60 and cfg["max_runs_per_day"] <= 12


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


if __name__ == "__main__":
    print("── S-503 lane_bot ──")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("\n✅ passed")
