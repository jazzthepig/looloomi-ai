#!/usr/bin/env python3
"""T-188 第三轮：Paxos 管辖语言 + HL 条款 JS bundle 挖掘。

只读；输出打印到 stdout（<60 行），全文落 docs/research/t188_hk_text/。
"""
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


def ctx(text, kw, before=400, after=900, limit=2):
    out = []
    for m in list(re.finditer(kw, text, re.I))[:limit]:
        i = m.start()
        out.append(re.sub(r"\s+", " ", text[max(0, i - before):i + after]))
    return out


def main():
    os.makedirs(TXTDIR, exist_ok=True)

    # --- A. Paxos General TC: 找管辖/资格措辞 ---
    p = os.path.join(TXTDIR, "paxos_general_tc.txt")
    t = open(p, encoding="utf-8", errors="replace").read()
    t1 = re.sub(r"\s+", " ", t)
    print("### PAXOS GENERAL TC — jurisdiction/eligibility wording")
    for kw in (r"state of residence", r"resident of", r"New York", r"not available",
               r"onboard", r"applicable law of your jurisdiction"):
        for frag in ctx(t1, kw, limit=1):
            print(f"[{kw}] {frag[:520]}")
            print("---")

    # --- B. Paxos AML/KYC Disclosure 页 ---
    try:
        u = "https://www.paxos.com/terms-and-conditions/aml-kyc-disclosure"
        raw = grab(u)
        raw1 = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
        raw1 = re.sub(r"<[^>]+>", " ", raw1)
        raw1 = re.sub(r"\s+", " ", raw1)
        open(os.path.join(TXTDIR, "paxos_aml.txt"), "w").write(raw1)
        print("### PAXOS AML/KYC page chars", len(raw1), "HK:", raw1.lower().count("hong kong"))
        for frag in ctx(raw1, "jurisdiction|resid", limit=2):
            print("  ", frag[:420])
    except Exception as e:  # noqa: BLE001
        print("aml page err", e)

    # --- C. HL terms: 抓 JS bundle 找条款文本 ---
    print("### HYPERLIQUID terms via JS bundles")
    try:
        h = grab("https://app.hyperliquid.xyz/terms")
        bundles = sorted(set(re.findall(r'src="([^"]+\.js)"', h)))
        print("bundles:", len(bundles))
        found = 0
        for u in bundles[:60]:
            url = u if u.startswith("http") else "https://app.hyperliquid.xyz" + u
            try:
                b = grab(url, timeout=45)
            except Exception:  # noqa: BLE001
                continue
            if "Restricted Jurisdiction" in b or "Hong Kong" in b:
                open(os.path.join(TXTDIR, "hl_terms_bundle.txt"), "w").write(b)
                found += 1
                print(f"  HIT {url} len={len(b)} "
                      f"HK={b.count('Hong Kong')} RJ={b.count('Restricted Jurisdiction')}")
                if found >= 2:
                    break
        if not found:
            print("  no bundle with 'Restricted Jurisdiction'/'Hong Kong'")
    except Exception as e:  # noqa: BLE001
        print("hl err", e)


if __name__ == "__main__":
    main()
