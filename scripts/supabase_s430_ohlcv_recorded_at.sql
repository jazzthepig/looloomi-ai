-- S-430 (2026-09-26) — applied as migration `s430_ohlcv_recorded_at_on_value_change`.
-- Every ohlcv_daily writer upserts without recorded_at, so an update kept the FIRST insert time: a mid-day
-- partial bar later overwritten with the final close still looked partial, and "written after the close"
-- (S-413 readiness) could not tell partial from final. Bump only when a price value changes, so an
-- identical re-assert keeps its time and point-in-time replay (pit_replay.py) is preserved.
create or replace function public.ohlcv_daily_touch_recorded_at()
returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if (new.open, new.high, new.low, new.close, new.volume)
     is distinct from (old.open, old.high, old.low, old.close, old.volume) then
    new.recorded_at := now();
  else
    new.recorded_at := old.recorded_at;
  end if;
  return new;
end $$;
drop trigger if exists ohlcv_daily_touch_recorded_at on public.ohlcv_daily;
create trigger ohlcv_daily_touch_recorded_at before update on public.ohlcv_daily
  for each row execute function public.ohlcv_daily_touch_recorded_at();
revoke execute on function public.ohlcv_daily_touch_recorded_at() from anon, authenticated, public;
