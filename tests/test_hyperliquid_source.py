"""Hyperliquid as a price source, and the date bug it exposes (S-191/S-192).

WHY. Asked whether the portfolio caught the 08-19 rally, our stored CoinGecko
bars said BTC +0.30%, ETH +0.22%, SOL +1.35% — a flat day. Hyperliquid said
+7.15%, +17.57%, +10.84%. Both cannot be right.

They are not. Our `trade_date = 2026-08-19` BTC row holds 64,686.30; HL's
**08-18** close is 64,696. Ours is a day behind, systematically, on every symbol
and every day checked. The CoinGecko writer stamps rows with the WRITE date
instead of the bar date, so a loop running at 07:49 on the 20th files
yesterday's close under the 19th.

Consequences: every CoinGecko return series is shifted one day; joining it to
`binance_hist` or `eodhd` splices two date conventions (S-106 on the date axis
rather than the bar axis); and every paper book marking off it marks a day late.

A bar knows when it is. A process writing it does not. Hyperliquid ships the
epoch with the candle, so this class of error cannot recur there — which is one
of three reasons to prefer it, the largest being that it is where we will
actually execute.
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
from tests._source import code_only  # noqa: E402


def test_the_date_comes_from_the_bar_not_the_clock():
    """The single line that separates this collector from the broken one."""
    src = code_only((ROOT / "src/data/market/hyperliquid_collector.py").read_text())
    fn = src.split("async def _fetch_one")[1].split("\nasync def ")[0]

    assert 'k["t"]' in fn, "trade_date must derive from the candle's own epoch"
    m = re.search(r'"trade_date":\s*([^\n]+)', fn)
    assert m, "no trade_date assignment found"
    expr = m.group(1)
    assert "ts" in expr, f"trade_date built from {expr!r} — must use the bar timestamp"
    for forbidden in ("now()", "utcnow", "today()"):
        assert forbidden not in expr, (
            f"trade_date built from the CLOCK ({forbidden}) — that is exactly the "
            f"CoinGecko bug: a row written at 07:49 on the 20th filed under the 19th")


def test_source_label_is_not_mixed_into_the_binance_panel():
    """Bar convention is a property of the source (S-106/S-107), and perp marks
    are not spot closes. Two labels, two conventions, no splice."""
    from src.data.market.hyperliquid_collector import SOURCE
    assert SOURCE == "hyperliquid"
    src = code_only((ROOT / "src/data/market/hyperliquid_collector.py").read_text())
    assert "binance_hist" not in src, (
        "must never write into the Binance panel's label — nine years of that "
        "series are spot bars from one venue")


def test_the_coverage_floor_blocks_the_write():
    """S-190: deep_panel_collector wired its floor into the return value only, so
    a 1-of-262 run still wrote and max(trade_date) then read as current."""
    src = code_only((ROOT / "src/data/market/hyperliquid_collector.py").read_text())
    fn = src.split("async def collect_hyperliquid")[1]
    guard = fn.find("frac < _MIN_OK_FRACTION")
    write = fn.find("await supabase_upsert_table(")
    assert guard > 0 and write > 0
    assert guard < write, "the floor is checked after the write — annotation, not a gate"
    assert "return" in fn[guard:write], "must return before writing, not set a flag"


def test_tradeable_overlap_is_measurable():
    """34% of the research panel is executable on the venue. That number should
    be computable by anyone designing a sleeve, not rediscovered each time."""
    from src.data.market.hyperliquid_collector import tradeable_overlap  # noqa: F401
    src = code_only((ROOT / "src/data/market/hyperliquid_collector.py").read_text())
    fn = src.split("async def tradeable_overlap")[1]
    for key in ("tradeable_pct", "research_only", "untouched_on_venue"):
        assert key in fn, f"overlap report must expose {key}"


def test_the_loop_is_registered():
    """S-175: a collector with no scheduler is a collector that does not run."""
    main = code_only((ROOT / "src/api/main.py").read_text())
    assert "_hyperliquid_loop" in main
    assert "create_task(_hyperliquid_loop())" in main.replace(" ", ""), (
        "the loop must be started, not merely defined")
    loop = main.split("async def _hyperliquid_loop")[1].split("\n@app")[0]
    assert "collect_hyperliquid" in loop


def test_coingecko_writer_is_flagged_for_the_date_bug():
    """S-191 is not fixed here — it is in the CoinGecko write path and touching
    it rewrites history. This test exists so the finding cannot be forgotten
    while the fix is pending; it should be replaced by a real guard once the
    writer is corrected."""
    state = (ROOT / "PROJECT_STATE.md").read_text()
    assert "S-191" in state, (
        "the CoinGecko off-by-one must stay on the first screen until fixed — "
        "every return series from that source is shifted one day")


# ── S-204: the collector throttled itself into refusing to write ─────────────

def test_pacing_stays_inside_the_venue_budget():
    """Concurrency 8 at a 0.15s pause is ~53 req/s. Hyperliquid answered 429 to
    57 of 232 symbols INCLUDING BTC, coverage fell to 56%, the 70% floor fired,
    and the collector refused to write for two days. Every step was correct; the
    collector had caused the condition it then correctly refused through."""
    from src.data.market import hyperliquid_collector as hc
    rate = hc._CONCURRENCY / max(hc._BATCH_PAUSE_S, 1e-9)
    assert rate <= 10, (
        f"~{rate:.0f} req/s — measured 429s above this. A collector that takes "
        f"two minutes and finishes beats one that takes twenty seconds and is "
        f"throttled into silence.")


def test_throttling_and_delisting_are_different_outcomes():
    """A 429 is transient and must be retried; an empty body is a delisting and
    never will be. Collapsing them made a self-inflicted rate limit look like
    45% of the venue disappearing — S-180's miss-vs-error, one layer down."""
    src = code_only((ROOT / "src/data/market/hyperliquid_collector.py").read_text())
    fn = src.split("async def _fetch_one")[1].split("\nasync def ")[0]
    assert "429" in fn and "throttled" in fn, "a 429 must be named as throttling"
    assert "delisted" in fn, "an empty body must be named as a delisting"
    assert "_MAX_RETRIES" in fn, "throttling must be retried"
    # and the retry must NOT cover the delisted path
    delist_line = [l for l in fn.split("\n") if '"delisted"' in l][0]
    assert "return" in delist_line, "a delisting must return immediately, not retry"


def test_the_floor_denominator_excludes_permanent_absences():
    """45 delisted perps are still in the venue's `meta` list. Counting them as
    failures drags a health signal down every run with a permanent fact."""
    src = code_only((ROOT / "src/data/market/hyperliquid_collector.py").read_text())
    fn = src.split("async def collect_hyperliquid")[1]
    assert "reachable" in fn, "the floor must divide by symbols that COULD answer"
    frac_line = [l for l in fn.split("\n") if "frac =" in l][0]
    assert "reachable" in frac_line, (
        f"coverage still divides by the full list: {frac_line.strip()}")


def test_the_report_separates_the_three_outcomes():
    src = code_only((ROOT / "src/data/market/hyperliquid_collector.py").read_text())
    for key in ("symbols_reachable", "symbols_delisted", "symbols_throttled"):
        assert f'"{key}"' in src, f"{key} must be reported — 'failed: 102' is not actionable"
