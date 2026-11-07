#!/usr/bin/env python3
"""T-223 主计算 —— S-696(a) 五因子前向核对(2026-10 信号月)+ 第二族 G1–G6 因子普查。

口径逐字照 docs/research/s691_holdout.sql(留出段)与 s691_factor_zoo_discovery.sql(发现段),
只换日期段;宇宙照 S-689 映射校验(重叠 ≥ 30 日、中位误差 ≤ 0.05);零分布/盈亏不涉及。

只读:全部 SELECT,不做 DDL、不入库。
产出:docs/research/t223_results.json(本脚本)→ 报告由人写。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

URL = os.environ.get("SUPABASE_URL", "").strip()
KEY = os.environ.get("SUPABASE_KEY", "").strip()
if not URL or not KEY:
    sys.exit("SUPABASE_URL / SUPABASE_KEY 未设置 —— 读库需要它们(publishable key 即可)。")
HEAD = {"apikey": KEY, "Authorization": "Bearer " + KEY}
PAGE = 1000

REPO = Path(__file__).resolve().parents[2]
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t223_cache")
T209 = Path("/Volumes/CometCloudAI/cometcloud-local/research/t209_cache")
OUT = REPO / "docs/research/t223_results.json"

# ---------------------------------------------------------------- 口径常量
MCAP_MIN = 20_000_000
MIN_NAMES = 30
MAP_MIN_OVERLAP = 30
MAP_MAX_MED_ERR = 0.05
MIN_VOL_OBS = 25
MIN_TAKER_OBS = 5
FACTORS = ["f01_oi_mcap", "f03_doi30", "f07_taker7", "f08_mom30", "f09_mom7", "f11_vol30"]
FROZEN = {  # 冻结短名单:符号 = 期望方向(留出段确认过的方向)
    "f03_doi30": -1, "f07_taker7": +1, "f08_mom30": -1, "f09_mom7": -1, "f11_vol30": -1,
}
GRID_FROM = "2022-11-01"
GRID_TO = "2026-11-07"
WIN = {
    "discovery": ("2023-01-01", "2024-11-30"),   # 发现段(2024-12 隔离,照 SQL)
    "holdout": ("2025-01-01", "2026-09-26"),    # S-691 留出段,用来验实现
    "forward_card": ("2026-10-01", "2026-10-02"),   # 卡上写的窗口
    "forward_ext": ("2026-10-01", "2026-10-07"),    # 数据现在到 11-06 ⇒ 多到 10-07 的 y 已到期
    "forward_shift": ("2026-09-30", "2026-10-06"),  # S-665 纪律:信号日挪一天
    "forward_sept_tail": ("2026-09-27", "2026-09-30"),  # S-696 的前向起点(9/27 起)
}


# ---------------------------------------------------------------- 取数
def _http(path: str, params: list[tuple[str, str]], rng: str | None = None, timeout=300) -> str:
    url = URL.rstrip("/") + path + "?" + urllib.parse.urlencode(params, safe="(),.*:<>=")
    req = urllib.request.Request(url, headers=HEAD)
    req.add_header("Accept", "text/csv")
    if rng:
        req.add_header("Range", rng)
    last = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode()
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500 or attempt == 5:
                raise
            time.sleep(min(2 ** (attempt + 1), 30))
        except urllib.error.URLError as e:
            last = e
            if attempt == 5:
                raise
            time.sleep(min(2 ** (attempt + 1), 30))
    raise RuntimeError(f"unreachable: {last}")


def _count(path: str, params: list[tuple[str, str]]) -> int:
    req = urllib.request.Request(URL.rstrip("/") + path + "?" + urllib.parse.urlencode(params, safe="(),.*:<>="),
                                 headers={**HEAD, "Prefer": "count=exact", "Range": "0-0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        cr = r.headers.get("Content-Range", "")
    tail = cr.split("/")[-1] if "/" in cr else ""
    return int(tail) if tail.isdigit() else -1


def pull(path: str, params: list[tuple[str, str]], order: str, tag: str) -> pd.DataFrame:
    """带 order= 主键排序,分页 1000 行,落 CSV 缓存。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    csv_p = CACHE / f"{tag}.csv"
    meta_p = CACHE / f"{tag}.meta.json"
    want = {"path": path, "params": [list(p) for p in params], "order": order}
    if csv_p.exists() and meta_p.exists():
        try:
            got = json.loads(meta_p.read_text())
            if got.get("want") == want and csv_p.stat().st_size > 0:
                print(f"[cache] {tag} <- {csv_p}", flush=True)
                return pd.read_csv(csv_p, dtype=str)
        except Exception:
            pass
    ordered = list(params) + [("order", order)]
    total = _count(path, ordered)
    if total < 0:
        sys.exit(f"{tag}: 服务端计数失败")
    ranges = [(i, min(i + PAGE - 1, total - 1)) for i in range(0, total, PAGE)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        bodies = list(ex.map(lambda r: _http(path, ordered, rng=f"{r[0]}-{r[1]}"), ranges))
    header = bodies[0].splitlines()[0] if bodies else ""
    n = 0
    with csv_p.open("w") as f:
        f.write(header + "\n")
        for b in bodies:
            for line in b.splitlines()[1:]:
                if line.strip():
                    f.write(line + "\n")
                    n += 1
    meta_p.write_text(json.dumps({"want": want, "rows": n, "total": total,
                                  "pulled_at": datetime.now(timezone.utc).isoformat()}))
    if n != total:
        sys.exit(f"{tag}: 拉回 {n} 行 != 服务端计数 {total} —— 分页有缺口,拒绝出结果")
    print(f"[pull ] {tag}: {n} rows -> {csv_p}", flush=True)
    return pd.read_csv(csv_p, dtype=str)


def d2ord(s: str) -> int:
    y, m, d = (int(x) for x in str(s)[:10].split("-"))
    return date(y, m, d).toordinal()


def ord2d(o: int) -> str:
    return date.fromordinal(o).isoformat()


# ---------------------------------------------------------------- 载入
def load_all() -> dict:
    print("[load ] 读 2022-11-25 → 2026-10 的历史缓存 + 拉新鲜尾巴", flush=True)
    deriv = pd.read_csv(T209 / "deriv_metrics_daily.csv", dtype=str)
    am = pd.read_csv(T209 / "asset_mcap_daily.csv", dtype=str)
    cg = pd.read_csv(T209 / "cg_coin_mcap_daily.csv", dtype=str)
    maps = pd.read_csv(T209 / "perp_cg_map.csv", dtype=str)

    deriv_f = pull("/rest/v1/deriv_metrics_daily",
                   [("select", "symbol,d,oi_close,oi_value_close,taker_ratio_mean"),
                    ("d", "gte.2026-10-20"), ("d", "lte.2026-11-07")],
                   "symbol.asc,d.asc", "deriv_tail")
    am_f = pull("/rest/v1/asset_mcap_daily",
                [("select", "symbol,coin_id,d,price,mcap"), ("source", "eq.coingecko_pro_market_chart"),
                 ("d", "gte.2026-10-27"), ("d", "lte.2026-11-07")],
                "symbol.asc,d.asc", "am_tail")
    cg_f = pull("/rest/v1/cg_coin_mcap_daily",
                [("select", "coin_id,d,price,mcap"), ("d", "gte.2026-10-27"), ("d", "lte.2026-11-07")],
                "coin_id.asc,d.asc", "cg_tail")
    deriv = pd.concat([deriv, deriv_f], ignore_index=True)
    am = pd.concat([am, am_f], ignore_index=True)
    cg = pd.concat([cg, cg_f], ignore_index=True)
    for df in (deriv, am, cg):
        df.drop_duplicates(subset=[c for c in ("symbol", "d", "coin_id") if c in df.columns],
                           inplace=True, ignore_index=True)
    print(f"[load ] deriv {len(deriv)} / am {len(am)} / cg {len(cg)} / map {len(maps)}", flush=True)
    return {"deriv": deriv, "am": am, "cg": cg, "maps": maps}


# ---------------------------------------------------------------- 宇宙
def build_universe(data: dict) -> dict:
    deriv, am, cg, maps = data["deriv"], data["am"], data["cg"], data["maps"]
    name_set = set(deriv["symbol"].astype(str))
    am_syms = set(am["symbol"].astype(str).str.upper())

    px: dict[str, dict[int, tuple[float, float, float]]] = {}
    for r in am.itertuples(index=False):
        sym = str(r.symbol).upper()
        if sym not in name_set:
            continue
        try:
            p, m = float(r.price), float(r.mcap)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(p) and p > 0):
            continue
        px.setdefault(sym, {})[d2ord(r.d)] = (p, m, 1.0)

    cg_by_id: dict[str, dict[int, tuple[float, float]]] = {}
    for r in cg.itertuples(index=False):
        try:
            p, m = float(r.price), float(r.mcap)
        except (TypeError, ValueError):
            continue
        cg_by_id.setdefault(str(r.coin_id), {})[d2ord(r.d)] = (p, m)

    mapped: dict[str, tuple[str, float]] = {}
    for r in maps.itertuples(index=False):
        if str(r.verdict) != "resolved":
            continue
        sym = str(r.symbol).upper()
        if sym not in name_set or sym in am_syms:
            continue
        mult = float(r.mult) if str(r.mult) not in ("", "nan", "None") else 1.0
        mapped[sym] = (str(r.coin_id), mult)
    for sym, (cid, mult) in mapped.items():
        for d, (p, m) in cg_by_id.get(cid, {}).items():
            if math.isfinite(p) and p > 0:
                px.setdefault(sym, {})[d] = (p, m, mult)
    print(f"[map  ] deriv 名字 {len(name_set)} / 有价 {len(px)} / 映射补数 {len(mapped)}", flush=True)

    oi: dict[str, dict[int, dict]] = {}
    for r in deriv.itertuples(index=False):
        def f(x):
            try:
                v = float(x)
            except (TypeError, ValueError):
                return None
            return v if math.isfinite(v) else None
        oi.setdefault(str(r.symbol).upper(), {})[d2ord(r.d)] = {
            "oi_close": f(r.oi_close), "oi_value": f(r.oi_value_close), "taker": f(r.taker_ratio_mean)}

    # S-689 / S-691 映射校验:d ≥ 2023-01-01,重叠 ≥ 30 日、中位误差 ≤ 0.05
    def mapcheck(lo, hi):
        detail = {}
        for sym, series in oi.items():
            if sym not in px:
                continue
            errs = []
            for d, rec in series.items():
                if d < lo or d > hi:
                    continue
                if rec["oi_close"] is None or rec["oi_value"] is None:
                    continue
                if rec["oi_close"] <= 0 or rec["oi_value"] <= 0:
                    continue
                p = px[sym].get(d)
                if p is None:
                    continue
                implied = rec["oi_value"] / rec["oi_close"]
                errs.append(abs(p[0] * p[2] / implied - 1.0))
            if errs:
                detail[sym] = {"overlap_days": len(errs), "median_err": float(np.median(errs))}
        kept = {s for s, v in detail.items()
                if v["overlap_days"] >= MAP_MIN_OVERLAP and v["median_err"] <= MAP_MAX_MED_ERR}
        return kept, detail

    lo = d2ord("2023-01-01")
    hi_now = d2ord(GRID_TO)
    hi_snap = d2ord("2026-10-26")   # S-691 留出段开封时的数据快照
    kept_now, detail_now = mapcheck(lo, hi_now)
    kept_snap, detail_snap = mapcheck(lo, hi_snap)
    kept_t209, _ = mapcheck(d2ord("2023-01-02"), d2ord("2026-10-19"))
    print(f"[map  ] 校验窗口对比:现在 {len(kept_now)}/{len(detail_now)} 名;"
          f"截到 10-26(留出段快照) {len(kept_snap)}/{len(detail_snap)} 名;"
          f"T-209 窗口 {len(kept_t209)} 名", flush=True)
    print(f"[map  ] 快照版比现在版少 {sorted(kept_now - kept_snap)};"
          f"多 {sorted(kept_snap - kept_now)}", flush=True)
    kept = kept_snap  # 主口径 = 留出段开封时的宇宙(前向核对要与留出段同一个宇宙)
    print(f"[map  ] 采用快照宇宙 {len(kept)} 名(敏感性:现在版 {len(kept_now)} 名)", flush=True)
    return {"px": px, "oi": oi, "kept": sorted(kept), "map_detail": detail_snap, "mapped": mapped,
            "kept_now": sorted(kept_now)}


