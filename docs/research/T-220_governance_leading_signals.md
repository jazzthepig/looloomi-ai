# T-220 治理的领先信号:解锁 / 团队钱包 / 营销强度 —— 数据源可行性 + 现有数据能构造什么 + 两条预注册草稿

**日期**:2026-11-02 · **lane**:lane-c · **纪律**:全程只读(SELECT / 公开 GET / 公开网页),不改代码、不做 DDL、不入库。
**可复跑脚本与中间结果**:`/Volumes/CometCloudAI/cometcloud-local/research/t220/`(本仓 `docs/research/t220/` 有一份拷贝)。

---

## 0. 结论摘要(先看这四条)

1. **① 免费源不够做 CIS 加密 25 个名字的检验。**
   解锁日程:DeFiLlama 的 API 端点已经**全站转付费**(`/emissions`、`/emission/<slug>`、`/raises` 一律 **402** `Upgrade to the paid API plan at https://defillama.com/subscription`)。
   免费能拿到的只有**网页版** `defillama.com/unlocks`(`__NEXT_DATA__` 里内嵌 371 个协议),它给 **22/25** 个 CIS 名字留了条目、其中**只有 10/25 有实际解锁日程**,而且 **371 条全部 `unlockEvents = null` —— 只有未来日程,没有历史**,不能回测 2021–2026。
   钱包标签:免费源给不出「团队/基金会/投资方地址 + 历史余额/转账」这套东西。免费只有 DeFiLlama `/protocol` 的 `treasury`(**7/25 有金库地址**)与 `raises`(**8/25 有融资轮 + 领投方**),都是当前快照。
   缺口与量级(交 Jazz / Seth 定,本卡不替人花钱):解锁日程历史 = DeFiLlama **API 档 $300/月 或 $3,000/年**(Pro 档 $49/月 $490/年**不含 API**);团队/交易所地址标签 + 历史余额 = Arkham / Nansen 付费档,或自建(人工贴标签 + 自己扫链)。

2. **② 营销强度:现有可读表能造出币级事件,但历史太短。**
   `social_daily`(Santiment)是唯一够用的表:23/25 个 CIS 名字、每币 **348 个日观测、2025-10-20 → 2026-10-02**;点值 z>2 事件 **177**(情绪加权)/ **146**(社交量),30 日滚动均值 z>2 事件 **49 / 16**。
   `trending_log` 覆盖 25/25 但只从 **2026-06-26** 起、事件 **14** 个;`sharpe_mindshare_snap` 只有 **14 天**(2026-10-20 → 11-02)⇒ **做不了 30 日 z,0 事件**;`sharpe_narrative_mindshare` 有 **30 个叙事 × 2026-04-23 起**,103 个事件,但是**叙事级不是币级**。

3. **③ S-661 的「开闸」事件:现有营销表基本判不了。**
   重跑 `s661_value_mining.py onset` 得 **18 个**事件(卡上写 17 —— 差的是 `bankercoin-2`,它没有前瞻价,17 = 有 1 个月前瞻收益的那 17 个)。
   18 个里**只有 3 个**(YFI 2026-02-07、SPELL 2026-06-01、LDO 2026-06-01)的「开闸前 30 天」有 ≥20 天热度数据;**其中只有 1 个(SPELL,2026-06-01)开闸前 30 天有热度峰值**(情绪加权 z=2.05、社交量 z=2.22)。
   原因不是"没有峰值",是**热度数据从 2025-10-20 才开始**,12 个更早的开闸事件根本没有热度历史。

4. **④ 两条草稿:H1 现在跑不了(缺两样输入),H2 可以在现有数据上跑但功效很薄。**
   H2 的三个口径里,**"30 日均值 z>2" 家族在发现段是 0 事件**(V1 0、V5 0),按 S-661/S-663 的纪律 ⇒ 这两个口径进不了留出段;只有点值 z>2 家族(V2/V3/V4)发现段有事件(17 / 59 / 31)。

---

## 1. ① 数据源可行性表(不接入、不付费、不注册账号)

### 1.1 代币解锁日程

