# T-211 — Mac 引擎三处静默失败(宏观默认值 / 两个推送脚本缺失)

**日期**:2026-10-29 · **lane**:Minimax-C(lane-c) · **改动位置**:Mac 根 `/Volumes/CometCloudAI/cometcloud-local/`(**不在 PR 分支**)
**卡**:`tasks/T-211.json` · **依据**:MINIMAX_SYNC §Seth-1029a / §Seth-1029b

---

## 0. 结论摘要

| # | 静默失败 | 状态 | 判定 |
|---|---|---|---|
| ① | `risk_meter_history_push.py` / `vector_push.py` 从 Mac 根消失 | **已定位 + 已恢复** | 2026-10-13 09:13 的 `git stash -u` 扫进 `stash@{0}`,从未 pop 回来。恢复件与 stash 原件 **blob 哈希逐字节一致** |
| ② | 脚本缺失时 hook 只打 WARNING 然后 continue/return | **已改** | 缺失 ⇒ `rc_mask=8` + ERROR + `_record_hook_failure`;不再"跳过" |
| ③ | 宏观取不到时回落 MacroSnapshot 默认值 | **已改** | 部分取到也算 unavailable ⇒ ERROR + 计红,不许回落默认值 |
| ④ | **新发现**:Mac→Railway 内部写入全被 token 挡住 | **未解(需 Jazz 对齐 key)** | 恢复的脚本真跑 → `403 bad or missing X-Internal-Token`;D1 同错;vector_push `401 Invalid token` |

**数据现状(实测)**:`select max(d) from risk_meter_history` = **2026-10-13**(今天 17:50 查)。恢复件本身可用,但 **④ 未解 ⇒ 风险表今天仍然写不进去**。

---

## ① 两个脚本去了哪 —— `git stash -u`(2026-10-13)

**根因(已用原始数据核对,不是推测)**:

```
$ git -C /Volumes/CometCloudAI/cometcloud-local stash list
stash@{0}: On lane-c/T-087: T-087 WIP before T-085

$ git -C … log -1 --format='%H %ad %s' --date=iso 'stash@{0}'
12dd9063abed8e062d7a0b8ef1ab502402182e55 2026-10-13 09:13:02 +0900 On lane-c/T-087: T-087 WIP before T-085

$ git -C … ls-tree -r --name-only 'stash@{0}^3' | grep -E 'risk_meter_history_push|vector_push'
risk_meter_history_push.py
vector_push.py
```

- 这两个脚本在 Mac 根**从未被 git 跟踪**(`git ls-files` 里没有),所以一次 `git stash -u`(连未跟踪文件一起 stash)就把它们从工作树扫进了 stash 的第三棵树(`stash@{0}^3`),之后没人 pop。
- 同一批被扫走的还有 `scripts/run_cis_scheduler.sh`、`macro_brief_contract.py`、`book_trader.py` 等(当时 stash 的未跟踪清单共 300+ 项)。
- 恢复源:`Shadow/cometcloud-local/`(仓库里的 Mac 根快照,Sep 18 19:27 那次整体拷贝)。**已逐字节核对**:

| 文件 | stash 原件 blob | Shadow 副本 blob | 现在 Mac 根 |
|---|---|---|---|
| `risk_meter_history_push.py` | `ff94efaddef0257eeb5377cbd62fad4962c4fa34` | 同左 | 同左 |
| `vector_push.py` | `a9dcb2f57f71f42dcc08e7063f1d2bf5fa9ee89b` | 同左 | 同左 |

⇒ 恢复件 = 10-13 被扫走的那一版,不是别的版本。

**时间线(全部来自 `_logs/cis_scheduler.log.*`)**:

| 时间 | 日志 | 含义 |
|---|---|---|
| 2026-10-13 04:00:07 | `INFO  \| [M-WO-D2] daily push OK (0 chars stdout)` | 最后一次成功写 risk_meter_history |
| 2026-10-13 09:13:02 | (stash@{0}) | 脚本被 `git stash -u` 扫走 |
| 2026-10-14 05:00:09 | `WARNING \| [M-WO-D2] script missing: /Volumes/…/risk_meter_history_push.py — skipping` | 从此每天"跳过",**不算失败** |
| 2026-10-29 00:02:17 | `WARNING \| [A-N2-VP] vector_push.py missing: /Volumes/…/vector_push.py — skipping` | 每轮都打,连续 30 天 |

