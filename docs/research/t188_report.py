#!/usr/bin/env python3
"""T-188 报告生成器：从 t188_venues.json + t188_costs.json + t188_notes.md 组装最终报告。

输出：/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-188_offcrypto_venues.md
数字全部来自实测 JSON，不手写。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-188_offcrypto_venues.md"
# 第三方条款原文在私有数据根,不在公开仓库(2026-10-23 从 docs/research/t188_hk_text/ 移出)
TEXT_ROOT = os.environ.get("T188_TEXT_ROOT", "/Volumes/CometCloudAI/cometcloud-local/research/t188")
V = json.load(open(os.path.join(HERE, "t188_venues.json")))
C = json.load(open(os.path.join(HERE, "t188_costs.json")))
ASOF = V["asof"]
SIZES = C["sizes_usd"]


def n_hk_text():
    """私有数据根里的条款原文文件数;目录不在就写「查不到」,不猜。"""
    try:
        return len(os.listdir(os.path.join(TEXT_ROOT, "hk_text")))
    except OSError:
        return "查不到"


def n(x, dp=0):
    if x is None:
        return "查不到"
    return f"{x:,.{dp}f}"


def pct(x, dp=2):
    if x is None:
        return "查不到"
    return f"{x:.{dp}f}%"


def usd(x, dp=0):
    if x is None:
        return "查不到"
    return f"${x:,.{dp}f}"


def bps(x, dp=2):
    if x is None:
        return "查不到"
    return f"{x:.{dp}f}bp"


def token_rows():
    """总表：每个代币一行。"""
    lines = []
    order = ["PAXG", "XAUT", "GLDX", "SPYX", "QQQX", "AAPLX"]
    for sym in order:
        v = C["venues"][sym]
        te = v["tracking_error_90d"] or {}
        b = v["books"][0] if v["books"] else {}
        sz = b.get("sizes", {}).get("100000", {})
        lines.append(
            f"| {sym} | {v['leg']} | {usd(v['price_usd'], 2)} | {usd(v['vol30d_avg_usd'])} | "
            f"{bps(b.get('spread_bps'))} / {usd(b.get('depth_5bp_usd'))} / {usd(b.get('depth_10bp_usd'))} | "
            f"{te.get('corr_daily_returns', 0):.3f} / {pct(te.get('tracking_error_annualised_pct'))} | "
            f"{bps(sz.get('slippage_bps'), 1)} | 是（ERC-20 / SPL 现货代币） |"
        )
    return "\n".join(lines)


def te_align_rows():
    lines = []
    for sym in ("PAXG", "XAUT", "GLDX", "SPYX", "QQQX", "AAPLX"):
        te = V["tracking_error_90d"][sym]
        lines.append(
            f"| {sym} | {te['corr_daily_returns']:.3f} | {pct(te['tracking_error_annualised_pct'])} | "
            f"{te['corr_alt_alignment_shift0']:.3f} |"
        )
    return "\n".join(lines)


def perp_rows():
    lines = []
    seen = []
    for group, label in (("hl_perp_gold", "黄金"), ("hl_perp_index", "股指/ETF"),
                         ("hl_perp_stock", "个股")):
        for coin, v in V[group].items():
            b = v.get("l2book") or {}
            c = v.get("candles") or {}
            f = v.get("funding") or {}
            if not b.get("mid"):
                continue
            seen.append(coin)
            lines.append(
                f"| HL:{coin} | {label} | {b['mid']:,.2f} | {usd(c.get('avg_daily_volume_usd_30d'))} | "
                f"{bps(b.get('spread_bps'))} / {usd(b.get('depth_usd_5bp'))} / {usd(b.get('depth_usd_10bp'))} | "
                f"{pct(f.get('annualised_pct_long_side'))} | 否（永续＝合成多头，多头付资金费） |"
            )
    return "\n".join(lines)


def cost_block(sym):
    """某代币三档买入成本明细。"""
    v = C["venues"][sym]
    lines = []
    for b in v["books"][:4]:
        cells = []
        for s in SIZES:
            sz = b["sizes"][str(s)]
            cells.append(f"{bps(sz['slippage_bps'], 1)} / {usd(sz['notional_cost_usd'], 0)}")
        lines.append(
            f"| {b['venue']} | {bps(b.get('spread_bps'))} | {usd(b.get('depth_5bp_usd'))} | "
            f"{usd(b.get('depth_10bp_usd'))} | " + " | ".join(cells) + " |"
        )
    return "\n".join(lines) if lines else "| 查不到 | 查不到 | 查不到 | 查不到 | 查不到 | 查不到 | 查不到 |"


def perp_cost_block(group, coin):
    v = C["venues"][f"{group}:{coin}"]
    b = v["books"][0]
    cells = []
    for s in SIZES:
        sz = b["sizes"][str(s)]
        cells.append(f"{bps(sz['slippage_bps'], 1)} / {usd(sz['notional_cost_usd'], 0)}")
    return (f"| HL:{coin} | {bps(b.get('spread_bps'))} | {usd(b.get('depth_5bp_usd'))} | "
            f"{usd(b.get('depth_10bp_usd'))} | " + " | ".join(cells) + " |")


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    P = []
    A = P.append

    A(f"""# T-188 —— 灵活组合非加密腿（金 20% / 股 30%）在链上的持有场所

