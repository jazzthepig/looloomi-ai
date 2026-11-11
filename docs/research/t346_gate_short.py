#!/usr/bin/env python3
"""T-346 — S-819 对账与盲复算(lane-b):闸门关着时空大盘(BTC / ETH 永续),s 0.15 / 0.30。

口径来源(只读):
  登记   `REFUTATION_LEDGER.md` 的 `## S-819 —` 登记节(窗口 / 内核 / 腿 / RBv2 / 现金计息 / R-v2 叠加 / 闸门 / 成本 / 判据 (i)–(iv))
  对账   `tasks/T-252.json` 的「定义 C」(majors 指数在 200 日线下 ⇒ 1× BTC 永续空;2020-07-01 起;报 −45.67%)
  装配   自己的 `docs/research/t343_blind.py`(C0 = L3:腿 + 现金计息 + R-v2 叠加;内核 `src/data/universe/flex_alloc.dynamic_mix_nav`)
  闸门   `t310_slots.load_gate()`(= 登记写死的那个,一字不改)
  价格   `s681/_um_daily.jsonl`(Binance UM 永续日收盘) · 资金费 `s681/_um_funding.jsonl`(8 小时资金费)
  对账源 `perp_bv_daily`(BTC 永续收盘)/ `v_funding_daily`(Binance 日资金费)/ `style_index_pit_daily`(majors, cap)—— T-252 用的那三张表

⚠️ 盲性有破口(诚实记录):找登记节时同一次 grep 溢出到了紧邻的「S-819 结果」节,本人读过那段数字。
      本报告的所有数字都由本文件自己算(不引用那段结果),但期望值已知 ⇒ 存在事后偏差风险。
      登记的四条判据、口径、窗口逐条照抄执行,不做任何参数调整。

只读库、不入库、不改 `src/`。用法:`python3 docs/research/t346_gate_short.py` → 写 `docs/research/t346_results.json`
"""
from __future__ import annotations

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
os.environ.setdefault("T156_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t156/")
os.environ.setdefault("T159_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t159/")

from src.data.evaluation import apparatus as AP     # noqa: E402  零分布 / p 值(唯一允许的实现)
from src.data.universe import flex_alloc as FA       # noqa: E402  组合层核

import t310_slots as T310                             # noqa: E402  闸门(登记写死)
import t343_blind as T343                             # noqa: E402  自己的 C0 装配

# ── 登记写死的口径 ────────────────────────────────────────────────────────────
UM = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl"
FUND = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_funding.jsonl"
STYLE = "/Volumes/CometCloudAI/cometcloud-local/research/t156/_style.json"
FLIP_COST = 5e-4          # 登记:闸门状态翻转的那天另扣 5bp × s
S_LIST = [0.15, 0.30]     # 登记两档
FULL_START = "2020-07-01"  # 全史起点
ACC_START = "2021-10-11"   # 登记窗口起点(= C0 记账起点)
T252_END = "2026-11-04"    # T-252 的窗口终点
NULL_ITERS, NULL_SEED = 500, 819

OUT_JSON = HERE / "t346_results.json"
OUT_MD = HERE / "T-346_blind_gate_short.md"
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t346_account_cache.pkl")

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出")
URL = URL.rstrip("/")


# ── 读库(分页 ≤1000 行 / 页,必带 order=,核总行数)─────────────────────────────
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


# ── 本地文件:Binance UM 永续日线 / 8 小时资金费 ───────────────────────────────
def load_um(need=("BTC", "ETH")) -> tuple[dict, dict]:
    px, fund = {}, {}
    with open(UM) as f:
        for line in f:
            x = json.loads(line)
            s = x["symbol"]
            if s in need:
                rows = sorted({tuple(b) for b in x["bars"] if len(b) >= 5 and b[4]})
                px[s] = {r[0]: float(r[4]) for r in rows}
    with open(FUND) as f:
        for line in f:
            x = json.loads(line)
            s = x["symbol"]
            if s in need:
                d = defaultdict(float)
                for ts, rate in x["rates"]:
                    d[str(ts)[:10]] += float(rate)
                fund[s] = dict(d)
    return px, fund


def load_style() -> dict:
    rows = json.load(open(STYLE))
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("data") or []
    rows = [r for r in rows if r.get("ret") is not None]
    rows.sort(key=lambda r: r["d"])
    return {r["d"]: float(r["ret"]) for r in rows}


