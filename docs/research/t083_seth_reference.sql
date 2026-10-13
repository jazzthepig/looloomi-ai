-- T-083 / M-557 second source (Seth, 10-13). Same basis as S-555 dx_cap_breadth, full price history (no mcap
-- filter on the price rows), ZEC excluded, N=50, L=30, weekly Sunday rebalance, cash 4%/yr, GROSS (no costs).
--   main = cap_breadth: every top-N name at its market-cap share × breadth (npos / nmom)  ⇒  r(t) = w(t)·R_cap(t)
--   A    = cap_full × the segment's mean w (constant exposure, same names)
-- Result 10-13 (read-only on Supabase):
--   S1 (2023-01-01 → 2024-12-29, 105 wk): main +164.0% / maxDD −14.2% / Sharpe 1.78   A +144.2% / −14.2% / 1.86   mean w 0.508
--   S2 (2025-01-05 → 2026-10-04,  92 wk): main  +2.7% / maxDD −27.2% / Sharpe 0.17   A  −3.5% / −26.1% / −0.01  mean w 0.420
-- Random-timing control B for this definition: shuffle w(t) in 4-week blocks, r_B(t) = w(π(t))·R_cap(t).
with elig as (
  select distinct coin_id from asset_mcap_daily
  where source = 'coingecko_pro_market_chart' and d >= '2022-12-01' and mcap >= 2e8
    and coin_id not in ('tether','usd-coin','dai','ethena-usde','first-digital-usd','usds','paypal-usd',
                        'binance-usd','true-usd','frax','usdd','pax-dollar','zcash')
),
pxd as (
  select distinct on (a.coin_id, a.d) a.coin_id, a.d, a.price, a.mcap
  from asset_mcap_daily a join elig using (coin_id)
  where a.source = 'coingecko_pro_market_chart' and a.d >= '2022-09-01' and a.price > 0
  order by a.coin_id, a.d, a.mcap desc nulls last
),
ret as (
  select coin_id, d, price, mcap,
         case when d - lag(d) over w = 1 then price / lag(price) over w - 1 end r
  from pxd window w as (partition by coin_id order by d)
),
vol as (
  select coin_id, d, price, mcap,
         stddev_samp(r) over (partition by coin_id order by d rows between 29 preceding and current row) vol30,
         count(r) over (partition by coin_id order by d rows between 29 preceding and current row) nvol
  from ret
),
snap as (
  select v.d s, v.coin_id, v.price p0, v.mcap, n.price p1, a.price p14, b.price p30, c.price p60
  from vol v
  left join pxd n on n.coin_id = v.coin_id and n.d = v.d + 7
  left join pxd a on a.coin_id = v.coin_id and a.d = v.d - 14
  left join pxd b on b.coin_id = v.coin_id and b.d = v.d - 30
  left join pxd c on c.coin_id = v.coin_id and c.d = v.d - 60
  where extract(isodow from v.d) = 7 and v.d >= '2023-01-01' and v.d <= (select max(d) - 7 from pxd)
    and v.mcap >= 2e8 and not (v.nvol >= 20 and v.vol30 < 0.005)
),
ranked as (
  select *, row_number() over (partition by s order by mcap desc) rk, coalesce(p1 / p0 - 1, 0) rw
  from snap
),
params(variant, n, l, mode) as (values ('cb', 50, 30, 'cap_breadth'), ('cf', 50, 30, 'cap_full')),
uni as (
  select p.variant, p.n, p.l, p.mode, r.s, r.coin_id, r.mcap, r.rw,
         case p.l when 14 then r.p0 / r.p14 - 1 when 30 then r.p0 / r.p30 - 1 when 60 then r.p0 / r.p60 - 1 end mom
  from params p join ranked r on r.rk <= p.n
),
agg as (
  select variant, s, count(mom) nmom, count(*) filter (where mom > 0) npos,
         sum(mom) filter (where mom > 0) smom, sum(mcap) scap, count(*) nall
  from uni group by variant, s
),
w as (
  select u.variant, u.s, u.coin_id, u.rw,
    case u.mode
      when 'mom_breadth' then case when u.mom > 0 then u.mom / a.smom * a.npos / nullif(a.nmom, 0) else 0 end
      when 'ew_breadth'  then case when u.mom > 0 then 1.0 / a.npos * a.npos / nullif(a.nmom, 0) else 0 end
      when 'cap_breadth' then u.mcap / a.scap * coalesce(a.npos::float / nullif(a.nmom, 0), 0)
      when 'mom_full'    then case when u.mom > 0 then u.mom / a.smom else 0 end
      when 'cap_full'    then u.mcap / a.scap
      when 'ew_full'     then 1.0 / a.nall
    end wt
  from uni u join agg a using (variant, s)
),
port as (
  select variant, s, sum(wt * rw) gross_risky, sum(wt) w_risky from w group by variant, s
),
seg as (
  select *, case when s + 1 <= '2024-12-31' then 'S1' else 'S2' end sg from port
),
ex as (select sg, avg(w_risky) e from seg where variant = 'cb' group by sg),
rr as (
  select 'main' arm, sg, s, gross_risky + (1 - w_risky) * 0.000767 r, w_risky from seg where variant = 'cb'
  union all
  select 'A', c.sg, c.s, ex.e * c.gross_risky + (1 - ex.e) * 0.000767, ex.e from seg c join ex using (sg) where c.variant = 'cf'
),
nav as (select *, exp(sum(ln(1 + r)) over (partition by arm, sg order by s)) nv from rr),
dd as (select *, nv / greatest(1, max(nv) over (partition by arm, sg order by s rows between unbounded preceding and current row)) - 1 ddv from nav)
select arm, sg, count(*) wks, round((exp(sum(ln(1 + r))) - 1)::numeric, 4) total_gross, round(min(ddv)::numeric, 4) maxdd,
       round((avg(r) / nullif(stddev_samp(r), 0) * sqrt(52))::numeric, 2) sharpe, round(avg(w_risky)::numeric, 3) avg_exp
from dd group by arm, sg order by sg, arm
;
