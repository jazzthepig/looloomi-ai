-- S-484 (2026-10-05, migration s484_price_source_agreement_daily): T-044b standing guard — one row per day per source.
create table if not exists price_source_agreement_daily (
  d          date not null,
  source     text not null,
  n_symbols  integer not null,
  n_findings integer not null,
  n_error    integer not null,
  by_kind    jsonb,
  worst      jsonb,
  code_ref   text,
  updated_at timestamptz not null default now(),
  primary key (d, source)
);
alter table price_source_agreement_daily enable row level security;
revoke all on price_source_agreement_daily from anon, authenticated;
grant all on price_source_agreement_daily to service_role;
