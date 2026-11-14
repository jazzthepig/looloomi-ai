# T-382 · T-376 更正清单

> 卡:T-376 返工(Farside ETH 重测、Binance 同 host 对照、清算日量、CMC range 语义与字段序)。
> 探测脚本:`docs/research/T-382_probe.py` · `docs/research/T-382_farside.py` · `docs/research/T-382_liq.py`
> 原始结果:`T-382_probe_results.json` · `T-382_farside_results.json` · `T-382_liq_results.json`
> 改版正文:`docs/research/T-376_data_sources.md`(≤250 行)· 探测时点 2026-11-14T12:59Z–13:33Z(UTC)。
> **本文只描述数据可得性与字段结构,不含任何资产买卖建议。**

## 1. Farside ETH —— 原「免费路走不通」结论撤回

**实测(T-382_farside.py)**

- `GET https://farside.co.uk/eth/` → **200**,209,464 字节。首页是**静态 HTML `<table>`**,不是 JS 外壳。
  表格实测 **24 行** = 2 行表头(第 0 行末格 `Total`;第 1 行 `ETHA ETHB FETH ETHW TETH ETHV QETH EZET MSSE ETHE ETH`)+ `Fee` + `Staking fee` + `Seed` + **15 个逐日行** + `Total/Average/Maximum/Minimum` 四个统计行。
  **逐日行 = 15 行,2026-10-26 → 2026-11-13**;数值带括号表示流出(如 `(88.6)`),单位 US$m。
- **历史能回到哪天:首页只到 2026-10-26(近 15 个交易日)。**
  但表格脚注里有一条**没人试过的入口**:`/ethereum-etf-flow-all-data/`
  → 实测 **200**,**659,725 字节**,静态 HTML 表,**逐日行 592 条,2024-07-23 → 2026-11-13**
  (= ETH 现货 ETF 上市首日至今,每个交易日一行),**12 列**:`ETHA ETHB FETH ETHW TETH ETHV QETH EZET MSSE ETHE ETH Total`。
  **这才是完整历史,一次调用给全,不需要分页。**
- **admin-ajax 分页:探不到。**
  `admin-ajax.php` 上 16 个 action 名(`etf_flows` / `eth_table` / `farside_eth` / `farside_table` / `get_etf_table` /
  `load_more` / `table_pagination` / `get_table` / `eth_flows` / `etf_table_data` / `fund_flows` / `load_table` /
  `get_more_rows` / `get_historical` + 页面内嵌的 `um_remove_modal`)**× GET/POST 共 32 次,全部无表体**(400 或 `0`)。
  首页 URL 侧 15 种分页写法(`?page=2/3/12`、`?paged=2/3`、`?fund=all`、`?table=2`、`?start=2024-07-23`、
  `?from=`、`?date=`、`?year=2024`、`?month=7`、`?all=1`、`?format=table`、`?days=1000`)**全部 200 但最早逐日行仍是 2026-10-26**。
  `/wp-json/` 无 etf/flow/farside 相关 route;`/wp-json/wp/v2/pages?slug=eth` 返回 `[]`(slug 不是 `eth`)。
  **⇒ 「分页探不到」成立,但那不重要:全量表一次给全 592 天。**
- **上一版为什么判错**:只看了首页,且按 ISO 格式(`20\d\d-\d\d-\d\d`)扫日期 —— Farside 表里的日期是 `26 Oct 2026` 这种格式,
  ISO 扫描得到 **0 个** token,于是被判成「拿不到逐日数据」。**是探测方法错,不是免费路不通。**

**许可 / 署名条款原文(实测)**

- 表格下方脚注(逐字):
  `Source: Farside Investors`
  `Note: The above table is generated automatically. Farside Investors is not liable for any errors or inaccuracies in the data.`
  `*ETHE & ETH seed is a conversion from a prior product. To see an alternative table with all the daily flow data, click here`
  (「click here」→ `/ethereum-etf-flow-all-data/`;图表下方另有 `Source: Farside Investors` /
  `Note: These charts are updated automatically in real time`)
