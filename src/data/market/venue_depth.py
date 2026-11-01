"""我们真能下单的场所的盘口深度(T-082 B,11-02):每天 UTC 00 / 08 / 16 各采一次 Hyperliquid 现货与永续的
±1% / ±2% 订单簿深度,落 `venue_depth_snapshots`,容量接口多一列「场所口径」。

## 为什么

S-544 的容量按全市场报告成交额(CoinGecko 聚合)× 10% 参与率算:$30M 下 58/58 名都过。那个数含不能下单的场所与
刷量。T-085(lane-c)用 ccxt 量过 5 个 CEX:$500M 下 4/5 本账在场所深度上过不了 —— 但**我们现在只在 HL 上下单**
(真钱账户、东京主机),HL 那次没量到(ccxt 在沙盒里起不来)。所以先量我们真在用的那一个场所。

## 口径

- 深度 = 中间价 ±b 以内挂单的美元额(买盘 = 价 ≥ mid × (1 − b) 的 bid,卖盘 = 价 ≤ mid × (1 + b) 的 ask),b = 1%、2%。
- HL `l2Book` 每边只给 20 档。先取原始档(中间价、价差从这里来);原始 20 档覆盖不到 ±2% 的一边,改用 `nSigFigs = 3`
  的聚合档算那一边的深度(聚合档的价格粒度 ≤ 1%,边界那一档按聚合价判,写进 `granularity`)。聚合档也覆盖不到 ⇒
  深度是**下限**(`covered_*_pct` < 带宽时照写,不外推)。
- 名字:真钱在用的现货 UBTC / UETH / XAUT0 / SPYX;永续 = CIS 加密 25 个里在 HL 上市的 + R-v2 账本里 pending / open 的票。
- 容量(与 T-085 同一个式子):场所容量 = 7 天中位数的 min(买盘, 卖盘) ±2% 深度 ÷ 单名仓位比例(5%)。
  **冰山看不见,所以这是下限**;全市场口径是上限。两列并排,不合成一个数。

判活:`select fetched_utc, count(*) from venue_depth_snapshots group by 1 order by 1 desc limit 3`(每 8 小时一批)。
"""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Any, Optional

TABLE = "venue_depth_snapshots"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("fetched_utc", "venue", "symbol", "ex_symbol", "mid", "spread_bps",
                          "depth_1pct_bid_usd", "depth_1pct_ask_usd", "depth_2pct_bid_usd", "depth_2pct_ask_usd",
                          "covered_bid_pct", "covered_ask_pct", "granularity", "code_ref")}
CODE_REF = "venue_depth v1 (11-02)"
SLOTS_UTC = (0, 8, 16)
BANDS = (0.01, 0.02)
SPOT_TOKENS = {"BTC": "UBTC", "ETH": "UETH", "XAUT0": "XAUT0", "SPYX": "SPYX"}
COARSE_SIG_FIGS = 3
MEDIAN_DAYS = 7


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def slot_for(now: dt.datetime) -> dt.datetime:
    """纯函数。≤ now 的最近一个采样时点(UTC 00 / 08 / 16)。"""
    now = now.astimezone(dt.timezone.utc)
    h = max(s for s in SLOTS_UTC if s <= now.hour)
    return now.replace(hour=h, minute=0, second=0, microsecond=0)


def _levels(book: Any) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    lv = (book or {}).get("levels") if isinstance(book, dict) else None
    if not isinstance(lv, list) or len(lv) != 2:
        return [], []
    side = lambda xs: [(float(x["px"]), float(x["sz"])) for x in xs or [] if _f(x.get("px")) and _f(x.get("sz"))]
    return side(lv[0]), side(lv[1])


def band_depth(bids: list[tuple[float, float]], asks: list[tuple[float, float]], mid: float,
               band: float) -> tuple[float, float]:
    """纯函数。±band 以内两边的美元深度。"""
    b = sum(p * s for p, s in bids if p >= mid * (1 - band))
    a = sum(p * s for p, s in asks if p <= mid * (1 + band))
    return round(b, 2), round(a, 2)


def coverage(bids: list[tuple[float, float]], asks: list[tuple[float, float]], mid: float) -> tuple[float, float]:
    """纯函数。这一份盘口两边各覆盖到离中间价多远(%)。"""
    cb = (1 - bids[-1][0] / mid) * 100 if bids else 0.0
    ca = (asks[-1][0] / mid - 1) * 100 if asks else 0.0
    return round(cb, 3), round(ca, 3)


def measure(fine: Any, coarse: Any = None) -> Optional[dict[str, Any]]:
    """纯函数。原始档 → 中间价 / 价差 / 深度;原始档覆盖不到 ±2% 的那一边用聚合档。两边都没有 ⇒ None。"""
    fb, fa = _levels(fine)
    if not fb or not fa:
        return None
    mid = (fb[0][0] + fa[0][0]) / 2
    spread = (fa[0][0] - fb[0][0]) / mid * 1e4
    cb, ca = coverage(fb, fa, mid)
    far = max(BANDS) * 100
    gran = "raw"
    bids, asks = fb, fa
    if (cb < far or ca < far) and coarse is not None:
        xb, xa = _levels(coarse)
        xcb, xca = coverage(xb, xa, mid) if xb and xa else (0.0, 0.0)
        if cb < far and xb and xcb > cb:
            bids, cb, gran = xb, xcb, f"nSigFigs={COARSE_SIG_FIGS}"
        if ca < far and xa and xca > ca:
            asks, ca, gran = xa, xca, f"nSigFigs={COARSE_SIG_FIGS}"
    out = {"mid": round(mid, 10), "spread_bps": round(spread, 3), "covered_bid_pct": cb, "covered_ask_pct": ca,
           "granularity": gran}
    for b in BANDS:
        k = f"{int(b * 100)}pct"
        out[f"depth_{k}_bid_usd"], out[f"depth_{k}_ask_usd"] = band_depth(bids, asks, mid, b)
    return out


