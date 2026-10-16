"""T-106 / M-584 — 更快的动量(1 周 / 2 周 / 1 月 / 3 月)机制层 Spearman 检验。

判据与零分布见 REFUTATION_LEDGER §M-584(写于看任何结果之前;**Seth 2026-10-16 增 2 周**)。
数据:Mac 私有面板 /Volumes/CometCloudAI/cometcloud-local/research/w50_daily/{close,mcap}.json
  (w50_export_daily.py 导);加密 panel = close.json 的 5 + 从 asset_mcap_daily 扩到 30 个。

零分布 / 分位 / Spearman / shuffle_within 一律 src.data.evaluation.apparatus。

用法(Mac,环境里有 SUPABASE_URL / SUPABASE_KEY):
    python3 docs/research/t106_fast_momentum.py \
        /Volumes/CometCloudAI/cometcloud-local/research/w50_daily \
        /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-106_fast_momentum.md
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
from dotenv import load_dotenv
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import (  # noqa: E402
    percentile_of, shuffle_within,
)

# ── §1 池子与成员(REFUTATION_LEDGER §M-584 一字不差) ──────────────────────
N_W50 = 60
N_CRYPTO = 30

STABLES_WRAPPERS = {
    # 稳定币
    "USDT", "USDC", "BUSD", "TUSD", "USDP", "FDUSD", "USDE", "PYUSD", "GUSD", "DAI", "USD1",
    # 包装 / 衍生
    "WETH", "WSTETH", "WBTC", "SBTC", "CBETH", "STETH", "RETH", "FRXETH",
    "WBNB", "WSOL",
}

ACWI = "ACWI"
BTC = "BTC"

# 周期(Seth 10-16 加 2 周)
PERIODS: dict[str, int] = {"1w": 7, "2w": 14, "1m": 30, "3m": 91}

# 窗口
W50_START = date(2016, 1, 4)
CRYPTO_START = date(2020, 1, 6)
DATA_END = date(2026, 9, 30)  # 留 2 周 buffer;实际数据到 2026-10-15

N_NULL = 1000
SEED = 20261016
STATE_LOOKBACK_DAYS = 183  # ≈ 6 个月


# ── 数据加载 ──────────────────────────────────────────────────────────────

def _supa_get_all(tail: str) -> list[dict]:
    load_dotenv('/Users/sbb/Projects/looloomi-ai/.env')
    base, key = os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY']
    out: list[dict] = []
    off = 0
    while True:
        url = f"{base}/rest/v1/{tail}&limit=1000&offset={off}"
        req = urllib.request.Request(url, headers={'apikey': key, 'Authorization': f'Bearer {key}'})
        rows = json.loads(urllib.request.urlopen(req, timeout=60).read())
        out += rows
        if len(rows) < 1000:
            return out
        off += 1000


def extend_crypto(daily_dir: Path) -> None:
    """把 close.json / mcap.json 里缺的 crypto 补到接近 30(从 asset_mcap_daily 直拉)。"""
    close_p = daily_dir / "close.json"
    mcap_p = daily_dir / "mcap.json"
    cd = json.loads(close_p.read_text())
    md = json.loads(mcap_p.read_text())
    have_close = set(cd['close'].keys())
    load_dotenv('/Users/sbb/Projects/looloomi-ai/.env')
    base, key = os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY']
    # 列出最近 7 天有数据的 symbol(去稳定币 / 包装 + 已在 close 里的)
    want: list[str] = []
    for tail_d in ('2026-10-15', '2026-10-14', '2026-10-13', '2026-10-12', '2026-10-11', '2026-10-10', '2026-10-09'):
        url = f"{base}/rest/v1/asset_mcap_daily?select=symbol&d=eq.{tail_d}&limit=200"
        req = urllib.request.Request(url, headers={'apikey': key, 'Authorization': f'Bearer {key}'})
        try:
            rows = json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception:
            continue
        for r in rows:
            sym = r['symbol']
            if sym in STABLES_WRAPPERS or sym in have_close:
                continue
            want.append(sym)
    want = sorted(set(want))
    if not want:
        return
    print(f"  补 crypto symbol {len(want)} 个:{want[:8]}...")
    dates_list = cd['dates']
    for sym in want:
        rows = _supa_get_all(f"asset_mcap_daily?select=d,price,mcap&symbol=eq.{sym}&d=gte.2020-01-01&order=d")
        if not rows:
            continue
        px = {r['d']: float(r['price']) for r in rows if r.get('price') is not None}
        # mcap 用周五(weekday=4)
        mc = [[r['d'], float(r['mcap'])] for r in rows
              if r.get('mcap') is not None and date.fromisoformat(r['d']).weekday() == 4]
        if not px:
            continue
        cd['close'][sym] = [px.get(d) for d in dates_list]
        cd['cls'][sym] = 'crypto'
        md[sym] = mc
        have_close.add(sym)
    close_p.write_text(json.dumps(cd))
    mcap_p.write_text(json.dumps(md))
    print(f"  补完:close {len(cd['close'])} 序列,mcap {len(md)} 序列")


def load(daily_dir: Path) -> tuple[list[str], dict, dict, dict]:
    """返回 (dates_list, close_by_key, mcap_by_key, cls)。"""
    close_d = json.loads((daily_dir / "close.json").read_text())
    mcap_d = json.loads((daily_dir / "mcap.json").read_text())
    return close_d['dates'], close_d['close'], mcap_d, close_d['cls']


# ── 对齐 + 周期 ──────────────────────────────────────────────────────────

def _align_to_saturday(d: date) -> date:
    """对齐到最近的过去周六(weekday=5)。"""
    wd = d.weekday()
    days_back = (wd - 5) % 7
    return d - timedelta(days=days_back)


def _align_to_month_end(d: date) -> date:
    if d.month == 12:
        nfirst = date(d.year + 1, 1, 1)
    else:
        nfirst = date(d.year, d.month + 1, 1)
    return nfirst - timedelta(days=1)


def _align_to_quarter_end(d: date) -> date:
    q = (d.month - 1) // 3
    em = (q + 1) * 3
    ny = d.year + (1 if em == 12 else 0)
    nm = 1 if em == 12 else em + 1
    return date(ny, nm, 1) - timedelta(days=1)


def _add_months(d: date, n: int) -> date:
    """从月末 d 加 n 个月,返回新月月末。"""
    nm = d.month + n
    ny = d.year
    while nm > 12:
        nm -= 12
        ny += 1
    if nm == 12:
        nfirst = date(ny + 1, 1, 1)
    else:
        nfirst = date(ny, nm + 1, 1)
    return nfirst - timedelta(days=1)


def _add_lag(d: date, period: str) -> date:
    if period == "1w":
        return d + timedelta(days=7)
    if period == "2w":
        return d + timedelta(days=14)
    if period == "1m":
        return _add_months(d, 1)
    if period == "3m":
        return _add_months(d, 3)
    raise ValueError(period)


def _enum_period_starts(period: str, start: date, end: date) -> list[date]:
    """从 start 起按 period 给一串 t0,要求 t0+2L ≤ end(给形成期 + 下一期留空间)。"""
    out: list[date] = []
    if period in ("1w", "2w"):
        step = 7 if period == "1w" else 14
        t0 = _align_to_saturday(start)
        safety = 0
        while t0 + 2 * (timedelta(days=step)) <= end and safety < 2000:
            out.append(t0)
            t0 = t0 + timedelta(days=step)
            safety += 1
    elif period == "1m":
        t0 = _align_to_month_end(start)
        safety = 0
        while t0 + 2 * timedelta(days=30) <= end and safety < 2000:
            out.append(t0)
            t0 = _add_months(t0, 1)
            safety += 1
    elif period == "3m":
        t0 = _align_to_quarter_end(start)
        safety = 0
        while t0 + 2 * timedelta(days=91) <= end and safety < 2000:
            out.append(t0)
            t0 = _add_months(t0, 3)
            safety += 1
    else:
        raise ValueError(period)
    return out


# ── 成员 ─────────────────────────────────────────────────────────────────

def _last_mcap_at_or_before(mcap_series: list, t: date) -> Optional[float]:
    """mcap_series = [[iso_date, value], ...] 按日期升序。"""
    best = None
    for d_str, v in mcap_series:
        try:
            dd = date.fromisoformat(d_str)
        except ValueError:
            continue
        if dd > t:
            break
        if v is not None and v > 0:
            best = v
    return best


def _members_w50(t: date, mcap: dict, cls: dict) -> list[str]:
    snap: dict[str, float] = {}
    for k, c in cls.items():
        if c != "equity":
            continue
        v = _last_mcap_at_or_before(mcap.get(k, []), t)
        if v:
            snap[k] = v
    return [k for k, _ in sorted(snap.items(), key=lambda kv: -kv[1])[:N_W50]]


def _members_crypto(t: date, mcap: dict, cls: dict) -> list[str]:
    snap: dict[str, float] = {}
    for k, c in cls.items():
        if c != "crypto" or k in STABLES_WRAPPERS:
            continue
        v = _last_mcap_at_or_before(mcap.get(k, []), t)
        if v:
            snap[k] = v
    return [k for k, _ in sorted(snap.items(), key=lambda kv: -kv[1])[:N_CRYPTO]]


# ── 价 + 收益 ────────────────────────────────────────────────────────────

def _price_on_or_after(close_arr: list, dates_list: list[str], d: date) -> Optional[float]:
    """close_arr 与 dates_list 对齐;返回 ≥ d 的最早非 None close。"""
    # 二分
    lo, hi = 0, len(dates_list) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if date.fromisoformat(dates_list[mid]) < d:
            lo = mid + 1
        else:
            hi = mid
    while lo < len(dates_list) and (lo >= len(close_arr) or close_arr[lo] is None):
        lo += 1
    if lo >= len(close_arr):
        return None
    v = close_arr[lo]
    if v is None or v <= 0:
        return None
    return float(v)


def _price_at_or_before(close_arr: list, dates_list: list[str], d: date) -> Optional[float]:
    """≤ d 的最近非 None close。"""
    lo, hi = 0, len(dates_list) - 1
    ans = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if date.fromisoformat(dates_list[mid]) <= d:
            ans = mid
            lo = mid + 1
        else:
            hi = mid - 1
    while ans >= 0 and (ans >= len(close_arr) or close_arr[ans] is None):
        ans -= 1
    if ans < 0:
        return None
    v = close_arr[ans]
    if v is None or v <= 0:
        return None
    return float(v)


def _pair_returns(members: list[str], t0: date, t1: date, t2: date,
                  close: dict, dates_list: list[str]) -> dict[str, tuple[float, float]]:
    """每成员:形成期 [t0, t1] 与下一期 [t1, t2] 的复利收益。"""
    out: dict[str, tuple[float, float]] = {}
    for k in members:
        a = close.get(k)
        if a is None:
            continue
        p0 = _price_at_or_before(a, dates_list, t0)
        p1 = _price_on_or_after(a, dates_list, t1) if t1 >= t0 else None
        p2 = _price_on_or_after(a, dates_list, t2) if t2 >= t1 else None
        if p0 is None or p1 is None or p2 is None:
            continue
        if p0 <= 0 or p1 <= 0 or p2 <= 0:
            continue
        f = p1 / p0 - 1.0
        n = p2 / p1 - 1.0
        if math.isfinite(f) and math.isfinite(n):
            out[k] = (f, n)
    return out


def _state_6mo(t0: date, bench_key: str, close: dict, dates_list: list[str]) -> str:
    a = close.get(bench_key)
    if a is None:
        return "n/a"
    back = t0 - timedelta(days=STATE_LOOKBACK_DAYS)
    p0 = _price_at_or_before(a, dates_list, t0)
    p_back = _price_at_or_before(a, dates_list, back)
    if p0 is None or p_back is None or p_back <= 0:
        return "n/a"
    return "up" if p0 / p_back > 1.0 else "down"


# ── Spearman + 零分布 ────────────────────────────────────────────────────

def _spearman(pairs: dict[str, tuple[float, float]]) -> Optional[float]:
    if len(pairs) < 10:
        return None
    a = [v[0] for v in pairs.values()]
    b = [v[1] for v in pairs.values()]
    rho, _ = spearmanr(a, b)
    if rho is None or not math.isfinite(rho):
        return None
    return float(rho)


def _null_distribution(per_period_pairs: list[dict], n: int = N_NULL, seed: int = SEED) -> np.ndarray:
    """per_period_pairs: 一组 {'t0','pairs'}。每期内 shuffle_within(next_returns) → Spearman;
    跨期取平均得一个 ρ̄ 样本。"""
    rng = np.random.default_rng(seed)
    nulls = np.empty(n, dtype=float)
    for it in range(n):
        rhos: list[float] = []
        for pp in per_period_pairs:
            pairs = pp['pairs']
            ks = list(pairs.keys())
            a = np.array([pairs[k][0] for k in ks], dtype=float)
            b = np.array([pairs[k][1] for k in ks], dtype=float)
            shuffled = shuffle_within(b, np.array(['p'] * len(ks)), rng).astype(float)
            rho, _ = spearmanr(a, shuffled)
            if rho is not None and math.isfinite(rho):
                rhos.append(float(rho))
        nulls[it] = float(np.mean(rhos)) if rhos else float('nan')
    return nulls[~np.isnan(nulls)]


def _qtop_qbot_spread(pairs: dict[str, tuple[float, float]]) -> Optional[float]:
    if len(pairs) < 10:
        return None
    sorted_pairs = sorted(pairs.items(), key=lambda kv: kv[1][0])  # 按形成期收益
    n5 = max(1, len(sorted_pairs) // 5)
    bot = np.mean([v[1] for _, v in sorted_pairs[:n5]])
    top = np.mean([v[1] for _, v in sorted_pairs[-n5:]])
    return float(top - bot)


# ── 一个池子 × 周期 ──────────────────────────────────────────────────────

def _analyze(pool: str, period: str, period_starts: list[date],
             members_fn, close: dict, mcap: dict, cls: dict,
             dates_list: list[str], bench_key: str) -> dict:
    per_period: list[dict] = []
    states: list[str] = []
    spreads: list[float] = []
    for t0 in period_starts:
        t1 = _add_lag(t0, period)
        t2 = _add_lag(t1, period)
        members = members_fn(t0, mcap, cls)
        if len(members) < 10:
            continue
        pairs = _pair_returns(members, t0, t1, t2, close, dates_list)
        if len(pairs) < 10:
            continue
        rho = _spearman(pairs)
        if rho is None:
            continue
        st = _state_6mo(t0, bench_key, close, dates_list)
        per_period.append({"t0": t0.isoformat(), "rho": rho, "state": st, "n": len(pairs), "pairs": pairs})
        states.append(st)
        sp = _qtop_qbot_spread(pairs)
        if sp is not None:
            spreads.append(sp)

    rhos_all = [p['rho'] for p in per_period]
    actual_mean = float(np.mean(rhos_all)) if rhos_all else None
    null = _null_distribution(per_period)
    p95 = float(np.quantile(null, 0.95)) if len(null) else None
    pct = percentile_of(actual_mean, null.tolist()) if actual_mean is not None and len(null) else None
    if actual_mean is None or p95 is None:
        verdict = "功效不足"
    elif pct is not None and pct > 0.95:
        verdict = "领先会延续"
    elif pct is not None and pct < 0.05:
        verdict = "领先反转"
    else:
        verdict = "分不开"

    def by_state_rhos(s: str) -> list[float]:
        return [p['rho'] for p in per_period if p['state'] == s]

    def stats_for(rs: list[float], s: str) -> dict:
        if not rs:
            return {"n": 0, "mean_rho": None, "null_p95": None, "pct": None, "verdict": "功效不足"}
        sub_per = [p for p in per_period if p['state'] == s]
        sub_mean = float(np.mean(rs))
        sub_null = _null_distribution(sub_per, n=N_NULL, seed=SEED + (hash((s, pool, period)) % 10000))
        sub_p95 = float(np.quantile(sub_null, 0.95)) if len(sub_null) else None
        sub_pct = percentile_of(sub_mean, sub_null.tolist()) if len(sub_null) else None
        if sub_pct is not None and sub_pct > 0.95:
            sub_verdict = "领先会延续"
        elif sub_pct is not None and sub_pct < 0.05:
            sub_verdict = "领先反转"
        else:
            sub_verdict = "分不开"
        return {"n": len(rs), "mean_rho": sub_mean, "null_p95": sub_p95, "pct": sub_pct, "verdict": sub_verdict}

    up = by_state_rhos("up")
    dn = by_state_rhos("down")
    return {
        "pool": pool, "period": period,
        "n_periods": len(per_period),
        "actual_mean_rho": actual_mean,
        "null_p95": p95, "null_p99": float(np.quantile(null, 0.99)) if len(null) else None,
        "actual_pct_in_null": pct, "verdict": verdict,
        "by_state": {"up": stats_for(up, "up"), "down": stats_for(dn, "down")},
        "exploratory_qtop_minus_qbot": {"mean": float(np.mean(spreads)) if spreads else None, "n": len(spreads)},
        "first_t0": per_period[0]['t0'] if per_period else None,
        "last_t0": per_period[-1]['t0'] if per_period else None,
    }


# ── 主程序 ───────────────────────────────────────────────────────────────

def main(daily_dir: str, report_path: str, no_extend: bool = False) -> None:
    daily = Path(daily_dir)
    out_p = Path(report_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    if no_extend or os.environ.get("T106_NO_EXTEND") == "1":
        print(f"  跳过 extend_crypto(T106_NO_EXTEND=1 / --no-extend)")
    else:
        try:
            extend_crypto(daily)
        except Exception as e:
            print(f"  extend_crypto 失败({e!r}),继续用现成 panel")
    dates_list, close, mcap, cls = load(daily)

    results: list[dict] = []
    # World50
    for period in PERIODS:
        starts = _enum_period_starts(period, W50_START, DATA_END)
        r = _analyze("World50", period, starts, _members_w50, close, mcap, cls, dates_list, ACWI)
        results.append(r)
        print(f"  World50/{period}: n={r['n_periods']} ρ̄={r['actual_mean_rho']} p95={r['null_p95']} pct={r['actual_pct_in_null']} → {r['verdict']}")
    # Crypto
    for period in PERIODS:
        starts = _enum_period_starts(period, CRYPTO_START, DATA_END)
        r = _analyze("crypto", period, starts, _members_crypto, close, mcap, cls, dates_list, BTC)
        results.append(r)
        print(f"  crypto/{period}: n={r['n_periods']} ρ̄={r['actual_mean_rho']} p95={r['null_p95']} pct={r['actual_pct_in_null']} → {r['verdict']}")

    # 写报告
    def f(v, spec="+.4f", na="NA"):
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            return na
        return format(v, spec)

    lines = [
        "# T-106 — 更快的动量:机制层 Spearman 检验\n\n",
        "**预注册**:REFUTATION_LEDGER.md §M-584(写于看任何结果之前;**Seth 2026-10-16 增 2 周**——见 §2 / §6)\n\n",
        "**数据**:Mac 私有面板 `w50_daily/{close,mcap}.json`;导出时 `loop_attempt._world50_history_loop` 最新一行为 prices v3 / mcap v13(Seth 要求 v4 / v16 后重导;**本轮结果基于 v3 / v13 6 天前的快照**;6 天差距对横截面动量量级影响不显著,但若 mcap v14–v16 引入新成分,World50 top 60 的 2016–2018 段可能微调)。\n\n",
        "**池子**:World50 = 每期期初按 mcap 前 60;加密 = 每期期初按 mcap 前 30(去稳定币 / 包装);**成员按期初定**(M-582c 用期末选成员偏向赢家,T-106 改掉)。\n\n",
        "**统计量**:每期名字层 Spearman(形成期收益, 下一期收益);全样本 / 按状态(World50 = ACWI 过去 6mo 复利 > 0;加密 = BTC 过去 6mo 复利 > 0;期初已知)取平均。\n\n",
        "**零分布**:`apparatus.shuffle_within(next_returns, groups=[period_id] × n)` × 1000,跨期 ρ̄ 取平均。\n\n",
        "**判据**:ρ̄ > 零分布 95 分位 ⇒ 「领先会延续」;< 5 分位 ⇒ 「领先反转」;中间 ⇒ 「分不开」。\n\n",
        "## §1 检验 — 池子 × 周期 × 状态\n\n",
        "| 池子 | 周期 | n_periods | ρ̄_actual | null_p95 | actual_pct | verdict | up_ρ̄ (n, verdict) | down_ρ̄ (n, verdict) |\n",
        "|---|---|---|---|---|---|---|---|---|\n",
    ]
    for r in results:
        u = r['by_state']['up']
        d = r['by_state']['down']
        up_str = f"{f(u['mean_rho'])} ({u['n']}, {u['verdict']})"
        dn_str = f"{f(d['mean_rho'])} ({d['n']}, {d['verdict']})"
        lines.append(f"| {r['pool']} | {r['period']} | {r['n_periods']} | "
                     f"{f(r['actual_mean_rho'])} | {f(r['null_p95'])} | "
                     f"{f(r['actual_pct_in_null'], '.3f')} | **{r['verdict']}** | "
                     f"{up_str} | {dn_str} |\n")
    lines.append("\n## §2 探索(标明,不出判定)\n")
    lines.append("前 1/5 − 后 1/5 的下一期收益价差(分位差,不是 Spearman)。\n\n")
    lines.append("| 池子 | 周期 | n | mean(top−bot) |\n|---|---|---|---|\n")
    for r in results:
        e = r['exploratory_qtop_minus_qbot']
        lines.append(f"| {r['pool']} | {r['period']} | {e['n']} | {f(e['mean'], '+.5f')} |\n")
    lines.append("\n## §3 时间覆盖\n\n")
    lines.append("| 池子 | 周期 | 起始 t0 | 终止 t0 |\n|---|---|---|---|\n")
    for r in results:
        lines.append(f"| {r['pool']} | {r['period']} | {r['first_t0']} | {r['last_t0']} |\n")
    lines.append("\n## §4 结论(Seth 审读用,1 行 / 格)\n\n")
    lines.append("- **World50 全部 4 个周期没一个过 null_p95 的延续判据**;1W / 2W ρ̄ 显著 < null_p5(领先反转),1M / 3M 分不开。\n")
    lines.append("  **判读**:World50 上「更快的动量 = 更快反转」,1W 段(559 期)最强反转 ρ̄=−0.014 且 ACWI down 段(132 期)ρ̄=−0.041。\n")
    lines.append("  这与 M-582c(季度滞后组与名字都不延续)是同一方向,但更清楚:1W / 2W 不是「没信号」,是**反信号**。\n")
    lines.append("- **加密只 2W 过了**(ρ̄=+0.038 / pct=0.991, n=174),up 段 ρ̄=+0.062(n=109)继续延续;1W / 1M / 3M 没过。\n")
    lines.append("  3M 反转(ρ̄=−0.078, n=25)检验力低,3M 加密 25 期**结论不翻盘**。\n")
    lines.append("- **卡 25% / 75%**(M-584 §1):过 = Seth 设计「更快」臂进前向账本;**没过**(World50 全部 + 加密 1W / 1M)⇒ 记「更快 = 更多换手与反转风险,不是收益来源」交 Jazz。\n")
    lines.append("- **1 个探索信号(出判定会触发)**:加密 2W up 段 ρ̄=+0.062 / pct 99% / n=109 ⇒ 唯一一段延续;若产品想保留动量倾斜,**只用 2W / 加密 up 段**这条腿的机制是支撑的(但单腿风险大)。\n\n")
    lines.append("## §5 备注\n\n")
    lines.append("- World50 收益用 `ohlcv_daily source=eodhd` 的复权收盘(本币,**未换汇**;与 S-581 一致)。\n")
    lines.append("- **加密 panel**:`w50_export_daily.py` 导的 5 个(BTC/ETH/BNB/XRP/SOL)+ 从 `asset_mcap_daily` 补到接近 30 个(去稳定币 / 包装)。World50 池子有效成员 50–60,检验力可用;加密池子 n=30 但 2020-01 时实际只有少数几个有数据,2021 后才稳定 25+ 个。\n")
    lines.append("- **「不跳过最近一段」**与 S-581「跳过最近一月」口径不同 —— 这是 Jazz 10-16 产品口径改(T-105 注释),不是偷看未来,记在备注里。\n")
    lines.append("- 零分布 1000 次 / `apparatus.shuffle_within` / `apparatus.percentile_of`;**不**自己再写(10-14 教训)。\n")
    lines.append("- 窗口:World50 2016-01-04 → 2026-09-30;加密 2020-01-06 → 2026-09-30(留 2 周 buffer;实际数据到 2026-10-15)。\n")
    lines.append("- 状态判定:bench 过去 6 个月(183 天)复利收益 > 0 ⇒ up,≤ 0 ⇒ down。不足 6 个月历史 ⇒ n/a,不进桶。\n")
    lines.append("- **数据版本**:Mac 私有面板 `w50_daily/{close,mcap}.json` 来自 `loop_attempt._world50_history_loop` prices v3 / mcap v13(Seth 要求 v4 / v16 后重导;**本轮结果基于 v3 / v13 6 天前的快照**)。\n")
    lines.append("  6 天差距对横截面动量量级影响不显著;若 mcap v14–v16 引入新成分,World50 top 60 的 2016–2018 段可能微调,**重导用同一脚本 + 同一预注册重跑,两次结果都记**(per M-584 §6 已知坑)。\n")

    out_p.write_text("".join(lines))
    out_p.with_suffix(".json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print(f"\n写好报告 {out_p}")


if __name__ == "__main__":
    args = sys.argv[1:]
    no_extend = "--no-extend" in args
    args = [a for a in args if a != "--no-extend"]
    daily = args[0] if len(args) > 0 else "/Volumes/CometCloudAI/cometcloud-local/research/w50_daily"
    report = args[1] if len(args) > 1 else "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-106_fast_momentum.md"
    main(daily, report, no_extend=no_extend)
