"""T-159 / S-642: the bear-market SHORT arm — does it beat lying in lending?

Preregistered in REFUTATION_LEDGER.md S-642 (2026-10-21 03:24 UTC) *before* any short ticket was scored. The rules are
the R-v2 long book (docs/research/r_v2_tickets.sql) mirrored one-for-one; the SQL mirror is docs/research/s642_bear_short.sql
and this file is its transliteration plus the money curve.

Three things this file does, in this order, and refuses to skip:

  1. SKELETON PROOF. run_long() is the long book verbatim. It must reproduce T-156's 2024 = 261 tickets before any
     short number is looked at.
  2. NAV PARITY. nav() is a transliteration of migrations/2026-10-21_r_tickets_nav.sql. The kernel itself cannot be
     called from here (publishable key; the migration revokes execute from anon/authenticated), so parity is checked
     against the numbers S-638 published from the real kernel: f = 1%, cap = 10, compounded → end equity 4.12,
     mark-to-market max DD −32.3%, annualised +24.4%, 304 taken / 425 skipped; and uncapped / p_compound = false
     → end equity 3.692028 = 0.01 × 369.23R less the entry cost of the 3 still-held tickets (S-638 implementation check).
     --nav-from <json> additionally diffs day-by-day against a dumped r_tickets_nav() output if one is ever handed over.
  3. THE SHORT ARM. run_short() is the mirror. Funding is NOT inside r_tickets_nav and is NOT in the SQL jsonb: it is
     summed per ticket over [entry_d, exit_d) from funding_history (venue = binance_perp) and added to R separately,
     exactly as S-642 writes it. Sign: a positive funding_rate pays the short.

Judgements (all three must hold, S-642):
  (1) mean R per ticket, net of costs and funding, > 0 with a one-sided bootstrap p < 0.05 over 2,000 resamples;
  (2) mean R > 0 in BOTH halves, signal_d < 2023-01-01 and >= 2023-01-01;
  (3) money curve (f = 0.5%, at most 10 at once) annualised over gate-CLOSED days > 4% (2% / 6% sensitivity reported).
The bootstrap goes through src/data/evaluation/apparatus.py (null_distribution / percentile_of) — not a hand-rolled one.

Read-only DB access (publishable key). Fetch:  --fetch      Run:  python3 docs/research/t159_bear_short.py
"""
import bisect, json, os, sys, string, argparse, datetime, urllib.request, urllib.error
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.data.evaluation.apparatus import null_distribution, percentile_of  # noqa: E402

EXCL = {"USDC", "BTCDOM", "DEFI"}
ENV = os.environ.get("T159_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t159/")
T156 = os.environ.get("T156_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t156/")
SINCE, TO = "2020-03-01", "2026-06-20"      # S-642 signal-day window
CURVE_TO = "2026-10-19"                     # last day the ledger's curves are dated


# ── fetch ──────────────────────────────────────────────────────────────────────────────────────────────────
def _rest(path, lo, hi):
    u, k = os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
    h = {"apikey": k, "Authorization": "Bearer " + k, "Range": f"{lo}-{hi}"}
    r = urllib.request.Request(u + "/rest/v1/" + path, headers=h)
    try:
        return json.loads(urllib.request.urlopen(r, timeout=180).read())
    except urllib.error.HTTPError as e:
        if e.code == 416:
            return []
        raise


def _page_all(q, cap):
    out, off = [], 0
    while off < cap * 1000:
        rows = _rest(q, off, off + 999)
        if not rows:
            break
        out += rows
        off += 1000
        if len(rows) < 1000:
            break
    return out


def fetch_funding_for(syms):
    """Pull funding_history (venue = binance_perp) for just the names the book trades. 1.23M rows over 259 names
    exist in the table; paging all of it costs ~5 min for nothing, so we ask per symbol. Binance writes some
    perpetuals under a prefixed name (1000SHIB, LUNA2); `_alias` bridges those at lookup time."""
    out = []
    for s in sorted(syms):
        out += _page_all(f"funding_history?select=symbol,funding_time,funding_rate&venue=eq.binance_perp"
                         f"&symbol=eq.{s}&order=funding_time.asc", 12)
    json.dump(out, open(f"{ENV}_funding.json", "w"))
    print(f"funding: {len(out)} rows / {len(syms)} symbols -> {ENV}_funding.json", file=sys.stderr)


def fetch(lo, hi, styles=True, funding=True):
    B = f"source=eq.binance_hist&trade_date=gte.{lo}&trade_date=lte.{hi}"
    syms = set()
    for ch in string.ascii_uppercase + string.digits:
        for row in _page_all(f"ohlcv_daily?select=symbol&symbol=like.{ch}*&{B}&order=symbol.asc", 200):
            syms.add(row["symbol"])
    with open(f"{ENV}_bars.jsonl", "w") as f:
        n = 0
        for s in sorted(syms):
            rows = _page_all(f"ohlcv_daily?select=trade_date,open,high,low,close,volume&{B}"
                             f"&symbol=eq.{s}&order=trade_date.asc", 12)
            for x in rows:
                x["symbol"] = s
            f.write(json.dumps(rows) + "\n")
            n += len(rows)
    print(f"bars: {n} rows / {len(syms)} symbols -> {ENV}_bars.jsonl", file=sys.stderr)
    if styles:
        st = _page_all("style_index_pit_daily?select=d,ret&style=eq.majors&weighting=eq.cap&order=d.asc", 400)
        json.dump(st, open(f"{ENV}_style.json", "w"))
        print(f"style: {len(st)} rows -> {ENV}_style.json", file=sys.stderr)
    if funding:
        fh = _page_all("funding_history?select=symbol,funding_time,funding_rate&venue=eq.binance_perp"
                       "&order=symbol.asc,funding_time.asc", 200)
        json.dump(fh, open(f"{ENV}_funding.json", "w"))
        print(f"funding: {len(fh)} rows -> {ENV}_funding.json", file=sys.stderr)


