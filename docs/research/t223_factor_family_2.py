"""T-223 (lane-b) — S-696 第一次前向月度核对 + 第二族因子普查.

口径严格照 docs/research/s691_holdout.sql (Seth 版) 与 docs/research/s691_factor_zoo_discovery.sql:
  宇宙   : names = deriv_metrics_daily 的 symbol;px = asset_mcap_daily(source=coingecko_pro_market_chart)
           ∪ perp_cg_map(resolved) × cg_coin_mcap_daily;kept = n_overlap>=30 且 med_err<=0.05
  逐日   : mcap >= 20e6;每天每名一行
  y      : (p[d+30]/p[d]-1) - (btc[d+30]/btc[d]-1)      (精确日 join)
  因子   : f01 oi_value/mcap · f03 ln(oi_close[d]/oi_close[d-30]) · f07 taker7(≥5)
           f08 mom30 · f09 mom7 · f11 vol30(30 日 stddev of ln 收益, n>=25)
  判定量 : 规模控制的偏 Spearman;(r_vy - r_vs*r_ys)/sqrt((1-r_vs^2)(1-r_ys^2));每天 >=30 名
  汇总   : 月均 IC,t = 月均/月标准差*sqrt(月数)

只读:GET only,不改代码、不做 DDL、不入库。
"""
import bisect
import csv
import gzip
import json
import math
import os
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
MAC = "/Volumes/CometCloudAI/cometcloud-local/research"
CACHE = os.path.join(MAC, "t223", "cache")
RESULTS = os.path.join(HERE, "t223_results.json")

# ---------------------------------------------------------------- 窗口(预注册)
FWD_MONTH = "2026-10"          # A 段:第一个前向核对月
DISC = ("2023-01-01", "2024-12-31")   # B 段:发现段
HOLD = ("2025-01-01", "2026-09-30")   # B 段:留出段(封存)
MCAP_MIN = 20_000_000
MIN_NAMES = 30
CARD_LITERAL_LAST_DAY = "2026-10-02"   # 卡上写的"y 用到 2026-10-02 为止"

HOLD_SIGNS = {  # S-691 留出段冻结短名单(台账 S-691)
    "f03_doi30": -1, "f07_taker7": +1, "f08_mom30": -1, "f09_mom7": -1, "f11_vol30": -1,
}
HOLD_STATS = {  # s691_holdout_seth.json,main 口径(2025-01..2026-09,21 个月)
    "f01_oi_mcap": (-0.0582, -2.37), "f03_doi30": (-0.0653, -6.54), "f07_taker7": (0.0727, 4.48),
    "f08_mom30": (-0.0764, -2.57), "f09_mom7": (-0.0369, -2.53), "f11_vol30": (-0.1639, -4.62),
}
FACTORS = ["f01_oi_mcap", "f03_doi30", "f07_taker7", "f08_mom30", "f09_mom7", "f11_vol30"]


def d2s(d):
    return d.strftime("%Y-%m-%d")


def s2d(s):
    import datetime
    y, m, dd = (int(x) for x in s.split("-"))
    return datetime.date(y, m, dd)


def dadd(d, n):
    import datetime
    if isinstance(d, str):
        d = s2d(d)
    return d + datetime.timedelta(days=n)


def dspan(d, n):
    """d 往前 n 天的闭区间起点。"""
    import datetime
    if isinstance(d, str):
        d = s2d(d)
    return d - datetime.timedelta(days=n)


