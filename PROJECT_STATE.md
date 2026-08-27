# PROJECT_STATE.md — the living single source of truth

**Last updated:** 2026-08-27 (Seth/Cowork lane — S-244，测试注册缺口)

## 本轮一句话:**一个形状,十次**

每一次都是**「拿不到」被渲染成一个合理的数字**,而不是被渲染成「拿不到」。
一个 0 在合法区间内、看起来正常、是空累加的天然产物 —— 所以九次都没人发现。

| # | 哪里 | 缺失变成了什么 |
|---|---|---|
| S-180 | `redis_get_key` miss=error | 一次丢包 → 58 资产 T1→T2,评级写进永久记录 |
| S-184 | quant / crowd_clock / 日快照 | 交易历史被覆盖 · 重复行 · 影子行 |
| S-185 | 占用查询用了不存在的列 | fail-closed 拒写 → **静默停机 115 分钟,`/health` 全绿** |
| S-190 | 深度面板覆盖率下限只标注不拦截 | 1/262 的运行照写,`max(trade_date)` 显示当天 |
| S-194 | 五本账本 `pnl = 0.0` + 条件累加 | **面板 +23.99% 期间账本记 0.00%** |
| S-195 | CoinGecko 用错端点四个月 | 小时点塌缩成"日收盘",08-19 BTC 记 +0.30%(实际 +7.15%) |
| S-200 | T2 构建 110s / 预算 12s | 缓存永远填不上 → 永久降级,`regime=None` |
| S-201 | `NAV_TABLE` 声明了没写入者 | 表存在、永远空、看起来这项有人管 |
| S-202 | `{"ok": True, "rows": 0}` | **CIS 四个月用中性权重打分,日志每天说正常** |
| S-242 | 接收端漏写顶层 `macro_regime` | HIGH 级 regime 信号**从 feed 里消失**(守卫是 `if regime:`);CIS gate 落到 58 默认值而非 TIGHTENING 的 52 → **27 个过闸报成 20 个** |
| S-243 | 每资产 regime 从没和顶层对过账 | 同一份响应顶层 `Tightening` / 每资产 `RISK_ON`(58/58)→ 配置面板对投资人显示 **"Risk appetite elevated. Full allocation eligible."** |

**S-242/243 三课**(细节见 ledger,别在这里展开):① **沉默也是一种渲染** —— 前九次是「拿不到」
渲染成一个合理的数字,这次渲染成**什么都没有**,一条缺席的 HIGH 信号和「没这个状况」在输出上
一样;所以 `cis_regime_unmeasured` 那条 pillar 全 0 的信号不是装饰,**未测量必须占一个位置**。
② **读对 key 还不够** —— 引擎发 `Tightening`,所有表是 UPPER_SNAKE,miss 的表现是默认值不是报错。
③ **「两处写法不一致」要当缺陷查,不是当风格容忍** —— S-243 正是问「要不要统一大小写」问出来的,
表层不一致底下压着一个不一致的**事实**。四条出口(含最易烂的 degraded/LKG)统一走 `_unify_regime()`,
矛盾一律 `_logger.error`,**不静默调和**(引擎侧归 Minimax lane)。

⚠️ 守卫失败第七轮,同一类(匹配名字而非构造):S-243 前端守卫初版按 `if "regime" in line` 过滤,
而出问题的 key 所在行**恰好没有这个词** —— **在真实的坏文件上通过**。已改成跟踪代码块 +
补「用 fixture 重新引入 bug 确认守卫会响」的测试;旧版 CISWidget 实测 7 处全捕获。

⚠️ **守卫自己失败了六轮**,两类:匹配名字而非构造(**解释 bug 的注释废掉了抓这个 bug 的测试**,已抽成 `tests/_source.py`);测试样本过度确定。每个守卫现在都用重新引入 bug 验证过。

## 现在能跑的 / 不能跑的

```
✅ CIS T1        43 symbol,每天在写,今天还在
✅ T2 universe   58 个,regime=Tightening,11s(110s 是 provider 降级,已恢复;预计算已下请求路径)
🟡 regime        S-242 已部署验证(`cis_regime` 回到 feed,闸=52);S-243 全链路 UPPER_SNAKE + 每资产对账**未 push**(含 dashboard,需 rebuild)
✅ Hyperliquid   232 永续,日线自带 epoch,已是价格锚
✅ 五本账本      定不了价就拒绝标记,不再记假平盘
🔴 IC 权重       中性 —— 只有 6 个独立交易日,门槛 20。**诚实地不通,不是坏了**
🔴 signal_outcomes  停 112 天(Mac lane),卡住投资人页面的 track record
🟡 HL 采集器     最新 08-21,静默原因未查证
```

## 三个等你的决定

1. **① 账本 v4 已升(HL 是价格锚,不是成交场所)** —— 08-21/22 假 mark 已 void 并附原因。**void = 标记不是删除,行永远可查。**
2. **② 面板 262 里只有 88 个能在 HL 成交** —— 另外 174 个的回测执行不了。要不要把研究宇宙收敛到可执行的那 88 个?
3. **③ `_nav` 两张表没有写入者** —— 一周后还空就补写入者或删常量。

<details><summary>历史 header (08-18 / 08-19) — 详见 REFUTATION_LEDGER 与 PROJECT_STATE_LOG</summary>
</details>

## OPEN RISKS  (≤7 · cold-start first screen · every item ships a VERIFY command)

*Why this block is first: measured on 2026-07-30, a cold agent following CLAUDE.md exactly could
not reach S-92 or the still-open security hole — the header was dated older than the incident and
the lessons lived only in a 5,672-line ledger. **Don't transmit memory, transmit verification.**
Contract + failure-path walkthrough: `docs/AMNESIA_PROTOCOL.md`; enforced by
`tests/test_cold_start_contract.py`.*

*RETIRED 2026-08-12 to make room for #0: **#5 MCP streamable-transport migration** — closed
2026-08-09, no open follow-on, and its VERIFY (`grep -c 'mcp/sse' src/mcp/*.py` → 0) is a
regression check, not a risk. Moved to the ledger. Structural note while retiring it: **5 of
the 8 entries were 🟢 closed.** A cap of 7 does not bind on risk, it binds on the list, so
resolved items crowd out live ones and a cold agent reads eight entries to find three risks.
The cap is doing its job only if closure is as routine as addition.*

0. **🔴 C3 sizing table was INVERTED ON BOTH AXES (S-151, 2026-08-12).** Measured by
   execution: `lookup_size(regime=5 out-of-distribution, signal=1 weakest) = 1.30` and
   `(regime=1 in-dist, signal=5 strongest) = 0.10` — exactly backwards from the module's own
   stated design; `compute_size(None, None) = 1.20`, i.e. **no information produced leverage**,
   and `beta_core_size_hook` documented that 1.20 as the intended first-ship baseline.
   It survived because table + smoke test + hook docstring all agreed with EACH OTHER; only the
   stated intent dissented. **A frozen-value check could not have caught it — the table was
   transposed before it was frozen, and freezing preserves it.** Fixed by making the wrong
   ORIENTATION unable to load (`src/data/signals/strategy_params.py`, behavioural invariants
   validated at load), not by editing Minimax-C's 25 values. Until C seeds a re-oriented table,
   C3 runs the neutral table = ① baseline, no edge. Reversing both axes yields a passing table
   from the SAME 25 values — the magnitudes were designed right, the assembly was not.
   **AWAITING MINIMAX-C** (`MINIMAX_SYNC.md` §C3-SIZE-INVERSION-2026-08-12, items C6/C7).
   VERIFY: `python3 -m tests.test_sizing_cannot_invert` → green ⇒ an inverted orientation
   cannot load · `python3 -c "from src.data.signals.beta_core_size import compute_size as c;
   print(c('x',None,None,1.0).size_final)"` → ≤1.0 ⇒ no information buys no leverage
   OWNER: Seth (the gate) · Minimax-C (the 25 values + C7 polarity call)

