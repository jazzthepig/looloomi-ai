# T-376 · 数据来源调研(只写文档,不写抓取器)

> 目标:四项数据(清算量 / ETH 现货 ETF 净流入 / 山寨解锁日历 / 流通量历史)各找候选来源,
> 查清**免密钥与否、额度、许可与署名、实测能否取到、字段与频率、历史深度**,并给出
> 「常驻进程还是定时拉」「存表最小字段」的落地口径。
> **本文只调研,不含抓取器**;入库由 Seth 做。
> **2026-11-14(T-382)修订**:ETH ETF 结论撤回(见 §2)、Binance 判定细化为「单端点 404」(见 §1.2)、
> 清算日量改为同口径实测外推(见 §1.4)、CMC range 与字段序核定(见 §4.1/§4.2)。逐条更正见
> `docs/research/T-382_corrections.md`。

**一句话结论**

| 项 | 免费可得的路径 | 实测判定 |
|---|---|---|
| ① 清算量 | **OKX WS `liquidation-orders`(免密钥)** + OKX REST 兜底;Bybit WS 可用但稀疏 | ✅ 能取到(Binance `allForceOrders` 单端点 404,Hyperliquid 无公开流) |
| ② ETH 现货 ETF 每日净流入 | **Farside 全量历史表(免密钥,静态 HTML)** | ✅ **走得通** —— 原「走不通」结论已撤回(见 §2) |
| ③ 山寨前瞻解锁日历 | 免费档全部要 key / 已转付费 | ❌ 无免密钥路径(DefiLlama 402、CryptoRank/Tokenomist 401、Cloudflare 403) |
| ④ 各币流通量**历史** | **CMC 内部 data-api(range=1Y 是日频)+ blockchain.com** | ✅ 能取到(**range=all 是周频,range=1Y 才是日频**,见 §4.1) |

---

## 0. 怎么测的

只读探测脚本(纯 GET / WS 订阅,**无密钥、不读 .env、不写库**),脚本与原始结果同名:
`T-376_probe.py` → `T-376_probe_results.json` · `T-376_probe_gaps.py` → `T-376_probe_gaps.json` ·
`T-376_probe_final.py` → `T-376_probe_final.json` · `_t376_verify.py`(流通量语义核验)→ `T-376_supply_verify.json` ·
T-382 新增:`T-382_probe.py`(Binance/CMC/Farside 复核)→ `T-382_probe_results.json` ·
`T-382_farside.py`(Farside 分页/admin-ajax/全量页)→ `T-382_farside_results.json` ·
`T-382_liq.py`(清算量同口径外推)→ `T-382_liq_results.json`。

探测时点:**2026-11-13T16:03Z**(round 1)/ **2026-11-14T01:1x–01:2xZ**(round 2、3)/ **2026-11-14T12:59Z–13:0xZ**(T-382 复核),UTC。
下文每条结论都贴**实际返回的前 200 字符**或**真实错误**,推不动的照实写「抓不到 + 报错」。

> 口径提醒:WS 帧率与清算量都是**静时、单点测量**,只能当量级,不能当全天。

---

## 1. 清算量

### 1.1 候选来源(实测矩阵)

