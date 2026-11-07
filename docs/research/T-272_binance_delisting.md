# T-272 — Binance 下架公告之后 30 天,代币在别的场所还继续跑输吗

**任务**:S-751(B 道)。口径一字不改照台账:`events` 里 `source=binance, kind=delisting` 的**整个代币下架**公告;
d0 = 公告时刻之后的第一个 UTC 日收盘;价格 = CoinGecko 日收盘;超额 = 代币收益 − BTC 收益;H = 30 天(主)、7 天(副);
对照 = 同一代币在 [d0−365, d0−60] 里随机取 200 个日子算同样的 30 天超额,事件中位数在对照中位数分布里的分位。

**结论(主源 `asset_mcap_daily`,n = 53):公告之后仍持续跑输,判据 (a)–(e) 全过 ⇒ ✅。**
但**跑输的大头不在公告本身**——公告前 30 天已经跑输 −34.4%、公告当天再跳 −23.7%,公告**之后**的 30 天是 −37.7%。
所以这是「坏币持续性」,不是「公告的因果效应」;当成 ② 的面板卫生规则可用,当成可交易的因果结论不成立。

- 脚本:`docs/research/t272_delisting.py`(阶段 `screen → prices → stats`,先落清单再取价)
- 筛选清单(全部 368 条的纳入/排除):`docs/research/t272_screening.json`
- 数字产物:`docs/research/t272_results.json`(含每代币明细)

---

## 1. 筛选规则(先写死,再对全表跑)

事件库 `kind=delisting` 共 **368 条,全部是 source=binance**(2022-02-17 → 2026-10-27;表内总数 368,抓取 368,已核)。

**纳入**:标题含 `Will Delist <代币>…`,且不含任何「仅杠杆 / 仅合约 / 仅交易对 / 仅板块」标记:
`Margin, Loan, Leveraged Token, Options, Alpha, Staking, Earn, Redemption, Trading Pair, Collateral, Stocks`。

**排除 329 条**,理由分布(全部逐条落在 `t272_screening.json` 的 `decisions[].reason`):

| 理由 | 条数 | 例 |
|---|---|---|
| pair_removal:spot_or_trading_pairs | 188 | `Notice of Removal of Spot Trading Pairs - …` |
| pair_removal:margin_pairs | 63 | `Notice of Removal of Margin Trading Pairs - …` |
| banned:Margin(仅保证金对/借贷) | 30 | `Binance Margin to Delist LUNA on Cross Margin …` |
| no_will_delist(杠杆代币/质押/监控标签/股票/稳定币转换) | 14 | `… Leveraged Tokens` / `Binance Staking to Delist …` / `Will Extend the Monitoring Tag …` |
| alpha_board | 10 | `Binance Alpha Will Remove …` |
| banned:Margin,Loan | 6 | `Binance Margin And Loan Will Delist …` |
| not_a_delisting:Notice of Removal of(单数形式) | 5 | `Notice of Removal of AXS/BIDR Trading Pair` |
| banned:Options(每日期权) | 2 | `Binance Will Delist All American-Style Daily Options` |
| banned:Margin,Trading Pair | 2 | — |
| not_a_delisting:Binance Loans | 2 | `Notice on Delisting of Binance Loans …` |
| not_a_delisting:Upcoming Changes to | 2 | `Upcoming Changes to RON Spot Trading` |
| 其余单条(banned:Margin,Earn / Loan,Collateral / Alpha / Redemption / Suspension of / Notice Regarding the Removal) | 7 | `Suspension of Gifto (GFT) Deposits and Update on the Delisting Date` |

**纳入 39 条公告 → 164 个代币(一个代币多次公告取最早一次 ts)**。最晚一次纳入公告 2026-10-14(EPIC, QUICK)。

> ⚠️ 方法学限制(诚实):`Notice of Removal of Spot Trading Pairs` 这 188 条**标题里不带币名**,无法从标题判断是「整币下架」还是「只下架某几个交易对」。台账写死排除「移除某些交易对」,故一律排除——**这条规则可能漏掉一批真正的整币下架公告**,但漏的方向是**少计事件**,不会造出假阳性。

---

## 2. 判据 (a)–(e)(主源 `asset_mcap_daily`,`source=coingecko_pro_market_chart`)

| 判据 | 阈值 | 实测 | 过 |
|---|---|---|---|
| (a) 30 天超额中位数 | ≤ −10% | **−37.71%** | ✅ |
| (b) 30 天超额为负的事件占比 | ≥ 65% | **81.13%**(43/53) | ✅ |
| (c) 对照分位(200 次随机日抽样) | ≤ 0.05 | **0.000** | ✅ |
| (d) 2022–2023 与 2024–2026 两段中位数同号 | 同号 | **−2.68%** vs **−37.71%**(均负) | ✅(形式) |
| (e) 有价可算代币 | ≥ 40 | **53** | ✅ |

**对照零分布(200 次)**:对照中位数的 q05 = −13.20%、q50 = −8.68%、q95 = −3.47%;
事件中位数 −37.71% **低于全部 200 次抽样** ⇒ 分位 0.000。

**有价 / 无价代币**:纳入 164 个代币中,**有价 53 个(能算满 30 天超额),无价 111 个**(下架后 CoinGecko 不再跟价,
在 `asset_mcap_daily` / `ohlcv_daily` 里查无此 symbol);有价但 30 天超额不可算 = 0。

