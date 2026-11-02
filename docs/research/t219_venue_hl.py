"""T-219 step 4d: HL spot pairs + order books for rail tokens; HIP-3 xyz dex coverage.

Fix: spotMeta universe pairs reference tokens by INDEX (not tokenId).
"""
import json, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)", "Content-Type": "application/json"}


def post_info(payload):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(payload).encode(),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]

meta = post_info({"type": "spotMetaAndAssetCtxs"})
smeta, sctx = meta[0], meta[1]
tokens = smeta["tokens"]
universe = smeta["universe"]
print("tokens", len(tokens), "pairs", len(universe), "ctxs", len(sctx))
print("sample pair:", json.dumps(universe[0])[:200], " sample ctx:", json.dumps(sctx[0])[:200])

rail_idx = {}
for t in tokens:
    nm = (t.get("name") or "").upper()
    if nm in RAIL:
        rail_idx[t["index"]] = (nm, t)

print("\n== HL SPOT: rail tokens -> pairs / market state / order book ==")
for idx, (nm, t) in sorted(rail_idx.items(), key=lambda kv: kv[1][0]):
    pairs = [p for p in universe if idx in (p.get("tokens") or [])]
    print("  %-5s idx=%-4s tokenId=%s szDec=%s  pairs=%s"
          % (nm, idx, t.get("tokenId"), t.get("szDecimals"), [p.get("name") for p in pairs]))
    for p in pairs:
        ci = p.get("index")
        c = sctx[ci] if ci is not None and ci < len(sctx) else {}
        print("      ctx[%s] name=%s mark=%s mid=%s prevDay=%s vol24=%s oi=%s"
              % (ci, p.get("name"), c.get("markPx"), c.get("midPx"), c.get("prevDayPx"),
                 c.get("dayNtlVlm"), (c.get("openInterest") or {}).get("oi")))
        try:
            bk = post_info({"type": "l2Book", "coin": p.get("name")})
        except Exception as e:
            print("      l2Book ERR", str(e)[:90])
            continue
        lv = bk.get("levels", [[], []])
        bids, asks = lv[0], lv[1]
        mid = (float(bids[0]["px"]) + float(asks[0]["px"])) / 2 if bids and asks else None
        def d(side):
            if mid is None:
                return 0.0, 0
            tot, n = 0.0, 0
            for x in side:
                px, sz = float(x["px"]), float(x["sz"])
                if abs(px / mid - 1.0) <= 0.01:
                    tot += px * sz
                    n += 1
            return tot, n
        bd, bn = d(bids)
        ad, an = d(asks)
        print("      book mid=%s  bid<=1%% $%s (%d lv)  ask<=1%% $%s (%d lv)  raw %d/%d"
              % ("%.4f" % mid if mid else "-", "%.0f" % bd, bn, "%.0f" % ad, an, len(bids), len(asks)))
