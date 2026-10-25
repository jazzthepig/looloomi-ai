"""S-681 H4(台账 2026-10-25 13:21 UTC,照抄不改):熊市反弹失败做空。

状态 = 收盘 < 200 日线 且 200 日线低于 20 天前;
设置 = 过去 10 天(含 t)最高收盘 ≥ 过去 20 天(含 t)最低收盘 × 1.15,且 c_t < l_{t−1} 且 c_t < SMA20_t;
止损 = 过去 10 天(含 t)最高价,与次日开盘之比封顶 30%;
出场 = 收盘 > 20 日线的次日开盘,或 N = 30;
宇宙 = 全部 USDT 本位永续(含 BTC / ETH)、30 日成交额 ≥ $5M、上市 ≥ 200 天;同币持仓不叠。
对照 = 同一币、同样处于该状态(只要求状态,不要求设置)的随机日子空,同样止损口径与出场规则。
        —— 用 short_lab_common.null_same_day;**pools 的键改成票号**(该函数按 t["signal_d"] 取池,
           所以把票号塞进副本的 signal_d),池内容 = 该币同段窗口内的状态日。
发现段 = 信号日 2020-01-01 → 2023-12-31;**先算完发现段并写进结果,再打开留出段(2024-01-01 起)**。
只报项(台账):资金曲线(f 0.5%、10 张)年化与最大回撤;最差 1% 的票(R);胜率与赔率;跳空穿止损次数;
资金费贡献;按年;对冲版(空 + 等名义多 BTC)。卡上另加:NASDAQ 1971–2014、Binance 现货 2018–2020、
BTC / ETH 单独列、与 S-600 破位空的对照。
用法:python3 docs/research/s681_h4_bear_rally_fail.py [--root <数据根>]
"""
from __future__ import annotations

import bisect
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
os.environ["COMETCLOUD_DATA_ROOT"] = ROOT
import short_lab_common as sl  # noqa: E402

N_HOLD = 30                 # 台账:N = 30
STOP_CAP = 0.30             # 台账:止损与进场价之比封顶 30%
SMA_N, SMA_BACK = 200, 20   # 200 日线、且低于 20 天前
RALLY_N, LOW_N = 10, 20     # 过去 10 天 / 20 天(含 t)
RALLY_MULT = 1.15           # 有过反弹:最高收盘 ≥ 最低收盘 × 1.15
ADV_MIN = 5e6               # 30 日成交额 ≥ $5M
MIN_LISTED_DAYS = 200       # 上市 ≥ 200 天
DISC_LO, DISC_HI = sl.DISCOVERY
HOLD_LO = sl.HOLDOUT_FROM
OUT = os.path.join(HERE, "s681_h4_bear_rally_fail_results.json")
TICKET_FIELDS = ("symbol", "signal_d", "entry_d", "exit_d", "entry_px", "stop_px", "exit_px", "risk",
                 "r", "ret", "funding", "funding_days", "hold_days", "why", "gap", "still")


