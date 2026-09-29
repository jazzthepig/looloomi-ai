-- S-436 — coingecko_pro_ohlc rows are labelled one day late.
-- CoinGecko /ohlc/range stamps each daily candle with its CLOSE time (D+1 00:00 UTC);
-- data_layer.get_cg_ohlc_range read that stamp as D. Measured: CG(D) = Binance(D-1) to 0.02%, 18/18 days.
-- Apply AFTER the code fix is deployed (otherwise the 6-hourly loop re-writes the old labels for 60 days).
-- Two passes into a disjoint range so the (symbol, trade_date, source) unique key never collides.
-- recorded_at is untouched: the S-430 trigger only refreshes it when a price value changes.
begin;
update ohlcv_daily set trade_date = trade_date - 100000 where source = 'coingecko_pro_ohlc';
update ohlcv_daily set trade_date = trade_date + 99999  where source = 'coingecko_pro_ohlc';
commit;
-- Storage: two passes rewrite ~33k rows twice ⇒ ~66k dead tuples (a few MB of bloat on ohlcv_daily).
-- Run outside the transaction right after:
vacuum (analyze) ohlcv_daily;
-- check: CG close(D) should now match Binance close(D) to ~0.03%
-- select c.trade_date, c.close, b.close from ohlcv_daily c join ohlcv_daily b
--   on b.symbol=c.symbol and b.trade_date=c.trade_date and b.source='binance_hist'
--  where c.source='coingecko_pro_ohlc' and c.symbol='BTC' order by 1 desc limit 10;
