"""T-251 —— R-v2 名义合计上限 30% / 40% / 100% 三档回放(只报,不判)。

数据:`perp_bv_daily`(S-719/S-730 的永续源)+ `perp_bv_pairs`(验证宇宙)+ `style_index_pit_daily`
(majors/cap 的 gate)。`r_tickets_paper` 在库里是 0 行,所以票是**回放**出来的:
`migrations/2026-11-05_r_tickets_perp_source.sql` 的 `r_tickets_scan`(plpgsql → Python,
逐条对齐 t156 的 `run_v2` 移植)。

主机跳过规则(`src/exec_host/tickets.py: ticket_actions`):
  名义 = 净值 × risk_frac ÷ stop_frac,单票 ≤ 净值 50%;主机已满 10 张 / 同币已有仓 /
  名义低于 HL 最小名义额 $10 ⇒ 不可执行;名义合计 > 净值 × gross_cap ⇒ 这张票不做、**不找替补**。
逐日模拟:先按开盘平掉当日的止损/收盘破 SMA20 出场,再按 (信号日, 名字) 顺序处理当日进场,
最后按收盘给净值。复利。

用法:python3 docs/research/t251_gross_cap.py            (默认跑完并写 t251_results.json)
"""
from __future__ import annotations

import datetime as dt
import bisect
import gzip
import json
import math
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict, deque

U = os.environ.get("SUPABASE_URL")
K = os.environ.get("SUPABASE_KEY")
if not U or not K:
    raise SystemExit("SUPABASE_URL / SUPABASE_KEY 不在环境里,退出(不要去找 .env)")

H = {"apikey": K, "Authorization": "Bearer " + K}
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t251_cache"
HERE = os.path.dirname(os.path.abspath(__file__))
EXCL = {"USDC", "BTCDOM", "DEFI"}
D_FROM = dt.date(2020, 7, 1)
D_TO = dt.date.today() - dt.timedelta(days=1)
CAPS = [0.30, 0.40, 1.00]
EQUITY0 = 630.0          # 今天账户净值(美元)—— 让 HL 的 $10 最小名义规则全程生效
RISK_FRAC = 0.005        # 每票风险占净值 0.5%
CAP_N = 10               # 主机最多 10 张
MIN_NOTIONAL = 10.0      # HL 最小名义额
STOP_ATR = 2.5


