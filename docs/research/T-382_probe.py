#!/usr/bin/env python3
"""T-382 probes (read-only HTTP, no keys, no .env, no DB writes).

Three sections:
  A. Farside ETH  -- page content, table history depth, pagination/admin-ajax hunt,
                     robots.txt + licence/attribution text.
  B. Binance      -- same-host controls (fapi ping / ticker / depth / exchangeInfo vs
                     allForceOrders) to separate "whole host down" from "single endpoint 404".
  C. CoinMarketCap-- range=all / 1Y / 1M point counts + median interval + the
                     v[2]/v[0] == v[4] field-order identity.

Writes docs/research/T-382_probe_results.json
"""
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "T-382_probe_results.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
RES = {"probed_at_utc": datetime.now(timezone.utc).isoformat()}


def get(url, timeout=40, headers=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(6_000_000).decode("utf-8", "replace")
            return r.status, body, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(4000).decode("utf-8", "replace"), dict(e.headers)
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e), {}


def first200(t):
    t = re.sub(r"\s+", " ", t or "")
    return t[:200]


# ----------------------------------------------------------------------------
# A. Farside ETH
# ----------------------------------------------------------------------------
def farside():
    out = {}
    st, html, hdr = get("https://farside.co.uk/eth/")
    out["page"] = {"url": "https://farside.co.uk/eth/", "status": st,
                   "len": len(html), "first200": first200(html),
                   "content_type": hdr.get("Content-Type", "")}

    # --- table structure -----------------------------------------------------
    tbl = re.findall(r"<table.*?</table>", html, re.S | re.I)
    out["n_tables"] = len(tbl)
    tables = []
    for t in tbl:
        rows = re.findall(r"<tr.*?</tr>", t, re.S | re.I)
        cells = [[re.sub(r"<[^>]+>", "", c).strip()
                  for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S | re.I)]
                 for r in rows]
        cells = [c for c in cells if any(x for x in c)]
        if not cells:
            continue
        # find the table that has a date-ish first column and many rows
        tables.append({"n_rows": len(cells), "header": cells[0][:16],
                       "first_row": cells[1][:16] if len(cells) > 1 else None,
                       "last_row": cells[-1][:16]})
    out["tables"] = tables

    # --- date extraction from the widest table -------------------------------
    dates = []
    for m in re.finditer(r"(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})", html):
        s = m.group(1)
        try:
            dates.append(datetime.strptime(s, "%d %b %Y").replace(tzinfo=timezone.utc))
        except ValueError:
            pass
    if dates:
        out["date_tokens"] = {"n": len(dates), "min": min(dates).strftime("%Y-%m-%d"),
                               "max": max(dates).strftime("%Y-%m-%d"),
                               "first5": [d.strftime("%Y-%m-%d") for d in dates[:5]],
                               "last5": [d.strftime("%Y-%m-%d") for d in dates[-5:]]}

    # --- pagination / admin-ajax hunt ----------------------------------------
    hints = {}
    for pat in ("admin-ajax", "ajaxurl", "wp-admin", "load more", "loadmore",
                "pagination", "data-page", "page=", "paged=", "fund_filter",
                "etf_fund", "view_more"):
        hits = [m.start() for m in re.finditer(re.escape(pat), html, re.I)]
        if hits:
            hints[pat] = len(hits)
    out["pagination_hints"] = hints
    if "admin-ajax" in html.lower():
        i = html.lower().find("admin-ajax")
        out["admin_ajax_excerpt"] = re.sub(r"\s+", " ", html[max(0, i - 200):i + 300])
    # script srcs (may carry the ajax logic)
    out["script_srcs"] = sorted(set(re.findall(r"<script[^>]+src=[\"']([^\"']+)", html, re.I)))[:40]

    # --- try pagination params on the page itself ---------------------------
    pg = {}
    base = "https://farside.co.uk/eth/"
    for q in ("?page=2", "?paged=2", "?page=3", "?paged=3", "?fund=all",
              "?page=2&fund=all", "?table=2"):
        s2, h2, _ = get(base + q)
        d2 = []
        for m in re.finditer(r"(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})", h2 or ""):
            try:
                d2.append(datetime.strptime(m.group(1), "%d %b %Y"))
            except ValueError:
                pass
        pg[q] = {"status": s2, "n_date_tokens": len(d2),
                 "min": min(d2).strftime("%Y-%m-%d") if d2 else None,
                 "max": max(d2).strftime("%Y-%m-%d") if d2 else None,
                 "same_as_base": (min(d2).strftime("%Y-%m-%d") if d2 else None)
                 == (min(dates).strftime("%Y-%m-%d") if dates else None)}
    out["page_param_try"] = pg

    # --- admin-ajax direct attempts -----------------------------------------
    aj = {}
    for act in ("farside_table", "eth_table", "get_etf_table", "farside_eth",
                "load_more", "etf_flows", "table_pagination"):
        u = "https://farside.co.uk/wp-admin/admin-ajax.php?action=%s&page=2" % act
        s3, b3, _ = get(u)
        aj["GET action=%s" % act] = {"status": s3, "first200": first200(b3)}
    out["admin_ajax_try"] = aj

    # --- robots.txt ---------------------------------------------------------
    s4, b4, _ = get("https://farside.co.uk/robots.txt")
    out["robots"] = {"status": s4, "first2000": (b4 or "")[:2000]}

    # --- footer links + terms candidates ------------------------------------
    links = sorted(set(re.findall(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                                  html, re.S | re.I)))
    out["links_with_terms"] = [{"href": h, "text": re.sub(r"\s+", " ", t)[:80]}
                                for h, t in links
                                if re.search(r"term|licen|attribut|disclaim|privacy|about|"
                                             r"contact|source|copyright|faq", h + t, re.I)][:30]
    out["n_links"] = len(links)

    terms = {}
    for path in ("/terms-and-conditions/", "/terms/", "/terms-of-use/", "/legal/",
                 "/disclaimer/", "/privacy-policy/", "/about/", "/faq/", "/",
                 "/contact/"):
        u = "https://farside.co.uk" + path
        s5, b5, _ = get(u)
        txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", b5 or "", flags=re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        terms[path] = {"status": s5, "len": len(b5 or ""), "text": txt[:1500]}
    out["terms_pages"] = terms

    # licence-ish sentences inside the main pages
    lic = []
    for path in ("/eth/", "/", "/terms-and-conditions/", "/terms/"):
        s6, b6, _ = get("https://farside.co.uk" + path)
        t6 = re.sub(r"<[^>]+>", " ", b6 or "")
        t6 = re.sub(r"\s+", " ", t6)
        for m in re.finditer(r"[^.]{0,180}(licen[cs]|attribut|redistribut|reproduc|"
                             r"scrap|crawl|spider|robots|not be used|personal data|"
                             r"copyright|source)[^.]{0,220}\.", t6, re.I):
            lic.append({"path": path, "sent": m.group(0).strip()[:400]})
    out["licence_sentences"] = lic[:40]

    # BTC page for depth comparison
    s7, b7, _ = get("https://farside.co.uk/btc/")
    d7 = []
    for m in re.finditer(r"(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})", b7 or ""):
        try:
            d7.append(datetime.strptime(m.group(1), "%d %b %Y"))
        except ValueError:
            pass
    out["btc_page"] = {"status": s7, "n_date_tokens": len(d7),
                       "min": min(d7).strftime("%Y-%m-%d") if d7 else None,
                       "max": max(d7).strftime("%Y-%m-%d") if d7 else None}
    RES["farside"] = out


