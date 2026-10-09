"""S-529 / T-078:每个 CIS 信号的归因 —— 事件、驱动、结果、汇总。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.cis.signal_attribution import (  # noqa: E402
    COLUMNS, beta_at, build_rows, drivers, ew_index, find_events, group_of, outcomes, track_record)


def _row(sym, d, sig, score=50.0, cls="L1", **p):
    base = {"symbol": sym, "d": d, "signal": sig, "score": score, "asset_class": cls, "grade": "B"}
    base.update({f"pillar_{k}": v for k, v in p.items()})
    return base


def test_events_are_changes_only_and_skip_first_appearance() -> None:
    rows = [_row("A", "2025-05-01", "NEUTRAL"), _row("A", "2025-05-02", "NEUTRAL"),
            _row("A", "2025-05-04", "OUTPERFORM"), _row("A", "2025-05-05", "OUTPERFORM"),
            _row("B", "2025-05-03", "UNDERPERFORM")]
    ev = find_events(rows)
    assert len(ev) == 1 and ev[0]["symbol"] == "A" and ev[0]["cur"]["d"] == "2025-05-04"
    assert ev[0]["prev"]["d"] == "2025-05-02", "「之前」= 上一个有记录的日子"


def test_drivers_weighted_contributions_and_residual() -> None:
    prev = _row("A", "2025-05-01", "NEUTRAL", 50.0, f=50, m=40, o=50, s=50, a=50)
    cur = _row("A", "2025-05-02", "OUTPERFORM", 60.0, f=50, m=70, o=50, s=50, a=60)
    d = drivers(cur, prev)
    assert d["contrib"]["M"] == 7.5 and d["contrib"]["A"] == 1.0 and d["contrib"]["F"] == 0.0
    assert d["top_driver"] == "M" and d["d_score"] == 10.0 and d["contrib_residual"] == 1.5
    assert d["weights"] == "base:L1"
    cur2 = dict(cur, pillar_o=None, asset_class="Gaming")
    d2 = drivers(cur2, prev)
    assert d2["contrib"]["O"] is None, "缺支柱不补 0"
    assert d2["weights"] == "base:default"


def test_group_of() -> None:
    assert group_of("L2") == "crypto" and group_of("Memecoin") == "crypto"
    assert group_of("US Bond") == "tradfi:US Bond" and group_of(None) == "tradfi:unknown"


def _panel():
    days = pd.date_range("2025-01-01", "2025-07-01", freq="D")
    rng = np.random.default_rng(1)
    btc = 100 * np.cumprod(1 + rng.normal(0, 0.02, len(days)))
    a = 50 * np.cumprod(1 + np.r_[0, 2 * (btc[1:] / btc[:-1] - 1)])   # 日收益恰好 2 × BTC
    b = 20 * np.cumprod(1 + rng.normal(0, 0.02, len(days)))
    return pd.DataFrame({"BTC": btc, "A": a, "B": b}, index=days)


def test_beta_and_outcomes() -> None:
    px = _panel()
    d = pd.Timestamp("2025-05-01")
    beta = beta_at(px["A"], px["BTC"], d)
    assert beta is not None and abs(beta - 2.0) < 0.05, "A 的日收益 = 2 × BTC ⇒ β ≈ 2"
    idx = ew_index(px[["A", "B", "BTC"]])
    last = pd.Timestamp("2025-05-20")
    out = outcomes("A", d, px, idx, px["BTC"], last)
    assert out["matured_7"] is True and out["matured_30"] is False and "ret_30" not in out, "没到期不填数"
    r7 = px.at[d + pd.Timedelta(days=7), "A"] / px.at[d, "A"] - 1
    assert abs(out["ret_7"] - r7) < 1e-12
    assert abs(out["rel_7"] - (out["ret_7"] - out["univ_7"])) < 1e-12
    assert abs(out["alpha_7"] - (out["ret_7"] - out["beta_btc"] * out["btc_7"])) < 1e-12
    assert outcomes("ZZZ", d, px, idx, None, last) == {"note": "信号日没有收盘价 —— 只记驱动"}


def test_build_rows_full_columns_and_track_record() -> None:
    px = _panel()
    idx = ew_index(px[["A", "B"]])
    rows = [_row("A", "2025-04-01", "NEUTRAL", f=50, m=50, o=50, s=50, a=50),
            _row("A", "2025-04-02", "OUTPERFORM", 66, f=50, m=80, o=50, s=50, a=50),
            _row("B", "2025-04-01", "NEUTRAL"), _row("B", "2025-04-02", "UNDERPERFORM", 40),
            _row("SPY", "2025-04-01", "NEUTRAL", cls="US Equity"), _row("SPY", "2025-04-02", "OUTPERFORM", cls="US Equity")]
    out = build_rows(find_events(rows), {"crypto": (px, idx)}, px["BTC"])
    assert len(out) == 3 and all(tuple(r) == COLUMNS for r in out), "每行补齐全部列"
    spy = [r for r in out if r["symbol"] == "SPY"][0]
    assert spy["grp"] == "tradfi:US Equity" and spy["ret_7"] is None and "没有价格源" in spy["note"]
    tr = track_record(out)
    assert tr["crypto"]["OUTPERFORM"]["30d"]["n"] == 1 and "btc_below_ma50" in tr["crypto"]["OUTPERFORM"]
    assert tr["tradfi"]["OUTPERFORM"]["30d"] == {"n": 0}
