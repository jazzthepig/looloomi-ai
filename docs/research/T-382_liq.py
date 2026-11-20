#!/usr/bin/env python3
"""T-382 (3) liquidation volume, SAME-CALIBER measurement.

Both calibers are measured over the same wall-clock window:
  caliber A -- OKX WS  liquidation-orders, instType=SWAP (all families)
  caliber B -- OKX WS  liquidation-orders, instType=SWAP + instFamily=BTC-USDT
  caliber C -- OKX REST /api/v5/public/liquidation-orders?instType=SWAP&state=filled
               &uly=BTC-USDT (polled every 15s, deduplicated by fill key)

Everything here is an EXTRAPOLATION from a short window, NOT a lower bound on the
daily count: the window is a quiet-hour sample, the REST endpoint is a
near-end snapshot (successive polls overlap and are deduplicated), and neither
endpoint covers other venues.

2026-11-15 rework (Seth §Seth-1114f ③): v1 multiplied the WS fill count by 288
without filtering on ts.  OKX pushes a BACKLOG on connect (v1 saw 80 fills whose
ts spanned 23.3 h), so "fills seen during the window" is NOT "fills that happened
during the window".  v2 therefore counts ONLY fills whose own ts falls inside
[window_start, window_end] and extrapolates from that count.  The family
subscription is also checked for being honoured (v1: the server ignored
instFamily and pushed 18 non-BTC contracts).

Writes docs/research/T-382_liq_results_v2.json
"""
import asyncio
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "T-382_liq_results_v2.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
WINDOW_S = int(os.environ.get("T382_WINDOW_S", "300"))
POLL_S = 15

REST_URL = ("https://www.okx.com/api/v5/public/liquidation-orders"
            "?instType=SWAP&state=filled&uly=BTC-USDT&limit=100")
WS_URL = "wss://ws.okx.com/ws/v5/public"


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(3_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000).decode("utf-8", "replace")
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def rest_poller(stop_at, res):
    """Poll the REST snapshot every POLL_S; keep the union of distinct fills."""
    seen = {}
    polls = 0
    codes = []
    rows_per_poll = []
    while time.time() < stop_at:
        st, body = http_get(REST_URL)
        polls += 1
        codes.append(st)
        if st == 200:
            try:
                j = json.loads(body)
                rows_per_poll.append(len(j.get("data") or []))
                for item in (j.get("data") or []):
                    inst = item.get("instId", "?")
                    for d in (item.get("details") or []):
                        key = "|".join([str(inst), str(d.get("ts")), str(d.get("bkPx")),
                                        str(d.get("sz")), str(d.get("side")),
                                        str(d.get("posSide"))])
                        seen.setdefault(key, {
                            "ts": d.get("ts"), "instId": inst, "bkPx": d.get("bkPx"),
                            "sz": d.get("sz"), "side": d.get("side"),
                            "posSide": d.get("posSide"), "bkLoss": d.get("bkLoss")})
            except Exception as e:
                res["rest_parse_error"] = "%s: %s" % (type(e).__name__, e)
        time.sleep(POLL_S)
    res["rest"] = {"url": REST_URL, "n_polls": polls, "status_codes": codes[:5],
                   "rows_per_poll": rows_per_poll,
                   "max_rows_per_poll": max(rows_per_poll) if rows_per_poll else 0,
                   "n_distinct_fills": len(seen),
                   "fills": sorted(seen.values(), key=lambda x: str(x.get("ts")))}


async def ws_collect(sub, seconds):
    """Subscribe and hold the connection for the whole window.

    OKX closes an idle connection with 4004 ("No data received in 30s") unless the
    client sends the literal string "ping"; we therefore ping every 15s and
    reconnect if the socket drops anyway.
    """
    import websockets
    frames, details, errs = [], [], []
    deadline = time.time() + seconds
    n_conn = 0
    while time.time() < deadline:
        n_conn += 1
        try:
            async with websockets.connect(WS_URL, open_timeout=20, max_size=None,
                                          ping_interval=None) as s:
                await s.send(json.dumps({"op": "subscribe", "args": [sub]}))

                async def pinger():
                    while True:
                        await asyncio.sleep(15)
                        try:
                            await s.send("ping")
                        except Exception:
                            return

                pt = asyncio.ensure_future(pinger())
                try:
                    while time.time() < deadline:
                        left = deadline - time.time()
                        if left <= 0:
                            break
                        try:
                            raw = await asyncio.wait_for(s.recv(), timeout=min(left, 10))
                        except asyncio.TimeoutError:
                            continue
                        raw = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
                        frames.append(raw)
                        if '"channel":"liquidation-orders"' in raw:
                            try:
                                j = json.loads(raw)
                                for item in (j.get("data") or []):
                                    for d in (item.get("details") or []):
                                        details.append({
                                            "instId": item.get("instId"), "ts": d.get("ts"),
                                            "bkPx": d.get("bkPx"), "sz": d.get("sz"),
                                            "side": d.get("side"),
                                            "posSide": d.get("posSide")})
                            except Exception:
                                pass
                finally:
                    pt.cancel()
        except Exception as e:
            errs.append("%s: %s" % (type(e).__name__, e))
            await asyncio.sleep(1)
    return frames, details, errs, n_conn


