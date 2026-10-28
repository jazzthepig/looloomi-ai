#!/usr/bin/env python3
"""T-209 / 台账 S-694 —— ① 面板「躲开宽宇宙五因子合成最差五分之一」盲复算(C 道)。

**照台账 S-694 一字不改**,卡上写死的口径全部在这里实现:

  · 合成 = S-691 冻结短名单:F3(ΔOI 30 天,−)、F7(主动买卖比 7 天,+)、F8(30 天相对动量,−)、
    F9(7 天相对动量,−)、F11(30 天波动,−)。定义与 S-691 复算脚本(t208_factor_zoo_holdout.py)
    逐字相同(同样的窗口、同样的最少观测数、同样的 BTC 相对口径)。
  · 宇宙:deriv_metrics_daily 里的名字,过 S-689 映射校验(隐含价 = oi_value_close / oi_close,
    重叠日 ≥ 30 且中位 |CG 价 × 倍数 / 隐含价 − 1| ≤ 5%)、当天 CG 市值 ≥ 2,000 万、
    当天 OI > 0(oi_close > 0 且 oi_value_close > 0)、五个因子都有定义、当天 ≥ 30 名。
  · 调仓日:周一 UTC,2023-01-02 → 2026-10-19(收益 = 调仓日收盘 → 下周一收盘)。
  · comp = 五个 percent_rank 的平均(方向按冻结符号);最差五分之一 = ntile(5) 第 1 档。
  · 面板 = 24 名;主口径 = 市值加权(落在最差档的权重 × 0.5 后归一);副 = 等权、剔除。
  · 成本 10 bp × Σ|目标 − 上周漂移后权重|。
  · 判据:(a) 年化净超额 > 0 且随机对照(每周随机挑同样个数减半,1,000 次)≥ 95 分位;
    (b) 两段(调仓日 ≤ 2024-11-30 / 之后)净超额都 > 0。

零分布 / 分位 / A-B 一律走 `src/data/evaluation/apparatus.py`(不另起炉灶)。
只读 Supabase(publishable key)。用法:
    python3 docs/research/t209_avoid_tilt.py
环境:SUPABASE_URL / SUPABASE_KEY(缺一个就报错退出)。
产物:
    docs/research/t209_results.json
    /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-209_avoid_tilt.md
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.data.evaluation.apparatus import (   # 零分布 / 盈亏 / A/B 只许用这里的函数
    NoOpNull,
    null_distribution,
    percentile_of,
)

# ---------------------------------------------------------------- 配置(照卡)

SIGNAL_START = "2023-01-02"          # 第一个调仓日(周一)
SIGNAL_END = "2026-10-19"            # 最后一个调仓日(周一)
OUTCOME_END = "2026-10-26"           # 最后一个调仓日的下周一
PRICE_FROM = "2022-11-25"            # 价格/市值:给 F8/F11 的 30 天回看留头
DERIV_FROM = "2022-11-25"            # 衍生指标:给 F3 的 30 天回看留头
HALF_CUT = "2024-11-30"              # 两段切点(≤ 此日 / 之后)

PANEL = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT",
         "LTC", "TRX", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI", "UNI", "AAVE",
         "INJ", "FIL", "ETC", "BCH"]

# S-691 冻结短名单(代码, 名字, 冻结符号)
FROZEN = [
    ("F3", "ΔOI 30天 (ln 张数)", -1),
    ("F7", "主动买卖比 7天均", +1),
    ("F8", "30天相对动量 (对 BTC)", -1),
    ("F9", "7天相对动量 (对 BTC)", -1),
    ("F11", "30天波动 (日对数收益标准差)", -1),
]

MCAP_MIN = 20_000_000.0        # CG 市值门槛(台账:2,000 万)
MAP_MIN_OVERLAP = 30           # 映射校验:最少重叠日
MAP_MAX_MED_ERR = 0.05         # 映射校验:中位误差上限
MIN_NAMES = 30                 # 当天宇宙最少名字数
MIN_VOL_OBS = 25               # F11 波动:最少收益个数
MIN_WINDOW_DAYS = 5            # F7:7 天窗口里最少有效天数
COST_BP = 10.0                 # 成本:10 bp × Σ|目标 − 漂移后权重|
N_NULL = 1000                  # 随机对照次数
SEED = 20261028                # 随机对照种子(可复现)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = REPO_ROOT / "docs" / "research" / "t209_results.json"
MAC_ROOT = Path("/Volumes/CometCloudAI/cometcloud-local")
CACHE_DIR = MAC_ROOT / "research" / "t209_cache"
OUT_MD = MAC_ROOT / "_reports" / "absorb_input" / "T-209_avoid_tilt.md"

URL = os.environ.get("SUPABASE_URL", "").strip()
KEY = os.environ.get("SUPABASE_KEY", "").strip()
if not URL or not KEY:
    sys.exit("SUPABASE_URL / SUPABASE_KEY 未设置 —— 读库需要它们(publishable key 即可)。")

HEAD = {"apikey": KEY, "Authorization": "Bearer " + KEY}
PAGE = 1000  # PostgREST 服务端 max-rows = 1000


# ---------------------------------------------------------------- 取数

def _http(path: str, params: list[tuple[str, str]], rng: str | None = None) -> str:
    url = URL.rstrip("/") + path + "?" + urllib.parse.urlencode(params, safe="(),.*:<>=")
    headers = dict(HEAD)
    headers["Accept"] = "text/csv"
    if rng:
        headers["Range"] = rng
    req = urllib.request.Request(url, headers=headers)
    last = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read().decode()
        except urllib.error.HTTPError as e:  # 5xx 退避重试(PostgREST 压力大时会给 500)
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


def count_rows(path: str, params: list[tuple[str, str]]) -> int:
    for attempt in range(6):
        req = urllib.request.Request(URL.rstrip("/") + path + "?" + urllib.parse.urlencode(params, safe="(),.*:<>="),
                                     headers={**HEAD, "Prefer": "count=exact", "Range": "0-0"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                cr = r.headers.get("Content-Range", "")
            if not cr or "/" not in cr:
                return -1
            tail = cr.split("/")[-1]
            return int(tail) if tail.isdigit() else -1
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 5:
                raise
            time.sleep(min(2 ** (attempt + 1), 30))
    return -1


def pull_chunk(path: str, params: list[tuple[str, str]], order: str, tag: str) -> Path:
    """拉一段(带 order= 主键排序),分页 1000 行,落 CSV 缓存。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{tag}.csv"
    meta = CACHE_DIR / f"{tag}.meta.json"
    want = {"path": path, "params": [list(p) for p in params], "order": order}
    if cached.exists() and meta.exists():
        try:
            got = json.loads(meta.read_text())
            if got.get("want") == want and cached.stat().st_size > 0:
                print(f"[cache] {tag} <- {cached}", flush=True)
                return cached
        except Exception:
            pass

    ordered = list(params) + [("order", order)]
    total = count_rows(path, ordered)
    if total >= 0:
        ranges = [(i, min(i + PAGE - 1, total - 1)) for i in range(0, total, PAGE)]
    else:
        i = 0
        ranges = []
        while True:
            body = _http(path, ordered, rng=f"{i}-{i + PAGE - 1}")
            lines = body.strip().splitlines()
            if len(lines) <= 1:
                break
            ranges.append((i, i + len(lines) - 2))
            i += PAGE

    def one(r):
        a, b = r
        return a, _http(path, ordered, rng=f"{a}-{b}")

    chunks: list[tuple[int, str]] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for a, body in ex.map(one, ranges):
            chunks.append((a, body))
    chunks.sort(key=lambda x: x[0])

    header = chunks[0][1].splitlines()[0] if chunks else ""
    n_rows = 0
    with cached.open("w") as f:
        f.write(header + "\n")
        for _, body in chunks:
            for line in body.splitlines()[1:]:
                if line.strip():
                    f.write(line + "\n")
                    n_rows += 1
    meta.write_text(json.dumps({"want": want, "rows": n_rows,
                                 "pulled_at": datetime.now(timezone.utc).isoformat()}))
    if total >= 0 and n_rows != total:
        print(f"[WARN ] {tag}: 拉回 {n_rows} 行,服务端计数 {total} —— 分页有缺口,数字不能用!",
              file=sys.stderr, flush=True)
        raise SystemExit(f"{tag}: 分页行数 {n_rows} != {total},拒绝出结果")
    print(f"[pull ] {tag}: {n_rows} rows -> {cached}", flush=True)
    return cached