| # | 来源 | 接口 | 拉/推 | 免密钥 | 实测结果 | 许可 / 署名 |
|---|---|---|---|---|---|---|
| A | OKX | `GET https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&state=filled&uly=BTC-USDT&limit=100` | 定时拉 | ✅ 免密钥免签名 | **200 `code=0`**,返回近端强平明细 | OKX 公共 API,对外使用需按其条款标注来源(数据为交易所公开成交) |
| B | OKX | `wss://ws.okx.com/ws/v5/public` + `{"op":"subscribe","args":[{"channel":"liquidation-orders","instType":"SWAP"}]}` | **常驻推送** | ✅ | **21 帧 / 75 秒 ≈ 16.8 帧/分**(全部 SWAP 合约) | 同 A;官方另发「8443 端口将退役,迁 443」通知 |
| C | Bybit | `wss://stream.bybit.com/v5/public/linear` + `{"op":"subscribe","args":["allLiquidation.BTCUSDT"]}` | **常驻推送** | ✅ | 订阅回执 `success:true`;帧数 **3 帧/90 秒**(round 1)vs **0 帧/75 秒**(round 3)→ 静时极稀疏 | Bybit 公共 WS;按其 API 条款 |
| D | Binance | `GET https://fapi.binance.com/fapi/v1/allForceOrders?symbol=BTCUSDT&limit=10` | 定时拉 | ✅ | **404**,返回 HTML 错误页而非 JSON(同 host 对照见 §1.2) | — |
| E | Binance | `wss://fstream.binance.com/stream?streams=btcusdt@forceOrder` | 常驻推送 | ✅ | 连接成功、**0 条事件**;对照组 `btcusdt@aggTrade` 同样 **0 条** → 本机 IP 取不到 Binance WS 数据 | — |
| F | Binance 归档 | `https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/?prefix=data/futures/um/monthly/` | 历史 | ✅ | 200;`monthly/` 下 **9 个目录**(aggTrades / bookTicker / fundingRate / klines / markPriceKlines / premiumIndexKlines / trades …),**没有 `liquidationSnapshot`** → 卡上「快照是空的」应更正为:**这个目录根本不存在** | 归档公开 |
| G | Hyperliquid | `POST https://api.hyperliquid.xyz/info` | 查询 | ✅ | **422** `Failed to deserialize the JSON body into the target type`(type 是枚举,未知名即 422,无法枚举) | HL 公共 API |
| H | Hyperliquid | `wss://api.hyperliquid.xyz/ws` + `{"method":"subscribe","subscription":{"type":"allMids"}}` | 常驻 | ✅ | 连接成功(4 帧/30 秒);**没有公开强平频道** | 同上 |

### 1.2 同 host 对照:Binance 是「单端点 404」,不是「整站不通」(2026-11-14T12:59Z 实测)

同一 host `fapi.binance.com`,11 个端点实测:
**200(7 个)**:`/fapi/v1/ping` → `{}` · `/fapi/v1/ticker/price?symbol=BTCUSDT` → `{"price":"67063.60","symbol":"BTCUSDT","time":1794660781911}` · `/fapi/v1/ticker/24hr` · `/fapi/v1/depth` · `/fapi/v1/openInterest` → `{"symbol":"BTCUSDT","openInterest":"96536.437","time":1794660786444}` · `/fapi/v1/premiumIndex` · `/fapi/v1/exchangeInfo`(1,176,869 字节)。
**401(1 个)**:`/fapi/v1/forceOrders?symbol=BTCUSDT&limit=10` → `{"code":-2014,"msg":"API-key format invalid."}`。
**404(2 个)**:`/fapi/v1/allForceOrders`(带 `symbol` 与不带 `symbol` 均是)→ `<!DOCTYPE html> <!-- saved from url=(0032)https://www.binance.com/en/error --> ...`(1,404 字节 HTML)。**403(1 个)**:`fapi.binance.com/` 根 → HTML。
现货 `api.binance.com` 同机对照:`/api/v3/ping` 200 `{}`、`/api/v3/ticker/price` 200 `{"symbol":"BTCUSDT","price":"67081.46000000"}`、`/api/v3/time` 200。
**⇒ 结论是「单端点 404」。** 「整站不通」被实测排除:同 host 上 7 个端点 200,不是 IP/地域封锁,不是本机网络问题。
`allForceOrders` 回 404 而同 host 的 `forceOrders` 回 401,对照说明**该端点未对公众开放**(非临时封禁);**带 key 后是否可用本次未测(本机无 key)**。

### 1.3 实测返回(前 200 字符)

