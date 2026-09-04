"""企业/主权持币的**决策流**采集 —— 用我们已经付钱的那档 (S-291).

## 这条被失忆了很多次

Jazz 2026-09-04:「我们有 coingecko analyst api 是 139 刀一个月的。。。
你又把他忽略了?这件事已经被失忆了很多次。」

**他是对的。** 时间线:

    S-264   我自己写下 `PAID_ENTITLEMENTS`,含 14 项 analyst_only 能力,
            并为 public_treasury 写了理由:「MicroStrategy 买 BTC 是一个
            有主体、有时点、有金额的企业决策,不需要我们推断」
    此后     **那四项 Entity 能力零调用**
    S-290   我用**免费**端点建了快照层,并写下「历史买不来,今天开始攒」
    S-291   实测:付费档直接给到 2020-08-11。**那句话对免费档成立,
            对我们付的这档不成立。**

而我判定「不可用」的依据是一次 **HTTP 403** —— 那是 **Cloudflare 1010
客户端指纹拦截**(裸 urllib),不是权限。换成代码库同款 httpx 立刻 200:

    plan=Analyst · 月额度 500,000 · 本月剩余 482,574

> **「我探测失败」和「我们没有这个能力」是两个状态。**
> 本周第 N 次同一个形状,而这次的代价是几个月的订阅费买的东西没被用。

**防复发不靠这段话,靠 `tests/test_paid_capability_is_used.py`** ——
一份没有任何调用点的付费能力清单,会被守卫判为失败。

## 付费档解锁的正是关键那一段

    page=1   100 条   2026-08-31 → 2022-01-31
    page=2    19 条   2021-12-30 → **2020-08-11**   ← Analyst 独占
    page=3     0 条

Strategy 的完整决策史 119 条,回到 MicroStrategy 买入第一笔 BTC 那天。

## entity_id 推导不出来,所以**解析必须是三值的**

`microstrategy` → 404;`strategy` → 200(公司改名了)。
朴素 slug 命中率:

    按家数   55%
    **按持仓  88.4%**   ← 对我们要的东西,这个才是对的口径

一家持 12 枚而解析不出的公司不重要,Strategy 的 845,050 枚重要。
**两个口径必须一起报** —— 只报家数会让人以为覆盖很差,
只报持仓会让人以为已经全覆盖。

未解析的实体**显式列出**,不静默丢弃(本周反复的那条)。
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

CG_PRO_BASE = "https://pro-api.coingecko.com/api/v3"

#: 每个实体最多翻多少页。护栏,不是预期 —— Strategy 是 2 页,
#: 走满更可能是分页逻辑坏了。
MAX_PAGES = 12

#: 一页的条数(CG 返回 100)。用于判断「还有下一页」。
PAGE_SIZE = 100

RESOLVED, UNRESOLVED, CONFLICT = "resolved", "unresolved", "conflict"

#: 解析来源。**猜出来的和查出来的必须可分。**
FROM_SLUG, FROM_TICKER, FROM_MANUAL, FROM_API = "slug", "ticker", "manual", "api"

#: 手工修正表 —— 改名 / 无法从名字推导的。**每条都是一次实测,不是猜。**
#: 加一条 = 改这里 + 台账,与 `_ALLOWED_WRITERS` 同样的摩擦。
MANUAL_IDS: dict[str, str] = {
    "MicroStrategy": "strategy",          # 2026 改名 Strategy
    "Twenty One Capital": "xxi.us",       # 实测:ticker.exchange 形式
}

_SUFFIX = re.compile(
    r"-(inc|corp|corporation|ltd|limited|plc|holdings|co|group|ag|sa|nv)$")


def slugify(name: str) -> str:
    """公司名 → 候选 id。**这是猜,不是查** —— 所以结果要带 `resolved_from`。"""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return _SUFFIX.sub("", s)


def candidates(name: str, symbol: Optional[str] = None) -> list:
    """一个公司的所有候选 id,按可信度排序。**手工表最先** —— 它是实测过的。"""
    out = []
    if name in MANUAL_IDS:
        out.append((MANUAL_IDS[name], FROM_MANUAL))
    s = slugify(name)
    if s:
        out.append((s, FROM_SLUG))
    sym = (symbol or "").lower().strip()
    for t in (sym, sym.split(":")[-1]):
        if t and t not in {c for c, _ in out}:
            out.append((t, FROM_TICKER))
    seen, uniq = set(), []
    for cid, src in out:
        if cid not in seen:
            seen.add(cid)
            uniq.append((cid, src))
    return uniq


@dataclass(frozen=True)
class Resolution:
    """一个公司名的 id 解析结果。**三值,不是有/无。**"""
    name: str
    entity_id: Optional[str]
    resolved_from: Optional[str]
    verdict: str
    holdings: float = 0.0
    tried: tuple = ()
    reason: str = ""


@dataclass(frozen=True)
class Decision:
    """一次有凭证的持仓决策。**source_url 是它比 VC 新闻稿强的地方。**"""
    entity_id: str
    coin_id: str
    decision_date: str
    decision_type: str
    holding_net_change: Optional[float]
    transaction_value_usd: Optional[float]
    holding_balance: Optional[float]
    avg_entry_value_usd: Optional[float]
    source_url: Optional[str]


def _num(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _date(ms) -> Optional[str]:
    n = _num(ms)
    if n is None:
        return None
    try:
        return dt.datetime.utcfromtimestamp(n / 1000).date().isoformat()
    except Exception:                                          # noqa: BLE001
        return None


def parse_decisions(entity_id: str, payload: dict) -> list:
    """`transaction_history` 响应 → `Decision` 列表。

    **`type` 原样保留(buy/sell)** —— 不做任何归一或推断。
    一笔 `holding_net_change` 为负而 type 是 buy 的记录,是上游的事实,
    我们记下来,不替它决定哪个对。
    """
    out = []
    for t in (payload or {}).get("transactions") or []:
        d = _date(t.get("date"))
        if not d:
            continue
        out.append(Decision(
            entity_id=entity_id,
            coin_id=str(t.get("coin_id") or ""),
            decision_date=d,
            decision_type=str(t.get("type") or "unknown"),
            holding_net_change=_num(t.get("holding_net_change")),
            transaction_value_usd=_num(t.get("transaction_value_usd")),
            holding_balance=_num(t.get("holding_balance")),
            avg_entry_value_usd=_num(t.get("average_entry_value_usd")),
            source_url=t.get("source_url") or None,
        ))
    return out


def resolve_all(companies: Sequence[dict], probe: Callable) -> dict:
    """公司列表 → 解析结果 + **两个口径的覆盖率**。

    `probe(entity_id) -> bool` 由调用方注入(注入是为了这层能离线测试,
    不是为了优雅)。

    **两个覆盖率必须一起报:** 只报家数会让人以为覆盖很差(55%),
    只报持仓会让人以为已经全覆盖(88.4%)。它们回答不同的问题。
    """
    rows, resolved = [], []
    for co in companies or []:
        name = str(co.get("name") or "").strip()
        if not name:
            continue
        h = _num(co.get("total_holdings")) or 0.0
        tried = candidates(name, co.get("symbol"))
        hit = None
        for cid, src in tried:
            if probe(cid):
                hit = (cid, src)
                break
        if hit:
            r = Resolution(name, hit[0], hit[1], RESOLVED, h,
                           tuple(c for c, _ in tried),
                           f"命中 '{hit[0]}'(来源 {hit[1]})")
            resolved.append(r)
        else:
            r = Resolution(name, None, None, UNRESOLVED, h,
                           tuple(c for c, _ in tried),
                           f"{len(tried)} 个候选全部 404 —— **未解析 ≠ 没有数据**,"
                           f"这家公司的决策史存在,只是我们没找到它的 id")
        rows.append(r)

    n = len(rows)
    tot_h = sum(r.holdings for r in rows) or 1.0
    got_h = sum(r.holdings for r in resolved)
    return {
        "n_total": n,
        "n_resolved": len(resolved),
        "coverage_by_count": round(len(resolved) / n, 4) if n else 0.0,
        # **这个才是对我们要的东西正确的口径。**
        "coverage_by_holdings": round(got_h / tot_h, 4),
        "resolved": [r for r in rows if r.verdict == RESOLVED],
        # **显式列出,不静默丢弃。**
        "unresolved": [{"name": r.name, "holdings": r.holdings,
                        "tried": list(r.tried)}
                       for r in rows if r.verdict == UNRESOLVED],
        "reason": (
            f"{len(resolved)}/{n} 家解析出 id(**按家数 "
            f"{len(resolved)/n if n else 0:.0%}、按持仓 {got_h/tot_h:.1%}**)。"
            f"两个口径一起报 —— 只看家数会以为覆盖很差,只看持仓会以为已全覆盖;"
            f"未解析的 {n - len(resolved)} 家已显式列出,**不是没有数据,"
            f"是我们没找到它的 id**"),
    }


async def fetch_decisions(entity_id: str, get, *, max_pages: int = MAX_PAGES
                          ) -> dict:
    """翻完一个实体的全部交易页。**page>1 是 Analyst 独占的那一段。**

    `get(path, params) -> (status, json)` 由调用方注入。
    停止条件是**短页**(< PAGE_SIZE)或空页,不是页数 —— 与 S-269 同一条:
    以固定页数为界会把长历史静默截断。
    """
    all_rows, pages, note = [], 0, ""
    for pg in range(1, max_pages + 1):
        status, body = await get(
            f"/public_treasury/{entity_id}/transaction_history", {"page": pg})
        pages = pg
        if status != 200:
            note = (f"page={pg} HTTP {status} —— **读不到 ≠ 没有**;"
                    f"已拿到的 {len(all_rows)} 条不丢")
            break
        batch = parse_decisions(entity_id, body)
        all_rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    else:
        note = (f"走满 {max_pages} 页仍未见短页 —— **更可能是分页逻辑坏了**,"
                f"不静默截断")
    dates = sorted(r.decision_date for r in all_rows if r.decision_date)
    return {
        "entity_id": entity_id,
        "n": len(all_rows),
        "pages_fetched": pages,
        "earliest": dates[0] if dates else None,
        "latest": dates[-1] if dates else None,
        "decisions": all_rows,
        "note": note,
    }


def rows_for_supabase(decisions: Sequence[Decision]) -> list:
    """→ `treasury_decisions` 的行。主键含 `holding_net_change`,
    因为同一天同一方向可能有多笔(不同披露)。"""
    return [{
        "entity_id": d.entity_id, "coin_id": d.coin_id,
        "decision_date": d.decision_date, "decision_type": d.decision_type,
        "holding_net_change": d.holding_net_change,
        "transaction_value_usd": d.transaction_value_usd,
        "holding_balance": d.holding_balance,
        "avg_entry_value_usd": d.avg_entry_value_usd,
        "source_url": d.source_url, "source": "coingecko_analyst",
    } for d in decisions if d.decision_date and d.holding_net_change is not None]
