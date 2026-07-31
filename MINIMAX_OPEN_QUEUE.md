# MINIMAX_OPEN_QUEUE — 2026-07-26 Monday standup prep

> **One-page summary of every open §X in MINIMAX_SYNC by lane.** Refreshed
> 2026-07-26. Source: latest entries in `MINIMAX_SYNC.md` (search for
> `2026-07-26` for fresh resolution statements).
>
> **Read time: ~3 minutes.** Below is the queue to triage for Monday.
> Production-side (Seth) is **READY on every P0**; the remaining items are
> supply-side (Mac / ingestion).

---

## 🔴 P0 — single Mac-side unblocker for the production push

| § | Title | Lane | ETA | Notes |
|---|---|---|---|---|
| §OUTCOMES-STALE | Price feed (`ohlcv_daily`) frozen at 2026-06-19 (~37d). signal_outcomes trails at 2026-05-03 (~80d). | **Minimax-A (cron / scheduler)** | Same-day | Diagnose why `ohlcv_daily` stopped at 2026-06-19. Backfill 2026-06-19 → today (prefer exchange-native: Binance via CCXT for crypto, EODHD for TradFi). Confirm the live `signal_outcomes` writer is running at all — it stops 2026-05-03, EARLIER than ohlcv, so it may have a SECOND independent failure. Once fresh, `refresh_signal_track_record()` runs and the §BETA-METRIC-AGG ship gate opens automatically. |

---

## 🟡 P1 — Mac-side follow-ups (production push lands regardless)

| § | Title | Lane | ETA | Notes |
|---|---|---|---|---|
| §REGIME-ALIGN ① | T1 engine stalled at 2026-07-19 14:54 UTC ⇒ null pillars. Same family as §OHLCV-DEAD. | **Minimax-A (T1 engine restart)** | Same-day | `cis_v4_engine.py` → `cis_scheduler.py` → `cis_push.py` chain. Restart + backfill pillars 07-19 → now. |
| §REGIME-ALIGN ③ | Find where "UNKNOWN" originates in T1 push (likely failed macro fetch). Map to NEUTRAL at source. | **Minimax-A (T1 engine)** | Same-day | T1 must keep emitting canonical 7 UPPER_SNAKE labels per the Seth-side `canonical_regime()` contract. |
| §BETA-METRIC 2026-07-21 | Live `signal_outcomes` writer β-population. | **Minimax-A (writer)** | Same-day | Mirror `beta_adjust.py` semantics EXACTLY in the writer (PIT expanding-window, min 20 priors, NEVER default β=1.0). |
| §VDB 2026-07-23 #1 | Mac-side asset-vector push → pgvector. | **Minimax-A (T1 engine)** | This week | `pgvector_store.upsert_embeddings` contract: `vec` = first-18 finite core, `vec_full` = full v2 with null for NaN. |
| §VDB 2026-07-26 | Run `migrate_redis_to_postgres()` once at deploy time. | **Minimax-A (deploy)** | This week | Seth-side code + migration ready (see `scripts/supabase_strategy_records.sql`). Safe to re-run (idempotent). |
| §VDB 2026-07-26 | Schedule `STRATEGY_RECORDS_DUAL_WRITE=0` flip after one full cycle. | **Minimax-A (deploy)** | Next deploy | Currently default ON. Safe to flip after verifying Postgres count ≥ Redis count. |

---

## 🟢 P2 — research-side (does not block production push)

| § | Title | Lane | ETA | Notes |
|---|---|---|---|---|
| §PIT-LEAK-C | Re-run research interpretation_c on the fixed (PIT-safe) `regime_score_c`. | **Minimax-A (research)** | This week | Seth-side production is PIT-LEAK-CLEAN. The research re-run is to confirm the original pooled-book conclusion still holds on PIT-clean normalization. |
| §DATA-ALIGN 2026-07-23 | Header alignment + A pillar reconstruction + β-adj in `cis_historical_11yr.csv`. | **Minimax-A (data)** | This week | P0 for the long-lens mining spec (per-year sign-stability, vol-regime × macro redo, per-asset-class). |
| §DATA-ALIGN 2026-07-23 B | Land §CIS-HISTORY-BACKFILL (2024-03→2025-05, F/M/O/S/A) into Supabase. | **Minimax-A (data)** | This week | Single dataset unblocks S-77/78/79 multi-cycle re-run. |
| §PIT-LEAK-C | (Same as above — duplicated for clarity.) | | | |

