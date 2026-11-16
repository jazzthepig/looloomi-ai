"""
Positioning pressure — the UPSTREAM cause #2 (reflexive forced flow, not a reflection).

Forward supply (cause #1) is STRUCTURAL forced selling (unlocks). This is REFLEXIVE forced flow:
leverage. Extreme positive funding + high open interest = overleveraged longs whose liquidation
is a forced future SELL (bearish); extreme negative funding + high OI = overleveraged shorts whose
squeeze is a forced future BUY (bullish). The positioning is a decision already made; the
liquidation propagates into price LATER — upstream, knowable now, not a reflection of price.

This is the marginal participant being *forced* — the mechanism under the whole 大象无形 / marginal-
buyer thesis, made a signal. Signed: positioning_pressure ∈ [-1 (bearish long-liq) .. +1 (bullish squeeze)].

**读库优先(11-16)。** 原来这里每 30 分钟直接打 CoinGecko 的**公开** `/derivatives`,而
`src/data/market/derivatives_market.py` 每 6 小时把**同一份数据**落进 `derivatives_market_daily` ——
一个端点,两个额度池:公开端点每分钟只有十几次(Pro key 在公开 host 上会被忽略),429 是家常便饭;
Analyst 档每分钟 500 次却几乎没被这条路径用上。「路径直接走了调用,而不是先走我们的数据库」的
一个具体实例。现在:**先读表**,读不到 / 读旧了(>12 小时)才回落 **Pro** 端点。同一个端点只花一次额度。

**口径(两条路逐位相同)。** funding = 全场所永续的 **OI 加权平均**资金费,只有带 funding_rate 的
永续参与加权。读库路径:`funding_oiw_sum / oi_funding_usd`;API 路径:`Σ(f·oi) / Σ(oi)` —— 同一个式子。
不要拿这张表的 `top_funding_raw`(持仓最大的那个场所的资金费)顶替:那是另一个量。
单位无关:资金费按横截面分位数缩放,原始单位不影响结果。喂给唯一的 kernel(conviction)。
"""
from __future__ import annotations

import datetime as dt
import logging

logger = logging.getLogger(__name__)

