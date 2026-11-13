#!/usr/bin/env python3
"""T-376 gap probes (round 2): read-only HTTP/WS, no keys, no .env reads.

Fills the holes round 1 left open:
  (a) WS liquidation streams on the CORRECT v5 paths (binance/okx/bybit/hyperliquid)
  (b) ETH spot ETF daily net-flow candidates (tftc siblings, nasdaq endpoints, EDGAR)
  (c) token-unlock calendar candidates (CMC/DefiLlama internal data-api, Next.js data routes)
  (d) circulating-supply HISTORY series (CMC chart semantics, blockchain.com charts)

Writes docs/research/T-376_probe_gaps.json next to itself.
Run: python3 docs/research/T-376_probe_gaps.py
"""
import asyncio
import json
import os
import re
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "T-376_probe_gaps.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
RECORDS = []


def http(name, url, method="GET", body=None, headers=None, timeout=25, parse=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    t0 = time.time()
    rec = {"name": name, "url": url, "method": method}
    txt = ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read(400000).decode("utf-8", "replace")
            rec["status"] = r.status
            rec["ctype"] = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        txt = e.read(2000).decode("utf-8", "replace")
        rec["status"] = e.code
        rec["ctype"] = e.headers.get("Content-Type", "")
        rec["http_error"] = True
    except Exception as e:
        rec["status"] = None
        rec["error"] = f"{type(e).__name__}: {e}"
    rec["ms"] = int((time.time() - t0) * 1000)
    rec["first200"] = txt[:200]
    try:
        j = json.loads(txt) if txt else None
        if isinstance(j, dict):
            rec["keys"] = list(j.keys())[:20]
            for k in ("code", "msg", "message", "error", "status"):
                if k in j and isinstance(j[k], (str, int, float)):
                    rec["code_" + k] = str(j[k])[:120]
            if isinstance(j.get("data"), list):
                rec["data_len"] = len(j["data"])
                if j["data"] and isinstance(j["data"][0], dict):
                    rec["data0_keys"] = list(j["data"][0].keys())[:20]
            if isinstance(j.get("days"), list):
                rec["days_len"] = len(j["days"])
                if j["days"]:
                    rec["day0"] = str(j["days"][0])[:160]
                    rec["day_last"] = str(j["days"][-1])[:160]
        elif isinstance(j, list):
            rec["list_len"] = len(j)
            if j and isinstance(j[0], dict):
                rec["item0_keys"] = list(j[0].keys())[:20]
    except Exception:
        pass
    if parse:
        try:
            rec.update(parse(j, txt) or {})
        except Exception as e:
            rec["parse_error"] = f"{type(e).__name__}: {e}"
    RECORDS.append(rec)
    print(f"{name:34s} {str(rec.get('status')):>5} {rec.get('ms'):>6}ms "
          f"{rec.get('data_len') or rec.get('list_len') or rec.get('days_len') or ''}")
    return rec


def ws_probe(name, url, subscribe=None, seconds=60):
    """Connect, optionally send one subscribe msg, collect raw frames for `seconds`."""
    import websockets

    async def run():
        events, err = [], None
        t0 = time.time()
        try:
            async with websockets.connect(url, open_timeout=20, max_size=None,
                                          ping_interval=None) as sock:
                if subscribe is not None:
                    await sock.send(json.dumps(subscribe))
                while time.time() - t0 < seconds:
                    left = seconds - (time.time() - t0)
                    if left <= 0:
                        break
                    try:
                        raw = await asyncio.wait_for(sock.recv(), timeout=min(left, 20))
                    except asyncio.TimeoutError:
                        break
                    events.append(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        return events, err

    events, err = asyncio.run(run())
    rec = {"name": name, "url": url, "method": "WS", "status": 200 if events else None,
           "events": len(events), "seconds": seconds,
           "per_min": round(len(events) / (seconds / 60.0), 3),
           "first200": (events[0][:200] if events else ""),
           "error": err}
    RECORDS.append(rec)
    print(f"{name:34s} WS events={len(events):<5} {rec['per_min']}/min {err or ''} "
          f"{rec['first200'][:110]}")
    return rec


# ---------------------------------------------------------------- (d) supply history
def _cmc_chart(j, txt):
    try:
        pts = j["data"]["points"]
        ks = sorted(int(k) for k in pts)
        first, last = pts[str(ks[0])], pts[str(ks[-1])]
        return {"points": len(ks),
                "ts_first": ks[0], "date_first": time.strftime("%Y-%m-%d", time.gmtime(ks[0])),
                "ts_last": ks[-1], "date_last": time.strftime("%Y-%m-%d", time.gmtime(ks[-1])),
                "v_first": first.get("v"), "v_last": last.get("v"),
                "c_first": first.get("c"), "c_last": last.get("c")}
    except Exception as e:
        return {"cmc_parse_error": str(e)}


# ---------------------------------------------------------------- (b) ETF flows
def _tftc(j, txt):
    try:
        d = j.get("data") or j
        if isinstance(d, list) and d:
            return {"row0_keys": list(d[0].keys())[:20], "rows": len(d),
                    "row0": json.dumps(d[0])[:220]}
        if isinstance(d, dict):
            return {"top_keys": list(d.keys())[:20],
                    "sample": json.dumps(d)[:220]}
    except Exception as e:
        return {"tftc_parse_error": str(e)}
    return {}


def _nasdaq(j, txt):
    try:
        sd = j.get("data", {}).get("summaryData", {})
        return {"summary_keys": list(sd.keys())[:24]}
    except Exception as e:
        return {"nasdaq_parse_error": str(e)}


def main():
    # ---------------- (d) circulating supply HISTORY ----------------
    print("--- supply history ---")
    http("supply_cmc_chart_sol_all", "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id=5426&range=all", parse=_cmc_chart)
    http("supply_cmc_chart_btc_all", "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id=1&range=all", parse=_cmc_chart)
    http("supply_cmc_detail_eth", "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail?id=1027")
    http("supply_bc_total_btc_json", "https://api.blockchain.info/charts/total-bitcoins?timespan=all&format=json")
    http("supply_bc_eth_total", "https://api.blockchain.info/charts/eth-total?timespan=all&format=json")
    http("supply_bc_charts_list", "https://api.blockchain.info/charts/list")
    http("supply_cmc_chart_xmr_all", "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id=1447&range=all", parse=_cmc_chart)

    # ---------------- (b) ETH spot ETF net flow ----------------
    print("--- eth etf flow ---")
    for nm, u in [
        ("etf_tftc_eth_flows", "https://www.tftc.io/ethereum-etf-flows/data.json"),
        ("etf_tftc_ethflow2", "https://www.tftc.io/eth-etf-flows/data.json"),
        ("etf_tftc_sol_flows", "https://www.tftc.io/solana-etf-flows/data.json"),
        ("etf_tftc_root_links", "https://www.tftc.io/"),
    ]:
        http(nm, u, parse=_tftc)
    http("etf_nasdaq_etha_netflow", "https://api.nasdaq.com/api/quote/ETHA/net-fund-flows?assetclass=etf")
    http("etf_nasdaq_etha_netflow2", "https://api.nasdaq.com/api/quote/ETHA/net-flows?assetclass=etf")
    http("etf_nasdaq_etha_fundflow2", "https://api.nasdaq.com/api/quote/ETHA/fund-flow?assetclass=etf")
    http("etf_nasdaq_etha_hist", "https://api.nasdaq.com/api/quote/ETHA/historical?assetclass=etf&fromdate=2026-10-01&todate=2026-11-13")
    http("etf_nasdaq_etha_summ2", "https://api.nasdaq.com/api/quote/ETHA/summary?assetclass=etf", parse=_nasdaq)
    # SEC EDGAR: find the iShares Ethereum Trust CIK + NPORT filings
    http("etf_edgar_atom_ishares_eth", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=ishares+ethereum+trust&type=NPORT-P&output=atom")
    http("etf_edgar_atom_etf_a", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=ethereum+trust&type=NPORT-P&output=atom")
    http("etf_edgar_fts", "https://efts.sec.gov/LATEST/search-index?q=%22iShares+Ethereum+Trust%22&forms=NPORT-P")
    http("etf_edgar_submissions_ibit", "https://data.sec.gov/submissions/CIK0001980994.json")

    # ---------------- (c) token unlock calendar ----------------
    print("--- unlock calendar ---")
    http("unlock_cmc_dataapi", "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/token-unlocks?id=1027")
    http("unlock_cmc_dataapi2", "https://api.coinmarketcap.com/data-api/v3/token-unlocks")
    http("unlock_llama_emissions", "https://api.llama.fi/emissions")
    http("unlock_llama_emission_eth", "https://api.llama.fi/emission/ethereum")
    http("unlock_llama_unlocks", "https://api.llama.fi/unlocks")
    http("unlock_llama_coins_emissions", "https://coins.llama.fi/emissions")
    http("unlock_tokenomist_pub", "https://api.tokenomist.ai/v1/unlocks")
    http("unlock_cryptorank_pub", "https://api.cryptorank.io/v1/tokens/unlocks")

    # Next.js data-route discovery (free, no key)
    for nm, page, base in [
        ("unlock_dl_next", "https://defillama.com/unlocks", "https://defillama.com"),
        ("unlock_cmc_next", "https://coinmarketcap.com/token-unlocks/", "https://coinmarketcap.com"),
    ]:
        def _next(j, txt, page=page, base=base):
            m = re.search(r'"buildId":"([^"]+)"', txt)
            out = {"build_id": m.group(1) if m else None}
            hits = sorted(set(re.findall(r'https?://[a-z0-9.\-]*llama\.fi/[^"\'\\ ]{3,80}', txt)))[:8]
            out["llama_urls_in_html"] = hits
            hits2 = sorted(set(re.findall(r'/data-api/v3/[A-Za-z0-9/_?=&.\-]{3,60}', txt)))[:12]
            out["data_api_paths_in_html"] = hits2
            return out
        http(nm, page, parse=_next)

    # ---------------- (a) liquidation: REST + WS ----------------
    print("--- liquidation rest ---")
    http("liq_binance_fapi_allforce", "https://fapi.binance.com/fapi/v1/allForceOrders?symbol=BTCUSDT&limit=10")
    http("liq_binance_fapi_allforce_nosym", "https://fapi.binance.com/fapi/v1/allForceOrders?limit=10")
    http("liq_binance_dapi_allforce", "https://dapi.binance.com/dapi/v1/allForceOrders?symbol=BTCUSD_PERP&limit=10")
    http("liq_binance_fapi_time", "https://fapi.binance.com/fapi/v1/time")
    http("liq_binance_vision_dir", "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/?prefix=data/futures/um/monthly/liquidationSnapshot/BTCUSDT/&delimiter=/")
    http("liq_okx_priapi", "https://www.okx.com/priapi/v5/liquidation-orders?instType=SWAP&state=filled&uly=BTC-USDT&limit=100")
    http("liq_okx_rest_eth", "https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&state=filled&uly=ETH-USDT&limit=100")
    http("liq_bybit_recent_trade", "https://api.bybit.com/v5/market/recent-trade?category=linear&symbol=BTCUSDT&limit=5")
    http("liq_hl_info_badtype", "https://api.hyperliquid.xyz/info", method="POST", body={"type": "__probe__"})

    # ---------------- (a) liquidation: WS on correct paths ----------------
    print("--- liquidation ws (60s each) ---")
    ws_probe("ws_binance_forceorder", "wss://fstream.binance.com/stream?streams=btcusdt@forceOrder",
             {"method": "SUBSCRIBE", "params": ["btcusdt@forceOrder"], "id": 1})
    ws_probe("ws_binance_aggtrade_ctrl", "wss://fstream.binance.com/stream?streams=btcusdt@aggTrade",
             {"method": "SUBSCRIBE", "params": ["btcusdt@aggTrade"], "id": 1}, seconds=30)
    ws_probe("ws_okx_liq_channel", "wss://ws.okx.com:8443/ws/v5/liquidation",
             {"op": "subscribe", "args": [{"channel": "liquidation", "instType": "SWAP"}]})
    ws_probe("ws_okx_public_channel", "wss://ws.okx.com:8443/ws/v5/public",
             {"op": "subscribe", "args": [{"channel": "liquidation-orders", "instType": "SWAP"}]})
    ws_probe("ws_bybit_allliq_linear", "wss://stream.bybit.com/v5/public/linear",
             {"op": "subscribe", "args": ["allLiquidation.BTCUSDT"]})
    ws_probe("ws_hl_allmids", "wss://api.hyperliquid.xyz/ws",
             {"method": "subscribe", "subscription": {"type": "allMids"}}, seconds=30)

    with open(OUT, "w") as f:
        json.dump({"probed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "results": RECORDS}, f, indent=1)
    print("WROTE", OUT, len(RECORDS))


if __name__ == "__main__":
    main()
