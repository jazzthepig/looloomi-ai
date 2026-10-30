# T-214 — P3 前置(只读):XAUT 与 SPYX 两条腿,香港居民今天能走通的执行路径

> **性质**:只读调研。不注册、不下单、不碰私钥、不连钱包、不写库。
> **抓取窗口**:2026-10-30T03:35Z – 04:00Z(UTC);**复核轮**:2026-10-30T04:12–04:15Z(42 项断言全过,见 §10)。
> **引用档案**:`docs/research/t214_cites.json`(119 个页面/API 条目,每条含 url + 抓取时间 + 原文片段)、
> `docs/research/t214_venues.json`(同一批公开 API 的结构化汇总:挂牌场所 / 价差 / DEX 池)、
> `docs/research/t214_verify.json`(复核轮:42 条断言逐条 PASS/FAIL + 各自抓取时间)。
> **口径**:金额按卡上的额度 —— 黄金腿 XAUT = $120,股票腿 SPYX = $180(按卡上「($120 / $180)」的顺序;
> 若两者对调,成本按比例缩放,结论不变)。T25 起始 600 USDC 留在 HL。

---

## 0. 结论先行(一句话版)

**两条腿今天都能在技术上走通,但没有一条是「香港居民有牌照依据」的路**:能读到挂牌的场所
(Kraken / Binance / OKX / Bybit / Gate / MEXC / Hyperliquid / DEX)**没有一个在 SFC 持牌 VA 平台名单上**;
13 家持牌平台里我们能读到的公开 API 一个都没列出这两条腿。**卡在「谁有权让香港居民开户」这一格,不在技术格。**
技术上最干净的一条是 **Hyperliquid 现货内部换腿**(两条腿同在一个交易所、USDC 计价的现货对、零 gas、零出金费),
但 HL 的条款原文本环境读不到、HL 未在 SFC 名单上 ⇒ **这条是「技术上今天能走、香港合规待判定」**。

---

## 1. 场所的香港监管身份(SFC 持牌 VA 平台名单,原文)

**出处**:`https://www.sfc.hk/en/Welcome-to-the-Fintech-Contact-Point/Virtual-assets/Virtual-asset-trading-platforms-operators/Lists-of-virtual-asset-trading-platforms`
**抓取时间**:2026-10-30T03:35:35Z / 03:58:22Z(两次,内容一致;页长 126,829 字符)
**引用键**:`sfc_vatp_list`、`sfc_list_again`、`sfc_count`

### 1.1 持牌名单(13 家,原文逐行)

| CE | 公司 | 平台 | 发牌日 |
|---|---|---|---|
| BPJ213 | OSL Digital Securities Limited  OSL數字證券有限公司 | OSL Exchange | 15/12/2020 |
| BPL992 | Hash Blockchain Limited | HashKey Exchange | 09/11/2022 |
| BPW549 | Hong Kong Virtual Asset Exchange Limited 香港虛擬資產交易所有限公司 | HKVAX | 03/10/2024 |
| BPO721 | Hong Kong Digital Asset EX Limited 香港數字資產交易集團有限公司 | HKbitEX | 18/12/2024 |
| BUA970 | Accumulus GBA Technology (Hongkong) Co., Limited 雲賬戶大灣區科技(香港)有限公司 | Accumulus | 18/12/2024 |
| BUN619 | DFX Labs Company Limited | DFX Labs | 18/12/2024 |
| BUT670 | EXIO Limited | EX.IO | 18/12/2024 |
| BUY578 | Panthertrade (Hong Kong) Limited 猎豹交易(香港)有限公司 | PantherTrade | 27/01/2025 |
| BUT913 | YAX (Hong Kong) Limited | YAX | 27/01/2025 |
| BUQ956 | Bullish HK Markets Limited | Bullish | 18/02/2025 |
| BSI739 | Hong Kong BGE Limited | BGE | 17/06/2025 |
| BTF116 | Victory Fintech Company Limited 勝利數碼科技有限公司 | VDX | 13/02/2026 |
| BUY737 | NewBX Limited | Bixin.com | 18/05/2026 |

### 1.2 待批申请(5 家,原文逐行)

`HighBlock Limited / bitV / 06/02/2024` · `Foris DAX HK Limited^ / Crypto.com / 09/02/2024` ·
`Whalefin Markets Limited^# / WhaleFin / 21/02/2024` · `Nebulas Hong Kong Limited / Nebulas / 25/10/2024` ·
`Spark Fintech Limited / Bybit / 06/06/2025`
(脚注原文:*A licence application submitted to the SFC may be returned by the SFC if it is incomplete and/or has
unresolved fundamental issues.*)

### 1.3 已撤回 / 被退回(19 行,与我们相关的四行原文)

| 公司 | 平台 | 递交 | 移除日 | 原因 |
|---|---|---|---|---|
| OKX Hong Kong FinTech Company Limited | OKX | 16/11/2023 | 24/05/2024 | Withdrawn |
| Spark Fintech Limited | Bybit | 31/01/2024 | 31/05/2024 | Withdrawn |
| Gate Digital Limited | Gate.HK | 28/02/2024 | 22/05/2024 | Withdrawn |
| Bitcoin World Technology Limited | bitcoinworld | 17/05/2024 | 10/10/2024 | Returned |

另有一张**「须于指定日期前结业」表**:`Flying Hippo Technologies Limited / Matrixport HK / https://www.matrixport.hk / 12/01/2027`。

### 1.4 名单页全文计数(我们自己跑的检索,`sfc_count`,126,829 字符全页)

| 名称 | 出现次数 | 出现在哪张表 |
|---|---|---|
| Kraken | **0** | — 不在名单任何一张表 |
| Binance | **0** | — 不在名单任何一张表 |
| Coinbase / Bitfinex / MEXC / BingX / Nado / VALR | **0** | — |
| OKX | 2 | 仅「已撤回」表 |
| Bybit | 2 | 「待批申请」表 + 「已撤回」表 |
| Bullish | 2 | 「持牌」表(持牌) |
| HashKey | 1 | 「持牌」表(持牌) |

