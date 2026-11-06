-- 11-06:lane-b(T-267)/ lane-a(T-265)拿 publishable key 读 cg_coin_map 得 401 —— 代币 → CoinGecko id 的映射是研究的基础设施,
-- 没有任何敏感内容;style_universe_broad(币的分类 / 板块)同理。只开读。已通过 Supabase MCP 施加(lane_read_cg_coin_map_style_universe)。
grant select on public.cg_coin_map to anon;
drop policy if exists lane_read on public.cg_coin_map;
create policy lane_read on public.cg_coin_map for select to anon using (true);
grant select on public.style_universe_broad to anon;
drop policy if exists lane_read on public.style_universe_broad;
create policy lane_read on public.style_universe_broad for select to anon using (true);
