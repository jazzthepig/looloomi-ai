"""T-156 §Seth-1020l: replay BOTH kernels of the R-v2 ticket book in python and diff them, ticket by ticket.

Why this file exists next to t156_rv2_forward_vs_replay.py: that one reconciles the forward ledger
(r_tickets_paper) against a replay.  It could not answer "why 266 and not 261", because the 266 run
never left a per-ticket dump and read-only access cannot run SQL.  Seth then dropped the 261-ticket
dump (research/t156/seth_2024_tickets_continuous.json), so this file re-implements both kernels from
their SQL text and diffs them against that dump:

  V1  docs/research/r_v2_tickets.sql              one-shot; exits at `least(rn+120, n)` and marks the
                                                 tail `still_open` (exit_d = null) when the symbol ran
                                                 out of bars first
  V2  migrations/2026-10-20_r_tickets_paper.sql   r_tickets_scan day-by-day state machine; adds
                                                 rule 3b (`no_data`: a symbol that stopped printing
                                                 bars is closed at its last close after 10 days)

Nothing here is a new rule; both sides are transliterations of the SQL above.  Read-only DB access.

  python3 docs/research/t156_rv2_replay_twokernels.py --since 2020-03-01 --to 2024-12-31 \
      --seth research/t156/seth_2024_tickets_continuous.json
"""
import json, os, sys, string, datetime, argparse, urllib.request
from collections import defaultdict

EXCL = {"USDC", "BTCDOM", "DEFI"}
ENV = os.environ.get("T156_DATA", "")  # dir holding cached _bars*.jsonl / _style.json


def _rest(path, lo, hi):
    u = os.environ["SUPABASE_URL"]; k = os.environ["SUPABASE_KEY"]
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
        out += rows; off += 1000
        if len(rows) < 1000:
            break
    return out


def fetch(lo, hi):
    """Pull ohlcv_daily + style_index_pit_daily into the cache dir (PostgREST caps a page at 1000 rows)."""
    B = f"source=eq.binance_hist&trade_date=gte.{lo}&trade_date=lte.{hi}"
    syms = set()
    for ch in string.ascii_uppercase + string.digits:
        for row in _page_all(f"ohlcv_daily?select=symbol&symbol=like.{ch}*&{B}&order=symbol.asc", 120):
            syms.add(row["symbol"])
    with open(f"{ENV}_bars.jsonl", "w") as f:
        n = 0
        for s in sorted(syms):
            rows = _page_all(f"ohlcv_daily?select=trade_date,open,high,low,close,volume&{B}"
                             f"&symbol=eq.{s}&order=trade_date.asc", 8)
            for x in rows:
                x["symbol"] = s
            f.write(json.dumps(rows) + "\n"); n += len(rows)
    st = _page_all("style_index_pit_daily?select=d,ret&style=eq.majors&weighting=eq.cap&order=d.asc", 400)
    json.dump(st, open(f"{ENV}_style.json", "w"))
    print(f"fetched {n} bars over {len(syms)} symbols, {len(st)} style rows -> {ENV}", file=sys.stderr)


def load_bars():
    by = defaultdict(list)
    for fn in (f"{ENV}_bars_early.jsonl", f"{ENV}_bars.jsonl"):
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
    c = [r[4] for r in rows]; h = [r[2] for r in rows]; l = [r[3] for r in rows]; dv = [r[5] for r in rows]
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


def load_gate():
    rows = [x for x in json.load(open(f"{ENV}_style.json"))
            if x["ret"] is not None and x["ret"] > -0.95]
    rows.sort(key=lambda x: x["d"])
    lvl, cur = [], 1.0
    for x in rows:
        cur *= (1.0 + x["ret"]); lvl.append(cur)
    return {x["d"]: bool(min(i + 1, 200) < 200 or lvl[i] > win(lvl, i, 0, 199))
            for i, x in enumerate(rows)}


