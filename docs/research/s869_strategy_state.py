"""S-869 / S-870:每个策略在哪个状态下是长处;今天是哪个状态就只用在这个状态下是长处的策略。

Jazz 2026-11-15:「所有策略重新打分和升级,然后形成组合。策略不需要全局高效,在特定矢量下 2–3 个月适用跑出超额就可以。
主要发挥优势,而不是补短板。」预期、判据与后果写在台账 S-869 / S-870(先登记,后计算)。只描述 + 一本纸面账的配方;不动真钱。

状态:`s866_cells.json` 的逐日四轴(盲复算过的那一份)。D 日收盘的状态配 D + 1 的收益。
  第一层 8 个半状态(R升 R降 L抽 L注 W坏 W好 T线下 T线上);第二层 4 个(T × L)。
策略:仓库里现成有逐日净值的 13 条 + 同目录下所有 `s869_extra_panel*.csv`(family,d,nav[,funded];各 lane 各写各的文件,互不覆盖)。
  占用本金的(核心、X1V、股、金)扣现金利率;叠加类(R-v2 票、坟场各族)是票 / 保证金的盈亏曲线,不扣(台账「S-869 更正(算前)」)。

判据两版:v1 = S-869 登记的五条(⑶ = 六成的段为正);**v2 = Jazz 11-15「可以不用高胜率,但是盈亏比需要高」(台账 S-871):
⑶ 换成 盈亏比 ≥ 2.0(为正各段的平均累计收益 ÷ 为负各段的平均累计亏损)。** 此后以 v2 为准;v1 留着是为了能复现 S-869 的结果。

用法(仓库根目录):
    python3 docs/research/s869_strategy_state.py --selftest [--rules v2]
    python3 docs/research/s869_strategy_state.py            # v1,写 docs/research/s869_results.json
    python3 docs/research/s869_strategy_state.py --rules v2 # v2,写 docs/research/s871_results.json
"""
from __future__ import annotations

import csv
import datetime as dt
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = "v2" if "v2" in sys.argv[1:] else "v1"
OUT = "docs/research/s871_results.json" if RULES == "v2" else "docs/research/s869_results.json"
GAP, MIN_EP, MIN_DAYS, MIN_RATIO, MIN_POS, MIN_PAYOFF = 5, 5, 120, 0.5, 0.6, 2.0


def payoff_ratio(ep: np.ndarray) -> float:
    """盈亏比:为正各段的平均累计收益 ÷ 为负各段的平均累计亏损的绝对值。没有为负的段 ⇒ 99(算过);没有为正的段 ⇒ 0。"""
    win, loss = ep[ep > 0], ep[ep < 0]
    if not len(win):
        return 0.0
    return 99.0 if not len(loss) else float(win.mean() / abs(loss.mean()))


def rule3(ep: np.ndarray) -> bool:
    return bool(payoff_ratio(ep) >= MIN_PAYOFF) if RULES == "v2" else bool(len(ep) and (ep > 0).mean() >= MIN_POS)
N_SHIFT, MIN_SHIFT, SEED, ANN = 2000, 180, 869, 365
WF_MIN_HISTORY, VOL_WIN, VOL_MIN_OBS, TARGET_VOL, MAX_SCALE, N_PLACEBO = 730, 90, 60, 0.10, 3.0, 200
# MAX_SCALE:13 条那一轮(S-869 / S-871 的结果)用的是 25,各条实际倍数中位 0.2 – 1.7、几乎不碰上限;补进套息之后 25 倍会把一条
# 波动极小的曲线放大成整本组合(台账「S-871 补」,算前改成 3)。要复现 13 条那一轮的数:把这里改回 25.0。
AXES = {"R": ("升", "降"), "L": ("抽", "注"), "W": ("坏", "好"), "T": ("线下", "线上")}
G2 = [f"T{t}·L{l}" for t in AXES["T"] for l in AXES["L"]]


