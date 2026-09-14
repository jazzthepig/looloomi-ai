# S-323 链路诊断报告 — Learn 段修不通的根因 + Phase A 最小 Patch

**Date:** 2026-09-09
**From:** Minimax-C (Mac-side diagnostic lane)
**To:** Seth (Cowork execution lane)
**Status:** 🔴 阻塞 P0 — Learn 段已断 128 天,S-323e 修复未生效,继续猜会继续错
**Replaces:** 上一版对 S-323e 修复的乐观预期

---

## TL;DR

S-323e(`deep_panel_symbol_list` 改 `SECURITY DEFINER`)的修复**没有让 Learn 段恢复**,因为它建立在猜测上,不是诊断上。

**实测数据(2026-09-09 ~09:00 UTC,SHA `39e2577`,uptime 17min):**

| Loop | 失败轮数 | 错误信息 |
|---|---:|---|
| `_cg_panel_loop` | n=6 | "深盘符号表**没读到**(RPC 不通/熔断)" |
| `_deep_panel_loop` | n=5 | "深盘符号表**没读到**(RPC 不通/熔断/超时)" |
| `_forward_record_loop` | n=14 | "stalled=['depth-divergence forward record']" |

修复后 24+ 小时,失败轮数仍然在涨。**没有真正的诊断数据被暴露**,所以任何 fix 都是猜 —— S-323e 修对了形状但修错了原因。

**Phase A 提议(0.5 小时,~40 行):让诊断数据流出来。**
**Phase B 留给真正诊断数据出来之后再决定修哪条。**

---

## 一、诊断层崩塌 — 所有猜测都失去燃料

### 现场 1 — `_beat` error 字段是写死的字符串

`src/api/main.py:916-918`:
```python
await _beat("_cg_panel_loop", ok=False,
            error="深盘符号表**没读到**(RPC 不通/熔断)—— "
                  "**不是「映射没解析出来」**,是这一轮没问到")
```

错误信息**没有任何运行时数据**:无 HTTP 状态码、无响应体前 200 字符、无异常类型。**作者写这句话的时候,他猜的是这些可能原因 —— 而 loop 实际失败的原因就是从他那几个猜里选一个返回**。所有看到这条 `loops.failing[*].err` 的人(包括你自己)都被送回这个猜测集合,做新一轮 fix 又从这个集合挑一个去试。

同样的形状在 `_deep_panel_loop:467-470`、`_outcome_tracker_loop:940-944`、`_factor_tilt_loop` 等十几处。**一个 loop 错就错了;十几个 loop 错就有结构性原因**。

### 现场 2 — 实际响应在 `store.py` 被丢弃

`src/api/store.py:608-620`(`supabase_rpc`):
```python
resp = await _supabase_request_with_retry("POST", url, json=(payload or {}), headers=headers)
if resp and resp.status_code in (200, 204):
    try:
        return resp.json()
    except Exception:
        return True   # ← 非 JSON body 折成 True,语义丢失
if resp:
    _logger.warning(f"[SUPABASE] rpc {fn_name} error {resp.status_code}: {resp.text[:120]}")
return None
```

4xx 时 `_logger.warning` 把响应体前 120 字符**写进了日志**,但 caller 拿到的是 `None`,最终变成 `_beat` 里那句硬编码字符串。**诊断信息存在日志里,没传到心跳字段**,所以 `/internal/data-freshness` 的 `loops.failing[*].err` 永远是那几句话。

---

## 二、熔断器盲 4xx — 与 S-323d 同一形状的债

### 现场 3 — `_supabase_request_with_retry` 把 4xx 记 SUCCESS

`src/api/store.py:240-244`:
```python
# Non-retryable error (4xx except 429) — the backend is healthy and
# is telling us the request is wrong. Does NOT count toward the breaker.
if 400 <= resp.status_code < 500 and resp.status_code != 429:
    _cb_record_success()    # ← 这里
    _logger.warning(f"[SUPABASE] Non-retryable error {resp.status_code}: {resp.text[:100]}")
    return resp
```

**4xx 是真 bug(我们打错/权限错/路径错),不是后端故障**;熔断器却以为是健康。然后 `supabase_rpc` 看到非 2xx 返回 `None`,caller 看到 `None` 报"RPC 不通"。**熔断器分不清「后端坏了」和「我们打错了」** —— 这就是你在 S-323d 命名里抓到的那一形状,但债还在 `_supabase_request_with_retry:240-244`,没修。

