# T-188 取证笔记 —— 香港可得性（逐条，含链接 + 日期）

取数日期：2026-10-24（UTC）。全部只读公开网页，未注册、未连钱包、未下单。
原文全文落在本目录 `t188_hk_text/`（每文件一个来源），此文件只存结论。

---

## 1. PAXG —— Paxos Trust Company, NA（OCC 监管的美国信托）

- 发行方与法律结构：`Paxos Trust Company, NA`（美国国民银行协会，受 OCC 监管）发行 PAXG；`Paxos Global PTE LTD` 为转售商。PAXG 是 ERC-20，1 枚 = 1 金衡盎司 London Good Delivery 分配金条（LBMA 保管、编号可识别、实物在伦敦 LBMA 保管库）。
  - 依据：`Paxos General Terms and Conditions`（Last Modified: December 12, 2025）+ `PAX Gold Terms and Conditions`
  - 链接：https://www.paxos.com/terms-and-conditions/pax-gold-terms-conditions
  - 链接：https://www.paxos.com/terms-and-conditions/general-terms-and-conditions
  - 链接：https://www.paxos.com/pax-gold
- 购买/赎回资格：**「Only verified Customers may purchase PAXG from us or convert or redeem PAXG from us」**（PAXG TC §4.11）。Paxos 可自行裁量拒绝发行或拒绝赎回（账户被暂停/终止、或认为发行或赎回违反适用法律）。
- 香港：**条款原文未见把香港列为禁止辖区**；General TC 亦未见「Restricted Jurisdictions」定义列表（已全文 grep：`Restricted Jurisdictions` / `Restricted Jurisdiction` / `Prohibited Jurisdiction` 均 0 命中）。但 General TC §5.3(n) 明写「Paxos may not be regulated as a financial institution or equivalent in your jurisdiction」——即发行方自身不承担香港监管义务。
- 美国人限制：General TC 由 `Paxos Trust Company, NA` 与用户订立，适用美国法；PAXG 获 OCC 特定批准向 Paxos Trust 客户发行（§4.5–4.6）。
- KYC：有。Verified Customer 制度 + 单独的 AML/KYC Disclosure 文件。
- 赎回时效：购买请求 5:00 p.m. EST 前提交且过合规检查 → 次一工作日交付；全部换算向下取整到 1/100 金衡盎司；Paxos 可设最低换算额（金额与时效以 help.paxos.com 用户指南为准，本轮未取到具体数字 → **查不到**）。
- 二级市场（第三方 CEX/AMM）：Paxos 条款不禁止个人在二级市场持有 ERC-20；但**直接赎回回实物金须通过 Paxos 账户（KYC）**。
- 风险：实物金由第三方保管人保管，非 Paxos 自有资产；链上拥堵；Paxos 可拒绝赎回。

## 2. XAUT —— Tether（Gold token, XAUt）

- 发行方与法律结构：Tether Gold 由 `Tether International SA` 体系发行（`gold.tether.to`）。具体发行实体与实物金保管安排本轮**只拿到 JS 渲染壳页（253 字符）**，结构细节 → **查不到**（FAQ 与白皮书页同样 JS 渲染）。
- 依据：Tether 通用条款（`https://tether.to/en/legal/`，78888 字符全文已存）
- 定义（原文要点）：「**Prohibited Person**」= 任何 U.S. Person（Tether 自行酌情同意的 Eligible Contract Participants 除外）、任何 Canadian Person、任何 Singaporean Person、委内瑞拉政府、任何 Prohibited Jurisdiction（古巴、朝鲜、伊朗、叙利亚、克里米亚、顿涅茨克、卢甘斯克、赫尔松、扎波罗热）居民或政府官员，以及任何被制裁人士。
- 香港：**香港不在 Prohibited Person / Prohibited Jurisdiction 定义内**（逐条比对定义原文，无香港字样）。
- 美国人限制：有（U.S. Person 一律为 Prohibited Person）。
- KYC / 最低申赎额 / 时效：`gold.tether.to/legal/termsofservice` 与 FAQ 均为 JS 应用，本轮取不到正文 → **查不到**。
- 风险：发行人无信用/主权信用；实物金托管与审计为发行人自述（`gold.tether.to/reports`）。

