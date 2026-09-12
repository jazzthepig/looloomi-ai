"""A NAV curve with one distinct value is not a track record (S-336).

WHAT WAS MEASURED, 2026-09-12, on live production data:

    GET /api/v1/signals/fusion-paper
    days: 26 · inception 2026-08-15 · latest 2026-09-09 · validated: false

    nav                    distinct = 1   [0.9995]
    daily_return           distinct = 1   [-0.0005]
    gross                  distinct = 1   [0.6667]
    n_positions            distinct = 1   [18]
    cost                   distinct = 1   [0.0005]
    fill_ratio_overall     distinct = 1   [0.9259]
    detector_fired         distinct = 1   [True]
    top_longs              distinct = 23

Twenty-six marks of a market-neutral book across twenty-six days of crypto, and
every quantity that constitutes the record is one number. `daily_return` equals
`-cost` exactly, every day — market P&L identically zero. NAV does not compound:
0.9995 on the first mark and on the twenty-sixth, where -5bps/day for 26 days
would be 0.9871.

Only the WEIGHTS varied, which is the tell: live data was flowing into `w_tgt`
while `w_held` came back empty, so the P&L loop never executed and an empty
accumulation was written as a flat day. S-194, in the one book that never called
`mark_coverage.weighted_mark` — the function built to refuse exactly this.

WHY A SEPARATE GUARD, rather than trusting the fix. `_load_state`'s own docstring
says: "The 5 identical marks at NAV=0.9995 (S-176) were the result of this
function returning {}". **Same book, same number, already diagnosed.** The remedy
chosen then was a Supabase fallback for the state read — which makes the state
read less LIKELY to fail and does nothing about what the book records when it
does. The failure recurred and ran 5 → 26 marks unnoticed.

    A remedy that lowers the probability of a failure, without changing what the
    system reports when it happens, buys time and no information.

So this guard watches the OUTPUT, not the cause. Whatever makes a curve freeze —
lost state, a dead price feed, a constant returned by a stub — a record that does
not move is not a record, and the product is a verifiable forward record.

⚠️ AND IT NEARLY CERTIFIED ITSELF. `validated` flips true at
VALIDATION_MIN_DAYS = 60. At mark 60 this curve would have reported
`validated: true` on sixty identical rows.
"""
from __future__ import annotations

import ast
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

#: Columns whose variation IS the record. A frozen one of these is the defect.
#: `top_longs` / `note` / `capacity_status` are excluded on purpose — a book may
#: legitimately hold a stable roster or sit at one capacity band for weeks.
_RECORD_COLUMNS = ("nav", "daily_return", "price_pnl", "realized_pnl",
                   "unrealized_pnl", "excess_return", "benchmark_nav")

#: Below this many marks, one distinct value proves nothing — a young book can
#: honestly be flat for a few days. 5 is the same floor `get_curve` uses before
#: it will compute a Sharpe.
_MIN_MARKS = 5


def frozen_record_columns(rows: list[dict], *, min_marks: int = _MIN_MARKS) -> list[str]:
    """Which record-bearing columns never change across `rows`?

    Pure and offline so it can be unit-tested here AND run against live curve
    JSON by the ops console. Returns [] for a curve too short to judge — an
    unknown is reported as an unknown, never as health.
    """
    if len(rows) < min_marks:
        return []
    frozen = []
    for col in _RECORD_COLUMNS:
        present = [r[col] for r in rows if isinstance(r, dict) and r.get(col) is not None]
        if len(present) >= min_marks and len({repr(v) for v in present}) == 1:
            frozen.append(col)
    return frozen


def _claims_positions(row: dict) -> bool:
    """Does this row assert the book was HOLDING something that day?"""
    n = row.get("n_positions")
    g = row.get("gross")
    return bool((isinstance(n, (int, float)) and n > 0)
                or (isinstance(g, (int, float)) and g > 0))


def curve_verdict(rows: list[dict], *, min_marks: int = _MIN_MARKS) -> tuple[str, str]:
    """(verdict, reason) — `moves` / `flat_by_declaration` / `fabricated` / `unknown`.

    ⚠️ WHY THIS EXISTS AND `frozen_record_columns` IS NOT ENOUGH. Run against
    live data on 2026-09-12, the frozen-column detector flagged TWO books:

        fusion_paper    26 marks · nav 0.9995 · n_positions 18 · gross 0.6667
        two_layer_paper 28 marks · nav 1.0000 · n_positions None · gross 0
                                 · book_state "core_dead" · positions "FLAT"

    Only the first is a defect. **A book that genuinely holds nothing HAS a flat
    curve, and that is arithmetic, not a lie** — two_layer says `core_dead` and
    `FLAT` on every row, so a reader can see exactly why it did not move.

    Flagging it would have been a false positive on the one book that was being
    honest, and **a guard that fires on honest data gets muted** — after which it
    also occupies the slot a working guard would have taken.

    The separating fact is the CONTRADICTION, not the flatness: fusion's rows
    assert 18 positions at 0.667 gross and simultaneously report exactly zero
    market P&L for twenty-six consecutive days. Those two claims cannot both be
    true. two_layer asserts nothing and reports nothing.

    This is the S-326 ①/② split once more — "holds nothing by design" versus
    "does not know what it holds" — arriving this time inside my own detector.
    """
    if len(rows) < min_marks:
        return "unknown", (f"{len(rows)} marks is below the {min_marks} needed to "
                           "judge; a young book can honestly be flat")
    frozen = frozen_record_columns(rows, min_marks=min_marks)
    if not frozen:
        return "moves", "the record varies"
    holding = [r for r in rows if isinstance(r, dict) and _claims_positions(r)]
    if not holding:
        return "flat_by_declaration", (
            "the curve is flat and every row declares an empty book "
            "(n_positions/gross absent or zero) — holding nothing times any "
            "market is zero, which is arithmetic")
    return "fabricated", (
        f"{len(holding)}/{len(rows)} rows claim an open book (n_positions/gross > 0) "
        f"while {frozen} never move. A held book cannot post identical returns "
        "every day; an empty accumulation is being recorded as a flat day "
        "(S-194/S-176/S-336)")


