"""T-428:读 S-642 空头臂需要的输入(只读),缓存到 Mac 数据根的 research/t428/。"""
from __future__ import annotations

import asyncio
import json
import os
import pickle
import sys
import time

sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai-lane-a")

OUT = "/Volumes/CometCloudAI/cometcloud-local/research/t428"
BARS_FROM = "2024-05-16"          # S642_FROM(2025-01-01)往前 230 天(>220 根热身)
BARS_TO = "2026-11-22"
GATE_FROM = "2023-01-01"


async def main() -> None:
    from src.data.universe.state_book import _get_all
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    tail = (f"ohlcv_daily?select=symbol,trade_date,open,high,low,close,volume"
            f"&source=eq.binance_hist&trade_date=gte.{BARS_FROM}&trade_date=lte.{BARS_TO}"
            f"&order=symbol.asc,trade_date.asc")
    rows = await _get_all(tail)
    t_read = time.time() - t0
    print(f"[bars] {len(rows)} 行,读 {t_read:.1f}s", flush=True)
    with open(f"{OUT}/bars.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")

    t1 = time.time()
    grows = await _get_all(f"style_index_pit_daily?select=d,ret&style=eq.majors&weighting=eq.cap"
                           f"&d=gte.{GATE_FROM}&d=lte.{BARS_TO}&order=d")
    print(f"[gate] {len(grows)} 行,读 {time.time()-t1:.1f}s", flush=True)
    with open(f"{OUT}/gate.json", "w") as f:
        json.dump(grows, f)

    # 形状统计
    bysym: dict[str, list[str]] = {}
    for r in rows:
        bysym.setdefault(r["symbol"], []).append(str(r["trade_date"])[:10])
    n_bars = sorted(len(v) for v in bysym.values())
    print(f"符号数 {len(bysym)}, 每符号根数 中位 {n_bars[len(n_bars)//2]} 最小 {n_bars[0]} 最大 {n_bars[-1]}", flush=True)
    warm = {s: sum(1 for d in v if d < "2025-01-01") for s, v in bysym.items()}
    ws = sorted(warm.values())
    print(f"2025-01-01 之前的根数: 中位 {ws[len(ws)//2]} 最小 {ws[0]} 最大 {ws[-1]}; "
          f"≥220 的符号 {sum(1 for x in ws if x >= 220)}/{len(ws)}", flush=True)
    dates = sorted({str(r["trade_date"])[:10] for r in rows})
    print(f"日期 {dates[0]} → {dates[-1]},共 {len(dates)} 天", flush=True)
    with open(f"{OUT}/meta.json", "w") as f:
        json.dump({"rows": len(rows), "read_s": t_read, "symbols": len(bysym),
                   "d0": dates[0], "d1": dates[-1]}, f)
    print(f"[done] 总 {time.time()-t0:.1f}s", flush=True)


asyncio.run(main())
