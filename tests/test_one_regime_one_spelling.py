"""One regime per response, one spelling everywhere.

S-243 (2026-08-26), found while unifying the case split left over from S-242.
The live payload did not merely spell the regime two ways — it reported two
DIFFERENT regimes in the same document:

    GET /api/v1/cis/universe
      top-level  macro_regime  ->  "Tightening"
      per-asset  macro_regime  ->  "RISK_ON"   (all 58 assets)

`PortfolioAllocation.jsx` reads the per-asset field; everything else reads the
top-level. So during a Tightening reading the allocation panel told investors
"Risk appetite elevated. Full allocation eligible." The contract normaliser
overlays canonical fields onto a copy of each asset precisely to preserve
display fields, so an engine-stamped per-asset regime rode through untouched.

The case split is the same wound, smaller. `Tightening` on the wire against
UPPER_SNAKE lookup tables meant the components keyed CORRECTLY (PortfolioAllocation,
CISCompare, ShareCard) silently missed to a grey default, while the one keyed
title-case (CISWidget) worked — the codebase looked half-right from either side.

These tests pin three things: the API emits one canonical dialect, no asset may
contradict the response it arrives in, and no regime lookup table in the
frontend is keyed on a dialect the API does not emit.
"""

import inspect
import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from src.api.routers.cis import _unify_regime
from src.data.cis.cis_provider import _CANONICAL_REGIMES


# ── The reconciler ───────────────────────────────────────────────────────────

def test_asset_regimes_are_overwritten_with_the_authoritative_one():
    """The exact live shape: top-level Tightening, every asset stamped RISK_ON."""
    universe = [{"symbol": s, "macro_regime": "RISK_ON"} for s in ("BTC", "ETH", "SOL")]

    canon = _unify_regime(universe, "Tightening")

    assert canon == "TIGHTENING"
    assert {a["macro_regime"] for a in universe} == {"TIGHTENING"}, (
        "no asset may carry a regime that contradicts the response it ships in"
    )


def test_returns_canonical_spelling_for_the_top_level_field():
    assert _unify_regime([], "Tightening") == "TIGHTENING"
    assert _unify_regime([], "Risk-Off") == "RISK_OFF"
    assert _unify_regime([], "risk on") == "RISK_ON"


def test_unmeasured_clears_stale_asset_labels_rather_than_leaving_them():
    """An asset holding yesterday's regime while the response says "unmeasured"
    is the same split, one field over — and it is the harder one to notice,
    because the asset's value looks perfectly plausible on its own."""
    universe = [{"symbol": "BTC", "macro_regime": "RISK_ON"}]

    assert _unify_regime(universe, None) is None
    assert universe[0]["macro_regime"] is None


def test_unrecognised_authoritative_label_does_not_become_neutral():
    universe = [{"symbol": "BTC", "macro_regime": "RISK_ON"}]
    assert _unify_regime(universe, "BANANA") is None
    assert universe[0]["macro_regime"] is None


def test_disagreement_is_logged_at_error_level(caplog):
    """A contradiction is a Mac-lane defect we cannot fix from Railway. Serving a
    coherent answer silently would hide it, so the log has to carry it."""
    universe = [{"symbol": "BTC", "macro_regime": "RISK_ON"}]

    with caplog.at_level("ERROR"):
        _unify_regime(universe, "Tightening")

    assert any("[REGIME]" in r.message or "[REGIME]" in r.getMessage()
               for r in caplog.records), "engine self-contradiction must be logged"


def test_agreement_is_not_logged(caplog):
    """Only contradictions are loud; a case difference alone is routine."""
    universe = [{"symbol": "BTC", "macro_regime": "Tightening"}]

    with caplog.at_level("ERROR"):
        _unify_regime(universe, "TIGHTENING")

    assert not [r for r in caplog.records if "[REGIME]" in r.getMessage()]


def test_tolerates_non_dict_entries():
    universe = [{"symbol": "BTC", "macro_regime": "RISK_ON"}, None, "junk"]
    assert _unify_regime(universe, "Tightening") == "TIGHTENING"


# ── Every response path goes through it ──────────────────────────────────────

def test_every_universe_return_path_unifies_the_regime():
    """merged / railway / degraded / last_known_good — four exits, one contract.

    The degraded and LKG branches are the ones that rot: they are only reached
    when something else is already broken, so a divergence there is invisible
    until the day it matters most.
    """
    from src.api.routers import cis

    src = inspect.getsource(cis)
    body = src[src.index("async def _build_cis_universe"):]
    body = body[:body.index('@router.get("/api/v1/cis/debug/datasources")')]

    # Counted rather than pattern-matched per return statement: the merged path
    # unifies into `_cached_regime` several lines above its dict literal, and the
    # railway path assigns into `result[...]`. A regex over the return sites
    # would pass on shape while missing the thing that matters.
    calls = body.count("_unify_regime(")
    assert calls >= 4, (
        f"expected _unify_regime on all four exits (merged / railway / degraded / "
        f"last_known_good), found {calls}"
    )
    assert "_cached_regime = _unify_regime(merged" in body, "merged path"
    assert '_unify_regime(railway_universe' in body, "railway path"
    assert "_unify_regime(stale_universe" in body, "degraded path"
    assert "_unify_regime(lkg_universe" in body, "last_known_good path"


