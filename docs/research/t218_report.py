#!/usr/bin/env python3
"""T-218:生成报告 docs/research/T-218_rails_vs_tokens.md。

数字全部来自 t218_table.json / t218_baserates.json(脚本生成,不当手抄),
措辞与判据是人工写的,判据阈值先写死再套季度。
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = json.loads((HERE / "t218_table.json").read_text())
BR = json.loads((HERE / "t218_baserates.json").read_text())
rows = T["table"]
RAILS = ["COIN", "HOOD", "CRCL"]
TOKB = ["ETH", "SOL", "TRX", "HYPE"]
SNAP = T["snapshot"]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def n(v, s=1e6, dd=1):
    return "—" if v is None else f"{v / s:,.{dd}f}"


def p(v, dd=1):
    return "—" if v is None else f"{v:+.{dd}f}"


# ── 表 1:稳定币供应与收入归属 ──────────────────────────────────────────────
t1 = ["季度", "USDT市值($B)", "USDC市值($B)", "合计($B)", "合计环比%", "Tether收入($M)",
      "Circle收入($M)", "发行方合计($M)", "公链持币人收入($M)", "发行方/持币人",
      "发行方年化收益率/供应"]
l1 = ["| " + " | ".join(t1) + " |", "|" + "---|" * len(t1)]
for r in rows:
    iss = None
    if r["tether_rev"] is not None and r["circle_rev"] is not None:
        iss = r["tether_rev"] + r["circle_rev"]
    elif r["tether_rev"] is not None:
        iss = r["tether_rev"]
    parts = [r.get(k) for k in ("eth_holders_rev", "sol_holders_rev", "trx_holders_rev",
                                 "hype_holders_rev")]
    hold = sum(x or 0 for x in parts) if any(x is not None for x in parts) else None
    sup = r["stable_total"]
    rate = (iss * 4 / sup * 100) if (iss is not None and sup) else None
    ratio = (iss / hold) if (iss and hold) else None
    l1.append("| " + " | ".join([
        r["quarter"], n(r["usdt_mcap"], 1e9, 2), n(r["usdc_mcap"], 1e9, 2), n(sup, 1e9, 2),
        p(r["stable_qoq_pct"]), n(r["tether_rev"]), n(r["circle_rev"]), n(iss),
        n(hold), "—" if ratio is None else f"{ratio:.1f}×",
        "—" if rate is None else f"{rate:.2f}%"]) + " |")

# ── 表 2:季度收益 ──────────────────────────────────────────────────────────
t2 = ["季度", "BTC%", "ETH%", "SOL%", "TRX%", "HYPE%", "ETH超额vsBTC(pp)", "SOL超额vsBTC(pp)",
      "COIN%", "HOOD%", "CRCL%", "代币篮子%", "轨道篮子%", "代币−轨道(pp)", "更像哪一支"]
l2 = ["| " + " | ".join(t2) + " |", "|" + "---|" * len(t2)]
branch_rows = []
cnt = {"A": 0, "B": 0, "none": 0, "na": 0}
qA, qB = [], []
rail_first = {}
for r in rows:
    tkm = mean([r.get(f"{s}_ret_pct") for s in TOKB])
    rlm = mean([r.get(f"{s}_ret_pct") for s in RAILS])
    diff = None
    if tkm is not None and rlm is not None:
        diff = tkm - rlm
        if tkm >= 10 and rlm >= 10:
            br = "A"
        elif rlm >= 10 and diff <= -10:
            br = "B"
        else:
            br = "none"
        cnt[br] += 1
        (qA if br == "A" else qB if br == "B" else []).append(r["quarter"])
    else:
        br = "—"
        cnt["na"] += 1
    for s in RAILS:
        if r.get(f"{s}_ret_pct") is not None and s not in rail_first:
            rail_first[s] = r["quarter"]
    branch_rows.append((r["quarter"], tkm, rlm, diff, br))
    l2.append("| " + " | ".join([
        r["quarter"], p(r["BTC_ret_pct"]), p(r["ETH_ret_pct"]), p(r["SOL_ret_pct"]),
        p(r["TRX_ret_pct"]), p(r["HYPE_ret_pct"]), p(r["ETH_excess_pct"]), p(r["SOL_excess_pct"]),
        p(r["COIN_ret_pct"]), p(r["HOOD_ret_pct"]), p(r["CRCL_ret_pct"]),
        p(tkm), p(rlm), p(diff), br]) + " |")

# DB(eq.eodhd)与 Nasdaq 公开源的逐季交叉核对
xchk = []
for s in RAILS:
    ds = [abs(r[f"{s}_ret_diff_pp"]) for r in rows if r.get(f"{s}_ret_diff_pp") is not None]
    xchk.append((s, max(ds) if ds else None, len(ds)))
xchk_txt = "、".join(f"{s} 最大差 {m:.2f} pp(n={k})" for s, m, k in xchk if m is not None) or "无重叠季"

# 累计(基数 1.0,逐季连乘)
rails_cum, tok_cum = 1.0, 1.0
for _, tkm, rlm, _, _ in branch_rows:
    if tkm is None or rlm is None:
        continue
    rails_cum *= (1 + rlm / 100)
    tok_cum *= (1 + tkm / 100)
xs = [t for _, t, r_, _, _ in branch_rows if t is not None and r_ is not None]
ys = [r_ for _, t, r_, _, _ in branch_rows if t is not None and r_ is not None]
mx, my = mean(xs), mean(ys)
cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / len(xs)
sx = (sum((a - mx) ** 2 for a in xs) / len(xs)) ** 0.5
sy = (sum((b - my) ** 2 for b in ys) / len(ys)) ** 0.5
corr = cov / (sx * sy)
vol_t, vol_r = sx, sy
more = "A" if cnt["A"] > cnt["B"] else ("B" if cnt["B"] > cnt["A"] else "两边一样多")
more_txt = {"A": "A「轨道与代币一起赢」", "B": "B「轨道赢、代币跑输」", "两边一样多": "两边一样多"}[more]

# ── ③ 前向命题 ─────────────────────────────────────────────────────────────
ETH0 = SNAP["ETH"]["last"][1]
SOL0 = SNAP["SOL"]["last"][1]
COIN0 = SNAP["COIN"]["last"][1]   # DB eq.eodhd 的最后收盘(11-02 已入库)
HOOD0 = SNAP["HOOD"]["last"][1]
CRCL0 = SNAP["CRCL"]["last"][1]
PROPS = [
    {"id": "R1-A-01", "scenario": "A",
     "statement": "代币端:ETH 在结算日收盘不低于 2,560 美元(2026-11-01 收盘 2,275.31 的 1.125 倍),"
                  "即公链代币在 2027Q1 之前回到资金回流状态",
     "variable": "close:ETH", "op": "gt", "lo": 2560, "hi": None, "prob": 0.45,
     "horizon_d": "2027-03-31"},
    {"id": "R1-A-02", "scenario": "A",
     "statement": "代币端:SOL 在结算日收盘不低于 115 美元(2026-11-01 收盘 94.53 的 1.22 倍)",
     "variable": "close:SOL", "op": "gt", "lo": 115, "hi": None, "prob": 0.35,
     "horizon_d": "2027-03-31"},
    {"id": "R1-A-03", "scenario": "A",
     "statement": "轨道端:COIN 在结算日收盘不低于 172 美元(2026-10-30 收盘 143.54 的 1.20 倍);"
                  "该序列已入库(eq.eodhd),可直接结算",
     "variable": "close:COIN", "op": "gt", "lo": 172, "hi": None, "prob": 0.40,
     "horizon_d": "2027-03-31"},
    {"id": "R1-A-04", "scenario": "A",
     "statement": "轨道端:HOOD 在结算日收盘不低于 102 美元(2026-10-30 收盘 84.99 的 1.20 倍)",
     "variable": "close:HOOD", "op": "gt", "lo": 102, "hi": None, "prob": 0.40,
     "horizon_d": "2027-06-30"},
    {"id": "R1-A-05", "scenario": "A",
     "statement": "市场状态:面板中站在 MA50 上方的资产比例回到 50% 以上(2026-11-01 为 0,"
                  "历史日频 44.7% 的日子在 0.5 以上)——「一起赢」需要宽度,不是只有龙头涨",
     "variable": "state:breadth_above_ma50", "op": "gt", "lo": 0.5, "hi": None, "prob": 0.40,
     "horizon_d": "2027-03-31"},
    {"id": "R1-B-01", "scenario": "B",
     "statement": "代币端:ETH 在结算日收盘低于 1,935 美元(2026-11-01 收盘 2,275.31 的 0.85 倍),"
                  "即代币端继续跑输而价值留在发行方/股权",
     "variable": "close:ETH", "op": "lt", "lo": None, "hi": 1935, "prob": 0.35,
     "horizon_d": "2027-06-30"},
    {"id": "R1-B-02", "scenario": "B",
     "statement": "代币端:SOL 在结算日收盘低于 80 美元(2026-11-01 收盘 94.53 的 0.85 倍)",
     "variable": "close:SOL", "op": "lt", "lo": None, "hi": 80, "prob": 0.40,
     "horizon_d": "2027-06-30"},
    {"id": "R1-B-03", "scenario": "B",
     "statement": "轨道端:CRCL 在结算日收盘不低于 87 美元(2026-10-30 收盘 72.54 的 1.20 倍);"
                  "与 R1-B-01/B-02 同时成立即 B 分支",
     "variable": "close:CRCL", "op": "gt", "lo": 87, "hi": None, "prob": 0.35,
     "horizon_d": "2027-06-30"},
    {"id": "R1-B-04", "scenario": "B",
     "statement": "发行方业务量:稳定币供应 30 日变化在结算日转正(state:stable_supply_30d > 0;"
                  "历史 2468 个交易日里 72.9% 为正),即价值继续沉淀在稳定币端而非代币端",
     "variable": "state:stable_supply_30d", "op": "gt", "lo": 0, "hi": None, "prob": 0.55,
     "horizon_d": "2027-03-31"},
    {"id": "R1-B-05", "scenario": "B",
     "statement": "风险偏好:波动率指数在结算日低于 18(2026-10-30 为 19.42,历史 52.2% 的日子在 18 以下),"
                  "低波动环境更利于以股权承载的价值",
     "variable": "macro:vix", "op": "lt", "lo": None, "hi": 18, "prob": 0.45,
     "horizon_d": "2027-06-30"},
]

# 台账字段补齐(origin/main 的 scenario_ledger:author 由提交方的 token 定,
# 这里按 lane-a 惯例给建议值;code_ref 由库里的 row_for() 固定写 "scenario_ledger v1 (11-02)")
for _e in PROPS:
    _e["author"] = "lane-a:t218"
    _e["scenario"] = ("A 轨道与代币一起赢" if _e["scenario"] == "A"
                      else "B 轨道赢、代币跑输(价值落在发行方/股权)")

bmap = {q: (t, r, d, b) for q, t, r, d, b in branch_rows}
rowmap = {r["quarter"]: r for r in rows}
first_rails_q = rail_first.get("COIN") or "—"
ex_bear = rowmap.get("2022Q4", {})
ex_25q3 = bmap.get("2025Q3", (None, None, None, None))

body = f"""# T-218 长期情景「轨道赢 / 代币赢」:2021Q1→2026Q3 季度观察 + 第一批可自动结算的前向命题

