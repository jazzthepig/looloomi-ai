"""The macro brief: one prompt, enforced rules, a cadence that matches (S-186/187).

WHY. Asked on 2026-08-20 to "upgrade the macro brief prompt", the first file I
opened was `src/data/market/macro_brief_v2.py` — which had ZERO callers, emitted
Chinese, and had been flagged as dead on 2026-07-08 without being removed. The
prompt actually producing the live brief was in the Mac lane. Upgrading the dead
one would have changed nothing and looked like success.

Two prompts in one repo is not redundancy, it is a coin flip about which one the
next edit lands on. That is the first thing pinned here.

The second: every compliance rule in a prompt is a REQUEST to a 9B local model.
CLAUDE.md #1 (no BUY/SELL vocabulary) and #8 (no internals) are P0s, and a P0
enforced by politely asking a language model is not enforced. Hence
`validate_brief`, and hence a receiver that rejects rather than publishes.

The third: freshness constants that describe a system nobody runs any more. The
brief was regenerated every 6 hours while `_REDIS_TTL` said "briefs are twice
daily" and the CDN header said 10 minutes. Now the CDN window is DERIVED from
the poll interval, because a hand-written 600 sitting next to a 5-minute
requirement is precisely how the CDN quietly becomes the binding constraint.
"""
import pathlib
import re

import pytest

from src.api.contracts import macro_brief as mb
from tests._source import code_only, flat

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── One prompt ───────────────────────────────────────────────────────────────

def test_only_one_macro_brief_prompt_in_the_repo():
    """A second prompt is a coin flip about which one gets upgraded."""
    builders = []
    for path in (ROOT / "src").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        txt = code_only(path.read_text())
        # A prompt builder = a function that returns text instructing a model to
        # write the brief. Matched on the instruction, not on a function name,
        # because the dead one was called `generate_llm_macro_signal`.
        if re.search(r"(?i)write .{0,40}macro brief", txt) and "def " in txt:
            builders.append(str(path.relative_to(ROOT)))
    assert builders == ["src/api/contracts/macro_brief.py"], (
        f"expected exactly one macro-brief prompt, found {builders}. "
        f"src/data/market/macro_brief_v2.py was deleted for this reason — it "
        f"had zero callers for six weeks and was the file an 'upgrade the "
        f"prompt' request landed on first.")


def test_dead_module_stays_dead():
    assert not (ROOT / "src/data/market/macro_brief_v2.py").exists(), (
        "macro_brief_v2.py is deleted; it emitted Chinese into a user-facing "
        "surface and had no importer")


# ── The rules are enforced, not requested ────────────────────────────────────

#: Each sample must trip EXACTLY ONE rule, and the assertion names which.
#:
#: The first version used realistic sentences carrying several violations at
#: once ("Investors should buy BTC here on this attractive entry" trips both
#: `buy` and `attractive entry`). Mutation-testing exposed it: deleting the
#: buy/sell patterns entirely left every test green, because each sample was
#: still caught by its OTHER violation. Over-determined samples measure the
#: validator as a whole and pin none of its parts — exactly the condition where
#: a rule can be dropped and nothing notices.
@pytest.mark.parametrize("bad,expect", [
    ("Investors should buy the panel.",              "buy"),
    ("The desk would sell into this.",               "sell"),
    ("We would accumulate here.",                    "accumulate"),
    ("The desk would reduce exposure.",              "reduce"),
    ("This marks an attractive entry.",              "attractive entry"),
    ("Bitcoin is likely to firm from here.",         "is likely to"),
    ("We expect dominance to hold.",                 "we expect"),
    ("Dominance is poised to climb.",                "poised to"),
    ("Conditions will likely persist.",              "will likely"),
    ("The move continues in the coming weeks.",      "in the coming weeks"),
    ("Our Railway deployment refreshed the panel.",  "railway"),
    ("The LLM refreshed the panel.",                 "llm"),
    ("Supabase holds the panel history.",            "supabase"),
])
def test_each_rule_is_independently_enforced(bad, expect):
    padded = bad + " " + ("Conditions remain unchanged across the panel. " * 16)
    r = mb.validate_brief(padded)
    assert not r["ok"], f"should have been refused: {bad!r}"
    joined = " ".join(r["violations"]).lower()
    assert expect.lower() in joined, (
        f"refused, but not for the expected reason. Wanted {expect!r}, got "
        f"{r['violations']}. A sample that trips a different rule cannot pin "
        f"the rule it was written for.")