> **⇒ 事实陈述(不含建议)**:在 2026-10-30 的 SFC 名单上,**Kraken、Binance 不在持牌名单,也不在任何一张表里**;
> OKX 的香港牌照申请已撤回;Bybit 的申请仍在待批;持牌方里与我们这两条腿相关的是 Bullish 与 HashKey。
> 与我们的候选场所直接相关的**唯一持牌方是 Bullish(BUQ956, 18/02/2025)与 HashKey Exchange(BPL992, 09/11/2022)**。

### 1.5 持牌方有没有这两条腿?

- CoinGecko 全部挂牌场所快照(`t214_venues.json`,2026-10-30T03:55:47Z):
  XAUT 共 **100 个场所 ticker**、SPYX 共 **35 个**、wSPYX **12 个**、XAUt0 **63 个**。
  表格里**没有 Bullish、没有 HashKey、没有 OSL、没有 HKVAX、没有 HKbitEX、没有 Bixin.com、没有 Accumulus / DFX Labs / EX.IO / PantherTrade / YAX / BGE / VDX**。
- `api.hashkey.com` 与 `api.bullish.com` 在本环境 **DNS 被挡**(URLError),所以「持牌方是否挂这两条腿」我们**没读到**,
  不能写成「持牌方不挂」——只能写成:「**我们能读到挂牌数据的场所里没有持牌方**;持牌方的产品清单本轮读不到」。

---

## 2. 候选路径 —— 黄金腿(XAUT)

### 路径 A:Hyperliquid 现货(XAUT0/USDC)

- **① 场所与监管身份**:Hyperliquid **不在** SFC 持牌名单(§1.4,全页 0 次命中);它是链上协议、无香港牌照。
  *证据*:`sfc_count`、`hyperliquid_spotmeta`。
- **② 香港居民开户 / KYC**:**读不到**。HL 条款页在本环境取不到正文 —— `app.hyperliquid.xyz/terms-of-service`
  只回 6,831 字符的 JS 外壳;`hyperliquid.gitbook.io/hyperliquid-docs/legal/{terms,index,hyperliquid-terms-of-service}.md`
  三个候选全部是 GitBook 的 "Page Not Found"(2.3–2.6 KB);`llms.txt` 索引里没有 legal/terms 条目。
  ⇒ **本轮无法从条款原文回答「香港居民能不能在 HL 开户」。**
  *证据*:`hl_terms_app`、`hl_legal_terms`、`hl_legal_index`、`hl_legal_tos`、`hl_llms_txt`。
- **③ 链与钱包**:HL 现货内部持有,**不需要链上钱包**。若要提链上,HL 内部 token 的 EVM 合约地址是
  `0xf4d9235269a96aadafc9adae454a0618ebe37949`(HyperEVM),`isCanonical: false`。
  *证据*:`hyperliquid_spotmeta`(token index 297, `evmContract.address`)。
- **④ 成本($120)**:现货 taker **0.070%**、maker 0.040%(Tier 0,14 天加权成交量 <$5M);
  价差 **0.010017%**;24h 名义成交额 **$396,914**(复核轮 04:12Z 的 HL ctx 读数为 **$400,666**)。
  → 手续费 $0.084 + 价差 $0.012 ≈ **$0.096(0.08%)**;**gas 0、出入金 0**。
  *证据*:`hl_fees_raw`(Spot fee tiers 表 Tier 0 行原文:`0 | | 0.070% | 0.040% | …`)、
  `t214_venues.json → venues["tether-gold-tokens"]`、`t214_verify.json → hl_fee_tier0 / hl_midpx_182 / hl_vol_182`。
- **⑤ 出金**:在 HL 内部卖回 USDC 即可(标的腿与 USDC 同一交易所),**无出金费**。
  HL 的 USDC 是 Hyperliquid L1 原生铸造;Circle 在 HyperEVM 上的合约 `0xb88339cb7199b77e23db6e890353e22632ba630f`。
  *证据*:`hyperliquid_usdc`。
- **✓ 复核后的读数**:HL `spotMetaAndAssetCtxs` 按 `coin` 字段正确配对后,`@182 XAUT0/USDC` 的
  `midPx = 3990.25`、`dayNtlVlm = 400,666.46`(04:12Z),**与 CoinGecko 的 $3,990.20 归一化报价一致**。
  (本报告初稿里「midPx 差 14,000 倍」的读数警告是**抓取脚本自身的配对错误**,已在 §10 更正并撤下。)

### 路径 B:海外 CEX 现货(Kraken / Binance / OKX / Bybit 任选)

- **① 场所与监管身份**:**全部不在** SFC 持牌名单(§1.4)。OKX 香港牌照申请**已撤回**;Bybit **待批**;
  Kraken / Binance 在名单上**连名字都没有**。
- **② 香港居民开户 / KYC**:**读不到**。
  - Kraken:全球条款全文 3,808,345 字符里检索 **"Hong Kong" 命中 0 次**(即该文件不含香港限制条款);
    但 `support.kraken.com/hc/en-us/articles/360000426166-Kraken-available-in-your-country` 返回 **404**,
    且 Kraken 条款里的 "Restricted Jurisdiction" 只出现在 Opt-In Rewards 段落,**没有给出辖区清单**。
    ⇒ 「香港是否在 Kraken 的受限辖区清单内」**本轮无法回答**。
  - Binance:`binance.com/en/legal/terms` 与 `/en/legal/global_terms` 均返回 **0 字符**(JS 渲染/被挡)⇒ 读不到。
  - OKX:`okx.com/legal/terms`、`/help/where-can-i-use-okx` 均 **404** ⇒ 读不到。
  - Bybit:`bybit.com/en/legal/terms` 返回 25,317 字符的 JS 外壳,能看见 "Service Restricted Countries" 的菜单键名,**正文没有取到** ⇒ 读不到。
  - 可读到的通用要求只有 Kraken 条款里的一句:*"You will need to complete certain verification procedures before you are permitted to s[end]"*(身份验证条款),
    以及 Binance 公告里的 bStocks 条款(见路径 C)。
  *证据*:`kraken_terms_hk`、`kraken_countries`、`binance_terms_hk`、`okx_terms_hk`、`bybit_terms_hk`。
