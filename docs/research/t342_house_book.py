#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-342(S-815):整合账本 —— 一个账户、一个内核、一个窗口(2021-10-11 → 2026-10-30),
梯子 L0–L4 量每个开关(R-v2 / RBv2 / 现金计息 / 每票风险 1%)在账户口径上值多少。

**装配方式照 T-321(t321_rb_holdout.py)与 T-323(t323_rb_v2.py);核一字不改**
(`src/data/universe/flex_alloc.py` 的 `dynamic_mix_nav` / `rb_weights` / `BASE_T25` / `BOUNDS`,
reb = 21、cost = 20bp),只换窗口与开关:

- 窗口:共同日从 **2021-07-13**(① = cap_pit24 的起点,同 S-799)起,前 **63** 个共同日只作历史,
  记 NAV 从 **2021-10-11** 到 **2026-10-30**(含 2022)。
- 腿:crypto = `tom` 核(`TOM_ARMS['CORE_X1V']` = ('CORE','rally',0.0,'l20',True))作用于 ① 的 NAV;
  equity = `ohlcv_daily` eodhd `ACWI`;gold = eodhd `XAUUSD`。
- 现金利率:`feature_matrix_daily` 的 `f->>'stable_lend_apy_7d'` ÷ 100 ÷ 365(逐日历日;2023-02-10 之前没有 ⇒ 记 0)。
- R-v2 叠加:`docs/research/t251_gross_cap.py` 的 `simulate`(票源 t197 `tickets.A`、cap_n 14、gross_cap 0.40)
  净值曲线的逐日收益,作 `overlay_ret`;f = 0.5%(L1–L3)与 1.0%(L4)。

只读、不入库、不改 `src/`。长计算 nohup 后台跑。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MAIN_ROOT = "/Users/sbb/Projects/looloomi-ai"
DATA_ROOT = "/Volumes/CometCloudAI/cometcloud-local"
CACHE = os.path.join(DATA_ROOT, "t342_raw_cache.json")
KERNEL_NEW = os.path.join(DATA_ROOT, "t342_kernel_s815.py")     # 带 cash_ret / overlay_ret 的核快照
KERNEL_OLD = os.path.join(DATA_ROOT, "t342_kernel_main.py")      # origin/main 的核快照(自检 ③)

WIN_START = "2021-07-13"     # ① = cap_pit24 的共同日起点(S-799 同一起点)
WIN_END = "2026-10-30"       # 记 NAV 到这天
FETCH_START = "2021-07-01"
WARM_DAYS = 63               # 前 63 个共同日只作历史(不记 NAV)
REB = 21
COST = 20 / 1e4
DAYS_PER_YEAR = 365.0
S799_END = "2022-12-30"      # S-799 窗口终点(自检 ①)
AB_MEAN_BLOCK = 20.0
AB_N_BOOT = 2000
AB_SEED = 342

# R-v2 引擎口径(照 T-310 / T-251,一字不改)
RV2_CAP_N = 14
RV2_GROSS_CAP = 0.40
RV2_EQ0 = 630.0
RV2_F_BASE = 0.005           # L1–L3:每票风险 0.5%
RV2_F_HIGH = 0.010           # L4:每票风险 1.0%(S-638 的 f★)

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY —— 不读 .env,退出。")

# ── S-815 原文(逐字;运行时与 REFUTATION_LEDGER.md 核对)────────────────────────────
S815 = """## S-815 — 整合账本:把**已经过了检验、真钱能做**的几块放进同一个账户、同一个记账内核、同一个窗口,量每一个开关在账户口径上值多少 —— 登记(Seth,2026-11-11 13:39 UTC;Jazz 11-11「put them up together and tackle down some hard work, so that we can actually make money from now on」;交 C 道 T-342 算、B 道 T-343 盲复算)
**为什么。** 这两周 30 多条检验的账:**择时 / 预测类全部不过**(态近邻 S-745 / S-793、周期空间 S-814、阈值 S-811–813、做空 S-736 / 808 / 809 / 810、② 的 P 与 M52 S-802 / 803 / 804);**站住的是不预测的那几块** —— RBv2 分配(S-801)、R-v2 单票(S-627 / S-788)、硬规则(S-751 / S-753)、借贷这把尺(S-749)。它们各自在各自的窗口里量过,**从没在一个账户里合起来量**;而真钱账户 11-10 有 54% 是收益记 0 的 USDC(结构性现金 24% + X1V 空仓的 30%)。挣钱的下一步不是第 31 个信号,是把过了的拼起来、把漏的堵上。
**写死(一个窗口、一个内核):** 内核 `flex_alloc.dynamic_mix_nav`(reb 21、cost 20bp;11-11 起带 `cash_ret` / `overlay_ret`)。窗口 2021-10-11 → 2026-10-30(含 2022),前 63 个共同日作历史(同 S-799)。腿:加密 = `TOM_ARMS['CORE_X1V']` 作用于 ① = `cap_pit24`(整个窗口同一条 ①);股 = eodhd ACWI;金 = eodhd XAUUSD。**现金利率** = `feature_matrix_daily` 的 `stable_lend_apy_7d` ÷ 100 ÷ 365(逐日历日;2023-02-10 之前没有 ⇒ 记 0,写明)。**R-v2 叠加** = `docs/research/t251_gross_cap.py` 的 `simulate`(票源 t197 tickets.A、cap_n 14、gross_cap 0.40)净值曲线的逐日收益,作 `overlay_ret`(永续只占保证金,盈亏直接进账户)。
**梯子(每一级只多开一个开关):** L0 = 常数 T25(30 / 30 / 20)、现金 0、无叠加;L1 = L0 + R-v2(f 0.5%)= **11-10 之前的真钱基线**;L2 = L1 换 RBv2 权重 = **11-30 起的真钱**;L3 = L2 + 现金计息;L4 = L3 把 R-v2 的 f 提到 1.0%(S-638 的 f★)。另报:L3H = L3 但加密腿直接持有 ①(不用 X1V)—— β 捕获的代价与回报;① 自己;各级之间的差(每个开关值多少 pp / 年、多少回撤)。每臂:总收益、CAGR、波动、最大回撤、Calmar、最差月、**逐年收益表(2022 … 2026)**。
**判(只判两个要提给 Jazz 的配置):** **L3**:(i) 全窗口最大回撤不深于 **−25%**(Jazz 10-18 选的档);(ii) CAGR ≥ L1;(iii) 逐年收益都 ≥ L1 同年 − 1pp。**L4**:同 (i)。过 ⇒ 提给 Jazz:L3 ⇒ 给真钱建现金收益腿(场所按 DECISIONS 10-05 的现金等价物,由他选);L4 ⇒ 每票风险 0.5% → 1%(他 11-05 的规矩是满一个闸门周期再升,由他定)。不过 ⇒ 写清是哪个开关把哪一年 / 回撤弄坏的。
**诚实。** 这是回放:X1V 的执行拖累 T-146 量过(≈ −9.5pp / 年,基准格),不在这里;R-v2 叠加与腿之间的保证金占用按一阶近似(叠加收益直接相加);现金利率是 DeFi 借贷的 7 日均,真钱能拿到的取决于场所。梯子的顺序是按「已经决定的 → 还没决定的」排的,不是按效果挑的。**试验计数:不计(已过检验的部件的记账合成)。** 前向:整合臂 `flex_x1v:RB_T25_Y`(RBv2 + 现金计息)11-11 起记。"""

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
                 dcol: str, vcol: str) -> tuple[pd.Series, str]:
    rows, total = fetch_paged(table, select, filters, order_col)
    s = series_from(rows, dcol, vcol)
    log(f"  {table} {filters}: {len(s)} 行(server total={total})"
        + (f" {s.index[0].date()} → {s.index[-1].date()}" if len(s) else ""))
    return s, total