def sig_at(a, i, gate_open):
    """The `ev` / `_rt_bars.sig` predicate, identical in both kernels."""
    if i < 220 or a["atr14"][i] is None or a["atr14"][i] <= 0: return False
    if a["adv30"][i] is None or a["adv30"][i] < 5e6: return False
    if a["mindd120"][i] is None or a["mindd120"][i] > 0.5: return False
    hh, ll = a["hh40"][i], a["ll40"][i]
    if hh is None or ll is None or hh == 0 or (hh - ll) / hh > 0.40: return False
    if not (a["c"][i] > hh): return False
    if a["sma200"][i] is None or not (a["c"][i] > a["sma200"][i]): return False
    if a["adv40p"][i] is None or a["dv"][i] < 2 * a["adv40p"][i]: return False
    return gate_open


def run_v1(bars, gate, d_from, d_to):
    """docs/research/r_v2_tickets.sql, verbatim semantics."""
    tr = defaultdict(list)
    for sym, rows in bars.items():
        a = indicators(rows); n = len(rows)
        for i in range(220, n):
            d = a["d"][i]
            if not (d_from <= d <= d_to) or not sig_at(a, i, gate.get(d, True)): continue
            ei = i + 1
            if ei >= n: continue
            entry = a["o"][ei]; stop = entry - 2.5 * a["atr14"][i]
            if not (entry > stop): continue
            k = None
            for j in range(ei, min(i + 120, n - 1) + 1):
                if a["l"][j] <= stop or a["c"][j] < a["sma20"][j]:
                    k = j; break
            if k is None:
                xi = min(i + 120, n - 1); xp = a["c"][xi]; still = (i + 120 > n - 1)
            elif a["l"][k] <= stop:
                xi = k; xp = a["o"][k] if (k > ei and a["o"][k] <= stop) else stop; still = False
            elif k + 1 <= n - 1:
                xi = k + 1; xp = a["o"][k + 1]; still = False
            else:
                xi = k; xp = a["c"][k]; still = (k + 1 > n - 1)
            t = dict(symbol=sym, signal_d=d, entry_d=a["d"][ei], exit_d=None if still else a["d"][xi],
                     entry_px=entry, stop_px=stop, exit_px=None if still else xp,
                     ei=ei, xi=xi, still=still)
            t["r"] = None if still else ((xp - entry) / (entry - stop) - 0.004 * entry / (entry - stop))
            tr[sym].append(t)
    res = []
    for sym, ts in tr.items():
        ts.sort(key=lambda t: t["ei"]); cur = ts[0]; res.append(cur)
        while True:
            nxt = [t for t in ts if t["ei"] > cur["xi"]]
            if not nxt: break
            cur = nxt[0]; res.append(cur)
    res.sort(key=lambda t: (t["signal_d"], t["symbol"]))
    return res