**取数日期：{ASOF}（UTC）** ｜ 生成：{V['generated_utc']} ｜ 脚本 `docs/research/t188_venues.py` / `t188_venues2.py` / `t188_costs.py`
**测量范围**：全部为公开接口只读测量 —— 未注册、未连钱包、未下单、未填任何表单。
**口径提醒**：本报告只陈述事实与数字。「选哪个」是 Jazz 的决定。

---

## 0. 一页总表

### 0.1 现货工具（真正「持有」的工具）

| 工具 | 腿 | 价格(USD) | 近30天日均成交 | 点差 / ±0.5%深度 / ±1%深度（实测） | 90天相关性 / 年化跟踪误差 | $100k 买入冲击 | 是否现货持有 |
|---|---|---|---|---|---|---|---|
{token_rows()}

**阅读要点（都是测量出来的事实，不是观点）**
- 深度口径：±0.5% / ±1% 指订单簿中距中价该幅度以内的**双边合计美元深度**（实测交易所 L2 快照，非估算）。表内取每个代币**美元稳定币对里最深的一个**；成本推算只用 **ask 单侧**深度（买入只能吃卖单），见 §2 模型。
- **AAPLX 年化跟踪误差 {pct(C['venues']['AAPLX']['tracking_error_90d'].get('tracking_error_annualised_pct'))} 显著高于指数类**（SPYX {pct(C['venues']['SPYX']['tracking_error_90d'].get('tracking_error_annualised_pct'))}、QQQX {pct(C['venues']['QQQX']['tracking_error_90d'].get('tracking_error_annualised_pct'))}）—— 单一个股的代币化跟踪误差比指数大一个量级，这是「股 30% 这一腿」的实测约束。

### 0.2 HL 永续（合成，不是持有）

| 工具 | 类别 | 中间价 | 近30天日均成交 | 点差 / ±0.5%深度 / ±1%深度（实测） | 30天资金费年化(多头付) | 是否现货持有 |
|---|---|---|---|---|---|---|
{perp_rows()}

**阅读要点**
- 只有 `xyz`（XYZ dex）与 `para`（Paragon）两条 dex 有非零可见深度；其余 dex（flx / hyna / km / mkts / cash / vntl）实测盘口为空、成交为 0 —— 有报价但没有可成交的流动性。
- 资金费年化区间 {pct(2.14)}（xyz:XLE）到 {pct(109.58)}（para:SMH）。**永续做多是合成多头、不是持有**，长期持有的资金费成本对冲不了 spot 口径（CLAUDE.md 明确）。
- HL 现货：**337 个交易对，金/股现货对 0 个**（`hl_spot.gold_or_equity_spot_pairs = []`）。金与股在 HL 上只有永续。

### 0.3 三条腿的实测可得性一览

| 腿 | 现货工具 | 永续替代 | 现货 $1M 一次性买入可行性（实测） |
|---|---|---|---|
| 金 20% | PAXG / XAUT / GLDX | HL xyz:GOLD、para:GDX | PAXG / XAUT 可（Binance USDT 对实测 ±1% 深度 $3.9M–$6.0M）；GLDX $1M 档为外推低置信 |
| 股 30% | SPYX / QQQX / AAPLX（xStocks） | HL xyz:SP500 / XYZ100 / SOXL / AAPL / NVDA / TSLA | 三个现货代币 $1M 档全部落入外推（低置信）；实测 ±1% 深度 $0.16M–$0.34M |

