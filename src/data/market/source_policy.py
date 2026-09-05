"""Which source may be fanned out over many assets, and which may not (S-205).

Jazz, 2026-08-23: **不可以那么依赖任何免费 api,大量多资产会被封啊。多并发高需求量
的我们要以 pro 的 coingecko 为主要来源。**

He had said this before. I did it twice anyway, in one week:

  · `deep_panel_collector` — 262 symbols against Binance's free mirror. Result:
    one symbol reachable, panel dead for days (S-190).
  · `hyperliquid_collector` — 232 symbols against a free public DEX endpoint at
    ~53 req/s. Result: HTTP 429 on 57 symbols INCLUDING BTC, coverage 56%, the
    write refused for two days (S-204).

Both times I "fixed" the symptom — a floor that blocks, a gentler pace. Neither
fix addressed the actual rule, which is that **a paid API is what you fan out
over, and a free one is what you ask a single question of.** A reminder that has
been given and violated twice is not a reminder any more; it needs to be a
constraint that fails a build.

THE RULE

    fan-out over > BULK_THRESHOLD assets   →  a PAID source. Always.
    a free/public endpoint                 →  one call, or a handful

WHAT THIS CHANGED IN PRACTICE, and it is embarrassing in the useful direction:
Hyperliquid's `metaAndAssetCtxs` returns markPx, oraclePx, funding, openInterest
and day volume for **all 232 perps in ONE request**. I was issuing 232 separate
`candleSnapshot` calls to obtain closing prices that were already sitting in that
single response. The rate limit was not a wall I had to pace myself against — it
was the venue telling me I was asking the wrong question.

THE SPLIT

    CoinGecko Pro   bulk daily bars, market caps, dominance, categories,
                    trending, breadth across ~17,000 assets. We pay monthly for
                    exactly this and were using the free-shaped endpoints (S-195).
                    `/coins/markets` alone returns 250 assets per call.

    Hyperliquid     what only the venue knows and what it gives cheaply:
                    funding rates, oracle vs mark, open interest, the tradeable
                    listing. ONE `metaAndAssetCtxs` call covers every perp.
                    Per-symbol candle pulls are a last resort, not a default.

    EODHD           TradFi bars. Paid, already the primary there.

This is not "free sources are bad". It is that free sources price bulk access at
a rate limit, and a rate limit paid in outages is more expensive than the
subscription we already hold.
"""
from __future__ import annotations

#: Above this many assets in one job, a paid source is mandatory. Six is small
#: on purpose — the two incidents were 262 and 232, and any honest bulk job is
#: far above this, so the threshold never needs judgement at a call site.
BULK_THRESHOLD = 6

#: Sources we pay for. Their rate limits are contractual and generous.
PAID_SOURCES = frozenset({"coingecko_pro", "eodhd"})

# ── S-296 (2026-09-05): 用途轴 —— 数量守卫拦不住的那一半 ────────────────────
#
# Jazz:**「我们实时数据和前端应该优先走 coingecko 的付费 api,
# 是接入交易生产的才读 hyperliquid。」**
#
# S-205 的守卫只问「几个资产」。它拦住了 233 个标的的蜡烛扇出 —— 拦对了,
# 而且从 2026-08-23 起一直在拦。**但拦住之后没有人接手**:hyperliquid 的
# 日线停在 08-23,CG Pro 那边只接了 25 个标的,面板 262 个里有 237 个
# 从那天起没有任何日线来源。
#
# > **一个只拦不导的守卫,会把违规变成缺口。** 数量守卫说「别在这里取」,
# > 它没说「去哪里取」,于是两周里没有人去取。
#
# 用途轴补的就是这一句。它不是「HL 是坏源」——
#
#     market_data  面板、前端、研究、回测的价格与历史
#                  → 付费源(CG Pro / EODHD)。可以 fan-out,我们为此付钱。
#
#     execution    只有场馆自己知道的:资金费、oracle vs mark、未平仓、挂牌
#                  → Hyperliquid。**但资产集是「我们真会在那里下单的」,
#                    不是「那里挂了什么」。**
#
# 最后那句是这条规则的全部重量。HL 挂了 233 个永续;那是**场馆的库存**,
# 不是我们的成交集。把「挂牌」当成「要交易」,就是本周反复的那个形状 ——
# 两个不同的状态塌进一个表示 —— 而它塌出来的结果,正好是 S-204 那次
# 233 个标的的扇出。
MARKET_DATA, EXECUTION = "market_data", "execution"

