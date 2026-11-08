# T-309 / S-789 —— S-753 在逐句解析之后重量:打上监控标签的代号 80 → 137

**lane-b · 2026-11-09 · 只算、不入库、不改生产代码**

---

## 0. S-789 预注册原文(照抄,只算一次)

> **S-789 — S-753 在逐句解析之后重量:打上监控标签的代号 80 → 137(预注册,Seth,2026-11-08 14:50 UTC;新加的 57 个代号一个价都没看过;交 B 道 T-309)**
>
> **为什么。** S-753 的事件集来自 v1 整行解析,漏掉了 43 次「打上」;硬规则已按 Jazz 的拍板前移,但它的证据要建在正确的事件集上。
>
> **写死:** 口径逐字照 S-753 与 `docs/research/t274_monitoring.py`(同一价格源、同一对照 [d0 − 365, d0 − 60] 随机 200 日、同一判据 (a)–(e)),只换事件:每个代号**第一次**出现在某条公告的「打上」句里(`events.monitoring_tag_changes(title)["add"]`,2023-07-26 起)。报:新旧事件集的差、有价个数、(a)–(e) 逐条;新增的那批单独的中位。**后果:** 全过 ⇒ S-753 在正确事件集上站住;(a) 或 (c) 不过 ⇒ 向 Jazz 报「硬规则前移的证据变弱」,规则是否保留由他再定。**试验计数:复算(数据修复),不计。**

**结果一句话:✅ 全过。** 事件集从 80 → **137**(新增 57,一个没丢),主口径 30 天相对 BTC 超额中位 **−15.78%**,对照分位 **0.005**,(a)–(e) 五条全过 ⇒ S-753 在正确事件集上站住,硬规则「打标签即剔除」的证据**没有**变弱。

---

## 1. 改了什么、没改什么

| | T-274(S-753,旧) | T-309(S-789,本卡) |
|---|---|---|
| 事件定义 | `events` 里 kind=monitoring_tag 的公告,用 **v1 整行解析**取代号 | **同一条公告**,但代号取 `monitoring_tag_changes(title)["add"]` —— 逐句,v2 生产解析器 |
| 扫的公告 | 只扫 kind=`monitoring_tag`(18 条) | 扫 kind ∈ {`monitoring_tag`, `monitoring_tag_removed`}(27 条,全部) |
| 价格源 | `asset_mcap_daily`(主)/ `ohlcv_daily` source=`coingecko_pro_ohlc`(交叉源) | **一字未改** |
| 对照 | 同代币 [d0−365, d0−60] 随机 200 日,seed 20261108 | **一字未改** |
| 窗口 / 锚点 | 30 天主、7 天副;d0 = 公告 ts 的 UTC 日 | **一字未改** |
| 判据 | (a)–(e) | **一字未改** |

脚本:`docs/research/t309_monitoring.py`(= `t274_monitoring.py` 逐行复制,只改 `phase_screen` 的事件集 + 加一段分组统计)。
事件清单:`docs/research/t309_events.csv`(137 行);结果:`docs/research/t309_results.json`。

```bash
python3 docs/research/t309_monitoring.py screen   # → t309_events.csv + t309_screening.json
python3 docs/research/t309_monitoring.py prices   # → t309_price_cache.json
python3 docs/research/t309_monitoring.py stats    # → t309_results.json
```

---

## 2. 新旧事件集的差

```
旧事件集(v1,t274_events.csv)   80 个代号
新事件集(v2 逐句)             137 个代号
只在旧集                        0 个   ← 旧集是新集的真子集,没有「修好解析器反而丢了」的
新增                           57 个
d0 变了的代号                    0 个   ← 新增代号没有一个抢在旧代号前面改变 d0
```

**为什么旧集少 43 次「打上」:** 库里 `kind` 是入库时用 **v1 整行解析**打的。v1 看到标题里出现 "Remove" 就把整条公告判成 `monitoring_tag_removed` —— 而这些标题恰恰是
「Extend the Monitoring Tag to Include A, B … , **Remove the** Seed Tag for C」这种一句里既有加又有减的。
于是 27 条监控标签公告里有 **9 条**被 v1 判成 `monitoring_tag_removed`,t274 只扫 `kind=monitoring_tag`,这 9 条里的「打上」句整条漏掉:

| 公告日 | 库里 kind | v2 解析出的「打上」个数 | 标题(截断) |
|---|---|---|---|
| 2024-01-04 | monitoring_tag_removed | 10 | Extend the Monitoring Tag to Include ANT, FIRO, KP3R, MDX, MOB, REEF, VAI, XMR, ZEC & ZEN, and Remove the Seed Tag for … |
| 2024-07-01 | monitoring_tag_removed | 11 | Extend the Monitoring Tag to Include BAL, CTXC, CVP, CVX, DOCK, HARD, IRIS, MBL, POLS, SNT & SUN and Remove the Monitoring Tag for … |
| 2024-10-03 | monitoring_tag_removed | 5 | Extend the Monitoring Tag to Include BLZ, CLV, KEY, PROS & VITE … |
| 2025-01-02 | monitoring_tag_removed | 2 | Extend the Monitoring Tag to Include STMX & TROY … |
| 2025-04-03 | monitoring_tag_removed | 10 | Extend the Monitoring Tag to Include ARDR, BSW, FLM, LTO, NKN, PDA, PERP, VIB, VOXEL & WING … |
| 2025-10-09 | monitoring_tag_removed | 1 | Extend the Monitoring Tag to Include WAN … |
| 2026-03-06 | monitoring_tag_removed | 9 | Extend the Monitoring Tag to Include COS, DEGO, FORTH, FUN, HOOK, LRC, MBOX, OXT & WIF … |
| 2026-04-14 | monitoring_tag_removed | 7 | Extend the Monitoring Tag to Include FARM, HIGH, MLN, RESOLV, SYS, TRU & VELODROME … |

(另 1 条 2024-04-03 在旧集里,因为它标题里没有 "Remove"。)

**新增的 57 个代号**(全部来自上表):
ANT ARDR BAL BLZ BSW CLV COS CTXC CVP CVX D DEGO DOCK FARM FIRO FLM FOR FORTH FUN HARD HIGH HOOK IRIS KEY KP3R LRC LTO MBL MBOX MDX MLN MOB NKN OXT PDA PERP POLS PROS REEF RESOLV SNT STMX SUN SYS TROY TRU VAI VELODROME VIB VITE VOXEL WAN WIF WING XMR ZEC ZEN

> 代号本身**逐个核对过标题**,没有解析垃圾:`FOR`=ForTube、`HIGH`=Highstreet、`D`=原 DAR、`PERP`=Perpetual Protocol,都是 Binance 真代号;其余为常规代号。

**有价个数(主源 `asset_mcap_daily`):**

| | 代号总数 | 有价 | 无价 |
|---|---|---|---|
| 新事件集 | 137 | **60** | 77 (56%) |
| 旧事件集 | 80 | 36 | 44 (55%) |
| 新增那批 | 57 | **24** | 33 (58%) |

交叉源 `ohlcv_daily`(`coingecko_pro_ohlc`):全集 n = 28;旧集 n = 18;新增那批 n = 10。

---

## 3. 判据 (a)–(e) 逐条(主源 `asset_mcap_daily`)

| 判据 | 门槛 | T-309(137) | 旧 S-753(80) | |
|---|---|---|---|---|
| (a) 30 天超额中位 | ≤ −5% | **−15.78%** | −18.28% | ✅ |
| (b) 超额为负的比例 | ≥ 60% | **75.0%**(45/60) | 80.6% | ✅ |
| (c) 对照分位 | ≤ 0.05 | **0.005** | 0.010 | ✅ |
| (d) 按事件日期对半分两段 | 中位同号 ∧ 每段 ≥ 10 | 早 **n=30 −12.15%** / 晚 **n=30 −22.45%** | −15.7% / −20.8%(各 n=18) | ✅ |
| (e) 有价代币 | ≥ 30 | **60** | 36 | ✅ |

**判据全过 ⇒ PASS。**

**完整分布(全集,n = 60):** 中位 **−15.78%** · 均值 **−17.24%** · p10 **−65.31%** · p90 **+12.14%** · 为负 75.0%。
去掉最负的 1 / 2 / 3 / 5 个后中位 −14.88 / −14.79 / −14.70 / −13.40% ⇒ 不是极端值撑起来的。

**对照(null,同代币 [d0−365, d0−60] 随机 200 日,seed 20261108):** 零分布中位分位 q05 −12.39% / q50 −8.66% / q95 −4.58%;实测中位 **−15.78% 落在 q05 之外**,分位 **0.005**(200 次抽样里只有 1 次比实测更差)。

**交叉源(`coingecko_pro_ohlc`,n = 28):** 中位 **−22.20%** · 均值 −29.70% · p10 −68.63% · p90 +2.61% · 为负 85.7% · 对照分位 **0.000**。方向与主源一致。

---

## 4. 新增那批(57 个)单独的中位

| 组 | 代号 | 有价 | 30 天超额中位 | 均值 | p10 | p90 | 为负 |
|---|---|---|---|---|---|---|---|
| **新增那批** | 57 | 24 | **−12.33%** | −10.95% | −51.06% | +9.20% | 66.7% |
| 旧集那 80 个 | 80 | 36 | −18.28% | −21.43% | −70.57% | +18.59% | 80.6% |
| 全集 | 137 | 60 | −15.78% | −17.24% | −65.31% | +12.14% | 75.0% |

新增那批去掉最负的 1 / 2 / 3 / 5 个后中位 −11.26 / −8.90 / −6.55 / −6.08%(方向不变,量级随尾部削减明显 ⇒ 这批的尾部比旧集薄)。
交叉源下新增那批 n = 10,中位 **−33.45%**,为负 80%。