Supabase 侧对照:`select d from risk_meter_history order by d desc limit 3` → `2026-10-13 / 10-12 / 10-11`(= 停写当天,与 stash 日期同一天)。

**为什么 16 天没人知道**:见 ② —— "脚本缺失"被当成"跳过",`rc_total` 保持 0,24h gate 照常推进,日志看起来每天都正常。

---

## ② 脚本缺失现在计入失败(改 cis_scheduler.py)

**改动**(`cis_scheduler.py`,Mac 根):

| 位置 | 改之前 | 改之后 |
|---|---|---|
| `_maybe_run_d1_d2`(~L1446) | `venv python missing` → WARNING + return | ERROR + `_record_hook_failure(..., rc_mask=8)` |
| `_maybe_run_d1_d2`(~L1452) | `script missing` → WARNING + **continue**(rc_total 不变) | `rc_total \|= 8` + ERROR + continue;末尾 `rc_total != 0` ⇒ 记 `d1_d2` 失败、gate 不推进 |
| `_maybe_run_d1_d2`(~L1468-1484) | push 失败 / 超时 / 异常 → WARNING | 全部升到 **ERROR** + `_record_hook_failure` |
| `_maybe_run_vector_push`(~L1572) | `RAILWAY_URL` 未设 → 静默 return | ERROR + `_record_hook_failure(rc_mask=8)` |
| `_maybe_run_vector_push`(~L1581) | `venv python missing` → WARNING + return | ERROR + 记失败 |
| `_maybe_run_vector_push`(~L1586) | `vector_push.py missing` → WARNING + **return** | ERROR + `_record_hook_failure(rc_mask=8)` + return |
| `_maybe_run_vector_push`(~L1598) | push 失败 / 超时 / 异常 → WARNING | ERROR + `_record_hook_failure`(rc_mask 1/2/4) |
| 新增 `_record_hook_failure` / `_clear_hook_failure` / `hook_failures_snapshot`(L~74-104) | — | 进程内失败登记表,每条都先打 `[HOOK-FAIL] <hook>: <reason>` |

**改前 → 改后日志行(实测)**:

```
改前  2026-10-29 00:02:17 | WARNING  | [A-N2-VP] vector_push.py missing: /Volumes/CometCloudAI/cometcloud-local/vector_push.py — skipping
改后  2026-10-29 17:33:43 | ERROR    | [A-N2-VP] vector_push.py missing: …/vector_push.py — FAILING (rc_mask=8)
改后  2026-10-29 17:33:43 | ERROR    | [HOOK-FAIL] vector_push: vector_push.py missing: …/vector_push.py

改后(live,恢复件真跑)2026-10-29 18:02:17 | ERROR | [A-N2-VP] vector push failed (rc=1): — attempt 1/3 failed: TimeoutError: The read operation timed out; retry in 1s
改后(live)                  2026-10-29 18:02:17 | ERROR | [HOOK-FAIL] vector_push: vector push failed (rc=1)

改前  2026-10-29 00:02:26 | WARNING  | [M-WO-D2] script missing: /Volumes/CometCloudAI/cometcloud-local/risk_meter_history_push.py — skipping
改后  2026-10-29 17:34:06 | ERROR    | [M-WO-D2] script missing: …/risk_meter_history_push.py — FAILING (rc_mask bit 8)
改后  2026-10-29 17:34:06 | ERROR    | [M-WO-D1/D2] at least one daily push failed (rc_mask=8); timestamp NOT advanced — will retry next cycle
改后  2026-10-29 17:34:06 | ERROR    | [HOOK-FAIL] d1_d2: daily push failed (rc_mask=8)
```

(17:33 / 17:34 那几行是本地自测在临时空目录里触发的"脚本缺失"分支;17:48:47 的自测跑出同一形状。)

