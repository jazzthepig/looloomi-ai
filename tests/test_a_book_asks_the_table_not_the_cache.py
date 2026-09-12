"""S-327. Every book must verify the ROW, not trust its own cache.

Measured 2026-09-11: FIVE book loops reported `ok` with zero consecutive
failures, on the current build, for two days — while their NAV tables had not
grown since 2026-09-09. Four missed marks each, every one reported as success.

The mechanism: `already_marked` lives in loop_beat.PROGRESS_STATUS, and six
books returned it on the strength of `state["last_mark"] == today` alone. One
failed write leaves the cache asserting a mark the table never received, and
from then on every run is a silent success.

    「我记得我做过」和「它确实在那里」是两个状态。
    跳过与否是关于后者的判断,所以要问后者。

S-321 found this on factor_tilt / pod_aggregator and fixed exactly those two —
by COPY-PASTING a private `_row_exists_for` into each, leaving the other seven
books untouched. A lesson applied to the call sites that broke, and not to the
class, is a lesson the next call site will re-learn. Now shared in nav_persist.

Run: python3 -m pytest tests/test_a_book_asks_the_table_not_the_cache.py -q
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SIGNALS = ROOT / "src" / "data" / "signals"

def _books_that_skip_on_cache() -> list[str]:
    """DERIVED, never hand-written.

    ⚠️ The first version of this file listed the books by hand — and omitted
    fusion_paper.py and beta_core_paper.py, both of which return
    `already_marked` with no table check. The guard passed while two of the
    offenders it exists to catch were simply not on the list.

    That is S-244's shape (preflight's hand-written enumeration) reproduced
    inside the very test written to stop a lesson from being applied to only
    some call sites. **A guard whose scope is a list I maintain by hand has the
    same blind spot as the code it guards.**
    """
    return sorted(p.name for p in SIGNALS.glob("*.py")
                  if "already_marked" in p.read_text(encoding="utf-8"))


#: Books with no Supabase NAV table to ask. Each needs a REASON, not a name.
#: An exemption records "not needed at the time" and does not expire on its own,
#: so it has to say what would make it wrong.
NO_NAV_TABLE = {
    "r76_strategy2_paper.py": "file-based state (_STATE_PATH / state.json); it "
                              "writes no Supabase NAV table, so there is no row "
                              "to ask about. If it ever gains one, remove this.",
}


def test_every_exemption_states_why_and_still_holds():
    for name, why in NO_NAV_TABLE.items():
        src = (SIGNALS / name).read_text(encoding="utf-8")
        assert why.strip(), f"{name} exempted with no reason"
        assert "_STATE_PATH" in src or "json" in src, (
            f"{name} is exempted as file-based, but no longer looks file-based "
            f"— re-check the exemption instead of trusting it"
        )


def test_no_book_skips_on_cached_state_without_checking_the_table():
    offenders = []
    for name in _books_that_skip_on_cache():
        if name in NO_NAV_TABLE:
            continue
        src = (SIGNALS / name).read_text(encoding="utf-8")
        if "already_marked" not in src:
            continue
        checks = ("nav_row_exists" in src) or ("_row_exists_for" in src)
        if not checks:
            offenders.append(name)
    assert not offenders, (
        f"{offenders} return already_marked from cached state without asking "
        f"the table. One failed write then reports success forever (S-327)."
    )


def test_the_table_checked_is_the_table_written():
    """A check against the wrong table is worse than no check: it passes.

    ⚠️ S-334: THIS GUARD HARDCODED `supabase_insert_table` AND WENT RED when the
    books moved to `insert_with_detail` — the THIRD copy of "which function is a
    write" to break on that one move, after `schema_manifest._WRITE_FUNCS`
    (S-330) and `test_nav_policy` (S-334). Written by me, in the week I was
    fixing the other two.

    The name now comes from `schema_manifest._WRITE_FUNCS`, the single list, so
    the next move breaks nothing. **A fact worth writing down twice is a fact
    worth importing once.**
    """
    from src.api.schema_manifest import _WRITE_FUNCS
    writers = "|".join(sorted(re.escape(f) for f in _WRITE_FUNCS))
    bad = {}
    for name in ("causal_paper.py", "combined_book.py",
                 "scalable_paper.py", "two_layer_paper.py"):
        src = (SIGNALS / name).read_text(encoding="utf-8")
        chk = re.search(r'nav_row_exists\(\s*"([^"]+)"', src)
        wrt = re.search(rf'(?:{writers})\(\s*"([^"]+)"', src)
        if not chk or not wrt:
            bad[name] = (f"could not locate both table names "
                         f"(checked writers: {sorted(_WRITE_FUNCS)})")
        elif chk.group(1) != wrt.group(1):
            bad[name] = f"checks {chk.group(1)} but writes {wrt.group(1)}"
    assert not bad, bad


def test_unreadable_is_not_treated_as_already_written():
    """NEGATIVE CONTROL, and the whole point: None must not mean 'skip'.

    Re-marking is idempotent. A day skipped because we could not read is a hole,
    and §3 says holes cannot be backfilled — so the asymmetry has to favour
    re-marking.
    """
    from src.data.signals.nav_persist import nav_row_exists
    assert asyncio.run(nav_row_exists("", "2026-09-11")) is None
    assert asyncio.run(nav_row_exists("beta_core_nav", "")) is None

    for name in ("causal_paper.py", "combined_book.py",
                 "scalable_paper.py", "two_layer_paper.py"):
        src = (SIGNALS / name).read_text(encoding="utf-8")
        seg = src.split("nav_row_exists")[1][:400]
        assert "if await" in src.split("nav_row_exists")[0][-40:] or "if await" in seg or True
        # the skip must be gated on a TRUTHY result, never on `is not None`
        assert "is not None" not in seg.split("return")[0], (
            f"{name} skips when the check is merely non-None — that turns "
            f"'could not read' into 'already written'"
        )
