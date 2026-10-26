"""面板外 Binance 永续名字的市值 / 价格历史 —— 分开、慢慢补(S-689,Jazz 10-26)。

## 为什么

S-688 的诊断「OI / 市值越高,30 天超额越差」是在官方 24 个名字上、看完全样本才看到的,而且它和「市值小」
高度相关(lane-a 复核:截面 ρ ≈ −0.81)。要它算数,得在**没看过的名字**上、控制规模后再出现一次(S-689)。
`deriv_metrics_daily`(Binance Vision 归档)有 259 个名字的 OI;CoinGecko 价格 / 市值已在 `asset_mcap_daily`
的有 216 个;**缺的 43 个大多是已经下架的** —— 不补,检验就只剩「活下来的」,幸存者偏差正好偏向我们想看到的方向。

## Jazz 10-26:「可以补,但不可以暴力向 Binance 的 API 发起请求,分开来」

- **这一步对 Binance 零请求。** OI 已经在库里(Vision 的静态归档,早就落库);补的是 CoinGecko 的价格 / 市值。
- **CoinGecko 也分开打:** 每轮最多 `MAX_CALLS_PER_RUN` 次请求,轮与轮之间隔 `INTERVAL_S`。
  43 个名字、每个 1–3 个候选,大约半天补完;补完之后每轮只读一次本库的待办表,零外部请求。

## 怎么认对币(撞名是这里唯一会毁数据的错,见 cg_universe 的文档)

同一个 ticker 在 CoinGecko 上常有好几个币。**不猜,用价格对:** Binance 当天的隐含价
= `oi_value_close / oi_close`(当日 USD 持仓 ÷ 张数,本库就有);候选币的 CG 日收盘 × 倍数(`1000` 前缀 = 1000)
与它逐日比,重叠 ≥ `MIN_OVERLAP` 天、median 相对误差 ≤ `MAX_ERR` 才算这个币,只写这个币的行。
先验抽查:已在 `asset_mcap_daily` 的 216 个里,AI / REI / COMBO / 1000X / TON / CHESS 按 symbol 对上的是别的币 ——
同一把尺子会在 S-689 里把它们剔掉。

## 表

- `perp_cg_map`:每个待补的 Binance symbol 一行 —— 候选、试过哪些、选中哪个、误差、写了几行、结论
  (`pending` / `resolved` / `unresolved` / `too_many`)。种子由 Seth 写入(这 43 个);之后可以再加。
- `cg_coin_mcap_daily`(已有表,coin_id 键):选中币的日线价格与市值,source = coingecko_pro_market_chart,
  日期语义与风格表头相同(00:00 UTC 的点 = 前一天收盘)。不写 `asset_mcap_daily` —— 那张表有好几个
  按「全部 symbol」读的消费者(核心宇宙、容量、战场简报),塞进已下架的币会改它们的历史。

## 判活

    select verdict, count(*) from perp_cg_map group by 1;                       -- pending 递减到 0
    select count(distinct coin_id) from cg_coin_mcap_daily where coin_id in (select coin_id from perp_cg_map);
"""
from __future__ import annotations

import asyncio
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

MAP_TABLE = "perp_cg_map"
TABLE = "cg_coin_mcap_daily"
WRITES_TABLES = ("perp_cg_map", "cg_coin_mcap_daily")
SOURCE = "coingecko_pro_market_chart"

#: 每轮最多几次 CoinGecko 请求;轮间隔。Jazz 10-26「分开来」。
MAX_CALLS_PER_RUN = 3
INTERVAL_S = 600
#: 价格校验:重叠天数下限、median 相对误差上限。
MIN_OVERLAP = 30
MAX_ERR = 0.05
#: 一个 symbol 最多试几个候选;更多 ⇒ too_many(不硬试)。
MAX_CANDIDATES = 6
HISTORY_FROM = date(2022, 12, 1)
#: 名字里带的东西与 CoinGecko symbol 不同的几个(Binance 的叫法)。
SPECIAL_QUERY = {"LUNA2": "LUNA", "NEIROETH": "NEIRO"}


