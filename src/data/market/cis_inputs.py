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
WRITES_TABLES = (MACRO_TABLE, TVL_TABLE, "asset_mcap_daily", "equity_fundamentals_q", "github_commits_weekly")
HISTORY_START = "2021-06-01"          # 2023 起的重建要 400 天回看(252 日动量、ATH 用全史另算)
#: 10-16(Jazz:按时点模拟当时的情绪,S-590):恐惧贪婪 / 全市场市值 / VIX 存全历史(alternative.me 从 2018-02 起),
#: 不只是 CIS 重建用的那段 —— 情绪与拥挤的研究要 2018–2021 的牛熊。
MACRO_HISTORY_START = "2018-01-01"
VOLUME_BACKFILL_FROM = "2022-06-01"
TRADFI_BACKFILL_DAYS = 1500           # 约 2022-08 起
#: DeFi 类 CIS 名字 → DeFiLlama 协议 slug。L2 用链 TVL(chain_activity_daily),不在这里。
#: 美股单票(ETF 没有 PE / 营收):按披露日复原 PE 与营收同比(F 支柱,标准 §4)。
STOCKS: tuple[str, ...] = ("AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA")
FUND_TABLE = "equity_fundamentals_q"
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


#: `days=1` 是 5 分钟粒度,00:00 那一档的点落在 00:00–00:05 之间。
RECENT_TOLERANCE_MS = 10 * 60 * 1000


def global_rows(gm: dict, since: str = HISTORY_START, tolerance_ms: int = 0) -> list[dict]:
    """纯函数。CG `/global/market_cap_chart` → total_mcap / total_volume 行。只收 00:00 UTC 的点,d = 前一天(收盘)。
    `days=max` 是日粒度,但**最后一个 00:00 点是昨天的**(今天 00:00 被「现在」那个点取代)—— 所以 d 的收盘要到 d+2
    才出现,正式发布(d+1 的 UTC 06:00 前)永远缺 BTC 占比(S-536)。最近一天改从 `days=1`(5 分钟粒度)取 00:00 后
    第一个点,容差 `tolerance_ms`(只往后容);同一天两边都有时取 `days=max` 的整点。"""
    from src.data.market.bar_semantics import covered_day, is_day_boundary
    out = []
    for series, key in (("total_mcap", "market_cap"), ("total_volume", "volume")):
        seen: set[str] = set()
        for t, v in (gm or {}).get(key) or []:
            try:
                t = int(t)
            except (TypeError, ValueError):
                continue
            val = _f(v)
            if val is None or val <= 0 or not is_day_boundary(t, tolerance_ms):
                continue
            if covered_day("coingecko_market_chart", t).isoformat() in seen:
                continue                                    # 容差内同一天多个点:只取最早的
            seen.add(covered_day("coingecko_market_chart", t).isoformat())
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


def fundamentals_rows(symbol: str, j: dict, since: str = "2020-06-01") -> list[dict]:
    """纯函数。EODHD 基本面历史 → 每季一行:期末、可得日(EPS 公布日,没有则报送日)、EPS、营收。
    兼容两种返回形状:嵌套({Earnings: {History}})与按过滤路径平铺({"Earnings::History": …})。"""
    eh = j.get("Earnings::History") or ((j.get("Earnings") or {}).get("History")) or {}
    iq = (j.get("Financials::Income_Statement::quarterly")
          or (((j.get("Financials") or {}).get("Income_Statement") or {}).get("quarterly")) or {})
    out = []
    for per in sorted(set(eh) | set(iq)):
        e, i = eh.get(per) or {}, iq.get(per) or {}
        pe_ = str(e.get("date") or i.get("date") or per)[:10]
        avail = str(e.get("reportDate") or i.get("filing_date") or "")[:10]
        if len(pe_) != 10 or len(avail) != 10 or pe_ < since or avail < pe_:
            continue
        eps, rev = _f(e.get("epsActual")), _f(i.get("totalRevenue"))
        if eps is None and rev is None:
            continue
        out.append({"symbol": symbol, "period_end": pe_, "available_d": avail, "eps": eps, "revenue": rev,
                    "source": "eodhd_fundamentals"})
    return out


