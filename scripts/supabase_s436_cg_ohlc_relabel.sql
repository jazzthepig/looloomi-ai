-- S-436 — coingecko_pro_ohlc rows are labelled one day late.
-- CoinGecko /ohlc/range stamps each daily candle with its CLOSE time (D+1 00:00 UTC);
-- data_layer.get_cg_ohlc_range read that stamp as D. Measured: CG(D) = Binance(D-1) to 0.02%, 18/18 days.
--
-- AS APPLIED 2026-09-29 ~07:50 UTC (migrations s436_cg_ohlc_relabel + s436b_...), after the fix deployed at ~05:30 UTC.
-- By then the fixed loop had already rewritten part of the table, so the relabel is per row, not a blanket shift:
--   old row  = recorded_at < 05:30 UTC on 09-29 (the S-430 trigger bumps recorded_at whenever a price changes,
--              so every row the fixed code rewrote carries a later recorded_at)
--   1) an old row whose day-earlier slot already holds a rewritten row is a duplicate -> delete (81 rows)
--   2) every other old row moves back one day, via a parking range so the unique key never collides
-- Known residue: for symbols the fixed loop had rewritten, the day just before its 60-day window has no row (1 day each).
-- ~5 symbols/day (incl. ONDO, SUI) still sit one day off Binance after the relabel — open under T-031.
-- Storage: two passes rewrote ~28k rows ⇒ ~56k dead tuples on ohlcv_daily; vacuum (analyze) was run right after.
-- NOTE: 100000 days is ~274 years; the first run's second pass used '< 1000-01-01' and matched nothing,
-- which is why a separate s436b pass exists. The filter below is the corrected one.

delete from ohlcv_daily o using ohlcv_daily n
 where o.source='coingecko_pro_ohlc' and n.source='coingecko_pro_ohlc'
   and o.recorded_at < '2026-09-29 05:30+00' and n.recorded_at >= '2026-09-29 05:30+00'
   and n.symbol=o.symbol and n.trade_date=o.trade_date-1;
update ohlcv_daily set trade_date = trade_date - 100000
 where source='coingecko_pro_ohlc' and recorded_at < '2026-09-29 05:30+00';
update ohlcv_daily set trade_date = trade_date + 99999
 where source='coingecko_pro_ohlc' and trade_date < date '1900-01-01';
vacuum (analyze) ohlcv_daily;

-- check: share of rows closer to Binance's same-day close than to the previous day's (was ~0%, after ~95%)
-- select count(*) filter (where abs(c.close/b0.close-1) < abs(c.close/b1.close-1))::float / count(*)
--   from ohlcv_daily c
--   join ohlcv_daily b0 on b0.symbol=c.symbol and b0.source='binance_hist' and b0.trade_date=c.trade_date
--   join ohlcv_daily b1 on b1.symbol=c.symbol and b1.source='binance_hist' and b1.trade_date=c.trade_date-1
--  where c.source='coingecko_pro_ohlc' and c.trade_date >= '2026-08-01' and b0.close<>b1.close;
