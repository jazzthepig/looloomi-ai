# T-366 — 真钱在交易的币有没有向量:R-v2 票源币逐个对账(资产向量 / 资金面向量 / CIS)

**卡** T-366(台账 S-842) · **lane-b** · 第二轮(返工 Seth 2026-11-13 八条 CHANGES)· 只读、未入库、未改 `src/`
**脚本** `docs/research/T-366_coverage.py` · **结果** `docs/research/T-366_traded_universe_coverage.json`
**生成口径**:本文件由脚本从上面的 JSON 渲染(③:数字一律从 JSON 生成,没有手抄)

---

## 0. 结论

1. **九成票源币没有向量。** 2024-11 以来开过票的 **241 个币**里,`asset_embeddings`(schema_version=3 且 7 天内更新)只有 **24 个(10.0%)**;三套描述(资产向量 / 资金面向量 / CIS)**一个都没有**的有 **137 个币(56.8%)**,对应 **234 张票(56.9%)**、**61.9% 的 |美元盈亏|**。
2. **「缺向量的就是亏钱那一侧」是错的 —— 两边都赚。** 未覆盖的 137 个币净 **$1,778.48**(净/|P&L| = 28.3%),覆盖的 104 个币净 **$1,244.66**(32.2%)—— 覆盖组确实更赚钱(单位 |P&L| 的净利率更高),但**未覆盖组本身也赚钱**。全窗 241 个币里 103 个净赚、138 个净亏。
3. **27 维里 17 维依赖 CIS、10 维不依赖**(`6,7,8,9,10,11,12,13,16,17`)。但**「非 CIS 币最多 10 维、卡在门槛上」这个第一轮说法在活路径上不成立**:真实写端是 `src/data/vector/embedder.py::generate_embedding`,它把缺失字段填**默认值**而不是 NaN(实测 `measured_dims(default)=18`、`is_thin(default)=False`),且 `upsert_embeddings` **不过门槛**(upsert 源码里有没有 `is_thin(`:False)。没有 CIS 的币写出来是**看起来完整的 18 维**向量,支柱是 0.0 —— 不是「被门槛挡住」。
4. **真正挡住扩面板的是输入契约,不是抓取器 universe。** Mac 端 `vector_push.py` 的 payload 就是 `cis_scores_latest.json`(= CIS 宇宙)⇒ 非 CIS 的币根本进不了 payload;「把 CoinGecko derivatives 抓取器扩到票源币」只解决 [12] 这一维,解决不了另外 17 维。扩面板 = 扩 payload 契约或新开写路径(需另开卡)。
5. **最小方案(零新抓取器)的实测算式(逐币,不是估的)**:仅 Supabase 库 ⇒ 0 币达 10 维门槛;加 Mac 永续日线面板 ⇒ 0 币;**再加 OI 存量 ⇒ 99 币**;**再补 funding(只有 ≤7 天的才算实测)⇒ 170 币**(净增 71 币);剩下 71 个币补不满,逐币分组见第 5 节。

---

## 1. 票源与口径(一字不改,全部沿用上游)

| 项 | 值 |
|---|---|
| 票源 | `docs/research/t197_results.json → tickets.A(与 t310_slots.load_tickets 同源)` |
| 总票 / 窗口 | 956 张 / `signal_d ≥ 2024-11-01` → **411 张票、241 个币**,信号 2024-11-06 → 2026-09-29 |
| 未平仓票 | 0 张, r 为空 → 用 Mac 数据根永续日线最后一根收盘算 mtm(0 张算不出名义) |
| 名义 | `min(净值 × 0.5% ÷ 止损距离, 净值 × 50%)`,净值恒取 $630(t310 的 equity0,逐票独立口径,不复利) |
| 美元盈亏 | `名义 × r`;全窗 **|P&L| = $10,160.09、净 = $3,023.13** |
| 永续面板 | `/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl`,890 币,2020-01-01 → 2026-09-30 |

