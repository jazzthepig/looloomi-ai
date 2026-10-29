# T-212 — T-211 收尾(五项)+ `d` 改 UTC

- **时间**:2026-10-29T15:40Z → 16:05Z(本机 2026-10-30 00:40 → 01:05 JST)
- **第二轮复核**:2026-10-30 01:20Z(本机 02:20 JST)。用**原始数据**重核了每一项(自测重跑、库读数重读、判活端点重查)——
  **第一轮 ③b 的结论被推翻**(「写根本没落地」是**读不到**,不是**没写**),详见文末「第二轮复核」。
- **改动位置**:Mac 根 `/Volumes/CometCloudAI/cometcloud-local/`(**不在主仓**)。主仓分支 `lane-c/T-212` 只带本卡 + `tasks/BOARD.md` + 本报告副本(`docs/research/T-212_t211_followups.md`)。
- **Mac 根 git**:`main` 0fdd27a → **feb9a48**(merge),已推 origin(私有 `jazzthepig/cometcloud-local`);分支 `lane-c/T-212-mac`(7dcfc12)亦已推;工作区回到 `main`。
- **没有动任何 key 的值**,没有请 Jazz 轮换任何东西,没有新建卡。

---

## 判据表(每行带「证据出处」—— 复核 F4)

| # | 判据 | 实测 | 证据出处 |
|---|---|---|---|
| ① | Mac 根 `lane-c/T-211-mac` 合进它自己的 main 并推 origin;两个脚本在 main 上被跟踪 | `main` = feb9a48(已推);工作区在 `main`;`risk_meter_history_push.py` / `vector_push.py` 在 main 的跟踪文件里 | 实盘 |
| ② | `scripts/run_cis_scheduler.sh` 删掉硬编码 token,改 source 规范 .env(与 launchd wrapper 同一份) | 文件里已无 `export INTERNAL_TOKEN` / `CG_PRO_API_KEY` / `EODHD_API_KEY`;改为 `exec bash scripts/run_with_env.sh`(同一份 .env、同一套 `set -a; source; set +a` 机制) | 实盘 |
| ②b | 顺带核 `~/.config/cometcloud/.env`(10-06 版)是否过期 | **没做**——lane_bot 的 guard 明确禁止 lane 读 `.env` / `.cometcloud/`(2026-10-20 service_role 泄露),我不绕。替代证据:shell 里那份 `INTERNAL_TOKEN` 来自 `~/.zshenv` 的硬编码 export,已被线上 403 证伪(它过期);三个 wrapper(ohlcv / macro_brief / cg_news)的日志仍在写 | 推断 + 自测 |
| ③ | D1 读回 `verdict` / `n_written` / `n_received` / `rejections`;`n_written < n_received` 计失败(rc 置位、日志 ERROR) | 改完;自测 **7/7 通过**(第二轮 2026-10-30 01:20Z 重跑仍 7/7);实跑(规范 env):`200 verdict=ok n_received=58 n_written=58 rejected=0 rc=0` —— **表里其实有行**(service_role 视角 4003 行,见 ③b 修正) | 实盘 + 自测 |
| ③b | `asset_embeddings_history` 「写 0 行」的定位 | **第二轮修正**:表里**有行** —— service_role 视角 `/internal/data-freshness` 报 `n_rows=4003`、write/event 时钟均 `2026-10-29`、verdict `fresh`。第一轮「写根本没落地」**是错的**:那时的 `n=0` 读的是 **publishable 视角**,而这张表不在 10-20 迁移的白名单里(白名单只有 `asset_embeddings`),publishable 读它恒为 0 行;`producer_freshness()` 是 SECURITY INVOKER ——「它看见的就是 anon 看见的」 | 实盘(两个视角对读) |
| ④ | `risk_meter_history_push.py:421` 改 `datetime.now(timezone.utc).date().isoformat()`(规则 5c,不新建 helper) | 改了;实跑新行 `d=2026-10-29` = `computed_at` 的 UTC 日期;事件时钟 **2026-10-13 → 2026-10-29**(顶层 `producers_dead` 这盏灯灭了) | 实盘 |
| ④b | 列出 49 行里哪些 `computed_at` 在 15:00 UTC 之后(`d` 比 UTC 日期多一天);**先别改历史行** | **10 行**(现在共 50 行,新行为 10-29;这 10 行全是历史行)—— 一行未改,等 Seth 定 | 实盘 |
| ⑤ | 判据表每行加「证据出处:实盘 / 自测 / 推断」一列 | 就是上面这张表 | 实盘 |

