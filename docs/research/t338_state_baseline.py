#!/usr/bin/env python3
"""T-338 补充(§Seth-1111h):情景文件里 `state:<feature>` 的基准率。

结算器(`src/data/evaluation/scenario_ledger.py::_value`)读的是
`state_daily` 里 `entity='panel'`、`feature=<key>`、`d=<horizon>` 的 `value`。
所以基准率必须**用同一条序列**算,不能拿别的口径(30 日均值)顶替。

只读:只调用 `src.data.style.header._read_all`(自带 order= 与 1000 行/页分页)。
产物:`docs/research/t338_state_baseline.json`。
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.style.header import _read_all  # noqa: E402

FEATURES = ("funding_7d_ann", "funding_7d_ann_binance")
OUT = Path(__file__).resolve().parent / "t338_state_baseline.json"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


async def panel_features() -> dict:
    rows = await _read_all(
        "state_daily",
        {"select": "feature,d,value", "entity": "eq.panel", "order": "feature.asc,d.asc"},
    )
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(str(r.get("feature")), []).append(r)
    out = {}
    for feat, rs in sorted(by.items()):
        vals = [v for v in (_f(r.get("value")) for r in rs) if v is not None]
        ds = [str(r.get("d"))[:10] for r in rs]
        out[feat] = {
            "n_rows": len(rs),
            "n_value": len(vals),
            "first_d": min(ds) if ds else None,
            "last_d": max(ds) if ds else None,
            "min": min(vals) if vals else None,
            "median": statistics.median(vals) if vals else None,
            "max": max(vals) if vals else None,
            "positive_rate": round(sum(1 for v in vals if v > 0) / len(vals), 6) if vals else None,
        }
    return out


async def series(feat: str) -> list:
    rows = await _read_all(
        "state_daily",
        {"select": "d,value", "entity": "eq.panel", "feature": f"eq.{feat}", "order": "d.asc"},
    )
    out = []
    for r in rows:
        v = _f(r.get("value"))
        if v is not None:
            out.append((str(r.get("d"))[:10], v))
    return out


async def macro_series() -> dict:
    rows = await _read_all("macro_daily", {"select": "series,d,value", "order": "series.asc,d.asc"})
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(str(r.get("series")), []).append((str(r.get("d"))[:10], _f(r.get("value"))))
    out = {}
    for s, rs in sorted(by.items()):
        vals = [v for _, v in rs if v is not None]
        out[s] = {
            "n": len(rs),
            "first_d": min(d for d, _ in rs),
            "last_d": max(d for d, _ in rs),
            "last_value": rs[-1][1] if rs else None,
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
        }
    return out


async def btc_close(n: int = 5) -> list:
    rows = await _read_all(
        "ohlcv_daily",
        {"select": "trade_date,close", "symbol": "eq.BTC", "source": "eq.binance_hist",
         "order": "trade_date.desc"},
    )
    out = []
    for r in rows[:n]:
        out.append({"trade_date": str(r.get("trade_date"))[:10], "close": _f(r.get("close"))})
    return out


async def btc_close_all() -> list:
    rows = await _read_all(
        "ohlcv_daily",
        {"select": "trade_date,close", "symbol": "eq.BTC", "source": "eq.binance_hist",
         "order": "trade_date.asc"},
    )
    out = []
    for r in rows:
        v = _f(r.get("close"))
        if v is not None:
            out.append((str(r.get("trade_date"))[:10], v))
    return out


async def ledger_rows_t338() -> list:
    """情景台账里是否已经有 T-338 的行(有就不能改旧条目的口径)。只读,读不到不算 0 行。"""
    try:
        rows = await _read_all("scenario_ledger", {"select": "id,variable,horizon_d", "id": "like.T-338*"})
        return [{"id": r.get("id"), "variable": r.get("variable"), "horizon_d": r.get("horizon_d")} for r in rows]
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)[:200]}]


async def main() -> int:
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")):
        print("缺 SUPABASE_URL / SUPABASE_KEY,退出")
        return 1

    feats = await panel_features()
    detail = {}
    for f in FEATURES:
        s = await series(f)
        if not s:
            detail[f] = {"n": 0}
            continue
        vals = [v for _, v in s]
        detail[f] = {
            "n": len(s),
            "first_d": s[0][0],
            "last_d": s[-1][0],
            "last_value": s[-1][1],
            "min": min(vals),
            "median": statistics.median(vals),
            "max": max(vals),
            "positive_rate": round(sum(1 for v in vals if v > 0) / len(vals), 6),
            "tail10": [{"d": d, "v": v} for d, v in s[-10:]],
        }
    macros = await macro_series()
    btc = await btc_close()
    btc_all = await btc_close_all()
    ledger = await ledger_rows_t338()

    # 基准率:情景条目用的每个阈值,都用与结算器同源的序列算
    def share(rows, thr, tail=None):
        rs = rows[-tail:] if tail else rows
        vals = [v for _, v in rs]
        if not vals:
            return None
        return round(sum(1 for v in vals if v > thr) / len(vals), 6)

    breadth = await series("breadth_above_ma50")
    fb = await series("funding_7d_ann_binance")
    fa = await series("funding_7d_ann")

    def persist(rows, thr, h=20):
        """条件基准率:今天收盘 > thr 的日子里,h 个交易日后仍 > thr 的比例(与命题同期数)。"""
        num = den = 0
        for i in range(len(rows) - h):
            if rows[i][1] > thr:
                den += 1
                if rows[i + h][1] > thr:
                    num += 1
        return {"n_cond": den, "share": round(num / den, 6) if den else None}

    def persist_from(rows, cond, thr, h=20):
        """条件基准率:满足 cond 的日子(起点状态)里,h 个交易日后 > thr 的比例。"""
        num = den = 0
        for i in range(len(rows) - h):
            if cond(rows[i][1]):
                den += 1
                if rows[i + h][1] > thr:
                    num += 1
        return {"n_cond": den, "share": round(num / den, 6) if den else None}

    baserates = {
        "state:funding_7d_ann_binance > 0": {
            "n": detail.get("funding_7d_ann_binance", {}).get("n"),
            "share": detail.get("funding_7d_ann_binance", {}).get("positive_rate"),
            "persist_20d": persist(fb, 0.0),
            "last_value": fb[-1][1] if fb else None,
            "last_d": fb[-1][0] if fb else None,
            "window": [detail.get("funding_7d_ann_binance", {}).get("first_d"),
                       detail.get("funding_7d_ann_binance", {}).get("last_d")]},
        "state:funding_7d_ann > 0": {
            "n": detail.get("funding_7d_ann", {}).get("n"),
            "share": detail.get("funding_7d_ann", {}).get("positive_rate"),
            "persist_20d": persist(fa, 0.0),
            "last_value": fa[-1][1] if fa else None,
            "last_d": fa[-1][0] if fa else None,
            "window": [detail.get("funding_7d_ann", {}).get("first_d"),
                       detail.get("funding_7d_ann", {}).get("last_d")]},
        "state:breadth_above_ma50 > 0.5": {
            "n": len(breadth), "share": share(breadth, 0.5),
            "persist_20d": persist(breadth, 0.5),
            "from_low_le_0.1": persist_from(breadth, lambda v: v <= 0.1, 0.5),
            "last_value": breadth[-1][1] if breadth else None,
            "last_d": breadth[-1][0] if breadth else None,
            "window": [breadth[0][0] if breadth else None, breadth[-1][0] if breadth else None]},
        "close:BTC > 65000": {
            "n": len(btc_all), "share": share(btc_all, 65000),
            "share_last_730d": share(btc_all, 65000, tail=730),
            "persist_20d": persist(btc_all, 65000),
            "window": [btc_all[0][0] if btc_all else None, btc_all[-1][0] if btc_all else None]},
        "close:BTC > 70000": {
            "n": len(btc_all), "share": share(btc_all, 70000),
            "share_last_730d": share(btc_all, 70000, tail=730),
            "persist_20d": persist(btc_all, 70000),
            "window": [btc_all[0][0] if btc_all else None, btc_all[-1][0] if btc_all else None]},
    }

    payload = {
        "as_of": date.today().isoformat(),
        "note": "只读;基准率与结算器读的是同一条 state_daily 序列(entity=panel)",
        "panel_features": feats,
        "funding_detail": detail,
        "macro_series": macros,
        "btc_close_latest": btc,
        "baserates": baserates,
        "scenario_ledger_t338_rows": ledger,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "as_of": payload["as_of"],
        "baserates": baserates,
        "btc_close_latest": btc,
        "scenario_ledger_t338_rows": ledger,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
