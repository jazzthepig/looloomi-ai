# T-270 —— S-747 复现:「持有人数增长越快、之后越跑输」在市值第 201–600 名上还在不在

**状态:装置与缓存审计已交付;(a)–(d) 本轮仍未跑 —— 不是「没过」,也不是「过了」。**
本轮把上一轮唯一的实质阻塞项(**asset_mcap.json 重复键**)消掉了,并把跑数命令
固化;真正跑数被 lane 的上下文护栏挡下(见 §5)。

- 卡:T-270(lane-a) · 台账:`REFUTATION_LEDGER.md` `S-747`(Seth,2026-11-06 14:45 UTC 预注册)
- 脚本:`docs/research/t270_holders_201_600.py` · 缓存:`/Volumes/CometCloudAI/cometcloud-local/research/t265/`
- 结果:`docs/research/t270_results.json`(四个槽位 null + 原因)· 情景:`docs/research/scenarios/lane-a-T-270.json`(4 条)
- 只读库,不写库,不改生产代码。零分布 / 打乱 / 分位 / 涨跌腿收益全走
  `src/data/evaluation/apparatus.py`(`null_distribution` / `shuffle_within` / `percentile_of` /
  `long_return` / `short_return`);本卡无联合模型,不碰 `joint_model.py`。

---

## 1. 判据(台账 S-747 原文,一字不改)

> **判据(全部满足才 ✅):** (a) 平均周截面 Spearman IC < 0 且 NW(4 阶)t ≤ −2.0;
> (b) g 最高五分之一减最低五分之一的平均 4 周超额 ≤ −1.0%;
> (c) 周内打乱 g(1,000 次,种子 747)实际均值 IC 分位 ≤ 0.05;
> (d) 两段(按周数对半)同号。

写死项:同一数据源与合并宇宙(`cg_coin_mcap_daily` ∪ `asset_mcap_daily`,BTC 基准
`ohlcv_daily` binance_hist)、同一过滤(上市满 26 周、去稳定币 / 包装 / 质押、|g| > 1 丢掉、
t − 28 与 t 的点相差 ≤ 7 天);**只换宇宙为当周市值第 201–600 名**;特征 = **原始 g**
(不取残差);周一调仓、4 周目标。

**为什么值得做**:T-265(S-743)的主检验是残差版 g_res,四条全不过;但**看过结果之后**发现
原始 g 的反向关系(未残差)更强(IC −0.038079 / t −1.6354 / 分位 0.000 / 两半同号负)。
那是看完数字才发现的,只能拿到**没看过的币**上复现才有意义 —— 第 201–600 名这条带
S-743 从没看过。

**预期方向**:S-743 台账给的是负(IC < 0)。但本卡**先验记为「不确定」**,理由是:
S-743 的原始 g 读数只有 IC −0.038、t −1.6354 —— 已在 (a) 的门槛(t ≤ −2.0)之下,
且 (b)(c) 未验。换了宇宙以后符号是否稳定,本身就是本次要测的东西;若结果翻正,
那是与 S-743 不一致,同样是要报告的发现,不是「挑一个好看的方向」。

---

## 2. 本轮的实质进展:缓存的重复键阻塞项已清除

上一轮(S-746 装置冻结时)审计发现:`asset_mcap.json` 358,853 行里只有 358,112 个唯一
`(coin_id, d)` 键 ⇒ **741 个重复键**,来源是 PostgREST 翻页边界漂移(**行数照样等于
`count=exact`,却少了约 741 个键**)。这是 §Seth-1106t 第 1 条「行数不能当完整性证据」
的实例,也是当时不敢开跑的原因:合并宇宙缺这些 (币, 日) ⇒ 第 201–600 名这条带的
边界每周会差几个币。

**本轮实测(直接读缓存文件,不是读上一轮的结论):**

| 文件 | 行数 | 唯一 `(coin_id, d)` 键 | 重复键 |
|---|---|---|---|
| `asset_mcap.json` | 358,112 | 358,112 | **0** |

⇒ 重复键已清零(上一轮记的 741 个不再存在)。**这个阻塞项解除。**

缓存目录里现在有:`asset_mcap.json`(42.0 MB,11-07 00:41 重写)、`cg_mcap.json`(36.8 MB)、
`bench_ohlcv.json`、`coverage.json`、`asset_mcap_early.json`、`cg_mcap_early.json`、
`asset_mcap_mondays.json`、`asset_mcap_onlyholders.json`,以及分片件 `asset1/2/3.json`、
`cg1/2/3.json`。脚本 `run` 需要的四个文件(`holders.json`、`coverage.json`、
`cg_mcap.json`、`bench_ohlcv.json`)齐全 ⇒ **不需要再跑 `fetch_assetmcap`**。

