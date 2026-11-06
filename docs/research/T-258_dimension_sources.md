# T-258 · 缺的维度,哪里有数(只查不接)

**日期**:2026-11-06 · **lane**:lane-c · **卡**:T-258 · **口径**:只查不接 —— 不改代码、不入库、不打印 key
**验证方式**:2026-11-06 从 Mac 出网(`python3 urllib`;curl / WebFetch 被本机权限挡),**每个候选源一次真实请求**,只取 1–2 行,不落库;响应字段名按实际返回抄写。
**未做的**:没接任何数据、没建表、没跑回测、没算任何零分布。

---

## 〇、一句话结论

六个缺的维度**都有免费可得的源**;其中**交易所级杠杆率 + 净流入**和 **ETF 资金流**是「一次请求就覆盖全部对象」,不构成扇出;
另有两项(BTC×纳指/美元相关、HYG/LQD 相对强弱)**用现有的 `ohlcv_daily` 就能算,零接入**;
**FRED 与 GDELT DOC 在本机不通/被限流**,要在生产端各复验一次(其余全部本机验通)。

---

## 一、已有什么(不重复查的清单)

| 表 | 实测 | 说明 |
|---|---|---|
| `feature_matrix_daily.f` | 30 个键,最新 d = **2026-11-05** | 面板现有维度:`breadth_above_ma50` `dist_200` `dvol:btc(_pct_1y)` `funding_7d_ann(_binance)` `macro:fed_net_liquidity` `macro:fed_rrp` `macro:fng` `macro:total_mcap` `macro:total_volume` `macro:vix` `mom_20/60/200` `oi_chg_30d` `regime_coverage_30d` `regime_share_30d:*` `spy_ret_21` `stable_lend_apy_7d` `style_rel_majors_30d` `taker_buy_share_30d` `vol_30` `vol_pct_3y` `vratio_30_180` |
| `state_daily`(long 格式) | 23 个 feature,最新 d = **2026-11-05** | 比 `f` 多两个:`stable_supply_30d`(**全局**稳定币供应 30 日变化,今天 **−0.0402**)、`dvol:btc` 另列 |
| `ohlcv_daily`(传统标的) | QQQ **2015-01-02→2026-11-05**、SPY 2015-01-02→、UUP **2015-07-13→**、HYG 2015-07-13→、LQD/TLT 2015-07-13→、BTC 2015-07-14→ | 纳指代理、美元代理、高收益/投资级债代理**都已在库** |
| `macro_daily` | `fed_net_liquidity`(2026-11-06 = **5790.845**)、`fed_balance_sheet`(2026-11-04 = 6748.145) | 走 FRED |
| `social_daily` | 只有 `social_volume_total` 一个 metric,**最新 d = 2026-10-07** | Santiment 免费档不含最近 30 天 ⇒ **这条注意力线已经追不上实时**(今天 = 11-06,最新只到 10-07) |
| `events` | news 类只有 **19 条**(coindesk 5 / the_defiant 4 / decrypt 3 / the_block 3 / cointelegraph 3 / bitcoin_magazine 1);listing 294 / delisting 332 / perp_listing 285 / perp_delisting 69;最新 ts 2026-11-06T05:07Z | 「事件」在库,但只有交易所公告,没有政治/宏观事件 |

**六项缺的维度的现状**:
① ETF 资金流 —— 无;② 交易所级稳定币余额与净流入 —— 无(只有**全局** `stable_supply_30d`);③ HY 利差 / MOVE —— 无(`macro:vix` 是股债波动,不是信用利差);④ BTC×纳指/美元相关 —— 无(但 QQQ/UUP/BTC 都在库,**可立刻算**);⑤ OI ÷ 市值杠杆率 —— 只有 `oi_chg_30d`(**变化**,不是水平);⑥ 政治/事件强度 —— 无(`social_daily` 已死、`events` 只有上币/下币)。

---

## 二、可行性表