| 源 | 实测 HTTP(2026-11-02) | 覆盖 CIS 加密 25 名 | 历史起点 | 当时可知(PIT)? | 需注册 | 费用 / 条款 |
|---|---|---|---|---|---|---|
| DeFiLlama API `/emissions` | **402** `Upgrade to the paid API plan at https://defillama.com/subscription` | — | — | — | 否(要付费档) | API 档 **$300/月 或 $3,000/年**;1,000 req/min、1M calls/月,超出 $0.60/1000 次 |
| DeFiLlama API `/emission/<slug>` | **402** 同上 | — | — | — | 同上 | 同上 |
| DeFiLlama API `/raises` | **402** 同上 | — | — | — | 同上 | 同上 |
| DeFiLlama **公开网页** `defillama.com/unlocks` | **200**,1,061,031 B,`__NEXT_DATA__` 内嵌 **371** 个协议 | **22/25** 按 gecko_id 命中;未命中:ADA(cardano)、ETH(ethereum)、XRP(ripple);**有实际解锁日程的只有 10/25**:APT / ARB / AVAX / DOT / ONDO / OP / SOL / STRK / SUI / TIA | **无历史**:371 条**全部** `unlockEvents = null`,只给未来(`nextEvent` / `upcomingEvent` / `next24h` / `unlocksPerDay`);`historicalPrice` 是价格不是解锁 | **否** —— 只有未来日程,不是"当时可知"的历史表 | 否 | 免费;`defillama.com/robots.txt` 是 `Allow: /`,但数据本体是付费 API 的网页版 ⇒ 抓网页属灰色,正解是买 API |
| DeFiLlama API `/protocol/<slug>` | **200** 免费 | 25 个都能打开协议页(XRP 400) | 有 `raises`(融资轮,带 `date` 时间戳、`leadInvestors`/`otherInvestors`)、`treasury`(金库地址) | 是历史**事件**,但不是解锁日程 | 否 | 免费 |
| Tokenomist API `api.tokenomist.ai` | **401** `x-api-key not found` | 需 key | — | — | 是 | 未知 |
| CryptoRank v2 `api.cryptorank.io/v2/...` | **401** Authorization Required | 需 key | — | — | 是 | 未知 |
| Santiment GraphQL `api.santiment.net/graphql` | **200**(可达;查询报错/需 key) | — | — | — | 是 | 免费档受限 |
| CoinGecko `api.coingecko.com/api/v3/ping` | **200** `(V3) To the Moon!` | **无解锁日程字段** | — | — | 否(公开端点限速) | 免费;`robots.txt` 里 `Disallow: /api/v3` |
| `tokenunlocks.app` / `tokenunlocks.xyz` | 连接被重置 / DNS 解析失败 | 实测不可达 | — | — | — | — |
| 项目官方 tokenomics 文档 | 人工逐币 | 25 币里多数有网页 | 只公布当前计划 | **否**(无快照) | 否 | 免费 / 版权 |

**解锁日程这条的判断**:免费源(网页版)**只够做"从今天起的前向试验"**——今天抓一次页面就知道未来的 cliff / linear 日程、类别(见下)、解锁量;要回看历史某天"当时知道什么",必须从今天开始每天存快照,或者买 DeFiLlama API 档。
**类别口径(影响 H1 的可写性)**:页面给的 `category` 取值是 `insiders / privateSale / noncirculating / ecosystem / liquidity / staking / farming / publicSale / airdrop / Uncategorized` —— **没有单独的 `team` / `advisor` / `treasury` 类**,团队与投资方都并进 `insiders`;`upcomingEvent` 类别分布(371 条合计):insiders 97、noncirculating 63、privateSale 42、farming 36、ecosystem 26、staking 11、liquidity 4、airdrop 4、publicSale 3、Uncategorized 18。

### 1.2 团队 / 基金会 / 投资方钱包标签

