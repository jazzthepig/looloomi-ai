#!/usr/bin/env python3
"""T-283 — S-762:S-761 只改出场(交易所挂单式止损 + 资金费 10% 上限),判据 (a)–(e) 一字不改。

改了什么(只有出场):
  ① 止损从「收盘触发、次日开盘出」换成**交易所挂单式止损**:某日 perp_bv_daily 最高价 ≥ 止损价
     ⇒ 当日按 max(止损价, 当日开盘价) 成交(跳空按开盘);
  ② 新增资金费保护:空腿累计付出的资金费 ≥ 名义 10% ⇒ 次日开盘出。
其余(事件 / 进场 / ATR 口径 / 对冲腿 / 成本 / 资金费窗口 / 判据)与 S-761 一字不改。

- 事件:T-282 的 142 个事件原样(docs/research/t283_events.json)
- 价格:perp_bv_daily(Binance USDT 永续日线 o/h/l/c)—— 新规则需要日内最高价 h
- 资金费:funding_history(venue = binance_perp)
- 统计:只用 src/data/evaluation/apparatus.py
- 只算、不改代码、不入库
"""
from __future__ import annotations

import json
import math
import os
import sys
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    long_return,
    null_distribution,
    percentile_of,
    random_dates_like,
    short_return,
)

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
SESSION = requests.Session()

RESEARCH = Path("/Volumes/CometCloudAI/cometcloud-local/research")
CACHE = RESEARCH / "t282_cache"      # 复用 T-282 的缓存(同一批价格/资金费,只改出场)
CACHE.mkdir(parents=True, exist_ok=True)
OUT = Path(__file__).resolve().parent

# ── 台账 S-762 写死的参数(除出场外与 S-761 完全相同)──────────────────────────
SEED = 762
N_ROUNDS = 200          # (c) 对照:随机日 200 轮
HOLD = 30               # 持有 30 根日线
STOP_ATR = 2.5          # 2.5 ATR 止损
TAKER = 0.0005          # taker 5bp(每腿每边)
SLIP_NEW = 0.0005       # 滑点 5bp(新币)
SLIP_BTC = 0.0002       # 滑点 2bp(BTC)
COST_TOK = TAKER + SLIP_NEW   # 10bp 每边
COST_BTC = TAKER + SLIP_BTC   # 7bp 每边
CTRL_LO, CTRL_HI = 90, 365    # 对照窗口 [d+90, d+365]
PRE = 15                # 回看(前一根收盘 → TR)
POST = 400              # 事件后拉多少天
ATR_N = 14
FUND_CAP = 0.10         # 资金费保护:空腿累计付出 ≥ 名义 10%
FUND_MODE = "gross"     # 累计付出 = Σ max(0, −rate)(字面读法);net 读法作副项

CFG_MAIN = {"hold": HOLD, "stop_atr": STOP_ATR, "hedge": True}

# S-761 的参照数(用 ticket_v1 复算时要对上,说明继承没走样)
S761_REF = {"n_tickets": 131, "mean_pct": 9.96, "median_pct": 16.33, "worst5_mean_pct": -81.23}


# ── 取数 ────────────────────────────────────────────────────────────────────
def paged(table: str, q: str) -> list[dict]:
    rows: list[dict] = []
    off, total = 0, -1
    while True:
        r = SESSION.get(f"{URL}/rest/v1/{table}?{q}", headers={**H, "Prefer": "count=exact"},
                        params={"limit": 1000, "offset": off}, timeout=300)
        if r.status_code not in (200, 206):
            raise RuntimeError(f"{table}: HTTP {r.status_code} {r.text[:200]}")
        body = r.json()
        rows.extend(body)
        cr = r.headers.get("content-range", "")
        if "/" in cr:
            total = int(cr.split("/")[-1])
        off += len(body)
        if not body or total < 0 or off >= total:
            break
    return rows


def cached(table: str, sym: str, dcol: str, lo: str, hi: str, select: str) -> list[dict]:
    p = CACHE / f"{table}_{sym}_{lo}_{hi}.json".replace(":", "-")
    if p.exists():
        return json.loads(p.read_text())
    extra = "&venue=eq.binance_perp" if table == "funding_history" else ""
    q = (f"select={select}&symbol=eq.{sym}&{dcol}=gte.{lo}&{dcol}=lte.{hi}{extra}"
         f"&order={dcol}.asc")
    rows = paged(table, q)
    p.write_text(json.dumps(rows))
    print(f"  pulled {table} {sym} [{lo},{hi}]: {len(rows)}", flush=True)
    return rows


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


class Series:
    """日线序列(dates 升序)。"""

    def __init__(self, rows: list[dict]):
        rows = [r for r in rows if r.get("d")]
        rows.sort(key=lambda r: r["d"])
        self.dates = [r["d"] for r in rows]
        self.o = [num(r.get("o")) for r in rows]
        self.h = [num(r.get("h")) for r in rows]
        self.l = [num(r.get("l")) for r in rows]
        self.c = [num(r.get("c")) for r in rows]
        self.idx = {d: i for i, d in enumerate(self.dates)}

    def __len__(self):
        return len(self.dates)


