# Strategy 4 — Cross-Asset Quality-Momentum-LowVol Tilt (AQR flavor)

**Minimax-B, 2026-08-20** — Spec for an AQR-style long-only factor tilt across
crypto + TradFi. Status: 🟡 **SPEC LOCKED, backtest pending (Minimax-B
analysis lane)**.

## Why this is the right next move

AQR's foundational contribution was demonstrating that **value / momentum /
quality / low-risk** factors are robust across decades and asset classes.
The architecture is:
- **Multi-asset** (equities, bonds, commodities, FX) — not crypto-only.
- **Long-only or modest L/S** with explicit beta exposure (the "tilt" in
  "factor tilt" — capture beta first, then add factor premium).
- **Vol-targeted** so the factor premium is comparable across sleeves.
- **Long holding periods** (1+ months rebalance) — factor premia are slow.

CLAUDE.md is explicit:
> **默认 long-only: tilt, 不要 neutralize.**

Strategy 4 implements this directly:
- Multi-asset: 41 crypto + 17 TradFi = 58-asset universe
- Long-only tilt: overweight winners, underweight losers, no shorting
- Vol-targeted: H3.2 conviction-scaled sizing
- 5d rebalance (R77 cadence — same as our validated line)

The graveyard (12-attempt) was about **cross-sectional market-neutral L/S
shapes**. Strategy 4 explicitly avoids that by construction — it's a tilt,
not a neutralisation. The W5 fragility that breaks single-leg market-neutral
factor books does NOT apply to a long-only tilt, because we're not betting
against the market; we're betting on relative quality + momentum.

## Hypothesis (testable)

A long-only tilt by composite z_quality + z_momentum + z_lowrisk on the
58-asset universe produces:
- Excess return vs hold-the-panel benchmark, regime-stable.
- Sharpe > 1.0 with maxDD < −20% (factor-tilt-class).
- W5 ann% positive (no sign-flip — long-only tilt is the structural fix
  for the L/S W5 fragility).
- Survives 5bps cost round-trip.

## Falsification criteria (pre-registered)

Strategy 4 is REFUTED if any of:
- OOS Sharpe < 1.0 (factor tilt must beat simple long-only).
- maxDD > −25% (factor-tilt-class max DD; tighter than expected).
- W5 ann% < 0 (sign-flip — long-only tilt doesn't fix fragility, the
  factor itself is regime-specific).
- 5bps cost round-trip kills the gross edge (cost structure is hostile).

## Construction (frozen-cell pending backtest)

### Universe
- 41-asset crypto (R46 panel) + 17 TradFi ETFs (per `cis_quality_tradfi.py`).
- 731-day window (2024-06-07 → 2026-06-07).
- 6-window partition (R62 partition).

### Factor scoring (per asset, per day, PIT-safe)

```
z_quality_t  = (cis_pillar_o[t-1, a] - μ_quality[t-1]) / σ_quality[t-1]   # PIT lag 1d
z_momentum_t = (close[t-1, a] / close[t-31, a] - 1)                       # 30d return
z_lowrisk_t  = -(σ_30d[t-1, a] - μ_σ[t-1]) / σ_σ[t-1]                     # -30d vol z

score_t = (z_quality + z_momentum + z_lowrisk) / 3    # equal-weight composite
```

All inputs use t-1 (or earlier) data — no look-ahead. cross-sectional
z-scores use the panel mean/std at t-1.

### Tilt weights (long-only, no neutralisation)

```
rank = score_t.rank(ascending=False)             # 1 = best, N = worst
weight_raw = (N + 1 - rank) / sum(N + 1 - rank)   # linear, top-heavy
weight = weight_raw × vol_target_size            # H3.2 conviction-scaled
```

**No shorting** — the worst-quartile assets get minimum weight (1/N), not
negative weight. CLAUDE.md canonical.

### Aggregator-level controls
- Vol target: 12% annualized (same as Strategy 3).
- Rebalance: 5 days (R77 cadence).
- Cost: 5bps round-trip on turnover.
- H3.2 sizing floor 0.5 / cap 1.75 (R77's Pareto decision).

## Performance (target thresholds)

| Metric | Target | Why |
|---|---|---|
| OOS Sharpe | ≥ 1.0 | factor tilt must beat simple long-only benchmark |
| maxDD | ≤ −20% | tighter than −25% crypto-shop, looser than −15% pod aggregator |
| W5 ann% | ≥ 0 | long-only fixes the L/S W5 sign-flip |
| Hit rate | ≥ 55% | direction-of-tilt correctness |
| 5bps ann cost | ≤ 2%/yr | cost efficiency |

## Live spec

If SHIP-worthy:
- File: `src/research/validation/cross_asset_factor_tilt_live.py`
  (paper-trade loop).
- Endpoint: `GET /api/v1/signals/factor-tilt` (new endpoint, parallel to
  `/api/v1/signals/fusion-paper`).
- Append to STRATEGY_PLAYBOOK as Strategy 4 with frozen cell.

## Files

- **Spec**: this document.
- **Backtest rig**: `src/research/validation/cross_asset_factor_tilt.py`
  (Mac-side, reads 58-asset panel + CIS-history pillar_O).
- **Output**: `reports/CROSS_ASSET_FACTOR_TILT_2026-08-NN.md` (3-check +
  per-window + factor-decomposition).

## Monitoring (post-SHIP)

- `cross_asset_factor_tilt_tracking_loop` (daily mark).
- Per-factor contribution to Sharpe — if any one factor contributes > 70%
  of the Sharpe, the composite is not actually diversified (refutes the
  "factor diversification" claim).
- Regime sensitivity — does the tilt still produce excess in Tightening
  regime (R46 was regime-conditional; tilt should be more regime-stable).

## Pre-flight (before backtest result is finalised)

- `tests/test_strategy_discipline.py` 13/13 green.
- `tests/test_factor_tilt_smoke.py` — 3 unit tests:
  1. long-only constraint (no negative weights ever).
  2. cross-sectional z-score uses t-1 data only (PIT-safe).
  3. vol targeting (ann vol ≤ 13% on the IS window).

## What this is NOT

- Not a market-neutral L/S — explicitly long-only tilt per CLAUDE.md.
- Not a new alpha source — quality/momentum/low-risk are well-known
  factors; we are NOT discovering them, we are applying them within our
  CIS-quality framework.
- Not a replacement for R77 — R77 is a market-neutral L/S sleeve;
  Strategy 4 is a long-only tilt. They are complementary, not substitutes.
  If SHIP, both ship; the question is allocation between them.
- Not a substitute for §OHLCV-EXTENSION — runs on 731-day panel;
  11yr extension re-validates.

## Why now (and not earlier)

Three preconditions that JUST landed:
1. CIS pillar_O is now OOS-validated at t=+3.33 (R46, 2026-07-20) — quality
   factor has a defensible base.
2. H3.2 sizing is shipped (2026-07-10) — vol-targeting layer is production-ready.
3. The 731-day bear-dominated graveyard finding (2026-07-26, lesson #54) tells
   us single-leg L/S is dead — but long-only tilt is structurally different
   and unencumbered by the L/S sign-flip fragility.

Combined, this is the first time in the project's history that Strategy 4's
preconditions are ALL met simultaneously.