def test_a_clean_brief_passes():
    """Over-blocking is its own failure: a validator that refuses good briefs
    gets switched off, and then nothing is validated."""
    clean = (
        "The tape is quiet. Bitcoin trades at $72,279, little changed over the "
        "session, and total market capitalisation holds at $2.45T. Dominance at "
        "58.73% leaves capital concentrated in the benchmark rather than rotating "
        "outward. Nothing in the panel moved beyond its reporting threshold. "
        "Positioning across the majors reads NEUTRAL. Grades cluster in the B "
        "band, which is the scoring narrowing as it does under a tightening "
        "regime rather than a view about direction; relative ranking still "
        "separates the panel. The condition most worth watching is dominance. "
        "While it holds above the current level, capital is not rotating, and "
        "the compression in grades persists as a mechanical consequence.")
    r = mb.validate_brief(clean)
    assert r["ok"], f"clean brief refused: {r['violations']}"


def test_positioning_enum_survives_the_validator():
    """The enum must NOT be caught by the banned-term sweep."""
    for term in ("STRONG OUTPERFORM", "OUTPERFORM", "NEUTRAL",
                 "UNDERPERFORM", "UNDERWEIGHT"):
        body = (f"Positioning reads {term} across the panel. " * 20)
        r = mb.validate_brief(body)
        assert r["ok"], f"compliance enum {term!r} was refused: {r['violations']}"


def test_receiver_rejects_rather_than_publishes():
    src = code_only((ROOT / "src/api/routers/macro.py").read_text())
    recv = src.split("async def receive_macro_brief")[1].split("\nasync def ")[0]
    assert "validate_brief" in recv, "the receiver must validate before publishing"
    v_at = recv.find("validate_brief(")
    w_at = recv.find("redis_set_key(")
    assert 0 <= v_at < w_at, "validation must run BEFORE the Redis write"
    assert "422" in recv, (
        "a failing brief must be refused. Unlike the cis_push receiver (S-178, "
        "echoes and never rejects) there is no ambiguity here about which side "
        "is right — CLAUDE.md #1 is a P0.")


# ── Prompt content ───────────────────────────────────────────────────────────

def test_absent_inputs_are_named_absent_and_never_narrated():
    """I1 (NaN-honesty) in prose form: unmeasured must not become a sentence."""
    p = mb.build_prompt({"macro_regime": "Tightening", "btc_price": 72279,
                         "defi_tvl_usd": None, "fear_greed_index": None})
    assert "NOT MEASURED" in p
    assert "DeFi TVL" in p.split("NOT MEASURED")[1].split("WRITE:")[0]
    assert "Fear & Greed" in p.split("NOT MEASURED")[1].split("WRITE:")[0]
    # And absent values must never appear as a measured line.
    measured = p.split("MEASURED DATA")[1].split("NOT MEASURED")[0]
    assert "—" not in measured and "None" not in measured, (
        "an unmeasured reading reached the model dressed as a measured one")


def test_prompt_forbids_inventing_numbers():
    p = mb.build_prompt({"macro_regime": "Tightening", "btc_price": 72279})
    assert "Use ONLY the numbers given above" in p
    assert "no advisory licence" in p.lower() or "NO FORWARD-LOOKING" in p


def test_prompt_carries_the_regime_doctrine():
    """CLAUDE.md: defensive regimes compress grades BY DESIGN. Without this the
    brief reads a mechanical narrowing as a bearish opinion."""
    p = mb.build_prompt({"macro_regime": "Tightening", "btc_price": 72279})
    assert "compresses grades by design" in flat(p)


def test_prompt_is_told_what_moved_not_just_where_things_are():
    prev = {"btc_price": 71848, "macro_regime": "Tightening"}
    cur = {"btc_price": 71848 * 1.006, "macro_regime": "Tightening"}
    p = mb.build_prompt(cur, prev, why="BTC 0.6%")
    assert "MOVEMENT since" in p and "+0.60%" in p
    assert "asked to rewrite because" in p


def test_zero_deltas_are_not_listed_as_movement():
    """The first draft emitted '+0.00% since last brief' under a heading saying
    MOVEMENT — the prompt contradicting itself where the model is told to anchor."""
    same = {"btc_price": 72279, "total_market_cap_usd": 2.45e12,
            "macro_regime": "Tightening"}
    p = mb.build_prompt(dict(same), dict(same))
    assert "+0.00%" not in p and "-0.00%" not in p
    assert "the tape is flat" in p, (
        "a flat tape must be stated, not omitted — an absent section reads as "
        "'not provided', which is a different fact")


# ── Cadence ──────────────────────────────────────────────────────────────────

def test_cdn_window_cannot_exceed_the_poll_interval():
    """Otherwise the CDN is the binding constraint and 5 minutes is really 10."""
    from src.api.routers import macro
    assert macro._BRIEF_MAX_AGE <= mb.POLL_INTERVAL_S, (
        f"max-age={macro._BRIEF_MAX_AGE}s exceeds the {mb.POLL_INTERVAL_S}s poll "
        f"interval — freshness is capped by the cache, not by the pipeline")
    assert macro._BRIEF_SWR <= macro._BRIEF_MAX_AGE, (
        "a stale copy must not outlive the fresh one (S-183)")


