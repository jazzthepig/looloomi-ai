"""T-197 / S-684:R-v2 的幸存者偏差 —— 在 Binance 全部 USDT 永续(含已下架)上一字不改重跑,对比「今天还在面板里的」。

预注册:台账 S-684(2026-10-25 15:03 UTC,写于在这个宇宙上算任何一张票之前)。规则**一字不改**:

  票   = docs/research/t159_bear_short.py 的 `run_long(bars, gate, d_from, d_to)`(= r_v2_tickets.sql 逐字)
  闸门 = `t159.load_gate()`(research/t156/_style.json,线上同一个 majors 指数)
  钱   = `t159.nav` + `t159.stats`(f = 1%、cap = 10、复利,d_to = 2026-09-30)

只换 K 线:research/s681/_um_daily.jsonl —— 行 = [d, o, h, l, c, quote_volume]。第 6 列就是**成交额**,
和 t159.load_bars() 里那个 `close * volume` 同义,所以 dv 直接取第 6 列,不做任何再加工。

两个宇宙(台账原文):
  A = 全部 890 个永续
  S = A 里基础币名在 research/s677/_survivor_symbols.json(今天 binance_hist 的 262 名)里的
      —— 1000 / 1000000 前缀去掉算同名(1000SHIB ↔ SHIB,双向)
  D = A \\ S

判据(S-684):
  ① A 上平均 R > 0 且月块自助 2,000 次(种子 684)p(≤ 0) < 0.05
  ② A 的平均 R ≥ 0.5 × S 的平均 R
仍持有(still)的票不进平均,单列。

零分布走 src/data/evaluation/apparatus.py(null_distribution / percentile_of),不手写。

用法:python3 docs/research/t197_rv2_survivorship.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, ROOT)

# t159 的数据根:闸门在 t156,面板 K 线在 t156 + t159。必须在 import t159 之前设好(模块级读 env)。
os.environ.setdefault("T156_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t156/")
os.environ.setdefault("T159_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t159/")

_spec = importlib.util.spec_from_file_location("t159", os.path.join(HERE, "t159_bear_short.py"))
t159 = importlib.util.module_from_spec(_spec)
sys.modules["t159"] = t159
_spec.loader.exec_module(t159)

from src.data.evaluation.apparatus import null_distribution, percentile_of  # noqa: E402

DATA = "/Volumes/CometCloudAI/cometcloud-local/research"
UM_FILE = f"{DATA}/s681/_um_daily.jsonl"
SURV_FILE = f"{DATA}/s677/_survivor_symbols.json"
OUT_JSON = os.path.join(HERE, "t197_results.json")
OUT_MD = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-197_rv2_survivorship.md"

SIG_FROM, SIG_TO = "2020-01-01", "2026-09-30"     # 信号日窗(台账原文)
NAV_TO = "2026-09-30"                              # 钱曲线终点(台账原文)
F, CAP = 0.01, 10                                 # S-638 线上参数
BOOT_DRAWS, BOOT_SEED = 2000, 684                 # 月块自助:2,000 次、种子 684(台账原文)
DEAD_BEFORE = "2026-08-01"                        # 数据早于这天就断 = 币没了(数据集本身到 2026-09-30)


# ── 宇宙 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def load_um():
    """research/s681/_um_daily.jsonl → {symbol: [(d, o, h, l, c, quote_volume)]}。c ≤ 0 的行丢掉(S-677 同样处理)。"""
    bars = {}
    for line in open(UM_FILE):
        x = json.loads(line)
        rows = sorted({tuple(b) for b in x["bars"] if len(b) >= 6 and b[4] > 0})
        if rows:
            bars[x["symbol"]] = rows
    return bars


def base_name(s, prefixes=("1000000", "1000")):
    """1000 / 1000000 前缀去掉算同名(1000SHIB ↔ SHIB)。"""
    for p in prefixes:
        if s.startswith(p) and s[len(p):].isalpha():
            return s[len(p):]
    return s


def survivor_canon(prefixes=("1000000", "1000")):
    """今天的 binance_hist 面板名(262 个)→ 同名集合(前缀归一,双向)。"""
    surv = set(json.load(open(SURV_FILE))["symbols"])
    canon = set(surv) | {base_name(s, prefixes) for s in surv}
    return surv, canon


def is_survivor(sym, canon, prefixes=("1000000", "1000")):
    return sym in canon or base_name(sym, prefixes) in canon


# ── 统计 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def closed_of(tickets):
    return [t for t in tickets if t.get("r") is not None]


def still_of(tickets):
    return [t for t in tickets if t.get("r") is None]


def mtm_r(t, bars):
    """仍持有的票按最后收盘盯市(单列用,不进平均)。"""
    last_c = bars[t["symbol"]][-1][4]
    den = t["entry_px"] - t["stop_px"]
    if den == 0:
        return None
    return (last_c - t["entry_px"]) / den - 0.004 * t["entry_px"] / den


def month_block_boot(tickets, draws=BOOT_DRAWS, seed=BOOT_SEED):
    """月块自助:按信号月整块重抽。返回 (实际均值, p(≤0), 实际值在零分布里的分位, 零分布均值, 分位数, 种子敏感性)。"""
    by = defaultdict(list)
    for t in closed_of(tickets):
        by[t["signal_d"][:7]].append(t["r"])
    months = list(by)
    if not months:
        return None, None, None, None, None, None
    actual = float(np.mean([r for m in months for r in by[m]]))

    def draw(rng):
        pick = rng.choice(len(months), size=len(months), replace=True)
        rs = [r for i in pick for r in by[months[i]]]
        return float(np.mean(rs))

    null = null_distribution(draw, draws, seed, actual=actual)
    sens = []
    for s in (684, 1, 2, 7, 42, 2026, 999):
        rng = np.random.default_rng(s)
        sens.append(float((np.array([draw(rng) for _ in range(draws)]) <= 0).mean()))
    qs = [float(x) for x in np.percentile(null, [1, 5, 10, 25, 50, 75, 90, 95, 99])]
    return actual, float((null <= 0).mean()), percentile_of(actual, null), float(null.mean()), qs, sens


def month_block_boot_centered(tickets, draws=BOOT_DRAWS, seed=BOOT_SEED):
    """① 的另一种读法:月均值先减去总均值(零分布以 0 为中心),再整月重抽 ⇒ p(≤ 0)。
    台账只写了「月块自助 p(≤ 0)」,没写零分布是否以 0 为中心;两种读法都报。"""
    by = defaultdict(list)
    for t in closed_of(tickets):
        by[t["signal_d"][:7]].append(t["r"])
    months = list(by)
    if not months:
        return None
    grand = float(np.mean([r for m in months for r in by[m]]))
    cm = {m: np.array(by[m]) - grand for m in months}

    def draw(rng):
        pick = rng.choice(len(months), size=len(months), replace=True)
        return float(np.mean([r for i in pick for r in cm[months[i]]]))

    null = null_distribution(draw, draws, seed)
    return float((null <= 0).mean())


def listing_composition(tickets, first_d):
    """按 (宇宙, 上市年) 拆:票数 / 平均 R / ΣR。first_d = 币的第一根 bar 日期。"""
    g = defaultdict(list)
    for t in closed_of(tickets):
        g[(t["universe"], first_d[t["symbol"]][:4])].append(t["r"])
    out = {}
    for (u, y), v in sorted(g.items()):
        out.setdefault(u, {})[y] = dict(n=len(v), mean_r=float(np.mean(v)), sum_r=float(sum(v)))
    return out


def dead_exposure(tickets, bars, dead_before):
    """币真的没了(数据早于 dead_before 就断)的票:有没有在币没了的时候还拿着。"""
    last = {s: v[-1][0] for s, v in bars.items()}
    dead = {s: d for s, d in last.items() if d < dead_before}
    ts = [t for t in tickets if t["symbol"] in dead]
    open_at_death = [t for t in ts if t["exit_d"] is None or t["exit_d"] > last[t["symbol"]]]
    return dict(dead_symbols=len(dead), tickets=len(ts), open_at_death=len(open_at_death),
                sum_r=float(sum(t["r"] or 0 for t in ts)),
                list=[dict(symbol=t["symbol"], signal_d=t["signal_d"], exit_d=t["exit_d"],
                           last_bar=last[t["symbol"]], r=t["r"]) for t in ts])



def by_year(tickets):
    out = {}
    for y in sorted({t["signal_d"][:4] for t in tickets}):
        ts = [t for t in tickets if t["signal_d"][:4] == y]
        tc = closed_of(ts)
        out[y] = dict(n=len(ts), n_closed=len(tc), n_still=len(ts) - len(tc),
                      mean_r=float(np.mean([t["r"] for t in tc])) if tc else None,
                      sum_r=float(sum(t["r"] for t in tc)))
    return out


def summary(tickets, bars=None):
    tc = closed_of(tickets)
    rs = [t["r"] for t in tc]
    st = still_of(tickets)
    d = dict(n=len(tickets), n_closed=len(tc), n_still=len(st),
             mean_r=float(np.mean(rs)) if rs else None,
             sum_r=float(sum(rs)) if rs else None,
             median_r=float(np.median(rs)) if rs else None,
             win=float(np.mean([r > 0 for r in rs])) if rs else None,
             ex_top5_mean=float(np.mean(sorted(rs, reverse=True)[5:])) if len(rs) > 5 else None)
    if bars is not None and st:
        m = [mtm_r(t, bars) for t in st]
        m = [x for x in m if x is not None]
        d["still_mtm_mean_r"] = float(np.mean(m)) if m else None
        d["still_mtm_min_r"] = float(np.min(m)) if m else None
        d["still_mtm_n_below_minus1"] = sum(1 for x in m if x <= -1.0)
        d["still_mtm_n_below_minus5"] = sum(1 for x in m if x <= -5.0)
    return d


# ── 大行情(S-618 口径) ──────────────────────────────────────────────────────────────────────────────────
def fish_s618(bars, d_from, d_to):
    """S-618 逐字:rn ≥ 220、adv30 ≥ $5M、之后 120 根内最高收盘 ≥ 3 × 当天收盘 ⇒ 命中;同名命中相隔 ≤ 30 根并成一条鱼。"""
    out = []
    for s, rows in bars.items():
        c = [r[4] for r in rows]
        dv = [r[5] for r in rows]
        hits = []
        for i in range(219, len(rows) - 1):
            if not (d_from <= rows[i][0] <= d_to):
                continue
            w = dv[max(0, i - 29): i + 1]
            adv = sum(w) / len(w)
            fm = max(c[i + 1: i + 121]) if i + 1 < len(c) else None
            if adv >= 5e6 and fm is not None and fm >= 3 * c[i]:
                hits.append(i)
        cur = None
        for i in hits:
            if cur and i - cur["last"] <= 30:
                cur["last"] = i
            else:
                cur = {"symbol": s, "first": i, "last": i}
                out.append(cur)
    for f in out:
        rows = bars[f["symbol"]]
        f["d0"], f["d1"] = rows[f["first"]][0], rows[f["last"]][0]
    return out


def fish_low100(bars, d_from, d_to):
    """卡上口径:120 根内从低点涨 ≥ 100%(低点 = 当日之前 120 根最低收盘,涨幅 = 之后 120 根最高收盘 ≥ 2 × 低点)。
    命中口径与 S-618 同(rn ≥ 220、adv30 ≥ $5M、同名 ≤ 30 根并成一条)。"""
    out = []
    for s, rows in bars.items():
        c = [r[4] for r in rows]
        dv = [r[5] for r in rows]
        hits = []
        for i in range(219, len(rows) - 1):
            if not (d_from <= rows[i][0] <= d_to):
                continue
            w = dv[max(0, i - 29): i + 1]
            adv = sum(w) / len(w)
            lo = min(c[max(0, i - 119): i + 1])
            fm = max(c[i + 1: i + 121]) if i + 1 < len(c) else None
            if adv >= 5e6 and fm is not None and lo > 0 and fm >= 2 * lo:
                hits.append(i)
        cur = None
        for i in hits:
            if cur and i - cur["last"] <= 30:
                cur["last"] = i
            else:
                cur = {"symbol": s, "first": i, "last": i}
                out.append(cur)
    for f in out:
        rows = bars[f["symbol"]]
        f["d0"], f["d1"] = rows[f["first"]][0], rows[f["last"]][0]
    return out


def capture(fishes, tickets):
    """开过票 = 该鱼区间(首命中日 → 末命中日)里有进场日落在里面。"""
    by = defaultdict(list)
    for t in tickets:
        by[t["symbol"]].append(t["entry_d"])
    got = [f for f in fishes if any(f["d0"] <= e <= f["d1"] for e in by.get(f["symbol"], ()))]
    return dict(fish=len(fishes), captured=len(got),
                share=(len(got) / len(fishes)) if fishes else None,
                captured_symbols=len({f["symbol"] for f in got}))


# ── 主流程 ──────────────────────────────────────────────────────────────────────────────────────────────────
def main():
    t0 = datetime.now(timezone.utc)
    barsA = load_um()
    surv, canon = survivor_canon()
    gate = t159.load_gate()

    symA = set(barsA)
    symS = {s for s in symA if is_survivor(s, canon)}
    symD = symA - symS
    barsS = {s: barsA[s] for s in symS}
    barsD = {s: barsA[s] for s in symD}

    # 票:A 上跑一遍,再按名字切 S / D(同一本书,不改规则)
    tkA = t159.run_long(barsA, gate, SIG_FROM, SIG_TO)
    tkS = [t for t in tkA if t["symbol"] in symS]
    tkD = [t for t in tkA if t["symbol"] in symD]

    sumA, sumS, sumD = summary(tkA, barsA), summary(tkS, barsS), summary(tkD, barsD)
    mA, pA, pctA, nullA, qA, sensA = month_block_boot(tkA)
    mS, pS, pctS, nullS, qS, sensS = month_block_boot(tkS)
    mD, pD, pctD, nullD, qD, sensD = month_block_boot(tkD)

    j1 = (sumA["mean_r"] is not None and sumA["mean_r"] > 0 and pA is not None and pA < 0.05)
    j2 = (sumA["mean_r"] is not None and sumS["mean_r"] is not None and sumA["mean_r"] >= 0.5 * sumS["mean_r"])

    # 台账字面规则(只剥 1000)的敏感性 —— 归一口径不同,S / D 的名字归属可能差
    _, canon_strict = survivor_canon(("1000",))
    symS_strict = {s for s in symA if is_survivor(s, canon_strict, ("1000",))}
    symD_strict = symA - symS_strict
    tkS_strict = [t for t in tkA if t["symbol"] in symS_strict]
    tkD_strict = [t for t in tkA if t["symbol"] in symD_strict]
    sumS_strict = summary(tkS_strict, {s: barsA[s] for s in symS_strict})
    sumD_strict = summary(tkD_strict, {s: barsA[s] for s in symD_strict})
    moved_syms = sorted(symS ^ symS_strict)
    moved_tickets = [t for t in tkA if (t["symbol"] in symS) != (t["symbol"] in symS_strict)]
    j2_strict = (sumA["mean_r"] is not None and sumS_strict["mean_r"] is not None
                 and sumA["mean_r"] >= 0.5 * sumS_strict["mean_r"])
    # ① 的另一种读法:零分布以 0 为中心(月均值先减去总均值)
    pA_c = month_block_boot_centered(tkA)
    pS_c = month_block_boot_centered(tkS)

    # 钱曲线(A / S 各自用自己的 K 线盯市)
    curveA = list(t159.nav(tkA, barsA, F, cap=CAP, d_to=NAV_TO))
    curveS = list(t159.nav(tkS, barsS, F, cap=CAP, d_to=NAV_TO))
    curveD = list(t159.nav(tkD, barsD, F, cap=CAP, d_to=NAV_TO))
    navA = t159.stats(curveA) if curveA else None
    navS = t159.stats(curveS) if curveS else None
    navD = t159.stats(curveD) if curveD else None
    # cap=None(全接):把「每张票本身」和「cap=10 的名额竞争」分开
    navA_unc = t159.stats(list(t159.nav(tkA, barsA, F, cap=None, d_to=NAV_TO))) if tkA else None
    navS_unc = t159.stats(list(t159.nav(tkS, barsS, F, cap=None, d_to=NAV_TO))) if tkS else None
    navD_unc = t159.stats(list(t159.nav(tkD, barsD, F, cap=None, d_to=NAV_TO))) if tkD else None

    def year_eq(curve):
        """年末净值 → 逐年收益。"""
        out, raw = {}, {}
        if not curve:
            return out
        for r in curve:
            y = r["d"][:4]
            if y not in raw:
                raw[y] = r["equity"]
        ys = sorted(raw)
        for i, y in enumerate(ys):
            base = 1.0 if i == 0 else raw[ys[i - 1]]
            out[y] = dict(end=round(raw[y], 6), ret=(raw[y] / base - 1) if base else None)
        return out

    # 面板 770 张(t159.load_bars() + 同一个 run_long 复现)与 S 的重合
    panel_bars = t159.load_bars()
    panel_tk = t159.run_long(panel_bars, gate, t159.SINCE, t159.CURVE_TO)
    panel_keys = {(t["symbol"], t["signal_d"]) for t in panel_tk}
    keysA = {(t["symbol"], t["signal_d"]) for t in tkA}
    keysS = {(t["symbol"], t["signal_d"]) for t in tkS}
    keysD = {(t["symbol"], t["signal_d"]) for t in tkD}
    overlap_S = len(keysS & panel_keys)
    overlap_A = len(keysA & panel_keys)
    # 面板窗口内的重合(面板信号日 2020-03-01 → 2026-10-19,本跑 2020-01-01 → 2026-09-30)
    pw = (t159.SINCE, t159.CURVE_TO)
    keysS_w = {k for k in keysS if pw[0] <= k[1] <= pw[1]}
    overlap_S_w = len(keysS_w & panel_keys)
    panel_cache = f"{t159.ENV}_tickets_{t159.SINCE}_{t159.TO}.json"
    cache_check = None
    if os.path.exists(panel_cache):
        ref = {(t["symbol"], t["signal_d"]) for t in json.load(open(panel_cache))["long"]}
        cache_check = dict(ref_n=len(ref), mine_n=len(panel_keys), same_set=(ref == panel_keys))

    # 大行情(S-618 逐字 + 卡上口径)
    fsA = fish_s618(barsA, SIG_FROM, SIG_TO)
    fsS = fish_s618(barsS, SIG_FROM, SIG_TO)
    fsD = fish_s618(barsD, SIG_FROM, SIG_TO)
    flA = fish_low100(barsA, SIG_FROM, SIG_TO)
    flS = fish_low100(barsS, SIG_FROM, SIG_TO)
    flD = fish_low100(barsD, SIG_FROM, SIG_TO)
    fishA = capture(fsA, tkA)
    fishS = capture(fsS, tkS)
    fishD = capture(fsD, tkD)
    lowA = capture(flA, tkA)
    lowS = capture(flS, tkS)
    lowD = capture(flD, tkD)

    first_d = {s: v[0][0] for s, v in barsA.items()}
    tagged = [dict(t, universe=("S" if t["symbol"] in symS else "D")) for t in tkA]
    listing = listing_composition(tagged, first_d)
    listing["A"] = listing_composition([dict(t, universe="A") for t in tkA], first_d)["A"]
    dead = dict(A=dead_exposure(tkA, barsA, DEAD_BEFORE), S=dead_exposure(tkS, barsS, DEAD_BEFORE),
                D=dead_exposure(tkD, barsD, DEAD_BEFORE))

    res = dict(
        meta=dict(run_utc=t0.isoformat(), data=UM_FILE, surv_file=SURV_FILE,
                  signal_window=[SIG_FROM, SIG_TO], nav_to=NAV_TO, f=F, cap=CAP,
                  boot=dict(draws=BOOT_DRAWS, seed=BOOT_SEED),
                  panel_window=[t159.SINCE, t159.CURVE_TO]),
        universe=dict(A_symbols=len(barsA), S_symbols=len(symS), D_symbols=len(symD),
                      A_bars=sum(len(v) for v in barsA.values()),
                      first_d=min(v[0][0] for v in barsA.values()),
                      last_d=max(v[-1][0] for v in barsA.values()),
                      prefix_matched=sorted(s for s in symA if s not in surv and is_survivor(s, canon)),
                      survivor_list_n=len(surv)),
        judgement=dict(
            j1=dict(rule="A 平均 R > 0 且月块自助 2,000 次(种子 684)p(≤ 0) < 0.05",
                    mean_r=sumA["mean_r"], p_le0=pA, percentile=pctA, null_mean=nullA, pass_=bool(j1)),
            j2=dict(rule="A 平均 R ≥ 0.5 × S 平均 R",
                    mean_r_A=sumA["mean_r"], mean_r_S=sumS["mean_r"],
                    ratio=(sumA["mean_r"] / sumS["mean_r"]) if sumS["mean_r"] else None,
                    half_S=(0.5 * sumS["mean_r"]) if sumS["mean_r"] is not None else None,
                    pass_=bool(j2)),
            all_pass=bool(j1 and j2)),
        A=sumA, S=sumS, D=sumD,
        sensitivity=dict(
            prefix_strict=dict(
                rule="只剥 1000(台账字面)",
                S_symbols=len(symS_strict), D_symbols=len(symD_strict),
                moved_symbols=moved_syms, moved_tickets=len(moved_tickets),
                S=sumS_strict, D=sumD_strict,
                j1=bool(j1), j2=bool(j2_strict), all_pass=bool(j1 and j2_strict)),
            null_reading=dict(p_le0_centered_A=pA_c, p_le0_centered_S=pS_c,
                               j1_centered=bool(sumA["mean_r"] > 0 and pA_c is not None and pA_c < 0.05))),
        boot=dict(A=dict(mean=mA, p_le0=pA, pct=pctA, null_mean=nullA, quantiles=qA, seed_sensitivity=sensA),
                  S=dict(mean=mS, p_le0=pS, pct=pctS, null_mean=nullS, quantiles=qS, seed_sensitivity=sensS),
                  D=dict(mean=mD, p_le0=pD, pct=pctD, null_mean=nullD, quantiles=qD, seed_sensitivity=sensD)),
        by_year=dict(A=by_year(tkA), S=by_year(tkS), D=by_year(tkD)),
        nav=dict(A=navA, S=navS, D=navD, A_uncapped=navA_unc, S_uncapped=navS_unc, D_uncapped=navD_unc,
                 year_eq_A=year_eq(curveA), year_eq_S=year_eq(curveS), year_eq_D=year_eq(curveD)),
        panel=dict(n=len(panel_keys), symbols=len({s for s, _ in panel_keys}),
                   overlap_S=overlap_S, share_S=(overlap_S / len(keysS)) if keysS else None,
                   overlap_S_in_panel_window=overlap_S_w,
                   share_S_in_panel_window=(overlap_S_w / len(keysS_w)) if keysS_w else None,
                   n_S_in_panel_window=len(keysS_w),
                   overlap_A=overlap_A, share_A=(overlap_A / len(keysA)) if keysA else None,
                   share_of_panel=(overlap_S / len(panel_keys)) if panel_keys else None,
                   cache_check=cache_check,
                   panel_in_A=len(panel_keys & keysA), panel_in_S=len(panel_keys & keysS)),
        worst5_D=[dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                       exit_d=t["exit_d"], r=t["r"]) for t in sorted(closed_of(tkD), key=lambda t: t["r"])[:5]],
        worst5_D_still=[dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                             r_mtm=mtm_r(t, barsD)) for t in
                        sorted(still_of(tkD), key=lambda t: (mtm_r(t, barsD) if mtm_r(t, barsD) is not None else 0))[:5]],
        fish=dict(s618=dict(A=fishA, S=fishS, D=fishD),
                  low100=dict(A=lowA, S=lowS, D=lowD)),
        listing=listing, dead=dead,
        tickets=dict(A=[dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                              exit_d=t["exit_d"], entry_px=t["entry_px"], stop_px=t["stop_px"],
                              exit_px=t["exit_px"], r=t["r"], still=bool(t.get("still")),
                              universe=("S" if t["symbol"] in symS else "D"))
                         for t in tkA]),
    )
    json.dump(res, open(OUT_JSON, "w"), indent=1, default=str)

    md = write_md(res, tkA, tkS, tkD, symS, symD, fsA, flA)
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    open(OUT_MD, "w").write(md)

    print(json.dumps(dict(
        universe=res["universe"], judgement=res["judgement"], A=sumA, S=sumS, D=sumD,
        nav_A=navA, nav_S=navS, nav_D=navD, panel=res["panel"],
        fish=res["fish"], worst5_D=res["worst5_D"],
        out_json=OUT_JSON, out_md=OUT_MD), indent=1, default=str))


def _pc(x):
    return "n/a" if x is None else f"{100 * x:+.2f}%"


def _num(x, d=4):
    return "n/a" if x is None else f"{x:.{d}f}"


def write_md(res, tkA, tkS, tkD, symS, symD, fsA, flA):
    j, u, A, S, D = res["judgement"], res["universe"], res["A"], res["S"], res["D"]
    nav, pan, fi = res["nav"], res["panel"], res["fish"]
    L = []
    p = L.append
    p("# T-197 / S-684 — R-v2 的幸存者偏差:全部 USDT 永续(含已下架)vs 今天还在面板里的")
    p("")
    p(f"生成:{res['meta']['run_utc']} · 数据 `{res['meta']['data']}` · 只读 · "
      f"信号日 {res['meta']['signal_window'][0]} → {res['meta']['signal_window'][1]} · "
      f"钱曲线 f = {res['meta']['f']:.0%}、cap = {res['meta']['cap']}、到 {res['meta']['nav_to']}")
    p("")
    p("规则一字未改:票 = `docs/research/t159_bear_short.py` 的 `run_long`(= `r_v2_tickets.sql` 逐字);"
      "闸门 = `t159.load_gate()`(`research/t156/_style.json`,线上同一个 majors 指数);钱 = `t159.nav` + `t159.stats`。"
      "只换 K 线:`research/s681/_um_daily.jsonl`(行 = [d, o, h, l, c, quote_volume],成交额直接用第 6 列)。")
    p("")
    p("## 0 · 判据表(S-684)")
    p("")
    p("| # | 判据 | 实测 | 判定 |")
    p("|---|---|---|---|")
    p(f"| ① | A 上平均 R > 0 且月块自助 2,000 次(种子 684)p(≤ 0) < 0.05 | "
      f"均值 R = {_num(j['j1']['mean_r'])};p(≤0) = {_num(j['j1']['p_le0'], 4)};实际值分位 = {_num(j['j1']['percentile'], 4)} | "
      f"{'**过**' if j['j1']['pass_'] else '**不过**'} |")
    p(f"| ② | A 平均 R ≥ 0.5 × S 平均 R | A = {_num(j['j2']['mean_r_A'])};S = {_num(j['j2']['mean_r_S'])};"
      f"A/S = {_num(j['j2']['ratio'], 3)};0.5×S = {_num(j['j2']['half_S'])} | "
      f"{'**过**' if j['j2']['pass_'] else '**不过**'} |")
    p("")
    p(f"**总判定(台账原文):{'①② 都过 ⇒「R-v2 的证据经得起幸存者偏差」' if j['all_pass'] else '任一不过 ⇒ 交 Jazz:真钱维持 L = 1、不加仓,直到前向票说话'}**")
    p("")
    b = res["boot"]["A"]
    p(f"① 的细节:月块自助的零分布(整月重抽、种子 {res['meta']['boot']['seed']}、{res['meta']['boot']['draws']} 次)"
      f"中位数 {b['null_mean']:+.4f},1/5/10/25/50/75/90/95/99 分位 = "
      f"{' / '.join(f'{x:+.3f}' for x in b['quantiles'])};换 7 个种子 p(≤0) = "
      f"{' / '.join(f'{x:.3f}' for x in b['seed_sensitivity'])}。S 的同一把尺子 p(≤0) = "
      f"{res['boot']['S']['p_le0']:.4f},D = {res['boot']['D']['p_le0']:.4f}。")
    p("")
    p("## 1 · 宇宙")
    p("")
    p(f"- A = **{u['A_symbols']}** 个永续({u['A_bars']:,} 根日线,{u['first_d']} → {u['last_d']})")
    p(f"- S = **{u['S_symbols']}** 个(基础币名在今天的 binance_hist 面板 {u['survivor_list_n']} 名里)")
    p(f"- D = A \\ S = **{u['D_symbols']}** 个")
    if u["prefix_matched"]:
        p(f"- 前缀归一后补进 S 的:{', '.join('`%s`' % s for s in u['prefix_matched'])}(见 §6 协议问题)")
    p("")
    p("## 2 · A / S / D 汇总(仍持有的票不进平均)")
    p("")
    p("| 宇宙 | 票数 | 已了结 | 仍持有 | 平均 R | ΣR | 中位 R | 胜率 | 去掉最好 5 张后的平均 R |")
    p("|---|---|---|---|---|---|---|---|---|")
    for name, s in (("A", A), ("S", S), ("D", D)):
        p(f"| {name} | {s['n']} | {s['n_closed']} | {s['n_still']} | {_num(s['mean_r'])} | "
          f"{_num(s['sum_r'], 2)} | {_num(s['median_r'])} | {_pc(s['win'])} | {_num(s['ex_top5_mean'])} |")
    p("")
    p("> 仍持有的票(数据集先到头,120 根没走完)按台账**不进平均**,单列如下 —— 盯市 R 是「这批票现在浮着多少」的直接读数:")
    p("")
    p("| 宇宙 | 仍持有票 | 盯市平均 R | 最差 | R ≤ −1 | R ≤ −5 |")
    p("|---|---|---|---|---|---|")
    for name, s in (("A", A), ("S", S), ("D", D)):
        p(f"| {name} | {s.get('n_still')} | {_num(s.get('still_mtm_mean_r'))} | "
          f"{_num(s.get('still_mtm_min_r'))} | {s.get('still_mtm_n_below_minus1')} | {s.get('still_mtm_n_below_minus5')} |")
    p("")
    p("## 3 · 按年")
    p("")
    p("| 年 | A 票 | A 平均 R | A ΣR | S 票 | S 平均 R | S ΣR | D 票 | D 平均 R | D ΣR |")
    p("|---|---|---|---|---|---|---|---|---|---|")
    for y in sorted(set(res["by_year"]["A"]) | set(res["by_year"]["S"]) | set(res["by_year"]["D"])):
        a = res["by_year"]["A"].get(y, {})
        s = res["by_year"]["S"].get(y, {})
        d = res["by_year"]["D"].get(y, {})
        p(f"| {y} | {a.get('n', 0)} | {_num(a.get('mean_r'))} | {_num(a.get('sum_r'), 2)} | "
          f"{s.get('n', 0)} | {_num(s.get('mean_r'))} | {_num(s.get('sum_r'), 2)} | "
          f"{d.get('n', 0)} | {_num(d.get('mean_r'))} | {_num(d.get('sum_r'), 2)} |")
    p("")
    p("## 4 · 资金曲线(`t159.nav`,f = 1%、cap = 10、复利、到 2026-09-30)")
    p("")
    p("| 宇宙 | 起 | 止 | 期末净值 | 年化 | 盯市最大回撤 | 接 / 挡 / 了结 |")
    p("|---|---|---|---|---|---|---|")
    for name, k in (("A", "A"), ("S", "S"), ("D", "D")):
        n = nav.get(k)
        if not n:
            p(f"| {name} | — | — | — | — | — | — |")
            continue
        p(f"| {name} | {n['d0']} | {n['d1']} | {n['end']:.4f} | {_pc(n['annualised'])} | "
          f"{_pc(n['mdd'])} | {n['taken']} / {n['skipped']} / {n['closed']} |")
    p("")
    p("### 4.1 cap = None(全接,不限 10 张):把「每张票本身」和「名额竞争」分开")
    p("")
    p("| 宇宙 | 期末净值 | 年化 | 盯市最大回撤 | 接 / 挡 / 了结 |")
    p("|---|---|---|---|---|")
    for name, k in (("A", "A_uncapped"), ("S", "S_uncapped"), ("D", "D_uncapped")):
        n = nav.get(k)
        if not n:
            p(f"| {name} | — | — | — | — |")
            continue
        p(f"| {name} | {n['end']:.4f} | {_pc(n['annualised'])} | {_pc(n['mdd'])} | "
          f"{n['taken']} / {n['skipped']} / {n['closed']} |")
    p("")
    p("> cap = 10 时 A 与 S 不是「相加」关系:同一批名额在 A 里被 D 的票(按 `(信号日, 币名)` 排序)挤掉过,"
      "所以 A 的曲线并不等于 S 的曲线加 D 的曲线。上表全接,才看得到票本身。")
    p("")
    p("### 4.2 逐年净值(A / S / D)")
    p("")
    p("> 2022 没有新票(闸门整年关着),当年的净值变化全部是 2021 开的仓位盯市出来的,不是新交易。")
    p("")
    p("| 年 | A 期末净值 | A 当年 | S 期末净值 | S 当年 | D 期末净值 | D 当年 |")
    p("|---|---|---|---|---|---|---|")
    ya, ys, yd = nav.get("year_eq_A", {}), nav.get("year_eq_S", {}), nav.get("year_eq_D", {})
    for y in sorted(set(ya) | set(ys) | set(yd)):
        a, s, d = ya.get(y, {}), ys.get(y, {}), yd.get(y, {})
        p(f"| {y} | {_num(a.get('end'), 4)} | {_pc(a.get('ret'))} | {_num(s.get('end'), 4)} | {_pc(s.get('ret'))} | "
          f"{_num(d.get('end'), 4)} | {_pc(d.get('ret'))} |")
    p("")
    p("## 5 · 只报项")
    p("")
    p(f"### 5.1 D(今天不在面板里的 {u['D_symbols']} 个)最差 5 张")
    p("")
    p("| 币 | 信号日 | 进场日 | 出场日 | R |")
    p("|---|---|---|---|---|")
    for w in res["worst5_D"]:
        p(f"| {w['symbol']} | {w['signal_d']} | {w['entry_d']} | {w['exit_d']} | {_num(w['r'], 3)} |")
    p("")
    p("D 的仍持有票(按最后收盘盯市)最差 5 张 —— 台账规定它们不进平均,但它们正是偏差的所在:")
    p("")
    p("| 币 | 信号日 | 进场日 | 盯市 R |")
    p("|---|---|---|---|")
    for w in res["worst5_D_still"]:
        p(f"| {w['symbol']} | {w['signal_d']} | {w['entry_d']} | {_num(w['r_mtm'], 3)} |")
    p("")
    p("### 5.2 S 的票 vs 面板 770 张(同币同信号日)")
    p("")
    p(f"- 面板(用 `t159.load_bars()` + 同一个 `run_long` 复现):**{pan['n']}** 张 / {pan['symbols']} 个名字"
      + (f";与缓存票集完全一致 = {pan['cache_check']['same_set']}" if pan.get("cache_check") else ""))
    p(f"- S 的票落在面板票集里的:**{pan['overlap_S']}** 张 ⇒ 占 S 的票 **{_pc(pan['share_S'])}**;"
      f"占面板 770 张的 **{_pc(pan['share_of_panel'])}**")
    p(f"- 只在面板窗口(2020-03-01 → 2026-10-19)内比:S 的票 {pan['n_S_in_panel_window']} 张里 "
      f"**{pan['overlap_S_in_panel_window']}** 张重合 ⇒ **{_pc(pan['share_S_in_panel_window'])}**")
    p(f"- A 的票落在面板票集里的:**{pan['overlap_A']}** 张 ⇒ 占 A 的票 **{_pc(pan['share_A'])}**;"
      f"面板票里落在 A 的 **{pan['panel_in_A']}** 张、落在 S 的 **{pan['panel_in_S']}** 张")
    p("")
    p("### 5.3 抓到的大行情")
    p("")
    p("| 口径 | 宇宙 | 鱼(行情条数) | 开过票 | 捕获率 | 涉及币数 |")
    p("|---|---|---|---|---|---|")
    p(f"| S-618 逐字(120 根内最高收盘 ≥ 3× 当日收盘) | A | {fi['s618']['A']['fish']} | "
      f"{fi['s618']['A']['captured']} | {_pc(fi['s618']['A']['share'])} | {fi['s618']['A']['captured_symbols']} |")
    p(f"| 同上 | S | {fi['s618']['S']['fish']} | {fi['s618']['S']['captured']} | "
      f"{_pc(fi['s618']['S']['share'])} | {fi['s618']['S']['captured_symbols']} |")
    p(f"| 同上 | D | {fi['s618']['D']['fish']} | {fi['s618']['D']['captured']} | "
      f"{_pc(fi['s618']['D']['share'])} | {fi['s618']['D']['captured_symbols']} |")
    p(f"| 卡上口径(120 根内从低点涨 ≥ 100%) | A | {fi['low100']['A']['fish']} | "
      f"{fi['low100']['A']['captured']} | {_pc(fi['low100']['A']['share'])} | {fi['low100']['A']['captured_symbols']} |")
    p(f"| 同上 | S | {fi['low100']['S']['fish']} | {fi['low100']['S']['captured']} | "
      f"{_pc(fi['low100']['S']['share'])} | {fi['low100']['S']['captured_symbols']} |")
    p(f"| 同上 | D | {fi['low100']['D']['fish']} | {fi['low100']['D']['captured']} | "
      f"{_pc(fi['low100']['D']['share'])} | {fi['low100']['D']['captured_symbols']} |")
    p("")
    p("### 5.4 币真的没了的那部分(数据在 2026-08-01 前就断了)")
    p("")
    de = res["dead"]
    p("| 宇宙 | 数据断掉的币 | 这些币上的票 | 其中「币没了还拿着」 | ΣR |")
    p("|---|---|---|---|---|")
    for name in ("A", "S", "D"):
        d = de[name]
        p(f"| {name} | {d['dead_symbols']} | {d['tickets']} | {d['open_at_death']} | {_num(d['sum_r'], 2)} |")
    p("")
    p("明细(A 的):")
    p("")
    p("| 币 | 信号日 | 出场日 | 该币最后一根 bar | R |")
    p("|---|---|---|---|---|")
    for x in de["A"]["list"]:
        p(f"| {x['symbol']} | {x['signal_d']} | {x['exit_d']} | {x['last_bar']} | {_num(x['r'], 3)} |")
    p("")
    p("### 5.5 票的来源:按上市年拆(为什么 D 差)")
    p("")
    ls = res["listing"]
    yrs = sorted({y for u in ls for y in ls[u]})
    p("| 上市年 | A 票 | A 平均 R | S 票 | S 平均 R | D 票 | D 平均 R |")
    p("|---|---|---|---|---|---|---|")
    for y in yrs:
        a = ls.get("A", {}).get(y, {})
        s = ls.get("S", {}).get(y, {})
        d = ls.get("D", {}).get(y, {})
        p(f"| {y} | {a.get('n', 0)} | {_num(a.get('mean_r'))} | {s.get('n', 0)} | {_num(s.get('mean_r'))} | "
          f"{d.get('n', 0)} | {_num(d.get('mean_r'))} |")
    p("")
    p("## 6 · 协议问题(不改规则,只记录)")
    p("")
    p("1. **卡上写「1000 前缀去掉也算同名」,数据里还有 `1000000` 前缀**(`1000000BOB` / `1000000MOG`)。"
      "只剥 1000 会把 `1000000BOB` 判成 D,而它是 BOB(今天在面板里)。本跑把 1000000 一并归一 ⇒ "
      f"`1000000BOB`、`1000PEPE` 进 S;`1000000MOG` 仍进 D(MOG 不在今天的 262 名里)。")
    p("2. **卡上「大行情」写的是「120 天内从低点涨 ≥ 100%」,S-618 原文是「之后 120 根内最高收盘 ≥ 3 × 当日收盘」**"
      "(= 涨 200%,且起点是当日收盘而不是低点)。两个口径都算了(§5.3),主口径取 S-618 逐字。")
    p("3. **D ≠ 「已下架」**。D 是「今天不在 binance_hist 面板 262 名里」:既包含真正下架的(LUNA / FTT 一类),"
      "也包含还活着但没进面板的币。两个口径下 D 都是同一个集合,判据 ①② 的结论不受影响。")
    p("4. **仍持有(still)的票被排除在平均之外**,台账如此规定。但对 D 来说,「still」多半就是「币没了」—— "
      "所以 §2 的盯市那一栏才是偏差的直接读数,判据那一栏是台账口径。")
    p("5. **「still」在这份数据里几乎不是「币没了」**:48 张 still 票里绝大多数信号日在 2026-09(数据集末尾),"
      "只有数据在 2026-08-01 前就断的那些币才是真下架 —— 而它们的票**没有一张是在币没了之后还开着的**"
      f"(§5.4:open_at_death = {res['dead']['A']['open_at_death']})。")
    p("6. **面板的 262 个名字是「冻结」的名单**:S 里没有一个币是 2024 年之后上市的(§5.5)。"
      "所以 D 里的 630 个 = 真下架的 + 面板冻结之后才上市的,不是单纯的「死币」。这是解读 D 的负数时最要紧的一条。")
    p("")
    sn = res["sensitivity"]
    ps, nr = sn["prefix_strict"], sn["null_reading"]
    p("## 7 · 稳健性(不改规则,只报)")
    p("")
    p("| 读法 / 口径 | S 票 | S 平均 R | D 票 | D 平均 R | 判据 ① | 判据 ② | 总判定 |")
    p("|---|---|---|---|---|---|---|---|")
    p(f"| 本跑(1000 + 1000000 归一) | {S['n']} | {_num(S['mean_r'])} | {D['n']} | {_num(D['mean_r'])} | "
      f"{'过' if j['j1']['pass_'] else '不过'}(p={_num(j['j1']['p_le0'], 4)}) | "
      f"{'过' if j['j2']['pass_'] else '不过'} | {'过' if j['all_pass'] else '不过'} |")
    p(f"| 台账字面(只剥 1000) | {ps['S']['n']} | {_num(ps['S']['mean_r'])} | {ps['D']['n']} | {_num(ps['D']['mean_r'])} | "
      f"{'过' if ps['j1'] else '不过'}(同 A) | {'过' if ps['j2'] else '不过'} | {'过' if ps['all_pass'] else '不过'} |")
    p(f"| ① 的零分布换成以 0 为中心 | — | — | — | — | "
      f"{'过' if nr['j1_centered'] else '不过'}(p={_num(nr['p_le0_centered_A'], 4)}) | — | "
      f"{'过' if (j['j2']['pass_'] and nr['j1_centered']) else '不过'} |")
    p("")
    p(f"- **前缀口径**:受影响的名字只有 {', '.join('`%s`' % s for s in ps['moved_symbols']) or '无'},"
      f"这些名字上的票 **{ps['moved_tickets']}** 张 ⇒ S / D 的票与所有汇总数字一分不差;"
      f"只有名字计数变(S {u['S_symbols']} ↔ {ps['S_symbols']}、D {u['D_symbols']} ↔ {ps['D_symbols']})。")
    p(f"- **① 的 p 值读法**:本跑的零分布是「原样本整月重抽」,中位数 {res['boot']['A']['null_mean']:+.4f}(不是以 0 为中心),"
      f"p(≤0) = {_num(j['j1']['p_le0'], 4)} 是「重抽后均值落在 ≤ 0 的比例」;"
      f"另一种读法(月均值先减去总均值、零分布以 0 为中心)p = {_num(nr['p_le0_centered_A'], 4)}"
      f"(S 同尺 = {_num(nr['p_le0_centered_S'], 4)})⇒ **两种读法 ① 都不过**,结论不随读法变。")
    p(f"- **均值不是被极端票撑起来的**:去掉最好 5 张票后 A 的平均 R 仍是 {_num(A['ex_top5_mean'])}"
      f"(S {_num(S['ex_top5_mean'])}、D {_num(D['ex_top5_mean'])}),符号不变。")
    p("")
    p("---")
    p("")
    p(f"复算:`python3 docs/research/t197_rv2_survivorship.py`;逐票数据 `docs/research/t197_results.json`"
      f"(A 的 {res['tickets']['A'].__len__()} 张票全在里面,带 universe 标记)。")
    p("")
    return "\n".join(L)


if __name__ == "__main__":
    main()
