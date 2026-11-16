"""T-406 探针:生产闸门(STYLE 指数表)vs 研究闸门(t310_slots.load_gate)逐日比对 + 生产输入覆盖度。

用法:python3 docs/research/t406_probe.py
只读;不打印任何 key。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

MAC = Path("/Volumes/CometCloudAI/cometcloud-local")
URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Prefer": "count=exact"}


def sb_get(table: str, params: dict):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{URL}/rest/v1/{table}?{q}", headers=HDR)
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read().decode()
        rng = r.headers.get("Content-Range", "") or ""
    total = None
    if "/" in rng:
        tail = rng.split("/")[-1].strip()
        if tail.isdigit():
            total = int(tail)
    return (json.loads(body) if body else []), total


def sb_paged(table: str, params: dict, page: int = 1000, max_pages: int = 400):
    out, tot = [], None
    for i in range(max_pages):
        p = dict(params)
        p["limit"] = str(page)
        p["offset"] = str(i * page)
        rows, t = sb_get(table, p)
        if i == 0:
            tot = t
        out += rows
        if len(rows) < page:
            break
    return out, tot


def gate_from_rows(rows) -> tuple[dict, dict]:
    """研究 load_gate 的同一算式:水平 = cumprod(1+ret),SMA200(含当天),n<200 ⇒ 开。"""
    rows = [r for r in rows if r.get("ret") is not None and float(r["ret"]) > -0.95]
    rows.sort(key=lambda r: r["d"])
    lvl, cur = [], 1.0
    for r in rows:
        cur *= (1.0 + float(r["ret"]))
        lvl.append(cur)
    gate, lvl_by_d = {}, {}
    for i, r in enumerate(rows):
        seg = lvl[max(0, i - 199): i + 1]
        sma = sum(seg) / len(seg)
        n = len(seg)
        gate[r["d"]] = bool(n < 200 or lvl[i] > sma)
        lvl_by_d[r["d"]] = lvl[i]
    return gate, lvl_by_d


def main() -> None:
    # ── 1. 研究闸门(t310_slots.load_gate,STYLE 指向研究文件) ──
    import t310_slots as T310
    T310.STYLE = str(MAC / "research/t156/_style.json")
    res_gate, res_lvl, res_diag = T310.load_gate()
    print("[research] load_gate diag:", json.dumps(res_diag, ensure_ascii=False))
    print("[research] gate days:", len(res_gate), min(res_gate), max(res_gate),
          "closed:", sum(1 for v in res_gate.values() if not v))

    # ── 2. 生产闸门(STYLE 指数表) ──
    rows, tot = sb_paged("style_index_pit_daily",
                         {"select": "d,ret", "style": "eq.majors", "weighting": "eq.cap", "order": "d.asc"})
    print("[prod] style_index_pit_daily eq.majors/eq.cap rows:", len(rows), "total:", tot,
          "range:", (rows[0]["d"], rows[-1]["d"]) if rows else None)
    prod_gate, prod_lvl = gate_from_rows(rows)

    # 研究文件里的原始行(同一算式再算一遍,确认 load_gate 没被别处改过)
    raw = json.load(open(MAC / "research/t156/_style.json"))
    if isinstance(raw, dict):
        raw = raw.get("rows") or raw.get("data") or []
    if raw and "style" in raw[0]:
        raw = [r for r in raw if r.get("style") == "majors" and r.get("weighting") in (None, "cap")]
    raw_gate, _ = gate_from_rows(raw)
    same_as_research = all(bool(raw_gate.get(k)) == bool(v) for k, v in res_gate.items())
    print("[research] raw rows:", len(raw), "raw gate == load_gate:", same_as_research)

    # ── 3. 逐日比对 ──
    common = sorted(set(res_gate) & set(prod_gate))
    mism = [d for d in common if bool(res_gate[d]) != bool(prod_gate[d])]
    print(f"[cmp] overlap days: {len(common)}  ({common[0] if common else '-'} → {common[-1] if common else '-'})")
    print(f"[cmp] MISMATCH days: {len(mism)}")
    if mism:
        print("[cmp] first 10 mismatch:", [(d, bool(res_gate[d]), bool(prod_gate[d])) for d in mism[:10]])
        print("[cmp] last 10 mismatch:", [(d, bool(res_gate[d]), bool(prod_gate[d])) for d in mism[-10:]])
    # 水平差(同一 d 的指数水平)
    lv_common = [d for d in common if d in res_lvl and d in prod_lvl]
    if lv_common:
        diffs = [(abs(res_lvl[d] - prod_lvl[d]), d) for d in lv_common]
        diffs.sort(reverse=True)
        print("[cmp] max |level diff|:", diffs[0][0], "at", diffs[0][1], " median:", diffs[len(diffs)//2][0])
        # 首个不等的 d
        first_diff = next((d for d in sorted(lv_common) if abs(res_lvl[d] - prod_lvl[d]) > 1e-12), None)
        print("[cmp] first level-diff day:", first_diff)
        if first_diff:
            print("      research lvl", res_lvl[first_diff], "prod lvl", prod_lvl[first_diff])

    # ── 4. 生产输入覆盖度(asset_mcap_daily 价格 / funding_history 资金费) ──
    for sym in ("BTC", "ETH"):
        r, t = sb_get("asset_mcap_daily",
                      {"select": "d,price", "symbol": f"eq.{sym}", "order": "d.asc", "limit": "1"})
        r2, t2 = sb_get("asset_mcap_daily",
                        {"select": "d,price", "symbol": f"eq.{sym}", "order": "d.desc", "limit": "1"})
        print(f"[prod] asset_mcap_daily {sym}: total={t} first={r[0]['d'] if r else None} last={r2[0]['d'] if r2 else None}")
        fr, ft = sb_get("funding_history",
                        {"select": "funding_time", "venue": "eq.binance_perp", "symbol": f"eq.{sym}", "order": "funding_time.asc", "limit": "1"})
        fr2, ft2 = sb_get("funding_history",
                          {"select": "funding_time", "venue": "eq.binance_perp", "symbol": f"eq.{sym}", "order": "funding_time.desc", "limit": "1"})
        print(f"[prod] funding_history {sym}: total={ft} first={fr[0]['funding_time'] if fr else None} last={fr2[0]['funding_time'] if fr2 else None}")


if __name__ == "__main__":
    main()