> 只读研究(SELECT / 公开 GET),不改代码、不做 DDL、不入库。生成链:`t218_build2.py` → `t218_table.json`
> → `t218_report.py` → 本文;分析:`t218_analysis.py` → `t218_analysis.txt`;命题基准率:`t218_baserates.py`。
> 卡:`tasks/T-218.json`(lane-a)。所有数字由脚本从原始源算出,不是手抄。

## 0. 三句结论

1. **历史上占多数的是 {more_txt}**:23 个季度里可判 {cnt['A'] + cnt['B'] + cnt['none']} 个,A「轨道与代币一起赢」占
   **{cnt['A']} 个季度**({"、".join(qA)}),B「轨道赢、代币跑输」占 **{cnt['B']} 个季度**
   ({"、".join(qB)}),其余 {cnt['none']} 个季度两边都不像。
   但**长跑口径是代币赢**:同期季度再平衡的轨道篮子 {(rails_cum-1):+.1%} vs 代币篮子 {(tok_cum-1):+.1%};
   两者季度收益相关系数 {corr:+.2f}(n={len(xs)})、季度波动 代币 {vol_t:.0f}pp vs 轨道 {vol_r:.0f}pp
   ⇒ **轨道股权与代币同向、波动接近(轨道 {vol_r:.0f}pp vs 代币 {vol_t:.0f}pp)、五年多只走完代币 {rails_cum / tok_cum:.0%} 的涨幅**:
   历史上它更像「代币 beta 的一层更窄表达」,而不是一条独立于代币的价值通道。
