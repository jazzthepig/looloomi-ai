-- S-468 — binance_hist held 41,804 forward-filled rows (125 delisted symbols, none in the core panel).
-- The one-time 2026-08-08 deep import filled every delisted pair from its last trade to the import date
-- with volume=0, O=H=L=C rows: "no data" stored as a price (same class as S-459).
-- AS APPLIED 2026-10-03 (migration s468_binance_hist_ffill_relabel). UPDATE only, reversible:
--   update ohlcv_daily set source='binance_hist' where source='binance_hist_ffill';
-- Storage: the UPDATE rewrote ~42k rows (~42k dead tuples, ~10 MB at ~229 B/row); vacuum (analyze) was run right
-- after (2026-10-03 05:51 UTC): n_dead_tup 0, table 182 MB total.
update ohlcv_daily set source = 'binance_hist_ffill'
 where source = 'binance_hist' and volume = 0 and open = high and high = low and low = close
   and recorded_at >= '2026-08-08 00:00+00' and recorded_at < '2026-08-09 00:00+00';
vacuum (analyze) ohlcv_daily;
-- cg_coin_map, same day: ONE cross-2 -> harmony, AI artificial-inu-3 -> sleepless-ai (both in the stored candidate list;
-- mcap_tiebreak had picked the largest-cap candidate, not the Binance-listed one).
update cg_coin_map set coin_id = v.cid, resolved_from = 'manual_verified', resolved_at = now()
  from (values ('ONE','harmony'), ('AI','sleepless-ai')) as v(sym, cid)
 where cg_coin_map.symbol = v.sym and v.cid = any(cg_coin_map.candidates);
