"""S-850(11-13,Seth 写、lane 跑):同一套读法(利率方向 × 稳定币供应 × 自己的周线 × 自己的供给 / 资金维度)在别的资产上成不成立。

登记见 REFUTATION_LEDGER `## S-850`。只读、描述加循环平移对照,不叠账户、不动钱。
用法(仓库根目录,环境里有只读的 SUPABASE_URL / SUPABASE_KEY;key 不打印):
    nohup python3 docs/research/s850_cross_asset.py > docs/research/s850_run.log 2>&1 &
    python3 docs/research/s850_cross_asset.py --selftest      # 不联网,用合成数据把整条路走一遍
产出 docs/research/s850_results.json。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

import numpy as np

OUT = "docs/research/s850_results.json"
SEED, N_NULL, H_WEEKS = 20261113, 200, 8
W0, W1 = dt.date(2019, 6, 2), dt.date(2026, 9, 13)
CRYPTO, TRADFI = ("BTC", "ETH", "SOL"), ("XAUUSD", "ACWI", "QQQ")
ASSETS = CRYPTO + ("ALT20",) + TRADFI
HALVINGS = [dt.date(2012, 11, 28), dt.date(2016, 7, 9), dt.date(2020, 5, 11), dt.date(2024, 4, 20)]
BTC_EXPECT = {"wk_ok/rates_falling": 18.7, "wk_ok/rates_rising": 5.8, "wk_down/rates_falling": 11.1, "wk_down/rates_rising": -0.4}
SUPPLY_IDS = {"ETH": "ethereum", "SOL": "solana"}


def get(path: str, params: dict) -> list[dict]:
    """PostgREST 分页读;读不到抛错(读不到 ≠ 0 行)。"""
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


class Series:
    """按日期排序的序列;asof(d, max_age) = ≤ d 的最近一个值(太旧 ⇒ None)。绝不取 d 之后的。"""

    def __init__(self, pairs):
        p = sorted((D(a), float(b)) for a, b in pairs if b is not None)
        self.d = [a for a, _ in p]
        self.v = [b for _, b in p]

    def asof(self, d: dt.date, max_age: int = 6):
        import bisect
        i = bisect.bisect_right(self.d, d) - 1
        return self.v[i] if i >= 0 and (d - self.d[i]).days <= max_age else None


def sundays() -> list[dt.date]:
    out, d = [], W0
    while d <= W1:
        out.append(d)
        d += dt.timedelta(days=7)
    return out


def weekly_down(level: list, i: int) -> bool | None:
    """该资产自己的周线:本周 < 10 周均线(含本周)且 < 4 周前。前面不够 10 周 / 缺值 ⇒ None。"""
    if i < 9 or any(level[j] is None for j in range(i - 9, i + 1)):
        return None
    w = level[i - 9:i + 1]
    return bool(level[i] < sum(w) / 10 and level[i] < level[i - 4])


def cell_table(rets, a, b, na: str, nb: str) -> dict:
    """两维布尔状态 → 四格:周数 / 均值 / 中位 / 为负比例 / 年份数。缺任一维或缺收益的周不进。"""
    g = defaultdict(list)
    for (d, r), x, y in zip(rets, a, b):
        if r is None or x is None or y is None:
            continue
        g[f"{na[1] if x else na[0]}/{nb[1] if y else nb[0]}"].append((d, r))
    return {k: {"n": len(v), "mean8": round(float(np.mean([r for _, r in v])) * 100, 1), "med8": round(float(np.median([r for _, r in v])) * 100, 1),
                "neg8": round(float(np.mean([r < 0 for _, r in v])) * 100), "years": len({d.year for d, _ in v})} for k, v in sorted(g.items())}


def diff_good_bad(rets, good, bad):
    g = [r for (_, r), x in zip(rets, good) if r is not None and x]
    b = [r for (_, r), x in zip(rets, bad) if r is not None and x]
    return (float(np.mean(g) - np.mean(b)) if len(g) >= 5 and len(b) >= 5 else None), len(g), len(b)


def null_pctile(rets, good, bad, rng) -> dict:
    real, ng, nb = diff_good_bad(rets, good, bad)
    if real is None:
        return {"diff_pp": None, "n_good": ng, "n_bad": nb, "pctile": None}
    n, nd = len(rets), []
    for _ in range(N_NULL):
        k = int(rng.integers(4, n - 4))
        d, _, _ = diff_good_bad(rets, good[k:] + good[:k], bad[k:] + bad[:k])
        if d is not None:
            nd.append(d)
    return {"diff_pp": round(real * 100, 1), "n_good": ng, "n_bad": nb, "pctile": round(float(np.mean(np.array(nd) < real)), 3) if nd else None,
            "null_median_pp": round(float(np.median(nd)) * 100, 1) if nd else None, "null_p90_pp": round(float(np.quantile(nd, 0.9)) * 100, 1) if nd else None}


def halving_month(d: dt.date) -> float:
    return (d - max(h for h in HALVINGS if h <= d)).days / 30.44


def analyse(weeks, level: dict, fwd: dict, rate_up, stable_neg, extra: dict, rng) -> dict:
    """level[asset] / fwd[asset]:与 weeks 等长的列表(该周日的水平、之后 8 周收益);extra[asset] = (名字, 布尔列表, (假名, 真名)) 或读不到的原因。"""
    res = {}
    for a in ASSETS:
        rets = list(zip(weeks, fwd[a]))
        wk = [weekly_down(level[a], i) for i in range(len(weeks))]
        good = [(x is False and y is False) for x, y in zip(rate_up, stable_neg)]                  # 利率降 + 稳定币在加
        bad = [(x is True and y is True) for x, y in zip(rate_up, stable_neg)]                     # 利率升 + 稳定币在抽
        st_good = [y is False for y in stable_neg]
        st_bad = [y is True for y in stable_neg]
        r = {"n_weeks": sum(1 for x in fwd[a] if x is not None),
             "rates_x_stable": cell_table(rets, rate_up, stable_neg, ("rates_falling", "rates_rising"), ("stable_adding", "stable_draining")),
             "weekly_x_rates": cell_table(rets, wk, rate_up, ("wk_ok", "wk_down"), ("rates_falling", "rates_rising")),
             "stable_x_weekly": cell_table(rets, stable_neg, wk, ("stable_adding", "stable_draining"), ("wk_ok", "wk_down")),
             "good_minus_bad": null_pctile(rets, good, bad, rng), "stable_only": null_pctile(rets, st_good, st_bad, rng)}
        e = extra.get(a)
        if isinstance(e, tuple):
            name, flags, labels = e
            g2 = defaultdict(list)
            for (d, x), f in zip(rets, flags):
                if x is not None and f is not None:
                    g2[labels[1] if f else labels[0]].append(x)
            r["own_dimension"] = {"name": name, **{k: {"n": len(v), "mean8": round(float(np.mean(v)) * 100, 1), "neg8": round(float(np.mean([y < 0 for y in v])) * 100)}
                                                   for k, v in sorted(g2.items())}}
        else:
            r["own_dimension"] = {"name": "读不到", "why": str(e)}
        res[a] = r
    return res


def expectations(res: dict) -> dict:
    gm = {a: res[a]["good_minus_bad"] for a in ASSETS}
    so = {a: res[a]["stable_only"] for a in ASSETS}
    cr = ("ETH", "SOL", "ALT20")
    e1 = all(gm[a]["diff_pp"] is not None and gm[a]["diff_pp"] > 0 and (gm[a]["pctile"] or 0) >= 0.9 for a in cr)
    e1b = gm["ALT20"]["diff_pp"] is not None and gm["BTC"]["diff_pp"] is not None and gm["ALT20"]["diff_pp"] >= gm["BTC"]["diff_pp"]
    e2 = all(so[a]["pctile"] is not None and so[a]["pctile"] < 0.9 for a in TRADFI)
    cmax = [abs(so[a]["diff_pp"]) for a in cr if so[a]["diff_pp"] is not None]
    e2b = bool(cmax) and all(so[a]["diff_pp"] is not None and abs(so[a]["diff_pp"]) < 0.5 * max(cmax) for a in TRADFI)
    return {"1_crypto_good_minus_bad_positive_and_above_p90": bool(e1), "1b_alt_diff_ge_btc_diff": bool(e1b),
            "2_stable_not_above_p90_for_gold_equities": bool(e2), "2b_tradfi_stable_diff_lt_half_of_crypto": bool(e2b),
            "3_own_dimension": "只报,见各资产 own_dimension"}


def load_live():
    weeks = sundays()
    lo = "2019-01-01"
    px = {}
    for s in CRYPTO:
        px[s] = Series((r["trade_date"], r["close"]) for r in get("ohlcv_daily", {"select": "trade_date,close", "symbol": f"eq.{s}", "source": "eq.binance_hist", "trade_date": f"gte.{lo}", "order": "trade_date.asc"}))
        print("loaded", s, len(px[s].d), flush=True)
    for s in TRADFI:
        px[s] = Series((r["trade_date"], r["close"]) for r in get("ohlcv_daily", {"select": "trade_date,close", "symbol": f"eq.{s}", "source": "eq.eodhd", "trade_date": f"gte.{lo}", "order": "trade_date.asc"}))
        print("loaded", s, len(px[s].d), flush=True)
    mac = {}
    for s in ("ust_2y", "ust_10y_real", "hy_oas"):
        mac[s] = Series((r["d"], r["value"]) for r in get("macro_daily", {"select": "d,value", "series": f"eq.{s}", "d": "gte.2018-06-01", "order": "d.asc"}))
    stable = Series((r["d"], r["value"]) for r in get("state_daily", {"select": "d,value", "entity": "eq.panel", "feature": "eq.stable_supply_30d", "d": "gte.2019-01-01", "order": "d.asc"}))
    # 山寨篮子:binance_hist 全部币的日线(收盘、成交量),一次取完(几十万行,要几分钟)
    allrows = get("ohlcv_daily", {"select": "symbol,trade_date,close,volume", "source": "eq.binance_hist", "trade_date": f"gte.{lo}", "order": "trade_date.asc,symbol.asc"})
    print("loaded binance_hist rows", len(allrows), flush=True)
    by = defaultdict(list)
    for r in allrows:
        if r.get("close") and r["symbol"] not in ("BTC", "ETH"):
            by[r["symbol"]].append((D(r["trade_date"]), float(r["close"]), float(r.get("volume") or 0.0) * float(r["close"])))
    supply = {}
    for sym, cid in SUPPLY_IDS.items():
        try:
            supply[sym] = Series((r["d"], r["circulating_supply"]) for r in get("coin_supply_daily", {"select": "d,circulating_supply", "coin_id": f"eq.{cid}", "order": "d.asc"}))
        except Exception as e:                                             # noqa: BLE001
            supply[sym] = f"{type(e).__name__}: {str(e)[:80]}"
    return weeks, px, mac, stable, by, supply


def build(weeks, px, mac, stable, by, supply):
    def trailing(sym_rows, d):
        return sum(v for (x, _, v) in sym_rows if d - dt.timedelta(days=30) < x <= d)
    alt = {s: Series((x, c) for x, c, _ in rows) for s, rows in by.items()}
    level, fwd = {}, {}
    for a in CRYPTO + TRADFI:
        age = 6
        level[a] = [px[a].asof(d, age) for d in weeks]
        nxt = [px[a].asof(d + dt.timedelta(weeks=H_WEEKS), age) for d in weeks]
        fwd[a] = [(n / c - 1) if (c and n) else None for c, n in zip(level[a], nxt)]
    idx, lev, f8, members_log = 1.0, [], [], []
    prev_members, prev_d = None, None
    for d in weeks:
        if prev_members:                                                    # 篮子自己的周线:每周换成分、等权,链起来
            rr = [alt[s].asof(d) / alt[s].asof(prev_d) - 1 for s in prev_members if alt[s].asof(d) and alt[s].asof(prev_d)]
            idx *= 1 + (float(np.mean(rr)) if rr else 0.0)
        ranked = sorted(((trailing(rows, d), s) for s, rows in by.items() if alt[s].asof(d)), reverse=True)[:20]
        mem = [s for v, s in ranked if v > 0]
        members_log.append(len(mem))
        lev.append(idx if mem else None)
        r8 = [alt[s].asof(d + dt.timedelta(weeks=H_WEEKS)) / alt[s].asof(d) - 1 for s in mem if alt[s].asof(d + dt.timedelta(weeks=H_WEEKS))]
        f8.append(float(np.mean(r8)) if len(r8) >= 10 else None)
        prev_members, prev_d = mem, d
    level["ALT20"], fwd["ALT20"] = lev, f8

    def direction(series, d, lag=91, age=10):
        a, b = series.asof(d, age), series.asof(d - dt.timedelta(days=lag), age)
        return None if a is None or b is None else bool(a > b)
    rate_up = [direction(mac["ust_2y"], d) for d in weeks]
    stable_neg = [(None if stable.asof(d, 3) is None else bool(stable.asof(d, 3) < 0)) for d in weeks]
    extra = {"BTC": ("halving_phase", [18 <= halving_month(d) < 30 for d in weeks], ("other", "18-30m")),
             "XAUUSD": ("real_yield_10y", [direction(mac["ust_10y_real"], d) for d in weeks], ("falling", "rising")),
             "ACWI": ("hy_oas", [direction(mac["hy_oas"], d) for d in weeks], ("narrowing", "widening")),
             "QQQ": ("hy_oas", [direction(mac["hy_oas"], d) for d in weeks], ("narrowing", "widening")),
             "ALT20": "篮子成员没有代码 → coin_id 的映射,流通量中位读不到"}
    for sym in SUPPLY_IDS:
        s = supply.get(sym)
        if not isinstance(s, Series) or len(s.d) < 400:
            extra[sym] = f"coin_supply_daily 不足一年({0 if not isinstance(s, Series) else len(s.d)} 天)" if not isinstance(s, str) else s
            continue
        flags = []
        for d in weeks:
            now, was = s.asof(d, 5), s.asof(d - dt.timedelta(days=30), 5)
            hist = [s.asof(d - dt.timedelta(days=k), 5) for k in range(30, 366, 7)]
            ch = [(hist[i] / hist[i + 4] - 1) for i in range(len(hist) - 4) if hist[i] and hist[i + 4]]
            flags.append(None if not (now and was and len(ch) >= 20) else bool((now / was - 1) > float(np.median(ch))))
        extra[sym] = ("supply_30d_vs_own_1y_median", flags, ("below", "above"))
    return level, fwd, rate_up, stable_neg, extra, members_log


def run(weeks, px, mac, stable, by, supply) -> dict:
    level, fwd, rate_up, stable_neg, extra, members_log = build(weeks, px, mac, stable, by, supply)
    rng = np.random.default_rng(SEED)
    res = analyse(weeks, level, fwd, rate_up, stable_neg, extra, rng)
    btc = res["BTC"]["weekly_x_rates"]
    repro = {k: (btc.get(k, {}).get("mean8"), v) for k, v in BTC_EXPECT.items()}
    # 自检(能失败):把切点之后的全部价格与成交额乘 2,切点及之前每一周的状态(各资产的周线、篮子的成分数)必须一格不变;
    # 而切点之后的周线至少有一处变了(否则说明这次扰动根本没起作用,自检是空的)。
    cut_i = len(weeks) // 2
    cut = weeks[cut_i]
    px2 = {k: Series((d, v * (2.0 if d > cut else 1.0)) for d, v in zip(sr.d, sr.v)) for k, sr in px.items()}
    by2 = {k: [(d, c * (2.0 if d > cut else 1.0), dv * (2.0 if d > cut else 1.0)) for d, c, dv in rows] for k, rows in by.items()}
    level2, _f2, _r2, _s2, _e2, members2 = build(weeks, px2, mac, stable, by2, supply)
    same_before = all([weekly_down(level[a], i) for i in range(cut_i + 1)] == [weekly_down(level2[a], i) for i in range(cut_i + 1)] for a in ASSETS) \
        and members_log[:cut_i + 1] == members2[:cut_i + 1]
    changed_after = any([weekly_down(level[a], i) for i in range(cut_i + 1, len(weeks))] != [weekly_down(level2[a], i) for i in range(cut_i + 1, len(weeks))] for a in ASSETS)
    checks = {"btc_reproduces_s844_5": {k: {"got": g, "want": w, "ok": g is not None and abs(g - w) <= 0.3} for k, (g, w) in repro.items()},
              "states_before_cut_ignore_future_prices": bool(same_before), "perturbation_changed_something_after_cut": bool(changed_after),
              "alt_members_min_median": [int(min(members_log)), int(np.median(members_log))]}
    return {"window": [str(W0), str(W1)], "weeks": len(weeks), "assets": res, "expectations": expectations(res), "self_checks": checks,
            "state_weeks": {"rates_rising": sum(1 for x in rate_up if x), "rates_falling": sum(1 for x in rate_up if x is False),
                            "stable_draining": sum(1 for x in stable_neg if x), "stable_adding": sum(1 for x in stable_neg if x is False)}}


def synthetic():
    """合成数据:只为把整条路走一遍(不联网)。利率与稳定币的状态决定加密的漂移,黄金与股票与它们无关。"""
    rng = np.random.default_rng(7)
    days = [dt.date(2018, 6, 1) + dt.timedelta(days=i) for i in range((dt.date(2026, 12, 31) - dt.date(2018, 6, 1)).days + 1)]
    y2 = np.cumsum(rng.normal(0, 0.02, len(days))) + 3.0
    stb = np.sin(np.arange(len(days)) / 180.0) * 0.02 + rng.normal(0, 0.002, len(days))
    drift = np.where((np.gradient(y2) < 0) & (stb > 0), 0.003, -0.0005)
    mk = lambda mu, vol: Series(zip(days, 100 * np.exp(np.cumsum(mu + rng.normal(0, vol, len(days))))))
    px = {"BTC": mk(drift, 0.03), "ETH": mk(drift * 1.2, 0.04), "SOL": mk(drift * 1.5, 0.05),
          "XAUUSD": mk(0.0003, 0.008), "ACWI": mk(0.0003, 0.01), "QQQ": mk(0.0004, 0.012)}
    mac = {"ust_2y": Series(zip(days, y2)), "ust_10y_real": Series(zip(days, y2 - 2)), "hy_oas": Series(zip(days, 3 + rng.normal(0, 0.1, len(days)).cumsum() * 0.05))}
    by = {f"A{i}": [(d, float(p), float(p) * (50 + i)) for d, p in zip(days, 10 * np.exp(np.cumsum(drift * 1.8 + rng.normal(0, 0.05, len(days)))))] for i in range(25)}
    supply = {"ETH": Series(zip(days, 1e8 * np.exp(np.cumsum(rng.normal(1e-5, 1e-5, len(days)))))), "SOL": "合成数据里故意读不到"}
    return sundays(), px, mac, Series(zip(days, stb)), by, supply


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    out = run(*(synthetic() if selftest else load_live()))
    for a in ASSETS:
        r = out["assets"][a]
        print("ASSET", a, json.dumps({"n": r["n_weeks"], "good_minus_bad": r["good_minus_bad"], "stable_only": r["stable_only"], "own": r["own_dimension"]}, ensure_ascii=False), flush=True)
    print("EXPECT", json.dumps(out["expectations"], ensure_ascii=False))
    print("CHECKS", json.dumps(out["self_checks"], ensure_ascii=False))
    if selftest:
        assert out["weeks"] == 381 and all(out["assets"][a]["n_weeks"] > 300 for a in ASSETS), "合成数据没走通"
        assert out["assets"]["SOL"]["own_dimension"]["name"] == "读不到" and out["assets"]["ETH"]["own_dimension"]["name"] != "读不到"
        assert out["assets"]["BTC"]["good_minus_bad"]["diff_pp"] > 0 and out["self_checks"]["states_before_cut_ignore_future_prices"] and out["self_checks"]["perturbation_changed_something_after_cut"]
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
