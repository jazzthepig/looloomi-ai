#!/usr/bin/env python3
"""T-376 data-source probes (read-only HTTP/WS, no keys).

Writes docs/research/T-376_probe_results.json next to itself.
Run:  python3 docs/research/T-376_probe.py
Every probe records: status, latency, first 200 chars of the real response,
and (for JSON) the top-level keys, so the report quotes actual returns.
"""
import asyncio
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "T-376_probe_results.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def probe(name, url, method="GET", body=None, headers=None, timeout=20, extra=None):
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
            txt = r.read(60000).decode("utf-8", "replace")
            rec["status"] = r.status
            rec["ctype"] = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        txt = e.read(4000).decode("utf-8", "replace")
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
            rec["keys"] = list(j.keys())[:24]
            for k in ("code", "msg", "message", "error"):
                if k in j and isinstance(j[k], (str, int, float)):
                    rec["code_" + k] = j[k]
            if isinstance(j.get("data"), list):
                rec["data_len"] = len(j["data"])
                if j["data"] and isinstance(j["data"][0], dict):
                    rec["data0_keys"] = list(j["data"][0].keys())[:24]
            if isinstance(j.get("days"), list):
                rec["days_len"] = len(j["days"])
                if j["days"]:
                    rec["day0"] = j["days"][0]
                    rec["day_last"] = j["days"][-1]
        elif isinstance(j, list):
            rec["list_len"] = len(j)
            if j and isinstance(j[0], dict):
                rec["item0_keys"] = list(j[0].keys())[:24]
    except Exception:
        pass
    if extra:
        try:
            for k, fn in (extra.items() if isinstance(extra, dict) else []):
                if callable(fn):
                    rec[k] = fn(j, txt)
                elif isinstance(fn, (list, tuple)):
                    pats, n = fn[0], fn[1] if len(fn) > 1 else 5
                    hits = []
                    for p in pats:
                        hits += re.findall(p, txt)[:n]
                    rec[k] = hits[: n * len(pats)]
                else:
                    rec[k] = fn
        except Exception as e:
            rec["extra_error"] = f"{type(e).__name__}: {e}"
    return rec


async def ws_probe(name, url, sub=None, seconds=45):
    import websockets  # noqa
    rec = {"name": name, "url": url, "kind": "websocket", "planned_seconds": seconds}
    t0 = time.time()
    count = 0
    samples = []
    try:
        async with websockets.connect(url, open_timeout=20, close_timeout=5,
                                     max_size=2 ** 20) as ws:
            if sub:
                await ws.send(json.dumps(sub))
            end = time.time() + seconds
            while time.time() < end:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=max(0.5, end - time.time()))
                except asyncio.TimeoutError:
                    break
                count += 1
                if len(samples) < 3:
                    samples.append(msg[:300])
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    el = time.time() - t0
    rec["events"] = count
    rec["elapsed_s"] = round(el, 1)
    rec["events_per_min"] = round(count / max(el, 1) * 60, 3)
    rec["events_per_day_est"] = int(rec["events_per_min"] * 1440)
    rec["samples"] = samples
    return rec


