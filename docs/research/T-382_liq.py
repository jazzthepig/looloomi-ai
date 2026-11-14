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

Writes docs/research/T-382_liq_results.json
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
OUT = os.path.join(HERE, "T-382_liq_results.json")
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
            return label, {"subscribe": sub, "n_frames": len(frames),
                           "n_detail_rows": len(details),
                           "n_distinct_fills": len(uniq),
                           "n_connections": n_conn,
                           "ts_min": ts_list[0] if ts_list else None,
                           "ts_max": ts_list[-1] if ts_list else None,
                           "n_instIds": len(insts),
                           "instId_counts": dict(sorted(insts.items(),
                                                       key=lambda kv: -kv[1])[:12]),
                           "first_frame": frames[0][:300] if frames else None,
                           "last_frame": frames[-1][:300] if frames else None,
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
    t_lo = int(start.timestamp() * 1000)
    t_hi = int(t_end * 1000)
    scale = 86400.0 / WINDOW_S
    extrap = {"scale_per_day": round(scale, 4),
              "window_s": WINDOW_S,
              "calibers": {}}
    r = res.get("rest", {})
    fills = r.get("fills", [])
    in_win = [f for f in fills if t_lo <= int(f.get("ts", 0)) <= t_hi]
    extrap["calibers"]["okx_rest_uly_BTC-USDT"] = {
        "n_distinct_fills_seen": len(fills),
        "n_fills_inside_window": len(in_win),
        "n_fills_outside_window": len(fills) - len(in_win),
        "rows_per_poll_max": r.get("max_rows_per_poll"),
        "extrapolated_per_day": round(len(in_win) * scale, 1),
        "caliber": "one instrument family (BTC-USDT), 15s poll, snapshot endpoint",
    }
    for label, v in res.get("ws", {}).items():
        n = v.get("n_distinct_fills", 0)
        extrap["calibers"]["okx_ws_" + label] = {
            "n_distinct_fills": n,
            "ts_min": v.get("ts_min"),
            "ts_max": v.get("ts_max"),
            "n_instIds": v.get("n_instIds"),
            "extrapolated_per_day": round(n * scale, 1),
            "caliber": ("push, no gap" if label == "ws_all_swap"
                        else "push, one instrument family"),
        }
    extrap["caveat"] = (
        "quiet-hours sample scaled linearly; NOT a lower bound (the active part "
        "of the day is not represented), NOT a day total, NOT the market, "
        "and NOT a promise of any order size")
    res["extrapolation"] = extrap

    with open(OUT, "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    print("wrote", OUT)
    print("rest polls=%s distinct=%s" % (res.get("rest", {}).get("n_polls"),
                                         res.get("rest", {}).get("n_distinct_fills")))
    for k, v in res["ws"].items():
        print(k, "frames=%s details=%s distinct=%s err=%s" %
              (v["n_frames"], v["n_detail_rows"], v["n_distinct_fills"], v["error"]))
    print(json.dumps(extrap, indent=1)[:1600])


if __name__ == "__main__":
    main()
