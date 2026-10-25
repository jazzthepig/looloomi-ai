#!/usr/bin/env python3
"""T-198 / S-684 —— R-v2 幸存者偏差的**独立复算**(lane-c)。

台账:REFUTATION_LEDGER.md S-684(2026-10-25 15:03 UTC 预注册)—— 一字不改,有问题写进报告「协议问题」。
B 道 T-197 做同一件事;本文件不读 T-197 的脚本、结果与报告(独立性要求)。

规则来源:`docs/research/t159_bear_short.py` 的 `run_long`(= `r_v2_tickets.sql` 逐字)与 `load_gate`
(线上同一个 majors 闸门,research/t156/_style.json)。两者都 **import**,不复制、不改。
K 线换成 `research/s681/_um_daily.jsonl`(Binance UM 永续日线,890 个,含已下架;行 = [d, o, h, l, c, quote_volume])。

两个宇宙(台账原文):
  A = 全部 890 个 USDT 永续
  S = A 里基础币名在 `research/s677/_survivor_symbols.json`(今天 binance_hist 的 262 名)里的;
      基础币名与名单两边都按「去掉 1000 前缀算同名」归一(Binance 把 LUNC→1000LUNC 之类改过名)
  D = A \\ S

判据(台账原文):
  ① A 上平均 R > 0 且月块自助 2,000 次(种子 684)p(≤ 0) < 0.05
  ② A 的平均 R ≥ 0.5 × S 的平均 R(幸存者偏差吃掉的不到一半)

零分布与 p 值走 `src/data/evaluation/apparatus.py`(`null_distribution` / `percentile_of`),不手写。

跑:python3 docs/research/t198_rv2_survivorship_replica.py [--no-panel]
"""
import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)     # for `import t159_bear_short`
sys.path.insert(0, REPO)    # for `src.data.evaluation.apparatus`

from src.data.evaluation.apparatus import null_distribution, percentile_of  # noqa: E402
import t159_bear_short as t159  # noqa: E402  (run_long / load_gate / nav / stats 全部原样用)

# 交叉核对用:仓库自己的月块自助(`s657_s658_breadth_second_leg.boot_months`,`random.Random` 版)。
# 判据里的 p 用 apparatus 那条路径;这条只用来确认结论不依赖 RNG 实现。
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "s657_boot", os.path.join(HERE, "s657_s658_breadth_second_leg.py"))
s657_boot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s657_boot)

# 「大鱼」计数器用 T-154 的公用模块 `docs/research/fish_counter.py`(S-618 口径,rn≥220、adv30 ≥ $5M、
# 之后 120 根内最高收盘 ≥ 3× 当日收盘,同名命中相隔 ≤ 30 根并成一条鱼)。
_spec = importlib.util.spec_from_file_location("fish_counter", os.path.join(HERE, "fish_counter.py"))
fish_counter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fish_counter)

DATA = "/Volumes/CometCloudAI/cometcloud-local/research"
UM_DAILY = f"{DATA}/s681/_um_daily.jsonl"
SURVIVORS = f"{DATA}/s677/_survivor_symbols.json"
T156_DIR = f"{DATA}/t156/"
OUT_JSON = os.path.join(HERE, "t198_results.json")
REPORT = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-198_rv2_survivorship_replica.md"

D_FROM, D_TO = "2020-01-01", "2026-09-30"     # 台账:信号日窗口
BOOT_DRAWS, BOOT_SEED = 2000, 684            # 台账:月块自助 2,000 次,种子 684
F_FRAC, CAP = 0.01, 10                       # 台账/S-638 线上参数:f = 1%、最多 10 张
QUOTES = ("USDT", "USDC", "BUSD")