class Funding:
    """funding_history(binance_perp)按时间排序 + 前缀和。

    pre      : Σ rate(净)
    pre_paid : Σ max(0, −rate)(空腿「累计付出」的字面读法)
    """

    def __init__(self, rows: list[dict]):
        pts = []
        for r in rows:
            if r.get("funding_rate") is None or not r.get("funding_time"):
                continue
            try:
                t = datetime.fromisoformat(str(r["funding_time"]).replace("Z", "+00:00"))
            except ValueError:
                continue
            pts.append((t, float(r["funding_rate"])))
        pts.sort(key=lambda p: p[0])
        self.t = [p[0] for p in pts]
        self.r = [p[1] for p in pts]
        self.pre = [0.0]
        self.pre_paid = [0.0]
        for x in self.r:
            self.pre.append(self.pre[-1] + x)
            self.pre_paid.append(self.pre_paid[-1] + max(0.0, -x))

    def _win(self, t0: datetime, t1: datetime) -> tuple[int, int]:
        i = bisect_right(self.t, t0)
        j = bisect_left(self.t, t1, lo=i)
        return i, j

    def sum_between(self, t0: datetime, t1: datetime) -> float:
        """严格 t0 < t < t1 的资金费之和(进场时刻那一期算在持仓之前)。"""
        if not self.t:
            return 0.0
        i, j = self._win(t0, t1)
        return self.pre[j] - self.pre[i]

    def paid_between(self, t0: datetime, t1: datetime, mode: str = "gross") -> float:
        """空腿在 (t0, t1) 窗口里「累计付出」的资金费(占名义的比例,正数=付出)。

        gross(字面读法,主口径):Σ max(0, −rate) —— 只算付出去的,收到的不退。
        net  (净读法,副项):    −Σ rate            —— 收到的不减。
        """
        if not self.t:
            return 0.0
        i, j = self._win(t0, t1)
        if mode == "net":
            return -(self.pre[j] - self.pre[i])
        return self.pre_paid[j] - self.pre_paid[i]


def day_start(d: str) -> datetime:
    return datetime.fromisoformat(d + "T00:00:00+00:00")


# ── S-761 出场(原样保留:逐票新旧对照 + 复算校验)──────────────────────────────
def ticket_v1(sym: Series, btc: Series, fsym: Funding | None, fbtc: Funding | None,
              entry_date: str, cfg: dict) -> dict:
    """S-761:进场=entry_date 当日开盘;出场=第 hold 根收盘 或 止损(收盘触发、次日开盘出)。"""
    out: dict = {"entry_date": entry_date, "hold": cfg["hold"], "stop_atr": cfg["stop_atr"],
                 "hedge": bool(cfg["hedge"])}
    i = sym.idx.get(entry_date)
    if i is None:
        out.update(ok=False, reason="no_entry_bar")
        return out
    e = sym.o[i]
    if e is None:
        out.update(ok=False, reason="bad_entry_price")
        return out
    out["entry_px"] = e

    hold, stop_atr = cfg["hold"], cfg["stop_atr"]
    trs: list[float] = []
    atr = None
    exit_kind = exit_date = exit_px = None
    k_exit = 0
    stop_at_hold = False
    max_h = max_l = None
    n = len(sym.dates)
    jj, k = i, 0
    while jj < n and k < hold:
        h, l, c = sym.h[jj], sym.l[jj], sym.c[jj]
        if h is None or l is None or c is None:
            jj += 1
            continue
        k += 1
        max_h = h if max_h is None else max(max_h, h)
        max_l = l if max_l is None else min(max_l, l)
        pc = sym.c[jj - 1] if jj > 0 else None
        tr = (h - l) if pc is None else max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
        m = min(k, ATR_N)
        atr = sum(trs[-m:]) / m
        stop_px = e + stop_atr * atr
        if c >= stop_px:
            if k < hold:
                nxt = jj + 1
                if nxt < n and sym.o[nxt] is not None:
                    exit_kind, exit_date, exit_px = "stop", sym.dates[nxt], sym.o[nxt]
                else:
                    exit_kind, exit_date, exit_px = "stop_no_next", sym.dates[jj], c
                k_exit = k
                break
            stop_at_hold = True
        if k == hold:
            exit_kind, exit_date, exit_px = "hold", sym.dates[jj], c
            k_exit = k
            break
        jj += 1

    out["bars_held"] = k
    out["atr_at_exit"] = atr
    out["max_high_pct"] = (max_h / e - 1) * 100 if max_h else None
    out["min_low_pct"] = (max_l / e - 1) * 100 if max_l else None
    if exit_kind is None:
        out.update(ok=False, reason="no_exit")
        return out
    out.update(exit_kind=exit_kind, exit_date=exit_date, exit_px=exit_px,
               stop_triggered_at_hold=stop_at_hold)

    btc_r = None
    btc_entry = btc_exit = None
    if cfg["hedge"]:
        bi0, bi = btc.idx.get(entry_date), btc.idx.get(exit_date)
        if bi0 is None or bi is None or btc.o[bi0] is None:
            out.update(ok=False, reason="no_btc_bar")
            return out
        btc_entry = btc.o[bi0]
        btc_exit = btc.c[bi] if exit_kind in ("hold", "stop_no_next") else btc.o[bi]
        if btc_exit is None:
            out.update(ok=False, reason="bad_btc_price")
            return out

    edt = day_start(entry_date)
    xdt = day_start(exit_date)
    if exit_kind in ("hold", "stop_no_next"):
        xdt += timedelta(days=1)
    f_tok = fsym.sum_between(edt, xdt) if fsym else 0.0
    f_btc = fbtc.sum_between(edt, xdt) if fbtc else 0.0

    tok_r = short_return(e, exit_px)
    cost = 2 * COST_TOK + (2 * COST_BTC if cfg["hedge"] else 0.0)
    if cfg["hedge"]:
        btc_r = long_return(btc_entry, btc_exit)
        net = tok_r + btc_r + f_tok - f_btc - cost
    else:
        net = tok_r + f_tok - cost

    out.update(ok=True, net=net, tok_ret=tok_r, btc_ret=btc_r, btc_entry=btc_entry,
               btc_exit=btc_exit, funding_tok=f_tok, funding_btc=f_btc, cost=cost,
               n_funding=int(len([1 for t in (fsym.t if fsym else []) if edt < t < xdt])))
    return out


