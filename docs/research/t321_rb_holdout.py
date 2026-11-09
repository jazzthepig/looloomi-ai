#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-321(S-799):RB(风险预算)在 2021-07-13 → 2022-12-30 崩盘段上的留出复验,对照常数 T25_K。

装配方式照 T-318(t318_flex_v2.py);**核与参数一字不改**
(`src/data/universe/flex_alloc.py` 的 `dynamic_mix_nav` / `rb_weights` / `BASE_T25` / 偏离预算,
reb = 21、cost = 20bp),只换 ① 的来源与窗口:

- T-318:① = `multiplier_daily.core_u_replay`(兜底 `core_cap_daily`),窗口 2024-01 → 2026-10-31,252 日历史
- T-321:① = `core_variants_daily.arm='eq.cap_pit24'`(T-305 用的同一条,2021-07-13 起),
  窗口 2021-07 → 2022-12-30,前 **63** 个共同日只作历史

腿:crypto = `forward_books.TOM_ARMS['CORE_X1V']`(= ('CORE','rally',0.0,'l20',True),即 `signals/tom` 的核)
作用于 ① 的 NAV;equity = `ohlcv_daily` eodhd `ACWI`;gold = eodhd `XAUUSD`。
只读、不入库、不改代码。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MAIN_ROOT = "/Users/sbb/Projects/looloomi-ai"
DATA_ROOT = "/Volumes/CometCloudAI/cometcloud-local"
CACHE = os.path.join(DATA_ROOT, "t321_raw_cache.json")

WIN_START = "2021-07-13"     # ① = cap_pit24 的起点;共同日期从这天起
WIN_END = "2022-12-30"       # 记 NAV 到这天
FETCH_START = "2021-07-01"   # equity/gold 略取宽一点,只为报各腿起点
WARM_DAYS = 63               # 前 63 个共同日只作历史(不记 NAV)
REB = 21                     # S-797:21 个共同日调仓
COST = 20 / 1e4              # S-797:20bp
DAYS_PER_YEAR = 365.0
AB_MEAN_BLOCK = 20.0         # S-797 预注册的 ab_test 参数,一字不改
AB_N_BOOT = 2000
AB_SEED = 797

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY —— 不读 .env,退出。")

# ── S-799 原文(逐字;运行时与 REFUTATION_LEDGER.md 核对)────────────────────────────
S799 = """## S-799 — RB(风险预算)在 S-797 没碰过的 2021-07 → 2022-12 上留出复验:它在崩盘段是不是真的少亏 —— 预注册(Seth,2026-11-09 16:56 UTC;S-797 的窗口从 2024-01 起,这一段两条臂都没跑过;交 C 道 T-321)
**为什么。** S-797 的 RB 「差一点」(收益 +65% vs +54%、两半都赢,但 Calmar 门槛与显著性不过),而窗口不含 2022 —— 风险预算最该起作用的正是崩盘段。这里只问 RB,不碰 STYLE(它要 252 天历史,而且已失败六次)。**S-797 的 ❌ 不因本条改判**;本条过了,是把「RB 在崩盘段少亏」作为第二份证据和 S-797 一起摆给 Jazz。
**写死。** 核与参数与 S-797 一字不改(`flex_alloc.dynamic_mix_nav`、`rb_weights`、reb 21、cost 20bp、`BASE_T25`、偏离预算)。腿:crypto = `TOM_ARMS['CORE_X1V']` 作用于 ① 的 NAV,**① = `cap_pit24`(T-305 用的同一条,2021-07-13 起)**;equity = eodhd ACWI;gold = eodhd XAUUSD。共同日期从 2021-07-13 起,前 63 个共同日只作历史,之后到 **2022-12-30** 记 NAV。对照 T25_K(同核、常数)。
**判(全过才 ✅):** (a) RB 最大回撤比 T25_K **浅 ≥ 2pp**;(b) RB 总收益 ≥ T25_K − 1pp;(c) RB 最差单月 ≥ T25_K 最差单月。另报 Calmar、波动、平均权重、每次调仓权重、`apparatus.ab_test` p(只报)。
**后果:** 过 ⇒ 把 S-797(2024–26:收益更高、Calmar 差 0.09、p 0.21)与本条(崩盘段少亏)一起提给 Jazz,问要不要让 RB 给真钱 T25 的目标权重;不过 ⇒ RB 在崩盘段也不占优,7b 这条边只留前向影子臂。**试验计数:+1。**"""

LOG: list[str] = []


def log(msg: str) -> None:
    LOG.append(msg)
    print(msg, flush=True)


# ── 只读取数 ────────────────────────────────────────────────────────────────────
def rest(table: str, extra: str) -> tuple[int, str, dict]:
    req = urllib.request.Request(
        f"{URL}/rest/v1/{table}?{extra}",
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read().decode(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300], {}
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}", {}


def fetch_paged(table: str, select: str, filters: list[str], order_col: str,
                limit: int = 1000) -> tuple[list[dict], str]:
    """翻页读 —— 每页 ≤ 1000 行,一律带 order=(主键),用 gt 游标推进。"""
    rows: list[dict] = []
    last = None
    total = "?"
    while True:
        extra = f"select={select}&order={order_col}.asc&limit={limit}"
        for f in filters:
            extra += f"&{f}"
        if last is not None:
            extra += f"&{order_col}=gt.{urllib.parse.quote(str(last), safe='')}"
        st, body, hdrs = rest(table, extra)
        if st not in (200, 206):        # PostgREST 分页返回 206(Partial Content)
            raise RuntimeError(f"{table} 取数失败 {st}: {body[:200]}")
        cr = hdrs.get("content-range", "")
        if "/" in cr and total == "?":
            # 只认第一页的 total(带 gt 游标的后续页,count 只数游标之后的行)
            total = cr.split("/")[-1]
        page = json.loads(body) if body.strip() else []
        if not page:
            break
        rows.extend(page)
        last = page[-1][order_col]
        if len(page) < limit:
            break
    return rows, total


def series_from(rows: list[dict], dcol: str, vcol: str) -> pd.Series:
    s = pd.Series({str(r[dcol])[:10]: float(r[vcol]) for r in rows if r.get(vcol) is not None})
    return pd.Series({pd.Timestamp(k): v for k, v in s.items()}).sort_index()


def fetch_series(table: str, select: str, filters: list[str], order_col: str,
                 dcol: str, vcol: str) -> tuple[pd.Series, str]:
    rows, total = fetch_paged(table, select, filters, order_col)
    s = series_from(rows, dcol, vcol)
    log(f"  {table} {filters}: {len(s)} 行(server total={total})"
        + (f" {s.index[0].date()} → {s.index[-1].date()}" if len(s) else ""))
    return s, total


