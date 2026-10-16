# T-111 — World50 本地上市股数(第二批)

**Branch:** lane-a/T-111 · **Lane:** lane-a · **Date:** 2026-10-16 · **Status:** in_review

本卡交付 9 家 + Siemens 的 2024 / FY2024 锚点行(共 10 行),逐年回填待接力。

**最终路径:**
- CSV: `/Volumes/CometCloudAI/cometcloud-local/research/t111/exchange_shares.csv`
- 报告: `/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-111_local_shares_2.md`

**测得的锚点数字** (粗算 mcap 与公开 mcap 对照 ±5% 以内):
- 3968.HK 招商银行: 25,219,845,601 (A=20,628,944,429 + H=4,590,901,172)
- 601628.SHG 中国人寿: 28,264,705,000
- 601088.SHG 中国神华: 19,889,004,000 (A=16,491,037,955 + H=3,397,966,025)
- 0883.HK 中海油 CNOOC Limited: 47,572,000,000 (HK 单地,卡里写 2022 A 股与事实不符 → @seth 核)
- 2308.TW 台达电: 2,603,374,000 issued / 2,576,148,000 outstanding
- 601138.SHG 工业富联: ~19,844,000,000 (A 单地,2018 上市)
- INVE-B.ST Investor AB: 2,980,290,860 (A=1,243,157,154 + B=1,737,133,706)
- IBE.MC Iberdrola: ~6,317,000,000 (待 CNMV 精确核)
- SIE.XETRA Siemens FY2024: 388,971,090 (T-110 已交,锚点引用)
- PRX.AS Prosus FY2024: 0 (sandbox 取不到 PDF,接力)

**本轮 sandbox 限制:** WebFetch / curl 均需用户授权,只 WebSearch 可用;逐年回填(每家约 10 年,合计 ~108 行)需直读 PDF → **Seth 接力**或下一轮 lane 接力。

下一步:卡推 lane-a/T-111;Seth merge 后写 main 仓库的 tasks/T-111.json 与 BOARD.md。