**自测**:`research/_tests/test_t211_silent_failures.py`(本卡新增)—— `5/5 passed`(17:48:47 实测输出):
`test_d1_d2_missing_script_is_a_failure` / `test_vector_push_missing_script_is_a_failure` / `test_macro_unavailable_never_uses_defaults` / `test_macro_partial_fetch_is_unavailable` / `test_macro_measured_is_green`。

---

## ③ 宏观不再回落默认值(改 cis_scheduler.py + data_fetcher.py,新增 macro_availability.py)

**规则(新)**:宏观 **available ⟺ 4 个必需字段全部实测**(`vix` / `treasury_2y` / `treasury_10y` / `dxy`)。部分取到 = **unavailable(红)**,不允许任何字段用 `MacroSnapshot` 的 dataclass 默认值补齐。

**改动**:

- `data_fetcher.fetch_macro_indicators()`:缺字段时不再打 "will use MacroSnapshot default",改成 "no default will be substituted — T-211";缺字段就不放进返回值。
- `cis_scheduler.run_cis_job()` 的 macro 块:先 `macro_availability.check_macro_availability()`;available 才构造 `MacroSnapshot`,并打 `source=measured`;unavailable 则 **ERROR + `[HOOK-FAIL] macro`**,`macro_snapshot = None`。
- 新增 `macro_availability.py`(Mac 根):`--once --write` → 写 `_reports/absorb_input/macro_availability_<date>.{json,md}` + MacErrorEnvelope + postmortem;退出码 `0=🟢 HEALTHY / 1=🔴 CRITICAL`。由 `cis_scheduler._maybe_run_macro_selfcheck()` 每日 **04:10-04:59 UTC** 窗口跑一次(= 计红)。

**改前 → 改后日志行(实测)**:

```
改前  2026-10-29 00:00:13 | INFO | [MACRO] VIX=18.0, 2Y=4.50%, 10Y=4.25%, DXY=104.0, real_rate=1.05%, regime=Tightening
      (09-29 ~ 10-29 14:31,每一轮都是这一行,字节相同 —— 默认值和实测值长得一模一样)
改后  2026-10-29 15:00:04 | INFO | [MACRO] VIX=16.9, 2Y=4.69%, 10Y=5.00%, DXY=102.1, real_rate=1.80%, regime=Tightening   ← 真值(Jazz 换 EODHD key 后;当时还是旧代码,没有 source 字段)
改后(live,新代码上线后第一轮)2026-10-29 18:00:04 | INFO | [MACRO] VIX=16.9, 2Y=4.69%, 10Y=5.00%, DXY=102.1, real_rate=1.80%, regime=Tightening, source=measured
      取数失败时:ERROR | [MACRO] UNAVAILABLE — missing=[…] error=…; NOT falling back to MacroSnapshot defaults
      + ERROR | [HOOK-FAIL] macro: macro unavailable: missing=[…]
```

**引擎改动什么时候生效**:launchd 的 plist(`com.cometcloud.cis_scheduler.plist`)是 `StartCalendarInterval{Minute:0}` + `RunAtLoad` + `KeepAlive{SuccessfulExit:false,Crashed:true}` —— **每小时 :00 起一个新进程**,所以改过的 `cis_scheduler.py` 在下一轮整点自动生效,**不需要人工重启**。上面 18:00:04 那行就是新代码跑出来的(`source=measured` 是新增字段)。

- 真值出现的原因是 **Jazz 10-29 05:32 UTC 换了 Mac 的 EODHD key**;本卡改的是"取不到"这一侧的形状(不再渲染成合理数字)。
- 今天 17:53 跑 `macro_availability.py --once --write` 实测:**🟢 HEALTHY (source = measured)**,measured = `vix=16.91, treasury_2y=4.691, treasury_10y=4.999, dxy=102.139`,missing=`—`,报告已落在 `_reports/absorb_input/macro_availability_2026-10-29.{json,md}`。
- 记录在案:`MacroSnapshot` 里 EODHD **永远不供**、恒为默认值的 7 个字段(`fed_funds_rate, cpi_yoy, pce_yoy, gdp_growth, unemployment, ism_mfg, credit_spread`)—— 报告里单独列出,别让人误以为"measured"覆盖了它们。

---

