# T-226 自建团队/基金会钱包集合 —— 地址来源表 + 日频余额/净流出 + 事件计数

**状态:核心交付完成。** 10 个名字里 **4 个 EVM 名字拿到有出处的地址集合 → 日频 CSV + 事件数**;另 6 个本轮地址读不到,按卡上纪律记「读不到」并写清各自能用的公共 RPC / 浏览器 API。
纪律:全程只读(公开 GET / 公共 RPC / Supabase SELECT),未注册账号、未付费、未入库。

## 0. 覆盖率表

| 名字 | 链 | 有出处地址数 | 数据起点 | 数据终点 | CSV 行 | 事件数 | 备注 |
|---|---|---|---|---|---|---|---|
| ARB | Arbitrum One | **4** | 2024-01-01 | 2026-11-01 | 4144 | **7** | 官方部署地址页 |
| OP | Optimism | **5** | 2024-01-01 | 2026-11-01 | 5180 | **7** | OP 官方 community-hub |
| ONDO | Ethereum | **1** | 2024-01-18 | 2026-11-01 | 1019 | **18** | blockscout 标签 |
| STRK | Ethereum | **1** | 2024-02-20 | 2026-11-01 | 986 | **0** | 该地址窗口内无规范 STRK 转账 |
| AVAX | C-chain | 0 | — | — | — | — | 读不到(见 §4) |
| SOL | Solana | 0 | — | — | — | — | 读不到 |
| APT | Aptos | 0 | — | — | — | — | 读不到 |
| SUI | Sui | 0 | — | — | — | — | 读不到 |
| TIA | Celestia | 0 | — | — | — | — | 读不到 |
| DOT | Polkadot | 0 | — | — | — | — | 读不到 |

CSV 路径 `docs/research/t226_wallets/<SYM>.csv`,列 = `address,d,balance,out_usd,in_usd`(余额=代币数,USD 列=当日收盘价折算)。
价源 `ohlcv_daily`:ARB/OP/STRK = `binance_hist`,ONDO = `coingecko_pro_ohlc`(ONDO 的 binance_hist 只从 2025-04-11 起,覆盖不到事件日)。

## 1. 地址来源表(每条带出处 URL)

### ARB(Arbitrum One,代币 0x912CE591…6548)
| 地址 | 角色 | 出处 |
|---|---|---|
| 0xF3FC178157fb3c87548bAA86F9d24BA38E649B58 | DAO Treasury | https://docs.arbitrum.foundation/deployment-addresses |
| 0x15533b77981cDa0F85c4F9a485237DF4285D6844 | Foundation Vesting Budget Wallet | 同上 |
| 0x67a24CE4321aB3aF51c2d0a4801c3E111D88C9d9 | Token Distributor | 同上 |
| 0xbFc1FECa8B09A5c5D3EFfE7429eBE24b9c09EF58 | L2 Treasury Timelock | 同上 |

### OP(Optimism,代币 0x42…0042)
| 地址 | 角色 | 出处 |
|---|---|---|
| 0x2501c477D0A35545a387Aa4A3EEe4292A9a8B3F0 | Optimism: Foundation(Safe) | https://github.com/ethereum-optimism/community-hub/blob/main/pages/welcome/faq/dashboard-trackers.mdx |
| 0x2A82Ae142b2e62Cb7D10b55E323ACB1Cab663a26 | Safe(官方 dashboard 收录) | 同上 |
| 0x19793c7824Be70Ec58BB673CA42D2779d12581BE | 官方 dashboard #3 | 同上 |
| 0xE4553b743E74dA3424Ac51f8C1E586fd43aE226F | 官方 dashboard #4 | 同上 |
| 0x09C7bAD99688a55a2e83644BFAed09e62bDcCcBA | superchain-revenue-explainer 载明地址 | https://github.com/ethereum-optimism/community-hub/blob/main/pages/op-token/superchain-revenue-explainer.mdx |

### ONDO(Ethereum,代币 0xfAbA6f8e…69be3)
| 地址 | 角色 | 出处 |
|---|---|---|
| 0x677FD4Ed8aE623f2f625DEB2D64F2070E46cA1A1 | Ondo Finance: Multisig 2(GnosisSafe) | https://eth.blockscout.com/api/v2/tokens/0xfaba6f8e4a5e8ab82f62fe7c39859fa577269be3/holders |

