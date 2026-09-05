"""Paper-trade spec library — Seth/Austin lane.

Re-exports the spec-driven runner surface so callers (Mac-side `book_trader.py`,
`tests/test_spec_runner.py`, future CLI in `paper_trading/spec_runner.py`) can
import from `paper_trading` without reaching into submodules.

Lane note (S-284): `paper_trading/` is the spec library; the older sleeve
prototypes live in `src/research/paper_books/`. Both are Seth/Austin lanes —
see CLAUDE.md source-of-truth table. Until E is decided, this package does not
re-export anything from `paper_books/`.
"""
from __future__ import annotations

from paper_trading.spec_runner import (
    Decision,
    ExternalFeature,
    FAMILIES,
    Leg,
    MAX_PANEL_AGE_DAYS,
    MIN_UNIVERSE_FOR_RANK,
    Panel,
    Spec,
    UnwiredFamily,
    Verdict,
    build_panel,
    decide,
    decide_gated,
    decide_survivors_book,
    exit_due,
    should_run_today,
)

__version__ = "2026.09.04"

__all__ = [
    # version
    "__version__",
    # core types
    "Spec",
    "Panel",
    "Decision",
    "Leg",
    "ExternalFeature",
    "Verdict",
    "UnwiredFamily",
    # constants
    "FAMILIES",
    "MAX_PANEL_AGE_DAYS",
    "MIN_UNIVERSE_FOR_RANK",
    # entry points
    "build_panel",
    "decide",
    "decide_gated",
    "decide_survivors_book",
    "should_run_today",
    "exit_due",
]