# ---------------------------------------------------------------- 读缓存
def read_csv_gz(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            yield row


def f2(x):
    if x is None:
        return None
    x = str(x).strip()
    if not x:
        return None
    try:
        v = float(x)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------- DB 只读小拉
def pull_tail(db):
    """补 DB 尾段:amcg / btc 到 2026-11-05(缓存停在 2026-11-01)。"""
    out = {}
    for name, table, sel, order, filt in [
        ("amcg_tail", "asset_mcap_daily", "symbol,d,price,mcap", "symbol.asc,d.asc",
         {"source": "eq.coingecko_pro_market_chart", "d": "gte.2026-11-01"}),
        ("btc_tail", "asset_mcap_daily", "d,price", "d.asc",
         {"source": "eq.coingecko_pro_market_chart", "coin_id": "eq.bitcoin", "d": "gte.2026-11-01"}),
    ]:
        path = os.path.join(CACHE, name + ".csv.gz")
        if os.path.exists(path) and os.path.getsize(path) > 0:
            out[name] = path
            continue
        rows = db.all(table, select=sel, order=order, filters=filt)
        with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=sel.split(","))
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in sel.split(",")})
        out[name] = path
    return out


# ---------------------------------------------------------------- 面板
class Panel(object):
    def __init__(self):
        self.px = defaultdict(dict)        # sym -> d -> (price, mcap, mult)
        self.deriv = defaultdict(dict)     # sym -> d -> (oi_close, oi_value, taker)
        self.btc = {}                      # d -> price
        self.kept = {}                     # sym -> (n_overlap, med_err)
        self.state = defaultdict(dict)     # feature -> d -> value
        self.rev = []                      # protocol_revenue rows
        self.cg_sym = {}                   # coin_id -> symbol (asset_mcap_daily)

    # ---------- load
    def load(self):
        amcg = os.path.join(CACHE, "amcg.csv.gz")
        for path in [amcg, os.path.join(CACHE, "amcg_tail.csv.gz")]:
            if not os.path.exists(path):
                continue
            for r in read_csv_gz(path):
                p, m = f2(r.get("price")), f2(r.get("mcap"))
                if not p or p <= 0:
                    continue
                self.px[r["symbol"].upper()][r["d"]] = (p, m, 1.0)
        # perp 侧:只在不在 amcg 名单里才用(S-691 px_all 的口径)
        am_syms = set(self.px)
        pmap = {}
        for r in read_csv_gz(os.path.join(CACHE, "perp_cg_map.csv.gz")):
            if r.get("verdict") == "resolved" and r.get("coin_id"):
                pmap[r["symbol"]] = (r["coin_id"], f2(r.get("mult")) or 1.0)
        cg = defaultdict(dict)
        for r in read_csv_gz(os.path.join(CACHE, "cg_mcap.csv.gz")):
            p, m = f2(r.get("price")), f2(r.get("mcap"))
            if p and p > 0:
                cg[r["coin_id"]][r["d"]] = (p, m)
        for sym, (cid, mult) in pmap.items():
            if sym in am_syms:
                continue
            for d, (p, m) in cg.get(cid, {}).items():
                self.px[sym][d] = (p, m, mult)
        for path in [os.path.join(CACHE, "btc.csv.gz"), os.path.join(CACHE, "btc_tail.csv.gz")]:
            if not os.path.exists(path):
                continue
            for r in read_csv_gz(path):
                p = f2(r.get("price"))
                if p and p > 0:
                    self.btc[r["d"]] = p
        for r in read_csv_gz(os.path.join(CACHE, "deriv_metrics_daily.csv.gz")):
            self.deriv[r["symbol"]][r["d"]] = (f2(r.get("oi_close")), f2(r.get("oi_value_close")),
                                               f2(r.get("taker_ratio_mean")))
        for r in read_csv_gz(os.path.join(CACHE, "state_daily.csv.gz")):
            v = f2(r.get("value"))
            if v is not None:
                self.state[r["feature"]][r["d"]] = v
        for r in read_csv_gz(os.path.join(CACHE, "protocol_revenue_daily.csv.gz")):
            self.rev.append(r)
        self._precompute()

    def _precompute(self):
        """每名:价格数组 + ln 收益 + vol30 窗口;OI/taker 的滚动窗口。"""
        self.pdates = {}   # sym -> [d]
        self.px_list = {}  # sym -> [price]
        self.lr = {}       # sym -> [(d, lr)]
        for sym, dd in self.px.items():
            ds = sorted(dd)
            ps = [dd[d][0] for d in ds]
            self.pdates[sym] = ds
            self.px_list[sym] = ps
            lr = []
            for i in range(1, len(ds)):
                if ps[i - 1] > 0 and ps[i] > 0:
                    lr.append((ds[i], math.log(ps[i] / ps[i - 1])))
            self.lr[sym] = lr
        self.tk = {}  # sym -> [(d, taker)]
        for sym, dd in self.deriv.items():
            self.tk[sym] = sorted((d, v[2]) for d, v in dd.items() if v[2] is not None)

    # ---------- 宇宙
    def build_universe(self):
        names = set(self.deriv)
        px_all = {s: {d: v for d, v in dd.items() if s in names} for s, dd in self.px.items()}
        errs = defaultdict(list)
        n_ov = defaultdict(int)
        for sym, dd in self.deriv.items():
            for d, (oi_c, oi_v, _tk) in dd.items():
                if d < "2023-01-01" or not oi_c or oi_c <= 0 or not oi_v or oi_v <= 0:
                    continue
                pv = px_all.get(sym, {}).get(d)
                if not pv:
                    continue
                price, _m, mult = pv
                if not price or price <= 0:
                    continue
                errs[sym].append(abs(price * mult / (oi_v / oi_c) - 1.0))
                n_ov[sym] += 1
        for sym in n_ov:
            med = statistics.median(errs[sym])
            if n_ov[sym] >= 30 and med <= 0.05:
                self.kept[sym] = (n_ov[sym], med)
        self.px_all = px_all

    # ---------- 特征
    def vol30(self, sym, d):
        """30 日窗口内 ln 收益的样本标准差 + 计数(S-691: nlr30 >= 25)。d 为 'YYYY-MM-DD'。"""
        lr = self.lr.get(sym)
        if not lr:
            return None, 0
        ds = [x[0] for x in lr]
        lo = bisect.bisect_left(ds, dspan(d, 29).isoformat())
        hi = bisect.bisect_right(ds, d)
        vals = [x[1] for x in lr[lo:hi]]
        if len(vals) < 2:
            return None, len(vals)
        return statistics.stdev(vals), len(vals)

    def tkr7(self, sym, d):
        tk = self.tk.get(sym)
        if not tk:
            return None, 0
        ds = [x[0] for x in tk]
        lo = bisect.bisect_left(ds, dspan(d, 6).isoformat())
        hi = bisect.bisect_right(ds, d)
        vals = [x[1] for x in tk[lo:hi]]
        if len(vals) < 5:
            return None, len(vals)
        return sum(vals) / len(vals), len(vals)

    def price(self, sym, d):
        v = self.px.get(sym, {}).get(d)
        return v[0] if v else None

    def mcap(self, sym, d):
        v = self.px.get(sym, {}).get(d)
        return v[1] if v else None

    def rows_for_day(self, d, need_y=True):
        """一天一行: y, size, 各因子。d 可以是 date 或 'YYYY-MM-DD'。"""
        if isinstance(d, str):
            d = s2d(d)
        ds = d.isoformat()
        out = []
        n_pre = 0
        for sym in sorted(self.kept):
            pv = self.px.get(sym, {}).get(ds)
            if not pv:
                continue
            price, mcap, _mult = pv
            if not price or price <= 0 or not mcap or mcap < MCAP_MIN:
                continue
            n_pre += 1
            row = {"sym": sym, "size": math.log(mcap)}
            btc0 = self.btc.get(ds)
            ok = True
            if need_y:
                p30 = self.price(sym, dadd(d, 30).isoformat())
                b30 = self.btc.get(dadd(d, 30).isoformat())
                if not p30 or not btc0 or not b30:
                    ok = False
                else:
                    row["y"] = (p30 / price - 1.0) - (b30 / btc0 - 1.0)
            if not ok:
                continue
            oi = self.deriv.get(sym, {}).get(ds)
            row["has_oi"] = bool(oi and oi[1] and oi[1] > 0)
            if row["has_oi"]:
                row["f01_oi_mcap"] = oi[1] / mcap
                oi30 = self.deriv.get(sym, {}).get(dadd(d, -30).isoformat())
                if oi30 and oi30[0] and oi30[0] > 0 and oi[0] and oi[0] > 0:
                    row["f03_doi30"] = math.log(oi[0] / oi30[0])
            t, _n = self.tkr7(sym, ds)
            if t is not None:
                row["f07_taker7"] = t
            p30 = self.price(sym, dadd(d, -30).isoformat())
            b30 = self.btc.get(dadd(d, -30).isoformat())
            if p30 and b30 and btc0:
                row["f08_mom30"] = (price / p30 - 1.0) - (btc0 / b30 - 1.0)
            p7 = self.price(sym, dadd(d, -7).isoformat())
            b7 = self.btc.get(dadd(d, -7).isoformat())
            if p7 and b7 and btc0:
                row["f09_mom7"] = (price / p7 - 1.0) - (btc0 / b7 - 1.0)
            v, nlr = self.vol30(sym, ds)
            if v is not None and nlr >= 25:
                row["f11_vol30"] = v
            out.append(row)
        return out, n_pre


