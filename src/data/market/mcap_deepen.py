"""S-700 数据补齐:`asset_mcap_daily` 往前补到 2018-12,并把 ① 历史上真正在前 24 里的死币接上(Seth 的 ingestion 道,一次性)。

## 为什么

`asset_mcap_daily` 大多数名字从 2019-06-01 起(style/header HISTORY_START 当时是 2020,后来补到 2019-06);2018-12 → 2019-05 只有 4 个名字。
且 EOS / LUNA / OMG / XEM… 这些 2019–2022 在前 24 里、后来归零或下架的名字,`cg_coin_map` 里没有或映错(OM → 马赛球迷币)。
按时点的 ① 回放(`core_pit`)少了它们就还是幸存者名单。

## 规则

- 两类工作:**延深**(已有映射的名字,从 2018-12-01 补到它现有的第一天)与 **新名**(下面 `DEAD_NAMES` 的映射,整段 2018-12-01 → 今天)。
- 同源同约定:CoinGecko `market_chart/range`(daily),`parse_market_chart` 同一函数,`source = coingecko_pro_market_chart`,主键 (symbol, d, source)。
- **每个新名的映射用 binance_hist 收盘逐日核价**:重叠日 ≥ 30 且 |CG/Binance − 1| 的中位数 ≤ 3% ⇒ 写;否则拒绝并记原因(映射错 = T-043 / S-460 的形状)。
  已有映射的延深段也核(它们 2019 上半年的 Binance 收盘在 binance_hist 里)。
- 每币一次请求,间隔 2.5 秒(Jazz 10-26「分开来」);每轮最多 12 分钟;做过的名字按版本记在 loop_attempt(detail.done),重启接着做。
- **不删不改任何已有行**(upsert 只会补空位:同一 (symbol,d,source) 已有的行,值一致就是幂等;不一致会覆盖 —— 所以延深只取现有第一天之前的区间)。

## 判活

    select symbol, min(d) from asset_mcap_daily where symbol in ('BTC','ETH','EOS','LUNC','OMG') group by 1;   -- 应到 2018-12
    select detail->'done', detail->'remaining' from loop_attempt where loop_name = '_mcap_deepen_loop' order by at desc limit 1;
"""
from __future__ import annotations

import asyncio
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

TABLE = "asset_mcap_daily"
WRITES_TABLES = (TABLE,)
LOOP_NAME = "_mcap_deepen_loop"
VERSION = 1
START = "2018-12-01"
EXTEND_UNTIL = "2019-06-01"      # 延深:现有名字第一天普遍是 2019-06-01;只补这之前
PACE_S = 2.5
TIME_BUDGET_S = 12 * 60
MAX_MEDIAN_GAP = 0.03
MIN_OVERLAP = 30
CHECKPOINT_EVERY = 8