def run_v2(bars, gate, v_from, p_to):
    """migrations/2026-10-20_r_tickets_paper.sql `r_tickets_scan`, plpgsql -> python."""
    inds = {s: indicators(r) for s, r in bars.items()}
    idx = {s: {r[k][0]: k for k in range(len(r))} for s, r in bars.items()}
    live, tickets, stopped = {}, [], None
    d = v_from
    while d <= p_to:
        ds = d.isoformat()
        n_bars = sum(1 for s in bars if ds in idx[s])
        n_prev = sum(1 for s in bars if (d - datetime.timedelta(days=1)).isoformat() in idx[s])
        if n_bars < max(20, 0.8 * n_prev):
            stopped = f"only {n_bars} bars on {ds} (previous day {n_prev})"; break
        if ds not in gate and ds > "2020-07-18":
            stopped = f"majors index missing on {ds}"; break
        for s, t in list(live.items()):                                    # 1. SMA20 flag fills at today's open
            if t["status"] == "open" and t["exit_flag"] and ds in idx[s]:
                t.update(status="closed", exit_d=ds, exit_reason="sma20", exit_px=inds[s]["o"][idx[s][ds]])
                _book(t); del live[s]
        for s, t in list(live.items()):                                    # 2. pending fills at today's open
            if t["status"] == "pending" and ds in idx[s]:
                o = inds[s]["o"][idx[s][ds]]
                if o - 2.5 * t["atr14"] > 0:
                    t.update(status="open", entry_d=ds, entry_px=o, stop_px=o - 2.5 * t["atr14"],
                             exit_flag=False, bars_held=0)
                else:
                    t.update(status="void", entry_d=ds, entry_px=o, stop_px=o - 2.5 * t["atr14"])
                    del live[s]
        for s, t in list(live.items()):                                    # 3. stop > SMA20 flag > time
            if t["status"] != "open" or t["exit_flag"] or ds not in idx[s]: continue
            i = idx[s][ds]; a = inds[s]
            t["bars_held"] += 1
            if a["l"][i] <= t["stop_px"]:
                px = a["o"][i] if (ds > t["entry_d"] and a["o"][i] <= t["stop_px"]) else t["stop_px"]
                t.update(status="closed", exit_d=ds, exit_reason="stop", exit_px=px)
                _book(t); del live[s]; continue
            if a["c"][i] < a["sma20"][i]:
                t["exit_flag"] = True
            if t["bars_held"] >= 120:
                t.update(status="closed", exit_d=ds, exit_reason="time", exit_px=a["c"][i])
                _book(t); del live[s]
        for s, t in list(live.items()):                                    # 3b. symbol stopped printing bars
            if t["status"] != "open": continue
            prior = [x for x in idx[s] if x <= ds]
            if prior and prior[-1] < (d - datetime.timedelta(days=9)).isoformat():
                t.update(status="closed", exit_d=prior[-1], exit_reason="no_data",
                         exit_px=inds[s]["c"][idx[s][prior[-1]]])
                _book(t); del live[s]
        for s in bars:                                                     # 4. today's signals
            if ds not in idx[s] or s in live: continue
            i = idx[s][ds]
            if not sig_at(inds[s], i, gate.get(ds, True)): continue
            t = dict(symbol=s, signal_d=ds, atr14=inds[s]["atr14"][i], status="pending",
                     gate_open=gate.get(ds, True), entry_d=None, entry_px=None, stop_px=None,
                     exit_flag=False, bars_held=0, exit_d=None, exit_px=None, exit_reason=None, r=None)
            tickets.append(t); live[s] = t
        d += datetime.timedelta(days=1)
    return tickets, live, stopped


def _book(t):
    if t.get("exit_px") is not None and t.get("entry_px") and t["entry_px"] != t["stop_px"]:
        t["r"] = ((t["exit_px"] - t["entry_px"]) / (t["entry_px"] - t["stop_px"])
                  - 0.004 * t["entry_px"] / (t["entry_px"] - t["stop_px"]))


