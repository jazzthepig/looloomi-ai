#!/usr/bin/env python3
"""T-210 probe18: 找 404 页面的正确 URL(ondo usdy 路径、OKX/Coinbase 费率、SFC、HashKey)。"""
import json
import re
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def head(url):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read(200000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)[:100]


print("== ondo docs llms.txt: 找 USDY / OUSG / stock 路径 ==")
for base in ("https://docs.ondo.finance/llms.txt", "https://docs.ondo.finance/llms-full.txt"):
    st, txt = head(base)
    print(" ", base, "->", st, len(txt))
    if st == 200 and txt:
        paths = sorted(set(re.findall(r"https://docs\.ondo\.finance/[^\s\)\]]+", txt)))
        for kw in ("usdy", "ousg", "stocks", "eligibility", "transfer", "secondary", "fees"):
            hit = [p for p in paths if kw in p.lower()][:6]
            print("   ", kw, "->", hit)
        break

print("== 备选费率 / 监管页 ==")
alts = [
    ("okx_fee_alt", "https://www.okx.com/help/understanding-fees"),
    ("okx_fee_spot", "https://www.okx.com/trade-spot"),
    ("coinbase_fee_alt", "https://help.coinbase.com/en/coinbase/trading-and-funding/fees-and-pricing"),
    ("coinbase_fee_alt2", "https://www.coinbase.com/pricing"),
    ("sfc_va_list", "https://apps.sfc.hk/edistributionWeb/gateway/EN/va-sfc-list/"),
    ("sfc_va_home", "https://www.sfc.hk/en/Regulatory-functions/Intermediaries/Virtual-asset-trading-platforms"),
    ("sfc_va_home2", "https://www.sfc.hk/en/Regulatory-functions/Intermediaries/Virtual-asset-trading-platforms/Regulatory-requirements-for-virtual-asset-trading-platform-operators"),
    ("hashkey_ousg_alt", "https://www.hashkey.com/earn"),
    ("hashkey_help_home", "https://support.hashkey.com/hc/en-gb"),
    ("dinari_alt", "https://docs.dinari.com/llms.txt"),
    ("dinari_home", "https://www.dinari.com/"),
]
for name, url in alts:
    st, txt = head(url)
    print(f"  {name:22s} {st} len={len(txt)}")