#: 没有(或映错)CoinGecko 映射、而 2019–2025 某个月在 Binance 现货成交额前 20 的名字。记账名 = binance_hist 的 symbol。
#: `cg`:CoinGecko id;`note`:为什么要它。映射对不对由核价决定,不由这张表决定。
DEAD_NAMES: dict[str, dict[str, str]] = {
    "EOS":   {"cg": "eos", "note": "2018–2020 前 10;2025 改名 Vaulta(A)"},
    "OMG":   {"cg": "omisego", "note": "2019–2021 前 30;后下架"},
    "LUNC":  {"cg": "terra-luna", "note": "Terra 旧币,2021–22 前 10,2022-05 归零;Binance 符号 LUNC(当时叫 LUNA)"},
    "LUNA":  {"cg": "terra-luna-2", "note": "Terra 2.0(2022-05 起)"},
    "XEC":   {"cg": "ecash", "note": "eCash(BCHA)2021 起"},
    "BTT":   {"cg": "bittorrent", "note": "BTT 新币(2022 起,1:1000 换币);旧 BTT 见 bittorrent-old"},
    "BTTOLD": {"cg": "bittorrent-old", "note": "旧 BTT 2019–2021;Binance 当时符号 BTT —— 核价要对 BTT 2022 之前的收盘"},
    "NANO":  {"cg": "nano", "note": "2018–2021 前 50;2021 改名 XNO"},
    "NULS":  {"cg": "nuls", "note": "2018–2019 Binance 成交前 20"},
    "DYDX":  {"cg": "dydx", "note": "旧 dYdX(以太坊,2021–2023);cg_coin_map 映的是 dydx-chain(2023-10 起)—— 只补 2023-10-30 之前"},
    "OM":    {"cg": "mantra-dao", "note": "MANTRA;cg_coin_map 映成了 olympique-de-marseille-fan-token(错)。2025-04 一夜 −90%"},
    "IP":    {"cg": "story-2", "note": "Story Protocol(2025-02 起)"},
    "ALPHA": {"cg": "alpha-finance", "note": "Alpha Finance / Alpha Venture DAO,2020-11 起"},
    "KNCOLD": {"cg": "kyber-network", "note": "旧 KNC(2017–2021-04);cg_coin_map 的 kyber-network-crystal 从 2021-04 起"},
    "PERP":  {"cg": "perpetual-protocol", "note": "2021 起"},
    "LOOM":  {"cg": "loom-network-new", "note": "Loom Network(2018 起;2023-09 Binance 成交前 10)"},
    "HIGH":  {"cg": "highstreet", "note": "2021-10 起"},
    # S-700 修订:不在 Binance 的大市值名字也进宇宙(按市值前 24 就是按市值前 24)
    "BSV":   {"cg": "bitcoin-cash-sv", "note": "2018-11 分叉,2019–2021 前 10;不在 binance_hist"},
    "LEO":   {"cg": "leo-token", "note": "Bitfinex,2019 起前 30;不在 Binance"},
    "HT":    {"cg": "huobi-token", "note": "2018–2022 前 30;不在 Binance"},
    "WLD":   {"cg": "worldcoin-wld", "note": "2023-07 起"},
    "HNT":   {"cg": "helium", "note": "2020–2022 前 50"},
}
#: 不在 binance_hist 的名字:用 CoinGecko `coins/markets` 回声的 symbol 核(改名别名在 SYMBOL_ALIAS)
SYMBOL_ALIAS = {"LUNC": {"lunc", "luna"}, "LUNA": {"luna"}, "BTTOLD": {"bttold", "btt"}, "NANO": {"xno", "nano"},
                "KNCOLD": {"knc"}, "DYDX": {"dydx", "ethdydx"}, "EOS": {"eos", "a"}, "OM": {"om"}, "IP": {"ip"}}
#: 核价时 binance_hist 里的符号(记账名与 Binance 符号不同的几个)
BINANCE_SYMBOL = {"BTTOLD": "BTT", "KNCOLD": "KNC", "LUNC": "LUNC"}
#: 核价与写入都截到这一天之前(旧币让位给新币的那一天;None = 不截)
WRITE_BEFORE = {"BTTOLD": "2022-01-26", "KNCOLD": "2021-04-21", "DYDX": "2023-10-30"}


def _ts(d: str) -> int:
    return int(datetime.combine(date.fromisoformat(d), datetime.min.time(), tzinfo=timezone.utc).timestamp())


def price_gap(cg_rows: list[dict], binance_close: dict[str, float]) -> dict[str, Any]:
    """纯函数。CG 日价对 Binance 同日收盘:重叠日数、|比值 − 1| 的中位数。"""
    gaps = []
    for r in cg_rows:
        b = binance_close.get(r["d"])
        if b and r.get("price") and b > 0:
            gaps.append(abs(float(r["price"]) / b - 1.0))
    return {"overlap": len(gaps), "median_gap": round(statistics.median(gaps), 5) if gaps else None}


def verdict_for(gap: dict[str, Any]) -> tuple[bool, str]:
    if gap["overlap"] < MIN_OVERLAP:
        return False, f"重叠日 {gap['overlap']} < {MIN_OVERLAP},核不了价,不写"
    if gap["median_gap"] is None or gap["median_gap"] > MAX_MEDIAN_GAP:
        return False, f"CG 对 Binance 收盘中位差 {gap['median_gap']} > {MAX_MEDIAN_GAP}:映射可疑,不写"
    return True, f"重叠 {gap['overlap']} 日,中位差 {gap['median_gap']}"