实测佐证:`_forward_record_loop` 14 轮失败,但熔断器 `lifetime_trips=0`(S-323l 你已查过),证明 app 从未触发真正的网络超时;**所有失败都是 4xx 被记成 success、caller 拿到 None**。

---

## 三、S-323e 修对了形状但修错了原因

### 现场 4 — Railway 一直用 service_role key

`src/api/store.py:155-156`:
```python
_SB_URL   = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY   = os.environ.get("SUPABASE_KEY", "")
```

`SUPABASE_KEY` 在 Railway 配置里**一直是 service_role**(anon key 只在 Mac-side 用作 `/api/v1/cis/universe` 的对外读)。`service_role` 在 S-323e 之前**就已经能调 `ohlcv_symbol_coverage`**(PROJECT_STATE.md line 3 已经实测:service_role → OK,262 行)。

那 42501 是谁出的?**是 anon/authenticated 出的,不是 Railway 的 loop 出的。** 你的修复改了 anon/authenticated 的权限问题,但 Railway 那个 loop 本来就不在那条路径上。

那 Railway 为什么还在 fail?**没人知道,因为诊断数据被写死字符串吞了**。可能:
- ❶ PostgREST schema cache 看到旧函数签名(404)
- ❷ 函数体改了但 PostgREST 还缓存旧 grant(403)
- ❸ 函数返回 200 但 body 是空/非 JSON(被 `return True` 吞掉)
- ❹ breaker 已开但 next tick 仍在 cooldown(返回 None,error 写"熔断")
- ❺ 上游 `coingecko_pro_ohlc` 写入 RPC 自己挂(没改任何 security 也不通)

**5 个独立可能,任何一个都对应一个不同的修法。S-323e 改了第 0 个(权限)。**

### 现场 5 — `_forward_record_loop` 还在 failure 而非 refused

`/internal/data-freshness` 返回的 `loops.failing` 里仍含 `_forward_record_loop`(n=14)。但 S-323j 你说"depth-divergence 是正确拒绝,不是故障"。

矛盾:**loop 自检也不知道自己在正确拒绝**。`problems=['resolve: no response from...']` 这个 message 暗示 `refresh_depth_divergence` 链路断了(可能 `p_date` 写入路径返回 -1 被 Python 当成错误)。

更深层:S-323f 改基线 + S-323g 改 -3 都在 PROJECT_STATE line 3 说"已修",但线上的 `_forward_record_loop` 14 轮失败 + 这个 error 字符串说明**至少其中一个没生效,或三个改动之间有冲突**。同样,没有真实响应数据 = 看不出来。

---

## 四、整个通路为什么"修不好"

### 现场 6 — Learn 段 6 条独立断点

```
                  ┌─────────────────────────────────┐
                  │  Learn 段(整个通路,目前断路)    │
                  │                                  │
                  │  ② signal_outcomes  死 125 天   │
                  │     ↓ (前置)                      │
                  │  source 列 migration 未 ship     │  ← 你承诺本周
                  │     ↓                            │
                  │  ohlcv_daily       6/9 源 dead    │  ← M-118 + ban + HL 退役
                  │     ↓                            │
                  │  refresh_signal_track_record     │  ← 跑空因上
                  │     ↓                            │
                  │  depth_divergence   23% 维护源    │  ← 正确拒绝但 Jazz 待拍
                  │     ↓                            │
                  │  forward_record_keeper            │  ← S-323g -3 路径
                  │     ↓                            │
                  │  outcome_tracker     0 行,无消费  │  ← 假绿灯
                  └─────────────────────────────────┘
```

6 条独立断点,每条要不同修法。**S-323e 试图一次修根因,但根因就是"没有真实诊断" —— 修了 guess #1,guess #2/3/4/5/6 还在那里。**

---

## 五、Phase A — 让诊断数据流出来(0.5 小时,~40 行)

**不动任何业务逻辑,只把真实响应暴露给 `_beat`。** 这一步让接下来所有 fix 都不再是猜。

### A1 — `src/api/store.py:600-620 supabase_rpc` 改两值返回

现在:`return None` 把"4xx / 200+空 body / timeout / breaker open" 全折成一个。