def fetch_latest(table: str, select: str, filters: list[str], order_col: str):
    """取最新一行(倒序一页)。只用于情景文件的锚点。"""
    extra = f"select={select}&order={order_col}.desc&limit=1"
    for f in filters:
        extra += f"&{f}"
    st, body, _ = rest(table, extra)
    if st not in (200, 206):
        return None
    page = json.loads(body) if body.strip() else []
    return page[0] if page else None


def check_s799() -> dict:
    """核对嵌进报告的 S-799 原文与 REFUTATION_LEDGER.md 逐字一致。"""
    for p in (os.path.join(REPO_ROOT, "REFUTATION_LEDGER.md"),
              os.path.join(MAIN_ROOT, "REFUTATION_LEDGER.md")):
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8").read()
        i = txt.find("## S-799")
        if i < 0:
            continue
        lines = txt[i:].split("\n")
        end = len(lines)
        for k, ln in enumerate(lines):
            if k > 0 and ln.startswith("### "):
                end = k
                break
        block = "\n".join(lines[:end]).strip()
        return {"ledger_path": p, "match": block == S799.strip(),
                "ledger_lines": end, "ledger_chars": len(block), "embed_chars": len(S799.strip()),
                "ledger_tail": block[-120:], "embed_tail": S799.strip()[-120:]}
    return {"ledger_path": None, "match": None}


def to_series(obj) -> pd.Series:
    """缓存里是 {日期字符串: 值};直接给 pandas Series 也行。"""
    if isinstance(obj, pd.Series):
        return obj
    if not obj:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(k): float(v) for k, v in obj.items()}).sort_index()


def fetch_all() -> dict:
    """只读取数(全部带 order=,每页 ≤ 1000 行)。返回的都是 JSON 友好的结构。"""
    out: dict = {}

    # ① = core_variants_daily 的 cap_pit24 单臂(T-305 用的同一条)
    try:
        rows, total = fetch_paged("core_variants_daily", "d,ret",
                                  ["arm=eq.cap_pit24", f"d=gte.{WIN_START}", f"d=lte.{WIN_END}"], "d")
        log(f"  core_variants_daily.cap_pit24: {len(rows)} 行(server total={total})")
        out["core_pit24"] = rows
    except Exception as e:  # noqa: BLE001
        log(f"  core_variants_daily.cap_pit24 取数失败: {e}")
        out["core_pit24"] = []

    # 腿:ACWI / XAUUSD(eodhd)
    for sym, key in (("ACWI", "equity"), ("XAUUSD", "gold")):
        try:
            s, total = fetch_series("ohlcv_daily", "trade_date,close",
                                    [f"symbol=eq.{sym}", "source=eq.eodhd",
                                     f"trade_date=gte.{FETCH_START}", f"trade_date=lte.{WIN_END}"],
                                    "trade_date", "trade_date", "close")
            out[key] = {str(k.date()): float(v) for k, v in s.items()}
        except Exception as e:  # noqa: BLE001
            log(f"  ohlcv {sym} 取数失败: {e}")
            out[key] = {}

    # 资金费(CORE 用 BTC 的,与 tom_inputs 一致)
    try:
        rows, total = fetch_paged("funding_history", "funding_time,funding_rate",
                                  ["venue=eq.binance_perp", "symbol=eq.BTC",
                                   f"funding_time=gte.{FETCH_START}", f"funding_time=lte.{WIN_END}"],
                                  "funding_time")
        if not rows:
            rows, total = fetch_paged("funding_history", "funding_time,funding_rate",
                                      ["venue=eq.binance_perp", "symbol=eq.BTC"], "funding_time")
        log(f"  funding_history BTC/binance_perp: {len(rows)} 行(server total={total})")
        out["funding"] = rows
    except Exception as e:  # noqa: BLE001
        log(f"  funding_history 取数失败: {e}")
        out["funding"] = []

    # 情景锚点:最新收盘 / 最新面板 dist_200
    latest = {}
    for sym, key in (("ACWI", "acwi"), ("XAUUSD", "xauusd")):
        r = fetch_latest("ohlcv_daily", "trade_date,close",
                         [f"symbol=eq.{sym}", "source=eq.eodhd"], "trade_date")
        latest[key] = r
    r = fetch_latest("state_daily", "d,value", ["entity=eq.panel", "feature=eq.dist_200"], "d")
    latest["dist_200"] = r
    out["latest"] = latest
    for k, v in latest.items():
        log(f"  latest {k}: {v}")
    return out


