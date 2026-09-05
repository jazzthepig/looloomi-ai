"""symbol → CoinGecko coin_id 的解析 —— **24 条取数路径的根** (S-303).

## 这一条是整个 Sense 段发散的单一根因

2026-09-05 顺着链条查下去:

    唯一 trusted 且能保持新鲜的 crypto 源  =  coingecko_pro_ohlc
      ↑ 由 cg_pro_backfill 写(S-258 已建好)
        ↑ 只有一个手动 API 路由触发,**没有任何循环**
          ↑ 所以表里 0 行(它自己的 docstring 第 11 行就写着「一行都没有」)
            ↑ 所以账本从库里读不到可信价格
              ↑ 所以 24 个模块各自出去打外网

而 `backfill()` 要的是 `[(symbol, coin_id)]` 对,**全仓没有这张对照表**,
`/coins/list`(一次调用给全部 ~17,000 条)**调用点为零**。

所以我之前当成三件事的「面板 237 个标的无源」「接 CG Analyst」「Sense 收敛」,
**是同一个动作**。

## 先花零成本的那部分

`trending_log` 里已经有 258 组 (symbol, coingecko_id),是 trending 采集的副产品。
与 262 个面板标的取交集:**57 个已经免费有了**,206 个要解析。
先用库里的,不够的才打 API —— 与 S-292 的实体解析同一条纪律。

## ⚠️ symbol 撞名是这里唯一会毁掉数据的错

CoinGecko 有 ~17,000 个币,**ticker 不唯一**:山寨盘、分叉币、纯骗子合约
会占用同一个 symbol。选错一个,就是**把另一个币的整段价格历史写进这个标的**,
而画出来的曲线完全正常 —— 这正是 S-258 写 `check_mapping` 的理由。

所以解析是**三值的,而且永不静默取第一个**:

    resolved    symbol 在 listing 里唯一,或市值裁决后又通过了收盘价校验
    ambiguous   多个候选 —— **带着全部候选返回,不猜**
    unresolved  一个候选都没有

`resolved_from` 必须记下来,因为「查出来的」和「按市值猜的」是两个可信度,
而它们在 `coin_id` 这一列上完全同形 —— 本周反复的那个形状。

## 市值裁决是启发式,不是真相

同 symbol 的多个币里取市值最大的,绝大多数时候对。**但它是猜。**
所以它必须:① 标记 `MCAP_TIEBREAK`;② 之后仍要过 S-258 的收盘价校验;
③ 校验不过 → `ambiguous`,不写。

**一个没有被价格校验过的市值裁决,不允许进 `ohlcv_daily`。**
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

CG_PRO_BASE = "https://pro-api.coingecko.com/api/v3"

RESOLVED, AMBIGUOUS, UNRESOLVED = "resolved", "ambiguous", "unresolved"

#: 解析来源。**「查出来的」和「猜出来的」必须可分。**
FROM_DB = "free_db"          # trending_log 里已有,零成本
FROM_UNIQUE = "list_unique"  # /coins/list 里该 symbol 唯一 —— 最可信
FROM_MCAP = "mcap_tiebreak"  # 撞名,按市值裁决 —— **是猜,必须再过价格校验**


@dataclass(frozen=True)
class CoinMatch:
    symbol: str
    coin_id: Optional[str]
    resolved_from: Optional[str]
    verdict: str
    candidates: tuple = ()
    reason: str = ""

    @property
    def needs_price_check(self) -> bool:
        """市值裁决出来的,**在写库前必须过 S-258 的收盘价校验**。"""
        return self.resolved_from == FROM_MCAP


def index_listing(listing: Iterable[dict]) -> dict[str, list[str]]:
    """`/coins/list` 的响应 → `{SYMBOL: [coin_id, ...]}`。

    **不做去重取一个** —— 撞名本身是要被上层看见的信息。
    """
    out: dict[str, list[str]] = {}
    for c in listing or []:
        sym = str((c or {}).get("symbol") or "").strip().upper()
        cid = str((c or {}).get("id") or "").strip()
        if sym and cid:
            out.setdefault(sym, []).append(cid)
    return out


def resolve(symbols: Sequence[str], *,
            known: Optional[dict[str, str]] = None,
            listing_index: Optional[dict[str, list[str]]] = None,
            mcap: Optional[dict[str, float]] = None) -> dict[str, Any]:
    """解析一批 symbol。**纯函数** —— 注入是为了这层能离线测。

    `known`          库里已有的(trending_log),零成本,最先用
    `listing_index`  `/coins/list` 的索引
    `mcap`           `{coin_id: market_cap}`,用于撞名裁决;**缺了就判 ambiguous**

    ⚠️ `mcap` 缺失时**不退化成取第一个**。取第一个会让一个骗子合约
    静默地成为我们某个标的的价格来源,而曲线看起来完全正常。
    """
    known = {k.upper(): v for k, v in (known or {}).items()}
    idx = listing_index or {}
    mcap = mcap or {}
    rows: list[CoinMatch] = []

    for raw in symbols:
        s = str(raw or "").strip().upper()
        if not s:
            continue
        if s in known:
            rows.append(CoinMatch(s, known[s], FROM_DB, RESOLVED,
                                  reason="库里已有(trending_log 副产品),零成本"))
            continue
        cands = list(idx.get(s) or [])
        if not cands:
            rows.append(CoinMatch(s, None, None, UNRESOLVED, (),
                                  "listing 里没有这个 symbol —— **未解析 ≠ 没有数据**,"
                                  "可能是 CG 用了别的 ticker"))
        elif len(cands) == 1:
            rows.append(CoinMatch(s, cands[0], FROM_UNIQUE, RESOLVED, tuple(cands),
                                  "listing 里唯一,最可信"))
        else:
            scored = [(mcap.get(c), c) for c in cands]
            have = [(m, c) for m, c in scored if m is not None]
            if not have:
                rows.append(CoinMatch(
                    s, None, None, AMBIGUOUS, tuple(cands),
                    f"{len(cands)} 个同 symbol 候选且**一个都没有市值** —— "
                    f"不猜。取第一个会让一个骗子合约静默成为这个标的的价格源"))
            else:
                have.sort(reverse=True)
                rows.append(CoinMatch(
                    s, have[0][1], FROM_MCAP, RESOLVED, tuple(cands),
                    f"{len(cands)} 个候选,按市值裁决取 '{have[0][1]}' —— "
                    f"**这是猜,写库前必须过 S-258 的收盘价校验**"))

    n = len(rows)
    res = [r for r in rows if r.verdict == RESOLVED]
    guessed = [r for r in res if r.needs_price_check]
    return {
        "n_total": n,
        "n_resolved": len(res),
        "n_from_db": sum(1 for r in res if r.resolved_from == FROM_DB),
        "n_unique": sum(1 for r in res if r.resolved_from == FROM_UNIQUE),
        # **单列** —— 这些还没有被证明是对的。
        "n_mcap_tiebreak_unverified": len(guessed),
        "resolved": res,
        "needs_price_check": guessed,
        # **理由一起带出来** —— 一个只说「未决」不说为什么的条目,
        # 下一个人只能重新调查一遍,而调查结果本来就在这一行产生过。
        "ambiguous": [{"symbol": r.symbol, "candidates": list(r.candidates),
                       "reason": r.reason}
                      for r in rows if r.verdict == AMBIGUOUS],
        "unresolved": [r.symbol for r in rows if r.verdict == UNRESOLVED],
        "reason": (
            f"{len(res)}/{n} 解析出 coin_id"
            f"(库里已有 {sum(1 for r in res if r.resolved_from == FROM_DB)} · "
            f"listing 唯一 {sum(1 for r in res if r.resolved_from == FROM_UNIQUE)} · "
            f"**市值裁决 {len(guessed)},未经价格校验**)。"
            f"撞名未决 {sum(1 for r in rows if r.verdict == AMBIGUOUS)} 个、"
            f"未解析 {sum(1 for r in rows if r.verdict == UNRESOLVED)} 个,"
            f"**全部显式列出,不静默丢弃**"),
    }


def pairs_for_backfill(res: dict, *, include_unverified: bool = False
                       ) -> list[tuple[str, str]]:
    """→ `cg_pro_backfill.backfill()` 要的 `[(symbol, coin_id)]`。

    **默认排除市值裁决的那些** —— 它们还没过收盘价校验,而一个错的 coin_id
    会把另一个币的整段历史写进这个标的。要包含就显式说,别让默认值替你决定。
    """
    out = [(r.symbol, r.coin_id) for r in res.get("resolved", [])
           if r.coin_id and (include_unverified or not r.needs_price_check)]
    return out