# ---------------------------------------------------------------- 统计
def avg_rank(vals):
    """SQL: rank() over (order by v) + (count(*) over (partition by v) - 1)/2。"""
    n = len(vals)
    order = sorted(range(n), key=lambda i: vals[i])
    counts = defaultdict(int)
    for v in vals:
        counts[v] += 1
    less = defaultdict(int)
    for i, v in enumerate(vals):
        less[v] += 1
    seen = {}
    r = [0.0] * n
    for idx in order:
        v = vals[idx]
        seen[v] = seen.get(v, 0) + 1
        less[v] -= 1
    # 严格小于 v 的个数
    cnt = defaultdict(int)
    for v in vals:
        cnt[v] += 1
    uniq = sorted(cnt)
    cumul = {}
    run = 0
    for v in uniq:
        cumul[v] = run
        run += cnt[v]
    for i, v in enumerate(vals):
        r[i] = 1.0 + cumul[v] + (cnt[v] - 1) / 2.0
    return r


def corr(a, b):
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sa = sum((x - ma) ** 2 for x in a)
    sb = sum((x - mb) ** 2 for x in b)
    if sa <= 0 or sb <= 0:
        return None
    sab = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return sab / math.sqrt(sa * sb)


def partial_ic(rows, factor):
    """规模控制的偏 Spearman: 控制 size 的 factor→y 偏相关。"""
    sel = [r for r in rows if r.get(factor) is not None and r.get("y") is not None]
    if len(sel) < 3:
        return None, len(sel)
    v = [r[factor] for r in sel]
    y = [r["y"] for r in sel]
    s = [r["size"] for r in sel]
    rv, ry, rs = avg_rank(v), avg_rank(y), avg_rank(s)
    r_vy, r_vs, r_ys = corr(rv, ry), corr(rv, rs), corr(ry, rs)
    if r_vy is None or r_vs is None or r_ys is None:
        return None, len(sel)
    if abs(r_vs) >= 1 or abs(r_ys) >= 1:
        return None, len(sel)
    return (r_vy - r_vs * r_ys) / math.sqrt((1 - r_vs * r_vs) * (1 - r_ys * r_ys)), len(sel)


