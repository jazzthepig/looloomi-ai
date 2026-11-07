"""T-286 — S-765(Binance 在一个币的成交里占比下降 → 之后 4 周相对 BTC 跑输吗,横截面周频)

预注册(台账 S-765,Seth,2026-11-07 11:24 UTC)要点,一字不改:
  宇宙 = 每周一当周 `asset_mcap_daily` 市值前 200,且 `ohlcv_daily`(source=binance_hist)有 ≥ 60 天日线
         (含后来停更的);2021-06 → 2026-10。
  特征 = Δs = s30(m) − s30(前 30 天);s30 = 过去 30 天 Binance 现货成交额(close × volume)÷ 同期
         CG 全市场成交额(`asset_mcap_daily.volume`)。严格 ≤ 周一前一日。
  目标 = 之后 4 周相对 BTC 的超额。
  预期 = Δs 越负越跑输 ⇒ IC(Δs, 超额) > 0。
  丢弃 = s30 > 1 或 CG 成交为 0 的格。
  判据 = (a) 每周截面 Spearman IC 均值 > 0 且 NW(4 阶) t ≥ 2.0;
         (b) Δs 最高五分之一减最低五分之一的平均 4 周超额 ≥ +1.5%;
         (c) 每周内打乱 Δs(1,000 次,种子 765)实际均值 IC 分位 ≥ 0.95;
         (d) 两段(按周数对半)同号。
  副项(只报不判)= 水平 s30 的 IC;8 周目标;只看市值 51–200;价格源交叉核对(binance_hist 收盘)。

预注册没有写死、本脚本在**看到任何结果之前**先定死的三处:
  1) 价格源:标的与 BTC **都用** `asset_mcap_daily.price`(CG 日收盘,同源 ⇒ 超额同口径);
     另跑交叉核对臂:标的与 BTC 都用 `ohlcv_daily`(binance_hist)收盘。
  2) 入场价 = ≤ m 的最后一个收盘(回看 ≤ 7 天);出场价 = ≥ m+28 的第一个收盘(≤ 7 天)。
  3) 数据卫生:30 天窗内 CG 成交额有效天数 ≥ 25(否则丢弃该格,单独计数);每周截面有效格 ≥ 10 才计入 IC;
     as-of 市值回看 ≤ 7 天。

用法:
  python3 t286_share.py fetch   # 取数到 Mac 数据根(分片)
  python3 t286_share.py run     # 算 (a)–(d) + 副项,写 t286_results.json
"""
import bisect
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
from scipy.stats import spearmanr

REPO = "/Users/sbb/Projects/looloomi-ai-lane-b"
sys.path.insert(0, os.path.join(REPO, "src"))
from data.evaluation import apparatus as ap  # noqa: E402

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("FATAL: SUPABASE_URL / SUPABASE_KEY not in env")
URL = URL.rstrip("/")

OUT_DIR = "/Volumes/CometCloudAI/cometcloud-local/research/t286"
RESULT_PATH = os.path.join(REPO, "docs/research/t286_results.json")

D_START = "2021-04-01"          # 第一个周一(2021-06-07)往前 60 天的 s30 窗
D_END = "2026-11-15"            # 取数到这一天(含前向价)
WEEK_FIRST = "2021-06-07"       # 第一个周一
WEEK_LAST = "2026-10-26"        # 最后一个周一
TOP_N = 200                     # 市值前 200
MIN_BARS = 60                   # binance_hist 日线条数
MIN_CELL_DAYS = 25              # 30 天窗内 CG 成交额有效天数下限
MIN_CROSS_N = 10                # 每周截面最小格数
HOLD_DAYS = 28                  # 4 周
HOLD_DAYS_8W = 56               # 副项:8 周
SEED = 765
N_PERM = 1000

HDRS = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


# ── Supabase REST(只读)──────────────────────────────────────────────────────
def _qs(params=None, order=None, limit=None, offset=None):
    """把参数拼成查询串:order= / limit= / offset= 永远是字面量出现在请求里
    (PostgREST 翻页边界规则:不带 order= 的翻页会漏键)。"""
    parts = []
    for k, v in (params or {}).items():
        if isinstance(v, (list, tuple)):
            for x in v:
                parts.append(f"{k}={x}")
        else:
            parts.append(f"{k}={v}")
    if order:
        parts.append(f"order={order}")
    if limit is not None:
        parts.append(f"limit={limit}")
    if offset is not None:
        parts.append(f"offset={offset}")
    return "&".join(parts)