# ---------------------------------------------------------------- 面板
def build_panel(uni: dict) -> dict:
    lo, hi = d2ord(GRID_FROM), d2ord(GRID_TO)
    grid = np.arange(lo, hi + 1)
    gidx = {d: i for i, d in enumerate(grid)}
    idx = pd.DatetimeIndex([pd.Timestamp(ord2d(d)) for d in grid])
    names = uni["kept"]
    n, T = len(names), len(grid)

    price = np.full((n, T), np.nan)
    mcap = np.full((n, T), np.nan)
    oi_close = np.full((n, T), np.nan)
    oi_value = np.full((n, T), np.nan)
    taker = np.full((n, T), np.nan)

    for i, sym in enumerate(names):
        for d, (p, m, _mu) in uni["px"].get(sym, {}).items():
            j = gidx.get(d)
            if j is not None:
                price[i, j] = p
                mcap[i, j] = m
        for d, rec in uni["oi"].get(sym, {}).items():
            j = gidx.get(d)
            if j is None:
                continue
            oi_close[i, j] = rec["oi_close"] if rec["oi_close"] is not None else np.nan
            oi_value[i, j] = rec["oi_value"] if rec["oi_value"] is not None else np.nan
            taker[i, j] = rec["taker"] if rec["taker"] is not None else np.nan

    btc = np.full(T, np.nan)
    # BTC:asset_mcap_daily 里 coin_id='bitcoin'(S-691 的 btc 子句)—— add_btc 里填
    return {"grid": grid, "gidx": gidx, "idx": idx, "names": names, "price": price, "mcap": mcap,
            "oi_close": oi_close, "oi_value": oi_value, "taker": taker, "btc": btc}


