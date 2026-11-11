-- 11-12 投机仓(手动交易的 HL 子账户)记分账:每天一行,只读 HL 公开接口,地址不进表。src/data/accounting/spec_account.py
create table if not exists public.spec_account_daily (
  d            date primary key,
  equity_usd   double precision,
  cum_pnl_usd  double precision,
  ret          double precision,
  nav          double precision,
  n_reads      integer not null default 0,
  read_at      timestamptz,
  note         text,
  rule         text
);
alter table public.spec_account_daily enable row level security;