# ---------------------------------------------------------------- 取数
def _rest(path, rng="0-999", extra=None):
    h = dict(H)
    h["Range"] = rng
    if extra:
        h.update(extra)
    r = urllib.request.Request(U + "/rest/v1/" + path, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            return json.loads(resp.read()), resp.headers.get("Content-Range")
    except urllib.error.HTTPError as e:
        if e.code == 416:
            return [], None
        raise RuntimeError(f"HTTP {e.code} on {path[:140]}: {e.read()[:300].decode('utf8','replace')}") from None


def _page_all(path, cap_pages=100000):
    out, off = [], 0
    while off < cap_pages * 1000:
        rows, _ = _rest(path, f"{off}-{off+999}")
        if not rows:
            break
        out += rows
        off += 1000
        if len(rows) < 1000:
            break
    return out


def _panel_symbols():
    """ohlcv_daily(source='binance_hist') 面板里的符号 —— 用游标一次一个地取 distinct。"""
    syms, last = [], ""
    while True:
        q = "ohlcv_daily?select=symbol&source=eq.binance_hist&order=symbol.asc"
        if last:
            q += f"&symbol=gt.{last}"
        rows, _ = _rest(q, "0-0")
        if not rows:
            break
        s = rows[0]["symbol"]
        if s in syms:
            break
        syms.append(s)
        last = s
    return syms


def fetch_all(force=False):
    """缓存到 Mac 数据根(不是 /tmp)。"""
    os.makedirs(CACHE, exist_ok=True)
    f_bars = os.path.join(CACHE, "perp_bv_daily.jsonl.gz")
    f_style = os.path.join(CACHE, "style_majors_cap.json")
    f_pairs = os.path.join(CACHE, "perp_bv_pairs.json")
    f_uni = os.path.join(CACHE, "validated_universe.json")
    if not force and all(os.path.exists(f) for f in (f_bars, f_style, f_pairs, f_uni)):
        print("用缓存", file=sys.stderr)
        pairs = json.load(open(f_pairs))
        style = json.load(open(f_style))
        uni = set(json.load(open(f_uni)))
        bars = defaultdict(list)
        with gzip.open(f_bars, "rt") as fh:
            for line in fh:
                x = json.loads(line)
                if x["symbol"] in uni:
                    bars[x["symbol"]].append((x["d"], x["o"], x["h"], x["l"], x["c"], x["dv"]))
        return pairs, style, bars, sorted(uni)

    # 1) 验证宇宙(S-730):perp_bv_pairs 的币 ∩ binance_hist 面板符号
    pairs = _page_all("perp_bv_pairs?select=symbol,kind,dead_from,active&order=symbol.asc")
    coin = {p["symbol"] for p in pairs
            if p["symbol"] not in EXCL and (p.get("kind") == "coin"
                                           or (p.get("kind") is None and p.get("dead_from")))}
    panel = _panel_symbols()
    uni = sorted(coin & set(panel))
    print(f"验证宇宙:{len(coin)} 个 coin 永续 ∩ {len(panel)} 个 binance_hist 面板符号 "
          f"= {len(uni)}", file=sys.stderr)
    json.dump(pairs, open(f_pairs, "w"))
    json.dump(uni, open(f_uni, "w"))

    # 2) 永续日线(分片,每片 ≤ 1000 行一页,带 order=)
    bars = defaultdict(list)
    n = 0
    with gzip.open(f_bars, "wt") as fh:
        for i in range(0, len(uni), 20):
            shard = ",".join(uni[i:i + 20])
            q = (f"perp_bv_daily?select=symbol,d,o,h,l,c,qv&symbol=in.({shard})"
                 f"&order=symbol.asc,d.asc")
            for x in _page_all(q):
                row = (x["d"], float(x["o"]), float(x["h"]), float(x["l"]), float(x["c"]), float(x["qv"] or 0.0))
                bars[x["symbol"]].append(row)
                fh.write(json.dumps({"symbol": x["symbol"], "d": x["d"], "o": row[1], "h": row[2],
                                     "l": row[3], "c": row[4], "dv": row[5]}) + "\n")
                n += 1
            print(f"  perp_bv_daily {n} 行 ({i+20}/{len(uni)} 个符号)", file=sys.stderr)

    # 3) majors/cap 的 gate 源
    style = _page_all("style_index_pit_daily?select=d,ret&style=eq.majors&weighting=eq.cap&order=d.asc")
    json.dump(style, open(f_style, "w"))
    print(f"取数完成:{n} 根永续日线 / {len(bars)} 个符号 / {len(style)} 行 majors", file=sys.stderr)
    return pairs, style, bars, uni


# ---------------------------------------------------------------- 指标(等价 SQL 窗口)
def _sliding(a, w, incl, is_max):
    n = len(a)
    out = [None] * n
    dq = deque()
    for i in range(n):
        j = i if incl else i - 1
        if j >= 0:
            while dq and (a[dq[-1]] <= a[j] if is_max else a[dq[-1]] >= a[j]):
                dq.pop()
            dq.append(j)
        left = i - w
        while dq and dq[0] < left:
            dq.popleft()
        out[i] = a[dq[0]] if dq else None
    return out


def _mean(a, w, incl):
    n = len(a)
    ps = [0.0] * (n + 1)
    for i, x in enumerate(a):
        ps[i + 1] = ps[i] + x
    out = [None] * n
    for i in range(n):
        hi = i if incl else i - 1
        lo = max(0, i - w)
        if hi < lo:
            continue
        out[i] = (ps[hi + 1] - ps[lo]) / (hi - lo + 1)
    return out


def indicators(rows):
    c = [r[4] for r in rows]
    h = [r[2] for r in rows]
    l = [r[3] for r in rows]
    dv = [r[5] for r in rows]
    n = len(rows)
    pc = [c[i - 1] if i > 0 else c[i] for i in range(n)]
    tr = [max(h[i] - l[i], abs(h[i] - pc[i]), abs(l[i] - pc[i])) for i in range(n)]
    cmax = _sliding(c, 365, True, True)
    dd = [c[i] / cmax[i] for i in range(n)]
    return dict(c=c, o=[r[1] for r in rows], h=h, l=l, dv=dv, d=[r[0] for r in rows],
                sma20=_mean(c, 19, True),
                sma200=_mean(c, 199, True),
                atr14=_mean(tr, 13, True),
                adv30=_mean(dv, 29, True),
                adv40p=_mean(dv, 40, False),
                hh40=_sliding(h, 40, False, True),
                ll40=_sliding(l, 40, False, False),
                mindd120=_sliding(dd, 120, True, False))


def load_gate(style):
    """`_rt_gate`:majors/cap 的 level = Π(1+ret),gate = level > 200 日均线(n<200 时开着)。"""
    rows = [x for x in style if x.get("ret") is not None and x["ret"] > -0.95]
    rows.sort(key=lambda x: x["d"])
    lvl, cur = [], 1.0
    for x in rows:
        cur *= (1.0 + x["ret"])
        lvl.append(cur)
    gate = {}
    for i, x in enumerate(rows):
        w = lvl[max(0, i - 199):i + 1]
        gate[x["d"]] = bool(len(w) < 200 or lvl[i] > sum(w) / len(w))
    return gate


def sig_at(a, i, gate_open):
    """`r_tickets_scan` 的 sig 谓词。"""
    if i < 219 or a["atr14"][i] is None or a["atr14"][i] <= 0:
        return False
    if a["adv30"][i] is None or a["adv30"][i] < 5e6:
        return False
    if a["mindd120"][i] is None or a["mindd120"][i] > 0.5:
        return False
    hh, ll = a["hh40"][i], a["ll40"][i]
    if hh is None or ll is None or hh == 0 or (hh - ll) / hh > 0.40:
        return False
    if not (a["c"][i] > hh):
        return False
    if a["sma200"][i] is None or not (a["c"][i] > a["sma200"][i]):
        return False
    if a["adv40p"][i] is None or a["dv"][i] < 2 * a["adv40p"][i]:
        return False
    return gate_open


# ---------------------------------------------------------------- 回放票源(r_tickets_scan)
def scan(bars, gate, d_from, d_to):
    inds = {s: indicators(r) for s, r in bars.items()}
    idx = {s: {r[0]: k for k, r in enumerate(rws)} for s, rws in bars.items()}
    daycount = defaultdict(int)
    for s, rws in bars.items():
        for r in rws:
            daycount[r[0]] += 1
    # SQL 的数据完整性 guard(`n_bars < max(20, 0.8 × 前一日)` ⇒ 停机)在回放里撞上 perp_bv_daily 的
    # 历史空洞:2022-02-26~28 与 2022-04-01~02 各有 43 个符号缺 bar(邻日 119/121 → 76,几天后自动恢复)。
    # 口径:空洞日照常推进(持仓的止损/出场照走),但**不生成新信号**(那天数据不全,信号不可信);
    # 真的萎缩(不恢复)仍照 SQL 停机。
    ds_all = []
    _d = d_from
    while _d <= d_to:                      # 日历(不是「有 bar 的日」——整天缺 bar 的日子也要看见)
        ds_all.append(_d.isoformat())
        _d += dt.timedelta(days=1)
    hole_days, guard_events = set(), []
    for i, dd in enumerate(ds_all):
        if i == 0:
            continue
        n, pn = daycount.get(dd, 0), daycount.get(ds_all[i - 1], 0)
        if n >= max(20, 0.8 * pn):
            continue
        fwd = max((daycount.get(ds_all[j], 0) for j in range(i + 1, min(len(ds_all), i + 6))), default=0)
        kind = "hole" if fwd >= 0.8 * pn else "attrition"
        guard_events.append({"d": dd, "n_bars": n, "n_prev": pn, "fwd_max": fwd, "kind": kind})
        if kind == "hole":
            thr = 0.8 * pn
            j = i
            while j < len(ds_all) and daycount.get(ds_all[j], 0) < thr:
                hole_days.add(ds_all[j])
                j += 1
    live, tickets, stopped = {}, [], None
    d = d_from
    while d <= d_to:
        ds = d.isoformat()
        n_bars = daycount.get(ds, 0)
        n_prev = daycount.get((d - dt.timedelta(days=1)).isoformat(), 0)
        if n_bars < max(20, 0.8 * n_prev) and ds not in hole_days:
            stopped = f"only {n_bars} bars on {ds} (previous day {n_prev})"
            break
        if ds not in gate and ds > "2020-07-18":
            stopped = f"majors index missing on {ds}"
            break
        # 1) 昨天挂的 SMA20 出场标记:今天开盘出
        for s, t in list(live.items()):
            if t["status"] == "open" and t["exit_flag"] and ds in idx[s]:
                t.update(status="closed", exit_d=ds, exit_reason="sma20", exit_px=inds[s]["o"][idx[s][ds]])
                del live[s]
        # 2) pending:今天开盘成交
        for s, t in list(live.items()):
            if t["status"] == "pending" and ds in idx[s]:
                o = inds[s]["o"][idx[s][ds]]
                if o - 2.5 * t["atr14"] > 0:
                    t.update(status="open", filled=True, entry_d=ds, entry_px=o,
                             stop_px=o - 2.5 * t["atr14"], exit_flag=False, bars_held=0)
                else:
                    t.update(status="void", filled=False, entry_d=ds, entry_px=o,
                             stop_px=o - 2.5 * t["atr14"])
                    del live[s]
        # 3) 止损 > 收盘破 SMA20(挂标记) > 120 根到期
        for s, t in list(live.items()):
            if t["status"] != "open" or t["exit_flag"] or ds not in idx[s]:
                continue
            i = idx[s][ds]
            a = inds[s]
            t["bars_held"] += 1
            if a["l"][i] <= t["stop_px"]:
                px = a["o"][i] if (ds > t["entry_d"] and a["o"][i] <= t["stop_px"]) else t["stop_px"]
                t.update(status="closed", exit_d=ds, exit_reason="stop", exit_px=px)
                del live[s]
                continue
            if a["c"][i] < a["sma20"][i]:
                t["exit_flag"] = True
            if t["bars_held"] >= 120:
                t.update(status="closed", exit_d=ds, exit_reason="time", exit_px=a["c"][i])
                del live[s]
        # 3b) 停更的票:最后一根收盘平
        for s, t in list(live.items()):
            if t["status"] != "open":
                continue
            prior = [x for x in idx[s] if x <= ds]
            if prior and prior[-1] < (d - dt.timedelta(days=9)).isoformat():
                t.update(status="closed", exit_d=prior[-1], exit_reason="no_data",
                         exit_px=inds[s]["c"][idx[s][prior[-1]]])
                del live[s]
        # 4) 今天的信号(数据空洞日不生成新信号)
        for s in bars:
            if ds in hole_days:
                break
            if ds not in idx[s] or s in live:
                continue
            i = idx[s][ds]
            g = gate.get(ds, True)
            if not sig_at(inds[s], i, g):
                continue
            t = dict(tid=f"{s}:{ds}", symbol=s, signal_d=ds, atr14=inds[s]["atr14"][i],
                     ref_close=inds[s]["c"][i], gate_open=g, status="pending" if g else "blocked",
                     filled=False, entry_d=None,
                     entry_px=None, stop_px=None, exit_flag=False, bars_held=0, exit_d=None,
                     exit_px=None, exit_reason=None, r=None)
            tickets.append(t)
            if g:
                live[s] = t      # 闸门关着的票在 SQL 里是 'blocked',不占位、不进场
        d += dt.timedelta(days=1)
    # R(与 r_tickets_nav / 库里的 r_mult 同式):(出场价-进场价)/(进场价-止损价) - 0.004*进场价/(进场价-止损价)
    for t in tickets:
        if t["exit_px"] is not None and t["entry_px"] and t["entry_px"] != t["stop_px"]:
            den = t["entry_px"] - t["stop_px"]
            t["r"] = (t["exit_px"] - t["entry_px"]) / den - 0.004 * t["entry_px"] / den
    return tickets, stopped, sorted(hole_days), guard_events


# ---------------------------------------------------------------- 主机的逐日模拟
def _szd(px):
    """HL 的 szDecimals 没有历史快照,用价格档近似(误差 ≈ 1% 的取整损耗,已在报告里声明)。"""
    for lim, d in ((10000, 5), (1000, 4), (100, 3), (10, 2), (1, 1)):
        if px >= lim:
            return d
    return 0


def simulate(tickets, bars, gate, cap_frac, equity0=EQUITY0, risk_frac=RISK_FRAC,
             cap_n=CAP_N, min_notional=MIN_NOTIONAL, exact_qty=False):
    # 逐日的价
    om, cm, dates = {}, {}, {}
    for s, rws in bars.items():
        om[s] = {r[0]: r[1] for r in rws}
        cm[s] = {r[0]: r[4] for r in rws}
        dates[s] = [r[0] for r in rws]

    def mark(sym, day, use_open):
        m = om if use_open else cm
        dk = day.isoformat() if isinstance(day, dt.date) else day
        px = m.get(sym, {}).get(dk)
        if px is not None:
            return px
        ds = dates.get(sym) or []
        i = bisect.bisect_right(ds, dk) - 1
        return cm[sym][ds[i]] if i >= 0 else None

    entries = defaultdict(list)
    for t in tickets:
        if t.get("filled") and t["entry_d"] and t["entry_px"]:
            entries[t["entry_d"]].append(t)
    for d in entries:
        entries[d].sort(key=lambda t: (t["signal_d"], t["symbol"]))

    exits_open = defaultdict(list)   # 止损 / 破 SMA20:当天开盘平
    exits_close = defaultdict(list)  # 120 根到期 / 停更:当天收盘平
    for t in tickets:
        if not t["exit_d"] or t["exit_px"] is None:
            continue
        (exits_open if t["exit_reason"] in ("stop", "sma20") else exits_close)[t["exit_d"]].append(t)

    days = []
    d = dt.date.fromisoformat(min(entries)) if entries else D_FROM
    ex = [dt.date.fromisoformat(t["exit_d"]) for t in tickets if t["exit_d"]]
    last = max(ex + [d])
    while d <= last:
        days.append(d)
        d += dt.timedelta(days=1)

    book = {}          # tid -> pos
    realized = 0.0
    curve = []
    taken, blocked_gross, blocked_cap, blocked_min, blocked_coin = set(), [], [], [], []
    gross_hist, gross_ratio_hist = [], []
    held = set()

    def equity(day, use_open):
        e = equity0 + realized
        for p in book.values():
            px = mark(p["symbol"], day, use_open)
            if px is None:
                continue
            e += p["qty"] * (px - p["entry_px"]) - p["qty"] * 0.002 * p["entry_px"]
        return e

    for day in days:
        ds = day.isoformat()
        # 1) 开盘出场
        for t in exits_open.get(ds, []):
            p = book.pop(t["tid"], None)
            if not p:
                continue
            realized += p["qty"] * (p["exit_px"] - p["entry_px"] - 0.004 * p["entry_px"])
            held.discard(p["symbol"])
        # 2) 进场(主机的跳过规则)
        eq_open = equity(day, True)
        alloc = eq_open
        gross_limit = alloc * cap_frac
        gross = 0.0
        for p in book.values():
            px = mark(p["symbol"], day, True)
            gross += p["qty"] * (px if px is not None else p["entry_px"])
        gross_start = gross
        for t in entries.get(ds, []):
            if len(book) >= cap_n:
                blocked_cap.append(t)
                continue
            if t["symbol"] in held:
                blocked_coin.append(t)
                continue
            # 主机计划里的 stop_frac = STOP_ATR × ATR(信号日) ÷ 收盘(信号日)
            if t.get("ref_close"):
                stop_frac = STOP_ATR * t["atr14"] / t["ref_close"]
            else:
                stop_frac = (t["entry_px"] - t["stop_px"]) / t["entry_px"]
            mid = mark(t["symbol"], day, True)
            if not mid or mid <= 0 or not (0 < stop_frac < 0.9):
                blocked_min.append(t)
                continue
            target = min(alloc * risk_frac / stop_frac, alloc * 0.5)
            if exact_qty:                     # 归一化敏感性:不按 HL 的 szDecimals 取整(否则 $1 净值下 qty 全变 0)
                qty = target / mid
            else:
                qty = math.floor(target / mid * (10 ** _szd(mid)) + 1e-9) / (10 ** _szd(mid))
            n = round(qty * mid, 2)          # 主机 size_entry 的 notional = round(qty × mid, 2)
            if n < min_notional:
                blocked_min.append(t)
                continue
            if gross + n > gross_limit:
                blocked_gross.append({**t, "notional": n, "gross_before": gross,
                                      "gross_limit": gross_limit, "alloc": alloc})
                continue
            gross += n
            book[t["tid"]] = dict(tid=t["tid"], symbol=t["symbol"], entry_px=t["entry_px"],
                                   stop_px=t["stop_px"], qty=qty, exit_d=t["exit_d"],
                                   exit_px=t["exit_px"], exit_reason=t["exit_reason"], r=t["r"])
            held.add(t["symbol"])
            taken.add(t["tid"])
        gross_hist.append(gross)          # 当日进场后的名义合计
        if eq_open > 0:
            gross_ratio_hist.append(gross / eq_open)
        # 3) 收盘出场
        for t in exits_close.get(ds, []):
            p = book.pop(t["tid"], None)
            if not p:
                continue
            realized += p["qty"] * (p["exit_px"] - p["entry_px"] - 0.004 * p["entry_px"])
            held.discard(p["symbol"])
        # 4) 收盘净值
        eq = equity(day, False)
        curve.append((ds, eq, len(book), gross))

    return dict(curve=curve, taken=taken, blocked_gross=blocked_gross, blocked_cap=blocked_cap,
                blocked_min=blocked_min, blocked_coin=blocked_coin,
                gross_hist=gross_hist, gross_ratio_hist=gross_ratio_hist)


# ---------------------------------------------------------------- 指标
def curve_stats(curve, equity0):
    eq = [c[1] for c in curve]
    peak, mdd = -1e18, 0.0
    for x in eq:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1.0)
    days = max(1, len(eq))
    total = eq[-1] / equity0 - 1.0
    cagr = (eq[-1] / equity0) ** (365.0 / days) - 1.0 if eq[-1] > 0 else None
    # 最差月
    bym = defaultdict(list)
    for (ds, v, *_rest) in curve:
        bym[ds[:7]].append(v)
    months = []
    prev = equity0
    for m in sorted(bym):
        last = bym[m][-1]
        months.append((m, last / prev - 1.0))
        prev = last
    worst = min(months, key=lambda x: x[1]) if months else (None, None)
    return dict(total_return=total, cagr=cagr, max_dd=mdd,
                calmar=(cagr / abs(mdd) if cagr is not None and mdd < 0 else None),
                end_equity=eq[-1], n_days=days, worst_month=worst[0], worst_month_ret=worst[1],
                n_months=len(months))