---

## ✅ RESOLVED on Seth-side (what's already shipped, waiting on Mac confirmation/use)

| § | Resolution | Status | Mac-side action |
|---|---|---|---|
| §BETA-METRIC-AGG | Code + migration + 16/16 smoke tests. Ship gate auto-blocks β-ADJ publish on stale ohlcv_daily. | **READY** | Restart `signal_outcomes` writer (per §OUTCOMES-STALE). |
| §VDB (strategy vectors) | `scripts/supabase_strategy_records.sql` + `src/data/vector/strategy_store.py` rewrite + 7/7 tests. NaN boundary preserved. | **READY** | Run `migrate_redis_to_postgres()` at deploy (above). |
| §REGIME-ALIGN ② | `cis_provider.canonical_regime()` normalizes stored macro_regime to UPPER_SNAKE on read; T2 fallback output now agrees with T1's format. | **READY** | Confirm T1 enforces the canonical 7; map UNKNOWN → NEUTRAL at source. |
| §FEEDS-RESILIENCE | EODHD primary (TradFi) + Hyperliquid fallback (crypto) live. Loud zero-write warning + 2 new `loop_health` stages. | **DONE** | (Optional) restore CG as primary crypto source when quota refreshes. |
| §OHLCV-DEAD (data completeness) | T2 fallback now persists pillars (shape-tolerant). The "stuck at 07-19 14:54" symptom does not reproduce; may have been transient. | **RECOVERED** | (Re-probe suggested; not blocking.) |
| §PIT-LEAK-C (production) | `_NORM_WIN = 252` trailing window in `regime_score_c`; production is PIT-clean. | **LANDED** | Re-run research on the fixed engine (P2). |

---

## The three-line summary for Monday standup

1. **Production push is code-complete and gated** — every P0 Seth-side item is shipped, tested, and preflight-green. §BETA-METRIC-AGG's ship gate auto-suppresses β-ADJ publish while ohlcv_daily is stale (no investor surface degrades).
2. **The single unblocker is `ohlcv_daily`** — restart the writer (cron / API key / scheduler) and backfill 2026-06-19 → today. Two-week-old `signal_outcomes` may have a second independent failure (older stall at 2026-05-03).
3. **Everything else is research-side** — §PIT-LEAK-C re-run, §DATA-ALIGN long-lens dataset, §VDB Mac-push routing. Not blocking production.

---

## 📡 §MINIMAX-A OBSERVATION — `cis_scores` pipeline health for the R75 maturity gate (2026-07-26)

> **Mac-side data observation only.** This is not a research claim; it is a status read of
> the `cis_scores` write cadence from `cis_scheduler.py` / `cis_push.py` so Seth's R75
> maturity gate has honest numbers to gate against. The R75 verdict itself is Seth's lane.

**Source.** `src/research/validation/r75_hourly_so_quintile.py` — diagnosed from Railway
`/api/v1/cis/history/{symbol}` payloads at run time `2026-07-26 13:09 UTC` (R75c→R75d gap of
**1.7 wall-clock hours**).

| Metric | 11:21 UTC (R75c) | **13:09 UTC (R75d)** | Δ |
|---|---|---|---|
| `latest_data_hour` | 2026-07-26T01:00 | 2026-07-26T12:00 | +11 h observed |
| `staleness_hours` | 1.3 | **1.2** | improving |
| Panel `valid_hours` (≥12 assets non-null) | 662 | **667** | **+5 in 1.7 wall-clock h** |
| `calendar_days` | 35.96 | **36.17** | +0.21 d |
| Null-pillar assets | 3 (BCH, ICP, WIF) | 3 (BCH, ICP, WIF) | unchanged |

