"""代币持有人数的历史(CoinGecko Analyst `/onchain/networks/{net}/tokens/{addr}/holders_chart`,Beta —— Jazz 11-06「先把 Analyst API 用足」)。

**为什么:** 持有人数是采用面的**因**(出圈 = 人变多),价格是它的果之一。我们只有前 50 大持有人的快照
(`holder_provider.py`,集中度),没有「人数随时间怎么变」。CoinGecko 给 `days=max`(周频历史)和 `days=30`(日频)。

**宇宙:** `cg_coin_mcap_coins`(`cg_coin_mcap_daily` ∪ `asset_mcap_daily` 里出现过的全部币,1,216 个,含已掉出前列的 —— 时点宇宙,不是今天的幸存者;11-06 前者单独没有 BTC / ETH 等主币),
取它在 CoinGecko 上的**第一个平台**(= 本链;桥过去的副本不算,别的链上的人数是另一回事),本链不在 CoinGecko 支持的
网络里就跳过(原生 L1 币没有合约,也跳过;SUI 这种本链原生代币有地址,照收)。

**取法:** 每轮先用 `/coins/list?include_platform=true`(1 次)拿平台;没有周频历史的币取 `days=max`(每轮最多
`MAX_BACKFILL` 个,按日期轮换,别让同几个取不到的币每轮占满额度);**已有日频历史**、最新一天落后的取 `days=30`(最多 `MAX_DAILY` 个);
**只有周频历史**的币不占日频名额,只做有界轮换探测(每轮最多 `MAX_WEEKLY_PROBE` 个,按日期哈希轮换)。

**11-16 修:周频币不该每轮都进日频队列。** 原来「最新的落后了一天 ⇒ 进日频队列」只看 `max_d`,不看这个币
到底有没有日频数据。于是几百个只有周频历史的币(`days=30` 取不到日频、或返回空)每轮都被判成过期、每轮都重试,
把 450 个日频名额吃光 —— 真正有日频数据、该刷新的币反而排不上。有没有日频历史不用猜:覆盖视图里已经有
`count(*) n` 和 `count(*) filter (where granularity='weekly') n_weekly`,**`n - n_weekly` 就是日频行数**。
于是:有日频历史 ⇒ 按日频刷;只有周频 ⇒ 有界探测;视图里没有 `n` 列(老视图)⇒ 退回老行为,不猜。

**Beta 数据:** CoinGecko 自己说覆盖与质量还在改进 ⇒ 研究时按币做稳健处理(增长率、截尾),别把一个币的跳变当信号。
判活:`select count(distinct coin_id), max(d) from token_holders_daily`。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

TABLE = "token_holders_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "coin_id", "network", "address", "holders", "granularity", "fetched_at")}
LOOP_NAME = "_token_holders_loop"
UNIVERSE_VIEW = "cg_coin_mcap_coins"
COVERAGE_VIEW = "token_holders_coverage"

#: CoinGecko 平台 id → GeckoTerminal 网络 id(holders_chart 支持的网络,文档 11-06)。tokenized 股票链(robinhood)不收。
NETWORK = {"ethereum": "eth", "solana": "solana", "base": "base", "binance-smart-chain": "bsc", "polygon-pos": "polygon_pos",
           "arbitrum-one": "arbitrum", "optimistic-ethereum": "optimism", "avalanche": "avax", "the-open-network": "ton",
           "sui": "sui-network", "ronin": "ronin", "linea": "linea", "bittensor": "bittensor", "stable": "stable", "arc": "arc"}
MAX_BACKFILL = 120
MAX_DAILY = 450
#: 11-16:只有周频历史的币,每轮只探测这么多(按日期哈希轮换)。它们不是「该刷新的日频币」,
#: 只是在「试探这个币到底有没有日频数据」—— 试探的代价要有上限。
MAX_WEEKLY_PROBE = 30
PAUSE_S = 0.15


def home_chain(platforms: Any) -> Optional[tuple[str, str]]:
    """纯函数。CoinGecko 的平台字典(第一个键 = 本链)→ (网络, 地址);本链不支持 / 没有地址 ⇒ None。"""
    if not isinstance(platforms, dict):
        return None
    for plat, addr in platforms.items():
        if not plat:
            continue                                                       # 原生币的空键
        net = NETWORK.get(plat)
        return (net, str(addr).strip()) if net and addr and str(addr).strip() else None
    return None


def parse(payload: Any, coin_id: str, network: str, address: str, granularity: str, fetched_at: str) -> list[dict]:
    """纯函数。holders_chart → 每天一行(同一天取最后一个点);人数 ≤ 0 / 坏值丢掉。"""
    try:
        pts = payload["data"]["attributes"]["token_holders_list"]
    except (TypeError, KeyError):
        return []
    by_d: dict[str, tuple[str, int]] = {}
    for p in pts if isinstance(pts, list) else []:
        try:
            ts, n = str(p[0]), int(float(p[1]))
        except (TypeError, ValueError, IndexError):
            continue
        if n <= 0 or len(ts) < 10:
            continue
        d = ts[:10]
        if d not in by_d or ts >= by_d[d][0]:
            by_d[d] = (ts, n)
    return [{"d": d, "coin_id": coin_id, "network": network, "address": address[:120], "holders": n, "granularity": granularity,
             "fetched_at": fetched_at} for d, (_, n) in sorted(by_d.items())]


def _n_daily(cov: dict) -> Optional[int]:
    """这个币有多少行是**日频**的。覆盖视图里的 `n`(总行数)减掉 `n_weekly` 就是。
    视图没有 `n`(老视图 / 手搓的 dict)⇒ None ⇒ 调用方按老行为走,不猜。"""
    n = cov.get("n")
    nw = cov.get("n_weekly")
    if n is None or nw is None:
        return None
    try:
        return max(0, int(n) - int(nw))
    except (TypeError, ValueError):
        return None


def choose(universe: list[dict], homes: dict[str, tuple[str, str]], coverage: dict[str, dict], today: dt.date
           ) -> tuple[list[str], list[str], list[str]]:
    """纯函数。→ (要回填 days=max 的币, 要补日频 days=30 的币, 只探一 probe 的周频币)。

    回填按「币 + 日期」的哈希轮换;日频按市值大的先;周频币的探测也按日期哈希轮换(每天换一批,
    不让同几个币每轮占满额度)。视图没有 `n` 列 ⇒ 退回老行为(只看 max_d)。
    """
    cands = [u["coin_id"] for u in sorted(universe, key=lambda u: -(u.get("last_mcap") or 0)) if u["coin_id"] in homes]
    salt = today.isoformat()
    cov = coverage or {}
    need_back = sorted([c for c in cands if not (cov.get(c) or {}).get("n_weekly")],
                       key=lambda c: hashlib.sha1(f"{c}|{salt}".encode()).hexdigest())[:MAX_BACKFILL]
    daily: list[str] = []
    weekly_only: list[str] = []
    for c in cands:
        c_cov = cov.get(c) or {}
        nd = _n_daily(c_cov)
        mx = c_cov.get("max_d")
        stale = bool(mx) and (today - dt.date.fromisoformat(str(mx)[:10])).days >= 1
        if nd is None:
            if stale:                                   # 老视图:只按 max_d 判(老行为)
                daily.append(c)
        elif nd > 0:
            if stale:                                   # 有日频历史 → 按日频刷新
                daily.append(c)
        elif c_cov.get("n_weekly"):                     # 只有周频 → 不占日频名额,只做有界探测
            weekly_only.append(c)
    probe = sorted(weekly_only, key=lambda c: hashlib.sha1(f"{c}|probe|{salt}".encode()).hexdigest())[:MAX_WEEKLY_PROBE]
    return need_back, daily[:MAX_DAILY], probe


async def run_once(now: Optional[dt.datetime] = None, fetch=None, read=None, upsert=None) -> dict[str, Any]:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    real = fetch is None
    if fetch is None:
        from src.data.market.data_layer import CG_API_KEY, CG_PRO_BASE, _cg_headers, _get_cg_client
        if not CG_API_KEY:
            return {"ok": False, "refused": True, "why": "COINGECKO_API_KEY 没配"}

        async def fetch(path: str, params: dict):
            r = await _get_cg_client().get(f"{CG_PRO_BASE}{path}", headers=_cg_headers(), params=params, timeout=60)
            r.raise_for_status()
            return r.json()
    if read is None:
        from src.data.style.header import _read_all as read
    if upsert is None:
        from src.api.store import supabase_upsert_table as upsert
    coins = await fetch("/coins/list", {"include_platform": "true"})
    homes = {c["id"]: h for c in coins if isinstance(c, dict) and c.get("id") and (h := home_chain(c.get("platforms")))}
    universe = await read(UNIVERSE_VIEW, {"select": "coin_id,last_mcap"})
    try:
        cov_rows = await read(COVERAGE_VIEW, {"select": "coin_id,max_d,n,n_weekly"})
    except Exception as e:                                                   # noqa: BLE001 —— 老视图没有 n 列
        logger.warning(f"[TOKEN-HOLDERS] 覆盖视图读不到 n 列({type(e).__name__}: {e})—— 退回老行为")
        cov_rows = await read(COVERAGE_VIEW, {"select": "coin_id,max_d,n_weekly"})
    coverage = {r["coin_id"]: r for r in cov_rows}
    back, daily, probe = choose(universe, homes, coverage, now.date())
    calls, written, errors, empty = 1, 0, 0, 0
    for coin, days, gran in ([(c, "max", "weekly") for c in back]
                             + [(c, "30", "daily") for c in daily]
                             + [(c, "30", "daily") for c in probe]):
        net, addr = homes[coin]
        calls += 1
        try:
            rows = parse(await fetch(f"/onchain/networks/{net}/tokens/{addr}/holders_chart", {"days": days}), coin, net, addr, gran,
                         now.isoformat())
        except Exception:                                                 # noqa: BLE001 —— 404 = 不在覆盖里;下个币
            errors += 1
            rows = []
        if not rows:
            empty += 1
        elif not await upsert(TABLE, rows, on_conflict="d,coin_id"):
            return {"ok": False, "why": f"写 {TABLE} 失败({coin})", "calls": calls, "written": written}
        written += len(rows)
        if real:
            await asyncio.sleep(PAUSE_S)
    in_scope = sum(1 for u in universe if u["coin_id"] in homes)
    return {"ok": written > 0 or not (back or daily or probe), "calls": calls, "written": written, "backfill": len(back),
            "daily": len(daily), "probe": len(probe),
            "empty": empty, "errors": errors, "in_scope": in_scope, "backlog": len(back) >= MAX_BACKFILL,
            "why": (f"宇宙 {len(universe)} 个币,本链可查 {in_scope} · 回填 {len(back)} · 日频 {len(daily)} · "
                    f"周频探测 {len(probe)} · 写 {written} 行 · 空 {empty}")}
