# T-265 / S-743 — 持有人数增长(采用面)对之后 4 周相对 BTC 的超额,横截面周频

**轮次**:2026-11-06 lane-a · **状态**:前提未满足,**(a)–(d) 没跑**;交付的是检验装置(冻结)+ 前提数字 + 数据侧发现。
**预注册来源**:`REFUTATION_LEDGER.md` §S-743(Seth, 2026-11-06 08:36 UTC)——(a)–(d) 一字不改,写于回填完成之前、没看过任何一个持有人数。

---

## 0. 前提检查(卡 acceptance ①)

| 量 | 实测 | 门槛 |
|---|---|---|
| `token_holders_daily` 行数 | **0** | — |
| `token_holders_coverage` 行数 | **0** | — |
| 其中 `n_weekly ≥ 52` 的币数 | **0** | ≥ 80 |

⇒ **停,不跑**。表与视图都在 `public` schema(查不存在的表时 PostgREST 的 hint 回 `public.token_holders_daily`),`token_holders_daily` 的 RLS 已开但有 `lane_read … for select to anon using (true)`(见 `migrations/2026-11-06_token_holders_daily.sql`)⇒ **0 行是真空,不是 anon 权限被挡**。

表结构(迁移文件,已核对):`token_holders_daily(d, coin_id, network, address, holders, granularity, fetched_at)`,PK `(d, coin_id)`;`token_holders_coverage` 视图出 `(coin_id, min_d, max_d, n, n_weekly)`。

**写入端没找到**:仓库 `src/ scripts/ migrations/` 里没有 `token_holders_daily` 的写入端(只有 `data_layer.get_token_holders` 那个按地址查 Moralis 的旧接口,与此无关);Mac 根 `/Volumes/CometCloudAI/cometcloud-local/` 全树 grep `token_holders_daily` 也无命中。**要 @seth 指认回填的写入端与排期** —— 没有写入端,这张卡永远跑不了。

## 1. 交付:冻结的检验装置

`docs/research/t265_holders.py`(一个脚本,阶段:`cover` / `fetch` / `fetchfast` / `selftest` / `run` / `report` / `universe` / `scen`)。

口径逐条对照台账(写死成常量,`docs/research/t265_results.json` 的 `harness.prereg_params` 是同一份):

| S-743 原文 | 实现 |
|---|---|
| 每周一 t | 逐周一 |
| 宇宙 = 当周市值前 200 | `cg_coin_mcap_daily` 当周 mcap 排序取前 200 |
| 上市满 26 周 | 该币在 `cg_coin_mcap_daily` 的首个日期距 t ≥ 26×7 天 |
| 去掉稳定币/包装/质押衍生(相对 BTC 或 ETH 或 1 美元的 90 天波动 < 1%) | 90 天窗口日频对数收益的 σ:对 `ln(p/BTC)`、`ln(p/ETH)`、`ln(p)` 各算一次,**任一 < 1% 即去掉** |
| 持有人序列在 t−28 与 t 都有点(取 ≤ t 最近点,相差 ≤ 7 天) | 两个点分别取 ≤ t / ≤ t−28 的最近点,各自与目标日相差 ≤ 7 天 |
| g = ln(H_t / H_{t−28});\|g\| > 1 丢掉 | 同左,逐周丢 |
| g_res = g 对「过去 4 周对数收益」与「ln 市值」的横截面秩回归残差(每周单独回归) | 每周单独:三个变量各取横截面百分位秩,OLS(含截距)取残差 |
| 结果 = t → t+28 相对 BTC 的对数超额 | `ln(p_{t+28}/p_t) − ln(BTC_{t+28}/BTC_t)` |
| (a) 周横截面 Spearman IC 均值 > 0 且按周 t ≥ 2.0(Newey-West 4 阶) | 每周 Spearman IC → 均值;Newey-West HAC(Bartlett, lag 4) t 统计(本脚本自实现,仓库里没有现成的 HAC t) |
| (b) 前 1/5 减后 1/5 的平均 4 周超额 ≥ +1.5% | 每周按 g_res 排序取前/后五分之一,差 = 前档均值 − 后档均值(**同时报对数版与百分比版**,判据用百分比版) |
| (c) 每周内打乱 g_res,1,000 次,种子 743,实际均值 IC 分位 ≥ 0.95 | `apparatus.shuffle_within` + `null_distribution` + `percentile_of`(种子 743、1,000 次) |
| (d) 两段(按样本周数对半)同号 | IC 序列前后各半的均值同号 |
| 副(不判) | 原始 g(不取残差)、按 network 分、8 周目标(t+56):都实现,只报不判 |