#: 每个用途的主源。**这是路由表,不是偏好。**
PURPOSE_PRIMARY: dict[str, str] = {
    MARKET_DATA: "coingecko_pro",
    EXECUTION: "hyperliquid",
}

#: 每个用途允许的**资产集口径**,写成人话是为了让违规在 code review 时就刺眼。
PURPOSE_SCOPE: dict[str, str] = {
    MARKET_DATA: "整个研究面板(262)—— 付费源,fan-out 是买来的权利",
    EXECUTION: "**我们真会下单的标的**,不是场馆挂牌的全部。今天这个集合是空的"
               "(① 还是纸面),所以任何 execution 扇出都必须显式传入名单",
}

#: 我们买到了什么,以及用掉了多少 (S-264, 2026-09-01 实测)。
#:
#: **为什么这必须是代码而不是记忆。** 2026-09-01 我告诉 Jazz「我们测不了流,
#: 没有任何持久化的流量序列」。他的回答是「coingecko pro 应该是有的」,
#: 然后:「这点已经说过好多次了,我买了 139 刀每月的 pro api」。
#:
#: 他是对的,而且这件事**本来就写在这个文件里** —— 上面那段 S-205 的正文
#: 明写着 CoinGecko Pro 给 "market caps, dominance, categories, trending,
#: breadth across ~17,000 assets. We pay monthly for exactly this and were
#: using the free-shaped endpoints"。我没读自己 lane 里的这个模块就断言了缺失。
#:
#: 这跟 2026-08-19 那次是同一个动作:**在说「我们没有 X」之前没有 grep**。
#: CLAUDE.md 为那次加了一整段警告。一年里第二次,所以这次不写成警告 ——
#: 写成一个可以被查询、且被测试盯住的表。
#:
#: 最刺眼的一个数:**额度用了 0.4%。** 我整个 session 都在为 Supabase 免费版
#: 的 500MB 做取舍(S-261 把回填改成本地优先),而旁边这个付费额度几乎全新。
#: 一个被珍惜的免费额度和一个被闲置的付费额度同时存在,说明约束被找错了地方。
PAID_ENTITLEMENTS: dict[str, dict] = {
    "coingecko_pro": {
        "plan": "Analyst",                    # $103.2/月(年付)· $139 月付
        "monthly_call_credit": 500_000,
        "rate_limit_per_min": 500,
        "websockets": 10,
        "webhooks": 5,
        "data_freshness": "real-time",
        "measured_on": "2026-09-01",
        "calls_used_at_measurement": 2_074,   # = 0.4%
        # Analyst 解锁文档里标 💼 的全部端点;只差 👑 Enterprise。
        "unlocks_analyst_tier": True,
        "verify": "GET /api/v3/key → {plan, monthly_call_credit, "
                  "current_remaining_monthly_calls}",
        # ── Analyst 档独有、Basic 没有的能力(2026-09-01 从定价表核过)──────
        # Jazz:「现在我们缺的 infra 其实 139 这个 plan 都有,整起来吧。
        #        我觉得不要降级,降级之后我不敢做营销的。」
        # 记在这里的作用不是清单,是**让「我们缺 X」这句话在说出口之前先被检查一次**
        # —— S-264 就是因为这句话说错过两次才存在的。
        "analyst_only": {
            "/coins/{id}/ohlc/range": "自定义区间 OHLC —— **已接**(S-258 深盘回填)",
            "coin_history_depth": "日线 from 2013 / 小时线 from 2018(Basic 只给 2 年)"
                                  " —— 这是深盘面板的真正解药:binance_hist 死了、"
                                  "market_state_writer 只拿到 343 天,而这里有 4000+ 天",
            "/global/market_cap_chart": "历史全局市值 + 成交量 ⇒ **BTC 主导率的轨迹**。"
                                        "⓪ 层(流动性周期判断)要的正是轨迹不是当前值",
            "/coins/top_gainers_losers": "涨跌幅榜,横截面极值",
            "/coins/list/new": "新上币 —— 叙事萌芽的最早观测点",
            "/exchanges/{id}/volume_chart/range": "场所成交量历史区间 ⇒ "
                                                  "「场所 infra 被买」的成交量对照",
            "/onchain/.../tokens/{addr}/trades": "**成交分类的原料**(散户/机构/TWAP)",
            "/onchain/.../tokens/{addr}/top_holders": "持有人结构 —— Entity 层的直接观测",
            "/onchain/.../tokens/{addr}/holders_chart": "持有人历史 ⇒ 谁在进谁在出",
            "/onchain/.../top_traders": "谁在交易,不只是交易了多少",
            "/onchain/pools/megafilter": "跨链池筛选,一次调用",
            "onchain_ohlcv_depth": "池/代币 OHLCV from 2021(Basic 只给 6 个月)",
            "public_treasury_history": "上市公司持币历史 from 2020 —— "
                                       "**这是 Entity/Decision 层最干净的样本**:"
                                       "MicroStrategy 买 BTC 是一个有主体、有时点、"
                                       "有金额的企业决策,不需要我们推断",
            "websocket": "10 路实时流 —— 可替代轮询",
        },
        # ⚠️ 全部档位都【没有】的:历史流通量/总供应量(Coin Historical
        # Circulating & Total Supply 三档全 ✗)。所以加密侧的「渗透率分母」
        # 不能指望 CG;代币化 RWA 那侧的分母走 EODHD fundamentals(S-267)。
        "not_available_any_tier": ["coin_historical_circulating_supply",
                                   "coin_historical_total_supply"],
    },
}