# ── 读数 ─────────────────────────────────────────────────────────────────────────
def D(s) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def load_states() -> dict:
    daily = json.load(open(os.path.join(HERE, "s866_cells.json"), encoding="utf-8"))["daily"]
    return {D(k): {a: v[a] for a in AXES} for k, v in daily.items()}


def _daily_from_nav(nav: dict) -> dict:
    """净值 → 逐日收益;首末日之间缺的日子按净值不变(收益 0)。"""
    ds = sorted(nav)
    out, prev, d = {}, nav[ds[0]], ds[0] + dt.timedelta(days=1)
    while d <= ds[-1]:
        cur = nav.get(d, prev)
        out[d] = cur / prev - 1 if prev else 0.0
        prev, d = cur, d + dt.timedelta(days=1)
    return out


def load_panel() -> tuple[dict, dict]:
    """→ ({策略: {日: 超额收益}}, {策略: 说明})。"""
    panel, meta, cash = {}, {}, {}
    navs: dict[str, dict] = {"x1v": {}, "equity": {}, "gold": {}}
    for r in csv.DictReader(open(os.path.join(HERE, "t348_r4_legs.csv"))):
        d = D(r["d"])
        cash[d] = float(r["cash_daily_rate"] or 0.0)
        for name, col in (("x1v", "crypto_nav"), ("equity", "equity_close"), ("gold", "gold_close")):
            if r[col] not in ("", None):
                navs[name][d] = float(r[col])
    navs["core"] = {D(r["date"]): float(r["core_nav_1_cap_pit24"]) for r in csv.DictReader(open(os.path.join(HERE, "t342_daily.csv")))
                    if r["core_nav_1_cap_pit24"] not in ("", None)}
    for name, why in (("core", "① 核心:市值加权 PIT24,一直拿着"), ("x1v", "加密腿 + 200 日闸门(真钱规则 X1V)"),
                      ("equity", "股(ACWI)"), ("gold", "金(XAUUSD)")):
        panel[name] = {d: r - cash.get(d, 0.0) for d, r in _daily_from_nav(navs[name]).items()}
        meta[name] = {"what": why, "funded": True}
    rv2 = {D(r["d"]): float(r["nav"]) for r in csv.DictReader(open(os.path.join(HERE, "t348_r3_rv2_curve.csv")))}
    panel["rv2"], meta["rv2"] = _daily_from_nav(rv2), {"what": "R-v2 票(每票 0.5% / 上限 40% / 名额 14 的研究曲线)", "funded": False}
    fam: dict[str, dict] = {}
    for r in csv.DictReader(open(os.path.join(HERE, "t348_r3_families.csv"))):
        fam.setdefault(r["family"], {})[D(r["d"])] = float(r["nav"])
    funded_extra = set()
    for extra in sorted(glob.glob(os.path.join(HERE, "s869_extra_panel*.csv"))):
        for r in csv.DictReader(open(extra)):
            fam.setdefault(r["family"], {})[D(r["d"])] = float(r["nav"])
            if str(r.get("funded") or "").strip() in ("1", "true", "True"):
                funded_extra.add(r["family"])
    for name, nav in fam.items():
        rr = _daily_from_nav(nav)
        panel[name] = {d: v - cash.get(d, 0.0) for d, v in rr.items()} if name in funded_extra else rr
        meta[name] = {"what": "坟场 / 补充序列", "funded": name in funded_extra}
    return panel, meta


# ── 状态集合 ───────────────────────────────────────────────────────────────────────
def state_names() -> list[str]:
    return [a + v for a in AXES for v in AXES[a]] + G2


def state_of(lab: dict, name: str) -> bool:
    if "·" in name:
        t, l = name.split("·")
        return lab["T"] == t[1:] and lab["L"] == l[1:]
    return lab[name[0]] == name[1:]


