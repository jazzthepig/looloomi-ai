#!/usr/bin/env python3
"""T-282 — S-761 ④ 空票:Binance 上线 USDT 永续的次日开盘做空 + 等名义多 BTC,持有 30 天,
2.5 ATR 止损,扣成本与资金费。判据 (a)–(e) 照台账一字不改。

- 事件:S-758 / T-279 主口径 142 个(docs/research/t282_events.json,原样)
- 价格:perp_bv_daily(Binance USDT 永续日线 o/h/l/c)
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
CACHE = RESEARCH / "t282_cache"
CACHE.mkdir(parents=True, exist_ok=True)
OUT = Path(__file__).resolve().parent

# ── 台账 S-761 写死的参数 ────────────────────────────────────────────────────
SEED = 761
N_ROUNDS = 200          # (c) 对照:随机日 200 轮(每轮每票抽 1 个日子 → 每票共 200 个日子)
HOLD = 30               # 持有 30 根日线
STOP_ATR = 2.5          # 2.5 ATR 止损
TAKER = 0.0005          # taker 5bp(每腿每边)
SLIP_NEW = 0.0005       # 滑点 5bp(新币)
SLIP_BTC = 0.0002       # 滑点 2bp(BTC)
COST_TOK = TAKER + SLIP_NEW   # 10bp 每边
COST_BTC = TAKER + SLIP_BTC   # 7bp 每边
CTRL_LO, CTRL_HI = 90, 365    # 对照窗口 [d+90, d+365]
PRE = 15                # 回看(前一根收盘 → TR)
POST = 400              # 事件后拉多少天(对照窗口 + 30 根持有)
ATR_N = 14

CFG_MAIN = {"hold": HOLD, "stop_atr": STOP_ATR, "hedge": True}


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
    """funding_history(binance_perp)按时间排序 + 前缀和。"""

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
        for x in self.r:
            self.pre.append(self.pre[-1] + x)

    def sum_between(self, t0: datetime, t1: datetime) -> float:
        """严格 t0 < t < t1 的资金费之和(进场时刻那一期算在持仓之前)。"""
        if not self.t:
            return 0.0
        i = bisect_right(self.t, t0)
        j = bisect_left(self.t, t1, lo=i)
        return self.pre[j] - self.pre[i]


# ── 单票 ────────────────────────────────────────────────────────────────────
def ticket(sym: Series, btc: Series, fsym: Funding | None, fbtc: Funding | None,
           entry_date: str, cfg: dict) -> dict:
    """进场=entry_date 当日开盘;出场=第 hold 根收盘 或 止损(次日开盘)。返回逐票台账。"""
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

    # BTC 多腿(等名义、同进出场日、同价格类型)
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

    # 资金费:进场日 00:00 之后、出场时刻之前逐期
    edt = datetime.fromisoformat(entry_date + "T00:00:00+00:00")
    xdt = datetime.fromisoformat(exit_date + "T00:00:00+00:00")
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


def main() -> None:
    res: dict = {
        "task": "T-282", "ledger": "S-761", "seed": SEED, "n_rounds": N_ROUNDS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rules": {
            "entry": "上线日 d 的次日(d+1,日历日)perp_bv_daily 开盘;没有 ⇒ 不进",
            "exit": "第 30 根日线收盘;或收盘 ≥ 进场×(1+2.5×ATR14/进场价) ⇒ 次日开盘出",
            "atr": "TR=max(h−l,|h−c_{k−1}|,|l−c_{k−1}|);ATR_k=TR_1..TR_min(k,14) 的均值",
            "hedge": "同时等名义做多 BTC 永续,同一进出场日、同一价格类型",
            "cost_per_side": {"token": COST_TOK, "btc": COST_BTC},
            "funding": "funding_history(venue=binance_perp)逐期;空腿收/付、多腿反向",
            "pnl": "两腿合计 ÷ 代币腿名义(等名义 ⇒ 两腿名义相同)",
        },
    }

    ev_doc = json.loads((OUT / "t282_events.json").read_text())
    events = ev_doc["events"]
    res["events_source"] = {k: ev_doc[k] for k in ("source", "source_commit", "ledger")}
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
                         "n_btc_funding": len(fbtc.t)}

    # ── 主口径票 ────────────────────────────────────────────────────────────
    tickets: list[dict] = []
    skipped: list[dict] = []
    for i_e, e in enumerate(events):
        sym = e["sym"]
        d0 = date.fromisoformat(e["d"])
        entry = (d0 + timedelta(days=1)).isoformat()
        t = ticket(series[sym], btc, funds.get(sym), fbtc, entry, CFG_MAIN)
        t.update(i=i_e, sym=sym, d=e["d"], mcap_pre=e.get("mcap_pre"),
                 ex30_pct=e.get("ex30_pct"), pre30_ret_pct=e.get("pre30_ret_pct"))
        if t.get("ok"):
            tickets.append(t)
        else:
            s = series[sym]
            t["perp_first_bar"] = s.dates[0] if len(s) else None
            t["perp_bars_in_window"] = len(s)
            skipped.append(t)
    res["n_tickets"] = len(tickets)
    res["skipped"] = skipped
    res["exit_kinds"] = {k: sum(1 for t in tickets if t["exit_kind"] == k)
                         for k in sorted({t["exit_kind"] for t in tickets})}
    nets = [t["net"] for t in tickets]
    res["main"] = stats(nets)
    res["main"]["mean_funding_tok_pct"] = float(np.mean([t["funding_tok"] for t in tickets]) * 100)
    res["main"]["mean_funding_btc_pct"] = float(np.mean([t["funding_btc"] for t in tickets]) * 100)
    res["main"]["mean_cost_pct"] = float(np.mean([t["cost"] for t in tickets]) * 100)
    res["main"]["mean_tok_ret_pct"] = float(np.mean([t["tok_ret"] for t in tickets]) * 100)
    res["main"]["mean_btc_ret_pct"] = float(np.mean([t["btc_ret"] for t in tickets]) * 100)
    res["main"]["net_without_funding"] = stats([t["net"] - t["funding_tok"] + t["funding_btc"]
                                                for t in tickets])

    # (d) 两段同号
    seg_a = [t["net"] for t in tickets if t["d"] < "2023-01-01"]
    seg_b = [t["net"] for t in tickets if t["d"] >= "2023-01-01"]
    res["segments"] = {"2020_2022": stats(seg_a), "2023_plus": stats(seg_b)}

    # 分解:两腿各贡献多少(「这张票赚的是空腿还是 BTC beta」)
    def decomp(ts):
        if not ts:
            return {}
        return {
            "n": len(ts),
            "tok_ret_pct": float(np.mean([t["tok_ret"] for t in ts]) * 100),
            "btc_ret_pct": float(np.mean([t["btc_ret"] for t in ts]) * 100),
            "funding_tok_pct": float(np.mean([t["funding_tok"] for t in ts]) * 100),
            "funding_btc_pct": float(np.mean([t["funding_btc"] for t in ts]) * 100),
            "cost_pct": float(np.mean([t["cost"] for t in ts]) * 100),
            "net_pct": float(np.mean([t["net"] for t in ts]) * 100),
            # 同一批窗口上「只做多 BTC 永续」的对照
            "btc_only_pct": float(np.mean([t["btc_ret"] - t["funding_btc"] + 2 * COST_BTC
                                           for t in ts]) * 100),
            "exit_kinds": {kk: sum(1 for t in ts if t["exit_kind"] == kk)
                           for kk in sorted({t["exit_kind"] for t in ts})},
        }

    res["decomposition"] = {
        "all": decomp(tickets),
        "2020_2022": decomp([t for t in tickets if t["d"] < "2023-01-01"]),
        "2023_plus": decomp([t for t in tickets if t["d"] >= "2023-01-01"]),
    }
    res["worst_tickets"] = [
        {k: t[k] for k in ("sym", "d", "entry_date", "entry_px", "exit_date", "exit_px",
                           "exit_kind", "tok_ret", "btc_ret", "funding_tok", "funding_btc",
                           "cost", "net", "max_high_pct", "min_low_pct", "atr_at_exit")}
        for t in sorted(tickets, key=lambda t: t["net"])[:8]]

    # ── (c) 同代币随机日对照 ────────────────────────────────────────────────
    print("对照(随机日)…", flush=True)
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
            ct = ticket(s, btc, funds.get(sym), fbtc, d0s, CFG_MAIN)
            if ct.get("ok"):
                vals[d0s] = ct["net"]
        ctrl_pnl[i_e] = vals
        eligible[i_e] = sorted(vals.keys())
    res["ctrl_eligible"] = {str(k): len(v) for k, v in eligible.items()}
    res["ctrl_mean_dates_per_event"] = float(np.mean([len(v) for v in eligible.values()]))

    actual_mean = float(np.mean(nets))

    def one_round(rng):
        draws = random_dates_like([(i_e, e["d"]) for i_e, e in enumerate(events)],
                                   eligible, rng, stratum=lambda _s: "all")
        vals = [ctrl_pnl[i_e][d0] for i_e, d0 in draws if d0 is not None and d0 in ctrl_pnl[i_e]]
        return float(np.mean(vals)) if vals else float("nan")

    null_err = None
    try:
        null = null_distribution(one_round, N_ROUNDS, SEED, actual=actual_mean)
        pct = percentile_of(actual_mean, null)
        res["null_control"] = {
            "n": int(null.size), "mean_pct": float(null.mean() * 100),
            "p05_pct": float(np.quantile(null, 0.05) * 100),
            "p50_pct": float(np.quantile(null, 0.5) * 100),
            "p95_pct": float(np.quantile(null, 0.95) * 100),
            "actual_mean_pct": actual_mean * 100,
            "percentile": pct,
        }
    except NoOpNull as ex:
        null_err = str(ex)
        res["null_control"] = {"error": null_err}

    # ── 副项(只报不判)──────────────────────────────────────────────────────
    sub: dict = {}

    def run_variant(cfg):
        ts = []
        for e in events:
            sym = e["sym"]
            entry = (date.fromisoformat(e["d"]) + timedelta(days=1)).isoformat()
            t = ticket(series[sym], btc, funds.get(sym), fbtc, entry, cfg)
            if t.get("ok"):
                ts.append(t)
        return stats([t["net"] for t in ts]), len(ts)

    for label, cfg in [
        ("no_hedge", {"hold": HOLD, "stop_atr": STOP_ATR, "hedge": False}),
        ("stop_2.0", {"hold": HOLD, "stop_atr": 2.0, "hedge": True}),
        ("stop_3.0", {"hold": HOLD, "stop_atr": 3.0, "hedge": True}),
        ("hold_15", {"hold": 15, "stop_atr": STOP_ATR, "hedge": True}),
        ("hold_60", {"hold": 60, "stop_atr": STOP_ATR, "hedge": True}),
    ]:
        st, n = run_variant(cfg)
        st["n_tickets"] = n
        sub[label] = st

    # 入场日变体:下一个有日线的日子(副项)
    ts = []
    for e in events:
        sym = e["sym"]
        s = series[sym]
        d0 = date.fromisoformat(e["d"])
        nxt = None
        for dd in s.dates:
            if dd > e["d"]:
                nxt = dd
                break
        if nxt is None:
            continue
        t = ticket(s, btc, funds.get(sym), fbtc, nxt, CFG_MAIN)
        if t.get("ok"):
            t["entry_date"] = nxt
            ts.append(t)
    st = stats([t["net"] for t in ts])
    st["n_tickets"] = len(ts)
    sub["entry_next_bar"] = st

    # 市值三分位(用 T-279 已算的 mcap_pre)
    ter = {}
    with_mc = [t for t in tickets if t.get("mcap_pre") is not None]
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

    # 资金费贡献单列
    sub["funding_only"] = {
        "mean_token_funding_pct": float(np.mean([t["funding_tok"] for t in tickets]) * 100),
        "median_token_funding_pct": float(np.median([t["funding_tok"] for t in tickets]) * 100),
        "mean_btc_funding_pct": float(np.mean([t["funding_btc"] for t in tickets]) * 100),
        "share_token_funding_positive": float(np.mean([t["funding_tok"] > 0 for t in tickets]) * 100),
    }
    res["sub"] = sub

    # ── 判据 ────────────────────────────────────────────────────────────────
    crit = {
        "a_mean_ge_3pct": {"value_pct": res["main"]["mean_pct"], "pass": res["main"]["mean_pct"] >= 3.0},
        "b_median_ge_0": {"value_pct": res["main"]["median_pct"], "pass": res["main"]["median_pct"] >= 0},
        "c_percentile_ge_0.95": {
            "value": (res.get("null_control") or {}).get("percentile"),
            "pass": bool((res.get("null_control") or {}).get("percentile") is not None
                         and res["null_control"]["percentile"] >= 0.95)},
        "d_two_segments_same_sign": {
            "v1_pct": res["segments"]["2020_2022"].get("mean_pct"),
            "v2_pct": res["segments"]["2023_plus"].get("mean_pct"),
            "pass": bool(res["segments"]["2020_2022"].get("mean_pct") is not None
                         and res["segments"]["2023_plus"].get("mean_pct") is not None
                         and (res["segments"]["2020_2022"]["mean_pct"] >= 0) ==
                             (res["segments"]["2023_plus"]["mean_pct"] >= 0))},
        "e_worst5_mean_ge_-30pct": {
            "value_pct": res["main"].get("worst5_mean_pct"),
            "pass": bool(res["main"].get("worst5_mean_pct") is not None
                         and res["main"]["worst5_mean_pct"] >= -30.0)},
    }
    res["criteria"] = crit
    res["verdict"] = "✅ 全部通过" if all(c["pass"] for c in crit.values()) else "❌ 未全部通过"

    # ── 逐票台账 ────────────────────────────────────────────────────────────
    res["tickets"] = [{
        "sym": t["sym"], "d": t["d"], "entry_date": t["entry_date"], "entry_px": t["entry_px"],
        "exit_date": t["exit_date"], "exit_px": t["exit_px"], "exit_kind": t["exit_kind"],
        "bars_held": t["bars_held"], "atr_at_exit": t["atr_at_exit"],
        "tok_ret_pct": t["tok_ret"] * 100, "btc_ret_pct": (t["btc_ret"] or 0) * 100,
        "btc_entry": t["btc_entry"], "btc_exit": t["btc_exit"],
        "funding_tok_pct": t["funding_tok"] * 100, "funding_btc_pct": t["funding_btc"] * 100,
        "cost_pct": t["cost"] * 100, "net_pct": t["net"] * 100,
        "max_high_pct": t.get("max_high_pct"), "min_low_pct": t.get("min_low_pct"),
        "mcap_pre": t["mcap_pre"],
    } for t in tickets]

    (OUT / "t282_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({k: res[k] for k in ("n_events", "n_tickets", "exit_kinds", "main",
                                          "segments", "null_control", "criteria", "verdict")},
                     ensure_ascii=False, indent=1))
    print("副项:", json.dumps(sub, ensure_ascii=False, indent=1)[:2000])
    print("skipped:", len(skipped), [s["reason"] for s in skipped][:10])


if __name__ == "__main__":
    main()