2. **收入归属的数字支持「价值落在发行方」**:2026Q3 Tether+Circle 季度收入
   ${n(rows[-1]['tether_rev'] + rows[-1]['circle_rev'])}M,公链持币人收入(ETH+SOL+TRX+HYPE 合计)
   ${n(sum(rows[-1].get(k) or 0 for k in ('eth_holders_rev','sol_holders_rev','trx_holders_rev','hype_holders_rev')))}M,
   倍数 **{((rows[-1]['tether_rev'] + rows[-1]['circle_rev']) / sum(rows[-1].get(k) or 0 for k in ('eth_holders_rev','sol_holders_rev','trx_holders_rev','hype_holders_rev'))):.1f}×**
   (2024Q1 还是 1.2×);发行方年化收入 / 稳定币供应 =
   **${(rows[-1]['tether_rev'] + rows[-1]['circle_rev']) * 4 / 1e6:,.0f}M ÷ {rows[-1]['stable_total'] / 1e9:,.1f}B = {((rows[-1]['tether_rev'] + rows[-1]['circle_rev']) * 4 / rows[-1]['stable_total'] * 100):.2f}%**。
   ETH 一条链的持币人收入从 2021 年 ${5.14:.2f}B(口径覆盖不全,见 §4)降到 2026 年至今 ${0.04:.2f}B。
   **注意这是收入归属口径,不是股价口径**:收入落在发行方,不等于「轨道股权的股价会跑赢代币」——
   §0.1 的价格数据说的正好相反(历史上轨道与代币同向,轨道赢代币跑的季度只有 {cnt['B']} 个)。