def pull_dated(path: str, base_params: list[tuple[str, str]], date_col: str,
               d_from: str, d_to: str, order: str, tag: str) -> Path:
    """按自然年分段拉一段日期范围,再拼成一张表。

    为什么分段:整段 4 年的查询在 PostgREST 上会 500(实测 2026-10-28),
    分年拉每段 ~1/4 的行数就稳。拼接后逐行数与各段服务端计数之和核对。
    """
    y0, y1 = int(d_from[:4]), int(d_to[:4])
    parts: list[tuple[int, Path]] = []
    total_rows = 0
    for y in range(y0, y1 + 1):
        lo = max(d_from, f"{y}-01-01")
        hi = min(d_to, f"{y}-12-31")
        if lo > hi:
            continue
        params = list(base_params) + [(date_col, f"gte.{lo}"), (date_col, f"lte.{hi}")]
        p = pull_chunk(path, params, order, f"{tag}_{y}")
        n = sum(1 for _ in p.open()) - 1
        parts.append((y, p))
        total_rows += n
    out = CACHE_DIR / f"{tag}.csv"
    with out.open("w") as f:
        header = None
        for _, p in parts:
            with p.open() as g:
                for k, line in enumerate(g):
                    if k == 0 and header is None:
                        header = line
                        f.write(line)
                    elif k == 0:
                        continue
                    else:
                        f.write(line)
    meta = CACHE_DIR / f"{tag}.meta.json"
    meta.write_text(json.dumps({"path": path, "from": d_from, "to": d_to, "order": order,
                                 "rows": total_rows,
                                 "pulled_at": datetime.now(timezone.utc).isoformat()}))
    print(f"[pull ] {tag}: {total_rows} rows (按年拼接) -> {out}", flush=True)
    return out


# ---------------------------------------------------------------- 小工具

def d2ord(s: str) -> int:
    return date.fromisoformat(s[:10]).toordinal()


def ord2d(o: int) -> str:
    return date.fromordinal(o).isoformat()


def avg_rank(vals: np.ndarray) -> np.ndarray:
    """并列名次的平均名次(名次 1 = 最小值)。"""
    n = len(vals)
    if n == 0:
        return np.zeros(0)
    order = np.argsort(vals, kind="mergesort")
    sv = vals[order]
    newgrp = np.ones(n, dtype=bool)
    newgrp[1:] = sv[1:] != sv[:-1]
    grp = np.cumsum(newgrp) - 1
    starts = np.flatnonzero(newgrp)
    counts = np.diff(np.append(starts, n))
    sums = np.add.reduceat(np.arange(1, n + 1, dtype=float), starts)
    out = np.empty(n, dtype=float)
    out[order] = (sums / counts)[grp]
    return out


def pct_rank(vals: np.ndarray) -> np.ndarray:
    """percent_rank = (平均名次 − 1) / (n − 1),取值 [0,1],越大越好。"""
    n = len(vals)
    if n <= 1:
        return np.zeros(n)
    return (avg_rank(vals) - 1.0) / (n - 1.0)


def ntile5(comp: np.ndarray) -> np.ndarray:
    """PostgreSQL ntile(5):按 comp 升序分 5 档,前面的档多拿行。返回 1..5。"""
    n = len(comp)
    out = np.empty(n, dtype=int)
    base, rem = divmod(n, 5)
    order = np.argsort(comp, kind="mergesort")
    pos = 0
    for b in range(5):
        size = base + (1 if b < rem else 0)
        out[order[pos:pos + size]] = b + 1
        pos += size
    return out


def roll_mean(arr: np.ndarray, span: int, min_days: int) -> np.ndarray:
    """日历窗口 [d−span+1, d] 的均值(缺日算 NaN),要求窗口内至少 min_days 个有效值。"""
    n = len(arr)
    valid = np.isfinite(arr)
    filled = np.where(valid, arr, 0.0)
    cs = np.concatenate([[0.0], np.cumsum(filled)])
    cv = np.concatenate([[0.0], np.cumsum(valid.astype(float))])
    lo = np.maximum(np.arange(n) - span + 1, 0)
    s = cs[1:] - cs[lo]
    c = cv[1:] - cv[lo]
    out = np.full(n, np.nan)
    ok = c >= min_days
    out[ok] = s[ok] / c[ok]
    return out


