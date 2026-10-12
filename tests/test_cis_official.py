"""T-080 / S-533 — official CIS = the unified-standard daily-close series.

Guards: (1) a batch only publishes when complete (or after the deadline, flagged);
(2) the published level continues yesterday's level through the ±10-percentile buffer;
(3) the API overlay replaces score/grade/signal/pillars with the official row, keeps the live
values under `intraday`, never mutates the cached live payload, and says so when it could not
apply; (4) writers that RECORD the live series ask for it explicitly.
"""
from __future__ import annotations

import copy
import inspect
from datetime import date
from pathlib import Path

from src.data.cis.official import completeness, official_rows, overlay
from src.data.cis.rebuild import CODE_REF

BASE = Path(__file__).resolve().parents[1]


def _row(sym, cls="L1", pct=0.5, fng=50, dom=0.55):
    return {"symbol": sym, "d": "2026-10-10", "asset_class": cls, "raw_score": 60.0, "score": 58.0,
            "grade": "B+", "pct": pct, "pillar_f": 50, "pillar_m": 60, "pillar_o": 55, "pillar_s": 40,
            "pillar_a": 70, "regime": "TIGHTENING", "inputs": {"fng": fng, "btc_dom": dom}, "missing": []}


def _assets(n_crypto=10, n_tradfi=2):
    a = {f"C{i}": {"class": "L1"} for i in range(n_crypto - 1)}
    a["BTC"] = {"class": "L1"}
    a.update({f"T{i}": {"class": "US Equity"} for i in range(n_tradfi)})
    return a


def test_completeness_ok_and_failures():
    assets = _assets()
    rows = [_row(s) for s in assets]
    assert completeness(rows, assets) == []
    no_btc = [r for r in rows if r["symbol"] != "BTC"]
    assert any("BTC" in p for p in completeness(no_btc, assets))
    thin = [r for r in rows if r["symbol"] not in ("C0", "C1")]
    assert any("8/10" in p for p in completeness(thin, assets))
    no_fng = [_row(s, fng=None) if s == "BTC" else _row(s) for s in assets]
    assert completeness(no_fng, assets) == ["恐惧贪婪缺"]


def test_official_rows_continue_yesterdays_level_through_the_buffer():
    # yesterday OUTPERFORM (3); today pct 0.62 is inside the 0.70−0.10 buffer → stays OUTPERFORM, watch down
    out = official_rows([_row("X", pct=0.62)], {"X": 3}, "2026-10-11T00:10:00+00:00")
    assert out[0]["signal"] == "OUTPERFORM" and out[0]["watch"] == "down"
    # pct 0.55 crosses below the buffer → NEUTRAL
    out = official_rows([_row("X", pct=0.55)], {"X": 3}, "t")
    assert out[0]["signal"] == "NEUTRAL"
    # no yesterday → raw level
    out = official_rows([_row("Y", pct=0.95)], {}, "t")
    assert out[0]["signal"] == "STRONG OUTPERFORM" and out[0]["watch"] is None
    r = out[0]
    assert r["cis_score"] == 60.0 and r["regime_adjusted_score"] == 58.0 and r["code_ref"] == CODE_REF
    assert r["published_at"] == "t"


def _live():
    return {"status": "success", "macro_regime": "RISK_ON", "regime_confidence": 0.4, "timestamp": "now",
            "source": "merged", "universe": [
                {"symbol": "BTC", "cis_score": 70.0, "raw_cis_score": 70.0, "regime_adjusted_score": 69.0,
                 "grade": "A", "signal": "OUTPERFORM", "f": 1, "m": 2, "o": 3, "s": 4, "a": 5,
                 "pillars": {"F": 1}, "percentile_rank": 90.0, "macro_regime": "RISK_ON", "price": 1.0},
                {"symbol": "eth", "cis_score": 50.0, "grade": "C+", "signal": "NEUTRAL", "price": 2.0},
                {"symbol": "NEW", "cis_score": 40.0, "grade": "C", "signal": "UNDERPERFORM"},
            ]}


