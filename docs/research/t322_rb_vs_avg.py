#!/usr/bin/env python3
"""T-322 / S-800:RB 对它自己的平均权重(常数)—— 好处是「择时」还是只是「换了配比」。

**写死(S-800,一字不改):** 两个窗口各算一次,核与参数不动。
- W1 = S-799 的窗口(2021-10-11 → 2022-12-30),① = `core_variants_daily` 的 `cap_pit24`。
- W2 = S-797 的窗口(2024-01-04 → 2026-10-30),① = `multiplier_daily` 的 `core_u_replay`。
- 对照臂 AVG_w = `dynamic_mix_nav` 的**常数**权重 = RB 在该窗口里各次调仓权重的算术平均
  (加密 / 股 / 金;现金为余数)。
- 判:两个窗口里 RB 的总收益都 ≥ AVG_w,且最大回撤都不比 AVG_w 差 ⇒ 时变部分有用(✅);
  任一窗口 RB 不如 AVG_w ⇒ 好处来自常数配比(❌)。

**核:** `src/data/universe/flex_alloc.py`(只 import,一字不改);
crypto 腿的规则 `src/data/signals/tom.py`(TOM_ARMS['CORE_X1V'] = rally / 0.0 / l20 / 资金费);
显著性 `src/data/evaluation/apparatus.py` 的 `ab_test`(只读,一手写,参数照 S-797 预注册:
mean_block=20 / n_boot=2000 / seed=797)。

**只读:** 不写库、不改 `src/`。取数走 PostgREST(每页 ≤ 1000 行、一律带 `order=`),
命中 Mac 上的既有缓存(t321_raw_cache.json / t318_raw_cache.json)时不重复取。

用法:python3 t322_rb_vs_avg.py [--no-cache] [--check]
"""
from __future__ import annotations

import argparse
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

CACHE_W1 = os.path.join(DATA_ROOT, "t321_raw_cache.json")
CACHE_W2 = os.path.join(DATA_ROOT, "t318_raw_cache.json")
OUT_JSON = os.path.join(HERE, "t322_results.json")
OUT_LEGS = os.path.join(HERE, "t322_legs.csv")

REB = 21                      # S-797:21 个共同日调仓
COST = 20 / 1e4               # S-797:20bp
DAYS_PER_YEAR = 365.0
AB_MEAN_BLOCK = 20.0          # S-797 预注册的 ab_test 参数,一字不改
AB_N_BOOT = 2000
AB_SEED = 797

W1 = {"name": "W1", "ledger": "S-799", "warm": 63, "cutoff": "2022-12-30",
      "fetch_start": "2021-07-13", "cache": CACHE_W1,
      "expect_record": ("2021-10-11", "2022-12-30"),
      "selfcheck_rb_total_return": -0.0990, "selfcheck_src": "T-321"}
W2 = {"name": "W2", "ledger": "S-797", "warm": 252, "cutoff": "2026-10-31",
      "fetch_start": "2023-01-01", "cache": CACHE_W2,
      "expect_record": ("2024-01-04", "2026-10-30"),
      "selfcheck_rb_total_return": 0.6503, "selfcheck_src": "T-318"}

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")

LOG: list[str] = []

S800 = """## S-800 — RB 的好处是「择时」还是只是「换了一个常数配比」:RB 对它自己的平均权重(常数)—— 预注册(Seth,2026-11-09 17:19 UTC;交 C 道 T-322)
**写死:** 两个窗口各算一次,核与参数不动:窗口 W1 = S-799 的(2021-10-11 → 2022-12-30)、W2 = S-797 的(2024-01-04 → 2026-10-30)。对照臂 AVG_w = `dynamic_mix_nav` 常数权重 = RB 在**该窗口**里各次调仓权重的算术平均(加密 / 股 / 金;现金为余数)—— 这是看过 RB 权重之后的对照,目的就是问「去掉时变部分还剩多少」。**判:** 两个窗口里 RB 的总收益都 ≥ AVG_w,且最大回撤都不比 AVG_w 差 ⇒ 时变部分有用(✅);任一窗口 RB 不如 AVG_w ⇒ 好处来自常数配比(❌),那么摆给 Jazz 的应是「换一个常数配比」,不是 RB。另报两窗口的 Calmar、最差月、`ab_test` p。**试验计数:+1。**"""


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
        if st not in (200, 206):
            raise RuntimeError(f"{table} 取数失败 {st}: {body[:200]}")
        cr = hdrs.get("content-range", "")
        if "/" in cr and total == "?":
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
                 dcol: str, vcol: str) -> pd.Series:
    rows, total = fetch_paged(table, select, filters, order_col)
    s = series_from(rows, dcol, vcol)
    log(f"  {table}: {len(s)} 行(server total={total})"
        + (f" {s.index[0].date()} → {s.index[-1].date()}" if len(s) else ""))
    return s