def get(path, query="", count=False, retries=4):
    url = f"{URL}/rest/v1/{path}"
    if query:
        url = f"{url}?{query}"
    headers = dict(HDRS)
    if count:
        headers["Prefer"] = "count=exact"
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as r:
                body = r.read()
                total = r.headers.get("Content-Range")
            rows = json.loads(body) if body else []
            n = None
            if total and "/" in total:
                try:
                    n = int(total.split("/")[-1])
                except ValueError:
                    n = None
            return rows, n
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:200]!r}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {path} failed: {last}")


def get_all(path, params=None, order=None, page=1000, label=""):
    """带 order= 的全量翻页(PostgREST 边界规则);每页最多 1000 行。"""
    rows, total = get(path, _qs(params, order=order, limit=page, offset=0), count=True)
    if label:
        print(f"  {label}: count_exact={total}", flush=True)
    out = list(rows)
    while total is not None and len(out) < total:
        more, _ = get(path, _qs(params, order=order, limit=page, offset=len(out)))
        if not more:
            break
        out.extend(more)
        if label and len(out) % 50000 < page:
            print(f"  {label}: {len(out)}/{total}", flush=True)
    return out


# ── 取数(分片)───────────────────────────────────────────────────────────────
def month_edges(start, end):
    """[start, end) 的 6 个月分片边界。"""
    edges = []
    y, m = int(start[:4]), int(start[5:7])
    while True:
        cur = f"{y:04d}-{m:02d}-01"
        for _ in range(6):
            if m == 12:
                y, m = y + 1, 1
            else:
                m += 1
        nxt = f"{y:04d}-{m:02d}-01"
        edges.append((cur, nxt))
        if nxt[:7] >= end[:7]:
            break
    return edges


def cmd_fetch():
    os.makedirs(OUT_DIR, exist_ok=True)
    edges = month_edges(D_START, D_END)
    print("shards:", len(edges), edges[0], edges[-1], flush=True)

    def do_mcap(a, b):
        name = f"mcap_{a}_{b}.json"
        path = os.path.join(OUT_DIR, name)
        if os.path.exists(path):
            print("skip", name, flush=True)
            return name, None
        rows = get_all("asset_mcap_daily",
                       {"select": "symbol,d,mcap,price,volume", "order": "symbol.asc,d.asc", "d": [f"gte.{a}", f"lt.{b}"]},
                       label=name)   # Seth 合并时:order 挪进参数字典(静态检查只认字典里的 order;请求串不变)
        with open(path + ".tmp", "w") as f:
            json.dump(rows, f)
        os.replace(path + ".tmp", path)
        return name, len(rows)

    def do_ohlc(a, b):
        name = f"ohlc_{a}_{b}.json"
        path = os.path.join(OUT_DIR, name)
        if os.path.exists(path):
            print("skip", name, flush=True)
            return name, None
        rows = get_all("ohlcv_daily",
                       {"select": "symbol,trade_date,close,volume", "source": "eq.binance_hist", "order": "symbol.asc,trade_date.asc",
                        "trade_date": [f"gte.{a}", f"lt.{b}"]},
                       label=name)   # 同上
        with open(path + ".tmp", "w") as f:
            json.dump(rows, f)
        os.replace(path + ".tmp", path)
        return name, len(rows)

    for fn in (do_mcap, do_ohlc):
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = [ex.submit(fn, a, b) for a, b in edges]
            for fu in futs:
                nm, n = fu.result()
                print("done", nm, n, flush=True)
    print("FETCH_DONE", flush=True)


# ── 面板装配 ────────────────────────────────────────────────────────────────
def ord_of(s):
    return date.fromisoformat(str(s)[:10]).toordinal()


