#!/usr/bin/env python3
"""T-218:逐条核对 10 条前向命题在 origin/main 情景台账实现下的**可结算性**(只读)。

台账的取值口径(`src/data/evaluation/scenario_ledger.py::_value`,origin/main 版):
  close:<SYM> → ohlcv_daily, symbol='eq.<SYM>', source 依次试 'eq.binance_hist' → 'eq.eodhd'
  state:<f>   → state_daily, entity='eq.panel', feature='eq.<f>', d = 结算日
  macro:<s>   → macro_daily, series='eq.<s>', 取结算日或之前 7 天内最近一个值
本脚本用同一套过滤条件读一遍库,确认每条命题**今天就能解析到值**,并打印序列的新鲜度
(最后一条数据的日期)。只读:不写库、不改代码。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
PAGE = 1000
LATE_DAYS = 7


def sb(path, params):
    """分页读;每页都带 order=。返回 (status, rows, err)。"""
    rows_all, off = [], 0
    while True:
        q = dict(params)
        q["limit"] = str(PAGE)
        q["offset"] = str(off)
        url = f"{SB}/rest/v1/{path}?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers=H)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                st = r.status
                body = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:  # noqa: PERF203
            return e.code, [], e.read().decode()[:200]
        if st != 200:
            return st, [], str(body)[:200]
        rows_all.extend(body)
        if len(body) < PAGE:
            return st, rows_all, None
        off += PAGE


def main():
    report = (HERE / "T-218_rails_vs_tokens.md").read_text()
    props = json.loads(re.search(r"```json\n(.*?)\n```", report, re.S).group(1))
    print(f"{'id':<9} {'kind':<6} {'key':<22} {'解析路径':<34} {'n':>7}  最后日期")
    bad = 0
    for e in props:
        kind, key = e["variable"].split(":", 1)
        horizon = e["horizon_d"]
        if kind == "close":
            for src in ("binance_hist", "eodhd"):
                st, rows, err = sb("ohlcv_daily",
                                   {"select": "trade_date,close", "symbol": f"eq.{key}",
                                    "source": f"eq.{src}", "order": "trade_date.asc"})
                if st == 200 and rows:
                    last = str(rows[-1].get("trade_date"))[:10]
                    print(f"{e['id']:<9} {kind:<6} {key:<22} {'ohlcv_daily eq.'+key+' / eq.'+src:<34} "
                          f"{len(rows):>7}  {last}")
                    break
            else:
                print(f"{e['id']:<9} {kind:<6} {key:<22} {'✗ 两个 source 都没有行':<34} {'—':>7}  —")
                bad += 1
        elif kind == "state":
            st, rows, err = sb("state_daily",
                               {"select": "d,value", "entity": "eq.panel",
                                "feature": f"eq.{key}", "order": "d.asc"})
            if st == 200 and rows:
                last = str(rows[-1].get("d"))[:10]
                print(f"{e['id']:<9} {kind:<6} {key:<22} {'state_daily entity=panel':<34} "
                      f"{len(rows):>7}  {last}")
            else:
                print(f"{e['id']:<9} {kind:<6} {key:<22} {'✗ entity=panel 下读不到':<34} {'—':>7}  —")
                bad += 1
        elif kind == "macro":
            st, rows, err = sb("macro_daily",
                               {"select": "d,value", "series": f"eq.{key}", "order": "d.asc"})
            if st == 200 and rows:
                last = str(rows[-1].get("d"))[:10]
                print(f"{e['id']:<9} {kind:<6} {key:<22} {'macro_daily series='+key:<34} "
                      f"{len(rows):>7}  {last}")
            else:
                print(f"{e['id']:<9} {kind:<6} {key:<22} {'✗ 读不到':<34} {'—':>7}  —")
                bad += 1
        wd = dt.date.fromisoformat(horizon).strftime("%a")
        print(f"{'':<9} └─ 结算日 {horizon}({wd}),今天 {dt.date.today()} 未到期")
    print()
    print(f"共 {len(props)} 条,今天解析不到值的 {bad} 条")


if __name__ == "__main__":
    main()
