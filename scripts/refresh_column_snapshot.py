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


def _load_dotenv() -> None:
    """读仓库根的 `.env`,**不覆盖已导出的环境变量**。

    S-361:Jazz 在 Mac 上跑这个脚本报「需要 SUPABASE_URL / SUPABASE_KEY」,
    而 `.env` 里两个都有值 —— 因为脚本只读 `os.environ`,而 `preflight.sh`
    是在它自己第 404 行才 `source .env` 的,而我把这个脚本排在 preflight **之前**。

    **一个只能在另一个脚本跑过之后才工作的脚本,不是一个脚本。**
    它自己读,于是单独跑、在链里跑、在 CI 里跑都一样。
    已导出的优先 —— CI 里注入的 secret 不该被仓库里的 `.env` 盖掉。
    """
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip().strip('"').strip("'")

# ⚠️ 真正跑的是 `public_columns()` RPC(见 `_source`)。这份常量只作参照,
# **两处必须一致** —— 不一致时以 RPC 为准,并把这里改过来。
#
# S-360:两处原本都写 `t.table_type = 'BASE TABLE'`,于是 13 个视图(127 列)
# 不进快照。而 `test_postgrest_columns_exist` 对「不在快照里的对象」是 **skip** 的,
# 所以针对视图的 filter 全部变成不检查 —— 包括 `ohlcv_daily_canonical` 和
# `signal_outcomes_unified`,正是 `docs/SPINE.md` 要所有消费者迁过去的两条 canonical 路径。
#
# PostgREST 对视图和表一视同仁:filter 一个视图的列一样会 400。守卫却只看得见一半。
# 这个脚本当时写完没跑过,所以收缩从未发生 —— 一旦跑,快照会从 89 个对象缩到 79,
# **而测试全程绿**。一个让仪表变盲的修复比不修更坏(S-357 是我写的,这条记在自己账上)。
SQL = """
select jsonb_object_agg(table_name, cols) from (
  select c.table_name, jsonb_agg(c.column_name order by c.column_name) as cols
  from information_schema.columns c
  join information_schema.tables t
    on t.table_schema = c.table_schema and t.table_name = c.table_name
  where c.table_schema = 'public' and t.table_type in ('BASE TABLE', 'VIEW')
  group by c.table_name) s;
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--allow-shrink", metavar="REASON", default="",
                    help="对象数下降时必须给出理由 —— 见下面的棘轮")
    args = ap.parse_args()

    _load_dotenv()
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or ""
    if not (url and key):
        print("✗ 需要 SUPABASE_URL / SUPABASE_KEY(已尝试读仓库根的 .env)")
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

    # ── 棘轮:快照不许缩水 ────────────────────────────────────────────────
    # S-360:这个脚本差一点把 13 个视图从快照里抹掉(`BASE TABLE` 过滤),
    # 而 `test_postgrest_columns_exist` 对不在快照里的对象是 **skip** 的 ——
    # 于是覆盖率下降会表现为**一片绿**。被抹掉的恰好包括
    # `ohlcv_daily_canonical` / `signal_outcomes_unified`,SPINE 的两条 canonical 路径。
    #
    # 守卫放在这里而不是放在测试里,是因为**危险的动作是写入,不是断言**。
    # 测试只能在事后说「现在覆盖少了」,而那时旧快照已经没了。
    if dropped_t and not args.allow_shrink:
        print(f"\n✗ 拒绝写入:{len(dropped_t)} 个对象会从快照消失。")
        print(f"  {dropped_t}")
        print("  快照缩水 = 守卫变盲,而测试会**照样绿**(不在快照里的对象被 skip)。")
        print("  确认这些对象真的被 DROP 了,再加 --allow-shrink '<原因>' 重跑。")
        return 1
    if dropped_t:
        print(f"\n⚠ 允许缩水({args.allow_shrink}):{dropped_t}")
    SNAP.write_text(json.dumps(
        {"_generated": str(dt.date.today()),
         "_source": "information_schema via public_columns() RPC",
         "tables": {t: sorted(v) for t, v in sorted(live.items())}},
        indent=2) + "\n")
    print(f"  已写入 {SNAP.relative_to(ROOT)} · {len(live)} 张表")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