# ---------------------------------------------------------------- A 段:前向核对
# S-696(a):前向信号日 ≥ 2026-09-27;每个自然月到期后重算一次;前向月数 ≥ 3 且累计同号且 |月 t| ≥ 2 ⇒ 确认。
# 卡上要的「2026-10 信号月」= 信号日 2026-10-01 起(y 需 30 天,数据到 2026-11-04 ⇒ 10-05 为止)。
FWD_WINDOWS = [
    ("F1_s696_first_forward_month", "2026-09-27", "2026-09-30"),
    ("F2_october_signal_month", "2026-10-01", "2026-10-31"),
    ("F_all_forward_to_date", "2026-09-27", "2026-10-31"),
]


def part_a(pnl):
    daily = {}
    d = s2d("2026-09-27")
    end = s2d("2026-10-31")
    while d <= end:
        rows, n_pre = pnl.rows_for_day(d)
        entry = {"d": d.isoformat(), "n_px": len(rows), "n_mcap_pass": n_pre,
                 "has_y": 1 if rows else 0, "ic": {}}
        for reading in ("main", "literal"):
            for f in FACTORS:
                sub = [r for r in rows if reading == "literal" or r.get("has_oi")]
                ic, n = partial_ic(sub, f)
                if ic is not None and n >= MIN_NAMES:
                    entry["ic"].setdefault(reading, {})[f] = {"ic": round(ic, 4), "n": n}
        daily[d.isoformat()] = entry
        d = dadd(d, 1)
    # 汇总:每个窗口 × 因子
    summary = {}
    for label, lo, hi in FWD_WINDOWS:
        days = [k for k in sorted(daily) if lo <= k <= hi]
        for reading in ("main", "literal"):
            for f in FACTORS:
                series = [(k, daily[k]["ic"][reading][f]["ic"], daily[k]["ic"][reading][f]["n"])
                          for k in days if reading in daily[k]["ic"] and f in daily[k]["ic"][reading]]
                if not series:
                    continue
                ics = [x[1] for x in series]
                mean_ic = sum(ics) / len(ics)
                t = None
                if len(ics) > 1 and statistics.stdev(ics) > 0:
                    t = mean_ic / statistics.stdev(ics) * math.sqrt(len(ics))
                sign = HOLD_SIGNS.get(f)
                summary.setdefault(label, {}).setdefault(reading, {})[f] = {
                    "window": [lo, hi], "n_days": len(series), "mean_ic": round(mean_ic, 4),
                    "t_days": round(t, 2) if t is not None else None,
                    "pos_days": sum(1 for x in ics if x > 0),
                    "days_same_sign_as_holdout": sum(
                        1 for x in ics if sign is not None and (x > 0) == (sign > 0)),
                    "holdout_sign": sign,
                    "same_sign_as_holdout": (None if sign is None else (mean_ic > 0) == (sign > 0)),
                    "holdout_mean_ic": HOLD_STATS[f][0], "holdout_t": HOLD_STATS[f][1],
                    "daily": [(k, ic, n) for k, ic, n in series],
                }
    return daily, summary