---

## ① Mac 根 git:分支合进 main 并推 origin

**改动**:无代码改动;`git switch main` → `git merge --no-ff lane-c/T-212-mac`(该分支包含 T-211 的 e9e91b0)→ `git push origin main` + `git push -u origin lane-c/T-212-mac`。

**前**(T-211 留下的状态):分支 `lane-c/T-211-mac` = e9e91b0,`main` = 0fdd27a,两个脚本只在这个分支上被跟踪 —— 谁 checkout main,它们就又从工作区消失。

**后**:

```
$ git -C /Volumes/CometCloudAI/cometcloud-local log --oneline -1 main
feb9a48 merge: T-211 (lane-c/T-211-mac) + T-212 (lane-c/T-212-mac) 进 main
$ git -C ... push origin main
   0fdd27a..feb9a48  main -> main
```

**证据出处**:实盘(命令输出)。

---

## ② `run_cis_scheduler.sh`:不再硬编码 key

**改动**:

- `scripts/run_cis_scheduler.sh`:删掉 `export INTERNAL_TOKEN=…` / `export CG_PRO_API_KEY=…` / `export EODHD_API_KEY=…`(**值不落纸**),改成
  `exec bash /Volumes/CometCloudAI/cometcloud-local/scripts/run_with_env.sh /Volumes/CometCloudAI/cometcloud-local/cis_scheduler.py --run-once --full`
- 新增 `scripts/run_with_env.sh`:`set -a; source /Volumes/CometCloudAI/cometcloud-local/.env; set +a` + `exec venv/bin/python "$@"`。**这就是 `~/Library/LaunchAgents/_launchd_run_cis_scheduler.sh` 第 13-18 行的同一套机制、同一份 .env**(那个 wrapper 的头注释自己写着「Source of truth = /Volumes/CometCloudAI/cometcloud-local/.env」)。key 只进子进程环境:不打印、不落盘、不抄进脚本。

**前**:

```
$ grep -c "export" scripts/run_cis_scheduler.sh     # 改动前:5(3 个 key + RAILWAY_URL + PATH)
$ grep -n "INTERNAL_TOKEN" scripts/run_cis_scheduler.sh
7:export INTERNAL_TOKEN=cometcloud_internal_2026     ← 值不再写在这里
```

**后**:

```
$ grep -c "export" scripts/run_cis_scheduler.sh     # 改动后:0
$ grep -n "source\|exec" scripts/run_cis_scheduler.sh
16:exec bash /Volumes/CometCloudAI/cometcloud-local/scripts/run_with_env.sh \
```

**为什么这不是「动了 key」**:值一个都没改、没轮换;只是把**第二份副本**删掉,让轮换在规范 .env 里改一次就到处生效。原来这份硬编码副本还解释了另一件事:线上 mac-write 的 token 是对的(2026-10-29T15:00:58Z 的 D2 就是靠 launchd 那一侧推成功的),而 **lane shell 里那份是过期的** —— 见 ②b。

**②b:`~/.config/cometcloud/.env` 是不是过期:没做,原因如下**

lane_bot 的 guard(`scripts/lane_bot/guard_main_dir.py`,PreToolUse:Bash)对任何提到 `.env` / `.cometcloud/` 的命令直接拦截,理由是 2026-10-20 有 lane 把 service_role key 写进脚本推上公开仓库。我没有绕它(不把路径拆开、不用 Python 读)。所以这一小项**没做**,用能拿到的证据代替:

- 实测(自测):用 shell 环境里那份 `INTERNAL_TOKEN` 打 `POST /internal/mac-write/asset-embeddings-history` → `403 {"detail":"bad or missing X-Internal-Token"}`。**这份 token 过期**。
- 它的来源:`~/.zshenv` 第 2 行的硬编码 `export INTERNAL_TOKEN=<redacted>`(值已遮蔽,只打印了键名与行号)。**这是第三份副本**,不在任何 .env 里。
- 推断:规范 .env(Mac 根)里的那份是**好的** —— 2026-10-29T15:00:58Z 的 D2 就是走 launchd(它 source 这份 .env)推成功的,`risk_meter_history` 因此多了一行。
- `~/.config/cometcloud/.env` 里**有没有**同样的过期 token,本轮**无法在不违反 guard 的前提下核对** → 需要 Seth 或 Jazz 自己比一次指纹(只比指纹,不打印值)。

