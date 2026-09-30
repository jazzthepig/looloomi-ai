"""T-039 风格表头 —— 分类法。纯函数,无 I/O。

Jazz 2026-09-30:「分辨不了大币周期、二线公链、山寨币、meme 的暴露,就是表头没有做。」
风格/相位判断一直是设计的第一步(HIGH_DIM §5b-bis ⓪、DECISION_PATH_SPEC ①);缺的是这张表。

两层:
1. **基础风格**来自 CoinGecko 的分类成员关系(`/coins/markets?category=<id>`),按优先级取第一个命中:
   meme > AI > 基础设施与代币化 > DeFi > 公链(L1) > L2。
   一个币同时在「Meme」和「Layer 1」里时,决定它价格行为的是 meme 属性 —— 所以 meme 优先。
2. **档位**只切公链:当天(PIT,用 d-1 的市值)在非大币、非稳定币里市值前 N 的公链 = 头部公链,其余 = 二线公链与 L2。
   同一个币在不同年份可以属于不同档位 —— 这正是「大币周期 / 二线周期」要能分辨的东西。
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

#: 风格桶(顺序即展示顺序)。键是英文 slug,落库用;值是中文名。
STYLES: dict[str, str] = {
    "majors": "大币",
    "top_l1": "头部公链",
    "second_l1_l2": "二线公链与 L2",
    "defi": "DeFi",
    "infra_tokenization": "基础设施与代币化",
    "ai": "AI",
    "meme": "meme",
}

#: 大币不看分类,直接指定。
MAJORS = frozenset({"BTC", "ETH"})

#: CoinGecko 分类 id → 基础风格。按优先级从高到低;一个币取第一个命中。
#: id 在运行时对 `/coins/categories/list` 校验,**不存在的 id 让整轮拒绝**,不静默跳过。
#:
#: v2(09-30,首轮数据复核后):**公链排在 AI / 基础设施 / DeFi 前面。** v1 把 NEAR、ICP 归进 AI,
#: INJ、ALGO、XLM 归进基础设施 —— 它们首先是一条链,「二线公链周期」里涨跌的就是它们。
#: 例外写在 OVERRIDES 里,不改规则。
CATEGORY_PRIORITY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("meme", ("meme-token",)),
    ("l1", ("layer-1",)),
    ("ai", ("artificial-intelligence", "ai-agents")),
    ("infra_tokenization", ("oracle", "real-world-assets-rwa", "interoperability")),
    ("defi", ("decentralized-finance-defi",)),
    ("l2", ("layer-2",)),
)

#: 规则之外的判断,逐条写理由。键 = 符号,值 = 基础风格。
OVERRIDES: dict[str, str] = {
    "TAO": "ai",     # Bittensor 带 layer-1 标签,但它是 AI 板块的领头币,价格跟 AI 叙事走
}

#: 不在任何分类前 40 里、但在我们账本面板里的币:显式给出 CoinGecko id 与风格。
#: TON 在分类列表里撞名成了 Tokamak Network(一个 L2),这里指定 Toncoin。
EXTRA_MEMBERS: dict[str, tuple[str, str]] = {
    "DOT": ("polkadot", "l1"),
    "ATOM": ("cosmos", "l1"),
    "TON": ("the-open-network", "l1"),
    "POLYX": ("polymesh", "infra_tokenization"),   # 代币化篮子成员(DECISIONS 09-26)
}

#: 每个风格至少几个成员才出指数。大币只有 BTC / ETH 两个。
MIN_MEMBERS: dict[str, int] = {"majors": 2}
MIN_MEMBERS_DEFAULT = 3

#: 不进任何风格指数:它们的价格是别的东西的影子(稳定币、包装币、流动性质押凭证)。
EXCLUDE_CATEGORIES: tuple[str, ...] = ("stablecoins", "wrapped-tokens", "liquid-staking-tokens")

#: 头部公链的档位线:非大币公链里,d-1 市值排名前 N。
TOP_L1_RANK = 10


def all_category_ids() -> list[str]:
    ids = [c for _, cs in CATEGORY_PRIORITY for c in cs] + list(EXCLUDE_CATEGORIES)
    return list(dict.fromkeys(ids))


def base_style(symbol: str, categories: Iterable[str]) -> Optional[str]:
    """基础风格:'majors' / 'meme' / 'ai' / 'infra_tokenization' / 'defi' / 'l1' / 'l2' / None(排除或未归类)。"""
    s = symbol.upper()
    if s in MAJORS:
        return "majors"
    if s in OVERRIDES:
        return OVERRIDES[s]
    cats = set(categories)
    if cats & set(EXCLUDE_CATEGORIES):
        return None
    for style, ids in CATEGORY_PRIORITY:
        if cats & set(ids):
            return style
    return None


def resolve_styles(base: Mapping[str, Optional[str]], mcap_prev: Mapping[str, float],
                   top_n: int = TOP_L1_RANK) -> dict[str, str]:
    """一天的最终风格。`base` = 基础风格;`mcap_prev` = d-1 的市值(PIT)。

    公链切两档:有 d-1 市值的 l1 按市值排,前 top_n 为 top_l1,其余与 l2 一起为 second_l1_l2。
    没有 d-1 市值的币当天不归类(不猜)。
    """
    out: dict[str, str] = {}
    l1 = sorted((s for s, b in base.items() if b == "l1" and mcap_prev.get(s)),
                key=lambda s: -float(mcap_prev[s]))
    top = set(l1[:top_n])
    for s, b in base.items():
        if b is None or not mcap_prev.get(s):
            continue
        if b == "l1":
            out[s] = "top_l1" if s in top else "second_l1_l2"
        elif b == "l2":
            out[s] = "second_l1_l2"
        else:
            out[s] = b
    return out
