-- 2026-11-08 · S-726 / S-777 / S-781 squeeze(与 flush)的前向记录(src/data/signals/crowding_watch.py)。只描述,不进任何敞口。
-- 一个 (类, 合约, 事件日) 一行;cohort = forward(2026-11-05 起:S-781 用的数据止于 2026-11-04)/ backfill(只作对照,= S-781 的样本)。
-- 结果口径照抄 S-726:d+1 开盘 → d+1 / d+7 / d+30 收盘(窗口内最后一个收盘),减同一进出窗口的时点等权篮(宇宙 = crowding_events 的 uni)。
create table if not exists public.crowding_watch (
  kind        text not null check (kind in ('squeeze', 'flush')),
  symbol      text not null,
  d           date not null,
  fund_pct    double precision,
  ret         double precision,
  atr_thr     double precision,
  qv_mult     double precision,
  cohort      text not null check (cohort in ('forward', 'backfill')),
  x1          double precision,
  x7          double precision,
  x30         double precision,
  basket_n    integer,
  code_ref    text not null,
  settled_at  timestamptz,
  created_at  timestamptz not null default now(),
  primary key (kind, symbol, d)
);
create index if not exists crowding_watch_d on public.crowding_watch (d desc);
alter table public.crowding_watch enable row level security;
grant select on public.crowding_watch to anon;
drop policy if exists lane_read on public.crowding_watch;
create policy lane_read on public.crowding_watch for select to anon using (true);

-- 事件(干净口径)+ 到期的超额。p_from 之前的事件不返回;结果只用 p_from 之后的日线(窗口都是向后的)。
-- crowding_events 每次都要扫全史(扩张分位与去重需要),~30 秒 ⇒ 调用方一天一次。
create or replace function public.crowding_watch_rows(p_from date)
returns table (kind text, symbol text, d date, fund_pct double precision, ret double precision, atr_thr double precision,
               qv_mult double precision, x1 double precision, x7 double precision, x30 double precision, basket_n integer)
language sql stable set search_path = public, pg_temp set statement_timeout = '300s' as $fn$
with asof as (select max(d) mx from perp_bv_daily),
ev as (select * from public.crowding_events(p_from, (select mx from asof), true)),
uni as (
  select distinct p.symbol from perp_bv_pairs p
  where p.kind = 'coin' or (coalesce(nullif(btrim(p.kind), ''), '') = '' and p.dead_from is not null)
),
px as (select b.symbol, b.d, b.o, b.c from perp_bv_daily b join uni u on u.symbol = b.symbol where b.d >= p_from),
pf as (
  select symbol, d, first_value(o) over n1 o1, first_value(d) over n1 d1,
    last_value(c) over n1 c1, last_value(c) over f7 c7, last_value(c) over f30 c30
  from px
  window n1  as (partition by symbol order by d range between interval '1 day' following and interval '1 day' following),
         f7  as (partition by symbol order by d range between interval '1 day' following and interval '7 days' following),
         f30 as (partition by symbol order by d range between interval '1 day' following and interval '30 days' following)
),
r as (
  select symbol, d,
    case when d1 = d + 1 and o1 > 0 and d + 1  <= (select mx from asof) then c1  / o1 - 1 end r1,
    case when d1 = d + 1 and o1 > 0 and d + 7  <= (select mx from asof) then c7  / o1 - 1 end r7,
    case when d1 = d + 1 and o1 > 0 and d + 30 <= (select mx from asof) then c30 / o1 - 1 end r30
  from pf where d in (select ev.d from ev)
),
x as (
  select symbol, d, r1 - avg(r1) over w x1, r7 - avg(r7) over w x7, r30 - avg(r30) over w x30, count(r1) over w nb
  from r window w as (partition by d)
)
select ev.kind, ev.symbol, ev.d, ev.fund_pct, ev.ret, ev.atr_thr, ev.qv_mult, x.x1, x.x7, x.x30, x.nb::int
from ev left join x on x.symbol = ev.symbol and x.d = ev.d
order by ev.kind, ev.d, ev.symbol
$fn$;
revoke all on function public.crowding_watch_rows(date) from public, anon, authenticated;
grant execute on function public.crowding_watch_rows(date) to service_role;