「一次请求覆盖面」写的是**一个 HTTP 请求能拿到的对象数**,不是能拿到的历史长度。
「时滞」凡未实测的都标了「未实测」—— 发布时滞决定「按时点可用的那一天」,不能猜。

### ① ETF 资金流(IBIT / FBTC …)

| 源 | 端点 | key / 价格 | 历史起点 | 频率 | 时滞 | 一次请求覆盖面 | 我们的 key 能用吗 | 验证 |
|---|---|---|---|---|---|---|---|---|
| **Farside Investors**(免费首选) | `https://farside.co.uk/bitcoin-etf-flow-all-data/`、`/eth/`、`/sol/` | 无 key、无注册 | BTC 页首行 **11 Jan 2024**(实测),该页共 **724 个交易日行**(实测,到 2026-11-05);ETH/SOL 页首行未实测(ETH 上市 2024-07、SOL 更晚,见备注) | 日 | 未实测(市场收盘后发布,需连抓两天校准) | **一页 = 13 只基金 + 合计**(BTC 页列:IBIT FBTC BITB ARKB BTCO EZBC BRRR HODL BTCW MSBT GBTC + BTC + Total;ETH 页列 ETHA ETHB FETH ETHW TETH ETHV QETH EZET MSSE ETHE ETH;SOL 页列 BSOL VSOL FSOL TSOL SOEZ MSOL GSOL) | 不需要 key | ✅ **HTTP 200**,HTML 表格;首行 `11 Jan 2024 IBIT 111.7 / FBTC 227.0 / … / Total 655.3`(US$m);末三行实测 `03 Nov 2026 IBIT (95.0) / FBTC 6.8 / Total (52.6)`、`04 Nov 2026 IBIT (201.2) / FBTC 236.7 / Total 74.6`、`05 Nov 2026 IBIT (105.0) / FBTC (199.9) / Total (430.2)` ⇒ **近三日合计净流出 −52.6 / +74.6 / −430.2 US$m** |
| CoinGlass Open API v3 | `https://open-api-v3.coinglass.com/api/v1/etf/bitcoin/flow-history` | **要 key**(免费档有额度上限) | 未验 | 日 | 未验 | 历史流 + 分基金,一次调用 | 无(本机没有这个 key) | ⚠️ 无 key → **HTTP 500**(不是 401,别把它当「端点不存在」) |
| SoSoValue Open API | `https://api.sosovalue.com/openapi/v2/etf/historicalInflow?type=us-btc-spot` | 要 key(免费档) | 未验 | 日 | 未验 | 分基金历史 | 无 | ❌ 本机 **DNS 不解析**(`nodename nor servname`)⇒ 未验证,不下结论 |
| Nasdaq 公开行情 API | `https://api.nasdaq.com/api/quote/IBIT/historical?assetclass=etf` | 无 key | 2005(工具给的历史,未实测) | 日 | 0(收盘价) | 单只基金(要逐只 ⇒ 扇出) | 不需要 key | ✅ **HTTP 200**,字段 `date, close, volume, open, high`(实测 IBIT `11/05/2026 close 43.03 volume 68,671,960`)—— **只有价量,没有资金流** |
| CoinGecko | `/api/v3/etfs` | 有 key | — | — | — | — | 本机 key 见下 | ❌ **HTTP 404**「Incorrect path」⇒ CoinGecko **没有 ETF 端点** |

> **怎么从价量得到流**:流 = Δ份额 × 净值。Farside 直接给流;Nasdaq 只有价量 ⇒ 要自己拿份额(发行商页面 / yfinance 的 `funds_data`),本机 yfinance 1.3.0 已装但 **YFRateLimitError**,Yahoo `query1` 本机 **403** ⇒ 别把 yfinance 当流的主路。
> **合规**:Farside 是**一次请求**解析一页 ⇒ 不构成扇出,**不需要** `FREE_BULK_EXCEPTIONS` 例外;Nasdaq 若要逐只取 ⇒ 要登记。

### ② 交易所稳定币余额与净流入