def _latest():
    def off(sym, score, sig, pct):
        return {"symbol": sym, "d": "2026-10-10", "cis_score": score, "regime_adjusted_score": score - 1,
                "grade": "B", "signal": sig, "watch": None, "pct": pct, "pillar_f": 10, "pillar_m": 20,
                "pillar_o": 30, "pillar_s": 40, "pillar_a": 50, "regime": "TIGHTENING", "missing": ["oi"],
                "code_ref": CODE_REF, "published_at": "2026-10-11T00:10:00+00:00"}
    return {"d": "2026-10-10", "code_ref": CODE_REF, "published_at": "2026-10-11T00:10:00+00:00",
            "rows": {"BTC": off("BTC", 55.0, "NEUTRAL", 0.5), "ETH": off("ETH", 62.0, "OUTPERFORM", 0.8)}}


def test_overlay_replaces_official_fields_and_keeps_live_under_intraday():
    live = _live()
    before = copy.deepcopy(live)
    out = overlay(live, _latest(), today=date(2026, 10, 11))
    assert live == before, "overlay must not mutate the cached live payload"
    by = {a["symbol"].upper(): a for a in out["universe"]}
    btc = by["BTC"]
    assert btc["cis_score"] == 55.0 and btc["signal"] == "NEUTRAL" and btc["grade"] == "B"
    assert btc["pillars"] == {"F": 10, "M": 20, "O": 30, "S": 40, "A": 50} and btc["f"] == 10
    assert btc["percentile_rank"] == 50.0 and btc["group_percentile"] == 0.5
    assert btc["signal_basis"] == "daily_close" and btc["official_date"] == "2026-10-10"
    assert btc["intraday"]["signal"] == "OUTPERFORM" and btc["intraday"]["cis_score"] == 70.0
    assert btc["price"] == 1.0
    assert by["ETH"]["signal"] == "OUTPERFORM", "symbol match is case-insensitive"
    assert by["NEW"]["signal_basis"] == "intraday" and "intraday" not in by["NEW"]
    assert [a["symbol"] for a in out["universe"]] == ["eth", "BTC", "NEW"], "re-sorted by official score"
    assert out["macro_regime"] == "TIGHTENING" and out["intraday"]["macro_regime"] == "RISK_ON"
    o = out["official"]
    assert o["applied"] and o["d"] == "2026-10-10" and o["age_days"] == 1 and o["covered"] == 2 and o["total"] == 3
    assert "UTC daily close" in o["method"]
    assert overlay(out, _latest()) is out, "idempotent"


def test_overlay_without_publication_serves_live_and_says_so():
    live = _live()
    out = overlay(live, {"rows": {}, "reason": "no official publication yet"})
    assert out["universe"] == live["universe"]
    assert out["official"]["applied"] is False and out["official"]["reason"] == "no official publication yet"
    assert overlay(live, None)["official"]["applied"] is False
    assert overlay({"universe": []}, _latest()) == {"universe": []}


def test_official_basis_is_compliance_clean():
    from src.api.contracts.disclosure import OFFICIAL_BASIS, OFFICIAL_BASIS_ZH
    low = OFFICIAL_BASIS.lower()
    for w in ("buy", "sell", "accumulate", "avoid", "reduce", "will outperform", "predict"):
        assert w not in low
    assert "UTC" in OFFICIAL_BASIS and "UTC" in OFFICIAL_BASIS_ZH


def test_universe_endpoint_defaults_to_official_and_only_recorders_opt_out():
    from src.api.routers import cis
    sig = inspect.signature(cis.get_cis_universe)
    assert sig.parameters["official"].default is True
    src = (BASE / "src/api/routers/cis.py").read_text()
    i = src.index("async def snapshot_full_universe_to_supabase")
    assert "get_cis_universe(force_source=None, official=False)" in src[i:i + 600]
    # S-539:前向记录(档位带、conviction、纸面再平衡、crowd_clock)也读正式序列,版本边界 2026-10-12
    for path in ("src/api/routers/trading.py", "src/api/routers/signals.py", "src/api/main.py", "src/data/market/crowd_clock.py"):
        assert "official=False" not in (BASE / path).read_text(), path

