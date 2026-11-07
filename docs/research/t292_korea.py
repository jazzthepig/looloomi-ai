"""T-292 / S-771 韩国溢价与韩国成交份额(横截面)—— 分析。

口径(照抄 S-771 预注册,只算一次):
  每周一 t:  P_i = ln(KRW 收盘_i / 全球美元收盘_i) − ln(KRW 收盘_BTC / 全球美元收盘_BTC),过去 7 天中位
             S_i = Upbit KRW 成交额 / (全球成交额 × USDKRW),过去 7 天和(USDKRW = Upbit KRW-USDT 收盘;
                   上市前的周不算 S)
  截面:      当周两边有价 + Binance 现货在 + 市值 ≥ 2,000 万
  目标:      之后 4 周相对 BTC 的超额
判(P、S 各自,BH 两条): IC 均值 < 0 且 NW t ≤ −2;最高五分位 − 最低五分位 < 0;周内打乱 1,000 次分位 ≤ 0.05;
             2021–2023 / 2024–2026 两段同号。
「按金额」附加判据(Jazz 11-07 规则):五分位差按**市值加权**算,扣一轮往返成本 20 bps,块自助分位 ≤ 0.05。

零分布 / 盈亏只用 src/data/evaluation/apparatus.py。
"""
import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from data.evaluation.apparatus import (  # noqa: E402
    newey_west_t, null_distribution, percentile_of, shuffle_within, stationary_bootstrap_index,
)

CACHE = Path(os.environ.get("T292_CACHE", "/Volumes/CometCloudAI/cometcloud-local/research/_cache/t292"))
RES = ROOT / "docs/research/t292_results.json"

WIN_START = "2021-01-04"       # 第一个计入的周一
SIGNAL_DAYS = 7                # 过去 7 天
MIN_VALID = 5                  # 7 天里至少 5 天有效
MCAP_MIN = 2.0e7               # 市值门槛 2,000 万
HOLD_DAYS = 28                 # 4 周(入场 t+1 收盘,出场 t+29 收盘)
COST_RT = 0.0020               # 一轮往返成本 20 bps(单边 10 bps taker)
N_NULL = 1000
SEED = 771
N_BOOT = 2000
BOOT_BLOCK = 4.0               # 平稳块自助:平均块长 4 周(目标重叠长度)

# ── 读数 ─────────────────────────────────────────────────────────────────────
up = pd.read_json(CACHE / "upbit_daily.jsonl", lines=True)
oh = pd.read_csv(CACHE / "ohlcv_binance_hist.csv")
mc = pd.read_json(CACHE / "mcap.jsonl", lines=True)
up["d"] = up["d"].astype(str)
oh["trade_date"] = oh["trade_date"].astype(str)
mc["d"] = mc["d"].astype(str)

dates = sorted(set(up["d"]) | set(oh["trade_date"]))
didx = {d: i for i, d in enumerate(dates)}
D = len(dates)
syms = sorted(set(up["symbol"]) | set(oh["symbol"]) | set(mc["symbol"]))
sidx = {s: i for i, s in enumerate(syms)}
S = len(syms)

krw_c = np.full((D, S), np.nan)
krw_qv = np.full((D, S), np.nan)
usd_c = np.full((D, S), np.nan)
usd_qv = np.full((D, S), np.nan)
mcap = np.full((D, S), np.nan)

ui = up["d"].map(didx).values
uj = up["symbol"].map(sidx).values
krw_c[ui, uj] = pd.to_numeric(up["c"], errors="coerce").values
krw_qv[ui, uj] = pd.to_numeric(up["vol_krw"], errors="coerce").values

oi = oh["trade_date"].map(didx).values
oj = oh["symbol"].map(sidx).values
oc = pd.to_numeric(oh["close"], errors="coerce").values
ov = pd.to_numeric(oh["volume"], errors="coerce").values
usd_c[oi, oj] = oc
usd_qv[oi, oj] = oc * ov            # 基础量 × 价 = 美元成交额

mi = mc["d"].map(didx).values
mj = mc["symbol"].map(sidx).values
mcap[mi, mj] = pd.to_numeric(mc["mcap"], errors="coerce").values

has_binance = np.zeros(S, dtype=bool)
for s in oh["symbol"].unique():
    has_binance[sidx[s]] = True

BTC = sidx["BTC"]
assert "USDT" in sidx, "Upbit KRW-USDT(USDKRW 代理)不在表里"
USDKRW = krw_c[:, sidx["USDT"]]     # KRW per USDT

# 市值:信号日当天;缺则用之前 7 天内最近一次(ffill,limit=7)
mcap_ff = pd.DataFrame(mcap).ffill(limit=7).to_numpy()

