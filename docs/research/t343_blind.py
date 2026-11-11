#!/usr/bin/env python3
"""T-343 — S-815 盲复算(lane-b):house book 梯子 L0–L4(+ L3H、① 自己)。

口径来源:**只读** `REFUTATION_LEDGER.md` 的 `## S-815` 原文(唯一口径来源)。
**禁读** lane-c 的 `docs/research/t342_*` / `T-342_*` / `lane-c/T-342` 分支 —— 本文件不打开它们。

装配(全部自己来,只用三个「核」):
  内核   `src/data/universe/flex_alloc.dynamic_mix_nav`(reb 21、cost 20bp、11-11 起带 `cash_ret`/`overlay_ret`)
         —— `src/` 那份的 `BOUNDS["crypto"]` 已是 (0.20,0.40)= S-801 的 RBv2;与 lane-b T-320 的副本
         (`t320_flex_alloc_core.py`)只差两处:BOUNDS 与 cash/overlay 两个新参数,其余逐字节相同(已核)。
  腿     crypto = `forward_books.TOM_ARMS['CORE_X1V']` 作用于 **① 的 NAV**(`signals/tom` 核,
         与 lane-b T-331 逐字同一份装配);equity = eodhd `ACWI`;gold = eodhd `XAUUSD`
  ①      `core_variants_daily.cap_pit24`(整个窗口同一条 ①)
  窗口   2021-10-11 → 2026-10-30;腿从 2021-07-13 起(同 S-799 W1),**前 63 个共同日作历史**
  现金   `feature_matrix_daily` 的 `stable_lend_apy_7d` ÷ 100 ÷ 365(逐日历日;2023-02-10 之前记 0)
  叠加   `docs/research/t251_gross_cap.py` 的 `simulate`(票源 `docs/research/t197_results.json` → `tickets.A`,
         cap_n 14、gross_cap 0.40、f 0.5%/1.0%)的净值曲线逐日收益 → `overlay_ret`

只读库、不入库、不改 `src/`。用法:`python3 docs/research/t343_blind.py` → 写 `docs/research/t343_results.json`
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

# t159 的数据根(模块级读 env)—— 必须在 import t159 之前设好
os.environ.setdefault("T156_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t156/")
os.environ.setdefault("T159_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t159/")

from src.data.signals import tom as TOM                  # noqa: E402  交易层核(X1V)
from src.data.universe import flex_alloc as FA           # noqa: E402  组合层核(RBv2 + cash/overlay)
from src.data.universe import forward_books as FB         # noqa: E402  TOM_ARMS

import t251_gross_cap as T251                            # noqa: E402  叠加引擎(simulate / curve_stats,一字不改)

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出")
URL = URL.rstrip("/")

# ── S-815 写死的口径 ───────────────────────────────────────────────────────────
REB, COST = 21, 20 / 1e4
YEAR_BASIS = 365.0
LEG_FROM = "2021-07-13"        # ① 的腿从这天起(同 S-799 W1)
WARM = 63                     # 前 63 个共同日作历史
WINDOW_END = "2026-10-30"     # 记账终点(写死)
NAV_START_EXPECT = "2021-10-11"   # 写死的记账起点
CASH_FIRST = "2023-02-10"     # stable_lend_apy_7d 的第一天;之前记 0

# 叠加(R-v2)口径
T197_JSON = HERE / "t197_results.json"
UM_FILE = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl"
STYLE_FILE = "/Volumes/CometCloudAI/cometcloud-local/research/t156/_style.json"
OVERLAY_EQ0 = 630.0           # t251 的 EQUITY0(「今天账户净值」)
OVERLAY_CAP_N = 14            # S-815 写死
OVERLAY_GROSS = 0.40          # S-815 写死
F_BASE, F_STAR = 0.005, 0.010  # 每票风险 0.5%(L1–L3) / 1.0%(L4,S-638 的 f★)

# 判据(S-815 写死)
MDD_LIMIT = -0.25             # (i) 全窗口最大回撤不深于 −25%
YEAR_TOL = 0.01               # (iii) 逐年收益 ≥ L1 同年 − 1pp

OUT_JSON = HERE / "t343_results.json"
OUT_MD = HERE / "T-343_blind_house_book.md"


# ── 只读取库(分页 ≤1000 行 / 页,必带 order=,核总行数)─────────────────────────
def fetch(table: str, query: str, order: str) -> list[dict]:
    rows, start, total = [], 0, None
    while True:
        req = urllib.request.Request(
            f"{URL}/rest/v1/{table}?{query}&order={order}",
            headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                     "Prefer": "count=exact", "Range": f"{start}-{start + 999}"},
        )
        with urllib.request.urlopen(req, timeout=180) as r:
            cr = r.headers.get("Content-Range", "")
            page = json.loads(r.read().decode())
        if total is None and "/" in cr:
            total = int(cr.split("/")[-1])
        rows.extend(page)
        if len(page) < 1000:
            break
        start += 1000
        if total is not None and start >= total:
            break
    if total is not None and len(rows) != total:
        raise SystemExit(f"{table}: 抓到 {len(rows)} 行 ≠ server total {total}")
    return rows


# ── 指标 ──────────────────────────────────────────────────────────────────────
def metrics(nav: pd.Series, year_basis: float = YEAR_BASIS) -> dict:
    nav = nav.dropna()
    if len(nav) < 3:
        return {"n_days": int(len(nav))}
    r = nav.pct_change().dropna()
    yrs = (nav.index[-1] - nav.index[0]).days / year_basis
    total = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / yrs) - 1.0) if yrs > 0 else None
    vol = float(r.std(ddof=1) * math.sqrt(year_basis)) if len(r) > 1 else None
    dd = nav / nav.cummax() - 1.0
    maxdd = float(dd.min())
    calmar = float(cagr / abs(maxdd)) if (cagr is not None and maxdd < 0) else None
    m = r.groupby([r.index.year, r.index.month]).apply(lambda x: float((1 + x).prod() - 1.0))
    worst_m = float(m.min()) if len(m) else None
    worst_mk = f"{int(m.idxmin()[0])}-{int(m.idxmin()[1]):02d}" if len(m) else None
    return {"n_days": int(len(nav)), "first": nav.index[0].date().isoformat(),
            "last": nav.index[-1].date().isoformat(), "years": round(yrs, 3),
            "total_return": round(total, 6), "cagr": round(cagr, 6) if cagr is not None else None,
            "vol_ann": round(vol, 6) if vol is not None else None,
            "max_drawdown": round(maxdd, 6), "calmar": round(calmar, 4) if calmar is not None else None,
            "worst_month": round(worst_m, 6) if worst_m is not None else None,
            "worst_month_key": worst_mk}


def yearly(nav: pd.Series) -> dict:
    """逐年收益:上一年最后一个净值做基数;第一年(残年)用窗口起点净值(=1)。"""
    nav = nav.dropna()
    ye = nav.groupby(nav.index.year).last()
    out, prev = {}, float(nav.iloc[0])
    for y in ye.index:
        v = float(ye.loc[y])
        out[str(y)] = round(v / prev - 1.0, 6)
        prev = v
    return out


# ── 取数:腿 / ① / 现金 ────────────────────────────────────────────────────────
def load_legs() -> dict:
    out = {}

    # ①:cap_pit24 的日 ret → NAV
    cv = fetch("core_variants_daily", "select=d,ret&arm=eq.cap_pit24", "d.asc")
    rets = {pd.Timestamp(str(r["d"])[:10]): float(r["ret"]) for r in cv if r.get("ret") is not None}
    s = pd.Series(rets).sort_index()
    out["core_ret"] = s
    out["core_nav"] = (1.0 + s).cumprod()

    # equity / gold(eodhd 日收盘)
    tf = fetch("ohlcv_daily", "select=trade_date,symbol,close&source=eq.eodhd"
                             "&symbol=in.(ACWI,XAUUSD)", "symbol.asc,trade_date.asc")
    eq, gd = {}, {}
    for r in tf:
        c = r.get("close")
        if c is None:
            continue
        (eq if r["symbol"] == "ACWI" else gd)[pd.Timestamp(r["trade_date"])] = float(c)
    out["equity"] = pd.Series(eq).sort_index()
    out["gold"] = pd.Series(gd).sort_index()

    # 资金费(BTC 永续,年化)—— X1V 腿要
    fh = fetch("funding_history", "select=funding_time,funding_rate&venue=eq.binance_perp"
                                  "&symbol=eq.BTC", "funding_time.asc")
    fdf = pd.DataFrame(fh)
    fdf["d"] = pd.to_datetime(fdf["funding_time"].str[:10])
    out["funding"] = fdf.groupby("d")["funding_rate"].sum().astype(float) * 365.0
    return out


def load_cash() -> tuple[pd.Series, dict]:
    """`stable_lend_apy_7d` ÷ 100 ÷ 365,逐日历日;2023-02-10 之前记 0。

    注:PostgREST 对 `f->>'stable_lend_apy_7d'` 的**过滤**(`not.is.null`)返回 0 行,
    且返回列名带引号(`"'stable_lend_apy_7d'"`)⇒ 直接取整列 `f` 在 Python 里挑键。
    """
    rows = fetch("feature_matrix_daily", "select=d,f", "d.asc")
    apy = {}
    for r in rows:
        f = r.get("f") or {}
        v = f.get("stable_lend_apy_7d", f.get("'stable_lend_apy_7d'"))
        if v is not None:
            apy[pd.Timestamp(str(r["d"])[:10])] = float(v)
    s = pd.Series(apy).sort_index()
    diag = {"n_rows_with_apy": len(s), "first": s.index[0].date().isoformat() if len(s) else None,
            "last": s.index[-1].date().isoformat() if len(s) else None,
            "median_apy": round(float(s.median()), 6) if len(s) else None,
            "min_apy": round(float(s.min()), 6) if len(s) else None,
            "max_apy": round(float(s.max()), 6) if len(s) else None,
            "pct_of_days_with_apy": round(len(s) / max(1, (pd.Timestamp(s.index[-1]) - pd.Timestamp(s.index[0])).days + 1), 4) if len(s) else None}
    return s, diag


def crypto_leg(cnav: pd.Series, fund: pd.Series) -> tuple[pd.Series, pd.Series]:
    """CORE_X1V 规则作用于 ① 的 NAV ⇒ 加密腿。核与 lane-b T-331 一字不改。"""
    key, bear, size, exit_mode, vol = FB.TOM_ARMS["CORE_X1V"]
    assert key == "CORE" and bear == "rally" and exit_mode == "l20" and vol is True
    g = TOM.trade_path(cnav, bear, size, exit_mode, vol)
    cr = TOM.trade_returns(cnav, g, fund)
    leg = pd.Series((1.0 + cr).cumprod(), index=cr.index)
    leg = pd.concat([pd.Series({cnav.index[0]: 1.0}), leg]).sort_index()
    return leg, g


# ── 叠加(R-v2):t197 的票 → t251 的 simulate ───────────────────────────────────
def load_tickets() -> list[dict]:
    d = json.load(open(T197_JSON))
    tk = d["tickets"]["A"]
    return tk, d


def load_um_bars(need: set[str]) -> dict:
    bars = {}
    with open(UM_FILE) as f:
        for line in f:
            x = json.loads(line)
            s = x["symbol"]
            if s not in need:
                continue
            rows = sorted({tuple(b) for b in x["bars"] if len(b) >= 6 and b[4] > 0})
            if rows:
                bars[s] = [list(r) for r in rows]
    return bars


def _sma20(closes: list[float]) -> list[float]:
    """T-159 `indicators` 的 `sma20` = `win(c, i, 0, 19) or c[i]` = 近 20 日均(含当日)。
    这里用前缀和写成 O(n)(t159 的 `wmax(c, i, 365, 0)` 是 O(n×365),全宇宙跑不动)。"""
    pre = [0.0]
    for c in closes:
        pre.append(pre[-1] + c)
    out = []
    for i in range(len(closes)):
        lo = max(0, i - 19)
        out.append((pre[i + 1] - pre[lo]) / (i + 1 - lo))
    return out


def classify_exits(tickets: list[dict], bars: dict) -> tuple[dict, list]:
    """按 T-159 `run_long` 的规则重算每张票的出场原因(止损 / 破 SMA20 / 到期 / 仍开着),
    并与 t197 存的 `exit_d` / `exit_px` 逐张对表 —— 对不上就是我的重算错了。"""
    cache, out, bad = {}, {}, []
    for t in tickets:
        sym = t["symbol"]
        rows = bars.get(sym)
        if not rows:
            continue
        if sym not in cache:
            cache[sym] = ({r[0]: i for i, r in enumerate(rows)}, _sma20([r[4] for r in rows]))
        idx, sm = cache[sym]
        i, ei = idx.get(t["signal_d"]), idx.get(t["entry_d"])
        if i is None or ei is None:
            continue
        stop = t["stop_px"]
        n = len(rows)
        hi = min(i + 120, n - 1)
        k = None
        for j in range(ei, hi + 1):
            if rows[j][3] <= stop or rows[j][4] < sm[j]:
                k = j
                break
        if k is None:
            if i + 120 > n - 1:                      # 数据先断 ⇒ 票还开着
                reason, ed, ep = "still", None, None
            else:                                    # 120 根到期、当天收盘平
                reason, ed, ep = "time", rows[hi][0], rows[hi][4]
        elif rows[k][3] <= stop:                     # 止损:当天开盘平(跳空则按开盘价)
            reason, ed = "stop", rows[k][0]
            ep = rows[k][1] if (k > ei and rows[k][1] <= stop) else stop
        elif k + 1 <= n - 1:                         # 破 SMA20:次日开盘平
            reason, ed, ep = "sma20", rows[k + 1][0], rows[k + 1][1]
        else:
            reason, ed, ep = "still", None, None
        out[t["signal_d"] + "|" + sym] = (reason, ed, ep)
        if t.get("still"):
            if reason != "still":
                bad.append((sym, t["signal_d"], f"still 但重算 {reason}"))
        else:
            if ed != t["exit_d"] or (ep or 0) != (t["exit_px"] or 0):
                bad.append((sym, t["signal_d"], f"重算 {reason} {ed} {ep} vs t197 {t['exit_d']} {t['exit_px']}"))
    return out, bad


def to_engine_tickets(tickets: list[dict], exits: dict) -> list[dict]:
    """换成 t251 `simulate` 要的字段形状(字段名一致,值来自 t197 + 重算的出场原因)。"""
    out = []
    for t in tickets:
        reason, ed, ep = exits.get(t["signal_d"] + "|" + t["symbol"], (None, None, None))
        out.append(dict(
            tid=f"{t['symbol']}:{t['signal_d']}", symbol=t["symbol"], signal_d=t["signal_d"],
            entry_d=t["entry_d"], exit_d=t["exit_d"], entry_px=t["entry_px"], stop_px=t["stop_px"],
            exit_px=t["exit_px"], exit_reason=reason, r=t.get("r"), filled=True))
    return out


def overlay_series(engine_tickets: list[dict], bars: dict, gate: dict,
                   risk_frac: float, cap_n: int = OVERLAY_CAP_N,
                   gross: float = OVERLAY_GROSS, eq0: float = OVERLAY_EQ0) -> tuple[pd.Series, dict]:
    """跑 t251 的 simulate,取净值曲线的**逐日收益**。第一天的基准 = eq0(引擎自己的起始净值)。"""
    res = T251.simulate(engine_tickets, bars, gate, gross, equity0=eq0,
                         risk_frac=risk_frac, cap_n=cap_n)
    curve = res["curve"]
    if not curve:
        return pd.Series(dtype=float), {"error": "empty curve"}
    ds = [c[0] for c in curve]
    eq = [float(c[1]) for c in curve]
    idx = pd.to_datetime(pd.Series(ds))
    s = pd.Series(eq, index=idx).sort_index()
    ret = s.pct_change()
    ret.iloc[0] = s.iloc[0] / eq0 - 1.0          # 第一天:从 eq0 起算
    st = T251.curve_stats(curve, eq0)
    diag = dict(risk_frac=risk_frac, cap_n=cap_n, gross_cap=gross, equity0=eq0,
                curve_first=ds[0], curve_last=ds[-1], n_days=len(curve),
                taken=len(res["taken"]),
                blocked_gross=len(res["blocked_gross"]),
                blocked_cap=len(res["blocked_cap"]),
                blocked_min=len(res["blocked_min"]),
                blocked_coin=len(res["blocked_coin"]),
                overlay_total_return=round(st["total_return"], 6),
                overlay_cagr=round(st["cagr"], 6) if st["cagr"] is not None else None,
                overlay_max_dd=round(st["max_dd"], 6),
                overlay_worst_month=st["worst_month"],
                overlay_worst_month_ret=round(st["worst_month_ret"], 6) if st["worst_month_ret"] is not None else None,
                mean_daily_ret=round(float(ret.mean()), 8),
                ann_vol=round(float(ret.std(ddof=1) * math.sqrt(YEAR_BASIS)), 6))
    return ret, diag


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main() -> int:
    t0 = datetime.now(timezone.utc)
    print("[load] 腿 / ① / 现金 …", flush=True)
    data = load_legs()
    apy, apy_diag = load_cash()
    tickets, t197 = load_tickets()
    need = {t["symbol"] for t in tickets}
    bars = load_um_bars(need)
    exits, bad = classify_exits(tickets, bars)
    engine_tickets = to_engine_tickets(tickets, exits)
    gate = {}                                     # simulate 不用 gate(逐字核对过),照签名传空
    print(f"[tickets] {len(tickets)} 张 / {len(need)} 个币 / bars {len(bars)};出场原因不一致 {len(bad)} 张", flush=True)

    # 叠加:两种 f
    ov_base, ov_base_diag = overlay_series(engine_tickets, bars, gate, F_BASE)
    ov_star, ov_star_diag = overlay_series(engine_tickets, bars, gate, F_STAR)
    # 探索性敏感性:大账户(最小名义 $10 不咬合)下同一份票源的叠加
    ov_big, ov_big_diag = overlay_series(engine_tickets, bars, gate, F_BASE, eq0=1_000_000.0)
    print(f"[overlay] f=0.5% total {ov_base_diag['overlay_total_return']:+.4%} "
          f"mdd {ov_base_diag['overlay_max_dd']:+.4%} | f=1.0% total {ov_star_diag['overlay_total_return']:+.4%}", flush=True)

    # ── 腿与窗口 ──────────────────────────────────────────────────────────────
    cnav_all = data["core_nav"]
    cnav = cnav_all[cnav_all.index >= pd.Timestamp(LEG_FROM)]
    cleg_x1v, gpath = crypto_leg(cnav, data["funding"])
    end = pd.Timestamp(WINDOW_END)

    def cut(d):
        return {k: v[v.index <= end] for k, v in d.items()}

    legs_x1v = cut({"crypto": cleg_x1v, "equity": data["equity"], "gold": data["gold"]})
    legs_hold = cut({"crypto": cnav, "equity": data["equity"], "gold": data["gold"]})
    df = pd.concat(legs_x1v, axis=1).dropna().sort_index()
    common = df.index
    nav_start = common[WARM]
    nav_start_ok = nav_start.date().isoformat() == NAV_START_EXPECT

    # 现金:逐日历日 apy/100/365;2023-02-10 之前 0;日历日全覆盖(ffill 补缺口)
    cal = pd.date_range(common[0], end, freq="D")
    apy_cal = apy.reindex(cal).ffill()
    apy_cal = apy_cal.where(apy_cal.index >= pd.Timestamp(CASH_FIRST), 0.0)
    cash_daily = (apy_cal / 100.0 / 365.0)
    cash_daily.name = "cash_ret"

    # ── 臂 ────────────────────────────────────────────────────────────────────
    def fn_t25(hist, d):
        return dict(FA.BASE_T25)

    def fn_rb(hist, d):
        return FA.rb_weights(hist)

    ARMS = [
        ("L0", "T25 常数、现金 0、无叠加", fn_t25, None, None, legs_x1v),
        ("L1", "L0 + R-v2 叠加(f 0.5%)", fn_t25, None, ov_base, legs_x1v),
        ("L2", "L1 换 RBv2 权重", fn_rb, None, ov_base, legs_x1v),
        ("L3", "L2 + 现金计息", fn_rb, cash_daily, ov_base, legs_x1v),
        ("L4", "L3 把叠加的 f 提到 1.0%", fn_rb, cash_daily, ov_star, legs_x1v),
        ("L3H", "L3 但加密腿直接持有 ①", fn_rb, cash_daily, ov_base, legs_hold),
    ]

    out = {
        "meta": dict(card="T-343", lane="lane-b", ran_utc=t0.isoformat(),
                     spec_source="REFUTATION_LEDGER.md ## S-815(只读原文)",
                     blind_note=("本文件不读 lane-c 的 t342_* / T-342_*;内核用 src/data/universe/flex_alloc.py,"
                                 "叠加引擎用 docs/research/t251_gross_cap.py 的 simulate,票源用 "
                                 "docs/research/t197_results.json 的 tickets.A。"),
                     window=[NAV_START_EXPECT, WINDOW_END],
                     reb=REB, cost_bps=20, warm_common_days=WARM,
                     leg_from=LEG_FROM, cash_rate_first=CASH_FIRST,
                     overlay=dict(ticket_source="docs/research/t197_results.json → tickets.A",
                                  engine="docs/research/t251_gross_cap.py:simulate(未改一字)",
                                  cap_n=OVERLAY_CAP_N, gross_cap=OVERLAY_GROSS,
                                  equity0=OVERLAY_EQ0, f_base=F_BASE, f_star=F_STAR),
                     source_hashes={}),
        "validation": {},
        "window": {},
        "cash": {},
        "overlay": {},
        "arms": {},
        "judgement": {},
    }

    # 校验
    out["validation"] = {
        "nav_start_computed": nav_start.date().isoformat(),
        "nav_start_expected": NAV_START_EXPECT,
        "nav_start_matches": bool(nav_start_ok),
        "n_common_days": int(len(common)),
        "common_first": common[0].date().isoformat(),
        "common_last": common[-1].date().isoformat(),
        "exit_reason_mismatch": len(bad),
        "exit_reason_mismatch_sample": bad[:10],
        "core_first": cnav.index[0].date().isoformat(),
        "core_last": cnav.index[-1].date().isoformat(),
    }
    out["cash"] = dict(apy_diag=apy_diag,
                       rule="stable_lend_apy_7d ÷ 100 ÷ 365,逐日历日;2023-02-10 之前记 0",
                       calendar_days=int(len(cal)),
                       n_nonzero_cash_days=int((cash_daily != 0).sum()),
                       cash_total_compound_2023_to_end=round(float((1 + cash_daily).prod() - 1.0), 6),
                       mean_apy_used=round(float(apy_cal[apy_cal > 0].mean()), 4) if (apy_cal > 0).any() else None)
    out["overlay"] = dict(f_base=ov_base_diag, f_star=ov_star_diag,
                           f_base_big_account=ov_big_diag)

    print(f"[window] 共同日 {len(common)}  记账起点 {nav_start.date()} (期望 {NAV_START_EXPECT})", flush=True)

    # 跑臂
    for name, desc, fn, cash, ov, legs in ARMS:
        nav, log = FA.dynamic_mix_nav(legs, fn, reb=REB, cost=COST, start=nav_start,
                                      cash_ret=cash, overlay_ret=ov)
        m = metrics(nav)
        y = yearly(nav)
        w = pd.DataFrame([{c: r[c] for c in ("crypto", "equity", "gold")} for r in log])
        m["yearly"] = y
        m["weights_mean"] = {c: round(float(w[c].mean()), 4) for c in w.columns}
        m["weights_min"] = {c: round(float(w[c].min()), 4) for c in w.columns}
        m["weights_max"] = {c: round(float(w[c].max()), 4) for c in w.columns}
        m["n_rebalances"] = int(len(log))
        m["cash_share_mean"] = round(float(1 - w.sum(axis=1).mean()), 4)
        out["arms"][name] = dict(desc=desc, metrics=m, weights_log=log[:3] + (["…"] if len(log) > 6 else []) + log[-3:])
        print(f"[{name}] total {m['total_return']:+.4%}  cagr {m['cagr']:+.4%}  mdd {m['max_drawdown']:+.4%}  "
              f"calmar {m['calmar']}  worst_m {m['worst_month']:+.2%}({m['worst_month_key']})", flush=True)

    # ① 自己:同一记账起点、同一终点
    core_w = cnav[(cnav.index >= nav_start) & (cnav.index <= end)]
    cm = metrics(core_w)
    cm["yearly"] = yearly(core_w)
    out["arms"]["CORE_1"] = dict(desc="① 自己(cap_pit24 的 NAV,同一记账起点、同一终点)", metrics=cm)
    print(f"[①] total {cm['total_return']:+.4%}  cagr {cm['cagr']:+.4%}  mdd {cm['max_drawdown']:+.4%}", flush=True)

    # 加密腿敞口(X1V 空仓占比)—— 解释 L3H 的差
    gg = gpath[(gpath.index >= nav_start) & (gpath.index <= end)]
    out["window"]["x1v_exposure"] = dict(
        n_days=int(len(gg)), flat_days=int((gg <= 0).sum()),
        flat_frac=round(float((gg <= 0).mean()), 4),
        over1_days=int((gg > 1).sum()), max_g=round(float(gg.max()), 4))

    # ── 判据 ────────────────────────────────────────────────────────────────
    L1, L3, L4 = out["arms"]["L1"]["metrics"], out["arms"]["L3"]["metrics"], out["arms"]["L4"]["metrics"]
    y1, y3, y4 = L1["yearly"], L3["yearly"], L4["yearly"]
    yrs = sorted(set(y1) | set(y3) | set(y4))
    j3_i = L3["max_drawdown"] >= MDD_LIMIT
    j3_ii = (L3["cagr"] is not None and L1["cagr"] is not None and L3["cagr"] >= L1["cagr"])
    per_year = {y: dict(L1=y1.get(y), L3=y3.get(y), L4=y4.get(y),
                         L3_minus_L1_pp=round((y3.get(y) - y1.get(y)) * 100, 3) if (y3.get(y) is not None and y1.get(y) is not None) else None,
                         L3_ok=bool(y3.get(y) is not None and y1.get(y) is not None and y3.get(y) >= y1.get(y) - YEAR_TOL))
                 for y in yrs}
    j3_iii = all(v["L3_ok"] for k, v in per_year.items() if k != "2021") if per_year else False
    j4_i = L4["max_drawdown"] >= MDD_LIMIT
    out["judgement"] = dict(
        L3=dict(i_maxdd=dict(value=L3["max_drawdown"], limit=MDD_LIMIT, ok=bool(j3_i),
                             text="全窗口最大回撤不深于 −25%"),
                ii_cagr=dict(L3=L3["cagr"], L1=L1["cagr"], ok=bool(j3_ii),
                             text="CAGR ≥ L1"),
                iii_yearly=dict(per_year=per_year, ok=bool(j3_iii),
                                text="逐年收益都 ≥ L1 同年 − 1pp"),
                pass_all=bool(j3_i and j3_ii and j3_iii)),
        L4=dict(i_maxdd=dict(value=L4["max_drawdown"], limit=MDD_LIMIT, ok=bool(j4_i),
                             text="全窗口最大回撤不深于 −25%"),
                pass_all=bool(j4_i)),
    )
    # 各级之间的差(每个开关值多少 pp/年、多少回撤)
    deltas = {}
    names = ["L0", "L1", "L2", "L3", "L4", "L3H", "CORE_1"]
    for a, b in zip(names[:-1], names[1:]):
        A, B = out["arms"][a]["metrics"], out["arms"][b]["metrics"]
        deltas[f"{b}_vs_{a}"] = dict(
            total_pp=round((B["total_return"] - A["total_return"]) * 100, 3),
            cagr_pp=round((B["cagr"] - A["cagr"]) * 100, 3) if (B["cagr"] is not None and A["cagr"] is not None) else None,
            mdd_delta_pp=round((B["max_drawdown"] - A["max_drawdown"]) * 100, 3),
            per_year_pp={y: round((B["yearly"].get(y) - A["yearly"].get(y)) * 100, 3)
                         for y in sorted(set(A["yearly"]) | set(B["yearly"]))
                         if A["yearly"].get(y) is not None and B["yearly"].get(y) is not None})
    out["deltas"] = deltas

    json.dump(out, open(OUT_JSON, "w"), indent=1, default=str)
    print("[out]", OUT_JSON)
    print("[judgement]", json.dumps(out["judgement"]["L3"]["pass_all"]), json.dumps(out["judgement"]["L4"]["pass_all"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