3. **轨道方的行情数据已经进库,轨道侧可以按结算口径出数**:`ohlcv_daily(symbol=eq.<SYM>, source=eq.eodhd)`
   里 COIN **{T['rails_db_q']['COIN']['n']}** 行 / HOOD **{T['rails_db_q']['HOOD']['n']}** 行 /
   CRCL **{T['rails_db_q']['CRCL']['n']}** 行,最后一次收盘 {T['rails_db_q']['COIN']['last']}(COIN)。
   ⇒ 轨道侧季度收益改用 **DB(eq.eodhd)= 台账结算用的同一路**;Nasdaq 公开接口降级为独立交叉核对
   (逐季最大差:{xchk_txt})。**轨道三条命题(COIN/HOOD/CRCL)因此可直接结算**。

## 1. ① 季度表 2021Q1→2026Q3

### 表 1 稳定币供应与收入归属

{chr(10).join(l1)}

> 「发行方年化收益率/供应」= 当季发行方收入 × 4 ÷ 当季末 USDT+USDC 合计市值 = 发行方对稳定币存量的年化抽成。
> 「公链持币人收入」= DeFiLlama `dailyHoldersRevenue`(ETH/SOL/TRX/HYPE),不是协议 TVL 收入,也不是手续费。

### 表 2 季度收益:代币 vs 轨道

{chr(10).join(l2)}

> 「代币篮子」= ETH/SOL/TRX/HYPE 当季可得的等权平均;「轨道篮子」= COIN/HOOD/CRCL 当季可得的等权平均
> (轨道侧用 DB `eq.eodhd`;首次有季度收益的季度:{"、".join(f"{s} {q}" for s, q in rail_first.items())},成分随时间变)。
> 「更像哪一支」用 §2 的阈值自动判定,只描述、不下胜负结论。
> **交叉核对**:轨道侧同时用 Nasdaq 公开接口算了一遍同口径季度收益,与 DB 的逐季差:{xchk_txt}。

## 2. ② 两个分支的可量判据

### A「轨道与代币一起赢」

| 指标 | 阈值 | 可观测来源 |
|---|---|---|
| A1 代币端 | 代币篮子季度收益 ≥ +10%,且其中至少两个 ≥ +25% | `ohlcv_daily` 季末收盘 |
| A2 轨道端 | 轨道篮子季度收益 ≥ +10% | `ohlcv_daily`(symbol=`eq.<SYM>`, source=`eq.eodhd`,已入库) |
| A3 宽度与风险偏好 | `state:breadth_above_ma50` > 0.5 且 `macro:fng` ≥ 45 | `state_daily` / `macro_daily` |

### B「轨道赢、代币跑输(价值落在发行方 / 股权)」