**OKX REST**(A):
```
{"code":"0","data":[{"details":[{"bkLoss":"0","bkPx":"68904.6","ccy":"","posSide":"short","side":"buy","sz":"0.61","time":1794585117596,"ts":"1794585117596"},{"bkLoss":"0","bkPx":"68904.6",...
```
→ 顶层 `code=0`;`data[]` 每项含 `instId / instType / instFamily / uly / totalLoss / details[]`;`details[]` 每笔含 `bkPx(强平价)/sz(数量)/side(强平单方向)/posSide(被强平仓位方向)/bkLoss/time/ts`。
**必须带 `uly` 或 `instFamily`**,否则 `400 {"code":"50015","msg":"Either parameter uly or instFamily is required"}`。

**OKX WS**(B)真实帧:
```
{"arg":{"channel":"liquidation-orders","instType":"SWAP"},"data":[{"details":[{"bkLoss":"0","bkPx":"937.81","ccy":"","posSide":"long","side":"sell","sz":"1","ts":"1794586718031"}],...
```

**Bybit WS**(C)订阅回执:
```
{"success":true,"ret_msg":"","conn_id":"dbqr5nprroeem1pn9rh0-jady","req_id":"","op":"subscribe"}
```

### 1.4 一天大概多少条 —— 同口径实测外推(2026-11-14)

同一脚本 `T-382_liq.py`,**同一 300 秒墙钟窗口**,两个口径分别测、分别外推(×86400/300 = 288):

| 口径 | 实测 | 外推 | 说明 |
|---|---|---|---|
| OKX WS(全 SWAP,推送) | **306 笔 / 300 s** | **≈ 8.8 万笔/天** | 推送不漏;但只覆盖 OKX 一家 |
| OKX WS(BTC-USDT family,推送) | **306 笔 / 300 s** | ≈ 8.8 万笔/天 | 两条订阅计数相同 ⇒ 该窗口内强平全部落在 BTC-USDT 族 |
| OKX REST(`uly=BTC-USDT`,15 s 轮询) | **222 笔 / 300 s** | ≈ 6.4 万笔/天 | 单币族口径;`limit=100` 的近端快照,轮询间隔必须短于回看窗口才不漏 |

窗口:2026-11-14T13:00:26Z → 13:05:26Z(UTC,静时)。**口径不可混算**:WS 两行是「全 SWAP / 单 family」,REST 是「单 family + 轮询」,
两数之差不是「漏掉的量」,是口径差。

**这个外推不是下界,也不是全天值。** 静时窗口的速率既可能高于也可能低于全天平均速率
(窗口若落在活跃时段则外推偏高,落在极静时段则偏低),所以这个数**既不能写成 `≥`,也不能当成全天值**;
它只说明「在 2026-11-14T13:00–13:05Z 这 5 分钟里,OKX 上的强平笔数是这个量级」。

**T-376 旧版写的「≥4.5 万笔/天(单场所单币下界)」——删。** 那个数没有可核的出处(旧探测没落盘每轮返回条数,
也没把 WS 与 REST 分口径),而且「≥ / 下界」的措辞本身站不住(见上一段)。
再往后 §1.5 的「每天几十到几千笔量级」(Bybit 单 symbol)同样只是**帧率**量级,不是笔数,不能当笔数用。

### 1.5 常驻进程还是定时拉

- **WS = 常驻进程**:长连接 + 心跳 + 断线重连退避;**断线期间的量永久丢失**(WS 没有回补)。
- **REST = 定时拉,只做兜底**:OKX `liquidation-orders` 的回看窗口极短,轮询间隔必须短于该窗口才不漏;
  建议 1 分钟一轮,用来补 WS 断线的最后几分钟。
- **历史从哪来**:Binance 归档里**没有**强平快照(D/E/F 三条实测都指向「本机取不到」),
  OKX/Bybit 也没有公开归档 → **历史强平量目前无免费来源,只能从今天起自己累积**。
  → 若要历史,只能付钱(Binance/Coinglass 等)或走交易所付费数据。