def q(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
    return s[i]


def rdist(rs):
    if not rs:
        return dict(n=0)
    return dict(n=len(rs), sum_r=round(sum(rs), 4), mean_r=round(sum(rs) / len(rs), 4),
                min=round(min(rs), 4), p25=round(q(rs, 0.25), 4), med=round(q(rs, 0.50), 4),
                p75=round(q(rs, 0.75), 4), max=round(max(rs), 4),
                win_pct=round(100.0 * sum(1 for r in rs if r > 0) / len(rs), 1))


# ---------------------------------------------------------------- 主流程
def main():
    pairs, style, bars, uni = fetch_all()
    bars = {s: v for s, v in bars.items() if v}
    print(f"回放票源:perp_bv_daily {sum(len(v) for v in bars.values())} 行 / {len(bars)} 个符号",
          file=sys.stderr)
    gate = load_gate(style)
    print(f"gate:{len(gate)} 天 ({min(gate)} → {max(gate)})", file=sys.stderr)
    tickets, stopped, hole_days, guard_events = scan(bars, gate, D_FROM, D_TO)
    print(f"scan:{len(tickets)} 张票,停止原因 {stopped};空洞日 {hole_days}", file=sys.stderr)
    entered = [t for t in tickets if t.get("filled")]
    closed = [t for t in entered if t["exit_d"]]

    res = {"as_of": dt.date.today().isoformat(), "window": [D_FROM.isoformat(), D_TO.isoformat()],
           "scan_stopped": stopped, "universe_symbols": len(bars),
           "universe": uni,
           "data_hole_days": hole_days, "guard_events": guard_events,
           "tickets_total": len(tickets), "tickets_entered": len(entered),
           "tickets_closed": len(closed),
           "tickets_still_open_at_end": len(entered) - len(closed),
           "gate_days": len(gate), "gate_range": [min(gate), max(gate)],
           "gate_days_open": sum(1 for v in gate.values() if v),
           "gate_days_closed": sum(1 for v in gate.values() if not v),
           "equity0": EQUITY0, "risk_frac": RISK_FRAC, "cap_n": CAP_N,
           "min_notional": MIN_NOTIONAL, "settings": {}}

    for c in CAPS:
        sim = simulate(tickets, bars, gate, c)
        st = curve_stats(sim["curve"], EQUITY0)
        bg = sim["blocked_gross"]
        st["tickets_taken"] = len(sim["taken"])
        st["blocked_by_gross_cap"] = len(bg)
        st["blocked_by_cap10"] = len(sim["blocked_cap"])
        st["blocked_by_min_notional"] = len(sim["blocked_min"])
        st["blocked_by_same_coin"] = len(sim["blocked_coin"])
        st["blocked_r_dist"] = rdist([b["r"] for b in bg if b.get("r") is not None])
        st["gross_usd"] = dict(median=q(sim["gross_hist"], 0.5), p95=q(sim["gross_hist"], 0.95),
                               max=max(sim["gross_hist"] or [0]))
        st["gross_frac_of_equity"] = dict(median=q(sim["gross_ratio_hist"], 0.5),
                                          p95=q(sim["gross_ratio_hist"], 0.95),
                                          max=max(sim["gross_ratio_hist"] or [0]))
        # cap 只在**建仓那一刻**判定(主机规则:合计超过 ⇒ 这张票不做)。持仓期间净值/价格一动,
        # 名义÷净值可以漂到 cap 之上 —— 记下越界的日数与最大比值,免得「没被挡」被读成「始终没超」。
        st["gross_ratio_over_cap_days"] = sum(1 for r in sim["gross_ratio_hist"] if r > c + 1e-9)
        st["taken_by_year"] = {}
        for tid in sorted(sim["taken"]):
            y = tid.split(":")[1][:4]
            st["taken_by_year"][y] = st["taken_by_year"].get(y, 0) + 1
        st["blocked_by_year"] = {}
        for b in bg:
            y = b["signal_d"][:4]
            st["blocked_by_year"][y] = st["blocked_by_year"].get(y, 0) + 1
        st["_taken"] = sorted(sim["taken"])
        st["_blocked_gross_ids"] = sorted(b["tid"] for b in bg)
        res["settings"][f"{c:.2f}"] = st
        print(f"cap {c:.2f}:{st['total_return']*100:.2f}% CAGR {st['cagr']*100:.2f}% "
              f"mDD {st['max_dd']*100:.2f}% taken {st['tickets_taken']} "
              f"blocked {st['blocked_by_gross_cap']}", file=sys.stderr)

    # 30 → 40 的边际
    t30 = set(res["settings"]["0.30"]["_taken"])
    t40 = set(res["settings"]["0.40"]["_taken"])
    marginal = sorted(t40 - t30)
    t100 = set(res["settings"]["1.00"]["_taken"])
    marg_info = []
    by_tid = {t["tid"]: t for t in tickets}
    for tid in marginal:
        t = by_tid[tid]
        marg_info.append({"tid": tid, "symbol": t["symbol"], "signal_d": t["signal_d"],
                          "entry_d": t["entry_d"], "r": t["r"], "exit_reason": t["exit_reason"],
                          "regime_entry": "above" if gate.get(t["entry_d"], True) else "below",
                          "regime_signal": "above" if gate.get(t["signal_d"], True) else "below"})
    res["marginal_30_to_40"] = {
        "n": len(marginal),
        "r_dist": rdist([m["r"] for m in marg_info if m["r"] is not None]),
        "by_regime_entry": {
            "above": rdist([m["r"] for m in marg_info if m["regime_entry"] == "above" and m["r"] is not None]),
            "below": rdist([m["r"] for m in marg_info if m["regime_entry"] == "below" and m["r"] is not None])},
        "tickets": marg_info,
        "also_in_100": len([tid for tid in marginal if tid in t100]),
        "n_100_vs_40": len(t100 - t40),
    }
    # 40 → 100 的边际(参考档)
    marg40_100 = sorted(t100 - t40)
    res["marginal_40_to_100"] = {
        "n": len(marg40_100),
        "r_dist": rdist([by_tid[x]["r"] for x in marg40_100 if by_tid[x].get("r") is not None]),
    }
    # 反向边际:30% 做得到、40% 反而做不到的票(路径依赖 —— 名义占住 10 个仓位)
    rev = sorted(t30 - t40)
    rev_info = [{"tid": x, "symbol": by_tid[x]["symbol"], "signal_d": by_tid[x]["signal_d"],
                 "entry_d": by_tid[x]["entry_d"], "r": by_tid[x]["r"],
                 "exit_reason": by_tid[x]["exit_reason"],
                 "regime_entry": "above" if gate.get(by_tid[x]["entry_d"], True) else "below"}
                for x in rev]
    res["marginal_30_only"] = {
        "n": len(rev),
        "r_dist": rdist([m["r"] for m in rev_info if m["r"] is not None]),
        "by_regime_entry": {
            "above": rdist([m["r"] for m in rev_info if m["regime_entry"] == "above" and m["r"] is not None]),
            "below": rdist([m["r"] for m in rev_info if m["regime_entry"] == "below" and m["r"] is not None])},
        "tickets": rev_info,
    }
    res["all_tickets_r"] = rdist([t["r"] for t in tickets if t.get("r") is not None])

    # 真钱尺度:今天净值 $630 下每张票的名义(用各自的止损距离;档位只决定做不做)
    per_ticket = []
    for t in entered:
        stop_frac = (STOP_ATR * t["atr14"] / t["ref_close"]) if t.get("ref_close") else \
                    (t["entry_px"] - t["stop_px"]) / t["entry_px"]
        target = min(EQUITY0 * RISK_FRAC / stop_frac, EQUITY0 * 0.5)
        per_ticket.append({"tid": t["tid"], "stop_frac": stop_frac, "target_notional": target,
                           "below_min": target < MIN_NOTIONAL,
                           "taken30": t["tid"] in t30, "taken40": t["tid"] in t40,
                           "taken100": t["tid"] in t100})
    res["money_scale_630"] = {
        "n_tickets": len(per_ticket),
        "below_10_all": round(100.0 * sum(1 for x in per_ticket if x["below_min"]) / len(per_ticket), 1),
        "below_10_taken30": round(100.0 * sum(1 for x in per_ticket if x["below_min"] and x["taken30"])
                                  / max(1, len([x for x in per_ticket if x["taken30"]])), 1),
        "below_10_taken40": round(100.0 * sum(1 for x in per_ticket if x["below_min"] and x["taken40"])
                                  / max(1, len([x for x in per_ticket if x["taken40"]])), 1),
        "below_10_taken100": round(100.0 * sum(1 for x in per_ticket if x["below_min"] and x["taken100"])
                                   / max(1, len([x for x in per_ticket if x["taken100"]])), 1),
        "median_target_notional": q([x["target_notional"] for x in per_ticket], 0.5),
        "p05_target_notional": q([x["target_notional"] for x in per_ticket], 0.05),
    }

    # 敏感性:归一化净值(equity0=1,关掉 $10 最小名义规则与取整)—— 三档的相对次序不该变
    norm = {}
    for c in CAPS:
        sim = simulate(tickets, bars, gate, c, equity0=1.0, min_notional=0.0, exact_qty=True)
        st = curve_stats(sim["curve"], 1.0)
        norm[f"{c:.2f}"] = {"total_return": st["total_return"], "cagr": st["cagr"],
                            "max_dd": st["max_dd"], "taken": len(sim["taken"]),
                            "blocked_gross": len(sim["blocked_gross"])}
    res["sensitivity_normalised"] = norm
    # 敏感性二:只关 $10 最小名义规则(净值仍 $630,取整照旧)
    for c in CAPS:
        sim = simulate(tickets, bars, gate, c, equity0=EQUITY0, min_notional=0.0)
        st = curve_stats(sim["curve"], EQUITY0)
        res.setdefault("sensitivity_no_min_notional", {})[f"{c:.2f}"] = {
            "total_return": st["total_return"], "cagr": st["cagr"], "max_dd": st["max_dd"],
            "taken": len(sim["taken"]), "blocked_gross": len(sim["blocked_gross"])}

    # 把内部集合剔掉
    for k, v in res["settings"].items():
        v.pop("_taken", None)
        v.pop("_blocked_gross_ids", None)
    out = os.path.join(HERE, "t251_results.json")
    json.dump(res, open(out, "w"), indent=1, default=str)
    print(f"写出 {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