| 源 | 端点 | key / 价格 | 历史起点 | 频率 | 时滞 | 一次请求覆盖面 | 我们的 key 能用吗 | 验证 |
|---|---|---|---|---|---|---|---|---|
| **DeFiLlama CEX**(免费首选) | `https://api.llama.fi/cexs` | 无 key | **无历史**(只有当前值;`/cex/{slug}`、`/cexs/chart` 等 7 条路径实测全 **404**) | 快照 | `inflows_24h/1w/1m` 是滚动窗,**响应里没有时间戳字段** ⇒ 必须自己记抓取时刻 | **一次 = 全部交易所**(实测含 Binance / OKX / Bitfinex …) | 不需要 key | ✅ **HTTP 200**;字段:`id, name, slug, coin, coinSymbol, walletsLink, cgId, cgDeriv, url, cgSpotId, currentTvl, cleanAssetsTvl, inflows_24h, inflows_1w, inflows_1m, spotVolume, oi, derivVolume, leverage`。实测 Binance:`currentTvl 127,018,953,685.92`、`oi 31,717,585,440.46`、`leverage 0.24970750`、`inflows_24h −162,859,378.06`、`inflows_1m −7,747,145,366.47`;OKX:`currentTvl 28,421,315,641.33`、`oi 8,406,590,603.87`、`leverage 0.29578471`、`inflows_1w +527,919,321.34` |
| DeFiLlama 稳定币(链级) | `https://stablecoins.llama.fi/stablecoinchains`、`/stablecoincharts/{chain}`、`/stablecoincharts/all` | 无 key | **2017-11-27**(实测首个 `date` = 1511913600) | 日 | T+0 | 一次 = 全部链(`name` + `totalCirculatingUSD.peggedUSD`;实测 Tron 93.8B、Monad 825M 等) | 不需要 key | ✅ **HTTP 200**;`stablecoincharts/Ethereum` 字段:`date, totalCirculating, totalCirculatingUSD, totalMintedUSD` |
| CryptoQuant Community | `https://community-api.cryptoquant.io/v1/exchange-flows/netflow` | 要 key(免费档要人工批准) | 未验 | 日 | 未验 | 交易所×资产 | 无 | ❌ 本机 **DNS 不解析** ⇒ 未验证 |
| CoinGlass / Glassnode / Nansen / Arkham | 各自 REST | 要 key 或付费 | 未验 | 日 | 未验 | 交易所级余额 + 净流入(分资产) | 无 | ❌ 无 key 调用 CoinGlass → **HTTP 500**(同 ①) |

> **口径提醒(重要)**:DeFiLlama 的 `currentTvl` 是**交易所自报/估算的总资产**,不是「稳定币余额」;`inflows_*` 是**全资产净流入**。
> 「交易所级**稳定币**余额」免费源到不了链级精度 —— 要么接受 DeFiLlama 的总资产 + 净流入口径,要么付费(Glassnode/Nansen/CryptoQuant)。

### ③ 高收益债利差 / MOVE

