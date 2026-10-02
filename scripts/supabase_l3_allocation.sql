-- v0.2 L3 配置层(纸面)。S-167 姿态:RLS 开、零 policy、只授 service_role。
create table if not exists allocation_override (
  id          bigserial primary key,
  created_at  timestamptz not null default now(),
  start_d     date not null,
  delta       double precision not null check (delta between -1.3 and 1.3),
  horizon     text not null check (horizon in ('7d','14d','1m','delegate')),
  expires_d   date,
  reason      text not null check (length(reason) > 0),
  by_whom     text not null default 'jazz'
);
create table if not exists allocation_daily (
  d          date not null,
  book       text not null,
  weight     double precision not null,
  exposure   double precision not null,
  evidence   jsonb,
  why        jsonb,
  code_ref   text not null,
  updated_at timestamptz not null default now(),
  primary key (d, book)
);
create table if not exists allocation_nav_daily (
  d               date primary key,
  nav             double precision not null,
  ret             double precision not null,
  exposure        double precision not null,
  core_weight     double precision not null,
  n_books         int not null,
  missing_returns jsonb,
  code_ref        text not null,
  updated_at      timestamptz not null default now()
);
alter table allocation_override  enable row level security;
alter table allocation_daily     enable row level security;
alter table allocation_nav_daily enable row level security;
revoke all on allocation_override, allocation_daily, allocation_nav_daily from anon, authenticated;
grant all on allocation_override, allocation_daily, allocation_nav_daily to service_role;
grant usage, select on sequence allocation_override_id_seq to service_role;