零分布 / 打乱 / 分位 / 价格取值全部走 `src/data/evaluation/apparatus.py`(`shuffle_within`、`null_distribution`、`percentile_of`、`price_on_or_after`),没有另写一套。

**机器自检(合成面板,验代码通路 —— 不是证据)**:

| 用例 | 均值 IC | NW t | 置换分位 | 读法 |
|---|---|---|---|---|
| planted(fwd = 0.05·g + 噪声) | +0.5280 | 50.50 | 1.000 | 因子有信号时全部判据都过 |
| null(fwd = 纯噪声) | −0.0090 | −0.84 | 0.259 | 无信号时不过(分位 ~ 均匀) |
| ret_only(fwd = 0.30·ret4w + 噪声) | −0.0000122 | −0.005 | 0.497 | 秩回归确实把「过去 4 周收益」这一支剥掉了 |

## 2. 顺带查到的数据侧事实(会影响实现,已写进脚本)

1. **`cg_coin_mcap_daily` 里没有 BTC** —— 没有 `coin_id='bitcoin'`,只有 `wrapped-bitcoin` / `coinbase-wrapped-btc` / `renbtc` 这类包装币。而 S-743 的结果是「相对 BTC 的超额」⇒ 资产价用 `cg_coin_mcap_daily`、**BTC 基准只能取 `ohlcv_daily`**(`symbol='BTC'`;2026-11-05 收 76005(coingecko_pro_ohlc)/ 76088(binance_hist),2026-11-04 收 80444 / 80504)。台账没写死 BTC 用哪个源,这是实现选择,**要 @seth 认一下**(两源差异 < 0.1%,不敏感)。
2. `cg_coin_mcap_coins`(804 个币的 first_d/last_d/last_mcap)可以直接供「当周市值前 200」,不必要 `cg_coin_map` —— 后者对 anon 是 401 读不了。`token_holders_daily.coin_id` 与 `cg_coin_mcap_daily.coin_id` 同一命名空间(CoinGecko id),持有人↔价格连接不需要映射表。
3. `cg_coin_mcap_daily` 单源 `coingecko_pro_market_chart`,497,674 行 / 416,843 行 mcap 非空,2019-12-31 → 2026-11-05;另有一个 source 的行 mcap 为 null(该视图 `cg_coin_mcap_coins` 用 `where mcap > 0` 取,自动排除)。
4. 抓数速度:offset 分页在 40 万行上退化(O(n²),实测 ~5 万行后明显变慢),逐币抓(每币一页,300 个候选币)快得多 —— 脚本里两种都在(`fetch` / `fetchfast`)。

## 3. 还差什么(下一轮/下一位)

- **回填**:需要有人把 `token_holders_daily` 填上(CoinGecko Analyst Beta 的 `holders_chart`;周频历史 + 近 30 天日频)。门槛:≥ 80 个币有 ≥ 52 周周频。
- **跑法**(前提一过就一条命令,不改代码):
  ```bash
  python3 docs/research/t265_holders.py fetch && python3 docs/research/t265_holders.py run
  ```
  `run` 会把 (a)–(d) 的原始数字、置换分位、两段符号、副项(原始 g / 按网络 / 8 周)写进 `docs/research/t265_results.json`;前提不过则写 `"status": "STOPPED_PRECONDITION"` 并退出(不产生任何 (a)–(d) 数字)。
- **缓存落点**(Mac 数据根,不落 /tmp):`/Volumes/CometCloudAI/cometcloud-local/research/t265/`(本轮已建;`fetchfast.log` 里是逐币抓取的进度)。

## 4. 诚实边界

- 本轮**没有任何**持有人数被读过(表是空的),所以 (a)–(d) 的「事前性」没被破坏:预注册是 Seth 写的,装置是我照抄的,数据到了就能直接跑。
- 自检里的数字是合成面板上的,**不能当证据**,只证明代码通路是通的。
- 「稳定币/包装/质押衍生」的 90 天波动口径台账没给算法,本实现按「三个锚任一 σ<1% 即去掉」处理并在此写明;若与台账本意不同,改一行常量即可(阈值 `VOL_EXCL`)。
- (b) 的 +1.5% 门槛在「对数超额」上不好直接比,本实现同时给对数版与百分比版,判据取百分比版(若两版跨在门槛两侧,报告里会同时列出)。