def test_methodology_page_mirrors_official_basis():
    import json
    import re
    from src.api.contracts.disclosure import OFFICIAL_BASIS
    text = (BASE / "dashboard/src/components/MethodologyPage.jsx").read_text(encoding="utf-8")
    m = re.search(r"^const OFFICIAL_BASIS = (\".*\");$", text, re.M)
    assert m and json.loads(m.group(1)) == OFFICIAL_BASIS, "改 disclosure.py 的口径,同步 MethodologyPage"


def _patch_run(monkeypatch, *, have_rows, prev, rows, now_hour=7, ready=True, refresh_log=None):
    import asyncio
    from datetime import datetime, timezone
    from types import SimpleNamespace
    import src.api.store as store
    import src.data.cis.official as off
    import src.data.cis.rebuild as rb
    import src.data.vector.market_state_writer as msw
    written = []

    async def sb_get(table, params):
        return SimpleNamespace(ok=True, rows=[{"d": "x"}] if have_rows else [], reason="")

    async def load_inputs(d):
        return _assets(), {}

    async def prev_rows(d):
        from src.data.cis.rebuild import LEVELS
        return {k: {"grade": "B", "signal": LEVELS[v] if v is not None else None} for k, v in prev.items()}

    async def no_events(out, prev_rows, d):
        return {}

    async def insert(table, out):
        written.extend(out)
        return SimpleNamespace(ok=True, why="")

    monkeypatch.setattr(msw, "_sb_get", sb_get)
    monkeypatch.setattr(rb, "load_inputs", load_inputs)
    monkeypatch.setattr(rb, "score_day", lambda d, a, data: [dict(r) for r in rows])
    monkeypatch.setattr(off, "_prev_rows", prev_rows)
    monkeypatch.setattr(off, "publish_events", no_events)
    monkeypatch.setattr(store, "supabase_insert_table", insert)

    async def inputs_ready(d):
        return ready

    async def refresh(now):
        if refresh_log is not None:
            refresh_log.append(now)
        return {"closes": {"rows": 1}}

    import src.data.market.cis_inputs as ci
    monkeypatch.setattr(off, "_close_inputs_ready", inputs_ready)
    monkeypatch.setattr(ci, "refresh_close_inputs", refresh)
    now = datetime(2026, 10, 11, now_hour, 5, tzinfo=timezone.utc)
    return asyncio.run(off.run_once(now)), written


def test_run_once_publishes_once_and_waits_for_a_seed(monkeypatch):
    rows = [_row(s, cls=c["class"]) for s, c in _assets().items()]
    res, w = _patch_run(monkeypatch, have_rows=True, prev={"BTC": 2}, rows=rows)
    assert res["written"] == 0 and "只发一次" in res["reason"] and not w
    res, w = _patch_run(monkeypatch, have_rows=False, prev={}, rows=rows)
    assert res["refused"] and not w, "no previous level anywhere → do not seed the chain without hysteresis"
    assert res["ok"] is False, "still waiting after the deadline must turn the heartbeat red"
    res, w = _patch_run(monkeypatch, have_rows=False, prev={}, rows=rows, now_hour=2)
    assert res["refused"] and res["ok"] is True and not w
    res, w = _patch_run(monkeypatch, have_rows=False, prev={"BTC": 2}, rows=rows)
    assert res["written"] == len(rows) and {r["d"] for r in w} == {"2026-10-10"}
    thin = [r for r in rows if r["symbol"] not in ("C0", "C1")]
    res, w = _patch_run(monkeypatch, have_rows=False, prev={"BTC": 2}, rows=thin, now_hour=3)
    assert res["refused"] and not w, "incomplete before the deadline → wait"
    res, w = _patch_run(monkeypatch, have_rows=False, prev={"BTC": 2}, rows=thin, now_hour=7)
    assert res["refused"] and res["ok"] is False and not w, "S-538:大部分加密没有收盘 = 硬性缺,过了 06:00 也不发半批"


def test_soft_gaps_publish_after_deadline_and_missing_closes_are_fetched(monkeypatch):
    rows = [_row(s, cls=c["class"], fng=None if s == "BTC" else 50) for s, c in _assets().items()]
    log: list = []
    res, w = _patch_run(monkeypatch, have_rows=False, prev={"BTC": 2}, rows=rows, now_hour=3, ready=False, refresh_log=log)
    assert res["refused"] and not w and len(log) == 1, "收盘输入没落库 → 发布器自己补一次,再判"
    res, w = _patch_run(monkeypatch, have_rows=False, prev={"BTC": 2}, rows=rows, now_hour=7)
    assert res["written"] == len(rows) and all("batch:恐惧贪婪缺" in r["missing"] for r in w), "软性缺:过点照发并标出"
    from src.data.cis.official import is_hard
    assert is_hard("BTC 没有价格") and is_hard("加密名字有价的 3/25") and not is_hard("恐惧贪婪缺")


