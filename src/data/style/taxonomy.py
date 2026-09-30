"""T-039 风格表头 —— 分类法。纯函数,无 I/O。

Jazz 2026-09-30:「分辨不了大币周期、二线公链、山寨币、meme 的暴露,就是表头没有做。」
Jazz 2026-09-30(v3):「公链和分类不冲突啊。NEAR 也是区块链里面 AI 最重要的。」

**所以风格是两个正交的维度,不是一个桶:**

1. **层级(tier)—— 每个币恰好一个:** 大币 / 头部公链 / 二线公链与 L2 / 应用币(不是链的代币)。
   公链的头部 / 二线按当天(PIT,用 d-1 市值)在非大币公链里的市值排名切,同一个币不同年份可以换档。
2. **板块(sector)—— 每个币零个或多个:** AI / meme / DeFi / 基础设施与代币化。
   NEAR 同时是「头部或二线公链」和「AI」;TAO 同时是公链和 AI;INJ 同时是公链、DeFi、代币化。
   一个币进它所属的**每一个**板块指数,不再用优先级把它塞进唯一一格 —— 那样做就是二值化。

v1/v2 用「优先级取第一个」给每个币一个风格,NEAR 要么进 AI 要么进公链,两种都丢了一半事实。
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

#: 层级维度(每个币一个)
TIERS: dict[str, str] = {
    "majors": "大币",
    "top_l1": "头部公链",
    "second_l1_l2": "二线公链与 L2",
    "app": "应用币",
}

#: 板块维度(每个币零个或多个)
SECTORS: dict[str, str] = {
    "ai": "AI",
    "meme": "meme",
    "defi": "DeFi",
    "infra_tokenization": "基础设施与代币化",
}

#: 全部指数名 → 中文;两个维度的名字互不重复,所以可以共用一张指数表。
STYLES: dict[str, str] = {**TIERS, **SECTORS}
DIMENSION: dict[str, str] = {**{k: "tier" for k in TIERS}, **{k: "sector" for k in SECTORS}}

#: 大币不看分类,直接指定。
MAJORS = frozenset({"BTC", "ETH"})

#: 层级来自这两个分类;都不在 ⇒ 应用币。
CHAIN_CATEGORIES: dict[str, tuple[str, ...]] = {
    "l1": ("layer-1",),
    "l2": ("layer-2",),
}

#: 板块来自这些分类(多标签)。id 在运行时对 `/coins/categories/list` 校验,不存在即整轮拒绝。
SECTOR_CATEGORIES: dict[str, tuple[str, ...]] = {
    "ai": ("artificial-intelligence", "ai-agents"),
    "meme": ("meme-token",),
    "defi": ("decentralized-finance-defi",),
    "infra_tokenization": ("oracle", "real-world-assets-rwa", "interoperability"),
}

#: 不进任何指数:它们的价格是别的东西的影子(稳定币、包装币、流动性质押凭证)。
EXCLUDE_CATEGORIES: tuple[str, ...] = ("stablecoins", "wrapped-tokens", "liquid-staking-tokens")

#: 不在任何分类前 40 里、但在我们账本面板里的币:显式给出 CoinGecko id 与分类。
#: TON 在分类列表里撞名成了 Tokamak Network(一个 L2),这里指定 Toncoin。
EXTRA_MEMBERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "DOT": ("polkadot", ("layer-1", "interoperability")),
    "ATOM": ("cosmos", ("layer-1", "interoperability")),
    "TON": ("the-open-network", ("layer-1",)),
    "POLYX": ("polymesh", ("layer-1", "real-world-assets-rwa")),   # 代币化篮子成员(DECISIONS 09-26)
}

#: 每个指数至少几个成员才出一行。大币只有 BTC / ETH 两个。
MIN_MEMBERS: dict[str, int] = {"majors": 2}
MIN_MEMBERS_DEFAULT = 3

#: 头部公链的档位线:非大币公链里,d-1 市值排名前 N。
TOP_L1_RANK = 10


def all_category_ids() -> list[str]:
    ids = ([c for cs in CHAIN_CATEGORIES.values() for c in cs]
           + [c for cs in SECTOR_CATEGORIES.values() for c in cs] + list(EXCLUDE_CATEGORIES))
    return list(dict.fromkeys(ids))


def classify(symbol: str, categories: Iterable[str]) -> Optional[tuple[str, frozenset[str]]]:
    """→ (层级基础, 板块集合);层级基础 ∈ {'majors','l1','l2','app'}。被排除的返回 None。"""
    s = symbol.upper()
    cats = set(categories)
    if s not in MAJORS and cats & set(EXCLUDE_CATEGORIES):
        return None
    sectors = frozenset(k for k, ids in SECTOR_CATEGORIES.items() if cats & set(ids))
    if s in MAJORS:
        return "majors", sectors
    if cats & set(CHAIN_CATEGORIES["l1"]):
        return "l1", sectors
    if cats & set(CHAIN_CATEGORIES["l2"]):
        return "l2", sectors
    return "app", sectors


def resolve_tiers(tier_base: Mapping[str, str], mcap_prev: Mapping[str, float],
                  top_n: int = TOP_L1_RANK) -> dict[str, str]:
    """一天的层级。`tier_base` = classify 的第一项;`mcap_prev` = d-1 市值(PIT)。
    l1 按 d-1 市值排,前 top_n 为 top_l1,其余与 l2 一起为 second_l1_l2。没有 d-1 市值的币当天不归类(不猜)。
    """
    l1 = sorted((s for s, b in tier_base.items() if b == "l1" and mcap_prev.get(s)),
                key=lambda s: -float(mcap_prev[s]))
    top = set(l1[:top_n])
    out: dict[str, str] = {}
    for s, b in tier_base.items():
        if not mcap_prev.get(s):
            continue
        out[s] = {"l1": "top_l1" if s in top else "second_l1_l2", "l2": "second_l1_l2"}.get(b, b)
    return out


def members_by_index(tier_base: Mapping[str, str], sectors: Mapping[str, frozenset],
                     mcap_prev: Mapping[str, float]) -> dict[str, list[str]]:
    """一天里每个指数的成员。层级:每币一个;板块:每币可以在多个里。"""
    tiers = resolve_tiers(tier_base, mcap_prev)
    out: dict[str, list[str]] = {k: [] for k in STYLES}
    for s, t in tiers.items():
        out[t].append(s)
        for sec in sectors.get(s, ()):
            out[sec].append(s)
    return out