**Verdict (Mac-side read).** Pipeline is **HEALTHY and ACCRUING**. Accrual rate observed
**+5 valid hours per 1.7 wall-clock h ≈ +2.94 h/h**. To clear R75's 720 h floor from current
**667**, we need **+53 more valid hours ≈ +18 wall-clock h at current rate**, i.e. gate
should clear by **~2026-07-27 07:00 UTC** if pipeline stays healthy.

**Why this matters for the production push.** R75 is the build-order #5 verification, not a
ship blocker. But the same data feed (`cis_scores`) powers the Railway T2 CIS engine; that
engine has been **stalled since 2026-07-19 14:54 UTC** per §REGIME-ALIGN ① (loudly visible in
the R75 panel as a 200-hour density hole in the calendar span). The R75 pipeline-health
observation is the cleanest external probe of the upstream state — no need to log into the
Mac Mini to know whether the engine is writing.

**Mac-side checks I did NOT make (out of lane):**
- I did NOT modify `cis_v4_engine.py` / `cis_scheduler.py` / `cis_push.py`. That's a separate
  restoral action if needed (see §REGIME-ALIGN ① above).
- I did NOT touch `src/research/validation/r75_hourly_so_quintile.py` (already Seth's; no
  change since 2026-07-23).
- I did NOT write to `REFUTATION_LEDGER.md` or `PROJECT_STATE.md` — those are Seth's lane.
  An earlier cross-lane write by me (R75d entries attributed to "Seth") has been rolled back
  to keep lane discipline clean.

**Handoff to Seth (your lane).** The 13:09 UTC `cis_scores` snapshot is on disk at the
gitignored outputs:
```
reports/r75_hourly_so_quintile/2026-07-26_rerun/{REPORT.md, verdict.json}
```
…with full per-cell sweep (`(pillar, Δ-h, reb-h, bps) → (stable_t, pos_t, neg_t, headline_sign_flip)`).
If R75d status belongs in `REFUTATION_LEDGER.md`, you (Seth) own that write — please do so
when you're back in your lane, since the lessons-on-headline-instability writeup is research-
synthesis work. The ledger entry this Minimax-A pass would have written is *deliberately
absent* from this commit; I will not sign Seth-attributed research notes.

— *Minimax-A, 2026-07-26 13:14 UTC.*

---

## 📡 §MINIMAX-A DIAGNOSTIC — Mac-side T1 engine fully stalled since 2026-07-19 23:21 (2026-07-26)

> **Root cause confirmed (not transient).** §REGIME-ALIGN ① is REAL.
> The Mac T1 engine has not run successfully since `cis_20260719_231346`
> completed at 23:21:26 on 2026-07-19. **Seven days of zero local writes** to
> `cis_history.db`, `cis_scores_*.json`, or `cis_scheduler.log`.
> The R75 observation above (+5 valid hours in 1.7 wall-clock h) was reading
> from **Supabase** via `src/api/store.py::supabase_get_history()` — the
> Railway-side T2 fallback engine. **That writer is alive and independent of
> the Mac T1 stall.**

### What I checked (all read-only, sandbox-safe)

| Probe | Result |
|---|---|
| `tail -50 cis_scheduler.log` | Last INFO line: `2026-07-19 23:21:26 \| CIS job completed: 43 assets in 460.4s`. After that, log file empty. |
| `MAX(timestamp) FROM cis_history` | **2026-07-19T23:20:55** (matches the stalled log line exactly) |
| `run_metadata ORDER BY rowid DESC LIMIT 5` | Last 5 runs are all 2026-07-19 or earlier — most recent is `cis_20260719_231346` |
| `cis_scores_*.json` mtimes | Latest = `cis_scores_20260719_2320.json` (Jul 19 23:20). Nothing since. |
| `pgrep -fl "cis_scheduler.py --run-once --full"` | rc=0, **no output** (canonical liveness check from `scripts/loop_health_monitor.py:96`) |
| `pgrep -fl cis_scheduler` | rc=0, **no output** (no in-flight scheduler process in any mode) |
| `crontab -l` | empty (no per-user cron entries) |
| `ls *.plist` (Mac-side) | no `com.cometcloud.*` launchd plists present |
| `loop_health.log` historical | **2026-07-15T11:53:58 \| WARN \| 1 failing: crontab** — the crontab-check was ALREADY failing 4 days before the stall |
| `shadow_sync.log` last entry | 2026-07-19 23:31:11 (same stall window) |
| `cis_history.db` file mtime | 2026-07-26 22:38 (misleading — no WAL exists; mtime is from a checkpoint/touch, NOT new data) |
| `cis_scheduler.py --help` | works (CLI healthy) |
| Wrapper script executable | yes (`-rwxr-xr-x`) |
| Wrapper invocation site | `scripts/run_cis_scheduler.sh:13` calls `cis_scheduler.py --run-once --full` |

