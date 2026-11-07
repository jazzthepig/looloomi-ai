-- 2026-11-08 · metrics 日档 / 资金费月档的宇宙 v2:binance_hist 现货名单 ∪ 全部 coin 类 U 本位永续。
-- v1(11-07 13:30 生效、14:58 撤回)的两个错:① 用 coalesce(kind, 'coin') ⇒ 没分类的股票永续(ABBV / PFE / MELI …)混进来;
-- ② 只上永续的币不在 assets ⇒ funding_history 外键整批失败。还有一个运行时的:解析在事件循环里同步跑(代码已改到线程、预算降,
-- 见 binance_vision*.py)。这里:**只取 kind = 'coin'**;先把这些名字登记进 assets(class 空、三个 monitor 全 false ——
-- 与已有 612 行「class 为空」的登记一样,没有任何代码按登记表路由);再换两张计划视图。
-- 前提:binance_vision 线程化 + 预算的提交已经部署(否则别应用这份)。
insert into public.assets (asset_id, symbol, name, class, listed_at, monitor_daily, monitor_hourly, monitor_funding)
select b.symbol, b.symbol, b.symbol, null, min(b.d), false, false, false
from public.perp_bv_daily b
join public.perp_bv_pairs pp on pp.pair = b.pair and pp.kind = 'coin'
where b.pair = b.symbol || 'USDT'
  and not exists (select 1 from public.assets a where a.asset_id = b.symbol)
group by b.symbol
on conflict (asset_id) do nothing;

create or replace view public.deriv_metrics_plan with (security_invoker = true) as
with o as (
  select symbol, min(trade_date) first_d, max(trade_date) last_d
  from public.ohlcv_daily
  where source = 'binance_hist' and symbol <> all (array['USDC', 'BTCDOM', 'DEFI'])
  group by symbol
),
p as (
  select b.symbol, min(b.d) first_d, max(b.d) last_d
  from public.perp_bv_daily b
  join public.perp_bv_pairs pp on pp.pair = b.pair and pp.kind = 'coin'
  where b.pair = b.symbol || 'USDT'
  group by b.symbol
),
u as (
  select coalesce(o.symbol, p.symbol) symbol, least(o.first_d, p.first_d) first_d, greatest(o.last_d, p.last_d) last_d
  from o full join p using (symbol)
)
select u.symbol, greatest(u.first_d, date '2020-09-01') as target_start, u.last_d, c.min_d, c.max_d
from u
left join (select symbol, min(d) min_d, max(d) max_d from public.deriv_metrics_daily group by symbol) c using (symbol);

create or replace view public.funding_vision_plan with (security_invoker = true) as
with u as (
  select ohlcv_daily.symbol,
         greatest(date '2020-01-01', date_trunc('month', min(ohlcv_daily.trade_date))::date) as start_m
  from public.ohlcv_daily
  where ohlcv_daily.source = 'binance_hist' and ohlcv_daily.symbol <> all (array['USDC', 'BTCDOM', 'DEFI'])
  group by ohlcv_daily.symbol
  union
  select short_paper_tickets.symbol, date_trunc('month', min(short_paper_tickets.entry_d))::date as start_m
  from public.short_paper_tickets
  where short_paper_tickets.entry_d is not null
  group by short_paper_tickets.symbol
  union
  select b.symbol, greatest(date '2020-01-01', date_trunc('month', min(b.d))::date) as start_m
  from public.perp_bv_daily b
  join public.perp_bv_pairs pp on pp.pair = b.pair and pp.kind = 'coin'
  where b.pair = b.symbol || 'USDT'
  group by b.symbol
),
u1 as (select u.symbol, min(u.start_m) as start_m from u group by u.symbol),
have as (
  select funding_history.symbol, date_trunc('month', funding_history.funding_time at time zone 'utc')::date as m
  from public.funding_history
  where funding_history.venue = 'binance_perp'
  group by 1, 2
),
months as (
  select u1.symbol, g.g::date as m
  from u1
  cross join lateral generate_series(u1.start_m::timestamptz,
                                     (date_trunc('month', now() at time zone 'utc') - interval '1 mon')::date::timestamptz,
                                     interval '1 mon') g(g)
)
select symbol, m as month
from months m
where not exists (select 1 from have h where h.symbol = m.symbol and h.m = m.m)
  and not exists (select 1 from public.funding_vision_absent a where a.symbol = m.symbol and a.month = m.m);