| 源 | 端点 | key / 价格 | 历史起点 | 频率 | 时滞 | 一次请求覆盖面 | 我们的 key 能用吗 | 验证 |
|---|---|---|---|---|---|---|---|---|
| **FRED 公开 CSV(免密钥)** | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2` | **免密钥**(我们代码里已在用,`data_layer.py:747 / 3090 / 3124`) | HY OAS(`BAMLH0A0HYM2`)1996 起;IG OAS `BAMLC0A0CM`;EY OAS `BAMLH0A0HYM2EY`;广义美元 `DTWEXBGS` | 日 | 未实测(ICE BofA 一般 T+1 营业日) | **一次 = 全部序列**(`id=` 可逗号并列多序列) | 不需要 key | ⚠️ **本机不通**:fred.stlouisfed.org / api.stlouisfed.org / alfred.stlouisfed.org 三次 read timeout(45 / 60 / 90s)。**源本身没问题** —— 我们生产代码每天在用它取 `CPIAUCSL`/`A191RL1Q225SBEA`/`UNRATE`/`FEDFUNDS`。**需在 Railway 侧复验一次** |
| FRED API(要 key) | `https://api.stlouisfed.org/fred/series/observations` | 要 key(`FRED_API_KEY`,`cis_provider.py:1081` 在读) | 同上 | 日 | 同上 | 同上 | 本机 env **没有** `FRED_API_KEY`;生产有 | ⚠️ 本机同样 timeout(连不带 key 的错误响应都拿不到 ⇒ 是网络层不通,不是鉴权) |
| CBOE 指数 CSV | `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv`(MOVE 同目录 `MOVE_History.csv`) | 无 key | VIX **1990-01-02**(实测首行) | 日 | T+0 收盘 | 一次 = 全历史单文件 | 不需要 key | ✅ VIX CSV **HTTP 200**(列 `DATE,OPEN,HIGH,LOW,CLOSE`);❌ **MOVE_History.csv → 403 AccessDenied**,`quotes/MOVE.json` → 403;`cboe.com/us/indices/dashboard/move/` 页面 200 但**页面里没有直链 json/csv**(实测正则扫过) |
| 已在库的债代理 | `ohlcv_daily` HYG / LQD / TLT(2015-07-13→) | — | 2015-07-13 | 日 | T+0 | — | — | ✅ 在库(**零接入**) |

> **结论**:真正的 MOVE 指数在本机拿不到(CBOE 403);**HY 利差有免密钥路(FRED CSV)**,但要在生产端验;想要**今天就能用**的信用风险量,用已在库的 **HYG/LQD 相对强弱**(HYG 相对 LQD 的 30 日超额)——它不是利差,但方向上同源(信用风险定价),且零接入、训练期全覆盖。
> **MOVE 的免费替代**:FRED 的 `VIXCLS` + `VIX3M`(期限结构)+ `BAMLH0A0HYM2`(信用)拼一个波动率组合,同样是免密钥 CSV。

### ④ BTC × 纳指 / 美元滚动相关

| 源 | 端点 | key / 价格 | 历史起点 | 频率 | 时滞 | 一次请求覆盖面 | 我们的 key 能用吗 | 验证 |
|---|---|---|---|---|---|---|---|---|
| **现有 `ohlcv_daily`** | `BTC` × `QQQ` / `UUP` | 0 | QQQ 2015-01-02、UUP 2015-07-13、BTC 2015-07-14 | 日 | T+0 | 全历史已在库 | — | ✅ **已在库,零接入**(见第一节跨度) |
| FRED 免密钥 CSV | `fredgraph.csv?id=DTWEXBGS`(广义美元指数) | 免密钥 | 2006 起 | 日 | T+1 | 一次 = 全历史 | 不需要 key | ⚠️ 本机 timeout(同 ③) |
| EODHD | `NDX.INDEX` / `DXY` / `QQQ.US` | 生产有 `EODHD_API_KEY` | 未验 | 日 | T+0 | 逐个代码 ⇒ 扇出 | 生产有 key;**但基本面我们的套餐 403(S-531)**,价格类正常 | ⚠️ 本机无法验(不读 .env) |

> **零接入结论**:这一维**不需要任何新源** —— QQQ / UUP / BTC 三个序列都在 `ohlcv_daily`,2015→今天,当天就能算 30/60 日滚动相关。

### ⑤ 持仓量 ÷ 市值(杠杆率)