# ── 一个「策略 × 状态」的全部读数 ─────────────────────────────────────────────────────────
def _episodes(ords: np.ndarray) -> list[np.ndarray]:
    """状态内的日序号(升序)→ 各段在 ords 里的下标;间隔 ≤ GAP 天并成一段。"""
    if not len(ords):
        return []
    cuts = np.where(np.diff(ords) > GAP)[0] + 1
    return np.split(np.arange(len(ords)), cuts)


def core_stats(ords: np.ndarray, r: np.ndarray, inside: np.ndarray) -> dict:
    """ords = 状态日 D 的序号(升序),r = D + 1 的超额收益,inside = D 是否在状态里。只算判「长处」要的那几个数(快,逐月重算与安慰剂都走它)。"""
    n_in = int(inside.sum())
    out = {"n_days": n_in, "n_episodes": 0, "strength": False, "avoid": False}
    if n_in == 0 or n_in == len(r):
        return out
    rin, rout = r[inside], r[~inside]
    eps = _episodes(ords[inside])
    ep_ret = np.array([float(np.prod(1 + rin[e]) - 1) for e in eps])
    vol = float(rin.std()) * np.sqrt(ANN)
    ann = float(rin.mean()) * ANN
    ratio = ann / vol if vol > 0 else 0.0
    pos = float((ep_ret > 0).mean()) if len(eps) else 0.0
    best = int(np.argmax(ep_ret)) if len(eps) else 0
    keep = np.ones(n_in, dtype=bool)
    if len(eps):
        keep[eps[best]] = False
    loo = float(rin[keep].mean()) * ANN if keep.any() else 0.0
    lift = (float(rin.mean()) - float(rout.mean())) * ANN
    enough = len(eps) >= MIN_EP and n_in >= MIN_DAYS
    out.update({"n_episodes": len(eps), "ann_in": round(ann, 4), "vol_in": round(vol, 4), "ratio_in": round(ratio, 3),
                "ann_out": round(float(rout.mean()) * ANN, 4), "lift": round(lift, 4), "pos_episodes": round(pos, 3),
                "worst_episode": round(float(ep_ret.min()), 4) if len(eps) else None, "ann_in_without_best_episode": round(loo, 4),
                "enough": bool(enough), "payoff": round(payoff_ratio(ep_ret), 2),
                "strength": bool(enough and ann > 0 and ratio >= MIN_RATIO and rule3(ep_ret) and loo > 0 and lift > 0),
                "avoid": bool(enough and ann < 0 and (1 - pos) >= MIN_POS)})
    return out


def shift_p(r: np.ndarray, inside: np.ndarray) -> dict:
    n = len(r)
    if inside.sum() < 5 or (~inside).sum() < 5 or n <= 2 * MIN_SHIFT + 1:
        return {"dev": None, "tail2": None}
    rng = np.random.default_rng(SEED)
    stat = lambda m: float(r[m].mean() - r[~m].mean())            # noqa: E731
    obs = stat(inside)
    sims = np.array([stat(np.roll(inside, int(k))) for k in rng.integers(MIN_SHIFT, n - MIN_SHIFT, N_SHIFT)])
    dev = float((np.abs(sims - sims.mean()) >= abs(obs - sims.mean())).mean())
    tail2 = min(1.0, 2.0 * min(float((sims <= obs).mean()), float((sims >= obs).mean())))
    return {"dev": round(dev, 4), "tail2": round(tail2, 4)}


def aligned(states: dict, rets: dict) -> tuple[np.ndarray, np.ndarray, list]:
    """状态日 D 与 D + 1 的收益对齐。→ (D 的序号, r[D + 1], D 的标签列表)。"""
    one = dt.timedelta(days=1)
    ds = [d for d in sorted(states) if d + one in rets]
    return np.array([d.toordinal() for d in ds]), np.array([rets[d + one] for d in ds]), [states[d] for d in ds]


