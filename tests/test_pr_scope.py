"""S-500:lane 分支的改动范围 = 任务卡允许的范围。CI 和 Mac 侧执行器跑同一个函数。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_pr_scope import check  # noqa: E402

CARD = {"id": "T-123", "owner": "lane-b", "status": "in_review",
        "allowed_paths": ["src/data/evaluation/", "tests/test_rr_*.py", "/Volumes/CometCloudAI/cometcloud-local/"],
        "forbidden_paths": ["src/api/"]}


def test_inside_scope_passes() -> None:
    ok = ["src/data/evaluation/rr_matrix.py", "tests/test_rr_matrix.py", "tasks/T-123.json", "tasks/BOARD.md",
          "scripts/lesson_enforcement_baseline.txt"]
    assert check("lane-b/T-123", ok, CARD) == []
    assert check("lane-b/T-123-fixup", ok, CARD) == []


def test_outside_scope_and_forbidden_are_named() -> None:
    bad = check("lane-b/T-123", ["src/api/main.py", "src/data/allocation/allocator.py", "tasks/T-124.json"], CARD)
    assert any("src/api/main.py" in b and "禁区" in b for b in bad), bad
    assert any("allocator.py" in b and "allowed_paths" in b for b in bad), bad
    assert any("T-124.json" in b for b in bad), bad


def test_global_forbidden_cannot_be_opened_by_a_card() -> None:
    wide = dict(CARD, allowed_paths=[""] and ["Shadow/", ".github/", "docs/"])
    bad = check("lane-b/T-123", ["Shadow/x.py", ".github/workflows/ci.yml", "docs/DECISIONS.md"], wide)
    assert len([b for b in bad if "禁区" in b]) == 3, bad


def test_wrong_owner_status_branch_or_missing_card() -> None:
    assert any("owner" in b for b in check("lane-a/T-123", ["src/data/evaluation/x.py"], CARD))
    assert any("in_review" in b for b in check("lane-b/T-123", ["src/data/evaluation/x.py"], dict(CARD, status="open")))
    assert any("分支名" in b for b in check("feature/x", ["a"], CARD))
    assert any("不存在" in b for b in check("lane-b/T-999", ["a"], None))
    assert any("没有任何改动" in b for b in check("lane-b/T-123", [], CARD))


def test_absolute_mac_paths_never_match_repo_files() -> None:
    card = dict(CARD, allowed_paths=["/Volumes/CometCloudAI/cometcloud-local/"])
    assert any("allowed_paths" in b for b in check("lane-b/T-123", ["src/x.py"], card))


if __name__ == "__main__":
    print("── S-500 lane 改动范围 ──")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("\n✅ passed")


def test_research_cards_that_ask_for_scenarios_must_ship_them():
    """S-705:expect 里点名 scenarios/ 的卡,交付必须带 docs/research/scenarios/<lane>-<tid>.json,≥ 3 条、每条合格、结算日留 7 天。"""
    import json
    card = {"owner": "lane-a", "status": "in_review", "allowed_paths": ["docs/research/", "tasks/T-222.json"],
            "acceptance": {"expect": "报告 …;scenarios/lane-a-T-222.json;in_review"}}
    rpt = ["docs/research/T-222_funding_carry.md", "tasks/T-222.json"]
    assert any("scenarios/lane-a-T-222.json" in p for p in check("lane-a/T-222", rpt, card))
    good = {"author": "lane-a", "entries": [
        {"id": f"T-222-{i}", "scenario": "s", "statement": "x", "variable": "close:BTC", "op": "gt", "lo": 1, "prob": 0.5,
         "horizon_d": "2099-01-01"} for i in range(3)]}
    f = "docs/research/scenarios/lane-a-T-222.json"
    assert check("lane-a/T-222", rpt + [f], card, reader=lambda p: json.dumps(good)) == []
    short = {**good, "entries": good["entries"][:2]}
    assert any("要 ≥ 3" in p for p in check("lane-a/T-222", rpt + [f], card, reader=lambda p: json.dumps(short)))
    soon = {**good, "entries": [{**good["entries"][0], "horizon_d": "2026-11-03"}] + good["entries"][1:]}
    assert any("horizon_d" in p for p in check("lane-a/T-222", rpt + [f], card, reader=lambda p: json.dumps(soon)))
    wrong = {**good, "author": "jazz"}
    assert any("author" in p for p in check("lane-a/T-222", rpt + [f], card, reader=lambda p: json.dumps(wrong)))
    old_card = {**card, "acceptance": {"expect": "报告 docs/research/T-220_x.md;in_review"}}
    assert check("lane-a/T-220", ["docs/research/T-220_x.md", "tasks/T-220.json"], {**old_card}) == [] or \
        all("scenarios" not in p for p in check("lane-a/T-220", ["docs/research/T-220_x.md", "tasks/T-220.json"], old_card))
