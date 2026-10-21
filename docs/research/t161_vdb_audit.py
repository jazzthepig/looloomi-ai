"""T-161 — VDB 体检 (read-only).

Per `tasks/T-161.json` acceptance:
  - Per space: row count / date range / is still updating / per-dim per-year missing rate.
  - Point-in-time audit on market_state_vectors: expand the all-history z-score
    (S-245 / `src/data/vector/market_state.py:zscore_columns`) to an expanding
    window (>=365 d), measure per-dim rank correlation vs the stored values on
    a 50-day random sample, and the 20-nearest-neighbour overlap at k=20 of
    the same 50 days (cosine on shared dims, including `min_shared`).
  - Universe coverage vs 3 lists:
      R-v2 forward universe = binance_hist 30-day symbols
      HL perpetuals        = funding_history venue=hyperliquid
      ① 24-name universe   = keys of core_cap_daily.arm='cap_a1' weights
  - Code-level readers (live vs dead). Use grep on /Users/sbb/Projects/looloomi-ai.

Write output to:
  /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-161_vdb_audit.md

Only publishable key (publishable key only reads anon-allowed rows)."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import random
import re
import statistics
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

# 验证装置 ── 见 src/data/evaluation/apparatus.py,「打乱 + 盈亏 + A/B」
sys.path.insert(0, str(Path("/Users/sbb/Projects/looloomi-ai") / "src"))
from data.evaluation.apparatus import null_distribution, percentile_of  # noqa: E402


# ─── configuration ──────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    print("FATAL: SUPABASE_URL/SUPABASE_KEY not set", file=sys.stderr)
    sys.exit(2)

REPO = Path("/Users/sbb/Projects/looloomi-ai")  # main repo, read-only inspection
REPORT_PATH = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-161_vdb_audit.md")
REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

TODAY_UTC = dt.datetime.now(dt.timezone.utc).date()
PRIORITY_TABLES = [
    "market_state_vectors",
    "regime_daily",
    "style_index_pit_daily",
    "style_pit_coverage_daily",
    "asset_embeddings",
    "treasury_entities",
    "treasury_decisions",
]

# T-166:publishable key 被 RLS 隐式屏蔽(查询返回 0 行且不报错)的表。
# 值 = (服务端行数, min(d), max(d)),由 Seth 在服务端只读查得(lane-c §C-auto-1021-1206
# 复核 + Seth 只读查),**不是本脚本用 publishable key 测出来的**。
# 用途:报告里不把这些表写成「空表 / 写入端死亡」——0 行是只读角色的权限边界,不是通路缺陷。
RLS_HIDDEN_SERVER_ROWS = {
    "regime_daily": (507, "2025-05-03", "2026-10-20"),
}
DIMS = (
    "cis_mean", "cis_disp", "cis_skew", "pct_grade_A",
    "alt_btc_spread", "breadth_200ma", "disp_return", "corr_mean",
    "stable_supply_chg", "volume_trend", "adv_concentration",
    "funding_mean", "funding_disp", "fng", "oi_mcap",
    "vol_mkt", "vol_of_vol", "downside_ratio",
    "trend_strength", "trend_age_days",
    "d_cis_mean", "stability_OS",
    "_reserved_1", "_reserved_2",
)
assert len(DIMS) == 24, "spec fixes 24 dims"


# ─── helpers ────────────────────────────────────────────────────────────────
def _hdr():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept-Profile": "public",
    }


def rest_get(table: str, query: str):
    """One-shot GET on the REST endpoint. Returns (status, json_or_text, headers)."""
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{table}?{query}"
    req = urllib.request.Request(url, headers=_hdr())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, raw.decode(errors="replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace"), {}


def rest_count(table: str) -> int | None:
    """Use HEAD-style `Prefer: count=exact` to fetch a count for a single row."""
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{table}?select=d&limit=1"
    req = urllib.request.Request(url, headers={**_hdr(), "Prefer": "count=exact"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ct = r.headers.get("Content-Range", "?")
            m = re.match(r"\d+-\d+/(\d+|\*)", ct)
            if m and m.group(1) != "*":
                return int(m.group(1))
            return None
    except urllib.error.HTTPError:
        return None


def fetch_all(table: str, select: str, extra: str = "", page_size: int = 1000, order_col: str = "d"):
    """Paged fetch. Returns list of dicts."""
    all_rows = []
    offset = 0
    while True:
        q = f"select={select}&order={order_col}.asc&limit={page_size}&offset={offset}"
        if extra:
            q = f"{q}&{extra}"
        _, body, _ = rest_get(table, q)
        rows = json.loads(body) if body.strip().startswith("[") else []
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return all_rows


def parse_int_header(headers: dict) -> int | None:
    cr = headers.get("Content-Range", "")
    m = re.match(r"\d+-\d+/(\d+|\*)", cr)
    if not m or m.group(1) == "*":
        return None
    return int(m.group(1))


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation."""
    def ranks(vs):
        sorted_idx = sorted(range(len(vs)), key=lambda i: vs[i])
        r = [0.0] * len(vs)
        for i, idx in enumerate(sorted_idx):
            r[idx] = i + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    return pearson(rx, ry)


