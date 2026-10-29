#!/usr/bin/env python3
"""T-210 出处抓取:把报告要引的每一句原文抓下来,连 URL 与取数时刻一起存档。

只读 GET 公开页面。不注册、不下单、不写库。
输出:t210_cites.json(同目录)—— report 里的每条引文都能在这里核到 URL + 时间戳。
"""
import datetime
import html
import json
import os
import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

PAGES = [
    ("paxos_paxg_terms", "https://www.paxos.com/terms-and-conditions/pax-gold-terms-conditions",
     ["verified Customers", "minimum of 430", "storage fee", "freeze", "seize", "withdraw", "OCC"]),
    ("tether_terms", "https://tether.to/en/legal/",
     ["Prohibited Person", "Prohibited Jurisdiction", "Sanctioned Person", "redemption", "freeze"]),
    ("tether_gold", "https://tether.to/en/gold/",
     ["gold", "XAUT", "redeem", "vault", "Tether Gold", "fee"]),
    ("ondo_stocks_eligibility", "https://docs.ondo.finance/ondo-stocks/eligibility.md",
     ["United States", "Hong Kong", "Professional Investor", "Prohibited Persons", "8 million"]),
    ("ondo_stocks_invest_redeem", "https://docs.ondo.finance/ondo-stocks/investing-and-redeeming.md",
     ["minimum", "redeem", "redemption", "burn", "fee", "settlement", "NAV"]),
    ("ondo_stocks_fees", "https://docs.ondo.finance/ondo-stocks/fees-and-taxes.md",
     ["fee", "spread", "commission", "management"]),
    ("ondo_stocks_transferability", "https://docs.ondo.finance/ondo-stocks/transferability.md",
     ["transfer", "wallet", "restricted", "blockchain"]),
    ("ondo_stocks_secondary", "https://docs.ondo.finance/ondo-stocks/secondary-market-restrictions.md",
     ["secondary", "transfer", "resell", "restriction", "trading"]),
    ("ondo_ousg_eligibility", "https://docs.ondo.finance/qualified-access-products/ousg/eligibility-and-onboarding.md",
     ["Qualified-Access", "net worth", "5M", "25M", "redeem", "transfer"]),
    ("xstocks_legal", "https://docs.xstocks.fi/docs/product-legal-overview",
     ["not marketed", "U.S. Persons", "Jersey", "FMA", "Security Agent", "collateral"]),
    ("xstocks_llms", "https://docs.xstocks.fi/llms.txt", ["redemption", "minting", "fee", "eligibility"]),
    ("circle_usdc_terms", "https://www.circle.com/legal/usdc-terms",
     ["Restricted Person", "Blocked Addresses", "supported jurisdictions", "not reversible", "freeze"]),
    ("kraken_xstocks", "https://www.kraken.com/legal/xstocks",
     ["United States", "eligible", "KYC", "minimum investment", "jurisdiction", "redemption", "not available"]),
    ("binance_spot_fees", "https://www.binance.com/en/fee/schedule",
     ["maker", "taker", "Spot", "0.1000%", "0.0750%"]),
    ("kraken_fees", "https://www.kraken.com/features/fee-schedule",
     ["maker", "taker", "0.26%", "0.16%"]),
    ("okx_fees", "https://www.okx.com/help/okx-trade-fees",
     ["maker", "taker", "0.10%", "0.08%"]),
    ("coinbase_fees", "https://help.coinbase.com/en/coinbase/trading-and-funding/fees",
     ["maker", "taker", "0.40%", "0.60%", "0.50%"]),
    ("hashkey_ousg", "https://support.hashkey.com/hc/en-gb/articles/60100192600985-HashKey-Earn-Channel-Launches-Ondo-Short-Term-U-S-Treasuries-Treasuries-Fund-OUSG",
     ["OUSG", "minimum", "fee", "redeem", "Hong Kong", "eligible"]),
    ("dinari", "https://docs.dinari.com/",
     ["United States", "eligible", "tokenized", "KYC", "minimum", "custody"]),
    # ---- 2026-10-29 lane-b 补充:腿的候选清单、托管原文、香港限制 ----
    ("ondo_stocks_overview", "https://docs.ondo.finance/ondo-stocks/overview.md",
     ["SPY", "SPDR", "S&P 500", "token", "NAV", "Ondo Global Markets", "tokenized"]),
    ("ondo_stocks_assets", "https://docs.ondo.finance/ondo-stocks/assets.md",
     ["SPY", "ticker", "symbol", "issuer", "CUSIP", "eligible"]),
    ("ondo_usdy_overview", "https://docs.ondo.finance/usdy/overview.md",
     ["USDY", "T-bill", "Treasury", "redemption", "minimum", "eligible", "Ondo"]),
    ("ondo_usdy_eligibility", "https://docs.ondo.finance/usdy/eligibility-and-onboarding.md",
     ["United States", "Hong Kong", "eligible", "Prohibited", "minimum", "KYC"]),
    ("xstocks_products", "https://xstocks.com/products",
     ["SPY", "SPYX", "S&P 500", "fee", "xStock", "Backed"]),
    ("xstocks_faq", "https://docs.xstocks.fi/docs/faq",
     ["redemption", "fee", "custody", "SPY", "broker", "eligible"]),
    ("paxos_gold_faq", "https://gold.paxos.com/faq",
     ["vault", "custod", "allocated", "buy", "redeem", "fee", "minimum"]),
    ("paxos_paxg_faq", "https://www.paxos.com/pax-gold/faq",
     ["vault", "custod", "allocated", "redeem", "fee", "KYC", "verified"]),
    ("tether_gold_faq", "https://tether.to/en/gold/",
     ["vault", "redeem", "fee", "Tether Gold", "XAUT", "gold bars", "Switzerland"]),
    ("dinari_tokens", "https://docs.dinari.com/tokenized-stocks",
     ["SPY", "Arbitrum", "ticker", "eligible", "minimum", "redemption"]),
    ("sfc_va_retail", "https://www.sfc.hk/en/Regulatory-functions/Intermediaries/Virtual-asset-trading-platforms",
     ["licen", "retail", "virtual asset", "Hong Kong", "professional investor"]),
    ("sfc_va_consult", "https://www.sfc.hk/en/News-and-announcements/Policy-statements-and-announcements/Consultation-conclusions-on-the-regulatory-regime-for-virtual-asset-trading-platforms-and-dealing-in-virtual-assets",
     ["retail", "professional investor", "licensed", "virtual asset", "Hong Kong"]),
    ("kraken_ousg", "https://www.kraken.com/legal/ousg",
     ["OUSG", "eligible", "KYC", "minimum", "redemption", "jurisdiction"]),
    ("circle_usdc_reserve", "https://www.circle.com/transparency",
     ["reserve", "USDC", "cash", "custodian", "BofA"]),
]


def to_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<(br|/p|/div|/li|/tr|/h[1-6])[^>]*>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\xa0]+", " ", raw)
    raw = re.sub(r" *\n *", "\n", raw)
    return re.sub(r"\n{2,}", "\n", raw).strip()


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "ignore")


def main():
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    out = {"fetched_at_utc": ts, "pages": {}}
    for key, url, kws in PAGES:
        rec = {"url": url, "keywords": kws}
        try:
            txt = to_text(fetch(url))
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"
            out["pages"][key] = rec
            print(key, "ERR", rec["error"][:90])
            continue
        rec["chars"] = len(txt)
        lines = txt.split("\n")
        quotes = []
        seen = set()
        for i, line in enumerate(lines):
            low = line.lower()
            for kw in kws:
                if kw.lower() in low:
                    s = line.strip()
                    if 40 < len(s) < 1400 and s not in seen:
                        seen.add(s)
                        quotes.append({"kw": kw, "line_no": i, "text": s[:1200]})
                    break
            if len(quotes) >= 26:
                break
        rec["quotes"] = quotes
        out["pages"][key] = rec
        print(key, "OK chars", len(txt), "quotes", len(quotes))

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t210_cites.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print("WROTE", path, "at", ts)


if __name__ == "__main__":
    main()
