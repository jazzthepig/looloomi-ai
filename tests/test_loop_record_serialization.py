"""循环记录器的两个盲点(10-29)。

① 成功轮的 detail 带 numpy 标量 / NaN → json 序列化在记录器里抛出 → 被吞 → **只有成功的那几轮没有记录**
   (`_meta_allocator_loop` 10-28 23:30 真的写了表,而 loop_attempt 里最后一次 ok 停在 10-08)。
② 退役的循环在心跳里永远是「死了」(`_narrative_probe_loop`)—— 只按显式登记排除,不按时间自动清。
"""
import datetime as dt
import json
import math

import numpy as np
import pandas as pd

from src.api import loop_beat
from src.api.json_safe import json_safe


def test_numpy_nan_and_dates_become_strict_json():
    detail = {"written": np.int64(1213), "eval": {"sharpe": np.float64(1.25), "dd": float("nan"),
                                                  "inf": np.float64(np.inf), "picks": pd.Series([1, 2]).value_counts().to_dict(),
                                                  "d": pd.Timestamp("2026-10-27"), "day": dt.date(2026, 10, 28),
                                                  "arr": np.array([1.0, np.nan])}}
    out = json_safe(detail)
    s = json.dumps(out, allow_nan=False)                 # 严格 JSON:PostgREST 不收 NaN
    back = json.loads(s)
    assert back["written"] == 1213 and back["eval"]["sharpe"] == 1.25
    assert back["eval"]["dd"] is None and back["eval"]["inf"] is None
    assert back["eval"]["d"].startswith("2026-10-27") and back["eval"]["day"] == "2026-10-28"
    assert back["eval"]["arr"] == [1.0, None]
    assert not any(isinstance(v, float) and math.isnan(v) for v in back["eval"].values())


def test_plain_payload_is_unchanged():
    d = {"a": 1, "b": "x", "c": [1, 2.5, None], "d": {"e": True}}
    assert json_safe(d) == d


def test_retired_loops_are_not_reported_dead_and_live_ones_still_are():
    beats = {"_narrative_probe_loop": {"last_run_at": 1, "ok": True, "last_ok_at": 1},
             "_some_loop": {"last_run_at": 1, "ok": False, "n_consecutive_failures": 3, "last_error": "x"}}
    o = loop_beat.overall(beats)
    names = [r["loop"] for r in o["rows"]]
    assert "_narrative_probe_loop" not in names
    assert o["n_failing"] == 1 and "_some_loop" in names
    assert "_narrative_probe_loop" in loop_beat.RETIRED_LOOPS


def test_retired_names_really_are_gone_from_the_code():
    """登记表不能变成「把吵的循环藏起来」的地方:登记的名字在 main.py 里不能还有 `async def`。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src/api/main.py").read_text(encoding="utf-8")
    for name in loop_beat.RETIRED_LOOPS:
        assert f"async def {name}(" not in src, f"{name} 还在代码里 —— 它没退役,别把它从面板上藏掉"
