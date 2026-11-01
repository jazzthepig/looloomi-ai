#!/usr/bin/env python3
"""T-217 ②: 直接读 `loop_attempt` 表(只读) —— 卡面点名的 ~50 次超时按时间点对齐。

卡面说「把近 7 天 loop_attempt 里 …按时间点对齐成一张表」——
上两轮用 `/internal/loop-attempts` 端点得到 404,那是端点路径不对,
表本身在 `loop_attempt`(src/api/rpc_diagnostics.py::_LOOP_ATTEMPT_TABLE)。

输出: t217_loop_attempt.json
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
COLS = "at,loop_name,outcome,reason,elapsed_ms,detail,writer,build"


def q(table: str, params: dict):
    qq = urllib.parse.urlencode(params, safe="().,:*$")
    url = SB + "/rest/v1/" + table + "?" + qq
    req = urllib.request.Request(url, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:160]


def main() -> None:
    out = {"probe": {}, "rows": []}
    # 1) 可读性 + 列名
    st, sample = q("loop_attempt", {"select": COLS, "order": "at.asc", "limit": "1"})
    out["probe"]["first_row_status"] = st
    out["probe"]["first_row_sample"] = sample if not isinstance(sample, list) else (sample[0] if sample else None)
    if st != 200:
        print("NOT READABLE", st, str(sample)[:200])
        (HERE / "t217_loop_attempt.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
        return

    # 2) 近 7 天全部(翻页带 order=)
    now = dt.datetime.now(dt.timezone.utc)
    since = (now - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows, offset = [], 0
    while True:
        st, page = q("loop_attempt", {
            "select": COLS, "at": "gte." + since,
            "order": "at.asc,id.asc", "limit": "1000", "offset": str(offset)})
        if st != 200 or not isinstance(page, list) or not page:
            break
        rows.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
        if offset > 20000:
            break
    out["probe"]["since"] = since
    out["probe"]["n_rows_7d"] = len(rows)
    out["rows"] = rows
    (HERE / "t217_loop_attempt.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("rows 7d:", len(rows))

    # 3) 口径汇总
    by_outcome = collections.Counter(r.get("outcome") for r in rows)
    print("outcomes:", dict(by_outcome))
    bad = [r for r in rows if r.get("outcome") in ("error", "refused", "failed")]
    by_loop = collections.Counter(r.get("loop_name") for r in bad)
    print("bad rows:", len(bad))
    for k, v in by_loop.most_common():
        print("  ", k, v)
    errs = [r for r in rows if r.get("outcome") == "error"]
    by_reason = collections.Counter((r.get("reason") or "")[:90] for r in errs)
    print("error reasons:")
    for k, v in by_reason.most_common(30):
        print("  ", v, "|", k)


if __name__ == "__main__":
    main()
