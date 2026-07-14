# H2 Direction Table — Per-Regime CIS Gate Direction (post-H2a, 2026-07-10)

**Author:** Seth / Austin · 2026-07-10
**Status:** 🟡 awaiting Phase A (H2b) A/B validation before any production flip
**Builds on:** `docs/H2_REGIME_GATE_DESIGN_2026-07-06.md` (the design), `reports/H2A_RELATIVE_IC_2026-07-10.md` (the finding)
**Purpose:** Single source of truth for the per-regime × per-horizon CIS gate direction
that the LS v1 Nautilus gate must apply, *validated by H2a's benchmark-relative IC test*.

---

## 0. TL;DR

H2a (run 2026-07-10) **confirmed** H1's sign-flips are **genuine reversals**, not beta artifacts:

| Regime | 7d abs-IC | 7d rel-IC | read |
|---|---:|---:|---|
| Stagflation | -0.235 | **-0.326** (DEEPENS) | reversal — high-CIS underperforms BTC *more* in relative terms |
| Risk-On    | -0.166 | -0.101 | reversal — persists at 7d |
| Risk-Off   | -0.093 | -0.104 | reversal — most reliable (n=5,578) |
| Easing     | +0.029 | +0.016 | flat — no signal |
| Tightening | +0.168 | +0.108 | consistent — high-CIS is correct (both signs +) |

LS v1 (Nautilus) currently runs `LSV1_GATE_DIRECTION_<R>=high` for all regimes (i.e., *long* high-CIS / *block* low-CIS). That is **wrong in 3 of 5 observed regimes at 7d**.

The H2 design (2026-07-06) was framed as "we won't just invert in production." With H2a confirming genuine reversal, **inversion becomes the correct path** — but ONLY where H2a says reversal, and ONLY at the relevant horizon. This doc publishes the table.

---

## 1. The direction table (H2a-derived, canonical for 7d horizon)

```
H2 direction table (7d) — for LS v1 `per_regime_direction` config:
  Tightening  → high        (CIS-as-ranking is correct; long high-CIS names)
  Easing      → high        (both ICs near zero, but use "high" as neutral default;
                             no reason to actively pick the lower-CIS bucket)
  Risk-Off    → inverted    (low-CIS names outperform in reversal regimes)
  Risk-On     → inverted    (low-CIS bounce; high-CIS fade)
  Stagflation → inverted    (high-CIS underperforms *more* under relative returns)

Unobserved regimes (kept as future work, do NOT ship):
  Neutral     → high        (current default, no data)
  Goldilocks  → high        (current default, no data)
```

**Horizon note:** LS v1 holds positions for 1–5 days (4h bars + ATR SL/TP brackets). 7d is the relevant IC. 30d horizon (not used by LS v1):
```
30d addendum (informational only):
  Easing      → inverted    (genuine reversal at 30d, both ICs negative)
  Risk-On     → flat/drop   (only BETA artifact at 30d — flip is short-horizon only)
```

---

## 2. How the gate uses it (concrete semantics)

LS v1's `_cis_passes(symbol, side=+1)` already supports three modes:

```
direction="high"     → require score >= effective_floor
direction="inverted" → require score <= effective_floor
direction="drop"     → no CIS check (allow)
```

The H2a table maps to:

| Regime (today) | LS v1 gate direction |
|---|---|
| Tightening | high |
| Easing | high |
| Risk-Off | inverted |
| Risk-On | inverted |
| Stagflation | inverted |

**Why `inverted` ≠ literal "short high-CIS":**

The Nautilus LS v1 strategy picks long vs short from EMA(9)/EMA(21) cross + ADX(14) — *not* from CIS. CIS gates *which assets* are tradeable. So `direction=inverted` means: *only allow trades on assets where today's CIS is below the regime floor* — i.e., the assets that historically *outperformed* in this regime.

This is consistent with both the H2 design §3 separation (CIS = cross-sectional spread, regime = direction) and the H2a finding (in reversal regimes, low-CIS names outperform).

For a 3-asset universe (BTC/ETH/SOL), this means:
- Risk-Off + BTC CIS=60, ETH CIS=55, SOL CIS=58 → only ETH (CIS<=floor) is tradeable on this bar.
- Tightening + same → BTC and SOL (CIS>=floor) are tradeable; ETH is blocked.

---

## 3. The freqtrade LS V4 comparator (why we are NOT adopting its design directly)

`Shadow/freqtrade/user_data/strategies/CometCloudLongShortV4.py` uses a **ranking-based** model:
- `REGIME_CIS_FLOOR` = long-side table (enter long with CIS >= floor)
- `REGIME_CIS_FLOOR_SHORT` = short-side table (enter short with CIS <= floor_short, e.g., 30)
- Direction comes from CIS *signal* + ADX + EMA — both sides are active based on regime + signal.