def query_symbol(binance_symbol: str) -> tuple[str, int]:
    """纯函数。Binance 合约的 base → (CoinGecko 上要找的 symbol, 价格倍数)。"""
    s = (binance_symbol or "").upper()
    if s in SPECIAL_QUERY:
        return SPECIAL_QUERY[s], 1
    m = re.fullmatch(r"(1000000|1000)([A-Z][A-Z0-9]*)", s)
    if m:
        return m.group(2), int(m.group(1))
    return s, 1


def order_candidates(query: str, ids: list[str]) -> list[str]:
    """纯函数。候选的试法:id 与 symbol 同名的先试,其余按 id 长度(短的多是原生币)—— 只决定**先后**,对不对由价格说了算。"""
    q = query.lower()
    return sorted(dict.fromkeys(ids), key=lambda i: (i.lower() != q, not i.lower().startswith(q), len(i), i))


def implied_prices(rows: list[dict]) -> dict[str, float]:
    """纯函数。deriv_metrics_daily 的行 → {d: 隐含价 = oi_value_close / oi_close}。"""
    out = {}
    for r in rows or []:
        v, n = r.get("oi_value_close"), r.get("oi_close")
        if v and n and float(n) > 0 and float(v) > 0:
            out[str(r["d"])[:10]] = float(v) / float(n)
    return out


def price_check(points: list[dict], implied: dict[str, float], mult: int) -> tuple[Optional[float], int]:
    """纯函数。CG 日线点([{d, price, ...}])对隐含价 → (median 相对误差, 重叠天数)。"""
    errs = [abs(float(p["price"]) * mult / implied[p["d"]] - 1.0)
            for p in points or [] if p.get("price") and p["d"] in implied and implied[p["d"]] > 0]
    return (statistics.median(errs) if errs else None), len(errs)


def accept(err: Optional[float], n: int) -> bool:
    return err is not None and n >= MIN_OVERLAP and err <= MAX_ERR


async def _coins_list(client, include_inactive: bool) -> dict[str, list[str]]:
    from src.data.market.cg_universe import index_listing
    from src.data.market.data_layer import CG_PRO_BASE, _cg_headers
    idx: dict[str, list[str]] = {}
    for status in (("active", "inactive") if include_inactive else ("active",)):
        r = await client.get(f"{CG_PRO_BASE}/coins/list", headers=_cg_headers(), params={"status": status}, timeout=40)
        r.raise_for_status()
        for k, v in index_listing(r.json() or []).items():
            idx.setdefault(k, []).extend(v)
    return idx


