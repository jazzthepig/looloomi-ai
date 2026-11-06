# T-264 —— S-742「谁在买」:场所成交份额对 BTC / 山寨之后 30 天

**结论:前提不成立 ⇒ 5 个检验一个都没跑(卡 acceptance ① 的停机分支)。**
交付的是**覆盖表 + 一次跑完的预注册实现 + 机器自测**;数据落行后一条命令重跑即可出结果。

- 卡:T-264(lane-a) · 台账:REFUTATION_LEDGER.md `S-742`(Seth,2026-11-06 08:36 UTC 预注册,写于回填完成之前)
- 脚本:`docs/research/t264_venue.py` · 结果:`docs/research/t264_results.json` · 自测:`docs/research/t264_selftest.json`
- 只读库,不写库,不改生产代码。零分布 / 分位只用 `src/data/evaluation/apparatus.py`
  (`null_distribution` 驱动循环平移、`percentile_of` 读分位);本卡无联合模型,不碰 `joint_model.py`。

---

## 1. 前提检查(卡 acceptance ①)

### 1.1 覆盖表 —— 四场所自 2021-03-01 起的逐日覆盖

`exchange_volume_daily` 的列名已探明:`d` / `exchange` / `kind` / `volume_btc`(CoinGecko Analyst volume_chart,BTC 计价)。

**该表在库中读出来 0 行**(`Prefer: count=exact` ⇒ `Content-Range: */0`;`select=d,exchange,kind,volume_btc` ⇒ `[]`),
所以没有任何一天可以计入覆盖:

| 场所 | 自 2021-03-01 起有数据的天数 | 应有天数 | 覆盖率 | 缺的天数 |
|---|---|---|---|---|
| gdax | 0 | 末日起算(表空,无末日) | 0.00% | 全部 |
| binance | 0 | 同上 | 0.00% | 全部 |
| upbit | 0 | 同上 | 0.00% | 全部 |
| binance_futures | 0 | 同上 | 0.00% | 全部 |

任一缺 > 5% ⇒ **停,不跑**。四条都缺 100% ⇒ 停。

### 1.2 视图侧同样为空

`feature_matrix_daily` 2,866 行(2019-01-01 → 2026-11-05):

| 项 | 实测 |
|---|---|
| `f` 里的 `venue:*` 键 | **0 个** |
| `has.venue = true` 的行 | **0 / 2866** |
| 三个预注册特征键的行数 | `venue:coinbase_share_spot30` 0 · `venue:korea_share_spot30` 0 · `venue:deriv_to_spot30` 0 |

### 1.3 这是「表还没落行」,不是「我的 key 读不到」

同一把 publishable key 在同一个库里读得到:`feature_matrix_daily` 2,866 行 · `ohlcv_daily` 1,531,626 行 ·
`cg_coin_mcap_daily` 497,674 行 · `perp_bv_daily` / `macro_daily` / `state_daily` 均正常。
外部佐证:`MINIMAX_SYNC.md`(11-06)记 `venue:*`「**回填中(还不能用)**」,并写明是 `exchange_volume_daily` 2021 起、约 8 轮。

### 1.4 顺带查出来的一件事(与卡字面不同,见 §3)

卡写「山寨价格用 `cg_coin_mcap_daily`」——**该表里没有 ① 面板 24 名中的任何一个主币**:
`coin_id=in.(bitcoin,ethereum,solana,binance-coin,ripple,litecoin,dogecoin,cardano,avalanche-2,aptos,sui,polkadot,uniswap,filecoin,cosmos,near-protocol,arbitrum,optimism,ethereum-classic,bitcoin-cash,tron)` ⇒ **0 行**。
那张表装的是新币 / 包装 / 跨链宇宙(`wrapped-bitcoin`、`usd-coin-ethereum-bridged`、`magic-internet-money-arbitrum` …)。
面板现货收盘只能取 `ohlcv_daily`(source=`binance_hist`,与 `core_cap.PRICE_SOURCE` 一致),覆盖 24/24:

BTC 2015-07-14→2026-11-05(7,806 行)· ETH 2015-08-07→ · SOL 2020-04-11→ · AAVE 2020-10-03→ ·
APT 2022-10-19→ · ARB 2023-03-23→ · SUI 2023-05-03→ ……(每个 symbol 的首末日都探过,全到 2026-11-05)

---

## 2. 已经交付的东西(数据落行后可直接跑)

`python3 docs/research/t264_venue.py`

| 阶段 | 内容 |
|---|---|
| 阶段 0 | 前提:四场所逐日覆盖(缺 > 5% ⇒ 停)+ 视图 `venue:*` 键清点 → 不成立就写 `t264_results.json` 并退出 |
| 阶段 1 | 特征:F1 = `venue:coinbase_share_spot30` − 自己过去 180 天均值;F2 = `venue:korea_share_spot30` 过去 365 天分位;F3 = `venue:deriv_to_spot30` 过去 365 天分位(只用 ≤ d) |
| 阶段 2 | 结果:BTC 永续(`perp_bv_daily`,symbol=BTC)d→d+30 对数收益 / d→d+30 最大回撤;山寨等权(① 面板除 BTC/ETH = 22 名)减 BTC 的 30 天对数超额 |
| 阶段 3 | 5 个检验(见 §4)+ BH(q = 0.10)+ 副项(7 天、链上永续份额只描述) |
| 自测 | `--selftest`:不碰市场数据,两条人造序列 |

