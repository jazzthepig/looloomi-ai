# PANEL_LONG_ONLY_SPEC — §5b ① 形态 A · panel-wide long-only hold

> **This is the canonical ①** — the FoF core benchmark every other sleeve
> is measured against. **BTT-LEX (M-152) is the BTC-only形态 B of the same
> return layer**, validated SHIP-READY at SR +1.115 / cum +178.0% /
> MaxDD -20.44%. **This spec exists because M-152 was not enough** — the
> panel-wide形态 A was the actual §5b structural gap. **「Hold the panel,
> never 0」 was the doctrine; the instrument that holds the panel
> literally did not exist before this.**

## §5b context (do not re-derive; quote ARCHITECTURE.md)

> ① **capture beta** (long-only hold of the panel — the FoF core;
> the benchmark every sleeve is measured against is "hold the panel",
> NEVER 0)

The hierarchy is a priority order, not a menu. ① is what every other
return must measure against. If the panel is not held, every ②③④
excess is measured against the wrong baseline (zero = a magic dollar).
R76…R94 built ④ cross-sectional demean, which **discards beta by
construction**, then measured excess against zero. That is the
specification error behind the 15-attempt graveyard.

**This spec implements ①.** It is the doctrinal baseline.

## What this spec does NOT do (preemptive scope cuts)

| NOT | Why |
|---|---|
| Short any symbol | ① is **long-only** by definition. Shorts belong to ④. |
| Derivatives / perps / funding | ① holds **spot**, on whichever chain has depth. Perps belong to ②③④ because they already carry funding accounting; ① does not. **Measured 2026-08-23**: equal-weight funding on the ① panel was +23.07% annualised (AAVE +110.8%, NEAR +94.4%), so at gross 1.15 a perp-based ① bleeds ~26.5%/yr — larger than any alpha ever demonstrated. |
| Cross-sectional rank / L/S | ④ — different family. |
| Beta-neutralize any book | β-adjustment is for **attribution** (see R62), never for neutralizing the benchmark. |
| Fabricate a return when panel is empty | Per §3: refuse, then `insufficient_data`, never mark 0%. |
| Use today's price to decide today's trades | **lag-1 PIT discipline** (S-114, S-122): signal uses bars ≤ d-1; entry price = bar at d. |

## Spec shape

```json
{
  "spec_name": "panel_long_only_bench",
  "spec_family": "panel_long_only",
  "universe": ["BTC", "ETH", "SOL", "AAVE", "MKR", "UNI", ...],
  "parameters": {
    "allocation": "equal_weight",        // or "cis_weight" | "market_cap_weight"
    "target_size": 0,                    // 0 = entire universe; N = top N by allocation rank
    "rebalance_cadence": 7,              // days between rebalances
    "max_position_pct": 0.10,            // cap any single position at 10%
    "min_position_pct": 0.0,             // floor (0 = no floor)
    "cost_bps_rt": 5.0,                  // round-trip cost per leg
    "dd_stop_pct": -25.0,                // if port DD < this → SKIPPED, no new entry
    "max_open_trades": 200,              // defensive cap; ① is rarely at the cap
    "regime_gate": {                     // optional regime filter
      "RISK_OFF": false,
      "STAGFLATION": false,
      "default": true                    // all other regimes: hold
    },
    "min_history_days": 365              // need 1y to qualify as ① candidate
  },
  "data_source": {"primary": "deep_walk"},
  "execution": {"dry_run": true}
}
```

## decide_panel_long_only() shape

```text
INPUTS
  spec     : Spec (universe + parameters + family)
  panel    : Panel (closes by symbol, last_bar)
  as_of    : date (today)
  regime   : canonical regime or None
  n_open   : current open trade count
  state    : portfolio state (last_rebalance, current_weights, peak_nav)

1. BLOCKED
   panel.n_symbols == 0                           → BLOCKED "empty panel"
   panel.age_days(as_of) > MAX_PANEL_AGE_DAYS     → BLOCKED "panel too old"
   len(universe) < MIN_UNIVERSE_FOR_RANK          → BLOCKED "universe < 3"
   universe not subset of panel.closes            → BLOCKED "missing symbols"

2. Sizing — derive target_weights
   target_symbols = top_n_by(allocation_rank, panel, spec.target_size)
                    or universe if target_size == 0
   weights        = equal / cis / market_cap, normalised
   weights        = cap(weights, spec.max_position_pct)

3. SKIPPED gates (in order)
   regime not in regime_gate (default skip on RISK_OFF / STAGFLATION)
                                                  → SKIPPED f"regime {regime} gated"
   dd_stop breached (peak_nav → current_nav)
                                                  → SKIPPED "dd_stop"
   n_open >= max_open_trades                     → SKIPPED "capacity"
   last_rebalance within rebalance_cadence days  → SKIPPED "not rebalance day"

4. ENTERED
   legs = tuple(Leg(sym, "long", weight, px_at_d) for sym, weight in target)
   return Decision(verdict=ENTERED, legs=legs,
                   reason=f"rebalance {as_of}, n_legs={len(legs)}")
```

## Why "ENTERED on rebalance days, SKIPPED otherwise"

① must produce a **markable** book. Daily marks come from the NAV layer
(daily market value of held positions), not from spec_runner. Spec_runner
is the **decision** layer — it produces an ENTERED leg tuple when there
is a rebalance, and SKIPPED otherwise. **The daily mark still happens
either way** — that's what "the panel is held every day" means in
practice.

ENTERED-on-every-day is also acceptable as long as the legs are
idempotent (same targets → same legs → cost-tracked daily). We chose
SKIPPED-on-non-rebalance-day for **audit clarity**: an operator looking
at the decision log can tell at a glance which days were rebalance
events.

## What needs to exist for this to ship

