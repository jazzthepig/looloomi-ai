-- 11-13 已通过 Supabase MCP 施加(migration name: asset_mcap_daily_source_coin_d_idx)。
-- 为什么:pg_stat_statements 里「source = $1 AND coin_id = ANY($2) AND d >= $3 ORDER BY coin_id, d」43,189 次、均 324 ms(合计 3.9 小时),
-- 表上没有 coin_id 开头的索引 ⇒ 每次顺序扫 76 万行(pg_stat_user_tables:seq_scan 114,105 次 × 每次 36.7 万行)。
-- 建完之后同形状的查询走 Index Only Scan。
create index if not exists asset_mcap_daily_source_coin_d_idx on public.asset_mcap_daily using btree (source, coin_id, d) include (price, mcap, volume);
analyze public.asset_mcap_daily;
