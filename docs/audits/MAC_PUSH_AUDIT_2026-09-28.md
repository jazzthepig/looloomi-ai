# Mac-side push scripts Rule 5b audit — 2026-09-28

> **Lane:** A (Austin / systems)
> **Scope:** `/Volumes/CometCloudAI/cometcloud-local/*.py` push scripts
> **Reference:** S-405 mirror (Railway 端 82 张表 28 张 0 行), Rule 5b 三件套
> **Method:** static read + live query against `https://web-production-0cdf76.up.railway.app/internal/data-freshness`
> **Sandbox:** `python3` + `httpx` + `curl`, no Mac write, no git

---

## 一、Inventory:Mac-side 写入端(cis_push + 7 个 _push + 信号轴脚本)

| # | 脚本 | Mode | Schedule | Target 端点 | Target 表 | 调度者 |
|---|------|------|----------|-------------|-----------|--------|
| 1 | `cis_push.py` | subproc | implicit(cis_scheduler.py hourly cycle) | `RAILWAY_URL/internal/cis-scores` | `cis_scores` | `cis_scheduler.py` hourly |
| 2 | `vector_push.py` | subproc | per cycle (60s) | `RAILWAY_URL/internal/asset-vectors` | `asset_embeddings` (vec 列) | `cis_scheduler.py` |
| 3 | `macro_brief_push.py` | own `--loop` | 30min cadence | `RAILWAY_URL/internal/macro-brief`(or 直接) | `macro_briefs` | dedicated launchd `com.cometcloud.macro-brief` |
| 4 | `asset_embeddings_history_push.py` | subproc | daily | `RAILWAY_URL/internal/mac-write/asset-embeddings-history` | `asset_embeddings_history` | `cis_scheduler.py` |
| 5 | `risk_meter_history_push.py` | subproc | daily | `RAILWAY_URL/internal/mac-write/risk-meter-history` | `risk_meter_history` | `cis_scheduler.py` |
| 6 | `signal_outcome_tracker.py` | subproc | daily (`_A_N2_INTERVAL`) | `SUPABASE_URL/rest/v1/signal_journal` (+ RPC `exec_sql`) | `signal_journal` (+`signal_outcomes` 经 RPC) | `cis_scheduler.py` |
| 7 | `signal_edge_map_refresh.py` | `--once` | daily | `SUPABASE_URL/rest/v1/rpc/<edge_map RPC>` | `signal_edge_map` | `cis_scheduler.py` |
| 8 | `signal_axis_attribution.py` | pure compute | n/a | **none**(compute only) | n/a(产物给 bridge 吃) | n/a |
| 9 | `signal_resonance_attribution_bridge.py` | async | **BLOCKED on Seth `/api/v1/signals/outcomes-raw`** | n/a yet | `signal_axis` / `signal_resonance`(空) | None |

---

## 二、Rule 5b 三件套核对(每行:① 调度者 ✓ ② 判活判据 ✓ ③ 第一行真实数据 ✓)

| # | 1 调度者 | 2 判活判据(producers monitor) | 3 第一行真实数据 | 状态 |
|---|----------|-------------------------------|------------------|------|
| 1 | launchd `cis_scheduler.py` ✅ | ✅ `cis_scores` 174,357 rows, fresh 09-28 | ✅ 09-28 fresh | 🟢 HEALTHY |
| 2 | cis_scheduler 60s cycle ✅ | ✅ `asset_embeddings` 72 rows, fresh 09-28 | ✅ 09-28 fresh | 🟢 HEALTHY |
| 3 | **launchd `com.cometcloud.macro-brief` 30min ⚠️** | ❌ **`macro_briefs` NOT in producers.monitor** | ✅ post-T-018 surgery ≥ 4 rows confirmed | 🟡 **MONITOR GAP** |
| 4 | cis_scheduler daily ✅ | ✅ `asset_embeddings_history` 2205 rows, fresh 09-27 | ✅ 09-27 | 🟢 HEALTHY |
| 5 | cis_scheduler daily ✅ | ✅ `risk_meter_history` 33 rows, fresh 09-27 | ✅ 09-27 | 🟢 HEALTHY |
| 6 | cis_scheduler `_A_N2_INTERVAL` daily ✅ | ⚠️ `signal_journal` STALE 4d(last 09-24, ≥ 3d 陈旧线) | ❌ last write 09-24 → silent-dead 4d | 🔴 **SILENT FAIL**(per S-405) |
| 7 | cis_scheduler daily ✅ | ✅ `signal_edge_map` ACTIVE in active_monitor canary("Q1 daily refresh" 1d) | ✅ covered via canary | 🟢 HEALTHY |

**Observations:**

