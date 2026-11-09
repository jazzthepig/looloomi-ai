"""强平地图(T-221,11-02)—— 头部账户的强平价离现价多远,按距离分档汇总;主机算,只送汇总(没有地址)。

## 为什么

链上是透明的:HL 上每个账户的持仓、杠杆、强平价都是公开的。被迫卖出的人是价格的原因(ARCHITECTURE「更靠近原因」)。
东京主机的 whales 进程(T-130)每 15 分钟记前 200 个头部账户的持仓;这里把最近一轮的持仓按「强平价离现价的距离」分档:
多头的强平价在现价下方(价格跌到那里被迫卖),空头在上方(被迫买)。每档 = 名义额(|持仓| × 现价)与仓位数。

Railway 把它和永续 ±2% 深度(`venue_depth_snapshots`)放在一起:跌 5% / 10% / 15% 时,被迫卖出的名义额是盘口深度的几倍。

## 规则

- 每个地址只取最近一次快照(30 分钟内;whales 每轮查一半名单,所以要两轮拼一张图);
- 档位 0–2%、2–5%、5–10%、10–15%、15–20%、20% 以上不算(不是近处的风险);没有强平价的仓位(全仓低杠杆常见)单列「无强平价」;
- **不送地址**:只送 (币, 方向, 档位) 的汇总;
- 只认名义额前 15 的币。
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Iterable, Optional

BANDS = ((0.0, 0.02), (0.02, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20))
FRESH_MS = 30 * 60 * 1000
TOP_COINS = 15


def _f(x: Any) -> Optional[float]:
    try:
        v = None if x is None else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is None or v == v else None


def latest_positions(records: Iterable[dict], now_ms: int) -> list[dict]:
    """纯函数。每个地址只留最近一次快照(FRESH_MS 内)的全部仓位。"""
    last: dict[str, int] = {}
    recs = [r for r in records if isinstance(r, dict) and r.get("address") and r.get("ts")]
    for r in recs:
        if now_ms - int(r["ts"]) <= FRESH_MS:
            last[r["address"]] = max(last.get(r["address"], 0), int(r["ts"]))
    return [r for r in recs if last.get(r["address"]) == int(r["ts"])]


def buckets(positions: list[dict], mids: dict[str, float]) -> list[dict]:
    """纯函数。仓位 + 现价 → (币, 方向, 档位) 的名义额与仓位数。现价没有的币不算。"""
    agg: dict[tuple, dict] = {}
    totals: dict[str, float] = {}
    for p in positions:
        coin, szi, liq = p.get("coin"), _f(p.get("szi")), _f(p.get("liquidationPx"))
        mark = _f(mids.get(coin))
        if not coin or not szi or not mark or mark <= 0:
            continue
        side = "long" if szi > 0 else "short"
        notional = abs(szi) * mark
        totals[coin] = totals.get(coin, 0.0) + notional
        if liq is None or liq <= 0:
            key = (coin, side, None, None)
        else:
            dist = (mark - liq) / mark if side == "long" else (liq - mark) / mark
            band = next(((lo, hi) for lo, hi in BANDS if lo <= dist < hi), None)
            if dist < 0:
                band = BANDS[0]                     # 已经越过强平价还没被强平(数据时差)—— 算进最近的一档
            if band is None:
                continue
            key = (coin, side, band[0], band[1])
        a = agg.setdefault(key, {"notional_usd": 0.0, "n_positions": 0})
        a["notional_usd"] += notional
        a["n_positions"] += 1
    keep = {c for c, _ in sorted(totals.items(), key=lambda kv: -kv[1])[:TOP_COINS]}
    return [{"coin": c, "side": s, "band_lo": lo, "band_hi": hi, "notional_usd": round(v["notional_usd"], 2),
             "n_positions": v["n_positions"], "mark": mids.get(c)}
            for (c, s, lo, hi), v in sorted(agg.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] if kv[0][2] is not None else 9))
            if c in keep]


POS_TOP_COINS = 40


def positioning(positions: list[dict], mids: dict[str, float], top: int = POS_TOP_COINS) -> list[dict]:
    """纯函数(11-09,S-794)。头部账户最近一轮的**全部**仓位 → 每个币的多 / 空名义额、仓位数、持有它的账户数。

    与 `buckets` 的区别:`buckets` 只收强平价在 20% 以内的仓位(那是强平风险,不是持仓);这里不分距离,
    是「谁押了什么」的完整一面。**不送地址**:账户只计数。现价没有的币不算;只取多 + 空名义额前 `top` 的币。"""
    agg: dict[str, dict[str, Any]] = {}
    for p in positions:
        coin, szi = p.get("coin"), _f(p.get("szi"))
        mark = _f(mids.get(coin)) if coin else None
        if not coin or not szi or not mark or mark <= 0:
            continue
        a = agg.setdefault(coin, {"long_usd": 0.0, "short_usd": 0.0, "n_long": 0, "n_short": 0, "acct": set()})
        notional = abs(szi) * mark
        if szi > 0:
            a["long_usd"] += notional
            a["n_long"] += 1
        else:
            a["short_usd"] += notional
            a["n_short"] += 1
        if p.get("address"):
            a["acct"].add(p["address"])
    keep = sorted(agg, key=lambda c: -(agg[c]["long_usd"] + agg[c]["short_usd"]))[:max(0, int(top))]
    return [{"coin": c, "long_usd": round(agg[c]["long_usd"], 2), "short_usd": round(agg[c]["short_usd"], 2),
             "n_long": agg[c]["n_long"], "n_short": agg[c]["n_short"], "n_accounts": len(agg[c]["acct"]),
             "mark": mids.get(c)} for c in sorted(keep)]


def read_records(rec_dir: Path, days: list[str]) -> list[dict]:
    """主机本地 whales 文件(gzip JSONL);读不到的那天跳过。"""
    out: list[dict] = []
    for day in days:
        p = rec_dir / f"{day}.jsonl.gz"
        if not p.exists():
            continue
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def shock_table(rows: list[dict], depth_2pct: dict[str, dict[str, float]], shocks=(0.05, 0.10, 0.15)) -> list[dict]:
    """纯函数(Railway 用)。跌 / 涨 x% 时会被强平的名义额,对永续 ±2% 深度的倍数。depth_2pct = {coin: {bid, ask}}。"""
    out = []
    for coin in sorted({r["coin"] for r in rows}):
        rs = [r for r in rows if r["coin"] == coin and r.get("band_lo") is not None]
        d = depth_2pct.get(coin) or {}
        for s in shocks:
            longs = sum(r["notional_usd"] for r in rs if r["side"] == "long" and r["band_lo"] < s)
            shorts = sum(r["notional_usd"] for r in rs if r["side"] == "short" and r["band_lo"] < s)
            out.append({"coin": coin, "shock": s, "forced_sell_usd": round(longs, 0), "forced_buy_usd": round(shorts, 0),
                        "sell_vs_bid_depth": round(longs / d["bid"], 2) if d.get("bid") else None,
                        "buy_vs_ask_depth": round(shorts / d["ask"], 2) if d.get("ask") else None})
    return out
