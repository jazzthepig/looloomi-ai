"""Smoke tests for r77_multicycle_round3_11yr (Phase C round-3 bridge skeleton).

Five pure-function pins (no panel data required; the sqlite may or may not exist):
  1. Module imports cleanly and exposes the expected names.
  2. DB_PATH matches r97_panel_11yr.DB_PATH (consistency pin — single source of truth).
  3. Frozen weights are inherited unchanged (R46=0.25, R62=0.75, R76=0.30).
  4. Round-3 verdict grammar contains the new strings + the inherited unhashed marker.
  5. Default disclosure has is_11yr_R77 = False (honest until round-3 actually runs).

Each test runs standalone (no pytest) via main() at the bottom.

Lane: Minimax-C skeleton. NOT in preflight yet (panel-dependent).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import src.research.validation.r77_multicycle_round3_11yr as r3
import src.research.validation.r97_panel_11yr as r97
import src.research.validation.r77_multicycle_revalidation as r77


# ── Test 1: module imports + exposes expected names ──────────────────────────
def t_module_imports():
    for name in ("load_r77_panel_11yr",
                 "round3_disclosure_default",
                 "VERDICT_R3_REGIME_CANDIDATE",
                 "VERDICT_R3_INSUFFICIENT_FUNDING",
                 "VERDICT_R3_FROZEN_UNHASHED",
                 "R77_FROZEN_W_R46", "R77_FROZEN_W_R62", "R77_FROZEN_W_R76",
                 "DB_PATH", "MIN_SPAN_DAYS"):
        assert hasattr(r3, name), f"module missing {name}"
    print("  ✓ module exposes load_r77_panel_11yr + verdict grammar + 3 frozen weights")


# ── Test 2: DB_PATH consistency with r97_panel_11yr ──────────────────────────
def t_db_path_consistency():
    assert r3.DB_PATH == r97.DB_PATH, (
        f"r3.DB_PATH ({r3.DB_PATH}) must equal r97.DB_PATH ({r97.DB_PATH}) — "
        f"single source of truth for the 11yr sqlite location"
    )
    assert r3.MIN_SPAN_DAYS == r97.MIN_SPAN_DAYS, (
        f"r3.MIN_SPAN_DAYS ({r3.MIN_SPAN_DAYS}) must equal r97.MIN_SPAN_DAYS "
        f"({r97.MIN_SPAN_DAYS})"
    )
    print(f"  ✓ DB_PATH/MIN_SPAN_DAYS match r97_panel_11yr ({r3.DB_PATH})")


# ── Test 3: frozen weights inherited unchanged from 731d module ───────────────
def t_frozen_weights_inherited():
    assert r3.R77_FROZEN_W_R46 == r77.R77_FROZEN_W_R46 == 0.25, (
        f"w_R46 drift: r3={r3.R77_FROZEN_W_R46} vs r77={r77.R77_FROZEN_W_R46} — "
        f"round-3 must NOT redefine frozen weights"
    )
    assert r3.R77_FROZEN_W_R62 == r77.R77_FROZEN_W_R62 == 0.75
    assert r3.R77_FROZEN_W_R76 == r77.R77_FROZEN_W_R76 == 0.30
    print("  ✓ frozen weights inherited from r77_multicycle_revalidation (no drift)")


# ── Test 4: verdict grammar contains new + inherited strings ──────────────────
def t_verdict_grammar():
    grammar = (r3.VERDICT_R3_REGIME_CANDIDATE,
               r3.VERDICT_R3_INSUFFICIENT_FUNDING,
               r3.VERDICT_R3_FROZEN_UNHASHED)
    assert grammar == ("R77_REGIME_CANDIDATE_ON_11YR",
                       "R77_INSUFFICIENT_FUNDING_ON_11YR",
                       "R77_FROZEN_WEIGHTS_UNHASHED")
    # Inherited marker MUST be identical to the 731d module's marker
    assert r3.VERDICT_R3_FROZEN_UNHASHED == r77.VERDICT_FROZEN_UNHASHED, (
        "unhashed honesty marker must be the same string across 731d and 11yr modules"
    )
    print("  ✓ verdict grammar: 3 new strings + inherited unhashed marker")


# ── Test 5: default disclosure is honest (is_11yr_R77 = False) ───────────────
def t_default_disclosure_honest():
    disc = r3.round3_disclosure_default()
    assert disc["is_11yr_R77"] is False, (
        "default disclosure must say is_11yr_R77=False until round-3 actually clears "
        "the 3-check + M-WO-1 gauntlet on the 11yr panel (Lesson #92)"
    )
    assert disc["is_post_2023_funding_coverage_sleeve"] is True
    assert disc["R46_full_11yr_leg_status"] == "PENDING_ROUND3_RUN"
    assert disc["frozen_weights_unhashed"] is True
    assert "binance_spot@" in disc["panel_source"]
    assert disc["min_span_days"] == 2000
    print("  ✓ default disclosure: is_11yr_R77=False (honest until round-3 clears)")


# ── run all ──────────────────────────────────────────────────────────────────
_TEST_FUNCS = [
    t_module_imports,
    t_db_path_consistency,
    t_frozen_weights_inherited,
    t_verdict_grammar,
    t_default_disclosure_honest,
]


def main() -> int:
    failed = 0
    for fn in _TEST_FUNCS:
        try:
            fn()
        except AssertionError as exc:
            print(f"  ✗ {fn.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"  ✗ {fn.__name__}: {type(exc).__name__}: {exc}")
            failed += 1
    total = len(_TEST_FUNCS)
    passed = total - failed
    print()
    print(f"  {passed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