| 源 | 实测 HTTP(2026-11-02) | 覆盖 | 历史起点 | 当时可知? | 需注册 | 费用 / 备注 |
|---|---|---|---|---|---|---|
| Etherscan API V2 | **200** 但 body `{"status":"0","message":"NOTOK","result":"Missing/Invalid API Key"}` | 需 key 才能批量 | 无历史快照 | 否 | 是(免费 key) | 免费档限速;`etherscan.io/address/<addr>` 网页 GET **200** 且带标签(实测 Binance 14 地址页面里有 "Binance")⇒ 人工查可以,批量要 key |
| Arkham API `api.arkhamintelligence.com/intelligence/address/...` | **400** `invalid timestamp format, please sign up for an api key :)` | 需 key | 无免费历史 | 否 | 是 | 付费档为主 |
| Arkham 网页 `intel.arkm.com` | **403** Cloudflare「Just a moment...」挑战 | 浏览器才有 | — | 否 | 是 | — |
| Nansen API `api.nansen.ai` | 根 **200** `{"message":"ok"}`,数据端点需 key | 标签 / Smart Money 在付费产品 | — | 否 | 是 | 付费 |
| Covalent / Bitquery / Dune / Tokenomist | **401 / 401 / 401 / 401** | 需 key | — | 否 | 是 | Dune 免费但要账号 |
| Blockchair `api.blockchair.com` | stats **200**;地址面板 **430**「Your IP address is temporary blacklisted due to exceeding usage… please apply for an API key」 | 免费无 key 实际已被限死 | — | 否 | 要申请 key | 免费档 |
| **DeFiLlama `/protocol` 的 `treasury`** | **200** 免费 | **7/25**:AAVE `aave.js`、ADA `cardano.js`、DOT `polkadot.js`、LDO `lido.js`、OP `op-foundation.js`、SKY `maker.js`、UNI `uniswap.js` | 当前值,无历史 | 否 | 否 | 免费 |
| **DeFiLlama `/protocol` 的 `raises`** | **200** 免费 | **8/25**:AAVE 4 轮、BTC 1、LDO 3、LINK 1、PENDLE 3、SKY 3、TIA 1、UNI 2(含 `leadInvestors`/`otherInvestors`/`valuation`/`date`) | 历史事件(有 `date`) | 是(历史事件) | 否 | 免费 |
| OpenChain 标签 API `api.openchain.xyz` | **404** / DNS 失败 | 实测未找到可用端点 | — | — | — | 未确认 |
| `labels.ethereum.org` | DNS 解析失败 | — | — | — | — | — |

**钱包标签这条的判断**:免费源只能给出「**一个**金库地址」和「**融资轮与领投方名单**」;给不出「团队/基金会/投资方地址集合 + 每日余额/转账」—— 而 H1 的信号(解锁前 30 天团队钱包向交易所**净流出**)恰恰需要后者。
⇒ **免费源不够**。缺口两块:(a) 标签地址集合(可人工贴,25 币 × ~5 地址,量级是人工周级工作量);(b) 标签地址的日频余额/转账历史(自己扫链可行,但要写取数与断点续跑,等价于 T-168 那种工程量)。
**费用量级(交 Jazz / Seth 拍板,本卡不花钱)**:解锁日程历史 ≈ DeFiLlama API 档 **$3,000/年**($300/月,可只用 1 个月做一次性历史回填);团队/交易所地址标签 + 历史余额 ≈ Arkham / Nansen 付费档(**$几百–几千/月**量级,需按对方报价确认),或自建(人力,无 API 费)。

---

## 2. ② 营销强度:现有可读表的覆盖与能构造的事件

**先说两个坑(都踩过)**:
- `social_daily` 的 `metric` **不止一个**:有 `sentiment_weighted_total` 与 `social_volume_total`,每个 `(symbol, d)` 各一行(全库 146,754 行 / 211 个 symbol / **每个 (symbol,d) 恰好 2 行**,两 metric 各一行)。第一版画像只查到 1 个 metric(`ORDER BY metric` + LIMIT 500 的截断),按单 metric 算出来的 z 全是错的 —— **本报告所有数字都按 metric 分开、每 (symbol,d,metric) 唯一**。
- z 分数一律用**先验窗**(不含当天),最小 60 个先验观测 ⇒ 首个可算 z 的日期是 **2025-12-19**(数据从 2025-10-20 起)。

### 2.1 覆盖画像