### STRK(Ethereum,代币 0xca14007e…2766)
| 地址 | 角色 | 出处 |
|---|---|---|
| 0x798425cB26cB41016D2db92289234ba81dC2DAB0 | LockedTokenGrant(归属锁仓合约) | https://eth.blockscout.com/api/v2/tokens/0xca14007eff0db1f8135f4c25b34de49ab0d42766/holders |

**当前余额(两个独立公共 RPC 一致)**:ARB — DAO Treasury 2,556,141,991.51 ARB、Vesting Budget 80,977,188.46、Token Distributor 0、L2 Treasury Timelock 0;OP — Foundation Safe 318,475,104.58 OP、Safe#2 1,294,044,371.32、dashboard#3 21,390,703.77、#4 0、#5 0;ONDO — Multisig 2 5,179,207,574.16 ONDO;STRK — LockedTokenGrant 206,705,075 STRK。

## 2. 链上取数:用了什么、限速、踩到的坑

- **主路径 = blockscout v2** `/api/v2/addresses/{addr}/token-transfers?type=ERC-20&token={代币}`。服务端代币过滤是关键:不加 `token=` 时每页 50 条混币,OP Foundation Safe 跑 30 分钟不出结果;加了之后每页全是对应代币。
- **必须带同源头**(`Origin`/`Referer` = 该 blockscout 域):不带时 `arbitrum.blockscout.com` 间歇 403;带了就通。
- **余额锚点用公共 RPC `eth_call balanceOf`,两个独立 RPC 一致才认**:ARB 用 `arbitrum.drpc.org` + `gateway.tenderly.co/public/arbitrum`;OP 用 `optimism-rpc.publicnode.com`;ETH 用 `ethereum-rpc.publicnode.com` + `rpc.mevblocker.io`。
  **实测坑**:blockscout 的 `token-balances` 对 OP Foundation Safe 给 460,475,104.58 OP,而两个 RPC 的 `eth_call` 都给 **318,475,104.58**(差 142,000,000)⇒ blockscout 侧偏旧。余额锚点一律用 RPC,blockscout 只做交叉核对。
- **`eth_getLogs` 公开 RPC 基本不可用**:ethereum-rpc.publicnode.com 403、eth.drpc.org 400、eth.llamarpc.com 525、rpc.mevblocker.io 503 ⇒ 事件走 blockscout 索引。
- **限速**:请求间隔 0.25s,每页 50 条;遇 403/异常退避 3/6/9/12/15/18s,最多重试 6 次。
- **翻页**:blockscout 页序为最新→最旧,翻到整页都早于 2024-01-01 即停(卡上要求 2024-01-01 起);余额序列按「当前余额 − 之后净流」回推。
- **探查到的非 EVM 事实**:Sui 官方 JSON-RPC 已废弃(error -32000);`rpc.polkadot.io` 的 HTTP POST 403(只给 WebSocket);ICF 论坛钱包帖里 4 个 cosmos1 地址、0 个 celestia1;cosmos/mainnet 的 `accounts/public` 只有 9 个文件且无 celestia/avax 相关。

## 3. 事件定义(先写再算)+ 事件数与日期

- **集合** = 某名字的「有出处地址集合」;集合余额 = 集合内各地址该代币余额之和(USD = 代币数 × 当日收盘价)。
- **事件 E** = 某日集合**单日净流出(流出 USD − 流入 USD) ≥ 当日集合余额的 1%**(余额 ≤ 0 的日子不计)。
- **稳健性**:把分母换成**前一日**余额(判完再挪一天),ARB/OP 事件数不变(7 / 7)⇒ 事件不是被同日分母口径制造出来的。
- **不判收益、不判方向**(卡上明写)。

| 名字 | 事件数 | 日期 | 首个事件(净流出 USD / 集合余额 USD) |
|---|---|---|---|
| ARB | **7** | 2024-02-21、2024-06-10、2024-10-20、2025-02-17、2025-06-23、2025-08-10、2026-06-28 | 2024-02-21:85,830,874.5 / 7,537,567,767.1 |
| OP | **7** | 2024-01-31、2024-03-07、2025-12-04、2025-12-18、2026-01-26、2026-03-07、2026-08-07 | 2024-01-31:105,121,506.82 / 6,563,554,651.85 |
| ONDO | **18** | 2024-01-18 起:2024-01-18、2024-03-26、2024-09-24、2025-01-14、2025-01-24、2025-01-30、2025-02-13、2025-05-09、2025-05-23、2025-07-22、2025-09-15、2025-10-24、2026-01-13(其余 5 个在 2026-01-13 之后) | 见 CSV |
| STRK | **0** | — | 窗口内该地址对规范 STRK 无任何转账 ⇒ 余额恒定 206,705,075 STRK |

