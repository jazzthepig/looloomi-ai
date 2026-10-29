#!/usr/bin/env python3
"""T-210:重抓第一轮失败的出处页(okx/coinbase 费率、HashKey 香港、Ondo USDY、SFC、Dinari、xStocks FAQ…)。

只读 GET 公开页面;不注册、不下单、不写库。失败页重试 3 次(退避),成功后并回 t210_cites.json。
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

RETRY_KEYS = ["okx_fees", "coinbase_fees", "hashkey_ousg", "ondo_stocks_assets",
              "ondo_usdy_overview", "ondo_usdy_eligibility", "xstocks_faq",
              "paxos_gold_faq", "paxos_paxg_faq", "dinari_tokens",
              "sfc_va_retail", "sfc_va_consult", "kraken_ousg"]


def grab(url, kws):
    last = ""
    for attempt, wait in enumerate((0, 5, 12, 25)):
        if wait:
            time.sleep(wait)
        try:
            txt = C.to_text(C.fetch(url))
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            continue
        rec = {"url": url, "keywords": kws, "chars": len(txt)}
        lines = txt.split("\n")
        quotes, seen = [], set()
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
        return rec
    return {"url": url, "keywords": kws, "error": last}


def main():
    path = os.path.join(HERE, "t210_cites.json")
    out = json.load(open(path))
    out.setdefault("pages", {})
    for key, url, kws in C.PAGES:
        if key not in RETRY_KEYS:
            continue
        rec = grab(url, kws)
        old = out["pages"].get(key) or {}
        if rec.get("error") and old.get("quotes"):
            print(key, "still failing, keeping old:", rec["error"][:70])
            continue
        out["pages"][key] = rec
        print(key, "->", "ERR " + rec["error"][:70] if rec.get("error")
              else f"OK chars={rec['chars']} quotes={len(rec['quotes'])}")
    out["retried_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print("WROTE", path)


if __name__ == "__main__":
    main()
