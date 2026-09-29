-- T-039 风格表头:成员 / 市值历史 / 风格指数。RLS on、零策略、只给 service_role(S-167 姿态)。
create table if not exists public.style_membership (
  symbol      text not null,
  coin_id     text not null,
  categories  jsonb not null default '[]'::jsonb,
  base_style  text,
  fetched_d   date not null,
  recorded_at timestamptz not null default now(),
  primary key (symbol, fetched_d)
);
create table if not exists public.asset_mcap_daily (
  symbol      text not null,
  coin_id     text not null,
  d           date not null,           -- 覆盖的那一天(CG 00:00 UTC 点 − 1 天)
  price       double precision,
  mcap        double precision,
  source      text not null,
  recorded_at timestamptz not null default now(),
  primary key (symbol, d, source)
);
create index if not exists asset_mcap_daily_d_idx on public.asset_mcap_daily (source, d);
create table if not exists public.style_index_daily (
  d           date not null,
  style       text not null,
  weighting   text not null check (weighting in ('cap','equal')),
  ret         double precision not null,
  level       double precision not null,
  n_members   integer not null,
  top_member  text,
  top_weight  double precision,
  members     jsonb,
  basis       text not null,            -- current_constituents_backfilled = 幸存者偏差,如实标注
  code_ref    text,
  computed_at timestamptz not null default now(),
  primary key (d, style, weighting)
);
alter table public.style_membership  enable row level security;
alter table public.asset_mcap_daily  enable row level security;
alter table public.style_index_daily enable row level security;
revoke all on public.style_membership, public.asset_mcap_daily, public.style_index_daily from anon, authenticated;
grant select, insert, update, delete on public.style_membership, public.asset_mcap_daily, public.style_index_daily to service_role;