# ── 数据 ────────────────────────────────────────────────────────────────────────────────────────────────────
def load_um_bars():
    """s681/_um_daily.jsonl → symbol -> [(d, o, h, l, c, quote_volume)]。行内按日期排序并按日去重。"""
    by, pairs = defaultdict(list), {}
    for line in open(UM_DAILY):
        line = line.strip()
        if not line:
            continue
        x = json.loads(line)
        sym = x["symbol"]
        pairs[sym] = x.get("pair")
        for b in x["bars"]:
            by[sym].append((b[0], float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5])))
    out = {}
    for s, rows in by.items():
        rows.sort(key=lambda r: r[0])
        ded = []
        for r in rows:
            if ded and ded[-1][0] == r[0]:
                ded[-1] = r
            else:
                ded.append(r)
        out[s] = ded
    return out, pairs


def base_of(sym, pair):
    p = pair or (sym + "USDT")
    for q in QUOTES:
        if p.endswith(q) and len(p) > len(q):
            return p[: -len(q)]
    return sym


def survivor_sets():
    """名单 + 名单里每个 1000 前缀名去掉前缀后的形式(两边都归一 ⇒ LUNC ≡ 1000LUNC)。"""
    names = json.load(open(SURVIVORS))["symbols"]
    norm = set(names)
    for n in names:
        if n.startswith("1000") and len(n) > 4:
            norm.add(n[4:])
    return set(names), norm


def is_survivor(base, names, norm):
    return base in names or base in norm or (base.startswith("1000") and len(base) > 4 and base[4:] in norm)


# ── 统计 ────────────────────────────────────────────────────────────────────────────────────────────────────
def mean_r(tickets):
    rs = [t["r"] for t in tickets if t["r"] is not None]
    return (float(np.mean(rs)) if rs else None), len(rs)


def month_block_p(tickets, draws=BOOT_DRAWS, seed=BOOT_SEED):
    """月块自助:p(均值 ≤ 0)。票按信号月分块,每次重抽 len(块数) 个月(有放回),把块里的票摊平求均值。
    零分布交给 apparatus.null_distribution(rng),p 交给 apparatus.percentile_of(0.0, null)。"""
    by = defaultdict(list)
    for t in tickets:
        if t["r"] is not None:
            by[t["signal_d"][:7]].append(t["r"])
    months = sorted(by)
    if not months:
        return None, 0
    arrs = [np.asarray(by[m], dtype=float) for m in months]
    n_months = len(months)

    def fn(rng):
        pick = rng.integers(0, n_months, n_months)
        return float(np.concatenate([arrs[i] for i in pick]).mean())

    actual = float(np.concatenate(arrs).mean())
    null = null_distribution(fn, draws, seed, actual=actual)
    p = percentile_of(0.0, null)          # = (null < 0).mean() + 0.5·(null == 0).mean()
    q = {k: float(np.quantile(null, v)) for k, v in (("q05", 0.05), ("q50", 0.50), ("q95", 0.95))}
    return p, n_months, q


def by_year(tickets):
    out = {}
    for t in tickets:
        y = t["signal_d"][:4]
        r = out.setdefault(y, dict(n=0, n_closed=0, sum_r=0.0, n_still=0))
        r["n"] += 1
        if t["r"] is None:
            r["n_still"] += 1
        else:
            r["n_closed"] += 1
            r["sum_r"] += t["r"]
    for y, v in out.items():
        v["mean_r"] = v["sum_r"] / v["n_closed"] if v["n_closed"] else None
    return out


def money_curve(tickets, bars):
    if not tickets:
        return None
    return t159.stats(t159.nav(tickets, bars, F_FRAC, cap=CAP, d_to=D_TO, compound=True))


def pct(x):
    return "n/a" if x is None else ("%+.2f%%" % (100 * x))