def utilisation(source: str) -> float | None:
    """已用额度占比。`None` = 没量过 —— **不等于 0,也不等于健康**(S-246)。"""
    e = PAID_ENTITLEMENTS.get(source)
    if not e or not e.get("monthly_call_credit"):
        return None
    return e["calls_used_at_measurement"] / e["monthly_call_credit"]

#: Free/public. Fine for a single question, never for a fan-out.
FREE_SOURCES = frozenset({"hyperliquid", "binance", "binance_vision",
                          "yfinance", "alternative_me", "defillama"})

#: Endpoints that answer for MANY assets in ONE request. Reaching for a
#: per-symbol loop when one of these exists is the actual error — pacing the
#: loop only makes the wrong approach survivable.
BULK_ENDPOINTS = {
    "coingecko_pro": {
        "/coins/markets": "250 assets/call — price, mcap, volume, %change",
        "/global": "total mcap, BTC dominance, one call",
        "/coins/categories": "sector breadth 叙事层,一次调用 — 每个分类的市值+成交量",
        # ── 以下四条 2026-09-01 补入。它们一直存在于 Analyst 档,我们一次没调过。
        "/rwas/markets": (
            "所有代币化 RWA 的价格/市值/成交量,一次调用。**这是流本身,不是倒影** —— "
            "市值序列即该代币化资产的 AUM"),
        "/rwas/issuers/list": "RWA 发行方全表,一次调用",
        "/global/market_cap_chart": "💼 历史全局市值 + 成交量(Analyst 档已含)",
        "/exchanges/{id}/volume_chart": "场所成交量历史 — 检验「场所 infra 被买」的直接读数",
    },
    "hyperliquid": {
        "/info metaAndAssetCtxs": (
            "ALL perps in one call: markPx, oraclePx, funding, openInterest, "
            "dayNtlVlm. Measured 2026-08-23: 232 symbols, one request. The "
            "232-request candleSnapshot loop it replaces is what earned the 429s."),
        "/info meta": "the tradeable listing, one call",
    },
}


