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
