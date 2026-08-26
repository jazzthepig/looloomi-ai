"""The macro regime must survive the trip from the Mac push to the signal feed.

S-242 (2026-08-26). `/api/v1/signals` reported "17 assets pass CIS ≥58 in UNKNOWN
regime" while `/api/v1/cis/universe` reported Tightening at 0.85 confidence, from
the same push, seconds apart. Three separate defects stacked:

  1. `/internal/cis-scores` normalises the payload into BOTH `macro` and a
     top-level `macro_regime` (the contract even lists `macro_regime` under
     `recommended_top_level`) — then wrote only `macro` into the Redis blob.
  2. The signal feed read the top-level key that was never written, so its
     `if regime:` guard dropped the entire regime signal. A HIGH-importance
     macro signal was missing from the feed and nothing reported its absence.
  3. The CIS gate is regime-keyed UPPER_SNAKE (`TIGHTENING → 52`) and fell to
     its 58 default. 20 assets reported passing instead of 27 — NVDA, INJ, LDO,
     SLV, TLT, SHY and GOOGL were shown failing a gate they clear.

Defect 3 is why this is not cosmetic: a missing label silently moved a
positioning threshold. Note also that fixing (1) alone would not have been
enough — the engine sends `Tightening`, and a raw title-case label misses the
UPPER_SNAKE lookup and lands on exactly the same fallback.

These tests pin the contract at both ends: the receiver writes a canonical
top-level regime, and the feed resolves one from any shape the blob has carried.
"""

import inspect
import re
import sys
from pathlib import Path

import pytest

# market.py imports `data.market.data_layer` (not `src.data...`), matching the
# dual sys.path insert in src/api/main.py. conftest only adds PROJECT_ROOT, so
# add src/ here rather than changing the import style of a production router.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from src.api.routers.market import _cache_regime


# ── The feed's resolver ──────────────────────────────────────────────────────

def test_resolves_regime_from_the_nested_macro_dict():
    """The shape every blob written before S-242 actually has on disk."""
    assert _cache_regime({"macro": {"regime": "Tightening"}}) == "TIGHTENING"


def test_resolves_regime_from_the_top_level_key():
    """The shape the receiver writes now, and the contract documented all along."""
    assert _cache_regime({"macro_regime": "TIGHTENING"}) == "TIGHTENING"


@pytest.mark.parametrize("raw", ["Tightening", "tightening", "TIGHTENING"])
def test_canonicalises_case_and_separators(raw):
    """`Tightening` from the engine must hit an UPPER_SNAKE threshold table.

    Reading the right key but not canonicalising reproduces the same fallback,
    one layer down and harder to see.
    """
    assert _cache_regime({"macro": {"regime": raw}}) == "TIGHTENING"


def test_risk_off_variants_collapse_to_one_regime():
    assert _cache_regime({"macro_regime": "Risk-Off"}) == "RISK_OFF"
    assert _cache_regime({"macro_regime": "risk off"}) == "RISK_OFF"


@pytest.mark.parametrize(
    "blob",
    [None, {}, {"macro": {}}, {"macro_regime": None}, {"macro_regime": ""}],
    ids=["no-cache", "empty", "empty-macro", "null-label", "blank-label"],
)
def test_unmeasured_returns_none_not_a_plausible_regime(blob):
    """Unmeasured is None. It is never NEUTRAL and never the string 'UNKNOWN'.

    Both substitutes are values that look like data: NEUTRAL is a regime the ①
    book sizes off (S-120), and "UNKNOWN" shipped into investor-visible signal
    copy for weeks precisely because it reads like a reading.
    """
    assert _cache_regime(blob) is None


def test_unrecognised_label_is_none_rather_than_neutral():
    assert _cache_regime({"macro_regime": "BANANA"}) is None


# ── The receiver's write ─────────────────────────────────────────────────────

def _receiver_source() -> str:
    from src.api.routers import cis
    return inspect.getsource(cis.receive_local_cis_scores)


