#!/usr/bin/env python3
"""T-188 打印轮：Backed 受限国家 / Ondo 二级市场限制与费用要点。"""
import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


def grab(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=35) as r:
        raw = r.read().decode("utf-8", errors="replace")
    t = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<(br|/p|/li|/h\d|/tr|/div)[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    import html
    t = html.unescape(t)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t)


def show(url, anchor, span=2500, skip=0):
    t = grab(url)
    i = t.find(anchor, skip)
    print("=" * 12, url.rsplit("/", 1)[-1], "len", len(t))
    if i < 0:
        print("  [anchor not found]", anchor)
        return
    print(t[i:i + span])


def main():
    show("https://assets.backed.fi/legal-documentation/restricted-countries",
         "Restricted Countries", 3200)
    print()
    show("https://assets.backed.fi/onboarding", "Onboarding", 2200)
    print()
    show("https://docs.ondo.finance/ondo-stocks/secondary-market-restrictions",
         "Secondary Market Restrictions", 2400, skip=2000)
    print()
    show("https://docs.ondo.finance/ondo-stocks/fees-and-taxes", "Fees", 2000, skip=2000)


if __name__ == "__main__":
    main()