# ── S-762 出场(只改出场)──────────────────────────────────────────────────────
def ticket_v2(sym: Series, btc: Series, fsym: Funding | None, fbtc: Funding | None,
              entry_date: str, cfg: dict) -> dict:
    """S-762:① 挂单式止损(日内最高价触及即成交,跳空按开盘)② 资金费累计 ≥ 10% ⇒ 次日开盘出
    ③ 否则第 hold 根收盘。进场 / ATR / 对冲腿 / 成本 / 资金费窗口与 S-761 同。"""
    out: dict = {"entry_date": entry_date, "hold": cfg["hold"], "stop_atr": cfg["stop_atr"],
                 "hedge": bool(cfg["hedge"]), "fund_cap": cfg.get("fund_cap", FUND_CAP),
                 "fund_mode": cfg.get("fund_mode", FUND_MODE)}
    i = sym.idx.get(entry_date)
    if i is None:
        out.update(ok=False, reason="no_entry_bar")
        return out
    e = sym.o[i]
    if e is None:
        out.update(ok=False, reason="bad_entry_price")
        return out
    out["entry_px"] = e

    hold, stop_atr = cfg["hold"], cfg["stop_atr"]
    fund_cap = cfg.get("fund_cap", FUND_CAP)
    fund_mode = cfg.get("fund_mode", FUND_MODE)
    trs: list[float] = []
    atr = None
    exit_kind = exit_date = exit_px = None
    k_exit = 0
    max_h = max_l = None
    n = len(sym.dates)
    jj, k = i, 0
    edt = day_start(entry_date)
    cum_paid = 0.0
    while jj < n and k < hold:
        o, h, l, c = sym.o[jj], sym.h[jj], sym.l[jj], sym.c[jj]
        if h is None or l is None or c is None:
            jj += 1
            continue
        k += 1
        max_h = h if max_h is None else max(max_h, h)
        max_l = l if max_l is None else min(max_l, l)
        pc = sym.c[jj - 1] if jj > 0 else None
        tr = (h - l) if pc is None else max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
        m = min(k, ATR_N)
        atr = sum(trs[-m:]) / m
        stop_px = e + stop_atr * atr
        # ① 挂单式止损:日内最高价触及止损价 ⇒ 当日成交;跳空(开盘已越过止损价)按开盘价
        if h >= stop_px:
            if k == hold and cfg.get("hold_bar_stop_close"):
                exit_kind, exit_date, exit_px = "hold", sym.dates[jj], c
            else:
                fill = stop_px if o is None else max(stop_px, o)
                exit_kind, exit_date, exit_px = "stop_intraday", sym.dates[jj], fill
                if cfg.get("extra_slip"):
                    exit_px = exit_px * (1.0 + SLIP_NEW)
            k_exit = k
            break
        # ② 资金费保护:空腿累计付出 ≥ 名义 10% ⇒ 次日开盘出(hold 那根按持有规则收盘出)
        if k < hold and fund_cap:
            cum_paid = fsym.paid_between(edt, day_start(sym.dates[jj]) + timedelta(days=1),
                                         fund_mode) if fsym else 0.0
            if cum_paid >= fund_cap:
                nxt = jj + 1
                if nxt < n and sym.o[nxt] is not None:
                    exit_kind, exit_date, exit_px = "fund", sym.dates[nxt], sym.o[nxt]
                else:
                    exit_kind, exit_date, exit_px = "fund_no_next", sym.dates[jj], c
                k_exit = k
                break
        # ③ 持有到期
        if k == hold:
            exit_kind, exit_date, exit_px = "hold", sym.dates[jj], c
            k_exit = k
            break
        jj += 1

    out["bars_held"] = k
    out["atr_at_exit"] = atr
    out["max_high_pct"] = (max_h / e - 1) * 100 if max_h else None
    out["min_low_pct"] = (max_l / e - 1) * 100 if max_l else None
    if exit_kind is None:
        out.update(ok=False, reason="no_exit")
        return out
    out.update(exit_kind=exit_kind, exit_date=exit_date, exit_px=exit_px)

    # 资金费窗口:S-761 的口径 —— 开盘出 ⇒ 该日 00:00 那期不含;收盘/日内出 ⇒ 出场日整天计入
    if exit_kind in ("hold", "stop_intraday", "fund_no_next"):
        xdt = day_start(exit_date) + timedelta(days=1)
    else:  # fund:在 exit_date 的开盘出
        xdt = day_start(exit_date)
    f_tok = fsym.sum_between(edt, xdt) if fsym else 0.0
    f_btc = fbtc.sum_between(edt, xdt) if fbtc else 0.0
    out["fund_paid_gross"] = fsym.paid_between(edt, xdt, "gross") if fsym else 0.0
    out["fund_paid_net"] = fsym.paid_between(edt, xdt, "net") if fsym else 0.0
    out["cum_paid_at_trigger"] = cum_paid

    # BTC 对冲腿:同一进出场日、同一价格类型
    btc_r = None
    btc_entry = btc_exit = None
    if cfg["hedge"]:
        bi0, bi = btc.idx.get(entry_date), btc.idx.get(exit_date)
        if bi0 is None or bi is None or btc.o[bi0] is None:
            out.update(ok=False, reason="no_btc_bar")
            return out
        btc_entry = btc.o[bi0]
        if exit_kind in ("hold", "fund_no_next"):
            btc_exit = btc.c[bi]
        elif exit_kind == "fund":
            btc_exit = btc.o[bi]
        else:  # stop_intraday:同价格类型(开盘);副项 btc_stop_at_close 换成当日收盘
            btc_exit = btc.c[bi] if cfg.get("btc_stop_at_close") else btc.o[bi]
        if btc_exit is None:
            out.update(ok=False, reason="bad_btc_price")
            return out

    tok_r = short_return(e, exit_px)
    cost = 2 * COST_TOK + (2 * COST_BTC if cfg["hedge"] else 0.0)
    if cfg["hedge"]:
        btc_r = long_return(btc_entry, btc_exit)
        net = tok_r + btc_r + f_tok - f_btc - cost
    else:
        net = tok_r + f_tok - cost

    out.update(ok=True, net=net, tok_ret=tok_r, btc_ret=btc_r, btc_entry=btc_entry,
               btc_exit=btc_exit, funding_tok=f_tok, funding_btc=f_btc, cost=cost,
               n_funding=int(len([1 for t in (fsym.t if fsym else []) if edt < t < xdt])))
    return out


def stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    a = np.asarray(vals, dtype=float)
    srt = np.sort(a)
    k5 = max(1, int(math.ceil(0.05 * len(a))))
    return {
        "n": int(a.size),
        "mean_pct": float(a.mean() * 100),
        "median_pct": float(np.median(a) * 100),
        "std_pct": float(a.std(ddof=1) * 100) if a.size > 1 else None,
        "win_rate_pct": float((a > 0).mean() * 100),
        "p05_pct": float(np.quantile(a, 0.05) * 100),
        "p95_pct": float(np.quantile(a, 0.95) * 100),
        "worst5_mean_pct": float(srt[:k5].mean() * 100),
        "best5_mean_pct": float(srt[-k5:].mean() * 100),
        "sum_pct": float(a.sum() * 100),
    }


def decompose(tickets: list[dict]) -> dict:
    if not tickets:
        return {}
    return {
        "n": len(tickets),
        "tok_ret_pct": float(np.mean([t["tok_ret"] for t in tickets]) * 100),
        "btc_ret_pct": float(np.mean([t["btc_ret"] for t in tickets]) * 100),
        "funding_tok_pct": float(np.mean([t["funding_tok"] for t in tickets]) * 100),
        "funding_btc_pct": float(np.mean([t["funding_btc"] for t in tickets]) * 100),
        "cost_pct": float(np.mean([t["cost"] for t in tickets]) * 100),
        "net_pct": float(np.mean([t["net"] for t in tickets]) * 100),
        "btc_only_pct": float(np.mean([t["btc_ret"] - t["funding_btc"] + 2 * COST_BTC
                                       for t in tickets]) * 100),
        "exit_kinds": {kk: sum(1 for t in tickets if t["exit_kind"] == kk)
                       for kk in sorted({t["exit_kind"] for t in tickets})},
    }


def criteria(main: dict, seg_a: dict, seg_b: dict, ctrl: dict) -> dict:
    pct = ctrl.get("percentile")
    return {
        "a_mean_ge_3pct": {"value_pct": main.get("mean_pct"),
                            "pass": main.get("mean_pct") is not None and main["mean_pct"] >= 3.0},
        "b_median_ge_0": {"value_pct": main.get("median_pct"),
                           "pass": main.get("median_pct") is not None and main["median_pct"] >= 0},
        "c_percentile_ge_0.95": {
            "value": pct,
            "pass": bool(pct is not None and pct >= 0.95)},
        "d_two_segments_same_sign": {
            "v1_pct": seg_a.get("mean_pct"), "v2_pct": seg_b.get("mean_pct"),
            "pass": bool(seg_a.get("mean_pct") is not None and seg_b.get("mean_pct") is not None
                         and (seg_a["mean_pct"] >= 0) == (seg_b["mean_pct"] >= 0))},
        "e_worst5_mean_ge_-30pct": {
            "value_pct": main.get("worst5_mean_pct"),
            "pass": bool(main.get("worst5_mean_pct") is not None
                         and main["worst5_mean_pct"] >= -30.0)},
    }


