"""
Guard: the two new forward records cannot silently stop recording (S-173).

WHAT THEY ARE FOR.

  depth_divergence_log        — S-172 measured -1.85% 20d excess (t=-5.23) for
                                depth-up/price-flat, IN SAMPLE. This log tests it
                                forward. Inception 2026-08-18, gate 2026-10-17.
  holder_concentration_history — holder_provider has computed top-10 share and
                                HHI since inception and written them only to a
                                TTL'd Redis map. Its own code says
                                `"chuquan": False,  # Phase 2 (needs timeseries)`.
                                There was no timeseries because nothing stored
                                one, so "diffusion velocity" — the thing
                                ARCHITECTURE.md calls the deepest object — was
                                gated behind a table that did not exist.

WHY A GUARD AND NOT JUST THE TABLES. Every incident found this week was
something computed and discarded, and each one looked healthy from outside:

    activation_z                 no write path at all
    strategy library             24h-TTL Redis key (S-105)
    signal_outcomes              dead 104 days, callers reported success
    eleven tables                did not exist; writes returned False (S-166)
    production                   read-only for 5 days, pushes returned 200 (S-168)
    asset_embeddings_history     0 rows, push script logged "complete" (S-169)

The pattern is not carelessness. **Computing something feels like having it, and
only a schema disagrees.** So this guard checks the two properties that make a
forward record real rather than decorative:

  1. a row records HOW MUCH OF THE PANEL it saw, so a collapsed feed is visible
     in the data instead of discoverable by whoever happens to look;
  2. an outcome column is NEVER written at creation time, and a failure to
     persist is REPORTED rather than returned as a quiet False.

THE FIRST ONE FIRED IMMEDIATELY. The very first call to refresh_depth_divergence()
wrote 25 rows against a 262-symbol panel: the `Crypto` class feed is 10 days
stale (last day 2026-08-08) while L1/L2/DeFi/Infra/RWA are current. Left alone
the log would have filled with 25 rows a day and looked fine — which is exactly
TaskList #31/#32's shape, arriving before the record was a day old.

Run: python3 -m tests.test_forward_records_actually_record
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.data.signals.depth_divergence import (   # noqa: E402
    DEPTH_Z_MIN,
    GATE_DAYS,
    INCEPTION,
    PRICE_FLAT_ABS,
    SIGNAL_NEUTRAL,
    SIGNAL_UNDERWEIGHT,
    classify,
    summarise,
    to_row,
)

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


# ── The measured condition, and only that condition ──────────────────────────

def test_the_underweight_fires_only_on_the_measured_cell() -> None:
    """S-172 measured ONE negative cell. Firing on any other is a claim nothing
    supports."""
    hit = classify("AAA", "2026-08-18", depth_z=2.0, px20=0.02)
    check("depth up + price flat → UNDERWEIGHT",
          hit.signal == SIGNAL_UNDERWEIGHT and hit.cell == "depth_up_price_flat", "")
    for label, dz, px in (("depth up + price up", 2.0, 0.25),
                          ("depth up + price down", 2.0, -0.25),
                          ("depth flat", 0.2, 0.02)):
        o = classify("AAA", "2026-08-18", depth_z=dz, px20=px)
        check(f"{label} stays NEUTRAL", o.signal == SIGNAL_NEUTRAL,
              f"got {o.signal} — S-172 found no evidence for a call here "
              f"(up_up was t=-1.56, indistinguishable from zero)")


def test_no_buy_sell_language_anywhere() -> None:
    """CLAUDE.md #1. We hold no 投顾 license; the vocabulary is positioning-only.
    A -1.85% conditional in a long-only book is a WEIGHT decision, not a
    direction — 'do not add here', never 'sell'."""
    src = (_ROOT / "src/data/signals/depth_divergence.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    body = code.split('"""')[-1]     # past the module docstring
    for banned in ("BUY", "SELL", "ACCUMULATE", "AVOID", "REDUCE"):
        check(f"no '{banned}' in emitted values", banned not in body.upper(), "")
    check("signals come from the compliance enum",
          SIGNAL_UNDERWEIGHT == "UNDERWEIGHT" and SIGNAL_NEUTRAL == "NEUTRAL", "")