| 表 | 名字覆盖(CIS 加密 25) | 起始 | 结束 | 粒度 | 事件数(z>2 / 30 日均值 z>2) |
|---|---|---|---|---|---|
| `social_daily` · `sentiment_weighted_total` | **23/25**(缺 HYPE、SKY) | 2025-10-20 | **2026-10-02** | 日(每币 348 条) | **177** / **49** |
| `social_daily` · `social_volume_total` | **23/25**(缺 HYPE、SKY) | 2025-10-20 | **2026-10-02** | 日(每币 348 条) | **146** / **16** |
| `trending_log` · `attention_score` | **25/25** | **2026-06-26**(逐币不同) | 2026-11-02 | 不规则(每币 1–445 条:APT 12、ADA 27、SKY 1、LDO 1、POL 15、PENDLE 13、OP 9;BTC 118、ETH 270、HYPE 407、SOL 361、SUI 315) | **14**(先验窗 60 / 最少 20) |
| `sharpe_mindshare_snap` · `mindshare_pct` | 23/25(缺 DOT、SKY) | 2026-10-20 | 2026-11-02 | 日,**只有 14 天** | **0**(窗口不足,30 日 z 不可能) |
| `sharpe_narrative_mindshare` | 30 个**叙事**(非币级) | 2026-04-23 | 2026-11-02 | 日(每叙事 187–194 条) | **103**(叙事级) |
| `cis_v2_daily` | 25 加密 + 125 股票 = 150 | 2026-10-21 | 2026-11-01 | 日(**仅 12 天**) | 不作事件源 |

### 2.2 「某币热度 30 日 z > 2」能不能造 —— 能,但要挑口径

两个 z 口径(都只用先验数据,天然 PIT):
- **点值 z**:z(t) = (v_t − mean(前 180 观测)) / sd(前 180 观测),最少 60 个先验观测。
- **30 日滚动均值 z**:m30(t) = 30 日均值;z30(t) = (m30(t) − mean(窗内所有 30 日均值)) / sd(同上)。

事件定义 = z 首次越过 2 的那天(连续段只取首日)。

逐币事件数(`social_daily`,2025-10-20 → 2026-10-02):

| 币 | 情绪加权 点值 / 30日均值 | 社交量 点值 / 30日均值 | 币 | 情绪加权 点值 / 30日均值 | 社交量 点值 / 30日均值 |
|---|---|---|---|---|---|
| AAVE | 5 / 0 | 6 / 1 | LDO | 7 / 5 | 8 / 2 |
| ADA | 10 / 3 | 4 / 1 | LINK | 7 / 0 | 5 / 0 |
| APT | 9 / 1 | 3 / 0 | NEAR | 10 / 6 | 8 / 1 |
| ARB | 8 / 2 | 6 / 1 | ONDO | 9 / 2 | 9 / 1 |
| AVAX | 8 / 0 | 7 / 1 | OP | 9 / 2 | 4 / 0 |
| BNB | 7 / 3 | 2 / 0 | PENDLE | 16 / 4 | 16 / 1 |
| BTC | 4 / 5 | 4 / 0 | POL | 7 / 0 | 4 / 1 |
| DOT | 8 / 2 | 6 / 2 | SOL | 6 / 1 | 3 / 0 |
| ETH | 13 / 4 | 3 / 0 | STRK | 6 / 1 | 3 / 0 |
| INJ | 5 / 2 | 15 / 2 | SUI | 6 / 2 | 7 / 1 |
| TIA | 5 / 2 | 10 / 0 | UNI | 3 / 1 | 10 / 1 |
| XRP | 9 / 0 | 3 / 0 | HYPE / SKY | **social_daily 无** | **social_daily 无** |

**事件数总计**:情绪加权 177 / 49,社交量 146 / 16,trending_log 14,narrative 级 103。

---

## 3. ③ S-661 的「开闸」事件逐个标记(开闸前 30 天有没有热度峰值)

跑的是仓库里现成的 `docs/research/s661_value_mining.py onset`(只读,缓存 `research/s661/_llama_rev.jsonl` + `_mcap_daily.json`)。
**18 个事件**(卡上写 17):`bankercoin-2`(2026-09-29)没有前瞻价 ⇒ 有 1 个月前瞻相对收益的是 **17** 个 —— 与卡面对齐。
标记口径:`pre30_n` = 开闸前 30 天内有几天能算出 z;`pre30_z_max` = 该窗口内 z 的最大值;**峰值 = z_max > 2**;`pre30_covered` = `pre30_n ≥ 20`(否则不判)。

