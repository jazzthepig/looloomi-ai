with elig as (
  select distinct coin_id from asset_mcap_daily
  where source = 'coingecko_pro_market_chart' and d >= '2022-12-01' and mcap >= 2e8
    and coin_id not in ('tether','usd-coin','dai','ethena-usde','first-digital-usd','usds','paypal-usd',
                        'binance-usd','true-usd','frax','usdd','pax-dollar')
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
params(variant, n, l, mode) as (values ('nb_N30_L14', 30, 14, 'mom_breadth'), ('nb_N30_L30', 30, 30, 'mom_breadth'), ('nb_N30_L60', 30, 60, 'mom_breadth'), ('nb_N50_L14', 50, 14, 'mom_breadth'), ('nb_N50_L30', 50, 30, 'mom_breadth'), ('nb_N50_L60', 50, 60, 'mom_breadth'), ('nb_N75_L14', 75, 14, 'mom_breadth'), ('nb_N75_L30', 75, 30, 'mom_breadth'), ('nb_N75_L60', 75, 60, 'mom_breadth'), ('nb_N100_L14', 100, 14, 'mom_breadth'), ('nb_N100_L30', 100, 30, 'mom_breadth'), ('nb_N100_L60', 100, 60, 'mom_breadth'), ('dx_cap_breadth', 50, 30, 'cap_breadth'), ('dx_ew_breadth', 50, 30, 'ew_breadth'), ('dx_mom_full', 50, 30, 'mom_full'), ('dx_cap_full', 50, 30, 'cap_full'), ('dx_ew_full', 50, 30, 'ew_full')),
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
pr as (
  select variant, s, gross_risky + (1 - w_risky) * 0.000767 gross, w_risky from port
),
drift as (
  select w.variant, w.s + 7 s_next, w.coin_id, w.wt * (1 + w.rw) / (1 + pr.gross) wd
  from w join pr using (variant, s)
),
turn as (
  select coalesce(w.variant, d.variant) variant, coalesce(w.s, d.s_next) s,
         sum(abs(coalesce(w.wt, 0) - coalesce(d.wd, 0))) turnover
  from w full outer join drift d on d.variant = w.variant and d.s_next = w.s and d.coin_id = w.coin_id
  group by 1, 2
),
net as (
  select pr.variant, pr.s, pr.gross, pr.w_risky, coalesce(t.turnover, pr.w_risky) turnover
  from pr left join turn t using (variant, s)
),
seg as (
  select variant, s, w_risky, turnover, gross,
         case when s + 1 <= '2024-12-31' then 'S1' else 'S2' end sg
  from net
)
, rr as (
  select variant, sg, s, w_risky, bps, gross - turnover * bps / 1e4 r
  from seg cross join (values (10)) b(bps)
),
nav as (
  select *, exp(sum(ln(1 + r)) over (partition by variant, sg, bps order by s)) nv from rr
),
dd as (
  select *, nv / greatest(1, max(nv) over (partition by variant, sg, bps order by s rows between unbounded preceding and current row)) - 1 ddv from nav
)
select variant, sg, bps, count(*) wks, round((exp(sum(ln(1 + r))) - 1)::numeric, 4) total,
       round(min(ddv)::numeric, 4) maxdd, round((avg(r) / nullif(stddev_samp(r), 0) * sqrt(52))::numeric, 2) sharpe,
       round(avg(w_risky)::numeric, 3) avg_exp
from dd group by variant, sg, bps order by variant, sg, bps
