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

-- S-469 (2026-10-03, migration s469_cg_coin_map_manual_sticky): the ONE/AI fix above was overwritten 4 minutes later.
-- _cg_panel_loop reads cg_coin_map through the slow cg_known_coin_map RPC; on timeout it got [] and treated every
-- panel symbol as unresolved, re-guessing by market cap and upserting over the manual rows. Code now refuses the round
-- when the map is unreadable; this trigger makes manual_verified rows immune to any non-manual update.
create or replace function cg_coin_map_keep_manual() returns trigger
language plpgsql set search_path = public, pg_temp as $$
begin
  if old.resolved_from = 'manual_verified' and coalesce(new.resolved_from, '') <> 'manual_verified' then
    return old;
  end if;
  return new;
end $$;
revoke all on function cg_coin_map_keep_manual() from public, anon, authenticated;
drop trigger if exists cg_coin_map_keep_manual on cg_coin_map;
create trigger cg_coin_map_keep_manual before update on cg_coin_map
  for each row execute function cg_coin_map_keep_manual();
-- then the ONE/AI update above was re-applied.
