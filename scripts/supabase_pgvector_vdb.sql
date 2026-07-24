-- ============================================================================
-- VDB 落库 — asset vectors on Supabase pgvector (the proper vector-DB path).
-- Seth, 2026-07-23. Applied live via MCP (migrations vdb_pgvector_asset_embeddings
-- + vdb_match_rpc_class_mode). This file is the repo-visible provenance.
--
-- WHY: the vector store was Redis-JSON blobs ({symbol:[floats]}) with O(n) Python
-- cosine — fine at 84 assets, but not a vector DB (no index/ANN, can't scale to
-- text/news embeddings). pgvector gives an HNSW cosine index + SQL k-NN.
--
-- I1 (unmeasured ≠ 0): `vec vector(18)` = the DENSE finite v1 core (index rides this);
-- `vec_full jsonb` = the full v2 vector with null for NaN dims (pgvector rejects NaN),
-- for exact NaN-aware re-ranking — the unmeasured dims are never fabricated as 0.
-- ============================================================================

create extension if not exists vector;

create table if not exists asset_embeddings (
  symbol         text primary key,
  asset_class    text,
  macro_regime   text,
  schema_version int  default 2,
  dims           int,
  vec            vector(18),   -- dense finite v1 core [0..17]
  vec_full       jsonb,        -- full v2 [0..26] with null for NaN (I1)
  computed_at    timestamptz default now()
);

create index if not exists asset_embeddings_vec_hnsw
  on asset_embeddings using hnsw (vec vector_cosine_ops);

-- k-NN by target symbol. class_mode ∈ 'any' | 'same' | 'cross' (exclude same class).
create or replace function match_asset_embeddings(
  target text, k int default 5, class_mode text default 'any')
returns table(symbol text, asset_class text, macro_regime text, cosine_sim double precision)
language sql stable as $$
  with t as (select vec, asset_class tc from asset_embeddings where symbol = target and vec is not null)
  select e.symbol, e.asset_class, e.macro_regime,
         (1 - (e.vec <=> t.vec))::double precision as cosine_sim
  from asset_embeddings e, t
  where e.symbol <> target and e.vec is not null
    and ( class_mode = 'any'
       or (class_mode = 'same'  and e.asset_class = t.tc)
       or (class_mode = 'cross' and e.asset_class is distinct from t.tc) )
  order by e.vec <=> t.vec
  limit k;
$$;

-- Written by: src/data/vector/pgvector_store.py (upsert + similar).
-- Dual-written by: src/data/cis/cis_provider.py (beside Redis save_embeddings).
-- Read by: /api/v1/cis/similar (pgvector-first, Redis fallback).
-- Verified 2026-07-23: 72 assets loaded; match('ETH','cross') → LINK/UNI/AAVE/POL/AAPL (cross-class analogs).
