#!/usr/bin/env python3
"""T-376 final probes: capture actual WS frames + verify CMC supply semantics.

Writes docs/research/T-376_probe_final.json
"""
import asyncio
import json
import os
import re
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "T-376_probe_final.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
R = []


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(2_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000).decode("utf-8", "replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def http(name, url, timeout=30):
    st, txt = get(url, timeout)
    rec = {"name": name, "url": url, "status": st, "first200": txt[:200]}
    try:
        j = json.loads(txt)
        if isinstance(j, dict):
            rec["keys"] = list(j.keys())[:20]
    except Exception:
        pass
    R.append(rec)
    print(f"{name:34s} {st} {txt[:90]}".replace("\n", " "))
    return rec, txt


def ws(name, url, subscribe=None, seconds=60, keep=3):
    import websockets

    async def run():
        frames, err = [], None
        t0 = time.time()
        try:
            async with websockets.connect(url, open_timeout=20, max_size=None,
                                          ping_interval=None) as s:
                if subscribe is not None:
                    await s.send(json.dumps(subscribe))
                while time.time() - t0 < seconds:
                    left = seconds - (time.time() - t0)
                    if left <= 0:
                        break
                    try:
                        raw = await asyncio.wait_for(s.recv(), timeout=min(left, 15))
                    except asyncio.TimeoutError:
                        break
                    frames.append(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        return frames, err

    frames, err = asyncio.run(run())
    payload = [f for f in frames if '"channel":"liquidation' in f or 'Liquidation' in f
               or 'liquidat' in f.lower() and 'op' not in f[:6]]
    rec = {"name": name, "url": url, "method": "WS", "status": 200 if frames else None,
           "frames": len(frames), "liquidation_frames": len(payload),
           "per_min": round(len(frames) / (seconds / 60.0), 2),
           "frames_head": frames[:keep], "frames_tail": frames[-keep:] if frames else [],
           "error": err}
    R.append(rec)
    print(f"{name:34s} WS frames={len(frames)} liq={len(payload)} {err or ''}")
    for f in (frames[:2] + frames[-2:]):
        print("      ", f[:180].replace("\n", " "))
    return rec


def main():
    # --- 1. supply semantics: CMC v[4] vs blockchain.com (independent series) ---
    st, txt = get("https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id=1&range=all")
    try:
        pts = json.loads(txt)["data"]["points"]
        ks = sorted(int(k) for k in pts)
        gaps = [ks[i + 1] - ks[i] for i in range(len(ks) - 1)]
        recent = gaps[-90:]
        supply = {time.strftime("%Y-%m-%d", time.gmtime(k)): pts[str(k)]["v"][4] for k in ks[-5:]}
        first_supply = pts[str(ks[0])]["v"][4]
        st2, txt2 = get("https://api.blockchain.info/charts/total-bitcoins?timespan=all&format=json")
        bc = json.loads(txt2)
        bc_map = {time.strftime("%Y-%m-%d", time.gmtime(v["x"] / 1000)): v["y"] for v in bc["values"]}
        bc_first = time.strftime("%Y-%m-%d", time.gmtime(bc["values"][0]["x"] / 1000))
        bc_last = time.strftime("%Y-%m-%d", time.gmtime(bc["values"][-1]["x"] / 1000))
        cmp_pairs = []
        for d, s in supply.items():
            cand = bc_map.get(d)
            if cand is None:
                for d2, c in bc_map.items():
                    if abs((time.mktime(time.strptime(d2, "%Y-%m-%d")) -
                            time.mktime(time.strptime(d, "%Y-%m-%d")))) < 3 * 86400:
                        cand = c
                        break
            if cand:
                cmp_pairs.append((d, round(float(s), 1), round(float(cand), 1)))
        rec = {"name": "verify_cmc_v4_is_supply", "status": 200,
               "cmc_points": len(ks), "cmc_first_date": time.strftime("%Y-%m-%d", time.gmtime(ks[0])),
               "cmc_last_date": time.strftime("%Y-%m-%d", time.gmtime(ks[-1])),
               "cmc_first_supply": first_supply,
               "cmc_gap_median_recent_days": round(sorted(recent)[len(recent) // 2] / 86400, 2),
               "cmc_gap_median_all_days": round(sorted(gaps)[len(gaps) // 2] / 86400, 2),
               "bc_first_date": bc_first, "bc_last_date": bc_last, "bc_points": len(bc["values"]),
               "bc_name": bc.get("name"), "bc_unit": bc.get("unit"), "bc_description": bc.get("description"),
               "cmc_vs_blockchain": cmp_pairs}
        R.append(rec)
        print(json.dumps(rec, indent=1)[:1400])
    except Exception as e:
        print("supply verify failed:", type(e).__name__, e)

    # --- 2. binance archive: is liquidationSnapshot really empty? ---
    st, txt = get("https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/?prefix=data/futures/um/monthly/liquidationSnapshot/BTCUSDT/")
    keys = re.findall(r"<Key>([^<]+)</Key>", txt)
    st2, txt2 = get("https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/?prefix=data/futures/um/monthly/&delimiter=/")
    dirs = re.findall(r"<Prefix>([^<]+)</Prefix>", txt2)
    rec = {"name": "binance_vision_liq_snapshot", "status": st,
           "keys_under_liqsnapshot": keys[:10], "n_keys": len(keys),
           "monthly_dirs_sample": dirs[:12], "n_monthly_dirs": len(dirs)}
    R.append(rec)
    print(json.dumps(rec)[:700])

    # --- 3. TFTC: any eth dataset? list json links on root ---
    st, txt = get("https://www.tftc.io/")
    links = sorted(set(re.findall(r'href="(/[^"]*)"', txt)))[:40]
    st2, txt2 = get("https://www.tftc.io/ethereum-etf/")
    rec = {"name": "tftc_links", "status": st, "links": links,
           "eth_page_status": st2, "eth_page_head": txt2[:160]}
    R.append(rec)
    print(json.dumps(rec)[:900])

    # --- 4. WS: capture real liquidation frames ---
    ws("ws_okx_public_443", "wss://ws.okx.com/ws/v5/public",
       {"op": "subscribe", "args": [{"channel": "liquidation-orders", "instType": "SWAP"}]}, seconds=75)
    ws("ws_bybit_allliq", "wss://stream.bybit.com/v5/public/linear",
       {"op": "subscribe", "args": ["allLiquidation.BTCUSDT"]}, seconds=75)
    ws("ws_binance_pathstyle", "wss://fstream.binance.com/ws/btcusdt@aggTrade", None, seconds=30)
    ws("ws_binance_forceorder_pathstyle", "wss://fstream.binance.com/ws/btcusdt@forceOrder", None, seconds=45)

    with open(OUT, "w") as f:
        json.dump({"probed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "results": R}, f, indent=1)
    print("WROTE", OUT, len(R))


if __name__ == "__main__":
    main()