- 页脚:`© 2025 Farside Investors. All rights reserved.`
- 条款页:`/legal/` **200**(正文 3,065 字符,内容是「Dr Wright 不是中本聪」与比特币白皮书版权声明,**不含数据许可条款**);
  `/terms/` `/terms-and-conditions/` `/disclaimer/` `/about/` `/contact/` 全部 **404**;`/privacy-policy/` 200(隐私政策)。
- **⇒ 站点上没有可引用的数据使用许可条款。** 唯一约束 = 署名 + 免责声明 + 版权保留。
  自用研究未见禁止条款;**再分发(推给前端/给机构客户)无明示授权** → 需 @seth / Jazz 拍板,lane 不自决。

**对 T-376 的更正**:§2.1 候选表补 Farside 行;§2.2 结论由「免费路走不通」改为「**走得通**」;
§2.3「给 Seth 的三条可选口径(需拍板)」→ **付费那条撤回**(BTC 代理 / 自建发行商持仓也不必了);
新增 §2.4 署名与许可。**唯一剩下的是许可问题,不是数据问题。**

## 2. Binance —— 判定细化为「单端点 404」

同一 host `fapi.binance.com` 实测 11 个端点:
**200(7)**:`/fapi/v1/ping`(`{}`)、`/fapi/v1/ticker/price`(`{"price":"67063.60","symbol":"BTCUSDT","time":1794660781911}`)、
`/fapi/v1/ticker/24hr`、`/fapi/v1/depth`、`/fapi/v1/openInterest`(`{"symbol":"BTCUSDT","openInterest":"96536.437",...}`)、
`/fapi/v1/premiumIndex`、`/fapi/v1/exchangeInfo`(1,176,869 字节);
**401(1)**:`/fapi/v1/forceOrders?symbol=BTCUSDT&limit=10` → `{"code":-2014,"msg":"API-key format invalid."}`;
**404(2)**:`/fapi/v1/allForceOrders`(带 / 不带 `symbol` 均是)→ `<!DOCTYPE html> <!-- saved from url=(0032)https://www.binance.com/en/error --> ...`(1,404 字节 HTML);
**403(1)**:host 根 → HTML。现货 `api.binance.com` 同机对照:`/api/v3/ping` `/api/v3/ticker/price` `/api/v3/time` 全部 200。

**⇒ 结论属「单端点 404」,「整站不通」被实测排除**(同 host 7 个端点 200 → 不是 IP/地域封锁,不是本机网络)。
`allForceOrders` 对未认证请求回 404 而同 host 的 `forceOrders` 回 401,对照说明**该端点未对公众开放**(非临时封禁);
**带 key 后是否可用本次未测(本机无 key)**。

## 3. 清算日量 —— 删掉「≥4.5 万笔/天」,只报同口径实测外推

**旧结论作废**:T-376 旧卡里写的「上一轮 REST 推的 **≥4.5 万笔/天(单场所单币下界)**」——
**没有可核出处**(旧探测没落盘每轮返回条数、也没把 WS 与 REST 分口径),**「≥ / 下界」的措辞本身也站不住**。
按卡要求删除,不保留、不加脚注式保留。

**新的报法 —— 同口径实测外推**(同一脚本 `T-382_liq.py`,**同一 300 秒墙钟窗口**,2026-11-14T13:00:26Z→13:05:26Z,UTC 静时):

| 口径 | 实测 | 外推(×288) |
|---|---|---|
| OKX WS 全 SWAP(推送) | **306 笔 / 300 s** | **≈ 8.8 万笔/天** |
| OKX WS BTC-USDT family(推送) | **306 笔 / 300 s** | ≈ 8.8 万笔/天 |
| OKX REST `uly=BTC-USDT`(15 s 轮询) | **222 笔 / 300 s** | ≈ 6.4 万笔/天 |

- **口径不可混算**:两个 WS 数是「全 SWAP / 单 family」,REST 是「单 family + 轮询」;两数之差**不是漏掉的量,是口径差**。
- **明确标注:这不是下界,也不是全天值。** 静时窗口速率既可能高于也可能低于全天平均速率
  (窗口落在活跃时段则外推偏高,极静时段则偏低),所以这个数**不能写成 `≥`**,只能读作
  「2026-11-14T13:00–13:05Z 这 5 分钟里 OKX 上的强平笔数是这个量级」。活跃时段可高 1–2 个数量级;且只有 OKX 一家,不是全市场。