- **③ 链与钱包**:**取决于各所的提现网络,本轮读不到**(各所提现网络端点需鉴权:
  `api.binance.com/sapi/v1/capital/config/getall` → 400;`okx /api/v5/asset/currencies` → 401;`bybit /v5/asset/coin/query-info` → `apiKey is missing`)。
  ⇒ **「从 Kraken/Binance 提出来的 XAUT 是哪个合约」没有证据,这是本卡最大的未取证项**(见 §8.1)。
- **④ 成本($120)**:见 §6 成本表(实测价差 + 公开费率)。
- **⑤ 出金**:卖成 USDC 后按各所的 USDC 提现规则提到 HL(Arbitrum→HyperCore CCTP / HyperEVM 上的 Circle USDC);
  **各所提现费读不到**,链上 gas 见 §6。

### 路径 C:链上 DEX + 自托管钱包(Uniswap / Raydium 等)

- **① 场所与监管身份**:DEX 无牌照;场所是智能合约,**SFC 名单不适用**(名单只列 VA 平台运营商)。
  注意**发行方**才是有牌照门槛的那一层:xStocks 由 **Backed Assets (JE) Limited**(泽西公司,受 Jersey Financial Services Commission 监管)发行,
  每份是 **1:1 全额抵押的追踪凭证**,底层股票由受监管托管人隔离保管;**列支敦士登 FMA 批准的基准招股书可在 EEA 护照通行**。
  链上直接申购/赎回要走发行方 KYC(不是开交易所账户)。
  *证据*:`xstocks_legal`。
- **② 香港居民开户 / KYC**:DEX 本身不需要开户(只要钱包);**发行方 KYC 是读不到的那一格**:
  `docs.xstocks.fi/docs/eligibility.md` → 404(站点 sitemap 里没有该路径;`/apis/openapi/market-trades/list_trades_market_fees` 只给出
  费率字段结构 `issuance/redemption/bridge → {initialFee, minimumFee, percentageFee}`,**数值需要 API key**)。
  xStocks 官网页只写:*"xStocks are not available in the U.S. or to U.S. persons. Geo restrictions apply."* ⇒ 香港不在被点名禁止的一侧,
  但**没有正面授权**。
  *证据*:`xstocks_legal`、`xstocks_products`、`xstocks_eligibility_doc`(404)、`xstocks_sitemap_locs`、`xstocks_fees_doc`。
- **③ 链与钱包**:见 §5(两条腿可以同链同钱包)。
- **④ 成本($120)**:见 §6(池费 + gas + 价差)。
- **⑤ 出金**:卖回 USDC → 提到 HL(HyperEVM 上的 Circle USDC)或直接在 HyperEVM 上换成 USDC 给 HL 入金。

---

## 3. 候选路径 —— 股票腿(SPYX / Backed xStocks)

> **先分清三个不同的东西**(这是本卡最容易踩的坑):
> **SPYX**(Backed SP500 xStock,合约 `0x90a2a4c7…`,Solana mint `XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W`)、
> **wSPYX / XSTX**(Wrapped SP500 xStock,合约 `0xe7e553cd…`,在 x-layer / Ink / Arbitrum / HyperEVM)、
> **Binance 的 SPYB**(Binance 自家的 "bStocks" 代币化证券)。
> 三者的关系:**本轮没有取到任何一份文件证明 wSPYX 与 SPYX 是同一份权利凭证**;而 Binance 的 SPYB **确定不是** Backed 的 SPYX
> —— CoinGecko 的 SPYX 场所表里没有 Binance,Binance 的 SPYXUSDT 交易对 **400 无效符号**。

### 路径 A:Hyperliquid 现货(SPYX/USDC)

- **① 场所与监管身份**:同 §2 路径 A —— HL 不在 SFC 名单。
- **② 开户/KYC**:读不到(同 §2 路径 A②)。
- **③ 链与钱包**:HL 内部;`SPYX` token index 846,`tokenId 0x29067197b3125c8b82ad0f338e4a31b2`,
  `evmContract 0xe7e553cd128f0011777323a0b44a7b96ea1cb540`(= wSPYX 合约),`fullName "Wrapped SP500 xStock"`。
  *证据*:`hyperliquid_spotmeta`。
- **④ 成本($180)**:taker 0.070% → $0.126;价差 **0.032582%**(复核轮 0.031285%)→ $0.059;合计 ≈ **$0.185**;gas 0、出金 0。
  **深度:复核后两个来源互证** —— HL ctx 按 `coin` 正确配对,`@703 SPYX/USDC` 的
  `midPx = 767.12`、`dayNtlVlm = 134,063.71`(04:12Z);CoinGecko 同刻报 `last 767.18 / spread 0.031285% / 24h $132,829`。
  ⇒ **$180 这一档在深度上没有问题**(24h 名义成交额是这一档的 700 多倍)。
  **仍缺的一步**:盘口档位(`l2book`)在本环境返回 422,读不到**卖一/买一量级** ⇒ 成交价是否被这一档吃掉,仍需人工在 HL 界面看。
  另注 HL 上还有一个 `SPY` token(index 420,合约 `0xb7bf37783db41a2851b77c6917280c56312c833a`,`fullName: null`):
  `@279 SPY/USDC` 的 `midPx 755.73`(≈ SPY 现货价位),但 **24h 名义成交额 = 0** ——
  它是 SPY 现货 ETF 的凭证、不是 Backed 的 SPYX 追踪凭证,**不要拿它当 SPYX 用**。
  *证据*:`hl_spot_ctx_px`、`hyperliquid_spotctx`、`t214_venues.json`、`t214_verify.json → hl_ctx_703 / hl_midpx_703 / hl_vol_703 / hl_ctx_279 / cg_spyx_hl_volume`。