def to_series(obj) -> pd.Series:
    if isinstance(obj, pd.Series):
        return obj
    if not obj:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(k): float(v) for k, v in obj.items()}).sort_index()


def fetch_all() -> dict:
    """只读取数(全部带 order=,每页 ≤ 1000 行)。"""
    out: dict = {}
    # ① = core_variants_daily 的 cap_pit24 单臂(S-799 的同一条)
    rows, total = fetch_paged("core_variants_daily", "d,ret",
                              ["arm=eq.cap_pit24", f"d=gte.{WIN_START}", f"d=lte.{WIN_END}"], "d")
    log(f"  core_variants_daily.cap_pit24: {len(rows)} 行(server total={total})")
    out["core_pit24"] = rows
    # 表里 2021-07-13 之前还有没有行?(有也不取:共同日起点写死 2021-07-13)
    pre, _ = fetch_paged("core_variants_daily", "d,ret",
                         ["arm=eq.cap_pit24", f"d=gte.{FETCH_START}", f"d=lt.{WIN_START}"], "d")
    log(f"  core_variants_daily.cap_pit24 在 {WIN_START} 之前: {len(pre)} 行(不取)")
    out["core_pre"] = pre
    # 腿:ACWI / XAUUSD(eodhd)
    for sym, key in (("ACWI", "equity"), ("XAUUSD", "gold")):
        s, total = fetch_series("ohlcv_daily", "trade_date,close",
                                [f"symbol=eq.{sym}", "source=eq.eodhd",
                                 f"trade_date=gte.{FETCH_START}", f"trade_date=lte.{WIN_END}"],
                                "trade_date", "trade_date", "close")
        out[key] = {str(k.date()): float(v) for k, v in s.items()}
    # 资金费(CORE 用 BTC 的,与 tom_inputs 一致)
    rows, total = fetch_paged("funding_history", "funding_time,funding_rate",
                              ["venue=eq.binance_perp", "symbol=eq.BTC",
                               f"funding_time=gte.{FETCH_START}", f"funding_time=lte.{WIN_END}"],
                              "funding_time")
    log(f"  funding_history BTC/binance_perp: {len(rows)} 行(server total={total})")
    out["funding"] = rows
    # 现金利率:feature_matrix_daily 的 f->>'stable_lend_apy_7d'
    rows, total = fetch_paged("feature_matrix_daily", "d,f",
                              [f"d=gte.{FETCH_START}", f"d=lte.{WIN_END}"], "d")
    log(f"  feature_matrix_daily: {len(rows)} 行(server total={total})")
    apy = {}
    for r in rows:
        f = r.get("f") or {}
        if isinstance(f, dict) and f.get("stable_lend_apy_7d") is not None:
            apy[str(r["d"])[:10]] = float(f["stable_lend_apy_7d"])
    log(f"  stable_lend_apy_7d 非空 {len(apy)}/{len(rows)}"
        + (f" {min(apy)} → {max(apy)}" if apy else ""))
    out["cash_apy"] = apy
    # 面板 dist_200(情景基准率;结算源 state_daily)
    rows, total = fetch_paged("state_daily", "d,value",
                              ["entity=eq.panel", "feature=eq.dist_200",
                               f"d=gte.{FETCH_START}", f"d=lte.{WIN_END}"], "d")
    log(f"  state_daily panel/dist_200: {len(rows)} 行(server total={total})")
    out["dist_200"] = {str(r["d"])[:10]: float(r["value"]) for r in rows if r.get("value") is not None}
    # 情景锚点:最新收盘
    latest = {}
    for sym, key in (("ACWI", "acwi"), ("XAUUSD", "xauusd")):
        st, body, _ = rest("ohlcv_daily",
                           f"select=trade_date,close&symbol=eq.{sym}&source=eq.eodhd&order=trade_date.desc&limit=1")
        page = json.loads(body) if body.strip() else []
        latest[key] = page[0] if page else None
    st, body, _ = rest("state_daily", "select=d,value&entity=eq.panel&feature=eq.dist_200&order=d.desc&limit=1")
    page = json.loads(body) if body.strip() else []
    latest["dist_200"] = page[0] if page else None
    out["latest"] = latest
    for k, v in latest.items():
        log(f"  latest {k}: {v}")
    return out


# ── 核(flex_alloc) ──────────────────────────────────────────────────────────────
def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def snapshot_kernels() -> dict:
    """把两份核各存一份字节快照(保证运行期间不被改动),并记 sha256。

    新核 = 带 `cash_ret` / `overlay_ret` 的那一份(S-815 写死的内核);
    旧核 = origin/main 的那一份(自检 ③ 的对照)。"""
    cands = []
    for tag, root in (("main_worktree", MAIN_ROOT), ("repo_src", REPO_ROOT)):
        p = os.path.join(root, "src", "data", "universe", "flex_alloc.py")
        if os.path.exists(p):
            cands.append((tag, p))
    new = None
    for tag, p in cands:
        txt = open(p, encoding="utf-8").read()
        if "cash_ret" in txt and "overlay_ret" in txt:
            new = (tag, p, txt)
            break
    if new is None:
        sys.exit("找不到带 cash_ret / overlay_ret 的核(候选:" + str(cands) + ")—— @seth:内核要先落 main。")
    with open(KERNEL_NEW, "w", encoding="utf-8") as f:
        f.write(new[2])
    old_txt = subprocess.run(["git", "-C", REPO_ROOT, "show", "origin/main:src/data/universe/flex_alloc.py"],
                             capture_output=True, text=True, check=True).stdout
    with open(KERNEL_OLD, "w", encoding="utf-8") as f:
        f.write(old_txt)
    info = {
        "new": {"source": new[0], "path": new[1], "snapshot": KERNEL_NEW,
                "sha256": hashlib.sha256(new[2].encode("utf-8")).hexdigest(),
                "has_cash_overlay": True},
        "old": {"source": "origin/main", "snapshot": KERNEL_OLD,
                "sha256": hashlib.sha256(old_txt.encode("utf-8")).hexdigest(),
                "has_cash_overlay": "cash_ret" in old_txt},
        "candidates": [c[1] for c in cands],
    }
    log(f"  新核(带 cash/overlay): {info['new']['source']} sha256={info['new']['sha256'][:16]}…")
    log(f"  旧核(origin/main): sha256={info['old']['sha256'][:16]}… "
        f"带 cash/overlay={info['old']['has_cash_overlay']}")
    return info


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