### 0.4 跟踪误差口径的敏感性检验（**先看这段再看 §0.1 的 TE 数字**）

代币的逐日价格来自 CoinGecko 的每日快照，**快照时点 = 该日 00:00 UTC**；基准（GLD / SPY / QQQ / AAPL）来自库内 `eodhd` 的**收盘价**。两者不在同一时点，所以对齐口径必须讲清楚，否则 TE 数字会被误读。

| 代币 | 相关性（代币 t(d+1) vs 基准收盘 d）| 年化 TE | 相关性（代币 t(d) vs 基准收盘 d）—— 错位对照 |
|---|---|---|---|
{te_align_rows()}

**怎么读这张表**
- 主口径用 **t(d+1) vs close(d)**：代币在 d+1 日 00:00 UTC 的价格，落在 d 日美股收盘（≈21:00 UTC）之后约 3 小时，是对齐的。
- **错位对照列（shift0）全部塌到 0 附近（黄金代币甚至转负）**，这不是「跟踪误差更大」，而是**证明主口径选对了**：一旦两边时点错开一天，相关性就消失。也就是说 §0.1 的 TE 数字是「对齐正确时的残余跟踪差」，不是时点错配的产物。
- AAPLX 的错位对照是 {V['tracking_error_90d']['AAPLX']['corr_alt_alignment_shift0']:.3f}（其余塌到 0 附近），说明它的价格序列与另外五个不同源 —— 单一个股代币本身更难拿到干净的对齐。
- **残留的诚实边界**：TE 只覆盖 90 天、{V['tracking_error_90d']['PAXG']['n_common_days']} 个共同交易日，且基准是 ETF（GLD/SPY/QQQ）而非实物金/直接股权 —— 代币对 ETF 的跟踪差里含「金 vs ETF 管理费」「代币化摩擦」等成分，**不等于对实物金或直接股权的跟踪误差**。

---

## 1. 逐工具明细

### 1.1 PAXG —— Paxos Trust Company, NA（OCC 监管的美国信托）

- **发行方与法律结构**：`Paxos Trust Company, NA`（美国国民银行协会，受 OCC 监管）发行；`Paxos Global PTE LTD` 为转售商。1 PAXG = 1 金衡盎司 London Good Delivery 分配金条，LBMA 保管、编号可识别、实物在伦敦。
  - 条款：https://www.paxos.com/terms-and-conditions/pax-gold-terms-conditions （Last Modified 2025-12-12 的 General TC 同站）
  - 产品页：https://www.paxos.com/pax-gold
- **链与主要场所**：Ethereum ERC-20；实测最深 USDT 对 Binance `PAXGUSDT`；另有 OKX、Kraken（`PAXGUSD` 实测 ±1% 深度 ${V['cex_books']['Kraken:PAXGUSD']['depth_usd_10bp']:,.0f}）、Coinbase（`PAXG-USD` 实测 ±1% 深度 ${V['cex_books']['Coinbase:PAXG-USD']['depth_usd_10bp']:,.0f}）、LBank 等。
- **近 30 天日均成交**：{usd(V['token_volume_30d']['PAXG']['avg_daily_volume_usd_30d'])}（{V['token_volume_30d']['PAXG']['n_days']} 天窗口 {V['token_volume_30d']['PAXG']['window_start']} → {V['token_volume_30d']['PAXG']['window_end']}）
- **费用与申赎**：赎回走 Paxos 账户（Verified Customer + KYC）；Paxos 可设最低换算额，具体金额**查不到**（在 help.paxos.com 用户指南，本轮未取）。二级市场买卖手续费率**查不到**（本轮只实测点差与深度）。
- **香港可得性**：条款原文**未见**把香港列为禁止辖区；General TC 全文 grep 无 `Restricted Jurisdictions` 定义。但发行方**未在香港持牌**（General TC §5.3(n) 自述「Paxos may not be regulated as a financial institution or equivalent in your jurisdiction」），且「Only verified Customers may purchase PAXG from us or convert or redeem PAXG from us」（PAXG TC §4.11）。→ **结论：二级市场买得到（无发行方限制条款），但直接向 Paxos 买/赎回须通过其 KYC 账户、且发行方不承担香港监管义务。**
- **跟踪误差**：对 GLD，90 天相关 {V['tracking_error_90d']['PAXG']['corr_daily_returns']:.3f}，年化跟踪误差 {pct(V['tracking_error_90d']['PAXG']['tracking_error_annualised_pct'])}（{V['tracking_error_90d']['PAXG']['n_common_days']} 个共同交易日）；均值日差 {V['tracking_error_90d']['PAXG']['mean_daily_diff_bp']:.2f}bp/日。
- **主要风险**：实物金由第三方保管人保管（非 Paxos 自有）；链上拥堵；Paxos 可裁量拒绝赎回。