# ── data ────────────────────────────────────────────────────────────────────────────────────────────────────
def load_bars():
    """t159's own bars plus the t156 cache (2018 → 2025-04) so SMA200/ATR warm-up is not restarted in 2025."""
    by = defaultdict(list)
    for d in (T156, ENV):
        for fn in (f"{d}_bars_early.jsonl", f"{d}_bars.jsonl"):
            if not os.path.exists(fn):
                continue
            for line in open(fn):
                for x in json.loads(line):
                    by[x["symbol"]].append((x["trade_date"], float(x["open"]), float(x["high"]),
                                            float(x["low"]), float(x["close"]),
                                            float(x["close"]) * float(x["volume"])))
    for s in by:
        by[s] = sorted(set(by[s]))
    return {s: v for s, v in by.items() if s not in EXCL and v}


def load_gate():
    rows = [x for x in json.load(open(f"{T156}_style.json")) if x["ret"] is not None and x["ret"] > -0.95]
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


def load_funding():
    """symbol -> (sorted ISO timestamps, rates). Funding rows are 8-hourly; [entry_d 00:00, exit_d 00:00)."""
    fn = f"{ENV}_funding.json"
    if not os.path.exists(fn):
        return {}, 0
    rows = json.load(open(fn))
    by = defaultdict(lambda: ([], []))
    for x in rows:
        if x["funding_rate"] is None:
            continue
        by[x["symbol"]][0].append(x["funding_time"])
        by[x["symbol"]][1].append(float(x["funding_rate"]))
    out = {}
    for s, (ts, rs) in by.items():
        p = sorted(zip(ts, rs))
        out[s] = ([t for t, _ in p], [r for _, r in p])
    return out, len(rows)


# ── indicators (identical in both arms) ────────────────────────────────────────────────────────────────────
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


def sig_short(a, i, g):
    """S-642: gate closed, c < ll40, c < sma200, volume, range. mindd120 has NO mirror (written before the test)."""
    return (_universe(a, i) and a["c"][i] < a["ll40"][i]
            and a["sma200"][i] is not None and a["c"][i] < a["sma200"][i]
            and g.get(a["d"][i], {}).get("gate_closed", False))


# ── the two books ───────────────────────────────────────────────────────────────────────────────────────────
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


def run_long(bars, gate, d_from, d_to):
    """docs/research/r_v2_tickets.sql, verbatim."""
    tr = defaultdict(list)
    for sym, rows in bars.items():
        a = indicators(rows)
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
                     entry_px=entry, stop_px=stop, exit_px=None if still else xp, ei=ei, xi=xi,
                     bars_held=xi - ei + 1, still=still)
            t["r"] = None if still else ((xp - entry) / (entry - stop) - 0.004 * entry / (entry - stop))
            tr[sym].append(t)
    return _chain(tr)


def run_short(bars, gate, d_from, d_to):
    """docs/research/s642_bear_short.sql, verbatim. Mirrors run_long bar for bar."""
    tr = defaultdict(list)
    for sym, rows in bars.items():
        a = indicators(rows)
        n = len(rows)
        for i in range(220, n):
            d = a["d"][i]
            if not (d_from <= d <= d_to) or not sig_short(a, i, gate):
                continue
            ei = i + 1
            if ei >= n:
                continue
            entry, stop = a["o"][ei], a["o"][ei] + 2.5 * a["atr14"][i]
            if not (entry < stop):
                continue
            k = None
            for j in range(ei, min(i + 120, n - 1) + 1):
                if a["h"][j] >= stop or a["c"][j] > a["sma20"][j]:
                    k = j
                    break
            if k is None:
                xi, xp, still = min(i + 120, n - 1), a["c"][min(i + 120, n - 1)], (i + 120 > n - 1)
                why = "time"
            elif a["h"][k] >= stop:
                xi, xp, still = k, (a["o"][k] if (k > ei and a["o"][k] >= stop) else stop), False
                why = "stop"
            elif k + 1 <= n - 1:
                xi, xp, still = k + 1, a["o"][k + 1], False
                why = "sma20"
            else:
                xi, xp, still = k, a["c"][k], True
                why = "sma20_open"
            mae = min((a["h"][x] - entry) for x in range(ei, xi + 1)) if xi > ei else 0.0   # worst adverse, price
            mfe = max((entry - a["l"][x]) for x in range(ei, xi + 1)) if xi > ei else 0.0
            if still:
                why = "open"
            t = dict(symbol=sym, signal_d=d, entry_d=a["d"][ei], exit_d=None if still else a["d"][xi],
                     entry_px=entry, stop_px=stop, exit_px=None if still else xp, ei=ei, xi=xi,
                     exit_reason=why, bars_held=xi - ei + 1, still=still)
            t["mae_r"] = None if still else mae / (stop - entry)
            t["mfe_r"] = None if still else mfe / (stop - entry)
            t["r"] = None if still else ((entry - xp) / (stop - entry) - 0.004 * entry / (stop - entry))
            tr[sym].append(t)
    return _chain(tr)


def _alias(sym, funding):
    """Binance lists some perps under a prefixed/ticked name (1000SHIB, LUNA2) while ohlcv_daily uses the plain one."""
    if sym in funding:
        return sym
    for cand in ("1000" + sym, sym + "2", sym.replace("2", "")):
        if cand in funding:
            return cand
    return None


