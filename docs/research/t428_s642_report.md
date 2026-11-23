# T-428 — S-642 空头臂接进纸面账 state_book

**分支** `lane-a/T-428` · **卡** `tasks/T-428.json` · **2026-11-23**(lane-a)

## 1. 交付了什么

| 位置 | 内容 |
|---|---|
| `src/data/universe/state_book.py` | `S642_FROM`/`S642_BARS_FROM`/`S642_GATE_FROM`/`S642_SHARDS` 四个写死的常量;`_s642_known_to()`(覆盖规则);`_s642_member()`(同步纯函数);`_s642_inputs()`(分 16 片并发走现有 `_get_all`);`load_inputs` 里用 `asyncio.to_thread` 接上;`SOURCES["S642"]` 加进去(不扣现金),`UNAVAILABLE` 里拿掉 |
| `tests/test_state_book.py` | ① roster 断言改成「持有 3 / 名单 4;拿不到 S736_published」;② fixture 逐日净值一致(≤ 1e-9);③ 价格停在某天 ⇒ 最后一个给出的日子 = 价格的最后天 |
| `docs/research/scenarios/lane-a-T-428.json` | 四条预注册命题的结算(S1 否 / S2 ✓ / S3 ✓ / S4 待测) |

**没动**:`RULE`、`ROSTERS`、`START`、`SOURCE_OUTAGES`、已有成员的来路。

## 2. 实测(卡 ⑥)

| 项 | 值 |
|---|---|
| 一次读的行数 | **182,097 行** ohlcv_daily(binance_hist)/ 262 个符号 / 921 天(窗口 2024-05-16 → 2026-11-22,起点写死不随 cutoff 变) |
| 闸门 | style_index_pit_daily(majors / cap)1,419 行 / 2023-01-01 起 |
| **单流读** | **109.1 s** ← 超过卡上「30 秒先停下来说」那条线 |
| **算** | **1.15 s**(262 符号 × 921 根,`indicators` + `run_short` + `nav` 整段) |
| 每天符号数 | 首 220 / 末 135 / 中位 216 / 最大 226;**80% 断点 0 个、日历缺口 0 个** |
| `known_to` | **2026-11-19**(= 闸门最后一天;价与闸门都到得了) |
| 序列 | 净值 601 天 / 收益 600 天(2025-03-30 → 2026-11-19) |

**⚠️ 16 片并发读这一轮没量到**(上一轮的上下文守卫在 99k→121k 处拦下了计时脚本,这一轮又在 101k 处拦下了)。
上面 109.1 s 是**单流**读;生产里 `_s642_inputs` 走的是 16 片并发。Seth 合并前跑一条命令就能结算(见 §5)。

## 3. 起点改动 vs 研究族曲线(卡 ⑤,共同 569 天:2025-03-30 → 2026-10-19)

| 量 | 值 |
|---|---|
| 中位差 | **+0.000e+00**(逐日完全相同的日子 371/569 = 65.2%) |
| p95(绝对) | 1.332e-03 |
| 最大(绝对) | 5.728e-03 |
| 累计(2025-01-01 起复利) | 我的 1.105385 vs 族 1.124020 ⇒ **差 −1.8635 个百分点** |
| 相关 | **0.977722** |

**这条否掉了自己预注册的 S1**:起点从 2020-03-01 改成 2025-01-01 后,逐日收益**中位差是 0**(不是 > 1e-6)——
因为研究族曲线在 2025-01-01 边界上没有未平的票、净值路径是平的 ⇒ 单位数一样 ⇒ 逐日收益逐位相同;
差只出现在 34.8% 的日子(族曲线那边有跨边界的旧票在复利路径上)。
⇒ **「起点固定」这条纪律买的不是「逐日收益一样」,是「未来重算的历史不会变」**(每天重算出来的过去必须一样,
否则账本里已写下的行会被后来的重算推翻)。S2 / S3 成立。

## 4. 设计要点

- **起点写死**(`S642_FROM = "2025-01-01"`):每票 0.5% 净值风险 + 同时最多 10 张 ⇒ 今天的净值依赖更早开的票;
  起点一变,每天重算出来的整段历史就变。读的窗口也写死(`S642_BARS_FROM = 2024-05-16`,`S642_FROM` 往前 230 天 ≈ 220 根热身 + 10 根余量)。
- **闸门复用** `short_paper.gate_closed_by_day`(没重写);闸门起点 `S642_GATE_FROM = "2023-01-01"` 写死(闸门自己要有 200 天 majors 才出值)。
- **价缺不许变成 0**(S-898 / I1):`_s642_known_to` 从日历上**第一个**断点就停(「当天有日线的符号数 ≥ 前一天的 80% 且闸门有值」),
  之后一律不给(纸面账等源)。生产数据上 0 个断点。