1. **🟢 Service_role RESOLVED in production 2026-08-09 13:57Z.** `/health.strategy_library:
   pg_configured:true, degraded:false, consecutive:0`. ① clock live (OPEN RISK #4 below),
   §BETA-METRIC-AGG track record populated (66 signals, 60 scored). Kept here as the lesson +
   the local-Mac-side follow-on: **local `.env` still missing the real service_role key** —
   Mac-side Seth backfills (D1, D2, §OHLCV-DEAD backfill) remain blocked until Jazz pastes
   the real key. Downgraded from P0 to P2 because: (a) the immediate P0 consequence (Railway
   writes blocked, ① ② ③ unable to start) is RESOLVED, (b) all Mac-side-only work can be
   deferred without blocking product surface. **Lesson #72: a JWT that decodes is not a JWT
   that verifies.** The token carried `iss=supabase`, `ref=soupjamxlfsmgmmtoeok`,
   `role=service_role`, exp 2036 — every local check passed. It was the **anon key's signature
   spliced onto an edited payload**: byte-identical header, byte-identical 43-char signature,
   only the `role` claim differed. A signature is an HMAC over header+payload, so it cannot
   survive a payload edit — proof it was hand-assembled, not issued. Server verdict:
   `401 Invalid API key`. Almost certainly an earlier agent that needed service_role, had only
   anon, and produced one. **Never validate a credential by decoding it; validate it against
   the server that issued it.** Now enforced in `build_l1_observations.py --diagnose`, which
   probes for ROWS (real anon returns 200/0 rows under S-94 RLS, so status alone also proves
   nothing). Forged copies purged from `.env` and both `.claude/**/settings.local.json`
   (12 entries); never git-tracked (`.gitignore:42`).
   VERIFY: `bash -c 'set -a; . .env; set +a; curl -s -H "apikey: $SUPABASE_KEY" "$SUPABASE_URL/rest/v1/ohlcv_daily?select=symbol&limit=1"'`
   → `[{...}]` = real service_role · `401` = forged/stale · `[]` = anon under RLS, still blocked
   → **currently returns `401` (no local key) — expected, deferred**
   OWNER: Jazz (dashboard → Project Settings → API Keys → service_role → paste into `.env` —
   follow-on, not P0)

   **Lesson #71: a security linter's silence is not safety.** Four of the worst exposures were absent from the advisor's 11 errors — it excludes permissive SELECT policies, so `cis_scores` was world-readable and unflagged. Audit `pg_policies` / `pg_proc` directly.

2. **🟡 External probe live 2026-07-30, unproven** — `cometcloud-external-probe`, every 2 h,
   **outside the monitored process** (5 checks: liveness · the endpoint that died · Mac-push
   freshness · security-regression on the revoked RPC · anonymous read). Worst-case blind window
   **10.4 h → 2 h**. Still open because: it runs only while the desktop app is open, it has never
   fired on a real failure, and **an unfired alarm is not a proven alarm**. Downgrade to 🟢 only
   after it catches something, or after a deliberate induced failure confirms it fires.
   VERIFY: `ls /Users/sbb/Documents/Claude/Scheduled/cometcloud-external-probe/` and check the
   last run reported `✅ probe OK`; no run in >3 h ⇒ the probe itself is dead.
   OWNER: Jazz (keep the app open) / Seth (induce a failure to prove it fires)

3. **🔴 The VDB's durable layer is not finished — and one gap was silently losing research.**
   *(merged from two entries: "tables are empty" and "the graveyard was in a cache" are the same
   problem seen from the data side and the mechanism side.)*

   **(a) A table that was never created.** `scripts/supabase_strategy_records.sql`, written
   2026-07-26 specifically to move the strategy record library off a 24 h-TTL Redis key, **was
   never applied.** `_pg_upsert()` POSTed to a nonexistent table, caught the exception, logged one
   WARNING, returned False, and `upsert_record()` fell back to Redis with `_TTL = 86_400`.
   CLAUDE.md calls the graveyard the asset; the asset sat in a cache that expires daily, for 12
   days. **It survived because the warning fired on EVERY write — an always-on warning carries no
   information.**

   **🔴→🟢 THE CLASS, NOT THE INSTANCE (S-166, 2026-08-15).** This entry described ONE table
   that was never created. On 2026-08-15 the same check run across the whole codebase found
   **ELEVEN more** — `beta_core_nav_q(_meta)`, `beta_core_nav_size(_meta)`, `strategy_params`,
   `execution_intents/outcomes`, `fusion_paper_nav/lifecycle`, `crowd_clock_log`. This file's
   own header had called C2 and C3 "complete; 79/79 smoke green" while neither sleeve had
   anywhere to write a row. **The risk was written here, the lesson was recorded, and it still
   recurred eleven times — because what got fixed was that table, not the absence of any
   comparison between the set of tables the code writes and the set that exists.** Fixing an
   instance and calling the class closed is how one bug gets renamed eleven times.
   All 11 created; verified live `23/23 present, missing: []`.
   VERIFY: `python3 -m tests.test_every_written_table_exists` (offline: manifest matches source)
   · `curl -s -H "X-Internal-Token: $INTERNAL_TOKEN" $RAILWAY/internal/schema-drift` → `missing: []`
   OWNER: Seth (both halves shipped) · still open: `scripts/supabase_fusion_paper.sql` grants
   `FOR INSERT WITH CHECK (true)` to PUBLIC on a forward NAV table — the DB was built without it,
   the file still needs correcting or the next person to run it re-opens public writes.

   Migration now applied (RLS on, anon revoked); `/health` gained
   `data_layer.strategy_library`; `tests/test_strategy_durability.py` 4/4 in preflight. Kept OUT of
   `degraded` on purpose: losing durable research does not make the API unhealthy, and conflating
   them would either 503 a healthy API or bury data loss under a green tick.
   **Service_role RESOLVED on Railway 2026-08-09** (see risk #1 below) — Railway-side writes work.
   `/health.strategy_library: pg_configured:true, degraded:false, total:0, last_ok_ts:null` (no
   records yet because no record has been written since the migration). **Mac-side backfill remains
   P2** awaiting local `.env` service_role key (Jazz's call). DUAL_WRITE=0 flip safe to schedule
   once first record lands and Postgres ≥ Redis is verified.
   **Task #20 "VDB 落库" was logged COMPLETE but only the asset half landed** — `asset_embeddings`
   72 rows, strategy side absent. A half-migration recorded as done is how the next agent stops looking.

   **(b) Tables that exist but are empty.** `asset_embeddings_history` (risk #1) ·
   `risk_meter_history` 0 rows (M-WO-D2) · **`decisions` 0 rows / `entities` 1 row.**
   ARCHITECTURE.md says the deepest object is the entity-and-decision, not the asset; that is where
   the claim lands, and it is empty. **Either wire them or demote the claim — an empty table cannot
   carry an ontological argument.** `signal_outcomes` also ends 2026-05-03, so the response surface
   omits the last 3 months.
   VERIFY: `select count(*) from strategy_records;` → 0 ⇒ backfill pending ·
   `curl -s $BASE/health | jq .data_layer.strategy_library.degraded` → true ⇒ writes not durable ·
   `select count(*) from decisions;` → 0 ⇒ ontology claim still unbacked
   OWNER: Jazz (service_role → risk #1; judgement call on the ontology) · Seth (backfill, extend
   signal_outcomes) · Minimax-A (M-WO-D2)

4. **🟢 ① beta_core: v2 inception LIVE 2026-08-09 13:57Z.** `/internal/beta-core-clock`
   returns `{"configured":true,"marks":1,"started":true,"inception":"2026-08-09",
   "last_mark":"2026-08-09","days_since_mark":0,"missing_days":0,
   "gate_days_remaining":59,"stalled":false}`. Migration ran (v2 row present),
   service_role works (`/health.strategy_library.pg_configured:true, degraded:false`),
   the loop fires and writes. **60-day SHIP-ready gate opens 2026-10-08** (was
   2026-10-初 per OVERSIGHT §3). Kept here as a verification record + monitor; if
   `marks` stops advancing or `stalled:true` flips back, escalate P0.
   VERIFY: `curl -sm 15 -H "X-Internal-Token: $INTERNAL_TOKEN" "$BASE/internal/beta-core-clock"`
   ⇒ `marks≥1, started:true, gate_days_remaining:59-58-...` ⇒ loop firing.
   `stalled:true` ⇒ escalate P0.
   OWNER: Seth (verify) · Jazz (service_role → resolved 2026-08-09)

   *Original entry, for the record (kept as the lesson, not the status — see header above).*
   S-103 + S-105 refuted the ④-layer cross-sectional market-neutral L/S construction (β confounded
   across all 5 tiers, cost 4.6 %/yr > ~3 % best-case effect). **3 of 5 live L/S paper books
   (causal_paper / combined_book / scalable_paper) demoted to RESEARCH RECORDS on 2026-08-08**
   (commit `fc4d331`). The product book `beta_core_paper` (commit `121b54c`) is the only forward-clock
   with a SHIP floor in mind: equal-weight hold-the-panel (no short, no neutralisation) + ex-ante
   vol target + ⓠ regime override caps gross at {0.0, 0.5, 1.0, 1.3}, marked daily to Supabase
   `beta_core_nav` with `benchmark_nav` alongside `nav` so excess is arithmetic. S-123 fix in code
   (commits b8af18b + c0516f9) AND migration `scripts/supabase_beta_core_reinception.sql` BOTH
   deployed & applied by 2026-08-09 13:57Z. **A book that is silent cannot be told from a book
   that is alive but writes were dropped on the floor (S-105 redux) — the silent period
   (2026-08-08 → 2026-08-09) was both; the S-123 fix was the half that was visible. The migration
   was the other half, and was the harder dependency to see because it sat in Supabase, not in
   code.** Full audit (S-103, S-105, S-106, demotion reasoning, anti-amnesia state recovery,
   S-123 inception identity) lives in OVERSIGHT_2026-08.md §0 + §3 + §7 + REFUTATION_LEDGER.md S-124.
   · Seth (verification probe — see VERIFY; re-run once Jazz pastes key) · Minimax-A
   (M1: keep T1 engine push alive — Mac T1 health drives this loop's panel).

5. **🔴 CoinGecko 日线整体错位一天 (S-191, 2026-08-20).** 我们 `trade_date=2026-08-19` 的
   BTC close 是 **64,686.30**;Hyperliquid 的 **08-18** close 是 64,696,08-19 是 69,323。
   ETH(我们 1,916.40 / HL 08-18 1,916.8)、SOL(77.00 / 77.036)同样。**写入端用【写入日期】
   打标签,不是【K线日期】** —— 07:49 跑的 loop 把昨天的收盘记在今天名下。
   影响:coingecko 全部 25 个 symbol 的收益序列整体滞后一天 · 与 `binance_hist`/`eodhd` 拼接
   就是两套日期口径的 splice(**S-106 在日期轴上的重演**)· 所有纸面账本 mark 晚一天。
   **这是我今天回答"暴涨抓到没有"时答错的原因** —— 库里说 08-19 BTC +0.30% 是平的,
   HL 说 +7.15%,ETH +17.57%。**Bar 知道自己是哪天,写它的进程不知道。**
   缓解(已做):`hyperliquid` 采集器上线,日期取自 candle 自带 epoch,`ohlcv_daily_canonical`
   的 source 优先级里 hyperliquid 已经排在 coingecko 之上,所以有 HL 行的地方会自动改用。
   **未做:coingecko 写入端本身没改,历史也没回补(那是改写历史,需要决定)。**
   VERIFY: `curl -s -X POST https://api.hyperliquid.xyz/info -d '{"type":"candleSnapshot","req":{"coin":"BTC","interval":"1d","startTime":1755648000000,"endTime":1755907200000}}' -H 'Content-Type: application/json' | python3 -m json.tool | head -20`
   → 对比 `select trade_date, close from ohlcv_daily where source='coingecko' and symbol='BTC' order by trade_date desc limit 3;`
   两者应当同日同价;若我们的 D 等于 HL 的 D−1,bug 仍在。
   OWNER: Seth(写入端 + 是否回补历史 → 需 Jazz 决定)

6. **🟢 S-104 T2 fan-out fix VERIFIED IN PRODUCTION 2026-08-09 07:05Z.** `git_sha=5a54d1c1`
   is the live build (24.6 min uptime, last_cis_push 221s ago). `t2_branches` reports
   `fanout_total_ms=634` (well under 12 s budget), `degraded_branches=[]`. Served
   `/api/v1/cis/universe`: `timestamp=2026-08-09T07:02:27.674901Z, data_age_s=70.8,
   stale=false, t1_count=43, t2_count=15, source=merged, macro_regime=Tightening,
   regime_confidence=0.72`. `/internal/loop-health` shows ALL 7 stages `flowing`
   (compute/serve · store/hot · data completeness · ingest freshness · upstream causes ·
   outcomes→conviction · narrative/NMA). `/internal/health-summary`: `mac_mini_push:
   ok - 71s ago`. Two `/cis/universe` calls 35 s apart show `timestamp` advancing
   normally (70.8s → ~110s) and `stale=false` steady. **This entry stays here as the
   verification record; the original "UNVERIFIED IN PROD" hypothesis is settled.**
   **What remains (fix-ladder steps 3+4, not in scope of S-104):** T2 still runs inside
   the request path; 24 h data still runs inside the build. These are different problems.
   VERIFY: `curl -sm 15 $BASE/api/v1/cis/universe | python3 -c "import json,sys;
   d=json.load(sys.stdin); print(d['timestamp'], d['data_age_s'], d['stale'], d['t1_count'],
   d['t2_count'])"` ⇒ should print a recent ISO timestamp, age <300s, `False`, 40+43+,
   10+15+. OWNER: Seth (re-verify if any of the three: build, T2 fan-out, or /health
   payload change)

---

**🟢 S-104 T2 fan-out fix verified in production 2026-08-09 07:05Z** — promoted from
   OPEN RISK #7 to LANDED. The per-branch budget fix lands cleanly:
   `t2_branches.fanout_total_ms=634` (under 12 s budget), `degraded_branches=[]`,
   `last_universe_build.total_ms≈5 s` steady, served timestamp advances 70→110 s
   over a 35 s gap, `stale:false` steady. `/internal/loop-health` shows all 7 stages
   `flowing` (compute · store · data completeness · ingest · upstream causes ·
   outcomes→conviction · narrative). `mac_mini_push: ok - 71s ago` matches the
   served timestamp within seconds. The original "build never completes" failure
   mode is gone. *(fix-ladder steps 3+4 — T2 outside request path, 24h data outside
   build — are not in scope of S-104.)* **Lesson to write up: a 56-min stalled payload
   read as a slow endpoint — measurement (S-104) found it was a never-completed build;
   preflight is the only place that re-verifies the fix in production, so the
   `/health` `t2_branches` block stays load-bearing.**

**🔴 ① beta_core paper book — clock STALLED, not 1 day old but 0 days old.** OPEN
   RISK #4 promoted from "1 day old" to "never marked." `/internal/beta-core-clock` returns
   `marks:0, started:false, gate_days_remaining:60` and the S-123 fix (commits b8af18b +
   c0516f9) IS deployed (`git_sha=5a54d1c1`). The migration that adds the
   `inception_id`/`void_reason` columns and unblocks v2 SELECT has not run —
   blocked on service_role (OPEN RISK #1). A book that is silent cannot be told from
   a book that is alive but writes were dropped on the floor (S-105 redux) — *and
   this is a re-inception, so the lesson compounds: the S-123 fix INCLUDED a
   migration for exactly this reason, but the migration needs service_role which is
   the OPEN RISK #1 dependency. A code fix without its data migration is half a fix.*

---

## 2026-08-27 收口 — 跨 lane 半成品做完 + S-244

周末 token 用尽时 Minimax 以 Seth 身份接手,留了一批未提交的改动在同一个工作树里。
本轮把它们**做完并推齐**,而不是绕过关卡:

1. **重建 Vite bundle。** `dashboard/src` 最新 08-27 00:33（S-243 的 regime 拼写
   修复 + `agent.jsx` 去掉硬编码 `'Risk-Off'`），`dist` 停在 08-25 16:30 ——
   **修好的东西一次也没被打包。** Minimax-B 的 bundle-freshness 关卡拦对了。

2. **S-244:测试注册缺口。** S-243 台账写着「回归测试:
   `tests/test_one_regime_one_spelling.py`（13 passed）」,而 preflight 里**没有
   一行提到它**。顺查:`tests/` 75 个文件里 **9 个从未被引用** —— 74 条绿断言
   守护空气,`test_factory` 9 条红断言无声地烂着。全部注册,并加
   `tests/test_every_test_is_registered.py`（registered / exempt / orphan 三值 ＋
   「调用方式必须匹配文件形式」）。现在 **73 registered · 1 exempt · 0 orphan**。

   这是「一个形状」的**第 32 条**,压的是验证装置自己:
   **守卫写了 vs 守卫被执行 → 一个「有测试」**。

   那条守卫的分类器**我连错两次**（先"有 def test_ 就算 pytest 式"刷出 50 条假
   阳性,再"__main__ 必须有 sys.exit"刷出 8 条,含 `test_strategy_discipline`）。
   两次都是 `tests/_source.py` 记的同一个错法:**匹配了模式,不是构造。**
   所以它自带合成样本负控制,分类器坏了先响,不报结论。

3. **S-245:几何基底的写者。** 轨 A 第一件。按「先读消费者再写生产者」先读现状,
   读出来的比预想严重:

   - **仓库里没有任何代码写 `market_state_vectors`** —— 那 582 行来自 Mac 侧工具。
     它是唯一一张没有可复现写者的表。
   - **582 行里 568 行(97.6%)混了价源**,229 行含 `yfinance`(已死),
     568 行含 `coingecko`(S-195 禁用)。入口是 `build_l1_observations.fetch_panel()`
     里一句**没有 source 过滤**的查询 —— 同一天同一标的,后到的源静默覆盖先到的。
   - 2025-01 之后 `ohlcv_daily` 有 **17,876 个 symbol-day 存在 ≥2 个源**,
     **平均差 190.6bps**,最大 5,506bps。所以 `vol_mkt`/`vol_of_vol`/`downside_ratio`
     量的是**换源跳变**,不是二阶矩(S-106 原话)。
   - `n_symbols` 在 **25↔75** 摆动 —— 横截面维在变动成员上算,
     「广度下降」与「面板少了 30 个标的」同一个数。

   新写者 `src/data/vector/market_state_writer.py`:单源 · 定盘 · 一次标准化 ·
   **写前地板**。而地板当场逼出一个我本来会静默做错的选择:默认起点从 2018-06
   (只剩 **8 个达标标的**,写者拒绝)改到 2022-01(1,693 天 / 127 标的,
   深度 ×2.9)。另把 `fng`/`oi_mcap`/`stable_supply_chg` 从完整度分母摘出
   (全库 81 张表,**没有任何一张**持有它们)—— 一个永远达不到的上限不携带信息。

   变异测试:五个变异,**「`if False:` 掉地板」连着打穿我两版守卫** ——
   第一版验「那行代码在不在」(AST 能看结构,看不到可达性),第二版的夹具
   同时触发三条地板、分不出是哪条在起作用。第三版每条地板配独立夹具 + upsert 探针,
   五个变异全数打回。

4. **S-246:我写的错误信息说不出错在哪。** dry-run 回来是
   `error / reason: "Supabase 读不到,offset=0"` —— **四个原因塌成一个 None**
   (凭证没设 / 断路器打开 / HTTP 4xx / 传输失败),而那句话里我**当场引用了
   `(S-180)`**,也就是「读失败 ≠ 读到空」那一课。引用一条教训和执行它是两件事。

   根因在环境:**仓库里没有任何代码为 `src/api/store.py` 加载 `.env`** ——
   Railway 上是真环境变量,Mac 上裸跑 `python3 -c` 时 `os.getenv` 读到空。
   修成 `SbRead(rows, reason)`,四条失败四句互不相同的话,凭证那条直接给补救命令。
   变异(四句压回一句)打红 5 条。

   **今天第十次同一个形状,而这次是我一小时前写的代码。** 结论不是「要更小心」,
   是:**每写一个返回 Optional 的读函数,当场问一次调用方需要分开几种失败。**

5. **S-247:安全检测 —— 8 个 SECURITY DEFINER 视图把数据层交给了 anon。已修。**

   RLS 本身全绿(67 表全开、零 anon 写权限、11 个 SECURITY DEFINER 函数对 anon
   全部 EXECUTE=false)。**而 8 个视图以属主身份执行,RLS 不适用。** 切到 anon 实跑:

   ```
   底表 signal_outcomes        0 行  │  视图 signal_outcomes_unified   7,834 行
   底表 ohlcv_daily            0 行  │  视图 ohlcv_daily_canonical   485,352 行
                                     │  视图 ohlcv_venue_spread      488,607 行
   ```

   负控制:同一 anon 角色下 5 个 `security_invoker` 视图**全部返回 0** ——
   原因隔离到 SECURITY DEFINER 这一个属性。`signal_outcomes_unified` /
   `asset_embeddings_latest` 正是「不可以免费暴露」的挖掘成果。

   已 `alter view … set (security_invoker = on)` × 8。前置验证:前端不直连
   Supabase、后端持 service_role;改完 service_role 视角行数**逐个不变**。

   **更正既有记载**:`CODE_CHECK_2026-08-09.md` 说 anon key「打包进前端」——
   实测 `dist/*.js` 里没有任何 JWT,只剩 `external_probe.sh` 一处。

   **次发现**:`test_no_stack_leakage_on_user_surfaces.py` 每次都绿,而它的 5 条
   断言**全在扫前端厂商名**,Python API 不在范围内 —— `src/api/` 里 21 处
   `HTTPException(detail=str(e))` 从没被看过。S-244 的形状落在安全面上。
   两处无截断的已修,其余 19 处冻结,新增 `test_exception_text_never_reaches_the_client`。

   **未修留档(按严重度)**:① webhook SSRF(认证后,带 120 字节读取预言机)
   ② `INTERNAL_TOKEN` 用 `!=` 非恒定时间比较 ③ 依赖 23/24 行 `>=` 不固定
   ④ npm 14 条中仅 `lodash` 真进 bundle ⑤ **`pip-audit` 沙箱超时未完成 ——
   未检查 ≠ 干净,需 Mac 上补跑**。

6. **S-248/S-249:「我们不是有几个赚钱的吗」—— 有,而且页面把它盖掉了。**

   ```
   STRONG_OUTPERFORM  n=  7  α30=+4.99%  胜率 71.4%   ← journal era
   STRONG OUTPERFORM  n=134  α_beta_adj=+7.99%  胜率 50%  ← legacy era 独立复现
   ```

   **但那 7 个没有一个用可信价源测出来。** 出口价源 83/95 被禁
   (coingecko market_chart S-195 / yfinance 已死 S-230);可信子集只有 12 行,
   而它的 ret30 是 **+1.64%** vs coingecko 那 38 行的 **−13.38%(差 15pp)**。

   加上两个测量错误:**退出规则均值 8 天而判定窗口 30 天**
   (23 个 WIN 里 12 个两者符号相反 —— 我们在赢的仓位赚钱前砍掉了它);
   **统计条四个数用三种度量而不标注**。

   > **那个 −26.19% 既不是坏消息也不是好消息 —— 它是一个不可测量的量,
   > 被渲染成了一个可信的数。** 而它指向自我贬低,所以没人怀疑过它。

   已建 `src/data/signals/track_record.py`(两种度量分开 · 价源四分类 ·
   可信样本 <30 给原因不给数)、`signals.py` regime 分组前强制 strict 规范化、
   响应加 `measure_basis` 逐项声明口径。

   **S-249:修 ④ 时我写了仓库里的第四个 regime 规范化实现**,是
   `test_regime_write_path` 挡下来的,不是我发现的 —— 而同一天早些时候我刚在
   路由展平上正确复用过既有实现。**知道一条规则,和在下一个场景里认出它,
   是两件事。** 给它写守卫时又被自己的 docstring 打红(引用了反面例子),
   `tests/_source.py` 那一课今天踩了两种拼写。

7. **🔴 S-251:两个可信加密价源已死,而探针报 `fresh`。** 做价源回填时撞到的。

   ```
   2026-07-27  binance_hist 261 标的 → 07-28 掉到 221 → 08-09 掉到 1(只剩 BCH)
   08-09 起连续 19 天,每天只写一个标的
   ```

   `supabase_ohlcv_daily_freshness()` 的全部查询是
   `order=trade_date.desc limit 1` —— **全表一行,不分源不分标的**。
   BCH 天天把 max 推着走,coingecko 也在写,于是 `/internal/data-freshness`
   报 **`verdict:"fresh", age_days:0.5`**。那个探针的 docstring 写着自己
   就是为 silent pipeline death 建的,并列了三次前科 —— **它抓不到第四次。**

   ```
   coingecko    0d  25/25  flowing  ← 但 S-195 禁它做收益
   eodhd        1d  33/33  flowing  ← TradFi,可信
   hyperliquid  4d   0/177 DEAD
   binance_hist 7d   0/212 DEAD
   ```

   **加密侧没有任何可用于收益的价源在更新。** 后果:S-245 的写者跑通也只能
   产出 7 天前的基底(budget 2 天);S-248 里 41 个 crypto 行只有 20 个可重算。

   已建 `source_freshness.py`(按覆盖率判活 · 按域给判决 · 五值)+ RPC
   `ohlcv_source_coverage()`(**SECURITY INVOKER,只授 service_role**,
   anon 实测被拒 42501)。同一模块我犯了三次同样的错:全局 ok 掩盖整个域、
   差点每周六狼来了(`main.py` 里那段警告一字不差地描述了我正在写的 bug)、
   变异测试打穿一条"验占位符而非验属性"的断言。

   **🔴 P0 给 Jazz/Minimax:采集为什么在 07-28 和 08-09 两次掉档。这不是工程活。
   在它恢复之前,`/quant` 上任何加密数字都还是噪声上的数字。**

**分工(Jazz 2026-08-27)**:价源回填我做;**退出规则对比发 Minimax-C**。

**下一步**:在 Mac 上 `set -a; source .env; set +a` 后重跑 dry-run,先看
`panel` 的三个数(`n_symbols` / `coverage` / `excluded`)再跑真的。
判据:`/internal/vdb-health` 连续 7 天 `overall: flowing`,且 `coherence` 只有一个 pass。

---

## History moved out (S-165, 2026-08-15)

`## LANDED` and `## Building log` now live in **`PROJECT_STATE_LOG.md`** — append-only,
never read at session start. They were 266,028 of this file's 315,708 characters, and both
described themselves as history in their own headings ("kept for the lessons, not for the
status"). CLAUDE.md tells every agent to read this file on start; that was ~99k tokens of
cold-start tax per lane per session, most of it settled.

Look there for: what landed and why, the terse build log, the lessons behind each fix.
Do not read it to find out what is true now — that is what the sections above are for.

## North star (1 line)
We are the **judgment substrate** — hard-to-verify upstream intelligence (influence → quality
propagation, 出圈/proximity-to-cause) that we verify ourselves and hand over with provenance so
other agents can trust it. Full autonomy is the partner's game, not ours. Soul: `ARCHITECTURE.md`.

## What we're building (the PRD-lite)
1. **CometCloud fund** — AI-curated crypto FoF, Hong Kong regulated, performance-only.
2. **The intelligence substrate** (the moat + a sellable product):
   - **CIS** — 5-pillar quality score, per asset class, regime-neutral grade + regime as a
     separate exposure axis (GRADE-ALIGN Option B).
   - **cause_proximity / 出圈** — how far a consensus has diffused (fragility).
   - **Risk Meter** — turns grade + fragility + conviction into position sizing.
   - **Edge map** — the Glassnode-tier product: expected 30d benchmark-relative alpha per
     signal tier × risk gradient, every cell a real outcome with sample size.
   - **Provenance + track record** — so a consuming agent can *defend* a decision.
3. **The self-tuning loop** — Sense → Synthesize → Judge → Act → Learn → back into Judge,
   recalibrating conviction daily from our own outcomes.

## Core validated findings (from our own data — don't re-derive, cite these)
- Signal is **monotonic** in 30d benchmark-relative alpha: STRONG OUTPERFORM +3.3% → OUTPERFORM
  −0.4% → UNDERWEIGHT −1.2% → UNDERPERFORM −1.8%. It ranks correctly. (`TRACK_RECORD_2026-07-01.md`)
- Edge is **regime/gradient-conditional**: long top tier in risk-ON (deep-on +10.5% / 100d,
  +26.8% / 11yr backtest); short bottom tier in risk-OFF (+6% deep-off). Neutral tape → shrinks.
- **11-year backtest (our OHLCV) confirms** the long-leaders-in-risk-on structure across cycles.
- Long edge **concentrates per asset**: ETH (46 signals, +13.8%), LINK, ARB, LDO. HYPE too new.
- Discipline (大象无形): ranking stable, tradeable *direction* is regime-conditional; N-gate
  everything; never trade a frozen factor.

## Architecture snapshot
- **Serving** = Supabase (lean; what API/agents read). **Warehouse** = local drive
  `/Volumes/CometCloudAI/cometcloud-local/_data/` (heavy: 11yr OHLCV, CIS-historical, backtests),
  mirrored to `Shadow/` so Seth can READ it. Seth writes Supabase only; Minimax owns the drive.
  (`MINIMAX_SYNC.md §WAREHOUSE`)
- Ownership: Seth = `src/` + Railway + Supabase serving. Minimax-A = Mac data/ops + drive.
  Minimax-B = NautilusTrader. Minimax-C = freqtrade. Jazz = decisions + push + capital.

## Where we are — in-flight & blocked (by owner)
**Seth (me):**
- ✅ done: cause_proximity, Risk Meter, conviction tilt (self-tuning), provenance, benchmark-
  relative outcomes, outcome tracker on own-data, track record + edge map (tables+endpoints+MCP),
  P0/P1 fixes, T2 base-weight alignment.
- ✅ HOLD RELEASED (2026-07-05): `cis_provider.py` T2 weights — Minimax-A shipped T1 #5 (17/17
  classes canonical, MD5-identical Live↔Shadow). Seth step-2 verified: T2 `_BASE_WEIGHTS` byte-
  identical to CIS_BASE_WEIGHTS.md AND T2 grades on regime-neutral raw = Σ base×pillar (Option B);
  L1 test vector → raw 67.0 matches T1 acceptance. **Now URGENT to deploy** — T1 is live/next-tick
  canonical while Railway T2 still runs the OLD table → live divergence until `cis_provider.py` ships.
  Jazz commits it in the same push as the sleeve fix (no longer needs to be separate).
- ✅ COMMITTED, needs push: edge-map batch (signals/store/mcp + HANDOFF) — **HEAD is 2 commits
  ahead of origin/main.** Jazz runs `git push origin main`. (Verified via git rev-list 2026-07-05,
  NOT memory — the summary wrongly said "staged/blocked".)
- 🟡 uncommitted (2026-07-05, Loop Watch fix) — BLOCKED by sandbox `.git/index.lock` (can't unlink,
  OS perms); Jazz clears lock + commits `trading.py` + `risk_meter.py` + `CLAUDE.md` + `PROJECT_STATE.md`:
  - `trading.py`: (a) bogus tp/sl flag guard (stop_loss/take_profit=0 made `price>=0` fire
    tp_triggered on every METER_REBAL position → false "exits stalled" alarm); (b) **risk
    circuit-breaker** `REBAL_MAX_ADVERSE_PCT=-20%`, NOT churn-gated; (c) regime-no-short breaker.
  - `risk_meter.py`: **regime-gated shorts** (`_SHORT_OK={Risk-Off,Stagflation}`, `shorts_allowed`
    threaded through build_risk_meter) — shorts only in true falling-market regimes. Self-test extended.
  - EXCLUDE from this commit: `cis_provider.py` (held for T1 #5), `requirements.txt` + `src/research/nautilus/` (Minimax's).
- 🟡 uncommitted (2026-07-06): `cause_proximity.py` — **season lifecycle consumed** (Jazz money
  insight + Minimax §BOARD #5): `momentum` season DEPRESSES out-of-circle risk ×0.55 (ride the
  出圈 wealth-creation window), `stale` ELEVATES to floor 0.72 (window closed). Flows into sizing
  via Risk Meter (verified: momentum name +19% weight vs stale). Dormant until D3 data lands
  (query_id 7891077). No-cost strategy win. Ready to commit + push (Mac-side).

**Strategy direction (no new cost — Jazz 2026-07-06 "先赚到钱再加"):**
- **H1 finding (research lane):** composite CIS 7d forward-return IC is NEGATIVE in Risk-Off/Risk-On/
  Stagflation, POSITIVE only in Tightening, flat in Easing → the CIS gate is directionally INVERTED
  in 3/6 regimes; it works as a RISK FILTER, not a return predictor. Validates regime-conditioning
  (edge map + regime-gated shorts + season already do this). **H2 = per-regime gate direction+magnitude.**
  ⚠️ Do NOT unilaterally invert the production Risk Meter on H1 alone — wait for H2's confirmed
  direction table (research lane in-flight); premature inversion risks the live book.
- **H2 design DONE** (`docs/H2_REGIME_GATE_DESIGN_2026-07-06.md`): reframe = separate CIS-as-ranking
  from regime-as-beta-timing; do NOT invert CIS in prod. Blocked on Phase 0 = fix the noisy regime
  detector (Minimax-A). Immediate-safe changes: drop CIS floor→eligibility in Easing (flat IC),
  shrink gross in low-confidence regimes.
- **H2a script DONE** (`src/research/cis_regime_studies/h2a_relative_ic.py`) — benchmark-relative IC
  test (is the sign-flip beta artifact or real reversal). Runs Mac-side (needs OHLCV panel + scipy).
- **season lifecycle EXTENDED** (`cause_proximity.py`): full pre-出圈 accumulation stages
  (capitulation/dry_up/spring_test/early_markup) + momentum/stale, cold→hot risk curve verified
  (dry_up lowest 0.168 → stale highest 0.720). Season vocab contract handed to Minimax (§MINIMAX_SYNC).
- **current-band read + posture DONE** (`signals.py` + `main.py` + MCP): `/api/v1/signals/current-band`
  computes today's risk-gradient band (BTC 30d) → per-tier expected alpha NOW → actionable **posture**
  (net_bias + gross_scale + confirmation), sample-size-guarded (thin cell → dampen + flag). Persisted
  daily to Supabase `regime_band_log` (created; cols incl net_bias/gross_scale) via `_band_log_loop`
  → flows to Mac warehouse (Minimax adds it to the drive mirror). MCP tool `cometcloud_get_current_band`.
  Posture is ADVISORY (positioning language) — not wired to force live sizing (that needs Jazz nod).
- **Conviction Fusion #1 DONE** (`src/data/cis/conviction.py` + `/api/v1/cis/conviction` +
  `cometcloud_get_conviction` MCP): the single per-asset verdict fusing regime-neutral QUALITY ×
  cause-proximity (in-circle vs 出圈 + season) × edge-map expected alpha (tier × TODAY's band, real
  outcomes) × EXECUTABILITY. Ranked by signed edge; sample-size gated; illiquid names discounted
  (a B+ you can't size ≠ a core overweight). Verified on live universe. **Flagship Diagnose enriched**
  to consume it — per-holding conviction/direction/action + book `illiquid_pct` + verdict note
  ("X% in illiquid names — can't build/exit size"). This is the actionable output of all the mining.
- 🟡 Moralis D3: key works live, but holder map empty → likely `/erc20/{addr}/owners` is a premium
  Moralis endpoint on this plan (or field mismatch). Added `/api/v1/signals/holder-map` diagnostic
  (uncommitted) — push it, hit it, read `probe_error` to decide (upgrade Moralis vs Helius/Bitquery).
- **Edge-map SHRINKAGE DONE** (`src/data/signals/edge_shrinkage.py`) — the hard statistical problem:
  100 days = wildly uneven cells (n=1..1672); a raw thin cell is pure noise (OUTPERFORM/deep-off
  −64% on n=3). Empirical-Bayes shrinkage: two-way ADDITIVE prior (tier+band, captures the monotonic
  "rises with risk-on" structure) + James-Stein weight `n/(n+K)`, K by ROBUST (median) MoM. Result:
  well-sampled cells keep 76–90% own value, thin/noisy cells collapse to the structural prior, grid
  becomes monotonic + denoised (K≈184). Wired into `compute_current_band` (posture/conviction now read
  the SHRUNK alpha) + conviction's hard n-gate relaxed (n → confidence, not discard) + edge-map endpoint
  exposes raw/shrunk/weight/prior. This is AQR/Millennium-grade rigor making the surface honest on thin data.
- **H3 edge-map BACKFILL DONE** (`h3_edge_map_backfill.py`) — the root-cause fix for "only 100 days"
  (Jazz: don't use it as an excuse). Applies CURRENT signal logic across `cis_history` (393d × 40) ×
  OHLCV → ~12k historical signal→30d-alpha pairs → backfills `signal_outcomes` (before live, no clobber)
  → existing refresh rebuilds a robust edge map (thin cells n=1..3 → hundreds). Runs Mac-side (`--write`).
  Phase-2 (Minimax): extend `cis_history` to 11yr OHLCV via CIS reconstruction → h3 auto-covers it.
  **Phase-2 ✅ DONE 2026-07-18** (`scripts/reconstruct_cis_history.py --days 4015` + `scripts/cis_historical_ingest.py`)
  — 75,478 rows, 34 assets, 2015-07-21 → 2026-07-18, ingested into local `cis_history` (run_id
  `historical_11yr_20260718_192540`). Supabase ingest pending service-role key. Full report:
  `reports/CIS_HISTORICAL_11YR_2026-07-18.md`. Schema migration added 4 columns (`macro_regime`,
  `las`, `source`, `data_tier`). Honest gaps: FNG pre-2018-02-01 (neutral fallback), SEI 404 skip,
  newer assets (ENA/STRK/ONDO/TIA/POL) only have post-2022 history.
- **EDGE GATE bridge DONE** (`src/research/strategies/edge_gate.py` + `scripts/export_edge_gate_grid.py`)
  — the intelligence→execution connection Jazz asked for (reference Minimax-B/C strategies). Replaces the
  hand-tuned `REGIME_CIS_FLOOR` (H1: wrong in 3/6 regimes) with `gate(grid, tier, band, side)` reading the
  SHRUNK edge map → allow/block + conviction-scaled size, direction from DATA (short-weak allowed only where
  it empirically pays). Pure module (no pandas/scipy) so it runs inside Nautilus/freqtrade. Grid live at the
  edge-map endpoint (shrinkage confirmed live, K=184). Integration recipe for Minimax-B/C in MINIMAX_SYNC.
- **NOTE: shrinkage is LIVE** (deployed via a Minimax push) — verified on `/api/v1/signals/edge-map`.
- **2026-07-09 EDGE GATE A/B (continuous, per-regime IC) — NEGATIVE for ship**
  (`src/research/nautilus/ls_v1/edge_gate.py`, `src/research/cis_regime_studies/edge_gate_ab.py`,
  `reports/EDGE_GATE_AB_2026-07-09.md`). The continuous `edge = side × IC_regime × z × sigma × sqrt(h) − cost`
  gate (alternative to the empirical grid edge gate above) is wired into LS v1 with `use_edge_gate=True` and
  A/B'd across 4 smoothed dirs × {IS, OOS} × {baseline, edge_gate} = 16 runs. **Edge gate loses in both
  windows across all dirs** (ΔIS PnL −$316 to −$503, ΔOOS PnL −$23). Per-regime IC magnitudes (−0.09 to
  −0.36 smoothed) sit below the AQR noise floor (~±0.24 at n=70); the regime-conditional reversal is
  structurally correct but empirically underpowered. **3 negative results in a row** on per-regime gate
  refinement (H3, H2 magnitudes, this). Keep `REGIME_CIS_FLOOR` as production gate. Phase 1 ship
  (smoothed regime labels, no floor changes) is the correct next move. Pivot edge-gate formula to H3.2
  sizing-multiplier when ≥6mo OOS data accumulates.
- **2026-07-09 H3.2 conviction-weighted SIZING A/B — POSITIVE for ship as opt-in**
  (`src/research/nautilus/ls_v1/strategy.py` `use_h32_sizing` config +
  `_h32_sizing_multiplier()` + `create_order_qty` applies multiplier;
  `src/research/cis_regime_studies/h32_sizing_ab.py`;
  `reports/H32_SIZING_AB_2026-07-09.md`). Per H3: "conviction is a sizing signal,
  not a gating signal." H3.1 (gate-multiplier) lost because the floor band is a
  knife-edge. H3.2 sidesteps that by leaving the gate at `REGIME_CIS_FLOOR` unchanged
  and scaling POSITION SIZE by today's conviction: `trade_size × (floor + (cap−floor) × c)`.
  A/B'd across raw + modal_recency dirs × {IS, OOS} × {baseline, h32_sizing} = 8 runs.
  **H3.2 wins per-trade PnL in ALL 4 runs** (Δ IS $/pos +$1.79 to +$2.14, Δ OOS $/pos
  +$0.10 to +$2.25). Trade count unchanged (gate unmodified). **First POSITIVE result
  in the H-series** (H3 prototype / H2 magnitudes / edge gate all lost). Mechanism =
  Millennium soft-sizing: let the signal through, weight by confidence. Ship as opt-in
  via `LSV1_USE_H32_SIZING=1` (floor/cap configurable via env).
- **2026-07-10 H3.2 sizing FLOOR/CAP SWEEP — REFINED positive; bump default cap 1.5 → 1.75**
  (`src/research/cis_regime_studies/h32_sizing_sweep.py`,
  `src/research/nautilus/ls_v1/strategy.py` `LSv1Config.h32_size_cap` default bumped 1.5→1.75,
  `reports/H32_SIZING_FLOORCAP_SWEEP_2026-07-10.md`). The `[0.5, 1.5]` default was ad-hoc.
  Swept 6 (floor, cap) variants × raw + modal_recency × {IS, OOS} = 24 Nautilus runs.
  **Key insight:** IS Sharpe is INVARIANT to (floor, cap) at this sample size — both
  per-trade mean AND per-trade std scale linearly with size, so E[X]/SD[X] is invariant.
  The differentiating metric is **per-trade PnL**, which scales monotonically with cap:
  cap 1.25→1.5→1.75→2.0 gives raw IS $/pos $+5.74→$+6.85→$+8.02→$+9.01.
  `cvx` (linear through origin) is the WORSE outcome — zero size on low-conv days removes
  the protective trades. `d0.25` matters little (median conviction ≈ 0.93, floor rarely bites).
  **Pareto decision:** bump production default cap 1.5 → **1.75**. Captures +37% PnL
  on IS (n=58 reliable) with no Sharpe penalty. Cap=2.0 is research ceiling (diminishing
  returns + Sharpe decay in modal_recency 0.066→0.061). Cap=1.25 too tight. **Re-verify
  after ≥6mo OOS data accumulates.**
- **2026-07-10 H3.2 PORTFOLIO-LEVEL MaxDD analysis — CORRECTIVE FINDING (linear lever, not alpha)**
  (`src/research/cis_regime_studies/h32_sizing_portfolio_dd.py`,
  `reports/H32_SIZING_PORTFOLIO_DD_2026-07-10.md`). Aggregated per-trade PnL from
  the 24 sweep runs into portfolio equity curves. **Critical finding:** ALL variants
  have DD/PnL ≈ 0.96-1.00 — capturing 1× the PnL costs ~1× the Max DD. This is the
  expected math when only position size changes (trade list is identical across variants).
  Per-day Sharpe is essentially flat (0.0766-0.0779 raw/IS, within noise at n=58).
  **Revised framing:** H3.2 is a **linear sizing controller**, not an alpha source.
  The "Pareto-balanced" framing in the previous report was misleading — the choice
  between cap=1.0 and cap=1.75 is a **leverage decision**, not a quality decision.
  One mitigating finding: t1.75 has the BEST per-day Sharpe (+0.0008 over def) — within
  noise but consistent with the H3 finding. **Revised recommendation:** keep cap=1.75
  as default but document it as a leverage bump (already shipped to strategy.py).
  Env-var override (`LSV1_H32_SIZE_CAP`) keeps the choice tunable per deployment.
  Corrective addendum added to `reports/H32_SIZING_FLOORCAP_SWEEP_2026-07-10.md`.
- **2026-07-10 H2a benchmark-relative IC test — CRITICAL FINDING (genuine reversal in 3/5 regimes)**
  (`src/research/cis_regime_studies/h2a_relative_ic.py` ran successfully today;
  `reports/H2A_RELATIVE_IC_2026-07-10.md`, raw output `reports/cis_regime_relative_ic_2026-07-06.{md,json}`).
  Tests if H1's sign-flips are BETA artifact (vanish under BTC-relative returns) or genuine
  reversal (persist). **Verdict: GENUINE REVERSAL in 3/5 regimes at 7d** — Stagflation IC_abs=-0.235
  → IC_rel=-0.326 (gets WORSE), Risk-On IC_abs=-0.166 → IC_rel=-0.101, Risk-Off IC_abs=-0.093
  → IC_rel=-0.104. Only Tightening is consistent (both positive, n=216 small). At 30d:
  Easing becomes genuine reversal (was flat at 7d); Risk-On becomes beta artifact (recovers
  to flat under relative). **H2 direction-by-regime is now CONFIRMED necessary, not just
  hypothesized.** Action items: (a) H2 design must populate per-regime × per-horizon direction
  table, (b) H3.2 sizing remains valid as a sizing LAYER (independent of gate direction),
  (c) Phase 1 ship (smoothed regime labels) still valid, (d) empirical-grid edge gate A/B
  should consider per-regime direction. Honest caveats: Stagflation n=195 and Tightening n=216
  small; OHLCV ends 2026-06-07; benchmark = BTC for all crypto (no per-asset benchmark).
- **2026-07-10 RESEARCH RE-PRIORITIZATION ROADMAP** (`docs/RESEARCH_ROADMAP_2026-07-10.md`)
  — based on H3.2 + H3.2 portfolio DD + H2a findings. Tally: 3 STRONG POSITIVES (H3.2
  sizing, DSR swing lineage, causal sleeve), 1 CRITICAL STRUCTURAL (H2a genuine reversal),
  4 NEGATIVES (H3.1, H2 mag, edge gate continuous, A2 falsified). **Phased plan:**
  - **Phase A (HIGHEST PRIORITY): H2b direction A/B** — applies H2a finding directly.
    Per-regime direction table is no longer optional. 8 runs (~2-3 hr total).
  - **Phase B: empirical-grid edge gate A/B** — production drop-in, distinct from failed
    continuous one. Needs (tier, band) snapshot generation. 8 runs (~4 hr).
  - **Phase C: combined gate integration** — H2b + empirical-grid + H3.2 sizing. 16 runs.
  - **Phase D1: SwingOverlay walk-forward OOS** ✅ DONE 2026-07-14 — 4/4 ROBUST,
    V7_MTF recommended for production, V9≡V10 caveat documented. See
    `_data/research/SWING_WALK_FORWARD_OOS_2026-07-14.md`.
  - **Phase D1.5: funding-gate fix + vol-target calibration + 10-pair extension**
    ✅ DONE 2026-07-14. V12b funding-gate fixed (was never firing), V10c vol-target
    calibrated (was no-op), 10-pair universe added. **V7 production, V10c risk-managed,
    V12b regime-overlay.** See `_data/research/SWING_WALK_FORWARD_D15_2026-07-14.md`.
  - **Phase D1.6: forward test 17 weeks post-OOS** ✅ DONE 2026-07-15. All 5
    strategies pass 5/5 OOS criteria on 10-pair universe. V7 forward +$623/+10.39%,
    maxDD 0.99% (improves vs holdout). V12b = V9 (funding too orderly to trigger
    gate — expected). See `_data/research/SWING_WALK_FORWARD_D16_FORWARD_2026-07-15.md`.
    Next: live paper deployment of 4-slot sleeve (V7 50% + V9 15% + V12b 20% + V14a 15%) — D2.2 recommendation, capacity
    stress test at $60k/$600k.
  - **Phase D3: forward-supply unlock event study** — historical evidence without 180d wait.
    5-10 events × 30d post-unlock.
  - **Stop testing:** continuous edge gate refinements, per-regime floor mag tuning,
    gate-multiplier prototypes, edge-map direction (all 4+ negatives).
  - **Single most important thing this week:** apply H2a finding to production gate
    (Phase A). Everything else stacks on top.
- **2026-07-09 CAUSE-DRIVEN BACKTEST infrastructure (B2) — SHIPPED, run BLOCKED on data**
  (`scripts/supabase_migration_cause_history.sql`, `src/data/cis/cause_persistence.py`,
  `src/research/cis_regime_studies/cause_backtest.py`, `reports/CAUSE_BACKTEST_2026-07-09.md`).
  First real test of whether ARCHITECTURE.md "causes predict" (forced-seller short + squeeze-long
  + long-liq short). Cause data has only been live ~3 days — no historical record exists.
  Built the rig (schema + persistence + backtest skeleton + smoke test) but the actual backtest
  needs ≥180 days cause_snapshots_daily + OHLCV panel landing (Minimax-A P1, not started). Live
  snapshot today: 5 forced_seller_short candidates (HYPE/APT/SUI/ONDO/OP), 0 squeeze_longs.
  Discipline: we built the experiment; we cannot shortcut the 6-month waiting.
- ⬜ next: A/B the empirical grid edge gate (separate approach) in Nautilus LS v1; run H3+H2a Mac-side;
  conviction UI; Phase 1 ship (smoothed regime labels); cause-history accumulation (180d).
- 🟡 uncommitted (2026-07-06, GRADE-ALIGN Option B frontend/read switch) — BLOCKED by git lock;
  Jazz commits `cis.py` + `cis_provider.py`:
  - `cis.py` merge: normalizes the WHOLE universe (T1+T2) onto raw quality — `grade = get_grade(raw)`,
    `cis_score = raw`, `regime_adjusted_score` = old adjusted (regime lens preserved), sort on raw.
    Single Railway-side change, NO T1 cis_v4_engine lockstep (both tiers already carry raw_cis_score).
  - `cis_provider.py`: T2 emits the same shape natively (grade on raw, cis_score=raw, +regime_adjusted_score).
  - Verified against live universe: grade==g(cis_score) for ALL assets; 16 grades shift vs regime-baked;
    leaderboard now quality-ranked (PENDLE B+ quality, regime tilt → signal/regime_adjusted).
  - PRODUCT-FACING (grades move, cis_score semantics change) → needs Jazz green-light to push.
  - Minimax note: Railway now overrides T1's pushed `grade` (re-grades on raw at merge, idempotent);
    T1 can later grade on raw natively — identical result, no rush. SCHEMA note in §GRADE-ALIGN.
- ⬜ next: regime-lens UI badge (surface regime_adjusted_score as the visible separate axis) ·
  regime-aware conviction (reads edge map, N-gated) · live "current band" on edge-map · win.html surfacing.

**Loop Watch finding (2026-07-05):** METER_REBAL "rotation stall" was NOT a broken exit path.
Book is stable in flat Tightening regime (target≈held, `reason=none`). Real issue: sleeve holds
shorts on benchmark-underperformers (ADA/ETH still UNDERPERFORM = thesis intact) but trades
ABSOLUTE price while the signal predicts only benchmark-RELATIVE alpha → shorts bleed beta when
tape isn't risk-off (edge-map: shorts only pay deep-off). 12-vs-5 trade_results gap = historical
pre-fix closes, writer healthy. **DECISION FOR JAZZ:** regime-gate shorts (only open shorts when
risk gradient is risk-off) vs keep the −20% breaker as the only guard. Breaker shipped as safety net.

**D3 LIVE = Moralis-on-Railway ✅ (Seth, 2026-07-06):** Jazz connected Moralis; I wired the on-chain
holder tier on Railway — `src/data/cis/holder_provider.py` (registry symbol→contract → Moralis owners →
top10 share + HHI → `stage`; multi-chain incl Solana Phase-2), `_holder_refresh_loop` → Redis `cis:holder_map`,
attached into `cause_proximity` (cis.py). Activates on deploy with `MORALIS_API_KEY` (already set). Verified:
concentrated→stage 0.08→risk down, dispersed→0.79→risk up, confidence 0.85. Covers ONDO/PENDLE/UNI/AAVE/MKR/
LINK/LDO/ARB, graceful D4 for rest. **This SUPERSEDES the Dune path** (query 7891077 → optional Phase-2 history
only; NO Dune purchase needed — the cost question is resolved). Phase-2 = dynamic season/chuquan from Moralis
holder-timeseries (Minimax Wyckoff lane; season contract unchanged).
**Minimax-A:** T1 #5 (per-class weights, patch in §GRADE-ALIGN) · restore drive→Shadow sync · stand up local warehouse + CG/EODHD top-ups
(dominance, mcap, VIX) + 11yr CIS-historical reconstruction · macro brief model (gemma-4-31b-qat +
API thinking-off).
**Minimax-B/C:** backtest the validated hypothesis (regime-conditional long-STRONG / short-UNDER, gradient-scaled).
**Jazz:** bless canonical `CIS_BASE_WEIGHTS.md` · greenlight the edge-map commit + coordinated
GRADE-ALIGN deploy · rotate shared `INTERNAL_TOKEN`.

## Key decisions log (pointers)
- GRADE-ALIGN Option B + canonical base weights → `CIS_BASE_WEIGHTS.md`, `MINIMAX_SYNC §GRADE-ALIGN`.
- Two-tier data landing → `MINIMAX_SYNC §WAREHOUSE`.
- Historical reconstruction from CG Pro + EODHD (FNG synthesized, on-chain proxied by volume) → `HANDOFF_2026-07-02.md §3`.
- Substrate positioning / vectors & movement → `ARCHITECTURE.md`.
- Full session comms → `HANDOFF_2026-07-02.md`.

## Detailed docs index
`ARCHITECTURE.md` (soul) · `MINIMAX_SYNC.md` (coordination, gitignored) · `CIS_BASE_WEIGHTS.md`
(canonical) · `TRACK_RECORD_2026-07-01.md` · `AUDIT_financial_engineer_2026-06-30.md` ·
`ADR-001_loop_architecture_completeness.md` · `HANDOFF_2026-07-02.md` · `scripts/track_record.sql` ·
`scripts/loop_health.py` (daily watch).