def main():
    start = datetime.now(timezone.utc)
    t_end = time.time() + WINDOW_S
    t_lo = int(start.timestamp() * 1000)
    t_hi = int(t_end * 1000)
    res = {"window_s": WINDOW_S, "poll_s": POLL_S,
           "start_utc": start.isoformat(),
           "end_utc": datetime.fromtimestamp(t_end, timezone.utc).isoformat(),
           "note": "extrapolation from a short quiet-window sample; NOT a lower bound "
                   "on the daily count and NOT other venues"}
    th = threading.Thread(target=rest_poller, args=(t_end, res), daemon=True)
    th.start()

    async def run_ws():
        async def one(label, sub):
            frames, details, errs, n_conn = await ws_collect(sub, WINDOW_S)
            uniq = {}
            for d in details:
                uniq.setdefault("|".join(str(d.get(k)) for k in
                                         ("instId", "ts", "bkPx", "sz", "side", "posSide")), d)
            ts_list = sorted(int(d["ts"]) for d in uniq.values() if d.get("ts"))
            insts = {}
            for d in uniq.values():
                insts[d.get("instId")] = insts.get(d.get("instId"), 0) + 1
            # only fills that HAPPENED inside the window count as the window rate
            in_win = [d for d in uniq.values()
                      if d.get("ts") and t_lo <= int(d["ts"]) <= t_hi]
            non_family = sorted(str(i) for i in insts
                                if not str(i).startswith("BTC-USDT"))
            span_h = ((ts_list[-1] - ts_list[0]) / 3.6e6) if len(ts_list) > 1 else 0.0
            return label, {"subscribe": sub, "n_frames": len(frames),
                           "n_detail_rows": len(details),
                           "n_distinct_fills": len(uniq),
                           "n_fills_inside_window": len(in_win),
                           "n_fills_outside_window": len(uniq) - len(in_win),
                           "n_connections": n_conn,
                           "ts_min": ts_list[0] if ts_list else None,
                           "ts_max": ts_list[-1] if ts_list else None,
                           "ts_span_hours": round(span_h, 3),
                           "n_instIds": len(insts),
                           "n_instIds_outside_BTC-USDT": len(non_family),
                           "instIds_outside_BTC-USDT": non_family[:20],
                           "instId_counts": dict(sorted(insts.items(),
                                                       key=lambda kv: -kv[1])[:12]),
                           "first_frame": frames[0][:300] if frames else None,
                           "last_frame": frames[-1][:300] if frames else None,
                           "in_window_fills_sample": [
                               {"instId": d.get("instId"), "ts": d.get("ts")}
                               for d in sorted(in_win, key=lambda z: str(z.get("ts")))][:20],
                           "errors": errs[:5]}

        pairs = await asyncio.gather(
            one("ws_all_swap", {"channel": "liquidation-orders", "instType": "SWAP"}),
            one("ws_btc_usdt_family", {"channel": "liquidation-orders",
                                       "instType": "SWAP", "instFamily": "BTC-USDT"}))
        return dict(pairs)

    res["ws"] = asyncio.run(run_ws())
    th.join(timeout=WINDOW_S + 60)
    res["end_utc_actual"] = datetime.now(timezone.utc).isoformat()

    # --- same-caliber extrapolation -------------------------------------
    # The window is a quiet-hours sample. Counts are scaled by 86400/WINDOW_S
    # and are labelled an extrapolation, never a floor: the sample window is
    # NOT representative of the active part of the day, and one venue is not
    # the market. Each caliber is reported separately so the two numbers are
    # never subtracted from each other.
    #
    # v2 (2026-11-15): the count that is scaled is the count of fills whose OWN
    # ts is inside the window.  v1 scaled the number of fills merely SEEN
    # during the connection, which on OKX includes a connect-time backlog
    # (ts span 23.3 h) -- that is not a window rate.
    scale = 86400.0 / WINDOW_S
    extrap = {"scale_per_day": round(scale, 4),
              "window_s": WINDOW_S,
              "window_start_ms": t_lo, "window_end_ms": t_hi,
              "calibers": {}}
    r = res.get("rest", {})
    fills = r.get("fills", [])
    in_win = [f for f in fills if t_lo <= int(f.get("ts", 0)) <= t_hi]
    n_rest_in = len(in_win)
    extrap["calibers"]["okx_rest_uly_BTC-USDT"] = {
        "n_distinct_fills_seen": len(fills),
        "n_fills_inside_window": n_rest_in,
        "n_fills_outside_window": len(fills) - n_rest_in,
        "rows_per_poll_max": r.get("max_rows_per_poll"),
        "extrapolated_per_day": round(n_rest_in * scale, 1),
        "poisson_rel_err": (round(1.0 / (n_rest_in ** 0.5), 3) if n_rest_in else None),
        "usable_as_daily_rate": bool(n_rest_in >= 30),
        "caliber": "one instrument family (BTC-USDT), 15s poll, snapshot endpoint",
    }
    for label, v in res.get("ws", {}).items():
        n_in = v.get("n_fills_inside_window", 0)
        extrap["calibers"]["okx_ws_" + label] = {
            "n_distinct_fills_seen": v.get("n_distinct_fills"),
            "n_fills_inside_window": n_in,
            "n_fills_outside_window": v.get("n_fills_outside_window"),
            "ts_min": v.get("ts_min"),
            "ts_max": v.get("ts_max"),
            "ts_span_hours": v.get("ts_span_hours"),
            "n_instIds": v.get("n_instIds"),
            "n_instIds_outside_BTC-USDT": v.get("n_instIds_outside_BTC-USDT"),
            "extrapolated_per_day": round(n_in * scale, 1),
            "poisson_rel_err": (round(1.0 / (n_in ** 0.5), 3) if n_in else None),
            "usable_as_daily_rate": bool(n_in >= 30),
            "caliber": ("push, all SWAP families" if label == "ws_all_swap"
                        else "push, server-answered instFamily=BTC-USDT"),
        }
    extrap["caveat"] = (
        "quiet-hours sample scaled linearly; NOT a lower bound (the active part "
        "of the day is not represented), NOT a day total, NOT the market, "
        "and NOT a promise of any order size")
    res["extrapolation"] = extrap

    # --- what this run can and cannot say ---------------------------------
    ws_all = res.get("ws", {}).get("ws_all_swap", {})
    ws_fam = res.get("ws", {}).get("ws_btc_usdt_family", {})
    same_set = (sorted(ws_all.get("instIds_outside_BTC-USDT") or []) ==
                sorted(ws_fam.get("instIds_outside_BTC-USDT") or []))
    res["verdict"] = {
        "window_rate_basis": "fills whose own ts is inside the window",
        "ws_in_window_fills_all_swap": ws_all.get("n_fills_inside_window"),
        "ws_in_window_fills_btc_usdt_sub": ws_fam.get("n_fills_inside_window"),
        "rest_in_window_fills_uly_btc_usdt": n_rest_in,
        "ws_ts_span_hours_all_swap": ws_all.get("ts_span_hours"),
        "ws_connect_backlog": bool((ws_all.get("ts_span_hours") or 0) > 1.0),
        "instFamily_filter_honoured": bool(
            (ws_fam.get("n_instIds_outside_BTC-USDT") or 0) == 0),
        "ws_both_subscriptions_same_nonfamily_set": same_set,
        "can_measure_daily_rate": all(
            c.get("usable_as_daily_rate")
            for c in extrap["calibers"].values()),
        "statement": (
            "本次测不出日量" if not all(c.get("usable_as_daily_rate")
                                        for c in extrap["calibers"].values())
            else "窗内计数可线性外推到日量级(仍非全天值、非下界)"),
    }

    with open(OUT, "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    print("wrote", OUT)
    print("rest polls=%s distinct=%s" % (res.get("rest", {}).get("n_polls"),
                                         res.get("rest", {}).get("n_distinct_fills")))
    for k, v in res["ws"].items():
        print(k, "frames=%s details=%s distinct=%s in_window=%s span_h=%s err=%s" %
              (v["n_frames"], v["n_detail_rows"], v["n_distinct_fills"],
               v["n_fills_inside_window"], v["ts_span_hours"], v["errors"][:1]))
    print(json.dumps(res["verdict"], indent=1, ensure_ascii=False))
    print(json.dumps(extrap["calibers"], indent=1)[:2000])


if __name__ == "__main__":
    main()