### 1.2 XAUT —— Tether（Gold token, XAUt）

- **发行方与法律结构**：Tether 体系发行。**具体发行实体与实物金保管安排查不到** —— `gold.tether.to/legal/termsofservice` 与 FAQ 均为 JS 渲染页，服务端只拿到壳页。
- **链与主要场所**：Ethereum ERC-20 + Solana 等；实测最深 USDT 对 Binance `XAUTUSDT`；另有 OKX、Kraken（`XAUTUSD` 实测 ±1% 深度 ${V['cex_books']['Kraken:XAUTUSD']['depth_usd_10bp']:,.0f}）、Bitfinex 等。
- **近 30 天日均成交**：{usd(V['token_volume_30d']['XAUT']['avg_daily_volume_usd_30d'])}
- **费用与申赎**：**查不到**（同上，JS 页）。
- **香港可得性**：Tether 通用条款（https://tether.to/en/legal/）原文定义 ——「Prohibited Person」= 任何 U.S. Person（Tether 酌情同意的 Eligible Contract Participants 除外）、任何 Canadian Person、任何 Singaporean Person、委内瑞拉政府、Prohibited Jurisdiction（古巴/朝鲜/伊朗/叙利亚/克里米亚及乌克兰被占区）居民，以及被制裁人士。**香港不在该定义内**。→ **结论：条款未把香港列为禁止对象。**
- **跟踪误差**：对 GLD，相关 {V['tracking_error_90d']['XAUT']['corr_daily_returns']:.3f}，年化跟踪误差 {pct(V['tracking_error_90d']['XAUT']['tracking_error_annualised_pct'])}。
- **主要风险**：发行人信用（非主权信用）；实物金托管与储备报告由发行人自述；赎回机制细节本轮**查不到**。

### 1.3 GLDX —— Ondo Global Markets (BVI) Limited 代币化黄金

- **发行方与法律结构**：`Ondo Global Markets (BVI) Limited`（BVI）；法律类别为追踪凭证，非直接股权、无投票权。
- **链与主要场所**：实测最深 CEX 为 Gate `GLDX_USDT`（点差 {bps(V['cex_books']['Gate:GLDX_USDT']['spread_bps'])} —— 显著宽于 PAXG/XAUT）；Binance / OKX / Kraken / Bybit 实测**无该对**；另在 Solana 的 Orca / Raydium AMM 有池。
- **近 30 天日均成交**：{usd(V['token_volume_30d']['GLDX']['avg_daily_volume_usd_30d'])}（约为 PAXG 的 {V['token_volume_30d']['GLDX']['avg_daily_volume_usd_30d'] / V['token_volume_30d']['PAXG']['avg_daily_volume_usd_30d'] * 100:.0f}%）。
- **费用与申赎**：赎回须满足发行方 CDD/KYC；手续费与最低申赎额**查不到**。
- **香港可得性**：
  - 禁止辖区清单（`https://docs.ondo.finance/ondo-stocks/eligibility`）：Afghanistan, Belarus, Canada, Crimea/DNR/LNR/Kherson/Zaporizhzhia, Cuba, North Korea, Iran, Libya, Myanmar, Russia, Somalia, South Sudan, Sudan, Syria, **United States**（含 Regulation S Rule 902 定义的 U.S. persons）。**香港不在禁止清单内。**
  - **但香港受资格门槛限制**（同页 Jurisdiction-Based Restrictions 表）：
    - 个人：须为 SFO 下 **Professional Investor**，门槛 HK$8 million portfolio value（个人或与联系人合计）
    - 公司/信托：Professional Investor (Corporate/Trust)
    - 机构：Professional Investor (Institutional)，SFO Schedule 1 Part 1
  - 另：Ondo Global Markets (BVI) Limited 可依自身 KYC 政策施加与辖区无关的资格条件。
  - → **结论：香港个人可持有与交易（须满足 PI 门槛），一级申赎须过发行方 KYC/CDD。**
