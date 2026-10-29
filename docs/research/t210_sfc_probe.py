#!/usr/bin/env python3
"""T-210 补充:探测 SFC 持牌虚拟资产交易平台名单的数据端点(只读 GET)。

背景:报告 §3 风险 7 的第一个缺口 —— SFC 的 VA 平台持牌名单页面是 JS 应用,
正文抓不到(只抓到 14 字符)。这里只探测公开端点,不写库、不注册。

用法: python3 t210_sfc_probe.py
输出: docs/research/t210_sfc.json
"""
import json
import urllib.error
import urllib.request

UA = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "*/*",
}

CANDIDATES = [
    "https://apps.sfc.hk/edistributionWeb/gateway/EN/va-sfc-list/",
    "https://apps.sfc.hk/edistributionWeb/api/va-sfc-list/list?lang=EN",
    "https://apps.sfc.hk/edistributionWeb/api/va-intermediaries/list?lang=EN",
    "https://apps.sfc.hk/edistributionWeb/api/va-list/list?lang=EN",
    "https://apps.sfc.hk/edistributionWeb/api/common/list?lang=EN",
    "https://www.sfc.hk/en/Regulatory-functions/Intermediaries/Virtual-asset-trading-platforms",
]


def probe(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            ctype = r.headers.get("Content-Type", "")
            return {"ok": True, "status": r.status, "ctype": ctype,
                    "bytes": len(body), "head": body[:400].decode("utf-8", "ignore")}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": "HTTP %d" % e.code, "head": e.read()[:200].decode("utf-8", "ignore")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:120])}


def main():
    out = {}
    for u in CANDIDATES:
        res = probe(u)
        out[u] = res
        print("%-6s %-8s %s" % ("OK" if res.get("ok") else "ERR",
                                 res.get("bytes", res.get("error", "")), u))
    with open("docs/research/t210_sfc.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("WROTE docs/research/t210_sfc.json")


if __name__ == "__main__":
    main()
