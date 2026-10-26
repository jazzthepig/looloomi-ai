-- S-688(台账,预注册 2026-10-26 10:30 UTC):CIS 衍生品两项对 30 天超额的截面 IC。Seth 版;B 道 T-203 独立复算。
-- 跑法:整段贴进 Supabase SQL(只读)。输出两张:逐月(term, month, n_days, rho, prho)与汇总(term, n_months, mean, t, 两半, 偏相关)。
-- 两项一字照抄 src/data/cis/cis_provider.py 的 v4.3 分段(interp 夹在两端值之间)。
-- score 读 cis-standard-v1.3 的重建行:必须在 S-687 附记二的修复上线、周一全量重写之后读(10-26 12:00 UTC 之后)。
with base as (
  select o.symbol, o.d, o.alpha,
         (r.inputs->>'funding')::float8 as fr,
         (r.inputs->>'mcap')::float8    as mcap,
         r.score,
         m.oi_value_close               as oi
  from cis_standard_outcomes o
  join cis_rebuild_daily r on r.symbol = o.symbol and r.d = o.d and r.code_ref = 'cis-standard-v1.3'
  left join deriv_metrics_daily m on m.symbol = o.symbol and m.d = o.d
  where o.grp = 'crypto' and o.symbol <> 'BTC' and o.alpha is not null
), t1 as (
  select *,
    case when fr is null then null
         when fr >  0.0005 then greatest(-15.0, least(-8.0, -8.0 + (fr - 0.0005) / (0.002 - 0.0005) * (-7.0)))
         when fr >  0.0001 then greatest(0.0,   least(3.0,   3.0 + (fr - 0.0001) / (0.0005 - 0.0001) * (-3.0)))
         when fr > -0.0001 then 0.0
         when fr > -0.0005 then 2.0
         else -3.0 end as fr_adj,
    case when oi is null or oi <= 0 or mcap is null or mcap <= 0 then null else oi / mcap end as oi_ratio
  from base
), t2 as (
  select *,
    case when oi_ratio is null then null
         when oi_ratio > 1.0 then greatest(-10.0, least(-5.0, -5.0 + (oi_ratio - 1.0) / (3.0 - 1.0) * (-5.0)))
         when oi_ratio > 0.5 then greatest(-5.0,  least(-3.0, -3.0 + (oi_ratio - 0.5) / (1.0 - 0.5) * (-2.0)))
         when oi_ratio < 0.2 then 3.0
         else 0.0 end as oi_adj
  from t1
), long as (
  select 'fr_adj'   as term, symbol, d, fr_adj   as x, alpha, score from t2 where fr_adj   is not null
  union all
  select 'oi_adj',          symbol, d, oi_adj,         alpha, score from t2 where oi_adj   is not null
  union all
  select 'diag_fr_level',   symbol, d, fr,             alpha, score from t2 where fr       is not null
  union all
  select 'diag_oi_ratio',   symbol, d, oi_ratio,       alpha, score from t2 where oi_ratio is not null
), ok_days as (
  select term, d from long group by term, d having count(*) >= 8 and count(distinct x) >= 2
), ranked as (
  select l.term, l.d,
         rank() over (partition by l.term, l.d order by l.x)     + (count(*) over (partition by l.term, l.d, l.x)     - 1) / 2.0 as rx,
         rank() over (partition by l.term, l.d order by l.alpha) + (count(*) over (partition by l.term, l.d, l.alpha) - 1) / 2.0 as ra,
         rank() over (partition by l.term, l.d order by l.score) + (count(*) over (partition by l.term, l.d, l.score) - 1) / 2.0 as rs
  from long l join ok_days k using (term, d)
  where l.score is not null
), daily as (
  select term, d, corr(rx, ra) as r_xa, corr(rx, rs) as r_xs, corr(ra, rs) as r_as from ranked group by term, d
), daily2 as (
  select term, d, r_xa,
         case when abs(r_xs) < 1 and abs(r_as) < 1
              then (r_xa - r_xs * r_as) / sqrt((1 - r_xs * r_xs) * (1 - r_as * r_as)) end as p_xa
  from daily
), monthly as (
  select term, date_trunc('month', d)::date as m, count(*) as n_days, avg(r_xa) as rho, avg(p_xa) as prho
  from daily2 group by term, date_trunc('month', d)
)
-- 逐月(复算对数用):
-- select term, m, n_days, round(rho::numeric, 6) rho, round(prho::numeric, 6) prho from monthly order by term, m;
select term, count(*) as n_months, sum(n_days) as n_days,
       round(avg(rho)::numeric, 4) as mean_rho,
       round((avg(rho) / nullif(stddev_samp(rho), 0) * sqrt(count(rho)))::numeric, 2) as t_month,
       round(avg(rho) filter (where m <  date '2024-07-01')::numeric, 4) as first_half,
       round(avg(rho) filter (where m >= date '2024-07-01')::numeric, 4) as second_half,
       round(avg(prho)::numeric, 4) as mean_partial,
       round((avg(prho) / nullif(stddev_samp(prho), 0) * sqrt(count(prho)))::numeric, 2) as t_partial
from monthly group by term order by term;
