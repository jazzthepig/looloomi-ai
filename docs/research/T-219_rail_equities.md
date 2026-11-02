# T-219 — 轨道公司股权进宇宙的第一份研究:风险画像、与 ① / BTC 的关系、执行场所逐家判断

> lane-b(Minimax)· 2026-11-02 · 分支 `lane-b/T-219`
> 卡:`tasks/T-219.json` · 纪律:只读(SELECT / 公开 GET / 公开网页),不改代码、不做 DDL、不入库。
> 零分布 / 盈亏 / A-B 一律只走 `src/data/evaluation/apparatus.py`(`block_permute` / `shuffle_within` /
> `null_distribution` / `percentile_of` / `ab_test` / `stationary_bootstrap_index`),不另起炉灶。

---

## 0. 数据闸门:10 个轨道名字**一个都没有日线** ⇒ 风险画像等数据,本轮只测「并排」的老轨道

**测量时间:** 2026-11-02 08:3x–08:4x UTC · 库 = Supabase 研究库(只读 publishable key)
**方法:** `GET /rest/v1/<table>` 全部带 `order=`(翻页边界),计数用 `Prefer: count=exact`。
脚本:`docs/research/t219_db.py`(公共读取helper)、`docs/research/t219_counts.py`、`docs/research/t219_world50.py`、`docs/research/t219_probe_data.py`。

| 表 | 总量 | CRCL | COIN | HOOD | GLXY | MSTR | PYPL | XYZ | BLSH | FIGR | GEMI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `ohlcv_daily`(全部 source) | 1,509,138 行 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `asset_mcap_daily` | 753,580 行 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `world50_mcap_weekly`(列名 `key`) | 163,871 行 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

`ohlcv_daily` 按 source:`eodhd` 514,748 行 / `binance_hist` 445,866 / `yfinance` 91,162 / 其余
(`binance_hist_ffill`、`binance_um_hist`、`coingecko_pro_ohlc`)。**EODHD 通道本身是通的**(51 万行),
但 10 个轨道票**没有一个在里面** —— 卡面说的「11-02 加进周更、最晚 11-03 落库」在写这份报告时
**尚未落库**。

**同库可用、可作「并排」基线的:**

| 表 | 符号 | 行数 | 区间 | 备注 |
|---|---|---|---|---|
| `ohlcv_daily` | V / MA / BLK / IBKR / SCHW | 各 2,975 | 见 §2 实测 | 老轨道,有日线 |
| `ohlcv_daily` | QQQ / SPY | 各 5,726 | — | 基准 |
| `ohlcv_daily` | BTC | 7,768 | 2015-07-14 → 2026-11-01 | source: binance_hist / binance_um_hist / coingecko / coingecko_pro_ohlc / hyperliquid |
| `world50_mcap_weekly` | V / MA | 各 1,856 | 2015-01-02 → 2026-10-30 | 含 `shares`(621 行非空) |
| `world50_mcap_weekly` | IBKR / SCHW | 各 623 | 2015-01-02 → 2026-10-30 | 含 `shares`(621 行非空) |
| `world50_mcap_weekly` | BLK | 109 | 2024-11-08 → 2026-10-30 | 含 `shares`(107 行非空) |
| `core_cap_daily` | `cap_a1` / `cap_a05` / `ew_a0` | 各 31 | 2026-10-02 → 2026-11-01 | ① 的 NAV 代理 |
| `core_cap_daily` | **`cap_a1_u`** | **21** | **2026-10-12 → 2026-11-01** | 卡面指定口径;**只有 21 天** |
| `state_daily` | `stable_supply_30d` | 2,862 | 2019-01-01 → 2026-11-01 | 早期为 null;预注册假设的信号源 |

**两条读不到的东西(点名请 Seth 代查,本报告不推测):**
1. **①(`cap_a1_u`)的 NAV 历史只有 21 天**(2026-10-12 → 2026-11-01)。卡面要「按 2023-01 起与 2025 起
   两段」算**对 ① 的 β** —— 本仓做不到:长窗口的 ① NAV 不在 `core_cap_daily` 里。
   ⇒ **需要 Seth 代查:** ① 的完整日 NAV 是否在别处(`core_nav_daily` / Mac 根 / Railway 内部表)?
   本报告只给「对 BTC 的 β/相关」两窗口 + 「对 ① 的 β」在这 21 天窗口上的值,并标明窗口。