def add_btc(panel: dict, data: dict) -> None:
    am = data["am"]
    btc = panel["btc"]
    gidx = panel["gidx"]
    sub = am[am["coin_id"].astype(str) == "bitcoin"]
    for r in sub.itertuples(index=False):
        j = gidx.get(d2ord(r.d))
        if j is None:
            continue
        try:
            p = float(r.price)
        except (TypeError, ValueError):
            continue
        if math.isfinite(p) and p > 0:
            btc[j] = p


def compute_factors(panel: dict) -> dict:
    price, mcap = panel["price"], panel["mcap"]
    btc = panel["btc"]
    idx = panel["idx"]
    n, T = price.shape

    def shift(arr, k):
        """向后看 k 天(用 j−k 的值),照 SQL 的 left join x.d = x.d − k。"""
        out = np.full_like(arr, np.nan, dtype=float)
        if arr.ndim == 1:
            if k > 0:
                out[k:] = arr[:-k]
        elif k > 0:
            out[:, k:] = arr[:, :-k]
        return out

    def shift_fwd(arr, k):
        """向前看 k 天(用 j+k 的值),照 SQL 的 join x30f.d = x.d + k。"""
        out = np.full_like(arr, np.nan, dtype=float)
        if arr.ndim == 1:
            if k > 0:
                out[:-k] = arr[k:]
        elif k > 0:
            out[:, :-k] = arr[:, k:]
        return out

    with np.errstate(invalid="ignore", divide="ignore"):
        prev = np.concatenate([np.full((n, 1), np.nan), price[:, :-1]], axis=1)
        lr = np.where((price > 0) & (prev > 0), np.log(price / prev), np.nan)
        ret30 = np.where((price > 0) & (shift(price, 30) > 0), price / shift(price, 30) - 1.0, np.nan)
        btc30 = np.where((btc > 0) & (shift(btc, 30) > 0), btc / shift(btc, 30) - 1.0, np.nan)
        ret7 = np.where((price > 0) & (shift(price, 7) > 0), price / shift(price, 7) - 1.0, np.nan)
        btc7 = np.where((btc > 0) & (shift(btc, 7) > 0), btc / shift(btc, 7) - 1.0, np.nan)
        oi30 = shift(panel["oi_close"], 30)
        f03 = np.where((panel["oi_close"] > 0) & (oi30 > 0), np.log(panel["oi_close"] / oi30), np.nan)
        f01 = np.where(panel["oi_value"] > 0, panel["oi_value"] / mcap, np.nan)
        f08 = ret30 - btc30
        f09 = ret7 - btc7
        # y = 之后 30 天的收益 − BTC 之后 30 天的收益(S-691 的 join x30f.d = x.d + 30)
        px30f = shift_fwd(price, 30)
        btc30f = shift_fwd(btc, 30)
        y = np.where((px30f > 0) & (price > 0) & (btc30f > 0) & (btc > 0),
                     (px30f / price - 1.0) - (btc30f / btc - 1.0), np.nan)

    # f07:7 个日历日的 taker 均(照 SQL 的 '6 days preceding' → 7 天窗口),≥ 5 个观测
    f07 = np.full((n, T), np.nan)
    s = pd.DataFrame(panel["taker"].T, index=idx)
    mean7 = s.rolling("7D", min_periods=1).mean().to_numpy().T
    cnt7 = s.rolling("7D", min_periods=1).count().to_numpy().T
    f07 = np.where(cnt7 >= MIN_TAKER_OBS, mean7, np.nan)

    # f11:30 个日历日的日收益样本标准差,≥ 25 个观测
    f11 = np.full((n, T), np.nan)
    s2 = pd.DataFrame(lr.T, index=idx)
    std30 = s2.rolling("30D", min_periods=1).std(ddof=1).to_numpy().T
    cnt30 = s2.rolling("30D", min_periods=1).count().to_numpy().T
    f11 = np.where(cnt30 >= MIN_VOL_OBS, std30, np.nan)

    panel.update({"f01_oi_mcap": f01, "f03_doi30": f03, "f07_taker7": f07, "f08_mom30": f08,
                  "f09_mom7": f09, "f11_vol30": f11, "y": y})
    return panel


