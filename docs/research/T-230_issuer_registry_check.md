# T-230 发行方登记表核验（37 家）

**卡**: T-230（lane-b）· **日期**: 2026-11-04 · **纪律**: 只读;不改代码、不做 DDL、不入库;不评价、不打分。

## 0. 口径与方法

**被核对象**：`issuer_entities` 表（2026-11-04 实读，37 行）与主仓 `src/data/entity/issuers.py` 的 `ENTITIES` 逐行比对，**两者完全一致**（id / kind / instruments / confidence 均对得上），所以下面引用代码行号即可定位。

| 项 | 实测值 |
|---|---|
| 表内行数 | 37 |
| kind 分布 | foundation 19 · company 8 · venue 6 · stablecoin_issuer 3 · protocol 1 |
| confidence 分布 | **assumed 36 / verified 1**（只有 `bitcoin`）—— 本卡要把这 36 家的 assumed 变成带出处的结论 |
| 主源 | 官网 · 治理论坛（gov.uniswap.org / governance.aave.com / gov.optimism.io / forum.arbitrum.foundation / forum.polygon.technology / community.starknet.io / research.lido.fi / vote.sky.money 等）· SEC EDGAR（10-K / 10-Q / 20-F / S-1 / F-1 / 8-K）· 官方博客 · 评级机构（Moody's / S&P）· DeFiLlama |
| 只读探针 | `docs/research/_t230_probe.py`（跑 8 次；只 GET，不写） |

**建议分级**：
- **改** —— 主体名 / kind / 工具清单 三者之一与核到的事实不符，给出具体改法。
- **不改** —— 核到后确认现值正确。
- **核不到(部分)** —— 该行的**主体与工具已核到**（建议方向成立），但有子项查不到且**写进报告**（例如某份治理投票的结果读不到）。**本卡无整行核不到。**

**计数**：**建议改 29 家 / 不改 8 家 / 整行核不到 0 家 / 部分子项核不到 12 家**。
其中 **kind 建议改动 6 家**（celestia、chainlink-labs、ondo、pendle、robinhood、sky）；**工具清单建议动 11 行**（净增 9 个工具、移除 2 个）。

---

## 1. 37 行总表

