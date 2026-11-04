-- Strategy 空间向量(11-04;src/data/strategy/book_vectors.py)。已通过 Supabase MCP 施加(migration name: book_vectors)。
create table if not exists public.book_vectors (
  d date not null,
  book_id text not null,
  layer text,
  status text,
  vector jsonb not null,
  n_days int not null,
  start date,
  code_ref text,
  computed_at timestamptz not null default now(),
  primary key (d, book_id)
);
create index if not exists book_vectors_book on public.book_vectors (book_id, d desc);
alter table public.book_vectors enable row level security;
drop policy if exists lane_read on public.book_vectors;
create policy lane_read on public.book_vectors for select to anon using (true);
grant select on public.book_vectors to anon, authenticated;
grant all on public.book_vectors to service_role;