### Root cause (smoking gun)

**The crontab entry that invokes `scripts/run_cis_scheduler.sh` every 30 min
went missing by 2026-07-15** (loop_health.log shows `crontab` failing then,
and the user-level `crontab -l` is empty today). Some other process kept the
scheduler alive through 2026-07-19 23:21 (likely a launchd-resident process
started before the cron entry was lost). **`ps aux` shows the root launchd
process started `19Jul26`** — i.e. the Mac rebooted on 2026-07-19. The reboot
killed the in-flight cis_scheduler process. With no crontab entry, nothing
restarted it after the reboot.

Net effect: a single missed cron entry + a routine reboot = 7-day silent stall
of the Mac-side T1 engine. The Railway T2 fallback is what kept the Supabase
pipeline (and therefore the R75 panel) alive.

### Mac-side unblock actions (lane-correct for Minimax-A, needs Jazz go-ahead)

I have NOT taken any of these — they're state-modifying actions on your Mac
that start a recurring scheduled task. The lane says I can modify
`/Volumes/CometCloudAI/cometcloud-local/`, but I won't start a scheduler
without explicit confirmation.

**Option A — restore the cron entry** (lowest-touch):

```bash
# Run on Mac side. Adds a single line to your user crontab.
(crontab -l 2>/dev/null; echo "*/30 * * * * /Volumes/CometCloudAI/cometcloud-local/scripts/run_cis_scheduler.sh >> /Volumes/CometCloudAI/cometcloud-local/_logs/cron.log 2>&1") | crontab -
```

**Option B — install a launchd plist** (more robust; survives missed cron
loads and reboots with `RunAtLoad`):

Write to `~/Library/LaunchAgents/com.cometcloud.cis_scheduler.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>          <string>com.cometcloud.cis_scheduler</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Volumes/CometCloudAI/cometcloud-local/venv/bin/python</string>
    <string>/Volumes/CometCloudAI/cometcloud-local/cis_scheduler.py</string>
    <string>--run-once</string>
    <string>--full</string>
  </array>
  <key>StartInterval</key>   <integer>1800</integer>
  <key>RunAtLoad</key>       <true/>
  <key>StandardOutPath</key> <string>/Volumes/CometCloudAI/cometcloud-local/_logs/cis_scheduler.log</string>
  <key>StandardErrorPath</key><string>/Volumes/CometCloudAI/cometcloud-local/_logs/cis_scheduler.err.log</string>
</dict>
</plist>
```
Then `launchctl load ~/Library/LaunchAgents/com.cometcloud.cis_scheduler.plist`.

**Option C — one-shot recovery + Option A**: run `cis_scheduler.py --run-once --full` once to backfill today's snapshot into the local DB, THEN install Option A so it stays running.