def holdout_replication(pnl):
    """自校验:用同一套代码复算 S-691 留出段(2025-01-01..2026-09-26),与台账 s691_holdout_seth.json 比。
    口径错的话这里先错 —— 前向核对的数字才可信。"""
    import datetime
    days = []
    d = s2d("2025-01-01")
    end = s2d("2026-09-26")
    while d <= end:
        days.append(d)
        d = dadd(d, 1)
    per = {r: {f: [] for f in FACTORS} for r in ("main", "literal")}
    names = {r: {f: [] for f in FACTORS} for r in ("main", "literal")}
    for dd in days:
        rows, _n_pre = pnl.rows_for_day(dd)
        if not rows:
            continue
        for reading in ("main", "literal"):
            sub = [r for r in rows if reading == "literal" or r.get("has_oi")]
            for f in FACTORS:
                ic, n = partial_ic(sub, f)
                if ic is not None and n >= MIN_NAMES:
                    per[reading][f].append((dd.isoformat(), ic))
                    names[reading][f].append(n)
    out = {}
    for reading in ("main", "literal"):
        out[reading] = {}
        for f in FACTORS:
            ser = per[reading][f]
            if not ser:
                continue
            months = defaultdict(list)
            for ds_, ic in ser:
                months[ds_[:7]].append(ic)
            mics = [sum(v) / len(v) for _k, v in sorted(months.items())]
            mean_ic = sum(mics) / len(mics)
            t = None
            if len(mics) > 1 and statistics.stdev(mics) > 0:
                t = mean_ic / statistics.stdev(mics) * math.sqrt(len(mics))
            out[reading][f] = {
                "n_months": len(mics), "mean_ic": round(mean_ic, 4),
                "t_month": round(t, 2) if t is not None else None,
                "pos_months": sum(1 for x in mics if x > 0),
                "names_avg": round(sum(names[reading][f]) / len(names[reading][f]), 1),
                "ledger_mean_ic": HOLD_STATS[f][0], "ledger_t": HOLD_STATS[f][1],
                "delta_mean_ic": round(mean_ic - HOLD_STATS[f][0], 4),
            }
    return out