def test_cache_header_is_derived_not_restated():
    src = code_only((ROOT / "src/api/routers/macro.py").read_text())
    assert "_BRIEF_MAX_AGE" in src and "max-age=600" not in src, (
        "the header must be derived from the poll interval; a hand-written 600 "
        "beside a 5-minute requirement is how they drift apart")


def test_gate_regenerates_on_material_change_only():
    prev = {"macro_regime": "Tightening", "btc_price": 71848,
            "btc_dominance": 58.73, "total_market_cap_usd": 2.45e12,
            "fear_greed_index": 62}

    do, why = mb.should_regenerate(dict(prev), prev, 360)
    assert not do, f"flat tape should not spend a model call: {why}"

    do, _ = mb.should_regenerate({**prev, "btc_price": 71848 * 1.006}, prev, 360)
    assert do, "a 0.6% BTC move is above the 0.5% threshold"

    do, _ = mb.should_regenerate({**prev, "btc_price": 71848 * 1.002}, prev, 360)
    assert not do, "a 0.2% BTC move is below threshold — that is sampling, not news"

    do, why = mb.should_regenerate({**prev, "macro_regime": "Risk-Off"}, prev, 360)
    assert do and "Risk-Off" in why, "a regime change is the headline fact"

    do, _ = mb.should_regenerate({**prev, "fear_greed_index": 48}, prev, 360)
    assert do, "Fear/Greed crossing Greed→Neutral is a band change"

    do, _ = mb.should_regenerate({**prev, "fear_greed_index": 58}, prev, 360)
    assert not do, "62→58 stays inside Greed; the value moved, the band did not"


def test_gate_has_a_floor_and_a_ceiling():
    prev = {"macro_regime": "Tightening", "btc_price": 71848}

    do, why = mb.should_regenerate({**prev, "btc_price": 71848 * 1.05}, prev, 120)
    assert not do and "floor" in why, (
        "a violent move inside the floor must still wait — the Mac also runs the "
        "T1 CIS engine and cannot be starved by one volatile hour")

    do, why = mb.should_regenerate(dict(prev), prev, 1860)
    assert do and "ceiling" in why, (
        "prose must never sit past the ceiling even on a dead tape: a brief that "
        "never regenerates is indistinguishable from a pipeline that has died")


def test_first_ever_brief_generates():
    do, why = mb.should_regenerate({"btc_price": 1}, None, 0)
    assert do and "no brief" in why


def test_prompt_version_is_declared_and_echoed():
    assert re.fullmatch(r"mb-\d+", mb.PROMPT_VERSION)
    recv = code_only((ROOT / "src/api/routers/macro.py").read_text())
    assert "prompt_version" in recv, (
        "the Mac must report which prompt built the brief, or the two codebases "
        "drift with nowhere for the drift to show (cis_push SCHEMA_VERSION pattern)")


# ── Review of Minimax's Mac-side plan (2026-08-20) ───────────────────────────

def test_top_assets_are_crypto_only():
    """`/api/v1/cis/top` is canonical and correctly includes TradFi — measured
    live, three of the top eight were US equities (XLF #1, NVDA #4, MSFT #6).
    But this prompt opens 'a read of the CRYPTO market' and its whole measured
    block is crypto. Handing the model XLF beside BTC dominance either wastes
    the row or produces a paragraph about financials in a crypto brief."""
    items = [
        {"symbol": "XLF",  "asset_class": "US Equity",      "cis_score": 68.7},
        {"symbol": "LINK", "asset_class": "Infrastructure", "cis_score": 67.7},
        {"symbol": "NVDA", "asset_class": "US Equity",      "cis_score": 67.4},
        {"symbol": "AAVE", "asset_class": "DeFi",           "cis_score": 67.7},
        {"symbol": "MSFT", "asset_class": "US Equity",      "cis_score": 65.2},
        {"symbol": "ETH",  "asset_class": "L1",             "cis_score": 64.1},
    ]
    got = [a["symbol"] for a in mb.select_top_assets(items)]
    assert got == ["LINK", "AAVE", "ETH"], got
    assert mb.TOP_ASSET_FETCH > mb.TOP_ASSET_SHOW, (
        "over-fetch then filter — asking for exactly 8 and dropping 3 leaves 5")


def test_health_fails_on_a_stale_brief_not_just_a_missing_one():
    """The Mac loop's own MAX_BRIEF_AGE_S ceiling cannot fire when the loop is
    what died. Detection must live on the other side of the wire."""
    src = code_only((ROOT / "src/api/health.py").read_text())
    block = src.split('"macro_brief"')[0][-2000:] + src.split('"macro_brief"')[1][:2000]
    assert "MAX_BRIEF_AGE_S" in block, (
        "the freshness limit must derive from the generator's own ceiling, not "
        "be restated — restating is how two numbers drift apart")
    assert "received_at" in block, "must compare against the arrival time"
    assert "STALE" in src, "a stale brief must report as stale, not as present"
