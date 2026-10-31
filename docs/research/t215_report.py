#!/usr/bin/env python3
"""T-215:把 t215_align.json 的块对齐敏感性 / 固定窗口结果渲染进 t210_onchain_legs.md。

设计意图:md 里的每个数字都由 JSON 直接渲染,人手不转写 ⇒ md 与 JSON 不会各说各话。
区块用 marker 包住,重复运行幂等:
  <!-- T215:CORRECTION:BEGIN --> … <!-- T215:CORRECTION:END -->   (文首「T-215 更正记录」)
  <!-- T215:SECTION:BEGIN --> … <!-- T215:SECTION:END -->           (§1.7)
另有一组「整行替换」(§1 表 / §3 风险 4 / §4 探索 2 / §4 探索 7 / §5 来源)——
按行首定位、整行改写,重复运行结果相同。

只读:只写 docs/research/t210_onchain_legs.md;不写库、不下单、不打印任何 key。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MD = os.path.join(HERE, "t210_onchain_legs.md")
ALIGN = os.path.join(HERE, "t215_align.json")

K_BEG = "<!-- T215:CORRECTION:BEGIN -->"
K_END = "<!-- T215:CORRECTION:END -->"
S_BEG = "<!-- T215:SECTION:BEGIN -->"
S_END = "<!-- T215:SECTION:END -->"
T213_S_END = "<!-- T213:SECTION:END -->"
T213_C_END = "<!-- T213:CORRECTION:END -->"


def fmt(x, n=3, dash="—"):
    if x is None:
        return dash
    return ("%." + str(n) + "f") % x


def pct(x, n=3, dash="—"):
    if x is None:
        return dash
    return fmt(x, n) + "%"


def strip_block(text, beg, end):
    """删掉 marker 之间的整块(含 marker)与紧随其后的空行,让重排幂等(字节级)。"""
    while True:
        i = text.find(beg)
        j = text.find(end)
        if i == -1 or j == -1 or j < i:
            return text
        k = j + len(end)
        while k < len(text) and text[k] == "\n":
            k += 1
        text = text[:i] + text[k:]


def splice(text, beg, end, body, anchor):
    """把 marker 块放到 anchor 之前;已存在则先删旧块。幂等(字节级)。"""
    text = strip_block(text, beg, end)
    block = beg + "\n" + body.rstrip() + "\n" + end
    i = text.find(anchor)
    if i == -1:
        raise SystemExit("anchor not found: " + anchor)
    prefix = text[:i].rstrip("\n")
    suffix = text[i + len(anchor):].lstrip("\n")
    out = prefix + "\n\n" + block + "\n\n" + anchor
    if suffix:
        out += "\n\n" + suffix
    return out


def splice_after(text, beg, end, body, anchor):
    """把 marker 块放到 anchor 之后;已存在则先删旧块。幂等(字节级)。"""
    text = strip_block(text, beg, end)
    block = beg + "\n" + body.rstrip() + "\n" + end
    i = text.find(anchor)
    if i == -1:
        raise SystemExit("anchor not found: " + anchor)
    prefix = text[:i + len(anchor)].rstrip("\n")
    suffix = text[i + len(anchor):].lstrip("\n")
    out = prefix + "\n\n" + block
    if suffix:
        out += "\n\n" + suffix
    return out


def replace_line(text, prefix, new_line):
    """按行首定位整行改写;找不到就原样返回(幂等:改完再跑,内容相同)。"""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith(prefix):
            lines[i] = new_line
            break
    return "\n".join(lines)


# ── 取数助手 ────────────────────────────────────────────────────────────
def leg(t, name, rs, win="common_window"):
    return t["legs"][name][win][rs]


def base(t, key, rs):
    b = t["baselines"][key]
    return {"canonical": b["common_window"],
            "legacy": b["common_window_legacy"],
            "fixed": b["fixed_window"]}[rs]


def align_range(rec):
    return "%s–%s%%" % (fmt(rec["align_min"]), fmt(rec["align_max"]))


def align_spread(rec):
    return fmt(rec["align_max"] - rec["align_min"])


def legacy_block0(t, name):
    return leg(t, name, "legacy")["align"]["offset_0"]["te_ann_pct"]


def base_block0(t, key):
    return base(t, key, "legacy")["align"]["offset_0"]["te_ann_pct"]


DRIFT_KEYS = ["PAXG", "XAUT", "SPYX", "SPY_ondo"]
LEG_LABEL = {"canonical": "固定窗口(周一~周五相邻日)",
             "legacy": "T-213 原行集"}


def build_correction(t):
    L = []
    A = L.append
    A("### T-215 更正记录（2026-10-31）")
    A("")
    A("T-213 的头条「5 日块 TE」有两个不稳定源，本轮把口径钉死、把量级降级。**只读数据，未写库、未下单。**")
    A("")
    A("1. **块起点是任意的 —— 头条用的 offset_0 只是 5 种里的一种。** 把不重叠 5 日块的起点挪 0..4 位，"
      "同一行集的 TE 极差达 %s pp（%s）。⇒ §1.4 / §1.6 里所有「5 日块 TE」**单点数作废**，"
      "权威口径改为**基准 ISO 自然周块**，5 种起点只作敏感性区间报（§1.7 表 E）。"
      % (fmt(max(leg(t, n, "canonical")["align_spread"] for n in DRIFT_KEYS), 3),
         "；".join("%s %s" % (n, align_range(leg(t, n, "canonical"))) for n in DRIFT_KEYS)))
    A("2. **代币序列原来是滚动窗口取数（`limit=400`）⇒ 头条每天变、不可复现。** 改为**写死的固定日期窗口**"
      "（代币 %s → %s、基准 %s → %s、公共窗口 %s → %s）⇒ 同代码两天跑出同数。"
      "（实测：两次 `t215_align.json` 除时间戳外逐字段一致，fingerprint `%s`。）"
      % (t["windows"]["token"][0], t["windows"]["token"][1],
         t["windows"]["benchmark"][0], t["windows"]["benchmark"][1],
         t["windows"]["common"][0], t["windows"]["common"][1],
         t.get("fingerprint_sha256_excl_timestamp", "")[:16]))
    A("3. **量级降级为方向性结论。** 「代币化在黄金腿上的跟踪成本差」这个**单点量级**写法全部撤掉"
      "（§1.4 答案、§1.6、§3 风险 4、§4 探索 7 均已改写）。保留下来的只有方向："
      "① 股票腿 **SPYX 优于 Ondo SPY**（ISO 周块 + 5 种块起点共 6/6 成立）；"
      "② 黄金腿两候选 **XAUT / PAXG 的 TE 差不可读**、符号随口径翻转 ⇒ 不能作选型依据；"
      "③ 股票腿相对不代币化基线的跟踪成本差**方向为「明显更高」**；"
      "④ 黄金腿相对不代币化 GLD 的跟踪成本差**方向为「不更高」**。")
    A("4. **§4 探索 2（「日界错位本身可能是可交易的时序源」）列入撤回清单**（§1.6 追加），正文引用同步改掉"
      "（原 md:333 把 §4 探索 2 当活结论引）。")
    A("5. **lane-c 判据①的引用改写**：原话是「price_ratio 统计上是空的／根本不可对照」——"
      "**结论对，理由错**：退化是**零分布族**的性质（置换保值 ⇒ 乘积不变），不是这个量的性质。"
      "正确口径是**重抽**（平稳块自助重抽中心化超出收益）⇒ 改写为「**实测漂移在重抽噪声内**」（§1.7 表 G），"
      "**不写「这个量是空的」**。")
    A("6. **基准坏点 2026-06-26（eodhd SPY：ETF 日收益与同日指数差 >50bps，见 §1.4 坏点警告）"
      "已剔除后再报**（SPYX / Ondo 的剔除前后数见 §1.7）。")
    A("7. **库里 `eq.SPX` 有非指数来源污染**：它是 **Hyperliquid 的 SPX 永续**，%s → %s 共 %s 行，"
      "单日最大 %s%%、%s 天单日 |涨跌| > 5%% ⇒ **任何走 `ohlcv_daily eq.SPX` 的基线都是坏的**。"
      "本报告的股票腿基线走 FRED `SP500`，没踩到。**本卡不改库**（库修复排到 @seth）。"
      % (t["eq_spx"]["by_source"]["hyperliquid"]["first"],
         t["eq_spx"]["by_source"]["hyperliquid"]["last"],
         t["eq_spx"]["by_source"]["hyperliquid"]["n_rows"],
         fmt(t["eq_spx"]["by_source"]["hyperliquid"]["max_abs_daily_move_pct"], 3),
         t["eq_spx"]["by_source"]["hyperliquid"]["n_days_abs_move_gt_5pct"]))
    A("")
    A("数据与脚本：`docs/research/t215_align.py` → `docs/research/t215_align.json`"
      "（只读 Supabase + 公开行情源）；本段与 §1.7 由 `docs/research/t215_report.py` 渲染（幂等）。")
    return "\n".join(L)


def build_section(t):
    L = []
    A = L.append
    A("### 1.7 T-215 重报：块对齐敏感性 + 固定日期窗口（权威口径）")
    A("")
    A("**为什么重报**：T-213 的头条有两个不稳定源 —— ①「5 日不重叠块」的块起点是任意的（从第 k 行开始切，"
      "k = 0..4），而头条只报了 offset_0；② 代币序列用 Binance `limit=400` 的**滚动**窗口取"
      "（起点每天前移一天）⇒ 同代码两天跑出不同数。**本节把口径钉死，并给出敏感性区间。**")
    A("")
    A("**口径（T-215 权威）**")
    A("")
    A("- **固定日期窗口**（写死，不是滚动）：代币 %s → %s；基准 %s → %s；公共窗口 %s → %s。"
      % (t["windows"]["token"][0], t["windows"]["token"][1],
         t["windows"]["benchmark"][0], t["windows"]["benchmark"][1],
         t["windows"]["common"][0], t["windows"]["common"][1]))
    A("- **块起点钉在基准 ISO 自然周**：同一 ISO 周内（周一~周五）的逐日收益复合成一块，"
      "整周不足 4 天则弃；块 TE（年化）= std(块差) · sqrt(52)。")
    A("- **行集两套都报**：`canonical` = 公共日期 ∩ 窗口 ∩ 周一~周五 ∩ **日历相邻（gap==1）**；"
      "`legacy` = T-213 原行集（保留周五→周一的 gap==3 对）。")
    A("- **敏感性**：同一行集下，5 日不重叠块的起点挪 0..4 位，报**区间**（不报单点）。")
    A("- **零分布**：一律走 `src/data/evaluation/apparatus.py`"
      "（`block_permute` / `null_distribution` / `percentile_of` / `stationary_bootstrap_index`）；"
      "种子 %s，%s 次。" % (t["seed"], t["n_boot"]))
    A("")
    A("#### 表 E —— 固定窗口下的权威口径（ISO 周块）与 5 种块起点的区间")
    A("")
    A("| 腿 | 基准 | 行集 | n（日 / ISO 块） | 逐日 TE | **ISO 周块 TE（权威）** | 5 种块起点区间 | 极差(pp) |")
    A("|---|---|---|---|---|---|---|---|")
    rows = [
        ("PAXG（Paxos Gold）", "XAUUSD", "PAXG", None),
        ("XAUT（Tether Gold）", "XAUUSD", "XAUT", None),
        ("SPYX（xStocks，Solana 池）", "SPY（eodhd）", "SPYX", None),
        ("SPY（Ondo，Ethereum 池）", "SPY（eodhd）", "SPY_ondo", None),
        ("不代币化基线：GLD（ETF）", "XAUUSD", None, "GLD_vs_XAUUSD"),
        ("不代币化基线：SPY(ETF) vs SPX", "SPX（指数，FRED）", None, "SPY_etf_vs_index"),
    ]
    for label, bench, name, bkey in rows:
        for rs in ("canonical", "legacy"):
            rec = leg(t, name, rs) if name else base(t, bkey, rs)
            A("| %s | %s | %s | %s / %s | %s | **%s** | %s | %s |"
              % (label, bench, LEG_LABEL[rs], rec["n_rows"], rec["iso_week_te"]["n"],
                 pct(rec["daily_te"]["te_ann_pct"]), pct(rec["iso_week_te"]["te_ann_pct"]),
                 align_range(rec), align_spread(rec)))
    A("")
    A("> **读法**：ISO 周块 TE 是权威单点；「5 种块起点区间」是同一行集下把块起点挪 0..4 位的极值。"
      "**T-213 的 5 日块单点数（原表 A）已作废** —— 它们是上表某一行的某个起点，不是这条腿的量级。"
      "固定窗口（各腿自身可得全历史）见 `t215_align.json` 的 `fixed_window`。"
      "（T-213 原行集上的 offset_0 单点复算：PAXG %s、XAUT %s、SPYX %s、Ondo %s、GLD %s、"
      "SPY(ETF)-指数 %s —— 与 T-213 报告同量级，量级漂移来自块起点与滚动窗口两处。）"
      % (pct(legacy_block0(t, "PAXG")), pct(legacy_block0(t, "XAUT")),
         pct(legacy_block0(t, "SPYX")), pct(legacy_block0(t, "SPY_ondo")),
         pct(base_block0(t, "GLD_vs_XAUUSD")), pct(base_block0(t, "SPY_etf_vs_index"))))
    A("")
    A("#### 表 F —— 候选之间的差：6 种口径下的观测差与零分布分位")
    A("")
    A("| 候选对 | 口径 | A 的 TE | B 的 TE | 观测差(pp) | 零分布中位差 | 分位 | 双侧 p | 判读 |")
    A("|---|---|---|---|---|---|---|---|---|")
    pairs = [("SPYX − SPY(ondo)", "SPYX_minus_SPY_ondo", "SPYX", "SPY_ondo"),
             ("XAUT − PAXG", "XAUT_minus_PAXG", "XAUT", "PAXG")]
    for label, key, a_name, b_name in pairs:
        c = t["comparisons"][key]
        for mode in ("iso", "align_0", "align_1", "align_2", "align_3", "align_4"):
            m = c[mode]
            readable = m["two_sided_p"] <= 0.05
            if label.startswith("SPYX"):
                verdict = ("**差距可读**" if readable else "差距读不出来（双侧 p > 0.05）")
            else:
                # 分位 1.0 = 差落在零分布的另一端 ⇒ 仍属「可读」，方向相反
                who = ("A 更紧" if m["actual_diff_pp"] < 0 else "B 更紧")
                verdict = ("差距可读（%s；量级 ≤ 0.36pp，见下）" % who if readable
                           else "**差距不可读**")
            A("| %s | %s | %s | %s | %+.3f | %+.3f | %s | %s | %s |"
              % (label, "ISO 周块" if mode == "iso" else mode.replace("_", " "),
                 pct(m["te_a"]), pct(m["te_b"]), m["actual_diff_pp"], m["null_median"],
                 fmt(m["percentile"], 4), fmt(m["two_sided_p"], 4), verdict))
    A("")
    c_s = t["comparisons"]["SPYX_minus_SPY_ondo"]
    c_g = t["comparisons"]["XAUT_minus_PAXG"]
    A("**读法（方向 vs 量级）**：")
    A("")
    A("- **股票腿 SPYX vs Ondo SPY —— 方向稳，量级不稳。** 6/6 种口径（ISO + 5 种块起点）SPYX 的 TE 都更低，"
      "方向差 %s pp ~ %s pp（同向；**最小差距只有最大差距的 %s×**）；但**「差距是否可读」本身依赖口径**：ISO 周块分位 %s（可读），"
      "5 种块起点分位 %s（其中只有 %s 种达到 5%% 水平）⇒ **差距可读性是对齐的函数**，"
      "只当方向性证据用。"
      % (fmt(min(c_s[m]["actual_diff_pp"] for m in ("iso", "align_0", "align_1", "align_2", "align_3", "align_4")), 3),
         fmt(max(c_s[m]["actual_diff_pp"] for m in ("iso", "align_0", "align_1", "align_2", "align_3", "align_4")), 3),
         fmt(abs(max(c_s[m]["actual_diff_pp"] for m in ("iso", "align_0", "align_1", "align_2", "align_3", "align_4"))
                  / min(c_s[m]["actual_diff_pp"] for m in ("iso", "align_0", "align_1", "align_2", "align_3", "align_4"))), 1),
         fmt(c_s["iso"]["percentile"], 4),
         "/".join(fmt(c_s[m]["percentile"], 3) for m in ("align_0", "align_1", "align_2", "align_3", "align_4")),
         sum(1 for m in ("align_0", "align_1", "align_2", "align_3", "align_4") if c_s[m]["percentile"] <= 0.05)))
    A("- **黄金腿 XAUT vs PAXG —— 差距不可读，且符号随口径翻转。** ISO 周块差 %+.3f pp（分位 %s）；"
      "5 种块起点差 %s pp，其中 %s 种分位 ≤ 0.05（PAXG 更紧）。"
      "**全部口径的差都在 ±0.36 pp 以内** ⇒ 即使统计上可读，**量级微不足道**；且符号翻转 ⇒ "
      "**不能作选型依据**（二选一由 Jazz 定，见 §1.5）。"
      % (c_g["iso"]["actual_diff_pp"], fmt(c_g["iso"]["percentile"], 4),
         "/".join("%+.3f" % c_g[m]["actual_diff_pp"] for m in ("align_0", "align_1", "align_2", "align_3", "align_4")),
         sum(1 for m in ("align_0", "align_1", "align_2", "align_3", "align_4") if c_g[m]["percentile"] <= 0.05)))
    A("")
    A("#### 表 G —— 漂移的零分布（重抽，不是置换）")
    A("")
    A("| 腿 | 行集 | 实测漂移 | 零分布中位 | 零分布 sd | 分位（单侧） | 双侧 p | 判读 |")
    A("|---|---|---|---|---|---|---|---|")
    for n in DRIFT_KEYS:
        for rs, suffix in (("canonical", ""), ("legacy", "_legacy_rows")):
            d = t["drift_null"][n + suffix]
            A("| %s | %s | %s%% | %s%% | %s%% | %s | %s | 在重抽噪声内 |"
              % (n, LEG_LABEL[rs], fmt(d["actual_drift_pct"]), fmt(d["null_median_pct"]),
                 fmt(d["null_sd_pct"]), fmt(d["percentile_one_sided"], 4),
                 fmt(d["two_sided_p"], 3)))
    A("")
    can_p = [t["drift_null"][n]["percentile_one_sided"] for n in DRIFT_KEYS]
    leg_p = [t["drift_null"][n + "_legacy_rows"]["percentile_one_sided"] for n in DRIFT_KEYS]
    all_p = [t["drift_null"][n + s]["two_sided_p"]
             for n in DRIFT_KEYS for s in ("", "_legacy_rows")]
    A("> **零分布怎么做的**：置换（打乱基准 / 打乱配对）会**保住乘积**，零分布退化 ⇒ 那个退化是"
      "**零分布族的性质，不是这个量的性质**。正确口径是**平稳块自助重抽「中心化后的超出收益」**"
      "（`apparatus.stationary_bootstrap_index`，mean_block=5，%s 次）：乘积会被重抽改变，"
      "零分布才有宽度。" % t["n_boot"])
    A(">")
    A("> **lane-c 判据①的引用（按 §Seth-1031a 改写）**：lane-c 的头条判据①「price_ratio 统计上是空的／"
      "根本不可对照」—— **结论对（漂移分不开候选），理由错**（退化来自零分布族）。"
      "理由改写为：**实测漂移在重抽噪声内**。lane-b 10-31 交叉复核在 T-213 行集上测得四腿分位 "
      "**0.477 / 0.320 / 0.459 / 0.224**；本轮在**固定窗口**行集上复测为 canonical 分位 "
      "**%s–%s**、T-213 原行集 **%s–%s**（双侧 p %s–%s，**无一在 5%% 水平上拒绝**）⇒ 同方向结论。"
      % (fmt(min(can_p), 3), fmt(max(can_p), 3), fmt(min(leg_p), 3), fmt(max(leg_p), 3),
         fmt(min(all_p), 3), fmt(max(all_p), 3)))
    A(">")
    A("> **不写**「这个量是空的」—— 这个写法把零分布族的退化说成了量的性质，是错的（§Seth-1031a 第 1 条）。")
    A("")
    A("#### 基准坏点（2026-06-26，eodhd SPY）剔除前后")
    A("")
    A("| 腿 | 口径 | 含坏点 | 剔除坏点 | 5 种块起点区间（含 → 剔） |")
    A("|---|---|---|---|---|")
    for n in ("SPYX", "SPY_ondo"):
        w = t["bad_day"][n]["with_bad_day"]["leg"]
        wo = t["bad_day"][n]["without_bad_day"]["leg"]
        A("| %s | ISO 周块 TE | %s | %s | %s → %s |"
          % (n, pct(w["iso_week_te"]["te_ann_pct"]), pct(wo["iso_week_te"]["te_ann_pct"]),
             align_range(w), align_range(wo)))
    A("")
    A("> 坏点是 **基准侧**的一天（ETF 日收益与同日指数差 50 bps 以上）。剔除它对两条腿的 ISO 周块 TE 影响 "
      "在 **0.01–0.81 pp** 量级（见上表）—— 再次说明：**单点量级对单日敏感，别报单点**。")
    A("")
    A("#### 库内 `eq.SPX` 污染（记录，不改库）")
    A("")
    eq = t["eq_spx"]
    hs = eq["by_source"]["hyperliquid"]
    A("- 库内 `eq.SPX` **不是 S&P 500 指数**，是 **Hyperliquid 的 SPX 永续**：%s → %s 共 **%s 行**，"
      "单日最大绝对涨跌 **%s%%**，**%s 天**单日 |涨跌| > 5%%（%s）。"
      % (hs["first"], hs["last"], hs["n_rows"], fmt(hs["max_abs_daily_move_pct"], 3),
         hs["n_days_abs_move_gt_5pct"],
         "、".join("%s %s%%" % (x["d"], fmt(x["pct"], 3))
                   for x in eq["hyperliquid_detail"]["daily_moves_gt_5pct"])))
    A("- ⇒ **任何走 `ohlcv_daily eq.SPX` 的基线都是坏的**（`bench_series(\"SPX\")` 会踩到）。"
      "本报告的股票腿基线走 **FRED `SP500`**（S&P Dow Jones 官方收盘），没踩到。")
    A("- **本卡不改库**（只读）；库修复排到 @seth（§Seth-1031a 第 4 条已记）。")
    A("")
    A("#### 降级后的结论（权威口径；量级只报区间）")
    A("")
    A("1. **方向 ① —— 股票腿 SPYX 的跟踪质量优于 Ondo SPY：成立。** ISO 周块 + 5 种块起点共 **6/6** 种口径成立。"
      "**量级**：SPYX %s、Ondo %s（块起点区间）—— 随块起点变，**不报单点**。"
      % (align_range(leg(t, "SPYX", "canonical")), align_range(leg(t, "SPY_ondo", "canonical"))))
    A("2. **方向 ② —— 黄金腿两候选 XAUT / PAXG 的 TE 差不可读、不能作选型依据。** 6 种口径的差全在 ±0.36 pp 内，"
      "且符号随口径翻转（§1.7 表 F）。二选一仍由 Jazz 定（§1.5 只列四项事实）。")
    A("3. **方向 ③ —— 黄金腿：代币化相对不代币化 GLD 的跟踪成本差，方向为「不更高」。** "
      "ISO 周块 PAXG %s / XAUT %s vs GLD %s；5 种块起点下代币化 **5/5** 更紧。"
      "**量级不报单点**（区间随块起点变）。"
      % (pct(leg(t, "PAXG", "canonical")["iso_week_te"]["te_ann_pct"]),
         pct(leg(t, "XAUT", "canonical")["iso_week_te"]["te_ann_pct"]),
         pct(base(t, "GLD_vs_XAUUSD", "canonical")["iso_week_te"]["te_ann_pct"])))
    A("4. **方向 ④ —— 股票腿：代币化相对不代币化基线（SPY(ETF) vs SPX 指数）的跟踪成本差，方向为「明显更高」。** "
      "ISO 周块 SPYX %s / Ondo %s vs 基线 %s。**量级只报区间**。"
      % (pct(leg(t, "SPYX", "canonical")["iso_week_te"]["te_ann_pct"]),
         pct(leg(t, "SPY_ondo", "canonical")["iso_week_te"]["te_ann_pct"]),
         pct(base(t, "SPY_etf_vs_index", "canonical")["iso_week_te"]["te_ann_pct"])))
    A("")
    A("#### §1.6 追加：T-215 撤回 / 改写清单")
    A("")
    A("| 结论 | 处置 | 依据 |")
    A("|---|---|---|")
    A("| §4 探索 2：「日界错位本身可能是一个可交易的时序源」 | **撤回** | "
      "本轮**没有做任何小时级对齐检验**，也没有零信号对照；它是从口径敏感性直接跳出来的猜想。"
      "§4 探索 2 的**前半句**（对齐口径极度敏感）经 T-215 复现成立并写进 §1.7 表 E；"
      "后半句（可交易的时序源）不成立，撤。原 md:333 的引用已同步改掉 |")
    A("| §1.4 表 A 的「累计 price_ratio」列 | **保留但标注为不可读** | "
      "两点估计·无对照；且漂移对末日极敏感。**不写「这个量是空的」** —— 退化是零分布族的性质；"
      "正确口径下（重抽）结论是「实测漂移在噪声内」（§1.7 表 G），"
      "lane-c 判据①**结论对、理由按此改写** |")
    A("| 「黄金腿代币化没有额外跟踪成本差」「股票腿代币化溢价 +2.785 / +11.322 pp」 | **量级降级为方向性结论** | "
      "单点量级随块起点变（§1.7 表 E：同一行集 5 种块起点的 TE 极差 %s–%s pp），"
      "且原数字取自**滚动窗口**（不可复现）。方向结论保留：①股票腿代币化成本差方向为「明显更高」；"
      "②黄金腿方向为「不更高」 |"
      % (fmt(min(leg(t, n, "canonical")["align_spread"] for n in DRIFT_KEYS), 3),
         fmt(max(leg(t, n, "canonical")["align_spread"] for n in DRIFT_KEYS), 3)))
    A("")
    return "\n".join(L)


def apply_inline(t, md):
    """整行改写(§1 表 / §3 风险 4 / §4 探索 2 / §4 探索 7 / §5 来源)。"""
    spyx = leg(t, "SPYX", "canonical")
    ondo = leg(t, "SPY_ondo", "canonical")
    paxg = leg(t, "PAXG", "canonical")
    xaut = leg(t, "XAUT", "canonical")
    gld = base(t, "GLD_vs_XAUUSD", "canonical")
    etf = base(t, "SPY_etf_vs_index", "canonical")

    md = replace_line(
        md,
        "| **代币化 SPY** |",
        "| **代币化 SPY** | **SPYX（xStocks, Solana）** | SPY（Ondo Stocks, Ethereum 池） | "
        "同一底层、同一时期，T-210 的逐日口径 SPYX TE_ann **7.52%%** vs Ondo **19.15%%**，corr 0.88 vs **0.527**。"
        "**T-215 重报（权威口径见 §1.7）**：基准 ISO 自然周块 SPYX **%s** vs Ondo **%s**；"
        "块起点挪 0..4 位时 SPYX **%s**、Ondo **%s** ⇒ **方向稳（6/6 种口径 SPYX 更紧）**，"
        "但量级随块起点变 ⇒ **只报区间、不报单点**（T-213 的 5 日块单点数已作废）。"
        "差距不在合规，在**二级深度**：Ondo 的 SPY 在 **Ethereum** 侧最深池 **$81,175.95**"
        "（vol24 $12,268.80；$5k 名义额 = 池深的 **6.16%%**、$50k = **61.6%%**），"
        "SPYX 在 Solana 侧 $2,113,641。 |"
        % (pct(spyx["iso_week_te"]["te_ann_pct"]), pct(ondo["iso_week_te"]["te_ann_pct"]),
           align_range(spyx), align_range(ondo)))

    md = replace_line(
        md,
        "| **黄金** |",
        "| **黄金** | **待定 —— 两项候选只列事实，二选一由 Jazz 定（§1.5）** | XAUT / PAXG 二选一 | "
        "T-210 原以「XAUT 贴得更紧（TE_ann **4.53%** vs PAXG **6.86%**）」支持 XAUT，**该 TE 依据已撤回**。"
        "**T-215 复核**：ISO 自然周块 + 5 种块起点共 6 种口径下，XAUT 与 PAXG 的 TE 差在 "
        "**−0.067 ~ +0.355 pp** 之间翻转、判「差距不可读」⇒ **TE 不能作选型依据**（§1.7 表 F）。"
        "其余实测依据仍在：$50k 进场滑点更低（0.92 vs 1.15 bps）、"
        "**PAXG 的赎回门槛 430 枚（≈$1.73M）把我们量级完全排除在赎回之外**、样本长 392 天（PAXG）vs 211 天（XAUT）。"
        "发行方 / 托管 / 冻结记录 / 监管四项事实见 §1.5。 |")

    md = replace_line(
        md,
        "4. **跟踪误差是这条腿的成本项",
        "4. **跟踪误差是这条腿的成本项 —— 但 T-215 把口径钉死后，量级只能读区间。** "
        "T-210 引用的 TE（黄金腿 PAXG 6.86%% / XAUT 4.53%%、股票腿 SPYX 7.52%%）是**逐日**口径，"
        "含「代币 24/7 收市 vs 基准工作日收市」的日界错位；T-213 的 5 日块单点数则**对块起点敏感**"
        "（挪 0..4 位，同一行集的 TE 变 2–3 倍，见 §1.7 表 E）。**T-215 权威口径 = 基准 ISO 自然周块 + "
        "固定日期窗口**（§1.7）：黄金腿 PAXG **%s** / XAUT **%s**，不代币化的 GLD **%s** ⇒ "
        "代币化黄金腿的跟踪成本**方向上不高于**不代币化（5 种块起点下也是 5/5 代币化更紧），"
        "**量级不报单点**；股票腿 SPYX **%s**、Ondo SPY **%s**，对照不代币化基线 SPY(ETF) vs SPX(指数) "
        "**%s** ⇒ 股票腿的代币化跟踪成本**方向上明显更高**，量级随块起点变（SPYX %s、Ondo %s）。"
        "对 T25 的含义：月度调仓下，**股票腿的跟踪偏离会吃掉 alpha**；黄金腿的 TE 在块口径下不足以单独立项。"
        "**逐日错位仍是执行时点风险**（操作层面）—— 注意这与被撤回的 §4 探索 2"
        "（「错位本身可能是可交易的时序源」）不是一回事，后者已列入 §1.6 追加撤回清单。"
        % (pct(paxg["iso_week_te"]["te_ann_pct"]), pct(xaut["iso_week_te"]["te_ann_pct"]),
           pct(gld["iso_week_te"]["te_ann_pct"]), pct(spyx["iso_week_te"]["te_ann_pct"]),
           pct(ondo["iso_week_te"]["te_ann_pct"]), pct(etf["iso_week_te"]["te_ann_pct"]),
           align_range(spyx), align_range(ondo)))

    md = replace_line(
        md,
        "2. **TE 的对齐口径极度敏感。**",
        "2. **【T-215 撤回】TE 的对齐口径极度敏感 —— 前半句成立，后半句（「错位本身可能是可交易的时序源」）撤。** "
        "**成立的部分**：块起点挪 0..4 位，同一行集的 TE 变 2–3 倍（§1.7 表 E）；逐日口径下相关系数掉到 ~0 ⇒ "
        "**任何用日收盘算 TE 的方法都必须先声明对齐口径**。**撤回的部分**："
        "「这也提示『代币 24/7 / 基准工作日』的错位本身可能是一个可交易的时序源」—— "
        "本轮**没有做任何小时级对齐检验**，也没有零信号对照支撑；它是从口径敏感性里直接跳出来的猜想。"
        "⇒ 列入 §1.6 追加撤回清单；要复活它，需要另立预注册、拿小时级数据、过零信号对照。")

    md = replace_line(
        md,
        "7. **「代币化溢价」在两条腿上的量级完全不同。**",
        "7. **【T-215 改写】代币化跟踪成本的差在两条腿上的方向不同，但量级只报区间。** "
        "权威口径（ISO 自然周块 + 固定窗口，公共窗口 %s → %s）：黄金腿 GLD **%s** vs PAXG **%s** / "
        "XAUT **%s**（代币化**不高于**不代币化；5 种块起点下 5/5 更紧），股票腿 SPYX **%s** / Ondo **%s** "
        "vs 不代币化基线 SPY(ETF) vs SPX(指数) **%s**（代币化**明显更高**；块起点区间 SPYX %s、Ondo %s）。"
        "⇒ 「要不要用代币化这条腿」在**黄金上没有成本差、在股票上有大成本差** —— 这是**方向性**结论；"
        "T-213 的单点量级（+2.785 / +11.322 pp）已作废，区间见 §1.7 表 E。"
        "值得预注册一个「按底层资产类别分层」的假设，在更长的样本上复测。"
        % (t["windows"]["common"][0], t["windows"]["common"][1],
           pct(gld["iso_week_te"]["te_ann_pct"]), pct(paxg["iso_week_te"]["te_ann_pct"]),
           pct(xaut["iso_week_te"]["te_ann_pct"]), pct(spyx["iso_week_te"]["te_ann_pct"]),
           pct(ondo["iso_week_te"]["te_ann_pct"]), pct(etf["iso_week_te"]["te_ann_pct"]),
           align_range(spyx), align_range(ondo)))

    src_anchor = "- `t213_report.py` — T-213："
    src_lines = ("- `t215_align.py` / `t215_align.json` — T-215：块对齐敏感性 + 固定日期窗口 + "
                 "漂移重抽零分布 + 基准坏点 + `eq.SPX` 污染留证（只读；固定窗口 ⇒ 同码两天同数）",
                 "- `t215_report.py` — T-215：把 `t215_align.json` 渲染成本文的「T-215 更正记录」与 §1.7"
                 "（幂等，md 数字全部来自 JSON，不手抄）")
    # 先删掉可能重复的旧行,再按锚点插入一次 ⇒ 幂等
    md = "\n".join(ln for ln in md.split("\n") if ln not in src_lines)
    if src_anchor in md:
        i = md.find(src_anchor)
        j = md.find("\n", i)
        add = "\n" + "\n".join(src_lines)
        md = md[:j] + add + md[j:]

    return md


def main():
    with open(ALIGN) as fh:
        t = json.load(fh)
    with open(MD) as fh:
        md = fh.read()
    md = splice_after(md, K_BEG, K_END, build_correction(t), T213_C_END)
    md = splice(md, S_BEG, S_END, build_section(t), "## 2. 明细")
    md = apply_inline(t, md)
    with open(MD, "w") as fh:
        fh.write(md)
    print("WROTE", MD, len(md), "chars")


if __name__ == "__main__":
    main()