## ④ 推送字段:本轮**没有**改(等 §2 合约)

卡里写明「推送里带上「宏观来源 = 实测 / 不可用」字段之前先在 MINIMAX_SYNC §2 写合约,Seth 确认后再改推送」。规则 2 也要求先写合约。
本轮:**`source` 只在进程内 + 本地报告里**(`macro_availability.py` 返回值、`_reports/absorb_input/macro_availability_*.json`),**没有**进任何推送 payload。日志行末尾的 `source=measured` 是本地日志,不是推送字段。
⇒ 需要 Seth 在 §2 写合约并确认后,再把「宏观来源 = 实测 / 不可用」加进推送 schema。

---

## ⑤ 额外发现(卡外,探索性):Mac→Railway 内部写入全被 token 挡住 —— **同一根因,第四处**

恢复脚本后真跑(17:49-17:53 实测,不是推断):

```
$ python3 risk_meter_history_push.py          # 恢复件
[M-WO-D2] Meter: band=low score=0.194 long_gross=0.9996 / Macro regime: EASING / panel_regime_run_length=59d
POST https://web-production-0cdf76.up.railway.app/internal/mac-write/risk-meter-history → 403
{"detail":"bad or missing X-Internal-Token"}

$ python3 asset_embeddings_history_push.py    # D1(一直存在,每天都在跑)
[M-WO-D1] d=2026-10-29: built 58 rows (live), measured_dims min=12 p50=17 max=17 of 27
POST …/internal/mac-write/asset-embeddings-history → 403 {"detail":"bad or missing X-Internal-Token"}

$ python3 vector_push.py                      # 恢复件
[VECTOR_PUSH] payload assembled: 43 assets, 43 with prior_pillars, 43 with pillar_history, macro=Neutral, schema=1.0
POST …/internal/asset-vectors → 401 {"detail":"Invalid token"}
```

**服务端怎么判**:`src/api/routers/mac_writes.py:114-120` 与 `os.environ["INTERNAL_TOKEN"]` 严格相等,不等 ⇒ 403;`src/api/routers/mac_push.py:73-76`(`_auth`)⇒ 401。Mac 根的**两个** token 来源(`.env`、`scripts/run_cis_scheduler.sh` 的 `export INTERNAL_TOKEN`)都被拒 ⇒ Mac 上的 token 与 Railway 端不一致。

**断点定位(D1 日志实测)**:D1 在 10-14 / 10-15 / 10-16 / 10-17 还是 `INFO | [M-WO-D1] daily push OK`,**从 10-18 起**变 `WARNING | [M-WO-D1] daily push failed (rc=1)`(每天必现)⇒ token 是在 **10-17 ~ 10-18 之间**对不上的,与 10-13 的 stash 是**两件独立的事**。

**为什么这层没被算进"静默失败"**:D1 的失败是 `rc=1` + WARNING —— 可见,但没人去读;而且 `asset_embeddings_history` 表现在**0 行**(今天 17:52 查),说明 D1 在 10-14~10-17 报 OK 时也没真的写进去。仓库自己的 `src/api/routers/mac_push.py` 已经把这个形状写进注释:「both target tables reached today with 0 rows while the push script logged 'complete'」。

**要 Jazz 做的**:把 Mac 的 `INTERNAL_TOKEN` 与 Railway 端对齐(key 动作,我不能碰)。对齐后:
- D2 会立刻补上今天的行(`max(d)` 从 2026-10-13 跳到当天);
- D1 / vector_push 同时恢复。

**要不要回填 10-14 ~ 10-28 的 risk_meter_history?** —— 需要拍板,我的倾向是**不回填**:脚本是用"今天的 universe + 今天的 macro-pulse"算 meter 的,拿今天的值填历史日期等于伪造历史。回填必须另立预注册、用当日真实输入重算。

---

## 怎么判活(判据)