**My recommendation: Option C**. A single backfill is harmless (it appends the latest run, doesn't conflict with anything), and Option A is the lowest-touch restore of the original behavior.

### What the fix unblocks (cascade)

Once Mac T1 is running again:
- `cis_history.db` resumes appending → Railway `/internal/cis-scores` receives fresh T1 pushes → CIS universe leaderboard returns T1 scores (currently the engine badge flips to T2 amber).
- `loop_health.log` "crontab" check turns green → all 8/8 health stages pass.
- `ohlcv_daily` writer state (separate item §OUTCOMES-STALE) still needs its own investigation — that's `ohlcv_collector.py` not `cis_scheduler.py`. The cron failure above may have been the same root cause (a single lost crontab), but `ohlcv_collector.py` has its own schedule. Worth probing as a follow-up.
- `signal_outcomes` writer (also §OUTCOMES-STALE, frozen at 2026-05-03, 80 days stale) — separate cron entry, separate failure; not addressed by fixing the cis_scheduler cron.

### Mac-side checks I did NOT make (lane discipline)

- I did NOT modify `cis_scheduler.py`, `cis_v4_engine.py`, `cis_push.py`, or any other file in `/Volumes/CometCloudAI/cometcloud-local/`. The root cause is upstream of the code (lost scheduler invocation), so a code patch would mask the symptom, not fix it.
- I did NOT modify any Seth-lane file (`src/`, `dashboard/`, `REFUTATION_LEDGER.md`, `PROJECT_STATE.md`, `MEMORY.md`).
- I did NOT load any launchd plist or modify any crontab.

### Ask (one-liner)

> **Jazz — confirm Option A vs Option B vs Option C.** Option C is my rec.
> I will execute on Mac side once you say go.

— *Minimax-A, 2026-07-26 22:42 UTC.*

---

## 📡 §MINIMAX-A STATUS — T1 cron restore done; §OUTCOMES-STALE / §VDB / DUAL_WRITE need lane-cross or Railway-deploy (2026-07-26 22:55 UTC)

> **Honest status after "按顺序fix" sweep.** 1 of 4 tasks is fully resolved
> end-to-end. 1 is fully diagnosed with a clean lane-boundary answer. 2
> require explicit Jazz decisions before any further Mac-side code.

### ✅ Done — T1 engine cron restore + backfill (§REGIME-ALIGN ①)

| Step | Status | Evidence |
|---|---|---|
| 1. One-shot backfill `bash scripts/run_cis_scheduler.sh` | ✅ SUCCESS | `cis_history.db MAX(timestamp)` advanced from `2026-07-19T23:20:55` → `2026-07-26T22:51:47` (38 new rows, run_id `cis_20260726_224832`, 240.7s, exit 0). `cis_scheduler.log` resumed writing. Railway `/api/v1/cis/top` returning fresh t1_count. |
| 2. Recurring cron entry `*/30 * * * * /Volumes/CometCloudAI/cometcloud-local/scripts/run_cis_scheduler.sh` | ✅ INSTALLED | `crontab -l` confirms; cron daemon PID 209 running; `MAILTO=""` set to suppress output emails. Will fire every :00 and :30. |

**Note on launchd.** There IS a pre-existing launchd plist at
`~/Library/LaunchAgents/com.cometcloud.cis_scheduler.plist.DISABLED`
(modified 2026-06-24, stripped down to `RunAtLoad` only — no
`StartCalendarInterval` so it would fire ONCE on load and never again).
There's also `com.cometcloud.cis_scheduler.plist.bak.2026-06-20` which
is the FULL original with `StartCalendarInterval: Minute=0` + 30s
throttle. **The DISABLED → plist rename + load path was NOT taken** —
I added the cron entry instead, since the cron entry fires every 30
min and is functionally equivalent. If you want to migrate to launchd
instead of cron, the backup plist is ready to restore (lane-correct
Mac-side action, needs your call).

### ✅ Diagnosed — §OUTCOMES-STALE P0 (lane-boundary finding)

**Mac-side `ohlcv_collector.py`** (writes local Parquet, NOT Supabase):
- Last ran **2026-06-07** (~7 weeks ago)
- No cron entry / launchd plist drives it
- **Impact: research-side only** — `scripts/fetch_ohlcv_to_local.py` (manually
  triggered) covers the 58-symbol local SQLite buffer; it's fresh (per
  `src/research/data/README.md` "Coverage (as of 2026-07-26): 58/58").
- **Conclusion**: informational gap, not a blocker. Can be restored by
  adding a cron entry if you want; not urgent.

**Railway-side `ohlcv_daily` (Supabase, frozen 2026-06-19) + `signal_outcomes`
(frozen 2026-05-03)**:
- **No Mac-side writer exists** — `grep -rln "ohlcv_daily\|signal_outcomes"` in
  `/Volumes/CometCloudAI/` returns ZERO non-research results. Writers must be
  on Railway side.
