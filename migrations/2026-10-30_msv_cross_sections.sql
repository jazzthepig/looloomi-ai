-- 2026-10-30 · 矢量库 v2(T-094 / S-699):market_state_vectors 的三个横截面维在服务端聚合,一次调用返回逐日结果。
-- 为什么:旧写者用一页 limit=5000 读 funding_history / cis_scores,而服务端 db-max-rows = 1000 —— 资金费维只读到
-- 窗口开头的 1000 行(几天),CIS 维同理(S-416 的同一个形状)。123 万行资金费分页读要 1,230 页;在服务端聚合是一次调用。
-- 成员是按月的(时点面板:上月末按 30 日成交额取前 N),所以由调用方传入 {YYYY-MM: [symbol, …]}。
-- 只给 service_role。

create or replace function public.msv_funding_xs(p_members jsonb, p_from date)
returns table(d date, n int, mean_rate double precision, sd_rate double precision)
language sql stable security invoker set search_path = public as $fn$
  with m as (
    select e.key as month, x.symbol
    from jsonb_each(p_members) e cross join lateral jsonb_array_elements_text(e.value) x(symbol)
  ), daily as (
    select f.symbol, (f.funding_time at time zone 'utc')::date as d, avg(f.funding_rate)::float8 as r
    from funding_history f
    where f.venue = 'binance_perp' and f.funding_time >= p_from
      and f.symbol in (select distinct symbol from m)
    group by 1, 2
  )
  select daily.d, count(*)::int, avg(daily.r), stddev_samp(daily.r)
  from daily join m on m.symbol = daily.symbol and m.month = to_char(daily.d, 'YYYY-MM')
  group by daily.d order by daily.d
$fn$;

create or replace function public.msv_oi_xs(p_members jsonb, p_from date)
returns table(d date, n int, oi_value double precision)
language sql stable security invoker set search_path = public as $fn$
  with m as (
    select e.key as month, x.symbol
    from jsonb_each(p_members) e cross join lateral jsonb_array_elements_text(e.value) x(symbol)
  )
  select o.d, count(*)::int, sum(o.oi_value_close)::float8
  from deriv_metrics_daily o join m on m.symbol = o.symbol and m.month = to_char(o.d, 'YYYY-MM')
  where o.d >= p_from and o.oi_value_close is not null
  group by o.d order by o.d
$fn$;

-- CIS 横截面:每个标的每个 UTC 日取当天最后一个分数,再在当天全部标的上求均值 / 标准差 / 偏度 / A 档占比。
create or replace function public.msv_cis_xs(p_from date)
returns table(d date, n int, mean_score double precision, sd_score double precision, skew_score double precision,
              pct_grade_a double precision)
language sql stable security invoker set search_path = public as $fn$
  with last_per_day as (
    select distinct on (symbol, (recorded_at at time zone 'utc')::date)
           symbol, (recorded_at at time zone 'utc')::date as d, score::float8 as s, grade
    from cis_scores
    where recorded_at >= p_from and score is not null
    order by symbol, (recorded_at at time zone 'utc')::date, recorded_at desc
  ), st as (
    select d, count(*)::int as n, avg(s) as mu, stddev_samp(s) as sd,
           avg(case when grade like 'A%' then 1.0 else 0.0 end)::float8 as pa
    from last_per_day group by d
  )
  select st.d, st.n, st.mu, st.sd,
         case when st.sd > 0 then avg(power((l.s - st.mu) / st.sd, 3)) end,
         st.pa
  from st join last_per_day l on l.d = st.d
  group by st.d, st.n, st.mu, st.sd, st.pa order by st.d
$fn$;

revoke all on function public.msv_funding_xs(jsonb, date) from public, anon, authenticated;
revoke all on function public.msv_oi_xs(jsonb, date) from public, anon, authenticated;
revoke all on function public.msv_cis_xs(date) from public, anon, authenticated;
grant execute on function public.msv_funding_xs(jsonb, date) to service_role;
grant execute on function public.msv_oi_xs(jsonb, date) to service_role;
grant execute on function public.msv_cis_xs(date) to service_role;