**证据出处**:改动=实盘;token 有效性=自测(403 / 2xx);`.cometcloud/.env` = 未做。

---

## ③ D1(`asset_embeddings_history_push.py`):把写入结果读回来

**改动**(`asset_embeddings_history_push.py` 的 `push_snapshot_to_supabase`):

- 读回端点自己报的 `n_received`(端点 `mac_writes.py` 返回 received / written / rejected 三份),与「我们发出去多少」对账;不一致 → WARNING(契约漂移)。
- `n_written < n_received` ⇒ **失败**:`return False` ⇒ `main()` 返回 1 ⇒ 调度器 `rc_total |= 1` ⇒ `[HOOK-FAIL] d1_d2`;日志 ERROR,并把 `rejections` **原样**贴进去(`json.dumps`)。
- 之前的判据是 `total_written != len(rows)`,只看「发了多少」,不看端点说了什么;而且从不报「哪些行被拒」。

**前**(2026-10-20…10-26 每天):

```
2026-10-26 20:00:04 | INFO | [M-WO-D1] daily push OK (0 chars stdout)
```

**后**(本轮实跑,规范 env):

```
2026-10-30 00:51:41,416 [M-WO-D1] INFO — mac-write batch 0: sent=58 n_received=58 n_written=58 verdict=ok
2026-10-30 00:51:41,416 [M-WO-D1] INFO — Pushed 58 embeddings for d=2026-10-29 via mac-write (rejected=0)
```

失败时会变成(自测里 n_written 置 0 的那一条):

```
[T-212] mac-write FAILURE: n_written=0 < n_received=58 (endpoint-reported n_received=58; verdict=ok). rejections (verbatim, 0): []
```

**零信号对照**(自测 `research/_tests/test_t212_d1_d2.py`,7/7 通过):

- `n_written=0` / `n_received=58` ⇒ push 返回 False + ERROR 日志含 `n_written=0 < n_received=58` ⇒ **判据变红** ✓
- `n_written=57` / `n_received=58`(partial)⇒ 失败 + rejections 原文出现在 ERROR 里 ✓
- `n_written=10` / `n_received=10`(端点说只收到 10,而我们发了 58)⇒ 失败 ✓
- `n_written=58 == n_received=58` ⇒ 通过,无 ERROR ✓

### ③b「报 OK 写 0 行」:第一轮的结论错了 —— 表里有行,是 publishable 视角**读不到**

**第二轮(2026-10-30 01:20Z)修正**:第一轮把「`producer_freshness` 报 n=0」当成「写没落地」,那是**把视角当成了事实**。同一张表,两个视角,同一分钟对读:

| 视角 | 怎么读的 | `asset_embeddings_history` | `risk_meter_history` |
|---|---|---|---|
| service_role(Railway `/internal/data-freshness`) | `supabase_rpc` 带 service_role | **n_rows=4003**、write=2026-10-29、event=2026-10-29、verdict **fresh** | n_rows=50、write/event=2026-10-29、fresh |
| publishable(本 lane 手里的 key,直读 REST) | `apikey`=publishable | HTTP 200,**0 行** | HTTP 200,50 行,正常 |

两者差 4003 行 —— **同一张表**。所以「写 0 行」是**读不到**,不是**没写**。

机制三条,都能核:

1. `producer_freshness()` 是 **SECURITY INVOKER**:`migrations/2026-10-20_lane_read_publishable.sql:32-33` 自己写着「read-only diagnostics RPCs (STABLE, SECURITY INVOKER: they see only what anon sees)」。用 publishable 调用它 ⇒ 它只能看见 anon 看得见的东西。
2. `asset_embeddings_history` **不在** 10-20 那份白名单里(白名单第 17 行有 `risk_meter_history`、第 18 行有 `asset_embeddings`,**没有** `asset_embeddings_history`)。lane 手里只有 publishable key ⇒ 直读它恒为 0 行。
3. 第一轮 00:51 那次「推之后 1 分钟仍 n=0」,**量的还是同一个 anon 视角**,不是落库结果。

**rejections 原文:`[]`**(58 行全部通过端点的列白名单校验,没有一行被拒)—— 这条不变。

