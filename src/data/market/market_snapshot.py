"""行情快照:取回来的全宇宙行情落一份(S-908,2026-11-23)。

## 为什么

Jazz 11-23:「读取后是否落表」「研究时候是否直接走了 api 而不是走我们数据库」。量下来:`data_layer` 里打 CoinGecko 的
25 个函数没有一个自己写库。采集循环落了表,但**全宇宙行情的即时值**(价、市值、全交易所 24h 量、流通 / 总量 / 上限)
和**全市场市值 / BTC 占比**只进内存与 Redis:盘中引擎每 5 分钟取一次、页面每次过期取一次,取完就没了。
后果有三件,都已经发生过:CoinGecko 一停,「总量」「上限」「BTC 占比」没有任何库内来源(S-900);研究要这些数只能
再打一次 API;CMC 兜底在请求路径上每次页面请求打 2 笔,自设的日预算几小时就打光。

## 是什么

`market_snapshot`(只追加):每 30 分钟一批,一个名字一行,另加全市场一行(`symbol = '_GLOBAL'`)。
- 现在的来源:CoinMarketCap `quotes/latest`(25 个名字一笔)+ `global-metrics`(一笔)。
- CoinGecko 恢复后:盘中引擎每次成功取 `/coins/markets` 时顺手落一份(`source = 'coingecko_markets'`,同样 30 分钟一份)。
- **读的人**:宏观脉搏 / `/global` 的 CMC 兜底先读这张表(≤ `FRESH_S` 秒算新),不新才打活的;研究直接查表。

## CMC 按代码查币会查错

`quotes/latest?symbol=SKY` 回的是「代码叫 SKY 的那个排名最高的币」,不保证是我们的 SKY。所以每个名字落表前过
`identity_of`:名字对得上,且与库里的参考价差在 0.5–2 倍内;或名字对不上、但与币安最近收盘差 ≤ 15%。
两条都不满足 ⇒ **不落**,在循环的记录里点名(宁缺,不把另一个币的价写进我们的名字下)。

## 收盘批次(S-909 / T-432)

正式 CIS 只认收盘口径。循环在快到 UTC 00:00 时把下一次醒来对齐到零点后 15 秒,那一轮取的一批带 `close_of` = 前一天;
只在 00:00–00:30 窗内算数(库里有约束),一天一批(唯一索引)。`close_batches()` 给 `cis/cg_less_fallback` 的第二层用。

## 三样(规则 5b)

调度:`_market_snapshot_loop`(每 10 分钟醒一次,`run_once` 自己按 30 分钟节流 —— 部署重启不会多取一轮)。
判活:`select source, max(ts), count(*) from market_snapshot where ts > now() - interval '2 hours' group by 1`。
第一行:CMC 的 key 11-23 起可用 ⇒ 部署当天就有;CoinGecko 那一半要等 12-01 订阅恢复。
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

TABLE = "market_snapshot"
LOOP_NAME = "_market_snapshot_loop"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("ts", "d", "source", "symbol", "vendor_id", "name", "price", "market_cap", "volume_24h",
                          "circulating_supply", "total_supply", "max_supply", "pct_24h", "pct_7d", "btc_dominance",
                          "source_ts", "identity", "close_of")}
SOURCE_CMC = "coinmarketcap"
SOURCE_CG = "coingecko_markets"
GLOBAL = "_GLOBAL"
#: 一份快照隔多久。CMC 一轮 2 笔 ⇒ 一天 96 笔(`cmc_provider.DEFAULT_DAILY_BUDGET` 留了余量)。
INTERVAL_S = 1800
#: 读的人把多旧的快照当作「新」。两轮间隔 + 一轮失败的余量。
FRESH_S = 5400
#: 收盘批次(S-909 / T-432):UTC 00:00 之后这么多秒内取的那一批才算「前一天的收盘」。过窗取到的不是收盘 ⇒ 那天没有收盘批次。
CLOSE_WINDOW_S = 1800
#: 循环平时每隔这么久醒一次;快到 UTC 00:00 时改成对齐到零点后 `CLOSE_ALIGN_S` 秒(收盘批次离零点越近越好)。
WAKE_S = 600
CLOSE_ALIGN_S = 15
#: 身份核对的两个口子(见模块说明)。
REF_LOOSE = (0.5, 2.0)
REF_TIGHT = 0.15
_WORD = re.compile(r"[a-z0-9]+")
_latest_cache: dict[str, Any] = {"at": 0.0, "val": None}
_cg_last_persist = 0.0


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _pos(v: Any) -> Optional[float]:
    """正数才算有;0 / 负 / 缺 ⇒ None(价、市值、供给量没有「等于 0」这回事 —— 那是缺)。"""
    x = _f(v)
    return x if x is not None and x > 0 else None


def _iso(v: Any) -> Optional[str]:
    """那一家自己的更新时间 → ISO(UTC);认 ISO 字符串与 UNIX 秒。认不出 ⇒ None。"""
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat()
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def close_day(now: datetime) -> Optional[str]:
    """纯函数。`now` 落在收盘窗(UTC 00:00 起 `CLOSE_WINDOW_S` 秒)里 ⇒ 它是哪一天的收盘(前一天,ISO);否则 None。"""
    n = now.astimezone(timezone.utc)
    if n.hour * 3600 + n.minute * 60 + n.second >= CLOSE_WINDOW_S:
        return None
    return (n.date() - timedelta(days=1)).isoformat()


def next_wake_s(now: Optional[datetime] = None) -> float:
    """纯函数。循环下一次该睡多久:平时 `WAKE_S`;离 UTC 零点不到 `WAKE_S` 时,睡到零点后 `CLOSE_ALIGN_S` 秒。"""
    n = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    to_midnight = 86400 - (n.hour * 3600 + n.minute * 60 + n.second + n.microsecond / 1e6)
    return float(min(WAKE_S, to_midnight + CLOSE_ALIGN_S))


def identity_of(our_name: str, vendor_name: Any, price: Any, ref_px: Any, ref_is_venue: bool) -> Optional[str]:
    """纯函数。CMC 按代码回来的这个币是不是我们的那个:'name' / 'price' / None(不是,或没法确认)。

    名字:我们名字的第一个词是对方名字里的**一个完整的词**(「sky」对「Sky」算,对「Skycoin」不算)。
    参考价:`ref_is_venue` = 币安最近收盘(隔夜最多差一天的行情 ⇒ 15% 内才算对上);否则是更旧的库内日点,只当粗筛。
    """
    p, ref = _pos(price), _pos(ref_px)
    ours = _WORD.findall(str(our_name or "").lower())
    theirs = _WORD.findall(str(vendor_name or "").lower())
    named = bool(ours) and ours[0] in theirs
    ratio = (p / ref) if (p is not None and ref is not None) else None
    if named and (ratio is None or REF_LOOSE[0] <= ratio <= REF_LOOSE[1]):
        return "name"
    if ratio is not None and ref_is_venue and abs(ratio - 1.0) <= REF_TIGHT:
        return "price"
    return None


def cmc_rows(quotes: Mapping[str, Mapping[str, Any]], glob: Mapping[str, Any], now: datetime,
             names: Mapping[str, str], refs: Mapping[str, tuple[float, bool]],
             close_of: Optional[str] = None) -> tuple[list[dict], list[str]]:
    """纯函数。CMC 的两个回包 → (要落的行, 被拒的名字及原因)。没有的字段是 None,不是 0。
    `close_of`:这一批是哪一天的收盘(调用方只在收盘窗里给);每一行都带同一个值。"""
    ts = now.astimezone(timezone.utc).isoformat()
    rows: list[dict] = []
    rejected: list[str] = []

    def base(sym: str) -> dict:
        return {"ts": ts, "d": ts[:10], "source": SOURCE_CMC, "symbol": sym, "vendor_id": None, "name": None,
                "price": None, "market_cap": None, "volume_24h": None, "circulating_supply": None,
                "total_supply": None, "max_supply": None, "pct_24h": None, "pct_7d": None, "btc_dominance": None,
                "source_ts": None, "identity": None, "close_of": close_of}

    for sym in sorted(names):
        q = (quotes or {}).get(sym)
        if not isinstance(q, Mapping) or _pos(q.get("price")) is None:
            rejected.append(f"{sym}:没有报价")
            continue
        ref_px, ref_is_venue = refs.get(sym, (None, False))
        ident = identity_of(names[sym], q.get("name"), q.get("price"), ref_px, ref_is_venue)
        if ident is None:
            rejected.append(f"{sym}:对方给的是「{str(q.get('name'))[:24]}」@{_pos(q.get('price')):g},"
                            f"参考价 {ref_px if ref_px is not None else '无'} —— 身份对不上")
            continue
        rows.append({**base(sym), "vendor_id": None if q.get("id") is None else str(q.get("id")),
                     "name": None if q.get("name") is None else str(q.get("name"))[:80],
                     "price": _pos(q.get("price")), "market_cap": _pos(q.get("market_cap")),
                     "volume_24h": _pos(q.get("volume_24h")), "circulating_supply": _pos(q.get("circulating_supply")),
                     "total_supply": _pos(q.get("total_supply")), "max_supply": _pos(q.get("max_supply")),
                     "pct_24h": _f(q.get("percent_change_24h")), "pct_7d": _f(q.get("percent_change_7d")),
                     "source_ts": _iso(q.get("last_updated")), "identity": ident})
    if glob and _pos(glob.get("total_market_cap_usd")) is not None:
        rows.append({**base(GLOBAL), "name": "all crypto", "market_cap": _pos(glob.get("total_market_cap_usd")),
                     "volume_24h": _pos(glob.get("total_volume_24h_usd")),
                     "pct_24h": _f(glob.get("total_market_cap_change_24h_pct")),
                     "btc_dominance": _pos(glob.get("btc_dominance_pct")), "identity": "global"})
    else:
        rejected.append(f"{GLOBAL}:没有全市场数据")
    return rows, rejected


def cg_rows(markets: Mapping[str, Mapping[str, Any]], now: datetime, cg2sym: Mapping[str, str]) -> list[dict]:
    """纯函数。CoinGecko `/coins/markets` 的行(按 coin id)→ 要落的行。按 id 取的,不需要身份核对。"""
    ts = now.astimezone(timezone.utc).isoformat()
    out = []
    for cg_id, m in (markets or {}).items():
        sym = cg2sym.get(cg_id)
        if not sym or not isinstance(m, Mapping):
            continue
        price = _pos(m.get("price") if m.get("price") is not None else m.get("current_price"))
        if price is None:
            continue
        out.append({"ts": ts, "d": ts[:10], "source": SOURCE_CG, "symbol": sym, "vendor_id": cg_id,
                    "name": None if m.get("name") is None else str(m.get("name"))[:80], "price": price,
                    "market_cap": _pos(m.get("market_cap")),
                    "volume_24h": _pos(m.get("volume_24h") if m.get("volume_24h") is not None else m.get("total_volume")),
                    "circulating_supply": _pos(m.get("circulating_supply")), "total_supply": _pos(m.get("total_supply")),
                    "max_supply": _pos(m.get("max_supply")),
                    "pct_24h": _f(m.get("change_24h") if m.get("change_24h") is not None
                                  else m.get("price_change_percentage_24h")),
                    "pct_7d": _f(m.get("change_7d")), "btc_dominance": None,
                    "source_ts": _iso(m.get("last_updated")), "identity": "id", "close_of": None})
    return out


def _parse_ts(v: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


async def ref_prices(symbols: list[str], sym2cg: Mapping[str, str], today: Optional[datetime] = None
                     ) -> dict[str, tuple[float, bool]]:
    """身份核对用的参考价:币安最近 4 天里最新的收盘(venue = True);没有的名字用 CoinGecko 最后一个日点(40 天内)。"""
    from src.data.style.header import _read_all
    now = today or datetime.now(timezone.utc)
    out: dict[str, tuple[float, bool]] = {}
    rows = await _read_all("ohlcv_daily", {"select": "symbol,trade_date,close", "source": "eq.binance_hist",
                                           "symbol": f"in.({','.join(symbols)})",
                                           "trade_date": f"gte.{(now - timedelta(days=4)).date().isoformat()}",
                                           "order": "trade_date.asc"})
    for r in rows or []:
        c = _pos(r.get("close"))
        if c is not None:
            out[str(r["symbol"]).upper()] = (c, True)
    rest = [s for s in symbols if s not in out and sym2cg.get(s)]
    if rest:
        cg2sym = {sym2cg[s]: s for s in rest}
        rows = await _read_all("asset_mcap_daily", {"select": "coin_id,d,price",
                                                    "coin_id": f"in.({','.join(cg2sym)})",
                                                    "d": f"gte.{(now - timedelta(days=40)).date().isoformat()}",
                                                    "order": "d.asc"})
        for r in rows or []:
            c = _pos(r.get("price"))
            if c is not None and r.get("coin_id") in cg2sym:
                out[cg2sym[r["coin_id"]]] = (c, False)
    return out


async def run_once(now: Optional[datetime] = None, force: bool = False) -> dict[str, Any]:
    """一轮:上一份还新就不取;否则 CMC 两笔 → 身份核对 → 落表。CMC 不可用 = refused(带原因),不报 ok。"""
    from src.api.store import supabase_insert_table
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    from src.data.market import cmc_provider as cmc
    from src.data.vector.market_state_writer import _sb_get
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    last = await _sb_get(TABLE, {"select": "ts", "source": f"eq.{SOURCE_CMC}", "order": "ts.desc", "limit": "1"})
    if not last.ok:
        return {"ok": False, "written": 0, "why": f"{TABLE} 读不到:{last.reason}"}      # 读不到 ≠ 没有上一份
    prev = _parse_ts(last.rows[0]["ts"]) if last.rows else None
    # 收盘批次(S-909):在收盘窗里、前一天的收盘还没取过 ⇒ 这一轮就是它,不管上一份新不新。
    close_of = close_day(now)
    if close_of is not None:
        got = await _sb_get(TABLE, {"select": "ts", "source": f"eq.{SOURCE_CMC}", "close_of": f"eq.{close_of}", "limit": "1"})
        if not got.ok:
            return {"ok": False, "written": 0, "why": f"{TABLE} 读不到(查收盘批次):{got.reason}"}
        if got.rows:
            close_of = None                                 # 已经有了:这一轮照平常的节奏走
    if close_of is None and prev is not None and not force and (now - prev).total_seconds() < INTERVAL_S - 60:
        return {"ok": True, "status": "already_done", "written": 0, "last_ts": prev.isoformat(), "why": "上一份还新"}
    allowed, why = await cmc.admit()
    if not allowed:
        return {"ok": False, "refused": True, "written": 0, "why": f"CMC 不可用:{why}"}
    names = {s: str(c.get("name") or s) for s, c in CRYPTO_ASSETS.items()}
    sym2cg = {s: c.get("coingecko") for s, c in CRYPTO_ASSETS.items() if c.get("coingecko")}
    cmc.LAST.clear()
    quotes = await cmc.cmc_quotes(sorted(names))
    glob = await cmc.cmc_global_metrics()
    if not quotes and not glob:
        return {"ok": False, "refused": True, "written": 0,
                "why": f"CMC 两笔都没有数据:{cmc.LAST.get('why') or '回包是空的'}"}
    try:
        refs = await ref_prices(sorted(names), sym2cg, now)
    except Exception as e:                                  # noqa: BLE001 —— 参考价读不到 ⇒ 只能靠名字,照实记
        refs = {}
        ref_note = f"参考价读不到({type(e).__name__}),只按名字核对"
    else:
        ref_note = None
    rows, rejected = cmc_rows(quotes, glob, now, names, refs, close_of=close_of)
    if not rows:
        return {"ok": False, "refused": True, "written": 0, "why": "没有一行过得了核对:" + ";".join(rejected)[:300]}
    res = await supabase_insert_table(TABLE, rows)
    if not res.ok:
        return {"ok": False, "written": 0, "why": f"写入失败:{res.why}"}
    _latest_cache.update({"at": 0.0, "val": None})
    g = next((r for r in rows if r["symbol"] == GLOBAL), None)
    out = {"ok": True, "written": len(rows), "ts": rows[0]["ts"], "source": SOURCE_CMC,
           "btc_dominance": g.get("btc_dominance") if g else None, "rejected": rejected,
           "by_identity": {k: sum(1 for r in rows if r["identity"] == k) for k in ("name", "price", "global")}}
    if close_of:
        out["close_of"] = close_of                          # 这一批是这一天的收盘
    if ref_note:
        out["note"] = ref_note
    if rejected:                                            # 有名字没落:这一轮照样算成(落了的是对的),没落的点名进 loop_attempt
        out["why"] = f"落了 {len(rows)} 行;没落的:" + ";".join(rejected)[:320]
    return out


async def latest(source: str = SOURCE_CMC, max_age_s: float = FRESH_S, now: Optional[datetime] = None
                 ) -> Optional[dict[str, Any]]:
    """最近一份快照(够新才给):`{"ts", "age_s", "source", "global": 行或 None, "rows": {代码: 行}}`。
    没有 / 太旧 / 读不到 ⇒ None —— 调用方自己回落,不拿旧数冒充。进程内缓存 60 秒。"""
    from src.data.style.header import _read_all
    from src.data.vector.market_state_writer import _sb_get
    t = time.time()
    c = _latest_cache
    if c["val"] is not None and t - c["at"] < 60 and c["val"].get("source") == source:
        val = c["val"]
    else:
        try:
            top = await _sb_get(TABLE, {"select": "ts", "source": f"eq.{source}", "order": "ts.desc", "limit": "1"})
            if not top.ok or not top.rows:
                return None
            ts = top.rows[0]["ts"]
            rows = await _read_all(TABLE, {"select": "*", "source": f"eq.{source}", "ts": f"eq.{ts}"})
        except Exception:                                   # noqa: BLE001
            return None
        val = {"ts": ts, "source": source, "global": next((r for r in rows if r.get("symbol") == GLOBAL), None),
               "rows": {r["symbol"]: r for r in rows if r.get("symbol") != GLOBAL}}
        c.update({"at": t, "val": val})
    when = _parse_ts(val["ts"])
    age = ((now or datetime.now(timezone.utc)) - when).total_seconds() if when else None
    if age is None or age > max_age_s:
        return None
    return {**val, "age_s": int(age)}


async def close_batches(since: str, until: Optional[str] = None, source: str = SOURCE_CMC) -> dict[str, dict[str, Any]]:
    """收盘批次(S-909):`{"YYYY-MM-DD": {"ts", "global": 行或 None, "rows": {代码: 行}}}`,键 = 那一批是哪一天的收盘。
    **读不到抛异常**(读不到 ≠ 那天没有收盘批次);没有批次的日子就是不在返回里。"""
    from src.data.style.header import _read_all
    params = {"select": "*", "source": f"eq.{source}", "close_of": f"gte.{since}", "order": "close_of.asc,symbol.asc"}
    rows = await _read_all(TABLE, params)
    out: dict[str, dict[str, Any]] = {}
    for r in rows or []:
        day = str(r.get("close_of") or "")[:10]
        if not day or (until and day > until):              # 上界在这边裁(一天 26 行,不值得为它拼第二个过滤条件)
            continue
        b = out.setdefault(day, {"ts": r.get("ts"), "global": None, "rows": {}})
        if r.get("symbol") == GLOBAL:
            b["global"] = r
        else:
            b["rows"][r["symbol"]] = r
    return out


def cmc_shaped(snap: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """纯函数。一份快照 → `cmc_provider` 两个函数的形状(调用方不用知道数是从表里来的还是活的):
    `{"global": cmc_global_metrics() 的形状或 {}, "quotes": {代码: cmc_quotes() 的形状}, "as_of": 快照时刻}`。
    表里没有的字段(活跃币种数、市场数)是 None。"""
    if not snap:
        return {"global": {}, "quotes": {}, "as_of": None}
    g = snap.get("global") or {}
    glob = {}
    if g and _pos(g.get("market_cap")) is not None:
        glob = {"total_market_cap_usd": g.get("market_cap"), "total_volume_24h_usd": g.get("volume_24h"),
                "total_market_cap_change_24h_pct": g.get("pct_24h"), "btc_dominance_pct": g.get("btc_dominance"),
                "btc_dominance_change_24h_pp": None, "active_cryptocurrencies": None, "markets": None,
                "source": snap.get("source") or SOURCE_CMC}
    quotes = {}
    for sym, r in (snap.get("rows") or {}).items():
        if _pos(r.get("price")) is None:
            continue
        quotes[sym] = {"id": r.get("vendor_id"), "name": r.get("name"), "symbol": sym, "price": r.get("price"),
                       "market_cap": r.get("market_cap"), "volume_24h": r.get("volume_24h"),
                       "percent_change_24h": r.get("pct_24h"), "percent_change_7d": r.get("pct_7d"),
                       "circulating_supply": r.get("circulating_supply"), "total_supply": r.get("total_supply"),
                       "max_supply": r.get("max_supply"), "last_updated": r.get("source_ts"),
                       "source": snap.get("source") or SOURCE_CMC}
    return {"global": glob, "quotes": quotes, "as_of": snap.get("ts")}


async def cmc_latest_shaped(max_age_s: float = FRESH_S) -> dict[str, Any]:
    """`latest()` + `cmc_shaped()`。**绝不抛**:读不到就是三样都空,调用方回落到活的。"""
    try:
        return cmc_shaped(await latest(SOURCE_CMC, max_age_s))
    except Exception:                                       # noqa: BLE001
        return {"global": {}, "quotes": {}, "as_of": None}


async def persist_cg_markets(markets: Mapping[str, Mapping[str, Any]], now: Optional[datetime] = None) -> dict[str, Any]:
    """盘中引擎每次成功取到 CoinGecko `/coins/markets` 之后调:30 分钟落一份。**绝不抛**(落表失败不许连累取数)。"""
    global _cg_last_persist
    t = time.time()
    if not markets or t - _cg_last_persist < INTERVAL_S - 60:
        return {"ok": True, "written": 0, "why": "没有行情可落" if not markets else "上一份还新"}
    try:
        from src.api.store import supabase_insert_table
        from src.data.cis.cis_provider import CRYPTO_ASSETS
        cg2sym = {c["coingecko"]: s for s, c in CRYPTO_ASSETS.items() if c.get("coingecko")}
        rows = cg_rows(markets, (now or datetime.now(timezone.utc)), cg2sym)
        if not rows:
            return {"ok": True, "written": 0, "why": "没有可落的行"}
        _cg_last_persist = t                               # 先占位:写失败也别每 5 分钟重试一次
        res = await supabase_insert_table(TABLE, rows)
        return {"ok": bool(res.ok), "written": len(rows) if res.ok else 0, "why": None if res.ok else res.why}
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "written": 0, "why": f"{type(e).__name__}: {str(e)[:120]}"}
