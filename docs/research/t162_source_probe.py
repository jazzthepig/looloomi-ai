#!/usr/bin/env python3
"""t162_source_probe.py — minimal read-only probes for style taxonomy v2.

Per task T-162 (lane-b), this only probes public Coingecko + DeFiLlama endpoints
plus a few head-only HTTP checks. No keys, no .env. Writes nothing to project DB.

Outputs JSON to /tmp/t162_probe_<tag>.json for use by the taxonomy doc.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

CACHE = Path("/tmp")


def http_get_json(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "t162-probe/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main():
    out = {}

    # 1) Coingecko categories (id-only, no auth)
    try:
        d = http_get_json("https://api.coingecko.com/api/v3/coins/categories/list")
        out["coingecko_categories_list_count"] = len(d)
        out["coingecko_categories_list"] = [c["category_id"] for c in d]
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        out["coingecko_categories_list_error"] = str(e)

    # 2) Coingecko categories (with included coins and count + market_cap)
    try:
        d = http_get_json("https://api.coingecko.com/api/v3/coins/categories")
        out["coingecko_categories_full_count"] = len(d)
        out["coingecko_categories_full"] = [
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "coins_count": c.get("coins_count"),
                "included_count": len(c.get("included") or []),
                "market_cap": c.get("market_cap"),
                "market_cap_change_24h": c.get("market_cap_change_24h"),
                "updated_at": c.get("updated_at"),
                "top_3_coins": [
                    x.get("symbol") for x in (c.get("top_3_coins_in_category") or [])
                ],
            }
            for c in d
        ]
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        out["coingecko_categories_full_error"] = str(e)

    # 3) DeFiLlama top-level categories
    try:
        d = http_get_json("https://api.llama.fi/categories")
        rows = d if isinstance(d, list) else d.get("categories", [])
        out["defillama_categories_count"] = len(rows)
        out["defillama_categories"] = [
            {
                "category": r.get("category"),
                "protocols_count": r.get("protocols_count"),
                "tvl_usd": r.get("tvl"),
            }
            for r in sorted(rows, key=lambda r: -float(r.get("tvl") or 0))
        ]
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        out["defillama_categories_error"] = str(e)

    # 4) DeFiLlama protocols (slim - count by category)
    try:
        d = http_get_json("https://api.llama.fi/protocols")
        out["defillama_protocols_count"] = len(d)
        from collections import Counter
        cat_counter = Counter()
        for p in d:
            cat = p.get("category")
            if cat:
                cat_counter[cat] += 1
        out["defillama_category_top_n"] = cat_counter.most_common(40)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        out["defillama_protocols_error"] = str(e)

    # 5) Per-category coin counts via /coins/markets?category=ID for v2 sectors
    v2_sector_ids = [
        "layer-1", "layer-2", "decentralized-perpetuals",
        "decentralized-exchange", "decentralized-derivatives",
        "lending-borrowing", "real-world-assets-rwa",
        "artificial-intelligence", "ai-agents", "ai-applications",
        "depin", "decentralized-finance-defi", "meme-token",
        "gaming", "oracle", "zero-knowledge-zk", "infrastructure",
        "stablecoins", "exchange-based-tokens",
    ]
    counts = {}
    for cid in v2_sector_ids:
        try:
            url = (
                "https://api.coingecko.com/api/v3/coins/markets"
                f"?vs_currency=usd&category={cid}&per_page=1&page=1"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "t162-probe/0.1"})
            with urllib.request.urlopen(req, timeout=15) as r:
                first_page = json.loads(r.read())
            # Use header pages available to count - try per_page=250
            url_big = (
                "https://api.coingecko.com/api/v3/coins/markets"
                f"?vs_currency=usd&category={cid}&per_page=250&page=1"
            )
            req2 = urllib.request.Request(url_big, headers={"User-Agent": "t162-probe/0.1"})
            with urllib.request.urlopen(req2, timeout=20) as r:
                big = json.loads(r.read())
            counts[cid] = {
                "first_page_n": len(first_page),
                "big_page_n": len(big),
                "sample_symbols": [x.get("symbol") for x in big[:8]],
            }
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            counts[cid] = {"error": str(e)}
    out["v2_sector_member_counts"] = counts

    # 6) Hyperliquid info (universe) via public POST endpoint
    try:
        url = "https://api.hyperliquid.xyz/info"
        body = '{"type":"meta"}'.encode()
        req = urllib.request.Request(
            url, data=body, headers={
                "User-Agent": "t162-probe/0.1",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            hl_meta = json.loads(r.read())
        if isinstance(hl_meta, dict) and "universe" in hl_meta:
            univ = hl_meta["universe"]
            out["hl_universe_count"] = len(univ)
            out["hl_sample_symbols"] = [
                f"{u.get('name')} (idx={u.get('index')}, szDecimals={u.get('szDecimals')})"
                for u in univ[:25]
            ]
            out["hl_perp_only_symbols"] = [
                u.get("name") for u in univ
                if not (u.get("name", "").endswith("USDC") or "USD" in (u.get("name") or ""))
            ][:30]
        else:
            out["hl_meta_keys"] = list(hl_meta.keys()) if isinstance(hl_meta, dict) else type(hl_meta).__name__
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        out["hl_error"] = str(e)

    out_path = CACHE / "t162_probe.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    print(f"wrote {out_path} (keys={list(out.keys())})")


if __name__ == "__main__":
    main()