def test_it_flags_the_real_fusion_curve() -> None:
    """The exact shape pulled from production on 2026-09-12."""
    rows = [{"mark_date": f"2026-08-{15 + i:02d}", "nav": 0.9995,
             "daily_return": -0.0005, "gross": 0.6667, "n_positions": 18,
             "cost": 0.0005, "top_longs": f"BTC:+0.0{i}"} for i in range(26)]
    frozen = frozen_record_columns(rows)
    assert "nav" in frozen and "daily_return" in frozen, frozen
    verdict, why = curve_verdict(rows)
    assert verdict == "fabricated", (verdict, why)


def test_it_does_not_accuse_a_book_that_declares_an_empty_position() -> None:
    """two_layer, live 2026-09-12: 28 marks at NAV 1.0, book_state core_dead.

    THE FALSE POSITIVE THIS PREVENTS. The first version of this guard flagged
    this curve identically to fusion's. It is not the same thing: every row
    declares an empty book, so a flat curve is the honest consequence. Flagging
    it would have accused the one book that was telling the truth — and a guard
    that fires on honest data is a guard that gets muted.
    """
    rows = [{"mark_date": f"2026-07-{22 + i:02d}", "nav": 1.0, "daily_return": 0.0,
             "gross": 0, "n_positions": None, "book_state": "core_dead",
             "positions": "FLAT"} for i in range(28)]
    assert frozen_record_columns(rows)          # it IS frozen
    verdict, why = curve_verdict(rows)          # and that is not a defect
    assert verdict == "flat_by_declaration", (verdict, why)


def test_it_does_not_flag_a_curve_that_moves() -> None:
    """NEGATIVE CONTROL. A guard that fires on healthy data gets muted, and a
    muted guard also occupies the slot a real one would have taken."""
    nav = 1.0
    rows = []
    for i in range(30):
        r = 0.001 if i % 2 else -0.0007
        nav *= (1 + r)
        rows.append({"mark_date": f"d{i}", "nav": round(nav, 6), "daily_return": r,
                     "n_positions": 18, "gross": 0.67})
    assert frozen_record_columns(rows) == []
    assert curve_verdict(rows)[0] == "moves"


def test_a_short_curve_is_unknown_not_healthy() -> None:
    """Four flat days is a plausible week, not evidence of anything."""
    rows = [{"mark_date": f"d{i}", "nav": 1.0, "daily_return": 0.0} for i in range(4)]
    assert frozen_record_columns(rows) == []


def test_a_nav_that_never_compounds_is_caught_even_if_returns_vary() -> None:
    """The subtler form: returns move, NAV does not — they cannot both be true.

    This is what distinguishes "a quiet market" from "the NAV is being recomputed
    from a fresh 1.0 every day", which is what fusion was doing.
    """
    rows = [{"mark_date": f"d{i}", "nav": 0.9995,
             "daily_return": -0.0005 + i * 1e-5} for i in range(20)]
    assert "nav" in frozen_record_columns(rows)


def test_fusion_refuses_an_empty_book_it_cannot_justify() -> None:
    """The structural half: the fix must be present, not merely intended.

    Asserts on the AST rather than on prose — this file's own docstring names
    `nav_table_has_any_rows`, and a guard that greps source text would match its
    own documentation and pass while the code was missing.
    """
    src = (_ROOT / "src" / "data" / "signals" / "fusion_paper.py").read_text()
    tree = ast.parse(src)
    called = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "nav_table_has_any_rows" in called, (
        "fusion_paper computes P&L over w_held without first asking the TABLE "
        "whether an empty book means inception or lost state. With w_held empty "
        "the accumulation stays 0.0 and is recorded as a flat day — 26 identical "
        "marks, 2026-09-12 (S-194/S-326/S-336)."
    )


def test_the_helper_is_three_valued() -> None:
    """`None` must not collapse into False.

    "I could not check whether this book has history" is not "this book has no
    history", and reading the second for the first resets a live NAV to 1.0 —
    which is the failure being fixed, re-created by its own fix.
    """
    import asyncio

    from src.data.signals.nav_persist import nav_table_has_any_rows
    assert asyncio.run(nav_table_has_any_rows("")) is None


def main() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not isinstance(fn, types.FunctionType):
            continue
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            fails += 1
            print(f"  ✗ {name}\n    {e}")
    print(f"\n{'✅' if not fails else '🔴'} a curve that never moves is not a record "
          f"— {fails} failing")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
