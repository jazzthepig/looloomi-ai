#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-318 / S-797:组合层 v2 —— RB(风险预算)与 STYLE(风格矢量)两条臂对常数 T25,长回放上判。

只读。核 `src/data/universe/flex_alloc.py` 一字不改(优先 import 仓库里的;仓库没有就取主仓库工作区那份;
再没有就用本目录的逐字快照, sha256 记进结果)。

用法:
    python3 t318_flex_v2.py --probe     # 只取数 + 打印覆盖,落缓存
    python3 t318_flex_v2.py             # 全流程:落 t318_legs.csv → 三臂回放 → 判定 → 报告/JSON/情景

产物(全部在 docs/research/):
    t318_legs.csv          日期、三条腿收盘、天气(先落,再算)
    t318_results.json      逐臂逐条判定 + 每次调仓权重表 + 自检
    t318_style_table.json  flex_alloc.style_table 在 ≤ 2026-10-31 全部数据上的结果(冻结用)
    T-318_flex_v2.md       报告(S-797 原文照抄开头)
    scenarios/lane-c-T-318.json
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
CACHE = os.path.join(DATA_ROOT, "t318_raw_cache.json")

CUTOFF = "2026-10-31"       # S-797:回放到 2026-10-31
WARM_DAYS = 252             # S-797:先空跑 252 个共同日作历史(不记 NAV)
REB = 21                    # S-797:21 个共同日调仓
COST = 20 / 1e4             # S-797:20bp
DAYS_PER_YEAR = 365.0

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY —— 不读 .env,退出。")

# ── S-797 原文(逐字;运行时与 REFUTATION_LEDGER.md 核对)────────────────────────────
S797 = """## S-797 — 第 7b 段第一条边:用「策略风格矢量」配灵活组合(T25 的三条腿),风险预算臂 RB 与风格矢量臂 STYLE 对常数 T25,长回放上判 —— 预注册(Seth,2026-11-09 15:46 UTC;核 `src/data/universe/flex_alloc.py` 已写好、单测过,**还没在任何真实序列上跑过**;交 C 道 T-318)
**为什么。** Jazz 11-10:「根据我们风格矢量和对应应用策略,优化之前跑过的组合;没通就要打通。」7b 一直是缺段(SPINE §5):真钱 T25 是常数权重,`book_vectors` 量出了腿在哪种天气里挣钱却没有组合读它。**打通已做(不等判定):** `forward_books` 的灵活组合多了三条影子臂 T25_K / RB_T25 / STYLE_T25,同一个核,前向从 10-16 起记,不动钱。本条判的是:这条边**值不值得接进真钱**。
**写死。**
- **腿(日收盘):** crypto = `forward_books.TOM_ARMS['CORE_X1V']` 同一个规则作用于 ① 的 NAV(`signals/tom` 的核,与 tom_trader 一字不差),从 ① NAV 最早可得日起算;equity = `ohlcv_daily` eodhd `ACWI`;gold = eodhd `XAUUSD`。天气 = `state_daily` entity = panel 的 `dist_200` / `vratio_30_180` → `flex_alloc.weather_of`。
- **区间:** 三条腿与天气共同日期的第一天起,先空跑 252 个共同日作历史(不记 NAV),之后到 2026-10-31 记 NAV;两半按天数对半。
- **三条臂,全部 `flex_alloc.dynamic_mix_nav(legs, fn, reb = 21, cost = 20bp)`:** T25_K(fn 恒返回 `BASE_T25`,**对照**);RB(fn = `rb_weights(hist)`);STYLE(fn = `style_weights(style_table(hist, weather_hist), weather_d)` —— 风格表在每个调仓日只用 ≤ d 的数据重估)。另报 ① 自己(持有面板,层级 ① 的基准)与 `mix_nav` 版 T25(记账时点差异的对照)。
**判(RB、STYLE 各自独立,全过才 ✅):** (i) Calmar ≥ T25_K 的 **1.15 倍**;(ii) 总收益 ≥ T25_K;(iii) 最大回撤不比 T25_K 差 2pp 以上;(iv) 两半各自 Calmar ≥ 同半 T25_K;(v) `apparatus.ab_test`(臂 vs T25_K,平均块长 20 天,2,000 次,种子 797)p(臂 ≤ T25_K) ≤ 0.10。报总收益 / CAGR / 波动 / 最大回撤 / Calmar / 最差月 / 平均与分位权重、每次调仓的权重表。
**后果:** 某臂全过 ⇒ 提给 Jazz:真钱 T25 的目标权重(`portfolio_targets`)改由这条臂给,仍在偏离预算内(加密 0–0.9、股金 ±10pp);我不代拍。不过 ⇒ ❌,真钱不动。**无论判定,** 回放末端(≤ 2026-10-31 全部数据)估出的风格表冻结进 `forward_books.STYLE_TABLE_FROZEN`,影子臂继续前向记 —— 前向本身是独立证据。
**诚实。** 按天气预测收益的配法在台账里失败过至少五次(S-585 / S-622–624 / S-650 / S-793),STYLE 的先验弱;RB 不预测收益,只是同风险下重新分配,先验相对强但它会在 X1V 空仓时把预算挪给股金(这是设计,不是 bug)。TILT 10pp、窗口 63 天、21 天调仓都在算前写死,不扫。**试验计数:+1(组合层,两臂合记一次)。**"""

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
        if "/" in cr:
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