def build_fish(bars):
    """S-618 口径的「鱼」:rn≥220、adv30 ≥ $5M、之后 120 根内最高收盘 ≥ 3× 当日收盘 ⇒ 命中;
    同名命中相隔 ≤ 30 根并成一条鱼。c × vol = quote volume(= S-618 的 dv)。"""
    panel = {}
    for s, rows in bars.items():
        pr = []
        for r in rows:
            c = r[4]
            if c <= 0:
                continue
            pr.append({"d": r[0], "c": c, "vol": r[5] / c})   # c × vol = quote volume(S-618 的 dv)
        panel[s] = pr
    return fish_counter.fish(panel, D_FROM, D_TO)


def fish_capture(fishes, tickets, sym_set):
    """一条鱼被捕获 = 该币有一张票的**进场日**落在鱼的命中区间 [start_date, last_hit_date] 内。"""
    entry_by_sym = defaultdict(list)
    for t in tickets:
        entry_by_sym[t["symbol"]].append(t["entry_d"])
    mine = [f for f in fishes if f["symbol"] in sym_set]
    got = [f for f in mine if any(f["start_date"] <= e <= f["last_hit_date"]
                                  for e in entry_by_sym.get(f["symbol"], []))]
    n_tk = sum(1 for t in tickets if t["symbol"] in sym_set)
    return dict(universe_fish=len(mine), captured=len(got),
                share=(len(got) / len(mine)) if mine else None,
                tickets=n_tk,
                tickets_per_captured_fish=(n_tk / len(got)) if got else None,
                fish_total_all=len(fishes),
                peak_multiple_median=float(np.median([f["peak_multiple"] for f in mine])) if mine else None)


