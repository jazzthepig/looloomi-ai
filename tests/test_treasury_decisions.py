"""企业持币决策流的守卫 (S-291)。

这个文件里有两条真正重要的断言:

**① 覆盖率必须两个口径一起报。**
   按家数 57% / **按持仓 88.9%** —— 差 32 个百分点。只看家数会以为覆盖很差,
   只看持仓会以为已经全覆盖。一家持 12 枚而解析不出 id 的公司不重要,
   Strategy 的 845,050 枚重要。

**② 未解析 ≠ 没有数据。** MARA 持 35,303 枚,它的决策史存在,
   只是我们没找到它的 entity_id(`microstrategy` 404、`strategy` 200 —— 改名了)。
   所以未解析的必须**显式列出**,不静默丢弃。

## 这条被失忆了很多次

CG Analyst($139/mo)的 `transaction_history` **page>1 是付费独占** ——
Strategy 完整 119 条回到 2020-08-11。而我 S-290 用免费端点建了快照层,
还写下「历史买不来,今天开始攒」。**那句话对免费档成立,对我们付的这档不成立。**
防复发靠 `tests/test_paid_capability_is_used.py`,不靠这段话。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.entity.collect import (                            # noqa: E402
    FROM_MANUAL, FROM_SLUG, MANUAL_IDS, PAGE_SIZE, RESOLVED, UNRESOLVED,
    candidates, fetch_decisions, parse_decisions, resolve_all,
    rows_for_supabase, slugify,
)

_FAIL: list = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


#: **实测形状**(2026-09-04 CG Analyst 返回)。
LIVE_TX = {"transactions": [
    {"date": 1788134400000, "source_url": "https://.../form-8-k_08-31-2026.pdf",
     "coin_id": "bitcoin", "type": "buy", "holding_net_change": 3081.0,
     "transaction_value_usd": 356900000.0, "holding_balance": 845050.0,
     "average_entry_value_usd": 76057.0},
    {"date": 1597104000000, "source_url": "https://.../8-k-2020.pdf",
     "coin_id": "bitcoin", "type": "buy", "holding_net_change": 21454.0,
     "transaction_value_usd": 250000000.0, "holding_balance": 21454.0,
     "average_entry_value_usd": 11652.0},
]}

#: 实测的公司列表片段 —— 大持仓解析得出、小持仓解析不出,正是真实分布。
LIVE_COS = [
    {"name": "Strategy", "symbol": "MSTR", "total_holdings": 845050},
    {"name": "MARA Holdings", "symbol": "MARA", "total_holdings": 35303},
    {"name": "Metaplanet", "symbol": "3350.T", "total_holdings": 43000},
    {"name": "Hut 8 Mining Corp", "symbol": "HUT", "total_holdings": 13696},
]


def t_coverage_is_reported_in_two_units():
    """**本文件的理由之一。** 家数与持仓是两个问题。"""
    ok_ids = {"strategy", "metaplanet"}
    r = resolve_all(LIVE_COS, lambda cid: cid in ok_ids)
    _check("两个覆盖率都给出",
           "coverage_by_count" in r and "coverage_by_holdings" in r, str(sorted(r)))
    _check(f"按家数 {r['coverage_by_count']:.0%}", r["coverage_by_count"] == 0.5)
    _check(f"按持仓 {r['coverage_by_holdings']:.1%}(明显更高)",
           r["coverage_by_holdings"] > 0.9, str(r["coverage_by_holdings"]))
    _check("两个数不相等(证明没有混为一谈)",
           r["coverage_by_count"] != r["coverage_by_holdings"])
    _check("reason 里两个口径都出现", "按家数" in r["reason"] and "按持仓" in r["reason"],
           r["reason"][:80])


def t_unresolved_is_listed_not_dropped():
    """**理由之二。** MARA 持 35,303 枚 —— 它的数据存在,我们只是没找到 id。"""
    r = resolve_all(LIVE_COS, lambda cid: cid in {"strategy", "metaplanet"})
    names = {u["name"] for u in r["unresolved"]}
    _check("未解析的被列出", names == {"MARA Holdings", "Hut 8 Mining Corp"},
           str(names))
    _check("并带上它们的持仓(说明代价有多大)",
           all(u["holdings"] > 0 for u in r["unresolved"]), str(r["unresolved"]))
    _check("并记录试过哪些候选",
           all(u["tried"] for u in r["unresolved"]), str(r["unresolved"][:1]))
    _check("reason 写明「未解析 ≠ 没有数据」", "不是没有数据" in r["reason"],
           r["reason"][-70:])


def t_manual_ids_win_over_guessing():
    """`microstrategy` 404 / `strategy` 200 —— 改名会让 slug 静默失配。"""
    c = candidates("MicroStrategy", "MSTR")
    _check("手工表排第一", c[0] == ("strategy", FROM_MANUAL), str(c[:2]))
    _check("而 slug 会猜错", slugify("MicroStrategy") == "microstrategy")
    _check("解析来源被记录(猜的和查的可分)",
           {src for _, src in c} >= {FROM_MANUAL, FROM_SLUG}, str(c))
    _check("MANUAL_IDS 里每条都是实测过的实体",
           all(isinstance(v, str) and v for v in MANUAL_IDS.values()))


def t_pagination_stops_on_a_short_page_not_a_page_count():
    """以固定页数为界会把长历史静默截断(S-269 同一条)。"""
    pages = {1: {"transactions": [dict(LIVE_TX["transactions"][0])] * PAGE_SIZE},
             2: {"transactions": [dict(LIVE_TX["transactions"][1])] * 19},
             3: {"transactions": []}}
    calls = {"n": 0}

    async def get(path, params):
        calls["n"] += 1
        return 200, pages.get(params.get("page", 1), {"transactions": []})

    r = asyncio.run(fetch_decisions("strategy", get))
    _check("短页即停(不再翻第 3 页)", r["pages_fetched"] == 2,
           f"翻了 {r['pages_fetched']} 页,调用 {calls['n']} 次")
    _check(f"拿到 {r['n']} 条(100 + 19)", r["n"] == PAGE_SIZE + 19, str(r["n"]))
    _check("回到 2020", r["earliest"] == "2020-08-11", str(r["earliest"]))


def t_a_failed_page_keeps_what_was_already_fetched():
    """**读不到 ≠ 没有** —— 已拿到的不丢,并写明到此为止。"""
    async def get(path, params):
        if params.get("page", 1) == 1:
            return 200, {"transactions": [dict(LIVE_TX["transactions"][0])] * PAGE_SIZE}
        return 429, {}

    r = asyncio.run(fetch_decisions("x", get))
    _check("已拿到的保留", r["n"] == PAGE_SIZE, str(r["n"]))
    _check("note 写明读不到 ≠ 没有", "读不到" in r["note"], r["note"])
    _check("并说明已拿到的不丢", "不丢" in r["note"], r["note"])


def t_each_decision_carries_its_receipt():
    """`source_url` 是它比 VC 融资新闻稿强的地方 —— 有披露义务背书。"""
    ds = parse_decisions("strategy", LIVE_TX)
    _check("解析出 2 条", len(ds) == 2, str(len(ds)))
    _check("每条都有凭证 URL", all(d.source_url for d in ds))
    _check("方向原样保留(不归一不推断)",
           {d.decision_type for d in ds} == {"buy"}, str([d.decision_type for d in ds]))
    _check("日期转成 ISO", ds[1].decision_date == "2020-08-11", ds[1].decision_date)

    rows = rows_for_supabase(ds)
    _check("落库行保留 source_url", all(r["source_url"] for r in rows))
    _check("落库行标注来源为付费档",
           all(r["source"] == "coingecko_analyst" for r in rows))


def main() -> int:
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("t_")]:
        print(f"\n▸ {fn.__name__}")
        fn()
    print("\n" + ("✓ 全部通过" if not _FAIL else f"✗ {len(_FAIL)} 条失败"))
    for f in _FAIL:
        print("   " + f)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