# ---------------------------------------------------------------- 每日偏 IC
def _rank(a: np.ndarray) -> np.ndarray:
    return pd.Series(a).rank(method="average").to_numpy()


def _partial(v: np.ndarray, yv: np.ndarray, s: np.ndarray) -> float:
    rv, ry, rs = _rank(v), _rank(yv), _rank(s)
    r_vy = np.corrcoef(rv, ry)[0, 1]
    r_vs = np.corrcoef(rv, rs)[0, 1]
    r_ys = np.corrcoef(ry, rs)[0, 1]
    if not all(np.isfinite([r_vy, r_vs, r_ys])) or abs(r_vs) >= 1 or abs(r_ys) >= 1:
        return np.nan
    return float((r_vy - r_vs * r_ys) / np.sqrt((1 - r_vs * r_vs) * (1 - r_ys * r_ys)))


def _pct_rank(a: np.ndarray) -> np.ndarray:
    return pd.Series(a).rank(method="average").to_numpy() / len(a)


def daily_ic(panel: dict) -> pd.DataFrame:
    grid, gidx = panel["grid"], panel["gidx"]
    y, mcap = panel["y"], panel["mcap"]
    oi_value = panel["oi_value"]
    fac = {f: panel[f] for f in FACTORS}
    size = np.where(mcap > 0, np.log(mcap), np.nan)
    has_oi = oi_value > 0
    mcap_ok = mcap >= MCAP_MIN

    rows = []
    for d in grid:
        j = gidx[d]
        yv = y[:, j]
        ok_y = np.isfinite(yv) & mcap_ok[:, j]
        if ok_y.sum() < MIN_NAMES:
            continue
        for reading in ("main", "literal"):
            base = ok_y & (has_oi[:, j] if reading == "main" else True)
            for f in FACTORS:
                v = fac[f][:, j]
                sel = base & np.isfinite(v)
                if sel.sum() < MIN_NAMES:
                    continue
                ic = _partial(v[sel], yv[sel], size[sel, j])
                if np.isfinite(ic):
                    rows.append({"d": ord2d(d), "reading": reading, "factor": f,
                                 "n": int(sel.sum()), "ic": ic})
    return pd.DataFrame(rows)