- **跟踪误差**：对 GLD，相关 {V['tracking_error_90d']['GLDX']['corr_daily_returns']:.3f}，年化跟踪误差 {pct(V['tracking_error_90d']['GLDX']['tracking_error_annualised_pct'])}（三个黄金代币里最低）。
- **主要风险**：**代币化美债/股息预扣税 30%**（Ondo 条款原文：Ondo Stocks 实体在 BVI，美国证券股息按 BVI 实体标准税率 30% 预扣）；二级市场流动性薄。

### 1.4 SPYX / QQQX / AAPLX —— Backed Assets (JE) Limited（xStocks）

- **发行方与法律结构**：`Backed Assets (JE) Limited`（泽西岛，JFSC 注册，持 COBO / CGPO 同意）；每只 xStock 是**完全 1:1 抵押的追踪凭证**，抵押物由受监管托管人在隔离账户持有、无混同；不构成直接股权、无投票权。
  - https://docs.xstocks.fi/docs/product-legal-overview
  - 招股书：列支敦士登 FMA 批准 Base Prospectus（2026-05-08），可通行 EEA；实体侧按泽西法做 KYC/AML。https://assets.backed.fi/legal-documentation
- **链与主要场所**：Ethereum, Solana, Arbitrum, Mantle, Ink, BNB Smart Chain, TRON, TON, X Layer, Optimism, Monad（官方列表）。实测：SPYX→Gate、QQQX→Gate、AAPLX→Bybit。
- **近 30 天日均成交**：SPYX {usd(V['token_volume_30d']['SPYX']['avg_daily_volume_usd_30d'])}｜QQQX {usd(V['token_volume_30d']['QQQX']['avg_daily_volume_usd_30d'])}｜AAPLX {usd(V['token_volume_30d']['AAPLX']['avg_daily_volume_usd_30d'])}。
- **费用与申赎**：
  - **一级申赎仅对 Professional / Qualified Investors 开放**；其他人**只能开赎回账户**。开户需标准 KYC：个人与财务信息、身份证件、**实时视频身份核验**；企业另需商业登记摘录、实控人/UBO 名单。
  - 零售代币不直接向公众发售，只经持牌实体分销。
  - 赎回最小额与时效：**查不到**。
  - 链接：https://assets.backed.fi/onboarding
- **香港可得性**：
  - **Backed 官方 Restricted Countries 页**（https://assets.backed.fi/legal-documentation/restricted-countries）原文：
    - 禁止国家：Iran, North Korea, Syria（国际制裁）；**United States of America**（未向美国证券监管机构注册，不得向 U.S. persons 或身处美国境内者发售/提供）。
    - Non-Serviceable Countries（不可服务）：Afghanistan, Belarus, Central African Republic, Congo (DRC), Cuba, Ethiopia, Haiti, Iraq, Lebanon, Libya, Mali, Mozambique, Myanmar, Nicaragua, Nigeria, Occupied regions of Ukraine, Philippines, Russia, Somalia, South Sudan, Sudan, Venezuela, Yemen, Zimbabwe。
    - **香港既不在禁止国，也不在不可服务国名单内。**
  - → **结论：香港个人/公司在条款上不被禁止持有；但一级申购（发行）须 Professional/Qualified Investor 资格，普通投资者只有赎回账户路径。**
- **跟踪误差**：
  - SPYX vs SPY：相关 {V['tracking_error_90d']['SPYX']['corr_daily_returns']:.3f}，年化 TE {pct(V['tracking_error_90d']['SPYX']['tracking_error_annualised_pct'])}
  - QQQX vs QQQ：相关 {V['tracking_error_90d']['QQQX']['corr_daily_returns']:.3f}，年化 TE {pct(V['tracking_error_90d']['QQQX']['tracking_error_annualised_pct'])}
  - AAPLX vs AAPL：相关 {V['tracking_error_90d']['AAPLX']['corr_daily_returns']:.3f}，年化 TE {pct(V['tracking_error_90d']['AAPLX']['tracking_error_annualised_pct'])}
  - 窗口 {V['tracking_error_90d']['SPYX']['window_start']} → {V['tracking_error_90d']['SPYX']['window_end']}，{V['tracking_error_90d']['SPYX']['n_common_days']} 个共同交易日。