# ── 指标(全部只用当天及以前)────────────────────────────────────────────────────────────
def roll_max(x: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= w:
        out[w - 1:] = np.lib.stride_tricks.sliding_window_view(x, w).max(axis=1)
    return out


def roll_min(x: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= w:
        out[w - 1:] = np.lib.stride_tricks.sliding_window_view(x, w).min(axis=1)
    return out


def prep(a: dict) -> dict:
    """所有派生量只用当天及以前。"""
    c = a["c"]
    n = len(c)
    sma20 = sl.rolling_mean(c, 20)
    sma200 = sl.rolling_mean(c, SMA_N)
    back = np.full(n, np.nan)
    back[SMA_BACK:] = sma200[:-SMA_BACK]
    prev_l = np.r_[np.nan, a["l"][:-1]]
    return {
        "sma20": sma20,
        "sma200": sma200,
        "back": back,
        "state": (c < sma200) & (sma200 < back),
        "setup": roll_max(c, RALLY_N) >= roll_min(c, LOW_N) * RALLY_MULT,
        "fail": (c < prev_l) & (c < sma20),
        "hmax10": roll_max(a["h"], RALLY_N),
    }


def eligible(a: dict, p: dict, use_adv: bool = True, use_listed: bool = True) -> np.ndarray:
    m = np.isfinite(p["sma200"]) & np.isfinite(p["back"]) & np.isfinite(p["sma20"])
    if use_adv:
        m &= sl.adv30(a) >= ADV_MIN
    if use_listed:
        days = np.array(a["d"], dtype="datetime64[D]")
        m &= (days - days[0]).astype(int) >= MIN_LISTED_DAYS
    return m


def stop_series(a: dict, p: dict) -> np.ndarray:
    """止损价 = 过去 10 天(含 t)最高价,与次日开盘之比封顶 30%。"""
    entry = np.r_[a["o"][1:], np.nan]          # entry[i] = 第 t+1 天开盘
    return np.minimum(p["hmax10"], entry * (1 + STOP_CAP))


def open_ticket(a: dict, i: int, stops: np.ndarray, sma20: np.ndarray, fund, sym: str):
    """t 收盘定、t+1 开盘进空;止损用 stops[i];出场 = 收盘 > SMA20 的次日开盘,或 N = 30。"""
    n = len(a["d"])
    if i + 1 >= n:
        return None
    entry = float(a["o"][i + 1])
    stop = float(stops[i])
    if not (stop > entry > 0):
        return None
    return sl.short_ticket(a, i, STOP_CAP, N_HOLD, fund=fund,
                           exit_rule=lambda aa, j: aa["c"][j] > sma20[j],
                           stop_px=stop, symbol=sym)


# ── 扫描一个宇宙 ──────────────────────────────────────────────────────────────────────
def scan_um(um: dict, fund_daily: dict, use_adv: bool = True, use_listed: bool = True) -> dict:
    """返回候选票(未叠票)、对照池(每币的状态日)、每币的 SMA20 与止损序列。"""
    tickets, pools, sma20s, stops = [], {}, {}, {}
    n_state = n_cand = 0
    for sym, a in um.items():
        n = len(a["d"])
        if n < SMA_N + SMA_BACK + 2:
            continue
        p = prep(a)
        el = eligible(a, p, use_adv, use_listed)
        st = stop_series(a, p)
        sma20s[sym] = p["sma20"]
        stops[sym] = st
        entry = np.r_[a["o"][1:], np.nan]          # entry[i] = 第 t+1 天开盘
        ok = el & (st > entry) & (entry > 0)
        idx = np.where(p["state"] & ok)[0]
        pools[sym] = [int(i) for i in idx]
        n_state += len(idx)
        cand = np.where(p["state"] & p["setup"] & p["fail"] & el)[0]
        n_cand += len(cand)
        for i in cand:
            t = open_ticket(a, int(i), st, p["sma20"], fund_daily.get(sym), sym)
            if t:
                tickets.append(t)
    return {"tickets": tickets, "pools": pools, "sma20s": sma20s, "stops": stops,
            "n_state_days": n_state, "n_cand_days": n_cand}


# ── 对照零分布(同币、随机状态日)───────────────────────────────────────────────────────
def control_pools(tickets: list[dict], um: dict, pools: dict, lo: str, hi: str):
    """pools 的键 = 票号;池 = 该币同段窗口内的状态日。返回 (proxy 票, pools)。"""
    proxy, cpools = [], {}
    for t in tickets:
        key = f"{t['symbol']}#{t['signal_d']}"
        proxy.append(dict(t, signal_d=key))
        ds = um[t["symbol"]]["d"]
        days = [i for i in pools.get(t["symbol"], []) if lo <= ds[i] <= hi]
        cpools[key] = [(t["symbol"], i) for i in days]
    return proxy, cpools


def null_for(tickets: list[dict], um: dict, scan: dict, fund_daily: dict, lo: str, hi: str,
             draws: int = 1000) -> np.ndarray:
    proxy, cpools = control_pools(tickets, um, scan["pools"], lo, hi)
    stops, sma20s = scan["stops"], scan["sma20s"]

    def make(sym, i):
        return open_ticket(um[sym], i, stops[sym], sma20s[sym], fund_daily.get(sym), sym)

    return sl.null_same_day(proxy, cpools, make, draws=draws, seed=sl.SEED)


def null_block(tickets: list[dict], um: dict, scan: dict, fund_daily: dict, lo: str, hi: str) -> dict:
    null = null_for(tickets, um, scan, fund_daily, lo, hi)
    m = float(np.mean([t["r"] for t in tickets])) if tickets else float("nan")
    return {"n_null_draws": int(len(null)),
            "null_median": float(np.median(null)) if len(null) else None,
            "null_q95": float(np.quantile(null, 0.95)) if len(null) else None,
            "null_mean": float(np.mean(null)) if len(null) else None,
            "null_pct_below_mean": float((null < m).mean()) if len(null) else None,
            "_null": null}


# ── 只报项 ────────────────────────────────────────────────────────────────────────────
def payoff(tickets: list[dict]) -> dict:
    r = np.array([t["r"] for t in tickets])
    if not len(r):
        return {"win_rate": None, "avg_win_r": None, "avg_loss_r": None, "payoff": None}
    w, l = r[r > 0], r[r <= 0]
    return {"win_rate": float((r > 0).mean()),
            "avg_win_r": float(w.mean()) if len(w) else None,
            "avg_loss_r": float(l.mean()) if len(l) else None,
            "payoff": float(w.mean() / abs(l.mean())) if len(w) and len(l) and l.mean() != 0 else None}


def btc_leg(um: dict, t: dict):
    """对冲版的 BTC 多头腿:进场日开盘 → 出场日开盘(未平则最后收盘)的收益。"""
    a = um.get("BTC")
    if a is None:
        return None
    ds, o = a["d"], a["o"]
    i0 = bisect.bisect_left(ds, t["entry_d"])
    if i0 >= len(ds) or ds[i0] != t["entry_d"]:
        return None
    if t["still"] or not t["exit_d"]:
        x = float(a["c"][-1])
    else:
        i1 = bisect.bisect_right(ds, t["exit_d"]) - 1
        x = float(o[i1]) if i1 >= 0 else None
    e = float(o[i0])
    if x is None or not (e > 0):
        return None
    return x / e - 1


def hedged(tickets: list[dict], um: dict) -> dict:
    """空 + 等名义多 BTC(按同一风险单位)。"""
    out = []
    for t in tickets:
        b = btc_leg(um, t)
        if b is None:
            continue
        r = (t["ret"] + b) / t["risk"]
        out.append(dict(t, r=r, btc_leg=b, ret=t["ret"] + b))
    return {"summary": sl.summary(out), "n": len(out)}


# ── 其它场所(只报)────────────────────────────────────────────────────────────────────
def load_nasdaq(root: str, hi: str = "2014-12-31") -> dict:
    path = os.path.join(root, "research", "crash_atlas", "fred", "NASDAQCOM.csv")
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            d = r["observation_date"]
            raw = (r.get("NASDAQCOM") or "").strip()
            if not raw or raw == ".":          # FRED 缺值 = 空或 "."
                continue
            v = float(raw)
            if d <= hi:
                rows.append((d, v))
    c = np.array([v for _, v in rows], float)
    n = len(c)
    return {"d": [d for d, _ in rows], "o": c, "h": c, "l": c, "c": c, "qv": np.zeros(n)}


def load_spot(root: str) -> dict:
    path = os.path.join(root, "research", "s677", "_bv_daily.jsonl")
    out = {}
    for line in open(path):
        x = json.loads(line)
        rows = sorted({tuple(b) for b in x["bars"] if b[4] > 0})
        if not rows:
            continue
        a = np.array([r[1:] for r in rows], float)
        out[x["symbol"]] = {"d": [r[0] for r in rows], "o": a[:, 0], "h": a[:, 1], "l": a[:, 2],
                            "c": a[:, 3], "qv": a[:, 4]}
    return out


# ── 主流程 ────────────────────────────────────────────────────────────────────────────
def main() -> None:
    um = sl.load_um()
    fund_daily = sl.daily_funding(sl.load_funding())
    scan = scan_um(um, fund_daily)
    allt = sl.chain(scan["tickets"])
    res = {"rule": {"n_hold": N_HOLD, "stop_cap": STOP_CAP, "sma_n": SMA_N, "sma_back": SMA_BACK,
                    "rally_n": RALLY_N, "low_n": LOW_N, "rally_mult": RALLY_MULT,
                    "adv_min": ADV_MIN, "min_listed_days": MIN_LISTED_DAYS,
                    "discovery": list(sl.DISCOVERY), "holdout_from": HOLD_LO},
           "universe": {"n_symbols": len(um), "n_state_days": scan["n_state_days"],
                        "n_cand_days": scan["n_cand_days"],
                        "n_tickets_before_chain": len(scan["tickets"]), "n_tickets_after_chain": len(allt)}}

    # ── 发现段(先算完、写进结果,再打开留出段)────────────────────────────────────────
    disc = sl.in_window(allt, DISC_LO, DISC_HI)
    d = null_block(disc, um, scan, fund_daily, DISC_LO, DISC_HI)
    res["discovery"] = {"summary": sl.summary(disc), "payoff": payoff(disc),
                        "null_median": d["null_median"], "null_q95": d["null_q95"],
                        "null_mean": d["null_mean"], "null_pct_below_mean": d["null_pct_below_mean"],
                        "p_le0": sl.boot_months(disc) if disc else None,
                        "hedged": hedged(disc, um)}
    json.dump(res, open(OUT, "w"), indent=1, default=str)          # 发现段先落盘
    print("DISCOVERY", json.dumps({"n": res["discovery"]["summary"].get("n"),
                                   "mean_r": res["discovery"]["summary"].get("mean_r"),
                                   "p_le0": res["discovery"]["p_le0"],
                                   "null_q95": res["discovery"]["null_q95"]}, default=str))

    # ── 留出段(2024-01-01 起,之前没对这些定义算过)────────────────────────────────────
    hold = [t for t in allt if t["signal_d"] >= HOLD_LO]
    h = null_block(hold, um, scan, fund_daily, HOLD_LO, "9999-12-31")
    res["holdout"] = {"summary": sl.summary(hold), "payoff": payoff(hold),
                      "null_median": h["null_median"], "null_q95": h["null_q95"],
                      "null_mean": h["null_mean"], "null_pct_below_mean": h["null_pct_below_mean"],
                      "p_le0": sl.boot_months(hold) if hold else None,
                      "hedged": hedged(hold, um)}
    res["judged"] = sl.judge(disc, d["_null"], hold)
    print("HOLDOUT", json.dumps({"n": res["holdout"]["summary"].get("n"),
                                 "mean_r": res["holdout"]["summary"].get("mean_r")}, default=str))
    print("JUDGED", json.dumps(res["judged"], default=str))

    # ── BTC / ETH 单独列 ────────────────────────────────────────────────────────────
    res["by_symbol_btc_eth"] = {}
    for sym in ("BTC", "ETH"):
        sub = [t for t in allt if t["symbol"] == sym]
        sd = sl.in_window(sub, DISC_LO, DISC_HI)
        sh = [t for t in sub if t["signal_d"] >= HOLD_LO]
        b = {"discovery": sl.summary(sd), "holdout": sl.summary(sh)}
        if sd:
            nb = null_block(sd, um, scan, fund_daily, DISC_LO, DISC_HI)
            b["null_q95"] = nb["null_q95"]
            b["judged"] = sl.judge(sd, nb["_null"], sh)
        res["by_symbol_btc_eth"][sym] = b

    # ── 资金曲线 ───────────────────────────────────────────────────────────────────
    nb = sl.nav_bars({s: um[s] for s in {t["symbol"] for t in allt}})
    last = max(a["d"][-1] for a in um.values())
    res["money_discovery"] = sl.money(disc, nb, "2024-03-31")
    res["money_holdout"] = sl.money(hold, nb, last)

    # ── 只报: NASDAQ 1971–2014(无 OHLC、无成交额、无资金费)────────────────────────
    nas = {"NASDAQCOM": load_nasdaq(ROOT)}
    nscan = scan_um(nas, {}, use_adv=False, use_listed=False)
    nt = sl.chain(nscan["tickets"])
    res["nasdaq_1971_2014"] = {"n": len(nt), "summary": sl.summary(nt), "payoff": payoff(nt),
                               "n_state_days": nscan["n_state_days"], "n_cand_days": nscan["n_cand_days"]}
    if nt:
        lo = nt[0]["signal_d"]
        hi = nt[-1]["signal_d"]
        nnull = null_block(nt, nas, nscan, {}, lo, hi)
        res["nasdaq_1971_2014"]["null_median"] = nnull["null_median"]
        res["nasdaq_1971_2014"]["null_q95"] = nnull["null_q95"]
        res["nasdaq_1971_2014"]["null_pct_below_mean"] = nnull["null_pct_below_mean"]

    # ── 只报: Binance 现货 2018–2020(无资金费)─────────────────────────────────────
    spot = load_spot(ROOT)
    sscan = scan_um(spot, {})
    st = sl.chain(sscan["tickets"])
    st = [t for t in st if t["signal_d"] >= "2018-01-01"]
    res["spot_binance_2018_2020"] = {"n": len(st), "summary": sl.summary(st), "payoff": payoff(st),
                                     "n_state_days": sscan["n_state_days"], "n_cand_days": sscan["n_cand_days"]}
    if st:
        sn = null_block(st, spot, sscan, {}, "2018-01-01", "9999-12-31")
        res["spot_binance_2018_2020"]["null_median"] = sn["null_median"]
        res["spot_binance_2018_2020"]["null_q95"] = sn["null_q95"]
        res["spot_binance_2018_2020"]["null_pct_below_mean"] = sn["null_pct_below_mean"]

    # ── 每张票 ───────────────────────────────────────────────────────────────────
    res["tickets"] = [dict({k: t[k] for k in TICKET_FIELDS},
                           phase=("discovery" if DISC_LO <= t["signal_d"] <= DISC_HI else
                                  ("holdout" if t["signal_d"] >= HOLD_LO else "pre"))) for t in allt]
    json.dump(res, open(OUT, "w"), indent=1, default=str)
    print("MONEY", json.dumps({"disc": res["money_discovery"], "hold": res["money_holdout"]}, default=str)[:900])
    print("BTC_ETH", json.dumps({k: {"d_n": v["discovery"].get("n"), "d_mean_r": v["discovery"].get("mean_r"),
                                     "h_n": v["holdout"].get("n"), "h_mean_r": v["holdout"].get("mean_r")}
                                 for k, v in res["by_symbol_btc_eth"].items()}, default=str))
    print("NASDAQ", json.dumps(res["nasdaq_1971_2014"], default=str)[:500])
    print("SPOT", json.dumps(res["spot_binance_2018_2020"], default=str)[:500])
    print("HEDGED", json.dumps({"disc_mean_r": res["discovery"]["hedged"]["summary"].get("mean_r"),
                                "hold_mean_r": res["holdout"]["hedged"]["summary"].get("mean_r")}, default=str))


if __name__ == "__main__":
    main()