def check_s815() -> dict:
    """核对嵌进报告的 S-815 原文与 REFUTATION_LEDGER.md 逐字一致。"""
    for p in (os.path.join(REPO_ROOT, "REFUTATION_LEDGER.md"),
              os.path.join(MAIN_ROOT, "REFUTATION_LEDGER.md")):
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8").read()
        i = txt.find("## S-815")
        if i < 0:
            continue
        lines = txt[i:].split("\n")
        end = len(lines)
        for k, ln in enumerate(lines):
            if k > 0 and ln.startswith("### "):
                end = k
                break
        block = "\n".join(lines[:end]).strip()
        return {"ledger_path": p, "match": block == S815.strip(),
                "ledger_lines": end, "ledger_chars": len(block), "embed_chars": len(S815.strip()),
                "ledger_tail": block[-120:], "embed_tail": S815.strip()[-120:]}
    return {"ledger_path": None, "match": None}


# ── 指标 ────────────────────────────────────────────────────────────────────────
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


def yearly(nav: pd.Series) -> dict:
    """逐年收益:第 y 年 = 该年最后一个 NAV ÷ 上一年最后一个 NAV(第一年用起点)。"""
    nav = nav.dropna()
    out: dict[int, float] = {}
    if len(nav) < 2:
        return out
    prev = float(nav.iloc[0])
    for y, grp in nav.groupby(nav.index.year):
        last = float(grp.iloc[-1])
        out[int(y)] = last / prev - 1.0
        prev = last
    return out


# ── R-v2 叠加(t310_slots + t251_gross_cap.simulate,一字不改)────────────────────
def build_overlay(risk_frac: float) -> dict:
    """跑一遍 R-v2 引擎,取净值曲线的逐日收益。"""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import t251_gross_cap as T251       # noqa: PLC0415
    import t310_slots as T310           # noqa: PLC0415
    if not _RV2["loaded"]:
        raw, t197 = T310.load_tickets()
        need = {t["symbol"] for t in raw}
        bars = T310.load_bars(need)
        exits, bad = T310.classify_exits(raw, bars)
        log(f"  R-v2 票源 {len(raw)} 张 / {len(need)} 符号;重算出场与 t197 不一致 {len(bad)} 张")
        _RV2.update({"loaded": True, "tickets": T310.to_engine_tickets(raw, exits), "bars": bars,
                     "n_bad": len(bad), "T251": T251})
        _RV2["gate"] = T310.load_gate()[0]
    T251 = _RV2["T251"]
    res = T251.simulate(_RV2["tickets"], _RV2["bars"], _RV2["gate"], RV2_GROSS_CAP, equity0=RV2_EQ0,
                        risk_frac=risk_frac, cap_n=RV2_CAP_N)
    st = T251.curve_stats(res["curve"], RV2_EQ0)
    curve = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index()
    dret = curve.pct_change().dropna()
    log(f"  R-v2 f={risk_frac:.3%} cap_n={RV2_CAP_N} gross_cap={RV2_GROSS_CAP}: "
        f"总收益 {st['total_return']:+.4%} 最大回撤 {st['max_dd']:+.4%} Calmar {st['calmar']} "
        f"成交 {len(res['taken'])} 张 / 曲线 {len(curve)} 天 {curve.index[0]} → {curve.index[-1]}")
    return {"stats": st, "dret": dret, "curve": curve, "n_taken": len(res["taken"]),
            "n_exit_mismatch": _RV2["n_bad"], "risk_frac": risk_frac}


_RV2: dict = {"loaded": False}


