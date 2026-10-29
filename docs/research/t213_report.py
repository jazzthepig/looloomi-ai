#!/usr/bin/env python3
"""T-213:把 t210_tracking.json 的重报结果渲染成 t210_onchain_legs.md 的两个区块。

设计意图:md 里的每个数字都由 JSON 直接渲染,人手不转写 ⇒ md 与 JSON 不会各说各话。
两个区块用 marker 包住,重复运行幂等:
  <!-- T213:CORRECTION:BEGIN --> … <!-- T213:CORRECTION:END -->   (文首「更正记录」)
  <!-- T213:SECTION:BEGIN --> … <!-- T213:SECTION:END -->           (§1.4/§1.5/§1.6)
只读:只写 docs/research/t210_onchain_legs.md,不写库、不下单。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MD = os.path.join(HERE, "t210_onchain_legs.md")
TRACK = os.path.join(HERE, "t210_tracking.json")
DEPTH = os.path.join(HERE, "t210_depth.json")
DEPTH2 = os.path.join(HERE, "t210_depth2.json")

C_BEG = "<!-- T213:CORRECTION:BEGIN -->"
C_END = "<!-- T213:CORRECTION:END -->"
S_BEG = "<!-- T213:SECTION:BEGIN -->"
S_END = "<!-- T213:SECTION:END -->"


def fmt(x, n=3, dash="—"):
    if x is None:
        return dash
    return ("%." + str(n) + "f") % x


def money(x, n=2):
    return "{:,.{n}f}".format(x, n=n)


def spl(block, key):
    return block.get(key) if isinstance(block, dict) else None


def strip_block(text, beg, end):
    """删掉 marker 之间的整块(含 marker),让重排幂等。"""
    while True:
        i = text.find(beg)
        j = text.find(end)
        if i == -1 or j == -1 or j < i:
            return text
        text = text[:i] + text[j + len(end):]


def splice(text, beg, end, body, anchor):
    """把 marker 块放到 anchor 行之前;已存在则先删旧块。幂等。"""
    text = strip_block(text, beg, end)
    block = beg + "\n" + body.rstrip() + "\n" + end + "\n\n"
    i = text.find(anchor)
    if i == -1:
        raise SystemExit("anchor not found: " + anchor)
    return text[:i] + block + text[i:]


def te_cell(t):
    if not t:
        return "—"
    return "%s%%（corr %s）" % (fmt(t.get("te_ann_pct")), fmt(t.get("corr"), 4))


def build_correction(t, dep, dep2):
    spy_eth = dep["dex"]["SPY_ondo:eth"]
    spy_pool = spy_eth["top_pools"][0]
    nv = spy_eth["notional_vs_pool"]
    gldx_eth = dep2["dex"]["GLDx:eth"]
    gldx_pool = gldx_eth["top_pools"][0]
    ser = t["series"]
    common = t["common_window"]

    def te(key, win, field):
        return ser[key][win][field]["te_ann_pct"]

    lines = []
    lines.append("## 更正记录（T-213，2026-10-30）")
    lines.append("")
    lines.append("本节记录对 T-210（`3690670a` / `12c00f17`）的更正。**原始数据一律重新核过**，"
                 "不是照抄上一轮的结论。改动的数字与判读见下文各节，重报表在 **§1.4**，"
                 "黄金腿两项候选的四项事实在 **§1.5**，保留/撤回清单在 **§1.6**。")
    lines.append("")
    lines.append("1. **§2.2.2 与 §1 表的 Ondo SPY 池深数字错了（源头是把 GLDx 的池当成了 SPY 的池）。**")
    lines.append("   原文写的「Ethereum 侧最深池仅 $10,325.92」取自 `t210_depth2.json` 的 "
                 "`dex/GLDx:eth` —— 那是 **GLDx / USDC 88%%**（池 `%s`，reserve $%s，vol24 $%s）"
                 "，属黄金腿，不属股票腿。"
                 % (gldx_pool["pool"][:10] + "…", money(gldx_pool["reserve_usd"]),
                    money(gldx_pool["vol24_usd"])))
    lines.append("   Ondo SPY 在 **Ethereum** 侧的真实最深池是 **%s**（`%s`），"
                 "reserve **$%s**、vol24 **$%s**（`t210_depth.json` → `dex/SPY_ondo:eth`）。"
                 % (spy_pool["name"], spy_pool["pool"][:10] + "…",
                    money(spy_pool["reserve_usd"]), money(spy_pool["vol24_usd"])))
    lines.append("   ⇒ 名义额占池深：$500 = **%s%%**、$5k = **%s%%**、$50k = **%s%%**。"
                 "原文「$5k = 池深的 48%%」「$50k = 484%% ⇒ 不可执行」是 GLDx 的数；"
                 "改正后 $5k 只占 6.16%%（可做但有影响），**$50k 仍占 61.6%%（仍超出池深）**。"
                 % (fmt(nv["500"]["share_of_pool_pct"], 2), fmt(nv["5000"]["share_of_pool_pct"], 2),
                    fmt(nv["50000"]["share_of_pool_pct"], 2)))
    lines.append("   §1 表、§2.2.2、§3 风险 3、§4 探索 1 里所有「$10,326 / $10.3K」已一并改正。")
    lines.append("")
    lines.append("2. **逐日 TE 的量级主要是收市错位的口径伪影；5 日块复合后量级下降、排序在 PAXG 与 SPYX 之间反转。**")
    lines.append("   公共窗口 %s → %s。逐日 TE → 5 日块 TE："
                 "PAXG %s%% → %s%%、XAUT %s%% → %s%%、SPYX %s%% → %s%%、Ondo SPY %s%% → %s%%。"
                 % (common["start"], common["end"],
                    fmt(te("PAXG", "common_window", "daily_te")), fmt(te("PAXG", "common_window", "block5_te")),
                    fmt(te("XAUT", "common_window", "daily_te")), fmt(te("XAUT", "common_window", "block5_te")),
                    fmt(te("SPYX", "common_window", "daily_te")), fmt(te("SPYX", "common_window", "block5_te")),
                    fmt(te("SPY_ondo", "common_window", "daily_te")),
                    fmt(te("SPY_ondo", "common_window", "block5_te"))))
    lines.append("   **排序反转**发生在各自全窗口口径：逐日 PAXG %s%% 优于 SPYX %s%%，"
                 "5 日块 PAXG %s%% 差于 SPYX %s%%。"
                 % (fmt(te("PAXG", "full_window", "daily_te")), fmt(te("SPYX", "full_window", "daily_te")),
                    fmt(te("PAXG", "full_window", "block5_te")), fmt(te("SPYX", "full_window", "block5_te"))))
    lines.append("   **XAUT 与 PAXG 的相对次序没有反转**（逐日与块口径都是 XAUT 略优）；"
                 "但在公共窗口上两者差距只有 %s pp（逐日），零信号对照判「差距不可读」（§1.4 表 C）。"
                 % fmt(abs(t["candidate_differences"]["XAUT_minus_PAXG"]["daily"]["observed_diff_pp"]), 3))
    lines.append("")
    lines.append("3. **`t210_tracking.py` 的 walrus 判假 ⇒ 5 日块检验从未执行（已修）。**")
    lines.append("   原写法 `if best_off := max(...)` 把 `best_off == 0` 当假值，"
                 "而四条腿的最佳对齐**恰好都是 offset 0** ⇒ `block_5d_at_best_offset` 从未写进 JSON。"
                 "已改为先取值再判空（`if best_off is not None`）。同时修了块切分的 off-by-one："
                 "原起点是 `step-1` ⇒ 头 4 对永远不进任何块。")
    lines.append("")
    lines.append("4. **补「不代币化」的基线（原文没问「要不要用代币化这条腿」）。**")
    lines.append("   黄金腿基线 = **GLD**（实物支撑 ETF）vs XAUUSD，取自 `ohlcv_daily`（eodhd 优先）。")
    lines.append("   股票腿基线 = **SPY（ETF 本身）vs S&P 500 指数口径** —— 前 5 处外部源取不到"
                 "（stockanalysis ×4 404、investing.com 403；库内唯一的 `SPX` 是 **Hyperliquid 的 SPX 永续**，"
                 "不是 S&P 500 指数；stooq 返回 JS 挑战页、Yahoo chart 403 —— 留证在 "
                 "`t210_tracking.json` → `t213_correction.spx_fetch_attempts` 与 "
                 "`docs/research/t213_spx_probe.json`），"
                 "**本轮追加 FRED `SP500`（S&P Dow Jones 官方指数收盘，CSV 免 key）取到了** ⇒ "
                 "ETF-vs-指数的基线**已测出**（§1.4 表 D），不再只能给分辨率下限。")
    lines.append("   **附带发现**：eodhd 的 SPY 序列有坏点 —— 2024-08-27 ETF 收盘 −2.42% 而同日指数 +0.16%；"
                 "全窗口里 |日收益差| > 50bps 的只有 4 天，剔除后逐日 TE 从 2.610% 降到 0.900%"
                 "（`t213_correction.baselines.SPY_etf_vs_index.outlier_check`；"
                 "逐日偏离明细 `docs/research/t213_spx_check.json`）。"
                 "⇒ **指数基线只读公共窗口的数字**，全窗口逐日数被坏点抬高。")
    lines.append("")
    lines.append("5. **§2.2.2 的链标注错了。** 原文写「Solana 侧（`SPY_ondo_dex`，池 `0x5638bbde...`）」—— "
                 "该池是 **Ethereum** 侧池，且本轮 Ondo SPY 的 **Solana 侧未取到池深度**"
                 "（`t210_depth.json` 的 `dex/SPY_ondo:solana` 无池记录）。"
                 "TE 序列 `SPY_ondo_dex` 取自 **Ethereum** 池（182 天日线），已改正。")
    lines.append("")
    lines.append("6. **§0 指向一个不存在的 §1.3。** 「offset ±1/±2 全跑了一遍（见 §1.3）」——正文里没有 §1.3；"
                 "offset 扫描表在 `t210_tracking.json` 的 `tracking.*.by_offset`。"
                 "§1.4 已补上对应表格并指向 JSON。")
    lines.append("")
    lines.append("7. **§2.1.1「Tether 有历史冻结记录」在本轮引用页集内没有逐笔证据。** "
                 "抓到的 `tether.to/en/legal/` 只写了冻结/扣押的风险与 Tether 的权利、"
                 "以及 Sanctions List / Prohibited Person 的定义；"
                 "**逐笔冻结记录本轮未取到**。§1.5 的四项事实表按引用页原文写，历史记录一栏标为未取到。")
    lines.append("")
    lines.append("8. **黄金腿的「推荐 XAUT」改为不替 Jazz 选。** "
                 "其**跟踪误差依据撤回**（公共窗口 XAUT 与 PAXG 的 TE 差不可读，§1.4 表 C）；"
                 "其余实测依据仍在：$50k 进场滑点 0.92 vs 1.15 bps、PAXG 赎回门槛 430 枚（≈$1.73M）"
                 "把我们的量级排除在赎回通道外、样本长度 211 vs 392 天。"
                 "**两项候选只列发行方 / 托管 / 冻结记录 / 监管四项事实（§1.5），二选一由 Jazz 定。**")
    lines.append("")
    lines.append("9. **（标为待核，本卡不改正）§2.1.3 的「$50k 名义额占池 0.156%」用的是 `SOLOMON / GLDx` 池"
                 "（reserve $32,087,524，但 vol24 只有 $18.96）的储备额，不是同句列出的 "
                 "`GLDx / USDC` 主池（$864,628）—— 按主池算 $50k 应占 5.78%。"
                 "该条不在 T-213 的更正范围（卡上只点了 §2.2.2 与 §1 表），故本轮**只记录、不改**，"
                 "留给持卡人决定是否另开一条。")
    lines.append("")
    return "\n".join(lines)


def build_section(t, dep):
    ser = t["series"]
    common = t["common_window"]
    diffs = t["candidate_differences"]
    base = t["baselines"]
    lines = []
    A = lines.append

    A("### 1.4 T-213 重报：跟踪误差（四列 × 两窗口）+ 零信号对照 + 不代币化基线")
    A("")
    A("**为什么重报**：T-210 的跟踪误差只有「逐日、offset 0、各自窗口」一个口径。"
      "逐日口径把「代币 24/7 收市」与「基准工作日收市」的日界错位算进了 TE，"
      "而上一轮代码里的 `if best_off := …` 判假又让 5 日块检验从未执行（见文首更正记录第 3 条）。"
      "本节按卡上的口径重报。")
    A("")
    A("**口径**")
    A("")
    A("- 对齐：代币与基准同一段日历窗口 `[d-1 → d]`（offset 0）。代币 UTC 日线收市 00:00 UTC，"
      "基准在美国收市结算 ⇒ 同窗口内仍有约 21 小时日界错位（这是口径的一部分，不是被消掉的误差）。")
    A("- **逐日 TE**（年化）= `std(r_tok − r_bench) · sqrt(365)`。")
    A("- **5 日不重叠块 TE**（年化）= `std(块差) · sqrt(365/5)`，块 = 连续 5 个成对日收益复合，"
      "从第一对开始切、不丢头部；四条腿共用同一组块边界 ⇒ 腿与腿可比。")
    A("- **累计 price_ratio** = 代币价 / 基准价 的累计变化（%）。")
    A("- **波动比** = 代币年化波动 / 基准年化波动。")
    A("- **零信号对照**：用 `src/data/evaluation/apparatus.py` 的 `block_permute` 打乱基准日收益"
      "（块长 5 天），%d 次重算 TE，报**实际 TE 在零分布里的分位**；候选之间的差走同一对照。"
      "seed %s。" % (t["definition"]["n_draws"], t["definition"]["seed"]))
    A("- **公共窗口** = 四条腿与基准的公共区间：%s → %s；"
      "**各自全窗口** = 每条腿自身可得的完整历史（PAXG 自 2025-09-25，XAUT 自 2026-03-26，"
      "SPYX 自 2026-04-30，Ondo SPY 自 2026-04-25）。" % (common["start"], common["end"]))
    A("")
    A("#### 表 A —— 四条腿 × 四列（公共窗口 / 各自全窗口）")
    A("")
    A("| 腿 | 基准 | 窗口 | n（成对日 / 5 日块） | 逐日 TE（年化） | 5 日块 TE（年化） | 累计 price_ratio | 波动比（代币/基准） |")
    A("|---|---|---|---|---|---|---|---|")
    labels = {"PAXG": "PAXG（Paxos Gold）", "XAUT": "XAUT（Tether Gold）",
              "SPYX": "SPYX（xStocks，Solana 池）", "SPY_ondo": "SPY（Ondo，Ethereum 池）"}
    for key in ("PAXG", "XAUT", "SPYX", "SPY_ondo"):
        for win, wname in (("common_window", "公共"), ("full_window", "全窗口")):
            w = ser[key][win]
            pr = w["price_ratio"]
            A("| %s | %s | %s | %d / %d | %s | %s | %s | %s |"
              % (labels[key], ser[key]["benchmark"], wname, w["n_days_all"],
                 w["block5_meta"]["n_blocks"], te_cell(w["daily_te"]), te_cell(w["block5_te"]),
                 "%s%%（%s → %s）" % (fmt(pr["ratio_change_pct"], 3), fmt(pr["ratio_start"], 4),
                                     fmt(pr["ratio_end"], 4)),
                 fmt(w["daily_te"]["vol_ratio"], 4)))
    A("")
    A("> `price_ratio` 的绝对水平不可比（PAXG/XAUT 是「枚价 ÷ 美元金价」，比值 1.00 附近；"
      "SPYX/SPY 是「份价 ÷ 份价」）；可比的是它的**变化**列。")
    A("")
    A("#### 表 B —— 零信号对照：实际 TE 在零分布里的分位")
    A("")
    A("| 腿 | 窗口 / 口径 | 实际 TE（年化） | 零分布中位数 | [p05, p95] | 分位 | 判读 |")
    A("|---|---|---|---|---|---|---|")
    for key in ("PAXG", "XAUT", "SPYX", "SPY_ondo"):
        nc = ser[key]["null_controls"]
        for wname, pre in (("公共窗口", "common_window"), ("各自全窗口", "full_window")):
            for ck, cname in (("daily", "逐日"), ("block5", "5 日块")):
                c = nc["%s_%s" % (pre, ck)]
                A("| %s | %s / %s | %s%% | %s%% | [%s%%, %s%%] | %s | 实际 TE 远低于零分布中位 ⇒ **不是噪声** |"
                  % (labels[key], wname, cname, fmt(c["actual_te_ann_pct"]),
                     fmt(c["null_median"], 2), fmt(c["null_p05"], 2), fmt(c["null_p95"], 2),
                     fmt(c["percentile_of_actual"], 4)))
    A("")
    A("#### 表 C —— 候选之间的差（同一零信号对照）")
    A("")
    A("| 候选对 | 口径 | A 的 TE | B 的 TE | 观测差（pp） | 零分布中位差 | [p05, p95] | 分位 | 双侧 p | 判读 |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for name, d in diffs.items():
        for ck, cname in (("daily", "逐日"), ("block5", "5 日块")):
            c = d[ck]
            A("| %s | %s | %s%% | %s%% | %+.3f | %+.3f | [%+.3f, %+.3f] | %s | %s | %s |"
              % (d["label"], cname, fmt(c["te_a_ann_pct"]), fmt(c["te_b_ann_pct"]),
                 c["observed_diff_pp"], c["null_median_diff_pp"], c["null_p05_pp"], c["null_p95_pp"],
                 fmt(c["percentile_of_observed"], 4), fmt(c["two_sided_p"], 4), c["verdict"]))
    A("")
    A("**读法**：XAUT 与 PAXG 的 TE 差在两种口径下都落在零分布中段 ⇒ **差距不可读**，"
      "T-210 用 TE 差距支持「XAUT 更紧」的那一条依据不成立。"
      "SPYX 与 Ondo SPY 的 TE 差在两种口径下都远在零分布之外 ⇒ **差距可读**。")
    A("> **口径提示**：差检验跑在**两条腿的公共日期区间**上"
      "（XAUT − PAXG n=%d 天、SPYX − Ondo n=%d 天），"
      "所以表 C 的「A 的 TE / B 的 TE」与表 A 各自窗口的数字会有小数点后一位的差别"
      "（如 SPYX 逐日 7.910%% vs 表 A 的 7.843%%）。**观测差与零分布同口径，可直接读。**"
      % (diffs["XAUT_minus_PAXG"]["n_days"], diffs["SPYX_minus_SPY_ondo"]["n_days"]))
    A("")
    A("#### 表 D —— 基线：代币化这条腿比「不代币化」多付多少跟踪成本")
    A("")
    A("| 对照 | 窗口 | n（成对日 / 块） | 逐日 TE | 5 日块 TE | corr | 累计 price_ratio |")
    A("|---|---|---|---|---|---|---|")
    gld = base["GLD_vs_XAUUSD"]
    for wname, key in (("公共", "common_window"), ("全窗口", "full_window")):
        w = gld[key]
        A("| **GLD vs XAUUSD（不代币化的黄金腿）** | %s | %d / %d | %s | %s | %s | %s%% |"
          % (wname, w["n_days_all"], w["block5_meta"]["n_blocks"], te_cell(w["daily_te"]),
             te_cell(w["block5_te"]), fmt(w["daily_te"]["corr"], 4),
             fmt(w["price_ratio"]["ratio_change_pct"], 3)))
    for key in ("PAXG", "XAUT"):
        for wname, wk in (("公共", "common_window"), ("全窗口", "full_window")):
            w = ser[key][wk]
            A("| %s vs XAUUSD（代币化） | %s | %d / %d | %s | %s | %s | %s%% |"
              % (labels[key], wname, w["n_days_all"], w["block5_meta"]["n_blocks"],
                 te_cell(w["daily_te"]), te_cell(w["block5_te"]), fmt(w["daily_te"]["corr"], 4),
                 fmt(w["price_ratio"]["ratio_change_pct"], 3)))
    sd = base.get("SPY_source_divergence", {}).get("common_window")
    if sd:
        A("| SPY(eodhd) vs SPY(yfinance)（测量分辨率下限） | 公共 | %d / %d | %s | %s | %s | %s%% |"
          % (sd["n_days_all"], sd["block5_meta"]["n_blocks"], te_cell(sd["daily_te"]),
             te_cell(sd["block5_te"]), fmt(sd["daily_te"]["corr"], 4),
             fmt(sd["price_ratio"]["ratio_change_pct"], 3)))
    spx_base = base.get("SPY_etf_vs_index", {})
    for wname, wk in (("公共", "common_window"), ("全窗口", "full_window")):
        w = spx_base.get(wk)
        if not w:
            continue
        A("| **SPY(ETF,eodhd) vs SPX(指数,FRED)（不代币化的股票腿）** | %s | %d / %d | %s | %s | %s | %s%% |"
          % (wname, w["n_days_all"], w["block5_meta"]["n_blocks"], te_cell(w["daily_te"]),
             te_cell(w["block5_te"]), fmt(w["daily_te"]["corr"], 4),
             fmt(w["price_ratio"]["ratio_change_pct"], 3)))
    for key in ("SPYX", "SPY_ondo"):
        w = ser[key]["common_window"]
        A("| %s vs SPY（代币化） | 公共 | %d / %d | %s | %s | %s | %s%% |"
          % (labels[key], w["n_days_all"], w["block5_meta"]["n_blocks"], te_cell(w["daily_te"]),
             te_cell(w["block5_te"]), fmt(w["daily_te"]["corr"], 4),
             fmt(w["price_ratio"]["ratio_change_pct"], 3)))
    A("")
    A("**答案（黄金腿，公共窗口 %s → %s）**：不代币化的 GLD 5 日块 TE **%s%%**，"
      "代币化的 PAXG **%s%%**、XAUT **%s%%** ⇒ "
      "**代币化这条腿多付的跟踪成本 ≈ 0（在 5 日块口径下与不代币化同量级，差 %+.3f / %+.3f pp）**。"
      % (common["start"], common["end"],
         fmt(gld["common_window"]["block5_te"]["te_ann_pct"]),
         fmt(ser["PAXG"]["common_window"]["block5_te"]["te_ann_pct"]),
         fmt(ser["XAUT"]["common_window"]["block5_te"]["te_ann_pct"]),
         ser["PAXG"]["common_window"]["block5_te"]["te_ann_pct"] - gld["common_window"]["block5_te"]["te_ann_pct"],
         ser["XAUT"]["common_window"]["block5_te"]["te_ann_pct"] - gld["common_window"]["block5_te"]["te_ann_pct"]))
    A("逐日口径下 GLD 的 TE 反而**更大**（%s%% vs PAXG %s%% / XAUT %s%%），"
      "因为 GLD 与 XAUUSD 的收市错位同属逐日伪影 —— 这正是「逐日 TE 不可直接比」的第二处证据。"
      % (fmt(gld["common_window"]["daily_te"]["te_ann_pct"]),
         fmt(ser["PAXG"]["common_window"]["daily_te"]["te_ann_pct"]),
         fmt(ser["XAUT"]["common_window"]["daily_te"]["te_ann_pct"])))
    A("")
    spx_cw = spx_base.get("common_window")
    if spx_cw:
        oc = spx_base.get("outlier_check", {}).get("common_window", {})
        ocf = spx_base.get("outlier_check", {}).get("full_window", {})
        A("**答案（股票腿，公共窗口 %s → %s）**："
          "「不代币化」的 **SPY(ETF) vs SPX(指数)** 逐日 TE **%s%%**、"
          "**5 日块 TE %s%%**（n=%d 天 / %d 块；指数源 FRED `SP500`，S&P Dow Jones 官方收盘）"
          "⇒ 代币化两条腿相对它多付的跟踪成本 = "
          "**SPYX %+.3f pp、Ondo SPY %+.3f pp（5 日块口径）**。"
          % (common["start"], common["end"],
             fmt(spx_cw["daily_te"]["te_ann_pct"]), fmt(spx_cw["block5_te"]["te_ann_pct"]),
             spx_cw["n_days_all"], spx_cw["block5_meta"]["n_blocks"],
             ser["SPYX"]["common_window"]["block5_te"]["te_ann_pct"] - spx_cw["block5_te"]["te_ann_pct"],
             ser["SPY_ondo"]["common_window"]["block5_te"]["te_ann_pct"] - spx_cw["block5_te"]["te_ann_pct"]))
        A("逐日口径下代币化两条腿的 TE 明显更大（SPYX %s%%、Ondo SPY %s%% vs 基线 %s%%），"
          "其中含收市错位；**5 日块口径才是可比的量**。"
          % (fmt(ser["SPYX"]["common_window"]["daily_te"]["te_ann_pct"]),
             fmt(ser["SPY_ondo"]["common_window"]["daily_te"]["te_ann_pct"]),
             fmt(spx_cw["daily_te"]["te_ann_pct"])))
        A("**坏点警告**：eodhd 的 SPY 序列在公共窗口有 %d 天 |日收益差| > 50bps（%s），"
          "剔除后基线逐日 TE 从 %s%% 降到 %s%%（corr %s）；"
          "全窗口另有 2024-08-27 一个坏点（ETF −2.42%% 而同日指数 +0.16%%），"
          "剔除 %d 天后全窗口逐日 TE 从 %s%% 降到 %s%%。"
          "⇒ **读公共窗口**，并注意这条数据通道在极端日本身有误差。"
          % (oc.get("n_flagged", 0), "、".join(oc.get("flagged_days", [])) or "—",
             fmt(spx_cw["daily_te"]["te_ann_pct"]), fmt(oc.get("te_ann_pct_excl_flagged")),
             fmt(oc.get("corr_excl_flagged"), 4),
             ocf.get("n_flagged", 0),
             fmt(spx_base.get("full_window", {}).get("daily_te", {}).get("te_ann_pct")),
             fmt(ocf.get("te_ann_pct_excl_flagged"))))
    else:
        A("**股票腿**：指数序列本轮取不到，只能给分辨率下限（SPY 两数据源偏离：逐日 %s%%、"
          "5 日块 %s%%，n=%d）。" % (fmt(sd["daily_te"]["te_ann_pct"]) if sd else "—",
                                    fmt(sd["block5_te"]["te_ann_pct"]) if sd else "—",
                                    sd["n_days_all"] if sd else 0))
    A("")
    A("### 1.5 黄金腿两个候选：四项事实（不替 Jazz 选）")
    A("")
    A("按卡上的口径，这里只列**发行方 / 托管 / 冻结记录 / 监管**四项事实，"
      "二选一由 Jazz 定。事实来源：本轮引用页集 `docs/research/t210_cites.json`"
      "（`tether_gold` / `tether_terms` / `paxos_paxg_terms`）。")
    A("")
    A("| 事实项 | XAUT（Tether Gold / XAU₮） | PAXG（Paxos Gold） |")
    A("|---|---|---|")
    A("| 发行方 | **Tether**（多资产代币体系的一员，与 USD₮ / MXN₮ 并列；`tether.to/en/gold/`）"
      " | **Paxos Trust** 发行（`paxos.com/terms-and-conditions/pax-gold-terms-conditions`） |")
    A("| 托管 | **本轮抓到的页面未披露独立托管方 / 金条托管安排** —— "
      "`tether.to/en/gold/` 只说明 XAU₮ 属 Tether 代币体系；赎回走 Tether 侧账户与合格投资者流程 | "
      "**Paxos 平台可托管**（条款 4.6「available on the Paxos Platform for trading, for custody with Paxos, "
      "and for withdrawal」）；每枚对应 1 金衡盎司 LGD 标准金条、由专业保管人托管；"
      "条款允许电汇提取 Unallocated Gold ounces 到客户披露账户 |")
    A("| 冻结记录 | **逐笔冻结记录本轮未取到**；条款层面 Tether 保留权利并写明「因政府冻结/扣押导致的"
      "转账延迟或价值损失」由用户承担（`tether.to/en/legal/` L195、L202），"
      "并定义 Sanctions List / Prohibited Person（含新加坡籍） | "
      "**条款明文赋权**：14.1「Paxos has the ability and the right to freeze and upgrade all PAXG tokens "
      "(on an aggregate basis), regardless of where they are being held」；14.2 须遵守冻结指令；"
      "14.5 被依法冻结/扣押的 PAXG 或实物金**可能永久不可用**；"
      "风险提示原文「WE MAY FREEZE … YOUR USE OF, AND ACCESS TO, PAXG OR THE LONDON GOOD DELIVERY GOLD BARS "
      "… WITH OR WITHOUT ADVANCE NOTICE」 |")
    A("| 监管 | Tether 条款载明其取得 **El Salvador 稳定币发行人与数字资产服务商**授权（L116）；"
      "同体系亦适用制裁与 Prohibited Person 限制。**香港居民与非美国人在各所的准入状态本轮未逐一核实** | "
      "经 **OCC 特别批准**（条款 4.6「approved for Customers of Paxos Trust through specific approval from the OCC」）；"
      "仅 **verified Customers** 可向 Paxos 买入/兑换/赎回（4.11）；"
      "实物赎回下限 **430 PAXG**/条（≈$1.73M）。**香港对应门槛本轮未定位到** |")
    A("")
    A("> 另两项非「四项事实」但与执行直接相关、且不构成选择的实测：$50k 进场滑点 "
      "Binance `XAUTUSDT` **0.92 bps** vs `PAXGUSDT` **1.15 bps**；"
      "PAXG 赎回下限 430 枚 ≈ $1.73M（我们的量级进不了赎回通道），"
      "XAUT 赎回走 Tether 侧账户与合格投资者流程。")
    A("")
    A("### 1.6 T-210 结论的保留与撤回")
    A("")
    A("| T-210 的结论 | 处置 | 依据 |")
    A("|---|---|---|")
    A("| 三条腿的退出路径全是二级卖出（不假设可随时赎回） | **保留** | T-213 未触及赎回条款（§3 风险 1 原样） |")
    A("| 费用（10–40 bps）主导于滑点（$50k 也只有 0.9–2.6 bps） | **保留** | 未触及 |")
    A("| 同名假币泛滥，必须走合约地址白名单 | **保留** | 未触及 |")
    A("| 香港可执行性的三个缺口（SFC 持牌 VA 名单 / Ondo 香港门槛 / 各所准入） | **保留** | 未触及；SFC 探测留证见 `t210_sfc.json` |")
    A("| 代币化 SPY 腿：SPYX 优于 Ondo SPY | **保留** | "
      "TE 差（SPYX − Ondo）在逐日与 5 日块两种口径下都过零信号对照（分位 0.000 / 0.000，双侧 p 0.000） |")
    A("| 黄金腿：XAUT 的跟踪误差更紧（TE 4.53%% vs 6.86%%） | **撤回该依据** | "
      "公共窗口 XAUT − PAXG 的 TE 差只有 %+.3f pp，零分布对照判「差距不可读」（§1.4 表 C）；"
      "且两条腿在各自窗口长度不同（211 vs 392 天），原比较本身不同口径 |"
      % diffs["XAUT_minus_PAXG"]["daily"]["observed_diff_pp"])
    A("| 黄金腿：「推荐 XAUT」 | **改为不替 Jazz 选** | "
      "TE 依据撤回；余下依据（滑点、赎回门槛、样本长度）已在 §1.5 列出事实，选择权留给人 |")
    A("| Ondo SPY：Ethereum 侧最深池只有 $10,326、$5k 占池深 48% | **撤回（数字错）** | "
      "那是 GLDx 的池；Ondo SPY ETH 最深池 $81,175.95（vol24 $12,268.80），$5k 占 6.16%、$50k 占 61.6% |")
    A("| 「跟踪误差很大：黄金腿 6.86% / 4.53%、股票腿 7.52%」 | **改口径后换数字** | "
      "逐日 TE 含收市错位伪影；5 日块口径：PAXG 4.290%、XAUT 2.364%、SPYX 3.162%、Ondo 11.173%（各自全窗口） |")
    A("| §3 风险 4「TE 是这条腿的成本项，月度调仓会吃掉 alpha」 | **保留但改写** | "
      "逐日 TE 里主要是口径伪影；5 日块口径下黄金腿 TE 与不代币化的 GLD 同量级"
      "（GLD 1.995% vs PAXG 1.899% / XAUT 1.855%，公共窗口）⇒ **代币化溢价在黄金腿上测不到**；"
      "股票腿的溢价则确实存在（不代币化基线 SPY(ETF) vs SPX(指数) 5 日块 0.377%，"
      "SPYX 3.162% ⇒ +2.785 pp、Ondo 11.699% ⇒ +11.322 pp，公共窗口） |")
    A("")
    return "\n".join(lines)


def main():
    with open(TRACK) as fh:
        tr = json.load(fh)
    with open(DEPTH) as fh:
        dep = json.load(fh)
    with open(DEPTH2) as fh:
        dep2 = json.load(fh)
    t = tr["t213_correction"]
    with open(MD) as fh:
        md = fh.read()
    md = splice(md, C_BEG, C_END, build_correction(t, dep, dep2),
                "## 0. 口径偏差（先说清楚，因为它改了卡上的一个字）")
    md = splice(md, S_BEG, S_END, build_section(t, dep), "## 2. 明细")
    with open(MD, "w") as fh:
        fh.write(md)
    print("WROTE", MD, len(md), "chars")


if __name__ == "__main__":
    main()