def forward_from_starts(ords: np.ndarray, r: np.ndarray, inside: np.ndarray, h: int) -> dict:
    """每段第一天起 h 个自然日(不管中间状态变没变)的累计超额:中位、为正的占比。「2–3 个月适用」的那一问。"""
    pos = {int(o): i for i, o in enumerate(ords)}
    idx_in = np.where(inside)[0]
    out = []
    for e in _episodes(ords[inside]):
        i0 = int(idx_in[e[0]])
        end = pos.get(int(ords[i0]) + h - 1)
        if end is not None and end - i0 + 1 == h:
            out.append(float(np.prod(1 + r[i0:end + 1]) - 1))
    return {"n": len(out), "median": round(float(np.median(out)), 4) if out else None,
            "pos": round(float(np.mean([x > 0 for x in out])), 3) if out else None}


def fitness(states: dict, panel: dict) -> dict:
    table = {}
    for k, rets in panel.items():
        ords, r, labs = aligned(states, rets)
        if len(r) < MIN_DAYS:
            continue
        row = {"_all": {"n_days": int(len(r)), "ann": round(float(r.mean()) * ANN, 4),
                        "ratio": round(float(r.mean()) * ANN / (float(r.std()) * np.sqrt(ANN)), 3) if r.std() > 0 else 0.0,
                        "first": dt.date.fromordinal(int(ords[0])).isoformat(), "last": dt.date.fromordinal(int(ords[-1])).isoformat()}}
        for s in state_names():
            inside = np.array([state_of(lab, s) for lab in labs])
            c = core_stats(ords, r, inside)
            if c["n_days"] and c.get("ann_in") is not None:
                c["p_shift"] = shift_p(r, inside)
                c["fwd60"], c["fwd90"] = forward_from_starts(ords, r, inside, 60), forward_from_starts(ords, r, inside, 90)
            row[s] = c
        table[k] = row
    return table


# ── S-870:逐月向前走 ─────────────────────────────────────────────────────────────────
def _scaled(panel: dict) -> dict:
    """每条按滞后 VOL_WIN 天的实现波动缩放到同一目标(只用前一天及以前);不足 VOL_MIN_OBS 个观测或波动为 0 ⇒ 当天不可持有。"""
    tgt = TARGET_VOL / np.sqrt(ANN)
    out = {}
    for k, rets in panel.items():
        ds = sorted(rets)
        v = np.array([rets[d] for d in ds])
        sc = {}
        for i, d in enumerate(ds):
            w = v[max(0, i - VOL_WIN):i]
            if len(w) >= VOL_MIN_OBS and w.std() > 0:
                sc[d] = float(v[i] * min(MAX_SCALE, tgt / w.std()))
        out[k] = sc
    return out


T_LEVEL = ["T线下", "T线上"]
_QCACHE: dict = {}