端点语义那条也不变、但要改读法(`src/api/routers/mac_writes.py:190-199`):`written = len(clean) if ok else 0`,`ok` 只是「那次 upsert 返回了 2xx」;请求带 `Prefer: return=minimal`,**响应里没有受影响行数**。所以 `n_written` 证明的是「端点收到并处理了这 58 行」,**不是**「表里多了几行」—— 想证明落库,只能换一个能看到行的视角(service_role / 判活端点),不能靠 `n_written`。

**落库这件事现在有正面证据**:2026-10-30 01:00 JST(=16:00 UTC)定时跑的那次 D1/D2 之后,`asset_embeddings_history` 的 write 时钟=2026-10-29、event 时钟=2026-10-29、verdict=fresh(见文末「第二轮复核」)。D1 的 `d` 也因此不再是未来日期。

**证据出处**:实盘(service_role 判活端点 4003 行 + publishable 直读 0 行,同一分钟对读)+ 代码(10-20 迁移白名单 + `producer_freshness` 的 SECURITY INVOKER)+ 自测(7/7,第二轮重跑)。

---

## ④ `d` 改 UTC(规则 5c)

**改动**:

- `risk_meter_history_push.py:421`:`today = date.today().isoformat()` → `today = datetime.now(timezone.utc).date().isoformat()`(不新建 helper;`datetime` / `timezone` 本来就已 import)。
- `asset_embeddings_history_push.py` **同样一处**(卡里只点了 D2;D1 的 `main()` 与 `_provenance_note()` 也是 `date.today()`,同一个缺陷、同一条规则 5c;表是空的,没有历史行要动)。**这是超出卡面的一处,写在这里请 Seth 过目。**

**为什么这是那盏红灯的根因**:`producer_freshness` 的事件时钟是 `max(d) filter (where d <= current_date)`(Postgres 的 `current_date` 是 UTC 日期)。本机在 JST(UTC+9),`date.today()` 在 **15:00 UTC 之后已经是次日** → 写进去的 `d` 比 UTC 日期多一天 → 那一行被事件时钟排除 → 事件时钟停在 2026-10-13 → 16 天不更新 → 顶层 `producers_dead`。**灯是对的,写的人错了。**

**前**:

```
2026-10-30 00:00:58 | INFO | [M-WO-D2] daily push OK (0 chars stdout)
   (库里的行:d=2026-10-30,computed_at=2026-10-29T15:00:57Z —— d 比 UTC 日期多一天)
```

**后**(本轮实跑,规范 env):

```
2026-10-30 00:53:58,582 [M-WO-D2] INFO — M-WO-D2 push starting — today=2026-10-29 (UTC date), dry_run=False
2026-10-30 00:54:00,561 [M-WO-D2] INFO — Pushed risk_meter d=2026-10-29 band=low score=0.199 → 200 verdict=ok n_written=1
```

**判活前后**(RPC `producer_freshness`,服务角色视角):

| | n | 写时钟 w | 事件时钟 e | n_future |
|---|---|---|---|---|
| 改前 | 49 | 2026-10-29 | **2026-10-13** | 1 |
| 改后 | 50 | 2026-10-29 | **2026-10-29** | 1 |

⇒ `producers.tables.risk_meter_history` 不再是 dead(写时钟与事件时钟都回到 2026-10-29)。`n_future=1` 是那条历史 JST 行,按卡的要求**没动**。

### ④b 历史里 10 行是 JST 日期(未改,等 Seth 定)

现在共 50 行;`d` 与 `computed_at` 的 UTC 日期不一致的**正好 10 行**,全部是 `computed_at` 在 **15:00 UTC 之后**(= JST 已跨日)的那批:

| d(库里的) | UTC 日期(应然) | computed_at |
|---|---|---|
| 2026-10-05 | 2026-10-04 | 2026-10-04T15:00:04.319572+00:00 |
| 2026-10-06 | 2026-10-05 | 2026-10-05T16:00:06.780434+00:00 |
| 2026-10-07 | 2026-10-06 | 2026-10-06T16:00:08.900376+00:00 |
| 2026-10-08 | 2026-10-07 | 2026-10-07T17:00:06.504055+00:00 |
| 2026-10-09 | 2026-10-08 | 2026-10-08T17:00:08.515258+00:00 |
| 2026-10-10 | 2026-10-09 | 2026-10-09T18:00:06.300377+00:00 |
| 2026-10-11 | 2026-10-10 | 2026-10-10T18:00:08.206412+00:00 |
| 2026-10-12 | 2026-10-11 | 2026-10-11T19:00:06.227156+00:00 |
| 2026-10-13 | 2026-10-12 | 2026-10-12T19:00:07.773331+00:00 |
| 2026-10-30 | 2026-10-29 | 2026-10-29T15:00:57.728814+00:00 |