| 开闸日 | gecko | 币 | rel_1m | 情绪加权 前30天 n / z_max / 峰值 | 社交量 前30天 n / z_max / 峰值 | trending |
|---|---|---|---|---|---|---|
| 2021-08-05 | ethereum | ETH | −0.098 | 0 / — / 覆盖外 | 0 / — / 覆盖外 | 覆盖外 |
| 2022-11-23 | tron | TRX | +0.148 | 0 / — / 覆盖外 | 0 / — / 覆盖外 | 覆盖外 |
| 2023-01-05 | kyber-network-crystal | KNC | +0.117 | 0 / — / 覆盖外 | 0 / — / 覆盖外 | 覆盖外 |
| 2023-01-10 | woo-network | WOO | −0.047 | 0 / — / 覆盖外 | 0 / — / 覆盖外 | 覆盖外 |
| 2024-09-16 | thorchain | RUNE | +0.164 | 0 / — / 覆盖外 | 0 / — / 覆盖外 | 覆盖外 |
| 2025-01-02 | syrup | SYRUP | +0.048 | 该币不在 social_daily | 该币不在 social_daily | 覆盖外 |
| 2025-02-06 | ssv-network | SSV | −0.080 | 0 / — / 覆盖外 | 0 / — / 覆盖外 | 覆盖外 |
| 2025-02-17 | jupiter-exchange-solana | JUP | −0.138 | 该币不在 social_daily | 该币不在 social_daily | 覆盖外 |
| 2025-04-09 | aave | AAVE | +0.096 | 0 / — / 覆盖外 | 0 / — / 覆盖外 | 覆盖外 |
| 2025-06-04 | binancecoin | BNB | +0.111 | 0 / — / 覆盖外 | 0 / — / 覆盖外 | 覆盖外 |
| 2025-07-15 | pump-fun | PUMP | −0.674 | 该币不在 social_daily | 该币不在 social_daily | 覆盖外 |
| 2025-08-07 | chainlink | LINK | +0.230 | 0 / — / 覆盖外 | 0 / — / 覆盖外 | 覆盖外 |
| 2025-12-29 | uniswap | UNI | −0.268 | 10 / 0.676 / 无峰 | 10 / 0.164 / 无峰 | 覆盖外 |
| 2026-02-07 | yearn-finance | YFI | −0.102 | 30 / −0.103 / 无峰 | 30 / 0.405 / 无峰 | 覆盖外 |
| **2026-06-01** | **spell-token** | **SPELL** | **−0.290** | **30 / 2.052 / 峰值** | **30 / 2.220 / 峰值** | 覆盖外 |
| 2026-06-01 | lido-dao | LDO | −0.100 | 30 / −0.006 / 无峰 | 30 / 1.447 / 无峰 | 覆盖外 |
| 2026-08-22 | pyth-network | PYTH | −0.027 | 该币不在 social_daily | 该币不在 social_daily | 覆盖外 |
| 2026-09-29 | bankercoin-2 | BNKR | — | 该币不在 social_daily | 该币不在 social_daily | 覆盖外 |

**判定**:18 个事件里 **可判定(前 30 天 ≥20 天热度数据)只有 3 个**(YFI / SPELL / LDO),**其中有热度峰值的只有 1 个**(SPELL,2026-06-01)。另外 12 个事件早于热度历史起点(2025-10-20),3 个事件的币根本不在 `social_daily` 里(SYRUP / JUP / PUMP / PYTH / BNKR 五币无热度数据)。
⇒ **③ 的答案是:现有营销表覆盖不到 S-661 的开闸事件**,不能拿它去说"开闸前有没有热度峰值"。

---

## 4. ④ 两条预注册草稿(只写设计,不算任何结果)

> 共同的机械约定:零分布 / 盈亏 / A-B 一律用 `src/data/evaluation/apparatus.py`(`block_permute` / `shuffle_within` / `null_distribution` / `percentile_of` / `long_return` / `short_return` / `price_on_or_after` / `ab_test` / `brier`),不另写一份。事件日当天的派生量一律**挪一天再判一次**(入场用 `price_on_or_after(dates, closes, T+1, max_gap_days=3)`),只在当天成立的不算。

