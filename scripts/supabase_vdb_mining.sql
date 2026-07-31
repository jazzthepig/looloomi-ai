-- ============================================================================
-- VDB 挖掘架构 — 让策略成为可持续挖掘的对象(docs/VDB_MINING_SCHEMA.md)
-- Seth, 2026-07-27。⚠️ Supabase 持续超时未能 apply,请 Mac 端执行。
--
-- 核心转变:向量编码「环境」,查询「相似环境里谁活过」= 导航,不是后视镜。
-- Jazz:"价格是高维信号的映射…现在都是后视镜开 120 然后撞车"
-- ============================================================================
create extension if not exists vector;

-- ① 环境向量:每日市场状态,不含任何策略信息。价格只占 5/24 维,且仅用于二阶矩与相位。
create table if not exists market_state_vectors (
  d                   date primary key,
  vec                 vector(24),
  vec_full            jsonb,        -- 含 null(未测量)的完整版,I1
  regime_label        text,         -- 人读标注,不参与检索
  source_completeness real,         -- 真实测量维度占比 = 可信度
  computed_at         timestamptz default now()
);
create index if not exists msv_hnsw on market_state_vectors using hnsw (vec vector_cosine_ops);

-- ② 策略响应面:策略 × 环境簇 → 收益分布(不是单一 Sharpe)
create table if not exists strategy_response (
  strategy_id   text not null,
  state_cluster int  not null,
  n_days        int,
  ret_mean      real,
  ret_vol       real,
  ret_p10       real,      -- 左尾(I5:分布不是点估计)
  hit_rate      real,
  max_dd        real,
  sample_grade  text,      -- sufficient | sparse | none  ← none 是一等公民
  updated_at    timestamptz default now(),
  primary key (strategy_id, state_cluster)
);
create index if not exists sr_cluster_idx on strategy_response (state_cluster);

-- ③ 查询范式:今天的环境,历史上最像哪些天?
create or replace function similar_market_states(target_d date, k int default 20)
returns table(d date, similarity double precision, regime_label text)
language sql stable as $$
  with t as (select vec from market_state_vectors where d = target_d)
  select m.d, (1 - (m.vec <=> t.vec))::double precision, m.regime_label
  from market_state_vectors m, t
  where m.d < target_d and m.vec is not null
  order by m.vec <=> t.vec
  limit k;
$$;

comment on table market_state_vectors is
  'VDB ① 环境向量。每日市场状态高维刻画,不含策略信息。价格仅 5/24 维且只用于二阶矩与趋势相位 —— '
  '重建高维,不消费投影。';
comment on table strategy_response is
  'VDB ② 响应面。策略不再有"一个 Sharpe",而有"每类环境下的收益分布"。'
  'sample_grade=none 表示该策略从未在此环境活过 —— 这正是最该知道的事。';