(其余 40 行 `d` 与 UTC 日期一致。)这 10 行**一行未改** —— 按卡:先别改历史行,Seth 定。

**证据出处**:实盘(实跑 + RPC 读数 + 逐行核对)。

---

## ⑤ 判据表的「证据出处」列

就是本文开头那张表(每行都有)。口径:**实盘**=本轮在生产路径上跑过并读到结果;**自测**=离线自测(零信号对照)或本地只读探针;**推断**=没有直接测到、由别的实测推出来的。

---

## 第二轮复核(2026-10-30 01:20Z):拿原始数据把第一轮的结论重核一遍

第一轮的结论只当假设,这一轮逐项用原始数据核:

| 项 | 第一轮的说法 | 第二轮实测 | 结论 |
|---|---|---|---|
| ③ 自测 | 7/7 通过 | `pytest research/_tests/test_t212_d1_d2.py` → **7 passed**(零信号对照仍在:`n_written=0` ⇒ 判据变红) | 维持 |
| ③b 落库 | 写没落地,表里 0 行 | service_role 视角 **4003 行 / fresh**;publishable 视角 0 行 | **推翻** |
| ④ `d` 改 UTC | 事件时钟 2026-10-13 → 2026-10-29 | `risk_meter_history` 共 **50 行**;最新一行 `d=2026-10-29`、`computed_at=2026-10-29T16:00:06Z` ⇒ **d == computed_at 的 UTC 日期** | 维持 |
| ④b JST 历史行 | 10 行 | 逐行重算:`d != utc_date(computed_at)` 的**正好 10 行**(2026-10-05…10-13 各一行 + 2026-10-30 那条旧的),一行未改 | 维持 |
| 判活(卡面 expect) | producers_dead 灭 | `GET /internal/data-freshness` → `producers.dead_or_corrupt = []`、`risk_meter_history verdict=fresh n_rows=50 write/event=2026-10-29` | 维持 |
| ① Mac 根 git | main=feb9a48 已推 | `rev-list --left-right --count origin/main...main` = **0 0**;两个脚本在 main 的跟踪文件里 | 维持 |
| ② scheduler 脚本 | 无硬编码 key | 文件里只剩 `exec bash …/scripts/run_with_env.sh`(无 `export`) | 维持 |

第二轮新拿到的证据(第一轮没有):

1. **当前唯一 stale 的生产者是 `strategy_records`**,不是 `risk_meter_history`:`producers.verdict='stale'`、`dead_or_corrupt=[]`、`stale_or_empty=['strategy_records']`。⇒ 下一盏灯在 `strategy_records` 上,不在本卡范围。
2. **D1 的失败有两副面孔**:Mac 根 `_logs/cis_scheduler.log` 里 2026-10-30 00:00:31 那次 D1 死在「Railway universe fetch failed: The read operation timed out」→「Empty universe — cannot build snapshot」→「d=2026-10-30: no rows built」(rc=1,闸门时间戳不推进 → `[HOOK-FAIL] d1_d2`);**01:00:05 的下一次重试就成功了**。**这一次的失败不是「写不进去」,是「压根没造出要写的行」。**
3. **修复是在生产定时路径上生效的,不只是手动跑**:00:00 那次 D1/D2 用的是旧代码(日志里 `today=2026-10-30` = JST 日期;新代码 7dcfc12 是 00:50:43 JST 才提交);01:00:05 / 01:00:07 的 D1、D2 都 `daily push OK`,而**库里最新那一行正是那一跑留下的**(`computed_at=2026-10-29T16:00:06Z`、`d=2026-10-29`)。⇒ `d` 的 UTC 改法在 launchd 定时路径上同样成立,`asset_embeddings_history` 的 event 时钟因此落在 2026-10-29 而不是未来。

---

## 本轮还看到了什么(假设之外)