### 4.1 H1 —— 解锁前 30 天团队钱包向交易所净流出 ⇒ 之后 30 / 90 天相对宇宙跑输

**状态:本轮跑不了** —— 三样必需输入缺两样(解锁日程历史、团队/交易所地址标签 + 日频余额),只有链上原始数据是免费可得的。以下是"数据到位后照此执行"的前向草案(不是回测)。

| 项 | 内容 |
|---|---|
| 宇宙 | CIS 加密 25 名(固定名单,`cis_v2_daily` 的 `grp='crypto'`),每币一条日频序列 |
| 事件 | 解锁事件日 T:取 DeFiLlama `unlockEvents` 的 **cliff** 类,类别含 `insiders`(团队+投资方,页面不单列 team/advisor);`linear` 类单独作为变体 |
| 信号窗口 | W = T−30 … T−1;信号 = 「标签为团队/基金会/投资方的地址 → 标签为交易所的地址」的**净流出**(流出 − 流入)/ 流通市值(流通市值用 `asset_mcap_daily`) |
| 结果窗口 | 之后 **30 天 / 90 天**;结果 = 该币对数收益 − 同期 25 名等权宇宙对数收益 |
| 对照 1(随机日期) | 每个币在「无解锁事件」的日期区间内抽等量伪事件日,算同样的 30/90 天相对收益 ⇒ 零分布 |
| 对照 2(打乱) | `shuffle_within`:同一月内打乱「事件日 ↔ 币」的归属后再算;序列层面用 `block_permute` 打乱日序列块,构造"信号与结果无关"的零分布 |
| 统计 | `null_distribution` 出零分布,`percentile_of` 出实际值分位(单侧:跑输方向);同时用 `ab_test` 报 MDE,不足则标「功效不足」 |
| 试验计数 | 治理族第 1 次;卡内预注册变体 2 个(净流出比例 vs 绝对金额)× 2 个期限(30/90)⇒ Bonferroni **k = 4**,阈值 **0.05/4 = 0.0125** |
| 判据 | 实际值分位 ≤ 0.0125 **且**平均相对收益为负 ⇒ 过;否则记档 |
| 需要的数据 | ① 解锁日程**历史**快照(免费只有未来 ⇒ 从今天起每天存;或买 DeFiLlama API $3,000/年);② 团队/基金会/交易所地址标签(免费无);③ 标签地址日频余额/转账(自己扫链) |
| 若要现在就跑的最小版本 | 只做 **前向**:从 2026-11 起每天抓 `defillama.com/unlocks` 存快照,先攒 3–6 个月的未来日程,信号端用免费链上数据 + 人工贴的 25 币团队/交易所地址 ⇒ 事件数极少,只能当"管道通不通"的冒烟,不能出结论 |

### 4.2 H2 —— 热度事件 ⇒ 之后 30 天相对宇宙跑输

**状态:可以在现有数据上跑**(数据齐),但功效很薄,必须先看事件数。