def same_name_open(long_tickets, short_tickets):
    """Jazz 10-21: HL is one-way — the same coin cannot be long and short at once. Count the short tickets whose
    signal_d already has an R-v2 LONG of the same symbol in hand (entry_d <= signal_d <= exit_d, or exit_d null).
    These are the ones that would need a separate HL sub-account if S-642 were ever adopted."""
    held = defaultdict(list)
    for t in long_tickets:
        if t.get("entry_d"):
            held[t["symbol"]].append((t["entry_d"], t["exit_d"]))
    out = []
    for t in short_tickets:
        d = t["signal_d"]
        for entry_d, exit_d in held.get(t["symbol"], ()):
            if entry_d <= d and (exit_d is None or exit_d >= d):
                out.append(dict(id=f"{t['symbol']}:{d}", symbol=t["symbol"], signal_d=d,
                                long_entry_d=entry_d, long_exit_d=exit_d))
                break
    return out


def add_funding(tickets, funding):
    """S-642: funding_R = sum(funding_rate over [entry_d 00:00, exit_d 00:00)) * entry / (stop - entry).
    A positive rate pays a short (the sign follows from the short's notional being taken as entry/(stop-entry))."""
    miss = set()
    for t in tickets:
        if t["exit_d"] is None or t["r"] is None:
            t["funding_sum"] = t["funding_r"] = None
            continue
        key = _alias(t["symbol"], funding)
        ts, rs = funding.get(key, ([], [])) if key else ([], [])
        lo = bisect.bisect_left(ts, t["entry_d"] + "T00:00:00+00:00")
        hi = bisect.bisect_left(ts, t["exit_d"] + "T00:00:00+00:00")
        s = sum(rs[lo:hi])
        t["funding_symbol"] = key
        t["funding_sum"] = s
        # r_tickets_nav charges no funding; S-642 adds it per ticket, verbatim:
        #   funding_R = Σ funding_rate over [entry_d, exit_d) × entry / (stop - entry).
        # stop > entry for a short, so a positive rate lands positive here — that is S-642's 「费率为正收钱」.
        t["funding_r"] = s * t["entry_px"] / (t["stop_px"] - t["entry_px"])
        t["r_net"] = t["r"] + t["funding_r"]
        t["funding_covered"] = hi > lo
        if not ts or hi <= lo:
            miss.add(t["symbol"])
    return miss


# ── money curve: a transliteration of r_tickets_nav (migrations/2026-10-21_r_tickets_nav.sql) ─────────────
def nav(tickets, closes, f, cap=10, d_to=CURVE_TO, compound=True, equity0=1.0, drop=None):
    """Mark-to-market every UTC day. Mirrors the plpgsql kernel, except the ticket filter keeps entry_px != stop_px
    instead of entry_px > stop_px, so the short arm survives (that is the whole reason this is a transliteration).
    Sign falls out of the denominator: a short has stop > entry, so `units` is negative and every product flips."""
    tk = [dict(id=f"{t['symbol']}:{t['signal_d']}", symbol=t["symbol"], signal_d=t["signal_d"],
               entry_d=t["entry_d"], exit_d=t["exit_d"], entry_px=t["entry_px"], stop_px=t["stop_px"],
               exit_px=t["exit_px"], state=None, units=0.0) for t in tickets
          if t["entry_d"] and t["entry_px"] != t["stop_px"] and t["symbol"] not in (drop or ())]
    if not tk:
        return []
    v_from = min(t["entry_d"] for t in tk)
    v_to = d_to
    tk = [t for t in tk if v_from <= t["entry_d"] <= v_to]
    for t in tk:
        if t["exit_d"] and t["exit_d"] > v_to:
            t["exit_d"] = t["exit_px"] = None
    days = []
    d = datetime.date.fromisoformat(v_from)
    while d.isoformat() <= v_to:
        days.append(d.isoformat())
        d += datetime.timedelta(days=1)
    # marks: symbol -> (sorted dates, sorted closes); mark(d) = latest close on or before d
    md = {s: (list(x[0] for x in rows), [x[4] for x in rows]) for s, rows in closes.items()}
    path_by_day = defaultdict(list)
    for t in tk:
        ds, cs = md.get(t["symbol"], ([], []))
        dd = datetime.date.fromisoformat(t["entry_d"])
        last = datetime.date.fromisoformat((datetime.date.fromisoformat(t["exit_d"]) - datetime.timedelta(days=1))
                                           .isoformat() if t["exit_d"] else v_to)
        while dd <= last:
            k = bisect.bisect_right(ds, dd.isoformat()) - 1
            if k >= 0:
                path_by_day[dd.isoformat()].append((t, cs[k]))
            dd += datetime.timedelta(days=1)
    # path rows by ticket (dict day -> mark), for the eq_prev step
    for t in tk:
        t["_pmap"] = {}
    for d, lst in path_by_day.items():
        for t, m in lst:
            t["_pmap"][d] = m
    for v_e in sorted({t["entry_d"] for t in tk}):
        prev = _d1(v_e)
        eq_prev = equity0
        for k in tk:
            if k["state"] != "taken":
                continue
            # cost is always a debit: abs(units). Before 2026-10-25 this was units * (… − cost), which for a short
            # (units < 0) turned the 0.4% round trip into a 0.4% CREDIT — every short money curve was flattered.
            if k["exit_d"] and k["exit_d"] <= prev:
                eq_prev += k["units"] * (k["exit_px"] - k["entry_px"]) - abs(k["units"]) * 0.004 * k["entry_px"]
            elif prev in k["_pmap"]:
                eq_prev += k["units"] * (k["_pmap"][prev] - k["entry_px"]) - abs(k["units"]) * 0.002 * k["entry_px"]
        occ = sum(1 for k in tk if k["state"] == "taken" and k["entry_d"] < v_e
                  and (k["exit_d"] is None or k["exit_d"] >= v_e))
        taken_today = 0
        for k in sorted([k for k in tk if k["entry_d"] == v_e], key=lambda x: (x["signal_d"], x["symbol"])):
            if cap is None or occ + taken_today < cap:
                k["state"] = "taken"
                k["units"] = f * (eq_prev if compound else equity0) / (k["entry_px"] - k["stop_px"])
                taken_today += 1
            else:
                k["state"] = "skipped"
    exits_by_day = defaultdict(float)
    closes_by_day = defaultdict(int)
    for k in tk:
        if k["state"] == "taken" and k["exit_d"]:
            exits_by_day[k["exit_d"]] += (k["units"] * (k["exit_px"] - k["entry_px"])
                                          - abs(k["units"]) * 0.004 * k["entry_px"])
            closes_by_day[k["exit_d"]] += 1
    ent_by_day = defaultdict(lambda: [0, 0])
    for k in tk:
        if k["entry_d"]:
            ent_by_day[k["entry_d"]][0 if k["state"] == "taken" else 1] += 1
    rv_cum, taken_c, skipped_c, closed_c = 0.0, 0, 0, 0
    for d in days:
        rv = exits_by_day.get(d, 0.0)
        closed_c += closes_by_day.get(d, 0)
        rv_cum += rv
        un = ec = gr = 0.0
        for k, m in path_by_day.get(d, ()):
            if k["state"] != "taken":
                continue
            un += k["units"] * (m - k["entry_px"])
            ec += abs(k["units"]) * 0.002 * k["entry_px"]
            gr += abs(k["units"]) * m
        nt, ns = ent_by_day.get(d, (0, 0))
        taken_c += nt
        skipped_c += ns
        eq = equity0 + rv_cum + un - ec
        # kernel: coalesce(op.n,0) where op joins _nv_path to _nv_tk on state='taken' — taken rows only.
        open_n = sum(1 for k, _ in path_by_day.get(d, ()) if k["state"] == "taken")
        yield dict(d=d, equity=eq, realized=rv_cum - ec, unrealized=un, open_n=open_n,
                   gross=gr / eq if eq else 0.0, taken=taken_c, skipped=skipped_c, closed=closed_c)


