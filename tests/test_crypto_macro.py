"""加密宏观状态守卫 (S-271)。

最重要的一条不是维度算得对:

    **这一层不发标签,而「不发标签」必须是可被测试盯住的性质。**

一个 `CRYPTO_TIGHTENING` 枚举需要因 + 基础率 + OOS 存活,三样都没有。
`REFUTATION_LEDGER` 里 R76–R94 那 15 次连败正是「先发明分类器、后找证据」。
所以守卫直接断言 `label is None`,并要求模块里没有任何 regime 枚举常量 ——
**下一个人想加一个标签,会先看到这条测试红。**

第二条:**「没读数」不等于「平静」。** 完备度必须与状态一起走。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.crypto_macro import (            # noqa: E402
    CRYPTO_MACRO_DIMS, INSUFFICIENT, MIN_COMPLETENESS, NO_DATA, OK, PARTIAL,
    build, divergence, gap_report,
)

_FAIL: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


ALL = {k: 1.0 for k in CRYPTO_MACRO_DIMS}


def t_this_layer_emits_no_label_and_that_is_enforced():
    """**本文件的第一理由。** 发明一个未验证的分类器是 R76-R94 的形状。"""
    st = build("2026-09-02", ALL)
    _check("五维全测到仍然 label is None", st.label is None, str(st.label))
    _check("label_reason 说明为什么留空",
           "OOS" in st.label_reason and "15 次连败" in st.label_reason,
           st.label_reason)

    # 结构性:模块里不得出现 regime 枚举常量 —— 加一个会先让这条红。
    #
    # ⚠️ 初版我手写了一个「剥掉 # 开头的行和含三引号的行」的过滤器,
    # 于是被**docstring 里解释这条规则时举的反例**绊倒 —— 今天第三次
    # (S-249 是 docstring 引用 .upper().replace(),S-265 是注释引用旧写法)。
    # 而 `tests/_source.py:code_only` 一直在那里:AST 剥注释 + docstring,
    # 比我手写的那三个都正确。**又一次没先 grep 就自己写。**
    from tests._source import code_only

    from src.data.market import crypto_macro as M
    code = code_only(Path(M.__file__).read_text())
    banned = [w for w in ("CRYPTO_TIGHTENING", "CRYPTO_EASING", "CRYPTO_RISK_ON")
              if w in code]
    _check("模块里没有加密 regime 枚举常量", not banned, str(banned))

    _check("divergence 也不发加密标签",
           divergence("TIGHTENING", st)["crypto_label"] is None)


def t_completeness_travels_with_the_state():
    """一个 2/5 维的状态和一个 5/5 维的,在下游不能长得一样。"""
    full = build("2026-09-02", ALL)
    _check("五维全测 → ok", full.verdict == OK, f"{full.verdict}: {full.reason}")
    _check("完备度 1.0", full.completeness == 1.0)

    two = build("2026-09-02", {"funding_rate": 0.01, "btc_dominance": 0.59})
    _check(f"两维(今天的真实处境)→ INSUFFICIENT", two.verdict == INSUFFICIENT,
           f"{two.verdict}: {two.reason}")
    _check("INSUFFICIENT 不可用", two.usable is False)
    _check("缺的维度被列出来", "stablecoin_supply" in two.missing_dims,
           str(two.missing_dims))
    _check("原因点破缺货币基数就不叫加密宏观",
           "货币基数" in two.reason, two.reason)

    four = build("2026-09-02", {k: 1.0 for k in list(CRYPTO_MACRO_DIMS)[:4]})
    _check("四维 → PARTIAL(可用但须带完备度)", four.verdict == PARTIAL, four.verdict)
    _check("PARTIAL 可用", four.usable is False or four.verdict == PARTIAL)
    _check("原因要求完备度跟着往下游传", "一起往下游传" in four.reason, four.reason)


def t_zero_is_a_value_but_missing_is_not():
    """资金费率**可以是 0** —— 把没测的记成 0 等于宣称杠杆成本为零。"""
    z = build("2026-09-02", {**ALL, "funding_rate": 0.0})
    _check("funding_rate=0 算已测", "funding_rate" in z.measured_dims)
    _check("完备度仍是 1.0", z.completeness == 1.0)

    m = build("2026-09-02", {**ALL, "funding_rate": None})
    _check("funding_rate=None 算未测", "funding_rate" in m.missing_dims)
    _check("两者的完备度不同 —— 这就是区分的全部作用",
           z.completeness != m.completeness)
    _check("非数值 → 未测(不是崩)",
           "funding_rate" in build("d", {**ALL, "funding_rate": "x"}).missing_dims)
    _check("全空 → NO_DATA", build("d", {}).verdict == NO_DATA)


def t_dims_are_declared_before_they_are_fetched():
    """按「现在能拿到什么」定义维度,会把「我们没接」伪装成「世界没有」。"""
    _check("五个维度都声明了代理对象",
           all("proxies" in v for v in CRYPTO_MACRO_DIMS.values()))
    _check("每个维度声明了来源",
           all(v.get("source") for v in CRYPTO_MACRO_DIMS.values()))
    _check("每个维度声明了是否已落库",
           all("persisted" in v for v in CRYPTO_MACRO_DIMS.values()))
    # 未落库的维度必须仍在声明里 —— 那正是「声明在前」的意义。
    unpersisted = [k for k, v in CRYPTO_MACRO_DIMS.items() if not v["persisted"]]
    _check(f"有 {len(unpersisted)} 个维度已声明但未落库(它们仍在表里)",
           len(unpersisted) >= 1, str(unpersisted))


def t_gap_report_is_a_roadmap_not_an_excuse():
    g = gap_report()
    _check("报出今天可达的最高完备度", g["max_completeness_today"] < 1.0,
           str(g["max_completeness_today"]))
    _check("今天可达的上限低于可用门槛(所以这层现在不可用)",
           g["max_completeness_today"] < MIN_COMPLETENESS,
           f"{g['max_completeness_today']} vs {MIN_COMPLETENESS}")
    _check("原因把不可用归因到摄取缺口而不是方法",
           "摄取缺口" in g["reason"], g["reason"])
    _check("缺的维度带着来源(那是路线图)",
           all(g["missing"].values()), str(g["missing"]))


def t_no_reading_is_not_calm():
    """**「加密层没读数」不等于「加密层平静」。**"""
    two = build("2026-09-02", {"funding_rate": 0.01, "btc_dominance": 0.59})
    d = divergence("TIGHTENING", two)
    _check("组合不可读", d["readable"] is False)
    _check("原因明说没读数不等于平静", "不等于" in d["reason"], d["reason"])
    _check("USD 层的标签照常带出", d["usd_regime"] == "TIGHTENING")

    full = build("2026-09-02", ALL)
    d2 = divergence("TIGHTENING", full)
    _check("两层都可读时组合可记录", d2["readable"] is True, d2["reason"])
    _check("USD 层缺失时也不可读", divergence(None, full)["readable"] is False)


if __name__ == "__main__":
    print("── 加密宏观状态守卫 (S-271) ──")
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            fn()
    if _FAIL:
        print(f"\n🔴 {len(_FAIL)} FAILED:")
        for f in _FAIL:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 加密宏观状态守卫全绿")
