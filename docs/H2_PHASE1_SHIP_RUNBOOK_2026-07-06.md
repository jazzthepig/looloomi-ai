# H2 Phase 1 Ship Runbook — Smoothed Regime Labels in Production

**Date:** 2026-07-06
**Owner sequence:** Minimax-A (Mac) → Seth (Railway) → Jazz (push + verify)
**Decision:** Use **`cis_history_smoothed/` (modal_recency, window=14d)** as the
new regime-label source in production. Default per
`scripts/regime_smoother.py`.

---

## Background (TL;DR)

H2 design §6 phases the regime-conditional gate rollout into 3 phases.
**Phase 1** is the smallest ship-able change: swap the production
regime-label source from raw to smoothed. No floor values change. No
production logic change.

Cross-evidence convergence says this is safe:

| Evidence | Source | Finding |
|---|---|---|
| H1.5 robustness | Smoothed Easing IC = -0.13 abs | Smoothed labels are not broken |
| H2 sweep | Combined smoothed gates IS +$580 | Smoothed gates don't destroy alpha |
| rebalance_engine v4 A/B | Same CAGR, Sharpe +0.02 | Smoothing on consumption side is safe |
| 5-dir × Nautilus A/B | modal_recency IS +18% / OOS -0.9% | Smoothed swap is safe, modest IS upside |

Per `reports/H2_PHASE1_SHIP_READINESS_5DIR_NAUTILUS_2026-07-06.md`:
modal_recency is the only safer-than-baseline smoother. modal_majority
is bit-identical. persistence-14d is structurally worse (-46% IS in
Nautilus) — do not pick.

---

## Architecture — where regime labels flow

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│  Mac Mini       │    │  Mac             │    │  Railway            │
│  cis_v4_engine  │───▶│  cis_scheduler   │───▶│  Redis cache        │
│  MacroSnapshot  │    │  cis_push        │    │  cis:local_scores   │
│  .determine_    │    │  /internal/      │    │  + cis_provider.py  │
│   regime()      │    │  cis-scores      │    │  /api/v1/cis/...    │
└─────────────────┘    └──────────────────┘    └─────────────────────┘
         │                                                 │
         ▼                                                 ▼
   cis_history/                                     (CISLeaderboard,
   cis_YYYY-MM-DD.json                               Signal Feed, ...)
```

`macro_regime` field is set on the **Mac side** by `MacroSnapshot.determine_regime`
and flows through unchanged to Railway + frontend. All consumers read
this field.

---

## What Minimax-A needs to do on the Mac (P0 — blocking)

### Step 1.1 — generate smoothed regime JSON (one-shot)

Already done. **Verify** the 4 smoothed dirs exist with 393 files each:

```bash
ls -la /Volumes/CometCloudAI/cometcloud-local/_data/cis_history_smoothed/ \
       /Volumes/CometCloudAI/cometcloud-local/_data/cis_history_smoothed_majority/ \
       /Volumes/CometCloudAI/cometcloud-local/_data/cis_history_smoothed_persistence/ | \
  grep -c cis_
# expect 393 in each
```

If re-generation needed:

```bash
# From inside the venv on the Mac
source venv/bin/activate
python3 scripts/regime_smoother.py --relabel \
  --cis-dir /Volumes/CometCloudAI/cometcloud-local/_data/cis_history/ \
  --dst-dir /Volumes/CometCloudAI/cometcloud-local/_data/cis_history_smoothed/ \
  --smoother modal_recency --window 14
```

### Step 1.2 — change `MacroSnapshot.determine_regime` to emit smoothed regime

**Decision point:** do you want the **raw** regime persisted (for A/B
provenance) and a **smoothed** regime emitted as `macro_regime`?

Recommended payload shape (forward-compat, no schema bump):

```python
# cis_v4_engine.py MacroSnapshot.determine_regime():
#
# CURRENT:
#   snapshot["macro_regime"] = raw_classification(...)
#
# NEW:
#   snapshot["macro_regime_raw"] = raw_classification(...)
#   snapshot["macro_regime"] = smoothed_classification(
#       snapshot["macro_regime_raw"],
#       history=smoothed_history_for_date,
#       window=14,
#       algorithm="modal_recency",
#   )
```

`history` should be the running array of `macro_regime_raw` from
existing per-day CIS JSON files in `cis_history/` — load them lazily
at engine init, keep an in-memory buffer of (date_str, regime_raw).

`smoothed_classification` should call
`scripts/regime_smoother.smoothed_regime_series` with `window=14` and
return the modal regime for today. The H1.5 robustness check
confirmed modal_recency is the safest pick.

### Step 1.3 — verify locally before push

```bash
# Diff before vs after for a sample window
python3 -c "
import json, glob
for f in sorted(glob.glob('/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/cis_*.json'))[-30:]:
    d = json.load(open(f))
    raw = d.get('macro_regime_raw', '<absent>')
    smoothed = d.get('macro_regime', '<absent>')
    print(f'{f[-15:-5]}: raw={raw:<12} smoothed={smoothed:<12}')
