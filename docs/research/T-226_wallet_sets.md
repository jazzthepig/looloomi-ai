# T-226 自建团队 / 基金会 / 投资方钱包集合 —— 地址来源表 + 数据源实测(部分交付)

**状态:部分交付。** 本轮完成「地址来源表(每条带出处 URL)」+「公共数据源实测矩阵」+「事件定义与预注册草稿」;
**日频余额/净流出 CSV 与事件计数未完成** —— 执行抓取脚本时上下文钩子中断(121k token),脚本已就位,续跑起点见 §7。
全程只读(公开 GET / 公共 RPC),未注册账号、未付费、未入库。

## 1. 覆盖率表

| 名字 | 归属/锁仓合约 | 基金会/团队多签 | 投资方地址 | 有出处地址数 | 数据起点 | 事件数 |
|---|---|---|---|---|---|---|
| ARB | 3(Token Distributor / Vesting Budget Wallet / L2 Treasury Timelock) | 1(DAO Treasury) | 0 | 4 | 2024-01-01 | 未跑 |
| OP | 0 | 5(OP Foundation Safe + 官方 dashboard 4 个) | 0 | 5 | 2024-01-01 | 未跑 |
| ONDO | 0 | 1(Ondo Finance: Multisig 2) | 0 | 1 | 2024-01-01 | 未跑 |
| STRK | 1(LockedTokenGrant 归属锁仓) | 0 | 0 | 1 | 2024-01-01 | 未跑 |
| AVAX | 0 | 0 | 0 | **0** | — | — |
| SOL | 0 | 0 | 0 | **0** | 非 EVM | 读不到 |
| APT | 0 | 0 | 0 | **0** | 非 EVM | 读不到 |
| SUI | 0 | 0 | 0 | **0** | 非 EVM | 读不到 |
| TIA | 0 | 0 | 0 | **0** | 非 EVM | 读不到 |
| DOT | 0 | 0 | 0 | **0** | 非 EVM(Substrate) | 读不到 |

T-220 已确认这 10 个名字确有实际解锁日程(APT/ARB/AVAX/DOT/ONDO/OP/SOL/STRK/SUI/TIA),DefiLlama 网页版
`unlockEvents` 全为 null ⇒ 只有未来日程、无历史,所以归属地址必须自建 —— 本卡正是补这一段。

## 2. 地址来源表(每条带出处 URL)

出处类型:A=项目官方文档/官方 GitHub;B=公开浏览器标签(Blockscout/Etherscan);C=链上验证(RPC)。

### ARB(Arbitrum One,代币 0x912CE591…6548)
| 地址 | 角色 | 出处 | 类型 |
|---|---|---|---|
| 0xF3FC178157fb3c87548bAA86F9d24BA38E649B58 | DAO Treasury | https://docs.arbitrum.foundation/deployment-addresses | A+C |
| 0x15533b77981cDa0F85c4F9a485237DF4285D6844 | Foundation Vesting Budget Wallet | 同上 | A+C |
| 0x67a24CE4321aB3aF51c2d0a4801c3E111D88C9d9 | Token Distributor | 同上 | A+C |
| 0xbFc1FECa8B09A5c5D3EFfE7429eBE24b9c09EF58 | L2 Treasury Timelock (ETH treasury) | 同上 | A+C |

出处佐证:官方页「DAO contract addresses」共含 43 个 0x 地址;另 https://docs.arbitrum.foundation/token-supply
正文直接以 `arbiscan.io/token/0x912ce591…?a=0xF3FC1781…` 引用 DAO Treasury。

### OP(Optimism,代币 0x42…0042)
| 地址 | 角色 | 出处 | 类型 |
|---|---|---|---|
| 0x2501c477D0A35545a387Aa4A3EEe4292A9a8B3F0 | Optimism: Foundation(Safe) | https://github.com/ethereum-optimism/community-hub/blob/main/pages/welcome/faq/dashboard-trackers.mdx | A+B+C |
| 0x2A82Ae142b2e62Cb7D10b55E323ACB1Cab663a26 | Safe(官方 dashboard 收录) | 同上 | A+C |
| 0x19793c7824Be70ec58BB673CA42D2779d12581BE | 官方 dashboard #3 | 同上 | A |
| 0xE4553b743E74dA3424Ac51f8C1E586fd43aE226F | 官方 dashboard #4 | 同上 | A |
| 0x09C7bAD99688a55a2e83644BFAed09e62bDcCcBA | superchain-revenue-explainer 载明地址 | https://github.com/ethereum-optimism/community-hub/blob/main/pages/op-token/superchain-revenue-explainer.mdx | A |

