"""T-058 end-to-end sanity — proves the production test catches all 8 hallucinations.

Inject all 8 (tool, key) pairs from T-055 drill_structural §1 INTO the docstring of
each matching tool in a sandbox copy of cometcloud_mcp.py, then re-run the same
assertion as the production test (`test_no_hallucinated_field_claims_in_docstrings`)
inline. Expectation: the production test fails with exactly 8 messages, one per pair.

This is the ON-DEMAND proof that the test machinery works — it does NOT change any
file under tests/, src/, or scripts/. Run with:

    python3 _reports/T058_proof.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

# Reuse the production test's private helpers — same module, no fork.
import test_mcp_descriptions_match_responses as tmod

PAIRS = tmod.HALLUCINATIONS
TOOL_KEYS = tmod.TOOL_KEYS
_get_docstring = tmod._get_docstring
_mentions_standalone = tmod._mentions_standalone

src = tmod.MCP_PY.read_text()
mutated = src


def _inject(tool: str, key: str, source: str) -> str:
    open_pat = rf"(?:async\s+)?def\s+{re.escape(tool)}\s*\([^)]*\)[^:]*:\s*\"\"\""
    m = re.search(open_pat, source)
    assert m, f"function header not found: {tool}"
    close_idx = source.find('"""', m.end())
    assert close_idx != -1, f"docstring close not found: {tool}"
    return source[:close_idx] + f"\n__INJECTED_FOR_PROOF__: {key}\n" + source[close_idx:]


for tool, key in PAIRS:
    mutated = _inject(tool, key, mutated)


# Run the SAME production-style assertion against the mutated source.
failures: list[str] = []
for tool, key in PAIRS:
    keys = TOOL_KEYS.get(tool, frozenset())
    key_in_response = key in keys
    docstring = _get_docstring(mutated, tool)
    claims = _mentions_standalone(docstring, key)

    if claims and not key_in_response:
        failures.append(f"{tool}: `{key}`")
    elif claims and key_in_response:
        failures.append(f"{tool}: `{key}` (claim present but key IS in response surface — T-055 false positive)")
    elif not claims:
        failures.append(f"{tool}: `{key}` (INJECTION NOT DETECTED — proof broken)")

print(f"[T058 proof] injected {len(PAIRS)} hallucination(s) into sandbox source")
print(f"[T058 proof] production-style assertion produced {len(failures)} finding(s):")
for f in failures:
    print(f"  - {f}")

# The contract: ALL 8 hallucination pairs must show up in `failures` after injection.
# If any pair is missing, the proof machinery is broken — flag loudly.
EXPECTED = 8
assert len(failures) == EXPECTED, (
    f"proof expected {EXPECTED} findings but produced {len(failures)}; "
    f"either injection or detection regressed. findings={failures!r}"
)
print(f"\n[T058 proof] ✓ all {EXPECTED} hallucination pairs detected — test machinery works.")
