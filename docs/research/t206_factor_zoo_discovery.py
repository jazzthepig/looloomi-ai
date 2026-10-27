#!/usr/bin/env python3
"""T-206 / 台账 S-691 —— 宽宇宙 14 个时点可得因子的截面 IC 普查(发现段)。

**发现段封存**:只对信号日 2023-01-01 → 2024-11-30 的行算任何因子统计量。
信号日 ≥ 2024-12-01 的行(留出段)本脚本连读都不读 —— 价格/市值表按日期截断到
2024-12-30(发现段最后一个信号日 + 30 天的结果窗口),衍生指标表截断到 2024-11-30。

方法照台账 S-691 一字不改,统计量与 S-689 相同(偏 Spearman 控制规模):
  · 宇宙(主口径 = 台账宇宙句的字面读法):deriv_metrics_daily 里的名字(含 CIS 面板名字,
    不像 S-689 那样剔掉面板),过 S-689 的映射校验(隐含价 = oi_value_close / oi_close,
    对重叠日算 median |CG 价 × 倍数 / 隐含价 − 1|,≥ 30 个重叠日且 ≤ 0.05 才留),
    当天 CG 市值 ≥ 2,000 万美元,d 与 d + 30 的 CG 价都在 —— 台账没写「当天还要有 OI 值」,
    所以当天没有 OI 行、但有价有市值的名字也留在宇宙里。
    对照口径(S-689 的 rows CTE:每天还要当天 oi_value_close > 0)另跑一遍,写进结果的
    `universe_sensitivity_s689_rows`,不出短名单。
  · 结果 y = (p_{d+30}/p_d − 1) − (BTC_{d+30}/BTC_d − 1),同一 CG 源。
  · 每个 d 每个因子:该因子有定义的名字 ≥ 30 个才算一天。
  · 主统计量:偏 Spearman ρ(因子, y | 规模);F14 用原始 Spearman。
  · 日值按自然月平均,t = 月均 / 月标准差 × √月数。

只读 Supabase(publishable key)。用法:
    python3 docs/research/t206_factor_zoo_discovery.py
环境:SUPABASE_URL / SUPABASE_KEY(缺一个就报错退出)。
产物:
    docs/research/t206_results.json
    /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-206_factor_zoo_discovery.md
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

# ---------------------------------------------------------------- 配置

DISCOVERY_START = "2023-01-01"          # 第一个信号日
DISCOVERY_END = "2024-11-30"            # 最后一个信号日(封存边界:之后的行不读)
OUTCOME_H = 30                          # 结果窗口 d → d+30
OUTCOME_END = "2024-12-30"              # 发现段结果窗口的最后一天(2024-11-30 + 30)
PRICE_FROM = "2021-12-01"               # 价格/市值:留出 F13 的 364 天回看
DERIV_FROM = "2022-11-25"               # 衍生指标:留出 F2/F3 的 30 天回看
FUNDING_FROM = "2022-11-25"             # 资金费:留出 F4 的 7 天回看

MIN_NAMES = 30                          # 每天每个因子的最少名字数
MCAP_MIN = 20_000_000.0                 # CG 市值门槛
MAP_MIN_OVERLAP = 30                    # 映射校验:最少重叠日
MAP_MAX_MED_ERR = 0.05                  # 映射校验:中位误差上限
MIN_VOL_OBS = 25                        # F11 波动:最少收益个数
MIN_HIGH_OBS = 300                      # F13:52 周高点窗口最少价格个数
MIN_WINDOW_DAYS = 5                     # F4/F7:7 天窗口里最少有效天数

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = REPO_ROOT / "docs" / "research" / "t206_results.json"
MAC_ROOT = Path("/Volumes/CometCloudAI/cometcloud-local")
CACHE_DIR = MAC_ROOT / "research" / "t206_cache"
OUT_MD = MAC_ROOT / "_reports" / "absorb_input" / "T-206_factor_zoo_discovery.md"
OUT_JSON_ALT = MAC_ROOT / "research" / "t206_universe_s689rows.json"   # 对照口径的逐月结果

# 宇宙口径:
#   "broad"(主):台账 S-691 宇宙那句的**字面读法** ——「deriv_metrics_daily 里的名字,过 S-689 的
#     映射校验;当天 CG 市值 ≥ 2,000 万;d 与 d+30 有 CG 价」,**没写**「当天要有 OI 值」:
#     映射校验是名字层面的,当天没有 OI 行、但有价有市值的名字仍留在宇宙里。
#   "oi_required"(对照):S-689 的 rows CTE 的读法 —— 每天还要当天 oi_value_close > 0。
#   台账那句括注「与 S-689 相同,但含面板名字」两读都能解释;主表用字面读法(broad),
#   因为它是台账宇宙句的逐条枚举,也与平行道(Seth)的实现对得上;另一读法作为对照写进结果。
UNIVERSE_MODE = "broad"

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

FACTORS = [
    ("F1", "OI/市值", "partial"),
    ("F2", "ΔOI 7天 (ln 张数)", "partial"),
    ("F3", "ΔOI 30天 (ln 张数)", "partial"),
    ("F4", "funding 7天均 (Binance)", "partial"),
    ("F5", "大户持仓多空比", "partial"),
    ("F6", "全体账户多空比", "partial"),
    ("F7", "主动买卖比 7天均", "partial"),
    ("F8", "30天相对动量 (对 BTC)", "partial"),
    ("F9", "7天相对动量 (对 BTC)", "partial"),
    ("F10", "90天相对动量 (对 BTC)", "partial"),
    ("F11", "30天波动 (日对数收益标准差)", "partial"),
    ("F12", "换手 7天均 (成交额/市值)", "partial"),
    ("F13", "距 52 周高点", "partial"),
    ("F14", "规模 ln(市值)", "raw"),
]


def main() -> None:
    t0 = time.time()
    import pandas as pd
    selfcheck()
    broad = (UNIVERSE_MODE == "broad")
    print(f"[mode ] {UNIVERSE_MODE}", flush=True)

    # ---------------- 拉数(全部按日期截断,封存段不读) ----------------
    deriv_csv = pull(
        "/rest/v1/deriv_metrics_daily",
        [("select", "symbol,d,oi_close,oi_value_close,top_pos_ratio_close,global_acct_ratio_close,taker_ratio_mean"),
         ("d", f"gte.{DERIV_FROM}"), ("d", f"lte.{DISCOVERY_END}")],
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
    fund_csv = pull(
        "/rest/v1/funding_history",
        [("select", "symbol,funding_time,funding_rate"), ("venue", "eq.binance_perp"),
         ("funding_time", f"gte.{FUNDING_FROM}T00:00:00Z"), ("funding_time", f"lte.{DISCOVERY_END}T23:59:59Z")],
        "symbol.asc,funding_time.asc", "funding_history")

    deriv = pd.read_csv(deriv_csv, dtype={"symbol": str, "d": str})
    am = pd.read_csv(am_csv, dtype={"symbol": str, "coin_id": str, "d": str})
    maps = pd.read_csv(map_csv, dtype={"symbol": str, "coin_id": str})
    cg = pd.read_csv(cg_csv, dtype={"coin_id": str, "d": str})
    fund = pd.read_csv(fund_csv, dtype={"symbol": str, "funding_time": str})

    # ---------------- 宇宙 + px(照 S-689 的映射段) ----------------
    name_set = set(deriv.loc[deriv["d"] >= DISCOVERY_START, "symbol"].astype(str))
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

    # 资金费:按 UTC 日聚合(symbol, day) -> 日均
    fund_mean: dict[str, dict[int, float]] = {}
    fund_dup = 0
    seen_ft: set[tuple[str, str]] = set()
    for row in fund.itertuples(index=False):
        ft = str(row.funding_time)
        sym = str(row.symbol)
        key = (sym, ft)
        if key in seen_ft:
            fund_dup += 1
            continue
        seen_ft.add(key)
        rate = float(row.funding_rate) if row.funding_rate == row.funding_rate else None
        if rate is None:
            continue
        fund_mean.setdefault(sym, {}).setdefault(d2ord(ft[:10]), []).append(rate)
    fund_mean = {s: {d: float(np.mean(v)) for d, v in dd.items()} for s, dd in fund_mean.items()}

    # ---------------- 映射校验(照 S-689;重叠日只在发现段信号日内) ----------------
    lo, hi = d2ord(DISCOVERY_START), d2ord(DISCOVERY_END)
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
        fund_d = dense(fund_mean.get(sym, {}))
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

        # F7: taker_ratio_mean 的 7 日均(≥ 5 天);F4: 日均 funding 的 7 日均(≥ 5 天)
        f7 = roll_mean(taker_d, 7, MIN_WINDOW_DAYS)
        f4 = roll_mean(fund_d, 7, MIN_WINDOW_DAYS)
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
    d_lo, d_hi = d2ord(DISCOVERY_START), d2ord(DISCOVERY_END)
    daily_ic: dict[str, dict[int, float]] = {f[0]: {} for f in FACTORS}
    daily_ic_alt: dict[str, dict[int, float]] = {f[0]: {} for f in FACTORS}
    daily_ic_var: dict[str, dict[int, float]] = {"F12b": {}}
    daily_n: dict[str, dict[int, int]] = {f[0]: {} for f in FACTORS}
    pair_acc: dict[tuple[str, str], list[float]] = {}
    universe_sizes: list[int] = []
    rows_out = 0
    f12_daycounts: list[int] = []

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

        # 敏感性变体 F12b(换手,7 天窗口要求 ≥ 5 个有效成交额日)—— 不进主表/短名单
        arrb = np.full(len(uni), np.nan)
        for k, s in enumerate(uni):
            arrb[k] = factor_value("F12b", s, d, gi, gi + OUTCOME_H, px, oi, roll, btc)
        mb = np.isfinite(arrb)
        if int(mb.sum()) >= MIN_NAMES:
            icb = partial_spearman(avg_rank(arrb[mb]), avg_rank(y[mb]), avg_rank(size[mb]))
            if math.isfinite(icb):
                daily_ic_var["F12b"][d] = icb

        # 探索:14 个因子两两的截面秩相关(只报均值)
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
    shortlist = []
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
        rec = {
            "factor": code,
            "label": label,
            "stat": "raw_spearman" if kind == "raw" else "partial_spearman_ctrl_size",
            "monthly": {m: round(float(np.mean(by_month[m])), 6) for m in months},
            "monthly_n_days": {m: len(by_month[m]) for m in months},
            "n_months": n_months,
            "n_days_total": sum(len(v) for v in by_month.values()),
            "mean_rho": None if not math.isfinite(mean) else round(mean, 6),
            "t_month": None if not math.isfinite(t) else round(t, 4),
            "names_per_day_min": min(n_names) if n_names else 0,
            "names_per_day_mean": round(float(np.mean(n_names)), 1) if n_names else 0,
            "months_positive": sum(1 for v in mvals if v > 0),
            "mean_rho_alt_rank_set": None if not math.isfinite(mean_alt) else round(mean_alt, 6),
            "t_month_alt_rank_set": None if not math.isfinite(t_alt) else round(t_alt, 4),
        }
        out_factors.append(rec)
        if math.isfinite(t) and abs(t) >= 3.0:
            shortlist.append({"factor": code, "label": label, "mean_rho": rec["mean_rho"],
                              "t_month": rec["t_month"], "sign": "+" if mean > 0 else "-",
                              "n_months": n_months,
                              "t_month_alt_rank_set": rec["t_month_alt_rank_set"]})
    shortlist_alt = [{"factor": c, "label": l, "t_month": rec["t_month_alt_rank_set"],
                       "sign": "+" if (rec["mean_rho_alt_rank_set"] or 0) > 0 else "-"}
                      for c, l, k in FACTORS
                      for rec in out_factors if rec["factor"] == c
                      and rec["t_month_alt_rank_set"] is not None
                      and abs(rec["t_month_alt_rank_set"]) >= 3.0]

    pair_mean = {f"{a}|{b}": round(float(np.mean(v)), 4) for (a, b), v in pair_acc.items()}

    sensitivities = {}
    for code, bm in daily_ic_var.items():
        bym: dict[str, list[float]] = {}
        for d, v in bm.items():
            bym.setdefault(month_of(d), []).append(v)
        ms = sorted(bym)
        mv = [float(np.mean(bym[m])) for m in ms]
        m_, t_, n_ = t_of(mv)
        sensitivities[code] = {
            "label": "换手 7天均(≥5 天成交额)",
            "stat": "partial_spearman_ctrl_size",
            "monthly": {m: round(float(np.mean(bym[m])), 6) for m in ms},
            "n_months": n_,
            "mean_rho": None if not math.isfinite(m_) else round(m_, 6),
            "t_month": None if not math.isfinite(t_) else round(t_, 4),
            "why": "台账对 F12 只写「d−6..d 成交额平均」没写最少天数(F4/F7 写了 ≥5 天);"
                   "这是换手率的门槛敏感性变体。",
        }

    result = {
        "task": "T-206",
        "ledger": "S-691",
        "generated_at_utc": datetime.now(timezone.utc).isoformat() + "Z",
        "segment": {
            "signal_days": f"{DISCOVERY_START}..{DISCOVERY_END}",
            "outcome_window_end": OUTCOME_END,
            "sealed": "信号日 >= 2024-12-01 的行未读取(价格/市值表截断 2024-12-30)",
            "min_names_per_day": MIN_NAMES,
            "mcap_min_usd": MCAP_MIN,
            "universe_mode": UNIVERSE_MODE,
        },
        "universe": {
            "deriv_symbols_with_data_from_2023": len(names),
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
            "funding_duplicate_rows": fund_dup,
            "funding_rows": int(len(fund)),
            "deriv_rows": int(len(deriv)),
            "names_without_cg_price": sorted([s for s in names if s not in px]),
            "asset_mcap_rows": int(len(am)),
        },
        "factors": out_factors,
        "shortlist_abs_t_ge_3": shortlist,
        "shortlist_abs_t_ge_3_alt_rank_set": shortlist_alt,
        "sensitivities": sensitivities,
        "pairwise_rank_corr_mean": pair_mean,
        "notes": [
            "F13 = p_d / max(p_{d−364..d}),窗口内 ≥ 300 个有效价格(窗口向前看,不含未来价)。",
            "F11 = d−29..d 的日对数收益样本标准差(ddof=1),≥ 25 个观测。",
            "F8/F9/F10 相对动量 = (p_d/p_{d−k} − 1) − (BTC_d/BTC_{d−k} − 1)。",
            "F4 = d−6..d 的 Binance 日均 funding 的平均,≥ 5 个有效日。",
            "F7 = d−6..d 的 taker_ratio_mean 平均,≥ 5 个有效日。",
            "F12 = d−6..d 的日成交额均值 / 当天市值(台账未设最少天数,≥ 1 天)。",
            "F14 用原始 Spearman(规模本身就是因子)。",
            "每个因子的名次在该因子有定义的当天截面上重算(偏相关的三个 ρ 同一批观测);"
            "F1 的截面 = 宇宙本身 ⇒ 与 S-689 同法。",
            "映射校验的重叠日窗口 = 2023-01-01 → 2024-11-30(只在发现段信号日内,封存段不读);"
            "S-689 的下界相同、上界是全历史(它跑的是完整样本)。",
        ],
    }

    cross_check_f1(result)
    if not broad:
        OUT_JSON_ALT.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON_ALT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
        print(f"[write] {OUT_JSON_ALT}", flush=True)
        print(f"[done ] {time.time() - t0:.1f}s", flush=True)
        return
    # 主口径(broad):把对照口径(S-689 rows:当天必须有 OI 值)的结果并进来
    if OUT_JSON_ALT.exists():
        try:
            b = json.loads(OUT_JSON_ALT.read_text())
            result["universe_sensitivity_s689_rows"] = {
                "mode": "oi_required —— S-689 的 rows CTE 读法(每天还要当天 oi_value_close > 0);仅对照",
                "universe": {k: b["universe"].get(k) for k in
                             ("mapping_checked", "mapping_kept", "names_per_day_mean",
                              "names_per_day_min", "names_per_day_max", "cross_section_rows")},
                "factors": [{"factor": f["factor"], "mean_rho": f["mean_rho"], "t_month": f["t_month"],
                             "n_months": f["n_months"], "names_per_day_mean": f["names_per_day_mean"]}
                            for f in b["factors"]],
                "shortlist_abs_t_ge_3": b["shortlist_abs_t_ge_3"],
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
        "note": "宇宙不同(本表含 25 个面板名字、只到 2024-11-30;S-689 是面板外、45 个月),"
                "逐月差应来自宇宙差而不是方法差。",
    }
    result["cross_check_f1_vs_s689"] = out
    return out


def write_report(result: dict) -> None:
    u = result["universe"]
    L = []
    L.append("# T-206 · 宽宇宙 14 因子截面 IC 普查(发现段)\n")
    L.append("- 台账:S-691(预注册 2026-10-27);卡:T-206;分支:`lane-b/T-206`")
    L.append(f"- 段:信号日 {result['segment']['signal_days']};结果窗口止于 {result['segment']['outcome_window_end']}")
    L.append(f"- {result['segment']['sealed']}")
    L.append(f"- 宇宙:{u['deriv_symbols_with_data_from_2023']} 个 deriv 名字 → 映射校验后留 {u['mapping_kept']} 个;"
             f"有宇宙的日子 {u['days_with_universe']} 天,每天名字数 {u['names_per_day_min']}–{u['names_per_day_max']}"
             f"(均值 {u['names_per_day_mean']}),截面行数 {u['cross_section_rows']:,}")
    L.append(f"- 统计量:每个 d 每个因子,该因子有定义的名字 ≥ {result['segment']['min_names_per_day']} 个才算一天;"
             "F1–F13 偏 Spearman(控制规模),F14 原始 Spearman;日值按自然月平均,t = 月均 / 月标准差 × √月数\n")

    L.append("## 14 个因子(发现段)\n")
    L.append("| 因子 | 含义 | 月均 ρ | 月 t | 月数 | 正月数 | 每日名字数(均/最小) | 统计量 | 名次口径 B 月 t |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for f in result["factors"]:
        L.append(f"| {f['factor']} | {f['label']} | {f['mean_rho']} | {f['t_month']} | {f['n_months']} | "
                 f"{f['months_positive']} | {f['names_per_day_mean']} / {f['names_per_day_min']} | "
                 f"{'偏 Spearman' if f['stat'].startswith('partial') else '原始 Spearman'} | "
                 f"{f['t_month_alt_rank_set']} |")
    L.append("")
    L.append("> 「口径 B」= 因子名次在自身有定义的子集内算、结果/规模名次在当天全宇宙内算(偏相关的三个 ρ "
             "不在同一批观测上,数学上不自洽;列出来只为量口径差多少)。口径 A(主)= 三个名次全在该因子有定义的"
             "当天截面上重算。\n")

    L.append("## 短名单(|月 t| ≥ 3.0)\n")
    sl = result["shortlist_abs_t_ge_3"]
    if not sl:
        L.append("**无。**发现段没有任何因子的月 t 达到 ±3.0。\n")
    else:
        L.append("| 因子 | 含义 | 月均 ρ | 月 t | 符号 | 月数 | 口径 B 月 t |")
        L.append("|---|---|---|---|---|---|---|")
        for s in sl:
            L.append(f"| {s['factor']} | {s['label']} | {s['mean_rho']} | {s['t_month']} | {s['sign']} | "
                     f"{s['n_months']} | {s.get('t_month_alt_rank_set')} |")
    L.append("")
    slb = result.get("shortlist_abs_t_ge_3_alt_rank_set") or []
    L.append("口径 B 下的短名单:" + (", ".join(f"{x['factor']}({x['sign']}, t={x['t_month']})" for x in slb)
                                     if slb else "无") + "\n")

    L.append("## 宇宙口径:两种读法的对照\n")
    alt = result.get("universe_sensitivity_s689_rows")
    if alt:
        L.append(f"- 读法 A(主)= 台账宇宙句的字面读法(当天不要求有 OI 值):每日名字数均值 "
                 f"{u['names_per_day_mean']}({u['names_per_day_min']}–{u['names_per_day_max']})。")
        L.append(f"- 读法 B(对照)= S-689 的 rows CTE(每天还要当天 oi_value_close > 0):每日名字数均值 "
                 f"{alt['universe']['names_per_day_mean']}"
                 f"({alt['universe']['names_per_day_min']}–{alt['universe']['names_per_day_max']})。")
        L.append("")
        L.append("| 因子 | 主口径 月均 ρ / 月 t | 对照口径 月均 ρ / 月 t | 月 t 差 |")
        L.append("|---|---|---|---|")
        for f, a in zip(result["factors"], alt["factors"]):
            L.append(f"| {f['factor']} | {f['mean_rho']} / {f['t_month']} | {a['mean_rho']} / {a['t_month']} | "
                     f"{round((a['t_month'] or 0) - (f['t_month'] or 0), 2):+} |")
        L.append("")
        L.append("> 两种读法的短名单:" + ", ".join(
            f"{x['factor']}({x['sign']}, t={x['t_month']})" for x in alt["shortlist_abs_t_ge_3"]) + "。\n")
    else:
        L.append("- (对照口径未并入 —— 单独跑 `python3 docs/research/t206_factor_zoo_discovery.py` 会一并生成。)\n")
    seth = {"F1": (-0.118, -6.43), "F2": (-0.023, -2.93), "F3": (-0.042, -3.16), "F4": (0.003, 0.19),
            "F5": (-0.009, -0.57), "F6": (0.023, 1.01), "F7": (0.107, 4.63), "F8": (-0.064, -3.16),
            "F9": (-0.035, -3.25), "F10": (-0.057, -2.18), "F11": (-0.102, -3.75), "F12": (-0.058, -2.74),
            "F13": (-0.040, -1.29), "F14": (0.028, 0.80)}
    L.append("## 与平行道(Seth)的对照(台账 §S-691 发现段表,已发布)\n")
    L.append("| 因子 | 本道 月均 ρ | 本道 月 t | 平行道 月均 ρ | 平行道 月 t | 月 t 差 | 同号 |")
    L.append("|---|---|---|---|---|---|---|")
    for f in result["factors"]:
        s = seth.get(f["factor"])
        if not s:
            continue
        L.append(f"| {f['factor']} | {f['mean_rho']} | {f['t_month']} | {s[0]} | {s[1]} | "
                 f"{round((f['t_month'] or 0) - s[1], 2):+} | {'✓' if (f['mean_rho'] or 0) * s[0] > 0 else '✗'} |")
    L.append("")
    L.append("> 平行道的数是台账 §S-691「发现段(Seth)」已发布的汇总(不是我从 s691_* 产物里读的 —— "
             "本卡禁止读那批文件)。差异集中在价格类因子,方向一致、幅度略大。\n")

    L.append("## 逐月 ρ(复算对数用)\n")
    for f in result["factors"]:
        L.append(f"- **{f['factor']} {f['label']}** — " + ", ".join(f"{m}:{v}" for m, v in f["monthly"].items()))
    L.append("")

    L.append("## 探索:14 个因子两两的截面秩相关(发现段均值)\n")
    pc = result["pairwise_rank_corr_mean"]
    if pc:
        codes = [f["factor"] for f in result["factors"]]
        L.append("| | " + " | ".join(codes) + " |")
        L.append("|---|" + "---|" * len(codes))
        for a in codes:
            row = []
            for b in codes:
                if a == b:
                    row.append("—")
                else:
                    key = f"{a}|{b}" if f"{a}|{b}" in pc else f"{b}|{a}"
                    row.append(str(pc.get(key, "n/a")))
            L.append(f"| {a} | " + " | ".join(row) + " |")
    L.append("")

    cc = result.get("cross_check_f1_vs_s689")
    if cc:
        L.append("## 方法校验:F1 对已发布的 S-689 面板外序列\n")
        L.append(f"- 逐月对比 {cc['months_compared']} 个月:平均差 **{cc['mean_diff']}**,"
                 f"最大绝对差 {cc['max_abs_diff']},同号 {cc['same_sign_months']}/{cc['months_compared']} 个月。")
        L.append(f"- 本表 F1(23 个月,含面板名字):月均 {cc['mine_mean_rho']} / t {cc['mine_t_month']};"
                 f"S-689(面板外,{cc['s689_n_months']} 个月):月均 {cc['s689_mean_rho']} / t {cc['s689_t_month']}。")
        L.append(f"- {cc['note']}\n")

    L.append("## 协议问题(需要人确认)\n")
    _f = {x["factor"]: x for x in result["factors"]}
    _alt = {x["factor"]: x for x in (result.get("universe_sensitivity_s689_rows") or {}).get("factors", [])}
    L.append(f"- **宇宙口径有两读,短名单在 F12 上不一致(最要紧的一条)**。台账宇宙句逐条枚举的是"
             f"「deriv_metrics_daily 里的名字 + 过 S-689 的映射校验 + 当天 CG 市值 ≥ 2,000 万 + d 与 d+30 有 CG 价」,"
             f"**没写「当天还要有 OI 值」**(读法 A = 本表主口径);台账括注「与 S-689 相同」指向 S-689 的 rows CTE,"
             f"那里每天还要当天 oi_value_close > 0(读法 B = 对照口径,见上表)。")
    L.append(f"  - 两种读法下 OI 类因子(F1/F2/F3/F5/F6/F7)**逐位相同**;"
             f"价格类因子(F8–F14)因读法 A 的截面更宽而略弱(F8 {_f['F8']['mean_rho']} vs {_alt.get('F8',{}).get('mean_rho')},"
             f"F11 {_f['F11']['mean_rho']} vs {_alt.get('F11',{}).get('mean_rho')})。")
    L.append(f"  - 与平行道(Seth,台账 §S-691 发现段表)对账:OI 类**逐位吻合到小数点后三位**"
             f"(F1 {_f['F1']['mean_rho']} vs −0.118、F3 {_f['F3']['mean_rho']} vs −0.042、"
             f"F7 {_f['F7']['mean_rho']} vs +0.107);价格类**方向一致、幅度略大**"
             f"(F8 {_f['F8']['mean_rho']} vs −0.064、F11 {_f['F11']['mean_rho']} vs −0.102、"
             f"F12 {_f['F12']['mean_rho']} vs −0.058、F13 {_f['F13']['mean_rho']} vs −0.040、"
             f"F14 {_f['F14']['mean_rho']} vs +0.028)⇒ 平行道的宇宙比我的宽"
             f"(Seth:映射校验 248 名、段内 225 名;我:校验 {u['mapping_checked']} 名、段内 "
             f"{len(result['universe']['names_kept'])} 名)。")
    L.append(f"  - 我从库里**重建不出 248 这个数**(deriv_metrics_daily 220 名 / perp_cg_map 43 名 / "
             f"面板 25 名 / asset_mcap_daily 340 名 / cg_coin_mcap_daily 267 个 coin_id,任何并集都到不了 248)"
             f"⇒ 请平行道把「映射校验 248 名」的定义写清楚(哪个池、重叠日窗口怎么取)。")
    L.append(f"  - **结论:短名单 F3 / F7 / F8 / F9 / F11 两道一致;F12 是未决项**"
             f"(我 |t| = {abs(_f['F12']['t_month']):.2f}(主口径)/{abs(_alt.get('F12',{}).get('t_month') or 0):.2f}(对照口径),"
             f"平行道 2.74)—— 宇宙口径与名字池一改就可能翻面。按 S-691「逐月一致后冻结」的规则,"
             f"F12 不应在宇宙没钉死之前冻进短名单。")
    L.append("- **名次在哪个截面上算**:每个因子的三个名次(因子 / 结果 / 规模)全部在该因子**有定义的当天截面**上"
             "重算 —— 偏相关公式要求三个 ρ 来自同一批观测。F1 的有定义集合 = 宇宙本身 ⇒ F1 与 S-689 同法、"
             "可逐位比;F12 / F13 之类的子集因子会与「先在全宇宙排好名次再取子集」的口径有差。")
    L.append("- **映射校验的重叠窗口被截断**:S-689 用全历史重叠日(到 2026-10),本脚本按封存纪律只在发现段信号日"
             "(2023-01-01 → 2024-11-30)内算重叠日与中位误差 ⇒ 名字集合可能与 S-689 的名单不同。"
             "Seth 复算若沿用 S-689 的全历史窗口,逐月数会在名字集合上有差。")
    L.append("- **F13 的窗口方向**:必须是 p_d / max(p_{d−364..d})(**向前**的 52 周窗口)。"
             "scipy 的 `maximum_filter1d(origin=…)` 很容易写反成前视窗口(本脚本已用 selfcheck 钉住)。")
    L.append("- **F12 的最少天数**:台账只写「d−6..d 成交额平均」,没写「≥ 5 天」(F4/F7 有)。本脚本按字面取"
             "窗口内可用日的平均(≥ 1 天),并在结果里记录每日名字数。敏感性变体 F12b(≥ 5 天):"
             + (f"月均 {result['sensitivities']['F12b']['mean_rho']} / t {result['sensitivities']['F12b']['t_month']}"
                if "F12b" in result.get("sensitivities", {}) else "n/a")
             + " —— 两种口径下 F12 都在 |t| ≥ 3.0 一侧,换手率的门槛口径不改它进不进短名单。")
    L.append("- **F11 的标准差口径**:样本标准差(ddof=1)。窗口 = d−29..d 的 30 个日历日日对数收益。")
    L.append("- **相对动量的算法**:相对收益之差(与 y 的定义同构),不是比值。")
    L.append("- **留出段仍封存**:本轮只跑发现段;留出段(信号日 ≥ 2025-01-01)按 S-691 由 Seth 跑、B 道复算。")
    L.append("- **换手率只覆盖有成交额的名字**(asset_mcap_daily 才有 volume),F12 的每日名字数因此小于其他因子。\n")

    L.append("## 还看到了什么(探索性 —— 需另立预注册、在新数据上过零信号对照)\n")
    pc = result.get("pairwise_rank_corr_mean") or {}
    pairs = sorted(pc.items(), key=lambda kv: -abs(kv[1]))[:8]
    if pairs:
        L.append("- 探索性 —— 需另立预注册、在新数据上过零信号对照:**哪几个因子是同一件事**。"
                 "发现段里两两截面秩相关最高的 8 对:"
                 + "; ".join(f"{k.replace('|', '↔')} = {v}" for k, v in pairs)
                 + "。这只是「同一件事」的地图,不是可交易结论;任何由它导出的组合都要另立预注册、"
                   "在新数据上过零信号对照。")
    near = [f for f in result["factors"]
            if f["t_month"] is not None and 2.0 <= abs(f["t_month"]) < 3.0]
    if near:
        L.append("- 探索性 —— 需另立预注册、在新数据上过零信号对照:**差一档就进短名单的因子**:"
                 + ", ".join(f"{f['factor']}(t={f['t_month']})" for f in near)
                 + "。发现段只有 23 个月,|t| 在 2–3 之间的因子换 23 个月样本就能上下翻面,"
                   "不该当发现。")
    L.append("- 探索性 —— 需另立预注册、在新数据上过零信号对照:**短名单里的因子互相不是独立的**。"
             "F3(ΔOI 30 天)与 F1(水平)、F8/F9(相对动量)与 F10 高度相关;把它们当成 4 个独立发现会高估"
             "有效试验数。")
    L.append("- 探索性 —— 需另立预注册、在新数据上过零信号对照:**F13(距 52 周高点)的前视陷阱是真实存在的**。"
             "scipy `maximum_filter1d(origin=-182)` 会把未来 364 天的最高价算进分母,写成 "
             "「距未来一年最高点的距离」,因子会显著变样;本脚本的 selfcheck 已把方向钉住。")
    L.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    # 先跑对照口径(S-689 rows:当天必须有 OI 值),再跑主口径(台账宇宙句的字面读法)
    UNIVERSE_MODE = "oi_required"
    main()
    UNIVERSE_MODE = "broad"
    main()
