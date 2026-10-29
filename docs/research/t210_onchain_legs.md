# T-210 — 灵活组合 T25 的链上腿执行路径对比（只读调查）

**范围**：代币化黄金 / 代币化 SPY / 现金（稳定币、代币化国债）三条腿，在 **$500 / $5,000 / $50,000** 三档订单下的执行路径对比。
**性质**：只读调查。**未碰任何私钥、未下任何单、未注册任何账户、未写任何表。**
**数据**：公开网页正文（45 页，`docs/research/t210_cites.json`）+ 公开交易所/链上深度接口（`t210_depth2.json`）+ Supabase 只读表 `ohlcv_daily`（publishable key）。
**取数时刻**：滑点/盘口 = **2026-10-29 09:26:48–09:28:40 UTC**；跟踪误差 = **2026-10-29 09:29:17 UTC**；引用页正文 = **2026-10-29 08:47 UTC**（第二批 09:40 UTC 补抓）。
**合规**：本文只描述执行路径与成本，不含任何投资建议；信号措辞限于 STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT。

---

## 0. 口径偏差（先说清楚，因为它改了卡上的一个字）

卡上写的跟踪误差口径是「用 Supabase `world50_onchain_forms` 的价格快照对 `ohlcv_daily` eodhd 的 XAUUSD / SPY 同日收盘算」。**这条不可执行**，两个原因都实测过：

1. **该表对 publishable key 无读权限。** `GET /rest/v1/world50_onchain_forms` → `42501 permission denied for table world50_onchain_forms`。原因见 `scripts/supabase_t098_world50.sql:37` —— `revoke all on public.world50_onchain_forms from anon, authenticated;`，只授 service_role。同类的 `tokenization_tilt_daily`（PostgREST 提示的真实价格表名）也是 `42501`。`tokenized_market_data` 这个表名在库里不存在（404）。
2. **那张表里没有价格。** `world50_onchain_forms` 是**形式清单元数据**（`as_of, token_id, key, symbol, name, category, issuer, match_rule`），价格另在 `tokenized_market_data` / `tokenization_tilt_daily`。

**本轮实际口径（替代，并已做敏感性）**：

- 代币价格 = 公开交易所/链上日线收盘：PAXG / XAUT / USDC = Binance 现货日 K 线收盘；USDY = Bybit 现货日 K 线收盘；SPYX (xStocks) 与 SPY (Ondo) = GeckoTerminal 池日线 OHLCV（Solana / Ethereum）。
- 基准 = `ohlcv_daily` 的 eodhd XAUUSD（1000 行，2023-11-08→2026-10-28）与 SPY（546 行，2024-08-26→2026-10-28），查询带 `order=trade_date.desc`。
- **对齐口径**：代币与基准取同一段日历窗口 `[days[i-1] → days[i]]`。代币 UTC 日线收盘 = 00:00 UTC；基准在美国收市（约 21:00 UTC）结算 ⇒ 同窗口内仍约有 3 小时错位。**已按要求把 offset ±1 / ±2 全跑了一遍**（见 §1.3）：只有 offset 0 的相关系数成立，其余档全部掉到 ~0。因此 TE 一律按 offset 0 报，其余档原样列出，不挑数字。
- 脚本：`docs/research/t210_tracking.py`；结果：`docs/research/t210_tracking.json`。

**要 @seth 确认**：若必须用 `world50_onchain_forms` 口径，需要一条 service_role 的只读通道（或一张 publishable 可读的代币价格表）；否则本报告的 TE 口径以公开交易所日线为准。

---

## 1. 对比表（每条腿一个推荐 + 一个备选）