def test_receiver_writes_macro_regime_at_the_top_level():
    """The Redis blob must carry the key its consumers read.

    Source-level assertion on purpose: the write goes through Upstash, and a test
    that needs a live Redis is a test that gets skipped in CI — which is how a
    dropped field survives.
    """
    src = _receiver_source()
    cache_block = src[src.index("cache_data = {"):]
    cache_block = cache_block[:cache_block.index("}")]
    assert '"macro_regime"' in cache_block, (
        "cache_data must include a top-level 'macro_regime'. The contract emits "
        "it and the signal feed reads it; writing only 'macro' is S-242."
    )


def test_receiver_canonicalises_the_regime_it_caches():
    src = _receiver_source()
    assert "canonical_regime_strict" in src, (
        "the cached regime must go through canonical_regime_strict — the engine "
        "sends 'Tightening' and every downstream table is keyed UPPER_SNAKE"
    )


# ── The gate ─────────────────────────────────────────────────────────────────

def test_tightening_gate_is_lower_than_the_neutral_default():
    """Pins the fact that made the missing label expensive rather than cosmetic.

    If these two ever converge, the S-242 fallback becomes harmless and this
    test should be deleted deliberately — not left passing by coincidence.
    """
    from src.api.routers import market

    src = inspect.getsource(market.get_signals)
    table = re.search(r"thresholds\s*=\s*\{[^}]*\}", src).group(0)
    assert '"TIGHTENING": 52' in table
    assert re.search(r'thresholds\.get\([^)]*,\s*58\)', src), (
        "the regime-neutral fallback should stay 58; if it changes, the "
        "20-vs-27 divergence this test documents changes with it"
    )


def test_feed_never_names_unknown_as_a_regime():
    """`in UNKNOWN regime` was investor-visible copy. It must not come back.

    Comment lines are stripped first: the fix documents the old string in a
    comment on purpose, and a guard that cannot tell an executable placeholder
    from a note explaining why it was removed would forbid writing that note.
    """
    from src.api.routers import market

    offenders = [
        line.strip()
        for line in inspect.getsource(market.get_signals).splitlines()
        if not line.lstrip().startswith("#")
        and "UNKNOWN" in line
        and "regime" in line.lower()
    ]
    assert not offenders, (
        "no 'UNKNOWN' placeholder in regime handling — unmeasured is None, and "
        "the copy says 'unmeasured' rather than naming a regime we did not "
        f"observe. Offending line(s): {offenders}"
    )


def test_loop_state_gate_canonicalises_before_looking_up():
    """The same defect lived a second life in /api/v1/trading/loop-state.

    That endpoint read `macro.regime` correctly — and still missed, because
    `_REGIME_GATE` is UPPER_SNAKE and the engine sends `Tightening`, so the gate
    took its 50 default where TIGHTENING calls for 52. Reading the right key is
    only half the fix; the other half is the letter case.
    """
    from src.api.routers import trading

    assert trading._REGIME_GATE["TIGHTENING"] == 52
    src = inspect.getsource(trading.get_loop_state)
    assert "canonical_regime_strict" in src, (
        "loop-state must canonicalise the regime before _REGIME_GATE.get()"
    )
    offenders = [
        line.strip() for line in src.splitlines()
        if not line.lstrip().startswith("#")
        and "UNKNOWN" in line and "regime" in line.lower()
    ]
    assert not offenders, f"unmeasured regime is None, not 'UNKNOWN': {offenders}"


def test_loop_state_reports_whether_the_regime_was_measured():
    """A default gate and a chosen gate must be distinguishable by the consumer."""
    from src.api.routers import trading

    assert '"regime_measured"' in inspect.getsource(trading.get_loop_state)


def test_unmeasured_regime_emits_a_visible_notice():
    """Silence is the failure mode that hid this. The else-branch must exist."""
    from src.api.routers import market

    src = inspect.getsource(market.get_signals)
    assert "cis_regime_unmeasured" in src, (
        "when the regime is unmeasured the feed must SAY so; a feed with no "
        "regime entry is indistinguishable from one reporting a calm regime"
    )
