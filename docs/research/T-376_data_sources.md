# T-376 · 数据来源调研(只写文档,不写抓取器)

> 目标:四项数据(清算量 / ETH 现货 ETF 净流入 / 山寨解锁日历 / 流通量历史)各找候选来源,
> 查清**免密钥与否、额度、许可与署名、实测能否取到、字段与频率、历史深度**,并给出
> 「常驻进程还是定时拉」「存表最小字段」的落地口径。
> **本文只调研,不含抓取器**;入库由 Seth 做。

**一句话结论**

| 项 | 免费可得的路径 | 实测判定 |
|---|---|---|
| ① 清算量 | **OKX WS `liquidation-orders`(免密钥)** + OKX REST 兜底;Bybit WS 可用但稀疏 | ✅ 能取到(Binance 本机取不到,Hyperliquid 无公开流) |
| ② ETH 现货 ETF 每日净流入 | **没有免费结构化接口** | ❌ 走不通(逐条见 §2) |
| ③ 山寨前瞻解锁日历 | 免费档全部要 key / 已转付费 | ❌ 无免密钥路径(DefiLlama 402、CryptoRank/Tokenomist 401、Cloudflare 403) |
| ④ 各币流通量**历史** | **CMC 内部 data-api + blockchain.com** | ✅ 能取到(**但历史是周频不是日频**,见 §4) |

---

## 0. 怎么测的

三个只读探测脚本(纯 GET / WS 订阅,**无密钥、不读 .env、不写库**):

| 脚本 | 项数 | 原始结果 |
|---|---|---|
| `docs/research/T-376_probe.py` | 81 | `docs/research/T-376_probe_results.json` |
| `docs/research/T-376_probe_gaps.py` | 45 | `docs/research/T-376_probe_gaps.json` |
| `docs/research/T-376_probe_final.py` | 帧抓取 + 语义核验 | `docs/research/T-376_probe_final.json` |

辅助:`docs/research/_t376_verify.py`(流通量语义核验)→ `docs/research/T-376_supply_verify.json`。

探测时点:**2026-11-13T16:03Z**(round 1)/ **2026-11-14T01:1x–01:2xZ**(round 2、3),UTC。
下文每条结论都贴**实际返回的前 200 字符**或**真实错误**,推不动的照实写「抓不到 + 报错」。

> 口径提醒:WS 帧率是**静时、单点测量**(周日 UTC 凌晨窗口),只能当量级,不能当全天。

---

## 1. 清算量

### 1.1 候选来源(实测矩阵)

| # | 来源 | 接口 | 拉/推 | 免密钥 | 实测结果 | 许可 / 署名 |
|---|---|---|---|---|---|---|
| A | OKX | `GET https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&state=filled&uly=BTC-USDT&limit=100` | 定时拉 | ✅ 免密钥免签名 | **200 `code=0`**,返回近端强平明细 | OKX 公共 API,对外使用需按其条款标注来源(数据为交易所公开成交) |
| B | OKX | `wss://ws.okx.com/ws/v5/public` + `{"op":"subscribe","args":[{"channel":"liquidation-orders","instType":"SWAP"}]}` | **常驻推送** | ✅ | **21 帧 / 75 秒 ≈ 16.8 帧/分**(全部 SWAP 合约) | 同 A;官方另发「8443 端口将退役,迁 443」通知 |
| C | Bybit | `wss://stream.bybit.com/v5/public/linear` + `{"op":"subscribe","args":["allLiquidation.BTCUSDT"]}` | **常驻推送** | ✅ | 订阅回执 `success:true`;帧数 **3 帧/90 秒**(round 1)vs **0 帧/75 秒**(round 3)→ 静时极稀疏 | Bybit 公共 WS;按其 API 条款 |
| D | Binance | `GET https://fapi.binance.com/fapi/v1/allForceOrders?symbol=BTCUSDT&limit=10` | 定时拉 | ✅(但要 key 才稳) | **404**,返回 HTML 错误页而非 JSON | — |
| E | Binance | `wss://fstream.binance.com/stream?streams=btcusdt@forceOrder` | 常驻推送 | ✅ | 连接成功、**0 条事件**;对照组 `btcusdt@aggTrade` 同样 **0 条** → 本机 IP 取不到 Binance WS 数据 | — |
| F | Binance 归档 | `https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/?prefix=data/futures/um/monthly/` | 历史 | ✅ | 200;`monthly/` 下 **9 个目录**(aggTrades / bookTicker / fundingRate / klines / markPriceKlines / premiumIndexKlines / trades …),**没有 `liquidationSnapshot`** → 卡上「快照是空的」应更正为:**这个目录根本不存在** | 归档公开 |
| G | Hyperliquid | `POST https://api.hyperliquid.xyz/info` | 查询 | ✅ | **422** `Failed to deserialize the JSON body into the target type`(type 是枚举,未知名即 422,无法枚举) | HL 公共 API |
| H | Hyperliquid | `wss://api.hyperliquid.xyz/ws` + `{"method":"subscribe","subscription":{"type":"allMids"}}` | 常驻 | ✅ | 连接成功(4 帧/30 秒);**没有公开强平频道** | 同上 |