| 腿 | **推荐** | **备选** | 一句话理由 |
|---|---|---|---|
| **黄金** | **XAUT（Tether Gold）** | PAXG（Paxos） | XAUT 贴得更紧（TE_ann **4.53%** vs PAXG **6.86%**，corr 0.9855 vs 0.9731），$50k 进场滑点更低（0.92 vs 1.15 bps），且 **PAXG 的赎回门槛 430 枚（≈$1.73M）把我们量级完全排除在赎回之外**。PAXG 胜在样本长（392 天 vs 211 天）与 OCC 特别批准的纯度。 |
| **代币化 SPY** | **SPYX（xStocks, Solana）** | SPY（Ondo Stocks, Solana） | 同一底层、同一时期，SPYX 的 TE_ann **7.52%** vs Ondo **19.15%**，corr 0.88 vs **0.527**，drift +1.02%/yr vs **−11.67%/yr**。差距不在合规，在**二级深度**：Ondo 的 SPY 在 Ethereum 侧最深池只有 $10,326（$5k 名义额 = 池深的 48%），SPYX 在 Solana 侧 $2,113,641。 |
| **现金** | **USDC（基础）+ USDY（收益腿）** | OUSG（仅在拿得到 Qualified-Access 准入时） | USDC 滑点恒定 0.05 bps、日波动 2.2 bps，是干净的结算/底仓资产。USDY carry **+3.489%/yr**，但 accrue 抖动 0.965%/yr、Bybit $500 进场滑点 3.42 bps ⇒ 只适合「不动的那部分现金」。**OUSG 不推荐**：需 Qualified-Access Funds 准入 + 即时申赎最低 $5,000，且 ETH 侧 USDC 池深度为 **$0.000002**（实质买不到）。 |

**共同的、也是最重要的一条**：在我们这个量级（$500–$50k），**三条腿的退出路径全是二级市场卖出，不是赎回**。PAXG 赎回要 430 枚；OUSG 即时申赎要 $5,000 起；xStocks 赎回走 Backed 要额外费用；Ondo 赎回要过发行方 KYC 且发行方保留拒赎权。T25 的腿要按「长期持有多头 + 二级流动性」设计，不能假设可随时赎回回稳定币。

---

## 2. 明细

### 2.1 黄金腿

#### 2.1.1 XAUT（Tether Gold / XAU₮）— **推荐**