def done_from(rows: list[dict], version: int = VERSION) -> dict[str, str]:
    done: dict[str, str] = {}
    for r in rows or []:
        det = r.get("detail") or {}
        if det.get("v") != version:
            continue
        for s, v in (det.get("done") or {}).items():
            done.setdefault(s, v)
    return done


async def _binance_close(symbol: str, d0: str, d1: str) -> dict[str, float]:
    from src.data.style.header import _read_all
    rows = await _read_all("ohlcv_daily", {"select": "trade_date,close", "symbol": f"eq.{symbol}", "source": "eq.binance_hist",
                                           "trade_date": f"gte.{d0}", "order": "trade_date.asc"})
    return {str(r["trade_date"])[:10]: float(r["close"]) for r in rows if r.get("close") and str(r["trade_date"])[:10] < d1}


async def _existing_names() -> list[dict]:
    """已有映射、第一天晚于 START 的名字:(symbol, coin_id, first_d)。读 cg_coin_map 以外的也算 —— 以 asset_mcap_daily 里的 coin_id 为准。"""
    from src.api.store import supabase_rpc_all
    from src.data.style.header import _read_all
    try:
        rows = await supabase_rpc_all("mcap_first_days", {}, {})
        if isinstance(rows, list) and rows:
            return [r for r in rows if str(r.get("first_d")) > START and str(r.get("first_d")) <= EXTEND_UNTIL]
    except Exception:                                                    # noqa: BLE001 —— 没有这个 RPC 就用慢路径
        pass
    out, seen = [], set()
    rows = await _read_all(TABLE, {"select": "symbol,coin_id,d", "d": f"lte.{EXTEND_UNTIL}", "order": "d.asc"})
    for r in rows:
        if r["symbol"] in seen:
            continue
        seen.add(r["symbol"])
        if str(r["d"]) > START:
            out.append({"symbol": r["symbol"], "coin_id": r["coin_id"], "first_d": str(r["d"])})
    return out


async def _fetch(coin_id: str, d0: str, d1: str) -> list[dict]:
    from src.data.market.data_layer import get_cg_market_chart_range
    from src.data.style.header import parse_market_chart
    raw = await get_cg_market_chart_range(coin_id, _ts(d0), _ts(d1), interval="daily")
    if not raw.get("available"):
        raise RuntimeError(str(raw.get("error") or raw.get("reason"))[:160])
    pts = parse_market_chart(raw.get("prices"), raw.get("market_caps"), raw.get("volumes"))
    return [p for p in pts if d0 <= p["d"] < d1]


async def _write(symbol: str, coin_id: str, pts: list[dict]) -> Optional[str]:
    from src.api.store import supabase_upsert_table
    from src.data.style.header import SOURCE
    rows = [{"symbol": symbol, "coin_id": coin_id, "source": SOURCE, **p} for p in pts]
    for i in range(0, len(rows), 2000):
        r = await supabase_upsert_table(TABLE, rows[i:i + 2000], on_conflict="symbol,d,source")
        if not r:
            return f"写入失败:{(getattr(r, 'why', '') or '')[:160]}"
    return None


def symbol_echo_ok(symbol: str, echo_symbol: Optional[str]) -> bool:
    """纯函数。CoinGecko 回声的 symbol 是不是这个记账名(含改名别名)。"""
    if not echo_symbol:
        return False
    e = str(echo_symbol).lower()
    return e == symbol.lower() or e in SYMBOL_ALIAS.get(symbol, set())


async def _echo_symbol(coin_id: str) -> Optional[str]:
    from src.data.market.data_layer import get_cg_markets_strict
    rows = await get_cg_markets_strict([coin_id])
    return (rows[0].get("symbol") if rows else None)


