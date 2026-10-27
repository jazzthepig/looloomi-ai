-- 2026-10-27 · S-690 ✅ 的前向记录:每张 R-v2 纸面票在信号日的规模中性 OI/市值分位(「去掉高杠杆三分之一」纸面臂)。
-- 写入 ← src/data/signals/oi_leverage.py(_r_tickets_paper_loop 里 ticket_tags 之后的一步)。只读本库,不打交易所。
create table if not exists public.r_ticket_oi_tags (
  ticket_id    text primary key,
  symbol       text not null,
  signal_d     date not null,
  p            double precision,      -- 规模中性分位 0..1(rank(OI/市值) 对 rank(ln 市值) 的残差的 percent_rank)
  n_cs         integer,               -- 当天截面名字数
  high         boolean,               -- p ≥ 2/3
  why_missing  text,
  rule         text not null default 'S-690',
  tagged_at    timestamptz not null default now()
);
alter table public.r_ticket_oi_tags enable row level security;
grant select on public.r_ticket_oi_tags to anon;
drop policy if exists lane_read on public.r_ticket_oi_tags;
create policy lane_read on public.r_ticket_oi_tags for select to anon using (true);
