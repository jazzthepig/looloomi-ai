-- S-350 · 已于 2026-09-15 经 MCP 应用到生产 · 记录副本,非待跑文件
-- migration: s350_catalog_inventory_existence_is_a_catalog_question
--
-- 为什么。PostgREST 挡了 information_schema / pg_catalog(PGRST106),drift 探针只能靠
-- POST 看状态码。而 PostgREST 按**参数名**解析 RPC:有必填参数的函数 POST {} 回 PGRST202
-- =「没有匹配这组参数名的重载」,不是「不存在」;全默认参数的函数 POST {} 则**把它跑一遍**
-- (exec_backfill / refresh_depth_divergence 是生产写函数)。
-- 实测规模:库里 148 个函数,**128 个有必填参数** —— POST-{} 探法会把 128 个报成缺失。
-- 实测代价:A-RPC-DRIFT-REPORT 报 10 个 RPC 缺失,核实后 0 个成立。
create or replace function public.catalog_inventory()
returns table (kind text, name text, args text, n_args integer, n_required integer)
language sql stable security definer
set search_path = public, pg_catalog
as $$
    select 'table'::text, c.relname::text, ''::text, 0, 0
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r','p','v','m')
    union all
    select 'function'::text, p.proname::text,
           pg_get_function_identity_arguments(p.oid),
           p.pronargs::int, (p.pronargs - p.pronargdefaults)::int
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.prokind = 'f'
    order by 1, 2;
$$;
-- S-323h:GRANT 是加法,创建时 PUBLIC 默认就有 EXECUTE,必须显式收窄。
revoke all on function public.catalog_inventory() from public;
grant execute on function public.catalog_inventory() to anon;
grant execute on function public.catalog_inventory() to authenticated;
grant execute on function public.catalog_inventory() to service_role;
-- 实测:148 functions · 91 tables · A 报缺的 6 个全部在列
