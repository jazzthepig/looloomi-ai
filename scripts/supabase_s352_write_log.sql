-- S-352 · 已于 2026-09-15 经 MCP 应用到生产 · 记录副本,非待跑文件
-- migration: s352_write_log_a_failed_write_must_leave_a_trace
--
-- Jazz:「现在我们建了好多东西,但写入没有写入完全是玄学!」
-- 玄学的形状:**写成功留下一行,写失败什么都不留。** 于是「表里没有行」同时意味着
--   ① 没人写过(pod_aggregator._save_state 定义了从未被调用)
--   ② 写了但失败了(fusion_paper_state 表不存在,S-336)
--   ③ 写了但写到别处(order=ts.desc 打在不存在的列上,400 被 debug 吞掉,S-330)
-- 三者在库里完全同形。这个月建的所有检查都在量**结果**,没有一个在量**尝试**。
create table if not exists public.write_log (
    id bigserial primary key,
    at timestamptz not null default now(),
    table_name text not null,
    n_rows integer not null default 0,
    outcome text not null,
    status integer,
    body text,
    elapsed_ms integer,
    writer text
);
create index if not exists write_log_table_at_desc on public.write_log (table_name, at desc);
create index if not exists write_log_failures on public.write_log (at desc) where outcome <> 'ok';
alter table public.write_log enable row level security;
grant select on public.write_log to anon;
grant select, insert on public.write_log to authenticated;
grant select, insert, delete on public.write_log to service_role;

-- 一次往返回答「每张表最后一次成功/失败是什么时候、最近在失败什么」。
create or replace function public.write_health()
returns table (table_name text, last_ok timestamptz, last_fail timestamptz,
               last_outcome text, last_body text, n_ok_24h bigint, n_fail_24h bigint)
language sql stable security definer
set search_path = public, pg_catalog
as $$
    select w.table_name,
           max(w.at) filter (where w.outcome = 'ok'),
           max(w.at) filter (where w.outcome <> 'ok'),
           (array_agg(w.outcome order by w.at desc))[1],
           (array_agg(w.body    order by w.at desc))[1],
           count(*) filter (where w.outcome =  'ok' and w.at > now() - interval '24 hours'),
           count(*) filter (where w.outcome <> 'ok' and w.at > now() - interval '24 hours')
    from public.write_log w group by w.table_name order by max(w.at) desc;
$$;
revoke all on function public.write_health() from public;   -- S-323h
grant execute on function public.write_health() to anon;
grant execute on function public.write_health() to authenticated;
grant execute on function public.write_health() to service_role;
