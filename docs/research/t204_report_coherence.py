#!/usr/bin/env python3
"""T-204 报告正文与交付状态对齐:闸门开、结果落定后,把正文里「闸门未开 / 本轮判不了 / 下一轮一条命令」
这三处状态性表述改成交付态;数字一律从 docs/research/t204_results.json 读,不手抄。

做法是**最小侵入的行/块替换**(不整节重写)——§3.1 的诊断表、§5 的协议问题、§1.1 的闸门历史都原样保留,
只在标题与状态句上改;改不动的锚点直接报错退出,不做半截修改。

只改 Mac 数据根下的报告文件;不改协议、不改统计量。
用法: python3 docs/research/t204_report_coherence.py [--check]
"""
import json
import os
import sys

REPO = "/Users/sbb/Projects/looloomi-ai-lane-c"
REPORT = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-204_oi_mcap_outofpanel.md"
RESULTS = os.path.join(REPO, "docs", "research", "t204_results.json")


def f6(x):
    return "—" if x is None else "%.*f" % (6, x)


def f4(x):
    return "—" if x is None else "%.*f" % (4, x)


def replace_line(txt, prefix, new_text):
    """把**唯一**含 prefix 的那一行换成 new_text(可含换行);保留该行原来的缩进。"""
    lines = txt.split("\n")
    hits = [i for i, ln in enumerate(lines) if prefix in ln]
    if len(hits) != 1:
        raise SystemExit("anchor %r hit %d times (want 1)" % (prefix, len(hits)))
    i = hits[0]
    indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
    body = new_text.split("\n")
    body = [body[0]] + [(indent + b if b else b) for b in body[1:]]
    lines[i:i + 1] = body
    return "\n".join(lines)


def replace_block(txt, first_prefix, last_prefix, new_text):
    """把从 first_prefix 行到 last_prefix 行(含)的整段换成 new_text。"""
    lines = txt.split("\n")
    starts = [i for i, ln in enumerate(lines) if first_prefix in ln]
    if len(starts) != 1:
        raise SystemExit("block start %r hit %d times" % (first_prefix, len(starts)))
    i0 = starts[0]
    ends = [i for i in range(i0, len(lines)) if last_prefix in lines[i]]
    if len(ends) != 1:
        raise SystemExit("block end %r hit %d times" % (last_prefix, len(ends)))
    i1 = ends[0]
    lines[i0:i1 + 1] = new_text.split("\n")
    return "\n".join(lines)


