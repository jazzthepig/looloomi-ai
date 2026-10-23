#!/usr/bin/env python3
"""T-188 第二轮：找 Restricted Countries / Tether Gold ToS / HL 条款的可读版本。

把候选 URL 逐个试，命中即存全文到 <私有数据根>/research/t188/hk_text/。
"""
import html
import os
import re
import subprocess
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
# 第三方条款原文与摘录留在私有数据根,不进公开仓库(2026-10-23 Seth 要求)
TEXT_ROOT = os.environ.get("T188_TEXT_ROOT", "/Volumes/CometCloudAI/cometcloud-local/research/t188")
TXTDIR = os.path.join(TEXT_ROOT, "hk_text")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/pdf,*/*"}

CANDIDATES = [
    ("backed_restricted", "https://assets.backed.fi/restricted-countries"),
    ("backed_restricted2", "https://assets.backed.fi/legal/restricted-countries"),
    ("backed_restricted3", "https://backed.fi/restricted-countries"),
    ("backed_onboarding", "https://assets.backed.fi/onboarding"),
    ("backed_notices", "https://assets.backed.fi/notices-to-investors"),
    ("tether_gold_tos_pdf", "https://gold.tether.to/legal/termsofservice.pdf"),
    ("tether_gold_whitepaper", "https://gold.tether.to/whitepaper.pdf"),
    ("tether_gold_tos_raw", "https://gold.tether.to/legal/termsofservice?lang=en"),
    ("tether_tos_page", "https://tether.to/en/legal/"),
    ("hl_terms_raw", "https://app.hyperliquid.xyz/terms?lang=en"),
    ("hl_hip3_docs", "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/hip-3"),
    ("hl_docs_root", "https://hyperliquid.gitbook.io/hyperliquid-docs/"),
    ("hl_docs_llms", "https://hyperliquid.gitbook.io/hyperliquid-docs/llms.txt"),
]


def fetch(url, timeout=35):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if raw[:4] == b"%PDF" or url.lower().endswith(".pdf"):
                tmp = os.path.join(TEXT_ROOT, "_t188_tmp2.pdf")
                with open(tmp, "wb") as f:
                    f.write(raw)
                txt = subprocess.run(["pdftotext", "-layout", tmp, "-"],
                                     capture_output=True, text=True, timeout=60).stdout
                os.remove(tmp)
                return txt, r.status, r.geturl()
            enc = r.headers.get_content_charset() or "utf-8"
            return raw.decode(enc, errors="replace"), r.status, r.geturl()
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


def main():
    os.makedirs(TXTDIR, exist_ok=True)
    for key, url in CANDIDATES:
        raw, status, final = fetch(url)
        text = to_text(raw) if raw else ""
        hk = len(re.findall(r"(?i)hong kong", text))
        if text:
            with open(os.path.join(TXTDIR, f"{key}.txt"), "w") as f:
                f.write(text)
        print(f"[{key}] status={status} chars={len(text)} HK_hits={hk} "
              f"final={final[:70]} {'<<' if hk else ''}")
    print("done")


if __name__ == "__main__":
    main()