**(d) 的诚实读数**:2022–2023 段只有 **n = 1**(HNT,2023-03-17,−2.68%),因为这批 2022 年的币(BCD/CND/MTH/NCASH/YOYO、
HEGIC/RENBTC/SUSD、EZ/QSP/BRD/NXS/NAV/MDA/SPARTA、DNT/NBS/BTG/TCT、MITH/TRIBE/REP/BTCST)今天已不在价格库里。
**这一段形式上同号,但实质上 n=1,不能当"两段都成立"读**;稳健的那一段是 2024–2026(n = 52)。

**分布形状(30 天超额分位)**:p0 −123.4% / p10 −91.0% / p25 −63.4% / **中位 −37.7%** / p75 −17.3% / p90 +33.3%(最大 +230.2%)。
不是一个极端值撑起来的:剔除绝对值最大的 3 个样本后(n = 50)中位数 **−30.90%**、负占比 80.0%;剔除疑似 ticker 复用的
`DATA`(CoinGecko `story-2`,见 §5)后(n = 52)中位数 **−37.71%**、负占比 80.8% —— **两条敏感性都不改变结论**。

---

## 3. 副项(只报不判)

| 副项 | 中位数 | n |
|---|---|---|
| 公告**前** 30 天超额(d0−30 → d0,是否提前走漏) | **−34.40%** | 53 |
| 公告**当天**那一跳(d0−1 → d0) | **−23.73%** | 53 |
| 7 天超额(副持有期) | −13.65% | 53 |
| 按公告前市值三分位:低市值档 | **−55.81%**(市值 421 万–1012 万) | 16 |
| 中市值档 | −30.90%(1052 万–2114 万) | 16 |
| 高市值档 | −20.97%(2178 万–29.9 亿) | 18 |
| `perp_delisting` 同口径另报 | **−48.44%**,7/7 为负 | 7 个可算(37 个标的) |

**这张表是本卡最重要的东西**:公告**前** 30 天已经跑输 −34.4%,公告当天再 −23.7%,公告**后** 30 天 −37.7%。
三段加起来,超额跌幅的**绝大部分发生在公告之前**。币安的下架公告在链上/交易所上是「公开事件」,但**代币本身早就在跌**——
下架投票的标准本身(流动性/表现)就是把已经在崩的币挑出来。**所以「公告后继续跑输」是真的(✅ 成立),
但它更像是坏币的持续性(selection),不是公告的因果效应(causation)。**

---

## 4. 交叉核对(第二个独立价格源)

`ohlcv_daily(source=coingecko_pro_ohlc)` 作为独立源重跑同口径:

| | 主源 `asset_mcap_daily` | 核对源 `ohlcv_daily` |
|---|---|---|
| 可算代币 | 53 | 32 |
| 30 天超额中位数 | −37.71% | **−54.25%** |
| 负占比 | 81.13% | 84.38% |
| 对照分位 | 0.000 | 0.000 |

两个源同向、结论一致(核对源覆盖的币更少、跌得更深,因为它偏向仍在跟价的僵尸币)。

---

## 5. 诚实caveats

1. **ticker 复用**:CoinGecko 的 symbol 会复用。逐条核对 `coin_id`(`t272_results.json` → `sensitivity.all_coin_ids`):
   52 个代币的 ticker 与 coin_id 一致;**1 个可疑**——`DATA` → `story-2`(story 的 ticker 应是 STORY),
   而 Binance 2026-02-02 公告里 `DATA` 与 `DF`(dForce)并列,故 `DATA` 很可能匹配到了别的币。剔除它结论不变(§2)。
2. **幸存/可见性偏差**:只有 53/164 个代币今天还有价,能进样本的本身就是「币安下架了、但别处还在交易」的那批;
   无价的那 111 个**不是「没有效应」,是「看不见」**——它们很可能是跌得最惨的(价格直接归零)。
   所以 −37.7% 是**样本内下界,不是总体估计**。
3. **(d) 段 n=1**(见 §2)。
4. **公告前就跑输**(见 §3)⇒ 不可把本卡读成「公告 → 下跌」的因果证据。
5. **超额用差值**(代币收益 − BTC 收益),照台账写死;币级波动率差异会让差值比比值更极端。

---

## 6. 产物

| 文件 | 内容 |
|---|---|
| `docs/research/t272_delisting.py` | 三阶段脚本(screen / prices / stats) |
| `docs/research/t272_screening.json` | 368 条的逐条纳入/排除判定 + 39 条纳入公告 + 164 代币 + 78 条 perp 判定 |
| `docs/research/t272_price_cache.json` | 两个价格源逐 symbol 的原始行(缓存,可复跑) |
| `docs/research/t272_results.json` | (a)–(e) 数字、每代币明细、副项、敏感性、两个源的对照 |
| `docs/research/scenarios/lane-b-T-272.json` | 前向预期(机器结算) |

零分布 / 多空盈亏 / 分位一律走 `src/data/evaluation/apparatus.py`(`random_dates_like` / `null_distribution` /
`percentile_of` / `long_return` / `price_on_or_after`);未改任何生产代码、未入库。