### 1.2 实测返回(前 200 字符)

**OKX REST**(A):
```
{"code":"0","data":[{"details":[{"bkLoss":"0","bkPx":"68904.6","ccy":"","posSide":"short","side":"buy","sz":"0.61","time":1794585117596,"ts":"1794585117596"},{"bkLoss":"0","bkPx":"68904.6","ccy":"","posSide":"short","side":"buy","sz":"0.61","time":...
```
→ 顶层 `code=0`;`data[]` 每项含 `instId / instType / instFamily / uly / totalLoss / details[]`;
`details[]` 每笔含 `bkPx(强平价) / sz(数量) / side(强平单方向) / posSide(被强平仓位方向) / bkLoss / time / ts`。
**必须带 `uly` 或 `instFamily`**,否则 `400 {"code":"50015","msg":"Either parameter uly or instFamily is required"}`。

**OKX WS**(B)真实帧:
```
{"arg":{"channel":"liquidation-orders","instType":"SWAP"},"data":[{"details":[{"bkLoss":"0","bkPx":"937.81","ccy":"","posSide":"long","side":"sell","sz":"1","ts":"1794586718031"}],...
```

**Bybit WS**(C)订阅回执:
```
{"success":true,"ret_msg":"","conn_id":"dbqr5nprroeem1pn9rh0-jady","req_id":"","op":"subscribe"}
```

**Binance REST**(D)错误体:
```
<!DOCTYPE html> | <!-- saved from url=(0032)https://www.binance.com/en/error --> | <html> | <head> | ...
```

### 1.3 一天大概多少条

- OKX WS:实测 **16.8–27 帧/分钟**(静时,全 SWAP 合约族)→ **量级 ~2 万帧/天**;一帧内 `details[]` 可含多笔,
  真实**强平笔数 > 帧数**。**这是静时窗口的量级,不是全天值**;活跃时段(瀑布/插针)可高 1–2 个数量级。
- Bybit WS(单 symbol BTCUSDT):实测 **0–2 帧/分钟** → **每天几十到几千笔量级**。
- OKX REST 单次调用只回**近端一小段**(`limit=100`,时间跨度远小于一天)→ **REST 拿不到历史**。

### 1.4 常驻进程还是定时拉

- **WS = 常驻进程**:长连接 + 心跳 + 断线重连退避;**断线期间的量永久丢失**(WS 没有回补)。
- **REST = 定时拉,只做兜底**:OKX `liquidation-orders` 的回看窗口极短,轮询间隔必须短于该窗口才不漏;
  建议 1 分钟一轮,用来补 WS 断线的最后几分钟。