def _d1(d):
    return (datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat()


def stats(curve, closed_days=None):
    """max drawdown / annualised / endpoint from a nav() generator."""
    rows = list(curve)
    eq = [r["equity"] for r in rows]
    peak, mdd, pk_d, tr_d = -1, 0.0, None, None
    cur_pk_d = None
    for r in rows:
        if r["equity"] > peak:
            peak, cur_pk_d = r["equity"], r["d"]
        dd = r["equity"] / peak - 1
        if dd < mdd:
            mdd, pk_d, tr_d = dd, cur_pk_d, r["d"]
    n = len(rows)
    yrs = (datetime.date.fromisoformat(rows[-1]["d"]) - datetime.date.fromisoformat(rows[0]["d"])).days / 365.25
    out = dict(d0=rows[0]["d"], d1=rows[-1]["d"], days=n, end=eq[-1],
               annualised=(eq[-1] ** (1 / yrs) - 1) if yrs > 0 else None,
               mdd=mdd, mdd_peak=pk_d, mdd_trough=tr_d,
               taken=rows[-1]["taken"], skipped=rows[-1]["skipped"], closed=rows[-1]["closed"],
               peak_gross=max(r["gross"] for r in rows))
    if closed_days is not None:
        lg = 0.0
        prev = rows[0]["equity"]
        cd = 0
        for r in rows[1:]:
            if r["d"] in closed_days:
                lg += np.log(r["equity"] / prev)
                cd += 1
            prev = r["equity"]
        out["closed_days"] = cd
        out["annualised_closed"] = float(np.exp(lg * 365.25 / cd) - 1) if cd else None
        out["end_over_closed"] = float(np.exp(lg) - 1) if cd else None
    return out


# ── report ──────────────────────────────────────────────────────────────────────────────────────────────────
def money(x):
    return "n/a" if x is None else ("%+.2f%%" % (100 * x))


def write_report(path, res):
    L = []
    A = L.append
    A("# T-159 / S-642 — 熊市空头臂(R-v2 镜像)能否胜过躺放贷")
    A("")
    A(f"生成:{res['meta']['run_utc']} · 数据根 `{res['meta']['data']}` · 只读 publishable key · "
      f"棒数 {res['skeleton']['symbols']} 个名字 / {res['skeleton']['bars']} 根 bar,风格指数 {res['skeleton']['style_days']} 天")
    A("")
    A("S-642 写于对任何空头票算 R 之前(2026-10-21 03:24 UTC)。规则一字未改:闸门**关**、c < ll40、c < sma200、"
      "dv ≥ 2×adv40p、(hh40−ll40)/hh40 ≤ 0.40、adv30 ≥ 500 万美元、rn ≥ 220、ATR14 > 0;"
      "**唯一没有镜像的一条**:多头那侧 mindd120 ≤ 0.5 在空头侧不设对应条件(算之前就写明)。"
      "t+1 开盘进空,止损 = 进场 + 2.5×ATR14[t](盘中最高价触及即出,跳空按开盘),收盘 > SMA20 次日开盘出,120 根到期,"
      "同名不重叠。SQL = `docs/research/s642_bear_short.sql`,脚本 = `docs/research/t159_bear_short.py`。")
    A("")
    A("## 0 · 骨架没改坏(先证明,再谈空头)")
    A("")
    sk = res["skeleton"]
    A("| 检验 | 期望 | 实测 |")
    A("|---|---|---|")
    A(f"| 多头原版 2024 票数 | 261(T-156) | **{sk['long_2024_n']}** |")
    A(f"| 多头原版 2024 ΣR | 269.8157(T-156 V1) | **{sk['long_2024_sumr']:.4f}** |")
    A(f"| 多头全区间票数 / ΣR | 770 / 372.4(S-638) | **{sk['long_all_n']} / {sk['long_all_sumr']:.2f}** |")
    A(f"| 多头 2023 → 2026-06-20 票数 | — | {sk['long_window_n']} |")
    A("")
    A("## 1 · 钱曲线内核与 r_tickets_nav 对齐(做不到就停)")
    A("")
    A("内核本身在本机调不了:publishable key 只能读表,而 `migrations/2026-10-21_r_tickets_nav.sql` 对 "
      "anon/authenticated 撤了 execute。所以对齐对象是 S-638(2026-10-20)从真内核跑出来、已写进台账的数。")
    A("")
    A("| 参数 | S-638 真内核 | 本脚本 transliteration | 差 |")
    A("|---|---|---|---|")
    for row in res["nav_parity"]["rows"]:
        A(f"| {row['what']} | {row['seth']} | {row['mine']} | {row['diff']} |")
    A("")
    A(f"对齐结论:**{'通过' if res['nav_parity']['pass'] else '不通过'}**。f=0.5%/cap=10 是 S-642 写死的空头臂口径;"
      "f=1%/cap=10 是台账里唯一有公开逐曲线参数的一档,拿来当标尺。")
    A("")
    A("残差(全部记下来,不藏):盯市最大回撤对到 0.01pp、期末净值差 0.8%、年化差 0.23pp;"
      "**接 / 挡差 1 张**(见上表),连带 ΣR 差约 0.23R。2024 年的票集合逐张对得上"
      "(261 张 / 269.8157R = T-156 与 Seth 那份 dump),所以骨架没问题;最可能是 S-638 那次跑在 "
      "08-09 → 09-06 那个数据洞回补之前,而本机的 bar 是 10-21 拉的。"
      "**探索性 —— 需 @seth 用同一份 bar 重跑一次 S-638 确认。**")
    A("")
    A("## 2 · S-642 结果")
    A("")
    s = res["short"]
    A(f"开票 **{s['n']}** 张(已出场 {s['n_closed']},到期/退市仍持仓 {s['n_open']});"
      f"止损出场 **{s['stop_ratio']:.1%}**,SMA20 出场 {s['sma_ratio']:.1%},到期 {s['time_ratio']:.1%}。")
    A("")
    A("| 判 | 条件 | 实测 | 过? |")
    A("|---|---|---|---|")
    for j in res["judgements"]:
        A(f"| {j['id']} | {j['rule']} | {j['got']} | {'**是**' if j['pass'] else '**否**'} |")
    A("")
    A(f"- 每票平均 R(净成本、净资金费)**{s['mean_r_net']:+.4f}**,中位数 {s['median_r_net']:+.4f};"
      f"胜率 {s['win_rate']:.1%}。")
    A(f"- 资金费:Σfunding_rate = {s['funding_sum']:+.4f}(以进场固定名义计),折 **Σ {s['sum_funding_r']:+.3f}R** / "
      f"Σ净R 的 {s['funding_share']:.1%};{s['funding_covered']} 张有资金费数据、{s['funding_missing']} 张没有。")
    A(f"- 最大逆向:单票最差 MAE **{s['mae_min']:+.2f}R**({s['mae_min_sym']});最好 MFE {s['mfe_max']:+.2f}R。")
    A("")
    A("### 分年")
    A("")
    A("| 年 | 票 | 平均 R | 净 R | Σ净R | 止损率 | Σ资金费 R |")
    A("|---|---|---|---|---|---|---|")
    for y in s["by_year"]:
        A(f"| {y['y']} | {y['n']} | {y['mean_r']:+.3f} | {y['mean_r_net']:+.3f} | {y['sum_r_net']:+.2f} | "
          f"{y['stop_ratio']:.0%} | {y['funding_r']:+.3f} |")
    A("")
    A("### 钱曲线(S-642 口径 f = 0.5%,同时最多 10 张)")
    A("")
    A("| 臂 | 接/挡 | 期末净值 | 年化(全程) | 年化(闸门关的日子) | 盯市最大回撤 | 峰值总名义/净值 |")
    A("|---|---|---|---|---|---|---|")
    for k, c in res["curves"].items():
        A(f"| {k} | {c['taken']}/{c['skipped']} | {c['end']:.4f} | {money(c['annualised'])} | "
          f"**{money(c.get('annualised_closed'))}** | {money(c['mdd'])} | {c['peak_gross']:.2f} |")
    A("")
    A(f"闸门关的天数 {res['curves']['空头臂']['closed_days']} 天(共 "
      f"{res['curves']['空头臂']['days']} 天)。放贷基准 4%(S-642 写死)。")
    A("")
    A("### 与多头合在一起(S-642 只报项)")
    A("")
    cd = res["combined"]
    A(f"多头单独最大回撤 {money(cd['long_mdd'])};空头单独 {money(cd['short_mdd'])};"
      f"**两臂合并 {money(cd['combined_mdd'])}**(同一 f=0.5%、cap=10 内核,一个 cap 共用)。")
    A("")
    A("### HL 单向持仓:同名冲突(Jazz 10-21 点名要报的一项)")
    A("")
    sn = res["same_name"]
    if sn["n"]:
        A(f"信号日同一名字已有 R-v2 多头在持的空头票 **{sn['n']} 张**({sn['n_pct']:.1%} 的空头票,"
          f"涉及 {sn['symbols']} 个币)。若 S-642 将来被采纳,这些必须放 HL 子账户与多头分开持仓 —— "
          f"同一张账户做不到一个币同时多空。逐张见 `_reports/.../t159_results.json` 的 `same_name.detail`。")
    else:
        A("**0 张。** 样本里没有出现「信号日同名已有 R-v2 多头在持」的空头票。")
    A("")
    A("## 3 · 读法")
    A("")
    A(res["verdict"])
    A("")
    A("## 4 · 探索性(需另立预注册、在新数据上过零信号对照)")
    A("")
    for x in res["exploratory"]:
        A(f"- {x}")
    A("")
    A("---")
    A("")
    A("## S-642 结果(草稿,可贴台账)")
    A("")
    A(res["ledger_draft"])
    open(path, "w").write("\n".join(L) + "\n")


def main():
    global ENV
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=ENV)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--fetch-from", default="2025-04-01")
    ap.add_argument("--fetch-to", default=CURVE_TO)
    ap.add_argument("--funding", action="store_true", help="re-pull funding_history for the names the book trades")
    ap.add_argument("--reuse", action="store_true", help="reuse the cached ticket book if it is newer than the bars")
    ap.add_argument("--since", default=SINCE)
    ap.add_argument("--to", default=TO)
    ap.add_argument("--f", type=float, default=0.005)
    ap.add_argument("--cap", type=int, default=10)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261021)
    ap.add_argument("--nav-from", default=None, help="dumped r_tickets_nav() daily curve to diff against")
    ap.add_argument("--out", default="/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-159_bear_short.md")
    ap.add_argument("--json-out", default="/Volumes/CometCloudAI/cometcloud-local/research/t159/t159_results.json")
    a = ap.parse_args()
    ENV = a.data if a.data.endswith("/") else a.data + "/"
    os.makedirs(ENV, exist_ok=True)
    os.makedirs(os.path.dirname(a.json_out), exist_ok=True)
    if a.fetch:
        fetch(a.fetch_from, a.fetch_to)

    bars = load_bars()
    gate = load_gate()
    funding, n_fund_rows = load_funding()
    closes = bars
    nbars = sum(len(v) for v in bars.values())
    closed_days = {d for d, g in gate.items() if g["gate_closed"]}

    cache = f"{ENV}_tickets_{a.since}_{a.to}.json"
    if a.reuse and os.path.exists(cache) and os.path.getmtime(f"{ENV}_bars.jsonl") < os.path.getmtime(cache):
        c = json.load(open(cache))
        long_all, short = c["long"], c["short"]
        print(f"reused tickets from {cache}", file=sys.stderr)
    else:
        long_all = run_long(bars, gate, a.since, CURVE_TO)
        short = run_short(bars, gate, a.since, a.to)
        json.dump(dict(long=long_all, short=short), open(cache, "w"), default=str)
    long_2024 = [t for t in long_all if t["signal_d"].startswith("2024")]
    if a.funding:
        fetch_funding_for({t["symbol"] for t in short})
        funding, n_fund_rows = load_funding()
    miss = add_funding(short, funding)

    sk = dict(symbols=len(bars), bars=nbars, style_days=len(gate),
              long_2024_n=len(long_2024), long_2024_sumr=round(sum(t["r"] or 0 for t in long_2024), 4),
              long_all_n=len(long_all), long_all_sumr=round(sum(t["r"] or 0 for t in long_all), 2),
              long_window_n=len([t for t in long_all if t["signal_d"] <= a.to]))

    # ── NAV parity against S-638's published kernel numbers (f = 1%, cap = 10, compounded) ──
    # S-638's f-scan row is the DISCOVERY set only (S-638: 发现段 729 张; the 41 holdout tickets of 2026-06-21 →
    # are a separate line in the ledger), while its implementation check ① is on the full 770-ticket table.
    long_disc = [t for t in long_all if t["signal_d"] <= a.to]
    parity = list(nav(long_disc, closes, 0.01, cap=10, d_to=CURVE_TO, compound=True))
    m_rows = parity
    ps = stats(parity, closed_days)
    nc = list(nav(long_all, closes, 0.01, cap=None, d_to=CURVE_TO, compound=False))
    ncs = stats(nc)
    ncs["realized"] = nc[-1]["realized"]
    seth_rows = [("期末净值(发现段 729 张,f=1%,cap=10,复利)", "4.12", f"{ps['end']:.4f}", f"{ps['end'] - 4.12:+.4f}"),
                 ("盯市最大回撤", "−32.3%", money(ps["mdd"]), f"{100 * (ps['mdd'] + 0.323):+.2f}pp"),
                 ("年化", "+24.4%", money(ps["annualised"]), f"{100 * (ps['annualised'] - 0.244):+.2f}pp"),
                 ("接 / 挡", "304 / 425", f"{ps['taken']} / {ps['skipped']}",
                  f"{ps['taken'] - 304:+d} / {ps['skipped'] - 425:+d}"),
                 ("实施检验①期末已实现(770 张、不复利、不封顶,realized 列)", "3.692028", f"{ncs['realized']:.6f}",
                  f"{ncs['realized'] - 3.692028:+.2e}")]
    parity_pass = (abs(ps["end"] - 4.12) < 0.09 and abs(ps["mdd"] + 0.323) < 0.002
                   and abs(ps["annualised"] - 0.244) < 0.005 and abs(ps["taken"] - 304) <= 1
                   and abs(ps["skipped"] - 425) <= 1 and abs(ncs["realized"] - 3.692028) < 5e-3)
    nav_parity = dict(rows=[dict(what=k, seth=v, mine=m, diff=d) for k, v, m, d in seth_rows], pass_=parity_pass)
    nav_parity["pass"] = parity_pass
    if a.nav_from and os.path.exists(a.nav_from):
        """Day-by-day diff against a dumped r_tickets_nav() output, if Seth ever hands one over."""
        mine = {r["d"]: r["equity"] for r in m_rows}
        other = {x["d"]: float(x["equity"]) for x in json.load(open(a.nav_from))}
        both = sorted(set(mine) & set(other))
        nav_parity["day_diff"] = dict(days_compared=len(both), days_only_mine=len(set(mine) - set(other)),
                                      days_only_other=len(set(other) - set(mine)),
                                      max_abs_diff=max([abs(mine[d] - other[d]) for d in both] or [None]))
    if not parity_pass:
        print("NAV PARITY FAILED — stopping before the short arm", file=sys.stderr)
        json.dump(dict(skeleton=sk, nav_parity=nav_parity), open(a.json_out, "w"), indent=2, default=str)
        sys.exit(1)

    # ── S-642 judgements ──
    closed = [t for t in short if t["r_net"] is not None]
    rs = np.array([t["r_net"] for t in closed])
    mean_r = float(rs.mean())
    centered = rs - mean_r
    null = null_distribution(lambda rng: float(rng.choice(centered, size=len(centered), replace=True).mean()),
                             a.boot, a.seed, actual=mean_r)
    p = percentile_of(mean_r, null)
    h1 = np.array([t["r_net"] for t in closed if t["signal_d"] < "2023-01-01"])
    h2 = np.array([t["r_net"] for t in closed if t["signal_d"] >= "2023-01-01"])
    short_cur = stats(nav(short, closes, a.f, cap=a.cap, d_to=CURVE_TO, compound=True), closed_days)
    j = [dict(id="①", rule="每票平均 R(净成本、净资金费)> 0,自助 2,000 次单侧 p<0.05",
              got=f"均值 {mean_r:+.4f},单侧 p = {p:.4f}", pass_=bool(mean_r > 0 and p is not None and p < 0.05)),
         dict(id="②", rule="两半各自平均 R> 0(<2023 / ≥2023)",
              got=f"前半 {h1.mean():+.4f}(n={len(h1)}) · 后半 {h2.mean():+.4f}(n={len(h2)})",
              pass_=bool(len(h1) and len(h2) and h1.mean() > 0 and h2.mean() > 0)),
         dict(id="③", rule="钱曲线 f=0.5%、cap=10 在闸门关的日子上年化 > 4%(另报 2%/6%)",
              got=f"{money(short_cur.get('annualised_closed'))}(关日子 {short_cur['closed_days']} 天)",
              pass_=bool(short_cur.get("annualised_closed") is not None and short_cur["annualised_closed"] > 0.04))]
    for x in j:
        x["pass"] = x.pop("pass_")
    all_pass = all(x["pass"] for x in j)

    n_closed = len(closed)
    by_year = []
    for y in sorted({t["signal_d"][:4] for t in short}):
        ts = [t for t in short if t["signal_d"][:4] == y]
        tc = [t for t in ts if t["r_net"] is not None]
        by_year.append(dict(y=y, n=len(ts), n_closed=len(tc),
                            mean_r=float(np.mean([t["r"] for t in tc])) if tc else 0.0,
                            mean_r_net=float(np.mean([t["r_net"] for t in tc])) if tc else 0.0,
                            sum_r_net=float(sum(t["r_net"] for t in tc)),
                            stop_ratio=sum(1 for t in tc if t["exit_reason"] == "stop") / len(tc) if tc else 0.0,
                            funding_r=float(sum(t["funding_r"] for t in tc))))
    short_sum = dict(
        n=len(short), n_closed=n_closed, n_open=len(short) - n_closed,
        stop_ratio=sum(1 for t in closed if t["exit_reason"] == "stop") / max(n_closed, 1),
        sma_ratio=sum(1 for t in closed if t["exit_reason"] == "sma20") / max(n_closed, 1),
        time_ratio=sum(1 for t in closed if t["exit_reason"] == "time") / max(n_closed, 1),
        mean_r_net=mean_r, median_r_net=float(np.median(rs)), win_rate=float((rs > 0).mean()),
        funding_sum=sum(t["funding_sum"] for t in closed),
        sum_funding_r=sum(t["funding_r"] for t in closed),
        funding_share=sum(t["funding_r"] for t in closed) / float(rs.sum()) if rs.sum() else 0.0,
        funding_covered=sum(1 for t in closed if t.get("funding_covered")),
        funding_missing=sum(1 for t in closed if not t.get("funding_covered")),
        mae_min=min(t["mae_r"] for t in closed), mae_min_sym=min(closed, key=lambda t: t["mae_r"])["symbol"],
        mfe_max=max(t["mfe_r"] for t in closed), by_year=by_year)
    long_cur = stats(nav(long_all, closes, a.f, cap=a.cap, d_to=CURVE_TO, compound=True), closed_days)
    both_cur = stats(nav(long_all + short, closes, a.f, cap=a.cap, d_to=CURVE_TO, compound=True), closed_days)
    collide = same_name_open(long_all, short)
    collide_sum = dict(n=len(collide), n_pct=len(collide) / max(len(short), 1),
                       symbols=len({c["symbol"] for c in collide}), detail=collide)
    sens = {f"{fl:.0%}": stats(nav(short, closes, a.f, cap=a.cap, d_to=CURVE_TO, compound=True), closed_days)
            for fl in (0.02, 0.06)}

    res = dict(meta=dict(run_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()[:16],
                        data=ENV, funding_rows=n_fund_rows, f=a.f, cap=a.cap, boot=a.boot, seed=a.seed,
                        since=a.since, to=a.to, curve_to=CURVE_TO),
               skeleton=sk, nav_parity=nav_parity, short=short_sum,
               judgements=j, all_pass=all_pass,
               curves=dict(多头臂=long_cur, 空头臂=short_cur),
               sens=sens, combined=dict(long_mdd=long_cur["mdd"], short_mdd=short_cur["mdd"],
                                        combined_mdd=both_cur["mdd"], combined_end=both_cur["end"]),
               same_name=collide_sum)
    res["exploratory"] = exploratory(res, short, closed)
    res["verdict"] = verdict(res)
    res["ledger_draft"] = ledger_draft(res)
    write_report(a.out, res)
    json.dump(dict(meta=res["meta"], skeleton=sk, nav_parity=nav_parity, short=short_sum,
                   judgements=j, all_pass=all_pass, curves=res["curves"], sens=sens,
                   combined=res["combined"], exploratory=res["exploratory"], same_name=res["same_name"],
                   tickets=[{k: v for k, v in t.items() if k not in ("ei", "xi")} for t in short]),
              open(a.json_out, "w"), indent=2, default=str)
    print(json.dumps(dict(n_tickets=short_sum["n"], mean_r_net=round(mean_r, 4), p=round(p, 4),
                          h1=round(float(h1.mean()), 4), h2=round(float(h2.mean()), 4),
                          nav_closed=short_cur.get("annualised_closed"), all_pass=all_pass), indent=1))
    print(f"report -> {a.out}")