- **This is OUT OF MINIMAX-A LANE.** Per CLAUDE.md ownership boundaries
  ("Seth/Austin only modify `src/`, `dashboard/`"), the Railway writers are
  Seth/Austin territory.
- **The §BETA-METRIC-AGG ship gate (Seth-side, READY)** auto-suppresses
  β-ADJ publish while ohlcv_daily is stale — so no investor-facing surface
  has degraded. The staleness is "data is missing" not "data is wrong".

**Recommended action**: ping Seth/Austin to diagnose the Railway-side
writers. Same lost-crontab root cause is plausible but unverified from
Mac.

### ⚠️ Cross-lane design needed — §VDB 2026-07-23 #1 (Mac-side asset-vector push to pgvector)

**Current state**: Railway-side `cis_provider.py:2541` dual-writes pgvector
via `pgvector_store.upsert_embeddings()`. **Mac-side `cis_scheduler.py`
does NOT push asset vectors.** That's the §VDB gap.

**Lane-bound constraint**: Mac engine cannot import Seth-side code
(`src/data/vector/embedder.py` + `pgvector_store.py` are not mirrored to
Mac — Shadow/cometcloud-local/ has no `vector/` subdir). Mac must ship
data via HTTP, NOT in-process call.

**Two design options (need your pick):**

- **Option A — Cross-lane (cleaner, more work)**: Mac-side helper builds
  the per-asset payload (pillars, deltas, stability, derivatives,
  edge_moments, regime) and POSTs to a new Railway endpoint, e.g.
  `POST /internal/asset-vectors`. Seth-side adds the endpoint that calls
  `generate_embedding` + `upsert_embeddings`. Per CLAUDE.md §4, the
  push-interface contract change must be documented in `MINIMAX_SYNC.md`
  §2 BEFORE code changes + bump `SCHEMA_VERSION`. **Estimated scope:**
  1 new Mac-side helper (~80 LoC), 1 new Railway endpoint (~30 LoC +
  tests), 1 §2 contract doc update.

- **Option B — Mac-direct via PostgREST (simpler, drift risk)**: Mirror
  `embedder.py` + `pgvector_store.py` to Mac engine at
  `/Volumes/CometCloudAI/cometcloud-local/vector/` (next to `cis_v4_engine.py`).
  Mac calls upsert_embeddings() directly against Supabase REST. **Risk:**
  every change to Seth-side embedder/pgvector needs Mac-side sync
  (drift-prone; Shadow sync already proved fragile). **Estimated scope:**
  2 file mirrors (~600 LoC) + Mac-side test (similar to
  `test_pgvector_store_smoke.py`).

**My recommendation**: Option A. Drift risk of Option B is exactly
what motivated the original 2026-07-23 spec — "implement against a
spec instead of against each other." A new internal endpoint honors
that.

### ⚠️ Railway-deploy only — STRATEGY_RECORDS_DUAL_WRITE=0 flip

**Verified**: `src/data/vector/strategy_store.py::_dual_write_enabled()`
returns `True` unless env var is `"0"|"false"|"False"`. Default is `"1"`
(ON).

**Verified**: `migrate_redis_to_postgres()` exists, idempotent, ready
to run at deploy time. SQL migration `scripts/supabase_strategy_records.sql`
is also idempotent.

**NOT verified from sandbox**: Postgres `strategy_records` row count vs
Redis count (Railway doesn't expose `/api/v1/strategy-vector/meta` —
endpoint returned "Not found" on curl probe). Needs Seth/Austin or Mac
CLI to run the comparison.

**Action**: Seth/Austin should, at next Railway deploy:
1. Run `migrate_redis_to_postgres()` once (idempotent).
2. Verify Postgres count >= Redis count (read both, compare).
3. Flip Railway env `STRATEGY_RECORDS_DUAL_WRITE=0`.
4. Re-deploy; subsequent cycles write to Postgres only.

This is a Railway env-var change, not Mac-side. Not actionable from
sandbox.

### Asks for Jazz (in priority order)

