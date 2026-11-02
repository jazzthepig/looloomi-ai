-- 2026-11-02 · feed_items: the Telegram news feed's ledger (Jazz 11-02 "make it a feed like All Things AI first").
-- One row per fetched RSS item (id = sha1 of the link). Items are scored against our universe; only those over
-- MIN_SCORE are posted, and posted_at records the post. dup_of marks the same story reported by a later outlet.
-- Dry mode (no TELEGRAM_FEED_CHAT_ID) still writes rows, so liveness never depends on the channel.
create table if not exists public.feed_items (
  id            text primary key,
  source        text not null,
  title         text not null,
  link          text not null,
  published_at  timestamptz,
  fetched_at    timestamptz not null default now(),
  summary_raw   text,
  hits          jsonb not null default '[]'::jsonb,
  score         integer not null default 0,
  post_text     text,
  posted_at     timestamptz,
  dup_of        text
);
create index if not exists feed_items_fetched_idx on public.feed_items (fetched_at desc);
create index if not exists feed_items_posted_idx on public.feed_items (posted_at desc) where posted_at is not null;
alter table public.feed_items enable row level security;
grant select on public.feed_items to anon;
drop policy if exists lane_read on public.feed_items;
create policy lane_read on public.feed_items for select to anon using (true);