def comp_ic(panel: dict) -> pd.DataFrame:
    """合成的偏 IC(只报不判):comp5 = 五因子 percent_rank 的平均,再对 y 求偏 Spearman。"""
    grid, gidx = panel["grid"], panel["gidx"]
    y, mcap, size = panel["y"], panel["mcap"], None
    size = np.where(mcap > 0, np.log(mcap), np.nan)
    mcap_ok = mcap >= MCAP_MIN
    rows = []
    for d in grid:
        j = gidx[d]
        yv = y[:, j]
        allf = np.ones(len(yv), dtype=bool)
        for f in FROZEN:
            allf &= np.isfinite(panel[f][:, j])
        sel = allf & np.isfinite(yv) & mcap_ok[:, j]
        if sel.sum() < MIN_NAMES:
            continue
        idxs = np.where(sel)[0]
        cs = np.zeros(len(idxs))
        for f, sgn in FROZEN.items():
            cs += _pct_rank(panel[f][idxs, j] * sgn)
        cs /= len(FROZEN)
        ic = _partial(cs, yv[idxs], size[idxs, j])
        if np.isfinite(ic):
            rows.append({"d": ord2d(d), "ic": ic, "n": int(sel.sum())})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 汇总
def monthly_summary(daily: pd.DataFrame, d0: str, d1: str) -> dict:
    sub = daily[(daily["d"] >= d0) & (daily["d"] <= d1)].copy()
    if sub.empty:
        return {}
    sub["m"] = sub["d"].str[:7]
    out = {}
    for (reading, factor), g in sub.groupby(["reading", "factor"]):
        mon = g.groupby("m")["ic"].mean()
        n_m = len(mon)
        mean_ic = float(mon.mean())
        sd = float(mon.std(ddof=1)) if n_m > 1 else float("nan")
        t = mean_ic / sd * np.sqrt(n_m) if n_m > 1 and sd > 0 else float("nan")
        out[f"{reading}|{factor}"] = {
            "n_days": int(len(g)), "n_months": n_m, "mean_names": float(g["n"].mean()),
            "mean_ic": mean_ic, "t_month": t,
            "pos_months": int((mon > 0).sum()), "neg_months": int((mon < 0).sum()),
            "months": {m: float(v) for m, v in mon.items()},
        }
    return out


