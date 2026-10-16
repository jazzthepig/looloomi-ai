"""加密研究面板(日频)—— asset_mcap_daily 全部标的的价格与市值,供横截面挖掘(S-586)。私有数据,不进 git。

用法(Mac 上,环境里有 SUPABASE_URL / SUPABASE_KEY;key 不打印、不写文件):
    python3 docs/research/crypto_export_daily.py /Volumes/CometCloudAI/cometcloud-local/research/crypto_daily [起始日 2019-06-01]

写出 panel.json:{"dates": [...], "price": {sym: [...与 dates 对齐,缺 = null]}, "mcap": {sym: [...]}, "source": {sym: 来源}}
同一 symbol 有多个 source 时取行数最多的那个(打印出来)。只读。
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import httpx

PAGE = 1000


def main(out_dir: str, start: str = "2019-06-01") -> None:
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_KEY 不在环境里")
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    rows_by: dict[tuple[str, str], dict[str, tuple]] = defaultdict(dict)
    with httpx.Client(base_url=base, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=120) as c:
        offset = 0
        while True:
            r = c.get(f"/rest/v1/asset_mcap_daily?select=symbol,d,price,mcap,source&d=gte.{start}"
                      f"&order=symbol,source,d&limit={PAGE}&offset={offset}")
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
            rows = r.json()
            for x in rows:
                rows_by[(x["symbol"], x.get("source") or "")][x["d"]] = (x.get("price"), x.get("mcap"))
            offset += len(rows)
            if len(rows) < PAGE:
                break
            if offset % 50000 == 0:
                print(f"  …{offset} 行")
    best: dict[str, tuple[str, dict]] = {}
    for (sym, src), ser in rows_by.items():
        if sym not in best or len(ser) > len(best[sym][1]):
            best[sym] = (src, ser)
    dates = sorted({d for _, ser in best.values() for d in ser})
    price = {s: [ (ser.get(d) or (None, None))[0] for d in dates] for s, (_, ser) in best.items()}
    mcap = {s: [ (ser.get(d) or (None, None))[1] for d in dates] for s, (_, ser) in best.items()}
    (out / "panel.json").write_text(json.dumps({"dates": dates, "price": price, "mcap": mcap,
                                                "source": {s: src for s, (src, _) in best.items()}}))
    print(f"写好 {out}/panel.json:{len(best)} 个标的 × {len(dates)} 天(共读 {offset} 行)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "2019-06-01")