1. **§VDB 2026-07-23 #1**: Option A (cross-lane) vs Option B (Mac-direct)?
   I'll execute on receipt. Option A needs a §2 doc update + new Railway
   endpoint (Seth-side code), so it's the bigger commitment. Option B I
   can do start-to-finish on Mac-side alone.
2. **§OUTCOMES-STALE Railway-side**: confirm I should ping Seth/Austin,
   or wait for Monday standup?
3. **DUAL_WRITE flip**: confirm I should run `migrate_redis_to_postgres()`
   on Mac CLI next session + flip the Railway env (needs Seth-side deploy
   coordination)?
4. **Optional: Mac-side ohlcv_collector.py cron**: add `0 6 * * *`
   daily-restart entry? Not blocking; just closes a 7-week gap. Need
   explicit yes/no.
5. **Optional: re-enable launchd vs keep cron**: the backup plist
   (`com.cometcloud.cis_scheduler.plist.bak.2026-06-20`) is ready if you
   want to switch from cron to launchd (more robust across reboots).
   Otherwise cron entry stays.

— *Minimax-A, 2026-07-26 22:55 UTC.*

---

*Seth, 2026-07-26. Last appended by Minimax-A re T1 cron restore + cross-lane status.*

---

## §VDB 2026-07-27 (Minimax-A → Seth) — Option A picked, Mac-side payload ready, waiting on your endpoint

**Status: cross-lane half-done.** Per Jazz's "3 A" pick (2026-07-27):
- ✅ **Minimax-A done:** Mac-side `vector_push.py` written, contract documented in
  `MINIMAX_SYNC.md §2` (POST /internal/asset-vectors, canonical v1, schema_version "1.0").
  Dry-run verified 2026-07-27 12:18 UTC: 38/38 assets, 38/38 with prior_pillars + 7-row
  pillar_history, 3/38 with derivatives (BTC/ETH/SOL only — CG-tickers limitation,
  NaN-honest treatment in payload). Source data = `_data/cis_scores_latest.json` (the
  live CIS push snapshot the engine already writes) + cis_history.db (for v2 prior/history).
- ❌ **Seth needs to do:** build `/internal/asset-vectors` endpoint on Railway. Use the
  contract in `MINIMAX_SYNC.md §2` as the spec — schema_version validation, X-Internal-Token
  check, then the standard `generate_embedding(asset, macro_regime, derivatives_map,
  prior_pillars, pillar_history, edge_moments)` + `upsert_embeddings(embeddings,
  asset_meta, macro_regime, schema_version=2)` call. `edge_moments` is Mac-side
  data-not-available — pass None, Seth's existing separate loop fills the v2 [25..26] dims
  later (NaN-honest, I1 compliant).

**Mac-side hook NOT wired yet.** `vector_push.py` is standalone (`python3 vector_push.py
[--dry-run]`) per contract "No go-live signal yet. This contract is a draft until both
sides have built + dryrun + echo-tested." I will NOT touch `cis_scheduler.py` post-push
block until your endpoint is up + echo-tested.

**Mac-side verification (already done):**
```
$ python3 vector_push.py --dry-run
INFO live payload job_id=cis_20260727_115944, 38 assets, macro=RISK_ON
INFO v2 enrichment: 38/38 assets with prior, 38/38 with ≥3-obs history
INFO payload assembled: 38 assets, 38 with prior_pillars, 38 with pillar_history,
     macro=RISK_ON, schema=1.0
[full JSON payload printed to stdout]
```

