"""一本账换了 inception,库里的 CHECK 必须跟着放行 —— 否则新的那一段一行都写不进去(T-026 / S-607)。

10-13 fusion 的 `_INCEPTION_ID` 改成 "v3"(S-561),而 `fusion_paper_nav_inception_chk` 只放行 ('v1', 'v2')。
从那天起每一次写入都被 23514 拒绝 —— 先被 Binance 451 盖住(账本根本走不到写入那一步),
S-607 修好取价之后第一次 mark 才露出来(10-19 00:05–00:33 UTC,14 次全拒)。

本文件从 `migrations/` 里取每张表**最后一次**定义的 inception CHECK,断言对应模块的 `_INCEPTION_ID` 在里面。
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
#: 表 → 写它的模块(模块里的 `_INCEPTION_ID`)
BOOKS = {"fusion_paper_nav": "src/data/signals/fusion_paper.py"}
_CHK = re.compile(r"ADD\s+CONSTRAINT\s+(\w+)_inception_chk\s+CHECK\s*\(\s*inception_id\s+IN\s*\(([^)]*)\)\s*\)", re.I | re.S)


def allowed_ids() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for p in sorted((ROOT / "migrations").glob("*.sql")):
        for table, ids in _CHK.findall(p.read_text(encoding="utf-8")):
            out[table] = {s.strip().strip("'\"") for s in ids.split(",") if s.strip()}
    return out


def inception_id(module: str) -> str:
    tree = ast.parse((ROOT / module).read_text(encoding="utf-8"))
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "_INCEPTION_ID" for t in n.targets):
            return ast.literal_eval(n.value)
    raise AssertionError(f"{module} 没有 _INCEPTION_ID")


def test_every_book_inception_is_allowed_by_its_latest_check():
    allowed = allowed_ids()
    for table, module in BOOKS.items():
        assert table in allowed, f"migrations/ 里找不到 {table}_inception_chk"
        iid = inception_id(module)
        assert iid in allowed[table], (
            f"{module} 写的是 inception {iid!r},而 {table}_inception_chk 只放行 {sorted(allowed[table])} —— "
            "新的一段会一行都写不进去。先加迁移放行它,再改 _INCEPTION_ID。")


def test_the_parser_reads_the_last_definition():
    sql = "ADD CONSTRAINT t_inception_chk CHECK (inception_id IN ('v1', 'v2'));"
    assert _CHK.findall(sql) == [("t", "'v1', 'v2'")]
