-- 2026-11-08 · S-770 ✅(lane-c T-291)⇒ Upbit KRW 首次上币进同一张前向记录表(src/data/signals/event_watch.py,kind = upbit_krw_listing)。
alter table public.binance_event_watch drop constraint if exists binance_event_watch_kind_check;
alter table public.binance_event_watch add constraint binance_event_watch_kind_check
  check (kind in ('listing', 'perp_listing', 'upbit_krw_listing'));