# ---------------------------------------------------------------- B 段:第二族
G_SPEC = {
    "G1": "协议收入 30 天和 ÷ 市值(protocol_revenue_daily.revenue_30d ÷ mcap)",
    "G2": "收入 30 天变化 ln(r30 / r30_prev)",
    "G3": "持币人收入占比(holders_30d ÷ revenue_30d)",
    "G4": "市值 ÷ 完全稀释(asset_mcap_daily × cg_coin_mcap_daily 拼 FDV)",
    "G5": "稳定币供给 30 天变化(state_daily panel.stable_supply_30d)—— 共用时间因子,只做时间序列 t 检",
    "G6": "交易所净流入(state_daily)",
}


def universe_month_end(pnl, win):
    """窗口内每月最后一天 + 该天的等权宇宙 30 天前瞻收益(相对 BTC)。"""
    out = []
    d = s2d(win[0])
    end = s2d(win[1])
    while d <= end:
        m_end = d
        d2 = dadd(d, 1)
        while d2 <= end:
            if d2.month != d.month:
                break
            m_end = d2
            d2 = dadd(d2, 1)
        out.append(m_end)
        d = dadd(m_end, 1)
    return out


def g5_timeseries(pnl, win):
    """G5: 月末 stable_supply_30d 对 等权宇宙 30 天前瞻收益(相对 BTC)的 OLS t 检。"""
    days = universe_month_end(pnl, win)
    xs, ys, raw, rows_out = [], [], [], []
    for d in days:
        ds = d.isoformat()
        x = pnl.state.get("stable_supply_30d", {}).get(ds)
        if x is None:
            continue
        rows, _n_pre = pnl.rows_for_day(d, need_y=True)
        if not rows or rows[0].get("y") is None:
            continue
        ew = sum(r["y"] for r in rows) / len(rows)
        # 原始(不相对 BTC)的等权 30 天收益
        btc0, btc30 = pnl.btc.get(ds), pnl.btc.get(dadd(d, 30).isoformat())
        raw_ret = None
        if btc0 and btc30:
            rets = []
            for sym in pnl.kept:
                p0 = pnl.price(sym, ds)
                p30 = pnl.price(sym, dadd(d, 30).isoformat())
                if p0 and p30:
                    rets.append(p30 / p0 - 1.0)
            if rets:
                raw_ret = sum(rets) / len(rets)
        xs.append(x)
        ys.append(ew)
        raw.append(raw_ret)
        rows_out.append({"d": ds, "x": round(x, 5), "ew_fwd_rel_btc": round(ew, 5),
                         "ew_fwd_raw": (round(raw_ret, 5) if raw_ret is not None else None),
                         "n_names": len(rows)})
    n = len(xs)
    out = {"window": list(win), "n_months": n}
    if n < 3:
        out["t"] = None
        out["note"] = "n<3"
        out["rows"] = rows_out
        return out
    r = corr(xs, ys)
    t = None
    if r is not None and abs(r) < 1:
        t = r * math.sqrt((n - 2) / (1 - r * r))
    out["r"] = round(r, 4) if r is not None else None
    out["t"] = round(t, 2) if t is not None else None
    out["slope_sign"] = None if t is None else (1 if t > 0 else -1)
    out["pos_months"] = sum(1 for a, b in zip(xs, ys) if (a * b) > 0)
    out["rows"] = rows_out
    return out