| 源 | 端点 | key / 价格 | 历史起点 | 频率 | 时滞 | 一次请求覆盖面 | 我们的 key 能用吗 | 验证 |
|---|---|---|---|---|---|---|---|---|
| **DeFiLlama CEX(免费首选)** | `https://api.llama.fi/cexs` → `leverage`(= `oi` / `currentTvl`,实测 Binance 31.72B / 127.02B = 0.2497 ✓) | 无 key | **无历史** | 快照 | 无时间戳字段 ⇒ 自己记抓取时刻 | 一次 = 全部交易所 | 不需要 key | ✅ 同 ② |
| Hyperliquid | `POST https://api.hyperliquid.xyz/info` `{"type":"metaAndAssetCtxs"}` | 无 key | 快照(无历史) | 每小时(HL 有 `fundingHistory` 之类的逐币历史,但 OI 历史没有免费档) | 即时 | **一次 = 235 个永续** | 不需要 key | ✅ **HTTP 200**;`universe[i]` = `{szDecimals, name, maxLeverage, marginTableId}`;`ctx[i]` = `{funding, openInterest, prevDayPx, dayNtlVlm, premium, oraclePx, markPx, midPx, impactPxs, dayBaseVlm}`。实测 BTC:`openInterest 40,692.0975`、`markPx 75,523.0`、`prevDayPx 80,449.0` |
| Binance 期货 | `GET https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT`;`GET /futures/data/openInterestHist?symbol=BTCUSDT&period=1d&limit=2` | 无 key | openInterestHist 有历史 | 日 | T+0 | **逐个 symbol ⇒ 扇出** | 不需要 key | ✅ 两个端点都 **HTTP 200**;字段:`{symbol, openInterest:"95220.521", time}`;历史端点 `[{symbol, sumOpenInterest, sumOpenInterestValue, CMCCirculatingSupply, timestamp}]`(实测 `sumOpenInterestValue 7,738,508,370.24`) |
| CoinGecko Pro(市值分母) | `pro-api.coingecko.com/api/v3/coins/markets` | 付费 Analyst(`PAID_ENTITLEMENTS` 记 500k/月、实测用量 0.4%) | — | 即时 | — | 250 资产/次 | ⚠️ 本机这把 `COINGECKO_API_KEY` 在 pro-api 主机上 **HTTP 401「API Key Missing」**(header / query / demo-header 三种形式都试过;httpbin 对照证明请求头**确实发出去了**);`api.coingecko.com` 同一把 key **HTTP 200** ⇒ 本机这把更像 **Demo 档**,生产的 Analyst key 在 Railway | ❌ 本机不可用 / ✅ 生产应可用 |
| CoinGlass | `open-api-v3.coinglass.com/api/v1/openInterest/aggregated-history` | 要 key | 未验 | — | 未验 | 未验 | 无 | ❌ 无 key → **HTTP 500** |

> **分母注意**:杠杆率的分母该用**流通市值**。加密的流通量历史 CG 全部档位都没有(`source_policy` 里写着「coin_historical_circulating_supply:全部档位 ✗」)⇒ 用 CG 的 `market_cap` 当分母是可行近似,但要写清是市值不是流通量。

### ⑥ 政治 / 事件强度

| 源 | 端点 | key / 价格 | 历史起点 | 频率 | 时滞 | 一次请求覆盖面 | 我们的 key 能用吗 | 验证 |
|---|---|---|---|---|---|---|---|---|
| **GDELT 批量文件(免费首选)** | `http://data.gdeltproject.org/gdeltv2/lastupdate.txt` → `…export.CSV.zip` / `.mentions.CSV.zip` / `.gkg.csv.zip`;清单 `masterfilelist.txt` | 无 key | **2015-02-18**(实测 `masterfilelist.txt` 首条 `20150218230000.export.CSV.zip`) | **15 分钟一档** | ~15 分钟(档名即时间戳) | 一次 = **全世界全部事件**(一档 163KB / 61 列) | 不需要 key | ✅ **HTTP 200**;`lastupdate.txt` 实测给 `20261106061500.export.CSV.zip`(43,973 B)、`.gkg.csv.zip`(2,777,606 B);下载 `20261105000000.export.CSV.zip` → **200, 163,027 字节** |
| GDELT DOC API | `https://api.gdeltproject.org/api/v2/doc/doc?query=…&mode=timelinevol&format=json` | 无 key | **只近 3 个月**(窗口限制未实测) | 15 分钟 | ~15 分钟 | 一次 = 一个 query 的时间线 | 不需要 key | ✅ **HTTP 200**(JSON:`query_details{title, date_resolution}`、`timeline[0]{series:"Volume Intensity", data[{date:"20261001T000000Z", value}]}`);⚠️ **前两次连发 429**「Please limit requests to one every 5 seconds」⇒ 生产端要退避 |
| Wikimedia pageviews | `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/…/daily/YYYYMMDD/YYYYMMDD` | 无 key | 2015-07 起 | 日 | T+0 | 单条目 | 不需要 key | ✅ **HTTP 200**;⚠️ 日期必须 **`YYYYMMDD`**(用 `YYYYMMDDHHMMSS` → **400**「must be a valid date in YYYYMMDD format」) |
| ACLED / 事件数据库 | 各自 | 要 key / 付费 | 未验 | 日 | 未验 | 未验 | 无 | 未验(本机不查) |

