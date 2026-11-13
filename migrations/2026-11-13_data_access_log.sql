-- 11-13 已通过 Supabase MCP 施加(migration name: data_access_log)。研究数据只读入口的留痕表:谁、读了哪个对象、什么查询、几行、多久。
-- src/api/routers/lane_read.py。行级安全开着、没有任何策略 ⇒ 只有服务端 key 读写得到。
create table if not exists public.data_access_log (
  id      bigint generated always as identity primary key,
  at      timestamptz not null default now(),
  reader  text not null,
  obj     text not null,
  query   text,
  status  integer,
  n_rows  integer,
  ms      integer
);
create index if not exists data_access_log_at_idx on public.data_access_log (at desc);
create index if not exists data_access_log_reader_at_idx on public.data_access_log (reader, at desc);
alter table public.data_access_log enable row level security;