# ── 主流程 ──────────────────────────────────────────────────────────────────────
ARMS = [
    ("L0", "常数 T25(30 / 30 / 20);现金 0;无叠加"),
    ("L1", "L0 + R-v2 叠加(f 0.5%,cap_n 14,gross_cap 0.40)—— 11-10 之前的真钱基线"),
    ("L2", "L1 换 RBv2 权重(crypto 0.20–0.40)—— 11-30 起的真钱"),
    ("L3", "L2 + 现金计息(stable_lend_apy_7d ÷ 100 ÷ 365)"),
    ("L4", "L3 的 R-v2 f 提到 1.0%(S-638 的 f★)"),
    ("L3H", "L3 但加密腿直接持有 ①(不用 X1V)"),
]
REPORT_MD = os.path.join(HERE, "T-342_house_book.md")
OUT_JSON = os.path.join(HERE, "t342_results.json")
DAILY_CSV = os.path.join(HERE, "t342_daily.csv")
SCEN_JSON = os.path.join(HERE, "scenarios", "lane-c-T-342.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="只取数 + 打印覆盖")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--check", action="store_true", help="只核对 S-815 原文与台账是否逐字一致")
    args = ap.parse_args()

    chk = check_s815()
    log(f"  S-815 原文核对: {json.dumps(chk, ensure_ascii=False)}")
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

    kinfo = snapshot_kernels()
    fa = _load_module(KERNEL_NEW, "flex_alloc_s815")
    fa_old = _load_module(KERNEL_OLD, "flex_alloc_main")
    trade_path, trade_returns, ab_test = load_tom_and_apparatus()
    log(f"  BASE_T25={fa.BASE_T25} BOUNDS={fa.BOUNDS} VOL_WINDOW={fa.VOL_WINDOW} MIN_OBS={fa.MIN_OBS}")
    if dict(fa.BOUNDS) != dict(fa_old.BOUNDS):
        sys.exit(f"两份核的 BOUNDS 不一致:新 {fa.BOUNDS} 旧 {fa_old.BOUNDS} —— 停。")

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
    rets1 = raw_rets.fillna(0.0)
    core = (1.0 + rets1).cumprod()
    log(f"  ① cap_pit24: 表 {len(cv_rows)} 行 {d0.date()} → {d1.date()};日历补齐 {len(full_idx)} 天"
        f"(其中无行 {n_null} 天按 0 收益)")

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

    # ── crypto 腿 = tom 核(TOM_ARMS['CORE_X1V'] = ('CORE','rally',0.0,'l20',True))──
    g = trade_path(core, "rally", 0.0, "l20", True)
    r = trade_returns(core, g, fund if len(fund) else None)
    crypto_nav = pd.concat([pd.Series([1.0], index=[core.index[0]]), (1.0 + r).cumprod()]).sort_index()
    log(f"  crypto 腿(X1V on ①): {len(crypto_nav)} 行 {crypto_nav.index[0].date()} → {crypto_nav.index[-1].date()}")
    g_after = g.iloc[200:]
    g_flat = g_after[g_after == 0.0]
    g_stats = {
        "after_warm_n": int(len(g_after)),
        "after_warm_flat_days": int(len(g_flat)),
        "after_warm_full_days": int((g_after == 1.0).sum()),
        "after_warm_flat_first": str(g_flat.index[0].date()) if len(g_flat) else None,
        "after_warm_flat_last": str(g_flat.index[-1].date()) if len(g_flat) else None,
        "warm_until": str(g.index[min(199, len(g) - 1)].date()),
    }
    log(f"  crypto 腿敞口 g:前 200 日 g≡1.0(核内建 WARM=200,到 {g_stats['warm_until']});"
        f"其后 {g_stats['after_warm_n']} 天里 g=0 有 {g_stats['after_warm_flat_days']} 天 "
        f"({g_stats['after_warm_flat_first']} → {g_stats['after_warm_flat_last']})")

    legs_x = {"crypto": crypto_nav, "equity": equity, "gold": gold}
    df = pd.concat(legs_x, axis=1).dropna().sort_index()
    log(f"  三腿共同日期: {len(df)} 天 {df.index[0].date()} → {df.index[-1].date()}")
    if len(df) <= WARM_DAYS + 2:
        sys.exit(f"共同日期只有 {len(df)} 天,不够 63 天历史 + 判定。")
    start = df.index[WARM_DAYS]
    end = df.index[-1]
    log(f"  记 NAV 区间: {start.date()} → {end.date()}(前 {WARM_DAYS} 个共同日只作历史)")

    # ── 现金利率(stable_lend_apy_7d ÷ 100 ÷ 365;2023-02-10 之前没有 ⇒ 0)────────
    apy = raw.get("cash_apy") or {}
    cal = pd.date_range(df.index[0].normalize(), end, freq="D")
    cash_ret = pd.Series({d: (float(apy[str(d.date())]) / 100.0 / 365.0
                              if str(d.date()) in apy else 0.0) for d in cal}, dtype=float)
    n_apy = int((cash_ret > 0).sum())
    log(f"  现金利率: {len(cash_ret)} 个日历日,其中有 apy 的 {n_apy} 天"
        + (f"(首个 {min(apy)});其余记 0" if apy else ""))

    # ── R-v2 叠加曲线(f 0.5% 与 1.0%)──────────────────────────────────────────
    ov_base = build_overlay(RV2_F_BASE)
    ov_high = build_overlay(RV2_F_HIGH)
    ov_base_ret = ov_base["dret"]
    ov_high_ret = ov_high["dret"]

    # ── 腿 CSV:先落,再算(下面的算全从落好的 CSV 读回)────────────────────────
    rec = df[df.index >= start]
    with open(DAILY_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "core_nav_1_cap_pit24", "crypto_leg_nav_x1v",
                    "equity_close_acwi", "gold_close_xauusd",
                    "cash_daily_rate", "cash_apy_7d_pct", "rv2_daily_ret_f05",
                    "rv2_daily_ret_f10", "is_record_window"])
        for d in df.index:
            w.writerow([
                str(d.date()),
                f"{float(core.get(d, float('nan'))):.10g}" if d in core.index else "",
                # 三条进记账的腿按 8 位有效数字落盘 —— 与 T-321 的腿 CSV 同口径,
                # 自检 ①(逐位复现 T-321 的 T25_K)才成立
                f"{float(crypto_nav.get(d, float('nan'))):.8g}" if d in crypto_nav.index else "",
                f"{float(equity.get(d, float('nan'))):.8g}" if d in equity.index else "",
                f"{float(gold.get(d, float('nan'))):.8g}" if d in gold.index else "",
                f"{float(cash_ret.get(d.normalize(), 0.0)):.10g}",
                f"{float(apy.get(str(d.date()), float('nan'))):.10g}" if str(d.date()) in apy else "",
                f"{float(ov_base_ret.get(d, 0.0)):.10g}",
                f"{float(ov_high_ret.get(d, 0.0)):.10g}",
                "1" if d >= start else "0",
            ])
    log(f"  落 {DAILY_CSV}({len(df)} 行,记 NAV {len(rec)} 行)")

    # 从落好的 CSV 读回:算只认这份文件
    cdf = pd.read_csv(DAILY_CSV, parse_dates=["date"]).set_index("date").sort_index()
    legs = {"crypto": cdf["crypto_leg_nav_x1v"].astype(float),
            "equity": cdf["equity_close_acwi"].astype(float),
            "gold": cdf["gold_close_xauusd"].astype(float)}
    core_csv = cdf["core_nav_1_cap_pit24"].astype(float)
    cash_ret = cdf["cash_daily_rate"].astype(float)
    ov_base_ret = cdf["rv2_daily_ret_f05"].astype(float)
    ov_high_ret = cdf["rv2_daily_ret_f10"].astype(float)
    df = pd.concat(legs, axis=1).dropna().sort_index()
    log(f"  从 CSV 读回:{len(df)} 天 {df.index[0].date()} → {df.index[-1].date()}")
    n_ov = int((ov_base_ret != 0).sum())
    win_ov = ov_base_ret[ov_base_ret.index >= start]
    log(f"  R-v2 日收益(读回):非零 {n_ov}/{len(ov_base_ret)} 天;记 NAV 区间内复利 "
        f"{(1 + win_ov).prod() - 1:+.4%}(f 0.5%)")
    if n_ov == 0:
        sys.exit("R-v2 叠加读回后全 0 —— 停(索引没对上)。")

    # ── 六条臂 ────────────────────────────────────────────────────────────────
    def fn_const(hist, d):
        return fa.BASE_T25

    def fn_rb(hist, d):
        return fa.rb_weights(hist)

    legs_h = {"crypto": core_csv, "equity": legs["equity"], "gold": legs["gold"]}
    plan = {
        "L0": (legs, fn_const, None, None),
        "L1": (legs, fn_const, None, ov_base_ret),
        "L2": (legs, fn_rb, None, ov_base_ret),
        "L3": (legs, fn_rb, cash_ret, ov_base_ret),
        "L4": (legs, fn_rb, cash_ret, ov_high_ret),
        "L3H": (legs_h, fn_rb, cash_ret, ov_base_ret),
    }
    arms, logs = {}, {}
    for name, (lg, fn, cr, ov) in plan.items():
        nav, lg_log = fa.dynamic_mix_nav(lg, fn, reb=REB, cost=COST, start=start,
                                         cash_ret=cr, overlay_ret=ov)
        nav = nav[nav.index <= pd.Timestamp(WIN_END)]
        arms[name] = nav
        logs[name] = lg_log
        log(f"  臂 {name}: {len(nav)} 天 {nav.index[0].date()} → {nav.index[-1].date()} "
            f"终值 {float(nav.iloc[-1]):.4f} 调仓 {len(lg_log)} 次")

    if args.probe:
        json.dump({"kernel": kinfo, "df_index": [str(x.date()) for x in df.index]},
                  open(os.path.join(DATA_ROOT, "t342_probe.json"), "w"))
        log("=== probe 结束 ===")
        return

    # ── 自检 ①:L0 在 S-799 窗口复现 T-321 的 T25_K(−15.70%)────────────────────
    l0_s799 = arms["L0"][arms["L0"].index <= pd.Timestamp(S799_END)]
    m_l0_s799 = metrics(l0_s799)
    t321 = json.load(open(os.path.join(HERE, "t321_results.json")))
    t321_tk = t321["arms"]["T25_K"]["metrics"]
    chk1 = {
        "what": "L0(常数 T25)在 S-799 窗口(2021-10-11 → 2022-12-30)复现 T-321 的 T25_K",
        "t342_L0": m_l0_s799,
        "t321_T25_K": t321_tk,
        "total_return_diff_pp": (m_l0_s799["total_return"] - t321_tk["total_return"]) * 100,
        "max_dd_diff_pp": (m_l0_s799["max_dd"] - t321_tk["max_dd"]) * 100,
        "n_days_same": int(m_l0_s799["n_days"] == t321_tk["n_days"]),
        "target_total_return": t321_tk["total_return"],
        "target_label": "−15.70%",
    }
    chk1["pass"] = bool(abs(chk1["total_return_diff_pp"]) < 1e-9 and abs(chk1["max_dd_diff_pp"]) < 1e-9)
    log(f"  自检①: L0@S-799 总收益 {m_l0_s799['total_return']*100:.4f}% vs T-321 {t321_tk['total_return']*100:.4f}%"
        f"(差 {chk1['total_return_diff_pp']:.2e} pp)→ {'✅' if chk1['pass'] else '❌'}")

    # ── 自检 ②:R-v2 曲线复现 T-310 的 cap 14(+63.50% / −25.71%)─────────────────
    t310 = json.load(open(os.path.join(HERE, "t310_results.json")))
    t310_14 = t310["slots"]["14"]["0.40"]["stats"]
    st = ov_base["stats"]
    chk2 = {
        "what": "R-v2 曲线(cap_n 14、gross_cap 0.40、f 0.5%)复现 T-310 的 cap 14",
        "t342": {"total_return": st["total_return"], "max_dd": st["max_dd"], "calmar": st["calmar"],
                 "n_days": st["n_days"], "end_equity": st["end_equity"]},
        "t310": {"total_return": t310_14["total_return"], "max_dd": t310_14["max_dd"],
                 "calmar": t310_14["calmar"], "n_days": t310_14["n_days"],
                 "end_equity": t310_14["end_equity"]},
        "total_return_diff_pp": (st["total_return"] - t310_14["total_return"]) * 100,
        "max_dd_diff_pp": (st["max_dd"] - t310_14["max_dd"]) * 100,
        "target_label": "+63.50% / −25.71%",
    }
    chk2["pass"] = bool(abs(chk2["total_return_diff_pp"]) < 1e-6 and abs(chk2["max_dd_diff_pp"]) < 1e-6)
    log(f"  自检②: R-v2 cap14 总收益 {st['total_return']*100:.4f}% / 回撤 {st['max_dd']*100:.4f}%"
        f" vs T-310 {t310_14['total_return']*100:.4f}% / {t310_14['max_dd']*100:.4f}%"
        f" → {'✅' if chk2['pass'] else '❌'}")

    # ── 自检 ③:新核(不给 cash/overlay)与旧核逐位相同 ──────────────────────────
    nav_new, log_new = fa.dynamic_mix_nav(legs, fn_const, reb=REB, cost=COST, start=start)
    nav_old, log_old = fa_old.dynamic_mix_nav(legs, fn_const, reb=REB, cost=COST, start=start)
    nav_new = nav_new[nav_new.index <= pd.Timestamp(WIN_END)]
    nav_old = nav_old[nav_old.index <= pd.Timestamp(WIN_END)]
    same_len = len(nav_new) == len(nav_old)
    same_idx = bool(same_len and (nav_new.index == nav_old.index).all())
    diffs = []
    if same_idx:
        for a, b in zip(nav_new.to_numpy(), nav_old.to_numpy()):
            if repr(float(a)) != repr(float(b)):
                diffs.append(repr(float(a)))
    same_log = repr(log_new) == repr(log_old)
    chk3 = {
        "what": "带 cash_ret / overlay_ret 的核在两者都不给时,与 origin/main 的旧核逐位相同",
        "n_days_new": int(len(nav_new)), "n_days_old": int(len(nav_old)),
        "index_same": same_idx,
        "n_value_diffs": len(diffs),
        "first_diffs": diffs[:5],
        "rebalance_log_same": bool(same_log),
        "end_new": repr(float(nav_new.iloc[-1])), "end_old": repr(float(nav_old.iloc[-1])),
    }
    chk3["pass"] = bool(same_idx and not diffs and same_log)
    log(f"  自检③: 新核 vs 旧核 —— 天数 {chk3['n_days_new']}/{chk3['n_days_old']}、"
        f"逐位不同的值 {chk3['n_value_diffs']} 个、调仓日志相同={same_log} → {'✅' if chk3['pass'] else '❌'}")

    # ── 指标 ──────────────────────────────────────────────────────────────────
    met = {k: metrics(v) for k, v in arms.items()}
    yr = {k: yearly(v) for k, v in arms.items()}
    # ① 自己(归一到记 NAV 起点)
    core_rec = core_csv[core_csv.index >= start]
    core_rec = core_rec / float(core_rec.iloc[0])
    met["CORE_1"] = metrics(core_rec)
    yr["CORE_1"] = yearly(core_rec)
    arms["CORE_1"] = core_rec

    # ── 差表(相邻两级)─────────────────────────────────────────────────────────
    diffs_tbl = []
    for a, b in (("L0", "L1"), ("L1", "L2"), ("L2", "L3"), ("L3", "L4"), ("L3", "L3H")):
        ma, mb = met[a], met[b]
        row = {"from": a, "to": b,
               "d_total_return_pp": (mb["total_return"] - ma["total_return"]) * 100,
               "d_cagr_pp": (mb["cagr"] - ma["cagr"]) * 100,
               "d_vol_pp": ((mb["vol_ann"] or 0) - (ma["vol_ann"] or 0)) * 100,
               "d_max_dd_pp": (mb["max_dd"] - ma["max_dd"]) * 100,   # 正 = 回撤变浅
               "d_calmar": (mb["calmar"] or 0) - (ma["calmar"] or 0),
               "d_worst_month_pp": ((mb["worst_month"] or 0) - (ma["worst_month"] or 0)) * 100}
        for y in range(2022, 2027):
            row[f"d_{y}_pp"] = ((yr[b].get(y) or 0.0) - (yr[a].get(y) or 0.0)) * 100
        diffs_tbl.append(row)

    # ── A/B(L2 vs L1:RBv2 这个开关;用 apparatus.ab_test)───────────────────────
    r1 = arms["L1"].pct_change().dropna()
    r2 = arms["L2"].pct_change().dropna()
    ab = ab_test(r1.to_numpy(), r2.to_numpy(), mean_block=AB_MEAN_BLOCK, n_boot=AB_N_BOOT, seed=AB_SEED)
    log(f"  ab_test(L1 → L2): p(L2≤L1)={ab['p_b_le_a']} p(L2≥L1)={ab['p_b_ge_a']} 判定={ab['verdict']}")

    # ── 判据:L3 / L4 ─────────────────────────────────────────────────────────
    years = list(range(2022, 2027))
    l1, l3, l4 = met["L1"], met["L3"], met["L4"]
    c_i = l3["max_dd"] >= -0.25
    c_ii = l3["cagr"] >= l1["cagr"]
    c_iii_rows = []
    for y in years:
        v3, v1 = yr["L3"].get(y), yr["L1"].get(y)
        c_iii_rows.append({"year": y, "L3": v3, "L1": v1, "diff_pp": (v3 - v1) * 100,
                           "pass": bool(v3 >= v1 - 0.01)})
    c_iii = all(r["pass"] for r in c_iii_rows)
    judge = {
        "L3": {"(i) 最大回撤不深于 −25%": {"value": l3["max_dd"], "threshold": -0.25, "pass": bool(c_i)},
               "(ii) CAGR ≥ L1": {"L3_cagr": l3["cagr"], "L1_cagr": l1["cagr"], "pass": bool(c_ii)},
               "(iii) 逐年 ≥ L1 同年 − 1pp": {"rows": c_iii_rows, "pass": bool(c_iii)}},
        "L4": {"(i) 最大回撤不深于 −25%": {"value": l4["max_dd"], "threshold": -0.25,
                                          "pass": bool(l4["max_dd"] >= -0.25)}},
    }
    judge["L3"]["pass"] = bool(c_i and c_ii and c_iii)
    judge["L4"]["pass"] = bool(l4["max_dd"] >= -0.25)
    log(f"  判据 L3: (i)={c_i} (ii)={c_ii} (iii)={c_iii} → {'✅ 过' if judge['L3']['pass'] else '❌ 不过'}")
    log(f"  判据 L4: (i)={l4['max_dd'] >= -0.25} → {'✅ 过' if judge['L4']['pass'] else '❌ 不过'}")

    # ── 情景文件(前向命题)────────────────────────────────────────────────────
    latest = raw.get("latest") or {}
    acwi_close = float((latest.get("acwi") or {}).get("close"))
    xau_close = float((latest.get("xauusd") or {}).get("close"))
    d200 = to_series(raw.get("dist_200"))
    base_rate_up = float((d200 > 0).mean()) if len(d200) else 0.5
    # ACWI / XAUUSD 的「未来 6 周高于今天」的历史命中率(在窗口内用 42 个自然日)
    def fwd_hit(s: pd.Series, days: int = 42) -> float:
        s = s.dropna()
        if len(s) < 10:
            return 0.5
        fut = s.shift(-1)
        hit = 0
        n = 0
        for i in range(len(s)):
            j = s.index.searchsorted(s.index[i] + pd.Timedelta(days=days))
            if j >= len(s):
                break
            n += 1
            if float(s.iloc[j]) > float(s.iloc[i]):
                hit += 1
        return hit / n if n else 0.5

    acwi_hit = fwd_hit(equity)
    xau_hit = fwd_hit(gold)
    scen = {
        "author": "lane-c",
        "entries": [
            {"id": "T-342-1", "author": "lane-c",
             "scenario": "S-815 整合账本 · 股票腿",
             "statement": (
                 f"ACWI 在 2026-12-15 的收盘高于 {WIN_END} 的收盘 {acwi_close:.2f}。"
                 f"T-342 实测:{WIN_END} ACWI = {acwi_close:.2f};窗口内 ACWI 未来 42 个自然日高于当天的命中率 "
                 f"{acwi_hit:.2f}({len(equity.dropna())} 个交易日上量);L3 账户里股票腿占 20–40% 权重,给 {acwi_hit:.2f}。"),
             "variable": "close:ACWI", "op": "gt", "lo": acwi_close, "hi": None,
             "prob": round(acwi_hit, 2), "horizon_d": "2026-12-15"},
            {"id": "T-342-2", "author": "lane-c",
             "scenario": "S-815 整合账本 · 黄金腿",
             "statement": (
                 f"XAUUSD 在 2026-12-15 的收盘高于 {WIN_END} 的收盘 {xau_close:.2f}。"
                 f"T-342 实测:{WIN_END} XAUUSD = {xau_close:.2f};窗口内 XAUUSD 未来 42 个自然日高于当天的命中率 "
                 f"{xau_hit:.2f};黄金是 L0–L4 里波动最小的一条腿,给 {xau_hit:.2f}。"),
             "variable": "close:XAUUSD", "op": "gt", "lo": xau_close, "hi": None,
             "prob": round(xau_hit, 2), "horizon_d": "2026-12-15"},
            {"id": "T-342-3", "author": "lane-c",
             "scenario": "S-815 整合账本 · 面板天气",
             "statement": (
                 f"面板 dist_200 在 2026-12-15 仍 > 0(① 在 200 日线上)。T-342 实测:窗口内 "
                 f"{base_rate_up:.2f} 的日子 dist_200 > 0;RBv2 的权重就是按这种「上/下 × 冷/热」四档切的,给 {base_rate_up:.2f}。"),
             "variable": "state:dist_200", "op": "gt", "lo": 0.0, "hi": None,
             "prob": round(base_rate_up, 2), "horizon_d": "2026-12-15"},
            {"id": "T-342-4", "author": "lane-c",
             "scenario": "S-815 整合账本 · 前向整合臂",
             "statement": (
                 "到 2027-03-31,前向整合臂(book=flex_x1v、arm=RB_T25_Y = RBv2 + 现金计息)的 NAV ≥ "
                 "同 book 下 T25_K 的 NAV(比值 ≥ 1)。人工结算:取 forward_book_nav 里 book=flex_x1v、"
                 "arm ∈ {RB_T25_Y, T25_K} 在 2027-03-31 的 nav,比值 = RB_T25_Y / T25_K。"
                 f"T-342 回放里 RBv2 这个开关(L1→L2)在 {met['L1']['d0']} → {met['L1']['d1']} 的 "
                 f"CAGR 差 {diffs_tbl[1]['d_cagr_pp']:+.2f}pp/年、apparatus.ab_test 的 p(L2≥L1)="
                 f"{ab['p_b_ge_a']};先验 {ab['p_b_ge_a']:.2f}。"),
             "variable": "manual", "op": "gt", "lo": 1.0, "hi": None,
             "prob": round(float(ab["p_b_ge_a"]), 2), "horizon_d": "2027-03-31"},
        ],
    }
    os.makedirs(os.path.dirname(SCEN_JSON), exist_ok=True)
    json.dump(scen, open(SCEN_JSON, "w"), indent=1, ensure_ascii=False)
    log(f"  落 {SCEN_JSON}({len(scen['entries'])} 条命题)")

    # ── 结果 JSON ────────────────────────────────────────────────────────────
    out = {
        "card": "T-342", "ledger": "S-815",
        "kernel": kinfo,
        "kernel_params": {"BASE_T25": fa.BASE_T25, "BOUNDS": fa.BOUNDS,
                          "VOL_WINDOW": fa.VOL_WINDOW, "MIN_OBS": fa.MIN_OBS,
                          "reb": REB, "cost_bp": COST * 1e4,
                          "source": "src/data/universe/flex_alloc.py(带 cash_ret / overlay_ret 的一份;一字不改,只 import)"},
        "s815_text_check": chk,
        "window": {"common_start": str(df.index[0].date()), "record_start": str(start.date()),
                   "record_end": str(end.date()), "n_common": int(len(df)),
                   "n_record": int(len(rec)), "warm_days": WARM_DAYS},
        "data_coverage": {
            "core_cap_pit24": {"rows": len(cv_rows), "d0": str(d0.date()), "d1": str(d1.date()),
                               "calendar_days": len(full_idx), "missing": n_null},
            "equity_acwi": {"rows": int(len(equity)), "d0": str(equity.index[0].date()),
                            "d1": str(equity.index[-1].date())},
            "gold_xauusd": {"rows": int(len(gold)), "d0": str(gold.index[0].date()),
                            "d1": str(gold.index[-1].date())},
            "funding_btc": {"rows": int(len(fund)), "d0": str(fund.index[0].date()) if len(fund) else None,
                            "d1": str(fund.index[-1].date()) if len(fund) else None},
            "cash_apy": {"days_with_apy": n_apy, "calendar_days": int(len(cash_ret)),
                         "first_apy": min(apy) if apy else None, "last_apy": max(apy) if apy else None},
            "rv2_curve": {"d0": str(ov_base["curve"].index[0]), "d1": str(ov_base["curve"].index[-1]),
                          "n_days": int(len(ov_base["curve"])), "n_taken": ov_base["n_taken"],
                          "n_exit_mismatch_vs_t197": ov_base["n_exit_mismatch"],
                          "note": "票源到 2026-09-30 为止:窗口最后一个月(10-01 → 10-30)R-v2 贡献为 0"},
        },
        "crypto_leg_exposure": g_stats,
        "self_checks": {"①": chk1, "②": chk2, "③": chk3},
        "arms": {k: {"metrics": met[k], "yearly": {str(y): v for y, v in yr[k].items()}}
                 for k in list(met.keys())},
        "arm_defs": {k: v for k, v in ARMS},
        "diffs": diffs_tbl,
        "ab_test_L1_vs_L2": ab,
        "judgement": judge,
        "rv2_base": {"stats": ov_base["stats"], "risk_frac": RV2_F_BASE},
        "rv2_high": {"stats": ov_high["stats"], "risk_frac": RV2_F_HIGH},
        "legs_csv": DAILY_CSV,
        "scenarios": SCEN_JSON,
        "report_md": REPORT_MD,
    }
    json.dump(out, open(OUT_JSON, "w"), indent=1, default=str)
    log(f"  落 {OUT_JSON}")

    write_report(out, met, yr, diffs_tbl, ab, judge, chk1, chk2, chk3, scen, raw)
    log(f"  落 {REPORT_MD}")


