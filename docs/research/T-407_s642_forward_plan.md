# T-407 · S-642(熊市空头臂)前向化清单

> 只写清单,不含生产代码、不改库、不下结论(不判断 S-642 值不值得前向)。
> 每条事实都给出处;**没核实的地方写「未核实」**,不当成已知。
> 规则出处:`docs/research/t159_bear_short.py`(研究实现,逐行照抄 `docs/research/s642_bear_short.sql`),
> 票本与曲线:`docs/research/t348_r3_families.csv` + `docs/research/t348_r3_results.json`,
> 生产侧闸门与纸面空头臂:`src/data/signals/short_paper.py`。库里最新行是 2026-11-15 用只读 key 查的。

## 0. 一句话

S-642 = 「**majors 闸门关** + 个币收盘跌破前 40 日低 + 收在 200 日线之下 + 量能放大」→ 次日开盘开空、
止损 = 进场价 + 2.5×ATR14、最多持有 120 根 K 线(止损 / 收回 20 日线出场);每票 0.5% 净值、最多同时 10 张、
逐日盯市复利。241 张票,进场 2022-01-21 → 最后出场 2026-09-07;族曲线 1733 天(2022-01-21 → 2026-10-19),
终值 1.0175906660151923(总收益 +1.3868%,CAGR 0.29%,年化波动 5.38%,最大回撤 −11.42%,
峰 2022-11-09 / 谷 2024-10-15)。**族曲线不含资金费**(S-642 原文把资金费单列在 R 里)。

## 1. 开票 / 管票 / 出场:逐条规则

| # | 环节 | 规则(逐字) | 出处 |
|---|---|---|---|
| 1 | 宇宙 | 信号日往前满 220 根;ATR14 > 0;ADV30(30 日美元额均值)≥ 5e6;(HH40−LL40)/HH40 ≤ 0.40;当日美元额 ≥ 2 × 前 40 日均额(不含当日) | `t159_bear_short.py: _universe()`、`indicators()` |
| 2 | 指标 | sma20 / sma200 / atr14(TR 用前收)/ adv30 / adv40p / hh40 / ll40(前 40 日高低,不含当日)/ mindd120(对 365 日最高价的 120 日最小回撤) | `indicators()` |
| 3 | 信号(空) | close < LL40 且 close < SMA200 且 **闸门关**;`mindd120` **没有**空头镜像(写规则时还没做那个检验) | `sig_short()` |
| 4 | 闸门 | `style_index_pit_daily`(style=majors, weighting=cap)的日收益逐日复利成 level;level ≤ **自身 200 日均值** ⇒ 关;样本 < 200 天 ⇒ 开 | `load_gate()`;生产同款:`src/data/signals/short_paper.py: gate_closed_by_day()` |
| 5 | 进场 | 信号日收盘后,**下一根 K 线开盘**成交(entry = open[i+1]) | `run_short()` |
| 6 | 止损 | stop = entry_open + 2.5 × ATR14(**信号日**那根);触发那根若 open ≥ stop 按 open 成交,否则按 stop 成交(同日即进场那根则按 stop) | `run_short()` |
| 7 | 出场 | 持有中自进场日起最多 120 根:先到者为准 —— high ≥ stop ⇒ 止损出场;close > SMA20 ⇒ **次日开盘**出场;都没有 ⇒ 时间出场(到第 120 根收盘) | `run_short()` |
| 8 | 串链 | 同一 symbol 的票按进场序串起来:后一张的进场必须晚于前一张的出场,重叠的票被丢掉 | `_chain()` |
| 9 | 仓位 | 每票风险 0.5% 净值(f=0.005);同时最多 10 张;逐日盯市(标记 = 不晚于当日最后一条收盘);复利 | `nav()`;参数见 `t348_r3_results.json` meta(risk_frac 0.005 / cap 10) |
| 10 | 成本 | 0.4%(双边),以价格计:R = (entry−exit)/(stop−entry) − 0.004×entry/(stop−entry) | `run_short()` |
| 11 | 成本口径 | `nav()` 里成本**始终是借记**(abs(units));2026-10-25 之前写成 `units×(…−cost)`,空头(units<0)会变成 0.4% 的**贷记** —— 复刻必须用当前口径 | `nav()` 注释 |
| 12 | 资金费 | 不进这条族曲线(S-642 原文单列在 R) | `t348_graveyard.py: family_s642()` 注释 |

**前向化时必须写死的三个歧义点**(研究里的默认做法,列出来让人拍板):
① 同一根 K 线里 stop 与 sma20 都触发 → 研究里 **stop 优先**;
② 资金费要不要进前向账本(进了就不能和族曲线直接比,得另出一条含资金费的基准);
③ 进场当日(entry 那根)就打到 stop ⇒ 按 stop 价成交(不按开盘价)。

