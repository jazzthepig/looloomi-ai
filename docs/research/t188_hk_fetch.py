#!/usr/bin/env python3
"""T-188 香港可得性取证：抓发行方 / 交易所条款原文，只抽取相关段落。

只读公开网页，不注册、不填表、不下单。
输出 <私有数据根>/research/t188/t188_hk_snippets.json + docs/research/t188_notes.md 的证据段。
条款原文与摘录不进公开仓库(2026-10-23 Seth 要求)。
"""
import json
import os
import re
import html
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
# 第三方条款原文与摘录留在私有数据根,不进公开仓库(2026-10-23 Seth 要求)
TEXT_ROOT = os.environ.get("T188_TEXT_ROOT", "/Volumes/CometCloudAI/cometcloud-local/research/t188")
OUT = os.path.join(TEXT_ROOT, "t188_hk_snippets.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

# (key, url, 关键词列表) —— 关键词命中的上下文段落会被抽出
# PDF 用 pdftotext 转文本再抽。
TARGETS = [
    ("paxos_paxg_tc", "https://www.paxos.com/terms-and-conditions/pax-gold-terms-conditions",
     ["Hong Kong", "Restricted", "jurisdiction", "United States", "eligible", "minimum"]),
    ("paxos_general_tc", "https://www.paxos.com/terms-and-conditions/general-terms-and-conditions",
     ["Hong Kong", "Restricted", "jurisdiction", "United States", "accredited", "KYC"]),
    ("paxos_paxg_page", "https://www.paxos.com/pax-gold",
     ["Hong Kong", "gold", "vault", "redemption", "minimum", "custod"]),
    ("tether_gold_tos", "https://gold.tether.to/legal/termsofservice",
     ["Hong Kong", "Restricted", "jurisdiction", "United States", "minimum", "redemption",
      "Tether International", "gold"]),
    ("tether_gold_faq", "https://gold.tether.to/faq",
     ["Hong Kong", "who can", "minimum", "redemption", "vault", "Tether International"]),
    ("ondo_stocks_faq", "https://ondo.finance/ondo-stocks",
     ["Hong Kong", "eligible", "accredited", "KYC", "jurisdiction", "United States",
      "non-U.S.", "mint", "redeem"]),
    ("ondo_eligibility", "https://docs.ondo.finance/ondo-stocks/eligibility",
     ["Hong Kong", "eligible", "accredited", "KYC", "jurisdiction", "United States",
      "professional", "minimum"]),
    ("xstocks_tos_pdf", "https://xstocks.fi/documents/xstocks-terms-of-service.pdf",
     ["Hong Kong", "Restricted", "jurisdiction", "United States", "KYC", "eligible",
      "backed", "segregated"]),
    ("xstocks_legal_overview", "https://docs.xstocks.fi/docs/product-legal-overview",
     ["Hong Kong", "Restricted", "jurisdiction", "United States", "eligible", "backed",
      "segregated", "prospectus"]),
    ("backed_assets_docs", "https://assets.backed.fi/legal-documentation",
     ["Hong Kong", "prospectus", "Malta", "BaFin", "segregated", "eligible"]),
    ("hl_terms", "https://app.hyperliquid.xyz/terms",
     ["Restricted", "blocked", "jurisdiction", "United States", "geographic", "Hong Kong",
      "prohibited", "sanction"]),
    ("hl_hip3", "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/hip-3",
     ["HIP-3", "USDC", "deploy", "builder", "margin"]),
]


def fetch(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            enc = r.headers.get_content_charset() or "utf-8"
            data = raw.decode(enc, errors="replace")
            if url.lower().endswith(".pdf") or raw[:4] == b"%PDF":
                tmp = os.path.join(TEXT_ROOT, "_t188_tmp.pdf")
                with open(tmp, "wb") as f:
                    f.write(raw)
                import subprocess
                txt = subprocess.run(["pdftotext", "-layout", tmp, "-"],
                                     capture_output=True, text=True, timeout=60).stdout
                os.remove(tmp)
                return txt, r.status, r.geturl()
            return data, r.status, r.geturl()
    except urllib.error.HTTPError as e:
        return "", e.code, url
    except Exception as e:  # noqa: BLE001
        return "", str(e), url


def to_text(raw):
    t = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t


def snippets(text, keywords, cap=6, width=300):
    out = []
    seen = set()
    for kw in keywords:
        for m in re.finditer(re.escape(kw), text, flags=re.I):
            s = max(0, m.start() - width)
            e = min(len(text), m.end() + width)
            frag = re.sub(r"\s+", " ", text[s:e]).strip()
            key = frag[:120]
            if key in seen:
                continue
            seen.add(key)
            out.append({"kw": kw, "frag": frag[:640]})
            if len(out) >= cap:
                return out
    return out


def main():
    res = {}
    txtdir = os.path.join(TEXT_ROOT, "hk_text")
    os.makedirs(txtdir, exist_ok=True)
    for key, url, kws in TARGETS:
        raw, status, final = fetch(url)
        text = to_text(raw) if raw else ""
        if text:
            with open(os.path.join(txtdir, f"{key}.txt"), "w") as f:
                f.write(text)
        res[key] = {
            "url": url,
            "final_url": final,
            "status": status,
            "n_chars": len(text),
            "head": text[:200].strip(),
            "snippets": snippets(text, kws) if text else [],
        }
        print(f"[{key}] status={status} chars={len(text)} snip={len(res[key]['snippets'])}")
        with open(OUT, "w") as f:
            json.dump(res, f, indent=1, ensure_ascii=False)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