| 判据 | 期望 | 现在 |
|---|---|---|
| Mac 日志 `[MACRO]` | 带 `source=measured`,不再出现 `VIX=18.0 / 2Y=4.50 / 10Y=4.25 / DXY=104.0` | ✅ live 18:00:04 已带 `source=measured`(新代码上线,launchd 每小时 :00 起新进程,无需人工重启) |
| 取数失败时 | `ERROR [MACRO] UNAVAILABLE — missing=[…]` + `ERROR [HOOK-FAIL] macro` | 自测已覆盖(5/5) |
| `[M-WO-D2]` / `[A-N2-VP]` | 出现 `missing … FAILING (rc_mask=8)` 或成功行,**不再出现 `— skipping`** | ✅ live 18:02:17 `[A-N2-VP] vector push failed (rc=1)` 已是 ERROR + `[HOOK-FAIL]`;D1/D2 的下一次尝试是 **10-29 23:00 JST**(24h 门限自 10-28 23:00 那次成功起算),届时 D2 会真跑并因 ⑤ 报 ERROR(响,而不是静默) |
| `_reports/absorb_input/macro_availability_<date>.md` | `Verdict: 🟢 HEALTHY (source = measured)` | ✅ 2026-10-29 已生成(17:53) |
| `select max(d) from risk_meter_history` | = 当天 | ❌ 仍是 2026-10-13(等 token 对齐) |

---

## 改了哪些文件(全在 Mac 根 `/Volumes/CometCloudAI/cometcloud-local/`,**不在 PR 分支**)

| 文件 | 状态 | 说明 |
|---|---|---|
| `cis_scheduler.py` | 改 | 失败登记 + 缺失脚本计入失败 + macro 不回落 + macro selfcheck |
| `data_fetcher.py` | 改 | `fetch_macro_indicators` 不再补默认值 |
| `macro_availability.py` | **新增** | 宏观可用性自检(🟢/🔴,写报告 + envelope + postmortem) |
| `risk_meter_history_push.py` | **恢复** | 从 Shadow 复制回根,blob 哈希 = stash 原件 |
| `vector_push.py` | **恢复** | 同上 |
| `research/_tests/test_t211_silent_failures.py` | **新增** | 5 条自测 |
| `_t211_d2_live.py` | 新增(辅助) | 用 `scripts/run_cis_scheduler.sh` 的 export 跑推送脚本(只读 export 行,不打印 key) |

按卡的要求,引擎改动**留在 Mac 根**(该根的 git 是独立 checkout,分支 `lane-c/T-020`,未提交),PR 分支只带本报告 + 卡 + BOARD。

---

## 没做 / 需要人拍板

1. **推送字段没动**(「宏观来源 = 实测 / 不可用」)—— 等 Seth 在 §2 写合约。
2. **key 没碰** —— Mac 的 `INTERNAL_TOKEN` 与 Railway 不一致(403/401),要 Jazz 对齐。
3. **历史不回填**(10-14 ~ 10-28 的 risk_meter_history)—— 需拍板 + 另立预注册。
4. `asset_embeddings_history` 0 行 —— 与 ⑤ 同源,token 对齐后再看是否还有第二层问题。

---

### 探索性发现(需另立预注册、在新数据上过零信号对照)

- **E1**:`risk_meter_history` 与 `asset_embeddings_history` 是 Mac 侧两个"看起来在跑、其实没在写"的表;停写的**机制**有两种(stash 把脚本带走 / token 轮换把写入挡住),而**信号形态完全一样**(日志里都是一行 INFO/WARNING)。零信号对照:把"生产者存活"当成被解释变量,而不是看表里有没有新行。
- **E2**:`MacroSnapshot` 有 7 个字段(EODHD 不供)**永远**是默认值。⇒ "source=measured" 只覆盖 4/11 个宏观字段;若下游按"measured"理解整张快照,仍会把 7 个默认值当实测用。要不要给这些字段单独标 `source=default`,需要另立预注册再定。
- **E3**:D1 在 10-14~10-17 日志报 `OK` 而表是 0 行 —— "rc=0 不等于写进去了"。`/internal/mac-write/schema` 的 `rows_written` 契约存在,但 Mac 侧脚本的日志没有把 `rows_written` 读回来核对。

*(本报告所有数字均来自 2026-10-29 17:4x-18:0x 的原始日志 / Supabase 只读查询 / 实跑输出;继承自上一轮未提交改动的结论已逐条用原始数据复核。)*