## 2. 输入 → 生产库的表 / 列 / 每天几点可用

| 用途 | 表 | 列 | 库里最新一行(2026-11-15 查) | 可用时点 |
|---|---|---|---|---|
| 全部指标(开票/管票) | `ohlcv_daily`(source='binance_hist') | trade_date, open, high, low, close, volume, symbol, recorded_at | trade_date=2026-11-14,recorded_at=2026-11-15T00:10:16Z;共 447,621 行 | D 的日线在 D+1 约 00:10 UTC 入库(recorded_at 实测这一行) |
| 闸门 | `style_index_pit_daily`(style='majors', weighting='cap') | d, ret, level, computed_at, members… | d=2026-11-14;共 2,510 行 | D 的行在 D+1 落库(带 computed_at;**具体钟点未核实**) |
| 资金费(可选,R 分支) | `funding_history`(venue='binance_perp') | symbol, funding_time, funding_rate, venue | funding_time=2026-11-15T00:00:00Z;共 2,658,464 行 | 每 8 小时一条结算记录 |
| 纸面空头账(可复用) | `short_paper_tickets` / `short_paper_state` / `short_paper_money` | 由 `src/data/signals/short_paper.py: WRITES_TABLES` 声明 | — | 与生产循环同拍 |

**研究里用了而库里没有 / 口径不同的**:
- 研究的历史 bar 来自两个本地缓存:`T159_DIR` 的 `_bars.jsonl`(Mac 数据根 `research/t159/`)与 **T156 的 `_bars_early.jsonl`**(2018 → 2025-04,为了 SMA200/ATR 的 warm-up 不从 2025 重来)。生产回放没有这一步 → **必须先查 `ohlcv_daily`(binance_hist) 最早覆盖到哪一天**,否则 warm-up 长度变了票数就会变。
- 宇宙筛选用的「美元额」研究里自己算 `close × volume`;库里 `volume` 是币量 → 生产要明确用 close×volume。
- 闸门的 level:研究是从 `ret` 逐日复利、且先过滤 `ret is not None and ret > -0.95` 再复利;生产 `gate_closed_by_day()` 是否同一过滤、同一复利起点 **未核实**。
- 研究排除了 `USDC / BTCDOM / DEFI`(`EXCL`);生产宇宙要显式写这条排除。
- 研究里 bars 是现货/合约混在 `ohlcv_daily` 的 symbol 命名里;`funding_history` 里 Binance 有前缀名(1000SHIB 之类),研究用 `_alias()` 桥接 → 生产查询要有同样的别名表。

## 3. 生产内核最小要几个纯函数

1. `indicators(rows) -> dict` —— 入参 `rows=[(d,o,h,l,c,dollar_volume)]`(按 d 升序);返回 sma20/sma200/atr14/adv30/adv40p/hh40/ll40/mindd120/close/open/high/low/date。纯函数、无 IO。
2. `universe_ok(ind, i) -> bool` —— 五条宇宙条件(读 indicators 的产物)。
3. `gate_closed_by_day(style_rows) -> dict[d, bool]` —— **已经有了**:`src/data/signals/short_paper.py`。复用,别重写(重写就会有两个闸门,以后必然分叉)。
4. `signal_short(ind, i, gate) -> bool` —— close<ll40 且 close<sma200 且 gate[d]。
5. `open_ticket(ind, i, d_to) -> dict|None` —— 进场/止损/出场扫描(≤120 根)→ 一张票(字段:symbol, signal_d, entry_d, entry_px, stop_px, exit_d, exit_px, exit_reason, bars_held, still)。
6. `chain(tickets) -> list` —— 同 symbol 去重叠,按进场序。
7. `mark_to_market(tickets, marks, f=0.005, cap=10) -> list[(d, equity)]` —— 逐日盯市复利 + 成本借记 + 名额上限。
8. (可选)`funding_pnl(tickets, funding) -> dict[d, float]` —— 只在决定把资金费进账本时才需要。

最小集 = 1、2、3、4、5、7 六个;其中 3 已经在生产里。5 与 7 是最该写成纯函数的两块(其余都只是查表)。

## 4. 一致性检验怎么做

