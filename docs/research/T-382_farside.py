#!/usr/bin/env python3
"""T-382 (1) v2: Farside ETH deep probe.

Fixes v1's two gaps:
  * pagination verdict must be read off the TABLE's daily rows (dates are
    "26 Oct 2026", not ISO -- v1's ISO token scan read 0 and was useless);
  * the table footnote was truncated in v1 and it points at an "alternative
    table with all the daily ..." -- fetch it in full and follow its link.

Adds: POST admin-ajax.php with the page's own action names + a candidate
list, and the WP REST routes, to test whether history exists behind a call
the free page does not make by itself.

Writes docs/research/T-382_farside_results.json (overwrites v1 output).
"""
import datetime
import hashlib
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "T-382_farside_results.json")
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}
DAY_ROW = re.compile(r"^\d{1,2} [A-Z][a-z]{2} 20\d\d$")
MON = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
       "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def http(url, data=None):
    h = dict(UA)
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:
        return -1, str(exc)


def strip_tags(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def daily_rows(page):
    """Return (first_date, last_date, n_daily_rows, header) of the ETH table."""
    tables = re.findall(r"<table[^>]*>.*?</table>", page, re.S)
    for t in tables:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)
        cells = [[strip_tags(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>",
                                                   r, re.S)] for r in rows]
        days = []
        for r in cells:
            if r and DAY_ROW.match(r[0]):
                d = r[0].split()
                days.append("%s-%02d-%02d" % (d[2], MON[d[1]], int(d[0])))
        if days:
            header = None
            for r in cells:
                if "ETHA" in r:
                    header = r
                    break
            return days[0], days[-1], len(days), header
    return None, None, 0, None


