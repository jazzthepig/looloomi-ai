# Strategy 3 — Pod Aggregator (Millennium flavor)

**Minimax-B, 2026-08-20** — Spec for a pod-style meta-strategy that aggregates
already-validated sleeves (R46 / R62 / R76) as independent alpha "pods". Status:
🟡 **SPEC LOCKED, backtest pending (Minimax-B analysis lane)**.

## Why this is the right next move

Millennium Management runs ~280 independent pods on a shared risk/financing
platform. The architecture is:
- Each pod has its own strategy, sizing, kill switch.
- Aggregate is constructed by **OOS-Sharpe-weighted** combination.
- Cross-pod correlation is bounded — pods share risk only when their
  return streams are genuinely orthogonal.
- **Capital efficiency** comes from aggregation; **alpha** comes from each pod
  independently; the platform does NOT manufacture new alpha, it just
  allocates it well.

Our frozen R77 fusion cell (w_R46=0.25 / w_R62=0.75 / w_R76=0.30) is already
a 3-leg aggregation with the same flavor. Strategy 3 generalises:
- Same 3 legs as pods.
- Generalised to N pods (a future R-N candidate can be added as Pod N+1).
- Cross-pod correlation gate formalised (lesson #42).
- Vol-targeting moved up to the aggregator (not the pod).
- Per-pod DD circuit breaker.

The graveyard (12-attempt) was about **single-leg survival on bear-dominated
panel**. Strategy 3 does NOT try to discover a new alpha source — it
**aggregates the alpha we already have** with capital-efficiency discipline.

## Hypothesis (testable)

A pod-style aggregator over {R46, R62, R76} produces:
- Sharpe > max(pod Sharpe) due to diversification, on the bear-dominated
  731-day panel.
- maxDD < max(pod maxDD) due to vol-targeting at the aggregator.
- Stable per-window (W1-W6) P&L — the pod correlation structure should
  smooth the W5 fragility that hits R46 and R62 individually.

## Falsification criteria (pre-registered)

Strategy 3 is REFUTED if any of:
- Aggregator OOS Sharpe < best single pod (no diversification benefit).
- max |corr(pods)| > 0.30 (lesson #42 — pods are not orthogonal, aggregation
  is just weighted averaging with extra capacity overhead).
- Aggregator maxDD > any pod's maxDD + 5pp (vol-targeting doesn't help).
- W5 ann% flips sign vs single-pod best (the per-window stability claim fails).

## Construction (frozen-cell pending backtest)

### Pods
- **Pod 1**: R46 pillar_O 5d/5bps — score = pillar_O LEVEL (PIT-safe ffill,
  1d lag), k=3 terciles, long top / short bottom.
- **Pod 2**: R62 fragility-gated fade-the-crowd 21d/0bps — score = −funding_z
  (long uncrowded / short crowded), gated by R62 fragility detector.
- **Pod 3**: R76 funding residual 5d/0bps — score = funding − mean_a(funding),
  k=3 terciles, long high-residual / short low.

### Frozen weights (placeholders, pending OOS-Sharpe regression)
```
w_Pod1 = 0.25   # placeholder; replace with shrinkage-Sharpe weight
w_Pod2 = 0.75   # placeholder
w_Pod3 = 0.30   # placeholder
```
**Frozen weights are filled in by `pod_aggregator.py` after backtest runs**
(see §FROZEN-WEIGHT-FILL).

### Cross-pod correlation gate (lesson #42)
- Pre-trade: max |corr(pod_i, pod_j)| for any pair < 0.30 on the IS window.
- If breached: drop the lowest-OOS-Sharpe pod, re-weight.

### Aggregator-level controls
- Vol target: 12% annualized (AQR-class — lower than 15-20% crypto shop,
  higher than the vol-naive unweighted book).
- Rebalance: 5 days.
- Cost: 5bps round-trip on turnover.
- Per-pod DD circuit breaker: −15% per pod (kill switch — that pod's weight
  goes to 0 until manual reset).

### Universe
- 41-asset CIS ∩ OHLCV (R46 panel — the broadest validated panel).
- 731-day window (2024-06-07 → 2026-06-07).
- 6-window partition (R62 partition).

## Performance (target thresholds)

| Metric | Target | Why |
|---|---|---|
| OOS Sharpe | ≥ 1.5 | better than any single pod (R77 OOS Sharpe ≈ 2.06) |
| maxDD | ≤ −15% | vol-targeting should bound this; tighter than single-pod worst |
| W5 ann% | ≥ 0 | the fragility claim — aggregator should not inherit W5 sign-flip |
| max \|corr(pods)\| | ≤ 0.30 | lesson #42 gate |
| gross_t | ≥ 2.0 | survives the 3-check gauntlet |
| OOS_t | ≥ 2.0 | survives the 3-check gauntlet |

## Live spec

If SHIP-worthy:
- New file: `src/research/validation/pod_aggregator_live.py` (paper-trade loop).
- Endpoint: `GET /api/v1/signals/pod-aggregator` (mirror of `/api/v1/signals/fusion-paper`).
- Append to STRATEGY_PLAYBOOK as Strategy 3 with frozen cell.

## Files

- **Spec**: this document.
- **Backtest rig**: `src/research/validation/pod_aggregator.py` (Mac-side,
  reads 41-asset panel + R46/R62/R76 sleeve-return files).
- **Output**: `reports/POD_AGGREGATOR_2026-08-NN.md` (3-check + per-window).

## Monitoring (post-SHIP)

- `pod_aggregator_tracking_loop` (mirror of `fusion_paper_tracking_loop`).
- Daily NAV vs R77 (Strategy 1) correlation — if > 0.85, pod structure is
  adding nothing (refutes the diversification thesis live).

## Pre-flight (before backtest result is finalised)

- `tests/test_strategy_discipline.py` 13/13 — cause documented / oos_survival
  / ≥60d paper / regime-conditional, all green.
- `tests/test_pod_aggregator_smoke.py` — 3 unit tests:
  1. cross-pod correlation gate (max |corr| < 0.30)
  2. vol targeting (ann vol ≤ 13% over the IS window)
  3. per-pod DD circuit breaker (a -16% pod is dropped from aggregation)

## What this is NOT

- Not a new alpha source — Strategy 3 is capital-efficiency + risk discipline
  on top of validated sleeves.
- Not a replacement for R77 — Strategy 3 generalises R77; if SHIP, R77 stays
  frozen as the in-production 3-leg cell. Strategy 3 is a meta-layer with
  stricter gates.
- Not a substitute for §OHLCV-EXTENSION — Strategy 3 still runs on the
  731-day bear-dominated panel. The 11yr extension (when it lands) is a
  re-validation, not a precondition.