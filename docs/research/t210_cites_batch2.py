#!/usr/bin/env python3
"""T-210 出处第二批:修掉第一轮 404 的路径(Ondo USDY 实际在 general-access-products/ 下),
补上 OUSG 费用/投资/重要提示、SFC 持牌平台名单、HashKey Earn、Dinari、OKX/Coinbase 费率。

只读 GET 公开页面;不注册、不下单、不写库。写入 t210_cites.json(追加,不覆盖第一轮成功的条目)。
"""
import datetime
import importlib.util
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("t210_cites", os.path.join(HERE, "t210_cites.py"))
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

PAGES2 = [
    ("ondo_usdy_eligibility", "https://docs.ondo.finance/general-access-products/usdy/eligibility.md",
     ["United States", "Hong Kong", "eligible", "Prohibited", "minimum", "KYC", "net worth", "Professional"]),
    ("ondo_usdy_basics", "https://docs.ondo.finance/general-access-products/usdy/basics.md",
     ["USDY", "rebasing", "redeem", "transfer", "minimum", "eligible", "T-bill"]),
    ("ondo_usdy_important", "https://docs.ondo.finance/general-access-products/usdy/important-notes.md",
     ["redeem", "minimum", "transfer", "freeze", "blocked", "T+0", "fee", "smart contract"]),
    ("ondo_ousg_fees", "https://docs.ondo.finance/qualified-access-products/ousg/fees-and-taxes.md",
     ["fee", "redemption", "management", "expense", "0."]),
    ("ondo_ousg_investing", "https://docs.ondo.finance/qualified-access-products/ousg/investing.md",
     ["minimum", "redeem", "subscribe", "NAV", "settlement", "wallet"]),
    ("ondo_ousg_important", "https://docs.ondo.finance/qualified-access-products/ousg/important-notes.md",
     ["redeem", "freeze", "block", "transfer", "holder", "T+0", "custod"]),
    ("ondo_ousg_instant_limits", "https://docs.ondo.finance/qualified-access-products/ousg/instant-limits.md",
     ["limit", "instant", "redeem", "million"]),
    ("ondo_stocks_available_assets", "https://docs.ondo.finance/ondo-stocks/available-assets.md",
     ["SPY", "ticker", "USDon", "minimum", "asset", "CUSIP"]),
    ("sfc_va_list", "https://apps.sfc.hk/edistributionWeb/gateway/EN/va-sfc-list/",
     ["licence", "platform", "name", "HashKey", "OSL"]),
    ("hashkey_earn", "https://www.hashkey.com/earn",
     ["OUSG", "Treasury", "eligible", "Hong Kong", "minimum", "redeem", "APY"]),
    ("dinari_llms", "https://docs.dinari.com/llms.txt",
     ["SPY", "tokenized", "eligib", "minimum", "redemption", "Arbitrum", "United States", "custod"]),
    ("okx_fee_spot", "https://www.okx.com/trade-spot",
     ["maker", "taker", "fee", "0.1", "0.08"]),
    ("coinbase_fee_help", "https://help.coinbase.com/en/coinbase/trading-and-funding/advanced-fees",
     ["maker", "taker", "fee", "0.4", "0.6"]),
]


def grab(url, kws):
    last = ""
    for wait in (0, 4, 10):
        if wait:
            time.sleep(wait)
        try:
            txt = C.to_text(C.fetch(url))
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            continue
        rec = {"url": url, "keywords": kws, "chars": len(txt)}
        quotes, seen = [], set()
        for i, line in enumerate(txt.split("\n")):
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
        return rec
    return {"url": url, "keywords": kws, "error": last}


def main():
    path = os.path.join(HERE, "t210_cites.json")
    out = json.load(open(path))
    pages = out.setdefault("pages", {})
    for key, url, kws in PAGES2:
        rec = grab(url, kws)
        if rec.get("error") and (pages.get(key) or {}).get("quotes"):
            print(key, "still failing, keeping old")
            continue
        pages[key] = rec
        print(key, "->", "ERR " + rec["error"][:70] if rec.get("error")
              else f"OK chars={rec['chars']} quotes={len(rec['quotes'])}")
    out["batch2_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print("WROTE", path)


if __name__ == "__main__":
    main()