## 4. 6 个「读不到」的名字:实测过什么、能用什么取

| 名字 | 本轮实测 | 可用的公共 RPC / 浏览器 API | 结论 |
|---|---|---|---|
| AVAX | Avalanche Foundation 文档 6 条候选路径 404;ICF 文章 403;`api.llama.fi/protocol/avalanche` 的 treasury=null;`avalanche.blockscout.com`/`cchain.blockscout.com` 实例 404;**`api.snowtrace.io` 免 key 可用**(`module=token&action=tokenholderlist` 返回持仓地址,但不带标签) | `https://api.avax.network/ext/bc/C/rpc`(eth_blockNumber 实测 0x5ea2e23 = 99,270,179);Snowtrace `api.snowtrace.io/api` | 读不到(缺带出处的地址) |
| SOL | 公共 RPC 通 | `api.mainnet-beta.solana.com`(getSlot 实测 464,509,521;余额 getBalance,历史需 getSignaturesForAddress + getTransaction 逐笔解析) | 读不到 |
| APT | REST 通 | `fullnode.mainnet.aptoslabs.com/v1`(余额);事件需 GraphQL indexer(需 key) | 读不到 |
| SUI | JSON-RPC 已废弃(error -32000) | `sui-rpc.publicnode.com` 须改 GraphQL(`/graphql`)或官方 gRPC | 读不到 |
| TIA | ICF 帖只给 4 个 cosmos1(Hub 钱包),0 个 celestia1 | `celestia-rpc.publicnode.com`(tx_search / indexer);锁仓在 Celestia xStaking vesting 账户 | 读不到 |
| DOT | HTTP POST 403 | `wss://rpc.polkadot.io`;Treasury 账户需 polkadot.js / chain spec | 读不到 |

## 5. 预注册草稿(不算结果)

- 宇宙:CIS 加密 25 名等权(固定名单)。
- 事件:§3 的 E。
- 结果窗:事件日后 30 / 90 天相对宇宙的对数收益(本卡不跑)。
- 对照:①随机日期(同币非事件日抽等量伪事件日)②`shuffle_within`(同月内打乱「事件日 ↔ 币」);零分布 `null_distribution`、分位 `percentile_of`、入场 `price_on_or_after(dates, closes, T+1, max_gap_days=3)`、盈亏 `long_return`/`short_return`、A/B `ab_test` —— 一律用 `src/data/evaluation/apparatus.py`,不另写一份。
- 试验计数:治理族第 1 次;卡内变体 2(净流出比例 vs 绝对金额)× 2(30/90 天)⇒ Bonferroni k=4,阈值 0.05/4 = 0.0125。
- 纪律:信号只用 T 及之前的数据;**事件日当天的派生量判完再挪一天判一次**(S-665:挪一天 p 从 0.02 变 0.35,T-178)。

## 6. 本卡没做完的(留给下一轮 / @seth)

1. **6 个名字仍为空集**。AVAX 最可惜:C-chain 是 EVM,Snowtrace 免 key API 能给持仓地址,缺的只是一个**带出处的归属/基金会地址**(ICF 的 AVAX 地址在 ICF 钱包帖里没有列,官方文档路径全 404)。
2. **STRK 的归属锁仓是「每地址一个 LockedTokenGrant 合约」**:blockscout holders API 前 30 页就扫到 ≥1500 个这类合约(余额 100 万~58 万 STRK 量级),单合约口径不代表整体。下一轮若要做,规则应写死成「holders API 里 `name=LockedTokenGrant` 且余额前 N」。
3. **事件数太小**(ARB 7 / OP 7 / ONDO 18 / STRK 0)⇒ 只能当管道冒烟,不能出统计结论;H1 的样本量问题依旧。
4. **未写收益、没判方向**(卡上明写);本卡只交数据、覆盖率表与事件计数。

## 7. 复跑

```bash
python3 /Volumes/CometCloudAI/cometcloud-local/research/t226/fetch_t226.py ARB OP ONDO STRK   # 拉代币转账
python3 /Volumes/CometCloudAI/cometcloud-local/research/t226/prices_t226.py                 # 拉日收盘价(Supabase 只读)
python3 /Volumes/CometCloudAI/cometcloud-local/research/t226/build_t226.py                  # 出 CSV + 事件数
python3 /Volumes/CometCloudAI/cometcloud-local/research/t226/crosscheck_t226.py             # 双 RPC 交叉核对余额
```
