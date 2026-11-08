#!/usr/bin/env python3
"""T-304 / S-787(只报不判)— 全市场韩国溢价(「泡菜溢价」)与之后 30 / 90 天的 BTC 与 ① 面板 24 名。

口径照抄 S-787(REFUTATION_LEDGER.md L32087-32089)+ 卡 T-304 的 acceptance:
  K   = kimchi_premium_daily.prem 的 7 日均值(尾随 7 个日历日,≥5 个有效天才算)
  K_z = K 相对自身前 365 个日历日的 z(≥180 个有效天才算)
  报  K_z 五分位 × {BTC, ① 面板 24 名} 之后 30 / 90 天收益 + 90 天内最大回撤
       K 顶点段(> 前 365 天 95 分位)起止 + 与 BTC 顶点的先后天数
       K < 0 连续段之后 30 / 90 天
  块置换(30 天块、1,000 次、种子 787)只给分位、不给判定。零分布只用 apparatus。

只算:不入库、不改生产代码。
输入缓存:/Volumes/CometCloudAI/cometcloud-local/research/_cache/t304/(拉数脚本 t304_pull.py)
输出:docs/research/t304_results.json
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/_cache/t304")

PANEL24 = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT",
           "LTC", "TRX", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI", "UNI", "AAVE",
           "INJ", "FIL", "ETC", "BCH"]
HORIZONS = (30, 90)
SEED = 787
N_PERM = 1000
BLOCK = 30
ERAS = [("E1_2018-03_2019-12", "2018-03-28", "2019-12-31"),
        ("E2_2020_2021", "2020-01-01", "2021-12-31"),
        ("E3_2022_2026", "2022-01-01", "2026-11-07")]


def load_apparatus():
    p = HERE.parents[1] / "src" / "data" / "evaluation" / "apparatus.py"
    spec = importlib.util.spec_from_file_location("apparatus", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AP = load_apparatus()


def pct(x):
    return None if x is None or not math.isfinite(float(x)) else float(x)


def desc(vals):
    """中位 / 均值 / p10 / p90 / n。"""
    v = np.asarray([x for x in vals if x is not None and math.isfinite(float(x))], dtype=float)
    if v.size == 0:
        return {"n": 0}
    return {
        "n": int(v.size),
        "median": float(np.median(v)),
        "mean": float(v.mean()),
        "p10": float(np.quantile(v, 0.10)),
        "p90": float(np.quantile(v, 0.90)),
        "std": float(v.std(ddof=1)) if v.size > 1 else None,
    }


def fwd(series, h):
    """t → t+h 的收益(精确日历日);缺失 ⇒ None。"""
    idx = series.index
    pos = {d: i for i, d in enumerate(idx)}
    out = {}
    for d in idx:
        j = pos.get(d + pd.Timedelta(days=h))
        if j is None:
            continue
        a, b = series.iloc[pos[d]], series.iloc[j]
        if pd.isna(a) or pd.isna(b) or a <= 0 or b <= 0:
            continue
        out[d] = float(b / a - 1.0)
    return out


def mdd(series, h):
    """t → t+h 路径上的最大回撤(以 t 为起点)。"""
    idx = series.index
    pos = {d: i for i, d in enumerate(idx)}
    out = {}
    for d in idx:
        i = pos[d]
        j = pos.get(d + pd.Timedelta(days=h))
        if j is None:
            continue
        path = series.iloc[i:j + 1].to_numpy(dtype=float)
        if len(path) < 2 or np.isnan(path).any() or (path <= 0).any():
            continue
        run_max = np.maximum.accumulate(path)
        out[d] = float((path / run_max - 1.0).min())
    return out


def spearman(x, y):
    """描述用的 Spearman 秩相关(单因子,全样本;不做检验)。"""
    a = np.asarray([xi for xi, yi in zip(x, y) if xi is not None and yi is not None
                    and math.isfinite(float(xi)) and math.isfinite(float(yi))], dtype=float)
    b = np.asarray([yi for xi, yi in zip(x, y) if xi is not None and yi is not None
                    and math.isfinite(float(xi)) and math.isfinite(float(yi))], dtype=float)
    if a.size < 3:
        return None
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


# ── 载入 ────────────────────────────────────────────────────────────────────
kim = json.loads((CACHE / "kimchi.json").read_text())
kd = pd.DataFrame(kim)
kd["d"] = pd.to_datetime(kd["d"])
kd = kd.sort_values("d").set_index("d")
cal = pd.date_range(kd.index.min(), kd.index.max(), freq="D")
prem = kd["prem"].reindex(cal).astype(float)

px = {}
for s in sorted(set(PANEL24) | {"BTC"}):
    rows = json.loads((CACHE / f"px_{s}.json").read_text())
    ser = pd.Series({pd.Timestamp(r["trade_date"]): float(r["close"]) for r in rows if r.get("close")})
    px[s] = ser.reindex(cal).astype(float)

closes = pd.DataFrame(px)[PANEL24]
rets = closes.pct_change(fill_method=None)
n_names = rets.notna().sum(axis=1)
panel_r = rets.mean(axis=1, skipna=True)
panel_v = (1.0 + panel_r.fillna(0.0)).cumprod()
btc = px["BTC"]

# ── K / K_z ─────────────────────────────────────────────────────────────────
K = prem.rolling(7, min_periods=5).mean()


def make_kz(start=None):
    """K 的尾随 365 天 z;start 之后才允许 K 有效(用于剔除早期薄流动性段)。"""
    k = K if start is None else K.where(K.index >= pd.Timestamp(start))
    w = k.shift(1).rolling(365, min_periods=180)
    return (k - w.mean()) / w.std(ddof=1)


KZ_FULL = make_kz()
KZ_NO_EARLY = make_kz("2018-07-01")

# ── 前瞻收益 / 回撤 ─────────────────────────────────────────────────────────
btc_fwd = {h: fwd(btc, h) for h in HORIZONS}
panel_fwd = {h: fwd(panel_v, h) for h in HORIZONS}
btc_mdd = {h: mdd(btc, h) for h in HORIZONS}
panel_mdd = {h: mdd(panel_v, h) for h in HORIZONS}
ASSETS = {"BTC": (btc_fwd, btc_mdd), "PANEL24": (panel_fwd, panel_mdd)}


# ── 五分位方案 ──────────────────────────────────────────────────────────────
def assign_global(kz):
    edges = np.quantile(kz, [0.2, 0.4, 0.6, 0.8])
    return pd.Series(np.searchsorted(edges, kz, side="right") + 1, index=kz.index), edges


def assign_expanding(kz):
    """扩展窗(时点)五分位:每一天用当时为止的分布定档。"""
    q = kz.expanding(min_periods=60).rank(pct=True)
    q = (q * 5).apply(lambda x: int(np.ceil(x)) if pd.notna(x) else np.nan)
    return q.astype(float), None


def qmean_stat(qser, fwd_d, h, q=5):
    a = [fwd_d[h].get(d) for d in qser.index if qser[d] == q]
    a = [x for x in a if x is not None]
    return float(np.mean(a)) if a else None


def spread_stat(qser, fwd_d, h, q_hi=5, q_lo=1):
    a = [fwd_d[h].get(d) for d in qser.index if qser[d] == q_hi]
    b = [fwd_d[h].get(d) for d in qser.index if qser[d] == q_lo]
    a = [x for x in a if x is not None]
    b = [x for x in b if x is not None]
    if not a or not b:
        return None
    return float(np.mean(a) - np.mean(b))


SCHEMES = [
    {"name": "global", "kz": KZ_FULL, "assign": assign_global},
    {"name": "expanding_pit", "kz": KZ_FULL, "assign": assign_expanding},
    {"name": "kz_ex_early", "kz": KZ_NO_EARLY, "assign": assign_global},
]


def build_table(qser):
    rows = []
    for asset, (fwd_d, mdd_d) in ASSETS.items():
        for h in HORIZONS:
            for q in (1, 2, 3, 4, 5):
                ds = [d for d in qser.index if qser[d] == q]
                rows.append({"asset": asset, "h": h, "q": q,
                             "ret": desc([fwd_d[h].get(d) for d in ds]),
                             "mdd90": desc([mdd_d[h].get(d) for d in ds])})
    return rows


def era_table(qser):
    out = []
    for asset, (fwd_d, mdd_d) in ASSETS.items():
        for h in HORIZONS:
            for era, lo, hi in ERAS:
                lo, hi = pd.Timestamp(lo), pd.Timestamp(hi)
                for q in (1, 5):
                    ds = [d for d in qser.index if qser[d] == q and lo <= d <= hi]
                    out.append({"asset": asset, "h": h, "era": era, "q": q,
                                "ret": desc([fwd_d[h].get(d) for d in ds]),
                                "mdd90": desc([mdd_d[h].get(d) for d in ds])})
    return out


def permutation_null(scheme, qser):
    """打乱 K_z 的 30 天块 → 重算五分位 → 重算统计量 → 分位。只给分位,不给判定。

    零分布机器:apparatus.null_distribution(种子 787、1,000 次)驱动抽样,
    apparatus.block_permute 做 30 天块置换,apparatus.percentile_of 给分位。
    每次抽样同时算完所有统计量(否则 24 个统计量各抽 1,000 次,太慢)。
    """
    kz = scheme["kz"].dropna()
    kz_col = kz.to_numpy(dtype=float)
    out = {}

    def stats_for(q):
        r = {}
        for asset, (fwd_d, mdd_d) in ASSETS.items():
            for h in HORIZONS:
                r[f"{asset}|{h}|q5_mean"] = qmean_stat(q, fwd_d, h, 5)
                r[f"{asset}|{h}|spread_q5_q1"] = spread_stat(q, fwd_d, h, 5, 1)
                m5 = [mdd_d[h].get(d) for d in q.index if q[d] == 5]
                m5 = [x for x in m5 if x is not None]
                r[f"{asset}|{h}|q5_mdd90_mean"] = float(np.mean(m5)) if m5 else None
        return r

    actual = stats_for(qser)
    keys = list(actual.keys())
    draws = []

    def draw(rng):
        perm = AP.block_permute(kz_col, BLOCK, rng)
        q, _ = scheme["assign"](pd.Series(perm, index=kz.index))
        st = stats_for(q)
        draws.append(st)
        v = st[keys[0]]
        return float(v) if v is not None else float("nan")

    AP.null_distribution(draw, N_PERM, SEED, actual=None)
    assert len(draws) == N_PERM, len(draws)
    for k in keys:
        arr = np.asarray([d.get(k) for d in draws if d.get(k) is not None], dtype=float)
        a = actual[k]
        out[k] = {"actual": pct(a),
                  "null_pct": pct(AP.percentile_of(a, arr)) if (a is not None and arr.size) else None,
                  "null_median": float(np.median(arr)) if arr.size else None,
                  "null_p10": float(np.quantile(arr, 0.10)) if arr.size else None,
                  "null_p90": float(np.quantile(arr, 0.90)) if arr.size else None,
                  "null_n": int(arr.size)}
    return out


# ── 顶点段 / 折价段 ─────────────────────────────────────────────────────────
def runs(mask: pd.Series, min_len=1):
    """连续 True 段。"""
    idx = list(mask.index)
    out, i = [], 0
    while i < len(idx):
        if mask.iloc[i]:
            j = i
            while j + 1 < len(idx) and mask.iloc[j + 1]:
                j += 1
            out.append((idx[i], idx[j]))
            i = j + 1
        else:
            i += 1
    return [(a, b) for a, b in out if (b - a).days + 1 >= min_len]


w_full = K.shift(1).rolling(365, min_periods=180)
thr95 = w_full.quantile(0.95)
k_hist = K.dropna()

top_segs = runs((K > thr95).fillna(False))
neg_segs = runs((K < 0).fillna(False))

btc_vals = btc.dropna()
btc_tops = []
for d in btc_vals.index:
    lo, hi = d - pd.Timedelta(days=60), d + pd.Timedelta(days=60)
    win = btc_vals[(btc_vals.index >= lo) & (btc_vals.index <= hi)]
    rest = win.drop(d)
    if len(win) and btc_vals[d] >= win.max() and (len(rest) == 0 or btc_vals[d] > rest.max()):
        btc_tops.append(d)

top_detail = []
for a, b in top_segs:
    seg = K.loc[a:b]
    peak = seg.idxmax()
    cands = [t for t in btc_tops if abs((t - peak).days) <= 180]
    near = min(cands, key=lambda t: abs((t - peak).days)) if cands else None
    top_detail.append({
        "start": str(a.date()), "end": str(b.date()), "len_days": int((b - a).days + 1),
        "k_peak": float(seg.max()), "k_peak_date": str(peak.date()),
        "btc_top_near": str(near.date()) if near is not None else None,
        "k_minus_btc_days": int((peak - near).days) if near is not None else None,
        "btc_close_at_k_peak": pct(btc_vals.get(peak)),
        "btc_fwd30_at_k_peak": pct(btc_fwd[30].get(peak)),
        "btc_fwd90_at_k_peak": pct(btc_fwd[90].get(peak)),
    })

neg_detail = []
for a, b in neg_segs:
    seg = K.loc[a:b]
    neg_detail.append({
        "start": str(a.date()), "end": str(b.date()), "len_days": int((b - a).days + 1),
        "k_min": float(seg.min()), "k_mean": float(seg.mean()),
        "btc_fwd30_from_end": pct(btc_fwd[30].get(b)),
        "btc_fwd90_from_end": pct(btc_fwd[90].get(b)),
        "panel_fwd30_from_end": pct(panel_fwd[30].get(b)),
        "panel_fwd90_from_end": pct(panel_fwd[90].get(b)),
        "btc_fwd30_from_start": pct(btc_fwd[30].get(a)),
        "btc_fwd90_from_start": pct(btc_fwd[90].get(a)),
    })

# ── 输出 ────────────────────────────────────────────────────────────────────
res = {
    "card": "T-304", "ledger": "S-787", "kind": "只报不判(report only, no verdict)",
    "spec": {
        "K": "kimchi_premium_daily.prem 的尾随 7 个日历日均值(≥5 个有效天)",
        "K_z": "(K − 前 365 个日历日 K 的均值) / 同窗标准差(ddof=1,≥180 个有效天)",
        "panel": "① 面板 24 名(docs/research/s694_avoid_tilt.sql L34),等权日再平衡,当日有价的名字等权",
        "btc": "ohlcv_daily(source=binance_hist, symbol=BTC) 收盘",
        "fwd": "t → t+h(精确日历日),h ∈ {30, 90}",
        "mdd90": "t → t+90 日收盘路径上的最大回撤(起点为 t)",
        "null": f"块置换(30 天块、{N_PERM} 次、种子 {SEED});apparatus.block_permute / null_distribution / percentile_of",
        "note": "块置换分位是「实际值在零分布里的中秩分位」;只报分位,不给判定。",
    },
    "coverage": {
        "kimchi_days": int(len(kd)), "kimchi_first": str(kd.index.min().date()), "kimchi_last": str(kd.index.max().date()),
        "calendar_days": int(len(cal)),
        "K_valid_days": int(K.notna().sum()),
        "K_z_valid_days": int(KZ_FULL.notna().sum()),
        "K_z_first": str(KZ_FULL.dropna().index.min().date()), "K_z_last": str(KZ_FULL.dropna().index.max().date()),
        "K_z_ex_early_days": int(KZ_NO_EARLY.notna().sum()),
        "K_z_ex_early_first": str(KZ_NO_EARLY.dropna().index.min().date()),
        "btc_days": int(btc.notna().sum()),
        "panel_days_with_return": int(panel_r.notna().sum()),
        "panel_names_first_day": int(n_names.dropna().iloc[0]) if len(n_names.dropna()) else 0,
        "panel_names_last_day": int(n_names.dropna().iloc[-1]) if len(n_names.dropna()) else 0,
        "panel_names_min": int(n_names.min()), "panel_names_max": int(n_names.max()),
        "fwd_counts": {f"{a}|{h}": len(ASSETS[a][0][h]) for a in ASSETS for h in HORIZONS},
        "btc_close_last": float(btc.dropna().iloc[-1]), "btc_close_last_d": str(btc.dropna().index[-1].date()),
        "usdkrw_last": float(kd["usdkrw"].dropna().iloc[-1]), "usdkrw_last_d": str(kd["usdkrw"].dropna().index[-1].date()),
    },
    "K_stats": {
        "mean": float(k_hist.mean()), "median": float(k_hist.median()),
        "p10": float(k_hist.quantile(0.10)), "p90": float(k_hist.quantile(0.90)),
        "min": float(k_hist.min()), "min_date": str(k_hist.idxmin().date()),
        "max": float(k_hist.max()), "max_date": str(k_hist.idxmax().date()),
        "n_days_below_zero": int((K < 0).sum()),
        "K_z_mean": float(KZ_FULL.dropna().mean()), "K_z_std": float(KZ_FULL.dropna().std(ddof=1)),
        "n_days_prem_gt_0_15": int((prem > 0.15).sum()),
        "prem_gt_015_first": str(prem[prem > 0.15].index.min().date()) if (prem > 0.15).any() else None,
        "prem_gt_015_last": str(prem[prem > 0.15].index.max().date()) if (prem > 0.15).any() else None,
    },
    "independent_segments": {
        "n_k_lt0_segments": len(neg_detail),
        "n_k_top_segments": len(top_detail),
        "n_nonoverlap_90d_blocks_in_Kz": int(len(KZ_FULL.dropna()) // 90),
        "n_nonoverlap_30d_blocks_in_Kz": int(len(KZ_FULL.dropna()) // 30),
        "n_btc_tops_pm60d": len(btc_tops),
    },
    "schemes": {},
    "top_segments": {"n": len(top_detail), "btc_tops": [str(t.date()) for t in btc_tops], "detail": top_detail},
    "discount_segments": {"n": len(neg_detail), "detail": neg_detail},
}

for sch in SCHEMES:
    kz = sch["kz"].dropna()
    qser, edges = sch["assign"](kz)
    nulls = permutation_null(sch, qser)
    counts = qser.value_counts().sort_index().to_dict()
    # 描述用 IC(单因子、全样本;不是检验)
    ic = {}
    for asset, (fwd_d, mdd_d) in ASSETS.items():
        for h in HORIZONS:
            xs = [qser[d] for d in qser.index]
            ys = [fwd_d[h].get(d) for d in qser.index]
            ic[f"{asset}|{h}"] = pct(spearman(xs, ys))
    res["schemes"][sch["name"]] = {
        "kz_first": str(kz.index.min().date()), "kz_last": str(kz.index.max().date()), "kz_days": int(len(kz)),
        "quintile_edges_global": [float(x) for x in edges] if edges is not None else None,
        "quintile_counts": {str(k): int(v) for k, v in counts.items()},
        "table": build_table(qser),
        "eras": era_table(qser),
        "spearman_ic": ic,
        "null": nulls,
    }

(HERE / "t304_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
print("written:", HERE / "t304_results.json")
print("K_z days:", res["coverage"]["K_z_valid_days"], "| top segs:", len(top_detail), "| neg segs:", len(neg_detail))
print("btc tops:", [str(t.date()) for t in btc_tops])
for sch in SCHEMES:
    print(sch["name"], res["schemes"][sch["name"]]["quintile_counts"], res["schemes"][sch["name"]]["spearman_ic"])
