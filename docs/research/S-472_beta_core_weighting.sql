-- S-472 — ① 的加权方式是一个连续参数:w ∝ mcap(d-1)^α,单币上限 40%(Jazz 09-29 的单一标的上限),每日再平衡。
-- α = 0 等权(现行 beta_core 的口径,未含波动率目标),α = 1 市值加权。2023-01-01 起,同一 24 名面板(causal_positioning.DEFAULT_UNIVERSE)。
-- 价格与市值:asset_mcap_daily(CoinGecko market_chart,S-436 语义:d = 覆盖日)。只读;在 Supabase SQL 编辑器可直接重跑。
-- 已知偏差:成员是今天的 24 名往回取(幸存者)——偏向等权(幸存的小币被等权放大),所以「市值更好」的结论是保守的;不计成本(等权换手更高,也偏向等权)。
with p as (
  select symbol, d, price, mcap, lag(price) over w pp, lag(mcap) over w pm, lag(d) over w pd
  from asset_mcap_daily
  where symbol in ('BTC','ETH','SOL','BNB','XRP','DOGE','ADA','AVAX','LINK','DOT','LTC','TRX','ATOM','NEAR','APT','ARB','OP','SUI','UNI','AAVE','INJ','FIL','ETC','BCH')
    and d >= '2022-12-25'
  window w as (partition by symbol order by d)),
r as (select symbol, d, price/pp - 1 as ret, pm from p
      where pd = d - 1 and pp > 0 and pm > 0 and price/pp - 1 between -0.9 and 5 and d >= '2023-01-01'),
a as (select unnest(array[0, 0.25, 0.5, 0.75, 1.0]) alpha),
cw as (select a.alpha, r.*, power(pm, a.alpha) / sum(power(pm, a.alpha)) over (partition by a.alpha, r.d) w0
       from r cross join a),
ex as (select alpha, d, sum(greatest(w0 - 0.4, 0)) excess, sum(case when w0 < 0.4 then w0 else 0 end) rest
       from cw group by 1,2),
cw2 as (select cw.alpha, cw.d, cw.symbol, cw.ret,
               case when w0 >= 0.4 then 0.4 else w0 * (1 + ex.excess / nullif(ex.rest,0)) end w1
        from cw join ex using (alpha, d)),
daily as (select alpha, d, sum(w1*ret) ret, max(case when symbol='BTC' then w1 end) wbtc from cw2 group by 1,2),
nav as (select alpha, d, ret, wbtc, exp(sum(ln(1+ret)) over (partition by alpha order by d)) nav from daily),
dd as (select *, nav / max(nav) over (partition by alpha order by d) - 1 dd from nav)
select alpha,
  round((exp(sum(ln(1+ret)))-1)::numeric,2) total_2023_now,
  round((exp(sum(ln(1+ret)) filter (where d >= '2025-01-01'))-1)::numeric,2) since_2025,
  round((exp(sum(ln(1+ret)) filter (where d >= '2026-07-15'))-1)::numeric,2) since_jul15,
  round((stddev(ret)*sqrt(365))::numeric,2) vol, round(min(dd)::numeric,2) mdd,
  round((avg(ret)*365/(stddev(ret)*sqrt(365)))::numeric,2) sharpe0, round(avg(wbtc)::numeric,2) avg_w_btc
from dd group by alpha order by alpha;
