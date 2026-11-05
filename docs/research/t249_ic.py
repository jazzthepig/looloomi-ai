#!/usr/bin/env python3
"""T-249 · IC 乘数层的新喂料与走步验证(S-734)。

判据一字不改地照 S-734 预注册(REFUTATION_LEDGER.md, 2026-11-05)跑:

  喂料   cis_rebuild_daily(code_ref=cis-standard-v1.3, 时点重建的支柱 F/M/O/S/A)
         × 30 天相对基准超额 alpha(组 = crypto/tradfi;基准 BTC / SPY)
  截面   每月最后一个「两边都有数据」的交易日;组内 Spearman IC;截面 ≥ 8 名才算;
         支柱缺值的名字不进该支柱的截面
  乘数   支柱 p 在月末 m: IC̄_p = m 之前已到期的最近 24 个月末截面 IC 的均值
         乘数 = 1 + clamp(2.5 × IC̄_p, ±0.30),只有月聚类 t = IC̄/(sd/√n) ≥ 2.0 且 n ≥ 12 才启用
  走步   (a) 乘后总分的截面 IC − 不乘的 IC,月度差均值 > 0 且月聚类 t ≥ 2.0
         (b) 乘后总分前 1/5 的 30 天超额中位数不低于不乘的
         (c) 零信号对照:各支柱乘数在支柱间随机置换 1,000 次(种子 734),(a) 的均值差 ≥ 对照 95 分位
         (d) 逐期(2025H1 / 2025H2 / 2026)报,不判

总分一律调 `src/data/cis/cis_provider.calculate_total_score`(只 import,不改);
零分布/分位一律调 `src/data/evaluation/apparatus.py`(null_distribution / percentile_of)。

## 一处必须说明的偏差(不是判据的改动)

卡上点名的 y 表 `cis_standard_outcomes` 对 lane 的 publishable 只读 key 是 **401 permission denied**
(2026-11-05 实测;`signal_outcomes_unified` 同样 401)。因此本脚本用**仓库自己的生产者函数**
`src.data.cis.standard_outcomes.outcome_rows`(纯函数,只 import,不改) + 同一批收盘
(`asset_mcap_daily` source=coingecko_pro_market_chart 的 crypto 价格 / `ohlcv_daily` source=eodhd 的
传统资产收盘,传统资产按生产者的口径向前填 ≤ 4 天),把 alpha 逐 (symbol, d) 重算出来,
provenance = reconstructed(与卡上要的口径一致:只用重建序列的日期,正式发布的日期从 2026-10-10 起,
那部分是 provenance=published,卡上要的是 reconstructed)。

alpha 的定义、30 天持有期、成熟期切法(d + 30 ≤ last_close)全部沿用生产者的口径;
重算值与线上 `cis_standard_outcomes` 的一致性用**可读的** `signal_edge_map`(同一张表 RPC 聚合出来的
分档平均 alpha)交叉核对,结果见 t249_results.json 的 `validation` 段。

用法: python3 docs/research/t249_ic.py [--out docs/research/t249_results.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from src.data.cis.cis_provider import ASSETS_CONFIG, CRYPTO_ASSETS, calculate_total_score  # noqa: E402
from src.data.cis.rebuild import TRADFI  # noqa: E402  (传统资产的「类」集合,生产者同一份)
from src.data.cis.standard_outcomes import outcome_rows  # noqa: E402
from src.data.evaluation.apparatus import NoOpNull, null_distribution, percentile_of  # noqa: E402

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HEAD = {"apikey": KEY, "Authorization": "Bearer " + KEY}

CODE_REF = "cis-standard-v1.3"
START = "2023-01-01"           # 全样本起点(S-734:2023-01 → 最近到期月末)
WF_START = "2025-01"          # 走步起点(S-734 判据窗口)
LOOKBACK_M = 24               # IC̄ 用最近 24 个月末截面
MIN_N = 12                    # 启用门槛 n ≥ 12
T_ON = 2.0                    # 启用门槛月聚类 t ≥ 2.0
MIN_CROSS = 8                 # 截面 ≥ 8 名才算
CLAMP = 0.30                  # 乘数 clamp ±0.30
K = 2.5                       # 乘数斜率 2.5
N_PERM = 1000
SEED = 734
PILLARS = ("F", "M", "O", "S", "A")
PG = ("F", "M", "O", "S", "A")

REGIME_MAP = {
    "GOLDILOCKS": "Goldilocks", "RISK_ON": "Risk-On", "EASING": "Easing",
    "NEUTRAL": "Neutral", "TIGHTENING": "Tightening", "RISK_OFF": "Risk-Off",
    "STAGFLATION": "Stagflation",
}


# ── HTTP(只读)─────────────────────────────────────────────────────────────────
def _req(path, params=None, headers=None, timeout=120):
    url = URL + "/rest/v1/" + path
    if params:
        url = url + "?" + urllib.parse.urlencode(params, doseq=True)
    h = dict(HEAD)
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()[:300]


def exact_count(table, filters):
    st, body = _req(table, {"select": "count", **filters}, headers={"Prefer": "count=exact"})
    if st != 200:
        return None
    try:
        return json.loads(body)[0]["count"]
    except (ValueError, IndexError, KeyError):
        return None


def fetch_all(table, select, filters, order, page=1000, label=""):
    """按 order 逐页取,每页 ≤ 1000 行;抓完核总行数。"""
    rows, off = [], 0
    while True:
        params = {"select": select, "order": order}
        params.update(filters)
        st, body = _req(table, params, headers={"Range": f"{off}-{off + page - 1}"})
        if st == 416:
            break
        if st != 200:
            raise RuntimeError(f"{table} 取数失败 {st}: {body[:200]}")
        chunk = json.loads(body)
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < page:
            break
        off += page
    n_exact = exact_count(table, filters)
    if n_exact is not None and n_exact != len(rows):
        raise RuntimeError(f"{table} 行数核对失败:抓到 {len(rows)} / 表里 {n_exact}")
    print(f"  [fetch] {label or table}: {len(rows)} 行(核对通过)", flush=True)
    return rows


CACHE_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_cache/t249")


def fetch_cached(name, fn):
    """抓一次存到 Mac 数据根的 _cache(只读表的原始行);重跑不再打库。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"{name}.json"
    if p.exists():
        rows = json.loads(p.read_text(encoding="utf-8"))
        print(f"  [cache] {name}: {len(rows)} 行(本地缓存)", flush=True)
        return rows
    rows = fn()
    p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