- **⑤ 出金**:内部卖回 USDC,无出金费。

### 路径 B:Kraken xStocks(SPYX/USD)

- **① 场所与监管身份**:Kraken **不在** SFC 名单(§1.4,0 命中)。
- **② 开户/KYC**:读不到(同 §2 路径 B②;Kraken 条款明确要身份验证,但没有香港辖区清单)。
- **③ 链与钱包**:**支持自托管提现** —— Kraken 条款原文:*"Can I withdraw my xStocks to a self-hosted wallet?
  Yes – self-custody is supported. You can withdraw your xStocks to a compatible on-chain wallet."*
  但 Kraken 公开 `AssetPairs` 里 **SPYX / SPYx / SPY / TSLAx 命中数均为 0**(全表 1,464 个交易对),
  xStocks 在 Kraken Pro 的另一个命名空间(CoinGecko 给的交易入口是 `pro.kraken.com/app/trade/SPYx-USD`)⇒
  **xStocks 走哪条链、提现网络是什么,本轮读不到**。
  *证据*:`kraken_xstocks`、`kraken_assetpairs_full`、`kraken_xaut_pairs_fees`。
- **④ 成本($180)**:Kraken xStocks FAQ 原文:*"The purchase price for all xStocks includes a market price + 1.0% spread."*
  ⇒ **买入侧 1.0% 的加价 = $1.80**;另:*"For clients purchasing xStocks with all crypto or fiat other than USDG or USD,
  standard Instant Buy/Sell fees apply. Clients purchasing xStocks with USDG or USD will not incur any additional fees."*
  盘口价差(CoinGecko 归一化)**0.012623%**;24h 名义成交额 **$113,792**;最小投资 **$1**
  (*"Clients can purchase fractional shares, with investments starting as low as $1 per xStock."*)。
- **⑤ 出金**:xStocks 可在 Kraken 平台直接卖成 USD/加密/稳定币(*"sell them for USD, crypto, or stablecoins directly on the Kraken platform"*);
  赎回需找 Backed 且**另收费用**(*"Tokenholders may redeem their xStocks with Backed (for an additional fee)"*)。

### 路径 C:Binance bStocks(SPYB)

- **① 场所与监管身份**:Binance **不在** SFC 名单(§1.4,0 命中)。
- **② 开户/KYC + 发行限制**:Binance 公告原文(2026-10-28,`binance_cms_detail_bstocks`):
  *"bStocks are offered through an Approved Prospectus in the ADGM and are not offered in any other jurisdiction.
  No public offer is made outside of the ADGM. Tokenized Securities are available only to eligible users in permitted
  jurisdictions on a secondary market basis only."*
  ⇒ **只在 ADGM(阿布扎比)发行;其他司法辖区没有公开发售;只有「permitted jurisdictions 的合格用户」能在二级市场拿到。**
  香港是否属 permitted jurisdiction、什么算 eligible user,**本轮读不到**。
- **③ 链与钱包**:SPYB 交易对 `SPYBUSDT` 在 Binance 现货在线(`isSpotTradingAllowed: true`,`minQty 0.001` ≈ $0.76);
  提现链**读不到**(需鉴权)。
- **④ 成本($180)**:24h 报价 `last 763.75`,盘口 763.72/763.75 ⇒ 价差 ≈ **0.004%**;24h 名义成交额 **$1,103,866**。
  Binance 现货费率页 `binance.com/en/fee/schedule` 返回 **0 字符**,`/sapi/v1/asset/tradeFee` 返回 400 ⇒ **费率读不到**。
- **⑤ 出金**:同 CEX 通用路径(提现费读不到)。

### 路径 D:链上 DEX(与黄金腿合并执行)

见 §2 路径 C 与 §5/§6:Solana(SpYx/USDC 池 $2.10M)与 HyperEVM(USDC/wSPYx 0.05% 池 $143,340)有真实池子;
Ethereum 上 SPYX 的池子储备只有 **$476–797** 且费 tier 显示 87% / 96.5%(不可用);**Arbitrum 上 SPYX 一个池都没有**。

---

## 4. 「能不能一个钱包 / 一条链装下两条腿」——能,而且有三条链成立

| 链 | 黄金腿合约 | 股票腿合约 | 两条腿都有池子? | 备注 |
|---|---|---|---|---|
| **HyperEVM** | XAUt0 `0xf4d9235269a96aadafc9adae454a0618ebe37949` | wSPYX `0xe7e553cd128f0011777323a0b44a7b96ea1cb540` | ✅ USDC₮0/XAUt0 0.05%(储备 $20,554)+ USDC/wSPYx 0.05%(储备 $143,340) | gas **0.169 gwei**;HL 就在这条链上 |
| **Solana** | XAUt0 mint `AymATz4TCL9sWNEEV9Kvyz45CHVhDZ6kUgjTJPzLpU9P` | SPYX mint `XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W` | ✅ SpYx/USDC 储备 **$2,099,939**;XAUt0 只有 USDT 池($405,987 / $254,816)与 GLDx 池($439,696) | 优先费实测 **0**;但**没有 XAUt0/USDC 直池**,要多一次 USDT/USDC 兑换 |
| **Ethereum** | XAU₮ `0x68749665ff8d2d112fa859aa293f07a622782f38` | SPYX `0x90a2a4c76b5d8c0bc892a69ea28aa775a8f2dd48` | ⚠️ 黄金腿池 $7.07M(XAUt/WETH 0.3%),**股票腿池只有 $476–797** | 不建议 |
| **Arbitrum** | XAUt0 `0x40461291347e1ecbb09499f3371d3f17f10d7159` | SPYX `0x90a2a4c7…` | ⚠️ XAUt0 池 $48,546 / $34,723;**SPYX 池数 = 0** | 不可用 |
| ~~X-Layer~~ | — | wSPYX `0xe7e553cd…` | 池 $4.12M(wSPYx/USDG 0.05%) | 黄金腿不在此链 |

