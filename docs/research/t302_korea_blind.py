#!/usr/bin/env python3
"""T-302 —— S-771 / S-784 盲复算:按币的韩国溢价 P 与韩国成交份额 S → 之后 4 周相对 BTC。

纪律:
- 只读台账 REFUTATION_LEDGER.md 的 S-771 预注册原文与 S-784;**不读** T-292 的代码与结果段
  (docs/research/t292_korea.py、T-292_korea_premium.md、t292_results.json 一律未打开)。
- 零分布 / NW t / 块自助**只用** src/data/evaluation/apparatus.py。
- 数据:复用 lane-a 的只读缓存 /Volumes/CometCloudAI/cometcloud-local/research/_cache/t292/(只读)。

S-771 原文(台账,逐字照抄见 T-302_korea_blind.md 开头):
  每周一,代号 i:P_i = ln(KRW 收盘_i / 全球美元收盘_i) − ln(KRW 收盘_BTC / 全球美元收盘_BTC)
  (全球价 = Binance 现货 ohlcv_daily binance_hist 收盘,没有则 asset_mcap_daily;过去 7 天中位);
  S_i = Upbit KRW 成交额 / (全球成交额 × USDKRW)(过去 7 天和;USDKRW 用 Upbit KRW-USDT 收盘,上市之前的周不算 S);
  截面:当周两边都有价、Binance 现货在、市值 ≥ 2,000 万;目标 = 之后 4 周相对 BTC 的超额。
  判(P、S 各自):IC 均值 < 0 且 NW t ≤ −2;最高五分位 − 最低五分位 < 0;周内打乱 1,000 次分位 ≤ 0.05;
  2021–2023 / 2024–2026 两段同号。
S-784 追加:周内打乱种子 784;块自助(4 周块,2,000 次,种子 784,p = 抽样差 ≥ 0 的比例);成本 20 bps 往返。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]          # docs/research → 仓库根
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.data.evaluation import apparatus as ap  # noqa: E402  (零分布只许用这里的函数)

CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/_cache/t292")

# ── 写死的口径(S-771 / S-784)────────────────────────────────────────────
WIN_START = date(2020, 12, 1)      # 缓存窗口起点
TRAIL = 7                          # 过去 7 天(信号日及前 6 天)
FWD = 28                           # 之后 4 周
MCAP_MIN = 2e7                     # 市值 ≥ 2,000 万(美元)
SEED = 784
N_SHUFFLE = 1000
N_BOOT = 2000
BOOT_BLOCK = 4.0                   # 4 周块
COST = 0.0020                      # 20 bps 往返(50/50 多空组合 ⇒ 每边 10 bps 的净值口径)
SEG_A = (date(2021, 1, 1), date(2023, 12, 31))
SEG_B = (date(2024, 1, 1), date(2026, 12, 31))


# ── 小工具 ────────────────────────────────────────────────────────────────
def rankdata(a: np.ndarray) -> np.ndarray:
    """平均秩(并列取均值);不引 scipy。"""
    a = np.asarray(a, dtype=float)
    n = a.size
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    sa = a[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sa[j + 1] == sa[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size < 3:
        return float("nan")
    a = a - a.mean()
    b = b - b.mean()
    da, db = float(a @ a), float(b @ b)
    if da <= 0 or db <= 0:
        return float("nan")
    return float((a @ b) / math.sqrt(da * db))


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    return pearson(rankdata(a), rankdata(b))


def describe(x) -> dict:
    v = np.asarray([z for z in x if z is not None and np.isfinite(z)], dtype=float)
    if v.size == 0:
        return {"n": 0}
    q = np.percentile(v, [10, 50, 90])
    return {"n": int(v.size), "mean": float(v.mean()), "median": float(q[1]),
            "p10": float(q[0]), "p90": float(q[2]),
            "min": float(v.min()), "max": float(v.max()),
            "std": float(v.std(ddof=1)) if v.size > 1 else 0.0}


def wavg(y: np.ndarray, w: np.ndarray) -> float:
    sw = float(w.sum())
    return float((y * w).sum() / sw) if sw > 0 else float(y.mean())


# ── 读缓存(只读)───────────────────────────────────────────────────────────
def load_cache(cache: Path):
    up, usdt = {}, {}
    with open(cache / "upbit_daily.jsonl") as f:
        for line in f:
            r = json.loads(line)
            if r["market"] == "KRW-USDT":
                usdt[r["d"]] = float(r["c"])
            else:
                up.setdefault(r["symbol"], {})[r["d"]] = (float(r["c"]), float(r["vol_krw"]))
    binance = {}
    with open(cache / "ohlcv_binance_hist.csv") as f:
        for row in csv.DictReader(f):
            binance.setdefault(row["symbol"], {})[row["trade_date"]] = (float(row["close"]), float(row["volume"]))
    mcap = {}
    with open(cache / "mcap.jsonl") as f:
        for line in f:
            r = json.loads(line)
            mcap.setdefault(r["symbol"], {})[r["d"]] = tuple(
                None if r.get(k) is None else float(r[k]) for k in ("price", "mcap", "volume"))
    return up, usdt, binance, mcap


def gprice(sym: str, d: str, binance, mcap):
    """全球美元价:Binance 现货收盘,没有则 asset_mcap_daily 的价。"""
    b = binance.get(sym, {}).get(d)
    if b is not None and b[0] is not None:
        return b[0]
    m = mcap.get(sym, {}).get(d)
    return m[0] if (m is not None and m[0] is not None) else None


def gprice_pair(sym: str, d0: str, d1: str, binance, mcap):
    """入场 / 出场价取同一来源(避免跨场所拼接):优先 Binance(两天都有),否则 asset_mcap_daily。"""
    b = binance.get(sym, {})
    if d0 in b and d1 in b and b[d0][0] is not None and b[d1][0] is not None:
        return b[d0][0], b[d1][0]
    m = mcap.get(sym, {})
    if d0 in m and d1 in m and m[d0][0] is not None and m[d1][0] is not None:
        return m[d0][0], m[d1][0]
    return None, None


def gvol_usd(sym: str, d: str, binance, mcap, mode: str):
    """全球成交额(美元)。mode='same':与价格同源(Binance 优先,否则 asset_mcap_daily);
    mode='mcap':优先 asset_mcap_daily(全场所口径),没有才用 Binance(收盘 × 成交量)。"""
    b = binance.get(sym, {}).get(d)
    m = mcap.get(sym, {}).get(d)
    b_usd = (b[0] * b[1]) if (b is not None and b[0] is not None and b[1] is not None) else None
    m_usd = m[2] if (m is not None and m[2] is not None) else None
    if mode == "mcap":
        return m_usd if m_usd else b_usd
    return b_usd if b_usd else m_usd


def trail_median(getter, days) -> float | None:
    vals = []
    for d in days:
        v = getter(d)
        if v is not None and v > 0:
            vals.append(v)
    return float(np.median(vals)) if vals else None


# ── 面板:每个周一的面板行 ─────────────────────────────────────────────────
def build_panel(data, *, btc_in: bool, binance_mode: str, vol_mode: str,
                y_source: str = "global", p_def: str = "ratio_of_medians"):
    up, usdt, binance, mcap = data
    first_b = {s: min(v) for s, v in binance.items()}
    first_u = {s: min(v) for s, v in up.items()}
    first_g = {s: min(v) for s, v in mcap.items()}
    cands = sorted((set(up) & (set(binance) | set(mcap))) - {"USDT"})
    max_global_day = max(max(max(v) for v in binance.values()), max(max(v) for v in mcap.values()))

    weeks, rows = [], {}
    w = WIN_START + timedelta(days=(7 - WIN_START.weekday()) % 7)   # 第一个周一
    while w <= date(2026, 11, 9):
        d0 = w.isoformat()                                       # 入场日(信号日收盘)
        d1 = (w + timedelta(days=FWD)).isoformat()               # 出场日(4 周后)
        days = [(w - timedelta(days=k)).isoformat() for k in range(TRAIL - 1, -1, -1)]
        if d1 > max_global_day:
            w += timedelta(days=7)
            continue
        krw_btc_med = trail_median(lambda x: up.get("BTC", {}).get(x, (None,))[0], days)
        glob_btc_med = trail_median(lambda x: gprice("BTC", x, binance, mcap), days)
        if not krw_btc_med or not glob_btc_med:
            w += timedelta(days=7)
            continue
        if y_source == "upbit_krw":                      # 目标用韩元价算(Upbit KRW)
            btc_in_px = up.get("BTC", {}).get(d0, (None,))[0]
            btc_out_px = up.get("BTC", {}).get(d1, (None,))[0]
        else:                                            # 目标用全球美元价算
            btc_in_px, btc_out_px = gprice_pair("BTC", d0, d1, binance, mcap)
        if btc_in_px is None or btc_out_px is None:
            w += timedelta(days=7)
            continue
        if p_def == "median_of_ratios":                 # P = 7 天「对数比」的中位
            rr = [math.log(up["BTC"][x][0] / gprice("BTC", x, binance, mcap))
                  for x in days if x in up.get("BTC", {}) and gprice("BTC", x, binance, mcap)]
            p_btc = float(np.median(rr)) if rr else None
        else:                                            # P = 中位价之比
            p_btc = math.log(krw_btc_med / glob_btc_med)
        if p_btc is None:
            w += timedelta(days=7)
            continue
        btc_fwd = math.log(btc_out_px / btc_in_px)

        rs = []
        for s in cands:
            if binance_mode == "by_signal":
                fb = first_b.get(s)
                if fb is None or fb > w.isoformat():
                    continue
            elif binance_mode == "ever":
                if s not in binance:
                    continue
            # 'none':不要求 Binance 现货(口径偏离,只作对照)
            krw = up.get(s, {})
            krw_med = trail_median(lambda x: krw.get(x, (None,))[0], days)
            g_med = trail_median(lambda x: gprice(s, x, binance, mcap), days)
            if not krw_med or not g_med:
                continue
            # 市值 ≥ 2,000 万(信号日;取窗口内最近的已知值)
            mc_val = None
            for x in days:
                mm = mcap.get(s, {}).get(x)
                if mm is not None:
                    mc_val = mm[1]
                    break
            if mc_val is None or mc_val < MCAP_MIN:
                continue
            # 之后 4 周相对 BTC 的超额
            if y_source == "upbit_krw":
                px0 = up.get(s, {}).get(d0, (None,))[0]
                px1 = up.get(s, {}).get(d1, (None,))[0]
            else:
                px0, px1 = gprice_pair(s, d0, d1, binance, mcap)
            if px0 is None or px1 is None or px0 <= 0:
                continue
            y = math.log(px1 / px0) - btc_fwd
            if p_def == "median_of_ratios":
                rr = []
                for x in days:
                    kv, gv = krw.get(x), gprice(s, x, binance, mcap)
                    if kv and gv and gv > 0:
                        rr.append(math.log(kv[0] / gv))
                if not rr:
                    continue
                p_i = float(np.median(rr)) - p_btc
            else:
                p_i = math.log(krw_med / g_med) - p_btc

            # S:Upbit KRW 成交额 / (全球成交额 × USDKRW),过去 7 天和;上市之前的周不算
            s_i = None
            fu, fg = first_u.get(s), first_g.get(s)
            if fu and fg and fu <= days[0] and fg <= days[0]:
                num = den = 0.0
                ndays = 0
                for x in days:
                    fx = usdt.get(x)
                    vk = krw.get(x)
                    vg = gvol_usd(s, x, binance, mcap, vol_mode)
                    if fx is None or vk is None or vg is None or vg <= 0:
                        continue
                    num += vk[1]
                    den += vg * fx
                    ndays += 1
                if ndays >= 5 and den > 0:
                    s_i = num / den
            if s == "BTC" and not btc_in:
                continue
            rs.append({"sym": s, "P": p_i, "S": s_i, "y": y, "mcap": mc_val})
        if rs:
            weeks.append(w)
            rows[w] = rs
        w += timedelta(days=7)
    return weeks, rows


# ── 每周统计 ──────────────────────────────────────────────────────────────
def week_row(rs, key):
    sig = np.array([r[key] for r in rs if r[key] is not None], dtype=float)
    y = np.array([r["y"] for r in rs if r[key] is not None], dtype=float)
    wt = np.array([r["mcap"] for r in rs if r[key] is not None], dtype=float)
    if sig.size < 3:
        return None
    out = {"n": int(sig.size)}
    if sig.size >= 4:
        out["ic_spear"] = spearman(sig, y)
        out["ic_pear"] = pearson(sig, y)
    if sig.size >= 5:
        order = np.argsort(sig, kind="mergesort")
        g = np.array_split(order, 5)
        out["q5_mc"] = wavg(y[g[4]], wt[g[4]])
        out["q1_mc"] = wavg(y[g[0]], wt[g[0]])
        out["spread_mc"] = out["q5_mc"] - out["q1_mc"]
        out["q5_ew"] = float(y[g[4]].mean())
        out["q1_ew"] = float(y[g[0]].mean())
        out["spread_ew"] = out["q5_ew"] - out["q1_ew"]
    return out


def signal_stats(weeks, rows, key):
    """返回该信号(每周一个截面)的 IC 序列与价差序列。"""
    ic_rows, sp_rows, wk_ic, wk_sp = [], [], [], []
    for w in weeks:
        r = week_row(rows[w], key)
        if r is None:
            continue
        if "ic_spear" in r:
            sig = np.array([x[key] for x in rows[w] if x[key] is not None], dtype=float)
            y = np.array([x["y"] for x in rows[w] if x[key] is not None], dtype=float)
            ic_rows.append((sig, y))
            wk_ic.append((w, r["ic_spear"], r["ic_pear"], r["n"]))
        if "spread_mc" in r:
            sig = np.array([x[key] for x in rows[w] if x[key] is not None], dtype=float)
            y = np.array([x["y"] for x in rows[w] if x[key] is not None], dtype=float)
            wt = np.array([x["mcap"] for x in rows[w] if x[key] is not None], dtype=float)
            sp_rows.append((sig, y, wt))
            wk_sp.append((w, r["spread_mc"], r["spread_ew"], r["q1_mc"], r["q5_mc"], r["q1_ew"], r["q5_ew"], r["n"]))
    return {"ic_rows": ic_rows, "sp_rows": sp_rows, "wk_ic": wk_ic, "wk_sp": wk_sp}


# ── 零分布(只用 apparatus)────────────────────────────────────────────────
def shuffle_null_ic(ic_rows, actual, n=N_SHUFFLE, seed=SEED):
    """周内打乱:每周内把信号值随机置换归属 → 重算每周 IC → 取全样本均值。"""
    if not ic_rows:
        return None, None
    sig_all = np.concatenate([r[0] for r in ic_rows])
    grp = np.concatenate([np.full(r[0].size, i, dtype=object) for i, r in enumerate(ic_rows)])
    sizes = [r[0].size for r in ic_rows]

    def one(rng):
        perm = np.asarray(ap.shuffle_within(np.arange(sig_all.size), grp, rng), dtype=int)
        vals, off = [], 0
        for sig, y in ic_rows:
            k = sizes[len(vals)]
            vals.append(spearman(sig[perm[off:off + k] - off], y))
            off += k
        return float(np.mean(vals))

    try:
        null = ap.null_distribution(one, n, seed, actual=actual)
    except ap.NoOpNull as e:
        return None, str(e)
    return ap.percentile_of(actual, null), null


def shuffle_null_spread(sp_rows, actual, n=N_SHUFFLE, seed=SEED):
    """周内打乱:置换信号 → 重算每周市值加权 Q5 − Q1 → 取全样本均值。"""
    if not sp_rows:
        return None, None
    sig_all = np.concatenate([r[0] for r in sp_rows])
    grp = np.concatenate([np.full(r[0].size, i, dtype=object) for i, r in enumerate(sp_rows)])
    sizes = [r[0].size for r in sp_rows]

    def one(rng):
        perm = np.asarray(ap.shuffle_within(np.arange(sig_all.size), grp, rng), dtype=int)
        vals, off = [], 0
        for sig, y, wt in sp_rows:
            k = sizes[len(vals)]
            s2 = sig[perm[off:off + k] - off]
            off += k
            order = np.argsort(s2, kind="mergesort")
            g = np.array_split(order, 5)
            vals.append(wavg(y[g[4]], wt[g[4]]) - wavg(y[g[0]], wt[g[0]]))
        return float(np.mean(vals))

    try:
        null = ap.null_distribution(one, n, seed, actual=actual)
    except ap.NoOpNull as e:
        return None, str(e)
    return ap.percentile_of(actual, null), null


def block_boot_p(series, n_boot=N_BOOT, seed=SEED, block=BOOT_BLOCK):
    """平稳块自助(Politis–Romano,平均块长 = 4 周):p = 抽样均值 ≥ 0 的比例。"""
    v = np.asarray([z for z in series if z is not None and np.isfinite(z)], dtype=float)
    if v.size < 5:
        return None
    rng = np.random.default_rng(seed)
    idx = ap.stationary_bootstrap_index(int(v.size), float(block), int(n_boot), rng)
    boot = v[idx].mean(axis=1)
    return {"p_ge0": float((boot >= 0).mean()), "p_le0": float((boot <= 0).mean()),
            "boot_mean": float(boot.mean()), "boot_sd": float(boot.std(ddof=1)),
            "n_weeks": int(v.size), "mean_block": float(block), "n_boot": int(n_boot), "seed": seed}


# ── 一个变体的一整套统计 ─────────────────────────────────────────────────
def run_variant(data, name, **kw):
    weeks, rows = build_panel(data, **kw)
    out = {"name": name, "params": {k: v for k, v in kw.items()},
           "n_weeks": len(weeks),
           "first_week": weeks[0].isoformat() if weeks else None,
           "last_week": weeks[-1].isoformat() if weeks else None}
    ns = [len(rows[w]) for w in weeks]
    out["cross_section"] = describe(ns)
    for key, kname in (("P", "P"), ("S", "S")):
        st = signal_stats(weeks, rows, key)
        ic_series = [x[1] for x in st["wk_ic"]]
        ic_p = [x[2] for x in st["wk_ic"]]
        sp = [x[1] for x in st["wk_sp"]]
        sp_ew = [x[2] for x in st["wk_sp"]]
        q1 = [x[3] for x in st["wk_sp"]]
        q5 = [x[4] for x in st["wk_sp"]]
        blk = {"weeks_with_signal": len(st["wk_ic"]), "weeks_with_quintile": len(st["wk_sp"])}
        if ic_series:
            t, m, se = ap.newey_west_t(ic_series, lags=5)
            t4, m4, se4 = ap.newey_west_t(ic_series, lags=4)
            tp, mp, sep = ap.newey_west_t(ic_p, lags=5)
            blk["ic_spearman"] = {"dist": describe(ic_series), "nw_t_lag5": t, "nw_mean": m, "nw_se": se,
                                  "nw_t_lag4": t4, "nw_mean_lag4": m4,
                                  "ic_pearson": {"dist": describe(ic_p), "nw_t_lag5": tp, "nw_mean": mp}}
            pct, null = shuffle_null_ic(st["ic_rows"], m)
            blk["ic_spearman"]["shuffle_percentile"] = pct
            blk["ic_spearman"]["shuffle_null_mean"] = float(np.mean(null)) if null is not None else None
            blk["ic_spearman"]["shuffle_null_sd"] = float(np.std(null, ddof=1)) if null is not None else None
            blk["ic_spearman"]["block_boot"] = block_boot_p(ic_series)
        if sp:
            t, m, se = ap.newey_west_t(sp, lags=5)
            blk["spread_mcapw"] = {"dist": describe(sp), "net20_dist": describe([z - COST for z in sp]),
                                   "net40_dist": describe([z - 2 * COST for z in sp]),
                                   "nw_t_lag5": t, "nw_mean": m, "nw_se": se}
            pct, null = shuffle_null_spread(st["sp_rows"], m)
            blk["spread_mcapw"]["shuffle_percentile"] = pct
            blk["spread_mcapw"]["shuffle_null_mean"] = float(np.mean(null)) if null is not None else None
            blk["spread_mcapw"]["block_boot"] = block_boot_p(sp)
            blk["spread_equalw"] = {"dist": describe(sp_ew),
                                    "nw_t_lag5": ap.newey_west_t(sp_ew, lags=5)[0]}
            blk["q1_only_mcapw"] = {"dist": describe(q1), "nw_t_lag5": ap.newey_west_t(q1, lags=5)[0]}
            blk["q5_only_mcapw"] = {"dist": describe(q5), "nw_t_lag5": ap.newey_west_t(q5, lags=5)[0]}
        # 两段同号
        seg = {}
        for label, (lo, hi) in (("2021-2023", SEG_A), ("2024-2026", SEG_B)):
            wi = [x for x in st["wk_ic"] if lo <= x[0] <= hi]
            ws = [x for x in st["wk_sp"] if lo <= x[0] <= hi]
            seg[label] = {"n_weeks_ic": len(wi), "ic_mean": float(np.mean([x[1] for x in wi])) if wi else None,
                          "ic_nw_t": ap.newey_west_t([x[1] for x in wi], lags=5)[0] if len(wi) >= 7 else None,
                          "n_weeks_sp": len(ws),
                          "spread_mean": float(np.mean([x[1] for x in ws])) if ws else None,
                          "spread_nw_t": ap.newey_west_t([x[1] for x in ws], lags=5)[0] if len(ws) >= 7 else None}
        a, b = seg["2021-2023"], seg["2024-2026"]
        seg["same_sign_ic"] = (None if a["ic_mean"] is None or b["ic_mean"] is None
                               else bool(np.sign(a["ic_mean"]) == np.sign(b["ic_mean"])))
        seg["same_sign_spread"] = (None if a["spread_mean"] is None or b["spread_mean"] is None
                                   else bool(np.sign(a["spread_mean"]) == np.sign(b["spread_mean"])))
        blk["segments"] = seg
        out[kname] = blk
    return out


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--cache", default=str(CACHE))
    ap_.add_argument("--out", default=str(HERE / "t302_results.json"))
    args = ap_.parse_args()
    cache = Path(args.cache)
    data = load_cache(cache)
    up, usdt, binance, mcap = data

    meta = {
        "cache": str(cache),
        "upbit_symbols": len(up), "upbit_usdt_days": len(usdt),
        "usdt_first": min(usdt) if usdt else None, "usdt_last": max(usdt) if usdt else None,
        "binance_symbols": len(binance), "mcap_symbols": len(mcap),
        "universe_upbit_and_global": len(set(up) & (set(binance) | set(mcap))),
        "universe_binance_listed": len(set(up) & set(binance)),
        "params": {"trail_days": TRAIL, "fwd_days": FWD, "mcap_min": MCAP_MIN, "cost_bps": 20,
                   "shuffle_n": N_SHUFFLE, "boot_n": N_BOOT, "boot_block_weeks": BOOT_BLOCK, "seed": SEED},
    }
    # 诚实注记:下架 / 提前消失的市场(之后 4 周不可观测)
    last_d = {s: max(v) for s, v in up.items()}
    meta["upbit_markets_total"] = len(last_d)
    meta["upbit_markets_ended_before_2026_06"] = sum(1 for v in last_d.values() if v < "2026-06-01")
    meta["upbit_markets_ended_before_2025_01"] = sum(1 for v in last_d.values() if v < "2025-01-01")

    variants = {
        "primary": dict(btc_in=False, binance_mode="by_signal", vol_mode="same"),
        "btc_in": dict(btc_in=True, binance_mode="by_signal", vol_mode="same"),
        "binance_ever": dict(btc_in=False, binance_mode="ever", vol_mode="same"),
        "vol_mcap": dict(btc_in=False, binance_mode="by_signal", vol_mode="mcap"),
        # 口径对照(为解释与 S-771 的差异;不替换主结果)
        "y_upbit_krw": dict(btc_in=False, binance_mode="by_signal", vol_mode="same", y_source="upbit_krw"),
        "p_median_of_ratios": dict(btc_in=False, binance_mode="by_signal", vol_mode="same", p_def="median_of_ratios"),
        "no_binance_filter": dict(btc_in=False, binance_mode="none", vol_mode="same"),
        "y_krw_and_medratio": dict(btc_in=False, binance_mode="by_signal", vol_mode="same",
                                   y_source="upbit_krw", p_def="median_of_ratios"),
    }
    out = {"task": "T-302", "ledger": {"S-771": "REFUTATION_LEDGER.md §S-771(预注册原文)", "S-784": "REFUTATION_LEDGER.md §S-784"},
           "meta": meta, "variants": {}}
    for name, kw in variants.items():
        out["variants"][name] = run_variant(data, name, **kw)
        print(f"[done] {name}", flush=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("WROTE", args.out)


if __name__ == "__main__":
    main()