def _quarters(k: str, ords: np.ndarray) -> np.ndarray:
    if k not in _QCACHE or len(_QCACHE[k]) != len(ords):
        _QCACHE[k] = np.array([dt.date.fromordinal(int(x)).year * 4 + (dt.date.fromordinal(int(x)).month - 1) // 3 for x in ords])
    return _QCACHE[k]


def _good(rr: np.ndarray, q: np.ndarray) -> bool:
    """「无条件好」:把全样本当成一个状态、自然季度当段,过 ⑴⑵⑶⑷(没有 ⑸ —— 没有状态外可比)。"""
    us = np.unique(q)
    ep = np.array([float(np.prod(1 + rr[q == u]) - 1) for u in us])
    ann, vol = float(rr.mean()) * ANN, float(rr.std()) * np.sqrt(ANN)
    if len(ep) < MIN_EP or ann <= 0 or vol <= 0 or ann / vol < MIN_RATIO or not rule3(ep):
        return False
    return bool(rr[q != us[int(np.argmax(ep))]].mean() > 0)


def month_tables(states: dict, panel: dict) -> dict:
    """每个月初 m:只用 D + 1 < m 的收益,算每条策略在 6 个状态(T × L 四个 + 线下 / 线上)下是不是长处、以及是不是「无条件好」。
    一次算完,四种组合共用(安慰剂每平移一次也只走这一遍)。"""
    days = sorted(states)
    months = [d for i, d in enumerate(days) if (i == 0 or d.month != days[i - 1].month) and (d - days[0]).days >= WF_MIN_HISTORY]
    names = G2 + T_LEVEL
    pre = {}
    for k, rets in panel.items():
        ords, r, labs = aligned(states, rets)
        pre[k] = (ords, r, {s: np.array([state_of(lab, s) for lab in labs]) for s in names}, _quarters(k, ords))
    out = {}
    for m in months:
        cut = m.toordinal()
        strength, good = {s: [] for s in names}, []
        for k, (ords, r, ins, q) in pre.items():
            n = int(np.searchsorted(ords, cut - 1))                 # D + 1 < m ⇒ D ≤ m − 2
            if n < MIN_DAYS:
                continue
            if _good(r[:n], q[:n]):
                good.append(k)
            for s in names:
                if core_stats(ords[:n], r[:n], ins[s][:n])["strength"]:
                    strength[s].append(k)
        out[m] = {"strength": strength, "good": good}
    return out


def walk(states: dict, tables: dict, scaled: dict, level: list[str], mode: str = "cond") -> dict:
    """level = 一组互斥的状态名。mode:cond = 只拿该状态的长处;plus = 状态长处 ∪ 无条件好的(更正 ②);uncond = B1,不看状态只拿无条件好的。"""
    one = dt.timedelta(days=1)
    months = sorted(tables)
    last_day = max(states)
    sel_at, held, port = {}, {s: {} for s in level}, {}
    for mi, m in enumerate(months):
        t = tables[m]
        picks = {s: (list(t["good"]) if mode == "uncond" else sorted(set(t["strength"][s]) | (set(t["good"]) if mode == "plus" else set()))) for s in level}
        sel_at[m.isoformat()] = picks
        end = months[mi + 1] if mi + 1 < len(months) else last_day + one + one
        d = m
        while d < end:
            lab = states.get(d - one)                                # 前一日收盘的状态
            if lab is not None:
                s = next(x for x in level if state_of(lab, x))
                rs = [scaled[k][d] for k in picks[s] if d in scaled[k]]
                port[d] = float(np.mean(rs)) if rs else 0.0
                for k in picks[s]:
                    if d in scaled[k]:
                        held[s][k] = held[s].get(k, 0) + 1
            d += one
    return {"series": port, "selection": sel_at, "held_days": held}


def perf(series: dict) -> dict:
    ds = sorted(series)
    if not ds:
        return {"n_days": 0}
    r = np.array([series[d] for d in ds])
    nav = np.cumprod(1 + r)
    peak = np.maximum.accumulate(nav)
    uw, cur = 0, 0
    for x, p in zip(nav, peak):
        cur = 0 if x >= p else cur + 1
        uw = max(uw, cur)
    roll20 = np.array([nav[i + 20] / nav[i] - 1 for i in range(len(nav) - 20)]) if len(nav) > 20 else np.array([0.0])
    vol = float(r.std()) * np.sqrt(ANN)
    return {"n_days": int(len(r)), "first": ds[0].isoformat(), "last": ds[-1].isoformat(),
            "ann": round(float(nav[-1] ** (ANN / len(r)) - 1), 4), "vol": round(vol, 4),
            "ratio": round(float(r.mean()) * ANN / vol, 3) if vol > 0 else 0.0,
            "longest_underwater_d": int(uw), "worst_20d": round(float(roll20.min()), 4), "share_in_cash": round(float((r == 0).mean()), 3)}


def shifted_states(states: dict, k: int) -> dict:
    ds = sorted(states)
    labs = [states[d] for d in ds]
    return {d: labs[(i - k) % len(ds)] for i, d in enumerate(ds)}


VARIANTS = (("cond_TxL", G2, "cond"), ("cond_T", T_LEVEL, "cond"), ("plus_TxL", G2, "plus"), ("plus_T", T_LEVEL, "plus"))


def portfolio(states: dict, panel: dict, n_placebo: int = N_PLACEBO) -> dict:
    scaled = _scaled(panel)
    tables = month_tables(states, panel)
    out = {}
    for name, level, mode in VARIANTS:
        w = walk(states, tables, scaled, level, mode)
        out[name] = {"perf": perf(w["series"]), "held_days": w["held_days"],
                     "last_selection": w["selection"][max(w["selection"])] if w["selection"] else {}}
    days = sorted(walk(states, tables, scaled, G2, "cond")["series"])
    b0 = {}
    for d in days:
        rs = [scaled[k][d] for k in panel if d in scaled[k]]
        b0[d] = float(np.mean(rs)) if rs else 0.0
    out["B0_all_equal_risk"] = {"perf": perf(b0)}
    b1 = walk(states, tables, scaled, G2, "uncond")
    out["B1_good_unconditional"] = {"perf": perf(b1["series"]), "last_selection": tables[max(tables)]["good"] if tables else []}
    rng = np.random.default_rng(SEED + 1)
    ks = [int(k) for k in rng.integers(MIN_SHIFT, len(states) - MIN_SHIFT, n_placebo)]
    acc = {name: {"ratio": [], "ann": []} for name, _, _ in VARIANTS}
    for k in ks:
        sh = shifted_states(states, k)
        tb = month_tables(sh, panel)
        for name, level, mode in VARIANTS:
            p = perf(walk(sh, tb, scaled, level, mode)["series"])
            acc[name]["ratio"].append(p.get("ratio", 0.0))
            acc[name]["ann"].append(p.get("ann", 0.0))
    for name, _, _ in VARIANTS:
        real, ratios, anns = out[name]["perf"], np.array(acc[name]["ratio"]), np.array(acc[name]["ann"])
        out[name]["placebo"] = {"n": int(n_placebo), "ratio_median": round(float(np.median(ratios)), 3), "ratio_q90": round(float(np.quantile(ratios, 0.9)), 3),
                                "percentile_of_real_ratio": round(float((ratios < real.get("ratio", 0.0)).mean()), 3),
                                "ann_median": round(float(np.median(anns)), 4),
                                "percentile_of_real_ann": round(float((anns < real.get("ann", 0.0)).mean()), 3)}
    last = max(states)
    out["today"] = {"state_day": last.isoformat(), "labels": states[last], "TxL": next(x for x in G2 if state_of(states[last], x))}
    return out


def synthetic() -> tuple[dict, dict]:
    rng = np.random.default_rng(869)
    days = [dt.date(2019, 1, 1) + dt.timedelta(days=i) for i in range(2600)]
    def regime(p):                                                          # 持续几十天的二元状态
        x, cur = [], 0
        for _ in days:
            cur = 1 - cur if rng.random() < p else cur
            x.append(cur)
        return x
    t, l, rr, w = regime(1 / 70), regime(1 / 60), regime(1 / 90), regime(1 / 50)
    states = {d: {"T": AXES["T"][t[i]], "L": AXES["L"][l[i]], "R": AXES["R"][rr[i]], "W": AXES["W"][w[i]]} for i, d in enumerate(days)}
    panel = {k: {} for k in ("bear_only", "bull_only", "noise", "always_up", "always_down")}
    for i, d in enumerate(days[1:], start=1):
        bear = t[i - 1] == 0                                                # AXES["T"][0] = 线下;用的是前一日的状态
        panel["bear_only"][d] = float(rng.normal(0.004 if bear else -0.001, 0.02))
        panel["bull_only"][d] = float(rng.normal(-0.001 if bear else 0.004, 0.02))
        panel["noise"][d] = float(rng.normal(0.0, 0.02))
        panel["always_up"][d] = float(rng.normal(0.0015, 0.01))
        panel["always_down"][d] = float(rng.normal(-0.003, 0.02))
    return states, panel


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        states, panel = synthetic()
        meta = {k: {"what": "合成", "funded": False} for k in panel}
    else:
        states = load_states()
        panel, meta = load_panel()
    table = fitness(states, panel)
    strengths = {s: sorted(k for k, row in table.items() if row.get(s, {}).get("strength")) for s in state_names()}
    avoid = {s: sorted(k for k, row in table.items() if row.get(s, {}).get("avoid")) for s in state_names()}
    both_p = [(k, s) for k, row in table.items() for s in state_names()
              if (row.get(s, {}).get("p_shift") or {}).get("dev") is not None and max(row[s]["p_shift"]["dev"], row[s]["p_shift"]["tail2"]) < 0.05]
    port = portfolio(states, panel, n_placebo=(20 if selftest else N_PLACEBO))
    out = {"strategies": {k: {**meta.get(k, {}), **table[k]["_all"]} for k in table}, "table": table, "strengths": strengths, "avoid": avoid,
           "both_p_below_0.05": both_p, "n_cells_judged": sum(1 for row in table.values() for s in state_names() if row.get(s, {}).get("enough")),
           "portfolio": port,
           "rules": {"version": RULES, "min_payoff": MIN_PAYOFF, "min_episodes": MIN_EP, "min_days": MIN_DAYS, "min_ratio": MIN_RATIO, "min_pos_episodes": MIN_POS, "gap_merge_d": GAP}}
    print("STRATEGIES", json.dumps(out["strategies"], ensure_ascii=False), flush=True)
    for s in state_names():
        print("STATE", s, "| 长处:", ",".join(strengths[s]) or "-", "| 避开:", ",".join(avoid[s]) or "-", flush=True)
    print("BOTH_P_BELOW_0.05", len(both_p), json.dumps(both_p, ensure_ascii=False), "of judged", out["n_cells_judged"], flush=True)
    for name in ("cond_TxL", "cond_T", "plus_TxL", "plus_T", "B0_all_equal_risk", "B1_good_unconditional"):
        print("PORT", name, json.dumps({k: v for k, v in port[name].items() if k != "held_days"}, ensure_ascii=False), flush=True)
    print("HELD", json.dumps({n: port[n]["held_days"] for n in ("cond_TxL", "cond_T", "plus_TxL")}, ensure_ascii=False), flush=True)
    print("TODAY", json.dumps(port["today"], ensure_ascii=False), "| 今天这个状态的长处(全样本表):", ",".join(strengths[port["today"]["TxL"]]) or "-", flush=True)
    if selftest:
        assert "bear_only" in strengths["T线下"] and "bear_only" not in strengths["T线上"], strengths
        assert "bull_only" in strengths["T线上"] and "always_down" not in sum(strengths.values(), []), strengths
        assert "always_down" in avoid["T线下"] and "always_down" in avoid["T线上"]
        assert port["cond_T"]["perf"]["ratio"] > port["B0_all_equal_risk"]["perf"]["ratio"], "按状态取长处应当好过全都等权拿着(合成数据里长处是种进去的)"
        assert port["cond_T"]["placebo"]["percentile_of_real_ratio"] >= 0.9, port["cond_T"]["placebo"]
        assert port["plus_T"]["held_days"]["T线上"].get("always_up", 0) > 500, "一直好的那条,加了并集之后在它相对弱的一半状态里也该拿着"
        # 不偷看:把某天之后的收益全改掉,那天之前选出来的名单不许变
        cut = sorted(states)[1500]
        p2 = {k: {d: (v if d <= cut else -v) for d, v in rets.items()} for k, rets in panel.items()}
        a = walk(states, month_tables(states, panel), _scaled(panel), T_LEVEL)["selection"]
        b = walk(states, month_tables(states, p2), _scaled(p2), T_LEVEL)["selection"]
        early = [m for m in a if dt.date.fromisoformat(m) <= cut]
        assert early and all(a[m] == b[m] for m in early), "月初的名单用到了当月及以后的收益"
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
