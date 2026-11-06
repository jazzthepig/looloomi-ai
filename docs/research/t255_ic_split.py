#!/usr/bin/env python3
"""T-255(S-734 后续 · 只报不判):支柱截面 IC 的分时段 / 分 regime 稳定性。

口径(与 T-249 同,不复用它的结论,只复用它的数据层):
  · 数据层:_cache/t249/ 里的原始行(rebuild_cis_v13 / cg_closes / eodhd_closes)——
    不重抓。alpha 用生产函数 `outcome_rows` 本地重算。
  · 月末截面:每月最后一个「组内 ≥8 名」有数据的交易日;alpha 必须已到期(d+30 ≤ last_close)。
  · 组内 Spearman:pillar_x 与 30 天相对基准超额 alpha 的秩相关(与 T-249 逐字同一实现)。
  · regime:majors cap 风格指数(style_index_pit_daily)按 ret 复原水平 vs 自身 200 日均线
    —— 与 `src/data/signals/multiplier.py::_majors_gate` 同一读法;只用 ≤ 截面日的数据。
  · 零信号对照:截面内「名字 ↔ 超额」的对应打乱 1,000 次(种子 255)——
    `apparatus.shuffle_within` + `apparatus.null_distribution` + `apparatus.percentile_of`。

只报不判:任何「可以改权重」的念头都写成待预注册的假设,不写成建议。

用法:python3 docs/research/t255_ic_split.py [--nperm 1000] [--out docs/research/t255_results.json]
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
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.data.cis.cis_provider import ASSETS_CONFIG, CRYPTO_ASSETS  # noqa: E402
from src.data.cis.rebuild import TRADFI  # noqa: E402
from src.data.cis.standard_outcomes import outcome_rows  # noqa: E402
from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull, null_distribution, percentile_of, shuffle_within,
)

# ── 常量 ───────────────────────────────────────────────────────────────────────
CACHE_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_cache/t249")
STYLE_CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/_cache/t255/style_majors_cap.json")
T249_RESULTS = REPO / "docs" / "research" / "t249_results.json"
CODE_REF = "cis-standard-v1.3"
START = "2023-01-01"
PG = ("F", "M", "O", "S", "A")
GROUPS = ("crypto", "tradfi")
MIN_CROSS = 8          # 截面 ≥ 8 名才算(同 T-249)
LOOKBACK_M = 24        # IC̄ 用最近 24 个月末截面(同 T-249)
P1_LAST = "2024-12"    # 分段:2023-01→2024-12 / 2025-01→末
SEED = 255
N_PERM = 1000
MA_WIN = 200           # majors 200 日均线

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    print("缺 SUPABASE_URL / SUPABASE_KEY —— 报错退出", file=sys.stderr)
    sys.exit(2)
HEAD = {"apikey": KEY, "Authorization": "Bearer " + KEY}


# ── HTTP(只读)──────────────────────────────────────────────────────────────────
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


# ── 统计(与 T-249 逐字一致)────────────────────────────────────────────────────
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


def monthly_t(vals):
    """月度 IC 序列的 t 统计(同 T-249 的 clustered_t)。"""
    v = np.array([x for x in vals if x is not None and math.isfinite(float(x))], dtype=float)
    n = int(v.size)
    if n < 2:
        return {"n": n, "mean": None, "sd": None, "t": None}
    mean = float(v.mean())
    sd = float(v.std(ddof=1))
    t = (mean / (sd / math.sqrt(n))) if sd > 0 else None
    return {"n": n, "mean": round(mean, 6), "sd": round(sd, 6),
            "t": (round(t, 4) if t is not None else None)}


# ── 数据层(复用 T-249 的缓存,不重抓)──────────────────────────────────────────
def load_cached(name):
    p = CACHE_DIR / f"{name}.json"
    rows = json.loads(p.read_text(encoding="utf-8"))
    print(f"  [cache] {name}: {len(rows)} 行", flush=True)
    return rows


def build_closes(crypto_syms, tradfi_syms):
    """与 T-249 同:CG 收盘(coin_id → symbol)+ EODHD 收盘(传统资产向前填 ≤ 4 天)。"""
    mc = load_cached("cg_closes")
    oh = load_cached("eodhd_closes")
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
    return closes


def majors_regime():
    """majors cap 风格指数 → 每个日期「在/不在自己的 200 日均线上方」。
    读法与 src/data/signals/multiplier.py::_majors_gate 一致:(n<200) | (lvl > sma)。"""
    if STYLE_CACHE.exists():
        rows = json.loads(STYLE_CACHE.read_text(encoding="utf-8"))
        print(f"  [cache] style_majors_cap: {len(rows)} 行", flush=True)
    else:
        rows = fetch_all("style_index_pit_daily", "d,ret,style,weighting",
                         {"style": "eq.majors", "weighting": "eq.cap"}, "d.asc",
                         label="style_index_pit_daily[majors, cap]")
        STYLE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        STYLE_CACHE.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    r = pd.Series({str(pd.Timestamp(x["d"]))[:10]: float(x["ret"]) for x in rows
                   if x.get("ret") is not None and float(x["ret"]) > -0.95}, dtype=float).sort_index()
    lvl = (1 + r).cumprod()
    sma = lvl.rolling(MA_WIN, min_periods=1).mean()
    n = lvl.rolling(MA_WIN, min_periods=1).count()
    above = ((n < MA_WIN) | (lvl > sma))
    warm = int((n < MA_WIN).sum())
    out = {str(d)[:10]: (bool(above.loc[d]), int(n.loc[d])) for d in lvl.index}
    return out, {"rows": len(r), "first": str(r.index.min())[:10], "last": str(r.index.max())[:10],
                 "warmup_days_below_200": warm}


def bench_regime(px):
    """组内基准(SPY / BTC)自身收盘 vs 它的 200 日均线(日历日口径,和风格指数同一约定)。"""
    s = px.reindex(pd.date_range(px.index.min(), px.index.max(), freq="D")).ffill()
    sma = s.rolling(MA_WIN, min_periods=1).mean()
    n = s.rolling(MA_WIN, min_periods=1).count()
    above = ((n < MA_WIN) | (s > sma))
    return {str(d)[:10]: bool(above.loc[d]) for d in s.index}


# ── 主流程 ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "docs" / "research" / "t255_results.json"))
    ap.add_argument("--nperm", type=int, default=N_PERM)
    args = ap.parse_args()
    n_perm = args.nperm
    t0 = time.time()

    print("[1] 宇宙与正式发布起点", flush=True)
    crypto_syms = {s: cfg for s, cfg in CRYPTO_ASSETS.items() if cfg.get("coingecko")}
    tradfi_syms = [s for s in ASSETS_CONFIG if s not in CRYPTO_ASSETS]
    classes = {s: cfg.get("class") for s, cfg in ASSETS_CONFIG.items()}
    st, body = _req("cis_official_daily", {"select": "d", "order": "d.asc", "limit": 1})
    official_start = str(json.loads(body)[0]["d"])[:10] if st == 200 and body else None
    t249 = json.loads(T249_RESULTS.read_text(encoding="utf-8"))
    official_start_file = t249["universe"]["official_start"]
    print(f"  宇宙 {len(ASSETS_CONFIG)}(crypto {len(crypto_syms)} / 传统 {len(tradfi_syms)});"
          f" 正式起点 {official_start}(T-249 文件记 {official_start_file})", flush=True)

    print("[2] 读重建行 + 重算 alpha", flush=True)
    reb = load_cached("rebuild_cis_v13")
    reb_rec = [r for r in reb if official_start is None or str(r["d"])[:10] < official_start]
    closes = build_closes(crypto_syms, tradfi_syms)
    last_close = max((s.index.max() for s in closes.values() if len(s)), default=pd.Timestamp.utcnow())
    points = defaultdict(list)
    for r in reb_rec:
        sig = r.get("signal_pct")
        if not sig:
            continue
        points[r["symbol"]].append({"d": str(r["d"])[:10], "signal": sig, "grade": r.get("grade"),
                                    "provenance": "reconstructed"})
    out_rows = outcome_rows(dict(points), closes, classes, TRADFI, last_close)
    alpha = {(r["symbol"], r["d"]): r["alpha"] for r in out_rows if r.get("alpha") is not None}
    print(f"  重建行 {len(reb)} → reconstructed {len(reb_rec)};alpha 行 {len(alpha)}"
          f"(成熟到 {last_close.date() - pd.Timedelta(days=30)})", flush=True)

    rd = {(r["symbol"], str(r["d"])[:10]): r for r in reb_rec}
    joint = [k for k in rd if k in alpha]
    names_by_group_date = defaultdict(lambda: defaultdict(set))
    for sym, d in joint:
        g = "tradfi" if classes.get(sym) in TRADFI else "crypto"
        names_by_group_date[g][d].add(sym)
    xsec_date = {}
    for g, dd in names_by_group_date.items():
        by_month = defaultdict(list)
        for d in dd:
            by_month[d[:7]].append(d)
        for m, ds in by_month.items():
            pick = None
            for d in sorted(ds, reverse=True):
                if len(dd[d]) >= MIN_CROSS:
                    pick = d
                    break
            if pick:
                xsec_date[(g, m)] = pick
    print(f"  月末截面 {len(xsec_date)} 个(组×月);样本内共 {len(joint)} 行", flush=True)

    print("[3] regime:majors 200 日线(+ 组内基准 200 日线,补充)", flush=True)
    regime, regime_meta = majors_regime()
    style_days = sorted(regime)
    bench_reg = {"crypto": bench_regime(closes["BTC"]) if "BTC" in closes else {},
                 "tradfi": bench_regime(closes["SPY"]) if "SPY" in closes else {}}
    bench_meta = {g: {"days": len(v), "first": (min(v) if v else None), "last": (max(v) if v else None)}
                  for g, v in bench_reg.items()}

    def regime_of(d):
        """截面日 d 的 regime(as-of:只用 ≤ d 的数据)。"""
        if d in regime:
            return regime[d][0]
        prior = [x for x in style_days if x <= d]
        if not prior:
            return None
        return regime[prior[-1]][0]

    def bench_of(g, d):
        """组内基准 200 日线 regime(as-of ≤ d)。"""
        m = bench_reg.get(g) or {}
        if d in m:
            return m[d]
        prior = [x for x in sorted(m) if x <= d]
        return m[prior[-1]] if prior else None

    print("[4] 逐月截面 IC", flush=True)
    ic_series = defaultdict(list)          # (group, pillar) → [{month,date,ic,n,regime}]
    ic_data = defaultdict(dict)            # (group, pillar) → date → (xs, ys)
    for (g, m), d in sorted(xsec_date.items()):
        syms = sorted(names_by_group_date[g][d])
        ys = [alpha[(s, d)] for s in syms]
        for p in PG:
            xs = [rd[(s, d)].get("pillar_" + p.lower()) for s in syms]
            keep = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
            if len(keep) < MIN_CROSS:
                continue
            ic = spearman([k[0] for k in keep], [k[1] for k in keep])
            if ic is None:
                continue
            ic_series[(g, p)].append({"month": m, "date": d, "ic": round(ic, 6), "n": len(keep)})
            ic_data[(g, p)][d] = ([k[0] for k in keep], [k[1] for k in keep])
    print(f"  (组,支柱) 组合 {len(ic_series)} 个", flush=True)

    # 自检:复算的全样本 IC 必须与 T-249 的结果一致(不是继承它的结论,是核一遍)
    repro = {}
    for (g, p), rows in sorted(ic_series.items()):
        stt = monthly_t([r["ic"] for r in rows])
        repro[f"{g}|{p}"] = {**stt, "months": [r["month"] for r in rows],
                             "first": rows[0]["month"], "last": rows[-1]["month"]}
    ref = t249["full_sample_ic"]
    diffs = []
    for k, v in repro.items():
        r0 = ref.get(k)
        if r0 is None:
            diffs.append((k, "缺", None, None))
            continue
        for f in ("n", "mean", "sd", "t"):
            a, b = v.get(f), r0.get(f)
            if a is None or b is None:
                if a is not b:
                    diffs.append((k, f, a, b))
            elif abs(float(a) - float(b)) > 1e-6:
                diffs.append((k, f, a, b))
        if v["months"] != r0.get("months"):
            diffs.append((k, "months", len(v["months"]), len(r0.get("months") or [])))
    print(f"  自检:与 T-249 全样本 IC 对照 {len(repro)} 格,不一致 {len(diffs)} 处", flush=True)
    for d0 in diffs[:10]:
        print("   ", d0, flush=True)

    # ── 零信号对照用的秩矩阵 ──────────────────────────────────────────────────
    print("[5] 准备零信号对照的秩(截面内打乱名字↔超额)", flush=True)
    ranks = {}
    for key, bydate in ic_data.items():
        per = {}
        for d, (xs, ys) in bydate.items():
            rx = pd.Series(np.asarray(xs, dtype=float)).rank().to_numpy()
            ry = pd.Series(np.asarray(ys, dtype=float)).rank().to_numpy()
            if np.std(rx) == 0 or np.std(ry) == 0:
                continue
            rx_c = rx - rx.mean()
            ry_c = ry - ry.mean()
            per[d] = {"rx_unit": (rx_c / np.linalg.norm(rx_c)).astype(float),
                      "ry": ry, "ry_norm": float(np.linalg.norm(ry_c)),
                      "n": len(rx)}
        ranks[key] = per

    def prepare_cell(key, dates):
        """把一个格子的各截面秩向量拼起来(每个截面一段),打乱时按段(=按截面)分组。"""
        per = ranks[key]
        rx_all, ry_all, groups, slices = [], [], [], []
        off = 0
        for d in dates:
            p = per.get(d)
            if p is None:
                continue
            rx_all.append(p["rx_unit"])
            ry_all.append(p["ry"])
            groups += [d] * p["n"]
            slices.append((off, off + p["n"], p["ry_norm"]))
            off += p["n"]
        if not rx_all:
            return None
        return (np.concatenate(rx_all), np.concatenate(ry_all),
                np.array(groups, dtype=object), slices)

    def perm_cell_mean(rng, prep):
        """一次置换:每个截面内打乱「名字↔超额」的对应(= 打乱该截面的秩向量;
        秩是超额的单调函数,置换与之可交换 ⇒ 与打乱超额原值等价),再对截面取均值。"""
        rx_all, ry_all, groups, slices = prep
        ry_p = np.asarray(shuffle_within(ry_all, groups, rng), dtype=float)
        tot = 0.0
        for (a, b, ry_norm) in slices:
            tot += float(rx_all[a:b] @ ry_p[a:b]) / ry_norm
        return tot / len(slices)

    def cell_null(key, dates, actual):
        """零分布:1,000 次打乱,种子 255(apparatus.null_distribution)。"""
        if len(dates) < 2:
            return None, "n<2"
        prep = prepare_cell(key, dates)
        if prep is None:
            return None, "没有可用截面"
        try:
            null = null_distribution(lambda rng: perm_cell_mean(rng, prep),
                                     n_perm, SEED, actual)
        except NoOpNull as exc:
            return None, f"NoOpNull:{exc}"
        return null, None

    # ── 分格统计 ─────────────────────────────────────────────────────────────
    print("[6] 分时段 / 分 regime 的逐格统计 + 零信号对照", flush=True)
    cells = ["full", "p1", "p2", "above", "below", "p1_above", "p1_below", "p2_above", "p2_below",
             "bench_above", "bench_below"]

    def dates_for(key, cell):
        g = key[0]
        rows = ic_series[key]
        out = []
        for r in rows:
            m, d = r["month"], r["date"]
            reg = regime_of(d)
            breg = bench_of(g, d)
            if cell == "full":
                pass
            elif cell == "p1" and m > P1_LAST:
                continue
            elif cell == "p2" and m <= P1_LAST:
                continue
            elif cell == "above" and reg is not True:
                continue
            elif cell == "below" and reg is not False:
                continue
            elif cell == "p1_above" and not (m <= P1_LAST and reg is True):
                continue
            elif cell == "p1_below" and not (m <= P1_LAST and reg is False):
                continue
            elif cell == "p2_above" and not (m > P1_LAST and reg is True):
                continue
            elif cell == "p2_below" and not (m > P1_LAST and reg is False):
                continue
            elif cell == "bench_above" and breg is not True:
                continue
            elif cell == "bench_below" and breg is not False:
                continue
            out.append(d)
        return out

    out_cells = {}
    for key in sorted(ic_series):
        g, p = key
        out_cells[f"{g}|{p}"] = {}
        for cell in cells:
            ds = dates_for(key, cell)
            ics = [r["ic"] for r in ic_series[key] if r["date"] in set(ds)]
            stt = monthly_t(ics)
            null, err = cell_null(key, ds, stt["mean"])
            pct = percentile_of(stt["mean"], null) if null is not None else None
            months = [r["month"] for r in ic_series[key] if r["date"] in set(ds)]
            out_cells[f"{g}|{p}"][cell] = {
                **stt, "months": months,
                "null_pct": (round(pct, 4) if pct is not None else None),
                "null_mean": (round(float(np.mean(null)), 6) if null is not None else None),
                "null_sd": (round(float(np.std(null, ddof=1)), 6) if null is not None and len(null) > 1 else None),
                "null_n": (int(len(null)) if null is not None else 0),
                "null_error": err,
            }
            print(f"   {g:6s} {p} {cell:9s} n={stt['n']:3d} mean={stt['mean']} t={stt['t']}"
                  f" pct={out_cells[f'{g}|{p}'][cell]['null_pct']}", flush=True)

    # ── 符号翻转格子 ─────────────────────────────────────────────────────────
    flips = []
    for k in sorted(out_cells):
        c = out_cells[k]
        pairs = [("p1", "p2"), ("above", "below"), ("p1_above", "p2_above"),
                 ("p1_below", "p2_below"), ("full", "p1"), ("full", "p2"),
                 ("bench_above", "bench_below")]
        for a, b in pairs:
            ma, mb = c[a]["mean"], c[b]["mean"]
            if ma is None or mb is None or ma == 0 or mb == 0:
                continue
            if (ma > 0) != (mb > 0):
                # full 是 p1/p2 的混合,full↔p1/p2 的「翻转」是机械的(哪一段占权重大),
                # 不算独立信息;两侧 n < 10 的格子样本太小,单独标出来。
                mechanical = "full" in (a, b)
                informative = (not mechanical) and c[a]["n"] >= 10 and c[b]["n"] >= 10
                flips.append({"key": k, "left": a, "left_mean": ma, "left_t": c[a]["t"], "left_n": c[a]["n"],
                              "right": b, "right_mean": mb, "right_t": c[b]["t"], "right_n": c[b]["n"],
                              "left_pct": c[a]["null_pct"], "right_pct": c[b]["null_pct"],
                              "kind": ("mechanical_full_vs_part" if mechanical else
                                       ("informative" if informative else "thin_n"))})
    n_inf = sum(1 for f in flips if f["kind"] == "informative")
    n_thin = sum(1 for f in flips if f["kind"] == "thin_n")
    n_mech = sum(1 for f in flips if f["kind"] == "mechanical_full_vs_part")
    print(f"[7] 符号翻转格子 {len(flips)} 处(informative {n_inf} / 薄样本 {n_thin} / 机械 {n_mech})", flush=True)

    # ── 多重比较 + regime 与时段的混淆度 ────────────────────────────────────
    n_cells = sum(len(v) for v in out_cells.values())
    sig_lo = [(k, c) for k, v in out_cells.items() for c, x in v.items()
              if x["null_pct"] is not None and x["null_pct"] <= 0.05]
    sig_hi = [(k, c) for k, v in out_cells.items() for c, x in v.items()
              if x["null_pct"] is not None and x["null_pct"] >= 0.95]
    bonf = 0.05 / max(1, n_cells)
    sig_lo_b = [x for x in sig_lo if out_cells[x[0]][x[1]]["null_pct"] <= bonf]
    sig_hi_b = [x for x in sig_hi if out_cells[x[0]][x[1]]["null_pct"] >= 1 - bonf]
    regime_mix = {}
    for g in GROUPS:
        c = out_cells[f"{g}|F"]
        regime_mix[g] = {"p1_above": c["p1_above"]["n"], "p1_below": c["p1_below"]["n"],
                         "p2_above": c["p2_above"]["n"], "p2_below": c["p2_below"]["n"],
                         "bench_above": c["bench_above"]["n"], "bench_below": c["bench_below"]["n"]}
    print(f"  多重比较:共 {n_cells} 格;分位 ≤0.05 有 {len(sig_lo)} 格、≥0.95 有 {len(sig_hi)} 格;"
          f"Bonferroni 阈值 {bonf:.5f} ⇒ 仍显著 {len(sig_lo_b) + len(sig_hi_b)} 格", flush=True)
    print(f"  regime 与时段混淆(月份数):{regime_mix}", flush=True)

    # ── as-of IC̄(T-249 的成熟期口径:d' + 30 ≤ as-of 截面日 D)────────────────
    asof = {}
    for g in GROUPS:
        ds = sorted(xsec_date.get((g, m)) for m in sorted({m for (gg, m) in xsec_date if gg == g}))
        ds = [d for d in ds if d]
        if not ds:
            continue
        D = ds[-1]
        asof[g] = {"asof_date": D}
        for p in PG:
            series = ic_series.get((g, p), [])
            hist = [r for r in series
                    if date.fromisoformat(r["date"]) + timedelta(days=30) <= date.fromisoformat(D)][-LOOKBACK_M:]
            stt = monthly_t([r["ic"] for r in hist])
            asof[g][p] = {**stt, "months": [r["month"] for r in hist]}
    print(f"  as-of IC̄: " + "; ".join(f"{g} {asof[g]['asof_date']} " +
                                     " ".join(f"{p}:{asof[g][p]['mean']}(n{asof[g][p]['n']})" for p in PG)
                                     for g in asof), flush=True)

    # ── 汇总 ─────────────────────────────────────────────────────────────────
    months_all = sorted({m for (g, m) in xsec_date})
    last_month = months_all[-1]
    result = {
        "card": "T-255",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "只报不判:支柱截面 IC 分时段 / 分 regime 的稳定性",
        "method": {
            "data_layer": "复用 T-249 的 _cache/t249 原始行(rebuild_cis_v13 / cg_closes / eodhd_closes);不重抓",
            "alpha": "src/data/cis/standard_outcomes.py::outcome_rows 本地重算(30 天相对基准超额)",
            "cross_section": "每月最后一个组内 ≥8 名有数据的交易日;alpha 须已到期(d+30 ≤ last_close)",
            "ic": "组内 Spearman(pillar_x vs alpha),与 T-249::spearman 同一实现",
            "periods": {"p1": "2023-01 → " + P1_LAST, "p2": "2025-01 → " + last_month},
            "regime": "majors cap 风格指数复原水平 vs 自身 200 日均线(as-of ≤ 截面日);读法同 multiplier.py::_majors_gate",
            "null": f"截面内名字↔超额对应打乱 {n_perm} 次(种子 {SEED}):apparatus.shuffle_within + null_distribution + percentile_of",
            "min_cross": MIN_CROSS, "lookback_m": LOOKBACK_M, "n_perm": n_perm, "seed": SEED,
        },
        "universe": {
            "n_assets": len(ASSETS_CONFIG), "crypto": len(crypto_syms), "tradfi": len(tradfi_syms),
            "official_start": official_start, "official_start_from_t249_file": official_start_file,
            "last_close": str(last_close)[:10], "code_ref": CODE_REF,
            "months": months_all, "n_months": len(months_all), "last_month": last_month,
            "n_cross_sections": len(xsec_date),
        },
        "regime_meta": {**regime_meta, "bench_regime_meta": bench_meta},
        "self_check_vs_t249": {"cells": len(repro), "mismatches": len(diffs), "detail": diffs[:20]},
        "full_sample_ic_recomputed": repro,
        "cells": out_cells,
        "sign_flips": flips,
        "sign_flip_counts": {"total": len(flips), "informative": n_inf, "thin_n": n_thin,
                              "mechanical_full_vs_part": n_mech},
        "multiplicity": {"n_cells": n_cells, "bonferroni_alpha": round(bonf, 6),
                         "n_pct_le_0.05": len(sig_lo), "n_pct_ge_0.95": len(sig_hi),
                         "n_survive_bonferroni": len(sig_lo_b) + len(sig_hi_b),
                         "sig_lo": [f"{k}|{c}" for k, c in sig_lo],
                         "sig_hi": [f"{k}|{c}" for k, c in sig_hi]},
        "regime_period_confound": regime_mix,
        "asof_icbar": asof,
        "monthly_ic": {f"{g}|{p}": ic_series[(g, p)] for (g, p) in sorted(ic_series)},
    }
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[8] 写 {args.out}(用时 {time.time() - t0:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
