-- World50 前向账本(Jazz 10-15:EW 与 EW×Mom 两条臂,2026-12-31 起前向记账;S-581 / S-583)。
-- 写入端 src/data/universe/world50_book.py 的 run_book;调度 = 周更循环 _world50_history_loop 的 book 段。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-15(migration world50_book)。
-- 判活:select arm, count(*), max(d) from world50_book_nav group by arm;(2027-01-02 之前为 0 行是对的 —— 循环 detail 里有预演)

create table if not exists public.world50_book_holdings (
  as_of       date not null,               -- 调仓日(日历季末;收盘后的目标权重)
  arm         text not null,               -- 'EW' | 'EWxMom'
  key         text not null,               -- world50.CANDIDATES 的 key
  weight      double precision not null,
  rank        integer,                     -- 当时市值排名
  mcap_usd    double precision,
  neutral     boolean not null default false,   -- 动量不可算、分数记 1
  rule        text not null,
  recorded_at timestamptz not null default now(),
  primary key (as_of, arm, key)
);

create table if not exists public.world50_book_nav (
  d           date not null,               -- 工作日;调仓日那一行 = 扣成本后的净值
  arm         text not null,
  nav         double precision not null,   -- 开账 = 1
  ret         double precision,            -- 对上一行的日收益;调仓日为空
  n_priced    integer,
  as_of       date not null,               -- 这一行用的是哪个调仓日的权重
  rule        text not null,
  recorded_at timestamptz not null default now(),
  primary key (d, arm)
);

alter table public.world50_book_holdings enable row level security;
alter table public.world50_book_nav enable row level security;
revoke all on public.world50_book_holdings from anon, authenticated;
revoke all on public.world50_book_nav from anon, authenticated;
grant select, insert, update, delete on public.world50_book_holdings to service_role;
grant select, insert, update, delete on public.world50_book_nav to service_role;
