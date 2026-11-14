-- 2026-11-14 · write_health() reads through the index instead of scanning all of write_log (S-862).
-- 已通过 Supabase MCP 施加,两步:索引(create index concurrently,不在事务里)→ write_health_reads_by_index。
--
-- WHY. write_health() was `GROUP BY table_name` over the whole of write_log with two array_agg(... ORDER BY at DESC):
-- 1.18M rows / 262 MB on every call. Both the ops console and /internal/data-freshness call it. pg_stat_statements:
-- 22,319 calls, 18,718 s in total, max 28.8 s. In the minutes after a restart it runs into the 8 s statement timeout:
-- of the nine timeouts between 07:58 and 08:02 UTC on 11-14, eight were this function. A health check that times out
-- when the system is busiest reports nothing exactly when it is needed, and it adds to the load it is measuring.
--
-- WHAT. Same signature, same columns, same order. Per table: the latest row, the latest ok and the latest failure are
-- each one index probe; the 24 h counts are an index range. Table names come from a loose index scan (recursive CTE).
-- New partial index so that "latest failure" for a table that has never failed is an empty range, not a walk over
-- every failure of every table.
--
-- CHECKED BEFORE REPLACING (old function vs new query, one statement): 149 tables on both sides, none on one side
-- only, 0 differences in last_ok / last_fail / last_outcome / last_body / n_ok_24h / n_fail_24h.
-- Time on a quiet database: 1,335 ms -> 66 ms.
--
-- NOTE. scripts/supabase_s352_write_log.sql still carries the first definition; running that file again would put the
-- slow version back. This file is the current one.
--
-- LIVENESS: select count(*) from write_health();   -- one row per table that has ever been written (149 on 11-14)

create index concurrently if not exists write_log_table_fail_at
  on public.write_log (table_name, at desc) where outcome <> 'ok';

create or replace function public.write_health()
 returns table(table_name text, last_ok timestamp with time zone, last_fail timestamp with time zone, last_outcome text, last_body text, n_ok_24h bigint, n_fail_24h bigint)
 language sql
 stable security definer
 set search_path to 'public', 'pg_catalog'
as $function$
    with recursive names as (
        (select w.table_name from public.write_log w order by w.table_name limit 1)
        union all
        select (select w.table_name from public.write_log w where w.table_name > n.table_name order by w.table_name limit 1)
        from names n where n.table_name is not null
    )
    select n.table_name, ok.at, fail.at, last.outcome, last.body, c.n_ok, c.n_fail
    from names n
    cross join lateral (select w.at, w.outcome, w.body from public.write_log w
                        where w.table_name = n.table_name order by w.at desc limit 1) last
    left join lateral (select w.at from public.write_log w
                       where w.table_name = n.table_name and w.outcome = 'ok' order by w.at desc limit 1) ok on true
    left join lateral (select w.at from public.write_log w
                       where w.table_name = n.table_name and w.outcome <> 'ok' order by w.at desc limit 1) fail on true
    cross join lateral (select count(*) filter (where w.outcome = 'ok') n_ok, count(*) filter (where w.outcome <> 'ok') n_fail
                        from public.write_log w
                        where w.table_name = n.table_name and w.at > now() - interval '24 hours') c
    where n.table_name is not null
    order by last.at desc;
$function$;
