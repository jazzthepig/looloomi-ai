#!/usr/bin/env python3
"""T-340 —— S-814 周期位置空间的**盲复算**(lane-c)。

只读 `REFUTATION_LEDGER.md` 的 S-814 原文(唯一口径来源),自己实现空间与 (a)–(e)。
**不 import** `src/data/state/cycle_space.py`(生产内核)、不读 lane-a 的 `t339_*`。
零分布 / Brier / 块自助 / 循环平移一律走 `src/data/evaluation/apparatus.py`。

数据(只读):
  - Supabase `macro_daily`(series 长表):台账 S-814 点名的五条全在库里 ——
    `btc_price_usd` / `btc_mvrv` / `btc_puell` / `btc_hash_30d`(2011 起)+ `fng`(2018-02 起);
    另取 `btc_issuance_usd` / `btc_hashrate` 两条原始量,用来**自己复算** Puell 与算力 30 天变化
    与库值交叉核对(核对结果写进报告 §0)。
  - Coin Metrics 社区 API(免密钥):`PriceUSD` / `CapMVRVCur` —— 只作交叉核对,不入计算。

产物(写到仓库 docs/research/):
  - t340_weekly.csv   周度表(先落)
  - t340_results.json (a)–(e) + 口径变体
用法: python3 t340_blind.py [--out DIR]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import urllib.request
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

# ── apparatus:零分布 / Brier / 块自助 / 循环平移只许用这里的函数 ──────────────
_REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "apparatus", _REPO / "src" / "data" / "evaluation" / "apparatus.py")
apparatus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apparatus)

# ── S-814 原文写死的常量 ──────────────────────────────────────────────────────
DIMS = ["mvrv", "puell", "hash_30d", "dist_200", "ret_365", "dd_ath", "vol_90", "fng_30"]
N_DIM = 8
LOOKBACK_CANDIDATE = 181    # 候选日 s ≤ t − 181 天
K_NEIGHBOR = 60             # 近邻数
MIN_COMMON_DIM = 5          # 共有维 < 5 不比
STD_MIN_OBS = 730           # 该维 ≥ 730 个观测才出 z
Z_CLIP = 6.0
FWD_DAYS = 180              # fwd = 价(s+180) ÷ 价(s) − 1
DOWN_LE = -0.20             # down: fwd ≤ −20%
UP_GE = 0.25                # up:   fwd ≥ +25%
SEG_GAP_DAYS = 90           # 近邻相隔 ≥ 90 天 ⇒ 新段
SHRINK_K = 3                # w = 段数 ÷ (段数 + 3)
TILT_ADD = 0.25             # tilt_excess ≥ +0.25 ⇒ add
TILT_TRIM = -0.25           # tilt_excess ≤ −0.25 ⇒ trim
MIN_SEGMENTS = 3            # 段数 ≥ 3
W_ADD, W_TRIM, W_HOLD = 1.0, 0.35, 0.70
COST_BPS = 10               # 10bp × 换手
HALVINGS = ["2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20"]
EXTREME_WINDOW = 30         # 顶/底 ±30 天
SPEARMAN_MIN = 0.20         # (a)
ALPHA_A = 0.05
ALPHA_C = 0.10
N_NULL_A = 1000
N_NULL_C = 1000
N_BOOT_B = 2000
BLOCK_WEEKS = 26            # 块长 26 周
SEED = 814

CACHE = pathlib.Path("/Volumes/CometCloudAI/cometcloud-local/research/t340_blind")


# ── 取数(只读)───────────────────────────────────────────────────────────────
def _postgrest(path: str) -> str:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    req = urllib.request.Request(url)
    req.add_header("apikey", os.environ["SUPABASE_KEY"])
    req.add_header("Authorization", "Bearer " + os.environ["SUPABASE_KEY"])
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read().decode()


NEEDED_SERIES = ["btc_price_usd", "btc_mvrv", "btc_puell", "btc_hash_30d",
                 "btc_issuance_usd", "btc_hashrate", "fng"]


def load_macro_daily(series: list[str] | None = None) -> dict[str, dict[str, float]]:
    """macro_daily 指定序列 → {series: {d: value}}。每条序列单独翻页(limit=1000,PostgREST 单页上限),
    带 order=d.asc —— 不带 order 时翻页边界会漂(T-170/T-173 实测)。只读。"""
    series = series or NEEDED_SERIES
    out: dict[str, dict[str, float]] = {}
    for name in series:
        cache = CACHE / f"series_{name}.json"
        if cache.exists():
            out[name] = json.load(open(cache))
            continue
        d: dict[str, float] = {}
        off = 0
        while True:
            page = json.loads(_postgrest(
                f"macro_daily?select=d,value&series=eq.{name}&order=d.asc&limit=1000&offset={off}"))
            if not page:
                break
            for r in page:
                if r.get("value") is not None:
                    d[r["d"]] = float(r["value"])
            off += len(page)
            if len(page) < 1000:
                break
        CACHE.mkdir(parents=True, exist_ok=True)
        json.dump(d, open(cache, "w"))
        out[name] = d
    return out


def load_coinmetrics() -> dict:
    """Coin Metrics 社区 API(免密钥)原始缓存 —— **只作交叉核对**,不入计算。"""
    cache = CACHE / "coinmetrics_raw.json"
    if cache.exists():
        return json.load(open(cache))
    url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
           "?assets=btc&metrics=PriceUSD,CapMVRVCur&start_time=2010-01-01&page_size=10000&frequency=1d")
    cm, pages = {}, 0
    while url and pages < 30:
        req = urllib.request.Request(url, headers={"User-Agent": "lane-c/T-340"})
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.loads(r.read().decode())
        for row in j.get("data") or []:
            d = row["time"][:10]
            for m in ("PriceUSD", "CapMVRVCur"):
                v = row.get(m)
                if v not in (None, ""):
                    cm.setdefault(d, {})[m] = float(v)
        url = j.get("next_page_url")
        pages += 1
    CACHE.mkdir(parents=True, exist_ok=True)
    json.dump(cm, open(cache, "w"))
    return cm


def load_price(macro: dict[str, dict[str, float]]) -> tuple[pd.Series, str]:
    """价格:优先 `macro_daily.btc_price_usd`(回填后库里有,台账点名的就是它);没有才现取 Coin Metrics。"""
    d = macro.get("btc_price_usd") or {}
    src = "macro_daily.btc_price_usd"
    if not d:
        src = "coinmetrics:PriceUSD"
        cm = load_coinmetrics()
        d = {k: v["PriceUSD"] for k, v in cm.items() if "PriceUSD" in v}
    s = pd.Series(d, dtype=float)
    s.index = pd.to_datetime(s.index)
    return s.sort_index(), src


def _cmp(a: pd.Series, b: pd.Series) -> dict:
    """两条同索引序列的一致性(相对误差)。"""
    j = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if not len(j):
        return {"n": 0}
    rel = ((j["a"] - j["b"]).abs() / j["b"].abs().replace(0, np.nan)).dropna()
    return {"n": int(len(j)),
            "max_abs": float((j["a"] - j["b"]).abs().max()),
            "max_rel": float(rel.max()) if len(rel) else None,
            "p99_rel": float(rel.quantile(0.99)) if len(rel) else None,
            "exact": int((j["a"] == j["b"]).sum())}


# ── 8 维原始值(只用 ≤ d)──────────────────────────────────────────────────────
def build_raw(macro: dict[str, dict[str, float]], price: pd.Series,
              *, use_db_derived: bool = True) -> tuple[pd.DataFrame, dict]:
    """逐维原始值(台账原文:mvrv=ln(MVRV);puell=ln(Puell);hash_30d 原值;dist_200=ln(价÷200 日均价);
    ret_365=ln(价÷365 天前);dd_ath=价÷至今最高−1;vol_90=90 日对数收益**总体**标准差;fng_30=30 日均值)。

    Puell 与算力 30 天变化:库里(`btc_puell` / `btc_hash_30d`)优先,缺则按
    「Puell = 当日发行美元 ÷ 最近 365 天(含当天)均值」「算力 30 天变化 = ln(近 7 天均值 ÷ 30 天前的 7 天均值)」
    自己算;两条都算一遍用于交叉核对。返回 (DataFrame, 核对 dict)。"""
    idx = price.index                       # 日历轴 = 有价格的每一天
    px = price.reindex(idx)

    def mapser(d: dict[str, float]) -> pd.Series:
        s = pd.Series({pd.Timestamp(k): v for k, v in d.items()}, dtype=float)
        return s.reindex(idx)

    mvrv_s = mapser(macro.get("btc_mvrv", {}))
    iss_s = mapser(macro.get("btc_issuance_usd", {}))
    hr_s = mapser(macro.get("btc_hashrate", {}))
    fng_s = mapser(macro.get("fng", {}))
    puell_db = mapser(macro.get("btc_puell", {}))
    hash_db = mapser(macro.get("btc_hash_30d", {}))

    # —— 自己实现的派生(数据层,不是被审的周期空间内核)——
    iss_win = iss_s.rolling(365, min_periods=365).mean()                # 含当天的 365 日均值
    puell_own = iss_s / iss_win
    hr7 = hr_s.rolling(7, min_periods=7).mean()
    hr7_30 = hr_s.shift(30).rolling(7, min_periods=7).mean()
    hash_own = np.log(hr7 / hr7_30)

    xcheck = {"puell_db_vs_own": _cmp(puell_db, puell_own),
              "hash_30d_db_vs_own": _cmp(hash_db, hash_own)}
    if use_db_derived:
        puell_s = puell_db.where(puell_db.notna(), puell_own)
        hash_s = hash_db.where(hash_db.notna(), hash_own)
    else:
        puell_s, hash_s = puell_own, hash_own

    out = pd.DataFrame(index=idx)
    out["mvrv"] = np.log(mvrv_s.where(mvrv_s > 0))                       # ln(MVRV)
    out["puell"] = np.log(puell_s.where(puell_s > 0))                    # ln(Puell)
    out["hash_30d"] = hash_s                                            # 原值(已是 ln 比值)
    out["dist_200"] = np.log(px / px.rolling(200, min_periods=200).mean()).where(px > 0)
    out["ret_365"] = np.log(px / px.shift(365)).where(px > 0)
    out["dd_ath"] = px / px.cummax() - 1.0
    logret = np.log(px).diff()
    out["vol_90"] = logret.rolling(90, min_periods=90).std(ddof=0)     # 总体标准差
    out["fng_30"] = fng_s.rolling(30, min_periods=20).mean()            # ≥20 观测才有值
    return out, xcheck


def zscore(raw: pd.DataFrame, window: int | None = None) -> pd.DataFrame:
    """标准化:每维用**严格更早**的值算均值/样本标准差;该维 ≥ 730 个观测才出 z;截到 ±6。
    window=None ⇒ 扩张窗口(全部历史,原文只写「≥ 730 个观测」);window=730 ⇒ 变体。"""
    z = pd.DataFrame(np.nan, index=raw.index, columns=raw.columns)
    for c in raw.columns:
        s = raw[c].shift(1)                      # 严格更早
        if window is None:
            mean = s.expanding(min_periods=1).mean()
            std = s.expanding(min_periods=2).std(ddof=1)
            cnt = s.expanding(min_periods=1).count()
        else:
            mean = s.rolling(window, min_periods=window).mean()
            std = s.rolling(window, min_periods=2).std(ddof=1)
            cnt = s.rolling(window, min_periods=1).count()
        ok = cnt >= STD_MIN_OBS
        zz = (raw[c] - mean) / std
        z[c] = zz.where(ok).clip(-Z_CLIP, Z_CLIP)
    return z


# ── 走步:每个周一一个读数 ───────────────────────────────────────────────────
def weekly_readings(z: pd.DataFrame, px: pd.Series, *, trim_needs_segments: bool,
                    uncond_in_space: bool, k: int = K_NEIGHBOR) -> pd.DataFrame:
    """每个周一 t:候选池 ≤ t−181 → 距离 → 最近 k 近邻 → 段数 → 收缩 → tilt → 表态。

    trim_needs_segments: 表态口径变体 —— 主口径按**原文字面**:「段数 ≥ 3 且 tilt ≥ +0.25 ⇒ add;
                          ≤ −0.25 ⇒ trim」的并列结构,trim 分句没有重述段数条件;
                          变体下 trim 也要求段数 ≥ 3。
    uncond_in_space:     无条件频率的分母是否只算「空间里可比的」(≥5 维有 z)的日子。
    """
    dates = z.index
    n = len(dates)
    Z = z.to_numpy(dtype=float)
    valid = ~np.isnan(Z)
    pxs = px.to_numpy(dtype=float)
    daynum = dates.to_numpy(dtype="datetime64[D]").astype("int64")
    pos = {d: i for i, d in enumerate(dates)}

    fwd = np.full(n, np.nan)
    up = np.zeros(n, dtype=bool)
    down = np.zeros(n, dtype=bool)
    for i in range(n):
        j = pos.get(dates[i] + pd.Timedelta(days=FWD_DAYS))
        if j is None or not np.isfinite(pxs[i]) or pxs[i] <= 0:
            continue
        f = pxs[j] / pxs[i] - 1.0
        fwd[i] = f
        up[i] = f >= UP_GE
        down[i] = f <= DOWN_LE

    in_space = valid.sum(axis=1) >= MIN_COMMON_DIM
    mondays = [i for i, d in enumerate(dates) if d.weekday() == 0]
    rows = []
    for t in mondays:
        if valid[t].sum() < MIN_COMMON_DIM:
            continue
        cut = daynum[t] - LOOKBACK_CANDIDATE
        cand = np.where(daynum <= cut)[0]
        if cand.size == 0:
            continue
        shared = valid[cand] & valid[t][None, :]
        nshared = shared.sum(axis=1)
        diff = Z[cand] - Z[t][None, :]
        sq = np.where(shared, diff ** 2, 0.0).sum(axis=1)
        dist = np.sqrt(sq) * np.sqrt(N_DIM / np.maximum(nshared, 1))
        ok = nshared >= MIN_COMMON_DIM
        if not ok.any():
            continue
        cand_ok, dist_ok = cand[ok], dist[ok]
        order = np.lexsort((cand_ok, dist_ok))          # 距离升序,同距按日期
        nb = np.sort(cand_ok[order[:k]])                # 按日期排(段数用)
        if nb.size == 0:
            continue
        segs = 1 + int((np.diff(daynum[nb]) >= SEG_GAP_DAYS).sum())
        fwd_nb = fwd[nb]
        fin = np.isfinite(fwd_nb)
        if fin.sum() == 0:
            continue
        nb_up = float(up[nb][fin].mean())
        nb_down = float(down[nb][fin].mean())
        u_all = cand[np.isfinite(fwd[cand])]            # 无条件:所有 ≤ t−181 且 fwd 可算的日子
        if uncond_in_space:
            u_all = u_all[in_space[u_all]]
        if u_all.size == 0:
            continue
        u_up = float(up[u_all].mean())
        u_down = float(down[u_all].mean())
        w = segs / (segs + SHRINK_K)
        p_up = w * nb_up + (1 - w) * u_up
        p_dn = w * nb_down + (1 - w) * u_down
        tilt = (p_up - p_dn) - (u_up - u_down)
        if segs >= MIN_SEGMENTS and tilt >= TILT_ADD:
            stance = "add"
        elif (segs >= MIN_SEGMENTS if trim_needs_segments else True) and tilt <= TILT_TRIM:
            stance = "trim"
        else:
            stance = "hold"
        rows.append({
            "t": dates[t].date().isoformat(), "price": float(pxs[t]),
            "n_dims": int(valid[t].sum()), "n_cand": int(cand_ok.size),
            "n_nb": int(nb.size), "n_nb_fwd": int(fin.sum()), "segments": int(segs),
            "nb_up": nb_up, "nb_down": nb_down, "u_up": u_up, "u_down": u_down,
            "w": float(w), "p_up": float(p_up), "p_down": float(p_dn),
            "tilt_excess": float(tilt), "stance": stance,
        })
    return pd.DataFrame(rows)


# ── (a) Spearman + 循环平移零分布 ───────────────────────────────────────────
def crit_a(rd: pd.DataFrame, px: pd.Series, dates_index: pd.DatetimeIndex) -> dict:
    """周度 Spearman(tilt_excess, 实现 fwd180) ≥ 0.20;实现序列整体循环平移零分布 p_upper ≤ 0.05。"""
    tilt = rd["tilt_excess"].to_numpy(dtype=float)
    realized = rd["realized_fwd180"].to_numpy(dtype=float)
    ok = np.isfinite(realized) & np.isfinite(tilt)
    realized, tilt = realized[ok], tilt[ok]
    n = len(realized)
    if n < 2 * BLOCK_WEEKS:
        return {"n_weeks": int(n), "spearman": None, "p_upper": None, "why": "样本不足两个块长"}
    rho = float(spearmanr(tilt, realized).statistic)

    def one(rng):
        sh = apparatus.circular_shift(pd.Series(realized), rng, block=BLOCK_WEEKS)
        return float(spearmanr(tilt, np.asarray(sh, dtype=float)).statistic)

    try:
        null = apparatus.null_distribution(one, N_NULL_A, SEED, actual=rho)
        p_up = apparatus.p_upper(rho, null)
    except apparatus.NoOpNull as e:
        return {"n_weeks": int(n), "spearman": rho, "p_upper": None,
                "pass_spearman": bool(rho >= SPEARMAN_MIN), "pass_p": None, "why": str(e)}
    return {"n_weeks": int(n), "spearman": rho, "p_upper": p_up,
            "null_mean": float(np.mean(null)), "null_q95": float(np.quantile(null, 0.95)),
            "pass_spearman": bool(rho >= SPEARMAN_MIN),
            "pass_p": bool(p_up is not None and p_up <= ALPHA_A)}


# ── (b) 三档 Brier + 配对块自助 ──────────────────────────────────────────────
def crit_b(rd: pd.DataFrame) -> dict:
    """三档(up / down / 中间)Brier:收缩后的 p < 无条件频率的 Brier;配对块自助差的 95% 上沿 < 0。"""
    p_up = rd["p_up"].to_numpy(dtype=float)
    p_dn = rd["p_down"].to_numpy(dtype=float)
    u_up = rd["u_up"].to_numpy(dtype=float)
    u_dn = rd["u_down"].to_numpy(dtype=float)
    p_mid, u_mid = 1.0 - p_up - p_dn, 1.0 - u_up - u_dn
    fwd180 = rd["realized_fwd180"].to_numpy(dtype=float)
    ok = np.isfinite(fwd180)
    y_up = np.where(fwd180 >= UP_GE, 1.0, 0.0)
    y_dn = np.where(fwd180 <= DOWN_LE, 1.0, 0.0)
    y_mid = 1.0 - y_up - y_dn
    brier_s = (apparatus.brier(p_up[ok], y_up[ok]) + apparatus.brier(p_dn[ok], y_dn[ok])
               + apparatus.brier(p_mid[ok], y_mid[ok]))
    brier_u = (apparatus.brier(u_up[ok], y_up[ok]) + apparatus.brier(u_dn[ok], y_dn[ok])
               + apparatus.brier(u_mid[ok], y_mid[ok]))
    if brier_s is None or brier_u is None:
        return {"n_weeks": int(n), "brier_shrunk": brier_s, "brier_uncond": brier_u,
                "diff": None, "pass_brier": None, "why": "Brier 不可算"}
    d = ((p_up - y_up) ** 2 + (p_dn - y_dn) ** 2 + (p_mid - y_mid) ** 2
         - (u_up - y_up) ** 2 - (u_dn - y_dn) ** 2 - (u_mid - y_mid) ** 2)[ok]
    n = len(d)
    out = {"n_weeks": int(n), "brier_shrunk": brier_s, "brier_uncond": brier_u,
           "diff": brier_s - brier_u, "pass_brier": bool(brier_s < brier_u)}
    if n < 2 * BLOCK_WEEKS:
        out.update({"boot_q95": None, "pass_boot": None, "why": "样本不足两个块长"})
        return out
    rng = np.random.default_rng(SEED)
    idx = apparatus.stationary_bootstrap_index(n, BLOCK_WEEKS, N_BOOT_B, rng)
    boot = d[idx].mean(axis=1)
    q95 = float(np.quantile(boot, 0.95))
    out.update({"boot_q95": q95, "boot_mean": float(boot.mean()),
                "pass_boot": bool(q95 < 0.0), "block": BLOCK_WEEKS, "n_boot": N_BOOT_B})
    return out


# ── (c) 配置回测:周一收盘定权重、次日收盘生效、10bp × 换手、现金 0 ──────────
def backtest(rd: pd.DataFrame, px: pd.Series, dates_index: pd.DatetimeIndex,
             weights: np.ndarray) -> dict:
    """按给定权重日程回测。返回累计收益、最大回撤、Calmar。"""
    idx = {d: i for i, d in enumerate(dates_index)}
    pxs = px.to_numpy(dtype=float)
    nav, cur, prev_w = 1.0, [], 0.0
    for k, t in enumerate(rd["t"]):
        i0 = idx.get(pd.Timestamp(t) + pd.Timedelta(days=1))     # 次日收盘生效
        i1 = idx.get(pd.Timestamp(t) + pd.Timedelta(days=8))     # 持有到下一周同日收盘
        if i0 is None or i1 is None or not np.isfinite(pxs[i0]) or not np.isfinite(pxs[i1]):
            continue
        w = float(weights[k])
        gross = w * (pxs[i1] / pxs[i0] - 1.0)                    # 现金 0
        cost = (COST_BPS / 10000.0) * abs(w - prev_w)            # 10bp × 换手
        cur.append(gross - cost)
        nav *= (1.0 + gross - cost)
        prev_w = w
    if not cur:
        return {"total_return": None, "max_dd": None, "calmar": None, "n_periods": 0}
    curve = np.cumprod(1.0 + np.asarray(cur))
    peak = np.maximum.accumulate(curve)
    dd = (peak - curve) / peak
    max_dd = float(dd.max())
    total = float(curve[-1] - 1.0)
    years = max(len(cur) * 7.0 / 365.0, 1e-9)
    ann = (1.0 + total) ** (1.0 / years) - 1.0 if total > -1 else -1.0
    calmar = ann / max_dd if max_dd > 0 else float("inf")
    return {"total_return": total, "max_dd": max_dd, "calmar": float(calmar),
            "ann_return": float(ann), "n_periods": len(cur)}


def crit_c(rd: pd.DataFrame, px: pd.Series, dates_index: pd.DatetimeIndex) -> dict:
    w = np.where(rd["stance"].to_numpy() == "add", W_ADD,
                 np.where(rd["stance"].to_numpy() == "trim", W_TRIM, W_HOLD)).astype(float)
    strat = backtest(rd, px, dates_index, w)
    hold = backtest(rd, px, dates_index, np.full(len(rd), W_HOLD))
    out = {"strategy": strat, "hold70": hold,
           "pass_return": bool(strat["total_return"] is not None and hold["total_return"] is not None
                               and strat["total_return"] >= hold["total_return"]),
           "pass_dd": bool(strat["max_dd"] is not None and hold["max_dd"] is not None
                           and (hold["max_dd"] - strat["max_dd"]) >= 0.05)}
    if strat["calmar"] is None or not np.isfinite(strat["calmar"]):
        out.update({"calmar_null_p": None, "pass_calmar": None})
        return out
    ws = pd.Series(w)

    def one(rng):
        sh = apparatus.circular_shift(ws, rng, block=1)
        bt = backtest(rd, px, dates_index, np.asarray(sh, dtype=float))
        return bt["calmar"] if bt["calmar"] is not None else np.nan

    try:
        null = apparatus.null_distribution(one, N_NULL_C, SEED, actual=strat["calmar"])
        p_up = apparatus.p_upper(strat["calmar"], null)
    except apparatus.NoOpNull as e:
        out.update({"calmar_null_p": None, "pass_calmar": None, "why": str(e)})
        return out
    out.update({"calmar_null_p": p_up, "pass_calmar": bool(p_up is not None and p_up <= ALPHA_C),
                "calmar_null_mean": float(np.nanmean(null))})
    return out


# ── (d) 四轮周期的极端 ──────────────────────────────────────────────────────
def crit_d(rd: pd.DataFrame, px: pd.Series, dates_index: pd.DatetimeIndex) -> dict:
    pxs = px.to_numpy(dtype=float)
    bounds = [pd.Timestamp(h).date() for h in HALVINGS]
    end = dates_index[-1].date()
    tops, bottoms = [], []
    for k, b in enumerate(bounds):
        nxt = bounds[k + 1] if k + 1 < len(bounds) else end + timedelta(days=1)
        seg = [(i, pxs[i]) for i in range(len(dates_index))
               if b <= dates_index[i].date() < nxt and np.isfinite(pxs[i])]
        tops.append(max(seg, key=lambda x: x[1]) if seg else None)
    for k in range(len(tops) - 1):                 # 底 = 每个顶之后到下一个顶之前的最低收盘
        i0, i1 = tops[k][0], tops[k + 1][0]
        seg = [(i, pxs[i]) for i in range(i0, i1) if np.isfinite(pxs[i])]
        bottoms.append(min(seg, key=lambda x: x[1]) if seg else None)
    stance_by_day = {pd.Timestamp(r["t"]).date(): r["stance"] for _, r in rd.iterrows()}
    rd_days = pd.to_datetime(rd["t"]).dt.date.to_numpy()

    def win(center: date, w: int):
        lo, hi = center - timedelta(days=w), center + timedelta(days=w)
        return [stance_by_day[dd] for dd in rd_days if lo <= dd <= hi]

    per = []
    for k, t in enumerate(tops):
        if t is None:
            continue
        center = dates_index[t[0]].date()
        st, st60 = win(center, EXTREME_WINDOW), win(center, 60)
        b = bottoms[k] if k < len(bottoms) else None
        bs = win(dates_index[b[0]].date(), EXTREME_WINDOW) if b is not None else []
        bs60 = win(dates_index[b[0]].date(), 60) if b is not None else []
        per.append({
            "epoch": f"E{k+1}", "epoch_start": HALVINGS[k],
            "top_date": center.isoformat(), "top_close": float(t[1]),
            "top_window30": {"add": st.count("add"), "trim": st.count("trim"),
                             "hold": st.count("hold"), "n": len(st)},
            "top_window60": {"add": st60.count("add"), "trim": st60.count("trim"), "n": len(st60)},
            "bottom_date": (dates_index[b[0]].date().isoformat() if b is not None else None),
            "bottom_close": (float(b[1]) if b is not None else None),
            "bottom_window30": ({"add": bs.count("add"), "trim": bs.count("trim"),
                                 "hold": bs.count("hold"), "n": len(bs)} if bs else None),
            "bottom_window60": ({"add": bs60.count("add"), "trim": bs60.count("trim"),
                                 "n": len(bs60)} if bs60 else None),
            "pass_top_no_add": st.count("add") == 0,
            "pass_bottom_no_trim": (bs.count("trim") == 0) if bs else None,
        })
    n_top_trim = sum(1 for p in per if p["top_window30"]["trim"] > 0)
    n_top_trim60 = sum(1 for p in per if p["top_window60"]["trim"] > 0)
    n_bot_add = sum(1 for p in per if p["bottom_window30"] and p["bottom_window30"]["add"] > 0)
    n_bot_add60 = sum(1 for p in per if p["bottom_window60"] and p["bottom_window60"]["add"] > 0)
    return {"per_epoch": per, "n_tops_with_trim": n_top_trim, "n_bottoms_with_add": n_bot_add,
            "n_tops_with_trim_60d": n_top_trim60, "n_bottoms_with_add_60d": n_bot_add60,
            "pass_top_no_add": all(p["pass_top_no_add"] for p in per),
            "pass_bottom_no_trim": all(p["pass_bottom_no_trim"] for p in per
                                       if p["pass_bottom_no_trim"] is not None),
            "pass_ge2_top_trim": bool(n_top_trim >= 2),
            "pass_ge2_bottom_add": bool(n_bot_add >= 2)}


# ── (e) 两半 Spearman 同号 ──────────────────────────────────────────────────
def crit_e(rd: pd.DataFrame) -> dict:
    t = rd["tilt_excess"].to_numpy(dtype=float)
    r = rd["realized_fwd180"].to_numpy(dtype=float)
    ok = np.isfinite(t) & np.isfinite(r)
    t, r = t[ok], r[ok]
    n = len(t)
    if n < 4:
        return {"rho_h1": None, "rho_h2": None, "pass": None, "why": "样本太短"}
    h = n // 2
    r1 = float(spearmanr(t[:h], r[:h]).statistic)
    r2 = float(spearmanr(t[h:], r[h:]).statistic)
    return {"rho_h1": r1, "rho_h2": r2, "n_h1": h, "n_h2": n - h,
            "pass": bool((r1 > 0 and r2 > 0) or (r1 < 0 and r2 < 0))}


# ── 单维基线(另报,不判)─────────────────────────────────────────────────────
def expansion_pct(series: pd.Series, query: pd.DatetimeIndex) -> np.ndarray:
    """扩张分位:查询日的值在**其自身历史**(≤ 当日)里的百分位。只在查询日上算(不是每天)。"""
    vals = series.to_numpy(dtype=float)
    order = np.argsort(vals, kind="stable")
    sorted_vals = vals[order]
    pos = {d: i for i, d in enumerate(series.index)}
    out = np.full(len(query), np.nan)
    for i, q in enumerate(query):
        j = pos.get(q)
        if j is None or j < 2 or not np.isfinite(vals[j]):
            continue
        lo = int(np.sum(vals[:j] < vals[j]))
        hi = int(np.sum(vals[:j] <= vals[j]))
        n_prev = int(np.sum(np.isfinite(vals[:j])))
        if n_prev < STD_MIN_OBS:
            continue
        out[i] = 0.5 * (lo + hi) / n_prev
    return out


def single_dim_baselines(rd: pd.DataFrame, raw: pd.DataFrame, z: pd.DataFrame) -> dict:
    """只用 MVRV 的扩张分位 / 只用 dist_200,同一个 Spearman(tilt_excess → 实现 fwd180)。"""
    r = rd["realized_fwd180"].to_numpy(dtype=float)
    q = pd.to_datetime(rd["t"])
    out = {}
    sigs = {
        "mvrv_expansion_pct": expansion_pct(raw["mvrv"], q),
        "dist_200_z": z["dist_200"].reindex(q).to_numpy(dtype=float),
    }
    for name, sig in sigs.items():
        ok = np.isfinite(sig) & np.isfinite(r)
        out[name] = {"spearman": float(spearmanr(sig[ok], r[ok]).statistic) if ok.sum() > 2 else None,
                     "n": int(ok.sum())}
    ok = np.isfinite(rd["tilt_excess"].to_numpy(dtype=float)) & np.isfinite(r)
    out["space_tilt_excess"] = {
        "spearman": float(spearmanr(rd["tilt_excess"].to_numpy(dtype=float)[ok], r[ok]).statistic)}
    return out


# ── 主流程 ──────────────────────────────────────────────────────────────────
def _add_realized(rd: pd.DataFrame, px: pd.Series) -> pd.DataFrame:
    idx = {d: i for i, d in enumerate(px.index)}
    pxs = px.to_numpy(dtype=float)
    real = []
    for t in rd["t"]:
        i = idx.get(pd.Timestamp(t))
        j = idx.get(pd.Timestamp(t) + pd.Timedelta(days=FWD_DAYS))
        real.append(np.nan if (i is None or j is None) else pxs[j] / pxs[i] - 1.0)
    rd = rd.copy()
    rd["realized_fwd180"] = real
    return rd


def run(outdir: pathlib.Path, variants: dict) -> dict:
    print("[1] 取数(只读)…", flush=True)
    macro = load_macro_daily()
    price, price_src = load_price(macro)
    print(f"    macro_daily {len(macro)} 条 series; price[{price_src}] "
          f"{price.index[0].date()}..{price.index[-1].date()} n={len(price)}", flush=True)
    raw, xcheck = build_raw(macro, price)
    cm = load_coinmetrics()
    if cm:
        cm_px = pd.Series({pd.Timestamp(k): v["PriceUSD"] for k, v in cm.items() if "PriceUSD" in v}).sort_index()
        xcheck["price_db_vs_coinmetrics"] = _cmp(price, cm_px)
        cm_mvrv = pd.Series({pd.Timestamp(k): v["CapMVRVCur"] for k, v in cm.items() if "CapMVRVCur" in v}).sort_index()
        xcheck["mvrv_db_vs_coinmetrics"] = _cmp(
            pd.Series({pd.Timestamp(k): v for k, v in macro.get("btc_mvrv", {}).items()}, dtype=float).sort_index(),
            cm_mvrv)
    print("    交叉核对:", json.dumps(xcheck, ensure_ascii=False), flush=True)
    print("[2] 8 维原始值 + 标准化…", flush=True)
    z_exp = zscore(raw, window=None)
    z_730 = zscore(raw, window=730)

    results = {"meta": {"seed": SEED, "block_weeks": BLOCK_WEEKS, "n_null_a": N_NULL_A,
                         "n_null_c": N_NULL_C, "n_boot_b": N_BOOT_B, "dims": DIMS,
                         "constants": {"candidate_lookback": LOOKBACK_CANDIDATE, "K": K_NEIGHBOR,
                                       "min_common_dim": MIN_COMMON_DIM, "std_min_obs": STD_MIN_OBS,
                                       "z_clip": Z_CLIP, "fwd_days": FWD_DAYS, "down_le": DOWN_LE,
                                       "up_ge": UP_GE, "seg_gap_days": SEG_GAP_DAYS,
                                       "shrink_k": SHRINK_K, "tilt_add": TILT_ADD,
                                       "tilt_trim": TILT_TRIM, "min_segments": MIN_SEGMENTS,
                                       "w_add": W_ADD, "w_trim": W_TRIM, "w_hold": W_HOLD,
                                       "cost_bps": COST_BPS, "halvings": HALVINGS,
                                       "extreme_window": EXTREME_WINDOW, "spearman_min": SPEARMAN_MIN}},
              "data": {"price_source": price_src,
                       "price_first": price.index[0].date().isoformat(),
                       "price_last": price.index[-1].date().isoformat(),
                       "price_n": int(len(price)),
                       "macro_daily_series": sorted(macro),
                       "macro_daily_counts": {k: len(v) for k, v in macro.items()},
                       "cross_check": xcheck},
              "variants": {}}

    print("[3] 主口径走步…", flush=True)
    rd = weekly_readings(z_exp, price, trim_needs_segments=False, uncond_in_space=False)
    rd = _add_realized(rd, price)
    # 检验区间:从第一个能出读数的周到「最后一个 180 天结果已知」的周一
    rd = rd[rd["realized_fwd180"].notna()].reset_index(drop=True)
    print(f"    周数 {len(rd)}  {rd['t'].iloc[0]} .. {rd['t'].iloc[-1]}", flush=True)
    outdir.mkdir(parents=True, exist_ok=True)
    rd.to_csv(outdir / "t340_weekly.csv", index=False)
    print(f"    → {outdir/'t340_weekly.csv'}", flush=True)

    res = {"n_weeks": int(len(rd)), "first_week": rd["t"].iloc[0], "last_week": rd["t"].iloc[-1],
           "stance_counts": {k: int(v) for k, v in rd["stance"].value_counts().items()},
           "stance_pct": {k: float(v) for k, v in
                          (rd["stance"].value_counts() / len(rd) * 100).round(2).items()},
           "a": crit_a(rd, price, price.index), "b": crit_b(rd),
           "c": crit_c(rd, price, price.index), "d": crit_d(rd, price, price.index),
           "e": crit_e(rd), "baselines": single_dim_baselines(rd, raw, z_exp)}
    w = np.where(rd["stance"] == "add", W_ADD,
                 np.where(rd["stance"] == "trim", W_TRIM, W_HOLD)).astype(float)
    changes = int((np.abs(np.diff(w)) > 1e-12).sum())
    years = max(len(rd) * 7.0 / 365.0, 1e-9)
    res["turnover_changes"] = changes
    res["turnover_per_year"] = changes / years
    res["independent_180d_intervals"] = int(len(rd) * 7 // FWD_DAYS)
    res["tilt_stats"] = {"mean": float(rd["tilt_excess"].mean()),
                         "std": float(rd["tilt_excess"].std(ddof=1)),
                         "min": float(rd["tilt_excess"].min()),
                         "max": float(rd["tilt_excess"].max())}
    res["all_pass"] = bool(
        res["a"]["pass_spearman"] and res["a"]["pass_p"] and res["b"]["pass_brier"]
        and res["b"]["pass_boot"] is not False and res["c"]["pass_return"] and res["c"]["pass_dd"]
        and res["c"]["pass_calmar"] is not False and res["d"]["pass_top_no_add"]
        and res["d"]["pass_bottom_no_trim"] and res["d"]["pass_ge2_top_trim"]
        and res["d"]["pass_ge2_bottom_add"] and res["e"]["pass"])
    results["main"] = res
    print(f"    (a) rho={res['a'].get('spearman')} p_upper={res['a'].get('p_upper')}", flush=True)
    print(f"    (b) brier {res['b'].get('brier_shrunk')} vs {res['b'].get('brier_uncond')} "
          f"q95={res['b'].get('boot_q95')}", flush=True)
    print(f"    (c) strat {res['c']['strategy'].get('total_return')} vs hold70 {res['c']['hold70'].get('total_return')} "
          f"dd {res['c']['strategy'].get('max_dd')}/{res['c']['hold70'].get('max_dd')} "
          f"calmar_p={res['c'].get('calmar_null_p')}", flush=True)
    print(f"    (d) tops_trim={res['d']['n_tops_with_trim']} bots_add={res['d']['n_bottoms_with_add']} "
          f"no_add_at_top={res['d']['pass_top_no_add']} no_trim_at_bottom={res['d']['pass_bottom_no_trim']}",
          flush=True)
    print(f"    (e) {res['e']}", flush=True)
    print(f"    stance {res['stance_counts']}  换仓/年 {res['turnover_per_year']:.2f}", flush=True)

    for vname, kw in variants.items():
        print(f"[4] 变体 {vname} …", flush=True)
        zz = z_730 if kw.get("z_window") == 730 else z_exp
        rv = weekly_readings(zz, price,
                             trim_needs_segments=kw.get("trim_needs_segments", False),
                             uncond_in_space=kw.get("uncond_in_space", False),
                             k=kw.get("k", K_NEIGHBOR))
        if len(rv) == 0:
            results["variants"][vname] = {"error": "无读数"}
            continue
        rv = _add_realized(rv, price)
        rv = rv[rv["realized_fwd180"].notna()].reset_index(drop=True)
        va, vb, vc, ve = crit_a(rv, price, price.index), crit_b(rv), crit_c(rv, price, price.index), crit_e(rv)
        results["variants"][vname] = {
            "n_weeks": int(len(rv)), "first_week": rv["t"].iloc[0], "last_week": rv["t"].iloc[-1],
            "stance_counts": {k: int(v) for k, v in rv["stance"].value_counts().items()},
            "a": va, "b": vb, "e": ve,
            "c_total_return": vc["strategy"]["total_return"], "c_hold70": vc["hold70"]["total_return"],
            "c_max_dd": vc["strategy"]["max_dd"], "c_hold70_max_dd": vc["hold70"]["max_dd"],
            "c_calmar_p": vc["calmar_null_p"],
            "d": crit_d(rv, price, price.index)}
        print(f"    (a) rho={va['spearman']} p={va['p_upper']} | (b) diff={vb['diff']:.5f} q95={vb['boot_q95']}"
              f" | (e) {ve.get('rho_h1')} / {ve.get('rho_h2')}", flush=True)

    json.dump(results, open(outdir / "t340_results.json", "w"), ensure_ascii=False, indent=2)
    print(f"[5] → {outdir/'t340_results.json'}", flush=True)
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(_REPO / "docs" / "research"))
    args = ap.parse_args()
    run(pathlib.Path(args.out), variants={
        "V1_trim_requires_3_segments": {"trim_needs_segments": True},
        "V2_rolling730_std": {"z_window": 730},
        "V3_uncond_in_space": {"uncond_in_space": True},
        "V4_K30": {"k": 30},
        "V5_K120": {"k": 120},
    })