| 项 | 内容 |
|---|---|
| 链 | Ethereum（主网 ERC-20） |
| 合约地址 | `0x68749665ff8d2d112fa859aa293f07a622782f38`（CoinGecko `tether-gold` 平台字段，取数 2026-10-29 08:28 UTC） |
| 发行方 / 托管 | Tether（[tether.to/en/gold](https://tether.to/en/gold/)）；与 USD₮ / MXN₮ 同属 Tether 的多资产代币体系 |
| 二级市场能否直接买 | **能**，CEX 现货为主：Binance `XAUTUSDT`、OKX `XAUT-USDT`、Bybit `XAUTUSDT`、Kraken `XAUTUSD`；Coinbase `XAUT-USD` 本轮 404 |
| 香港居民 / 非美国人 KYC | 走 CEX 自身 KYC（香港居民在 Binance / Kraken / OKX 的准入状态**本轮未逐一核实** —— 见 §3 风险 7）；发行人层面 Tether 未对香港设专门条款，但代币条款与冻结/制裁名单绑定（[USDT 条款](https://tether.to/legal/)） |
| 进场滑点（2026-10-29 09:26:49–09:26:58 UTC） | Binance `XAUTUSDT`：spread **0.0248 bps**，进场 **0.012 / 0.06 / 0.92 bps**（$500 / $5k / $50k），来回 **0.025 / 0.07 / 1.62 bps**。Bybit `XAUTUSDT`：0.012 / 0.21 / 2.63，往来 0.03 / 0.72 / 5.45。OKX `XAUT-USDT`：0.65 / 0.85 / 2.06，往来 0.77 / 0.97 / 3.11。Kraken `XAUTUSD`：0.87 / 3.34 / 6.51，往来 1.74 / 4.21 / 8.25。**用 USDC 计价**：Binance `XAUTUSDC` 0.63 / 1.78 / **9.03**，来回 1.21 / 3.00 / 21.22 |
| 来回费用 | 上表「来回」为**盘口走完的价格冲击**（不含交易所手续费）。交易所费另计：Kraken Spot Tier 1（$0–5M 30 日量）**taker 0.40%**（实测抓取 2026-10-29 09:4x UTC，[费率表](https://www.kraken.com/features/fee-schedule)）；Binance / OKX / Coinbase 费率页见 §5 链接，本轮未重抓数字。**费用量级（10–40 bps）大于滑点量级（$50k 也只有 0.9–2.6 bps）⇒ 费用主导** |
| 跟踪误差 vs XAUUSD | **211 天**（2026-03-27 → 2026-10-28，offset 0）：corr **0.9855**，TE_ann **4.527%**（日 23.70 bps），beta 0.9207，drift **−0.537%/yr**，代币年化波动 29.4% vs 基准 29.7% |
| 赎回 / 冻结 / 黑名单 | 赎回走 Tether 侧账户与合格投资者流程（[Tether Gold 页](https://tether.to/en/gold/)）；冻结与制裁名单适用 Tether 全局条款 —— **Tether 有历史冻结记录，这是链上腿里最需要盯的一项** |

#### 2.1.2 PAXG（Paxos Gold）— **备选**

| 项 | 内容 |
|---|---|
| 链 | Ethereum |
| 合约地址 | `0x45804880de22913dafe09f4980848ece6ecbaf78` |
| 发行方 / 托管 | Paxos Trust 发行，**经 OCC 特别批准**（[PAXG 条款 4.5](https://www.paxos.com/terms-and-conditions/pax-gold-terms-conditions)）；每枚对应 1 金衡盎司 LGD 标准金条，由专业保管人托管；可在 Paxos 平台交易、托管、提取 |
| 二级市场能否直接买 | **能**：Binance `PAXGUSDT`、Kraken `PAXGUSD`、OKX `PAXG-USDT`、Coinbase `PAXG-USD`；Uniswap V3 (Ethereum) |
| 香港居民 / 非美国人 KYC | 发行方要求 **仅 verified Customers** 可向 Paxos 购买或赎回（条款 4.11），但**二级市场转让不要求**（条款 4.6）。故 KYC 落在 CEX 侧，非美国人有路 |
| 进场滑点（09:26:48 UTC） | Binance `PAXGUSDT`：spread **0.0248 bps**，进场 **0.012 / 0.125 / 1.15 bps**，来回 **0.025 / 0.144 / 2.48 bps**。Kraken `PAXGUSD`：0.43 / 0.84 / 4.62，往来 0.87 / 1.64 / 8.89。OKX `PAXG-USDT`：0.50 / 0.65 / 2.79。Coinbase `PAXG-USD`：1.51 / 1.90 / 6.37。**用 USDC 计价**：Binance `PAXGUSDC` 0.88 / 2.22 / **32.61**，来回 1.76 / 4.46 / **45.35** |
| 来回费用 | 同上：盘口冲击 0.03–2.48 bps（Binance）+ 交易所 taker（Kraken Tier1 0.40% 实测；Binance/OKX/Coinbase 见链接） |
| 跟踪误差 vs XAUUSD | **392 天**（2025-09-26 → 2026-10-27，offset 0）：corr **0.9731**，TE_ann **6.86%**（日 35.91 bps），beta 0.9624，drift **+0.15%/yr**，代币年化波动 29.39% vs 基准 29.72% |
| 赎回 / 冻结 / 黑名单 | **赎回最低 430 PAXG + 费用**（条款：按 LGD 金条），≈ **$1.73M**（430 × $4,022）⇒ **我们的量级根本进不了赎回通道**；条款允许电汇提取实物金到客户披露账户；Paxos 可拒绝对 verified Customer 发行/兑换/赎回；仅 verified Customers 可交易 |

#### 2.1.3 GLDx（Ondo Gold，Solana）— 观察，不推荐本轮

Solana 侧池：GLDx/USDC reserve **$864,628**（vol24 $454,464）、XAUt0/GLDx $440,514（vol24 $41,129）；$50k 名义额占池 **0.156%**。
Ethereum 侧：最深池只有 **$10,326**（$5k = 池深 48%，$50k = 484%）⇒ **ETH 侧不可执行**。
跟踪误差：**无序列**（库内无价格源，未取到可信日线）⇒ 不能报数。
结论：链上深度尚可，但**跟踪误差无法量化**，不满足 T25 的决策要求，列为观察。

---

### 2.2 代币化 SPY 腿

#### 2.2.1 SPYX（xStocks，Solana）— **推荐**

| 项 | 内容 |
|---|---|
| 链 | Solana（另有 Ethereum 等链部署，报告口径以 Solana 池为准） |
| 合约地址 | `XsoCS1TfEyfFhpvj8EtZ528L3CaKBDBRqRapnBbDF2W`（GeckoTerminal token pools，2026-10-29 09:28:40 UTC） |
| 发行方 / 托管 | **Backed Assets (JE) Limited**，泽西岛 SPV，泽西金融服务业委员会（JFSC）注册，持 COBO 与 CGPO 同意书；每个 xStock 是**全额抵押的 tracker certificate**（[法律概览](https://docs.xstocks.fi/docs/product-legal-overview)）。EU/EEA 分销适用**列支敦士登 FMA 批准的基准招股书**，可 passport |
| 二级市场能否直接买 | **能**：Solana DEX（GeckoTerminal 池）+ **Kraken 上直接买卖 xStocks**（[Kraken xStocks 法律页](https://www.kraken.com/legal/xstocks)） |
| 香港居民 / 非美国人 KYC | xStocks **明确不向美国及 U.S. persons 提供**（[xstocks.com/products](https://xstocks.com/products)），另有 geo restrictions ⇒ **非美国人可用**。KYC 落在发行方（Backed，开曼/Jersey 流程）+ 交易场所两层 |
| 进场滑点（09:28:40 UTC） | DEX 无真盘口，用**占池比**做深度代理（池 `SPYx/USDC`，reserve **$2,113,640.83**，vol24 $841,744.93）：$500 = 池的 **0.0237%**，$5k = **0.2366%**，$50k = **2.3656%**。次池 `STONK/SPYx` reserve $1,429,265、`SPYx/SOL` reserve $589,559 |
| 来回费用 | DEX 走池子手续费 + L2 gas（Solana 单笔 < $0.01 量级，本轮未逐笔实测）；Kraken 上有独立的 xStocks 费率档（[Kraken 费率页](https://www.kraken.com/features/fee-schedule) 提到 "Kraken uses a maker-taker fee schedule for xStocks"） |
| 跟踪误差 vs SPY | **124 天**（2026-04-30 → 2026-10-27，offset 0，池日线）：corr **0.88**，TE_ann **7.52%**（日 39.36 bps），beta 0.9555，drift **+1.019%/yr** |
| 赎回 / 冻结 / 黑名单 | 赎回三通道：Atomic RFQ（xChange）/ In-Kind Flow（xPort）/ Market Flow（[xStocks 文档](https://docs.xstocks.fi/llms.txt)）；Kraken 页载明可向 Backed 赎回（**另收费用**）或直接在平台卖出 |

#### 2.2.2 SPY（Ondo Global Markets，Solana/Ethereum）— **备选**

| 项 | 内容 |
|---|---|
| 链 | Ethereum / BNB Chain / Solana / HyperEVM（[可转让性页](https://docs.ondo.finance/ondo-stocks/transferability.md) 明确「可在美国以外跨这些链转移」） |
| 发行方 / 托管 | **Ondo Global Markets (BVI) Limited**；抵押品 Security Agent = **Ankura Trust Company, LLC**（[二级市场限制页](https://docs.ondo.finance/ondo-stocks/secondary-market-restrictions.md)） |
| 二级市场能否直接买 | **能，但深度分层严重**：Ethereum 侧最深池仅 **$10,325.92**（$500 = 4.84% 池深，$5k = **48.4%**，$50k = **484%** ⇒ 不可执行）；Solana 侧（`SPY_ondo_dex`，池 `0x5638bbde...`）有 182 天日线可用，深度未在本轮同口径列出 |
| 香港居民 / 非美国人 KYC | **禁美国人**：[资格页](https://docs.ondo.finance/ondo-stocks/eligibility.md) 排除「美国及其任何州、属地」「从美国境内下单的人」「U.S. persons 或为其账户行事的人」。**香港居民落在「需按辖区具备 Professional Investor / Qualified Investor 身份」这一栏**（该页按辖区列了 Brazil 等的具体门槛，**香港的具体门槛本轮未在该页定位到** —— 见 §3 风险 7） |
| 进场滑点 | DEX 侧以占池比代理，见上（Ethereum 侧 $5k 即占池 48%）⇒ 这个量级下**不存在可用的「滑点」概念，是执行不了** |
| 来回费用 | Ondo 自有费用 0（[费用页](https://docs.ondo.finance/ondo-stocks/fees-and-taxes.md)：报价时产生费用；二级市场由第三方收取） |
| 跟踪误差 vs SPY | **123 天**（2026-04-28 → 2026-10-27，offset 0）：corr **0.527**，TE_ann **19.154%**（日 100.26 bps），beta 0.8404，drift **−11.667%/yr** |
| 赎回 / 冻结 / 黑名单 | 赎回须满足发行方 KYC，**发行方保留单方拒赎权**；赎回用 **USDon**（Ondo 自家稳定币），转 USDC 需 swapper 有对应流动性，否则可先赎 USDon 等 swapper 补充；二级市场取得者即视为接受全套免责与风险警示（[二级市场限制页](https://docs.ondo.finance/ondo-stocks/secondary-market-restrictions.md)） |

#### 2.2.3 Dinari — **不是我们能直接用的腿**

[docs.dinari.com](https://docs.dinari.com/) 是 **B2B 基础设施**：Ondo 式券商能力以 API 形式提供给机构（自持 brokerage、KYC 可自备 Persona/Onfido 也可白标托管）。也就是说 Dinari 是「造腿的人」，不是「腿」。若要用 Dinari 的 SPY，等于自己接一层券商 + KYC + 托管，**不在本轮只读调查的执行路径内**，列出仅为避免误选。

---

### 2.3 现金腿

#### 2.3.1 USDC（Circle）— **推荐做基础/结算资产**

| 项 | 内容 |
|---|---|
| 链 | 多链（Ethereum / Solana / Arbitrum / Base …） |
| 发行方 / 托管 | Circle；储备透明度见 [Circle USDC 条款](https://www.circle.com/legal/usdc-terms) 与储备披露 |
| 二级市场能否直接买 | **能，且极深**：Binance `USDCUSDT` spread 0.0999 bps，进场 **0.05 / 0.05 / 0.05 bps**（三档相同，因为深度远超名义额），来回 0.10 bps；Kraken `USDCUSD` 0.50；Bybit `USDCUSDT` 0.50 |
| 香港居民 / 非美国人 KYC | Circle 条款：**Restricted Person（受制裁者）不得持有 USDC**；Circle Mint 账户、USDC 服务与支持**仅向位于 supported jurisdictions 的个人与机构提供**；**Blocked Addresses 条款** —— Circle 认定违规可封禁地址 |
| 进场滑点 | 见上（0.05 bps 恒定） |
| 来回费用 | 盘口 0.10 bps + 交易所 taker（Kraken Tier1 0.40% 实测；Binance 见链接） |
| 相对现金的持有收益 | **carry_ann 0.147%/yr**，accrual 抖动 0.425%/yr，日波动 **2.224 bps**，399 天总回报 0.160% |
| 赎回 / 冻结 / 黑名单 | Circle 可随时冻结/封禁地址（Blocked Addresses）；赎回走 Circle 账户（机构 KYC 通道），链上转账可做但**不等于赎回** |

#### 2.3.2 USDY（Ondo General-Access）— **推荐做收益腿（不动的那部分）**

| 项 | 内容 |
|---|---|
| 链 | Ethereum `0x96f6ef951840721adbf46ac996b59e0235cb985c`；Solana `A1KLoBrKBde8Ty9qtNQUtq3C2ortoC3u7twggz7sEto6`；Arbitrum `0x35e050d3c0ec2d29d269a8ecea763a183bdf9a9d` |
| 发行方 / 托管 | Ondo Global Markets (BVI) Limited（[USDY 资格页](https://docs.ondo.finance/general-access-products/usdy/eligibility.md)） |
| 二级市场能否直接买 | **能**：Bybit `USDYUSDT` 现货；Solana DEX 池 `USDY/USDC` reserve **$2,916,273**（$50k = 池的 1.71%）。**Ethereum 侧最深池仅 $20,609**（$5k = 池深 24.3%，$50k = 242.6%）⇒ ETH 侧不可执行；**Arbitrum 侧池只有 $41.70** ⇒ 不可执行 |
| 香港居民 / 非美国人 KYC | 与 Ondo Stocks 同框架：**禁美国人**（美国及其州属地、美国境内下单者、U.S. persons）；其余按辖区门槛。**USDY 属 General-Access 产品，准入门槛低于 OUSG 的 Qualified-Access Funds**（[OUSG 资格页](https://docs.ondo.finance/qualified-access-products/ousg/eligibility-and-onboarding.md) 明确写：不符合 QAF 门槛者可能仍符合 Ondo Stocks 资格） |
| 进场滑点（09:26:57–09:28 UTC） | Bybit `USDYUSDT`：spread 1.7379 bps，进场 **3.42 / 3.80 / 5.76 bps**，来回 **4.28 / 4.67 / 6.63 bps**（本报告里最贵的 CEX 腿之一）；DEX（Solana）以占池比代理：$500 = 0.0171%、$5k = 0.1715%、$50k = 1.7145% |
| 来回费用 | 盘口 4.28–6.63 bps（Bybit）+ 交易所 taker。**注意这个成本会吃 carry**：年化 carry 3.489%，来回 6.63 bps ⇒ 调仓 26 次就把一年的 carry 全部吃掉 |
| 相对现金的持有收益 | **carry_ann 3.489%/yr**，accrual 抖动 **0.965%/yr**，日波动 **5.052 bps**，399 天总回报 3.882% |
| 赎回 / 冻结 / 黑名单 | 赎回需过 Ondo 的 KYC 流程并受其合规裁量；发行人保留拒赎权（同 Ondo Stocks 框架） |

#### 2.3.3 OUSG（Ondo Short-Term US Treasuries）— **不推荐（除非拿到准入）**

| 项 | 内容 |
|---|---|
| 链 | Ethereum `0x1b19c19393e2d034d8ff31ff34c81252fcbbee92` |
| 发行方 / 托管 | Ondo（Qualified-Access Funds 系列） |
| 二级市场能否直接买 | **实质不能**：Ethereum 侧唯一 `OUSG/USDC` 池 reserve **$0.000002**（深度代理显示 $50k 名义额 = 池的 2.5×10¹² %）；Solana 侧 **无池**。⇒ OUSG 的现实路径是**发行方申购**，不是二级市场 |
| 香港居民 / 非美国人 KYC | **仅能投 Qualified-Access Funds 的准入用户**（[资格页](https://docs.ondo.finance/qualified-access-products/ousg/eligibility-and-onboarding.md)：OUSG 没有自己的 KYC，必须先 onboard 到 QAF）⇒ 这是**发行人层面的机构准入**，不是开个交易所账号 |
| 进场滑点 | 二级市场滑点不适用（无流动性）。申购侧有门槛：**即时申购/即时赎回最低 $5,000**；即时申购有 **$50M 全球限额**（24h 滚动）与 **$25M 个人限额**（[即时限额页](https://docs.ondo.finance/qualified-access-products/ousg/instant-limits.md)） |
| 来回费用 | **管理费 0.15%，已豁免至 2027-01-01**；基金费用上限 0.15%/yr（[费用页](https://docs.ondo.finance/qualified-access-products/ousg/fees-and-taxes.md)）。**豁免到期后每年 0.15% 相对当前 3.489% carry 是 4% 的相对磨损** |
| 跟踪误差 | **无序列**（库内无可用价格序列）⇒ 相对 T-bill 基准的 TE **无法报数** |
| 赎回 / 冻结 / 黑名单 | 赎回需满足 QAF 准入 + $5,000 门槛 + 24h 限额约束；Ondo 可拒绝 |

> 补充：[HashKey Earn 已上线 OUSG 通道](https://support.hashkey.com/hc/en-gb/articles/60100192600985-HashKey-Earn-Channel-Launches-Ondo-Short-Term-U-S-Treasuries-Treasuries-Fund-OUSG) —— 若走香港持牌平台，这可能是比自建 DEX 更现实的入口，但**本轮未取到该页正文（抓取时正文长度不足），门槛与费用未核实**。

---

## 3. 风险

1. **赎回通道在量级外。** PAXG 需 430 枚（≈$1.73M）；OUSG 即时申赎需 $5,000 起且需 QAF 准入；xStocks 赎回走 Backed 另收费；Ondo 赎回需过发行方 KYC 且发行方保留拒赎权。⇒ **$500–$50k 的腿，退出=二级卖出**。T25 若把腿当可赎回资产设计，会在第一次需要流动性时才发现通道不存在。
2. **同名假币泛滥。** dexscreener 上带 "PAXG" 名的池子横跨 $0.00012 到 $5,007 的价格区间、合约地址各不相同 —— 绝大多数是克隆盘。**执行必须走合约地址白名单**（本报告 §2 各表已列出官方地址）。买错地址在链上不可追回。
3. **跨链深度差 5–7 个数量级。** USDY：Solana 池 $2.92M vs Arbitrum 池 $41.70；Ondo SPY：Solana 有序列 vs Ethereum 池 $10.3K。⇒ **链的选择不是偏好问题，是可执行性问题**；同名资产在不同链上根本不是一个可交易性资产。
4. **跟踪误差本身很大。** 黄金腿 TE_ann 6.86%（PAXG）/ 4.53%（XAUT），相对黄金 29.4% 年化波动 ≈ 23% / 15%；股票腿 SPYX 7.52%。T25 若月度调仓，TE 直接吃掉 alpha —— **TE 不是事后统计，是这条腿的成本项**。
5. **费用主导而非滑点主导。** $50k 在 Binance 上滑点只有 0.9–1.2 bps，但 Kraken Tier1 现货 taker 是 0.40%（实测自抓 2026-10-29 09:4x UTC）—— **差 30 倍以上**。选错执行场所比选错代币更贵。
6. **发行人单方裁量。** Ondo（SPY/USDY/OUSG）保留单方拒赎权与「酌情判定是否违规」的权利；PAXG 侧 Paxos 亦可拒绝对 verified Customer 兑换/赎回。⇒ 这类腿的「可赎回」是有条件的，不是权利。
7. **香港口径的三个缺口（本轮未核实，不是「没问题」）**：
   - **SFC 持牌虚拟资产交易平台名单本轮未取到**。已探测并留证（`docs/research/t210_sfc_probe.py` → `docs/research/t210_sfc.json`）：名单页 `apps.sfc.hk/edistributionWeb/gateway/EN/va-sfc-list/` 是 JS 应用，正文只抓到 14 字符；探测 4 个候选 API 路径全 404；`main.41ff7da8.chunk.js` 里公开的 API 端点只有 circular / consultation / news / intermediaries-licensing，**不含 VA 持牌名单端点**。⇒ **我们在香港能合法用哪些交易所/平台做这几条腿，本报告没有回答** —— 这一项要么由人查 SFC 名单，要么走 Jazz 拍板。
   - Ondo 资格页按辖区列门槛，**香港对应的 Professional/Qualified Investor 具体标准本轮未定位到**。
   - 香港居民在 Binance / Kraken / OKX 的准入状态未逐一核实（Kraken 费率与 xStocks 页有 jurisdiction 免责语，但那是免责声明不是准入结论）。
   ⇒ **在补上这三点之前，本报告的「香港可执行」结论只对 CEX 层成立，对发行人层（Ondo 申购、Backed 赎回）不成立。**
8. **USDC 作为底仓的隐藏成本。** Circle 的 Blocked Addresses 与冻结权是真实存在的对手方风险；USDC 相对现金的 carry 只有 0.147%/yr，但它是唯一在四家所都稳定 0.05 bps 滑点的资产 —— 这个「便宜」买的是可用性。

---

## 4. 还看到了什么（探索性）

> 以下每条都是**本轮数据里的意外发现**，不是已验证的结论。都需要**另立预注册、在新数据上过零信号对照**才能进决策。

1. **同一条「代币化 SPY」腿，两家差距在二级流动性而非合规。** Ondo SPY TE_ann 19.15% / drift −11.67%/yr vs xStocks SPYX 7.52% / +1.019%/yr，corr 0.527 vs 0.88。若某天 Ondo 的二级深度追上（ETH 池从 $10K 涨到百万级），这条腿可能反转 —— 值得预注册一个「按二级深度分层」的假设来测。
2. **TE 的对齐口径极度敏感。** offset ±1 / ±2 时相关系数全部掉到 ~0（PAXG 从 0.9731 → −0.02 ~ −0.08；SPYX 0.88 → ~0），TE 从 6.86% 跳到 42%+。这意味着：**任何用日收盘算 TE 的方法都必须先声明对齐口径**，否则数字是伪相关。这也提示「代币 24/7 / 基准工作日」的错位本身可能是一个可交易的时序源。
3. **用 USDC 直接买同一个代币，$50k 贵 28 倍。** Binance `PAXGUSDC` 进场 32.61 bps vs `PAXGUSDT` 1.15 bps；`XAUTUSDC` 9.03 vs `XAUTUSDT` 0.92。直觉上「用我已有的 USDC 买」省了一次换汇，实际是把点差让渡给 USDC 簿子。
4. **USDY 的 carry 会被调仓吃掉。** carry 3.489%/yr，往回成交成本 4.28–6.63 bps ⇒ 26 次调仓吃光一年 carry。现金腿的持有期决定它值不值，而不是 carry 本身。
5. **同一代币跨链的「跟踪质量」可能差一个数量级。** 同一 USDY，Solana 有 399 天日线与 $2.92M 池，Arbitrum 有 $41.7 池 —— 但跟踪误差是**价格序列的性质**，不是池深度的性质。若某条腿只在某条链上有可交易的深度，那条链就是那条腿的「唯一现实」。这条值得单独预注册。
6. **偏离卡上口径的副作用。** 因为 `world50_onchain_forms` 不可读，我们用交易所日线代替链上价格快照 —— 交易所日线包含交易所自身的价差/流动性结构。若要给出「纯链上」的 TE，需要另建通道（见 §0）。

---

## 5. 附：本报告引用的来源

**发行方 / 产品文档**
- PAXG 条款：https://www.paxos.com/terms-and-conditions/pax-gold-terms-conditions
- Tether Gold：https://tether.to/en/gold/
- Ondo Stocks 资格 / 申赎 / 费用 / 二级市场限制 / 可转让性：https://docs.ondo.finance/ondo-stocks/{eligibility,investing-and-redeeming,fees-and-taxes,secondary-market-restrictions,transferability}.md
- Ondo OUSG 资格 / 费用 / 即时限额：https://docs.ondo.finance/qualified-access-products/ousg/{eligibility-and-onboarding,fees-and-taxes,instant-limits}.md
- Ondo USDY 资格：https://docs.ondo.finance/general-access-products/usdy/eligibility.md
- xStocks 法律概览 / FAQ / 产品页：https://docs.xstocks.fi/docs/product-legal-overview · https://docs.xstocks.fi/docs/faq · https://xstocks.com/products
- Circle USDC 条款：https://www.circle.com/legal/usdc-terms
- Dinari：https://docs.dinari.com/
- HashKey Earn OUSG 通道：https://support.hashkey.com/hc/en-gb/articles/60100192600985-HashKey-Earn-Channel-Launches-Ondo-Short-Term-U-S-Treasuries-Treasuries-Fund-OUSG

**交易所费率与法律**
- Kraken 费率：https://www.kraken.com/features/fee-schedule
- Kraken xStocks：https://www.kraken.com/legal/xstocks
- Binance 费率：https://www.binance.com/en/fee/schedule
- OKX 费率：https://www.okx.com/help/okx-trade-fees
- Coinbase 费率：https://help.coinbase.com/en/coinbase/trading-and-funding/fees
- SFC 持牌 VA 平台（本轮 404，未取得）：https://www.sfc.hk/en/Regulatory-functions/Intermediaries/Virtual-asset-trading-platforms

**数据与脚本（本仓库 `docs/research/`）**
- `t210_cites.json` — 45 页引用正文与命中行（抓取 2026-10-29 08:47 / 09:40 UTC）
- `t210_depth2.json` — CEX 盘口 + DEX 池深度、$500/$5k/$50k 三档滑点（取数 2026-10-29 09:26–09:28 UTC）
- `t210_tracking.py` / `t210_tracking.json` — 跟踪误差脚本与结果（取数 2026-10-29 09:29 UTC）
- `t210_recon.json` / `t210_recon2.json` — 合约地址与场所/池侦察
- `t210_sfc_probe.py` / `t210_sfc.json` — SFC 持牌 VA 平台名单端点探测记录（未取到名单，见 §3 风险 7）
