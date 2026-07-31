-- ============================================================================
-- strategy_records durable table — Postgres jsonb storage for the strategy vector.
-- Seth, 2026-07-26 (MINIMAX_SYNC §VDB — strategy vectors item, 2026-07-23).
--
-- WHY: src/data/vector/strategy_store.py persists records to Upstash Redis with
-- a 24h TTL. A 24h TTL on the EXACT record library is the wrong default — a
-- single Redis evict loses months of research. This migration moves the
-- source of truth to durable Postgres (jsonb), with embeddings remaining in
-- Redis as a derived cache rebuildable from records.
--
-- DESIGN RULE (matches §VDB):
--   - records (FEW: ~30–200 rows, sparse schema) → Postgres jsonb (this table).
--   - similarity / coverage_gaps / redundancy       → Python NaN-aware cosine
--     (NOT pgvector-ANN — at this scale pgvector gives no benefit AND its
--     dense cosine would impute unmeasured→0, which is wrong).
--   - embeddings                                    → Redis, rebuildable from
--     records. The Postgres table is single source of truth.
--
-- The existing src/data/vector/strategy_store.py is refactored to:
--   1. WRITE:  postgres upsert (primary) + redis set embeddings (secondary).
--   2. READ:   postgres primary (with redis-cache fallback path via
--              migrate_redis_to_postgres() helper if a deploy finds post=
--              postgres has fewer rows than the existing redis).
-- ============================================================================

create table if not exists strategy_records (
  id          text primary key,
  record      jsonb not null,
  created_at  timestamptz default now(),
  updated_at  timestamptz default now()
);

create index if not exists idx_strategy_records_updated_at
  on strategy_records (updated_at desc);

-- Auto-bump updated_at on jsonb body changes via trigger so cache TTL
-- logic can compare against store_age_seconds().
create or replace function strategy_records_bump_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists trg_strategy_records_updated_at on strategy_records;
create trigger trg_strategy_records_updated_at
  before update on strategy_records
  for each row execute function strategy_records_bump_updated_at();

comment on table strategy_records is
  'Durable source of truth for strategy_vector records (~30–200 rows). Replaces the previous '
  'Upstash-Redis 24h TTL store which was vulnerable to evicts losing the entire research library. '
  'Embeddings remain in Redis as a derived cache (rebuildable from record.body via '
  'src/data/vector/strategy_embedder.generate_embedding). Similarity is computed in Python '
  'NaN-aware cosine (canonical), NOT pgvector-ANN — at this scale pgvector gives no benefit '
  'and would silently corrupt by imputing unmeasured→0. See MINIMAX_SYNC §VDB (2026-07-23).';

comment on column strategy_records.record is
  'StrategyRecord.to_dict() payload verbatim. Stored as jsonb so consumers can introspect '
  'with jsonb_path_query without parsing the whole row.';
