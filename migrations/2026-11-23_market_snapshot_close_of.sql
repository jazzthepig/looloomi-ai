-- 2026-11-23 · market_snapshot.close_of(S-909 / T-432):哪一批是「某一天的收盘」。
-- 正式 CIS 只认收盘口径:UTC 00:00 之后第一轮取的那一批,标上前一天的日期。
-- 只在 00:00–00:30 窗内算数(过窗取到的不是收盘);一天、一个名字、一个来源只有一行收盘(唯一索引)。
alter table public.market_snapshot add column if not exists close_of date;
alter table public.market_snapshot drop constraint if exists market_snapshot_close_window;
alter table public.market_snapshot add constraint market_snapshot_close_window check (
  close_of is null
  or (close_of = ((ts at time zone 'utc')::date - 1) and (ts at time zone 'utc')::time < time '00:30')
);
create unique index if not exists market_snapshot_one_close
  on public.market_snapshot (source, symbol, close_of) where close_of is not null;
create index if not exists market_snapshot_close_of
  on public.market_snapshot (close_of, source) where close_of is not null;