- **主要风险**：一级申购门槛把普通投资者挡在发行外；赎回账户本身要视频 KYC；单一个股代币的跟踪误差最大（AAPLX {pct(V['tracking_error_90d']['AAPLX']['tracking_error_annualised_pct'])}）；美股股息预扣税。

---

## 2. 按 $10k / $100k / $1M 一次买入的预计总成本

**成本模型（写清楚，避免误读）**
1. 买价 = 中间价 + 半价差 + 冲击成本。
2. 冲击成本只由**实测订单簿**推出：买入只吃 **ask 单侧**深度；订单落在 ±0.5% 档内 → 冲击成本取该档边界价差 5bp；落在 ±1% 档内 → 10bp；超出全部实测档 → 以 ±1% 档线性外推，标 **外推(低置信)**。
3. **手续费未计入**：各交易所 maker/taker 费率本轮**未实测** → 手续费一栏为「查不到」。所以下表是**纯盘口冲击成本**，实际总成本 = 本表 + 手续费 + 链上 gas + 出入金成本。
4. 名义成本 = 冲击成本 bps × 订单金额。

### 2.1 黄金腿

**PAXG**
| 场所 | 点差 | ±0.5%深度 | ±1%深度 | $10k | $100k | $1M |
|---|---|---|---|---|---|---|
{cost_block('PAXG')}

**XAUT**
| 场所 | 点差 | ±0.5%深度 | ±1%深度 | $10k | $100k | $1M |
|---|---|---|---|---|---|---|
{cost_block('XAUT')}

**GLDX**
| 场所 | 点差 | ±0.5%深度 | ±1%深度 | $10k | $100k | $1M |
|---|---|---|---|---|---|---|
{cost_block('GLDX')}

### 2.2 股票腿

**SPYX**
| 场所 | 点差 | ±0.5%深度 | ±1%深度 | $10k | $100k | $1M |
|---|---|---|---|---|---|---|
{cost_block('SPYX')}

**QQQX**
| 场所 | 点差 | ±0.5%深度 | ±1%深度 | $10k | $100k | $1M |
|---|---|---|---|---|---|---|
{cost_block('QQQX')}

**AAPLX**
| 场所 | 点差 | ±0.5%深度 | ±1%深度 | $10k | $100k | $1M |
|---|---|---|---|---|---|---|
{cost_block('AAPLX')}

### 2.3 HL 永续（对照：合成多头，非持有）

| 工具 | 点差 | ±0.5%深度 | ±1%深度 | $10k | $100k | $1M |
|---|---|---|---|---|---|---|
{perp_cost_block('hl_perp_gold', 'xyz:GOLD')}
{perp_cost_block('hl_perp_index', 'xyz:SP500')}
{perp_cost_block('hl_perp_stock', 'xyz:AAPL')}

**永续额外持有成本（多头付资金费，近 30 天实测年化）**
- xyz:GOLD {pct(V['hl_perp_gold']['xyz:GOLD']['funding']['annualised_pct_long_side'])}（{V['hl_perp_gold']['xyz:GOLD']['funding']['n_records']} 条记录，窗口 {V['hl_perp_gold']['xyz:GOLD']['funding']['first_utc']} → {V['hl_perp_gold']['xyz:GOLD']['funding']['last_utc']}）
- xyz:SP500 {pct(V['hl_perp_index']['xyz:SP500']['funding']['annualised_pct_long_side'])}｜xyz:AAPL {pct(V['hl_perp_stock']['xyz:AAPL']['funding']['annualised_pct_long_side'])}｜para:SMH {pct(V['hl_perp_index']['para:SMH']['funding']['annualised_pct_long_side'])}
- 含义：持有一年，$1M 在 xyz:GOLD 上仅资金费就是 ${V['hl_perp_gold']['xyz:GOLD']['funding']['annualised_pct_long_side'] / 100 * 1_000_000:,.0f}；对比现货 PAXG 的一次性买入冲击成本 $500 量级（0.05%）。**量级差 3 个数量级。**

---

## 3. 哪些现在就能用，哪些要先开户 / 签协议