class Series:
    """一个代号的日频序列(按日期升序)。"""

    __slots__ = ("ds", "mcap", "price", "vol", "qv", "close", "ps_vol", "ps_qv", "nvol")

    def __init__(self):
        self.ds = []
        self.mcap = []
        self.price = []
        self.vol = []
        self.qv = []
        self.close = []
        self.ps_vol = [0.0]
        self.ps_qv = [0.0]
        self.nvol = [0]

    def finalize(self):
        self.ps_vol = [0.0]
        self.nvol = [0]
        for v in self.vol:
            self.ps_vol.append(self.ps_vol[-1] + (0.0 if v is None else v))
            self.nvol.append(self.nvol[-1] + (0 if v is None else 1))
        self.ps_qv = [0.0]
        for q in self.qv:
            self.ps_qv.append(self.ps_qv[-1] + (0.0 if q is None else q))


def load_mcap():
    series = {}
    n_rows = 0
    for fn in sorted(os.listdir(OUT_DIR)):
        if not fn.startswith("mcap_"):
            continue
        rows = json.load(open(os.path.join(OUT_DIR, fn)))
        n_rows += len(rows)
        for r in rows:
            sym = r.get("symbol")
            if not sym:
                continue
            s = series.get(sym)
            if s is None:
                s = series[sym] = Series()
            s.ds.append(ord_of(r["d"]))
            s.mcap.append(r.get("mcap"))
            s.price.append(r.get("price"))
            v = r.get("volume")
            s.vol.append(None if v is None else float(v))
        print(f"  loaded {fn}: {len(rows)} rows", flush=True)
    for s in series.values():
        order = sorted(range(len(s.ds)), key=lambda i: s.ds[i])
        s.ds = [s.ds[i] for i in order]
        s.mcap = [s.mcap[i] for i in order]
        s.price = [s.price[i] for i in order]
        s.vol = [s.vol[i] for i in order]
        s.finalize()
    print(f"[mcap] symbols={len(series)} rows={n_rows}", flush=True)
    return series


def load_ohlc():
    """binance_hist:close × volume(USD 成交额)+ close(交叉核对臂)。"""
    series = {}
    n_rows = 0
    for fn in sorted(os.listdir(OUT_DIR)):
        if not fn.startswith("ohlc_"):
            continue
        rows = json.load(open(os.path.join(OUT_DIR, fn)))
        n_rows += len(rows)
        for r in rows:
            sym = r.get("symbol")
            if not sym:
                continue
            s = series.get(sym)
            if s is None:
                s = series[sym] = Series()
            s.ds.append(ord_of(r["trade_date"]))
            c, v = r.get("close"), r.get("volume")
            s.close.append(None if c is None else float(c))
            s.qv.append(None if (c is None or v is None) else float(c) * float(v))
        print(f"  loaded {fn}: {len(rows)} rows", flush=True)
    for s in series.values():
        order = sorted(range(len(s.ds)), key=lambda i: s.ds[i])
        s.ds = [s.ds[i] for i in order]
        s.qv = [s.qv[i] for i in order]
        s.close = [s.close[i] for i in order]
        s.finalize()
    print(f"[ohlc] symbols={len(series)} rows={n_rows}", flush=True)
    return series


def asof_value(s, arr, d_ord, max_gap=7):
    """≤ d_ord 的最后一个有效值(回看 ≤ max_gap 天)。"""
    i = bisect.bisect_right(s.ds, d_ord) - 1
    if i < 0 or d_ord - s.ds[i] > max_gap:
        return None
    j = i
    while j >= 0:
        p = arr[j]
        if p is not None and float(p) > 0:
            return float(p)
        j -= 1
    return None


def after_value(s, arr, d_ord, max_gap=7):
    """≥ d_ord 的第一个有效值(≤ max_gap 天)。"""
    i = bisect.bisect_left(s.ds, d_ord)
    while i < len(s.ds):
        if s.ds[i] - d_ord > max_gap:
            return None
        p = arr[i]
        if p is not None and float(p) > 0:
            return float(p)
        i += 1
    return None


def window_sum(s, ps, d_hi, d_lo):
    """(d_lo, d_hi] 区间上的和与行数。"""
    i = bisect.bisect_right(s.ds, d_lo)
    j = bisect.bisect_left(s.ds, d_hi + 1)
    if j <= i:
        return 0.0, 0
    return ps[j] - ps[i], j - i


def window_days(s, cnt, d_hi, d_lo):
    """(d_lo, d_hi] 区间里非空成交额的天数。"""
    i = bisect.bisect_right(s.ds, d_lo)
    j = bisect.bisect_left(s.ds, d_hi + 1)
    if j <= i:
        return 0
    return cnt[j] - cnt[i]