def to_series(obj) -> pd.Series:
    if isinstance(obj, pd.Series):
        return obj
    if not obj:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(k): float(v) for k, v in obj.items()}).sort_index()


def fetch_window(cfg: dict) -> dict:
    """只读取数(全部带 order=,每页 ≤ 1000 行)。"""
    out: dict = {}
    if cfg["name"] == "W1":
        rows, total = fetch_paged("core_variants_daily", "d,ret",
                                  ["arm=eq.cap_pit24", f"d=gte.{cfg['fetch_start']}",
                                   f"d=lte.{cfg['cutoff']}"], "d")
        log(f"  core_variants_daily.cap_pit24: {len(rows)} 行(server total={total})")
        out["core_pit24"] = rows
    else:
        rows, total = fetch_paged("multiplier_daily", "d,nav",
                                  ["arm=eq.core_u_replay", f"d=gte.{cfg['fetch_start']}",
                                   f"d=lte.{cfg['cutoff']}"], "d")
        log(f"  multiplier_daily.core_u_replay: {len(rows)} 行(server total={total})")
        out["core_u_replay"] = rows
    for sym, key in (("ACWI", "equity"), ("XAUUSD", "gold")):
        s = fetch_series("ohlcv_daily", "trade_date,close",
                         [f"symbol=eq.{sym}", "source=eq.eodhd",
                          f"trade_date=gte.{cfg['fetch_start']}", f"trade_date=lte.{cfg['cutoff']}"],
                         "trade_date", "trade_date", "close")
        out[key] = {str(k.date()): float(v) for k, v in s.items()}
    rows, total = fetch_paged("funding_history", "funding_time,funding_rate",
                               ["venue=eq.binance_perp", "symbol=eq.BTC",
                                f"funding_time=gte.{cfg['fetch_start']}",
                                f"funding_time=lte.{cfg['cutoff']}"], "funding_time")
    log(f"  funding_history BTC/binance_perp: {len(rows)} 行(server total={total})")
    out["funding"] = rows
    return out