### 1.6 存表最小字段(建议)

```
ts_utc            # 用 OKX/Bybit 自带 ts,不用本地时间(规则 5c)
exchange          # OKX / BYBIT / ...          symbol   # BTC-USDT / BTCUSDT,统一成 BTC-USDT
side              # 强平单方向:buy / sell      pos_side # 被强平仓位方向:long / short
price             # bkPx                       qty      # sz
loss_usd          # bkLoss / totalLoss         source   # okx_ws / okx_rest / bybit_ws
batch_id          # 同一批多笔去重键(OKX 一批多笔,不去重会重复计数)
```
`batch_id`:OKX 顶层有 `instId + totalLoss`,`details[]` 是同批的成交明细 → 用 `exchange + instId + ts + totalLoss`
拼一个稳定键,否则一批会被计成多笔。

---

## 2. 以太坊现货 ETF 每日净流入

### 2.1 候选来源(实测矩阵)

| # | 来源 | 接口 | 免密钥 | 免费额度 | 实测 | 备注 |
|---|---|---|---|---|---|---|
| A | **TFTC**(已在用,BTC) | `GET https://www.tftc.io/bitcoin-etf-flows/data.json` | ✅ | 未见速率限制 | **200** | 前 200:`{"name":"US Spot Bitcoin ETF Daily Flows","description":"Daily net flows for US spot Bitcoin ETFs since launch (2024-01-11): daily Total, original vendor aggregate, per-fund breakdown where available,` |
| A′ | TFTC(ETH 变体) | `/ethereum-etf-flows/data.json`、`/eth-etf-flows/data.json`、`/solana-etf-flows/data.json` | ✅ | — | **404**(三个变体全部) | **TFTC 只有 BTC,没有 ETH** |
| B | **Nasdaq** | `GET https://api.nasdaq.com/api/quote/ETHA/summary?assetclass=etf`(另有 `/info`、`/historical`、`/chart`) | ✅ | 未见速率限制 | **200**,只含**行情与份额成交量** | 前 200:`{"data":{"symbol":"ETHA","summaryData":{"TodayHighLow":{"label":"Today's High/Low","value":"$44.57/$43.23"},"ShareVolume":{"label":"Share Volume","value":"4,282,649.343880"}...` |
| B′ | Nasdaq 资金流端点 | `/net-fund-flows`、`/net-flows`、`/fund-flow`(均 `assetclass=etf`) | ✅ | — | **404**(三个全空 body) | Nasdaq 公开 API **没有** ETF 净流入端点 |
| C | **SEC EDGAR** | `https://efts.sec.gov/LATEST/search-index?q=...`(200,415 条 NPORT-P 命中);`https://data.sec.gov/submissions/CIK0001980994.json`(200) | ✅ | SEC 公开 | 200 | **NPORT-P 是季度申报(月度持仓、约 60 天延迟)→ 月频,不是日频**;`browse-edgar … output=atom` 首轮 200、后轮 **403**(SEC 要求带联系方式的 UA) |
| D | CoinGlass | 网页 `https://www.coinglass.com/eth-etf` 200(JS 外壳);API 404 / 500 | ❌ | — | 500/404 | 需 API key(付费) |
| E | SoSoValue | 网页 **403**;`api.sosovalue.com` **DNS 不解析** | ❌ | — | 403 | 需 key |
| F | **Farside(ETH)** | `GET https://farside.co.uk/ethereum-etf-flow-all-data/`(全量历史表);`GET https://farside.co.uk/eth/`(近端表) | ✅ | 未见速率限制 | **200**,静态 HTML 表 | **592 个交易日,2024-07-23(ETH ETF 上市首日)→ 2026-11-13**,12 列(ETHA ETHB FETH ETHW TETH ETHV QETH EZET MSSE ETHE ETH + Total) |
| G | iShares 持仓 CSV | 发行商每日持仓 | ❌ | — | 卡上已记录「返回网页外壳」 | 未再测 |
| H | Yahoo `query1.finance.yahoo.com` | chart | ❌ | — | **403** | — |

