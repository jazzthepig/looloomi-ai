"""T-134 研究 = 实盘:回放只经实盘的那几个函数;计划与 Railway /plan 同源;止损用前一天的止损线;
零摩擦时回放持仓贴着目标走(差在 5% 调仓门槛与取整之内)。"""
import ast
import pathlib

import numpy as np
import pandas as pd

from src.data.execution import executor as ex
from src.data.execution.host_plan import make_plan
from src.exec_host import replay as rp

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _ohlc(n=520, seed=3, crash_at=None):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.02, n)))
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close}, index=idx)
    if crash_at is not None:
        df.iloc[crash_at, df.columns.get_loc("low")] = df["close"].iloc[crash_at - 1] * 0.5
    return df


def test_replay_goes_through_the_live_functions_only():
    tree = ast.parse((ROOT / "src/exec_host/replay.py").read_text(encoding="utf-8"))
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert {"make_plan", "core.plan_host_orders", "core.stop_hits"} <= calls
    hp = ast.parse((ROOT / "src/data/execution/host_plan.py").read_text(encoding="utf-8"))
    plan_core = next(n for n in ast.walk(hp) if isinstance(n, ast.AsyncFunctionDef) and n.name == "plan_core")
    assert "make_plan" in {ast.unparse(n.func) for n in ast.walk(plan_core) if isinstance(n, ast.Call)}, \
        "Railway /plan 也必须经 make_plan,否则回放与实盘收到的计划会分叉"


def test_plan_matches_the_kernel():
    o = {"BTC": _ohlc(), "ETH": _ohlc(seed=4)}
    closes = {s: df["close"] for s, df in o.items()}
    p = make_plan(closes, "2025-06-03")
    assert p["targets"] == {s: round(w, 6) for s, w in ex.target_weights(closes).items()}
    assert p["stop_px"]["BTC"] == ex.stop_price(closes["BTC"])


def test_frictionless_replay_tracks_targets_within_the_rebalance_band():
    o = {"BTC": _ohlc(), "ETH": _ohlc(seed=4)}
    r = rp.replay(o, "2024-08-01", account=3_000.0, nav_cap=None, half_spread_bps=0.0, fee_bps=0.0, stop_slip_bps=0.0)
    nav = r["nav"]
    assert len(nav) > 100 and r["trades"], "有信号、有成交"
    gap = (nav["w_BTC"] - nav["t_BTC"]).abs() + (nav["w_ETH"] - nav["t_ETH"]).abs()
    assert (gap <= 0.12).mean() > 0.95, "持仓与目标的偏离被调仓门槛(5% / 名)与取整限住"


def test_the_intraday_stop_uses_yesterdays_line_and_sells_everything():
    base = _ohlc()
    r0 = rp.replay({"BTC": base, "ETH": _ohlc(seed=4)}, "2024-08-01", nav_cap=None)
    held = r0["nav"][r0["nav"]["w_BTC"] > 0.2].index
    assert len(held), "测试前提:某天持有 BTC"
    crash_day = base.index.get_loc(pd.Timestamp(held[len(held) // 2])) + 1
    r = rp.replay({"BTC": _ohlc(crash_at=crash_day), "ETH": _ohlc(seed=4)}, "2024-08-01", nav_cap=None)
    hit = [s for s in r["stops"] if s["symbol"] == "BTC"]
    assert hit and hit[0]["d"] == str(base.index[crash_day])[:10]
    assert hit[0]["px"] <= hit[0]["line"], "按 min(开盘, 止损线) 减滑点卖"
    assert r["nav"].loc[hit[0]["d"], "w_BTC"] < 0.2 or r["nav"].loc[hit[0]["d"], "t_BTC"] > 0, \
        "止损当天清仓(收盘后若信号仍要持有才会再买回)"
