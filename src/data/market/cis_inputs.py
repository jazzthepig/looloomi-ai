"""CIS 统一标准缺的维度 —— 补齐并日更(T-079 / S-531,docs/CIS_STANDARD.md §4)。

## 为什么

Jazz 10-09:「重建不是问题,问题是要数据和时序对上。有缺了维度的补上。」CIS 的公式要用的输入里,
有几样我们从来没存过历史(实盘每次现取现用、算完就丢),所以历史无法按同一个公式复原:

- 恐惧贪婪(S 支柱、状态判定)、VIX(传统资产 S、状态)、全市场市值(BTC 占比 → 状态)→ `macro_daily`
- DeFi 协议 TVL(F / O 支柱)→ `protocol_tvl_daily`(L2 用链 TVL,已在 chain_activity_daily)
- 全市场成交额(M / S 支柱)→ `asset_mcap_daily.volume`(CG market_chart 一直返回、一直被丢)
- 传统资产日线回填到 2022-10,并统一为复权口径(ohlcv 路由 `eodhd_adjusted_rows`)—— 每周全量重取一次,
  因为复权值会随新的分红回改。

资金费率在 `binance_hf_collector`(扩到 CIS 全部加密名字、回填到 2022-11)。

## 时点

d = UTC 日。CG 的 00:00 UTC 采样点 = 前一天收盘(`bar_semantics.covered_day`);恐惧贪婪按时间戳日期;
EODHD 按交易日;DeFiLlama 今天的占位点不收。HTTP 全在 data_layer。

## 判活判据(规则 5b ②)

    select series, max(d) from macro_daily group by 1;      -- fng / total_mcap = 昨天或今天;vix = 最近交易日
    select max(d) from protocol_tvl_daily;                   -- = 昨天
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

MACRO_TABLE = "macro_daily"
TVL_TABLE = "protocol_tvl_daily"
WRITES_TABLES = (MACRO_TABLE, TVL_TABLE, "asset_mcap_daily")
HISTORY_START = "2021-06-01"          # 2023 起的重建要 400 天回看(252 日动量、ATH 用全史另算)
VOLUME_BACKFILL_FROM = "2022-06-01"
TRADFI_BACKFILL_DAYS = 1500           # 约 2022-08 起
#: DeFi 类 CIS 名字 → DeFiLlama 协议 slug。L2 用链 TVL(chain_activity_daily),不在这里。
PROTOCOLS: dict[str, tuple[str, str]] = {"UNI": ("uniswap", "uniswap"), "AAVE": ("aave", "aave"),
                                         "LDO": ("lido", "lido-dao"), "PENDLE": ("pendle", "pendle")}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def fng_rows(data: list[dict], since: str = HISTORY_START) -> list[dict]:
    """纯函数。alternative.me 记录 → macro_daily 行;d = 时间戳的 UTC 日期(00:00 发布,早于当天收盘)。"""
    out = {}
    for x in data or []:
        try:
            d = datetime.fromtimestamp(int(x["timestamp"]), tz=timezone.utc).date().isoformat()
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        v = _f(x.get("value"))
        if v is None or d < since:
            continue
        out[d] = {"series": "fng", "d": d, "value": v, "source": "alternative.me"}
    return [out[k] for k in sorted(out)]


def eod_rows(series: str, rows: list[dict], since: str = HISTORY_START) -> list[dict]:
    """纯函数。EODHD 日线 → macro_daily 行;值 = adjusted_close(没有则 close);读不出的不收。"""
    out = []
    for x in rows or []:
        d = str(x.get("date") or "")[:10]
        v = _f(x.get("adjusted_close"))
        if v is None:
            v = _f(x.get("close"))
        if len(d) != 10 or v is None or v <= 0 or d < since:
            continue
        out.append({"series": series, "d": d, "value": v, "source": "eodhd"})
    return out


def global_rows(gm: dict, since: str = HISTORY_START) -> list[dict]:
    """纯函数。CG `/global/market_cap_chart` → total_mcap / total_volume 行。只收 00:00 UTC 的点,d = 前一天(收盘)。"""
    from src.data.market.bar_semantics import covered_day, is_day_boundary
    out = []
    for series, key in (("total_mcap", "market_cap"), ("total_volume", "volume")):
        for t, v in (gm or {}).get(key) or []:
            try:
                t = int(t)
            except (TypeError, ValueError):
                continue
            val = _f(v)
            if val is None or val <= 0 or not is_day_boundary(t):
                continue
            d = covered_day("coingecko_market_chart", t).isoformat()
            if d >= since:
                out.append({"series": series, "d": d, "value": val, "source": "coingecko_pro_global"})
    return out


def tvl_rows(sym: str, slug: str, gecko: str, points: list[list], today: date, since: str = HISTORY_START) -> list[dict]:
    """纯函数。DeFiLlama 协议 TVL → 行;同一天取最后一个点;今天(UTC)的占位点不收。"""
    from src.data.market.chain_activity import by_day
    days = by_day(points, today)
    return [{"protocol": slug, "d": d, "symbol": sym, "gecko_id": gecko, "tvl_usd": v, "source": "defillama_protocol"}
            for d, v in sorted(days.items()) if d >= since and v > 0]


async def _upsert(table: str, rows: list[dict], conflict: str) -> Optional[str]:
    from src.api.store import supabase_upsert_table
    for i in range(0, len(rows), 2000):
        res = await supabase_upsert_table(table, rows[i:i + 2000], on_conflict=conflict)
        if not res.ok:
            return f"{table}: {res.why}"
    return None


async def _macro(today: date) -> dict[str, Any]:
    from src.data.market.data_layer import get_cg_global_market_cap_chart, get_eodhd_eod_range, get_fng_history
    out: dict[str, Any] = {}
    for name, fetch in (("fng", lambda: get_fng_history()),
                        ("vix", lambda: get_eodhd_eod_range("VIX", "INDX", HISTORY_START)),
                        ("global", lambda: get_cg_global_market_cap_chart("max"))):
        try:
            raw = await fetch()
            rows = fng_rows(raw) if name == "fng" else eod_rows("vix", raw) if name == "vix" else global_rows(raw)
            err = await _upsert(MACRO_TABLE, rows, "series,d") if rows else f"{name}: 0 行"
            out[name] = {"rows": len(rows), "error": err, "last": rows[-1]["d"] if rows else None}
        except Exception as e:                              # noqa: BLE001
            out[name] = {"rows": 0, "error": f"{type(e).__name__}: {str(e)[:100]}"}
    return out


async def _protocols(today: date) -> dict[str, Any]:
    from src.data.market.data_layer import get_llama_protocol_tvl
    out: dict[str, Any] = {}
    for sym, (slug, gecko) in PROTOCOLS.items():
        try:
            rows = tvl_rows(sym, slug, gecko, await get_llama_protocol_tvl(slug), today)
            err = await _upsert(TVL_TABLE, rows, "protocol,d") if rows else "0 行"
            out[sym] = {"rows": len(rows), "error": err}
        except Exception as e:                              # noqa: BLE001
            out[sym] = {"rows": 0, "error": f"{type(e).__name__}: {str(e)[:100]}"}
    return out


async def _volumes(today: date) -> dict[str, Any]:
    """CIS 加密名字的 asset_mcap_daily:VOLUME_BACKFILL_FROM 起成交额为空的行 > 5 ⇒ 重取整段(同源同约定,价格 / 市值不变)。"""
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    from src.data.market.data_layer import get_cg_market_chart_range
    from src.data.style.header import SOURCE, _read_all, parse_market_chart
    out: dict[str, Any] = {}
    to_ts = int(datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    frm_ts = int(datetime.combine(date.fromisoformat(VOLUME_BACKFILL_FROM) - timedelta(days=2),
                                  datetime.min.time(), tzinfo=timezone.utc).timestamp())
    for sym, cfg in CRYPTO_ASSETS.items():
        cg = cfg.get("coingecko")
        if not cg:
            continue
        missing = await _read_all("asset_mcap_daily", {"select": "symbol,d", "coin_id": f"eq.{cg}", "source": f"eq.{SOURCE}",
                                                       "d": f"gte.{VOLUME_BACKFILL_FROM}", "volume": "is.null"})
        if len(missing) <= 5:
            continue
        stored_sym = missing[0]["symbol"]
        raw = await get_cg_market_chart_range(cg, frm_ts, to_ts, interval="daily")
        if not raw.get("available"):
            out[sym] = f"读不到:{str(raw.get('error') or raw.get('reason'))[:80]}"
            continue
        pts = parse_market_chart(raw.get("prices"), raw.get("market_caps"), raw.get("volumes"))
        rows = [{"symbol": stored_sym, "coin_id": cg, "source": SOURCE, **p} for p in pts if p["d"] >= VOLUME_BACKFILL_FROM]
        err = await _upsert("asset_mcap_daily", rows, "symbol,d,source")
        out[sym] = err or f"{len(rows)} 行"
    return out


async def _tradfi(today: date) -> dict[str, Any]:
    """传统资产 eodhd 日线:最早一行晚于 2022-11 或今天是周一 ⇒ 全量重取(复权口径,TRADFI_BACKFILL_DAYS 天)。"""
    from src.api.routers.ohlcv import collect_ohlcv
    from src.data.cis.cis_provider import ASSETS_CONFIG, CRYPTO_ASSETS
    from src.data.vector.market_state_writer import _sb_get
    syms = [s for s in ASSETS_CONFIG if s not in CRYPTO_ASSETS]
    rd = await _sb_get("ohlcv_daily", {"select": "trade_date", "source": "eq.eodhd", "symbol": "eq.SPY",
                                       "order": "trade_date.asc", "limit": "1"})
    first = (rd.rows or [{}])[0].get("trade_date") if rd.ok else None
    if first and str(first)[:10] <= "2022-11-01" and today.weekday() != 0:
        return {"skipped": f"已回填(SPY 最早 {str(first)[:10]}),周一全量重取"}
    res = await collect_ohlcv(symbols=syms, days=TRADFI_BACKFILL_DAYS)
    return {"rows": res.get("rows_written"), "first_before": str(first)[:10] if first else None}


async def run_once(today: Optional[date] = None) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    macro = await _macro(today)
    protocols = await _protocols(today)
    volumes = await _volumes(today)
    try:
        tradfi = await _tradfi(today)
    except Exception as e:                                  # noqa: BLE001
        tradfi = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    errors = [f"macro.{k}" for k, v in macro.items() if v.get("error")] + \
             [f"tvl.{k}" for k, v in protocols.items() if v.get("error")] + \
             [f"vol.{k}" for k, v in volumes.items() if not str(v).endswith("行")] + \
             (["tradfi"] if tradfi.get("error") else [])
    return {"ok": not errors, "refused": False, "errors": errors[:20], "macro": macro, "protocols": protocols,
            "volumes": volumes, "tradfi": tradfi,
            "reason": "全部写入" if not errors else f"{len(errors)} 项失败:{errors[:6]}"}
