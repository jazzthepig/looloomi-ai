-- 2026-11-25 · SEC 原始财报事实(src/data/universe/world50_data.refresh_facts,T-434 ④ / 台账 S-913)。
-- 起因:权益类我们几乎只有收盘价;EODHD 基本面套餐 403(equity_fundamentals_q 0 行)。在 SEC 申报的公司用 SEC 的免费结构化接口
-- (companyconcept,与股本 / 营收两段同一个取数入口),存原始事实,不在写入端做任何派生 —— 季度值、自由现金流、派息率都在研究侧按时点现算。
-- 一行 = 一家公司 × 一个标签 × 一个单位 × 一个期间;同一期间多次报送只留最早的那次(当时的原始报告,filed = 已知日)。
-- 时点值(权益、封面股数):period_start = period_end。期间值:一季 / 半年 / 九个月 / 一年(10-Q 的现金流量表是年初至今)。
create table if not exists public.sec_facts (
  key          text             not null,
  tag          text             not null,
  unit         text             not null,
  period_start date             not null,
  period_end   date             not null,
  filed        date             not null,
  val          double precision not null,
  accn         text,
  form         text,
  recorded_at  timestamptz      not null default now(),
  primary key (key, tag, unit, period_start, period_end)
);
create index if not exists sec_facts_tag_key on public.sec_facts (tag, key, period_end);

-- 读写都只给服务端 key:Jazz 11-13「数据访问不能匿名」—— 不开 anon 读;哪条 lane 要读,按人登记后另开。
alter table public.sec_facts enable row level security;
revoke all on public.sec_facts from anon, authenticated;