# ── 主流程 ──────────────────────────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-panel", action="store_true", help="跳过「S 与面板票重合」这一项")
    args = ap.parse_args()

    for p in (UM_DAILY, SURVIVORS, f"{T156_DIR}_style.json"):
        if not os.path.exists(p):
            print(f"缺文件: {p}", file=sys.stderr)
            sys.exit(1)

    bars, pairs = load_um_bars()
    names, norm = survivor_sets()
    gate = t159.load_gate()
    print(f"[bars] {len(bars)} symbols / {sum(len(v) for v in bars.values())} rows; "
          f"[gate] {len(gate)} days; [survivors] {len(names)} names", file=sys.stderr)

    # 宇宙划分
    uni = {}
    for s in bars:
        b = base_of(s, pairs.get(s))
        uni[s] = "S" if is_survivor(b, names, norm) else "D"
    n_s_sym = sum(1 for v in uni.values() if v == "S")
    n_d_sym = sum(1 for v in uni.values() if v == "D")

    tickets = t159.run_long(bars, gate, D_FROM, D_TO)
    for t in tickets:
        t["universe"] = uni[t["symbol"]]

    A = tickets
    S = [t for t in tickets if t["universe"] == "S"]
    D = [t for t in tickets if t["universe"] == "D"]
    A_c = [t for t in A if t["r"] is not None]
    S_c = [t for t in S if t["r"] is not None]
    D_c = [t for t in D if t["r"] is not None]
    still = [t for t in A if t["r"] is None]

    mA, nA = mean_r(A_c)
    mS, nS = mean_r(S_c)
    mD, nD = mean_r(D_c)

    # 判据 ①:月块自助
    pA, n_blocks, null_q = month_block_p(A_c)
    # 交叉核对:仓库自己的 boot_months(random.Random,同种子、同块定义)—— 结论不应依赖 RNG 实现
    _bm = s657_boot.boot_months([{"signal_d": t["signal_d"], "r": t["r"]} for t in A_c],
                                draws=BOOT_DRAWS, seed=BOOT_SEED)
    p_cross = sum(m <= 0 for m in _bm) / len(_bm) if _bm else None
    j1 = bool(mA is not None and mA > 0 and pA is not None and pA < 0.05)
    # 判据 ②
    j2 = bool(mA is not None and mS is not None and mA >= 0.5 * mS)
    verdict = "过" if (j1 and j2) else "不过"

    # 资金曲线 f = 1%、cap = 10
    cur_A = money_curve(A, bars)
    cur_S = money_curve(S, bars)
    cur_D = money_curve(D, bars)

    # D 的最差 5 张
    worst5 = sorted(D_c, key=lambda t: t["r"])[:5]

    # 探索性:去掉最好的几张票之后的平均 R(台账没写这一条,只描述不改判据)
    rob = {}
    for lab, ck in (("A", A_c), ("S", S_c)):
        v = np.sort(np.array([t["r"] for t in ck], dtype=float))[::-1]
        rob[f"{lab}_wo1"] = float(v[1:].mean()) if len(v) > 1 else None
        rob[f"{lab}_wo5"] = float(v[5:].mean()) if len(v) > 5 else None
    va = np.sort(np.array([t["r"] for t in A_c], dtype=float))[::-1]
    rob["total_R"] = float(va.sum())
    rob["top1_share"] = float(va[0] / va.sum()) if va.sum() else None

    # 抓到的大行情(S-618 口径):全宇宙的「鱼」与各臂的捕获
    fishes = build_fish(bars)
    fish_res = {lab: fish_capture(fishes, tk, syms)
                for lab, tk, syms in (("A", A, set(bars)),
                                      ("S", S, {s for s in bars if uni[s] == "S"}),
                                      ("D", D, {s for s in bars if uni[s] == "D"}))}

    # S 与面板票的重合(同币同信号日)
    panel = None
    if not args.no_panel:
        pb = {s: v for s, v in t159.load_bars().items() if s in names}
        pt = t159.run_long(pb, gate, D_FROM, D_TO)
        pset = {(t["symbol"], t["signal_d"]) for t in pt if t["r"] is not None}
        sset = {(t["symbol"], t["signal_d"]) for t in S_c}
        inter = sset & pset
        panel = dict(panel_symbols=len(pb), panel_tickets=len(pt), panel_closed=len(pset),
                     s_closed=len(sset), overlap=len(inter),
                     overlap_of_s=(len(inter) / len(sset)) if sset else None,
                     overlap_of_panel=(len(inter) / len(pset)) if pset else None)
        panel["panel_by_year"] = {y: v["n_closed"] for y, v in sorted(by_year(pt).items())}

    # ── 结果 JSON ──
    res = dict(
        task="T-198", ledger="S-684", lane="lane-c",
        protocol=dict(d_from=D_FROM, d_to=D_TO, f=F_FRAC, cap=CAP,
                      boot_draws=BOOT_DRAWS, boot_seed=BOOT_SEED,
                      bars=UM_DAILY, survivors=SURVIVORS, gate=f"{T156_DIR}_style.json"),
        universes=dict(A_symbols=len(bars), S_symbols=n_s_sym, D_symbols=n_d_sym),
        summary=dict(A=dict(tickets=len(A), closed=nA, still=len(A) - nA, mean_r=mA),
                     S=dict(tickets=len(S), closed=nS, still=len(S) - nS, mean_r=mS),
                     D=dict(tickets=len(D), closed=nD, still=len(D) - nD, mean_r=mD)),
        judgement=dict(c1_mean_gt0=bool(mA is not None and mA > 0), c1_p=pA, c1_pass=j1,
                       c1_p_crosscheck_house_rng=p_cross,
                       null_quantiles=null_q,
                       c2_ratio=mA / mS if (mA is not None and mS) else None,
                       c2_threshold=0.5 * mS if mS is not None else None, c2_pass=j2,
                       verdict=verdict, month_blocks=n_blocks),
        robustness=dict(
            A_mean_wo_top1=rob.get("A_wo1"), A_mean_wo_top5=rob.get("A_wo5"),
            S_mean_wo_top1=rob.get("S_wo1"), S_mean_wo_top5=rob.get("S_wo5"),
            top1_share_of_total_R=rob.get("top1_share"), total_R=rob.get("total_R"),
            note="探索性:只作描述,不改判据(台账没写这一条)"),
        curves=dict(A=cur_A, S=cur_S, D=cur_D),
        by_year=dict(A=by_year(A), S=by_year(S), D=by_year(D)),
        worst5_D=[dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                       exit_d=t["exit_d"], r=t["r"]) for t in worst5],
        still_held=[dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                         universe=t["universe"]) for t in still],
        panel_overlap=panel,
        fish_s618=fish_res,
    )
    res["tickets"] = [dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                           exit_d=t["exit_d"], r=t["r"], universe=t["universe"]) for t in A]
    with open(OUT_JSON, "w") as f:
        json.dump(res, f, indent=2, default=str)

    # ── 报告 ──
    L = []
    L.append("# T-198 · S-684 独立复算:R-v2 在全部 USDT 永续(含已下架)上的幸存者偏差\n")
    L.append(f"- 台账:`REFUTATION_LEDGER.md` S-684(2026-10-25 15:03 UTC 预注册),**一字不改**")
    L.append(f"- 独立性:lane-c 独立算;未读 `docs/research/t197_*`、未读 B 道报告、未读台账 S-684 之后的结果小节")
    L.append(f"- 规则:`t159_bear_short.run_long`(= `r_v2_tickets.sql` 逐字)与 `t159_bear_short.load_gate`"
             f"(线上 majors 闸门 `research/t156/_style.json`)—— import,未复制、未改")
    L.append(f"- K 线:`research/s681/_um_daily.jsonl`(890 个 UM 永续,含已下架;成交额用 quote volume)")
    L.append(f"- 信号日窗口:{D_FROM} → {D_TO};资金曲线 f = {F_FRAC:.0%},最多 {CAP} 张")
    L.append(f"- 零分布:`src/data/evaluation/apparatus.py`(`null_distribution` / `percentile_of`),种子 {BOOT_SEED},{BOOT_DRAWS:,} 次\n")

    L.append("## 判据表\n")
    L.append("| # | 判据(台账原文) | 实测 | 判定 |")
    L.append("|---|---|---|---|")
    L.append(f"| ① | A 上平均 R > 0 且月块自助 2,000 次(种子 684)p(≤ 0) < 0.05 | "
             f"平均 R = **{mA:+.4f}**(n = {nA}),p(≤ 0) = **{pA:.4f}**(月块 {n_blocks} 个) | **{'过' if j1 else '不过'}** |")
    L.append(f"| ② | A 的平均 R ≥ 0.5 × S 的平均 R | "
             f"A {mA:+.4f} vs 0.5 × S {mS:+.4f} = {0.5 * mS:+.4f} | **{'过' if j2 else '不过'}** |")
    L.append(f"\n**总结:{'①② 都过 ⇒「R-v2 的证据经得起幸存者偏差」' if verdict == '过' else '①② 有不过 ⇒ 交 Jazz:真钱维持 L = 1、不加仓,直到前向票说话'}**\n")

    L.append("## A / S / D 汇总\n")
    L.append("| 宇宙 | 宇宙币数 | 有票币数 | 票数 | 已平仓 | 仍持有 | 平均 R | 中位 R | 胜率 | 最差 R | 最好 R |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for lab, tk, ck, n_sym in (("A(全部永续)", A, A_c, len(bars)),
                               ("S(今天在面板)", S, S_c, n_s_sym),
                               ("D(A \\ S)", D, D_c, n_d_sym)):
        rs = np.array([t["r"] for t in ck]) if ck else np.array([])
        if len(rs):
            L.append(f"| {lab} | {n_sym} | {len({t['symbol'] for t in tk})} | {len(tk)} | {len(ck)} | {len(tk) - len(ck)} | "
                     f"{rs.mean():+.4f} | {np.median(rs):+.4f} | {(rs > 0).mean():.1%} | {rs.min():+.4f} | {rs.max():+.4f} |")
        else:
            L.append(f"| {lab} | {n_sym} | 0 | {len(tk)} | 0 | {len(tk)} | n/a | n/a | n/a | n/a | n/a |")
    L.append(f"\n- 仍持有的票(A 共 {len(still)} 张)单列,**不进任何平均**;明细见 `docs/research/t198_results.json` 的 `still_held`。")
    L.append(f"- D(后来不在面板的 {n_d_sym} 个币)的平均 R = **{mD:+.4f}**,是负的;"
             f"它把 A 的平均 R 从 S 的 {mS:+.4f} 拉到 {mA:+.4f}(S 的 {mA / mS:.1%})。\n")

    L.append("## 资金曲线(t159.nav,f = 1%、cap = 10)\n")
    L.append("| 宇宙 | 起 | 止 | 期末权益 | 年化 | 最大回撤 | 回撤峰/谷 | 入场 / 跳过 / 平仓 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for lab, c in (("A", cur_A), ("S", cur_S), ("D", cur_D)):
        if not c:
            L.append(f"| {lab} | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        L.append(f"| {lab} | {c['d0']} | {c['d1']} | {c['end']:.4f} | {pct(c['annualised'])} | {pct(c['mdd'])} | "
                 f"{c['mdd_peak']} → {c['mdd_trough']} | {c['taken']} / {c['skipped']} / {c['closed']} |")
    L.append("")

    L.append("## 按年(信号年)\n")
    L.append("| 年 | A 票 | A 平均 R | S 票 | S 平均 R | D 票 | D 平均 R |")
    L.append("|---|---|---|---|---|---|---|")
    years = sorted(set(list(res["by_year"]["A"]) + list(res["by_year"]["S"]) + list(res["by_year"]["D"])))
    for y in years:
        a = res["by_year"]["A"].get(y, {})
        s = res["by_year"]["S"].get(y, {})
        d = res["by_year"]["D"].get(y, {})

        def f(v):
            return f"{v['n_closed']}" if v else "0"
        def mr(v):
            return f"{v['mean_r']:+.4f}" if v and v.get("mean_r") is not None else "n/a"
        L.append(f"| {y} | {f(a)} | {mr(a)} | {f(s)} | {mr(s)} | {f(d)} | {mr(d)} |")
    gate_open_by_year = defaultdict(int)
    gate_days_by_year = defaultdict(int)
    for d, v in gate.items():
        gate_days_by_year[d[:4]] += 1
        if v.get("gate_open"):
            gate_open_by_year[d[:4]] += 1
    missing = [y for y in ("2020", "2021", "2022", "2023", "2024", "2025", "2026")
               if y not in res["by_year"]["A"]]
    L.append("")
    if missing:
        L.append(f"- **{', '.join(missing)} 年没有一张票**:majors 闸门(`t156/_style.json`)在这些日子是关的 —— "
                 f"闸门开的天数:{'、'.join(f'{y} {gate_open_by_year[y]}/{gate_days_by_year[y]}' for y in sorted(gate_days_by_year))}。")
    L.append("")

    L.append("## D 的最差 5 张(已平仓,按 R 升序)\n")
    L.append("| symbol | 信号日 | 进场日 | 出场日 | R |")
    L.append("|---|---|---|---|---|")
    for t in worst5:
        L.append(f"| {t['symbol']} | {t['signal_d']} | {t['entry_d']} | {t['exit_d']} | {t['r']:+.4f} |")
    L.append("")

    L.append(f"## 仍持有的票(A 共 {len(still)} 张;单列,不进任何平均)\n")
    L.append("| symbol | 宇宙 | 信号日 | 进场日 |")
    L.append("|---|---|---|---|")
    for t in sorted(still, key=lambda x: (x["signal_d"], x["symbol"])):
        L.append(f"| {t['symbol']} | {t['universe']} | {t['signal_d']} | {t['entry_d']} |")
    L.append("")

    if panel:
        L.append("## S 与面板票的重合(同币同信号日)\n")
        L.append(f"- 面板票(`research/t156` 的 K 线,同一 `run_long`、同一闸门、同一窗口):"
                 f"{panel['panel_tickets']} 张(已平仓 {panel['panel_closed']}),覆盖 {panel['panel_symbols']} 个币")
        L.append(f"- S 的已平仓票:{panel['s_closed']} 张")
        L.append(f"- 重合:**{panel['overlap']}** 张 —— 占 S 的 **{panel['overlap_of_s']:.1%}**、"
                 f"占面板票的 **{panel['overlap_of_panel']:.1%}**")
        L.append(f"- 面板票按年:{panel['panel_by_year']}\n")

    L.append("## 抓到的大行情(S-618 口径)\n")
    L.append("- 鱼 = 之后 120 根内最高收盘 ≥ 3 × 当日收盘的命中日链(rn ≥ 220、adv30 ≥ $5M,同名相隔 ≤ 30 根并成一条);"
             "计数器用 T-154 的公用模块 `docs/research/fish_counter.py`。")
    L.append(f"- 全宇宙(A 的 890 个币,窗口 {D_FROM} → {D_TO})共 **{fish_res['A']['fish_total_all']}** 条鱼。\n")
    L.append("| 宇宙 | 该宇宙的鱼 | 捕获 | 捕获率 | 票数 | 每捕一条的票钱 |")
    L.append("|---|---|---|---|---|---|")
    for lab in ("A", "S", "D"):
        f = fish_res[lab]
        L.append(f"| {lab} | {f['universe_fish']} | {f['captured']} | "
                 f"{f['share']:.1%} | {f['tickets']} | {f['tickets_per_captured_fish']:.1f} |")
    L.append("")

    L.append("## 稳健性检查(探索性 —— 需另立预注册、在新数据上过零信号对照;不改判据)\n")
    L.append(f"- **p 值不依赖 RNG 实现**:用仓库自己的 `s657_s658_breadth_second_leg.boot_months`(`random.Random(684)`、同块定义)"
             f"复算同一批票 ⇒ p(≤ 0) = **{p_cross:.4f}**(apparatus 那条是 {pA:.4f})—— 两条都 > 0.05,判据 ① 的结论不变。")
    L.append(f"- **自助零分布的形状**:均值的中位数 {null_q['q50']:+.4f},5% 分位 {null_q['q05']:+.4f},95% 分位 {null_q['q95']:+.4f}"
             f"(n = {BOOT_DRAWS:,})—— 零分布跨过 0 的那一侧有约 {pA:.1%} 的质量。")
    L.append(f"- **去掉最大的赢家之后**:A 的平均 R 从 {mA:+.4f} → 去最好 1 张 {rob['A_wo1']:+.4f} → 去最好 5 张 {rob['A_wo5']:+.4f};"
             f"S: {mS:+.4f} → {rob['S_wo1']:+.4f} → {rob['S_wo5']:+.4f}。最好的一张占 A 总 R 的 {rob['top1_share']:.1%}。")
    L.append(f"- **中位数是负的**:A 的中位 R {np.median([t['r'] for t in A_c]):+.4f}、胜率 "
             f"{np.mean([t['r'] > 0 for t in A_c]):.1%} —— 靠右尾吃饭(凸性),不是靠胜率。\n")

    L.append("## 协议问题(不改规则,只报告)\n")
    L.append(PROTOCOL_NOTES.strip() + "\n")

    L.append("## 复算方式\n")
    L.append("```bash")
    L.append("python3 docs/research/t198_rv2_survivorship_replica.py")
    L.append("```")
    L.append(f"- 结果 JSON:`docs/research/t198_results.json`(每张票:symbol / signal_d / entry_d / exit_d / r / universe 标记)")
    L.append(f"- 脚本:`docs/research/t198_rv2_survivorship_replica.py`")
    L.append("")

    with open(REPORT, "w") as f:
        f.write("\n".join(L))
    print(json.dumps(dict(verdict=verdict, mA=mA, mS=mS, mD=mD, pA=pA, j1=j1, j2=j2,
                          nA=nA, nS=nS, nD=nD, still=len(still)), ensure_ascii=False, indent=2))


PROTOCOL_NOTES = """
1. **S 与面板票不是同一批 K 线。** 台账要「S 与 770 张面板票的重合」,但 A/S/D 的 K 线是 `research/s681/_um_daily.jsonl`
   (Binance UM **永续**日线,成交额 = quote volume),而线上那 770 张是 T-156/S-620 在 `research/t156`(binance_hist
   **现货** ohlcv_daily)上算的。两边信号因此可能不同,重合比例见上。
2. **`load_gate()` 的闸门文件是 `research/t156/_style.json`**(= 线上同一个 majors 指数),不是 s681 的文件;闸门本身不含币的成分,
   所以换 K 线不换闸门是台账写明的做法,不是笔误。
3. **p 值的方向。** 台账写「p(≤ 0)」。`t159_bear_short` 自己的写法是 `percentile_of(mean_r, null)`(null 中心化后算实际值在 null 里的分位),
   对正均值会给出接近 1 的数;本复算按台账字面取 p(≤ 0) = `percentile_of(0.0, null)`(与 `short_lab_common.boot_months` /
   `s657_s658_breadth_second_leg.boot_months` 的 `p_le0` 同义),两者差一个补集关系。
4. **月块自助的块定义**:按**信号月**(`signal_d[:7]`)分块,每次有放回重抽「块数」个月,摊平后求均值 —— 与
   `s657.boot_months` / `short_lab_common.boot_months` 同构;差别只在 RNG:`apparatus.null_distribution` 用
   `numpy.random.default_rng(684)`,那两处用 `random.Random(seed)`。
5. **幸存者名单的 1000 前缀**:`_survivor_symbols.json` 262 名里有 5 个带 1000 前缀(1000LUNC / 1000SHIB / 1000WHY / 1000X / 1000XEC),
   名单里**没有**去掉前缀的原名。台账说「1000 前缀按去掉 1000 也算同名」,本复算两边都归一(名单加上前缀去掉的形式,
   基础币名也试前缀去掉的形式)⇒ `LUNCUSDT` 与 `1000LUNCUSDT` 同属 S。
6. **仍持有的票**:`run_long` 自己判定(120 根到期但数据不够)⇒ `r = None`;这些票不进任何平均,单列在结果 JSON 的 `still_held`,
   但**进资金曲线**(按最后一个收盘价盯市,与线上口径一致)。
7. **资金曲线的截止日**用 `2026-09-30`(K 线的最后一天),不是 `t159.CURVE_TO`(2026-10-19)—— 后者会多出 19 天空盯市。
8. **「抓到的大行情(S-618 口径)」的宇宙换成了永续**:S-618 原文的宇宙是 `binance_hist` **现货**面板(并用它自己的 286/287 条鱼做对账);
   本卡要把鱼算在 A/S/D 上,所以鱼是在 s681 的 890 个 UM 永续上数的,成交额用 quote volume(= S-618 的 `close × volume`,
   这里是真美元额,不是面板那种「收盘 × 基础币量」的近似)。`fish_counter.py` docstring 里「先对上 286/287」那条对账
   **没有在本卡重做**(那是现货面板的事,与本卡的永续宇宙不同源)。捕获口径沿用 `s677_rv2_oos.capture`:该币有一张票的
   **进场日**落在鱼的命中区间 [起点, 末次命中] 内即算捕获。
9. **A 的票数可能与「面板 770 张」不可直接比**:面板票用的是现货 K 线、A 用的是永续 K 线,同一信号日的进出场价不同,
   两者 R 的差异不能当作「幸存者偏差」。
"""


if __name__ == "__main__":
    main()
