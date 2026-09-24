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
