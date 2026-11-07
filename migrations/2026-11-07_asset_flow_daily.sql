-- 2026-11-07 · 按币的资金面空间(src/data/state/asset_flow.py;HIGH_DIM_ONTOLOGY §5 的 Asset 空间缺的「原因维」)。
-- 每个 (币, 日):11 个当天收盘可知的资金面 / 行为量 + 当天截面里的百分位 + 11 维向量(百分位居中到 [−1, 1])
-- + 之后 7 / 30 天相对当天截面等权的超额(结果列,到期才有;查询时必须只用 d' + H < 查询日的行)。
-- 宇宙:Binance USDT 永续,metrics 当天 ≥ 200 个点且 OI / 多空比 / 主动买卖比都有,7 日均成交额 ≥ 200 万美元。2022-06 起。
create or replace view public.asset_flow_daily_live as
with m as (
  select symbol, d, oi_close, global_acct_ratio_close g, top_pos_ratio_close tp, taker_ratio_mean tk
  from public.deriv_metrics_daily
  where d >= date '2022-06-01' and n_points >= 200 and oi_close > 0 and global_acct_ratio_close > 0
    and top_pos_ratio_close > 0 and taker_ratio_mean > 0
),
mw as (
  select symbol, d, g, tp, oi_close,
    first_value(oi_close) over w8 oi_7, first_value(d) over w8 d_oi7,
    avg(ln(tk)) over w7 taker7
  from m
  window w8 as (partition by symbol order by d range between interval '7 days' preceding and current row),
         w7 as (partition by symbol order by d range between interval '6 days' preceding and current row)
),
syms as (select distinct symbol from m union select 'BTC'),
px as (   -- 只取有 metrics 的合约(+ BTC);结果列用它的全部日线(不受 metrics 过滤),死币用窗口内最后一个收盘
  select p.symbol, p.d, p.o, p.h, p.c, p.qv from public.perp_bv_daily p
  where p.d >= date '2022-02-01' and p.pair = p.symbol || 'USDT' and p.c > 0 and p.symbol in (select symbol from syms)
),
asof as (select max(d) mx from px),
pxl as (
  select symbol, d, o, h, c, qv,
    ln(c / nullif(lag(c) over s, 0)) * case when d - lag(d) over s = 1 then 1 end lr
  from px window s as (partition by symbol order by d)
),
pxf as (
  select symbol, d, c, qv,
    first_value(c) over w8 c_7, first_value(d) over w8 d_7,
    first_value(c) over w31 c_30, first_value(d) over w31 d_30,
    avg(qv) over w7 qv7, avg(qv) over w60 qv60, count(*) over w60 n60,
    max(h) over w90 h90,
    stddev_samp(lr) over w7 vol7, stddev_samp(lr) over w30 vol30, count(lr) over w30 n30,
    first_value(o) over n1 o_1, first_value(d) over n1 d_1,
    last_value(c) over f7 c_f7, last_value(d) over f7 d_f7,
    last_value(c) over f30 c_f30, last_value(d) over f30 d_f30
  from pxl
  window w8  as (partition by symbol order by d range between interval '7 days' preceding and current row),
         w31 as (partition by symbol order by d range between interval '30 days' preceding and current row),
         w7  as (partition by symbol order by d range between interval '6 days' preceding and current row),
         w30 as (partition by symbol order by d range between interval '29 days' preceding and current row),
         w60 as (partition by symbol order by d range between interval '59 days' preceding and current row),
         w90 as (partition by symbol order by d range between interval '89 days' preceding and current row),
         n1  as (partition by symbol order by d range between interval '1 day' following and interval '1 day' following),
         f7  as (partition by symbol order by d range between interval '1 day' following and interval '7 days' following),
         f30 as (partition by symbol order by d range between interval '1 day' following and interval '30 days' following)
),
fd as (
  select symbol, d, avg(funding_rate * n * 365) over w7 fund7
  from public.v_funding_daily where d >= date '2022-05-01'
  window w7 as (partition by symbol order by d range between interval '6 days' preceding and current row)
),
raw as (
  select mw.symbol, mw.d,
    fd.fund7,
    case when mw.d - mw.d_oi7 between 6 and 8 then ln(mw.oi_close / mw.oi_7) end doi7,
    ln(mw.g) crowd,
    ln(mw.tp) - ln(mw.g) smart,
    mw.taker7,
    case when p.d - p.d_7 between 6 and 8 and b.d - b.d_7 between 6 and 8 then ln(p.c / p.c_7) - ln(b.c / b.c_7) end mom7,
    case when p.d - p.d_30 between 28 and 31 and b.d - b.d_30 between 28 and 31 then ln(p.c / p.c_30) - ln(b.c / b.c_30) end mom30,
    case when p.n30 >= 25 then p.vol30 end vol30,
    case when p.n30 >= 25 and p.vol30 > 0 then p.vol7 / p.vol30 end vratio,
    case when p.n60 >= 50 and p.qv60 > 0 and p.qv7 > 0 then ln(p.qv7 / p.qv60) end turn,
    ln(p.c / nullif(p.h90, 0)) dd90,
    p.qv7,
    case when p.d_1 = p.d + 1 and p.o_1 > 0 and p.d + 7 <= (select mx from asof) then ln(p.c_f7 / p.o_1) end r7,
    case when p.d_1 = p.d + 1 and p.o_1 > 0 and p.d + 30 <= (select mx from asof) then ln(p.c_f30 / p.o_1) end r30,
    case when p.d + 30 <= (select mx from asof) then p.d_f30 < p.d + 27 end trunc30
  from mw
  join pxf p on p.symbol = mw.symbol and p.d = mw.d
  join pxf b on b.symbol = 'BTC' and b.d = mw.d
  left join fd on fd.symbol = mw.symbol and fd.d = mw.d
  where p.qv7 >= 2e6
),
cs as (
  select raw.*,
    count(*) over (partition by d) n_cs,
    case when fund7  is not null then percent_rank() over (partition by d, fund7  is null order by fund7)  end q_fund7,
    case when doi7   is not null then percent_rank() over (partition by d, doi7   is null order by doi7)   end q_doi7,
    case when crowd  is not null then percent_rank() over (partition by d, crowd  is null order by crowd)  end q_crowd,
    case when smart  is not null then percent_rank() over (partition by d, smart  is null order by smart)  end q_smart,
    case when taker7 is not null then percent_rank() over (partition by d, taker7 is null order by taker7) end q_taker7,
    case when mom7   is not null then percent_rank() over (partition by d, mom7   is null order by mom7)   end q_mom7,
    case when mom30  is not null then percent_rank() over (partition by d, mom30  is null order by mom30)  end q_mom30,
    case when vol30  is not null then percent_rank() over (partition by d, vol30  is null order by vol30)  end q_vol30,
    case when vratio is not null then percent_rank() over (partition by d, vratio is null order by vratio) end q_vratio,
    case when turn   is not null then percent_rank() over (partition by d, turn   is null order by turn)   end q_turn,
    case when dd90   is not null then percent_rank() over (partition by d, dd90   is null order by dd90)   end q_dd90,
    r7 - avg(r7) over (partition by d) x7,
    r30 - avg(r30) over (partition by d) x30
  from raw
)
select symbol, d, n_cs, fund7, doi7, crowd, smart, taker7, mom7, mom30, vol30, vratio, turn, dd90, qv7,
  q_fund7, q_doi7, q_crowd, q_smart, q_taker7, q_mom7, q_mom30, q_vol30, q_vratio, q_turn, q_dd90,
  case when q_fund7 is not null and q_doi7 is not null and q_crowd is not null and q_smart is not null and q_taker7 is not null
        and q_mom7 is not null and q_mom30 is not null and q_vol30 is not null and q_vratio is not null and q_turn is not null
        and q_dd90 is not null
       then array[2*q_fund7-1, 2*q_doi7-1, 2*q_crowd-1, 2*q_smart-1, 2*q_taker7-1, 2*q_mom7-1, 2*q_mom30-1,
                  2*q_vol30-1, 2*q_vratio-1, 2*q_turn-1, 2*q_dd90-1]::real[]::vector(11) end vec,
  r7, r30, x7, x30, trunc30
from cs;

grant select on public.asset_flow_daily_live to service_role;
create materialized view if not exists public.asset_flow_daily as select * from public.asset_flow_daily_live;
create unique index if not exists asset_flow_daily_uq on public.asset_flow_daily (symbol, d);
create index if not exists asset_flow_daily_d on public.asset_flow_daily (d);
grant select on public.asset_flow_daily to anon, authenticated, service_role;

create or replace function public.refresh_asset_flow() returns integer
language plpgsql security definer set search_path = public, pg_temp set statement_timeout = '600s' as $$   -- 11-07:宇宙 v2 之后行数会翻倍
begin
  refresh materialized view concurrently public.asset_flow_daily;
  return (select count(*) from public.asset_flow_daily);
end $$;
revoke all on function public.refresh_asset_flow() from public, anon, authenticated;
grant execute on function public.refresh_asset_flow() to service_role;

-- 近邻:只在「结果已到期」的历史行里找(d' + H < 查询日)—— 时点安全由函数保证,不靠调用方自觉。
create or replace function public.asset_flow_knn(p_symbol text, p_d date, p_k integer default 100, p_h integer default 30)
returns table(symbol text, d date, dist double precision, x7 double precision, x30 double precision)
language sql stable security invoker set search_path = public, pg_temp as $$
  with q as (select a.vec from public.asset_flow_daily a where a.symbol = upper(p_symbol) and a.d = p_d and a.vec is not null)
  select a.symbol, a.d, (a.vec <-> q.vec)::float8, a.x7, a.x30
  from public.asset_flow_daily a, q
  where a.vec is not null and a.d < p_d - greatest(p_h, 7)
    and (case when p_h <= 7 then a.x7 else a.x30 end) is not null
  order by a.vec <-> q.vec
  limit greatest(1, least(coalesce(p_k, 100), 1000))
$$;
revoke all on function public.asset_flow_knn(text, date, integer, integer) from public;
grant execute on function public.asset_flow_knn(text, date, integer, integer) to anon, authenticated, service_role;
