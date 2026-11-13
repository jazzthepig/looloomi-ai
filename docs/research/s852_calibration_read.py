"""T-375 附属:读出 S-852 用到的各条序列的**最新**读数,并给 scenarios/lane-a-T-375.json 里的概率定标。

只读。不改 s851/s852 的任何一行 —— 那两个是 Seth 写的,这里只 import 取它的 get()。
用法(仓库根目录):
    python3 docs/research/s852_calibration_read.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os

_sp = importlib.util.spec_from_file_location("s851", os.path.join(os.path.dirname(os.path.abspath(__file__)), "s851_watch_base_rate.py"))
S = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(S)

MACRO = ("fng", "btc_mvrv", "ust_2y", "usdjpy", "btc_etf_net_flow_usd")
STATE = ("funding_7d_ann_binance", "stable_supply_30d", "taker_buy_share_30d", "dist_200")


def last_macro(series: str):
    rows = S.get("macro_daily", {"select": "d,value", "series": "eq." + series, "order": "d.asc"})
    rows = [r for r in rows if r.get("value") is not None]
    return (rows[-1].get("d"), rows[-1].get("value")) if rows else (None, None)


def last_state(feature: str):
    rows = S.get("state_daily", {"select": "d,value", "entity": "eq.panel", "feature": "eq." + feature, "order": "d.asc"})
    rows = [r for r in rows if r.get("value") is not None]
    return (rows[-1].get("d"), rows[-1].get("value")) if rows else (None, None)


def macro_series(series: str):
    rows = S.get("macro_daily", {"select": "d,value", "series": "eq." + series, "order": "d.asc"})
    return [(S.D(r["d"]), float(r["value"])) for r in rows if r.get("value") is not None]


def state_series(feature: str):
    rows = S.get("state_daily", {"select": "d,value", "entity": "eq.panel", "feature": "eq." + feature, "order": "d.asc"})
    return [(S.D(r["d"]), float(r["value"])) for r in rows if r.get("value") is not None]


def hit_within(series, want, horizon_days: int) -> tuple[int, int, float]:
    """在**当前**取值不满足 want 的那些历史上,往后 horizon_days 个交易日内有没有出现过满足 want 的值。

    返回 (样本数, 命中数, 命中率)。只用 ≤ 今天的日期(不看未来)。"""
    today = series[-1][0]
    idx = {d: v for d, v in series}
    days = [d for d, _ in series if d <= today]
    cond = lambda v: want(v)                                        # noqa: E731
    n = h = 0
    for i, d in enumerate(days):
        if cond(series[i][1]):
            continue
        n += 1
        window = [idx.get(days[j]) for j in range(i + 1, min(i + 1 + horizon_days, len(days)))]
        if any(v is not None and cond(v) for v in window):
            h += 1
    return n, h, (h / n if n else float("nan"))


def persist(series, want, horizon_days: int) -> tuple[int, int, float]:
    """在**当前**取值满足 want 的那些历史上,恰好 horizon_days 个交易日之后是否仍满足。

    返回 (样本数, 命中数, 命中率)。只用 ≤ 今天的日期。"""
    today = series[-1][0]
    days = [d for d, _ in series if d <= today]
    n = h = 0
    for i, d in enumerate(days):
        if not want(series[i][1]):
            continue
        j = i + horizon_days
        if j >= len(days):
            continue
        n += 1
        if want(series[j][1]):
            h += 1
    return n, h, (h / n if n else float("nan"))


def main() -> None:
    for s in MACRO:
        print("macro:%-24s %s" % (s, last_macro(s)))
    for f in STATE:
        print("state:%-24s %s" % (f, last_state(f)))
    bars = S.get("ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC", "source": "eq.binance_hist", "order": "trade_date.asc"})
    print("close:BTC%-18s %s" % ("", bars[-1] if bars else None))

    print("\n-- 条件现状(三条先行条件,需 ≥2 条且 dist_200>0)--")
    d200 = state_series("dist_200")
    taker = state_series("taker_buy_share_30d")
    stable = state_series("stable_supply_30d")
    y2 = macro_series("ust_2y")
    print("dist_200>0 :", d200[-1][1] > 0, " taker<0.5 :", taker[-1][1] < 0.5,
          " stable<=0 :", stable[-1][1] <= 0, " ust_2y vs 91d :", y2[-1][1] > [v for d, v in y2 if d <= y2[-1][0] - dt.timedelta(days=91)][-1])
    print("dist_200>0 的交易日占比(全样本): %.1f%%" % (100.0 * sum(1 for _, v in d200 if v > 0) / len(d200)))

    print("\n-- 定标:当前不满足时,未来 N 个交易日内满足的历史频率 --")
    for label, series, want, horizon in (
        ("dist_200 > 0", d200, lambda v: v > 0, 22),
        ("fng >= 50", macro_series("fng"), lambda v: v >= 50, 22),
        ("btc_mvrv < 2.20", macro_series("btc_mvrv"), lambda v: v < 2.20, 22),
        ("stable_supply_30d <= 0", stable, lambda v: v <= 0, 22),
    ):
        n, h, p = hit_within(series, want, horizon)
        cur = series[-1][1]
        print("%-26s 当前=%-10s 满足=%s  N=%d 命中=%d 频率=%.3f" % (label, round(cur, 4), want(cur), n, h, p))

    print("\n-- 定标:当前满足时,+22 个交易日(≈31 自然日)后仍满足的历史频率 --")
    for label, series, want in (
        ("dist_200 > 0", d200, lambda v: v > 0),
        ("fng < 50", macro_series("fng"), lambda v: v < 50),
        ("btc_mvrv < 2.20", macro_series("btc_mvrv"), lambda v: v < 2.20),
        ("stable_supply_30d <= 0", stable, lambda v: v <= 0),
        ("taker_buy_share_30d >= 0.5", taker, lambda v: v >= 0.5),
    ):
        n, h, p = persist(series, want, 22)
        cur = series[-1][1]
        print("%-26s 当前=%-10s 满足=%s  N=%d 命中=%d 频率=%.3f" % (label, round(cur, 4), want(cur), n, h, p))

    print("\n-- 从「当前不满足」出发,+22 个交易日后**恰好**满足的频率 --")
    for label, series, want in (
        ("dist_200 > 0", d200, lambda v: v > 0),
        ("fng >= 50", macro_series("fng"), lambda v: v >= 50),
    ):
        n = h = 0
        days = [d for d, _ in series if d <= series[-1][0]]
        for i, d in enumerate(days):
            if want(series[i][1]) or i + 22 >= len(days):
                continue
            n += 1
            if want(series[i + 22][1]):
                h += 1
        print("%-26s N=%d 命中=%d 频率=%.3f" % (label, n, h, (h / n if n else float("nan"))))

    print("\n-- 周线闸门(S.weekly_down_days):今天是否已坏 --")
    bars = S.get("ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC", "source": "eq.binance_hist", "order": "trade_date.asc"})
    bdays = [S.D(r["trade_date"]) for r in bars]
    bclose = {S.D(r["trade_date"]): float(r["close"]) for r in bars}
    wd = S.weekly_down_days(bdays, bclose)
    today = bdays[-1]
    print("最后交易日 %s 收盘 %.0f  周线已坏=%s" % (today, bclose[today], wd.get(today)))
    print("若去掉趋势闸门(dist_200>0),今天三条先行条件里成立 %d 条" % (
        (1 if taker[-1][1] < 0.5 else 0) + (1 if stable[-1][1] <= 0 else 0) + (1 if y2[-1][1] > [v for d, v in y2 if d <= y2[-1][0] - dt.timedelta(days=91)][-1] else 0)))

    print("\n-- S-852 结果里,每段在 开始/最高点/结束 三个时点的读数中位数 --")
    import json
    res = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "s852_results.json"), encoding="utf-8"))
    eps = res["episodes"]
    keys = ("fng", "btc_mvrv", "funding_7d_ann", "taker_buy_share_30d", "stable_supply_30d", "ust_2y", "usdjpy", "btc_etf_flow_5d_bn")

    def med(xs):
        xs = sorted(xs)
        n = len(xs)
        return None if not n else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2)

    for k in keys:
        row = []
        for w in ("start", "peak", "end"):
            xs = [e["at_" + w].get(k) for e in eps if e["at_" + w].get(k) is not None]
            row.append("n=%d med=%s" % (len(xs), med(xs)))
        rise = sum(1 for e in eps if (e["at_peak"].get(k) is not None and e["at_start"].get(k) is not None and e["at_peak"][k] > e["at_start"][k]))
        have = sum(1 for e in eps if e["at_start"].get(k) is not None)
        print("%-22s start: %-20s peak: %-20s end: %-20s peak>start %d/%d" % (k, row[0], row[1], row[2], rise, have))


if __name__ == "__main__":
    main()
