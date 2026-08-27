# Mac-side LM Studio 模型替换 — 2026-08-27 spec

> Owner: Minimax-A (Mac lane). Spec 由 Seth (2026-08-27) 写,Minimax-A 执行。
> MINIMAX_SYNC 指针:`§MAC-SIDE-LM-STUDIO-MODEL-SWAP-2026-08-27` (该节只留指针,详见本文件)

## Context

LM Studio 9.0 上 `qwen3.5-35b-a3b` 已下线。Seth lane 已完成:
- `~/.claude/CLAUDE.md`、`agents/cis-scorer.md`、`skills/cometcloud/*`、`.mcp.json`、`mcp/cometcloud_mcp_server.py`、`settings*.json`
- 全部切到 `qwen/qwen3.8-27b`(deep)+ `qwen/qwen3.5-9b`(batch)

**Mac-side `/Volumes/CometCloudAI/cometcloud-local/` 是 Minimax-A lane,唯一未完成。**

## ⚠ MLX caveat

Jazz 在单独装 MLX 后端的 qwen3.8 build。当前 LM Studio 上的 27b 是非 MLX(慢且效果差,Seth 实测 ~219s/prompt)。**先确认 MLX 落地,再动 spec**——直接切非 MLX 会把 deep-analysis 拖到 4-5x。

## Spec to apply

### Model name

| 旧 | 新 |
|---|---|
| `"qwen3.5-35b-a3b"` | `"qwen/qwen3.8-27b"` |
| `"qwen3.5-9b"` | `"qwen/qwen3.5-9b"`(加 `qwen/` 前缀,与 LM Studio 实际 id 对齐) |

### max_tokens (按任务)

| 任务 | 旧 | 新 |
|---|---|---|
| CIS deep analysis / RWA / macro | 8000 | **6000** |
| GP evaluation report | 10000 | **8000** |
| 批处理 (qwen3.5-9b) | 3000 | **3000**(不变) |

### Disable thinking(关键)

把每个 deep-model callsite 的:

```python
"extra_body": {"no_think": True},   # ← 旧,在 qwen3.8 上 NO-OP
```

改成 Qwen3 官方:

```python
"chat_template_kwargs": {"enable_thinking": False},   # ← 实测 -57% tokens / -69% reasoning
```

Callsite 写法参考已 ship 的 `~/.claude/skills/cometcloud/{cis-analyst,gp-evaluator,macro-signal,market-reporter}.md`。

## Execution

### 1. 验 MLX 后端

```bash
curl -s http://127.0.0.1:1234/v1/models | jq '.data[] | {id, type: .object}'
```

判定:
- ✅ 已有 MLX qwen3.8 id(Jazz 装完会重命名) → 继续步骤 2
- 🟡 仍是非 MLX → 停,告诉 Jazz 装完再来,**不要硬切**

### 2. 扫 Mac-side 调用点

```bash
cd /Volumes/CometCloudAI/cometcloud-local/
grep -rln 'qwen3\.5-35b-a3b\|qwen3\.5-35b[^a-z-]\|"qwen3\.5-9b"' \
  --include='*.py' --include='*.sh' --include='*.json' --include='*.yaml' \
  --exclude-dir=__pycache__ --exclude-dir=_cache
```

期望列出:`cis_v4_engine.py` / `data_fetcher.py` / `cis_scheduler.py` / `macro_brief_push.py` 之类。

### 3. 逐 callsite 应用 spec

按上面的 Model name / max_tokens / enable_thinking 表格改。

### 4. Verify

跑最小 CIS prompt:

```bash
curl -s http://127.0.0.1:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"qwen/qwen3.8-27b","max_tokens":6000,"temperature":0.1,
    "chat_template_kwargs":{"enable_thinking":false},
    "messages":[
      {"role":"system","content":"你是 DeFi 量化分析师。直接输出 JSON。"},
      {"role":"user","content":"分析 UNI 的 CIS 评分,5 支柱 JSON。"}
    ]
  }' | jq '.usage.completion_tokens, (.choices[0].message.content | length), (.choices[0].message.reasoning_content // "" | length)'
```

**期望:**
- `completion_tokens` < 2500(实测 1707)
- `reasoning_content` 接近 0
- wall-clock:MLX 应 < 60s,非 MLX 会到 ~219s(→ 失败)

## 三条硬要求(每条都付过学费)

1. **先验 MLX 再动 spec**——非 MLX 的 27b 慢 4-5x
2. **`enable_thinking=False` 不漏**——Seth smoke test 实证 `extra_body.no_think=True` 在 qwen3.8 上完全无效,reasoning 占 1.6x output
3. **max_tokens=6000 不回 8000**——27B 实测 3349 tokens,6000 是 +80% buffer

## 完成后的回报

把以下行 reply 到 MINIMAX_SYNC §IN-FLIGHT 同条目,我会标 ✅ 并移到 ARCHIVE:

```
VERIFY ✅ 2026-08-2X
- /api/v1/models 含 MLX qwen3.8 id: <id>
- Mac-side `grep -c qwen3.5-35b-a3b` = 0
- 完成时间 + 改了哪些文件
```