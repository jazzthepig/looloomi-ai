-- S-694(台账,预注册 2026-10-28 12:04 UTC):① 面板(24 名)里落在宽宇宙 S-691 五因子合成最差五分之一的名字权重减半。Seth 版;C 道 T-209 盲复算。
-- 研究临时表(用完删):rs_s694_comp(每周一的宽宇宙合成)、rs_s694_w(面板 × 周:周收益、市值、档位)、rs_s694_rand(随机对照)。
-- 依赖 S-691 的研究临时表 rs_s691_px / rs_s691h_px / rs_s691_oi / rs_s691h_oi / rs_s691_kept(定义见 s691_factor_zoo_discovery.sql、s691_holdout.sql)。

-- 1. 每周一的宽宇宙合成(只用 d 收盘已知的)
create table rs_s694_comp as
with mondays as (select d::date as d from generate_series('2023-01-02'::date, '2026-10-19'::date, interval '7 days') d),
px as (select sym, d, price, mcap, vol30, nlr30 from rs_s691_px where d <= '2024-11-30'
       union all select sym, d, price, mcap, vol30, nlr30 from rs_s691h_px where d >= '2024-12-01'),
oi as (select sym, d, oi_value_close, oi_close, tkr7, ntkr7 from rs_s691_oi where d <= '2024-11-30'
       union all select sym, d, oi_value_close, oi_close, tkr7, ntkr7 from rs_s691h_oi where d >= '2024-12-01'),
btc as (select d, price from asset_mcap_daily where source = 'coingecko_pro_market_chart' and coin_id = 'bitcoin' and d >= '2022-11-01'),
f as (
  select x.sym, x.d, ln(o.oi_close / o30.oi_close) as f3, case when o.ntkr7 >= 5 then o.tkr7 end as f7,
    (x.price / x30.price - 1) - (b.price / b30.price - 1) as f8, (x.price / x7.price - 1) - (b.price / b7.price - 1) as f9,
    case when x.nlr30 >= 25 then x.vol30 end as f11
  from px x join mondays m on m.d = x.d
  join oi o on o.sym = x.sym and o.d = x.d and o.oi_value_close > 0 and o.oi_close > 0
  join oi o30 on o30.sym = x.sym and o30.d = x.d - 30 and o30.oi_close > 0
  join px x30 on x30.sym = x.sym and x30.d = x.d - 30 and x30.price > 0
  join px x7 on x7.sym = x.sym and x7.d = x.d - 7 and x7.price > 0
  join btc b on b.d = x.d join btc b30 on b30.d = x.d - 30 join btc b7 on b7.d = x.d - 7
  where x.mcap >= 20000000),
c as (select * from f where f7 is not null and f11 is not null),
ok as (select d from c group by d having count(*) >= 30),
r as (select c.sym, c.d, (percent_rank() over w3 + percent_rank() over w7 + percent_rank() over w8 + percent_rank() over w9 + percent_rank() over w11) / 5 as comp
  from c join ok using (d)
  window w3 as (partition by c.d order by -f3), w7 as (partition by c.d order by f7), w8 as (partition by c.d order by -f8),
         w9 as (partition by c.d order by -f9), w11 as (partition by c.d order by -f11))
select sym, d, comp, ntile(5) over (partition by d order by comp) as q5, count(*) over (partition by d) as n from r;

-- 2. 面板 × 周(CG 日收盘,周一到下周一)
create table rs_s694_w as
with panel(sym, ord) as (select * from unnest(array['BTC','ETH','SOL','BNB','XRP','DOGE','ADA','AVAX','LINK','DOT','LTC','TRX','ATOM','NEAR','APT','ARB','OP','SUI','UNI','AAVE','INJ','FIL','ETC','BCH']) with ordinality),
weeks as (select distinct d as wk from rs_s694_comp),
px as (select upper(symbol) sym, d, price, mcap from asset_mcap_daily where source='coingecko_pro_market_chart' and upper(symbol) in (select sym from panel) and d >= '2023-01-01')
select w.wk, p.sym, p.ord, (b.price / a.price - 1) as r, a.mcap, c.q5
from weeks w cross join panel p
join px a on a.sym = p.sym and a.d = w.wk join px b on b.sym = p.sym and b.d = w.wk + 7
left join rs_s694_comp c on c.sym = p.sym and c.d = w.wk
where a.price > 0 and b.price > 0 and a.mcap > 0;