# ── T-252 的三张表(只读) ─────────────────────────────────────────────────────
def load_t252_sources() -> dict:
    px_rows = fetch("perp_bv_daily", "select=d,c,symbol&symbol=eq.BTC", "d.asc")
    px = {str(r["d"])[:10]: float(r["c"]) for r in px_rows if r.get("c") is not None}
    fu_rows = fetch("v_funding_daily", "select=d,funding_rate,symbol&symbol=eq.BTC", "d.asc")
    fu = {str(r["d"])[:10]: float(r["funding_rate"]) for r in fu_rows if r.get("funding_rate") is not None}
    st_rows = fetch("style_index_pit_daily",
                     "select=d,style,weighting,ret,level&style=eq.majors&weighting=eq.cap", "d.asc")
    st = {str(r["d"])[:10]: r for r in st_rows}
    return dict(px=px, fund=fu, style=st,
                px_first=min(px) if px else None, px_last=max(px) if px else None,
                fu_first=min(fu) if fu else None, fu_last=max(fu) if fu else None,
                st_first=min(st) if st else None, st_last=max(st) if st else None,
                n_px=len(px), n_fu=len(fu), n_st=len(st))


# ── 闸门 ─────────────────────────────────────────────────────────────────────
def gate_from_style_rows(rows: dict) -> tuple[np.ndarray, list[str]]:
    """rows: {d: ret} → (gate_closed 数组, 日期列表)。闸门开 = 水平 > 自己的 200 日均(= t310_slots.load_gate 同法)。"""
    ds = sorted(rows)
    lvl, cur = [], 1.0
    for d in ds:
        cur *= (1.0 + rows[d])
        lvl.append(cur)
    closed = []
    for i in range(len(ds)):
        seg = lvl[max(0, i - 199): i + 1]
        sma = sum(seg) / len(seg)
        closed.append(not (len(seg) < 200 or lvl[i] > sma))
    return np.array(closed, dtype=bool), ds


# ── 空头叠加引擎(登记口径)───────────────────────────────────────────────────
def build_short(closed_grid: np.ndarray, grid: pd.DatetimeIndex, pr: np.ndarray,
                fd: np.ndarray, s: float, delay: int = 0, flip_cost: float = FLIP_COST) -> dict:
    """登记:d 日的空头叠加收益(占账户净值)= 若 gate[d−1] 关:−s×(r_BTC,d + r_ETH,d)/2 + s×(当日 8h 资金费之和)/2;
    闸门状态翻转的那天另扣 5bp × s。delay = 持仓整体晚 N 天。

    pr[i] = 当日价格收益(等权腿平均)· fd[i] = 当日资金费合计(等权腿平均)· closed_grid[i] = gate 在 i 日是否关
    """
    n = len(grid)
    active = np.zeros(n, dtype=bool)
    for i in range(n):
        j = i - 1 - delay
        if j >= 0 and closed_grid[j]:
            active[i] = True
    prev = np.concatenate([[False], active[:-1]])
    flip = active != prev
    price = np.where(active, -s * pr, 0.0)
    funding = np.where(active, s * fd, 0.0)
    cost = np.where(flip, -flip_cost * s, 0.0)
    total = price + funding + cost
    return dict(active=active, flip=flip, price=price, funding=funding, cost=cost, total=total,
                n_flips=int(flip.sum()))


def series_total(total: np.ndarray, grid: pd.DatetimeIndex, win: tuple[str, str]) -> float:
    m = (grid >= pd.Timestamp(win[0])) & (grid <= pd.Timestamp(win[1]))
    return float(np.prod(1.0 + total[m]) - 1.0)


def seg_stats(sh: dict, grid: pd.DatetimeIndex, win: tuple[str, str], min_days: int = 10) -> list[dict]:
    m = (grid >= pd.Timestamp(win[0])) & (grid <= pd.Timestamp(win[1]))
    act, tot = sh["active"][m], sh["total"][m]
    ds = [d.strftime("%Y-%m-%d") for d in grid[m]]
    out, i, n = [], 0, len(ds)
    while i < n:
        if act[i]:
            j = i
            while j + 1 < n and act[j + 1]:
                j += 1
            days = j - i + 1
            seg_tot = float(np.prod(1.0 + tot[i:j + 1]) - 1.0)
            seg_price = float(np.prod(1.0 + sh["price"][m][i:j + 1]) - 1.0)
            seg_fund = float(np.prod(1.0 + sh["funding"][m][i:j + 1]) - 1.0)
            out.append(dict(start=ds[i], end=ds[j], days=days, pnl=round(seg_tot, 6),
                            pnl_price_only=round(seg_price, 6), pnl_funding_only=round(seg_fund, 6),
                            pnl_ex_cost=round(float(np.prod(1.0 + (sh["price"][m] + sh["funding"][m])[i:j + 1]) - 1.0), 6)))
            i = j + 1
        else:
            i += 1
    return [s for s in out if s["days"] >= min_days], len(out)