def mondays():
    d = date.fromisoformat(WEEK_FIRST)
    end = date.fromisoformat(WEEK_LAST)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


# ── 主计算 ──────────────────────────────────────────────────────────────────
def build_records(mcap, ohlc):
    btc = mcap.get("BTC")
    btc_oh = ohlc.get("BTC")
    recs = []
    weeks_meta = []
    for wk in mondays():
        M = wk.toordinal()
        ranked = []
        for sym, s in mcap.items():
            i = bisect.bisect_right(s.ds, M) - 1
            if i < 0 or M - s.ds[i] > 7:
                continue
            mc = s.mcap[i]
            if mc is None or float(mc) <= 0:
                continue
            ranked.append((float(mc), sym))
        ranked.sort(key=lambda t: (-t[0], t[1]))
        universe = ranked[:TOP_N]
        rank_of = {sym: r + 1 for r, (_mc, sym) in enumerate(universe)}
        cnt = {"universe": len(universe), "no_bars": 0, "no_cg_vol": 0, "thin_cg": 0,
               "s30_gt1": 0, "no_entry": 0, "no_exit": 0, "ok": 0, "ok_bh": 0}
        for _mc, sym in universe:
            o = ohlc.get(sym)
            if o is None or bisect.bisect_right(o.ds, M) < MIN_BARS:
                cnt["no_bars"] += 1
                continue
            s = mcap[sym]
            cg_cur, _ = window_sum(s, s.ps_vol, M - 1, M - 31)
            cg_prev, _ = window_sum(s, s.ps_vol, M - 31, M - 61)
            dcur = window_days(s, s.nvol, M - 1, M - 31)
            dprev = window_days(s, s.nvol, M - 31, M - 61)
            if cg_cur <= 0 or cg_prev <= 0:
                cnt["no_cg_vol"] += 1
                continue
            if dcur < MIN_CELL_DAYS or dprev < MIN_CELL_DAYS:
                cnt["thin_cg"] += 1
                continue
            bin_cur, _ = window_sum(o, o.ps_qv, M - 1, M - 31)
            bin_prev, _ = window_sum(o, o.ps_qv, M - 31, M - 61)
            s30 = bin_cur / cg_cur
            s30_prev = bin_prev / cg_prev
            if s30 > 1.0 or s30_prev > 1.0:
                cnt["s30_gt1"] += 1
                continue
            px0 = asof_value(s, s.price, M)
            if px0 is None:
                cnt["no_entry"] += 1
                continue
            px1 = after_value(s, s.price, M + HOLD_DAYS)
            r_asset = ap.long_return(px0, px1) if px1 else None
            btc0 = asof_value(btc, btc.price, M) if btc else None
            btc1 = after_value(btc, btc.price, M + HOLD_DAYS) if btc else None
            r_btc = ap.long_return(btc0, btc1) if (btc0 and btc1) else None
            if r_asset is None or r_btc is None:
                cnt["no_exit"] += 1
                continue
            excess = (1.0 + r_asset) / (1.0 + r_btc) - 1.0
            # 副项:8 周目标
            px1_8w = after_value(s, s.price, M + HOLD_DAYS_8W)
            r_asset_8w = ap.long_return(px0, px1_8w) if px1_8w else None
            btc1_8w = after_value(btc, btc.price, M + HOLD_DAYS_8W) if btc else None
            r_btc_8w = ap.long_return(btc0, btc1_8w) if (btc0 and btc1_8w) else None
            excess_8w = ((1.0 + r_asset_8w) / (1.0 + r_btc_8w) - 1.0
                         if (r_asset_8w is not None and r_btc_8w is not None) else None)
            # 副项:交叉核对臂(标的与 BTC 都用 binance_hist 收盘)
            excess_bh = None
            if o is not None and btc_oh is not None:
                b0 = asof_value(o, o.close, M)
                b1 = after_value(o, o.close, M + HOLD_DAYS)
                k0 = asof_value(btc_oh, btc_oh.close, M)
                k1 = after_value(btc_oh, btc_oh.close, M + HOLD_DAYS)
                ra = ap.long_return(b0, b1) if (b0 and b1) else None
                rb = ap.long_return(k0, k1) if (k0 and k1) else None
                if ra is not None and rb is not None:
                    excess_bh = (1.0 + ra) / (1.0 + rb) - 1.0
                    cnt["ok_bh"] += 1
            # 探索性:入场前 4 周超额(用来做反转对照)
            past_excess = None
            px_m28 = asof_value(s, s.price, M - HOLD_DAYS)
            btc_m28 = asof_value(btc, btc.price, M - HOLD_DAYS) if btc else None
            r_past = ap.long_return(px_m28, px0) if px_m28 else None
            r_btc_past = ap.long_return(btc_m28, btc0) if (btc_m28 and btc0) else None
            if r_past is not None and r_btc_past is not None:
                past_excess = (1.0 + r_past) / (1.0 + r_btc_past) - 1.0
            cnt["ok"] += 1
            recs.append({
                "week": wk.isoformat(), "symbol": sym, "rank": rank_of[sym],
                "ds": s30 - s30_prev, "s30": s30, "s30_prev": s30_prev,
                "excess": excess, "excess_8w": excess_8w, "excess_bh": excess_bh,
                "past_excess": past_excess,
                "r_asset": r_asset, "r_btc": r_btc,
            })
        weeks_meta.append({"week": wk.isoformat(), **cnt})
    return recs, weeks_meta


