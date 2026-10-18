"""T-125 / S-606 —— 灵活组合的回撤—收益地图,股票腿换真腿(Seth 10-18 第 3 轮再修版)。

S-604 → S-606 的两处变化(字面不动 S-604 的常量):
  1. 股票腿:ACWI → World50 EW×Mom **日 NAV 回放**(在 research/w50_daily 上重跑)。
     **修正-2(Seth 10-18 退回)**:`months[:mi + 1]` 这段把当月月末价当成"已知"
     来算动量,日版 CAGR 因此比 t099 月度版高 36pp。本版:
       a) 只用 **截至 m−1 月末** 的数据(closes + mcap)做 m 月的成分与权重;
       b) 换仓节奏 = 季度换仓(EW×Mom = 03/06/09/12 季末换,6 + 12 月动量,
          与 `t099.run_arm` 一套) → 季内按日价漂移;
       c) 起始 1–3 月数据不足 → 1/N 等权;首季度末(2016-04 起)开始正式动量调权。
     这本与 t099 月度版同口径、不再有前视。
     **不再用月收益等比拆日**:`(1+r_m)^(1/n) − 1` 会把月内波动抹平,股票
     越重的组合 ddp5 越乐观 —— 退回原因-1。本版本用真实日 NAV。
  2. 黄金网格:{0, 0.10, 0.20} → {0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40}(步长 0.05)
  3. 追加两个固定点 T25 = 30/30/20/20、T35 = 40/40/20/0,各给 H / X1V /
     X1V_fric 三种加密腿下的 cagr 中位 / p05 / dd 中位 / ddp5。

其余(crypto 腿 H / X1V / X1V_fric、grid 总数、cost、rebalance、bootstrap
块长、days、seed)照 s604_frontier 一字不改。

用法:python3 docs/research/t125_s606_frontier.py <research 目录> <输出 json>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.data.evaluation.apparatus import stationary_bootstrap_index  # noqa: E402
from src.data.universe.world50 import (  # noqa: E402
    closes_from_returns as w50_closes_from_returns,
    equal_weights,
    momentum_tilt,
    select_members,
    rank_by_mcap,
)

import s602_simulate as s602  # noqa: E402
import t099_world50_replay as t099  # noqa: E402

# ── 照搬 s604 的常量(一个字不改) ─────────────────────────────────────────────
START, END, REB, COST, N_PATHS, DAYS, BLOCK, SEED = "2016-01-04", "2026-10-15", 21, 10 / 1e4, 1000, 1512, 60, 604
COST_EQUITY = COST  # equity 10bp(同 t099)


# ── 黄金网格放宽到 0–40%(本卡唯一的 grid 改动) ────────────────────────────────
GOLD_STEP = 0.05


def gold_grid() -> list[float]:
    g = 0.0
    out = []
    while g <= 0.40 + 1e-9:
        out.append(round(g, 4))
        g += GOLD_STEP
    return out


def grid():
    """crypto 1..7 / equity 1..8 / gold 0..0.40 步长 5%;c+e+g ∈ [3, 10];其余现金。"""
    out = []
    for c in range(1, 8):
        for e in range(1, 9):
            for g in gold_grid():
                gw = round(g, 2)
                if c / 10 + e / 10 + gw <= 1.0 + 1e-9 and c / 10 + e / 10 + gw >= 0.30 - 1e-9:
                    out.append((c / 10, e / 10, gw))
    return out


def fixed_points() -> list[tuple]:
    """Seth 10-18 指定的两个对照点(配比 = crypto/equity/gold/cash),cash = 1 − (c+e+g)。"""
    return [(0.30, 0.30, 0.20, "T25"), (0.40, 0.40, 0.20, "T35")]


# ── 复用 s604 的 portfolio / stats ────────────────────────────────────────────

def portfolio(R: np.ndarray, w: tuple) -> np.ndarray:
    """R: (paths, days, 3);恒定配比,每 REB 天再平衡;返回 (paths, days) 日收益。"""
    tgt = np.array(w)
    P, D, _ = R.shape
    hold = np.tile(tgt, (P, 1))
    out = np.zeros((P, D))
    for t in range(D):
        if t % REB == 0 and t > 0:
            tv = np.abs(hold - tgt).sum(axis=1)
            hold = np.tile(tgt, (P, 1))
            cost = tv * COST
        else:
            cost = 0.0
        r = (hold * R[:, t, :]).sum(axis=1)
        out[:, t] = r - cost
        grown = hold * (1 + R[:, t, :])
        tot = grown.sum(axis=1) + (1 - hold.sum(axis=1))
        hold = grown / tot[:, None]
    return out


def stats(r: np.ndarray, per_year: float = 252.0):
    nav = np.cumprod(1 + r, axis=1)
    yrs = r.shape[1] / per_year
    cagr = nav[:, -1] ** (1 / yrs) - 1
    dd = (nav / np.maximum.accumulate(nav, axis=1) - 1).min(axis=1)
    return cagr, dd


# ── World50 EW×Mom 日 NAV 回放 ────────────────────────────────────────────────

def _monthly_close(close_all: list, dates_all: list[str]) -> dict[str, dict[str, float]]:
    """每个成分在每个月份的最后一个非空 close(月份 → {key: close});空月跳过。"""
    out: dict[str, dict[str, float]] = {}
    cur_ym, last_d, last_v = None, None, None
    for i, d in enumerate(dates_all):
        ym = d[:7]
        v = close_all[i]
        if ym != cur_ym:
            if cur_ym is not None and last_v is not None:
                out.setdefault(cur_ym, {})  # noqa: F841
            cur_ym = ym
            last_d, last_v = d, None
        if v is not None and v > 0:
            last_d, last_v = d, float(v)
    if cur_ym is not None and last_v is not None:
        out.setdefault(cur_ym, {})  # noqa: F841
    # re-do scan writing into out (simpler: second pass with explicit dict)
    out2: dict[str, dict[str, float]] = {}
    cur_ym, last_v = None, None
    for i, d in enumerate(dates_all):
        ym = d[:7]
        v = close_all[i]
        if ym != cur_ym:
            if cur_ym is not None and last_v is not None:
                out2[cur_ym] = {"_last": last_v}
            cur_ym = ym
            last_v = None
        if v is not None and v > 0:
            last_v = float(v)
    if cur_ym is not None and last_v is not None:
        out2[cur_ym] = {"_last": last_v}
    return out2


def _month_ends(dates_all: list[str], close_data: dict) -> dict[str, dict[str, float]]:
    """更准确的逐 key 实现:每个月选最后一个非空 close。返回 {ym: {key: close}}。"""
    out: dict[str, dict[str, float]] = {}
    for k, c in close_data["close"].items():
        cur_ym, last_v = None, None
        for i, d in enumerate(dates_all):
            ym = d[:7]
            v = c[i]
            if ym != cur_ym:
                if cur_ym is not None and last_v is not None:
                    out.setdefault(cur_ym, {})[k] = last_v
                cur_ym = ym
                last_v = None
            if v is not None and v > 0:
                last_v = float(v)
        if cur_ym is not None and last_v is not None:
            out.setdefault(cur_ym, {})[k] = last_v
    return out


def _filled_mcap(mcap_data: dict, months: list[str]) -> dict[str, dict[str, float]]:
    """对每个月,取 ≤ 月末的最后一个 mcap 快照。"""
    snap_by_ym: dict[str, dict[str, float]] = {}
    for k, pts in mcap_data.items():
        for d, v in pts:
            if v and v > 0:
                snap_by_ym.setdefault(d[:7], {})[k] = float(v)
    sorted_snaps = sorted(snap_by_ym.keys())
    out: dict[str, dict[str, float]] = {}
    j = 0
    for m in months:
        while j < len(sorted_snaps) and sorted_snaps[j] <= m:
            j += 1
        if j > 0:
            out[m] = dict(snap_by_ym[sorted_snaps[j - 1]])
        else:
            out[m] = {}
    return out


def world50_monthly_nav(daily_dir: Path, start: str, end: str) -> dict:
    """用 t099 的 run_arm('EWxMom') 在同一份 w50_daily 上跑月度版(Seth 要求对比)。

    返回 dict,包含 monthly returns + stats(cagr / vol_ann / max_dd)。
    """
    close_data = json.loads((daily_dir / "close.json").read_text())
    mcap_data = json.loads((daily_dir / "mcap.json").read_text())
    dates_all = close_data["dates"]
    cls = close_data["cls"]

    # 月份骨架(2015-01 → 2026-10)
    months: list[str] = []
    for y in range(2015, 2027):
        for mo in range(1, 13):
            if y == 2026 and mo > 10:
                break
            months.append(f"{y:04d}-{mo:02d}")

    # 月末价 = 每个月最后一条非空 close
    me_close = _month_ends(dates_all, close_data)
    # 月收益 = 当月最后价 / 上月最后价 − 1
    rets: dict[str, list[Optional[float]]] = {}
    for k in close_data["close"]:
        seq: list[Optional[float]] = []
        prev = None
        for m in months:
            v = me_close.get(m, {}).get(k)
            if prev is None or v is None:
                seq.append(None)
            else:
                seq.append(v / prev - 1.0)
            if v is not None:
                prev = v
        rets[k] = seq

    # mcap:每个月末(取 ≤ 月末的最接近 mcap 快照)
    snap_by_ym: dict[str, dict[str, float]] = {}
    for k, pts in mcap_data.items():
        for d, v in pts:
            if v and v > 0:
                snap_by_ym.setdefault(d[:7], {})[k] = float(v)
    sorted_snaps = sorted(snap_by_ym.keys())
    mcap_q: dict[str, dict[str, float]] = {}
    j = 0
    for m in months:
        while j < len(sorted_snaps) and sorted_snaps[j] <= m:
            j += 1
        if j > 0:
            mcap_q[m] = dict(snap_by_ym[sorted_snaps[j - 1]])

    rets_clean = {k: [None if v is None else float(v) for v in vs] for k, vs in rets.items()}
    closes_built = {k: w50_closes_from_returns(v) for k, v in rets_clean.items()}
    arm = t099.run_arm("EWxMom", months, rets_clean, mcap_q, cls, closes_built)
    # 只保留窗口内的月份
    span = [m for m in arm["months"] if start <= m + "-01" <= end]
    i0 = arm["months"].index(span[0]) if span else 0
    i1 = arm["months"].index(span[-1]) if span else len(arm["months"]) - 1
    rets_in_window = arm["ret"][i0: i1 + 1]
    months_in_window = arm["months"][i0: i1 + 1]
    if not rets_in_window:
        return {"monthly_log": arm, "stats": None}
    r = np.array(rets_in_window, dtype=float)
    nav_m = np.cumprod(1 + r)
    yrs_m = len(r) / 12.0
    cagr_m = float(nav_m[-1] ** (1 / yrs_m) - 1) if yrs_m > 0 else np.nan
    vol_m = float(r.std(ddof=1) * np.sqrt(12))
    peak_m = np.maximum.accumulate(np.concatenate([[1.0], nav_m]))
    dd_m = float((np.concatenate([[1.0], nav_m]) / peak_m - 1).min())
    return {"monthly_log": arm, "stats": {"cagr": round(cagr_m, 4), "annualized_vol": round(vol_m, 4),
                                          "max_dd": round(dd_m, 4), "window": (months_in_window[0], months_in_window[-1]),
                                          "n_months": len(r)}}


def world50_daily_nav(daily_dir: Path, start: str, end: str) -> tuple[list[str], np.ndarray, dict]:
    """EW×Mom 日 NAV 回放(零前视、季度换仓)。

    与 `t099.run_arm('EWxMom')` 同口径 —— 季末(03/06/09/12)换仓换股,
    1 个月内 drift;但 m 月的成分与权重只能用 **截至 m−1 月末** 的数据。
    也就是说,首季度末 2016-04 的重设看 2016-03 月末价 + 2016-03 的 mcap 快照;
    2016-04–06 三个月的 NAV 漂移,统一用这套权重。
    月初 4 个月动量数据 ≤ 7 ⇒ 1/N 等权;首季度末之后正常走动量打分(6 + 12 月)。

    返回 (out_days, out_ret, meta):
      - out_days:窗口内每个交易日的 date 串(长度 = NAV 天数 + 1)
      - out_ret:对齐 out_days[1:] 的日收益(NAV 比)
      - meta:窗口、cagr(365.25 日历 / 252 交易日两种)、波动、最大回撤、季度调账
    """
    close_data = json.loads((daily_dir / "close.json").read_text())
    mcap_data = json.loads((daily_dir / "mcap.json").read_text())
    dates_all = close_data["dates"]
    cls = close_data["cls"]
    idx = {d: i for i, d in enumerate(dates_all)}
    close_series = close_data["close"]

    universe = sorted(k for k in close_series if cls.get(k) == "equity")

    # 月份骨架(只看窗口内至少有一个交易日的月份)
    days = [d for d in dates_all if start <= d <= end]
    month_to_days: dict[str, list[str]] = {}
    for d in days:
        month_to_days.setdefault(d[:7], []).append(d)
    months = sorted(month_to_days.keys())
    if not months:
        raise RuntimeError("窗口里没有月份,检查 START/END 与 w50_daily/close.json 的覆盖")

    me_close = _month_ends(dates_all, close_data)
    me_mcap = _filled_mcap(mcap_data, months)

    # 起始 NAV
    nav = 1.0
    nav_by_date: dict[str, float] = {}
    prev_prices: dict[str, float] = {}
    members: list[str] = []
    w: dict[str, float] = {}
    last_log: list[dict] = []
    first_weight_month: Optional[str] = None

    QUARTER_STARTS = {"04", "07", "10", "01"}  # 季末月 03/06/09/12 的次月

    def _select_and_weight(ref_m: str) -> tuple[list[str], dict[str, float], bool]:
        """用截至 ref_m(≤ ref_m)月末数据,选 50 个成分 + 算 EW×Mom。
        ref_m = 上一个月(即 mi-1,本月的"cutoff")。
        数据 < 7 月连续 ⇒ fallback 1/N EW。返回 (members, weights, used_momentum)。
        """
        snap = me_mcap.get(ref_m, {})
        if not snap:
            return [], {}, False
        ranked_keys = [k for k, v in sorted(snap.items(), key=lambda kv: -kv[1]) if v and v > 0]
        new_members = select_members(ranked_keys, previous=members, n=50)
        new_members = [k for k in new_members if k in universe]
        if not new_members:
            return [], {}, False
        # 收集每个成分的月度价;cutoff = ref_m(只用 ≤ ref_m 数据)
        ref_idx = months.index(ref_m)
        closes_dict: dict[str, list[float]] = {}
        ok_members: list[str] = []
        for k in new_members:
            tail: list[float] = []
            for mm in reversed(months[: ref_idx + 1]):
                c = me_close.get(mm, {}).get(k)
                if c is None:
                    break
                tail.append(c)
            if len(tail) >= 7:
                ok_members.append(k)
                closes_dict[k] = list(reversed(tail))
        if not ok_members:
            # 无动量可算太多 ⇒ 等权 + 把所有成员都纳进来
            new_w = equal_weights(new_members)
            return new_members, new_w, False
        try:
            new_w, _neut = momentum_tilt(ok_members, closes_dict)
        except Exception:
            new_w = equal_weights(ok_members)
        return new_members, new_w, True

    # ── 主循环:按"季度首月"换仓;季内 drift ───────────────────────────────
    for mi, m in enumerate(months):
        ds = month_to_days[m]
        d0 = ds[0]

        if mi == 0:
            # 首月(W50 起点):设初始权重 = mi=0 月底 mcap 选的 50 名(数据 < 7 月 ⇒ 1/N EW);
            # NAV 仍因"无前一日价可对"先记 1.0,然后到 mi=1 才正式漂移。
            # 等价于 t099:out_r 不含 12 月,首笔收益 = 次月(2016-01)按 2015-12 EW。
            init_members, init_w, _ = _select_and_weight(m)
            if init_w:
                members = init_members
                w = init_w
                first_weight_month = m
                last_log.append({"month": m, "is_rebalance": False, "n_members": len(members),
                                 "max_w": round(max(w.values()), 4), "turnover_oneway": 0.0})
            for d in ds:
                nav_by_date[d] = nav
            last_close_d = ds[-1]
            last_ci = idx[last_close_d]
            for k in universe:
                v = close_series[k][last_ci] if k in close_series else None
                if v is not None and v > 0:
                    prev_prices[k] = float(v)
            continue

        prev_m = months[mi - 1]
        m_5 = m[5:]
        is_reb_month = m_5 in QUARTER_STARTS

        # 1) 上一月最后一日 → 本月第一日的 drift(用 w)
        port_ret = 0.0
        if w:
            for k in w:
                wn = w.get(k, 0.0)
                if wn <= 0:
                    continue
                ci = idx[d0]
                v = close_series[k][ci] if k in close_series else None
                vp = prev_prices.get(k)
                if v is not None and vp and v > 0 and vp > 0:
                    port_ret += wn * (v / vp - 1)

        # 2) 季首月:重新选 + 重算权重
        cost_rate = 0.0
        if is_reb_month:
            new_members, new_w, used_mom = _select_and_weight(prev_m)
            if new_w:
                keys = set(new_w) | set(w)
                cost_rate = 0.5 * sum(abs(new_w.get(k, 0.0) - w.get(k, 0.0)) for k in keys) * COST_EQUITY
                members = new_members
                w = new_w
            # else: 仍沿用上一季度权重 + 0 换手

        # 3) 应用 day 0 收益 + 换手费
        nav *= (1 + port_ret - cost_rate)
        nav_by_date[d0] = nav
        # 更新 prev_prices 用今日价
        for k in (w if w else prev_prices.keys()):
            ci = idx[d0]
            v = close_series[k][ci] if k in close_series else None
            if v is not None and v > 0:
                prev_prices[k] = float(v)

        # 4) 本月剩余日:drift
        for di in range(1, len(ds)):
            d = ds[di]
            port_ret = 0.0
            if w:
                for k in w:
                    wn = w.get(k, 0.0)
                    if wn <= 0:
                        continue
                    ci = idx[d]
                    v = close_series[k][ci] if k in close_series else None
                    vp = prev_prices.get(k)
                    if v is not None and vp and v > 0 and vp > 0:
                        port_ret += wn * (v / vp - 1)
            nav *= (1 + port_ret)
            nav_by_date[d] = nav
            for k in (w if w else prev_prices.keys()):
                ci = idx[d]
                v = close_series[k][ci] if k in close_series else None
                if v is not None and v > 0:
                    prev_prices[k] = float(v)

        # 5) 记账
        if first_weight_month is None and w:
            first_weight_month = m
        last_log.append({
            "month": m,
            "is_rebalance": is_reb_month,
            "n_members": len(members),
            "max_w": round(max(w.values()), 4) if w else None,
            "turnover_oneway": round(cost_rate / COST_EQUITY if COST_EQUITY > 0 else 0.0, 4),
        })

    # ── 输出对齐 ────────────────────────────────────────────────────────────
    nav_arr = np.array([nav_by_date.get(d, np.nan) for d in days], dtype=float)
    ok = np.isfinite(nav_arr)
    n_skipped = int((~ok).sum())
    if ok.sum() < 2:
        raise RuntimeError("World50 NAV 序列空,检查 w50_daily/close 与 mcap 的覆盖")

    eq_ret = np.full_like(nav_arr, np.nan)
    eq_ret[1:] = nav_arr[1:] / nav_arr[:-1] - 1.0
    eq_ret[~ok] = np.nan
    valid_ret = eq_ret[1:][np.isfinite(eq_ret[1:])]
    valid_idx = np.where(ok)[0]
    out_days = [days[i] for i in valid_idx]
    out_ret = eq_ret[valid_idx][1:]  # returns aligned to out_days[1:]

    # NAV 整体评估(对世界 50 自身)
    yrs = len(valid_ret) / 365.25
    cagr_cal = float(nav_arr[ok][-1] ** (1 / yrs) - 1) if yrs > 0 else float("nan")
    dd = float((nav_arr[ok] / np.maximum.accumulate(nav_arr[ok]) - 1).min())
    daily_log = np.log(nav_arr[ok][1:] / nav_arr[ok][:-1])
    vol_ann = float(daily_log.std(ddof=1) * np.sqrt(365.25)) if len(daily_log) > 1 else float("nan")
    yrs_252 = len(valid_ret) / 252.0
    cagr_252 = float(nav_arr[ok][-1] ** (1 / yrs_252) - 1) if yrs_252 > 0 else float("nan")

    w50_meta = {
        "annualized_vol": round(vol_ann, 4),
        "max_dd": round(dd, 4),
        "cagr": round(cagr_cal, 4),                       # CAGR 365.25 日历
        "cagr_trading_days_252": round(cagr_252, 4),
        "window": (months[0], months[-1]),
        "n_days_in_window": int(ok.sum()),
        "n_skipped_days": n_skipped,
        "first_weight_month": first_weight_month,
        "rebalance_cadence": "quarter-end (04/07/10/01, see last_log.is_rebalance)",
        "last_log": last_log,
    }
    return out_days, out_ret, w50_meta


# ── 替换 s604 的 legs():股票腿从 ACWI 换成 World50 EW×Mom **日 NAV 回放** ──────────

def legs(research: str):
    daily_dir = Path(research) / "research" / "w50_daily"
    daily = json.loads((daily_dir / "close.json").read_text())
    dates = daily["dates"]

    # 1. equity 日 NAV 回放
    t0 = time.time()
    eq_days, eq_rets, w50_meta = world50_daily_nav(daily_dir, START, END)
    print(f"[w50] 日 NAV 回放 done {time.time()-t0:.1f}s "
          f"window={w50_meta['window']} days={w50_meta['n_days_in_window']} "
          f"vol_ann={w50_meta['annualized_vol']:.2%} max_dd={w50_meta['max_dd']:.2%} "
          f"cagr_s604={w50_meta['cagr']:.2%}", flush=True)

    # 1b. equity 月度版(同一份 w50_daily + 同一套规则,只动月度)—— 跟日版对比
    t0 = time.time()
    monthly = world50_monthly_nav(daily_dir, START, END)
    if monthly.get("stats"):
        ms = monthly["stats"]
        print(f"[w50] 月度 EW×Mom (t099.run_arm) done {time.time()-t0:.1f}s "
              f"window={ms['window']} n_months={ms['n_months']} "
              f"vol_ann={ms['annualized_vol']:.2%} max_dd={ms['max_dd']:.2%} cagr={ms['cagr']:.2%}", flush=True)
    w50_meta["monthly_stats"] = monthly.get("stats")

    # 2. Crypto leg(s604 一样)—— H / X1V / X1V_fric
    btc = np.array([x if x else np.nan for x in daily["close"]["BTC"]], dtype=float)
    ok_btc = np.isfinite(btc)
    bd = [d for d, o in zip(dates, ok_btc) if o]
    bc = btc[ok_btc]
    ex = s602.exposures(bc)
    nav_crypto = {"H": np.cumprod(1 + s602.rets(bc, ex["H"])),
                  "X1V": np.cumprod(1 + s602.rets(bc, ex["X1V"])),
                  "X1V_fric": np.cumprod(1 + s602.rets(bc, ex["X1V"], True))}
    crypto_by_d = {k: dict(zip(bd, v)) for k, v in nav_crypto.items()}

    # 3. Gold 腿 —— 仍用 XAUUSD 日收盘价(代表黄金资产)
    xau = daily["close"]["XAUUSD"]

    # 4. 取交集日期(三腿 + START/END 窗口 + XAU 不空)
    common_dates = [d for d in eq_days if d in crypto_by_d["H"]
                    and xau[dates.index(d)] is not None and xau[dates.index(d)] > 0]
    if not common_dates:
        raise RuntimeError("三腿公共交易日为空;检查 w50_daily XAU/BTC 的覆盖")
    out = {}
    for k in nav_crypto:
        # crypto NAV 序列对齐 common_dates
        c_valid = np.array([crypto_by_d[k][d] for d in common_dates])
        x_valid = np.array([xau[dates.index(d)] for d in common_dates], dtype=float)
        # equity NAV:用 eq_dates 与 eq_rets → 在 common_dates 上重建
        # 简化:eq_rets 是按 eq_days 顺序的;同一日期的 equity NAV = 累计复利
        # 先按 eq_days 求 NAV,再按 common_dates 取相应 NAV(同一日期)
        eq_nav = np.concatenate([[1.0], np.cumprod(1 + eq_rets)])  # len = len(eq_days)
        eq_by_d = dict(zip(eq_days, eq_nav))
        # 取 common_dates 上的 equity NAV(两端都有的日期之间才能算 return)
        e_valid = np.array([eq_by_d[d] for d in common_dates])
        # 日收益 = NAV[i+1] / NAV[i] − 1
        c_r = c_valid[1:] / c_valid[:-1] - 1
        e_r = e_valid[1:] / e_valid[:-1] - 1
        x_r = x_valid[1:] / x_valid[:-1] - 1
        R = np.column_stack([c_r, e_r, x_r])
        out[k] = R
    return common_dates, out, w50_meta


# ── 复用 s604 的 main 结构 ────────────────────────────────────────────────────

def main(research: str, out_path: str):
    common, legs_R, w50_meta = legs(research)
    rng = np.random.default_rng(SEED)
    n = len(next(iter(legs_R.values())))
    idx = stationary_bootstrap_index(n, BLOCK, N_PATHS, rng)[:, :DAYS]
    gs = grid()
    print(f"[grid] 共 {len(gs)} 个配比(crypto×equity×gold),黄金网格 0–40% 步长 {GOLD_STEP};", flush=True)
    print(f"[boot] idx 矩阵 ({N_PATHS}×{min(DAYS, n)}) base_seed={SEED} block={BLOCK}", flush=True)

    res = {
        "days": [common[0], common[-1], len(common)],
        "gold_grid_step": GOLD_STEP,
        "grid_size": len(gs),
        "w50_meta": w50_meta,
        "fixed_points": {},
        "variants": {},
    }

    fixed = fixed_points()
    print("[fixed] T25 (30/30/20/20), T35 (40/40/20/0);各给 H / X1V / X1V_fric", flush=True)

    for k, R in legs_R.items():
        Rp = R[idx]
        rows = []
        for w in gs:
            cg, dd = stats(portfolio(Rp, w))
            hc, hd = stats(portfolio(R[None, :, :], w))
            rows.append({"crypto": w[0], "equity": w[1], "gold": w[2], "cash": round(1 - sum(w), 2),
                         "cagr_median": float(np.median(cg)), "cagr_p05": float(np.percentile(cg, 5)),
                         "dd_median": float(np.median(dd)), "dd_p05_worst": float(np.percentile(dd, 5)),
                         "hist_cagr": float(hc[0]), "hist_dd": float(hd[0])})
        front = {}
        for cap in (-0.25, -0.35, -0.45):
            ok = [r for r in rows if r["dd_p05_worst"] >= cap]
            front[str(cap)] = max(ok, key=lambda r: r["cagr_median"]) if ok else None
        res["variants"][k] = {"rows": rows, "frontier": front}
        # fixed points
        fp = {}
        for c, e, g, name in fixed:
            cagr_b, dd_b = stats(portfolio(Rp, (c, e, g)))
            cagr_h, dd_h = stats(portfolio(R[None, :, :], (c, e, g)))
            fp[name] = {
                "crypto": c, "equity": e, "gold": g, "cash": round(1 - c - e - g, 2),
                "cagr_median": float(np.median(cagr_b)), "cagr_p05": float(np.percentile(cagr_b, 5)),
                "dd_median": float(np.median(dd_b)), "dd_p05_worst": float(np.percentile(dd_b, 5)),
                "hist_cagr": float(cagr_h[0]), "hist_dd": float(dd_h[0]),
            }
        res["fixed_points"][k] = fp
        print(k, "done", flush=True)

    Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    r = main(sys.argv[1], sys.argv[2])
    print("days", r["days"], "grid_size", r["grid_size"])
    for k, v in r["variants"].items():
        print("==", k)
        for cap, f in v["frontier"].items():
            if f:
                print(f"  worst5%DD ≥ {cap}: crypto {f['crypto']:.0%} eq {f['equity']:.0%} gold {f['gold']:.0%} cash {f['cash']:.0%} | "
                      f"cagr med {f['cagr_median']*100:.1f}% p05 {f['cagr_p05']*100:.1f}% | dd med {f['dd_median']*100:.1f}% worst5 {f['dd_p05_worst']*100:.1f}% | hist {f['hist_cagr']*100:.1f}% / {f['hist_dd']*100:.1f}%")
    print("== fixed points (T25 = 30/30/20/20, T35 = 40/40/20/0)")
    for k, fp in r["fixed_points"].items():
        for name, row in fp.items():
            print(f"  {k} {name}: cagr med {row['cagr_median']*100:.1f}% p05 {row['cagr_p05']*100:.1f}% dd med {row['dd_median']*100:.1f}% ddp5 {row['dd_p05_worst']*100:.1f}% hist {row['hist_cagr']*100:.1f}%/{row['hist_dd']*100:.1f}%")
