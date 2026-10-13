"""S-560:锚定之后前向记录还在被改写(配置层 why、meta_knn、core_variants 的前向 nav / ret)。

六个整条重算的写入端写之前都过 forward_lock:d ≤ 今天 − 2 的前向行已存在就不再改;晚到的可以补;
未冻结的新行 NAV 从前一行已存的接着乘;回放行(d < inception)照写。
"""
from __future__ import annotations

import ast
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.accounting.forward_lock import cutoff, lock_rows  # noqa: E402

TODAY = date(2026, 10, 13)          # 截止日 10-11


def _r(d, nav, ret, arm="a", inc="2026-10-08"):
    return {"d": d, "arm": arm, "nav": nav, "ret": ret, "inception": inc}


def test_frozen_forward_rows_are_not_rewritten_and_new_rows_chain_from_the_stored_nav() -> None:
    assert cutoff(TODAY) == "2026-10-11"
    stored = [_r("2026-10-08", 1.00, 0.0), _r("2026-10-09", 1.10, 0.10), _r("2026-10-10", 1.21, 0.10),
              _r("2026-10-11", 1.21, 0.0), _r("2026-10-12", 1.30, 0.07)]
    # 本轮整条重算:上游修订让历史水位全变了(1.0 → 2.0 起),最后两天的 ret 是 +1% / +2%
    rows = [_r("2026-10-07", 1.9, 0.0), _r("2026-10-08", 2.0, 0.0), _r("2026-10-09", 2.2, 0.1), _r("2026-10-10", 2.4, 0.09),
            _r("2026-10-11", 2.5, 0.04), _r("2026-10-12", 2.525, 0.01), _r("2026-10-13", 2.5755, 0.02)]
    out, st = lock_rows(rows, stored, "arm", TODAY)
    days = {r["d"]: r for r in out}
    assert "2026-10-07" in days, "回放行照写"
    assert not {"2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11"} & set(days), "冻结的前向行不写"
    assert abs(days["2026-10-12"]["nav"] - 1.21 * 1.01) < 1e-9, "未冻结的 10-12 从 10-11 已存 NAV 接着乘"
    assert abs(days["2026-10-13"]["nav"] - 1.21 * 1.01 * 1.02) < 1e-9
    assert st["frozen_skipped"] == 4 and st["replay"] == 1


def test_late_rows_for_frozen_days_may_be_inserted_but_never_replace() -> None:
    stored = [_r("2026-10-08", 1.0, 0.0)]
    rows = [_r("2026-10-08", 9.9, 0.0), _r("2026-10-09", 9.9, 0.05)]
    out, st = lock_rows(rows, stored, "arm", TODAY)
    assert [r["d"] for r in out] == ["2026-10-09"] and abs(out[0]["nav"] - 1.05) < 1e-9
    assert st["late_inserted"] == 1


def test_allocation_days_freeze_as_a_whole_and_keys_are_independent() -> None:
    stored = [{"d": "2026-10-10", "book": "core_cap"}]
    rows = [{"d": "2026-10-10", "book": "core_cap", "why": ["new text"]}, {"d": "2026-10-10", "book": "new_book"},
            {"d": "2026-10-12", "book": "core_cap"}]
    out, _ = lock_rows(rows, stored, "book", TODAY, nav=None, ret=None, day_level=True)
    assert [(r["d"], r["book"]) for r in out] == [("2026-10-12", "core_cap")], "冻结的那天一组决定整体不动"
    other = lock_rows([_r("2026-10-09", 2.0, 0.0, arm="b")], [_r("2026-10-09", 1.0, 0.0, arm="a")], "arm", TODAY)[0]
    assert other and other[0]["arm"] == "b", "别的臂在同一天已有行,不冻结这个臂"


def test_every_full_path_writer_goes_through_the_lock() -> None:
    writers = ["src/data/signals/core_variants.py", "src/data/signals/meta_allocator.py",
               "src/data/signals/feature_arms.py", "src/data/signals/multiplier.py",
               "src/data/signals/portfolio_layer.py", "src/data/allocation/allocator.py"]
    for w in writers:
        src = (ROOT / w).read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_once")
        body = ast.get_source_segment(src, fn) or ""
        assert "write_locked(" in body, f"{w}: run_once 必须经 forward_lock 写"
        assert "supabase_upsert_table(" not in body, f"{w}: run_once 直接 upsert 会绕过冻结"
    alloc = (ROOT / "src/data/allocation/allocator.py").read_text(encoding="utf-8")
    assert 'WRITES_TABLES = ("allocation_daily", "allocation_nav_daily")' in alloc, "schema_manifest 要看得见这两张表"
