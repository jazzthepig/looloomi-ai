"""T-039 风格表头 —— 风格指数的计算与落库。

两个维度(v3,Jazz 09-30「公链和分类不冲突」):层级(大币 / 头部公链 / 二线公链与 L2 / 应用币,每币一个)
与板块(AI / meme / DeFi / 基础设施与代币化,每币零到多个)。见 `taxonomy.py`。

三张表(`scripts/supabase_t039_style_header.sql`):
- `style_membership`   每个币属于哪些 CoinGecko 分类、基础风格是什么(按抓取日留历史)
- `asset_mcap_daily`   每个币每天的价格与市值(CoinGecko market_chart,日线)
- `style_index_daily`  每个风格每天的收益与累计水平,市值加权(单币上限 40%)与等权两版

**时间戳语义(S-436 的教训,写在最前面):** CoinGecko market_chart 的日线点在 00:00 UTC 取样,
那一刻的价格就是**前一天的收盘**。所以 `d = 点的日期 − 1 天`;不在 00:00 的点(最后一个「现在」)丢弃。

**已知偏差,如实标注:** 成分来自**今天**各分类的市值前列,再往回取历史 —— 那些已经死掉的币不在里面,
所以回填出来的历史指数偏乐观(幸存者偏差,S-111 量过约 25pp/年)。每行 `basis` 字段写明这一点;
从今天起的前向部分成分按当天市值,没有这个偏差。
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from src.data.style.taxonomy import (DIMENSION, EXTRA_MEMBERS, MIN_MEMBERS, MIN_MEMBERS_DEFAULT,
                                     STYLES, all_category_ids, classify, members_by_index,
                                     resolve_tiers)

HISTORY_START = "2020-01-01"
SINGLE_CAP = 0.40
#: d-1 市值低于这个的币当天不进指数:小到几百万美元的币价格常有错点,等权时会把整个风格带飞
#: (v1 首轮出现过单日 +116,682% 的等权「收益」)。
MIN_MCAP_USD = 20e6
#: 单币单日收益超出这个范围按坏点处理(当天丢掉这个币,行里记 n_dropped),不参与平均。
MAX_DAILY_RET, MIN_DAILY_RET = 5.0, -0.95
#: 过去 30 天日收益标准差低于这个的币当天不进指数:RWA 分类里混着代币化国债(THBILL、FIGR_HELOC 等),
#: 价格钉在 1 附近,它们不是「代币化基础设施」的风险暴露,而是现金。
MIN_VOL_30D = 0.005
MEMBERS_PER_CATEGORY = 40
MEMBERSHIP_REFRESH_DAYS = 7
BASIS_BACKFILL = "current_constituents_backfilled"
SOURCE = "coingecko_pro_market_chart"
CODE_REF = "t039-v3b"
WEIGHTINGS = ("cap", "equal")


# ── 纯函数 ──────────────────────────────────────────────────────────────────

def parse_market_chart(prices: list, market_caps: list) -> list[dict]:
    """market_chart → [{d, price, mcap}]。只保留 00:00 UTC 的点,d = 点的日期 − 1。"""
    caps = {int(t): v for t, v in (market_caps or []) if t is not None}
    out = []
    for t, p in prices or []:
        t = int(t)
        if t % 86_400_000 != 0 or p is None:
            continue
        d = (datetime.fromtimestamp(t / 1000, tz=timezone.utc) - timedelta(days=1)).date()
        m = caps.get(t)
        out.append({"d": d.isoformat(), "price": float(p),
                    "mcap": float(m) if m else None})
    return out


def capped_weights(mcap: pd.Series, cap: float = SINGLE_CAP) -> pd.Series:
    """市值加权,单个上限 `cap`,超出部分按比例分给其余的(迭代到收敛)。"""
    w = mcap / mcap.sum()
    if len(w) * cap < 1:
        # 成员太少,上限无法满足(大币只有 BTC/ETH):用真实市值权重,不设上限。
        # v3 首版在这里退回了等权 —— 「大币」市值加权指数于是成了 BTC/ETH 各半,2021 年显示 +198%。
        return w
    for _ in range(50):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = (w[over] - cap).sum()
        w[over] = cap
        rest = ~over
        w[rest] += excess * w[rest] / w[rest].sum()
    return w


def compute_style_index(price: pd.DataFrame, mcap: pd.DataFrame,
                        tier_base: Mapping[str, str],
                        sectors: Optional[Mapping[str, frozenset]] = None, *,
                        start: str, end: str,
                        prev_level: Optional[Mapping[tuple[str, str], float]] = None,
                        basis: str = BASIS_BACKFILL) -> list[dict]:
    """逐日的风格指数行。PIT:成员与权重都用 d-1 的市值;收益 = d 相对 d-1 的收盘。

    `price` / `mcap`:行 = 日期(Timestamp),列 = 币。缺值是 NaN,**不前推**。
    成员不足 MIN_MEMBERS 的那一天不出行(拿不到 ≠ 收益为 0)。
    两个维度:层级指数每币一个;板块指数每币可以进多个(NEAR 既在公链里也在 AI 里)。
    """
    sectors = sectors or {}
    price = price.sort_index()
    mcap = mcap.reindex(price.index).sort_index()
    rets = price / price.shift(1) - 1
    # 日期不连续时(缺一整天),跨越缺口的「日收益」不是日收益 —— 丢掉
    gap = price.index.to_series().diff() != pd.Timedelta(days=1)
    rets[gap.values] = np.nan
    vol30 = rets.rolling(30, min_periods=20).std().shift(1)      # 只用 d 之前的,PIT
    level = dict(prev_level or {})
    rows: list[dict] = []
    days = price.index[(price.index >= pd.Timestamp(start)) & (price.index <= pd.Timestamp(end))]
    for d in days:
        i = price.index.get_loc(d)
        if i == 0:
            continue
        m_prev = mcap.iloc[i - 1].dropna()
        m_prev = m_prev[m_prev >= MIN_MCAP_USD]
        v = vol30.loc[d]
        m_prev = m_prev[[not (pd.notna(v.get(s)) and v.get(s) < MIN_VOL_30D) for s in m_prev.index]]
        idx_members = members_by_index(tier_base, sectors, m_prev.to_dict())
        r_d = rets.loc[d]
        for style in STYLES:
            cand = [s for s in idx_members.get(style, []) if pd.notna(r_d.get(s))]
            bad = [s for s in cand if not (MIN_DAILY_RET <= float(r_d[s]) <= MAX_DAILY_RET)]
            members = [s for s in cand if s not in bad]
            if len(members) < MIN_MEMBERS.get(style, MIN_MEMBERS_DEFAULT):
                continue
            r = r_d[members].astype(float)
            for wname in WEIGHTINGS:
                w = (capped_weights(m_prev[members].astype(float)) if wname == "cap"
                     else pd.Series(1.0 / len(members), index=members))
                ret = float((w * r).sum())
                key = (style, wname)
                level[key] = level.get(key, 1.0) * (1 + ret)
                top = w.idxmax()
                rows.append({"d": d.date().isoformat(), "style": style, "dimension": DIMENSION[style],
                             "weighting": wname,
                             "ret": ret, "level": level[key], "n_members": len(members),
                             "n_dropped": len(bad), "top_member": top, "top_weight": float(w[top]),
                             "members": sorted(members), "basis": basis, "code_ref": CODE_REF})
    return rows


# ── I/O ─────────────────────────────────────────────────────────────────────

async def _read_all(table: str, params: dict) -> list[dict]:
    """分页读全表。读不到抛异常 —— 读不到 ≠ 0 行(S-180)。"""
    from src.data.vector.market_state_writer import _sb_get
    out: list[dict] = []
    offset = 0
    while True:
        rd = await _sb_get(table, {**params, "limit": "1000", "offset": str(offset)})
        if not rd.ok:
            raise RuntimeError(f"{table} 读不到(offset={offset}):{rd.reason}")
        batch = rd.rows or []
        out.extend(batch)
        if len(batch) < 1000:
            return out
        offset += len(batch)


async def refresh_membership(today: date) -> dict[str, Any]:
    """按分类抓成员,算基础风格,按抓取日落库。分类 id 先对 CoinGecko 校验。"""
    from src.api.store import supabase_upsert_table
    from src.data.market.data_layer import get_cg_category_ids, get_cg_category_markets
    known = await get_cg_category_ids()
    unknown = [c for c in all_category_ids() if c not in known]
    if unknown:
        raise RuntimeError(f"分类 id 在 CoinGecko 不存在:{unknown} —— 改 taxonomy,不静默跳过")
    cats: dict[str, set] = {}
    coin: dict[str, tuple[str, float]] = {}
    for cid in all_category_ids():
        rows = await get_cg_category_markets(cid, MEMBERS_PER_CATEGORY)
        for r in rows or []:
            sym = str(r.get("symbol") or "").upper()
            mc = float(r.get("market_cap") or 0)
            if not sym:
                continue
            if sym in coin and coin[sym][0] != r["id"] and coin[sym][1] >= mc:
                continue          # 同名币:留市值大的那个
            coin[sym] = (r["id"], mc)
            cats.setdefault(sym, set()).add(cid)
        await asyncio.sleep(0.2)
    rows = [{"symbol": s, "coin_id": coin[s][0], "categories": sorted(cats[s]),
             "base_style": (classify(s, cats[s]) or (None,))[0], "fetched_d": today.isoformat()}
            for s in coin]
    res = await supabase_upsert_table("style_membership", rows, on_conflict="symbol,fetched_d")
    if not res.ok:
        raise RuntimeError(f"style_membership 写入失败:{res.why}")
    return {"n": len(rows), "by_style": pd.Series([r["base_style"] for r in rows]).value_counts(dropna=False).to_dict()}


def _member(symbol: str, coin_id: str, categories, fetched_d: str) -> dict:
    c = classify(symbol, categories or [])
    return {"symbol": symbol, "coin_id": coin_id, "fetched_d": fetched_d,
            "tier_base": c[0] if c else None, "sectors": sorted(c[1]) if c else []}


async def latest_membership() -> list[dict]:
    """最近一次抓取的成员。**层级与板块在读取时按当前分类法重算**(改规则不必等 7 天重抓),再并入 EXTRA_MEMBERS。"""
    rows = await _read_all("style_membership", {"select": "symbol,coin_id,categories,fetched_d",
                                                "order": "fetched_d.desc"})
    if not rows:
        return []
    last = rows[0]["fetched_d"]
    out = {r["symbol"]: _member(r["symbol"], r["coin_id"], r.get("categories"), last)
           for r in rows if r["fetched_d"] == last}
    for sym, (cid, cats) in EXTRA_MEMBERS.items():
        out[sym] = _member(sym, cid, cats, last)
    return list(out.values())


def _dims(members: list[dict]) -> tuple[dict[str, str], dict[str, frozenset]]:
    tier = {m["symbol"]: m["tier_base"] for m in members if m.get("tier_base")}
    sec = {m["symbol"]: frozenset(m.get("sectors") or ()) for m in members if m.get("tier_base")}
    return tier, sec


async def backfill_mcap(members: list[dict], today: date) -> dict[str, Any]:
    """每个币补到昨天。已有历史的只取最近 10 天;没有的从 HISTORY_START 取。"""
    from src.api.store import supabase_upsert_table
    from src.data.market.data_layer import get_cg_market_chart_range
    from src.data.vector.market_state_writer import _sb_get
    written, failed = 0, {}
    to_ts = int(datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    for m in members:
        if m.get("tier_base") is None:
            continue
        rd = await _sb_get("asset_mcap_daily", {"select": "d", "symbol": f"eq.{m['symbol']}",
                                                "coin_id": f"eq.{m['coin_id']}",
                                                "order": "d.desc", "limit": "1"})
        if not rd.ok:
            failed[m["symbol"]] = f"读不到已有历史:{rd.reason}"
            continue
        last = (rd.rows or [{}])[0].get("d")
        frm = (date.fromisoformat(last) - timedelta(days=10)) if last else date.fromisoformat(HISTORY_START)
        from_ts = int(datetime.combine(frm, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        raw = await get_cg_market_chart_range(m["coin_id"], from_ts, to_ts, interval="daily")
        if not raw.get("available"):
            failed[m["symbol"]] = str(raw.get("error") or raw.get("reason"))[:120]
            continue
        pts = parse_market_chart(raw.get("prices"), raw.get("market_caps"))
        rows = [{"symbol": m["symbol"], "coin_id": m["coin_id"], "source": SOURCE, **p} for p in pts]
        for i in range(0, len(rows), 2000):
            res = await supabase_upsert_table("asset_mcap_daily", rows[i:i + 2000],
                                              on_conflict="symbol,d,source")
            if not res.ok:
                failed[m["symbol"]] = f"写入失败:{res.why}"
                break
        else:
            written += len(rows)
        await asyncio.sleep(0.15)
    return {"rows": written, "failed": failed}


async def rebuild_index(members: list[dict], end: date) -> dict[str, Any]:
    """从已存的价格与市值重算风格指数。表空时从头算,否则从最后一行往回 40 天接着算。"""
    from src.api.store import supabase_upsert_table
    tier_base, sectors = _dims(members)
    from src.data.vector.market_state_writer import _sb_get
    rd = await _sb_get("style_index_daily", {"select": "d,code_ref", "order": "d.desc", "limit": "1"})
    if not rd.ok:
        raise RuntimeError(f"style_index_daily 读不到:{rd.reason}")
    top = (rd.rows or [{}])[0]
    # 分类法或算法变了(code_ref 不同)⇒ 从头重算,不接旧水平
    last = top.get("d") if top.get("code_ref") == CODE_REF else None
    start = (date.fromisoformat(last) - timedelta(days=40)) if last else date.fromisoformat(HISTORY_START)
    prev_level: dict[tuple[str, str], float] = {}
    if last:
        prev = await _read_all("style_index_daily", {"select": "style,weighting,level,d",
                                                     "d": f"eq.{(start - timedelta(days=1)).isoformat()}"})
        prev_level = {(r["style"], r["weighting"]): float(r["level"]) for r in prev}
    rows = await _read_all("asset_mcap_daily", {
        "select": "symbol,coin_id,d,price,mcap", "source": f"eq.{SOURCE}",
        "d": f"gte.{(start - timedelta(days=3)).isoformat()}", "order": "d.asc,symbol.asc"})
    if not rows:
        return {"written": 0, "reason": "asset_mcap_daily 在窗口里 0 行 —— 先补市值历史"}
    want = {m["symbol"]: m["coin_id"] for m in members}
    df = pd.DataFrame(rows)
    df = df[df["coin_id"] == df["symbol"].map(want)]     # 同名币换过 id 时,旧 id 的行不参与
    df["d"] = pd.to_datetime(df["d"])
    days = pd.date_range(df["d"].min(), df["d"].max(), freq="D")
    price = df.pivot_table(index="d", columns="symbol", values="price").reindex(days)
    mcap = df.pivot_table(index="d", columns="symbol", values="mcap").reindex(days)
    out = await asyncio.to_thread(compute_style_index, price, mcap, tier_base, sectors,
                                  start=start.isoformat(), end=end.isoformat(), prev_level=prev_level)
    for i in range(0, len(out), 2000):
        res = await supabase_upsert_table("style_index_daily", out[i:i + 2000],
                                          on_conflict="d,style,weighting")
        if not res.ok:
            raise RuntimeError(f"style_index_daily 写入失败:{res.why}")
    return {"written": len(out), "from": start.isoformat(), "to": end.isoformat()}


async def run_once() -> dict[str, Any]:
    """一轮:成员(每 7 天)→ 市值历史补到昨天 → 风格指数重算。"""
    today = datetime.now(timezone.utc).date()
    members = await latest_membership()
    refreshed = None
    if not members or (today - date.fromisoformat(members[0]["fetched_d"])).days >= MEMBERSHIP_REFRESH_DAYS:
        refreshed = await refresh_membership(today)
        members = await latest_membership()
    mc = await backfill_mcap(members, today)
    idx = await rebuild_index(members, today - timedelta(days=1))
    expo = await book_exposures(members, today - timedelta(days=45))
    n_styled = sum(1 for m in members if m.get("tier_base"))
    ok = idx.get("written", 0) > 0 and len(mc["failed"]) <= max(3, n_styled // 10)
    return {"ok": ok, "refused": False, "membership": refreshed, "n_styled": n_styled,
            "mcap_rows": mc["rows"], "mcap_failed": list(mc["failed"])[:10], "index": idx,
            "exposure": expo,
            "reason": (f"{n_styled} 个币有风格;市值写 {mc['rows']} 行,失败 {len(mc['failed'])} 个;"
                       f"指数写 {idx.get('written', 0)} 行;账本风格暴露写 {expo.get('written', 0)} 行")}


# ── 账本的风格暴露(持仓法)───────────────────────────────────────────────────
#
# 有逐日权重的账本,暴露就是「持仓按风格加总」—— 精确,不需要回归。
# 没有逐日权重的(多空账本只存前三大持仓)先不算,不用回归去猜。

EXPOSURE_BOOKS: tuple[tuple[str, str, str], ...] = (
    # (表, 权重列, 标签)
    ("beta_plus_daily", "weights", "beta_plus"),
    ("tokenization_tilt_daily", "weights", "tokenization_tilt"),
)


def exposure_shares(weights: Mapping[str, float], tiers: Mapping[str, str],
                    sectors: Mapping[str, frozenset]) -> list[tuple[str, str, float]]:
    """持仓 → [(维度, 名字, 占总多头的比例)]。

    层级:各层加起来 = 1(未归类的单列 'unclassified',不丢)。
    板块:每个板块各自是「持仓里带这个标签的币占多少」—— 可以重叠,加起来不必等于 1。
    """
    tot = sum(max(0.0, float(w)) for w in weights.values())
    if tot <= 0:
        return []
    tier_sh: dict[str, float] = {}
    sec_sh: dict[str, float] = {}
    for s, w in weights.items():
        w = max(0.0, float(w)) / tot
        if w == 0:
            continue
        s = s.upper()
        k = tiers.get(s, "unclassified")
        tier_sh[k] = tier_sh.get(k, 0.0) + w
        for sec in sectors.get(s, ()):
            sec_sh[sec] = sec_sh.get(sec, 0.0) + w
    return ([("tier", k, v) for k, v in tier_sh.items()]
            + [("sector", k, v) for k, v in sec_sh.items()])


async def book_exposures(members: list[dict], since: date) -> dict[str, Any]:
    """逐日、逐账本、逐臂的风格暴露,落 `book_style_exposure_daily`。公链档位按 d-1 市值(PIT)。"""
    from src.api.store import supabase_upsert_table
    tier_base, sectors = _dims(members)
    want = {m["symbol"]: m["coin_id"] for m in members}
    mc = await _read_all("asset_mcap_daily", {"select": "symbol,coin_id,d,mcap", "source": f"eq.{SOURCE}",
                                              "d": f"gte.{(since - timedelta(days=2)).isoformat()}"})
    mcap_by_d: dict[str, dict[str, float]] = {}
    for r in mc:
        if want.get(r["symbol"]) == r["coin_id"] and r.get("mcap"):
            mcap_by_d.setdefault(r["d"], {})[r["symbol"]] = float(r["mcap"])
    out: list[dict] = []
    for table, col, label in EXPOSURE_BOOKS:
        rows = await _read_all(table, {"select": f"d,arm,{col}", "d": f"gte.{since.isoformat()}",
                                       "order": "d.asc"})
        for r in rows:
            prev = (date.fromisoformat(r["d"]) - timedelta(days=1)).isoformat()
            tiers = resolve_tiers(tier_base, mcap_by_d.get(prev, {}))
            w = r.get(col) or {}
            for dim, st, share in exposure_shares(w, tiers, sectors):
                out.append({"d": r["d"], "book": label, "arm": r["arm"], "dimension": dim, "style": st,
                            "weight": share, "n_holdings": sum(1 for v in w.values() if float(v) > 0),
                            "code_ref": CODE_REF})
    for i in range(0, len(out), 2000):
        res = await supabase_upsert_table("book_style_exposure_daily", out[i:i + 2000],
                                          on_conflict="d,book,arm,style")
        if not res.ok:
            raise RuntimeError(f"book_style_exposure_daily 写入失败:{res.why}")
    return {"written": len(out)}
