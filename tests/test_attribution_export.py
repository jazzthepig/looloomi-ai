"""信号归因可以完整导出(2026-10-26 用户报告:一次最多 200 条,17,658 条历史拉不全)。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.api.routers.cis import ATTR_CSV_COLUMNS, attribution_csv, attribution_window  # noqa: E402

ROWS = [{"symbol": s, "d": d, "signal": "OUTPERFORM", "ret_30": 0.1}
        for d in ("2026-10-03", "2026-10-02", "2026-10-01") for s in ("NEAR", "BTC")]


def test_window_filters_by_symbol_and_date_and_pages():
    page, total = attribution_window(ROWS, symbol="near", since="2026-10-02")
    assert total == 2 and [r["d"] for r in page] == ["2026-10-03", "2026-10-02"]
    page, total = attribution_window(ROWS, offset=4, limit=10)
    assert total == 6 and len(page) == 2, "offset 翻到最后一页"


def test_csv_has_every_matching_row_and_blank_for_missing():
    text = attribution_csv(ROWS)
    lines = text.strip().splitlines()
    assert lines[0].split(",") == list(ATTR_CSV_COLUMNS) and len(lines) == 1 + len(ROWS)
    assert ",,," in lines[1], "缺的字段是空,不是 None"