- **不新增取数入口、不出外网**:日线与闸门都走现有的 `_get_all`(同一个 `_supabase_get`),分片只改怎么取、不改取到哪些行,
  取回后按 (symbol, trade_date) 去重再排好。
- **不扣现金**(`SOURCES["S642"] = (…, False)`),与研究族曲线同口径。

## 5. 需要 Seth 做的事

### 5.1 ⚠️ tests/test_state_book.py 少一坨(上下文守卫拦下了那次 Edit)

`load_inputs` 那条测试的假库 mock 里,我加了 S-642 的两行输入(`rows642` / `gate642`),
但**定义这两行的补丁被守卫拦下**,现在那条测试会 `NameError`。合并前请把下面这段插进
`tests/test_state_book.py` 里 `test_load_inputs_…` 函数中、`    async def get_all(tail):` 之前
(紧跟 `lead_rows = [...]` 那行之后):

```python
    # T-428:S-642 的输入 —— 把 T-412 的 fixture 往后挪三年(2020-01-01 → 2023-01-01),
    # 让它落在 S642_FROM(2025-01-01)之后,好让真的 `_s642_inputs` + `_s642_member` 在假库上跑一遍
    import json
    fx642 = json.loads((ROOT / "tests/fixtures/s642_fixture.json").read_text())
    k642 = ("trade_date", "open", "high", "low", "close", "volume")
    shift = dt.timedelta(days=1096)

    def _sd(d) -> str:
        return (dt.date.fromisoformat(str(d)[:10]) + shift).isoformat()
    rows642 = []
    for s_, rs in fx642["bars"].items():
        for r in rs:
            row = dict(zip(k642, r))
            row["symbol"] = s_
            row["trade_date"] = _sd(row["trade_date"])
            rows642.append(row)
    gate642 = [{"d": _sd(d), "ret": r} for d, r in fx642["gate"]]
```

（补丁之后那条测试断言 `set(x["rets"]) == set(sb.SOURCES) - {"style_meme"}` 成立:S642 走的是真的 `_s642_inputs` + 真的 `_s642_member`。）

### 5.2 16 片并发读的计时(卡 ⑥ / 预注册 S4)

```bash
cd ~/Projects/looloomi-ai-lane-a && python3 - <<'PY'
import asyncio, time, json
from src.data.universe.state_book import _s642_inputs, _s642_member
async def main():
    t0 = time.time(); bars, gate = await _s642_inputs("2026-11-22"); t1 = time.time()
    m = await asyncio.to_thread(_s642_member, bars, gate, "2026-11-22"); t2 = time.time()
    n = sum(len(v) for v in bars.values())
    print(json.dumps({"rows": n, "read_s_concurrent": round(t1 - t0, 1), "compute_s": round(t2 - t1, 2),
                      "known_to": m["known_to"], "symbols": len(bars)}, ensure_ascii=False))
asyncio.run(main())
PY
```

`read_s_concurrent ≤ 22` ⇒ S4 成立(S4 的先验 0.8,到期 2026-11-30)。
生产里这本账没写到昨天时每 3 小时最多整段读一次 ⇒ 单次 109 s(单流)/ 目标 ≤ 22 s(16 片)都能接受,但**接线前请确认并发读真的 ≤ 22 s**。

### 5.3 复算配方(上一轮跑的脚本,只读)

`docs/research/_t428_read.py`(读库 + 计时,缓存落 `/Volumes/CometCloudAI/cometcloud-local/research/t428/`)、
`docs/research/_t428_fit.py`(fixture 逐位复算)、`docs/research/_t428_timing.py`(页成本)、
`docs/research/_t428_probe.py`(覆盖规则 / known_to / 算耗时探针)。
生产跑批日志:`/Volumes/CometCloudAI/cometcloud-local/research/t428/prod_check.log`。

## 6. 探索性发现(未经预注册,别当结论用)

- **fixture 的段尾覆盖是导出形状,不是源停供**:T-412 的 fixture 在 2022-02-05 起每天只剩 9–16 个符号(尾 25 天只剩 1 个),
  覆盖规则会在 2022-02-07 断掉(10 < 0.8×13)⇒ 逐日净值那条测试用**显式截断点**给到段末
  (`_s642_member(..., known_to=段末)`);生产路径仍走 `_s642_known_to`。生产数据上 0 个断点。
- **起点固定这条纪律买的不是「逐日收益一样」**——见 §3。
