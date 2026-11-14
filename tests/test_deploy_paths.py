"""只在运行时用得到的路径变了才部署(S-859;Jazz 11-14)。清单只有一份(`scripts/deploy_paths.py`),`railway.json`、等部署的脚本、提交机器人都跟它走。"""
import importlib.util
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


dp = _load("deploy_paths", "scripts/deploy_paths.py")


def test_railway_json_says_exactly_what_the_list_says():
    assert json.loads((ROOT / "railway.json").read_text(encoding="utf-8")) == dp.railway_config()
    for pat in dp.PATTERNS:
        assert pat.startswith("/") and (pat.endswith("/**") or "*" not in pat or re.fullmatch(r"/[\w./-]+/\*\.\w+", pat)), f"只允许三种写法:{pat}"


def test_what_restarts_the_service_and_what_does_not():
    yes = ["src/api/main.py", "src/data/market/crowd_clock.py", "dashboard/dist/assets/app-1.js", "dashboard/src/App.jsx",
           "strategies/open_source/BreakoutStrategy.py", "paper_trading/specs/x.json", "scripts/compute_regime_fitness.py",
           "scripts/deploy_paths.py", "docs/research/scenarios/lane-a-T-375.json", "docs/research/scenarios/settlements/s.json",
           "requirements.txt", "Procfile", "nixpacks.toml", "railway.json"]
    no = ["PROJECT_STATE.md", "PROJECT_STATE_LOG.md", "MEMORY.md", "CLAUDE.md", "tasks/T-378.json", "tasks/BOARD.md",
          "tests/test_public_cache.py", "docs/research/s852_watch_v2.py", "docs/research/s852_results.json", "docs/SPINE.md",
          "migrations/2026-11-13_x.sql", "scripts/preflight.sh", "scripts/seth_bot/seth_bot.py", "scripts/lane_bot/lane_bot.py",
          ".claude/skills/deploy-workflow/SKILL.md", "functions/api/[[path]].js", "deploy/executor/write_env.sh", "src_backup/x.py"]
    for p in yes:
        assert dp.touches_runtime([p]), f"该触发部署:{p}"
    for p in no:
        assert not dp.touches_runtime([p]), f"不该触发部署:{p}"
    assert dp.touches_runtime(["PROJECT_STATE.md", "src/api/swr.py"]) and not dp.touches_runtime([])


def test_every_repo_path_the_running_service_reads_is_on_the_list():
    """清单按「运行时读不读」定。情景文件由部署后的入账循环读;路由 import 的 scripts 模块要跟着部署。"""
    from src.data.evaluation import scenario_ledger as sl
    assert dp.touches_runtime([sl.SCENARIO_DIR + "/x.json"]) and dp.touches_runtime([sl.SETTLE_DIR + "/x.json"])
    mods = set()
    for p in (ROOT / "src" / "api").rglob("*.py"):
        mods |= set(re.findall(r"^\s*(?:from|import)\s+scripts\.([A-Za-z_]\w*)", p.read_text(encoding="utf-8", errors="ignore"), flags=re.M))
    assert mods, "前提:路由确实 import 了 scripts 下的模块"
    for m in mods:
        assert dp.touches_runtime([f"scripts/{m}.py"]), f"scripts/{m}.py 被运行时 import,必须在清单里"


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_is_current_means_no_runtime_path_differs(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "code")
    live = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "PROJECT_STATE.md").write_text("state\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "docs")
    assert dp.is_current(live, "HEAD", tmp_path), "只多了一个状态文件:线上那一版就是最新"
    (tmp_path / "src" / "a.py").write_text("x = 2\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "code2")
    assert not dp.is_current(live, "HEAD", tmp_path), "运行时路径变了:线上落后"
    assert not dp.is_current("0" * 40, "HEAD", tmp_path) and not dp.is_current("", "HEAD", tmp_path), "认不出的 sha 不算最新"


def test_the_bot_commits_runtime_changes_last_and_the_wait_script_uses_the_same_rule():
    bot = _load("seth_bot_for_test", "scripts/seth_bot/seth_bot.py")
    jobs = [{"paths": ["src/api/swr.py"]}, {"paths": ["PROJECT_STATE.md"]}, {"paths": ["dashboard/dist"]}, {"paths": ["tasks/T-1.json"]}]
    order = sorted(range(len(jobs)), key=lambda k: bot._touches_runtime(jobs[k]["paths"]))
    assert order == [1, 3, 0, 2], "不碰运行时的先提交,碰的在后;各自内部顺序不变;目录路径(dashboard/dist)算碰"
    src = (ROOT / "scripts/seth_bot/seth_bot.py").read_text(encoding="utf-8")
    assert "live = sorted(live, key=lambda k: _touches_runtime(" in src
    for rel in ("scripts/wait_for_deploy.sh", "scripts/postdeploy_verify.sh"):
        assert "deploy_paths.py --is-current" in (ROOT / rel).read_text(encoding="utf-8"), rel
    assert "_runtime_current(live)" in (ROOT / "scripts/deploy_health_gate.py").read_text(encoding="utf-8")