"
# Expect: regimes now change LESS often (smoothed runs are ≥14d)
```

### Step 1.4 — push + restart cis_scheduler

```bash
# Stop the running scheduler
launchctl unload ~/Library/LaunchAgents/com.cometcloud.cis_scheduler.plist
# OR (if running via cron)
ps aux | grep cis_scheduler | grep -v grep | awk '{print $2}' | xargs kill

# Verify it's down
ps aux | grep cis_scheduler | grep -v grep

# Restart (depends on your launchd setup)
launchctl load ~/Library/LaunchAgents/com.cometcloud.cis_scheduler.plist
```

Watch the logs for ~30 min to confirm pushes include `macro_regime_raw`
and `macro_regime` is now stable across days.

---

## What Seth (Railway) needs to do (after Minimax ships Step 1.4)

### Step 2.1 — update CIS push contract documentation

Per CLAUDE.md rule 4: "All schema changes MUST be documented in
MINIMAX_SYNC.md §2 BEFORE code changes." The new
`macro_regime_raw` field is a schema addition.

Add to `MINIMAX_SYNC.md §2` (CIS Push Interface Contract):

```
SCHEMA v1.1 (planned 2026-07-0X):
  - ADDED: macro_regime_raw  (string) — original regime classification
    from MacroSnapshot.determine_regime(), before smoothing. Same enum
    as macro_regime. Available for A/B provenance + Minimax-B H3 conviction
    re-derivation. Optional in older payloads (missing → no A/B possible).
  - macro_regime semantics UNCHANGED — still one of {Goldilocks, Risk-On,
    Easing, Neutral, Tightening, Risk-Off, Stagflation}.
  - Bumped SCHEMA_VERSION from "1.0" to "1.1" in /internal/cis-scores POST.
```

Then **bump SCHEMA_VERSION** in `src/api/contracts/cis_push.py`:

```python
SCHEMA_VERSION = "1.1"  # was "1.0"
```

### Step 2.2 — update `cis_push.py` normalizer

In `src/api/contracts/cis_push.py::normalize_cis_payload()`, add a
defensive branch for the new field:

```python
# Macro regime: preserve both raw and smoothed if present
if "macro_regime_raw" in payload:
    normalized["macro_regime_raw"] = payload["macro_regime_raw"]
# `macro_regime` is unchanged — already handled
```

The normalizer logs drift loudly — verify it shows zero drift on the
first post-deploy push.

### Step 2.3 — verify production CIS pulls smooth

After Mac deploys + Railway deploys + restart cis_scheduler, watch
the next 24h of pushes:

```bash
# In Railway logs, look for:
grep -i "macro_regime_raw\|schema_version" /var/log/railway/cis*.log | tail -50

# On Mac, verify the pushed payloads contain both fields
python3 -c "
import json, requests
r = requests.get('https://web-production-0cdf76.up.railway.app/api/v1/cis/universe')
d = r.json()
for asset in d.get('assets', [])[:5]:
    print(f'{asset[\"symbol\"]:<6} macro={asset.get(\"macro_regime\"):<12} '
          f'raw={asset.get(\"macro_regime_raw\", \"<absent>\"):<12}')
"
# Expect: macro ≠ raw sometimes (regime smoothing); some assets show
# different macro vs the prior day's raw
```

### Step 2.4 — verify production matches A/B test

The A/B test (`reports/H2_PHASE1_SHIP_READINESS_5DIR_NAUTILUS_2026-07-06.md`)
predicted IS +18% PnL for modal_recency vs raw. After Phase 1 ships, the
production Nautilus LS v1 paper-trade (if running) should:

1. Show regime-change triggers firing **less often** (median regime length
   should jump from ~4d to ~14d+).
2. Show **slightly more trades** in paper trade logs (gate stops blocking
   on noisy 1-3 day regime flips).
3. Show **similar OOS PnL** in any rolling 2-month OOS window (per the
   A/B: $39.55 smoothed vs $39.92 raw — within $0.50).

If any of these is wrong, see Step 4 — emergency rollback.

---

## What Jazz needs to do (after Seth ships Step 2)

### Step 3.1 — coordinated git push

Per CLAUDE.md standard deploy workflow:

```bash
# Mac-side (or commit from sandbox and let Jazz push):
git add src/api/contracts/cis_push.py \
        MINIMAX_SYNC.md \
        docs/H2_PHASE1_SHIP_RUNBOOK_2026-07-06.md
git commit -m "feat(cis): H2 phase 1 — smoothed regime labels in payload