### 2.2 结论:**免费路走得通 —— 原「免费路走不通」已于 2026-11-14 撤回**

- **Farside 有一条没人试过的免密钥全量历史表**:`https://farside.co.uk/ethereum-etf-flow-all-data/`
  实测 **200**,659,725 字节,**静态 HTML `<table>`**(不是 JS 外壳),逐日行 **592 条**,
  覆盖 **2024-07-23 → 2026-11-13**(ETH 现货 ETF 上市首日至今,每个交易日一行),
  列序 **ETHA, ETHB, FETH, ETHW, TETH, ETHV, QETH, EZET, MSSE, ETHE, ETH, Total**(11 只基金 + 合计,US$m)。
  入口在 `/eth/` 页表格下方的脚注里(脚注原文见 §2.4)。
- **`/eth/` 主页只有近 15 个交易日**(2026-10-26 → 2026-11-13,逐日行 15 行,另有 Seed/Total/Average/Maximum/Minimum 统计行)。
  上一版只看了主页、且日期按 ISO 格式扫(扫到 0 个),因此误判「拿不到数据」—— **是探测方法错,不是免费路不通**。
- **15 种分页/admin-ajax 写法都翻不动主页**(实测 `?page=2/3/12`、`?paged=2/3`、`?fund=all`、`?table=2`、`?start=2024-07-23`、`?from=`、`?date=`、`?year=2024`、`?month=7`、`?all=1`、`?format=table`、`?days=1000` 全部 200 但**最早逐日行仍是 2026-10-26**;`admin-ajax.php` 的 16 个 action 名 × GET/POST 全部无表体)。
  **但全量表不需要分页 —— 一次就给全 592 天。**
- TFTC 仍只有比特币 ETF 流量 JSON(ETH/SOL 变体 404);Nasdaq 仍只有行情/成交量;EDGAR 仍是季度口径 + 约 60 天延迟。
  **这三条不再是 ETH 日频的唯一选项 —— Farside 全量表直接就是日频。**

### 2.3 更正:给 Seth 的付费拍板项**撤回**

- T-376 §2.3 提的三条口径(**BTC 代理 / 自建发行商持仓 / 付费**)里,第 3 条**不需要了**:
  **ETH 现货 ETF 日频净流入(含上市以来全部历史)有免密钥来源**,Farside 全量表一条就够。
- 剩下的不是「买不买」,而是**许可**:见 §2.4 —— 站点没有公开的数据许可/再分发条款页,
  页脚只有 `© 2025 Farside Investors. All rights reserved.`。**自用研究**与**对外再分发**(推给前端展示或给机构客户)
  是两回事,后者需 @seth / Jazz 拍板(产品边界 + 版权),lane 不自决。

### 2.4 署名与许可(实测原文)

- 表格下方脚注(逐字):
  `Source: Farside Investors`
  `Note: The above table is generated automatically. Farside Investors is not liable for any errors or inaccuracies in the data.`
  `*ETHE & ETH seed is a conversion from a prior product. To see an alternative table with all the daily flow data, click here`
  (「click here」= `/ethereum-etf-flow-all-data/`;图表下方另有 `Source: Farside Investors` / `Note: These charts are updated automatically in real time`)
- 页脚:`© 2025 Farside Investors. All rights reserved.`
- 条款页实测:`/legal/` **200**(正文 3,065 字符,内容是「Dr Wright 不是中本聪」与比特币白皮书版权声明,**不含数据许可条款**);
  `/terms/`、`/terms-and-conditions/`、`/disclaimer/`、`/about/`、`/contact/` 全部 **404**;`/privacy-policy/` 200(隐私政策,与数据再分发无关)。