# ── 报告 ────────────────────────────────────────────────────────────────────────
def _pct(x, nd=2):
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def _pp(x, nd=2):
    return "—" if x is None else f"{x:+.{nd}f}pp"


def write_report(out, met, yr, diffs_tbl, ab, judge, chk1, chk2, chk3, scen, raw) -> None:
    A: list[str] = []
    A.append("# T-342 · S-815 整合账本(2021-10-11 → 2026-10-30)")
    A.append("")
    A.append("> **预注册原文(S-815,逐字照抄;运行时与 `REFUTATION_LEDGER.md` 逐字核对)↓**")
    A.append("")
    for ln in S815.strip().split("\n"):
        A.append(ln)
        A.append("")
    A.append("---")
    A.append("")
    A.append(f"**一句话结论:**L3 = {'✅ 过' if judge['L3']['pass'] else '❌ 不过'}"
             f"(判据 (i) {'✅' if judge['L3']['(i) 最大回撤不深于 −25%']['pass'] else '❌'}、"
             f"(ii) {'✅' if judge['L3']['(ii) CAGR ≥ L1']['pass'] else '❌'}、"
             f"(iii) {'✅' if judge['L3']['(iii) 逐年 ≥ L1 同年 − 1pp']['pass'] else '❌'});"
             f"L4 = {'✅ 过' if judge['L4']['pass'] else '❌ 不过'}"
             f"(判据 (i) 最大回撤 {met['L4']['max_dd'] * 100:.2f}%)。")
    A.append("")

    A.append("## 0 · 三条自检")
    A.append("")
    A.append("| 自检 | 结果 |")
    A.append("|---|---|")
    A.append(f"| ① L0 在 S-799 窗口复现 T-321 的 T25_K(−15.70%) | "
             f"{'✅' if chk1['pass'] else '❌'} 总收益 {met['L0']['total_return'] * 100:.4f}% "
             f"→ S-799 窗口 {chk1['t342_L0']['total_return'] * 100:.4f}%"
             f"(与 T-321 差 {chk1['total_return_diff_pp']:.2e}pp)、最大回撤差 {chk1['max_dd_diff_pp']:.2e}pp |")
    A.append(f"| ② R-v2 曲线复现 T-310 的 cap 14(+63.50% / −25.71%) | "
             f"{'✅' if chk2['pass'] else '❌'} 总收益 {chk2['t342']['total_return'] * 100:.4f}%、"
             f"最大回撤 {chk2['t342']['max_dd'] * 100:.4f}%(与 T-310 差 {chk2['total_return_diff_pp']:.2e}pp / {chk2['max_dd_diff_pp']:.2e}pp) |")
    A.append(f"| ③ 不给 cash_ret / overlay_ret 时与旧核逐位相同 | "
             f"{'✅' if chk3['pass'] else '❌'} {chk3['n_days_new']} 天里逐位不同的值 "
             f"{chk3['n_value_diffs']} 个、调仓日志相同 = {chk3['rebalance_log_same']} |")
    A.append("")
    A.append(f"**核:**新核 `flex_alloc.py` sha256 `{out['kernel']['new']['sha256'][:16]}…`"
             f"(来源 {out['kernel']['new']['source']},带 `cash_ret` / `overlay_ret`);"
             f"对照旧核(origin/main)sha256 `{out['kernel']['old']['sha256'][:16]}…`。"
             f"reb {out['kernel_params']['reb']}、cost {out['kernel_params']['cost_bp']:.0f}bp、"
             f"`BASE_T25` {out['kernel_params']['BASE_T25']}、`BOUNDS` {out['kernel_params']['BOUNDS']}。")
    A.append("")

    A.append("## 1 · 口径")
    A.append("")
    w = out["window"]
    A.append(f"- 共同日 {w['common_start']} → {w['record_end']},共 {w['n_common']} 天;"
             f"前 {w['warm_days']} 个共同日只作历史,记 NAV **{w['record_start']} → {w['record_end']}**({w['n_record']} 天)。")
    A.append(f"- 腿:加密 = `tom` 核(`TOM_ARMS['CORE_X1V']`)作用于 ① `cap_pit24`;"
             f"股 = eodhd ACWI;金 = eodhd XAUUSD。")
    A.append(f"- 现金利率 = `feature_matrix_daily.f->>'stable_lend_apy_7d'` ÷ 100 ÷ 365,"
             f"覆盖 {out['data_coverage']['cash_apy']['days_with_apy']} 个日历日"
             f"(首个 {out['data_coverage']['cash_apy']['first_apy']}),之前的记 0。")
    A.append(f"- R-v2 叠加 = `t251_gross_cap.simulate`(票源 t197 `tickets.A`、cap_n 14、gross_cap 0.40)"
             f"的净值曲线逐日收益;曲线 {out['data_coverage']['rv2_curve']['d0']} → {out['data_coverage']['rv2_curve']['d1']},"
             f"成交 {out['data_coverage']['rv2_curve']['n_taken']} 张,重算出场与 t197 不一致 "
             f"{out['data_coverage']['rv2_curve']['n_exit_mismatch_vs_t197']} 张。"
             f"**票源到 2026-09-30 为止 ⇒ 窗口最后一个月(10-01 → 10-30)R-v2 贡献为 0。**")
    A.append(f"- 逐日底账:`docs/research/t342_daily.csv`(日期、各腿收盘、现金日利率、R-v2 日收益、逐臂 NAV 底稿)。")
    A.append("")

    A.append("## 2 · 梯子(每臂一整套指标)")
    A.append("")
    A.append("| 臂 | 定义 | 总收益 | CAGR | 波动(年) | 最大回撤 | Calmar | 最差月 | 最好月 |")
    A.append("|---|---|---|---|---|---|---|---|---|")
    for name, desc in ARMS + [("CORE_1", "cap_pit24 净值(归一到起点)")]:
        m = met[name]
        cal = "—" if m.get("calmar") is None else f"{m['calmar']:.3f}"
        A.append(f"| **{name}** | {desc} | {_pct(m['total_return'])} | {_pct(m['cagr'])} | "
                 f"{_pct(m['vol_ann'])} | {_pct(m['max_dd'])} | {cal} | "
                 f"{_pct(m['worst_month'])} | {_pct(m['best_month'])} |")
    A.append("")
    A.append("最大回撤的峰/谷:")
    for name in [a for a, _ in ARMS] + ["CORE_1"]:
        m = met[name]
        A.append(f"- {name}:回撤 {m['max_dd'] * 100:.2f}%(峰 {m['dd_peak']} → 谷 {m['dd_trough']})")
    A.append("")

    A.append("## 3 · 逐年收益(2022 … 2026;2026 记到 10-30)")
    A.append("")
    A.append("| 臂 | " + " | ".join(str(y) for y in range(2022, 2027)) + " |")
    A.append("|---|" + "---|" * 5)
    for name in [a for a, _ in ARMS] + ["CORE_1"]:
        A.append(f"| **{name}** | " + " | ".join(_pct(yr[name].get(y)) for y in range(2022, 2027)) + " |")
    A.append("")

    A.append("## 4 · 相邻两级之差(每个开关值多少)")
    A.append("")
    A.append("| 从 → 到 | 开关 | Δ总收益 | ΔCAGR | Δ波动 | Δ最大回撤(正=变浅) | ΔCalmar | Δ最差月 |")
    A.append("|---|---|---|---|---|---|---|---|")
    sw = {"L1": "R-v2 叠加(f 0.5%)", "L2": "RBv2 权重", "L3": "现金计息", "L4": "R-v2 f → 1.0%",
          "L3H": "加密腿改持 ①(不是开关,是腿的替换)"}
    for row in diffs_tbl:
        A.append(f"| {row['from']} → {row['to']} | {sw.get(row['to'], '')} | "
                 f"{_pp(row['d_total_return_pp'])} | {_pp(row['d_cagr_pp'])} | {_pp(row['d_vol_pp'])} | "
                 f"{_pp(row['d_max_dd_pp'])} | {row['d_calmar']:+.3f} | {_pp(row['d_worst_month_pp'])} |")
    A.append("")
    A.append("逐年的差(pp):")
    A.append("")
    A.append("| 从 → 到 | " + " | ".join(str(y) for y in range(2022, 2027)) + " |")
    A.append("|---|" + "---|" * 5)
    for row in diffs_tbl:
        A.append(f"| {row['from']} → {row['to']} | "
                 + " | ".join(_pp(row[f'd_{y}_pp']) for y in range(2022, 2027)) + " |")
    A.append("")

    A.append("## 5 · 判据(只判 L3 与 L4)")
    A.append("")
    j3 = judge["L3"]
    A.append(f"**L3**(RBv2 + R-v2 f 0.5% + 现金计息):{'✅ 全过' if j3['pass'] else '❌ 不过'}")
    A.append("")
    A.append(f"- (i) 全窗口最大回撤不深于 −25%:回撤 {j3['(i) 最大回撤不深于 −25%']['value'] * 100:.2f}%"
             f" → {'✅' if j3['(i) 最大回撤不深于 −25%']['pass'] else '❌'}")
    A.append(f"- (ii) CAGR ≥ L1:L3 {j3['(ii) CAGR ≥ L1']['L3_cagr'] * 100:.2f}% vs L1 "
             f"{j3['(ii) CAGR ≥ L1']['L1_cagr'] * 100:.2f}% → {'✅' if j3['(ii) CAGR ≥ L1']['pass'] else '❌'}")
    A.append(f"- (iii) 逐年收益 ≥ L1 同年 − 1pp:")
    A.append("")
    A.append("| 年 | L3 | L1 | 差 | 判 |")
    A.append("|---|---|---|---|---|")
    for row in j3["(iii) 逐年 ≥ L1 同年 − 1pp"]["rows"]:
        A.append(f"| {row['year']} | {_pct(row['L3'])} | {_pct(row['L1'])} | {_pp(row['diff_pp'])} | "
                 f"{'✅' if row['pass'] else '❌'} |")
    A.append("")
    j4 = judge["L4"]
    A.append(f"**L4**(L3 + R-v2 f 提到 1.0%):{'✅ 过' if j4['pass'] else '❌ 不过'}")
    A.append("")
    A.append(f"- (i) 全窗口最大回撤不深于 −25%:回撤 {j4['(i) 最大回撤不深于 −25%']['value'] * 100:.2f}%"
             f" → {'✅' if j4['pass'] else '❌'}")
    A.append("")
    A.append(f"**A/B(只报,`apparatus.ab_test`,mean_block {AB_MEAN_BLOCK}、n_boot {AB_N_BOOT}、seed {AB_SEED}):**"
             f"L1 → L2 的 `p(L2 ≥ L1)` = {ab['p_b_ge_a']}、`p(L2 ≤ L1)` = {ab['p_b_le_a']},"
             f"比值 {ab['ratio_b_over_a']:.4f},95% 区间 {ab['ci95_log_diff']},判定 **{ab['verdict']}**。")
    A.append("")

    A.append("## 6 · 前向命题(`scenarios/lane-c-T-342.json`)")
    A.append("")
    for e in scen["entries"]:
        A.append(f"- **{e['id']}**({e['variable']} {e['op']} {e['lo']},horizon {e['horizon_d']},p={e['prob']})"
                 f" —— {e['statement']}")
    A.append("")

    A.append("## 7 · 诚实与限制")
    A.append("")
    A.append("- 这是回放:X1V 的执行拖累(T-146 量过 ≈ −9.5pp/年,基准格)不在这里;"
             "R-v2 叠加与腿之间的保证金占用按一阶近似(叠加收益直接相加,没有争保证金);"
             "现金利率是 DeFi 借贷的 7 日均,真钱能拿到的取决于场所。")
    A.append("- R-v2 票源只到 2026-09-30 ⇒ 窗口最后一个月没有叠加贡献;"
             "f = 1.0% 的那一档,票源相同但每票名义翻倍 ⇒ 40% 名义上限更早咬合(票更少)。")
    A.append("- 现金利率 2023-02-10 之前记 0 —— 那段本来就没有 DeFi 借贷利率的观测;"
             "L0/L1/L2 与 L3/L4 的差别因此只从 2023-02-10 起累积。")
    A.append("- 梯子顺序是「已经决定的 → 还没决定的」,不是按效果挑的;本卡是记账合成,试验计数不计。")
    A.append("")

    open(REPORT_MD, "w", encoding="utf-8").write("\n".join(A) + "\n")


if __name__ == "__main__":
    main()