- **对哪条曲线**:`docs/research/t348_r3_families.csv` 里 family=S642 的 1733 行(2022-01-21 → 2026-10-19,终值 1.0175906660151923,总收益 +1.3867517096161075%)。它是「原脚本重跑」出来的族曲线,参数一个没改(f=0.005、cap=10、逐日盯市、复利、不含资金费)。
- **用哪段历史**:2022-01-21 → 2026-10-19;票本参照 `/Volumes/CometCloudAI/cometcloud-local/research/t159/_tickets_2020-03-01_2026-06-20.json`(241 张票那一版)与 `t159_results.json` / `t348_r3_results.json` 的 meta。
- **做法**:生产内核在同一段历史上重放 → 逐日净值与族曲线对齐;票数、同时持仓数、每张票的 entry/exit 也要逐张对上。
- **容差**:逐日 nav 相对差 ≤ 1e-9;末值与 1.0175906660151923 差 ≤ 1e-6;总收益差 ≤ 1e-6;票数 241;同时持仓 ≤ 10。
- **不一致时先查这三处**(按嫌疑排序):① 闸门(复利起点与 `ret > -0.95` 过滤)② 跳空成交价(entry 当根打到 stop 用 stop 价)③ 成本借贷口径(第 11 条)。
- **互相对表**:`t159_bear_short.py` 的 `nav()` 是 plpgsql 内核的转写;生产实现与它两套互相对表,差 0 才认 —— 别拿族曲线当唯一基准。
- **前置条件**:`ohlcv_daily`(binance_hist) 的历史起点必须覆盖 2022-01 之前(否则 warm-up 不足 → 票数变),这一条要先查;`style_index_pit_daily` 的 ret 覆盖也要覆盖 2020 起的 200 天预热。

## 5. 与已经在跑的 S681 H4 纸面空头臂能共用什么

- **闸门可以共用,而且是同一个**:`short_paper.py` 的臂 H `short_h4_gate` 加的那条「信号日 majors 闸门关」,用的就是 `gate_closed_by_day()`(majors cap 指数 ≤ 自身 200 日均值)——**这就是 S-642 的闸门**,同一张表 `style_index_pit_daily`。S-642 不需要新数据、不需要新闸门。
- **票表与记账可以共用**:`short_paper_tickets` / `short_paper_state` / `short_paper_money` 三张表已经在跑,加一个臂标识(如 `short_s642`)即可落 S-642 的票与钱;命名、名额上限、逐日盯市的口径沿用同一套。
- **不能共用的**:开票规则(40 日低破位 + SMA200 + 宇宙五筛 vs H4 的反弹失败设置)、出场(2.5 ATR + 120 根 vs H4 自己的)、仓位(0.5%/10 张)。
- **建议**:把 S-642 做成 `short_paper` 的第二个臂,共用闸门、票表、记账;把 ATR/SMA/美元额这些纯函数抽到两个臂共用的模块,免得指标口径分叉。
- **要问人的**:H4 臂的票表列是否放得下 S-642 的字段(entry_px/stop_px/exit_reason/atr14),以及两臂共用 `short_paper_money` 时名义上限怎么分(各自 10 张?合计?)。

## 6. 工作量估计与最大的不确定处

**工作量(我估,人日)**:纯函数模块(指标 + 宇宙 + 信号 + 开平票 + 逐日盯市)3–5;一致性检验脚本(重放 2022–2026 + 逐日对表 + 容差断言)1–2;写票表与记账接入 short_paper 2–3;合计 **6–10 人日**(不含 Jazz 拍板的部分,也不含 CI/上线)。

**最大的不确定处(按可能造成系统性偏差的大小排)**:
1. **历史起点**:研究用了 T156 的 2018→2025-04 早期 bar;生产只有 `ohlcv_daily`。若库里 binance_hist 覆盖不到 2022-01 之前,220 根 warm-up 与 200 天闸门预热都会变 → 票数直接变。**一致性检验前必须先查 ohlcv_daily 的最早 trade_date 与 style_index_pit_daily 的最早 d。**
2. **闸门口径**:生产的 `gate_closed_by_day()` 与研究 `load_gate()` 的复利起点、过滤、n<200 的处理是否完全一样,未核实 —— 这是最可能造成「复现不出来」的一处。
3. **资金费口径**:族曲线不含资金费;前向账本一旦计入,与族曲线不可直接比(需要另出一条含资金费的基准曲线)。
4. **撮合口径**:同一根 K 线里 stop 与 sma20 同时触发的优先级、entry 当根打到 stop 的成交价,研究里已有默认,生产撮合要与之对齐(否则逐日对不上 1e-9)。

## 7. 本卡没做的事

- 没写生产代码、没改库、没下结论(不判断 S-642 是否该前向、也没给仓位建议)。
- 「同一张票表?同一个记账?」的答案是**可以共用**(H4 已在跑),但列宽与两臂名义上限怎么分需要票表作者/Seth 定。
- 具体钟点(`style_index_pit_daily` 的 computed_at 时刻、相关循环的调度时间)未核实;库里最新行的日期与 recorded_at 是实测值。
