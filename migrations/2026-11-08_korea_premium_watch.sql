-- 2026-11-08 · S-771 P(按币韩国溢价)的前向记录(src/data/signals/korea_premium_watch.py)。只描述,不进任何敞口。
-- 每个周一 t、每个币 i:P_i = ln(KRW 收盘_i / Binance 现货收盘_i) − ln(KRW 收盘_BTC / Binance 现货收盘_BTC),取 t−6 … t 的中位(≥ 5 天有效);
-- 截面 = 当天 Binance 现货有收盘且市值 ≥ 2,000 万;q = 截面五分位(5 = 韩国人多付得最多);结果 = t+1 收盘 → t+29 收盘相对 BTC,到期才有。
-- cohort:t ≥ 2026-11-09 = forward(S-771 的数据止于 2026-10);之前 = backfill(只作对照)。
-- S-784:S-771 的 P 口径依赖(中位取在价格上 ⇒ 不过;取在每天的溢价上 = 这里 ⇒ 过)⇒ 这个读法只能前向判(S-786)。
create table if not exists public.korea_premium_watch (
  d          date not null,
  symbol     text not null,
  p7         double precision not null,
  n_days     integer,
  mcap       double precision,
  q          integer check (q between 1 and 5),
  n_cs       integer,
  x28        double precision,
  cohort     text not null check (cohort in ('forward', 'backfill')),
  code_ref   text not null,
  settled_at timestamptz,
  created_at timestamptz not null default now(),
  primary key (d, symbol)
);
create index if not exists korea_premium_watch_d on public.korea_premium_watch (d desc);
alter table public.korea_premium_watch enable row level security;
grant select on public.korea_premium_watch to anon;
drop policy if exists lane_read on public.korea_premium_watch;
create policy lane_read on public.korea_premium_watch for select to anon using (true);

create or replace function public.korea_premium_rows(p_from date, p_to date)
returns table (d date, symbol text, p7 double precision, n_days integer, mcap double precision, q integer, n_cs integer, x28 double precision)
language sql stable set search_path = public, pg_temp set statement_timeout = '120s' as $fn$
with mon as (
  select t::date t from generate_series(p_from, p_to, interval '1 day') t where extract(isodow from t) = 1
),
asof as (select max(trade_date) mx from ohlcv_daily where source = 'binance_hist'),
g as (
  select o.symbol, o.trade_date d, o.close from ohlcv_daily o
  where o.source = 'binance_hist' and o.close > 0 and o.trade_date between p_from - 6 and p_to + 29
),
u as (select x.symbol, x.d, x.c from upbit_daily x where x.c > 0 and x.d between p_from - 6 and p_to),
dp as (
  select u.symbol, u.d, ln(u.c / g.close) - ln(ub.c / gb.close) p
  from u join g on g.symbol = u.symbol and g.d = u.d
  join u ub on ub.symbol = 'BTC' and ub.d = u.d
  join g gb on gb.symbol = 'BTC' and gb.d = u.d
  where u.symbol <> 'BTC'
),
sig as (
  select m.t, dp.symbol, percentile_cont(0.5) within group (order by dp.p) p7, count(*)::int n_days
  from mon m join dp on dp.d between m.t - 6 and m.t
  group by m.t, dp.symbol having count(*) >= 5
),
xs as (
  select s.t, s.symbol, s.p7, s.n_days, a.mcap
  from sig s
  join asset_mcap_daily a on a.symbol = s.symbol and a.d = s.t
  join g on g.symbol = s.symbol and g.d = s.t
  where a.mcap >= 2e7
),
ranked as (
  select xs.*, ntile(5) over (partition by xs.t order by xs.p7)::int q, count(*) over (partition by xs.t)::int n_cs from xs
),
out as (
  select r.*,
    case when r.t + 29 <= (select mx from asof) then
      (e1.close / e0.close - 1) - (b1.close / b0.close - 1) end x28
  from ranked r
  left join g e0 on e0.symbol = r.symbol and e0.d = r.t + 1
  left join g e1 on e1.symbol = r.symbol and e1.d = r.t + 29
  left join g b0 on b0.symbol = 'BTC' and b0.d = r.t + 1
  left join g b1 on b1.symbol = 'BTC' and b1.d = r.t + 29
)
select t, symbol, p7, n_days, mcap, q, n_cs, x28 from out order by t, symbol
$fn$;
revoke all on function public.korea_premium_rows(date, date) from public, anon, authenticated;
grant execute on function public.korea_premium_rows(date, date) to service_role;
