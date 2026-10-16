# T-110 — World50 扩池 21 家本地上市公司历年总股数

**卡状态:** in_review · **Lane:** lane-c · **Date:** 2026-10-16 (Round 2)
**分支:** lane-c/T-110
**数据(不在 git 里,在 Mac 数据根):**
- `/Volumes/CometCloudAI/cometcloud-local/research/t110/exchange_shares.csv` (17 行 + 表头,全有数,无 shares=0 占位)
- `/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-110_local_shares.md` (约 100 行报告)

**Round 2 修正:**
- ABBN.SW outstanding 180,944,818 → 1,915,000,000 (差 10x 修);新增 ABBN 2022 行 (2,039,423,682)
- CFR.SW FY24 B 股 522M → 537,582,089 (Nov-2023 资本增加);新增 CFR FY23 行
- 删除 5 个 shares=0 占位行 (SU 旧 + 4 个中国/港股)

**覆盖:** 12/21 家已交付有数股数,9 家 (IBE/PRX/INVE-B/3968/601628/601088/0883/2308/601138) 交 T-111 lane A Round 2。
**mcap 验证:** 偏差 ≤ 25%(SIE/AIR 偏差源于股价估的不够新,outstanding 口径对);其余 11 家对得上公开 mcap。
**@seth 复核项:** (a) SIE/AIR 2024 末股价;(b) ABBN par CHF 0.0949 vs AR2022 报 0.12 中间是否 reverse-split;(c) 2014-2021 历史是否下轮补(约 80 个 URD PDF)。