### Spec + decide_

- `paper_trading/spec_runner.py`:
  - Add `"panel_long_only": True` to `FAMILIES`
  - Add Spec.load() branch requiring `allocation`, `rebalance_cadence`,
    `cost_bps_rt`, `dd_stop_pct`, `max_open_trades`, `min_history_days`
  - Add dispatch in decide() → `decide_panel_long_only()`
  - Implement `decide_panel_long_only()` per shape above
  - State contract: spec_runner reads `state.last_rebalance` (a date) to
    decide rebalance day; this requires passing `state` through. **The
    current decide() signature has only n_open, not full state.** Either
    add a `state` parameter (breaking change to all families) or read
    `last_rebalance` from spec.raw directly (less clean but no signature
    break — same trick BTT-LEX used for raw params). **Recommend the
    latter** — signature break ripples to every existing family.

### Allocation helpers

- `allocation = "equal_weight"`: target_weights = {sym: 1.0/N} normalised
- `allocation = "cis_weight"`: pull cis_score from panel features, weight
  = (cis_score - 25) clipped to 0, normalised. **Caveat**: cis_score
  changes daily; this means rebalance has to also re-fetch features.
- `allocation = "market_cap_weight"`: pull market_cap from external
  feature; same caveat.

For v1 ship, **equal_weight only**. cis_weight and market_cap_weight go
on a "next" list because they need the features layer wired through
panel.

### Tests (CI-portable, no DB / no secrets)

`tests/test_panel_long_only_smoke.py`:

- T1: panel empty → BLOCKED
- T2: panel 5d old → BLOCKED
- T3: universe size 2 (< MIN) → BLOCKED
- T4: missing symbol → BLOCKED
- T5: regime = RISK_OFF (gated off) → SKIPPED "regime gated"
- T6: dd_stop breached (state.peak_nav / current_nav < threshold) →
  SKIPPED "dd_stop"
- T7: rebalance day → ENTERED with N equal-weight long legs
- T8: not rebalance day (last_rebalance = yesterday, cadence = 7) →
  SKIPPED "not rebalance day"
- T9: target_size = 3, allocation = cis_weight → ENTERED with top 3
  symbols, weights capped at max_position_pct
- T10: max_position_pct = 0.10, 5 symbols → no weight > 0.10, weights
  sum to 1.0
- T11: lag-1 PIT — signal bars ≤ d-1; entry price = bar at d

### Bar to ship

- decide_panel_long_only() passes 11/11 synthetic tests
- Wire into runner as a family
- Smoke a 365d paper-trading backtest on the actual panel
- Compare return vs `buy-and-hold-equal-weight` benchmark — excess
  should be ~0 (≤ cost bps) — that's the bar for "this is the benchmark"

## M-152 vs panel_long_only (形态 A vs 形态 B of §5b ①)

| | M-152 BTT-LEX (形态 B) | panel_long_only (形态 A) |
|---|---|---|
| Universe | BTC only | Full benchmark universe (24 names) |
| Sizing | weight × regime ladder (1.30/1.15/1.00/0.80/0.00) | equal / cis / mcap weight |
| Rebalance | Daily | Cadence (default 7d) |
| Regime interaction | Goes to 0 in RISK_OFF | Goes to 0 only if regime_gate says so |
| DD stop | -20% | -25% (looser — benchmark shouldn't flinch early) |
| Lag-1 PIT | ✅ | ✅ |
| Status | SHIP-READY 2026-09-13 | **Design only** — this doc |

**Why both?** BTT-LEX is the BTC-as-bellwether形态. Panel-long-only is
the full-panel形态. **For §5b ① to be a complete doctrine, both must
exist.** BTT-LEX is also a useful sanity check — if ① panel-wide
produces returns that disagree with BTT-LEX on regime risk-off days,
the disagreement itself is information.

## What this spec explicitly defers

- **multi-source panel reconciliation** (S-276, S-273/274/275): the spec
  takes a Panel; the panel must already have done the
  `deepest_start = union across sources` discipline. If it hasn't,
  this spec produces nonsense and the bug lives in panel_fetcher, not
  here.
- **funding-aware sizing for perps**: ① is spot-only per ARCHITECTURE
  and the 2026-08-23 funding measurement.
- **v5 CIS weighting** (M-153 apply): when v5 lands, `cis_weight`
  allocation needs to read v5's two-score output, not v4's pillar sum.
  v5 wiring is on the apply script path (M-153), separate lane.

## Acceptance for SHIP-READY

1. decide_panel_long_only() passes 11/11 synthetic tests
2. Equal-weight variant on 365d backtest produces excess vs buy-and-hold
   within cost bps (the bar for "this is the benchmark, not alpha")
3. Lag-1 PIT discipline enforced (M-114 retention ≥ 0.50)
4. Sparse-sleeve guard M-145 passes (panel_long_only is NOT a sparse
   sleeve — every rebalance day ENTERED — so this is a no-op for the
   default cadence; but if someone sets cadence=60 and 6 symbols only,
   the guard must not flip-fail it)
5. Decision log includes reason field that names the rebalance trigger
   (today's date + cadence elapsed)
6. Wired into the book universe alongside the existing 9 paper books
   as the **first ① standalone** (BTT-LEX being the BTC-only形态 B)

## Linked artifacts

- `docs/ARCHITECTURE.md` §5b (doctrine)
- `docs/HIGH_DIM_ONTOLOGY.md` §5b (return hierarchy)
- `paper_trading/spec_runner.py` (existing families)
- `M-152` BTT-LEX memory (形态 B precedent)
- `M-114` lag-discipline guard (test contract)
- `M-145` sparse-sleeve guard (test contract)
- `tests/test_strategy_discipline.py` (SHIPPED gate)
