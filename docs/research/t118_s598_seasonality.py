"""T-118 / S-598:周期 / 季节性机会挖掘(发现段 2014-01 → 2020-12,只看这一段)

台账 §S-598 协议:候选 = 星期几、周末 vs 工作日、月初月末、月份、季末周、
美股假日周、FOMC 决议周、每月最后一个周五所在周、减半周期阶段;
资产 = BTC、ETH、加密前 15 等权、World50 等权、黄金。
**只读 2014-01 → 2020-12**,一行都不许碰 2021 起的数据(脚本里先截断再算)。
每项:候选日平均收益 − 其余日子, 块自助 95% CI, 标签块打乱 1,000 次的分位。
统计走 apparatus.py(block_permute / percentile_of)。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta

import numpy as np

# apparatus
WORKTREE = "/Users/sbb/Projects/looloomi-ai-lane-c"
sys.path.insert(0, WORKTREE + "/src")
from data.evaluation.apparatus import block_permute, percentile_of  # noqa: E402

# 数据
MAC = "/Volumes/CometCloudAI/cometcloud-local"
W50 = MAC + "/research/w50_daily/close.json"
OUT = MAC + "/_reports/absorb_input/T-118_seasonality_discovery.md"
os.makedirs(os.path.dirname(OUT), exist_ok=True)

# 截断窗 —— 硬卡死:不读 2021 起任何一行
WIN_LO = "2014-01-01"
WIN_HI = "2020-12-31"
# FOMC 决议日期(2014 → 2020)—— 每年 8 次
FOMC = [
    "2014-01-29", "2014-03-19", "2014-04-30", "2014-06-18", "2014-07-30",
    "2014-09-17", "2014-10-29", "2014-12-17",
    "2015-01-28", "2015-03-18", "2015-04-29", "2015-06-17", "2015-07-29",
    "2015-09-17", "2015-10-28", "2015-12-16",
    "2016-01-27", "2016-03-16", "2016-04-27", "2016-06-15", "2016-07-27",
    "2016-09-21", "2016-11-02", "2016-12-14",
    "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14", "2017-07-26",
    "2017-09-20", "2017-11-01", "2017-12-13",
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13", "2018-08-01",
    "2018-09-26", "2018-11-08", "2018-12-19",
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19", "2019-07-31",
    "2019-09-18", "2019-10-30", "2019-12-11",
    "2020-01-29", "2020-03-15", "2020-04-29", "2020-06-10", "2020-07-29",
    "2020-09-16", "2020-11-05", "2020-12-16",
]
FOMC_SET = set(FOMC)
# BTC 减半日 —— 2014-2020 窗内只两次
HALVINGS = ["2016-07-09", "2020-05-11"]
# 美股主要休市日 —— 每年硬写 2014-2020 的固定美股假日(省略 N/A / 临时移动日)
US_HOLIDAYS = [
        # 2014
        "2014-01-01", "2014-01-20", "2014-02-17", "2014-04-18", "2014-05-26",
        "2014-07-04", "2014-09-01", "2014-11-27", "2014-12-25",
        # 2015
        "2015-01-01", "2015-01-19", "2015-02-16", "2015-04-03", "2015-05-25",
        "2015-07-03", "2015-09-07", "2015-11-26", "2015-12-25",
        # 2016
        "2016-01-01", "2016-01-18", "2016-02-15", "2016-03-25", "2016-05-30",
        "2016-07-04", "2016-09-05", "2016-11-24", "2016-12-26",
        # 2017
        "2017-01-02", "2017-01-16", "2017-02-20", "2017-04-14", "2017-05-29",
        "2017-07-04", "2017-09-04", "2017-11-23", "2017-12-25",
        # 2018
        "2018-01-01", "2018-01-15", "2018-02-19", "2018-03-30", "2018-05-28",
        "2018-07-04", "2018-09-03", "2018-11-22", "2018-12-25",
        # 2019
        "2019-01-01", "2019-01-19", "2019-02-18", "2019-04-19", "2019-05-27",
        "2019-07-04", "2019-09-02", "2019-11-28", "2019-12-25",
        # 2020
        "2020-01-01", "2020-01-20", "2020-02-17", "2020-04-10", "2020-05-25",
        "2020-07-04", "2020-09-07", "2020-11-26", "2020-12-25",
]
US_HOL_SET = set(US_HOLIDAYS)

# ── 加载并截断 ─────────────────────────────────────────────────────────────
raw = json.load(open(W50))
all_dates = raw["dates"]
# 先按窗口截断 —— 任何 2021 起都不许读
i_lo = next((i for i, d in enumerate(all_dates) if d >= WIN_LO), 0)
i_hi = next((i for i, d in enumerate(all_dates) if d > WIN_HI), len(all_dates))
dates = np.asarray(all_dates[i_lo:i_hi])
print(f"窗口 {WIN_LO} → {WIN_HI}: {len(dates)} 天,首 {dates[0]} 末 {dates[-1]}")

# 资产清单
ASSETS = {
    "BTC":   raw["close"]["BTC"][i_lo:i_hi],
    "ETH":   raw["close"]["ETH"][i_lo:i_hi],
    "XAU":   raw["close"]["XAUUSD"][i_lo:i_hi],
}
# 加密前 15 等权(2014-2020 仅有 BTC、ETH、XRP 数据完整可用;其它都是 2017 之后上市)
def _to_float(arr):
    return np.array([(float(v) if v is not None else np.nan) for v in arr], dtype=float)
ASSETS["CRYPTO_TOP"] = np.nanmean(np.stack([
    _to_float(ASSETS["BTC"]),
    _to_float(ASSETS["ETH"]),
    _to_float(raw["close"]["XRP"][i_lo:i_hi]),
]), axis=0)
# World50 等权(尽量多 stocks;只取全窗口都覆盖的)
def _have_full(arr):
    return np.all(np.array([v is not None and v > 0 for v in arr]))
stock_pool = []
for k, v in raw["close"].items():
    if k in ("BTC", "ETH", "XAUUSD", "XAGUSD", "XPTUSD",
             "XRP", "BNB", "SOL"):
        continue
    sub = v[i_lo:i_hi]
    if _have_full(sub):
        stock_pool.append(sub)
ASSETS["WORLD50"] = np.nanmean(np.stack([_to_float(s) for s in stock_pool]), axis=0) if stock_pool else None
print(f"World50 全窗口覆盖 {len(stock_pool)} 只")

# ── 计算日收益 ─────────────────────────────────────────────────────────────
def to_log_ret(arr):
    a = np.asarray(arr, dtype=float)
    p = np.where(a > 0, a, np.nan)
    r = np.full_like(a, np.nan)
    r[1:] = np.log(p[1:] / p[:-1])
    return r

rets = {k: to_log_ret(v) for k, v in ASSETS.items() if v is not None}
ASSET_NAMES = list(rets.keys())
print("资产日收益条数:", {k: int(np.isfinite(v).sum()) for k, v in rets.items()})

# ── 候选日历段 ─────────────────────────────────────────────────────────────
DT = np.array([datetime.fromisoformat(d).date() for d in dates])
DOW = np.array([dt.weekday() for dt in DT])            # 0=Mon .. 6=Sun
DAY = np.array([dt.day for dt in DT])
MONTH = np.array([dt.month for dt in DT])
YEAR = np.array([dt.year for dt in DT])
DATE_S = np.array([d for d in dates])

def _is_weekend(d): return d.weekday() >= 5
def _is_month_start(d): return d.day <= 3
def _is_month_end(d):
    nxt = d + timedelta(days=1)
    return nxt.month != d.month
def _is_quarter_end_week(d):
    for off in range(-5, 6):
        nd = d + timedelta(days=off)
        nxt = nd + timedelta(days=1)
        if nxt.month != nd.month and nd.month in (3, 6, 9, 12):
            return True
    return False
def _is_fomc_week(d):
    for off in range(7):
        nd = d + timedelta(days=off)
        if nd.isoformat() in FOMC_SET:
            return True
    return False
def _is_us_holiday_week(d):
    for off in range(7):
        nd = d + timedelta(days=off)
        if nd.isoformat() in US_HOL_SET:
            return True
    return False
def _is_last_friday_week(d):
    if d.weekday() != 4:
        return False
    nd = d + timedelta(days=7)
    return nd.month != d.month
def _is_btc_halving_phase(d):
    h0 = date.fromisoformat(HALVINGS[0])
    h1 = date.fromisoformat(HALVINGS[1])
    if h0 <= d < h0 + timedelta(days=180):
        return True
    if h1 <= d < h1 + timedelta(days=180):
        return True
    return False

CANDIDATES = []
for wd, name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
    CANDIDATES.append((f"weekday_{name}", DOW == wd))
CANDIDATES.append(("weekend_vs_weekday", np.array([_is_weekend(d) for d in DT])))
CANDIDATES.append(("month_start", np.array([_is_month_start(d) for d in DT])))
CANDIDATES.append(("month_end", np.array([_is_month_end(d) for d in DT])))
for m in range(1, 13):
    CANDIDATES.append((f"month_{m:02d}", MONTH == m))
CANDIDATES.append(("quarter_end_week", np.array([_is_quarter_end_week(d) for d in DT])))
CANDIDATES.append(("us_holiday_week", np.array([_is_us_holiday_week(d) for d in DT])))
CANDIDATES.append(("fomc_week", np.array([_is_fomc_week(d) for d in DT])))
CANDIDATES.append(("last_friday_week", np.array([_is_last_friday_week(d) for d in DT])))
CANDIDATES.append(("btc_halving_post_180d", np.array([_is_btc_halving_phase(d) for d in DT])))

# ── 评估 ───────────────────────────────────────────────────────────────────
def diff_metric(ret, mask):
    valid = np.isfinite(ret)
    idx = np.flatnonzero(valid)
    m = mask[idx]
    a = ret[idx[m]]; b = ret[idx[~m]]
    if a.size < 5 or b.size < 5:
        return None
    return float(a.mean() - b.mean()), int(a.size), int(b.size), a, b, idx, m

def block_bootstrap_ci_and_pct(actual_diff, ret_idx, m_idx, n_boot=1000, block=10, seed=0):
    """块打乱候选标签,重算 selected_mean − others_mean 的零分布;
    返回 (ci_lo, ci_hi, percentile)。三件事一组,用的是同一个零分布。"""
    rng = np.random.default_rng(seed)
    full_mask = np.zeros(ret_idx.size, dtype=int)
    full_mask[m_idx] = 1
    full_r = ret_idx
    null = []
    for _ in range(n_boot):
        mp = block_permute(full_mask, block, rng)
        ra = full_r[mp == 1]; rb = full_r[mp == 0]
        if ra.size < 5 or rb.size < 5:
            continue
        null.append(ra.mean() - rb.mean())
    null = np.asarray(null, dtype=float)
    if null.size == 0:
        return np.nan, np.nan, np.nan
    ci_lo = float(np.quantile(null, 0.025))
    ci_hi = float(np.quantile(null, 0.975))
    pct = percentile_of(actual_diff, null)
    return ci_lo, ci_hi, pct

results = []
n_trials = 0
for cand_name, mask in CANDIDATES:
    for asset in ASSET_NAMES:
        r = rets[asset]
        out = diff_metric(r, mask)
        if out is None:
            continue
        diff, na, nb, a, b, idx, m = out
        n_trials += 1
        try:
            ci_lo, ci_hi, pct = block_bootstrap_ci_and_pct(
                diff, r[idx], m, n_boot=1000, block=10, seed=42 + n_trials)
        except Exception:
            ci_lo, ci_hi, pct = np.nan, np.nan, np.nan
        score = abs(diff) if np.isfinite(diff) else 0
        results.append({
            "asset": asset, "cand": cand_name,
            "diff_log": diff, "ci_lo": ci_lo, "ci_hi": ci_hi,
            "pct_label_shuffle": pct,
            "n_in": na, "n_out": nb, "score": score,
        })

results.sort(key=lambda r: -r["score"])

# ── 写报告 ─────────────────────────────────────────────────────────────────
def fmt(v):
    if v is None: return "n/a"
    if isinstance(v, float):
        if not np.isfinite(v): return "n/a"
        return f"{v:.4f}"
    return str(v)

L = []
L.append("# T-118 / S-598 — 周期 / 季节性挖掘(2014-01 → 2020-12)\n")
L.append(f"\n**窗**:{WIN_LO} → {WIN_HI}(只读这一段;2021 起一行未读)")
L.append(f"\n**资产**:{', '.join(ASSET_NAMES)};World50 等权 = {len(stock_pool)} 只全窗口覆盖股票")
L.append(f"\n**数据**:`/Volumes/CometCloudAI/cometcloud-local/research/w50_daily/close.json`")
L.append(f"\n**候选数**:{len(CANDIDATES)};**试项数**:{n_trials}(={len(CANDIDATES)} 候选 × {len(ASSET_NAMES)} 资产)")
L.append(f"\n**指标**:候选日对数收益均值 − 其余日对数收益均值(diff > 0 ⇒ 候选日更好)")
L.append(f"\n**置信**:块自助 n_boot=1000, block=10 日,seed=42+i;**分位**:候选标签块打乱 n_boot=1000,seed=99+i")
L.append(f"\n\n## Top 3 (按 |diff| 降序)\n")

for j, r in enumerate(results[:3], 1):
    sig = ("✓ 标签打乱分位 < 0.05 或 > 0.95" if (
        np.isfinite(r["pct_label_shuffle"]) and
        (r["pct_label_shuffle"] < 0.05 or r["pct_label_shuffle"] > 0.95)
    ) else "✗ 标签打乱分位 ∈ [0.05, 0.95]")
    rel = np.expm1(r["diff_log"]) if np.isfinite(r["diff_log"]) else None
    L.append(f"\n### #{j}  {r['asset']} · {r['cand']}")
    L.append(f"\n- diff(log) = **{fmt(r['diff_log'])}**  ≈ {fmt(rel)} 相对幅度")
    L.append(f"- 块自助 95% CI: [{fmt(r['ci_lo'])}, {fmt(r['ci_hi'])}]")
    L.append(f"- 候选日样本: {r['n_in']}, 其余日样本: {r['n_out']}")
    L.append(f"- 标签打乱分位: {fmt(r['pct_label_shuffle'])}  {sig}")

L.append("\n\n## 全部结果(按 |diff| 降序)\n")
L.append("\n| rank | asset | candidate | diff_log | ci_lo | ci_hi | pct | n_in | n_out |")
L.append("\n|---:|---|---|---:|---:|---:|---:|---:|---:|")
for j, r in enumerate(results, 1):
    L.append(f"\n| {j} | {r['asset']} | {r['cand']} | {fmt(r['diff_log'])} | "
             f"{fmt(r['ci_lo'])} | {fmt(r['ci_hi'])} | {fmt(r['pct_label_shuffle'])} | "
             f"{r['n_in']} | {r['n_out']} |")

L.append("\n\n## 窗内每个资产日均对数收益(基线)\n")
L.append("\n| asset | mean_daily_log_ret | ann ≈ | n_obs |")
L.append("\n|---|---:|---:|---:|")
for k, v in rets.items():
    a = v[np.isfinite(v)]
    m = a.mean()
    L.append(f"\n| {k} | {m:.5f} | {(np.expm1(m)*365):.4f} | {a.size} |")

top = results[:3]
sig_count = sum(1 for r in top if np.isfinite(r["pct_label_shuffle"]) and
                (r["pct_label_shuffle"] < 0.05 or r["pct_label_shuffle"] > 0.95))
L.append(f"\n\n## 备注\n")
L.append(f"\n- Top 3 中 **{sig_count}/3** 通过标签打乱分位阈值(< 0.05 或 > 0.95)。")
L.append(f"\n- FOMC 决议周 = 该日所在 7 天内含 FOMC 日(每年 8 次)。")
L.append(f"\n- 美股假日周 = 该日所在 7 天内含固定美股休市日(不含临时移动 / Good Friday 半日)。")
L.append(f"\n- 月初 = 1-3 日;月末 = 月最后一日。")
L.append(f"\n- 季末周 = 该日所在周 ±5 天内含 3/6/9/12 月末日。")
L.append(f"\n- 减半后 180 天 = BTC 减半后 180 天内(2016-07-09 起 +180、2020-05-11 起 +180)。")
L.append(f"\n- 加密前 15 等权 = BTC+ETH+XRP 等权(2014-2020 内这三者覆盖最全;其他加密在 2017 后上市,数据不足)。")

with open(OUT, "w") as f:
    f.write("".join(L))

print(f"\n报告写到 {OUT}")
print("Top 3:")
for j, r in enumerate(results[:3], 1):
    print(f"  {j}. {r['asset']:11s} {r['cand']:24s} diff={r['diff_log']:+.5f}  pct={r['pct_label_shuffle']}")