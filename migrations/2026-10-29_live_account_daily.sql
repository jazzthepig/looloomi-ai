-- 2026-10-29 · 真钱账户每日快照(P1,src/data/accounting/live_account.py;Jazz 10-29「每日快照锚定」)。
-- 一个完成的 UTC 日一行,写一次不改;进 forward_anchor_daily。地址不进表。
-- 只给 service_role:行里有美元额(证据面只出收益)。
create table if not exists public.live_account_daily (
  d               date primary key,
  equity_usd      double precision not null,
  usdc            double precision not null,
  spot_usd        jsonb not null default '{}'::jsonb,     -- {symbol: usd}
  perp_upnl       double precision not null default 0,
  perp_positions  jsonb not null default '{}'::jsonb,     -- {coin: szi}
  account_mode    text,                                   -- HL userAbstraction(unifiedAccount / default / …)
  flows_usd       double precision,                       -- 外部净出入金(读不到 = null)
  nav             double precision,                       -- 开账日 = 1;链断 / 认不出出入金 = null
  ret             double precision,
  heartbeat_at    timestamptz,
  n_heartbeats    integer not null,
  note            text,
  rule            text not null,
  written_at      timestamptz not null default now()
);
alter table public.live_account_daily enable row level security;
revoke all on public.live_account_daily from anon, authenticated;