def github_rows(symbol: str, repo: str, weeks: list[int], today: date) -> list[dict]:
    """纯函数。GitHub participation 的 52 周(旧 → 新,最后一个 = 本周,未完)→ 每个**已完成**的周一行。
    GitHub 按周日开始分周(UTC);本周不收。历史只有 52 周 —— 更早的提交数复原不了(标准 §4)。"""
    this_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    n = len(weeks)
    out = []
    for i, c in enumerate(weeks[:-1]):
        ws = this_sunday - timedelta(days=7 * (n - 1 - i))
        out.append({"symbol": symbol, "repo": repo, "week_start": ws.isoformat(), "commits": int(c), "source": "github_participation"})
    return out


async def _github(today: date) -> dict[str, Any]:
    from src.data.cis.cis_provider import GITHUB_REPOS
    from src.data.market.data_layer import get_github_participation
    out: dict[str, Any] = {}
    for sym, repo in GITHUB_REPOS.items():
        try:
            rows = github_rows(sym, repo, await get_github_participation(repo), today)
            err = await _upsert("github_commits_weekly", rows, "symbol,week_start") if rows else "0 行"
            out[sym] = {"rows": len(rows), "error": err}
        except Exception as e:                              # noqa: BLE001
            out[sym] = {"rows": 0, "error": f"{type(e).__name__}: {str(e)[:80]}"}
    return out


async def _fundamentals() -> dict[str, Any]:
    from src.data.market.data_layer import get_eodhd_quarterly_history
    out: dict[str, Any] = {}
    for s in STOCKS:
        try:
            rows = fundamentals_rows(s, await get_eodhd_quarterly_history(s, "US"))
            err = await _upsert(FUND_TABLE, rows, "symbol,period_end") if rows else "0 行"
            out[s] = {"rows": len(rows), "error": err}
        except Exception as e:                              # noqa: BLE001
            msg = f"{type(e).__name__}: {str(e)[:100]}"
            if "HTTP 403" in msg:
                # 10-11 实测:我们的 EODHD 套餐不含基本面接口(实盘 T2 的 PE / 营收 / 市值同样拿不到)。
                # 这是付费源的决定(Jazz:付费 API 待定),不是故障 —— 标出来,不记成错误。
                out[s] = {"rows": 0, "error": None, "unavailable": "EODHD 套餐不含基本面(403)"}
            else:
                out[s] = {"rows": 0, "error": msg}
    return out


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
                        ("vix", lambda: get_eodhd_eod_range("VIX", "INDX", MACRO_HISTORY_START)),
                        ("global", lambda: get_cg_global_market_cap_chart("max")),
                        ("global_recent", lambda: get_cg_global_market_cap_chart("1"))):
        try:
            raw = await fetch()
            if name == "global_recent":
                have = {(r["series"], r["d"]) for r in out.get("_global_rows", [])}
                rows = [r for r in global_rows(raw, tolerance_ms=RECENT_TOLERANCE_MS) if (r["series"], r["d"]) not in have]
            else:
                rows = (fng_rows(raw, MACRO_HISTORY_START) if name == "fng" else eod_rows("vix", raw, MACRO_HISTORY_START)
                        if name == "vix" else global_rows(raw, MACRO_HISTORY_START))
            if name == "global":
                out["_global_rows"] = rows
            err = await _upsert(MACRO_TABLE, rows, "series,d") if rows else f"{name}: 0 行"
            out[name] = {"rows": len(rows), "error": err, "last": rows[-1]["d"] if rows else None}
        except Exception as e:                              # noqa: BLE001
            out[name] = {"rows": 0, "error": f"{type(e).__name__}: {str(e)[:100]}"}
    out.pop("_global_rows", None)
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