def test_macro_pulse_canonicalises_before_it_caches():
    """The second public regime surface. It must agree with the first character
    for character — two endpoints, two dialects, is how S-242 started."""
    from src.data.market import data_layer

    src = inspect.getsource(data_layer.get_macro_pulse)
    assert "canonical_regime_strict" in src
    assert re.search(
        r'result\["macro_regime"\]\s*=\s*canonical_regime_strict', src
    ), "macro-pulse must canonicalise its regime on the way out"


# ── The frontend ─────────────────────────────────────────────────────────────

_DASHBOARD = _ROOT / "dashboard" / "src"

# Title-case spellings that must no longer appear as OBJECT KEYS or in
# membership tests. They remain legal as display VALUES ("Tightening" shown to a
# human is fine) — this guard is about lookups, which fail silently.
_TITLE_CASE_KEY = re.compile(
    r'["\']?(Risk-On|Risk-Off|Tightening|Easing|Stagflation|Goldilocks)["\']?\s*:'
)
_TITLE_CASE_IN_LIST = re.compile(
    r'\[\s*["\'](Risk-On|Risk-Off|Tightening|Easing|Stagflation|Goldilocks)["\']'
)


def _regime_lookup_lines(text: str):
    """Yield (lineno, line) for lines that PARTICIPATE in a regime lookup.

    Per-line `if "regime" in line` is not enough, and getting that wrong here
    would have reproduced the bug in the guard: the offending keys live inside

        const REGIME_COLORS = {
          "Tightening": "#f59e0b",     <- no "regime" on this line

    so the naive filter skips exactly the lines that mattered and the test
    passes on the broken file. Track the enclosing block instead.
    """
    depth_of_regime_block = None
    depth = 0
    for i, line in enumerate(text.splitlines(), 1):
        opens_regime_block = re.search(r"(const|let|var)\s+\w*REGIME\w*\s*=\s*\{", line)
        if opens_regime_block and depth_of_regime_block is None:
            depth_of_regime_block = depth
        if depth_of_regime_block is not None or "regime" in line.lower():
            yield i, line
        depth += line.count("{") - line.count("}")
        if depth_of_regime_block is not None and depth <= depth_of_regime_block:
            depth_of_regime_block = None


@pytest.mark.parametrize("pattern,what", [
    (_TITLE_CASE_KEY, "object key"),
    (_TITLE_CASE_IN_LIST, "membership test"),
])
def test_no_frontend_lookup_is_keyed_on_a_dialect_the_api_never_emits(pattern, what):
    """CISWidget was keyed title-case and PortfolioAllocation UPPER_SNAKE.

    Exactly one could be right at a time, and the wrong one produced a grey
    default rather than an error — which is why both survived side by side.
    """
    offenders = []
    for f in _DASHBOARD.rglob("*.jsx"):
        for i, line in _regime_lookup_lines(f.read_text(encoding="utf-8")):
            if pattern.search(line):
                offenders.append(f"{f.relative_to(_ROOT)}:{i}: {line.strip()[:90]}")

    assert not offenders, (
        f"regime {what} keyed title-case; the API emits UPPER_SNAKE:\n  "
        + "\n  ".join(offenders)
    )


def test_the_frontend_guard_actually_catches_the_shape_it_is_guarding():
    """Re-introduce the bug in a fixture and confirm the guard fires.

    Required because the guard's first draft passed on the real broken file —
    it filtered to lines containing "regime", and the offending keys do not.
    A guard that never demonstrated a failure is a guard nobody has tested.
    """
    broken = (
        "const REGIME_COLORS = {\n"
        '  "Risk-On": "#22c55e",\n'
        '  "Tightening": "#f59e0b",\n'
        "};\n"
    )
    hits = [l for _, l in _regime_lookup_lines(broken) if _TITLE_CASE_KEY.search(l)]
    assert len(hits) == 2, f"guard failed to see title-case regime keys: {hits}"

    fixed = 'const REGIME_COLORS = {\n  RISK_ON: "#22c55e",\n  TIGHTENING: "#f59e0b",\n};\n'
    assert not [l for _, l in _regime_lookup_lines(fixed) if _TITLE_CASE_KEY.search(l)]


def test_canonical_regime_set_is_what_the_frontend_colours():
    """If the engine gains a regime, the UI must gain a colour in the same change
    — otherwise the new state renders grey and looks like a bug in the data."""
    colours = (_DASHBOARD / "components" / "CISWidget.jsx").read_text(encoding="utf-8")
    block = colours[colours.index("const REGIME_COLORS"):]
    block = block[:block.index("}")]

    missing = [r for r in _CANONICAL_REGIMES if r not in block]
    assert not missing, f"CISWidget has no colour for canonical regime(s): {missing}"