- **⇒ 站点上没有可引用的数据使用许可条款。** 唯一约束是署名 + 免责声明 + 版权保留。
  自用/内部研究未见禁止条款;**再分发无授权,需拍板**。

---

## 3. 山寨前瞻解锁 / 释放日历

### 3.1 候选来源(实测矩阵)

| # | 来源 | 接口 | 免密钥 | 实测(前 200 字符 / 真实报错) | 判定 |
|---|---|---|---|---|---|
| A | **DefiLlama** | `GET https://api.llama.fi/emissions`、`/emission/ethereum` | ❌(已转付费) | `Upgrade to the paid API plan at https://defillama.com/subscription`(**402**) | ❌ 走不通 |
| A′ | DefiLlama 变体 | `/api.llama.fi/unlocks`(404)、`coins.llama.fi/emissions`(404)、网页 `defillama.com/unlocks`(200,Next.js 外壳,HTML 内**扫不到任何 api.llama.fi URL**) | — | 404 / JS 外壳 | ❌ 无免费数据口 |
| B | **Tokenomist** | `GET https://api.tokenomist.ai/v1/unlocks` | ❌ | `{"status":false,"statusCode":401,"errorMessage":"x-api-key not found"}`(**401**) | ❌ 要 key(有免费档,需自申请) |
| B′ | Tokenomist 网页 | `tokenomist.ai` | — | **403** Cloudflare(`Just a moment...`) | ❌ 抓不动 |
| C | **CryptoRank** | `api.cryptorank.io/v1/tokens/unlocks` | ❌ | 首轮 **401** `401 Authorization Required`,本轮 **403** Cloudflare | ❌ 要 key |
| D | DropsTab | `dropstab.com` / `drops.tab` | — | **DNS 不解析**(`nodename nor servname provided`) | ❌ 域名/接口未定 |
| E | **CoinMarketCap** | 网页 `coinmarketcap.com/token-unlocks/` 200(JS 外壳);`api.coinmarketcap.com/data-api/v3/cryptocurrency/token-unlocks?id=1027`、`/data-api/v3/token-unlocks` | ✅(data-api 免密钥,图表接口实测 200) | 404 / 404(路径不存在) | ❌ 内部接口路径未找到 |

### 3.2 结论

**没有免密钥的前瞻解锁日历。** 免费档的三条正经路(CryptoRank / Tokenomist / DropsTab)全部要 key 或被 Cloudflare 挡,
DefiLlama 已把 emissions 收进付费档(402 原文如此)。CMC 页面是 JS 外壳,内部 data-api 路径没猜中
(我只试了 2 个路径,**不能断言不存在**;要继续就得在浏览器 DevTools 里抓一次真实请求 —— 需要 @seth 给一台能开 DevTools 的机器)。

### 3.3 最小可行方案(需拍板)

- 自申请 **Tokenomist / CryptoRank 免费档 key**(免费、不用花钱,但要注册)→ 由 Seth 决定是否入库这类 key;
- 或付 DefiLlama 付费档;
- 或**自建**:链上解锁事件从合约 `transfer` 事件 + 已知分配地址表推导(工程量大、覆盖不全,不建议现在做)。

---

## 4. 各币流通量**历史**序列(现在库里只有 8 天)

### 4.1 候选来源(实测矩阵)

