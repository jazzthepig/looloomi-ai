"""symbol → coin_id 解析的守卫 (S-303)。

**这里只有一条真正要紧的断言:永不静默取第一个候选。**

CoinGecko 有 ~17,000 个币,ticker 不唯一。选错一个 coin_id,
就是把另一个币的整段价格历史写进我们的标的 —— 而画出来的曲线完全正常,
NAV 完全正常,没有任何东西会报错。这是本仓库能犯的最贵的一类数据错误,
比任何一次采集失败都贵,因为**采集失败是可见的,写错的历史不是**。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.cg_universe import (                    # noqa: E402
    AMBIGUOUS, FROM_DB, FROM_MCAP, FROM_UNIQUE, RESOLVED, UNRESOLVED,
    index_listing, pairs_for_backfill, resolve)

_FAIL: list = []

_LISTING = [
    {"symbol": "btc", "id": "bitcoin"},
    {"symbol": "uni", "id": "uniswap"},
    {"symbol": "uni", "id": "unicorn-scam"},
    {"symbol": "grt", "id": "the-graph"},
    {"symbol": "grt", "id": "golden-ratio-token"},
]


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(label)


def t_a_symbol_collision_is_never_silently_taken() -> None:
    """**本文件的理由。** 撞名且无市值 ⇒ ambiguous,不是「取第一个」。"""
    r = resolve(["GRT"], listing_index=index_listing(_LISTING), mcap={})
    _check("撞名且无市值 → ambiguous", r["ambiguous"] and not r["resolved"],
           str(r["ambiguous"]))
    _check("两个候选都被带出来",
           set(r["ambiguous"][0]["candidates"]) == {"the-graph", "golden-ratio-token"},
           str(r["ambiguous"]))
    # ⚠️ 这一条我第一版写成了 `... or True` —— **一个永远为真的断言**。
    # 整晚在修「常亮的灯等于坏灯」,然后在这个文件里自己点了一盏。
    why = r["ambiguous"][0]["reason"]
    _check("理由点破取第一个候选的后果", "骗子合约" in why, why[:90])


def t_mcap_tiebreak_is_marked_as_a_guess_and_excluded_by_default() -> None:
    """市值裁决**是猜**,而猜和查在 `coin_id` 那一列上完全同形。"""
    r = resolve(["UNI"], listing_index=index_listing(_LISTING),
                mcap={"uniswap": 5.2e9, "unicorn-scam": 1200.0})
    got = r["resolved"][0]
    _check("裁决出的是市值最大的那个", got.coin_id == "uniswap", str(got))
    _check("来源标成 MCAP_TIEBREAK", got.resolved_from == FROM_MCAP, str(got.resolved_from))
    _check("它自己知道还需要价格校验", got.needs_price_check is True)
    _check("默认**不进**回填对", pairs_for_backfill(r) == [],
           str(pairs_for_backfill(r)) + " —— 未经价格校验的猜测不许写 ohlcv_daily")
    _check("显式要求时才进", pairs_for_backfill(r, include_unverified=True)
           == [("UNI", "uniswap")])
    _check("单列计数,不混进 n_resolved 就完事",
           r["n_mcap_tiebreak_unverified"] == 1)


def t_the_free_db_map_is_used_before_any_api_call() -> None:
    """`trending_log` 里已有 258 组,与面板交集 57 个 —— **先花零成本那部分。**"""
    r = resolve(["SOL", "BTC"], known={"SOL": "solana"},
                listing_index=index_listing(_LISTING))
    by = {m.symbol: m for m in r["resolved"]}
    _check("库里已有的标 free_db", by["SOL"].resolved_from == FROM_DB)
    _check("listing 唯一的标 list_unique", by["BTC"].resolved_from == FROM_UNIQUE)
    _check("两个来源可分(可信度不同)",
           by["SOL"].resolved_from != by["BTC"].resolved_from)


def t_unresolved_is_not_the_same_as_no_data() -> None:
    r = resolve(["NOSUCH"], listing_index=index_listing(_LISTING))
    _check("没有候选 → unresolved", r["unresolved"] == ["NOSUCH"], str(r))
    # 同上:第二盏常亮的灯。unresolved 的理由必须真的被读出来检查。
    r2 = resolve(["NOSUCH"], listing_index=index_listing(_LISTING))
    _check("unresolved 的数量与内容都对",
           r2["n_resolved"] == 0 and r2["unresolved"] == ["NOSUCH"], str(r2["reason"])[:80])
    _check("unresolved 显式列出,不静默丢弃", "NOSUCH" in r["unresolved"])


def t_three_verdicts_are_actually_three() -> None:
    """resolved / ambiguous / unresolved 必须真的可分 —— 塌成两个就白建了。"""
    r = resolve(["BTC", "GRT", "NOSUCH"], listing_index=index_listing(_LISTING),
                mcap={})
    _check("三种裁决同时出现",
           bool(r["resolved"]) and bool(r["ambiguous"]) and bool(r["unresolved"]),
           f"resolved={len(r['resolved'])} ambiguous={len(r['ambiguous'])} "
           f"unresolved={len(r['unresolved'])}")
    _check("reason 三个数都报", all(k in r["reason"] for k in ("撞名未决", "未解析")),
           r["reason"][-80:])


def main() -> int:
    print("── symbol → coin_id 解析 (S-303) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("t_")]:
        print(f"\n▸ {fn.__name__}")
        fn()
    print()
    if _FAIL:
        print(f"🔴 {len(_FAIL)} FAILED: {_FAIL}")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
