# T-284 / S-763 —— S-708「开闸是高位」在真实 Binance 现货上币公告日上的复现

> **状态:部分交付(事件清单已落盘并核对;主判据未算)。** 判据一字不改(照 S-708 / S-763):中位数 < 0 且随机日对照 ≤ 5 分位。
> 脚本 `docs/research/t284_listing.py` · 事件清单 `docs/research/t284_events.json` · 结果 `docs/research/t284_results.json`(未生成)
> 本轮被上下文守卫拦在取价阶段(见 §5),剩余动作见 §7。

## 0. 为什么要复现

S-708 ✅ 成立,但建在**代理事件源**上(`binance_hist` 首现日 = 上币日代理);公告当时 `events` 还没回填,
现在 `events` 有 1,474 条 Binance 上币公告。S-763 要求换成**真实公告日**重跑、判据不动。S-758 已证明
「补全事件映射后结论可能变强也可能变」—— 事件族要拿去做 ② / ④ 之前,必须先在真公告日上站住。

## 1. 口径(照 S-763 写死)

| 项 | 口径 |
|---|---|
| 事件 | `events` source=binance、kind=listing、payload.scope=**spot** |
| 代号 | `events.symbols`;空则补 `src/data/market/events.py:symbols_from_title`(T-277 那套解析) |
| 去重 | 同一代号 90 天内重复公告取**第一条** |
| d | 公告时刻(ts)所在 UTC 日 |
| 主口径收益 | d+1 → d+30(派生量挪一天,S-665) |
| 基准 | 同期 PIT 加密等权篮(照 S-708 / T-233 的算法 + 逐位自检) |
| 对照 | 同一符号随机起点 d,1,000 次,种子 **708**,统计量 = 各事件超额的中位数(`apparatus.null_distribution`) |
| 价格 | `asset_mcap_daily`(主)、`coingecko_pro_ohlc`(副);另跑 `binance_hist`(S-708 同源对照 + 代理事件校准) |
| 无价 | 公告后 10 天内没有价 ⇒ 无价 |
| 判据 | 中位数 < 0 **且** 随机日对照 ≤ 5 分位 ⇒ ✅;否则 ❌ |

## 2. 事件清单(先落文件,再取价)—— ✅ 已落盘

落盘:`docs/research/t284_events.json`(每条含 symbol / d / ts / 代号来源 / 标题;排除条目含代码)。
`events` 侧计数(`Prefer: count=exact`):

| 项 | 数 |
|---|---|
| `events` source=binance & kind=listing 总行数 | **1,474** |
| scope:spot / margin / alpha | 1,172 / 300 / 2 |
| `events.symbols` 非空(全部 scope) | 966 |
| **纳入(唯一代号,90 天去重后)** | **703** |
| 排除 | 1,052 = `no_symbol` 380 + `dup_within_90d` 370 + `scope_margin_not_spot` 300 + `scope_alpha_not_spot` 2 |

代号来源(按事件条数):`events.symbols` 792 条、标题解析 380 条(两条都空 → 排除)。
纳入事件年代分布:2017 35 · 2018 64 · 2019 41 · 2020 123 · 2021 128 · 2022 55 · 2023 41 · 2024 58 · 2025 86 · 2026 72。

**未解析标题样例(380 条 `no_symbol`)**:「Qtum Trading on Binance」「The Announcement for BCC Distribution」
「Binance Opens BNB/ETH Trading Market」「Binance Will Add USDT Market Soon(Updated)」「Binance Will List OMG Market」
「Binance Will List ZRX Market」「Binance will List STRAT Market」「Binance Lists SNGLS」。
未解析按年代:2017 68 · 2018 6 · 2019 22 · 2020 52 · 2021 14 · 2022 8 · 2023 32 · 2024 66 · 2025 56 · 2026 56。

**读法(诚实):** ① 覆盖缺口不是均匀的 —— 早期(2017:68 条)与近期(2024–2026:178 条)都丢;
② `kind=listing` 里混着**已上市代币的新交易对**与**空投/分发公告**(如上例),这类事件不是「新代币上币」,
它们在价格上几乎不跳 —— 机械按 S-763 规则纳入会稀释样本(下一轮必须按标题类别分层报,主口径照 S-763 不变);
③ 代号解析沿用 `src/data/market/events.py` 的官方解析器(T-277 同款),未自造新解析。

## 3. 价格源覆盖(已核对,取价进行中)

| 表 | 行数 | 日期覆盖 |
|---|---|---|
| `asset_mcap_daily`(主) | 756,980 | 2014-12-31 → 2026-11-06 |
| `ohlcv_daily` source=`coingecko_pro_ohlc`(副) | 104,670 | 2019-12-31 → 2026-11-06 |
| `ohlcv_daily` source=`binance_hist`(S-708 同源对照) | 446,541 | 2017-08-17 → 2026-11-06 |

## 4. 结果 —— ⬜ 本轮未算

主判据(30 天超额中位 / 随机日对照分位)、两段(2017–2022 / 2023–2026)、与代理事件的日期差分布、
PIT 篮逐位自检(向量化 vs `apparatus.long_return`)、代理事件校准(应复现 S-708 的 −18.03% / 分位 0.000)
全部**未算**,不得引用任何数字。

## 5. 本轮为什么停在这里

取价阶段(约 1,309 页 REST,每页 ≤1000 行、6 线程)启动后,上下文用量触发 lane 守卫(约 92k token),
只放行「改卡 / 写情景 / task_board / git」;再跑主脚本被拦。取价缓存写在 `docs/research/t284_cache/`
(**不入库**:大 JSON),若后台进程跑完则下一轮直接命中缓存,否则重取约 3–4 分钟。

## 6. 下一轮要做的(顺序固定)

1. `python3 docs/research/t284_listing.py`(取价 → 事件清单 → 三臂 + 校准 → `t284_results.json`)
2. 填本文件 §3/§4 的数字;把「已上市代币新交易对 / 分发公告」按标题类别分层另报(不改主口径)
3. 写 `docs/research/scenarios/lane-a-T-284.json`;卡 `status` → `in_review`;`task_board.py`;preflight;提交推送

## 7. 交付物清单

- `docs/research/t284_listing.py` —— 事件清单 / 取价 / PIT 篮 / 随机日对照 / 判据(一次跑完,`--events|--prices|--titles|--refresh`)
- `docs/research/t284_events.json` —— 事件清单(纳入 703 + 排除 1,052,含代号来源与排除代码)
- `docs/research/T-284_listing_replication.md` —— 本文件
