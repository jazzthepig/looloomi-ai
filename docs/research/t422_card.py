"""T-422:把卡的 status 改 in_review + notes 写测得值。卡在主仓库(只读)⇒ 拷进 worktree 再改。"""
import json
import pathlib
import shutil

SRC = pathlib.Path("/Users/sbb/Projects/looloomi-ai/tasks/T-422.json")
DST = pathlib.Path("/Users/sbb/Projects/looloomi-ai-lane-b/tasks/T-422.json")

NOTES = """

---

## lane-b 交付(2026-11-21,分支 `lane-b/T-422`,默认关)

**① 口径差表(2026-11-19 三路对跑;23 个加密名参与统计 —— 25 个里 HYPE、SKY 兜底取不到收盘价)**

| 量 | max | mean | median | min |
|---|---|---|---|---|
| Δscore(total,A_rep−B_rep) | **6.90** | **4.73** | **4.70** | 2.90 |
| Δraw(cis_score) | **9.20** | **6.19** | **6.10** | 3.90 |

- **差在哪个支柱**:F −0.009(≈0)/ **M +23.87(max 36.6)**/ O −0.022 / S +1.87 / A +0.017。
- **归因**(第三路 C_rep = 兜底价+市值 **+ CG 成交**):Δraw −0.03、Δscore −0.039、Δpillar_M +0.017
  ⇒ **四维口径差 100% 来自成交量**;价/市值/chg30 一分不差。
- **口径量级**:收盘价(Binance vs CG)差 **0.010–0.116%**;市值(流通量×价 vs CG mcap)差 **0.010–0.204%**
  ⇒ **同一个式子,不是近似**;成交额 CG/兜底 = **6.5×–34.1×**(逐币不同 ⇒ **无常数可校准**)。
- **兜底 vs 已发布官方档**(B_rep − A_pub):Δscore max +2.5 / mean −0.87 / median −0.8 / min −4.4;
  **等级变 6/23**(PENDLE C→D、STRK C→D、ONDO C→D、ARB C+→C、UNI C+→C);**档位变 5/23**;
  **regime 变 0/23**(三路都是 RISK_OFF)。
- **max_supply 缺失单独一行**:方向确定、量级 **≤5 分 F**(capped-emission bonus);两路 static 相同 ⇒
  分数差里量不出来,故单列(不混进上面的 Δscore)。
- TradFi 对照(33 名)Δscore 全为 0 ⇒ 兜底确实不碰传统资产。

**③ 「缺了会怎样」逐日实测(11-13…11-30,`t422_gap.py`)**:CG 市值行 422/423/421/408/410/408/405 → **11-20 起 0 行**;
Binance 11-20 仍 **135 符号 / 覆盖 23 个加密名**;`coin_supply_daily` 最后一批 **11-20 300 行**(`fetched_at=11-20 06:00Z`)。
- **硬闸只有一条**:加密名「有价」比例(`MIN_CRYPTO_PRICED=0.90`)—— 兜底的 Binance 价能过闸。
- **软缺但必须补**:`total_supply`(缺 ⇒ fdv=0、supply_ratio=0 ⇒ F 支柱 **30 分整体塌**,不是偏一点)。
- **软缺且补不了**:`max_supply`(≤5 分 F)、`macro.total_mcap`(⇒ bdom ⇒ regime 少一个输入)⇒ 如实标缺,不许补 0。
- ⚠️ **11-21 那行是 0,但不能读成「采集器也死了」**:扫描时刻 11-21 **05:37 UTC**,日批采集 ~06:00 UTC 才落 ⇒
  「还没到采集点」与「订阅停了」性质不同,**要 11-21 06:00 UTC 之后再扫一次才能分开**(已在报告里标注)。

**② 兜底实现**:`src/data/cis/cg_less_fallback.py`(新文件)+ `rebuild.py` / `official.py` 的**默认关**钩子。
开关 `CIS_CG_LESS_FALLBACK=1` 才启用;**只在 CG 取不到的那一维接管,不是替换**;接管与否写进日志与报告字段。
不改评分公式 / 闸门 / 公开面 / `MIN_CRYPTO_PRICED` / `PUBLISH_DEADLINE_HOUR`。

**④ 测试**(`tests/test_cis_cg_less_fallback.py`,`pytest` ⇒ **12 passed, 1 skipped**,50s):
- 开关关 ⇒ `data` 一个字节不动、返回不多一个键、**真实 11-19 库内数据**上 `score_day` 输出逐字节相同(本轮补跑,不是夹具);
- 同一份真实数据、开关开 + CG 模拟取不到 ⇒ 兜底真的接管,价/市值/成交/总量都有值,且输出**必须变**(否则是装饰品);
- **三条变异测试红**:兜底价改 0 / 流通量改 0(F 支柱掉)/ `total_supply` 改 0(F 支柱掉);
- ⚠️ **1 条跳过**:`load_inputs` 全量输出 vs 落盘快照 —— 本机 4 张表(`protocol_tlv_daily` / `chain_activity_daily` /
  `github_commits_weekly` / `equity_fundamentals_q`)对 publishable key **401** ⇒ `load_inputs` 抛错跑不起来。
  **这一条要 @seth 在有 service 权限的机器上补跑。**

**⑤ 报告**:`docs/research/t422_cg_less_fallback.md`(含差表、逐日缺口表、测试表、§5「能不能接受」的三条可选路)。
数字表:`/Volumes/CometCloudAI/cometcloud-local/research/t422/`(`ab_table.json` / `ab_rows.json` /
**`gap_1113_1130.json`** / `gap_run.log` / `official_1119.json`)。
前向预期:`docs/research/scenarios/lane-b-T-422.json`(4 条机器可核命题)。

**要 Seth / Jazz 拍的**(本轮不替 Jazz 定):**成交额口径**是唯一的拦路虎 ——
(a) 成交额如实标缺(宁缺勿造,但 M 仍掉,闸门去拒);(b) 给 M 一个明确标注的「Binance 单所口径」(口径变更需点头);
(c) 不接这 10 天的官方档,等 12-01 恢复后用重建档补(洞仍在,但不发错的档)。
另:**开关默认关,合进主干不改变任何一行现有输出** —— 要不要打开由 Seth 在合并/上线时决定。
"""

d = json.loads(SRC.read_text())
d["status"] = "in_review"
d["notes"] = d.get("notes", "") + NOTES
DST.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC, DST)
DST.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
print("status:", d["status"], "| notes chars:", len(d["notes"]))