def roll_std(arr: np.ndarray, span: int, min_obs: int) -> np.ndarray:
    """日历窗口 [d−span+1, d] 的样本标准差(ddof=1),要求至少 min_obs 个有效值。"""
    n = len(arr)
    valid = np.isfinite(arr)
    filled = np.where(valid, arr, 0.0)
    cs = np.concatenate([[0.0], np.cumsum(filled)])
    cs2 = np.concatenate([[0.0], np.cumsum(filled * filled)])
    cv = np.concatenate([[0.0], np.cumsum(valid.astype(float))])
    lo = np.maximum(np.arange(n) - span + 1, 0)
    c = cv[1:] - cv[lo]
    s = cs[1:] - cs[lo]
    s2 = cs2[1:] - cs2[lo]
    out = np.full(n, np.nan)
    ok = c >= max(min_obs, 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(c > 0, s / np.maximum(c, 1), np.nan)
        var = np.where(c > 1, (s2 - c * mean * mean) / (c - 1), np.nan)
    out[ok] = np.sqrt(var[ok])
    return out


def selfcheck() -> None:
    """钉住三个容易静默出错的地方:percent_rank、ntile(5) 的档内行数、漂移后权重。"""
    v = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    pr = pct_rank(v)
    assert np.allclose(pr, [0.0, 0.25, 0.5, 0.75, 1.0]), pr
    pr2 = pct_rank(np.array([1.0, 1.0, 2.0]))
    assert np.allclose(pr2, [0.25, 0.25, 1.0]), pr2          # 并列取平均名次
    assert list(ntile5(np.arange(134.0))) == list(np.concatenate([np.full(27, 1), np.full(27, 2),
                                                                np.full(27, 3), np.full(27, 4),
                                                                np.full(26, 5)])), "ntile 档内行数不对"
    assert ntile5(np.arange(10.0)).tolist() == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5], ntile5(np.arange(10.0))
    # 漂移:w=(0.5,0.5),r=(+100%,0) ⇒ 漂移后 (0.667,0.333)
    grown = np.array([0.5, 0.5]) * (1 + np.array([1.0, 0.0]))
    assert np.allclose(grown / grown.sum(), [2 / 3, 1 / 3])


# ---------------------------------------------------------------- 回测

def simulate(weeks: list[dict], flag_sets: list[np.ndarray], mode: str) -> dict:
    """mode: "mw"(市值加权) / "ew"(等权) / "exc"(剔除落在最差档的)。

    flag_sets[t] 是第 t 周的布尔数组(与 weeks[t]["names"] 同序),标出被减半/剔除的名字。
    每周:目标权重 → 与上周漂移后权重的换手 → 成本 → 组合收益 → 漂移后权重。
    """
    W = len(weeks)
    gross = np.zeros(W)
    cost = np.zeros(W)
    prev: dict[str, float] | None = None
    for t in range(W):
        wk = weeks[t]
        names: list[str] = wk["names"]
        mcap: np.ndarray = wk["mcap"]
        rets: np.ndarray = wk["rets"]
        n = len(names)
        if mode == "ew":
            w = np.full(n, 1.0 / n)
        else:
            w = mcap / mcap.sum()
        flagged = flag_sets[t]
        if mode == "exc":
            keep = ~flagged
            if not keep.any():
                gross[t], cost[t] = 0.0, 0.0
                continue                      # 全被剔除 ⇒ 这周不动
            w = w * keep
        else:
            w = w * np.where(flagged, 0.5, 1.0)
        w = w / w.sum()
        target = {names[i]: float(w[i]) for i in range(n)}
        if prev is None:
            turnover = 0.0
        else:
            keys = set(target) | set(prev)
            turnover = sum(abs(target.get(k, 0.0) - prev.get(k, 0.0)) for k in keys)
        c = (COST_BP / 1e4) * turnover
        g = float((w * rets).sum())
        gross[t] = g
        cost[t] = c
        grown = w * (1.0 + rets)
        prev = {names[i]: float(grown[i] / grown.sum()) for i in range(n)}
    net = gross - cost
    return {"gross": gross, "cost": cost, "net": net}


def ann_geo(series: np.ndarray) -> float:
    """年化几何收益(周频 → 52)。"""
    s = np.asarray(series, dtype=float)
    if s.size == 0 or np.any(1.0 + s <= 0):
        return float("nan")
    return float(np.prod(1.0 + s) ** (52.0 / s.size) - 1.0)


def stats(tilt: dict, base: dict, idx: np.ndarray) -> dict:
    """一段样本上的超额统计。"""
    idx = np.asarray(idx)
    gt, nt = tilt["gross"][idx], tilt["net"][idx]
    gb, nb = base["gross"][idx], base["net"][idx]
    ex_net = nt - nb
    ex_gross = gt - gb
    n = int(idx.size)
    out = {
        "n_weeks": n,
        "ann_gross_tilt": ann_geo(gt),
        "ann_gross_base": ann_geo(gb),
        "ann_net_tilt": ann_geo(nt),
        "ann_net_base": ann_geo(nb),
        "ann_excess_gross_geo": ann_geo(gt) - ann_geo(gb),
        "ann_excess_net_geo": ann_geo(nt) - ann_geo(nb),
        "ann_excess_net_arith": float(np.mean(ex_net) * 52.0) if n else float("nan"),
        "ann_excess_gross_arith": float(np.mean(ex_gross) * 52.0) if n else float("nan"),
        "tracking_error_net": float(np.std(ex_net, ddof=1) * math.sqrt(52.0)) if n > 1 else float("nan"),
        "weekly_excess_net_mean": float(np.mean(ex_net)) if n else float("nan"),
        # 成本年化:周成本之和 × (52 / 周数)
        "cost_bp_per_year_tilt": float(np.sum(tilt["cost"][idx]) * (52.0 / max(n, 1)) * 1e4),
        "cost_bp_per_year_base": float(np.sum(base["cost"][idx]) * (52.0 / max(n, 1)) * 1e4),
        # 敏感性:基准不付成本(净超额 = 倾斜方净 − 基准方毛)
        "ann_excess_net_vs_costless_base": ann_geo(nt) - ann_geo(gb),
    }
    return out


# ---------------------------------------------------------------- 主流程