# ── 核(flex_alloc / tom / apparatus):只 import,一字不改 ────────────────────────
def load_kernel() -> tuple[object, dict]:
    cands = []
    p = os.path.join(REPO_ROOT, "src", "data", "universe", "flex_alloc.py")
    if os.path.exists(p):
        cands.append(("repo_src", p))
    p2 = os.path.join(MAIN_ROOT, "src", "data", "universe", "flex_alloc.py")
    if os.path.exists(p2):
        cands.append(("main_worktree", p2))
    if not cands:
        sys.exit("找不到 flex_alloc 核。")
    tag, path = cands[0]
    spec = importlib.util.spec_from_file_location("flex_alloc_kernel", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    log(f"  flex_alloc 核: {tag} {path} sha256={sha[:16]}…")
    return mod, {"source": tag, "path": path, "sha256": sha}


def load_tom_and_apparatus():
    for root in (REPO_ROOT, MAIN_ROOT):
        if os.path.exists(os.path.join(root, "src", "data", "signals", "tom.py")):
            if root not in sys.path:
                sys.path.insert(0, root)
            from src.data.signals.tom import trade_path, trade_returns  # noqa: PLC0415
            from src.data.evaluation.apparatus import ab_test  # noqa: PLC0415
            log(f"  tom / apparatus: {root}")
            return trade_path, trade_returns, ab_test
    sys.exit("找不到 src/data/signals/tom.py 与 src/data/evaluation/apparatus.py。")


# ── 指标 ───────────────────────────────────────────────────────────────────────
def _monthly(nav: pd.Series) -> pd.Series:
    try:
        return nav.resample("ME").last().pct_change().dropna()
    except ValueError:
        return nav.resample("M").last().pct_change().dropna()


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
    return {
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


def weight_stats(log_rows: list[dict]) -> dict:
    out: dict = {}
    for leg in ("crypto", "equity", "gold"):
        v = np.array([float(r[leg]) for r in log_rows], dtype=float)
        if not len(v):
            continue
        out[leg] = {"mean": float(v.mean()), "p25": float(np.quantile(v, 0.25)),
                    "p50": float(np.quantile(v, 0.50)), "p75": float(np.quantile(v, 0.75)),
                    "min": float(v.min()), "max": float(v.max()), "n_reb": int(len(v))}
    if log_rows:
        c = np.array([1.0 - sum(float(r[l]) for l in ("crypto", "equity", "gold"))
                      for r in log_rows], dtype=float)
        out["cash"] = {"mean": float(c.mean()), "p25": float(np.quantile(c, 0.25)),
                       "p50": float(np.quantile(c, 0.50)), "p75": float(np.quantile(c, 0.75)),
                       "min": float(c.min()), "max": float(c.max()), "n_reb": int(len(c))}
    return out


def check_s800() -> dict:
    """核对嵌进报告的 S-800 原文与 REFUTATION_LEDGER.md 逐字一致。"""
    for p in (os.path.join(REPO_ROOT, "REFUTATION_LEDGER.md"),
              os.path.join(MAIN_ROOT, "REFUTATION_LEDGER.md")):
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8").read()
        i = txt.find("## S-800")
        if i < 0:
            continue
        lines = txt[i:].split("\n")
        end = len(lines)
        for k, ln in enumerate(lines):
            if k > 0 and (ln.startswith("## ") or ln.startswith("### ")):
                end = k
                break
        block = "\n".join(lines[:end]).strip()
        return {"ledger_path": p, "match": block == S800.strip(),
                "ledger_lines": end, "ledger_chars": len(block), "embed_chars": len(S800.strip()),
                "ledger_tail": block[-120:], "embed_tail": S800.strip()[-120:]}
    return {"ledger_path": None, "match": None}


# ── 装配一个窗口 ───────────────────────────────────────────────────────────────
def assemble(cfg: dict, raw: dict, trade_path, trade_returns) -> dict:
    """① 的 NAV + 三条腿 + 共同日期 + 记 NAV 区间。口径照 T-321(W1)/ T-318(W2)。"""
    if cfg["name"] == "W1":
        cv_rows = raw.get("core_pit24") or []
        if not cv_rows:
            sys.exit("①(cap_pit24)取不到,停。")
        ret_map = {pd.Timestamp(str(r["d"])[:10]): (float(r["ret"]) if r.get("ret") is not None else None)
                   for r in cv_rows}
        d0, d1 = min(ret_map), max(ret_map)
        full_idx = pd.date_range(d0, d1, freq="D")
        raw_rets = pd.Series({d: ret_map.get(d) for d in full_idx}, dtype=float)
        n_null = int(raw_rets.isna().sum())
        rets1 = raw_rets.fillna(0.0)
        core = (1.0 + rets1).cumprod()
        log(f"  ① cap_pit24: 表 {len(cv_rows)} 行 {d0.date()} → {d1.date()};"
            f"日历补齐 {len(full_idx)} 天(其中无 ret {n_null} 天按 0 收益)")
    else:
        rows = raw.get("core_u_replay") or []
        if not rows:
            sys.exit("①(core_u_replay)取不到,停。")
        core = series_from(rows, "d", "nav")
        n_null = 0
        log(f"  ① core_u_replay: {len(core)} 行 "
            f"{core.index[0].date() if len(core) else '-'} → {core.index[-1].date() if len(core) else '-'}")

    equity = to_series(raw.get("equity"))
    gold = to_series(raw.get("gold"))

    frows = raw.get("funding") or []
    fund = pd.Series(dtype=float)
    if frows:
        df = pd.DataFrame(frows)
        df["d"] = pd.to_datetime(df["funding_time"].astype(str).str[:10])
        fund = df.groupby("d")["funding_rate"].sum().astype(float) * 365.0
        log(f"  资金费 BTC: {len(fund)} 天 {fund.index[0].date()} → {fund.index[-1].date()}")

    g = trade_path(core, "rally", 0.0, "l20", True)
    r = trade_returns(core, g, fund if len(fund) else None)
    crypto_nav = pd.concat([pd.Series([1.0], index=[core.index[0]]), (1.0 + r).cumprod()]).sort_index()
    log(f"  crypto 腿(X1V on ①): {len(crypto_nav)} 行 "
        f"{crypto_nav.index[0].date()} → {crypto_nav.index[-1].date()}")

    legs = {"crypto": crypto_nav, "equity": equity, "gold": gold}
    df = pd.concat(legs, axis=1).dropna().sort_index()
    log(f"  三腿共同日期: {len(df)} 天 {df.index[0].date()} → {df.index[-1].date()}")
    df = df[df.index <= pd.Timestamp(cfg["cutoff"])]
    if len(df) <= cfg["warm"] + 2:
        sys.exit(f"{cfg['name']} 共同日期只有 {len(df)} 天,不够 {cfg['warm']} 天历史 + 判定。")
    start = df.index[cfg["warm"]]
    log(f"  记 NAV 区间: {start.date()} → {df.index[-1].date()}(前 {cfg['warm']} 个共同日只作历史)")
    return {"legs": legs, "df": df, "start": start, "end": df.index[-1],
            "core": core, "crypto_nav": crypto_nav, "g": g, "n_null": n_null,
            "equity": equity, "gold": gold, "fund_days": int(len(fund))}


# ── 主流程 ─────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--check", action="store_true", help="只核对 S-800 原文")
    args = ap.parse_args()

    chk = check_s800()
    log(f"  S-800 原文核对: {json.dumps(chk, ensure_ascii=False)}")
    if args.check:
        sys.exit(0 if chk.get("match") else 1)

    fa, kinfo = load_kernel()
    trade_path, trade_returns, ab_test = load_tom_and_apparatus()
    log(f"  BASE_T25={fa.BASE_T25} BOUNDS={fa.BOUNDS} VOL_WINDOW={fa.VOL_WINDOW} MIN_OBS={fa.MIN_OBS}")

    results = {"card": "T-322", "ledger": "S-800", "kernel": kinfo, "s800_text_check": chk,
               "kernel_params": {"BASE_T25": fa.BASE_T25, "BOUNDS": fa.BOUNDS,
                                 "VOL_WINDOW": fa.VOL_WINDOW, "MIN_OBS": fa.MIN_OBS,
                                 "SIGMA_FLOOR": fa.SIGMA_FLOOR, "reb": REB, "cost_bp": COST * 1e4,
                                 "ab_mean_block": AB_MEAN_BLOCK, "ab_n_boot": AB_N_BOOT, "ab_seed": AB_SEED,
                                 "source": "src/data/universe/flex_alloc.py(只 import,一字不改)"}}

    windows = {}
    legs_rows = []
    for cfg in (W1, W2):
        log(f"=== {cfg['name']}({cfg['ledger']})===")
        raw = None
        if os.path.exists(cfg["cache"]) and not args.no_cache:
            try:
                raw = json.load(open(cfg["cache"]))
                log(f"  用缓存 {cfg['cache']}")
            except Exception:  # noqa: BLE001
                raw = None
        if raw is None:
            if not URL or not KEY:
                sys.exit("缓存不在且环境里没有 SUPABASE_URL / SUPABASE_KEY,停。")
            raw = fetch_window(cfg)
            try:
                json.dump(raw, open(cfg["cache"], "w"))
                log(f"  缓存写到 {cfg['cache']}")
            except Exception as e:  # noqa: BLE001
                log(f"  缓存写不了(不影响): {e}")

        A = assemble(cfg, raw, trade_path, trade_returns)
        legs = A["legs"]
        start = A["start"]

        def fn_t25(hist, d):
            return fa.BASE_T25

        def fn_rb(hist, d):
            return fa.rb_weights(hist)

        nav_rb, log_rb = fa.dynamic_mix_nav(legs, fn_rb, reb=REB, cost=COST, start=start)
        # ── AVG_w = RB 在该窗口里各次调仓权重的算术平均(现金为余数)─────────────
        avg_w = {leg: float(np.mean([float(r[leg]) for r in log_rb])) for leg in ("crypto", "equity", "gold")}
        avg_w = {k: round(v, 6) for k, v in avg_w.items()}
        cash_avg = round(1.0 - sum(avg_w.values()), 6)
        log(f"  AVG_w(常数权重)= {avg_w} 现金 {cash_avg:.4f}(RB 调仓 {len(log_rb)} 次的算术平均)")

        def fn_avg(hist, d):
            return dict(avg_w)

        nav_avg, log_avg = fa.dynamic_mix_nav(legs, fn_avg, reb=REB, cost=COST, start=start)
        nav_t25, log_t25 = fa.dynamic_mix_nav(legs, fn_t25, reb=REB, cost=COST, start=start)

        arms = {}
        for nm, nav in (("RB_T25", nav_rb), ("AVG_w", nav_avg), ("T25_K", nav_t25)):
            nav = nav[nav.index <= pd.Timestamp(cfg["cutoff"])]
            arms[nm] = nav
            log(f"  臂 {nm}: {len(nav)} 天 {nav.index[0].date()} → {nav.index[-1].date()} "
                f"终值 {float(nav.iloc[-1]):.6f} 调仓 {len(nav) and len(log_rb)} 次")

        m_rb, m_avg, m_t25 = (metrics(arms["RB_T25"]), metrics(arms["AVG_w"]),
                              metrics(arms["T25_K"]))

        # ── ab_test:三对(参数照 S-797 预注册,只报)────────────────────────────
        def ab_pair(a_name: str, b_name: str) -> dict:
            ra = arms[a_name].pct_change().dropna()
            rb_ = arms[b_name].pct_change().dropna()
            idx = ra.index.intersection(rb_.index)
            out = ab_test(ra.reindex(idx).values, rb_.reindex(idx).values,
                          mean_block=AB_MEAN_BLOCK, n_boot=AB_N_BOOT, seed=AB_SEED)
            out["a"] = a_name
            out["b"] = b_name
            out["note"] = ("mean_block=20 / n_boot=2000 / seed=797(照 S-797 预注册,一字不改);"
                           f"a={a_name}、b={b_name};p_b_le_a = P({b_name} ≤ {a_name})、"
                           f"p_b_ge_a = P({b_name} ≥ {a_name})。只报,不作判据。")
            return out

        ab_rb_vs_avg = ab_pair("AVG_w", "RB_T25")
        ab_rb_vs_t25 = ab_pair("T25_K", "RB_T25")
        ab_avg_vs_t25 = ab_pair("T25_K", "AVG_w")
        for nm, ab in (("AVG_w→RB", ab_rb_vs_avg), ("T25_K→RB", ab_rb_vs_t25),
                       ("T25_K→AVG_w", ab_avg_vs_t25)):
            log(f"  ab_test {nm}: p(b≤a)={ab.get('p_b_le_a')} p(b≥a)={ab.get('p_b_ge_a')} "
                f"verdict={ab.get('verdict')} n={ab.get('n_days')} "
                f"underpowered={ab.get('underpowered')}")

        # ── 判据(S-800)────────────────────────────────────────────────────────
        ret_ok = bool(m_rb["total_return"] >= m_avg["total_return"])
        dd_ok = bool(m_rb["max_dd"] >= m_avg["max_dd"])       # 浅 = 亏损更小 = 数值更大
        w_ok = bool(ret_ok and dd_ok)
        judgement = {
            "rule": ("两个窗口里 RB 的总收益都 ≥ AVG_w 且最大回撤都不比 AVG_w 差 ⇒ 时变部分有用(✅);"
                     "任一窗口 RB 不如 AVG_w ⇒ 好处来自常数配比(❌)"),
            "rb_total_return": m_rb["total_return"], "avg_w_total_return": m_avg["total_return"],
            "ret_gap_pp": (m_rb["total_return"] - m_avg["total_return"]) * 100.0,
            "ret_ok": ret_ok,
            "rb_max_dd": m_rb["max_dd"], "avg_w_max_dd": m_avg["max_dd"],
            "dd_gap_pp": (m_rb["max_dd"] - m_avg["max_dd"]) * 100.0,
            "dd_ok": dd_ok,
            "window_pass": w_ok,
        }
        log(f"  判据: 总收益 {m_rb['total_return']*100:.2f}% vs AVG_w {m_avg['total_return']*100:.2f}%"
            f"(差 {judgement['ret_gap_pp']:+.2f}pp) ⇒ {'✅' if ret_ok else '❌'}; "
            f"最大回撤 {m_rb['max_dd']*100:.2f}% vs {m_avg['max_dd']*100:.2f}%"
            f"(差 {judgement['dd_gap_pp']:+.2f}pp) ⇒ {'✅' if dd_ok else '❌'}")
        log(f"  ⇒ {cfg['name']} {'✅ 过' if w_ok else '❌ 不过'}(时变部分{'有用' if w_ok else '不占优'})")

        # ── 自检:复现 T-321(W1)/ T-318(W2)的 RB 总收益 ────────────────────────
        sc = cfg["selfcheck_rb_total_return"]
        diff_pp = (m_rb["total_return"] - sc) * 100.0
        selfcheck = {"expect_rb_total_return": sc, "src": cfg["selfcheck_src"],
                     "got_rb_total_return": m_rb["total_return"], "diff_pp": diff_pp,
                     "match": bool(abs(diff_pp) < 0.05),
                     "expect_record_window": list(cfg["expect_record"]),
                     "got_record_window": [m_rb["d0"], m_rb["d1"]],
                     "window_match": bool(m_rb["d0"] == cfg["expect_record"][0]
                                          and m_rb["d1"] == cfg["expect_record"][1])}
        log(f"  自检 {cfg['selfcheck_src']}: RB {m_rb['total_return']*100:+.2f}% vs 期望 "
            f"{sc*100:+.2f}%(差 {diff_pp:+.3f}pp)⇒ {'✅' if selfcheck['match'] else '❌'};"
            f"记 NAV 区间 {m_rb['d0']} → {m_rb['d1']} ⇒ "
            f"{'✅' if selfcheck['window_match'] else '❌'}")

        windows[cfg["name"]] = {
            "ledger": cfg["ledger"], "warm_days": cfg["warm"], "cutoff": cfg["cutoff"],
            "interval": {"common_dates_total": int(len(A["df"])),
                         "first_common_date": str(A["df"].index[0].date()),
                         "record_start": str(A["start"].date()), "record_end": str(A["end"].date()),
                         "n_record_days": int(len(arms["RB_T25"]))},
            "avg_w_constant_weights": avg_w, "avg_w_cash": cash_avg,
            "avg_w_n_weights_averaged": int(len(log_rb)),
            "rb_rebalance_log": log_rb,
            "rb_weight_stats": weight_stats(log_rb),
            "arms": {"RB_T25": m_rb, "AVG_w": m_avg, "T25_K": m_t25},
            "ab_test": {"avg_w_to_rb": ab_rb_vs_avg, "t25k_to_rb": ab_rb_vs_t25,
                        "t25k_to_avg_w": ab_avg_vs_t25},
            "judgement": judgement,
            "selfcheck": selfcheck,
        }
        for d in A["df"].index:
            legs_rows.append([cfg["name"], str(d.date()),
                              float(legs["crypto"].get(d, float("nan"))),
                              float(legs["equity"].get(d, float("nan"))),
                              float(legs["gold"].get(d, float("nan"))),
                              "1" if d >= A["start"] else "0"])

    # ── 总结论 ─────────────────────────────────────────────────────────────────
    w1_ok = windows["W1"]["judgement"]["window_pass"]
    w2_ok = windows["W2"]["judgement"]["window_pass"]
    overall = {
        "W1_pass": w1_ok, "W2_pass": w2_ok, "all_pass": bool(w1_ok and w2_ok),
        "verdict": ("时变部分有用(✅):摆给 Jazz 的仍是 RB" if (w1_ok and w2_ok)
                    else "好处来自常数配比(❌):摆给 Jazz 的应是「换一个常数配比」,不是 RB"),
    }
    results["windows"] = windows
    results["overall"] = overall
    results["legs_csv"] = OUT_LEGS
    results["scenarios"] = os.path.join(HERE, "scenarios", "lane-c-T-322.json")

    with open(OUT_LEGS, "w", newline="") as f:
        f.write("window,date,crypto_leg_nav_x1v,equity_close_acwi,gold_close_xauusd,is_record_window\n")
        for row in legs_rows:
            f.write(",".join(str(x) for x in row) + "\n")
    log(f"  落 {OUT_LEGS}({len(legs_rows)} 行)")

    json.dump(results, open(OUT_JSON, "w"), ensure_ascii=False, indent=2, default=str)
    log(f"  落 {OUT_JSON}")
    log(f"=== 总结论: {overall['verdict']}(W1 {'✅' if w1_ok else '❌'} / W2 {'✅' if w2_ok else '❌'})===")


if __name__ == "__main__":
    main()
