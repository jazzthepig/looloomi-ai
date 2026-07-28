# Regime Fingerprint Spec — M-WO-7.1 (VDB 做多)

**Status:** Draft v0.1 (2026-07-28)
**Lane:** Seth (design-first per M-WO-7.5 model)
**Author:** Seth
**Audience:** Jazz (sign-off) + Minimax (cross-lane read after sign-off)
**Supersedes:** None — greenfield build

---

## 1. North star (why)

Per Jazz 2026-07-28:

> "现在策略开发方向跟我们之前升级过的讨论根本没有在一条线上。策略都是简单因子和特征不断重复，而不是利用好我们vdb做风格辨识和运用的。"

**The goal of this build is not another sleeve.** It's the retrieval layer that answers:

> "今天的 regime 在 11yr 历史里最像哪 5 天？那 5 天的 R77-style 真 edge 是多少？"

One vector query, no factor loop. The next sizing call is anchored to **structural prior** — what the universe of regimes says happened next, not a hand-picked feature in a single backtest.

**Why now (vs the M-WO-7 lineup).** M-WO-7 has 6 ordered slices (§PROJECT_STATE 2026-07-27 building log):

1. regime fingerprints → pgvector (phase retrieval) — **this spec**
2. strategy records durable (R74 SETTLED)
3. outcome-distribution vectors (§P1 geometric)
4. TS-window shapelets
5. Entity/Decision space (design-first with Seth — covered by `ENTITY_DECISION_SPACE.md` 2026-07-27)
6. Text-RAG

The regime fingerprint build is **slice 1** because every later slice (3-6) needs a regime anchor to attach to.

---

## 2. What problem this unlocks (concretely)

### 2.1 The recurring graveyard we've just seen

R46→R97 (15 attempts). All REFUTED on the 731-day panel. The structural finding (PROJECT_STATE 2026-07-27 §STRATEGY-2 — 6 attempts all REFUTED, 10 attempts all REFUTED, 12 attempts all REFUTED):

```
on a bear-dominated panel, ANY single-strategy shape that
samples randomly across regimes fails the 3-check because
the regimes don't share the same forward distribution
```

### 2.2 What fails without regime anchor

Sleeves see the average alpha of a heterogeneous regime bag:
- Win rate looks OK
- 5-day rebal looks neutral
- The W5 fragility window undoes everything

### 2.3 What becomes possible with regime anchor

Each candidate sleeve is **conditional** on a regime fingerprint match:

```
candidate_sleeve.conditional_alpha = AVG[R77-like-alpha |
  match_regime_fingerprint(candidate_sleeve.regime_context) > θ]
```

The M-WO-1 episode-count gate (≥8 OOS clusters under gap>7d discipline) is **automatically satisfied** because 11yr × daily regime samples ≫ 8 (PROJECT_STATE line 12 explicitly listed VDB-derived episode structure as an alternative to §OHLCV-EXTENSION).

---

## 3. The 12-dim feature vector — feature by feature (PIT-safe)

**One row per trade_date.** `regime_fingerprints.regime_fingerprint(t)` is a 12-dim vector with the following semantic axes:

| Dim | Name | Type | Range | Source (validated) | PIT contract |
|---:|:---|:---|:---|:---|:---|
| [0] | macro_regime_one_hot | categorical | 1-of-7 | `cis_provider.canonical_regime()` UPPER_SNAKE | reads today's `macro_regime` field — strictly ≤ t |
| [1] | vol_regime_tercile | ordinal | {0,1,2} | `regime_vol_stratification.vol_regime()` 30d BTC PIT realized-vol | reads ≤ t-1 close (30d window) |
| [2] | pillar_f_ic_30d_z | z-score | [-3,3] | `cis_quality_absorption` per-pillar IC rolling 30d | reads ≤ t-1 panel |
| [3] | pillar_m_ic_30d_z | z-score | [-3,3] | same | same |
| [4] | pillar_o_ic_30d_z | z-score | [-3,3] | same — **pillar_O is a sparse anomaly detector** (Jazz 2026-07-28); this dim will be NaN on most days, only non-NaN when anomalies are firing | same |
| [5] | pillar_s_ic_30d_z | z-score | [-3,3] | same | same |
| [6] | pillar_a_ic_30d_z | z-score | [-3,3] | same | same |
| [7] | so_pulse_4h_mean_abs_delta | sum | [0,2] | `r75_hourly_so_quintile.normalize_hourly_history()` over last 24h | reads ≤ t-1h |
| [8] | detector_fire_rate_30d | ratio | [0,1] | `r62_fragility_gated_funding` 30d detector fire-rate (cross_class_crowded_count, btc_funding_level, btc_funding_acceleration ∈ R) | reads ≤ t-1d |
| [9] | funding_residual_W5_lift_tstat | t-stat | [-3,5] | `r76_funding_residual_ls` W5-window accum t-stat | reads ≤ t-1d |
| [10] | pillar_a_trajectory_30d_slope_z | z | [-2,2] | M-WO-2 EXTENDED per-cycle IC + Δpillar_A rolling | reads ≤ t-1d |
| [11] | cross_class_centroid_drift_30d | length | [0,1] | `asset_embeddings.match_asset_embeddings()` centroid drift over rolling 30d | reads ≤ t-1d |