---

## 3. 装置(S-747 口径逐字对齐,已冻结)

`docs/research/t270_holders_201_600.py`,子命令 `fetch` / `run` / `report` /
`fetch_assetmcap` / `fetch_early` / `refresh` / `fetch_asset`。

- **取数**:分页读**全部带 `order=`**(12 处),每页 ≤ 1000 行,`Prefer: count=exact`;
  本地 CI `tests/test_research_paged_reads_have_order.py` 3 passed。
- **合并宇宙**:`cg_coin_mcap_daily` ∪ `asset_mcap_daily`(+ early / mondays / onlyholders
  增量合并,按 `(coin_id, d)` 去重)。
- **基准**:`ohlcv_daily` / `binance_hist` 的 BTC 收盘。
- **持有人**:`token_holders_daily`,按 (network, address) 分系列;`primary` 取最长系列,
  `total` 模式求和;t − 28 与 t 的点相差 ≤ 7 天才算有效。
- **g**:**原始 4 周持有人增长**(不取残差)。
- **周截面**:周一调仓、4 周目标;g 最高五分之一减最低五分之一 = 判据 (b)。
- **统计**:平均周截面 Spearman IC;NW(4 阶)t;周内打乱 g 1,000 次种子 747 的分位(判据 (c));
  按周数对半的两段同号(判据 (d))。
- **零分布 / 打乱 / 分位 / 涨跌腿**:全部走 `src/data/evaluation/apparatus.py`,不手写。

---

## 4. (a)–(d) 的原始数字

**本轮为空 —— 没有跑。** 不是「没过」也不是「过了」。

`t270_results.json` 的四个槽位仍是 `null`,原因是:上一轮被 lane 上下文护栏
(`scripts/lane_bot/guard_main_dir.py`)拦住,本轮同一护栏在约 102k token 处再次拦下
`run` 的启动(护栏此时只放行「改卡 / 写情景 / task_board / git 落地」)。
跑数本身预计只需几分钟(缓存已在本地,不打库),但护栏不看预计时长。

**下一轮一条命令(口径不变,脚本已就位,缓存已就绪,不要再跑 fetch):**

```
python3 docs/research/t270_holders_201_600.py run
python3 docs/research/t270_holders_201_600.py report
```

`run` 会把 (a)–(d) 与副项写进 `docs/research/t270_results.json`;`report` 落正文到本文件。

---

## 5. 副项(只报不判,尚未产出)

台账 S-747 的副项:控制过去 4 周收益后的残差版 g;8 周目标;前 200 名里同口径的数
(复述 T-265,对照用)。三者随 (a)–(d) 一起产出。

---

## 6. 口径偏离与待确认

① **市值源**:S-747 只写「当周市值第 201–600 名」,没写市值源;本卡按台账
「同一数据源与合并宇宙」取**合并宇宙**(`cg_coin_mcap_daily` ∪ `asset_mcap_daily`)的名次。
若台账要改成只算 `cg_coin_mcap_daily`,这条带的边界每周会差几个币 ⇒ 需返工。
**@seth 请裁定:用合并宇宙(现实现)还是只算 cg?**

② T-265 的 CHANGES(§Seth-1106t)第 1 条(取数带 order)已随 `lane-a/T-265-v2` 合并
(main 上的 `f283275e`);第 2 条「清缓存重取并重跑」尚未做;T-270 用的是同一份缓存目录,
两卡同源,建议 T-265 重跑与 T-270 开跑**同批**做,避免两次口径不同的重取。

③ T-264 那张卡的 `tasks/T-264.json` 曾含裸换行,严格 JSON 解析失败 ⇒
`scripts/task_board.py` 整板崩掉(不影响研究结果,但看板会停)。已在
`lane-a/T-264-v2` 上改回规范 JSON,`task_board` 恢复(269 张卡)。

④ **T-270 的 (a)–(d) 若与 T-265 前 200 的副项同向**,是否要把「原始 g 的反向」写进
台账 S-747 的结果段,还是先等 lane-b / lane-c 的交叉复核?**@seth 请给一句**。

---

*只读库、未入库、未改生产代码;零分布 / 打乱 / 分位 / 涨跌腿只走
`src/data/evaluation/apparatus.py`;本卡无联合模型,未触碰 `joint_model.py`。*