- 同脚本于 **13:28–13:33Z 复跑一次**(结果文件已覆盖,含每轮 REST 返回条数、WS 明细 ts 区间与 instId 分布);
  **以 `T-382_liq_results.json` 的 `extrapolation` 字段为权威值**,上表是 13:00–13:05Z 那次运行的数。
- T-376 §1.3 的 Bybit「每天几十到几千笔」同理只是**帧率**量级,不是笔数。

## 4. CMC range —— 三档点数与间隔,以及「按月跑 range=1Y」的可行性

BTC(`id=1`)实测,三个 range 各一次调用:

| range | 点数 | 首 → 末 | 中位间隔 | max 间隔 | ≤1.5 天的间隔 |
|---|---|---|---|---|---|
| `all` | **701** | 2010-07-13 → 2026-11-14 | **9.0 天** | 9.0 | **0 / 700** |
| `1Y` | **366** | 2025-11-14 → 2026-11-14 | **1.0 天** | 1.54 | **364 / 365** |
| `1M` | **701** | 2026-10-15 → 2026-11-14 | **0.0417 天(1 小时)** | 0.083 | **700 / 700** |

- **更正**:T-376 §4.1 旧行写「`range=1M` 短窗口是**日频**」—— **实测是小时频**(22.6 点/天,中位间隔 1 小时)。
  旧行说「日频只能拿到近期」,方向对、频次写错了。
- **「按月跑 range=1Y 累积日频」:可行,但按月跑是浪费。**
  `range=1Y` **一次就返回整整 366 天日频**,不是「每次给一点」—— **单次调用即可把最近一年补齐**,不必跑满 12 个月。
  按月跑的唯一作用是**滚动续期**(每月新增约 30 点,其余 336 点重叠)。
  **每次必须全量 upsert 这 366 点,不能只取「新增」** —— 否则某次失败后没人重跑,窗口滑过去就永久缺口(`range=1Y` 不回头补)。
  **失败容忍度 = 366 天**:任何一次失败只要 366 天内重跑即可补回 ⇒ 每天/每周跑比按月跑更稳。
  再往前(>366 天)只有 `range=all` 的稀疏点,**1Y 累积补不出更早的日频**(2024 年以前无免费日频源)。

## 5. CMC `v` 字段序 —— 恒等式核定

对每个点检验 **`v[2] / v[0] == v[4]`**(若 `v[0]`=价格、`v[2]`=市值、`v[4]`=流通量,则市值 ÷ 价格 必须精确等于流通量):

| range | 点数 | 中位相对差 | 最大相对差 |
|---|---|---|---|
| `all` | 701 | **0.0** | 2.13e-16 |
| `1Y` | 366 | **0.0** | 1.87e-16 |
| `1M` | 701 | **0.0** | 1.85e-16 |

**三个 range 全部精确成立(残差 = 浮点舍入量级 1e-16)** ⇒ `v[0]`=价格、`v[2]`=市值、`v[4]`=流通量,
字段序 **`[price, ?, marketCap, ?, circulatingSupply]` 核定通过**。
附带:`v[3]` 恒为 1(全样本无例外);`v[1]` 与 `v[4]` 系统性差几个百分点(`v[1]/v[0] / v[4]` 中位 ≈ 0.978–0.994)
—— **`v[1]` 语义未定且不等于 `v[4]`,入库时不要拿它当流通量**。

## 6. 交付物与未决

- 改版正文:`docs/research/T-376_data_sources.md`;本更正清单:`docs/research/T-382_corrections.md`。
- **未决(需 @seth / Jazz 拍板,非技术问题)**:Farside 数据可否**对外再分发**(许可)。自用研究未见禁止条款,再分发无授权。
- **未测**:`allForceOrders` 带 key 是否可用(本机无 key);Farside 是否限流(只测了单次调用,未测速率)。
- 本文不含任何买卖建议;涉及标的仅使用 OUTPERFORM / NEUTRAL 等定位语言。