# ----------------------------------------------------------------------------
# B. Binance same-host controls
# ----------------------------------------------------------------------------
def binance():
    out = {}
    cases = [
        ("fapi_ping", "https://fapi.binance.com/fapi/v1/ping"),
        ("fapi_ticker_price", "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT"),
        ("fapi_ticker_24hr", "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT"),
        ("fapi_depth", "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=5"),
        ("fapi_exchangeInfo", "https://fapi.binance.com/fapi/v1/exchangeInfo"),
        ("fapi_allForceOrders", "https://fapi.binance.com/fapi/v1/allForceOrders?symbol=BTCUSDT&limit=10"),
        ("fapi_forceOrders", "https://fapi.binance.com/fapi/v1/forceOrders?symbol=BTCUSDT&limit=10"),
        ("fapi_allForceOrders_nosym", "https://fapi.binance.com/fapi/v1/allForceOrders?limit=10"),
        ("fapi_premiumIndex", "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"),
        ("fapi_openInterest", "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT"),
        ("spot_ping", "https://api.binance.com/api/v3/ping"),
        ("spot_ticker_price", "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"),
        ("spot_time", "https://api.binance.com/api/v3/time"),
        ("fapi_root", "https://fapi.binance.com/"),
    ]
    for name, url in cases:
        st, body, hdr = get(url, timeout=25)
        rec = {"url": url, "status": st, "first200": first200(body),
               "content_type": hdr.get("Content-Type", ""), "len": len(body or "")}
        try:
            j = json.loads(body)
            if isinstance(j, dict):
                rec["json_keys"] = list(j.keys())[:10]
            elif isinstance(j, list):
                rec["json_list_len"] = len(j)
        except Exception:
            pass
        out[name] = rec
    ok = [k for k, v in out.items() if v["status"] == 200]
    out["_summary"] = {
        "n_200": len(ok),
        "ok_endpoints": ok,
        "force_status": out["fapi_allForceOrders"]["status"],
        "conclusion": ("single_endpoint_404" if len(ok) >= 3
                       else "host_unreachable" if len(ok) == 0
                       else "partial_host_failure"),
    }
    RES["binance"] = out


