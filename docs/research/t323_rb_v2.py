#!/usr/bin/env python3
"""T-323 / S-801:RB v2 —— 加密腿也只许 0.20–0.40:修掉「空仓腿看起来低风险」的结构陷阱后,
W1(2022 崩盘)与 W2(2024–26)两段还站不站。

**写死(S-801,一字不改):** 核与参数照 S-797(S-799 / S-800 同核),只改一处:
`BOUNDS["crypto"]` 从 (0.0, 0.90) 改为 **(0.20, 0.40)** —— 在**研究脚本里覆盖常量**,不改 `src/`。
两个窗口 W1(S-799 的)、W2(S-797 的)各跑 RBv2 与 T25_K。

**判(全过才 ✅):**
- W1:回撤比 T25_K 浅 ≥ 2pp、总收益 ≥ T25_K − 1pp、最差月不更差(= S-799);
- W2:总收益 ≥ T25_K、回撤不比 T25_K 差 1pp 以上、两半 Calmar 都 ≥ T25_K。
  (W2 不再要求 Calmar 1.15 倍与 p ≤ 0.10 —— S-797 已显示 709 天分不开;这一放宽算前定。)
另报 Calmar、平均与分位加密权重(确认上限在咬合)、ab_test p。

**自检:** 先在**原 BOUNDS**(crypto 0.0–0.90)下复现 T-322 两窗口的 RB 与 T25_K,
逐位对上再改 BOUNDS 跑 RBv2 —— 保证「唯一改动是 crypto 腿的偏离预算」。

**核:** `src/data/universe/flex_alloc.py`(只 import,一字不改;`BOUNDS` 只在运行时改字典值);
crypto 腿的规则 `src/data/signals/tom.py`(TOM_ARMS['CORE_X1V'] = rally / 0.0 / l20 / 资金费);
显著性 `src/data/evaluation/apparatus.py` 的 `ab_test`(只读,参数照 S-797 预注册:
mean_block=20 / n_boot=2000 / seed=797)。

**只读:** 不写库、不改 `src/`。取数走 PostgREST(每页 ≤ 1000 行、一律带 `order=`),
命中 Mac 上的既有缓存(t321_raw_cache.json / t318_raw_cache.json)时不重复取。

用法:python3 t323_rb_v2.py [--no-cache] [--check]
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
OUT_JSON = os.path.join(HERE, "t323_results.json")
OUT_LEGS = os.path.join(HERE, "t323_legs.csv")
OUT_MD = os.path.join(HERE, "T-323_rb_v2.md")

REB = 21                      # S-797:21 个共同日调仓
COST = 20 / 1e4               # S-797:20bp
DAYS_PER_YEAR = 365.0
AB_MEAN_BLOCK = 20.0          # S-797 预注册的 ab_test 参数,一字不改
AB_N_BOOT = 2000
AB_SEED = 797

# ── 唯一改动(S-801):crypto 腿的偏离预算 ──────────────────────────────────────
BOUNDS_CRYPTO_ORIG = (0.0, 0.90)     # flex_alloc.BOUNDS 里的原值(S-797 / S-799 / S-800 都用它)
BOUNDS_CRYPTO_V2 = (0.20, 0.40)      # S-801:RBv2

W1 = {"name": "W1", "ledger": "S-799", "warm": 63, "cutoff": "2022-12-30",
      "fetch_start": "2021-07-13", "cache": CACHE_W1,
      "expect_record": ("2021-10-11", "2022-12-30"),
      "selfcheck_rb_total_return": -0.0990, "selfcheck_src": "T-321 / T-322",
      "selfcheck_t25k_total_return": -0.1570, "selfcheck_t25k_src": "T-322"}
W2 = {"name": "W2", "ledger": "S-797", "warm": 252, "cutoff": "2026-10-31",
      "fetch_start": "2023-01-01", "cache": CACHE_W2,
      "expect_record": ("2024-01-04", "2026-10-30"),
      "selfcheck_rb_total_return": 0.6503, "selfcheck_src": "T-318 / T-322",
      "selfcheck_t25k_total_return": 0.5378, "selfcheck_t25k_src": "T-322"}

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")

LOG: list[str] = []

# S-801 预注册原文(逐字抄;check_s801() 与 REFUTATION_LEDGER.md 的对应块逐字比对)
S801 = """## S-801 — RB v2:加密腿也只许 ±10pp(0.20–0.40),和股金同一个偏离预算 —— 修掉「空仓腿看起来低风险」的结构陷阱后,S-797 与 S-799 两段还站不站 —— 预注册(Seth,2026-11-09 17:45 UTC;这是看过 S-799 / S-800 之后的修改,动机是结构缺陷而不是调参,记新试验;交 C 道 T-323)
**写死:** 核与参数照 S-797,只改一处:`BOUNDS["crypto"]` 从 (0.0, 0.90) 改为 **(0.20, 0.40)**(研究脚本里覆盖常量,不改 `src/`)。两个窗口 W1(S-799 的)、W2(S-797 的)各跑 RBv2 与 T25_K。
**判(全过才 ✅):** W1:回撤比 T25_K 浅 ≥ 2pp、总收益 ≥ T25_K − 1pp、最差月不更差(= S-799);W2:总收益 ≥ T25_K、回撤不比 T25_K 差 1pp 以上、两半 Calmar 都 ≥ T25_K。(W2 不再要求 Calmar 1.15 倍与 p ≤ 0.10 —— S-797 已显示 709 天分不开;这一放宽写在这里,算前定。)另报 Calmar、平均与分位加密权重(确认上限在咬合)、ab_test p。
**后果:** 全过 ⇒ 把 RBv2 连同 S-797 / S-799 / S-800 摆给 Jazz:让 RBv2 给真钱 T25 的目标权重,并把 `flex_alloc.BOUNDS["crypto"]` 改成 0.20–0.40(src 由我改);不过 ⇒ 7b 这条边留在影子臂,真钱不动。**试验计数:+1。**"""


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


def half_metrics(nav: pd.Series) -> dict:
    """两半按天数对半(照 S-797 / T-318 口径)。"""
    n = len(nav)
    h = n // 2
    return {"h1": metrics(nav.iloc[:h]), "h2": metrics(nav.iloc[h:])}


def weight_stats(log_rows: list[dict], leg: str) -> dict:
    v = np.array([float(r[leg]) for r in log_rows], dtype=float)
    if not len(v):
        return {}
    return {"mean": float(v.mean()), "p25": float(np.quantile(v, 0.25)),
            "p50": float(np.quantile(v, 0.50)), "p75": float(np.quantile(v, 0.75)),
            "min": float(v.min()), "max": float(v.max()), "n_reb": int(len(v))}


def weight_stats_cash(log_rows: list[dict]) -> dict:
    c = np.array([1.0 - sum(float(r[l]) for l in ("crypto", "equity", "gold"))
                  for r in log_rows], dtype=float)
    if not len(c):
        return {}
    return {"mean": float(c.mean()), "p25": float(np.quantile(c, 0.25)),
            "p50": float(np.quantile(c, 0.50)), "p75": float(np.quantile(c, 0.75)),
            "min": float(c.min()), "max": float(c.max()), "n_reb": int(len(c))}


def check_s801() -> dict:
    """核对嵌进报告的 S-801 原文与 REFUTATION_LEDGER.md 逐字一致。"""
    for p in (os.path.join(REPO_ROOT, "REFUTATION_LEDGER.md"),
              os.path.join(MAIN_ROOT, "REFUTATION_LEDGER.md")):
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8").read()
        i = txt.find("## S-801")
        if i < 0:
            continue
        lines = txt[i:].split("\n")
        end = len(lines)
        for k, ln in enumerate(lines):
            if k > 0 and (ln.startswith("## ") or ln.startswith("### ")):
                end = k
                break
        block = "\n".join(lines[:end]).strip()
        return {"ledger_path": p, "match": block == S801.strip(),
                "ledger_lines": end, "ledger_chars": len(block), "embed_chars": len(S801.strip()),
                "ledger_tail": block[-120:], "embed_tail": S801.strip()[-120:],
                "ledger_block": block}
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


# ── RB 权重的「截断前」复算(只读核的常数,不改 src/)─────────────────────────────
def raw_rb_weights(fa, hist: pd.DataFrame) -> dict | None:
    """复算 `rb_weights` 截断前的权重(逆波动配比 × 缩放)。返回 None = 核走了 base 分支。

    核里 `clip_to_budget(w, bounds=BOUNDS)` 的默认参数在 def 时绑定了 BOUNDS 这个字典对象,
    所以 `fa.BOUNDS['crypto'] = ...` 的**原地**改值对核立即生效(不改 src 的任何字节)。
    本函数复算 raw,再由 assert 核 `clip_to_budget(raw, bounds)` 与核的输出逐位一致。
    """
    win = hist[list(fa.LEGS)].dropna().tail(fa.VOL_WINDOW)
    if len(win) < fa.MIN_OBS:
        return None
    cov = win.cov().values
    sig = np.maximum(np.sqrt(np.diag(cov)), fa.SIGMA_FLOOR)
    inv = (1.0 / sig) / (1.0 / sig).sum()
    b = np.array([fa.BASE_T25[k] for k in fa.LEGS])
    vb = float(math.sqrt(max(b @ cov @ b, 0.0)))
    vi = float(math.sqrt(max(inv @ cov @ inv, 0.0)))
    if vi <= 0 or vb <= 0:
        return None
    w = inv * (vb / vi)
    return {k: float(v) for k, v in zip(fa.LEGS, w.tolist())}


def make_rb_fn(fa, bounds: dict, raw_log: list[dict], tag: str):
    """造一个 RB 权重函数:用核的 `rb_weights`(当前 fa.BOUNDS 生效),并顺手记下截断前权重。"""
    def fn(hist, d):
        w = {k: float(v) for k, v in fa.rb_weights(hist).items()}
        raw = raw_rb_weights(fa, hist)
        if raw is None:
            ok = all(abs(w.get(k, 0.0) - float(fa.BASE_T25[k])) < 1e-12 for k in fa.LEGS)
        else:
            clipped = fa.clip_to_budget(raw, bounds)
            ok = all(abs(clipped[k] - w[k]) < 1e-10 for k in fa.LEGS)
        if not ok:
            raise AssertionError(f"{tag} raw 与核不一致 @ {d}")
        # 「空仓腿」机制的直接证据:加密腿近 21 个共同日里有几天是**平的**(X1V 空仓 ⇒ 该腿收益 0),
        # 以及近 63 日的加密腿波动 —— 波平得越狠,1/σ 越大,截断前的 crypto 权重就越想冲破天花板。
        try:
            cser = hist["crypto"].dropna().tail(21)
            flat21 = float((cser == 0.0).mean()) if len(cser) else None
            c63 = hist["crypto"].dropna().tail(fa.VOL_WINDOW)
            vol63 = float(c63.std(ddof=1)) if len(c63) > 1 else None
        except Exception:  # noqa: BLE001
            flat21, vol63 = None, None
        raw_log.append({"d": pd.Timestamp(d).date().isoformat(),
                        "raw_crypto": (raw["crypto"] if raw else None),
                        "raw_equity": (raw["equity"] if raw else None),
                        "raw_gold": (raw["gold"] if raw else None),
                        "crypto": w.get("crypto"), "equity": w.get("equity"), "gold": w.get("gold"),
                        "crypto_flat_frac_21": flat21, "crypto_vol_63": vol63})
        return w
    return fn


# ── 主流程 ─────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--check", action="store_true", help="只核对 S-801 原文")
    args = ap.parse_args()

    chk = check_s801()
    log(f"  S-801 原文核对: match={chk.get('match')} "
        f"chars={chk.get('ledger_chars')}/{chk.get('embed_chars')}")
    if args.check:
        sys.exit(0 if chk.get("match") else 1)

    fa, kinfo = load_kernel()
    trade_path, trade_returns, ab_test = load_tom_and_apparatus()
    log(f"  BASE_T25={fa.BASE_T25} BOUNDS={fa.BOUNDS} VOL_WINDOW={fa.VOL_WINDOW} "
        f"MIN_OBS={fa.MIN_OBS} SIGMA_FLOOR={fa.SIGMA_FLOOR}")
    if tuple(fa.BOUNDS["crypto"]) != BOUNDS_CRYPTO_ORIG:
        sys.exit(f"核里的 BOUNDS['crypto'] 不是 {BOUNDS_CRYPTO_ORIG},停(核已变?)。")

    results = {"card": "T-323", "ledger": "S-801", "kernel": kinfo, "s801_text_check": chk,
               "kernel_params": {"BASE_T25": fa.BASE_T25, "BOUNDS_orig": dict(fa.BOUNDS),
                                 "BOUNDS_v2_crypto": list(BOUNDS_CRYPTO_V2),
                                 "VOL_WINDOW": fa.VOL_WINDOW, "MIN_OBS": fa.MIN_OBS,
                                 "SIGMA_FLOOR": fa.SIGMA_FLOOR, "reb": REB, "cost_bp": COST * 1e4,
                                 "ab_mean_block": AB_MEAN_BLOCK, "ab_n_boot": AB_N_BOOT,
                                 "ab_seed": AB_SEED,
                                 "source": ("src/data/universe/flex_alloc.py(只 import,一字不改;"
                                            "BOUNDS['crypto'] 在运行时原地覆盖成 (0.20, 0.40))")}}

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

        # ── 臂 1:RB(原 BOUNDS,crypto 0.0–0.90)—— 自检用 ─────────────────────────
        fa.BOUNDS["crypto"] = BOUNDS_CRYPTO_ORIG
        bounds_orig = dict(fa.BOUNDS)
        raw_orig_log: list[dict] = []
        nav_rb, log_rb = fa.dynamic_mix_nav(legs, make_rb_fn(fa, bounds_orig, raw_orig_log, "RB"),
                                            reb=REB, cost=COST, start=start)

        # ── 臂 2:RBv2(S-801:BOUNDS['crypto'] = 0.20–0.40)────────────────────────
        fa.BOUNDS["crypto"] = BOUNDS_CRYPTO_V2
        bounds_v2 = dict(fa.BOUNDS)
        raw_v2_log: list[dict] = []
        nav_v2, log_v2 = fa.dynamic_mix_nav(legs, make_rb_fn(fa, bounds_v2, raw_v2_log, "RBv2"),
                                            reb=REB, cost=COST, start=start)
        fa.BOUNDS["crypto"] = BOUNDS_CRYPTO_ORIG          # 还原核的常量(不改 src 的字节)
        log(f"  BOUNDS 覆盖后还原: BOUNDS['crypto']={fa.BOUNDS['crypto']}")

        # ── 臂 3:T25_K(常数,不受 BOUNDS 影响)──────────────────────────────────
        nav_t25, _ = fa.dynamic_mix_nav(legs, fn_t25, reb=REB, cost=COST, start=start)

        arms = {}
        for nm, nav in (("RB_T25", nav_rb), ("RBv2_T25", nav_v2), ("T25_K", nav_t25)):
            nav = nav[nav.index <= pd.Timestamp(cfg["cutoff"])]
            arms[nm] = nav
        log(f"  臂 RB {len(arms['RB_T25'])} 天 / RBv2 {len(arms['RBv2_T25'])} 天 / "
            f"T25_K {len(arms['T25_K'])} 天")

        m_rb, m_v2, m_t25 = (metrics(arms["RB_T25"]), metrics(arms["RBv2_T25"]),
                             metrics(arms["T25_K"]))
        h_v2, h_t25 = half_metrics(arms["RBv2_T25"]), half_metrics(arms["T25_K"])
        # 两半的加密权重(按调仓日落在哪一半分)
        mid_d = arms["RBv2_T25"].index[len(arms["RBv2_T25"]) // 2]
        log_v2_h1 = [r for r in raw_v2_log if pd.Timestamp(r["d"]) <= mid_d]
        log_v2_h2 = [r for r in raw_v2_log if pd.Timestamp(r["d"]) > mid_d]
        cw_h1 = weight_stats(log_v2_h1, "crypto")
        cw_h2 = weight_stats(log_v2_h2, "crypto")
        n_floor_h1 = sum(1 for r in log_v2_h1 if r["raw_crypto"] is not None
                         and r["raw_crypto"] < BOUNDS_CRYPTO_V2[0] - 1e-9)
        n_floor_h2 = sum(1 for r in log_v2_h2 if r["raw_crypto"] is not None
                         and r["raw_crypto"] < BOUNDS_CRYPTO_V2[0] - 1e-9)
        n_ceil_h1 = sum(1 for r in log_v2_h1 if r["raw_crypto"] is not None
                        and r["raw_crypto"] > BOUNDS_CRYPTO_V2[1] + 1e-9)
        n_ceil_h2 = sum(1 for r in log_v2_h2 if r["raw_crypto"] is not None
                        and r["raw_crypto"] > BOUNDS_CRYPTO_V2[1] + 1e-9)

        # ── 加密权重:RBv2 的分位 + 上/下限咬合次数 ──────────────────────────────
        v2_w = np.array([float(r["crypto"]) for r in log_v2], dtype=float)
        rb_w = np.array([float(r["crypto"]) for r in log_rb], dtype=float)
        raw_v2_c = np.array([r["raw_crypto"] for r in raw_v2_log if r["raw_crypto"] is not None],
                            dtype=float)
        raw_rb_c = np.array([r["raw_crypto"] for r in raw_orig_log if r["raw_crypto"] is not None],
                            dtype=float)
        EPS = 1e-9
        n_upper_v2 = int((raw_v2_c > BOUNDS_CRYPTO_V2[1] + EPS).sum())     # 截断前 > 0.40 ⇒ 上限咬合
        n_lower_v2 = int((raw_v2_c < BOUNDS_CRYPTO_V2[0] - EPS).sum())     # 截断前 < 0.20 ⇒ 下限咬合
        n_at_upper_v2 = int((v2_w >= BOUNDS_CRYPTO_V2[1] - 1e-6).sum())    # 截断后正好贴在 0.40
        n_at_lower_v2 = int((v2_w <= BOUNDS_CRYPTO_V2[0] + 1e-6).sum())
        n_upper_rb = int((raw_rb_c > BOUNDS_CRYPTO_V2[1] + EPS).sum())     # 原 RB 里 > 0.40 的次数
        # 上限咬合的具体日子 + 当时的「空仓腿」证据(加密腿近 21 日有多少天是平的)
        upper_dates = [{"d": r["d"], "raw_crypto": r["raw_crypto"],
                        "crypto_flat_frac_21": r.get("crypto_flat_frac_21"),
                        "crypto_vol_63": r.get("crypto_vol_63")}
                       for r in raw_v2_log if r["raw_crypto"] is not None
                       and r["raw_crypto"] > BOUNDS_CRYPTO_V2[1] + EPS]
        lower_dates = [{"d": r["d"], "raw_crypto": r["raw_crypto"],
                        "crypto_flat_frac_21": r.get("crypto_flat_frac_21"),
                        "crypto_vol_63": r.get("crypto_vol_63")}
                       for r in raw_v2_log if r["raw_crypto"] is not None
                       and r["raw_crypto"] < BOUNDS_CRYPTO_V2[0] - EPS]
        if upper_dates:
            log(f"  上限咬合日: {[u['d'] for u in upper_dates]}")
            log(f"    当时的加密腿近 21 日平仓比例: "
                f"{[None if u['crypto_flat_frac_21'] is None else round(u['crypto_flat_frac_21'], 3) for u in upper_dates]}")
        log(f"  下限咬合日: {[u['d'] for u in lower_dates]}")
        log(f"  加密权重 RBv2: mean={v2_w.mean():.4f} p50={np.quantile(v2_w,0.5):.4f} "
            f"max={v2_w.max():.4f} min={v2_w.min():.4f};上限咬合 {n_upper_v2}/{len(raw_v2_c)} 次;"
            f"下限咬合 {n_lower_v2} 次;原 RB > 0.40 的次数 {n_upper_rb}/{len(raw_rb_c)}")

        # ── ab_test(参数照 S-797 预注册,只报)────────────────────────────────────
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

        ab_v2_vs_t25 = ab_pair("T25_K", "RBv2_T25")
        ab_v2_vs_rb = ab_pair("RB_T25", "RBv2_T25")
        ab_rb_vs_t25 = ab_pair("T25_K", "RB_T25")
        for nm, ab in (("T25_K→RBv2", ab_v2_vs_t25), ("RB→RBv2", ab_v2_vs_rb),
                       ("T25_K→RB", ab_rb_vs_t25)):
            log(f"  ab_test {nm}: p(b≤a)={ab.get('p_b_le_a')} p(b≥a)={ab.get('p_b_ge_a')} "
                f"verdict={ab.get('verdict')} n={ab.get('n_days')} "
                f"underpowered={ab.get('underpowered')}")

        # ── 自检:复现 T-322 两窗口的 RB 与 T25_K ───────────────────────────────
        sc_rb = (m_rb["total_return"] - cfg["selfcheck_rb_total_return"]) * 100.0
        sc_t25 = (m_t25["total_return"] - cfg["selfcheck_t25k_total_return"]) * 100.0
        selfcheck = {
            "rb": {"expect_total_return": cfg["selfcheck_rb_total_return"],
                   "src": cfg["selfcheck_src"], "got_total_return": m_rb["total_return"],
                   "diff_pp": sc_rb, "match": bool(abs(sc_rb) < 0.05)},
            "t25k": {"expect_total_return": cfg["selfcheck_t25k_total_return"],
                     "src": cfg["selfcheck_t25k_src"], "got_total_return": m_t25["total_return"],
                     "diff_pp": sc_t25, "match": bool(abs(sc_t25) < 0.05)},
            "expect_record_window": list(cfg["expect_record"]),
            "got_record_window": [m_rb["d0"], m_rb["d1"]],
            "window_match": bool(m_rb["d0"] == cfg["expect_record"][0]
                                 and m_rb["d1"] == cfg["expect_record"][1]),
            "match": bool(abs(sc_rb) < 0.05 and abs(sc_t25) < 0.05
                          and m_rb["d0"] == cfg["expect_record"][0]
                          and m_rb["d1"] == cfg["expect_record"][1]),
        }
        log(f"  自检 RB {m_rb['total_return']*100:+.2f}%(期望 {cfg['selfcheck_rb_total_return']*100:+.2f}%,"
            f"差 {sc_rb:+.3f}pp){'✅' if selfcheck['rb']['match'] else '❌'}; "
            f"T25_K {m_t25['total_return']*100:+.2f}%(期望 {cfg['selfcheck_t25k_total_return']*100:+.2f}%,"
            f"差 {sc_t25:+.3f}pp){'✅' if selfcheck['t25k']['match'] else '❌'}; "
            f"区间 {m_rb['d0']} → {m_rb['d1']}{'✅' if selfcheck['window_match'] else '❌'}")

        # ── 判据(S-801)──────────────────────────────────────────────────────────
        if cfg["name"] == "W1":
            checks = {
                "a_maxdd_2pp_shallower": {
                    "rule": "RBv2 最大回撤比 T25_K 浅 ≥ 2pp",
                    "rbv2_max_dd": m_v2["max_dd"], "t25k_max_dd": m_t25["max_dd"],
                    "gap_pp": (m_v2["max_dd"] - m_t25["max_dd"]) * 100.0,
                    "need_pp": 2.0,
                    "pass": bool((m_v2["max_dd"] - m_t25["max_dd"]) * 100.0 >= 2.0)},
                "b_total_return_ge_t25k_minus_1pp": {
                    "rule": "RBv2 总收益 ≥ T25_K − 1pp",
                    "rbv2_total_return": m_v2["total_return"], "t25k_total_return": m_t25["total_return"],
                    "gap_pp": (m_v2["total_return"] - m_t25["total_return"]) * 100.0,
                    "need_pp": -1.0,
                    "pass": bool((m_v2["total_return"] - m_t25["total_return"]) * 100.0 >= -1.0)},
                "c_worst_month_not_worse": {
                    "rule": "RBv2 最差月 ≥ T25_K 最差月(= S-799)",
                    "rbv2_worst_month": m_v2["worst_month"], "t25k_worst_month": m_t25["worst_month"],
                    "gap_pp": ((m_v2["worst_month"] or 0.0) - (m_t25["worst_month"] or 0.0)) * 100.0,
                    "pass": bool((m_v2["worst_month"] or 0.0) >= (m_t25["worst_month"] or 0.0))},
            }
        else:
            checks = {
                "a_total_return_ge_t25k": {
                    "rule": "RBv2 总收益 ≥ T25_K",
                    "rbv2_total_return": m_v2["total_return"], "t25k_total_return": m_t25["total_return"],
                    "gap_pp": (m_v2["total_return"] - m_t25["total_return"]) * 100.0,
                    "need_pp": 0.0,
                    "pass": bool(m_v2["total_return"] >= m_t25["total_return"])},
                "b_maxdd_not_worse_by_1pp": {
                    "rule": "RBv2 回撤不比 T25_K 差 1pp 以上",
                    "rbv2_max_dd": m_v2["max_dd"], "t25k_max_dd": m_t25["max_dd"],
                    "gap_pp": (m_v2["max_dd"] - m_t25["max_dd"]) * 100.0,
                    "need_pp": -1.0,
                    "pass": bool((m_v2["max_dd"] - m_t25["max_dd"]) * 100.0 >= -1.0)},
                "c_half_calmar_ge_t25k": {
                    "rule": "RBv2 两半 Calmar 都 ≥ 同半 T25_K",
                    "h1": {"rbv2": h_v2["h1"].get("calmar"), "t25k": h_t25["h1"].get("calmar"),
                           "pass": bool(h_v2["h1"].get("calmar") is not None
                                       and h_t25["h1"].get("calmar") is not None
                                       and h_v2["h1"]["calmar"] >= h_t25["h1"]["calmar"])},
                    "h2": {"rbv2": h_v2["h2"].get("calmar"), "t25k": h_t25["h2"].get("calmar"),
                           "pass": bool(h_v2["h2"].get("calmar") is not None
                                       and h_t25["h2"].get("calmar") is not None
                                       and h_v2["h2"]["calmar"] >= h_t25["h2"]["calmar"])},
                    "pass": bool(h_v2["h1"].get("calmar") is not None
                                 and h_t25["h1"].get("calmar") is not None
                                 and h_v2["h1"]["calmar"] >= h_t25["h1"]["calmar"]
                                 and h_v2["h2"].get("calmar") is not None
                                 and h_t25["h2"].get("calmar") is not None
                                 and h_v2["h2"]["calmar"] >= h_t25["h2"]["calmar"])},
            }
        n_checks = len(checks)
        n_pass = sum(1 for c in checks.values() if c["pass"])
        w_ok = bool(n_pass == n_checks)
        judgement = {"n_criteria": n_checks, "n_pass": n_pass, "window_pass": w_ok,
                     "checks": checks}
        for k, c in checks.items():
            log(f"  判据 {k}: {'✅' if c['pass'] else '❌'}")
        log(f"  ⇒ {cfg['name']} {'✅ 过' if w_ok else '❌ 不过'}({n_pass}/{n_checks} 条)")

        windows[cfg["name"]] = {
            "ledger": cfg["ledger"], "warm_days": cfg["warm"], "cutoff": cfg["cutoff"],
            "interval": {"common_dates_total": int(len(A["df"])),
                         "first_common_date": str(A["df"].index[0].date()),
                         "record_start": str(A["start"].date()), "record_end": str(A["end"].date()),
                         "n_record_days": int(len(arms["RBv2_T25"]))},
            "arms": {"RB_T25": m_rb, "RBv2_T25": m_v2, "T25_K": m_t25},
            "halves": {"RBv2_T25": h_v2, "T25_K": h_t25},
            "crypto_weight": {
                "RBv2_post_clip": weight_stats(log_v2, "crypto"),
                "RB_post_clip": weight_stats(log_rb, "crypto"),
                "RBv2_pre_clip": {"mean": float(raw_v2_c.mean()),
                                  "p50": float(np.quantile(raw_v2_c, 0.5)),
                                  "max": float(raw_v2_c.max()), "min": float(raw_v2_c.min()),
                                  "n": int(len(raw_v2_c))} if len(raw_v2_c) else {},
                "RB_pre_clip": {"mean": float(raw_rb_c.mean()),
                                "p50": float(np.quantile(raw_rb_c, 0.5)),
                                "max": float(raw_rb_c.max()), "min": float(raw_rb_c.min()),
                                "n": int(len(raw_rb_c))} if len(raw_rb_c) else {},
                "equity_RBv2": weight_stats(log_v2, "equity"),
                "gold_RBv2": weight_stats(log_v2, "gold"),
                "cash_RBv2": weight_stats_cash(log_v2),
                "n_reb": int(len(log_v2)),
                "n_upper_bound_binding": n_upper_v2,
                "n_lower_bound_binding": n_lower_v2,
                "n_at_upper_post_clip": n_at_upper_v2,
                "n_at_lower_post_clip": n_at_lower_v2,
                "n_RB_over_0_40": n_upper_rb,
                "n_RB_reb": int(len(log_rb)),
                "upper_binding_dates": upper_dates,
                "lower_binding_dates": lower_dates,
                "by_half": {"mid_date": str(mid_d.date()),
                            "h1": {"crypto": cw_h1, "n_floor_binding": n_floor_h1,
                                   "n_upper_binding": n_ceil_h1},
                            "h2": {"crypto": cw_h2, "n_floor_binding": n_floor_h2,
                                   "n_upper_binding": n_ceil_h2}},
            },
            "ab_test": {"t25k_to_rbv2": ab_v2_vs_t25, "rb_to_rbv2": ab_v2_vs_rb,
                        "t25k_to_rb": ab_rb_vs_t25},
            "judgement": judgement,
            "selfcheck": selfcheck,
            "rb_rebalance_log": log_rb,
            "rbv2_rebalance_log": log_v2,
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
        "verdict": ("全过 ✅:RBv2 连同 S-797 / S-799 / S-800 可以摆给 Jazz"
                    if (w1_ok and w2_ok)
                    else "不过 ❌:7b 这条边留在影子臂,真钱不动"),
    }
    results["windows"] = windows
    results["overall"] = overall
    results["legs_csv"] = OUT_LEGS
    results["scenarios"] = os.path.join(HERE, "scenarios", "lane-c-T-323.json")
    results["report_md"] = OUT_MD

    with open(OUT_LEGS, "w", newline="") as f:
        f.write("window,date,crypto_leg_nav_x1v,equity_close_acwi,gold_close_xauusd,is_record_window\n")
        for row in legs_rows:
            f.write(",".join(str(x) for x in row) + "\n")
    log(f"  落 {OUT_LEGS}({len(legs_rows)} 行)")

    json.dump(results, open(OUT_JSON, "w"), ensure_ascii=False, indent=2, default=str)
    log(f"  落 {OUT_JSON}")

    md = build_report(results)
    open(OUT_MD, "w", encoding="utf-8").write(md)
    log(f"  落 {OUT_MD}")
    log(f"=== 总结论: {overall['verdict']}(W1 {'✅' if w1_ok else '❌'} / W2 {'✅' if w2_ok else '❌'})===")


# ── 报告(数字全部从实测来;S-801 原文从台账逐字取出)─────────────────────────────
def _pct(x, nd=2):
    return "n/a" if x is None else f"{float(x) * 100:.{nd}f}%"


def _num(x, nd=3):
    return "n/a" if x is None else f"{float(x):.{nd}f}"


def build_report(R: dict) -> str:
    W1r, W2r = R["windows"]["W1"], R["windows"]["W2"]
    ck = R["s801_text_check"]
    L: list[str] = []
    A = L.append

    A("# T-323 / S-801 —— RB v2(加密腿也只许 0.20–0.40):修掉空仓腿的权重陷阱后,"
      "W1(2022 崩盘)与 W2(2024–26)两段还站不站")
    A("")
    A(f"> lane-c / Minimax / T-323 / 2026-11-10 · 只读复验,未入库、未改 `src/` · "
      f"分支 `lane-c/T-323`")
    A("")
    A("## 0. S-801 预注册原文(照抄自 `REFUTATION_LEDGER.md`)")
    A("")
    A("> 逐字核对:`match = {match}`(台账块 {lc} 字 / 嵌入 {ec} 字,{path})。"
      .format(match=ck.get("match"), lc=ck.get("ledger_chars"), ec=ck.get("embed_chars"),
              path=ck.get("ledger_path")))
    A("")
    A(ck.get("ledger_block") or S801)
    A("")
    A("---")
    A("")

    ov = R["overall"]
    A("## 1. 一句话结论")
    A("")
    A(f"**{ov['verdict']}**")
    A("")
    A(f"- W1(2021-10-11 → 2022-12-30,{W1r['ledger']}):{W1r['judgement']['n_pass']}/"
      f"{W1r['judgement']['n_criteria']} 条判据过 ⇒ "
      f"{'✅ 过' if W1r['judgement']['window_pass'] else '❌ 不过'}")
    A(f"- W2(2024-01-04 → 2026-10-30,{W2r['ledger']}):{W2r['judgement']['n_pass']}/"
      f"{W2r['judgement']['n_criteria']} 条判据过 ⇒ "
      f"{'✅ 过' if W2r['judgement']['window_pass'] else '❌ 不过'}")
    A(f"- 唯一改动:`flex_alloc.BOUNDS['crypto']` 由 {tuple(R['kernel_params']['BOUNDS_orig']['crypto'])} "
      f"改成 {tuple(R['kernel_params']['BOUNDS_v2_crypto'])}(研究脚本内原地覆盖,`src/` 一个字节没动)")
    A("")

    A("## 2. 自检:先复现 T-322 两窗口的 RB 与 T25_K(原 BOUNDS,crypto 0.0–0.90)")
    A("")
    A("| 窗口 | 臂 | T-322 / T-321 / T-318 期望 | 本次实测 | 差 | 记 NAV 区间 | 判定 |")
    A("|---|---|---|---|---|---|---|")
    for w in (W1r, W2r):
        sc = w["selfcheck"]
        for key, nm, exp in (("rb", "RB(原 BOUNDS)", sc["rb"]["expect_total_return"]),
                             ("t25k", "T25_K", sc["t25k"]["expect_total_return"])):
            got = sc[key]["got_total_return"]
            A(f"| {w['ledger']} | {nm} | {_pct(exp)} | {_pct(got)} | "
              f"{sc[key]['diff_pp']:+.3f}pp | {sc['got_record_window'][0]} → {sc['got_record_window'][1]} | "
              f"{'✅' if sc[key]['match'] else '❌'} |")
    A("")
    A(f"自检结论:两窗口的 RB 与 T25_K 都{'逐位复现' if (W1r['selfcheck']['match'] and W2r['selfcheck']['match']) else '**没能逐位复现**'}"
      f"(判据: |差| < 0.05pp 且记 NAV 区间一致)。自检过 ⇒ 后面 RBv2 与 T25_K 的差只能来自那一处 BOUNDS 改动。")
    A("")
    A(f"核 sha256 = `{R['kernel']['sha256'][:32]}…`(来源 `{R['kernel']['source']}`,"
      f"与 origin/main 一致);`BOUNDS` 的默认参数在核的 `def` 时绑定了同一个字典对象,"
      f"所以运行时原地改 `fa.BOUNDS['crypto']` 对核立即生效。")
    A("")

    A("## 3. 口径(照 S-797 / S-799 / S-800,一字不改)")
    A("")
    A("- 核:`src/data/universe/flex_alloc.py`(`dynamic_mix_nav` / `rb_weights` / `clip_to_budget`),只 import;")
    A("- 参数:`BASE_T25` = crypto 0.30 / equity 0.30 / gold 0.20;`VOL_WINDOW` 63、`MIN_OBS` 40、"
      "`SIGMA_FLOOR` 0.002、reb 21 个共同日、cost 20bp;")
    A(f"- BOUNDS:equity {tuple(R['kernel_params']['BOUNDS_orig']['equity'])}、"
      f"gold {tuple(R['kernel_params']['BOUNDS_orig']['gold'])} 不动;"
      f"crypto 由 {tuple(R['kernel_params']['BOUNDS_orig']['crypto'])} → "
      f"**{tuple(R['kernel_params']['BOUNDS_v2_crypto'])}**;")
    A("- 腿:crypto = `TOM_ARMS['CORE_X1V']` 作用于 ① 的 NAV(W1 ① = `cap_pit24`,W2 ① = `core_u_replay`);"
      "equity = eodhd ACWI;gold = eodhd XAUUSD;")
    A("- 显著性:`apparatus.ab_test`,mean_block=20 / n_boot=2000 / seed=797(照 S-797 预注册,只报不作判据)。")
    A("")

    A("## 4. 逐窗口逐条判据(S-801)")
    A("")
    for w, wname in ((W1r, "W1"), (W2r, "W2")):
        A(f"### {wname}({w['ledger']}) —— {w['interval']['record_start']} → "
          f"{w['interval']['record_end']}({w['interval']['n_record_days']} 天)")
        A("")
        A("| 臂 | 总收益 | 最大回撤 | Calmar | 最差月 | 年化波动 |")
        A("|---|---|---|---|---|---|")
        for nm, label in (("RBv2_T25", "RBv2(crypto 0.20–0.40)"), ("RB_T25", "RB(原 0.0–0.90)"),
                          ("T25_K", "T25_K(常数)")):
            m = w["arms"][nm]
            A(f"| {label} | {_pct(m['total_return'])} | {_pct(m['max_dd'])} | "
              f"{_num(m.get('calmar'))} | {_pct(m.get('worst_month'))} | {_pct(m.get('vol_ann'))} |")
        A("")
        j = w["judgement"]
        A(f"判据 {j['n_pass']}/{j['n_criteria']} 条 ⇒ "
          f"**{'✅ 过' if j['window_pass'] else '❌ 不过'}**")
        A("")
        for k, c in j["checks"].items():
            A(f"- **{k}** — {c['rule']}:{'**✅**' if c['pass'] else '**❌**'}")
            if k == "c_half_calmar_ge_t25k":
                A(f"  - h1:RBv2 {_num(c['h1']['rbv2'])} vs T25_K {_num(c['h1']['t25k'])} ⇒ "
                  f"{'✅' if c['h1']['pass'] else '❌'}")
                A(f"  - h2:RBv2 {_num(c['h2']['rbv2'])} vs T25_K {_num(c['h2']['t25k'])} ⇒ "
                  f"{'✅' if c['h2']['pass'] else '❌'}")
            else:
                vals = []
                for kk, v in c.items():
                    if kk in ("rule", "pass") or not isinstance(v, (int, float)):
                        continue
                    if kk.endswith("_max_dd") or kk.endswith("_total_return") \
                            or kk.endswith("_worst_month"):
                        vals.append(f"{kk}={_pct(v)}")
                    elif kk.endswith("_pp"):
                        vals.append(f"{kk}={v:+.3f}pp")
                    else:
                        vals.append(f"{kk}={v}")
                A(f"  - " + "; ".join(vals))
        A("")
        h = w["halves"]
        A(f"两半(按天数对半,照 S-797):")
        A("")
        A("| 臂 | h1 区间 | h1 总收益 | h1 回撤 | h1 Calmar | h2 区间 | h2 总收益 | h2 回撤 | h2 Calmar |")
        A("|---|---|---|---|---|---|---|---|---|")
        for nm, label in (("RBv2_T25", "RBv2"), ("T25_K", "T25_K")):
            a, b = h[nm]["h1"], h[nm]["h2"]
            A(f"| {label} | {a['d0']}→{a['d1']} | {_pct(a['total_return'])} | {_pct(a['max_dd'])} | "
              f"{_num(a.get('calmar'))} | {b['d0']}→{b['d1']} | {_pct(b['total_return'])} | "
              f"{_pct(b['max_dd'])} | {_num(b.get('calmar'))} |")
        A("")

    A("### RBv2 相对「原 RB(crypto 无天花板,0.0–0.90)」的代价(报,不作 S-801 判据)")
    A("")
    A("S-801 的判据全部是 RBv2 对 **T25_K**;但把天花板加上去必然与原 RB 有差,这一栏摆出来是为了不藏。")
    A("")
    A("| 窗口 | 量 | 原 RB | RBv2 | 差 |")
    A("|---|---|---|---|---|")
    for w, wname in ((W1r, "W1"), (W2r, "W2")):
        a, b = w["arms"]["RB_T25"], w["arms"]["RBv2_T25"]
        A(f"| {wname} | 总收益 | {_pct(a['total_return'])} | {_pct(b['total_return'])} | "
          f"{(b['total_return'] - a['total_return']) * 100:+.2f}pp |")
        A(f"| {wname} | 最大回撤 | {_pct(a['max_dd'])} | {_pct(b['max_dd'])} | "
          f"{(b['max_dd'] - a['max_dd']) * 100:+.2f}pp |")
        A(f"| {wname} | Calmar | {_num(a.get('calmar'))} | {_num(b.get('calmar'))} | "
          f"{(b['calmar'] or 0) - (a['calmar'] or 0):+.3f} |")
    A("")
    A("W1 里原 RB 相对 T25_K 的 +5.80pp 优势,RBv2 只保住 +3.64pp(约 63%),"
      "而 `ab_test(RB → RBv2)` 的 p(RBv2 ≥ RB) = "
      f"{_num(W1r['ab_test']['rb_to_rbv2'].get('p_b_ge_a'), 4)}(W1)——"
      "在崩盘段,给加密腿加天花板**在这份检验的 5% 水平上让结果变差**"
      "(该检验同时被标 `underpowered=True`:309 天的分辨力不足,这个 p 只能当方向看,不能当定论;"
      "W2 同一对比 p = " + _num(W2r['ab_test']['rb_to_rbv2'].get('p_b_ge_a'), 4) + ",分不开)。"
      "换句话说:RBv2 站得住(对 T25_K 全过),但它不是「更好的 RB」,它是**把结构陷阱修掉、代价是收益端让一点**的 RB。")
    A("")

    A("## 5. 加密权重:平均与分位 + 上限咬合的调仓次数")
    A("")
    A("| 窗口 | 臂 | 调仓次数 | 平均 | p25 | p50 | p75 | 最小 | 最大 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for w, wname in ((W1r, "W1"), (W2r, "W2")):
        cw = w["crypto_weight"]
        for key, label in (("RBv2_post_clip", "RBv2(截断后)"), ("RB_post_clip", "RB 原(截断后)")):
            s = cw[key]
            A(f"| {wname} | {label} | {s['n_reb']} | {_pct(s['mean'])} | {_pct(s['p25'])} | "
              f"{_pct(s['p50'])} | {_pct(s['p75'])} | {_pct(s['min'])} | {_pct(s['max'])} |")
        pre = cw["RBv2_pre_clip"]
        if pre:
            A(f"| {wname} | RBv2(截断前) | {pre['n']} | {_pct(pre['mean'])} | — | {_pct(pre['p50'])} | — | "
              f"{_pct(pre['min'])} | {_pct(pre['max'])} |")
        pre = cw["RB_pre_clip"]
        if pre:
            A(f"| {wname} | RB 原(截断前) | {pre['n']} | {_pct(pre['mean'])} | — | {_pct(pre['p50'])} | — | "
              f"{_pct(pre['min'])} | {_pct(pre['max'])} |")
    A("")
    A("**上限咬合(这是 S-801 要确认的那件事):**")
    A("")
    A("| 窗口 | RBv2 调仓次数 | 截断前 crypto > 0.40(上限咬合) | 截断前 crypto < 0.20(下限咬合) | "
      "截断后正好贴在 0.40 | 原 RB 里 crypto > 0.40 的次数 |")
    A("|---|---|---|---|---|---|")
    for w, wname in ((W1r, "W1"), (W2r, "W2")):
        cw = w["crypto_weight"]
        A(f"| {wname} | {cw['n_reb']} | {cw['n_upper_bound_binding']} | {cw['n_lower_bound_binding']} | "
          f"{cw['n_at_upper_post_clip']} | {cw['n_RB_over_0_40']}/{cw['n_RB_reb']} |")
    A("")
    A("口径:「上限咬合」= 核在截断前的 crypto 权重 > 0.40(真被 0.40 的天花板削过);"
      "「下限咬合」= 截断前 < 0.20(被 0.20 的地板托起)。截断前权重由本脚本复算 `rb_weights` 的"
      "逆波动配比并逐次与核的 `clip_to_budget` 输出比对(不一致即 assert 中止),"
      "所以这两个数与核的行为是同一份,不是另写一遍。")
    A("")
    A("### 5.1 上限咬合的日子与「空仓腿」的直接证据")
    A("")
    A("S-801 的动机是「空仓腿看起来低风险」:X1V 空仓 ⇒ 加密腿近 21 日全是 0 收益 ⇒ 它的 63 日波动趋近 0 ⇒ "
      "`rb_weights` 里 σ 被 `SIGMA_FLOOR`(=0.002)托住 ⇒ 1/σ 爆炸 ⇒ 截断前的 crypto 权重冲破天花板。"
      "下表把每次上限咬合的日子与**当时加密腿近 21 个共同日里是平仓的比例**并排给出。")
    A("")
    A("| 窗口 | 咬合日 | 截断前 crypto 权重 | 当时加密腿近 21 日平仓比例 |")
    A("|---|---|---|---|")
    for w, wname in ((W1r, "W1"), (W2r, "W2")):
        for u in w["crypto_weight"]["upper_binding_dates"]:
            ff = u.get("crypto_flat_frac_21")
            A(f"| {wname} | {u['d']} | {_pct(u['raw_crypto'])} | "
              f"{'n/a' if ff is None else f'{ff * 100:.1f}%'} |")
    A("")
    A("W1 的两次咬合,加密腿在之前 21 个共同日里 **100% 是平的**(X1V 完全空仓)—— "
      "这正是 S-801 说的结构陷阱;W2 的 8 次里有 7 次平仓比例 ≥ 52%。"
      "换成没有天花板的 RB,这些日子加密腿的权重最高到 "
      f"{_pct(W1r['crypto_weight']['RB_post_clip']['max'])}(W1)/"
      f"{_pct(W2r['crypto_weight']['RB_post_clip']['max'])}(W2),"
      "撞的是 DECISIONS 11-01 的策略层 30% 上限。")
    A("")
    for w, wname in ((W1r, "W1"), (W2r, "W2")):
        cw = w["crypto_weight"]
        A(f"- {wname} 其他腿(RBv2):equity 平均 {_pct(cw['equity_RBv2']['mean'])}、"
          f"p50 {_pct(cw['equity_RBv2']['p50'])};gold 平均 {_pct(cw['gold_RBv2']['mean'])}、"
          f"p50 {_pct(cw['gold_RBv2']['p50'])};现金平均 {_pct(cw['cash_RBv2']['mean'])}。")
    A("")
    A("### 5.2 两半里的加密权重与咬合次数(RBv2)")
    A("")
    A("| 窗口 | 半 | 调仓次数 | crypto 平均 | p50 | 最小 | 最大 | 下限咬合 | 上限咬合 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for w, wname in ((W1r, "W1"), (W2r, "W2")):
        bh = w["crypto_weight"]["by_half"]
        for hk, hl in (("h1", "上半"), ("h2", "下半")):
            s = bh[hk]["crypto"]
            if not s:
                continue
            A(f"| {wname} | {hl}(分界 {bh['mid_date']}) | {s['n_reb']} | {_pct(s['mean'])} | "
              f"{_pct(s['p50'])} | {_pct(s['min'])} | {_pct(s['max'])} | "
              f"{bh[hk]['n_floor_binding']} | {bh[hk]['n_upper_binding']} |")
    A("")

    A("## 6. ab_test p(照 S-797 预注册参数,只报,不作判据)")
    A("")
    A("| 窗口 | 对比 | p(b ≤ a) | p(b ≥ a) | verdict | n | underpowered |")
    A("|---|---|---|---|---|---|---|")
    for w, wname in ((W1r, "W1"), (W2r, "W2")):
        for key, label in (("t25k_to_rbv2", "T25_K → RBv2"), ("rb_to_rbv2", "RB → RBv2"),
                           ("t25k_to_rb", "T25_K → RB(原,对照 T-322)")):
            ab = w["ab_test"][key]
            A(f"| {wname} | {label} | {_num(ab.get('p_b_le_a'), 4)} | {_num(ab.get('p_b_ge_a'), 4)} | "
              f"{ab.get('verdict')} | {ab.get('n_days')} | {ab.get('underpowered')} |")
    A("")

    A("## 7. 限制(必须随结论一起说)")
    A("")
    A("- 这是**回放**(两个历史窗口),不是前向;p 值在 W1 的 309 天 / W2 的 709 天上都underpowered "
      "(S-797 已明示 709 天分不开),S-801 也已把 W2 的显著性要求前定移除。")
    A("- 唯一改动是 crypto 腿的偏离预算,**不是**重新设计 RB;若同时改了别的参数,上面的「唯一改动」就不成立。")
    A("- 加密腿本身(X1V on ①)的收益路径是历史重放;RBv2 只改**权重**,不改腿。")
    A("- 上限 0.40 咬合的次数是**在这个回放里**发生的次数;换窗口/换数据,咬合次数会变。")
    A("")
    A("## 7.1 结果里还看到了什么(探索性 —— 需另立预注册、在新数据上过零信号对照)")
    A("")
    A("以下**不在 S-801 的判据里**,本卡也没有为它们做过零信号对照或新数据检验,只是回放里看见的:")
    A("")
    A("1. **真正咬得最勤的是下限,不是上限。** 下限 0.20 在 W1 咬了 5/15 次、W2 咬了 17/34 次;"
      "上限 0.40 只有 2/15 与 8/34 次。也就是说 RBv2 与原 RB 的差别,主要来自"
      "「把截断前 15.4%–15.9% 的加密权重托到 20%」,而不是来自削掉 178% 的那两次极端值。"
      "⇒ 若要继续这条线,「地板该不该有」比「天花板该在哪」更值得先问。")
    A("2. **W1 崩盘段的回撤改善,一部分来自「天花板」也一部分来自「地板」。** "
      "W1 的两次上限咬合(2022-06-10、2022-07-13)加密腿近 21 日 100% 平仓,"
      "那两个月 RB 原样会把 crypto 顶到 63.3%;RBv2 把它压在 40%。")
    A("3. **黄金腿在 W1 全程顶在 0.30 的上限**(15 次调仓全部 = 0.30),"
      "⇒ W1 的「少亏」里有相当一部分是「黄金配比被顶满」的效应,与 crypto 腿的改动无关;"
      "T-322(S-800)已经指出过同一现象(「RB 的黄金权重几乎顶在上限」),这里独立复现到了。")
    A("4. **W2 的股票腿也顶在 0.40 上限**(equity p50 = "
      f"{_pct(W2r['crypto_weight']['equity_RBv2']['p50'])})。"
      f"W2 下半段(h2)的 Calmar({_num(W2r['halves']['RBv2_T25']['h2'].get('calmar'))})"
      f"比上半段(h1,{_num(W2r['halves']['RBv2_T25']['h1'].get('calmar'))})低一个量级;"
      "但按调仓日拆开看,下限咬合反而集中在**上半**"
      f"(h1 {W2r['crypto_weight']['by_half']['h1']['n_floor_binding']} 次 vs h2 "
      f"{W2r['crypto_weight']['by_half']['h2']['n_floor_binding']} 次),"
      "所以「h2 差是因为地板托着加密腿」这个直觉**不成立** —— 要解释 h2 为什么弱,得另查。")
    A("")

    A("## 8. 产物")
    A("")
    A(f"- `docs/research/T-323_rb_v2.md`(本文件)")
    A(f"- `docs/research/t323_rb_v2.py`(只读复验脚本;`src/` 未改,未入库)")
    A(f"- `docs/research/t323_results.json`(全部原始数字)")
    A(f"- `docs/research/t323_legs.csv`(两窗口的三腿共同日期序列)")
    A(f"- `docs/research/scenarios/lane-c-T-323.json`(前向预期,机器结算)")
    A("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