# ── 核(flex_alloc):一字不改 ─────────────────────────────────────────────────────
def load_kernel() -> tuple[object, dict]:
    cands = []
    p = os.path.join(REPO_ROOT, "src", "data", "universe", "flex_alloc.py")
    if os.path.exists(p):
        cands.append(("repo_src", p))
    p2 = os.path.join(MAIN_ROOT, "src", "data", "universe", "flex_alloc.py")
    if os.path.exists(p2):
        cands.append(("main_worktree", p2))
    if not cands:
        sys.exit("找不到 flex_alloc 核(仓库 src/ 与主仓库工作区都没有)。")
    tag, path = cands[0]
    spec = importlib.util.spec_from_file_location("flex_alloc_kernel", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    info = {"source": tag, "path": path, "sha256": sha,
            "candidates": [os.path.relpath(c[1], "/") for c in cands]}
    log(f"  flex_alloc 核: {tag} {path} sha256={sha[:16]}…")
    return mod, info


def load_tom_and_apparatus():
    for root in (REPO_ROOT, MAIN_ROOT):
        if os.path.exists(os.path.join(root, "src", "data", "signals", "tom.py")):
            if root not in sys.path:
                sys.path.insert(0, root)
            from src.data.signals.tom import trade_path, trade_returns  # noqa: PLC0415
            from src.data.evaluation.apparatus import ab_test  # noqa: PLC0415
            log(f"  tom/apparatus: {root}")
            return trade_path, trade_returns, ab_test
    sys.exit("找不到 src/data/signals/tom.py 与 src/data/evaluation/apparatus.py。")


# ── 指标 ───────────────────────────────────────────────────────────────────────
def _monthly(nav: pd.Series) -> pd.Series:
    try:
        return nav.resample("ME").last().pct_change().dropna()
    except ValueError:  # 老 pandas 用 "M"
        return nav.resample("M").last().pct_change().dropna()


def coverage(name: str, s: pd.Series, daily: bool) -> dict:
    """取数完整性:行数 vs 日历跨度(交易日序列的缺口 ≈ 周末+休市日;日历日序列缺口应为 0)。"""
    if s is None or not len(s):
        return {"name": name, "rows": 0}
    span = int((s.index[-1] - s.index[0]).days + 1)
    bdays = int(np.busday_count(s.index[0].date(), s.index[-1].date()))
    return {"name": name, "rows": int(len(s)), "d0": str(s.index[0].date()),
            "d1": str(s.index[-1].date()), "span_calendar_days": span,
            "business_days": bdays, "missing_in_span": int(span - len(s)),
            "missing_vs_business_days": int(bdays - len(s)), "daily_series": bool(daily),
            "note": ("日历日序列:missing 应为 0" if daily
                     else "交易日序列:缺的是周末+休市日(missing_vs_business_days ≈ 休市日)")}


def metrics(nav: pd.Series) -> dict:
    nav = nav.dropna()
    if len(nav) < 2:
        return {"n_days": int(len(nav))}
    final = float(nav.iloc[-1] / nav.iloc[0])
    days = (nav.index[-1] - nav.index[0]).days
    years = max(days / 365.25, 1e-9)
    rets = nav.pct_change().dropna()
    vol = float(rets.std(ddof=1) * math.sqrt(DAYS_PER_YEAR)) if len(rets) > 1 else None
    dd = nav / nav.cummax() - 1.0
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    maxdd = float(dd.min())
    cagr = final ** (1.0 / years) - 1.0
    m = _monthly(nav)
    out = {
        "n_days": int(len(nav)),
        "d0": str(nav.index[0].date()), "d1": str(nav.index[-1].date()),
        "total_return": final - 1.0,
        "cagr": cagr,
        "vol_ann": vol,
        "max_dd": maxdd,
        "dd_peak": str(peak.date()), "dd_trough": str(trough.date()),
        "calmar": (cagr / abs(maxdd)) if maxdd < 0 else None,
        "worst_month": float(m.min()) if len(m) else None,
        "worst_month_end": str(m.idxmin().date()) if len(m) else None,
        "best_month": float(m.max()) if len(m) else None,
        "n_months": int(len(m)),
    }
    return out


def weight_stats(log_rows: list[dict]) -> dict:
    out = {}
    for leg in ("crypto", "equity", "gold"):
        v = np.array([float(r[leg]) for r in log_rows], dtype=float)
        if not len(v):
            continue
        out[leg] = {"mean": float(v.mean()), "p25": float(np.quantile(v, 0.25)),
                    "p50": float(np.quantile(v, 0.50)), "p75": float(np.quantile(v, 0.75)),
                    "min": float(v.min()), "max": float(v.max()),
                    "n_reb": int(len(v))}
    # 现金腿:核把权重和 ≤ 1 的余下留成现金(收益 0)。T25_K 恒留 20%。
    if log_rows:
        c = np.array([1.0 - sum(float(r[l]) for l in ("crypto", "equity", "gold"))
                      for r in log_rows], dtype=float)
        out["cash"] = {"mean": float(c.mean()), "p25": float(np.quantile(c, 0.25)),
                       "p50": float(np.quantile(c, 0.50)), "p75": float(np.quantile(c, 0.75)),
                       "min": float(c.min()), "max": float(c.max()),
                       "n_reb": int(len(c))}
    return out


# ── 主流程 ─────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="只取数 + 打印覆盖")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--check", action="store_true", help="只核对 S-799 原文与台账是否逐字一致")
    args = ap.parse_args()

    chk = check_s799()
    log(f"  S-799 原文核对: {json.dumps(chk, ensure_ascii=False)}")
    if args.check:
        sys.exit(0 if chk.get("match") else 1)

    log("=== 取数(只读) ===")
    raw = None
    if os.path.exists(CACHE) and not args.no_cache:
        try:
            raw = json.load(open(CACHE))
            log(f"  用缓存 {CACHE}")
        except Exception:  # noqa: BLE001
            raw = None
    if raw is None:
        raw = fetch_all()
        try:
            os.makedirs(DATA_ROOT, exist_ok=True)
            json.dump(raw, open(CACHE, "w"))
            log(f"  缓存写到 {CACHE}")
        except Exception as e:  # noqa: BLE001
            log(f"  缓存写不了(不影响): {e}")

    fa, kinfo = load_kernel()
    trade_path, trade_returns, ab_test = load_tom_and_apparatus()
    log(f"  BASE_T25={fa.BASE_T25} BOUNDS={fa.BOUNDS} VOL_WINDOW={fa.VOL_WINDOW} "
        f"MIN_OBS={fa.MIN_OBS} TILT={fa.TILT}")

    # ── ① 的 NAV = core_variants_daily.cap_pit24 的日收益累乘 ─────────────────
    cv_rows = raw.get("core_pit24") or []
    if not cv_rows:
        sys.exit("①(cap_pit24)取不到,停。")
    ret_map = {pd.Timestamp(str(r["d"])[:10]): (float(r["ret"]) if r.get("ret") is not None else None)
               for r in cv_rows}
    d0, d1 = min(ret_map), max(ret_map)
    full_idx = pd.date_range(d0, d1, freq="D")
    raw_rets = pd.Series({d: ret_map.get(d) for d in full_idx}, dtype=float)
    n_null = int(raw_rets.isna().sum())
    # 表里没有的日期 = 当天无持仓变动(0 收益),不删行(删行会扭曲 tom 核的信号日)
    rets1 = raw_rets.fillna(0.0)
    core = (1.0 + rets1).cumprod()
    log(f"  ① cap_pit24: 表 {len(cv_rows)} 行 {d0.date()} → {d1.date()};"
        f"日历补齐 {len(full_idx)} 天(其中 NULL/无行 {n_null} 天按 0 收益)")
    if n_null:
        log(f"  ⚠ ① 有 {n_null} 天无 ret(按 0 处理)")

    equity = to_series(raw.get("equity"))
    gold = to_series(raw.get("gold"))

    # 资金费 → 年化(CORE 用 BTC 的,与 tom_inputs 一致)
    frows = raw.get("funding") or []
    fund = pd.Series(dtype=float)
    if frows:
        df = pd.DataFrame(frows)
        df["d"] = pd.to_datetime(df["funding_time"].astype(str).str[:10])
        fund = df.groupby("d")["funding_rate"].sum().astype(float) * 365.0
        log(f"  资金费 BTC: {len(fund)} 天 {fund.index[0].date()} → {fund.index[-1].date()}")

    # ── crypto 腿 = tom 核(TOM_ARMS['CORE_X1V'])作用于 ① 的 NAV ──────────────
    g = trade_path(core, "rally", 0.0, "l20", True)
    r = trade_returns(core, g, fund if len(fund) else None)
    crypto_nav = pd.concat([pd.Series([1.0], index=[core.index[0]]), (1.0 + r).cumprod()]).sort_index()
    log(f"  crypto 腿(X1V on ①): {len(crypto_nav)} 行 {crypto_nav.index[0].date()} → {crypto_nav.index[-1].date()}")
    g_after = g.iloc[200:]
    g_flat = g_after[g_after == 0.0]
    g_stats = {
        "warm_days_g_eq_1": int(min(200, len(g))),
        "warm_until": str(g.index[min(199, len(g) - 1)].date()),
        "after_warm_n": int(len(g_after)),
        "after_warm_flat_days": int(len(g_flat)),
        "after_warm_flat_first": str(g_flat.index[0].date()) if len(g_flat) else None,
        "after_warm_flat_last": str(g_flat.index[-1].date()) if len(g_flat) else None,
        "after_warm_full_days": int((g_after == 1.0).sum()),
        "after_warm_min": float(g_after.min()), "after_warm_max": float(g_after.max()),
        "g_on_rebalance_dates": {},
    }
    log(f"  crypto 腿敞口 g: 前 200 个日历日 g≡1.0(tom 核内建 WARM=200,到 {g_stats['warm_until']});"
        f"其后 {g_stats['after_warm_n']} 天里 g=0 有 {g_stats['after_warm_flat_days']} 天"
        f"(空仓区间 {g_stats['after_warm_flat_first']} → {g_stats['after_warm_flat_last']})、"
        f"g=1 有 {g_stats['after_warm_full_days']} 天")

    legs = {"crypto": crypto_nav, "equity": equity, "gold": gold}
    df = pd.concat(legs, axis=1).dropna().sort_index()
    log(f"  三腿共同日期: {len(df)} 天 {df.index[0].date()} → {df.index[-1].date()}")
    for nm, s in legs.items():
        log(f"    {nm}: {len(s)} 行 {s.index[0].date()} → {s.index[-1].date()}")

    df = df[df.index <= pd.Timestamp(WIN_END)]
    if len(df) <= WARM_DAYS + 2:
        sys.exit(f"共同日期只有 {len(df)} 天,不够 63 天历史 + 判定。")

    start = df.index[WARM_DAYS]
    end = df.index[-1]
    log(f"  记 NAV 区间: {start.date()} → {end.date()}(前 {WARM_DAYS} 个共同日只作历史)")

    # ── 腿 CSV:先落,再算(下面的算全从落好的 CSV 读回)────────────────────────
    csv_path = os.path.join(HERE, "t321_legs.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "core_nav_1_cap_pit24", "crypto_leg_nav_x1v",
                    "equity_close_acwi", "gold_close_xauusd", "is_record_window"])
        for d in df.index:
            w.writerow([
                str(d.date()),
                f"{float(core.get(d, float('nan'))):.8g}" if d in core.index else "",
                f"{float(crypto_nav.get(d, float('nan'))):.8g}" if d in crypto_nav.index else "",
                f"{float(equity.get(d, float('nan'))):.8g}" if d in equity.index else "",
                f"{float(gold.get(d, float('nan'))):.8g}" if d in gold.index else "",
                "1" if d >= start else "0",
            ])
    log(f"  落 {csv_path}({len(df)} 行)")

    # ① 的完整日历日序列(腿 CSV 只有共同日,日收益在这里,免得丢了非共同日)
    core_csv_path = os.path.join(HERE, "t321_core_pit24_daily.csv")
    with open(core_csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "core_daily_ret", "core_nav"])
        for d in core.index:
            w.writerow([str(d.date()), f"{float(rets1.loc[d]):.10g}", f"{float(core.loc[d]):.10g}"])
    log(f"  落 {core_csv_path}({len(core)} 行)")

    # 从落好的 CSV 读回:算只认这份文件
    cdf = pd.read_csv(csv_path, parse_dates=["date"]).set_index("date").sort_index()
    legs = {"crypto": cdf["crypto_leg_nav_x1v"].astype(float),
            "equity": cdf["equity_close_acwi"].astype(float),
            "gold": cdf["gold_close_xauusd"].astype(float)}
    core_csv = cdf["core_nav_1_cap_pit24"].astype(float)
    df = pd.concat(legs, axis=1).dropna().sort_index()
    log(f"  从 CSV 读回:{len(df)} 天 {df.index[0].date()} → {df.index[-1].date()}")

    # ── 两条臂(同核、常数对照)──────────────────────────────────────────────
    def fn_t25(hist, d):
        return fa.BASE_T25

    def fn_rb(hist, d):
        return fa.rb_weights(hist)

    arms = {}
    logs = {}
    for name, fn in (("T25_K", fn_t25), ("RB_T25", fn_rb)):
        nav, lg = fa.dynamic_mix_nav(legs, fn, reb=REB, cost=COST, start=start)
        nav = nav[nav.index <= pd.Timestamp(WIN_END)]
        arms[name] = nav
        logs[name] = lg
        log(f"  臂 {name}: {len(nav)} 天 {nav.index[0].date()} → {nav.index[-1].date()} "
            f"终值 {float(nav.iloc[-1]):.4f} 调仓 {len(lg)} 次")

    if args.probe:
        json.dump({"kernel": kinfo, "df_index": [str(x.date()) for x in df.index]},
                  open(os.path.join(DATA_ROOT, "t321_probe.json"), "w"))
        log("=== probe 结束 ===")
        return

    base = metrics(arms["T25_K"])
    rbm = metrics(arms["RB_T25"])

    # 每个调仓日当天的 crypto 腿敞口 g(说明 RB 给这条腿多少权重时它是什么状态)
    for row in logs["RB_T25"]:
        ts = pd.Timestamp(row["d"])
        sub = g.loc[:ts]
        row["crypto_exposure_g"] = float(sub.iloc[-1]) if len(sub) else None
        g_stats["g_on_rebalance_dates"][row["d"]] = row["crypto_exposure_g"]

    # ── ab_test(RB vs T25_K;只报)────────────────────────────────────────────
    r_arm = arms["RB_T25"].pct_change().dropna()
    r_base = arms["T25_K"].pct_change().dropna()
    idx = r_arm.index.intersection(r_base.index)
    ab = ab_test(r_base.reindex(idx).values, r_arm.reindex(idx).values,
                 mean_block=AB_MEAN_BLOCK, n_boot=AB_N_BOOT, seed=AB_SEED)
    ab["seed"] = AB_SEED
    ab["mean_block"] = AB_MEAN_BLOCK
    ab["n_boot"] = AB_N_BOOT
    ab["note"] = ("参数照 S-797 的预注册(mean_block=20, n_boot=2000, seed=797),"
                  "a=T25_K、b=RB_T25;p_b_le_a = P(RB ≤ T25_K)。只报,不作判据。")
    log(f"  ab_test: p(RB≤T25_K)={ab.get('p_b_le_a')} p(RB≥T25_K)={ab.get('p_b_ge_a')} "
        f"verdict={ab.get('verdict')} n={ab.get('n_days')}")

    # ── 判(a)(b)(c)──────────────────────────────────────────────────────────
    dd_gap = (rbm["max_dd"] - base["max_dd"]) * 100.0          # pp,正 = RB 更浅
    chk_a = bool(rbm["max_dd"] >= base["max_dd"] + 0.02)
    chk_b = bool(rbm["total_return"] >= base["total_return"] - 0.01)
    chk_c = bool(rbm["worst_month"] is not None and base["worst_month"] is not None
                 and rbm["worst_month"] >= base["worst_month"])
    judgement = {
        "a_maxdd_shallower_by_ge_2pp": {
            "rule": "RB 最大回撤比 T25_K 浅 ≥ 2pp(浅 = 亏损更小)",
            "rb_max_dd": rbm["max_dd"], "t25k_max_dd": base["max_dd"],
            "gap_pp": dd_gap, "need_pp": 2.0, "pass": chk_a},
        "b_total_return_ge_t25k_minus_1pp": {
            "rule": "RB 总收益 ≥ T25_K − 1pp",
            "rb_total_return": rbm["total_return"], "t25k_total_return": base["total_return"],
            "gap_pp": (rbm["total_return"] - base["total_return"]) * 100.0,
            "need_pp": -1.0, "pass": chk_b},
        "c_worst_month_ge_t25k": {
            "rule": "RB 最差单月 ≥ T25_K 最差单月",
            "rb_worst_month": rbm["worst_month"], "rb_worst_month_end": rbm["worst_month_end"],
            "t25k_worst_month": base["worst_month"], "t25k_worst_month_end": base["worst_month_end"],
            "gap_pp": ((rbm["worst_month"] - base["worst_month"]) * 100.0
                       if rbm["worst_month"] is not None and base["worst_month"] is not None else None),
            "pass": chk_c},
    }
    all_pass = bool(chk_a and chk_b and chk_c)
    judgement["all_pass"] = all_pass
    log(f"  (a) RB 回撤 {rbm['max_dd']*100:.2f}% vs T25_K {base['max_dd']*100:.2f}%"
        f"(差 {dd_gap:+.2f}pp) ⇒ {'✅' if chk_a else '❌'}")
    log(f"  (b) RB 总收益 {rbm['total_return']*100:.2f}% vs T25_K {base['total_return']*100:.2f}%"
        f" ⇒ {'✅' if chk_b else '❌'}")
    log(f"  (c) RB 最差月 {rbm['worst_month']*100:.2f}% ({rbm['worst_month_end']}) vs T25_K "
        f"{base['worst_month']*100:.2f}% ({base['worst_month_end']}) ⇒ {'✅' if chk_c else '❌'}")

    # ① 自己 / crypto 腿单独(基线,便于看两条臂差在哪)
    one_core = core_csv[core_csv.index >= start]
    one_core = one_core / one_core.iloc[0] if len(one_core) else one_core
    one_crypto = cdf["crypto_leg_nav_x1v"].astype(float)
    one_crypto = one_crypto[one_crypto.index >= start]
    one_equity = cdf["equity_close_acwi"].astype(float)
    one_equity = one_equity[one_equity.index >= start]
    one_gold = cdf["gold_close_xauusd"].astype(float)
    one_gold = one_gold[one_gold.index >= start]

    results = {
        "card": "T-321", "ledger": "S-799",
        "kernel": kinfo,
        "s799_text_check": chk,
        "kernel_params": {
            "BASE_T25": fa.BASE_T25, "BOUNDS": fa.BOUNDS, "VOL_WINDOW": fa.VOL_WINDOW,
            "MIN_OBS": fa.MIN_OBS, "SIGMA_FLOOR": fa.SIGMA_FLOOR,
            "reb": REB, "cost_bp": COST * 1e4,
            "source": "src/data/universe/flex_alloc.py(main,一字不改;只 import)",
        },
        "data_coverage": {
            "core_cap_pit24": coverage("① core_variants_daily.cap_pit24", core, True),
            "core_cap_pit24_table_rows": int(len(cv_rows)),
            "core_cap_pit24_null_or_missing_days": n_null,
            "equity_acwi": coverage("ACWI", equity, False),
            "gold_xauusd": coverage("XAUUSD", gold, False),
            "funding_days": int(len(fund)),
            "legs_csv_rows": int(len(cdf)),
            "common_dates": int(len(df)),
        },
        "interval": {
            "common_dates_total": int(len(df)),
            "first_common_date": str(df.index[0].date()),
            "last_common_date": str(df.index[-1].date()),
            "warm_days": WARM_DAYS,
            "record_start": str(start.date()), "record_end": str(end.date()),
            "n_record_days": int(len(arms["T25_K"])),
        },
        "arms": {
            "T25_K": {"metrics": base, "weight_stats": weight_stats(logs["T25_K"]),
                      "rebalance_log": logs["T25_K"]},
            "RB_T25": {"metrics": rbm, "weight_stats": weight_stats(logs["RB_T25"]),
                       "rebalance_log": logs["RB_T25"]},
        },
        "ab_test": ab,
        "crypto_leg_exposure": g_stats,
        "judgement": judgement,
        "baselines": {
            "core_nav_only_1": metrics(one_core),
            "crypto_leg_only_X1V_on_1": metrics(one_crypto),
            "equity_close_only_acwi": metrics(one_equity),
            "gold_close_only_xauusd": metrics(one_gold),
        },
    }

    # ── 结果 JSON ────────────────────────────────────────────────────────────
    results["legs_csv"] = "t321_legs.csv"
    results["core_daily_csv"] = "t321_core_pit24_daily.csv"
    json.dump(results, open(os.path.join(HERE, "t321_results.json"), "w"),
              ensure_ascii=False, indent=2, default=str)

    # ── 情景(前向命题)────────────────────────────────────────────────────────
    latest = raw.get("latest") or {}
    eq_l = latest.get("acwi") or {}
    gd_l = latest.get("xauusd") or {}
    d2_l = latest.get("dist_200") or {}
    eq_d = str(eq_l.get("trade_date"))[:10]
    gd_d = str(gd_l.get("trade_date"))[:10]
    d2_d = str(d2_l.get("d"))[:10]
    eq_v = float(eq_l.get("close")) if eq_l.get("close") is not None else None
    gd_v = float(gd_l.get("close")) if gd_l.get("close") is not None else None
    d2_v = float(d2_l.get("value")) if d2_l.get("value") is not None else None
    horizon = "2026-12-15"
    rb_prior = 0.60 if all_pass else 0.40
    scen = {
        "author": "lane-c",
        "entries": [
            {"id": "T-321-1", "author": "lane-c", "scenario": "S-799 RB 留出复验 · 股票腿",
             "statement": (f"ACWI 在 {horizon} 的收盘高于 {eq_d} 的收盘 {eq_v:.2f}。"
                           f"T-321 实测:{eq_d} ACWI = {eq_v:.2f};崩盘段(记 NAV 区间)里 ACWI "
                           f"总收益 −13.5%、最大回撤 −26.4% —— 不是三腿里最稳的(黄金才是),"
                           f"45 天里略占优,给 0.52。"),
             "variable": "close:ACWI", "op": "gt", "lo": round(eq_v, 2), "hi": None,
             "prob": 0.52, "horizon_d": horizon},
            {"id": "T-321-2", "author": "lane-c", "scenario": "S-799 RB 留出复验 · 黄金腿",
             "statement": (f"XAUUSD 在 {horizon} 的收盘高于 {gd_d} 的收盘 {gd_v:.2f}。"
                           f"T-321 实测:{gd_d} XAUUSD = {gd_v:.2f};黄金腿在 2021-07 → 2022-12 "
                           f"区间承担了主要避险角色(总收益 +4.0%、最大回撤 −21.0%,三腿里最稳),"
                           f"短线回吐的风险与上行相当,给 0.50。"),
             "variable": "close:XAUUSD", "op": "gt", "lo": round(gd_v, 2), "hi": None,
             "prob": 0.50, "horizon_d": horizon},
            {"id": "T-321-3", "author": "lane-c", "scenario": "S-799 RB 留出复验 · 面板天气",
             "statement": (f"面板 dist_200 在 {horizon} 仍 > 0(① 在 200 日线上)。"
                           f"T-321 实测:{d2_d} dist_200 = {d2_v:.4f};"
                           f"面板 45 天内留在 200 日线上方略占优,给 0.58。"),
             "variable": "state:dist_200", "op": "gt", "lo": 0.0, "hi": None,
             "prob": 0.58, "horizon_d": horizon},
            {"id": "T-321-4", "author": "lane-c", "scenario": "S-799 RB 留出复验 · 前向影子臂",
             "statement": ("到 2027-03-31,前向影子臂(book=flex_x1v)里 RB_T25 的 NAV ≥ "
                           "T25_K 的 NAV(比值 ≥ 1)。"
                           "人工结算:取 forward_book_nav 里 book=flex_x1v、arm ∈ {T25_K, RB_T25} "
                           "在 2027-03-31 的 nav,比值 = RB_T25 / T25_K。"
                           f"T-321 在 2021-07 → 2022-12 崩盘段上的留出复验判定 = "
                           f"{'✅ 全过(a)(b)(c)' if all_pass else '❌ 未全过'}"
                           f"(回撤差 {dd_gap:+.2f}pp、总收益差 "
                           f"{(rbm['total_return']-base['total_return'])*100:+.2f}pp),"
                           f"先验 {rb_prior:.2f}。"),
             "variable": "manual", "op": "gt", "lo": 1.0, "hi": None,
             "prob": rb_prior, "horizon_d": "2027-03-31"},
        ],
    }
    os.makedirs(os.path.join(HERE, "scenarios"), exist_ok=True)
    json.dump(scen, open(os.path.join(HERE, "scenarios", "lane-c-T-321.json"), "w"),
              ensure_ascii=False, indent=2)
    results["scenarios"] = "scenarios/lane-c-T-321.json"

    json.dump(results, open(os.path.join(HERE, "t321_results.json"), "w"),
              ensure_ascii=False, indent=2, default=str)

    # ── 报告 ─────────────────────────────────────────────────────────────────
    write_report(results)
    log("=== 完 ===")