def main():
    res = {"probed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    status, page = http("https://farside.co.uk/eth/")
    res["page_status"] = status
    res["page_len"] = len(page)
    res["page_first200"] = page[:200]
    first, last, ndays, header = daily_rows(page)
    res["base_table"] = {"first_daily": first, "last_daily": last,
                         "n_daily_rows": ndays, "header": header}

    # --- table footnote, in full, with the links inside it ---------------
    idx = page.find("Note: The above table")
    frag = page[max(0, idx - 300): idx + 2500]
    res["footnote_html"] = frag[:2600]
    res["footnote_text"] = strip_tags(frag)[:900]
    res["footnote_links"] = [
        {"href": h, "text": strip_tags(t)}
        for h, t in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', frag, re.S)
    ]
    res["page_internal_links"] = sorted(
        {m.replace("https://farside.co.uk", "")
         for m in re.findall(r'href="(https://farside\.co\.uk/[^"#?]*)"', page)}
    )

    # --- the footnote's "all the daily flow data" page --------------------
    alt = {}
    for path in ("/ethereum-etf-flow-all-data/",):
        st, body = http("https://farside.co.uk" + path)
        f2, l2, n2, h2 = daily_rows(body)
        alt[path] = {"status": st, "len": len(body), "first_daily": f2,
                     "last_daily": l2, "n_daily_rows": n2, "header": h2,
                     "sha8": hashlib.sha256(body.encode()).hexdigest()[:8]}
        for q in ("?page=2", "?paged=2", "?page=3", "?page=12"):
            st2, body2 = http("https://farside.co.uk" + path + q)
            f3, l3, n3, _ = daily_rows(body2)
            alt[path + q] = {"status": st2, "len": len(body2),
                             "first_daily": f3, "last_daily": l3,
                             "n_daily_rows": n3}
    res["alt_table"] = alt

    # --- WP REST index: any custom route that carries the flows? ---------
    st, wpx = http("https://farside.co.uk/wp-json/")
    routes = sorted(set(re.findall(r'"/([^"]*(?:etf|flow|farside|chart)[^"]*)"',
                                   wpx, re.I)))
    res["wp_json_routes_etf"] = routes[:60]
    res["wp_json_len"] = len(wpx)

    # --- pagination verdict, read off the table's daily rows -------------
    probes = {}
    for q in ("", "?page=2", "?paged=2", "?page=3", "?page=12", "?fund=all",
              "?table=2", "?start=2024-07-23", "?from=2024-07-23",
              "?date=2024-07-23", "?year=2024", "?month=7", "?all=1",
              "?format=table", "?days=1000"):
        st, body = http("https://farside.co.uk/eth/" + q)
        f2, l2, n2, _ = daily_rows(body)
        probes[q or "(base)"] = {
            "status": st, "len": len(body),
            "sha8": hashlib.sha256(body.encode()).hexdigest()[:8],
            "first_daily": f2, "last_daily": l2, "n_daily_rows": n2,
        }
    res["pagination_probes"] = probes
    res["pagination_verdict"] = (
        "no parameter exposed a daily row older than the base table"
        if all(p["first_daily"] == probes["(base)"]["first_daily"]
               for p in probes.values() if p["first_daily"])
        else "a parameter DID change the earliest daily row -- inspect pagination_probes"
    )

    # --- admin-ajax, GET and POST ----------------------------------------
    actions = set()
    for pat in (r"""['"]action['"]\s*:\s*['"]([A-Za-z0-9_\-]+)['"]""",
                r"""action\s*[:=]\s*['"]([A-Za-z0-9_\-]+)['"]""",
                r"""admin-ajax\.php[^'"]*?['"]action['"]\s*[:=]\s*['"]([A-Za-z0-9_\-]+)['"]"""):
        for m in re.finditer(pat, page):
            actions.add(m.group(1))
    candidates = sorted(actions | {
        "etf_flows", "eth_table", "farside_eth", "farside_table",
        "get_etf_table", "load_more", "table_pagination", "get_table",
        "eth_flows", "etf_table_data", "fund_flows", "load_table",
        "get_more_rows", "get_historical"})
    ajax = {}
    for act in candidates:
        row = {}
        for method in ("GET", "POST"):
            url = ("https://farside.co.uk/wp-admin/admin-ajax.php?action=" + act
                   if method == "GET" else
                   "https://farside.co.uk/wp-admin/admin-ajax.php")
            st, body = http(url, data={"action": act} if method == "POST" else None)
            f2, l2, n2, _ = daily_rows(body)
            row[method] = {
                "status": st, "len": len(body), "first200": body[:200],
                "n_daily_rows": n2, "first_daily": f2, "last_daily": l2,
            }
        ajax[act] = row
    res["admin_ajax"] = ajax

    # --- WP REST routes --------------------------------------------------
    rest = {}
    for path in ("/wp-json/", "/wp-json/wp/v2/pages?slug=eth",
                 "/wp-json/wp/v2/pages?slug=ethereum", "/eth/?_format=json",
                 "/eth/feed/"):
        st, body = http("https://farside.co.uk" + path)
        rest[path] = {"status": st, "len": len(body), "first200": body[:200]}
    res["rest_routes"] = rest

    with open(OUT, "w") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print("wrote", OUT)
    print("base table:", res["base_table"]["first_daily"], "->",
          res["base_table"]["last_daily"], "n=", res["base_table"]["n_daily_rows"])
    print("header:", res["base_table"]["header"])
    print("footnote:", res["footnote_text"][:400])
    print("footnote links:", res["footnote_links"])
    print("ALT TABLE:", json.dumps(res["alt_table"], ensure_ascii=False)[:600])
    print("WP-JSON etf routes:", res["wp_json_routes_etf"][:25])
    for q, v in probes.items():
        print("  %-22s %s n=%s %s..%s sha=%s" % (q, v["status"], v["n_daily_rows"],
                                                   v["first_daily"], v["last_daily"], v["sha8"]))
    print("verdict:", res["pagination_verdict"])
    hit = False
    for act, row in ajax.items():
        for m, v in row.items():
            if v["status"] == 200 and v["n_daily_rows"]:
                print("  AJAX HIT", act, m, v["first_daily"], v["last_daily"])
                hit = True
    if not hit:
        print("  no admin-ajax action returned table rows")
    for p, v in rest.items():
        print("  REST", p, v["status"], v["len"])


if __name__ == "__main__":
    main()