**Critical invariant — I1 (NaN-honesty).** Per VECTOR_SCHEMA_SPEC §0 (already enforced in asset v2):
- Any dim where the source is absent or the source module returns NaN → fingerprint dim = NaN
- `vec vector(12)` (dense core, pgvector, no NaN inside): takes the row's **non-NaN** subset, re-normalized by length
- `vec_full JSONB` (full NaN-aware, 12 sparse entries): always populated, NaN → null on write, restore on read
- `cosine_similarity` skips shared-NaN dims pairwise; refuses below `MIN_SHARED_DIMS = 4` (same rule as asset v2 — preserves learned tolerance)
- **Exactly one rule**, three storage categories — same §STORAGE-LAW as asset v2 (RULE: dense+many → pgvector; sparse+few → JSONB + NaN-aware Python cosine). Regime fingerprint is 12 dims × ~3000 dates = 36k cells, fits the dense+many path with sparse JSONB safety net.

### 3.1 Why these 12 dims, not 8, not 20

- **8 was too thin** to differentiate regime context more granularly than the 7 macro regimes (no win).
- **20 was too dense** with overlap between dim [10] pillar_a_trajectory and dim [6] pillar_a_ic — orthogonal or redundant dims are exactly the failure mode of "feature lattice."
- **12 = 3 macro + 5 pillar+IC + 1 micro-pulse + 1 fire-rate + 1 perp + 1 trajectory + 1 context**, evenly distributed across validated operator families. Each dim has **at least one §DATA-ALIGN / §VECTOR_SCHEMA_SPEC citation** tying it to validated code.

---

## 4. Schema (Supabase, pgvector)

```sql
-- scripts/supabase_regime_fingerprints.sql (idempotent)
-- precondition: pgvector extension already enabled (asset_embeddings uses it)

CREATE TABLE IF NOT EXISTS regime_fingerprints (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL UNIQUE,
    canonical_regime TEXT NOT NULL,                -- T1/T2 aligned UPPER_SNAKE
    vec vector(12),                                -- dense cosine core (no NaN)
    vec_full JSONB NOT NULL,                       -- 12 entries, NaN→null
    schema_version INT NOT NULL DEFAULT 3,
    -- OUTCOME LABEL: realized R77-style 5d forward β-adj alpha_pct
    r77_fwd_5d_alpha_pct REAL,                     -- populated when rebal date lands
    r77_oos_window_start DATE,                     -- last 30% OOS window that this row backs
    r77_oos_window_end DATE,
    computed_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS regime_fingerprints_vec_hnsw_idx
    ON regime_fingerprints USING hnsw (vec vector_cosine_ops);

CREATE INDEX IF NOT EXISTS regime_fingerprints_date_idx
    ON regime_fingerprints (trade_date DESC);

CREATE INDEX IF NOT EXISTS regime_fingerprints_regime_idx
    ON regime_fingerprints (canonical_regime);

-- RPC: nearest-k regime analogs with realized R77 outcome
CREATE OR REPLACE FUNCTION match_regime_fingerprints(
    p_target vector(12),
    p_k INT DEFAULT 5,
    p_regime_filter TEXT DEFAULT NULL,
    p_min_r77_alpha_pct REAL DEFAULT NULL
) RETURNS TABLE (
    trade_date DATE,
    canonical_regime TEXT,
    vec_dist FLOAT,
    r77_fwd_5d_alpha_pct REAL,
    n_shared_dims INT
) AS $$
    WITH ranked AS (
        SELECT
            r.trade_date,
            r.canonical_regime,
            (r.vec <=> p_target)::FLOAT AS vec_dist,
            r.r77_fwd_5d_alpha_pct,
            r.vec_full,
            p_target AS target_full
        FROM regime_fingerprints r
        WHERE
            (p_regime_filter IS NULL OR r.canonical_regime = p_regime_filter)
            AND (p_min_r77_alpha_pct IS NULL
                 OR r.r77_fwd_5d_alpha_pct >= p_min_r77_alpha_pct)
    )
    SELECT
        trade_date,
        canonical_regime,
        vec_dist,
        r77_fwd_5d_alpha_pct,
        -- shared-dim count: dimensions where neither row has NaN
        (
            SELECT COUNT(*)::INT FROM jsonb_each_text(ranked.vec_full) f1
            WHERE f1.value IS NOT NULL
              AND jsonb_typeof(jsonb_extract_path(ranked.target_full, f1.key))
                  NOT IN ('null')
        ) AS n_shared_dims
    FROM ranked
    ORDER BY vec_dist ASC
    LIMIT p_k;
$$ LANGUAGE SQL STABLE;
```

