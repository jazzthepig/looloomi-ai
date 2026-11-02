"""T-219 step 4e: (a) all HL spot markets touching rail tokens, (b) xstocks.fi canonical registry
check for the 4 HL tokenIds, (c) Solana xStocks depth per rail ticker (Jupiter + DexScreener)."""
import json, urllib.request, re

UA = {"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)", "Content-Type": "application/json"}
RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]
HL_TOKENIDS = {
    "COIN": "0x3e3a2bdcd2db04b313384e1c42eaa7ae",
    "CRCL": "0x8b92defb1901e6be9384d365c4f306a4",
    "HOOD": "0xe101753dcfea619a512111d3ae54a592",
    "MSTR": "0x9b00bd499ee10686ba795c86fa99d991",
}


def post_info(payload):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(payload).encode(),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def get_json(url):
    return json.loads(get(url))


print("########## (a) HL spot: every ctx whose coin maps to a rail token index")
meta = post_info({"type": "spotMetaAndAssetCtxs"})
smeta, sctx = meta[0], meta[1]
tokens = {t["index"]: t for t in smeta["tokens"]}
rail_idx = {i: (t.get("name") or "").upper() for i, t in tokens.items() if (t.get("name") or "").upper() in RAIL}
print("rail token indices:", rail_idx)
found = {}
for c in sctx:
    coin = c.get("coin") or ""
    m = re.match(r"^@(\d+)$", coin)
    if m and int(m.group(1)) in rail_idx:
        found[coin] = (rail_idx[int(m.group(1))], c)
    else:
        base = coin.split("/")[0]
        if base.upper() in RAIL:
            found[coin] = (base.upper(), c)
for coin, (nm, c) in sorted(found.items(), key=lambda kv: kv[1][0]):
    print("  %-6s %-10s mark=%s mid=%s prevDay=%s vol24=%s supply=%s"
          % (nm, coin, c.get("markPx"), c.get("midPx"), c.get("prevDayPx"), c.get("dayNtlVlm"), c.get("circulatingSupply")))
    try:
        bk = post_info({"type": "l2Book", "coin": coin})
        lv = bk.get("levels", [[], []])
        bids, asks = lv[0], lv[1]
        mid = (float(bids[0]["px"]) + float(asks[0]["px"])) / 2 if bids and asks else None
        def d(side):
            tot, n = 0.0, 0
            for x in side:
                px, sz = float(x["px"]), float(x["sz"])
                if mid and abs(px / mid - 1.0) <= 0.01:
                    tot += px * sz
                    n += 1
            return tot, n
        bd, bn = d(bids)
        ad, an = d(asks)
        print("      book mid=%s  bid<=1%% $%s (%d)  ask<=1%% $%s (%d)  raw %d/%d"
              % ("%.4f" % mid if mid else "-", "%.0f" % bd, bn, "%.0f" % ad, an, len(bids), len(asks)))
        if bids:
            print("      top bids:", [(b["px"], b["sz"]) for b in bids[:3]])
        if asks:
            print("      top asks:", [(a["px"], a["sz"]) for a in asks[:3]])
    except Exception as e:
        print("      l2Book ERR", str(e)[:90])

print("\n########## (b) xstocks.fi registry: do the 4 HL tokenIds appear?")
try:
    html = get("https://xstocks.fi/")
    print("html len", len(html))
    for nm, tid in HL_TOKENIDS.items():
        print("  %-5s tokenId %s -> in xstocks.fi page: %s" % (nm, tid, tid.lower() in html.lower()))
    for tk in RAIL:
        cnt = len(re.findall(r"\b" + tk + r"\b", html))
        print("  ticker %-6s occurrences on page: %d" % (tk, cnt))
    # try to pull an embedded JSON-ish mapping ticker -> addresses
    for m in list(re.finditer(r"0x[0-9a-fA-F]{40}", html))[:0]:
        pass
    addrs = set(a.lower() for a in re.findall(r"0x[0-9a-fA-F]{40}", html))
    print("  distinct 0x addresses on page:", len(addrs))
    for nm, tid in HL_TOKENIDS.items():
        print("  %-5s canonical page addr present: %s" % (nm, tid.lower() in addrs))
except Exception as e:
    print("  ERR", str(e)[:150])

print("\n########## (c) Solana xStocks depth per rail ticker")
for tk in RAIL:
    rows = []
    for q in (tk + "x", tk):
        try:
            d = get_json("https://api.jup.ag/tokens/v2/search?query=" + q)
        except Exception as e:
            d = []
        if isinstance(d, list):
            for t in d:
                sym = (t.get("symbol") or "")
                if sym.upper() in (tk.upper() + "X", tk.upper()):
                    rows.append(t)
        if rows:
            break
    if not rows:
        print("  %-6s -> no Jupiter token found (query %sx)" % (tk, tk))
        continue
    t = rows[0]
    print("  %-6s -> %s (%s) mint=%s usd=%s liquidity=$%s" %
          (tk, t.get("symbol"), t.get("name"), t.get("id"), t.get("usdPrice"),
           ("%.0f" % t["liquidity"]) if t.get("liquidity") else "0"))
    try:
        ds = get_json("https://api.dexscreener.com/latest/dex/tokens/" + t["id"])
        prs = ds.get("pairs") or []
        prs = [p for p in prs if p.get("chainId") == "solana"]
        prs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)
        for p in prs[:2]:
            liq = (p.get("liquidity") or {}).get("usd")
            print("      dex %-10s pair=%s liq=$%s vol24=$%s price=%s" %
                  (p.get("dexId"), p.get("pairAddress")[:12] + "..", ("%.0f" % liq) if liq else "-",
                   (p.get("volume") or {}).get("h24"), p.get("priceUsd")))
    except Exception as e:
        print("      dexscreener ERR", str(e)[:90])
