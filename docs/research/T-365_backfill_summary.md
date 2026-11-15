# T-365 坟场入库 — 计数摘要(第 1 轮 2026-11 · 第 2 轮 2026-10 · 第 3 轮 2026-09)

> 只放计数与口径说明,不放任何假设原文。台账是私有的,原文只在台账里。
> 批次文件:`cometcloud-local/_reports/absorb_input/experiment_runs_backfill_patch.jsonl`(追加,现 36 行)。

## 1. 处理情况

| 项 | 第 1 轮(2026-11) | 第 2 轮(2026-10) | 第 3 轮(2026-09) | 累计 |
|---|---|---|---|---|
| 本轮批次(行) | 12 | 12 | 12 | 36 |
| 合同 `_normalize_experiment_run` 逐行拒绝数 | 0(**第 3 轮实测全量 36 行**) | 0(同上) | 0 | **0(实测,warnings 10)** |
| 合同批次级 `normalize_research_payload` | 未跑 | 未跑(当时 fatal) | **已实测:按 source_lane 分 4 批,全部 ok=True / rejected=0 / fatal 空** | 4 批全绿 |

第 3 轮补读了前两轮的台账正文(每条 25 行,逐条),并按 Seth 11-13 的尺子 v2 复核了前 24 行。

## 2. 按月 × 结论词(行数,尺子 v2 之后)

| 月 | REFUTED | INCONCLUSIVE | CANDIDATE | REPLICATED | PENDING | 小计 |
|---|---|---|---|---|---|---|
| 2026-11 | 0 | 1 | 0 | 1 | 10 | 12 |
| 2026-10 | 5 | 3 | 0 | 0 | 4 | 12 |
| 2026-09 | 3 | 1 | 0 | 0 | 8 | 12 |
| **合计** | **8** | **5** | **0** | **1** | **22** | **36** |

PENDING 不是「没查」:它们是台账里**没有假设判定**的记录(只读核对 / 体检 / 工程 / 决策 / 审计),
台账本身不写结论词,所以保留 PENDING,把事实写进 notes。

## 3. 尺子 v2 复核(第 3 轮做,Seth 11-13 指示)

改了 4 行,其余 32 行不变:

| run_id | 原结论词 | 现结论词 | 依据 |
|---|---|---|---|
| M-200 | REPLICATED | **PENDING** | 台账状态是「完成 audit,待 Seth 行动」——审计,没有假设判定;REPLICATED 只给「两台引擎/两份独立复算一致」 |
| S-835.2 | INCONCLUSIVE | **PENDING** | 台账里没有本条小节,正文不可核 ⇒ 无判定依据 |
| S-829.2 | INCONCLUSIVE | **PENDING** | 同上 |
| S-832.2 | REFUTED | **PENDING** | 同上(三条都在 2026-11 批次) |

其余 32 行逐条过了一遍,结论词不变。**第 1 轮的 5 个结论词有 4 个是「台账无节/审计」造成的**,
这是这一轮最要紧的计数事实:第 1 轮当时给的两条 INCONCLUSIVE 与唯一的 REFUTED,
正文在台账里核不到。

## 4. 第 3 轮(2026-09)12 条的结论词(只有结论词,没有原文)

| 结论词 | run_id | 数 |
|---|---|---|
| REFUTED | S-273、S-276、S-279 | 3 |
| INCONCLUSIVE | S-274 | 1 |
| REPLICATED | — | 0 |
| CANDIDATE | — | 0 |
| PENDING | S-275、S-277、S-278、S-280、S-281、S-282、S-288、S-289 | 8 |

第 3 轮候选池 = 主文件里 `d = 2026-09-*` 的 106 条,按台账顺序取前 12 条非预注册、非更正的条目;
另有一条(数据源探测类)未收。

## 5. 口径与这一轮的发现(留给 Seth)

1. **结论词映射**(逐条定的,尺子 v2 未变):
   台账写 ❌ / FAIL / 判据不过 ⇒ REFUTED;写「只报不判 / 样本不够 / 作废待重跑」⇒ INCONCLUSIVE;
   过预注册判据但未进真钱 ⇒ CANDIDATE;两台引擎或两份独立复算一致 ⇒ REPLICATED;
   台账没有假设判定(只读核对 / 体检 / 工程 / 决策 / 审计)⇒ 保留 PENDING + notes 写事实。
2. **年化 ≠ 区间总收益**:台账写「年化 +x%」的一律**不**填 `total_return_pct`;
   「最差 N 个交易日 −x%」也不填 `max_dd_pct`。只有 S-608 填了 `max_dd_pct = −33.6%`(日序列区间最大回撤)。
3. **合同校验本轮全量实测(前两轮没跑成,原因是行里缺 `hypothesis`)**:
   合同 `_normalize_experiment_run` 对缺 hypothesis 的行直接判 rejected —— 补齐后
   **逐行 rejected = 0**(36 行,warnings 10 条,全是「无 n_obs」这类提示,不是拒绝)。
   批次级 `normalize_research_payload` 按 source_lane 分 4 批跑:
   `seth 24 / minimax-c 6 / minimax-b 5 / minimax-a 1`,**全部 ok=True、rejected=0、fatal 空**。
   ⇒ 上一轮那个「lane-b / lane-c 两批 fatal」已经靠 source_lane 改名(miminax-b / minimax-c)解掉。
4. **`source_lane` 的口径(第 3 轮改数据、不改合同)**:patch 行里写的是 `minimax-a / minimax-b /
   minimax-c / seth`,与合同 `KNOWN_LANES` 一致;主文件里的旧取值 `lane-a / lane-b / lane-c`
   由 `scripts/research/ledger_to_experiment_runs.py` 的 `lane_of` 改口径后重跑生成(不在本卡范围)。
5. **一条结构性事实(只是计数)**:36 条里 22 条 PENDING —— 坟场里「记录」比「判定」多,
   这是口径决定的(没有假设判定的条目只能 PENDING),不是没查。
6. **主文件 218 行 vs 已补的 36 行**:9 月以来 73 行没有 dsr / ledger_ref / source_lane 的那一格,
   要等主文件按新口径重跑 + 导入后才算填上。

## 6. 下一轮

**批次号 T-365-r4-2026-08**,目标:2026-08 的候选池(主文件里 `d = 2026-08-*`)里前 12 条
非预注册、非更正的条目。同样的流程:读正文 → 判结论词 → 只填台账写明的数 → 追加 patch →
全量跑两个合同校验并把两个拒绝数写进摘要。