- src/api/contracts/cis_push.py: SCHEMA_VERSION 1.0 → 1.1, normalizer
  accepts new optional macro_regime_raw field
- MINIMAX_SYNC §2: documented schema bump
- docs/H2_PHASE1_SHIP_RUNBOOK_2026-07-06.md: end-to-end checklist

Cross-evidence convergence (H1.5 robustness + H2 sweep +
rebalance_engine v4 A/B + 5-dir × Nautilus A/B) clears the ship gate.
Per-regime floors UNCHANGED. Production logic UNCHANGED."

git push origin main
# Railway auto-deploys on push
```

### Step 3.2 — verify Railway deploy succeeded

Watch Railway logs for:

```
[deploy] H2 Phase 1 — smoothed regime labels in payload
[deploy] SCHEMA_VERSION=1.1
```

Check `GET /internal/cis-scores/schema` returns version "1.1".

### Step 3.3 — 24h monitor

Watch for:

1. **Drift log noise**: `normalize_cis_payload` should log zero drift on
   Mac's next push (assuming Mac also shipped the field).
2. **Production CIS feed**: 84 assets, regime attribution should shift
   toward the smoothed distribution (median regime length ≥14d).
3. **Paper-trade results**: Nautilus LS v1 paper trades should fire
   slightly more often (per A/B prediction).

---

## Emergency rollback (any time, ≤30 min)

If anything goes wrong — drift, schema mismatch, paper-trade blow-up —
the rollback is just reverting the Railway deploy:

```bash
# Find the previous Railway deploy SHA
railway logs --deployment | head -20
# Revert
git revert HEAD~1  # the Phase 1 commit
git push origin main
# Railway auto-redeploys
# Mac side: revert MacroSnapshot.determine_regime() to raw (one-line)
```

This brings the system back to raw regime labels in ≤30 minutes.
**No data loss** — the smoothed regime is additive (new field), not
destructive.

---

## Done-when checklist

Phase 1 is shipped when ALL of the following are true:

- [ ] Mac: `MacroSnapshot.determine_regime` emits `macro_regime_raw` + smoothed `macro_regime`
- [ ] Mac: cis_scheduler restarted, ≥1 push verified to include both fields
- [ ] Railway: `SCHEMA_VERSION = "1.1"` in cis_push.py, deployed via `git push`
- [ ] Railway: normalizer accepts new field without drift logs
- [ ] Production: 24h of pushes have both fields populated, no drift
- [ ] Production: regime attribution median length ≥14d (was ~4d)
- [ ] Paper trade: regime-change triggers fire ≤50% as often (per rebalance_engine v4 A/B pattern)
- [ ] Paper trade: trade count slightly up, PnL similar (per 5-dir × Nautilus A/B prediction)
- [ ] Jazz: signed off in MINIMAX_SYNC.md (new entry under §SYNC)

---

## What's NOT in Phase 1 (and stays open)

| Phase | What | Why deferred |
|---|---|---|
| Phase 2 | H2 magnitude flip per regime | Needs ≥6mo OOS data + ≥100 trades/regime; current 10.5mo window is single-regime biased |
| §CIS-HISTORY-BACKFILL | Reconstruct 14mo back (2024-03 → 2025-05) | Different problem (data infrastructure), owned by Minimax-A per MINIMAX_SYNC §CIS-HISTORY-BACKFILL |
| H3 conviction-weighted | Already prototyped as gate-multiplier, NEGATIVE result (floor band too tight) | Pivot to H3.2 sizing-multiplier, deferred to Phase 2 |
| CoreBasketV6 5-dir A/B | Cross-strategy Phase 1 validation | Owned by Minimax-C, same 4 smoothed dirs |

---

## Citations

- H2 sweep: `reports/H2_FLOOR_CALIBRATION_2026-07-06.md`
- Phase 1 ship-readiness A/B: `reports/H2_PHASE1_SHIP_READINESS_5DIR_NAUTILUS_2026-07-06.md`
- H3 prototype (negative): `reports/H3_CONVICTION_WEIGHTED_GATE_2026-07-06.md`
- H2 design: `docs/H2_REGIME_GATE_DESIGN_2026-07-06.md`
- H1.5 robustness: `docs/H2_H15_ROBUSTNESS_2026-07-06.md`
- Phase 1 PRD: `docs/H2_PHASE1_EASING_DROP_2026-07-06.md`
- Smoother impl: `scripts/regime_smoother.py` (Minimax-C)
- CIS push contract: `src/api/contracts/cis_push.py` (Seth)
- Mac engine: `cometcloud-local/cis_v4_engine.py` (Minimax-A)
- §CIS-HISTORY-BACKFILL: `MINIMAX_SYNC.md` line 2051 (Minimax-C, P1)