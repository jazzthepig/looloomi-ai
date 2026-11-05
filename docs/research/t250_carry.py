#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-250 — S-733「④ 资金费套息在 HL 已实现小时费率上」盲复算(lane-a)+ HL 现货子集。

口径来源:REFUTATION_LEDGER.md §S-733 的「口径」段(S-707 原样)与卡 T-250 的 acceptance。
**盲复算声明**:本脚本写作时**没有**打开 `src/research/validation/s733_hl_carry.py`,
也没有打开 `docs/research/s733_hl_carry_result.json`;实现全部从上面的口径文字推出来。
(§2 的逐项对照是本脚本跑完之后、单独一步才做的。)

数据:Mac 数据根 `_data/hyperliquid_funding/*_funding_1h.csv`(HL `fundingHistory` 小时档,
Minimax-A 2026-07-20 抓)+ 同目录 `btc_1d_ohlcv.csv`(BTC 日线收盘,只做 (c) 的基准)。
只读、只算:不改代码、不入库。

面板:① 的 24 名 = `src/research/strategies/causal_positioning.py` 的 `DEFAULT_UNIVERSE`
(用 ast 解析,不改 src/)。

窗口:2023-06-01 → 2026-07-20(UTC)。

口径(照抄 S-733,一项不改):
  每日已实现 funding = 当日小时费率之和(空方收正费率);
  A = 常开;B = 每周一看过去 7 天日费率均值 > 0 且至少 5 天有数 ⇒ 开,否则空仓,按周换仓;
  净 = 毛 − 7.5bp × 切换次数(现货 taker 4bp + 永续 taker 3.5bp;A 只在起点付一次);
  等权 = 当日有费率(≥20 个小时档)的名字等权,不在场的份额闲置。
