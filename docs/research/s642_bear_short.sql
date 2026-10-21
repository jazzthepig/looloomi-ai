-- S-642 (ledger, 2026-10-21 03:24 UTC, preregistered before any short ticket was scored): the bear-market short arm,
-- a line-for-line mirror of docs/research/r_v2_tickets.sql. Everything is the long version with the sign flipped:
--   gate      : closed, not open   (majors cap index <= its own 200-day mean, and >= 200 days of history)
--   trigger   : c < ll40 (40-day new low) instead of c > hh40; c < sma200 instead of c > sma200
--   -- the ONLY condition with no mirror: the long side's mindd120 <= 0.5 is dropped (written before the test)
--   stop      : entry + 2.5 x ATR14[t]  (intraday high touches -> out; gap -> out at the open)
--   exit      : close > SMA20 -> out at the NEXT day's open (the long side uses close < SMA20)
--   expiry    : 120 bars; one ticket per symbol at a time (same non-overlap chain as the long book)
--   window    : signal days 2020-03-01 -> 2026-06-20
-- R = (entry - exit) / (stop - entry) - 0.004 * entry / (stop - entry)   [+ funding R, added per ticket in python]
-- Funding is NOT in this jsonb and NOT in r_tickets_nav: t159_bear_short.py adds funding_rate summed over
-- [entry_d, exit_d) from funding_history (venue = binance_perp) scaled by entry / (stop - entry), separately, per S-642.
-- Usage:  select * from r_tickets_nav(<this query>, 0.005, 10);   -- silently drops every ticket (it keeps only
--         entry_px > stop_px), which is why the money curve is transliterated in python.  Read the jsonb for tickets.
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
   min(l) over (partition by symbol order by rn rows between 40 preceding and 1 preceding) ll40
  from b0
), gate as (
  select d, (n >= 200 and lvl <= sma) gate_closed from (
    select d, lvl, avg(lvl) over (order by d rows between 199 preceding and current row) sma,
           count(*) over (order by d rows between 199 preceding and current row) n
    from (select d, exp(sum(ln(1 + ret)) over (order by d)) lvl
          from style_index_pit_daily where style = 'majors' and weighting = 'cap' and ret > -0.95) z) g
), arr as (
  select symbol, array_agg(o order by rn) ao, array_agg(h order by rn) ah, array_agg(c order by rn) ac,
         array_agg(coalesce(sma20, c) order by rn) a20, array_agg(d order by rn) ad, count(*)::int n
  from f group by symbol
), ev as (
  select f.symbol, f.rn, f.d, f.atr14 from f left join gate g on g.d = f.d
  where rn >= 220 and adv30 >= 5e6 and f.d between '2020-03-01' and '2026-06-20'
    and (hh40-ll40)/hh40 <= 0.40 and c < ll40 and c < sma200 and dv >= 2*adv40p and atr14 > 0
    and coalesce(g.gate_closed, false)
), sim as (
  select e.symbol, e.rn, e.d, a.n, a.ao[e.rn+1] entry, a.ao[e.rn+1] + 2.5*e.atr14 stop, x.k
  from ev e join arr a using (symbol)
  left join lateral (select min(i) k from generate_series(e.rn+1, least(e.rn+120, a.n)) i
    where a.ah[i] >= a.ao[e.rn+1] + 2.5*e.atr14 or a.ac[i] > a.a20[i]) x on true
  where e.rn + 1 <= a.n
), tr as (
  select s.symbol, s.d, s.rn+1 ei, s.entry, s.stop,
    case when s.k is null then least(s.rn+120, s.n) when a.ah[s.k] >= s.stop then s.k when s.k+1 <= s.n then s.k+1 else s.k end xi,
    case when s.k is null then a.ac[least(s.rn+120, s.n)]
         when a.ah[s.k] >= s.stop then (case when s.k > s.rn+1 and a.ao[s.k] >= s.stop then a.ao[s.k] else s.stop end)
         when s.k+1 <= s.n then a.ao[s.k+1] else a.ac[s.k] end xp,
    (s.k is null and s.rn+120 > s.n) or (s.k is not null and s.k+1 > s.n and a.ah[s.k] < s.stop) still_open
  from sim s join arr a using (symbol) where s.entry < s.stop
), rec as (
  (select distinct on (symbol) * from tr order by symbol, ei)
  union all
  select n2.* from rec cross join lateral (select * from tr t where t.symbol = rec.symbol and t.ei > rec.xi order by t.ei limit 1) n2
)
select jsonb_agg(jsonb_build_object(
         'id', r.symbol || ':' || r.d || ':s', 'symbol', r.symbol, 'signal_d', r.d, 'entry_d', a.ad[r.ei],
         'exit_d', case when r.still_open then null else a.ad[r.xi] end,
         'entry_px', r.entry, 'stop_px', r.stop, 'exit_px', case when r.still_open then null else r.xp end,
         'r', (r.entry - r.xp)/(r.stop - r.entry) - 0.004*r.entry/(r.stop - r.entry)) order by r.d, r.symbol)
from rec r join arr a using (symbol)