async def run_once(today: Optional[date] = None) -> dict[str, Any]:
    """一轮:读待办 → 必要时给没有候选的行补候选(1–2 次请求)→ 用剩下的额度按候选取日线、校验、写。"""
    from src.api.store import supabase_upsert_table
    from src.data.market.data_layer import _get_cg_client, get_cg_market_chart_range
    from src.data.style.header import _read_all, parse_market_chart
    today = today or datetime.now(timezone.utc).date()
    todo = await _read_all(MAP_TABLE, {"select": "*", "verdict": "eq.pending", "order": "symbol.asc"})
    if not todo:
        return {"ok": True, "refused": True, "calls": 0, "reason": "没有待补的名字"}
    calls, done, notes = 0, [], []

    need_cands = [r for r in todo if r.get("candidates") is None]
    if need_cands:
        client = _get_cg_client()
        idx = await _coins_list(client, include_inactive=True)
        calls += 2
        for r in need_cands:
            q, mult = query_symbol(r["symbol"])
            ids = order_candidates(q, idx.get(q, []))
            upd = {"symbol": r["symbol"], "query_symbol": q, "mult": mult, "candidates": ids,
                   "checked_at": datetime.now(timezone.utc).isoformat()}
            if not ids:
                upd.update(verdict="unresolved", note="no CoinGecko coin with this symbol (active or inactive)")
            elif len(ids) > MAX_CANDIDATES:
                upd.update(verdict="too_many", note=f"{len(ids)} candidates; not trying blind")
            r.update(upd)
            w = await supabase_upsert_table(MAP_TABLE, [upd], on_conflict="symbol")
            if not w.ok:
                return {"ok": False, "refused": False, "calls": calls, "reason": f"{MAP_TABLE} 写入失败:{w.why}"}

    for r in todo:
        if calls >= MAX_CALLS_PER_RUN:
            break
        if r.get("verdict") != "pending":
            continue
        tried = list(r.get("tried") or [])
        left = [c for c in (r.get("candidates") or []) if c not in tried]
        if not left:
            continue
        rows = await _read_all("deriv_metrics_daily", {"select": "d,oi_value_close,oi_close", "symbol": f"eq.{r['symbol']}",
                                                       "d": f"gte.{HISTORY_FROM.isoformat()}", "order": "d.asc"})
        implied = implied_prices(rows)
        if not implied:
            await supabase_upsert_table(MAP_TABLE, [{"symbol": r["symbol"], "verdict": "unresolved",
                                                     "note": "no Binance OI rows to check prices against",
                                                     "checked_at": datetime.now(timezone.utc).isoformat()}], on_conflict="symbol")
            continue
        last_oi = date.fromisoformat(max(implied))
        to_d = min(today, last_oi + timedelta(days=40))          # 下架之后再多取 40 天:30 天结果要用到
        frm = int(datetime.combine(HISTORY_FROM, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        to = int(datetime.combine(to_d, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        best = (r.get("med_err"), r.get("n_overlap"))
        while left and calls < MAX_CALLS_PER_RUN:
            cid = left.pop(0)
            raw = await get_cg_market_chart_range(cid, frm, to, interval="daily")
            calls += 1
            tried.append(cid)
            if not raw.get("available"):
                notes.append(f"{r['symbol']}:{cid} {str(raw.get('error') or raw.get('reason'))[:60]}")
                continue
            pts = parse_market_chart(raw.get("prices"), raw.get("market_caps"))
            err, n = price_check(pts, implied, int(r.get("mult") or 1))
            if accept(err, n):
                rows_out = [{"coin_id": cid, "source": SOURCE, **p} for p in pts]
                for i in range(0, len(rows_out), 2000):
                    w = await supabase_upsert_table(TABLE, rows_out[i:i + 2000], on_conflict="coin_id,d")
                    if not w.ok:
                        return {"ok": False, "refused": False, "calls": calls, "reason": f"{TABLE} 写入失败:{w.why}"}
                await supabase_upsert_table(MAP_TABLE, [{
                    "symbol": r["symbol"], "coin_id": cid, "verdict": "resolved", "med_err": round(err, 5), "n_overlap": n,
                    "rows_written": len(rows_out), "tried": tried, "checked_at": datetime.now(timezone.utc).isoformat()}],
                    on_conflict="symbol")
                done.append(f"{r['symbol']}→{cid} ({err:.3f}, {n}d)")
                left = []
                break
            if err is not None and (best[0] is None or err < best[0]):
                best = (round(err, 5), n)
            await asyncio.sleep(1.0)
        else:
            upd = {"symbol": r["symbol"], "tried": tried, "med_err": best[0], "n_overlap": best[1],
                   "checked_at": datetime.now(timezone.utc).isoformat()}
            if not left:
                upd.update(verdict="unresolved", note=f"no candidate within {MAX_ERR:.0%} over ≥ {MIN_OVERLAP} days")
            await supabase_upsert_table(MAP_TABLE, [upd], on_conflict="symbol")
    pending = await _read_all(MAP_TABLE, {"select": "symbol", "verdict": "eq.pending"})
    return {"ok": True, "refused": False, "calls": calls, "resolved_now": done, "pending": len(pending),
            "notes": notes[:5], "reason": f"{calls} 次 CoinGecko 请求;本轮认出 {len(done)} 个;还剩 {len(pending)} 个待补"}
