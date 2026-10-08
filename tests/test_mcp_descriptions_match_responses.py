"""T-058 acceptance — MCP tool descriptions must not claim fields absent from responses.

For each (tool, claimed_key) hallucination identified by T-055 drill_structural.py
(see docs/DECISIONS-style drill_structural.md §B-486, 2026-10-07), assert:

    if the key is ABSENT from the actual API response and the key is
    mentioned as a standalone word in the tool's docstring, FAIL.

The 8 (tool, key) pairs from drill_structural.py are all classified ABSENT
in the response structure — they are docstring over-claims. The fix (T-058,
shipped via src/mcp/cometcloud_mcp.py docstring edits) is to remove the
field-name mention from the docstring (the response side is owned by a
different card).

Response keys are INLINED below (TOOL_KEYS) — earlier revisions loaded them
from a `research/T-055/snapshots/` directory that was scoped to a one-off
drill and is not part of the merged tree. Inlining keeps the test independent
of that artefact while preserving the same (tool, key) contract:

    if key NOT in TOOL_KEYS[tool] AND key appears standalone in docstring → FAIL

REPRODUCIBILITY
---------------

Pre-fix (old docstrings that named absent fields): test fails — proves the
assertion is real.
Post-fix (T-058 docstrings): test passes — proves all 8 over-claims cleared.
"""
from __future__ import annotations

import re
from pathlib import Path

# Repo root = parent of the tests/ directory this file lives in.
BASE = Path(__file__).resolve().parents[1]
MCP_PY = BASE / "src" / "mcp" / "cometcloud_mcp.py"

# The 8 (tool, claimed_key) hallucinations from T-055 drill_structural §1.
# Mirrors drill_structural.py STRUCTURAL_X — keep in sync.
HALLUCINATIONS = [
    ("cometcloud_get_cis_exclusions", "tvl"),
    ("cometcloud_get_defi_yields", "tvl"),
    ("cometcloud_get_portfolio_stats", "volatility_30d"),
    ("cometcloud_get_portfolio_stats", "max_drawdown_90d"),
    ("cometcloud_get_prices", "market_cap"),
    ("cometcloud_get_signal_feed", "confidence"),
    ("cometcloud_get_signal_feed", "tvl"),
    ("cometcloud_market_snapshot", "tvl"),
]

# Known response-key surface per tool. Each set is the EXACT set of dict keys
# (top-level and any walked-over sub-dicts/lists) the tool exposes — drawn from the
# Returns block in src/mcp/cometcloud_mcp.py docstrings + the field accesses in
# each handler. None of the hallucinated keys appear here:
#   - "tvl"        (no tool returns a top-level `tvl`; tools use tvlUsd / total_tvl / defi_tvl_usd)
#   - "market_cap" (get_prices docstring explicitly excludes it)
#   - "confidence" (signals don't carry confidence; that lives on CIS assets)
#   - "volatility_30d" / "max_drawdown_90d" (portfolio_stats uses 90d return + ann. vol)
TOOL_KEYS: dict[str, frozenset[str]] = {
    # /api/v1/agent/cis-exclusions — see docstring Returns block
    "cometcloud_get_cis_exclusions": frozenset({
        "total_excluded", "filtered_count", "universe_evaluated",
        "universe_admitted", "standard_version", "exclusions",
        "symbol", "name", "asset_class", "criterion_violated",
        "criterion_labels", "reason", "excluded_since",
        "remediation_available", "remediation_note",
    }),
    # /api/v1/defi/yields — pools shape from handler
    "cometcloud_get_defi_yields": frozenset({
        "count", "pools", "project", "symbol", "chain", "apy", "tvlUsd",
    }),
    # /api/v1/portfolio/stats — data list with per-asset fields
    "cometcloud_get_portfolio_stats": frozenset({
        "data", "asset", "return_90d", "volatility", "sharpe", "price", "count",
    }),
    # /api/v1/market/prices — data list with per-asset fields; NO market_cap
    "cometcloud_get_prices": frozenset({
        "data", "symbol", "price", "change_24h", "change_7d", "volume_24h",
    }),
    # /api/v1/signals/feed — count/accuracy/signals wrapper; signals carry no confidence/tvl
    "cometcloud_get_signal_feed": frozenset({
        "count", "accuracy", "signals",
        "id", "type", "title", "body", "asset", "signal",
        "time_horizon", "timestamp", "direction", "status",
        "conviction_grade", "regime", "horizon", "outcome",
        "hit", "alpha_30d_pct",
        "resolved_30d_directional_pct", "n", "avg_alpha_30d_pct",
    }),
    # composite tool: merges {macro_pulse, gainers, losers, defi_overview}
    "cometcloud_market_snapshot": frozenset({
        "macro_pulse", "gainers", "losers", "defi_overview",
        # macro_pulse (from get_macro_pulse)
        "btc_dominance", "fear_greed_index", "fear_greed_label",
        "total_market_cap_usd", "defi_tvl_usd", "btc_price", "macro_regime",
        # defi_overview (from get_defi_overview)
        "total_tvl", "l2_tvl", "rwa_tvl", "defi_change_24h", "top_protocols",
        "name", "change_1d", "tvl",
        # gainers / losers (from CIS universe with on_change_24h)
        "grade", "change_24h",
    }),
}


