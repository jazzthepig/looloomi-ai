"""组合层(SPINE 第 7b 段,docs/PORTFOLIO_LAYER_DESIGN.md)—— 灵活组合 T25 的真钱目标表。

## Jazz 10-29 拍板(docs/DECISIONS.md)

- T25 真钱**起始 600 USDC**;权重同纸面 `flex_x1v:T25`(加密 X1V 30 / 股票 30 / 黄金 20 / 现金 20,
  `forward_books.FLEX_X1V_ARMS` 是唯一出处,这里不抄数字)。
- 黄金腿 = **XAUT**;股票腿 = SPYX(xStocks,Solana;T-210,方向采用);现金 = USDC 底仓 + USDY 收益腿。
- **R-v2 风险预算 ≤ 总资本 30%**:落成「R-v2 的名义合计 ≤ 账户净值 × 30%」,**单票风险不变**(账户净值 × 0.5%)。
  另一种读法(R-v2 只按 30% 的钱算净值)实测不可行:2024-06 起 433 张信号票,止损中位 17.7%(2.5 × ATR14),
  按 $189 算单票风险 $0.95 ⇒ 只有 4.4% 的票够得上 HL 最小名义额 $10;按账户净值算 99.5% 都够。
- 再平衡:21 个交易日,或任一腿偏离目标 > 5 个百分点,先到为准。

## 这张表是什么

`portfolio_targets_daily`:每天一份目标(每条腿的权重、美元额度、用什么、在哪、现在能不能执行、为什么)。
**写一次不改**(前向记录的纪律)。执行器今天读的是同一个函数算出的数(`plan_fields`,随 /internal/executor/plan 下发):
- X1V 的记账净值上限 = 加密腿的美元额度(30% × 600 = $180)—— 不加这一条,X1V 开仓时会把整个账户的 USDC 买成 BTC / ETH;
- R-v2 的名义合计上限 = 账户净值 × 30%。

## 还没建的腿

股票 / 黄金 / USDY 要第二个执行器(链上钱包,P3 / P4)。在那之前这几条腿的额度**以 USDC 留在 HL 账户**,
表里 `executable = false` 并写明原因 —— 真钱那条线与纸面 T25 的差距就是实施缺口,照实显示,不挪用。

## 再平衡

额度在开账日按 600 定;再平衡日按真钱快照(`live_account_daily`,P1)重定。偏离带要每条腿的实际权重,
只有一条腿(加密)真在场之前,偏离带只看加密腿。

判活:`select d, sleeve, target_usd, executable from portfolio_targets_daily order by d desc, sleeve limit 6`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

BOOK = "t25_live"
T25_ARM = "T25"
T25_CAPITAL_USD = 600.0            # Jazz 10-29
OPEN_DATE = "2026-10-30"           # 第一份目标(拍板之后的第一个 UTC 日)
RV2_GROSS_CAP_FRAC = 0.30          # Jazz 10-29:R-v2 名义合计 ≤ 账户净值 × 30%;单票风险不变
REBALANCE_TRADING_DAYS = 21
DRIFT_BAND = 0.05
RULE = ("t25_live_v1:Jazz 10-29(起始 600 USDC;权重 = forward_books.FLEX_X1V_ARMS['T25'];XAUT / SPYX / USDC+USDY;"
        "R-v2 名义 ≤ 净值 30%、单票风险不变;21 交易日或偏离 > 5pp 再平衡)")

#: 10-30 15:44 UTC:Jazz 切 EXECUTOR_T25_MODE=live,两条腿当场成交(SPYX 0.23 @ 762.23、XAUT0 0.03 @ 3907.5,sleeve t25_legs_live)。
LEGS_LIVE = True
LEGS_STAGE = "真跑中(东京执行器,10-30 15:44 UTC 建仓)" if LEGS_LIVE else "执行器已接、空跑中(主机 EXECUTOR_T25_MODE=dry_run)"
#: 记账名(= HL 现货代币名)↔ 组合层的腿
LEG_SYMBOLS = {"gold": "XAUT0", "equity": "SPYX"}

#: 每条腿:用什么、在哪、谁执行、现在能不能执行
SLEEVES: dict[str, dict[str, Any]] = {
    "crypto_x1v": {"instrument": "BTC / ETH 现货(X1V 规则决定在场与否;不在场 = 这 30% 是 USDC)",
                   "venue": "Hyperliquid 现货", "executable": True, "why": "东京执行器在跑(X1V)"},
    "equity": {"instrument": "SPYX(Wrapped SP500 xStock)—— 纸面 T25 用 ACWI,真钱用 SPY 作替身",
               "venue": "Hyperliquid 现货 SPYX/USDC(@703)", "executable": LEGS_LIVE,
               "why": "Jazz 10-30:走 HL 现货,与 X1V 同一个账户 / 执行器(T-214);" + LEGS_STAGE},
    "gold": {"instrument": "XAUT0(Tether Gold,omnichain)", "venue": "Hyperliquid 现货 XAUT0/USDC(@182)",
             "executable": LEGS_LIVE,
             "why": "Jazz 10-30:走 HL 现货,与 X1V 同一个账户 / 执行器(T-214);" + LEGS_STAGE},
    "cash": {"instrument": "USDC 底仓 + USDY 收益腿", "venue": "Hyperliquid(USDC)/ 链上(USDY)",
             "executable": True, "why": "USDC 留在 HL 即现金腿;USDY 收益腿未建(收益记 0,与纸面同)"},
}
WRITES_TABLES = ("portfolio_targets_daily",)
WRITES_COLUMNS = {"portfolio_targets_daily": ("d", "book", "sleeve", "kind", "target_w", "target_usd", "capital_usd",
                                              "instrument", "venue", "executable", "why", "next_rebalance_d", "rule")}


def t25_weights() -> dict[str, float]:
    """纸面 T25 的权重(唯一出处 forward_books)+ 现金 = 1 − 其余。"""
    from src.data.universe.forward_books import FLEX_X1V_ARMS
    w, _core = FLEX_X1V_ARMS[T25_ARM]
    out = {"crypto_x1v": float(w["crypto"]), "equity": float(w["equity"]), "gold": float(w["gold"])}
    out["cash"] = round(1.0 - sum(out.values()), 10)
    return out


def next_rebalance(open_d: str, d: str, every: int = REBALANCE_TRADING_DAYS) -> str:
    """开账日起每 `every` 个工作日一次;返回 ≥ d 的下一个再平衡日(开账日当天就是第 0 次)。"""
    from src.data.universe.world50_book import weekdays
    if d <= open_d:
        return open_d
    horizon = (dt.date.fromisoformat(d) + dt.timedelta(days=every * 2 + 7)).isoformat()
    days = weekdays(open_d, horizon)                     # 开账日之后的工作日
    return next(x for x in days[every - 1::every] if x >= d)


def t25_rows(d: str, capital: float = T25_CAPITAL_USD) -> list[dict[str, Any]]:
    """纯函数。一天的目标表行:四条 T25 腿(权重)+ R-v2(名义上限)。"""
    nxt = next_rebalance(OPEN_DATE, d)
    rows = []
    for sleeve, w in t25_weights().items():
        s = SLEEVES[sleeve]
        rows.append({"d": d, "book": BOOK, "sleeve": sleeve, "kind": "weight", "target_w": w,
                     "target_usd": round(w * capital, 2), "capital_usd": capital, "instrument": s["instrument"],
                     "venue": s["venue"], "executable": s["executable"], "why": s["why"],
                     "next_rebalance_d": nxt, "rule": RULE})
    rows.append({"d": d, "book": BOOK, "sleeve": "rv2", "kind": "gross_cap", "target_w": RV2_GROSS_CAP_FRAC,
                 "target_usd": None, "capital_usd": capital,
                 "instrument": "HL 永续单票(R-v2,双向;不在 T25 的 100% 里)", "venue": "Hyperliquid 永续",
                 "executable": True,
                 "why": "名义合计 ≤ 账户净值 × 30%;单票风险 = 账户净值 × 0.5%(不变)",
                 "next_rebalance_d": None, "rule": RULE})
    return rows


def plan_fields(d: Optional[str] = None) -> dict[str, Any]:
    """随执行器计划下发的那几个数(与表同一个函数)。"""
    d = d or dt.datetime.now(dt.timezone.utc).date().isoformat()
    rows = {r["sleeve"]: r for r in t25_rows(d)}
    nxt = rows["crypto_x1v"]["next_rebalance_d"]
    return {"book": BOOK, "d": d, "t25_capital_usd": T25_CAPITAL_USD,
            "x1v_nav_budget_usd": rows["crypto_x1v"]["target_usd"],
            "rv2_gross_cap_frac": RV2_GROSS_CAP_FRAC, "next_rebalance_d": nxt,
            # 黄金 / 股票腿(主机 `exec_host/legs.py`):再平衡日回到目标,其余日子只纠偏离 > 带宽 × 资本的腿
            "t25": {"capital_usd": T25_CAPITAL_USD, "band": DRIFT_BAND, "rebalance_today": nxt == d,
                    "legs": {LEG_SYMBOLS[k]: {"target_usd": rows[k]["target_usd"], "sleeve": k} for k in LEG_SYMBOLS}},
            "rule": RULE}


async def write_today(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    """今天的目标表:已写过就不再写(写一次不改)。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    d = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).date().isoformat()
    if d < OPEN_DATE:
        return {"ok": True, "waiting": f"目标表 {OPEN_DATE} 起", "preview": plan_fields(OPEN_DATE)}
    have = await _read_all("portfolio_targets_daily", {"select": "sleeve", "d": f"eq.{d}", "book": f"eq.{BOOK}"})
    done = {r.get("sleeve") for r in have or []}
    rows = [r for r in t25_rows(d) if r["sleeve"] not in done]
    if not rows:
        return {"ok": True, "d": d, "written": 0, "skipped": "今天的目标已写过"}
    w = await supabase_upsert_table("portfolio_targets_daily", rows, on_conflict="d,book,sleeve")
    if not w:
        return {"ok": False, "d": d, "why": f"写 portfolio_targets_daily 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    return {"ok": True, "d": d, "written": len(rows), "x1v_nav_budget_usd": plan_fields(d)["x1v_nav_budget_usd"]}