**读法:** 旧集那 80 个的 −18.28% **不是**靠被漏掉的 43 次「打上」撑起来的 —— 新增那批单独也是负的(−12.33%,66.7% 为负),但**比旧集那批弱**(中位浅 5.9pp、为负比例低 14pp)。
即:**修好解析器之后效应仍在,但边际强度下降;样本从 36 涨到 60,结论的精度上升,效应量下降。**
两批都负 ⇒ 结论方向不变;新增那批更靠近 0 ⇒ (a) 的裕度从 −18.28% 缩到 −15.78%(仍远在 −5% 门槛外),(b) 从 80.6% 掉到 75.0%(仍在 60% 上方)。

---

## 5. 副项(只报不判,口径照 T-274)

- **打标签后 180 天内被宣布整币下架:79 / 137 = 57.7%**(任何时候 103 / 137 = 75.2%)。旧集:45/80 = 56%(任何时候 67.5%)⇒ 新增那批的下架率与旧批一个量级(57.7% vs 56%)。
- **硬规则前移实际吃到的那一段**(打标签 → 下架公告):n = 48,超额中位 **−41.39%**,均值 −45.26%,p10 −85.17%,p90 −13.32%,**93.75% 为负**;中位相隔 **61 天**。旧集(T-274):n = 28,中位 −41.4%,89% 为负,中位 62 天 ⇒ **几乎一模一样**,前移能躲开的那一段没变。
- **标签被移除之后 30 天**:n = 5(可算),中位 −24.27%。
- **按打标签前市值三分位**(全集):低市值三分位 n = 19 中位 **−23.64%**(89.5% 为负)· 中位三分位 −16.67% · 高市值三分位 **−6.55%**(63.2% 为负)⇒ **市值越小越差**,与 S-753 同向。
- **公告前的先行**:打标签前 30 天超额中位 **−20.97%**(86.7% 为负);公告当天跳空中位 **−10.02%**(86.7% 为负);7 天超额中位 −5.94%(63.3% 为负)。
  ⇒ 标签是**滞后信号**:跌在打标签之前就开始了,打标签当天还在跌。

---

## 6. 诚实与局限

1. **无价 77 / 137 = 56%。** 而 S-753 已指出:无价的那批里很大比例很快被下架 ⇒ **幸存者偏差**,真值大概率**更负**,不是更浅。
2. **新事件集只多了「打上」,没动 d0。** 137 个代号的 d0 与旧集完全一致(0 个变化),所以新旧对比里**没有**「事件日期前移」这个混淆因素 —— 差异纯粹来自样本扩大。
3. **对照分位 0.005 = 200 次抽样里的最低一档。** 分辨率到顶了(再要更细得加抽样数);结论方向不依赖这个分辨率,但 (c) 的具体数值不要再往下解读。
4. **新增那批的 24 个有价样本仍然小**,中位 −12.33% 的置信区间宽;它「比旧批弱」这个读法是描述性的,不是判据。
5. **本卡是复算(数据修复),不是新假设** —— 试验计数不增加(S-789 原文口径)。
6. 事件集完全由**生产解析器** `src/data.market.events.monitoring_tag_changes` 产出;本卡**没有改任何生产代码**。

---

## 7. 结论与后果

- **S-753 在正确的事件集上站住。** (a)–(e) 全过,判据值与旧口径同一量级,新增那批单独也是负的。
- **按 S-789 预注册的后果条款:「全过 ⇒ S-753 在正确事件集上站住」** —— 不触发「向 Jazz 报硬规则前移的证据变弱」那一条。**规则保留与否仍是 Jazz 的决定**,本卡不代拍。
- 边际信息:**硬规则前移能躲开的那一段(打标签 → 下架公告,中位 61 天、−41.4%)在新事件集上完全没变** —— 这正是硬规则要保护的那一段,证据最硬。
- **诚实的一处减弱:** 效应量从 −18.28% 变成 −15.78%,为负比例从 80.6% 变成 75.0%。方向与显著性都没问题,但如果 Jazz 想引用一个数,应该引 **−15.78%(n = 60)**,不是旧的 −18.28%(n = 36)。

---

## 8. 产物

| 文件 | 内容 |
|---|---|
| `docs/research/t309_monitoring.py` | 复算脚本(只换事件) |
| `docs/research/t309_events.csv` | 137 个代号的首次「打上」事件(先落文件,再取价) |
| `docs/research/t309_screening.json` | 公告级切句结果 + 新旧差 |
| `docs/research/t309_price_cache.json` | 价格缓存(**不入库**,照 T-274 的做法 —— 10.8 MB,`prices` 阶段可重跑生成) |
| `docs/research/t309_results.json` | 全部统计(逐代号 + 判据 + 副项 + 分组) |
| `docs/research/scenarios/lane-b-T-309.json` | 前向预期(5 条) |

合规:本报告只用定位语言(OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT);描述的是**已发生的历史结果**,不是买卖建议,不是预测。