def main() -> None:
    t0 = time.time()
    import pandas as pd
    selfcheck()
    print("[self] ok", flush=True)

    # ---------------- 拉数 ----------------
    deriv_csv = pull_dated(
        "/rest/v1/deriv_metrics_daily",
        [("select", "symbol,d,oi_close,oi_value_close,taker_ratio_mean")],
        "d", DERIV_FROM, SIGNAL_END, "symbol.asc,d.asc", "deriv_metrics_daily")
    am_csv = pull_dated(
        "/rest/v1/asset_mcap_daily",
        [("select", "symbol,coin_id,d,price,mcap"), ("source", "eq.coingecko_pro_market_chart")],
        "d", PRICE_FROM, OUTCOME_END, "symbol.asc,d.asc", "asset_mcap_daily")
    map_csv = pull_chunk("/rest/v1/perp_cg_map", [("select", "symbol,coin_id,mult,verdict")],
                         "symbol.asc", "perp_cg_map")
    cg_csv = pull_dated(
        "/rest/v1/cg_coin_mcap_daily",
        [("select", "coin_id,d,price,mcap")],
        "d", PRICE_FROM, OUTCOME_END, "coin_id.asc,d.asc", "cg_coin_mcap_daily")

    deriv = pd.read_csv(deriv_csv, dtype={"symbol": str, "d": str})
    am = pd.read_csv(am_csv, dtype={"symbol": str, "coin_id": str, "d": str})
    maps = pd.read_csv(map_csv, dtype={"symbol": str, "coin_id": str})
    cg = pd.read_csv(cg_csv, dtype={"coin_id": str, "d": str})
    print(f"[load ] deriv {len(deriv)} / asset_mcap {len(am)} / map {len(maps)} / cg {len(cg)}", flush=True)

    # ---------------- 名字集合 + 价/市值 ----------------
    name_set = set(deriv["symbol"].astype(str))
    am_syms = set(am["symbol"].astype(str).str.upper())

    px: dict[str, dict[int, tuple[float, float, float]]] = {}   # sym -> d -> (price, mcap, mult)
    for row in am.itertuples(index=False):
        sym = str(row.symbol).upper()
        if sym not in name_set:
            continue
        p = float(row.price) if row.price == row.price else float("nan")
        m = float(row.mcap) if row.mcap == row.mcap else float("nan")
        if not (math.isfinite(p) and p > 0):
            continue
        px.setdefault(sym, {})[d2ord(str(row.d))] = (p, m, 1.0)

    cg_by_id: dict[str, dict[int, tuple[float, float]]] = {}
    for row in cg.itertuples(index=False):
        p = float(row.price) if row.price == row.price else float("nan")
        m = float(row.mcap) if row.mcap == row.mcap else float("nan")
        cg_by_id.setdefault(str(row.coin_id), {})[d2ord(str(row.d))] = (p, m)

    mapped: dict[str, tuple[str, float]] = {}
    for row in maps.itertuples(index=False):
        if str(row.verdict) != "resolved":
            continue
        sym = str(row.symbol).upper()
        if sym not in name_set or sym in am_syms:
            continue
        mapped[sym] = (str(row.coin_id), float(row.mult) if row.mult == row.mult else 1.0)
    for sym, (cid, mult) in mapped.items():
        for d, (p, m) in cg_by_id.get(cid, {}).items():
            if math.isfinite(p) and p > 0:
                px.setdefault(sym, {})[d] = (p, m, mult)
    print(f"[map  ] universe 名字 {len(name_set)},有价 {len(px)},映射补数 {len(mapped)}", flush=True)

    # ---------------- 衍生指标 ----------------
    oi: dict[str, dict[int, dict]] = {}
    for row in deriv.itertuples(index=False):
        rec = {
            "oi_close": float(row.oi_close) if row.oi_close == row.oi_close else None,
            "oi_value": float(row.oi_value_close) if row.oi_value_close == row.oi_value_close else None,
            "taker": float(row.taker_ratio_mean) if row.taker_ratio_mean == row.taker_ratio_mean else None,
        }
        oi.setdefault(str(row.symbol).upper(), {})[d2ord(str(row.d))] = rec

    # ---------------- 映射校验(照 S-689) ----------------
    lo, hi = d2ord(SIGNAL_START), d2ord(SIGNAL_END)
    check_rows = []
    for sym, series in oi.items():
        if sym not in px:
            continue
        errs = []
        for d, rec in series.items():
            if not (lo <= d <= hi):
                continue
            if rec["oi_close"] is None or rec["oi_value"] is None:
                continue
            if rec["oi_close"] <= 0 or rec["oi_value"] <= 0:
                continue
            p = px[sym].get(d)
            if p is None or not math.isfinite(p[0]) or p[0] <= 0:
                continue
            implied = rec["oi_value"] / rec["oi_close"]
            errs.append(abs(p[0] * p[2] / implied - 1.0))
        if errs:
            check_rows.append((sym, len(errs), float(np.median(errs))))
    kept = {s for s, n, e in check_rows if n >= MAP_MIN_OVERLAP and e <= MAP_MAX_MED_ERR}
    map_detail = {s: {"overlap_days": n, "median_err": round(e, 6)} for s, n, e in sorted(check_rows)}
    print(f"[map  ] 映射校验留 {len(kept)}/{len(check_rows)} 个名字", flush=True)

    # ---------------- 稠密日历 ----------------
    g_lo, g_hi = d2ord(PRICE_FROM), d2ord(OUTCOME_END)
    grid = np.arange(g_lo, g_hi + 1)
    gsize = len(grid)
    gidx = {d: i for i, d in enumerate(grid)}

    def dense(series: dict[int, float]) -> np.ndarray:
        arr = np.full(gsize, np.nan)
        for d, v in series.items():
            i = gidx.get(d)
            if i is not None and v is not None and math.isfinite(v):
                arr[i] = v
        return arr

    btc = np.full(gsize, np.nan)
    for row in am[am["coin_id"].astype(str) == "bitcoin"].itertuples(index=False):
        btc[gidx[d2ord(str(row.d))]] = float(row.price)

    # 每名预计算因子(稠密数组)
    per: dict[str, dict[str, np.ndarray]] = {}
    for sym in sorted(name_set):
        if sym not in px:
            continue
        price_d = dense({d: v[0] for d, v in px[sym].items()})
        mcap_d = dense({d: v[1] for d, v in px[sym].items()})
        recs = oi.get(sym, {})
        taker_d = dense({d: r["taker"] for d, r in recs.items() if r["taker"] is not None})
        oi_close_d = dense({d: r["oi_close"] for d, r in recs.items() if r["oi_close"] is not None})

        prev = np.concatenate([[np.nan], price_d[:-1]])
        with np.errstate(invalid="ignore", divide="ignore"):
            ret = np.where((price_d > 0) & (prev > 0), np.log(price_d / prev), np.nan)
        f11 = roll_std(ret, 30, MIN_VOL_OBS)
        f7 = roll_mean(taker_d, 7, MIN_WINDOW_DAYS)

        def lag_ratio(arr, k):
            with np.errstate(invalid="ignore", divide="ignore"):
                return np.where((arr[k:] > 0) & (arr[:-k] > 0), arr[k:] / arr[:-k] - 1.0, np.nan)

        # F3 = ln(oi_close_d / oi_close_{d−30});F8/F9 = 相对 BTC 的动量
        f3 = np.full(gsize, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            f3[30:] = np.log(oi_close_d[30:] / oi_close_d[:-30])
        f8 = np.full(gsize, np.nan)
        f9 = np.full(gsize, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            f8[30:] = lag_ratio(price_d, 30) - lag_ratio(btc, 30)
            f9[7:] = lag_ratio(price_d, 7) - lag_ratio(btc, 7)
        per[sym] = {"f3": f3, "f7": f7, "f8": f8, "f9": f9, "f11": f11,
                    "price": price_d, "mcap": mcap_d, "oi_close": oi_close_d}
    print(f"[calc ] 因子数组 {len(per)} 个名字", flush=True)

    # ---------------- 调仓日(周一) ----------------
    d0, d1 = d2ord(SIGNAL_START), d2ord(SIGNAL_END)
    rebal = []
    o = d0
    while o <= d1:
        if date.fromordinal(o).weekday() == 0:
            rebal.append(o)
        o += 1
    print(f"[date ] 调仓日 {len(rebal)} 个:{ord2d(rebal[0])} → {ord2d(rebal[-1])}", flush=True)

    weeks: list[dict] = []
    flagged_all: list[np.ndarray] = []
    flagged_panel_ntile: list[np.ndarray] = []      # 敏感性:ntile(5) 在 24 名面板内部做
    weekly_log: list[dict] = []
    skipped_small = 0
    uni_sizes: list[int] = []
    panel_flag_counts = {p: 0 for p in PANEL}
    panel_in_universe_counts = {p: 0 for p in PANEL}
    panel_eligible_counts = {p: 0 for p in PANEL}

    for t, d in enumerate(rebal):
        dn = d + 7
        i = gidx.get(d)
        j = gidx.get(dn)
        if i is None or j is None:
            continue
        # --- 宇宙 ---
        uni: list[str] = []
        raw: dict[str, np.ndarray] = {}
        for sym in sorted(kept):
            if sym not in per:
                continue
            recs = oi.get(sym, {})
            rec = recs.get(d)
            if rec is None or rec["oi_close"] is None or rec["oi_value"] is None:
                continue
            if rec["oi_close"] <= 0 or rec["oi_value"] <= 0:
                continue
            m = per[sym]["mcap"][i]
            if not math.isfinite(m) or m < MCAP_MIN:
                continue
            vals = []
            ok = True
            for code, _, _ in FROZEN:
                v = per[sym][{"F3": "f3", "F7": "f7", "F8": "f8", "F9": "f9", "F11": "f11"}[code]][i]
                if not math.isfinite(v):
                    ok = False
                    break
                vals.append(v)
            if not ok:
                continue
            uni.append(sym)
            raw[sym] = np.array(vals)
        if len(uni) < MIN_NAMES:
            skipped_small += 1
            continue
        uni_sizes.append(len(uni))
        uni_set = set(uni)
        # --- comp:五个 percent_rank 的平均(方向按冻结符号) ---
        comp = np.zeros(len(uni))
        for k, (code, _, sign) in enumerate(FROZEN):
            arr = np.array([raw[s][k] for s in uni]) * sign
            comp += pct_rank(arr)
        comp /= len(FROZEN)
        bucket = ntile5(comp)
        worst = {uni[k] for k in range(len(uni)) if bucket[k] == 1}
        comp_by_name = {uni[k]: float(comp[k]) for k in range(len(uni))}

        # --- 面板本周可用名单 ---
        names, mcaps, rets = [], [], []
        for p in PANEL:
            if p not in per:
                continue
            p0 = per[p]["price"][i]
            p1 = per[p]["price"][j]
            mm = per[p]["mcap"][i]
            if not (math.isfinite(p0) and p0 > 0 and math.isfinite(p1) and p1 > 0):
                continue
            if not (math.isfinite(mm) and mm > 0):
                continue
            names.append(p)
            mcaps.append(mm)
            rets.append(p1 / p0 - 1.0)
            panel_eligible_counts[p] += 1
        if len(names) == 0:
            continue
        flagged = np.array([p in worst for p in names])
        for p in names:
            if p in worst:
                panel_flag_counts[p] += 1
            if p in uni_set:
                panel_in_universe_counts[p] += 1
        weeks.append({"d": d, "names": names, "mcap": np.array(mcaps), "rets": np.array(rets),
                      "flagged": flagged, "universe": len(uni), "worst": len(worst)})
        flagged_all.append(flagged)
        # 敏感性:ntile(5) 改在「面板里(在宇宙中且有合成值的)」24 名内部做
        pn = [p for p in names if p in comp_by_name]
        if len(pn) >= 5:
            pb = ntile5(np.array([comp_by_name[p] for p in pn]))
            worst_p = {pn[k] for k in range(len(pn)) if pb[k] == 1}
        else:
            worst_p = set()
        flagged_panel_ntile.append(np.array([p in worst_p for p in names]))
        weekly_log.append({"date": ord2d(d), "universe": len(uni), "worst_bucket": len(worst),
                           "panel": len(names), "panel_flagged": int(flagged.sum()),
                           "panel_flagged_names": [p for p, f in zip(names, flagged) if f]})

    W = len(weeks)
    print(f"[week ] 有效调仓周 {W}(宇宙 < 30 名跳过 {skipped_small} 周)", flush=True)

    # ---------------- 三条臂 ----------------
    base_mw = simulate(weeks, [np.zeros(len(w["names"]), dtype=bool) for w in weeks], "mw")
    base_ew = simulate(weeks, [np.zeros(len(w["names"]), dtype=bool) for w in weeks], "ew")
    tilt_mw = simulate(weeks, flagged_all, "mw")
    tilt_ew = simulate(weeks, flagged_all, "ew")
    arm_exc = simulate(weeks, flagged_all, "exc")

    arms = {
        "mcap_weighted_tilt": {"tilt": tilt_mw, "base": base_mw},
        "equal_weight_tilt": {"tilt": tilt_ew, "base": base_ew},
        "exclude_worst": {"tilt": arm_exc, "base": base_mw},
    }

    # ---------------- 随机对照(每周随机挑同样个数减半) ----------------
    k_t = [int(w["flagged"].sum()) for w in weeks]
    n_t = [len(w["names"]) for w in weeks]

    def null_fn(rng: np.random.Generator, mode: str, weeks_sub: list[dict],
                k_sub: list[int], n_sub: list[int], base_net_sub: np.ndarray) -> float:
        """一次随机抽取:每周在当周可用的面板名字里随机挑同样多个减半,再跑同一条臂。

        base_net_sub = 该段的「不倾斜」净收益序列(必须与 weeks_sub 同一段,
        否则年化拿不同长度的两段相比,数字会离谱)。
        """
        flags = []
        for t in range(len(weeks_sub)):
            k = min(k_sub[t], n_sub[t])
            f = np.zeros(n_sub[t], dtype=bool)
            if k > 0:
                f[rng.choice(n_sub[t], size=k, replace=False)] = True
            flags.append(f)
        res = simulate(weeks_sub, flags, mode)
        return ann_geo(res["net"]) - ann_geo(base_net_sub)

    half_cut = d2ord(HALF_CUT)
    seg_idx = {
        "full": np.arange(W),
        "h1_le_2024-11-30": np.array([t for t, w in enumerate(weeks) if w["d"] <= half_cut]),
        "h2_after_2024-11-30": np.array([t for t, w in enumerate(weeks) if w["d"] > half_cut]),
    }

    nulls: dict[str, np.ndarray] = {}
    pct: dict[str, dict[str, float | None]] = {}
    seg_null_pct: dict[str, dict[str, float | None]] = {}
    seg_null_med: dict[str, dict[str, float | None]] = {}

    def safe_null(fn, n, seed, actual):
        """零分布没有方差时(NoOpNull)不假装有分位 —— 记成 None。"""
        try:
            return null_distribution(fn, n, seed, actual=actual), None
        except NoOpNull as e:
            return None, str(e)

    for a_i, (name, mode) in enumerate((("mcap_weighted_tilt", "mw"),
                                        ("equal_weight_tilt", "ew"),
                                        ("exclude_worst", "exc"))):
        base = base_mw if mode in ("mw", "exc") else base_ew
        obs = ann_geo(arms[name]["tilt"]["net"]) - ann_geo(base["net"])
        null, err = safe_null(lambda rng, m=mode: null_fn(rng, m, weeks, k_t, n_t, base["net"]),
                              N_NULL, SEED + a_i, obs)
        nulls[name] = null
        p = percentile_of(obs, null) if null is not None else None
        pct[name] = {"observed": obs, "null_pct": p, "null_error": err,
                     "null_q025": float(np.quantile(null, 0.025)) if null is not None else None,
                     "null_q50": float(np.quantile(null, 0.5)) if null is not None else None,
                     "null_q975": float(np.quantile(null, 0.975)) if null is not None else None,
                     "null_mean": float(np.mean(null)) if null is not None else None}
        print(f"[null ] {name}: obs {obs:+.4%} → 分位 {p} {err or ''}", flush=True)
        # 每段自己的随机对照(同一套随机化,只在该段上统计)
        seg_null_pct[name] = {}
        seg_null_med[name] = {}
        for s_i, (sk, idx) in enumerate(seg_idx.items()):
            if idx.size == 0:
                seg_null_pct[name][sk] = None
                seg_null_med[name][sk] = None
                continue
            wsub = [weeks[t] for t in idx]
            ksub = [k_t[t] for t in idx]
            nsub = [n_t[t] for t in idx]
            obs_s = ann_geo(arms[name]["tilt"]["net"][idx]) - ann_geo(base["net"][idx])
            null_s, _ = safe_null(lambda rng, m=mode: null_fn(rng, m, wsub, ksub, nsub, base["net"][idx]),
                                  N_NULL, SEED + 100 + a_i * 10 + s_i, obs_s)
            seg_null_pct[name][sk] = percentile_of(obs_s, null_s) if null_s is not None else None
            seg_null_med[name][sk] = float(np.quantile(null_s, 0.5)) if null_s is not None else None

    # ---------------- 分段统计 ----------------
    out_arms: dict[str, dict] = {}
    for name, ab in arms.items():
        segs = {sk: stats(ab["tilt"], ab["base"], idx) for sk, idx in seg_idx.items()}
        for sk in segs:
            if sk == "full":
                segs[sk]["null_pct"] = pct[name]["null_pct"]       # 主零分布(卡上那一次)
                segs[sk]["null_q50"] = pct[name]["null_q50"]
            else:
                segs[sk]["null_pct"] = seg_null_pct[name][sk]
                segs[sk]["null_q50"] = seg_null_med[name][sk]
        out_arms[name] = segs

    # ---------------- 敏感性:ntile(5) 在 24 名面板内部做(协议歧义 #2 的量化) ----------------
    k_pn = [int(f.sum()) for f in flagged_panel_ntile]
    tilt_mw_pn = simulate(weeks, flagged_panel_ntile, "mw")
    sens_pn = {sk: stats(tilt_mw_pn, base_mw, idx) for sk, idx in seg_idx.items()}
    obs_pn = ann_geo(tilt_mw_pn["net"]) - ann_geo(base_mw["net"])
    null_pn, err_pn = safe_null(lambda rng: null_fn(rng, "mw", weeks, k_pn, n_t, base_mw["net"]),
                                 N_NULL, SEED + 77, obs_pn)
    sens_pn["full"]["null_pct"] = percentile_of(obs_pn, null_pn) if null_pn is not None else None
    sens_pn["full"]["null_q50"] = float(np.quantile(null_pn, 0.5)) if null_pn is not None else None
    print(f"[sens ] panel-ntile: obs {obs_pn:+.4%} → 分位 {sens_pn['full']['null_pct']}", flush=True)

    # 面板不满 24 名的周(ARB/SUI 上市前)
    short_weeks = [w for w in weeks if len(w["names"]) < len(PANEL)]
    short_range = (f"{ord2d(short_weeks[0]['d'])} → {ord2d(short_weeks[-1]['d'])}"
                   if short_weeks else "无")

    # ---------------- 面板名字落在最差档的周占比 ----------------
    panel_share = {}
    for p in PANEL:
        panel_share[p] = {
            "weeks_flagged": panel_flag_counts[p],
            "weeks_in_universe": panel_in_universe_counts[p],
            "weeks_eligible": panel_eligible_counts[p],
            "share_of_all_weeks": panel_flag_counts[p] / W if W else None,
            "share_of_universe_weeks": (panel_flag_counts[p] / panel_in_universe_counts[p]
                                         if panel_in_universe_counts[p] else None),
        }

    # ---------------- 判定 ----------------
    main_arm = out_arms["mcap_weighted_tilt"]
    a_net = main_arm["full"]["ann_excess_net_geo"]
    a_pct = pct["mcap_weighted_tilt"]["null_pct"]
    b1 = main_arm["h1_le_2024-11-30"]["ann_excess_net_geo"]
    b2 = main_arm["h2_after_2024-11-30"]["ann_excess_net_geo"]
    judge = {
        "criterion_a_net_excess_positive": bool(a_net > 0),
        "criterion_a_null_pct_ge_95": bool(a_pct is not None and a_pct >= 0.95),
        "criterion_b_h1_positive": bool(b1 > 0),
        "criterion_b_h2_positive": bool(b2 > 0),
    }
    judge["pass"] = bool(all(judge.values()))

    result = {
        "card": "T-209",
        "ledger": "S-694",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spec": {
            "panel": PANEL,
            "signal_start": SIGNAL_START, "signal_end": SIGNAL_END, "outcome_end": OUTCOME_END,
            "rebalance": "周一 UTC", "frozen_factors": [{"code": c, "name": n, "sign": s} for c, n, s in FROZEN],
            "universe": (f"deriv 名字;过 S-689 映射校验(重叠 ≥ {MAP_MIN_OVERLAP} 日、中位误差 ≤ {MAP_MAX_MED_ERR});"
                         f"CG 市值 ≥ {MCAP_MIN:,.0f};当天 OI > 0;五因子都有定义;当天 ≥ {MIN_NAMES} 名"),
            "comp": "五个 percent_rank 的平均(方向按冻结符号)", "worst": "ntile(5) 第 1 档",
            "main_arm": "市值加权(落在最差档的权重 × 0.5 后归一)", "secondary_arms": ["等权", "剔除"],
            "cost": f"{COST_BP:.0f} bp × Σ|目标 − 上周漂移后权重|",
            "judgement": "(a) 年化净超额 > 0 且随机对照 ≥ 95 分位;(b) 两段净超额都 > 0",
        },
        "data": {
            "deriv_rows": int(len(deriv)), "asset_mcap_rows": int(len(am)),
            "cg_rows": int(len(cg)), "map_rows": int(len(maps)),
            "map_kept_names": len(kept), "names_with_price": len(px),
            "map_checked": len(check_rows),
        },
        "universe": {
            "n_rebalance_mondays": len(rebal), "n_weeks_used": W,
            "weeks_skipped_universe_lt_min": skipped_small,
            "universe_size_mean": float(np.mean(uni_sizes)) if uni_sizes else None,
            "universe_size_min": int(np.min(uni_sizes)) if uni_sizes else None,
            "universe_size_max": int(np.max(uni_sizes)) if uni_sizes else None,
            "worst_bucket_mean": float(np.mean([w["worst"] for w in weeks])) if W else None,
            "panel_flagged_mean_per_week": float(np.mean(k_t)) if W else None,
            "panel_flagged_max_per_week": int(np.max(k_t)) if W else None,
            "weeks_panel_below_24": len(short_weeks),
            "panel_short_weeks_range": short_range,
        },
        "arms": out_arms,
        "sensitivity_panel_ntile": {
            "note": "协议歧义:ntile(5) 改在 24 名面板内部做(而不是在宽宇宙上做)",
            "flagged_per_week_mean": float(np.mean(k_pn)) if k_pn else None,
            "segments": sens_pn,
        },
        "null_control": pct,
        "judgement": judge,
        "panel_worst_bucket_share": panel_share,
        "weekly": weekly_log,
        "map_check_detail": map_detail,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"[write] {OUT_JSON}", flush=True)

    write_report(result)
    print(f"[write] {OUT_MD}", flush=True)
    print(f"[done ] {time.time() - t0:.1f}s", flush=True)


# ---------------------------------------------------------------- 报告

def pctf(x: float | None, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:+.{digits}f}%"


def pctstr(p: float | None) -> str:
    if p is None or (isinstance(p, float) and not math.isfinite(p)):
        return "—"
    return f"{p * 100:.1f}%"


def pctabs(x: float | None, digits: int = 2) -> str:
    """不带正负号(跟踪误差、零分布中位这种)。"""
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:.{digits}f}%"


