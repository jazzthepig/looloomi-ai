"""上游通道的日度序列 —— 先从 CoinGecko Analyst 能给的开始(Jazz 2026-10-01)。

为什么:这一轮周期由传统资产代币化带动,而我们一直在用价格解释价格。稳定币供给、代币化资产规模
这些「资金从哪来」的量,一条都没有入库(S-457 后的讨论)。这里把 CoinGecko 能给的部分接进来:

- **稳定币**、**代币化资产**(国债、黄金、股票等)、**RWA**:CoinGecko 分类成员的市值逐日加总。
  分类 id **运行时从 `/coins/categories/list` 按关键词发现**,不写死 —— 新出现的代币化分类自动进来;
  发现了哪些写进 `channel_categories`,可审计。
- **全市场市值与成交额**:`/global/market_cap_chart`,作分母。

这些都是**水平**。进状态层时取变化量与加速度(扩散作用于变化,不作用于水平)。

**口径与已知偏差:**
- 市值 ≈ 流通规模:对稳定币与代币化基金这接近供给 / AUM;对其他币是价格 × 流通量。
- 成员是**今天**各分类的前 N 名往回取 —— 已消失的产品不在里面,历史规模偏低估增长前的存量。每行 `basis` 标注。
- CoinGecko 不按链拆分供给 —— 「哪条链承接」这一维要靠后续的 DeFiLlama 接入补。
- 时间戳语义同 S-436:00:00 UTC 的点 = 前一天收盘。
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

HISTORY_START = "2020-01-01"
MEMBERS_PER_CATEGORY = 50
SOURCE = "coingecko_pro_market_chart"
BASIS = "current_constituents_backfilled"
CODE_REF = "channels-v1"

#: 通道 → 分类 id 里出现的关键词(小写子串)。「发现」按这个做,结果落库。
CHANNEL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "stablecoin": ("stablecoin",),
    "tokenized": ("tokenized", "tokenised"),
    "rwa": ("real-world-asset", "rwa"),
}
#: 关键词误伤的排除(例如稳定币「协议」不是稳定币本身)。
EXCLUDE_IDS: frozenset[str] = frozenset()


def discover(category_ids: set[str]) -> dict[str, list[str]]:
    """纯函数:按关键词把分类 id 归到通道。一个 id 只归一个通道(按 CHANNEL_KEYWORDS 的顺序)。"""
    out: dict[str, list[str]] = {k: [] for k in CHANNEL_KEYWORDS}
    for cid in sorted(category_ids):
        if cid in EXCLUDE_IDS:
            continue
        for ch, kws in CHANNEL_KEYWORDS.items():
            if any(k in cid.lower() for k in kws):
                out[ch].append(cid)
                break
    return out


from src.data.market.bar_semantics import covered_day, is_day_boundary  # noqa: E402

def daily_points(points: list, tolerance_ms: int = 3_600_000) -> dict[str, float]:
    """[[ts_ms, v]…] → {覆盖日: v}。取 00:00 UTC 起 1 小时内的点(全局图的时间戳不一定正好是零点),
    d = 点的日期 − 1(S-436 语义);同一天多个点取最早的。"""
    out: dict[str, tuple[int, float]] = {}
    for t, v in points or []:
        t = int(t)
        if v is None or not is_day_boundary(t, tolerance_ms):
            continue
        d = covered_day("coingecko_global_chart", t).isoformat()   # 语义一处定义(T-049)
        if d not in out or t < out[d][0]:
            out[d] = (t, float(v))
    return {d: v for d, (_, v) in out.items()}


def aggregate(mcap: pd.DataFrame, members: dict[str, list[str]]) -> list[dict]:
    """纯函数:`mcap` 行 = 日期、列 = coin_id;`members` = {分组键: [coin_id…]}。
    每组每天:成员市值之和、当天有数的成员数。同一个币在一组里只算一次;缺值不补。"""
    rows = []
    for key, coins in members.items():
        cols = [c for c in dict.fromkeys(coins) if c in mcap.columns]
        if not cols:
            continue
        sub = mcap[cols]
        tot = sub.sum(axis=1, min_count=1)
        n = sub.notna().sum(axis=1)
        for d, v in tot.items():
            if pd.notna(v):
                rows.append({"d": d.date().isoformat(), "key": key, "mcap": float(v), "n_members": int(n.loc[d])})
    return rows


# ── I/O ─────────────────────────────────────────────────────────────────────

async def run_once() -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market.data_layer import (get_cg_category_ids, get_cg_category_markets,
                                            get_cg_global_market_cap_chart, get_cg_market_chart_range)
    from src.data.style.header import _read_all, parse_market_chart
    from src.data.vector.market_state_writer import _sb_get

    today = datetime.now(timezone.utc).date()
    found = discover(await get_cg_category_ids())
    cat_rows = [{"category_id": c, "channel": ch, "discovered_d": today.isoformat()}
                for ch, ids in found.items() for c in ids]
    if not cat_rows:
        return {"ok": False, "reason": "关键词一个分类都没发现 —— CoinGecko 分类名变了?不静默写 0"}
    res = await supabase_upsert_table("channel_categories", cat_rows, on_conflict="category_id,discovered_d")
    if not res.ok:
        return {"ok": False, "reason": f"channel_categories 写入失败:{res.why}"}

    members: dict[str, list[str]] = {}        # "通道/分类" 与 "通道/*" 两级
    for ch, ids in found.items():
        for cid in ids:
            rows = await get_cg_category_markets(cid, MEMBERS_PER_CATEGORY)
            coins = [r["id"] for r in rows or [] if r.get("id")]
            members[f"{ch}/{cid}"] = coins
            members.setdefault(f"{ch}/*", []).extend(coins)
            await asyncio.sleep(0.2)

    to_ts = int(datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    written, failed = 0, {}
    for coin in sorted({c for v in members.values() for c in v}):
        rd = await _sb_get("cg_coin_mcap_daily", {"select": "d", "coin_id": f"eq.{coin}",
                                                  "order": "d.desc", "limit": "1"})
        if not rd.ok:
            failed[coin] = f"读不到已有历史:{rd.reason}"
            continue
        last = (rd.rows or [{}])[0].get("d")
        frm = (date.fromisoformat(last) - timedelta(days=10)) if last else date.fromisoformat(HISTORY_START)
        from_ts = int(datetime.combine(frm, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        raw = await get_cg_market_chart_range(coin, from_ts, to_ts, interval="daily")
        if not raw.get("available"):
            failed[coin] = str(raw.get("error") or raw.get("reason"))[:120]
            continue
        pts = [{"coin_id": coin, "source": SOURCE, **p} for p in parse_market_chart(raw.get("prices"), raw.get("market_caps"))]
        for i in range(0, len(pts), 2000):
            w = await supabase_upsert_table("cg_coin_mcap_daily", pts[i:i + 2000], on_conflict="coin_id,d")
            if not w.ok:
                failed[coin] = f"写入失败:{w.why}"
                break
        else:
            written += len(pts)
        await asyncio.sleep(0.15)

    allc = sorted({c for v in members.values() for c in v})
    hist = []
    for i in range(0, len(allc), 40):
        hist += await _read_all("cg_coin_mcap_daily", {"select": "coin_id,d,mcap", "order": "d.asc",
                                                       "coin_id": "in.(" + ",".join(allc[i:i + 40]) + ")"})
    series: list[dict] = []
    if hist:
        df = pd.DataFrame(hist)
        df["d"] = pd.to_datetime(df["d"])
        mc = df.pivot_table(index="d", columns="coin_id", values="mcap")
        for r in aggregate(mc, members):
            ch, cat = r["key"].split("/", 1)
            series.append({"d": r["d"], "channel": ch, "category_id": cat, "mcap": r["mcap"],
                           "n_members": r["n_members"], "basis": BASIS, "code_ref": CODE_REF})

    g = await get_cg_global_market_cap_chart("max")
    for key, pts in (("market_cap", g["market_cap"]), ("volume", g["volume"])):
        for d, v in daily_points(pts).items():
            series.append({"d": d, "channel": "global", "category_id": key, "mcap": v,
                           "n_members": None, "basis": "coingecko_global", "code_ref": CODE_REF})
    for i in range(0, len(series), 2000):
        w = await supabase_upsert_table("channel_series_daily", series[i:i + 2000],
                                        on_conflict="d,channel,category_id")
        if not w.ok:
            return {"ok": False, "reason": f"channel_series_daily 写入失败:{w.why}"}
    n_coins = len(allc)
    ok = bool(series) and len(failed) <= max(5, n_coins // 10)
    return {"ok": ok, "categories": {k: len(v) for k, v in found.items()}, "coins": n_coins,
            "mcap_rows": written, "failed": list(failed)[:10], "series_rows": len(series),
            "reason": (f"分类 {sum(len(v) for v in found.values())} 个({ {k: len(v) for k, v in found.items()} }),"
                       f"币 {n_coins} 个,市值写 {written} 行,失败 {len(failed)};序列 {len(series)} 行")}
