-- ============================================================================
-- Entity/Decision space v1 — VDB space #5 (Seth, 2026-07-27)
-- Applied live via MCP (migration entity_decision_space_v1). Repo provenance.
-- Design: docs/ENTITY_DECISION_SPACE.md · Geometry: docs/HIGH_DIM_ONTOLOGY.md §5
--
-- WHY: everything else we store is the REFLECTION (asset/quality/price). S-81 proved
-- diffusing reflections carries nothing — the signal to diffuse is the CHANGE, and a
-- Decision is exactly a dated change event at a point in the field. This gives
-- propagation.propagate() its correct source term `s`.
--
-- VERIFIED 2026-07-27 (contract test, then cleaned):
--   · PIT decay exact — ARB with a today push (−0.06) + a 7d-old push (−0.06 × 2^(−7/14))
--     = −0.1024 ✓ ; OP (today only) = −0.06 ✓
--   · provenance CHECK blocks an empty-provenance insert ✓
--   · no future leakage — as_of BEFORE the decision date returns 0 rows ✓
-- ============================================================================
create extension if not exists vector;

create table if not exists entities (
  entity_id   text primary key,          -- 'whale:0xabc…' | 'inst:…' | 'proto:…' | 'policy:fed' | 'crowd:aggregate'
  kind        text not null,             -- whale | institution | protocol_gov | policy | exchange | crowd
  label       text,
  vec         vector(12),                -- influence coords (see entity_store.INFLUENCE_DIMS)
  lead_score  double precision,          -- EARNED via experiment E2 only; null = untested
  meta        jsonb default '{}'::jsonb, -- meta.measured{} flags which dims are real (I1)
  updated_at  timestamptz default now()
);
create index if not exists entities_vec_hnsw on entities using hnsw (vec vector_cosine_ops);
create index if not exists entities_kind_idx on entities (kind);

create table if not exists decisions (
  decision_id bigserial primary key,
  entity_id   text not null references entities(entity_id) on delete cascade,
  d           date not null,             -- PIT: KNOWN-BY date, not occurred date
  kind        text not null,             -- accumulate|distribute|unlock|list|delist|gov_vote|policy|allocate
  direction   double precision,          -- signed field push (+risk-on / −risk-off); NEVER buy/sell
  magnitude   double precision,          -- normalized (fraction of target ADV or float)
  targets     text[] default '{}',       -- Decision→Asset kernel edge
  half_life_d double precision,
  provenance  jsonb not null,            -- NO provenance ⇒ NO row
  created_at  timestamptz default now(),
  constraint decisions_provenance_nonempty check (provenance <> '{}'::jsonb)
);
create index if not exists decisions_d_idx on decisions (d);
create index if not exists decisions_entity_idx on decisions (entity_id);
create index if not exists decisions_targets_gin on decisions using gin (targets);

create or replace function decision_source_term(as_of date, lookback_days int default 30)
returns table(symbol text, s double precision)
language sql stable as $$
  select t.symbol,
         sum(dc.direction * dc.magnitude *
             exp(-ln(2) * (as_of - dc.d)::double precision
                 / nullif(coalesce(dc.half_life_d, 14.0), 0)))::double precision as s
  from decisions dc, unnest(dc.targets) as t(symbol)
  where dc.d <= as_of and dc.d > as_of - lookback_days
  group by t.symbol;
$$;

-- Writer: src/data/vector/entity_store.py (upsert_entity / record_decision / source_term)
-- Consumer: src/data/vector/propagation.py — propagate(graph, source_term(as_of)) = E3 kernel test
