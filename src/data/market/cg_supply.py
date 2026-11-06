"""供给的两件事(CoinGecko Analyst,Jazz 11-06「先把 Analyst API 用足」):

1. **未流通的那一截(`/coins/{id}/supply_breakdown`)。** S-587 已证「**已经发生**的稀释(过去 13 周流通量增长)之后跑输」,
   在留出段复现;但那是后视镜。供给拆分给的是**还没放出来的**:非流通量、锁仓钱包各自多少、哪一个异常。
   非流通 ÷ 总量 = 悬在头上的供给;它逐日变小 = 正在解锁 —— 这是被迫的供给(原因层),不是价格倒影。
   **没有历史 ⇒ 前向积累。** 宇宙 = 时点宇宙里最近 3 天还有市值的币,按市值取前 `MAX_COINS`;没有拆分的币(404)本进程内记住、不再问。
2. **新上的币(`/coins/list/new`,最近 200 个)。** 每天新上多少个 = 注意力与流动性被摊薄的速度。首个快照自带几天历史,此后前向。

判活:`select d, count(*) from coin_supply_daily group by 1 order by 1 desc limit 3` 与 `select count(*), max(activated_at) from cg_new_coins`。
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, Optional

SUPPLY_TABLE = "coin_supply_daily"
NEW_TABLE = "cg_new_coins"
WRITES_TABLES = (SUPPLY_TABLE, NEW_TABLE)
WRITES_COLUMNS = {SUPPLY_TABLE: ("d", "coin_id", "total_supply", "circulating_supply", "non_circulating_supply", "n_wallets",
                                 "anomaly", "cg_updated_at", "fetched_at"),
                  NEW_TABLE: ("coin_id", "symbol", "name", "activated_at", "first_seen_at")}
LOOP_NAME = "_cg_supply_loop"
UNIVERSE_VIEW = "cg_coin_mcap_coins"
MAX_COINS = 300
PAUSE_S = 0.15
_NO_BREAKDOWN: set[str] = set()                                            # 本进程内问过、没有拆分的币


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def supply_row(payload: Any, d: str, fetched_at: str) -> Optional[dict]:
    """纯函数。supply_breakdown → 一行;总量或流通量缺 ⇒ None(不编)。"""
    if not isinstance(payload, dict):
        return None
    sd = payload.get("supply_data") or {}
    tot, circ = _f(sd.get("total_supply")), _f(sd.get("circulating_supply"))
    if not payload.get("id") or not tot or tot <= 0 or circ is None:
        return None
    wallets = [w for w in (payload.get("non_circulating_wallets") or []) if isinstance(w, dict)]
    return {"d": d, "coin_id": str(payload["id"])[:120], "total_supply": tot, "circulating_supply": circ,
            "non_circulating_supply": _f(sd.get("non_circulating_supply")), "n_wallets": len(wallets),
            "anomaly": any(bool(w.get("anomaly")) for w in wallets), "cg_updated_at": sd.get("last_updated") or None,
            "fetched_at": fetched_at}


def new_coin_rows(payload: Any, fetched_at: str) -> list[dict]:
    """纯函数。/coins/list/new → 行;activated_at 是 unix 秒。"""
    out = []
    for c in payload if isinstance(payload, list) else []:
        try:
            ts = dt.datetime.fromtimestamp(int(c["activated_at"]), tz=dt.timezone.utc).isoformat()
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        if c.get("id"):
            out.append({"coin_id": str(c["id"])[:120], "symbol": str(c.get("symbol") or "")[:40], "name": str(c.get("name") or "")[:120],
                        "activated_at": ts, "first_seen_at": fetched_at})
    return out


def pick(universe: list[dict], today: dt.date) -> list[str]:
    """纯函数。最近 3 天还有市值的币,按最后市值取前 MAX_COINS,去掉本进程已知没有拆分的。"""
    live = [u for u in universe if u.get("last_d") and (today - dt.date.fromisoformat(str(u["last_d"])[:10])).days <= 3]
    live.sort(key=lambda u: -(u.get("last_mcap") or 0))
    return [u["coin_id"] for u in live if u["coin_id"] not in _NO_BREAKDOWN][:MAX_COINS]


async def run_once(now: Optional[dt.datetime] = None, fetch=None, read=None, upsert=None) -> dict[str, Any]:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    real = fetch is None
    if fetch is None:
        from src.data.market.data_layer import CG_API_KEY, CG_PRO_BASE, _cg_headers, _get_cg_client
        if not CG_API_KEY:
            return {"ok": False, "refused": True, "why": "COINGECKO_API_KEY 没配"}

        async def fetch(path: str, params: Optional[dict] = None):
            r = await _get_cg_client().get(f"{CG_PRO_BASE}{path}", headers=_cg_headers(), params=params or {}, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
    if read is None:
        from src.data.style.header import _read_all as read
    if upsert is None:
        from src.api.store import supabase_upsert_table as upsert
    stamp, d = now.isoformat(), now.date().isoformat()
    new_rows = new_coin_rows(await fetch("/coins/list/new"), stamp)
    new_ok = True
    if new_rows:
        # 第一次看见的时间不能被后来的轮次覆盖 ⇒ 只插新的
        have = {r["coin_id"] for r in await read(NEW_TABLE, {"select": "coin_id", "coin_id": f"in.({','.join(r['coin_id'] for r in new_rows)})"})}
        fresh = [r for r in new_rows if r["coin_id"] not in have]
        new_ok = (not fresh) or bool(await upsert(NEW_TABLE, fresh, on_conflict="coin_id"))
    coins = pick(await read(UNIVERSE_VIEW, {"select": "coin_id,last_d,last_mcap"}), now.date())
    rows, missing, errors = [], 0, 0
    for c in coins:
        failed = False
        try:
            p = await fetch(f"/coins/{c}/supply_breakdown")
        except Exception:                                                 # noqa: BLE001
            errors, failed, p = errors + 1, True, None
        r = supply_row(p, d, stamp) if p is not None else None
        if p is None and not failed:
            _NO_BREAKDOWN.add(c)                                          # 404 = 这个币没有拆分;出错的下轮再问
        if r:
            rows.append(r)
        else:
            missing += 1
        if real:
            await asyncio.sleep(PAUSE_S)
    if rows and not await upsert(SUPPLY_TABLE, rows, on_conflict="d,coin_id"):
        return {"ok": False, "why": f"写 {SUPPLY_TABLE} 失败"}
    return {"ok": bool(rows) and new_ok, "supply_rows": len(rows), "no_breakdown": missing, "errors": errors, "new_coins_seen": len(new_rows),
            "why": f"拆分 {len(rows)} / 问了 {len(coins)} 个币(没有拆分 {missing},错 {errors})· 新币快照 {len(new_rows)} 个"
                   + ("" if new_ok else " · 新币写入失败")}