> **GDELT 的坑(实测)**:export 的 CSV **没有表头**,是固定列序的 61 列 TSV —— 取数时最容易错位。实测位:第 45 位国家码(`CA`)、第 46 位一级行政区码(`CA02`)、第 58 位 `DATEADDED`(`20261105000000`)、第 59 位事件源 URL。字段名以官方 schema 为准(`GLOBALEVENTID / SQLDATE / Actor1Code / Actor1Name / Actor1CountryCode / Actor2* / EventCode / GoldsteinScale / NumMentions / AvgTone / QuadClass / ThreatScale / SOURCEURL`)。
> **GDELT DOC 的 404**:`/api/v2/events`、`/api/v2/events/gkg` 两条路径实测 **404**(那是文件下载路,不是 API);`/api/v2/context/context` 返回 200 但 204 字节 HTML(空壳)。

---

## 三、优先级:哪三个最可能让 S-737 的状态分得更开

> 依据:**覆盖期是否对齐 S-737**(训练期 2021-03 → 2023-12,留出期 2024 →,见 T-257)、**当前面板缺哪根轴**、**接入成本**、**信息源独立性**。
> 本卡**不跑回测**,下面是理由,不是结论。

**先说一个硬约束(会改变排序)**:ETF 资金流**只有 2024-01-11 之后**(Farside 实测首行)⇒ 它**进不了训练期**,只能进留出期。
所以「最可能分开状态」的三个,按对齐度排序是下面这三个;ETF 流排第 4。

### 第 1 位:HY 信用利差(FRED `BAMLH0A0HYM2`,1996 起,免密钥)

- **为什么**:现有面板的宏观轴只有 `macro:vix`(股债波动)、`macro:fed_rrp`、`macro:fed_net_liquidity`、`macro:fng` —— **没有一根信用轴**。HY OAS 是「风险偏好」里最经典、且与 BTC 联动最非线性的一根:2022 加息周期里信用利差张开与 BTC 下跌的时序关系,与 2020/2024 的「股市跌、信用不跌」完全不同。
- **对齐**:1996 起 ⇒ **训练期 100% 覆盖**(2021-03→2023-12),留出期全覆盖。
- **成本**:免密钥 CSV(我们代码里已有四处 `fredgraph.csv` 用法)⇒ 接一条序列,一个请求。
- **风险**:本机不通,必须在生产端复验一次;ICE BofA 的 OAS 在 FRED 上是 T+1 营业日更新 ⇒ 按点可得要用「上一营业日」的值(跟 `macro:fed_net_liquidity` 现有做法一致)。

### 第 2 位:BTC × 纳指 / 美元滚动相关(**用现有 `ohlcv_daily`,零接入**)

- **为什么**:它把「BTC 在不在风险资产那一侧」从 `regime_share_30d:*` 的标签猜,变成一个连续、可复算的量。而且它是**截面**量:同一时点 BTC 与 QQQ 的相关 + BTC 与 UUP 的相关,能把「同涨同跌」和「背离」这两种状态分开 —— 这正是 2022 与 2024 的差别。
- **对齐**:`ohlcv_daily` 的 BTC/QQQ/UUP 全部 **2015→今天** ⇒ 训练期、留出期全覆盖。
- **成本**:**零**(只写计算,不接数据)。这是本卡里唯一「今天就能做」的高价值项。
- **注意**:滚动窗口与「相关 vs 水平」的组合会自带状态持续性(相关高的时候相关本身也高)⇒ 如果进状态特征,要先自相关对照,别让它把 6 类状态的相关性撑成假的。

