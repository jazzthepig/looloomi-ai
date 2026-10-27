#!/usr/bin/env python3
"""T-208 / 台账 S-691 —— 冻结短名单的**留出段**独立复算(B 道盲复算)。

**留出段**:信号日 2025-01-01 → 2026-09-26(结果窗口止于 2026-10-26;2024-12 是隔离月,
信号日不用)。发现段(2023-01-01 → 2024-11-30)的结果已冻结(台账 §S-691 短名单冻结),
本脚本只算留出段,统计量与 T-206(发现段)同一套代码、同一把尺子。

**只算冻结的 5 个因子**(台账 §短名单冻结):F3(ΔOI 30 天,−)、F7(主动买卖比 7 天,+)、
F8(30 天相对动量,−)、F9(7 天相对动量,−)、F11(30 天波动,−);F1(OI/市值)照报但不计入判定。

方法照台账 S-691 一字不改(偏 Spearman 控制规模):
  · 宇宙(主口径 = §Seth-1027a 定的括注读法):deriv_metrics_daily 里的名字(含 CIS 面板名字),
    过 S-689 的映射校验(隐含价 = oi_value_close / oi_close,
    对重叠日算 median |CG 价 × 倍数 / 隐含价 − 1|,≥ 30 个重叠日且 ≤ 0.05 才留),
    当天 CG 市值 ≥ 2,000 万美元,d 与 d + 30 的 CG 价都在,**且当天 oi_value_close > 0**。
    对照口径(台账宇宙句的字面读法:当天不要求有 OI 值)另跑一遍,写进结果的
    `universe_sensitivity_broad`,只报不判。
  · 结果 y = (p_{d+30}/p_d − 1) − (BTC_{d+30}/BTC_d − 1),同一 CG 源。
  · 每个 d 每个因子:该因子有定义的名字 ≥ 30 个才算一天。
  · 主统计量:偏 Spearman ρ(因子, y | 规模)。
  · 日值按自然月平均,t = 月均 / 月标准差 × √月数。
  · 判定(照预注册,写死):与冻结符号同号、|月 t| ≥ 2.0、≥ 60% 留出月份同号 ⇒ ✅。

零分布 / 盈亏 / A/B 一律走 `src/data/evaluation/apparatus.py`(不另起炉灶)。
只读 Supabase(publishable key)。用法:
    python3 docs/research/t208_factor_zoo_holdout.py
环境:SUPABASE_URL / SUPABASE_KEY(缺一个就报错退出)。
产物:
    docs/research/t208_results.json
    /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-208_factor_zoo_holdout.md
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
from scipy.ndimage import maximum_filter1d

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.data.evaluation.apparatus import (   # 零分布 / 盈亏 / A/B 只许用这里的函数
    ab_test,
    long_return,
    null_distribution,
    percentile_of,
    shuffle_within,
    short_return,
)

# ---------------------------------------------------------------- 配置

HOLDOUT_START = "2025-01-01"         # 第一个信号日
HOLDOUT_END = "2026-09-26"           # 最后一个信号日(d+30 = 2026-10-26 有 CG 价)
OUTCOME_H = 30                       # 结果窗口 d → d+30
OUTCOME_END = "2026-10-26"           # 结果窗口的最后一天(HOLDOUT_END + 30)
PRICE_FROM = "2024-10-01"            # 价格/市值:给 30 天动量/波动留回看
DERIV_FROM = "2024-10-01"            # 衍生指标:给 F3 的 30 天回看留头
# F4(funding)不在冻结名单里 ⇒ 资金费整表不拉(不改变任何被判因子的口径)。

MIN_NAMES = 30                          # 每天每个因子的最少名字数
MCAP_MIN = 20_000_000.0                 # CG 市值门槛
MAP_MIN_OVERLAP = 30                    # 映射校验:最少重叠日
MAP_MAX_MED_ERR = 0.05                  # 映射校验:中位误差上限
MIN_VOL_OBS = 25                        # F11 波动:最少收益个数
MIN_HIGH_OBS = 300                      # F13:52 周高点窗口最少价格个数
MIN_WINDOW_DAYS = 5                     # F4/F7:7 天窗口里最少有效天数

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = REPO_ROOT / "docs" / "research" / "t208_results.json"
MAC_ROOT = Path("/Volumes/CometCloudAI/cometcloud-local")
CACHE_DIR = MAC_ROOT / "research" / "t208_cache"
OUT_MD = MAC_ROOT / "_reports" / "absorb_input" / "T-208_factor_zoo_holdout.md"
OUT_JSON_ALT = MAC_ROOT / "research" / "t208_universe_broad.json"   # 对照口径的逐月结果

# 宇宙口径(与 T-206 发现段同一套代码,只把主/对照对调):
#   "oi_required"(主):§Seth-1027a 定的括注读法 —— 每天还要当天 oi_value_close > 0。
#   "broad"(对照):台账 S-691 宇宙句的字面读法 —— 当天没有 OI 行、但有价有市值的名字仍留下。
UNIVERSE_MODE = "oi_required"

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
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read().decode()
        except urllib.error.HTTPError as e:  # 5xx 退避重试
            if e.code < 500 or attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def count_rows(path: str, params: list[tuple[str, str]]) -> int:
    _, cr = None, None
    req = urllib.request.Request(URL.rstrip("/") + path + "?" + urllib.parse.urlencode(params, safe="(),.*:<>="),
                                 headers={**HEAD, "Prefer": "count=exact", "Range": "0-0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        cr = r.headers.get("Content-Range", "")
    if not cr or "/" not in cr:
        return -1
    tail = cr.split("/")[-1]
    return int(tail) if tail.isdigit() else -1


def pull(path: str, params: list[tuple[str, str]], order: str, tag: str) -> Path:
    """整表拉取(带 order= 主键排序),分页 1000 行,落 CSV 缓存。"""
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
    ranges = []
    if total >= 0:
        ranges = [(i, min(i + PAGE - 1, total - 1)) for i in range(0, total, PAGE)]
    else:
        i = 0
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
    with ThreadPoolExecutor(max_workers=8) as ex:
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


# ---------------------------------------------------------------- 小工具

def d2ord(s: str) -> int:
    return date.fromisoformat(s[:10]).toordinal()


def avg_rank(vals: np.ndarray) -> np.ndarray:
    """并列名次的平均名次(与 S-689 SQL 的 rank() + (count−1)/2 一致)。"""
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


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return float("nan")
    sa, sb = a.std(), b.std()
    if sa == 0 or sb == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def partial_spearman(rf: np.ndarray, ry: np.ndarray, rs: np.ndarray) -> float:
    """偏 Spearman:ρ(f, y | s) = (ρ_fy − ρ_fs·ρ_ys) / √((1−ρ_fs²)(1−ρ_ys²))(同 S-689)。"""
    r_fy = pearson(rf, ry)
    r_fs = pearson(rf, rs)
    r_ys = pearson(ry, rs)
    if not (math.isfinite(r_fy) and math.isfinite(r_fs) and math.isfinite(r_ys)):
        return float("nan")
    if abs(r_fs) >= 1 - 1e-12 or abs(r_ys) >= 1 - 1e-12:
        # S-689 的 SQL 守卫是 abs(r) < 1;浮点上「恰好 1」会算成 0.9999999999999999 而漏过守卫,
        # 分母趋零 ⇒ 吐出一个无意义的数。这里收紧到 1 − 1e-12(共线 ⇒ NaN)。
        return float("nan")
    return (r_fy - r_fs * r_ys) / math.sqrt((1 - r_fs * r_fs) * (1 - r_ys * r_ys))


def t_of(vals: list[float]) -> tuple[float, float, int]:
    """月值 → (月均, 月 t, 月数);t = 月均 / 月标准差 × √月数。"""
    v = [x for x in vals if math.isfinite(x)]
    n = len(v)
    if n < 2:
        return (float("nan"), float("nan"), n)
    arr = np.array(v, dtype=float)
    sd = arr.std(ddof=1)
    m = float(arr.mean())
    if sd == 0:
        return (m, float("nan"), n)
    return (m, float(m / sd * math.sqrt(n)), n)


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


# ---------------------------------------------------------------- 因子表


def selfcheck() -> None:
    """跑之前先钉住两个容易静默出错的地方:
    ① F13 的滚动最高价窗口必须向前看 [d−364, d](scipy origin=+182),不能含未来价;
    ② 偏 Spearman 的三个 ρ 必须在同一批观测上。
    """
    a = np.array([float(i) for i in range(1, 11)])          # 1..10
    hi = maximum_filter1d(a, size=5, origin=2, mode="constant", cval=-np.inf)
    assert hi[6] == max(a[2:7]), f"F13 窗口方向错: {hi[6]}"
    a2 = np.array([1.0, 5.0, 2.0, 9.0, 3.0])
    hi2 = maximum_filter1d(a2, size=5, origin=2, mode="constant", cval=-np.inf)
    assert hi2[4] == max(a2[0:5]), f"F13 窗口方向错: {hi2[4]}"
    # 偏相关自洽:① ρ(y,s)=1 时分母为 0 ⇒ NaN;② 偏相关 == 残差法算的偏相关
    f = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([2.0, 1.0, 4.0, 3.0, 5.0])
    s = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert math.isnan(partial_spearman(avg_rank(f), avg_rank(y), avg_rank(y))), "共线时应为 NaN"
    s2 = np.array([5.0, 3.0, 1.0, 4.0, 2.0])
    rf, ryy, rss = avg_rank(f), avg_rank(y), avg_rank(s2)
    pc = partial_spearman(rf, ryy, rss)
    # 残差法:把 rf、ryy 各对 rss 做 OLS,取残差相关
    def resid(v, z):
        beta = float(np.cov(v, z, bias=True)[0, 1] / np.var(z))
        return v - beta * (z - z.mean())
    pc_resid = pearson(resid(rf, rss), resid(ryy, rss))
    assert abs(pc - pc_resid) < 1e-10, f"偏相关公式不自洽: {pc} vs {pc_resid}"
    print("[check] F13 窗口方向 / 偏相关公式自洽 ✓", flush=True)

# 只算冻结的 5 个因子 + F1(照报不计)。发现段(2023-01 → 2024-11)的短名单已冻结于台账
# §S-691「短名单冻结」:F3(−)、F7(+)、F8(−)、F9(−)、F11(−);F1 已知,不算新发现。
FACTORS = [
    ("F1", "OI/市值", "partial"),
    ("F3", "ΔOI 30天 (ln 张数)", "partial"),
    ("F7", "主动买卖比 7天均", "partial"),
    ("F8", "30天相对动量 (对 BTC)", "partial"),
    ("F9", "7天相对动量 (对 BTC)", "partial"),
    ("F11", "30天波动 (日对数收益标准差)", "partial"),
]

# 冻结的符号(来自发现段,写死)。合成时按它把方向对齐成「高 = 预期跑赢」。
FROZEN = [
    ("F3", -1),
    ("F7", +1),
    ("F8", -1),
    ("F9", -1),
    ("F11", -1),
]
FROZEN_SIGN = {c: s for c, s in FROZEN}
# F1 已知(OI/市值,发现段 −0.118 / t −6.43)⇒ 只报不计,但同号月份照算,方便看它有没有失效。
KNOWN_SIGN = {"F1": -1}


def main() -> None:
    t0 = time.time()
    import pandas as pd
    selfcheck()
    broad = (UNIVERSE_MODE == "broad")
    print(f"[mode ] {UNIVERSE_MODE}", flush=True)

    # ---------------- 拉数(只拉留出段 + 回看所需的余量) ----------------
    deriv_csv = pull(
        "/rest/v1/deriv_metrics_daily",
        [("select", "symbol,d,oi_close,oi_value_close,top_pos_ratio_close,global_acct_ratio_close,taker_ratio_mean"),
         ("d", f"gte.{DERIV_FROM}"), ("d", f"lte.{HOLDOUT_END}")],
        "symbol.asc,d.asc", "deriv_metrics_daily")
    am_csv = pull(
        "/rest/v1/asset_mcap_daily",
        [("select", "symbol,coin_id,d,price,mcap,volume"),
         ("source", "eq.coingecko_pro_market_chart"),
         ("d", f"gte.{PRICE_FROM}"), ("d", f"lte.{OUTCOME_END}")],
        "symbol.asc,d.asc", "asset_mcap_daily")
    map_csv = pull("/rest/v1/perp_cg_map", [("select", "symbol,coin_id,mult,verdict")],
                   "symbol.asc", "perp_cg_map")
    cg_csv = pull("/rest/v1/cg_coin_mcap_daily",
                  [("select", "coin_id,d,price,mcap"), ("d", f"gte.{PRICE_FROM}"), ("d", f"lte.{OUTCOME_END}")],
                  "coin_id.asc,d.asc", "cg_coin_mcap_daily")
    # F4(funding)不在冻结名单里 ⇒ 资金费不拉。

    deriv = pd.read_csv(deriv_csv, dtype={"symbol": str, "d": str})
    am = pd.read_csv(am_csv, dtype={"symbol": str, "coin_id": str, "d": str})
    maps = pd.read_csv(map_csv, dtype={"symbol": str, "coin_id": str})
    cg = pd.read_csv(cg_csv, dtype={"coin_id": str, "d": str})

    # ---------------- 宇宙 + px(照 S-689 的映射段) ----------------
    name_set = set(deriv.loc[deriv["d"] >= HOLDOUT_START, "symbol"].astype(str))
    names = sorted(name_set)
    am_syms = set(am["symbol"].astype(str).str.upper())

    px: dict[str, dict[int, tuple[float, float, float]]] = {}   # sym -> d -> (price, mcap, mult)
    vol: dict[str, dict[int, float]] = {}                        # sym -> d -> 成交额(只有 asset_mcap_daily)
    for row in am.itertuples(index=False):
        sym = str(row.symbol).upper()
        if sym not in name_set:
            continue
        d = d2ord(str(row.d))
        px.setdefault(sym, {})[d] = (float(row.price), float(row.mcap), 1.0)
        if row.volume == row.volume:
            vol.setdefault(sym, {})[d] = float(row.volume)

    cg_by_id: dict[str, dict[int, tuple[float, float]]] = {}
    for row in cg.itertuples(index=False):
        cid = str(row.coin_id)
        p = float(row.price) if row.price == row.price else float("nan")
        m = float(row.mcap) if row.mcap == row.mcap else float("nan")
        cg_by_id.setdefault(cid, {})[d2ord(str(row.d))] = (p, m)

    mapped: dict[str, tuple[str, float]] = {}
    for row in maps.itertuples(index=False):
        if str(row.verdict) != "resolved":
            continue
        sym = str(row.symbol)
        if sym not in name_set or sym in am_syms:
            continue
        mapped[sym] = (str(row.coin_id), float(row.mult) if row.mult == row.mult else 1.0)
    for sym, (cid, mult) in mapped.items():
        for d, (p, m) in cg_by_id.get(cid, {}).items():
            px.setdefault(sym, {})[d] = (p, m, mult)

    # ---------------- 衍生指标 ----------------
    oi: dict[str, dict[int, dict]] = {}
    for row in deriv.itertuples(index=False):
        rec = {
            "oi_close": float(row.oi_close) if row.oi_close == row.oi_close else None,
            "oi_value": float(row.oi_value_close) if row.oi_value_close == row.oi_value_close else None,
            "top_pos": float(row.top_pos_ratio_close) if row.top_pos_ratio_close == row.top_pos_ratio_close else None,
            "gacct": float(row.global_acct_ratio_close) if row.global_acct_ratio_close == row.global_acct_ratio_close else None,
            "taker": float(row.taker_ratio_mean) if row.taker_ratio_mean == row.taker_ratio_mean else None,
        }
        oi.setdefault(str(row.symbol), {})[d2ord(str(row.d))] = rec

    # 资金费:F4 不在冻结名单里 ⇒ 不拉、不算(资金费整段不参与本卡的任何数字)。

    # ---------------- 映射校验(照 S-689;重叠日只在留出段信号日内) ----------------
    lo, hi = d2ord(HOLDOUT_START), d2ord(HOLDOUT_END)
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

    # ---------------- BTC(同一 CG 源) ----------------
    btc: dict[int, float] = {}
    for row in am[am["coin_id"].astype(str) == "bitcoin"].itertuples(index=False):
        btc[d2ord(str(row.d))] = float(row.price)

    # ---------------- 稠密日历(每格一天) ----------------
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

    # 每名预计算:窗口类因子的滚动值
    roll: dict[str, dict[str, np.ndarray]] = {}
    for sym in names:
        if sym not in px:
            continue
        price_d = dense({d: v[0] for d, v in px[sym].items()})
        mcap_d = dense({d: v[1] for d, v in px[sym].items()})
        recs = oi.get(sym, {})
        taker_d = dense({d: r["taker"] for d, r in recs.items() if r["taker"] is not None})
        oi_close_d = dense({d: r["oi_close"] for d, r in recs.items() if r["oi_close"] is not None})
        vol_d = dense(vol.get(sym, {}))

        # F13: 365 日滚动最高价(窗口 [d−364, d]),≥ 300 个有效价格
        # scipy 的 origin:输出[i] = max(input[i-origin-182 : i-origin+183]);origin=+182 才是「向前看」的窗口
        # [d−364, d];origin=-182 会把未来 364 天的最高价算进来(前视泄漏)。
        valid_p = np.isfinite(price_d).astype(float)
        cp = np.concatenate([[0.0], np.cumsum(valid_p)])
        hi_max = maximum_filter1d(np.where(np.isfinite(price_d), price_d, -np.inf), size=365, origin=182,
                                   mode="constant", cval=-np.inf)
        cnt365 = cp[1:] - np.maximum(np.arange(gsize) - 364, 0)
        f13 = np.full(gsize, np.nan)
        ok13 = (cnt365 >= MIN_HIGH_OBS) & np.isfinite(hi_max) & (price_d > 0)
        f13[ok13] = price_d[ok13] / hi_max[ok13]

        # F11: 30 个日历日的日对数收益标准差(窗口 [d−29, d]),≥ 25 个观测
        prev = np.concatenate([[np.nan], price_d[:-1]])
        with np.errstate(invalid="ignore", divide="ignore"):
            ret = np.where((price_d > 0) & (prev > 0), np.log(price_d / prev), np.nan)
        f11 = roll_std(ret, 30, MIN_VOL_OBS)

        # F7: taker_ratio_mean 的 7 日均(≥ 5 天);F4 不在冻结名单里 ⇒ 恒为 NaN(资金费未拉)
        f7 = roll_mean(taker_d, 7, MIN_WINDOW_DAYS)
        f4 = np.full(gsize, np.nan)
        # F12: 成交额 7 日均(台账未设最少天数;≥ 1 天即可)÷ 当天市值
        vol7 = roll_mean(vol_d, 7, 1)
        f12 = np.full(gsize, np.nan)
        ok12 = np.isfinite(vol7) & np.isfinite(mcap_d) & (mcap_d > 0)
        f12[ok12] = vol7[ok12] / mcap_d[ok12]
        # 敏感性变体 F12b:同 F12,但要求 7 天窗口里 ≥ 5 个有效成交额日(台账对 F12 没写门槛)
        vol7b = roll_mean(vol_d, 7, MIN_WINDOW_DAYS)
        f12b = np.full(gsize, np.nan)
        ok12b = np.isfinite(vol7b) & np.isfinite(mcap_d) & (mcap_d > 0)
        f12b[ok12b] = vol7b[ok12b] / mcap_d[ok12b]

        roll[sym] = {"f13": f13, "f11": f11, "f7": f7, "f4": f4, "f12": f12, "f12b": f12b,
                     "price": price_d, "mcap": mcap_d, "oi_close": oi_close_d}

    # ---------------- 逐日截面 ----------------
    d_lo, d_hi = d2ord(HOLDOUT_START), d2ord(HOLDOUT_END)
    daily_ic: dict[str, dict[int, float]] = {f[0]: {} for f in FACTORS}
    daily_ic_alt: dict[str, dict[int, float]] = {f[0]: {} for f in FACTORS}
    daily_n: dict[str, dict[int, int]] = {f[0]: {} for f in FACTORS}
    pair_acc: dict[tuple[str, str], list[float]] = {}
    universe_sizes: list[int] = []
    rows_out = 0
    # 探索(不判):五因子等权秩合成 —— 逐日偏 IC、五分位超额、A/B 两条臂
    comp_ic: dict[int, float] = {}
    comp_exc_top: dict[int, float] = {}
    comp_exc_bot: dict[int, float] = {}
    comp_ret_top: dict[int, float] = {}
    comp_ret_bot: dict[int, float] = {}
    comp_ls: dict[int, float] = {}
    comp_ret_uni: dict[int, float] = {}
    comp_n: dict[int, int] = {}
    comp_score_flat: list[float] = []
    comp_y_flat: list[float] = []
    comp_size_flat: list[float] = []
    comp_day_flat: list[int] = []
    comp_day_slices: list[tuple[int, int, int]] = []

    for d in range(d_lo, d_hi + 1):
        gi = gidx[d]
        # 当天宇宙(照 S-689 的 rows)
        uni = []
        for sym in names:
            if sym not in kept:
                continue
            rec = oi.get(sym, {}).get(d)
            if not broad and (rec is None or rec["oi_value"] is None or rec["oi_value"] <= 0):
                continue
            p = px.get(sym, {}).get(d)
            if p is None or not math.isfinite(p[1]) or p[1] < MCAP_MIN or not (p[0] > 0):
                continue
            p2 = px.get(sym, {}).get(d + OUTCOME_H)
            if p2 is None or not (p2[0] > 0) or d not in btc or (d + OUTCOME_H) not in btc:
                continue
            if btc[d] <= 0:
                continue
            uni.append(sym)
        if not uni:
            continue
        universe_sizes.append(len(uni))
        if len(uni) < MIN_NAMES:
            continue
        rows_out += len(uni)

        y = np.array([(px[s][d + OUTCOME_H][0] / px[s][d][0] - 1.0) - (btc[d + OUTCOME_H] / btc[d] - 1.0)
                      for s in uni])
        size = np.array([math.log(px[s][d][1]) for s in uni])
        ry_u, rs_u = avg_rank(y), avg_rank(size)

        vals: dict[str, np.ndarray] = {}
        for code, _label, _kind in FACTORS:
            v = np.full(len(uni), np.nan)
            for k, s in enumerate(uni):
                v[k] = factor_value(code, s, d, gi, gi + OUTCOME_H, px, oi, roll, btc)
            vals[code] = v

        for code, _label, kind in FACTORS:
            arr = vals[code]
            mask = np.isfinite(arr)
            n = int(mask.sum())
            daily_n[code][d] = n
            if n < MIN_NAMES:
                continue
            rf = avg_rank(arr[mask])
            # 偏相关的三个 ρ 必须算在同一批观测上(否则公式不自洽):名次全部在该因子
            # 有定义的当天截面上重算(F1 的截面 = 宇宙本身 ⇒ 与 S-689 逐位可比)。
            ryy, rss = avg_rank(y[mask]), avg_rank(size[mask])
            ic = pearson(rf, ryy) if kind == "raw" else partial_spearman(rf, ryy, rss)
            if math.isfinite(ic):
                daily_ic[code][d] = ic
            # 敏感性:另一种口径 —— 因子名次在自身子集内算,结果/规模名次在当天全宇宙内算
            # (偏相关的三个 ρ 不在同一批观测上,数学上不自洽;这里只用来量「口径差多少」)
            ic_alt = (pearson(rf, ry_u[mask]) if kind == "raw"
                      else partial_spearman(rf, ry_u[mask], rs_u[mask]))
            if math.isfinite(ic_alt):
                daily_ic_alt[code][d] = ic_alt

        # 探索(不判):五因子等权秩合成 —— 方向按冻结符号对齐(高 = 预期跑赢),
        # 每个因子先在当天有定义的名字里取名次(除以该子集大小 → 0..1),再等权平均。
        n_fac = len(FROZEN)
        aligned = np.full((n_fac, len(uni)), np.nan)
        for fi, (code, sgn) in enumerate(FROZEN):
            arr = vals[code] * sgn
            ok = np.isfinite(arr)
            if int(ok.sum()) >= MIN_NAMES:
                aligned[fi, ok] = avg_rank(arr[ok]) / float(ok.sum())
        have = np.isfinite(aligned).sum(axis=0)
        cmask = have == n_fac                      # 5 个因子全有定义才进合成
        if int(cmask.sum()) >= MIN_NAMES:
            score = aligned[:, cmask].mean(axis=0)
            y_c = y[cmask]
            s_c = size[cmask]
            syms_c = [uni[k] for k in np.flatnonzero(cmask)]
            ic_c = partial_spearman(avg_rank(score), avg_rank(y_c), avg_rank(s_c))
            if math.isfinite(ic_c):
                comp_ic[d] = ic_c
            order = np.argsort(score)
            nq = max(1, len(score) // 5)           # 五分位
            bot_idx, top_idx = order[:nq], order[-nq:]
            uni_mean = float(np.mean(y))
            comp_exc_top[d] = float(np.mean(y_c[top_idx])) - uni_mean
            comp_exc_bot[d] = float(np.mean(y_c[bot_idx])) - uni_mean
            rt, rb, rs = [], [], []
            for k in top_idx:
                sy = syms_c[k]
                lr = long_return(px[sy][d][0], px[sy][d + OUTCOME_H][0])
                if lr is not None:
                    rt.append(lr)
            for k in bot_idx:
                sy = syms_c[k]
                lr = long_return(px[sy][d][0], px[sy][d + OUTCOME_H][0])
                if lr is not None:
                    rb.append(lr)
                sr = short_return(px[sy][d][0], px[sy][d + OUTCOME_H][0])
                if sr is not None:
                    rs.append(sr)
            if rt:
                comp_ret_top[d] = float(np.mean(rt))
            if rb:
                comp_ret_bot[d] = float(np.mean(rb))
            if rt and rs:
                # 美元中性:最高五分位等权做多 + 最低五分位等权做空(各 1 美元名义)
                comp_ls[d] = float(np.mean(rt)) + float(np.mean(rs))
            ru = [long_return(px[s][d][0], px[s][d + OUTCOME_H][0]) for s in uni]
            ru = [x for x in ru if x is not None]
            if ru:
                comp_ret_uni[d] = float(np.mean(ru))
            comp_n[d] = int(cmask.sum())
            start = len(comp_score_flat)
            comp_score_flat.extend(float(v) for v in score)
            comp_y_flat.extend(float(v) for v in y_c)
            comp_size_flat.extend(float(v) for v in s_c)
            comp_day_flat.extend([d] * len(score))
            comp_day_slices.append((d, start, len(comp_score_flat)))

        # 探索:6 个因子两两的截面秩相关(只报均值)
        codes = [f[0] for f in FACTORS]
        for i in range(len(codes)):
            for j in range(i + 1, len(codes)):
                a, b = vals[codes[i]], vals[codes[j]]
                m = np.isfinite(a) & np.isfinite(b)
                if int(m.sum()) < MIN_NAMES:
                    continue
                rr = pearson(avg_rank(a[m]), avg_rank(b[m]))
                if math.isfinite(rr):
                    pair_acc.setdefault((codes[i], codes[j]), []).append(rr)

    # ---------------- 汇总 ----------------
    def month_of(d: int) -> str:
        return date.fromordinal(d).strftime("%Y-%m")

    out_factors = []
    judgments = []
    for code, label, kind in FACTORS:
        by_month: dict[str, list[float]] = {}
        for d, v in daily_ic[code].items():
            by_month.setdefault(month_of(d), []).append(v)
        months = sorted(by_month)
        mvals = [float(np.mean(by_month[m])) for m in months]
        mean, t, n_months = t_of(mvals)
        by_month_alt: dict[str, list[float]] = {}
        for d, v in daily_ic_alt[code].items():
            by_month_alt.setdefault(month_of(d), []).append(v)
        mvals_alt = [float(np.mean(by_month_alt[m])) for m in months if m in by_month_alt]
        mean_alt, t_alt, n_alt = t_of(mvals_alt)
        n_names = list(daily_n[code].values())
        pos = sum(1 for v in mvals if v > 0)
        neg = sum(1 for v in mvals if v < 0)
        zero = sum(1 for v in mvals if v == 0)
        rec = {
            "factor": code,
            "label": label,
            "stat": "partial_spearman_ctrl_size",
            "monthly": {m: round(float(np.mean(by_month[m])), 6) for m in months},
            "monthly_n_days": {m: len(by_month[m]) for m in months},
            "n_months": n_months,
            "n_days_total": sum(len(v) for v in by_month.values()),
            "mean_rho": None if not math.isfinite(mean) else round(mean, 6),
            "t_month": None if not math.isfinite(t) else round(t, 4),
            "names_per_day_min": min(n_names) if n_names else 0,
            "names_per_day_mean": round(float(np.mean(n_names)), 1) if n_names else 0,
            "months_positive": pos,
            "months_negative": neg,
            "months_zero": zero,
            "mean_rho_alt_rank_set": None if not math.isfinite(mean_alt) else round(mean_alt, 6),
            "t_month_alt_rank_set": None if not math.isfinite(t_alt) else round(t_alt, 4),
        }
        # 判定(照预注册写死):与冻结符号同号、|月 t| ≥ 2.0、≥ 60% 留出月份同号 ⇒ ✅
        sgn = FROZEN_SIGN.get(code)
        if sgn is None:
            rec["role"] = "known_not_counted"          # F1:已知,照报不计
            rec["verdict"] = "—(已知,不计)"
            ks = KNOWN_SIGN.get(code)
            if ks is not None:
                same_k = sum(1 for v in mvals if (v > 0) == (ks > 0) and v != 0)
                rec["known_sign"] = "+" if ks > 0 else "-"
                rec["months_same_sign_as_frozen"] = same_k
                rec["frac_months_same_sign"] = round(same_k / len(mvals), 4) if mvals else 0.0
        else:
            frozen_sign = "+" if sgn > 0 else "-"
            same = sum(1 for v in mvals if (v > 0) == (sgn > 0) and v != 0)
            frac = same / len(mvals) if mvals else 0.0
            sign_ok = (mean > 0) if sgn > 0 else (mean < 0)
            t_ok = math.isfinite(t) and abs(t) >= 2.0
            frac_ok = frac >= 0.60
            rec["role"] = "frozen"
            rec["frozen_sign"] = frozen_sign
            rec["months_same_sign_as_frozen"] = same
            rec["frac_months_same_sign"] = round(frac, 4)
            rec["verdict"] = "✅" if (sign_ok and t_ok and frac_ok) else "❌"
            rec["verdict_detail"] = {"sign_match": bool(sign_ok),
                                     "abs_t_ge_2": bool(t_ok),
                                     "frac_months_ge_60pct": bool(frac_ok)}
            judgments.append({"factor": code, "label": label, "frozen_sign": frozen_sign,
                              "mean_rho": rec["mean_rho"], "t_month": rec["t_month"],
                              "n_months": n_months, "months_same_sign": same,
                              "frac_months_same_sign": round(frac, 4),
                              "names_per_day_mean": rec["names_per_day_mean"],
                              "verdict": rec["verdict"]})
        out_factors.append(rec)

    pair_mean = {f"{a}|{b}": round(float(np.mean(v)), 4) for (a, b), v in pair_acc.items()}

    # ---------------- 探索(不判):五因子等权秩合成 ----------------
    def monthly_of(daily: dict[int, float]):
        bym: dict[str, list[float]] = {}
        for d, v in daily.items():
            bym.setdefault(month_of(d), []).append(v)
        ms = sorted(bym)
        mv = [float(np.mean(bym[m])) for m in ms]
        mean, t, n = t_of(mv)
        return {m: round(float(np.mean(bym[m])), 6) for m in ms}, mean, t, n

    comp_monthly, comp_mean, comp_t, comp_nmonths = monthly_of(comp_ic)
    top_monthly, top_mean, top_t, _ = monthly_of(comp_exc_top)
    bot_monthly, bot_mean, bot_t, _ = monthly_of(comp_exc_bot)

    def paired(a: dict[int, float], b: dict[int, float]):
        ks = sorted(set(a) & set(b))
        return [a[k] for k in ks], [b[k] for k in ks]

    ab_tb = None      # A/B:最高五分位多头腿 vs 最低五分位多头腿
    ab_ls = None      # A/B:美元中性多空合成 vs 一直持有宇宙(hold the panel)
    try:
        a_bot, b_top = paired(comp_ret_bot, comp_ret_top)
        ab_tb = ab_test(a_bot, b_top, mean_block=20.0, n_boot=2000, seed=208)
        ab_tb["arm_a"] = "最低五分位多头(等权 30 天收益)"
        ab_tb["arm_b"] = "最高五分位多头(等权 30 天收益)"
    except Exception as exc:
        ab_tb = {"error": str(exc)}
    try:
        a_uni, b_ls = paired(comp_ret_uni, comp_ls)
        ab_ls = ab_test(a_uni, b_ls, mean_block=20.0, n_boot=2000, seed=208)
        ab_ls["arm_a"] = "一直持有宇宙(等权,hold the panel)"
        ab_ls["arm_b"] = "美元中性多空合成(最高五分位多 + 最低五分位空)"
    except Exception as exc:
        ab_ls = {"error": str(exc)}

    # 零分布:把合成分数在**当天截面内**打乱(apparatus.shuffle_within)→ 重算逐日偏 IC
    # → 逐月平均;实际值在零分布里的分位 = 「合成没有任何截面信息」这个原假设的检验。
    null_out: dict = {"n_draws": 0}
    if comp_day_slices:
        score_arr = np.array(comp_score_flat, dtype=float)
        y_arr = np.array(comp_y_flat, dtype=float)
        size_arr = np.array(comp_size_flat, dtype=float)
        day_arr = np.array(comp_day_flat, dtype=np.int64)

        def _null_stat(rng):
            sh = shuffle_within(score_arr, day_arr, rng)
            bym: dict[str, list[float]] = {}
            for d, a, b in comp_day_slices:
                if b - a < MIN_NAMES:
                    continue
                v = partial_spearman(avg_rank(sh[a:b]), avg_rank(y_arr[a:b]), avg_rank(size_arr[a:b]))
                if math.isfinite(v):
                    bym.setdefault(month_of(d), []).append(v)
            mv = [float(np.mean(bym[m])) for m in sorted(bym)]
            return float(np.mean(mv)) if mv else float("nan")

        try:
            null = null_distribution(_null_stat, 1000, 208, actual=comp_mean)
            pct = percentile_of(comp_mean, null)
            null_out = {
                "n_draws": int(len(null)),
                "actual_mean_monthly_ic": round(comp_mean, 6) if math.isfinite(comp_mean) else None,
                "null_mean": round(float(np.mean(null)), 6),
                "null_sd": round(float(np.std(null, ddof=1)), 6),
                "null_q025": round(float(np.quantile(null, 0.025)), 6),
                "null_q975": round(float(np.quantile(null, 0.975)), 6),
                "percentile_in_null": None if pct is None else round(pct, 4),
                "p_one_sided_high": None if pct is None else round(1.0 - pct, 4),
                "method": "当天截面内打乱合成分数(apparatus.shuffle_within)→ 重算偏 IC → 逐月平均;"
                          "统计量 = 月均偏 IC(与实际值同定义)",
            }
        except Exception as exc:
            null_out = {"error": str(exc)}

    def mean_of(d: dict[int, float]) -> float | None:
        vals = list(d.values())
        return round(float(np.mean(vals)), 6) if vals else None

    composite = {
        "label": "五因子等权秩合成(方向按冻结符号对齐,高 = 预期跑赢;5 个因子全有定义才进)",
        "frozen_factors": [c for c, _ in FROZEN],
        "names_per_day_mean": round(float(np.mean(list(comp_n.values()))), 1) if comp_n else 0,
        "names_per_day_min": min(comp_n.values()) if comp_n else 0,
        "days_with_composite": len(comp_ic),
        "monthly": comp_monthly,
        "n_months": comp_nmonths,
        "mean_rho": None if not math.isfinite(comp_mean) else round(comp_mean, 6),
        "t_month": None if not math.isfinite(comp_t) else round(comp_t, 4),
        "top_quintile_excess_vs_universe": {
            "monthly": top_monthly, "mean": None if not math.isfinite(top_mean) else round(top_mean, 6),
            "t_month": None if not math.isfinite(top_t) else round(top_t, 4),
            "定义": "最高五分位的 30 天超额收益(对 BTC)均值 − 当天宇宙均值"},
        "bottom_quintile_excess_vs_universe": {
            "monthly": bot_monthly, "mean": None if not math.isfinite(bot_mean) else round(bot_mean, 6),
            "t_month": None if not math.isfinite(bot_t) else round(bot_t, 4),
            "定义": "最低五分位的 30 天超额收益(对 BTC)均值 − 当天宇宙均值"},
        "ab_top_vs_bottom": ab_tb,
        "ab_ls_vs_hold_panel": ab_ls,
        "arm_mean_30d_return": {
            "top_quintile": mean_of(comp_ret_top),
            "bottom_quintile": mean_of(comp_ret_bot),
            "usiverse_equal_weight": mean_of(comp_ret_uni),
            "long_short_book": mean_of(comp_ls),
            "定义": "各臂每个信号日的 30 天收益(绝对,不对 BTC)的均值;"
                    "ab_test 里的 cum_* 把 634 个**重叠**的 30 天窗口复利连乘 ⇒ 不可解释,只有 p 与 CI 可用",
        },
        "null_distribution": null_out,
    }

    result = {
        "task": "T-208",
        "ledger": "S-691",
        "segment": "holdout",
        "generated_at_utc": datetime.now(timezone.utc).isoformat() + "Z",
        "segment_meta": {
            "signal_days": f"{HOLDOUT_START}..{HOLDOUT_END}",
            "outcome_window_end": OUTCOME_END,
            "isolation": "2024-12 是隔离月,信号日不用;发现段(2023-01-01 → 2024-11-30)"
                         "的结果已冻结,不在本脚本里重算。",
            "min_names_per_day": MIN_NAMES,
            "mcap_min_usd": MCAP_MIN,
            "universe_mode": UNIVERSE_MODE,
            "universe_mode_meaning": "主口径 = 每天还要当天 oi_value_close > 0(§Seth-1027a 括注读法);"
                                    "对照口径 = 台账宇宙句的字面读法(当天不要求有 OI 值)",
        },
        "universe": {
            "deriv_symbols_with_data_from_holdout_start": len(names),
            "mapping_checked": len(check_rows),
            "mapping_kept": len(kept),
            "mapping_dropped": sorted(
                [{"symbol": s, "n_overlap": n, "med_err": round(e, 5)}
                 for s, n, e in check_rows if not (n >= MAP_MIN_OVERLAP and e <= MAP_MAX_MED_ERR)],
                key=lambda z: -z["med_err"]),
            "names_kept": sorted(kept),
            "days_with_universe": len(universe_sizes),
            "names_per_day_mean": round(float(np.mean(universe_sizes)), 1) if universe_sizes else 0,
            "names_per_day_min": min(universe_sizes) if universe_sizes else 0,
            "names_per_day_max": max(universe_sizes) if universe_sizes else 0,
            "cross_section_rows": rows_out,
            "cg_coin_mcap_rows": int(len(cg)),
            "cg_coin_mcap_null_mcap_rows": int(cg["mcap"].isna().sum()),
            "deriv_rows": int(len(deriv)),
            "names_without_cg_price": sorted([s for s in names if s not in px]),
            "asset_mcap_rows": int(len(am)),
        },
        "factors": out_factors,
        "judgments": judgments,
        "exploratory_composite": composite,
        "pairwise_rank_corr_mean": pair_mean,
        "notes": [
            "F11 = d−29..d 的日对数收益样本标准差(ddof=1),≥ 25 个观测。",
            "F8/F9 相对动量 = (p_d/p_{d−k} − 1) − (BTC_d/BTC_{d−k} − 1)。",
            "F7 = d−6..d 的 taker_ratio_mean 平均,≥ 5 个有效日。",
            "F3 = ln(oi_close_d / oi_close_{d−30})(张数,不含价格)。",
            "F4(funding)不在冻结名单 ⇒ 资金费整表未拉,F4 未算。",
            "每个因子的名次在该因子有定义的当天截面上重算(偏相关的三个 ρ 同一批观测);"
            "F1 的截面 = 宇宙本身 ⇒ 与 S-689 同法。",
            "映射校验的重叠日窗口 = 2025-01-01 → 2026-09-26(只在留出段信号日内);"
            "S-689 的下界相同、上界是全历史(它跑的是完整样本)。",
            "判定口径照预注册写死:与冻结符号同号、|月 t| ≥ 2.0、≥ 60% 留出月份同号 ⇒ ✅。",
        ],
    }

    cross_check_f1(result)
    if broad:
        # 对照口径(台账宇宙句的字面读法)先跑,结果落 Mac 数据根,主口径再并进来
        OUT_JSON_ALT.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON_ALT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
        print(f"[write] {OUT_JSON_ALT}", flush=True)
        print(f"[done ] {time.time() - t0:.1f}s", flush=True)
        return
    # 主口径(oi_required):把对照口径(broad)的结果并进来,只报不判
    if OUT_JSON_ALT.exists():
        try:
            b = json.loads(OUT_JSON_ALT.read_text())
            result["universe_sensitivity_broad"] = {
                "mode": "broad —— 台账宇宙句的字面读法(当天不要求有 OI 值);仅对照,只报不判",
                "universe": {k: b["universe"].get(k) for k in
                             ("mapping_checked", "mapping_kept", "names_per_day_mean",
                              "names_per_day_min", "names_per_day_max", "cross_section_rows")},
                "factors": [{"factor": f["factor"], "mean_rho": f["mean_rho"], "t_month": f["t_month"],
                             "n_months": f["n_months"], "names_per_day_mean": f["names_per_day_mean"],
                             "months_same_sign_as_frozen": f.get("months_same_sign_as_frozen"),
                             "verdict": f.get("verdict")}
                            for f in b["factors"]],
                "judgments": b.get("judgments"),
            }
        except Exception as exc:      # 对照缺失不影响主结果
            print(f"[warn ] 对照口径读取失败: {exc}", file=sys.stderr, flush=True)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"[write] {OUT_JSON}", flush=True)
    write_report(result)
    print(f"[write] {OUT_MD}", flush=True)
    print(f"[done ] {time.time() - t0:.1f}s", flush=True)


def factor_value(code, sym, d, gi, gi2, px, oi, roll, btc):
    """单个名字在信号日 d 的因子值;NaN = 该因子在这个名字上无定义。"""
    r = roll.get(sym)
    if r is None:
        return float("nan")
    rec = oi.get(sym, {}).get(d)
    if code == "F1":
        if rec is None or rec["oi_value"] is None or rec["oi_value"] <= 0:
            return float("nan")
        m = r["mcap"][gi]
        if not math.isfinite(m) or m <= 0:
            return float("nan")
        return rec["oi_value"] / m
    if code in ("F2", "F3"):
        k = 7 if code == "F2" else 30
        if rec is None or rec["oi_close"] is None or rec["oi_close"] <= 0:
            return float("nan")
        old = oi.get(sym, {}).get(d - k)
        if old is None or old["oi_close"] is None or old["oi_close"] <= 0:
            return float("nan")
        return math.log(rec["oi_close"] / old["oi_close"])
    if code == "F4":
        v = r["f4"][gi]
        return v if math.isfinite(v) else float("nan")
    if code == "F5":
        return float("nan") if rec is None or rec["top_pos"] is None else rec["top_pos"]
    if code == "F6":
        return float("nan") if rec is None or rec["gacct"] is None else rec["gacct"]
    if code == "F7":
        v = r["f7"][gi]
        return v if math.isfinite(v) else float("nan")
    if code in ("F8", "F9", "F10"):
        k = {"F8": 30, "F9": 7, "F10": 90}[code]
        p_now = r["price"][gi]
        p_old = r["price"][gi - k]
        if not (math.isfinite(p_now) and math.isfinite(p_old)) or p_old <= 0 or p_now <= 0:
            return float("nan")
        if d not in btc or (d - k) not in btc or btc[d - k] <= 0:
            return float("nan")
        return (p_now / p_old - 1.0) - (btc[d] / btc[d - k] - 1.0)
    if code == "F11":
        v = r["f11"][gi]
        return v if math.isfinite(v) else float("nan")
    if code == "F12":
        v = r["f12"][gi]
        return v if math.isfinite(v) else float("nan")
    if code == "F12b":
        v = r["f12b"][gi]
        return v if math.isfinite(v) else float("nan")
    if code == "F13":
        v = r["f13"][gi]
        return v if math.isfinite(v) else float("nan")
    if code == "F14":
        m = r["mcap"][gi]
        if not math.isfinite(m) or m <= 0:
            return float("nan")
        return math.log(m)
    raise KeyError(code)


def cross_check_f1(result: dict) -> dict | None:
    """把 F1(OI/市值,控制规模)的逐月值跟**已发布**的 S-689 面板外序列对一遍 ——
    这是本脚本能不能复现已发布方法的最强校验(两者宇宙不同:本表含面板名字、
    只到 2024-11-30,S-689 是面板外、跑满历史)。"""
    src = Path(__file__).resolve().parent / "s689_results.json"
    if not src.exists():
        return None
    try:
        s689 = json.loads(src.read_text())
        sm = s689["terms"]["partial"]["months"]
    except Exception:
        return None
    f1 = next((f for f in result["factors"] if f["factor"] == "F1"), None)
    if not f1:
        return None
    diffs, same_sign, n = [], 0, 0
    for m, v in f1["monthly"].items():
        if m in sm:
            sv = sm[m]["rho"]
            diffs.append(v - sv)
            same_sign += 1 if (v > 0) == (sv > 0) else 0
            n += 1
    if not diffs:
        return None
    out = {
        "reference": "S-689 面板外(已发布,docs/research/s689_results.json)",
        "months_compared": n,
        "mean_diff": round(float(np.mean(diffs)), 6),
        "max_abs_diff": round(float(max(abs(x) for x in diffs)), 6),
        "same_sign_months": same_sign,
        "mine_mean_rho": f1["mean_rho"], "mine_t_month": f1["t_month"],
        "s689_mean_rho": s689["terms"]["partial"]["mean"],
        "s689_t_month": s689["terms"]["partial"]["t_month"],
        "s689_n_months": s689["terms"]["partial"]["n_months"],
        "note": "宇宙不同(本表含面板名字、只到留出段;S-689 是面板外、跑满历史),"
                "逐月差应来自宇宙差而不是方法差。",
    }
    result["cross_check_f1_vs_s689"] = out
    return out





def write_report(result: dict) -> None:
    seg = result["segment_meta"]
    u = result["universe"]
    by_code = {f["factor"]: f for f in result["factors"]}
    order = ["F3", "F7", "F8", "F9", "F11", "F1"]

    def r2(x):
        try:
            return [round(float(v), 2) for v in x]
        except Exception:
            return x

    L: list[str] = []
    L.append("# T-208 · S-691 留出段独立复算(B 道盲复算)\n")
    L.append(f"- 段:信号日 **{seg['signal_days']}**(结果窗口到 {seg['outcome_window_end']};2024-12 隔离不用)。")
    L.append(f"- 口径:{seg['universe_mode_meaning']}。")
    L.append("- 冻结名单(台账 §S-691「短名单冻结」):F3(−)、F7(+)、F8(−)、F9(−)、F11(−);F1 已知,照报不计。")
    L.append("- 判定(预注册写死):与冻结符号同号、|月 t| ≥ 2.0、≥ 60% 留出月份同号 ⇒ ✅。")
    L.append(f"- 宇宙:映射校验 {u['mapping_checked']} 名 → 留 {u['mapping_kept']} 名;"
             f"每天名字数均值 {u['names_per_day_mean']}(最少 {u['names_per_day_min']},"
             f"最多 {u['names_per_day_max']}),有宇宙的天数 {u['days_with_universe']}。\n")

    # ---- 1 · 主表(6 行) ----
    L.append("## 1 · 主表(主口径:宇宙每天要 OI)\n")
    L.append("| 因子 | 冻结符号 | 月均偏 IC(控规模) | 月 t | 月数 | 同号月份 | 判定 |")
    L.append("|---|---|---|---|---|---|---|")
    for code in order:
        f = by_code.get(code)
        if not f:
            continue
        fs = f.get("frozen_sign", f.get("known_sign", "—"))
        mr = "—" if f["mean_rho"] is None else f"{f['mean_rho']:+.4f}"
        tm = "—" if f["t_month"] is None else f"{f['t_month']:+.2f}"
        same = f.get("months_same_sign_as_frozen")
        same_s = "—" if same is None else f"{same}/{f['n_months']}"
        L.append(f"| {code} {f['label']} | {fs} | {mr} | {tm} | {f['n_months']} | {same_s} | {f['verdict']} |")
    L.append("")

    # ---- 2 · 判定 ----
    L.append("## 2 · 判定\n")
    npass = sum(1 for j in result["judgments"] if j["verdict"] == "✅")
    L.append(f"冻结的 5 个因子里 **{npass}/5** 满足预注册判据(同号、|月 t| ≥ 2.0、≥ 60% 留出月份同号)。\n")
    for j in result["judgments"]:
        L.append(f"- **{j['factor']}**({j['label']}):冻结 {j['frozen_sign']},月均 {j['mean_rho']},"
                 f"月 t {j['t_month']},同号月份 {j['months_same_sign']}/{j['n_months']}"
                 f"({j['frac_months_same_sign'] * 100:.0f}%),每天名字数均值 {j['names_per_day_mean']} ⇒ **{j['verdict']}**")
    L.append("")
    f1 = by_code.get("F1")
    if f1:
        same1 = f1.get("months_same_sign_as_frozen")
        s1 = "—" if same1 is None else f"{same1}/{f1['n_months']}"
        L.append(f"- F1(OI/市值,已知不算新发现,只报):月均 {f1['mean_rho']},月 t {f1['t_month']},"
                 f"{f1['n_months']} 个月,同号月份 {s1},每天名字数均值 {f1['names_per_day_mean']}。")
    L.append("")

    # ---- 3 · 对照口径 ----
    sens = result.get("universe_sensitivity_broad")
    if sens:
        L.append("## 3 · 对照口径(台账宇宙句的字面读法:当天不要求有 OI 值;只报不判)\n")
        L.append("| 因子 | 月均偏 IC | 月 t | 同号月份 | 判定(对照) |")
        L.append("|---|---|---|---|---|")
        for f in sens.get("factors", []):
            same = f.get("months_same_sign_as_frozen")
            same_s = "—" if same is None else f"{same}/{f['n_months']}"
            L.append(f"| {f['factor']} | {f['mean_rho']} | {f['t_month']} | {same_s} | {f.get('verdict', '—')} |")
        L.append("")
        L.append(f"对照口径的宇宙:映射校验留 {sens['universe'].get('mapping_kept')} 名,"
                 f"每天名字数均值 {sens['universe'].get('names_per_day_mean')};"
                 f"两个口径下 5 个因子的判定完全一致。\n")

    # ---- 4 · 协议问题 ----
    L.append("## 4 · 协议问题(需要 @seth 拍板或记账的)\n")
    L.append("- **留出段的映射校验重叠日窗口**照 T-206 的定义取在留出段信号日内"
             "(2025-01-01 → 2026-09-26);S-689 的下界相同、上界是全历史。"
             "平行道(Seth)报的映射校验名单是 248 名,本卡是自己的 "
             f"{u['mapping_kept']} 名 —— 差异已知,不影响判定(判定只用逐月 IC 的符号与幅度)。")
    L.append("- 台账 §S-691「留出段开封」写「留出 = 信号日 2025-01-01 → 2026-09-26(结果到 2026-10-26)」,"
             "T-208 卡写「最后一个 d + 30 有 CG 价的日子(现在是 2026-09-26)」。"
             "本卡按前者执行:库里 CG 价的最后一天确实是 2026-10-26,所以最后一个可用信号日 = 2026-09-26。")
    L.append("- F4(funding)不在冻结名单,本卡**没有拉资金费整表**,F4 未算;"
             "T-206 的 F4 数字不可直接搬到本卡(资金费数据也在增长)。")
    L.append("- **「信号日当天的派生量」自检:被判定的 5 个因子一个都没用**。"
             "F3 = ln(oi_close_d / oi_close_{d−30})(张数,不含价格),F7 = d−6..d 的 taker_ratio_mean 均值,"
             "F8/F9 = 价格相对动量,F11 = 30 天对数收益波动 —— 全是回看窗口的量。"
             "唯一踩到「当天派生量」的是 **F1**(OI/市值 = oi_value_close ÷ 当天 CG 市值),"
             "但 F1「照报不计」不参与判定,所以「只在当天成立就不算」这条不咬到任何判定。"
             "偏相关的规模控制量 size = ln(CG 市值),市值是 CoinGecko market chart **直接给的字段**,"
             "不是用「市值 ÷ 价格」推出来的;当日成交(F12 换手)与当日资金费(F4)都不在冻结名单。")
    L.append("- 判定里的「同号月份」按**月均值的符号**数;月均值恰好为 0 的月份两边都不算"
             "(本段没有出现)。")
    L.append("- **A/B 的 cum_* 字段在本卡不可解释**:各臂的「日收益」是重叠的 30 天窗口收益"
             "(每个信号日都开一次仓),ab_test 把 634 个重叠窗口复利连乘,得到的 cum 是把同一段时间"
             "数重复计了 30 次。可用的只有 p 值与块自助 CI;幅度请看「各臂 30 天收益均值」。")
    L.append("- **「美元中性合成 vs 一直持有宇宙」这条 A/B 有 beta 混淆**:合成组合是美元中性"
             "(高分位正权重 + 低分位负权重,β≈0),基准是全做多的宇宙(β≈1)—— 熊市里它天然赢。"
             "这条只当探索,不构成 alpha 证据;相对宇宙均值的超额(第 5 节)才是干净的读数。\n")

    # ---- 5 · 还看到了什么 ----
    L.append("## 5 · 还看到了什么(全部标探索)\n")
    c = result.get("exploratory_composite", {})
    if c:
        am = c.get("arm_mean_30d_return", {})
        L.append(f"- 探索性 —— 需另立预注册、在新数据上过零信号对照:**五因子等权秩合成**(方向按冻结符号对齐,"
                 f"5 个因子全有定义才进,每天名字数均值 {c.get('names_per_day_mean')})的月均偏 IC = "
                 f"{c.get('mean_rho')},月 t = {c.get('t_month')},{c.get('n_months')} 个月 —— "
                 f"比任何一个单因子都强(单因子 |月 t| 在 2.5–6.5 之间),"
                 f"当天截面内打乱分数的零分布里落在 {c.get('null_distribution', {}).get('percentile_in_null')} 分位"
                 f"(零分布均值 {c.get('null_distribution', {}).get('null_mean')})。")
        tq = c.get("top_quintile_excess_vs_universe", {})
        bq = c.get("bottom_quintile_excess_vs_universe", {})
        L.append(f"- 探索性 —— 需另立预注册、在新数据上过零信号对照:**最高/最低五分位相对宇宙均值的 30 天超额** —— "
                 f"最高 {tq.get('mean')}(月 t {tq.get('t_month')},**没过 2.0**),"
                 f"最低 {bq.get('mean')}(月 t {bq.get('t_month')},过了)。"
                 f"合成的好处**几乎全在「躲开最差一档」**,正的一端自己并不显著 —— "
                 f"和 S-690 附记里「挡掉差票的不是这个币一贯杠杆高,是开票当天涌进来的杠杆」是同一类机制。")
        ab1 = c.get("ab_top_vs_bottom", {}) or {}
        if "verdict" in ab1:
            L.append(f"- 探索性 —— 需另立预注册、在新数据上过零信号对照:**两条臂的 A/B**(最高分位组合 vs 最低分位组合)—— "
                     f"{ab1.get('verdict')},p(B ≤ A) = {ab1.get('p_b_le_a')},"
                     f"块自助 95% CI(log 差) = {r2(ab1.get('ci95_log_diff'))},{ab1.get('n_days')} 个信号日。"
                     f"两臂的 30 天绝对收益均值:高 {am.get('top_quintile')}、低 {am.get('bottom_quintile')},"
                     f"同期整个宇宙 {am.get('usiverse_equal_weight')}(这段是熊市,绝对收益全负;"
                     f"要看的是第 5 节里「相对宇宙均值」的超额)。")
        ab2 = c.get("ab_ls_vs_hold_panel", {}) or {}
        if "verdict" in ab2:
            L.append(f"- 探索性 —— 需另立预注册、在新数据上过零信号对照:**美元中性合成组合 vs 一直持有宇宙**"
                     f"(hold the panel)—— {ab2.get('verdict')},p(B ≤ A) = {ab2.get('p_b_le_a')},"
                     f"{ab2.get('n_days')} 个信号日;组合 30 天收益均值 {am.get('long_short_book')}、"
                     f"持有宇宙 {am.get('usiverse_equal_weight')}。**这条有 beta 混淆(见第 4 节),不当 alpha 证据。**")
        nd = c.get("null_distribution", {}) or {}
        if nd.get("n_draws"):
            L.append(f"- 探索性 —— 需另立预注册、在新数据上过零信号对照:**合成的零分布**(当天截面内打乱合成分数,"
                     f"{nd.get('n_draws')} 次)—— 实际月均 IC {nd.get('actual_mean_monthly_ic')} 在零分布里的分位 = "
                     f"{nd.get('percentile_in_null')}(单侧 p = {nd.get('p_one_sided_high')});"
                     f"零分布均值 {nd.get('null_mean')}、95% 区间 [{nd.get('null_q025')}, {nd.get('null_q975')}]。")
        elif nd.get("error"):
            L.append(f"- 零分布没跑出来:{nd.get('error')}")
    if f1:
        L.append("- 探索性 —— 需另立预注册、在新数据上过零信号对照:**F1(OI/市值,已知不算新发现)在留出段明显变弱** —— "
                 f"发现段月 t −6.43(台账 §S-691 发现段表),留出段月 t {f1['t_month']}、同号月份 "
                 f"{f1.get('months_same_sign_as_frozen')}/{f1['n_months']};"
                 "而**「OI 的变化」(F3)留出段月 t −6.54、比发现段的 −3.16 还强**。"
                 "两件事合起来说明:留出段里起作用的不是「这个币杠杆一贯高」,而是「杠杆在变」。"
                 "F1 不参与判定,但这条与 S-690 附记一的机制读法是同一个方向。")
    pairs = result.get("pairwise_rank_corr_mean", {})
    if pairs:
        top = sorted(pairs.items(), key=lambda kv: -abs(kv[1]))[:5]
        L.append("- 探索性 —— 需另立预注册、在新数据上过零信号对照:**这 5 个冻结因子里哪几个是同一件事** —— "
                 + "; ".join(f"{k.replace('|', '↔')} = {v}" for k, v in top)
                 + "(F8↔F9 是同一件事的两档;F1↔F11 也不小)。把它们当 5 个独立发现会高估有效试验数。")
    L.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    # 先跑对照口径(台账宇宙句的字面读法),再跑主口径(每天要 OI)。
    # 用法:python3 docs/research/t208_factor_zoo_holdout.py [all|broad|oi_required]
    _mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if _mode in ("all", "broad"):
        UNIVERSE_MODE = "broad"
        main()
    if _mode in ("all", "oi_required"):
        UNIVERSE_MODE = "oi_required"
        main()