# ── 统计 ───────────────────────────────────────────────────────────────────────
def spearman(x, y):
    xs = pd.Series(np.asarray(x, dtype=float))
    ys = pd.Series(np.asarray(y, dtype=float))
    m = xs.notna() & ys.notna()
    if int(m.sum()) < 3:
        return None
    rx = xs[m].rank().to_numpy()
    ry = ys[m].rank().to_numpy()
    if np.std(rx) == 0 or np.std(ry) == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def clustered_t(vals):
    v = np.array([x for x in vals if x is not None and math.isfinite(float(x))], dtype=float)
    n = int(v.size)
    if n < 2:
        return {"n": n, "mean": None, "sd": None, "t": None}
    mean = float(v.mean())
    sd = float(v.std(ddof=1))
    t = (mean / (sd / math.sqrt(n))) if sd > 0 else None
    return {"n": n, "mean": round(mean, 6), "sd": round(sd, 6),
            "t": (round(t, 4) if t is not None else None)}


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def top5_median(scores, alphas, k):
    """按分数取前 k 名,返回它们 alpha 的中位数。"""
    if not scores:
        return None
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], alphas[i]))
    sel = [alphas[i] for i in order[:k]]
    return float(np.median(sel)) if sel else None


# ── 主流程 ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "docs" / "research" / "t249_results.json"))
    ap.add_argument("--nperm", type=int, default=N_PERM, help="置换次数(默认 1000;调试用小值)")
    args = ap.parse_args()
    n_perm = args.nperm
    t_start = time.time()

    print("[1] 读宇宙与正式序列起点", flush=True)
    crypto_syms = {s: cfg for s, cfg in CRYPTO_ASSETS.items() if cfg.get("coingecko")}
    tradfi_syms = [s for s in ASSETS_CONFIG if s not in CRYPTO_ASSETS]
    classes = {s: cfg.get("class") for s, cfg in ASSETS_CONFIG.items()}
    st, body = _req("cis_official_daily", {"select": "d", "order": "d.asc", "limit": 1})
    official_start = str(json.loads(body)[0]["d"])[:10] if st == 200 and body else None
    print(f"  CIS 宇宙 {len(ASSETS_CONFIG)} 个(crypto {len(crypto_syms)} / 传统 {len(tradfi_syms)});"
          f" 正式发布起点 {official_start}", flush=True)

    # ── x 侧:时点重建的支柱 ───────────────────────────────────────────────────
    print("[2] 读 cis_rebuild_daily(时点重建支柱)", flush=True)
    sym_list = ",".join(sorted(ASSETS_CONFIG))
    reb = fetch_cached("rebuild_cis_v13", lambda: fetch_all(
        "cis_rebuild_daily",
        "symbol,d,asset_class,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,regime,signal,signal_pct,grade,score",
        {"code_ref": f"eq.{CODE_REF}", "d": f"gte.{START}", "symbol": f"in.({sym_list})"},
        "symbol.asc,d.asc", label="cis_rebuild_daily[CIS 宇宙, v1.3]"))

    # provenance=reconstructed:只用正式发布之前的日期(与卡上口径一致)
    reb_rec = [r for r in reb if official_start is None or str(r["d"])[:10] < official_start]
    print(f"  重建行 {len(reb)} → provenance=reconstructed 的 {len(reb_rec)} 行", flush=True)

    # ── y 侧:30 天相对基准超额 alpha(本地重算,口径同生产者)───────────────────
    print("[3] 读收盘并重算 alpha(用仓库自己的 outcome_rows)", flush=True)
    ids = ",".join(sorted({cfg["coingecko"] for cfg in crypto_syms.values()}))
    mc = fetch_cached("cg_closes", lambda: fetch_all("asset_mcap_daily", "coin_id,d,price,source",
                   {"source": "eq.coingecko_pro_market_chart", "coin_id": f"in.({ids})", "d": "gte.2022-11-01"},
                   "coin_id.asc,d.asc", label="asset_mcap_daily[CG 收盘]"))
    tf_list = ",".join(sorted(set(tradfi_syms) | {"SPY"}))
    oh = fetch_cached("eodhd_closes", lambda: fetch_all("ohlcv_daily", "symbol,trade_date,close,source",
                   {"source": "eq.eodhd", "symbol": f"in.({tf_list})", "trade_date": "gte.2022-08-01"},
                   "symbol.asc,trade_date.asc", label="ohlcv_daily[eodhd 收盘]"))

    closes: dict[str, pd.Series] = {}
    price_by_coin = defaultdict(dict)
    for r in mc:
        if r.get("price") is not None:
            price_by_coin[r["coin_id"]][str(r["d"])[:10]] = float(r["price"])
    for sym, cfg in crypto_syms.items():
        d = price_by_coin.get(cfg["coingecko"]) or {}
        if d:
            s = pd.Series(d)
            s.index = pd.to_datetime(s.index)
            closes[sym] = s.sort_index().astype(float)
    close_by_sym = defaultdict(dict)
    for r in oh:
        if r.get("close") is not None:
            close_by_sym[r["symbol"]][str(r["trade_date"])[:10]] = float(r["close"])
    for sym in sorted(set(tradfi_syms) | {"SPY"}):
        d = close_by_sym.get(sym) or {}
        if not d:
            continue
        s = pd.Series(d)
        s.index = pd.to_datetime(s.index)
        s = s.sort_index().astype(float)
        s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D")).ffill(limit=4)
        closes[sym] = s
    if "SPY" in classes and "SPY" not in closes:
        print("  [warn] SPY 没有收盘 —— 传统组基准缺失", flush=True)
    last_close = max((s.index.max() for s in closes.values() if len(s)), default=pd.Timestamp.utcnow())
    print(f"  收盘序列 {len(closes)} 条;last_close = {str(last_close)[:10]}", flush=True)

    points = defaultdict(list)
    for r in reb_rec:
        sig = r.get("signal_pct")
        if not sig:          # 生产者口径:没有信号的行不出结果行
            continue
        points[r["symbol"]].append({"d": str(r["d"])[:10], "signal": sig, "grade": r.get("grade"),
                                    "provenance": "reconstructed"})
    out_rows = outcome_rows(dict(points), closes, classes, TRADFI, last_close)
    alpha = {(r["symbol"], r["d"]): r["alpha"] for r in out_rows if r.get("alpha") is not None}
    print(f"  alpha 行 {len(alpha)}(成熟到 {last_close.date() - pd.Timedelta(days=30)})", flush=True)

    # ── 交叉表:重建行 × alpha ─────────────────────────────────────────────────
    rd = {}
    for r in reb_rec:
        rd[(r["symbol"], str(r["d"])[:10])] = r
    joint = [k for k in rd if k in alpha]
    print(f"  同名同日连接 {len(joint)} 行(重建 {len(rd)} / alpha {len(alpha)})", flush=True)

    def group_of(sym):
        """与生产者的 grp 同口径:cls ∈ TRADFI ⇒ tradfi(基准 SPY),否则 crypto(基准 BTC)。"""
        return "tradfi" if classes.get(sym) in TRADFI else "crypto"

    names_by_group_date = defaultdict(lambda: defaultdict(set))
    for sym, d in joint:
        names_by_group_date[group_of(sym)][d].add(sym)

    # 每月「重建序列里最后一个有数据的日」—— 用来标出被成熟期切短的那个月
    last_rebuild_date = defaultdict(dict)
    for (sym, d) in rd:
        g = group_of(sym)
        m = d[:7]
        if d > last_rebuild_date[g].get(m, ""):
            last_rebuild_date[g][m] = d

    # 每月最后一个「两边都有数据且 ≥8 名」的交易日
    xsec_date = {}
    for g, dd in names_by_group_date.items():
        by_month = defaultdict(list)
        for d in dd:
            by_month[d[:7]].append(d)
        for m, ds in by_month.items():
            ds.sort()
            pick = None
            for d in reversed(ds):
                if len(dd[d]) >= MIN_CROSS:
                    pick = d
                    break
            if pick:
                xsec_date[(g, m)] = pick

    def pillar_val(row, p):
        return row.get("pillar_" + p.lower())

    # ── ② 全样本:每支柱 × 每组的月度 IC 均值 / sd / n / 月聚类 t ───────────────
    print("[4] 算月度截面 IC", flush=True)
    ic_series = defaultdict(list)          # (group, pillar) → [(month, date, ic, n)]
    for (g, m), d in sorted(xsec_date.items()):
        syms = sorted(names_by_group_date[g][d])
        ys = [alpha[(s, d)] for s in syms]
        for p in PG:
            xs = [pillar_val(rd[(s, d)], p) for s in syms]
            keep = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
            if len(keep) < MIN_CROSS:
                continue
            ic = spearman([k[0] for k in keep], [k[1] for k in keep])
            if ic is not None:
                ic_series[(g, p)].append({"month": m, "date": d, "ic": round(ic, 6), "n": len(keep)})

    full_sample = {}
    for (g, p), rows in sorted(ic_series.items()):
        st_ = clustered_t([r["ic"] for r in rows])
        full_sample[f"{g}|{p}"] = {**st_, "months": [r["month"] for r in rows],
                                   "first": rows[0]["month"], "last": rows[-1]["month"]}
    print(f"  全样本: {len(full_sample)} 个 (组,支柱) 组合", flush=True)

    # ── 走步 ───────────────────────────────────────────────────────────────────
    print("[5] 走步(乘数 → 重算总分 → 截面 IC)", flush=True)
    months_all = sorted({m for (g, m) in xsec_date})
    wf_months = [m for m in months_all if m >= WF_START]
    print(f"  走步月份 {len(wf_months)}: {wf_months[0]} → {wf_months[-1]}", flush=True)

    def score_of(row, mult):
        pillars = {p: row.get("pillar_" + p.lower()) for p in PILLARS}
        reg = REGIME_MAP.get(str(row.get("regime") or "").upper(), "Neutral")
        return calculate_total_score(pillars, row.get("asset_class"), regime=reg, ic_mult=mult)["total_score"]

    wf_rows = []
    mult_by = {}                     # (g, month) → {pillar: mult}
    mult_info = {}                   # (g, month) → {pillar: 启用依据}
    mf_rows = []                     # 成熟期过滤前后的逐格对照
    for m in wf_months:
        for g in ("crypto", "tradfi"):
            mult = {}
            info = {}
            # as-of 截面日 D:该组本月的截面日;本月没有合格截面时,取该组 ≤ 本月末
            # 的最近一次截面日(取不到就没有历史可用)
            mdate = xsec_date.get((g, m))
            if mdate is None:
                cands = [d for (gg, mm), d in xsec_date.items() if gg == g and mm <= m]
                mdate = max(cands) if cands else None
            d_asof = date.fromisoformat(mdate) if mdate else None
            for p in PG:
                series = ic_series.get((g, p), [])
                # 已到期口径(S-734 原文:「m 之前**已到期**的最近 24 个月末截面」):
                # 历史截面 d' 的 30 天前瞻收益要到 d' + 30d 才成熟,必须 ≤ as-of 截面日 D。
                # 旧实现只比月份(r["month"] < m),会把 d' + 30d > D 的截面算进来 = 前视。
                hist = ([r for r in series
                         if d_asof is not None
                         and date.fromisoformat(r["date"]) + timedelta(days=30) <= d_asof]
                        [-LOOKBACK_M:] if d_asof is not None else [])
                # 旧口径(只比月份)保留作对照:过滤前后差多少
                hist_old = [r for r in series if r["month"] < m][-LOOKBACK_M:]
                ics = [r["ic"] for r in hist]
                s_new = clustered_t(ics)
                if len(ics) >= MIN_N:
                    t_ = s_new["t"]
                    if t_ is not None and t_ >= T_ON:
                        mult[p] = round(1.0 + clamp(K * s_new["mean"], -CLAMP, CLAMP), 6)
                    else:
                        mult[p] = 1.0
                else:
                    mult[p] = 1.0
                ics_old = [r["ic"] for r in hist_old]
                s_old = clustered_t(ics_old)
                mult_old = 1.0
                if len(ics_old) >= MIN_N:
                    t_old = s_old["t"]
                    if t_old is not None and t_old >= T_ON:
                        mult_old = round(1.0 + clamp(K * s_old["mean"], -CLAMP, CLAMP), 6)
                info[p] = {"n": len(ics), "ic_mean": (round(float(np.mean(ics)), 6) if ics else None),
                           "ic_sd": (round(float(np.std(ics, ddof=1)), 6) if len(ics) > 1 else None),
                           "t": (clustered_t(ics)["t"] if len(ics) > 1 else None),
                           "mult": mult[p],
                           "legacy_month_filter": {"n": len(ics_old),
                                                   "ic_mean": s_old["mean"], "t": s_old["t"],
                                                   "mult": mult_old}}
                mf_rows.append({"group": g, "month": m, "pillar": p, "asof": mdate,
                                "n_new": len(ics), "n_old": len(ics_old),
                                "mean_new": s_new["mean"], "mean_old": s_old["mean"],
                                "t_new": s_new["t"], "t_old": s_old["t"],
                                "mult_new": mult[p], "mult_old": mult_old})
            mult_by[(g, m)] = mult
            mult_info[(g, m)] = info

    def month_group_scores(g, m, mult):
        """返回 (names, score_mult, score_nomult, alphas) —— 用同一个生产函数算两遍。"""
        d = xsec_date[(g, m)]
        syms = sorted(s for s in names_by_group_date[g][d] if (s, d) in alpha)
        sm, sn, ys = [], [], []
        for s in syms:
            row = rd[(s, d)]
            sm.append(score_of(row, mult))
            sn.append(score_of(row, None))
            ys.append(alpha[(s, d)])
        return syms, sm, sn, ys

    for m in wf_months:
        rec = {"month": m, "groups": {}}
        diffs_g = []
        for g in ("crypto", "tradfi"):
            if (g, m) not in xsec_date:
                continue
            mult = mult_by[(g, m)]
            syms, sm, sn, ys = month_group_scores(g, m, mult)
            ic_m = spearman(sm, ys) if len(syms) >= MIN_CROSS else None
            ic_n = spearman(sn, ys) if len(syms) >= MIN_CROSS else None
            diff = (ic_m - ic_n) if (ic_m is not None and ic_n is not None) else None
            k = max(1, len(syms) // 5)
            top_m = top5_median(sm, ys, k)
            top_n = top5_median(sn, ys, k)
            rec["groups"][g] = {
                "date": xsec_date[(g, m)], "n": len(syms), "mult": mult,
                "ic_mult": (round(ic_m, 6) if ic_m is not None else None),
                "ic_nomult": (round(ic_n, 6) if ic_n is not None else None),
                "ic_diff": (round(diff, 6) if diff is not None else None),
                "top5_alpha_mult": (round(top_m, 6) if top_m is not None else None),
                "top5_alpha_nomult": (round(top_n, 6) if top_n is not None else None),
                "top5_diff": (round(top_m - top_n, 6) if (top_m is not None and top_n is not None) else None),
            }
            if diff is not None:
                diffs_g.append(diff)
        rec["ic_diff_avg"] = (round(float(np.mean(diffs_g)), 6) if diffs_g else None)
        wf_rows.append(rec)

    stat_all = clustered_t([r["ic_diff_avg"] for r in wf_rows if r.get("ic_diff_avg") is not None])
    stat_by_group = {g: clustered_t([r["groups"][g]["ic_diff"] for r in wf_rows
                                      if g in r["groups"] and r["groups"][g].get("ic_diff") is not None])
                     for g in ("crypto", "tradfi")}
    # (b) 也是月聚类:先按月把两组的「前 1/5 超额中位数差」平均,再对月做 t
    for r in wf_rows:
        ds = [r["groups"][g]["top5_diff"] for g in ("crypto", "tradfi")
              if g in r["groups"] and r["groups"][g].get("top5_diff") is not None]
        r["top5_diff_avg"] = (round(float(np.mean(ds)), 6) if ds else None)
    b_all = clustered_t([r["top5_diff_avg"] for r in wf_rows if r.get("top5_diff_avg") is not None])
    b_by_group = {g: clustered_t([r["groups"][g]["top5_diff"] for r in wf_rows
                                   if g in r["groups"] and r["groups"][g].get("top5_diff") is not None])
                  for g in ("crypto", "tradfi")}
    print(f"  (a) 月度差均值 {stat_all['mean']} t={stat_all['t']} n={stat_all['n']};"
          f"  crypto {stat_by_group['crypto']['mean']}/{stat_by_group['crypto']['t']};"
          f"  tradfi {stat_by_group['tradfi']['mean']}/{stat_by_group['tradfi']['t']}", flush=True)
    print(f"  (b) 前 1/5 超额中位数差 均值 {b_all['mean']} t={b_all['t']} n={b_all['n']}", flush=True)

    # ── (c) 零信号对照:乘数在支柱间随机置换 ───────────────────────────────────
    print("[6] (c) 零信号对照:1,000 次乘数置换(种子 734)", flush=True)
    actual = stat_all["mean"]

    # 置换时复用「不乘」的 IC 与 alpha(只重算被置换的乘数那一遍)
    xsec_cache, nomult_ic = {}, {}
    for (g, m) in xsec_date:
        if m not in wf_months:
            continue
        d = xsec_date[(g, m)]
        syms = sorted(s for s in names_by_group_date[g][d] if (s, d) in alpha)
        ys = [alpha[(s, d)] for s in syms]
        xsec_cache[(g, m)] = (syms, ys)
        nomult_ic[(g, m)] = spearman([score_of(rd[(s, d)], None) for s in syms], ys)

    def perm_stat(rng):
        diffs = []
        for r in wf_rows:
            m = r["month"]
            gs = []
            for g in ("crypto", "tradfi"):
                if g not in r["groups"]:
                    continue
                mult = mult_by[(g, m)]
                vals = [mult[p] for p in PG]
                idx = rng.permutation(len(PG))
                perm = {PG[i]: vals[idx[i]] for i in range(len(PG))}
                syms, ys = xsec_cache[(g, m)]
                sm = [score_of(rd[(s, xsec_date[(g, m)])], perm) for s in syms]
                ic_m = spearman(sm, ys)
                ic_n = nomult_ic[(g, m)]
                if ic_m is not None and ic_n is not None:
                    gs.append(ic_m - ic_n)
            if gs:
                diffs.append(float(np.mean(gs)))
        return float(np.mean(diffs)) if diffs else float("nan")

    c_res = {"actual_mean_diff": actual, "n_perm": n_perm, "seed": SEED}
    try:
        null = null_distribution(perm_stat, n_perm, SEED)
        p = percentile_of(actual, null)
        c_res.update({"percentile_of_actual": p,
                      "null_mean": round(float(np.mean(null)), 6),
                      "null_p95": round(float(np.percentile(null, 95)), 6),
                      "null_p05": round(float(np.percentile(null, 5)), 6),
                      "null_min": round(float(np.min(null)), 6),
                      "null_max": round(float(np.max(null)), 6),
                      "no_op_null": False,
                      "verdict": bool(actual is not None and actual >= float(np.percentile(null, 95)))})
    except NoOpNull as exc:
        c_res.update({"no_op_null": True, "why": str(exc), "verdict": None})
    print(f"  (c) 实际 {actual} / 对照 p95 {c_res.get('null_p95')} / 分位 {c_res.get('percentile_of_actual')}", flush=True)

    # ── (d) 逐期 ───────────────────────────────────────────────────────────────
    periods = {"2025H1": ("2025-01", "2025-06"), "2025H2": ("2025-07", "2025-12"), "2026": ("2026-01", "2026-12")}
    by_period = {}
    for name, (lo, hi) in periods.items():
        sel = [r for r in wf_rows if lo <= r["month"] <= hi]
        s_ = clustered_t([r["ic_diff_avg"] for r in sel if r.get("ic_diff_avg") is not None])
        per_g = {g: clustered_t([r["groups"][g]["ic_diff"] for r in sel if g in r["groups"]
                                 and r["groups"][g].get("ic_diff") is not None]) for g in ("crypto", "tradfi")}
        by_period[name] = {"months": [r["month"] for r in sel], "all": s_, "crypto": per_g["crypto"], "tradfi": per_g["tradfi"]}

    # ── 稳健性:最后一个月(成熟期切在半路,截面日不是月末)单独剔掉 ────────────
    trunc = [r["month"] for r in wf_rows
             if any(r["groups"][g]["date"] != last_rebuild_date[g].get(r["month"]) for g in r["groups"])]
    wf_keep = [r for r in wf_rows if r["month"] not in trunc]
    robust = {
        "truncated_months": trunc,
        "a_all_excl_truncated": clustered_t([r["ic_diff_avg"] for r in wf_keep if r.get("ic_diff_avg") is not None]),
        "a_crypto_excl_truncated": clustered_t([r["groups"]["crypto"]["ic_diff"] for r in wf_keep
                                                if "crypto" in r["groups"] and r["groups"]["crypto"].get("ic_diff") is not None]),
        "a_tradfi_excl_truncated": clustered_t([r["groups"]["tradfi"]["ic_diff"] for r in wf_keep
                                                if "tradfi" in r["groups"] and r["groups"]["tradfi"].get("ic_diff") is not None]),
        "b_all_excl_truncated": clustered_t([r["top5_diff_avg"] for r in wf_keep if r.get("top5_diff_avg") is not None]),
    }

    # ── 乘数启用清单 ──────────────────────────────────────────────────────────
    activated = []
    for (g, m), info in sorted(mult_info.items()):
        for p, d_ in info.items():
            if abs(d_["mult"] - 1.0) > 1e-12:
                activated.append({"group": g, "month": m, "pillar": p, **d_})
    mult_summary = {"n_active_cells": len(activated),
                     "n_cells_total": len(mult_info) * len(PG),
                     "activated": activated}

    # ── 校验:重算的总分 vs 重建表里存的总分;alpha vs 线上 edge map ────────────
    print("[7] 校验", flush=True)
    sample = reb_rec[:400]
    diffs = []
    for r in sample:
        if r.get("score") is None:
            continue
        pillars = {p: r.get("pillar_" + p.lower()) for p in PILLARS}
        reg = REGIME_MAP.get(str(r.get("regime") or "").upper(), "Neutral")
        got = calculate_total_score(pillars, r.get("asset_class"), regime=reg, ic_mult=None)["total_score"]
        diffs.append(abs(got - float(r["score"])))
    score_check = {"n": len(diffs), "max_abs_diff": (round(max(diffs), 4) if diffs else None),
                   "share_within_0.011": (round(float(np.mean([d <= 0.011 for d in diffs])), 4) if diffs else None)}

    edge_check = None
    st, body = _req("signal_edge_map", {"select": "benchmark,signal,risk_band,n,avg_alpha_pct", "limit": 1000})
    if st == 200:
        erows = json.loads(body)
        # edge_map 的 'btc' 基准行 = crypto 组、alpha = a_ret − b_ret(BTC),bench_trail_30d 非空 —— 与本地重算同口径
        by_sig = defaultdict(list)
        for r in erows:
            if r.get("benchmark") == "btc" and r.get("n") and r.get("avg_alpha_pct") is not None:
                by_sig[r["signal"]].append((r["n"], r["avg_alpha_pct"]))
        mine = defaultdict(list)
        for r in out_rows:
            if (r.get("grp") == "crypto" and r.get("alpha") is not None and r.get("signal")
                    and r.get("bench_trail_30d") is not None):
                mine[r["signal"]].append(r["alpha"] * 100.0)
        cmp_rows = []
        for sig in sorted(set(by_sig) | set(mine)):
            pairs = by_sig.get(sig) or []
            n_e = sum(p[0] for p in pairs)
            mean_e = (sum(p[0] * p[1] for p in pairs) / n_e) if n_e else None
            m = mine.get(sig) or []
            mean_m = float(np.mean(m)) if m else None
            cmp_rows.append({"signal": sig, "edge_map_n": n_e,
                             "edge_map_mean_alpha_pct": (round(mean_e, 4) if mean_e is not None else None),
                             "recomputed_n": len(m),
                             "recomputed_mean_alpha_pct": (round(mean_m, 4) if mean_m is not None else None),
                             "diff_pp": (round(mean_m - mean_e, 4) if (mean_e is not None and mean_m is not None) else None)})
        edge_check = {"scope": "edge_map benchmark='btc'(crypto 组,alpha = a_ret − b_ret vs BTC,bench_trail_30d 非空)",
                      "by_signal": cmp_rows,
                      "note": "edge_map 是同一张 cis_standard_outcomes 的 RPC 聚合(含 published 段);"
                              "recomputed 是本地重算(reconstructed 段)—— 段不同,数应接近"}

    results = {
        "card": "T-249", "ledger": "S-734", "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe": {"n_assets": len(ASSETS_CONFIG), "crypto": len(crypto_syms), "tradfi": len(tradfi_syms),
                     "official_start": official_start, "code_ref": CODE_REF, "last_close": str(last_close)[:10]},
        "data": {"rebuild_rows_cis_universe": len(reb), "rebuild_rows_reconstructed": len(reb_rec),
                 "alpha_rows": len(alpha), "joint_rows": len(joint),
                 "monthly_cross_sections": len(xsec_date),
                 "alpha_source": "本地重算(cis_standard_outcomes 对 publishable key 401):"
                                 "仓库的 src/data/cis/standard_outcomes.outcome_rows + 同一批收盘"},
        "full_sample_ic": full_sample,
        "walkforward": {"months": wf_months, "rows": wf_rows,
                        "a_all": stat_all, "a_crypto": stat_by_group["crypto"], "a_tradfi": stat_by_group["tradfi"],
                        "b_all": b_all, "b_crypto": b_by_group["crypto"], "b_tradfi": b_by_group["tradfi"]},
        "c_null": c_res,
        "d_by_period": by_period,
        "multipliers": mult_summary,
        "maturity_filter": {
            "rule": "历史截面 d' 只有在 d' + 30d ≤ 该组该月的 as-of 截面日 D 时才算「已到期」;"
                    "旧实现只比月份(r['month'] < m),会把 d'+30d > D 的截面算进来 = 前视",
            "asof": "D = 该组该月的截面日;该月无合格截面时取该组 ≤ 本月末的最近截面日",
            "n_cells": len(mf_rows),
            "cells_n_changed": sum(1 for r in mf_rows if r["n_new"] != r["n_old"]),
            "cells_mult_changed": sum(1 for r in mf_rows if r["mult_new"] != r["mult_old"]),
            "cells_t_changed": sum(1 for r in mf_rows if r["t_new"] != r["t_old"]),
            "max_abs_delta_mean": (max(abs(r["mean_new"] - r["mean_old"]) for r in mf_rows
                                       if r["mean_new"] is not None and r["mean_old"] is not None)
                                   if mf_rows else None),
            "max_abs_delta_t": (max(abs(r["t_new"] - r["t_old"]) for r in mf_rows
                                    if r["t_new"] is not None and r["t_old"] is not None)
                                if mf_rows else None),
            "rows": mf_rows,
        },
        "robustness": robust,
        "validation": {"score_recompute_vs_stored": score_check, "alpha_vs_edge_map": edge_check},
        "runtime_sec": round(time.time() - t_start, 1),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[8] 写 {out_path}  ({round(time.time() - t_start, 1)}s)", flush=True)
    print("SUMMARY " + json.dumps({"a": stat_all, "b": b_all, "c": c_res, "d": by_period}, ensure_ascii=False)[:4000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