| id | 当前 name | 当前 kind | 当前 instruments | 建议 | 建议改法（摘要） | 出处 |
|---|---|---|---|---|---|---|
| aave | Aave Labs / Aave DAO | foundation | AAVE:token, GHO:stablecoin | **改** | name→「Aave DAO(Aave Labs 为开发公司，持约 23% AAVE)」；note 改为「GHO 由 Aave DAO 直接发行；回购 2025-04 启动 → 2026-04-19 暂停(rsETH) → Aavenomics 3.0 于 2026-06-27 恢复链上自动回购；2026-04 约束性投票通过 2500 万美元资助 + 5000 AAVE 授予 Labs」。kind/instruments 不变 | [governance.aave.com/t/arfc-pause-aave-buybacks/24686](https://governance.aave.com/t/arfc-pause-aave-buybacks/24686) · [arfc-aave-will-win-framework/24352](https://governance.aave.com/t/arfc-aave-will-win-framework/24352) |
| aptos-foundation | Aptos Foundation / Aptos Labs | foundation | APT:token | **改** | name→「Aptos Foundation(Aptos Labs, operator)」；kind/instruments 不变 | [governance.aptosfoundation.org](https://governance.aptosfoundation.org/) · [aptoslabs.com](https://aptoslabs.com/) |
| arbitrum | Arbitrum DAO / Arbitrum Foundation / Offchain Labs | foundation | ARB:token | **改** | name→「Arbitrum DAO(Arbitrum Foundation；Offchain Labs, operator)」；kind 仍 foundation（代币治权在 DAO，Foundation 是执行方，protocol 档更贴切但可选）；instruments 不变 | [docs.arbitrum.foundation/state-of-progressive-decentralization](https://docs.arbitrum.foundation/state-of-progressive-decentralization) · [blog.arbitrum.foundation/the-next-phase-of-decentralization](https://blog.arbitrum.foundation/arbitrum-the-next-phase-of-decentralization/) |
| ava-labs | Ava Labs / Avalanche Foundation | foundation | AVAX:token | **改** | name→「Avalanche Foundation」（现名**主次颠倒**：AVAX 经济在 Avalanche Foundation，Ava Labs 只是商业技术公司）；**instruments 加 `AVAT:equity`**（Avalanche Treasury Corporation，Nasdaq 2026-06 上市，为 Avalanche Foundation 控股子公司）；kind 不变 | [nasdaq.com/market-activity/stocks/avat](https://www.nasdaq.com/market-activity/stocks/avat) · [cnbc.com/2026/06/11/…](https://www.cnbc.com/2026/06/11/avalanche-focused-treasury-firm-launches-on-nasdaq-as-crypto-proxy-trade-evolves.html) |
| binance | Binance | venue | BNB:token, BINANCE:venue | **改** | name→「Binance(Binance Holdings Ltd.)」；kind/instruments 不变；note 注明 `BINANCE:venue` 只指主场所（Binance.US / Binance Europe 为独立实体），**FDUSD 由香港 First Digital Labs 发行、非 Binance 自有**，BUSD 已停发 | [binance.com/en/academy/articles/what-is-first-digital-usd-fdusd](https://www.binance.com/en/academy/articles/what-is-first-digital-usd-fdusd) · [firstdigitallabs.com](https://www.firstdigitallabs.com/) |
| bitcoin | Bitcoin | protocol | BTC:token | **不改** | 无发行主体，protocol 正确 | [bitcoin.org/en/faq](https://bitcoin.org/en/faq) |
| block | Block, Inc. | company | XYZ:equity | **不改** | 法定名与代码（2025-01 由 SQ 改 XYZ）均正确；**无自有稳定币**（Cash App 只接入第三方）、**不开场所**（托管商 + 券商） | [investors.block.xyz/…Ticker-Symbol-Change-to-XYZ](https://investors.block.xyz/investor-news/news-details/2025/Block-Announces-Ticker-Symbol-Change-to-XYZ-To-Report-Fourth-Quarter-Results/default.aspx) · [sec.gov/…/xyz-20251231.htm](https://www.sec.gov/Archives/edgar/data/1512673/000162828026012254/xyz-20251231.htm) |
| bullish | Bullish | venue | BLSH:equity, BULLISH:venue | **改(note)** | id/name/kind/instruments 全不改；**note 更正：CIK 0001872195，F-1 / 20-F / 6-K 齐全，是外国私人发行人，不是「SEC 无 CIK」**（走 20-F 不走 10-K，多半是当初误判的来源）；**无自有稳定币**（是 SoFiUSD 等的分销方） | [sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001872195](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001872195) · [blsh20251231_20f.htm](https://www.sec.gov/Archives/edgar/data/1872195/000143774926007417/blsh20251231_20f.htm) |
| cardano-iog | Cardano (IOG / Cardano Foundation) | foundation | ADA:token | **改** | name→「Input Output Global(IOG)」—— **ADA 的原始发行与最大持有主体是 IOG**，Foundation / Intersect 承担治理与国库；现名把持币方与运营方并列且主次不明。**USDM 不是 Foundation/IOG 发行**（Moneta Digital LLC） | [cardano.org/genesis](https://cardano.org/genesis/) · [cardanofoundation.org/glossary](https://cardanofoundation.org/glossary) · [moneta.global/learn/usdm-core-fundamentals](https://moneta.global/learn/usdm-core-fundamentals/) |
| celestia | Celestia Foundation / Labs | foundation | TIA:token | **改** | name→「Celestia Labs(Celestia Foundation 列支敦士登，仅持约 7.5% TIA)」；**kind foundation→company**（Labs/核心贡献者持约 21.5% > Foundation 的 7.5%）；instruments 不变 | [docs.celestia.org/learn/TIA/staking-governance-supply](https://docs.celestia.org/learn/TIA/staking-governance-supply/) · [app.tokenomics.com/tokenomics/celestia](https://app.tokenomics.com/tokenomics/celestia) |
| chainlink-labs | Chainlink Labs | company | LINK:token | **改** | name→「Chainlink Foundation(Chainlink Labs 为运营公司)」；**kind company→foundation**（LINK 主要经济资源由 Foundation 持有，Labs 无股权/IP/利润）；instruments 不变。**无股票**（上市的是 Bitwise Chainlink Trust ETF，ticker CLNK） | [chain.link/faqs](https://chain.link/faqs) · [sec.gov/…/bitwise s1a2](https://www.sec.gov/Archives/edgar/data/2082889/000121390026001140/ea027072801-s1a2_bitwise.htm) |
| circle | Circle Internet Group | stablecoin_issuer | CRCL:equity, USDC:stablecoin | **改** | **instruments 加 `EURC:stablecoin`**（Circle Mint Europe SAS，法国 ACPR 许可，2026-09-30 流通约 €4.65 亿）；note 改为收入分成档位与「无股息/回购授权核不到」；kind 不变。**USYC 不是 Circle 的**（HashKey 发行） | [sec.gov/…/crcl-20260630.htm](https://www.sec.gov/Archives/edgar/data/1876042/000187604226000248/crcl-20260630.htm) · [circle.com/eurc](https://www.circle.com/eurc) |
| coinbase | Coinbase Global | venue | COIN:equity, COINBASE:venue | **不改** | kind=venue 成立（Coinbase Exchange, Inc. 是 SEC 注册交易所）；USDC 归 Circle、Coinbase 只是分成方，现行写法正确。note 可补：2025-12 依 TBOC 由 Delaware 迁册 Texas | [sec.gov/…/coin-20260630.htm](https://www.sec.gov/Archives/edgar/data/1679788/000167978826000088/coin-20260630.htm) · [coinbase.com/blog/ushering-in-the-next-chapter-for-usdc](https://www.coinbase.com/blog/ushering-in-the-next-chapter-for-usdc) |
| ethereum-foundation | Ethereum Foundation | foundation | ETH:token | **不改** | EF 是唯一有法律人格的生态主体；**不发行稳定币**（反而把 ETH 换成稳定币付运营费）、不运营交易所、无股票 | [ethereum.org/foundation](https://ethereum.org/foundation/) · [blog.ethereum.org/2025/06/04/ef-treasury-policy](https://blog.ethereum.org/2025/06/04/ef-treasury-policy) |
| figure | Figure Technology Solutions | company | FIGR:equity | **改** | **instruments 加 `FIGURE:venue`**（Figure Markets / Figure Exchange / SEC 注册经纪商 Figure Securities）；kind 不变；**无自有稳定币**；IPO 是 2025-09-10 定价 / 09-11 交易，**不是 2025-08** | [figuremarkets.com](https://www.figuremarkets.com/) · [sec.gov/…/figr-20251231.htm](https://www.sec.gov/Archives/edgar/data/2064124/000206412426000009/figr-20251231.htm) |
| galaxy | Galaxy Digital | company | GLXY:equity | **不改** | 法定名 Galaxy Digital Inc.，2025-05-16 Nasdaq 上市（重组上市，非直接上市）；**无自有稳定币**（持 sUSDS / 代币化 GLXY 股票，是持有方不是发行方）、无注册交易所实体 | [sec.gov/…/glxy-20251231.htm](https://www.sec.gov/Archives/edgar/data/1859392/000185939226000016/glxy-20251231.htm) · [nasdaqtrader.com?id=ECA2025-246](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2025-246) |
| gemini | Gemini Space Station | venue | GEMI:equity, GEMINI:venue | **改** | **instruments 加 `GUSD:stablecoin`**（Gemini 自发、1:1 全额储备可无手续费 1:1 兑换）；kind 不变。法定名 Gemini Space Station, Inc.（内华达，2025-02 注册）；**「2025-05 更名自 Gemini Global Markets」核不到** | [investors.gemini.com/node/7541/ixbrl-viewer](https://investors.gemini.com/node/7541/ixbrl-viewer) · [nasdaq.com/market-activity/stocks/gemi](https://www.nasdaq.com/market-activity/stocks/gemi) |
| hyperliquid | Hyperliquid (Hyper Foundation / Hyperliquid Labs) | venue | HYPE:token, HYPERLIQUID:venue, USDH:stablecoin | **改** | **instruments 移除 `USDH:stablecoin`** —— USDH **不是 Hyperliquid 发行**：发行权 2025-09-15 由治理论坛投票给 Native Markets，2026-05-14 品牌资产购买权转到 Coinbase（同期 USDC 成为原生抵押）。name→「Hyper Foundation(Hyperliquid Labs, operator)」；**kind=venue 不变**（它不构成 stablecoin_issuer）。另注：Hyperliquid Strategies Inc.（ticker **PURR**）是持 HYPE 的独立财库公司，**是另一个发行方**，若要收录股票须单列一行 | [coinbase.com/blog/coinbase-and-hyperliquid-aligning-markets-on-hyperliquid-to-usdc](https://www.coinbase.com/blog/coinbase-and-hyperliquid-aligning-markets-on-hyperliquid-to-usdc) · [blockworks.com/token-transparency/filing/hyperliquid](https://blockworks.com/token-transparency/filing/hyperliquid) |
| injective | Injective Labs / Foundation | foundation | INJ:token | **不改** | Injective Foundation 持约 46.33% INJ，是最大持币主体；**无股票**（21Shares INJ ETF 是 ETF；Pineapple Financial NASDAQ:PAPL 是持币公司不是 Injective）、**无自有稳定币**、不-self 营场所 | [injective.com/INJ_MiCA_Whitepaper.pdf](https://injective.com/INJ_MiCA_Whitepaper.pdf) · [blockworks.com/token-transparency/filing/injective](https://blockworks.com/token-transparency/filing/injective) |
| lido | Lido DAO | foundation | LDO:token, STETH:token | **改** | **instruments 加 `WSTETH:token`**（Lido 官方主代币，1:1 锚定 stETH）；name→「Lido DAO(Lido Labs Foundation 无控制权)」；kind 不变。**无自家稳定币**（stETH/wstETH 是质押凭证不是稳定币） | [blockworks.com/token-transparency/filing/lido](https://blockworks.com/token-transparency/filing/lido) · [blog.lido.fi/ldo-automated-buybacks-overview](https://blog.lido.fi/ldo-automated-buybacks-overview/) |
| near-foundation | NEAR Foundation | foundation | NEAR:token | **不改** | 单一法律实体（瑞士非营利）；2025-10-13 House of Stake 上线后协议参数由 veNEAR 质押投票决定。**无自家稳定币、无股票、不开场所** | [near.foundation](https://near.foundation/) · [near.org/blog/near-house-of-stake-is-now-live-on-mainnet](https://www.near.org/blog/near-house-of-stake-is-now-live-on-mainnet) |
| ondo | Ondo Finance | company | ONDO:token, USDY:stablecoin | **改** | name→「Ondo Foundation(Ondo Finance 为商业运营公司)」；**kind company→foundation**（Ondo Foundation 开曼无实益所有人非营利，持 ONDO 绝大部分并掌 Flux 治理权）；**instruments 加 `OUSG:token`**。**oUSDT 不存在**；**syrupUSDC 属 Maple Finance 不属 Ondo**；Ondo 自身无股票 | [ondo.foundation/about](https://ondo.foundation/about) · [blockworks.com/token-transparency/filing/ondo](https://blockworks.com/token-transparency/filing/ondo) · [ondo.finance/ousg](https://ondo.finance/ousg) |
| optimism | Optimism Foundation / OP Labs | foundation | OP:token | **改** | name→「Optimism Foundation(OP Labs, operator)」；kind/instruments 不变。OP Labs 是私营 PBC，**无股票**、不-self 营场所；Foundation 仍直接持币并主导 2026 年回购决策 | [gov.optimism.io/t/proposal-to-align-the-op-token-with-superchain-success/10527](https://gov.optimism.io/t/proposal-to-align-the-op-token-with-superchain-success/10527) · [optimism.io/blog/op-token-buybacks](https://optimism.io/blog/op-token-buybacks) |
| paxos | Paxos | stablecoin_issuer | PYUSD:stablecoin, USDG:stablecoin | **改** | **instruments 加 `USDP:stablecoin`、`PAXG:token`**；note 改为「USDG 发行方是 Paxos Digital Singapore；USDP + PAXG 为自有工具；无股票（2022 保密 S-1 已撤回，『2025-08 宣布 Nasdaq IPO』核不到，实际是 OCC 国民信托牌照申请 + SEC 清算机构登记）；持有人 0（Partner Rewards 付分销伙伴，不是持有人）」。**PAX Stablecoin 已停铸**（后继是 USDP） | [docs.paxos.com/guides/stablecoin](https://docs.paxos.com/guides/stablecoin) · [paxos.com/usdp-transparency](https://www.paxos.com/usdp-transparency) · [forgeglobal.com/paxos_ipo](https://forgeglobal.com/paxos_ipo/) |
| paypal | PayPal Holdings | company | PYPL:equity, PYUSD:stablecoin | **改** | **instruments 移除 `PYUSD:stablecoin`** —— PYUSD 实际发行方是 Paxos Trust Company, N.A.，PayPal 只是品牌与分销方；现写法与 `entity_by_symbol()`（PYUSD→paxos）自相矛盾（见 §6）。**PayPal 无 PAY 代币**、不-self 营交易所；kind 不变 | [paxos.com/pyusd](https://www.paxos.com/pyusd) · [newsroom.paypal-corp.com/2023-08-07-PayPal-Launches-U-S-Dollar-Stablecoin](https://newsroom.paypal-corp.com/2023-08-07-PayPal-Launches-U-S-Dollar-Stablecoin) |
| pendle | Pendle | foundation | PENDLE:token | **改** | name→「Pendle(Pendle Foundation 持 64.63%；新加坡主体运营)」；**kind foundation→company**（有公司化运营主体、法域明确、无非营利/捐赠治理属性）；instruments 不变。PT/YT/SY/weETH/ezETH 是收益凭证不是稳定币 | [app.tokenomics.com/tokenomics/pendle](https://app.tokenomics.com/tokenomics/pendle) · [docs.pendle.finance/pendle-v2/TermsOfUse](https://docs.pendle.finance/pendle-v2/TermsOfUse) |
| polygon-labs | Polygon Labs / Polygon Foundation | foundation | POL:token | **改** | name→「Polygon Foundation(Polygon Labs, operator)」；**id 建议一并改 `polygon-foundation`**（现 id 指向运营方，但持币主体是 Foundation）；kind/instruments 不变 | [forum.polygon.technology/t/pip-85-veblop-pip-65-priority-fee-formula-adjustment/21829](https://forum.polygon.technology/t/pip-85-veblop-pip-65-priority-fee-formula-adjustment/21829) · [polygon.technology/blog/polygon-2-0-tokenomics](https://polygon.technology/blog/polygon-2-0-tokenomics) |
| ripple | Ripple Labs | company | XRP:token, RLUSD:stablecoin | **不改** | Ripple Labs, Inc.（特拉华私人公司）控制 XRP 发行；RLUSD 由 Ripple 发行（2024-12 上线，2025-11 破 $1B）。**无股票**（GXRP 是 ETF 不是股权）、**不运营交易所**（Ripple Markets 是托管/OTC 持牌外壳，成交在 LMAX/SIX/Coinbase/Bitstamp） | [ripple.com/products/stablecoin](https://ripple.com/products/stablecoin/) · [coindesk.com/…/ripple-s-stablecoin-hits-usd1b-milestone](https://www.coindesk.com/markets/2025/11/04/ripple-s-stablecoin-hits-usd1b-milestone-as-president-discusses-m-and-a-strategy-to-fuel-growth) |
| robinhood | Robinhood Markets | venue | HOOD:equity | **改** | **kind venue→company**（零售证券经纪 + 加密 App + 预测市场；**无自有稳定币**，链上用 Paxos Digital Singapore 的 USDG、USDC 归 Circle、RLUSD 归 Ripple）；**自建 Robinhood Chain**（Arbitrum L2，2026-07-01 主网）、2026-08-10 起在英国经 Bitstamp 交易 ⇒ 是自营场所但不是撮合交易所，不建议加 `:venue` 工具 | [robinhood.com/us/en/newsroom/robinhood-accelerates-global-expansion-robinhood-chain-mainnet…](https://robinhood.com/us/en/newsroom/robinhood-accelerates-global-expansion-robinhood-chain-mainnet-stock-tokens-agentic-trading/) · [globaldollar.com/newsroom/usdg-is-now-available-on-robinhood-chain…](https://globaldollar.com/newsroom/usdg-is-now-available-on-robinhood-chain-as-the-lending-asset-in-robinhood-s-new-earn-product) |
| sky | Sky (ex-Maker) | foundation | SKY:token, MKR:token, USDS:stablecoin, DAI:stablecoin | **改** | name→「Sky Frontier Foundation(Sky DAO 治理；ex-MakerDAO)」；**kind foundation→stablecoin_issuer**（SFF 是开曼发行主体，同时发行 USDS/DAI，2026-10-07 获 Moody's **B3 发行者评级** —— 稳定币协议首个）；**instruments 加 `SUSDS:token`**（Sky Savings Rate 收益凭证）。**DAI 未废弃**，与 USDS 并存，1:1 单向不可逆升级 | [ratings.moodys.com/ratings-news/474486](https://ratings.moodys.com/ratings-news/474486) · [prnewswire.com/…/moodys-ratings-assigns-first-issuer-rating-to-sky-protocol](https://www.prnewswire.com/news-releases/moodys-ratings-assigns-first-issuer-rating-to-sky-protocol-302900578.html) · [sky.money/blog/understanding-the-sky-token](https://sky.money/blog/understanding-the-sky-token) |
| solana-foundation | Solana Foundation / Solana Labs | foundation | SOL:token | **改** | name→「Solana Foundation」（Labs 自 2021 年起已退出代币委托运营，两个法律实体并列是多余的）；kind/instruments 不变。**不发行稳定币**、不运营场所（Jupiter/Phantom 是独立实体）；**NASDAQ:HSDT「Solana Company」与本行无关** | [medium.com/solana-labs/announcing-the-solana-foundation-delegation-strategy](https://medium.com/solana-labs/announcing-the-solana-foundation-delegation-strategy-5bcccf9104ab) · [solana.com/news/announcing-the-formation-of-the-solana-foundation](https://solana.com/news/announcing-the-formation-of-the-solana-foundation) |
| starkware | StarkWare / Starknet Foundation | foundation | STRK:token | **改** | name→「Starknet Foundation(StarkWare Industries, developer)」；**id 建议一并改 `starknet-foundation`**（Foundation 持初始供应 50.1%，StarkWare 只是开发/商业公司）；kind/instruments 不变。**无股票**（Forge Global：未上市、未递 IPO） | [starknet.io/blog/part-3-starknet-token-design](https://www.starknet.io/blog/part-3-starknet-token-design/) · [blockworks.com/token-transparency/filing/starknet](https://blockworks.com/token-transparency/filing/starknet) |
| strategy | Strategy (ex-MicroStrategy) | company | MSTR:equity | **改(name 细节)** | name→「Strategy Inc」（法定名是 **Strategy Inc**，不是 Strategy Incorporated）；**代码仍 MSTR**（2025-08-11 改名，08-12 生效，CUSIP 不变）；kind/instruments 不变 | [strategy.com/press/strategy-announces-legal-name-change…](https://www.strategy.com/press/strategy-announces-legal-name-change-from-microstrategy-incorporated-to-strategy-inc_08-14-2025) · [sec.gov/…/d938099d8k.htm](https://www.sec.gov/Archives/edgar/data/1050446/000119312525177517/d938099d8k.htm) |
| sui-foundation | Sui Foundation / Mysten Labs | foundation | SUI:token | **改** | name→「Sui Foundation(Mysten Labs, operator)」；kind/instruments 不变。**无自家稳定币、无股票**（Nasdaq 的 SUI 是住宅 REIT Sun Communities，无关）、不-self 营场所 | [sui.io/blog/sui-token-allocation](https://sui.io/blog/sui-token-allocation) · [sui.io/token-schedule](https://sui.io/token-schedule) |
| tether | Tether | stablecoin_issuer | USDT:stablecoin, XAUT:token | **改** | **instruments 加 `USAT:stablecoin`、`GEL:stablecoin`**（USAT 2026-01-27 经 Anchorage Digital Bank 上线；GEL 与格鲁吉亚政府合发）；note 改为「储备收益 100% 归股东侧；Q3 2026 鉴证：净经营利润约 $15 亿、储备 $1915 亿、缓冲约 $79.5 亿；Tether Holdings S.A.（离岸）与 Tether Foundation（瑞士）分立；无 IPO」。**`TBILL` 不是 Tether 的**（是 OpenEden 的代币化国债） | [tether.io/news/tether-q3-attestation-reveals-…](https://tether.io/news/tether-q3-attestation-reveals-highest-percentage-of-cash-and-cash-equivalent-reserves-over-330m-reduction-in-secured-loans-and-maintains-726b-exposure-in-us-t-bills/) · [anchorage.com/press-room/anchorage-digital-tether-introduce-usat](https://www.anchorage.com/press-room/anchorage-digital-tether-introduce-usat) · [tether.io/news/…launch-gelt-the-official-stablecoin-of-georgia](https://tether.io/news/tether-and-the-government-of-georgia-to-launch-gelt-the-official-stablecoin-of-georgia/) |
| uniswap | Uniswap Labs / Uniswap Foundation | foundation | UNI:token | **改(note)** | id/name/kind/instruments 全不改；**note 更正**：费用开关 2025-12 开启后协议费用于**回购并销毁 UNI**（一次性追溯销毁 1 亿 UNI，2026-07-27 执行），**不是「分给持有人」**；2026-06 提议改为质押分发未落定。**实测佐证**：`protocol_revenue_daily` 里 uniswap 的 `holders_30d = revenue_30d = 8,038,790` ⇒ `holders_share = 1.0` | [gov.uniswap.org/t/unification-proposal/25881](https://gov.uniswap.org/t/unification-proposal/25881) · [blog.uniswap.org/unification](https://blog.uniswap.org/unification) |
| web3-foundation | Web3 Foundation / Parity | foundation | DOT:token | **改** | name→「Web3 Foundation」（Parity Technologies 是独立商业开发公司，与 W3F 是合作不是同一组织）；kind/instruments 不变。**无自家稳定币、无股票、不运营场所** | [web3.foundation](https://web3.foundation/) · [parity.io](https://www.parity.io/) |

### 1.1 建议按类型汇总

| 类型 | 家数 | id |
|---|---|---|
| **主体名改**（持币方与运营方并列 / 主次颠倒 / 法定名不准） | 14 | aave, aptos-foundation, arbitrum, ava-labs, binance, cardano-iog, celestia, chainlink-labs, lido, ondo, optimism, polygon-labs, pendle, solana-foundation, starkware, sui-foundation, sky, web3-foundation（其中 18 行 name 建议动，见下） |
| **kind 改** | 6 | celestia(→company)、chainlink-labs(→foundation)、ondo(→foundation)、pendle(→company)、robinhood(→company)、sky(→stablecoin_issuer) |
| **工具清单改** | 11 | ava-labs(+AVAT:equity)、circle(+EURC)、figure(+FIGURE:venue)、gemini(+GUSD)、hyperliquid(−USDH)、lido(+WSTETH)、ondo(+OUSG)、paxos(+USDP、+PAXG)、paypal(−PYUSD)、sky(+SUSDS)、tether(+USAT、+GEL) |
| **note 更正**（不改字段，只改说明） | 3 | bullish（CIK 错）、uniswap（销毁不是分红）、strategy（法定名） |
| **完全不改** | 8 | bitcoin, block, coinbase, ethereum-foundation, galaxy, injective, near-foundation, ripple |

> name 建议动到的行数：**18**（aave, aptos-foundation, arbitrum, ava-labs, binance, cardano-iog, celestia, chainlink-labs, lido, ondo, optimism, polygon-labs, pendle, sky, solana-foundation, starkware, strategy, sui-foundation, web3-foundation 中的 name 项）—— 按上表逐行读即可，不另给数。

---

## 2. ② 六家「有收入不分」：收入实际去了哪里

**实测口径**（`treatment_daily`，2026-11-03，`revenue_30d` / `holders_30d` / `holders_share`）：

| symbol | revenue_30d (USD) | holders_30d | holders_share | 收盘 2026-11-03 |
|---|---|---|---|---|
| AAVE | 5,029,079 | 0 | 0 | 126.99 |
| LDO | 3,393,734 | 0 | 0 | 0.3319 |
| POL | 1,925,949 | 0 | 0 | 0.0919 |
| ARB | 654,061 | 0 | 0 | 0.1579 |
| STRK | 192,892 | 0 | 0 | 0.0422 |
| **OP** | **70,611** | 0 | 0 | 0.1092 |

（前一日 2026-11-02 读数同向：AAVE 5,021,116 / ARB 677,071 / LDO 3,502,734 / OP 72,763 / POL 2,012,439 / STRK 197,558 —— 都不是「当天成立」。）

| id | 收入去向 | 分配提案（编号 / 通过日 / 生效日 / 现状） | 对持有人的实际分配 | 口径结论 |
|---|---|---|---|---|
| aave | 收入进 DAO 国库；经自动化回购引擎在二级市场买回 AAVE，**买回的进 Ecosystem Reserve 不销毁**，由治理再决定用途 | ARFC「Aavenomics implementation: Part one」(2025-03) 授权约 $1M/周 × 6 个月试点 → 「AAVE Buybacks program: An update」(2025-10) 把 $50M/年永久化 → 「Budget Adjustment」(2026-03) 下调到 $30M/年 → 「Pause AAVE Buybacks」(2026-04) 自 **2026-04-19 暂停**(rsETH 事件) → 「Restart aave buy backs」(2026-05-18) → **Aavenomics 3.0 于 2026-06-27 生效，链上自动回购恢复运行** | **无直接分配**。代币持有人拿到的是 stkAAVE 质押排放（国库出资的激励，不是收入分配）。「回购+质押+销毁」三件套在 2026-10 仍是 ARFC 讨论帖，**未核到任何已通过的「按比例分给 stkAAVE 持有人」提案** | **收入进国库**（回购是国库内的资产转换） |
| lido | 收入（质押者提走约 10% 后的余额）进 **Lido DAO 国库**（以 stETH 计价）；路线是**回购 LDO**，不是分给 stETH 持有人 | ① NEST 自动回购（LIP-36）**2026-08-14 上线**，参数：年化收入基准 ~$40M、日上限 $5 万、年上限 $10M；② 「Activating LDO Staking Module」提议永久启用 fee switch、把 DAO 收入 20% 导向 LDO Staking Pool —— **投票结果核不到**；③ 一次性 $20M LDO 回购 2026-04-13 Snapshot 通过 | **无**。① 传统 fee switch（分给 stETH/wstETH 持有人）**未生效**；② NEST 虽已上线，但计数器为负（未达 $40M 基准）**从未触发购买**，实质闲置；③ LDO 质押拿的是排放不是收入分成 | **收入进国库**（NEST 机制生效但未触发 ⇒ 实际分配 = 0） |
| polygon-labs | 网络费按 PIP-65 在 validator/staker 间拆；**PIP-85 把 post-commission priority fee 池的 50% 改向 POL 质押者**，以 **Ethereum 上的定期 merkle claimer** 发放（非自动到账） | PIP-85（2026-03-25 提出）**已通过**，但**机制处于 inactive**（POLTRACK 2026-10 明写未建模），首笔靠论坛帖 merkle 补发；PIP-92（2026-10-01 激活，窗口至 2026-12-01）把这 27,334,955.85 POL 作为提升，总质押收益提到 **7.7% 年化**，**其中 10% 归 proposer（Polygon Foundation）**，到期回落 ~3% 通胀基准 | **有，但形式是质押收益而非分红**，且金额与持续性都不确定；长期看仍主要靠**通胀出块**而非真实收入 | **部分给持有人部分进国库**（真实网络费部分流向质押者，但机制 inactive） |
| arbitrum | Sequencer/PGA 收入进 **Arbitrum DAO Treasury**；PGA/Fast Feed 按 **97% 国库 / 3% Developer Guild** 自动分账（RewardDistributor 合约路由）；AEP 链（如 Robinhood Chain）须把协议净收入 10%（8% 国库 / 2% Guild）回流 | 「Transition to PGA」+「Fast Feed」合并为一次 Constitutional 链上投票，**2026-09-23 通过、2026-09-24 生效** —— 但分账是**给国库不是给持有人**。真正触及「分给 ARB 持有人」的是 ARB 质押提案族：2024-08 的温度检查以约 98.8% For 通过（奖励是 DAO 铸的**排放**不是收入）；**2026-04 新质押提案（含「把网络收入分给代币持有人」表述）状态核不到** | **无收入分配**。质押者拿到的是 DAO 铸造的排放型奖励（~7.22% APY）。网络本身有收入（2025 DAO 收入 ~$23.49M；2026 H1 $6.19M；sequencer 12 个月收入 $123M、L1 结算后净利 ~$40M），但按现行规则进的是 Treasury 与 Guild | **收入进国库**（持有人只拿排放） |
| optimism | OP Stack 链 sequencer 收入按 Standard Rollup Charter 交回 Optimism Collective：`max(2.5% sequencer 收入, 15% 链上利润)`。2025 H1：OP Chains sequencer 收入合计 **$48.4M**，Collective 收到 **$8.3M** | 「Proposal to Align the OP Token with Superchain Success」(gov.optimism.io/t/…/10527，2026-01-07 提出 / 01-22 投票) **2026-01-28~29 以约 84.4% 支持通过** —— **已通过且已生效**：12 个月试点，把**净 Superchain sequencer 收入的 50% 用于按月回购 OP**，自 **2026-02 起执行** | **有，但形式是回购不是分红**（持有人不收现金，卖压被抵消，OP 回流金库）。累计 **>940 万枚 OP**（二手口径，未在 optimism.io 核到逐月台账原值） | **收入给了持有人（回购形式）** —— 6 家里唯一 |
| starkware | STRK 自 v0.14.0（2025-09-01）起是 Starknet 唯一手续费代币，但手续费扣除 sequencer 费用与 L1 数据成本后**留在协议侧**；收益捕获主要靠 STRK 质押**排放**与 StarkWare 商业收入 | **SNIP 18（Staking on Starknet）2024-09-13 通过**，奖励结构内含 burn / fee share 条款 —— 但**至今未启动**：Blockworks 的 Starknet Token Transparency Filing（2026-10-12）明确写「未描述任何 burn，且未找到这两项机制中的任何一项启动」 | **无收入分配**。STRK 质押者拿的是新铸 STRK 排放（~7.22% APY），不是手续费净收入分成 | **收入进国库**（准确说：协议手续费未形成对持有人的可分配收入流） |

### 2.1 对 S-711 的 keeps 分类是不是口径错 —— 是，有四个层面的错

1. **DeFiLlama 的 `holders` 字段 = Holders Revenue**，官方定义是「协议收入中返还给代币持有人的那一部分」，机制上涵盖**回购销毁 / 手续费销毁 / 对质押者的直接分配**，但官方同时说它「不一定等于持有人拿到的现金」（销毁与回购是非现金分配）。
   出处：<https://defillama.com/holders-revenue> · <https://defillama.com/data-definitions>
2. **口径错位（最要紧）**：`revenue_30d` / `holders_30d` 取自 `protocol_revenue_daily`，按 coingecko id **对所有 slug 求和**。Tether / Circle / Paxos 名下**没有任何 slug 被登记 holders-revenue 维度** ⇒ 必然 0。**这个 0 的含义是「DeFiLlama 没为它登记这个维度」，不是「我们核实过它不分配」。**
3. **三态不可区分**：「仅讨论」（Lido fee switch）、「已通过未生效」（Starknet SNIP 18 的 burn/fee share）、「已生效在执行」（Optimism OP 回购）在 `holders_share` 里**全是 0**。Lido NEST 更极端：机制已上线、参数明确（$10M/年上限），但因收入未达 $40M 基准而计数器为负、**从未触发购买** —— 治理上「生效」，经济上「分配 = 0」。只看 holders 会把「机制坏了」误读成「不分」。
4. **口径本身不稳**：gross vs net、是否扣 L1 数据成本、sequencer 收入归属，各家定义不同 —— Arbitrum 12 个月 sequencer 收入 $123M、L1 结算后净利 ~$40M、DAO 确认收入 ~$23.49M，三个数差一个量级。

**结论**：`holders_share` 只能当**待核线索**，不能当判据。对每家发行方「对持有人 0」必须由**发行人一手材料**独立佐证（本卡三家稳定币发行方均已如此核验，见 §3）。登记表 note 里的「持有人 0」应改写为「DeFiLlama 口径 holders 0（未登记该维度）；发行人一手材料核实：无持有人分配机制」。

---

## 3. ③ 三家稳定币发行方的收入分配

| id | 对持有人 | 对股东 | 工具清单 | 建议 |
|---|---|---|---|---|
| **circle**（Circle Internet Group, Inc.，特拉华 CIK 0001876042，2025-06-05 NYSE: CRCL） | **无**。Circle 不向 USDC 持有人支付任何储备收益；10-K 里储备「for the benefit of USDC holders」指的是**储备金所有权/求偿权**，不是收益分配 | **收入分成机制是「Circle ↔ Coinbase」，不是付给持有人**。档位（2023-08-21 原结构，**2026-08 续约至 2029、条款不变**）：Coinbase 拿存放在 Coinbase 平台上的 USDC **100%** 储备利息；平台外部分 Coinbase 拿 **50%**，按流通量阶梯 **$200 亿→40% / $550 亿→50% / $600 亿→60%**。**当前档位**：2026-09-30 USDC 流通 $733 亿 ⇒ **60% 档**。<br>**口径纠错**：卡里提示的「50%→100%」与公开档位不符，实际是 **40/50/60%**。<br>Q2 2026（截至 2026-06-30）：总收入及储备收益 **$7.013 亿**（+7% YoY），其中储备收益 $6.68 亿；分销成本 $4.07 亿；收入减分销成本 **$2.89 亿**（+15%，margin 41%）；**持续经营净利润 $4820 万**；Adjusted EBITDA $1.43 亿。<br>**分红：从未派息** —— CFO 2026-08 续约时明确排除季度股息，资本优先投增长。<br>**回购：核不到**任何已公告的 CRCL 回购授权。<br>（Q3 2026 业绩于 2026-11-04 当日 08:00 ET 发布，本报告用 Q2 数字。） | 现有 CRCL:equity + USDC:stablecoin 正确，**加 `EURC:stablecoin`**。**USYC 不是 Circle 的**（HashKey 发行） | 改（加 EURC + note） |
| **tether**（Tether Holdings S.A. 离岸 / Tether Foundation 瑞士发币主体，两者分立） | **无**。USDT / USD₮ 不付任何持有人收益；官方从未发布面向持有人的分配机制。**卡的前提需修正**：2021 年那次「按持仓分配储备收益」**核不到** —— 2021-05 发的是**储备明细披露报告**，2021-11 在 Tron 上**销毁 10 亿 USDT**，都不是分红。Tether 实际做过的「分红」发给**高管/股东**（2024 年内部人分红超 $5.5 亿，来源是 excess reserves），与持有人无关 | 储备收益**全部归股东侧**；**无任何公开的回购或股息公告**；盈余留作资本缓冲。<br>Q3 2026 鉴证（截至 2026-09-30，BDO）：净经营利润约 **$15 亿**、前九个月约 $45 亿；储备总额 **$1915 亿**；excess reserves 约 **$79.5 亿**（Q2 2026 为 $41 亿，近乎翻倍）；Q1 2026 净利 $10.4 亿、缓冲 $82.3 亿。<br>**无 10-K、无 S-1** —— EDGAR 全类型检索，Tether 只作为他方文件里的股东出现（Bitdeer SC 13D 称 Tether International 为 Tether Holdings 全资子公司）；ICIJ 明确指出 Tether「不公开正式披露主要股东」。 | 加 **`USAT:stablecoin`**（2025-09-12 宣布，2026-01-27 经 Anchorage Digital Bank 上线）与 **`GEL:stablecoin`**（与格鲁吉亚政府合发）。**`TBILL` 不是 Tether 的**（OpenEden 的代币化国债，BNY 托管）。XAUT 是真的（2026-01 破 $40 亿）。**无股票** —— CEO Ardoino 公开否定 IPO | 改（加 USAT + GEL + note） |
| **paxos**（私有公司） | **无已生效的原生分配机制**。PYUSD / USDG / USDP 均不向持有人支付储备收益。Paxos 有两套「rewards」但**都不是持有人收益**：① Global Dollar Network 的 **Partner Rewards Engine** 付给**分销伙伴**（Kraken、OKX、Robinhood 等）；② 某些分销渠道/交易所上平台方出资的促销返利（非 Paxos 合约义务）。个别第三方平台上 PYUSD 的 ~4% 口径是**平台活动**，不是 Paxos 发行的债券 | **核不到公开披露** —— 私有公司，无 10-K/10-Q/S-1。2022 年曾提交**保密 S-1 后撤回**（EDGAR 无记录），此后无公开注册声明；截至 2026-03 仍私有，股票只在二级私募市场流通（Forge Global / UpMarket 明确写 does not trade publicly）。<br>**卡的前提需修正**：**「2025-08 宣布在 Nasdaq 计划 IPO」核不到** —— 2025-08 的实际事件是 **申请 OCC 国民信托银行牌照**（2025-08-06 向 SEC 申请登记为清算机构）；2026-05-28 SEC 授予临时豁免令，PSSC 成为首家获批提供清算结算服务的区块链原生机构。<br>收入（二手）：储备收益 + 发行费 + 交易/分销费 + 基础设施业务；2024 年约 **$1 亿**（因 BUSD 停发下滑），2026-03 发行资产突破 **$80 亿**。**Paxos Blockchain 质押收入未核到具体数字。** | 加 **`USDP:stablecoin`**（Pax Dollar，后继于停铸的 PAX Stablecoin）与 **`PAXG:token`**（1 token = 1 金衡盎司）。USDG 发行方是 **Paxos Digital Singapore**。**无股票** | 改（加 USDP + PAXG + note） |

---

## 4. 登记表的内部不一致（本卡核验中顺带发现的，不在卡的三问里）

1. **`instruments` 与 `entity_by_symbol()` 的映射互相打架**。`entity_by_symbol()` 的规则是「稳定币归实际发行方（PYUSD → paxos）」，但 `paypal` 行的 instruments 里**也列着 `PYUSD:stablecoin`**，`circle` 行列 `USDC`、`paxos` 行列 `PYUSD`+`USDG`。同一工具在两行出现，而映射只认一行 ⇒ **登记表自己说的和它映射出来的不一致**。
2. **`hyperliquid` 行的 `USDH:stablecoin` 是无主资产**。USDH 的发行方是 Native Markets，2026-05 品牌转到 Coinbase —— **这两个主体都不在登记表里**。而 `entity_by_symbol()` 会把 USDH 唯一地映射给 hyperliquid，于是**库里给 USDH 挂了一个错的发行人**。
3. **`cls` 词表**：代码注释写的 cls 取值是 `token | equity | stablecoin | venue`。若采纳 AVAT，它必须是 **`equity`**（不是 batch-1 核验稿里写的 `stock`），否则词表越界。
4. **`STRK` 撞名**：Strategy 的 Nasdaq 优先股 Series A 代码就是 **STRK**，与 Starknet 的 STRK 代币同名。实测 `issuer_fundamentals_quarterly` 现有 9 个 symbol（COIN, CRCL, FIGR, GEMI, GLXY, HOOD, MSTR, PYPL, XYZ），**不含 STRK**，所以目前没串；一旦该表扩到优先股或有人用 ticker 直连，就会把 Strategy 的股数摊薄写进 `starkware` 那一行。

---

## 5. 核不到清单（逐条，含试过什么）

| id | 核不到的具体项 | 试过 |
|---|---|---|
| near-foundation | NEAR Foundation 具体持币地址与 veNEAR 锁仓量 | nearblocks.io / houseofstake.org 链上数据未取得（不影响建议方向） |
| hyperliquid | USDH 权威单一时点供应量（CoinGecko ~21M vs CoinMarketCap ~6.26M，两家口径冲突） | CoinGecko / CoinMarketCap / DeFiLlama stablecoins 页面 |
| arbitrum | 2026-04「把网络收入分给代币持有人」的质押提案，最终链上通过与执行记录 | forum.arbitrum.foundation 全部提案页 + arbitrum.proposals.app |
| optimism | 累计回购 OP 的**逐月台账原值**（>940 万枚是二手口径） | optimism.io/blog/op-token-buybacks 官方页无逐月原值 |
| lido | 「Activating LDO Staking Module」的**投票结果**（线程页 vote checkpoint 读不到） | research.lido.fi/t/proposal-activating-ldo-staking-module/11600 |
| pendle | 合约方的确切法律实体注册名（Terms of Use 仅称 "the Company"） | docs.pendle.finance/pendle-v2/TermsOfUse、ACRA / 开曼公司检索路径 |
| chainlink-labs | Chainlink Labs 是否自营场所 | 只见 Coinbase 合作（tokenized stocks 带入 DeFi），未见自营场所证据 |
| injective | Injective Foundation 是否直接自营做市（MiCA 白皮书称其角色「limited to seeking admission of INJ to trading」） | injective.com/INJ_MiCA_Whitepaper.pdf |
| circle | ① CRCL 是否有已公告的**回购授权** ② Q3 2026（2026-11-04 当日发布）数字 ③ 「Threshold」条款里 USDC 私钥独家权触发的具体阈值金额（EX-10.1 按公式定义，数字未公开） | EDGAR 全类型检索 / Circle IR 页 / 10-Q Part II Item 5 |
| bullish | 20-F 封面登记人确切措辞（登记人名 "Bullish"；"Bullish Group" 是文件里的集合定义术语，"Bullish Exchange Inc." 未作为登记人名出现） | EDGAR 检索结果 + IR 页（未直接调阅 20-F 原文） |
| gemini | 是否曾用名 "Gemini Global Markets"（公开记录显示法定名自 2025-02 起即为 Gemini Space Station, Inc.） | EDGAR 8-K 序列 + 投资者关系页 |
| paxos | ① IPO 公告（核不到，实际事件是 OCC 牌照申请）② 收入与质押收益的具体数字（私有公司） | EDGAR 全类型检索 + Forge Global / UpMarket / 二手报道 |
| tether | 「2021-08 按持仓分配储备收益」（核不到；2021-05 是披露报告、2021-11 是销毁） | tether.io/news 全量 + 鉴证报告 |

---

## 6. 探索性发现（超出本卡三问，需另立预注册并在新数据上过零信号对照）

> 以下每条都**不是**本卡 acceptance 的交付项，是核验过程中撞见的。它们**未经**预注册、未经零信号对照，**不得**直接当结论用。

1. **OP 的 DeFiLlama 收入口径与一手材料差约 57 倍**。库内 `protocol_revenue_daily` 里 optimism 的两行合计 **$72,479 / 30 日**（年化 ~$85 万），而 §2 核到 Optimism Collective 2025 H1 收到 **$8.3M**（年化约 $1.66 亿）、OP Chains sequencer 收入 H1 $48.4M，其 50% 自 2026-02 起按月回购 OP。**同一个协议、同一年的收入，两个口径差两个数量级。** 若 S-711 的 keeps 分类拿 `holders_share=0` 当「有收入不分」的判据，OP 这一家会同时被**收入口径**和**分配口径**两处误导 —— 而 OP 恰是 6 家里唯一已生效回购的一家。
2. **`holders_share` 的记账形式偏好与「分配形式」强相关**。实测 `protocol_revenue_daily` 里 uniswap 的 `holders_30d` **等于** `revenue_30d`（8,038,790），`holders_share = 1.0` —— 与核到的「费用开关 100% 回购销毁 UNI」完全吻合。**DeFiLlama 对「回购销毁」是记账的**；那 6 家的 0 就更可能是「机制没启动」或「记的是另一种形式」，而不是「DeFiLlama 不记回购」。这条会直接改变 §2.1 第 3 点的读法。
3. **登记表的 kind 改动会连带改变 S-711 的分类结果**。本卡建议改 kind 的 6 家里，chainlink（→foundation）、ondo（→foundation）、celestia（→company）、pendle（→company）这 4 家的判定**直接依据持币结构**，而 S-711 的 keeps 分类正是按 kind 分流 ⇒ **kind 一改，分类结果就变**。这说明「口径错」不只在 holders_share 一处，kind 本身也是口径的一半。
4. **Tether 在库内根本没有收入行**。`treatment_daily` 面板里 USDT / USDC / PYUSD / USDG **一行都没有**（25 个 symbol 中它们不在内），唯一相关的行是 `tether-gold` 的 **$401,967 / 30 日**（金价收益被 DeFiLlama 当成 protocol revenue）。而登记表 note 写的「Tether 收入 $5.2 亿 / 30 日（DeFiLlama）」**在库内找不到对应行** —— 该口径要么来自 DeFiLlama 站点的另一个字段，要么就是记错了。
5. **一个 symbol 一对多发行人已经在库里发生**。`paypal` 行同时持 `PYPL` 与 `PYUSD`，`entity_by_symbol()` 却把 PYUSD 判给 paxos；`hyperliquid` 行的 USDH 更是挂了个不存在的发行人。**登记表的 instruments 语义（"主体拥有该工具" vs "该工具与主体相关"）当前是混着的** —— 这不是某一家的事实错误，是表结构层面的歧义，需要 @seth 拍一个口径。

---

## 7. 交付物

- 报告：本文件 `docs/research/T-230_issuer_registry_check.md`
- 前向预期：`docs/research/scenarios/lane-b-T-230.json`
- 只读探针：`docs/research/_t230_probe.py`（只 GET；跑 8 次；未写库、未改代码）