### ONDO(Ethereum,代币 0xfAbA6f8e4a5e8ab82f62fe7c39859fa577269be3)
| 地址 | 角色 | 出处 | 类型 |
|---|---|---|---|
| 0x677FD4Ed8aE623f2f625DEB2D64F2070E46cA1A1 | Ondo Finance: Multisig 2 | https://eth.blockscout.com/api/v2/tokens/0xfaba6f8e4a5e8ab82f62fe7c39859fa577269be3/holders | B+C |

### STRK(Ethereum,代币 0xca14007eff0db1f8135f4c25b34de49ab0d42766)
| 地址 | 角色 | 出处 | 类型 |
|---|---|---|---|
| 0x798425cB26cB41016D2db92289234ba81dC2DAB0 | LockedTokenGrant(归属锁仓合约) | https://eth.blockscout.com/api/v2/tokens/0xca14007eff0db1f8135f4c25b34de49ab0d42766/holders | B+C |

### AVAX / SOL / APT / SUI / TIA / DOT:地址读不到(有出处的地址为 0)
按卡上纪律「没有出处的不进集合」,这 6 个名字本轮为空集。
- **AVAX**:Avalanche 官方 `build.avax.network/docs/avalanche-foundation*` 全 404(6 个候选路径);ICF medium 文章 403;
  Snowtrace 页面 202(JS 渲染,抓不到);ICF 论坛帖(https://forum.cosmos.network/t/interchain-foundation-wallet-addresses/10426)
  只给 cosmos 地址,无 C-chain 0x ⇒ **C-chain 归属地址读不到**。
- **SOL / APT / SUI / TIA**:非 EVM,公开可用的地址标签源同样读不到(见 §4 实测)。
- **DOT**:Substrate 库账户(非 0x),链上 treasury 账户需 polkadot.js / chain spec,不在本次公开 API 覆盖内。

## 3. 数据源实测矩阵(本轮真实跑过)

| 端点 | 用途 | 结果 |
|---|---|---|
| eth/arbitrum/optimism publicnode `eth_getLogs` | 代币 Transfer 日志 | **403 Forbidden**(不限 range 也 403) |
| avalanche-c-chain publicnode `eth_getLogs` | 同上 | **可用**,但 `exceed maximum block range: 50000` |
| gateway.tenderly.co/public/arbitrum | 同上 | 可用,chainId=42161(0xa4b1) |
| gateway.tenderly.co/public/optimism | 同上 | 可用,chainId=10(0xa) |
| rpc.mevblocker.io | 同上(仅 ETH) | 可用,chainId=1 |
| arbitrum.drpc.org | 同上 | 可用,chainId=42161 |
| eth/optimism/arbitrum.blockscout.com `api/v2/addresses/{a}/token-transfers` | 按地址取全部 ERC20 转账(带 timestamp、from、to、total、可分页) | **可用**(blockscout 必须带完整浏览器头,否则 403) |
| api.llama.fi/protocols | 协议 treasury 字段 | 8903 协议里 323 个有 treasury,但 10 个目标名字的 treasury 全为 null(字段指向 adapter 文件名,不含地址) |
| api.coingecko.com/api/v3/coins/{id} | 代币合约地址 | 可用(有限速),给出了 ONDO=0xfaba6f8e…、STRK=0xca14007e…、ARB=0x912ce591…(arb)/0xb50721bc…(eth)、OP=0x42…0042 |
| Supabase ohlcv_daily | USD 价格 | 可读;ARB 2023-03-23 起、OP 2022-05-31、ONDO 2024-01-18、STRK 2024-02-20、AVAX 2020-09-22,最新 2026-11-01(ARB 0.163739 / OP 0.112962 / ONDO 0.4047 / STRK 0.0427538 / AVAX 8.69) |

限速:Blockscout 公开实例未观测到硬限速,按 ~50 条/页分页;publicnode 按 5 万块/请求;CoinGecko 免费档 429 明显。

## 4. 非 EVM 链上「读不到」的判定与可用 RPC(实测)

| 链 | 公共 RPC 实测 | 事件能否取 | 备注 |
|---|---|---|---|
| SOL | https://api.mainnet-beta.solana.com `getSlot` **OK**(slot 464509521) | 勉强:余额可 `getBalance`;Transfer 需 `getSignaturesForAddress`+逐笔 `getTransaction` 解析,比 EVM 慢 1–2 个量级 | 缺地址(集合为空) |
| APT | https://fullnode.mainnet.aptoslabs.com/v1 | REST:账户余额可读;事件需 GraphQL indexer(需 key) | 缺地址 |
| SUI | https://sui-rpc.publicnode.com | **JSON-RPC 已废弃**(实测 error -32000 "Sui JSON-RPC endpoint has been deprecated"),须改用 GraphQL(`/graphql`)或官方 gRPC | 缺地址 |
| TIA | https://celestia-rpc.publicnode.com | 非 EVM(CometBFT),`eth_blockNumber` -32601;事件用 `tx_search`/indexer | 归属锁仓在 Cosmos Hub vesting account,非 Celestia 合约 |
| DOT | 公共 RPC 为 WebSocket(`wss://rpc.polkadot.io`),HTTP 不可用 | treasury 账户需 polkadot.js 侧读 | 缺地址 |

## 5. 事件定义(先写再算)

- **集合**:某名字的「有出处地址集合」(§2),余额 = 该集合内各地址该代币余额之和。
- **日流出**:该集合当日对该代币的净转出量(流出 USD - 流回 USD,取净;原始两列都留)。
- **事件 E**:某日该集合的**单日净流出 ≥ 当日集合总余额的 1%**(余额为 0 的日子不计)。
- **不判收益、不判方向**;本卡只交数据、事件数与覆盖率表。

## 6. 预注册草稿(不算结果)

- 宇宙:CIS 加密 25 名等权;事件:E 定义下的单日净流出 ≥ 1% 集合余额。
- 结果窗:事件日后 30 / 90 天相对宇宙的收益(仅登记,不跑)。
- 对照:随机日期 + `shuffle_within`;零分布 `null_distribution` + `percentile_of`;入场 `price_on_or_after(T+1)`。
- 试验计数:治理族第 1 次、卡内 k=4 ⇒ 阈值 0.0125。
- 检验纪律:**信号日当天的派生量判完再挪一天判一次**(S-665:挪一天 p 从 0.02 变 0.35,T-178)。

## 7. 未完成项与续跑起点(下一轮)

未完成:①`docs/research/t226_wallets/*.csv`(address,d,balance,out_usd,in_usd)②事件数与日期 ③10 个名字完整覆盖率表。
原因:本轮上下文(121k)触发钩子拦截,抓取脚本无法执行 —— 不是数据源问题(端点已全部实测可用)。
续跑起点(已就位,**改同一个文件再跑**,不要新建 probe):
- 抓取器:`/Volumes/CometCloudAI/cometcloud-local/research/t226/fetch_t226.py`(Blockscout 分页路径;ISO timestamp 解析已修;
  期初余额用「2024-01-01 前累计净额」重建,避免依赖历史 state 的 `eth_call`)。
- 中间产物:`/Volumes/CometCloudAI/cometcloud-local/research/t226/`(llama_protocols.json、holders_non_exch.json、icf_forum.txt、ddg_*.json、op_community_hub.json)。
- 已测得的链上余额(latest,供核对):ARB DAO Treasury 2,556,141,991.51 ARB;ARB Vesting Budget 80,977,188.46 ARB;ARB Token Distributor 0;
  OP Foundation 318,475,104.58 OP;OP Safe#1 1,294,044,371.32 OP;ONDO Multisig 2 5,179,207,574.16 ONDO;STRK LockedTokenGrant 206,705,075 STRK。
- 待补地址:AVAX(C-chain 归属)、SOL/APT/SUI/TIA/DOT 的非 EVM 归属地址 ⇒ 需 @seth 判断是否值得再做一轮人工出处检索。