def build_verdict(main_s, raw_s, size_s, oop):
    if main_s["month_mean"] < 0 and main_s["month_t"] <= -2.0 \
            and main_s["halves"]["h1"]["month_mean"] < 0 and main_s["halves"]["h2"]["month_mean"] < 0:
        tag = "✅「OI/市值在规模之外有信息」"
        why = ("主统计量月均 %s < 0、月 t %s ≤ −2.0、两半 %s / %s 都 < 0 ⇒ 命中台账第一条。"
               % (f6(main_s["month_mean"]), f4(main_s["month_t"]),
                  f6(main_s["halves"]["h1"]["month_mean"]), f6(main_s["halves"]["h2"]["month_mean"])))
    elif raw_s["month_mean"] < 0 and raw_s["month_t"] <= -2.0:
        tag = "❌「是规模效应」(OI/市值不进 CIS)"
        why = ("原始 ρ 月均 %s / 月 t %s 显著为负,而偏相关不过(主:月均 %s / 月 t %s / 两半 %s / %s)"
               " ⇒ 命中台账第二条。"
               % (f6(raw_s["month_mean"]), f4(raw_s["month_t"]), f6(main_s["month_mean"]),
                  f4(main_s["month_t"]), f6(main_s["halves"]["h1"]["month_mean"]),
                  f6(main_s["halves"]["h2"]["month_mean"])))
    else:
        tag = "❌ 只展示(不写进 CIS v2 影子)"
        why = ("主统计量月均 %s / 月 t %s / 两半 %s / %s;原始 ρ 月均 %s / 月 t %s ⇒ 不命中台账前两条 ⇒ 第三条。"
               % (f6(main_s["month_mean"]), f4(main_s["month_t"]),
                  f6(main_s["halves"]["h1"]["month_mean"]), f6(main_s["halves"]["h2"]["month_mean"]),
                  f6(raw_s["month_mean"]), f4(raw_s["month_t"])))
    L = []
    L.append("**判定(照抄台账 S-689 三条,不改):%s** —— %s" % (tag, why))
    L.append("")
    L.append("| 统计量 | 月均 | 月 t | H1(< 2024-07) 月均 / 月 t | H2(≥ 2024-07) 月均 / 月 t |")
    L.append("|---|---|---|---|---|")
    for label, s in (("**主**:偏 Spearman ρ(OI/市值, 结果 \\| 规模)", main_s),
                     ("副:原始 ρ(OI/市值, 结果)", raw_s),
                     ("副:ρ(规模 ln(市值), 结果)", size_s)):
        h1, h2 = s["halves"]["h1"], s["halves"]["h2"]
        L.append("| %s | %s | %s | %s / %s | %s / %s |" % (
            label, f6(s["month_mean"]), f4(s["month_t"]),
            f6(h1["month_mean"]), f4(h1.get("month_t")), f6(h2["month_mean"]), f4(h2.get("month_t"))))
    L.append("")
    L.append("宇宙 %s 个 deriv 名字(2023-01 起、去面板 25 名)⇒ 留下 **%s** / 剔除 %s;行 %s、"
             "截面日(≥30 名)%s、月数 %s。"
             % (oop.get("deriv_symbols_since_2023"), oop.get("n_kept"), oop.get("n_dropped"),
                oop.get("rows_total"), main_s.get("n_days"), main_s.get("n_months")))
    L.append("逐月值(6 位小数)在 `docs/research/t204_results.json`;"
             "第二实现(pandas/numpy)逐月对数在 `docs/research/t204_verify_out_of_panel.json`。")
    return "\n".join(L), tag