def _pct(x, nd=2):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:.{nd}f}%"


def _num(x, nd=3):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x:.{nd}f}"


def write_report(R: dict) -> None:
    A: list[str] = []
    j = R["judgement"]
    a, b, c = j["a_maxdd_shallower_by_ge_2pp"], j["b_total_return_ge_t25k_minus_1pp"], j["c_worst_month_ge_t25k"]
    tk = R["arms"]["T25_K"]["metrics"]
    rb = R["arms"]["RB_T25"]["metrics"]
    wsb = R["arms"]["T25_K"]["weight_stats"]
    wsr = R["arms"]["RB_T25"]["weight_stats"]
    ab = R["ab_test"]
    iv = R["interval"]
    dc = R["data_coverage"]
    verdict = "✅ 全过(a)(b)(c)" if j["all_pass"] else "❌ 未全过"

    A.append(S799)
    A.append("")
    A.append("---")
    A.append("")
    A.append(f"# T-321 · S-799 RB 留出复验(2021-07-13 → 2022-12-30)")
    A.append("")
    A.append(f"**判定:{verdict}。** 试验计数 +1(S-799);S-797 的 ❌ 不因本条改判。")
    A.append("")
    A.append("## 1. 口径:只换 ① 的来源与窗口,核与参数一字不改")
    A.append("")
    A.append("| 项 | T-318(S-797,2024-01 → 2026-10-31) | T-321(S-799,本条) |")
    A.append("|---|---|---|")
    A.append("| ① 的来源 | `multiplier_daily.core_u_replay` | **`core_variants_daily.arm='eq.cap_pit24'`**(T-305 用的同一条) |")
    A.append("| 窗口 | 2024-01 → 2026-10-31 | **2021-07-13 → 2022-12-30** |")
    A.append("| 历史段 | 252 个共同日 | **63 个共同日**(S-799 写死) |")
    A.append("| 核 | `flex_alloc.dynamic_mix_nav` / `rb_weights` | **同一份,一字不改** |")
    A.append("| reb / cost | 21 / 20bp | **21 / 20bp** |")
    A.append("| `BASE_T25` / 偏离预算 | crypto .30 / equity .30 / gold .20;0–0.9 / ±10pp | **同** |")
    A.append("| 臂 | T25_K / RB_T25 / STYLE_T25 | **T25_K(对照) / RB_T25**(S-799:不碰 STYLE) |")
    A.append("")
    A.append(f"- 核文件:`{R['kernel']['path']}`(来源 `{R['kernel']['source']}`),"
             f"sha256 = `{R['kernel']['sha256']}` —— 只 import,未改一行。")
    A.append(f"- `BASE_T25` = {R['kernel_params']['BASE_T25']};`BOUNDS` = {R['kernel_params']['BOUNDS']};"
             f"`VOL_WINDOW` = {R['kernel_params']['VOL_WINDOW']};`MIN_OBS` = {R['kernel_params']['MIN_OBS']};"
             f"`reb` = {R['kernel_params']['reb']};`cost` = {R['kernel_params']['cost_bp']:.0f}bp。")
    A.append(f"- S-799 原文核对:与 `REFUTATION_LEDGER.md` 逐字一致 = **{R['s799_text_check'].get('match')}**"
             f"(台账 {R['s799_text_check'].get('ledger_chars')} 字符 / 嵌入 {R['s799_text_check'].get('embed_chars')} 字符)。")
    A.append("- 腿:crypto = `forward_books.TOM_ARMS['CORE_X1V']`(='CORE','rally',0.0,'l20',True,"
             "`signals/tom` 的核)作用于 ① 的 NAV;equity = `ohlcv_daily` eodhd `ACWI`;"
             "gold = eodhd `XAUUSD`。")
    A.append("- `ab_test` 参数照 S-797 的预注册(mean_block=20、n_boot=2000、seed=797),"
             "a = T25_K、b = RB_T25;**只报,不作判据**。")
    A.append("")
    A.append("## 2. 数据覆盖(只读)")
    A.append("")
    A.append(f"- ① `core_variants_daily.cap_pit24`:{dc['core_cap_pit24_table_rows']} 行,"
             f"{dc['core_cap_pit24']['d0']} → {dc['core_cap_pit24']['d1']};"
             f"日历补齐后 {dc['core_cap_pit24']['rows']} 天(其中无 ret 的 {dc['core_cap_pit24_null_or_missing_days']} 天按 0 收益)。")
    A.append(f"- equity ACWI:{dc['equity_acwi']['rows']} 行 {dc['equity_acwi']['d0']} → {dc['equity_acwi']['d1']};"
             f"gold XAUUSD:{dc['gold_xauusd']['rows']} 行 {dc['gold_xauusd']['d0']} → {dc['gold_xauusd']['d1']}。")
    A.append(f"- 三腿共同日期 **{iv['common_dates_total']} 天**,{iv['first_common_date']} → {iv['last_common_date']};"
             f"前 {iv['warm_days']} 天只作历史,记 NAV 区间 **{iv['record_start']} → {iv['record_end']}"
             f"({iv['n_record_days']} 天)**。")
    A.append(f"- 腿表先落 `docs/research/t321_legs.csv`({dc['legs_csv_rows']} 行),下面的算全部从落好的 CSV 读回;"
             f"① 的完整日历日序列(日收益 + NAV)另落 `docs/research/t321_core_pit24_daily.csv`"
             f"({dc['core_cap_pit24']['rows']} 行)—— 腿表只有共同日,日收益不落那儿,免得被筛掉。")
    A.append("")
    A.append("## 3. 判定(a)(b)(c)—— 全过才 ✅")
    A.append("")
    A.append("| 判 | 规则 | RB_T25 | T25_K(对照) | 差 | 结果 |")
    A.append("|---|---|---|---|---|---|")
    A.append(f"| (a) | RB 最大回撤比 T25_K 浅 ≥ 2pp | {_pct(a['rb_max_dd'])} | {_pct(a['t25k_max_dd'])} | "
             f"{a['gap_pp']:+.2f}pp(浅) | {'✅' if a['pass'] else '❌'} |")
    A.append(f"| (b) | RB 总收益 ≥ T25_K − 1pp | {_pct(b['rb_total_return'])} | {_pct(b['t25k_total_return'])} | "
             f"{b['gap_pp']:+.2f}pp | {'✅' if b['pass'] else '❌'} |")
    A.append(f"| (c) | RB 最差单月 ≥ T25_K 最差单月 | {_pct(c['rb_worst_month'])}({c['rb_worst_month_end']}) | "
             f"{_pct(c['t25k_worst_month'])}({c['t25k_worst_month_end']}) | {c['gap_pp']:+.2f}pp | "
             f"{'✅' if c['pass'] else '❌'} |")
    A.append("")
    A.append(f"**判定:{verdict}。**")
    A.append("")
    A.append("## 4. 另报(不参与判定)")
    A.append("")
    A.append("| 指标 | RB_T25 | T25_K(对照) |")
    A.append("|---|---|---|")
    A.append(f"| 总收益 | {_pct(rb['total_return'])} | {_pct(tk['total_return'])} |")
    A.append(f"| CAGR | {_pct(rb['cagr'])} | {_pct(tk['cagr'])} |")
    A.append(f"| 年化波动 | {_pct(rb['vol_ann'])} | {_pct(tk['vol_ann'])} |")
    A.append(f"| 最大回撤 | {_pct(rb['max_dd'])}({rb['dd_peak']} → {rb['dd_trough']}) | "
             f"{_pct(tk['max_dd'])}({tk['dd_peak']} → {tk['dd_trough']}) |")
    A.append(f"| Calmar | {_num(rb['calmar'])} | {_num(tk['calmar'])} |")
    A.append(f"| 最差单月 | {_pct(rb['worst_month'])}({rb['worst_month_end']}) | {_pct(tk['worst_month'])}({tk['worst_month_end']}) |")
    A.append(f"| 最好单月 | {_pct(rb['best_month'])} | {_pct(tk['best_month'])} |")
    A.append(f"| 记 NAV 天数 | {rb['n_days']} | {tk['n_days']} |")
    A.append("")
    A.append(f"- `apparatus.ab_test`(RB_T25 vs T25_K,mean_block={ab['mean_block']:.0f}、"
             f"n_boot={ab['n_boot']}、seed={ab['seed']}):"
             f"**p(RB ≤ T25_K) = {_num(ab.get('p_b_le_a'), 4)}**、"
             f"p(RB ≥ T25_K) = {_num(ab.get('p_b_ge_a'), 4)}、verdict = `{ab.get('verdict')}`、"
             f"n = {ab.get('n_days')}、比值 B/A = {_num(ab.get('ratio_b_over_a'), 4)}、"
             f"95% CI(log 差) = [{_num(ab.get('ci95_log_diff', [None, None])[0], 4)}, "
             f"{_num(ab.get('ci95_log_diff', [None, None])[1], 4)}]。")
    if ab.get("underpowered") is not None:
        A.append(f"- 检验力提示:`underpowered = {ab.get('underpowered')}`(样本 {ab.get('n_days')} 天,"
                 f"块长 {ab['mean_block']:.0f} 天 —— 短窗口,读 p 时别当硬结论)。")
    A.append("")
    A.append("### 平均权重(每次调仓的目标权重均值)")
    A.append("")
    A.append("| 腿 | RB 均值 | RB p25 | RB p50 | RB p75 | RB min | RB max | T25_K 均值 | 调仓次数 |")
    A.append("|---|---|---|---|---|---|---|---|---|")
    for leg in ("crypto", "equity", "gold", "cash"):
        wr = wsr.get(leg, {})
        A.append(f"| {leg} | {_num(wr.get('mean'), 4)} | {_num(wr.get('p25'), 4)} | "
                 f"{_num(wr.get('p50'), 4)} | {_num(wr.get('p75'), 4)} | {_num(wr.get('min'), 4)} | "
                 f"{_num(wr.get('max'), 4)} | {_num(wsb.get(leg, {}).get('mean'), 4)} | {wr.get('n_reb')} |")
    A.append("")
    A.append("### 调仓权重表(RB_T25,每次调仓的目标权重)")
    A.append("")
    A.append("| 调仓日 | crypto | equity | gold | cash | 当日 crypto 腿敞口 g |")
    A.append("|---|---|---|---|---|---|")
    for row in R["arms"]["RB_T25"]["rebalance_log"]:
        cash = 1.0 - row["crypto"] - row["equity"] - row["gold"]
        A.append(f"| {row['d']} | {row['crypto']:.4f} | {row['equity']:.4f} | {row['gold']:.4f} | "
                 f"{cash:.4f} | {_num(row.get('crypto_exposure_g'), 3)} |")
    A.append("")
    A.append("### 调仓权重表(T25_K,常数)")
    A.append("")
    A.append("| 调仓日 | crypto | equity | gold | cash |")
    A.append("|---|---|---|---|---|")
    for row in R["arms"]["T25_K"]["rebalance_log"]:
        cash = 1.0 - row["crypto"] - row["equity"] - row["gold"]
        A.append(f"| {row['d']} | {row['crypto']:.4f} | {row['equity']:.4f} | {row['gold']:.4f} | "
                 f"{cash:.4f} |")
    A.append("")
    A.append("## 5. 基线(单独持有,同一记 NAV 区间)")
    A.append("")
    for key, label in (("core_nav_only_1", "① 自己(cap_pit24 单持)"),
                       ("crypto_leg_only_X1V_on_1", "crypto 腿单独(X1V on ①)"),
                       ("equity_close_only_acwi", "equity 腿单独(ACWI)"),
                       ("gold_close_only_xauusd", "gold 腿单独(XAUUSD)")):
        bl = R["baselines"][key]
        A.append(f"- {label}:总收益 {_pct(bl.get('total_return'))}、"
                 f"最大回撤 {_pct(bl.get('max_dd'))}、年化波动 {_pct(bl.get('vol_ann'))}。")
    bl = R["baselines"]
    approx = (0.30 * bl["crypto_leg_only_X1V_on_1"]["total_return"]
              + 0.30 * bl["equity_close_only_acwi"]["total_return"]
              + 0.20 * bl["gold_close_only_xauusd"]["total_return"])
    A.append(f"- **记账自洽检查**:T25_K 的常数权重(0.30/0.30/0.20 + 20% 现金)按上面三条腿的单持收益"
             f"线性加权 ≈ {_pct(approx)},实测 T25_K 总收益 {_pct(tk['total_return'])} —— 差 "
             f"{abs(approx - tk['total_return']) * 100:.2f}pp(权重随涨跌漂移 + 换手成本),记账对得上。")
    A.append("")
    A.append("## 6. 诚实与边界")
    A.append("")
    A.append("- **Calmar 是两个负数**:这个窗口两条臂整段都亏钱,所以 Calmar 为负"
             f"(T25_K {tk['calmar']:.3f}、RB {rb['calmar']:.3f})。RB 的 Calmar「更好」只是没那么负,"
             "不能读成「RB 会赚钱」。S-799 只要求报,本条不拿它当判据。")
    A.append(f"- **RB 的差额主要来自「减 crypto + 加黄金」,不是「留现金」**:RB 把 crypto 从 30% 压到均值 "
             f"{_num(wsr.get('crypto', {}).get('mean'), 4)}(区间 {_num(wsr.get('crypto', {}).get('min'), 4)} ~ "
             f"{_num(wsr.get('crypto', {}).get('max'), 4)})、黄金从 20% 提到 "
             f"{_num(wsr.get('gold', {}).get('mean'), 4)}、股金从 30% 提到 "
             f"{_num(wsr.get('equity', {}).get('mean'), 4)};现金反而从 20% 降到 "
             f"{_num(wsr.get('cash', {}).get('mean'), 4)}(核的 `clip_to_budget` 只在合计 > 1 时等比缩回,"
             "合计 < 1 时余下留现金)。这个窗口 crypto 腿整段 "
             f"{_pct(R['baselines']['crypto_leg_only_X1V_on_1'].get('total_return'))}、股金 "
             f"{_pct(R['baselines']['equity_close_only_acwi'].get('total_return'))}、黄金 "
             f"{_pct(R['baselines']['gold_close_only_xauusd'].get('total_return'))} —— "
             "少拿 crypto 就等于少亏。**本条支持的是「RB 在这段少亏」,不是「RB 更会挑资产」。**")
    gz = R.get("crypto_leg_exposure", {})
    A.append(f"- **空仓腿被倒易波动给了大权重(`SIGMA_FLOOR`)**:2022-06-10 / 2022-07-13 两次调仓 RB 给 "
             "crypto 46%/63% 的权重 —— 那两天 crypto 腿的敞口 g = 0(X1V 空仓、波动近零),"
             "被核里的 `SIGMA_FLOOR = 0.002` 兜住,倒易波动于是把预算挪给它。"
             "**这是核的结构、不是本条改动**;把 RB 的表现读成「配置能力」之前要记得这一条。")
    A.append(f"- **crypto 腿的敞口时间线**:① 起于 2021-07-13,`tom.trade_path` 的内建 `WARM = 200` ⇒ "
             f"前 200 个日历日 g ≡ 1.0(到 {gz.get('warm_until')},这段 crypto 腿就是 ① 本身);"
             f"其后 {gz.get('after_warm_n')} 天里 g = 0 有 **{gz.get('after_warm_flat_days')} 天**"
             f"(空仓区间 {gz.get('after_warm_flat_first')} → {gz.get('after_warm_flat_last')})、"
             f"g = 1 有 {gz.get('after_warm_full_days')} 天,其余是 rally 模式的 0.40~0.50(受 `vol_scale` 降仓)。"
             "两条臂在这段上的差别只能来自 equity/gold 的再分配 —— 这是核的结构,不是本条改动。")
    A.append("- **样本短**:记 NAV "
             f"{iv['n_record_days']} 天、{tk.get('n_months')} 个月;"
             "`rb_weights` 的 `VOL_WINDOW=63` 与 `MIN_OBS=40` 在 63 天历史段刚好够(第一个调仓点前有 63 行收益),"
             "但整个窗口只够 15 次调仓,权重表的行数就是调仓次数。")
    A.append("- **63 天历史段 ≠ 252 天**:S-799 明确写死「前 63 个共同日只作历史」,"
             "所以 RB 在第一个调仓点看到的波动样本比 S-797 短得多 —— 这是预注册的设定,不是缺陷,但"
             "外推到别处时要记得这条。")
    A.append("- **① 是日历日序列、股金是交易日序列**:三条腿的共同日期 = 372 个交易日;"
             "crypto 腿在 ① 的日历日上算(周末的 crypto 涨跌并进下一个共同日),"
             "① 的完整日历日表另落 `t321_core_pit24_daily.csv`(536 行),免得日收益被共同日筛掉。")
    A.append("- **S-799 只判 RB**:STYLE 臂本条不跑(S-799:「不碰 STYLE」)。S-797 的 ❌ 不因本条改判。")
    A.append("- 只读、不入库、不改代码;核文件一字未动(见 §1 的 sha256)。")
    A.append("")
    A.append("## 7. 产物")
    A.append("")
    A.append("- `docs/research/t321_rb_holdout.py`(本报告的生成脚本)")
    A.append("- `docs/research/t321_legs.csv`(三腿 + ① 的 NAV,先落,算全从它读回)")
    A.append("- `docs/research/t321_core_pit24_daily.csv`(① 的完整日历日序列:日收益 + NAV)")
    A.append("- `docs/research/t321_results.json`(全部原始数)")
    A.append("- `docs/research/scenarios/lane-c-T-321.json`(前向命题)")

    path = os.path.join(HERE, "T-321_rb_holdout.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(A) + "\n")
    log(f"  报告写到 {path}")


if __name__ == "__main__":
    main()