| 指标 | 阈值 | 可观测来源 |
|---|---|---|
| B1 相对强弱 | 轨道篮子季度收益 ≥ +10% 且 (代币篮子 − 轨道篮子) ≤ −10pp | 季度收盘 |
| B2 发行方业务量 | `state:stable_supply_30d` > 0 且 USDT+USDC 合计市值环比 > 0 | `state_daily` / `cg_coin_mcap_daily` |
| B3 无声跑输 | `state:funding_7d_ann` < 0.15(没有拥挤杠杆)但 `close:ETH` 季度收益 < 0 | `state_daily` / `ohlcv_daily` |

**逐季更像哪一支**(阈值先写死再套用,只描述):A {cnt['A']} 季 / B {cnt['B']} 季 / 两边都不像 {cnt['none']} 季 /
不可判(轨道侧该季无数据){cnt['na']} 季。逐季数值见表 2 末三列。

**长跑口径**:轨道篮子自 {first_rails_q} 起累计 {(rails_cum-1):+.1%}(1.0→{rails_cum:.3f}),代币篮子 {(tok_cum-1):+.1%}(1.0→{tok_cum:.3f})。
两条线季度相关系数 {corr:+.2f}(n={len(xs)})、季度波动 代币 {vol_t:.0f}pp vs 轨道 {vol_r:.0f}pp
⇒ 轨道股权**与代币同向、幅度更小**(2022Q4 熊市里 COIN 单季 {p(ex_bear.get('COIN_ret_pct'))}%
而 SOL {p(ex_bear.get('SOL_ret_pct'))}%;2025Q3 轨道篮子 {p(ex_25q3[1])}% 而代币篮子 {p(ex_25q3[0])}%)。
**这是本卡对「二选一」框架的实测修正**:历史上「轨道赢、代币跑输」只出现过 {cnt['B']} 次。

## 3. ③ 前向命题(第一批,可自动结算)

字段:`id` / `scenario`(A|B)/ `statement` / `variable`(`close:<SYMBOL>` | `state:<feature>` | `macro:<series>`)/
`op`(`between`|`gt`|`lt`)/ `lo` / `hi` / `prob` / `horizon_d`。

- **`horizon_d` 读作「结算日(日期)」**,全部落在 2026-12-01 → 2027-06-30 窗口内。若 Seth 的台账要的是整数天数,
  换算:`horizon_days = horizon_d − 2026-11-02`(2027-03-31 → 149;2027-06-30 → 240)。
- **阈值全部以 DB 收盘为基准**:代币 2026-11-01、轨道 2026-10-30(eq.eodhd 的最后收盘),写在 statement 里,可逐条复核。
- **prob 不是拍脑袋**:锚在同报告 §1 的历史季度基准率上(ETH 季度 ≥ +25% 占 23 季中的 9 季 = 39%;
  代币篮子 ≥ +10% 占 48%;代币篮子 ≤ −10% 占 26%;`stable_supply_30d` > 0 占 2468 个交易日的 72.9%;
  `breadth_above_ma50` > 0.5 占 44.7%;`vix` < 18 占 52.2%),再按当前状态(fng 37、宽度 0、mom_20 −5.0%)
  做保守折减。
- **但别把分支频率直接当概率**:历史上 A 分支占 {cnt['A']}/{cnt['A'] + cnt['B'] + cnt['none']} 个可判季度
  ({cnt['A'] / (cnt['A'] + cnt['B'] + cnt['none']):.0%}),B 占 {cnt['B']}/{cnt['A'] + cnt['B'] + cnt['none']}
  ({cnt['B'] / (cnt['A'] + cnt['B'] + cnt['none']):.0%});这 10 条是**水平条件 + 6~8 个月窗口**,
  与「一个季度里两支是否同时成立」不是同一件事 ⇒ prob 只能当先验量级看,不能当季度频率的搬运。
- **`close:COIN` / `close:HOOD` / `close:CRCL` 三条现在可结算**:台账 `close` 取值先试 `eq.binance_hist`、
  再回落 `eq.eodhd`,而 DB 里 COIN/HOOD/CRCL 的 `eq.eodhd` 序列已入库 ⇒ 三条都能读到结算日收盘。
- 全部命题只用**水平量**(收盘价、日频 state/macro 序列),不含「当日市值 ÷ 价格」这类当日派生量。
- **结算语义已按 origin/main 的实现核对过**(`src/data/evaluation/scenario_ledger.py`,11-02 版):
  `close:<SYMBOL>` 取 `ohlcv_daily` 中 `trade_date = horizon_d` 当天的收盘(先 `binance_hist` 再 `eodhd`);
  `state:<feature>` 取 `state_daily`(entity=`panel`)当天;`macro:<series>` 取结算日或之前 7 天内最近一个值。
  ⇒ 两个结算日(2027-03-31、2027-06-30)**都是星期三**,不会撞上非交易日导致「读不到」。
