"""A book that cannot price its holdings must refuse to mark (S-194).

Measured 2026-08-23. The equal-weight panel ran +8.84%, +5.23%, +11.03%, −1.43%
across 08-19…08-22. The books recorded:

    beta_core / beta_core_q / causal   0.00% on 3 of 6 marks
    two_layer                          0.00% on 6 of 6
    combined / scalable                stopped marking on 08-20

Every one of them computes daily return as `pnl = 0.0` followed by a
conditional accumulate. When nothing is priceable the loop body never runs and
the value stays 0.0 — in-range, plausible, and identical in the table to a
market that did not move. `beta_core` wrote the same thing as `sum(... if ...)`;
`sum(())` is 0.0 for the same reason.

Nothing caught it because every OTHER field stayed correct: realized_vol_30d
rose 0.302 → 0.586 (nanmean skips bad rows), so the vol scaler correctly cut
gross 1.30 → 1.00 and the row described a working book having a quiet week.
Over 08-18 → 08-23 the panel compounded +23.99% while NAV sat at 1.0470.

One helper for all five books, because the finding was that four books had the
same defect written four different ways.
"""
import pathlib

from src.data.signals.mark_coverage import (
    weighted_mark, DEFAULT_MIN_COVERAGE, MarkResult)
from tests._source import code_only

ROOT = pathlib.Path(__file__).resolve().parents[1]
_W = {"BTC": 0.3, "ETH": 0.3, "SOL": 0.2, "TINY": 0.2}
_MP = {k: 100.0 for k in _W}


def test_a_flat_market_and_a_dead_feed_are_different():
    """The whole finding in one assertion."""
    flat = weighted_mark(_W, {k: 100.0 for k in _W}, _MP, book="t")
    dead = weighted_mark(_W, {}, _MP, book="t")
    assert flat.ok and abs(flat.pnl) < 1e-12
    assert not dead.ok and dead.coverage == 0.0
    assert flat.pnl == dead.pnl, "both are 0.0 — which is exactly why ok must differ"


def test_a_real_move_is_measured():
    r = weighted_mark(_W, {k: 110.0 for k in _W}, _MP, book="t")
    assert r.ok and abs(r.pnl - 0.10) < 1e-9


def test_coverage_is_weighted_not_counted():
    """Dropping one 0.4%-weight name is noise; dropping the 30% BTC leg is not,
    and a name-count floor cannot tell them apart."""
    w = {"BTC": 0.7, "A": 0.1, "B": 0.1, "C": 0.1}
    mp = {k: 100.0 for k in w}
    # 3 of 4 names present, but only 30% of weight → must refuse
    r = weighted_mark(w, {"A": 110.0, "B": 110.0, "C": 110.0}, mp, book="t")
    assert not r.ok, f"30% of weight priced should refuse, got coverage {r.coverage}"
    # 1 of 4 names missing, 90% of weight → must mark
    r2 = weighted_mark(w, {"BTC": 110.0, "A": 110.0, "B": 110.0}, mp, book="t")
    assert r2.ok and r2.coverage == 0.9


def test_zero_and_negative_and_nan_prices_are_unpriceable():
    nan = float("nan")
    for bad in (0.0, -5.0, nan):
        r = weighted_mark({"BTC": 1.0}, {"BTC": bad}, {"BTC": 100.0}, book="t")
        assert not r.ok, f"price {bad!r} must not be treated as valid"
    r = weighted_mark({"BTC": 1.0}, {"BTC": 110.0}, {"BTC": nan}, book="t")
    assert not r.ok, "a NaN mark price must not be treated as valid"


def test_an_empty_book_refuses_rather_than_returning_zero():
    r = weighted_mark({}, {"BTC": 1.0}, {"BTC": 1.0}, book="t")
    assert not r.ok and "no positions" in r.reason


def test_the_skip_payload_names_what_was_missing():
    r = weighted_mark(_W, {}, _MP, book="beta_core")
    d = r.as_skip("beta_core")
    assert d["status"] == "skipped"
    assert d["unpriced"] == 4 and d["priced"] == 0
    assert set(d["unpriced_sample"]) == set(_W), "must name the symbols, not just count"


def test_every_book_uses_the_shared_helper():
    """Four books had the same defect written four different ways. One
    implementation, or the floors drift apart."""
    books = ["beta_core_paper", "combined_book", "causal_paper", "two_layer_paper"]
    for b in books:
        src = code_only((ROOT / f"src/data/signals/{b}.py").read_text())
        assert "weighted_mark(" in src, f"{b} does not use the shared mark guard"


def test_no_book_still_accumulates_from_zero_unguarded():
    """The defect shape: `pnl = 0.0` then a conditional `+=` with no coverage
    check. Matches the construct, not a name — see tests/_source.py."""
    import re
    offenders = []
    for b in ("beta_core_paper", "combined_book", "causal_paper", "two_layer_paper"):
        src = code_only((ROOT / f"src/data/signals/{b}.py").read_text())
        fn = src.split("def mark")[1] if "def mark" in src else src
        # an accumulate into a *_pnl / *_ret guarded only by an `if ... in ...`
        for m in re.finditer(r"^\s*(\w*(?:pnl|ret))\s*\+=", fn, re.M):
            var = m.group(1)
            before = fn[:m.start()]
            if "weighted_mark(" not in before:
                offenders.append(f"{b}: {var} += without a coverage guard above it")
    assert not offenders, "\n  ".join(offenders)


def test_the_floor_is_named_and_not_zero():
    assert 0.5 < DEFAULT_MIN_COVERAGE < 1.0, DEFAULT_MIN_COVERAGE
    assert isinstance(MarkResult(ok=False).pnl, float)
