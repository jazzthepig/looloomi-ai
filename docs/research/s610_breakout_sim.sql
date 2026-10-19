-- S-610 R 臂(深跌后转向、再跟趋势,G0 不设闸)的交易模拟 —— 在 Supabase 里原样跑过,结果:
--   n = 1,013(同名持仓期间不重复进场之后)· 均值 R +0.350 · 中位 −1.06 · 胜率 16.1% · 平均赢 +7.66R / 平均亏 −1.05R
--   三段:2020-03…2022 +0.887(125)· 2023–24 +0.149(725)· 2025–26 +0.829(163)
-- 口径(写死,见台账 S-610 预注册):
--   * 数据 ohlcv_daily source = binance_hist(Binance U 本位永续日线),剔除 USDC / BTCDOM / DEFI;成交额 = close × volume。
--   * rn = 该名的第几根日线(1 起);所有窗口按 rn,不按日历日。
--   * 宇宙:rn >= 220、前 30 日(含当天)平均成交额 >= 500 万美元、信号日 2020-03-01 … 2026-10-17。
--   * 信号(t 日收盘):t-120…t 内 close / 前 365 根最高收盘 的最小值 <= 0.5;t-40…t-1 振幅 (maxH - minL)/maxH <= 0.40;
--     close > t-40…t-1 的最高价;close > SMA200;当日成交额 >= 2 × t-40…t-1 的平均成交额。
--   * 进场 = t+1 开盘;止损 = max(t 日低点, 进场 - ATR14[t])(ATR14 = t-13…t 的真实波幅均值);进场开盘 <= 止损 ⇒ 不进。
--   * 出场:从进场日起每天先看止损(低点 <= 止损:进场日之后若开盘已 <= 止损按开盘价,否则按止损价),
--     再看收盘 < SMA20 ⇒ 次日开盘出;120 根内都没触发 ⇒ 第 120 根(或最后一根)收盘出。
--   * R = (出场 - 进场) / (进场 - 止损) - 0.004 × 进场 / (进场 - 止损);同名上一笔的出场根之后才能再进(递归)。
-- Python 复现(T-131)必须先对上上面的 n 与均值,再改管理规则。
with recursive b0 as (
  select symbol, trade_date d, open o, high h, low l, close c, close*volume dv,
         row_number() over w rn, lag(close) over w pc
  from ohlcv_daily where source='binance_hist' and symbol not in ('USDC','BTCDOM','DEFI')
  window w as (partition by symbol order by trade_date)
), f as (
  select *,
   avg(c) over (partition by symbol order by rn rows between 19 preceding and current row) sma20,
   avg(c) over (partition by symbol order by rn rows between 199 preceding and current row) sma200,
   avg(greatest(h-l, abs(h-coalesce(pc,c)), abs(l-coalesce(pc,c)))) over (partition by symbol order by rn rows between 13 preceding and current row) atr14,
   avg(dv) over (partition by symbol order by rn rows between 29 preceding and current row) adv30,
   avg(dv) over (partition by symbol order by rn rows between 40 preceding and 1 preceding) adv40p,
   max(h) over (partition by symbol order by rn rows between 40 preceding and 1 preceding) hh40,
   min(l) over (partition by symbol order by rn rows between 40 preceding and 1 preceding) ll40,
   c / max(c) over (partition by symbol order by rn rows between 365 preceding and current row) dd
  from b0
), f2 as (
  select f.*, min(dd) over (partition by symbol order by rn rows between 120 preceding and current row) mindd120 from f
), arr as (
  select symbol, array_agg(o order by rn) ao, array_agg(l order by rn) al, array_agg(c order by rn) ac,
         array_agg(coalesce(sma20, c) order by rn) a20, count(*)::int n
  from f group by symbol
), ev as (
  select symbol, rn, d, l, atr14 from f2
  where rn >= 220 and adv30 >= 5e6 and d between '2020-03-01' and '2026-10-17'
    and mindd120 <= 0.5 and (hh40-ll40)/hh40 <= 0.40 and c > hh40 and c > sma200 and dv >= 2*adv40p
), sim as (
  select e.symbol, e.rn, e.d, a.n, a.ao[e.rn+1] entry, greatest(e.l, a.ao[e.rn+1] - e.atr14) stop, x.k
  from ev e join arr a using (symbol)
  left join lateral (select min(i) k from generate_series(e.rn+1, least(e.rn+120, a.n)) i
    where a.al[i] <= greatest(e.l, a.ao[e.rn+1] - e.atr14) or a.ac[i] < a.a20[i]) x on true
  where e.rn + 1 <= a.n
), tr as (
  select s.symbol, s.d, s.rn+1 ei, s.entry, s.stop,
    case when s.k is null then least(s.rn+120, s.n) when a.al[s.k] <= s.stop then s.k when s.k+1 <= s.n then s.k+1 else s.k end xi,
    case when s.k is null then a.ac[least(s.rn+120, s.n)]
         when a.al[s.k] <= s.stop then (case when s.k > s.rn+1 and a.ao[s.k] <= s.stop then a.ao[s.k] else s.stop end)
         when s.k+1 <= s.n then a.ao[s.k+1] else a.ac[s.k] end xp
  from sim s join arr a using (symbol) where s.entry > s.stop
), rec as (
  (select distinct on (symbol) * from tr order by symbol, ei)
  union all
  select n2.* from rec cross join lateral (select * from tr t where t.symbol = rec.symbol and t.ei > rec.xi order by t.ei limit 1) n2
)
select count(*) n,
       avg((xp - entry)/(entry - stop) - 0.004*entry/(entry - stop)) mean_r
from rec;