def run_mode(mode: str, events: list[dict], series: dict, funds: dict, btc: Series,
             fbtc: Funding, do_control: bool = True, ticket_fn=ticket_v2) -> dict:
    """跑一整轮(主口径 + 对照 + 判据)。mode 只影响资金费保护的读法。"""
    cfg = dict(CFG_MAIN)
    cfg["fund_mode"] = mode
    tickets: list[dict] = []
    skipped: list[dict] = []
    for i_e, e in enumerate(events):
        sym = e["sym"]
        entry = (date.fromisoformat(e["d"]) + timedelta(days=1)).isoformat()
        t = ticket_fn(series[sym], btc, funds.get(sym), fbtc, entry, cfg)
        t.update(i=i_e, sym=sym, d=e["d"], mcap_pre=e.get("mcap_pre"),
                 ex30_pct=e.get("ex30_pct"), pre30_ret_pct=e.get("pre30_ret_pct"))
        if t.get("ok"):
            tickets.append(t)
        else:
            skipped.append(t)

    nets = [t["net"] for t in tickets]
    main = stats(nets)
    main["mean_funding_tok_pct"] = float(np.mean([t["funding_tok"] for t in tickets]) * 100)
    main["mean_funding_btc_pct"] = float(np.mean([t["funding_btc"] for t in tickets]) * 100)
    main["mean_cost_pct"] = float(np.mean([t["cost"] for t in tickets]) * 100)
    main["mean_tok_ret_pct"] = float(np.mean([t["tok_ret"] for t in tickets]) * 100)
    main["mean_btc_ret_pct"] = float(np.mean([t["btc_ret"] for t in tickets]) * 100)
    main["net_without_funding"] = stats([t["net"] - t["funding_tok"] + t["funding_btc"]
                                          for t in tickets])
    seg_a = stats([t["net"] for t in tickets if t["d"] < "2023-01-01"])
    seg_b = stats([t["net"] for t in tickets if t["d"] >= "2023-01-01"])

    out: dict = {
        "fund_mode": mode,
        "n_tickets": len(tickets),
        "skipped": [{"sym": s["sym"], "d": s["d"], "reason": s.get("reason")} for s in skipped],
        "exit_kinds": {k: sum(1 for t in tickets if t["exit_kind"] == k)
                       for k in sorted({t["exit_kind"] for t in tickets})},
        "main": main,
        "segments": {"2020_2022": seg_a, "2023_plus": seg_b},
        "decomposition": {
            "all": decompose(tickets),
            "2020_2022": decompose([t for t in tickets if t["d"] < "2023-01-01"]),
            "2023_plus": decompose([t for t in tickets if t["d"] >= "2023-01-01"]),
        },
        "worst_tickets": [
            {k: t.get(k) for k in ("sym", "d", "entry_date", "entry_px", "exit_date", "exit_px",
                                   "exit_kind", "tok_ret", "btc_ret", "funding_tok", "funding_btc",
                                   "cost", "net", "max_high_pct", "min_low_pct", "atr_at_exit",
                                   "fund_paid_gross", "cum_paid_at_trigger")}
            for t in sorted(tickets, key=lambda t: t["net"])[:8]],
    }

    # (c) 同代币随机日对照(同一套进出场 = 同一套新出场规则)
    ctrl: dict = {}
    if do_control:
        print(f"  对照(随机日,{mode})…", flush=True)
        ctrl_pnl: dict[int, dict[str, float]] = {}
        eligible: dict[int, list[str]] = {}
        for i_e, e in enumerate(events):
            sym = e["sym"]
            d0 = date.fromisoformat(e["d"])
            lo = (d0 + timedelta(days=CTRL_LO)).isoformat()
            hi = (d0 + timedelta(days=CTRL_HI)).isoformat()
            s = series[sym]
            vals: dict[str, float] = {}
            for d0s in s.dates:
                if not (lo <= d0s <= hi):
                    continue
                ct = ticket_fn(s, btc, funds.get(sym), fbtc, d0s, cfg)
                if ct.get("ok"):
                    vals[d0s] = ct["net"]
            ctrl_pnl[i_e] = vals
            eligible[i_e] = sorted(vals.keys())
        out["ctrl_eligible"] = {str(k): len(v) for k, v in eligible.items()}
        out["ctrl_mean_dates_per_event"] = float(np.mean([len(v) for v in eligible.values()]))
        actual_mean = float(np.mean(nets))

        def one_round(rng):
            draws = random_dates_like([(i_e, e["d"]) for i_e, e in enumerate(events)],
                                       eligible, rng, stratum=lambda _s: "all")
            vals = [ctrl_pnl[i_e][d0] for i_e, d0 in draws
                    if d0 is not None and d0 in ctrl_pnl[i_e]]
            return float(np.mean(vals)) if vals else float("nan")

        try:
            null = null_distribution(one_round, N_ROUNDS, SEED, actual=actual_mean)
            ctrl = {
                "n": int(null.size),
                "mean_pct": float(null.mean() * 100),
                "p05_pct": float(np.quantile(null, 0.05) * 100),
                "p50_pct": float(np.quantile(null, 0.5) * 100),
                "p95_pct": float(np.quantile(null, 0.95) * 100),
                "actual_mean_pct": actual_mean * 100,
                "percentile": percentile_of(actual_mean, null),
            }
        except NoOpNull as ex:
            ctrl = {"error": str(ex)}
    out["null_control"] = ctrl

    crit = criteria(out["main"], seg_a, seg_b, ctrl)
    out["criteria"] = crit
    out["verdict"] = "✅ 全部通过" if all(c["pass"] for c in crit.values()) else "❌ 未全部通过"
    out["_tickets"] = tickets
    return out