class SourcePolicyError(RuntimeError):
    """A bulk job pointed at a free source. Raised, not warned.

    A warning here would be logged and ignored exactly like the two print
    statements that hid S-190 and S-204 for days apiece.
    """


def assert_bulk_source(n_assets: int, source: str, *, job: str) -> None:
    """Gate a fan-out. Call it where the job decides its source, not later.

    >>> assert_bulk_source(232, "hyperliquid", job="daily bars")
    Traceback (most recent call last):
    SourcePolicyError: ...
    """
    if n_assets <= BULK_THRESHOLD:
        return
    if source in PAID_SOURCES:
        return
    hint = ""
    if source in BULK_ENDPOINTS:
        eps = "; ".join(f"{k} ({v.split('—')[0].strip()})"
                        for k, v in BULK_ENDPOINTS[source].items())
        hint = (f" If {source} genuinely has what you need, it very likely has a "
                f"BULK endpoint for it: {eps}")
    raise SourcePolicyError(
        f"{job}: fanning out over {n_assets} assets against '{source}', which is "
        f"a free source. Bulk access belongs on a paid source "
        f"({', '.join(sorted(PAID_SOURCES))}) — we pay monthly and were using the "
        f"free-shaped endpoints anyway (S-195).{hint}")


class PurposeMismatch(SourcePolicyError):
    """用途和源对不上。**继承 SourcePolicyError,所以现有的处理路径不用改。**"""


def assert_purpose_source(purpose: str, source: str, *, n_assets: int,
                          job: str, explicit_set: bool = False) -> None:
    """按**用途**而不是只按数量来判源 (S-296)。

    数量守卫回答「这么多资产能不能在这个源上取」;这一层回答
    「**这件事本来该在哪个源上做**」。两个问题的答案可以不同 ——
    HL 上取 5 个标的的蜡烛能过数量守卫,但如果那 5 个是拿来画前端的,
    它仍然走错了源。

    >>> assert_purpose_source(MARKET_DATA, "hyperliquid", n_assets=262,
    ...                       job="panel bars")
    Traceback (most recent call last):
    PurposeMismatch: ...

    `explicit_set=True` 是 execution 扇出的**唯一**通行方式:调用方必须
    自己传入成交名单。默认拿场馆挂牌当名单的,正是 S-204 那次。
    """
    want = PURPOSE_PRIMARY.get(purpose)
    if want is None:
        raise PurposeMismatch(
            f"{job}: 未知用途 '{purpose}'。用途必须是 "
            f"{sorted(PURPOSE_PRIMARY)} 之一 —— **说不出用途,就还没想清楚该问谁**")
    if source != want:
        raise PurposeMismatch(
            f"{job}: 用途是 '{purpose}',主源应为 '{want}',实际用了 '{source}'。"
            f"Jazz 2026-09-05:实时数据与前端走 CoinGecko 付费 API,"
            f"接入交易生产的才读 Hyperliquid。"
            f"这个用途的资产集口径:{PURPOSE_SCOPE.get(purpose, '')}")
    if purpose == EXECUTION and n_assets > BULK_THRESHOLD and not explicit_set:
        raise PurposeMismatch(
            f"{job}: 在 execution 用途下扇出 {n_assets} 个标的,而调用方"
            f"**没有显式传入成交名单** —— 这说明名单是从场馆挂牌来的。"
            f"「挂牌」不等于「我们要交易」:{PURPOSE_SCOPE[EXECUTION]}。"
            f"S-204 那次 233 个标的的扇出就是这么来的")
    assert_bulk_source(n_assets, source, job=job)


def bulk_endpoint_for(source: str) -> dict[str, str]:
    """What this source answers in one request. Check before writing a loop."""
    return dict(BULK_ENDPOINTS.get(source, {}))