**Read-side correctness invariants:**
- `p_target` is provided by the API route (computed from today’s regime state).
- `vec <=>` is pgvector's cosine distance — same metric as `match_asset_embeddings`.
- `n_shared_dims` is surfaced so the consumer knows whether the match is on 12 dims, 4 dims, or whatever subset has data — NaN-boundary preserved at the API too.
- `r77_fwd_5d_alpha_pct` may be NULL for very recent dates (5d forward not yet realized) — consumer decides how to handle NULLs (omit, group separately, weight by data-availability).

---

## 5. Compute path (the build module)

**Module:** `src/research/vector/regime_fingerprints.py` (PIT-safe compute + upsert)

```
class RegimeFingerprintBuilder:
    def __init__(self, conn):  # accepts Supabase client OR psycopg2
        self.conn = conn

    def compute_row(self, trade_date: pd.Timestamp) -> dict:
        # 12 dims, each calls into the cited validated module
        # NaN-honest per dim (I1) — never fabricate 0
        # Returns dict {trade_date, canonical_regime, vec (list[12]),
        #               vec_full (dict[12]), r77_outcome (or None)}

    def write_row(self, row: dict) -> None:
        # vec_full: JSONB with NaN → null via existing `_null_to_nan` helper
        # vec: dense core = re-normalize over non-NaN dims
        # r77_fwd_5d_alpha_pct = read-only reference, never recomputed here
        # UPSERT on trade_date (idempotent)

    def backfill(self, start_date, end_date):
        # Walks 11yr panel, calls write_row for each trade_date
        # Idempotent on re-run
```

**Backfill data sources** (all on disk):
- 11yr CIS: `_data/cis_historical/cis_historical_11yr.csv` (75,478 rows)
- 11yr OHLCV: `/tmp/cometcloud_data/ohlcv_11yr.db` (88,794 rows, TIER-I 20 syms)
- R77 paper NAV: needs `supabase.fusion_paper_nav` (live) — backfill label can be `None` if not present
- All other validated module outputs: read directly from the source script's deterministic function

---

## 6. The test suite (smoke + invariants)

`src/research/vector/tests/test_regime_fingerprints_smoke.py`

Tests (all must pass):
1. **I1 NaN honesty**: when source module returns NaN for dim [4], `vec_full["pillar_o_ic_30d_z"]` is null, dense `vec` only renormalizes over the other 11 dims.
2. **PIT safety**: `compute_row(t)` never reads anything > t.
3. **Cosine on shared dims**: a 12-dim `vec_a` with NaN on [3] matches a `vec_b` with NaN on [5] using only the 10 shared dims.
4. **MIN_SHARED_DIMS gate**: two rows sharing only 3 non-NaN dims → match refused (no false neighbor).
5. **Refuse asymmetry**: `similarity(a, b) == similarity(b, a)` (commutativity).
6. **Schema version locked**: write/read round-trip preserves `schema_version = 3`.
7. **Idempotent backfill**: re-running the same `backfill()` call yields the same rows (uniqueness of `trade_date`).
8. **`match_regime_fingerprints` SQL dry-run**: synth 12-dim target + 10-row seed → 5 nearest returned, ordered by cosine distance ascending, `n_shared_dims` matches what we wrote.

Total target: 8 tests.

---

## 7. Compliance boundary (the unavoidable fence)

