"""T-017 — 宏观简报的两条路都要拿到 24h 变化,兜底模板不得带仓位建议。

2026-09-24 实测:线上简报写「市场平静、无方向」,当天总市值 24h −6.4%。
两个成因叠在一起:
  1. prompt 与模板都读 `btc_change_24h`,macro-pulse 实际给 `btc.usd_24h_change` ——
     键名对不上,24h 变化从未进过任何一条路;
  2. 「距上份简报」的几分钟增量被标成 MOVEMENT,空时写 "the tape is flat"。
同时,Railway 模板兜底每档都带一句仓位建议(Accumulation zones / contrarian entry /
Allocate / Reduce risk),而它从不过 `validate_brief`。
"""
import itertools

from src.api.contracts import macro_brief as mb
from src.api.routers.macro import _generate_template_brief

#: `/api/v1/market/macro-pulse` 在 2026-09-24 12:09 UTC 的真实形状(数值原样)。
LIVE_SHAPE = {
    "data": {"market_cap_change_percentage_24h_usd": -5.29580997413459},
    "fng": {"value": "71", "value_classification": "Greed"},
    "btc": {"usd": 83423, "usd_24h_change": -2.463484995116385},
    "btc_price": 83423, "btc_dominance": 58.740940405772065,
    "fear_greed_index": 71, "total_market_cap_usd": 2850073056979.763,
    "defi_tvl_usd": 93904094436, "macro_regime": "TIGHTENING",
}


def test_24h_changes_are_read_from_the_live_shape():
    assert round(mb.btc_change_24h(LIVE_SHAPE), 2) == -2.46
    assert round(mb.mcap_change_24h(LIVE_SHAPE), 2) == -5.30


def test_prompt_carries_the_days_move():
    p = mb.build_prompt(dict(LIVE_SHAPE), dict(LIVE_SHAPE))
    assert "BTC 24h change: -2.46%" in p
    assert "Total market cap 24h change: -5.30%" in p
    assert "the tape is flat" not in p
    assert "a quiet interval of a few\n  minutes is not a quiet market" in p


def test_template_states_the_days_move():
    t = _generate_template_brief(dict(LIVE_SHAPE))
    assert "-5.3% over 24 hours" in t and "-2.5% over 24 hours" in t
    assert "—" not in t


REGIMES = ["TIGHTENING", "EASING", "RISK_ON", "RISK_OFF", "STAGFLATION",
           "GOLDILOCKS", "SOMETHING_NEW", None]
FNG = [10, 35, 50, 65, 90, None]


def test_every_template_variant_passes_the_vocabulary_check():
    for regime, fng in itertools.product(REGIMES, FNG):
        mp = dict(LIVE_SHAPE, macro_regime=regime, fear_greed_index=fng)
        t = _generate_template_brief(mp)
        bad = [v for v in mb.validate_brief(t)["violations"]
               if not v.startswith("too short")]
        assert not bad, (regime, fng, bad, t)


def test_validator_now_catches_what_the_old_template_said():
    for phrase in ("Accumulation zones possible for A-grade assets",
                   "potential contrarian entry for high-conviction positions",
                   "Await confirmation before adding risk",
                   "Allocate across grades B+ and above",
                   "Broader exposure warranted for assets above CIS 60",
                   "Risk-off positioning favoured",
                   "Reduce risk exposure incrementally"):
        assert not mb.validate_brief(phrase)["ok"], phrase


def test_missing_inputs_are_omitted_not_dashed():
    t = _generate_template_brief({"macro_regime": "TIGHTENING"})
    assert "—" not in t and "None" not in t


# ── 接收端 / 出口:与快照矛盾的「平静」不得发布(不依赖 Mac 副本的 prompt 版本)──

#: 2026-09-24 修复推送后线上仍在服务的那份(qwen,mb-2 副本)。
LIVE_QWEN_FLAT = ("The tape is flat. No movement has crossed the reporting floor since the "
                  "last refresh, leaving the market in a state of quiet equilibrium. With no "
                  "material shifts detected in the measured data, the current standing reflects "
                  "a pause in directional activity rather than a gap in information.")


def test_flat_brief_on_a_big_day_is_a_violation():
    why = mb.contradicts_the_day(LIVE_QWEN_FLAT, LIVE_SHAPE)
    assert why and "5.3%" in why
    assert any(v.startswith("contradicts the data")
               for v in mb.validate_brief(LIVE_QWEN_FLAT, LIVE_SHAPE)["violations"])


def test_flat_brief_on_a_quiet_day_is_fine():
    quiet = dict(LIVE_SHAPE, btc={"usd": 83423, "usd_24h_change": 0.3},
                 data={"market_cap_change_percentage_24h_usd": -0.6})
    assert mb.contradicts_the_day(LIVE_QWEN_FLAT, quiet) is None


def test_no_24h_data_means_no_judgement():
    assert mb.contradicts_the_day(LIVE_QWEN_FLAT, {"btc_price": 1}) is None


def test_the_corrected_template_does_not_trip_its_own_check():
    assert mb.contradicts_the_day(_generate_template_brief(dict(LIVE_SHAPE)), LIVE_SHAPE) is None


def test_serve_path_falls_back_when_the_cached_brief_contradicts_its_snapshot(monkeypatch):
    import asyncio, time
    from src.api.routers import macro

    cached = {"brief": LIVE_QWEN_FLAT * 2, "market_data": LIVE_SHAPE, "source": "mac_mini",
              "model": "qwen", "received_at": int(time.time()) - 60}

    async def fake_get(key):
        return cached if key == macro._REDIS_KEY else None

    async def fake_set(*a, **k):
        return True

    async def fake_pulse():
        return dict(LIVE_SHAPE)

    monkeypatch.setattr(macro, "redis_get_key", fake_get)
    monkeypatch.setattr(macro, "redis_set_key", fake_set)
    import src.data.market.data_layer as dl
    monkeypatch.setattr(dl, "get_macro_pulse", fake_pulse)

    class R:
        headers = {}
    out = asyncio.run(macro.get_macro_brief(R()))
    assert out["model"] == "template", out.get("model")
    assert "quiet equilibrium" not in out["brief"]


def test_a_brief_from_an_empty_snapshot_is_rejected():
    """09-14 → 09-23:空快照占 Mac 简报的 3/45 → 36/47,几乎全部写成「平静」。"""
    v = mb.validate_brief(LIVE_QWEN_FLAT * 2, {})["violations"]
    assert any(x.startswith("written without measured data") for x in v)
    assert not any(x.startswith("written without measured data")
                   for x in mb.validate_brief(LIVE_QWEN_FLAT * 2, LIVE_SHAPE)["violations"])


def test_serve_path_falls_back_when_the_cached_brief_had_no_data(monkeypatch):
    import asyncio, time
    from src.api.routers import macro
    cached = {"brief": "A calm and orderly session. " * 30, "market_data": {},
              "source": "mac_mini", "model": "qwen", "received_at": int(time.time()) - 60}

    async def fake_get(key):
        return cached if key == macro._REDIS_KEY else None

    async def fake_set(*a, **k):
        return True

    async def fake_pulse():
        return dict(LIVE_SHAPE)

    monkeypatch.setattr(macro, "redis_get_key", fake_get)
    monkeypatch.setattr(macro, "redis_set_key", fake_set)
    import src.data.market.data_layer as dl
    monkeypatch.setattr(dl, "get_macro_pulse", fake_pulse)

    class R:
        headers = {}
    assert asyncio.run(macro.get_macro_brief(R()))["model"] == "template"
