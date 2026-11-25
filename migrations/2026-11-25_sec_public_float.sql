-- 2026-11-25 · 按时点的龙头(美国部分)的原料(src/data/universe/world50_data.refresh_public_float,T-434 ⑤ / 台账 S-915)。
-- sec_public_float:SEC XBRL frames 的 dei:EntityPublicFloat —— 10-K 封面的「非关联方持有的普通股市值」(美元,截至该公司第二财季末)。
--   一年一页 = 当年所有 10-K 申报公司,含后来退市 / 被并购的(没有幸存者偏差)。原样存:XBRL 有量级录入错误(样本里有报成 71 万亿的),守卫在研究侧。
-- sec_company:各年流通市值前 400 的公司的 SEC submissions(名称、SIC、现用代码、交易所、注册地、曾用名)—— 行业对照与对代码用。
-- 读写都只给服务端 key(Jazz 11-13「数据访问不能匿名」)。
create table if not exists public.sec_public_float (
  cik          bigint           not null,
  ccp          text             not null,
  period_end   date             not null,
  val          double precision not null,
  entity_name  text,
  loc          text,
  accn         text,
  recorded_at  timestamptz      not null default now(),
  primary key (cik, ccp)
);
create index if not exists sec_public_float_ccp_val on public.sec_public_float (ccp, val desc);
create table if not exists public.sec_company (
  cik                    bigint      primary key,
  name                   text,
  sic                    text,
  sic_description        text,
  tickers                text,
  exchanges              text,
  state_of_incorporation text,
  fiscal_year_end        text,
  former_names           jsonb,
  recorded_at            timestamptz not null default now()
);
alter table public.sec_public_float enable row level security;
alter table public.sec_company enable row level security;
revoke all on public.sec_public_float from anon, authenticated;
revoke all on public.sec_company from anon, authenticated;
