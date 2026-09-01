#!/usr/bin/env bash
# CG Pro /rwas/markets 探针 —— 市场数据嵌在 tokenized_market_data 里,不在顶层
set -uo pipefail
: "${COINGECKO_API_KEY:?先 set -a; source .env; set +a}"
B=https://pro-api.coingecko.com/api/v3
H="x-cg-pro-api-key: $COINGECKO_API_KEY"

echo "── ① 面板规模 + 按资产类型拆(决定落库量级)──"
curl -s -H "$H" "$B/rwas/markets?per_page=250&page=1&order=market_cap_desc" \
| jq '{
    n: length,
    total_tokenized_mcap: ([.[].tokenized_market_data.market_cap // 0] | add),
    total_24h_volume:     ([.[].tokenized_market_data.total_volume // 0] | add),
    net_mcap_change_24h:  ([.[].tokenized_market_data.market_cap_change_24h // 0] | add),
    by_asset_type: (group_by(.asset_type) | map({
        type: .[0].asset_type, n: length,
        mcap: ([.[].tokenized_market_data.market_cap // 0] | add)})),
    top10: [.[:10][] | {
        name, type: .asset_type,
        mcap: .tokenized_market_data.market_cap,
        vol:  .tokenized_market_data.total_volume,
        chg24_pct: .tokenized_market_data.market_cap_change_percentage_24h,
        chg30d_pct: .tokenized_market_data.price_change_percentage_30d_in_currency}]}'

echo
echo "── ② 是否有第 2 页(250 是单页上限,不是总数)──"
curl -s -H "$H" "$B/rwas/markets?per_page=250&page=2" | jq 'length'

echo
echo "── ③ 发行方维度 =「在哪买」──"
curl -s -H "$H" "$B/rwas/issuers/list" | jq '{n: length, sample: .[:12]}'
