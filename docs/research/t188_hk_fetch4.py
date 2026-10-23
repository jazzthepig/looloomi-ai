#!/usr/bin/env python3
"""T-188 第四轮：Paxos PAXG 资格条款 + HL 条款/受限国家（官方优先，第三方标注为次级）。"""
import os
import re
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TXTDIR = os.path.join(HERE, "t188_hk_text")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


def grab(url, timeout=35):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def flat(s):
    return re.sub(r"\s+", " ", s)


def ctx(text, kw, before=300, after=800, limit=2):
    for m in list(re.finditer(kw, text, re.I))[:limit]:
        i = m.start()
        yield flat(text[max(0, i - before):i + after])


def main():
    os.makedirs(TXTDIR, exist_ok=True)

    # --- A. PAXG TC: Customer 定义 / 谁可以买 / 制裁限制 ---
    print("### A. PAXOS PAX GOLD TC — customer / eligibility")
    t = flat(open(os.path.join(TXTDIR, "paxos_paxg_tc.txt"),
                   encoding="utf-8", errors="replace").read())
    for kw in (r'"Customer" means', r"sanction", r"Verified Customer",
               r"may refuse to issue", r"Paxos Global serves as a reseller"):
        for frag in ctx(t, kw, limit=1):
            print(f"[{kw}] {frag[:520]}")
            print("---")

    # --- B. HL 条款：试若干数据端点 ---
    print("### B. HYPERLIQUID official terms fetch attempts")
    cands = [
        ("hl_terms_api", "https://app.hyperliquid.xyz/terms?raw=1"),
        ("hl_legal_json", "https://api.hyperliquid.xyz/info"),
        ("hl_legal_page", "https://www.hyperliquid.xyz/terms"),
        ("hl_legal_page2", "https://hyperliquid.xyz/terms-of-use"),
        ("hl_docs_terms_md", "https://hyperliquid.gitbook.io/hyperliquid-docs/legal/terms-of-use.md"),
        ("hl_docs_glossary", "https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-3-builder-deployed-perpetuals.md"),
    ]
    for key, url in cands:
        try:
            raw = grab(url)
            txt = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
            txt = re.sub(r"<[^>]+>", " ", txt)
            txt = flat(txt)
            hk = txt.lower().count("hong kong")
            rj = txt.count("Restricted Jurisdiction")
            print(f"[{key}] len={len(txt)} HK={hk} RJ={rj} url={url[:60]}")
            if hk or rj:
                open(os.path.join(TXTDIR, f"{key}.txt"), "w").write(txt)
                for frag in ctx(txt, r"Hong Kong|Restricted Jurisdiction", limit=2):
                    print("   ", frag[:420])
        except Exception as e:  # noqa: BLE001
            print(f"[{key}] ERR {str(e)[:70]}")

    # --- C. 次级来源：第三方受限国家清单（明确标注非官方） ---
    print("### C. SECONDARY (non-issuer) HL restricted-country lists")
    for key, url in [("hl_datawallet", "https://www.datawallet.com/crypto/hyperliquid-supported-and-restricted-countries"),
                     ("hl_coinperps", "https://www.coinperps.com/learn/hyperliquid-restricted-countries")]:
        try:
            raw = grab(url)
            txt = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
            txt = re.sub(r"<style.*?</style>", " ", txt, flags=re.S | re.I)
            txt = re.sub(r"<[^>]+>", " ", txt)
            txt = flat(txt)
            open(os.path.join(TXTDIR, f"{key}.txt"), "w").write(txt)
            print(f"[{key}] len={len(txt)} HK={txt.lower().count('hong kong')}")
            for frag in ctx(txt, r"Hong Kong", limit=2):
                print("   ", frag[:400])
        except Exception as e:  # noqa: BLE001
            print(f"[{key}] ERR {str(e)[:70]}")


if __name__ == "__main__":
    main()
