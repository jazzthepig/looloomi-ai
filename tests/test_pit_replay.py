"""Guards for the PIT replay harness (S-207).

The property under test is ONE distinction: a day with no position because the
rule declined is not the same event as a day with no position because the machine
could not answer. Every incident this month came from those two being one number.
On the first real run the harness found nine days where the rule could not run —
days that any two-valued report would have shown as "flat".
"""
from __future__ import annotations

import datetime as dt
import sys

from src.research.validation.pit_replay import (
    Decision, DayOutcome, InputUnavailable, ReplayReport, Verdict, replay)
from src.research.validation.rules.r70_rule import (
    MIN_PANEL, SKIP_REGIMES, canonical_regime, r70_decide)

D0 = dt.date(2026, 6, 10)
_fails: list[str] = []


def check(cond: bool, label: str) -> None:
    if not cond:
        _fails.append(label)


def rows(n: int, regime: str = "NEUTRAL", pillar: bool = True):
    return [{"symbol": f"S{i}", "macro_regime": regime,
             **({"pillar_a": float(i)} if pillar else {})} for i in range(n)]


# ── 1. the type refuses to represent an unexplained day ──────────────────────
try:
    DayOutcome(D0, Verdict.BLOCKED, "")
    check(False, "BLOCKED with empty reason was accepted")
except ValueError:
    pass

try:
    DayOutcome(D0, Verdict.FIRED, "ok", n_positions=0)
    check(False, "FIRED with zero positions was accepted")
except ValueError:
    pass

try:
    DayOutcome(D0, Verdict.FLAT, "ok", n_positions=3)
    check(False, "FLAT carrying positions was accepted")
except ValueError:
    pass

# ── 2. a rule that CANNOT run is BLOCKED, never FLAT ─────────────────────────
def raises(_d, _r):
    raise InputUnavailable("feed down")


r = replay([D0], lambda _d: rows(20), raises)
check(r.count(Verdict.BLOCKED) == 1 and r.count(Verdict.FLAT) == 0,
      "InputUnavailable did not produce BLOCKED")

# An unexpected exception is also BLOCKED — a rule that crashes has not decided
# anything, and reporting it as FLAT would credit the pipeline for the silence.
def boom(_d, _r):
    raise KeyError("pillar_a")


check(replay([D0], lambda _d: rows(20), boom).count(Verdict.BLOCKED) == 1,
      "an exception inside the rule was not BLOCKED")

# An empty snapshot is an engineering fact, not a quiet market.
check(replay([D0], lambda _d: [], lambda d, x: Decision({}, "n/a")).count(
    Verdict.BLOCKED) == 1, "empty snapshot was not BLOCKED")

# ── 3. a rule that runs and declines is FLAT, and that is not a failure ──────
r = replay([D0], lambda _d: rows(20), lambda d, x: Decision({}, "declined"))
check(r.count(Verdict.FLAT) == 1 and r.count(Verdict.BLOCKED) == 0,
      "a clean decline was not FLAT")

# ── 4. blocked days leave the fire-rate denominator ──────────────────────────
# Otherwise the metric IMPROVES when the pipeline breaks, which is how a broken
# feed turns into a flattering report.
days = [D0 + dt.timedelta(days=i) for i in range(4)]


def half_blocked(d, _r):
    if d.day % 2:
        raise InputUnavailable("down")
    return Decision({"BTC": 1.0}, "fired")


rep = replay(days, lambda _d: rows(20), half_blocked)
check(rep.count(Verdict.BLOCKED) == 2 and rep.count(Verdict.FIRED) == 2,
      "half-blocked replay miscounted")
check(abs(rep.fire_rate - 1.0) < 1e-9,
      "fire_rate did not exclude blocked days from its denominator")

# ── 5. the report refuses to carry a return ──────────────────────────────────
# A number present in a payload gets quoted. The replay's return is in-sample.
s = rep.summary()
check(s.get("return_pct") is None, "summary() carried a return number")
check(isinstance(s.get("return_omitted_because"), str) and s["return_omitted_because"],
      "summary() omitted a return without saying why")
check("blocking_reasons" in s and "flat_reasons" in s,
      "summary() lost the reason census")

# ── 6. regime spelling collapses to one state (S-209) ────────────────────────
variants = ["Risk-Off", "risk off", "RISK_OFF", "risk-off"]
check(len({canonical_regime(v) for v in variants}) == 1,
      "regime spellings did not collapse to one canonical state")
check(canonical_regime("") is None and canonical_regime(None) is None,
      "blank regime did not map to None")
# The skip set must hold canonical forms only — enumerating variants is the
# workaround that lets a new spelling through, which means trading a regime the
# config says to skip.
check(all(v == canonical_regime(v) for v in SKIP_REGIMES),
      "SKIP_REGIMES contains a non-canonical spelling")

# ── 7. R70: the gate is FLAT, a thin panel is BLOCKED ────────────────────────
for rg in SKIP_REGIMES:
    d = r70_decide(D0, rows(30, regime=rg))
    check(not d.positions, f"R70 opened positions in {rg}")

d = r70_decide(dt.date(2026, 6, 12), rows(30, regime="NEUTRAL"))
check(bool(d.positions), "R70 never fires even on a runnable non-skip cadence day") \
    if dt.date(2026, 6, 12).toordinal() % 3 == 0 else None

try:
    r70_decide(D0, rows(MIN_PANEL - 1, regime="NEUTRAL"))
    check(False, "R70 accepted a panel below MIN_PANEL")
except InputUnavailable:
    pass

try:
    r70_decide(D0, rows(30, regime="NEUTRAL", pillar=False))
    check(False, "R70 ranked a panel with no pillar values")
except InputUnavailable:
    pass

# ── 8. the panel check precedes the regime gate ──────────────────────────────
# THE FLATTERING-READING GUARD. A day with no usable data AND a skip regime must
# report BLOCKED. Reporting it as a clean regime skip credits the rule for a day
# our pipeline lost — and 9 of the first 70 replayed days were exactly this
# shape (T2 wrote scores and grades with every pillar NULL).
try:
    r70_decide(D0, rows(30, regime="TIGHTENING", pillar=False))
    check(False, "a dataless skip-regime day was not BLOCKED")
except InputUnavailable:
    pass

# ── 9. the rule cannot reach today's data ────────────────────────────────────
# A replay whose rule can query the network or the clock is not a replay. Checked
# against the module source rather than by trusting the signature.
import inspect

import src.research.validation.rules.r70_rule as _r70
src_txt = inspect.getsource(_r70)
for banned in ("httpx", "requests", "supabase_", "datetime.now", "date.today"):
    check(banned not in src_txt, f"the frozen rule reaches outside its snapshot: {banned}")

if _fails:
    print("✗ pit-replay guards FAILED:")
    for f in _fails:
        print("   ·", f)
    sys.exit(1)
print(f"  ✓ pit replay: blocked≠flat, fire-rate denominator, no return in payload, "
      f"regime canonicalisation, R70 gate-vs-panel ordering ({9 + len(SKIP_REGIMES)} properties)")
