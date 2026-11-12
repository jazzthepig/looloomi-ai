# lane-a 的情景台账体检:5 条死条目复活(T-308 整份 + T-252 三条 + T-256 一条)

**日期:** 2026-11-12 · **分支:** lane-a/T-308-fix · **触发:** lane-b 的 T-356 卡(情景台账死条目)提醒后,
lane-a 自查自己名下那 40 份情景文件 —— 找到 5 条「写着但永远不会进台账」的条目。
**性质:** 交付补正(不是新研究):概率、实质、检查方法一字未改,只改台账认不认得的形式。

---

## 1. 判据:跟写入端同一个口径

写入端 `src/data/evaluation/scenario_ledger.py` 的 `ingest_repo()`(第 330–350 行)是:

```python
new  = [e for e in rec["entries"] if str(e.get("id")) not in have]     # 只写还没入账的 id
good = [e for e in new if not validate({**e, "author": rec["author"]}, today)]
```

两条关键口径,自查时必须照抄:

1. **作者是文件级的**:每条没有自己的 `author` 字段没关系,写入端会把文件级 `author` 注入每条再校验。
   (直接拿条目喂 `validate()` 会全部误报「缺 author」—— 11-12 踩过一次。)
2. **只写还没入账的 id**:改一份已入账的文件等于没改;所以本次先查了库,确认要修的 id 一个都不在台账里。

检查脚本(可复现,退出码非 0 = 有死条目):

```
python3 docs/research/lane_a_scenario_ledger_check.py lane-a    # 本 lane
python3 docs/research/lane_a_scenario_ledger_check.py           # 全仓
```

## 2. 找到的死条目(lane-a 的 5 条)

| 文件 | 条目 | 死因 | 处理 |
|---|---|---|---|
| `scenarios/lane-a-T-308.json` | 整份 | 文件用的是自拟 schema(`task`/`owner`/`scenarios[]`),台账只认 `author` + `entries` ⇒ **author '' 不认,整份不认** | 按 `docs/research/scenarios/README.md` 重写为 `author` + `entries[]`,四条命题(T308-S1..S4)一一对应搬过去 |
| `scenarios/lane-a-T-252.json` | T-252-1 | `op: "lt"` 却把界写在 `lo` 里 ⇒ 校验要求 `lt` 的界在 `hi`(`lt 要 hi`) | `lo` → `hi`,界值 80504 不变 |
| `scenarios/lane-a-T-252.json` | T-252-3 | 同上(界 0) | `lo` → `hi` |
| `scenarios/lane-a-T-252.json` | T-252-4 | 同上(界 0.0416666666666667) | `lo` → `hi` |
| `scenarios/lane-a-T-256.json` | T-256-4 | 同上(界 0.0416666666666667) | `lo` → `hi` |

**改完的数(本机实测,`lane_a_scenario_ledger_check.py lane-a`):**

| | 改前(origin/main 基线) | 改后(本分支) |
|---|---|---|
| 活条目 | 220 | **228** |
| 死条目 | **5** | **0** |
| 整份不认的文件 | 1 | 0 |

活条目 +8 = 复活 4 条(T-252 ×3、T-256 ×1)+ T-308 整份的四条(原来 0 条)。
(基线取 origin/main;同一份扫描在 lane-a/T-355 分支上是 225→233,多的 5 条是 T-355 自己那份新写的命题。)

**概率与实质没动:** T-308 的 0.70 / 0.60 / 0.75 / 0.60 与 support、check 方法逐字照搬;
T-252 / T-256 的 `prob` 与 `horizon_d` 没动,只把界的键从 `lo` 换成 `hi`(`lt` 的语义仍是「小于该界」)。

**为什么原来不会有人发现:** `ingest_repo()` 对不合格的条目**只报不写**(`skipped`),
报告里只留前 20 条,写在每小时的日志里 —— 没人盯日志,条目就这么静默地死了,而文件在仓库里看着是好的。

## 3. 库里的核对(只读)

- `scenario_ledger` 里查 `T-252-1, T-252-3, T-252-4, T-256-4, T-308-1..4` ⇒ **0 行**(都没入过账),
  所以修完合并后会作为新行入账,不会被「id 已存在」跳过。
- 这些命题用到的自动变量都读得到(实测 2026-11-11):`state_daily(entity=panel)` 的
  `breadth_above_ma50` / `dist_200` / `funding_7d_ann` / `funding_7d_ann_binance` / `oi_chg_30d` 都有值,
  `ohlcv_daily` 的 BTC 收盘(源 binance_hist / coingecko_pro_ohlc)也在。

## 4. 全仓还剩多少死条目(不是 lane-a 的活,只报)

同一脚本跑全仓:**活 606 · 死 16**(整份不认 6 份)。

- **lane-b 15 条**:6 份整份不认(T-237 / T-238 / T-242 / T-244 / T-279 / T-282,全是「author '' 不认」)
  + 9 条条目级(T-230-2 `horizon_d 要是日期`;T-254 的 6 条全「缺 statement」;T-283 的 2 条「lt 要 hi」)。
- **lane-c 1 条**:T-239-5「lt 要 hi」—— 跟我这次修的是**同一个写法错误**(界写在 `lo` 里)。
  lane-b 的 T-283 两条也是。三个 lane 各自犯同一次,说明这条规则值得写进 lane 的提示词,而不是只改文件。

lane-a 的文件我一个字没动。

## 5. 需要别人做 / 回答的

1. **@seth**:T-308 这 4 条全是 `manual`(公告文本与账本计数,`close`/`state`/`macro` 三类自动变量量不到)。
   按 `settle_manual()` 的规矩,人工结算不能由 lane-a 自己结 —— 需要 lane-b / lane-c / seth 之一在
   `docs/research/scenarios/settlements/*.json` 里给观测值与证据。
2. **@seth**:`scenarios/README.md` 写着「每张卡 ≥ 3 条,**至少一条是自动结算的**」。T-308 这张卡做不到
   (它量的是公告与账本,不是价格 / 状态 / 宏观),所以这份文件是 lane-a 其余文件里唯一全 manual 的
   (扫描确认:lane-a 别的文件每份都至少有一条自动结算的)。
   是接受这个例外,还是 README 要改写,请回一句。
3. **@seth**:`ingest_repo()` 对不合格条目只报不写、只留前 20 条 —— 台账死了多少条要等到有人查。
   `docs/research/lane_a_scenario_ledger_check.py` 可以直接进 preflight 或 CI(退出码非 0 = 有死条目),
   要不要挂上去由你定(它在 `docs/research/` 下,不进 `scripts/`,不会碰 lane 的范围规则)。

## 6. 口径与合规

只做定位与覆盖面的陈述,不含方向性判断;信号用语只限
STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT。
本卡只读库、只改本 lane 的情景文件,没有写库、没有改任何账本或评分逻辑。