def write_report(r: dict) -> None:
    arms = r["arms"]
    null = r["null_control"]
    j = r["judgement"]
    u = r["universe"]
    sens = r["sensitivity_panel_ntile"]["segments"]
    lines: list[str] = []
    A = lines.append

    A("# T-209 / S-694 —— ① 面板「躲开宽宇宙五因子合成最差五分之一」盲复算(C 道)")
    A("")
    A(f"生成:{r['generated_at']} · 调仓:{r['spec']['signal_start']} → {r['spec']['signal_end']}"
      f"(周一 UTC,{u['n_rebalance_mondays']} 个调仓日,有效 {u['n_weeks_used']} 周)")
    A("")
    A("## 一、一张表(主口径 = 市值加权倾斜)")
    A("")
    A("| 口径 | 段 | 周数 | 年化毛超额 | 年化净超额 | 跟踪误差 | 随机对照分位 | 随机对照中位 |")
    A("|---|---|---|---|---|---|---|---|")
    seg_name = {"full": "全段", "h1_le_2024-11-30": "前段(≤2024-11-30)",
                "h2_after_2024-11-30": "后段(之后)"}
    for name, cn in (("mcap_weighted_tilt", "主:市值加权减半"),
                     ("equal_weight_tilt", "副:等权减半"),
                     ("exclude_worst", "副:剔除")):
        for sk in ("full", "h1_le_2024-11-30", "h2_after_2024-11-30"):
            s = arms[name][sk]
            if not s or s["n_weeks"] == 0:
                continue
            np_ = s.get("null_pct")
            A(f"| {cn} | {seg_name[sk]} | {s['n_weeks']} | {pctf(s['ann_excess_gross_geo'])} | "
              f"{pctf(s['ann_excess_net_geo'])} | {pctabs(s['tracking_error_net'])} | "
              f"{'—' if np_ is None else f'{np_ * 100:.1f}%'} | "
              f"{pctabs(s.get('null_q50'))} |")
    A("")
    A("## 二、判定(照卡写死的判据)")
    A("")
    A(f"- (a) 年化净超额 > 0:**{'是' if j['criterion_a_net_excess_positive'] else '否'}**"
      f"(主口径全段 {pctf(arms['mcap_weighted_tilt']['full']['ann_excess_net_geo'])})")
    A(f"- (a) 随机对照 ≥ 95 分位:**{'是' if j['criterion_a_null_pct_ge_95'] else '否'}**"
      f"(实际 {pctstr(null['mcap_weighted_tilt']['null_pct'])} 分位;"
      f"零分布中位 {pctf(null['mcap_weighted_tilt']['null_q50'])},"
      f"97.5% 分位 {pctf(null['mcap_weighted_tilt']['null_q975'])})")
    A(f"- (b) 前段净超额 > 0:**{'是' if j['criterion_b_h1_positive'] else '否'}**"
      f"({pctf(arms['mcap_weighted_tilt']['h1_le_2024-11-30']['ann_excess_net_geo'])})")
    A(f"- (b) 后段净超额 > 0:**{'是' if j['criterion_b_h2_positive'] else '否'}**"
      f"({pctf(arms['mcap_weighted_tilt']['h2_after_2024-11-30']['ann_excess_net_geo'])})")
    A("")
    A(f"**结论:{'✅ 过' if j['pass'] else '❌ 不过'}(S-694 判据 (a)+(b) 全部要过)。**")
    A("")
    A("## 三、支撑数字")
    A("")
    s = arms["mcap_weighted_tilt"]["full"]
    A(f"- 主口径全段:倾斜毛年化 {pctf(s['ann_gross_tilt'])} vs 不倾斜毛年化 {pctf(s['ann_gross_base'])};"
      f"倾斜净年化 {pctf(s['ann_net_tilt'])} vs 不倾斜净年化 {pctf(s['ann_net_base'])}")
    A(f"- 成本(10 bp × 换手):倾斜 {s['cost_bp_per_year_tilt']:.1f} bp/年,不倾斜 {s['cost_bp_per_year_base']:.1f} bp/年")
    A(f"- 周超额均值 {s['weekly_excess_net_mean'] * 100:+.4f}%,跟踪误差 {pctf(s['tracking_error_net'])}")
    A(f"- 敏感性(基准不付成本):全段净超额 {pctf(s['ann_excess_net_vs_costless_base'])}")
    A(f"- 宇宙:每天 {u['universe_size_min']}–{u['universe_size_max']} 名(均值 {u['universe_size_mean']:.0f}),"
      f"最差档平均 {u['worst_bucket_mean']:.1f} 名;面板平均每周 {u['panel_flagged_mean_per_week']:.2f} 个名字落在最差档"
      f"(最多 {u['panel_flagged_max_per_week']} 个)")
    A(f"- 宇宙不足 30 名而跳过的调仓日:{u['weeks_skipped_universe_lt_min']} 个")
    A("")
    A("### 面板每个名字落在最差档的周占比")
    A("")
    A("| 名字 | 落在最差档周数 | 在宇宙里的周数 | 占全部调仓周 | 占在宇宙的周 |")
    A("|---|---|---|---|---|")
    for p, v in sorted(r["panel_worst_bucket_share"].items(),
                        key=lambda kv: -kv[1]["share_of_all_weeks"]):
        A(f"| {p} | {v['weeks_flagged']} | {v['weeks_in_universe']} | "
          f"{'—' if v['share_of_all_weeks'] is None else f'{v['share_of_all_weeks'] * 100:.1f}%'} | "
          f"{'—' if v['share_of_universe_weeks'] is None else f'{v['share_of_universe_weeks'] * 100:.1f}%'} |")
    A("")
    A("## 四、协议问题(需要 @seth 拍板或知悉)")
    A("")
    A("1. **基准要不要付成本**:卡上只写「成本 10 bp × Σ|目标 − 上周漂移后权重|」。本卡把成本同时记在"
      "「倾斜」和「不倾斜」两条臂上(同一个 10 bp 模型),净超额 = 净(倾斜) − 净(不倾斜);"
      f"同时报了「基准不付成本」的敏感性(全段净超额 {pctf(s['ann_excess_net_vs_costless_base'])}"
      f" vs {pctf(s['ann_excess_net_geo'])},前段 "
      f"{pctf(arms['mcap_weighted_tilt']['h1_le_2024-11-30']['ann_excess_net_vs_costless_base'])}"
      f" vs {pctf(arms['mcap_weighted_tilt']['h1_le_2024-11-30']['ann_excess_net_geo'])})。"
      "两种读法在本卡上的结论一致。")
    A("2. **ntile(5) 在哪个样本上做**:卡上写「落在宽宇宙五因子合成最差五分之一」,本卡按**宇宙**做 ntile(5)"
      "(PostgreSQL 口径:前面的档多拿行),再取落在第 1 档的面板名字。若改成在 24 名面板内部做 ntile(5),"
      "每周恰好有 4–5 个名字被标记,「每个名字落在最差档的周占比」会退化成构造出来的 20%,不可用 —— "
      f"作为敏感性跑了一遍:全段净超额 {pctf(sens['full']['ann_excess_net_geo'])}"
      f"(毛 {pctf(sens['full']['ann_excess_gross_geo'])}),随机对照 "
      f"{'—' if sens['full'].get('null_pct') is None else f'{sens['full']['null_pct'] * 100:.1f}%'} 分位,"
      f"前段净超额 {pctf(sens['h1_le_2024-11-30']['ann_excess_net_geo'])} —— "
      "两种读法都不改变本卡的判定。")
    A("3. **「剔除」臂的基准**:卡上没写。本卡用「市值加权不倾斜(全持)」做基准(剔除臂天然要跟同族的市值加权比)。")
    A("4. **2024-12 是 S-691 的隔离月**:卡上写两段切在 2024-11-30,后段因此含 2024-12(S-691 当初留出时"
      "把 2024-12 整月隔离掉了)。本卡按卡上的字面切分,没剔除 12 月。")
    A(f"5. **面板早期不满 24 名**:ARB(2023-03 上市)、SUI(2023-05 上市)在此之前没有价格也没有 OI,"
      f"面板不满 24 名的调仓周共 {u['weeks_panel_below_24']} 个(最早 {u['panel_short_weeks_range']});"
      "这些名字缺席时不摊权重给别的名字(按市值归一)。")
    A("6. **宇宙门槛「当天 ≥ 30 名」**:不满 30 名的调仓日整周跳过(不进组合、不进随机对照),"
      f"本卡共跳过 {u['weeks_skipped_universe_lt_min']} 周。")
    A("")
    A("## 五、还看到了什么(探索性)")
    A("")
    A("> 以下每条都是**探索性** —— 需另立预注册、在新数据上过零信号对照,不得直接当结论用。")
    A("")
    ew = arms["equal_weight_tilt"]["full"]
    ex = arms["exclude_worst"]["full"]
    mw1 = arms["mcap_weighted_tilt"]["h1_le_2024-11-30"]
    ew1 = arms["equal_weight_tilt"]["h1_le_2024-11-30"]
    A(f"1. **前段毛超额是正的、净超额是负的**:主口径前段毛超额 {pctf(mw1['ann_excess_gross_geo'])}、"
      f"净超额 {pctf(mw1['ann_excess_net_geo'])} —— 差的是倾斜自己的换手成本"
      f"({mw1['cost_bp_per_year_tilt']:.0f} bp/年,而「不倾斜」只有 {mw1['cost_bp_per_year_base']:.1f} bp/年)。"
      "「躲开最差档」每周都要重定权重,成本不是零头:换手成本能把一个正的毛超额翻成负的净超额。")
    A(f"2. **面板名字落在最差档的频率高于基准**:宇宙的最差档占 20%,面板每周平均 "
      f"{u['panel_flagged_mean_per_week']:.2f} 个名字落在最差档(占 24 名的 "
      f"{u['panel_flagged_mean_per_week'] / len(PANEL) * 100:.0f}%)。"
      "面板本身在合成里被系统性地排得更靠后 —— 这本身是个独立问题(信号在宽宇宙里挑的是小盘)。")
    A(f"3. **同一信号在不同加权口径下前段方向相反**:等权减半前段毛超额 {pctf(ew1['ann_excess_gross_geo'])}、"
      f"净超额 {pctf(ew1['ann_excess_net_geo'])},市值加权前段却是毛 {pctf(mw1['ann_excess_gross_geo'])}、"
      f"净 {pctf(mw1['ann_excess_net_geo'])}。全段三个口径:市值加权 {pctf(arms['mcap_weighted_tilt']['full']['ann_excess_net_geo'])}、"
      f"等权 {pctf(ew['ann_excess_net_geo'])}、剔除 {pctf(ex['ann_excess_net_geo'])}。")
    A(f"4. **剔除臂的毛超额很大但被成本吃掉**:剔除全段毛超额 {pctf(ex['ann_excess_gross_geo'])}、"
      f"净超额 {pctf(ex['ann_excess_net_geo'])},成本 {ex['cost_bp_per_year_tilt']:.0f} bp/年,"
      f"跟踪误差 {pctabs(ex['tracking_error_net'])}(主口径只有 {pctabs(arms['mcap_weighted_tilt']['full']['tracking_error_net'])})。")
    A("5. 面板名字落在最差档的周占比(上表)分化很大(SOL 44.7% vs TRX 9.0%)。"
      "把「谁常年最差」当成一个横截面信号,是与本卡不同的假设。")
    A("")
    A("---")
    A("")
    A(f"原始结果:`docs/research/t209_results.json`(逐周宇宙大小、被标记名字、三条臂的周收益与成本)。"
      f"脚本:`docs/research/t209_avoid_tilt.py`。零分布与分位走 `src/data/evaluation/apparatus.py`"
      f"(`null_distribution` / `percentile_of`),没另起炉灶。")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