This is a **"long top / short bottom"** model, where the two tables are independent.

| | LS V4 (freqtrade) | LS v1 (Nautilus port) |
|---|---|---|
| Direction model | ranking (long top, short bottom) | single direction per regime (gate) |
| Floors | 2 tables (long + short) | 1 table (effective floor × direction) |
| Trade side from | CIS signal + ADX + EMA | EMA cross + ADX (CIS gates eligibility) |
| H2a reconciliation | both tables need updating (high-floor_long → low, high-floor_short → high) | one config field: `per_regime_direction` |

**Phase A focuses on LS v1** (Nautilus) — it's where the H2b A/B test is most actionable and uses the existing env-var plumbing already wired (`LSV1_GATE_DIRECTION_<R>=high|inverted|drop`). A separate freqtrade V4 update could be Phase 2.4 (handoff to Minimax-C with the SwingOverlay lineage).

---

## 4. Wire-up plan (Phase A + B + C)

### Phase A — H2b A/B (this phase, in scope now)
- **Goal:** confirm H2a direction table actually improves Nautilus LS v1 PnL vs baseline.
- **Mechanism:** promote `LSV1_GATE_DIRECTION_<R>` env vars to a proper `per_regime_direction` config field; A/B the H2a table against current `REGIME_CIS_FLOOR` baseline.
- **Runs:** 4 variants × 2 windows (IS, OOS) = 8 Nautilus runs.
  - `A`: baseline (current env-default = all "high")
  - `B`: H2a direction table (per-regime flipping)
  - `C`: baseline + H3.2 sizing (cap=1.75, optional)
  - `D`: H2a direction + H3.2 sizing
- **Success:** H2a variant ≥ baseline in Δ $/pos AND Δ Sharpe on both IS and OOS windows.

### Phase B — empirical-grid gate (next)
- Read shrunk alpha per (tier × band) from `/api/v1/signals/edge-map`.
- Replace `REGIME_CIS_FLOOR` with magnitude-scaled edges. Direction handling from H2a table stacks on top.

### Phase C — combined
- Wire H2b direction + empirical-grid + H3.2 sizing all together. Test additivity.

### Phase D — swing OOS validation
- The SwingOverlay (freqtrade) lineage is a SEPARATE gate model; H2a applies there too. Walk-forward OOS is the validator.

---

## 5. Success criteria + stop rules

### Pass criteria (production flip blocked until ALL met)
1. **IS PnL improvement:** Δ ≥ +$100 across 3 instruments (sum).
2. **OOS PnL improvement:** Δ ≥ +$10 across 3 instruments (the OOS window is short so we don't expect huge dollars; relative rank matters more).
3. **OOS Sharpe not worse:** Δ OOS Sharpe ≥ -0.05 (Sharpe can dip slightly with added turnover, but not collapse).
4. **Trade count not collapse:** n_orders ≥ 50% of baseline (we don't want a regime that goes near-empty).

### Stop rules (if Phase A fails)
- ❌ Direction flip hurts OOS by > 25% on either of the 3 reversal regimes → revert, don't ship direction.
- ❌ Inversion adds zero-edge trades (high DD / low win / large stale exposure) → revert.
- ❌ Inversion's improvement is IS-only, OOS collapses → keep current. Don't trust the flip.

If Phase A passes moderately (e.g., IS only), repeat with OOS walk-forward validation before any production change. The `REGIME_CIS_FLOOR` default *stays at 52/50/50/58/62/65* until Phase A confirms.

---

## 6. Files + citations

- H2 design (the framework): `docs/H2_REGIME_GATE_DESIGN_2026-07-06.md`
- H2a finding (drives the table): `reports/H2A_RELATIVE_IC_2026-07-10.md`
- H2 floor calibration sweep (the parent driver, reuses infra): `src/research/cis_regime_studies/h2_floor_calibration.py`
- Strategy (LS v1 gate code): `src/research/nautilus/ls_v1/strategy.py:_cis_passes`
- Runner (subprocess wrapper): `src/research/nautilus/ls_v1/runner.py`, `src/research/cis_regime_studies/common/nautilus_runner.py`
- freqtrade V4 comparator: `Shadow/freqtrade/user_data/strategies/CometCloudLongShortV4.py` (read-only reference)

## 7. Reproduction

```bash
source venv/bin/activate

# Phase A sweep driver (this commit):
python3 -m src.research.cis_regime_studies.h2b_regime_direction_ab

# Reuse the H2 sweep infrastructure if needed:
python3 -m src.research.cis_regime_studies.h2_floor_calibration \
    --regimes Risk-Off,Risk-On,Stagflation,Tightening,Easing \
    --magnitudes 30,40,50,60,70
```