# ── 滚动窗口 ─────────────────────────────────────────────────────────────────
def roll(arr, how, min_valid=MIN_VALID, w=SIGNAL_DAYS):
    """返回 (D-w+1, S):索引 i = 结束于日期 i+w-1 的窗口。"""
    sw = np.lib.stride_tricks.sliding_window_view(arr, w, axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = np.nanmedian(sw, axis=2) if how == "median" else np.nansum(sw, axis=2)
    cnt = np.isfinite(sw).sum(axis=2)
    out = np.asarray(out, dtype=float)
    out[cnt < min_valid] = np.nan
    return out


prem = np.log(krw_c) - np.log(usd_c)          # 每日溢价(log KRW/USD)
med_prem = roll(prem, "median")               # (D-6, S)
# S 的分子分母:只有三天都齐的日才计入
valid = np.isfinite(krw_qv) & np.isfinite(usd_qv) & np.isfinite(USDKRW)[:, None]
num_r = roll(np.where(valid, krw_qv, np.nan), "sum")
den_r = roll(np.where(valid, usd_qv, np.nan), "sum")
cnt_r = roll(valid.astype(float), "sum")

# ── 周网格 ───────────────────────────────────────────────────────────────────
mondays = [i for i, d in enumerate(dates) if pd.Timestamp(d).weekday() == 0 and d >= WIN_START]
# 目标窗完整(入场 t+1、出场 t+29 都有 BTC 全球价)才计入
btc_ok = np.isfinite(usd_c[:, BTC])
last_ok = max(i for i in range(D) if btc_ok[i])
mondays = [t for t in mondays if t + 1 + HOLD_DAYS <= last_ok]
W = len(mondays)
t_idx = np.array(mondays)
t6 = t_idx - (SIGNAL_DAYS - 1)

mp = med_prem[t6]                                   # (W,S) 7 天溢价中位
P = mp - mp[:, [BTC]]                               # 扣掉 BTC 自己的溢价

num_w = num_r[t6]
den_w = den_r[t6]
cnt_w = cnt_r[t6]
usdkrw_w = np.array([np.nanmedian(USDKRW[max(0, t - SIGNAL_DAYS + 1):t + 1]) for t in t_idx])
S_share = num_w / np.where(den_w * usdkrw_w[:, None] > 0, den_w * usdkrw_w[:, None], np.nan)
S_share[cnt_w < MIN_VALID] = np.nan

entry_i = t_idx + 1
exit_i = t_idx + 1 + HOLD_DAYS
b_entry = usd_c[entry_i, BTC]
b_exit = usd_c[exit_i, BTC]
b_ret = b_exit / b_entry - 1.0
X = (usd_c[exit_i] / usd_c[entry_i] - 1.0) - b_ret[:, None]
MC = mcap_ff[t_idx]
MC[~has_binance[None, :]] = np.nan

week_dates = [dates[t] for t in t_idx]

# ── 每个信号:逐周 IC / 五分位 ───────────────────────────────────────────────
def week_stats(sig):
    ic, n_cs, sp_eq, sp_dollar, q1_dollar, q5_dollar = [], [], [], [], [], []
    for w in range(W):
        m = np.isfinite(sig[w]) & np.isfinite(X[w]) & np.isfinite(MC[w]) & (MC[w] >= MCAP_MIN)
        n = int(m.sum())
        if n < 5:
            continue
        v, x, mcv = sig[w][m], X[w][m], MC[w][m]
        rv, rx = rankdata(v), rankdata(x)
        ic.append(float(np.corrcoef(rv, rx)[0, 1]))
        n_cs.append(n)
        order = np.argsort(v, kind="stable")
        groups = np.array_split(order, 5)
        eq = np.array([x[g].mean() for g in groups])
        dl = np.array([np.average(x[g], weights=mcv[g]) for g in groups])
        sp_eq.append(float(eq[4] - eq[0]))
        sp_dollar.append(float(dl[4] - dl[0]))
        q1_dollar.append(float(dl[0]))
        q5_dollar.append(float(dl[4]))
    return {
        "ic": np.array(ic), "n_cs": np.array(n_cs), "sp_eq": np.array(sp_eq),
        "sp_dollar": np.array(sp_dollar), "q1_dollar": np.array(q1_dollar),
        "q5_dollar": np.array(q5_dollar),
    }


def block_boot_p(series, actual=None, mean_block=BOOT_BLOCK, n_boot=N_BOOT, seed=SEED):
    """平稳块自助的单侧分位(实际值在零分布里的分位)。"""
    s = np.asarray(series, dtype=float)
    s = s[np.isfinite(s)]
    if s.size < 10:
        return None, None
    act = float(s.mean()) if actual is None else actual

    def one(rng):
        idx = stationary_bootstrap_index(s.size, mean_block, 1, rng)[0]
        return float(s[idx].mean())

    try:
        null = null_distribution(one, n_boot, seed, actual=act)
    except Exception as e:
        return None, str(e)
    return percentile_of(act, null), None


def shuffle_null(sig):
    """周内打乱:每周一在**当周有效截面内**打乱信号值,重算 IC 与金额五分位差。"""
    packed_v, packed_w, slices, xs, mcs = [], [], [], [], []
    for w in range(W):
        m = np.isfinite(sig[w]) & np.isfinite(X[w]) & np.isfinite(MC[w]) & (MC[w] >= MCAP_MIN)
        idx = np.flatnonzero(m)
        if idx.size < 5:
            continue
        slices.append((len(packed_v), len(packed_v) + idx.size))
        packed_v.append(sig[w][idx])
        packed_w.append(np.full(idx.size, w))
        xs.append(X[w][idx])
        mcs.append(MC[w][idx])
    if not slices:
        return None, None
    vals = np.concatenate(packed_v)
    grp = np.concatenate(packed_w)
    Xs = np.concatenate(xs)
    MCs = np.concatenate(mcs)
    rx = np.concatenate([rankdata(Xs[a:b]) for a, b in slices])
    # 每个元素在自己的周内做秩
    def rank_within(vals, slices):
        out = np.empty_like(vals, dtype=float)
        for a, b in slices:
            out[a:b] = rankdata(vals[a:b])
        return out

    rng = np.random.default_rng(SEED)
    ic_null, sp_null = [], []
    for it in range(N_NULL):
        sh = np.asarray(shuffle_within(vals, grp, rng), dtype=float)
        rp = rank_within(sh, slices)
        ics, sps = [], []
        for (a, b) in slices:
            x, mcv = Xs[a:b], MCs[a:b]
            rxa = rx[a:b]
            ics.append(float(np.corrcoef(rxa, rp[a:b])[0, 1]))
            v = sh[a:b]
            order = np.argsort(v, kind="stable")
            groups = np.array_split(order, 5)
            dl = np.array([np.average(x[g], weights=mcv[g]) for g in groups])
            sps.append(float(dl[4] - dl[0]))
        ic_null.append(float(np.mean(ics)))
        sp_null.append(float(np.mean(sps)))
    return np.array(ic_null), np.array(sp_null)


def summarize(name, sig):
    st = week_stats(sig)
    out = {"weeks": int(st["ic"].size), "n_cs_median": float(np.median(st["n_cs"])) if st["n_cs"].size else None}
    for key in ["ic", "sp_eq", "sp_dollar"]:
        s = st[key]
        t, m, se = newey_west_t(s, lags=5)
        out[key] = {"mean": m, "nw_t": t, "se": se, "n": int(s.size)}
    # 两段
    dts = pd.to_datetime(pd.Series(week_dates))
    keep = np.array([d for d in week_dates if d in set(week_dates)])  # 占位
    for label, lo, hi in [("h1_2021_2023", "2021-01-01", "2023-12-31"), ("h2_2024_2026", "2024-01-01", "2026-12-31")]:
        sel = np.array([(lo <= w <= hi) for w in week_dates])
        # 重新按周过滤(跳过 n<5 的周)
        idx = []
        j = 0
        for w in range(W):
            m = np.isfinite(sig[w]) & np.isfinite(X[w]) & np.isfinite(MC[w]) & (MC[w] >= MCAP_MIN)
            if int(m.sum()) < 5:
                continue
            if sel[w]:
                idx.append(j)
            j += 1
        idx = np.array(idx, dtype=int)
        seg = {}
        for key in ["ic", "sp_dollar"]:
            s = st[key][idx]
            t, m, se = newey_west_t(s, lags=5)
            seg[key] = {"mean": m, "nw_t": t, "n": int(s.size)}
        out[label] = seg
    # 零分布:周内打乱
    ic_null, sp_null = shuffle_null(sig)
    if ic_null is not None:
        out["shuffle_ic_pct"] = percentile_of(out["ic"]["mean"], ic_null)
        out["shuffle_sp_dollar_pct"] = percentile_of(out["sp_dollar"]["mean"], sp_null)
        out["shuffle_ic_null_median"] = float(np.median(ic_null))
        out["shuffle_sp_dollar_null_median"] = float(np.median(sp_null))
    # 块自助(按金额判据用)
    p_gross, err = block_boot_p(st["sp_dollar"])
    net = st["sp_dollar"] - COST_RT
    p_net, err2 = block_boot_p(net)
    out["sp_dollar_net20bp_mean"] = float(net.mean()) if net.size else None
    out["boot_p_gross"] = p_gross
    out["boot_p_net20bp"] = p_net
    if err or err2:
        out["boot_err"] = err or err2
    # 只报:最低五分位(按金额加权)
    t, m, se = newey_west_t(st["q1_dollar"], lags=5)
    out["q1_dollar_report_only"] = {"mean": m, "nw_t": t, "n": int(st["q1_dollar"].size)}
    t, m, se = newey_west_t(st["sp_eq"], lags=5)
    out["sp_eq_detail"] = {"mean": m, "nw_t": t}
    out["_series"] = st
    return out


res = {
    "card": "T-292",
    "prereg": "S-771",
    "generated_at": pd.Timestamp.utcnow().isoformat(),
    "config": {
        "window_start": WIN_START, "signal_days": SIGNAL_DAYS, "min_valid": MIN_VALID,
        "mcap_min": MCAP_MIN, "hold_days": HOLD_DAYS, "cost_round_trip": COST_RT,
        "n_null": N_NULL, "seed": SEED, "n_boot": N_BOOT, "boot_mean_block_weeks": BOOT_BLOCK,
    },
    "coverage": {
        "upbit_markets": int(up["market"].nunique()),
        "upbit_symbols": int(up["symbol"].nunique()),
        "upbit_d_range": [str(up["d"].min()), str(up["d"].max())],
        "binance_symbols": int(oh["symbol"].nunique()),
        "mcap_symbols": int(mc["symbol"].nunique()),
        "map_hit_binance": float((oh["symbol"].unique().size) / up["symbol"].nunique()),
        "map_hit_mcap": float((mc["symbol"].unique().size) / up["symbol"].nunique()),
        "weeks": W,
        "week_first": week_dates[0], "week_last": week_dates[-1],
        "usdkrw_first_date": str(dates[int(np.argmax(np.isfinite(USDKRW)))]),
        "usdkrw_n_days": int(np.isfinite(USDKRW).sum()),
    },
}

for name, sig in [("P_premium", P), ("S_share", S_share)]:
    r = summarize(name, sig)
    st = r.pop("_series")
    r["weekly_ic_head"] = [round(float(v), 4) for v in st["ic"][:8]]
    r["weekly_sp_dollar_head"] = [round(float(v), 4) for v in st["sp_dollar"][:8]]
    res[name] = r
    # 判据
    ic_ok = (r["ic"]["mean"] is not None and r["ic"]["mean"] < 0 and r["ic"]["nw_t"] is not None
             and r["ic"]["nw_t"] <= -2)
    sp_ok = (r["sp_dollar"]["mean"] is not None and r["sp_dollar"]["mean"] < 0
             and r["sp_dollar_net20bp_mean"] is not None and r["sp_dollar_net20bp_mean"] < 0
             and r["boot_p_net20bp"] is not None and r["boot_p_net20bp"] <= 0.05)
    sh_ok = (r.get("shuffle_ic_pct") is not None and r["shuffle_ic_pct"] <= 0.05)
    h1 = r["h1_2021_2023"]["ic"]["mean"]
    h2 = r["h2_2024_2026"]["ic"]["mean"]
    half_ok = (h1 is not None and h2 is not None and h1 < 0 and h2 < 0)
    r["verdict"] = {
        "ic_mean_lt0_and_nw_t_le_-2": bool(ic_ok),
        "dollar_quintile_spread_lt0_net20bp_and_boot_p_le_0.05": bool(sp_ok),
        "shuffle_pct_le_0.05": bool(sh_ok),
        "halves_same_sign": bool(half_ok),
        "pass_all": bool(ic_ok and sp_ok and sh_ok and half_ok),
    }

RES.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=float))
print(json.dumps({k: v for k, v in res.items() if k not in ("P_premium", "S_share")}, indent=1, ensure_ascii=False, default=float))
for k in ["P_premium", "S_share"]:
    r = res[k]
    print("\n==", k, "==")
    for kk in ["weeks", "n_cs_median", "ic", "sp_eq", "sp_dollar", "sp_dollar_net20bp_mean",
               "boot_p_gross", "boot_p_net20bp", "shuffle_ic_pct", "shuffle_sp_dollar_pct",
               "h1_2021_2023", "h2_2024_2026", "q1_dollar_report_only", "verdict"]:
        print(" ", kk, "=", json.dumps(r.get(kk), ensure_ascii=False, default=float))
print("WROTE", RES)