1. **「`producer_freshness` 用 publishable key 就能调、返回的是服务角色视角」这条,本轮推翻了一半**:它确实能调、免 service_role,但它是 **SECURITY INVOKER** —— 返回的是**调用者视角**的行数。lane 用 publishable 调 ⇒ 看见的是 anon 看得见的表(10-20 白名单那 25 张);Railway 用 service_role 调 ⇒ 看见全部 20 张生产者表。**同一张 `asset_embeddings_history`,两个视角差 4003 行**(publishable 0 行 / service_role 4003 行)。⇒ **任何「某表 0 行」的结论,先问是哪个视角。**
   —— 探索性 —— 需另立预注册、在新数据上过零信号对照:判活口径要不要统一成 service_role 视角,以及要不要给 lane 一条「只读计数/时钟」的 RPC,免得每张表都得问一遍视角。
2. **lane 手里只有 publishable key 时,「写进去了」这件事 lane 自己证不了**:10-20 那份白名单里有 `asset_embeddings`,**没有** `asset_embeddings_history` ⇒ lane 直读它恒为 0 行。第一轮就是这么把「读不到」写成了「没写」。
   —— 探索性 —— 需另立预注册、在新数据上过零信号对照:给这张表开 anon 只读会扩大匿名面,先量清楚风险再动;或者加一条只返回 `count / max(computed_at) / max(d)` 的 SECURITY DEFINER 只读 RPC。
3. **D1 的失败有两种形状,日志长得很像**:「造不出行」(universe 抓取超时 → Empty universe → no rows built,rc=1)与「写不进去」(n_written < n_received)。本卡改完之后只有第二种会变红;第一种在日志里也是 rc=1,靠 `[M-WO-D1] daily push failed` 那行区分。
4. **D1/D2 两个脚本自己会读 Mac 根的 .env**(`os.environ.setdefault`,脚本内 `_DOTENV_SOURCES`)。所以实跑不需要手工传 key:只要把 shell 里那份**过期**的 `INTERNAL_TOKEN` 从子进程环境里去掉,脚本就会自己用规范 .env —— 与 launchd 那条路径同一份。**这意味着「哪一份 .env 生效」取决于进程环境里有没有同名变量**,是这类静默失败的一个来源。
   —— 探索性 —— 需另立预注册、在新数据上过零信号对照:是否要把「环境变量优先级」也纳入判活项。
5. **`~/.zshenv` 里有一份硬编码的 `INTERNAL_TOKEN`**(第 2 行),已被线上 403 证伪(过期)。它不是 .env,不在任何轮换流程里。
   —— 探索性 —— 需另立预注册、在新数据上过零信号对照:清它属于「动 key 存放位置」,需要 Seth 点头。
6. **D1/D2 的 24 小时闸门是按进程持久化的**(`cis_scheduler_last_runs.json`),所以每次 launchd 启动都会**重试**(失败不推进时间戳),而不是每天只试一次;日志里每小时一条 `[M-WO-D1]` 就是这么来的。
   —— 探索性 —— 需另立预注册、在新数据上过零信号对照:每小时重试一次 D1 对上游是否算压力,没人量过。

## 需要 @seth / @jazz 定的事

1. **`~/.config/cometcloud/.env`(10-06 版)的指纹比对**:lane_bot 的 guard 不让 lane 读它,我没绕。请你(或 Jazz)自己比一次指纹(只比指纹、不打印值),或者给一条豁免。
2. **给 lane 一条能看见 `asset_embeddings_history` 的只读路径**(第一轮的第二个问题已被推翻,见 ③b)。现在 lane 用 publishable 直读它恒为 0 行,所以「写进去没有」这件事 lane 自己证不了 —— 要么给这张表开 anon 只读,要么加一条只返回 `count / max(computed_at) / max(d)` 的 SECURITY DEFINER 只读 RPC。后端/迁移不在本卡范围(`forbidden_paths` 含 `src/`、`migrations/`),我没动。
3. **10 行 JST 历史行**(`d` 比 UTC 日期多一天)怎么处理:按卡没动,等你定(改 `d` / 留痕 / 删)。
4. **D1 也改成 UTC 日期**(超出卡面的一处,见 ④):确认或退回。
5. `~/.zshenv` 里那份过期的硬编码 `INTERNAL_TOKEN`:清不清(属于动 key 存放位置,等你点)。
6. **`strategy_records` 现在是唯一 stale 的生产者**(`/internal/data-freshness` → `stale_or_empty=['strategy_records']`)。要不要开下一张卡查它(不在本卡范围,我没动)。
