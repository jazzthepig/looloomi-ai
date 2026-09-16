-- S-360 · applied 2026-09-16 · public_columns() 漏掉视图
--
-- 症状:preflight 报 `fusion_paper_nav.inception_id does not exist`,而那两列
-- 在库里确实存在(text)。快照 `schema/public_columns.json` 停在 2026-08-20。
--
-- 修快照的过程中发现更深的一层:刷新脚本(S-357,我自己写的)和它调用的
-- `public_columns()` RPC **都**过滤 `t.table_type = 'BASE TABLE'`,
-- 于是 13 个视图(127 列)不会进快照。而
-- `tests/test_postgrest_columns_exist.py` 对「不在快照里的对象」是 **skip** 的:
--
--     if table not in schema:
--         continue          # not in the snapshot; see the blind-spot test
--
-- 所以跑一次刷新,快照会从 89 个对象缩到 79,针对视图的 PostgREST filter
-- 全部变成不检查 —— 而测试**全程绿**。被放掉的恰好包括
-- `ohlcv_daily_canonical` 和 `signal_outcomes_unified`,
-- 正是 docs/SPINE.md 要所有消费者迁过去的两条 canonical 路径。
--
-- PostgREST 对视图和表一视同仁:filter 一个视图的列一样 400。守卫只看见一半。
-- **一个让仪表变盲的修复,比不修更坏** —— 它把红灯换成了绿灯,而不是换成事实。
--
-- 修完实测:92 个对象(79 表 + 13 视图),两条 canonical 视图均在。

create or replace function public.public_columns()
returns jsonb
language sql
stable
security definer
set search_path = public, pg_catalog
as $$
    select jsonb_object_agg(table_name, cols)
    from (
        select c.table_name,
               jsonb_agg(c.column_name order by c.column_name) as cols
        from information_schema.columns c
        join information_schema.tables t
          on t.table_schema = c.table_schema and t.table_name = c.table_name
        where c.table_schema = 'public'
          and t.table_type in ('BASE TABLE', 'VIEW')
        group by c.table_name
    ) s;
$$;

-- S-167 的惯例:SECURITY DEFINER 的函数,重建会把 grant 恢复成 PUBLIC,
-- 所以每次 create or replace 后都必须重新 revoke。
revoke all on function public.public_columns() from public;
revoke all on function public.public_columns() from anon, authenticated;
grant execute on function public.public_columns() to service_role;

-- 验证(跑完应为 92 / t / t):
--   select (select count(*) from jsonb_object_keys(public.public_columns())),
--          public.public_columns() ? 'ohlcv_daily_canonical',
--          public.public_columns() ? 'signal_outcomes_unified';
