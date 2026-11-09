"""强平地图的 Railway 一侧(T-221,11-02):收主机送来的汇总(`kind = liqmap`)→ `hl_liq_map_hourly`;读的时候配上永续深度。

主机侧的口径见 `src/exec_host/liqmap.py`(头部账户最近一轮持仓,按强平价离现价的距离分档,不含地址)。
这里只做两件事:校验后按小时写一份(同一小时重送 = 覆盖成同一份);`latest_view` 把最近一小时的地图与
`venue_depth_snapshots` 里最近一批永续 ±2% 深度放在一起,算「跌 / 涨 5 / 10 / 15% 时被迫成交的名义额是深度的几倍」。

判活:`select ts, count(*) from hl_liq_map_hourly group by 1 order by 1 desc limit 3`(主机拉代码后每小时一批)。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

TABLE = "hl_liq_map_hourly"
POS_TABLE = "hl_whale_positioning_hourly"     # 11-09 S-794:同一批快照的完整持仓(不分强平距离)
WRITES_TABLES = (TABLE, POS_TABLE)
WRITES_COLUMNS = {TABLE: ("ts", "coin", "side", "band", "band_lo", "band_hi", "notional_usd", "n_positions", "mark"),
                  POS_TABLE: ("ts", "coin", "long_usd", "short_usd", "n_long", "n_short", "n_accounts", "mark",
                              "snapshot_accounts")}
MAX_ROWS = 400
MAX_POS_ROWS = 100


def _f(x: Any) -> Optional[float]:
    try:
        v = None if x is None else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is None or v == v else None


def band_key(lo: Optional[float], hi: Optional[float]) -> str:
    return "none" if lo is None else f"{lo * 100:g}-{hi * 100:g}"


def clean(rows: list, at: Any) -> tuple[list[dict], list[str]]:
    """纯函数。主机送来的行 → 表行;有问题的整批拒(返回原因)。"""
    bad: list[str] = []
    try:
        ts = dt.datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return [], ["detail.at 不是时间"]
    ts = ts.replace(minute=0, second=0, microsecond=0)
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        return [], [f"rows 要是列表、最多 {MAX_ROWS} 行"]
    out = []
    for k, r in enumerate(rows):
        if not isinstance(r, dict) or not str(r.get("coin") or "").strip() or r.get("side") not in ("long", "short"):
            bad.append(f"rows[{k}] 缺币名或方向")
            continue
        lo, hi, n = _f(r.get("band_lo")), _f(r.get("band_hi")), _f(r.get("notional_usd"))
        if n is None or n < 0 or (lo is None) != (hi is None):
            bad.append(f"rows[{k}] 名义额或档位不对")
            continue
        if "address" in r or "user" in r:
            bad.append(f"rows[{k}] 带了地址 —— 只收汇总")
            continue
        out.append({"ts": ts.isoformat(), "coin": str(r["coin"])[:20], "side": r["side"], "band": band_key(lo, hi),
                    "band_lo": lo, "band_hi": hi, "notional_usd": round(n, 2),
                    "n_positions": int(_f(r.get("n_positions")) or 0), "mark": _f(r.get("mark"))})
    return (out, bad) if not bad else ([], bad)


def clean_positioning(rows: list, at: Any, snapshot_accounts: Any = None) -> tuple[list[dict], list[str]]:
    """纯函数(11-09,S-794)。主机送来的每币持仓汇总 → 表行;有问题整批拒。带地址的行拒收(只收汇总)。"""
    bad: list[str] = []
    try:
        ts = dt.datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return [], ["detail.at 不是时间"]
    ts = ts.replace(minute=0, second=0, microsecond=0)
    if not isinstance(rows, list) or len(rows) > MAX_POS_ROWS:
        return [], [f"positioning 要是列表、最多 {MAX_POS_ROWS} 行"]
    snap = _f(snapshot_accounts)
    out, seen = [], set()
    for k, r in enumerate(rows):
        coin = str((r or {}).get("coin") or "").strip() if isinstance(r, dict) else ""
        if not coin or coin in seen:
            bad.append(f"positioning[{k}] 缺币名或重复")
            continue
        if "address" in r or "user" in r or "addresses" in r:
            bad.append(f"positioning[{k}] 带了地址 —— 只收汇总")
            continue
        lu, su = _f(r.get("long_usd")), _f(r.get("short_usd"))
        if lu is None or su is None or lu < 0 or su < 0:
            bad.append(f"positioning[{k}] 名义额不对")
            continue
        seen.add(coin)
        out.append({"ts": ts.isoformat(), "coin": coin[:20], "long_usd": round(lu, 2), "short_usd": round(su, 2),
                    "n_long": int(_f(r.get("n_long")) or 0), "n_short": int(_f(r.get("n_short")) or 0),
                    "n_accounts": int(_f(r.get("n_accounts")) or 0), "mark": _f(r.get("mark")),
                    "snapshot_accounts": int(snap) if snap is not None else None})
    return (out, bad) if not bad else ([], bad)


async def write_positioning(rows: list, at: Any, snapshot_accounts: Any = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    out, bad = clean_positioning(rows, at, snapshot_accounts)
    if bad:
        return {"ok": False, "bad": bad[:10]}
    if not out:
        return {"ok": True, "written": 0}
    w = await supabase_upsert_table(POS_TABLE, out, on_conflict="ts,coin")
    return {"ok": bool(w), "written": len(out) if w else 0, **({} if w else {"why": (getattr(w, "why", "") or "")[:200]})}


async def write_rows(rows: list, at: Any) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    out, bad = clean(rows, at)
    if bad:
        return {"ok": False, "bad": bad[:10]}
    if not out:
        return {"ok": True, "written": 0}
    w = await supabase_upsert_table(TABLE, out, on_conflict="ts,coin,side,band")
    return {"ok": bool(w), "written": len(out) if w else 0, **({} if w else {"why": (getattr(w, "why", "") or "")[:200]})}


async def latest_view() -> dict[str, Any]:
    from src.exec_host.liqmap import shock_table
    from src.data.style.header import _read_all
    last = await _read_all(TABLE, {"select": "ts", "order": "ts.desc", "limit": "1"})
    if not last:
        return {"ok": True, "ts": None, "why": "还没有强平地图(主机拉代码后每小时一批)"}
    ts = last[0]["ts"]
    rows = await _read_all(TABLE, {"select": "coin,side,band,band_lo,band_hi,notional_usd,n_positions,mark", "ts": f"eq.{ts}"})
    dep = await _read_all("venue_depth_snapshots", {"select": "fetched_utc", "venue": "eq.hyperliquid_perp",
                                                    "order": "fetched_utc.desc", "limit": "1"})
    depth: dict[str, dict[str, float]] = {}
    if dep:
        for r in await _read_all("venue_depth_snapshots", {"select": "symbol,depth_2pct_bid_usd,depth_2pct_ask_usd",
                                                            "venue": "eq.hyperliquid_perp", "fetched_utc": f"eq.{dep[0]['fetched_utc']}"}):
            depth[r["symbol"]] = {"bid": _f(r.get("depth_2pct_bid_usd")), "ask": _f(r.get("depth_2pct_ask_usd"))}
    return {"ok": True, "ts": ts, "depth_at": dep[0]["fetched_utc"] if dep else None,
            "shocks": shock_table(rows, depth), "rows": rows}