def run_variant(cfg: dict, events: list[dict], series: dict, funds: dict, btc: Series,
                fbtc: Funding, mode: str = FUND_MODE) -> dict:
    cfg = dict(cfg)
    cfg["fund_mode"] = mode
    ts = []
    for e in events:
        sym = e["sym"]
        entry = (date.fromisoformat(e["d"]) + timedelta(days=1)).isoformat()
        t = ticket_v2(series[sym], btc, funds.get(sym), fbtc, entry, cfg)
        if t.get("ok"):
            ts.append(t)
    st = stats([t["net"] for t in ts])
    st["n_tickets"] = len(ts)
    st["exit_kinds"] = {kk: sum(1 for t in ts if t["exit_kind"] == kk)
                         for kk in sorted({t["exit_kind"] for t in ts})}
    return st


def main() -> None:
    res: dict = {
        "task": "T-283", "ledger": "S-762", "seed": SEED, "n_rounds": N_ROUNDS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rules": {
            "inherited_from_S761": {
                "events": "T-282 的 142 个事件原样",
                "entry": "上线日 d 的次日(d+1,日历日)perp_bv_daily 开盘;没有 ⇒ 不进",
                "atr": "TR=max(h−l,|h−c_{k−1}|,|l−c_{k−1}|);ATR_k=TR_1..TR_min(k,14) 的均值;止损价 = 进场 + 2.5×ATR_k",
                "hedge": "同时等名义做多 BTC 永续,同一进出场日、同一价格类型",
                "cost_per_side": {"token": COST_TOK, "btc": COST_BTC},
                "funding_window": "进场日 00:00 那期不含;开盘出 ⇒ 出场日 00:00 那期不含;收盘/日内出 ⇒ 出场日整天计入",
                "pnl": "两腿合计 ÷ 代币腿名义(等名义 ⇒ 两腿名义相同)",
            },
            "changed_exit_S762": {
                "stop": "某日 perp_bv_daily 最高价 ≥ 止损价 ⇒ 当日按 max(止损价, 当日开盘价) 成交(跳空按开盘)",
                "funding_guard": "空腿累计付出的资金费 ≥ 名义 10% ⇒ 次日开盘出",
                "hold": "否则第 30 根日线收盘",
                "precedence": "挂单止损 > 资金费保护 > 持有到期;持有到期那根同时触发止损 ⇒ 按日内成交(§口径)",
            },
        },
        "caliber_notes": {
            "btc_leg_intraday_stop": "止损出场日 BTC 腿按同日同价格类型 = 当日开盘(副项 btc_stop_at_close 给当日收盘的对照)",
            "funding_mode": "主口径 gross = Σ max(0, −rate)(字面「累计付出」);net 读法整轮另跑作副项",
            "hold_bar_stop": "主口径:持有到期那根若日内触及止损,按挂单成交(比收盘早);副项 hold_bar_stop_close 给 S-761 的平手约定",
            "stop_slippage": "主口径:止损成交价不再另加滑点 —— 代币腿每边成本 10bp(taker 5bp + 滑点 5bp)已经含了出场那 5bp;副项 extra_slip 给叠加版",
        },
    }

    ev_path = OUT / "t283_events.json"
    ev_doc = json.loads(ev_path.read_text())
    events = ev_doc["events"]
    res["events_source"] = {k: ev_doc.get(k) for k in ("source", "source_commit", "ledger")}
    res["n_events"] = len(events)
    syms = sorted({e["sym"] for e in events})
    res["n_symbols"] = len(syms)

    # ── 取数 ────────────────────────────────────────────────────────────────
    print("取数…", flush=True)
    rng_by_sym: dict[str, tuple[str, str]] = {}
    for e in events:
        d0 = date.fromisoformat(e["d"])
        lo = (d0 - timedelta(days=PRE)).isoformat()
        hi = (d0 + timedelta(days=POST)).isoformat()
        if e["sym"] in rng_by_sym:
            a, b = rng_by_sym[e["sym"]]
            rng_by_sym[e["sym"]] = (min(a, lo), max(b, hi))
        else:
            rng_by_sym[e["sym"]] = (lo, hi)

    series: dict[str, Series] = {}
    funds: dict[str, Funding] = {}
    for sym in syms:
        lo, hi = rng_by_sym[sym]
        series[sym] = Series(cached("perp_bv_daily", sym, "d", lo, hi, "d,o,h,l,c"))
        funds[sym] = Funding(cached("funding_history", sym, "funding_time", lo, hi,
                                    "funding_time,funding_rate,venue"))
    glo = min(date.fromisoformat(e["d"]) for e in events)
    ghi = max(date.fromisoformat(e["d"]) for e in events)
    btc_lo = (glo - timedelta(days=PRE)).isoformat()
    btc_hi = (ghi + timedelta(days=POST)).isoformat()
    btc = Series(cached("perp_bv_daily", "BTC", "d", btc_lo, btc_hi, "d,o,h,l,c"))
    fbtc = Funding(cached("funding_history", "BTC", "funding_time", btc_lo, btc_hi,
                           "funding_time,funding_rate,venue"))
    res["data_range"] = {"btc": [btc_lo, btc_hi], "n_btc_bars": len(btc),
                         "n_btc_funding": len(fbtc.t),
                         "n_symbols_with_bars": sum(1 for s in series.values() if len(s))}

    # ── 旧规则复算(S-761,校验继承没走样)───────────────────────────────────
    print("旧规则复算(S-761)…", flush=True)
    old = run_mode("gross", events, series, funds, btc, fbtc, do_control=False,
                   ticket_fn=ticket_v1)
    res["old_S761_recomputed"] = {k: v for k, v in old.items() if not k.startswith("_")}
    res["old_S761_recomputed"]["ref_S761"] = S761_REF
    res["old_S761_recomputed"]["matches_ref"] = bool(
        old["n_tickets"] == S761_REF["n_tickets"]
        and abs(old["main"]["mean_pct"] - S761_REF["mean_pct"]) < 0.02
        and abs(old["main"]["median_pct"] - S761_REF["median_pct"]) < 0.02
        and abs(old["main"]["worst5_mean_pct"] - S761_REF["worst5_mean_pct"]) < 0.05)

    # ── 新规则主口径(gross)─────────────────────────────────────────────────
    print("新规则主口径(S-762, gross)…", flush=True)
    new = run_mode("gross", events, series, funds, btc, fbtc, do_control=True)
    res["new_S762_gross"] = {k: v for k, v in new.items() if not k.startswith("_")}

    # ── 新规则副口径(net 读法)──────────────────────────────────────────────
    print("新规则副口径(S-762, net)…", flush=True)
    new_net = run_mode("net", events, series, funds, btc, fbtc, do_control=True)
    res["new_S762_net"] = {k: v for k, v in new_net.items() if not k.startswith("_")}

    # ── 逐票新旧对照 ────────────────────────────────────────────────────────
    old_by_i = {t["i"]: t for t in old["_tickets"]}
    new_by_i = {t["i"]: t for t in new["_tickets"]}
    rows = []
    for i_e in sorted(set(old_by_i) | set(new_by_i)):
        o = old_by_i.get(i_e) or {}
        n = new_by_i.get(i_e) or {}
        rows.append({
            "sym": (n or o).get("sym"), "d": (n or o).get("d"),
            "entry_date": (n or o).get("entry_date"), "entry_px": (n or o).get("entry_px"),
            "old_exit_kind": o.get("exit_kind"), "old_exit_date": o.get("exit_date"),
            "old_exit_px": o.get("exit_px"), "old_net_pct": (o.get("net") or 0) * 100,
            "old_tok_ret_pct": (o.get("tok_ret") or 0) * 100,
            "old_btc_ret_pct": (o.get("btc_ret") or 0) * 100,
            "old_funding_tok_pct": (o.get("funding_tok") or 0) * 100,
            "new_exit_kind": n.get("exit_kind"), "new_exit_date": n.get("exit_date"),
            "new_exit_px": n.get("exit_px"), "new_net_pct": (n.get("net") or 0) * 100,
            "new_tok_ret_pct": (n.get("tok_ret") or 0) * 100,
            "new_btc_ret_pct": (n.get("btc_ret") or 0) * 100,
            "new_funding_tok_pct": (n.get("funding_tok") or 0) * 100,
            "new_fund_paid_gross_pct": (n.get("fund_paid_gross") or 0) * 100,
            "new_cum_paid_at_trigger_pct": (n.get("cum_paid_at_trigger") or 0) * 100,
            "delta_net_pp": ((n.get("net") or 0) - (o.get("net") or 0)) * 100,
            "bars_held_old": o.get("bars_held"), "bars_held_new": n.get("bars_held"),
            "max_high_pct": n.get("max_high_pct"),
            "atr_at_exit_new": n.get("atr_at_exit"),
            "atr_at_exit_old": o.get("atr_at_exit"),
            "mcap_pre": n.get("mcap_pre"),
        })
    res["ticket_compare"] = rows
    res["ticket_compare_summary"] = {
        "n_rows": len(rows),
        "n_common": len([r for r in rows if r["old_exit_kind"] and r["new_exit_kind"]]),
        "exit_kind_pairs": {},
        "delta_mean_pp": float(np.mean([r["delta_net_pp"] for r in rows
                                        if r["old_exit_kind"] and r["new_exit_kind"]])),
        "delta_median_pp": float(np.median([r["delta_net_pp"] for r in rows
                                             if r["old_exit_kind"] and r["new_exit_kind"]])),
        "improved_count": sum(1 for r in rows if r["old_exit_kind"] and r["new_exit_kind"]
                               and r["delta_net_pp"] > 0),
        "worsened_count": sum(1 for r in rows if r["old_exit_kind"] and r["new_exit_kind"]
                              and r["delta_net_pp"] < 0),
        "worst_old_now_best_new": [],
    }
    pairs: dict[str, int] = {}
    for r in rows:
        key = f"{r['old_exit_kind']}→{r['new_exit_kind']}"
        pairs[key] = pairs.get(key, 0) + 1
    res["ticket_compare_summary"]["exit_kind_pairs"] = pairs
    res["ticket_compare_summary"]["worst_old_now_best_new"] = sorted(
        [r for r in rows if r["old_exit_kind"] and r["new_exit_kind"]],
        key=lambda r: r["delta_net_pp"], reverse=True)[:5]

    # ── 副项(只报不判)──────────────────────────────────────────────────────
    sub: dict = {}
    for label, cfg in [
        ("no_hedge", {"hold": HOLD, "stop_atr": STOP_ATR, "hedge": False}),
        ("stop_2.0", {"hold": HOLD, "stop_atr": 2.0, "hedge": True}),
        ("stop_3.0", {"hold": HOLD, "stop_atr": 3.0, "hedge": True}),
        ("hold_15", {"hold": 15, "stop_atr": STOP_ATR, "hedge": True}),
        ("hold_60", {"hold": 60, "stop_atr": STOP_ATR, "hedge": True}),
        ("btc_stop_at_close", {"hold": HOLD, "stop_atr": STOP_ATR, "hedge": True,
                               "btc_stop_at_close": True}),
        ("extra_slip", {"hold": HOLD, "stop_atr": STOP_ATR, "hedge": True, "extra_slip": True}),
        ("hold_bar_stop_close", {"hold": HOLD, "stop_atr": STOP_ATR, "hedge": True,
                                 "hold_bar_stop_close": True}),
        ("no_fund_guard", {"hold": HOLD, "stop_atr": STOP_ATR, "hedge": True, "fund_cap": None}),
    ]:
        sub[label] = run_variant(cfg, events, series, funds, btc, fbtc)

    # 市值三分位
    ter: dict = {}
    with_mc = [t for t in new["_tickets"] if t.get("mcap_pre") is not None]
    if with_mc:
        vals = sorted(t["mcap_pre"] for t in with_mc)
        q1 = vals[len(vals) // 3]
        q2 = vals[2 * len(vals) // 3]
        for name, lo_b, hi_b in (("small", None, q1), ("mid", q1, q2), ("large", q2, None)):
            grp = []
            for t in with_mc:
                m = t["mcap_pre"]
                if lo_b is not None and m <= lo_b:
                    continue
                if hi_b is not None and m > hi_b:
                    continue
                grp.append(t["net"])
            ter[name] = stats(grp)
        ter["cutoffs"] = {"q1": q1, "q2": q2, "n_with_mcap": len(with_mc)}
    sub["mcap_terciles"] = ter

    sub["funding_only"] = {
        "mean_token_funding_pct": float(np.mean([t["funding_tok"] for t in new["_tickets"]]) * 100),
        "median_token_funding_pct": float(np.median([t["funding_tok"] for t in new["_tickets"]]) * 100),
        "mean_btc_funding_pct": float(np.mean([t["funding_btc"] for t in new["_tickets"]]) * 100),
        "share_token_funding_positive": float(np.mean([t["funding_tok"] > 0
                                                       for t in new["_tickets"]]) * 100),
        "mean_gross_paid_pct": float(np.mean([t["fund_paid_gross"] for t in new["_tickets"]]) * 100),
        "max_gross_paid_pct": float(np.max([t["fund_paid_gross"] for t in new["_tickets"]]) * 100),
        "n_tickets_gross_paid_ge_10pct": sum(1 for t in new["_tickets"]
                                             if t["fund_paid_gross"] >= FUND_CAP),
        "n_triggered_by_guard": sum(1 for t in new["_tickets"] if t["exit_kind"] == "fund"),
    }
    res["sub"] = sub

    (OUT / "t283_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({k: res[k] for k in ("n_events",)}, ensure_ascii=False))
    for key in ("old_S761_recomputed", "new_S762_gross", "new_S762_net"):
        blk = res[key]
        print(f"--- {key}: n={blk['n_tickets']} exits={blk['exit_kinds']}")
        print(json.dumps({"main": blk["main"], "segments": blk["segments"],
                          "null_control": blk.get("null_control"),
                          "criteria": blk["criteria"], "verdict": blk["verdict"]},
                         ensure_ascii=False, indent=1))
    print("matches_ref(S-761 复算):", res["old_S761_recomputed"]["matches_ref"])
    print("ticket pairs:", json.dumps(res["ticket_compare_summary"]["exit_kind_pairs"],
                                      ensure_ascii=False))
    print("副项:", json.dumps({k: (v.get("mean_pct"), v.get("worst5_mean_pct"))
                               for k, v in sub.items() if isinstance(v, dict) and "mean_pct" in v},
                              ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
