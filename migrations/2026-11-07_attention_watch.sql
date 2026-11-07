-- 2026-11-07 · S-769 B ✅ 的前向记录(src/data/signals/attention_watch.py):Santiment 社交量尖峰(z ≥ 3)之后 7 / 30 天相对篮子。
-- 一个 (代号, 尖峰日) 一行;cohort = forward(2026-10-09 起,S-769 没看过的数据)/ backfill(只作对照)。
create table if not exists public.attention_watch (
  symbol      text not null,
  d           date not null,
  z           double precision,
  cohort      text not null check (cohort in ('forward', 'backfill')),
  excess_7d   double precision,
  excess_30d  double precision,
  basket_n    integer,
  code_ref    text not null,
  settled_at  timestamptz,
  created_at  timestamptz not null default now(),
  primary key (symbol, d)
);
create index if not exists attention_watch_d on public.attention_watch (d desc);
alter table public.attention_watch enable row level security;
grant select on public.attention_watch to anon;
drop policy if exists lane_read on public.attention_watch;
create policy lane_read on public.attention_watch for select to anon using (true);