| # | 来源 | 接口 | 免密钥 | 实测 | 历史深度 / 频率 |
|---|---|---|---|---|---|
| A | **CoinMarketCap 内部 data-api** | `GET https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id=<cmc_id>&range=all` | ✅ 免密钥 | **200** | BTC `id=1`:**701 点**,2010-07-13 → 2026-11-14,**中位间隔 9.0 天**(min 8.0 / max 9.0),**≤1.5 天的间隔 0 个**;ETH `id=1027`、SOL `id=5426` 同结构 |
| A′ | CMC 中窗口 | 同上 `range=1Y` | ✅ | 200 | BTC:**366 点**,2025-11-14 → 2026-11-14,**中位间隔 1.0 天**(max 1.54 天),**≤1.5 天的间隔 364/365** ⇒ **严格日频** |
| A″ | CMC 短窗口 | 同上 `range=1M` | ✅ | 200 | BTC:**701 点**,2026-10-15 → 2026-11-14,**中位间隔 0.0417 天(1 小时)**,**22.6 点/天** ⇒ **小时频(不是日频)** |
| B | **blockchain.com** | `GET https://api.blockchain.info/charts/total-bitcoins?timespan=all&format=json` | ✅ | **200** | `{"status":"ok","name":"Bitcoins in circulation","unit":"BTC","period":"day",...}`;**1501 点**,2009-01-03 → 2026-11-10,中位间隔 **4.35 天**(标称 period=day,实测非严格日频) |
| C | CoinGecko 公开档 | `GET https://api.coingecko.com/api/v3/coins/{id}/history?date=dd-mm-yyyy` | ✅ | 365 天内 **200**;更早 **401** `{"error":{"status":{...,"error_code":10012,...}}}`;再叠公开档限流 **429** | **只有 365 天**,且公开档限流严格 → 不能当历史源 |
| D | Etherscan v2 | `api.etherscan.io/api/v2/...` | ❌ | `{"status":"0","message":"NOTOK","result":"Missing/Invalid API Key"}` | 要 key;且只给当前供应量,非历史 |
| E | Coinlore | `api.coinlore.net/api/coin/...?id=80` | ✅ | **403** | ❌ |
| F | CoinGecko Pro(已配 key) | `/coins/{id}?localization=false…` | ✅(有 key) | **200** | **当前值**(`supply_cg_current_eth` 200)→ 每天抓一次自己累积,这是**唯一能拿到严格日频**的免费路径 |

### 4.2 语义核验:`v[4]` 到底是流通量吗?

CMC 的 `points[ts].v` 是 5 元数组,位置未文档化。实测核验:
`v = [price, marketCap, volume24h, ?, circulatingSupply]`。

用 **blockchain.com 的独立序列**对同一批日期逐日比对(例:2010-07-22 CMC 3,483,875 vs 3,484,500,差 0.02%;
2010-09-03 差 0.002%;2026-09-23 差 0.001%):
**148 个匹配日,最大相对差 0.73%** → 确认 `v[4]` = **流通量(枚)**,不是市值也不是成交量。
(`v[0]`=价格 68,661、`v[1]`=市值 $434.6 亿、`v[4]`=20,111,506 枚,与当日 BTC 实际供给一致。)

**字段序的代数核定(2026-11-14 实测,不依赖外部源)**:CMC 每点 `v` 是 5 元数组,
对每个点检验恒等式 **`v[2] / v[0] == v[4]`**(若 `v[0]`=价格、`v[2]`=市值、`v[4]`=流通量,则市值 ÷ 价格 必须精确等于流通量):

| range | 点数 | `v[2]/v[0]` vs `v[4]` 中位相对差 | 最大相对差 |
|---|---|---|---|
| `all` | 701 | **0.0** | 2.13e-16 |
| `1Y` | 366 | **0.0** | 1.87e-16 |
| `1M` | 701 | **0.0** | 1.85e-16 |

**恒等式在三个 range 上全部精确成立(残差 = 浮点舍入量级 1e-16)** ⇒ `v[0]`=价格、`v[2]`=市值、`v[4]`=流通量,
**字段序 `[price, ?, marketCap, ?, circulatingSupply]` 核定通过**。附带结论:`v[3]` 恒为 1(三个 range 全样本无例外),
且 `v[1]` 与 `v[4]` 系统性差几个百分点(实测 `v[1]/v[0] / v[4]` 中位 ≈ 0.978–0.994)
—— **`v[1]` 的语义仍未定,且它不等于 `v[4]`,入库时不要拿它当流通量**。