HTTP_PROBES = [
    # ---------- 1. liquidation ----------
    ("okx_liq_rest_btc",
     "https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&state=filled&uly=BTC-USDT&limit=100",
     "GET", None, None,
     {"okx_code": lambda j, t: j.get("code"),
      "n_details": lambda j, t: len(j.get("data") or []),
      "ts_span_h": lambda j, t: (round((max(d["details"][0]["ts"] for d in j["data"]) -
                                        min(d["details"][0]["ts"] for d in j["data"])) / 3.6e6, 2)
                                 if j.get("data") else None),
      "detail0": lambda j, t: (j["data"][0]["details"][0] if j.get("data") else None),
      "inst_ids": lambda j, t: sorted({d.get("instId") for d in (j.get("data") or [])})[:10]}),
    ("okx_liq_details_count",
     "https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&state=filled&uly=BTC-USDT&limit=100",
     "GET", None, None,
     {"n_liq": lambda j, t: sum(len(d.get("details") or []) for d in (j.get("data") or [])),
      "n_groups": lambda j, t: len(j.get("data") or []),
      "ts_min": lambda j, t: (min(x["ts"] for d in (j.get("data") or []) for x in d.get("details") or [])
                              if j.get("data") else None),
      "ts_max": lambda j, t: (max(x["ts"] for d in (j.get("data") or []) for x in d.get("details") or [])
                              if j.get("data") else None),
      "detail0": lambda j, t: ((j["data"][0]["details"] or [{}])[0] if j.get("data") else None)}),
    ("okx_liq_rest_family",
     "https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&state=filled&instFamily=BTC-USDT&limit=100",
     "GET", None, None,
     {"n_details": lambda j, t: len(j.get("data") or []),
      "ts_span_h": lambda j, t: (round((max(d["details"][0]["ts"] for d in j["data"]) -
                                        min(d["details"][0]["ts"] for d in j["data"])) / 3.6e6, 2)
                                 if j.get("data") else None)}),
    ("okx_liq_rest_no_uly",
     "https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&state=filled&limit=100",
     "GET", None, None, None),
    ("binance_allforce",
     "https://fapi.binance.com/fapi/v1/allForceOrders?symbol=BTCUSDT&limit=10",
     "GET", None, None, None),
    ("binance_ws_http_probe",
     "https://fapi.binance.com/fapi/v1/exchangeInfo", "GET", None, None,
     {"n_symbols": lambda j, t: len(j.get("symbols") or [])}),
    ("bybit_recent_trade",
     "https://api.bybit.com/v5/market/recent-trade?category=linear&symbol=BTCUSDT&limit=5",
     "GET", None, None,
     {"item0_keys": lambda j, t: list(((j.get("result") or {}).get("list") or [{}])[0].keys())}),
    ("bybit_public_data_root",
     "https://public.bybit.com/", "GET", None, None,
     {"liq_hits": ([r"[\w/\-\.]*[Ll]iquid[\w/\-\.]*"], 8)}),
    ("okx_data_download",
     "https://www.okx.com/data-download", "GET", None, None,
     {"liq_hits": ([r"[Ll]iquid\w*"], 8)}),
    ("hl_info_recent_liq",
     "https://api.hyperliquid.xyz/info", "POST", {"type": "recentLiquidations"}, None, None),
    ("hl_info_hist_liq",
     "https://api.hyperliquid.xyz/info", "POST", {"type": "historicalLiquidations"}, None, None),
    ("hl_info_meta",
     "https://api.hyperliquid.xyz/info", "POST", {"type": "meta"}, None, None),
    # ---------- 2. ETH spot ETF daily net flows ----------
    ("tftc_eth_etf_flows",
     "https://www.tftc.io/ethereum-etf-flows/data.json", "GET", None, None, None),
    ("tftc_btc_etf_flows",
     "https://www.tftc.io/bitcoin-etf-flows/data.json", "GET", None, None, None),
    ("tftc_root",
     "https://www.tftc.io/", "GET", None, None,
     {"etf_links": ([r"[\w/\-\.]*etf[\w/\-\.]*"], 12)}),
    ("etf_nasdaq_etha",
     "https://api.nasdaq.com/api/quote/ETHA/summary?assetclass=etf", "GET", None, None, None),
    ("etf_stooq_etha",
     "https://stooq.com/q/d/l/?s=etha.us&i=d", "GET", None, None,
     {"csv_head": lambda j, t: t.split("\n")[0] + " || " + t.split("\n")[1] if "\n" in t else t[:120]}),
    ("etf_coinglass_page",
     "https://www.coinglass.com/eth-etf", "GET", None, None, None),
    ("etf_sosovalue_page",
     "https://www.sosovalue.com/etf/eth", "GET", None, None, None),
    ("etf_yahoo_etha_chart",
     "https://query1.finance.yahoo.com/v8/finance/chart/ETHA?range=5d&interval=1d",
     "GET", None, None, None),
    ("etf_fidelity_feth",
     "https://digital.fidelity.com/prgw/digital/research/quote/dashboard/summary?symbol=FETH",
     "GET", None, None, None),
    ("etf_sec_edgar_atom",
     "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=ishares+ethereum+trust&type=NPORT-P&output=atom",
     "GET", None, {"User-Agent": "cometcloud-research sabastian@cometcloud.ai"}, None),
    ("etf_coinglass_ethflow",
     "https://open-api-v3.coinglass.com/api/etf/ethereum/flow-history",
     "GET", None, None, None),
    ("etf_sosovalue_api",
     "https://api.sosovalue.com/api/v1/etf/eth/daily", "GET", None, None, None),
    # ---------- 3. altcoin unlock calendar ----------
    ("unlock_llama_emission_eth",
     "https://api.llama.fi/emission/ethereum", "GET", None, None, None),
    ("unlock_defillama_page",
     "https://defillama.com/unlocks", "GET", None, None, None),
    ("unlock_cryptorank_api",
     "https://api.cryptorank.io/v2/token/unlock/schedule", "GET", None, None, None),
    ("unlock_dropstab_api",
     "https://api.drops.tab/api/unlocks", "GET", None, None, None),
    ("unlock_tokenomist_page",
     "https://tokenomist.ai/ethereum", "GET", None, None, None),
    ("unlock_tokenomist_api",
     "https://api.tokenomist.ai/v1/token/ETH", "GET", None, None, None),
    ("unlock_cryptorank_page",
     "https://cryptorank.io/price/unlocks", "GET", None, None, None),
    ("unlock_dropstab_page",
     "https://drops.tab/unlocks", "GET", None, None, None),
    ("unlock_cmc_page",
     "https://coinmarketcap.com/token-unlocks/", "GET", None, None, None),
    ("unlock_cmc_api",
     "https://api.coinmarketcap.com/data-api/v3/token-unlock/list", "GET", None, None, None),
    # ---------- 4. circulating supply history ----------
    ("supply_cg_hist_eth",
     "https://api.coingecko.com/api/v3/coins/ethereum/history?date=30-06-2020&localization=false",
     "GET", None, None,
     {"md_keys": lambda j, t: list((j.get("market_data") or {}).keys())[:20],
      "circ": lambda j, t: (j.get("market_data") or {}).get("circulating_supply")}),
    ("supply_cg_hist_sol",
     "https://api.coingecko.com/api/v3/coins/solana/history?date=01-01-2023&localization=false",
     "GET", None, None, None),
    ("supply_cg_site_hist",
     "https://www.coingecko.com/api/v3/coins/ethereum/history?date=30-06-2020&localization=false",
     "GET", None, None, None),
    ("supply_cg_market_chart_eth",
     "https://api.coingecko.com/api/v3/coins/ethereum/market_chart?vs_currency=usd&days=max&interval=daily",
     "GET", None, None,
     {"mc_keys": lambda j, t: list((j.get("market_caps") or {})[0].keys()) if j.get("market_caps") else None,
      "n_points": lambda j, t: len(j.get("market_caps") or []),
      "first_pt": lambda j, t: (j.get("market_caps") or [None])[0],
      "last_pt": lambda j, t: (j.get("market_caps") or [None])[-1]}),
    ("supply_cg_current_eth",
     "https://api.coingecko.com/api/v3/coins/ethereum?localization=false&tickers=false&community_data=false&developer_data=false&sparkline=false",
     "GET", None, None,
     {"circ": lambda j, t: (j.get("market_data") or {}).get("circulating_supply"),
      "mcap": lambda j, t: (j.get("market_data") or {}).get("market_cap")}),
    ("supply_cmc_chart_eth",
     "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id=1027&range=all",
     "GET", None, None,
     {"point_keys": lambda j, t: list((((j.get("data") or {}).get("points") or {}).values() or [{}])[0].keys()),
      "point0": lambda j, t: (list(((j.get("data") or {}).get("points") or {}).values()) or [None])[0],
      "n_points": lambda j, t: len(((j.get("data") or {}).get("points") or {}))}),
    ("supply_bc_total_bitcoins",
     "https://api.blockchain.info/charts/total-bitcoins?timespan=2years&format=json",
     "GET", None, None,
     {"n_vals": lambda j, t: len(((j.get("values") or {}))),
      "unit": lambda j, t: j.get("unit"), "name": lambda j, t: j.get("name")}),
    ("supply_etherscan_v1",
     "https://api.etherscan.io/api?module=stats&action=ethsupply", "GET", None, None, None),
    ("supply_etherscan_v2",
     "https://api.etherscan.io/v2/api?chainid=1&module=stats&action=ethsupply", "GET", None, None, None),
    ("supply_coinlore_eth",
     "https://api.coinlore.net/api/coin/?id=80", "GET", None, None, None),
    # ---------- round 4: follow-ups on what looked reachable ----------
    ("etf_nasdaq_etha_full",
     "https://api.nasdaq.com/api/quote/ETHA/summary?assetclass=etf", "GET", None, None,
     {"summary_keys": lambda j, t: list((((j.get("data") or {}).get("summaryData")) or {}).keys()),
      "summary": lambda j, t: {k: v.get("value") for k, v in
                               ((((j.get("data") or {}).get("summaryData")) or {}).items())}}),
    ("etf_nasdaq_ethe_full",
     "https://api.nasdaq.com/api/quote/ETHE/summary?assetclass=etf", "GET", None, None,
     {"summary_keys": lambda j, t: list((((j.get("data") or {}).get("summaryData")) or {}).keys())}),
    ("etf_nasdaq_ibit_full",
     "https://api.nasdaq.com/api/quote/IBIT/summary?assetclass=etf", "GET", None, None,
     {"summary_keys": lambda j, t: list((((j.get("data") or {}).get("summaryData")) or {}).keys())}),
    ("etf_nasdaq_etha_fundflow",
     "https://api.nasdaq.com/api/quote/ETHA/fund-flow?assetclass=etf", "GET", None, None, None),
    ("etf_nasdaq_etha_chart",
     "https://api.nasdaq.com/api/quote/ETHA/chart?assetclass=etf&fromdate=2026-10-01&todate=2026-11-13",
     "GET", None, None, None),
    ("etf_edgar_cik",
     "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=ishares+ethereum+trust&type=NPORT-P&output=atom",
     "GET", None, {"User-Agent": "cometcloud-research sabastian@cometcloud.ai"},
     {"cik_hits": ([r"CIK\d{10}", r"\d{10}0001725210"], 6)}),
    ("etf_coinglass_capi",
     "https://capi.coinglass.com/api/etf/ethereum/flow-history", "GET", None, None, None),
    ("etf_coinglass_web_api",
     "https://www.coinglass.com/api/etf/ethereum/flow-history", "GET", None, None, None),
    ("unlock_cmc_page_api_hits",
     "https://coinmarketcap.com/token-unlocks/", "GET", None, None,
     {"api_hits": ([r"/data-api/v3/[A-Za-z0-9\-_/\.]+"], 8)}),
    ("unlock_defillama_page_api_hits",
     "https://defillama.com/unlocks", "GET", None, None,
     {"api_hits": ([r"https://api\.llama\.fi/[A-Za-z0-9\-_/\.]*", r"/emissions?[A-Za-z0-9\-_/\.]*"], 8)}),
    ("supply_cg_hist_within_1y",
     "https://api.coingecko.com/api/v3/coins/ethereum/history?date=15-03-2026&localization=false",
     "GET", None, None,
     {"circ": lambda j, t: (j.get("market_data") or {}).get("circulating_supply"),
      "mcap": lambda j, t: (j.get("market_data") or {}).get("market_cap")}),
    ("supply_cg_hist_error_full",
     "https://api.coingecko.com/api/v3/coins/ethereum/history?date=30-06-2020&localization=false",
     "GET", None, None,
     {"err_full": lambda j, t: (((j.get("error") or {}).get("status") or {}).get("error_message"))}),
    ("supply_cg_mc_365",
     "https://api.coingecko.com/api/v3/coins/ethereum/market_chart?vs_currency=usd&days=365&interval=daily",
     "GET", None, None,
     {"n_points": lambda j, t: len(j.get("market_caps") or []),
      "mc_keys": lambda j, t: list((j.get("market_caps") or {})[0].keys()) if j.get("market_caps") else None}),
    ("supply_cmc_chart_keys",
     "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id=1027&range=all",
     "GET", None, None,
     {"data_keys": lambda j, t: list((j.get("data") or {}).keys()),
      "point_keys": lambda j, t: list((list(((j.get("data") or {}).get("points") or {}).values()) or [{}])[0].keys()),
      "point0": lambda j, t: (list(((j.get("data") or {}).get("points") or {}).values()) or [None])[0],
      "n_points": lambda j, t: len((j.get("data") or {}).get("points") or {}),
      "supply_hits": ([r"[Ss]upply", r"circulating"], 10)}),
    ("supply_bc_total_bitcoins2",
     "https://api.blockchain.info/charts/total-bitcoins?timespan=2years&format=json", "GET", None, None,
     {"n_vals": lambda j, t: len((j.get("values") or {})),
      "unit": lambda j, t: j.get("unit"), "name": lambda j, t: j.get("name"),
      "first_v": lambda j, t: (j.get("values") or {}).get("1")}),
    ("supply_bc_charts_list",
     "https://api.blockchain.info/charts", "GET", None, None,
     {"chart_hits": ([r"[a-z\-]*supply[a-z\-]*", r"total-bitcoins"], 10)}),
    # ---------- round 5: field-level verification of the reachable ones ----------
    ("supply_cmc_one_point",
     "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id=1027&range=1M",
     "GET", None, None,
     {"data_keys": lambda j, t: list((j.get("data") or {}).keys()),
      "point0": lambda j, t: (list(((j.get("data") or {}).get("points") or {}).values()) or [None])[0],
      "point_last": lambda j, t: (list(((j.get("data") or {}).get("points") or {}).values()) or [None])[-1],
      "n_points": lambda j, t: len((j.get("data") or {}).get("points") or {}),
      "has_supply_word": lambda j, t: ("supply" in t.lower(), "circulating" in t.lower())}),
    ("supply_cg_hist_1y_keys",
     "https://api.coingecko.com/api/v3/coins/ethereum/history?date=15-03-2026&localization=false",
     "GET", None, None,
     {"md_keys": lambda j, t: list((j.get("market_data") or {}).keys()),
      "circ": lambda j, t: (j.get("market_data") or {}).get("circulating_supply"),
      "price": lambda j, t: ((j.get("market_data") or {}).get("current_price") or {}).get("usd"),
      "mcap_usd": lambda j, t: ((j.get("market_data") or {}).get("market_cap") or {}).get("usd")}),
    ("supply_cg_mc_365_retry",
     "https://api.coingecko.com/api/v3/coins/ethereum/market_chart?vs_currency=usd&days=365&interval=daily",
     "GET", None, None,
     {"n_points": lambda j, t: len(j.get("market_caps") or []),
      "mc_keys": lambda j, t: list((j.get("market_caps") or {})[0].keys()) if j.get("market_caps") else None,
      "first_mc": lambda j, t: (j.get("market_caps") or [None])[0],
      "last_mc": lambda j, t: (j.get("market_caps") or [None])[-1],
      "first_px": lambda j, t: (j.get("prices") or [None])[0],
      "last_px": lambda j, t: (j.get("prices") or [None])[-1]}),
    ("etf_edgar_cik2",
     "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=ishares+ethereum+trust&type=NPORT-P&output=atom",
     "GET", None, {"User-Agent": "cometcloud-research sabastian@cometcloud.ai"},
     {"cik_hits": ([r"CIK[=\s:]*\d{10}", r"\b000\d{9}\b"], 6),
      "titles": ([r"<title>[^<]{0,80}</title>"], 4)}),
    ("etf_nasdaq_etha_chart_keys",
     "https://api.nasdaq.com/api/quote/ETHA/chart?assetclass=etf&fromdate=2026-10-01&todate=2026-11-13",
     "GET", None, None,
     {"data_keys": lambda j, t: list((j.get("data") or {}).keys()),
      "chart_keys": lambda j, t: list((((j.get("data") or {}).get("chart")) or [{}])[0].keys()) if (j.get("data") or {}).get("chart") else None,
      "chart0": lambda j, t: ((((j.get("data") or {}).get("chart")) or [None])[0]),
      "n_pts": lambda j, t: len((j.get("data") or {}).get("chart") or [])}),
    ("etf_nasdaq_etha_info",
     "https://api.nasdaq.com/api/quote/ETHA/info?assetclass=etf", "GET", None, None,
     {"data_keys": lambda j, t: list((j.get("data") or {}).keys()),
      "primary_data": lambda j, t: (j.get("data") or {}).get("primaryData")}),
    # ---------- round 6: licence / attribution text (measured from the docs pages) ----------
    ("doc_coingecko_history",
     "https://docs.coingecko.com/reference/coins-id-history", "GET", None, None,
     {"attrib": ([r"Data provided by CoinGecko[^.<]{0,80}", r"attribution[^.<]{0,90}"], 4),
      "range": ([r"[^.<]{0,70}(?:365 days|historical data)[^.<]{0,90}"], 4),
      "rate": ([r"[^.<]{0,60}rate limit[^.<]{0,90}"], 4)}),
    ("doc_blockchain_charts",
     "https://www.blockchain.com/explorers/charts/api-documentation", "GET", None, None,
     {"attrib": ([r"[^.<]{0,120}attribut[^.<]{0,140}", r"[^.<]{0,80}link to blockchain\.com[^.<]{0,80}"], 4),
      "rate": ([r"[^.<]{0,60}rate limit[^.<]{0,90}"], 3)}),
    ("doc_coingecko_rate",
     "https://docs.coingecko.com/reference/introduction", "GET", None, None,
     {"rate": ([r"[^.<]{0,90}\d{1,3} calls? per minute[^.<]{0,90}", r"[^.<]{0,60}rate limit[^.<]{0,110}"], 5)}),
]

