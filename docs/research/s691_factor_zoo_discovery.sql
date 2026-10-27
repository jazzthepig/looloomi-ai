-- S-691 发现段(台账,预注册 2026-10-27 04:33 UTC):14 个因子 × 宽宇宙,规模控制的截面偏 Spearman,按月 t。Seth 版;B 道 T-206 独立复算。
-- **封存:** 只用信号日 2023-01-01 → 2024-11-30 的行(结果窗口最远到 2024-12-30)。映射校验段同 S-689(只是数据质量,不是因子统计量)。
-- 参数 :factors —— 一次跑一组因子(where f.factor in (...)),避免一条语句太大;14 个分三组跑,结果合并。
with names as (select distinct symbol as sym from deriv_metrics_daily),
am_syms as (select distinct upper(symbol) as sym from asset_mcap_daily where source = 'coingecko_pro_market_chart'),
px_all as (
  select upper(a.symbol) as sym, a.d, a.price, a.mcap, a.volume, 1 as mult from asset_mcap_daily a
  where a.source = 'coingecko_pro_market_chart' and upper(a.symbol) in (select sym from names)
  union all
  select p.symbol, c.d, c.price, c.mcap, null::float8, p.mult from perp_cg_map p join cg_coin_mcap_daily c on c.coin_id = p.coin_id
  where p.verdict = 'resolved' and p.symbol not in (select sym from am_syms)
),
oi_all as (select symbol as sym, d, oi_value_close, oi_close, top_pos_ratio_close, global_acct_ratio_close, taker_ratio_mean from deriv_metrics_daily),
chk as (
  select o.sym, count(*) as n_overlap,
         percentile_cont(0.5) within group (order by abs(x.price * x.mult / (o.oi_value_close / o.oi_close) - 1)) as med_err
  from oi_all o join px_all x on x.sym = o.sym and x.d = o.d
  where o.d >= '2023-01-01' and o.oi_close > 0 and o.oi_value_close > 0 and x.price > 0 group by o.sym
),
kept as (select sym from chk where n_overlap >= 30 and med_err <= 0.05),
px as (select * from px_all where sym in (select sym from kept) and d between '2021-11-01' and '2024-12-31' and price > 0),
pxw as (
  select sym, d, price, mcap, volume,
         ln(price / lag(price) over (partition by sym order by d)) as lr,
         max(price) over (partition by sym order by d range between interval '364 days' preceding and current row) as hi365,
         count(price) over (partition by sym order by d range between interval '364 days' preceding and current row) as n365,
         avg(volume) over (partition by sym order by d range between interval '6 days' preceding and current row) as vol7,
         count(volume) over (partition by sym order by d range between interval '6 days' preceding and current row) as nvol7
  from px
),
pxw2 as (
  select *, stddev_samp(lr) over (partition by sym order by d range between interval '29 days' preceding and current row) as vol30,
            count(lr) over (partition by sym order by d range between interval '29 days' preceding and current row) as nlr30
  from pxw
),
oi as (select * from oi_all where sym in (select sym from kept) and d between '2022-08-01' and '2024-11-30'),
oiw as (
  select *, avg(taker_ratio_mean) over (partition by sym order by d range between interval '6 days' preceding and current row) as tkr7,
            count(taker_ratio_mean) over (partition by sym order by d range between interval '6 days' preceding and current row) as ntkr7
  from oi
),
fund as (
  select symbol as sym, (funding_time at time zone 'UTC')::date as d, avg(funding_rate) as fr from funding_history
  where venue = 'binance_perp' and funding_time >= '2022-11-20' and funding_time < '2024-12-01' group by 1, 2
),
fundw as (
  select sym, d, avg(fr) over (partition by sym order by d range between interval '6 days' preceding and current row) as f7,
         count(fr) over (partition by sym order by d range between interval '6 days' preceding and current row) as nf7
  from fund
),
btc as (select d, price from asset_mcap_daily where source = 'coingecko_pro_market_chart' and coin_id = 'bitcoin'),
base as (
  select x.sym, x.d, x.mcap, ln(x.mcap) as size,
         (x30f.price / x.price - 1) - (b30f.price / b.price - 1) as y,
         case when o.oi_value_close > 0 then o.oi_value_close / x.mcap end as f01_oi_mcap,
         case when o.oi_close > 0 and o7.oi_close > 0 then ln(o.oi_close / o7.oi_close) end as f02_doi7,
         case when o.oi_close > 0 and o30.oi_close > 0 then ln(o.oi_close / o30.oi_close) end as f03_doi30,
         case when fw.nf7 >= 5 then fw.f7 end as f04_fund7,
         o.top_pos_ratio_close as f05_top_pos,
         o.global_acct_ratio_close as f06_global_acct,
         case when o.ntkr7 >= 5 then o.tkr7 end as f07_taker7,
         case when x30.price > 0 then (x.price / x30.price - 1) - (b.price / b30.price - 1) end as f08_mom30,
         case when x7.price > 0 then (x.price / x7.price - 1) - (b.price / b7.price - 1) end as f09_mom7,
         case when x90.price > 0 then (x.price / x90.price - 1) - (b.price / b90.price - 1) end as f10_mom90,
         case when x.nlr30 >= 25 then x.vol30 end as f11_vol30,
         case when x.nvol7 >= 5 and x.vol7 > 0 then x.vol7 / x.mcap end as f12_turn7,
         case when x.n365 >= 300 then x.price / x.hi365 end as f13_dhigh,
         ln(x.mcap) as f14_size
  from pxw2 x
  join pxw2 x30f on x30f.sym = x.sym and x30f.d = x.d + 30
  join btc b on b.d = x.d join btc b30f on b30f.d = x.d + 30
  left join oiw o on o.sym = x.sym and o.d = x.d
  left join oi o7 on o7.sym = x.sym and o7.d = x.d - 7
  left join oi o30 on o30.sym = x.sym and o30.d = x.d - 30
  left join fundw fw on fw.sym = x.sym and fw.d = x.d
  left join px x7 on x7.sym = x.sym and x7.d = x.d - 7
  left join px x30 on x30.sym = x.sym and x30.d = x.d - 30
  left join px x90 on x90.sym = x.sym and x90.d = x.d - 90
  left join btc b7 on b7.d = x.d - 7 left join btc b30 on b30.d = x.d - 30 left join btc b90 on b90.d = x.d - 90
  where x.d between '2023-01-01' and '2024-11-30' and x.mcap >= 20000000
),
long as (
  select f.factor, b.sym, b.d, f.v, b.y, b.size from base b
  cross join lateral (values
    ('f01_oi_mcap', b.f01_oi_mcap), ('f02_doi7', b.f02_doi7), ('f03_doi30', b.f03_doi30), ('f04_fund7', b.f04_fund7),
    ('f05_top_pos', b.f05_top_pos), ('f06_global_acct', b.f06_global_acct), ('f07_taker7', b.f07_taker7),
    ('f08_mom30', b.f08_mom30), ('f09_mom7', b.f09_mom7), ('f10_mom90', b.f10_mom90), ('f11_vol30', b.f11_vol30),
    ('f12_turn7', b.f12_turn7), ('f13_dhigh', b.f13_dhigh), ('f14_size', b.f14_size)) as f(factor, v)
  where f.v is not null and f.factor in (:factors)
),
ok_days as (select factor, d from long group by factor, d having count(*) >= 30),
ranked as (
  select l.factor, l.d,
         rank() over (partition by l.factor, l.d order by l.v)    + (count(*) over (partition by l.factor, l.d, l.v)    - 1) / 2.0 as rv,
         rank() over (partition by l.factor, l.d order by l.y)    + (count(*) over (partition by l.factor, l.d, l.y)    - 1) / 2.0 as ry,
         rank() over (partition by l.factor, l.d order by l.size) + (count(*) over (partition by l.factor, l.d, l.size) - 1) / 2.0 as rs
  from long l join ok_days using (factor, d)
),
daily as (
  select factor, d, count(*) as n, corr(rv, ry) as r_vy, corr(rv, rs) as r_vs, corr(ry, rs) as r_ys from ranked group by factor, d
),
daily2 as (
  select factor, d, n,
         case when factor = 'f14_size' then r_vy
              when abs(r_vs) < 1 and abs(r_ys) < 1 then (r_vy - r_vs * r_ys) / sqrt((1 - r_vs * r_vs) * (1 - r_ys * r_ys)) end as ic
  from daily
),
monthly as (select factor, date_trunc('month', d)::date as m, count(*) as n_days, avg(n) as n_names, avg(ic) as ic from daily2 group by 1, 2)
select factor, count(*) as n_months, round(avg(n_names)) as avg_names,
       round(avg(ic)::numeric, 6) as mean_ic, round((avg(ic) / nullif(stddev_samp(ic), 0) * sqrt(count(ic)))::numeric, 3) as t_month,
       string_agg(to_char(m, 'YYYY-MM') || '=' || round(ic::numeric, 6), ' ' order by m) as months
from monthly group by factor order by factor;
