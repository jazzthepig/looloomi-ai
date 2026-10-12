"""容量:当下规模($30M)与设计规模($500M)下,每个名字、每本账能不能在给定天数内建满仓(S-544)。

Jazz 10-12:「AUM 先解决 30M,之后再达到 500M。我们需要定好设计和工程的冗余,不用我中途再升级。」
所以每个容量检查同时按两个规模算,口径在 `src/api/contracts/fund.py` 一处定义。

- 名字:日成交额(过去 30 天中位数)× 参与率 = 一天能吃下的量;满仓位 = 规模 × 单名仓位比例;建仓天数 = 两者之比;
  容量 = 在 BUILD_DAYS 天内建满时能承受的最大规模。
- 账本:按最新持仓权重,每个持仓都要在 BUILD_DAYS 天内建满 —— 账本容量 = 各持仓容量的最小值,并写出卡住的那个名字。
- 成交额是全市场报告值(CoinGecko 聚合 / EODHD),我们能下单的场所的深度更低;场所检查另列。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from src.api.contracts.fund import (BUILD_DAYS, DESIGN_AUM_USD, PARTICIPATION_RATE, SATELLITE_POSITION_PCT,
                                    TARGET_AUM_USD)

#: 有持仓权重的账本:登记表 id → (表, 臂)
WEIGHTED_BOOKS = {"core_cap": ("core_cap_daily", "cap_a1"), "cis_tilt": ("cis_tilt_daily", "cis_a1"),
                  "beta_plus_w": ("beta_plus_daily", "momentum_52w_w"), "beta_plus_m": ("beta_plus_daily", "momentum_52w_m"),
                  "tokenization_tilt": ("tokenization_tilt_daily", "tokenization_tilt_25")}


def days_to_build(aum: float, weight: float, adv_usd: Optional[float]) -> Optional[float]:
    if not adv_usd or adv_usd <= 0:
        return None
    return aum * weight / (adv_usd * PARTICIPATION_RATE)


def capacity_aum(weight: float, adv_usd: Optional[float]) -> Optional[float]:
    """在 BUILD_DAYS 天内建满这个仓位时能承受的最大规模。"""
    if not adv_usd or adv_usd <= 0 or weight <= 0:
        return None
    return adv_usd * PARTICIPATION_RATE * BUILD_DAYS / weight


def asset_row(symbol: str, asset_class: Optional[str], adv_usd: Optional[float]) -> dict[str, Any]:
    """纯函数。一个名字按「卫星仓位」(SATELLITE_POSITION_PCT)的容量。"""
    dt = days_to_build(TARGET_AUM_USD, SATELLITE_POSITION_PCT, adv_usd)
    dd = days_to_build(DESIGN_AUM_USD, SATELLITE_POSITION_PCT, adv_usd)
    cap = capacity_aum(SATELLITE_POSITION_PCT, adv_usd)
    return {"symbol": symbol, "asset_class": asset_class, "adv_usd": adv_usd,
            "days_to_build_at_target": dt, "days_to_build_at_design": dd, "capacity_aum_usd": cap,
            "ok_at_target": dt is not None and dt <= BUILD_DAYS, "ok_at_design": dd is not None and dd <= BUILD_DAYS}


def book_row(book: str, weights: Mapping[str, float], adv: Mapping[str, float]) -> dict[str, Any]:
    """纯函数。一本账按最新持仓的容量;没有成交额数据的持仓单列(不当成无限流动)。"""
    caps, missing = [], []
    for sym, w in weights.items():
        if not w or w <= 0:
            continue
        a = adv.get(sym.upper())
        if a is None:
            missing.append(sym)
            continue
        caps.append((capacity_aum(w, a), sym, w, a))
    caps = [c for c in caps if c[0] is not None]
    if not caps:
        return {"book": book, "capacity_aum_usd": None, "binding": None, "missing_adv": missing}
    cap, sym, w, a = min(caps)
    worst_t = max(days_to_build(TARGET_AUM_USD, ww, aa) for _, _, ww, aa in caps)
    worst_d = max(days_to_build(DESIGN_AUM_USD, ww, aa) for _, _, ww, aa in caps)
    return {"book": book, "capacity_aum_usd": cap,
            "binding": {"symbol": sym, "weight": w, "adv_usd": a},
            "days_to_build_at_target": worst_t, "days_to_build_at_design": worst_d,
            "ok_at_target": worst_t <= BUILD_DAYS, "ok_at_design": worst_d <= BUILD_DAYS,
            "missing_adv": missing}


async def _adv() -> dict[str, float]:
    """过去 30 天日成交额(美元)中位数:加密用 asset_mcap_daily(CG 聚合),传统资产用标准重建的 inputs.volume。"""
    import statistics
    from src.data.cis.rebuild import CODE_REF, TABLE as REBUILD
    from src.data.style.header import SOURCE, _read_all
    since = (datetime.now(timezone.utc).date() - timedelta(days=31)).isoformat()
    rows = await _read_all("asset_mcap_daily", {"select": "symbol,d,volume", "source": f"eq.{SOURCE}", "d": f"gte.{since}"})
    vols: dict[str, list[float]] = {}
    for r in rows:
        if r.get("volume"):
            vols.setdefault(str(r["symbol"]).upper(), []).append(float(r["volume"]))
    reb = await _read_all(REBUILD, {"select": "symbol,d,asset_class,inputs", "code_ref": f"eq.{CODE_REF}", "d": f"gte.{since}"})
    tf: dict[str, list[float]] = {}
    for r in reb:
        v = (r.get("inputs") or {}).get("volume")
        if v:
            tf.setdefault(str(r["symbol"]).upper(), []).append(float(v))
    out = {k: statistics.median(v) for k, v in vols.items() if v}
    for k, v in tf.items():
        out.setdefault(k, statistics.median(v))
    return out


async def report() -> dict[str, Any]:
    from src.data.cis.cis_provider import ASSETS_CONFIG
    from src.data.vector.market_state_writer import _sb_get
    adv = await _adv()
    assets = [asset_row(s, c.get("class"), adv.get(s)) for s, c in ASSETS_CONFIG.items()]
    books = []
    for bid, (table, arm) in WEIGHTED_BOOKS.items():
        rd = await _sb_get(table, {"select": "d,weights", "arm": f"eq.{arm}", "weights": "not.is.null",
                                   "order": "d.desc", "limit": "1"})
        w = ((rd.rows or [{}])[0].get("weights") or {}) if rd.ok else {}
        row = book_row(bid, {k: float(v) for k, v in w.items() if v is not None}, adv)
        row["as_of"] = (rd.rows or [{}])[0].get("d") if rd.ok else None
        books.append(row)
    return {
        "target_aum_usd": TARGET_AUM_USD, "design_aum_usd": DESIGN_AUM_USD,
        "assumptions": {"satellite_position_pct": SATELLITE_POSITION_PCT, "participation_rate": PARTICIPATION_RATE,
                        "build_days": BUILD_DAYS,
                        "volume": "median daily USD volume over 30 days, as reported across venues (CoinGecko aggregate "
                                  "for crypto, EODHD for traditional assets); depth on the venues we can trade is lower"},
        "summary": {"assets_ok_at_target": sum(a["ok_at_target"] for a in assets),
                    "assets_ok_at_design": sum(a["ok_at_design"] for a in assets), "assets": len(assets),
                    "books_ok_at_design": [b["book"] for b in books if b.get("ok_at_design")],
                    "books_not_ok_at_design": [b["book"] for b in books if b.get("capacity_aum_usd") and not b.get("ok_at_design")]},
        "books": books,
        "assets": sorted(assets, key=lambda a: (a["capacity_aum_usd"] is None, a["capacity_aum_usd"] or 0)),
    }