def main():
    check_only = "--check" in sys.argv
    res = json.load(open(RESULTS))
    oop = res.get("out_of_panel") or {}
    if not oop.get("stats"):
        raise SystemExit("results 里没有 out_of_panel.stats ⇒ 不是交付态,不改报告")
    if res.get("status") in ("incomplete_gate_not_met", "pre_gate_diagnostic_NOT_DELIVERABLE",
                             "gate_open_use_full"):
        raise SystemExit("results status=%r ⇒ 不是交付态,不改报告" % res.get("status"))
    st = oop["stats"]
    main_s, raw_s, size_s = st["main"], st["raw"], st["size"]
    gate = res.get("gate", {})
    run_utc = res.get("run_utc", "")
    rows = gate.get("perp_cg_map_rows")
    pend = gate.get("pending")
    n_pend = len(pend) if isinstance(pend, list) else pend
    verdict, tag = build_verdict(main_s, raw_s, size_s, oop)

    if check_only:
        print("run_utc:", run_utc)
        print("gate rows:", rows, "pending:", n_pend, "gate_ok:", gate.get("gate_ok"))
        print("kept/dropped:", oop.get("n_kept"), oop.get("n_dropped"))
        print("main:", f6(main_s["month_mean"]), f4(main_s["month_t"]))
        print("verdict:", tag)
        return 0

    txt = open(REPORT).read()
    how = ("补数循环把 `perp_cg_map` 的 pending 行补完、pending 归零,闸门在 **2026-10-28 00:00 UTC 兜底之前**就满足"
           if n_pend == 0 else
           "到 **2026-10-28 00:00 UTC 兜底**、仍有 %s 行 pending 未补上(按台账「没补上的名字列名剔除」执行),闸门按台账满足" % n_pend)
    txt = replace_line(txt, "## 1. 开工条件", "## 1. 开工条件(卡上写死)与它什么时候满足")
    txt = replace_line(txt, "| 闸门 | **未满足**",
                       "| 闸门 | **满足** ⇒ 面板外主统计量已落(本卡交付物;闸门进度见 §1.1 与本节末) |")
    txt = replace_block(
        txt, "**本轮更新(2026-10-26 16:5x UTC)**", "② 新增量纲敏感性",
        "**闸门已开、结果已落(交付态)**:%s ⇒ 面板外主统计量按台账 S-689 跑完并落定。\n"
        "交付态的正式数字 = **开头表 + `docs/research/t204_results.json`**;§3.1 那档是闸门未开时的**诊断快照(存档)**,\n"
        "不是交付物。交付时的闸门状态:rows %s、pending %s、`gate_ok` %s(跑完时间 %s)。\n"
        "上一轮(闸门未开期)做的两件事仍然有效、仍然留在报告里:① 主脚本与台账 S-689 **逐条对齐**"
        "(改掉一处 mult 取法差异,见 §5.14);② 新增量纲敏感性(§3.1),并发现台账在 1000 前缀名字上差 1000 倍(§5.14)。"
        % (how, rows, n_pend, gate.get("gate_ok"), run_utc))
    txt = replace_line(
        txt, "## 3. 面板外宇宙",
        "## 3. 面板外宇宙:名字层干跑 + 闸门未开时的诊断(存档)\n\n"
        "> 本节是**闸门未开时的诊断快照(存档,非交付物)**;**交付态的正式数字在开头表与 "
        "`docs/research/t204_results.json`**。下面这段名字层干跑与台账事先写的抽查"
        "「AI、REI、COMBO、1000X、TON、CHESS 会被剔」逐一对上,是价格校验实现正确的证据,故原样保留。")
    txt = replace_block(txt, "**本轮判不了**", "(闸门未开时的诊断那一档落在第 1 条的**形状**里", verdict)
    txt = replace_line(txt, "## 6. 还差什么(下一轮一条命令)", "## 6. 交回后:要 Seth 拍板 / 下一步")
    txt = replace_block(
        txt, "1. 等 `perp_cg_map` 的行补完", "   coin_id(§5.12)",
        "1. **交回给 Seth 审**:卡已改 `in_review`,`notes` 写的是本轮实测值;分支 `lane-c/T-204` 已推。\n"
        "   开头表 = 交付态;§3 = 闸门未开时的存档快照(已标注,非交付物);§5/§8 = 协议问题(照执行、不改协议)。\n"
        "2. **要 Seth 拍板(不自己定)**:\n"
        "   ① **量纲口径**(§5.14)—— 台账 `r = oi_value_close / mcap` 对 1000 前缀名字差一个 `mult` 倍\n"
        "   (1000 枚币的名义持仓 ÷ 1 枚币的市值)。主统计量照台账一字不改;另附两档敏感性\n"
        "   (`nominal_mcap` 名义市值口径、`exclude_1000` 剔除这批名字)。**要不要把 `r` 改成名义市值口径写进台账下一版?**\n"
        "   ② **MKR 算不算「看过」**(§5.9)—— 面板外宇宙里 MKR→SKY 与面板的 SKY 是同一项目;\n"
        "   主统计量照台账保留它,敏感性 `sensitivity_exclude_seen_alias` 已备好。\n"
        "   ③ `too_many` 终态的 8 个名字(含 1000SHIB)剔不剔(§5.12)—— 现按台账「没补上的名字列名剔除」执行。\n"
        "3. **本卡不写进正式 CIS 标准**:台账第一条最多只允许写进 **CIS v2 影子**(规模中性化的 OI/市值排名、\n"
        "   前向记录、到期再判);正式标准不动。")
    txt = replace_line(
        txt, "**标死:探索性 —— 需另立预注册、在新数据上过零信号对照**;而且这一档闸门未开",
        "**标死:探索性 —— 需另立预注册、在新数据上过零信号对照**;这一条已在闸门开后的全量跑上复算"
        "(交付态数字见开头表;两实现逐月对数见 `docs/research/t204_verify_out_of_panel.json`)")
    with open(REPORT, "w") as f:
        f.write(txt)
    print("report coherence patched ->", REPORT)
    print("verdict:", tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