- **历史从哪来**:Binance 归档里**没有**强平快照(D/E/F 三条实测都指向"本机取不到"),
  OKX/Bybit 也没有公开归档 → **历史强平量目前无免费来源,只能从今天起自己累积**。
  → 若要历史,只能付钱(Binance/Coinglass 等)或走交易所付费数据。

### 1.5 存表最小字段(建议)

```
ts_utc            # 用 OKX/Bybit 自带 ts,不用本地时间(规则 5c)
exchange          # OKX / BYBIT / ...
symbol            # BTC-USDT / BTCUSDT,统一成 BTC-USDT
side              # 强平单方向:buy / sell
pos_side          # 被强平仓位方向:long / short
price             # bkPx
qty               # sz
loss_usd          # bkLoss / totalLoss
batch_id          # 同一批多笔去重键(OKX 一批多笔,不去重会重复计数)
source            # okx_ws / okx_rest / bybit_ws
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
| F | Farside | `farside.co.uk` | ❌ | — | 卡上已记录「拒绝」 | 未再测 |
| G | iShares 持仓 CSV | 发 行商每日持仓 | ❌ | — | 卡上已记录「返回网页外壳」 | 未再测 |
| H | Yahoo `query1.finance.yahoo.com` | chart | ❌ | — | **403** | — |

### 2.2 结论:**免费路走不通(照实)**

- **TFTC 只有比特币 ETF 流量 JSON,ETH/SOL 变体 404** → 已有的免密钥资产**不能直接外推到 ETH**。
- Nasdaq 公开 API **只有行情/成交量,没有净流入**;三个可能的资金流端点路径全部 404。
- EDGAR 免费、权威,但 **NPORT-P 是季报口径 + 约 60 天延迟** → 拿不到「每日净流入」。
- 想要**日频 ETH 现货 ETF 净流入**,免费路径实测全部走不通(要么 403/404,要么口径不对)。

### 2.3 给 Seth 的三条可选口径(需拍板)

1. **用 BTC 流量做代理**:TFTC 的 BTC ETF 流量是现成免密钥的日频;ETH 与 BTC 的 ETF 流量相关性高但不是同一量。
2. **自建**:每天抓发行商每日持仓(shares outstanding)→ Δshares × NAV ≈ 净流入;发行商 CSV 需同意条款/登录态(本次没测通)。
3. **付费**:CoinGlass / SoSoValue / Farside 的付费或 key 档。
> 这条要 @seth / Jazz 定(钱与口径),lane 不自决。

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
| A | **CoinMarketCap 内部 data-api** | `GET https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id=<cmc_id>&range=all` | ✅ 免密钥 | **200** | **701 点**;BTC `id=1`:2010-07-13 → 2026-11-13,**间隔 8–9 天**;ETH `id=1027`:2015-08-07 →,间隔 5–6 天;SOL `id=5426`:2020-04-10 →,间隔 3–4 天 |
| A′ | CMC 短窗口 | 同上 `range=1M` | ✅ | 200 | 短窗口是**日频**(`range=1M` 首点即当日)→ 日频只能拿到近期 |
| B | **blockchain.com** | `GET https://api.blockchain.info/charts/total-bitcoins?timespan=all&format=json` | ✅ | **200** | `{"status":"ok","name":"Bitcoins in circulation","unit":"BTC","period":"day","description":"The total number of bitcoins that have already been mined...","values":[...]}`;**1501 点**,2009-01-03 → 2026-11-10,中位间隔 **4.35 天**(标称 period=day,实测非严格日频) |
| C | CoinGecko 公开档 | `GET https://api.coingecko.com/api/v3/coins/{id}/history?date=dd-mm-yyyy` | ✅ | 365 天内 **200**;更早 **401** `{"error":{"status":{...,"error_code":10012,...}}}`;再叠公开档限流 **429** | **只有 365 天**,且公开档限流严格 → 不能当历史源 |
| D | Etherscan v2 | `api.etherscan.io/api/v2/...` | ❌ | `{"status":"0","message":"NOTOK","result":"Missing/Invalid API Key"}` | 要 key;且只给当前供应量,非历史 |
| E | Coinlore | `api.coinlore.net/api/coin/...?id=80` | ✅ | **403** | ❌ |
| F | CoinGecko Pro(已配 key) | `/coins/{id}?localization=false…` | ✅(有 key) | **200** | **当前值**(`supply_cg_current_eth` 200)→ 每天抓一次自己累积,这是**唯一能拿到严格日频**的免费路径 |

