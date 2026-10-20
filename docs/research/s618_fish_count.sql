-- S-618「大鱼」的参照计数(台账 S-618 原文;2026-10-20 Seth 在当天的库上跑出 286 条,原记 287)。
-- 任何 lane 的鱼计数器先对上这一条再往下算(T-154)。
--   宇宙:binance_hist(去 USDC / BTCDOM / DEFI)、rn ≥ 220(该名的第几根日线,按 trade_date 排)、
--         30 日均成交额(close × volume,含当天)≥ 500 万美元、日期 2020-03-01 → 2026-06-20
--   命中:t 日之后 120 根(t+1 … t+120,按行不是按日历)里的最高收盘 ≥ 3 × t 日收盘
--   并鱼:同名的命中按 rn 排序,**与上一个命中**相隔 ≤ 30 根就并进同一条鱼(链式,不是相对鱼的起点)
--   起点 = 每条鱼的第一个命中日
with b as (
  select symbol, trade_date d, close c, close * volume dv,
         row_number() over (partition by symbol order by trade_date) rn
  from ohlcv_daily where source = 'binance_hist' and symbol not in ('USDC', 'BTCDOM', 'DEFI')
), f as (
  select *, avg(dv) over (partition by symbol order by rn rows between 29 preceding and current row) adv30,
         max(c) over (partition by symbol order by rn rows between 1 following and 120 following) fmax
  from b
), hits as (
  select symbol, rn, d from f
  where rn >= 220 and adv30 >= 5e6 and d between '2020-03-01' and '2026-06-20' and fmax >= 3 * c
), g as (
  select symbol, rn, d,
         case when rn - lag(rn) over (partition by symbol order by rn) <= 30 then 0 else 1 end newfish
  from hits
)
select count(*) filter (where newfish = 1) fish,          -- 2026-10-20:286
       count(*) hits,                                     -- 2026-10-20:13,396
       count(distinct symbol) symbols                     -- 2026-10-20:147
from g;