2. **10 个轨道票的 EODHD 日线还没落库** ⇒ 卡面「有数据的」分支(① 风险画像)本轮不适用。

**因此本轮的交付结构:** ① 风险画像 = **老轨道基线实测**(给下一轮当并排参照)+ 轨道票「等数据」;
② 执行场所逐家判断 = **本轮就能做**(公开页/公开 GET,与价格无关);③ **M-585 预注册**(写于算任何结果之前)。

---

## 3. M-585 预注册(写于算任何轨道结果之前,2026-11-02 08:45 UTC)

> 本节是**先写的**:提交 `docs/research/T-219_rail_equities.md` 的第一次提交(仅含 §0 数据闸门 +
> 本预注册)发生在**任何风险画像 / 场所判断 / 统计**之前。§1 风险画像与 §2 场所表是之后才写进去的。

> **M-585 (lane-b, 2026-11-02 08:45 UTC;PRE-REGISTERED before any result)—— T-219:轨道公司股权相对
> QQQ 的超额,与稳定币供应增速是否同向。**

**来源(写明):** Jazz 11-02「轨道公司股权进可投资宇宙(按发行方核验、不认代码)」。这条假设**不是**从
任何已算出的数字里提出来的 —— 本报告写作时 10 个轨道票**没有任何日线**(§0),所以它**不可能**是
「看了结果才提的」。理由是结构性的:轨道公司是加密世界的「轨道」(托管、清算、支付、持币),
稳定币供应是这轨道上的「燃料」;若两者真相关,轨道股的超额应当跟着燃料的边际变化走。

**面板(写死):** 10 个票 `CRCL, COIN, HOOD, GLXY, MSTR, PYPL, XYZ, BLSH, FIGR, GEMI` 的**等权价格指数**
(基期 = 面板首个可用交易日 = 100,每日再平衡等权,只用收盘价)。
**票的实际身份(待核,写在这里以便复核):** Circle / Coinbase / Robinhood / Galaxy Digital /
Strategy(前 MicroStrategy)/ PayPal / Block(前 SQ)/ Bullish / Figure / Gemini。
**纳入口径:** 在窗口起点有 ≥ 60 个交易日历史的票才进该窗口(固定规则,不许逐窗挑票)。
**基准:** QQQ(`ohlcv_daily`,源同 EODHD 通道)。

**信号(写死):** `S(m)` = `state_daily` 里 `feature = stable_supply_30d` 在**月末**的值
(30 日稳定币供应增长;该表 2019-01-01 起,早期为 null, null 当缺失、不插值)。

**结果(写死):** `E(m)` = 轨道面板与 QQQ 的**月度对数超额** = ln(面板指数 m→m+1) − ln(QQQ m→m+1)。
同期相关用 `ρ(S(m), E(m))`;领先用 `ρ(S(m), E(m+1))`。

**发现段(探索,机械):** 面板可用历史的前 **60%**(按交易日数切,切点日期在跑的时候如实记下,
**不许我挑**)。每个变体报告:Spearman ρ、ρ 的 t 值、`S` 高的月份 vs 低的月份(上中位 vs 下中位)的
`E` 均值差。**过发现段的条件:** ρ > 0 且 t ≥ 2.0(任一变体)。
**留出段(一次性):** 面板可用历史的**后 40%**。只检验过了发现段的变体(个数记为 k,≤ 2):
① ρ > 0,**3 个月一块的块自助 2,000 次**单侧 p < 0.05 / k;② 上中位 − 下中位的 `E` 均值差 > 0。
**两条都过 ⇒** 「轨道股超额随稳定币供应走」进候选(另立前向预注册);不过 ⇒ 记档,不动宇宙。

**零信号对照(必跑,写死):** 把 `S` 的**时间顺序**用 `apparatus.py` 的 `block_permute`(块长 = 3 个月)
打乱 2,000 次,重算 ρ 得到零分布,`percentile_of` 给出 p。**观测必须超出零分布的 95 分位**
—— 否则判「不过」。同时跑 `shuffle_within` 作为第二种打乱(月份内打乱)对照,两者结论不一致 ⇒ 记「不稳」。

**试验计数:轨道族第 1 次;发现段 2 个变体(同期 / 领先 1 月)为探索;留出段 k ≤ 2。**
**数据前置条件:** 10 个票的 EODHD 日线落库(否则本条留空,不估、不代)。

---