def main() -> None:
    data = load_all()
    uni = build_universe(data)
    panel = build_panel(uni)
    add_btc(panel, data)
    btc_idx = np.where(np.isfinite(panel["btc"]))[0]
    print(f"[btc  ] BTC 价 {len(btc_idx)} 天 "
          f"({ord2d(int(panel['grid'][btc_idx[0]]))} → {ord2d(int(panel['grid'][btc_idx[-1]]))})", flush=True)
    compute_factors(panel)
    daily = daily_ic(panel)
    daily.to_csv(REPO / "docs/research/t223_daily_ic.csv", index=False)
    comp = comp_ic(panel)
    comp.to_csv(REPO / "docs/research/t223_comp_ic.csv", index=False)

    res = {
        "card": "T-223",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "grid": [GRID_FROM, GRID_TO],
        "universe": {
            "deriv_names": len(set(data["deriv"]["symbol"])),
            "names_with_price": len(uni["px"]),
            "map_checked": len(uni["map_detail"]),
            "kept": len(uni["kept"]),
            "perp_mapped": len(uni["mapped"]),
            "map_rule": f"d ≥ 2023-01-01,重叠 ≥ {MAP_MIN_OVERLAP} 日,中位误差 ≤ {MAP_MAX_MED_ERR}",
        },
        "windows": {},
    }
    for tag, (a, b) in WIN.items():
        res["windows"][tag] = {"from": a, "to": b, "factors": monthly_summary(daily, a, b)}
        if not comp.empty:
            c = comp[(comp["d"] >= a) & (comp["d"] <= b)]
            if len(c):
                mon = c.groupby(c["d"].str[:7])["ic"].mean()
                res["windows"][tag]["comp"] = {
                    "n_days": int(len(c)), "n_months": int(len(mon)),
                    "mean_ic": float(mon.mean()),
                    "t_month": float(mon.mean() / mon.std(ddof=1) * np.sqrt(len(mon))) if len(mon) > 1 else float("nan"),
                    "pos_months": int((mon > 0).sum()),
                    "months": {m: float(v) for m, v in mon.items()},
                }
    # 逐日 IC(前向段)留档
    fwd = daily[(daily["d"] >= "2026-09-20") & (daily["d"] <= "2026-10-07")]
    res["forward_daily"] = fwd.to_dict(orient="records")

    # 市场层:每天的宇宙均值 y(字面口径:不要求 OI)与 BTC 的 30 天收益 —— G5 的时间序列目标
    mrows = []
    y, mcap = panel["y"], panel["mcap"]
    grid, gidx = panel["grid"], panel["gidx"]
    prev_btc = np.concatenate([[np.nan], panel["btc"][:-1]])
    btc_fwd30 = np.full_like(panel["btc"], np.nan)
    btc_fwd30[:-30] = panel["btc"][30:]
    btc_ret30 = np.where((btc_fwd30 > 0) & (panel["btc"] > 0), btc_fwd30 / panel["btc"] - 1.0, np.nan)
    for d in grid:
        j = gidx[d]
        sel = np.isfinite(y[:, j]) & (mcap[:, j] >= MCAP_MIN)
        if sel.sum() < MIN_NAMES:
            continue
        mrows.append({"d": ord2d(d), "n": int(sel.sum()),
                      "uni_mean_y": float(np.nanmean(y[sel, j])), "btc_ret30": float(btc_ret30[j])})
    mdf = pd.DataFrame(mrows)
    mdf["m"] = mdf["d"].str[:7]
    mon = mdf.groupby("m").agg(n_days=("d", "size"), uni_mean_y=("uni_mean_y", "mean"),
                                btc_ret30=("btc_ret30", "mean")).reset_index()
    res["market_monthly"] = mon.to_dict(orient="records")
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"[out  ] {OUT}", flush=True)
    for tag in ("holdout", "forward_card", "forward_ext", "forward_shift"):
        w = res["windows"][tag]["factors"]
        print(f"-- {tag}: " + " | ".join(
            f"{k.split('|')[1][:3]}:{k.split('|')[0][:3]} ic={v['mean_ic']:+.4f} "
            f"days={v['n_days']} n={v['mean_names']:.0f}" for k, v in sorted(w.items())), flush=True)


if __name__ == "__main__":
    main()
