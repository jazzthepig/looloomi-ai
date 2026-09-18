# Jev 实测附录 · CometCloud 三个内部场景

**状态**:骨架就绪 · 等待 early-access API key + 实测数据
**主文**:见 [`jev_decision_kernel_2026-09-18.md`](./jev_decision_kernel_2026-09-18.md)
**中文导读**:见 [`jev_decision_kernel_2026-09-18_zh.md`](./jev_decision_kernel_2026-09-18_zh.md)

---

## 1. 为什么做这个实测

TypeSafe 自报的数字(67.8% 平均精度 / 76× cheaper / 25× faster)是发布方选定的 4 个工作流上的统计,与 CometCloud 的内部场景未必对应。Maio 和 pearpages 两份独立分析都没自己跑过 Jev —— 他们的批评是方法学层面的(workflows 是 TypeSafe 自己设计的,reference labels 是 GPT-6 + Claude Fable 5.1 取平均而非 ground truth)。

M-176 不是为了再发一遍自报数字。M-176 的真正目标是 **per-decision calibration 曲线**——这是 §6 第二条批评("population-level ≠ per-decision")唯一能独立验证的部分,在 TypeSafe 公开材料里完全缺失。

## 2. 实验设计(完整版见 `M176_DESIGN.md`)

三个场景,贴近 CometCloud 真实生产数据:

| # | 场景 | 任务 | 原语 | Ground truth | 样本量目标 |
|---|---|---|---|---|---|
| A | 合规预筛 | BUY/SELL 检测 | Noul | 内部 compliance 系统 | 100+ |
| B | ops-console 分诊 | 真 incident vs fossil | Noul | `ops_console.py` 现行分类 | 200 |
| C | trace triage | fill 是否违反 doctrine | Noul | `spec_runner.py` 现行 auditable 输出(**匿名化后**) | 100 |

每个场景报告:**latency_ms 中位 / cost_usd 均值 / accuracy / Brier / reliability diagram (10-bin) / threshold sweep (0.5/0.7/0.85)**。

## 3. 边界声明(M-176 不能用来干什么)

重申一次,避免下游误用:
- ❌ 验证或反驳 67.8% / 17.3pp 自报 headline(场景不同)
- ❌ 推断"per-decision 校准在总体上是否成立"(400 条样本量不够做可靠区间)
- ❌ 替代 independent benchmark
- ✅ 在 CometCloud 这 3 个具体场景上,延迟 / 成本 / 准确率分别如何
- ✅ per-decision 校准曲线在 400 个真实样本上长什么样

## 4. 实测结果(待填)

> 以下章节为模板,等 M-176 跑完结果填入。

### 4.1 场景 A · 合规预筛

(由 `aggregate_report.py --a cache/scene_a_results.jsonl` 填入)

### 4.2 场景 B · ops-console 分诊

(由 `aggregate_report.py --b cache/scene_b_results.jsonl` 填入)

### 4.3 场景 C · trace triage(数据匿名化)

(由 `aggregate_report.py --c cache/scene_c_results.jsonl` 填入)

## 5. Per-decision calibration 专项分析(本附录真正的新贡献)

(待填。包含 10-bin reliability,以及"Brier 随 confidence 阈值漂移"的曲线)

## 6. 阈值耦合分析

(待填。threshold = 0.5 / 0.7 / 0.85 上 FP/FN 率)

## 7. CometCloud 内部决策建议

(待填。三个工作流分别:YES 接 / DEFER / NO 不接,基于实测数据)

## 8. 后续

- M-176e:Jev vs Claude Haiku 4.5 / Sonnet 4.6 / Opus 4.8 直接对照(回应 Maio/pearpages 的"决策图红利"批评)
- M-176f:per-decision calibration 偏差是否随 confidence 阈值系统化偏移(校准漂移结构测试)
- M-176g:把 §6 第二条批评的"per-decision ≠ population-level"写成可复用测试,纳入 preflight

---

*本附录与 Jev 主报告 / 中文导读同步发布。配套脚本在 `/tmp/jev_assets/eval_design/`(`jev_client.py` / `anonymize.py` / `run_scene_{a,b,c}.py` / `aggregate_report.py`)。*