**Investor-facing surfaces stay untouched.** This spec only exposes:
- `GET /api/v1/research/regime-analog?as_of=YYYY-MM-DD&k=5` — research-namespace endpoint, returns 5 nearest regime analogs with `r77_fwd_5d_alpha_pct` outcome label
- No CIS score, grade, signal, weight, or grade-threshold touched
- All positioning language is compliant (OUTPERFORM/NEUTRAL/UNDERPERFORM only — never BUY/SELL)

---

## 8. What this does NOT do (explicit non-goals)

These belong in **later M-WO-7 slices**, not this one:

| Excluded from this spec | Why | Where it belongs |
|---|---|---|
| Strategy records → pgvector migration | `strategy_store.py` already durable (Postgres jsonb, R74 settled) | Already built |
| Outcome-distribution vectors (§P1 geometric) | needs §P1 paper book to be stable | M-WO-7 slice 3 |
| TS-window shapelets | needs sub-cycle alignment | M-WO-7 slice 4 |
| Entity/Decision space propagation | separate design-first spec | `ENTITY_DECISION_SPACE.md` 2026-07-27 |
| Text-RAG (news/policy embeddings) | needs ingestion pipeline | M-WO-7 slice 6 |
| Frozen-cell reweight (R77 weights) | **DOES NOT** touch R77 — fingerprint only READS from R77 outcome | out of scope for any M-WO-7 |

---

## 9. Build sequence (after sign-off)

1. **Mac-side commit prep (Seth sandbox, ~30m)**: write `regime_fingerprints.py` + smoke + SQL
2. **Mac commit + push (Jazz/Mac, ~5m)**
3. **Mac-side schema deploy (Minimax, ~10m)** — `select refresh_signal_track_record()` equivalent for new table; SUPABASE_SERVICE_KEY required on Mac
4. **Backfill 11yr panel (Seth, ~30m)** — walks 3000 rows
5. **Surface live `GET /api/v1/research/regime-analog` (Seth, ~30m)** — Railway preflight + endpoint
6. **First retrieval test (Seth)**: query "2024-03-01" (mid-RISK_ON 2024 bull), get 5 analogs, verify structural coherence with known good/bad days
7. **First §DIRECTIVE-M-WO-1 proof (Seth)**: query today's fingerprint → top-5 analogs → among those 5 (or 10) days, the gap>7d cluster count = ?: if ≥8 → §DIRECTIVE ≥8 floor satisfied for **R77 forward-commit deck** automatically

---

## 10. Open questions for Jazz

1. **Outcome column `r77_fwd_5d_alpha_pct`** — keep it R77-only, or generalize to R62 / R76 outcomes too? (Each adds columns; we have one forward declared book.)
2. **Horizon** — 5d (matches R77 rebal cadence) vs 1d (matches R75 daily-roll) vs both? One column per horizon, or a unified scaled label?
3. **Re-density of dense `vec`** — when 12-dim drops to 4-dim (pillar O + 3 others NaN), should we still write a row, or skip? (Spec defaults to: still write, MIN_SHARED_DIMS gate is on read, not write.)
4. **Backfill depth** — 11yr × daily = 3000 rows (well within pgvector HNSW scale). Deeper if `cis_scores` table reaches back further?
5. **First-iteration readout** — do you want a 1-pager showing "today's 5 nearest regimes and their realized R77 outcome" as the deliverable artifact, or just the API + table live?

---

## 11. Files this spec produces (when code-authorized)

**New files (Seth sandbox):**
- `src/research/vector/regime_fingerprints.py` (~280 LoC)
- `src/research/vector/tests/test_regime_fingerprints_smoke.py` (~150 LoC, 8 tests)
- `scripts/supabase_regime_fingerprints.sql` (~70 LoC, idempotent)

**Modified files (Seth sandbox):**
- `REFUTATION_LEDGER.md` — append §M-WO-7.1 entry
- `MEMORY.md` — add regime fingerprint one-liner
- `PROJECT_STATE.md` — header update + building log entry
- `MINIMAX_SYNC.md` — §M-WO-7.1 cross-lane read
- `STRATEGY_PLAYBOOK.md` — note that R77 forward-commit deck can re-frame on the new evidence

**Zero changes to:** `src/api/contracts/cis_push.py`, Shadow/, Mac Mini engine, any CIS weight, any frontend module, any investor endpoint.

---

End of spec. Awaiting Jazz sign-off to proceed to code.

🎯