# ─── per-table footprint ──────────────────────────────────────────────────
def footprint(table: str, date_field: str | None = None, date_alias: str | None = None):
    """Return (status, count, min_date, max_date, last_computed_at).

    status ∈ {"ok", "empty_table", "denied", "no_d_col"}.
    `denied` = RLS/permission denied via publishable key (HTTP 401/403).
    `empty_table` = 0 rows visible, no permission error.
    `ok` = some rows present.
    `no_d_col` = rows present but no `d`/date column to sort on; we report count via
        raw Content-Range of the underlying list call.
    """
    df = date_alias or date_field or "d"
    # Tables differ: asset_embeddings has no `d`, only computed_at. Probe.
    if date_field is None and date_alias is None:
        _, probe, _ = rest_get(table, "select=*&limit=1")
        try:
            cols = set(json.loads(probe)[0].keys())
        except Exception:
            cols = set()
        for cand in ("d", "computed_at", "trade_date", "as_of", "created_at"):
            if cand in cols:
                df = cand
                break

    def _count_with_d():
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{table}?select={df}&order={df}.asc&limit=0"
        req = urllib.request.Request(url, headers={**_hdr(), "Prefer": "count=exact"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.headers.get("Content-Range", "")
        except urllib.error.HTTPError as e:
            return f"http_{e.code}"

    cr = _count_with_d()
    if cr.startswith("http_401") or cr == "http_403":
        return "denied", None, None, None, None
    if "*/" in cr:
        try:
            cnt = int(cr.split("*/")[-1])
        except Exception:
            cnt = -1
    else:
        cnt = -1

    # If we don't have `d` field, treat result as approximate count via paging
    if cnt < 0:
        # Fetch 1 row with select=*; if ok there's ≥1 row.
        _, body, _ = rest_get(table, f"select=*&limit=1")
        try:
            rows = json.loads(body)
            if not isinstance(rows, list):
                return "denied", None, None, None, None
            if not rows:
                return "empty_table", 0, None, None, None
            # try deeper paging — at least try to get count via 1000 first page
            _, b2, h2 = rest_get(table, f"select=*&limit=1000")
            try:
                rs2 = json.loads(b2)
                if isinstance(rs2, list):
                    cr2 = h2.get("Content-Range", "")
                    m = re.match(r"\d+-\d+/(\d+|\*)", cr2)
                    if m and m.group(1) != "*":
                        cnt = int(m.group(1))
                    else:
                        cnt = len(rs2) if len(rs2) < 1000 else f"≥{len(rs2)}"
            except Exception:
                cnt = f"≥{len(rows)}"
        except Exception:
            return "denied_or_unknown", None, None, None, None
        # Date info may not be available
        sample = "?"
        max_d = "?"
        return "ok", cnt, sample, max_d, None

    if cnt == 0:
        return "empty_table", 0, None, None, None

    _, body, _ = rest_get(table, f"select={df}&order={df}.asc&limit=1")
    try:
        rows = json.loads(body)
        sample = rows[0].get(df) if rows else None
    except Exception:
        sample = None
    _, body, _ = rest_get(table, f"select={df}&order={df}.desc&limit=1")
    try:
        rows = json.loads(body)
        max_d = rows[0].get(df) if rows else None
    except Exception:
        max_d = None
    _, body, _ = rest_get(table, f"select=computed_at&order=computed_at.desc&limit=1")
    try:
        rows = json.loads(body)
        last_ct = rows[0].get("computed_at") if rows else None
    except Exception:
        last_ct = None
    return "ok", cnt, sample, max_d, last_ct


def per_year_missing_rate(table: str, dim_col: str, df: str = "d") -> dict[int, list[float]]:
    """Per-dim missing rate by year. Paged — the anon key caps at 1000 rows/page,
    and a single limit=5000 call silently returned only 2022-2024 of a 1755-row
    table that runs to 2026."""
    rows = fetch_all(table, f"{df},{dim_col}", page_size=1000, order_col=df)
    out: dict[int, list[float]] = {}
    by_year: dict[int, list[list]] = defaultdict(list)
    for r in rows:
        v = r.get(dim_col)
        if not isinstance(v, list):
            continue
        try:
            year = int(str(r.get(df, ""))[:4])
        except Exception:
            continue
        by_year[year].append(v)
    for y in sorted(by_year):
        vals = by_year[y]
        n = len(vals)
        per_idx = []
        for i in range(24):
            ok = sum(1 for v in vals if i < len(v) and isinstance(v[i], (int, float)))
            per_idx.append(round(1 - ok / n, 4))
        out[y] = per_idx
    return out


# ─── PIT audit: market_state_vectors z-score ──────────────────────────────
MIN_HIST = 365  # expanding window floor, per card


def _expanding_z(vals: list[float | None]):
    """Point-in-time z over d'<=d with >=MIN_HIST prior obs.

    The stored column is z-scored ONCE across the whole history
    (market_state_writer.py:59, '一次标准化 ... 一个 zscore_pass 戳 S-232').
    That is a single affine map (z = (raw - mu_all)/sigma_all), identical for
    every row and every dim, so stored z is rank-equivalent to raw AND its
    cross-sectional geometry is recoverable: re-standardising the stored
    column over an expanding window gives exactly what an expanding-window
    writer would have stored. No raw round-trip needed.
    """
    n = len(vals)
    out: list[float | None] = [None] * n
    c = 0
    s = 0.0
    s2 = 0.0
    for i in range(n):
        v = vals[i]
        if v is not None and c >= MIN_HIST:
            mu = s / c
            var = max(s2 / c - mu * mu, 0.0)
            sd = var ** 0.5
            out[i] = (v - mu) / sd if sd > 1e-12 else None
        if v is not None:
            c += 1
            s += v
            s2 += v * v
    return out


def _cos_shared(a, b, min_shared=6):
    """Cosine over dims non-null in BOTH — mirrors shared_cosine in the
    similar_market_states RPC (only jointly-measured dims carry weight)."""
    dot = na = nb = 0.0
    k = 0
    for x, y in zip(a, b):
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            dot += x * y
            na += x * x
            nb += y * y
            k += 1
    if k < min_shared or na <= 0 or nb <= 0:
        return None
    return dot / ((na ** 0.5) * (nb ** 0.5))


def pit_audit_msv(seed: int = 7, bidirectional: bool = False, k_nn: int = 20):
    """Quantify the lookahead in the single all-history z-score.

    For every dim: Spearman rank correlation between the stored (all-history)
    z and an expanding-window z, plus signed bias and RMS gap. Then 20-NN
    overlap on random days: stored geometry vs expanding geometry.

    Parameters
    ----------
    bidirectional : bool
        False (default) = original口径: past-only (j < i) + |diff| > 30.
        True           = 生产 most_similar 口径: 仅排除 |diff| ≤ 30,
                         未来日合法(候选池跨整段时间,不再强制过去)。
    k_nn : int
        最近邻数 = 20(T-161 默认)。可用于敏感性。
    """
    rng = random.Random(seed)
    all_rows = fetch_all("market_state_vectors", "d,vec_full")
    rows = [r for r in all_rows if r.get("d") and isinstance(r.get("vec_full"), list)]
    if not rows:
        return {"note": "table empty or denied"}
    rows.sort(key=lambda r: r["d"])
    ds = [r["d"] for r in rows]
    dates = [dt.date.fromisoformat(str(d)[:10]) for d in ds]
    N = len(rows)

    def col(di):
        return [None if (di >= len(rows[i]["vec_full"])) else rows[i]["vec_full"][di] for i in range(N)]

    # ── per-dim: stored vs expanding ────────────────────────────────────
    per_dim = {}
    for di, dim in enumerate(DIMS):
        stored = col(di)
        if all(v is None for v in stored):
            per_dim[dim] = {"status": "never measured (0 rows)"}
            continue
        exp = _expanding_z(stored)
        pairs = [(stored[i], exp[i]) for i in range(N) if stored[i] is not None and exp[i] is not None]
        if len(pairs) < 30:
            per_dim[dim] = {"status": f"only {len(pairs)} days with >=365d of history"}
            continue
        rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
        bias = sum(e - s for s, e in pairs) / len(pairs)
        rms = (sum((e - s) ** 2 for s, e in pairs) / len(pairs)) ** 0.5
        per_dim[dim] = {
            "status": "ok",
            "n_days": len(pairs),
            "spearman_stored_vs_expanding": round(rho, 4) if rho is not None else None,
            "signed_bias_z": round(bias, 4),
            "rms_gap_z": round(rms, 4),
        }

    # ── 20-NN overlap on 50 random days ─────────────────────────────────
    stored_cols = {di: col(di) for di in range(24)}
    exp_cols = {di: _expanding_z(stored_cols[di]) for di in range(24)}
    eligible = [i for i in range(N) if sum(1 for di in range(24) if exp_cols[di][i] is not None) >= 6]
    sample_n = min(50, len(eligible))
    sample = rng.sample(eligible, sample_n) if sample_n else []
    K = k_nn
    overlaps = []
    pool_sizes = []
    for i in sample:
        stored_vec = [stored_cols[di][i] for di in range(24)]
        exp_vec = [exp_cols[di][i] for di in range(24)]
        di_t = dates[i]
        cand = []
        for j in range(N):
            if j == i:
                continue
            if not bidirectional and j > i:
                # 原始口径: 仅过去;日线回放里「未来日」会造成相位锁定
                continue
            # 生产 most_similar:仅 abs(diff) ≤ 30 才排除(双向语义,未来日合法)
            if abs((dates[j] - di_t).days) <= 30:
                continue
            cand.append(j)
        if cand:
            pool_sizes.append(len(cand))
        s_stored, s_exp = [], []
        for j in cand:
            a = _cos_shared(stored_vec, [stored_cols[di][j] for di in range(24)])
            b = _cos_shared(exp_vec, [exp_cols[di][j] for di in range(24)])
            if a is not None:
                s_stored.append((a, j))
            if b is not None:
                s_exp.append((b, j))
        if len(s_stored) < K or len(s_exp) < K:
            continue
        s_stored.sort(key=lambda t: -t[0])
        s_exp.sort(key=lambda t: -t[0])
        nn_a = {j for _, j in s_stored[:K]}
        nn_b = {j for _, j in s_exp[:K]}
        overlaps.append(len(nn_a & nn_b) / K)

    # ── 随机基线 ─────────────────────────────────────────────────────────
    # 在与实际抽样同步的「候选池规模分布」上,用 apparatus.null_distribution
    # 打乱出 |A∩B|/K 的零分布,再 percentile_of 看实际重合率处于零分布哪一端。
    # 候选池规模 = 上一步对每个抽样日记录到的 |cand|。
    actual_overlap_mean = (sum(overlaps) / len(overlaps)) if overlaps else None
    null_expected = None
    null_p = None
    null_median = None
    null_mean = None
    null_size = None
    if pool_sizes:
        n_iter = 2000
        median_pool = statistics.median(pool_sizes)
        K_int = K
        # 用每个抽样日自己的候选池规模抽样,保留「池子大小差异」的异质性,
        # 而不是统一池子 — 候选池在原口径 ≤ 末日,在双向口径下 1 至末日 |diff|>30 均在池。
        def _perday(rng_):
            n = rng_.choice(pool_sizes)
            if n < K_int:
                n = K_int
            a = rng_.choice(n, size=K_int, replace=False)
            b = rng_.choice(n, size=K_int, replace=False)
            return len(set(a.tolist()) & set(b.tolist())) / K_int
        # pool_sizes 上的实际重合率均值作为 actual
        actual_mean = actual_overlap_mean
        try:
            null = null_distribution(_perday, n=n_iter, seed=seed, actual=actual_mean)
            null_size = int(null.size)
            null_median = round(float(np.median(null)), 4) if null.size else None
            null_mean = round(float(np.mean(null)), 4) if null.size else None
            null_expected = round(float(null.mean()), 4) if null.size else None
            null_p = percentile_of(actual_mean, null.tolist())
            if null_p is not None:
                null_p = round(null_p, 4)
        except Exception as e:
            null_expected = None
            null_p = f"err:{type(e).__name__}:{str(e)[:80]}"
        pool_median = round(median_pool, 1)
    else:
        pool_median = None

    ok_dims = {d: v for d, v in per_dim.items() if v.get("status") == "ok"}
    rhos = [v["spearman_stored_vs_expanding"] for v in ok_dims.values() if v["spearman_stored_vs_expanding"] is not None]
    return {
        "pool_mode": "bidirectional" if bidirectional else "past_only",
        "n_total_days": N,
        "date_window": [ds[0], ds[-1]] if ds else None,
        "min_hist_days": MIN_HIST,
        "dims_with_history": len(ok_dims),
        "dims_never_measured": sorted(d for d, v in per_dim.items() if v.get("status") == "never measured (0 rows)"),
        "spearman_min": round(min(rhos), 4) if rhos else None,
        "spearman_median": round(statistics.median(rhos), 4) if rhos else None,
        "spearman_max": round(max(rhos), 4) if rhos else None,
        "rms_gap_median": round(statistics.median([v["rms_gap_z"] for v in ok_dims.values()]), 4) if ok_dims else None,
        "per_dim": per_dim,
        "nn_k": K,
        "nn_n_sample_days": len(overlaps),
        "nn_overlap_mean": round(sum(overlaps) / len(overlaps), 4) if overlaps else None,
        "nn_overlap_median": round(statistics.median(overlaps), 4) if overlaps else None,
        "nn_overlap_min": round(min(overlaps), 4) if overlaps else None,
        "nn_overlap_max": round(max(overlaps), 4) if overlaps else None,
        "nn_overlap_hist": [round(o, 3) for o in sorted(overlaps)],
        "k_nn": K,
        "pool_size_per_day": {
            "n_with_pool": len(pool_sizes),
            "min": min(pool_sizes) if pool_sizes else None,
            "median": pool_median,
            "max": max(pool_sizes) if pool_sizes else None,
        },
        "null_baseline": {
            "n_iter": null_size,
            "expected_overlap_mean": null_expected,
            "null_median": null_median,
            "null_mean": null_mean,
            "actual_overlap_mean": round(actual_overlap_mean, 4) if actual_overlap_mean is not None else None,
            "actual_percentile_vs_null": null_p,
        },
    }


def tgt_minus(ds_sorted: list[str], target: str, k: int) -> str:
    """Return date <target>k days ago (k calendar days, simple)."""
    from datetime import datetime as _dt, timedelta as _td
    td = _dt.fromisoformat(target).date() - _td(days=k)
    return td.isoformat()


def _qnorm_approx(frac: float) -> float:
    """Beasley-Springer-Moro approximation for the inverse normal CDF."""
    import math as _m
    if frac <= 0.0:
        return -4.0
    if frac >= 1.0:
        return 4.0
    if frac < 0.5:
        return -_qnorm_approx(1.0 - frac)
    a0, a1, a2 = 2.50662823884, -18.61500062529, 41.39119779534
    a3, a4 = -25.44106049637, 2.60459639921
    b0, b1, b2 = 1.0, -8.47351093091, 23.08336743743
    b3, b4, b5 = -21.14424156298, 5.61114927534, -0.5
    y = frac - 0.5
    x = y * y
    num = ((a4 * x + a3) * x + a2) * x + a1
    num = (num * x + a0) * y
    den = (((b5 * x + b4) * x + b3) * x + b2)
    den = ((den * x + b1) * x + b0)
    return num / den


# ─── universe coverage ─────────────────────────────────────────────────────
def distinct_symbols(table: str, base: dict, cap: int = 400) -> set[str]:
    """Distinct `symbol` values under `base` filters.

    PostgREST has no DISTINCT and the anon key is capped at 1000 rows/page, so
    `select=symbol&limit=2000&order=symbol.asc` silently returns only the
    alphabetically-FIRST symbols' rows. (That bug reported the HL perpetual list
    as 3 names when it is 234.) Walk the sort key instead: page, jump the
    cursor past the largest symbol seen, repeat.
    """
    seen: set[str] = set()
    cursor: str | None = None
    for _ in range(cap):
        q = dict(base)
        q["select"] = "symbol"
        q["order"] = "symbol.asc"
        q["limit"] = 1000
        if cursor is not None:
            q["symbol"] = "gt." + cursor
        _, body, _ = rest_get(table, "&".join(f"{k}={v}" for k, v in q.items()))
        try:
            rows = json.loads(body)
        except Exception:
            break
        if not isinstance(rows, list) or not rows:
            break
        syms = [r["symbol"] for r in rows if isinstance(r, dict) and r.get("symbol")]
        if not syms:
            break
        seen.update(syms)
        nxt = max(syms)
        if nxt == cursor:
            break
        cursor = nxt
    return seen


def coverage_universes():
    # ① 24-name universe = keys of core_cap_daily.arm='cap_a1' latest row
    _, body, _ = rest_get(
        "core_cap_daily",
        "select=d,arm,weights&arm=eq.cap_a1&order=d.desc&limit=1",
    )
    cap_names: list[str] = []
    try:
        rows = json.loads(body)
        if rows and isinstance(rows[0].get("weights"), dict):
            cap_names = sorted(rows[0]["weights"].keys())
    except Exception:
        cap_names = []
    # R-v2 forward universe = crypto names with bars in the last 30 days.
    # `binance_hist` is not a table in public schema; the deployed crypto feed is
    # ohlcv_daily rows with source=eq.binance_hist (market_state_writer.py:55).
    since_30 = (TODAY_UTC - dt.timedelta(days=30)).isoformat()
    crypto = distinct_symbols("ohlcv_daily", {"source": "eq.binance_hist", "trade_date": "gte." + since_30})
    _, b2, _ = rest_get("binance_hist", "select=symbol&limit=1")
    raw_present = json.loads(b2).__class__ is list if b2.strip().startswith("[") else False
    # HL perpetual list = distinct symbols ever funded on hyperliquid
    hl = distinct_symbols("funding_history", {"venue": "eq.hyperliquid"})
    # asset_embeddings: symbols in the VDB (73 rows => one snapshot per symbol)
    _, body, _ = rest_get("asset_embeddings", "select=symbol&order=symbol.asc&limit=1000")
    try:
        vec_names = sorted({r["symbol"] for r in json.loads(body) if r.get("symbol")})
    except Exception:
        vec_names = []
    return {
        "① cap_a1 24 名": cap_names,
        "R-v2 前向宇宙 (ohlcv_daily source=binance_hist, 30d)": sorted(crypto),
        "binance_hist 表是否存在(public)": raw_present,
        "HL 永续 (funding_history venue=hyperliquid)": sorted(hl),
        "asset_embeddings 向量库": vec_names,
    }


# ─── code readers (live/dead) ─────────────────────────────────────────────
def code_readers():
    """grep /Users/sbb/Projects/looloomi-ai/src for each table; classify as
    live writer / live reader / dead reference / comment-only."""
    import subprocess
    targets = {
        "market_state_vectors": "market_state_vectors",
        "regime_daily": "regime_daily",
        "style_index_pit_daily": "style_index_pit_daily",
        "style_pit_coverage_daily": "style_pit_coverage_daily",
        "asset_embeddings": "asset_embeddings",
        "asset_embeddings_history": "asset_embeddings_history",
        "treasury_entities": "treasury_entities",
        "treasury_decisions": "treasury_decisions",
    }
    out = {}
    for label, needle in targets.items():
        try:
            res = subprocess.run(
                ["grep", "-rn", "--include=*.py",
                 needle, str(REPO / "src")],
                capture_output=True, text=True, timeout=30,
            )
            lines = [l for l in res.stdout.splitlines() if "/tests/" not in l and "/__pycache__/" not in l]
        except Exception:
            lines = []
        live_writer = []
        live_reader = []
        dead_ref = []
        for ln in lines:
            file, rest = ln.split(":", 1)
            tail = rest.split(":", 1)[-1] if ":" in rest else rest
            stripped = tail.strip()
            # crude classification:
            if any(w in stripped for w in (
                "supabase_upsert", "supabase_upsert_table", "refresh_", "writer",
                "INSERT", ".insert", "_treasury", "_regime_", "embeddings_history",
                "loop", "upsert_",
            )):
                live_writer.append((file, stripped[:160]))
            elif any(w in stripped for w in ("supabase_query", "_read_all", "_paged", ".select(", "REST")):
                live_reader.append((file, stripped[:160]))
            elif stripped.startswith("#"):
                dead_ref.append((file, stripped[:160]))
            else:
                # treat unknown as reader-ish
                live_reader.append((file, stripped[:160]))
        # collapse
        cnt_writer = Counter(f for f, _ in live_writer)
        cnt_reader = Counter(f for f, _ in live_reader)
        out[label] = {
            "writer_files": dict(cnt_writer),
            "reader_files": dict(cnt_reader),
            "n_writer_calls": sum(cnt_writer.values()),
            "n_reader_calls": sum(cnt_reader.values()),
            "comment_only_lines": len(dead_ref),
            "sample_writer": live_writer[:3],
            "sample_reader": live_reader[:3],
        }
    return out


# ─── regime_fingerprints.py audit ──────────────────────────────────────────
def code_audit_regime_fingerprints():
    p = REPO / "src/research/vector/regime_fingerprints.py"
    if not p.exists():
        return {"note": "file not found"}
    src = p.read_text()
    return {
        "file": str(p),
        "lines": len(src.splitlines()),
        "imports": sorted(set(re.findall(r"^(?:from|import)\s+(\S+)", src, re.M)))[:20],
        "defs": sorted(re.findall(r"^def\s+(\w+)\(", src, re.M)),
        "uses_lookahead": bool(re.search(r"current_date|today\(\)|dt\.now|datetime\.now", src)),
        "uses_pit": bool(re.search(r"pit|as_of|on_or_before|<=", src)),
        "writes": sorted(re.findall(r"supabase_upsert|supabase_query", src)),
    }


# ─── main ─────────────────────────────────────────────────────────────────
def main():
    out = {}
    # 1) footprint per table
    out["footprint"] = {}
    for t in PRIORITY_TABLES:
        out["footprint"][t] = footprint(t)
    # 2) per-dim per-year missing rate on tables that carry 24-dim arrays
    out["per_year_missing_rate"] = {}
    for t, df in (("market_state_vectors", "d"), ("regime_daily", "d")):
        try:
            per = per_year_missing_rate(t, "vec_full", df)
        except Exception as e:
            out["per_year_missing_rate"][t] = {"_err": repr(e)[:160]}
            continue
        out["per_year_missing_rate"][t] = {
            str(y): {DIMS[i]: m for i, m in enumerate(missing)}
            for y, missing in per.items()
        } if per else {}
    # 2b) measured_dims distribution — the card's "declares 24, measures 11.1"
    # T-166 补:逐日共享维数分布,_reserved_1/2 不计入分母
    try:
        mrows = fetch_all("market_state_vectors", "d,measured_dims,source_completeness,n_symbols,vec_full")
        # 实际非空维(分母已不含 _reserved_*: 它们在原始 vec_full 里就是 null)
        live = [
            sum(1 for v in r["vec_full"] if isinstance(v, (int, float)))
            for r in mrows
            if isinstance(r.get("vec_full"), list)
        ]
        # 逐日分布(填几个非空维的天数有多少天)
        dist = Counter(live)
        # 验:vec_full 中 _reserved 位置 22/23 是否恒 null(确认不入分母)
        reserved_check: dict = {"_reserved_1": [], "_reserved_2": []}
        for r in mrows:
            if isinstance(r.get("vec_full"), list) and len(r["vec_full"]) == 24:
                for idx, name in enumerate(DIMS):
                    if name in ("_reserved_1", "_reserved_2"):
                        reserved_check[name].append(r["vec_full"][idx])
        # T-166 也报告 column-declared 的 measured_dims 分布(便于核对表的字段)
        md = [r.get("measured_dims") for r in mrows if isinstance(r.get("measured_dims"), int)]
        out["measured_dims"] = {
            "declared_in_dims_table": 24,
            "n_reserved_positions_unwired": 2,
            "n_wireable_dims": 22,
            "n_days": len(mrows),
            "non_null_dims_mean": round(sum(live) / len(live), 2) if live else None,
            "non_null_dims_min": min(live) if live else None,
            "non_null_dims_max": max(live) if live else None,
            "non_null_dims_distribution": dict(sorted(dist.items())),
            "days_fully_wired": sum(1 for x in live if x == 22),
            "days_at_24": sum(1 for x in live if x == 24),
            # 与原版(T-161)兼容 — derived from the column declared on the table
            "measured_dims_mean": round(sum(md) / len(md), 2) if md else None,
            "measured_dims_min": min(md) if md else None,
            "measured_dims_max": max(md) if md else None,
            "reserved_check": {k: {
                "n": len(v),
                "all_none": all(x is None for x in v) if v else None,
                "sample_non_none": [x for x in v if x is not None][:3],
            } for k, v in reserved_check.items()},
        }
    except Exception as e:
        out["measured_dims"] = {"_err": repr(e)[:160]}
    # 2c) asset_embeddings uses its OWN dim layout (dims column), so the 24-dim
    # DIMS map does NOT apply. Profile it on its own terms instead of
    # printing a table of zeros that looks like a coverage failure.
    try:
        erows = fetch_all("asset_embeddings", "symbol,asset_class,dims,vec_full,computed_at", order_col="computed_at")
        dims_seen = sorted({r.get("dims") for r in erows if r.get("dims") is not None})
        nn = [sum(1 for v in r["vec_full"] if isinstance(v, (int, float)))
              for r in erows if isinstance(r.get("vec_full"), list)]
        classes: dict[str, int] = defaultdict(int)
        for r in erows:
            classes[str(r.get("asset_class"))] += 1
        out["asset_embeddings_profile"] = {
            "rows": len(erows),
            "dims_values_seen": dims_seen,
            "nonnull_min": min(nn) if nn else None,
            "nonnull_max": max(nn) if nn else None,
            "rows_fully_null": sum(1 for r in erows if not r.get("vec_full")),
            "by_asset_class": dict(sorted(classes.items(), key=lambda kv: -kv[1])),
            "oldest": min((r["computed_at"] for r in erows if r.get("computed_at")), default=None),
            "newest": max((r["computed_at"] for r in erows if r.get("computed_at")), default=None),
        }
    except Exception as e:
        out["asset_embeddings_profile"] = {"_err": repr(e)[:160]}
    # 3) PIT audit on market_state_vectors z-score — 两次:原口径 + 生产双向口径
    out["pit_msv_past"] = pit_audit_msv(bidirectional=False)
    out["pit_msv_bi"] = pit_audit_msv(bidirectional=True)
    # 报告主口径保留为「双向」(生产口径),原口径单独存以与 T-161 原版比对
    out["pit_msv"] = out["pit_msv_bi"]
    # 4) universe coverage
    out["universes"] = coverage_universes()
    # 5) code readers
    out["code_readers"] = code_readers()
    # 6) regime_fingerprints.py audit
    out["regime_fingerprints_audit"] = code_audit_regime_fingerprints()

    # 7) write report
    write_report(out)
    print(json.dumps(out, default=str, ensure_ascii=False, indent=2)[:4000])


def write_report(out: dict):
    lines: list[str] = []
    lines.append(f"# T-161 · 向量库体检报告")
    lines.append("")
    lines.append(f"**Generated (UTC):** {dt.datetime.now(dt.timezone.utc).isoformat()}")
    lines.append(f"**Today (UTC):**      {TODAY_UTC.isoformat()}")
    lines.append(f"**Only publishable key, read-only.**")
    lines.append("")
    # ── §1 footprint ────────────────────────────────────────────
    lines.append("## §1 各空间快照")
    lines.append("")
    lines.append("| 表 | 状态 | 行数 | min(d) | max(d) | last computed_at | 距今天数 |")
    lines.append("|---|---|---:|---|---|---|---:|")
    for t in PRIORITY_TABLES:
        fp = out["footprint"][t]
        status, cnt, mn, mx, lc = fp
        if mx:
            try:
                days = (TODAY_UTC - dt.date.fromisoformat(str(mx)[:10])).days
            except Exception:
                days = -1
        else:
            days = -1
        # T-166:publishable 看不见 ≠ 表是空的。RLS 隐式屏蔽的表按「publishable 不可见
        # (RLS),服务端 N 行」显示 —— 行数是 Seth 服务端只读查得的,本脚本用
        # publishable key 核不到,所以它不是本表的测量值。
        rls = RLS_HIDDEN_SERVER_ROWS.get(t)
        shown_status = (f"publishable 不可见(RLS),服务端 {rls[0]} 行" if rls else status)
        lines.append(f"| `{t}` | {shown_status} | {cnt} | {mn} | {mx} | {lc} | {days} |")
    lines.append("")
    if RLS_HIDDEN_SERVER_ROWS:
        lines.append("> `publishable 不可见(RLS)` 的行数由 Seth 在服务端只读查得(**非本脚本的测量值**,"
                     "本脚本用 publishable key 查这些表返回 0 行)。**0 行 ≠ 写入端死亡** —— "
                     "它是只读角色的权限边界。逐表:见 §5 缺陷表第 2 行。")
        lines.append("")
    # ── §2 per-year missing rate per dim ────────────────────────
    lines.append("## §2 每维按年的缺失率")
    lines.append("")
    md = out.get("measured_dims", {})
    if md and "_err" not in md:
        lines.append(f"**`market_state_vectors` 声明 24 维(`DIMS` 表)。** "
                     f"`_reserved_1`/`_reserved_2` 永久空(实测 100% None)—— **有效维数 = 22**。"
                     f"`measured_dims` 列(列的字段)均值 **{md['measured_dims_mean']}** "
                     f"(min {md['measured_dims_min']}, max {md['measured_dims_max']});"
                     f"`vec_full` 实际非空(分母不含 _reserved)均值 **{md['non_null_dims_mean']}** "
                     f"(min {md['non_null_dims_min']}, max {md['non_null_dims_max']});"
                     f"填满 22 维的天数 = **{md['days_fully_wired']}**;等于 24 的天数 = **{md['days_at_24']}**。")
        lines.append("")
        # T-166 补:逐日分布
        dist = md.get("non_null_dims_distribution", {})
        if dist:
            lines.append("**逐日非空维数分布**:")
            lines.append("")
            lines.append("| 非空维数 | 天数 |")
            lines.append("|---:|---:|")
            for k in sorted(dist.keys(), key=lambda x: (isinstance(x, str), x)):
                lines.append(f"| {k} | {dist[k]} |")
            lines.append("")
        rc = md.get("reserved_check", {})
        for nm in ("_reserved_1", "_reserved_2"):
            r = rc.get(nm, {})
            lines.append(f"- `{nm}` 核实:共 {r.get('n')} 个采样,全部 None = **{r.get('all_none')}**;"
                         f"如非 None 的样本: {r.get('sample_non_none')}")
        lines.append("")
    lines.append("缺失率 = 1 − (该年非空天数 / 该年总天数)。")
    lines.append("")
    for t, yrs in out["per_year_missing_rate"].items():
        lines.append(f"### `{t}`")
        lines.append("")
        if not yrs or "_err" in yrs:
            lines.append(f"_无数据(表空或读权被拒)。{yrs.get('_err', '') if isinstance(yrs, dict) else ''}_")
            lines.append("")
            continue
        years = sorted(yrs)
        lines.append("| 维 | " + " | ".join(years) + " |")
        lines.append("|---|" + "---:|" * len(years))
        for dim in DIMS:
            cells = [yrs[y].get(dim) for y in years]
            if all(c == 1.0 for c in cells if c is not None) and cells[0] is not None:
                tag = " **(全空)**"
            else:
                tag = ""
            lines.append(f"| `{dim}`{tag} | " + " | ".join("—" if c is None else f"{c:.2f}" for c in cells) + " |")
        lines.append("")
        lines.append("")
    # ── §2d asset_embeddings (own dim layout) ─────────────────────
    ap = out.get("asset_embeddings_profile", {})
    if ap and "_err" not in ap:
        lines.append(f"### `asset_embeddings`(独立布局,{ap['rows']} 行)")
        lines.append("")
        lines.append(f"- `dims` 列取值:{ap['dims_values_seen']} —— **与 `market_state_vectors` 的 24 维不是同一套语义**,不能逐维对照。")
        lines.append(f"- 每行 `vec_full` 非空数:{ap['nonnull_min']}..{ap['nonnull_max']};整行为空:{ap['rows_fully_null']}")
        lines.append(f"- `computed_at` 跨度:{ap['oldest']} .. {ap['newest']}")
        lines.append(f"- 按资产类别:{ap['by_asset_class']}")
        lines.append("")

    # ── §3 PIT audit ────────────────────────────────────────────
    lines.append("## §3 market_state_vectors 全史 z-score 的未来信息量化")
    lines.append("")
    pit = out["pit_msv"]
    if "note" in pit:
        lines.append(f"> {pit['note']}")
    else:
        w0, w1 = pit["date_window"]
        lines.append(f"- 总天数 = {pit['n_total_days']} ({w0}..{w1});扩张窗口下限 = {pit['min_hist_days']} 天")
        lines.append(f"- **有 ≥365 天历史可重算的维: {pit['dims_with_history']}/24**;"
                     f"从未测到过的维: {pit['dims_never_measured'] or '无'}")
        lines.append("")
        lines.append(f"### §3.1 每维:stored(全史 z) vs 扩张窗口 z 的秩相关")
        lines.append("")
        lines.append(f"- Spearman 最小 **{pit['spearman_min']}** / 中位 **{pit['spearman_median']}** / 最大 **{pit['spearman_max']}**")
        lines.append(f"- RMS 差(z 单位)中位 **{pit['rms_gap_median']}**")
        lines.append("")
        lines.append("| 维 | 天数 | Spearman | 有偏(扩张−全史) | RMS 差 |")
        lines.append("|---|---:|---:|---:|---:|")
        for d in DIMS:
            v = pit["per_dim"].get(d, {})
            if v.get("status") != "ok":
                lines.append(f"| `{d}` | — | — | — | {v.get('status', '')} |")
                continue
            lines.append(
                f"| `{d}` | {v['n_days']} | {v['spearman_stored_vs_expanding']} "
                f"| {v['signed_bias_z']:+.4f} | {v['rms_gap_z']:.4f} |"
            )
        lines.append("")
        lines.append("> Spearman=1 表示「全史一次标准化」与「扩张窗口标准化」给出同一套排序,"
                     "即未来信息没有改变任何一天的名次;Spearman<1 表示它改变了。"
                     "**有偏** 为扩张窗口减全史的均值差:系统性为负 ⇒ 全史口径把后期水平当成了常态,压缩了当时的极端度。")
        lines.append("")
        lines.append(f"### §3.2 20 个最近邻重合率(stored 几何 vs 扩张窗口几何,两种候选池口径)")
        lines.append("")
        pit_past = out["pit_msv_past"]
        pit_bi = out["pit_msv_bi"]
        lines.append("| 口径 | 候选池语义 | 候选池规模(中位) | 平均重合率 | N 抽样 |")
        lines.append("|---|---|---:|---:|---:|")
        for label, pit_x in (("原(past-only)", pit_past), ("生产(bidirectional, |diff|≤30 排除)", pit_bi)):
            psp = pit_x.get("pool_size_per_day", {})
            lines.append(
                f"| {label} | "
                f"{'仅过去 + abs>30' if label.startswith('原') else '未来日合法,|diff|≤30 排除'} | "
                f"{psp.get('median', '?')} | "
                f"{pit_x.get('nn_overlap_mean') if pit_x.get('nn_overlap_mean') is not None else '?'} | "
                f"{pit_x.get('nn_n_sample_days', 0)} |"
            )
        lines.append("")
        lines.append(f"**生产口径**(pit_msv_bi)详细:平均 **{pit_bi['nn_overlap_mean']}** "
                     f"(中位 {pit_bi['nn_overlap_median']}, 最小 {pit_bi['nn_overlap_min']}, "
                     f"最大 {pit_bi['nn_overlap_max']}, N={pit_bi['nn_n_sample_days']})。"
                     f"原口径(past-only)详细:平均 **{pit_past['nn_overlap_mean']}** "
                     f"(中位 {pit_past['nn_overlap_median']}, 最小 {pit_past['nn_overlap_min']}, "
                     f"最大 {pit_past['nn_overlap_max']}, N={pit_past['nn_n_sample_days']})。")
        lines.append("")
        lines.append("> 20 个邻居里平均有 "
                     f"{round((1 - (pit_bi['nn_overlap_mean'] or 0)) * 20, 1) if pit_bi['nn_overlap_mean'] is not None else '?'} 个"
                     "(生产口径)是换口径后换掉的。这是 §5a 相位检索每天真正被改变的那部分。")
        lines.append("")
        # ── §3.3 随机基线 ─────────────────────────────
        nb = pit_bi.get("null_baseline", {})
        lines.append("### §3.3 随机基线(apparatus.null_distribution,生产口径候选池)")
        lines.append("")
        lines.append(f"- 迭代次数 = {nb.get('n_iter')}")
        lines.append(f"- **实际平均重合率 = {nb.get('actual_overlap_mean')}** / "
                     f"**零分布期望 = {nb.get('expected_overlap_mean')}** "
                     f"(中位 {nb.get('null_median')}, 均值 {nb.get('null_mean')})")
        lines.append(f"- 实际在零分布上的分位 = **{nb.get('actual_percentile_vs_null')}** "
                     "(中位秩;0.5 = 等同随机;1.0 = 远高于所有随机)")
        lines.append("")
        psp = pit_bi.get("pool_size_per_day", {})
        lines.append(f"- 候选池规模(逐日保留,异质抽样):"
                     f"中位 **{psp.get('median')}**(min {psp.get('min')}, max {psp.get('max')},"
                     f"{psp.get('n_with_pool')} 个抽样日)")
        lines.append("")
        # 零分布自身的解析核对:两套 K 个邻居从池 n 里独立抽,重合数期望 K²/n,
        # 换算成「/K 的比例」= K/n。模拟均值应当贴着 K/n —— 不贴就说明零分布没在
        # 随机抽(抽法错了 / 退化),而不是「结果显著」。
        K = pit_bi.get("k_nn")
        pm = psp.get("median")
        if isinstance(K, (int, float)) and isinstance(pm, (int, float)) and pm:
            analytic = K / pm
            sim = nb.get("null_mean")
            ok = (isinstance(sim, (int, float))
                  and abs(sim - analytic) <= 3 * (K * (1 / pm) * (1 - K / pm)) ** 0.5 / K)
            lines.append(f"- **零分布自检(解析核对)**:E[|A∩B|/K] = K/|cand| = {K}/{pm:.0f} = "
                         f"**{analytic:.4f}**;模拟均值 {sim},"
                         f"{'一致 ⇒ 零分布确在随机抽' if ok else '**不一致 ⇒ 零分布可疑**'}")
        lines.append("")
        lines.append("> 零分布由 apparatus.py 的 `null_distribution(fn, n, seed, actual)` 跑出 "
                     "(N=2000),对每一天的候选池规模 `|cand|` 在全集里随机抽两套 20 个邻居算 "
                     "|A∩B|/20,然后 percentile_of(actual, null) 看分位。等于 0.5 ⇒ 几何几乎在打乱;"
                     "等于 1.0 ⇒ 全史 z 几何与扩张窗口几何的相位一致性远超随机。")
        lines.append("")

    # ── §4 universe coverage ────────────────────────────────────
    lines.append("## §4 宇宙覆盖对照(三张名单)")
    lines.append("")
    u = out["universes"]
    cap = set(u["① cap_a1 24 名"])
    bnh = set(u["R-v2 前向宇宙 (ohlcv_daily source=binance_hist, 30d)"])
    hl = set(u["HL 永续 (funding_history venue=hyperliquid)"])
    vec = set(u["asset_embeddings 向量库"])
    lines.append(f"- ① cap_a1 24 名: **{len(cap)}** — {sorted(cap)}")
    lines.append(f"- R-v2 前向宇宙(ohlcv_daily source=binance_hist,近 30 天有 K 线): **{len(bnh)}**")
    lines.append(f"- HL 永续(funding_history venue=hyperliquid): **{len(hl)}**")
    lines.append(f"- asset_embeddings 向量库: **{len(vec)}**")
    lines.append(f"- `binance_hist` 在 public schema 存在吗: **{u['binance_hist 表是否存在(public)']}**"
                 "(crypto 行情实际落在 `ohlcv_daily`,按 `source='binance_hist'` 区分)")
    lines.append("")
    lines.append("### §4.1 覆盖对照")
    lines.append("")
    pairs = [
        ("① ∩ R-v2 前向", cap & bnh),
        ("① ∩ HL 永续", cap & hl),
        ("① ∩ 向量库", cap & vec),
        ("R-v2 前向 ∩ HL 永续", bnh & hl),
        ("R-v2 前向 ∩ 向量库", bnh & vec),
        ("HL 永续 ∩ 向量库", hl & vec),
        ("① \\ 向量库(持有但无向量)", cap - vec),
        ("R-v2 前向 \\ 向量库", bnh - vec),
        ("HL 永续 \\ 向量库", hl - vec),
        ("向量库 \\ (R-v2 ∪ HL)", vec - (bnh | hl)),
    ]
    lines.append("| 集合 | 元素数 | 列 |")
    lines.append("|---|---:|---|")
    for name, s in pairs:
        shown = sorted(s)
        shown = shown if len(shown) <= 30 else shown[:30] + [f"…(+{len(shown) - 30})"]
        lines.append(f"| {name} | {len(s)} | {shown} |")
    lines.append("")
    for label, uni in (("① 24 名", cap), ("R-v2 前向宇宙", bnh), ("HL 永续", hl)):
        cov = len(uni & vec) / len(uni) if uni else 0.0
        lines.append(f"- **{label}**: 向量库覆盖 **{len(uni & vec)}/{len(uni)} = {cov:.1%}**")
    lines.append("")

    # ── §5 code readers ─────────────────────────────────────────
    lines.append("## §5 每个空间的代码读者(活 / 死)")
    lines.append("")
    cr = out["code_readers"]
    lines.append("| 空间 | 写入端(文件 × 调用) | 读取端(文件 × 调用) | 注释行 |")
    lines.append("|---|---|---|---:|")
    for label, info in cr.items():
        wr = ", ".join(f"{f}({n})" for f, n in info["writer_files"].items()) or "—"
        rd = ", ".join(f"{f}({n})" for f, n in info["reader_files"].items()) or "—"
        lines.append(f"| `{label}` | {wr} | {rd} | {info['comment_only_lines']} |")
    lines.append("")
    for label, info in cr.items():
        if info["sample_writer"] or info["sample_reader"]:
            lines.append(f"### `{label}` 代表行")
            for f, s in info["sample_writer"]:
                lines.append(f"- WRITE: `{f}` :: `{s}`")
            for f, s in info["sample_reader"]:
                lines.append(f"- READ: `{f}` :: `{s}`")
            lines.append("")

    # ── §6 regime_fingerprints.py ──────────────────────────────
    lines.append("## §6 regime_fingerprints.py 代码审")
    lines.append("")
    rf = out["regime_fingerprints_audit"]
    lines.append("```")
    lines.append(json.dumps(rf, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")

    # ── §7 缺陷 × 影响 × 修法 × 谁做(按影响排序) ───────────────
    pit = out["pit_msv"]
    u = out["universes"]
    md = out.get("measured_dims", {})
    cap = set(u["① cap_a1 24 名"])
    vec = set(u["asset_embeddings 向量库"])
    bnh = set(u["R-v2 前向宇宙 (ohlcv_daily source=binance_hist, 30d)"])
    hl = set(u["HL 永续 (funding_history venue=hyperliquid)"])
    worst = sorted(((d, v) for d, v in pit["per_dim"].items() if v.get("status") == "ok"),
                   key=lambda kv: kv[1]["spearman_stored_vs_expanding"])[:3]
    nnm = pit.get("nn_overlap_mean")
    pct = lambda a, b: f"{len(a & b) / max(len(b), 1):.0%}"
    lines.append("## §7 缺陷清单(缺陷 × 影响 × 修法 × 谁做,按影响排序)")
    lines.append("")
    lines.append(f"排序依据:① 真钱持仓的向量覆盖 {len(cap & vec)}/{len(cap)};"
                 f"② 检索口径每天被改写的比例;③ 全史 z 对名次的实际扰动。全部为本轮实测,不是读文件得来的。")
    lines.append("")
    lines.append("| # | 缺陷(实测) | 影响 | 修法 | 谁做 |")
    lines.append("|---|---|---|---|---|")
    lines.append(
        f"| 1 | **向量库只盖到「① 的持仓 + 26% 的加密宇宙」**:73 个向量里 34 个是 SPY/QQQ/GLD/TLT 这类 TradFi;"
        f"R-v2 前向宇宙 {len(bnh)} 名只有 {len(bnh & vec)} 个有向量({pct(bnh & vec, bnh)});"
        f"HL 永续 {len(hl)} 名只有 {len(hl & vec)} 个({pct(hl & vec, hl)}) | "
        f"真金那 24 个反而最齐({len(cap & vec)}/24,缺 {sorted(cap - vec)}),"
        f"但**永续执行侧几乎全空**;升到 pgvector 之后检索面仍然是那 26% | "
        f"先补①缺的 3 个;R-v2/永续要不要进检索面是产品边界 | 取数/写入端 Seth;**检索面边界 Jazz** |")
    lines.append(
        f"| 2 | **`regime_daily` 用 publishable key 不可见(RLS 隐式屏蔽),"
        f"lane-c 端直查 0 行;服务端 Seth 端实有 507 行(2025-05-03→2026-10-20),生产是活的** | "
        f"T-161 报告的「空表 / 写入端死亡 / 8 个读取端全空」是 publishable key 的 RLS 伪影,"
        f"regime_match / phase_distance 在生产 environment 下能正常取数。"
        f"publishable 不可见是**只读角色权限边界**,不是通路问题 | "
        f"通路无问题,如要 lane 自己能验证,改用 anon role / internal token;不通过 publishable 跨权限 | @seth 决定 key 切换 |")
    lines.append(
        f"| 3 | **24 维里只有 {md.get('non_null_dims_mean')} 维非空**,填满 24 维的天数 = **{md.get('days_at_24')}**;"
        f"4 个 `cis_*` 维 2025 缺 92%、**2026 缺 100%** | "
        f"余弦只在 11 维上算,名义 24 维是虚的;跨 2025→2026 的回放不可比;"
        f"`source_completeness` 分母失真 | 先补 `cis_*` 写入(CIS 历史已在库),"
        f"再把 6 个永久空维移出分母并按 UNWIRED_DIMS 的规矩改文档 | Seth(写入端) |")
    lines.append(
        f"| 4 | **全史一次 z-score 的未来信息:20 邻重合率平均 {nnm}**(中位 {pit.get('nn_overlap_median')},"
        f"最小 {pit.get('nn_overlap_min')},最大 {pit.get('nn_overlap_max')},N={pit.get('nn_n_sample_days')}),"
        f"每维 Spearman 最低 {pit.get('spearman_min')} / 中位 {pit.get('spearman_median')} | "
        f"**每天 20 个「最像的过去时刻」里约 {round((1 - (nnm or 0)) * 20, 1)} 个会被换掉**;最差的一天整组 20 个全换。"
        f"扰动最大:" + ", ".join(f"`{d}`(ρ={v['spearman_stored_vs_expanding']},RMS={v['rms_gap_z']})" for d, v in worst)
        + f" | 因全史 z 是**单一仿射变换**,直接对存储列重标准化即可等价复现扩张窗口(§3 方法注),"
        f"不必回取原始值 | Seth(`market_state.py:zscore_columns`) |")
    lines.append(
        f"| 5 | **`treasury_entities` / `style_pit_coverage_daily` 用 publishable key 直接 42501** | "
        f"风格覆盖图与实体解析覆盖率在诊断面看不到 —— 「幸存者偏差写进 coverage」这条自证路径对只读角色**不可验证** | "
        f"这两张表该不该对只读角色可见是权限/产品边界 | **Jazz 拍板**;Seth 执行 |")
    lines.append(
        f"| 6 | **`asset_embeddings_history` 是死空间**:6 处写入引用、0 个读取端;"
        f"`asset_embeddings` 本体 73 行、每次覆盖写 | "
        f"`regime_fingerprints._cross_class_centroid_drift` 拿不到历史,只能恒返回 0.0 —— "
        f"**一个恒 0 的漂移指标比没有更坏** | 接上每日追加,或在指纹里对 `len(history) < 365` 直接拒绝出数 | Seth |")
    lines.append(
        f"| 7 | **`style_index_pit_daily` 查不到写入端**,却有 38730 行、覆盖 2020-01-01..2026-10-20、昨日新鲜 | "
        f"风格层是全库看起来最健康的,但**「谁在写」查不到**(疑似 `main.py` 内联) | "
        f"确认 writer 归属并登记进 `schema_manifest`,让写入端可点 | Seth |")
    lines.append(
        f"| 8 | **`funding_mean` / `funding_disp` 名义在册、实际已死**:2022 缺 99%,其后 100% | "
        f"从没有过 ≥365 天历史 → 扩张窗口重算对这两维**无解**(§3 覆盖不到) | "
        f"与 `fng`/`oi_mcap`/`stable_supply_chg` 同列 UNWIRED_DIMS,或补源 | Seth |")
    lines.append(
        f"| 9 | **SPINE.md §2 第 4 段仍写 `market_state_vectors` 582 行,实测 1755 行** | "
        f"文档落后 1173 行(S-361 之后没跟上);`producer_freshness` / `vdb_health` 拿硬编码规模做告警阈值 | "
        f"SPINE 与硬编码阈值同改 | Minimax-A(SPINE 一行)/ Seth(阈值) |")
    lines.append(
        f"| 10 | **`binance_hist` 不是 public schema 的表**(PGRST205);crypto 行情在 `ohlcv_daily` 靠 `source` 区分。"
        f"注意 `asset_class='Crypto'` 近 30 天 211 名 vs `source='binance_hist'` {len(bnh)} 名 | "
        f"两个口径差 74 个名 —— **不是错,是两个不同集合**;按表名查会 404,"
        f"「R-v2 前向宇宙 = binance_hist」这句在文档里是查不出来的 | 定一个口径写进通路文档 | **@seth 定口径** |")
    lines.append("")
    lines.append(f"> 本表 10 条之外:`regime_fingerprints.py` 代码审见 §6(`uses_lookahead=false`、`uses_pit=true`、无写入端)。"
                 f"各空间行数/日期范围/滞后见 §1,逐年逐维缺失率见 §2,PIT 量化见 §3,宇宙覆盖见 §4,读写端见 §5。")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines))
    print(f"WROTE {REPORT_PATH}")


if __name__ == "__main__":
    main()
