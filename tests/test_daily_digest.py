"""每日简报(11-01):纯文本、一天一次、读不到写「读不到」不写 0、不出现买卖字样。"""
import datetime as dt

from src.data.ops import daily_digest as dd


def test_compose_puts_real_money_first_and_marks_unreadable_sections():
    live = [{"d": "2026-10-30", "equity_usd": 629.49, "usdc": 338.11, "spot_usd": {"SPYX": 175.04, "XAUT0": 116.34}, "nav": 0.99817, "ret": -0.0018},
            {"d": "2026-10-31", "equity_usd": 629.52, "usdc": 338.11, "spot_usd": {"SPYX": 175.1, "XAUT0": 116.3}, "nav": 0.99822, "ret": 0.00005,
             "account_mode": "unifiedAccount", "note": "['SPYX', 'XAUT0'] 按最后一次心跳的 HL 中间价估值"}]
    ex = [{"sleeve": "t25_legs_live", "n_intents": 2, "fill_rate": 1.0, "mean_slippage_bps": 3.492, "implementation_shortfall_bps": 10.492,
           "median_decision_to_fill_s": 9.27},
          {"sleeve": "t25_legs_host_dry", "n_intents": 2, "fill_rate": None, "mean_slippage_bps": None, "implementation_shortfall_bps": None}]
    host = [{"at": "2026-11-01T00:08:34Z", "outcome": "ok", "detail": {"book": "t25", "kind": "cycle", "orders": []}},
            {"at": "2026-11-01T00:08:34Z", "outcome": "ok", "detail": {"book": "x1v", "kind": "cycle", "orders": []}},
            {"at": "2026-11-01T00:45:00Z", "outcome": "ok", "detail": {"book": "r_v2", "kind": "cycle", "intents_written": 1}},
            {"at": "2026-11-01T00:50:00Z", "outcome": "ok", "detail": {"book": "x1v", "kind": "heartbeat"}}]
    text = dd.compose("2026-11-01", live, ex, host, [{"loop_name": "_forward_record_loop", "reason": "no response"}], 4, ["PROJECT_STATE: OSError"],
                      host_code="d318119d", railway_code="ab12cd34")
    lines = text.split("\n")
    assert lines[0].startswith("CometCloud 日报 · 2026-11-01")
    assert "净值 629.52 USDC" in lines[1] and "当日 +0.01%" in lines[2] and "开账以来 -0.18%" in lines[2] and "SPYX 175" in lines[2]
    assert "x1v 1 轮 / 0 单" in text and "t25 1 轮 / 0 单" in text and "r_v2 1 轮 / 1 单" in text, "心跳不算轮次"
    assert "t25_legs_live 2 笔 成交率 100% 滑点 +3.5bp 差额 +10.5bp 决策→回报 9.3s" in text and "host_dry" not in text, "空跑账不进简报"
    assert "代码: 主机 d318119d · Railway ab12cd34" in text
    assert "循环不 ok: _forward_record_loop" in text and "OPEN RISKS: 4 条" in text and "读不到的段: PROJECT_STATE" in text
    for w in ("buy", "sell", "BUY", "SELL", "买", "卖"):
        assert w not in text, w


def test_empty_inputs_say_so_instead_of_zero():
    text = dd.compose("2026-11-01", [], [], [], [], None)
    assert "快照还没落" in text and "没有任何回报" in text and "循环: 全部 ok" in text and "OPEN RISKS: 读不到" in text
    assert " 0 USDC" not in text
    assert "心跳里没有(旧版主机)" in text


def test_once_a_day_after_0100_utc():
    """11-02:00:30 发的第一条把 00:45 才跑的 R-v2 写成「没跑」—— 挪到 01:00。"""
    t = dt.datetime(2026, 11, 1, 0, 59, tzinfo=dt.timezone.utc)
    assert not dd.due(t, sent_today=False)
    assert dd.due(t.replace(hour=1, minute=0), sent_today=False)
    assert not dd.due(t.replace(hour=9), sent_today=True)


def test_open_risks_count_reads_only_top_level_items():
    md = "# x\n\n## OPEN RISKS (≤7)\n\nintro\n\n1. **a**\n   VERIFY: x\n   1. sub\n2. **b**\n\n## next\n\n3. **not counted**\n"
    assert dd.open_risks_count(md) == 2
    assert dd.open_risks_count("# nothing") is None


def test_decision_triggers_from_11_02_are_watched_every_day():
    """DECISIONS 11-02:净值过 $5 万 ⇒ 独立账户 / key / 第二台主机;腿目标超过 HL ±2% 深度 ⇒ 走券商;每月 1 号提醒重跑探针。"""
    assert dd.decision_lines("2026-11-02", 630.0, {"XAUT0": 126.0, "SPYX": 189.0}, {"XAUT0": 25_625.0, "SPYX": 65_294.0}) == []
    big = dd.decision_lines("2026-12-15", 60_000.0, {"XAUT0": 12_000.0, "SPYX": 18_000.0}, {"XAUT0": 25_625.0, "SPYX": 15_000.0})
    assert len(big) == 2 and "独立 HL 账户" in big[0] and "SPYX 腿目标 $18,000 > HL 现货 ±2% 深度 $15,000" in big[1]
    assert dd.decision_lines("2026-12-01", None, {}, {}) == ["提醒(每月 1 号):重跑 scripts/host_probe_spot_trigger.command —— HL 现货触发单开了没有"]
    assert dd.decision_lines("2026-12-02", 100.0, {"XAUT0": 50.0}, {}) == [], "没有深度数据不猜"
    text = dd.compose("2026-12-01", [], [], [], [], 3, decisions=dd.decision_lines("2026-12-01", None, {}, {}))
    assert text.endswith("HL 现货触发单开了没有")


def test_digest_reports_scenario_calibration_by_author():
    """S-705:lane 的概率准不准每天在简报里看得到;没结算时只说已写几条。"""
    from src.data.ops.daily_digest import calibration_lines
    assert calibration_lines([], []) == []
    e = [{"id": "a1", "author": "lane-a", "prob": 0.8}, {"id": "a2", "author": "lane-a", "prob": 0.3}, {"id": "s1", "author": "seth", "prob": 0.5}]
    assert "已写 3 条" in calibration_lines(e, [])[0]
    line = calibration_lines(e, [{"id": "a1", "outcome": True, "brier": 0.04}, {"id": "a2", "outcome": True, "brier": 0.49}])[0]
    assert "lane-a 2 条" in line and "Brier 0.265" in line and "seth" not in line


def test_mcp_mount_failure_is_a_recorded_loop_error():
    """11-03:/mcp 没挂上几周没人看见。开机记 `_mcp_mount`;没挂 = error ⇒ 简报的「不 ok 的循环」列出来。"""
    src = (ROOT / "src/api/main.py").read_text(encoding="utf-8") if "ROOT" in globals() else __import__("pathlib").Path(__file__).resolve().parents[1].joinpath("src/api/main.py").read_text(encoding="utf-8")
    assert "_MCP_MOUNT_ERROR = f\"{type(_mcp_err).__name__}" in src
    assert 'await _iteration_result("_mcp_mount", {"ok": False' in src