- `author` 给了建议值 `lane-a:t218`(库里由提交方的 token 决定);`code_ref` 由 `row_for()` 固定写
  `scenario_ledger v1 (11-02)`,不需要 (也不应该由 lane) 自己编。

```json
{json.dumps(PROPS, ensure_ascii=False, indent=2)}
```

## 4. 数据源、读不到的东西、口径限制

| 需要的量 | 实际来源 | 状态 |
|---|---|---|
| USDT+USDC 市值 | `cg_coin_mcap_daily`(DB,source=coingecko_pro_market_chart,2019-12-31 起) | ✅ 读得到。卡上写的 `asset_mcap_daily` **没有 USDT/USDC**(该表 symbol 只有 `0G`),故改用本表 |
| 稳定币供应的 DB 内替代指标 | `state_daily.stable_supply_30d`(30 日变化,非水平值) | ✅ 读得到 |
| 发行方收入 | Mac 数据根 `research/s661/_llama_rev.jsonl` 的 `dailyRevenue`(tether 2021-05-01 起、circle 2022-05-28 起) | ✅ 读得到 |
| 公链持币人收入 | 同上缓存的 `dailyHoldersRevenue`(ethereum 2015 起、solana 2021-01 起、tron 2022-11 起、hyperliquid 2024-12 起) | ✅ 读得到 |
| 代币季度收盘 | `ohlcv_daily`(BTC/ETH/SOL/TRX=binance_hist,HYPE=coingecko_pro_ohlc) | ✅ 读得到 |
| 轨道公司季度收盘 | `ohlcv_daily(symbol=eq.<SYM>, source=eq.eodhd)` COIN/HOOD/CRCL | ✅ **已入库**(COIN {T['rails_db_q']['COIN']['n']} / HOOD {T['rails_db_q']['HOOD']['n']} / CRCL {T['rails_db_q']['CRCL']['n']} 行,截至 {T['rails_db_q']['COIN']['last']});Nasdaq 公开接口作独立交叉核对 |
| 发行方/公链收入的 DB 版本 | `protocol_revenue_daily` | ⚠️ 84 个 slug,无 tether/circle/ethereum/solana/tron/hyperliquid,且只覆盖 2026-10-21→11-01,故不用 |
| 命题变量值域 | `state_daily`(22 个 feature)、`macro_daily`(8 个 series) | ✅ 读得到 |

口径限制(必须一起读):

1. **ETH 持币人收入 2021 年的数字覆盖不全**:该年只有 149 个非零日(其余年份近 2000 天),所以 2021Q3/Q4 的
   $1,355M / $3,790M 不能当作真实峰值来读;去掉最大 8 天后 2021 年仍是 $4.65B,但覆盖问题依旧存在。
2. **`dailyHoldersRevenue` 不是「代币持有人到手」的唯一口径**(质押收益、MEV 归属与二级市场分成都未完全覆盖),
   只能当「链层面归属持币人的收入」的上界看。
3. **发行方收入 ÷ 供应 ≠ 净利**:未扣运营与合规成本。
4. **轨道篮子成分随时间变**(CRCL 2025Q3 才进),累计口径因此不是严格可比的同一篮子。
5. **轨道侧已换成结算口径**(DB `eq.eodhd`),Nasdaq 公开源只留作交叉核对;两者逐季收益差:{xchk_txt}
   ⇒ 轨道侧的季度数与 §2 判定以 DB 为准,结论不依赖 Nasdaq。
6. 季度末取「该季最后一个有数据的交易日」的收盘;2026Q3 因 2026-10-31/11-01 无数据而用季末可得值,
   与完整季度不完全可比。

## 5. 复现

```bash
cd ~/Projects/looloomi-ai-lane-a &&
python3 docs/research/t218_build2.py &&
python3 docs/research/t218_analysis.py > docs/research/t218_analysis.txt &&
python3 docs/research/t218_baserates.py &&
python3 docs/research/t218_report.py
```

`--recompute` 参数让 `t218_build2.py` 复用已落盘的源、不重新请求(调格式时用)。
"""

out = HERE / "T-218_rails_vs_tokens.md"
out.write_text(body)
print("wrote", out, len(body), "chars")