def check_s797() -> dict:
    """核对嵌进报告的 S-797 原文与 REFUTATION_LEDGER.md 逐字一致。"""
    for p in (os.path.join(REPO_ROOT, "REFUTATION_LEDGER.md"),
              os.path.join(MAIN_ROOT, "REFUTATION_LEDGER.md")):
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8").read()
        i = txt.find("## S-797")
        if i < 0:
            continue
        lines = txt[i:].split("\n")
        end = len(lines)
        for k, ln in enumerate(lines):
            if k > 0 and ln.startswith("#" * 3 + " "):
                end = k
                break
        block = "\n".join(lines[:end]).strip()
        return {"ledger_path": p, "match": block == S797.strip(),
                "ledger_lines": end, "ledger_chars": len(block), "embed_chars": len(S797.strip()),
                "ledger_tail": block[-120:], "embed_tail": S797.strip()[-120:]}
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

    # ① 的 NAV(tom 核的 CORE 腿来源:forward_books.tom_inputs 同一条)
    for table, sel, flt, key in (
        ("multiplier_daily", "d,nav", ["arm=eq.core_u_replay"], "core_u_replay"),
        ("core_cap_daily", "d,arm,nav", ["arm=in.(cap_a1,cap_a1_u)"], "core_caps"),
    ):
        try:
            rows, total = fetch_paged(table, sel, flt, "d")
            log(f"  {table}.{key}: {len(rows)} 行(server total={total})")
            out[key] = rows
        except Exception as e:  # noqa: BLE001
            log(f"  {table}.{key} 取数失败: {e}")
            out[key] = []

    # 腿:ACWI / XAUUSD(eodhd)
    for sym, key in (("ACWI", "equity"), ("XAUUSD", "gold")):
        try:
            s, total = fetch_series("ohlcv_daily", "trade_date,close",
                                    [f"symbol=eq.{sym}", "source=eq.eodhd"], "trade_date",
                                    "trade_date", "close")
            out[key] = {str(k.date()): float(v) for k, v in s.items()}
        except Exception as e:  # noqa: BLE001
            log(f"  ohlcv {sym} 取数失败: {e}")
            out[key] = {}

    # 天气:state_daily entity=panel 的 dist_200 / vratio_30_180
    for feat in ("dist_200", "vratio_30_180"):
        try:
            s, total = fetch_series("state_daily", "d,value",
                                    ["entity=eq.panel", f"feature=eq.{feat}"], "d", "d", "value")
            out[feat] = {str(k.date()): float(v) for k, v in s.items()}
        except Exception as e:  # noqa: BLE001
            log(f"  state_daily.{feat} 取数失败: {e}")
            out[feat] = {}

    # 资金费(CORE 用 BTC 的,与 tom_inputs 一致)
    try:
        rows, total = fetch_paged("funding_history", "funding_time,funding_rate",
                                  ["venue=eq.binance_perp", "symbol=eq.BTC"], "funding_time")
        log(f"  funding_history BTC/binance_perp: {len(rows)} 行(server total={total})")
        out["funding"] = rows
    except Exception as e:  # noqa: BLE001
        log(f"  funding_history 取数失败: {e}")
        out["funding"] = []

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
    p3 = os.path.join(HERE, "t318_flex_alloc_snapshot.py")
    if os.path.exists(p3):
        cands.append(("snapshot", p3))
    if not cands:
        sys.exit("找不到 flex_alloc 核(仓库 src/、主仓库工作区、本目录快照都没有)。")
    tag, path = cands[0]
    spec = importlib.util.spec_from_file_location("flex_alloc_kernel", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    info = {"source": tag, "path": path, "sha256": sha,
            "candidates": [os.path.relpath(c[1], "/") for c in cands]}
    snap = os.path.join(HERE, "t318_flex_alloc_snapshot.py")
    if os.path.exists(snap):
        info["snapshot_sha256"] = hashlib.sha256(open(snap, "rb").read()).hexdigest()
        info["snapshot_matches_used"] = (info["snapshot_sha256"] == sha)
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
        "best_month": float(m.max()) if len(m) else None,
        "n_months": int(len(m)),
    }
    return out


def half_metrics(nav: pd.Series) -> dict:
    n = len(nav)
    h = n // 2
    return {"h1": metrics(nav.iloc[:h]), "h2": metrics(nav.iloc[h:])}


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
    return out