```python
async def supabase_rpc(fn_name: str, payload: dict | None = None):
    """Call a Postgres function via PostgREST RPC. 三值返回 (S-323m):
        - list/dict: 200 + JSON body
        - None:      没读到(RPC 不通/熔断/超时/200+空 body)
        - raise:     4xx 真实诊断(把 status_code + body 抛给 caller)
    """
    if not _SB_URL or not _SB_KEY:
        return None
    url = f"{_SB_URL}/rest/v1/rpc/{fn_name}"
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}",
               "Content-Type": "application/json"}
    try:
        resp = await _supabase_request_with_retry("POST", url, json=(payload or {}), headers=headers)
        if resp and resp.status_code in (200, 204):
            try:
                return resp.json()
            except Exception:
                # 200 but not JSON — 真实 bug,不再 swallow
                raise RuntimeError(f"rpc {fn_name}: HTTP 200 but body not JSON: {(resp.text or '')[:200]}")
        if resp:
            # 4xx — 真实诊断,抛出而不是 None
            raise RuntimeError(f"rpc {fn_name}: HTTP {resp.status_code}: {(resp.text or '')[:200]}")
        return None  # 网络层失败(None 是 caller 已知处理过的 fallback 路径)
    except RuntimeError:
        raise
    except Exception as e:
        _logger.warning(f"[SUPABASE] rpc {fn_name} exception: {e}")
        return None
```

### A2 — `src/api/store.py:240-244` 4xx 不再记 breaker success

```python
if 400 <= resp.status_code < 500 and resp.status_code != 429:
    # 4xx 是 caller bug(我们打错),不是 backend outage ——
    # 不开闸也不假装 SUCCESS。新状态 `caller_error`,
    # 健康检查可以单独统计它(意味着「系统有事但不是饱和」)。
    _cb_record_caller_error()
    _logger.warning(f"[SUPABASE] Non-retryable 4xx {resp.status_code}: {resp.text[:200]}")
    return resp
```

加 `_cb_record_caller_error`(和 `_cb_record_success` 同形但记到 `lifetime_4xx` 计数器)。`supabase_breaker_state()` 暴露 `lifetime_4xx` 字段。

### A3 — `src/api/main.py` 所有 `_beat(ok=False, error=...)` 改为传递真实异常

最小改法:每个调用点 try/except 把异常塞进 error:

```python
# _cg_panel_loop 的 _panel = await deep_panel_symbols() 那块
try:
    _panel = await deep_panel_symbols()
except Exception as _e:
    await _beat("_cg_panel_loop", ok=False,
                error=f"{type(_e).__name__}: {str(_e)[:300]}")
    await _asyncio.sleep(_RETRY_AFTER_FAILURE_S)
    continue
if _panel is None:
    await _beat("_cg_panel_loop", ok=False,
                error="deep_panel_symbols() returned None — 网络层失败 (RPC 不通/熔断/超时/200+空 body)")
    await _asyncio.sleep(_RETRY_AFTER_FAILURE_S)
    continue
```

同样的形状应用到 `_deep_panel_loop:467-470`、`_forward_record_loop` 的 `run_once`、`_outcome_tracker_loop:940-944`、`_factor_tilt_loop` 等所有 `_beat(ok=False, error=...)` 站点(grep 一下,大概 11 个)。

### A4 — `loop_beat.py` 加 `last_failure_at` 字段

你在 S-323l 已经承认:"心跳只有 `n_consecutive_failures` 没有 `last_failure_at`,「9 小时前失败过正在等」和「刚刚失败」同形 —— 而我正是拿这条记录判断修复有没有生效"。这一条**还没修**,任何"看心跳判断修复有没有生效"的动作都不准。

`_beat(ok=False, ...)` 时同时写 `last_failure_at = utcnow()`,`/internal/data-freshness` 的 `loops.rows[*]` 加这个字段。

### A5 — heartbeat 加 `last_resp_status_code` / `last_resp_body[:200]`

`/internal/data-freshness.loops.rows[*]` 加两字段,在每个 `_beat(ok=False, error=...)` 站点附带。**这是 Phase A 的最大产出** —— 真实 HTTP 状态码 + 响应体第一次出现在心跳里。

### A6 — 重启 Railway,跑一轮

```
# 1. preflight
bash scripts/preflight.sh

# 2. commit + push (按 CLAUDE.md 规范)
cd ~/Projects/looloomi-ai
git add src/api/store.py src/api/main.py src/api/loop_beat.py
git commit -m "..."
git push origin main

# 3. 等 Railway 重部署 ~90s,跑验证
curl -s https://web-production-0cdf76.up.railway.app/internal/data-freshness \
  | python3 -c "
import sys,json
d=json.load(sys.stdin)['loops']
for r in d['rows']:
  if r.get('verdict')=='failing':
    print(r['loop'], r.get('last_failure_at'), r.get('last_resp_status_code'),
          (r.get('last_resp_body') or '')[:120])
"
```