def part_b_availability(pnl):
    """每个 G 因子的数据可得性(发现段 / 留出段)。"""
    rev_days = sorted(set(r["d"] for r in pnl.rev))
    rev_geo = (rev_days[0], rev_days[-1]) if rev_days else (None, None)
    has_fd = False  # asset_mcap_daily / cg_coin_mcap_daily 都只有 price+mcap,无 FDV
    feats = sorted(pnl.state)
    netflow_feats = [f for f in feats if any(k in f.lower() for k in ("flow", "inflow", "netflow"))]
    avail = {}
    for g, spec in G_SPEC.items():
        rec = {"spec": spec}
        if g in ("G1", "G2", "G3"):
            rec["source"] = "protocol_revenue_daily"
            rec["source_coverage"] = rev_geo
            rec["disc_overlap_days"] = len([d for d in rev_days if DISC[0] <= d <= DISC[1]])
            rec["hold_overlap_days"] = len([d for d in rev_days if HOLD[0] <= d <= HOLD[1]])
            rec["verdict"] = ("读不到" if rec["disc_overlap_days"] == 0 and rec["hold_overlap_days"] == 0
                              else "部分可算")
        elif g == "G4":
            rec["source"] = "asset_mcap_daily + cg_coin_mcap_daily"
            rec["has_fdv_column"] = has_fd
            rec["verdict"] = "读不到" if not has_fd else "可算"
        elif g == "G5":
            ss = pnl.state.get("stable_supply_30d", {})
            ds = sorted(ss)
            rec["source"] = "state_daily panel.stable_supply_30d"
            rec["source_coverage"] = (ds[0], ds[-1]) if ds else None
            rec["nonempty_days"] = len(ds)
            rec["verdict"] = "可算(时间序列)"
        elif g == "G6":
            rec["source"] = "state_daily"
            rec["candidate_features"] = netflow_feats
            rec["verdict"] = "读不到" if not netflow_feats else "可算"
        avail[g] = rec
    return avail


def g1_exploratory(pnl):
    """探索性:protocol_revenue_daily 仅有 15 天 —— 那 15 天的 G1 分布 + 后向 30 天收益相关。"""
    rev = pnl.rev
    days = sorted(set(r["d"] for r in rev))
    by_day = defaultdict(list)
    for r in rev:
        by_day[r["d"]].append(r)
    # token 映射:sym_coin_id.json 是 symbol → coin_id,这里反过来用
    sym_coin = json.load(open(os.path.join(CACHE, "sym_coin_id.json")))
    rev_coin = {}
    for s, c in sym_coin.items():
        rev_coin.setdefault(c, s)
    out = {"days": days, "n_protocol_rows": len(rev)}
    # 只用能映射到本宇宙 symbol 的协议
    mapped = []
    for r in rev:
        gid = (r.get("gecko_id") or "").strip()
        if not gid:
            continue
        sym = rev_coin.get(gid)
        if sym and sym in pnl.kept:
            r30 = f2(r.get("revenue_30d"))
            mcap = pnl.mcap(sym, r["d"])
            if r30 is not None and mcap:
                mapped.append({"d": r["d"], "sym": sym, "rev30": r30, "mcap": mcap,
                               "g1": r30 / mcap,
                               "g3": (f2(r.get("holders_30d")) / r30) if (f2(r.get("holders_30d")) is not None and r30 > 0) else None})
    out["n_mapped"] = len(mapped)
    out["mapped_sample"] = mapped[:8]
    if mapped:
        g1s = [m["g1"] for m in mapped]
        out["g1_mean"] = sum(g1s) / len(g1s)
        out["g1_median"] = statistics.median(g1s)
        out["g1_max"] = max(g1s)
    # 后向 30 天收益(探索,非前瞻)
    back = []
    for m in mapped:
        d0 = s2d(m["d"])
        d30 = dadd(d0, -30).isoformat()
        p0 = pnl.price(m["sym"], m["d"])
        pb = pnl.price(m["sym"], d30)
        if p0 and pb:
            back.append((m["g1"], p0 / pb - 1.0))
    if len(back) > 5:
        r = corr([x[0] for x in back], [x[1] for x in back])
        out["backward_corr_g1_vs_ret30"] = round(r, 4) if r is not None else None
        out["n_backward"] = len(back)
    return out


