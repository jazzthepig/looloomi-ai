#!/usr/bin/env python3
"""T-217 ②: 超时类 error 的时间点对齐。

两条通道(都只读):
  A) loop_attempt 直读        —— anon 读不到(RLS 开了但没有给 anon 的 policy)⇒ 0 行
  B) rpc/loop_attempt_health  —— SECURITY DEFINER,能读同一张表的聚合:
       逐循环 last_ok / last_fail / last_outcome / last_reason / n_ok_24h / n_fail_24h
  C) rpc/write_health         —— 逐表 last_ok / last_fail / last_outcome / last_body / n_*_24h

输出:
  t217_align_loops.json   —— 逐循环对齐表(卡面点名的循环在前)
  t217_align_tables.json  —— 逐表对齐表
  t217_align_clusters.json—— 按时间点把失败聚成簇(只报测量,不推测成因)
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent

# 卡面点名的循环
NAMED = ["_forward_record_loop", "_forward_return_backfill_loop", "_feature_arms_loop",
         "_core_variants_loop", "_public_cache_warm_loop", "_tokenization_tilt_loop",
         "_signal_attribution_loop", "_hl_book_loop", "_perp_mcap_backfill_loop",
         "executor_host"]


def sb(path: str, params: dict):
    qq = urllib.parse.urlencode(params, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + qq, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:250]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:140]


def ts(v):
    if not v:
        return None
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def main() -> None:
    out = {"read_at": dt.datetime.now(dt.timezone.utc).isoformat()}

    # A) 直读 loop_attempt
    st_direct, direct = sb("loop_attempt", {"select": "at,loop_name,outcome,reason,elapsed_ms,detail,writer,build",
                                             "order": "at.asc", "limit": "50"})
    out["direct_read"] = {"status": st_direct, "n_rows": len(direct) if isinstance(direct, list) else None,
                          "note": ("200 但 0 行 = RLS 开了、没给 anon policy(表里确实有行:rpc/loop_attempt_health "
                                   "读得到 97 个循环);不是表空" if st_direct == 200 and not direct else "")}
    print("direct loop_attempt:", st_direct, "n =", out["direct_read"]["n_rows"])

    # B) loop_attempt_health
    st_l, loops = sb("rpc/loop_attempt_health", {})
    print("loop_attempt_health:", st_l, "n =", len(loops) if isinstance(loops, list) else "n/a")
    out["loop_health_status"] = st_l
    if isinstance(loops, list):
        out["n_loops"] = len(loops)
        named_rows, other_rows = [], []
        for r in loops:
            r = dict(r)
            r["_named"] = r.get("loop_name") in NAMED
            (named_rows if r["_named"] else other_rows).append(r)
        named_rows.sort(key=lambda r: NAMED.index(r["loop_name"]))
        # 时间点对齐:按 last_fail 排
        named_rows.sort(key=lambda r: (ts(r.get("last_fail")) or dt.datetime.max.replace(tzinfo=dt.timezone.utc)))
        out["named_loops"] = named_rows
        out["other_loops_with_fail"] = sorted(
            [r for r in other_rows if r.get("last_fail")],
            key=lambda r: (ts(r.get("last_fail")) or dt.datetime.max.replace(tzinfo=dt.timezone.utc)))
        out["n_loops_total_fail24h"] = sum(int(r.get("n_fail_24h") or 0) for r in loops)
        out["named_loops_fail24h"] = sum(int(r.get("n_fail_24h") or 0) for r in named_rows)
        out["n_loops_total_ok24h"] = sum(int(r.get("n_ok_24h") or 0) for r in loops)
        # 簇:把所有 last_fail 落在同一分钟内的分到一簇
        pts = []
        for r in loops:
            t = ts(r.get("last_fail"))
            if t:
                pts.append((t, r.get("loop_name"), r.get("last_reason")))
        pts.sort()
        clusters = []
        for t, name, reason in pts:
            minute = t.replace(second=0, microsecond=0)
            if clusters and clusters[-1]["minute"] == minute.isoformat():
                clusters[-1]["loops"].append({"loop": name, "at": t.isoformat(), "reason": (reason or "")[:220]})
            else:
                clusters.append({"minute": minute.isoformat(),
                                 "loops": [{"loop": name, "at": t.isoformat(), "reason": (reason or "")[:220]}]})
        out["failure_clusters"] = clusters
        out["n_clusters"] = len(clusters)
        out["n_clusters_multi"] = sum(1 for c in clusters if len(c["loops"]) >= 2)
        (HERE / "t217_align_loops.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))

    # C) write_health
    st_w, tables = sb("rpc/write_health", {})
    print("write_health:", st_w, "n =", len(tables) if isinstance(tables, list) else "n/a")
    if isinstance(tables, list):
        tw = {"read_at": out["read_at"], "n_tables": len(tables),
              "fails": sorted([t for t in tables if t.get("last_fail")],
                              key=lambda t: ts(t.get("last_fail")) or dt.datetime.max.replace(tzinfo=dt.timezone.utc)),
              "recent_fail_24h": sorted([t for t in tables if int(t.get("n_fail_24h") or 0) > 0],
                                        key=lambda t: -(int(t.get("n_fail_24h") or 0)))}
        (HERE / "t217_align_tables.json").write_text(json.dumps(tw, ensure_ascii=False, indent=1))
        out["n_tables_fail_24h"] = len(tw["recent_fail_24h"])
        out["tables_fail_24h"] = tw["recent_fail_24h"]

    (HERE / "t217_align.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("wrote t217_align*.json")


if __name__ == "__main__":
    main()
