-- 2026-11-02 · issuer_fundamentals_quarterly: rail-company quarterly fundamentals from SEC EDGAR XBRL (UPGRADE_PATHS A4).
-- revenue / net_income / buybacks / dividends / diluted_shares per calendar quarter (frame), with the filing date so
-- research can take values point-in-time. Q4 is derived (annual − Q1..Q3) when all three quarters are present.
create table if not exists public.issuer_fundamentals_quarterly (
  symbol         text not null,
  cik            bigint not null,
  period         text not null,
  period_end     date,
  filed          date,
  revenue        double precision,
  net_income     double precision,
  buybacks       double precision,
  dividends      double precision,
  diluted_shares double precision,
  source         text not null default 'sec_edgar',
  recorded_at    timestamptz not null default now(),
  primary key (symbol, period)
);
create index if not exists issuer_fundamentals_filed_idx on public.issuer_fundamentals_quarterly (filed);
alter table public.issuer_fundamentals_quarterly enable row level security;
grant select on public.issuer_fundamentals_quarterly to anon;
drop policy if exists lane_read on public.issuer_fundamentals_quarterly;
create policy lane_read on public.issuer_fundamentals_quarterly for select to anon using (true);