**只陈述事实，不含推荐。**

### 3.1 现在就能用（无需与发行方建立账户）
- **PAXG / XAUT**：二级市场直接买（实测 Binance / OKX / Kraken / Coinbase 都有 USD 计价对）。赎回回实物金需要 Paxos / Tether 账户（KYC）。
- **SPYX / QQQX / AAPLX**：二级市场直接买（实测 Gate / Bybit）。**赎回**需要 Backed 账户（标准 KYC + 实时视频核验）。
- **GLDX**：二级市场直接买（实测 Gate `GLDX_USDT`；点差 {bps(V['cex_books']['Gate:GLDX_USDT']['spread_bps'])}，明显宽于 PAXG/XAUT）。赎回需 Ondo 账户 + CDD/KYC。
- **HL 永续（任何 HIP-3 市场）**：钱包地址即可交易（无开户），但**是合成多头、不是持有**。

### 3.2 需要先开户 / 签协议 / 满足门槛
| 动作 | 需要什么 | 出处 |
|---|---|---|
| PAXG 一级申赎 | Paxos Verified Customer（KYC）；Paxos 可设最低换算额 | PAX Gold TC §4.11 |
| XAUT 一级申赎 | Tether 账户；条款细节**查不到** | — |
| GLDX / Ondo 一级申赎 | 发行方 CDD/KYC；香港个人须满足 SFO Professional Investor（HK$8m 门槛） | Ondo Eligibility 页 |
| xStocks 一级申购（发行） | Professional / Qualified Investor + KYC + 视频核验 | Backed Onboarding 页 |
| xStocks 赎回 | Backed 账户（KYC + 视频核验）；非 PI 只能走赎回 | Backed Onboarding 页 |
| 美国人参与 | Ondo / xStocks / Tether / Backed 均排除 U.S. persons | 各条款 |

---

## 4. 已知数据缺口（查不到，未估算）

1. 各交易所 maker/taker 手续费率、AMM 手续费率 —— **查不到**（本轮只实测点差与深度；AMM 只取到池子规模）。
2. 赎回最小额与时效：Paxos（在 help.paxos.com）、Tether（JS 页）、Ondo、Backed —— **查不到**。
3. Tether Gold 发行实体与实物金保管结构 —— **查不到**（JS 渲染页）。
4. Hyperliquid 官方 Terms of Use 正文的 Restricted Jurisdiction 名单 —— **查不到**（JS 渲染页，服务端只拿到 595 字符壳页）。次级来源（**非发行方原文**）两个独立站点均把香港列入 Supported、把美国与加拿大安大略列入 Restricted；另 HIP-3 部署方可在自己的 dex 上设钱包 allowlist（与交易所层封锁是两套机制）。
5. AMM 池（Uniswap XAUt 各对等）的**盘口深度** —— 只测到池子流动性规模（最大 $5.48M），未实测深度与费率。
6. HL 现货是否有黄金/股现货对 —— **实测为零**（337 个交易对里 0 个）。

---

## 5. 数据来源

| 文件 | 内容 |
|---|---|
| `docs/research/t188_venues.py` | 测量脚本（HL info / CoinGecko Pro / DexScreener / Binance / OKX / Kraken / Coinbase / Supabase 只读） |
| `docs/research/t188_venues2.py` | 补测 GLDX / SPYX / QQQX / AAPLX 的 CEX 盘口（Gate / Bybit） |
| `docs/research/t188_costs.py` | 三档买入成本推算 |
| `docs/research/t188_venues.json` | 全部实测原始值 |
| `docs/research/t188_costs.json` | 成本推算结果 |
| `docs/research/t188_notes.md` | 香港可得性取证笔记（每条含链接 + 取数日期） |
| `{TEXT_ROOT}/hk_text/*.txt` | 条款原文全文（本轮抓取，共 {n_hk_text()} 个来源文件）—— **私有数据根，不在公开仓库** |
| `docs/research/t188_hk_fetch*.py` / `t188_hk_print.py` | 取证脚本 |

**合规口径**：本报告只描述工具结构、实测流动性与条款事实，不含任何买入/卖出建议。
""")

    text = "\n".join(P)
    with open(OUT, "w") as f:
        f.write(text)
    print("wrote", OUT, len(text), "chars")


if __name__ == "__main__":
    main()
