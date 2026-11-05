-- 2026-11-05 · text_vectors: the text space of the VDB (news / events → MiniMax embo-01, Jazz 11-05 "use minimax").
-- Unconstrained `vector` so a model change never fails the insert; `dim` says what each row is. Nearest-neighbour via RPC.
create table if not exists public.text_vectors (
  source        text not null,
  item_id       text not null,
  model         text not null,
  dim           integer not null,
  embedding     vector not null,
  text          text,
  published_at  timestamptz,
  created_at    timestamptz not null default now(),
  primary key (source, item_id, model)
);
alter table public.text_vectors enable row level security;
grant select on public.text_vectors to anon;
drop policy if exists lane_read on public.text_vectors;
create policy lane_read on public.text_vectors for select to anon using (true);

create or replace view public.text_vectors_todo with (security_invoker = true) as
  select 'feed_items'::text source, f.id item_id, f.title, f.summary_raw body, null::text kind, f.published_at
  from public.feed_items f
  where f.dup_of is null and not exists (select 1 from public.text_vectors v where v.source = 'feed_items' and v.item_id = f.id)
  union all
  select 'events', e.id, e.title, null, e.kind, e.ts
  from public.events e
  where not exists (select 1 from public.text_vectors v where v.source = 'events' and v.item_id = e.id);
grant select on public.text_vectors_todo to anon;

create or replace function public.text_vectors_nearest(q vector, k integer default 10, src text default null, mdl text default 'embo-01')
returns table (source text, item_id text, text text, published_at timestamptz, distance double precision)
language sql stable security invoker set search_path = public as $$
  select v.source, v.item_id, v.text, v.published_at, (v.embedding <=> q)::double precision distance
  from public.text_vectors v
  where v.model = mdl and v.dim = vector_dims(q) and (src is null or v.source = src)
  order by v.embedding <=> q
  limit greatest(1, least(k, 50));
$$;
grant execute on function public.text_vectors_nearest(vector, integer, text, text) to anon, authenticated, service_role;