def reconcile(bars, gate, d_from, d_to, year, seth_path=None):
    v1 = run_v1(bars, gate, d_from, d_to)
    v2, live, stopped = run_v2(bars, gate, datetime.date.fromisoformat(d_from),
                               datetime.date.fromisoformat(d_to))
    key = lambda t: (t["symbol"], t["signal_d"])
    A, B = {key(t): t for t in v1}, {key(t): t for t in v2}
    Ay = {k: v for k, v in A.items() if v["signal_d"].startswith(year)}
    By = {k: v for k, v in B.items() if v["signal_d"].startswith(year)}
    res = {"since": d_from, "to": d_to, "symbols": len(bars), "year": year,
           "scan_stopped": stopped, "tickets_still_live_at_end": len(live),
           "all_range": {"v1_n": len(A), "v2_n": len(B),
                         "only_v1": len(set(A) - set(B)), "only_v2": len(set(B) - set(A)),
                         "exit_d_diff": len([k for k in set(A) & set(B) if A[k]["exit_d"] != B[k]["exit_d"]])},
           f"v1_{year}": {"n": len(Ay), "sum_r": round(sum(t["r"] or 0 for t in Ay.values()), 4)},
           f"v2_{year}": {"n": len(By), "sum_r": round(sum(t["r"] or 0 for t in By.values()), 4)},
           "v1_vs_v2": {"only_v1": sorted(set(Ay) - set(By)), "only_v2": sorted(set(By) - set(Ay)),
                        "exit_d_diff": [], "r_diff_gt_1e-9": []},
           "no_data_tickets": sorted([t["symbol"], t["signal_d"], t["exit_d"], round(t["r"], 4)]
                                     for t in By.values() if t["exit_reason"] == "no_data"),
           "v1_still_open": sorted([t["symbol"], t["signal_d"]] for t in Ay.values() if t["still"])}
    for k in sorted(set(Ay) & set(By)):
        if Ay[k]["exit_d"] != By[k]["exit_d"]:
            res["v1_vs_v2"]["exit_d_diff"].append(
                {"symbol": k[0], "signal_d": k[1], "v1_exit_d": Ay[k]["exit_d"], "v2_exit_d": By[k]["exit_d"],
                 "v1_still_open": Ay[k]["still"], "v2_exit_reason": By[k]["exit_reason"],
                 "v1_r": Ay[k]["r"], "v2_r": By[k]["r"]})
        if Ay[k]["r"] is not None and By[k]["r"] is not None and abs(Ay[k]["r"] - By[k]["r"]) > 1e-9:
            res["v1_vs_v2"]["r_diff_gt_1e-9"].append([k[0], k[1]])
    if seth_path and os.path.exists(seth_path):
        s = json.load(open(seth_path))
        C = {(t[0], t[1]): {"exit_d": t[2], "r": t[3]} for t in s["tickets"]}
        res["seth"] = {"n": s.get("n"), "sum_r": s.get("sum_r"),
                       "v2_tickets_not_in_seth": sorted(set(By) - set(C)),
                       "seth_tickets_not_in_v2": sorted(set(C) - set(By)),
                       "exit_d_diff": sorted([(k[0], k[1]) for k in set(By) & set(C)
                                              if By[k]["exit_d"] != C[k]["exit_d"]]),
                       "r_diff_gt_1e-4": sorted([(k[0], k[1]) for k in set(By) & set(C)
                                                 if By[k]["r"] is not None and C[k]["r"] is not None
                                                 and abs(By[k]["r"] - C[k]["r"]) > 1e-4]),
                       "v2_sum_r_minus_seth": round(sum(t["r"] or 0 for t in By.values())
                                                    - sum(t["r"] or 0 for t in C.values()), 4),
                       "v1_sum_r_minus_seth": round(sum(t["r"] or 0 for t in Ay.values())
                                                    - sum(t["r"] or 0 for t in C.values()), 4)}
    return res


def main():
    global ENV
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="2020-03-01", help="replay start = the forward ledger's first scanned day")
    ap.add_argument("--to", default="2024-12-31")
    ap.add_argument("--year", default="2024", help="year the report focuses on")
    ap.add_argument("--data", default=os.environ.get("T156_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t156/"),
                    help="cache dir for _bars*.jsonl / _style.json")
    ap.add_argument("--fetch", action="store_true", help="re-pull ohlcv_daily + style from the DB first")
    ap.add_argument("--fetch-from", default="2018-01-01")
    ap.add_argument("--fetch-to", default="2025-04-30")
    ap.add_argument("--seth", default=None, help="seth_<tickets>.json dump to diff against")
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()
    ENV = a.data if a.data.endswith("/") else a.data + "/"
    os.makedirs(ENV, exist_ok=True)
    if a.fetch:
        fetch(a.fetch_from, a.fetch_to)
    res = reconcile(load_bars(), load_gate(), a.since, a.to, a.year, a.seth)
    print(json.dumps(res, indent=2, default=str))
    if a.json_out:
        json.dump(res, open(a.json_out, "w"), indent=2, default=str)


if __name__ == "__main__":
    main()