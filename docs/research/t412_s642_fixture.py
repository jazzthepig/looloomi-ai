"""T-412:从研究产物导出 S-642 一致性检验用的 fixture(生产形状的日线行 + 闸门行 + 期望逐日净值)。

**为什么要有这个脚本**:fixture 里的每一行都必须能从研究产物原样复现(否则测试里的「一致」是假的)。
本脚本只读 Mac 数据根下的研究缓存,不改库、不写生产表。

来源:
- 日线:`research/t156/_bars_early.jsonl` + `research/t156/_bars.jsonl` + `research/t159/_bars.jsonl`
  (= 研究 `t159_bear_short.load_bars()` 的三个来源;合并、去重、排序的口径照它)。
- 闸门:`research/t156/_style.json`(majors / cap 的日收益;与生产表 `style_index_pit_daily`
  的 (style='majors', weighting='cap') 行**逐行相同**(实测 max |Δret| = 0,2484 天))。
- 期望逐日净值:`docs/research/t348_r3_families.csv` 里 family=S642 的一段。
- 期望票本:`research/t159/_tickets_2020-03-01_2026-06-20.json` 的 `short`。

导出的一段:2022-01-21(族曲线的第一天 = 第一张票的进场日)→ 2022-11-05(这一段最后一张票的出场日),
22 张票 / 16 个标的 / 289 天。这一段里有 cap 触顶日(2022-01-23:6 张在手 + 6 张同日进场 ⇒ 跳过 2 张),
所以这段同时检验「跳过」口径。日线从 2020-03-01 前 220 根开始(信号日下标 ≥ 220 的 warm-up 口径),
到该标的这一段的最后出场为止 —— 研究那次跑票的信号日窗口就是 2020-03-01 起,候选集因此与研究完全一致。

用法(Mac 数据根):
    python3 docs/research/t412_s642_fixture.py
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.environ.get("COMETCLOUD_DATA", "/Volumes/CometCloudAI/cometcloud-local")
T156 = os.path.join(DATA, "research", "t156")
T159 = os.path.join(DATA, "research", "t159")
CACHES = [os.path.join(T156, "_bars_early.jsonl"), os.path.join(T156, "_bars.jsonl"),
          os.path.join(T159, "_bars.jsonl")]

D_FROM, D_TO = "2022-01-21", "2022-11-08"      # 这一段里进场日落在这里
SIGNAL_FROM = "2020-03-01"                    # 研究那次跑票的信号日窗口(候选集口径)
WARMUP = 220
OUT = os.path.join(ROOT, "tests", "fixtures", "s642_fixture.json")


def load_bars(symbols: set[str]) -> dict[str, list[dict]]:
    """照 `t159_bear_short.load_bars()` 的合并/去重口径,保留原始 volume(生产形状)。"""
    by: dict[str, list[tuple]] = defaultdict(list)
    meta: dict[tuple, dict] = {}
    for fn in CACHES:
        if not os.path.exists(fn):
            continue
        with open(fn) as fh:
            for line in fh:
                for x in json.loads(line):
                    s = x["symbol"]
                    if s not in symbols:
                        continue
                    dv = float(x["close"]) * float(x["volume"])
                    tup = (x["trade_date"][:10], float(x["open"]), float(x["high"]), float(x["low"]),
                           float(x["close"]), dv)
                    by[s].append(tup)
                    meta.setdefault((s,) + tup, {"volume": float(x["volume"])})
    out: dict[str, list[dict]] = {}
    for s, rows in by.items():
        seen = {}
        for tup in sorted(set(rows)):
            seen[tup] = meta[(s,) + tup]
        out[s] = [{"trade_date": t[0], "open": t[1], "high": t[2], "low": t[3], "close": t[4],
                   "volume": seen[t]["volume"]} for t in sorted(set(rows))]
    return out


def main() -> None:
    tickets_all = json.load(open(os.path.join(T159, "_tickets_2020-03-01_2026-06-20.json")))["short"]
    sel = [t for t in tickets_all if D_FROM <= t["entry_d"] <= D_TO]
    symbols = {t["symbol"] for t in sel}
    last_exit: dict[str, str] = {}
    for t in sel:
        last_exit[t["symbol"]] = max(last_exit.get(t["symbol"], ""), t["exit_d"] or "")
    bars = load_bars(symbols)

    # 从 SIGNAL_FROM 前 220 根开始(候选集与研究一致),到该标的最后出场为止
    cut: dict[str, list[dict]] = {}
    for s, rows in bars.items():
        idx = next((i for i, r in enumerate(rows) if r["trade_date"] >= SIGNAL_FROM), len(rows))
        start = max(0, idx - WARMUP)
        end = next((i for i, r in enumerate(rows) if r["trade_date"] > last_exit[s]), len(rows))
        cut[s] = rows[start:end]

    style = json.load(open(os.path.join(T156, "_style.json")))
    style = sorted(({"d": str(r["d"])[:10], "ret": float(r["ret"])} for r in style
                    if r.get("ret") is not None and float(r["ret"]) > -0.95),
                   key=lambda r: r["d"])
    gate = [r for r in style if r["d"] <= max(last_exit.values())]

    curve = []
    with open(os.path.join(HERE, "t348_r3_families.csv")) as fh:
        for row in csv.reader(fh):
            if row and row[0] == "S642":
                curve.append({"d": row[1], "nav": float(row[2])})
    expect = [r for r in curve if D_FROM <= r["d"] <= max(last_exit.values())]

    fx = {
        "meta": {
            "family": "S642", "rule": "S-642 熊市空头臂(T-407 清单 §1)",
            "segment": [D_FROM, max(last_exit.values())],
            "n_days": len(expect), "n_tickets": len(sel), "n_symbols": len(symbols),
            "bars_from": SIGNAL_FROM, "bars_warmup": WARMUP,
            "bar_row_keys": ["trade_date", "open", "high", "low", "close", "volume"],
            "gate_row_keys": ["d", "ret"],
            "source_curve": "docs/research/t348_r3_families.csv (family=S642)",
            "source_tickets": "research/t159/_tickets_2020-03-01_2026-06-20.json (short)",
            "source_bars": "research/t156/_bars_early.jsonl + t156/_bars.jsonl + t159/_bars.jsonl",
            "source_gate": "research/t156/_style.json(= 生产 style_index_pit_daily majors/cap 逐行相同)",
            "note": "美元额 = close × volume(库里 volume 是币量)。闸门由 short_paper.gate_closed_by_day 算。",
        },
        "gate": [[r["d"], r["ret"]] for r in gate],
        "bars": {s: [[r["trade_date"], r["open"], r["high"], r["low"], r["close"], r["volume"]] for r in rows]
                 for s, rows in sorted(cut.items())},
        "tickets": [{k: t[k] for k in ("symbol", "signal_d", "entry_d", "exit_d", "entry_px", "stop_px",
                                       "exit_px", "exit_reason", "bars_held")} for t in
                    sorted(sel, key=lambda t: (t["entry_d"], t["symbol"]))],
        "expected": [[r["d"], r["nav"]] for r in expect],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(fx, fh, ensure_ascii=False, separators=(",", ":"))
    n_rows = sum(len(v) for v in fx["bars"].values())
    print(f"wrote {OUT}: {n_rows} bar rows / {len(symbols)} symbols / {len(fx['gate'])} gate rows / "
          f"{len(fx['tickets'])} tickets / {len(fx['expected'])} expected days "
          f"({os.path.getsize(OUT)/1e6:.2f} MB)")


if __name__ == "__main__":
    sys.exit(main())
