"""渗透率守卫 (S-267)。

最重要的一条不是算术对不对,是:

    **一个用 ADV 代理算出来的渗透率,和一个用真实市值算出来的,数值上长得一样。**

`data_layer.py:2951` 在取不到真实市值时用 `price × volume × 30` 兜底 ——
对 F 支柱那是合理的(宁可粗糙也别把 mcap 饿成 0 让资产掉到 F),
但拿它做渗透率的分母会得到一个**看起来完全正常而毫无意义**的比例:
分子精确到美元,分母是 30 倍 ADV 的猜测。

所以分母来源走**白名单**而不是黑名单:新增来源必须显式加进来,
而不是「只要不在黑名单里就放行」。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.rwa.penetration import (                 # noqa: E402
    ADV_PROXY, ETF_AUM, FUNDAMENTALS_EQUITY, NO_DENOM, NO_NUMER, OK,
    TRUSTED_DENOMS, UNTRUSTED_DENOM, aggregate, compute, eodhd_ticker,
)

_FAIL: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def t_adv_proxy_denominator_is_refused():
    """**本文件的理由。** 粗估分母 + 精确分子 = 一个正常模样的假比例。"""
    real = compute("nvda", 620e6, 4.2e12, FUNDAMENTALS_EQUITY)
    fake = compute("nvda", 620e6, 4.2e12, ADV_PROXY)

    _check("真实分母 → ok", real.verdict == OK, f"{real.verdict}: {real.reason}")
    _check("ADV 代理分母 → untrusted_denominator", fake.verdict == UNTRUSTED_DENOM,
           f"{fake.verdict}: {fake.reason}")
    _check("被拒时 ratio 是 None,不是照算一个数", fake.ratio is None, str(fake.ratio))
    _check("原因点明它是给 F 支柱用的粗估", "F 支柱" in fake.reason, fake.reason)

    # 判别性:两者的【输入数值完全相同】,只有来源标签不同。
    # 少了 denom_source,这两个调用会给出同一个 1.48 bp。
    _check("同样的数值,只因来源不同而裁决不同(这就是标签的全部作用)",
           real.tokenized_mcap == fake.tokenized_mcap
           and real.underlying_mcap == fake.underlying_mcap
           and real.verdict != fake.verdict)


def t_denominator_sources_are_a_whitelist():
    """白名单,不是黑名单 —— 新来源必须显式获批。"""
    _check("白名单只含两个已核过的来源",
           TRUSTED_DENOMS == {FUNDAMENTALS_EQUITY, ETF_AUM}, str(TRUSTED_DENOMS))
    _check("ADV 代理不在白名单", ADV_PROXY not in TRUSTED_DENOMS)
    novel = compute("x", 1e6, 1e9, "some_new_vendor_2027")
    _check("没见过的来源默认被拒(不是默认放行)",
           novel.verdict == UNTRUSTED_DENOM, novel.verdict)


def t_missing_denominator_is_not_zero_and_not_guessed():
    """未上市标的拿不到流通盘 —— 那是正确结果,不是缺陷。"""
    spacex = compute("spacex", 180e6, None, "unavailable")
    _check("无分母 → no_denominator", spacex.verdict == NO_DENOM, spacex.verdict)
    _check("ratio 是 None", spacex.ratio is None)
    _check("原因明说不要用代理值补", "不要用任何代理值" in spacex.reason, spacex.reason)
    _check("分母为 0 也判 no_denominator(不是除零)",
           compute("x", 1e6, 0, FUNDAMENTALS_EQUITY).verdict == NO_DENOM)
    _check("分子未测 → no_numerator(与无分母分开)",
           compute("x", None, 1e9, FUNDAMENTALS_EQUITY).verdict == NO_NUMER)


def t_the_magnitude_lands_where_the_thesis_says():
    """量级本身是结论的一部分:个位数基点 = 「中小型券商」的定量形式。

    锁住这个量级,不是锁住某个具体数字 —— 如果哪天它跳到百分位,
    那是这件事的性质变了,应该有人来看一眼。
    """
    p = compute("nvda", 620e6, 4.2e12, FUNDAMENTALS_EQUITY)
    _check(f"NVDA 渗透率 {p.bps:.2f} bp —— 个位数基点量级",
           p.bps is not None and 0.1 < p.bps < 100,
           f"{p.bps} bp;若已进入百分位量级,说明性质变了,先看一眼再改这条")
    _check("bps 是 ratio 的 10,000 倍(刻度没搞错)",
           abs(p.bps - p.ratio * 10_000) < 1e-9)


def t_aggregate_sums_numerator_and_denominator_not_ratios():
    """**不能对比率求平均** —— 分母差几个数量级,等权会让小盘股主导。"""
    pens = [
        compute("big", 100e6, 1e12, FUNDAMENTALS_EQUITY),    # 0.1 bp
        compute("small", 50e6, 1e9, FUNDAMENTALS_EQUITY),    # 500 bp
    ]
    a = aggregate(pens)
    naive = (pens[0].ratio + pens[1].ratio) / 2 * 10_000
    _check(f"加总口径 {a['bps']:.2f} bp,而等权平均会是 {naive:.2f} bp",
           a["bps"] is not None and a["bps"] < naive / 10,
           f"{a['bps']} vs {naive} —— 两者若接近说明加权没起作用")
    _check("加总 = 分子和 / 分母和",
           abs(a["ratio"] - 150e6 / (1e12 + 1e9)) < 1e-12, str(a["ratio"]))
    _check("原因写明为什么不对比率平均", "不是对比率求平均" in a["reason"], a["reason"])


def t_coverage_is_by_amount_not_by_count():
    """少一只万亿标的和少一只两千万的,对结论差几个数量级 —— 条数对此沉默。"""
    pens = [
        compute("has", 900e6, 1e12, FUNDAMENTALS_EQUITY),
        compute("miss1", 50e6, None, "unavailable"),
        compute("miss2", 50e6, None, "unavailable"),
    ]
    a = aggregate(pens)
    _check("按条数只有 1/3,按金额覆盖 90%",
           abs(a["coverage"] - 0.9) < 0.01 and a["n_usable"] == 1,
           f"coverage={a['coverage']} n_usable={a['n_usable']}")
    _check("n_usable 与 n_total 都报出来(覆盖率不是唯一读数)",
           a["n_total"] == 3)

    empty = aggregate([compute("x", 1e6, None, "unavailable")])
    _check("一个可算的都没有 → ratio None + 说明去接分母",
           empty["ratio"] is None and "EODHD" in empty["reason"], str(empty))


def t_ticker_mapping_does_not_invent():
    """只做大小写与交易所后缀,不猜映射。"""
    _check("nvda → NVDA.US", eodhd_ticker("nvda") == "NVDA.US", eodhd_ticker("nvda"))
    _check("带空格也处理", eodhd_ticker(" spy ") == "SPY.US")
    _check("交易所可换", eodhd_ticker("bmw", exchange="XETRA") == "BMW.XETRA")
    # 未上市标的会映射成一个查不到的 ticker → 拿不到分母 → no_denominator。
    # **那是正确的结果**:一个未上市公司的「总流通盘」本来就不可比。
    _check("未上市标的照样生成 ticker,由分母缺失来拒绝(不在这里猜)",
           eodhd_ticker("spacex") == "SPACEX.US")


if __name__ == "__main__":
    print("── 渗透率守卫 (S-267) ──")
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            fn()
    if _FAIL:
        print(f"\n🔴 {len(_FAIL)} FAILED:")
        for f in _FAIL:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 渗透率守卫全绿")