async def deepen_one(symbol: str, coin_id: str, d0: str, d1: str, binance_symbol: Optional[str] = None) -> dict[str, Any]:
    """一个名字:取 → 核(binance_hist 有收盘就核价;没有就核 CoinGecko 回声的 symbol)→ 写。返回 verdict ok / rejected / error / empty。"""
    pts = await _fetch(coin_id, d0, d1)
    if not pts:
        return {"verdict": "empty", "why": f"CoinGecko {coin_id} 在 {d0}→{d1} 没有日点"}
    bclose = await _binance_close(binance_symbol or symbol, d0, d1)
    gap = price_gap(pts, bclose)
    if not bclose:
        echo = await _echo_symbol(coin_id)
        ok = symbol_echo_ok(symbol, echo)
        why = f"binance_hist 没有这个名字;CoinGecko {coin_id} 回声 symbol={echo!r} {'对上' if ok else '对不上'} {symbol}"
        gap = {**gap, "echo_symbol": echo}
    else:
        ok, why = verdict_for(gap)
    if not ok:
        return {"verdict": "rejected", "why": why, **gap, "n_points": len(pts)}
    err = await _write(symbol, coin_id, pts)
    if err:
        return {"verdict": "error", "why": err, **gap}
    return {"verdict": "ok", "n_written": len(pts), "first_d": pts[0]["d"], "last_d": pts[-1]["d"], **gap}


async def _checkpoint(done: dict[str, str]) -> None:
    try:
        from src.api.rpc_diagnostics import _record_loop_attempt
        await _record_loop_attempt(LOOP_NAME, "ok", reason="checkpoint", detail={"v": VERSION, "done": dict(done), "checkpoint": True},
                                   writer="src.data.market.mcap_deepen._checkpoint")
    except Exception:                                                    # noqa: BLE001
        pass


async def run_once(time_budget: float = TIME_BUDGET_S) -> dict[str, Any]:
    from src.data.signals.hl_book_daily import _supabase_get
    t0 = time.monotonic()
    prev = await _supabase_get(f"loop_attempt?select=at,detail&loop_name=eq.{LOOP_NAME}&order=at.desc&limit=200")
    done = done_from(prev or [])
    today = datetime.now(timezone.utc).date().isoformat()
    jobs: list[tuple[str, str, str, str, Optional[str]]] = []          # (key, symbol, coin_id, d0, d1, binance_symbol)
    for sym, spec in DEAD_NAMES.items():
        d1 = WRITE_BEFORE.get(sym) or today
        jobs.append((f"new:{sym}", sym, spec["cg"], START, d1, BINANCE_SYMBOL.get(sym)))
    for r in await _existing_names():
        jobs.append((f"ext:{r['symbol']}", r["symbol"], r["coin_id"], START, str(r["first_d"]), None))
    todo = [j for j in jobs if j[0] not in done or done[j[0]] == "error"]
    this: dict[str, str] = {}
    notes: dict[str, Any] = {}
    since_ckpt: dict[str, str] = {}
    for key, sym, cg, d0, d1, bsym in todo:
        if time.monotonic() - t0 > time_budget:
            break
        if len(since_ckpt) >= CHECKPOINT_EVERY:
            await _checkpoint(since_ckpt)
            since_ckpt = {}
        try:
            r = await deepen_one(sym, cg, d0, d1, bsym)
        except Exception as e:                                           # noqa: BLE001 — 一个名字炸了,下一个照做
            r = {"verdict": "error", "why": f"{type(e).__name__}: {str(e)[:160]}"}
        this[key] = r["verdict"]
        since_ckpt[key] = r["verdict"]
        notes[key] = {k: v for k, v in r.items() if k in ("verdict", "why", "n_written", "first_d", "last_d", "overlap", "median_gap")}
        await asyncio.sleep(PACE_S)
    left = [j[0] for j in todo if j[0] not in this]
    return {"ok": not any(v == "error" for v in this.values()), "v": VERSION, "done": this, "notes": notes,
            "remaining": len(left), "already_done": len(done), "n_jobs": len(jobs), "elapsed_s": round(time.monotonic() - t0, 1)}