WS_PROBES = [
    ("ws_binance_forceorder", "wss://fstream.binance.com/ws/!forceOrder@arr", None),
    ("ws_okx_liquidation", "wss://ws.okx.com:8443/ws/liquidation-orders?instType=SWAP", None),
    ("ws_okx_liquidation_sub", "wss://ws.okx.com:8443/ws",
     {"op": "subscribe", "args": [{"channel": "liquidation-orders", "instType": "SWAP"}]}),
    ("ws_okx_liquidation_fam", "wss://ws.okx.com:8443/ws/liquidation-orders?instType=SWAP&instFamily=BTC-USDT", None),
    ("ws_bybit_liquidation", "wss://stream.bybit.com/v5/public/liquidation", None),
    ("ws_bybit_linear", "wss://stream.bybit.com/v5/public/linear",
     {"op": "subscribe", "args": ["liquidation.BTCUSDT"]}),
    ("ws_hyperliquid_liquidation", "wss://api.hyperliquid.xyz/ws",
     {"method": "subscribe", "subscription": {"type": "liquidation", "coin": "BTC"}}),
    ("ws_hyperliquid_nocoin", "wss://api.hyperliquid.xyz/ws",
     {"method": "subscribe", "subscription": {"type": "liquidation"}}),
    ("ws_okx_443", "wss://ws.okx.com/ws",
     {"op": "subscribe", "args": [{"channel": "liquidation-orders", "instType": "SWAP"}]}),
    ("ws_bybit_spot_allliq", "wss://stream.bybit.com/v5/public/spot",
     {"op": "subscribe", "args": ["allLiquidation.BTCUSDT"]}),
    ("ws_bybit_spot_liq", "wss://stream.bybit.com/v5/public/spot",
     {"op": "subscribe", "args": ["liquidation.BTCUSDT"]}),
    ("ws_bybit_linear_allliq", "wss://stream.bybit.com/v5/public/linear",
     {"op": "subscribe", "args": ["allLiquidation.BTCUSDT"]}),
    ("ws_hyperliquid_trades", "wss://api.hyperliquid.xyz/ws",
     {"method": "subscribe", "subscription": {"type": "trades", "coin": "BTC"}}),
]


