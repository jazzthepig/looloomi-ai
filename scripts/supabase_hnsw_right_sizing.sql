-- ============================================================================
-- M-WO-D3 — HNSW right-sizing on asset_embeddings
-- Seth+Minimax, 2026-08-02. Per MINIMAX_SYNC §P0-CIS-UNIVERSE work order:
--   HNSW index created with default m=16/ef_construction=64 on a 72-row
--   table — over-provisioning is the write cost behind S-92 (the
--   connection-leak incident 2026-07-30). Right-size to m=8/ef_construction=32
--   which is appropriate for the 72→1000+ row range.
--
-- Own commit (not bundled with security SQL per §P0-CIS-UNIVERSE) so a
-- security rollback cannot drag an index rebuild along.
--
-- IDEMPOTENT: detects current index state and re-creates only if mismatched.
-- ============================================================================

do $$
declare
  v_index_name text;
  v_current_m  text;
  v_current_ef text;
begin
  -- 1. Find the actual index name on asset_embeddings.vec.
  select indexname into v_index_name
    from pg_indexes
   where tablename = 'asset_embeddings'
     and indexdef ilike '%hnsw%'
     and indexdef ilike '%vec%'
   limit 1;

  if v_index_name is null then
    raise notice 'No HNSW index found on asset_embeddings — nothing to right-size';
    return;
  end if;

  raise notice 'Found HNSW index: %', v_index_name;

  -- 2. Read the current build parameters (best-effort; if pg_indexes does not
  --    expose them we fall back to "always recreate").
  select
    coalesce((regexp_match(indexdef, 'm\s*=\s*(\d+)'))[1], ''),
    coalesce((regexp_match(indexdef, 'ef_construction\s*=\s*(\d+)'))[1], '')
    into v_current_m, v_current_ef
    from pg_indexes
   where indexname = v_index_name;

  raise notice 'Current params: m=% ef_construction=%', v_current_m, v_current_ef;

  -- 3. Right-size to m=8/ef_construction=32 (per supabase_connection_hygiene.sql §3
  --    + the verified index name in MINIMAX_SYNC §P0-CIS-UNIVERSE).
  --    Only rebuild if current params differ — avoids an unnecessary index rewrite
  --    on re-runs.
  if v_current_m = '8' and v_current_ef = '32' then
    raise notice 'Index already at m=8/ef_construction=32 — no rebuild needed';
    return;
  end if;

  raise notice 'Rebuilding index % with m=8, ef_construction=32', v_index_name;
  execute format('drop index if exists %I', v_index_name);
  execute format(
    'create index %I on asset_embeddings using hnsw (vec vector_cosine_ops) with (m = 8, ef_construction = 32)',
    v_index_name
  );
  raise notice 'Rebuild complete';
end $$;
