#!/usr/bin/env python3
"""T-188 第五轮：Backed 受限国家页 URL 发现 + HL 官方法律页 + Ondo 二级市场限制。"""
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


def ctx(text, kw, before=250, after=700, limit=2):
    for m in list(re.finditer(kw, text, re.I))[:limit]:
        i = m.start()
        yield flat(text[max(0, i - before):i + after])


def main():
    os.makedirs(TXTDIR, exist_ok=True)

    # --- A. assets.backed.fi 站点：发现 Restricted Countries 真实 URL ---
    print("### A. assets.backed.fi link discovery")
    try:
        raw = grab("https://assets.backed.fi/legal-documentation")
        links = sorted(set(re.findall(r'href="([^"]+)"', raw)))
        cand = [l for l in links if re.search(r"(?i)restrict|countr|juris|onboard|regulat|legal", l)]
        print("  candidates:", cand[:20])
        for l in cand[:12]:
            url = l if l.startswith("http") else "https://assets.backed.fi" + l
            try:
                t = grab(url)
                t1 = re.sub(r"<script.*?</script>", " ", t, flags=re.S | re.I)
                t1 = re.sub(r"<style.*?</style>", " ", t1, flags=re.S | re.I)
                t1 = flat(re.sub(r"<[^>]+>", " ", t1))
                hk = t1.lower().count("hong kong")
                print(f"  -> {url} len={len(t1)} HK={hk}")
                if hk:
                    name = re.sub(r"[^a-z0-9]+", "_", l.lower()).strip("_")[:40]
                    open(os.path.join(TXTDIR, f"backed_{name}.txt"), "w").write(t1)
                    for frag in ctx(t1, r"Hong Kong", limit=3):
                        print("     ", frag[:400])
            except Exception as e:  # noqa: BLE001
                print(f"  -> {url} ERR {str(e)[:60]}")
    except Exception as e:  # noqa: BLE001
        print("  discover err", e)

    # --- B. HL 官方法律页：llms.txt 里找 legal ---
    print("### B. HL docs llms.txt legal pages")
    try:
        ll = grab("https://hyperliquid.gitbook.io/hyperliquid-docs/llms.txt")
        legal = [l for l in ll.splitlines()
                 if re.search(r"(?i)legal|term|restrict|geo|block", l)]
        for l in legal[:12]:
            print("  ", l.strip()[:150])
        urls = re.findall(r"\((https://[^)]+)\)", "\n".join(legal))
        for u in urls[:8]:
            try:
                t = grab(u)
                t1 = flat(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", t, flags=re.S | re.I)))
                hk = t1.lower().count("hong kong")
                rj = t1.count("Restricted Jurisdiction")
                print(f"  -> {u[-70:]} len={len(t1)} HK={hk} RJ={rj}")
                if hk or rj:
                    open(os.path.join(TXTDIR, "hl_legal_found.txt"), "w").write(t1)
                    for frag in ctx(t1, r"Hong Kong|Restricted Jurisdiction", limit=2):
                        print("     ", frag[:400])
            except Exception as e:  # noqa: BLE001
                print(f"  -> {u[-60:]} ERR {str(e)[:60]}")
    except Exception as e:  # noqa: BLE001
        print("  llms err", e)

    # --- C. Ondo Secondary Market Restrictions ---
    print("### C. Ondo secondary-market restrictions / transferability")
    for key, u in [("ondo_smr", "https://docs.ondo.finance/ondo-stocks/secondary-market-restrictions"),
                   ("ondo_transfer", "https://docs.ondo.finance/ondo-stocks/transferability"),
                   ("ondo_fees", "https://docs.ondo.finance/ondo-stocks/fees-and-taxes")]:
        try:
            t = grab(u)
            t1 = flat(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", t, flags=re.S | re.I)))
            hk = t1.lower().count("hong kong")
            print(f"[{key}] len={len(t1)} HK={hk}")
            open(os.path.join(TXTDIR, f"{key}.txt"), "w").write(t1)
            for frag in ctx(t1, r"Hong Kong|secondary market", limit=2):
                print("   ", frag[:380])
        except Exception as e:  # noqa: BLE001
            print(f"[{key}] ERR {str(e)[:70]}")


if __name__ == "__main__":
    main()