def yearly_from(total: np.ndarray, grid: pd.DatetimeIndex, win: tuple[str, str]) -> dict:
    m = (grid >= pd.Timestamp(win[0])) & (grid <= pd.Timestamp(win[1]))
    idx = grid[m]
    r = total[m]
    s = pd.Series(np.cumprod(1.0 + r), index=idx)
    ye = s.groupby(s.index.year).last()
    out, prev = {}, float(1.0)
    for y in ye.index:
        out[str(y)] = round(float(ye.loc[y]) / prev - 1.0, 6)
        prev = float(ye.loc[y])
    return out


# ── 账户口径(C0 = L3)────────────────────────────────────────────────────────
def load_account_parts() -> dict:
    if CACHE.exists():
        d = pd.read_pickle(CACHE)
        d["from_cache"] = True
        return d
    print("[acct] 装配 C0(腿 / 现金计息 / R-v2 叠加)…", flush=True)
    data = T343.load_legs()
    apy, apy_diag = T343.load_cash()
    tickets, _ = T343.load_tickets()
    need = {t["symbol"] for t in tickets}
    bars = T343.load_um_bars(need)
    exits, bad = T343.classify_exits(tickets, bars)
    et = T343.to_engine_tickets(tickets, exits)
    ov_base, ov_diag = T343.overlay_series(et, bars, {}, T343.F_BASE)
    cnav = data["core_nav"]
    cnav = cnav[cnav.index >= pd.Timestamp(T343.LEG_FROM)]
    cleg, gpath = T343.crypto_leg(cnav, data["funding"])
    end = pd.Timestamp(T343.WINDOW_END)
    legs = {k: v[v.index <= end] for k, v in
            {"crypto": cleg, "equity": data["equity"], "gold": data["gold"]}.items()}
    df = pd.concat(legs, axis=1).dropna().sort_index()
    common = df.index
    nav_start = common[T343.WARM]
    cal = pd.date_range(common[0], end, freq="D")
    apy_cal = apy.reindex(cal).ffill()
    apy_cal = apy_cal.where(apy_cal.index >= pd.Timestamp(T343.CASH_FIRST), 0.0)
    cash = apy_cal / 100.0 / 365.0
    d = dict(legs=legs, cash=cash, nav_start=nav_start, ov_base=ov_base, ov_diag=ov_diag,
             exit_mismatch=len(bad), n_common=int(len(common)),
             common_first=common[0].strftime("%Y-%m-%d"), common_last=common[-1].strftime("%Y-%m-%d"),
             nav_start_str=nav_start.strftime("%Y-%m-%d"), apy_diag=apy_diag)
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        pd.to_pickle(d, CACHE)
        d["cache_written"] = str(CACHE)
    except Exception as e:  # noqa: BLE001
        d["cache_error"] = str(e)[:200]
    return d


def account_nav(parts: dict, overlay: pd.Series) -> pd.Series:
    nav, _log = FA.dynamic_mix_nav(parts["legs"], lambda h, _d: FA.rb_weights(h), reb=21, cost=20 / 1e4,
                                  start=parts["nav_start"], cash_ret=parts["cash"], overlay_ret=overlay)
    return nav


def longest_uw(nav: pd.Series) -> dict:
    nav = nav.dropna()
    uw = nav < nav.cummax()
    best = dict(days=0, start=None, end=None)
    i, n = 0, len(nav)
    while i < n:
        if bool(uw.iloc[i]):
            j = i
            while j + 1 < n and bool(uw.iloc[j + 1]):
                j += 1
            if (j - i + 1) > best["days"]:
                best = dict(days=int(j - i + 1), start=nav.index[i].strftime("%Y-%m-%d"),
                            end=nav.index[j].strftime("%Y-%m-%d"),
                            min_nav=round(float(nav.iloc[i:j + 1].min()), 6))
            i = j + 1
        else:
            i += 1
    return best


def acc_metrics(nav: pd.Series) -> dict:
    nav = nav.dropna()
    r = nav.pct_change().dropna()
    yrs = (nav.index[-1] - nav.index[0]).days / 365.0
    total = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / yrs) - 1.0) if yrs > 0 else None
    dd = nav / nav.cummax() - 1.0
    out = dict(n_days=int(len(nav)), first=nav.index[0].strftime("%Y-%m-%d"), last=nav.index[-1].strftime("%Y-%m-%d"),
               years=round(yrs, 3), total_return=round(total, 6),
               cagr=round(cagr, 6) if cagr is not None else None,
               max_drawdown=round(float(dd.min()), 6),
               vol_ann=round(float(r.std(ddof=1) * math.sqrt(365.0)), 6) if len(r) > 1 else None)
    ye = nav.groupby(nav.index.year).last()
    y, prev = {}, float(nav.iloc[0])
    for yy in ye.index:
        v = float(ye.loc[yy])
        y[str(yy)] = round(v / prev - 1.0, 6)
        prev = v
    out["yearly"] = y
    out["longest_underwater"] = longest_uw(nav)
    return out