# ── The two properties that make a record real ───────────────────────────────

def test_no_data_and_no_signal_are_different_states() -> None:
    """A NEUTRAL from 'nothing fired' and a NEUTRAL from 'we could not look' must
    never render the same. That collapse is S-131's cap_source, S-141's moat
    band, and the reason eleven missing tables read as 'no data yet'."""
    blind = classify("AAA", "2026-08-18", depth_z=None, px20=0.01)
    quiet = classify("AAA", "2026-08-18", depth_z=0.1, px20=0.01)
    check("missing input is flagged unmeasured",
          not blind.is_measured and blind.cell == "unmeasured", "")
    check("and says why", bool(blind.problems), "")
    check("a genuine non-signal IS measured", quiet.is_measured, "")
    check("the two carry different cells", blind.cell != quiet.cell, "")


def test_the_daily_summary_reports_coverage_not_just_hits() -> None:
    """3 hits out of 12 measured is a different day from 3 out of 240."""
    obs = ([classify(f"S{i}", "2026-08-18", depth_z=2.0, px20=0.01) for i in range(3)]
           + [classify(f"T{i}", "2026-08-18", depth_z=None, px20=None) for i in range(9)])
    s = summarise(obs)
    check("summary counts unmeasured separately", s["n_unmeasured"] == 9, str(s))
    check("summary counts measured", s["n_measured"] == 3, "")
    check("summary counts the underweights", s["n_underweight"] == 3, "")


def test_a_row_never_carries_its_own_outcome() -> None:
    """A row that knows its forward return at creation time is a row nobody can
    trust. The resolver fills those 20 trading days later, once."""
    r = to_row(classify("AAA", "2026-08-18", depth_z=2.0, px20=0.01))
    for col in ("fwd20", "bench20", "excess20", "resolved_at"):
        check(f"{col} absent at write time", col not in r, f"row leaked {col}")


def test_the_holder_history_write_reports_its_own_failure() -> None:
    """The previous arrangement lost this data quietly for months by writing it
    to a TTL'd cache. A best-effort persist is fine; a SILENT one is not."""
    src = (_ROOT / "src/data/cis/holder_provider.py").read_text(encoding="utf-8")
    check("refresh_holder_map persists history",
          "_persist_history(" in src, "")
    blk = src.split("async def _persist_history")[1][:3000]
    code = "\n".join(l for l in blk.splitlines() if not l.lstrip().startswith("#"))
    check("a failed persist logs a warning", "logger.warning" in code,
          "a silent False is what made the other four invisible")
    check("and names the likely cause", "APP_ROLE=production" in code, "")
    check("it uses the role-gated upsert", "supabase_upsert_table(" in code, "")


# ── The claim is bounded ─────────────────────────────────────────────────────

def test_the_in_sample_result_is_not_presented_as_forward() -> None:
    s = summarise([])
    check("the summary states IN-SAMPLE explicitly", "IN-SAMPLE" in s["claim"], "")
    check("and names the gate date inputs",
          INCEPTION in s["claim"] and str(GATE_DAYS) in s["claim"], "")
    check("gate is at least the discipline minimum", GATE_DAYS >= 60,
          "tests/test_strategy_discipline.py requires >=60d paper before SHIP")


def test_thresholds_are_stated_as_pre_registered() -> None:
    """They were fixed before S-172 ran and not re-scanned. If a later author
    tunes them against outcomes, that is a fit, and experiment_runs.dsr — the
    deflated-Sharpe column that exists to charge for exactly that — has never
    been populated in 43 rows."""
    check("depth threshold unchanged from the study", DEPTH_Z_MIN == 1.5, "")
    check("price-flat band unchanged from the study", PRICE_FLAT_ABS == 0.10, "")
    src = (_ROOT / "src/data/signals/depth_divergence.py").read_text(encoding="utf-8")
    check("the file records that they were pre-registered",
          "not re-scanned" in src or "BEFORE the study ran" in src, "")


if __name__ == "__main__":
    print("── forward records actually record (S-173) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ coverage visible · no-data ≠ no-signal · outcomes written only by the resolver")