**Lane-correct verification Seth should run (after endpoint ships):**
```
$ python3 vector_push.py            # not --dry-run
INFO POST /internal/asset-vectors → 200 OK: {"status":"ok","count":38,...}
```
Then on Railway: `SELECT COUNT(*) FROM asset_embeddings WHERE schema_version=2;`
should be 38 (or higher if you've run other paths). Then `SELECT symbol, dims,
vec_full IS NOT NULL FROM asset_embeddings ORDER BY updated_at DESC LIMIT 5;`
should show 27-dim full vectors.

**No go-live before echo test passes.** When your endpoint is up, send me the URL
+ a 1-asset dryrun, I'll mirror back from Mac-side. Then we wire the cis_scheduler
post-push hook together (Mac-side code change + 1-line addition to cis_scheduler.py).

— *Minimax-A, 2026-07-27 12:18 UTC.*

---

*Seth, 2026-07-26. Last appended by Minimax-A re T1 cron restore + cross-lane status.*

---

## §STRATEGY-RECORDS-MIGRATE 2026-07-27 (Minimax-A → Seth) — Mac-side state check done, Mac publishable key is 401; migration needs service_role OR your lane

**Per Jazz's "4.做" (2026-07-27):** do strategy_records migration + DUAL_WRITE flip prep on
Mac-side. **What I found and where I'm blocked:**

### ✅ Mac-side read-only state check (done 2026-07-27 12:25 UTC)

```
Redis records (load_all_records_redis_legacy):  0
Postgres count (_pg_count, Mac publishable key): -1  [HTTP 401 Unauthorized]
```

**Two facts:**
1. **Redis is empty** — `strategy:records` (legacy key) holds zero records. There's literally
   nothing in Redis to migrate. `migrate_redis_to_postgres()` would be a no-op (migrated_n=0).
2. **Mac publishable key (`sb_publishable_…`) gets 401** on the Supabase REST API for
   `strategy_records`. The RLS policy is the suspected culprit — `supabase_strategy_records.sql`
   doesn't GRANT to anon/authenticated, and the publishable key falls into anon. The Railway
   deploy uses the same key in its env, so **the same 401 likely blocks your live write path too**
   (worth checking — if the live upsert is silently failing, the DUAL_WRITE pattern isn't
   actually dual-writing right now).

### ❌ What I can't do from Mac-side

- **Can't run the migration**: my publishable key is 401. Service_role would work but I
  don't have it (and shouldn't — service_role bypasses RLS, ownership is yours).
- **Can't verify PG count**: same 401.
- **Can't flip `STRATEGY_RECORDS_DUAL_WRITE=0`**: that env var is on Railway, your lane.

### ✅ What you can do (Seth-side, ~5 min)

1. **Confirm the 401 is the same on Railway** by tailing a recent `/api/v1/strategy/...` write
   response (or your deploy log for `[StrategyStore] PG upsert failed: …`).
2. **Apply RLS / grants on the `strategy_records` table** so the publishable key can SELECT +
   INSERT + UPDATE. Two options:
   - **A (preferred, keep publishable key for app):** `grant select, insert, update on
     strategy_records to anon, authenticated;` + matching RLS policy `using (true) with
     check (true)`. Safe because strategy_records is NOT user-facing — it's our own
     research/paper-trading ledger.
   - **B (more conservative):** create a `service_role`-scoped REST key (Supabase dashboard
     → Settings → API), put it in Railway env as `SUPABASE_SERVICE_KEY`, change
     `strategy_store.py::_sb_url_key()` to prefer service_role for writes.
3. **Then** (Mac-side or yours): run `migrate_redis_to_postgres()` from a context that has
   the working key. Since Redis is empty, this is a no-op — but the call also exercises the
   upsert path, so it's a useful smoke test.
4. **Verify** `SELECT count(*) FROM strategy_records;` matches what your live deploy wrote
   (or 0 if no successful writes have ever happened).
5. **Flip `STRATEGY_RECORDS_DUAL_WRITE=0`** on Railway once you confirm PG is the durable
   source of truth. From that point on, the Redis path is retired; strategy_records lives in
   Postgres jsonb only.

### Lane-correct ask

I think the most valuable next move is **B above** (service_role key) because:
- It unblocks ALL future Seth-side writes to strategy_records (and any other Supabase table
  that needs server-side writes, like `signal_outcomes`).
- It's a one-time config; the publishable key stays for any anon-safe reads.
- Mac side stays out of credential land.

If you want A instead, ping me and I'll re-verify the migration can run from Mac with the
new grants. Either way, the **DUAL_WRITE=0 flip is your env-var change**, not mine.

— *Minimax-A, 2026-07-27 12:28 UTC.*

---

*Seth, 2026-07-26. Last appended by Minimax-A re T1 cron restore + cross-lane status.*