-- 3. 组合:市值加权 / 等权,减半 / 剔除;成本 10 bp × Σ|目标 − 上周漂移后权重|;按段年化(52 / 周数)
with x as (select wk, sym, r, mcap, q5 from rs_s694_w),
wt as (
  select wk, sym, r, q5,
    mcap / sum(mcap) over (partition by wk) as w_b,
    (mcap * case when q5 = 1 then 0.5 else 1 end) / sum(mcap * case when q5 = 1 then 0.5 else 1 end) over (partition by wk) as w_t,
    1.0 / count(*) over (partition by wk) as e_b,
    (case when q5 = 1 then 0.5 else 1 end) / sum(case when q5 = 1 then 0.5 else 1 end) over (partition by wk) as e_t,
    (mcap * case when q5 = 1 then 0 else 1 end) / sum(mcap * case when q5 = 1 then 0 else 1 end) over (partition by wk) as z_t
  from x),
pr as (select wk, sum(w_b*r) rb, sum(w_t*r) rt, sum(e_b*r) reb, sum(e_t*r) ret, sum(z_t*r) rzt from wt group by wk),
dr as (select w.wk + 7 as wk, w.sym, w.w_b*(1+w.r)/(1+p.rb) db, w.w_t*(1+w.r)/(1+p.rt) dt, w.e_b*(1+w.r)/(1+p.reb) deb,
          w.e_t*(1+w.r)/(1+p.ret) det, w.z_t*(1+w.r)/(1+p.rzt) dzt from wt w join pr p using (wk)),
tv as (select coalesce(w.wk, d.wk) wk, sum(abs(coalesce(w.w_b,0)-coalesce(d.db,0))) tb, sum(abs(coalesce(w.w_t,0)-coalesce(d.dt,0))) tt,
          sum(abs(coalesce(w.e_b,0)-coalesce(d.deb,0))) teb, sum(abs(coalesce(w.e_t,0)-coalesce(d.det,0))) tet,
          sum(abs(coalesce(w.z_t,0)-coalesce(d.dzt,0))) tzt
       from wt w full join dr d on d.wk = w.wk and d.sym = w.sym group by 1),
net as (select p.wk, p.rb - 0.001*t.tb nb, p.rt - 0.001*t.tt nt, p.reb - 0.001*t.teb neb, p.ret - 0.001*t.tet net_, p.rzt - 0.001*t.tzt nzt,
               p.rb gb, p.rt gt, p.reb geb, p.ret get from pr p join tv t using (wk)),
seg as (select case when wk <= '2024-11-30' then 'h1' else 'h2' end seg, * from net union all select 'all', * from net)
select seg, count(*) weeks,
  round((exp(sum(ln(1+nt)) - sum(ln(1+nb))) ^ (52.0/count(*)) - 1)::numeric, 4) cw_excess_ann_net,
  round((exp(sum(ln(1+gt)) - sum(ln(1+gb))) ^ (52.0/count(*)) - 1)::numeric, 4) cw_excess_ann_gross,
  round((exp(sum(ln(1+nb)))^(52.0/count(*)) - 1)::numeric, 4) cw_base_ann,
  round((exp(sum(ln(1+net_)) - sum(ln(1+neb))) ^ (52.0/count(*)) - 1)::numeric, 4) ew_excess_ann_net,
  round((exp(sum(ln(1+get)) - sum(ln(1+geb))) ^ (52.0/count(*)) - 1)::numeric, 4) ew_excess_ann_gross,
  round((exp(sum(ln(1+nzt)) - sum(ln(1+nb))) ^ (52.0/count(*)) - 1)::numeric, 4) cw_drop_excess_ann_net,
  round((stddev_samp(nt - nb) * sqrt(52))::numeric, 4) cw_te
from seg group by seg order by seg;

-- 4. 随机对照(毛口径):每周从有合成值的面板名字里随机挑同样个数减半,1,000 次(setseed 0.694)
select setseed(0.694);
create table rs_s694_rand as
with x as (select wk, sym, r, mcap, q5, count(*) filter (where q5 = 1) over (partition by wk) k from rs_s694_w),
dr as (select g.i as draw, x.*, case when q5 is not null then row_number() over (partition by g.i, x.wk order by (q5 is null), random()) end rn
       from generate_series(1, 1000) g(i) cross join x)
select draw, wk, sum(mcap * case when rn <= k then 0.5 else 1 end * r) / sum(mcap * case when rn <= k then 0.5 else 1 end) as rt
from dr group by draw, wk;
-- 实际 vs 随机:见台账 S-694 结果(实际对数超额 0.052,随机 87 分位;前段 54、后段 95)
