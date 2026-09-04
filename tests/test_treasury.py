"""上市公司持币的守卫 (S-290)。

这个文件里只有一条真正重要的断言:

    **`entry_value_usd = 0` 是「未披露」,不是「零成本」。**

实测 2026-09-04:BTC 180 家里 **88 家没披露成本**(MARA / BitMine /
Twenty One / SharpLink…)。把它当零成本,`current/entry` 会变成无穷大,
而那个数会一路走进「抛压强度」的排序里 —— I1:**未测 ≠ 0**。

第二条:**披露率必须与浮盈一起给。** ETH 侧只有 47% 披露 ⇒ 判 `thin`,
因为一个基于不到一半样本的「浮盈中位数」代表的是那一半,不是整体
(与 S-263 `agreement`、S-274 `spread` 同一条)。

## 为什么是这份数据

CG Analyst **没有** VC 融资端点(14 项能力里一项都没有),
DeFiLlama `/raises` 与 `/emissions` 实测 **HTTP 402**(对照组 `/protocols`
200/8179 证明不是网络)。而 `/companies/public_treasury` 免费可用,
且它比 VC 轮次更适合 Entity/Decision 层:**有披露义务背书。**
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.entity.treasury import (                          # noqa: E402
    MIN_DISCLOSED_SHARE, NO_DATA, OK, THIN, Holding, concentration, parse,
    summarise,
)

_FAIL: list = []
D = "2026-09-04"


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


#: **实测形状**(2026-09-04 从 CoinGecko 免费 API 取回)。
#: 用真数据当夹具 —— S-274 那次我编的形状不对,测的就是臆想。
LIVE = {"companies": [
    {"name": "Strategy", "symbol": "MSTR", "country": "US",
     "total_holdings": 845050, "percentage_of_total_supply": 4.023,
     "total_entry_value_usd": 64267830000,
     "total_current_value_usd": 68551123193},
    {"name": "Twenty One Capital", "symbol": "XXI", "country": "US",
     "total_holdings": 43514, "percentage_of_total_supply": 0.207,
     "total_entry_value_usd": 0,                    # ← 未披露
     "total_current_value_usd": 3529890036},
    {"name": "Metaplanet", "symbol": "3350.T", "country": "JP",
     "total_holdings": 43000, "percentage_of_total_supply": 0.205,
     "total_entry_value_usd": 3810765023,
     "total_current_value_usd": 3488193950},
    {"name": "MARA Holdings", "symbol": "MARA", "country": "US",
     "total_holdings": 35303, "percentage_of_total_supply": 0.168,
     "total_entry_value_usd": 0,                    # ← 未披露
     "total_current_value_usd": 2863807233},
]}


def t_zero_entry_value_is_undisclosed_not_free():
    """**本文件的理由。**"""
    hs = parse("bitcoin", LIVE, d=D)
    by = {h.name: h for h in hs}

    xxi = by["Twenty One Capital"]
    _check("成本 0 → entry_value_usd 变成 None", xxi.entry_value_usd is None,
           str(xxi.entry_value_usd))
    _check("浮盈返回 None,**不是 +∞ 也不是 0**",
           xxi.unrealized_multiple is None, str(xxi.unrealized_multiple))
    _check("cost_disclosed 为 False", xxi.cost_disclosed is False)

    # 判别性:披露了成本的必须算得出来,否则这就是「一律不算」
    ms = by["Strategy"]
    _check("披露成本的算得出浮盈", ms.unrealized_multiple is not None)
    _check("Strategy 浮盈 ≈ 1.07x(几乎在成本线上)",
           1.05 < ms.unrealized_multiple < 1.09,
           f"{ms.unrealized_multiple}")
    mp = by["Metaplanet"]
    _check("Metaplanet 在水下(<1.0)", mp.unrealized_multiple < 1.0,
           f"{mp.unrealized_multiple}")


def t_disclosure_share_travels_with_the_multiple():
    """一个基于 50% 样本的「浮盈中位数」和基于 95% 的,不能长得一样。"""
    s = summarise(parse("bitcoin", LIVE, d=D))
    _check("披露与未披露的家数都给出", s["n_cost_disclosed"] == 2
           and s["n_cost_undisclosed"] == 2, str(s))
    _check("披露率 = 0.5", s["disclosed_share"] == 0.5, str(s["disclosed_share"]))
    _check("原因里带上披露率", "披露了成本" in s["reason"], s["reason"][:70])
    _check("原因写明未披露记为 None 不是 0", "不是 0" in s["reason"])

    # 判别性:低于门槛必须判 thin,高于必须判 ok
    low = {"companies": LIVE["companies"][:1] + LIVE["companies"][1:2] * 3}
    s_low = summarise(parse("bitcoin", low, d=D))
    _check(f"披露率 {s_low['disclosed_share']} < {MIN_DISCLOSED_SHARE} → thin",
           s_low["verdict"] == THIN, s_low["verdict"])
    high = {"companies": [LIVE["companies"][0], LIVE["companies"][2]]}
    s_high = summarise(parse("bitcoin", high, d=D))
    _check("全部披露 → ok", s_high["verdict"] == OK, s_high["verdict"])
    _check("两种情况可分", s_low["verdict"] != s_high["verdict"])


def t_concentration_uses_share_of_supply_not_share_of_corporate():
    """按【占企业持仓】算会把「企业总共只有 0.1% 供应」和「有 30%」说成一样集中。"""
    c = concentration(parse("bitcoin", LIVE, d=D))
    _check("点名最大持有者", c["top1_name"] == "Strategy", c["top1_name"])
    _check("同时给出【占企业持仓】与【占总供应】",
           "top1_share_of_corporate" in c and "top1_pct_of_supply" in c,
           str(sorted(c)))
    _check("两个数不相等(证明没有混为一谈)",
           c["top1_share_of_corporate"] != c["top1_pct_of_supply"],
           f"{c['top1_share_of_corporate']} vs {c['top1_pct_of_supply']}")
    _check("HHI 反映高度集中", c["herfindahl"] > 0.5, str(c["herfindahl"]))
    _check("原因写明为什么用占总供应", "占总供应" in c["reason"], c["reason"][:60])


def t_empty_is_not_healthy():
    s = summarise([])
    _check("空 → NO_DATA", s["verdict"] == NO_DATA, s["verdict"])
    _check("原因写明「读不到 ≠ 没有」", "读不到" in s["reason"], s["reason"])
    c = concentration([])
    _check("集中度空 → NO_DATA", c["verdict"] == NO_DATA)


def t_pct_of_supply_is_carried_because_jazz_asked_for_it():
    """Jazz 2026-09-02:「多少比例和资产的发行占总流通盘才更重要」。"""
    hs = parse("bitcoin", LIVE, d=D)
    _check("每一行都带 pct_of_supply",
           all(h.pct_of_supply is not None for h in hs))
    s = summarise(hs)
    _check("面板层汇总占总供应", s["pct_of_supply_total"] > 4.0,
           str(s["pct_of_supply_total"]))
    _check("它出现在 reason 里", "总供应" in s["reason"])


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
