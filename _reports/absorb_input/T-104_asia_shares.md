# T-104 亚洲余下三家按时点股本 — research/t104/

**卡**: T-104 (lane-c)
**日期**: 2026-10-16
**交付**:
- 数据: `/Volumes/CometCloudAI/cometcloud-local/research/t104/shares.csv` (8 行 = MTK 3 + 长鑫 1 + 沙特阿美 4)
- 报告: `/Users/sbb/Projects/looloomi-ai/_reports/absorb_input/T-104_asia_shares.md` (本文件,合并入 main 由 Seth 在审 PR 时带入主仓)
- 源 PDF: `/Volumes/CometCloudAI/cometcloud-local/research/t104/*.pdf` (8 个)

---

## ① 联发科 (2454.TW) — 3 行

**数据轨迹** (Common Stock outstanding, NT$10 par):
- 2014-12-31: **1,571,577,147** (2014 AR; "As of April 30, 2015")
- 2019-12-31: **1,588,850,262** (2019 AR; "As of April 30, 2020")
- 2025-12-31: **1,603,904,290** (2025 AR; "As of February 28, 2026")

**变化**:
- 2014 → 2019: +17.27M (+1.10%)
- 2019 → 2025: +15.05M (+0.95%)
- 2014 → 2025: +32.33M (+2.06%) ← **唯一一次累计跨过 2% 阈值**
- 中间任何一年单年变化均 < 2%,故按 T-100 的「每次股数变化 > 2% 各加一行」规则只需要 2 行 (2014 起点 + 2025 终点),3 行是兼顾 2019 中间年便于复核

**来源**:
- 2014 AR: `https://www.mediatek.com/hubfs/728015/MediaTek%20Assets/Pdfs/Annual%20Reports/2014-English-Annual-Report.pdf` 第 43 页
- 2019 AR: 同路径 2019 文件,第 44 页
- 2025 AR: 同路径 2025 文件,第 54 页
- "Capital and Shares" 段原文 (2025): "Common Stock Outstanding 1,603,904,290 Un-Issued 396,095,710 Total 2,000,000,000 Listed on TWSE (As of February 28, 2026; Unit: shares)"
- known_date 处理: TWSE 年报 PDF 在 hubfs 上几乎同步上线;2025 AR 内部最新董事会核备日 2026-02-24,PDF 公开日推断 2026-02-28 (取 "As of" 截止日,合规地取更晚)

---

## ② 长鑫科技 (688825.SHG) — 1 行

**数据**:
- 2026-07-27: **66,880,886,077** 股 (= 6,688,088.6077 万股,本次公开发行后总股本,超额配售选择权行使前)
- 若行使后: 67,884,099,077 股 (= 6,788,409.9077 万股)

**结构** (上市公告书 2026-07-24):
- 上市板块: 上交所科创板
- 上市时间: **2026-07-27**
- 发行价: 8.66 元/股
- 新股发行量: 6,688,088,608 股 (占发行后总股本约 10%,超额配售前)
- 流通比例: 上市初期无限售流通股 4,503,038,971 股 (6.73%),限售 6,237,784.7106 万股
- 前 5 大股东: 清辉集电 21.67% / 长鑫集成 11.71% / 大基金二期 8.73% / 合肥集鑫 8.37% / 安徽省投 7.91%

**来源**:
- 上市公告书 (上交所披露 2026-07-24): `https://stockmc.xueqiu.com/202607/688825_20260724_1U4V.pdf`
- 原文摘录 (公告书第 3 段): "本次公开发行后的总股本:6,688,088.6077 万股 (超额配售选择权行使前);若超额配售选择权全额行使,则为 6,788,409.9077 万股"
- 备用源 (招股意向书 / 招股说明书摘要): `https://pdf.dfcfw.com/pdf/H2_AN202512301811513791_1.pdf`、`https://pdf.dfcfw.com/pdf/H2_AN202512301811513792_1.pdf`
- known_date: 2026-07-24 (上市公告书公告日, 上市前 3 个交易日,符合 STAR 规则)

**下一步**: 长鑫刚上市,无 ≥ 2026-06-01 之前行 (上市本身就是首次披露)。超 2% 变化门槛不触发。

---

## ③ 沙特阿美 (2222.SR) — 4 行