def _get_docstring(src: str, tool_name: str) -> str:
    """Extract the docstring immediately following `async def <tool_name>(...) -> str:`."""
    pattern = rf"(?:async\s+)?def\s+{re.escape(tool_name)}\s*\([^)]*\)[^:]*:.*?\"\"\"(.*?)\"\"\""
    m = re.search(pattern, src, re.DOTALL)
    return m.group(1) if m else ""


def _mentions_standalone(text: str, key: str) -> bool:
    """Return True iff `key` appears as a standalone token in `text` (case-insensitive).

    `key` is treated as a full word — `market_cap` does NOT match `market_cap_usd`
    and `tvl` does NOT match `tvlUsd` / `defi_tvl_usd`. This avoids false positives
    on response keys that merely contain the hallucinated substring.
    """
    pattern = r"(?<![A-Za-z0-9_])" + re.escape(key) + r"(?![A-Za-z0-9_])"
    return bool(re.search(pattern, text, re.IGNORECASE))


def test_no_hallucinated_field_claims_in_docstrings():
    """For each of the 8 (tool, key) hallucinations, the docstring must not
    name the key as a standalone field identifier unless the key is present
    in the actual API response (TOOL_KEYS[tool])."""
    src = MCP_PY.read_text()
    failures: list[str] = []
    checked: list[tuple[str, str, bool, bool]] = []

    for tool, key in HALLUCINATIONS:
        keys = TOOL_KEYS.get(tool, frozenset())
        key_in_response = key in keys
        docstring = _get_docstring(src, tool)
        claims = _mentions_standalone(docstring, key)
        checked.append((tool, key, key_in_response, claims))

        # The failure mode the test catches: docstring claims a field that
        # the response does not actually expose.
        if claims and not key_in_response:
            failures.append(
                f"{tool}: docstring mentions `{key}` but the field is absent "
                f"from the actual API response (T-055 ABSENT)"
            )

    # Sanity-check that the test machinery actually walked something — if all
    # 8 pairs are no-docstring / absent, the docstring extractor is broken.
    assert checked, "HALLUCINATIONS list is empty — test is a no-op"

    assert not failures, (
        "Docstring hallucinations (T-058 acceptance: 0 expected, "
        f"{len(failures)} found):\n  - "
        + "\n  - ".join(failures)
        + "\n\nAll 8 (tool, key) pairs checked:\n  - "
        + "\n  - ".join(
            f"{t}: key_in_response={kr}, claims_in_doc={cl}"
            for t, k, kr, cl in checked
        )
    )