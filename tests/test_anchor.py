"""T-073 / S-519:前向记录锚定 —— 规范化、摘要稳定、.ots 文件结构、等账本记齐。"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.accounting.anchor import (OTS_MAGIC, canonical, clean_rows, digest_of,  # noqa: E402
                                        ots_file, waiting_for)


def test_digest_ignores_key_order_and_recompute_time_but_not_numbers() -> None:
    a = {"d": "2026-10-08", "sources": {"t": clean_rows([{"arm": "x", "nav": 1.01, "computed_at": "now"}], "arm")}}
    b = {"sources": {"t": clean_rows([{"computed_at": "later", "nav": 1.01, "arm": "x"}], "arm")}, "d": "2026-10-08"}
    assert digest_of(a) == digest_of(b), "键顺序与重算时间不改变摘要"
    c = {"d": "2026-10-08", "sources": {"t": [{"arm": "x", "nav": 1.0100001}]}}
    assert digest_of(a) != digest_of(c), "数字改一点点,摘要就变 —— 这正是要暴露的"
    assert digest_of(a) == hashlib.sha256(canonical(a)).hexdigest()


def test_rows_are_sorted_so_read_order_does_not_matter() -> None:
    r1 = clean_rows([{"arm": "b", "v": 2}, {"arm": "a", "v": 1}], "arm")
    r2 = clean_rows([{"arm": "a", "v": 1}, {"arm": "b", "v": 2}], "arm")
    assert r1 == r2 and r1[0]["arm"] == "a"


def test_ots_file_layout() -> None:
    dg = "ab" * 32
    f = ots_file(dg, b"\xf0\x10resp")
    assert f.startswith(OTS_MAGIC) and f[len(OTS_MAGIC):len(OTS_MAGIC) + 2] == b"\x01\x08"
    assert f[len(OTS_MAGIC) + 2:len(OTS_MAGIC) + 34] == bytes.fromhex(dg) and f.endswith(b"\xf0\x10resp")


def test_waits_for_books_that_marked_yesterday() -> None:
    prev = {"sources": {"core_cap_daily": [{"d": 1}], "portfolio_layer_daily": [{"d": 1}], "x": []}}
    cur = {"sources": {"core_cap_daily": [{"d": 2}], "portfolio_layer_daily": [], "x": []}}
    assert waiting_for(prev, cur) == ["portfolio_layer_daily"]


def test_v2_anchors_forward_rows_only_and_every_arm() -> None:
    """S-560:v1 锚进了回放行(core_variants / feature_arms 没按起点过滤),又只锚 mult_v1 / pl_v2。"""
    from src.data.accounting.anchor import CODE_REF, SOURCES, forward_rows
    assert CODE_REF == "T-073 anchor v2"
    flt = {t: f for t, f, _k in SOURCES}
    assert flt["multiplier_daily"] == {} and flt["portfolio_layer_daily"] == {}, "新臂(mult_v2 / pl_v3)也要锚"
    rows = [{"d": "2026-10-07", "arm": "a", "inception": "2026-10-08"},
            {"d": "2026-10-08", "arm": "a", "inception": "2026-10-08"}, {"d": "2026-10-07", "book": "x"}]
    assert [r["d"] for r in forward_rows(rows)] == ["2026-10-08", "2026-10-07"]


def test_verify_compares_rows_not_a_rebuilt_digest() -> None:
    """改过的行与字段要点名;回放行不计;v1 没收的臂不算「锚后补进」;晚到的行单独报。"""
    from src.data.accounting.anchor import compare
    anchored = {"schema": "T-073 anchor v1", "sources": {
        "allocation_daily": [{"d": "2026-10-07", "book": "core_cap", "weight": 1, "why": ["old"]}],
        "core_variants_daily": [{"d": "2026-10-07", "arm": "btc", "nav": 5.0, "inception": "2026-10-08"}],
        "multiplier_daily": [{"d": "2026-10-07", "arm": "mult_v1", "nav": 1.0, "inception": "2026-10-01"}],
        "core_cap_daily": [{"d": "2026-10-07", "arm": "cap_a1", "nav": 0.98, "inception": "2026-10-02"}]}}
    current = {
        "allocation_daily": [{"d": "2026-10-07", "book": "core_cap", "weight": 1, "why": ["new"]}],
        "core_variants_daily": [{"d": "2026-10-07", "arm": "btc", "nav": 5.1, "inception": "2026-10-08"}],
        "multiplier_daily": [{"d": "2026-10-07", "arm": "mult_v1", "nav": 1.0, "inception": "2026-10-01"},
                             {"d": "2026-10-07", "arm": "mult_v2", "nav": 1.0, "inception": "2026-10-01"}],
        "core_cap_daily": [{"d": "2026-10-07", "arm": "cap_a1", "nav": 0.98, "inception": "2026-10-02"},
                           {"d": "2026-10-07", "arm": "late", "nav": 1.0, "inception": "2026-10-02"}]}
    out = compare(anchored, current)
    assert out["changed"] == [{"table": "allocation_daily", "key": "core_cap", "fields": ["why"]}]
    assert out["replay_rows_excluded"] == 1 and out["matches_current_tables"] is False
    assert out["added_after_anchor"] == [{"table": "core_cap_daily", "key": "late"}], "v1 没收的 mult_v2 不算补进"
    same = compare({"schema": "T-073 anchor v2", "sources": {"core_cap_daily": current["core_cap_daily"][:1]}},
                   {"core_cap_daily": current["core_cap_daily"][:1]})
    assert same["matches_current_tables"] is True and same["changed"] == [] and same["forward_rows_checked"] == 1


def test_anchor_day_is_the_frozen_day() -> None:
    """锚「今天 − 2」:那一天的前向行刚被冻结,之后不再变。"""
    import inspect
    from src.data.accounting import anchor
    from src.data.accounting.forward_lock import FINAL_LAG_DAYS
    assert FINAL_LAG_DAYS == 2
    assert "timedelta(days=FINAL_LAG_DAYS)" in inspect.getsource(anchor.run_once)
