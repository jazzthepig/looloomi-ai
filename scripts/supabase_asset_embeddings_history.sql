-- ============================================================================
-- M-WO-D1 — asset_embeddings_history() (H3 unlock)
-- Seth+Minimax, 2026-08-02. Per MINIMAX_SYNC §P0-CIS-UNIVERSE work order:
--   `asset_embeddings` is 72 rows, single snapshot (verified in DB 2026-07-30).
--   That is the real remaining blocker: no time series ⇒ style rotation cannot
--   be backtested ⇒ DECISION_PATH_SPEC §3 stands untouched by everything we
--   shipped this week.
--
-- D1: daily recompute of the 27-dim vector from `cis_scores` pillar history
--     (99,804 rows, 2025-05-03 → today). Backfill as far as the pillars allow;
--     NaN for unmeasured, never 0 (I1).
--
-- Schema mirrors the live `asset_embeddings` table so the embedder module
-- (src/data/vector/embedder.py, SCHEMA_VERSION=2) writes both tables with the
-- same code path. `vec` is the 18-dim core (HNSW-indexed) and `vec_full` is
-- the full 27-dim vector with null for NaN dims. The history table is NOT
-- HNSW-indexed (the 18-dim core here is for human/exact-k-NN queries; ANN
-- search stays on the live table where rows are few and write-rate matters).
-- ============================================================================

create extension if not exists vector;

create table if not exists asset_embeddings_history (
  d              date          not null,
  symbol         text          not null,
  asset_class    text,
  macro_regime   text,
  schema_version int           default 2,
  dims           int,
  vec            vector(18),   -- dense finite v1 core [0..17], mirrors live table
  vec_full       jsonb,        -- full v2 [0..26] with null for NaN (I1)
  computed_at    timestamptz   default now(),
  primary key (d, symbol)
);

create index if not exists asset_embeddings_history_d_idx
  on asset_embeddings_history (d desc);

create index if not exists asset_embeddings_history_symbol_d_idx
  on asset_embeddings_history (symbol, d desc);

comment on table asset_embeddings_history is
  'M-WO-D1 daily snapshot of the 27-dim asset vector, backfilled from cis_scores '
  'pillar history. Primary use: style-rotation backtests + regime fingerprint '
  'time series. 18-dim vec mirrors the live asset_embeddings HNSW column; '
  'vec_full jsonb preserves NaN-honest full vector for exact re-ranking.';

-- ── Convenience view: latest snapshot per symbol ────────────────────────────
-- Lets the API surface "current vector per symbol" without the live table
-- having to be the source of truth for history queries.
create or replace view asset_embeddings_latest as
select distinct on (symbol) d, symbol, asset_class, macro_regime,
                      schema_version, dims, vec, vec_full, computed_at
  from asset_embeddings_history
  order by symbol, d desc;

comment on view asset_embeddings_latest is
  'M-WO-D1: per-symbol most-recent snapshot. Use when a backtest wants the '
  'CURRENT vector with the same semantics as asset_embeddings but the latest '
  'historical is preferred over a stale live row.';

-- ── Idempotent daily upsert helper ──────────────────────────────────────────
-- Mac T1 scheduler calls this once per day after the CIS push completes.
-- Symbol list is passed as a jsonb array (the Mac builds it from the local
-- cis_history.db). One POST per day, ~70 rows.
create or replace function upsert_asset_embeddings_history(p_rows jsonb)
returns int
language plpgsql
as $$
declare
  v_count int;
begin
  -- S-169 (2026-08-18): the last four columns used to be DROPPED here while the
  -- table carried them and the Mac computed them ("16.9 measured dims/row" in
  -- its own push log). measured_dims / source_completeness are how a consumer
  -- tells a vector built from 4 measured dims from one built from 18 — the
  -- NaN-honesty rule (I1) this repo already enforced twice inside the embedder,
  -- reappearing at the persistence layer. Two writers into one table:
  -- backfill_embedding_history.py wrote them, the daily path silently did not.
  --
  -- schema_version no longer defaults to 2. The embedder is at 3, so an
  -- unstamped row was being labelled v2 — a guess presented as provenance. NULL
  -- is answerable; a wrong 2 is not. (Same argument as S-151 refusing to
  -- back-fill param_version.)
  insert into asset_embeddings_history
    (d, symbol, asset_class, macro_regime, schema_version, dims, vec, vec_full,
     measured_dims, source_completeness, price_source, provenance_note)
  select
    (r->>'d')::date,
    upper(r->>'symbol'),
    r->>'asset_class',
    r->>'macro_regime',
    (r->>'schema_version')::int,
    (r->>'dims')::int,
    (r->>'vec')::vector(18),
    (r->>'vec_full')::jsonb,
    (r->>'measured_dims')::int,
    (r->>'source_completeness')::real,
    r->>'price_source',
    r->>'provenance_note'
  from jsonb_array_elements(p_rows) as r
  on conflict (d, symbol) do update set
    asset_class         = excluded.asset_class,
    macro_regime        = excluded.macro_regime,
    schema_version      = excluded.schema_version,
    dims                = excluded.dims,
    vec                 = excluded.vec,
    vec_full            = excluded.vec_full,
    measured_dims       = excluded.measured_dims,
    source_completeness = excluded.source_completeness,
    price_source        = excluded.price_source,
    provenance_note     = excluded.provenance_note,
    computed_at         = now();
  get diagnostics v_count = row_count;
  return v_count;
end $$;

comment on function upsert_asset_embeddings_history(jsonb) is
  'M-WO-D1: idempotent daily upsert. p_rows is jsonb array of {d, symbol, '
  'asset_class, macro_regime, schema_version, dims, vec (text literal), '
  'vec_full (jsonb)}. Returns affected row count. Mac T1 calls once per day.';

-- ── Verification queries (run after Mac T1 first push) ──────────────────────
-- 1. Row count by date:
--    select d, count(*) from asset_embeddings_history group by d order by d desc limit 10;
-- 2. Symbols covered on the latest snapshot:
--    select count(distinct symbol) from asset_embeddings_history where d = (select max(d) from asset_embeddings_history);
-- 3. HNSW-style nearest-neighbor lookup (for backtest use):
--    select symbol, 1 - (vec <=> (select vec from asset_embeddings_history where symbol = 'BTC' order by d desc limit 1)) as cosine_sim
--      from asset_embeddings_history
--      where d = (select max(d) from asset_embeddings_history) and symbol <> 'BTC'
--      order by vec <=> (select vec from asset_embeddings_history where symbol = 'BTC' order by d desc limit 1) limit 5;
