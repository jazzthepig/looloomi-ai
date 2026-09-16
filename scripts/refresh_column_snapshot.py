#!/usr/bin/env python3
"""重生成 `schema/public_columns.json` —— 列快照的唯一维护路径(S-357)。

    python3 scripts/refresh_column_snapshot.py          # 写入
    python3 scripts/refresh_column_snapshot.py --dry    # 只报差异

为什么需要它。`tests/test_postgrest_columns_exist.py` 用这个快照判断
「代码 filter 的列在不在」,而快照**没有任何重生成路径** ——
实测 2026-09-16:快照停在 **2026-08-20**,近一个月。
于是 S-336 给 `fusion_paper_nav` 加的 `inception_id` / `void_reason` 在库里存在、
在快照里不存在,守卫报「列不存在」,而**列是在的**。

**一份需要有人记得手动更新的快照,和一份手写清单是同一种东西**(S-353:
`COVERAGE` 手写字典追不上新表,是同一个毛病的另一处)。

⚠️ 它**只报差异不静默覆盖**:快照是守卫的权威,悄悄改掉权威等于关掉守卫。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SNAP = ROOT / "schema" / "public_columns.json"

SQL = """
select jsonb_object_agg(table_name, cols) from (
  select c.table_name, jsonb_agg(c.column_name order by c.column_name) as cols
  from information_schema.columns c
  join information_schema.tables t
    on t.table_schema = c.table_schema and t.table_name = c.table_name
  where c.table_schema = 'public' and t.table_type = 'BASE TABLE'
  group by c.table_name) s;
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or ""
    if not (url and key):
        print("✗ 需要 SUPABASE_URL / SUPABASE_KEY")
        return 1

    # PostgREST 挡了 information_schema,所以走 catalog_inventory 的同类路子:
    # 逐表 limit=0 读 Content-Range 拿不到列名,只能靠一个 RPC。若 `public_columns()`
    # 不存在,明确说出来 —— **不要退化成「快照是对的」**。
    import httpx
    hdr = {"apikey": key, "Authorization": f"Bearer {key}",
           "Content-Type": "application/json"}
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{url}/rest/v1/rpc/public_columns", json={}, headers=hdr)
    if r.status_code != 200:
        print(f"✗ public_columns() 读不到: HTTP {r.status_code} {r.text[:200]}")
        print("  建一个 SECURITY DEFINER 的 public_columns() 返回 "
              "{table_name -> [column...]},SQL 见本文件顶部 SQL 常量。")
        return 1
    live = r.json()
    if isinstance(live, list) and live:
        live = live[0]
    if not isinstance(live, dict) or not live:
        print("✗ public_columns() 返回空 —— **空 ≠ 库里没有列**,拒绝覆盖快照")
        return 1

    old = json.loads(SNAP.read_text()) if SNAP.exists() else {"tables": {}}
    old_t = old.get("tables") or {}
    added_t = sorted(set(live) - set(old_t))
    dropped_t = sorted(set(old_t) - set(live))
    changed = {t: (sorted(set(live[t]) - set(old_t[t])),
                   sorted(set(old_t[t]) - set(live[t])))
               for t in set(live) & set(old_t)
               if set(live[t]) != set(old_t[t])}
    print(f"快照 {old.get('_generated', '?')} → {dt.date.today()}")
    if added_t:   print(f"  +表 {added_t}")
    if dropped_t: print(f"  -表 {dropped_t}  ← **表消失是大事,先确认是删除不是读取失败**")
    for t, (a, d) in sorted(changed.items()):
        print(f"  ~{t}: +{a} -{d}" if d else f"  ~{t}: +{a}")
    if not (added_t or dropped_t or changed):
        print("  无差异")
        return 0
    if args.dry:
        return 0
    SNAP.write_text(json.dumps(
        {"_generated": str(dt.date.today()),
         "_source": "information_schema via public_columns() RPC",
         "tables": {t: sorted(v) for t, v in sorted(live.items())}},
        indent=2) + "\n")
    print(f"  已写入 {SNAP.relative_to(ROOT)} · {len(live)} 张表")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
