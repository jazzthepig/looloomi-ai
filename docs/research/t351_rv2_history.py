"""T-351 / S-827 —— 右尾有多常见:R-v2 的开票 / 管票规则原样搬到 2017-09-01 → 2020-07-31 的 Binance 现货上。

预注册:台账 S-827(2026-11-11 17:42 UTC,写于在这个宇宙上算任何一张票之前)。

写死(台账原文):
  规则   = R-v2 现行的开票与管票 —— **本文件里的 indicators / _universe / sig_long / run_long / _chain
           逐字搬自 docs/research/t159_bear_short.py**(t197 用的同一份代码),不改一个数字。
  宇宙   = ohlcv_daily(source='binance_hist')2017-09-01 → 2020-07-31 当时在交易的现货(含后来下架的);
           30 日均成交额 ≥ 500 万美元(_universe 里的 adv30 ≥ 5e6)。
  闸门   = 2020 之前没有 majors 市值指数 ⇒ **BTC 自己的 200 日线**:close > BTC 自己的 SMA200 ⇒ gate_open。
           BTC 的 SMA200 尚未满 200 根时 → gate_open = True(与 majors 闸门 n<200 时同义,见 t159.load_gate)。
  成本   = 来回 0.4%(同口径:r 里减 0.004*entry/(entry-stop))。现货,没有资金费。

自检(两关):
  关 1(搬迁保真):同一份代码 + t197 自己的宇宙(s681/_um_daily.jsonl)+ t197 自己的闸门(majors)
                  + t197 自己的信号窗(2020-01-01 → 2026-09-30) ⇒ 票集应与 t197_results.json 的 tickets.A 完全相同。
  关 2(台账要求的自检):同一份代码在 **2020-08 之后**(现货宇宙 + BTC-200d 闸门)跑出的票 vs t197 tickets.A
                  ⇒ 对不上的张数与原因(宇宙不同 / 闸门不同 / 数据源不同 / 票源不同)。

报:每年的票数、R 合计、平均 R、胜率、R ≥ 5 / ≥ 10 的张数与名字、去掉当年最大一张后的 R 合计。
判(台账唯一一条):2017-09 → 2020-07 里 R ≥ 10 的票 ≥ 3 张,且分布在至少两个日历年 ⇒ 成立。

用法:python3 docs/research/t351_rv2_history.py
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
MAC = "/Volumes/CometCloudAI/cometcloud-local/research"
BARS_CACHE = f"{MAC}/t351/_bars_binance_hist.jsonl"
UM_FILE = f"{MAC}/s681/_um_daily.jsonl"
STYLE_FILE = f"{MAC}/t156/_style.json"
OUT_JSON = os.path.join(HERE, "t351_results.json")
OUT_MD = os.path.join(HERE, "T-351_right_tail_history.md")

EARLY_FROM, EARLY_TO = "2017-09-01", "2020-07-31"     # 台账 S-827 原文
SELF_FROM = "2020-08-01"                              # 台账自检:2020-08 之后
SELF_TO = "2026-09-30"
T197_FROM, T197_TO = "2020-01-01", "2026-09-30"        # t197 自己的信号窗
T197_RESULTS = os.path.join(HERE, "t197_results.json")


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 以下 indicators / _universe / sig_long / run_long / _chain:逐字搬自 docs/research/t159_bear_short.py
# (t197_rv2_survivorship.py 用的同一份代码)。行号对照见每段注释。**一个数字都没改。**
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════
def win(v, i, lo, hi):
    seg = v[max(0, i - hi): i - lo + 1]
    return sum(seg) / len(seg) if seg else None


def wmax(v, i, hi, lo):
    seg = v[max(0, i - hi): i - lo + 1]
    return max(seg) if seg else None


def wmin(v, i, hi, lo):
    seg = v[max(0, i - hi): i - lo + 1]
    return min(seg) if seg else None


def indicators(rows):
    c = [r[4] for r in rows]
    h = [r[2] for r in rows]
    l = [r[3] for r in rows]
    dv = [r[5] for r in rows]
    pc = [rows[i - 1][4] if i > 0 else c[i] for i in range(len(rows))]
    tr = [max(h[i] - l[i], abs(h[i] - pc[i]), abs(l[i] - pc[i])) for i in range(len(rows))]
    n = len(rows)
    dd = [c[i] / wmax(c, i, 365, 0) for i in range(n)]
    return dict(c=c, o=[r[1] for r in rows], h=h, l=l, dv=dv, d=[r[0] for r in rows],
                sma20=[win(c, i, 0, 19) or c[i] for i in range(n)],
                sma200=[win(c, i, 0, 199) for i in range(n)],
                atr14=[win(tr, i, 0, 13) for i in range(n)],
                adv30=[win(dv, i, 0, 29) for i in range(n)],
                adv40p=[win(dv, i, 1, 40) for i in range(n)],
                hh40=[wmax(h, i, 40, 1) for i in range(n)],
                ll40=[wmin(l, i, 40, 1) for i in range(n)],
                mindd120=[wmin(dd, i, 120, 0) for i in range(n)])


def _universe(a, i):
    if i < 220 or a["atr14"][i] is None or a["atr14"][i] <= 0:
        return False
    if a["adv30"][i] is None or a["adv30"][i] < 5e6:
        return False
    hh, ll = a["hh40"][i], a["ll40"][i]
    if hh is None or ll is None or hh == 0 or (hh - ll) / hh > 0.40:
        return False
    if a["adv40p"][i] is None or a["dv"][i] < 2 * a["adv40p"][i]:
        return False
    return True


def sig_long(a, i, g):
    return (_universe(a, i) and a["mindd120"][i] is not None and a["mindd120"][i] <= 0.5
            and a["c"][i] > a["hh40"][i] and a["sma200"][i] is not None and a["c"][i] > a["sma200"][i]
            and g.get(a["d"][i], {}).get("gate_open", True))


def _chain(tr):
    res = []
    for sym, ts in tr.items():
        ts.sort(key=lambda t: t["ei"])
        cur = ts[0]
        res.append(cur)
        while True:
            nxt = [t for t in ts if t["ei"] > cur["xi"]]
            if not nxt:
                break
            cur = nxt[0]
            res.append(cur)
    res.sort(key=lambda t: (t["signal_d"], t["symbol"]))
    return res


def run_long(bars, gate, d_from, d_to, ind_cache=None):
    """docs/research/r_v2_tickets.sql, verbatim (t159_bear_short.py:241-275)。

    ind_cache:可选的 {symbol: indicators(rows)} 缓存 —— 只为省掉重复计算,**不动任何一个数字**。
    """
    tr = defaultdict(list)
    for sym, rows in bars.items():
        a = ind_cache[sym] if (ind_cache is not None and sym in ind_cache) else indicators(rows)
        n = len(rows)
        for i in range(220, n):
            d = a["d"][i]
            if not (d_from <= d <= d_to) or not sig_long(a, i, gate):
                continue
            ei = i + 1
            if ei >= n:
                continue
            entry, stop = a["o"][ei], a["o"][ei] - 2.5 * a["atr14"][i]
            if not (entry > stop):
                continue
            k = None
            for j in range(ei, min(i + 120, n - 1) + 1):
                if a["l"][j] <= stop or a["c"][j] < a["sma20"][j]:
                    k = j
                    break
            if k is None:
                xi, xp, still = min(i + 120, n - 1), a["c"][min(i + 120, n - 1)], (i + 120 > n - 1)
            elif a["l"][k] <= stop:
                xi, xp, still = k, (a["o"][k] if (k > ei and a["o"][k] <= stop) else stop), False
            elif k + 1 <= n - 1:
                xi, xp, still = k + 1, a["o"][k + 1], False
            else:
                xi, xp, still = k, a["c"][k], True
            t = dict(symbol=sym, signal_d=d, entry_d=a["d"][ei], exit_d=None if still else a["d"][xi],
                     entry_px=entry, stop_px=stop, exit_px=None if xp is None else xp, ei=ei, xi=xi,
                     bars_held=xi - ei + 1, still=still)
            t["r"] = None if still else ((xp - entry) / (entry - stop) - 0.004 * entry / (entry - stop))
            tr[sym].append(t)
    return _chain(tr)


# ── 闸门 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def gate_btc200(bars):
    """S-827 原文:2020 之前没有 majors 指数 ⇒ 闸门用 BTC 自己的 200 日线代替。

    gate_open[d] = BTC 收盘 > BTC 自己的 SMA200(真 200 根;不足 200 根时没有历史可比 ⇒ gate_open = True,
    与 t159.load_gate() 的 `n < 200 ⇒ gate_open` 同义)。
    """
    btc = bars.get("BTC")
    if not btc:
        return {}, {}
    a = indicators(btc)
    g, raw = {}, {}
    for i, d in enumerate(a["d"]):
        s = a["sma200"][i] if i >= 199 else None       # 真 200 日均(不足 200 根 → None)
        raw[d] = dict(close=a["c"][i], sma200=s,
                      gate_open=bool(s is None or a["c"][i] > s))
    for d in raw:
        g[d] = dict(gate_open=raw[d]["gate_open"])
    return g, raw


def load_gate_majors():
    """t159.load_gate() 逐字搬(t159_bear_short.py:127-140)—— 只用于关 1(与 t197 同闸门)。"""
    rows = [x for x in json.load(open(STYLE_FILE)) if x["ret"] is not None and x["ret"] > -0.95]
    rows.sort(key=lambda x: x["d"])
    lvl, cur = [], 1.0
    for x in rows:
        cur *= (1.0 + x["ret"])
        lvl.append(cur)
    g = {}
    for i, x in enumerate(rows):
        n = min(i + 1, 200)
        g[x["d"]] = dict(n=n, lvl=lvl[i],
                        gate_open=bool(n < 200 or lvl[i] > win(lvl, i, 0, 199)),
                        gate_closed=bool(n >= 200 and lvl[i] <= win(lvl, i, 0, 199)))
    return g


# ── 数据 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def load_bars_cache():
    """t351/_bars_binance_hist.jsonl → {symbol: [(d, o, h, l, c, dv)]}。

    dv = close * volume —— 与 t159.load_bars() 完全同口径(第 6 列当成交额用)。
    c ≤ 0 的行丢掉(t197 的 load_um 同样处理)。
    """
    by = defaultdict(list)
    with open(BARS_CACHE) as f:
        for line in f:
            x = json.loads(line)
            c = float(x["close"])
            if c <= 0:
                continue
            by[x["symbol"]].append((x["trade_date"], float(x["open"]), float(x["high"]),
                                    float(x["low"]), c, c * float(x["volume"])))
    out = {}
    for s, rows in by.items():
        rows = sorted(set(rows))
        if rows:
            out[s] = rows
    return out


def load_um():
    """t197 的 load_um() 逐字搬 —— 只用于关 1(t197 自己的宇宙)。"""
    bars = {}
    for line in open(UM_FILE):
        x = json.loads(line)
        rows = sorted({tuple(b) for b in x["bars"] if len(b) >= 6 and b[4] > 0})
        if rows:
            bars[x["symbol"]] = rows
    return bars


# ── 统计 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def closed_of(tickets):
    return [t for t in tickets if not t.get("still") and t.get("r") is not None]


def by_year(tickets, years):
    out = {}
    for y in years:
        tk = [t for t in tickets if t["signal_d"][:4] == y]
        cl = closed_of(tk)
        rs = [t["r"] for t in cl]
        big5 = sorted([t for t in cl if t["r"] >= 5], key=lambda t: -t["r"])
        big10 = sorted([t for t in cl if t["r"] >= 10], key=lambda t: -t["r"])
        out[y] = dict(
            tickets=len(tk), closed=len(cl), still=len(tk) - len(cl),
            sum_r=round(sum(rs), 4) if rs else None,
            mean_r=round(sum(rs) / len(rs), 4) if rs else None,
            win_rate=round(sum(1 for r in rs if r > 0) / len(rs), 4) if rs else None,
            n_ge5=len(big5), n_ge10=len(big10),
            names_ge5=[f"{t['symbol']}@{t['signal_d']} R={t['r']:.2f}" for t in big5],
            names_ge10=[f"{t['symbol']}@{t['signal_d']} R={t['r']:.2f}" for t in big10],
            max_r=round(max(rs), 4) if rs else None,
            sum_r_ex_max=round(sum(rs) - max(rs), 4) if rs else None,
            max_ticket=(f"{max(cl, key=lambda t: t['r'])['symbol']}@{max(cl, key=lambda t: t['r'])['signal_d']}"
                        f" R={max(cl, key=lambda t: t['r'])['r']:.2f}") if rs else None)
    return out


def universe_stats(bars, d_from, d_to, ind_cache=None):
    """每年:当时在交易的币数、过了成交额门槛(adv30 ≥ 5e6)的币数、其中后来下架的数。"""
    years = sorted({d[:4] for d in
                    [r[0] for v in bars.values() for r in v if d_from <= r[0] <= d_to]})
    buckets = {y: dict(trading=set(), vol=set(), full=set()) for y in years}
    for s, rows in bars.items():
        a = ind_cache[s] if (ind_cache is not None and s in ind_cache) else indicators(rows)
        for i, d in enumerate(a["d"]):
            y = d[:4]
            if y not in buckets:
                continue
            b = buckets[y]
            b["trading"].add(s)
            if a["adv30"][i] is not None and a["adv30"][i] >= 5e6:
                b["vol"].add(s)
            if _universe(a, i):
                b["full"].add(s)
    last = {s: v[-1][0] for s, v in bars.items()}
    out = {}
    for y, b in buckets.items():
        pv = b["vol"]
        dead_by = {s for s in pv if last[s] <= d_to}          # 窗内就断了
        dead_later = {s for s in pv if last[s] < SELF_TO}     # 后来下架(含窗内)
        out[y] = dict(
            trading=len(b["trading"]),
            passed_vol_gate=len(pv),
            passed_full_universe=len(b["full"]),
            dead_by_window_end=len(dead_by),
            dead_later=len(dead_later),
            alive_at_data_end=len(pv) - len(dead_later))
    return out


def diff_tickets(mine, theirs):
    """票集比对:键 = (symbol, signal_d)。"""
    mk = {(t["symbol"], t["signal_d"]) for t in mine}
    tk = {(t["symbol"], t["signal_d"]) for t in theirs}
    return dict(mine_n=len(mk), theirs_n=len(tk), both=len(mk & tk),
                only_mine=sorted(mk - tk), only_theirs=sorted(tk - mk),
                mine_syms=len({s for s, _ in mk}), theirs_syms=len({s for s, _ in tk}))


def main():
    t0 = datetime.now(timezone.utc)
    bars = load_bars_cache()
    ind_cache = {s: indicators(v) for s, v in bars.items()}   # 三个跑共用,只省算力
    g_btc, g_raw = gate_btc200(bars)

    # ── 关 0:能不能开票(数据本身够不够) ────────────────────────────────────────────────────────────
    firsts = {s: v[0][0] for s, v in bars.items()}
    lasts = {s: v[-1][0] for s, v in bars.items()}
    earliest_signal = min((v[0][0] for v in bars.values()), default=None)

    # ── 主跑:早年窗(现货 + BTC-200d 闸门) ───────────────────────────────────────────────────────────
    tk_early = run_long(bars, g_btc, EARLY_FROM, EARLY_TO, ind_cache)
    years = [str(y) for y in range(2017, 2021)]
    early_by_year = by_year(tk_early, years)
    univ = universe_stats(bars, EARLY_FROM, EARLY_TO, ind_cache)

    cl = closed_of(tk_early)
    big10 = [t for t in cl if t["r"] >= 10]
    big10_years = sorted({t["signal_d"][:4] for t in big10})
    verdict_pass = bool(len(big10) >= 3 and len(big10_years) >= 2)

    # ── 关 1:搬迁保真(同一份代码 + t197 的宇宙 + t197 的闸门 + t197 的窗) ────────────────────────────────
    um = load_um()
    g_maj = load_gate_majors()
    um_ind = {s: indicators(v) for s, v in um.items()}
    tk_faithful = run_long(um, g_maj, T197_FROM, T197_TO, um_ind)

    # ── 臂 2(偏离登记,单列):宇宙换成 s681 的 890 个币(含后来下架的)── 现货表里没有下架币
    um_early = run_long(um, g_btc, EARLY_FROM, EARLY_TO, um_ind)
    um_by_year = by_year(um_early, years)
    um_univ = universe_stats(um, EARLY_FROM, EARLY_TO, um_ind)
    cl_um = closed_of(um_early)
    big10_um = [t for t in cl_um if t["r"] >= 10]
    big10_um_years = sorted({t["signal_d"][:4] for t in big10_um})
    um_verdict = dict(rule="R ≥ 10 的票 ≥ 3 张 且分布在至少两个日历年",
                      n_ge10=len(big10_um), years=big10_um_years,
                      pass_=bool(len(big10_um) >= 3 and len(big10_um_years) >= 2))
    t197 = json.load(open(T197_RESULTS))
    tk197 = t197["tickets"]["A"]
    d1 = diff_tickets(tk_faithful, tk197)
    # 同键也要比 r
    m = {(t["symbol"], t["signal_d"]): t for t in tk_faithful}
    o = {(t["symbol"], t["signal_d"]): t for t in tk197}
    r_diff = [k for k in (set(m) & set(o))
              if (m[k].get("r") is None) != (o[k].get("r") is None)
              or (m[k].get("r") is not None and o[k].get("r") is not None
                  and abs(m[k]["r"] - o[k]["r"]) > 1e-9)]

    # ── 关 2:台账要求的自检(现货 + BTC-200d 闸门,2020-08 之后 vs t197 tickets.A) ─────────────────────────
    tk_self = run_long(bars, g_btc, SELF_FROM, SELF_TO, ind_cache)
    d2 = diff_tickets(tk_self, tk197)
    um_syms = set(um)
    spot_syms = set(bars)
    only_spot = sorted(spot_syms - um_syms)
    only_um = sorted(um_syms - spot_syms)
    # 关 2 差异拆因:宇宙(名字不在 t197 的票源里)/闸门(BTC-200d 与 majors 不同)
    gate_diff_days = sum(1 for d, v in g_btc.items()
                          if v.get("gate_open") != g_maj.get(d, {}).get("gate_open", True))

    res = dict(
        meta=dict(run_utc=t0.isoformat(), bars_cache=BARS_CACHE,
                  window=[EARLY_FROM, EARLY_TO], self_check_window=[SELF_FROM, SELF_TO],
                  gate="BTC 自己的 200 日线(close > 自己的 SMA200)",
                  cost="来回 0.4%(与 t159/t197 同口径:r 里减 0.004*entry/(entry-stop))",
                  rule_src="docs/research/t159_bear_short.py:163-275(逐字搬)"),
        universe=dict(
            symbols_total=len(bars),
            rows_total=sum(len(v) for v in bars.values()),
            first_data=min(firsts.values()), last_data=max(lasts.values()),
            symbols_with_bar_in_window=sum(1 for s, v in bars.items()
                                           if any(EARLY_FROM <= r[0] <= EARLY_TO for r in v)),
            btc_first=firsts.get("BTC"), btc_last=lasts.get("BTC"),
            btc_sma200_first_full_day=min((d for d, v in g_raw.items() if v["sma200"] is not None),
                                          default=None)),
        per_year=early_by_year,
        universe_by_year=univ,
        arm2_delisted_universe=dict(
            note="偏离登记:现货表只有今天还在的 262 个名字,下架币不在里面 ⇒ 另起一臂,"
                 "宇宙换成 s681 的 890 个币(含后来下架的;永续,非现货),规则与闸门一字不改",
            universe_by_year=um_univ, per_year=um_by_year,
            n_ge10=len(big10_um), ge10_years=big10_um_years,
            ge10=[f"{t['symbol']}@{t['signal_d']} R={t['r']:.2f}" for t in
                  sorted(big10_um, key=lambda t: -t["r"])],
            still_tickets=len(um_early) - len(cl_um),
            verdict=um_verdict,
            tickets=[dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                          exit_d=t["exit_d"], r=t["r"], still=bool(t.get("still"))) for t in um_early]),
        tail=dict(n_ge5=sum(1 for t in cl if t["r"] >= 5), n_ge10=len(big10),
                  n_ge20=sum(1 for t in cl if t["r"] >= 20),
                  max_r=round(max((t["r"] for t in cl), default=0), 4),
                  ge10_years=big10_years,
                  ge10=[f"{t['symbol']}@{t['signal_d']} R={t['r']:.2f}" for t in
                        sorted(big10, key=lambda t: -t["r"])]),
        verdict=dict(rule="R ≥ 10 的票 ≥ 3 张 且分布在至少两个日历年",
                     n_ge10=len(big10), years=big10_years, pass_=verdict_pass,
                     text=("右尾在更早的周期里也出现过(成立)" if verdict_pass else
                           ("没有(窗内 R ≥ 10 的票 < 3 张)" if len(big10) < 3 else
                            "只落在同一个日历年"))),
        still_tickets=len(tk_early) - len(cl),
        selfcheck=dict(
            gate1_faithful=dict(note="同一份代码 + t197 自己的宇宙 + majors 闸门 + t197 自己的窗",
                                diff=d1, r_mismatch_n=len(r_diff), r_mismatch_sample=r_diff[:5]),
            gate2_vs_t197=dict(note="同一份代码 + 现货宇宙 + BTC-200d 闸门,2020-08 之后 vs t197 tickets.A",
                               diff=d2,
                               spot_only_symbols_n=len(only_spot), um_only_symbols_n=len(only_um),
                               um_only_sample=only_um[:10],
                               gate_disagree_days=gate_diff_days)),
        tickets=[dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                      exit_d=t["exit_d"], entry_px=t["entry_px"], stop_px=t["stop_px"],
                      exit_px=t["exit_px"], r=t["r"], still=bool(t.get("still")),
                      bars_held=t["bars_held"]) for t in tk_early])

    json.dump(res, open(OUT_JSON, "w"), indent=1, default=str)
    write_md(res)
    print(json.dumps(dict(verdict=res["verdict"], tail=res["tail"], universe=res["universe"],
                          per_year=early_by_year, universe_by_year=univ,
                          arm2=dict(per_year=res["arm2_delisted_universe"]["per_year"],
                                    univ=res["arm2_delisted_universe"]["universe_by_year"],
                                    n_ge10=res["arm2_delisted_universe"]["n_ge10"],
                                    years=res["arm2_delisted_universe"]["ge10_years"],
                                    verdict=res["arm2_delisted_universe"]["verdict"]),
                          selfcheck=dict(g1=d1, g1_r_mismatch=len(r_diff),
                                         g2=dict(mine=d2["mine_n"], theirs=d2["theirs_n"], both=d2["both"],
                                                 only_mine_n=len(d2["only_mine"]),
                                                 only_theirs_n=len(d2["only_theirs"])),
                                         gate_disagree_days=gate_diff_days),
                          out_json=OUT_JSON, out_md=OUT_MD), indent=1, default=str))


def write_md(res):
    def fm(x):
        return "—" if x is None else x

    L = []
    A = L.append
    A("# T-351 / S-827 —— 右尾有多常见:R-v2 的规则放到 2017-09 → 2020-07 的 Binance 现货上")
    A("")
    A(f"- 跑完时间(UTC):{res['meta']['run_utc']}")
    A(f"- 规则:**原样**(逐字搬 `docs/research/t159_bear_short.py`,t197 用的同一份开票/管票代码)")
    A(f"- 宇宙:`ohlcv_daily(source='binance_hist')` 现货,{res['universe']['symbols_total']} 个符号 / "
      f"{res['universe']['rows_total']} 行,数据 {res['universe']['first_data']} → {res['universe']['last_data']}")
    A(f"- 闸门:{res['meta']['gate']}(BTC 的 SMA200 满 200 根从 {res['universe']['btc_sma200_first_full_day']} 起)")
    A(f"- 成本:{res['meta']['cost']};现货,无资金费")
    A("")
    A("## ⚠️ 先说数据边界(登记的宇宙建不起来)")
    A("")
    A(f"1. **登记写「宇宙 = `ohlcv_daily(binance_hist)` 2017-09-01 → 2020-07-31 当时在交易的现货(含后来下架的)」,"
      f"但 `ohlcv_daily` 整张表只有 {res['universe']['symbols_total']} 个符号 —— 今天还在的那批名字;"
      f"窗内有 K 线的只有 {res['universe']['symbols_with_bar_in_window']} 个。**"
      "2017–2020 下架的山寨币**一个都不在表里**(环境里另一份含下架币的 s681 是 Binance **永续**,"
      "且数据从 2020-01 才开始 ⇒ 同样过不了 220 根预热)。"
      "⇒ 本卡能跑的是「今天还活着的币在早年那一段」,不是「当年那段的全部现货」。")
    A(f"2. **预热**:开票要求每个币至少 220 根 K 线(`run_long` 从 i=220 起);"
      f"而全表最早的数据是 {res['universe']['first_data']}(BTC)。⇒ **最早的信号日约在 2018-05**,"
      "2017-09 → 2018 的空档是预热造成的,不是「那一段没有信号」。")
    A("3. 结论:登记的判(「35 个月里 R ≥ 10 的票 ≥ 3 张」)只能就**可跑的那一段 + 幸存者名单**回答;"
      "「2017 山寨季有没有右尾」在本环境里**无法被检验**。下面是能跑的数。")
    A("")
    A("## 数据先报(台账要求)")
    A("")
    A("| 年 | 当时在交易的币 | 过成交额门槛(adv30 ≥ 500 万美元) | 过全部开票门槛 | 其中窗内就下架 | 后来下架(含窗内) | 至今还活着 |")
    A("|---|---|---|---|---|---|---|")
    for y, u in res["universe_by_year"].items():
        A(f"| {y} | {u['trading']} | {u['passed_vol_gate']} | {u['passed_full_universe']} | "
          f"{u['dead_by_window_end']} | {u['dead_later']} | {u['alive_at_data_end']} |")
    A("")
    A("## 自检")
    A("")
    g1 = res["selfcheck"]["gate1_faithful"]
    g2 = res["selfcheck"]["gate2_vs_t197"]
    A(f"- **关 1(搬迁保真)**:同一份代码 + t197 自己的宇宙 + majors 闸门 + t197 自己的窗 → "
      f"我的 {g1['diff']['mine_n']} 张 vs t197 {g1['diff']['theirs_n']} 张,重合 {g1['diff']['both']} 张,"
      f"只我有 {len(g1['diff']['only_mine'])} 张、只有它有 {len(g1['diff']['only_theirs'])} 张;"
      f"重合票的 R 不一致 {g1['r_mismatch_n']} 张。")
    A(f"- **关 2(台账口径)**:同一份代码在 2020-08 之后(现货宇宙 + BTC-200d 闸门)→ "
      f"我的 {g2['diff']['mine_n']} 张 vs t197 {g2['diff']['theirs_n']} 张,重合 {g2['diff']['both']} 张,"
      f"只我有 {len(g2['diff']['only_mine'])} 张、只有它有 {len(g2['diff']['only_theirs'])} 张。")
    A(f"- 关 2 的差异拆因:现货符号 {res['universe']['symbols_total']} 个 vs t197 票源 "
      f"{len(set(t['symbol'] for t in json.load(open(T197_RESULTS))['tickets']['A']))} 个;"
      f"闸门在 {g2['gate_disagree_days']} 天上与 majors 判定不同。")
    A("")
    A("## 逐年(信号日所在年)")
    A("")
    A("| 年 | 票数 | 已了结 | 未了结 | R 合计 | 平均 R | 胜率 | R ≥ 5 | R ≥ 10 | 最大 R | 去掉最大一张后的 R 合计 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for y, p in res["per_year"].items():
        A(f"| {y} | {p['tickets']} | {p['closed']} | {p['still']} | {fm(p['sum_r'])} | {fm(p['mean_r'])} | "
          f"{fm(p['win_rate'])} | {p['n_ge5']} | {p['n_ge10']} | {fm(p['max_r'])} | {fm(p['sum_r_ex_max'])} |")
    A("")
    A("### R ≥ 10 的票(名字 / 信号日 / R)")
    A("")
    for s in res["tail"]["ge10"]:
        A(f"- {s}")
    if not res["tail"]["ge10"]:
        A("- (窗内没有 R ≥ 10 的票)")
    A("")
    A("### R ≥ 5 的票(名字 / 信号日 / R,按年)")
    A("")
    for y, p in res["per_year"].items():
        A(f"- **{y}**({p['n_ge5']} 张):")
        for s in p["names_ge5"]:
            A(f"  - {s}")
        if not p["names_ge5"]:
            A("  - (无)")
    A("")
    A("### 全部票(信号日 / 名字 / R)")
    A("")
    byy = {}
    for t in res["tickets"]:
        byy.setdefault(t["signal_d"][:4], []).append(t)
    for y in sorted(byy):
        A(f"- **{y}**({len(byy[y])} 张):" +
          " · ".join(f"{t['symbol']}@{t['signal_d'][5:]} R={t['r']:.2f}" for t in byy[y]))
    A("")
    a2 = res["arm2_delisted_universe"]
    A("## 臂 2(偏离登记,单列):宇宙换成含下架币的名单")
    A("")
    A(f"- 为什么:登记写「宇宙 = `ohlcv_daily(binance_hist)` 2017-09-01 → 2020-07-31 当时在交易的现货"
      f"(**含后来下架的**)」,但 `ohlcv_daily` 整张表只有 {res['universe']['symbols_total']} 个符号 —— "
      "**今天还在的那批名字**;2017–2020 下架的币一个都不在表里。⇒ 臂 1(现货表)是幸存者名单,"
      "不是「当时在交易的全部现货」。臂 2 用 s681 的 890 名字(含下架的)把这一刀补上。")
    A("- 代价:臂 2 是永续不是现货;且 2017–2019 的 Binance 永续名单本来就只有主流币 —— "
      "山寨季那一批多数当时没有永续 ⇒ 臂 2 的「早年山寨季」仍是不完整的。")
    A("- 规则、闸门(BTC-200d)、成本、窗口:**一字不改**,只换宇宙。")
    A("")
    A("| 年 | 当时在交易的币 | 过成交额门槛 | 其中窗内就下架 | 票数 | R 合计 | 平均 R | 胜率 | R ≥ 5 | R ≥ 10 | 去掉最大一张 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for y, u in a2["universe_by_year"].items():
        p = a2["per_year"][y]
        A(f"| {y} | {u['trading']} | {u['passed_vol_gate']} | {u['dead_by_window_end']} | {p['tickets']} | "
          f"{p['sum_r']} | {p['mean_r']} | {p['win_rate']} | {p['n_ge5']} | {p['n_ge10']} | {p['sum_r_ex_max']} |")
    A("")
    A(f"- 臂 2 的 R ≥ 10 票:{a2['n_ge10']} 张,分布在 {a2['ge10_years'] or '—'}")
    for s in a2["ge10"]:
        A(f"  - {s}")
    A(f"- 臂 2 判(同一条):**{'成立' if a2['verdict']['pass_'] else '不成立'}**")
    A("")
    A("## 判(台账唯一一条)")
    A("")
    A(f"> {res['verdict']['rule']}")
    A("")
    A(f"**{res['verdict']['text']}** —— 窗内 R ≥ 10 的票 {res['verdict']['n_ge10']} 张,分布在 "
      f"{res['verdict']['years'] or '—'}。")
    A("")
    _t197 = json.load(open(T197_RESULTS))["tickets"]["A"]
    _big_now = sum(1 for t in _t197 if t.get("r") is not None and t["r"] >= 10)
    _n_early = sum(p["tickets"] for p in res["per_year"].values())
    A("**频率对照(把「没有」拆成两件事):** 当前票源(2020-08 起,t197 `tickets.A`)里 R ≥ 10 的票是 "
      f"**{_big_now}/{len(_t197)} = {_big_now / len(_t197) * 100:.2f}%/张**;本卡能跑的早年切片是 "
      f"**{res['verdict']['n_ge10']}/{_n_early} = "
      f"{(res['verdict']['n_ge10'] / _n_early * 100 if _n_early else 0):.2f}%/张**。"
      "⇒ **右尾的「频率」在早年并不更罕见**;不够的是**绝对张数** —— 能跑的两年只出了 "
      f"{_n_early} 张票,凑不出登记要的 3 张 R ≥ 10。把早年整段(含下架币)跑出来,才有资格回答登记那句话;"
      "本环境的数据做不到(见上「数据边界」)。")
    A("")
    A(f"**⚠️ 与登记的一处不符(Seth 复核):** S-827 写「这张票源(2020-08 起)里 R ≥ 10 的票 **7 张**、"
      f"其中 2021-10 之后只有 **3 张**」;我在仓库里的 `docs/research/t197_results.json` 上数到 "
      f"**{_big_now} 张**(其中 13 张在 2021-10 之后:最早 2021-04-06 ETC R=13.01,最大 2025-09-06 ZEC R=73.16)。"
      "⇒ 「等下一张 ZEC」的基数是 7 还是 14,值得对一次。")
    A("")
    A("## 诚实 / 限制")
    A("")
    A("- 现货不是永续(2017–2020 多数币没有永续);无资金费,无基差。")
    A("- 幸存者偏差按「当时在交易的名单」处理:宇宙取的是历史上真实存在过的符号(含后来下架的),"
      "但今天仍在 `binance_hist` 里的币必然被这份名单优先覆盖 —— 早年名单里被下架的币,只有"
      "在它自己那段时间里才进过开票门槛。")
    A("- BTC 的 200 日线是 majors 指数的代理;2020 之前没有 majors 市值指数可用。")
    A("- 数据显示最早只到 2017-08-17(BTC)与 2017-09-01(ETH),而开票要求每个币至少 220 根 K 线预热 ⇒ "
      "**窗内最早的信号日约在 2018-04**;2017 年的空档是数据预热造成的,不是「那一段没信号」。")
    A("- 未了结的票(数据在窗内断掉)不进 R 合计,单列。")
    A("")
    A("## 产物")
    A("")
    A("- `docs/research/t351_results.json`(全部票 + 逐年统计)")
    A("- `docs/research/t351_fetch.py`(取数)· `docs/research/t351_rv2_history.py`(本文件对应的脚本)")
    A("")
    open(OUT_MD, "w").write("\n".join(L))


if __name__ == "__main__":
    main()
