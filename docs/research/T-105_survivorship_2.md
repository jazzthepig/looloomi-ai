# T-105 — World50 幸存者偏差补完 ②(报告全文见 Mac 数据根)

**Date:** 2026-10-16
**Author:** Minimax-B (lane-b)
**Card:** `/Users/sbb/Projects/looloomi-ai/tasks/T-105.json`(status = **in_review**)
**Full report:** `/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-105_survivorship_2.md`
**Branch:** `lane-b/T-105`

## 这一张本卡交付了什么

四个 CSV + 一份报告,**全部在 Mac 数据根**:

| 文件 | 行数 | 内容 |
|---|---|---|
| `research/t105/adr_ratios.csv` | 75 | 六个 ADR 每 fiscal year 各一行 + VOD 2022-09 mid-year amendment |
| `research/t105/sec_prefix.csv` | 75 | FY2014-FY2018 封面股数 + UL PLC + NV 双股分列 |
| `research/t105/top100_by_year.csv` | 2025 | 2015-2025 每年前 20 / 2018 完整 100(本轮新增) |
| `research/t105/missing.csv` | 8 | 2018 PwC 真不在池中的 8 家 + 处理状态(本轮新增) |
| `_reports/absorb_input/T-105_survivorship_2.md` | 全报告 | 包含本轮 ③ DowDuPont spec + ④ 年份口径差 |

## 关键事实(详情见报告)

- **BTI FY2014-FY2018 EDGAR 不可得**(CIK 1303523 首份 20-F = FY2019);World50 backfill 在这段不含 BTI,除非单独采购 LSE/RNS;
- **UL pre-2020 是 PLC + NV 双股**(1,310,156,361 + 1,714,727,700 = 3.02B),市值得 ×3.02B;
- **DowDuPont 接不上一条连续时间线**(三个 CIK + 两份 8-K recast + pre-merger 两条独立线);建议方案 A(DOW + CTVA 两条线 2019-04 起,2017-2019 DWDP 段坦承缺);
- **PwC 2019-2025 top-21-to-100 获取路径未知**(PDF paywalled 403,Wayback CDX 零命中);2018 是唯一完整年;
- 2018 PwC quirk:同一项多个位置(BTI #74+#75;NVS / BHP / TTE / BUD 自家重复) — 这是 PwC 自己手抄表的特性。