**期望**:`_cg_panel_loop` / `_deep_panel_loop` / `_forward_record_loop` 第一次告诉我们**真正**的 HTTP 状态码和响应体。S-323e 修对了修错了,一看便知。

---

## 六、Phase B — 等诊断数据出来再决定

Phase A 跑完一轮之后,你会看到类似:
- `HTTP 404: function public.deep_panel_symbol_list() does not exist` → schema cache 没刷新,重发 `NOTIFY pgrst, 'reload schema'`
- `HTTP 403: permission denied for function ...` → SECURITY DEFINER 没真正生效,重跑 s323e migration 或检查 owner
- `HTTP 200 but body not JSON: <!doctype html>...` → 反向代理/网关拦截,PostgREST 路径配错
- `HTTP 200 / [list]` 但 loop 仍 fail → 是上游 `run_once()` 里的逻辑错(与 RPC 无关),问题在 `cg_panel_sync.py` / `deep_panel_collector.py`
- `_forward_record_loop` 的 problems=['resolve: no response from...'] → `refresh_depth_divergence` SQL 函数本身的问题,S-323f/g 改动没生效或冲突,需要看 PG log

**每条对应不同的修法。** Phase B 的工作量取决于 Phase A 暴露出来的是什么;可能是 30 分钟(404 schema cache),也可能是 4 小时(整条 forward_record 链路重做)。

---

## 七、不要做的(避免再烧一轮)

| 不要 | 为什么 |
|---|---|
| ❶ 再改一次 SECURITY DEFINER / GRANT / REVOKE | S-323e+323h 已修两轮,anon/authenticated 三角色实测都通;Railway 用 service_role,本来就不在权限路径上 |
| ❷ 改 `source_policy` 加新豁免 | binance_hist 4/123 是政策 ban 在工作(S-323i 已确认),放大它等于恢复违规 |
| ❸ 加 `_RETRY_AFTER_FAILURE_S` 更短 | 0.5h/6h/24h 都不解决真因;Phase A 的诊断数据出来之后再决定频率 |
| ❹ 把 `_beat(ok=False)` 改成 `ok=True` 让心跳安静 | 这是 S-299 假绿灯的反向版本,Learn 段会更长不报警 |
| ❺ 改 `_forward_record_loop` 自报 "refused" | 它现在不是 refused,是 failing。Phase A 之前你看不出来它到底是哪个;改了等于再骗一次仪表 |

---

## 八、谁来做什么

| Lane | 做什么 | 工作量 |
|---|---|---|
| **Seth** | Phase A 全套(A1–A6),commit + push + 等重部署 + 跑验证 curl | ~40 行代码 + 0.5h |
| **Minimax-C (我)** | Phase A 跑出来之后的 5 类响应诊断解读,把 Phase B 拆成具体 ticket | 等 Phase A 数据 |
| **Jazz** | (无,等诊断出来再拍 23% 决策 —— 已在 §IN-FLIGHT row 403) | — |

---

## 九、相关链接

- `MINIMAX_SYNC.md` §SETH-DISPATCH-2026-09-08 line 623-722(S-323 链路原始背景)
- `MINIMAX_SYNC.md` §SETH-CORRECTION-2026-09-08 line 726-787(本次根因更正)
- `MINIMAX_SYNC.md` §IN-FLIGHT row 403(23% 维护源 JAZZ 决策,阻塞中)
- `MINIMAX_SYNC.md` §IN-FLIGHT row 405(dispatch 撤回项提示)
- `PROJECT_STATE.md` line 3(S-296 → S-323l 完整链路)
- `src/api/main.py:865-941`(`_cg_panel_loop` 全文,Phase A3 改这里)
- `src/api/main.py:439-477`(`_deep_panel_loop` 全文)
- `src/api/main.py:374-435`(`_forward_record_loop` 全文)
- `src/api/store.py:212-263`(`_supabase_request_with_retry` Phase A2 改这里)
- `src/api/store.py:600-620`(`supabase_rpc` Phase A1 改这里)
- `src/api/loop_beat.py`(Phase A4 加 last_failure_at)

---

## 十、报告状态

**诊断完成,Phase A patch 已贴在 §五。** 任何 lane 想跑都得先有 Phase A 的诊断数据。

— Minimax-C, 2026-09-09