#: 10-16(S-590):全量加密成交额历史。风格头(style/header.py)从 2020 起落了 454 个名字的价格 / 市值,但成交额是后来才带上的 ——
#: 2026 年之前只有 19–29 个名字有成交额,「换手 / 刷量」类检验在前 50 上算不出来。CG market_chart 一直返回 total_volumes。
VOLUME_HISTORY_FROM = "2019-06-01"
VOLUME_HISTORY_MAX_PER_RUN = 120      # 一轮(每天)最多重取这么多个名字(CG 额度),约 4 天补齐;补齐之后每轮只剩一次小查询 / 名字


def needs_volume_history(null_rows: int, threshold: int = 30) -> bool:
    """纯函数。成交额为空的行超过门槛才重取 —— CG 在上市前几天偶尔不给成交额,几行空不值得整段重取。"""
    return null_rows > threshold


async def _volume_history_all(today: date) -> dict[str, Any]:
    from src.data.market.data_layer import get_cg_market_chart_range
    from src.data.style.header import SOURCE, latest_membership, parse_market_chart
    from src.data.vector.market_state_writer import _sb_get
    members = await latest_membership()
    to_ts = int(datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    frm_ts = int(datetime.combine(date.fromisoformat(VOLUME_HISTORY_FROM) - timedelta(days=2),
                                  datetime.min.time(), tzinfo=timezone.utc).timestamp())
    done, failed, checked = 0, {}, 0
    for m in members:
        if done >= VOLUME_HISTORY_MAX_PER_RUN:
            break
        sym, cg = m.get("symbol"), m.get("coin_id")
        if not sym or not cg:
            continue
        checked += 1
        rd = await _sb_get("asset_mcap_daily", {"select": "d", "symbol": f"eq.{sym}", "coin_id": f"eq.{cg}",
                                                "source": f"eq.{SOURCE}", "d": f"gte.{VOLUME_HISTORY_FROM}",
                                                "volume": "is.null", "order": "d.asc", "limit": "31"})
        if not rd.ok:
            failed[sym] = f"读不到:{rd.reason}"[:80]
            continue
        if not needs_volume_history(len(rd.rows or [])):
            continue
        raw = await get_cg_market_chart_range(cg, frm_ts, to_ts, interval="daily")
        if not raw.get("available"):
            failed[sym] = str(raw.get("error") or raw.get("reason"))[:80]
            continue
        pts = parse_market_chart(raw.get("prices"), raw.get("market_caps"), raw.get("volumes"))
        rows = [{"symbol": sym, "coin_id": cg, "source": SOURCE, **p} for p in pts if p["d"] >= VOLUME_HISTORY_FROM]
        err = await _upsert("asset_mcap_daily", rows, "symbol,d,source")
        if err:
            failed[sym] = err[:80]
        else:
            done += 1
    return {"checked": checked, "refetched": done, "failed": dict(list(failed.items())[:10]), "n_failed": len(failed)}


async def _migration_history(today: date) -> dict[str, Any]:
    """S-537:迁移前的旧币(MKR / MATIC)的 asset_mcap_daily 历史。没有就从 HISTORY_START 整段取;有了只补最近 10 天。
    统一标准把新币的历史在生效日前接到旧币上(src/data/cis/migrations.py),旧币没落库就接不上。"""
    from src.data.cis.migrations import MIGRATIONS
    from src.data.market.data_layer import get_cg_market_chart_range
    from src.data.style.header import SOURCE, parse_market_chart
    from src.data.vector.market_state_writer import _sb_get
    out: dict[str, Any] = {}
    to_ts = int(datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    for m in MIGRATIONS:
        rd = await _sb_get("asset_mcap_daily", {"select": "d", "coin_id": f"eq.{m['old_coin']}", "source": f"eq.{SOURCE}",
                                                "order": "d.desc", "limit": "1"})
        if not rd.ok:
            out[m["old"]] = f"读不到已有历史:{rd.reason}"
            continue
        last = (rd.rows or [{}])[0].get("d")
        frm = (date.fromisoformat(last) - timedelta(days=10)) if last else date.fromisoformat(HISTORY_START)
        raw = await get_cg_market_chart_range(m["old_coin"], int(datetime.combine(frm, datetime.min.time(),
                                                                                   tzinfo=timezone.utc).timestamp()),
                                              to_ts, interval="daily")
        if not raw.get("available"):
            out[m["old"]] = f"读不到:{str(raw.get('error') or raw.get('reason'))[:80]}"
            continue
        pts = parse_market_chart(raw.get("prices"), raw.get("market_caps"), raw.get("volumes"))
        rows = [{"symbol": m["old"], "coin_id": m["old_coin"], "source": SOURCE, **p} for p in pts]
        err = await _upsert("asset_mcap_daily", rows, "symbol,d,source") if rows else None
        out[m["old"]] = err or f"{len(rows)} 行"
    return out


async def refresh_close_inputs(now: Optional[datetime] = None) -> dict[str, Any]:
    """S-538:正式发布前把「收盘」那一档输入补齐 —— 全市场市值 / 恐惧贪婪 / VIX(`_macro`)与加密名字最近几天的收盘
    (CG market_chart,interval=daily)。不依赖每日采集循环跑在一天里的哪个钟点:发布器缺什么就自己补,每小时一次。
    写法与各自的每日采集相同(同源同约定),幂等。"""
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    from src.data.market.data_layer import get_cg_market_chart_range
    from src.data.style.header import SOURCE, parse_market_chart
    from src.data.vector.market_state_writer import _sb_get
    now = now or datetime.now(timezone.utc)
    out: dict[str, Any] = {"macro": await _macro(now.date())}
    frm_ts = int((now - timedelta(days=4)).timestamp())
    to_ts = int(now.timestamp())
    rows, failed = [], {}
    for sym, cfg in CRYPTO_ASSETS.items():
        cg = cfg.get("coingecko")
        if not cg:
            continue
        rd = await _sb_get("asset_mcap_daily", {"select": "symbol", "coin_id": f"eq.{cg}", "source": f"eq.{SOURCE}",
                                                "order": "d.desc", "limit": "1"})
        stored = ((rd.rows or [{}])[0].get("symbol") if rd.ok else None) or sym   # 沿用库里这个币已有的代码,不另起一行
        raw = await get_cg_market_chart_range(cg, frm_ts, to_ts, interval="daily")
        if not raw.get("available"):
            failed[sym] = str(raw.get("error") or raw.get("reason"))[:80]
            continue
        pts = parse_market_chart(raw.get("prices"), raw.get("market_caps"), raw.get("volumes"))
        rows += [{"symbol": stored, "coin_id": cg, "source": SOURCE, **p} for p in pts]
    err = await _upsert("asset_mcap_daily", rows, "symbol,d,source") if rows else None
    out["closes"] = {"rows": len(rows), "failed": failed, "error": err,
                     "last": max((r["d"] for r in rows), default=None)}
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
    volumes.update({f"migration.{k}": v for k, v in (await _migration_history(today)).items()})
    try:
        vol_hist = await _volume_history_all(today)
    except Exception as e:                                  # noqa: BLE001
        vol_hist = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    fundamentals = await _fundamentals()
    github = await _github(today)
    try:
        tradfi = await _tradfi(today)
    except Exception as e:                                  # noqa: BLE001
        tradfi = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    errors = [f"macro.{k}" for k, v in macro.items() if v.get("error")] + \
             [f"tvl.{k}" for k, v in protocols.items() if v.get("error")] + \
             [f"vol.{k}" for k, v in volumes.items() if not str(v).endswith("行")] + \
             [f"fund.{k}" for k, v in fundamentals.items() if v.get("error")] + \
             [f"gh.{k}" for k, v in github.items() if v.get("error")] + \
             (["tradfi"] if tradfi.get("error") else []) + \
             (["vol_history"] if vol_hist.get("error") or vol_hist.get("n_failed", 0) > 20 else [])
    return {"ok": not errors, "refused": False, "errors": errors[:20], "macro": macro, "protocols": protocols,
            "fundamentals": fundamentals, "github": {k: v for k, v in github.items() if v.get("error")},
            "volumes": volumes, "volume_history": vol_hist, "tradfi": tradfi,
            "reason": "全部写入" if not errors else f"{len(errors)} 项失败:{errors[:6]}"}
