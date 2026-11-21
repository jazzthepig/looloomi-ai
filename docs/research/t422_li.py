"""T-422:探一下本机 load_inputs 能不能跑起来(开关关)。"""
import asyncio
import sys
import traceback

sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai-lane-b")
import pandas as pd  # noqa: E402

from src.data.cis.rebuild import load_inputs  # noqa: E402

D = pd.Timestamp("2026-11-19")
try:
    assets, data = asyncio.run(load_inputs(D))
    print("OK keys:", sorted(data.keys()))
    for k in ("crypto", "tradfi", "static", "macro", "funding", "tvl"):
        v = data.get(k)
        print(k, type(v).__name__, len(v) if hasattr(v, "__len__") else v)
except Exception as e:  # noqa: BLE001
    print("RAISED:", type(e).__name__, str(e)[:400])
    traceback.print_exc(limit=6)
