"""
Guard: value added is denominated in dollars at a DERIVED capacity (S-132).

Berk & van Binsbergen (JFE 2015): percentage alpha does not predict itself;
dollars extracted persist ~10 years. Two failures this suite exists to prevent:

  1. A SHIP verdict carrying only a percentage. 40 %/yr passes every percentage
     threshold we own even when the book caps at $150k.
  2. A capacity computed over the names whose ADV happened to resolve. Book
     capacity is a MINIMUM; dropping a name can only raise it, and the names
     that fail to resolve are the thin ones that would have bound. A partial
     minimum is an upper bound wearing a capacity's clothes.

Run: python3 -m tests.test_value_added_dollars
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research.factory.capacity import capacity  # noqa: E402
from src.research.factory.value_added import (  # noqa: E402
    MIN_MEANINGFUL_NOTIONAL_USD,
    assess,
    deployable_notional,
    value_added_usd_yr,
)
from src.data.vector.strategy_schema import StrategyRecord  # noqa: E402

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


# ─────────────────────────────────────────────────────────────────────────────
# 1. capacity() must not silently drop unpriced names
# ─────────────────────────────────────────────────────────────────────────────
def test_capacity_reports_unpriced_names() -> None:
    w = {"BTC": 0.5, "ETH": 0.3, "THINCOIN": 0.2}
    adv = {"BTC": 20e9, "ETH": 10e9}          # THINCOIN deliberately absent
    res = capacity(w, adv_usd=adv)
    check("capacity flags partial coverage",
          res.get("status") == "partial", f"status={res.get('status')}")
    check("capacity names the unpriced leg",
          res.get("unpriced") == ["THINCOIN"], f"unpriced={res.get('unpriced')}")


def test_capacity_complete_when_all_priced() -> None:
    w = {"BTC": 0.6, "ETH": 0.4}
    res = capacity(w, adv_usd={"BTC": 20e9, "ETH": 10e9})
    check("complete coverage says so", res.get("status") == "complete",
          f"status={res.get('status')}")
    check("coverage_pct == 100", res.get("coverage_pct") == 100.0,
          f"{res.get('coverage_pct')}")


def test_capacity_no_network_when_adv_injected() -> None:
    """Railway US is geo-blocked from Binance fapi. If a fully-injected ADV map
    still reaches the network, every deployed capacity number is 0."""
    src = inspect.getsource(capacity)
    body = src.split('"""')[-1]           # skip the docstring, which names the fetch
    line = [ln for ln in body.splitlines() if "_adv_usd(s)" in ln]
    check("injected ADV short-circuits the fetch",
          bool(line) and "adv_usd" in line[0] and " or _adv_usd(s)" in line[0],
          f"capacity() must prefer the injected map; got {line}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. deployable_notional refuses partials
# ─────────────────────────────────────────────────────────────────────────────
def test_partial_coverage_returns_none() -> None:
    n, basis = deployable_notional({"BTC": 0.5, "THINCOIN": 0.5},
                                   {"BTC": 20e9})
    check("partial ADV → no notional", n is None, f"got {n}")
    check("basis explains the refusal", "partial_adv_coverage" in basis, basis)


def test_binding_leg_sets_capacity() -> None:
    """The thin leg must bind, not the deep one."""
    w = {"BTC": 0.5, "SMALL": 0.5}
    adv = {"BTC": 20e9, "SMALL": 4e6}
    n, basis = deployable_notional(w, adv)
    # 0.05 × 4e6 × 3 / 0.5 = 1.2e6
    check("thin leg binds", n is not None and abs(n - 1.2e6) < 1e5, f"n={n}")
    check("basis names the binding leg", "SMALL" in basis, basis)


def test_empty_book() -> None:
    n, basis = deployable_notional({}, {})
    check("empty book → None", n is None and basis == "no_positions", basis)


# ─────────────────────────────────────────────────────────────────────────────
# 3. the deception this whole item exists to catch
# ─────────────────────────────────────────────────────────────────────────────
def test_big_percentage_tiny_book_is_not_meaningful() -> None:
    """40 %/yr that caps below $1m is a research result, not a sleeve."""
    r = assess({"SMALL": 1.0}, {"SMALL": 1e6}, net_effect_pct_yr=40.0)
    # 0.05 × 1e6 × 3 / 1.0 = 150_000
    check("tiny capacity computed", r["deployable_notional_usd"] is not None
          and r["deployable_notional_usd"] < MIN_MEANINGFUL_NOTIONAL_USD,
          f"{r['deployable_notional_usd']}")
    check("40%/yr on a tiny book is NOT meaningful", r["meaningful"] is False,
          f"meaningful={r['meaningful']} note={r['note']}")
    check("note states the dollar cap", "research result" in r["note"], r["note"])


def test_small_percentage_large_book_is_meaningful() -> None:
    r = assess({"BTC": 0.5, "ETH": 0.5}, {"BTC": 20e9, "ETH": 10e9},
               net_effect_pct_yr=2.0)
    check("deep book is meaningful", r["meaningful"] is True, str(r))
    check("dollars beat the 40% micro-book",
          r["value_added_usd_yr"] > 60_000, f"{r['value_added_usd_yr']}")


def test_value_added_arithmetic() -> None:
    check("va = pct/100 × notional",
          value_added_usd_yr(2.5, 40e6) == 1_000_000.0,
          str(value_added_usd_yr(2.5, 40e6)))


# ─────────────────────────────────────────────────────────────────────────────
# 4. the SHIP gate actually consumes these fields
# ─────────────────────────────────────────────────────────────────────────────
def _ship_base() -> dict:
    sig = set(inspect.signature(StrategyRecord).parameters)
    base = dict(id="guard", title="guard", doc_source="tests", verdict="ship",
                cause="documented", oos_survival=True, paper_days=60,
                net_effect_pct_yr=3.0, turnover_cost_pct_yr=1.0)
    return {k: v for k, v in base.items() if k in sig}


def _problems(**kw) -> list:
    out = StrategyRecord(**{**_ship_base(), **kw}).validate()
    return out if isinstance(out, list) else (getattr(out, "problems", out) or [])


def test_ship_requires_dollar_fields() -> None:
    hits = [p for p in _problems()
            if "value_added_usd_yr" in str(p) or "deployable_notional_usd" in str(p)]
    check("ship without dollars is rejected", bool(hits),
          "validate() let a percentage-only SHIP through")


def test_ship_requires_a_basis() -> None:
    hits = [p for p in _problems(deployable_notional_usd=5e7,
                                 value_added_usd_yr=1.5e6,
                                 notional_basis="") if "notional_basis" in str(p)]
    check("empty notional_basis is rejected", bool(hits),
          "an unexplained notional is an assumed notional")


def test_ship_rejects_sub_million_capacity() -> None:
    """The exact deception: a real, positive percentage on a book too small to matter."""
    r = assess({"SMALL": 1.0}, {"SMALL": 1e6}, net_effect_pct_yr=40.0)
    hits = [p for p in _problems(deployable_notional_usd=r["deployable_notional_usd"],
                                 value_added_usd_yr=r["value_added_usd_yr"],
                                 notional_basis=r["notional_basis"])
            if "research result" in str(p)]
    check("40%/yr on $150k is rejected at the SHIP gate", bool(hits),
          f"gate accepted a ${r['deployable_notional_usd']:,.0f} book")


def test_floor_is_single_sourced() -> None:
    from src.data.vector import strategy_schema as _ss
    from src.research.factory import value_added as _va
    check("one floor, not two",
          _ss.MIN_MEANINGFUL_NOTIONAL_USD is _va.MIN_MEANINGFUL_NOTIONAL_USD,
          "value_added must import the schema's constant, not redefine it")


def test_ship_passes_with_derived_dollars() -> None:
    r = assess({"BTC": 0.5, "ETH": 0.5}, {"BTC": 20e9, "ETH": 10e9},
               net_effect_pct_yr=3.0)
    hits = [p for p in _problems(deployable_notional_usd=r["deployable_notional_usd"],
                                 value_added_usd_yr=r["value_added_usd_yr"],
                                 notional_basis=r["notional_basis"])
            if "value_added" in str(p) or "deployable_notional" in str(p)
            or "notional_basis" in str(p)]
    check("derived dollars satisfy the gate", not hits,
          f"still blocked: {hits[:1]}")


if __name__ == "__main__":
    print("── value added in dollars (S-132) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ all value-added guards pass")
