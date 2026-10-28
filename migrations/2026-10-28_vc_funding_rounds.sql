-- VC funding rounds as REPORTED in public news headlines (src/data/vc/rounds_store.py).
-- Why a table: the panel used to re-read the last ~20 RSS items per request and keep nothing, so a
-- 180-day window held one deal. Rows persist; the same round reported again within 21 days merges
-- into one row (earliest date wins, every outlet listed once).
-- Not a census: unreported / undisclosed rounds are missing; amounts are as printed, not verified.
create table if not exists public.vc_funding_rounds (
  id              text primary key,          -- '<project_norm>:<first announced date>'
  project         text not null,
  project_norm    text not null,
  amount_usd      double precision,          -- null = undisclosed, or reported in another currency
  amount_native   double precision,
  currency        text,
  amount_kind     text,                      -- 'round' | 'cumulative' ("… bringing total funding to $X")
  round           text,                      -- Seed / Series A / Strategic / Token sale / Fund close / Undisclosed stage
  announced_date  date not null,             -- earliest UTC date the round was reported
  category        text,                      -- RWA / Payments / AI / Trading / DeFi / Infrastructure / Bitcoin / Gaming / VC Fund / Other
  lead_investors  text[] not null default '{}',
  investors       text[] not null default '{}',
  valuation_usd   double precision,
  headline        text,
  source_name     text,
  source_url      text,
  sources         text[] not null default '{}',
  n_sources       integer not null default 1,
  crypto_basis    text,                      -- why it counts as crypto: 'keyword' | 'investor'
  first_seen_at   timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists vc_funding_rounds_date_idx on public.vc_funding_rounds (announced_date desc);
create index if not exists vc_funding_rounds_norm_idx on public.vc_funding_rounds (project_norm);
alter table public.vc_funding_rounds enable row level security;
grant select on public.vc_funding_rounds to anon;
drop policy if exists lane_read on public.vc_funding_rounds;
create policy lane_read on public.vc_funding_rounds for select to anon using (true);
