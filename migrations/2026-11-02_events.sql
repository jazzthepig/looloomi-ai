-- 2026-11-02 · events: one queryable table of "what happened" (UPGRADE_PATHS B2).
-- Writers: feed_items news (names hit), Binance CMS announcements (listing catalog 48 / delisting 161),
-- Hyperliquid spot new tokens. Upsert by id; nothing deletes. Lanes read it (the 开闸 backtest card).
create table if not exists public.events (
  id           text primary key,
  ts           timestamptz not null,
  kind         text not null,
  source       text not null,
  symbols      jsonb not null default '[]'::jsonb,
  title        text,
  url          text,
  payload      jsonb not null default '{}'::jsonb,
  recorded_at  timestamptz not null default now()
);
create index if not exists events_ts_idx on public.events (ts desc);
create index if not exists events_kind_ts_idx on public.events (kind, ts desc);
create index if not exists events_symbols_gin on public.events using gin (symbols);
alter table public.events enable row level security;
grant select on public.events to anon;
drop policy if exists lane_read on public.events;
create policy lane_read on public.events for select to anon using (true);