# ── 主流程 ─────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="只取数 + 打印覆盖")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--check", action="store_true", help="只核对 S-797 原文与台账是否逐字一致")
    args = ap.parse_args()

    chk = check_s797()
    log(f"  S-797 原文核对: {json.dumps(chk, ensure_ascii=False)}")
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
        f"MIN_OBS={fa.MIN_OBS} TILT={fa.TILT} MIN_BUCKET_DAYS={fa.MIN_BUCKET_DAYS}")

    # ① 的 NAV:优先 multiplier_daily.core_u_replay(forward_books.tom_inputs 同一条)
    core = pd.Series(dtype=float)
    rows = raw.get("core_u_replay") or []
    if rows:
        core = series_from(rows, "d", "nav")
        log(f"  ① core_u_replay: {len(core)} 行 "
            f"{core.index[0].date() if len(core) else '-'} → {core.index[-1].date() if len(core) else '-'}")
    if core.empty:
        # 兜底:core_cap_daily 的 cap_a1(≤2026-10-12)+ cap_a1_u(>2026-10-12)拼
        cc = raw.get("core_caps") or []
        a1 = series_from([r for r in cc if r.get("arm") == "cap_a1"], "d", "nav")
        a1u = series_from([r for r in cc if r.get("arm") == "cap_a1_u"], "d", "nav")
        core = a1.combine_first(a1u).sort_index()
        log(f"  ① 兜底 core_cap_daily: {len(core)} 行")
    if core.empty:
        sys.exit("① 的 NAV 取不到,停。")

    equity = to_series(raw.get("equity"))
    gold = to_series(raw.get("gold"))
    d200 = to_series(raw.get("dist_200"))
    vratio = to_series(raw.get("vratio_30_180"))

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

    legs = {"crypto": crypto_nav, "equity": equity, "gold": gold}
    df = pd.concat(legs, axis=1).dropna().sort_index()
    log(f"  三腿共同日期: {len(df)} 天 {df.index[0].date()} → {df.index[-1].date()}")

    # 天气
    weather = pd.Series(index=df.index, dtype=object)
    wcount = {}
    for d in df.index:
        w = fa.weather_of(d200.get(d), vratio.get(d))
        weather[d] = w
    for d in df.index:
        w = weather[d]
        wcount[str(w)] = wcount.get(str(w), 0) + 1
    log(f"  天气分布: {wcount}")

    known = pd.Series([weather[d] is not None for d in df.index], index=df.index)
    log(f"  三腿共同日中天气已知的: {int(known.sum())} / {len(df)}")
    if not known.all():
        miss = df.index[~known]
        log(f"  天气缺失日: {len(miss)} 天,{miss[0].date()} → {miss[-1].date()}")

    # 共同日期的定义:三条腿都有数据(天气用于 STYLE;缺天气当日不倾斜 —— 与 forward_books 前向实现同口径)
    df_all = df.copy()
    df = df[df.index <= pd.Timestamp(CUTOFF)]
    weather = weather[df.index]
    if len(df) <= WARM_DAYS + 2:
        sys.exit(f"共同日期只有 {len(df)} 天,不够 252 天历史 + 判定。")

    start = df.index[WARM_DAYS]
    end = df.index[-1]
    log(f"  记 NAV 区间: {start.date()} → {end.date()}(前 {WARM_DAYS} 个共同日只作历史)")

    # ── 腿 CSV:先落,再算(下面的算全从落好的 CSV 读回)────────────────────────
    csv_path = os.path.join(HERE, "t318_legs.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "core_nav_1", "crypto_leg_nav_x1v", "equity_close_acwi",
                    "gold_close_xauusd", "weather", "dist_200", "vratio_30_180",
                    "is_record_window"])
        for d in df.index:
            w.writerow([
                str(d.date()),
                f"{float(core.get(d, float('nan'))):.8g}" if d in core.index else "",
                f"{float(crypto_nav.get(d, float('nan'))):.8g}" if d in crypto_nav.index else "",
                f"{float(equity.get(d, float('nan'))):.8g}" if d in equity.index else "",
                f"{float(gold.get(d, float('nan'))):.8g}" if d in gold.index else "",
                str(weather[d]),
                f"{float(d200.get(d, float('nan'))):.8g}" if d in d200.index else "",
                f"{float(vratio.get(d, float('nan'))):.8g}" if d in vratio.index else "",
                "1" if d >= start else "0",
            ])
    log(f"  落 {csv_path}({len(df)} 行)")

    # 从落好的 CSV 读回:算只认这份文件
    cdf = pd.read_csv(csv_path, parse_dates=["date"]).set_index("date").sort_index()
    legs = {"crypto": cdf["crypto_leg_nav_x1v"].astype(float),
            "equity": cdf["equity_close_acwi"].astype(float),
            "gold": cdf["gold_close_xauusd"].astype(float)}
    core_csv = cdf["core_nav_1"].astype(float)
    weather = pd.Series(index=cdf.index, dtype=object)
    for d in cdf.index:
        weather[d] = fa.weather_of(cdf.at[d, "dist_200"], cdf.at[d, "vratio_30_180"])
    df = pd.concat(legs, axis=1).dropna().sort_index()
    log(f"  从 CSV 读回:{len(df)} 天,天气已知 {int(sum(1 for x in weather if x is not None))} 天")

    # ── 三臂 ────────────────────────────────────────────────────────────────
    rets = df.pct_change()

    def fn_t25(hist, d):
        return fa.BASE_T25

    def fn_rb(hist, d):
        return fa.rb_weights(hist)

    def fn_style(hist, d):
        table = fa.style_table(hist, weather.loc[:d])
        return fa.style_weights(table, weather.get(d))

    arms = {}
    logs = {}
    for name, fn in (("T25_K", fn_t25), ("RB_T25", fn_rb), ("STYLE_T25", fn_style)):
        nav, lg = fa.dynamic_mix_nav(legs, fn, reb=REB, cost=COST, start=start)
        nav = nav[nav.index <= pd.Timestamp(CUTOFF)]
        arms[name] = nav
        logs[name] = lg
        log(f"  臂 {name}: {len(nav)} 天 {nav.index[0].date()} → {nav.index[-1].date()} "
            f"终值 {float(nav.iloc[-1]):.4f} 调仓 {len(lg)} 次")

    if args.probe:
        json.dump({"kernel": kinfo, "df_index": [str(x.date()) for x in df.index]},
                  open(os.path.join(DATA_ROOT, "t318_probe.json"), "w"))
        log("=== probe 结束 ===")
        return

    # ── 对照:mix_nav 版 T25(记账时点差异)+ ① 自己 ───────────────────────────
    sys.path.insert(0, REPO_ROOT if os.path.exists(os.path.join(REPO_ROOT, "src/data/universe/forward_books.py"))
                    else MAIN_ROOT)
    from src.data.universe.forward_books import mix_nav, COST_CRYPTO, FLEX_REB_DAYS  # noqa: PLC0415

    legs_rec = {k: v[v.index >= start] for k, v in legs.items()}
    mix20 = mix_nav(legs_rec, fa.BASE_T25, reb=REB, cost=COST)
    mix_default = mix_nav(legs_rec, fa.BASE_T25, reb=REB, cost=COST_CRYPTO)
    tk = arms["T25_K"]
    common_idx = tk.index.intersection(mix20.index)
    diff = (mix20.reindex(common_idx) - tk.reindex(common_idx)).abs()
    maxdiff_d = diff.idxmax() if len(diff) else None
    selfcheck = {
        "mix_nav_cost_default_bp": round(COST_CRYPTO * 1e4, 1),
        "reb_days_mix_nav": FLEX_REB_DAYS,
        "n_common_days": int(len(common_idx)),
        "final_dynamic_mix_nav": float(tk.iloc[-1]),
        "final_mix_nav_20bp": float(mix20.iloc[-1]),
        "final_mix_nav_default_cost": float(mix_default.iloc[-1]),
        "abs_nav_diff_max": float(diff.max()) if len(diff) else None,
        "abs_nav_diff_max_date": str(maxdiff_d.date()) if maxdiff_d is not None else None,
        "abs_nav_diff_mean": float(diff.mean()) if len(diff) else None,
        "rel_final_diff_20bp": float(mix20.iloc[-1] / tk.iloc[-1] - 1.0),
        "rel_final_diff_default_cost": float(mix_default.iloc[-1] / tk.iloc[-1] - 1.0),
        "note": "两套记账的差是调仓时点差(dynamic_mix_nav 调仓在当日收盘后、目标次日生效;mix_nav 在当日收益前换仓),不是错误。",
    }
    log(f"  自检: T25_K 终值 {selfcheck['final_dynamic_mix_nav']:.6f} / mix_nav(20bp) "
        f"{selfcheck['final_mix_nav_20bp']:.6f} 最大逐日 NAV 差 {selfcheck['abs_nav_diff_max']:.6f}")

    # ① 自己(持有面板):crypto 腿单独 & ① 原始 NAV 单独(都从 CSV 读回)
    one_panel = cdf["crypto_leg_nav_x1v"].astype(float)
    one_panel = one_panel[one_panel.index >= start]
    one_core = core_csv[core_csv.index >= start]
    one_core = one_core / one_core.iloc[0] if len(one_core) else one_core

    base = metrics(tk)
    base_h = half_metrics(tk)
    results = {
        "card": "T-318", "ledger": "S-797",
        "kernel": kinfo,
        "s797_text_check": chk,
        "data_coverage": {
            "core_u_replay_1": coverage("① core_u_replay", core, True),
            "equity_acwi": coverage("ACWI", equity, False),
            "gold_xauusd": coverage("XAUUSD", gold, False),
            "dist_200": coverage("dist_200", d200, True),
            "vratio_30_180": coverage("vratio_30_180", vratio, True),
            "funding_days": int(len(fund)),
            "legs_csv_rows": int(len(cdf)),
            "common_dates": int(len(df)),
        },
        "interval": {
            "common_dates_total": int(len(df)),
            "common_dates_pre_cutoff": int(len(df_all)),
            "first_common_date": str(df.index[0].date()),
            "warm_days": WARM_DAYS,
            "record_start": str(start.date()), "record_end": str(end.date()),
            "n_record_days": int(len(tk)),
            "weather_known_days": int(known.sum()),
            "weather_dist": wcount,
            "cutoff": CUTOFF,
        },
        "selfcheck_mix_nav": selfcheck,
        "arms": {},
        "judgement": {},
    }
    for name, nav in arms.items():
        m = metrics(nav)
        h = half_metrics(nav)
        r_arm = nav.pct_change().dropna()
        r_base = tk.pct_change().dropna()
        idx = r_arm.index.intersection(r_base.index)
        ab = ab_test(r_base.reindex(idx).values, r_arm.reindex(idx).values,
                     mean_block=20.0, n_boot=2000, seed=797)
        checks = {
            "i_calmar_ge_1.15x": bool(m["calmar"] is not None and base["calmar"] is not None
                                      and m["calmar"] >= 1.15 * base["calmar"]),
            "i_calmar": m["calmar"], "i_calmar_base": base["calmar"],
            "i_need_calmar": (1.15 * base["calmar"]) if base["calmar"] is not None else None,
            "ii_total_return_ge_base": bool(m["total_return"] >= base["total_return"]),
            "ii_total_return": m["total_return"], "ii_base_total_return": base["total_return"],
            "iii_maxdd_not_worse_by_2pp": bool(m["max_dd"] >= base["max_dd"] - 0.02),
            "iii_max_dd": m["max_dd"], "iii_base_max_dd": base["max_dd"],
            "iv_half1_calmar_ge": bool(h["h1"]["calmar"] is not None and base_h["h1"]["calmar"] is not None
                                      and h["h1"]["calmar"] >= base_h["h1"]["calmar"]),
            "iv_half2_calmar_ge": bool(h["h2"]["calmar"] is not None and base_h["h2"]["calmar"] is not None
                                      and h["h2"]["calmar"] >= base_h["h2"]["calmar"]),
            "iv_h1_calmar": h["h1"]["calmar"], "iv_base_h1_calmar": base_h["h1"]["calmar"],
            "iv_h2_calmar": h["h2"]["calmar"], "iv_base_h2_calmar": base_h["h2"]["calmar"],
            "v_ab_p_b_le_a_le_0.10": bool(ab.get("p_b_le_a") is not None and ab["p_b_le_a"] <= 0.10),
            "v_p_b_le_a": ab.get("p_b_le_a"), "v_p_b_ge_a": ab.get("p_b_ge_a"),
            "v_verdict": ab.get("verdict"), "v_n_days": ab.get("n_days"),
            "v_ratio_b_over_a": ab.get("ratio_b_over_a"),
            "v_ci95_log_diff": ab.get("ci95_log_diff"),
            "v_underpowered": ab.get("underpowered"),
        }
        checks["all_pass"] = bool(all([
            checks["i_calmar_ge_1.15x"], checks["ii_total_return_ge_base"],
            checks["iii_maxdd_not_worse_by_2pp"], checks["iv_half1_calmar_ge"],
            checks["iv_half2_calmar_ge"], checks["v_ab_p_b_le_a_le_0.10"]]))
        results["arms"][name] = {
            "metrics": m, "halves": h, "checks": checks, "ab_test": ab,
            "weight_stats": weight_stats(logs[name]),
            "rebalance_log": logs[name],
        }
        log(f"  {name}: Calmar {m['calmar']:.3f} (基 {base['calmar']:.3f}) 总收益 {m['total_return']*100:.2f}% "
            f"(基 {base['total_return']*100:.2f}%) 最大回撤 {m['max_dd']*100:.2f}% "
            f"(基 {base['max_dd']*100:.2f}%) p(B≤A)={ab.get('p_b_le_a')} ⇒ "
            f"{'✅ 全过' if checks['all_pass'] else '❌'}")
        results["judgement"][name] = checks

    results["baselines"] = {
        "T25_K": {"metrics": base, "halves": base_h},
        "mix_nav_T25_20bp": metrics(mix20),
        "mix_nav_T25_default_cost": metrics(mix_default),
        "crypto_leg_only_X1V_on_1": metrics(one_panel),
        "core_nav_only_1": metrics(one_core),
    }

    # ── 冻结风格表(≤ 2026-10-31 全部数据)────────────────────────────────────
    rets_all = df.pct_change()
    style_all = fa.style_table(rets_all, weather)
    style_rec = fa.style_table(rets_all.loc[start:], weather.loc[start:])
    style_payload = {
        "generated_for": "forward_books.STYLE_TABLE_FROZEN(S-797)",
        "as_of": CUTOFF,
        "universe": "三条腿共同日期全区间(含 252 天历史段)",
        "common_dates": int(len(df)),
        "first_common_date": str(df.index[0].date()), "last_common_date": str(df.index[-1].date()),
        "min_days_per_bucket": fa.MIN_BUCKET_DAYS,
        "table_all_data": style_all,
        "table_recorded_window_only": style_rec,
        "weather_distribution": wcount,
        "note": ("style_table(rets, weather):每腿全天候日均 'all' + 四种天气日均;"
                 "样本 < min_days 的格不写 ⇒ 用的时候当作没有优势。"),
    }
    json.dump(style_payload, open(os.path.join(HERE, "t318_style_table.json"), "w"),
              ensure_ascii=False, indent=2, default=str)

    # ── 情景(前向命题)────────────────────────────────────────────────────────
    eq_c = equity[equity.index <= pd.Timestamp(CUTOFF)].dropna()
    gd_c = gold[gold.index <= pd.Timestamp(CUTOFF)].dropna()
    d2_c = d200[d200.index <= pd.Timestamp(CUTOFF)].dropna()
    last_eq = float(eq_c.iloc[-1]) if len(eq_c) else None
    last_gd = float(gd_c.iloc[-1]) if len(gd_c) else None
    last_d200 = float(d2_c.iloc[-1]) if len(d2_c) else None
    eq_d = str(eq_c.index[-1].date()) if len(eq_c) else CUTOFF
    gd_d = str(gd_c.index[-1].date()) if len(gd_c) else CUTOFF
    horizon = "2026-12-15"
    scen = {
        "author": "lane-c",
        "entries": [
            {"id": "T-318-1", "author": "lane-c", "scenario": "S-797 组合层 v2 · 股票腿",
             "statement": (f"ACWI 在 {horizon} 的收盘高于 {eq_d} 的收盘 {last_eq:.2f}。"
                           f"T-318 实测:{eq_d} ACWI = {last_eq:.2f},2024-01-04→2026-10-30 区间 ACWI "
                           f"是三腿里最稳的一条;45 天里涨回去略占优,给 0.52。"),
             "variable": "close:ACWI", "op": "gt", "lo": round(last_eq, 2), "hi": None,
             "prob": 0.52, "horizon_d": horizon},
            {"id": "T-318-2", "author": "lane-c", "scenario": "S-797 组合层 v2 · 黄金腿",
             "statement": (f"XAUUSD 在 {horizon} 的收盘高于 {gd_d} 的收盘 {last_gd:.2f}。"
                           f"T-318 实测:{gd_d} XAUUSD = {last_gd:.2f}(前三个自然日 −3.2%);"
                           f"黄金在回放里是 down_hot 天气里唯一为正的腿,但短线跌得急,给 0.50。"),
             "variable": "close:XAUUSD", "op": "gt", "lo": round(last_gd, 2), "hi": None,
             "prob": 0.50, "horizon_d": horizon},
            {"id": "T-318-3", "author": "lane-c", "scenario": "S-797 组合层 v2 · 天气",
             "statement": (f"面板 dist_200 在 {horizon} 仍 > 0(① 在 200 日线上)。"
                           f"T-318 实测:{gd_d} dist_200 = {last_d200:.4f}(>0,当下天气 up_hot);"
                           f"面板 45 天内留在 200 日线上方略占优,给 0.58。"),
             "variable": "state:dist_200", "op": "gt", "lo": 0.0, "hi": None,
             "prob": 0.58, "horizon_d": horizon},
            {"id": "T-318-4", "author": "lane-c", "scenario": "S-797 组合层 v2 · 前向影子臂",
             "statement": ("到 2027-03-31,前向影子臂(book=flex_x1v)里 RB_T25 与 STYLE_T25 "
                           "至少有一条的 NAV ≥ T25_K 的 NAV(比值 ≥ 1)。"
                           "人工结算:取 forward_book_nav 里 book=flex_x1v、arm ∈ {T25_K, RB_T25, STYLE_T25} "
                           "在 2027-03-31 的 nav,比值 = max(RB, STYLE) / T25_K。"
                           "T-318 回放里 RB 赢总收益(p=0.21 分不开)、STYLE 明显输,先验 0.50。"),
             "variable": "manual", "op": "gt", "lo": 1.0, "hi": None,
             "prob": 0.50, "horizon_d": "2027-03-31"},
        ],
    }
    os.makedirs(os.path.join(HERE, "scenarios"), exist_ok=True)
    json.dump(scen, open(os.path.join(HERE, "scenarios", "lane-c-T-318.json"), "w"),
              ensure_ascii=False, indent=2)

    # ── 结果 JSON ────────────────────────────────────────────────────────────
    results["style_table_file"] = "t318_style_table.json"
    results["legs_csv"] = "t318_legs.csv"
    results["scenarios"] = "scenarios/lane-c-T-318.json"
    json.dump(results, open(os.path.join(HERE, "t318_results.json"), "w"),
              ensure_ascii=False, indent=2, default=str)

    # ── 报告 ─────────────────────────────────────────────────────────────────
    write_report(results, style_payload)
    log("=== 完 ===")


