-- S-628 · 社交热度 K 臂(历史版)—— 规则全部来自台账 S-628 预注册(2026-10-20 11:45 UTC),此文件只是它的 SQL。
-- 输出:每个周一一行 —— 宇宙数、快鱼数、K 里的快鱼数(判据用),以及只报项。
-- 判据(K 快鱼率 > N,周内打乱 K / N 标签)只依赖每周的 (宇宙数, 快鱼数, K 数, K 快鱼数):
-- 周内打乱 ⇔ 每周 K 快鱼数服从超几何分布,在 Python 里按周独立抽 2,000 次即可(与逐行打乱等价)。

with mon as (
  select generate_series('2025-12-01'::date, '2026-08-17'::date, interval '7 day')::date t
), sd as (
  select symbol, d, value v from social_daily where source = 'santiment' and metric = 'social_volume_total'
), se as (
  select symbol, d, value v from social_daily where source = 'santiment' and metric = 'sentiment_weighted_total'
), b as (
  select symbol, trade_date d, close c, close * volume dv,
         row_number() over (partition by symbol order by trade_date) rn
  from ohlcv_daily where source = 'binance_hist' and symbol not in ('USDC','BTCDOM','DEFI')
), f as (
  select symbol, d, c, rn,
    avg(dv) over w30 adv30,
    max(c) over (partition by symbol order by d rows between 1 following and 60 following) fwdmax60,
    lead(c, 60) over (partition by symbol order by d) c60,
    min(c) over (partition by symbol order by d rows between 30 preceding and current row) min30
  from b
  window w30 as (partition by symbol order by d rows between 29 preceding and current row)
), soc as (
  select m.t, s.symbol,
    count(s.v) n_obs,
    sum(s.v) filter (where s.d between m.t - 6 and m.t) sv7,
    7 * percentile_cont(0.5) within group (order by s.v) filter (where s.d between m.t - 36 and m.t - 7) base7
  from mon m join sd s on s.d between m.t - 36 and m.t
  group by m.t, s.symbol
), sen as (
  select m.t, s.symbol, avg(s.v) sent7
  from mon m join se s on s.d between m.t - 6 and m.t
  group by m.t, s.symbol
), gate as (
  select d, lvl > avg(lvl) over (order by d rows between 199 preceding and current row) gate_open
  from (select d, exp(sum(ln(1 + ret)) over (order by d)) lvl
        from style_index_pit_daily where style = 'majors' and weighting = 'cap' and ret > -0.95) z
), u as (
  select m.t, f.symbol, f.c, f.c60, f.min30,
    (f.fwdmax60 >= 2 * f.c) fish,
    soc.sv7, soc.base7, soc.sv7 / greatest(coalesce(soc.base7, 0), 7) surge, sen.sent7
  from mon m
  join f on f.d = m.t
  join soc on soc.t = m.t and soc.symbol = f.symbol
  left join sen on sen.t = m.t and sen.symbol = f.symbol
  where f.rn >= 220 and f.adv30 >= 5e6 and f.symbol not in ('BTC','ETH') and soc.n_obs >= 30
), r as (
  select u.*,
    case when sv7 >= 20 then row_number() over (partition by t order by (sv7 >= 20) desc, surge desc, symbol) end rk_surge,
    row_number() over (partition by t order by sv7 desc nulls last, symbol) rk_level
  from u
), lab as (
  select r.*, (rk_surge is not null and rk_surge <= 10) k, (rk_level <= 10) k_level from r
)
select l.t, g.gate_open,
  count(*) n_univ, count(*) filter (where fish) n_fish,
  count(*) filter (where k) n_k, count(*) filter (where k and fish) k_fish,
  count(*) filter (where k_level) n_kl, count(*) filter (where k_level and fish) kl_fish,
  avg(ln(c60 / c)) filter (where k and c60 > 0) k_ret60, avg(ln(c60 / c)) filter (where not k and c60 > 0) n_ret60,
  avg(ln(c / nullif(min30, 0))) filter (where k and fish) k_runup_fish, avg(ln(c / nullif(min30, 0))) filter (where not k and fish) n_runup_fish,
  avg(sent7) filter (where k) k_sent7, avg(sent7) filter (where not k) n_sent7,
  string_agg(symbol || case when fish then '*' else '' end, ' ' order by rk_surge) filter (where k) k_names
from lab l left join gate g on g.d = l.t
group by l.t, g.gate_open
order by l.t;
