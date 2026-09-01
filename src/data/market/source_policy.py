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
        "plan": "Analyst",                    # $139/月
        "monthly_call_credit": 500_000,
        "measured_on": "2026-09-01",
        "calls_used_at_measurement": 2_074,   # = 0.4%
        # Analyst 解锁文档里标 💼 的全部端点;只差 👑 Enterprise。
        "unlocks_analyst_tier": True,
        "verify": "GET /api/v3/key → {plan, monthly_call_credit, "
                  "current_remaining_monthly_calls}",
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


def bulk_endpoint_for(source: str) -> dict[str, str]:
    """What this source answers in one request. Check before writing a loop."""
    return dict(BULK_ENDPOINTS.get(source, {}))