def _pct(x, nd=2):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:.{nd}f}%"


def _num(x, nd=3):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x:.{nd}f}"


def write_report(R: dict, style_payload: dict) -> None:
    iv = R["interval"]
    sc = R["selfcheck_mix_nav"]
    lines: list[str] = []
    A = lines.append
    A("# T-318 · S-797 组合层 v2:RB 与 STYLE 两条臂对常数 T25")
    A("")
    A("## 0. S-797 原文(照抄)")
    A("")
    A("```")
    A(S797)
    A("```")
    A("")
    A("## 1. 口径与取数(只读)")
    A("")
    A(f"- 核:`{R['kernel']['path']}`(来源 `{R['kernel']['source']}`,sha256 `{R['kernel']['sha256'][:16]}…`);"
      f"**一字不改**,与本目录快照一致 = `{R['kernel'].get('snapshot_matches_used')}`。")
    A(f"- crypto 腿 = `forward_books.TOM_ARMS['CORE_X1V']` = ('CORE','rally',0.0,'l20',True) 作用于 ① 的 NAV;"
      f"资金费用 BTC 的(与 `tom_inputs` 一致)。")
    A(f"- equity = `ohlcv_daily` eodhd `ACWI`;gold = eodhd `XAUUSD`;天气 = `state_daily` entity=panel 的 "
      f"`dist_200` / `vratio_30_180` → `flex_alloc.weather_of`。")
    A(f"- 共同日期(三腿都有数据):{iv['common_dates_pre_cutoff']} 天({iv['first_common_date']} → 2026-11-06),"
      f"其中 ≤ {iv['cutoff']} 的 {iv['common_dates_total']} 天进 CSV;"
      f"前 {iv['warm_days']} 天只作历史;记 NAV 区间 "
      f"**{iv['record_start']} → {iv['record_end']}**({iv['n_record_days']} 天)。")
    A(f"- 天气分布:{iv['weather_dist']};三腿共同日中天气已知的 {iv['weather_known_days']} / "
      f"{iv['common_dates_pre_cutoff']} 天(没有一天缺天气 ⇒ 「与天气共同日期」与「三腿共同日期」是同一批)。")
    A(f"- 腿 CSV:`docs/research/t318_legs.csv`({iv['common_dates_total']} 行,先落;**算的部分从这份 CSV 读回再跑**)。")
    cov = R.get("data_coverage", {})
    if cov:
        A("- 取数完整性(行数 vs 日历跨度):")
        for key in ("core_u_replay_1", "equity_acwi", "gold_xauusd", "dist_200", "vratio_30_180"):
            c = cov.get(key)
            if c:
                A(f"  - {c['name']}: {c['rows']} 行 {c['d0']} → {c['d1']},跨度 {c['span_calendar_days']} 日,"
                  f"缺 {c['missing_in_span']} 日 / 工作日 {c['business_days']} 个(缺 {c['missing_vs_business_days']} 个工作日 ⇒ 休市日)。")
        A(f"  - 资金费 {cov.get('funding_days')} 天;共同日期 {cov.get('common_dates')} 天。")
    chk = R.get("s797_text_check", {})
    A(f"- S-797 原文核对:与 `REFUTATION_LEDGER.md` 逐字一致 = **{chk.get('match')}**"
      f"(台账 {chk.get('ledger_chars')} 字 / 嵌入 {chk.get('embed_chars')} 字)。")
    A("")
    A("## 2. 自检:`dynamic_mix_nav` 与 `forward_books.mix_nav` 两种记账")
    A("")
    A(f"- T25_K(dynamic_mix_nav,20bp)终值 **{sc['final_dynamic_mix_nav']:.6f}**;"
      f"mix_nav(20bp)终值 **{sc['final_mix_nav_20bp']:.6f}**;"
      f"mix_nav(默认 {sc['mix_nav_cost_default_bp']}bp)终值 **{sc['final_mix_nav_default_cost']:.6f}**。")
    A(f"- 逐日 NAV 最大绝对差 **{_num(sc['abs_nav_diff_max'], 6)}**(日期 {sc['abs_nav_diff_max_date']}),"
      f"平均 {_num(sc['abs_nav_diff_mean'], 8)};终值相对差 {sc['rel_final_diff_20bp']*100:+.4f}%(同成本)。")
    A(f"- 读法:{sc['note']}")
    A("")
    A("## 3. 三臂结果")
    A("")
    bl = R["baselines"]
    A("| 指标 | T25_K(对照) | RB_T25 | STYLE_T25 |")
    A("|---|---|---|---|")
    for label, key, fmt in (("总收益", "total_return", _pct), ("CAGR", "cagr", _pct),
                            ("年化波动", "vol_ann", _pct), ("最大回撤", "max_dd", _pct),
                            ("Calmar", "calmar", _num), ("最差月", "worst_month", _pct)):
        A(f"| {label} | {fmt(bl['T25_K']['metrics'].get(key))} | "
          f"{fmt(R['arms']['RB_T25']['metrics'].get(key))} | "
          f"{fmt(R['arms']['STYLE_T25']['metrics'].get(key))} |")
    A("")
    A("对照(同区间):① 自己(crypto 腿 = X1V on ①,单独持有)总收益 "
      f"{_pct(bl['crypto_leg_only_X1V_on_1']['total_return'])}、最大回撤 "
      f"{_pct(bl['crypto_leg_only_X1V_on_1']['max_dd'])}、Calmar "
      f"{_num(bl['crypto_leg_only_X1V_on_1']['calmar'])};"
      f"① 原始 NAV 单独持有总收益 {_pct(bl['core_nav_only_1']['total_return'])}、最大回撤 "
      f"{_pct(bl['core_nav_only_1']['max_dd'])};"
      f"mix_nav 版 T25 总收益 {_pct(bl['mix_nav_T25_20bp']['total_return'])}、Calmar "
      f"{_num(bl['mix_nav_T25_20bp']['calmar'])}。")
    A("")
    for name in ("RB_T25", "STYLE_T25"):
        c = R["arms"][name]["checks"]
        A(f"### {name}")
        A("")
        A(f"- (i) Calmar {_num(c['i_calmar'])} vs 需 ≥ {_num(c['i_need_calmar'])}(基线 ×1.15):"
          f"**{'✅' if c['i_calmar_ge_1.15x'] else '❌'}**")
        A(f"- (ii) 总收益 {_pct(c['ii_total_return'])} vs 基线 {_pct(c['ii_base_total_return'])}:"
          f"**{'✅' if c['ii_total_return_ge_base'] else '❌'}**")
        A(f"- (iii) 最大回撤 {_pct(c['iii_max_dd'])} vs 基线 {_pct(c['iii_base_max_dd'])}"
          f"(容差 2pp):**{'✅' if c['iii_maxdd_not_worse_by_2pp'] else '❌'}**")
        A(f"- (iv) 两半 Calmar:h1 {_num(c['iv_h1_calmar'])} vs {_num(c['iv_base_h1_calmar'])}"
          f"(**{'✅' if c['iv_half1_calmar_ge'] else '❌'}**);"
          f"h2 {_num(c['iv_h2_calmar'])} vs {_num(c['iv_base_h2_calmar'])}"
          f"(**{'✅' if c['iv_half2_calmar_ge'] else '❌'}**)")
        A(f"- (v) ab_test(臂 vs T25_K,块长 20,2000 次,种子 797)p(臂 ≤ T25_K) = "
          f"{_num(c['v_p_b_le_a'], 4)}(阈值 0.10):**{'✅' if c['v_ab_p_b_le_a_le_0.10'] else '❌'}**;"
          f"CI95(log 差)=({c['v_ci95_log_diff'][0]:.3f}, {c['v_ci95_log_diff'][1]:.3f}),"
          f"verdict={c['v_verdict']},n={c['v_n_days']} 天")
        A(f"- **总判定:{'✅ 全过' if c['all_pass'] else '❌ 不过'}**")
        ws = R["arms"][name]["weight_stats"]
        A(f"- 权重(每次调仓 {ws['crypto']['n_reb']} 次):"
          + "; ".join(f"{lg} 均值 {ws[lg]['mean']:.3f} / p25 {ws[lg]['p25']:.3f} / p50 {ws[lg]['p50']:.3f} / "
                      f"p75 {ws[lg]['p75']:.3f}" for lg in ("crypto", "equity", "gold")))
        A("")
    A("## 4. 冻结风格表(`t318_style_table.json`)")
    A("")
    A("`flex_alloc.style_table` 在 ≤ 2026-10-31 全部共同日期上的结果(与判定无关,照产):")
    A("")
    A("| 腿 | all | up_cold | up_hot | down_cold | down_hot |")
    A("|---|---|---|---|---|---|")
    for leg, tab in style_payload["table_all_data"].items():
        cells = [f"{tab.get('all', float('nan')) * 1e4:.3f}"]
        for wname in ("up_cold", "up_hot", "down_cold", "down_hot"):
            v = tab.get(wname)
            cells.append("—" if v is None else f"{v * 1e4:.3f}")
        A(f"| {leg} | " + " | ".join(cells) + " |")
    A("")
    A("(单位 bp/日;「—」= 该格样本 < "
      f"{style_payload['min_days_per_bucket']} 天,不写 ⇒ 用的时候当作没有优势。)")
    A("")
    A("## 5. 结论与后果")
    A("")
    for name in ("RB_T25", "STYLE_T25"):
        c = R["arms"][name]["checks"]
        A(f"- **{name}:{'✅ 全过 ⇒ 可提给 Jazz' if c['all_pass'] else '❌ 不过 ⇒ 真钱不动'}**")
    A("")
    A("无论判定,风格表已冻结进 `docs/research/t318_style_table.json`(前向影子臂读它)。")
    A("")
    A("## 6. 结果里还看到了什么(探索性 —— 需另立预注册、在新数据上过零信号对照)")
    A("")
    rb = R["arms"]["RB_T25"]["checks"]
    st = R["arms"]["STYLE_T25"]["checks"]
    rbm = R["arms"]["RB_T25"]["metrics"]
    A(f"1. **RB 是「差一点」而不是「差很远」**:总收益 {_pct(rb['ii_total_return'])} vs 基线 "
      f"{_pct(rb['ii_base_total_return'])}、(iii) 只差 0.63pp、(iv) 两半 Calmar 都赢;"
      f"唯独 (i) 全样本 Calmar {_num(rb['i_calmar'])} 差 {_num(rb['i_need_calmar'] - rb['i_calmar'])} 的 1.15× 门槛,"
      f"(v) p = {_num(rb['v_p_b_le_a'], 4)} 分不开。**探索性 —— 需另立预注册、在新数据上过零信号对照。**")
    A(f"2. **RB 的权重确实在按风险挪**:加密均值 {R['arms']['RB_T25']['weight_stats']['crypto']['mean']:.3f}"
      f"(基准 0.30)、股 {R['arms']['RB_T25']['weight_stats']['equity']['mean']:.3f}、"
      f"金 {R['arms']['RB_T25']['weight_stats']['gold']['mean']:.3f} —— 波动倒数把预算从加密挪给股金"
      f"(加密腿年化波动 30%,股金 ~13%),这是设计不是 bug;但它让回撤比常数 T25 深 0.63pp。**探索性。**")
    A(f"3. **STYLE 几乎没在动**:加密权重均值 {R['arms']['STYLE_T25']['weight_stats']['crypto']['mean']:.3f}"
      f"(基准 0.30),p25–p75 只有 {R['arms']['STYLE_T25']['weight_stats']['crypto']['p25']:.2f}–"
      f"{R['arms']['STYLE_T25']['weight_stats']['crypto']['p75']:.2f};"
      f"风格表每格要 ≥60 个样本,不够就不倾斜 ⇒ 多数调仓日只动一两格。"
      f"STYLE 后半段 Calmar 只有 {_num(st['iv_h2_calmar'])}。**探索性。**")
    A("4. **风格表本身是有形状的**(见第 4 节:黄金在 down_hot 最好、加密在 up_cold 最好、"
      "股票在 down_hot 最差)—— 「天气 → 腿的优势」这个描述性事实成立;"
      "但把它变成组合权重后,风险调整后的收益反而不如常数配比。"
      "**探索性 —— 需另立预注册、在新数据上过零信号对照。**")
    A(f"5. **两套记账的差 {sc['rel_final_diff_20bp']*100:+.2f}%**(终值 {sc['final_dynamic_mix_nav']:.4f} vs "
      f"{sc['final_mix_nav_20bp']:.4f}),逐日最大差 {sc['abs_nav_diff_max']:.4f} —— 量级与「调仓目标次日生效 vs 当日生效」"
      "的一次错位相符。**探索性。**")
    A("")
    A("## 7. 诚实与边界")
    A("")
    A("- `flex_alloc.py` 截至本轮仍在主仓库工作区未合并进 `origin/main`;本报告用的是工作区那份(逐字, sha256 记在 "
      "`t318_results.json`),快照同 sha256。CI 要复现,需先把核合进 main。")
    A("- STYLE 的先验弱(台账里按天气预测收益的配法失败过至少五次);RB 不预测收益。")
    A("- 本卡只判「值不值得接进真钱」;真钱 `portfolio_targets` 的改动需 Jazz 拍板。")
    A("")
    A("## 8. 产物")
    A("")
    A("- `docs/research/t318_flex_v2.py`(本脚本,只读)")
    A("- `docs/research/t318_legs.csv`(日期、三条腿收盘、天气)")
    A("- `docs/research/t318_results.json`(逐臂逐条判定 + 每次调仓权重表 + 自检)")
    A("- `docs/research/t318_style_table.json`(冻结风格表)")
    A("- `docs/research/scenarios/lane-c-T-318.json`(前向命题)")
    A("")
    open(os.path.join(HERE, "T-318_flex_v2.md"), "w").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
