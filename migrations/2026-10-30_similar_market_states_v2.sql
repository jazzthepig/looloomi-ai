-- 2026-10-30 · similar_market_states(4 参数版)跟上矢量库 v2(S-699)。
-- 旧版只保留「维度齐备的天」(n = 全表最大维数)并在全样本上重新标准化。v1 每天都是 11 维,所以等于全部可用;
-- v2 的维数随数据可得性变(2021–24 年 15–16 维,2025-11 起 21 维),「只要齐备的天」就只剩最后一年 —— 深度白补。
-- 新版:vec_full 已经是按时点(扩张窗口)标准化的坐标,不再二次标准化;余弦只在目标与候选**都测到**的维上算,
-- 共享维数要 ≥ max(min_shared, ceil(0.7 × 目标当天的实测维数))。返回列不变。
create or replace function public.similar_market_states(target_day date default null::date, k integer default 5,
                                                        min_shared integer default 6, exclude_days integer default 30)
returns table(d date, cosine double precision, shared_dims integer, measured_dims integer, n_symbols integer)
language sql stable set search_path to 'public', 'extensions', 'pg_temp' as $function$
with tgt_day as (
    select coalesce(target_day, (select max(x.d) from market_state_vectors x)) as d
),
t as (
    select a.i, (a.val)::float8 as tv
    from market_state_vectors m, tgt_day
    join lateral jsonb_array_elements_text(m.vec_full) with ordinality a(val, i) on true
    where m.d = tgt_day.d and a.val is not null
),
need as (select greatest(min_shared, ceil(0.7 * count(*))::int) as n from t),
sim as (
    select m.d, count(*)::int as shared,
           sum((a.val)::float8 * t.tv) / nullif(sqrt(sum((a.val)::float8 ^ 2)) * sqrt(sum(t.tv ^ 2)), 0) as cos
    from market_state_vectors m
    cross join tgt_day
    join lateral jsonb_array_elements_text(m.vec_full) with ordinality a(val, i) on true
    join t on t.i = a.i
    where a.val is not null and m.d <> tgt_day.d and abs(m.d - tgt_day.d) > exclude_days
    group by m.d
)
select s.d, s.cos, s.shared, m.measured_dims, m.n_symbols
from sim s join market_state_vectors m on m.d = s.d cross join need
where s.shared >= need.n and s.cos is not null
order by s.cos desc
limit k;
$function$;