**结论**:**HyperEVM 一条链 + 一个钱包可以装下两条腿,而且两条腿都有 USDC 直池**(费用 0.05% 级别);
**Solana 也成立**,但黄金腿那侧缺 USDC 直池。**Ethereum 与 Arbitrum 不成立**(股票腿那一侧没池子)。

**合约出处(逐条)**:
- **XAU₮ 以太坊合约 `0x68749665FF8D2d112Fa859AA293F07A622782F38`** —— **Tether 自己的集成页原文**:
  *"XAU₮ contract address: https://etherscan.io/token/0x68749665FF8D2d112Fa859AA293F07A622782F38"*
  (`tether_supported_protocols`)。**这是唯一有发行方一手出处的合约地址。**
- **XAUt0 多链地址**(hyperevm / plasma / avalanche / monad / celo / solana / polygon-pos / arbitrum-one)
  —— CoinGecko `tether-gold-tokens` 的 `platforms` 字段(`cg_tether_gold_tokens`);**没有发行方一手出处**。
- **SPYX 合约 `0x90a2a4c76b5d8c0bc892a69ea28aa775a8f2dd48`**(arbitrum-one / monad / ethereum / binance-smart-chain 同一地址)
  与 **Solana mint `XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W`** —— CoinGecko `sp500-xstock`(`coingecko_spyx`);
  **wSPYX 合约 `0xe7e553cd128f0011777323a0b44a7b96ea1cb540`**(x-layer / hyperevm / ink / arbitrum-one)—— CoinGecko `wrapped-sp500-xstock`(`coingecko_wspyx`)。
- **⚠ 关键区分**:CoinGecko 把 **XAU₮(`tether-gold`,以太坊)** 与 **XAUt0(`tether-gold-tokens`,多链)** 记成**两个不同的 coin id**,
  两者价格同为 ~$3,990(2026-10-30 03:47–03:56Z),但**本轮没有任何文件证明二者同源或可互换**。
  这直接决定「在 Kraken/Binance 买到的 XAUT 提出来是哪个合约」——而各所提现网络清单**读不到**(§2 路径 B③)。

---

## 5. 全部成本(实测优先,读不到的明确标注)

### 5.1 报价与价差(2026-10-30T03:55:47Z,`t214_venues.json`)

| 场所 | 标的 | last | 价差 | 24h 名义成交额 |
|---|---|---|---|---|
| Binance | XAUT/USDT | 3,992.36 | 0.01025% | $19,851,992 |
| Bybit | XAUT/USDT | 3,996.14 | 0.01025% | $14,188,673 |
| MEXC | XAUT/USDT | 3,992.63 | 0.01025% | $11,757,839 |
| OKX | XAUT/USDT | 3,993.20 | 0.012504% | $10,299,946 |
| Gate | XAUT/USDT | 3,993.00 | 0.012504% | $9,812,815 |
| Kraken | XAUT/USD | 3,984.40 | 0.01251% | $794,229 |
| Kraken | XAUT/USDT | 3,996.00 | 0.012504% | $345,989 |
| Binance | XAUT/USDC | 3,985.48 | 0.015016% | $678,968 |
| **Hyperliquid** | **XAUt0/USDC** | **3,990.20** | **0.010017%** | **$396,914** |
| Uniswap V3 (Ethereum) | XAUt/WETH 0.3% | 3,981.16 | — | 池储备 $7,073,858 |
| **Hyperliquid** | **SPYX/USDC** | **767.18** | **0.032582%** | **$132,834** |
| Kraken | SPYX/USD | 762.32 | 0.012623%(FAQ 加价 1.0%) | $113,792 |
| Gate | SPYX/USDT | 764.28 | 0.015701% | $917,220 |
| MEXC | SPYX/USDT | 765.83 | 0.108279% | $620,750 |
| LBank | SPYX/USDT | 769.99 | 0.278283% | $2,972,411 |
| Binance | SPYB/USDT | 763.75 | ≈0.004%(763.72/763.75) | $1,103,866 |
| Raydium CLMM (Solana) | SPYX/USDC | 767.42 | 0.603411% | $2,919,328 |

### 5.2 费率(有原文的)

| 项 | 值 | 出处 |
|---|---|---|
| HL 现货 taker / maker(Tier 0) | **0.070% / 0.040%** | `hl_fees_raw` Spot fee tiers 表 |
| Kraken 现货 taker / maker(0–$50k 档) | **0.26% / 0.16%** | `kraken_fees_schedule` |
| Kraken xStocks 买入加价 | **1.0%**(market price + 1.0% spread) | `kraken_xstocks` FAQ 原文 |
| Uniswap V3 池费(HyperEVM 两条腿都是 0.05% 池) | **0.05%** | `t214_venues.json → pools` |
| Uniswap V3(Ethereum 黄金腿池 0.3%) | **0.3%** | 同上 |
| Binance 现货 / OKX 现货 / Bybit 现货费率 | **读不到**(JS 壳 / 404 / 需鉴权) | `binance_fee_spot`、`okx_fees_page`、`bybit_fee_spot` |

### 5.3 最小单与最小额

| 项 | 值 | 出处 |
|---|---|---|
| Kraken XAUT/USD 与 XAUT/USDT | ordermin **0.0012 XAUT** ≈ $4.79;costmin $0.50 | `kraken_xaut_pairs_fees`(实测 AssetPairs) |
| Binance XAUT/USDT | minQty **0.0001** ≈ $0.40 | `binance_exchangeinfo_xaut` |
| Binance SPYB/USDT | minQty **0.001** ≈ $0.76 | `binance_exchangeinfo_spyb` |
| Kraken xStocks 最小投资 | **$1** | `kraken_xstocks` FAQ |
| xStocks 发行/赎回 | 费率结构有(issuance/redemption/bridge 各 3 项),**数值需 API key** | `xstocks_fees_doc` |