def test_change_events_compare_with_previous_official_day():
    from src.data.cis.official import change_events
    out = [{"symbol": "A", "d": "2026-10-11", "grade": "A", "signal": "OUTPERFORM", "cis_score": 76.0, "asset_class": "L1"},
           {"symbol": "B", "d": "2026-10-11", "grade": "B", "signal": "NEUTRAL", "cis_score": 56.0, "asset_class": "L1"},
           {"symbol": "C", "d": "2026-10-11", "grade": "C", "signal": "UNDERPERFORM", "cis_score": 40.0, "asset_class": "L1"},
           {"symbol": "NEW", "d": "2026-10-11", "grade": "B", "signal": "NEUTRAL", "cis_score": 55.0, "asset_class": "L1"}]
    prev = {"A": {"grade": "B+", "signal": "OUTPERFORM"}, "B": {"grade": "B", "signal": "OUTPERFORM"},
            "C": {"grade": "C+", "signal": "NEUTRAL"}}
    ev = change_events(out, prev)
    assert [e["symbol"] for e in ev["GRADE_UPGRADE"]] == ["A"] and ev["GRADE_UPGRADE"][0]["delta"] == 1
    assert [e["symbol"] for e in ev["GRADE_DOWNGRADE"]] == ["C"]
    assert [(e["symbol"], e["from"], e["to"]) for e in ev["SIGNAL_CHANGE"]] == [("B", "OUTPERFORM", "NEUTRAL")]
    assert all(e["symbol"] != "NEW" for v in ev.values() for e in v), "没有前一天的名字不算变化"


def test_official_journal_ops_open_and_close_on_official_levels():
    from src.api.routers.signals import OFFICIAL_STRATEGY, official_journal_ops
    rows = [{"symbol": "A", "signal": "STRONG OUTPERFORM", "grade": "A", "cis_score": 80, "inputs": {"price": 10.0}},
            {"symbol": "B", "signal": "NEUTRAL", "grade": "B", "cis_score": 55, "inputs": {"price": 12.0}},
            {"symbol": "C", "signal": "OUTPERFORM", "grade": "B+", "cis_score": 66, "inputs": {"price": 5.0}}]
    open_rows = {"B": {"id": 7, "entry_price": 10.0, "signal_date": "2026-10-01T00:00:00+00:00"},
                 "C": {"id": 8, "entry_price": 4.0, "signal_date": "2026-10-05T00:00:00+00:00"}}
    new, closes = official_journal_ops(rows, open_rows, "2026-10-12T00:00:00+00:00")
    assert [r["symbol"] for r in new] == ["A"] and new[0]["strategy"] == OFFICIAL_STRATEGY
    assert new[0]["signal"] == "STRONG_OUTPERFORM" and new[0]["entry_price"] == 10.0
    assert closes == [(7, {"exit_price": 12.0, "exit_date": "2026-10-12T00:00:00+00:00", "exit_reason": "SIGNAL_TO_NEUTRAL",
                           "return_pct": 20.0, "holding_days": 11.0})]


def test_history_rows_prefer_published_and_carry_provenance():
    from src.data.cis.official import history_rows
    reb = [{"symbol": "BTC", "d": "2026-10-09", "raw_score": 60.0, "score": 58.0, "grade": "B", "signal_pct": "NEUTRAL",
            "pct": 0.5, "regime": "RISK_ON"},
           {"symbol": "BTC", "d": "2026-10-10", "raw_score": 61.0, "score": 59.0, "grade": "B", "signal_pct": "NEUTRAL",
            "pct": 0.5, "regime": "RISK_ON"}]
    off = [{"symbol": "BTC", "d": "2026-10-10", "cis_score": 62.0, "regime_adjusted_score": 60.0, "grade": "B",
            "signal": "OUTPERFORM", "pct": 0.7, "regime": "RISK_ON"}]
    h = history_rows(off, reb)["BTC"]
    assert [(p["d"], p["score"], p["signal"], p["provenance"]) for p in h] == [
        ("2026-10-09", 60.0, "NEUTRAL", "reconstructed"), ("2026-10-10", 62.0, "OUTPERFORM", "published")]
    assert h[1]["score_delta"] == 2.0 and h[0]["score_delta"] is None