## 3. GLDX（Ondo Global Markets 代币化黄金）/ SPYX / QQQX / AAPLX —— Ondo Global Markets (BVI) Limited

- 发行方与法律结构：`Ondo Global Markets (BVI) Limited`（BVI）发行 Ondo Stocks；法律类别为**追踪凭证（tracker）**，不是直接股权，无股东投票权。
- 关键条款（`https://docs.ondo.finance/ondo-stocks/eligibility` 全文已存）：
  - **禁止辖区清单（Prohibited Persons）**：Afghanistan, Belarus, Canada, Crimea/DNR/LNR/Kherson/Zaporizhzhia, Cuba, North Korea, Iran, Libya, Myanmar, Russia, Somalia, South Sudan, Sudan, Syria, **United States**（含其任何州、属地、联邦区），并含「在美国境内下单的人 / 依 Regulation S Rule 902 定义的 U.S. persons 或为其账户利益行事的人」。**香港不在禁止清单内。**
  - **香港受限制（可持有但有门槛）**：条款「Jurisdiction-Based Restrictions」表内香港条目为：
    - 个人：「Professional Investor」under the Securities and Futures (Professional Investor) Rules (PI Rules)，门槛 HK$8 million portfolio value（个人或与联系人合计）
    - 公司/信托：「Professional Investor」（Corporate/Trust）PI Rules
    - 机构：「Professional Investor」（Institutional）under the SFO Schedule 1 Part 1
  - 另注：Ondo Global Markets (BVI) Limited 另可依其 KYC 政策与合约施加**与辖区无关**的资格条件。
  - 链接：https://docs.ondo.finance/ondo-stocks/eligibility
  - 链接（FAQ，明确「only outside the United States and only to eligible non-U.S. persons」）：https://ondo.finance/ondo-stocks
- 二级市场：条款允许代币在二级市场挂牌或取得；**在二级市场买入的人自行承担「未被禁止取得」的陈述义务**（`Secondary Market Restrictions` 页）。赎回条件是满足发行方 CDD/KYC，发行方可因合规顾虑拒绝赎回。
  - 链接：https://docs.ondo.finance/ondo-stocks/secondary-market-restrictions
- 费用：报价相对标的价格有价差与费用归 Ondo；投资者自付 gas；美国股/债股息预扣税 **30%**（BVI 实体），ADR 非美公司通常由卢森堡先扣 15%。
  - 链接：https://docs.ondo.finance/ondo-stocks/fees-and-taxes
- 链与场所（实测，见 t188_venues.json）：Ondo Stocks 走 BNB Chain / Solana / Ethereum。

## 4. SPYX / QQQX / AAPLX（xStocks）—— Backed Assets (JE) Limited

注意：SPYX / QQQX / AAPLX 在本卡实测数据中为 xStocks 体系（Backed），与 Ondo 代币不是同一发行方；**GLDX 才是 Ondo 家的黄金代币**。

- 发行方与法律结构：`Backed Assets (JE) Limited`（泽西岛公司，JFSC 注册，持 COBO / CGPO 同意），每只 xStock 是**完全 1:1 抵押的追踪凭证**，抵押物由受监管托管人在隔离账户持有、无混同；不构成直接股权。
  - 链接：https://docs.xstocks.fi/docs/product-legal-overview
- 适用法 / 招股书：瑞士法；列支敦士登 FMA 批准的 Base Prospectus（2026-05-08），可在 EEA 通行；实体托管为 Jersey 规则（KYC/AML 按泽西法）。
  - 链接：https://assets.backed.fi/legal-documentation
- **受限国家（Restricted Countries）官方页**（`https://assets.backed.fi/legal-documentation/restricted-countries` 原文要点）：
  - **禁止国家**：Iran, North Korea, Syria（国际制裁）；**United States of America**（未向美国证券监管机构注册，不得向 U.S. persons 或身处美国境内的人发售/提供）。
  - **Non-Serviceable Countries**：Afghanistan, Belarus, Central African Republic, Congo (DRC), Cuba, Ethiopia, Haiti, Iraq, Lebanon, Libya, Mali, Mozambique, Myanmar, Nicaragua, Nigeria, Occupied regions of Ukraine, Philippines, Russia, Somalia, South Sudan, Sudan, Venezuela, Yemen, Zimbabwe。
  - **香港不在禁止国，也不在不可服务国名单内。**
