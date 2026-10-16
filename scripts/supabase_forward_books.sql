-- 山寨龙头腿(S-589)与灵活配置组合的前向账本(2026-12-31 起)。写入端 src/data/universe/forward_books.py 的 run_forward_books;
-- 调度 = 周更循环 _world50_history_loop 的 fwd_books 段。S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-16(migration forward_books)。
-- 判活(2027-01-02 之后):select book, arm, max(d) from forward_book_nav group by 1, 2;此前看 loop_attempt detail->'fwd_books'->'preview'。
create table if not exists public.forward_book_holdings (
  book text not null, arm text not null, as_of date not null, key text not null, weight double precision not null,
  note text, rule text not null, recorded_at timestamptz not null default now(), primary key (book, arm, as_of, key));
create table if not exists public.forward_book_nav (
  book text not null, arm text not null, d date not null, nav double precision not null, ret double precision,
  as_of date not null, rule text not null, recorded_at timestamptz not null default now(), primary key (book, arm, d));
alter table public.forward_book_holdings enable row level security;
alter table public.forward_book_nav enable row level security;
revoke all on public.forward_book_holdings from anon, authenticated;
revoke all on public.forward_book_nav from anon, authenticated;
grant select, insert, update, delete on public.forward_book_holdings to service_role;
grant select, insert, update, delete on public.forward_book_nav to service_role;