### 4.3 结论与口径建议

- **`range=all` 有历史,但历史不是日频**:BTC 8–9 天一个点(ETH/SOL 更密)。
  → 入库时**按 ts 走,不能假设一天一条**,也不能直接当「日频序列」与日频表对齐。
- **严格日频有一条现成免费路:`range=1Y`**(实测 366 点、中位间隔 1.0 天、≤1.5 天间隔 364/365)。
  它只覆盖**最近 366 天**,更早的日频仍要靠累积或别的源。
- **「按月跑 `range=1Y` 累积日频」—— 可行,但按月跑是浪费**:
  - `range=1Y` **一次就返回整整 366 天日频**,不是「每次只给一点」;**单次调用即可把最近一年补齐**,不必跑满 12 个月。
  - 按月跑的唯一作用是**滚动续期**(每月新增约 30 个点,其余 336 个重叠)。**每次必须全量 upsert 这 366 点,不能只取「新增」** ——
    否则一旦某次失败、之后没人重跑,窗口滑过去就永久缺口(`range=1Y` 不回头补)。
  - **失败容忍度 = 366 天**:任何一次抓取失败,只要 366 天内重跑一次即可补回;按月跑(容忍 30 天)比每天跑(容忍 366 天)更脆。
    ⇒ **建议每天或每周跑一次,全量 upsert;按月跑只有在想省调用次数时才做**。
  - 再往前(>366 天)只有 `range=all` 的稀疏点,**不能靠 1Y 累积补出更早的日频**(2024 年以前的日频没有免费来源)。
- **需要 CMC id,不是 CoinGecko id**(BTC=1 / ETH=1027 / SOL=5426)→ 入库前要一张 id 映射表。
- 前提提醒:CMC data-api 是**站点内部接口,无公开 SLA、无官方文档**(§5 已列),生产依赖前请 @seth 确认可接受。

---

## 5. 建议的入库顺序(给 Seth)

1. **流通量历史**(最省事):CMC data-api `range=1Y`(日频)+ `range=all`(稀疏历史) + blockchain.com(BTC)打底。
2. **清算量**:OKX WS 常驻(唯一实测稳定有帧的免密钥源)+ OKX REST 1 分钟兜底;Bybit WS 可选(稀疏)。
   Binance `allForceOrders` 实测是**单端点 404**(同 host 另有 7 个端点 200),不是整站不通;Hyperliquid 本轮实测取不到,先别写。
3. **ETH 现货 ETF 净流入**:**Farside 全量表可直接用**(免密钥、静态 HTML、592 个交易日 × 12 列)→ **T-376 §2.3 的付费拍板项撤回**;
   入库前只剩**许可问题**(再分发需拍板,见 §2.4)。
4. **解锁日历**:免费路走不通 → **需要拍板**(自申请免费 key / 付费 / 自建)。

**未解决 / 需要 @seth 的**
- ETH ETF 日频净流入:**源已解决,剩许可** —— Farside 数据可否对外再分发(产品边界 + 版权)?
- 解锁日历:是否允许申请 Tokenomist/CryptoRank 免费档 key(入库 key 的流程)?
- CMC data-api 是站点内部接口、**无公开 SLA、无官方文档** → 生产依赖前请确认可接受;需要时请 @seth 评估是否改用付费 CoinGecko/CMC 档做日频主源、CMC 内部接口只做历史底子。
- CMC data-api 的 `token-unlocks` 路径我只试了 2 个 → 若有人能用 DevTools 抓到真实请求路径,请回填,解锁日历那条也许还能救。

---

**合规**:本文只描述数据可得性与字段结构,不含任何资产买卖建议;文中出现的信号词若涉及标的,仅使用
OUTPERFORM / NEUTRAL 等定位语言。