- 账户与 KYC（`https://assets.backed.fi/onboarding` 原文要点）：
  - 「Professional / Qualified Investors」可开户做**发行与赎回**；**其他人（eligible token owners）只能开户做赎回**。
  - 开户需标准 KYC：提供个人与财务信息、上传身份证件、**通过实时视频身份核验**；企业客户另需商业登记摘录、法定代表人身份证件、实控人/UBO 名单等。
  - 零售代币**不直接向公众发售，只经持牌实体分销**；购买需符合 Terms and Services 定义的「Qualified Investor」。
  - 链接：https://assets.backed.fi/onboarding
- 美国人限制：有（U.S. persons / 身处美国境内均不可）。
- 链：Ethereum, Solana, Arbitrum, Mantle, Ink, BNB Smart Chain, TRON, TON, X Layer, Optimism, Monad（官方列表）。

## 5. HL HIP-3 黄金 / 股指 / 个股永续

- 机制：HIP-3 = 协议级 builder-deployed perpetuals。部署方负责市场定义（含**预言机定义**）、市场运营（设置预言机价格、杠杆上限、必要时结算市场）；每个 perp dex 有独立保证金、订单簿与部署方设置；与 HyperCore 同一套 API/保证金引擎；抵押品可为任何通过许可清单的 quote asset（`USDC` 等）；主网上线需质押 500k HYPE，至少维持 183 天。
  - 链接（官方 GitBook，Markdown 版）：https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-3-builder-deployed-perpetuals
  - 链接（部署方动作 API）：https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-3-deployer-actions
- 香港可得性：**官方 Terms of Use（https://app.hyperliquid.xyz/terms）为客户端 JS 渲染页面，本轮服务端只拿到 595 字符壳页，正文（含 Restricted Jurisdiction 名单）取不到 → 官方原文「查不到」。**
  - 次级来源（**非发行方原文，仅供定位**）：两个独立站点均把 **Hong Kong 列入 Supported Countries**，把 United States 与 Ontario (Canada) 列入 Restricted Countries：
    - https://www.datawallet.com/crypto/hyperliquid-supported-and-restricted-countries
    - https://www.coinperps.com/learn/hyperliquid-restricted-countries
  - 结论口径：**香港不在次级来源所列受限名单内；但因官方条款正文未能取得，本项标「官方原文查不到（次级来源称不在限制名单）」。**
- 额外发现（与卡相关的机制事实）：HIP-3 允许**部署方侧设置钱包 allowlist**，即单个 HIP-3 dex 可自行限制访问者（与交易所层的地域封锁是两套机制）。来源：https://cryptoslate.com/hyperliquid-tests-allowlists-that-let-operators-restrict-access-to-their-own-markets/
- 关键风险：预言机由部署方设置 → 永续标记价可偏离现货；永续做多是**合成多头**，持有多头付资金费（CLAUDE.md 明确：① 持有 = 现货）。

---

## 取证方法与限制（供复核）

- 抓取脚本：`docs/research/t188_hk_fetch.py`（第 1 轮）、`t188_hk_fetch2.py`（第 2 轮）、`t188_hk_fetch3.py`（第 3 轮）、`t188_hk_fetch4.py`（第 4 轮）、`t188_hk_fetch5.py`（第 5 轮）、`t188_hk_print.py`（打印轮）。全部只读 GET。
- 原文全文：`docs/research/t188_hk_text/*.txt`（每个来源一个文件，含 JS 壳页的空文件）。
- 未取到的项一律写「查不到」，未做任何估算：
  1. Tether Gold 发行实体与实物金保管结构细节、申赎最小额与时效（JS 渲染页）。
  2. Hyperliquid 官方 Terms of Use 正文的 Restricted Jurisdiction 名单（JS 渲染页）。
  3. Paxos 换算最低额与具体交付时序数字（在 help.paxos.com 用户指南里，本轮未取）。
  4. Ondo / Backed 的赎回最小额具体数字（页面未给出金额）。
  5. 手续费表（各 CEX maker/taker 费率、AMM 手续费率）：本轮 JSON 只实测了**点差与盘口深度**，**没有实测手续费率**；AMM 池只有流动性规模，无费率字段 → 手续费一栏标「查不到」。
