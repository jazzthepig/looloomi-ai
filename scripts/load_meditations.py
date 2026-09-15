#!/usr/bin/env python3
"""把 meditations/*.md 接进 regime_daily(S-349)。跑一次,之后每天增量。

    python3 scripts/load_meditations.py            # 全量 upsert
    python3 scripts/load_meditations.py --dry-run  # 只解析,不写

背景。83 篇每日市场冥想在 `meditations/` 躺了三个月,**被 0 行代码读过、0 行入过库**。
同时 HIGH_DIM_ONTOLOGY §5 的 VDB 表里 `Regime 指纹 12d` 标着「已算未入库」。
两个为彼此而生的东西一直没见过面 —— 而 VDB 存在的全部理由就是回答
「当前 60 天像历史哪段、那时什么风格在跑」(Jazz 2026-09-15)。

这个脚本只做一件事:把**人的判读**贴到**已经算好的指纹**旁边。

⚠️ 它刻意不从散文里反解数字。avg_cis / pct_out / pillar 均值全部来自 `cis_scores`
(记录源),已由 migration s349 算进 `regime_daily.features`。冥想提供的是
**regime 判读**和**推理正文** —— 那是库里没有、也算不出来的东西。
从散文里抠一个本来就在库里的数字,是给自己造第二个真相。
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MED = ROOT / "meditations"

# 判读词表。大小写/中英混排/带不带 confidence 都能命中;命不中就留空 ——
# **留空不是"那天没有 regime",是"这篇没写明"**,两者在下游不能同形。
_REGIME = re.compile(
    r"\b(TIGHTENING|GOLDILOCKS|EASING|STAGFLATION|NEUTRAL|RISK[_ ]?OFF|RISK[_ ]?ON)\b",
    re.I)


def parse(path: pathlib.Path) -> dict | None:
    """(d, meditation, meditation_regime)。文件名即日期,正文原样保留。"""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", path.stem)
    if not m:
        return None
    body = path.read_text(encoding="utf-8", errors="replace")
    head = body[:600]                      # 判读写在抬头;正文里的引用不算
    hit = _REGIME.search(head)
    return {
        "d": m.group(1),
        "meditation": body,
        "meditation_regime": (hit.group(1).upper().replace(" ", "_") if hit else None),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = [r for r in (parse(p) for p in sorted(MED.glob("*.md"))) if r]
    n_reg = sum(1 for r in rows if r["meditation_regime"])
    print(f"解析 {len(rows)} 篇 · 带判读 {n_reg} · 无判读 {len(rows) - n_reg}")
    if args.dry_run:
        for r in rows[-3:]:
            print(f"  {r['d']}  {r['meditation_regime'] or '(未写明)'}  {len(r['meditation'])} 字")
        return 0

    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or ""
    if not (url and key):
        print("✗ 需要 SUPABASE_URL / SUPABASE_KEY(Mac 侧有)")
        return 1

    import httpx
    hdr = {"apikey": key, "Authorization": f"Bearer {key}",
           "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}

    # regime_daily 上 features/regime_db/n_universe 是 NOT NULL(S-349 migration
    # 跑过、脚本不重算)。要写 meditation 必须先 fetch 现存的 features+regime_db+n_universe
    # 并入 row,否则 23502 not-null violation。这是脚本 bug,不是 schema drift。
    days = [r["d"] for r in rows]
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{url}/rest/v1/regime_daily",
                  params={"select": "d,features,regime_db,n_universe",
                          "or": f"({','.join(f'd.eq.{d}' for d in days)})"},
                  headers=hdr)
        r.raise_for_status()
        existing = {row["d"]: row for row in r.json()}
    n_missing_pre = sum(1 for r in rows if r["d"] not in existing)
    if n_missing_pre:
        print(f"⚠ {n_missing_pre} 天 regime_daily 没有现存的 features/regime_db/n_universe"
              f"(S-349 没跑到那一天) —— 这些天跳过 upsert,先看 S-349 日志")
        rows = [r for r in rows if r["d"] in existing]
    for r in rows:
        ex = existing[r["d"]]
        r["features"] = ex["features"]
        r["regime_db"] = ex["regime_db"]
        r["n_universe"] = ex["n_universe"]

    # upsert,不是 insert:重跑幂等,而冥想会被修订。
    ok = miss = 0
    with httpx.Client(timeout=30) as c:
        for i in range(0, len(rows), 20):
            chunk = rows[i:i + 20]
            r = c.post(f"{url}/rest/v1/regime_daily?on_conflict=d", json=chunk, headers=hdr)
            if r.status_code in (200, 201, 204):
                ok += len(chunk)
            else:
                miss += len(chunk)
                print(f"  ✗ {chunk[0]['d']}..{chunk[-1]['d']}  HTTP {r.status_code} {r.text[:160]}")
    print(f"写入 {ok} · 失败 {miss}")

    # 立刻对账:库里真的有这些天的正文吗。
    # (不回读就不算写成功 —— 这条链上被这个问题咬过太多次,S-334/S-336。)
    with httpx.Client(timeout=30) as c:
        q = c.get(f"{url}/rest/v1/regime_daily",
                  params={"select": "d", "meditation": "not.is.null"},
                  headers={**hdr, "Prefer": "count=exact", "Range": "0-0"})
        print(f"库里带冥想正文的天数: {q.headers.get('content-range', '?')}")
    return 0 if miss == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