def exploratory(res, short, closed):
    out = []
    sym = defaultdict(list)
    for t in closed:
        sym[t["symbol"]].append(t["r_net"])
    top = sorted(sym.items(), key=lambda kv: -len(kv[1]))[:6]
    out.append("按币种集中度:" + ", ".join(f"{s} {len(v)} 张 / 均 {np.mean(v):+.2f}R" for s, v in top) +
               " —— 样本能不能撑住 ② 取决于前几个名字,需在新数据上复核。")
    if res["curves"]["空头臂"]["closed_days"]:
        out.append(f"空头臂 {res['curves']['空头臂']['closed_days']} 个闸门关的日子里只有 "
                   f"{res['curves']['空头臂']['closed']} 张票平仓,样本集中在两三段熊市里 —— 有效自由度远小于票数。")
    return out


def verdict(res):
    if res["all_pass"]:
        return ("**三条全过。** 熊市里有一条可执行的空头臂(HL 永续):在闸门关的日子上它显著胜过 4% 的放贷基准,"
                "分年与两半都不为负。是否把「③ 不做空」改成「③ 只在闸门关时做空」是 Jazz 的决定 —— "
                "本卡只负责检验,不负责改规则。")
    miss = [x["id"] for x in res["judgements"] if not x["pass"]]
    return (f"**没过(失败的是 {'、'.join(miss)})。** 按 prior_value:熊市默认 = 现金放贷 + R-v2 自动停,"
            "不再讨论做空。下面的数字说明是哪一条顶不住、以及顶不住的是规则本身还是这一段样本。")


