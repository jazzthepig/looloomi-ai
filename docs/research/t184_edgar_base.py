"""T-184 — ② 起点股数对申报封面:补拉 EDGAR dei:EntityCommonStockSharesOutstanding。

只进报告 / Mac 数据根,**不入库、不进 v2、不改表**(T-184 卡 acceptance 末句)。
T-179 的缓存(edgar_entity_shares.json)只留了 end >= 2025-09-01 的事实,
本轮要判的是 **base_date = 2025-10-17 当日可得的封面**,需要再往前一年的申报,
所以重拉一次,窗口放宽到 end >= 2024-06-01。

SEC 要求:带 User-Agent,每秒 ≤ 5 次请求。
"""
from __future__ import annotations

import gzip
import io
import json
import time
import urllib.request

UA = "CometCloud research (seth@looloomi.ai; institutional research contact)"
CIK_TICKERS = "https://www.sec.gov/files/company_tickers.json"
CONCEPT = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/dei/EntityCommonStockSharesOutstanding.json"
OUT = "/Volumes/CometCloudAI/cometcloud-local/research/t184/edgar_base_shares.json"
FACT_FROM = "2024-06-01"

# T-179 未把 base_date 对过申报的 14 家(卡 acceptance ②)。
# WELL 是分类方法的来源(其 base 已核过),CMCSA 封面股数不按标准概念报(已知不可自动核)。
TICKERS = [
    "TSLA", "PANW", "INTC", "CVX", "UL", "CRM", "TTE", "MPC", "VLO",
    "ADBE", "STX", "ORCL", "WFC", "BAC",
]
_last = [0.0]


def get(url: str, timeout: int = 60) -> dict:
    gap = time.time() - _last[0]
    if gap < 0.22:            # ≤ 5 req/s
        time.sleep(0.22 - gap)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    _last[0] = time.time()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    return json.loads(raw.decode())


def main() -> None:
    by_tk: dict[str, list[tuple[int, str]]] = {}
    for v in get(CIK_TICKERS).values():
        by_tk.setdefault(v["ticker"].upper(), []).append((v["cik_str"], v["title"]))

    out: dict[str, dict] = {}
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
            print(t, cik, "ERROR", e)
            continue
        rows = []
        for unit, facts in j.get("units", {}).items():
            for f in facts:
                if f.get("end", "") >= FACT_FROM:
                    rows.append({
                        "end": f["end"], "val": f.get("val"), "unit": unit,
                        "form": f.get("form"), "filed": f.get("filed"),
                        "accn": f.get("accn"), "fy": f.get("fy"), "fp": f.get("fp"),
                    })
        rows.sort(key=lambda r: (r["end"], r["filed"] or ""))
        out[t] = {"cik": cik, "title": title, "n": len(rows), "facts": rows}
        print(f"{t:6s} CIK {cik:>10} {len(rows):>3} 条  最早 end {rows[0]['end'] if rows else '-'}")
        time.sleep(0.25)

    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print("written", OUT)


if __name__ == "__main__":
    main()