## 2. 三套描述的现状(本轮实测)

| 表 | 规模 | 关键事实 |
|---|---|---|
| `asset_embeddings` | 73 行 | 59 行 `schema_version=3` 且 7 天内更新(最新 2026-11-16T18:41:05.64874+00:00);14 行陈旧 |
| `asset_flow_daily` | 0-0/432296 行 | 最新日 2026-11-15;票源 239 币里 104 个「自己最新一行有 vec」(其中 34 个距最新日 ≤7 天);这 104 个币的 vec 最新行中位陈旧 1 天 |
| `cis_official_daily` | 2145 行 / 59 币 | 最新 2026-11-15,59 币都有正式分(等级 C,C+,D,F) |
| `asset_edge_moments`(视图) | */* | **0 行** ⇒ 写端 [25][26] 两维无数据可取 |

**存量向量审计(写端默认值污染)**:73 行存量向量里,**34 行**的 [11]=0.0、[12]=0.0、[13]=0.5 同时成立 —— 这是写端的**默认值**([13]=0.5 来自「ATH 距离缺省 50%」),不是实测;**34 行的 [12] 恰好为 0.0**(OI 存量从来没测到过);[25][26] 有 **50 行为 null、23 行非空**(非空的是历史遗留,视图今天仍是 0 行)。`asset_embeddings` 表**没有** `measured_dims` / `source_completeness` 列 ⇒ 消费方无法按「实测维数」过滤存量向量。

## 3. 逐币覆盖(三种权重)

| 覆盖口径 | 币数 | 占币 | 票数 | 占票 | \|P&L\| 占比 | 净盈亏占比 | 该组净盈亏 | 该组 \|P&L\| |
|---|---|---|---|---|---|---|---|---|
| `asset_embeddings`(v3 + 7 天内) | 24 | 10.0% | 63 | 15.3% | 16.5% | 25.2% | $763.31 | $1,675.81 |
| `asset_flow_daily`(逐币最新行有 vec) | 104 | 43.2% | 177 | 43.1% | 38.1% | 41.2% | $1,244.66 | $3,871.36 |
| `asset_flow_daily`(同上且 ≤7 天) | 34 | 14.1% | 89 | 21.7% | 23.3% | 30.3% | $915.90 | $2,369.92 |
| `cis_official_daily`(有正式分) | 24 | 10.0% | 63 | 15.3% | 16.5% | 25.2% | $763.31 | $1,675.81 |
| 三者都有 | 24 | 10.0% | 63 | 15.3% | 16.5% | 25.2% | $763.31 | $1,675.81 |
| 任一有 | 104 | 43.2% | 177 | 43.1% | 38.1% | 41.2% | $1,244.66 | $3,871.36 |
| **都没有** | 137 | 56.8% | 234 | 56.9% | 61.9% | 58.8% | $1,778.48 | $6,288.74 |

口径说明:`asset_flow_daily` 的两行分别是「该币自己最新一行的 `vec` 非空」与「那一行距全表 `max_d` ≤ 7 天」。这张表**每天只写几十个币**(最新日 2026-11-15),用全表 `max_d` 当分母会低估到 34 币 —— 别用那个口径下结论。

**盈亏归属(结论 2 的硬数字)**:全窗 241 个币中 **103 个净赚、138 个净亏、0 个持平**;未覆盖组净 $1,778.48 / |P&L| $6,288.74(净利率 28.3%),覆盖组净 $1,244.66 / |P&L| $3,871.36(净利率 32.2%)。⇒ **两边都赚**,覆盖组只是**单位 |P&L| 的净利率更高**(32.2% vs 28.3%)。

## 4. 27 维逐维:依据**真实写端** `generate_embedding`(不是 `compute_full_vec` —— 仓里没有这个函数)

写端源码扫描(行号是本脚本实测的,不是记忆里的):

| 断言 | 文件:行 | 原文 |
|---|---|---|
| `def generate_embedding\(` | `embedder:235` | `def generate_embedding(` |
| `_missing = _NAN if unmeasured_as_nan els` | `embedder:281` | `_missing = _NAN if unmeasured_as_nan else 0.0` |
| `unmeasured_as_nan: bool = False` | `embedder:243` | `unmeasured_as_nan: bool = False,` |
| `^MIN_MEASURED_DIMS = ` | `embedder:584` | `MIN_MEASURED_DIMS = 10   # of ASSET_DIMS_V2 (27). Below this the row is not written.` |
| `^def measured_dims\(` | `embedder:587` | `def measured_dims(vec) -> int:` |
| `^def is_thin\(` | `embedder:599` | `def is_thin(vec) -> bool:` |
| `1e6` | `embedder:292` | `# below (mcap 1e6, changes 0, volume 0, ath 50) are reasonable for the live` |
| `ath_distance_pct` | `embedder:314` | `ath_dist  = float(asset.get("ath_distance_pct") or pillars.get("ath_dist") or 50) \` |
| `funding_rate` | `embedder:22` | `[11] clamp(funding_rate * 1000, -1, 1)  — Futures funding rate (0.01%/8h = 0.1)` |
| `oi_usd` | `embedder:259` | `derivatives : {symbol: {funding_rate, oi_usd}} pre-fetched derivatives map` |
| `^def upsert_embeddings\(` | `pgvector_store:123` | `def upsert_embeddings(embeddings: dict[str, list], *, asset_meta: dict \| None = None,` |
| `generate_embedding\(` | `vector_router:549` | `vec = generate_embedding(` |
| `asset_edge_moments` | `vector_router:482` | `"notes": "edge_moments (v2 dims 25-26) are filled server-side from the asset_edge_moments "` |

| 维 | 含义 | 数据来源 | 没有 CIS 能不能算 | 原因 |
|---|---|---|---|---|
| [0] | F/100 | CIS 引擎 pillar_F(cis_official_daily.pillar_f) | **否** | 支柱是打分结果,不是永续数据能推出的量 |
| [1] | M/100 | CIS 引擎 pillar_M(cis_official_daily.pillar_m) | **否** | 同上 |
| [2] | O/100 | CIS 引擎 pillar_O(cis_official_daily.pillar_o) | **否** | 同上 |
| [3] | S/100 | CIS 引擎 pillar_S(cis_official_daily.pillar_s) | **否** | 同上 |
| [4] | A/100 | CIS 引擎 pillar_A(cis_official_daily.pillar_a) | **否** | 同上 |
| [5] | cis_score/100 | cis_official_daily.cis_score | **否** | 总分的定义就是五支柱的加总 |
| [6] | log10(mcap)/15 | asset_mcap_daily.mcap(CoinGecko 市值) | **部分** | 永续合约本身没有市值;CoinGecko 有该币市值才能算 —— 库里是 market_chart 的历史市值 |
| [7] | chg_24h/20 | 日收盘(asset_mcap_daily.price / ohlcv_daily.close) | **是** | 永续日线收盘即可算(口径与现货收盘有差,见第 6 节实测) |
| [8] | chg_7d/50 | 同上 | **是** | 需要 ≥8 根日线 |
| [9] | chg_30d/100 | 同上 | **是** | 需要 ≥31 根日线 |
| [10] | min(vol/mcap×10,1) | asset_mcap_daily.volume ÷ .mcap | **部分** | 永续有成交额(面板 qv)但库里这一维的分子是现货 24h 成交额,口径不同 |
| [11] | clamp(funding×1000) | funding_history(venue=binance_perp).funding_rate | **是** | 资金费是永续原生量;库里 funding_history 覆盖多币(永续原生,与 OI 同一个 derivatives 映射) |
| [12] | oi/mcap×5 | OI 存量(CoinGecko derivatives,只在 CIS universe 内)÷ mcap | **部分** | 有 OI 存量 + 有市值才能算;我们库里只有 ΔOI(flow 表 doi7),没有 OI 存量 |
| [13] | (100−ath)/100 | ath_distance_pct(现货 ATH;永续代理=历史最高价) | **是(代理)** | 永续日线可算历史最高价,但与现货 ATH 口径不同,只能当代理 |
| [14] | las/100 | CIS 引擎 las | **否** | LAS 是打分产物 |
| [15] | confidence | CIS 引擎 confidence | **否** | CIS 引擎自评的数据完整度 |
| [16] | class_enc/10 | 资产清单映射(_CLASS_ENC) | **部分** | 加密默认 Crypto=0.8 可填;L1/L2/DeFi/… 子类要外部映射 |
| [17] | regime_alignment | 全局 macro regime(_REGIME_ALIGN) | **是** | 全局量,任何资产都能填 —— 非 CIS 依赖 |
| [18] | d_F | 连续两天的 pillar_F | **否** | 需要 CIS 支柱历史 |
| [19] | d_M | 连续两天的 pillar_M | **否** | 同上 |
| [20] | d_O | 连续两天的 pillar_O | **否** | 同上 |
| [21] | d_S | 连续两天的 pillar_S | **否** | 同上 |
| [22] | d_A | 连续两天的 pillar_A | **否** | 同上 |
| [23] | stability_O | pillar_O 历史序列 std | **否** | 需要 CIS 支柱历史(≥3 obs) |
| [24] | stability_S | pillar_S 历史序列 std | **否** | 同上 |
| [25] | edge_vol | asset_edge_moments 视图(写端 edge_moments 入参) | **否** | **写端未实现 / 视图无数据**:asset_edge_moments 实测 0 行 ⇒ 写出来是 NaN(存量行里少数非空是历史遗留) |
| [26] | edge_p10 | asset_edge_moments 视图(写端 edge_moments 入参) | **否** | 同上 |

**活路径动态探针**(脚本现造一个「没有 CIS / 没有市值 / 没有资金费 / 没有 OI」的资产喂给写端):

- 写端默认口径(`unmeasured_as_nan` 不传)实测:**18 维非空**,`measured_dims` = **18**,`is_thin` = **False** ⇒ 写端认为它「够厚」,直接进 `upsert_embeddings`。
- 同一资产用 `unmeasured_as_nan=True`:**7 维非空**,`measured_dims` = **7**,`is_thin` = **True**。
- 活路径 `vector.py` 的 `generate_embedding(...)` 调用**没有传** `unmeasured_as_nan`(实测:False)。

⇒ **写端 docstring 写的是「unmeasured is NaN, never 0」,活路径做的是「填默认值 0.0」**;两者不一致,且 `MIN_MEASURED_DIMS` 这道门槛在活路径上是惰性的(`upsert_embeddings` 不过 `is_thin`)。第一轮「非 CIS 币最多 10 维、卡在门槛上」的表述**对活路径不成立**。

## 5. 最小方案(只用库里已有的数据,不新建抓取器)

| 场景 | 达 10 维门槛的币数 | 逐币可测维数分布 |
|---|---|---|
| 仅 Supabase 库 | 0 | {'2': 41, '3': 25, '4': 3, '5': 1, '6': 2, '7': 71, '8': 98} |
| + Mac 永续日线面板 | 0 | {'6': 41, '7': 27, '8': 74, '9': 99} |
| + OI 存量(扩已有 derivatives 抓取器 universe) | 99 | {'7': 41, '8': 27, '9': 74, '10': 99} |
| + funding(DB 里 ≤7 天的,或 Mac 的 Hyperliquid 文件) | **170** | {'8': 65, '9': 6, '10': 170} |

**加完 OI + funding 之后,仍缺的维(逐币分组)**:

| 仍缺的维 | 币数 |
|---|---|
| 缺 [] | 170 |
| 缺 [6][10] | 65 |
| 缺 [10] | 6 |

现成源的覆盖(零新抓取器):

| 源 | 覆盖票源币 | 备注 |
|---|---|---|
| `um_daily(永续日线,Mac 数据根)` | 241 | /Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl |
| `ohlcv_daily(DB,最近 60d)` | 186 | 窗口外只查「最后一行日期」,不做逐行计数 |
| `asset_mcap_daily(DB,最近 60d)` | 176 |  |
| `funding_history(DB,任意时刻)` | 239 |  |
| `hyperliquid_funding(Mac 数据根,1h CSV)` | 43 | 与写端要的 Binance funding 不同场所;这是「口径差」不是「同一个量」 |
| `OI 存量` | 0 | 库里没有 OI 存量(只有 flow.doi7 的 ΔOI) |

**修掉第一轮的两个数字**:第一轮写「补 OI ⇒ 172 币达 10 维」是错的 —— 逐币实测:**补 OI = 99 币**,**再补 funding 才 = 170 币**(补 funding 净增 71 币);剩下 71 个币补不满(逐币分组见上表)。第一轮写「立刻可算 9 维」也只在 99 币上成立(其余币缺市值或资金费)。

**funding 算「实测」的门槛**:[11] 资金费算「实测」的门槛:DB 里最后一次结算距今 ≤ 7 天(写端要的是**当前**资金费,16 天前的旧值不算实测)。「补 OI」「补 funding」两个场景都是同一个假设:把**已有**抓取器的 universe 扩到票源币,不是新建抓取器 ⇒ 补 funding 后 [11] 对所有票源币都算可得。

**与 Seth §Seth-1113o 的 per_symbol 分组对账**:Seth 2026-11-13 的 per_symbol 分组(缺 [12] 100 / 缺 [11][12] 72 / 缺 [6][10][12] 26 / 缺 [6][10][11][12] 43)与本脚本「补 OI 后」的分组逐组相差 ≤2 个币(本轮实测:不缺 99、只缺 [11] 71、缺市值+成交量 65、缺市值+成交量+资金费 41);差在市值/成交量行取不取与 funding 新鲜度的口径边界,不影响结论 —— 两边都指向同一件事:补 OI 只让约 100 个币够门槛,补 funding 再加约 70 个,剩下约 70 个币缺市值/成交量,没有现成源。

补 OI 后(还没补 funding)的缺失维分组:

| 仍缺的维 | 币数 |
|---|---|
| 缺 [] | 99 |
| 缺 [11] | 71 |
| 缺 [6][10][11] | 41 |
| 缺 [6][10] | 24 |
| 缺 [10][11] | 3 |
| 缺 [10] | 3 |

## 6. 永续 / 现货口径差(实测)

同一币、同一天,永续面板收盘 ÷ 现货 `ohlcv_daily.close` − 1:126 个币可配对、1763 对;中位 **-0.003%**,|差| 的 P90 **23.846%**、最大 **6936.829%**;18 个币的日均 |差| > 1%。有向量的那 24 个币子集:中位 **-0.017%**、|差| P90 **0.097%**。

资金费的场所口径差(Binance 8h ×3/日 对 Hyperliquid 1h 日内求和):0 个币可配对,日均资金费差的中位 **0.0 bp**、P90 **0.0 bp**、最大 **0.0 bp**。⇒ 用 Hyperliquid 文件补 [11] 是**换了一个场所的量**,与写端要的 Binance funding 不是同一个口径。

## 7. 资金面:同口径对照(替换第一轮 §7 的错归属)

**第一轮 §7 降级**:第一轮写「向量与 CIS 描述的那 24 个币恰好在最弱的一档」—— `state_daily` 这四个量的 `entity` **全是 `panel`**(实测:breadth_above_ma50=0, mom_20=-0.193286819254406, oi_chg_30d=-0.200179676306053, funding_7d_ann=0.0274939779868275),是**面板级**不是币级 ⇒ 那句归属**不成立**,本轮不再作为结论,只保留面板级的读数。

同口径对照(实验组=有向量且当日有资金面的 21 个币;对照组=同日全体有资金面的币里按种子 20261117 抽 11 个;统计量=11 维当日截面百分位居中后的均值;零分布走 `apparatus.null_distribution`,分位走 `apparatus.percentile_of`):

| 项 | 值 |
|---|---|
| 截面日 | 2026-11-15(全表有 vec 的币 32 个) |
| 实验组 | 21 币:均值 0.0428 |
| 对照组 | 11 币:均值 0.0071 |
| 当日全体 | 均值 0.0305 |
| 实验组均值在零分布里的分位 | 0.755(零分布中位 0.0307,P05 0.0007,P95 0.0597) |

实验组逐币(当日截面分位):

| 币 | 资金面姿态均值 | 当日分位 |
|---|---|---|
| AVAX | 0.2848 | 0.98 |
| AAVE | 0.2305 | 0.92 |
| INJ | 0.2113 | 0.86 |
| LDO | 0.1851 | 0.83 |
| NEAR | 0.1469 | 0.80 |
| BNB | 0.1465 | 0.77 |
| BTC | 0.1339 | 0.73 |
| LINK | 0.0965 | 0.67 |
| PENDLE | 0.0932 | 0.64 |
| SUI | 0.0890 | 0.58 |
| ETH | 0.0578 | 0.55 |
| ADA | 0.0363 | 0.48 |
| POL | 0.0246 | 0.42 |
| DOT | 0.0052 | 0.39 |
| SOL | -0.0110 | 0.36 |
| ONDO | -0.1195 | 0.27 |
| APT | -0.1200 | 0.23 |
| STRK | -0.1224 | 0.20 |
| TIA | -0.1305 | 0.17 |
| OP | -0.1489 | 0.14 |
| ARB | -0.1909 | 0.02 |

**限制**:当日截面只有 32 个币(这张表每天只写几十个币)⇒ 对照组与总体高度重叠,只能读成描述性对比

## 8. 限制

- 覆盖统计只算「有没有」,没算「对不对」;向量质量不在本卡范围。
- 净盈亏占比在净值为负的子集上会翻转,本卡用 |P&L| 作主权重、净盈亏作副权重,两个都报了。
- `asset_flow_daily` 逐币最新行与全表 `max_d` 差距大(这张表每天只写几十个币),别用 `max_d` 当分母。
- 0 张未平仓票的 mtm 用 Mac 面板末根收盘(面板止于 2026-09-30),不是「今天」。
- 票源窗口本身止于 2026-09-29(`r_tickets_paper` 前向 0 行),本卡不外延。
- 「达门槛」是**按输入可得性**算的(输入齐 ⇒ 写得出来),不是跑写端实测;写端实测见第 4 节探针。

## 9. 探索性发现(**需另立预注册、在新数据上过零信号对照**)

- **探索性 —— 需另立预注册、在新数据上过零信号对照**:永续面板与现货收盘的日均差中位 -0.003%、|差| P90 23.846% ⇒ 若用面板给票源币算 [7][8][9][13],那几维与现有 59 个向量(现货口径)**不是同一度量**;混在一个相似度池里比,比的其实是两个价。
- **探索性 —— 需另立预注册、在新数据上过零信号对照**:写端把缺失字段填默认值(0.0 / 0.5)⇒ 存量向量里 [11][12][13] 的「看起来有值」其实可能是缺省值;34/73 行带这个缺省签名 ⇒ 任何以向量维度做的相似度/聚类,都含这层伪影。
- **探索性 —— 需另立预注册、在新数据上过零信号对照**:有向量的那 21 个币在当日资金面截面上的姿态均值 0.0428,零分布分位 0.755 ⇒ 方向上「有描述的币」并不明显更极端;样本只有 32 个币,读不出东西。