_POS_KEY = "cis:positioning"
_POS_TTL = 30 * 60          # positioning moves faster than supply → 30 min
_MIN_OI_USD = 5_000_000     # ignore illiquid perps; positioning is only meaningful with real OI
TABLE = "derivatives_market_daily"
#: derivatives_market_daily 每 6 小时写一轮;超过两个周期没写上 ⇒ 表不可信,回落 API。
_MAX_DB_AGE_H = 12.0
#: 2026-10-26 用户报告:NEAR 的 oi_usd 20 亿,而 Hyperliquid 上只有 2.6 亿 —— 两个都对,口径不同。写进每条记录。
POSITIONING_SCOPE = ("CoinGecko /derivatives, every listed perp venue summed (includes small venues); funding = "
                     "OI-weighted mean of venue-reported rates in CoinGecko units (venues settle on different "
                     "intervals) — read positioning_pressure, not the raw funding; single-venue depth is in "
                     "tradability")


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _f(x):
    """float 或 None(坏值 / NaN 一律 None —— 不拿 0 冒充「没有资金费」)。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _compute(agg: dict) -> dict:
    """agg: {SYM: {"oi_wsum": Σ funding·oi, "oi": Σ oi}} → signed positioning pressure per asset.
    Robust: |funding| scaled by its 90th percentile across assets (unit-agnostic)."""
    fund = {}
    for sym, a in agg.items():
        oi = a["oi"]
        if oi < _MIN_OI_USD:
            continue
        fund[sym] = (a["oi_wsum"] / oi, oi)          # OI-weighted mean funding, total OI
    if not fund:
        return {}
    mags = sorted(abs(f) for f, _ in fund.values())
    p90 = mags[int(0.9 * (len(mags) - 1))] or (mags[-1] or 1e-9)
    scale = p90 or 1e-9
    out = {}
    for sym, (f, oi) in fund.items():
        # extreme POSITIVE funding → overleveraged longs → forced SELL → bearish (negative pressure)
        pressure = _clamp(-f / scale, -1.0, 1.0)
        out[sym] = {"positioning_pressure": round(pressure, 3),
                    "funding": round(f, 6), "oi_usd": round(oi, 0), "scope": POSITIONING_SCOPE}
    return out


def _agg_from_tickers(rows, known: set[str]) -> dict:
    """/derivatives 的合约行 → {SYM: {"oi_wsum", "oi"}}。只收永续、只收有 funding_rate 的行
    (没有资金费的合约不参与加权 —— 和落库那一份的口径一致)。"""
    agg: dict = {}
    for t in rows if isinstance(rows, list) else []:
        if not isinstance(t, dict):
            continue
        if (t.get("contract_type") or "perpetual") != "perpetual":
            continue
        sym = (t.get("index_id") or "").upper().strip()
        if sym not in known:
            continue
        f = _f(t.get("funding_rate"))
        oi = _f(t.get("open_interest"))
        if f is None or oi is None or oi <= 0:
            continue
        a = agg.setdefault(sym, {"oi_wsum": 0.0, "oi": 0.0})
        a["oi_wsum"] += f * oi
        a["oi"] += oi
    return agg


def _age_hours(fetched_at: str, latest_d: str, today: dt.date) -> float:
    """这一份数据有多旧(小时)。fetched_at 解析不出来就按「当天写的」最坏估。"""
    if fetched_at:
        raw = fetched_at.replace("Z", "+00:00")
        for cand in (raw, raw[:19]):
            try:
                ts = dt.datetime.fromisoformat(cand)
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            return max(0.0, (dt.datetime.now(dt.timezone.utc) - ts).total_seconds() / 3600.0)
    try:
        d = dt.date.fromisoformat(latest_d)
    except ValueError:
        return 999.0
    return (today - d).days * 24.0 + 24.0


async def _read_db(known: set[str]) -> tuple[dict, str]:
    """读 derivatives_market_daily 的最新一天 → {SYM: {"oi_wsum", "oi"}}。返回 (agg, 为什么)。

    读到的两列就是落库那一份的分子分母,除出来和 API 路径逐位相同。"""
    from src.data.vector.market_state_writer import _sb_get
    today = dt.datetime.now(dt.timezone.utc).date()
    since = (today - dt.timedelta(days=1)).isoformat()
    try:
        rd = await _sb_get(TABLE, {"select": "symbol,oi_funding_usd,funding_oiw_sum,d,fetched_at",
                                    "d": f"gte.{since}", "order": "d.desc", "limit": "4000"})
    except Exception as e:                                                 # noqa: BLE001 —— 读表失败不该把整条路径带走
        return {}, f"读 {TABLE} 失败:{type(e).__name__}"
    if not rd.ok:
        return {}, f"读不到 {TABLE}:{rd.reason}"
    rows = [r for r in (rd.rows or []) if isinstance(r, dict)]
    if not rows:
        return {}, f"{TABLE} 近两天没有行"
    latest_d = max(str(r.get("d") or "")[:10] for r in rows)
    agg: dict = {}
    newest = ""
    for r in rows:
        if str(r.get("d") or "")[:10] != latest_d:
            continue
        sym = str(r.get("symbol") or "").upper()
        if sym not in known:
            continue
        oi = _f(r.get("oi_funding_usd"))
        wsum = _f(r.get("funding_oiw_sum"))
        if oi is None or wsum is None or oi <= 0:
            continue
        agg[sym] = {"oi_wsum": wsum, "oi": oi}
        fa = str(r.get("fetched_at") or "")
        if fa > newest:
            newest = fa
    if not agg:
        return {}, f"{TABLE} {latest_d} 的行里没有已知标的(资金费两列还没写上?)"
    age = _age_hours(newest, latest_d, today)
    if age > _MAX_DB_AGE_H:
        return {}, f"{TABLE} 旧了(最新 {latest_d},fetched_at {newest},{age:.1f} 小时前)"
    return agg, f"{TABLE} {latest_d}(fetched_at {newest},{age:.1f} 小时前)"


async def _read_api(known: set[str]) -> tuple[dict, str]:
    """回落:CoinGecko `/derivatives`。有 key 走 **Pro** 端点(每分钟 500 次),没有才走公开端点。
    原来这里写死的是公开端点 —— 那才是 429 的来源。"""
    from src.data.market.data_layer import CG_API_KEY, CG_PRO_BASE, _cg_headers, _get_cg_client
    base = CG_PRO_BASE if CG_API_KEY else "https://api.coingecko.com/api/v3"
    headers = _cg_headers() if CG_API_KEY else {}
    try:
        r = await _get_cg_client().get(f"{base}/derivatives", headers=headers,
                                       params={"include_tickers": "unexpired"}, timeout=60)
        r.raise_for_status()
        rows = r.json()
    except Exception as e:                                                 # noqa: BLE001
        return {}, f"CG /derivatives 取不到:{type(e).__name__}: {e}"
    return _agg_from_tickers(rows, known), ("CG Pro /derivatives" if CG_API_KEY else "CG 公开 /derivatives")


async def refresh_positioning() -> dict:
    """先读库、读不到才调 API,汇总资金费·持仓 → 有符号的 positioning pressure → Redis。"""
    from src.data.market.data_layer import _redis_set
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    known = set(CRYPTO_ASSETS.keys())
    agg, src = await _read_db(known)
    if not agg:
        logger.warning(f"[POSITIONING] 读库没拿到({src})—— 回落 API")
        agg, src = await _read_api(known)
    if not agg:
        logger.warning(f"[POSITIONING] 两条路都没拿到数据: {src}")
        return {}
    out = _compute(agg)
    await _redis_set(_POS_KEY, out, ttl=_POS_TTL)
    extreme = sorted(((v["positioning_pressure"], s) for s, v in out.items()), key=lambda x: x[0])
    tail = extreme[:3] + extreme[-3:]
    logger.info(f"[POSITIONING] {len(out)} assets · 来源 {src}; extremes: "
                f"{', '.join(f'{s}={p:+.2f}' for p, s in tail)}")
    return out


async def get_positioning_map() -> dict:
    from src.data.market.data_layer import _redis_get
    m = await _redis_get(_POS_KEY)
    return m if isinstance(m, dict) else {}


def attach_positioning(universe: list, pmap: dict) -> None:
    pmap = pmap or {}
    for a in universe:
        if isinstance(a, dict):
            sym = (a.get("symbol") or a.get("asset_id") or "").upper()
            a["positioning"] = pmap.get(sym)