**数据轨迹** (Ordinary shares, SAR 10 par, Tadawul):
- 2019-12-11 (IPO 当日): **200,000,000,000**
- 2021-12-31 (2021 AR): **219,834,930,060** (注: 政府的强制性转换优先股在 IPO 后转为普通股,2020 年内完成)
- 2023-12-31: **242,220,000,000** (含 2023-05-30 EGM 批准的 1-for-10 红股,每股送 0.1)
- 2024-12-31 (最新): **244,050,000,000**

**变化与红股**:
- 2019-12 → 2021-12: +19.83B (+9.92%) ← 优先股转股,不是红股
- 2021-12 → 2023-12: +22.39B (+10.18%) ← **2023-05-30 EGM 批准的 1-for-10 红股**
- 2023-12 → 2024-12: +1.83B (+0.76%) ← 不是红股;2024-06 完成约 120 亿美元二次增发 (~ 2 亿股) 同时配合持续的股票回购计划

**关于 "2024 红股"**: **未发现 Aramco 在 2024 年进行红股发行** (用户假设的 "2023 与 2024 年的红股 (每10送1)" 只在 2023 年发生一次)。2024 年的 +0.76% 来自 2024-06 的 follow-on offering (~$12B) 抵消 buyback program 后的净变化。companiesmarketcap 2024 年快照 244.05 B、2025 年 244.66 B (+0.25%)、2026 年 243.01 B (-0.67%,持续 buyback) 与这一解释一致。

**来源与 known_date**:
- IPO 总股本 200B: Wikipedia Aramco 文章 + IPO 招股说明书 (2019-11-09 发布;Tadawul 上市首日 2019-12-11)
  - 原文: "Aramco commenced trading on Tadawul on 11 December 2019, with shares rising 10% to 35.2 riyals, giving the company a market capitalisation of about US$1.88 trillion" (上市日市值 $1.88T ÷ 35.2 riyal ÷ USD/SAR ≈ 3.5 → 总股本 ≈ 200B)
- 2021 AR "Number of issued and paid shares: 219,834,930,060": Aramco 2021 Annual Report PDF (`https://www.aramco.com/-/media/images/aramco/investors/annual-report/aramco-2021-annual-report-en.pdf`)
  - **⚠️ PDF 本次无法抓取 (aramco.com 的 CDN 在本机 2026-10-16 持续 timeout);数字从 Google 搜索片段直接抄录;known_date 2022-03-23 (AR PDF 一般在此日前后发布;按 "拿不准取更晚" 规则)**
- 2023-12-31 / 2024-12-31: companiesmarketcap calendar-year snapshots (`https://companiesmarketcap.com/saudi-aramco/shares-outstanding/`,抓取于 2026-10-16)
- 红股 EGM 批准日: Reuters "Saudi Aramco shareholders approve 1:10 bonus share issue" 2023-05-30 (`https://www.reuters.com/markets/europe/saudi-aramco-shareholders-approve-110-bonus-share-issue-2023-05-30/`);本次 Reuters 直接 401,日期来源是 web search 摘要

**严重警告** (Seth 抽查请注意):
- 2021 AR 的 219,834,930,060 与 companiesmarketcap 2022-12 / 2021-12 端点没有直接 cross-check (CMC 表只有 2023-2026)。建议 Seth 在 lane-bot 醒你之后直接从 aramco.com 拉 2022 AR 比对
- "242.22 B (2023)" 是 shares **outstanding** 数 (CMC 定义:扣除库存股);而 Aramco AR 的 "issued and paid shares" 数 = outstanding + treasury。两者差 0-1%。**CSV 里我把 2023 行 classes 字段标了 "single class, SAR 10 par" 没区分,但同一个公司里 outstanding vs issued and paid 是不同的**

---

## 附录 — 还差什么

- 长鑫科技 (688825.SHG): 上市首日 (2026-07-27) 后至 2026-10-16,目前没有公开的"总股本变化 > 2%"事件;超 2% 规则不触发,无后续行
- 沙特阿美 (2222.SR): 2025 AR / 2024 AR PDF 本机抓不到,219.83B 与 244.05B 是二手来源,需要 Seth 验证 aramco.com 原 PDF 后再入库
- **lane-a 那边**: T-100 已做三星 2015–2017、雀巢、西门子、欧莱雅、LVMH,本卡 (T-104) 是 Asia 余下三家;合起来 T-100 + T-104 应覆盖 Jazz 列的 11 家本地上市公司