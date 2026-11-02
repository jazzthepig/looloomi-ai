# 升级路径(2026-11-02,Seth;Jazz「列出潜在升级的路径和 stack 或者数据源」)

排序原则:按回报层级(① 持有 → ② 倾斜 → ③ 倍数 → ④ 纯 α)和「它解锁了什么我们现在量不到的东西」,不按新鲜度。
每条写清:解锁什么 / 费用 / 谁决定。**没有一条是「接了就有 α」**;接入只是让一个假设变得可测。

## A. 数据源

| # | 源 | 解锁什么 | 费用 / 现状 | 决定 |
|---|---|---|---|---|
| 1 | **DeFiLlama API(解锁日程 + 历史)** | T-220 的 H1(解锁前团队钱包流向 ⇒ 之后跑输)只能用它回测;免费只有未来日程、没有历史,22/25 名字有条目、10/25 有实际日程 | **$3,000 / 年**(T-220 实测 402;Pro $49 档不含 API) | Jazz |
| 2 | **团队 / 基金会钱包集合(自建)** | 不买标签:从归属合约(vesting)和基金会多签反推地址集合,Etherscan 免费 key 拉转账;**我们自己成为数据源**,之后可对外 | 免费 + 一张 lane 卡(先做 10 个有日程的名字) | Seth 派卡 |
| 3 | **Polymarket / Kalshi 公开接口** | 事件的市场隐含概率 ⇒ 情景台账的先验,以及「我们的 Brier vs 市场的 Brier」—— 校准有了对照组 | 免费 | Seth |
| 4 | **SEC EDGAR companyfacts / 8-K(XBRL)** | 轨道公司(CRCL / COIN / HOOD …)的利润、回购、稀释 —— 「小股东待遇」在 TradFi 侧也量得到,和链上发行方并排 | 免费 | Seth |
| 5 | **交易所上币 / 下币公告(Binance / Coinbase / HL RSS)** | 「开闸」事件(UNI −27%、PUMP −67% 那类)成为正式事件源,可回测、可当情景标记 | 免费;进 `feed_items` 同一管道 | Seth |
| 6 | **Deribit 公开接口(隐含波动、偏度、期限)** | ③ 的减仓规则换成加密自己的波动率结构(S-685 证明 TradFi 的 VIX 不是 BTC 的减仓信号) | 免费 | 预注册后做 |
| 7 | **HL HIP-3 股票永续 vs 真股**(T-219:mark 差 0–3%,carry +5.7–15.6% 年化) | 股票腿的「表达工具」成本曲线;要不要在 HL 上表达股票腿由这条曲线定 | 已有数据,加一张监测表 | Seth |
| 8 | **稳定币发行方月度储备证明 + 收入** | 发行方「可分配利润」的时间序列(T-218:2026Q3 发行方收入 7.8× 持币人收入) | 免费(DeFiLlama stablecoins 页 + 发行方公告) | Seth |
| 9 | Glassnode / CryptoQuant / Nansen 链上 | 交易所净流、长期持有者供给 —— 滞后指标为主,S-691 协议下再测 | 付费,$$$ | 不急 |

## B. Stack

1. **Agent harness(11-02 已落):** 降落守卫(按 token、按 lane)、额度预算(滚动 5 小时窗口、储备、自校准)、备用后端。下一步:**本机模型做便宜的活**(Mac Mini 的 LM Studio 已有 MCP 桥)—— 交叉复核、新闻摘要、情景文件初稿,不占订阅额度。
2. **事件库:** `feed_items`(今天起)+ 上币 / 下币 + 解锁日程 + 宏观日历 → 一张 `events` 表,挂实体;情景台账加 `event:` 类变量。情景分析不再从「我记得」开始,从一张能查的表开始。
3. **实时层:** 东京主机的 recorder(T-129)在录 HL 盘口,没有任何消费者。强平地图 × 盘口深度 ⇒ 盘中踩踏探测器,是 ③ 的盘中守卫候选(先 7 天数据、再预注册)。
4. **检索:** `market_state_vectors` v2 + 新闻 embedding ⇒ 「上一次 美联储 + ETF 净流出 + 资金费转负 同时出现,之后发生了什么」—— AI 情景分析的检索底座。
5. **开源 feed 项目(看过,不整套采用,借两块):**
   - [Thysrael/Horizon](https://github.com/successli/Horizon):七步管道(取 / 去重 / 打分 / 丰富 / 摘要 / 输出),源含 HN / Reddit / RSS / **Telegram 频道** / GitHub。借:**把 Telegram 频道当输入源**(All Things AI 本身就是一个信号源)。
   - [RSSHub](https://railway.com/deploy/deploy-rsshub.md):把 X / Twitter、Telegram、任何网页变成 RSS;公共实例限流,要自托管(Railway 一键),X 路由需 cookies。借:**X 账号 → RSS**,加密新闻先在 X 上出现。
   - [RSSbrew](https://github.com/yinan-c/rssbrew)、[it-digest-bot](https://awesome.ecosyste.ms/projects/github.com%2Folegiv%2Fit-digest-bot):AI 摘要 + 日报进 Telegram,人读用;我们的差异化不在摘要,在「每条新闻旁边有我们的数据」。
6. **分发:** Telegram 频道(今天,`TELEGRAM_FEED_CHAT_ID`)→ 同一批帖子进 track-record 页与 MCP `get_signal_feed`。

## C. 策略(按层级)

- ①:$30M 前的场所计划(HL 现货一次 $5.3M 容量);HIP-3 股票永续只做表达不做持有。
- ②:「躲开最差档」在 24 名(S-694)与 50 名(T-224)都 ❌ —— 换原因,不换宽度(T-223 第二族:收入 / 稀释 / 持币人分配)。
- ③:强平地图 7 天后开回放卡;Deribit 波动率结构预注册。
- ④:资金费套息(T-222 只报表)—— 要不要立预注册由 Jazz 定。
