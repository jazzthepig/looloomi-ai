"""The IC-weight chain: honest about being empty (S-202).

Jazz saw `cis weight failure` in production. Traced end to end:

    trade_results.realized_return_7d   234 rows, ALL NULL
      → compute_7d_returns finds nothing (CoinGecko path rate-limits, the third
        source is a score proxy the code itself labels METHODOLOGICALLY FLAWED)
      → compute_fitness: usable = []
      → return {"ok": True, "rows": 0}            ← reported SUCCESS
      → log line `[REGIME_FITNESS] daily — ok=True rows=0`
      → cis_regime_fitness: 0 rows
      → IC multiplier cannot load → neutral weights
      → CIS has scored every asset on neutral weights for four months

Inputs were never missing: trade_results held 234 closed fills across 40 symbols
from 06-29 onward, cis_scores held 115,931 rows in the 90-day window. Only the
one column was empty, and `ok=True` made the gap look like a working day.

BACKFILLED 104 rows from ohlcv_daily, same-source only — 20 candidate rows would
have spanned binance_hist→coingecko, and a return computed across two bar
conventions is the S-106 error on a different axis.

AND THEN THE RESULT SAID DO NOT SHIP IT. Deduplicated to one row per
(symbol, day), the samples are 64 observations over SIX days (TIGHTENING) and 23
over ONE day (RISK_ON) — whose five pillar ICs came out identical at −0.017, the
signature of a collapsed cross-section. The old floor, `len(pairs) >= 5`, passes
on five observations from a single day. Turning IC weighting on with that would
tilt CIS on noise, which is worse than neutral: neutral is at least honest about
knowing nothing.
"""
import pathlib

from tests._source import code_only

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_an_empty_fitness_run_is_not_reported_as_ok():
    """T-062 (2026-11-19): the writer moved to
    `src/research/validation/regime_fitness.py` — the old
    `scripts/compute_regime_fitness.py` read `cis_scores` (0 rows) and
    `trade_results` (0 rows), so it computed nothing for four months. The
    guard follows the code that actually runs; the intent is unchanged.

    An empty run is a refusal with a consequence, never `ok=True, rows=0`.
    """
    src = code_only((ROOT / "src/research/validation/regime_fitness.py").read_text())
    fn = src.split("def run(")[1]
    assert '"ok": False' in fn, (
        "rows=0 with ok=True printed as a normal daily run for four months")
    assert "degraded" in fn
    assert "consequence" in fn, (
        "the caller must be told what the empty table CAUSES — that the IC "
        "record has nothing in it — not merely that a number was zero")


def test_the_endpoint_does_not_turn_a_refusal_into_a_success():
    """The endpoint is a thin wrapper now. If it ever builds its own `ok`,
    the degraded shape dies at the boundary and the loop logs `ok` again."""
    src = code_only((ROOT / "src/api/routers/admin.py").read_text())
    fn = src.split("async def trigger_regime_fitness")[1].split("\n@router")[0]
    assert "to_thread" in fn
    assert '"ok": True' not in fn


def test_the_live_writer_keeps_the_day_floor_and_gates_before_the_correlation():
    """The floor that matters is the one in the module the loop calls."""
    import re
    src = code_only((ROOT / "src/research/validation/regime_fitness.py").read_text())
    n = int(re.search(r"MIN_INDEPENDENT_DAYS\s*=\s*(\d+)", src).group(1))
    assert n >= 20, f"floor {n} — measured samples span 6 days and 1 day"
    fn = src.split("def compute_fitness(")[1]
    gate = fn.find("min_days")
    corr_at = fn.find("_pearson")
    assert 0 < gate < corr_at, (
        "the day floor must gate BEFORE the correlation is recorded")


def test_the_sample_floor_counts_days_not_pairs():
    src = code_only((ROOT / "scripts/compute_regime_fitness.py").read_text())
    assert "MIN_INDEPENDENT_DAYS" in src, (
        "the unit of independence is the day: assets co-move, so N names on one "
        "day is closer to one observation than to N")
    fn = src.split("def compute_fitness")[1]
    day_gate = fn.find("MIN_INDEPENDENT_DAYS")
    corr_at = fn.find("pearson") if "pearson" in fn else fn.find("results.append")
    assert 0 < day_gate < corr_at, (
        "the day floor must gate BEFORE the correlation is recorded")


def test_the_day_floor_is_high_enough_to_bite_today():
    """With six days available, the honest output is 'not yet'. A floor set
    below what we have would let the noise through and call it a finding."""
    import re
    src = (ROOT / "scripts/compute_regime_fitness.py").read_text()
    n = int(re.search(r"MIN_INDEPENDENT_DAYS\s*=\s*(\d+)", src).group(1))
    assert n >= 20, f"floor {n} — measured samples span 6 days and 1 day"


def test_a_skipped_pillar_says_why():
    src = code_only((ROOT / "scripts/compute_regime_fitness.py").read_text())
    blk = src.split("MIN_INDEPENDENT_DAYS:")[1][:400]
    assert "SKIPPED" in blk and "independent day" in blk, (
        "a silent `continue` here is how the chain stayed invisible; the skip "
        "must name the pair count AND the day count so the gap is legible")


def test_neutral_weights_are_a_stated_state_not_a_silent_fallback():
    src = code_only((ROOT / "src/data/cis/cis_provider.py").read_text())
    assert "using neutral weights" in src, (
        "the fallback must announce itself — it did, which is the only reason "
        "this was findable at all")
