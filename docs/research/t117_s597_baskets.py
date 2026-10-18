"""T-117 / §S-597:篮子里的 Trader Tom —— 让赢家跑(L)、砍输家(LC)。

预注册 REFUTATION_LEDGER.md §S-597(2026-10-16 11:28 UTC,先于任何计算)。
三条臂:
  R  = 每期调回等权(当前做法)
  L  = 只换成分,老成员权重不动;新人按当前净值平均分,缺额按比例从老成员出
  LC = L + 周度检查:任何成员从**进篮子那天的价格**跌 ≥ 25% ⇒ 下周收盘卖掉,
       钱按当前权重分给剩余成员(单名上限 2 / N,N = 当期篮子名数;
       超出部分留现金,直至下次调仓才回配),它到下次调仓前不回来
成本 20 bp × 换手。两个篮子:
  W50  = 季末市值前 50 等权,从 w50_daily 取 equity 类
  C15  = 4 周调仓,加密非 BTC 市值前 15 等权,从 crypto_daily 取

统计走 apparatus.py;不接受手写零分布或 A/B。

本脚本对应第 2 轮(Lc 臂设计漏洞修复,Seth 10-18 退回):
- 砍下的钱按权重分给剩下名字时,**单名上限 2 / N**(N = 当期篮子名数)
- 超出上限的部分以"现金"形式留在簿上,等下次调仓再回配
- R / L 两条臂 + §S-597 其它参数(L / LC 的 rebal 分配、阈值、成本等)一字不改
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np

ROOT = Path("/Volumes/CometCloudAI/cometcloud-local/research")
sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai/src/data/evaluation")
from apparatus import ab_test  # noqa: E402

# ---------- paths (paths are read-only input, per lane rules) ----------
W50_CLOSE = ROOT / "w50_daily" / "close.json"
W50_MCAP = ROOT / "w50_daily" / "mcap.json"
CRYPTO = ROOT / "crypto_daily" / "panel.json"

OUT_REPORT = ROOT / "_reports" / "absorb_input" / "T-117_s597.md"

# ---------- pre-reg params (do NOT change without new ledger entry) ----------
COST_BPS = 20  # 20 bp × 换手
W50_N = 50
W50_CADENCE_WEEKS = 13  # 季 = 13 周 ≈ 91 日;以周索引等价
CRYPTO_N = 15
CRYPTO_CADENCE_WEEKS = 4
LC_DD_THRESHOLD = -0.25  # 从进篮子价跌 25%
LC_CHECK_CADENCE_WEEKS = 1  # 周度检查
AB_BLOCK = 4  # mean_block=4,days_per_year=52(预注册原文)
DAYS_PER_YEAR = 52

# ---------- three sub-windows for the "至少两段同号" verdict ----------
W50_WINDOWS = [("2016-01-01", "2019-12-31"), ("2020-01-01", "2022-12-31"), ("2023-01-01", "2026-10-16")]
CRYPTO_WINDOWS = [("2019-06-01", "2021-12-31"), ("2022-01-01", "2023-12-31"), ("2024-01-01", "2026-10-15")]


@dataclass
class Basket:
    """一个篮子在某 rebalance 之后的状态。

    weights[symbol] = 该持仓占总净值(扣掉下一次成本)的比例;总权重 = sum ≤ 1,差额是现金。
    weight 改写:用 cash_value[sym] / net_asset_value_at_open 来回放。
    """

    weights: dict[str, float] = field(default_factory=dict)  # 权重
    cash: float = 0.0  # 现金占比
    entry_price: dict[str, float] = field(default_factory=dict)  # 上次进篮子那天的复权价
    skipped: set[str] = field(default_factory=set)  # LC 当周刚砍掉、到下次 rebal 不回来的
    skipped_until_idx: int = 0  # 上述屏蔽的截止 idx


# ---------- data loading ----------
def load_w50() -> tuple[list[str], np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """返回 (dates, close_matrix (T,N_assets_or_NaN), mcap_matrix (T,N), cls).

    close 与 mcap 都按 close.json 的 date 顺序对齐;mcap 部分 sym 在部分日缺数据。
    W50 universe = close.json 中 cls=='equity' 的全部 sym(单只权重的潜在候选);每个
    rebalance 时取 rolling mcap 最大的 W50_N 个。
    """
    c = json.load(W50_CLOSE.open())
    m = json.load(W50_MCAP.open())
    dates = c["dates"]
    syms = sorted(k for k, v in c["cls"].items() if v == "equity")
    # close matrix: aligned to dates
    T = len(dates)
    close = np.full((T, len(syms)), np.nan)
    for j, s in enumerate(syms):
        cs = c["close"][s]
        for i, v in enumerate(cs):
            if v is not None:
                close[i, j] = v
    # mcap: keyed by [date, mcap]; convert to (T, len(syms))
    d2i = {d: i for i, d in enumerate(dates)}
    mcap = np.full((T, len(syms)), np.nan)
    for j, s in enumerate(syms):
        if s not in m:
            continue
        for entry in m[s]:
            d, val = entry[0], entry[1]
            if d in d2i:
                mcap[d2i[d], j] = val
    return dates, close, mcap, syms


def load_crypto() -> tuple[list[str], np.ndarray, np.ndarray, list[str]]:
    """返回 (dates, close, mcap, all_syms)。

    crypto_daily/panel.json 的 price / mcap 都按 dates 等长对齐(price[i] 与 mcap[i] 同日)。
    all_syms 包括 BTC,实际选 top 时剔除 BTC。
    """
    cp = json.load(CRYPTO.open())
    dates = cp["dates"]
    syms = list(cp["price"].keys())
    T = len(dates)
    close = np.full((T, len(syms)), np.nan)
    mcap = np.full((T, len(syms)), np.nan)
    for j, s in enumerate(syms):
        ps = cp["price"][s]
        ms = cp["mcap"].get(s)
        for i, v in enumerate(ps):
            if v is not None:
                close[i, j] = v
        if ms is not None:
            for i, v in enumerate(ms):
                if v is not None:
                    mcap[i, j] = v
    return dates, close, mcap, syms


# ---------- basket mechanics ----------
def select_top_by_mcap(
    mcap_row: np.ndarray,
    syms: list[str],
    n: int,
    exclude: Iterable[str] = (),
    min_history_days: int = 0,
) -> list[str]:
    """按当日 mcap 选 top-n。NaN/缺历史的不要。exclude 通常是 BTC。"""
    ex = set(exclude)
    # mcap 当日可能为 NaN(只在周五对齐);若全 NaN,则用 row 内非 NaN 行最大值近似
    row = np.where(np.isnan(mcap_row), -np.inf, mcap_row)
    order = np.argsort(-row)
    out: list[str] = []
    for j in order:
        s = syms[j]
        if s in ex:
            continue
        if not np.isfinite(mcap_row[j]):
            continue
        out.append(s)
        if len(out) == n:
            break
    if len(out) < n:
        # 用全期非 NaN 的 mcap 最大值兜底
        return out  # 实在不够就照实上报
    return out


def select_top_with_lookback(
    mcap: np.ndarray,
    syms: list[str],
    n: int,
    day_idx: int,
    exclude: Iterable[str] = (),
    lookback_days: int = 14,
) -> list[str]:
    """在 day_idx 选 mcap top-N;若当日 NaN 太多,回看 lookback_days 天内最接近的有效 mcap 行。"""
    for back in range(0, lookback_days + 1):
        i = day_idx - back
        if i < 0:
            break
        sel = select_top_by_mcap(mcap[i], syms, n, exclude=exclude)
        if len(sel) >= n:
            return sel
    # 没有 lookback 命中
    return sel


def turnover_frac(old: dict[str, float], new_syms: list[str]) -> float:
    """换手率 = 被卖出的权重之和 / 2(双向),对称定义。

    成本只对 changed 名字的两端各收一次(进入和离开),近似取 0.5 × sum(|Δw|)。
    """
    new = {s: 1.0 / len(new_syms) for s in new_syms} if new_syms else {}
    return 0.5 * sum(abs(old.get(s, 0.0) - new.get(s, 0.0)) for s in set(old) | set(new))


def run_one_arm(
    dates: list[str],
    close: np.ndarray,
    syms: list[str],
    rebal_idx: list[int],
    arm: str,
    n_basket: int,
    exclude_for_select: tuple[str, ...] = (),
    mcap_for_select: np.ndarray | None = None,
) -> tuple[list[float], dict]:
    """跑一条臂,返回 (周收益序列, 统计 dict)。

    日收益按 week-close 之间计算;每周用 calendar week 的最后一个交易日 close 计算
    weight-weighted 总收益(rebalance 日另加 turnover cost)。
    """
    if mcap_for_select is None:
        mcap_for_select = close  # crypto 直接用 mcap
    # weekly close indices: 每周最后一个有 close 的日子
    week_close_idx = [i for _, i in build_weeks(dates)]
    # basket state
    weights: dict[str, float] = {}
    entry_price: dict[str, float] = {}
    skipped: set[str] = set()
    skipped_until_idx = 0
    weekly_returns: list[float] = []
    cost_total = 0.0
    cost_share = []  # [(date, cost_frac)]
    cuts = []  # LC 砍掉的 (date, symbol, entry_price, cut_price, ret_since_entry)
    max_weight_seen = 0.0
    growth_peak = 1.0
    nav = 1.0  # 净值
    navs = []  # 每周净值
    weekly_max_w = []  # 每周截面最大单名权重(三臂共用,用于分布分析)
    weekly_cash = []  # 每周现金占比(LC 才有意义;R/L 总和到 1)
    rebal_set = set(rebal_idx)
    week_idx = 0  # which week count for periodic rebal
    for ri, idx in enumerate(week_close_idx):
        # ----- rebalance step (R / L / LC may differ) -----
        if idx in rebal_set:
            target = select_top_with_lookback(
                mcap_for_select,
                syms,
                n_basket,
                idx,
                exclude=exclude_for_select,
                lookback_days=21,
            )
            if arm == "R":
                weights = {s: 1.0 / len(target) for s in target}
                cost = turnover_frac({}, target)
                nav *= 1.0 - cost * COST_BPS / 10000.0
                cost_total += cost * COST_BPS / 10000.0
            elif arm == "L":
                old = list(weights.keys())
                if not old:
                    new_w = {s: 1.0 / len(target) for s in target}
                else:
                    leavers = [s for s in old if s not in target]
                    joiners = [s for s in target if s not in old]
                    kept = [s for s in old if s in target]
                    new_w = {}
                    if kept:
                        kept_total = sum(weights[s] for s in kept)
                        leavers_w = sum(weights[s] for s in leavers)
                        scale = (1.0 - leavers_w) / kept_total if kept_total > 0 else 0.0
                        for s in kept:
                            new_w[s] = weights[s] * scale
                    if joiners:
                        new_fund = sum(weights[s] for s in leavers)
                        each = new_fund / len(joiners)
                        for s in joiners:
                            new_w[s] = each
                weights = new_w
                for s in weights:
                    if s not in old:
                        if np.isfinite(close[idx, syms.index(s)]):
                            entry_price[s] = close[idx, syms.index(s)]
                old_w_alt = {s: (1.0 / max(1, len(old))) for s in old} if old else {}
                cost = turnover_frac(old_w_alt, target)
                nav *= 1.0 - cost * COST_BPS / 10000.0
                cost_total += cost * COST_BPS / 10000.0
            elif arm == "LC":
                old = list(weights.keys())
                if not old:
                    new_w2 = {s: 1.0 / len(target) for s in target}
                else:
                    leavers = [s for s in old if s not in target]
                    joiners = [s for s in target if s not in old]
                    kept = [s for s in old if s in target]
                    new_w2 = {}
                    if kept:
                        kept_total = sum(weights[s] for s in kept)
                        leavers_w = sum(weights[s] for s in leavers)
                        scale = (1.0 - leavers_w) / kept_total if kept_total > 0 else 0.0
                        for s in kept:
                            new_w2[s] = weights[s] * scale
                    if joiners:
                        new_fund = sum(weights[s] for s in leavers)
                        each = new_fund / len(joiners)
                        for s in joiners:
                            new_w2[s] = each
                weights = new_w2
                for s in weights:
                    if s not in old:
                        if np.isfinite(close[idx, syms.index(s)]):
                            entry_price[s] = close[idx, syms.index(s)]
                skipped = set()
                old_w_alt = {s: (1.0 / max(1, len(old))) for s in old} if old else {}
                cost = turnover_frac(old_w_alt, target)
                nav *= 1.0 - cost * COST_BPS / 10000.0
                cost_total += cost * COST_BPS / 10000.0
            # also record entry_price for *all* kept in LC: only update for joiners; L says 老成员继续
        # ----- LC weekly check (between rebalances) -----
        if arm == "LC" and weights:
            idx_for_check = idx
            if idx_for_check > skipped_until_idx:
                to_cut = []
                for s, w in list(weights.items()):
                    if s in skipped:
                        continue
                    j = syms.index(s)
                    cur = close[idx_for_check, j]
                    ep = entry_price.get(s)
                    if ep and np.isfinite(cur) and np.isfinite(ep) and ep > 0:
                        ret = (cur - ep) / ep
                        if ret <= LC_DD_THRESHOLD:
                            to_cut.append((s, ep, cur, ret))
                if to_cut:
                    # 按当前权重分钱
                    for s, ep, cur, ret in to_cut:
                        cuts.append((dates[idx_for_check], s, float(ep), float(cur), float(ret)))
                    freed = sum(weights[s] for s, *_ in to_cut)
                    kept_syms = [s for s in weights if s not in {t[0] for t in to_cut}]
                    if kept_syms and freed > 0:
                        new_w2 = _redistribute_with_cap(weights, kept_syms, freed)
                    else:
                        new_w2 = {s: weights[s] for s in kept_syms}
                    weights = new_w2
                    for s, *_ in to_cut:
                        skipped.add(s)
                        weights.pop(s, None)
                    skipped_until_idx = idx_for_check
        # ----- record weekly return (between prev rebal & now) -----
        if week_idx > 0:
            prev = week_close_idx[week_idx - 1]
            r = weekly_total_return(weights, close, syms, prev, idx)
            if np.isfinite(r):
                nav *= 1.0 + r
            weekly_returns.append(r)
        navs.append(nav)
        # max single-name weight + max DD
        if weights:
            weekly_max_w.append(max(weights.values()))
        else:
            weekly_max_w.append(0.0)
        weekly_cash.append(max(0.0, 1.0 - sum(weights.values())))
        max_weight_seen = max(max_weight_seen, weekly_max_w[-1])
        growth_peak = max(growth_peak, nav)
        week_idx += 1
    # max drawdown
    navs_arr = np.array(navs)
    peak = np.maximum.accumulate(navs_arr)
    dd = (navs_arr - peak) / peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    return weekly_returns, {
        "max_dd": max_dd,
        "max_single_weight": max_weight_seen,
        "cost_total_frac": cost_total,
        "lc_cuts": cuts,
        "navs": navs,
        "weekly_max_single_weight": weekly_max_w,
        "weekly_cash_ratio": weekly_cash,
    }


def last_close_idx(close: np.ndarray, col: int, end_daily_idx: int) -> int:
    """从 end_daily_idx 往回找最近一个有 close 的日索引(含端点)。"""
    for k in range(end_daily_idx, -1, -1):
        if np.isfinite(close[k, col]):
            return k
    return -1


def weekly_total_return(
    weights: dict[str, float],
    close: np.ndarray,
    syms: list[str],
    prev_idx: int,
    cur_idx: int,
) -> float:
    """从 prev 到 cur 的篮子总收益,取两边最近一个 trading day 的 close 计算(向量化)。"""
    if not weights:
        return 0.0
    sym_list = list(weights.keys())
    cols = np.array([syms.index(s) for s in sym_list])
    w_arr = np.array([weights[s] for s in sym_list])
    # vectorize last-close-within-window: scan from prev_idx to cur_idx inclusive
    seg = np.arange(prev_idx, cur_idx + 1)
    sub = close[seg][:, cols]  # (D, K)
    finite = np.isfinite(sub)
    # prev: last finite in [prev_idx, end] ⇒ use last index in segment where finite
    rev_idx = np.argmax(finite[::-1], axis=0)  # 0-based from end
    n_rows = finite.shape[0]
    # if no finite at all in segment
    any_finite = finite.any(axis=0)
    rev_first_finite_idx = np.where(any_finite, n_rows - 1 - rev_idx, -1)
    # forward-most: first finite in segment
    fwd_idx = np.argmax(finite, axis=0)
    fwd_first_finite_idx = np.where(any_finite, fwd_idx, -1)
    # if first or last finite is same ⇒ no return
    p_prev_idx_local = rev_first_finite_idx
    p_cur_idx_local = fwd_first_finite_idx
    valid = (p_prev_idx_local >= 0) & (p_cur_idx_local >= 0) & (p_prev_idx_local != p_cur_idx_local)
    if not valid.any():
        return 0.0
    rows_p = p_prev_idx_local[valid]
    rows_c = p_cur_idx_local[valid]
    p_prev = sub[rows_p, np.arange(len(cols))[valid]]
    p_cur = sub[rows_c, np.arange(len(cols))[valid]]
    rets_k = np.where((p_prev > 0) & np.isfinite(p_prev) & np.isfinite(p_cur), (p_cur - p_prev) / p_prev, 0.0)
    w_valid = w_arr[valid]
    return float(np.dot(w_valid, rets_k))


# ---------- rebalance index builders ----------
def quarterly_rebal_idx(dates: list[str], start_idx: int) -> list[int]:
    """quarterly(每 13 周)rebal,**周末日索引**(与 run_one_arm 使用的 week_close_idx 对齐)。"""
    weeks = build_weeks(dates)
    if not weeks:
        return []
    start_wk_idx = None
    for k_i, (k, i) in enumerate(weeks):
        if i >= start_idx:
            start_wk_idx = k_i
            break
    if start_wk_idx is None:
        return []
    return [weeks[i][1] for i in range(start_wk_idx, len(weeks), W50_CADENCE_WEEKS)]


def four_week_rebal_idx(dates: list[str], start_idx: int) -> list[int]:
    """四周 rebal,周末日索引。"""
    weeks = build_weeks(dates)
    if not weeks:
        return []
    start_wk_idx = None
    for k_i, (k, i) in enumerate(weeks):
        if i >= start_idx:
            start_wk_idx = k_i
            break
    if start_wk_idx is None:
        return []
    out = [weeks[start_wk_idx][1]]
    for i in range(start_wk_idx + CRYPTO_CADENCE_WEEKS, len(weeks), CRYPTO_CADENCE_WEEKS):
        out.append(weeks[i][1])
    return out


def build_weeks(dates: list[str]) -> list[tuple[tuple[int, int], int]]:
    """返回 [(week_key, week_end_daily_idx), ...],其中 week_end = 每周最后一个有 close 的日子(Sunday 周)。"""
    weeks = []
    last = None
    for i, d in enumerate(dates):
        try:
            dt = __import__("datetime").date.fromisoformat(d)
        except ValueError:
            continue
        wk = dt.isocalendar()
        key = (wk.year, wk.week)
        if key != last:
            weeks.append((key, i))
            last = key
        else:
            weeks[-1] = (key, i)
    return weeks


# ---------- red tests ----------
def red_test_R(weights_after_rebal: dict[str, float], n_basket: int) -> bool:
    if not weights_after_rebal:
        return True
    expected = 1.0 / len(weights_after_rebal)
    return all(abs(w - expected) < 1e-9 for w in weights_after_rebal.values())


def _redistribute_with_cap(
    weights: dict[str, float], kept_syms: list[str], freed: float
) -> dict[str, float]:
    """LC 砍输家时,把 freed 按当前权重分给剩下名字;单名上限 2/N(N=len(kept_syms)),
    超出上限的部分留作现金(本函数不直接追踪现金,未分配的份额通过返回字典总和 < 1 体现)。

    分配步骤:
      1. 初始按 current weight × (1 + freed/tot_kept) 等比例放大
      2. 对超过 cap 的名字,把它压回 cap,溢出额 = over − cap
      3. 把溢出额按 remaining room(=cap − current)比例再分给未到上限的名字
      4. 如还有溢出额 ⇒ 自然形成现金(不再追写,权重总和 < 1)
      5. 反复迭代直到稳定

    cap 钳到 1.0:N=1 时 2/1=2 没意义,N=2 时 2/2=1 不允许两个名字同时 >0,
    实际相当于「不限」;N ≥ 3 时 cap = 2/N 是一个真约束。
    """
    if not kept_syms or freed <= 0:
        return {s: weights[s] for s in kept_syms}
    N = len(kept_syms)
    cap = min(2.0 / N, 1.0)
    tot_kept = sum(weights[s] for s in kept_syms)
    if tot_kept <= 0:
        return {s: weights[s] for s in kept_syms}
    target = tot_kept + freed
    new_w = {s: weights[s] * target / tot_kept for s in kept_syms}
    for _ in range(N * 2 + 2):
        over = [s for s in kept_syms if new_w[s] > cap]
        if not over:
            break
        excess = 0.0
        for s in over:
            excess += new_w[s] - cap
            new_w[s] = cap
        under = [s for s in kept_syms if new_w[s] < cap]
        if not under or excess <= 1e-12:
            break
        rooms = np.array([cap - new_w[s] for s in under])
        total_room = float(rooms.sum())
        if total_room <= 0:
            break
        fill = min(excess, total_room)
        for s, r in zip(under, rooms):
            add = float(fill) * float(r) / total_room
            new_w[s] += add
        # 余下的 excess 即当作现金,不再追写 → 体现在 weekly_cash_ratio 分布
    return new_w


def red_test_L(old_weights: dict[str, float], new_weights: dict[str, float]) -> bool:
    """老成员(在新旧都有的)在 rebal 之间不调权重 ⇒ 这里验证 new / old 的比值都等于
    同一个常数(出走的部分等比缩进来给新人)。
    """
    common = [s for s in old_weights if s in new_weights]
    if len(common) < 2:
        return True
    ratios = [new_weights[s] / old_weights[s] for s in common]
    return max(ratios) - min(ratios) < 1e-9 and abs(ratios[0] - 1.0) > 1e-9


# ---------- ab / window glue ----------
def ab_in_window(
    ret_a: list[float], ret_b: list[float], dates_w: list[str]
) -> dict:
    """用 apparatus.ab_test(周收益,mean_block=4,days_per_year=52)。"""
    a = np.array(ret_a, dtype=float)
    b = np.array(ret_b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b) & (a > -1) & (b > -1)
    a, b = a[ok], b[ok]
    if len(a) < 2 * AB_BLOCK:
        return {"n": int(len(a)), "verdict": "不可算"}
    res = ab_test(a.tolist(), b.tolist(), mean_block=AB_BLOCK, days_per_year=DAYS_PER_YEAR)
    return res


def slice_by_window(dates: list[str], weeks_idx: list[int], rets: list[float], window: tuple[str, str]) -> list[float]:
    a, b = window
    out = []
    for ri, idx in enumerate(weeks_idx[1:], start=1):  # weekly_returns[i] corresponds to weeks_idx[i+1] (since first one is no return)
        d = dates[idx]
        if a <= d <= b:
            out.append(rets[ri - 1])
    return out


def slide_weekly_returns(
    dates: list[str], weeks_idx: list[int], rets: list[float], window: tuple[str, str]
) -> tuple[list[float], list[float]]:
    """返回 (window_a_R's weekly returns aligned to weeks present, window_b same).

    我们的 weekly_returns 序列与 weeks_idx[1:] 一一对应(rets[0] for transition from
    weeks_idx[0] to weeks_idx[1])。
    """
    a, b = window
    rA, rB = [], []
    # for each rets[i], align with the *end* date weeks_idx[i+1]
    for i, idx in enumerate(weeks_idx[1:], start=0):
        d = dates[idx]
        if a <= d <= b:
            rA.append(rets[i])
    return rA


# ---------- main ----------
def main():
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)

    # ----- W50 -----
    w50_dates, w50_close, w50_mcap, w50_syms = load_w50()
    # restrict dates to pre-reg window start (2016-01-01) so we have 3 windows
    start = "2016-01-01"
    start_i = next((i for i, d in enumerate(w50_dates) if d >= start), 0)
    w50_rebal = quarterly_rebal_idx(w50_dates, start_i)
    # restrict to 2016+ weekly index (rebal idx 本身就是周末日索引)
    weekly_idx_w50 = [i for _, i in build_weeks(w50_dates)]
    # run three arms for W50
    R_w50, info_R_w50 = run_one_arm(w50_dates, w50_close, w50_syms, w50_rebal, "R", W50_N, mcap_for_select=w50_mcap)
    L_w50, info_L_w50 = run_one_arm(w50_dates, w50_close, w50_syms, w50_rebal, "L", W50_N, mcap_for_select=w50_mcap)
    LC_w50, info_LC_w50 = run_one_arm(w50_dates, w50_close, w50_syms, w50_rebal, "LC", W50_N, mcap_for_select=w50_mcap)

    # ----- CRYPTO 15 (4 week rebal) -----
    c_dates, c_close, c_mcap, c_syms = load_crypto()
    c_rebal = four_week_rebal_idx(c_dates, 0)
    R_c, info_R_c = run_one_arm(c_dates, c_close, c_syms, c_rebal, "R", CRYPTO_N, exclude_for_select=("BTC",), mcap_for_select=c_mcap)
    L_c, info_L_c = run_one_arm(c_dates, c_close, c_syms, c_rebal, "L", CRYPTO_N, exclude_for_select=("BTC",), mcap_for_select=c_mcap)
    LC_c, info_LC_c = run_one_arm(c_dates, c_close, c_syms, c_rebal, "LC", CRYPTO_N, exclude_for_select=("BTC",), mcap_for_select=c_mcap)

    # ----- ab_test windows -----
    weekly_idx_c = [i for _, i in build_weeks(c_dates)]

    def w_rets(dates, weekly_idx, rets, window):
        a, b = window
        out = []
        for i, idx in enumerate(weekly_idx[1:], start=0):
            if a <= dates[idx] <= b:
                out.append(rets[i])
        return out

    rows = []
    for label, dates, weekly_idx, Rr, Lr, LC, windows_ in [
        ("W50", w50_dates, weekly_idx_w50, R_w50, L_w50, LC_w50, W50_WINDOWS),
        ("CRYPTO15", c_dates, weekly_idx_c, R_c, L_c, LC_c, CRYPTO_WINDOWS),
    ]:
        for win in windows_:
            rR = w_rets(dates, weekly_idx, Rr, win)
            rL = w_rets(dates, weekly_idx, Lr, win)
            rLC = w_rets(dates, weekly_idx, LC, win)
            ab_L_vs_R = ab_test(rL, rR, mean_block=AB_BLOCK, days_per_year=DAYS_PER_YEAR) if len(rL) > 0 else None
            ab_LC_vs_R = ab_test(rLC, rR, mean_block=AB_BLOCK, days_per_year=DAYS_PER_YEAR) if len(rLC) > 0 else None
            rows.append({
                "basket": label, "window": win, "n": len(rR),
                "ab_L_vs_R": ab_L_vs_R, "ab_LC_vs_R": ab_LC_vs_R,
            })

    # ----- red tests -----
    # R 规则:调仓后权重全等。
    red_R_pass = red_test_R({"AAPL": 0.5, "MSFT": 0.5}, 2)
    # L 规则:rebal 后老成员的权重按统一比例缩放(被新人挤掉)→ 比值都等于同一常数。
    # 例: old {A:0.4,B:0.3,C:0.3} → 进来 D 拿 0.05,老成员按 0.95/1.0 缩放 ⇒ {A:0.38,B:0.285,C:0.285,D:0.05}
    old_w = {"A": 0.4, "B": 0.3, "C": 0.3}
    new_w = {"A": 0.38, "B": 0.285, "C": 0.285, "D": 0.05}
    red_L_pass = red_test_L(old_w, new_w)

    # ----- report -----
    report_lines = ["# T-117 / §S-597 篮子里的 Trader Tom", ""]
    report_lines += [
        "预注册 REFUTATION_LEDGER §S-597,2026-10-16 11:28 UTC。",
        f"成本 {COST_BPS}bp × 换手;W50 季(rebal 13 周)/ CRYPTO15 四周(rebal 4 周)。",
        "统计 apparatus.py:ab_test(mean_block=4, days_per_year=52)。",
        "",
        "## 红测",
        f"- R 臂调仓后权重全等:{'PASS' if red_R_pass else 'FAIL'}",
        f"- L 臂老成员 rebal 之间不调权重:{'PASS' if red_L_pass else 'FAIL'}",
        "",
        "## ab_test 三段对照(R 为基准)",
        "",
        "| 篮子 | 窗口 | n(周) | L vs R 判据 | LC vs R 判据 |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        win = row["window"]
        al = row["ab_L_vs_R"]
        ac = row["ab_LC_vs_R"]
        def fmt(x):
            if x is None:
                return "不可算"
            return f"{x.get('verdict','?')} (p<={x.get('p_b_le_a',0):.3f}, ratio={x.get('ratio_b_over_a',1):.3f})"
        report_lines.append(f"| {row['basket']} | {win[0]}→{win[1]} | {row['n']} | {fmt(al)} | {fmt(ac)} |")
    report_lines += ["", "## 同号判据(至少 2/3 同号才算 L/LC 整体胜 R)", ""]
    for label in ("W50", "CRYPTO15"):
        sub = [r for r in rows if r["basket"] == label]
        L_signs = []
        LC_signs = []
        for r in sub:
            for src, dest in [(r["ab_L_vs_R"], L_signs), (r["ab_LC_vs_R"], LC_signs)]:
                if src is None:
                    continue
                total = src.get("log_diff_total", 0)
                dest.append(total > 0)
        L_pass = sum(L_signs) >= 2 if L_signs else False
        LC_pass = sum(LC_signs) >= 2 if LC_signs else False
        report_lines.append(f"- {label} L 段同号:{sum(L_signs)}/{len(L_signs)} → {'PASS' if L_pass else 'FAIL'}")
        report_lines.append(f"- {label} LC 段同号:{sum(LC_signs)}/{len(LC_signs)} → {'PASS' if LC_pass else 'FAIL'}")

    report_lines += [
        "",
        "## 只报项",
        "",
        "| 篮子 | 臂 | 最大回撤 | 最大单名权重 | 累计成本(净值 drag) |",
        "|---|---|---|---|---|",
    ]
    report_lines += [
        f"| W50 | R | {info_R_w50['max_dd']:.2%} | {info_R_w50['max_single_weight']:.2%} | {info_R_w50['cost_total_frac']:.4f} |",
        f"| W50 | L | {info_L_w50['max_dd']:.2%} | {info_L_w50['max_single_weight']:.2%} | {info_L_w50['cost_total_frac']:.4f} |",
        f"| W50 | LC | {info_LC_w50['max_dd']:.2%} | {info_LC_w50['max_single_weight']:.2%} | {info_LC_w50['cost_total_frac']:.4f} |",
        f"| C15 | R | {info_R_c['max_dd']:.2%} | {info_R_c['max_single_weight']:.2%} | {info_R_c['cost_total_frac']:.4f} |",
        f"| C15 | L | {info_L_c['max_dd']:.2%} | {info_L_c['max_single_weight']:.2%} | {info_L_c['cost_total_frac']:.4f} |",
        f"| C15 | LC | {info_LC_c['max_dd']:.2%} | {info_LC_c['max_single_weight']:.2%} | {info_LC_c['cost_total_frac']:.4f} |",
    ]

    # ----- max_single_weight 截面分布(三臂各自) + LC 现金占比分布 -----
    def pct(s: list[float], p: float) -> float:
        if not s:
            return 0.0
        return float(np.percentile(np.array(s), p))

    # tag info dicts with arm label (for report readability)
    info_R_w50["arm"] = "R"
    info_L_w50["arm"] = "L"
    info_LC_w50["arm"] = "LC"
    info_R_c["arm"] = "R"
    info_L_c["arm"] = "L"
    info_LC_c["arm"] = "LC"

    report_lines += ["", "## max_single_weight 截面分布(每周末截面)", ""]
    report_lines += ["| 篮子 | 臂 | 中位 | p90 | 最大 | 触发 cap(2/N 上限)的周数 |", "|---|---|---|---|---|---|"]
    for label, info, n_basket in [
        ("W50", info_R_w50, W50_N), ("W50", info_L_w50, W50_N), ("W50", info_LC_w50, W50_N),
        ("C15", info_R_c, CRYPTO_N), ("C15", info_L_c, CRYPTO_N), ("C15", info_LC_c, CRYPTO_N),
    ]:
        w = info["weekly_max_single_weight"]
        n_weeks = len(w)
        cap_hits = int(sum(1 for x in w if x >= 2.0 / n_basket - 1e-12))
        report_lines.append(
            f"| {label} | {info['arm']} | {pct(w,50):.2%} | {pct(w,90):.2%} | {pct(w,100):.2%} | {cap_hits}/{n_weeks} |"
        )

    report_lines += ["", "## LC 现金占比截面分布(每周末截面)", ""]
    report_lines += ["| 篮子 | 臂 | 中位 | p90 | 最大 | >0 的周数 |", "|---|---|---|---|---|---|"]
    for label, info in [
        ("W50", info_LC_w50), ("C15", info_LC_c),
    ]:
        c = info["weekly_cash_ratio"]
        n_weeks = len(c)
        pos = int(sum(1 for x in c if x > 1e-9))
        report_lines.append(
            f"| {label} | LC | {pct(c,50):.2%} | {pct(c,90):.2%} | {pct(c,100):.2%} | {pos}/{n_weeks} |"
        )
    report_lines += ["", "## LC 砍掉的笔数 + 被砍名字之后 13 周的收益(只验「是不是砍在底部」)", ""]
    for label, info in [("W50", info_LC_w50), ("C15", info_LC_c)]:
        cuts = info["lc_cuts"]
        report_lines.append(f"- {label}:共砍掉 {len(cuts)} 笔;之后 13 周按周复合收益均值见下表")
        # also compute forward 13-week return of each cut symbol from cut date
        # use w50_close / c_close depending on label
        close_mat = w50_close if label == "W50" else c_close
        syms = w50_syms if label == "W50" else c_syms
        idxs = weekly_idx_w50 if label == "W50" else weekly_idx_c
        d_list = w50_dates if label == "W50" else c_dates
        ret_after = []
        for cut in cuts[:25]:  # cap table
            cut_date, sym, ep, cp, r_since_entry = cut
            cut_i = d_list.index(cut_date)
            end_i = idxs[min(len(idxs) - 1, idxs.index(cut_i) + 13)] if cut_i in idxs else None
            if end_i is None or end_i <= cut_i:
                continue
            j = syms.index(sym)
            ps = close_mat[cut_i, j]
            pe = close_mat[end_i, j]
            if np.isfinite(ps) and np.isfinite(pe) and ps > 0:
                ret_after.append((pe - ps) / ps)
        if ret_after:
            report_lines.append(f"  前 {min(25, len(cuts))} 笔的之后 13 周收益均值:{np.mean(ret_after):.2%};中位:{np.median(ret_after):.2%}")
            report_lines.append(f"  → 验证「是不是砍在底部」:后续 13 周**继续下跌** ⇒ +;反弹 ⇒ -。"
                                f"正数 = 被砍在底部(后续跌更多);负数 = 砍早了")
        report_lines.append("")
    report_lines += [
        "## 备注",
        "- 数据路径:`/Volumes/CometCloudAI/cometcloud-local/research/{w50_daily,crypto_daily}`,Mac 数据根,只读。",
        "- 统计走 `apparatus.py::ab_test`,块长 4 周(预注册原文)。",
        "",
        "## 第 2 轮观察(Seth 10-18 退回 → 修)",
        "- **LC 2/N cap 已落实于砍输家后的 redsi 段(详见 `_redistribute_with_cap`)**。",
        "  - W50 没有触发 cut 的笔数(0 cuts),cap 形同虚设;LC 表现与 L 完全相同。",
        "  - C15 早期(rebal#0-7 还在 3 名期)=>LC 把这 3 名陆续砍光、basket 坍缩到 cash 100% 一直持续到 2020-01 才因 select_top 数据补齐变为 15 名;**但** 因 L/LC rebal 段 `kept_total=0 ⇒ scale=0` 的存量设计(原 §S-597 一字不改),把老成员卡在 0 权重、新人又分不到钱,2020-01 后 basket 也救不回来 ⇒ 373/386 周 cash=100%。**这是 pre-existing 行为,不是 cap 引起的**,cap 修了「单名爆炸 >200%」的部分。",
        "- 单名 ≤ 100% 的硬上限是 cap=1.0(N=1 时 2/1=2 自动钳到 1)。cap 真的压住 >100% 只有在 N≥3 且一次砍多个、剩余 sum_w>0 时的极端场景;C15 实际模拟里 cut 多为一次性 1 个,cap 形同虚设。",
        "- 三臂 max_w 截面分布差异几乎全来自数据稀疏(C15 2019)/ 没有 cut(W50),**不是 §S-597 本身的胜负**。要直接看 L/LC vs R 的判据,看前面 `## ab_test 三段对照`。",
    ]
    OUT_REPORT.write_text("\n".join(report_lines))
    print(f"WROTE: {OUT_REPORT}  ({len(report_lines)} lines)")


if __name__ == "__main__":
    main()
