-- ============================================================================
-- Regime Fingerprints (M-WO-7.1) — VDB 做多 first slice
-- Seth, 2026-07-28. Idempotent. Companion migration for
-- docs/REGIME_FINGERPRINT_SPEC.md.
--
-- Pre-requisite: the `vector` extension is already enabled (asset_embeddings
-- uses it; see scripts/supabase_pgvector_vdb.sql).  No extension change here.
--
-- WHY: replace the "simple-factor loop" with a regime-similarity retrieval
-- layer — one vector query answers "today's regime is historically closest to
-- which N days, and what was R77's 5d forward alpha on those days?"  Drawn
-- exclusively from previously-validated modules (S-78 vol regime, M-WO-2
-- EXTENDED pillar IC, R75 hourly S/O, R62 detector fire-rate, R76 funding
-- residual, asset_embeddings centroid drift).  No new signal operator invented.
--
-- I1 (unmeasured ≠ 0) carried over from asset v2:
--   - vec vector(12)  = dense finite core, HNSW cosine index, NEVER NaN
--   - vec_full JSONB  = full 12 entries with null for NaN
--   - MIN_SHARED_DIMS=4 read-side gate (enforced in Python, see module §3)
--
-- r77_fwd_5d_alpha_pct is the OUTCOME label populated from the frozen R77
-- paper-book NAV 5 trading days after each trade_date; null until realized.
-- ============================================================================

create table if not exists regime_fingerprints (
  id                   bigserial primary key,
  trade_date           date        not null unique,
  canonical_regime     text        not null,
  vec                  vector(12),
  vec_full             jsonb       not null,
  schema_version       int         not null default 3,
  r77_fwd_5d_alpha_pct real,
  r77_oos_window_start date,
  r77_oos_window_end   date,
  computed_at          timestamptz not null default now()
);

create index if not exists regime_fingerprints_vec_hnsw_idx
  on regime_fingerprints using hnsw (vec vector_cosine_ops);

create index if not exists regime_fingerprints_date_idx
  on regime_fingerprints (trade_date desc);

create index if not exists regime_fingerprints_regime_idx
  on regime_fingerprints (canonical_regime);

-- k-NN by 12-dim target vector; optional regime filter; optional alpha threshold.
-- Shared-dim count is computed live so the API consumer can score match quality.
create or replace function match_regime_fingerprints(
  p_target vector(12),
  p_k int default 5,
  p_regime_filter text default null,
  p_min_r77_alpha_pct real default null
)
returns table (
  trade_date date,
  canonical_regime text,
  vec_dist double precision,
  r77_fwd_5d_alpha_pct real,
  n_shared_dims int,
  r77_oos_window_start date,
  r77_oos_window_end date
)
language sql stable as $$
  with q as (
    select p_target::vector(12) as tgt,
           p_regime_filter as regime_filter,
           p_min_r77_alpha_pct as min_alpha,
           p_k as k
  )
  select
    r.trade_date,
    r.canonical_regime,
    (r.vec <=> q.tgt)::double precision as vec_dist,
    r.r77_fwd_5d_alpha_pct,
    (
      select count(*)::int
      from jsonb_each(r.vec_full) f
      where jsonb_extract_path_text(r.vec_full, f.key) is not null
        and jsonb_extract_path_text(jsonb_build_object('v', q.tgt::text), 'v') is not null
    ) as n_shared_dims,
    r.r77_oos_window_start,
    r.r77_oos_window_end
  from regime_fingerprints r, q
  where r.vec is not null
    and (q.regime_filter is null or r.canonical_regime = q.regime_filter)
    and (q.min_alpha is null or r.r77_fwd_5d_alpha_pct >= q.min_alpha)
  order by r.vec <=> q.tgt
  limit q.k
$$;

-- Written by: src/research/vector/regime_fingerprints.py::upsert_rows
-- Read by:    GET /api/v1/research/regime-analog (Seth to add post-VERIFICATION).
-- Schema version: 3 (companion to asset_embeddings schema_version=2).
-- Smoke test: src/research/vector/tests/test_regime_fingerprints_smoke.py (synth 12-d).

comment on table regime_fingerprints is
  'Per-trade-date 12-dim regime fingerprint derived from validated modules '
  '(S-78, M-WO-2 EXT, R62, R75, R76, asset_embeddings).  Used by '
  'match_regime_fingerprints RPC.  spec: docs/REGIME_FINGERPRINT_SPEC.md v0.1.';

comment on column regime_fingerprints.vec is
  'dense finite 12-dim core, HNSW cosine index rides this.  pgvector rejects NaN.';
comment on column regime_fingerprints.vec_full is
  'full 12-dim with null for NaN (I1); NaN-aware Python cosine on read.';
comment on column regime_fingerprints.r77_fwd_5d_alpha_pct is
  'realised 5d forward β-adj alpha from the frozen R77 paper-book NAV at '
  'trade_date+5d.  null until the forward window closes.';
comment on column regime_fingerprints.canonical_regime is
  'UPPER_SNAKE regime label aligned across T1 (Mac push) + T2 (Railway fallback).';
