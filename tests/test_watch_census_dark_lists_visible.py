"""
S-378b-D: dashboard showed "49/82 无判决 · 31 完全黑" — but the operator could
not see WHICH 31 tables were dark, only the count.

THE BLIND SPOT. `watch_census.census()` returns:
  - n_not_covered  (49 — the headline number)
  - n_dark         (31 — fully black: no rule AND no write attempts)
  - n_write_observed (18 — write_log sees them, no judgment rule)
  - not_covered_by_tier  (dict — tier → list of names)

What's MISSING: the actual NAMES of the 31 dark tables. The operator staring at
"31 完全黑" cannot tell whether they're REFERENCE items misclassified as OPS,
or whether they're TRACK_RECORD / INPUT tables that genuinely have no
observations. The dashboard hint explains the breakdown in prose but never
shows the list — so the operator can't act.

THE FIX. The `dark` list and `write_observed` list (already computed internally
for the count) are now returned as `dark_tables` and `write_observed_tables`
with their tier — so the dashboard, ops_console, and any future consumer can
enumerate them. The counts stay unchanged; the surface gains visibility.

Run: python3 -m tests.test_watch_census_dark_lists_visible
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.data.market import watch_census as wc   # noqa: E402

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


# ── The two fields the dashboard was missing ──────────────────────────────────

def _synth_census():
    """Build a tiny database with one table per status.

    Uses real COVERAGE table names so the test exercises the actual code path:
      - beta_core_nav          → COVERED (track_record tier)
      - gamma_input            → WRITE_OBSERVED (with write_health entry)
      - epsilon_dark           → NOT_COVERED (default tier → OPS)
      - risk_meter_extra       → NOT_COVERED (starts with risk_meter → SIGNAL)
    """
    tables = ["beta_core_nav", "gamma_input", "epsilon_dark", "risk_meter_extra"]
    write_health = {"gamma_input": {"last_ok": "2026-09-19T10:00Z",
                                    "last_fail": None,
                                    "n_ok_24h": 5, "n_fail_24h": 0}}
    return tables, write_health


def test_census_returns_dark_tables_list() -> None:
    """The '完全黑' tables must be enumerated, not just counted."""
    tables, write_health = _synth_census()
    out = wc.census(tables, write_health)

    check("census exposes 'dark_tables' list (was: only count)",
          "dark_tables" in out,
          f"out keys: {sorted(out.keys())}")
    check("dark_tables contains epsilon_dark by name",
          any(t.get("name") == "epsilon_dark"
              for t in (out.get("dark_tables") or [])),
          f"dark_tables={out.get('dark_tables')}")
    check("dark_tables contains risk_meter_extra by name",
          any(t.get("name") == "risk_meter_extra"
              for t in (out.get("dark_tables") or [])),
          f"dark_tables={out.get('dark_tables')}")
    check("dark_tables carries tier (so the dashboard can group)",
          all("name" in t and "tier" in t for t in (out.get("dark_tables") or [])),
          f"shape={(out.get('dark_tables') or [])[:1]}")


def test_census_returns_write_observed_tables_list() -> None:
    """The '能看见写入尝试' tables must be enumerated too — they're the
    middle ground between fully covered and fully dark, and they are where a
    coverage rule pays off the cheapest (one rule covers all of them)."""
    tables, write_health = _synth_census()
    out = wc.census(tables, write_health)

    check("census exposes 'write_observed_tables' list",
          "write_observed_tables" in out,
          f"out keys: {sorted(out.keys())}")
    check("write_observed_tables contains gamma_input by name",
          any(t.get("name") == "gamma_input"
              for t in (out.get("write_observed_tables") or [])),
          f"write_observed_tables={out.get('write_observed_tables')}")


def test_dark_tables_group_by_tier_for_the_dashboard() -> None:
    """Operators triage by tier. The dark list should be groupable by tier
    without each consumer re-deriving `tier_of` — so we ship it pre-grouped."""
    tables, write_health = _synth_census()
    out = wc.census(tables, write_health)

    dark_by_tier = out.get("dark_tables_by_tier") or {}
    check("dark_tables_by_tier is shipped pre-grouped",
          isinstance(dark_by_tier, dict),
          f"type={type(dark_by_tier).__name__}")
    check("epsilon_dark is in the OPS tier (its tier default)",
          "epsilon_dark" in (dark_by_tier.get("ops") or []),
          f"dark_by_tier={dark_by_tier}")
    check("risk_meter_extra is in the SIGNAL tier (tier_of routes it)",
          "risk_meter_extra" in (dark_by_tier.get("signal") or []),
          f"dark_by_tier={dark_by_tier}")


def test_counts_are_unchanged() -> None:
    """S-323z lesson: a weak fact must NOT shrink the headline number.
    The new lists must not change the existing counts."""
    tables, write_health = _synth_census()
    out = wc.census(tables, write_health)

    # In our synth: 1 covered (beta_core_nav), 1 write_observed (gamma_input),
    # 2 dark (epsilon_dark + risk_meter_extra). Total 4.
    check("n_total = 4 (1 covered + 3 not-covered)", out.get("n_total") == 4,
          f"n_total={out.get('n_total')}")
    check("n_not_covered = 3 (1 write_observed + 2 dark)",
          out.get("n_not_covered") == 3, f"n_not_covered={out.get('n_not_covered')}")
    check("n_write_observed = 1", out.get("n_write_observed") == 1,
          f"n_write_observed={out.get('n_write_observed')}")
    check("n_dark = 2", out.get("n_dark") == 2, f"n_dark={out.get('n_dark')}")
    check("n_dark still equals dark_tables length",
          out.get("n_dark") == len(out.get("dark_tables") or []),
          f"n_dark={out.get('n_dark')}, len={len(out.get('dark_tables') or [])}")
    check("n_write_observed still equals write_observed_tables length",
          out.get("n_write_observed") == len(out.get("write_observed_tables") or []),
          f"n_write_observed={out.get('n_write_observed')}, "
          f"len={len(out.get('write_observed_tables') or [])}")


if __name__ == "__main__":
    print("── S-378b-D: watch_census ships dark_tables + write_observed_tables ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ dark_tables list visible · write_observed list visible · counts unchanged")
