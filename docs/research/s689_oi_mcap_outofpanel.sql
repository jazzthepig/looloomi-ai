-- S-689(台账,预注册 2026-10-26 13:41 UTC):OI/市值在面板外名字上、控制规模后的截面 IC。Seth 版;C 道 T-204 独立复算。
-- 开算条件:perp_cg_map 没有 pending,或已过 2026-10-28 00:00 UTC。只读。
-- 输出:逐月(term, m, n_days, rho)与汇总(term, n_months, mean, t, 两半)。term = partial(主)/ raw / size。
with panel(sym) as (
  values ('AAVE'),('ADA'),('APT'),('ARB'),('AVAX'),('BNB'),('BTC'),('DOT'),('ETH'),('HYPE'),('INJ'),('LDO'),('LINK'),
         ('NEAR'),('ONDO'),('OP'),('PENDLE'),('POL'),('SKY'),('SOL'),('STRK'),('SUI'),('TIA'),('UNI'),('XRP')
), names as (
  select distinct symbol as sym from deriv_metrics_daily where d >= '2023-01-01' and symbol not in (select sym from panel)
), am_syms as (
  select distinct upper(symbol) as sym from asset_mcap_daily where source = 'coingecko_pro_market_chart'
), px as (                                    -- CG 价 / 市值:先 asset_mcap_daily(按 symbol),没有的用 perp_cg_map 校验过的 coin_id
  select upper(a.symbol) as sym, a.d, a.price, a.mcap, 1 as mult
  from asset_mcap_daily a
  where a.source = 'coingecko_pro_market_chart' and upper(a.symbol) in (select sym from names)
  union all
  select p.symbol, c.d, c.price, c.mcap, p.mult
  from perp_cg_map p join cg_coin_mcap_daily c on c.coin_id = p.coin_id
  where p.verdict = 'resolved' and p.symbol in (select sym from names) and p.symbol not in (select sym from am_syms)
), oi as (
  select symbol as sym, d, oi_value_close, oi_close from deriv_metrics_daily
  where d >= '2023-01-01' and symbol in (select sym from names)
), chk as (                                   -- 映射校验:隐含价 = oi_value_close / oi_close
  select o.sym, count(*) as n_overlap,
         percentile_cont(0.5) within group (order by abs(x.price * x.mult / (o.oi_value_close / o.oi_close) - 1)) as med_err
  from oi o join px x on x.sym = o.sym and x.d = o.d
  where o.oi_close > 0 and o.oi_value_close > 0 and x.price > 0
  group by o.sym
), kept as (
  select sym from chk where n_overlap >= 30 and med_err <= 0.05
), btc as (
  select d, price from asset_mcap_daily where source = 'coingecko_pro_market_chart' and coin_id = 'bitcoin'
), rows as (
  select o.sym, o.d,
         o.oi_value_close / x.mcap as r,
         ln(x.mcap) as size,
         (x2.price / x.price - 1) - (b2.price / b.price - 1) as y
  from oi o
  join kept k on k.sym = o.sym
  join px x  on x.sym = o.sym and x.d = o.d
  join px x2 on x2.sym = o.sym and x2.d = o.d + 30
  join btc b  on b.d = o.d
  join btc b2 on b2.d = o.d + 30
  where x.mcap >= 20000000 and o.oi_value_close > 0 and x.price > 0 and x2.price > 0
), ok_days as (
  select d from rows group by d having count(*) >= 30
), ranked as (
  select r0.d,
         rank() over (partition by r0.d order by r0.r)    + (count(*) over (partition by r0.d, r0.r)    - 1) / 2.0 as rr,
         rank() over (partition by r0.d order by r0.y)    + (count(*) over (partition by r0.d, r0.y)    - 1) / 2.0 as ry,
         rank() over (partition by r0.d order by r0.size) + (count(*) over (partition by r0.d, r0.size) - 1) / 2.0 as rs
  from rows r0 join ok_days using (d)
), daily as (
  select d, corr(rr, ry) as r_ry, corr(rr, rs) as r_rs, corr(ry, rs) as r_ys, count(*) as n from ranked group by d
), daily2 as (
  select d, n, r_ry as raw, r_ys as size_ic,
         case when abs(r_rs) < 1 and abs(r_ys) < 1
              then (r_ry - r_rs * r_ys) / sqrt((1 - r_rs * r_rs) * (1 - r_ys * r_ys)) end as partial
  from daily
), long as (
  select 'partial' as term, d, partial as v from daily2
  union all select 'raw', d, raw from daily2
  union all select 'size', d, size_ic from daily2
), monthly as (
  select term, date_trunc('month', d)::date as m, count(*) as n_days, avg(v) as rho from long group by term, date_trunc('month', d)
)
-- 逐月(复算对数用):select term, m, n_days, round(rho::numeric, 6) from monthly order by term, m;
-- 名单:select c.*, (c.sym in (select sym from kept)) as kept from chk c order by kept, med_err desc;
select term, count(*) as n_months, sum(n_days) as n_days,
       round(avg(rho)::numeric, 4) as mean_rho,
       round((avg(rho) / nullif(stddev_samp(rho), 0) * sqrt(count(rho)))::numeric, 2) as t_month,
       round(avg(rho) filter (where m <  date '2024-07-01')::numeric, 4) as first_half,
       round(avg(rho) filter (where m >= date '2024-07-01')::numeric, 4) as second_half
from monthly group by term order by term;
