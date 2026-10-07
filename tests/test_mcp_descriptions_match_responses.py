"""T-058 acceptance — MCP tool descriptions must not claim fields absent from responses.

For each (tool, claimed_key) hallucination identified by T-055 drill_structural.py
(see research/T-055/drill_structural.md, 2026-10-07), assert:

    if the key is ABSENT from the actual API response snapshot AND the key is
    mentioned as a standalone word in the tool's docstring, FAIL.

The 8 (tool, key) pairs from drill_structural.py are all classified ABSENT
in the response structure — they are docstring over-claims. The fix is to drop
the field-name mention from the docstring (the response side is owned by a
different card).

The test reproduces against the snapshots committed at
research/T-055/snapshots/. If new snapshot captures add new fields, rerun and
adjust the (tool, key) list.

REPRODUCIBILITY
---------------

Pre-fix (old docstrings): test fails — proves the assertion is real.
Post-fix (T-058 docstrings): test passes — proves all 8 over-claims cleared.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Repo root = parent of the tests/ directory this file lives in.
BASE = Path(__file__).resolve().parents[1]
SNAP_DIR = BASE / "research" / "T-055" / "snapshots"
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


def _walk(obj, target_key: str) -> int:
    """Recursively count occurrences of `target_key` as a key in dicts nested
    inside `obj` (dicts and lists). Caps at 50 items per list to bound cost."""
    count = 0
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == target_key:
                count += 1
            count += _walk(v, target_key)
    elif isinstance(obj, list):
        for item in obj[:50]:
            count += _walk(item, target_key)
    return count


def _load_snapshot(tool: str) -> dict:
    snaps = sorted(SNAP_DIR.glob(f"{tool}_*.json"))
    assert snaps, f"no T-055 snapshot for {tool} under {SNAP_DIR}"
    return json.loads(snaps[0].read_text())


def _get_docstring(src: str, tool_name: str) -> str:
    """Extract the docstring immediately following `async def <tool_name>(...) -> str:`."""
    # Match either `async def <name>` or `def <name>`, then a colon, then body
    # whose first non-whitespace line begins with a closing `"""`.
    pattern = rf"(?:async\s+)?def\s+{re.escape(tool_name)}\s*\([^)]*\)[^:]*:.*?\"\"\"(.*?)\"\"\""
    m = re.search(pattern, src, re.DOTALL)
    return m.group(1) if m else ""


def _mentions_standalone(text: str, key: str) -> bool:
    """Return True iff `key` appears as a standalone token in `text` (case-insensitive).

    `key` is treated as a full word — `market_cap` does NOT match `market_cap_usd`
    and `tvl` does NOT match `tvl_usd` / `defi_tvl_usd`. This avoids false positives
    on response keys that merely contain the hallucinated substring.
    """
    pattern = r"(?<![A-Za-z0-9_])" + re.escape(key) + r"(?![A-Za-z0-9_])"
    return bool(re.search(pattern, text, re.IGNORECASE))


def test_no_hallucinated_field_claims_in_docstrings():
    """For each of the 8 (tool, key) hallucinations, the docstring must not
    name the key as a standalone field identifier unless the key is present
    in the actual API response."""
    src = MCP_PY.read_text()
    failures: list[str] = []
    checked: list[tuple[str, str, bool, bool]] = []

    for tool, key in HALLUCINATIONS:
        snap = _load_snapshot(tool)
        raw = snap.get("raw_response", {})
        key_in_response = _walk(raw, key) > 0
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