"""
from __future__ import annotations

import ast
import csv
import json
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from src.data.evaluation.apparatus import block_permute, null_distribution, percentile_of  # noqa: E402

DATA_ROOT = "/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding"
PANEL_SRC = os.path.join(REPO, "src/research/strategies/causal_positioning.py")

WIN_START = date(2023, 6, 1)
WIN_END = date(2026, 7, 20)

MIN_BARS_PER_DAY = 20      # 卡:当日 ≥ 20 个小时档才算有
FEE_BPS = 7.5              # 口径:7.5bp/次
FEE = FEE_BPS / 10_000.0
SEED = 733
N_PERM = 2000              # (c) 块置换次数
N_CONTROL = 1000           # (d) 随机门控对照次数
SPOT_URL = "https://api.hyperliquid.xyz/info"

PERIODS = [
    ("2023H2", date(2023, 6, 1), date(2023, 12, 31)),
    ("2024", date(2024, 1, 1), date(2024, 12, 31)),
    ("2025", date(2025, 1, 1), date(2025, 12, 31)),
    ("2026H1", date(2026, 1, 1), date(2026, 6, 30)),
    ("2026-07-01..20", date(2026, 7, 1), date(2026, 7, 20)),
]

#: 逐期的第二种切法(Seth 的 by_period:2023/2026 按 H1/H2 切,2023H1 只剩 6 月)
PERIODS_SETH = [
    ("2023H1(Jun)", date(2023, 6, 1), date(2023, 6, 30)),
    ("2023H2(Jul-Dec)", date(2023, 7, 1), date(2023, 12, 31)),
    ("2024", date(2024, 1, 1), date(2024, 12, 31)),
    ("2025", date(2025, 1, 1), date(2025, 12, 31)),
    ("2026H1", date(2026, 1, 1), date(2026, 6, 30)),
    ("2026H2(Jul1-20)", date(2026, 7, 1), date(2026, 7, 20)),
]


# ───────────────────────────── 基础工具 ─────────────────────────────
def load_panel() -> list[str]:
    """从 causal_positioning.py 用 ast 取 DEFAULT_UNIVERSE(① 的 24 名),不 import src/。"""
    tree = ast.parse(open(PANEL_SRC, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "DEFAULT_UNIVERSE" for t in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise RuntimeError("DEFAULT_UNIVERSE not found")


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def mondays(a: date, b: date) -> list[date]:
    """[a, b] 内的所有周一(门控换仓日)。"""
    d = a + timedelta(days=(7 - a.weekday()) % 7)
    out = []
    while d <= b:
        out.append(d)
        d += timedelta(days=7)
    return out


def load_funding(sym: str) -> dict[date, tuple[float, int]]:
    """小时档 → {UTC 日: (费率之和, 小时档数)}。"""
    path = os.path.join(DATA_ROOT, f"{sym.lower()}_funding_1h.csv")
    agg: dict[date, list[float]] = defaultdict(lambda: [0.0, 0])
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as fh:
        for row in csv.reader(fh):
            if not row or row[0] == "fundingTime":
                continue
            day = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc).date()
            cell = agg[day]
            cell[0] += float(row[1])
            cell[1] += 1
    return {d: (v[0], v[1]) for d, v in agg.items()}


def load_btc_close() -> dict[date, float]:
    path = os.path.join(DATA_ROOT, "btc_1d_ohlcv.csv")
    out: dict[date, float] = {}
    with open(path, newline="") as fh:
        for row in csv.reader(fh):
            if not row or row[0] == "openTime":
                continue
            out[datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc).date()] = float(row[1])
    return out


def _ranks(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=lambda i: v[i])
    ranks = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float | None:
    """平均秩 Spearman(不依赖 scipy)。"""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def annualize(net: np.ndarray) -> float:
    """日净收益 → 复利年化。"""
    if net.size == 0:
        return float("nan")
    nav = float(np.prod(1.0 + net))
    if nav <= 0:
        return float("nan")
    return nav ** (365.0 / net.size) - 1.0


def max_drawdown(net: np.ndarray) -> float:
    if net.size == 0:
        return float("nan")
    nav = np.cumprod(1.0 + net)
    peak = np.maximum.accumulate(nav)
    return float((nav / peak - 1.0).min())


# ───────────────────────────── 面板与数据 ─────────────────────────────
def build_matrices():
    panel = load_panel()
    days = list(daterange(WIN_START, WIN_END))
    idx = {d: i for i, d in enumerate(days)}
    n_t, n_n = len(days), len(panel)

    R = np.zeros((n_t, n_n))
    PRESENT = np.zeros((n_t, n_n), dtype=bool)
    coverage, aggs = [], []

    for j, sym in enumerate(panel):
        agg = load_funding(sym)
        aggs.append(agg)
        if not agg:
            coverage.append({"symbol": sym, "has_data": False})
            continue
        first, last = min(agg), max(agg)
        for d, (s, c) in agg.items():
            if d in idx and c >= MIN_BARS_PER_DAY:
                R[idx[d], j] = s
                PRESENT[idx[d], j] = True
        coverage.append({
            "symbol": sym, "has_data": True,
            "first_day": str(first), "last_day": str(last),
            "days_total": len(agg),
            "bars_total": sum(c for _, c in agg.values()),
            "days_in_window": int(PRESENT[:, j].sum()),
            "days_below_20bars_in_window": int(sum(
                1 for d, (_, c) in agg.items() if d in idx and c < MIN_BARS_PER_DAY)),
        })
    return panel, days, idx, R, PRESENT, coverage, aggs


# ───────────────────────────── 规则 A / B ─────────────────────────────
def rule_a(R, PRESENT):
    """A:常开。每名只在首个有数据日(在窗口内)付一次 7.5bp;数据缺口不视为平仓。"""
    count = PRESENT.sum(axis=1)
    gross = np.where(count > 0, (PRESENT * R).sum(axis=1) / np.maximum(count, 1), 0.0)
    entry = np.zeros_like(PRESENT)
    fee_name = np.zeros_like(R)
    for j in range(PRESENT.shape[1]):
        idxs = np.flatnonzero(PRESENT[:, j])
        if idxs.size:
            entry[idxs[0], j] = True
            fee_name[idxs[0], j] = FEE
    fee_daily = np.where(count > 0, FEE * entry.sum(axis=1) / np.maximum(count, 1), 0.0)
    return gross - fee_daily, gross, fee_daily, fee_name, entry


def weekly_gate(R, PRESENT, days, idx, aggs, cols=None):
    """B:每周一看过去 7 天日费率均值 > 0 且至少 5 天有数 ⇒ 开,否则空仓,按周换仓。

    - 决策从窗口内第一个可行周一(不早于该名首个有数据日)开始;此前空仓。
    - 回看窗口可用窗口之前的数据(当时确实拿得到)。
    - 「有数」= 当日 ≥ 20 个小时档。
    """
    n_t, n_n = R.shape
    jcols = list(range(n_n)) if cols is None else list(cols)
    gate = np.zeros((n_t, n_n), dtype=bool)
    switch_day = np.zeros((n_t, n_n), dtype=bool)
    switch_count = np.zeros(n_n, dtype=int)
    mons = mondays(WIN_START, WIN_END)
    for j in jcols:
        agg = aggs[j]
        present_days = np.flatnonzero(PRESENT[:, j])
        if present_days.size == 0:
            continue
        first_day = days[present_days[0]]
        cur = False                                   # 初始空仓
        for m in mons:
            if m < first_day:
                continue
            vals = []
            for k in range(1, 8):
                d = m - timedelta(days=k)
                cell = agg.get(d)
                if cell and cell[1] >= MIN_BARS_PER_DAY:
                    vals.append(cell[0])
            on = (len(vals) >= 5) and (sum(vals) / len(vals) > 0)
            if on != cur:
                switch_day[idx[m], j] = True
                switch_count[j] += 1
                cur = on
            for k in range(0, 7):
                d = m + timedelta(days=k)
                if d in idx:
                    gate[idx[d], j] = on
    return gate, switch_day, switch_count


def rule_b(R, PRESENT, gate, switch_day):
    count = PRESENT.sum(axis=1)
    active = PRESENT & gate
    gross = np.where(count > 0, (active * R).sum(axis=1) / np.maximum(count, 1), 0.0)
    fee_daily = np.where(count > 0, FEE * switch_day.sum(axis=1) / np.maximum(count, 1), 0.0)
    fee_name = np.zeros_like(R)
    for j in range(R.shape[1]):
        fee_name[switch_day[:, j], j] = FEE
    return gross - fee_daily, gross, fee_daily, fee_name


# ───────────────────────── 负段 / 占比 ─────────────────────────
def negative_segments(panel, days, R, active, fee_name):
    """逐名:在「在场且持仓」的日子序列上找连续负费率段,累计 = Σ费率 + Σ费用(负数)。

    连续性按「该臂持仓日序列」判定:数据缺口(A)/被门控关掉(B)都会断段。
    """
    longest = worst = None
    segs_all = []
    for j, sym in enumerate(panel):
        act = list(np.flatnonzero(active[:, j]))
        run: list[int] = []
        for i in act + [None]:
            if i is not None and R[i, j] < 0:
                run.append(i)
                continue
            if run:
                cum = float(sum(R[i, j] for i in run)) + float(sum(fee_name[i, j] for i in run))
                seg = {"symbol": sym, "days": len(run), "cum_pct": cum * 100,
                       "start": str(days[run[0]]), "end": str(days[run[-1]])}
                segs_all.append(seg)
                if longest is None or seg["days"] > longest["days"]:
                    longest = seg
                if worst is None or seg["cum_pct"] < worst["cum_pct"]:
                    worst = seg
                run = []
    return longest, worst, segs_all


def occupancy(panel, days, idx, gate, PRESENT, mons):
    """在场占比:B 在场(周为单位 / 名-日为单位)。分母 = 该名在场的周(至少一天有数据)。"""
    on_weeks = tot_weeks = on_days = act_days = 0
    per_name = {}
    for j, sym in enumerate(panel):
        pd = np.flatnonzero(PRESENT[:, j])
        if pd.size == 0:
            per_name[sym] = None
            continue
        first = days[pd[0]]
        w_on = w_off = 0
        for m in mons:
            if m < first:
                continue
            wk_days = [m + timedelta(days=k) for k in range(7)]
            wk_days = [d for d in wk_days if d in idx]
            if not any(PRESENT[idx[d], j] for d in wk_days):
                continue
            if gate[idx[m], j]:
                w_on += 1
            else:
                w_off += 1
        d_on = int((PRESENT[:, j] & gate[:, j]).sum())
        d_act = int(PRESENT[:, j].sum())
        on_weeks += w_on
        tot_weeks += w_on + w_off
        on_days += d_on
        act_days += d_act
        per_name[sym] = {"weeks_on": w_on, "weeks_off": w_off,
                         "week_occupancy": w_on / max(w_on + w_off, 1),
                         "day_occupancy": d_on / max(d_act, 1)}
    return {
        "week_occupancy_overall": on_weeks / max(tot_weeks, 1),
        "day_occupancy_overall": on_days / max(act_days, 1),
        "weeks_on": on_weeks, "weeks_total": tot_weeks,
        "per_name": per_name,
    }


# ───────────────────────── 随机门控对照 (d) ─────────────────────────
def segment_pattern(states: list[bool]) -> list[tuple[bool, int]]:
    """把周状态序列拆成 [(状态, 长度), …] 的交替段。"""
    segs: list[tuple[bool, int]] = []
    for s in states:
        if segs and segs[-1][0] == bool(s):
            segs[-1] = (segs[-1][0], segs[-1][1] + 1)
        else:
            segs.append((bool(s), 1))
    return segs


def control_distribution(R, PRESENT, weekly_states, mons, days, idx,
                         n=N_CONTROL, seed=SEED, arith=False):
    """(d) 随机门控:逐名把开段 / 关段长度各自打乱(开周数、切换数不变),重算组合净年化。

    arith=True ⇒ 统计量用算术均值 × 365(Seth 的口径);False ⇒ 复利年化。
    """
    rng = np.random.default_rng(seed)
    count = PRESENT.sum(axis=1)
    out = []
    for _ in range(n):
        gate = np.zeros_like(PRESENT)
        sw = np.zeros_like(PRESENT)
        for j in range(R.shape[1]):
            segs = segment_pattern(list(weekly_states[j]))
            if not segs:
                continue
            on_idx = [i for i, (st, _) in enumerate(segs) if st]
            off_idx = [i for i, (st, _) in enumerate(segs) if not st]
            on_len = [segs[i][1] for i in on_idx]
            off_len = [segs[i][1] for i in off_idx]
            on_perm = list(rng.permutation(on_len))
            off_perm = list(rng.permutation(off_len))
            new_len = [0] * len(segs)
            for k, i in enumerate(on_idx):
                new_len[i] = on_perm[k]
            for k, i in enumerate(off_idx):
                new_len[i] = off_perm[k]
            wk: list[bool] = []
            for (st, _), ln in zip(segs, new_len):
                wk.extend([st] * ln)
            wk = wk[:len(mons)]
            prev = False
            for wi, st in enumerate(wk):
                if st != prev:
                    if mons[wi] in idx:
                        sw[idx[mons[wi]], j] = True
                    prev = st
                for k in range(7):
                    d = mons[wi] + timedelta(days=k)
                    if d in idx:
                        gate[idx[d], j] = st
        gross = np.where(count > 0, (gate * R).sum(axis=1) / np.maximum(count, 1), 0.0)
        fee = np.where(count > 0, FEE * sw.sum(axis=1) / np.maximum(count, 1), 0.0)
        net = gross - fee
        out.append(float(net.mean() * 365) if arith else annualize(net))
    return np.array(out)


def seth_stats(x: np.ndarray) -> dict:
    """Seth 实现里的 stats():算术年化 + **求和**式回撤 + **组合层**负段。"""
    cum = np.cumsum(x)
    dd = float((cum - np.maximum.accumulate(cum)).min())
    bl, bl_l, cl, cl_l = 0, 0.0, 0, 0.0
    for v in x:
        if v < 0:
            cl += 1
            cl_l += v
            if cl > bl or (cl == bl and cl_l < bl_l):
                bl, bl_l = cl, cl_l
        else:
            cl, cl_l = 0, 0.0
    return {"ann_net": float(x.mean() * 365), "max_dd_sum": dd,
            "neg_run_days": bl, "neg_run_loss": bl_l}


# ───────────────────────── 主流程 ─────────────────────────
def main() -> None:
    panel, days, idx, R, PRESENT, coverage, aggs = build_matrices()
    names_with_data = [c["symbol"] for c in coverage if c["has_data"]]

    net_a, gross_a, fee_a, fee_name_a, entry_a = rule_a(R, PRESENT)
    gate, switch_day, switch_count = weekly_gate(R, PRESENT, days, idx, aggs)
    net_b, gross_b, fee_b, fee_name_b = rule_b(R, PRESENT, gate, switch_day)

    active_a = PRESENT.copy()
    active_b = PRESENT & gate
    longest_a, worst_a, segs_a = negative_segments(panel, days, R, active_a, fee_name_a)
    longest_b, worst_b, segs_b = negative_segments(panel, days, R, active_b, fee_name_b)

    mons = mondays(WIN_START, WIN_END)
    occ_b = occupancy(panel, days, idx, gate, PRESENT, mons)

    def period_slice(net, a, b):
        sel = [i for i, d in enumerate(days) if a <= d <= b]
        if not sel:
            return None
        seg = net[sel]
        return {"days": len(seg), "ann_net_pct": annualize(seg) * 100,
                "total_pct": (float(np.prod(1 + seg)) - 1) * 100,
                "arith_ann_pct": float(seg.mean()) * 365 * 100,
                "max_dd_pct": max_drawdown(seg) * 100}

    per_period = {name: {"A": period_slice(net_a, a, b), "B": period_slice(net_b, a, b)}
                  for name, a, b in PERIODS}
    per_period_seth = {name: {"A": period_slice(net_a, a, b), "B": period_slice(net_b, a, b)}
                       for name, a, b in PERIODS_SETH}

    # ── (c) 月度套息 vs 未来 30 日 BTC ──
    btc = load_btc_close()

    def close_at(d: date):
        if d in btc:
            return btc[d]
        for k in range(1, 4):
            dd = d + timedelta(days=k)
            if dd in btc:
                return btc[dd]
        return None

    def month_end(d: date) -> date:
        return (d.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    monthly = []
    cur = date(WIN_START.year, WIN_START.month, 1)
    while cur <= WIN_END:
        m_end = month_end(cur)
        nxt = m_end + timedelta(days=1)
        if m_end > WIN_END:
            break
        sel = [i for i, d in enumerate(days) if cur <= d <= m_end]
        if len(sel) != (m_end - cur).days + 1:      # 不完整月不参与
            cur = nxt
            continue
        r_m = float(np.prod(1 + net_b[sel]) - 1)
        c0, c1 = close_at(m_end), close_at(m_end + timedelta(days=30))
        c_same0 = close_at(cur - timedelta(days=1))
        if c0 is None or c1 is None or c_same0 is None:
            cur = nxt
            continue
        monthly.append({
            "month": cur.strftime("%Y-%m"), "carry_b_pct": r_m * 100,
            "btc_fwd30_pct": (c1 / c0 - 1) * 100,
            "btc_same_month_pct": (c0 / c_same0 - 1) * 100,
        })
        cur = nxt

    def corr_block(x, y, block, n=N_PERM, seed=SEED):
        act = spearman(x, y)
        if act is None:
            return {"rho": None, "p": None, "n": len(x)}
        try:
            null = null_distribution(
                lambda rng: spearman(list(block_permute(x, block, rng)), y),
                n=n, seed=seed, actual=act)
        except Exception as exc:
            return {"rho": act, "p": None, "n": len(x), "error": str(exc)}
        p_one = 1.0 - percentile_of(act, null)
        p_two = float((np.abs(null) >= abs(act) - 1e-12).mean())
        return {"rho": act, "p_one_sided": float(p_one), "p_two_sided": p_two,
                "null_median": float(np.median(null)),
                "n": len(x), "block": block, "n_perm": n}

    mx = [m["carry_b_pct"] for m in monthly]
    mf = [m["btc_fwd30_pct"] for m in monthly]
    ms = [m["btc_same_month_pct"] for m in monthly]
    c_fwd30 = {f"block{b}": corr_block(mx, mf, b) for b in (1, 2, 3)}
    c_same = {f"block{b}": corr_block(mx, ms, b) for b in (1, 2)}

    nav_b = np.cumprod(1 + net_b)
    daily30 = []
    for i in range(29, len(days) - 30):
        c0, c1 = close_at(days[i]), close_at(days[i] + timedelta(days=30))
        if c0 is None or c1 is None:
            continue
        daily30.append((float(nav_b[i] / nav_b[i - 29] - 1) * 100, (c1 / c0 - 1) * 100))
    dx = [a for a, _ in daily30]
    dy = [b for _, b in daily30]
    c_daily = {"block30": corr_block(dx, dy, 30)}

    # ── ② 逐项对照(Seth 的实现口径,并排算一遍)──
    xcheck = {"A": seth_stats(net_a), "B": seth_stats(net_b),
              "days": len(days), "n_names": len(names_with_data)}
    cnt = PRESENT.sum(axis=1)
    xcheck["days_no_names"] = int((cnt == 0).sum())
    xcheck["min_names_per_day"] = int(cnt[cnt > 0].min())
    xcheck["n_mondays"] = len(mons)
    xcheck["switches_A"] = int(entry_a.sum())
    xcheck["switches_B"] = int(switch_day.sum())
    on_cells = sum(1 for m in mons for j in range(len(panel)) if gate[idx[m], j])
    xcheck["B_on_share_all_cells"] = on_cells / (len(mons) * len(panel))
    xcheck["per_name_A_gross_mean365"] = {
        panel[j]: float(R[PRESENT[:, j], j].mean() * 365)
        for j in range(len(panel)) if PRESENT[:, j].sum() > 0}
    # 月度:求和口径(Seth);参数 p(scipy)若有
    m_sum = []
    for m in monthly:
        mm = m["month"]
        sel = [i for i, d in enumerate(days) if d.strftime("%Y-%m") == mm]
        m_sum.append(float(net_b[sel].sum() * 100))
    m_fwd = [m["btc_fwd30_pct"] for m in monthly]
    m_same = [m["btc_same_month_pct"] for m in monthly]
    for row, s in zip(monthly, m_sum):
        row["carry_b_sum_pct"] = s
    xcheck["c_monthly_sum"] = corr_block(m_sum, m_fwd, 1)
    xcheck["c_same_month_sum"] = corr_block(m_sum, m_same, 1)
    try:  # scipy 的参数 p(Seth 报的 monthly_param_p / same_month_p 是这个)
        from scipy.stats import spearmanr
        xcheck["c_param_p"] = {
            "monthly_future": float(spearmanr(m_sum, m_fwd)[1]),
            "monthly_same_month": float(spearmanr(m_sum, m_same)[1]),
        }
    except Exception as exc:
        xcheck["c_param_p"] = {"error": str(exc)}
    # 日频:求和口径
    dxs, dys = [], []
    for i in range(29, len(days) - 30):
        c0, c1 = close_at(days[i]), close_at(days[i] + timedelta(days=30))
        if c0 is None or c1 is None:
            continue
        dxs.append(float(net_b[i - 29:i + 1].sum() * 100))
        dys.append((c1 / c0 - 1) * 100)
    xcheck["c_daily_sum_block30"] = corr_block(dxs, dys, 30, n=1000)

    # ── (d) 随机门控对照 ──
    weekly_states = []
    for j in range(R.shape[1]):
        weekly_states.append([bool(gate[idx[m], j]) if m in idx else False for m in mons])
    ctrl = control_distribution(R, PRESENT, weekly_states, mons, days, idx)
    b_ann = annualize(net_b)
    ctrl_pct = percentile_of(b_ann, list(ctrl))
    ctrl_stats = {
        "B_ann_pct": b_ann * 100,
        "control_median_pct": float(np.median(ctrl)) * 100,
        "control_p95_pct": float(np.percentile(ctrl, 95)) * 100,
        "B_percentile": ctrl_pct,
        "B_ge_p95": bool(ctrl_pct is not None and ctrl_pct >= 0.95),
        "n": int(ctrl.size),
    }

    # (d) 同一对照,统计量换成算术年化(Seth 的口径)
    ctrl_a = control_distribution(R, PRESENT, weekly_states, mons, days, idx, arith=True)
    b_arith = float(net_b.mean() * 365)
    xcheck["d_arith"] = {
        "B_ann": b_arith,
        "null_median": float(np.median(ctrl_a)),
        "null_p95": float(np.percentile(ctrl_a, 95)),
        "pctile": percentile_of(b_arith, list(ctrl_a)),
        "n": int(ctrl_a.size),
    }

    # ── ③ HL 现货子集 ──
    tokens = fetch_spot_tokens()
    spot_map = map_spot(panel, tokens)
    subset = [s for s in panel if s in spot_map]
    sub_res = None
    if subset:
        cols = [panel.index(s) for s in subset]
        Rs, Ps = R[:, cols], PRESENT[:, cols]
        sub_aggs = [aggs[j] for j in cols]
        net_as, gross_as, fee_as, fee_name_as, entry_as = rule_a(Rs, Ps)
        g_s, sw_s, swc_s = weekly_gate(Rs, Ps, days, idx, sub_aggs, cols=list(range(len(cols))))
        net_bs, gross_bs, fee_bs, fee_name_bs = rule_b(Rs, Ps, g_s, sw_s)
        la, wa, _ = negative_segments(subset, days, Rs, Ps.copy(), fee_name_as)
        lb, wb_, _ = negative_segments(subset, days, Rs, Ps & g_s, fee_name_bs)
        sub_res = {
            "subset": subset,
            "token_map": {s: spot_map[s] for s in subset},
            "A": {"ann_net_pct": annualize(net_as) * 100,
                  "total_pct": (float(np.prod(1 + net_as)) - 1) * 100,
                  "max_dd_pct": max_drawdown(net_as) * 100,
                  "longest_neg_seg": la, "worst_neg_seg": wa,
                  "entry_fees": int(entry_as.sum())},
            "B": {"ann_net_pct": annualize(net_bs) * 100,
                  "total_pct": (float(np.prod(1 + net_bs)) - 1) * 100,
                  "max_dd_pct": max_drawdown(net_bs) * 100,
                  "longest_neg_seg": lb, "worst_neg_seg": wb_,
                  "switches": int(sw_s.sum()),
                  "week_occupancy": occupancy(subset, days, idx, g_s, Ps, mons)["week_occupancy_overall"]},
            "coverage": [coverage[panel.index(s)] for s in subset],
        }

    contrib = []
    for j, sym in enumerate(panel):
        contrib.append({"symbol": sym,
                        "total_funding_pct": float(R[PRESENT[:, j], j].sum() * 100),
                        "days": int(PRESENT[:, j].sum())})
    contrib.sort(key=lambda c: c["total_funding_pct"])

    out = {
        "task": "T-250",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": [str(WIN_START), str(WIN_END)],
        "panel": panel,
        "panel_with_funding": names_with_data,
        "min_bars_per_day": MIN_BARS_PER_DAY,
        "fee_bps_per_switch": FEE_BPS,
        "coverage": coverage,
        "A": {
            "ann_net_pct": annualize(net_a) * 100,
            "arith_ann_pct": float(net_a.mean()) * 365 * 100,
            "total_pct": (float(np.prod(1 + net_a)) - 1) * 100,
            "max_dd_pct": max_drawdown(net_a) * 100,
            "gross_ann_pct": annualize(gross_a) * 100,
            "fee_total_pct": float(-fee_a.sum()) * 100,
            "entry_fees": int(entry_a.sum()),
            "longest_neg_seg": longest_a, "worst_neg_seg": worst_a,
        },
        "B": {
            "ann_net_pct": annualize(net_b) * 100,
            "arith_ann_pct": float(net_b.mean()) * 365 * 100,
            "total_pct": (float(np.prod(1 + net_b)) - 1) * 100,
            "max_dd_pct": max_drawdown(net_b) * 100,
            "gross_ann_pct": annualize(gross_b) * 100,
            "fee_total_pct": float(-fee_b.sum()) * 100,
            "switches": int(switch_day.sum()),
            "switches_by_name": {panel[j]: int(switch_count[j]) for j in range(len(panel))},
            "occupancy": occ_b,
            "longest_neg_seg": longest_b, "worst_neg_seg": worst_b,
        },
        "per_period": per_period,
        "per_period_seth_split": per_period_seth,
        "criterion_c": {
            "monthly_vs_btc_fwd30": c_fwd30,
            "monthly_vs_btc_same_month": c_same,
            "daily_trail30_vs_btc_fwd30": c_daily,
            "monthly_rows": monthly,
        },
        "criterion_d": ctrl_stats,
        "cross_check_seth_conventions": xcheck,
        "hl_spot_subset": sub_res,
        "spot_token_map": spot_map,
        "per_name_funding": contrib,
        "neg_segments_B_worst10": sorted(segs_b, key=lambda s: s["cum_pct"])[:10],
        "neg_segments_A_worst10": sorted(segs_a, key=lambda s: s["cum_pct"])[:10],
    }
    out_path = os.path.join(REPO, "docs/research/t250_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print("== A ==", json.dumps(out["A"], ensure_ascii=False))
    print("== B ==", json.dumps({k: v for k, v in out["B"].items() if k != "occupancy"}, ensure_ascii=False))
    print("== occ ==", json.dumps({k: v for k, v in out["B"]["occupancy"].items() if k != "per_name"}, ensure_ascii=False))
    print("== periods ==", json.dumps(out["per_period"], ensure_ascii=False))
    print("== (c) ==", json.dumps({k: v for k, v in out["criterion_c"].items() if k != "monthly_rows"}, ensure_ascii=False))
    print("== (d) ==", json.dumps(out["criterion_d"], ensure_ascii=False))
    print("== xcheck ==", json.dumps(xcheck, ensure_ascii=False))
    print("== periods(seth split) ==", json.dumps(per_period_seth, ensure_ascii=False))
    print("== spot ==", json.dumps(out["spot_token_map"], ensure_ascii=False))
    print("== subset ==", json.dumps(sub_res, ensure_ascii=False) if sub_res else "None")
    print("written:", out_path)


def fetch_spot_tokens() -> list[str]:
    """HL info spotMeta(公开端点,只读)。失败则返回空列表。"""
    try:
        req = urllib.request.Request(
            SPOT_URL, data=json.dumps({"type": "spotMeta"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.load(resp)
        return [t["name"] for t in data.get("tokens", [])]
    except Exception as exc:
        print("spotMeta fetch failed:", exc)
        return []


def map_spot(panel: list[str], tokens: list[str]) -> dict[str, list[str]]:
    """① 24 名 → HL 现货代币名(UBTC / AAVE0 / XRP1 …)。

    规则:代币名 == 标的,或 "U"+标的,或 标的+数字后缀,或 "U"+标的+数字后缀。
    """
    tset = set(tokens)
    out: dict[str, list[str]] = {}
    for sym in panel:
        cands = [sym, f"U{sym}", f"{sym}0", f"{sym}1", f"U{sym}0", f"U{sym}1"]
        hit = sorted(c for c in cands if c in tset)
        if hit:
            out[sym] = hit
    return out


if __name__ == "__main__":
    main()