# ---------------------------------------------------------------- main
def main():
    from t219_db import DB
    db = DB()
    pull_tail(db)
    pnl = Panel()
    pnl.load()
    pnl.build_universe()
    daily, summary = part_a(pnl)
    hold_repl = holdout_replication(pnl)
    g5_disc = g5_timeseries(pnl, DISC)
    g5_hold = g5_timeseries(pnl, HOLD)
    avail = part_b_availability(pnl)
    g1x = g1_exploratory(pnl)
    res = {
        "card": "T-223",
        "lane": "lane-b",
        "run_utc": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "universe": {"n_kept": len(pnl.kept), "n_deriv_syms": len(pnl.deriv),
                     "n_px_syms": len(pnl.px), "n_btc_days": len(pnl.btc),
                     "kept_sample": dict(list(sorted(pnl.kept.items()))[:5])},
        "part_a_forward_2026_10": {"daily": daily, "summary": summary,
                                   "card_literal_last_day": CARD_LITERAL_LAST_DAY},
        "selfcheck_holdout_replication": hold_repl,
        "part_b_second_family": {"availability": avail, "g5_discovery": g5_disc,
                                 "g5_holdout": g5_hold, "g1_exploratory": g1x},
    }
    with open(RESULTS, "w") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print("[universe] kept=%d deriv=%d px=%d" % (len(pnl.kept), len(pnl.deriv), len(pnl.px)))
    for dd in sorted(daily):
        e = daily[dd]
        ics = e["ic"].get("main", {})
        print("  %s n_px=%-4d has_y=%d  %s" % (
            dd, e["n_px"], e["has_y"],
            " ".join("%s=%+.3f" % (f, ics[f]["ic"]) for f in FACTORS if f in ics)))
    print("[selfcheck] holdout replication (main reading)")
    for f, v in sorted(hold_repl.get("main", {}).items()):
        print("  %-12s months=%d mean_ic=%+.4f (ledger %+.4f, Δ%+.4f) t=%s (ledger %+.2f) names=%s"
              % (f, v["n_months"], v["mean_ic"], v["ledger_mean_ic"], v["delta_mean_ic"],
                 v["t_month"], v["ledger_t"], v["names_avg"]))
    print("[A summary main]")
    for f, v in sorted(summary.get("main", {}).items()):
        print("  %-12s days=%d mean_ic=%+.4f t=%s same_sign=%s (holdout %+.4f t=%+.2f)"
              % (f, v["n_days"], v["mean_ic"], v["t_month"], v["same_sign_as_holdout"],
                 v["holdout_mean_ic"], v["holdout_t"]))
    print("[B availability]", json.dumps({k: v["verdict"] for k, v in avail.items()}, ensure_ascii=False))
    print("[G5 disc]", {k: g5_disc.get(k) for k in ("n_months", "r", "t", "pos_months")})
    print("[G5 hold]", {k: g5_hold.get(k) for k in ("n_months", "r", "t", "pos_months")})
    print("[G1 exploratory]", {k: g1x.get(k) for k in ("days", "n_protocol_rows", "n_mapped", "g1_median")})
    print("[written]", RESULTS)


if __name__ == "__main__":
    main()
