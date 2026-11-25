-- 2026-11-25 · 按时点龙头的第二道守卫(T-434 ⑤ / 台账 S-915 结果 1 的修正 ②)。
-- SEC frames 的 us-gaap:Assets(CY{Y}Q4I,各公司约 12 月底的总资产)。公众流通市值 > 总资产 60 倍 ⇒ 当 XBRL 录入错误(研究侧判)。
-- 起因:NPS Pharmaceuticals 2012–2014 连续三年把流通市值报成 $7,490 亿–3.5 万亿,同一 CIK 的中位数守卫拦不住。
-- 读写都只给服务端 key。
create table if not exists public.sec_assets (
  cik          bigint           not null,
  ccp          text             not null,
  period_end   date             not null,
  val          double precision not null,
  entity_name  text,
  accn         text,
  recorded_at  timestamptz      not null default now(),
  primary key (cik, ccp)
);
alter table public.sec_assets enable row level security;
revoke all on public.sec_assets from anon, authenticated;