def sample_sync(client: Any, perp_coins: list[str], fetched_utc: str) -> tuple[list[dict], list[str]]:
    """同步(由调用方放进线程)。HL 现货四个 + 永续若干 → 行;读不到的名字写进第二个返回值,不写 0。"""
    from src.data.venues.hl_spot import HlSpotFixture
    fx = HlSpotFixture(client.spot_meta(), client.spot_meta_and_asset_ctxs(), {}, {})
    targets = []
    for sym, tok in SPOT_TOKENS.items():
        pair = fx.find_pair_by_token(tok)
        if pair is not None:
            targets.append(("hyperliquid_spot", sym, pair.name))
    targets += [("hyperliquid_perp", c, c) for c in perp_coins]
    rows, failed = [], []
    for venue, sym, ex in targets:
        try:
            fine = client.l2_book(ex)
            m = measure(fine)
            if m and (m["covered_bid_pct"] < max(BANDS) * 100 or m["covered_ask_pct"] < max(BANDS) * 100):
                m = measure(fine, client.l2_book(ex, n_sig_figs=COARSE_SIG_FIGS))
        except Exception as e:                                           # noqa: BLE001 — 一个名字读不到不拦其余
            failed.append(f"{venue}:{sym}:{type(e).__name__}")
            continue
        if m is None:
            failed.append(f"{venue}:{sym}:空盘口")
            continue
        rows.append({"fetched_utc": fetched_utc, "venue": venue, "symbol": sym, "ex_symbol": ex, **m, "code_ref": CODE_REF})
    return rows, failed


def venue_capacity(rows: list[dict], position_pct: float) -> dict[str, dict[str, Any]]:
    """纯函数。每个 (场所, 名字) 最近 MEDIAN_DAYS 天的中位深度 → 场所容量(下限)。"""
    by: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        by.setdefault((r["venue"], r["symbol"]), []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for (venue, sym), rs in by.items():
        def med(k: str) -> Optional[float]:
            xs = [x for x in (_f(r.get(k)) for r in rs) if x is not None]
            return statistics.median(xs) if xs else None
        d1 = [med("depth_1pct_bid_usd"), med("depth_1pct_ask_usd")]
        d2 = [med("depth_2pct_bid_usd"), med("depth_2pct_ask_usd")]
        min2 = min(d2) if None not in d2 else None
        cur = out.get(sym)
        row = {"venue": venue, "n_snapshots": len(rs), "depth_1pct_min_usd": min(d1) if None not in d1 else None,
               "depth_2pct_min_usd": min2, "median_spread_bps": med("spread_bps"),
               "venue_capacity_aum_usd": None if min2 is None else round(min2 / position_pct, 0),
               "lower_bound": any((_f(r.get("covered_bid_pct")) or 0) < 2 or (_f(r.get("covered_ask_pct")) or 0) < 2 for r in rs)}
        # 同一个名字现货、永续都有 ⇒ 两个都留,容量取现货(① 只持现货)
        if cur is None or venue == "hyperliquid_spot":
            out[sym] = {**row, "other": cur} if cur else row
        else:
            cur["other"] = row
    return out


async def perp_coins() -> list[str]:
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    from src.data.market.hyperliquid_collector import hyperliquid_universe
    from src.data.style.header import _read_all
    listed = set(await hyperliquid_universe())
    want = set(CRYPTO_ASSETS)
    try:
        tk = await _read_all("r_tickets_paper", {"select": "symbol", "status": "in.(pending,open)"})
        want |= {str(r["symbol"]).upper() for r in tk if r.get("symbol")}
    except Exception:                                                    # noqa: BLE001 — 账本读不到不挡采样
        pass
    return sorted(c for c in want if c in listed)


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    import asyncio
    from src.api.store import supabase_insert_table
    from src.data.style.header import _read_all
    from src.data.venues.hl_spot import HlSpotClient
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    slot = slot_for(now)
    have = await _read_all(TABLE, {"select": "fetched_utc", "fetched_utc": f"gte.{slot.isoformat()}", "limit": "1"})
    if have:
        return {"ok": True, "status": "skipped", "why": f"{slot:%Y-%m-%d %H}:00 这一批已采"}
    coins = await perp_coins()
    rows, failed = await asyncio.to_thread(sample_sync, HlSpotClient(), coins, now.isoformat())
    if not rows:
        return {"ok": False, "why": f"一个名字都没采到:{failed[:6]}"}
    w = await supabase_insert_table(TABLE, rows)
    if not w.ok:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(w.why or '')[:200]}"}
    return {"ok": True, "written": len(rows), "failed": failed, "slot": slot.isoformat(),
            "why": f"{slot:%Y-%m-%d %H}:00 采 {len(rows)} 个(读不到 {len(failed)})"}