- **P0:signal_outcome_tracker silent fail** —— `signal_journal` last write 09-24,now 09-28,4 天没写过。期间 launchd 仍在跑 daily。`signal_outcomes` 148d dead(2026-05-03 last)。这是教科书 S-405 静默失败「写完了不通」。
- **MONITOR GAP:macro_briefs** —— writer **active**(T-018 surgery 实测 ≥ 4 rows),但 `/internal/data-freshness` 的 producers.tables 字典**没列**这张表。换言之,如果 macro_brief_push 静默死了,任何人都不会发现。Rule 5b 第一条「3 件套不齐 = 没通」的就义实锤。
- **signal_axis / signal_resonance 表** —— 当前 **0 张存在**(bridge BLOCKED on Seth `/api/v1/signals/outcomes-raw`)。**表都没建** → 监控也无从谈起,这是合规空白,但不违反「写完了不通」(因为「写完了」从来就没发生)。

---

## 三、其他发现

1. **Rule 3b (Ingestion ONE lane) Mac 端大部分遵守** —— Mac `cis_push.py` / `vector_push.py` / `asset_embeddings_*.py` / `risk_meter_history_push.py` 都走 Railway `/internal/mac-write/` 中转,不在 Mac 直接 POST Supabase。`signal_outcome_tracker.py` 是**唯一例外** —— 它直接走 `SUPABASE_URL/rest/v1/signal_journal` + `rpc/exec_sql`。这是 mac-side 违反 Rule 3b 唯一已知例子。Seth 是否有意(因为写入路径调的是 service_role RPC)留作 archival。

2. **S-405 类风险** —— `signal_outcome_tracker.py` daily 跑,但 4d 没新行。这同 S-405「全集 14 个写完了不通」同源:**写入端存活,内容已陈**。`data-freshness` 给了 stale verdict,但没人看(via dashboard),所以没人修。

3. **`macro_briefs` 盲区历史** —— 2026-09-23 (S-405 时点)它已经在 producers.monitor **之外**。Mac 之前抄的是 mb-2(prompt 已旧),但表是活的(`recorded_at` always fresh)。**T-018 surgery 解决了 prompt_version 问题,但仍未解决 monitor 缺口**。

---

## 四、推荐下一个动作(车 T-NNN 卡可拍)

| 卡 | 标题 | 优先级 | 拍板需要 |
|----|------|--------|----------|
| **T-031** | `macro_briefs` 加进 `/internal/data-freshness` producers.tables 字典(S-392 / Seth lane) | 🟡 P1 | Seth 拍 schema + 加一条规则 |
| **T-032** | `signal_outcome_tracker` 4d silent fail 修根因 + 加 `loop_attempt` 记录 per A-408-2 模式 | 🔴 P0 | A 自我执行(Lane-a,allowed_paths 含 Mac)|
| **T-033** | data-freshness 加 stdout-on-stale 告警(dashboard 显式显示) | 🟡 P2 | dashboard side(Seth / B 域)|

**A lane 接下来(无拍板,纯自律):**
1. T-032 自我执行:`signal_outcome_tracker.py:80-120` 修根因(纯文本探查,Seth 拍 preflight 后上)
2. T-002 spec 写(`cis_v4_engine.py` cadence 6h → 1h 的影响分析)

---

## 五、Audit 数据点(供决策素材)

```
cis_scores              fresh, 174,357 rows, last=2026-09-28
asset_embeddings        fresh, 72 rows, last=2026-09-28
asset_embeddings_history fresh, 2205 rows, last=2026-09-27
risk_meter_history      fresh, 33 rows, last=2026-09-27
macro_briefs            NOT MONITORED → BLIND SPOT (post-T-018 ≥ 4 rows confirmed)
signal_journal          STALE 4d, 302 rows, last=2026-09-24  ← silent-fail
signal_outcomes         DEAD 148d, 7743 rows, last=2026-05-03  ← silent-dead
signal_edge_map         OK(Q1 daily refresh canary)
signal_axis             0 tables exist (bridge BLOCKED on /api/v1/signals/outcomes-raw)
signal_resonance        0 tables exist (same blocker)

Mac-side writers: 9 push scripts
- 5 direct subproc of cis_scheduler (1, 2, 4, 5, 6, 7 = 6)
- 1 launchd --loop (3)
- 2 compute-only (8, 9)
```

---

## 六、引用

- **S-405** — 82 张表 28 张精确 0 行 14 张有写入端不通
- **Rule 5b** — 一个写入端落地必须同时交付 ①②③
- **Rule 3b** — Ingestion ONE lane (Seth); Mac consume-only
- **§minimax-b-2026-09-28** — internal_token 36 处 17 文件 audit 镜像
- **`/internal/data-freshness`** — 当前数据基线:`web-production-0cdf76.up.railway.app/internal/data-freshness`(anon-public)

---

**Last updated:** 2026-09-28(A 自落,sandbox only,no Mac / no git writes)
