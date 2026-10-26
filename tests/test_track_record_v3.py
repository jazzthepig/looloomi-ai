"""track-record v3(2026-10-26 用户报告):β 调整层第一次上线;每组合计行不能让 headline 把一个信号算两遍;
闸门关着时 β 字段压住、状态说「算了但被压住」而不是「从未上线」。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.api.routers._track_record_agg import build_headline, group_summary  # noqa: E402
from src.api.routers.signals import beta_layer_status  # noqa: E402

ROWS = [
    {"grp": "crypto", "signal": "OUTPERFORM", "grade": "B", "n": 100, "avg_alpha_pct": 1.0, "alpha_win_pct": 50.0,
     "avg_edge_beta_adj_pct": -0.5, "edge_beta_adj_t": -2.0, "n_beta_adj": 90, "avg_beta_pit": 1.1},
    {"grp": "crypto", "signal": "OUTPERFORM", "grade": "C", "n": 100, "avg_alpha_pct": 3.0, "alpha_win_pct": 60.0,
     "avg_edge_beta_adj_pct": 0.5, "edge_beta_adj_t": 1.0, "n_beta_adj": 90, "avg_beta_pit": 1.2},
    {"grp": "crypto", "signal": "OUTPERFORM", "grade": "ALL", "n": 200, "n_months": 40, "avg_alpha_pct": 2.0,
     "alpha_win_pct": 55.0, "alpha_t_month": 0.8, "avg_edge_beta_adj_pct": 0.0, "edge_beta_adj_t": -0.4,
     "edge_beta_adj_t_month": -0.1, "n_beta_adj": 180, "avg_beta_pit": 1.15,
     "edge_vs_neutral_pct": -0.3, "edge_vs_neutral_t_month": -0.2},
]


def test_headline_ignores_the_all_rows_so_n_is_not_doubled():
    h = build_headline(ROWS)
    assert h["RAW"]["OUTPERFORM_broad"]["n"] == 200 and abs(h["RAW"]["OUTPERFORM_broad"]["avg_alpha_pct"] - 2.0) < 1e-9
    assert h["BETA_ADJ"]["OUTPERFORM_broad"]["n"] == 180


def test_group_summary_keeps_groups_apart_and_carries_month_clustered_t():
    g = group_summary(ROWS, gate_open=True)
    cell = g["crypto"]["OUTPERFORM_broad"]
    assert cell["n_months"] == 40 and cell["edge_beta_adj_t_month"] == -0.1 and cell["n"] == 200
    assert cell["edge_vs_neutral_pct"] == -0.3 and cell["edge_vs_neutral_t_month"] == -0.2


def test_closed_gate_withholds_beta_fields_but_not_raw():
    cell = group_summary(ROWS, gate_open=False)["crypto"]["OUTPERFORM_broad"]
    assert cell["avg_edge_beta_adj_pct"] is None and cell["edge_beta_adj_t_month"] is None
    assert cell["edge_vs_neutral_pct"] is None and cell["edge_vs_neutral_t_month"] is None
    assert cell["avg_alpha_pct"] == 2.0 and cell["alpha_t_month"] == 0.8


def test_layer_status_says_suppressed_not_never_deployed_when_the_gate_holds_it():
    st = beta_layer_status({"BETA_ADJ": {"OUTPERFORM_broad": None}}, ROWS, gate_open=False)
    assert st["status"] == "computed_but_suppressed"
