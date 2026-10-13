"""S-561 / T-026:fusion 账本 51 天只记 −成本 —— 状态写入用了表里不存在的列名。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_state_write_and_read_use_the_live_column_names() -> None:
    """S-561 / T-026:写 `inception`(表里没有这一列)⇒ 每次插入被拒、状态读回 {} ⇒ 51 天只记 −成本。"""
    import asyncio
    import src.api.store as store
    from src.data.signals import fusion_paper as fp
    seen = []

    async def fake_insert(table, rows):
        seen.append((table, rows))
        return False                     # 失败:不进缓存这一支

    orig = getattr(store, "supabase_insert_table", None)
    store.supabase_insert_table = fake_insert
    try:
        asyncio.run(fp._save_state({"inception": "2026-10-14", "last_mark": "2026-10-14", "nav": 1.0,
                                    "weights": {"BTC": 0.1}, "cell": {"w_R46": 0.5}}))
    finally:
        if orig is not None:
            store.supabase_insert_table = orig
    (table, rows), = seen
    assert table == fp._STATE_TABLE and set(rows[0]) <= fp.LIVE_STATE_COLUMNS, set(rows[0]) - fp.LIVE_STATE_COLUMNS
    assert rows[0]["inception_id"] == fp._INCEPTION_ID and rows[0]["cell"]["inception_date"] == "2026-10-14"
    import inspect
    src = inspect.getsource(fp._fetch_state_from_supabase)
    assert "select=inception_id," in src and "inception_id=eq." in src and "select=inception," not in src
