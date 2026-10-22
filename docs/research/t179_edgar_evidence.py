"""T-179 evidence fetch — SEC EDGAR,**只进报告,不入库、不进任何计算**(T-179 卡 / 规则 3b)。

拉 dei:EntityCommonStockSharesOutstanding(申报封面股数),按申报日列出
窗口内(2025-09-01 之后)每一个申报日的股数与申报号,与 world50_mcap_weekly.shares
的台阶逐周对齐。

SEC 要求:带 User-Agent,每秒 ≤ 5 次请求。
"""
from __future__ import annotations

import json
import time
import urllib.request

UA = "CometCloud research (seth@looloomi.ai; institutional research contact)"
CIK_TICKERS = "https://www.sec.gov/files/company_tickers.json"
CONCEPT = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/dei/EntityCommonStockSharesOutstanding.json"

TICKERS = [
    "TSLA", "PANW", "INTC", "CVX", "UL", "CRM", "WELL", "TTE", "MPC", "VLO",
    "BKNG", "ADBE", "STX", "ORCL", "T", "WFC", "BAC", "DELL",
    "VZ", "CMCSA", "MO",  # 卡上点名要复核的三家低变化
]

_last = [0.0]


def get(url: str, timeout: int = 60) -> dict:
    gap = time.time() - _last[0]
    if gap < 0.22:            # ≤ 5 req/s
        time.sleep(0.22 - gap)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    import gzip
    import io
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    _last[0] = time.time()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    return json.loads(raw.decode())


def main() -> None:
    idx = get(CIK_TICKERS)
    by_tk = {}
    for v in idx.values():
        by_tk.setdefault(v["ticker"].upper(), []).append((v["cik_str"], v["title"]))

    out = {}
    for t in TICKERS:
        cands = by_tk.get(t.upper(), [])
        if not cands:
            out[t] = {"error": "no CIK"}
            continue
        cik, title = cands[0]
        try:
            j = get(CONCEPT.format(cik=cik))
        except Exception as e:                      # noqa: BLE001
            out[t] = {"cik": cik, "title": title, "error": str(e)}
            continue
        rows = []
        for unit, facts in j.get("units", {}).items():
            for f in facts:
                end = f.get("end", "")
                if end >= "2025-09-01":
                    rows.append(
                        {
                            "end": end, "val": f.get("val"), "unit": unit,
                            "form": f.get("form"), "filed": f.get("filed"),
                            "accn": f.get("accn"), "fy": f.get("fy"), "fp": f.get("fp"),
                        }
                    )
        rows.sort(key=lambda r: (r["end"], r["filed"] or ""))
        out[t] = {"cik": cik, "title": title, "n": len(rows), "facts": rows}
        print(t, cik, title, len(rows))
        time.sleep(0.25)

    with open("/Volumes/CometCloudAI/cometcloud-local/research/t179/edgar_entity_shares.json", "w") as f:
        json.dump(out, f, indent=1)
    print("written")


if __name__ == "__main__":
    main()