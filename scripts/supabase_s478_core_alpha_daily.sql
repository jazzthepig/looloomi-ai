-- S-478 (2026-10-04, migration s478_core_alpha_daily): the S-472 weighting SQL as a read-only function, for lanes
-- (T-045 / T-047) through GET /api/v1/research/core-alpha. alpha in {0, 0.5, 1}, max 40% per coin, 24 names, daily
-- rebalance, asset_mcap_daily prices and d-1 market caps. Reproduces S-472 exactly (2023-01-01..: +144% / +209% / +241%).
create or replace function public.core_alpha_daily(p_start date)
returns table(alpha double precision, d date, ret double precision, w_btc double precision, n integer)
language sql stable
set search_path = public, pg_temp
as $$
  with p as (
    select symbol, a.d, price, mcap, lag(price) over w pp, lag(mcap) over w pm, lag(a.d) over w pd
    from asset_mcap_daily a
    where symbol in ('BTC','ETH','SOL','BNB','XRP','DOGE','ADA','AVAX','LINK','DOT','LTC','TRX','ATOM','NEAR','APT','ARB','OP','SUI','UNI','AAVE','INJ','FIL','ETC','BCH')
      and a.d >= p_start - 10
    window w as (partition by symbol order by a.d)),
  r as (select symbol, p.d, price/pp - 1 as ret, pm from p
        where pd = p.d - 1 and pp > 0 and pm > 0 and price/pp - 1 between -0.9 and 5 and p.d >= p_start),
  a as (select unnest(array[0.0, 0.5, 1.0]::double precision[]) alpha),
  cw as (select a.alpha, r.*, power(pm, a.alpha) / sum(power(pm, a.alpha)) over (partition by a.alpha, r.d) w0
         from r cross join a),
  ex as (select alpha, cw.d, sum(greatest(w0 - 0.4, 0)) excess, sum(case when w0 < 0.4 then w0 else 0 end) rest
         from cw group by 1,2),
  cw2 as (select cw.alpha, cw.d, cw.symbol, cw.ret,
                 case when w0 >= 0.4 then 0.4 else w0 * (1 + ex.excess / nullif(ex.rest,0)) end w1
          from cw join ex using (alpha, d))
  select alpha, cw2.d, sum(w1*ret), max(case when symbol='BTC' then w1 end), count(*)::int
  from cw2 group by 1,2 order by 1,2
$$;
revoke all on function public.core_alpha_daily(date) from public, anon, authenticated;
grant execute on function public.core_alpha_daily(date) to service_role;