async def main():
    argv = sys.argv[1:]
    ws_seconds = int(next((a for a in argv if a.isdigit()), os.environ.get("WS_SECONDS", "45")))
    filters = [a for a in argv if not a.isdigit()]
    results = []
    for name, url, method, body, headers, extra in HTTP_PROBES:
        if filters and not any(f in name for f in filters):
            continue
        r = probe(name, url, method, body, headers, extra=extra)
        print(f"{name:30s} {str(r.get('status')):>5} {r.get('ms', 0):>6}ms "
              f"{r.get('first200', '')[:85]!r}", flush=True)
        results.append(r)

    ws_results = []
    if not filters or any(f.startswith("ws_") for f in filters):
        try:
            ws_results = await asyncio.gather(*[ws_probe(*w, seconds=ws_seconds) for w in WS_PROBES])
        except Exception as e:
            ws_results = [{"name": "ws_all", "error": f"{type(e).__name__}: {e}"}]
    for r in ws_results:
        print(f"{r.get('name'):30s} {str(r.get('status', 'ws')):>5} "
              f"events={r.get('events')} per_min={r.get('events_per_min')} "
              f"{str(r.get('error', ''))[:70]}", flush=True)
        results.append(r)

    merged = {}
    if os.path.exists(OUT):
        try:
            for r in json.load(open(OUT)).get("results", []):
                merged[r["name"]] = r
        except Exception:
            pass
    for r in results:
        merged[r["name"]] = r
    payload = {"probed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "results": list(merged.values())}
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False, default=str)
    print("WROTE", OUT, len(results), "total", len(merged))


if __name__ == "__main__":
    asyncio.run(main())