### 第 3 位:交易所级杠杆率 + 净流入(DeFiLlama `/cexs`,一次请求,免费)

- **为什么**:现有 `oi_chg_30d` 只有**变化**;`leverage`(= OI / 交易所资产)是**杠杆拥挤度的水平**,它有明确的横截面(各交易所),可以在 8 个状态上做散开;`inflows_1w/1m` 给的是「钱进场所」的方向,和已有的 `stable_supply_30d`(全局供应,**今天 −0.0402**)形成一个对子:**全球供应缩 + 交易所余额涨 = 资金回场**,这是当前面板看不出来的组合。
- **对齐**:**没有历史**(实测 `/cex/*`、`/cexs/chart` 全 404)⇒ 只能从今天开始每天存 ⇒ **训练期用不了,留出期立刻可用**。若把它排到第 3 而不是更高,原因就是训练期没有。
- **成本**:一次请求、免 key;但响应**没有时间戳字段** ⇒ 落库时必须自己记抓取时刻(否则事后无法判断「当时可见」)。

### 第 4 位:ETF 资金流(Farside 免费;2024-01-11 起 ⇒ 只进留出期)

- 价值高(合规资金、与现有动量/资金费/情绪都不同源),但**训练期没有数据**,且要自己定「哪一天算可得」(美股收盘后发布)。
- 若要做,**先做留出期**,别改训练期口径。

### 第 5 位:政治 / 事件强度(GDELT)

- 覆盖久(2015 起)、免费、一次一档全量;但它离价格远、噪声大,**是否有增量解释力完全没验过**。若要做,建议先用 GDELT DOC 的 `Volume Intensity` 时间线做一次零信号对照,再决定要不要上批量文件。

---

## 四、接数据时要注意的合规与成本(给 Seth 的清单,本卡不做)

1. **一次请求 vs 扇出**:Farside(1 页)、DeFiLlama `/cexs`(1 次)、FRED CSV(1 次多序列)、HL `metaAndAssetCtxs`(1 次 235 标的)、GDELT(1 档)—— 都**不构成扇出** ⇒ **不需要** `FREE_BULK_EXCEPTIONS` 例外。
   例外只在**逐币/逐基金**时才要:Binance `openInterestHist`(逐 symbol)、Nasdaq ETF 历史(逐基金)、CryptoQuant(逐资产)⇒ 这三条若要做,按 `("hyperliquid","hl_funding_hourly")` 的样式登记一条例外(Jazz 11-05 批过「Exception, 1 call/coin/day」的口径)。
2. **`source_policy.BULK_ENDPOINTS["defillama"]`** 现在只列了 `/overview/fees` ⇒ 建议补 `/cexs`(一次调用覆盖全部交易所 + `oi`/`leverage`/`inflows_*`)。这是 `src/` 改动,**不在本卡 allowed_paths,也不在我的口**。
3. **付费源的现状**:`PAID_ENTITLEMENTS` 里 CoinGecko Pro(Analyst,500k/月,实测用量 0.4%)和 EODHD 都是有的,但**本机这把 `COINGECKO_API_KEY` 在 pro-api 主机上 401** ⇒ 生产侧要用 Analyst key 复验一次再谈「用 CG 拿市值分母」。
4. **点可得性**:每条新序列都要写死「这一天的值,当时能看到吗」—— FRED 走 T+1 营业日、Farside 走美股收盘后、DeFiLlama `/cexs` 走抓取时刻(响应无时间戳)、HL/Binance 走即时。

---

## 五、没验成的 / 需要 @seth 与 @jazz 拍板的

