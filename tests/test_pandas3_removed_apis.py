"""APIs pandas 3 removed — a research helper can kill a book's daily mark (S-332).

Measured 2026-09-12 via /internal/book-dryrun:

    pod_aggregator   TypeError: NDFrame.fillna() got an unexpected keyword
                     argument 'method'

One line — `w5_forensics_external.py:113` — imported by pod_aggregator, r62 AND
r63, so a helper in src/research/validation took out a book's daily mark.

**The sandbox runs pandas 2.3.3, where `fillna(method=)` is merely deprecated
and still works. Production runs 3.x, where it is gone.** Passing locally is not
passing — this only appears when you call it in the real environment, which is
exactly what book-dryrun is for.

Run: python3 -m pytest tests/test_pandas3_removed_apis.py -q
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

#: pattern → what to use instead. Removed in pandas 3, silently deprecated in 2.
REMOVED = {
    r"\.fillna\s*\([^)]{0,150}method\s*=": ".ffill() / .bfill()",
    r"\.append\s*\(\s*(?!.*os\.|.*list|.*\[)": "pd.concat([...])",
}

#: `reindex(..., method="ffill")` is NOT affected — reindex still takes method.
SAFE_NOTE = "reindex(method=...) is unaffected and must not be flagged"


def _live_py():
    for p in SRC.rglob("*.py"):
        s = str(p)
        if ".claude" in s or "/.venv/" in s or "/venv/" in s:
            continue          # worktree scratch and vendored deps are not ours
        yield p


def test_no_live_module_uses_fillna_method():
    bad = []
    pat = re.compile(r"\.fillna\s*\([^)]{0,150}method\s*=", re.S)
    for p in _live_py():
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for m in pat.finditer(txt):
            line_no = txt[:m.start()].count("\n") + 1
            line = txt.splitlines()[line_no - 1].lstrip()
            if line.startswith("#"):
                continue      # naming it to explain the removal is not using it
            bad.append(f"{p.relative_to(ROOT)}:{line_no}")
    assert not bad, (
        f"pandas 3 removed fillna(method=): {bad}. Use .ffill()/.bfill(). "
        f"These pass on the sandbox's pandas 2.x and raise TypeError in "
        f"production — {SAFE_NOTE}."
    )


def test_the_guard_does_not_flag_reindex_method():
    """NEGATIVE CONTROL. reindex(method=) is legal and widespread here; a guard
    that flagged it would be muted within a day."""
    pat = re.compile(r"\.fillna\s*\([^)]{0,150}method\s*=", re.S)
    assert not pat.search('df.reindex(idx, method="ffill")')
    assert pat.search('s.fillna(method="ffill")')