# ── 主流程 ───────────────────────────────────────────────────────────────────
def main() -> int:
    t0 = datetime.now(timezone.utc)
    print("[start]", t0.isoformat(), flush=True)
    res = {"meta": dict(card="T-346", lane="lane-b", ran_utc=t0.isoformat(),
                        spec_source="REFUTATION_LEDGER.md ## S-819 登记节(只读)",
                        blind_caveat=("找登记节时同一次 grep 溢出到「S-819 结果」节,本人读过那段数字;"
                                      "本文件全部数字自算、不引用它,但期望值已知 ⇒ 存在事后偏差风险。"),
                        flip_cost_bp=5, s_list=S_LIST, full_start=FULL_START, acc_start=ACC_START,
                        null_iters=NULL_ITERS, null_seed=NULL_SEED,
                        price_src=UM, funding_src=FUND, gate_src="t310_slots.load_gate()")}

    # ── 1. 数据与闸门 ───────────────────────────────────────────────────────
    gate, lvl, gdiag = T310.load_gate()
    style = load_style()
    px, fund = load_um()
    grid = pd.date_range("2020-01-01", "2026-09-30", freq="D")
    gdates = [d.strftime("%Y-%m-%d") for d in grid]
    closed_grid = np.array([(d in gate) and (not gate[d]) for d in gdates], dtype=bool)
    missing_gate = [d for d in gdates if d not in gate]
    res["data"] = dict(gate_diag=gdiag, grid_first=gdates[0], grid_last=gdates[-1], n_grid=len(gdates),
                        missing_gate_days=len(missing_gate),
                        px_first=min(px["BTC"]), px_last=max(px["BTC"]), n_px_btc=len(px["BTC"]),
                        n_px_eth=len(px["ETH"]),
                        fund_first=min(fund["BTC"]), fund_last=max(fund["BTC"]),
                        gate_closed_days=int(closed_grid.sum()),
                        gate_flips=int((np.concatenate([[False], closed_grid[:-1]]) != closed_grid).sum()))
    print(f"[data] grid {len(gdates)} 天,gate 关 {int(closed_grid.sum())} 天,翻转 {res['data']['gate_flips']}", flush=True)

    # ── 2. 日期对齐自检(majors 指数 d 日收益 vs BTC 永续 d 日收益)───────────
    sr = pd.Series(style)
    btc_close = pd.Series(px["BTC"]).sort_index()
    btc_ret = btc_close.pct_change()
    al = pd.concat([sr.rename("majors"), btc_ret.rename("btc")], axis=1).dropna()
    def _corr(a, b):
        x = pd.concat([a, b], axis=1).dropna()
        return round(float(x.iloc[:, 0].corr(x.iloc[:, 1])), 4) if len(x) > 3 else None
    align = dict(n=int(len(al)),
                 corr_d0=_corr(al["majors"], al["btc"]),
                 corr_d_plus1=_corr(al["majors"], al["btc"].shift(-1)),
                 corr_d_minus1=_corr(al["majors"], al["btc"].shift(1)),
                 note="majors ret[d] 对 BTC 永续 ret[d] / ret[d±1];d+1 接近 0 ⇒ 没有前视")
    res["alignment"] = align
    print(f"[align] d {align['corr_d0']}  d+1 {align['corr_d_plus1']}  d-1 {align['corr_d_minus1']}", flush=True)

    # ── 3. 腿的日收益 / 资金费(等权平均)────────────────────────────────────
    def leg_arrays(legs):
        prs, fds = [], []
        for i in range(len(grid)):
            d, p = gdates[i], gdates[i - 1] if i > 0 else None
            vals = [px[s][d] / px[s][p] - 1.0 for s in legs if p and px[s].get(d) and px[s].get(p)]
            prs.append(float(np.mean(vals)) if len(vals) == len(legs) else 0.0)
            fds.append(float(np.mean([fund[s].get(d, 0.0) for s in legs])))
        return np.array(prs), np.array(fds)

    PR_BE, FD_BE = leg_arrays(("BTC", "ETH"))
    PR_B, FD_B = leg_arrays(("BTC",))

    # ── 4. T-252 定义 C 的对账(同一条规则 / BTC / 1 倍 / 2020-07-01 起)────
    t252 = load_t252_sources()
    res["t252_sources"] = {k: v for k, v in t252.items() if k not in ("px", "fund", "style")}
    # 闸门等价性:t156/_style.json 的 majors vs 库里的 style_index_pit_daily(majors, cap)
    st = t252["style"]
    eq = dict(n_common=0, n_diff=0, sample_diff=[])
    if st:
        st_sorted = sorted(st)
        lvl2, cur = [], 1.0
        for d in st_sorted:
            r = st[d].get("ret")
            if r is None:
                continue
            cur *= (1.0 + float(r))
            lvl2.append((d, cur))
        closed2 = []
        for i, (d, lv) in enumerate(lvl2):
            seg = [x[1] for x in lvl2[max(0, i - 199): i + 1]]
            sma = sum(seg) / len(seg)
            closed2.append((d, not (len(seg) < 200 or lv > sma)))
        cm = dict(closed2)
        diff = [(d, cm[d], (d in gate) and not gate[d]) for d in cm if d in gate]
        eq = dict(n_common=len(diff), n_diff=sum(1 for x in diff if x[1] != x[2]),
                  sample_diff=[x for x in diff if x[1] != x[2]][:5],
                  first_diff=next((x[0] for x in diff if x[1] != x[2]), None))
    res["gate_equivalence"] = eq
    print(f"[gate-eq] t156 vs style_index_pit_daily:共同 {eq['n_common']} 天,不同 {eq['n_diff']} 天", flush=True)

    # T-252 口径复刻:价 = perp_bv_daily BTC 收盘,资金费 = v_funding_daily,成本 7.5bp / 次开或关,窗口 2020-07-01→2026-11-04
    def t252_variant(px_src, fu_src, grid2, closed2, cost_per_transition, legs=("BTC",), win=("2020-07-01", T252_END)):
        n = len(grid2)
        gd2 = [d.strftime("%Y-%m-%d") for d in grid2]
        pr = np.zeros(n)
        fd = np.zeros(n)
        valid = np.ones(n, dtype=bool)
        for i in range(n):
            d = gd2[i]
            p = gd2[i - 1] if i > 0 else None
            vals = [px_src[s][d] / px_src[s][p] - 1.0 for s in legs if p and px_src[s].get(d) and px_src[s].get(p)]
            if len(vals) == len(legs):
                pr[i] = float(np.mean(vals))
            else:
                valid[i] = False        # 价缺 ⇒ 当天没有持仓(不静默记 0 收益)
            fd[i] = float(np.mean([fu_src[s].get(d, 0.0) for s in legs]))
        act = np.zeros(n, dtype=bool)
        for i in range(n):
            j = i - 1
            if j >= 0 and closed2[j] and valid[i]:
                act[i] = True
        flip = act != np.concatenate([[False], act[:-1]])
        tot = np.where(act, -pr + fd, 0.0) - np.where(flip, cost_per_transition, 0.0)
        m = (grid2 >= pd.Timestamp(win[0])) & (grid2 <= pd.Timestamp(win[1]))
        return dict(total=round(float(np.prod(1.0 + tot[m]) - 1.0), 6),
                    n_days_active=int(act[m].sum()), n_flips=int(flip[m].sum()),
                    cost_total=round(float(-np.where(flip, cost_per_transition, 0.0)[m].sum()), 6),
                    funding_total=round(float(np.where(act, fd, 0.0)[m].sum()), 6),
                    price_total=round(float(np.prod(1.0 + np.where(act, -pr, 0.0)[m]) - 1.0), 6))

    db_grid = pd.date_range("2020-07-01", T252_END, freq="D")
    # 闸门取 t156 的(t310_slots),在 db_grid 上重建
    db_closed = np.array([(d.strftime("%Y-%m-%d") in gate) and (not gate[d.strftime("%Y-%m-%d")])
                          for d in db_grid], dtype=bool)
    v_t252 = t252_variant({"BTC": t252["px"]}, {"BTC": t252["fund"]}, db_grid, db_closed, 7.5e-4)
    v_t252_5bp = t252_variant({"BTC": t252["px"]}, {"BTC": t252["fund"]}, db_grid, db_closed, 5e-4)
    # s681 源、同一 7.5bp(价格/资金费源换掉;窗口同 V4,只差成本)
    s681_grid = grid
    s681_closed = closed_grid
    v_s681_75bp = t252_variant({"BTC": px["BTC"]}, {"BTC": fund["BTC"]}, s681_grid, s681_closed, 7.5e-4,
                               win=("2020-07-01", "2026-09-30"))
    # s681 源、5bp(= 登记口径),窗口截到 s681 数据末端 2026-09-30
    v_s681_5bp = t252_variant({"BTC": px["BTC"]}, {"BTC": fund["BTC"]}, s681_grid, s681_closed, 5e-4,
                               win=("2020-07-01", "2026-09-30"))
    res["t252_reconciliation"] = dict(
        target_pct=-0.4567, target_note="T-252 定义 C:majors 在 200 日线下 ⇒ 1× BTC 永续空;2020-07-01→2026-11-04;报 −45.67%",
        variants={
            "V1_库源_7.5bp_per_transition(T-252 原口径)": v_t252,
            "V2_库源_5bp_per_transition": v_t252_5bp,
            "V3_s681源_7.5bp_per_transition": v_s681_75bp,
            "V4_s681源_5bp_per_transition(登记口径,窗口截 2026-09-30)": v_s681_5bp,
        })
    print("[t252]", json.dumps({k: v["total"] for k, v in res["t252_reconciliation"]["variants"].items()}), flush=True)

    # ── 5. 全史(2020-07-01 起)的空头叠加:必须报的第零件 ───────────────────
    FULL = (FULL_START, "2026-09-30")
    must = {}
    for label, legs, pr, fd in [("BTC_ETH", ("BTC", "ETH"), PR_BE, FD_BE), ("BTC_only", ("BTC",), PR_B, FD_B)]:
        for s in (1.0, 0.30, 0.15):
            sh = build_short(closed_grid, grid, pr, fd, s)
            segs, n_seg = seg_stats(sh, grid, FULL, min_days=10)
            must[f"{label}_s{s}"] = dict(
                legs=list(legs), s=s, total_return=round(series_total(sh["total"], grid, FULL), 6),
                n_days_active=int(sh["active"][(grid >= pd.Timestamp(FULL[0])) & (grid <= pd.Timestamp(FULL[1]))].sum()),
                n_flips=sh["n_flips"],
                funding_sum=round(float(sh["funding"][(grid >= pd.Timestamp(FULL[0])) & (grid <= pd.Timestamp(FULL[1]))].sum()), 6),
                funding_compound=round(float(np.prod(1.0 + sh["funding"][(grid >= pd.Timestamp(FULL[0])) & (grid <= pd.Timestamp(FULL[1]))]) - 1.0), 6),
                price_compound=round(float(np.prod(1.0 + sh["price"][(grid >= pd.Timestamp(FULL[0])) & (grid <= pd.Timestamp(FULL[1]))]) - 1.0), 6),
                cost_total=round(float(-sh["cost"][(grid >= pd.Timestamp(FULL[0])) & (grid <= pd.Timestamp(FULL[1]))].sum()), 6),
                yearly=yearly_from(sh["total"], grid, FULL),
                segments_ge10=segs, n_segments_all=n_seg)
    res["must_report_full_history"] = must
    print("[full] BTC-only s1.0 total", must["BTC_only_s1.0"]["total_return"], flush=True)

    # ── 6. 账户(C0 = L3 + 空头叠加)────────────────────────────────────────
    parts = load_account_parts()
    ov_base = parts["ov_base"]
    ov_base = ov_base[~ov_base.index.duplicated(keep="last")]
    print(f"[acct] nav_start {parts['nav_start_str']} common {parts['common_first']}→{parts['common_last']}", flush=True)

    def short_series(legs, s, delay=0, s681_grid_only=True):
        pr, fd = (PR_BE, FD_BE) if legs == ("BTC", "ETH") else (PR_B, FD_B)
        sh = build_short(closed_grid, grid, pr, fd, s, delay=delay)
        return sh

    ACC_WIN = (ACC_START, "2026-09-30")     # 主口径:短腿数据到 2026-09-30 为止,账户截到同一天
    acct = {}
    nav_c0_full = account_nav(parts, ov_base)
    acct["C0_full_window"] = acc_metrics(nav_c0_full)
    nav_c0 = nav_c0_full[(nav_c0_full.index >= pd.Timestamp(ACC_START)) & (nav_c0_full.index <= pd.Timestamp("2026-09-30"))]
    acct["C0"] = acc_metrics(nav_c0)
    for s in S_LIST:
        sh = short_series(("BTC", "ETH"), s)
        srs = pd.Series(sh["total"], index=grid)
        ov_tot = ov_base.add(srs, fill_value=0.0)
        nav = account_nav(parts, ov_tot)
        nav = nav[(nav.index >= pd.Timestamp(ACC_START)) & (nav.index <= pd.Timestamp("2026-09-30"))]
        acct[f"C0_plus_short_s{s}"] = acc_metrics(nav)
        # 参考:全记账窗(短腿 2026-09-30 后无数据 ⇒ 记 0,单独标注)
        nav_full = account_nav(parts, ov_tot)
        acct[f"C0_plus_short_s{s}_full_window_tail0"] = acc_metrics(nav_full)
        # 空头叠加自身(登记窗口)
        acct[f"short_s{s}_window"] = dict(
            total_return=round(series_total(sh["total"], grid, ACC_WIN), 6),
            yearly=yearly_from(sh["total"], grid, ACC_WIN),
            n_flips=sh["n_flips"],
            n_days_active=int(sh["active"][(grid >= pd.Timestamp(ACC_WIN[0])) & (grid <= pd.Timestamp(ACC_WIN[1]))].sum()))
    res["account"] = acct

    # ── 7. 零分布(apparatus.circular_shift, block 1, 500 次, seed 819)──────
    nulls = {}
    for s in S_LIST:
        pr, fd = PR_BE, FD_BE
        # 主口径:整条闸门序列(全网格)循环平移 ⇒ 重算整条空头叠加 ⇒ 取登记窗口的总收益
        rng = np.random.default_rng(NULL_SEED)
        null = []
        for _ in range(NULL_ITERS):
            sh_closed = AP.circular_shift(closed_grid, rng, block=1)
            sh = build_short(sh_closed, grid, pr, fd, s)
            null.append(series_total(sh["total"], grid, ACC_WIN))
        actual = series_total(build_short(closed_grid, grid, pr, fd, s)["total"], grid, ACC_WIN)
        arr = np.array(null, dtype=float)
        # 另算:只平移登记窗口内那段闸门(窗口自环),作对照口径
        wm = (grid >= pd.Timestamp(ACC_WIN[0])) & (grid <= pd.Timestamp(ACC_WIN[1]))
        wseq = closed_grid[wm]
        rng2 = np.random.default_rng(NULL_SEED)
        null2 = []
        for _ in range(NULL_ITERS):
            wsh = AP.circular_shift(wseq, rng2, block=1)
            act = np.concatenate([wsh[-1:], wsh[:-1]])
            flip = act != np.concatenate([[False], act[:-1]])
            tot = np.where(act, -s * pr[wm] + s * fd[wm], 0.0) - np.where(flip, FLIP_COST * s, 0.0)
            null2.append(float(np.prod(1.0 + tot) - 1.0))
        arr2 = np.array(null2, dtype=float)
        key = f"s{s:.2f}"
        nulls[key] = dict(actual=round(actual, 6),
                          null_median=round(float(np.median(arr)), 6),
                          null_mean=round(float(arr.mean()), 6),
                          null_p05=round(float(np.percentile(arr, 5)), 6),
                          null_p95=round(float(np.percentile(arr, 95)), 6),
                          p_upper=round(float(AP.p_upper(actual, arr)), 6),
                          percentile_of=round(float(AP.percentile_of(actual, arr)), 6),
                          n=len(arr),
                          variant_window_only=dict(actual=round(actual, 6),
                                                   null_median=round(float(np.median(arr2)), 6),
                                                   p_upper=round(float(AP.p_upper(actual, arr2)), 6),
                                                   percentile_of=round(float(AP.percentile_of(actual, arr2)), 6)))
        print(f"[null] {key}: actual {actual:+.4%} median {np.median(arr):+.4%} "
              f"p_upper {nulls[key]['p_upper']} (窗口内平移 p {nulls[key]['variant_window_only']['p_upper']})", flush=True)
    res["null_distribution"] = nulls

    # ── 8. 判据 (i)–(iv)逐档判 ────────────────────────────────────────────
    jud = {}
    for s in S_LIST:
        a = acct[f"C0_plus_short_s{s}"]
        c0 = acct["C0"]
        sh = short_series(("BTC", "ETH"), s)
        segs, n_seg = seg_stats(sh, grid, ACC_WIN, min_days=10)
        yrs = sh["yearly"] if "yearly" in sh else yearly_from(sh["total"], grid, ACC_WIN)
        yrs = yearly_from(sh["total"], grid, ACC_WIN)
        pos_years = [y for y, v in yrs.items() if v is not None and v > 0]
        pos_segs = [x for x in segs if x["pnl"] > 0]
        d_cagr = (a["cagr"] - c0["cagr"]) if (a["cagr"] is not None and c0["cagr"] is not None) else None
        d_uw = c0["longest_underwater"]["days"] - a["longest_underwater"]["days"]
        nd = nulls[f"s{s:.2f}"]
        jud[f"s{s}"] = dict(
            i_longest_uw=dict(c0_days=c0["longest_underwater"]["days"], new_days=a["longest_underwater"]["days"],
                              shorter_by_days=int(d_uw), need_ge_60=bool(d_uw >= 60),
                              text="最长水下比 C0 短 ≥ 60 天", ok=bool(d_uw >= 60)),
            ii_cagr=dict(c0=c0["cagr"], new=a["cagr"], delta_pp=None if d_cagr is None else round(d_cagr * 100, 3),
                         text="CAGR ≥ C0 − 1.0pp / 年", ok=bool(d_cagr is not None and d_cagr >= -0.01)),
            iii_not_one_regime=dict(yearly=yrs, n_positive_years=len(pos_years), positive_years=pos_years,
                                     n_segments_ge10=len(segs), n_segments_positive=len(pos_segs),
                                     segments=segs, text="≥2 个日历年为正,且 ≥10 天的闸门关闭段过半为正",
                                     ok=bool(len(pos_years) >= 2 and len(pos_segs) * 2 > len(segs))),
            iv_p_upper=dict(p_upper=nd["p_upper"], need_lt=0.10, ok=bool(nd["p_upper"] < 0.10),
                            actual=nd["actual"], null_median=nd["null_median"]),
            pass_all=bool(d_uw >= 60 and d_cagr is not None and d_cagr >= -0.01
                          and len(pos_years) >= 2 and len(pos_segs) * 2 > len(segs)
                          and nd["p_upper"] < 0.10))
        res.setdefault("judgement", {})[f"s{s}"] = jud[f"s{s}"]

    # ── 9. 只报不判的三件 ──────────────────────────────────────────────────
    only_report = {}
    # ① 持仓整体晚 1/2/3 天
    d1 = {}
    for delay in (0, 1, 2, 3):
        row = {}
        for s in S_LIST:
            sh = short_series(("BTC", "ETH"), s, delay=delay)
            ov_tot = ov_base.add(pd.Series(sh["total"], index=grid), fill_value=0.0)
            nav = account_nav(parts, ov_tot)
            nav = nav[(nav.index >= pd.Timestamp(ACC_START)) & (nav.index <= pd.Timestamp("2026-09-30"))]
            row[f"s{s}"] = dict(short_total=round(series_total(sh["total"], grid, ACC_WIN), 6),
                                account_longest_uw=longest_uw(nav), account_total=acc_metrics(nav)["total_return"])
        d1[f"delay_{delay}d"] = row
    only_report["delay_1_2_3_days"] = d1

    # ② 去掉 2022-01 → 2023-01 那一段
    drop = {}
    for s in S_LIST:
        sh = short_series(("BTC", "ETH"), s)
        tot = np.array(sh["total"], copy=True)
        m = (grid >= pd.Timestamp("2022-01-01")) & (grid <= pd.Timestamp("2022-12-31"))
        tot[m] = 0.0
        row = dict(window_ACC_total_without_2022=round(series_total(tot, grid, ACC_WIN), 6),
                   window_FULL_total_without_2022=round(series_total(tot, grid, FULL), 6),
                   window_ACC_total_with_2022=round(series_total(sh["total"], grid, ACC_WIN), 6),
                   window_FULL_total_with_2022=round(series_total(sh["total"], grid, FULL), 6))
        # 另一种读法:窗口截到 2022-01-01 之前
        row["window_FULL_total_truncated_at_2022_01"] = round(series_total(sh["total"], grid, (FULL_START, "2021-12-31")), 6)
        drop[f"s{s}"] = row
    only_report["drop_2022_segment"] = drop

    # ③ 空的换成只空 BTC
    btc_only = {}
    for s in (1.0, 0.30, 0.15):
        sh = build_short(closed_grid, grid, PR_B, FD_B, s)
        segs, n_seg = seg_stats(sh, grid, FULL, min_days=10)
        ov_tot = ov_base.add(pd.Series(sh["total"], index=grid), fill_value=0.0)
        nav = account_nav(parts, ov_tot)
        nav = nav[(nav.index >= pd.Timestamp(ACC_START)) & (nav.index <= pd.Timestamp("2026-09-30"))]
        btc_only[f"s{s}"] = dict(
            total_FULL=round(series_total(sh["total"], grid, FULL), 6),
            total_ACC=round(series_total(sh["total"], grid, ACC_WIN), 6),
            yearly_FULL=yearly_from(sh["total"], grid, FULL),
            segments_FULL_ge10=segs,
            account_LONGEST_UW=longest_uw(nav),
            account_total=acc_metrics(nav)["total_return"],
            n_flips=sh["n_flips"])
    only_report["btc_only"] = btc_only
    res["only_report"] = only_report

    res["account_parts"] = dict(nav_start=parts["nav_start_str"], common_first=parts["common_first"],
                                common_last=parts["common_last"], exit_reason_mismatch=parts["exit_mismatch"],
                                ov_diag=parts["ov_diag"], from_cache=parts.get("from_cache", False))
    json.dump(res, open(OUT_JSON, "w"), indent=1, default=str)
    print("[out]", OUT_JSON, flush=True)
    print("[done]", datetime.now(timezone.utc).isoformat(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
