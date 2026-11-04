-- 2026-11-04 · Entity / Decision layer (HIGH_DIM_ONTOLOGY §5, the kernel's deepest object; Jazz 11-04 "今天开始").
-- issuer_entities: the registry (code is the source of truth, synced every round). issuer_decisions: what an issuer did
-- to its minority holders, dated — derived from issuer_fundamentals_quarterly (filing date), events (listings) and
-- treatment_daily (weekly payout class / token dilution). Append-only by id; lanes read both.
create table if not exists public.issuer_entities (
  id             text primary key,
  name           text not null,
  kind           text not null,
  instruments    jsonb not null default '[]'::jsonb,
  coingecko_ids  jsonb not null default '[]'::jsonb,
  sec_ticker     text,
  confidence     text not null default 'assumed',
  note           text,
  code_ref       text,
  updated_at     timestamptz not null default now()
);
create table if not exists public.issuer_decisions (
  id          text primary key,
  entity_id   text not null,
  ts          timestamptz not null,
  kind        text not null,
  symbols     jsonb not null default '[]'::jsonb,
  value       double precision,
  payload     jsonb not null default '{}'::jsonb,
  source      text,
  code_ref    text,
  recorded_at timestamptz not null default now()
);
create index if not exists issuer_decisions_entity_ts_idx on public.issuer_decisions (entity_id, ts desc);
create index if not exists issuer_decisions_kind_ts_idx on public.issuer_decisions (kind, ts desc);
alter table public.issuer_entities enable row level security;
alter table public.issuer_decisions enable row level security;
grant select on public.issuer_entities to anon;
grant select on public.issuer_decisions to anon;
drop policy if exists lane_read on public.issuer_entities;
create policy lane_read on public.issuer_entities for select to anon using (true);
drop policy if exists lane_read on public.issuer_decisions;
create policy lane_read on public.issuer_decisions for select to anon using (true);