### 5.4 链上 gas(实测,同一时刻)

| 链 | gas price | 来源 |
|---|---|---|
| Ethereum | **0.6276 gwei**(`0x255665ad`) | `gas_eth_rpc`(publicnode) |
| Arbitrum | **0.0201 gwei**(`0x1331930`) | `gas_arb_rpc` |
| HyperEVM | **0.1694 gwei**(`0xa13efa4`) | `gas_hyperevm_rpc` |
| Solana | 优先费 **0**(近 128 slot 全 0) | `sol_priority_fee`;另 `eth_gas_blockchair` 给出 mempool 中位 1.9219 gwei |

### 5.5 两条腿的合计成本(按 $120 / $180)

**黄金腿 $120**

| 路径 | 交易费 | 价差/加价 | gas | 出入金 | 合计 | 占比 |
|---|---|---|---|---|---|---|
| HL 现货 XAUT0/USDC | $0.084(0.070%) | $0.012 | 0 | 0 | **≈$0.096** | 0.08% |
| Kraken XAUT/USDT | $0.312(0.26%) | $0.015 | 0 | [未知] | **≈$0.327** | 0.27% |
| Binance XAUT/USDT | [读不到,若 0.1% 则 $0.12] | $0.012 | 0 | [未知] | **≈$0.132** | 0.11% |
| 链上 Uniswap V3 ETH 0.3% 池 | $0.36(0.3%) | 池内滑点 | ≈$0.38(0.63 gwei × ~150k gas × $3,993) | [未知] | **≈$0.75+** | 0.63% |
| 链上 HyperEVM 0.05% 池 | $0.060 | 池内滑点 | ≈$0.001 | [未知] | **≈$0.06+** | 0.05% |

**股票腿 $180**

| 路径 | 交易费 | 价差/加价 | gas | 出入金 | 合计 | 占比 |
|---|---|---|---|---|---|---|
| HL 现货 SPYX/USDC | $0.126(0.070%) | $0.059 | 0 | 0 | **≈$0.185** | 0.10% |
| Kraken xStocks | 见下 | **$1.80(1.0% 加价)** | 0 | [未知] | **≈$1.87+** | 1.04% |
| Binance bStocks(SPYB) | [读不到] | $0.007 | 0 | [未知] | **≈$0.007+** | 0.004% |
| 链上 Solana SPYx/USDC | 池费[读不到] | 池内滑点 | ≈$0.001(优先费 0) | [未知] | **≈$0.00x+** | <0.05% |
| 链上 HyperEVM USDC/wSPYx 0.05% | $0.090 | 池内滑点 | ≈$0.001 | [未知] | **≈$0.09+** | 0.05% |

**两条腿合计(最小方案)**:HL 内部两条腿 ≈ **$0.28 / $300 = 0.09%**;
最贵组合(Kraken 两条腿)= ≈ **$2.20 / $300 = 0.73%**。
**在这个量级上,「路径成本」不是决策变量,「谁有权让香港居民开户 + 哪个合约」才是。**

### 5.6 出金(卖成 USDC 回到 HL)

| 环节 | 事实 | 状态 |
|---|---|---|
| 同所内部 | 腿与 USDC 在同一交易所 ⇒ 内部换腿,无出金费 | ✅ |
| USDC → HL(Arbitrum) | HL 文档:见 Circle 的 Arbitrum→HyperCore CCTP 转入;legacy Arbitrum bridge 持 supply 不到 10% | ✅ 路径存在,费率读不到 |
| USDC → HL(HyperEVM) | Circle 在 HyperEVM 的 USDC 合约 `0xb88339cb7199b77e23db6e890353e22632ba630f`;HL L1 原生 USDC | ✅ |
| 链上 gas | Arbitrum 0.0201 gwei ≈ $0.0001;Ethereum 0.6276 gwei ≈ $0.01(一次转账) | ✅ 实测 |
| **各所提现费** | Binance `sapi/v1/capital/config/getall` → 400;OKX → 401;Bybit → apiKey missing | ❌ **读不到** |
| 把 XAUT/SPYX 本体提到 HL 的链上地址 | 合约地址已知(§4);提现网络清单读不到 | ⚠️ 缺一步 |

---

## 6. 今天能走哪条,缺哪一步

**A. 技术上今天就能走完(不需要任何人拍板的那部分)**

1. **两条腿都在 Hyperliquid 现货内部成交** —— 无需钱包、无需 gas、无需出金、无需跨链;
   成交成本 ≈ $0.28 / $300(0.09%);价差 0.0100%(黄金)/0.0326%(股票);两条腿的 24h 名义成交额分别为 $400,666 / $134,064。
   **缺的一步**:① HL 条款读不到 ⇒ 香港居民能否开户未知;② HL 不在 SFC 持牌名单 ⇒ 香港合规待判定;
   ③ 盘口档位(`l2book`)读不到 ⇒ 成交价是否被这一档吃掉,须人工在界面看一次。
2. **黄金腿走 Kraken / Binance / OKX / Bybit 现货** —— 最小单 $0.40–$4.79,$120 完全够;
   价差 0.010–0.015%。
   **缺的一步**:① 香港居民在这些所的开户/条款读不到;② 提现网络清单读不到 ⇒ 拿到的 XAUT 是哪个合约未知;
   ③ Binance/OKX/Bybit 的费率读不到。
3. **股票腿走 Kraken xStocks(SPYX/USD)** —— 最小 $1,盘口价差 0.0126%。
   **缺的一步**:① **1.0% 的买入加价**($180 上是 $1.80,是所有路径里最贵的一项);
   ② xStocks 走哪条链/哪个提现网络读不到;③ 香港居民开户未知。