### 2.1 机器自测(证明零分布这条路没坏)

10-14 的教训是「打乱是空操作 ⇒ 零分布 = 实际值 ⇒ 所有检验都过」。所以自测必须**同时**跑「有信号」和「无信号」:

| 人造序列 | IC | 预期方向分位 | BH q | 结论 | 期望 |
|---|---|---|---|---|---|
| 注入关系(outcome = 0.35·z(feature) + 噪声) | **+0.329** | **1.000** | **0.000** | PASS | PASS ✅ |
| 纯噪声(特征与结果各自独立) | −0.0004 | 0.495 | 0.505 | FAIL | FAIL ✅ |

⇒ **既能发现信号,也不会对噪声乱拒**。零分布(整体循环平移,平移量 ≥ 60 天,1,000 次,种子 742)、
`apparatus.null_distribution` 的「打乱没打乱任何东西」护栏、`percentile_of`、BH 都是通的。

---

## 3. 与卡 / 台账字面不同的地方(逐条写明,没有藏)

| # | 台账 / 卡的字面 | 本卡实际做法 | 为什么 |
|---|---|---|---|
| 1 | 山寨价格 `cg_coin_mcap_daily` | 改用 `ohlcv_daily`(source=`binance_hist`) | 实测该表 0 主币(§1.4);`ohlcv_daily` 24/24 覆盖 |
| 2 | 5 个检验里 F3 → BTC 30 天收益**没有写方向** | 该条按**双侧**判(`|IC|` 对 `|零分布|`),两段/残差只要求与全样本同号 | 台账没写方向就不能事后编一个;双侧比单侧更严(BH 下 p 要 ≤ 0.05) |
| 3 | 山寨等权 | 两端都有价的名字不足 22 名里的 80%(≥ 18 名)时,该日记为缺失 | 台账没写门槛;不猜、不用 0 充数 |
| 4 | — | `ohlcv_daily` 同一 symbol 有多个 source(BTC 7,806 行 ≈ 2 来源 × 4,100 天)⇒ 只取 `binance_hist`,同日去重 | 不取源会得到两个「同一量」 |
| 5 | 控制「BTC 过去 30 天收益」 | 用永续 BTC 的过去 30 天对数收益(只用 ≤ d) | 与结果侧同源 |
| 6 | 零分布 = 特征序列整体循环平移 | 平移算子写在脚本里,**机器与分位由 `apparatus.null_distribution` / `percentile_of` 出** | `apparatus.py` 里没有现成的循环平移函数(见 §6) |
| 7 | BTC → 山寨超额里减的那个 BTC | 减 `ohlcv_daily` 的 BTC 现货 30 天对数收益(与山寨同源) | 同源相减才是「相对」 |

---

## 4. 5 个检验(数据到位后按此跑,方向一字不改)

| # | 特征 → 结果 | 预期方向 |
|---|---|---|
| T1 | F1 → BTC 永续 30 天对数收益 | **正** |
| T2 | F2 → BTC 永续 30 天对数收益 | **负** |
| T3 | F2 → 山寨等权减 BTC 的 30 天对数超额 | **负** |
| T4 | F3 → BTC 30 天最大回撤 | **更深(更负)** |
| T5 | F3 → BTC 永续 30 天对数收益 | **未预注册 ⇒ 双侧** |

每条单独判,四条判据全过 + BH q ≤ 0.10(跨 5 个检验)才算 PASS:
(a) 全样本日度 Spearman IC 与预期同号且 |IC| ≥ 0.10;(b) 零分布循环平移 ≥ 60 天、1,000 次、种子 742,实际 IC 在预期方向的分位 ≥ 0.95;
(c) 两段(2021-03 → 2023-06 / 2023-07 →)同号;(d) 控制 BTC 过去 30 天收益后(秩回归残差)仍同号。

---

## 5. 还差什么

1. **`exchange_volume_daily` 落行**(gdax / binance / upbit / binance_futures,2021-03 起)—— 这是唯一挡住的东西。
2. 落行后跑 `python3 docs/research/t264_venue.py`:若视图 `venue:*` 仍无键,脚本会**从原始表自算**三个份额
   (口径写在 §2 与脚本注释里:近 30 天 gdax 现货量 ÷ 全部现货量 / upbit+bithumb 同口径 / 衍生品量 ÷ 现货量),
   并在 `t264_results.json` 里标 `feature_source = derived_from_raw`——属**偏离**,需要在报告里复核。
3. 结果出来后再按台账写结论段(Seth 合并后入台账;本卡没有 `REFUTATION_LEDGER.md` 权限,没动那个文件)。

## 6. 需要 @seth 的两件事

- **`apparatus.py` 里没有「循环平移」这个算子**。本卡把平移写在脚本内(驱动与分位仍走 apparatus),
  这是 S-742 明写的零分布定义;若 apparatus 该拥有它,建议**由 @seth 统一加**,不要每张卡各写一遍(与 10-14「不要自己再写一遍」同源)。
- **卡 T-264 的数据口径要改**:山寨价格不是 `cg_coin_mcap_daily`(表里没有主币),而是 `ohlcv_daily`(binance_hist)。
- 若回填在本卡交付后完成,叫醒 lane-a 重跑即可(脚本与参数都在分支上)。
