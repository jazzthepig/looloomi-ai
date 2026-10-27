-- S-691 留出段(台账:预注册 2026-10-27 04:33 UTC;短名单冻结 F3−、F7+、F8−、F9−、F11−;开封 2026-10-27 14:28 UTC)。Seth 版;B 道 T-208 独立复算。
-- 留出 = 信号日 2025-01-01 → 2026-09-26(结果窗口到 2026-10-26);2024-12 隔离。主口径 = 每天要 OI(has_oi),字面口径作敏感性。
-- 口径与发现段 s691_factor_zoo_discovery.sql 相同(映射校验名单 rs_s691_kept = 那份 SQL 的 kept,248 名);因子只算冻结的 5 个 + F1。
-- Supabase 单句有超时,所以分三张研究临时表(用完删)。

-- 1. 价格(冻结名单的名字;F11 的 30 天波动在这里算)
create table rs_s691h_px as
with names as (select distinct symbol as sym from deriv_metrics_daily),
am_syms as (select distinct upper(symbol) as sym from asset_mcap_daily where source = 'coingecko_pro_market_chart'),
px_all as (
  select upper(a.symbol) as sym, a.d, a.price, a.mcap from asset_mcap_daily a
  where a.source = 'coingecko_pro_market_chart' and upper(a.symbol) in (select sym from names) and a.d between '2024-11-01' and '2026-10-26'
  union all
  select p.symbol, c.d, c.price, c.mcap from perp_cg_map p join cg_coin_mcap_daily c on c.coin_id = p.coin_id
  where p.verdict = 'resolved' and p.symbol not in (select sym from am_syms) and c.d between '2024-11-01' and '2026-10-26'
),
px as (select * from px_all where sym in (select sym from rs_s691_kept) and price > 0),
pxw as (select sym, d, price, mcap, ln(price / lag(price) over (partition by sym order by d)) as lr from px)
select *, stddev_samp(lr) over (partition by sym order by d range between interval '29 days' preceding and current row) as vol30,
          count(lr) over (partition by sym order by d range between interval '29 days' preceding and current row) as nlr30
from pxw;

-- 2. OI 与主动买卖比
create table rs_s691h_oi as
select symbol as sym, d, oi_value_close, oi_close,
       avg(taker_ratio_mean) over (partition by symbol order by d range between interval '6 days' preceding and current row) as tkr7,
       count(taker_ratio_mean) over (partition by symbol order by d range between interval '6 days' preceding and current row) as ntkr7
from deriv_metrics_daily where symbol in (select sym from rs_s691_kept) and d between '2024-11-20' and '2026-10-26';

-- 3. 每名每天一行:y = 30 天收益 − BTC 30 天收益;因子
create table rs_s691h_base as
with btc as (select d, price from asset_mcap_daily where source = 'coingecko_pro_market_chart' and coin_id = 'bitcoin' and d >= '2024-11-01')
select x.sym, x.d, x.mcap, ln(x.mcap) as size,
       (x30f.price / x.price - 1) - (b30f.price / b.price - 1) as y,
       (o.oi_value_close > 0) as has_oi,
       case when o.oi_value_close > 0 then o.oi_value_close / x.mcap end as f01_oi_mcap,
       case when o.oi_close > 0 and o30.oi_close > 0 then ln(o.oi_close / o30.oi_close) end as f03_doi30,
       case when o.ntkr7 >= 5 then o.tkr7 end as f07_taker7,
       case when x30.price > 0 then (x.price / x30.price - 1) - (b.price / b30.price - 1) end as f08_mom30,
       case when x7.price > 0 then (x.price / x7.price - 1) - (b.price / b7.price - 1) end as f09_mom7,
       case when x.nlr30 >= 25 then x.vol30 end as f11_vol30
from rs_s691h_px x
join rs_s691h_px x30f on x30f.sym = x.sym and x30f.d = x.d + 30
join btc b on b.d = x.d join btc b30f on b30f.d = x.d + 30
left join rs_s691h_oi o on o.sym = x.sym and o.d = x.d
left join rs_s691h_oi o30 on o30.sym = x.sym and o30.d = x.d - 30
left join rs_s691h_px x7 on x7.sym = x.sym and x7.d = x.d - 7
left join rs_s691h_px x30 on x30.sym = x.sym and x30.d = x.d - 30
left join btc b7 on b7.d = x.d - 7 left join btc b30 on b30.d = x.d - 30
where x.d between '2025-01-01' and '2026-09-26' and x.mcap >= 20000000;

-- 4. 判定统计量(同发现段):每天 ≥ 30 名,偏 Spearman 控规模,按自然月平均,t = 月均 / 月标准差 × √月数
with rd(reading) as (values ('main'), ('literal')),
long as (
  select r.reading, f.factor, b.sym, b.d, f.v, b.y, b.size from rs_s691h_base b cross join rd r
  cross join lateral (values ('f01_oi_mcap', b.f01_oi_mcap), ('f03_doi30', b.f03_doi30), ('f07_taker7', b.f07_taker7),
    ('f08_mom30', b.f08_mom30), ('f09_mom7', b.f09_mom7), ('f11_vol30', b.f11_vol30)) as f(factor, v)
  where f.v is not null and (r.reading = 'literal' or b.has_oi)
),
ok_days as (select reading, factor, d from long group by 1, 2, 3 having count(*) >= 30),
ranked as (
  select l.reading, l.factor, l.d,
         rank() over (partition by l.reading, l.factor, l.d order by l.v) + (count(*) over (partition by l.reading, l.factor, l.d, l.v) - 1) / 2.0 as rv,
         rank() over (partition by l.reading, l.factor, l.d order by l.y) + (count(*) over (partition by l.reading, l.factor, l.d, l.y) - 1) / 2.0 as ry,
         rank() over (partition by l.reading, l.factor, l.d order by l.size) + (count(*) over (partition by l.reading, l.factor, l.d, l.size) - 1) / 2.0 as rs
  from long l join ok_days using (reading, factor, d)
),
daily as (select reading, factor, d, count(*) as n, corr(rv, ry) as r_vy, corr(rv, rs) as r_vs, corr(ry, rs) as r_ys from ranked group by 1, 2, 3),
daily2 as (select reading, factor, d, n, case when abs(r_vs) < 1 and abs(r_ys) < 1 then (r_vy - r_vs * r_ys) / sqrt((1 - r_vs * r_vs) * (1 - r_ys * r_ys)) end as ic from daily),
monthly as (select reading, factor, date_trunc('month', d)::date as m, avg(n) as n_names, avg(ic) as ic from daily2 group by 1, 2, 3)
select reading, factor, count(*) as n_months, round(avg(n_names)) as names, round(avg(ic)::numeric, 4) as mean_ic,
       round((avg(ic) / nullif(stddev_samp(ic), 0) * sqrt(count(ic)))::numeric, 2) as t_month,
       sum(case when ic > 0 then 1 else 0 end) as pos_months,
       string_agg(to_char(m, 'YYMM') || '=' || round(ic::numeric, 3), ' ' order by m) as months
from monthly group by 1, 2 order by 1, 2;

-- 5. 探索(不判):五因子等权秩合成的偏 IC 与五分位 —— 见台账 S-691 留出段结果「看到的」。
-- comp5 = 平均(percent_rank(−F3), percent_rank(F7), percent_rank(−F8), percent_rank(−F9), percent_rank(−F11)),只取五个都有定义的名字,每天 ≥ 30 名。