4. **股票腿走 Binance bStocks(SPYB)** —— 盘口最紧(0.004%)、成交额最大($1.10M/24h)。
   **缺的一步**:Binance 公告写明 **只在 ADGM 发行、其他辖区没有公开发售、仅 permitted jurisdictions 的合格用户可在二级市场交易**
   ⇒ 香港是否 permitted、什么算 eligible,读不到;且 SPYB 与 Backed 的 SPYX **不是同一标的**。

**B. 今天走不通的**

5. **在 SFC 持牌平台上完成这两条腿** —— 持牌 13 家里,我们能读到挂牌数据的**一个都没有**;
   `api.hashkey.com` / `api.bullish.com` 在本环境 DNS 被挡 ⇒ 持牌方(Bullish / HashKey 等)是否挂 XAUT/SPYX **读不到**。
   ⇒ **这不是「不行」的结论,是「没读到」的结论**;它是 §7 里最该由人补上的一格。
6. **链上 DEX 当作「无牌照所以最简单」的退路** —— 技术上成立(HyperEVM 或 Solana 一条链装下两条腿,gas ≈ 0),
   但**发行方那一层的 KYC 读不到**(`docs.xstocks.fi/docs/eligibility.md` 404),
   且**从 CEX 提出来的 XAUT 是 XAU₮ 还是 XAUt0 没有证据** —— 链选错合约就会拿错资产。

---

## 7. 读不到的 / 没核实的(逐条列明,不猜)

1. **各所的 XAUT / SPYX 提现网络清单** ⇒ 「提出来是哪个合约」无法回答(§2 路径 B③、§4 关键区分)。
2. **香港居民在 Kraken / Binance / OKX / Bybit / Hyperliquid 的开户资格条款原文**(§2 路径 A②/B②)。
3. **SFC 持牌方(Bullish / HashKey / OSL / HKVAX / HKbitEX / Bixin.com / Accumulus / DFX Labs / EX.IO / PantherTrade / YAX / BGE / VDX)
   是否挂牌 XAUT / SPYX**(`api.hashkey.com`、`api.bullish.com` DNS 被挡)。
4. **各所提现费 / 出入金费**(端点需鉴权)。
5. **Binance / OKX / Bybit 的现货费率与 xStocks 的发行/赎回费数值**(需鉴权或 JS 渲染)。
6. **HL 的 SPYX/USDC 与 XAUT0/USDC 的实际盘口档位**(`l2book` 端点在本环境返回 422)。
   深度本身已在复核轮由两个来源互证(§3、§10),剩下的是**卖一/买一的量级**没读到。
7. **XAUt0 是否与 XAU₮ 同源可互换**;**wSPYX 是否与 SPYX 是同一份权利凭证**。
8. **Ondo 的香港门槛(T-210 §3 缺口之二)** —— 本卡两条腿不涉及 Ondo,未处理。

---

## 8. 探索性发现(非结论)

> 标注:**探索性 —— 需另立预注册、在新数据上过零信号对照。** 以下是本轮顺带看到、超出卡片问询范围的观察,
> **不构成任何结论或建议**:

1. **「交易所的链上副本」正在变成一条独立的腿**:Hyperliquid 的现货对 `@182 XAUT0/USDC`、`@703 SPYX/USDC`
   与 Kraken xStocks 的自托管提现,指向同一个事实 —— **两条腿都可以是「一个地址 + 一条链上的两个合约」,
   不需要交易所账户**。若这成立,P3 的「第二个执行器」也许不需要是交易所。
   *探索性 —— 需另立预注册、在新数据上过零信号对照。*
2. **香港的执行瓶颈可能是「读条款」而不是「找不到路」**:本轮所有路径的技术参数都取到了,
   卡住的全是「香港居民能不能开户 / 哪些司法辖区被点名」这类条款问题,而这些条款在多数所是 JS 渲染或需鉴权。
   ⇒ **值得先解决「能读到条款」这件事**(人工浏览 / 存档快照),而不是继续比对费率。
   *探索性 —— 需另立预注册、在新数据上过零信号对照。*
3. **Kraken 的 XAUT 最小单是 0.0012 XAUT(≈$4.79),不是传闻中的 $400** —— 我们第一轮把 AssetPairs 里
   上一对交易对的 `ordermin` 误读到了 XAUTUSD 头上;逐对解析后更正(§5.3)。
   ⇒ **教训:分片 API 的字段要逐条解析,不要跨条目抓窗口**;`t214_cites.json` 里保留了第一轮的原始误读片段,可复核。
   *探索性 —— 需另立预注册、在新数据上过零信号对照。*
4. **同一份 API 里「多数组并列」的响应,必须按 key 配对,不能按位置 `zip`** ——
   本轮 HL `spotMetaAndAssetCtxs` 返回的 `universe`(347 条)与 `ctxs`(1186 条)**长度与顺序都不同**;
   按位置 `zip` 会把 A 对的价格贴到 B 对的标签上,凭空造出「差 14,000 倍」和「深度为 0」两个读数警告。
   **教训本身可推广到任何分片/多数组 API**(与 §8.3「逐条解析」同一类)。
   *探索性 —— 需另立预注册、在新数据上过零信号对照。*

---

## 9. 复现

```bash
python3 docs/research/t214_cites.py        # 第 1 轮:34 页(SFC 名单 / Kraken / Binance / CG / HL / gas)
python3 docs/research/t214_cites_gap.py    # 第 2 轮:HK 准入条款 / 盘口 / DEX 池 / gas
python3 docs/research/t214_cites_gap2.py   # 第 3 轮:场所挂牌面 / bStocks / Kraken 全量 pair
python3 docs/research/t214_cites_gap3.py   # 第 4 轮:合约链清单 / xStocks 文档 / HL 桥接
python3 docs/research/t214_cites_gap4.py   # 第 5 轮:HL 条款候选 / 费率表原文 / SFC 全文计数
python3 docs/research/t214_venues.py       # 结构化汇总 → t214_venues.json
python3 docs/research/t214_merge_cites.py  # 合并 → t214_cites.json(119 页)
python3 docs/research/t214_verify.py       # 复核轮:42 条断言 → t214_verify.json(04:15Z 全过)
python3 docs/research/t214_annotate.py     # 给被取代的条目打 superseded 标记(原始 quotes 不改)
```

