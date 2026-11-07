"""散户注意力尖峰的前向记录(S-769 B ✅ 之后,11-07)—— 对手盘族里第一条「按币的散户注意力」。

## 研究说了什么

Santiment 社交量相对自身前 90 天 z ≥ 3 的那天(同代号 30 天去重),之后 30 天相对篮子中位 −8.75%、为负 71%、随机日对照分位 0.000
(n 510,2025-10 → 2026-10)。**但** 同一批币随便哪天进场都跑输(零分布中位 −6.5%),尖峰本身只多跑输约 2.2pp;样本只有一个行情段。
按预注册只立前向记录,不进任何规则。

## 口径(lane-a `docs/research/t290_attention.py` 的 `build_events` B 臂与 `arm_stats` 原样)

- 事件:`social_daily` source = santiment、metric = social_volume_total;每个 (代号, d):前 90 天内(严格更早)≥ 60 个观测,
  z =(当天 − 均值)/ 样本标准差(ddof 1),z ≥ 3;同代号 30 天内只取第一次。
- 结果:进场 d+1 收盘,出场 d+8 / d+31 收盘(`asset_mcap_daily`,按代号);篮子 = d 当天有价且市值 ≥ 2,000 万的全部币,
  同一进出日的等权收益;超额 = 代币 − 篮子。没价就空着,不写 0。
- cohort:d ≥ `FORWARD_FROM`(S-769 用的数据到 2026-10-08)= forward;之前 = backfill(只作对照)。
  **Santiment 免费档滞后 30 天**,所以新的事件最早在发生后约一个月才进表 —— 这是数据的滞后,不是前视。

判活:`select cohort, count(*), count(excess_30d), max(d) from attention_watch group by 1`。
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from typing import Any, Optional

TABLE = "attention_watch"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("symbol", "d", "z", "cohort", "excess_7d", "excess_30d", "basket_n", "code_ref", "settled_at")}
CODE_REF = "attention_watch v1 (11-07, S-769 B / T-290)"
FORWARD_FROM = dt.date(2026, 10, 9)
Z_THR = 3.0
LOOKBACK_D = 90
MIN_OBS = 60
DEDUPE_D = 30
MCAP_MIN = 20_000_000
PRICE_TABLE = "asset_mcap_daily"


def spikes(series: dict[str, dict[str, float]], thr: float = Z_THR) -> list[tuple[str, str, float]]:
    """纯函数。{代号: {d: 社交量}} → [(代号, d, z)](t290 build_events 的 z_events,sign +1、ddof 1,30 天去重)。"""
    cands = []
    for sym, ser in series.items():
        ds = sorted(ser)
        for i, d in enumerate(ds):
            lo = (dt.date.fromisoformat(d) - dt.timedelta(days=LOOKBACK_D)).isoformat()
            prior = [ser[x] for x in ds[:i] if x >= lo]
            if len(prior) < MIN_OBS:
                continue
            m = sum(prior) / len(prior)
            sd = math.sqrt(sum((p - m) ** 2 for p in prior) / max(1, len(prior) - 1))
            if sd <= 0:
                continue
            z = (ser[d] - m) / sd
            if z >= thr:
                cands.append((sym, d, z))
    out, last = [], {}
    for sym, d, z in sorted(cands, key=lambda x: (x[0], x[1])):
        do = dt.date.fromisoformat(d)
        if sym in last and (do - last[sym]).days < DEDUPE_D:
            continue
        last[sym] = do
        out.append((sym, d, z))
    return out


def excess(sym: str, d: str, px: dict[str, dict[str, tuple]], by_date: dict[str, dict[str, tuple]], h: int) -> tuple[Optional[float], Optional[int]]:
    """纯函数。进场 d+1 收盘 → d+1+h 收盘;篮子 = d 当天市值 ≥ 2,000 万、进出都有价的等权。→ (超额, 篮子数);没价 ⇒ (None, None)。"""
    do = dt.date.fromisoformat(d)
    e_d, x_d = (do + dt.timedelta(days=1)).isoformat(), (do + dt.timedelta(days=1 + h)).isoformat()
    ser = px.get(sym, {})
    e, x = ser.get(e_d), ser.get(x_d)
    if not e or not x or not e[0] or not x[0]:
        return None, None
    rets = []
    for s2, (p, m) in (by_date.get(d) or {}).items():
        if p is None or m is None or m < MCAP_MIN:
            continue
        e2, x2 = px.get(s2, {}).get(e_d), px.get(s2, {}).get(x_d)
        if e2 and x2 and e2[0] and x2[0]:
            rets.append(x2[0] / e2[0] - 1)
    if not rets:
        return None, None
    return round((x[0] / e[0] - 1) - sum(rets) / len(rets), 6), len(rets)


def rows(events: list[tuple[str, str, float]], px, by_date, today: dt.date) -> list[dict]:
    """纯函数。事件 → 表行;到期且有价才结算。"""
    out = []
    for sym, d, z in events:
        do = dt.date.fromisoformat(d)
        r = {"symbol": sym, "d": d, "z": round(z, 3), "cohort": "forward" if do >= FORWARD_FROM else "backfill",
             "excess_7d": None, "excess_30d": None, "basket_n": None, "code_ref": CODE_REF, "settled_at": None}
        if (today - do).days > 8:
            r["excess_7d"], _ = excess(sym, d, px, by_date, 7)
        if (today - do).days > 31:
            r["excess_30d"], r["basket_n"] = excess(sym, d, px, by_date, 30)
            if r["excess_30d"] is not None:
                r["settled_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        out.append(r)
    return out


async def run_once(now: Optional[dt.datetime] = None, read=None, upsert=None) -> dict[str, Any]:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    if read is None:
        from src.data.style.header import _read_all as read
    if upsert is None:
        from src.api.store import supabase_upsert_table as upsert
    soc = await read("social_daily", {"select": "symbol,d,value", "source": "eq.santiment", "metric": "eq.social_volume_total",
                                      "order": "symbol.asc,d.asc"})
    series: dict[str, dict[str, float]] = defaultdict(dict)
    for r in soc or []:
        if r.get("value") is not None:
            series[str(r["symbol"]).upper()][str(r["d"])[:10]] = float(r["value"])
    ev_all = spikes(series)
    if not ev_all:
        return {"ok": False, "refused": True, "why": f"social_daily 里算不出尖峰({len(soc or [])} 行)"}
    # 已结算(30 天有值)的不再重算 —— 每轮只处理新事件与没结算完的(省掉几百次截面读)
    have = await read(TABLE, {"select": "symbol,d,excess_30d", "order": "symbol.asc,d.asc"})
    settled = {(r["symbol"], str(r["d"])[:10]) for r in have or [] if r.get("excess_30d") is not None}
    ev = [e for e in ev_all if (e[0], e[1]) not in settled]
    if not ev:
        return {"ok": True, "written": 0, "events": len(ev_all), "why": f"{len(ev_all)} 个尖峰都已结算,没有新的"}
    # 价:每个事件日需要 d(篮子成员)、d+1、d+8、d+31 四天的整张截面
    days = sorted({(dt.date.fromisoformat(d) + dt.timedelta(days=k)).isoformat() for _, d, _ in ev for k in (0, 1, 8, 31)
                   if dt.date.fromisoformat(d) + dt.timedelta(days=k) <= now.date()})
    px: dict[str, dict[str, tuple]] = defaultdict(dict)
    by_date: dict[str, dict[str, tuple]] = defaultdict(dict)
    for i in range(0, len(days), 20):
        chunk = days[i:i + 20]
        got = await read(PRICE_TABLE, {"select": "symbol,d,price,mcap", "d": f"in.({','.join(chunk)})", "order": "symbol.asc,d.asc"})
        for r in got or []:
            s, d = str(r["symbol"]).upper(), str(r["d"])[:10]
            if d in px[s]:
                continue
            rec = (r.get("price"), r.get("mcap"))
            px[s][d] = rec
            by_date[d][s] = rec
    out = rows(ev, px, by_date, now.date())
    for i in range(0, len(out), 500):
        if not await upsert(TABLE, out[i:i + 500], on_conflict="symbol,d"):
            return {"ok": False, "why": f"写 {TABLE} 失败"}
    fwd = sum(1 for r in out if r["cohort"] == "forward")
    s30 = sum(1 for r in out if r["excess_30d"] is not None)
    latest = max((max(v) for v in series.values() if v), default=None)
    return {"ok": True, "written": len(out), "events": len(ev_all), "forward": fwd, "settled_30d_this_run": s30,
            "why": f"{len(ev_all)} 个尖峰,本轮写 {len(out)}(前向 {fwd})· 本轮新结算 {s30} · 社交量最新一天 {latest}"}
