"""S-851(11-13,Seth 写、lane 跑):「条件成立 = 开始盯」的基率 —— 从开始盯到周线确认隔多久、期间多头又走了多少、有多少次根本没确认。

登记见 REFUTATION_LEDGER `## S-851`。只读、描述加随机起点对照,不动钱。
用法(仓库根目录,环境里有只读的 SUPABASE_URL / SUPABASE_KEY):
    nohup python3 docs/research/s851_watch_base_rate.py > docs/research/s851_run.log 2>&1 &
    python3 docs/research/s851_watch_base_rate.py --selftest       # 不联网,合成数据走全程
产出 docs/research/s851_results.json。
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

import numpy as np

OUT = "docs/research/s851_results.json"
SEED, N_NULL = 20261113, 200
MIN_CONDS, QUIET_D, MAX_WATCH_D, INVALID_D, POST_D = 2, 30, 180, 14, 56
D0 = dt.date(2019, 6, 1)


def get(path: str, params: dict) -> list[dict]:
    base = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    key = os.environ["SUPABASE_KEY"]
    out, off = [], 0
    while True:
        q = urllib.parse.urlencode({**params, "limit": 1000, "offset": off})
        req = urllib.request.Request(base + "?" + q, headers={"apikey": key, "Authorization": "Bearer " + key, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            rows = json.loads(r.read())
        out += rows
        if len(rows) < 1000:
            return out
        off += 1000


def D(s) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def asof(dates: list, vals: list, d: dt.date, max_age: int):
    i = bisect.bisect_right(dates, d) - 1
    return vals[i] if i >= 0 and (d - dates[i]).days <= max_age else None


def weekly_down_days(days: list, close: dict) -> dict:
    """每个周日判一次:收盘 < 10 周均线(含本周)且 < 4 周前;结论从下周一起生效到下一个周日(只用 ≤ 该周日的数据)。"""
    suns = [d for d in days if d.weekday() == 6 and d in close]
    flag, out = {}, {}
    for i, d in enumerate(suns):
        if i >= 9:
            w = [close[x] for x in suns[i - 9:i + 1]]
            flag[d] = bool(close[d] < sum(w) / 10 and close[d] < close[suns[i - 4]])
    cur = None
    for d in days:
        prev_sun = d - dt.timedelta(days=(d.weekday() + 1) % 7 or 7)      # 严格早于 d 的最近一个周日
        cur = flag.get(prev_sun, cur if prev_sun not in flag else None)
        out[d] = cur
    return out


def conditions(d, close, dist200, taker, stable, y2_d, y2_v) -> int | None:
    """三条先行条件里成立了几条;价格不在 200 日线上方 ⇒ 0(先行条件只在趋势还好的时候才有意义);关键输入缺 ⇒ None。"""
    if dist200.get(d) is None:
        return None
    if dist200[d] <= 0:
        return 0
    n = 0
    if taker.get(d) is not None and taker[d] < 0.5:
        n += 1
    if stable.get(d) is not None and stable[d] <= 0:
        n += 1
    a, b = asof(y2_d, y2_v, d, 10), asof(y2_d, y2_v, d - dt.timedelta(days=91), 10)
    if a is not None and b is not None and a > b:
        n += 1
    return n


def episodes(days, cond: dict, wdown: dict, close: dict, starts: list | None = None) -> list[dict]:
    """开始盯 = 成立条数 ≥ 2 的第一天(此前 30 天都 < 2);之后:周线确认 / 条件连续 14 天全无(作废)/ 满 180 天(超时),先到为准。
    给了 starts 就用给定的起点(随机起点对照),其余记账相同。"""
    idx = {d: i for i, d in enumerate(days)}
    if starts is None:
        starts, quiet = [], QUIET_D
        for d in days:
            c = cond.get(d)
            if c is not None and c >= MIN_CONDS:
                if quiet >= QUIET_D:
                    starts.append(d)
                quiet = 0
            else:
                quiet += 1
    out, busy_until = [], None
    for s in starts:
        if busy_until is not None and s <= busy_until:
            continue
        i0, zero_run, end, how = idx[s], 0, None, "timeout"
        peak = close[s]
        for j in range(i0 + 1, min(i0 + MAX_WATCH_D, len(days) - 1) + 1):
            d = days[j]
            peak = max(peak, close.get(d, peak))
            if wdown.get(d):
                end, how = d, "confirmed"
                break
            zero_run = zero_run + 1 if (cond.get(d) or 0) == 0 else 0
            if zero_run >= INVALID_D:
                end, how = d, "invalidated"
                break
        end = end or days[min(i0 + MAX_WATCH_D, len(days) - 1)]
        post = close.get(end + dt.timedelta(days=POST_D))
        out.append({"start": str(s), "end": str(end), "outcome": how, "days": (end - s).days,
                    "ret_start_to_end_pct": round((close[end] / close[s] - 1) * 100, 1), "max_runup_pct": round((peak / close[s] - 1) * 100, 1),
                    "ret_8w_after_end_pct": None if post is None else round((post / close[end] - 1) * 100, 1)})
        busy_until = end
    return out


def summarise(ep: list[dict]) -> dict:
    def med(xs):
        xs = [x for x in xs if x is not None]
        return None if not xs else round(float(np.median(xs)), 1)
    by = {k: [e for e in ep if e["outcome"] == k] for k in ("confirmed", "invalidated", "timeout")}
    return {"n": len(ep), "share_confirmed": round(len(by["confirmed"]) / len(ep), 3) if ep else None,
            **{k: {"n": len(v), "median_days": med([e["days"] for e in v]), "median_ret_start_to_end_pct": med([e["ret_start_to_end_pct"] for e in v]),
                   "median_max_runup_pct": med([e["max_runup_pct"] for e in v]), "median_ret_8w_after_pct": med([e["ret_8w_after_end_pct"] for e in v]),
                   "mean_ret_8w_after_pct": None if not [e for e in v if e["ret_8w_after_end_pct"] is not None] else
                   round(float(np.mean([e["ret_8w_after_end_pct"] for e in v if e["ret_8w_after_end_pct"] is not None])), 1)} for k, v in by.items()}}


def run(days, close, dist200, taker, stable, y2_d, y2_v) -> dict:
    wdown = weekly_down_days(days, close)
    cond = {d: conditions(d, close, dist200, taker, stable, y2_d, y2_v) for d in days}
    ep = episodes(days, cond, wdown, close)
    real = summarise(ep)
    rng = np.random.default_rng(SEED)
    pool = [d for d in days[:-MAX_WATCH_D] if (dist200.get(d) or 0) > 0 and not wdown.get(d)]         # 对照:趋势还好、周线没坏的任意一天
    shares, mdays = [], []
    for _ in range(N_NULL):
        st = sorted(rng.choice(len(pool), size=min(len(ep), len(pool)), replace=False)) if pool and ep else []
        s = summarise(episodes(days, cond, wdown, close, [pool[i] for i in st]))
        if s["n"]:
            shares.append(s["share_confirmed"])
            if s["confirmed"]["median_days"] is not None:
                mdays.append(s["confirmed"]["median_days"])
    c = real["confirmed"]
    null = {"n_draws": len(shares), "share_confirmed_median": round(float(np.median(shares)), 3) if shares else None,
            "share_confirmed_p90": round(float(np.quantile(shares, 0.9)), 3) if shares else None,
            "real_share_pctile": round(float(np.mean(np.array(shares) < (real["share_confirmed"] or 0))), 3) if shares else None,
            "median_days_to_confirm_median": round(float(np.median(mdays)), 1) if mdays else None,
            "median_days_to_confirm_p10": round(float(np.quantile(mdays, 0.1)), 1) if mdays else None,
            "real_median_days_pctile": (round(float(np.mean(np.array(mdays) < real["confirmed"]["median_days"])), 3)
                                        if mdays and real["confirmed"]["median_days"] is not None else None)}
    i = real["invalidated"]
    expect = {"a_confirms_sooner_than_random_starts_p10": bool(null["median_days_to_confirm_p10"] is not None and c["median_days"] is not None
                                                             and c["median_days"] < null["median_days_to_confirm_p10"]),
              "b_bulls_still_run_before_confirmation": bool(c["median_max_runup_pct"] is not None and c["median_max_runup_pct"] > 0),
              "c_after_confirmation_worse_than_after_invalidation": bool(c["mean_ret_8w_after_pct"] is not None and i["mean_ret_8w_after_pct"] is not None
                                                                         and c["mean_ret_8w_after_pct"] < i["mean_ret_8w_after_pct"])}
    cov = {"days": len(days), "cond_known_days": sum(1 for v in cond.values() if v is not None), "first_taker_day": str(min((d for d, v in taker.items() if v is not None), default=None)),
           "days_with_2plus": sum(1 for v in cond.values() if (v or 0) >= MIN_CONDS)}
    # 自检(能失败):把切点之后的收盘全部乘 2,切点之前开始、且在切点之前结束的每一段,必须逐字不变
    cut = days[len(days) // 2]
    close2 = {d: v * (2.0 if d > cut else 1.0) for d, v in close.items()}
    ep2 = episodes(days, cond, weekly_down_days(days, close2), close2)
    before = [e for e in ep if e["end"] <= str(cut - dt.timedelta(days=POST_D))]
    before2 = [e for e in ep2 if e["end"] <= str(cut - dt.timedelta(days=POST_D))]
    checks = {"episodes_before_cut_ignore_future_prices": before == before2, "n_before_cut": len(before),
              "this_episode_present": [e for e in ep if e["start"] >= "2026-09-01"][:2]}
    return {"coverage": cov, "real": real, "null_random_starts": null, "expectations": expect, "self_checks": checks, "episodes": ep}


def load_live():
    px = get("ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC", "source": "eq.binance_hist", "trade_date": "gte.2018-09-01", "order": "trade_date.asc"})
    close = {D(r["trade_date"]): float(r["close"]) for r in px if r.get("close")}
    feats = {}
    for f in ("dist_200", "taker_buy_share_30d", "stable_supply_30d"):
        rows = get("state_daily", {"select": "d,value", "entity": "eq.panel", "feature": f"eq.{f}", "d": "gte.2019-01-01", "order": "d.asc"})
        feats[f] = {D(r["d"]): (None if r.get("value") is None else float(r["value"])) for r in rows}
        print("loaded", f, len(feats[f]), flush=True)
    y = get("macro_daily", {"select": "d,value", "series": "eq.ust_2y", "d": "gte.2018-06-01", "order": "d.asc"})
    days = sorted(d for d in close if d >= D0)
    return days, close, feats["dist_200"], feats["taker_buy_share_30d"], feats["stable_supply_30d"], [D(r["d"]) for r in y], [float(r["value"]) for r in y]


def synthetic():
    rng = np.random.default_rng(11)
    days = [dt.date(2018, 9, 1) + dt.timedelta(days=i) for i in range(3000)]
    lv = 100 * np.exp(np.cumsum(0.0006 + 0.03 * np.sin(np.arange(3000) / 90.0) / 30 + rng.normal(0, 0.025, 3000)))
    close = dict(zip(days, map(float, lv)))
    ma = np.convolve(lv, np.ones(200) / 200, mode="full")[:3000]
    dist = {d: (None if i < 200 else float(lv[i] / ma[i] - 1)) for i, d in enumerate(days)}
    taker = {d: float(0.5 + 0.01 * np.sin(i / 37.0) + rng.normal(0, 0.003)) for i, d in enumerate(days)}
    stable = {d: float(0.01 * np.sin(i / 120.0) + rng.normal(0, 0.002)) for i, d in enumerate(days)}
    y2 = np.cumsum(rng.normal(0, 0.02, 3000)) + 3
    return [d for d in days if d >= D0], close, dist, taker, stable, days, list(map(float, y2))


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    out = run(*(synthetic() if selftest else load_live()))
    for k in ("coverage", "real", "null_random_starts", "expectations", "self_checks"):
        print(k.upper(), json.dumps(out[k], ensure_ascii=False), flush=True)
    if selftest:
        assert out["real"]["n"] >= 5 and out["self_checks"]["episodes_before_cut_ignore_future_prices"] and out["self_checks"]["n_before_cut"] >= 1
        assert all(e["days"] <= MAX_WATCH_D and e["outcome"] in ("confirmed", "invalidated", "timeout") for e in out["episodes"])
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