def test_official_changes_window():
    from src.data.cis.official import official_changes
    hist = {"X": [{"d": "2026-10-08", "grade": "B", "signal": "NEUTRAL", "score": 56.0},
                  {"d": "2026-10-10", "grade": "B+", "signal": "OUTPERFORM", "score": 66.0}],
            "Y": [{"d": "2026-10-10", "grade": "C", "signal": "NEUTRAL", "score": 40.0}]}
    ch = official_changes(hist, 2)
    assert [u["symbol"] for u in ch["upgrades"]] == ["X"] and ch["upgrades"][0]["delta"] == 1
    assert ch["signal_changes"][0]["to_signal"] == "OUTPERFORM" and ch["stable_count"] == 1


def test_every_cis_surface_reads_the_official_series():
    """S-539(Jazz 10-12):页面 / 接口 / 事件 不得直读实时引擎的分数。只有写盘中历史的快照和日志价格回填可以。"""
    import inspect
    from src.api.routers import agent, cis, market, share, signals, social, strategies, trading, vector
    from src.data.market import crowd_clock
    live = ("calculate_cis_universe(", "redis_get()", "supabase_get_history(", "official=False",
            'redis_get_key("cis:local_scores")', 'redis_get("cis:local_scores")')
    must_be_official = [
        agent._exec_portfolio_analysis, agent._exec_cis_snapshot, agent._exec_regime_briefing, agent._exec_trade_signal,
        share.og_image, social._fetch_cis_top5, strategies.strategy_universe, trading._get_cis_for_symbol,
        trading._run_paper_rebalance, vector._get_cached_universe, signals.compute_current_band, signals.get_conviction,
        signals.assemble_briefing, market.get_signals, crowd_clock.get_crowd_clock,
        cis.get_cis_history, cis.get_cis_trend, cis.cis_history, cis.cis_trend, cis.get_grade_changes,
        cis.get_regime_transitions,
    ]
    bad = [f"{f.__module__}.{f.__name__}" for f in must_be_official if any(x in inspect.getsource(f) for x in live)]
    assert not bad, f"直读实时引擎的分数:{bad}"
    assert cis.LIVE_PUSH_FIRES_EVENTS is False, "实时推送不发对外事件 / 不记信号日志"
    assert "regime_overlay" in inspect.getsource(market.macro_pulse), "宏观脉搏的市场状态 = 正式日终那天的"
    src = inspect.getsource(cis.get_cis_history_batch)
    assert "official: bool = Query(default=True)" in src and "standard_history" in src


def test_regime_overlay_and_transitions():
    from src.data.cis.official import regime_overlay, regime_transitions
    pulse = {"macro_regime": "TIGHTENING", "regime_source": "mac_mini", "fng": {"value": 61}}
    latest = {"d": "2026-10-11", "rows": {"BTC": {"regime": "RISK_ON"}, "ETH": {"regime": "RISK_ON"}}}
    out = regime_overlay(pulse, latest)
    assert out["macro_regime"] == "RISK_ON" and out["intraday_regime"]["macro_regime"] == "TIGHTENING"
    assert out["regime_as_of"] == "2026-10-11" and pulse["macro_regime"] == "TIGHTENING", "不改入参"
    assert regime_overlay(pulse, {"rows": {}}) is pulse, "没有正式发布 → 原样"
    pts = [{"d": "2026-10-08", "regime": "TIGHTENING"}, {"d": "2026-10-09", "regime": "TIGHTENING"},
           {"d": "2026-10-10", "regime": "RISK_ON", "provenance": "published"}]
    assert regime_transitions(pts) == [{"symbol": None, "previous_regime": "TIGHTENING", "new_regime": "RISK_ON",
                                        "transition_time": "2026-10-10", "provenance": "published"}]