# ── 统计(判据尺子照 S-743 / S-765)──────────────────────────────────────────
def weekly_ic(recs, key, excess_key):
    weeks = sorted({r["week"] for r in recs})
    out = []
    for w in weeks:
        rr = [r for r in recs if r["week"] == w and r.get(excess_key) is not None]
        if len(rr) < MIN_CROSS_N:
            continue
        x = [r[key] for r in rr]
        e = [r[excess_key] for r in rr]
        if np.std(x) == 0 or np.std(e) == 0:
            continue
        rho = spearmanr(x, e).statistic
        if rho is None or math.isnan(rho):
            continue
        out.append((w, len(rr), float(rho)))
    return out


def nw_t(x, lags=4):
    x = np.asarray(x, dtype=float)
    n = len(x)
    d = x - x.mean()
    var = (d @ d) / n
    for l in range(1, lags + 1):
        gl = (d[l:] @ d[:-l]) / n
        var += 2.0 * (1.0 - l / (lags + 1.0)) * gl
    se = math.sqrt(max(var, 1e-24) / n)
    return float(x.mean() / se), float(x.mean()), float(se)


def evaluate(recs, label, key="ds", excess_key="excess", perm=True):
    ics = weekly_ic(recs, key, excess_key)
    if not ics:
        return None
    wk = [i[0] for i in ics]
    rho = np.array([i[2] for i in ics])
    n_per = np.array([i[1] for i in ics])
    t_stat, mean_ic, se = nw_t(rho, lags=4)
    # (b) 五分位
    pooled_top, pooled_bot, per_week_spread = [], [], []
    for w in wk:
        rr = [r for r in recs if r["week"] == w and r.get(excess_key) is not None]
        if len(rr) < MIN_CROSS_N:
            continue
        rr = sorted(rr, key=lambda r: r[key])
        n = len(rr)
        k = max(1, n // 5)
        top, bot = rr[-k:], rr[:k]
        pooled_top.extend(r[excess_key] for r in top)
        pooled_bot.extend(r[excess_key] for r in bot)
        per_week_spread.append(float(np.mean([r[excess_key] for r in top]) -
                                     np.mean([r[excess_key] for r in bot])))
    spread_pooled = float(np.mean(pooled_top) - np.mean(pooled_bot))
    spread_wmean = float(np.mean(per_week_spread)) if per_week_spread else float("nan")
    # (c) 零分布:每周内打乱
    sub = [r for r in recs if r.get(excess_key) is not None]
    g_arr = np.array([r[key] for r in sub], dtype=object)
    w_arr = np.array([r["week"] for r in sub], dtype=object)
    e_arr = np.array([r[excess_key] for r in sub], dtype=float)
    used = sorted({r["week"] for r in sub})
    masks = {w: (w_arr == w) for w in used}

    def null_stat(rng):
        sh = ap.shuffle_within(g_arr, w_arr, rng)
        rs = []
        for w in used:
            m = masks[w]
            xx = np.asarray(sh[m], dtype=float)
            yy = e_arr[m]
            if np.std(xx) == 0 or np.std(yy) == 0:
                continue
            rho_ = spearmanr(xx, yy).statistic
            if rho_ is not None and not math.isnan(rho_):
                rs.append(float(rho_))
        return float(np.mean(rs)) if rs else float("nan")

    null_pct, null_mean, null_sd = None, None, None
    if perm:
        try:
            null = ap.null_distribution(null_stat, N_PERM, SEED, actual=float(mean_ic))
            null_pct = ap.percentile_of(float(mean_ic), null)
            null_mean = float(np.mean(null))
            null_sd = float(np.std(null))
        except Exception as e:  # noqa: BLE001
            null_pct = f"ERR:{e}"
    # (d) 两段(按周数对半)
    half = len(wk) // 2
    h1 = float(np.mean(rho[:half]))
    h2 = float(np.mean(rho[half:]))
    return {
        "label": label, "key": key, "excess_key": excess_key,
        "n_weeks": len(wk), "weeks": [wk[0], wk[-1]],
        "n_obs_per_week_min": int(n_per.min()), "n_obs_per_week_max": int(n_per.max()),
        "mean_weekly_ic": float(mean_ic), "nw_t_4lag": float(t_stat), "nw_se": float(se),
        "b_spread_pooled_excess": spread_pooled,
        "b_spread_weekmean_excess": spread_wmean,
        "b_pooled_top_n": len(pooled_top), "b_pooled_bot_n": len(pooled_bot),
        "c_null_percentile": null_pct, "c_null_mean": null_mean, "c_null_sd": null_sd,
        "c_n_perm": N_PERM, "c_seed": SEED,
        "d_half1_weeks": half, "d_half1_mean_ic": h1,
        "d_half2_weeks": len(wk) - half, "d_half2_mean_ic": h2,
        "ic_series": [[w, int(n), float(r)] for w, n, r in ics],
    }


def _weekly_corr(pairs):
    """pairs: [(week, x, y)] → 每周 Spearman IC 的均值与 NW(4)t。"""
    weeks = sorted({p[0] for p in pairs})
    rhos = []
    for w in weeks:
        xs = [p[1] for p in pairs if p[0] == w]
        ys = [p[2] for p in pairs if p[0] == w]
        if len(xs) < MIN_CROSS_N or np.std(xs) == 0 or np.std(ys) == 0:
            continue
        rho = spearmanr(xs, ys).statistic
        if rho is None or math.isnan(rho):
            continue
        rhos.append(float(rho))
    if not rhos:
        return None
    t, mean, se = nw_t(rhos, lags=4)
    return {"mean_ic": mean, "nw_t_4lag": t, "nw_se": se, "n_weeks": len(rhos)}


def exploratory(recs):
    """探索性诊断(不参与判据):这条负向 IC 到底是不是「反转」的伪装。"""
    out = {}

    def quintile_profile(key):
        sub = [r for r in recs if r["excess"] is not None]
        sub.sort(key=lambda r: r[key])
        n = len(sub)
        k = n // 5
        prof = []
        for i in range(5):
            lo = i * k
            hi = n if i == 4 else (i + 1) * k
            grp = sub[lo:hi]
            prof.append({"q": i + 1, "n": len(grp),
                         "mean_excess": float(np.mean([g["excess"] for g in grp])),
                         "mean_key": float(np.mean([g[key] for g in grp]))})
        return prof

    out["quintile_profile_ds"] = quintile_profile("ds")
    out["quintile_profile_s30"] = quintile_profile("s30")

    # 反转对照:入场前 4 周超额 与 Δs / 与未来超额 的每周截面 IC
    pe = [r for r in recs if r["past_excess"] is not None and r["excess"] is not None]
    out["ic_past_excess_vs_ds"] = _weekly_corr([(r["week"], r["past_excess"], r["ds"]) for r in pe])
    out["ic_past_excess_vs_future_excess"] = _weekly_corr(
        [(r["week"], r["past_excess"], r["excess"]) for r in pe])

    def residual_ic(controls, xkey="ds", target="excess"):
        pairs = []
        for w in sorted({r["week"] for r in recs}):
            rr = [r for r in recs if r["week"] == w and r.get(target) is not None
                  and all(r.get(c) is not None for c in controls)]
            if len(rr) < MIN_CROSS_N:
                continue
            X = np.column_stack([np.ones(len(rr))] + [[float(r[c]) for r in rr] for c in controls])
            y = np.array([float(r[xkey]) for r in rr])
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ beta
            for r, e in zip(rr, resid):
                pairs.append((w, float(e), r[target]))
        return _weekly_corr(pairs)

    out["resid_ic_ds_given_past_excess"] = residual_ic(["past_excess"])
    out["resid_ic_ds_given_past_and_level"] = residual_ic(["past_excess", "s30"])
    out["resid_ic_ds_given_level"] = residual_ic(["s30"])
    return out


def cmd_run():
    os.makedirs(os.path.dirname(RESULT_PATH), exist_ok=True)
    print("[load] asset_mcap_daily ...", flush=True)
    mcap = load_mcap()
    print("[load] ohlcv_daily(binance_hist) ...", flush=True)
    ohlc = load_ohlc()
    recs, weeks_meta = build_records(mcap, ohlc)
    print(f"[panel] records={len(recs)} weeks={len(weeks_meta)}", flush=True)

    main = evaluate(recs, "main:Δs → 4 周超额")
    sec_level = evaluate(recs, "副:水平 s30 → 4 周超额", key="s30", perm=False)
    sec_8w = evaluate(recs, "副:Δs → 8 周超额", excess_key="excess_8w", perm=False)
    sec_51 = evaluate([r for r in recs if r["rank"] > 50], "副:Δs → 4 周超额(市值 51–200)",
                      perm=False)
    sec_bh = evaluate(recs, "副:Δs → 4 周超额(binance_hist 收盘核对)", excess_key="excess_bh")
    print("[exploratory] ...", flush=True)
    expl = exploratory(recs)

    agg = {}
    for w in weeks_meta:
        for k, v in w.items():
            if k == "week":
                continue
            agg[k] = agg.get(k, 0) + v
    out = {
        "task": "T-286", "ledger": "S-765", "author": "lane-b",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pre_reg": {
            "universe": "每周一当周 asset_mcap_daily 市值前 200 且 ohlcv_daily(binance_hist) ≥ 60 天日线",
            "feature": "Δs = s30 − s30(前 30 天);s30 = Binance close×volume ÷ CG volume,过去 30 天,严格 ≤ 周一前一日",
            "target": "之后 4 周相对 BTC 超额(标的与 BTC 同用 asset_mcap_daily.price)",
            "criteria": "(a) IC 均值>0 且 NW(4)t≥2.0;(b) 最高五分之一减最低五分之一平均超额 ≥ +1.5%;"
                        "(c) 每周内打乱(1,000 次,种子 765)分位 ≥ 0.95;(d) 两段同号",
            "drop_rules": "s30 > 1 或 CG 成交为 0;另加数据卫生:30 天窗 CG 有效天数 ≥ 25、截面 ≥ 10 格",
        },
        "counts": agg,
        "weeks": weeks_meta,
        "main": main,
        "secondary": {"level_s30": sec_level, "target_8w": sec_8w,
                      "rank_51_200": sec_51, "price_source_binance": sec_bh},
        "exploratory": expl,
    }
    if main:
        a_ok = main["mean_weekly_ic"] > 0 and main["nw_t_4lag"] >= 2.0
        b_ok = main["b_spread_pooled_excess"] >= 0.015
        c_ok = isinstance(main["c_null_percentile"], float) and main["c_null_percentile"] >= 0.95
        d_ok = (main["d_half1_mean_ic"] > 0) == (main["d_half2_mean_ic"] > 0)
        out["verdict"] = {"a": bool(a_ok), "b": bool(b_ok), "c": bool(c_ok), "d": bool(d_ok),
                          "all_pass": bool(a_ok and b_ok and c_ok and d_ok)}
    with open(RESULT_PATH + ".tmp", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    os.replace(RESULT_PATH + ".tmp", RESULT_PATH)
    print(json.dumps({k: out.get(k) for k in ("counts", "verdict")},
                     ensure_ascii=False, indent=1, default=str), flush=True)
    if main:
        print("main:", json.dumps({k: v for k, v in main.items() if k != "ic_series"},
                                  ensure_ascii=False, default=str), flush=True)
    print("RUN_DONE", RESULT_PATH, flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "fetch":
        cmd_fetch()
    elif cmd == "run":
        cmd_run()
    else:
        sys.exit("usage: t286_share.py [fetch|run]")
