"""S-491:track-record 的说明文字只能说数据里有的东西。

`signal_track_record` 自 2026-07-01 起 `n_beta_adj` 没有一行非空,而端点与 MCP 工具三个月来一直写着
「最高档 β 调整后为正、宽泛档恢复为正」。agent 用这个工具「决定信任多少」—— 这是对外最不能错的一句话。
"""
import pathlib

from src.api.routers.signals import track_record_note


def test_empty_beta_layer_is_said_plainly_and_no_edge_is_claimed():
    note = track_record_note({"BETA_ADJ": {"STRONG_OUTPERFORM": None, "OUTPERFORM_broad": None}})
    assert "EMPTY" in note and "no β-adjusted edge is claimed" in note
    assert "positive" not in note.lower()


def test_populated_beta_layer_is_not_pre_judged():
    note = track_record_note({"BETA_ADJ": {"STRONG_OUTPERFORM": {"n": 10, "avg_edge_beta_adj_pct": 1.2}}})
    assert "EMPTY" not in note and "positive" not in note.lower()


def test_no_hardcoded_edge_claims_left_in_the_agent_surface():
    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in ("src/api/routers/signals.py", "src/mcp/cometcloud_mcp.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "delivers positive β-ADJ" not in text, rel
        assert "restores it to a positive" not in text, rel