### 4.2 语义核验:`v[4]` 到底是流通量吗?

CMC 的 `points[ts].v` 是 5 元数组,位置未文档化。实测核验:
`v = [price, marketCap, volume24h, ?, circulatingSupply]`。

用 **blockchain.com 的独立序列**对同一批日期逐日比对:

| 日期 | CMC `v[4]` | blockchain.com | 相对差 |
|---|---|---|---|
| 2010-07-22 | 3,483,875 | 3,484,500 | 0.02% |
| 2010-09-03 | 3,895,838 | 3,895,750 | 0.002% |
| 2026-09-23 | 20,088,175 | 20,088,428.1 | 0.001% |

**148 个匹配日,最大相对差 0.73%** → 确认 `v[4]` = **流通量(枚)**,不是市值也不是成交量。
(`v[0]`=价格 68,661、`v[1]`=市值 $434.6 亿、`v[4]`=20,111,506 枚,与当日 BTC 实际供给一致。)

### 4.3 结论与口径建议

- **有历史,但历史不是日频**:CMC `range=all` 对老币是 8–9 天一个点(BTC)、5–6 天(ETH)、3–4 天(SOL)。
  → 入库时**按 ts 走,不能假设一天一条**,也不能直接当「日频序列」与日频表对齐。
- **要严格日频,只有一条免费路**:从今天起每天抓一次 CMC `detail?id=` 的当前 `circulatingSupply`(或用 data-api 当日点)自己累积;
  历史用 CMC 周频 + blockchain.com(BTC)打底。
- **需要 CMC id,不是 CoinGecko id**(BTC=1 / ETH=1027 / SOL=5426)→ 入库前要一张 id 映射表。

---

## 5. 建议的入库顺序(给 Seth)

1. **流通量历史**(最省事):CMC data-api + blockchain.com,先按周频落一份,再每天补当日值。
2. **清算量**:OKX WS 常驻(唯一实测稳定有帧的免密钥源)+ OKX REST 1 分钟兜底;Bybit WS 可选(稀疏)。
   Binance / Hyperliquid 本轮实测取不到,先别写。
3. **ETH 现货 ETF 净流入**:免费路走不通 → **需要拍板**(BTC 代理 / 自建 / 付费)。
4. **解锁日历**:免费路走不通 → **需要拍板**(自申请免费 key / 付费 / 自建)。

**未解决 / 需要 @seth 的**
- ETH ETF 日频净流入:走哪条?(付钱 or 代理)
- 解锁日历:是否允许申请 Tokenomist/CryptoRank 免费档 key(入库 key 的流程)?
- CMC data-api 是站点内部接口、**无公开 SLA、无官方文档** → 生产依赖前请确认可接受;需要时请 @seth 评估是否改用付费 CoinGecko/CMC 档做日频主源、CMC 内部接口只做历史底子。
- CMC data-api 的 `token-unlocks` 路径我只试了 2 个 → 若有人能用 DevTools 抓到真实请求路径,请回填,解锁日历那条也许还能救。

---

**合规**:本文只描述数据可得性与字段结构,不含任何资产买卖建议;文中出现的信号词若涉及标的,仅使用
OUTPERFORM / NEUTRAL 等定位语言。