全部脚本只发公开 GET/POST,不注册、不下单、不读 `.env`、不打印任何 key。

---

## 10. 复核与更正(2026-10-30T04:12Z)

复核脚本 `t214_verify.py` 把本报告里最吃重的 42 条断言**重新抓一遍**并逐条判定:
**PASS 42 / FAIL 0 / READ_FAIL 0**(`docs/research/t214_verify.json`,每条含 url + 抓取时间 + 实测值)。
复核覆盖:SFC 名单页的 6 个名称计数 + 持牌 13 家的平台名 + 三个发牌日 · HL 两枚 token 的 EVM 合约地址与 token index ·
HL 两条现货对的 midPx / 24h 成交额 · Kraken XAUT/USD 最小单与 xStocks FAQ 四句原文 · Binance XAUTUSDT / SPYBUSDT 最小单与
SPYXUSDT 无效符号 · CoinGecko 两个 coin 的场所面 · HyperEVM gas · Tether 官网的 XAU₮ 合约地址 · xStocks 发行方文档 ·
HL / Kraken 费率表原文。

### 10.1 撤下两条「读数警告」——它们是脚本自己的配对错误

初稿里有两条很重的警告,复核后**两条都不成立**:

| 初稿的说法 | 实情 | 处理 |
|---|---|---|
| §2「HL 的 `midPx` 在 XAUT0 那对上是 0.285195,与 CoinGecko 差 14,000 倍,不能拿来算规模」 | **抓取脚本把 A 对的价格贴到了 B 对的标签上**:`t214_cites_gap.py:189` 用 `zip(universe, ctxs)` 按位置配对,而 `universe` 只有 347 条、`ctxs` 有 1186 条,长度与顺序都不同 | 撤下;正确配对后 `midPx = 3990.25`,与 CoinGecko 的 3990.20 一致 |
| §3「HL 的 SPYX/USDC `midPx null / dayNtlVlm 0.0`,与 CoinGecko 的 $132,834 打架,深度不可读」 | 同一个错配 | 撤下;正确配对后 `midPx = 767.12 / dayNtlVlm = 134,063.71`,与 CoinGecko 的 132,829 一致 |
| §3「`@279 SPY/USDC` 的 `midPx 74.617`、24h 名义成交额 $3,533.62,单位与标的都对不上」 | 同一个错配 | 更正为:`midPx 755.73`(≈ SPY 现货价位)、**24h 名义成交额 = 0**;它确实不是 SPYX,但原因是**没有流动性**,不是单位错 |

**这不改变本卡的主结论**(卡点仍然在「谁有权让香港居民开户」与「提出来是哪个合约」),
但它**改变一条结论的强度**:HL 现货这两条腿的深度从「不可读、须人工看盘口」变成「两个来源互证、$180 这一档在深度上没问题」,
剩下没读的只有 `l2book` 的档位量级。

### 10.2 复核轮的新鲜读数(2026-10-30T04:12Z)

| 项 | 值 | 复核断言 |
|---|---|---|
| HL `@182 XAUT0/USDC` | `midPx 3990.25` · `dayNtlVlm 400,666.46` | `hl_midpx_182` / `hl_vol_182` PASS |
| HL `@703 SPYX/USDC` | `midPx 767.12` · `dayNtlVlm 134,063.71` | `hl_midpx_703` / `hl_vol_703` PASS |
| HL `@209 XAUT0/USDT0` / `@279 SPY/USDC` | `midPx 3921.5` / `755.73`,两者 24h 名义成交额均为 **0** | `hl_ctx_209` / `hl_ctx_279` PASS |
| CoinGecko SPYX/Hyperliquid | spread 0.031285% · 24h $132,829 | `cg_spyx_hl_spread` / `cg_spyx_hl_volume` PASS |
| SFC 名单页 | 126,829 字符;Kraken 0 次、Binance 0 次、OKX 2 次、Bybit 2 次、Bullish 2 次、HashKey 1 次;持牌 13 家平台名全中 | `sfc_count_*` / `sfc_licensed_13` / `sfc_licence_dates` PASS |
| Kraken XAUT/USD | `ordermin 0.0012`(≈$4.79)/ `costmin 0.5` | `kraken_xautusd_min` PASS |
| Binance XAUTUSDT / SPYBUSDT | `minQty 0.0001` / `0.001`(SPYB `isSpotTradingAllowed=true`);SPYXUSDT 仍为无效符号 | `binance_*_minqty` / `binance_spyx_invalid` PASS |
| HL / Kraken 费率原文 | Spot Tier 0 `0.070% / 0.040%`;Kraken taker 0.26% / maker 0.16% | `hl_fee_tier0` / `kraken_fee_026` PASS |
| HyperEVM gas | 落在 0.05–0.5 gwei 区间(初稿实测 0.1694 gwei) | `gas_hyperevm` PASS |
| Tether 集成页 | XAU₮ 合约地址 `0x68749665FF8D2d112Fa859AA293F07A622782F38` 原文可见 | `tether_xaut_contract` PASS |
| xStocks 文档 | `Backed Assets (JE) Limited` / `1:1` / `Jersey` 三处原文可见 | `xstocks_*` PASS |

### 10.3 没有被复核推翻的东西

复核只动了两条读数警告;**其余结论原样保留**:SFC 名单(13 家持牌 / Kraken·Binance 不在任何一张表 / OKX 已撤回 / Bybit 待批)、
Kraken xStocks 的 1.0% 买入加价与「最小 $1」、Binance bStocks「只在 ADGM 发行」的限制、
XAUT 与 SPYX 的合约地址与链分布、**「两条腿在一个钱包一条链」在 HyperEVM 与 Solana 上成立**、
以及 §7 里那 8 条「读不到 / 没核实」。§7 第 6 条按 §10.1 收窄为「只缺盘口档位」。