| 项 | 内容 |
|---|---|
| 宇宙 | CIS 加密 25 名(固定) |
| 主口径 | `social_daily.social_volume_total` 的**点值 z>2**(先验窗 180 观测 / 最少 60;连续段取首日)⇒ 发现段 31 个、留出段 115 个事件 |
| 变体(预注册) | V2 `sentiment_weighted_total` 点值 z>2(59 / 118);V3 `sentiment_weighted_total` 30 日均值 z>2(17 / 32);V4 `social_volume_total` 30 日均值 z>2(**发现段 0** ⇒ 按纪律进不了留出段,只报不判);V5 `trending_log.attention_score` 点值 z>2(先验窗 60/最少 20;**发现段 0**,只报不判) |
| 数据切分 | 热度历史到 **2026-10-02** ⇒ 发现段 **2025-12-19(首个可算 z 日)→ 2026-03-31**;留出段 **2026-04-01 → 2026-10-02**。发现段不过 ⇒ 不算留出段(同 S-663 原文) |
| 结果 | 事件日后 **30 天**对数收益,减 25 名等权宇宙同期对数收益;入场 `price_on_or_after(dates, closes, T+1, max_gap_days=3)`;价格源 `binance_hist`(Seth 09-27 裁定的守护路径) |
| 对照 1(随机日期) | 每个币在非事件日里抽等量伪事件日(固定 seed),算同样的 30 天相对收益 |
| 对照 2(打乱) | `shuffle_within` 在同一月内打乱「事件日 ↔ 币」归属后重算 |
| 统计 | `null_distribution` + `percentile_of`(单侧,跑输方向);`ab_test` 给 MDE 与 CI |
| 试验计数 | 营销/注意力族第 1 次;卡内可判口径 3 个(V1/V2/V3)⇒ Bonferroni **k = 3**,阈值 **0.05/3 ≈ 0.0167** |
| 已知功效上限(必须写进判据) | 发现段事件 17–59 个、留出段 32–118 个;样本内单币事件中位数个位数 ⇒ 若观测差 < MDE,判**「功效不足」**,不判「无效果」 |
| 需要的数据 | 全部已有(只读):`social_daily`、`trending_log`、`ohlcv_daily`(价格)、`asset_mcap_daily`(市值)。缺口:**SKY** 在 `ohlcv_daily` 里只有 hyperliquid 15 天(2026-08-09..08-23),无 binance 价 ⇒ 默认剔除并在结果里写明 |
| 纪律 | 信号只用 T 及之前的数据;事件日当天的派生量挪一天再判;若之后加变体,重算 k |

---

## 5. 附:怎么复核

```bash
# 数据源实测(全部公开 GET)
python3 /Volumes/CometCloudAI/cometcloud-local/research/t220/probe_sources.py    # 402 / 200 / 401 …
python3 /Volumes/CometCloudAI/cometcloud-local/research/t220/probe_sources2.py   # 标签源 401/430 …
python3 /Volumes/CometCloudAI/cometcloud-local/research/t220/probe_sources3.py   # unlocks 网页 / robots.txt
python3 /Volumes/CometCloudAI/cometcloud-local/research/t220/probe_sources4.py   # llama treasury / raises 覆盖
python3 /Volumes/CometCloudAI/cometcloud-local/research/t220/parse_unlocks.py     # __NEXT_DATA__ 结构
python3 /Volumes/CometCloudAI/cometcloud-local/research/t220/parse_unlocks2.py    # CIS 25 覆盖 + PIT
# 库内(只读,publishable key)
python3 /Volumes/CometCloudAI/cometcloud-local/research/t220/cis_universe.py      # 25 加密名单
python3 /Volumes/CometCloudAI/cometcloud-local/research/t220/analysis3.py         # ②③ 主计算
python3 /Volumes/CometCloudAI/cometcloud-local/research/t220/mindshare.py        # mindshare / narrative
python3 /Volumes/CometCloudAI/cometcloud-local/research/t220/segments.py         # 发现/留出段事件数
python3 /Volumes/CometCloudAI/cometcloud-local/research/t220/run_onset.py        # S-661 开闸事件
python3 /Volumes/CometCloudAI/cometcloud-local/research/t220/summarize.py         # 报告用紧凑表
```

**本轮没做 / 下一步(需要 @seth / @jazz 拍板)**
1. **要不要花钱**:解锁日程历史(DeFiLlama API $3,000/年 或 $300/月做一次性回填)+ 团队/交易所地址标签(Arkham / Nansen 付费档,或自建人工)。**11-02 两周铺排里写着不加新数据源** ⇒ 在 Jazz 拍板前,H1 不开工。
2. **先做不花钱的那一半**:H2 可以立刻在现有数据上跑(事件数已量出来,功效薄);要开卡请明确是否值得为 30–118 个事件开一张卡。
3. **解锁网页版抓取是否合规**:免费网页有数据但 robots 允许、数据本体是付费 API 的网页版 ⇒ 若要用,建议走 API 档而不是长期抓网页。
4. **SKY 的价格源**:`ohlcv_daily` 里 SKY 只有 15 天;需要指定守护源(改用 MKR 序列?还是 coingecko_pro_ohlc 的 sky?)—— 这属于取数口径,等 @seth 定。