# ----------------------------------------------------------------------------
# C. CoinMarketCap ranges + v-field identity
# ----------------------------------------------------------------------------
CMC_IDS = {"BTC": 1, "ETH": 1027, "SOL": 5426}


def cmc_chart(cid, rng):
    url = ("https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart"
           "?id=%s&range=%s" % (cid, rng))
    st, body, _ = get(url, timeout=40)
    if st != 200:
        return {"url": url, "status": st, "first200": first200(body)}
    j = json.loads(body)
    d = j.get("data", {})
    raw_pts = d.get("points") or []
    if isinstance(raw_pts, dict):
        pts = [{"ts": int(k), "v": v.get("v") if isinstance(v, dict) else v}
               for k, v in raw_pts.items()]
        pts.sort(key=lambda p: p["ts"])
    else:
        pts = raw_pts
    rec = {"url": url, "status": st, "n_points": len(pts),
           "top_keys": list(d.keys())[:12]}
    if pts:
        ts = [p["ts"] for p in pts]
        rec["first_ts"] = ts[0]
        rec["last_ts"] = ts[-1]
        # CMC data-api ts is in SECONDS (verified: 1.7e9 -> 2026-11-14)
        rec["first_date"] = datetime.fromtimestamp(ts[0], timezone.utc).strftime("%Y-%m-%d")
        rec["last_date"] = datetime.fromtimestamp(ts[-1], timezone.utc).strftime("%Y-%m-%d")
        gaps = [(ts[i + 1] - ts[i]) / 86400.0 for i in range(len(ts) - 1)]
        if gaps:
            rec["median_gap_days"] = round(statistics.median(gaps), 4)
            rec["min_gap_days"] = round(min(gaps), 4)
            rec["max_gap_days"] = round(max(gaps), 4)
            rec["n_gap_le_1_5d"] = sum(1 for g in gaps if g <= 1.5)
            rec["n_distinct_dates"] = len(set(
                datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d") for t in ts))
            rec["median_pts_per_day"] = round(len(ts) / max(rec["n_distinct_dates"], 1), 3)
        # v-field identity:  v[2]/v[0]  vs  v[4]   and  vs  v[4]/v[3]
        rel_2_0, rel_43, rel_1_0, samples, v3s = [], [], [], [], []
        for p in pts:
            v = p.get("v")
            if not isinstance(v, list) or len(v) < 5:
                continue
            try:
                v0, v1, v2, v3, v4 = [float(x) for x in v[:5]]
            except Exception:
                continue
            if v0 <= 0 or v4 <= 0:
                continue
            supply = v2 / v0
            rel_2_0.append(abs(supply - v4) / v4)
            rel_1_0.append(abs(v1 / v0 - v4) / v4)
            if v3 > 0:
                rel_43.append(abs(supply - v4 / v3) / max(v4 / v3, 1e-12))
            v3s.append(v3)
            if len(samples) < 3:
                samples.append({"date": datetime.fromtimestamp(p["ts"], timezone.utc)
                                .strftime("%Y-%m-%d"), "v": v[:6],
                                "v2_over_v0": supply})
        if rel_2_0:
            rec["identity_v2_over_v0_vs_v4"] = {
                "n": len(rel_2_0),
                "median_rel": float("%.6g" % statistics.median(rel_2_0)),
                "max_rel": float("%.6g" % max(rel_2_0)),
                "p95_rel": float("%.6g" % sorted(rel_2_0)[int(0.95 * (len(rel_2_0) - 1))]),
            }
            rec["alt_identity_v1_over_v0_vs_v4"] = {
                "median_rel": float("%.6g" % statistics.median(rel_1_0)),
                "max_rel": float("%.6g" % max(rel_1_0)),
            }
            if rel_43:
                rec["identity_v2_over_v0_vs_v4_over_v3"] = {
                    "n": len(rel_43),
                    "median_rel": float("%.6g" % statistics.median(rel_43)),
                    "max_rel": float("%.6g" % max(rel_43)),
                    "p95_rel": float("%.6g" % sorted(rel_43)[int(0.95 * (len(rel_43) - 1))]),
                }
            rec["v3_stats"] = {"min": min(v3s), "max": max(v3s),
                               "median": statistics.median(v3s)}
            rec["v_samples"] = samples
    return rec


def cmc():
    out = {}
    for sym, cid in CMC_IDS.items():
        out[sym] = {}
        for rng in ("all", "1Y", "1M"):
            out[sym][rng] = cmc_chart(cid, rng)
    RES["cmc"] = out


def farside_all():
    """Section D: the 'click here' full-history table linked from /eth/."""
    out = {}
    for path in ("/ethereum-etf-flow-all-data/", "/bitcoin-etf-flow-all-data/",
                 "/solana-etf-flow-all-data/", "/ethereum-etf-flow/",
                 "/bitcoin-etf-flow/"):
        u = "https://farside.co.uk" + path
        st, html, _ = get(u, timeout=60)
        rec = {"url": u, "status": st, "len": len(html or ""),
               "first200": first200(html)}
        if st == 200:
            tbls = re.findall(r"<table.*?</table>", html, re.S | re.I)
            rec["n_tables"] = len(tbls)
            if tbls:
                rows = re.findall(r"<tr.*?</tr>", tbls[0], re.S | re.I)

                def cells(r):
                    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
                            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r,
                                                re.S | re.I)]
                parsed = [cells(r) for r in rows]
                parsed = [c for c in parsed if any(x for x in c)]
                rec["n_rows"] = len(parsed)
                rec["header_rows"] = parsed[:4]
                rec["last_rows"] = parsed[-3:]
                dts = []
                for c in parsed:
                    if c and re.match(r"^\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}$", c[0] or ""):
                        try:
                            dts.append(datetime.strptime(c[0], "%d %b %Y"))
                        except ValueError:
                            pass
                if dts:
                    rec["n_daily_rows"] = len(dts)
                    rec["earliest"] = min(dts).strftime("%Y-%m-%d")
                    rec["latest"] = max(dts).strftime("%Y-%m-%d")
                    gaps = [(dts[i + 1] - dts[i]).days for i in range(len(dts) - 1)]
                    rec["median_gap_days"] = statistics.median(gaps) if gaps else None
                    rec["n_gap_gt_4d"] = sum(1 for g in gaps if g > 4)
            rec["n_ajax_action_refs"] = len(re.findall(r"admin-ajax\.php\?action", html, re.I))
            rec["n_loadmore_refs"] = len(re.findall(r"load more|loadmore", html, re.I))
            rec["csv_refs"] = re.findall(r'href="([^"]*(?:\.csv|download)[^"]*)"', html, re.I)[:5]
            i = html.find("Source: Farside")
            if i > 0:
                seg = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html[max(0, i - 1200):i + 1200]))
                rec["notes_excerpt"] = seg[-1400:]
        out[path] = rec
    # sitemap scan for other *-all-data pages
    s, sm = get("https://farside.co.uk/sitemap_index.xml")
    out["sitemap"] = {"status": s, "first300": first200(sm)}
    s2, sm2 = get("https://farside.co.uk/wp-sitemap.xml")
    out["wp_sitemap"] = {"status": s2, "len": len(sm2 or ""),
                         "all_data_urls": sorted(set(re.findall(
                             r"https://farside\.co\.uk/[a-z0-9\-]*all-data/[a-z0-9\-]*/?",
                             sm2 or "")))[:30]}
    RES["farside_all"] = out


if __name__ == "__main__":
    which = (sys.argv[1] if len(sys.argv) > 1 else
             os.environ.get("T382_SECTIONS", "ABC"))
    if "A" in which:
        farside()
    if "B" in which:
        binance()
    if "C" in which:
        cmc()
    if "D" in which:
        farside_all()
    merged = {}
    if os.path.exists(OUT):
        try:
            with open(OUT) as f:
                merged = json.load(f)
        except Exception:
            merged = {}
    merged.update(RES)
    with open(OUT, "w") as f:
        json.dump(merged, f, indent=1, sort_keys=True)
    print("wrote", OUT)
    for k in RES:
        print(" section:", k)
