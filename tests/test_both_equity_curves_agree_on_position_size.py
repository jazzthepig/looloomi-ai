"""
Guard: the two curves on the performance page must size a position the same way
(S-176, 2026-08-19).

WHAT WAS ON SCREEN. The Signal Performance page showed, simultaneously:

    CUMULATIVE ALPHA VS BTC/SPY · $100K BASE     −97.45% total
    MAX DRAWDOWN                                 −37.31%

Two numbers on one page describing the same book, disagreeing by 60 points. The
chart curve went from $100k to about $2k; the drawdown stat said the worst
peak-to-trough was 37%.

WHY. `_compute_metrics` builds two series:

    equity_curve         equity *= (1 + POSITION_FRAC * r)      ← fixed
    alpha_equity_series  aeq    *= (1 + a/100)                  ← NOT fixed

The absolute curve had already been corrected, and its comment names the exact
failure it removed: "Compounding each signal at 100% notional made one bad
signal wipe the curve (the -94% artifact)." **That correction was never applied
to the alpha series** — and the frontend explicitly prefers the alpha series and
labels it "the HONEST curve".

So the page rendered the uncorrected curve under the word honest, while quoting
drawdown from the corrected one.

THE DEFECT CLASS, which is the reason this file exists rather than a one-line
patch: the fix was applied to the INSTANCE and not the CLASS. Identical shape to
eleven tables created one at a time (S-166), a probe that checked reads and not
writes (S-174), and a schema_version defaulted in one writer and not its twin
(S-169). **When a correction lands, the question that has to follow is which
other call sites share the flaw** — and nothing was asking it.

ARITHMETIC, so the number is not a guess. 84 resolved signals, average 30-day
alpha −4.09%. Full notional: 0.9591^84 = 0.030 → −97.0%, which is the −97.45%
that was on screen. At POSITION_FRAC = 0.10: 0.99591^84 = 0.708 → about −29%.

⚠️ AND THE SIGNALS ARE STILL NEGATIVE. −29% is not a good number, it is a
correct one. Alpha win rate 26.6%, average 30d alpha −4.09%. This guard protects
the arithmetic, not the strategy; removing an artifact that sat on top of a real
problem must never be filed as having fixed the problem.

Run: python3 -m tests.test_both_equity_curves_agree_on_position_size
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SRC = (_ROOT / "src/api/routers/signals.py").read_text(encoding="utf-8")

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def _code() -> str:
    """Strip comments. This repo has produced seven guards that matched the prose
    explaining a bug rather than the bug (S-167, S-171). Not an eighth."""
    return "\n".join(l for l in _SRC.splitlines() if not l.lstrip().startswith("#"))


def test_position_frac_is_defined_once() -> None:
    code = _code()
    defs = re.findall(r"^\s*POSITION_FRAC\s*=\s*([0-9.]+)", code, re.M)
    check("POSITION_FRAC has exactly one definition", len(defs) == 1,
          f"found {len(defs)} — two curves on one page must not disagree about "
          f"how large a position is, and two constants will drift")
    if defs:
        v = float(defs[0])
        check("and it is a fraction, not full notional", 0 < v < 1,
              f"got {v}: at 1.0 a single bad signal wipes the curve, which is the "
              f"artifact this exists to remove")


def test_every_compounding_loop_applies_it() -> None:
    """The real invariant. Any line that compounds a per-signal return into an
    equity series must scale by POSITION_FRAC."""
    code = _code()
    bad: list[str] = []
    for line in code.splitlines():
        s = line.strip()
        # compounding looks like `x *= (1 + ...)` or `x = x * (1 + ...)`
        if not re.search(r"\*=\s*\(\s*1(\.0)?\s*\+|=\s*\w+\s*\*\s*\(\s*1(\.0)?\s*\+", s):
            continue
        if "POSITION_FRAC" not in s:
            bad.append(s[:100])
    check("no compounding loop sizes at full notional", not bad,
          "\n      ".join(bad) +
          "\n      Each of these multiplies a whole $100k book by one signal's "
          "return. Signals are held CONCURRENTLY — 84 of them over ~85 days at "
          "8.3d average hold is ~10 open at once — so one signal moves a slice.")


def test_the_alpha_series_specifically_is_sized() -> None:
    """Named on its own because it is the one that shipped wrong and the one the
    frontend prefers."""
    code = _code()
    blk = code.split("alpha_equity_series = []")[1][:600] if "alpha_equity_series = []" in code else ""
    check("alpha_equity_series exists", bool(blk), "")
    check("the alpha curve scales by POSITION_FRAC", "POSITION_FRAC" in blk,
          "the frontend prefers this series and calls it 'the HONEST curve'; "
          "unsized, it read −97.45% while max-drawdown on the same page read −37.31%")


def test_the_frontend_still_prefers_the_alpha_series() -> None:
    """If the frontend ever switches to the absolute series, the comment above
    stops being true and this guard is watching the wrong curve."""
    p = _ROOT / "dashboard/src/components/PerformanceDashboard.jsx"
    if not p.is_file():
        check("PerformanceDashboard present", False, f"{p} missing")
        return
    js = p.read_text(encoding="utf-8")
    check("frontend reads alpha_equity_series", "alpha_equity_series" in js,
          "this guard assumes the alpha curve is the rendered one")


def test_the_page_is_still_labelled_as_paper() -> None:
    """−29% or −97%, this is an observational record and not live capital. The
    label is the one thing on the page that must never quietly change."""
    p = _ROOT / "dashboard/src/components/PerformanceDashboard.jsx"
    if not p.is_file():
        return
    js = p.read_text(encoding="utf-8").upper()
    check("page still says PAPER / not live capital",
          "PAPER" in js and ("NOT LIVE" in js or "UNVALIDATED" in js),
          "an observational signal record must not read as a live track record")


if __name__ == "__main__":
    print("── both curves size a position the same way (S-176) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ one POSITION_FRAC · every compounding loop uses it · page still labelled paper")
