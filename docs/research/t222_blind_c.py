#!/usr/bin/env python3
"""T-222 v2 盲复算(lane-c)—— 三个数。

口径来源:`docs/research/T-222_funding_carry.md` 的 §口径(§0 CHANGES / §2 面板事实 / §4.1 规则定义 /
§4.3 随机门控构造 / §5.4 Spearman)。本脚本不引用该报告的结论段。

算三个数:
① 等权 24 名(binance_perp)2023-01-01 → 2026-10-31 的年化**毛**资金费;
② 规则 B(7 日均 funding > 0、滞后 1 日、周换仓)的**净**年化 + 同等开关次数 / 同等开仓天数的
   随机门控对照分位(1,000 次,种子 222);
③ 月度资金费 vs BTC **未来 30 日**收益的 Spearman(n ≈ 45)。

零分布 / 分位一律走 `src/data/evaluation/apparatus.py`(null_distribution / percentile_of /
block_permute / price_on_or_after),不自写零分布。全程只读 SELECT,不入库。

用法:python3 docs/research/t222_blind_c.py
输出:docs/research/t222_blind_c_results.json + stdout 摘要
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "data" / "evaluation"))
import apparatus  # noqa: E402  (验证装置:零分布 / 盈亏 / 分位只许用它)

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    print("缺少 SUPABASE_URL / SUPABASE_KEY,退出", file=sys.stderr)
    raise SystemExit(2)
HEAD = dict()
HEAD["apikey"] = KEY
HEAD["Authorization"] = "Bearer " + KEY

START = "2023-01-01"
END = "2026-10-31"
VENUE = "binance_perp"
FEE_PER_SWITCH = 0.00075          # 现货 taker 4bp + 永续 taker 3.5bp
N_NULL = 1000
SEED = 222
BLOCK = 30                       # 块置换块长(日),§Seth-1102f 指定
CRYPTO_CLASSES = ("L1", "L2", "DeFi", "RWA", "Infrastructure")

PANEL_Q = ("cis_official_daily?select=d,symbol,asset_class&order=d.desc,symbol.asc&limit=600")
OHLC_Q = ("ohlcv_daily?select=symbol,trade_date,close,source&symbol=eq.BTC"
          "&trade_date=gte.2022-10-01&trade_date=lte.2026-10-31&order=trade_date.asc")
FUND_Q = ("funding_history?select=symbol,funding_time,funding_rate&venue=eq." + VENUE +
          "&funding_time=gte.2023-01-01T00:00:00Z&funding_time=lt.2026-11-01T00:00:00Z"
          "&order=symbol.asc,funding_time.asc")


# ── 读库(只读 SELECT,翻页带 order=)──────────────────────────────────────────
def fetch(query: str, page: int = 1000) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        url = URL + "/rest/v1/" + query + "&limit=" + str(page) + "&offset=" + str(offset)
        req = urllib.request.Request(url, headers=HEAD)
        with urllib.request.urlopen(req, timeout=180) as resp:
            chunk = json.loads(resp.read().decode("utf-8"))
        rows.extend(chunk)
        if not chunk:
            break
        offset += len(chunk)
        if offset > 400000:
            break
    return rows


def daterange(a: str, b: str) -> list[str]:
    d0 = dt.date.fromisoformat(a)
    d1 = dt.date.fromisoformat(b)
    out = []
    while d0 <= d1:
        out.append(d0.isoformat())
        d0 += dt.timedelta(days=1)
    return out


def spearman(x, y):
    from scipy import stats
    if len(x) < 3:
        return None, None
    r = stats.spearmanr(x, y)
    return float(r.statistic), float(r.pvalue)


def main() -> dict:
    # ── 面板:`cis_official_daily` 最近一天的加密名 ────────────────────────────
    cis = fetch(PANEL_Q)
    latest = max(r["d"] for r in cis)
    panel_all = sorted(r["symbol"] for r in cis
                       if r["d"] == latest and r["asset_class"] in CRYPTO_CLASSES)
    res: dict = {"meta": {
        "panel_source": "cis_official_daily @ " + latest,
        "panel_crypto_classes": list(CRYPTO_CLASSES),
        "panel_crypto_names": panel_all,
        "n_panel_crypto": len(panel_all),
        "window": START + ".." + END,
        "venue": VENUE,
        "fee_per_switch": FEE_PER_SWITCH,
        "n_null": N_NULL, "seed": SEED, "block": BLOCK,
    }}

    fund_rows = fetch(FUND_Q + "&symbol=in.(" + ",".join(panel_all) + ")")
    res["meta"]["funding_rows"] = len(fund_rows)

    # 每名 → 每日资金费(该日 3 个 8h 结算之和)
    per_sym: dict[str, dict[str, float]] = {}
    for r in fund_rows:
        d = str(r["funding_time"])[:10]
        if not (START <= d <= END):
            continue
        per_sym.setdefault(r["symbol"], {})
        per_sym[r["symbol"]][d] = per_sym[r["symbol"]].get(d, 0.0) + float(r["funding_rate"] or 0.0)

    days = daterange(START, END)
    syms = sorted(per_sym)
    res["meta"]["n_symbols"] = len(syms)
    res["meta"]["symbols"] = syms
    res["meta"]["symbols_missing_funding"] = sorted(set(panel_all) - set(syms))
    res["meta"]["symbol_windows"] = {s: [min(per_sym[s]), max(per_sym[s]), len(per_sym[s])] for s in syms}

    # 主口径:每日「有数据的名字」的均值(日均组合,成分随时间变)
    port: dict[str, float] = {}
    n_names: list[int] = []
    for d in days:
        vals = [per_sym[s][d] for s in syms if d in per_sym[s]]
        if vals:
            port[d] = float(np.mean(vals))
            n_names.append(len(vals))
    pdates = sorted(port)
    res["meta"]["days_with_data"] = len(pdates)
    res["meta"]["names_per_day_min_max_mean"] = [min(n_names), max(n_names),
                                                 round(float(np.mean(n_names)), 4)]

    # ── ① 年化毛资金费 ────────────────────────────────────────────────────────
    f = np.array([port[d] for d in pdates])
    years = len(pdates) / 365.25
    ann_dailyavg = float(f.mean() * 365.25)
    cum_dailyavg = float(f.sum())
    per_name = {}
    for s in syms:
        ds = sorted(per_sym[s])
        v = np.array([per_sym[s][d] for d in ds])
        per_name[s] = {"start": ds[0], "end": ds[-1], "days": len(ds),
                       "ann_pct": float(v.mean() * 365.25 * 100.0),
                       "cum_pct": float(v.sum() * 100.0)}
    ann_names = np.array([per_name[s]["ann_pct"] for s in syms])
    res["m1_gross"] = {
        "dailyavg_portfolio": {"ann_pct": ann_dailyavg * 100.0, "cum_pct": cum_dailyavg * 100.0,
                               "years": years, "days": len(pdates),
                               "mean_daily_pct": float(f.mean() * 100.0)},
        "equal_weight_per_name_own_window": {"mean_ann_pct": float(ann_names.mean()),
                                              "median_ann_pct": float(np.median(ann_names)),
                                              "min_ann_pct": float(ann_names.min()),
                                              "max_ann_pct": float(ann_names.max()),
                                              "std_ann_pct": float(ann_names.std(ddof=1)),
                                              "n_negative": int((ann_names < 0).sum()),
                                              "n_names": len(syms)},
        "per_name": per_name,
    }

    # ── ② 规则 B(7 日均 > 0、滞后 1 日、周换仓)+ 随机门控对照 ──────────────────
    n = len(pdates)

    def gate_state(rebalance: str):
        """返回 (state, signal)。signal[t] = 只用 t-7..t-1(滞后 1 日,不看当天)的 7 日均值 > 0。"""
        sig = np.zeros(n, dtype=bool)
        for i in range(n):
            seg = f[max(0, i - 7):i]
            sig[i] = bool(len(seg) and float(seg.mean()) > 0.0)
        state = np.zeros(n, dtype=bool)
        cur = False
        last_key = None
        for i, d in enumerate(pdates):
            dt_ = dt.date.fromisoformat(d)
            if rebalance == "week":
                key = dt_.isocalendar()[:2]
            elif rebalance == "month":
                key = (d[:7],)
            else:
                key = (i,)
            if key != last_key:
                last_key = key
                cur = bool(sig[i])
            state[i] = cur
        return state, sig

    state, sig = gate_state("week")
    gross_b = float((state * f).sum())
    trans_b = int((state[1:] != state[:-1]).sum())
    # 开关计数:内部切换 + 起手那一次开仓(若路径以开仓开头)+ 末尾那一次平仓(若路径以持仓结尾)
    starts_open = bool(state[0])
    ends_open = bool(state[-1])
    switches_b = trans_b + (1 if starts_open else 0) + (1 if ends_open else 0)
    net_b = gross_b - FEE_PER_SWITCH * switches_b
    res["m2_ruleB_weekly"] = {
        "gross_pct": gross_b * 100.0,
        "net_pct": net_b * 100.0,
        "switches": switches_b, "transitions": trans_b,
        "starts_open": starts_open, "ends_open": ends_open,
        "switches_if_always_plus_final_close": trans_b + 2,
        "net_pct_if_always_plus_final_close": (gross_b - FEE_PER_SWITCH * (trans_b + 2)) * 100.0,
        "open_days": int(state.sum()), "closed_days": int((~state).sum()),
        "years": years, "ann_net_pct": net_b / years * 100.0,
        "ann_gross_pct": gross_b / years * 100.0,
        "open_days_fraction": float(state.mean()),
        "signal_definition": "7 日均 funding > 0,只用 t-7..t-1(滞后 1 日,不看当天);每个 ISO 周第一个有数据日重算",
    }

    # 随机门控对照:同样的起始状态、同样的开关次数(⇒ 同样的段数)、
    # 同样的开仓天数 ⇒ 费用完全相同;只有「哪些天开仓」随机。
    runs: list[tuple[bool, int]] = []
    for i in range(n):
        s = bool(state[i])
        if runs and runs[-1][0] == s:
            runs[-1] = (s, runs[-1][1] + 1)
        else:
            runs.append((s, 1))
    open_runs = [k for (s, k) in runs if s]
    closed_runs = [k for (s, k) in runs if not s]
    total_open = int(sum(open_runs))
    total_closed = n - total_open

    def rand_composition(total: int, k: int, rng: np.random.Generator) -> list[int]:
        """把 total 正整数随机切成 k 个正整数段(组合均匀)。"""
        if k <= 1:
            return [total]
        cuts = np.sort(rng.choice(np.arange(1, total), size=k - 1, replace=False))
        edges = np.concatenate(([0], cuts, [total]))
        return [int(x) for x in np.diff(edges)]

    def control_path(rng: np.random.Generator) -> np.ndarray:
        o = rand_composition(total_open, len(open_runs), rng)
        c = rand_composition(total_closed, len(closed_runs), rng)
        oi = ci = 0
        path = np.zeros(n, dtype=bool)
        pos = 0
        for (s, _) in runs:
            ln = o[oi] if s else c[ci]
            if s:
                oi += 1
            else:
                ci += 1
            path[pos:pos + ln] = s
            pos += ln
        return path

    def null_stat(rng: np.random.Generator) -> float:
        p = control_path(rng)
        return float((p * f).sum() - FEE_PER_SWITCH * switches_b)

    null = apparatus.null_distribution(null_stat, N_NULL, SEED, actual=net_b)
    pct = apparatus.percentile_of(net_b, null)
    res["m2_random_gate_control"] = {
        "n_null": int(null.size), "seed": SEED,
        "null_mean_pct": float(null.mean() * 100.0),
        "null_q05_pct": float(np.percentile(null, 5) * 100.0),
        "null_q50_pct": float(np.percentile(null, 50) * 100.0),
        "null_q95_pct": float(np.percentile(null, 95) * 100.0),
        "null_q99_pct": float(np.percentile(null, 99) * 100.0),
        "actual_net_pct": net_b * 100.0,
        "percentile_of_actual": pct,
        "n_null_ge_actual": int((null >= net_b).sum()),
        "construction": "同起始状态 + 同开关数(同段数)+ 同开仓天数;开/闭仓天数各自随机切成同样段数,交替排布",
        "n_open_runs": len(open_runs), "n_closed_runs": len(closed_runs),
        "total_open_days": total_open, "total_closed_days": total_closed,
    }

    # ── ③ 月度资金费 vs BTC 未来 30 日收益 Spearman ───────────────────────────
    ohlc_rows = fetch(OHLC_Q)
    res["meta"]["ohlcv_btc_rows"] = len(ohlc_rows)
    by_source: dict[str, dict[str, float]] = {}
    for r in ohlc_rows:
        by_source.setdefault(r["source"], {})
        by_source[r["source"]][str(r["trade_date"])[:10]] = float(r["close"])
    res["meta"]["btc_sources"] = {s: [len(v), min(v), max(v)] for s, v in by_source.items()}

    mkeys_all = []
    for d in pdates:
        k = d[:7]
        if not mkeys_all or mkeys_all[-1] != k:
            mkeys_all.append(k)

    def monthly_funding(mkey: str, port_map: dict[str, float]) -> float:
        vals = [port_map[d] for d in pdates if d[:7] == mkey]
        return float(np.mean(vals)) if vals else float("nan")

    mfund_mean = {k: monthly_funding(k, port) for k in mkeys_all}
    # 主口径:月内资金费**求和**(单位 %/月);月均值作稳健性变体
    mfund_sum = {k: float(sum(port[d] for d in pdates if d[:7] == k)) for k in mkeys_all}
    mfund = mfund_sum

    def btc_block(source: str):
        """返回 (日期列表, 收盘列表, 月末日期映射, 上月末日期映射, 入/出下标)。"""
        closes_by_day = by_source[source]
        bdates = sorted(closes_by_day)
        bcloses = [closes_by_day[d] for d in bdates]
        month_last = {}
        for d in bdates:
            month_last[d[:7]] = d
        months_sorted = sorted(month_last)
        prev_month_end = {}
        for i, k in enumerate(months_sorted):
            if i > 0:
                prev_month_end[k] = month_last[months_sorted[i - 1]]
        idx_entry, idx_exit = {}, {}
        for k in mkeys_all:
            if k not in month_last:
                continue
            m_end = month_last[k]
            tgt = (dt.date.fromisoformat(m_end) + dt.timedelta(days=30)).isoformat()
            i0 = bisect.bisect_left(bdates, m_end)
            i1 = bisect.bisect_left(bdates, tgt)
            if i1 >= len(bdates):
                continue
            if (dt.date.fromisoformat(bdates[i1]) - dt.date.fromisoformat(tgt)).days > 7:
                continue
            idx_entry[k] = i0
            idx_exit[k] = i1
        return bdates, bcloses, month_last, prev_month_end, idx_entry, idx_exit

    def fwd_return(bcloses, idx_entry, idx_exit, k):
        if k not in idx_entry:
            return None
        return float(bcloses[idx_exit[k]] / bcloses[idx_entry[k]] - 1.0)

    def same_month_return(bdates, bcloses, month_last, prev_month_end, k):
        """同期口径:本月末收盘 / 上月末收盘 − 1。"""
        if k not in month_last or k not in prev_month_end:
            return None
        p0 = apparatus.price_on_or_after(bdates, bcloses, month_last[k], max_gap_days=7)
        p1 = apparatus.price_on_or_after(bdates, bcloses, prev_month_end[k], max_gap_days=7)
        if p0 is None or p1 is None:
            return None
        return float(p0 / p1 - 1.0)

    def run_spearman(source: str, primary: bool):
        bdates_s, bcloses_s, month_last_s, prev_end_s, idx_e, idx_x = btc_block(source)
        # 与 apparatus 对账:下标法 == price_on_or_after
        mismatch = 0
        for k in mkeys_all:
            if k not in idx_e:
                continue
            m_end = month_last_s[k]
            tgt = (dt.date.fromisoformat(m_end) + dt.timedelta(days=30)).isoformat()
            p0 = apparatus.price_on_or_after(bdates_s, bcloses_s, m_end, max_gap_days=7)
            p1 = apparatus.price_on_or_after(bdates_s, bcloses_s, tgt, max_gap_days=7)
            if p0 is None or p1 is None or abs(p0 - bcloses_s[idx_e[k]]) > 1e-9 \
                    or abs(p1 - bcloses_s[idx_x[k]]) > 1e-9:
                mismatch += 1
        pairs = [(k, mfund[k], fwd_return(bcloses_s, idx_e, idx_x, k)) for k in mkeys_all]
        pairs = [(k, a, b) for (k, a, b) in pairs if b is not None]
        x = np.array([p[1] for p in pairs])
        y = np.array([p[2] for p in pairs])
        rho_f, p_f = spearman(x, y)
        pairs_s = [(k, mfund[k], same_month_return(bdates_s, bcloses_s, month_last_s, prev_end_s, k))
                   for k in mkeys_all]
        pairs_s = [(k, a, b) for (k, a, b) in pairs_s if b is not None]
        xs = np.array([p[1] for p in pairs_s])
        ys = np.array([p[2] for p in pairs_s])
        rho_s, p_s = spearman(xs, ys)
        # 块置换零分布(块长 30):BTC 日收益打乱块顺序 → 重建价格 → 重算未来 30 日 → 重算 ρ
        bret = np.diff(np.array(bcloses_s)) / np.array(bcloses_s[:-1])

        def null_rho_fn(rng: np.random.Generator) -> float:
            perm = apparatus.block_permute(bret, BLOCK, rng)
            px = [bcloses_s[0]]
            for r_ in perm:
                px.append(px[-1] * (1.0 + float(r_)))
            xx, yy = [], []
            for k in mkeys_all:
                if k not in idx_e:
                    continue
                xx.append(mfund[k])
                yy.append(float(px[idx_x[k]] / px[idx_e[k]] - 1.0))
            if len(xx) < 3:
                return float("nan")
            r_ = spearman(xx, yy)[0]
            return float("nan") if r_ is None else float(r_)

        null_rho = None
        pct_rho = None
        try:
            null_rho = apparatus.null_distribution(null_rho_fn, N_NULL, SEED, actual=rho_f)
            pct_rho = apparatus.percentile_of(rho_f, null_rho)
        except apparatus.NoOpNull as exc:
            null_rho = None
        out = {
            "source": source,
            "btc_days": len(bdates_s),
            "btc_first_last": [bdates_s[0], bdates_s[-1]],
            "index_crosscheck_mismatch_vs_apparatus": mismatch,
            "future_30d": {"rho": rho_f, "p_two_sided": p_f, "n": int(len(x)),
                           "null_mean": (None if null_rho is None else float(np.nanmean(null_rho))),
                           "null_q025": (None if null_rho is None else float(np.nanpercentile(null_rho, 2.5))),
                           "null_q975": (None if null_rho is None else float(np.nanpercentile(null_rho, 97.5))),
                           "percentile_of_actual": pct_rho},
            "same_month_return": {"rho": rho_s, "p_two_sided": p_s, "n": int(len(xs))},
            "months": [{"month": k, "funding_pct_day": float(mfund[k]),
                        "btc_fwd30_pct": (None if fwd_return(bcloses_s, idx_e, idx_x, k) is None
                                          else float(fwd_return(bcloses_s, idx_e, idx_x, k) * 100.0)),
                        "btc_same_month_pct": (None if same_month_return(bdates_s, bcloses_s, month_last_s, prev_end_s, k) is None
                                               else float(same_month_return(bdates_s, bcloses_s, month_last_s, prev_end_s, k) * 100.0))}
                       for k in mkeys_all],
        }
        return out

    primary_src = "binance_hist" if "binance_hist" in by_source else sorted(by_source)[0]
    res["m3_spearman"] = {
        "monthly_funding_definition": "24 名日均组合的日历月内每日均值(单位 %/日)",
        "n_months_total": len(mkeys_all),
        "primary_source": primary_src,
        "primary": run_spearman(primary_src, True),
        "other_sources": {},
    }
    for s in sorted(by_source):
        if s == primary_src:
            continue
        try:
            res["m3_spearman"]["other_sources"][s] = run_spearman(s, False)
        except Exception as exc:      # 覆盖不全的源只报不写
            res["m3_spearman"]["other_sources"][s] = {"error": type(exc).__name__ + ": " + str(exc)[:120]}

    # ── 口径变体扫描(同期 Spearman 的定义分歧)────────────────────────────────
    # 「BTC 月回报」有三种读法,月度资金费有两种读法,交叉算一遍,看 ρ 差在哪。
    cb = by_source[primary_src]
    bd_p = sorted(cb)
    bc_p = [cb[d] for d in bd_p]
    all_months = sorted(set(d[:7] for d in bd_p))
    m_first, m_last = {}, {}
    for d in bd_p:
        m_first.setdefault(d[:7], d)
        m_last[d[:7]] = d
    daily_by_month: dict[str, list[float]] = {}
    for i in range(1, len(bd_p)):
        daily_by_month.setdefault(bd_p[i][:7], []).append(bc_p[i] / bc_p[i - 1] - 1.0)
    mfund_sum = mfund
    fund_variants = {"month_sum_pct": mfund, "month_mean_pct_day": mfund_mean}
    btc_month_variants: dict[str, dict[str, float]] = {}
    for k in mkeys_all:
        if k not in m_last:
            continue
        idx = all_months.index(k)
        prev_end = m_last[all_months[idx - 1]] if idx > 0 else None
        vals = {}
        if prev_end is not None:
            vals["prev_month_end_to_month_end"] = float(cb[m_last[k]] / cb[prev_end] - 1.0)
        vals["month_first_to_month_end"] = float(cb[m_last[k]] / cb[m_first[k]] - 1.0)
        if daily_by_month.get(k):
            vals["arith_mean_daily_return"] = float(np.mean(daily_by_month[k]))
        btc_month_variants[k] = vals
    variants = {}
    for fv, fmap in fund_variants.items():
        for bv in ("prev_month_end_to_month_end", "month_first_to_month_end",
                   "arith_mean_daily_return"):
            ks = [k for k in mkeys_all if k in btc_month_variants and bv in btc_month_variants[k]]
            if len(ks) < 3:
                continue
            x = np.array([fmap[k] for k in ks])
            y = np.array([btc_month_variants[k][bv] for k in ks])
            rho, pv = spearman(x, y)
            variants["same_month|" + fv + "|" + bv] = {"rho": rho, "p": pv, "n": len(ks)}
        # 未来 30 日口径(资金费读法的稳健性)
        bdates_s, bcloses_s, month_last_s, prev_end_s, idx_e, idx_x = btc_block(primary_src)
        ks = [k for k in mkeys_all if k in idx_e]
        x = np.array([fmap[k] for k in ks])
        y = np.array([float(bcloses_s[idx_x[k]] / bcloses_s[idx_e[k]] - 1.0) for k in ks])
        rho, pv = spearman(x, y)
        variants["future_30d|" + fv] = {"rho": rho, "p": pv, "n": len(ks)}
    res["m3_variants"] = variants

    out_path = ROOT / "docs" / "research" / "t222_blind_c_results.json"
    out_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "meta": {k: res["meta"][k] for k in ("panel_source", "n_panel_crypto", "n_symbols",
                                              "symbols_missing_funding", "funding_rows",
                                              "days_with_data", "names_per_day_min_max_mean",
                                              "btc_sources", "panel_crypto_names")},
        "m1_gross": {k: v for k, v in res["m1_gross"].items() if k != "per_name"},
        "m2_ruleB_weekly": res["m2_ruleB_weekly"],
        "m2_random_gate_control": res["m2_random_gate_control"],
        "m3_primary": {k: v for k, v in res["m3_spearman"]["primary"].items() if k != "months"},
        "m3_other": {s: {k: v for k, v in blk.items() if k != "months"}
                     for s, blk in res["m3_spearman"]["other_sources"].items()},
        "m3_variants": res["m3_variants"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    main()