| 项 | 状态 |
|---|---|
| FRED(全部三个 host) | **本机 read timeout**(45/60/90s)⇒ 无法在本机确认字段名与时滞。需在 **Railway 侧跑一次** `fredgraph.csv?id=BAMLH0A0HYM2` 与 `?id=DTWEXBGS`(一个请求两个序列) |
| CoinGecko Pro | 本机 key 在 pro-api 上 **401**(三种认证形式)⇒ 需在生产用 Analyst key 复验一次 |
| SoSoValue / CryptoQuant | 本机 **DNS 不解析** ⇒ 未验证,表里已标注,**没有据此下结论** |
| CoinGlass | 无 key 一律 **500** ⇒ 需要 key 才有值(ETF 流 + 交易所余额 + OI) |
| CBOE MOVE | `MOVE_History.csv` / `quotes/MOVE.json` **403** ⇒ 真 MOVE 指数在本机拿不到;要么接受 FRED 免密钥组合(VIX+VIX3M+HY OAS),要么另找源 |
| Yahoo / yfinance | `query1.finance.yahoo.com` **403**、yfinance **YFRateLimitError** ⇒ 别当主路 |
| 需要拍板 | ① 交易所级口径接受「总资产 + 全资产净流入」,还是坚持要**稳定币专用**交易所余额(要付费源);② ETF 流只做留出期,还是等有历史再动;③ 政治事件强度要不要占一个状态维度(需要先做零信号对照) |

---

### 附:本卡的实测原始数字(便于复核)

- `feature_matrix_daily.f` 30 键 / `state_daily` 23 feature,最新 d = 2026-11-05;`stable_supply_30d` = −0.0402352786445492
- `macro_daily`:`fed_net_liquidity` 2026-11-06 = **5790.845**;`fed_balance_sheet` 2026-11-04 = 6748.145
- `ohlcv_daily`:`QQQ` 2015-01-02→2026-11-05、`UUP`/`HYG`/`LQD`/`TLT` 2015-07-13→、`BTC` 2015-07-14→2026-11-05
- `social_daily`:最新 d = **2026-10-07**(唯一 metric `social_volume_total`);`events`:news 19 条,最新 ts 2026-11-06T05:07Z
- DeFiLlama `/cexs`:Binance `currentTvl 127,018,953,685.92` / `oi 31,717,585,440.46` / `leverage 0.2497075004954624` / `inflows_24h −162,859,378.0581585` / `inflows_1w −5,053,267,834.285217` / `inflows_1m −7,747,145,366.473902`;OKX `currentTvl 28,421,315,641.327023` / `oi 8,406,590,603.865862` / `leverage 0.2957847099675414` / `inflows_1w 527,919,321.34327954`
- HL `metaAndAssetCtxs`:235 个永续;BTC `openInterest 40,692.0975` / `markPx 75,523.0` / `prevDayPx 80,449.0` / `dayNtlVlm 4,914,790,729.30`
- Binance `fapi/v1/openInterest?symbol=BTCUSDT` → `openInterest "95220.521"`;`openInterestHist` → `sumOpenInterestValue "7738508370.23556000"`
- Farside BTC 页首行:`11 Jan 2024 · IBIT 111.7 · FBTC 227.0 · BITB 237.9 · ARKB 65.3 · BTCO 17.4 · EZBC 50.1 · BRRR 29.4 · HODL 10.6 · BTCW 1.0 · MSBT − · GBTC (95.1) · BTC − · Total 655.3`(US$m);共 **724** 个交易日行;末三行 `03/04/05 Nov 2026` 的 Total = **(52.6) / 74.6 / (430.2)**
- Nasdaq IBIT:`totalRecords 26`,`11/05/2026 close 43.03 volume 68,671,960`
- GDELT:`20261105000000.export.CSV.zip` 163,027 字节 / 61 列 / 无表头;`masterfilelist.txt` 首条 `20150218230000.export.CSV.zip`
- CBOE VIX CSV 首行 `01/02/1990,17.240000,…`
- CoinGecko public host(`/api/v3/coins/markets?per_page=2`):`market_cap 1,516,044,216,171`(BTC)、`current_price 75,405`;`/api/v3/etfs` → 404
