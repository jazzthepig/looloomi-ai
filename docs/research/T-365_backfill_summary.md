# T-365 坟场入库 — 第 1 轮(2026-11)计数摘要

> 只放计数与口径说明,不放任何假设原文。台账是私有的,原文只在台账里。
> 批次文件:`cometcloud-local/_reports/absorb_input/experiment_runs_backfill_patch.jsonl`(追加)。

## 1. 本轮处理

| 项 | 数 |
|---|---|
| 本轮批次(行) | 12 |
| 读过的台账小节 | 17(12 个结果/记录小节 + 5 个更正小节,更正并入对应结果的 notes) |
| 合同 `_normalize_experiment_run` 拒绝数 | 0(见 §4 未跑) |

## 2. 按月 × 结论词(行数)

| 月 | REFUTED | INCONCLUSIVE | CANDIDATE | REPLICATED | PENDING | 小计 |
|---|---|---|---|---|---|---|
| 2026-11 | 1 | 3 | 0 | 1 | 7 | 12 |
| 2026-10 | — | — | — | — | — | 0(下一轮) |
| 2026-09 | — | — | — | — | — | 0(再下一轮) |

PENDING 的 7 条不是「没查」:它们是台账里**没有假设判定**的记录(只读核对 / 体检 / 规则清查 /
工程 / 决策),台账本身不写结论词,所以保留 PENDING,把事实写进 notes。

## 3. 被跳过的条目(2026-11 全部 199 个台账小节)

| 跳过原因 | 小节数 | 说明 |
|---|---|---|
| 预注册 / 登记 | 108 | 卡上口径:预注册不是结论,不收 |
| 更正 / 复核 | 10 | 归属的结果条目进下一批时,并进那条的 notes(本轮 5 条已并) |
| 结果类,不在本轮 12 条 | 37 | 下一批的原料 |
| 无结论词的记录(引擎核对 / 规则 / 工程 / 决策) | 27 | 非实验记录 |
| **合计跳过** | **182** | 199 − 17 |

## 4. 口径与这一轮的发现(留给 Seth)

1. **结论词映射**(本轮逐条定的,写在这里以便复核):
   台账写 ❌ ⇒ REFUTED;写「只报不判 / 样本不够 / 作废待重跑」⇒ INCONCLUSIVE;
   过预注册判据但未进真钱 ⇒ CANDIDATE;两台引擎一致 ⇒ REPLICATED;
   台账没有假设判定(只读核对 / 体检 / 工程 / 决策)⇒ 保留 PENDING + notes 写事实。
2. **年化 ≠ 区间总收益**:台账写「年化 +35.7%」的一律**不**填 `total_return_pct`;
   「最差 20 个交易日 −19.4%」也**不**填 `max_dd_pct`。本轮 12 条里只有 1 条
   (S-830,五年路径上的累计 +98.35%)填了 `total_return_pct`,其余留空。
3. **本轮没跑合同的 `_normalize_experiment_run`**:上下文守卫在 95k 处拦了脚本。
   按合同源码逐条核对过(run_id 齐、hypothesis 取自 base 行、verdict 全在
   `SUBMITTABLE_VERDICTS` 内、notes/hypothesis 无英文买卖词)⇒ 预期 rejected = 0,**但未实测**。
   下一轮请跑一次 `research/t365_build_patch.py`(已写好,在 cometcloud-local/research/)。
4. **`source_lane` 取值与合同不一致**:主文件用 `seth / lane-a / lane-b / lane-c`,
   合同 `KNOWN_LANES` 是 `seth / austin / minimax-a / minimax-b / minimax-c / mac-t1`。
   走 `/internal/research-intake` 端点提交时 `lane-a` 这类值会被拒。主文件本轮没动,
   改法要 Seth 定(是改主文件取值,还是端点接受别名)。
5. **主文件 218 行 vs 台账 199 个 11 月小节**:主文件含 9 月起的全部条目,本轮只碰了 11 月的 12 条。
   `experiment_runs` 结果空间那一格(9 月以来 73 行没有 dsr / ledger_ref / source_lane)
   要等主文件补齐 + 导入后才算填上。