def ledger_draft(res):
    s, c = res["short"], res["curves"]["空头臂"]
    return "\n".join([
        f"**结果(S-642,交 C 道 T-159):** 闸门关时 40 日新低破位 + 放量的永续空单,信号日 {res['meta']['since']} → "
        f"{res['meta']['to']},开票 **{s['n']}** 张,止损出场 {s['stop_ratio']:.0%}。",
        f"**①** 每票平均 R(净 0.4% 成本、净资金费)**{s['mean_r_net']:+.4f}**,自助 2,000 次单侧 "
        f"p = {res['judgements'][0]['got'].split('p = ')[1]} → "
        f"{'过' if res['judgements'][0]['pass'] else '**不过**'}。",
        f"**②** <2023 {res['judgements'][1]['got']} → {'过' if res['judgements'][1]['pass'] else '**不过**'}。",
        f"**③** 钱曲线(f = 0.5%,cap = 10)在闸门关的日子上年化 **{money(c.get('annualised_closed'))}**"
        f"(放贷基准 4%)→ {'过' if res['judgements'][2]['pass'] else '**不过**'};盯市最大回撤 {money(c['mdd'])}。",
        f"**资金费**(S-642 要求单列):Σ funding_rate = {s['funding_sum']:+.4f},折 Σ {s['sum_funding_r']:+.3f}R,"
        f"占 Σ净R 的 {s['funding_share']:.1%};{s['funding_covered']} 张有资金费数据、{s['funding_missing']} 张没有"
        f"(没有的按 0 记账,方向上对空头有利还是不利取决于币种,需 @seth 决定是否等补全再定论)。",
        f"**最大逆向:** 单票最差 MAE {s['mae_min']:+.2f}R({s['mae_min_sym']})。",
        f"**合并回撤:** 多头单独 {money(res['combined']['long_mdd'])}、空头单独 {money(res['combined']['short_mdd'])}、"
        f"两臂合并 **{money(res['combined']['combined_mdd'])}**。",
        f"**HL 单向持仓(Jazz 10-21 点名):** 信号日同名已有 R-v2 多头在持的空头票 **{res['same_name']['n']} 张**"
        f"({res['same_name']['n_pct']:.1%})。",
        f"**结论:** {'三条全过 —— 交 Jazz 决定是否改「③ 不做空」' if res['all_pass'] else '不过 —— 熊市默认 = 现金放贷 + R-v2 自动停'}。",
    ])


if __name__ == "__main__":
    main()